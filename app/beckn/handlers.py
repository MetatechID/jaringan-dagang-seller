"""Business logic handlers for each Beckn action.

Each handler receives the parsed BecknRequest body, performs the business
logic, and returns a BecknResponse-shaped dict that will be POSTed back
to the BAP as an on_* callback.
"""

from __future__ import annotations

import logging
import os
import sys
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.beckn.catalog_builder import BecknCatalogBuilder
from app.config import settings
from app.models.order import Order, OrderStatus
from app.models.product import Product, ProductStatus
from app.models.sku import SKU
from app.models.store import Store
from app.services import catalog_service, inventory_service, order_service, payment_service

# Make the beckn-protocol package importable
_proto_path = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "packages", "beckn-protocol")
)
if _proto_path not in sys.path:
    sys.path.insert(0, _proto_path)

from python import BecknAction, BecknContext, OrderState

logger = logging.getLogger(__name__)


def _callback_context(ctx: dict[str, Any], callback_action: str) -> dict[str, Any]:
    """Build the callback context by flipping the action and adding BPP info."""
    cb_ctx = dict(ctx)
    cb_ctx["action"] = callback_action
    cb_ctx["bpp_id"] = settings.BPP_SUBSCRIBER_ID
    cb_ctx["bpp_uri"] = settings.BPP_SUBSCRIBER_URL
    cb_ctx["timestamp"] = datetime.now(timezone.utc).isoformat()
    return cb_ctx


async def _get_default_store(db: AsyncSession) -> Store | None:
    """Get the first active store (single-store BPP for now)."""
    result = await db.execute(
        select(Store).where(Store.status == "active").limit(1)
    )
    return result.scalar_one_or_none()


# ======================================================================
# handle_search
# ======================================================================

async def handle_search(
    context: dict[str, Any],
    message: dict[str, Any],
    db: AsyncSession,
) -> dict[str, Any]:
    """Search products by intent (keyword, category).

    Returns on_search with catalog.
    """
    intent = message.get("intent", {})
    keyword: str | None = None
    category_beckn_id: str | None = None

    # Extract search keyword from intent.item.descriptor.name
    item_intent = intent.get("item", {})
    descriptor = item_intent.get("descriptor", {})
    keyword = descriptor.get("name")

    # Extract category from intent.category
    cat_intent = intent.get("category", {})
    category_beckn_id = cat_intent.get("id")

    products = await catalog_service.search_products_all_stores(
        db,
        keyword=keyword,
        category_beckn_id=category_beckn_id,
    )

    # Group products by store
    store_map: dict[uuid.UUID, tuple[Store, list[Product]]] = {}
    for product in products:
        sid = product.store_id
        if sid not in store_map:
            store_map[sid] = (product.store, [])
        store_map[sid][1].append(product)

    catalog = BecknCatalogBuilder.build_catalog(
        [(store, prods) for store, prods in store_map.values()]
    )

    return {
        "context": _callback_context(context, "on_search"),
        "message": {"catalog": catalog.model_dump(exclude_none=True)},
    }


# ======================================================================
# handle_select
# ======================================================================

async def handle_select(
    context: dict[str, Any],
    message: dict[str, Any],
    db: AsyncSession,
) -> dict[str, Any]:
    """Validate item availability and price, calculate quote with shipping.

    Returns on_select with order containing quote.
    """
    order_msg = message.get("order", {})
    items_msg = order_msg.get("items", [])

    items_with_qty: list[tuple[SKU, int]] = []
    order_items: list[dict[str, Any]] = []
    errors: list[str] = []

    for item_msg in items_msg:
        item_id = item_msg.get("id")
        qty = item_msg.get("quantity", {}).get("selected", {}).get("count", 1)

        result = await db.execute(
            select(SKU).where(SKU.id == uuid.UUID(item_id))
        )
        sku = result.scalar_one_or_none()

        if sku is None:
            errors.append(f"Item {item_id} not found")
            continue

        if sku.stock < qty:
            errors.append(
                f"Item {item_id} insufficient stock: requested {qty}, available {sku.stock}"
            )
            continue

        items_with_qty.append((sku, qty))
        order_items.append(
            {
                "id": str(sku.id),
                "quantity": {"selected": {"count": qty}},
            }
        )

    if errors:
        return {
            "context": _callback_context(context, "on_select"),
            "error": {
                "type": "DOMAIN-ERROR",
                "code": "40002",
                "message": "; ".join(errors),
            },
        }

    # Estimate shipping (flat rate for now)
    shipping_cost = 15000  # IDR 15,000 default
    quote = BecknCatalogBuilder.build_quote(items_with_qty, shipping_cost)

    provider_msg = order_msg.get("provider", {})

    return {
        "context": _callback_context(context, "on_select"),
        "message": {
            "order": {
                "provider": provider_msg,
                "items": order_items,
                "quote": quote,
                "fulfillments": [
                    {
                        "id": "fulfillment-delivery",
                        "type": "Delivery",
                        "tracking": True,
                    }
                ],
                "payments": [
                    {
                        "id": "payment-prepaid",
                        "type": "PRE-FULFILLMENT",
                        "collected_by": "BPP",
                        "status": "NOT-PAID",
                    }
                ],
            }
        },
    }


# ======================================================================
# handle_init
# ======================================================================

async def handle_init(
    context: dict[str, Any],
    message: dict[str, Any],
    db: AsyncSession,
) -> dict[str, Any]:
    """Create a draft order with billing/shipping info.

    Returns on_init with draft order (no payment triggered yet).
    """
    order_msg = message.get("order", {})
    billing = order_msg.get("billing", {})
    fulfillments = order_msg.get("fulfillments", [])
    items_msg = order_msg.get("items", [])

    shipping_address: dict[str, Any] | None = None
    if fulfillments:
        end = fulfillments[0].get("end", {})
        shipping_address = end.get("location", {}).get("address")

    store = await _get_default_store(db)
    if store is None:
        return {
            "context": _callback_context(context, "on_init"),
            "error": {
                "type": "DOMAIN-ERROR",
                "code": "30001",
                "message": "No active store configured",
            },
        }

    # Re-validate items and calculate total
    items_with_qty: list[tuple[SKU, int]] = []
    for item_msg in items_msg:
        item_id = item_msg.get("id")
        qty = item_msg.get("quantity", {}).get("selected", {}).get("count", 1)
        result = await db.execute(
            select(SKU).where(SKU.id == uuid.UUID(item_id))
        )
        sku = result.scalar_one_or_none()
        if sku:
            items_with_qty.append((sku, qty))

    shipping_cost = 15000
    quote = BecknCatalogBuilder.build_quote(items_with_qty, shipping_cost)
    total = sum(int(s.price) * q for s, q in items_with_qty) + shipping_cost

    order = await order_service.create_order(
        db,
        store.id,
        {
            "beckn_order_id": f"JD-{uuid.uuid4().hex[:12].upper()}",
            "buyer_name": billing.get("name"),
            "buyer_phone": billing.get("phone"),
            "buyer_email": billing.get("email"),
            "billing_address": billing,
            "shipping_address": shipping_address,
            "total": total,
            "items": [
                {"sku_id": str(s.id), "qty": q} for s, q in items_with_qty
            ],
        },
    )

    return {
        "context": _callback_context(context, "on_init"),
        "message": {
            "order": {
                "id": order.beckn_order_id,
                "state": OrderState.CREATED.value,
                "provider": order_msg.get("provider"),
                "items": [
                    {
                        "id": str(s.id),
                        "quantity": {"selected": {"count": q}},
                    }
                    for s, q in items_with_qty
                ],
                "billing": billing,
                "fulfillments": fulfillments,
                "quote": quote,
                "payments": [
                    {
                        "id": "payment-prepaid",
                        "type": "PRE-FULFILLMENT",
                        "collected_by": "BPP",
                        "status": "NOT-PAID",
                    }
                ],
            }
        },
    }


# ======================================================================
# handle_confirm
# ======================================================================

async def handle_confirm(
    context: dict[str, Any],
    message: dict[str, Any],
    db: AsyncSession,
) -> dict[str, Any]:
    """Finalize order and trigger payment.

    Returns on_confirm with order + payment link.
    """
    order_msg = message.get("order", {})
    order_id_str = order_msg.get("id")

    order = await order_service.get_order_by_beckn_id(db, order_id_str)
    if order is None:
        # No prior /init in this transaction — auto-create the order from the
        # /confirm payload. This supports the buyer-initiated flow that
        # previously used the seller_bridge HTTP shortcut.
        store = await _get_default_store(db)
        if store is None:
            return {
                "context": _callback_context(context, "on_confirm"),
                "error": {
                    "type": "DOMAIN-ERROR",
                    "code": "30001",
                    "message": "No active store configured",
                },
            }
        billing = order_msg.get("billing") or {}
        ship_addr = None
        fulfillments = order_msg.get("fulfillments") or []
        if fulfillments:
            ship_addr = (fulfillments[0].get("end") or {}).get("location", {}).get("address")
        items_msg = order_msg.get("items") or []
        # Items may already use the buyer's `{sku_id, qty}` shape OR Beckn's
        # `{id, quantity.selected.count}`. Normalize.
        normalized_items: list[dict] = []
        total_from_items = 0
        for it in items_msg:
            sku_id = it.get("sku_id") or it.get("id")
            qty = it.get("qty")
            if qty is None:
                qty = (it.get("quantity") or {}).get("selected", {}).get("count") or \
                      (it.get("quantity") or {}).get("count") or 1
            normalized_items.append({"sku_id": str(sku_id), "qty": int(qty)})
        try:
            quote_total = int(((order_msg.get("quote") or {}).get("price") or {}).get("value") or 0)
        except (TypeError, ValueError):
            quote_total = 0
        order = await order_service.create_order(
            db, store.id,
            {
                "beckn_order_id": order_id_str or f"JD-{uuid.uuid4().hex[:12].upper()}",
                "buyer_name": billing.get("name") or billing.get("display_name"),
                "buyer_phone": billing.get("phone"),
                "buyer_email": billing.get("email"),
                "billing_address": billing,
                "shipping_address": ship_addr,
                "total": quote_total or total_from_items,
                "items": normalized_items,
            },
        )

    # Race-safe inventory decrement. Uses SELECT ... FOR UPDATE so two
    # concurrent confirms for the last unit cannot both succeed.
    try:
        await inventory_service.decrement_or_raise(db, order.items or [])
        await db.flush()
    except inventory_service.OutOfStock as oos:
        await db.rollback()
        logger.warning("OOS at /confirm for order %s: %s", order.id, oos)
        return {
            "context": _callback_context(context, "on_confirm"),
            "error": {
                "type": "DOMAIN-ERROR",
                "code": "40002",
                "message": f"Out of stock: sku={oos.sku_id} have={oos.available} requested={oos.requested}",
            },
        }

    # Transition to ACCEPTED — set directly to avoid extra ORM round-trips
    # that can trip MissingGreenlet via lazy column refresh in async ctx.
    order.status = OrderStatus.ACCEPTED
    await db.flush()
    await db.refresh(order)  # pull server-defaulted columns (timestamps) cleanly

    # Cache values we'll need in the response *before* any further DB IO that
    # might expire the instance.
    _beckn_id = order.beckn_order_id
    _items = order.items
    _billing = order.billing_address
    _created_at = order.created_at
    _updated_at = order.updated_at
    _total = order.total
    _buyer_email = order.buyer_email
    _order_id = order.id

    # Create Xendit invoice
    payment_record = await payment_service.create_invoice(
        db,
        _order_id,
        _total,
        payer_email=_buyer_email,
        description=f"Order {_beckn_id}",
    )

    return {
        "context": _callback_context(context, "on_confirm"),
        "message": {
            "order": {
                "id": _beckn_id,
                "state": OrderState.ACCEPTED.value,
                "provider": order_msg.get("provider"),
                "items": _items,
                "billing": _billing,
                "fulfillments": [
                    {
                        "id": "fulfillment-delivery",
                        "type": "Delivery",
                        "state": {"descriptor": {"code": "Pending"}},
                        "tracking": True,
                    }
                ],
                "payments": [
                    {
                        "id": str(payment_record.id),
                        "type": "PRE-FULFILLMENT",
                        "collected_by": "BPP",
                        "status": "NOT-PAID",
                        "params": {
                            "transaction_id": payment_record.xendit_invoice_id,
                            "amount": str(payment_record.amount),
                            "currency": "IDR",
                        },
                    }
                ],
                "created_at": _created_at.isoformat() if _created_at else None,
                "updated_at": _updated_at.isoformat() if _updated_at else None,
            }
        },
    }


# ======================================================================
# handle_status
# ======================================================================

async def handle_status(
    context: dict[str, Any],
    message: dict[str, Any],
    db: AsyncSession,
) -> dict[str, Any]:
    """Return current order state."""
    order_id_str = message.get("order_id")
    order = await order_service.get_order_by_beckn_id(db, order_id_str)

    if order is None:
        return {
            "context": _callback_context(context, "on_status"),
            "error": {
                "type": "DOMAIN-ERROR",
                "code": "30004",
                "message": f"Order {order_id_str} not found",
            },
        }

    # Map internal status to Beckn OrderState
    status_map = {
        OrderStatus.CREATED: OrderState.CREATED.value,
        OrderStatus.ACCEPTED: OrderState.ACCEPTED.value,
        OrderStatus.IN_PROGRESS: OrderState.IN_PROGRESS.value,
        OrderStatus.COMPLETED: OrderState.COMPLETED.value,
        OrderStatus.CANCELLED: OrderState.CANCELLED.value,
    }

    fulfillment_info: list[dict[str, Any]] = []
    if order.fulfillment:
        f = order.fulfillment
        fulfillment_info.append(
            {
                "id": str(f.id),
                "type": f.type,
                "state": {"descriptor": {"code": f.status.value}},
                "tracking": bool(f.tracking_url),
            }
        )

    payment_info: list[dict[str, Any]] = []
    if order.payment:
        p = order.payment
        beckn_pay_status = "PAID" if p.status.value == "paid" else "NOT-PAID"
        payment_info.append(
            {
                "id": str(p.id),
                "type": "PRE-FULFILLMENT",
                "collected_by": "BPP",
                "status": beckn_pay_status,
                "params": {
                    "transaction_id": p.xendit_invoice_id,
                    "amount": str(p.amount),
                    "currency": "IDR",
                },
            }
        )

    return {
        "context": _callback_context(context, "on_status"),
        "message": {
            "order": {
                "id": order.beckn_order_id,
                "state": status_map.get(order.status, "Created"),
                "items": order.items,
                "billing": order.billing_address,
                "fulfillments": fulfillment_info or None,
                "payments": payment_info or None,
                "created_at": order.created_at.isoformat() if order.created_at else None,
                "updated_at": order.updated_at.isoformat() if order.updated_at else None,
            }
        },
    }


# ======================================================================
# handle_track
# ======================================================================

async def handle_track(
    context: dict[str, Any],
    message: dict[str, Any],
    db: AsyncSession,
) -> dict[str, Any]:
    """Return fulfillment tracking info."""
    order_id_str = message.get("order_id")
    order = await order_service.get_order_by_beckn_id(db, order_id_str)

    if order is None or order.fulfillment is None:
        return {
            "context": _callback_context(context, "on_track"),
            "error": {
                "type": "DOMAIN-ERROR",
                "code": "30004",
                "message": f"Tracking not available for order {order_id_str}",
            },
        }

    f = order.fulfillment
    return {
        "context": _callback_context(context, "on_track"),
        "message": {
            "tracking": {
                "id": str(f.id),
                "url": f.tracking_url or "",
                "status": f.status.value,
                "location": None,
            }
        },
    }


# ======================================================================
# handle_cancel
# ======================================================================

async def handle_cancel(
    context: dict[str, Any],
    message: dict[str, Any],
    db: AsyncSession,
) -> dict[str, Any]:
    """Cancel an order."""
    order_id_str = message.get("order_id")
    order = await order_service.get_order_by_beckn_id(db, order_id_str)

    if order is None:
        return {
            "context": _callback_context(context, "on_cancel"),
            "error": {
                "type": "DOMAIN-ERROR",
                "code": "30004",
                "message": f"Order {order_id_str} not found",
            },
        }

    try:
        order = await order_service.cancel_order(db, order.id)
    except order_service.InvalidOrderTransition as exc:
        return {
            "context": _callback_context(context, "on_cancel"),
            "error": {
                "type": "DOMAIN-ERROR",
                "code": "30009",
                "message": str(exc),
            },
        }

    return {
        "context": _callback_context(context, "on_cancel"),
        "message": {
            "order": {
                "id": order.beckn_order_id,
                "state": OrderState.CANCELLED.value,
                "cancellation": {
                    "reason": message.get("cancellation_reason_id", ""),
                },
            }
        },
    }


# ======================================================================
# handle_update
# ======================================================================

async def handle_update(
    context: dict[str, Any],
    message: dict[str, Any],
    db: AsyncSession,
) -> dict[str, Any]:
    """Update order (e.g. address change, item substitution, refund request)."""
    order_msg = message.get("order", {})
    order_id_str = order_msg.get("id")
    update_target = message.get("update_target")

    # Refund-request branch: buyer asks for a refund via fulfillment_state
    # descriptor.code = "refund_request".
    fstate = (order_msg.get("fulfillment_state") or {}).get("descriptor") or {}
    if fstate.get("code") == "refund_request":
        from app.services import refund_service
        reason_code = fstate.get("short_desc")
        reason_text = fstate.get("name")
        try:
            amount = int(((order_msg.get("payment") or {}).get("params") or {}).get("amount") or 0)
        except (TypeError, ValueError):
            amount = 0
        req = await refund_service.create_from_beckn_update(
            db,
            order_beckn_id=order_id_str or "",
            reason_code=reason_code,
            reason_text=reason_text,
            requested_amount=amount or None,
        )
        if req is None:
            return {
                "context": _callback_context(context, "on_update"),
                "error": {
                    "type": "DOMAIN-ERROR",
                    "code": "30004",
                    "message": f"Order {order_id_str} not found",
                },
            }
        return {
            "context": _callback_context(context, "on_update"),
            "message": {
                "order": {
                    "id": order_id_str,
                    "tags": [{
                        "code": "refund_pending",
                        "list": [{"code": "refund_request_id", "value": str(req.id)}],
                    }],
                }
            },
        }

    order = await order_service.get_order_by_beckn_id(db, order_id_str)
    if order is None:
        return {
            "context": _callback_context(context, "on_update"),
            "error": {
                "type": "DOMAIN-ERROR",
                "code": "30004",
                "message": f"Order {order_id_str} not found",
            },
        }

    # Apply updates based on target
    if update_target == "billing" and "billing" in order_msg:
        order.billing_address = order_msg["billing"]
    if update_target == "fulfillment" and "fulfillments" in order_msg:
        fulfillments = order_msg["fulfillments"]
        if fulfillments:
            end = fulfillments[0].get("end", {})
            addr = end.get("location", {}).get("address")
            if addr:
                order.shipping_address = addr

    await db.flush()

    return {
        "context": _callback_context(context, "on_update"),
        "message": {
            "order": {
                "id": order.beckn_order_id,
                "state": order.status.value.replace("_", "-").title(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        },
    }


# ======================================================================
# handle_rating
# ======================================================================

async def handle_rating(
    context: dict[str, Any],
    message: dict[str, Any],
    db: AsyncSession,
) -> dict[str, Any]:
    """Record a rating from the buyer."""
    ratings = message.get("ratings", [])
    # In a full implementation we would persist these ratings.
    # For now, acknowledge receipt.
    logger.info("Received %d rating(s)", len(ratings))

    return {
        "context": _callback_context(context, "on_rating"),
        "message": {"feedback_ack": True},
    }


# ======================================================================
# handle_support
# ======================================================================

async def handle_support(
    context: dict[str, Any],
    message: dict[str, Any],
    db: AsyncSession,
) -> dict[str, Any]:
    """Return support contact info."""
    store = await _get_default_store(db)
    return {
        "context": _callback_context(context, "on_support"),
        "message": {
            "phone": "+62-21-000-0000",
            "email": "support@jaringan-dagang.id",
            "uri": "https://jaringan-dagang.id/support",
        },
    }

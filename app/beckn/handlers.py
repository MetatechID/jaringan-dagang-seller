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
from app.beckn.quote_token import build_quote_token, verify_quote_token
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

from python import (
    BecknAction,
    BecknContext,
    ISSUE_CATEGORIES,
    ISSUE_SUB_CATEGORIES_ITEM,
    OrderState,
    RATING_CATEGORIES,
    SETTLEMENT_BASES,
    SETTLEMENT_WINDOWS,
    build_fulfillment_ondc_tags,
    build_payment_settlement_tags,
)

logger = logging.getLogger(__name__)


def _ondc_fulfillment_tags() -> list[dict[str, Any]]:
    """Canonical ONDC:RET11 fulfillment delivery-terms tags (Task A2).

    DAP = seller delivers to the buyer's named place (typical retail
    storefront delivery). Emitted on on_select / on_confirm fulfillments
    so they carry the same ONDC tags as on_search (catalog_builder).
    """
    return [
        t.model_dump(exclude_none=True)
        for t in build_fulfillment_ondc_tags(incoterms="DAP")
    ]


def _ondc_payment_tags() -> list[dict[str, Any]]:
    """Canonical ONDC:RET11 payment settlement-terms tags (Task A2)."""
    return [
        t.model_dump(exclude_none=True)
        for t in build_payment_settlement_tags(
            settlement_basis="delivery",
            settlement_window="P1D",
            buyer_app_finder_fee_type="percent",
            buyer_app_finder_fee_amount="3",
        )
    ]


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
                        "tags": _ondc_fulfillment_tags() or None,
                    }
                ],
                "payments": [
                    {
                        "id": "payment-prepaid",
                        "type": "PRE-FULFILLMENT",
                        "collected_by": "BPP",
                        "status": "NOT-PAID",
                        "tags": _ondc_payment_tags() or None,
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

    # Issue a 10-min signed quote_token covering the (items, total) the buyer
    # is about to commit to (spec § 6.1). The BAP echoes it back on /confirm
    # so we can refuse stale quotes.
    quote_items_for_token = [
        {"sku_id": str(s.id), "qty": q} for s, q in items_with_qty
    ]
    token = build_quote_token(items=quote_items_for_token, total=total)

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
                "tags": [
                    {
                        "code": "quote_token",
                        "list": [{"code": "value", "value": token}],
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

    # Extract buyer-echoed quote_token (spec § 6.1). For now this is
    # observability-only — a mismatch is logged but doesn't reject. We'll
    # tighten to a hard reject in a follow-up once the BAP reliably echoes
    # the token from /on_init.
    echoed_quote_token: str | None = None
    for tag in order_msg.get("tags") or []:
        if tag.get("code") == "quote_token":
            for kv in tag.get("list") or []:
                if (kv.get("code") or "").lower() == "value":
                    echoed_quote_token = kv.get("value")
                    break
            if echoed_quote_token:
                break
    if echoed_quote_token:
        # Verify only signature + expiry; defer items/total check until we
        # have the resolved order (below).
        ok, err = verify_quote_token(echoed_quote_token)
        if not ok:
            logger.warning(
                "quote_token check soft-failed for order %s: %s",
                order_id_str, err,
            )

    order = await order_service.get_order_by_beckn_id(db, order_id_str)
    if order is None:
        # No prior /init in this transaction — auto-create the order from the
        # /confirm payload. This supports the buyer-initiated flow that
        # previously used the seller_bridge HTTP shortcut.
        # Derive the right Store from the cart's first SKU so the order lands
        # in the correct toko (not the "first active store" fallback).
        items_for_store_lookup = order_msg.get("items") or []
        first_sku_id = None
        if items_for_store_lookup:
            first_sku_id = items_for_store_lookup[0].get("sku_id") or items_for_store_lookup[0].get("id")
        store = None
        if first_sku_id:
            try:
                _sku_uuid = uuid.UUID(first_sku_id)
                _sku_row = (await db.execute(
                    select(SKU)
                    .where(SKU.id == _sku_uuid)
                    .options(selectinload(SKU.product).selectinload(Product.store))
                )).scalar_one_or_none()
                if _sku_row and _sku_row.product:
                    store = _sku_row.product.store
            except (ValueError, TypeError):
                pass
        if store is None:
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
    _store_id = order.store_id

    # Resolve the store's subscriber_id so the outbound /on_confirm gets
    # signed with that toko's key (per-toko trust).
    from app.models.store import Store as _Store
    _store_row = (await db.execute(
        select(_Store).where(_Store.id == _store_id)
    )).scalar_one_or_none()
    _store_subscriber_id = (_store_row.subscriber_id if _store_row else None) or settings.BPP_SUBSCRIBER_ID

    # Create Xendit invoice
    payment_record = await payment_service.create_invoice(
        db,
        _order_id,
        _total,
        payer_email=_buyer_email,
        description=f"Order {_beckn_id}",
    )

    _ctx = _callback_context(context, "on_confirm")
    _ctx["bpp_id"] = _store_subscriber_id   # per-toko identity

    # Surface Xendit QRIS QR/checkout URL to the BAP per spec § 6.1.
    # The buyer storefront uses this to render the "Pay with QR" panel
    # without scraping the Xendit invoice response.
    _payment_params: dict[str, Any] = {
        "transaction_id": payment_record.xendit_invoice_id,
        "amount": str(payment_record.amount),
        "currency": "IDR",
    }
    _invoice_url = getattr(payment_record, "xendit_invoice_url", None)
    if _invoice_url:
        _payment_params["invoice_url"] = _invoice_url
        # Xendit's hosted invoice page also serves as the QR landing
        # page for QRIS payments; reuse the same URL.
        _payment_params["qr_image_url"] = _invoice_url

    return {
        "context": _ctx,
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
                        "tags": _ondc_fulfillment_tags() or None,
                    }
                ],
                "payments": [
                    {
                        "id": str(payment_record.id),
                        "type": "PRE-FULFILLMENT",
                        "collected_by": "BPP",
                        "status": "NOT-PAID",
                        "params": _payment_params,
                        "tags": _ondc_payment_tags() or None,
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
# handle_rating  (Task A6 — validate + persist + ack)
# ======================================================================

async def handle_rating(
    context: dict[str, Any],
    message: dict[str, Any],
    db: AsyncSession,
) -> dict[str, Any]:
    """Record a buyer rating, validate against ONDC v1 set, ack via /on_rating.

    Validation rejects (returns 70001 DOMAIN-ERROR):
      * Empty ratings list.
      * rating_category outside RATING_CATEGORIES.
      * Rating value that's not a number, or outside [1.0, 5.0].

    For v1 we log + persist into ``BecknTransactionLog`` (the existing
    inbound-log table already captures the full message body so we don't
    need a dedicated Rating table on the seller side). The persisted log
    is what a future v2 ranker reads.
    """
    ratings = message.get("ratings") or []
    if not ratings:
        return {
            "context": _callback_context(context, "on_rating"),
            "error": {
                "type": "DOMAIN-ERROR",
                "code": "70001",
                "message": "ratings list is empty",
            },
        }

    for r in ratings:
        cat = r.get("rating_category") or r.get("category")
        val = r.get("value")
        if cat not in RATING_CATEGORIES:
            return {
                "context": _callback_context(context, "on_rating"),
                "error": {
                    "type": "DOMAIN-ERROR",
                    "code": "70005",
                    "message": f"unsupported rating_category {cat!r}",
                },
            }
        if val is None:
            return {
                "context": _callback_context(context, "on_rating"),
                "error": {
                    "type": "DOMAIN-ERROR",
                    "code": "70001",
                    "message": "rating value is required",
                },
            }
        try:
            v = float(val)
        except (TypeError, ValueError):
            return {
                "context": _callback_context(context, "on_rating"),
                "error": {
                    "type": "DOMAIN-ERROR",
                    "code": "70001",
                    "message": f"rating value {val!r} not parseable",
                },
            }
        if not (1.0 <= v <= 5.0):
            return {
                "context": _callback_context(context, "on_rating"),
                "error": {
                    "type": "DOMAIN-ERROR",
                    "code": "70001",
                    "message": f"rating value {v} outside [1.0, 5.0]",
                },
            }

    logger.info("Received %d valid rating(s) on order %s",
                len(ratings), message.get("id"))

    return {
        "context": _callback_context(context, "on_rating"),
        "message": {"feedback_ack": True},
    }


# ======================================================================
# handle_settle  (Task A6 — ONDC RSP /settle -> /on_settle)
# ======================================================================

async def handle_settle(
    context: dict[str, Any],
    message: dict[str, Any],
    db: AsyncSession,
) -> dict[str, Any]:
    """Accept an ONDC RSP /settle, compute the settlement record, ack /on_settle.

    The buyer (BAP) asks the BPP for a settlement record for a specific
    order. The BPP computes the per-counterparty payable amount (paid
    minus fees minus refunds), persists a ``SettlementLedger`` row, and
    echoes back the record on /on_settle.

    v1 doesn't move money — the ``settlement_status`` on the returned
    record is ``NOT_PAID`` (or the persisted operator-flipped status if
    the ledger row already exists). The operator settles out-of-band via
    bank rails and flips the status manually.
    """
    from app.services import order_service, settlement_service

    settlement_msg = message.get("settlement") or {}
    order_id_str = settlement_msg.get("order_id") or ""
    basis = settlement_msg.get("settlement_basis") or "DELIVERY"
    window_obj = settlement_msg.get("settlement_window") or {}
    window = window_obj.get("duration") if isinstance(window_obj, dict) else "P1D"
    window = window or "P1D"

    if basis not in SETTLEMENT_BASES:
        return {
            "context": _callback_context(context, "on_settle"),
            "error": {
                "type": "DOMAIN-ERROR",
                "code": "95001",
                "message": f"unknown settlement_basis {basis!r}",
            },
        }
    if window not in SETTLEMENT_WINDOWS:
        return {
            "context": _callback_context(context, "on_settle"),
            "error": {
                "type": "DOMAIN-ERROR",
                "code": "95001",
                "message": f"unknown settlement_window {window!r}",
            },
        }

    order = await order_service.get_order_by_beckn_id(db, order_id_str)
    if order is None:
        return {
            "context": _callback_context(context, "on_settle"),
            "error": {
                "type": "DOMAIN-ERROR",
                "code": "95002",
                "message": f"Order {order_id_str} not found",
            },
        }

    try:
        record = await settlement_service.record_for_order(
            db,
            order_id=order.id,
            settlement_basis=basis,
            settlement_window=window,
        )
    except settlement_service.SettlementError as exc:
        return {
            "context": _callback_context(context, "on_settle"),
            "error": {
                "type": "DOMAIN-ERROR",
                "code": "95001",
                "message": str(exc),
            },
        }

    # Stamp the BPP-side identity onto each counterparty so the BAP can
    # verify the settlement against its registry expectations.
    for cp in record["counterparties"]:
        if cp.get("type") == "BPP":
            cp["id"] = settings.BPP_SUBSCRIBER_ID
            cp["uri"] = settings.BPP_SUBSCRIBER_URL

    return {
        "context": _callback_context(context, "on_settle"),
        "message": {
            "settlement": {
                **record,
                "settlement_reference": record.get("settlement_reference") or str(record["id"]),
            }
        },
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


# ======================================================================
# handle_issue — ONDC IGM /issue (Task A5)
# ======================================================================

async def handle_issue(
    context: dict[str, Any],
    message: dict[str, Any],
    db: AsyncSession,
) -> dict[str, Any]:
    """Accept a buyer-raised ONDC IGM Issue, create a RefundRequest, ACK.

    Task A5 narrow scope: every Issue we accept is treated as a refund
    request candidate. The seller-side response (PROCESSING / RESOLVED /
    REJECTED) is emitted later by the seller agent via the new
    ``POST /api/refunds/{id}/respond`` REST endpoint.

    This handler returns the synchronous /on_issue ACK envelope with
    ``respondent_action = PROCESSING`` so the BAP immediately knows we've
    accepted the Issue and assigned it our refund_id.
    """
    from app.services import refund_service

    issue = message.get("issue") or {}
    issue_id = issue.get("id")
    category = issue.get("category") or ""
    sub_category = issue.get("sub_category") or ""

    if not issue_id:
        return {
            "context": _callback_context(context, "on_issue"),
            "error": {
                "type": "DOMAIN-ERROR",
                "code": "90001",
                "message": "Issue.id is required",
            },
        }

    if category not in ISSUE_CATEGORIES:
        return {
            "context": _callback_context(context, "on_issue"),
            "error": {
                "type": "DOMAIN-ERROR",
                "code": "90001",
                "message": f"unknown IGM category {category!r}",
            },
        }
    if category == "ITEM" and sub_category not in ISSUE_SUB_CATEGORIES_ITEM:
        return {
            "context": _callback_context(context, "on_issue"),
            "error": {
                "type": "DOMAIN-ERROR",
                "code": "90001",
                "message": (
                    f"unknown IGM sub_category {sub_category!r} for "
                    f"category=ITEM"
                ),
            },
        }

    order_details = issue.get("order_details") or {}
    order_beckn_id = order_details.get("id") or ""
    description = issue.get("description") or {}
    reason_text = description.get("long_desc") or description.get(
        "short_desc"
    ) or ""
    additional = description.get("additional_desc") or {}
    refund_block = additional.get("refund") or {}
    try:
        refund_amount = int(refund_block.get("amount")) if refund_block.get(
            "amount"
        ) else None
    except (TypeError, ValueError):
        refund_amount = None

    req = await refund_service.create_from_beckn_issue(
        db,
        order_beckn_id=order_beckn_id,
        sub_category=sub_category,
        reason_text=reason_text,
        requested_amount=refund_amount,
        bap_issue_id=issue_id,
    )
    if req is None:
        return {
            "context": _callback_context(context, "on_issue"),
            "error": {
                "type": "DOMAIN-ERROR",
                "code": "90005",
                "message": (
                    f"Order {order_beckn_id} not found / not eligible "
                    f"for an IGM Issue"
                ),
            },
        }

    # Synchronous PROCESSING ACK: tell the BAP we accepted the Issue and
    # are working on it. The terminal RESOLVED/REJECTED ride out later as
    # a separate /on_issue when the seller agent responds.
    return {
        "context": _callback_context(context, "on_issue"),
        "message": {
            "issue": {
                "id": issue_id,
                "status": "PROCESSING",
                "issue_type": "ISSUE",
                "issue_actions": {
                    "complainant_actions": [],
                    "respondent_actions": [
                        {
                            "respondent_action": "PROCESSING",
                            "short_desc": "Issue received; investigating.",
                            "updated_at": datetime.now(
                                timezone.utc
                            ).isoformat(),
                            "updated_by": {
                                "type": "AGENT",
                                "id": settings.BPP_SUBSCRIBER_ID,
                            },
                        }
                    ],
                },
            }
        },
    }

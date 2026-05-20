"""Bahasa-Indonesia markdown response helpers.

The MCP tools return one ``content[0].text`` blob that is rendered to the
nullclaw LLM as: an Indonesian summary the chatbot will paraphrase to the
customer, followed by a fenced ```json`` block with the structured fields
the model can refer back to in subsequent turns.

Keeping these helpers tiny + pure (no IO, no state) keeps the tools easy
to unit-test (snapshot the markdown string).
"""

from __future__ import annotations

import json
from typing import Any


def format_idr(amount: float | int | str | None) -> str:
    """Format an Indonesian rupiah amount, tolerating None/string/float input."""
    if amount is None or amount == "":
        return "Rp —"
    try:
        n = int(round(float(amount)))
    except (TypeError, ValueError):
        return f"Rp {amount}"
    # Indonesian convention: dot as thousand separator.
    grouped = f"{n:,}".replace(",", ".")
    return f"Rp {grouped}"


def render_tool_response(summary_md: str, data: dict[str, Any]) -> str:
    """Combine the human summary and the JSON block into one text payload."""
    return summary_md.rstrip() + "\n\n```json\n" + json.dumps(
        data, ensure_ascii=False, indent=2, default=str,
    ) + "\n```"


def render_error(message: str, data: dict[str, Any] | None = None) -> str:
    """Standard error envelope: bold leader + optional data block."""
    body = f"**{message}**"
    if data:
        return render_tool_response(body, data)
    return body


# ---------- Per-tool summaries ----------


def summarize_search(results: list[dict[str, Any]]) -> str:
    """Top-5 product list across all stores in the BAP /results payload."""
    if not results:
        return (
            "Hasil pencarian belum tersedia. Coba lagi sebentar atau ubah "
            "kata kunci pencarian."
        )

    flat: list[dict[str, Any]] = []
    for store in results:
        for prod in store.get("products") or []:
            skus = prod.get("skus") or []
            primary_sku = skus[0] if skus else {}
            flat.append(
                {
                    "product_id": prod.get("product_id"),
                    "name": prod.get("name") or "(tanpa nama)",
                    "store": store.get("store_name") or store.get("bpp_id"),
                    "price_idr": primary_sku.get("price_idr"),
                    "stock": primary_sku.get("stock"),
                }
            )

    if not flat:
        return "Belum ada produk yang cocok dengan pencarian. Coba kata kunci lain."

    top = flat[:5]
    lines = [f"Ditemukan {len(flat)} produk. 5 teratas:"]
    for i, p in enumerate(top, 1):
        lines.append(
            f"{i}. **{p['name']}** — {format_idr(p['price_idr'])} "
            f"(stok {p['stock']}) · `{p['product_id']}`"
        )
    return "\n".join(lines)


def summarize_product(product: dict[str, Any]) -> str:
    name = product.get("name") or "(tanpa nama)"
    skus = product.get("skus") or []
    if not skus:
        return f"**{name}** — varian belum tersedia."
    lines = [f"**{name}**"]
    desc = product.get("description")
    if desc:
        lines.append(desc)
    lines.append("")
    lines.append("Varian:")
    for s in skus:
        price = format_idr(s.get("price_idr"))
        lines.append(
            f"- `{s.get('sku_id')}` · {s.get('variant_name') or 'default'} "
            f"{s.get('variant_value') or ''} — {price} · stok {s.get('stock')}"
        )
    return "\n".join(lines).rstrip()


def summarize_cart(cart: dict[str, Any]) -> str:
    items = cart.get("items") or []
    quote = cart.get("quote") or {}
    total = quote.get("total_idr") or quote.get("total") if isinstance(quote, dict) else None
    if items:
        lines = ["**Keranjang belanja:**"]
        for it in items:
            lines.append(
                f"- {it.get('sku_id') or it.get('item_id')} × {it.get('qty', 1)}"
            )
    else:
        lines = ["Keranjang masih kosong."]
    lines.append("")
    lines.append(f"Total sementara: {format_idr(total)}")
    status = cart.get("status")
    if status:
        lines.append(f"Status: `{status}`")
    return "\n".join(lines)


def summarize_checkout(payment: dict[str, Any], order_id: str | None) -> str:
    qr = payment.get("qr_image_url")
    invoice = payment.get("invoice_url")
    expires = payment.get("expires_at")
    lines = ["**Checkout siap. Silakan selesaikan pembayaran:**"]
    if order_id:
        lines.append(f"Nomor order: `{order_id}`")
    if qr:
        lines.append(f"- QR pembayaran: {qr}")
    else:
        lines.append("- QR pembayaran: (sedang dibuat oleh penjual, mohon tunggu)")
    if invoice:
        lines.append(f"- Invoice: {invoice}")
    if expires:
        lines.append(f"- Berlaku sampai: {expires}")
    lines.append("")
    lines.append(
        "Saya akan cek status pembayaran setiap beberapa detik dan beritahu "
        "saat sudah masuk."
    )
    return "\n".join(lines)


def summarize_payment_state(payment_state: str, order_id: str | None) -> str:
    state_id = {
        "pending": "Pembayaran belum masuk — masih menunggu.",
        "paid": "Pembayaran sudah masuk. Pesanan akan diproses penjual.",
        "expired": "Pembayaran kedaluwarsa. Mohon buat pesanan baru.",
        "failed": "Pembayaran gagal. Mohon coba lagi atau hubungi admin.",
    }.get(payment_state, f"Status pembayaran: {payment_state}")
    if order_id:
        return f"{state_id}\nNomor order: `{order_id}`"
    return state_id

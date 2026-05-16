"""Seed any toko catalog from buyer's JSON into seller's Postgres.

Generalises seed-safiyafood.py to support all 4 tokos (and any future ones)
via --slug. Idempotent — re-running skips already-created products.

Usage:
    python3 scripts/seed-from-buyer-catalog.py --slug safiyafood
    python3 scripts/seed-from-buyer-catalog.py --all
    python3 scripts/seed-from-buyer-catalog.py --slug antarestar --api-base http://localhost:8001
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_API_BASE = "http://localhost:8001"
IMAGE_HOST = "https://partner-demos.jaringan-dagang.metatech.id"

CATALOG_DIR = (
    Path(__file__).resolve().parents[1]
    / ".."
    / "jaringan-dagang-buyer"
    / "apps"
    / "beli-aman-bap"
    / "catalog"
)

# Map slug → canonical store metadata. store_id is the seller's local UUID
# (where known). If a slug's store doesn't exist yet, the script falls back
# to looking it up by name via the API.
STORES: dict[str, dict] = {
    "safiyafood": {
        "id": "30b8c0a7-2ed1-4f8f-9a0e-5c2f9a4d72ee",
        "name": "Safiya Food",
        "subscriber_id": "safiyafood.bpp.metatech.id",
        "subscriber_url": "http://localhost:8001/beckn",
    },
    "antarestar": {
        "id": "fc987547-c790-4d91-903d-41c53a18bfc6",
        "name": "Antarestar",
        "subscriber_id": "antarestar.bpp.metatech.id",
        "subscriber_url": "http://localhost:8001/beckn",
    },
    # gendes + yourbrand may not have UUIDs yet — leave id None to auto-create
    "gendes": {
        "id": None,
        "name": "Gendes",
        "subscriber_id": "gendes.bpp.metatech.id",
        "subscriber_url": "http://localhost:8001/beckn",
    },
    "yourbrand": {
        "id": None,
        "name": "YourBrand",
        "subscriber_id": "yourbrand.bpp.metatech.id",
        "subscriber_url": "http://localhost:8001/beckn",
    },
}


def _img(url: str, position: int, is_primary: bool = False) -> dict:
    return {
        "url": f"{IMAGE_HOST}{url}" if url.startswith("/") else url,
        "position": position,
        "is_primary": is_primary,
    }


def _build_payload(p: dict) -> dict:
    images = [_img(p["image"], 0, is_primary=True)] if p.get("image") else []
    for i, g in enumerate(p.get("gallery", []), start=1):
        if g != p.get("image"):
            images.append(_img(g, i))

    skus: list[dict] = []
    for v in p["variants"]:
        sku_images = []
        gallery = v.get("gallery") or ([v["image"]] if v.get("image") else [])
        for i, g in enumerate(gallery):
            sku_images.append(_img(g, i, is_primary=i == 0))
        skus.append({
            "variant_name": v.get("variant_name", "Size"),
            "variant_value": v.get("label") or v.get("variant_value", "Default"),
            "sku_code": v["sku"],
            "price": v.get("price_idr") or v.get("price"),
            "original_price": v.get("compare_at_price_idr") or v.get("original_price"),
            "stock": v.get("stock", 200),
            "weight_grams": v.get("weight_grams"),
            "images": sku_images,
        })

    parent_stem = (
        p["variants"][0]["sku"].rsplit("-", 1)[0] if p.get("variants") else p.get("sku", "")
    )
    return {
        "name": p["name"],
        "description": p.get("description", ""),
        "sku": parent_stem,
        "status": "active",
        "attributes": {
            "tagline": p.get("tagline"),
            "badges": p.get("badges", []),
            "category": p.get("category"),
            "option_axes": p.get("option_axes", []),
        },
        "images": images,
        "skus": skus,
    }


def _http_get(url: str) -> dict | list | None:
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        print(f"  WARN: GET {url} -> {e.code}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"  WARN: GET {url} -> {e}", file=sys.stderr)
        return None


def _http_post(url: str, payload: dict) -> dict | None:
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", "replace")
        print(f"  FAIL POST {url}: {e.code} {err_body[:300]}", file=sys.stderr)
        return None


def ensure_store(api_base: str, slug: str, meta: dict) -> str | None:
    """Look up store by id (if known) else by subscriber_id; auto-create if missing.

    Returns store_id (UUID string) or None on failure.
    """
    # Try the configured ID first
    if meta.get("id"):
        info = _http_get(f"{api_base}/api/stores/{meta['id']}")
        if info and (info.get("data") or info.get("id")):
            return meta["id"]

    # Look up all stores, find by name or subscriber_id
    listing = _http_get(f"{api_base}/api/stores")
    rows = (listing or {}).get("data") or (listing if isinstance(listing, list) else [])
    for s in rows:
        if s.get("subscriber_id") == meta["subscriber_id"] or s.get("name") == meta["name"]:
            return s.get("id")

    # Create
    payload = {
        "name": meta["name"],
        "subscriber_id": meta["subscriber_id"],
        "subscriber_url": meta["subscriber_url"],
        "status": "active",
    }
    out = _http_post(f"{api_base}/api/stores", payload)
    if out:
        sid = (out.get("data") or out).get("id")
        print(f"  created store {meta['name']} -> {sid}")
        return sid
    print(f"  could not ensure store for {slug}", file=sys.stderr)
    return None


def seed_slug(api_base: str, slug: str) -> int:
    """Seed one toko's products. Returns process exit code."""
    catalog_path = CATALOG_DIR / f"{slug}.json"
    if not catalog_path.exists():
        print(f"catalog not found: {catalog_path}", file=sys.stderr)
        return 2
    meta = STORES.get(slug)
    if not meta:
        print(f"unknown slug {slug} — add it to STORES dict", file=sys.stderr)
        return 2

    products = json.loads(catalog_path.read_text(encoding="utf-8")).get("products", [])
    if not products:
        print(f"  no products in {catalog_path.name}")
        return 0

    store_id = ensure_store(api_base, slug, meta)
    if not store_id:
        return 3

    list_url = f"{api_base}/api/products?store_id={store_id}&limit=500"
    create_url = f"{api_base}/api/products?store_id={store_id}"

    existing = _http_get(list_url) or {}
    existing_rows = existing.get("data") or (existing if isinstance(existing, list) else [])
    existing_skus = {p.get("sku") for p in existing_rows if p.get("sku")}
    print(f"  {slug}: {len(existing_rows)} existing products; {len(products)} in catalog")

    created = skipped = 0
    for p in products:
        if not p.get("variants"):
            print(f"  skip {p.get('name')} — no variants", file=sys.stderr)
            continue
        parent_stem = p["variants"][0]["sku"].rsplit("-", 1)[0]
        if parent_stem in existing_skus:
            skipped += 1
            continue
        payload = _build_payload(p)
        out = _http_post(create_url, payload)
        if out is None:
            return 2
        created += 1
    print(f"  {slug}: created={created} skipped={skipped}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api-base", default=DEFAULT_API_BASE)
    ap.add_argument("--slug", action="append", help="repeatable; or use --all")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()

    if args.all:
        slugs = list(STORES.keys())
    elif args.slug:
        slugs = args.slug
    else:
        ap.error("pass --slug X (repeatable) or --all")

    for slug in slugs:
        rc = seed_slug(args.api_base, slug)
        if rc != 0:
            return rc
    return 0


if __name__ == "__main__":
    sys.exit(main())

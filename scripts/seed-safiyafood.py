"""Seed Safiya Food's catalog into the seller dashboard.

Mirrors apps/beli-aman-bap/catalog/safiyafood.json so the seller dashboard
(/products) shows the same products as the buyer storefront, with per-variant
images via the new SKUImage table.

Usage:
    python3 scripts/seed-safiyafood.py [--api-base URL] [--store-id UUID] [--dry-run]

Defaults to the live production API + the Safiyafood store ID seeded into the
production database (or override via flags).
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_API_BASE = "https://jaringan-dagang-seller-api.metatech.id"
DEFAULT_STORE_ID = "30b8c0a7-2ed1-4f8f-9a0e-5c2f9a4d72ee"  # Safiya Food

# Task A7: image URLs are stored as host-agnostic relative paths in the
# seller DB; the catalog builder prepends per-store Store.image_base_url at
# the Beckn emission boundary. No host prefix here — preserve relative
# paths as they come from the buyer catalog JSON. Existing absolute URLs
# in the buyer catalog (if any) pass through verbatim.

CATALOG_PATH = (
    Path(__file__).resolve().parents[1]
    / ".."
    / "jaringan-dagang-buyer"
    / "apps"
    / "beli-aman-bap"
    / "catalog"
    / "safiyafood.json"
)


def _load_catalog() -> list[dict]:
    if not CATALOG_PATH.exists():
        sys.exit(
            f"Catalog file not found at {CATALOG_PATH}.\n"
            "Run sites/partner-demos/public/brands/safiyafood/generate_catalog.py first."
        )
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))["products"]


def _img(url: str, position: int, is_primary: bool = False) -> dict:
    # Task A7: preserve relative paths verbatim. Absolute URLs (if any in
    # the buyer catalog JSON) also pass through; the catalog builder's
    # _resolve_image_url passes absolute URLs through unchanged.
    return {
        "url": url,
        "position": position,
        "is_primary": is_primary,
    }


def _build_payload(p: dict) -> dict:
    images = [_img(p["image"], 0, is_primary=True)]
    for i, g in enumerate(p.get("gallery", []), start=1):
        if g != p["image"]:
            images.append(_img(g, i))

    skus: list[dict] = []
    for v in p["variants"]:
        sku_images = []
        gallery = v.get("gallery") or ([v["image"]] if v.get("image") else [])
        for i, g in enumerate(gallery):
            sku_images.append(_img(g, i, is_primary=i == 0))
        skus.append({
            "variant_name": "Size",
            "variant_value": v["label"],
            "sku_code": v["sku"],
            "price": v["price_idr"],
            "original_price": v.get("compare_at_price_idr"),
            "stock": v.get("stock", 200),
            "weight_grams": v.get("weight_grams"),
            "images": sku_images,
        })

    return {
        "name": p["name"],
        "description": p["description"],
        "sku": p["variants"][0]["sku"].rsplit("-", 1)[0],  # parent SKU stem
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api-base", default=DEFAULT_API_BASE)
    ap.add_argument("--store-id", default=DEFAULT_STORE_ID)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    products = _load_catalog()
    list_url = f"{args.api_base}/api/products?store_id={args.store_id}&limit=200"
    create_url = f"{args.api_base}/api/products?store_id={args.store_id}"

    existing_skus: set[str] = set()
    try:
        with urllib.request.urlopen(list_url, timeout=20) as r:
            existing = json.load(r).get("data", [])
        existing_skus = {p.get("sku") for p in existing if p.get("sku")}
        print(f"Found {len(existing)} existing products in store {args.store_id}")
    except urllib.error.HTTPError as e:
        print(f"WARN: could not list existing products ({e.code})", file=sys.stderr)

    created = skipped = 0
    for p in products:
        parent_sku_stem = p["variants"][0]["sku"].rsplit("-", 1)[0]
        if parent_sku_stem in existing_skus:
            print(f"  skip  {parent_sku_stem}  — already exists")
            skipped += 1
            continue
        payload = _build_payload(p)
        if args.dry_run:
            print(f"  dry   {parent_sku_stem} → would POST {payload['name']} "
                  f"({len(payload['skus'])} variants, {len(payload['images'])} parent imgs)")
            continue
        body = json.dumps(payload).encode()
        req = urllib.request.Request(
            create_url, data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                out = json.load(r)
            print(f"  ok    {parent_sku_stem} → {out['data']['id']} "
                  f"({len(payload['skus'])} variants)")
            created += 1
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", "replace")
            print(f"  FAIL  {parent_sku_stem}: {e.code} {err_body}", file=sys.stderr)
            return 2

    print(f"\nDone. Created {created} product(s), skipped {skipped}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Seed Antarestar's catalog into the seller dashboard.

Mirrors apps/beli-aman-bap/catalog/antarestar.json so the seller dashboard
(/products) shows the same products as the buyer storefront.

Usage:
    python3 scripts/seed-antarestar.py [--api-base URL] [--store-id UUID] [--dry-run]

Defaults to the live production API and the Antarestar store.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

DEFAULT_API_BASE = "https://jaringan-dagang-seller-api.metatech.id"
DEFAULT_STORE_ID = "fc987547-c790-4d91-903d-41c53a18bfc6"
IMAGE_HOST = "https://antarestar.com"

PRODUCTS = [
    {
        "name": "ANTARESTAR Official Jaket Crinkle Valmora",
        "description": (
            "Bahan crinkle ringan dan tahan air. Cocok untuk aktivitas harian, "
            "riding, atau perjalanan singkat. Unisex casual fit."
        ),
        "sku": "ANT-VLM-CRINKLE",
        "status": "active",
        "attributes": {
            "tagline": "Lightweight crinkle windbreaker. Daily wind protection.",
            "options": {
                "size": ["M", "L", "XL", "XXL"],
                "color": ["Navy", "Grey", "Black"],
            },
        },
        "images": [
            "/brands/antarestar/products/valmora-1.svg",
            "/brands/antarestar/products/valmora-2.svg",
            "/brands/antarestar/products/valmora-3.svg",
        ],
        "base_sku": {
            "sku_code": "ANT-VLM-CRINKLE-NAVY-L",
            "price": 425000,
            "original_price": 750000,
            "stock": 120,
            "weight_grams": 480,
        },
    },
    {
        "name": "ANTARESTAR Daypack Everest 25L",
        "description": (
            "Tahan air, padded laptop sleeve hingga 15 inch, kompartemen "
            "organizer untuk EDC. Cocok untuk kerja, kuliah, dan trip."
        ),
        "sku": "ANT-EVEREST-DAYPACK",
        "status": "active",
        "attributes": {
            "tagline": "Compact 25L daypack with laptop sleeve.",
            "options": {"color": ["Black", "Olive", "Navy"]},
        },
        "images": ["/brands/antarestar/products/daypack-1.svg"],
        "base_sku": {
            "sku_code": "ANT-EVEREST-DAYPACK-25L",
            "price": 285000,
            "original_price": 450000,
            "stock": 85,
            "weight_grams": 920,
        },
    },
    {
        "name": "ANTARESTAR Camping Cook Set 2-Person",
        "description": (
            "Set masak camping ringan untuk 2 orang. Stainless food-grade, "
            "lengkap dengan panci, wajan kecil, mangkok, dan peralatan makan."
        ),
        "sku": "ANT-COOK-SET-2P",
        "status": "active",
        "attributes": {"tagline": "Stainless cook set for two."},
        "images": ["/brands/antarestar/products/cookset-1.svg"],
        "base_sku": {
            "sku_code": "ANT-COOK-SET-2P",
            "price": 199000,
            "original_price": 320000,
            "stock": 60,
            "weight_grams": 1100,
        },
    },
]


def _build_payload(p: dict) -> dict:
    return {
        "name": p["name"],
        "description": p["description"],
        "sku": p["sku"],
        "status": p["status"],
        "attributes": p["attributes"],
        "images": [
            {"url": f"{IMAGE_HOST}{path}", "position": i, "is_primary": i == 0}
            for i, path in enumerate(p["images"])
        ],
        "skus": [
            {
                "variant_name": None,
                "variant_value": None,
                "sku_code": p["base_sku"]["sku_code"],
                "price": p["base_sku"]["price"],
                "original_price": p["base_sku"]["original_price"],
                "stock": p["base_sku"]["stock"],
                "weight_grams": p["base_sku"]["weight_grams"],
            }
        ],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api-base", default=DEFAULT_API_BASE)
    ap.add_argument("--store-id", default=DEFAULT_STORE_ID)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    list_url = f"{args.api_base}/api/products?store_id={args.store_id}"
    create_url = f"{args.api_base}/api/products?store_id={args.store_id}"

    # Skip products already present (idempotent on sku)
    existing_skus: set[str] = set()
    try:
        with urllib.request.urlopen(list_url, timeout=15) as r:
            existing = json.load(r).get("data", [])
        existing_skus = {p.get("sku") for p in existing if p.get("sku")}
        print(f"Found {len(existing)} existing products in store {args.store_id}")
    except urllib.error.HTTPError as e:
        print(f"WARN: could not list existing products ({e.code})", file=sys.stderr)

    created = 0
    for p in PRODUCTS:
        if p["sku"] in existing_skus:
            print(f"  skip  {p['sku']} — already exists")
            continue
        payload = _build_payload(p)
        if args.dry_run:
            print(f"  dry   {p['sku']} → would POST {payload['name']}")
            continue
        body = json.dumps(payload).encode()
        req = urllib.request.Request(
            create_url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                out = json.load(r)
            print(f"  ok    {p['sku']} → {out['data']['id']}")
            created += 1
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", "replace")
            print(f"  FAIL  {p['sku']}: {e.code} {err_body}", file=sys.stderr)
            return 2

    print(f"\nDone. Created {created} product(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

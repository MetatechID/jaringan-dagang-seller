"""
Seed script: Import Matchamu products into BPP catalog.
Usage: python scripts/seed-matchamu.py
"""
import asyncio
import sys
import os
import uuid
from decimal import Decimal
from pathlib import Path

# Add paths
sys.path.insert(0, str(Path(__file__).parent.parent / "apps" / "bpp-service"))
sys.path.insert(0, str(Path(__file__).parent.parent / "packages" / "beckn-protocol"))

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://jaringan:jaringan_dev@localhost:5432/jaringan_dagang"
)

# Import models
from app.models.base import Base
from app.models.store import Store
from app.models.product import Product, ProductStatus
from app.models.product_image import ProductImage
from app.models.category import Category
from app.models.sku import SKU

MATCHAMU_STORE = {
    "name": "Matchamu",
    "description": "Dedicated for Taste-Seeker. Premium matcha & powder beverages from Uji, Kyoto Japan. Established 2019, Yogyakarta.",
    "subscriber_id": "matchamu.jaringan-dagang.id",
    "subscriber_url": "http://localhost:8001/beckn",
    "domain": "retail",
    "city": "std:0274",  # Yogyakarta
    "logo_url": "https://matchamu.com/logo.png",
}

CATEGORIES = [
    {"name": "Matcha", "beckn_category_id": "food-beverages-matcha"},
    {"name": "Latte Powder", "beckn_category_id": "food-beverages-latte"},
    {"name": "Tea", "beckn_category_id": "food-beverages-tea"},
    {"name": "Jamu", "beckn_category_id": "food-beverages-jamu"},
    {"name": "Food Service", "beckn_category_id": "food-beverages-foodservice"},
]

# Matchamu retail products from tokopedia.com/matchamu + matchamu.com
PRODUCTS = [
    {
        "name": "Pure Matcha Powder Jar",
        "description": "Premium pure matcha powder dari Uji, Kyoto Jepang. Tanpa campuran pewarna, perasa, atau pengawet. Kaya antioksidan dan catechin, 127x dosis teh hijau biasa. Cocok untuk minuman, baking, dan cooking.",
        "category": "Matcha",
        "skus": [
            {"variant_name": "Size", "variant_value": "50g", "sku_code": "MTCH-PURE-50", "price": 55000, "stock": 200, "weight_grams": 80},
            {"variant_name": "Size", "variant_value": "100g Jar", "sku_code": "MTCH-PURE-100", "price": 101750, "stock": 150, "weight_grams": 150},
            {"variant_name": "Size", "variant_value": "250g", "sku_code": "MTCH-PURE-250", "price": 225000, "stock": 80, "weight_grams": 300},
        ],
        "image_url": "https://images.tokopedia.net/img/cache/500-square/VqbcmM/2024/1/4/pure-matcha-jar.jpg",
        "attributes": {"origin": "Uji, Kyoto, Japan", "type": "Ceremonial Grade", "bpom": "MD registered", "halal": True},
    },
    {
        "name": "Matcha Latte Jar",
        "description": "Matcha latte premium siap seduh. Matcha asli dari Uji, Jepang dengan rasa umami, sedikit pahit, dan aroma green tea yang lembut. Manisnya dari gula aren, creamy dari coconut cream. Gluten-free, tanpa pengawet buatan.",
        "category": "Latte Powder",
        "skus": [
            {"variant_name": "Size", "variant_value": "Jar", "sku_code": "MTCH-LATTE-JAR", "price": 79750, "stock": 200, "weight_grams": 350},
        ],
        "image_url": "https://images.tokopedia.net/img/cache/500-square/VqbcmM/2024/1/4/matcha-latte-jar.jpg",
        "attributes": {"sweetener": "Gula Aren", "dairy_free": True, "halal": True},
    },
    {
        "name": "Matcha Latte Box 20",
        "description": "Matcha latte sachet isi 20 pcs. Praktis untuk sehari-hari. Matcha asli Uji, Jepang. Tinggal seduh dengan air panas atau dingin.",
        "category": "Latte Powder",
        "skus": [
            {"variant_name": "Pack", "variant_value": "Box 20 sachet", "sku_code": "MTCH-LATTE-B20", "price": 101200, "stock": 300, "weight_grams": 500},
        ],
        "image_url": "https://images.tokopedia.net/img/cache/500-square/VqbcmM/2024/1/4/matcha-latte-box20.jpg",
        "attributes": {"sachet_count": 20, "per_sachet_gram": 24, "halal": True},
    },
    {
        "name": "Matcha Latte Box 3",
        "description": "Matcha latte sachet isi 3 pcs. Ukuran trial / hadiah. Matcha asli Uji, Jepang.",
        "category": "Latte Powder",
        "skus": [
            {"variant_name": "Pack", "variant_value": "Box 3 sachet", "sku_code": "MTCH-LATTE-B3", "price": 15620, "stock": 500, "weight_grams": 100},
        ],
        "image_url": "https://images.tokopedia.net/img/cache/500-square/VqbcmM/2024/1/4/matcha-latte-box3.jpg",
        "attributes": {"sachet_count": 3, "per_sachet_gram": 24, "halal": True},
    },
    {
        "name": "Hojicha Latte Box 20",
        "description": "Hojicha latte sachet isi 20 pcs. Hojicha adalah teh hijau Jepang yang di-roast, menghasilkan rasa smoky, nutty, dan karamel. Rendah kafein.",
        "category": "Tea",
        "skus": [
            {"variant_name": "Pack", "variant_value": "Box 20 sachet", "sku_code": "HJCH-LATTE-B20", "price": 101200, "stock": 250, "weight_grams": 500},
        ],
        "image_url": "https://images.tokopedia.net/img/cache/500-square/VqbcmM/2024/1/4/hojicha-latte-box20.jpg",
        "attributes": {"sachet_count": 20, "caffeine": "Low", "halal": True},
    },
    {
        "name": "Hojicha Latte Box 3",
        "description": "Hojicha latte sachet isi 3 pcs. Trial size.",
        "category": "Tea",
        "skus": [
            {"variant_name": "Pack", "variant_value": "Box 3 sachet", "sku_code": "HJCH-LATTE-B3", "price": 15620, "stock": 400, "weight_grams": 100},
        ],
        "image_url": "https://images.tokopedia.net/img/cache/500-square/VqbcmM/2024/1/4/hojicha-latte-box3.jpg",
        "attributes": {"sachet_count": 3, "halal": True},
    },
    {
        "name": "Hojicha Powder",
        "description": "Pure hojicha (roasted green tea) powder dari Jepang. Untuk minuman, baking, dan dessert.",
        "category": "Tea",
        "skus": [
            {"variant_name": "Size", "variant_value": "Box", "sku_code": "HJCH-PURE-BOX", "price": 15620, "stock": 200, "weight_grams": 50},
        ],
        "image_url": "https://images.tokopedia.net/img/cache/500-square/VqbcmM/2024/1/4/hojicha-powder.jpg",
        "attributes": {"origin": "Japan", "halal": True},
    },
    {
        "name": "Sakura Latte Jar",
        "description": "Sakura latte premium. Rasa bunga sakura khas Jepang yang lembut dan wangi. Cocok diseduh panas atau dingin.",
        "category": "Latte Powder",
        "skus": [
            {"variant_name": "Size", "variant_value": "Jar", "sku_code": "SKRA-LATTE-JAR", "price": 90750, "stock": 150, "weight_grams": 350},
        ],
        "image_url": "https://images.tokopedia.net/img/cache/500-square/VqbcmM/2024/1/4/sakura-latte-jar.jpg",
        "attributes": {"flavor": "Sakura (Cherry Blossom)", "halal": True},
    },
    {
        "name": "Taro Latte Jar",
        "description": "Taro latte premium. Rasa ubi ungu yang creamy dan manis alami. Favorit untuk semua umur.",
        "category": "Latte Powder",
        "skus": [
            {"variant_name": "Size", "variant_value": "Jar", "sku_code": "TARO-LATTE-JAR", "price": 68750, "stock": 180, "weight_grams": 350},
        ],
        "image_url": "https://images.tokopedia.net/img/cache/500-square/VqbcmM/2024/1/4/taro-latte-jar.jpg",
        "attributes": {"flavor": "Taro (Ubi Ungu)", "halal": True},
    },
    {
        "name": "Kinako Latte Box 3",
        "description": "Kinako (tepung kedelai panggang) latte sachet isi 3. Rasa nutty dan earthy khas Jepang.",
        "category": "Latte Powder",
        "skus": [
            {"variant_name": "Pack", "variant_value": "Box 3 sachet", "sku_code": "KNKO-LATTE-B3", "price": 15620, "stock": 300, "weight_grams": 100},
        ],
        "image_url": "https://images.tokopedia.net/img/cache/500-square/VqbcmM/2024/1/4/kinako-latte-box3.jpg",
        "attributes": {"flavor": "Kinako (Roasted Soybean)", "halal": True},
    },
    {
        "name": "Black Sesame Latte Box 3",
        "description": "Black sesame latte sachet isi 3. Rasa wijen hitam yang rich dan nutty. Kaya nutrisi.",
        "category": "Latte Powder",
        "skus": [
            {"variant_name": "Pack", "variant_value": "Box 3 sachet", "sku_code": "BSME-LATTE-B3", "price": 15620, "stock": 300, "weight_grams": 100},
        ],
        "image_url": "https://images.tokopedia.net/img/cache/500-square/VqbcmM/2024/1/4/black-sesame-latte-box3.jpg",
        "attributes": {"flavor": "Black Sesame (Wijen Hitam)", "halal": True},
    },
    {
        "name": "Abang Teh Tarik Box 30",
        "description": "Teh tarik sachet isi 30 pcs. Teh tarik ala Malaysia/Singapura yang creamy dan wangi. Best seller Matchamu!",
        "category": "Tea",
        "skus": [
            {"variant_name": "Pack", "variant_value": "Box 30 sachet", "sku_code": "ABTK-B30", "price": 58080, "stock": 400, "weight_grams": 720},
        ],
        "image_url": "https://images.tokopedia.net/img/cache/500-square/VqbcmM/2024/1/4/abang-teh-tarik-box30.jpg",
        "attributes": {"sachet_count": 30, "per_sachet_gram": 24, "halal": True},
    },
    {
        "name": "Abang Teh Tarik",
        "description": "Teh tarik sachet satuan. Teh tarik ala Malaysia/Singapura yang creamy. Cocok untuk trial.",
        "category": "Tea",
        "skus": [
            {"variant_name": "Pack", "variant_value": "1 sachet", "sku_code": "ABTK-1", "price": 12705, "stock": 1000, "weight_grams": 30},
        ],
        "image_url": "https://images.tokopedia.net/img/cache/500-square/VqbcmM/2024/1/4/abang-teh-tarik-single.jpg",
        "attributes": {"sachet_count": 1, "halal": True},
    },
    {
        "name": "Makjamu",
        "description": "Jamu modern sachet. Minuman jamu tradisional Indonesia dengan sentuhan modern. Segar dan menyehatkan.",
        "category": "Jamu",
        "skus": [
            {"variant_name": "Variant", "variant_value": "Original", "sku_code": "MKJM-ORI", "price": 9900, "stock": 500, "weight_grams": 30},
        ],
        "image_url": "https://images.tokopedia.net/img/cache/500-square/VqbcmM/2024/1/4/makjamu-original.jpg",
        "attributes": {"type": "Jamu Modern", "halal": True},
    },
    {
        "name": "Makjamu Glowing Hero",
        "description": "Jamu modern sachet varian Glowing Hero. Untuk kecantikan kulit dari dalam. Dengan kunyit, temulawak, dan bahan alami.",
        "category": "Jamu",
        "skus": [
            {"variant_name": "Variant", "variant_value": "Glowing Hero", "sku_code": "MKJM-GLOW", "price": 9900, "stock": 400, "weight_grams": 30},
        ],
        "image_url": "https://images.tokopedia.net/img/cache/500-square/VqbcmM/2024/1/4/makjamu-glowing.jpg",
        "attributes": {"type": "Jamu Modern - Beauty", "halal": True},
    },
]


async def seed():
    engine = create_async_engine(DATABASE_URL, echo=True)

    # Create tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        # Create store
        store = Store(
            name=MATCHAMU_STORE["name"],
            description=MATCHAMU_STORE["description"],
            subscriber_id=MATCHAMU_STORE["subscriber_id"],
            subscriber_url=MATCHAMU_STORE["subscriber_url"],
            domain=MATCHAMU_STORE["domain"],
            city=MATCHAMU_STORE["city"],
            logo_url=MATCHAMU_STORE["logo_url"],
            status="active",
        )
        session.add(store)
        await session.flush()
        print(f"Created store: {store.name} (id={store.id})")

        # Create categories
        cat_map = {}
        for cat_data in CATEGORIES:
            cat = Category(
                name=cat_data["name"],
                beckn_category_id=cat_data["beckn_category_id"],
            )
            session.add(cat)
            await session.flush()
            cat_map[cat_data["name"]] = cat
            print(f"  Created category: {cat.name} (id={cat.id})")

        # Create products with SKUs and images
        for prod_data in PRODUCTS:
            cat = cat_map[prod_data["category"]]
            product = Product(
                store_id=store.id,
                name=prod_data["name"],
                description=prod_data["description"],
                category_id=cat.id,
                status=ProductStatus.ACTIVE,
                attributes=prod_data.get("attributes", {}),
            )
            session.add(product)
            await session.flush()

            # Create image
            image = ProductImage(
                product_id=product.id,
                url=prod_data["image_url"],
                position=0,
                is_primary=True,
            )
            session.add(image)

            # Create SKUs
            for sku_data in prod_data["skus"]:
                sku = SKU(
                    product_id=product.id,
                    variant_name=sku_data["variant_name"],
                    variant_value=sku_data["variant_value"],
                    sku_code=sku_data["sku_code"],
                    price=Decimal(str(sku_data["price"])),
                    stock=sku_data["stock"],
                    weight_grams=sku_data["weight_grams"],
                )
                session.add(sku)

            await session.flush()
            sku_info = ", ".join(
                f'{s["variant_value"]} @ Rp{s["price"]:,}'
                for s in prod_data["skus"]
            )
            print(f"  Created product: {product.name} [{sku_info}]")

        await session.commit()
        print(f"\nDone! Seeded {len(PRODUCTS)} products with SKUs into store '{store.name}'")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())

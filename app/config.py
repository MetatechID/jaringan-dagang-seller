"""Application configuration loaded from environment variables."""

from typing import List, Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """BPP service configuration.

    All values can be overridden via environment variables or a .env file.
    """

    # --- Application ---
    APP_NAME: str = "Jaringan Dagang BPP"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = True
    HOST: str = "0.0.0.0"
    PORT: int = 8001

    # --- Database ---
    DATABASE_URL: str = (
        "postgresql+asyncpg://jaringan:jaringan_dev@localhost:5433/jaringan_dagang"
    )

    # --- Redis ---
    REDIS_URL: str = "redis://localhost:6379/0"

    # --- CORS ---
    ALLOWED_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://localhost:3001",
        "http://localhost:3002",
        "http://localhost:3003",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3002",
        "https://jaringan-dagang-seller.metatech.id",
        "https://jaringan-dagang-buyer.metatech.id",
        "https://jaringan-dagang.metatech.id",
        "https://beli-aman.metatech.id",
    ]

    # --- Beli Aman bridge ---
    # Shared secret with the Beli Aman BAP. The BAP POSTs new escrow orders to
    # /api/internal/escrow-orders with this token in X-Internal-Token. NEVER commit.
    BELI_AMAN_INTERNAL_TOKEN: str = "dev-seller-bridge-token"

    # --- Beckn Network ---
    # Canonical subscriber_id scheme (Task A3): ``*.jaringan-dagang.id``.
    # Per-store BPPs identify as ``<slug>.jaringan-dagang.id``
    # (Store.subscriber_id in the DB is authoritative). The value below is
    # the single-tenant fallback used when the seller process needs to
    # identify itself without a per-store signer.
    REGISTRY_URL: Optional[str] = "http://localhost:3030"
    GATEWAY_URL: Optional[str] = "http://localhost:4030"
    BPP_SUBSCRIBER_ID: str = "bpp.jaringan-dagang.id"
    BPP_SUBSCRIBER_URL: str = "http://localhost:8001"
    BPP_UNIQUE_KEY_ID: str = "k1"
    # Path (relative to repo root or absolute) to the BPP's Ed25519 private key
    # (base64 raw seed). Used to sign /on_* callbacks.
    BPP_SIGNING_KEY_PATH: str = "dev/keys/seller.private.b64"
    # Beli Aman BAP default — used if registry lookup fails or before lookup.
    # Canonical BAP id (Task A3); the deployed BAP runs at
    # api.beli-aman.metatech.id but its network identity is the canonical
    # value below.
    BELI_AMAN_BAP_URL: str = "http://localhost:8003/api/v1/beckn"
    BELI_AMAN_BAP_ID: str = "beli-aman.bap.jaringan-dagang.id"
    # Beckn transport base for the ONDC:RET (retail) family. The ONDC
    # domain *code* emitted in the context (e.g. ONDC:RET11 for Safiya) is
    # resolved per-store by python.domain_resolver.resolve_ondc_domain;
    # this stays the underlying spec-level base, unchanged by that layer.
    BECKN_DOMAIN: str = "nic2004:52110"
    BECKN_CORE_VERSION: str = "1.1.0"  # Beckn core spec version (distinct from ONDC domain code)
    BECKN_CITY_CODE: str = "std:021"  # Jakarta — canonical code from network-extension/cities.yaml
    BECKN_COUNTRY_CODE: str = "IDN"

    # --- Xendit Payment Gateway ---
    XENDIT_SECRET_KEY: Optional[str] = None
    XENDIT_WEBHOOK_TOKEN: Optional[str] = None
    XENDIT_API_BASE: str = "https://api.xendit.co"

    # --- Biteship Shipping ---
    BITESHIP_API_KEY: Optional[str] = None
    BITESHIP_API_BASE: str = "https://api.biteship.com/v1"

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


settings = Settings()

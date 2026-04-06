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
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3002",
        "https://jaringan-dagang-seller.metatech.id",
        "https://jaringan-dagang-buyer.metatech.id",
        "https://jaringan-dagang.metatech.id",
    ]

    # --- Beckn Network ---
    REGISTRY_URL: Optional[str] = "http://localhost:3030"
    GATEWAY_URL: Optional[str] = "http://localhost:4030"
    BPP_SUBSCRIBER_ID: str = "bpp.jaringan-dagang.local"
    BPP_SUBSCRIBER_URL: str = "http://localhost:8001"
    BPP_UNIQUE_KEY_ID: str = "key-1"
    BECKN_DOMAIN: str = "nic2004:52110"
    BECKN_CORE_VERSION: str = "1.1.0"
    BECKN_CITY_CODE: str = "ID:JKT"
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

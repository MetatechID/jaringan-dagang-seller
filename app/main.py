"""BPP service entrypoint.

FastAPI application with lifespan that:
  - Initialises the async DB engine.
  - Registers with the Beckn registry on startup (if REGISTRY_URL is set).
  - Mounts all routers (Beckn protocol + internal REST).
"""

from __future__ import annotations

import logging
import os
import sys
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import engine

# Make the beckn-protocol package importable
_proto_path = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "packages", "beckn-protocol")
)
if _proto_path not in sys.path:
    sys.path.insert(0, _proto_path)

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Registry self-registration
# ------------------------------------------------------------------

async def _register_with_registry() -> None:
    """Register this BPP with the Beckn registry (best-effort)."""
    if not settings.REGISTRY_URL:
        logger.info("REGISTRY_URL not set; skipping registry registration")
        return

    payload: dict[str, Any] = {
        "subscriber_id": settings.BPP_SUBSCRIBER_ID,
        "subscriber_url": settings.BPP_SUBSCRIBER_URL,
        "type": "BPP",
        "domain": settings.BECKN_DOMAIN,
        "city": settings.BECKN_CITY_CODE,
        "country": settings.BECKN_COUNTRY_CODE,
        "status": "SUBSCRIBED",
    }

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{settings.REGISTRY_URL}/subscribers",
                json=payload,
                timeout=10.0,
            )
            if resp.status_code < 300:
                logger.info(
                    "Registered with Beckn registry at %s", settings.REGISTRY_URL
                )
            else:
                logger.warning(
                    "Registry registration returned %s: %s",
                    resp.status_code,
                    resp.text[:200],
                )
    except Exception:
        logger.warning(
            "Could not register with Beckn registry at %s (is it running?)",
            settings.REGISTRY_URL,
            exc_info=True,
        )


# ------------------------------------------------------------------
# Lifespan
# ------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: DB init + registry registration.  Shutdown: dispose engine."""
    logger.info("Starting %s v%s", settings.APP_NAME, settings.APP_VERSION)

    # Optionally create tables (use Alembic in production)
    from app.models import Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    await _register_with_registry()

    yield

    await engine.dispose()
    logger.info("Shutdown complete")


# ------------------------------------------------------------------
# App factory
# ------------------------------------------------------------------

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ------------------------------------------------------------------
# Mount routers
# ------------------------------------------------------------------

from app.beckn.endpoints import router as beckn_router  # noqa: E402
from app.api.products import router as products_router  # noqa: E402
from app.api.orders import router as orders_router  # noqa: E402
from app.api.store import router as store_router  # noqa: E402

# Beckn protocol endpoints under /beckn/ (e.g. POST /beckn/search, POST /beckn/confirm)
app.include_router(beckn_router, prefix="/beckn")

# Internal seller dashboard API under /api/
app.include_router(products_router, prefix="/api")
app.include_router(orders_router, prefix="/api")
app.include_router(store_router, prefix="/api")


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok", "service": settings.APP_NAME}

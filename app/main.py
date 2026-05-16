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
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import engine

# Make the beckn-protocol package importable
_proto_path = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "packages", "beckn-protocol")
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

    # Schema is owned by Alembic. Local dev can run `alembic upgrade head` or
    # set CREATE_TABLES_ON_STARTUP=1 to recreate; serverless cold starts must
    # not pay for a metadata round-trip on every container boot.
    if os.getenv("CREATE_TABLES_ON_STARTUP") == "1":
        try:
            from app.models import Base
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
        except Exception:
            logger.warning("Could not connect to database (skipping table creation)", exc_info=True)

    await _register_with_registry()

    yield

    try:
        await engine.dispose()
    except Exception:
        pass
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


# Browser cache for read-only seller dashboard endpoints. Per-seller data, so
# `private`. SWR lets the page paint instantly while a background fetch refreshes.
_CACHEABLE_PREFIXES = (
    "/api/orders",
    "/api/customers",
    "/api/insights",
    "/api/products",
    "/api/store",
    "/api/stores",
)


@app.middleware("http")
async def _cache_control(request: Request, call_next):
    response = await call_next(request)
    if request.method == "GET" and any(
        request.url.path.startswith(p) for p in _CACHEABLE_PREFIXES
    ):
        response.headers.setdefault(
            "Cache-Control",
            "private, max-age=15, stale-while-revalidate=120",
        )
    return response


# ------------------------------------------------------------------
# Mount routers
# ------------------------------------------------------------------

from app.beckn.endpoints import router as beckn_router  # noqa: E402
from app.api.products import router as products_router  # noqa: E402
from app.api.orders import router as orders_router  # noqa: E402
from app.api.store import router as store_router  # noqa: E402
from app.api.store import stores_router  # noqa: E402
from app.api.escrow_orders import router as escrow_orders_router  # noqa: E402
from app.api.customers import router as customers_router  # noqa: E402
from app.api.insights import router as insights_router  # noqa: E402
from app.api.webhooks import router as webhooks_router  # noqa: E402
from app.api.refunds import router as refunds_router  # noqa: E402
from app.api.admin import router as admin_router  # noqa: E402

# Beckn protocol endpoints under /beckn/ (e.g. POST /beckn/search, POST /beckn/confirm)
app.include_router(beckn_router, prefix="/beckn")

# Internal seller dashboard API under /api/
app.include_router(products_router, prefix="/api")
app.include_router(orders_router, prefix="/api")
app.include_router(store_router, prefix="/api")
app.include_router(stores_router, prefix="/api")
app.include_router(customers_router, prefix="/api")
app.include_router(insights_router, prefix="/api")
app.include_router(refunds_router, prefix="/api")
app.include_router(admin_router, prefix="/api")

# Beli Aman bridge: BAP POSTs escrow orders to /api/internal/escrow-orders
app.include_router(escrow_orders_router, prefix="/api")

# External webhook receivers (Biteship, Xendit) — mounted at /webhooks/*
app.include_router(webhooks_router)


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok", "service": settings.APP_NAME}

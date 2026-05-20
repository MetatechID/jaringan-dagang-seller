"""Thin async wrapper over the Beli Aman BAP's bot REST surface.

The BAP exposes 8 endpoints under ``/api/v1/{search,cart,checkout}/*`` behind
a static ``Authorization: Bearer <BOT_API_TOKEN>`` guard (see B3a). The MCP
server is the only known caller today; nullclaw → MCP → BAP → Beckn.

This module is intentionally a *single class* with one method per endpoint.
No retries, no circuit breakers, no caching — the calling tool decides
policy. A single ``httpx.AsyncClient`` is reused for connection pooling.

Error model
-----------
- HTTP 4xx/5xx raise ``BAPHTTPError(status_code, body)`` — the tool layer
  then maps to Indonesian copy + ``isError: true`` in the MCP envelope.
- ``httpx.RequestError`` / timeout raises ``BAPTransportError(message)``.
- 2xx returns the parsed JSON body (a ``dict``).
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class BAPError(Exception):
    """Base for all BAP-client errors."""


class BAPHTTPError(BAPError):
    """The BAP returned a non-2xx status."""

    def __init__(self, status_code: int, body: Any) -> None:
        self.status_code = status_code
        self.body = body
        super().__init__(f"BAP returned HTTP {status_code}: {body!r}")


class BAPTransportError(BAPError):
    """The BAP could not be reached (DNS, refused, timeout, etc.)."""


class BAPClient:
    """One-shot async client. Construct in app lifespan; close on shutdown."""

    def __init__(
        self,
        base_url: str,
        token: str,
        timeout_sec: float = 15.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._timeout = timeout_sec
        # Allow injection for tests (httpx.MockTransport-backed clients).
        self._client = client or httpx.AsyncClient(timeout=timeout_sec)
        self._owns_client = client is None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    # ---------- Internals ----------

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        try:
            resp = await self._client.request(
                method, url, json=json, headers=self._headers(),
                timeout=self._timeout,
            )
        except httpx.TimeoutException as exc:
            raise BAPTransportError(f"timeout calling {method} {path}: {exc}") from exc
        except httpx.RequestError as exc:
            raise BAPTransportError(
                f"transport error calling {method} {path}: {exc}"
            ) from exc

        if resp.status_code >= 400:
            try:
                body: Any = resp.json()
            except Exception:
                body = resp.text
            raise BAPHTTPError(resp.status_code, body)

        try:
            return resp.json()
        except Exception as exc:
            raise BAPTransportError(
                f"BAP returned non-JSON body for {method} {path}: {exc}"
            ) from exc

    # ---------- Endpoints ----------

    async def search(
        self,
        *,
        query: str,
        category: str | None = None,
        city: str | None = None,
        bpp_id: str | None = None,
        bpp_uri: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"query": query}
        if category:
            body["category"] = category
        if city:
            body["city"] = city
        if bpp_id:
            body["bpp_id"] = bpp_id
        if bpp_uri:
            body["bpp_uri"] = bpp_uri
        return await self._request("POST", "/api/v1/search", json=body)

    async def get_search_results(self, session_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/api/v1/search/{session_id}/results")

    async def cart_select(
        self,
        *,
        session_id: str | None,
        bpp_id: str,
        bpp_uri: str | None,
        provider_id: str | None,
        items: list[dict[str, Any]],
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"bpp_id": bpp_id, "items": items}
        if session_id:
            body["session_id"] = session_id
        if bpp_uri:
            body["bpp_uri"] = bpp_uri
        if provider_id:
            body["provider_id"] = provider_id
        return await self._request("POST", "/api/v1/cart/select", json=body)

    async def get_cart(self, cart_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/api/v1/cart/{cart_id}")

    async def cart_init(
        self,
        cart_id: str,
        *,
        billing: dict[str, Any],
        shipping: dict[str, Any],
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/api/v1/cart/{cart_id}/init",
            json={"billing": billing, "shipping": shipping},
        )

    async def confirm(
        self,
        cart_id: str,
        *,
        quote_token: str | None = None,
        payment_proof: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if quote_token is not None:
            body["quote_token"] = quote_token
        if payment_proof is not None:
            body["payment_proof"] = payment_proof
        return await self._request(
            "POST", f"/api/v1/checkout/{cart_id}/confirm", json=body
        )

    async def checkout_status(self, cart_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/api/v1/checkout/{cart_id}/status")


def build_default_client() -> BAPClient:
    """Read env vars and construct the singleton client used by main.py."""
    base = os.environ.get("BAP_BASE_URL", "http://localhost:8003")
    token = os.environ.get("BOT_API_TOKEN", "")
    if not token:
        logger.warning(
            "BOT_API_TOKEN is not set; all BAP calls will be rejected by the "
            "BAP's require_bot guard with 401. Set BOT_API_TOKEN in env."
        )
    timeout = float(os.environ.get("BAP_TIMEOUT_SEC", "15"))
    return BAPClient(base_url=base, token=token, timeout_sec=timeout)

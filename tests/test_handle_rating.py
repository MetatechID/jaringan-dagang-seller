"""Task A6 — Beckn /rating handler.

The handler:
  1. Validates the ratings list (empty -> 70001).
  2. Validates rating_category in RATING_CATEGORIES (else 70005).
  3. Validates value parseable + in [1.0, 5.0] (else 70001).
  4. Returns feedback_ack=true otherwise.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PROTO = os.path.join(_ROOT, "packages", "beckn-protocol")
for _p in (_ROOT, _PROTO):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pytest  # noqa: E402

from app.beckn import handlers  # noqa: E402


def _ctx(action="rating"):
    return {
        "action": action,
        "bap_id": "beli-aman.bap.jaringan-dagang.id",
        "bap_uri": "http://b",
        "bpp_id": "bpp.jaringan-dagang.id",
        "bpp_uri": "http://s",
        "transaction_id": str(uuid.uuid4()),
        "message_id": str(uuid.uuid4()),
        "timestamp": "2026-05-20T00:00:00Z",
    }


class _StubDB:
    async def commit(self):
        return None


class TestHandleRating:
    def test_empty_ratings_returns_70001(self):
        async def run():
            return await handlers.handle_rating(
                _ctx(), {"id": "JD-1", "ratings": []}, _StubDB()
            )
        out = asyncio.run(run())
        assert out["error"]["code"] == "70001"

    def test_unknown_category_returns_70005(self):
        async def run():
            return await handlers.handle_rating(
                _ctx(),
                {"id": "JD-1", "ratings": [
                    {"rating_category": "SuperFan", "value": "5"},
                ]},
                _StubDB(),
            )
        out = asyncio.run(run())
        assert out["error"]["code"] == "70005"

    def test_out_of_range_returns_70001(self):
        async def run():
            return await handlers.handle_rating(
                _ctx(),
                {"id": "JD-1", "ratings": [
                    {"rating_category": "Provider", "value": "9"},
                ]},
                _StubDB(),
            )
        out = asyncio.run(run())
        assert out["error"]["code"] == "70001"

    def test_unparseable_value_returns_70001(self):
        async def run():
            return await handlers.handle_rating(
                _ctx(),
                {"id": "JD-1", "ratings": [
                    {"rating_category": "Item", "value": "five"},
                ]},
                _StubDB(),
            )
        out = asyncio.run(run())
        assert out["error"]["code"] == "70001"

    def test_happy_path_acks(self):
        async def run():
            return await handlers.handle_rating(
                _ctx(),
                {"id": "JD-1", "ratings": [
                    {"rating_category": "Provider", "value": "5"},
                    {"rating_category": "Item", "value": "4.5", "id": "SKU-1"},
                ]},
                _StubDB(),
            )
        out = asyncio.run(run())
        assert out["message"]["feedback_ack"] is True
        assert out["context"]["action"] == "on_rating"

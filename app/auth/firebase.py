"""Firebase Admin SDK init + ID-token verification for the seller dashboard.

Uses the same Firebase project as the Beli Aman BAP (env FIREBASE_SERVICE_ACCOUNT_JSON).
Lazy-initialized so Vercel cold-starts don't pay the init cost on every request.
"""

from __future__ import annotations

import json
import logging
import os
from functools import lru_cache
from typing import Any

import firebase_admin
from firebase_admin import auth as fb_auth, credentials

logger = logging.getLogger(__name__)

_APP_NAME = "jaringan-dagang-seller"


@lru_cache(maxsize=1)
def get_firebase_app() -> firebase_admin.App:
    """Initialize firebase_admin once and reuse the App across calls."""
    cred_json = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON", "")
    if not cred_json:
        raise RuntimeError(
            "FIREBASE_SERVICE_ACCOUNT_JSON env var is empty. Paste the entire "
            "service-account JSON contents into this Vercel env var."
        )
    try:
        cred_dict = json.loads(cred_json)
    except json.JSONDecodeError as e:
        raise RuntimeError("FIREBASE_SERVICE_ACCOUNT_JSON is not valid JSON") from e

    cred = credentials.Certificate(cred_dict)
    try:
        return firebase_admin.get_app(_APP_NAME)
    except ValueError:
        return firebase_admin.initialize_app(cred, name=_APP_NAME)


def verify_id_token(id_token: str) -> dict[str, Any]:
    """Verify a Firebase ID token and return its decoded claims.

    Raises ValueError on any failure.
    """
    app = get_firebase_app()
    try:
        return fb_auth.verify_id_token(id_token, app=app, check_revoked=False)
    except Exception as e:
        raise ValueError(f"invalid Firebase ID token: {e}") from e

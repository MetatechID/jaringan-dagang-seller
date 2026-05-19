"""Task A3 — seller BPP runs on the canonical ``*.jaringan-dagang.id``
subscriber_id scheme.

Verifies:
  * ``settings.BPP_SUBSCRIBER_ID`` matches the canonical regex
  * Default is the canonical single-tenant fallback ``bpp.jaringan-dagang.id``
  * ``signing_keys._NAME_TO_BPP_ID`` carries canonical values for the
    name-based fallback (the primary identity is ``Store.subscriber_id``)
  * No legacy ``bpp.jaringan-dagang.local`` / ``*.bpp.metatech.id`` value
    remains as a default or in the name-based fallback map
"""

from __future__ import annotations

import os
import re
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


CANONICAL_SUBSCRIBER_ID_RE = re.compile(
    r"^(?:"
    r"beli-aman\.bap\.jaringan-dagang\.id"  # BAP
    r"|bpp\.jaringan-dagang\.id"  # BPP fallback
    r"|gateway\.jaringan-dagang\.id"  # gateway
    r"|registry\.jaringan-dagang\.id"  # registry
    r"|[a-z][a-z0-9-]*\.jaringan-dagang\.id"  # per-toko BPP slug
    r")$"
)


def test_bpp_subscriber_id_default_is_canonical():
    """BPP fallback subscriber_id default must be canonical."""
    from app.config import Settings

    default_val = Settings.model_fields["BPP_SUBSCRIBER_ID"].default
    assert default_val == "bpp.jaringan-dagang.id", (
        f"BPP_SUBSCRIBER_ID default is {default_val!r}; "
        "expected 'bpp.jaringan-dagang.id'."
    )


def test_bpp_subscriber_id_matches_canonical_regex():
    """The live settings instance must also be canonical (env-overrideable
    but the default has to satisfy the regex too)."""
    from app.config import settings

    assert CANONICAL_SUBSCRIBER_ID_RE.match(settings.BPP_SUBSCRIBER_ID), (
        f"settings.BPP_SUBSCRIBER_ID={settings.BPP_SUBSCRIBER_ID!r} "
        "is not canonical."
    )


def test_beli_aman_bap_id_default_is_canonical():
    """The seller's reference to the Beli Aman BAP id must be canonical."""
    from app.config import Settings

    default_val = Settings.model_fields["BELI_AMAN_BAP_ID"].default
    assert default_val == "beli-aman.bap.jaringan-dagang.id", (
        f"BELI_AMAN_BAP_ID default is {default_val!r}; "
        "expected 'beli-aman.bap.jaringan-dagang.id'."
    )


def test_no_legacy_local_in_default():
    """Legacy '.local' must not appear in the BPP_SUBSCRIBER_ID default."""
    from app.config import Settings

    default_val = Settings.model_fields["BPP_SUBSCRIBER_ID"].default
    assert ".local" not in default_val, (
        f"Legacy '.local' suffix in default {default_val!r}."
    )


def test_no_metatech_id_in_default():
    """Legacy '.metatech.id' must not appear in the BPP_SUBSCRIBER_ID default."""
    from app.config import Settings

    default_val = Settings.model_fields["BPP_SUBSCRIBER_ID"].default
    assert "metatech.id" not in default_val, (
        f"Legacy '.metatech.id' suffix in default {default_val!r}."
    )


def test_name_to_bpp_id_uses_canonical_form():
    """``signing_keys._NAME_TO_BPP_ID`` must map every name to a canonical
    BPP subscriber_id (no .metatech.id, no .local)."""
    from app.beckn.signing_keys import _NAME_TO_BPP_ID

    for name, bpp_id in _NAME_TO_BPP_ID.items():
        assert CANONICAL_SUBSCRIBER_ID_RE.match(bpp_id), (
            f"_NAME_TO_BPP_ID[{name!r}]={bpp_id!r} is NOT canonical."
        )
        assert "metatech.id" not in bpp_id, (
            f"_NAME_TO_BPP_ID[{name!r}]={bpp_id!r} still uses legacy .metatech.id."
        )
        assert ".local" not in bpp_id, (
            f"_NAME_TO_BPP_ID[{name!r}]={bpp_id!r} still uses legacy .local."
        )


def test_name_to_bpp_id_has_all_known_stores():
    """Every onboarded store name must map to its canonical id.

    The 6 known stores from the live DB / network seed scripts are:
    safiya, antarestar, gendes, yourbrand, matchamu, optimumnutrition.
    """
    from app.beckn.signing_keys import _NAME_TO_BPP_ID

    expected = {
        "safiya": "safiyafood.jaringan-dagang.id",
        "antarestar": "antarestar.jaringan-dagang.id",
        "gendes": "gendes.jaringan-dagang.id",
        "yourbrand": "yourbrand.jaringan-dagang.id",
        "matchamu": "matchamu.jaringan-dagang.id",
        "optimumnutrition": "optimumnutrition.jaringan-dagang.id",
    }
    for name, expected_bpp in expected.items():
        assert _NAME_TO_BPP_ID.get(name) == expected_bpp, (
            f"_NAME_TO_BPP_ID[{name!r}]={_NAME_TO_BPP_ID.get(name)!r}; "
            f"expected {expected_bpp!r}."
        )

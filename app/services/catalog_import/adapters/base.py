"""SourceAdapter protocol — one class per supported marketplace export."""

from __future__ import annotations

from typing import Any, Protocol


class SourceAdapter(Protocol):
    name: str
    display_name: str
    file_extensions: tuple[str, ...]
    hint: str  # one-line UI hint, e.g. "Products → Bulk Export → XLSX"

    # canonical_field → source column header (as it appears in row 1 of export)
    default_column_mapping: dict[str, str]

    def detect(self, headers: list[str]) -> float:
        """Confidence score 0..1 that this adapter fits these headers.

        Used as a tiebreaker when the user picks 'Generic' but a more specific
        adapter would handle the file better. Not used to override an explicit
        user choice.
        """
        ...

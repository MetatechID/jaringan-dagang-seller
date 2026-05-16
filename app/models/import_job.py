"""ImportJob model — tracks spreadsheet catalog imports through their lifecycle.

An import goes upload → previewed → confirmed → applied (or failed at any step).
The preview_rows JSONB holds up to the first 500 parsed+normalized rows so the
review UI can re-render without re-parsing the file.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ImportSource(str, enum.Enum):
    BIGSELLER = "bigseller"
    SHOPEE = "shopee"
    TOKOPEDIA = "tokopedia"
    LAZADA = "lazada"
    GENERIC = "generic"


class ImportJobStatus(str, enum.Enum):
    UPLOADED = "uploaded"      # file received, parse not yet finished
    PREVIEWED = "previewed"    # parsed + normalized, awaiting user confirm
    CONFIRMED = "confirmed"    # user clicked confirm, applier running or pending
    APPLIED = "applied"        # rows committed to catalog
    FAILED = "failed"          # parse or apply errored


class ImportJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "import_jobs"

    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("stores.id", ondelete="CASCADE"),
        nullable=False,
    )
    source: Mapped[ImportSource] = mapped_column(
        SAEnum(ImportSource, name="import_source", create_constraint=True),
        nullable=False,
    )
    status: Mapped[ImportJobStatus] = mapped_column(
        SAEnum(ImportJobStatus, name="import_job_status", create_constraint=True),
        nullable=False,
        default=ImportJobStatus.UPLOADED,
    )
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    file_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    column_mapping: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    preview_rows: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    applied_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:
        return (
            f"<ImportJob(id={self.id}, source={self.source.value}, "
            f"status={self.status.value})>"
        )

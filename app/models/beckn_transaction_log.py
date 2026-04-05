"""BecknTransactionLog model for auditing all Beckn protocol messages."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class BecknTransactionLog(Base):
    __tablename__ = "beckn_transaction_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    transaction_id: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True
    )
    message_id: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True
    )
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    request_body: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    response_body: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    bap_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return (
            f"<BecknTransactionLog(id={self.id}, action='{self.action}', "
            f"txn='{self.transaction_id}')>"
        )

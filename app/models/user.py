"""User identity for seller dashboard access.

One row per human who's signed into the dashboard. Identified by Firebase UID
(stable across sessions) and also indexed by email (for invite-by-email).
"""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    firebase_uid: Mapped[str | None] = mapped_column(
        String(128), unique=True, nullable=True, index=True
    )
    email: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    photo_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    # Super admins bypass all StoreMembership checks and see every store.
    is_super_admin: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )

    # StoreMembership has TWO FKs back to users (user_id + invited_by_user_id);
    # specify foreign_keys so SQLAlchemy knows which one drives this collection.
    memberships: Mapped[list["StoreMembership"]] = relationship(  # noqa: F821
        back_populates="user",
        cascade="all, delete-orphan",
        foreign_keys="StoreMembership.user_id",
    )

    def __repr__(self) -> str:
        return f"<User(email={self.email!r}, super={self.is_super_admin})>"

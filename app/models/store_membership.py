"""StoreMembership — who can access which store and at what role.

Roles (2-level):
  owner — full control of the store: products, orders, refunds, settings,
          team management (invite/remove members)
  staff — operational: products, orders, refunds. No team management.

A user can have memberships in multiple stores. A store can have multiple
members. Super admins (User.is_super_admin) bypass this table entirely.

When `user_id` is NULL the row is a pending invite for `invited_email`. On
that user's first sign-in we materialize them and link the row.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class StoreRole(str, enum.Enum):
    OWNER = "owner"
    STAFF = "staff"


class StoreMembership(TimestampMixin, Base):
    __tablename__ = "store_memberships"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    invited_email: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True
    )
    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("stores.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[StoreRole] = mapped_column(
        SAEnum(StoreRole, name="store_role", create_constraint=True),
        nullable=False,
        default=StoreRole.STAFF,
    )
    invited_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    user: Mapped["User | None"] = relationship(  # noqa: F821
        back_populates="memberships", foreign_keys=[user_id]
    )

    def __repr__(self) -> str:
        return f"<StoreMembership(email={self.invited_email!r}, store={self.store_id}, role={self.role})>"


# At most one membership per (user_id, store_id) — application-enforced for
# pending invites where user_id is NULL (we dedupe by email+store_id).
Index(
    "uq_membership_user_store",
    StoreMembership.user_id,
    StoreMembership.store_id,
    unique=True,
    postgresql_where=StoreMembership.user_id.isnot(None),
)

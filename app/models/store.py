"""Store model -- represents a seller's store (BPP provider)."""

import uuid

from sqlalchemy import String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Store(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "stores"

    subscriber_id: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False
    )
    subscriber_url: Mapped[str] = mapped_column(String(512), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    logo_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # Per-store storefront origin used to resolve product image URLs at the
    # Beckn emission boundary (Task A7). Product/SKU rows store host-agnostic
    # relative paths like "/brands/<slug>/products/<file>.svg"; the catalog
    # builder prepends this base when constructing Item.images[].url so each
    # store can have its own storefront origin (Safiya = safiya.beliaman.com,
    # Antarestar = antarestar.beliaman.com, etc.). NULL = legacy absolute URLs
    # in image rows are passed through unchanged.
    image_base_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    domain: Mapped[str] = mapped_column(
        String(100), nullable=False, default="nic2004:52110"
    )
    city: Mapped[str] = mapped_column(
        String(50), nullable=False, default="ID:JKT"
    )
    signing_private_key: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    signing_public_key: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active"
    )

    # Relationships
    products: Mapped[list["Product"]] = relationship(  # noqa: F821
        back_populates="store", cascade="all, delete-orphan"
    )
    orders: Mapped[list["Order"]] = relationship(  # noqa: F821
        back_populates="store", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Store(id={self.id}, name='{self.name}')>"

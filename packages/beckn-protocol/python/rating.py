"""Beckn protocol rating models.

Models for submitting and receiving ratings in the Beckn protocol.
Ratings can apply to items, providers, fulfillments, or the overall order.
"""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from .catalog import Tag


class RatingCategory(str, Enum):
    """What entity is being rated."""

    ITEM = "Item"
    ORDER = "Order"
    FULFILLMENT = "Fulfillment"
    PROVIDER = "Provider"
    AGENT = "Agent"


class Rating(BaseModel):
    """A rating submitted by the buyer or acknowledged by the seller.

    Used in the `rating` action (buyer -> BAP -> BPP) and
    `on_rating` callback (BPP -> BAP).
    """

    model_config = {"populate_by_name": True}

    id: Optional[str] = Field(
        default=None,
        description="Rating ID (assigned by BPP on acknowledgment)",
    )
    rating_category: Optional[RatingCategory] = Field(
        default=None,
        description="The type of entity being rated",
    )
    value: Optional[str] = Field(
        default=None,
        description="Rating value as string (e.g. '4', '4.5')",
    )
    # The ID of the entity being rated
    id_ref: Optional[str] = Field(
        default=None,
        description="ID of the entity being rated (item_id, provider_id, etc.)",
    )
    feedback_form: Optional[list[dict[str, str]]] = Field(
        default=None,
        description="Structured feedback form responses",
    )
    feedback_id: Optional[str] = Field(
        default=None,
        description="Reference to a feedback form template",
    )
    tags: Optional[list[Tag]] = Field(
        default=None,
        description="Additional rating metadata",
    )

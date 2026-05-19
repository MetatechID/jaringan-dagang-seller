"""SQLAlchemy models for the BPP service."""

from app.models.base import Base, TimestampMixin
from app.models.store import Store
from app.models.category import Category
from app.models.product import Product, ProductStatus
from app.models.product_image import ProductImage
from app.models.sku import SKU
from app.models.sku_image import SKUImage
from app.models.order import Order, OrderStatus
from app.models.payment import PaymentRecord, PaymentStatus
from app.models.fulfillment import FulfillmentRecord, FulfillmentStatus
from app.models.beckn_transaction_log import BecknTransactionLog
from app.models.beckn_outbound_log import BecknOutboundLog
from app.models.refund import RefundReason, RefundRequest, RefundStatus
from app.models.marketplace_map import MarketplaceProductMap
from app.models.import_job import ImportJob, ImportJobStatus, ImportSource
from app.models.user import User
from app.models.store_membership import StoreMembership, StoreRole
from app.models.conversation import (
    Channel,
    Contact,
    Conversation,
    ConversationState,
    Inbox,
    Label,
    Message,
    MessageDelivery,
    MessageSender,
    conversation_labels,
)

__all__ = [
    "Base",
    "TimestampMixin",
    "Store",
    "Category",
    "Product",
    "ProductStatus",
    "ProductImage",
    "SKU",
    "SKUImage",
    "Order",
    "OrderStatus",
    "PaymentRecord",
    "PaymentStatus",
    "FulfillmentRecord",
    "FulfillmentStatus",
    "BecknTransactionLog",
    "BecknOutboundLog",
    "RefundRequest",
    "RefundStatus",
    "RefundReason",
    "MarketplaceProductMap",
    "ImportJob",
    "ImportJobStatus",
    "ImportSource",
    "User",
    "StoreMembership",
    "StoreRole",
    # Chatwoot-style CRM (Task C1)
    "Channel",
    "ConversationState",
    "MessageSender",
    "MessageDelivery",
    "Contact",
    "Inbox",
    "Conversation",
    "Message",
    "Label",
    "conversation_labels",
]

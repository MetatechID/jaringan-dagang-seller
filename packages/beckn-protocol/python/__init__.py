"""Beckn protocol library for Python.

Shared library used by BAP and BPP services. Provides Pydantic v2 models
for all Beckn protocol schemas and Ed25519 signing utilities.

Usage:
    from python import BecknContext, BecknRequest, BecknResponse
    from python import Catalog, Provider, Item, Order, Payment, Fulfillment
    from python import BecknSigner, sign_request, verify_request, generate_keypair
"""

# Context
from .context import (
    BecknAction,
    BecknCity,
    BecknContext,
    BecknCountry,
    BecknLocation,
)

# Catalog
from .catalog import (
    Catalog,
    CategoryId,
    Descriptor,
    Image,
    Item,
    Price,
    Provider,
    Quantity,
    QuantityDetail,
    QuantityMeasure,
    Tag,
    TagValue,
)

# Order
from .order import (
    Billing,
    CancellationTerm,
    Order,
    OrderItem,
    OrderState,
    Quote,
    QuoteBreakup,
    QuoteBreakupItem,
)

# Payment
from .payment import (
    Payment,
    PaymentCollectedBy,
    PaymentParams,
    PaymentStatus,
    PaymentType,
)

# Fulfillment
from .fulfillment import (
    Address,
    Contact,
    Fulfillment,
    FulfillmentEnd,
    FulfillmentStart,
    FulfillmentState,
    FulfillmentStop,
    FulfillmentType,
    Gps,
    Location,
    Person,
)

# Rating
from .rating import (
    Rating,
    RatingCategory,
)

# Message envelopes
from .message import (
    AckMessage,
    AckResponse,
    AckStatus,
    BecknRequest,
    BecknResponse,
)

# Errors
from .errors import (
    BecknError,
    BecknErrorType,
)

# Signing utilities
from .signer import (
    BecknSigner,
    KeyPair,
    generate_keypair,
    sign_request,
    verify_request,
)

__all__ = [
    # Context
    "BecknAction",
    "BecknCity",
    "BecknContext",
    "BecknCountry",
    "BecknLocation",
    # Catalog
    "Catalog",
    "CategoryId",
    "Descriptor",
    "Image",
    "Item",
    "Price",
    "Provider",
    "Quantity",
    "QuantityDetail",
    "QuantityMeasure",
    "Tag",
    "TagValue",
    # Order
    "Billing",
    "CancellationTerm",
    "Order",
    "OrderItem",
    "OrderState",
    "Quote",
    "QuoteBreakup",
    "QuoteBreakupItem",
    # Payment
    "Payment",
    "PaymentCollectedBy",
    "PaymentParams",
    "PaymentStatus",
    "PaymentType",
    # Fulfillment
    "Address",
    "Contact",
    "Fulfillment",
    "FulfillmentEnd",
    "FulfillmentStart",
    "FulfillmentState",
    "FulfillmentStop",
    "FulfillmentType",
    "Gps",
    "Location",
    "Person",
    # Rating
    "Rating",
    "RatingCategory",
    # Message envelopes
    "AckMessage",
    "AckResponse",
    "AckStatus",
    "BecknRequest",
    "BecknResponse",
    # Errors
    "BecknError",
    "BecknErrorType",
    # Signing
    "BecknSigner",
    "KeyPair",
    "generate_keypair",
    "sign_request",
    "verify_request",
]

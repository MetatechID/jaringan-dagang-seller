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

# Errors (+ ONDC retail error-code catalogue)
from .errors import (
    ONDC_RETAIL_ERROR_CODES,
    BecknError,
    BecknErrorType,
    OndcErrorClass,
    OndcErrorCode,
    ondc_error,
)

# ONDC @ondc/org tag builders (RET11 search/select/confirm)
from .ondc_tags import (
    ONDC_ORG_STATUTORY_PACKAGED_COMMODITIES,
    ONDC_ORG_STATUTORY_PREPACKAGED_FOOD,
    build_fulfillment_ondc_tags,
    build_item_statutory_tags,
    build_payment_settlement_tags,
)

# Signing utilities
from .signer import (
    BecknSigner,
    KeyPair,
    generate_keypair,
    sign_request,
    verify_request,
)

# Registry lookup
from .registry import (
    RegistryClient,
    Subscriber,
    SubscriberNotFound,
)

# ONDC domain resolution (per-store domain code on top of the Beckn base)
from .domain_resolver import (
    DEFAULT_ONDC_DOMAIN,
    ONDC_RETAIL_BECKN_BASE,
    OndcDomain,
    resolve_ondc_domain,
)

# ONDC IGM (Issue & Grievance Management) v1 — refund-request scope
from .igm import (
    COMPLAINANT_ACTIONS,
    ISSUE_CATEGORIES,
    ISSUE_SUB_CATEGORIES_ITEM,
    Issue,
    IssueActor,
    IssueDescription,
    IssueLevel,
    IssueResolutionAction,
    RESPONDENT_ACTIONS,
    build_issue_envelope,
    build_on_issue_envelope,
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
    # Errors (+ ONDC retail error-code catalogue)
    "BecknError",
    "BecknErrorType",
    "ONDC_RETAIL_ERROR_CODES",
    "OndcErrorClass",
    "OndcErrorCode",
    "ondc_error",
    # ONDC @ondc/org tag builders
    "ONDC_ORG_STATUTORY_PACKAGED_COMMODITIES",
    "ONDC_ORG_STATUTORY_PREPACKAGED_FOOD",
    "build_fulfillment_ondc_tags",
    "build_item_statutory_tags",
    "build_payment_settlement_tags",
    # Signing
    "BecknSigner",
    "KeyPair",
    "generate_keypair",
    "sign_request",
    "verify_request",
    # Registry
    "RegistryClient",
    "Subscriber",
    "SubscriberNotFound",
    # ONDC domain resolution
    "DEFAULT_ONDC_DOMAIN",
    "ONDC_RETAIL_BECKN_BASE",
    "OndcDomain",
    "resolve_ondc_domain",
    # ONDC IGM (Issue & Grievance Management) v1
    "COMPLAINANT_ACTIONS",
    "ISSUE_CATEGORIES",
    "ISSUE_SUB_CATEGORIES_ITEM",
    "Issue",
    "IssueActor",
    "IssueDescription",
    "IssueLevel",
    "IssueResolutionAction",
    "RESPONDENT_ACTIONS",
    "build_issue_envelope",
    "build_on_issue_envelope",
]

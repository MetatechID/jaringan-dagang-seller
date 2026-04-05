"""Beckn protocol error models.

Defines structured error types returned in Beckn protocol responses.
Error codes follow Beckn Core Specification conventions.
"""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class BecknErrorType(str, Enum):
    """Standard Beckn error type categories."""

    CONTEXT_ERROR = "CONTEXT-ERROR"
    CORE_ERROR = "CORE-ERROR"
    DOMAIN_ERROR = "DOMAIN-ERROR"
    POLICY_ERROR = "POLICY-ERROR"
    JSON_SCHEMA_ERROR = "JSON-SCHEMA-ERROR"


class BecknError(BaseModel):
    """Beckn protocol error object.

    Returned in the `error` field of a Beckn response when something goes wrong.
    """

    model_config = {"populate_by_name": True}

    type: BecknErrorType = Field(
        ...,
        description="Category of the error",
    )
    code: str = Field(
        ...,
        description="Beckn-standard error code (e.g. '30001')",
    )
    message: str = Field(
        ...,
        description="Human-readable error message",
    )
    path: Optional[str] = Field(
        default=None,
        description="JSON path to the field that caused the error",
    )

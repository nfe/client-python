"""SDK oficial da NFE.io para Python.

Quick start::

    from nfeio import NfeClient

    client = NfeClient(api_key="...")  # or NFE_API_KEY
    invoice = client.service_invoices.create_and_wait(
        company_id, {"cityServiceCode": "...", "description": "...", "servicesAmount": 100},
        external_id="pedido-123",
    )
    print(invoice.flow_status, invoice["number"])
"""

import logging as _logging

from ._client import AsyncNfeClient, NfeClient
from ._config import ApiFamily, RequestOptions, Timeout
from ._version import __version__
from .errors import (
    APIConnectionError,
    APIError,
    APITimeoutError,
    AuthenticationError,
    ConfigurationError,
    ConflictError,
    DuplicateExternalIdError,
    FailurePhase,
    InvalidParameterError,
    InvalidRequestError,
    InvoiceProcessingError,
    NfeError,
    NotFoundError,
    PermissionDeniedError,
    PollingTimeoutError,
    RateLimitError,
    ResponseTooLargeError,
    ServerError,
    SignatureVerificationError,
    UnexpectedResponseError,
)
from .models import (
    Address,
    Certificate,
    Company,
    LegalEntity,
    NaturalPerson,
    NfeObject,
    Party,
    ResponseInfo,
    ServiceInvoice,
    Webhook,
    WebhookEventType,
)
from .pagination import AsyncCursorPage, AsyncOffsetPage, CursorPage, OffsetPage
from .types import FlowStatus

_logging.getLogger("nfeio").addHandler(_logging.NullHandler())

__all__ = [
    "APIConnectionError",
    "APIError",
    "APITimeoutError",
    "Address",
    "ApiFamily",
    "AsyncCursorPage",
    "AsyncNfeClient",
    "AsyncOffsetPage",
    "AuthenticationError",
    "Certificate",
    "Company",
    "ConfigurationError",
    "ConflictError",
    "CursorPage",
    "DuplicateExternalIdError",
    "FailurePhase",
    "FlowStatus",
    "InvalidParameterError",
    "InvalidRequestError",
    "InvoiceProcessingError",
    "LegalEntity",
    "NaturalPerson",
    "NfeClient",
    "NfeError",
    "NfeObject",
    "NotFoundError",
    "OffsetPage",
    "Party",
    "PermissionDeniedError",
    "PollingTimeoutError",
    "RateLimitError",
    "RequestOptions",
    "ResponseInfo",
    "ResponseTooLargeError",
    "ServerError",
    "ServiceInvoice",
    "SignatureVerificationError",
    "Timeout",
    "UnexpectedResponseError",
    "Webhook",
    "WebhookEventType",
    "__version__",
]

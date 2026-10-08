"""Exceptions raised by the NFE.io SDK.

Every exception derives from :class:`NfeError`. HTTP error responses become subclasses of
:class:`APIError` chosen by status code; network failures become :class:`APIConnectionError`.

Hierarchy::

    NfeError
    ├── ConfigurationError            (also ValueError)
    ├── InvalidParameterError         (also ValueError)
    ├── APIError
    │   ├── InvalidRequestError       400, 405, 410, 415, 422 and other 4xx
    │   │   └── DuplicateExternalIdError
    │   ├── AuthenticationError       401
    │   ├── PermissionDeniedError     403
    │   ├── NotFoundError             404
    │   ├── ConflictError             409
    │   ├── RateLimitError            429
    │   └── ServerError               408 and 5xx
    ├── APIConnectionError
    │   └── APITimeoutError
    ├── ResponseTooLargeError
    ├── UnexpectedResponseError
    ├── InvoiceProcessingError
    ├── PollingTimeoutError
    └── SignatureVerificationError

No exception ever carries the API key or the ``Authorization`` header.
"""

from __future__ import annotations

import enum
import json
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from ._core.headers import Headers

if TYPE_CHECKING:
    from .models import ServiceInvoice

__all__ = [
    "APIConnectionError",
    "APIError",
    "APITimeoutError",
    "AuthenticationError",
    "ConfigurationError",
    "ConflictError",
    "DuplicateExternalIdError",
    "FailurePhase",
    "InvalidParameterError",
    "InvalidRequestError",
    "InvoiceProcessingError",
    "NfeError",
    "NotFoundError",
    "PermissionDeniedError",
    "PollingTimeoutError",
    "RateLimitError",
    "ResponseTooLargeError",
    "ServerError",
    "SignatureVerificationError",
    "UnexpectedResponseError",
]


class FailurePhase(str, enum.Enum):
    """When a network failure happened relative to sending the request."""

    #: DNS, refused connection or TLS handshake: no byte of the request left the machine.
    NOT_ESTABLISHED = "not_established"
    #: The request may have reached the server (read timeout, connection reset, ...).
    MAYBE_SENT = "maybe_sent"


class NfeError(Exception):
    """Base class for every exception raised by the SDK."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message

    def __str__(self) -> str:
        return self.message


class ConfigurationError(NfeError, ValueError):
    """Invalid client configuration: missing key, insecure TLS, invalid option."""


class InvalidParameterError(NfeError, ValueError):
    """A parameter was rejected locally, before any request was sent."""

    def __init__(self, message: str, *, param: str | None = None) -> None:
        super().__init__(message)
        self.param = param


class APIError(NfeError):
    """The API answered with an HTTP error status.

    Attributes:
        status_code: HTTP status.
        message: message extracted from the response body (sanitised, at most 1,000 chars).
        error_code: first ``code`` found in the body, when present.
        body: raw response body.
        headers: response headers (case-insensitive).
        request_id: value of ``x-request-id`` — quote it when contacting support.
        trace_id: ``traceId`` of ASP.NET ProblemDetails bodies.
        outcome_unknown: ``True`` when the request was not idempotent (POST) and the server may
            have processed it anyway (408/429/5xx). Reconcile before retrying — see
            ``service_invoices.find_by_external_id``.
        external_id: ``externalId`` of the invoice being issued, when applicable.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        body: bytes = b"",
        headers: Mapping[str, str] | None = None,
        error_code: int | str | None = None,
        trace_id: str | None = None,
        outcome_unknown: bool = False,
        external_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body
        self.headers = headers if isinstance(headers, Headers) else Headers(headers)
        self.error_code = error_code
        self.trace_id = trace_id
        self.outcome_unknown = outcome_unknown
        self.external_id = external_id

    @property
    def request_id(self) -> str | None:
        return self.headers.get("x-request-id")

    @property
    def json_body(self) -> Any:
        """Body decoded as JSON, or ``None`` when it is empty or not JSON."""
        if not self.body:
            return None
        try:
            return json.loads(self.body.decode("utf-8-sig"))
        except (UnicodeDecodeError, ValueError):
            return None

    def __str__(self) -> str:
        details = [f"status={self.status_code}"]
        if self.error_code is not None:
            details.append(f"code={self.error_code}")
        if self.request_id:
            details.append(f"request_id={self.request_id}")
        if self.outcome_unknown:
            details.append("outcome_unknown=True")
        return f"{self.message} ({', '.join(details)})"

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(status_code={self.status_code}, message={self.message!r}, "
            f"error_code={self.error_code!r}, request_id={self.request_id!r}, "
            f"outcome_unknown={self.outcome_unknown})"
        )


class InvalidRequestError(APIError):
    """400, 405, 410, 415, 422 and any other 4xx not mapped to a more specific class."""


class DuplicateExternalIdError(InvalidRequestError):
    """The API rejected an issuance because ``externalId`` already exists.

    The invoice from the first attempt exists: fetch it with
    ``service_invoices.find_by_external_id(company_id, err.external_id)``.
    """


class AuthenticationError(APIError):
    """401 — missing or invalid API key."""


class PermissionDeniedError(APIError):
    """403 — the key is valid but cannot access this API family (wrong key for the host)."""


class NotFoundError(APIError):
    """404 — resource (or route) not found."""


class ConflictError(APIError):
    """409 — conflicting state."""


class RateLimitError(APIError):
    """429 — too many requests.

    Attributes:
        retry_after: seconds the server asked to wait, when it sent ``Retry-After``.
    """

    def __init__(self, message: str, *, retry_after: float | None = None, **kwargs: Any) -> None:
        super().__init__(message, **kwargs)
        self.retry_after = retry_after


class ServerError(APIError):
    """408 or 5xx — server-side failure or timeout."""


class APIConnectionError(NfeError):
    """The request could not be completed at the network level.

    Attributes:
        phase: :class:`FailurePhase` — whether the request may have reached the server.
        outcome_unknown: ``True`` for non-idempotent requests that may have been processed.
        external_id: ``externalId`` of the invoice being issued, when applicable.
    """

    def __init__(
        self,
        message: str,
        *,
        phase: FailurePhase,
        outcome_unknown: bool = False,
        external_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.phase = phase
        self.outcome_unknown = outcome_unknown
        self.external_id = external_id

    def __str__(self) -> str:
        suffix = f"phase={self.phase.value}"
        if self.outcome_unknown:
            suffix += ", outcome_unknown=True"
        return f"{self.message} ({suffix})"

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(message={self.message!r}, phase={self.phase.value!r}, "
            f"outcome_unknown={self.outcome_unknown})"
        )


class APITimeoutError(APIConnectionError):
    """A connect, read or total deadline expired."""


class ResponseTooLargeError(NfeError):
    """The response body exceeded ``max_response_bytes``; the connection was discarded."""

    def __init__(self, message: str, *, limit: int) -> None:
        super().__init__(message)
        self.limit = limit


class UnexpectedResponseError(NfeError):
    """A successful status with a body the SDK cannot interpret (or an unsafe redirect)."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        body: bytes = b"",
        headers: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body
        self.headers = headers if isinstance(headers, Headers) else Headers(headers)

    @property
    def request_id(self) -> str | None:
        return self.headers.get("x-request-id")


class InvoiceProcessingError(NfeError):
    """Polling reached a failure state (``IssueFailed``, ``CancelFailed`` or ``Error``).

    Attributes:
        invoice: the last :class:`~nfeio.models.ServiceInvoice` observed.
        flow_status: the terminal failure status.
        flow_message: the explanation sent by the API (city hall rejection, ...).
    """

    def __init__(
        self,
        message: str,
        *,
        invoice: ServiceInvoice,
        flow_status: str | None,
        flow_message: str | None,
    ) -> None:
        super().__init__(message)
        self.invoice = invoice
        self.flow_status = flow_status
        self.flow_message = flow_message


class PollingTimeoutError(NfeError):
    """The wait deadline expired before the invoice reached a terminal status.

    Attributes:
        invoice: the last invoice observed (``None`` if every poll returned 404).
        flow_status: last ``flowStatus`` observed.
        elapsed: seconds spent waiting.
    """

    def __init__(
        self,
        message: str,
        *,
        invoice: ServiceInvoice | None,
        flow_status: str | None,
        elapsed: float,
    ) -> None:
        super().__init__(message)
        self.invoice = invoice
        self.flow_status = flow_status
        self.elapsed = elapsed


class SignatureVerificationError(NfeError):
    """A webhook delivery failed signature verification (raised by ``construct_event`` only)."""

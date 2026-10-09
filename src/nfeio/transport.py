"""Public transport API: implement :class:`Transport`/:class:`AsyncTransport` to plug another
HTTP stack. Transports must not follow redirects and must raise
:class:`~nfeio.errors.APIConnectionError` with the right
:class:`~nfeio.errors.FailurePhase` on network failures."""

from ._core.headers import Headers
from ._core.transport import (
    AsyncTransport,
    HttpClientTransport,
    HttpRequest,
    HttpResponse,
    ThreadedAsyncTransport,
    Transport,
)

__all__ = [
    "AsyncTransport",
    "Headers",
    "HttpClientTransport",
    "HttpRequest",
    "HttpResponse",
    "ThreadedAsyncTransport",
    "Transport",
]

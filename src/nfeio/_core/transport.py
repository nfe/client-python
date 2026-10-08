"""HTTP transport: protocols, request/response values and the stdlib implementation.

The default transport is built on :mod:`http.client` (not :mod:`urllib.request`) because the
SDK must know *when* a network failure happened: ``connect()`` is explicit, so DNS, refused
connections and TLS handshake errors are classified as ``NOT_ESTABLISHED`` (nothing was sent)
and anything after that as ``MAYBE_SENT``. ``urllib`` also follows redirects re-sending
headers to the new host, which is unacceptable with the API key in ``Authorization``.

Transports never follow redirects.
"""

from __future__ import annotations

import asyncio
import http.client
import os
import ssl
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable
from urllib.parse import urlsplit

from .._config import DEFAULT_MAX_RESPONSE_BYTES, Timeout, build_ssl_context
from ..errors import (
    APIConnectionError,
    APITimeoutError,
    ConfigurationError,
    FailurePhase,
    ResponseTooLargeError,
)
from .headers import SENSITIVE_HEADERS, Headers
from .redact import log_path

__all__ = [
    "AsyncTransport",
    "HttpClientTransport",
    "HttpRequest",
    "HttpResponse",
    "ThreadedAsyncTransport",
    "Transport",
]

_CHUNK = 64 * 1024
#: Methods whose requests may travel on a reused keep-alive connection.
_REUSABLE_METHODS = frozenset({"GET", "HEAD", "PUT", "DELETE", "OPTIONS"})
#: Errors that mean "the idle keep-alive connection was already closed by the server".
_STALE_CONNECTION_ERRORS = (
    http.client.RemoteDisconnected,
    BrokenPipeError,
    ConnectionResetError,
    ConnectionAbortedError,
)


@dataclass(frozen=True, repr=False)
class HttpRequest:
    """A fully-built HTTP request handed to a :class:`Transport`."""

    method: str
    url: str
    headers: Mapping[str, str] = field(default_factory=dict)
    body: bytes | None = None
    timeout: Timeout = field(default_factory=Timeout)
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES

    def __repr__(self) -> str:
        parts = urlsplit(self.url)
        shown = {
            k: ("<redacted>" if k.lower() in SENSITIVE_HEADERS else v)
            for k, v in self.headers.items()
        }
        return (
            f"HttpRequest(method={self.method!r}, host={parts.netloc!r}, "
            f"path={log_path(parts.path)!r}, headers={shown!r}, "
            f"body_bytes={len(self.body or b'')})"
        )


@dataclass(frozen=True, repr=False)
class HttpResponse:
    """Raw HTTP response returned by a :class:`Transport`."""

    status_code: int
    headers: Headers
    body: bytes = b""

    def __repr__(self) -> str:
        return (
            f"HttpResponse(status_code={self.status_code}, "
            f"request_id={self.headers.get('x-request-id')!r}, body_bytes={len(self.body)})"
        )


@runtime_checkable
class Transport(Protocol):
    """Synchronous transport.

    ``send`` must not follow redirects, must honour ``request.timeout`` and
    ``request.max_response_bytes``, and must raise :class:`~nfeio.errors.APIConnectionError`
    (with the right :class:`~nfeio.errors.FailurePhase`) for network failures.
    """

    def send(self, request: HttpRequest) -> HttpResponse: ...

    def close(self) -> None: ...


@runtime_checkable
class AsyncTransport(Protocol):
    """Asynchronous transport, same contract as :class:`Transport`."""

    async def send(self, request: HttpRequest) -> HttpResponse: ...

    async def aclose(self) -> None: ...


_PoolKey = tuple[str, str, int]


class HttpClientTransport:
    """Default transport on top of :mod:`http.client`, thread-safe.

    * TLS: verified context, TLS >= 1.2; an extra CA bundle or a custom (still verifying)
      ``ssl.SSLContext`` may be supplied. Disabling verification is rejected.
    * Keep-alive pool: LIFO per host, at most ``max_idle_per_host`` idle connections.
      Non-idempotent requests (POST) always use a brand-new connection, so a failure is never
      ambiguous because of a stale reused socket.
    * Body read in 64 KiB chunks, aborted above ``request.max_response_bytes``.
    """

    def __init__(
        self,
        *,
        ssl_context: ssl.SSLContext | None = None,
        ca_bundle: str | os.PathLike[str] | None = None,
        max_idle_per_host: int = 10,
    ) -> None:
        self._ssl_context = build_ssl_context(ssl_context, ca_bundle)
        self._max_idle = max(0, max_idle_per_host)
        self._pool: dict[_PoolKey, list[http.client.HTTPConnection]] = {}
        self._lock = threading.Lock()
        self._closed = False

    # -- pool -------------------------------------------------------------------------------

    def _acquire(self, key: _PoolKey) -> http.client.HTTPConnection | None:
        with self._lock:
            idle = self._pool.get(key)
            return idle.pop() if idle else None

    def _release(self, key: _PoolKey, conn: http.client.HTTPConnection) -> None:
        with self._lock:
            if not self._closed:
                idle = self._pool.setdefault(key, [])
                if len(idle) < self._max_idle:
                    idle.append(conn)
                    return
        conn.close()

    def idle_connections(self) -> int:
        """Number of idle pooled connections (useful in tests and diagnostics)."""
        with self._lock:
            return sum(len(v) for v in self._pool.values())

    def close(self) -> None:
        with self._lock:
            self._closed = True
            conns = [c for idle in self._pool.values() for c in idle]
            self._pool.clear()
        for conn in conns:
            conn.close()

    # -- sending ----------------------------------------------------------------------------

    def _connect(
        self, scheme: str, host: str, port: int, timeout: Timeout
    ) -> http.client.HTTPConnection:
        conn: http.client.HTTPConnection
        if scheme == "https":
            conn = http.client.HTTPSConnection(
                host, port, timeout=timeout.connect, context=self._ssl_context
            )
        else:
            conn = http.client.HTTPConnection(host, port, timeout=timeout.connect)
        try:
            conn.connect()
        except TimeoutError:
            conn.close()
            raise APITimeoutError(
                f"timed out connecting to {host}", phase=FailurePhase.NOT_ESTABLISHED
            ) from None
        except (OSError, http.client.HTTPException) as exc:
            conn.close()
            raise APIConnectionError(
                f"could not connect to {host}: {_describe(exc)}",
                phase=FailurePhase.NOT_ESTABLISHED,
            ) from None
        return conn

    def send(self, request: HttpRequest) -> HttpResponse:
        if self._closed:
            raise ConfigurationError("transport is closed")
        parts = urlsplit(request.url)
        scheme = parts.scheme.lower()
        if scheme not in ("https", "http") or not parts.hostname:
            raise ConfigurationError(f"unsupported URL scheme for request: {scheme!r}")
        host = parts.hostname
        port = parts.port or (443 if scheme == "https" else 80)
        target = parts.path or "/"
        if parts.query:
            target += "?" + parts.query
        key: _PoolKey = (scheme, host, port)
        method = request.method.upper()
        reusable = method in _REUSABLE_METHODS

        conn = self._acquire(key) if reusable else None
        if conn is not None:
            try:
                return self._exchange(conn, key, method, target, request, host, reusable)
            except APIConnectionError as exc:
                if not isinstance(exc.__cause__, _STALE_CONNECTION_ERRORS):
                    raise
                # The idle socket was closed by the server: replay once on a fresh connection.
                # Only idempotent methods ever travel on reused connections.
        conn = self._connect(scheme, host, port, request.timeout)
        return self._exchange(conn, key, method, target, request, host, reusable)

    def _exchange(
        self,
        conn: http.client.HTTPConnection,
        key: _PoolKey,
        method: str,
        target: str,
        request: HttpRequest,
        host: str,
        reusable: bool,
    ) -> HttpResponse:
        timeout = request.timeout
        deadline = time.monotonic() + timeout.total
        try:
            _set_timeout(conn, timeout.read, deadline)
            conn.request(method, target, body=request.body, headers=dict(request.headers))
            resp = conn.getresponse()
            headers = Headers(resp.getheaders())
            body = _read_body(conn, resp, timeout.read, deadline, request.max_response_bytes)
        except ResponseTooLargeError:
            conn.close()
            raise
        except APITimeoutError:
            conn.close()
            raise
        except TimeoutError as exc:
            conn.close()
            raise APITimeoutError(
                f"timed out waiting for {host}", phase=FailurePhase.MAYBE_SENT
            ) from exc
        except (OSError, http.client.HTTPException) as exc:
            conn.close()
            raise APIConnectionError(
                f"connection to {host} failed: {_describe(exc)}", phase=FailurePhase.MAYBE_SENT
            ) from exc
        if reusable and not resp.will_close:
            self._release(key, conn)
        else:
            conn.close()
        return HttpResponse(status_code=resp.status, headers=headers, body=body)


def _describe(exc: BaseException) -> str:
    text = str(exc).strip()
    return f"{type(exc).__name__}: {text}" if text else type(exc).__name__


def _set_timeout(conn: http.client.HTTPConnection, read: float, deadline: float) -> None:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise APITimeoutError("total request deadline exceeded", phase=FailurePhase.MAYBE_SENT)
    if conn.sock is not None:
        conn.sock.settimeout(min(read, remaining))


def _read_body(
    conn: http.client.HTTPConnection,
    resp: http.client.HTTPResponse,
    read_timeout: float,
    deadline: float,
    limit: int,
) -> bytes:
    declared = resp.getheader("content-length")
    if declared is not None and declared.strip().isdigit() and int(declared) > limit:
        raise ResponseTooLargeError(
            f"response declares {int(declared)} bytes, above max_response_bytes={limit}",
            limit=limit,
        )
    chunks: list[bytes] = []
    total = 0
    while True:
        _set_timeout(conn, read_timeout, deadline)
        chunk = resp.read(_CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise ResponseTooLargeError(
                f"response body exceeded max_response_bytes={limit}", limit=limit
            )
        chunks.append(chunk)
    return b"".join(chunks)


class ThreadedAsyncTransport:
    """Async adapter that runs a synchronous :class:`Transport` in a worker thread.

    Uses :func:`asyncio.to_thread` (the loop's default executor). Cancelling the awaiting task
    does not interrupt the request already in flight; its socket timeouts bound how long the
    thread lives.
    """

    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    @property
    def sync_transport(self) -> Transport:
        return self._transport

    async def send(self, request: HttpRequest) -> HttpResponse:
        return await asyncio.to_thread(self._transport.send, request)

    async def aclose(self) -> None:
        await asyncio.to_thread(self._transport.close)

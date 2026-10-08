"""``NfeClient`` and ``AsyncNfeClient``: explicit clients, no global state."""

from __future__ import annotations

import asyncio
import os
import ssl
import time
from collections.abc import Awaitable, Callable, Mapping
from types import TracebackType
from typing import TypeVar

from ._config import DEFAULT_MAX_RESPONSE_BYTES, ApiFamily, ClientConfig, Timeout
from ._core.ops import Op, run_async, run_sync
from ._core.transport import (
    AsyncTransport,
    HttpClientTransport,
    ThreadedAsyncTransport,
    Transport,
)
from .errors import ConfigurationError
from .resources.certificates import AsyncCertificatesService, CertificatesService
from .resources.companies import AsyncCompaniesService, CompaniesService
from .resources.lookups import AsyncLookupsService, LookupsService
from .resources.service_invoices import AsyncServiceInvoicesService, ServiceInvoicesService
from .resources.webhooks import AsyncWebhooksService, WebhooksService

__all__ = ["AsyncNfeClient", "NfeClient"]

T = TypeVar("T")
_DEFAULT_TIMEOUT = Timeout()


def _check_transport_args(
    transport: object,
    ssl_context: ssl.SSLContext | None,
    ca_bundle: str | os.PathLike[str] | None,
) -> None:
    if transport is not None and (ssl_context is not None or ca_bundle is not None):
        raise ConfigurationError(
            "ssl_context/ca_bundle configure the default transport; with a custom transport, "
            "configure TLS in the transport itself"
        )


class NfeClient:
    """Synchronous NFE.io client. Thread-safe; reuse one instance per configuration.

    Args:
        api_key: key for NFS-e, companies, certificates and webhooks. Defaults to the
            ``NFE_API_KEY`` environment variable.
        data_api_key: key for CNPJ/CPF/CEP lookups. Defaults to ``NFE_DATA_API_KEY``. The main
            key is never used as a fallback (data hosts reject it with 403).
        base_urls: override the base URL of an API family (``"service_invoices"``,
            ``"account"``, ``"legal_entity"``, ``"natural_person"``, ``"address"``); https only.
        timeout: :class:`~nfeio.Timeout` or seconds per attempt (default connect 10 s,
            read 60 s, total 120 s). Must be finite.
        max_retries: retries of safe requests (default 3). POSTs are never retried after the
            request may have reached the API.
        retry_base_delay, retry_max_delay: exponential backoff (1 s doubling up to 30 s,
            with +-30% jitter).
        max_retry_after: largest ``Retry-After`` honoured (default 60 s).
        max_response_bytes: response size limit (default 10 MiB).
        app_info: ``(name, version)`` appended to the User-Agent, e.g.
            ``("odoo-l10n_br_nfse_nfeio", "18.0.1.0")``.
        ssl_context: a verifying ``ssl.SSLContext`` (e.g. corporate CA). Contexts that
            disable verification are rejected.
        ca_bundle: path to extra trusted CA certificates (PEM).
        transport: custom :class:`~nfeio.transport.Transport`.
    """

    service_invoices: ServiceInvoicesService
    companies: CompaniesService
    certificates: CertificatesService
    webhooks: WebhooksService
    lookups: LookupsService

    def __init__(
        self,
        api_key: str | None = None,
        *,
        data_api_key: str | None = None,
        base_urls: Mapping[ApiFamily | str, str] | None = None,
        timeout: float | Timeout = _DEFAULT_TIMEOUT,
        max_retries: int = 3,
        retry_base_delay: float = 1.0,
        retry_max_delay: float = 30.0,
        max_retry_after: float = 60.0,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
        app_info: tuple[str, str] | None = None,
        ssl_context: ssl.SSLContext | None = None,
        ca_bundle: str | os.PathLike[str] | None = None,
        transport: Transport | None = None,
    ) -> None:
        _check_transport_args(transport, ssl_context, ca_bundle)
        self._config = ClientConfig.build(
            api_key=api_key,
            data_api_key=data_api_key,
            base_urls=base_urls,
            timeout=timeout,
            max_retries=max_retries,
            retry_base_delay=retry_base_delay,
            retry_max_delay=retry_max_delay,
            max_retry_after=max_retry_after,
            max_response_bytes=max_response_bytes,
            app_info=app_info,
        )
        self._transport: Transport = (
            transport
            if transport is not None
            else HttpClientTransport(ssl_context=ssl_context, ca_bundle=ca_bundle)
        )
        self._sleep: Callable[[float], None] = time.sleep
        self._monotonic: Callable[[], float] = time.monotonic
        self.service_invoices = ServiceInvoicesService(self)
        self.companies = CompaniesService(self)
        self.certificates = CertificatesService(self)
        self.webhooks = WebhooksService(self)
        self.lookups = LookupsService(self)

    def _run(self, op: Op[T]) -> T:
        return run_sync(op, self._transport, sleep=self._sleep, monotonic=self._monotonic)

    def close(self) -> None:
        """Close pooled connections."""
        self._transport.close()

    def __enter__(self) -> NfeClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def __repr__(self) -> str:
        return (
            f"NfeClient(api_key={self._config.api_key!r}, "
            f"data_api_key={self._config.data_api_key!r})"
        )


class AsyncNfeClient:
    """Asynchronous NFE.io client with the same surface and behaviour as :class:`NfeClient`.

    I/O runs in worker threads (``asyncio.to_thread`` over the stdlib transport) and waits use
    ``asyncio.sleep``, so the event loop is never blocked. Pass a native
    :class:`~nfeio.transport.AsyncTransport` to use another HTTP stack.
    """

    service_invoices: AsyncServiceInvoicesService
    companies: AsyncCompaniesService
    certificates: AsyncCertificatesService
    webhooks: AsyncWebhooksService
    lookups: AsyncLookupsService

    def __init__(
        self,
        api_key: str | None = None,
        *,
        data_api_key: str | None = None,
        base_urls: Mapping[ApiFamily | str, str] | None = None,
        timeout: float | Timeout = _DEFAULT_TIMEOUT,
        max_retries: int = 3,
        retry_base_delay: float = 1.0,
        retry_max_delay: float = 30.0,
        max_retry_after: float = 60.0,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
        app_info: tuple[str, str] | None = None,
        ssl_context: ssl.SSLContext | None = None,
        ca_bundle: str | os.PathLike[str] | None = None,
        transport: AsyncTransport | None = None,
    ) -> None:
        _check_transport_args(transport, ssl_context, ca_bundle)
        self._config = ClientConfig.build(
            api_key=api_key,
            data_api_key=data_api_key,
            base_urls=base_urls,
            timeout=timeout,
            max_retries=max_retries,
            retry_base_delay=retry_base_delay,
            retry_max_delay=retry_max_delay,
            max_retry_after=max_retry_after,
            max_response_bytes=max_response_bytes,
            app_info=app_info,
        )
        self._transport: AsyncTransport = (
            transport
            if transport is not None
            else ThreadedAsyncTransport(
                HttpClientTransport(ssl_context=ssl_context, ca_bundle=ca_bundle)
            )
        )
        self._sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
        self._monotonic: Callable[[], float] = time.monotonic
        self.service_invoices = AsyncServiceInvoicesService(self)
        self.companies = AsyncCompaniesService(self)
        self.certificates = AsyncCertificatesService(self)
        self.webhooks = AsyncWebhooksService(self)
        self.lookups = AsyncLookupsService(self)

    async def _run(self, op: Op[T]) -> T:
        return await run_async(op, self._transport, sleep=self._sleep, monotonic=self._monotonic)

    async def aclose(self) -> None:
        """Close pooled connections."""
        await self._transport.aclose()

    async def __aenter__(self) -> AsyncNfeClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    def __repr__(self) -> str:
        return (
            f"AsyncNfeClient(api_key={self._config.api_key!r}, "
            f"data_api_key={self._config.data_api_key!r})"
        )

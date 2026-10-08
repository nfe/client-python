"""NFS-e (service invoices), API v1 on ``https://api.nfe.io``.

Issuance and cancellation are asynchronous: the API answers ``202`` and the invoice moves
through ``flowStatus`` values until a terminal one. ``wait``/``create_and_wait``/
``cancel_and_wait`` poll ``GET /serviceinvoices/{id}`` with backoff (there is no ``/status``
route in GET).

**Never retry an issuance on your own after an ambiguous failure.** The API can create the
invoice and still answer 500/504. Use ``external_id`` and, when an error has
``outcome_unknown=True`` (or is ``DuplicateExternalIdError``), reconcile with
``find_by_external_id(company_id, external_id, wait=30)``.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from datetime import date
from typing import Any

from .._config import ApiFamily, ClientConfig, RequestOptions
from .._core import paths
from .._core.ops import Now, Op, Sleep
from .._core.requestor import (
    decode_json,
    expect_list,
    expect_object,
    follow_download,
    request,
    response_info,
)
from .._core.transport import HttpResponse
from ..errors import (
    InvalidParameterError,
    InvoiceProcessingError,
    NotFoundError,
    PollingTimeoutError,
    UnexpectedResponseError,
)
from ..models import ServiceInvoice
from ..pagination import AsyncOffsetPage, OffsetPage, OffsetState
from ..types import FlowStatus, ServiceInvoiceCreateParams
from ._base import AsyncService, SyncService

FAMILY = ApiFamily.SERVICE_INVOICES
#: (min, max) of ``pageCount`` per route — the API rejects values outside (probe 2026-10-08).
PAGE_COUNT_LIMITS = {"service_invoices": (1, 50)}

_DOWNLOADS = {
    "pdf": ("pdf", "application/pdf, */*"),
    "xml": ("xml", "application/xml, */*"),
    "cancellation_xml": ("cancellation-xml", "application/xml, */*"),
}

_CREATE_SUCCESS = frozenset({FlowStatus.ISSUED, FlowStatus.CANCELLED})
_CREATE_FAILURE = frozenset({FlowStatus.ISSUE_FAILED, FlowStatus.ERROR})
_CANCEL_SUCCESS = frozenset({FlowStatus.CANCELLED})
_CANCEL_FAILURE = frozenset({FlowStatus.CANCEL_FAILED, FlowStatus.ERROR})


def _base_path(company_id: str) -> str:
    return f"/v1/companies/{paths.opaque_id(company_id, 'company_id')}/serviceinvoices"


def _invoice_path(company_id: str, invoice_id: str) -> str:
    return f"{_base_path(company_id)}/{paths.opaque_id(invoice_id, 'invoice_id')}"


def _check_wait_params(
    timeout: float, initial_interval: float, max_interval: float, backoff: float, grace: float
) -> None:
    for name, value, allow_zero in (
        ("timeout", timeout, False),
        ("initial_interval", initial_interval, False),
        ("max_interval", max_interval, False),
        ("not_found_grace", grace, True),
    ):
        valid = (
            not isinstance(value, bool)
            and isinstance(value, (int, float))
            and math.isfinite(value)
            and (value >= 0 if allow_zero else value > 0)
        )
        if not valid:
            raise InvalidParameterError(f"{name} must be a finite positive number", param=name)
    if isinstance(backoff, bool) or not isinstance(backoff, (int, float)) or not 1 <= backoff <= 10:
        raise InvalidParameterError("backoff must be between 1 and 10", param="backoff")


def _accepted(
    response: HttpResponse, company_id: str, invoice_id: str | None = None
) -> ServiceInvoice:
    """Build the (possibly partial) invoice from a 200/201/202/204 answer.

    202 bodies (``{id, environment, flowStatus}``) are preserved. When the body has no id, it
    comes from the **path** of ``Location`` (whose scheme/host are never used: the API sends
    ``http://``).
    """
    data: dict[str, Any] = {}
    parsed = decode_json(response, allow_empty=True) if response.body.strip() else None
    if isinstance(parsed, dict):
        data = parsed
    found = data.get("id") if isinstance(data.get("id"), str) else None
    if found is None:
        found = _id_from_location(response, company_id)
    if found is None:
        found = invoice_id
    if found is None:
        raise UnexpectedResponseError(
            "the API accepted the request but returned no invoice id (no 'id' in the body "
            "and no usable Location header)",
            status_code=response.status_code,
            body=response.body,
            headers=response.headers,
        )
    data.setdefault("id", found)
    return ServiceInvoice._from_wire(data, response_info(response))


_LOCATION_RE = re.compile(
    r"/v1/companies/(?P<company>[A-Za-z0-9_-]{1,64})/serviceinvoices/(?P<id>[A-Za-z0-9_-]{1,64})/?"
)


def _id_from_location(response: HttpResponse, company_id: str) -> str | None:
    from urllib.parse import urlsplit

    location = response.headers.get("location")
    if not location:
        return None
    match = _LOCATION_RE.fullmatch(urlsplit(location.strip()).path)
    if match is None or match.group("company") != company_id:
        return None
    return match.group("id")


# -- ops ---------------------------------------------------------------------------------------


def create_op(
    cfg: ClientConfig,
    company_id: str,
    params: ServiceInvoiceCreateParams | Mapping[str, Any],
    external_id: str | None,
    options: RequestOptions | None,
) -> Op[ServiceInvoice]:
    path = _base_path(company_id)
    if not isinstance(params, Mapping):
        raise InvalidParameterError("params must be a mapping (the request body)", param="params")
    body = dict(params)
    wire_external_id = body.get("externalId")
    if external_id is not None:
        paths.check_free_text(external_id, "external_id")
        if wire_external_id is not None and wire_external_id != external_id:
            raise InvalidParameterError(
                "external_id and params['externalId'] differ; pass only one",
                param="external_id",
            )
        body["externalId"] = external_id
    elif isinstance(wire_external_id, str):
        external_id = wire_external_id
    response = yield from request(
        cfg, "POST", FAMILY, path, json=body, options=options, external_id=external_id
    )
    if response.status_code not in (200, 201, 202):
        raise UnexpectedResponseError(
            f"unexpected status {response.status_code} when issuing a service invoice",
            status_code=response.status_code,
            body=response.body,
            headers=response.headers,
        )
    return _accepted(response, company_id)


def list_op(
    cfg: ClientConfig,
    company_id: str,
    page_index: int,
    page_count: int,
    filters: dict[str, str | None],
    options: RequestOptions | None,
) -> Op[OffsetState[ServiceInvoice]]:
    path = _base_path(company_id)
    low, high = PAGE_COUNT_LIMITS["service_invoices"]
    if isinstance(page_index, bool) or not isinstance(page_index, int) or page_index < 1:
        raise InvalidParameterError(
            "page_index starts at 1 (the API pagination is 1-based)", param="page_index"
        )
    if (
        isinstance(page_count, bool)
        or not isinstance(page_count, int)
        or not (low <= page_count <= high)
    ):
        raise InvalidParameterError(
            f"page_count must be between {low} and {high}", param="page_count"
        )
    query: dict[str, str | int | None] = {"pageIndex": page_index, "pageCount": page_count}
    query.update(filters)
    response = yield from request(cfg, "GET", FAMILY, path, query=query, options=options)
    _, items = expect_list(response, "serviceInvoices")
    info = response_info(response)
    invoices = [ServiceInvoice._from_wire(item, info) for item in items if isinstance(item, dict)]

    def fetch(next_index: int) -> Op[OffsetState[ServiceInvoice]]:
        return list_op(cfg, company_id, next_index, page_count, filters, options)

    return OffsetState(invoices, info, page_index, page_count, fetch)


def retrieve_op(
    cfg: ClientConfig, company_id: str, invoice_id: str, options: RequestOptions | None
) -> Op[ServiceInvoice]:
    response = yield from request(
        cfg, "GET", FAMILY, _invoice_path(company_id, invoice_id), options=options
    )
    return ServiceInvoice._from_wire(expect_object(response), response_info(response))


def find_by_external_id_op(
    cfg: ClientConfig,
    company_id: str,
    external_id: str,
    wait: float,
    options: RequestOptions | None,
) -> Op[ServiceInvoice | None]:
    path = (
        f"{_base_path(company_id)}/external/{paths.free_text_segment(external_id, 'external_id')}"
    )
    if (
        isinstance(wait, bool)
        or not isinstance(wait, (int, float))
        or not (math.isfinite(wait) and wait >= 0)
    ):
        raise InvalidParameterError("wait must be a finite number >= 0", param="wait")
    start: float = yield Now()
    delay = 1.0
    while True:
        response = yield from request(cfg, "GET", FAMILY, path, options=options)
        data = decode_json(response)
        info = response_info(response)
        # Only an explicit empty list means "no invoice": anything else unexpected must not be
        # read as "safe to issue again" by a reconciliation flow.
        items = data.get("serviceInvoices") if isinstance(data, dict) else None
        if isinstance(items, list):
            first = next((item for item in items if isinstance(item, dict)), None)
            if first is not None:
                return ServiceInvoice._from_wire(first, info)
        elif isinstance(data, dict) and isinstance(data.get("id"), str):
            return ServiceInvoice._from_wire(data, info)  # object form, as the spec documents
        else:
            raise UnexpectedResponseError(
                "unexpected answer to the externalId lookup (expected a serviceInvoices list)",
                status_code=response.status_code,
                body=response.body,
                headers=response.headers,
            )
        now: float = yield Now()
        remaining = wait - (now - start)
        if remaining <= 0:
            return None
        yield Sleep(min(delay, remaining))
        delay = min(delay * 1.5, 5.0)


def cancel_op(
    cfg: ClientConfig, company_id: str, invoice_id: str, options: RequestOptions | None
) -> Op[ServiceInvoice]:
    path = _invoice_path(company_id, invoice_id)
    response = yield from request(cfg, "DELETE", FAMILY, path, options=options)
    if response.status_code not in (200, 201, 202, 204):
        raise UnexpectedResponseError(
            f"unexpected status {response.status_code} when cancelling a service invoice",
            status_code=response.status_code,
            body=response.body,
            headers=response.headers,
        )
    return _accepted(response, company_id, invoice_id)


def send_email_op(
    cfg: ClientConfig, company_id: str, invoice_id: str, options: RequestOptions | None
) -> Op[None]:
    path = f"{_invoice_path(company_id, invoice_id)}/sendemail"
    yield from request(cfg, "PUT", FAMILY, path, options=options)
    return None


def download_op(
    cfg: ClientConfig,
    company_id: str,
    invoice_id: str,
    kind: str,
    options: RequestOptions | None,
) -> Op[bytes]:
    suffix, accept = _DOWNLOADS[kind]
    path = f"{_invoice_path(company_id, invoice_id)}/{suffix}"
    response = yield from request(
        cfg, "GET", FAMILY, path, accept=accept, options=options, allow_redirect=True
    )
    response = yield from follow_download(
        cfg,
        response,
        family=FAMILY,
        origin_url=cfg.base_urls[FAMILY] + path,
        accept=accept,
        options=options,
    )
    if response.status_code != 200:
        raise UnexpectedResponseError(
            f"unexpected status {response.status_code} when downloading {kind}",
            status_code=response.status_code,
            headers=response.headers,
        )
    return response.body


def wait_op(
    cfg: ClientConfig,
    company_id: str,
    invoice_id: str,
    *,
    timeout: float,
    initial_interval: float,
    max_interval: float,
    backoff: float,
    not_found_grace: float,
    raise_on_failure: bool,
    options: RequestOptions | None,
    success: frozenset[str] = FlowStatus.SUCCESS,
    failure: frozenset[str] = FlowStatus.FAILURE,
) -> Op[ServiceInvoice]:
    _check_wait_params(timeout, initial_interval, max_interval, backoff, not_found_grace)
    paths.opaque_id(invoice_id, "invoice_id")
    start: float = yield Now()
    interval = float(initial_interval)
    last: ServiceInvoice | None = None
    while True:
        try:
            invoice = yield from retrieve_op(cfg, company_id, invoice_id, options)
        except NotFoundError:
            elapsed: float = (yield Now()) - start
            if elapsed >= not_found_grace:
                raise
        else:
            last = invoice
            status = invoice.flow_status
            if status in success:
                return invoice
            if status in failure:
                if not raise_on_failure:
                    return invoice
                raise InvoiceProcessingError(
                    f"service invoice {invoice_id} ended in {status}: "
                    f"{invoice.flow_message or 'no flowMessage'}",
                    invoice=invoice,
                    flow_status=status,
                    flow_message=invoice.flow_message,
                )
        now: float = yield Now()
        remaining = timeout - (now - start)
        if remaining <= 0:
            observed = last.flow_status if last is not None else None
            raise PollingTimeoutError(
                f"service invoice {invoice_id} did not reach a terminal status in "
                f"{timeout:g}s (last flowStatus: {observed})",
                invoice=last,
                flow_status=observed,
                elapsed=now - start,
            )
        yield Sleep(min(interval, remaining))
        interval = min(interval * backoff, max_interval)


def create_and_wait_op(
    cfg: ClientConfig,
    company_id: str,
    params: ServiceInvoiceCreateParams | Mapping[str, Any],
    external_id: str | None,
    wait_kwargs: dict[str, Any],
    options: RequestOptions | None,
) -> Op[ServiceInvoice]:
    invoice = yield from create_op(cfg, company_id, params, external_id, options)
    if invoice.flow_status in _CREATE_SUCCESS:
        return invoice
    if invoice.id is None:  # pragma: no cover - _accepted always sets an id
        raise UnexpectedResponseError("issued invoice has no id")
    result = yield from wait_op(
        cfg,
        company_id,
        invoice.id,
        options=options,
        success=_CREATE_SUCCESS,
        failure=_CREATE_FAILURE,
        **wait_kwargs,
    )
    return result


def cancel_and_wait_op(
    cfg: ClientConfig,
    company_id: str,
    invoice_id: str,
    wait_kwargs: dict[str, Any],
    options: RequestOptions | None,
) -> Op[ServiceInvoice]:
    invoice = yield from cancel_op(cfg, company_id, invoice_id, options)
    if invoice.flow_status in _CANCEL_SUCCESS:
        return invoice
    result = yield from wait_op(
        cfg,
        company_id,
        invoice_id,
        options=options,
        success=_CANCEL_SUCCESS,
        failure=_CANCEL_FAILURE,
        **wait_kwargs,
    )
    return result


def _filters(
    issued_begin: date | str | None,
    issued_end: date | str | None,
    created_begin: date | str | None,
    created_end: date | str | None,
) -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    for wire, param, value in (
        ("issuedBegin", "issued_begin", issued_begin),
        ("issuedEnd", "issued_end", issued_end),
        ("createdBegin", "created_begin", created_begin),
        ("createdEnd", "created_end", created_end),
    ):
        out[wire] = paths.iso_date(value, param) if value is not None else None
    return out


def _wait_kwargs(
    timeout: float,
    initial_interval: float,
    max_interval: float,
    backoff: float,
    not_found_grace: float,
    raise_on_failure: bool,
) -> dict[str, Any]:
    return {
        "timeout": timeout,
        "initial_interval": initial_interval,
        "max_interval": max_interval,
        "backoff": backoff,
        "not_found_grace": not_found_grace,
        "raise_on_failure": raise_on_failure,
    }


# -- facades -----------------------------------------------------------------------------------


class ServiceInvoicesService(SyncService):
    """``client.service_invoices`` — NFS-e operations (synchronous)."""

    __slots__ = ()

    def create(
        self,
        company_id: str,
        params: ServiceInvoiceCreateParams | Mapping[str, Any],
        *,
        external_id: str | None = None,
        options: RequestOptions | None = None,
    ) -> ServiceInvoice:
        """Issue an NFS-e. Usually returns ``202`` with a partial invoice (``id``,
        ``flow_status``); call :meth:`wait` or use :meth:`create_and_wait`.

        ``external_id`` (strongly recommended) is your dedupe key, sent as ``externalId``.
        This method never retries after the request may have reached the API.
        """
        return self._run(create_op(self._cfg, company_id, params, external_id, options))

    def list(
        self,
        company_id: str,
        *,
        page_index: int = 1,
        page_count: int = 10,
        issued_begin: date | str | None = None,
        issued_end: date | str | None = None,
        created_begin: date | str | None = None,
        created_end: date | str | None = None,
        options: RequestOptions | None = None,
    ) -> OffsetPage[ServiceInvoice]:
        """List invoices (``page_index`` starts at 1, ``page_count`` 1-50)."""
        filters = _filters(issued_begin, issued_end, created_begin, created_end)
        state = self._run(list_op(self._cfg, company_id, page_index, page_count, filters, options))
        return OffsetPage(state, self._runner)

    def retrieve(
        self, company_id: str, invoice_id: str, *, options: RequestOptions | None = None
    ) -> ServiceInvoice:
        return self._run(retrieve_op(self._cfg, company_id, invoice_id, options))

    def find_by_external_id(
        self,
        company_id: str,
        external_id: str,
        *,
        wait: float = 0.0,
        options: RequestOptions | None = None,
    ) -> ServiceInvoice | None:
        """Find the invoice issued with ``external_id``; ``None`` if there is none.

        Right after a ``202`` the lookup may lag a few seconds: pass ``wait=30`` to retry
        with backoff until found or until ``wait`` seconds elapse.
        """
        return self._run(find_by_external_id_op(self._cfg, company_id, external_id, wait, options))

    def cancel(
        self, company_id: str, invoice_id: str, *, options: RequestOptions | None = None
    ) -> ServiceInvoice:
        """Request cancellation (asynchronous: usually ``202``)."""
        return self._run(cancel_op(self._cfg, company_id, invoice_id, options))

    def send_email(
        self, company_id: str, invoice_id: str, *, options: RequestOptions | None = None
    ) -> None:
        """Re-send the invoice e-mail to the borrower."""
        self._run(send_email_op(self._cfg, company_id, invoice_id, options))

    def download_pdf(
        self, company_id: str, invoice_id: str, *, options: RequestOptions | None = None
    ) -> bytes:
        """PDF bytes. The API redirects to a pre-signed URL, followed without credentials."""
        return self._run(download_op(self._cfg, company_id, invoice_id, "pdf", options))

    def download_xml(
        self, company_id: str, invoice_id: str, *, options: RequestOptions | None = None
    ) -> bytes:
        """XML bytes, untouched (NFS-e XML starts with ``<Nfse`` without ``<?xml``).
        Parse with a hardened parser such as ``defusedxml``."""
        return self._run(download_op(self._cfg, company_id, invoice_id, "xml", options))

    def download_cancellation_xml(
        self, company_id: str, invoice_id: str, *, options: RequestOptions | None = None
    ) -> bytes:
        """Cancellation XML bytes (only some providers have it; otherwise ``NotFoundError``)."""
        return self._run(
            download_op(self._cfg, company_id, invoice_id, "cancellation_xml", options)
        )

    def wait(
        self,
        company_id: str,
        invoice_id: str,
        *,
        timeout: float = 120.0,
        initial_interval: float = 1.0,
        max_interval: float = 10.0,
        backoff: float = 1.5,
        not_found_grace: float = 10.0,
        raise_on_failure: bool = True,
        options: RequestOptions | None = None,
    ) -> ServiceInvoice:
        """Poll until ``flowStatus`` is terminal (``Issued``/``Cancelled`` or a failure).

        Raises ``InvoiceProcessingError`` on ``IssueFailed``/``CancelFailed``/``Error``
        (unless ``raise_on_failure=False``) and ``PollingTimeoutError`` after ``timeout``.
        """
        return self._run(
            wait_op(
                self._cfg,
                company_id,
                invoice_id,
                options=options,
                **_wait_kwargs(
                    timeout,
                    initial_interval,
                    max_interval,
                    backoff,
                    not_found_grace,
                    raise_on_failure,
                ),
            )
        )

    def create_and_wait(
        self,
        company_id: str,
        params: ServiceInvoiceCreateParams | Mapping[str, Any],
        *,
        external_id: str | None = None,
        timeout: float = 120.0,
        initial_interval: float = 1.0,
        max_interval: float = 10.0,
        backoff: float = 1.5,
        not_found_grace: float = 10.0,
        raise_on_failure: bool = True,
        options: RequestOptions | None = None,
    ) -> ServiceInvoice:
        """:meth:`create` followed by :meth:`wait` until ``Issued`` (or failure)."""
        return self._run(
            create_and_wait_op(
                self._cfg,
                company_id,
                params,
                external_id,
                _wait_kwargs(
                    timeout,
                    initial_interval,
                    max_interval,
                    backoff,
                    not_found_grace,
                    raise_on_failure,
                ),
                options,
            )
        )

    def cancel_and_wait(
        self,
        company_id: str,
        invoice_id: str,
        *,
        timeout: float = 120.0,
        initial_interval: float = 1.0,
        max_interval: float = 10.0,
        backoff: float = 1.5,
        not_found_grace: float = 10.0,
        raise_on_failure: bool = True,
        options: RequestOptions | None = None,
    ) -> ServiceInvoice:
        """:meth:`cancel` followed by :meth:`wait` until ``Cancelled`` (or failure)."""
        return self._run(
            cancel_and_wait_op(
                self._cfg,
                company_id,
                invoice_id,
                _wait_kwargs(
                    timeout,
                    initial_interval,
                    max_interval,
                    backoff,
                    not_found_grace,
                    raise_on_failure,
                ),
                options,
            )
        )


class AsyncServiceInvoicesService(AsyncService):
    """``client.service_invoices`` — NFS-e operations (asynchronous). Same behaviour as
    :class:`ServiceInvoicesService`."""

    __slots__ = ()

    async def create(
        self,
        company_id: str,
        params: ServiceInvoiceCreateParams | Mapping[str, Any],
        *,
        external_id: str | None = None,
        options: RequestOptions | None = None,
    ) -> ServiceInvoice:
        return await self._run(create_op(self._cfg, company_id, params, external_id, options))

    async def list(
        self,
        company_id: str,
        *,
        page_index: int = 1,
        page_count: int = 10,
        issued_begin: date | str | None = None,
        issued_end: date | str | None = None,
        created_begin: date | str | None = None,
        created_end: date | str | None = None,
        options: RequestOptions | None = None,
    ) -> AsyncOffsetPage[ServiceInvoice]:
        filters = _filters(issued_begin, issued_end, created_begin, created_end)
        state = await self._run(
            list_op(self._cfg, company_id, page_index, page_count, filters, options)
        )
        return AsyncOffsetPage(state, self._runner)

    async def retrieve(
        self, company_id: str, invoice_id: str, *, options: RequestOptions | None = None
    ) -> ServiceInvoice:
        return await self._run(retrieve_op(self._cfg, company_id, invoice_id, options))

    async def find_by_external_id(
        self,
        company_id: str,
        external_id: str,
        *,
        wait: float = 0.0,
        options: RequestOptions | None = None,
    ) -> ServiceInvoice | None:
        return await self._run(
            find_by_external_id_op(self._cfg, company_id, external_id, wait, options)
        )

    async def cancel(
        self, company_id: str, invoice_id: str, *, options: RequestOptions | None = None
    ) -> ServiceInvoice:
        return await self._run(cancel_op(self._cfg, company_id, invoice_id, options))

    async def send_email(
        self, company_id: str, invoice_id: str, *, options: RequestOptions | None = None
    ) -> None:
        await self._run(send_email_op(self._cfg, company_id, invoice_id, options))

    async def download_pdf(
        self, company_id: str, invoice_id: str, *, options: RequestOptions | None = None
    ) -> bytes:
        return await self._run(download_op(self._cfg, company_id, invoice_id, "pdf", options))

    async def download_xml(
        self, company_id: str, invoice_id: str, *, options: RequestOptions | None = None
    ) -> bytes:
        return await self._run(download_op(self._cfg, company_id, invoice_id, "xml", options))

    async def download_cancellation_xml(
        self, company_id: str, invoice_id: str, *, options: RequestOptions | None = None
    ) -> bytes:
        return await self._run(
            download_op(self._cfg, company_id, invoice_id, "cancellation_xml", options)
        )

    async def wait(
        self,
        company_id: str,
        invoice_id: str,
        *,
        timeout: float = 120.0,
        initial_interval: float = 1.0,
        max_interval: float = 10.0,
        backoff: float = 1.5,
        not_found_grace: float = 10.0,
        raise_on_failure: bool = True,
        options: RequestOptions | None = None,
    ) -> ServiceInvoice:
        return await self._run(
            wait_op(
                self._cfg,
                company_id,
                invoice_id,
                options=options,
                **_wait_kwargs(
                    timeout,
                    initial_interval,
                    max_interval,
                    backoff,
                    not_found_grace,
                    raise_on_failure,
                ),
            )
        )

    async def create_and_wait(
        self,
        company_id: str,
        params: ServiceInvoiceCreateParams | Mapping[str, Any],
        *,
        external_id: str | None = None,
        timeout: float = 120.0,
        initial_interval: float = 1.0,
        max_interval: float = 10.0,
        backoff: float = 1.5,
        not_found_grace: float = 10.0,
        raise_on_failure: bool = True,
        options: RequestOptions | None = None,
    ) -> ServiceInvoice:
        return await self._run(
            create_and_wait_op(
                self._cfg,
                company_id,
                params,
                external_id,
                _wait_kwargs(
                    timeout,
                    initial_interval,
                    max_interval,
                    backoff,
                    not_found_grace,
                    raise_on_failure,
                ),
                options,
            )
        )

    async def cancel_and_wait(
        self,
        company_id: str,
        invoice_id: str,
        *,
        timeout: float = 120.0,
        initial_interval: float = 1.0,
        max_interval: float = 10.0,
        backoff: float = 1.5,
        not_found_grace: float = 10.0,
        raise_on_failure: bool = True,
        options: RequestOptions | None = None,
    ) -> ServiceInvoice:
        return await self._run(
            cancel_and_wait_op(
                self._cfg,
                company_id,
                invoice_id,
                _wait_kwargs(
                    timeout,
                    initial_interval,
                    max_interval,
                    backoff,
                    not_found_grace,
                    raise_on_failure,
                ),
                options,
            )
        )

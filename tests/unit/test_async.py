from __future__ import annotations

import asyncio
import inspect
import threading
import time
from typing import Any

import pytest

from nfeio import (
    AsyncCursorPage,
    AsyncNfeClient,
    AsyncOffsetPage,
    InvalidParameterError,
    NfeClient,
    ServerError,
)
from nfeio.transport import HttpRequest, HttpResponse, ThreadedAsyncTransport
from tests.helpers import (
    COMPANY_ID,
    INVOICE_ID,
    FakeClock,
    FakeTransport,
    invoice_json,
    make_async_client,
    make_client,
    resp,
)

RESOURCES = ("service_invoices", "companies", "certificates", "webhooks", "lookups")
SYNC_ONLY_RETURN = {"OffsetPage": "AsyncOffsetPage", "CursorPage": "AsyncCursorPage"}


def _public_methods(obj: Any) -> dict[str, Any]:
    return {
        name: getattr(obj, name)
        for name in dir(obj)
        if not name.startswith("_") and callable(getattr(obj, name))
    }


def test_signature_parity() -> None:
    sync = NfeClient(api_key="k" * 10, transport=FakeTransport())
    asyn = AsyncNfeClient(api_key="k" * 10, transport=ThreadedAsyncTransport(FakeTransport()))
    sync_init = inspect.signature(NfeClient.__init__).parameters
    async_init = inspect.signature(AsyncNfeClient.__init__).parameters
    assert list(sync_init) == list(async_init)
    for name in sync_init:
        if name != "transport":
            assert sync_init[name].default == async_init[name].default, name
    for resource in RESOURCES:
        s_methods = _public_methods(getattr(sync, resource))
        a_methods = _public_methods(getattr(asyn, resource))
        assert set(s_methods) == set(a_methods), resource
        for name, method in s_methods.items():
            a_method = a_methods[name]
            assert inspect.iscoroutinefunction(a_method), f"{resource}.{name}"
            s_sig, a_sig = inspect.signature(method), inspect.signature(a_method)
            assert list(s_sig.parameters) == list(a_sig.parameters), f"{resource}.{name}"
            for p_name, param in s_sig.parameters.items():
                a_param = a_sig.parameters[p_name]
                assert param.default == a_param.default, f"{resource}.{name}.{p_name}"
                assert param.kind == a_param.kind
                assert param.annotation == a_param.annotation, f"{resource}.{name}.{p_name}"
            s_ret, a_ret = str(s_sig.return_annotation), str(a_sig.return_annotation)
            for s_name, a_name in SYNC_ONLY_RETURN.items():
                s_ret = s_ret.replace(s_name, a_name)
            assert s_ret.replace("AsyncAsync", "Async") == a_ret, f"{resource}.{name}"


async def test_same_responses_same_behaviour() -> None:
    script = [resp(503), resp(503), resp(200, {"webHooks": [{"id": "h1"}]})]
    s_clock, a_clock = FakeClock(), FakeClock()
    s_transport, a_transport = FakeTransport(*script), FakeTransport(*script)
    sync_result = make_client(s_transport, s_clock).webhooks.list()
    async_result = await make_async_client(a_transport, a_clock).webhooks.list()
    assert sync_result == async_result
    assert s_clock.sleeps == a_clock.sleeps == [1.0, 2.0]
    assert [r.url for r in s_transport.requests] == [r.url for r in a_transport.requests]


async def test_async_errors_and_validation_identical() -> None:
    transport = FakeTransport(resp(504))
    client = make_async_client(transport)
    with pytest.raises(ServerError) as info:
        await client.service_invoices.create(COMPANY_ID, {}, external_id="x")
    assert info.value.outcome_unknown
    with pytest.raises(InvalidParameterError):
        await client.service_invoices.retrieve(COMPANY_ID, "../x")


async def test_async_pagination() -> None:
    page1 = {"serviceInvoices": [invoice_json(id=f"i{n}") for n in range(2)], "page": 1}
    page2 = {"serviceInvoices": [invoice_json(id="i2")], "page": 2}
    transport = FakeTransport(
        resp(200, page1),
        resp(200, page2),
        resp(200, {"hasMore": True, "companies": [{"id": "a"}]}),
        resp(200, {"hasMore": False, "companies": [{"id": "b"}]}),
    )
    client = make_async_client(transport)
    page = await client.service_invoices.list(COMPANY_ID, page_count=2)
    assert isinstance(page, AsyncOffsetPage) and page.page_index == 1 and page.page_count == 2
    assert [inv.id async for inv in page.auto_paging_iter()] == ["i0", "i1", "i2"]
    cpage = await client.companies.list(limit=1)
    assert isinstance(cpage, AsyncCursorPage) and cpage.limit == 1
    assert [c.id async for c in cpage.auto_paging_iter()] == ["a", "b"]


async def test_async_next_page_none() -> None:
    transport = FakeTransport(
        resp(200, {"serviceInvoices": [], "page": 1}),
        resp(200, {"hasMore": False, "companies": []}),
    )
    client = make_async_client(transport)
    assert await (await client.service_invoices.list(COMPANY_ID)).next_page() is None
    assert await (await client.companies.list()).next_page() is None


async def test_async_full_surface_smoke() -> None:
    location = f"http://api.nfe.io/v1/companies/{COMPANY_ID}/serviceinvoices/{INVOICE_ID}"
    issued = resp(200, invoice_json())
    cancelled = resp(200, invoice_json(flowStatus="Cancelled"))
    transport = FakeTransport(
        resp(202, {"id": INVOICE_ID, "flowStatus": "WaitingSend"}),
        issued,  # create_and_wait
        resp(202, headers={"Location": location}),
        cancelled,  # cancel_and_wait
        issued,
        issued,  # retrieve, wait
        resp(200, {"serviceInvoices": [], "page": 1}),  # find
        resp(202, headers={"Location": location}),  # cancel
        resp(200),  # send_email
        resp(200, body=b"%PDF"),
        resp(200, body=b"<Nfse/>"),
        resp(200, body=b"<C/>"),  # downloads
        resp(200, {"company": {"id": "c"}}),
        resp(201, {"company": {"id": "c"}}),
        resp(200, {"company": {"id": "c"}}),
        resp(204),  # companies
        resp(200, {"certificate": {}}),
        resp(200, {"certificates": []}),  # certificates
        resp(200, {"webHooks": []}),
        resp(200, {"webHook": {"id": "h"}}),
        resp(201, {"webHook": {"id": "h"}}),
        resp(200, {"webHook": {"id": "h"}}),
        resp(204),
        resp(204),
        resp(200, {"eventTypes": []}),  # webhooks
        resp(200, {"legalEntity": {}}),
        resp(200, {"legalEntity": {}}),
        resp(200, {"status": "Regular"}),
        resp(200, {"address": {}}),  # lookups
    )
    c = make_async_client(transport)
    si = c.service_invoices
    assert (await si.create_and_wait(COMPANY_ID, {})).flow_status == "Issued"
    assert (await si.cancel_and_wait(COMPANY_ID, INVOICE_ID)).flow_status == "Cancelled"
    assert (await si.retrieve(COMPANY_ID, INVOICE_ID)).id == INVOICE_ID
    assert (await si.wait(COMPANY_ID, INVOICE_ID)).id == INVOICE_ID
    assert await si.find_by_external_id(COMPANY_ID, "e") is None
    assert (await si.cancel(COMPANY_ID, INVOICE_ID)).id == INVOICE_ID
    await si.send_email(COMPANY_ID, INVOICE_ID)
    assert await si.download_pdf(COMPANY_ID, INVOICE_ID) == b"%PDF"
    assert await si.download_xml(COMPANY_ID, INVOICE_ID) == b"<Nfse/>"
    assert await si.download_cancellation_xml(COMPANY_ID, INVOICE_ID) == b"<C/>"
    assert (await c.companies.retrieve("c")).id == "c"
    assert (await c.companies.create({"name": "x"})).id == "c"
    assert (await c.companies.update("c", {"name": "y"})).id == "c"
    await c.companies.delete("c")
    await c.certificates.upload(COMPANY_ID, b"PFX", "pw")
    assert await c.certificates.list(COMPANY_ID) == []
    assert await c.webhooks.list() == []
    assert (await c.webhooks.retrieve("h")).id == "h"
    await c.webhooks.create({"uri": "https://x"})
    await c.webhooks.update("h", {"uri": "https://x"})
    await c.webhooks.delete("h")
    await c.webhooks.ping("h")
    assert await c.webhooks.event_types() == []
    await c.lookups.cnpj("00000000000191")
    await c.lookups.cnpj_state_taxes("00000000000191", "SP")
    assert (await c.lookups.cpf("52998224725", "1990-01-01")).status == "Regular"
    await c.lookups.cep("01310100")
    assert transport.script == []


class _SlowTransport:
    def __init__(self) -> None:
        self.active = 0
        self.max_active = 0
        self.lock = threading.Lock()

    def send(self, request: HttpRequest) -> HttpResponse:
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        time.sleep(0.05)
        with self.lock:
            self.active -= 1
        return resp(200, {"webHooks": []})

    def close(self) -> None:
        pass


async def test_threaded_transport_does_not_block_loop() -> None:
    slow = _SlowTransport()
    client = AsyncNfeClient(api_key="k" * 10, transport=ThreadedAsyncTransport(slow))
    ticks = 0

    async def ticker() -> None:
        nonlocal ticks
        for _ in range(10):
            await asyncio.sleep(0.005)
            ticks += 1

    results = await asyncio.gather(ticker(), *[client.webhooks.list() for _ in range(10)])
    assert ticks == 10
    assert results[1:] == [[]] * 10
    assert slow.max_active > 1
    assert ThreadedAsyncTransport(slow).sync_transport is slow


async def test_async_context_manager_closes() -> None:
    transport = FakeTransport()
    async with make_async_client(transport) as client:
        assert "AsyncNfeClient" in repr(client)
    assert client._transport.closed  # type: ignore[attr-defined]

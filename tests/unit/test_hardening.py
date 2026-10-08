"""Regressions for the hardening found in the final security review (2026-10-08)."""

from __future__ import annotations

import pytest

from nfeio import UnexpectedResponseError
from tests.helpers import COMPANY_ID, INVOICE_ID, FakeTransport, invoice_json, make_client, resp


@pytest.mark.parametrize(
    "answer",
    [
        resp(200, body=b""),
        resp(200, {"unexpected": True}),
        resp(200, ["not", "an", "object"]),
        resp(302, headers={"Location": "https://elsewhere.example/x"}),
    ],
)
def test_external_lookup_never_reads_garbage_as_not_found(answer: object) -> None:
    """A reconciliation must not conclude "safe to issue again" from an unexpected answer."""
    transport = FakeTransport(answer)  # type: ignore[arg-type]
    with pytest.raises(UnexpectedResponseError):
        make_client(transport).service_invoices.find_by_external_id(COMPANY_ID, "p-1", wait=30)
    assert len(transport.requests) == 1


def test_redirect_outside_downloads_is_an_error() -> None:
    transport = FakeTransport(resp(302, headers={"Location": "https://api.nfse.io/x"}))
    with pytest.raises(UnexpectedResponseError, match="redirect"):
        make_client(transport).service_invoices.retrieve(COMPANY_ID, INVOICE_ID)
    assert len(transport.requests) == 1


def test_deeply_nested_json_stays_inside_the_hierarchy() -> None:
    nested = b"[" * 100_000 + b"]" * 100_000
    transport = FakeTransport(resp(200, body=nested), resp(400, body=nested))
    client = make_client(transport)
    with pytest.raises(UnexpectedResponseError):
        client.webhooks.list()
    from nfeio import InvalidRequestError

    with pytest.raises(InvalidRequestError) as info:
        client.webhooks.list()
    assert info.value.json_body is None


def test_offset_pagination_that_does_not_advance() -> None:
    same = {"serviceInvoices": [invoice_json(id="a"), invoice_json(id="b")], "page": 1}
    transport = FakeTransport(resp(200, same), resp(200, same))
    page = make_client(transport).service_invoices.list(COMPANY_ID, page_count=2)
    with pytest.raises(UnexpectedResponseError, match="did not advance"):
        list(page.auto_paging_iter())


def test_cursor_pagination_that_does_not_advance() -> None:
    transport = FakeTransport(resp(200, {"hasMore": True, "companies": [{"id": "x"}]}))
    page = make_client(transport).companies.list(limit=1, starting_after="x")
    with pytest.raises(UnexpectedResponseError, match="did not advance"):
        list(page.auto_paging_iter())


async def test_async_offset_pagination_that_does_not_advance() -> None:
    from tests.helpers import make_async_client

    same = {"serviceInvoices": [invoice_json(id="a")], "page": 1}
    transport = FakeTransport(resp(200, same), resp(200, same))
    page = await make_async_client(transport).service_invoices.list(COMPANY_ID, page_count=1)
    with pytest.raises(UnexpectedResponseError, match="did not advance"):
        [item async for item in page.auto_paging_iter()]

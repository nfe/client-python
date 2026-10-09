from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from nfeio import InvalidParameterError, OffsetPage
from tests.helpers import COMPANY_ID, FakeTransport, invoice_json, make_client, resp


def _invoices(start: int, count: int) -> dict[str, Any]:
    return {
        "serviceInvoices": [invoice_json(id=f"inv{start + i:05d}") for i in range(count)],
        "page": 1,
    }


def _companies(ids: list[str], has_more: bool) -> dict[str, Any]:
    return {"hasMore": has_more, "companies": [{"id": i} for i in ids]}


def test_first_page_query_and_has_more() -> None:
    transport = FakeTransport(resp(200, _invoices(0, 2)))
    page = make_client(transport).service_invoices.list(COMPANY_ID, page_index=1, page_count=2)
    assert isinstance(page, OffsetPage)
    assert transport.query() == {"pageIndex": ["1"], "pageCount": ["2"]}
    assert page.has_more and len(page) == 2 and page.page_index == 1 and page.page_count == 2
    assert page.last_response.request_id == "0HTEST:00000001"
    assert [i.id for i in page] == ["inv00000", "inv00001"]
    assert "OffsetPage" in repr(page)


def test_last_page() -> None:
    page = make_client(FakeTransport(resp(200, _invoices(0, 1)))).service_invoices.list(
        COMPANY_ID, page_count=2
    )
    assert not page.has_more
    assert page.next_page() is None


def test_filters_are_sent_as_iso_dates() -> None:
    transport = FakeTransport(resp(200, _invoices(0, 0)))
    make_client(transport).service_invoices.list(
        COMPANY_ID, issued_begin=date(2026, 1, 1), issued_end="2026-12-31"
    )
    query = transport.query()
    assert query["issuedBegin"] == ["2026-01-01"] and query["issuedEnd"] == ["2026-12-31"]
    assert "createdBegin" not in query


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"page_index": 0}, "starts at 1"),
        ({"page_count": 100}, "50"),
        ({"page_count": 0}, "between 1 and 50"),
        ({"page_index": True}, "starts at 1"),
    ],
)
def test_local_page_validation(kwargs: dict[str, Any], match: str) -> None:
    transport = FakeTransport()
    with pytest.raises(InvalidParameterError, match=match):
        make_client(transport).service_invoices.list(COMPANY_ID, **kwargs)
    assert transport.requests == []


def test_auto_paging_iter_offset_120_items() -> None:
    transport = FakeTransport(
        resp(200, _invoices(0, 50)), resp(200, _invoices(50, 50)), resp(200, _invoices(100, 20))
    )
    page = make_client(transport).service_invoices.list(COMPANY_ID, page_count=50)
    ids = [inv.id for inv in page.auto_paging_iter()]
    assert ids == [f"inv{i:05d}" for i in range(120)]
    assert [transport.query(i)["pageIndex"] for i in range(3)] == [["1"], ["2"], ["3"]]
    assert all(transport.query(i)["pageCount"] == ["50"] for i in range(3))


def test_auto_paging_stops_on_full_then_empty_page() -> None:
    transport = FakeTransport(resp(200, _invoices(0, 2)), resp(200, _invoices(2, 0)))
    page = make_client(transport).service_invoices.list(COMPANY_ID, page_count=2)
    assert len(list(page.auto_paging_iter())) == 2
    assert len(transport.requests) == 2


def test_cursor_page_query_and_forward_iteration() -> None:
    transport = FakeTransport(
        resp(200, _companies(["a", "b"], True)),
        resp(200, _companies(["c"], False)),
    )
    page = make_client(transport).companies.list(limit=2, starting_after="X")
    assert transport.query() == {"limit": ["2"], "startingAfter": ["X"]}
    assert page.has_more and page.limit == 2
    assert [c.id for c in page.auto_paging_iter()] == ["a", "b", "c"]
    assert transport.query(1) == {"limit": ["50"], "startingAfter": ["b"]}


def test_cursor_next_page_keeps_limit_and_backwards() -> None:
    transport = FakeTransport(
        resp(200, _companies(["m", "n"], True)), resp(200, _companies(["k", "l"], False))
    )
    page = make_client(transport).companies.list(limit=2, ending_before="o")
    nxt = page.next_page()
    assert nxt is not None and [c.id for c in nxt] == ["k", "l"]
    assert transport.query(1) == {"limit": ["2"], "endingBefore": ["m"]}
    assert nxt.next_page() is None


def test_cursor_has_more_true_with_empty_list_stops() -> None:
    transport = FakeTransport(resp(200, _companies([], True)))
    page = make_client(transport).companies.list()
    assert list(page.auto_paging_iter()) == []
    assert page.next_page() is None
    assert len(transport.requests) == 1


@pytest.mark.parametrize("limit", [0, 51, -1, True])
def test_cursor_limit_validation(limit: int) -> None:
    transport = FakeTransport()
    with pytest.raises(InvalidParameterError):
        make_client(transport).companies.list(limit=limit)
    assert transport.requests == []


def test_cursor_rejects_both_directions_and_bad_ids() -> None:
    client = make_client(FakeTransport())
    with pytest.raises(InvalidParameterError):
        client.companies.list(starting_after="a", ending_before="b")
    with pytest.raises(InvalidParameterError):
        client.companies.list(starting_after="../x")


def test_unexpected_list_shape() -> None:
    from nfeio import UnexpectedResponseError

    with pytest.raises(UnexpectedResponseError):
        make_client(FakeTransport(resp(200, {"other": []}))).service_invoices.list(COMPANY_ID)
    with pytest.raises(UnexpectedResponseError):
        make_client(FakeTransport(resp(200, body=b"<html>"))).companies.list()

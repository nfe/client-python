from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from nfeio import (
    DuplicateExternalIdError,
    FlowStatus,
    InvalidParameterError,
    InvoiceProcessingError,
    NotFoundError,
    PollingTimeoutError,
    ServerError,
    UnexpectedResponseError,
)
from tests.helpers import (
    API_KEY,
    COMPANY_ID,
    INVOICE_ID,
    FakeClock,
    FakeTransport,
    invoice_json,
    make_client,
    resp,
)

LOCATION = f"http://api.nfe.io/v1/companies/{COMPANY_ID}/serviceinvoices/{INVOICE_ID}"
BASE = f"/v1/companies/{COMPANY_ID}/serviceinvoices"


def _accepted(**body: Any) -> Any:
    return resp(202, body or None, headers={"Location": LOCATION})


# -- create ----------------------------------------------------------------------------------


def test_create_202_keeps_body() -> None:
    transport = FakeTransport(
        _accepted(id=INVOICE_ID, environment="Development", flowStatus="WaitingCalculateTaxes")
    )
    params = {"cityServiceCode": "2690", "description": "x", "servicesAmount": Decimal("100.10")}
    inv = make_client(transport).service_invoices.create(COMPANY_ID, params, external_id="p-1")
    assert inv.id == INVOICE_ID
    assert inv.flow_status == "WaitingCalculateTaxes"
    assert inv["environment"] == "Development"
    assert inv.last_response is not None and inv.last_response.status_code == 202
    req = transport.last
    assert req.method == "POST" and req.url == f"https://api.nfe.io{BASE}"
    assert req.headers["Content-Type"] == "application/json; charset=utf-8"
    assert b'"servicesAmount":100.10' in (req.body or b"")
    assert transport.json_body()["externalId"] == "p-1"


def test_create_202_empty_body_uses_location_path_only() -> None:
    transport = FakeTransport(_accepted())
    inv = make_client(transport).service_invoices.create(COMPANY_ID, {})
    assert inv.id == INVOICE_ID
    assert len(transport.requests) == 1  # Location never fetched


def test_create_202_location_for_other_company_is_ignored() -> None:
    other = "http://evil.example/v1/companies/other/serviceinvoices/abc"
    transport = FakeTransport(resp(202, headers={"Location": other}))
    with pytest.raises(UnexpectedResponseError, match="no invoice id"):
        make_client(transport).service_invoices.create(COMPANY_ID, {})


def test_create_202_without_any_id() -> None:
    with pytest.raises(UnexpectedResponseError):
        make_client(FakeTransport(resp(202))).service_invoices.create(COMPANY_ID, {})


def test_create_201_immediate() -> None:
    transport = FakeTransport(resp(201, invoice_json()))
    inv = make_client(transport).service_invoices.create(COMPANY_ID, {})
    assert inv.flow_status == "Issued"


def test_create_external_id_conflict() -> None:
    transport = FakeTransport()
    with pytest.raises(InvalidParameterError):
        make_client(transport).service_invoices.create(
            COMPANY_ID, {"externalId": "B"}, external_id="A"
        )
    with pytest.raises(InvalidParameterError):
        make_client(transport).service_invoices.create(COMPANY_ID, [], external_id="A")  # type: ignore[arg-type]
    with pytest.raises(InvalidParameterError):
        make_client(transport).service_invoices.create(COMPANY_ID, {}, external_id="")
    assert transport.requests == []


def test_create_external_id_from_params_is_tracked() -> None:
    transport = FakeTransport(resp(500))
    with pytest.raises(ServerError) as info:
        make_client(transport).service_invoices.create(COMPANY_ID, {"externalId": "from-body"})
    assert info.value.external_id == "from-body"
    assert info.value.outcome_unknown


def test_duplicate_external_id() -> None:
    body = b'"service invoice with external id (pedido-1) already exists"'
    transport = FakeTransport(resp(400, body=body))
    with pytest.raises(DuplicateExternalIdError) as info:
        make_client(transport).service_invoices.create(COMPANY_ID, {}, external_id="pedido-1")
    assert info.value.external_id == "pedido-1"


def test_create_unexpected_status() -> None:
    with pytest.raises(UnexpectedResponseError):
        make_client(FakeTransport(resp(204))).service_invoices.create(COMPANY_ID, {})


# -- retrieve / find / cancel / email ----------------------------------------------------------


def test_retrieve_and_not_found() -> None:
    transport = FakeTransport(
        resp(200, invoice_json()),
        resp(404, body=b'"service invoice with id (X) was not found"'),
    )
    client = make_client(transport)
    assert client.service_invoices.retrieve(COMPANY_ID, INVOICE_ID).id == INVOICE_ID
    assert transport.paths()[0] == f"{BASE}/{INVOICE_ID}"
    with pytest.raises(NotFoundError, match="was not found"):
        client.service_invoices.retrieve(COMPANY_ID, "X")


def test_find_by_external_id_found_missing_and_encoding() -> None:
    transport = FakeTransport(
        resp(200, {"serviceInvoices": [invoice_json(externalId="WOO NFE/110")], "page": 1}),
        resp(200, {"serviceInvoices": [], "page": 1}),
        resp(200, invoice_json()),
    )
    client = make_client(transport)
    found = client.service_invoices.find_by_external_id(COMPANY_ID, "WOO NFE/110")
    assert found is not None and found.external_id == "WOO NFE/110"
    assert transport.requests[0].url.endswith("/external/WOO%20NFE%2F110")
    assert client.service_invoices.find_by_external_id(COMPANY_ID, "missing") is None
    assert client.service_invoices.find_by_external_id(COMPANY_ID, "obj") is not None


def test_find_by_external_id_waits_for_indexing() -> None:
    clock = FakeClock()
    empty = resp(200, {"serviceInvoices": [], "page": 1})
    transport = FakeTransport(
        empty, empty, resp(200, {"serviceInvoices": [invoice_json()], "page": 1})
    )
    found = make_client(transport, clock).service_invoices.find_by_external_id(
        COMPANY_ID, "p", wait=30
    )
    assert found is not None
    assert clock.sleeps == [1.0, 1.5]


def test_find_by_external_id_wait_expires() -> None:
    clock = FakeClock()
    empty = resp(200, {"serviceInvoices": [], "page": 1})
    transport = FakeTransport(*[empty] * 20)
    assert (
        make_client(transport, clock).service_invoices.find_by_external_id(COMPANY_ID, "p", wait=10)
        is None
    )
    assert sum(clock.sleeps) == pytest.approx(10)
    with pytest.raises(InvalidParameterError):
        make_client(transport).service_invoices.find_by_external_id(COMPANY_ID, "p", wait=-1)


def test_cancel_variants() -> None:
    transport = FakeTransport(
        resp(
            202,
            {"id": INVOICE_ID, "flowStatus": "WaitingSendCancel"},
            headers={"Location": LOCATION},
        ),
        resp(202, headers={"Location": LOCATION}),
        resp(200, body=b'"cancelled"'),
        resp(204),
    )
    client = make_client(transport)
    first = client.service_invoices.cancel(COMPANY_ID, INVOICE_ID)
    assert first.flow_status == "WaitingSendCancel"
    assert transport.last.method == "DELETE"
    for _ in range(3):
        assert client.service_invoices.cancel(COMPANY_ID, INVOICE_ID).id == INVOICE_ID


def test_send_email() -> None:
    transport = FakeTransport(resp(200))
    make_client(transport).service_invoices.send_email(COMPANY_ID, INVOICE_ID)
    assert transport.last.method == "PUT"
    assert transport.paths() == [f"{BASE}/{INVOICE_ID}/sendemail"]
    assert transport.last.body is None


# -- downloads ---------------------------------------------------------------------------------


def test_download_pdf_follows_redirect_without_credentials() -> None:
    presigned = "https://api.nfse.io/v1/blob/download?b=x&e=y&s=sig"
    transport = FakeTransport(
        resp(302, headers={"Location": presigned}),
        resp(200, body=b"%PDF-1.4 ...", headers={"Content-Type": "application/pdf"}),
    )
    pdf = make_client(transport).service_invoices.download_pdf(COMPANY_ID, INVOICE_ID)
    assert pdf.startswith(b"%PDF")
    first, second = transport.requests
    assert first.headers["Authorization"] == API_KEY
    assert first.url.endswith(f"{INVOICE_ID}/pdf")
    assert second.url == presigned
    assert "Authorization" not in second.headers
    assert all(API_KEY not in v for v in second.headers.values())


def test_download_xml_untouched() -> None:
    xml = b"<Nfse><InfNfse><Numero>1</Numero></InfNfse></Nfse>"
    transport = FakeTransport(
        resp(302, headers={"Location": "https://api.nfse.io/v1/blob/download?s=1"}),
        resp(200, body=xml),
    )
    assert make_client(transport).service_invoices.download_xml(COMPANY_ID, INVOICE_ID) == xml


def test_download_relative_redirect_and_direct_200() -> None:
    transport = FakeTransport(
        resp(302, headers={"Location": "/v1/blob/download?s=1"}),
        resp(200, body=b"<x/>"),
        resp(200, body=b"%PDF"),
    )
    client = make_client(transport)
    assert client.service_invoices.download_xml(COMPANY_ID, INVOICE_ID) == b"<x/>"
    assert transport.requests[1].url == "https://api.nfe.io/v1/blob/download?s=1"
    assert client.service_invoices.download_pdf(COMPANY_ID, INVOICE_ID) == b"%PDF"


def test_download_refuses_http_redirect() -> None:
    transport = FakeTransport(resp(302, headers={"Location": "http://api.nfse.io/blob"}))
    with pytest.raises(UnexpectedResponseError, match="https"):
        make_client(transport).service_invoices.download_pdf(COMPANY_ID, INVOICE_ID)
    assert len(transport.requests) == 1


def test_download_too_many_redirects_and_missing_location() -> None:
    hop = resp(302, headers={"Location": "https://a.example/x"})
    transport = FakeTransport(hop, hop, hop, hop)
    with pytest.raises(UnexpectedResponseError, match="too many"):
        make_client(transport).service_invoices.download_pdf(COMPANY_ID, INVOICE_ID)
    with pytest.raises(UnexpectedResponseError, match="Location"):
        make_client(FakeTransport(resp(302))).service_invoices.download_pdf(COMPANY_ID, INVOICE_ID)


def test_download_presigned_error_and_odd_status() -> None:
    transport = FakeTransport(
        resp(302, headers={"Location": "https://blob.example/x"}), resp(403, body=b"")
    )
    from nfeio import PermissionDeniedError

    with pytest.raises(PermissionDeniedError):
        make_client(transport).service_invoices.download_pdf(COMPANY_ID, INVOICE_ID)
    with pytest.raises(UnexpectedResponseError):
        make_client(FakeTransport(resp(204))).service_invoices.download_pdf(COMPANY_ID, INVOICE_ID)


def test_cancellation_xml_not_available() -> None:
    body = b'"Cancellation event XML not available (National environment only)"'
    transport = FakeTransport(resp(404, body=body))
    with pytest.raises(NotFoundError, match="National environment only"):
        make_client(transport).service_invoices.download_cancellation_xml(COMPANY_ID, INVOICE_ID)
    assert transport.last.url.endswith("/cancellation-xml")


# -- polling -----------------------------------------------------------------------------------


def _status(status: str, message: str | None = None) -> Any:
    return resp(200, invoice_json(flowStatus=status, flowMessage=message))


def test_wait_until_issued_with_backoff() -> None:
    clock = FakeClock()
    transport = FakeTransport(
        _status("WaitingCalculateTaxes"),
        _status("WaitingSend"),
        _status("WaitingReturn"),
        _status("Issued"),
    )
    inv = make_client(transport, clock).service_invoices.wait(COMPANY_ID, INVOICE_ID)
    assert inv.flow_status == FlowStatus.ISSUED
    assert clock.sleeps == [1.0, 1.5, 2.25]
    assert all(p == f"{BASE}/{INVOICE_ID}" for p in transport.paths())
    assert not any(p.endswith("/status") for p in transport.paths())


def test_wait_interval_capped() -> None:
    clock = FakeClock()
    transport = FakeTransport(*[_status("WaitingSend")] * 8, _status("Issued"))
    make_client(transport, clock).service_invoices.wait(
        COMPANY_ID, INVOICE_ID, timeout=500, max_interval=3.0
    )
    assert max(clock.sleeps) == 3.0


def test_wait_timeout() -> None:
    clock = FakeClock()
    transport = FakeTransport(*[_status("WaitingReturn")] * 50)
    with pytest.raises(PollingTimeoutError) as info:
        make_client(transport, clock).service_invoices.wait(COMPANY_ID, INVOICE_ID, timeout=20)
    assert info.value.flow_status == "WaitingReturn"
    assert info.value.invoice is not None
    assert sum(clock.sleeps) == pytest.approx(20)


def test_wait_failure_raises_with_flow_message() -> None:
    transport = FakeTransport(_status("IssueFailed", "max retry reached; city hall rejected"))
    with pytest.raises(InvoiceProcessingError) as info:
        make_client(transport).service_invoices.wait(COMPANY_ID, INVOICE_ID)
    assert info.value.flow_status == "IssueFailed"
    assert info.value.flow_message == "max retry reached; city hall rejected"
    transport.add(_status("Error"))
    inv = make_client(transport).service_invoices.wait(
        COMPANY_ID, INVOICE_ID, raise_on_failure=False
    )
    assert inv.flow_status == "Error"


def test_wait_unknown_status_is_not_terminal() -> None:
    transport = FakeTransport(_status("WaitingSomethingNew"), _status("Issued"))
    inv = make_client(transport).service_invoices.wait(COMPANY_ID, INVOICE_ID)
    assert inv.flow_status == "Issued"
    assert len(transport.requests) == 2


def test_wait_tolerates_initial_404() -> None:
    clock = FakeClock()
    not_found = resp(404, body=b'"service invoice with id (x) was not found"')
    transport = FakeTransport(not_found, _status("Issued"))
    assert make_client(transport, clock).service_invoices.wait(COMPANY_ID, INVOICE_ID).id


def test_wait_404_after_grace_propagates() -> None:
    clock = FakeClock()
    not_found = resp(404, body=b'"not found"')
    transport = FakeTransport(*[not_found] * 20)
    with pytest.raises(NotFoundError):
        make_client(transport, clock).service_invoices.wait(
            COMPANY_ID, INVOICE_ID, not_found_grace=3
        )
    assert sum(clock.sleeps) >= 3


@pytest.mark.parametrize(
    "kwargs",
    [
        {"timeout": 0},
        {"timeout": float("inf")},
        {"initial_interval": -1},
        {"backoff": 0.5},
        {"backoff": True},
        {"not_found_grace": -1},
        {"max_interval": "1"},
    ],
)
def test_wait_param_validation(kwargs: dict[str, Any]) -> None:
    transport = FakeTransport()
    with pytest.raises(InvalidParameterError):
        make_client(transport).service_invoices.wait(COMPANY_ID, INVOICE_ID, **kwargs)
    assert transport.requests == []


def test_create_and_wait() -> None:
    clock = FakeClock()
    transport = FakeTransport(
        _accepted(id=INVOICE_ID, flowStatus="WaitingCalculateTaxes"),
        _status("WaitingSend"),
        _status("Issued"),
    )
    inv = make_client(transport, clock).service_invoices.create_and_wait(
        COMPANY_ID, {"servicesAmount": 1}, external_id="p-9"
    )
    assert inv.flow_status == "Issued"
    assert [r.method for r in transport.requests] == ["POST", "GET", "GET"]


def test_create_and_wait_immediate_and_failure_propagation() -> None:
    transport = FakeTransport(resp(201, invoice_json()))
    assert make_client(transport).service_invoices.create_and_wait(COMPANY_ID, {}).id
    transport = FakeTransport(resp(504))
    with pytest.raises(ServerError) as info:
        make_client(transport).service_invoices.create_and_wait(COMPANY_ID, {}, external_id="e")
    assert info.value.outcome_unknown and info.value.external_id == "e"
    assert len(transport.requests) == 1


def test_cancel_and_wait_ignores_issued_until_cancelled() -> None:
    transport = FakeTransport(
        resp(202, headers={"Location": LOCATION}),
        _status("Issued"),
        _status("WaitingReturnCancel"),
        _status("Cancelled"),
    )
    inv = make_client(transport).service_invoices.cancel_and_wait(COMPANY_ID, INVOICE_ID)
    assert inv.flow_status == "Cancelled"
    assert len(transport.requests) == 4


def test_cancel_and_wait_failure_and_immediate() -> None:
    transport = FakeTransport(resp(202, headers={"Location": LOCATION}), _status("CancelFailed"))
    with pytest.raises(InvoiceProcessingError):
        make_client(transport).service_invoices.cancel_and_wait(COMPANY_ID, INVOICE_ID)
    transport = FakeTransport(resp(200, invoice_json(flowStatus="Cancelled")))
    inv = make_client(transport).service_invoices.cancel_and_wait(COMPANY_ID, INVOICE_ID)
    assert inv.flow_status == "Cancelled"

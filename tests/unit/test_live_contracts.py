"""Replay the redacted live-contract fixtures (2026-10-08) through the SDK, without network."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from nfeio import (
    DuplicateExternalIdError,
    InvalidRequestError,
    NotFoundError,
    PermissionDeniedError,
    ServerError,
)
from nfeio.transport import HttpResponse
from tests.helpers import COMPANY_ID, INVOICE_ID, FakeTransport, make_client, resp

FIXTURES = Path(__file__).parent.parent / "fixtures" / "live-contracts"


def _load(name: str) -> dict[str, Any]:
    data = json.loads((FIXTURES / name).read_text("utf-8"))
    return data  # type: ignore[no-any-return]


def _fill(value: Any) -> Any:
    text = json.dumps(value)
    for placeholder, real in {
        "{invoiceId}": INVOICE_ID,
        "{companyId}": COMPANY_ID,
        "{externalId}": "sdkpy-ext-1",
        "{webhookId}": "0123456789abcdef0123456789abcdef",
        "{accountId}": "acc",
        "{secret}": "whsec",
    }.items():
        text = text.replace(placeholder, real)
    return json.loads(text)


def _replay(exchange: dict[str, Any]) -> HttpResponse:
    response = _fill(exchange["response"])
    headers = response.get("headers", {})
    if "rawBody" in response:
        return resp(response["status"], body=response["rawBody"].encode(), headers=headers)
    return resp(response["status"], response.get("body"), headers=headers)


def test_service_invoice_lifecycle_contract() -> None:
    ex = _load("service-invoice-lifecycle.json")["exchanges"]
    issued = resp(200, _fill({**ex["create"]["response"]["body"], "flowStatus": "Issued"}))
    cancelled = resp(200, _fill({**ex["create"]["response"]["body"], "flowStatus": "Cancelled"}))
    transport = FakeTransport(
        _replay(ex["create"]),
        _replay(ex["findByExternalIdRightAfter202"]),
        _replay(ex["duplicateExternalId"]),
        issued,
        resp(302, headers=_fill(ex["downloadPdf"]["first"]["headers"])),
        resp(200, body=b"%PDF-1.4 synthetic", headers={"content-type": "application/pdf"}),
        _replay(ex["cancel"]),
        cancelled,
        _replay(ex["cancellationXml"]),
    )
    client = make_client(transport)
    si = client.service_invoices
    created = si.create(COMPANY_ID, {"servicesAmount": 10}, external_id="sdkpy-ext-1")
    assert created.id == INVOICE_ID and created.flow_status == "WaitingCalculateTaxes"
    assert created.borrower is not None
    assert created.borrower.federal_tax_number == "52998224725"
    assert created.provider is not None
    assert created.provider.federal_tax_number == "00000000000191"
    found = si.find_by_external_id(COMPANY_ID, "sdkpy-ext-1")
    assert found is not None and found.id == INVOICE_ID
    with pytest.raises(DuplicateExternalIdError) as dup:
        si.create(COMPANY_ID, {}, external_id="sdkpy-ext-1")
    assert dup.value.external_id == "sdkpy-ext-1"
    assert si.wait(COMPANY_ID, INVOICE_ID).flow_status == "Issued"
    assert si.download_pdf(COMPANY_ID, INVOICE_ID).startswith(b"%PDF")
    assert "Authorization" not in transport.requests[5].headers
    assert si.cancel_and_wait(COMPANY_ID, INVOICE_ID).flow_status == "Cancelled"
    assert transport.requests[6].method == "DELETE"
    with pytest.raises(NotFoundError, match="National environment only"):
        si.download_cancellation_xml(COMPANY_ID, INVOICE_ID)


def test_company_v2_contract() -> None:
    ex = _load("company-v2-crud.json")["exchanges"]
    transport = FakeTransport(
        _replay(ex["create"]),
        _replay(ex["update"]),
        _replay(ex["delete"]),
        _replay(ex["retrieveAfterDelete"]),
    )
    client = make_client(transport)
    created = client.companies.create(_fill(ex["create"]["request"]["body"]["company"]))
    assert created.id == COMPANY_ID
    assert created.federal_tax_number == "99000000000191"
    assert created.status == "Active"
    assert transport.json_body(0) == _fill(ex["create"]["request"]["body"])
    assert client.companies.update(COMPANY_ID, {"name": "x"})["tradeName"].endswith("ATUALIZADA")
    client.companies.delete(COMPANY_ID)
    assert client.companies.retrieve(COMPANY_ID).status == "Inactive"


def test_webhook_contract() -> None:
    ex = _load("webhook-crud.json")["exchanges"]
    transport = FakeTransport(
        _replay(ex["createWithUnreachableUri"]),
        _replay(ex["create"]),
        _replay(ex["update"]),
        _replay(ex["delete"]),
    )
    client = make_client(transport)
    with pytest.raises(InvalidRequestError) as info:
        client.webhooks.create({"uri": "https://example.com/x"})
    assert info.value.error_code == 40001
    assert "verification failed" in info.value.message
    hook = client.webhooks.create({"uri": "https://httpbin.org/status/200"})
    assert hook.status == "Active" and hook.content_type == "json"
    assert "whsec" not in repr(hook)
    assert client.webhooks.update(hook.id or "", {"status": "Inactive"}).status == "Inactive"
    client.webhooks.delete(hook.id or "")


def test_certificate_upload_contract() -> None:
    fixture = _load("certificate-upload-v2.json")
    transport = FakeTransport(_replay(fixture))
    with pytest.raises(ServerError) as info:
        make_client(transport).certificates.upload(COMPANY_ID, b"not-a-pfx", "pw-123")
    assert info.value.outcome_unknown
    assert len(transport.requests) == 1
    body = transport.last.body or b""
    for field in fixture["request"]["multipartFields"]:
        assert f'name="{field}"'.encode() in body


def test_cross_key_contract() -> None:
    ex = _load("auth-cross-key.json")["exchanges"]
    transport = FakeTransport(
        _replay(ex["dataKeyOnServiceInvoices"]), _replay(ex["mainKeyOnAddress"])
    )
    client = make_client(transport)
    with pytest.raises(PermissionDeniedError, match="uses api_key"):
        client.service_invoices.list(COMPANY_ID)
    with pytest.raises(PermissionDeniedError, match="data_api_key"):
        client.lookups.cep("01310100")

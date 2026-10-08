"""Write integration tests (``--run-integration --live-write`` or the NFE_* env opt-ins).

Scope authorised for phase 2, and nothing else:
  a) NFS-e in homologation **only** on NFE_COMPANY_ID, unique ``externalId`` ``sdkpy-<uuid>``,
     at most ~5 invoices in total (this module issues 2 and cancels both);
  b) create and delete ONE disposable company (``SDK-PY TESTE DESCARTAVEL <date>``);
  c) create and delete test webhooks pointing to a harmless URL (see WEBHOOK_URI).
No real certificate is uploaded. Every write has a cleanup path that also covers ambiguous
failures (the resource is looked up and removed even if the create call raised).
"""

from __future__ import annotations

import json
import random
import time
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

import pytest

from nfeio import (
    APIError,
    AsyncNfeClient,
    DuplicateExternalIdError,
    NfeClient,
    NfeError,
    ServiceInvoice,
)
from tests.live.conftest import OUT, assert_write_company, env

pytestmark = [pytest.mark.live, pytest.mark.live_write]

EVIDENCE: dict[str, Any] = {}
# example.com fails the API verification call on create (405 -> 400 code 40001), so the test
# uses a public echo endpoint that answers 2xx and stores nothing. The query marks our hooks.
WEBHOOK_URI = "https://httpbin.org/status/200?nfeio-sdkpy-test=1"


def _evidence(key: str, value: Any) -> None:
    EVIDENCE[key] = value
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "write-summary.json").write_text(
        json.dumps(EVIDENCE, indent=2, ensure_ascii=False, default=str), "utf-8"
    )


def _redact_id(value: str | None) -> str:
    return f"{value[:4]}…{value[-4:]}" if value else "None"


def _invoice_params() -> dict[str, Any]:
    return {
        "borrower": {
            "type": "NaturalPerson",
            "name": "SDK-PY Teste Tomador",
            "federalTaxNumber": 52998224725,
            "email": "sdkpy-test@example.com",
        },
        "cityServiceCode": "10677",
        "description": "Servico de teste SDK Python v0.1 (homologacao)",
        "servicesAmount": Decimal("10.00"),
    }


def _skip_if_certificate_expired(client: NfeClient, company_id: str) -> None:
    certs = client.certificates.list(company_id)
    if not certs or all(cert.is_expired() for cert in certs):
        pytest.skip("test company certificate is missing or expired")


def _cancel_safely(client: NfeClient, company_id: str, invoice_id: str) -> ServiceInvoice:
    """Wait for a terminal issuance status, then cancel and wait for ``Cancelled``."""
    current = client.service_invoices.wait(
        company_id, invoice_id, timeout=180, raise_on_failure=False
    )
    if current.flow_status != "Issued":
        return current
    return client.service_invoices.cancel_and_wait(
        company_id, invoice_id, timeout=180, raise_on_failure=False
    )


def test_service_invoice_lifecycle(client: NfeClient, company_id: str) -> None:
    assert_write_company(company_id)
    _skip_if_certificate_expired(client, company_id)
    external_id = f"sdkpy-{uuid.uuid4()}"
    issued_id: str | None = None
    try:
        created = client.service_invoices.create(
            company_id, _invoice_params(), external_id=external_id
        )
        issued_id = created.id
        assert issued_id
        assert created.last_response is not None
        _evidence(
            "nfse_create",
            {
                "status": created.last_response.status_code,
                "location_present": "location" in created.last_response.headers,
                "location_scheme": created.last_response.headers.get("location", "").split(":")[0],
                "body_keys": sorted(created.keys()),
                "flowStatus": created.flow_status,
                "invoice_id": _redact_id(issued_id),
            },
        )

        started = time.monotonic()
        immediate = client.service_invoices.find_by_external_id(company_id, external_id)
        found = immediate or client.service_invoices.find_by_external_id(
            company_id, external_id, wait=30
        )
        _evidence(
            "nfse_find_by_external_id",
            {
                "found_immediately": immediate is not None,
                "found": found is not None,
                "seconds_until_found": round(time.monotonic() - started, 2),
            },
        )
        assert found is not None and found.id == issued_id

        try:
            duplicate = client.service_invoices.create(
                company_id, _invoice_params(), external_id=external_id
            )
        except DuplicateExternalIdError as dup:
            _evidence(
                "nfse_duplicate",
                {
                    "status": dup.status_code,
                    "error_code": dup.error_code,
                    "message": dup.message.replace(external_id, "<EXT>"),
                },
            )
        else:  # the API accepted a duplicate: clean it up and fail loudly
            if duplicate.id:
                _cancel_safely(client, company_id, duplicate.id)
            pytest.fail("API accepted a duplicated externalId")

        issued = client.service_invoices.wait(
            company_id, issued_id, timeout=180, raise_on_failure=False
        )
        _evidence(
            "nfse_wait", {"flowStatus": issued.flow_status, "flowMessage": issued.flow_message}
        )
        assert issued.flow_status == "Issued"
        assert issued.services_amount == Decimal("10.00")
        assert issued.borrower is not None
        assert issued.borrower.federal_tax_number == "52998224725"

        pdf = client.service_invoices.download_pdf(company_id, issued_id)
        xml = client.service_invoices.download_xml(company_id, issued_id)
        _evidence(
            "nfse_downloads",
            {
                "pdf_head": pdf[:8].decode("latin-1"),
                "pdf_bytes": len(pdf),
                "xml_head": xml[:12].decode("utf-8", "replace"),
                "xml_bytes": len(xml),
            },
        )
        assert pdf.startswith(b"%PDF")

        cancelled = client.service_invoices.cancel(company_id, issued_id)
        _evidence(
            "nfse_cancel",
            {
                "status": cancelled.last_response.status_code if cancelled.last_response else None,
                "location_present": bool(
                    cancelled.last_response and "location" in cancelled.last_response.headers
                ),
                "body_keys": sorted(cancelled.keys()),
                "flowStatus": cancelled.flow_status,
            },
        )
        final = client.service_invoices.wait(
            company_id, issued_id, timeout=180, raise_on_failure=False
        )
        deadline = time.monotonic() + 180
        while final.flow_status != "Cancelled" and time.monotonic() < deadline:
            time.sleep(3)
            final = client.service_invoices.retrieve(company_id, issued_id)
        _evidence("nfse_cancel_final", {"flowStatus": final.flow_status})
        assert final.flow_status == "Cancelled"
        try:
            xml = client.service_invoices.download_cancellation_xml(company_id, issued_id)
            _evidence("nfse_cancellation_xml", {"bytes": len(xml)})
        except APIError as exc:
            _evidence(
                "nfse_cancellation_xml",
                {"error": type(exc).__name__, "status": exc.status_code, "message": exc.message},
            )
    finally:
        if issued_id is None:  # ambiguous create: reconcile by externalId (recipe D5)
            leftover = client.service_invoices.find_by_external_id(company_id, external_id, wait=30)
            issued_id = leftover.id if leftover is not None else None
        if issued_id is not None:
            state = client.service_invoices.retrieve(company_id, issued_id)
            if state.flow_status != "Cancelled":
                _cancel_safely(client, company_id, issued_id)


async def test_async_create_and_cancel_and_wait(company_id: str) -> None:
    assert_write_company(company_id)
    async with AsyncNfeClient(api_key=env("NFE_API_KEY")) as client:
        certs = await client.certificates.list(company_id)
        if not certs or all(cert.is_expired() for cert in certs):
            pytest.skip("test company certificate is missing or expired")
        external_id = f"sdkpy-{uuid.uuid4()}"
        invoice_id: str | None = None
        try:
            created = await client.service_invoices.create(
                company_id, _invoice_params(), external_id=external_id
            )
            invoice_id = created.id
            assert invoice_id
            issued = await client.service_invoices.wait(
                company_id, invoice_id, timeout=180, raise_on_failure=False
            )
            assert issued.flow_status == "Issued"
            cancelled = await client.service_invoices.cancel_and_wait(
                company_id, invoice_id, timeout=180
            )
            _evidence(
                "nfse_async",
                {
                    "issued": issued.flow_status,
                    "cancelled": cancelled.flow_status,
                    "invoice_id": _redact_id(invoice_id),
                },
            )
            assert cancelled.flow_status == "Cancelled"
        finally:
            if invoice_id is None:
                found = await client.service_invoices.find_by_external_id(
                    company_id, external_id, wait=30
                )
                invoice_id = found.id if found is not None else None
            if invoice_id is not None:
                state = await client.service_invoices.retrieve(company_id, invoice_id)
                if state.flow_status == "Issued":
                    await client.service_invoices.cancel_and_wait(
                        company_id, invoice_id, timeout=180, raise_on_failure=False
                    )


def _disposable_cnpj() -> str:
    """A random CNPJ with valid check digits, branch 0001, starting with 99 (test only)."""
    from nfeio._core.paths import _cnpj_check_digit

    rng = random.SystemRandom()
    body = "99" + "".join(str(rng.randrange(10)) for _ in range(6)) + "0001"
    first = _cnpj_check_digit(body)
    second = _cnpj_check_digit(body + str(first))
    return f"{body}{first}{second}"


def _find_company(client: NfeClient, name: str, cnpj: str) -> str | None:
    for company in client.companies.list(limit=50).auto_paging_iter():
        if company["name"] == name and company.federal_tax_number == cnpj:
            return company.id
    return None


def test_disposable_company_crud(client: NfeClient) -> None:
    today = date.today().isoformat()
    name = f"SDK-PY TESTE DESCARTAVEL {today}"
    cnpj = _disposable_cnpj()
    params: dict[str, Any] = {
        "name": name,
        "tradeName": name,
        "federalTaxNumber": int(cnpj),
        "taxRegime": "SimplesNacional",
        "address": {
            "country": "BRA",
            "postalCode": "80010000",
            "street": "Rua Teste",
            "number": "1",
            "district": "Centro",
            "state": "PR",
            "city": {"code": "4106902", "name": "Curitiba"},
        },
    }
    created_id: str | None = None
    create_failed = False
    try:
        try:
            created = client.companies.create(params)
        except NfeError:
            create_failed = True
            raise
        created_id = created.id
        _evidence(
            "company_create",
            {
                "status": created.last_response.status_code if created.last_response else None,
                "company_id": _redact_id(created_id),
                "body_keys": sorted(created.keys()),
                "federalTaxNumber_type": type(created["federalTaxNumber"]).__name__,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        assert created_id
        assert created.federal_tax_number == cnpj
        fetched = client.companies.retrieve(created_id)
        assert fetched["name"] == name
        updated = client.companies.update(created_id, {**params, "tradeName": name + " ATUALIZADA"})
        _evidence(
            "company_update",
            {
                "status": updated.last_response.status_code if updated.last_response else None,
                "tradeName_updated": updated["tradeName"] == name + " ATUALIZADA",
            },
        )
        assert updated["tradeName"] == name + " ATUALIZADA"
        try:
            client.certificates.upload(
                created_id, b"not-a-real-pfx", "not-a-real-password", filename="fake.pfx"
            )
            _evidence("certificate_upload_garbage", {"result": "accepted (unexpected)"})
        except NfeError as exc:
            _evidence(
                "certificate_upload_garbage",
                {
                    "error": type(exc).__name__,
                    "status": getattr(exc, "status_code", None),
                    "message": exc.message,
                },
            )
    finally:
        if created_id is None and create_failed:
            created_id = _find_company(client, name, cnpj)
        if created_id:
            client.companies.delete(created_id)
            _evidence("company_delete", {"company_id": _redact_id(created_id), "deleted": True})
    # DELETE /v2/companies/{id} is a soft delete (probe 2026-10-08): 204, then the company is
    # still listed and retrievable with status "Inactive"; a second DELETE is also 204.
    if created_id:
        assert client.companies.retrieve(created_id).status == "Inactive"


def test_webhook_crud(client: NfeClient) -> None:
    params: dict[str, Any] = {
        "uri": WEBHOOK_URI,
        "secret": f"sdkpy-{uuid.uuid4().hex}",
        "contentType": "json",
        "insecureSsl": False,
        "status": "Inactive",
        "filters": ["service_invoice.issued_successfully"],
    }
    hook_id: str | None = None
    try:
        created = client.webhooks.create(params)
        hook_id = created.id
        _evidence(
            "webhook_create",
            {
                "status": created.last_response.status_code if created.last_response else None,
                "body_keys": sorted(created.keys()),
                "wire_status": created.status,
                "contentType": created.content_type,
                "secret_echoed": "secret" in created,
            },
        )
        assert hook_id
        fetched = client.webhooks.retrieve(hook_id)
        assert fetched["uri"] == WEBHOOK_URI
        updated = client.webhooks.update(hook_id, {**params, "uri": WEBHOOK_URI + "&v=2"})
        assert updated["uri"].endswith("&v=2")
        _evidence("webhook_update", {"wire_status": updated.status})
    finally:
        if hook_id is None:
            hook_id = next(
                (h.id for h in client.webhooks.list() if str(h["uri"]).startswith(WEBHOOK_URI)),
                None,
            )
        if hook_id:
            client.webhooks.delete(hook_id)
            _evidence("webhook_delete", {"deleted": True})
    assert all(not str(h["uri"]).startswith(WEBHOOK_URI) for h in client.webhooks.list())

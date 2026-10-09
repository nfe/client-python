"""Read-only integration tests (NFE_RUN_INTEGRATION=1)."""

from __future__ import annotations

import pytest

from nfeio import (
    AsyncNfeClient,
    NfeClient,
    NotFoundError,
    PermissionDeniedError,
    RequestOptions,
)
from tests.live.conftest import env

pytestmark = pytest.mark.live


def test_auth_by_family(client: NfeClient) -> None:
    assert isinstance(client.webhooks.list(), list)
    if not env("NFE_DATA_API_KEY"):
        pytest.skip("NFE_DATA_API_KEY not available")
    address = client.lookups.cep("01310-100")
    assert address.postal_code == "01310100"
    assert address["city"]["code"] == "3550308"
    with pytest.raises(PermissionDeniedError, match="data_api_key"):
        client.lookups.cep("01310100", options=RequestOptions(api_key=env("NFE_API_KEY")))


def test_service_invoices_reject_data_key(client: NfeClient, company_id: str) -> None:
    if not env("NFE_DATA_API_KEY"):
        pytest.skip("NFE_DATA_API_KEY not available")
    with pytest.raises(PermissionDeniedError) as info:
        client.service_invoices.list(
            company_id, options=RequestOptions(api_key=env("NFE_DATA_API_KEY"))
        )
    assert info.value.request_id


def test_companies_v2_full_sweep(client: NfeClient) -> None:
    first = client.companies.list(limit=50)
    seen: list[str] = []
    for company in first.auto_paging_iter():
        assert company.id
        seen.append(company.id)
    assert len(seen) == len(set(seen)), "duplicated companies while paging"
    assert len(seen) > 50


def test_company_retrieve(client: NfeClient, company_id: str) -> None:
    company = client.companies.retrieve(company_id)
    assert company.id == company_id
    assert company.federal_tax_number is not None and len(company.federal_tax_number) == 14
    assert company.created_on is not None and company.created_on.tzinfo is not None
    with pytest.raises(NotFoundError):
        client.companies.retrieve("0" * 32)


def test_service_invoices_read(client: NfeClient, company_id: str) -> None:
    page = client.service_invoices.list(company_id, page_count=5)
    assert page.last_response.request_id
    issued = next((inv for inv in page if inv.flow_status == "Issued"), None)
    assert len(page) <= 5
    if issued is None:
        pytest.skip("no issued invoice to read")
    assert issued.id is not None
    again = client.service_invoices.retrieve(company_id, issued.id)
    assert again.id == issued.id
    assert again.services_amount is not None
    pdf = client.service_invoices.download_pdf(company_id, issued.id)
    assert pdf.startswith(b"%PDF")
    xml = client.service_invoices.download_xml(company_id, issued.id)
    assert xml.lstrip().startswith(b"<")
    assert client.service_invoices.find_by_external_id(company_id, "sdkpy-missing-0000") is None
    with pytest.raises(NotFoundError):
        client.service_invoices.retrieve(company_id, "0" * 24)


def test_certificates_read(client: NfeClient, company_id: str) -> None:
    certs = client.certificates.list(company_id)
    assert certs, "test company should have a certificate"
    assert certs[0].expires_on is not None


def test_webhooks_read(client: NfeClient) -> None:
    hooks = client.webhooks.list()
    for hook in hooks:
        assert hook.id
    types = client.webhooks.event_types()
    assert any(t.id == "service_invoice.issued_successfully" for t in types)


def test_lookups(client: NfeClient) -> None:
    if not env("NFE_DATA_API_KEY"):
        pytest.skip("NFE_DATA_API_KEY not available")
    entity = client.lookups.cnpj("00.000.000/0001-91")
    assert entity.federal_tax_number == "00000000000191"
    assert entity["name"]
    taxes = client.lookups.cnpj_state_taxes("00000000000191", "DF")
    assert taxes.federal_tax_number == "00000000000191"
    with pytest.raises(NotFoundError) as info:
        client.lookups.cpf("52998224725", "1990-01-01")
    assert info.value.error_code == 40401


async def test_async_client_live() -> None:
    async with AsyncNfeClient(
        api_key=env("NFE_API_KEY"), data_api_key=env("NFE_DATA_API_KEY") or None
    ) as client:
        hooks = await client.webhooks.list()
        assert isinstance(hooks, list)
        page = await client.companies.list(limit=2)
        assert len(page) == 2

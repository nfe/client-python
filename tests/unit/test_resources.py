"""Companies v2, certificates, account webhooks and data lookups against scripted responses."""

from __future__ import annotations

import io
from datetime import date
from pathlib import Path

import pytest

from nfeio import (
    Address,
    Certificate,
    Company,
    InvalidParameterError,
    LegalEntity,
    NaturalPerson,
    NotFoundError,
    ServerError,
    Webhook,
)
from tests.helpers import API_KEY, COMPANY_ID, DATA_KEY, FakeTransport, make_client, resp

COMPANY = {
    "id": COMPANY_ID,
    "accountId": "acc1",
    "name": "SDK-PY TESTE",
    "federalTaxNumber": 191,
    "taxRegime": "SimplesNacional",
    "status": "Active",
    "municipalTaxes": [],
    "stateTaxes": [],
    "createdOn": "2026-10-08T12:00:00.123+00:00",
}

# -- companies ---------------------------------------------------------------------------------


def test_company_crud_envelopes() -> None:
    transport = FakeTransport(
        resp(201, {"company": COMPANY}),
        resp(200, {"company": COMPANY}),
        resp(200, {"company": {**COMPANY, "name": "NOVO"}}),
        resp(204),
    )
    client = make_client(transport)
    params = {
        "name": "SDK-PY TESTE",
        "federalTaxNumber": 191,
        "taxRegime": "SimplesNacional",
        "address": {"state": "SP", "city": {"code": "3550308", "name": "São Paulo"}},
    }
    created = client.companies.create(params)
    assert isinstance(created, Company) and created.id == COMPANY_ID
    assert created.federal_tax_number == "00000000000191"
    assert transport.json_body(0) == {"company": params}
    assert transport.requests[0].url == "https://api.nfse.io/v2/companies"
    assert client.companies.retrieve(COMPANY_ID).account_id == "acc1"
    updated = client.companies.update(COMPANY_ID, {"name": "NOVO"})
    assert updated["name"] == "NOVO"
    assert transport.requests[2].method == "PUT"
    assert transport.json_body(2) == {"company": {"name": "NOVO"}}
    client.companies.delete(COMPANY_ID)
    assert transport.requests[3].method == "DELETE"
    assert transport.paths()[3] == f"/v2/companies/{COMPANY_ID}"
    assert all(r.headers["Authorization"] == API_KEY for r in transport.requests)


def test_company_not_found_code() -> None:
    body = b'{"errors":[{"code":40401,"message":"company id not found"}]}'
    with pytest.raises(NotFoundError) as info:
        make_client(FakeTransport(resp(404, body=body))).companies.retrieve(COMPANY_ID)
    assert info.value.error_code == 40401


def test_company_params_must_be_mapping() -> None:
    with pytest.raises(InvalidParameterError):
        make_client(FakeTransport()).companies.create(["x"])  # type: ignore[arg-type]


def test_company_tolerates_unwrapped_object() -> None:
    company = make_client(FakeTransport(resp(200, COMPANY))).companies.retrieve(COMPANY_ID)
    assert company.id == COMPANY_ID


# -- certificates ------------------------------------------------------------------------------


def _parts(body: bytes) -> bytes:
    return body


def test_certificate_upload_from_path(tmp_path: Path) -> None:
    pfx = tmp_path / "cert.pfx"
    pfx.write_bytes(b"\x30\x82PFXDATA")
    cert_json = {
        "certificate": {
            "thumbprint": "AB12",
            "status": "Active",
            "validUntil": "2027-01-01T00:00:00Z",
        }
    }
    transport = FakeTransport(resp(200, cert_json))
    cert = make_client(transport).certificates.upload(COMPANY_ID, pfx, "s3cr3t-pw")
    assert isinstance(cert, Certificate) and cert.thumbprint == "AB12"
    req = transport.last
    assert req.url == f"https://api.nfse.io/v2/companies/{COMPANY_ID}/certificates"
    assert req.headers["Content-Type"].startswith("multipart/form-data; boundary=")
    body = req.body or b""
    assert b'name="file"; filename="cert.pfx"' in body
    assert b"Content-Type: application/x-pkcs12" in body
    assert b"\x30\x82PFXDATA" in body
    assert b'name="password"\r\n\r\ns3cr3t-pw\r\n' in body


def test_certificate_upload_from_bytes_and_fileobj() -> None:
    transport = FakeTransport(resp(200, {"certificate": {}}), resp(200, {"certificate": {}}))
    client = make_client(transport)
    client.certificates.upload(COMPANY_ID, b"PFX", "pw-123", filename="a.p12")
    assert b'filename="a.p12"' in (transport.last.body or b"")
    client.certificates.upload(COMPANY_ID, io.BytesIO(b"PFX2"), "pw-123")
    assert b"PFX2" in (transport.last.body or b"")


@pytest.mark.parametrize(
    ("file", "password"),
    [
        (b"", "pw"),
        (b"x" * (1024 * 1024 + 1), "pw"),
        (b"x", ""),
        (123, "pw"),
        ("/nonexistent/x.pfx", "pw"),
    ],
    # Short ids: pytest puts the id in PYTEST_CURRENT_TEST, and Windows rejects environment
    # variables longer than 32,767 characters (the 1 MiB value would be the id).
    ids=["empty-file", "file-over-1mib", "empty-password", "not-bytes-or-path", "missing-path"],
)
def test_certificate_local_validation(file: object, password: str) -> None:
    transport = FakeTransport()
    with pytest.raises(InvalidParameterError):
        make_client(transport).certificates.upload(COMPANY_ID, file, password)  # type: ignore[arg-type]
    assert transport.requests == []


def test_certificate_text_fileobj_rejected() -> None:
    with pytest.raises(InvalidParameterError):
        make_client(FakeTransport()).certificates.upload(COMPANY_ID, io.StringIO("x"), "pw")  # type: ignore[arg-type]


def test_certificate_upload_500_not_retried_and_password_hidden() -> None:
    body = b'{"title":"An error occurred while processing your request. pw=s3cr3t-pw","status":500}'
    transport = FakeTransport(resp(500, body=body))
    with pytest.raises(ServerError) as info:
        make_client(transport).certificates.upload(COMPANY_ID, b"PFX", "s3cr3t-pw")
    assert len(transport.requests) == 1
    err = info.value
    for text in (str(err), repr(err), err.message):
        assert "s3cr3t-pw" not in text
    assert b"s3cr3t-pw" not in err.body


def test_certificate_list() -> None:
    transport = FakeTransport(
        resp(
            200, {"certificates": [{"thumbprint": "A", "validUntil": "2026-11-03T16:18:00+00:00"}]}
        ),
        resp(200, {"certificates": []}),
    )
    client = make_client(transport)
    certs = client.certificates.list(COMPANY_ID)
    assert len(certs) == 1 and certs[0].expires_on is not None
    assert client.certificates.list(COMPANY_ID) == []


# -- webhooks ----------------------------------------------------------------------------------

HOOK_ID = "9dd4c3e9df4043adb11df22dcd9d8ce1"
HOOK: dict[str, object] = {
    "id": HOOK_ID,
    "uri": "https://example.com/nfeio-sdkpy-test",
    "contentType": "json",
    "insecureSsl": False,
    "status": "Active",
    "filters": ["service_invoice.issued_successfully"],
    "createdOn": "2026-01-01T00:00:00Z",
}


def test_webhook_crud() -> None:
    transport = FakeTransport(
        resp(200, {"webHooks": [HOOK]}),
        resp(200, {"webHook": HOOK}),
        resp(201, {"webHook": HOOK}),
        resp(200, {"webHook": HOOK}),
        resp(204),
        resp(204),
    )
    client = make_client(transport)
    hooks = client.webhooks.list()
    assert isinstance(hooks[0], Webhook)
    assert hooks[0].content_type == "json" and hooks[0].status == "Active"
    assert client.webhooks.retrieve(HOOK_ID).id == HOOK_ID
    params = {
        "uri": "https://erp.exemplo/hook",
        "secret": "abc",
        "filters": ["service_invoice.issued_successfully"],
    }
    client.webhooks.create(params)
    assert transport.json_body(2) == {"webHook": params}
    client.webhooks.update(HOOK_ID, {"uri": "https://novo"})
    assert transport.json_body(3) == {"webHook": {"uri": "https://novo"}}
    assert transport.requests[3].method == "PUT"
    client.webhooks.delete(HOOK_ID)
    client.webhooks.ping(HOOK_ID)
    assert transport.paths()[5] == f"/v2/webhooks/{HOOK['id']}/pings"
    assert transport.requests[5].method == "PUT"
    assert all(r.url.startswith("https://api.nfse.io/v2/webhooks") for r in transport.requests)


def test_webhook_event_types_free_text_ids() -> None:
    types = [{"id": f"evt.{i}"} for i in range(46)] + [
        {"id": "legal_entity_taxpayer:updated_sucessfully"}
    ]
    transport = FakeTransport(resp(200, {"eventTypes": types}))
    result = make_client(transport).webhooks.event_types()
    assert len(result) == 47 and result[-1].id == "legal_entity_taxpayer:updated_sucessfully"
    assert transport.paths() == ["/v2/webhooks/eventtypes"]


def test_no_delete_all_webhooks() -> None:
    client = make_client(FakeTransport())
    assert not hasattr(client.webhooks, "delete_all")
    with pytest.raises(TypeError):
        client.webhooks.delete()  # type: ignore[call-arg]


# -- lookups -----------------------------------------------------------------------------------


def test_cnpj_lookup() -> None:
    entity = {
        "legalEntity": {
            "federalTaxNumber": "00000000000191",
            "name": "BANCO",
            "shareCapital": 1000.5,
            "status": "Active",
            "openedOn": "1966-08-01T00:00:00Z",
        }
    }
    transport = FakeTransport(resp(200, entity), resp(200, entity))
    client = make_client(transport)
    result = client.lookups.cnpj("00.000.000/0001-91")
    assert isinstance(result, LegalEntity)
    assert result.federal_tax_number == "00000000000191"
    assert str(result.share_capital) == "1000.5"
    assert result.opened_on is not None and result.opened_on.year == 1966
    req = transport.requests[0]
    assert req.url == "https://legalentity.api.nfe.io/v3/legalentities/basicInfo/00000000000191"
    assert req.headers["Authorization"] == DATA_KEY
    client.lookups.cnpj("12.ABC.345/01DE-35", update_address=False, update_city_code=True)
    assert transport.requests[1].url.endswith(
        "/basicInfo/12ABC34501DE35?updateAddress=false&updateCityCode=true"
    )


def test_cnpj_invalid_never_requested() -> None:
    transport = FakeTransport()
    with pytest.raises(InvalidParameterError):
        make_client(transport).lookups.cnpj("00000000000100")
    with pytest.raises(InvalidParameterError):
        make_client(transport).lookups.cnpj_state_taxes("00000000000191", "XX")
    assert transport.requests == []


def test_cnpj_state_taxes() -> None:
    transport = FakeTransport(
        resp(
            200,
            {
                "legalEntity": {
                    "federalTaxNumber": "00000000000191",
                    "stateTaxes": [{"taxNumber": "1"}],
                }
            },
        )
    )
    result = make_client(transport).lookups.cnpj_state_taxes("00000000000191", "sp")
    assert result["stateTaxes"][0]["taxNumber"] == "1"
    assert transport.paths() == ["/v3/legalentities/stateTaxInfo/SP/00000000000191"]


def test_cpf_lookup() -> None:
    transport = FakeTransport(
        resp(
            200,
            {
                "federalTaxNumber": "52998224725",
                "status": "Regular",
                "birthOn": "1990-01-01T00:00:00",
            },
        ),
        resp(404, body=b'{"errors":[{"code":40401,"message":"not found"}]}'),
    )
    client = make_client(transport)
    person = client.lookups.cpf("529.982.247-25", date(1990, 1, 1))
    assert isinstance(person, NaturalPerson) and person.status == "Regular"
    assert person.birth_on is not None and person.birth_on.year == 1990
    assert transport.requests[0].url == (
        "https://naturalperson.api.nfe.io/v1/naturalperson/status/52998224725/1990-01-01"
    )
    with pytest.raises(NotFoundError) as info:
        client.lookups.cpf("52998224725", "1990-01-02")
    assert info.value.error_code == 40401
    with pytest.raises(InvalidParameterError):
        client.lookups.cpf("52998224725", "01/01/1990")


def test_cep_lookup() -> None:
    body = {
        "address": {
            "state": "SP",
            "city": {"code": "3550308", "name": "São Paulo"},
            "postalCode": "01310-100",
            "street": "Paulista",
        }
    }
    transport = FakeTransport(resp(200, body))
    address = make_client(transport).lookups.cep("01310-100")
    assert isinstance(address, Address)
    assert transport.requests[0].url == "https://address.api.nfe.io/v2/addresses/01310100"
    assert address["city"]["code"] == "3550308"
    assert address["state"] == "SP" and address["city"]["name"] == "São Paulo"
    assert address.postal_code == "01310100"
    assert not hasattr(make_client(FakeTransport()).lookups, "search")

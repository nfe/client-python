from __future__ import annotations

import copy
import json
import pickle
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from nfeio import Certificate, Company, NfeObject, ServiceInvoice
from nfeio.models import Address, LegalEntity, Party
from nfeio.models._base import normalize_document, parse_datetime, to_decimal
from tests.helpers import invoice_json


def test_unknown_field_preserved() -> None:
    inv = ServiceInvoice(invoice_json(novoCampo=1))
    assert inv["novoCampo"] == 1
    assert inv.to_dict()["novoCampo"] == 1


def test_typed_properties() -> None:
    inv = ServiceInvoice(invoice_json())
    assert inv.id == "fedcba9876543210fedcba98"
    assert inv.flow_status == "Issued"
    assert inv.flow_message is None
    assert inv.services_amount == Decimal("1234.56")
    assert inv.iss_rate == Decimal("0.02")
    assert inv.iss_tax_amount == Decimal("24.69")
    assert inv.issued_on == datetime(2026, 9, 1, 2, 55, 33, 418000, tzinfo=timezone.utc)
    assert inv.created_on == datetime(2026, 9, 1, 2, 55, 30, 123456, tzinfo=timezone.utc)
    assert inv.cancelled_on is None
    assert inv.borrower is not None and inv.borrower.federal_tax_number == "52998224725"
    assert inv.provider is not None and inv.provider.federal_tax_number == "00000000000191"
    assert isinstance(inv.borrower, Party)


def test_nested_by_key_is_nfeobject_and_to_dict_is_plain() -> None:
    inv = ServiceInvoice(invoice_json())
    borrower = inv["borrower"]
    assert isinstance(borrower, NfeObject) and not isinstance(borrower, Party)
    assert inv["borrower"]["address"]["city"]["code"] == "3550308"
    plain = inv.to_dict()
    assert type(plain["borrower"]) is dict
    json.dumps(plain)


def test_mapping_method_names_are_not_shadowed() -> None:
    obj = NfeObject({"items": [{"code": "1"}], "keys": "k", "get": "g"})
    assert obj["items"][0]["code"] == "1"
    assert callable(obj.items) and ("items", obj["items"]) in list(obj.items())
    assert obj.get("keys") == "k"
    assert set(obj.keys()) == {"items", "keys", "get"}
    with pytest.raises(AttributeError):
        obj.flowStatus  # type: ignore[attr-defined]  # noqa: B018 - no __getattr__ magic


def test_immutability() -> None:
    obj = NfeObject({"filters": ["a"], "nested": {"x": 1}})
    filters = obj["filters"]
    filters.append("b")
    assert obj["filters"] == ["a"]
    assert obj.to_dict()["filters"] == ["a"]
    with pytest.raises(TypeError):
        obj["x"] = 1  # type: ignore[index]
    with pytest.raises(AttributeError):
        obj.foo = 1
    with pytest.raises(AttributeError):
        ServiceInvoice({}).id = "x"
    source = {"a": {"b": 1}}
    built = NfeObject(source)
    source["a"]["b"] = 2
    assert built["a"]["b"] == 1
    out = built.to_dict()
    out["a"]["b"] = 3
    assert built["a"]["b"] == 1


def test_equality_and_copy() -> None:
    a = NfeObject({"x": {"y": [1, 2]}})
    assert a == {"x": {"y": [1, 2]}}
    assert a == NfeObject({"x": {"y": [1, 2]}})
    assert a != {"x": 1}
    assert a != 5
    assert a == {"x": NfeObject({"y": [1, 2]})}
    assert copy.copy(a) is a
    assert copy.deepcopy(a) == a
    # Round-trip of an object created right here (trusted data); the SDK never unpickles.
    restored = pickle.loads(pickle.dumps(ServiceInvoice(invoice_json())))  # noqa: S301
    assert isinstance(restored, ServiceInvoice) and restored.flow_status == "Issued"
    with pytest.raises(TypeError):
        hash(a)
    assert len(a) == 1 and "x" in a and list(a) == ["x"]


def test_repr_masks_secrets() -> None:
    obj = NfeObject({"webHook": {"Secret": "super-secret-value", "uri": "https://x"}})
    company = Company({"loginPassword": "p@ss", "name": "ACME"})
    assert "super-secret-value" not in repr(obj)
    assert "p@ss" not in repr(company)
    assert "ACME" in repr(company)
    assert obj.to_dict()["webHook"]["Secret"] == "super-secret-value"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2026-09-01T02:55:33.418+00:00", datetime(2026, 9, 1, 2, 55, 33, 418000, timezone.utc)),
        ("2026-09-01T02:55:33Z", datetime(2026, 9, 1, 2, 55, 33, tzinfo=timezone.utc)),
        (
            "2026-06-11T01:21:16.6890073+00:00",
            datetime(2026, 6, 11, 1, 21, 16, 689007, timezone.utc),
        ),
        ("2026-09-01", datetime(2026, 9, 1, tzinfo=timezone.utc)),
        ("2026-09-01T10:00:00", datetime(2026, 9, 1, 10, tzinfo=timezone.utc)),
        ("2026-09-01T10:00:00-03:00", datetime(2026, 9, 1, 13, tzinfo=timezone.utc)),
        ("2026-09-01T10:00:00-0300", datetime(2026, 9, 1, 13, tzinfo=timezone.utc)),
        ("2026-09-01 10:00", datetime(2026, 9, 1, 10, tzinfo=timezone.utc)),
    ],
)
def test_parse_datetime(text: str, expected: datetime) -> None:
    parsed = parse_datetime(text)
    assert parsed == expected
    assert parsed is not None and parsed.tzinfo is not None


@pytest.mark.parametrize(
    "text", ["", "ontem", "2026-13-01", "2026-09-01T25:00:00", "2026-09-01T10:00+25:00"]
)
def test_parse_datetime_invalid(text: str) -> None:
    assert parse_datetime(text) is None
    inv = ServiceInvoice({"createdOn": text})
    assert inv.created_on is None
    assert inv["createdOn"] == text


def test_decimal_conversion() -> None:
    assert to_decimal(1234.56) == Decimal("1234.56")
    assert to_decimal(0.1) == Decimal("0.1")
    assert to_decimal(100) == Decimal(100)
    assert to_decimal("10.50") == Decimal("10.50")
    for bad in [True, None, "abc", float("inf"), "NaN", [1]]:
        assert to_decimal(bad) is None


def test_document_normalisation() -> None:
    assert normalize_document(191, "cnpj") == "00000000000191"
    assert normalize_document("00.000.000/0001-91", "cnpj") == "00000000000191"
    assert normalize_document(52998224725, "cpf") == "52998224725"
    assert normalize_document(1234, "auto", "LegalEntity") == "00000000001234"
    assert normalize_document(1234, "auto", "NaturalPerson") == "00000001234"
    assert normalize_document(12345678000195, "auto") == "12345678000195"
    assert normalize_document("12ABC34501DE35", "auto") == "12ABC34501DE35"
    assert normalize_document("01310-100", "cep") == "01310100"
    for bad in [True, -1, "", "#$", 1.5, None]:
        assert normalize_document(bad, "auto") is None
    assert Company({"federalTaxNumber": 191}).federal_tax_number == "00000000000191"
    assert (
        LegalEntity({"federalTaxNumber": "00000000000191"}).federal_tax_number == "00000000000191"
    )
    assert Address({"postalCode": "01310-100"}).postal_code == "01310100"


def test_company_does_not_expose_municipal_tax_number() -> None:
    company = Company(
        {
            "id": "c1",
            "municipalTaxNumber": "0a1b2c3d4e5f60718293a4b5c6d7e8f9",
            "municipalTaxes": ["2693cd58b26f404aa3b434fc4035d1af"],
            "stateTaxes": [{"id": "st1"}, 3],
        }
    )
    assert not hasattr(company, "municipal_tax_number")
    assert company["municipalTaxNumber"] == "0a1b2c3d4e5f60718293a4b5c6d7e8f9"
    assert company.municipal_tax_ids == ["2693cd58b26f404aa3b434fc4035d1af"]
    assert company.state_tax_ids == ["st1"]
    assert Company({"municipalTaxes": "x"}).municipal_tax_ids is None


def test_certificate_expiration() -> None:
    cert = Certificate({"validUntil": "2026-11-03T16:18:00+00:00", "taxId": "00000000000191"})
    assert cert.expires_on == datetime(2026, 11, 3, 16, 18, tzinfo=timezone.utc)
    assert cert.is_expired(at=datetime(2026, 12, 1, tzinfo=timezone.utc))
    assert not cert.is_expired(at=datetime(2026, 10, 8, tzinfo=timezone.utc))
    assert not cert.is_expired(at=datetime(2026, 10, 8))  # naive = UTC
    assert Certificate({"expiresOn": "2030-01-01T00:00:00Z"}).expires_on is not None
    assert Certificate({}).is_expired()
    future = datetime.now(timezone.utc) + timedelta(days=30)
    assert not Certificate({"validUntil": future.isoformat()}).is_expired()
    assert cert.tax_id == "00000000000191"


def test_field_descriptor_on_class() -> None:
    from nfeio.models._base import Field, iter_fields

    assert isinstance(ServiceInvoice.flow_status, Field)
    names = dict(iter_fields(ServiceInvoice))
    assert names["flow_status"].wire_keys == ("flowStatus",)
    assert dict(iter_fields(Certificate))["expires_on"].wire_keys == ("validUntil", "expiresOn")

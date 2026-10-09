from __future__ import annotations

import json
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from nfeio import InvalidParameterError
from nfeio._core import jsonutil, multipart, paths
from tests.helpers import COMPANY_ID, FakeTransport, make_client


@pytest.mark.parametrize(
    "value",
    ["../../v2/webhooks", "..", ".", "", "a/b", "a b", "x" * 65, "abc%2F", "a\nb", 123, None],
    ids=[
        "traversal",
        "dotdot",
        "dot",
        "empty",
        "slash",
        "space",
        "65-chars",
        "percent-encoded",
        "newline",
        "int",
        "none",
    ],
)
def test_opaque_id_rejects(value: object) -> None:
    with pytest.raises(InvalidParameterError):
        paths.opaque_id(value, "invoice_id")


@pytest.mark.parametrize("value", ["5f0e3b1a2c4d5e6f7a8b9c0d", COMPANY_ID, "A-b_9"])
def test_opaque_id_accepts(value: str) -> None:
    assert paths.opaque_id(value, "id") == value


def test_path_traversal_never_reaches_transport() -> None:
    transport = FakeTransport()
    client = make_client(transport)
    with pytest.raises(InvalidParameterError):
        client.service_invoices.retrieve(COMPANY_ID, "../../v2/webhooks")
    with pytest.raises(InvalidParameterError):
        client.service_invoices.retrieve("../x", "abc")
    with pytest.raises(InvalidParameterError):
        client.webhooks.delete("a/b")
    assert transport.requests == []


@pytest.mark.parametrize(
    ("value", "encoded"),
    [("pedido/123", "pedido%2F123"), ("WOO NFE/110", "WOO%20NFE%2F110"), ("a?b#c", "a%3Fb%23c")],
)
def test_free_text_segment(value: str, encoded: str) -> None:
    assert paths.free_text_segment(value, "external_id") == encoded


@pytest.mark.parametrize(
    "value",
    ["", ".", "..", "a\x00b", "tab\there", "x" * 256, 5],
    ids=["empty", "dot", "dotdot", "nul", "tab", "256-chars", "int"],
)
def test_free_text_rejects(value: object) -> None:
    with pytest.raises(InvalidParameterError):
        paths.free_text_segment(value, "external_id")


@pytest.mark.parametrize(
    ("value", "normalized"),
    [
        ("00.000.000/0001-91", "00000000000191"),
        ("00000000000191", "00000000000191"),
        (191, "00000000000191"),
        ("12.ABC.345/01DE-35", "12ABC34501DE35"),
        ("12abc34501de35", "12ABC34501DE35"),
    ],
)
def test_cnpj_valid(value: object, normalized: str) -> None:
    assert paths.cnpj(value) == normalized


@pytest.mark.parametrize(
    "value", ["00000000000100", "00000000000000", "123", "12ABC34501DE36", "", None, True]
)
def test_cnpj_invalid(value: object) -> None:
    with pytest.raises(InvalidParameterError):
        paths.cnpj(value)


def test_cpf() -> None:
    assert paths.cpf("529.982.247-25") == "52998224725"
    for bad in ["52998224724", "11111111111", "123", "abc", None]:
        with pytest.raises(InvalidParameterError):
            paths.cpf(bad)


def test_cep_uf_date() -> None:
    assert paths.cep("01310-100") == "01310100"
    with pytest.raises(InvalidParameterError):
        paths.cep("1310-100")
    assert paths.uf(" sp ") == "SP"
    with pytest.raises(InvalidParameterError):
        paths.uf("XX")
    assert paths.iso_date(date(2026, 1, 2), "d") == "2026-01-02"
    assert paths.iso_date(datetime(2026, 1, 2, 3, tzinfo=timezone.utc), "d") == "2026-01-02"
    assert paths.iso_date("1990-01-31", "d") == "1990-01-31"
    for bad in ["01/01/1990", "1990-02-30", "1990-1-1", 19900101]:
        with pytest.raises(InvalidParameterError):
            paths.iso_date(bad, "d")


def test_json_decimal_is_exact() -> None:
    body = jsonutil.dumps({"servicesAmount": Decimal("100.10"), "n": [Decimal("1E+2"), 1.5]})
    assert body == b'{"servicesAmount":100.10,"n":[100,1.5]}'
    assert json.loads(body)["servicesAmount"] == pytest.approx(100.10)


def test_json_rejects_garbage() -> None:
    for bad in [{"a": float("nan")}, {"a": Decimal("NaN")}, {1: "x"}, {"a": object()}]:
        with pytest.raises(InvalidParameterError):
            jsonutil.dumps(bad)
    assert jsonutil.dumps({"d": date(2026, 1, 2)}) == b'{"d":"2026-01-02"}'
    assert jsonutil.dumps({"s": "ção"}) == '{"s":"ção"}'.encode()


def test_multipart_body_is_exact() -> None:
    body, ctype = multipart.encode(
        [("password", "s3nh@")],
        [multipart.FilePart("file", 'evil"\r\nname.pfx', b"\x00\x01PFX", "application/x-pkcs12")],
    )
    boundary = ctype.split("boundary=", 1)[1]
    assert ctype.startswith("multipart/form-data; boundary=nfeio-")
    assert len(boundary) == len("nfeio-") + 32
    expected = (
        (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="password"\r\n\r\n'
            "s3nh@\r\n"
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="file"; filename="evil___name.pfx"\r\n'
            "Content-Type: application/x-pkcs12\r\n\r\n"
        ).encode()
        + b"\x00\x01PFX\r\n"
        + f"--{boundary}--\r\n".encode()
    )
    assert body == expected
    assert multipart.sanitize_filename('a"b\\c\r\nd é') == "a_b_c__d _"
    with pytest.raises(ValueError, match="field name"):
        multipart.encode([('bad"name', "x")], [])

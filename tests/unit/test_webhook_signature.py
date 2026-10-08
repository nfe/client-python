"""Signature verification with the 3 real ping deliveries captured from api.nfse.io (2026-06-11)
plus the negative cases of the Node SDK spec ``webhook-signature-verification``."""

from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
from typing import Any

import pytest

from nfeio import InvalidParameterError, ServiceInvoice, SignatureVerificationError
from nfeio.webhooks import construct_event, verify_signature

VECTORS: list[dict[str, Any]] = json.loads(
    (Path(__file__).parent.parent / "fixtures" / "webhook-signatures.json").read_text("utf-8")
)["fixtures"]
SECRET = "whsec-test-0123456789"


def _sign(body: bytes, secret: str = SECRET) -> str:
    return "sha1=" + hmac.new(secret.encode(), body, hashlib.sha1).hexdigest().upper()


@pytest.mark.parametrize("vector", VECTORS, ids=[v["label"] for v in VECTORS])
def test_real_deliveries(vector: dict[str, Any]) -> None:
    body = vector["body"].encode("utf-8")
    assert verify_signature(body, vector["header_value"], vector["secret"]) is True
    assert verify_signature(vector["body"], vector["header_value"], vector["secret"]) is True
    assert verify_signature(body, vector["header_value"].lower(), vector["secret"]) is True
    assert verify_signature(body, "SHA1=" + vector["header_value"][5:], vector["secret"])
    assert verify_signature(body, [vector["header_value"]], vector["secret"])
    assert verify_signature(bytearray(body), vector["header_value"], vector["secret"].encode())


@pytest.mark.parametrize("vector", VECTORS, ids=[v["label"] for v in VECTORS])
def test_tampered_body(vector: dict[str, Any]) -> None:
    body = bytearray(vector["body"].encode("utf-8"))
    body[10] ^= 0x01
    assert verify_signature(bytes(body), vector["header_value"], vector["secret"]) is False


def test_negative_inputs_never_raise() -> None:
    body = b'{"action":"ping"}'
    good = _sign(body)
    hexpart = good[5:]
    cases: list[tuple[Any, Any, Any]] = [
        (body, "sha256=" + hexpart, SECRET),
        (body, hexpart, SECRET),
        (body, "sha1=abc", SECRET),
        (body, "sha1=" + "z" * 40, SECRET),
        (body, "sha1=" + "é" * 40, SECRET),
        (body, None, SECRET),
        (body, "", SECRET),
        (body, [], SECRET),
        (body, good, ""),
        (body, good, b""),
        (body, good, None),
        (None, good, SECRET),
        (12345, good, SECRET),
        (body, 12345, SECRET),
        (body, good + "00", SECRET),
        (body, _sign(body, "other-secret"), SECRET),
    ]
    for payload, signature, secret in cases:
        assert verify_signature(payload, signature, secret) is False, (signature, secret)
    assert verify_signature(body, good, SECRET) is True
    assert verify_signature(body, "  " + good + " ", SECRET) is True


def test_uses_compare_digest(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []
    real = hmac.compare_digest

    def spy(a: str, b: str) -> bool:
        calls.append((a, b))
        return real(a, b)

    monkeypatch.setattr(hmac, "compare_digest", spy)
    body = b"x"
    verify_signature(body, _sign(body), SECRET)
    assert len(calls) == 1


def test_construct_event_service_invoice() -> None:
    payload = json.dumps(
        {"action": "issued_successfully", "payload": {"id": "inv1", "flowStatus": "Issued"}}
    ).encode()
    headers = {
        "x-hub-signature": _sign(payload),
        "x-hook-id": "4efa03baf6014b788e591da82efbaba8",
        "X-Hook-Event": "service_invoice",
    }
    event = construct_event(payload, headers, SECRET)
    assert event.action == "issued_successfully"
    assert event.event_type == "service_invoice"
    assert event.hook_id == "4efa03baf6014b788e591da82efbaba8"
    assert isinstance(event.data, ServiceInvoice)
    assert event.data.flow_status == "Issued"
    assert event.raw == payload
    assert event.body["action"] == "issued_successfully"


def test_construct_event_ping_and_repr_hides_secret() -> None:
    vector = VECTORS[1]
    body = vector["body"].encode()
    event = construct_event(body, {"X-Hub-Signature": [vector["header_value"]]}, vector["secret"])
    assert event.action == "ping"
    assert event.data["Id"] == "ad1010b0f66441419454e5e283cce64b"
    assert vector["secret"] not in repr(event)
    assert vector["secret"] not in repr(event.data)
    by_value = construct_event(body, vector["header_value"], vector["secret"])
    assert by_value.hook_id is None and by_value.event_type is None


def test_construct_event_rejects_before_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_: Any, **__: Any) -> Any:
        raise AssertionError("body must not be parsed before verification")

    monkeypatch.setattr(json, "loads", boom)
    with pytest.raises(SignatureVerificationError):
        construct_event(b'{"a":1}', {"X-Hub-Signature": "sha1=" + "0" * 40}, SECRET)
    with pytest.raises(SignatureVerificationError):
        construct_event(b'{"a":1}', {}, SECRET)


def test_construct_event_limits_and_shapes() -> None:
    big = b"{" + b" " * (5 * 1024 * 1024) + b"}"
    with pytest.raises(InvalidParameterError):
        construct_event(big, _sign(big), SECRET)
    for body in (b"not json", b"[1,2]"):
        with pytest.raises(InvalidParameterError):
            construct_event(body, _sign(body), SECRET)
    with pytest.raises(InvalidParameterError):
        construct_event(None, "x", SECRET)  # type: ignore[arg-type]
    plain = b'{"id":"x"}'
    event = construct_event(plain, _sign(plain), SECRET)
    assert event.action is None and event.data["id"] == "x"

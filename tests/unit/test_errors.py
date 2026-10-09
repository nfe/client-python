from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import nfeio.errors as errors_module
from nfeio import (
    APIConnectionError,
    APIError,
    AuthenticationError,
    ConfigurationError,
    ConflictError,
    DuplicateExternalIdError,
    FailurePhase,
    InvalidParameterError,
    InvalidRequestError,
    NfeError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    ServerError,
    UnexpectedResponseError,
)
from nfeio._config import ApiFamily
from nfeio._core.error_mapping import error_from_response, extract_error, sanitize
from tests.helpers import API_KEY, COMPANY_ID, FakeTransport, make_client, resp

FIXTURES = json.loads(
    (Path(__file__).parent.parent / "fixtures" / "error-envelopes.json").read_text("utf-8")
)["cases"]


def _map(status: int, body: bytes, method: str = "GET", **headers: str) -> APIError:
    return error_from_response(
        resp(status, body=body, headers={"x-request-id": "abc:1", **headers}),
        family=ApiFamily.SERVICE_INVOICES,
        method=method,
    )


@pytest.mark.parametrize("case", FIXTURES, ids=[c["label"] for c in FIXTURES])
def test_real_error_envelopes(case: dict[str, Any]) -> None:
    err = _map(case["status"], case["body"].encode())
    assert type(err).__name__ == case["expect_class"]
    assert err.status_code == case["status"]
    assert err.request_id == "abc:1"
    assert err.message
    if "expect_message" in case:
        assert err.message == case["expect_message"]
    if "expect_message_contains" in case:
        assert case["expect_message_contains"] in err.message
    assert err.error_code == case["expect_code"]
    if "expect_trace_id" in case:
        assert err.trace_id == case["expect_trace_id"]
    assert err.body == case["body"].encode()


@pytest.mark.parametrize(
    ("status", "cls"),
    [
        (400, InvalidRequestError),
        (401, AuthenticationError),
        (403, PermissionDeniedError),
        (404, NotFoundError),
        (405, InvalidRequestError),
        (408, ServerError),
        (409, ConflictError),
        (410, InvalidRequestError),
        (415, InvalidRequestError),
        (422, InvalidRequestError),
        (429, RateLimitError),
        (500, ServerError),
        (502, ServerError),
        (503, ServerError),
        (504, ServerError),
    ],
)
def test_status_mapping(status: int, cls: type[APIError]) -> None:
    err = _map(status, b"")
    assert type(err) is cls
    assert isinstance(err, NfeError)
    assert err.message


def test_hierarchy() -> None:
    assert issubclass(ConfigurationError, ValueError)
    assert issubclass(InvalidParameterError, ValueError)
    assert issubclass(DuplicateExternalIdError, InvalidRequestError)
    for name in errors_module.__all__:
        obj = getattr(errors_module, name)
        if isinstance(obj, type) and issubclass(obj, Exception):
            assert issubclass(obj, NfeError), name


def test_permission_hint_by_family() -> None:
    fiscal = error_from_response(resp(403), family=ApiFamily.SERVICE_INVOICES, method="GET")
    data = error_from_response(resp(403), family=ApiFamily.LEGAL_ENTITY, method="GET")
    assert "api_key" in fiscal.message and "data_api_key" not in fiscal.message
    assert "data_api_key" in data.message


def test_cnpj_lookup_403_mentions_data_key() -> None:
    client = make_client(FakeTransport(resp(403)))
    with pytest.raises(PermissionDeniedError, match="data_api_key"):
        client.lookups.cnpj("00000000000191")


def test_duplicate_external_id_detection() -> None:
    for text in [
        '"service invoice with external id (pedido-1) already exists"',
        '"Service Invoice with External Id (pedido-1) ALREADY EXISTS"',
        '{"errors":[{"message":"service invoice with externalId (pedido-1) already exists"}]}',
    ]:
        err = _map(400, text.encode(), method="POST")
        assert isinstance(err, DuplicateExternalIdError), text
        assert err.external_id == "pedido-1"
        assert not err.outcome_unknown


def test_outcome_unknown_only_for_post_ambiguous() -> None:
    assert _map(500, b"", method="POST").outcome_unknown
    assert _map(504, b"", method="POST").outcome_unknown
    assert _map(429, b"", method="POST").outcome_unknown
    assert not _map(400, b"", method="POST").outcome_unknown
    assert not _map(500, b"", method="GET").outcome_unknown


def test_rate_limit_retry_after() -> None:
    err = _map(429, b"", **{"Retry-After": "3600"})
    assert isinstance(err, RateLimitError)
    assert err.retry_after == 3600


def test_message_sanitised_and_truncated() -> None:
    err = _map(400, json.dumps("bad\x00\x1b[31m" + "x" * 5000).encode())
    assert "\x00" not in err.message and "\x1b" not in err.message
    assert len(err.message) <= 1000
    assert len(err.body) > 5000
    assert sanitize("a\r\n  b") == "a b"


def test_extract_edge_cases() -> None:
    assert extract_error(b"", 500) == ("", None, None)
    assert extract_error(b"\xff\xfe", 500) == ("", None, None)
    assert extract_error(b"<html>Bad gateway</html>", 502)[0] == "<html>Bad gateway</html>"
    assert extract_error(b"[1, 2]", 400) == ("", None, None)
    assert extract_error(b'{"errors": ["plain"]}', 400)[0] == "plain"
    assert extract_error(b'{"errors": {"": ["no field"]}}', 400)[0] == "no field"


def test_str_and_repr_have_no_key() -> None:
    client = make_client(FakeTransport(resp(401)))
    with pytest.raises(AuthenticationError) as info:
        client.service_invoices.list(COMPANY_ID)
    err = info.value
    for text in (str(err), repr(err), repr(err.headers), str(vars(err))):
        assert API_KEY not in text
    assert "status=401" in str(err)
    assert "request_id=" in str(err)


def test_echoed_key_is_scrubbed() -> None:
    body = json.dumps(f"invalid key {API_KEY}").encode()
    client = make_client(FakeTransport(resp(400, body=body)))
    with pytest.raises(InvalidRequestError) as info:
        client.webhooks.list()
    assert API_KEY not in info.value.message
    assert API_KEY.encode() not in info.value.body


def test_json_body_property() -> None:
    err = _map(404, b'{"errors":[{"code":1,"message":"m"}]}')
    assert err.json_body == {"errors": [{"code": 1, "message": "m"}]}
    assert _map(404, b"").json_body is None
    assert _map(502, b"<html>").json_body is None


def test_connection_error_str() -> None:
    err = APIConnectionError("boom", phase=FailurePhase.MAYBE_SENT, outcome_unknown=True)
    assert "maybe_sent" in str(err) and "outcome_unknown=True" in str(err)
    assert "boom" in repr(err)
    unexpected = UnexpectedResponseError("x", status_code=200, headers={"x-request-id": "r"})
    assert unexpected.request_id == "r"

"""Regressions for the hardening found in the final security review (2026-10-08)."""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest

from nfeio import InvalidParameterError, UnexpectedResponseError
from nfeio._core import jsonutil
from nfeio._core.error_mapping import extract_error
from nfeio.webhooks import construct_event
from tests.helpers import COMPANY_ID, INVOICE_ID, FakeTransport, invoice_json, make_client, resp


@pytest.mark.parametrize(
    "answer",
    [
        resp(200, body=b""),
        resp(200, {"unexpected": True}),
        resp(200, ["not", "an", "object"]),
        resp(302, headers={"Location": "https://elsewhere.example/x"}),
    ],
)
def test_external_lookup_never_reads_garbage_as_not_found(answer: object) -> None:
    """A reconciliation must not conclude "safe to issue again" from an unexpected answer."""
    transport = FakeTransport(answer)  # type: ignore[arg-type]
    with pytest.raises(UnexpectedResponseError):
        make_client(transport).service_invoices.find_by_external_id(COMPANY_ID, "p-1", wait=30)
    assert len(transport.requests) == 1


def test_redirect_outside_downloads_is_an_error() -> None:
    transport = FakeTransport(resp(302, headers={"Location": "https://api.nfse.io/x"}))
    with pytest.raises(UnexpectedResponseError, match="redirect"):
        make_client(transport).service_invoices.retrieve(COMPANY_ID, INVOICE_ID)
    assert len(transport.requests) == 1


def test_deeply_nested_json_stays_inside_the_hierarchy() -> None:
    nested = b"[" * 100_000 + b"]" * 100_000
    transport = FakeTransport(resp(200, body=nested), resp(400, body=nested))
    client = make_client(transport)
    with pytest.raises(UnexpectedResponseError):
        client.webhooks.list()
    from nfeio import InvalidRequestError

    with pytest.raises(InvalidRequestError) as info:
        client.webhooks.list()
    assert info.value.json_body is None


def _nested(depth: int) -> str:
    return "[" * depth + "]" * depth


def test_json_depth_limit_is_explicit() -> None:
    """The limit does not depend on the interpreter: 129 levels decode fine with ``json``."""
    limit = jsonutil.MAX_JSON_DEPTH
    assert jsonutil.loads(_nested(limit).encode()) == json.loads(_nested(limit))
    json.loads(_nested(limit + 1))
    with pytest.raises(ValueError, match="nested deeper than 128"):
        jsonutil.loads(_nested(limit + 1).encode())
    objects = '{"a":' * limit + "1" + "}" * limit
    assert jsonutil.loads(objects) is not None
    with pytest.raises(ValueError, match="nested deeper"):
        jsonutil.loads('{"a":' * limit + "[1]" + "}" * limit)


def test_json_depth_ignores_brackets_inside_strings() -> None:
    noise = "[{" * 500
    assert jsonutil.loads(json.dumps({"text": noise, "list": [noise]})) == {
        "text": noise,
        "list": [noise],
    }
    # An escaped quote does not close the string, so the brackets after it still do not count.
    escaped = '{"text": "say \\"' + noise + '\\" ok"}'
    assert jsonutil.loads(escaped)["text"] == 'say "' + noise + '" ok'
    # An escaped backslash does close it: the brackets after it are real nesting.
    real = '["\\\\", ' * (jsonutil.MAX_JSON_DEPTH + 1) + "1" + "]" * (jsonutil.MAX_JSON_DEPTH + 1)
    with pytest.raises(ValueError, match="nested deeper"):
        jsonutil.loads(real)


def test_json_depth_check_with_unterminated_string_is_linear() -> None:
    """An unterminated string full of escaped quotes is scanned once, not once per quote."""
    hostile = "[" * 200 + '"' + '\\"' * 500_000
    with pytest.raises(ValueError, match="nested deeper"):
        jsonutil.loads(hostile)
    with pytest.raises(json.JSONDecodeError, match="Unterminated string"):
        jsonutil.loads("[" * 100 + '"' + '\\"' * 500_000)


def test_deeply_nested_error_body_and_webhook() -> None:
    deep = _nested(jsonutil.MAX_JSON_DEPTH + 1).encode()
    message, code, trace_id = extract_error(deep, 400)
    assert message.startswith("[[[") and code is None and trace_id is None
    secret = "s3cr3t"
    signature = "sha1=" + hmac.new(secret.encode(), deep, hashlib.sha1).hexdigest()
    with pytest.raises(InvalidParameterError, match="not valid JSON"):
        construct_event(deep, signature, secret)


def test_offset_pagination_that_does_not_advance() -> None:
    same = {"serviceInvoices": [invoice_json(id="a"), invoice_json(id="b")], "page": 1}
    transport = FakeTransport(resp(200, same), resp(200, same))
    page = make_client(transport).service_invoices.list(COMPANY_ID, page_count=2)
    with pytest.raises(UnexpectedResponseError, match="did not advance"):
        list(page.auto_paging_iter())


def test_cursor_pagination_that_does_not_advance() -> None:
    transport = FakeTransport(resp(200, {"hasMore": True, "companies": [{"id": "x"}]}))
    page = make_client(transport).companies.list(limit=1, starting_after="x")
    with pytest.raises(UnexpectedResponseError, match="did not advance"):
        list(page.auto_paging_iter())


async def test_async_offset_pagination_that_does_not_advance() -> None:
    from tests.helpers import make_async_client

    same = {"serviceInvoices": [invoice_json(id="a")], "page": 1}
    transport = FakeTransport(resp(200, same), resp(200, same))
    page = await make_async_client(transport).service_invoices.list(COMPANY_ID, page_count=1)
    with pytest.raises(UnexpectedResponseError, match="did not advance"):
        [item async for item in page.auto_paging_iter()]

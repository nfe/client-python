"""README examples: every Python block compiles; the quick start and the reconciliation recipe
run against the fake transport."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

import nfeio
from nfeio import APIConnectionError, FailurePhase, InvalidRequestError
from tests.helpers import COMPANY_ID, INVOICE_ID, FakeTransport, invoice_json, make_client, resp

README = (Path(__file__).resolve().parents[2] / "README.md").read_text("utf-8")
BLOCKS: list[str] = re.findall(r"```python\n(.*?)```", README, re.DOTALL)


def _block(containing: str) -> str:
    return next(block for block in BLOCKS if containing in block)


@pytest.mark.parametrize("index", range(len(BLOCKS)))
def test_python_blocks_compile(index: int) -> None:
    compile(BLOCKS[index], f"README.md#block{index}", "exec")


def test_quick_start_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    location = f"http://api.nfe.io/v1/companies/ID_DA_EMPRESA/serviceinvoices/{INVOICE_ID}"
    transport = FakeTransport(
        resp(202, {"id": INVOICE_ID, "flowStatus": "WaitingSend"}, headers={"Location": location}),
        resp(200, invoice_json()),
        resp(302, headers={"Location": "https://api.nfse.io/v1/blob/download?s=1"}),
        resp(200, body=b"%PDF-1.4"),
    )
    monkeypatch.setattr(nfeio, "NfeClient", lambda **_: make_client(transport))
    namespace: dict[str, Any] = {}
    exec(_block("create_and_wait(\n    company_id"), namespace)  # noqa: S102 - README example
    assert namespace["pdf"] == b"%PDF-1.4"
    assert transport.json_body(0)["externalId"] == "pedido-1001"


def _recipe() -> Any:
    namespace: dict[str, Any] = {}
    exec(_block("def emitir"), namespace)  # noqa: S102 - README example under test
    return namespace["emitir"]


PEDIDO = {"id": 7, "nfse": {"servicesAmount": 1}}


def test_recipe_success() -> None:
    transport = FakeTransport(resp(202, {"id": INVOICE_ID, "flowStatus": "WaitingSend"}))
    assert _recipe()(make_client(transport), COMPANY_ID, PEDIDO).id == INVOICE_ID


def test_recipe_reconciles_ambiguous_failure() -> None:
    found = resp(200, {"serviceInvoices": [invoice_json()], "page": 1})
    for failure in (resp(504), APIConnectionError("reset", phase=FailurePhase.MAYBE_SENT)):
        transport = FakeTransport(failure, found)
        nota = _recipe()(make_client(transport), COMPANY_ID, PEDIDO)
        assert nota.id == INVOICE_ID
        assert [r.method for r in transport.requests] == ["POST", "GET"]
        assert transport.requests[1].url.endswith("/external/pedido-7")


def test_recipe_reconciles_duplicate() -> None:
    duplicate = resp(400, body=b'"service invoice with external id (pedido-7) already exists"')
    found = resp(200, {"serviceInvoices": [invoice_json()], "page": 1})
    transport = FakeTransport(duplicate, found)
    assert _recipe()(make_client(transport), COMPANY_ID, PEDIDO).id == INVOICE_ID


def test_recipe_propagates_validation_errors_and_missing_invoice() -> None:
    transport = FakeTransport(resp(422, body=b'"cityServiceCode is required"'))
    with pytest.raises(InvalidRequestError):
        _recipe()(make_client(transport), COMPANY_ID, PEDIDO)
    empty = resp(200, {"serviceInvoices": [], "page": 1})
    transport = FakeTransport(resp(500), *[empty] * 40)
    client = make_client(transport)
    with pytest.raises(RuntimeError, match="seguro tentar de novo"):
        _recipe()(client, COMPANY_ID, PEDIDO)

from __future__ import annotations

import ast
import importlib.metadata
import logging
import re
from collections.abc import Callable
from pathlib import Path

import pytest

import nfeio
from nfeio import APIConnectionError, FailurePhase, NfeError, RequestOptions
from tests.helpers import API_KEY, COMPANY_ID, DATA_KEY, FakeTransport, make_client, resp

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "nfeio"
CERT_PASSWORD = "cert-password-XYZ987"


def test_secret_leak_scan(caplog: pytest.LogCaptureFixture) -> None:
    """Success, 401, 500 and a network failure with DEBUG logs: no key or password anywhere."""
    caplog.set_level(logging.DEBUG)
    transport = FakeTransport(
        resp(200, {"webHooks": [{"id": "h", "secret": "hook-secret-1234"}]}),
        resp(401),
        resp(500, body=b'{"title":"boom"}'),
        resp(500),
        APIConnectionError("reset", phase=FailurePhase.MAYBE_SENT),
        APIConnectionError("reset", phase=FailurePhase.MAYBE_SENT),
        APIConnectionError("reset", phase=FailurePhase.MAYBE_SENT),
        APIConnectionError("reset", phase=FailurePhase.MAYBE_SENT),
        resp(500, body=b'{"title":"upload failed"}'),
        resp(403),
    )
    client = make_client(transport, max_retries=3)
    texts: list[str] = [repr(client), repr(client._config), repr(RequestOptions(api_key=API_KEY))]
    hooks = client.webhooks.list()
    texts += [repr(hooks), repr(hooks[0])]
    calls: list[Callable[[], object]] = [
        lambda: client.service_invoices.list(COMPANY_ID),
        lambda: client.service_invoices.create(COMPANY_ID, {}, external_id="e"),
        lambda: client.webhooks.retrieve("h"),
        lambda: client.certificates.upload(COMPANY_ID, b"PFX", CERT_PASSWORD),
        lambda: client.lookups.cep("01310100"),
    ]
    for call in calls:
        with pytest.raises(NfeError) as info:
            call()
        err = info.value
        texts += [str(err), repr(err), repr(vars(err)), repr(err.args)]
    texts += [repr(r) for r in transport.requests]
    texts += [record.getMessage() for record in caplog.records]
    blob = "\n".join(texts)
    for secret in (API_KEY, DATA_KEY, CERT_PASSWORD, "hook-secret-1234"):
        assert secret not in blob, secret
    assert any("nfeio" in r.name for r in caplog.records)


def test_zero_runtime_dependencies() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text("utf-8")
    assert re.search(r"^dependencies = \[\]$", pyproject, re.MULTILINE)
    requires = importlib.metadata.requires("nfe-io") or []
    assert [r for r in requires if "extra ==" not in r] == []


def test_version_single_source() -> None:
    version = nfeio.__version__
    assert importlib.metadata.version("nfe-io") == version
    offenders = []
    for path in SRC.rglob("*.py"):
        if path.name == "_version.py":
            continue
        tree = ast.parse(path.read_text("utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                standalone = rf"(?<![\d.]){re.escape(version)}(?![\d.])"
                if re.search(standalone, node.value) or re.fullmatch(r"\d+\.\d+\.\d+", node.value):
                    offenders.append(f"{path.name}:{node.lineno}")
            if isinstance(node, ast.Assign):
                names = [t.id for t in node.targets if isinstance(t, ast.Name)]
                if "__version__" in names:
                    offenders.append(f"{path.name}:{node.lineno} assigns __version__")
    assert offenders == []


def test_py_typed_and_license_present() -> None:
    assert (SRC / "py.typed").exists()
    assert (ROOT / "LICENSE").read_text("utf-8").startswith("MIT License")
    assert "Private Vulnerability Reporting" in (ROOT / "SECURITY.md").read_text("utf-8")


def test_no_dangerous_calls_in_package() -> None:
    forbidden = re.compile(
        r"\b(pickle\.loads?|eval\(|exec\(|yaml\.load|marshal\.loads?|shell=True)"
    )
    hits = [
        f"{p.relative_to(ROOT)}"
        for p in SRC.rglob("*.py")
        if forbidden.search(p.read_text("utf-8"))
    ]
    assert hits == []


def test_public_api_surface() -> None:
    for name in nfeio.__all__:
        assert hasattr(nfeio, name), name
    assert not hasattr(nfeio, "api_key")  # no global state


@pytest.mark.parametrize("value", ["abc\n", "abc\r\n", "\nabc"])
def test_validators_reject_trailing_newline(value: str) -> None:
    from nfeio import ConfigurationError, InvalidParameterError
    from nfeio._core import paths

    with pytest.raises(InvalidParameterError):
        paths.opaque_id(value, "id")
    # Documents strip whitespace as a mask separator: the value that reaches the path is clean.
    assert paths.cnpj("00000000000191\n") == "00000000000191"
    with pytest.raises(InvalidParameterError):
        paths.iso_date("1990-01-01\n", "birth_date")
    with pytest.raises(ConfigurationError):
        RequestOptions(extra_headers={"X-A\n": "v"})


def test_logs_and_reprs_have_no_personal_data(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="nfeio")
    transport = FakeTransport(
        resp(503),
        resp(200, {"status": "Regular"}),
        resp(200, {"serviceInvoices": [], "page": 1}),
    )
    client = make_client(transport)
    client.lookups.cpf("52998224725", "1990-01-31")
    client.service_invoices.find_by_external_id(COMPANY_ID, "pedido-joao-silva")
    lines = [r.getMessage() for r in caplog.records] + [repr(r) for r in transport.requests]
    blob = "\n".join(lines)
    for personal in ("52998224725", "1990-01-31", "pedido-joao-silva", COMPANY_ID):
        assert personal not in blob
    assert "/v1/naturalperson/status/*/*" in blob

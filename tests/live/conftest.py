"""Opt-in integration tests against the real NFE.io API.

* Read tests run only with ``NFE_RUN_INTEGRATION=1`` (or ``pytest --run-integration``) and the
  keys from the environment or the repo ``.env`` (parsed here with the stdlib, never printed).
  The opt-in itself is never read from ``.env``.
* Write tests additionally need ``NFE_LIVE_WRITE=1`` (or ``--live-write``). NFS-e writes are
  locked to ``NFE_COMPANY_ID``; the only other writes are one disposable company and test
  webhooks, both deleted in ``finally`` blocks.
* Every exchange is recorded **redacted** to ``tests/live/out/`` (gitignored) as raw evidence;
  curated, synthetic fixtures go to ``tests/fixtures/live-contracts/``.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest

from nfeio import NfeClient
from nfeio._core.redact import log_path
from nfeio.transport import HttpClientTransport, HttpRequest, HttpResponse

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "out"


def _load_dotenv() -> dict[str, str]:
    path = ROOT / ".env"
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text("utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def env(name: str) -> str:
    return os.environ.get(name) or _load_dotenv().get(name, "")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    run = os.environ.get("NFE_RUN_INTEGRATION") == "1" or config.getoption("--run-integration")
    write = os.environ.get("NFE_LIVE_WRITE") == "1" or config.getoption("--live-write")
    for item in items:
        if "live" in item.keywords:
            if not run:
                item.add_marker(pytest.mark.skip(reason="set NFE_RUN_INTEGRATION=1 to run"))
            elif not env("NFE_API_KEY"):
                item.add_marker(pytest.mark.skip(reason="NFE_API_KEY not available"))
        if "live_write" in item.keywords and not write:
            item.add_marker(pytest.mark.skip(reason="set NFE_LIVE_WRITE=1 to run writes"))


class Recorder:
    """Records exchanges with ids, documents and secrets replaced by placeholders."""

    def __init__(self, secrets: list[str]) -> None:
        self.secrets = [s for s in secrets if s]
        self.entries: list[dict[str, Any]] = []

    def redact(self, text: str) -> str:
        for secret in self.secrets:
            text = text.replace(secret, "<SECRET>")
        text = re.sub(r"\b[0-9a-f]{32}\b", "<ID32>", text)
        text = re.sub(r"\b[0-9a-f]{24}\b", "<ID24>", text)
        text = re.sub(r"\b\d{11,14}\b", "<DOC>", text)
        text = re.sub(r"([?&])(s|e|b|sig|signature|token)=[^&\s\"]+", r"\1\2=<PRESIGNED>", text)
        return text

    def redact_value(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {k: self.redact_value(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self.redact_value(v) for v in value]
        if isinstance(value, str):
            return self.redact(value)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 10**8:
            return "<DOC>"
        return value

    def record(self, request: HttpRequest, response: HttpResponse | None, error: str = "") -> None:
        parts = urlsplit(request.url)
        body: Any = None
        if response is not None and response.body:
            ctype = response.headers.get("content-type", "")
            if "json" in ctype:
                try:
                    body = self.redact_value(json.loads(response.body.decode("utf-8-sig")))
                except ValueError:
                    body = {"_text": self.redact(response.body[:500].decode("utf-8", "replace"))}
            else:
                head = response.body[:16]
                body = {"_bytes": len(response.body), "_head": head.decode("latin-1")}
        self.entries.append(
            {
                "method": request.method,
                "host": parts.hostname,
                "path": log_path(parts.path),
                "authorization_sent": "Authorization" in request.headers,
                "status": response.status_code if response is not None else None,
                "headers": {
                    k.lower(): self.redact(v)
                    for k, v in (response.headers.items() if response is not None else [])
                    if k.lower() in {"content-type", "location", "retry-after", "content-length"}
                }
                | (
                    {"x-request-id": "<present>"}
                    if response is not None and "x-request-id" in response.headers
                    else {}
                ),
                "body": body,
                "error": error,
            }
        )

    def save(self, name: str) -> Path:
        OUT.mkdir(parents=True, exist_ok=True)
        path = OUT / f"{name}.json"
        text = json.dumps(self.entries, ensure_ascii=False, indent=2)
        for secret in self.secrets:
            assert secret not in text, "secret leaked into the evidence file"
        path.write_text(text, "utf-8")
        return path


class RecordingTransport(HttpClientTransport):
    def __init__(self, recorder: Recorder) -> None:
        super().__init__()
        self.recorder = recorder

    def send(self, request: HttpRequest) -> HttpResponse:
        try:
            response = super().send(request)
        except Exception as exc:
            self.recorder.record(request, None, error=f"{type(exc).__name__}: {exc}")
            raise
        self.recorder.record(request, response)
        return response


@pytest.fixture(scope="session")
def company_id() -> str:
    value = env("NFE_COMPANY_ID")
    if not value:
        pytest.skip("NFE_COMPANY_ID not available")
    return value


@pytest.fixture
def recorder(request: pytest.FixtureRequest) -> Iterator[Recorder]:
    rec = Recorder([env("NFE_API_KEY"), env("NFE_DATA_API_KEY"), env("NFE_COMPANY_ID")])
    yield rec
    rec.save(request.node.name)


@pytest.fixture
def client(recorder: Recorder) -> Iterator[NfeClient]:
    transport = RecordingTransport(recorder)
    c = NfeClient(
        api_key=env("NFE_API_KEY"),
        data_api_key=env("NFE_DATA_API_KEY") or None,
        transport=transport,
        app_info=("nfeio-sdk-python-live-tests", "0"),
    )
    yield c
    c.close()


def assert_write_company(company: str) -> None:
    """Hard lock: NFS-e writes only on the test company configured in NFE_COMPANY_ID."""
    allowed = env("NFE_COMPANY_ID")
    if not allowed or company != allowed:
        raise RuntimeError("refusing to write NFS-e outside NFE_COMPANY_ID")

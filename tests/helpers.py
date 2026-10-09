"""Test doubles: scripted transports, a fake clock and client factories (no network, no sleep)."""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import parse_qs, urlsplit

from nfeio import AsyncNfeClient, NfeClient
from nfeio.transport import Headers, HttpRequest, HttpResponse

API_KEY = "test_main_key_0123456789abcdef"
DATA_KEY = "test_data_key_fedcba9876543210"

Scripted = HttpResponse | BaseException | Callable[[HttpRequest], HttpResponse]


def resp(
    status: int = 200,
    json_body: Any = None,
    *,
    body: bytes | None = None,
    headers: Mapping[str, str] | None = None,
) -> HttpResponse:
    hdrs = {"x-request-id": "0HTEST:00000001"}
    if json_body is not None:
        body = json.dumps(json_body).encode()
        hdrs["Content-Type"] = "application/json; charset=utf-8"
    hdrs.update(headers or {})
    return HttpResponse(status_code=status, headers=Headers(hdrs), body=body or b"")


class FakeTransport:
    """Pops scripted responses (or raises scripted exceptions) and records every request."""

    def __init__(self, *script: Scripted) -> None:
        self.script: list[Scripted] = list(script)
        self.requests: list[HttpRequest] = []
        self.closed = False

    def add(self, *script: Scripted) -> None:
        self.script.extend(script)

    def send(self, request: HttpRequest) -> HttpResponse:
        self.requests.append(request)
        if not self.script:
            raise AssertionError(f"unexpected request: {request!r}")
        item = self.script.pop(0)
        if isinstance(item, BaseException):
            raise item
        if callable(item):
            return item(request)
        return item

    def close(self) -> None:
        self.closed = True

    # -- inspection helpers --
    @property
    def last(self) -> HttpRequest:
        return self.requests[-1]

    def paths(self) -> list[str]:
        return [urlsplit(r.url).path for r in self.requests]

    def query(self, index: int = -1) -> dict[str, list[str]]:
        return parse_qs(urlsplit(self.requests[index].url).query)

    def json_body(self, index: int = -1) -> Any:
        body = self.requests[index].body
        assert body is not None
        return json.loads(body)


class FakeAsyncTransport:
    def __init__(self, sync: FakeTransport) -> None:
        self.sync = sync
        self.closed = False

    async def send(self, request: HttpRequest) -> HttpResponse:
        return self.sync.send(request)

    async def aclose(self) -> None:
        self.closed = True


class FakeClock:
    """Monotonic clock advanced only by (fake) sleeps."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds

    async def asleep(self, seconds: float) -> None:
        self.sleep(seconds)


def _fixed_random() -> float:
    return 0.5  # jitter factor 0.7 + 0.6 * 0.5 = 1.0 -> deterministic delays


def make_client(
    transport: FakeTransport, clock: FakeClock | None = None, **kwargs: Any
) -> NfeClient:
    kwargs.setdefault("api_key", API_KEY)
    kwargs.setdefault("data_api_key", DATA_KEY)
    client = NfeClient(transport=transport, **kwargs)
    client._config = dataclasses.replace(client._config, random=_fixed_random)
    clock = clock or FakeClock()
    client._sleep = clock.sleep
    client._monotonic = clock.monotonic
    return client


def make_async_client(
    transport: FakeTransport, clock: FakeClock | None = None, **kwargs: Any
) -> AsyncNfeClient:
    kwargs.setdefault("api_key", API_KEY)
    kwargs.setdefault("data_api_key", DATA_KEY)
    client = AsyncNfeClient(transport=FakeAsyncTransport(transport), **kwargs)
    client._config = dataclasses.replace(client._config, random=_fixed_random)
    clock = clock or FakeClock()
    client._sleep = clock.asleep
    client._monotonic = clock.monotonic
    return client


COMPANY_ID = "0123456789abcdef0123456789abcdef"
INVOICE_ID = "fedcba9876543210fedcba98"


def invoice_json(**overrides: Any) -> dict[str, Any]:
    """A redacted service invoice with the wire shape observed on 2026-10-08."""
    data: dict[str, Any] = {
        "id": INVOICE_ID,
        "environment": "Development",
        "flowStatus": "Issued",
        "flowMessage": None,
        "status": "Issued",
        "number": 123,
        "checkCode": "ABCD1234",
        "rpsNumber": 77,
        "rpsSerialNumber": "IO",
        "description": "Serviço de teste",
        "cityServiceCode": "2690",
        "servicesAmount": 1234.56,
        "baseTaxAmount": 1234.56,
        "deductionsAmount": 0.0,
        "issRate": 0.02,
        "issTaxAmount": 24.69,
        "amountNet": 1234.56,
        "issuedOn": "2026-09-01T02:55:33.418+00:00",
        "createdOn": "2026-09-01T02:55:30.1234567Z",
        "modifiedOn": "2026-09-01T02:56:00+00:00",
        "borrower": {
            "id": "b0rr0w3r",
            "type": "NaturalPerson",
            "name": "Cliente Teste",
            "federalTaxNumber": 52998224725,
            "email": "cliente@example.com",
            "address": {"city": {"code": "3550308", "name": "São Paulo"}, "state": "SP"},
        },
        "provider": {
            "id": COMPANY_ID,
            "type": "LegalEntity",
            "name": "Empresa Teste",
            "federalTaxNumber": 191,
        },
    }
    data.update(overrides)
    return data

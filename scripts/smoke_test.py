"""Smoke test of an installed wheel in a clean environment (no network, no extra packages).

python scripts/smoke_test.py
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import importlib.metadata
import sys

import nfeio
from nfeio import AsyncNfeClient, ConfigurationError, NfeClient, ServiceInvoice
from nfeio.transport import Headers, HttpRequest, HttpResponse
from nfeio.webhooks import verify_signature


class _Transport:
    def send(self, request: HttpRequest) -> HttpResponse:
        assert request.headers["Authorization"] == "smoke-key-123456"
        return HttpResponse(200, Headers({"x-request-id": "smoke"}), b'{"webHooks": []}')

    def close(self) -> None:
        pass


def main() -> int:
    assert importlib.metadata.version("nfe-io") == nfeio.__version__
    requires = importlib.metadata.requires("nfe-io") or []
    assert [r for r in requires if "extra ==" not in r] == [], requires
    client = NfeClient(api_key="smoke-key-123456", transport=_Transport())
    assert client.webhooks.list() == []
    assert "smoke-key-123456" not in repr(client)
    try:
        NfeClient(api_key="k" * 10, base_urls={"service_invoices": "http://insecure"})
    except ConfigurationError:
        pass
    else:
        raise AssertionError("http base URL must be rejected")
    invoice = ServiceInvoice({"servicesAmount": 1234.56, "flowStatus": "Issued"})
    assert str(invoice.services_amount) == "1234.56"
    body = b'{"action":"ping"}'
    signature = "sha1=" + hmac.new(b"s", body, hashlib.sha1).hexdigest().upper()
    assert verify_signature(body, signature, "s")

    async def run_async() -> None:
        async with AsyncNfeClient(api_key="k" * 12) as aclient:
            assert repr(aclient)

    asyncio.run(run_async())
    print(f"nfeio {nfeio.__version__} smoke test ok on Python {sys.version.split()[0]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

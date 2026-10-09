"""The stdlib transport against real local sockets (no internet)."""

from __future__ import annotations

import http.server
import shutil
import socket
import ssl
import subprocess
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from nfeio import (
    APIConnectionError,
    APITimeoutError,
    AsyncNfeClient,
    ConfigurationError,
    FailurePhase,
    NfeClient,
    ResponseTooLargeError,
    Timeout,
)
from nfeio.transport import HttpClientTransport, HttpRequest, ThreadedAsyncTransport


class _Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args: Any) -> None:
        pass

    def _serve(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        self.server.seen.append((self.command, self.path, dict(self.headers), body))  # type: ignore[attr-defined]
        mode = self.path.split("?")[0].strip("/")
        if mode == "slow":
            time.sleep(1.0)
        if mode == "drop":
            payload = b"{}"
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            self.close_connection = True
            return
        if mode == "close":
            self.close_connection = True
            self.connection.close()
            return
        if mode == "big":
            payload = b"x" * 300_000
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.end_headers()  # no Content-Length: forces chunk-by-chunk accounting
            self.close_connection = True
            self.wfile.write(payload)
            return
        if mode == "declared-big":
            self.send_response(200)
            self.send_header("Content-Length", "999999999")
            self.end_headers()
            self.close_connection = True
            return
        payload = b'{"webHooks": []}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("x-request-id", "local:1")
        self.end_headers()
        self.wfile.write(payload)

    do_GET = do_POST = do_PUT = do_DELETE = _serve


@contextmanager
def _server(tls: ssl.SSLContext | None = None) -> Iterator[tuple[str, Any]]:
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.seen = []  # type: ignore[attr-defined]
    server.daemon_threads = True
    if tls is not None:
        server.socket = tls.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    scheme = "https" if tls else "http"
    try:
        yield f"{scheme}://127.0.0.1:{server.server_address[1]}", server
    finally:
        server.shutdown()
        server.server_close()


_OPEN: list[HttpClientTransport] = []


def _t(**kwargs: Any) -> HttpClientTransport:
    transport = HttpClientTransport(**kwargs)
    _OPEN.append(transport)
    return transport


@pytest.fixture(autouse=True)
def _close_transports() -> Iterator[None]:
    yield
    while _OPEN:
        _OPEN.pop().close()


def _req(url: str, method: str = "GET", **kwargs: Any) -> HttpRequest:
    kwargs.setdefault("timeout", Timeout(connect=2, read=2, total=5))
    return HttpRequest(method=method, url=url, headers={"Accept": "application/json"}, **kwargs)


def test_get_and_keepalive_pool() -> None:
    transport = _t()
    with _server() as (base, server):
        r1 = transport.send(_req(base + "/ok"))
        transport.send(_req(base + "/ok?x=1"))
        assert r1.status_code == 200 and r1.body == b'{"webHooks": []}'
        assert r1.headers["X-REQUEST-ID"] == "local:1"
        assert transport.idle_connections() == 1
        assert server.seen[1][1] == "/ok?x=1"
        assert server.seen[0][2]["Accept-Encoding"] == "identity"
        transport.send(_req(base + "/ok", method="POST", body=b"{}"))
        assert transport.idle_connections() == 1
        transport.close()
        assert transport.idle_connections() == 0
    with pytest.raises(ConfigurationError):
        transport.send(_req(base + "/ok"))


def test_stale_pooled_connection_is_replayed_for_get() -> None:
    transport = _t()
    with _server() as (base, server):
        # "/drop" answers normally (keep-alive, no "Connection: close") and then the server
        # silently closes the socket, leaving a dead connection in the client pool.
        assert transport.send(_req(base + "/drop")).status_code == 200
        assert transport.idle_connections() == 1
        time.sleep(0.05)
        assert transport.send(_req(base + "/ok")).status_code == 200
        assert [path for _, path, _, _ in server.seen] == ["/drop", "/ok"]


def test_connection_refused_is_not_established() -> None:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    with pytest.raises(APIConnectionError) as info:
        _t().send(_req(f"http://127.0.0.1:{port}/x"))
    assert info.value.phase is FailurePhase.NOT_ESTABLISHED


def test_dns_failure_is_not_established(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_dns(*_: Any, **__: Any) -> Any:
        raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")

    monkeypatch.setattr(socket, "getaddrinfo", no_dns)
    with pytest.raises(APIConnectionError) as info:
        _t().send(_req("http://nfeio-sdk-test.invalid/x"))
    assert info.value.phase is FailurePhase.NOT_ESTABLISHED


def test_read_timeout_is_maybe_sent() -> None:
    with _server() as (base, _), pytest.raises(APITimeoutError) as info:
        _t().send(_req(base + "/slow", method="POST", body=b"{}", timeout=Timeout(1, 0.2, 5)))
    assert info.value.phase is FailurePhase.MAYBE_SENT


def test_total_deadline() -> None:
    with _server() as (base, _), pytest.raises(APITimeoutError):
        _t().send(_req(base + "/slow", timeout=Timeout(1, 5, 0.3)))


def test_server_closes_connection_is_maybe_sent() -> None:
    with _server() as (base, _), pytest.raises(APIConnectionError) as info:
        _t().send(_req(base + "/close", method="POST", body=b"{}"))
    assert info.value.phase is FailurePhase.MAYBE_SENT


def test_response_size_limit() -> None:
    with _server() as (base, _):
        with pytest.raises(ResponseTooLargeError):
            _t().send(_req(base + "/big", max_response_bytes=100_000))
        with pytest.raises(ResponseTooLargeError):
            _t().send(_req(base + "/declared-big", max_response_bytes=100_000))
        ok = _t().send(_req(base + "/big", max_response_bytes=400_000))
        assert len(ok.body) == 300_000


def test_unsupported_scheme() -> None:
    with pytest.raises(ConfigurationError):
        _t().send(_req("ftp://example.com/x"))


def test_repr_hides_authorization() -> None:
    req = HttpRequest(
        method="GET",
        url="https://api.nfe.io/v1/x?s=secret",
        headers={"Authorization": "k3y-123456"},
    )
    assert "k3y-123456" not in repr(req) and "s=secret" not in repr(req)


@pytest.fixture(scope="module")
def self_signed(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    if shutil.which("openssl") is None:
        pytest.skip("openssl not available to create a test certificate")
    directory = tmp_path_factory.mktemp("tls")
    cert, key = directory / "cert.pem", directory / "key.pem"
    openssl = shutil.which("openssl")
    assert openssl is not None
    subprocess.run(  # noqa: S603 - fixed arguments, test only
        [
            openssl,
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "1",
            "-subj",
            "/CN=127.0.0.1",
            "-addext",
            "subjectAltName=IP:127.0.0.1",
            "-keyout",
            str(key),
            "-out",
            str(cert),
        ],
        check=True,
        capture_output=True,
    )
    return cert, key


def _server_tls(cert: Path, key: Path) -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert, key)
    return ctx


def test_self_signed_rejected_then_trusted_via_ca_bundle(self_signed: tuple[Path, Path]) -> None:
    cert, key = self_signed
    with _server(_server_tls(cert, key)) as (base, _):
        with pytest.raises(APIConnectionError) as info:
            _t().send(_req(base + "/ok"))
        assert info.value.phase is FailurePhase.NOT_ESTABLISHED
        trusted = _t(ca_bundle=cert)
        assert trusted.send(_req(base + "/ok")).status_code == 200
        client = NfeClient(api_key="k" * 12, base_urls={"account": base}, ca_bundle=cert)
        assert client.webhooks.list() == []
        client.close()


async def test_async_client_over_real_socket(self_signed: tuple[Path, Path]) -> None:
    cert, key = self_signed
    with _server(_server_tls(cert, key)) as (base, server):
        async with AsyncNfeClient(
            api_key="k" * 12, base_urls={"account": base}, ca_bundle=cert
        ) as client:
            assert await client.webhooks.list() == []
        assert server.seen[0][2]["Authorization"] == "k" * 12
    transport = ThreadedAsyncTransport(HttpClientTransport())
    await transport.aclose()

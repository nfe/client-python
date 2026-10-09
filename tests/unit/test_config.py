from __future__ import annotations

import math
import ssl

import pytest

from nfeio import ApiFamily, ConfigurationError, NfeClient, RequestOptions, Timeout
from nfeio._config import ClientConfig, SecretStr, build_ssl_context, build_user_agent, mask_secret
from tests.helpers import API_KEY, DATA_KEY, FakeTransport, make_client, resp


def test_two_clients_keep_their_own_keys() -> None:
    t1, t2 = FakeTransport(resp(200, {"webHooks": []})), FakeTransport(resp(200, {"webHooks": []}))
    make_client(t1, api_key="key-AAAAAAAAAAAA").webhooks.list()
    make_client(t2, api_key="key-BBBBBBBBBBBB").webhooks.list()
    assert t1.last.headers["Authorization"] == "key-AAAAAAAAAAAA"
    assert t2.last.headers["Authorization"] == "key-BBBBBBBBBBBB"


def test_resources_are_attributes() -> None:
    client = make_client(FakeTransport())
    for name in ("service_invoices", "companies", "certificates", "webhooks", "lookups"):
        assert hasattr(client, name)


def test_env_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NFE_API_KEY", "env-main-key-123456")
    monkeypatch.setenv("NFE_DATA_API_KEY", "env-data-key-654321")
    cfg = ClientConfig.build()
    assert cfg.key_for(ApiFamily.SERVICE_INVOICES, None) == "env-main-key-123456"
    assert cfg.key_for(ApiFamily.ADDRESS, None) == "env-data-key-654321"


def test_lookup_without_data_key_fails_before_io(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NFE_DATA_API_KEY", raising=False)
    transport = FakeTransport()
    client = NfeClient(api_key=API_KEY, transport=transport)
    with pytest.raises(ConfigurationError, match="data_api_key"):
        client.lookups.cep("01310-100")
    assert transport.requests == []


def test_no_key_at_all(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NFE_API_KEY", raising=False)
    transport = FakeTransport()
    client = NfeClient(transport=transport)
    with pytest.raises(ConfigurationError, match="NFE_API_KEY"):
        client.service_invoices.list("abc")
    assert transport.requests == []


def test_main_key_used_for_fiscal_and_data_key_for_lookups() -> None:
    transport = FakeTransport(
        resp(200, {"serviceInvoices": [], "page": 1}),
        resp(200, {"address": {"postalCode": "01310100"}}),
    )
    client = make_client(transport)
    client.service_invoices.list("abc")
    client.lookups.cep("01310100")
    assert transport.requests[0].headers["Authorization"] == API_KEY
    assert transport.requests[1].headers["Authorization"] == DATA_KEY
    assert API_KEY not in transport.requests[0].url


def test_base_url_override_and_https_only() -> None:
    transport = FakeTransport(
        resp(200, {"serviceInvoices": [], "page": 1}), resp(200, {"webHooks": []})
    )
    client = make_client(transport, base_urls={"service_invoices": "https://localhost:8443/"})
    client.service_invoices.list("abc")
    client.webhooks.list()
    assert transport.requests[0].url.startswith("https://localhost:8443/v1/companies/abc/")
    assert transport.requests[1].url.startswith("https://api.nfse.io/v2/webhooks")
    with pytest.raises(ConfigurationError, match="https"):
        NfeClient(api_key="x" * 10, base_urls={"service_invoices": "http://api.nfe.io"})
    with pytest.raises(ConfigurationError, match="unknown API family"):
        NfeClient(api_key="x" * 10, base_urls={"nope": "https://x"})
    with pytest.raises(ConfigurationError):
        NfeClient(api_key="x" * 10, base_urls={"address": "https://user:pw@host"})


@pytest.mark.parametrize("bad", [None, 0, -1, math.inf, math.nan, "10", True])
def test_timeout_must_be_finite(bad: object) -> None:
    with pytest.raises(ConfigurationError):
        NfeClient(api_key="x" * 10, timeout=bad)  # type: ignore[arg-type]


def test_timeout_coercion() -> None:
    assert Timeout.coerce(90) == Timeout(connect=10.0, read=90.0, total=90.0)
    assert Timeout.coerce(5) == Timeout(connect=5.0, read=5.0, total=5.0)
    custom = Timeout(connect=1, read=2, total=3)
    assert Timeout.coerce(custom) is custom
    with pytest.raises(ConfigurationError):
        Timeout(connect=0)


def test_per_call_timeout_and_retries() -> None:
    transport = FakeTransport(resp(503), resp(200, {"webHooks": []}))
    client = make_client(transport)
    from nfeio import ServerError

    with pytest.raises(ServerError):
        client.webhooks.list(options=RequestOptions(timeout=90, max_retries=0))
    assert len(transport.requests) == 1
    assert transport.requests[0].timeout.read == 90
    client.webhooks.list()
    assert transport.requests[1].timeout == Timeout()


@pytest.mark.parametrize("name", ["Authorization", "user-agent", "Content-Type"])
def test_protected_headers(name: str) -> None:
    with pytest.raises(ConfigurationError):
        RequestOptions(extra_headers={name: "x"})


def test_extra_headers_and_idempotency_key_are_sent() -> None:
    transport = FakeTransport(resp(200, {"webHooks": []}))
    make_client(transport).webhooks.list(
        options=RequestOptions(idempotency_key="abc-1", extra_headers={"X-Trace": "t1"})
    )
    assert transport.last.headers["Idempotency-Key"] == "abc-1"
    assert transport.last.headers["X-Trace"] == "t1"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"idempotency_key": "a\r\nb"},
        {"idempotency_key": ""},
        {"extra_headers": {"X-A": "v\n"}},
        {"extra_headers": {"bad name": "v"}},
        {"max_retries": -1},
        {"max_retries": 11},
        {"api_key": ""},
    ],
)
def test_request_options_validation(kwargs: dict[str, object]) -> None:
    with pytest.raises(ConfigurationError):
        RequestOptions(**kwargs)  # type: ignore[arg-type]


def test_per_call_api_key_override() -> None:
    transport = FakeTransport(resp(200, {"webHooks": []}))
    make_client(transport).webhooks.list(options=RequestOptions(api_key="override-key-999"))
    assert transport.last.headers["Authorization"] == "override-key-999"


def test_secret_masking() -> None:
    assert mask_secret("abcdefghijkl1234") == "****1234"
    assert mask_secret("short") == "****"
    secret = SecretStr("abcdefghijkl1234")
    assert "abcdefghijkl" not in repr(secret) and "abcdefghijkl" not in str(secret)
    assert secret.get_secret_value() == "abcdefghijkl1234"
    import pickle

    with pytest.raises(TypeError):
        pickle.dumps(secret)
    client = NfeClient(api_key=API_KEY, data_api_key=DATA_KEY, transport=FakeTransport())
    text = repr(client) + repr(client._config) + repr(RequestOptions(api_key=API_KEY))
    assert API_KEY not in text and DATA_KEY not in text
    assert API_KEY[-4:] in text


def test_user_agent_format(monkeypatch: pytest.MonkeyPatch) -> None:
    import platform
    import sys

    from nfeio import __version__

    monkeypatch.setattr(platform, "system", lambda: "Linux")
    expected = (
        f"nfe-io-python/{__version__} python/{sys.version_info[0]}.{sys.version_info[1]} linux"
    )
    assert build_user_agent(None) == expected
    assert build_user_agent(("odoo-l10n_br_nfse_nfeio", "18.0.1.0")).endswith(
        " odoo-l10n_br_nfse_nfeio/18.0.1.0"
    )
    transport = FakeTransport(resp(200, {"webHooks": []}))
    make_client(transport, app_info=("erp", "1.0")).webhooks.list()
    assert transport.last.headers["User-Agent"].endswith(" erp/1.0")
    assert transport.last.headers["Accept-Encoding"] == "identity"


@pytest.mark.parametrize("app_info", [("a b", "1"), ("a", "1\r\n"), ("only",), "str"])
def test_app_info_validation(app_info: object) -> None:
    with pytest.raises(ConfigurationError):
        NfeClient(api_key="x" * 10, app_info=app_info)  # type: ignore[arg-type]


def test_ssl_context_must_verify() -> None:
    insecure = ssl.create_default_context()
    insecure.check_hostname = False
    insecure.verify_mode = ssl.CERT_NONE
    with pytest.raises(ConfigurationError):
        NfeClient(api_key="x" * 10, ssl_context=insecure)
    no_hostname = ssl.create_default_context()
    no_hostname.check_hostname = False
    with pytest.raises(ConfigurationError):
        build_ssl_context(no_hostname)
    ok = build_ssl_context(ssl.create_default_context())
    assert ok.minimum_version >= ssl.TLSVersion.TLSv1_2
    with pytest.raises(ConfigurationError):
        build_ssl_context(ca_bundle="/nonexistent/ca.pem")
    with pytest.raises(ConfigurationError):
        NfeClient(api_key="x" * 10, transport=FakeTransport(), ssl_context=ok)


def test_other_config_validation() -> None:
    with pytest.raises(ConfigurationError):
        NfeClient(api_key="x" * 10, max_response_bytes=10)
    with pytest.raises(ConfigurationError):
        NfeClient(api_key="x" * 10, max_retries=True)
    with pytest.raises(ConfigurationError):
        NfeClient(api_key="")
    with pytest.raises(ConfigurationError):
        NfeClient(api_key="abc\ndef")


def test_context_manager_closes_transport() -> None:
    transport = FakeTransport()
    with NfeClient(api_key="x" * 10, transport=transport):
        pass
    assert transport.closed

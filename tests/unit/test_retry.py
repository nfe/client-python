from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import pytest

from nfeio import (
    APIConnectionError,
    APITimeoutError,
    FailurePhase,
    RateLimitError,
    RequestOptions,
    ServerError,
)
from nfeio._core.retry import parse_retry_after, should_retry_failure, should_retry_status
from tests.helpers import (
    API_KEY,
    COMPANY_ID,
    FakeClock,
    FakeTransport,
    invoice_json,
    make_client,
    resp,
)

RETRYABLE = [408, 429, 500, 502, 503, 504]
NOT_RETRYABLE = [400, 401, 403, 404, 405, 409, 422, 501, 505]


@pytest.mark.parametrize("method", ["GET", "HEAD", "PUT", "DELETE"])
@pytest.mark.parametrize("status", RETRYABLE)
def test_idempotent_methods_retry_transient_status(method: str, status: int) -> None:
    assert should_retry_status(method, status)


@pytest.mark.parametrize("status", RETRYABLE + NOT_RETRYABLE)
def test_post_never_retries_on_status(status: int) -> None:
    assert not should_retry_status("POST", status)


@pytest.mark.parametrize("status", NOT_RETRYABLE)
def test_other_4xx_not_retried(status: int) -> None:
    assert not should_retry_status("GET", status)


def test_failure_phase_table() -> None:
    assert should_retry_failure("GET", FailurePhase.MAYBE_SENT)
    assert should_retry_failure("GET", FailurePhase.NOT_ESTABLISHED)
    assert should_retry_failure("POST", FailurePhase.NOT_ESTABLISHED)
    assert not should_retry_failure("POST", FailurePhase.MAYBE_SENT)


def test_get_503_then_200() -> None:
    clock = FakeClock()
    transport = FakeTransport(resp(503), resp(200, {"webHooks": []}))
    assert make_client(transport, clock).webhooks.list() == []
    assert len(transport.requests) == 2
    assert clock.sleeps == [1.0]


def test_backoff_sequence_and_limit() -> None:
    clock = FakeClock()
    transport = FakeTransport(resp(503), resp(503), resp(503), resp(503))
    with pytest.raises(ServerError):
        make_client(transport, clock).webhooks.list()
    assert len(transport.requests) == 4  # 1 + max_retries=3
    assert clock.sleeps == [1.0, 2.0, 4.0]


def test_backoff_caps_at_max_delay() -> None:
    clock = FakeClock()
    transport = FakeTransport(*[resp(502)] * 7)
    client = make_client(transport, clock, max_retries=6, retry_max_delay=5.0)
    with pytest.raises(ServerError):
        client.webhooks.list()
    assert clock.sleeps == [1.0, 2.0, 4.0, 5.0, 5.0, 5.0]


def test_jitter_bounds() -> None:
    from nfeio._config import ClientConfig
    from nfeio._core.retry import backoff_delay

    low = ClientConfig.build(api_key="k" * 10, random=lambda: 0.0)
    high = ClientConfig.build(api_key="k" * 10, random=lambda: 0.999999)
    assert backoff_delay(1, low) == pytest.approx(0.7)
    assert backoff_delay(2, high) == pytest.approx(2.6, rel=1e-3)


def test_max_retries_zero() -> None:
    transport = FakeTransport(resp(503))
    with pytest.raises(ServerError):
        make_client(transport, max_retries=0).webhooks.list()
    assert len(transport.requests) == 1


def test_post_issuance_504_not_retried_and_outcome_unknown() -> None:
    transport = FakeTransport(resp(504))
    with pytest.raises(ServerError) as info:
        make_client(transport).service_invoices.create(
            COMPANY_ID, {"servicesAmount": 1}, external_id="pedido-2"
        )
    assert len(transport.requests) == 1
    assert info.value.outcome_unknown is True
    assert info.value.external_id == "pedido-2"


def test_post_500_with_idempotency_key_not_retried() -> None:
    transport = FakeTransport(resp(500))
    with pytest.raises(ServerError):
        make_client(transport).service_invoices.create(
            COMPANY_ID, {}, options=RequestOptions(idempotency_key="idem-1")
        )
    assert len(transport.requests) == 1


def test_post_retried_when_connection_not_established() -> None:
    clock = FakeClock()
    transport = FakeTransport(
        APIConnectionError("refused", phase=FailurePhase.NOT_ESTABLISHED),
        resp(202, {"id": "abc123", "flowStatus": "WaitingSend"}),
    )
    invoice = make_client(transport, clock).service_invoices.create(COMPANY_ID, {})
    assert invoice.id == "abc123"
    assert len(transport.requests) == 2
    assert clock.sleeps == [1.0]


def test_post_read_timeout_not_retried() -> None:
    transport = FakeTransport(APITimeoutError("read timeout", phase=FailurePhase.MAYBE_SENT))
    with pytest.raises(APITimeoutError) as info:
        make_client(transport).service_invoices.create(COMPANY_ID, {}, external_id="p-3")
    assert len(transport.requests) == 1
    assert info.value.outcome_unknown is True
    assert info.value.external_id == "p-3"


def test_get_connection_errors_retried_then_raised_without_outcome_flag() -> None:
    transport = FakeTransport(*[APIConnectionError("reset", phase=FailurePhase.MAYBE_SENT)] * 4)
    with pytest.raises(APIConnectionError) as info:
        make_client(transport).webhooks.list()
    assert len(transport.requests) == 4
    assert info.value.outcome_unknown is False


def test_os_error_from_custom_transport_is_wrapped() -> None:
    transport = FakeTransport(ConnectionResetError("x"), resp(200, {"webHooks": []}))
    assert make_client(transport).webhooks.list() == []


def test_post_429_not_retried() -> None:
    transport = FakeTransport(resp(429, headers={"Retry-After": "2"}))
    with pytest.raises(RateLimitError) as info:
        make_client(transport).service_invoices.create(COMPANY_ID, {})
    assert info.value.retry_after == 2
    assert len(transport.requests) == 1


def test_retry_after_seconds_honoured() -> None:
    clock = FakeClock()
    transport = FakeTransport(resp(429, headers={"Retry-After": "7"}), resp(200, {"webHooks": []}))
    make_client(transport, clock).webhooks.list()
    assert clock.sleeps == [7.0]


def test_retry_after_http_date() -> None:
    now = datetime(2026, 10, 8, 12, 0, 0, tzinfo=timezone.utc)
    header = format_datetime(now + timedelta(seconds=5), usegmt=True)
    assert parse_retry_after(header, now) == pytest.approx(5.0)
    assert parse_retry_after("garbage", now) is None
    assert parse_retry_after("", now) is None
    assert parse_retry_after(None, now) is None
    assert parse_retry_after(format_datetime(now - timedelta(seconds=5), usegmt=True), now) == 0


def test_retry_after_too_long_raises_without_waiting() -> None:
    clock = FakeClock()
    transport = FakeTransport(resp(429, headers={"Retry-After": "3600"}))
    with pytest.raises(RateLimitError) as info:
        make_client(transport, clock).webhooks.list()
    assert info.value.retry_after == 3600
    assert clock.sleeps == []
    assert len(transport.requests) == 1


def test_retry_log_has_no_secrets(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="nfeio")
    transport = FakeTransport(resp(502), resp(200, {"webHooks": []}))
    make_client(transport).webhooks.list()
    retry_logs = [r for r in caplog.records if "retry" in r.getMessage()]
    assert retry_logs
    message = retry_logs[0].getMessage()
    assert "502" in message and "attempt 1" in message and "0HTEST" in message
    assert all(API_KEY not in r.getMessage() for r in caplog.records)


def test_find_by_external_id_is_retryable_get() -> None:
    transport = FakeTransport(
        resp(503), resp(200, {"serviceInvoices": [invoice_json()], "page": 1})
    )
    found = make_client(transport).service_invoices.find_by_external_id(COMPANY_ID, "x")
    assert found is not None

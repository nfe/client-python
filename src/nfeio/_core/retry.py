"""Method- and phase-aware retry policy (port of the PHP SDK ``RetryingTransport``, stricter).

| Method                  | 429  | 408/500/502/503/504 | not established | maybe sent |
|-------------------------|------|---------------------|-----------------|------------|
| GET, HEAD, PUT, DELETE  | yes  | yes                 | yes             | yes        |
| POST (any)              | no   | no                  | yes             | no         |

A POST is never retried after the request may have reached the server: the API is known to
create the invoice and still answer 500/504. ``Idempotency-Key`` does not change this table
because the API ignores the header today.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

from .._config import ClientConfig
from ..errors import APIConnectionError, FailurePhase
from .ops import Op, Send, Sleep, UtcNow
from .redact import log_path
from .transport import HttpRequest, HttpResponse

logger = logging.getLogger("nfeio")

IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "PUT", "DELETE", "OPTIONS"})
RETRYABLE_STATUS = frozenset({408, 429, 500, 502, 503, 504})


def is_idempotent(method: str) -> bool:
    return method.upper() in IDEMPOTENT_METHODS


def should_retry_status(method: str, status: int) -> bool:
    return is_idempotent(method) and status in RETRYABLE_STATUS


def should_retry_failure(method: str, phase: FailurePhase) -> bool:
    return is_idempotent(method) or phase is FailurePhase.NOT_ESTABLISHED


def backoff_delay(attempt: int, cfg: ClientConfig) -> float:
    """``min(max_delay, base * 2**(attempt-1)) * U(0.7, 1.3)`` for ``attempt >= 1``."""
    raw = min(cfg.retry_max_delay, cfg.retry_base_delay * (2 ** max(0, attempt - 1)))
    return float(raw * (0.7 + 0.6 * cfg.random()))


def parse_retry_after(value: str | None, now: datetime) -> float | None:
    """Parse ``Retry-After`` as integer seconds or an HTTP-date. ``None`` if absent/invalid."""
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    if text.isdigit():
        return float(int(text))
    try:
        when = parsedate_to_datetime(text)
    except (TypeError, ValueError, IndexError):
        return None
    if when.tzinfo is None:
        return None
    seconds = (when - now).total_seconds()
    if not math.isfinite(seconds):
        return None
    return max(0.0, seconds)


def send_with_retry(
    cfg: ClientConfig,
    request: HttpRequest,
    *,
    max_retries: int,
    external_id: str | None = None,
) -> Op[HttpResponse]:
    """Send ``request``, retrying per the table above. Returns the last response (any status).

    Raises the transport's :class:`APIConnectionError` when retries are exhausted or not
    allowed; for non-idempotent requests that may have been sent it is flagged
    ``outcome_unknown=True`` and carries ``external_id``.
    """
    method = request.method.upper()
    parts = urlsplit(request.url)
    attempt = 0
    while True:
        try:
            response: HttpResponse = yield Send(request)
        except APIConnectionError as exc:
            if attempt < max_retries and should_retry_failure(method, exc.phase):
                attempt += 1
                delay = backoff_delay(attempt, cfg)
                _log_retry(
                    method,
                    parts.hostname,
                    log_path(parts.path),
                    type(exc).__name__,
                    attempt,
                    max_retries,
                    delay,
                    None,
                )
                yield Sleep(delay)
                continue
            if not is_idempotent(method) and exc.phase is FailurePhase.MAYBE_SENT:
                exc.outcome_unknown = True
                exc.external_id = external_id
            raise
        status = response.status_code
        if attempt < max_retries and should_retry_status(method, status):
            now: datetime = yield UtcNow()
            retry_after = parse_retry_after(response.headers.get("retry-after"), now)
            if retry_after is not None and retry_after > cfg.max_retry_after:
                return response
            attempt += 1
            delay = retry_after if retry_after is not None else backoff_delay(attempt, cfg)
            _log_retry(
                method,
                parts.hostname,
                log_path(parts.path),
                str(status),
                attempt,
                max_retries,
                delay,
                response.headers.get("x-request-id"),
            )
            yield Sleep(delay)
            continue
        return response


def _log_retry(
    method: str,
    host: str | None,
    path: str,
    reason: str,
    attempt: int,
    max_retries: int,
    delay: float,
    request_id: str | None,
) -> None:
    # Never log headers, query strings or bodies: they may carry keys or pre-signed tokens.
    logger.debug(
        "nfeio retry: %s %s%s got %s; attempt %d of %d in %.2fs (request_id=%s)",
        method,
        host,
        path,
        reason,
        attempt,
        max_retries,
        delay,
        request_id,
    )

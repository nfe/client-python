"""Turn an HTTP error response into the right :class:`~nfeio.errors.APIError`.

The NFE.io API uses (at least) these error bodies, all handled here:

* empty body (401/403, unserved routes);
* a raw JSON string: ``"pageCount must be between 1 and 50"``;
* ``{"errors": [{"code": 40401, "message": "..."}]}`` (with or without ``code``);
* ``{"code": ..., "message": "..."}``;
* ASP.NET ProblemDetails: ``{"title", "status", "traceId", "errors": {"field": ["msg"]}}``.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

from .._config import ApiFamily
from ..errors import (
    APIError,
    AuthenticationError,
    ConflictError,
    DuplicateExternalIdError,
    InvalidRequestError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    ServerError,
)
from .retry import is_idempotent, parse_retry_after
from .transport import HttpResponse

MAX_MESSAGE_CHARS = 1000
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]+")
_DUPLICATE_RE = re.compile(r"external\s*id.*already\s+exists", re.IGNORECASE | re.DOTALL)
_DUPLICATE_ID_RE = re.compile(r"external\s*id\s*\((.*?)\)", re.IGNORECASE | re.DOTALL)


def sanitize(text: str) -> str:
    cleaned = _CONTROL_RE.sub(" ", text).strip()
    cleaned = re.sub(r" {2,}", " ", cleaned)
    if len(cleaned) > MAX_MESSAGE_CHARS:
        cleaned = cleaned[: MAX_MESSAGE_CHARS - 1] + "…"
    return cleaned


def _default_message(status: int) -> str:
    try:
        phrase = HTTPStatus(status).phrase
    except ValueError:
        phrase = "HTTP error"
    return f"{status} {phrase}"


def _from_errors_list(items: list[Any]) -> tuple[str, int | str | None]:
    messages: list[str] = []
    code: int | str | None = None
    for item in items:
        if isinstance(item, dict):
            msg = item.get("message") or item.get("Message")
            if code is None and isinstance(item.get("code"), (int, str)):
                code = item["code"]
            if isinstance(msg, str) and msg:
                messages.append(msg)
        elif isinstance(item, str) and item:
            messages.append(item)
    return "; ".join(messages), code


def extract_error(body: bytes, status: int) -> tuple[str, int | str | None, str | None]:
    """Return ``(message, error_code, trace_id)`` from an error body."""
    if not body or not body.strip():
        return "", None, None
    try:
        text = body.decode("utf-8-sig")
    except UnicodeDecodeError:
        return "", None, None
    try:
        data: Any = json.loads(text)
    except (ValueError, RecursionError):
        return sanitize(text), None, None
    message = ""
    code: int | str | None = None
    trace_id: str | None = None
    if isinstance(data, str):
        message = data
    elif isinstance(data, dict):
        raw_trace = data.get("traceId")
        trace_id = raw_trace if isinstance(raw_trace, str) else None
        errors = data.get("errors")
        if isinstance(errors, list):
            message, code = _from_errors_list(errors)
        elif isinstance(errors, dict):
            details = []
            for name, msgs in errors.items():
                values: Iterable[Any] = msgs if isinstance(msgs, list) else [msgs]
                for msg in values:
                    if isinstance(msg, str) and msg:
                        details.append(f"{name}: {msg}" if name else msg)
            title = data.get("title") if isinstance(data.get("title"), str) else ""
            message = " ".join(part for part in (title, "; ".join(details)) if part)
        if not message:
            for key in ("message", "Message", "detail", "title", "error"):
                value = data.get(key)
                if isinstance(value, str) and value:
                    message = value
                    break
        if code is None and isinstance(data.get("code"), (int, str)):
            code = data["code"]
    return sanitize(message), code, trace_id


def _scrub(text: str, secrets: Iterable[str]) -> str:
    for secret in secrets:
        if secret and len(secret) >= 4:
            text = text.replace(secret, "<redacted>")
    return text


def error_from_response(
    response: HttpResponse,
    *,
    family: ApiFamily,
    method: str,
    external_id: str | None = None,
    secrets: Iterable[str] = (),
) -> APIError:
    status = response.status_code
    secrets = tuple(secrets)
    body = response.body
    if secrets:
        for secret in secrets:
            if secret and len(secret) >= 4 and secret.encode() in body:
                body = body.replace(secret.encode(), b"<redacted>")
    message, code, trace_id = extract_error(body, status)
    message = _scrub(message, secrets)
    outcome_unknown = not is_idempotent(method) and (status in (408, 429) or status >= 500)
    kwargs: dict[str, Any] = {
        "status_code": status,
        "body": body,
        "headers": response.headers,
        "error_code": code,
        "trace_id": trace_id,
        "outcome_unknown": outcome_unknown,
        "external_id": external_id,
    }

    if status == 400 and _DUPLICATE_RE.search(message):
        if external_id is None:
            match = _DUPLICATE_ID_RE.search(message)
            kwargs["external_id"] = match.group(1) if match else None
        return DuplicateExternalIdError(message, **kwargs)
    if status == 401:
        return AuthenticationError(
            message or f"authentication failed: missing or invalid {family.key_param}", **kwargs
        )
    if status == 403:
        hint = (
            f"permission denied for this API family ({family.value}); it uses "
            f"{family.key_param} — check that the right key was configured"
        )
        return PermissionDeniedError(f"{message} — {hint}" if message else hint, **kwargs)
    if status == 404:
        return NotFoundError(
            message or "404 Not Found (empty body: the route may not exist)", **kwargs
        )
    if status == 409:
        return ConflictError(message or _default_message(status), **kwargs)
    if status == 429:
        retry_after = parse_retry_after(
            response.headers.get("retry-after"), datetime.now(timezone.utc)
        )
        return RateLimitError(
            message or _default_message(status), retry_after=retry_after, **kwargs
        )
    if status == 408 or status >= 500:
        return ServerError(message or _default_message(status), **kwargs)
    return InvalidRequestError(message or _default_message(status), **kwargs)

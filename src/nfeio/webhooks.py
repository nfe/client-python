"""Receive NFE.io webhook deliveries safely (no client needed).

NFE.io signs each delivery with ``X-Hub-Signature: sha1=<HEX>`` where ``HEX`` is
``HMAC-SHA1(secret, raw_body)`` in upper case. Always verify against the **raw request bytes**
(never a re-serialised ``json.dumps`` of a parsed dict).

Deliveries are at-least-once: deduplicate by ``X-Hook-Id`` (:attr:`WebhookEvent.hook_id`).
The protocol has no signed timestamp, so there is no replay window to check.

Example (Flask)::

    from nfeio.webhooks import construct_event
    from nfeio.errors import SignatureVerificationError

    @app.post("/nfeio/webhook")
    def nfeio_webhook():
        try:
            event = construct_event(request.get_data(), request.headers, SECRET)
        except SignatureVerificationError:
            return "", 400
        ...
"""

from __future__ import annotations

import hashlib
import hmac
import json
import string
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .errors import InvalidParameterError, SignatureVerificationError
from .models import NfeObject, ServiceInvoice

__all__ = [
    "HOOK_EVENT_HEADER",
    "HOOK_ID_HEADER",
    "MAX_PAYLOAD_BYTES",
    "SIGNATURE_HEADER",
    "WebhookEvent",
    "construct_event",
    "verify_signature",
]

SIGNATURE_HEADER = "X-Hub-Signature"
HOOK_ID_HEADER = "X-Hook-Id"
HOOK_EVENT_HEADER = "X-Hook-Event"
MAX_PAYLOAD_BYTES = 5 * 1024 * 1024

_HEX = frozenset(string.hexdigits)
_PREFIX = "sha1="


def _as_bytes(value: object) -> bytes | None:
    if isinstance(value, bytes):
        return value
    if isinstance(value, (bytearray, memoryview)):
        return bytes(value)
    if isinstance(value, str):
        return value.encode("utf-8")
    return None


def _first(value: object) -> object:
    if isinstance(value, (list, tuple)):
        return value[0] if value else None
    return value


def verify_signature(
    payload: bytes | bytearray | memoryview | str,
    signature: str | Sequence[str] | None,
    secret: str | bytes,
) -> bool:
    """Return ``True`` only if ``signature`` is ``sha1=<40 hex>`` matching
    ``HMAC-SHA1(secret, payload)`` (hex compared case-insensitively, in constant time).

    Never raises: malformed input, another algorithm, empty secret or unexpected types all
    return ``False``.

    Args:
        payload: the raw request body (``str`` is encoded as UTF-8).
        signature: the ``X-Hub-Signature`` header value (a list uses its first item).
        secret: the webhook secret configured in NFE.io.
    """
    try:
        body = _as_bytes(payload)
        key = _as_bytes(secret)
        header = _first(signature)
        if body is None or not key or not isinstance(header, str):
            return False
        header = header.strip()
        if len(header) != len(_PREFIX) + 40 or header[: len(_PREFIX)].lower() != _PREFIX:
            return False
        received = header[len(_PREFIX) :]
        if not all(ch in _HEX for ch in received):
            return False
        expected = hmac.new(key, body, hashlib.sha1).hexdigest()
        return hmac.compare_digest(expected, received.lower())
    except Exception:  # never raise from a verification helper
        return False


@dataclass(frozen=True, repr=False)
class WebhookEvent:
    """A verified webhook delivery.

    Attributes:
        action: ``body["action"]`` (e.g. ``"issued_successfully"``, ``"ping"``).
        event_type: ``X-Hook-Event`` header (e.g. ``"service_invoice"``), if present.
        hook_id: ``X-Hook-Id`` header — the idempotency key of the delivery.
        data: the payload object (``ServiceInvoice`` for service invoice events; the
            ``webHook`` object for pings).
        body: the whole decoded body.
        raw: the raw bytes received.
    """

    action: str | None
    event_type: str | None
    hook_id: str | None
    data: NfeObject
    body: NfeObject
    raw: bytes

    def __repr__(self) -> str:
        # Never show the body: ping deliveries carry the webhook secret in clear text.
        return (
            f"WebhookEvent(action={self.action!r}, event_type={self.event_type!r}, "
            f"hook_id={self.hook_id!r})"
        )


def _header(headers: Mapping[str, Any], name: str) -> str | None:
    wanted = name.lower()
    for key, value in headers.items():
        if isinstance(key, str) and key.lower() == wanted:
            first = _first(value)
            return first if isinstance(first, str) else None
    return None


def construct_event(
    payload: bytes | bytearray | memoryview | str,
    headers: Mapping[str, Any] | str,
    secret: str | bytes,
) -> WebhookEvent:
    """Verify the signature, then parse the delivery.

    Args:
        payload: the raw request body.
        headers: the request headers (any mapping, case-insensitive lookup) or directly the
            ``X-Hub-Signature`` value.
        secret: the webhook secret.

    Raises:
        SignatureVerificationError: the signature is missing or does not match (the body is
            not parsed in that case).
        InvalidParameterError: the body is larger than 5 MiB or is not a JSON object.
    """
    body = _as_bytes(payload)
    if body is None:
        raise InvalidParameterError("payload must be bytes or str", param="payload")
    if len(body) > MAX_PAYLOAD_BYTES:
        raise InvalidParameterError("webhook payload exceeds 5 MiB", param="payload")
    if isinstance(headers, str):
        signature: str | None = headers
        hook_id = event_type = None
    else:
        signature = _header(headers, SIGNATURE_HEADER)
        hook_id = _header(headers, HOOK_ID_HEADER)
        event_type = _header(headers, HOOK_EVENT_HEADER)
    if not verify_signature(body, signature, secret):
        raise SignatureVerificationError("webhook signature verification failed")
    try:
        decoded = json.loads(body.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise InvalidParameterError("webhook body is not valid JSON", param="payload") from None
    if not isinstance(decoded, dict):
        raise InvalidParameterError("webhook body is not a JSON object", param="payload")
    action = decoded.get("action") if isinstance(decoded.get("action"), str) else None
    inner: Any = decoded.get("payload")
    if not isinstance(inner, dict):
        inner = decoded.get("webHook")
    if not isinstance(inner, dict):
        inner = decoded
    data: NfeObject
    if (event_type or "").lower().startswith("service_invoice") and inner is not decoded:
        data = ServiceInvoice._from_wire(inner)
    else:
        data = NfeObject._from_wire(inner)
    return WebhookEvent(
        action=action,
        event_type=event_type,
        hook_id=hook_id,
        data=data,
        body=NfeObject._from_wire(decoded),
        raw=body,
    )

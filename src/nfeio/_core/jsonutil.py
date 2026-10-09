"""JSON encoding/decoding with exact ``Decimal`` support and size awareness."""

from __future__ import annotations

import json
import math
import re
import secrets
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from ..errors import InvalidParameterError

MAX_JSON_DEPTH = 128
"""Deepest array/object nesting accepted from untrusted JSON (API responses, error bodies and
webhooks). NFE.io payloads nest a handful of levels; the explicit limit rejects a hostile body the
same way on every Python version and platform instead of relying on the interpreter's recursion
limit (Python 3.14 decodes 100,000 nested levels without ``RecursionError``)."""

# A JSON string, honouring escaped quotes and backslashes. The closing quote is optional so an
# unterminated string consumes the rest of the text instead of being rescanned from every escaped
# quote inside it (which would be quadratic); such a body is invalid JSON anyway.
_JSON_STRING = re.compile(r'"[^"\\]*(?:\\.[^"\\]*)*"?', re.DOTALL)
_NOT_BRACKET = re.compile(r"[^\[\]{}]+")


def _format_decimal(value: Decimal) -> str:
    if not value.is_finite():
        raise InvalidParameterError(f"cannot send non-finite number {value!s}")
    text = format(value, "f")
    return "0" if text in ("-0", "") else text


def dumps(obj: Any) -> bytes:
    """Serialise a request body. ``Decimal`` becomes an exact JSON number
    (``Decimal("100.10")`` → ``100.10``); ``date``/``datetime`` become ISO 8601 strings."""
    token = secrets.token_hex(8)
    decimals: list[Decimal] = []

    def convert(value: Any) -> Any:
        if isinstance(value, Decimal):
            decimals.append(value)
            return f"__nfeio_decimal_{token}_{len(decimals) - 1}__"
        if isinstance(value, bool) or value is None or isinstance(value, (str, int)):
            return value
        if isinstance(value, float):
            if not math.isfinite(value):
                raise InvalidParameterError(f"cannot send non-finite number {value!r}")
            return value
        if isinstance(value, datetime | date):
            return value.isoformat()
        if isinstance(value, Mapping):
            out: dict[str, Any] = {}
            for key, item in value.items():
                if not isinstance(key, str):
                    raise InvalidParameterError(
                        f"request body keys must be strings, got {type(key).__name__}"
                    )
                out[key] = convert(item)
            return out
        if isinstance(value, (list, tuple)):
            return [convert(item) for item in value]
        raise InvalidParameterError(f"cannot serialise {type(value).__name__} in a request body")

    text = json.dumps(convert(obj), ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    for index, value in enumerate(decimals):
        text = text.replace(f'"__nfeio_decimal_{token}_{index}__"', _format_decimal(value), 1)
    return text.encode("utf-8")


def _check_depth(text: str) -> None:
    """Raise ``ValueError`` when ``text`` nests arrays/objects deeper than :data:`MAX_JSON_DEPTH`.

    Linear time and no recursion: strings are removed first (brackets inside them do not count),
    then only ``[ ] { }`` are scanned."""
    if text.count("[") + text.count("{") <= MAX_JSON_DEPTH:
        return
    depth = 0
    for char in _NOT_BRACKET.sub("", _JSON_STRING.sub("", text)):
        if char in "[{":
            depth += 1
            if depth > MAX_JSON_DEPTH:
                raise ValueError(f"JSON nested deeper than {MAX_JSON_DEPTH} levels")
        else:
            depth -= 1


def loads(body: bytes | str) -> Any:
    """Decode untrusted JSON (bytes as UTF-8 with optional BOM). Raises ``ValueError`` when the
    body is invalid or nested deeper than :data:`MAX_JSON_DEPTH`."""
    text = body.decode("utf-8-sig") if isinstance(body, bytes) else body
    _check_depth(text)
    return json.loads(text)

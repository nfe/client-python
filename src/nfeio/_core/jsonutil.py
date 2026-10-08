"""JSON encoding/decoding with exact ``Decimal`` support and size awareness."""

from __future__ import annotations

import json
import math
import secrets
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from ..errors import InvalidParameterError


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


def loads(body: bytes) -> Any:
    """Decode a response body (UTF-8, optional BOM). Raises ``ValueError`` when invalid."""
    return json.loads(body.decode("utf-8-sig"))

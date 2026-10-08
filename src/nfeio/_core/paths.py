"""Validation and encoding of every value interpolated into a URL path.

Nothing reaches a path without going through this module: opaque ids must match a strict
pattern (no path traversal), free text is percent-encoded as a single segment, and Brazilian
documents are normalised and checked locally (data lookups may be billed per call).
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Final
from urllib.parse import quote

from ..errors import InvalidParameterError

_OPAQUE_ID_RE: Final = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_CONTROL_RE: Final = re.compile(r"[\x00-\x1f\x7f]")
_DOC_SEPARATORS_RE: Final = re.compile(r"[.\-/\s]")
_CNPJ_RE: Final = re.compile(r"^[0-9A-Z]{12}[0-9]{2}$")
_ISO_DATE_RE: Final = re.compile(r"^\d{4}-\d{2}-\d{2}$")

UFS: Final = frozenset(
    {
        "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG", "PA",
        "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO",
    }
)  # fmt: skip


def opaque_id(value: object, param: str) -> str:
    """An API identifier: ``^[A-Za-z0-9_-]{1,64}$`` (covers the 24- and 32-hex ids seen)."""
    if not isinstance(value, str) or not _OPAQUE_ID_RE.match(value):
        raise InvalidParameterError(
            f"{param} must be a non-empty identifier of letters, digits, '_' or '-' "
            f"(max 64), got {value!r}",
            param=param,
        )
    return value


def check_free_text(value: object, param: str) -> str:
    if not isinstance(value, str) or not value:
        raise InvalidParameterError(f"{param} must be a non-empty string", param=param)
    if value in (".", "..") or _CONTROL_RE.search(value) or len(value) > 255:
        raise InvalidParameterError(
            f"{param} must not be '.' or '..', contain control characters or exceed 255 characters",
            param=param,
        )
    return value


def free_text_segment(value: object, param: str) -> str:
    """Client-chosen text (e.g. ``externalId``) encoded as exactly one path segment."""
    return quote(check_free_text(value, param), safe="")


def _alnum_value(char: str) -> int:
    # RFB alphanumeric CNPJ: value = ASCII code - 48 ('0'..'9' -> 0..9, 'A' -> 17 ... 'Z' -> 42)
    return ord(char) - 48


def _cnpj_check_digit(body: str) -> int:
    weights = ([2, 3, 4, 5, 6, 7, 8, 9] * 2)[: len(body)]
    total = sum(_alnum_value(ch) * w for ch, w in zip(reversed(body), weights, strict=True))
    remainder = total % 11
    return 0 if remainder < 2 else 11 - remainder


def is_valid_cnpj(value: str) -> bool:
    if not _CNPJ_RE.match(value) or value == "0" * 14:
        return False
    first = _cnpj_check_digit(value[:12])
    second = _cnpj_check_digit(value[:12] + str(first))
    return value[12:] == f"{first}{second}"


def cnpj(value: object, param: str = "cnpj") -> str:
    """Normalise (remove mask, uppercase) and validate a numeric or alphanumeric CNPJ."""
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise InvalidParameterError(f"{param} must be a string", param=param)
    text = str(value) if isinstance(value, int) else value
    normalized = _DOC_SEPARATORS_RE.sub("", text).upper()
    if isinstance(value, int):
        normalized = normalized.zfill(14)
    if not is_valid_cnpj(normalized):
        raise InvalidParameterError(f"{param} is not a valid CNPJ: {value!r}", param=param)
    return normalized


def is_valid_cpf(value: str) -> bool:
    if len(value) != 11 or not value.isdigit() or value == value[0] * 11:
        return False
    digits = [int(ch) for ch in value]
    for size in (9, 10):
        total = sum(d * w for d, w in zip(digits[:size], range(size + 1, 1, -1), strict=True))
        check = (total * 10) % 11 % 10
        if digits[size] != check:
            return False
    return True


def cpf(value: object, param: str = "cpf") -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise InvalidParameterError(f"{param} must be a string", param=param)
    normalized = _DOC_SEPARATORS_RE.sub("", str(value))
    if isinstance(value, int):
        normalized = normalized.zfill(11)
    if not is_valid_cpf(normalized):
        raise InvalidParameterError(f"{param} is not a valid CPF: {value!r}", param=param)
    return normalized


def cep(value: object, param: str = "cep") -> str:
    if not isinstance(value, str):
        raise InvalidParameterError(f"{param} must be a string", param=param)
    normalized = _DOC_SEPARATORS_RE.sub("", value)
    if len(normalized) != 8 or not normalized.isdigit():
        raise InvalidParameterError(f"{param} must have 8 digits, got {value!r}", param=param)
    return normalized


def uf(value: object, param: str = "state") -> str:
    if not isinstance(value, str) or value.strip().upper() not in UFS:
        raise InvalidParameterError(
            f"{param} must be a Brazilian state code (UF), got {value!r}", param=param
        )
    return value.strip().upper()


def iso_date(value: object, param: str) -> str:
    """``date`` (or ``datetime``, date part) or ``"YYYY-MM-DD"`` → ``"YYYY-MM-DD"``."""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str) and _ISO_DATE_RE.match(value):
        try:
            return date.fromisoformat(value).isoformat()
        except ValueError:
            pass
    raise InvalidParameterError(
        f"{param} must be a date or a 'YYYY-MM-DD' string, got {value!r}", param=param
    )

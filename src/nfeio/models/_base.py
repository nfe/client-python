"""``NfeObject``: an immutable, typed view over the JSON the API sent.

Design (decision D1, "lean D"):

* An ``NfeObject`` **is** a ``Mapping[str, Any]`` over the decoded JSON. Nothing is copied out
  or filtered, so every field — including ones this SDK does not know yet — is available by its
  wire name: ``invoice["flowStatus"]``.
* Reading by key returns the wire value, except that a nested mapping comes back as an
  ``NfeObject`` and a list comes back as a *new* list whose mappings are ``NfeObject`` too.
  Mutating what you get never changes the object.
* A few typed snake_case properties exist **only** where the SDK corrects or types something:
  ids, statuses, dates (aware ``datetime``), money and rates (``Decimal``) and documents
  (CNPJ/CPF as normalised ``str``). They are declarative descriptors (``StrField(...)``, ...)
  that remember their wire key, which a test checks against the OpenAPI specs.
* There is no ``__getattr__`` magic: ``obj.items()`` is always the ``Mapping`` method, even
  when the payload has an ``items`` field.
"""

from __future__ import annotations

import copy
import json
import math
import re
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Generic, TypeVar, overload

from .._core.headers import Headers

T = TypeVar("T")
M = TypeVar("M", bound="NfeObject")

_SENSITIVE_KEY_RE = re.compile(r"secret|password|apikey|api_key|token", re.IGNORECASE)


@dataclass(frozen=True)
class ResponseInfo:
    """Metadata of the HTTP response an object or page came from."""

    status_code: int
    headers: Headers

    @property
    def request_id(self) -> str | None:
        """``x-request-id`` — quote it when contacting NFE.io support."""
        return self.headers.get("x-request-id")


def _wrap(value: Any) -> Any:
    if isinstance(value, dict):
        return NfeObject._from_wire(value)
    if isinstance(value, list):
        return [_wrap(item) for item in value]
    return value


def _plain(value: Any) -> Any:
    if isinstance(value, NfeObject):
        return copy.deepcopy(value._data)
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"NfeObject keys must be strings, got {type(key).__name__}")
            out[key] = _plain(item)
        return out
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return copy.deepcopy(value)


def _masked(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: ("<redacted>" if _SENSITIVE_KEY_RE.search(key) and item else _masked(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_masked(item) for item in value]
    return value


class NfeObject(Mapping[str, Any]):
    """Immutable mapping over an API JSON object, with typed properties on subclasses."""

    __slots__ = ("_data", "_last_response")

    _data: dict[str, Any]
    _last_response: ResponseInfo | None

    def __init__(
        self, data: Mapping[str, Any] | None = None, *, last_response: ResponseInfo | None = None
    ) -> None:
        object.__setattr__(self, "_data", _plain(data or {}))
        object.__setattr__(self, "_last_response", last_response)

    @classmethod
    def _from_wire(
        cls: type[M], data: dict[str, Any], last_response: ResponseInfo | None = None
    ) -> M:
        """Wrap a freshly decoded dict without copying (internal use only)."""
        obj = cls.__new__(cls)
        object.__setattr__(obj, "_data", data)
        object.__setattr__(obj, "_last_response", last_response)
        return obj

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError(f"{type(self).__name__} is immutable")

    def __delattr__(self, name: str) -> None:
        raise AttributeError(f"{type(self).__name__} is immutable")

    # -- Mapping protocol ------------------------------------------------------------------

    def __getitem__(self, key: str) -> Any:
        return _wrap(self._data[key])

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __contains__(self, key: object) -> bool:
        return key in self._data

    def __eq__(self, other: object) -> bool:
        if isinstance(other, NfeObject):
            return self._data == other._data
        if isinstance(other, Mapping):
            try:
                return bool(self._data == _plain(other))
            except TypeError:
                return False
        return NotImplemented

    __hash__ = None  # type: ignore[assignment]

    # -- extras ----------------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Deep copy of the wire JSON (plain dicts/lists, JSON-serialisable)."""
        return copy.deepcopy(self._data)

    @property
    def last_response(self) -> ResponseInfo | None:
        """Status, headers and ``request_id`` of the response this object came from."""
        return self._last_response

    def __repr__(self) -> str:
        body = json.dumps(_masked(self._data), ensure_ascii=False, default=str)
        return f"{type(self).__name__}({body})"

    def __copy__(self: M) -> M:
        return self

    def __deepcopy__(self: M, memo: dict[int, Any]) -> M:
        return type(self)._from_wire(copy.deepcopy(self._data, memo), self._last_response)

    def __reduce__(self) -> tuple[Any, ...]:
        return (_restore, (type(self), self._data))


def _restore(cls: type[M], data: dict[str, Any]) -> M:
    return cls._from_wire(data)


# --------------------------------------------------------------------------------------------
# Typed fields
# --------------------------------------------------------------------------------------------

Converter = Callable[[Any, Mapping[str, Any]], T | None]


class Field(Generic[T]):
    """Declarative read-only property bound to a wire key (with optional fallback keys)."""

    __slots__ = ("convert", "fallback_keys", "key", "name")

    def __init__(self, key: str, convert: Converter[T], *fallback_keys: str) -> None:
        self.key = key
        self.fallback_keys = fallback_keys
        self.convert = convert
        self.name = key

    def __set_name__(self, owner: type, name: str) -> None:
        self.name = name

    @property
    def wire_keys(self) -> tuple[str, ...]:
        return (self.key, *self.fallback_keys)

    @overload
    def __get__(self, obj: None, objtype: type | None = None) -> Field[T]: ...

    @overload
    def __get__(self, obj: NfeObject, objtype: type | None = None) -> T | None: ...

    def __get__(self, obj: NfeObject | None, objtype: type | None = None) -> Field[T] | T | None:
        if obj is None:
            return self
        data = obj._data
        for key in self.wire_keys:
            raw = data.get(key)
            if raw is not None:
                return self.convert(raw, data)
        return None

    def __set__(self, obj: NfeObject, value: Any) -> None:
        raise AttributeError(f"{self.name} is read-only")


def iter_fields(cls: type[NfeObject]) -> Iterator[tuple[str, Field[Any]]]:
    """Yield ``(attribute name, Field)`` for every typed property of a model class."""
    seen: set[str] = set()
    for klass in cls.__mro__:
        for name, value in vars(klass).items():
            if isinstance(value, Field) and name not in seen:
                seen.add(name)
                yield name, value


# -- converters --------------------------------------------------------------------------------


def to_str(raw: Any, _data: Mapping[str, Any] | None = None) -> str | None:
    if isinstance(raw, str):
        return raw
    if isinstance(raw, int) and not isinstance(raw, bool):
        return str(raw)
    return None


def to_decimal(raw: Any, _data: Mapping[str, Any] | None = None) -> Decimal | None:
    """``float`` → ``Decimal(repr(float))`` (recovers the JSON literal up to 15-17 digits)."""
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return Decimal(raw)
    if isinstance(raw, float):
        return Decimal(repr(raw)) if math.isfinite(raw) else None
    if isinstance(raw, str):
        try:
            value = Decimal(raw.strip())
        except InvalidOperation:
            return None
        return value if value.is_finite() else None
    return None


_DATETIME_RE = re.compile(
    r"^(?P<y>\d{4})-(?P<mo>\d{2})-(?P<d>\d{2})"
    r"(?:[T ](?P<h>\d{2}):(?P<mi>\d{2})(?::(?P<s>\d{2})(?:[.,](?P<f>\d{1,9}))?)?)?"
    r"\s*(?P<tz>Z|z|[+-]\d{2}(?::?\d{2})?)?$"
)


def parse_datetime(text: str) -> datetime | None:
    """Tolerant ISO 8601 parser: ``Z``, offsets, 0-9 fractional digits, date only.

    Values without an offset are interpreted as UTC. Returns ``None`` when unparseable.
    """
    match = _DATETIME_RE.fullmatch(text.strip())
    if not match:
        return None
    g = match.groupdict()
    frac = (g["f"] or "")[:6].ljust(6, "0")
    tz_text = g["tz"]
    tz: timezone
    if tz_text is None or tz_text in ("Z", "z"):
        tz = timezone.utc
    else:
        sign = -1 if tz_text[0] == "-" else 1
        digits = tz_text[1:].replace(":", "")
        hours = int(digits[:2])
        minutes = int(digits[2:4]) if len(digits) > 2 else 0
        if hours > 23 or minutes > 59:
            return None
        tz = timezone(sign * timedelta(hours=hours, minutes=minutes))
    try:
        return datetime(
            int(g["y"]),
            int(g["mo"]),
            int(g["d"]),
            int(g["h"] or 0),
            int(g["mi"] or 0),
            int(g["s"] or 0),
            int(frac),
            tzinfo=tz,
        )
    except ValueError:
        return None


def to_datetime(raw: Any, _data: Mapping[str, Any] | None = None) -> datetime | None:
    if isinstance(raw, str):
        return parse_datetime(raw)
    return None


def to_date(raw: Any, _data: Mapping[str, Any] | None = None) -> date | None:
    parsed = to_datetime(raw)
    return parsed.date() if parsed is not None else None


_DOC_CLEAN_RE = re.compile(r"[.\-/\s]")
_DOC_RE = re.compile(r"[0-9A-Z]+")


def normalize_document(raw: Any, kind: str, type_hint: Any = None) -> str | None:
    """Normalise a CNPJ/CPF that may arrive as int (leading zeros lost), masked or raw string.

    ``kind`` is ``"cnpj"``, ``"cpf"``, ``"cep"`` or ``"auto"``. For ``"auto"`` the sibling
    ``type`` field (``LegalEntity``/``NaturalPerson``) decides; without it, more than 11
    characters means CNPJ.
    """
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        if raw < 0:
            return None
        text = str(raw)
    elif isinstance(raw, str):
        text = _DOC_CLEAN_RE.sub("", raw).upper()
    else:
        return None
    if not text or not _DOC_RE.fullmatch(text):
        return None
    if kind == "auto":
        hint = type_hint.lower() if isinstance(type_hint, str) else ""
        if "legal" in hint or "company" in hint:
            kind = "cnpj"
        elif "natural" in hint or "person" in hint:
            kind = "cpf"
        else:
            kind = "cnpj" if len(text) > 11 else "cpf"
    size = _DOC_SIZES.get(kind, 0)
    return text.zfill(size) if len(text) <= size else text


_DOC_SIZES = {"cnpj": 14, "cpf": 11, "cep": 8}


def StrField(key: str, *fallback_keys: str) -> Field[str]:
    return Field(key, to_str, *fallback_keys)


def DecimalField(key: str, *fallback_keys: str) -> Field[Decimal]:
    return Field(key, to_decimal, *fallback_keys)


def DateTimeField(key: str, *fallback_keys: str) -> Field[datetime]:
    return Field(key, to_datetime, *fallback_keys)


def DocumentField(key: str, kind: str, type_key: str | None = None) -> Field[str]:
    def convert(raw: Any, data: Mapping[str, Any]) -> str | None:
        return normalize_document(raw, kind, data.get(type_key) if type_key else None)

    return Field(key, convert)


def StrListField(key: str) -> Field[list[str]]:
    def convert(raw: Any, _data: Mapping[str, Any]) -> list[str] | None:
        if not isinstance(raw, list):
            return None
        out: list[str] = []
        for item in raw:
            if isinstance(item, str):
                out.append(item)
            elif isinstance(item, dict) and isinstance(item.get("id"), str):
                out.append(item["id"])
        return out

    return Field(key, convert)


def ObjectField(key: str, cls: type[M]) -> Field[M]:
    def convert(raw: Any, _data: Mapping[str, Any]) -> M | None:
        return cls._from_wire(raw) if isinstance(raw, dict) else None

    return Field(key, convert)

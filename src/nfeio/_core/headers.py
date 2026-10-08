"""Case-insensitive, immutable HTTP header mapping."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping

#: Header names whose values are never shown in ``repr``.
SENSITIVE_HEADERS = frozenset(
    {"authorization", "proxy-authorization", "x-nfe-apikey", "apikey", "cookie", "set-cookie"}
)


class Headers(Mapping[str, str]):
    """Read-only header mapping with case-insensitive lookup.

    Repeated names are joined with ``", "`` (RFC 9110 §5.3). Iteration yields the names as first
    seen on the wire.
    """

    __slots__ = ("_store",)

    def __init__(self, items: Mapping[str, str] | Iterable[tuple[str, str]] | None = None) -> None:
        store: dict[str, tuple[str, str]] = {}
        pairs: Iterable[tuple[str, str]]
        if items is None:
            pairs = ()
        elif isinstance(items, Mapping):
            pairs = items.items()
        else:
            pairs = items
        for name, value in pairs:
            key = name.lower()
            if key in store:
                original, previous = store[key]
                store[key] = (original, f"{previous}, {value}")
            else:
                store[key] = (name, value)
        self._store = store

    def __getitem__(self, key: str) -> str:
        return self._store[key.lower()][1]

    def __contains__(self, key: object) -> bool:
        return isinstance(key, str) and key.lower() in self._store

    def __iter__(self) -> Iterator[str]:
        return (original for original, _ in self._store.values())

    def __len__(self) -> int:
        return len(self._store)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Mapping):
            return NotImplemented
        return {k.lower(): v for k, v in self.items()} == {
            str(k).lower(): v for k, v in other.items()
        }

    __hash__ = None  # type: ignore[assignment]

    def __repr__(self) -> str:
        shown = {
            name: ("<redacted>" if name.lower() in SENSITIVE_HEADERS else value)
            for name, value in self._store.values()
        }
        return f"Headers({shown!r})"

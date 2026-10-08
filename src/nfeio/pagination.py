"""Paginated results.

* :class:`OffsetPage` — API v1 lists (``pageIndex`` is **1-based**). The API sends no totals,
  so ``has_more`` is ``len(data) == page_count`` (at worst one extra request that comes back
  empty).
* :class:`CursorPage` — API v2 lists (``startingAfter``/``endingBefore``, ``hasMore``).

``auto_paging_iter()`` walks this page and the following ones lazily and always stops at an
empty page, even if the API says ``hasMore: true``. There is deliberately no "load everything"
helper. ``Async*`` variants are returned by :class:`~nfeio.AsyncNfeClient`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from ._core.ops import Op
from .models import NfeObject, ResponseInfo

__all__ = ["AsyncCursorPage", "AsyncOffsetPage", "CursorPage", "OffsetPage"]

T = TypeVar("T", bound=NfeObject)
S = TypeVar("S")

#: Maximum page size accepted by the API lists in v0.1.
MAX_PAGE_SIZE = 50


@dataclass(frozen=True)
class OffsetState(Generic[T]):
    items: list[T]
    last_response: ResponseInfo
    page_index: int
    page_count: int
    fetch: Callable[[int], Op[OffsetState[T]]]

    @property
    def has_more(self) -> bool:
        return len(self.items) > 0 and len(self.items) >= self.page_count


@dataclass(frozen=True)
class CursorState(Generic[T]):
    items: list[T]
    last_response: ResponseInfo
    has_more: bool
    limit: int
    backwards: bool
    fetch: Callable[[str | None, str | None, int], Op[CursorState[T]]]

    def next_op(self, limit: int) -> Op[CursorState[T]] | None:
        if not self.has_more or not self.items:
            return None
        if self.backwards:
            first = self.items[0].get("id")
            return self.fetch(None, first, limit) if isinstance(first, str) else None
        last = self.items[-1].get("id")
        return self.fetch(last, None, limit) if isinstance(last, str) else None


SyncRunner = Callable[[Op[Any]], Any]
AsyncRunner = Callable[[Op[Any]], Awaitable[Any]]


class _PageBase(Generic[T]):
    __slots__ = ("_runner", "_state")

    _state: OffsetState[T] | CursorState[T]
    _runner: Any

    @property
    def data(self) -> list[T]:
        """Items of this page (a new list on every access)."""
        return list(self._state.items)

    @property
    def has_more(self) -> bool:
        return self._state.has_more

    @property
    def last_response(self) -> ResponseInfo:
        return self._state.last_response

    def __len__(self) -> int:
        return len(self._state.items)

    def __iter__(self) -> Iterator[T]:
        """Iterate over **this page only**; use ``auto_paging_iter()`` for all pages."""
        return iter(list(self._state.items))

    def __repr__(self) -> str:
        return f"<{type(self).__name__} items={len(self)} has_more={self.has_more}>"


class OffsetPage(_PageBase[T]):
    """A page of an offset (``pageIndex``/``pageCount``) list."""

    __slots__ = ()
    _state: OffsetState[T]

    def __init__(self, state: OffsetState[T], runner: SyncRunner) -> None:
        self._state = state
        self._runner = runner

    @property
    def page_index(self) -> int:
        return self._state.page_index

    @property
    def page_count(self) -> int:
        return self._state.page_count

    def next_page(self) -> OffsetPage[T] | None:
        """Fetch the next page (same ``page_count``), or ``None`` if this one is the last."""
        if not self.has_more:
            return None
        state: OffsetState[T] = self._runner(self._state.fetch(self._state.page_index + 1))
        return OffsetPage(state, self._runner)

    def auto_paging_iter(self) -> Iterator[T]:
        """Yield every item of this page and the following ones, fetching lazily."""
        page: OffsetPage[T] | None = self
        while page is not None and len(page) > 0:
            yield from page._state.items
            page = page.next_page()


class AsyncOffsetPage(_PageBase[T]):
    """Async variant of :class:`OffsetPage`."""

    __slots__ = ()
    _state: OffsetState[T]

    def __init__(self, state: OffsetState[T], runner: AsyncRunner) -> None:
        self._state = state
        self._runner = runner

    @property
    def page_index(self) -> int:
        return self._state.page_index

    @property
    def page_count(self) -> int:
        return self._state.page_count

    async def next_page(self) -> AsyncOffsetPage[T] | None:
        if not self.has_more:
            return None
        state: OffsetState[T] = await self._runner(self._state.fetch(self._state.page_index + 1))
        return AsyncOffsetPage(state, self._runner)

    async def auto_paging_iter(self) -> AsyncIterator[T]:
        page: AsyncOffsetPage[T] | None = self
        while page is not None and len(page) > 0:
            for item in page._state.items:
                yield item
            page = await page.next_page()


class CursorPage(_PageBase[T]):
    """A page of a cursor (``startingAfter``/``endingBefore``) list."""

    __slots__ = ()
    _state: CursorState[T]

    def __init__(self, state: CursorState[T], runner: SyncRunner) -> None:
        self._state = state
        self._runner = runner

    @property
    def limit(self) -> int:
        return self._state.limit

    def next_page(self) -> CursorPage[T] | None:
        """Fetch the next page in the same direction (same ``limit``), or ``None``."""
        op = self._state.next_op(self._state.limit)
        if op is None:
            return None
        return CursorPage(self._runner(op), self._runner)

    def auto_paging_iter(self) -> Iterator[T]:
        """Yield every item, fetching following pages with ``limit=50``."""
        page: CursorPage[T] | None = self
        while page is not None and len(page) > 0:
            yield from page._state.items
            op = page._state.next_op(MAX_PAGE_SIZE)
            page = CursorPage(self._runner(op), self._runner) if op is not None else None


class AsyncCursorPage(_PageBase[T]):
    """Async variant of :class:`CursorPage`."""

    __slots__ = ()
    _state: CursorState[T]

    def __init__(self, state: CursorState[T], runner: AsyncRunner) -> None:
        self._state = state
        self._runner = runner

    @property
    def limit(self) -> int:
        return self._state.limit

    async def next_page(self) -> AsyncCursorPage[T] | None:
        op = self._state.next_op(self._state.limit)
        if op is None:
            return None
        return AsyncCursorPage(await self._runner(op), self._runner)

    async def auto_paging_iter(self) -> AsyncIterator[T]:
        page: AsyncCursorPage[T] | None = self
        while page is not None and len(page) > 0:
            for item in page._state.items:
                yield item
            op = page._state.next_op(MAX_PAGE_SIZE)
            page = AsyncCursorPage(await self._runner(op), self._runner) if op else None

"""Shared plumbing of resource services (sync and async facades over the same ops)."""

from __future__ import annotations

from typing import Any, Protocol, TypeVar

from .._config import ClientConfig
from .._core.ops import Op

T = TypeVar("T")


class SyncHost(Protocol):
    _config: ClientConfig

    def _run(self, op: Op[T]) -> T: ...


class AsyncHost(Protocol):
    _config: ClientConfig

    async def _run(self, op: Op[T]) -> T: ...


class SyncService:
    __slots__ = ("_host",)

    def __init__(self, host: SyncHost) -> None:
        self._host = host

    @property
    def _cfg(self) -> ClientConfig:
        return self._host._config

    def _run(self, op: Op[T]) -> T:
        return self._host._run(op)

    def _runner(self, op: Op[Any]) -> Any:
        return self._host._run(op)


class AsyncService:
    __slots__ = ("_host",)

    def __init__(self, host: AsyncHost) -> None:
        self._host = host

    @property
    def _cfg(self) -> ClientConfig:
        return self._host._config

    async def _run(self, op: Op[T]) -> T:
        return await self._host._run(op)

    async def _runner(self, op: Op[Any]) -> Any:
        return await self._host._run(op)

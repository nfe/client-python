"""Sans-IO operations.

Every SDK operation (retry, pagination, polling, redirects, ...) is written once as a generator
that *yields effects* and receives their results. Two drivers execute them: :func:`run_sync`
(blocking transport, ``time.sleep``) and :func:`run_async` (async transport,
``asyncio.sleep``). The sync and async clients therefore share every line of behaviour.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Generator
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, TypeVar, Union

from ..errors import APIConnectionError, FailurePhase, NfeError
from .transport import AsyncTransport, HttpRequest, Transport

T = TypeVar("T")


@dataclass(frozen=True)
class Send:
    """Send an HTTP request; the result is an :class:`HttpResponse` (or a raised NfeError)."""

    request: HttpRequest


@dataclass(frozen=True)
class Sleep:
    """Wait ``seconds``."""

    seconds: float


@dataclass(frozen=True)
class Now:
    """Read the monotonic clock (seconds, float)."""


@dataclass(frozen=True)
class UtcNow:
    """Read the wall clock as an aware UTC ``datetime`` (for HTTP dates)."""


Effect = Union[Send, Sleep, Now, UtcNow]  # noqa: UP007 - runtime alias on 3.10
Op = Generator[Effect, Any, T]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _wrap_os_error(exc: OSError) -> APIConnectionError:
    err = APIConnectionError(
        f"transport failed: {type(exc).__name__}", phase=FailurePhase.MAYBE_SENT
    )
    err.__cause__ = exc
    return err


def run_sync(
    op: Op[T],
    transport: Transport,
    *,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    utcnow: Callable[[], datetime] = _utcnow,
) -> T:
    """Drive ``op`` to completion with a blocking transport."""
    value: Any = None
    error: BaseException | None = None
    while True:
        try:
            effect = op.throw(error) if error is not None else op.send(value)
        except StopIteration as stop:
            return stop.value  # type: ignore[no-any-return]
        value, error = None, None
        if isinstance(effect, Send):
            try:
                value = transport.send(effect.request)
            except NfeError as exc:
                error = exc
            except OSError as exc:
                error = _wrap_os_error(exc)
        elif isinstance(effect, Sleep):
            if effect.seconds > 0:
                sleep(effect.seconds)
        elif isinstance(effect, Now):
            value = monotonic()
        elif isinstance(effect, UtcNow):
            value = utcnow()
        else:  # pragma: no cover - defensive
            raise TypeError(f"unknown effect {effect!r}")


async def run_async(
    op: Op[T],
    transport: AsyncTransport,
    *,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    utcnow: Callable[[], datetime] = _utcnow,
) -> T:
    """Drive ``op`` to completion with an async transport, never blocking the event loop."""
    value: Any = None
    error: BaseException | None = None
    while True:
        try:
            effect = op.throw(error) if error is not None else op.send(value)
        except StopIteration as stop:
            return stop.value  # type: ignore[no-any-return]
        value, error = None, None
        if isinstance(effect, Send):
            try:
                value = await transport.send(effect.request)
            except NfeError as exc:
                error = exc
            except OSError as exc:
                error = _wrap_os_error(exc)
        elif isinstance(effect, Sleep):
            if effect.seconds > 0:
                await sleep(effect.seconds)
        elif isinstance(effect, Now):
            value = monotonic()
        elif isinstance(effect, UtcNow):
            value = utcnow()
        else:  # pragma: no cover - defensive
            raise TypeError(f"unknown effect {effect!r}")

"""Handler transform capabilities."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Awaitable, Callable, ParamSpec, TypeVar

from combinators import lift as L
from combinators import timeout as comb_timeout

from ._base import HandlerTransform


P = ParamSpec("P")
T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class Timeout(HandlerTransform):
    """Add timeout to async handler at compile time.

    Usage:
        Timeout.seconds(30)
        Timeout.minutes(5)
        Timeout(timedelta(seconds=30))
    """

    duration: timedelta

    @classmethod
    def seconds(cls, n: float) -> Timeout:
        """Create timeout from seconds."""
        return cls(timedelta(seconds=n))

    @classmethod
    def minutes(cls, n: float) -> Timeout:
        """Create timeout from minutes."""
        return cls(timedelta(minutes=n))

    @classmethod
    def hours(cls, n: float) -> Timeout:
        """Create timeout from hours."""
        return cls(timedelta(hours=n))

    def apply_handler(
        self,
        handler: Callable[P, Awaitable[T]],
    ) -> Callable[P, Awaitable[T]]:
        """Wrap handler with timeout using combinators."""
        timeout_sec = self.duration.total_seconds()

        async def wrapped(*args: P.args, **kwargs: P.kwargs) -> T:
            async def call_handler() -> T:
                return await handler(*args, **kwargs)

            # catching_async wraps async fn, catches exceptions → Interp[T, Exception]
            interp = L.catching_async(call_handler, on_error=lambda e: e)
            with_timeout = comb_timeout(interp, seconds=timeout_sec)
            # unsafe re-raises the error if Error, returns value if Ok
            return await L.down.unsafe(with_timeout)

        return wrapped


__all__ = (
    "Timeout",
)

"""Counter pattern — atomic counter with typed backend.

Counter = Incr + Decr + IncrBy capabilities composed.

    counter_store = counter(redis_backend)

    # Increment
    new_value = await counter_store.incr("hits:page1")

    # Increment by amount
    new_value = await counter_store.incr_by("balance:user1", 100)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from kungfu import Result


from emergent.wire.axis.storage._capabilities import (
    Incr as IncrCap,
    Decr as DecrCap,
    IncrBy as IncrByCap,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Counter Backend — composition of capabilities
# ═══════════════════════════════════════════════════════════════════════════════


class CounterBackend[E](
    IncrCap[str, E],
    DecrCap[str, E],
    Protocol,
):
    """Backend with Counter capabilities. Incr + Decr."""

    ...


class CounterBackendFull[E](
    IncrCap[str, E],
    DecrCap[str, E],
    IncrByCap[str, E],
    Protocol,
):
    """Backend with full Counter capabilities. Incr + Decr + IncrBy."""

    ...


# ═══════════════════════════════════════════════════════════════════════════════
# Counter Store — typed wrapper
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Counter[E]:
    """Atomic counter store.

    All operations are atomic — safe for concurrent access.

    Example:
        counter_store = Counter(redis)

        # Page view counter
        views = await counter_store.incr("views:page1")
        print(f"Total views: {views.unwrap()}")

        # Decrement
        stock = await counter_store.decr("stock:item1")
    """

    backend: CounterBackend[E]

    async def incr(self, key: str) -> Result[int, E]:
        """Atomic increment by 1. Returns new value."""
        return await self.backend.incr(key)

    async def decr(self, key: str) -> Result[int, E]:
        """Atomic decrement by 1. Returns new value."""
        return await self.backend.decr(key)


@dataclass(frozen=True, slots=True)
class CounterFull[E]:
    """Atomic counter store with incr_by.

    Like Counter but also supports increment by arbitrary amount.
    """

    backend: CounterBackendFull[E]

    async def incr(self, key: str) -> Result[int, E]:
        """Atomic increment by 1. Returns new value."""
        return await self.backend.incr(key)

    async def decr(self, key: str) -> Result[int, E]:
        """Atomic decrement by 1. Returns new value."""
        return await self.backend.decr(key)

    async def incr_by(self, key: str, amount: int) -> Result[int, E]:
        """Atomic increment by amount. Returns new value.

        Use negative amount to decrement.
        """
        return await self.backend.incr_by(key, amount)

    async def decr_by(self, key: str, amount: int) -> Result[int, E]:
        """Atomic decrement by amount. Returns new value."""
        return await self.backend.incr_by(key, -amount)


def counter[E](backend: CounterBackend[E]) -> Counter[E]:
    """Create counter store from backend."""
    return Counter(backend)


def counter_full[E](backend: CounterBackendFull[E]) -> CounterFull[E]:
    """Create full counter store from backend."""
    return CounterFull(backend)


__all__ = (
    "CounterBackend",
    "CounterBackendFull",
    "Counter",
    "CounterFull",
    "counter",
    "counter_full",
)

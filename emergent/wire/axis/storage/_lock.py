"""Lock pattern — distributed lock with typed backend.

Lock = Acquire + Release + Extend capabilities composed.

    lock_store = lock(redis_backend)

    # Acquire with TTL
    acquired = await lock_store.acquire("resource:1", timedelta(seconds=30))

    # Context manager
    async with lock_store.hold("resource:1", timedelta(seconds=30)) as acquired:
        if acquired:
            # Do work while holding lock
            ...
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import timedelta
from typing import Protocol, AsyncIterator

from kungfu import Result


from emergent.wire.axis.storage._capabilities import (
    Acquire as AcquireCap,
    Release as ReleaseCap,
    Extend as ExtendCap,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Lock Backend — composition of capabilities
# ═══════════════════════════════════════════════════════════════════════════════


class LockBackend[E](
    AcquireCap[str, E],
    ReleaseCap[str, E],
    Protocol,
):
    """Backend with Lock capabilities. Acquire + Release."""

    ...


class LockBackendExtend[E](
    AcquireCap[str, E],
    ReleaseCap[str, E],
    ExtendCap[str, E],
    Protocol,
):
    """Backend with Lock + Extend capabilities."""

    ...


# ═══════════════════════════════════════════════════════════════════════════════
# Lock Store — typed wrapper
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Lock[E]:
    """Distributed lock store.

    Combines backend capabilities into convenient interface.

    Example:
        lock_store = Lock(redis)

        # Manual acquire/release
        if (await lock_store.acquire("job:1", timedelta(seconds=30))).unwrap():
            try:
                await do_work()
            finally:
                await lock_store.release("job:1")

        # Context manager (recommended)
        async with lock_store.hold("job:1", timedelta(seconds=30)) as acquired:
            if acquired:
                await do_work()
    """

    backend: LockBackend[E]

    async def acquire(self, key: str, ttl: timedelta) -> Result[bool, E]:
        """Acquire lock. Returns True if acquired, False if already held."""
        return await self.backend.acquire(key, ttl)

    async def release(self, key: str) -> Result[None, E]:
        """Release lock."""
        return await self.backend.release(key)

    @asynccontextmanager
    async def hold(
        self,
        key: str,
        ttl: timedelta,
    ) -> AsyncIterator[bool]:
        """Context manager for holding lock.

        Automatically releases on exit (even on exception).

        Args:
            key: Lock key
            ttl: Lock TTL (auto-release if holder crashes)

        Yields:
            True if lock was acquired, False otherwise

        Example:
            async with lock_store.hold("resource", timedelta(seconds=30)) as acquired:
                if acquired:
                    # Safe to proceed
                    await do_exclusive_work()
                else:
                    # Lock held by another process
                    raise ResourceBusy()
        """
        result = await self.acquire(key, ttl)
        acquired = result.unwrap_or(False)
        try:
            yield acquired
        finally:
            if acquired:
                await self.release(key)


@dataclass(frozen=True, slots=True)
class LockExtend[E]:
    """Distributed lock store with extend capability.

    Like Lock but also supports extending TTL while holding.
    """

    backend: LockBackendExtend[E]

    async def acquire(self, key: str, ttl: timedelta) -> Result[bool, E]:
        """Acquire lock. Returns True if acquired."""
        return await self.backend.acquire(key, ttl)

    async def release(self, key: str) -> Result[None, E]:
        """Release lock."""
        return await self.backend.release(key)

    async def extend(self, key: str, ttl: timedelta) -> Result[bool, E]:
        """Extend lock TTL. Returns True if extended (lock still held)."""
        return await self.backend.extend(key, ttl)

    @asynccontextmanager
    async def hold(
        self,
        key: str,
        ttl: timedelta,
    ) -> AsyncIterator[bool]:
        """Context manager for holding lock."""
        result = await self.acquire(key, ttl)
        acquired = result.unwrap_or(False)
        try:
            yield acquired
        finally:
            if acquired:
                await self.release(key)


def lock[E](backend: LockBackend[E]) -> Lock[E]:
    """Create lock store from backend."""
    return Lock(backend)


def lock_extend[E](backend: LockBackendExtend[E]) -> LockExtend[E]:
    """Create lock store with extend from backend."""
    return LockExtend(backend)


__all__ = (
    "LockBackend",
    "LockBackendExtend",
    "Lock",
    "LockExtend",
    "lock",
    "lock_extend",
)

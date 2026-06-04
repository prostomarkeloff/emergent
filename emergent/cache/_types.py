"""
Cache types.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from enum import Enum, auto
from typing import Protocol

from kungfu import Ok, Option, Some, Nothing

from emergent.wire.axis.storage import Delete, DeletePattern, Get, Set

type _LocalCacheMap[T] = dict[str, T]


# ═══════════════════════════════════════════════════════════════════════════════
# Tier Protocol — Users Implement This
# ═══════════════════════════════════════════════════════════════════════════════


class Tier[T, E](
    Get[str, T, E],
    Set[str, T, E],
    Delete[str, E],
    DeletePattern[E],
    Protocol,
):
    """Cache tier protocol — extends storage capabilities with name.

    Extends:
        Get[str, T, E]: get(key) -> Result[Option[T], E]
        Set[str, T, E]: set(key, value) -> Result[None, E]
        Delete[str, E]: delete(key) -> Result[None, E]
        DeletePattern[E]: delete_pattern(pattern) -> Result[int, E]

    Example:
        class RedisTier[T]:
            def __init__(self, client: Redis, ttl: int | None = None):
                self.client = client
                self.ttl = ttl

            @property
            def name(self) -> str:
                return "redis"

            async def get(self, key: str) -> Result[Option[T], RedisError]:
                try:
                    data = await self.client.get(key)
                    if data is None:
                        return Ok(Nothing())
                    return Ok(Some(pickle.loads(data)))
                except Exception as e:
                    return Error(RedisError(...))

            async def set(self, key: str, value: T) -> Result[None, RedisError]:
                try:
                    data = pickle.dumps(value)
                    await self.client.set(key, data, ex=self.ttl)
                    return Ok(None)
                except Exception as e:
                    return Error(RedisError(...))

            async def delete(self, key: str) -> Result[None, RedisError]:
                try:
                    await self.client.delete(key)
                    return Ok(None)
                except Exception as e:
                    return Error(RedisError(...))

            async def delete_pattern(self, pattern: str) -> Result[int, RedisError]:
                try:
                    keys = await self.client.keys(pattern)
                    if keys:
                        count = await self.client.delete(*keys)
                        return Ok(count)
                    return Ok(0)
                except Exception as e:
                    return Error(RedisError(...))
    """

    @property
    def name(self) -> str:
        """Tier name for debugging."""
        ...


# ═══════════════════════════════════════════════════════════════════════════════
# Local Tier — In-Memory LRU (Default)
# ═══════════════════════════════════════════════════════════════════════════════


class LocalTier[T]:
    """In-memory LRU cache tier with eviction.

    Unlike MemoryStorage, this has:
    - LRU eviction (max_size)
    - name property for tier identification

    Example:
        tier = LocalTier[User](max_size=1000)
    """

    def __init__(self, max_size: int = 1000) -> None:
        self._max_size = max_size
        self._cache: _LocalCacheMap[T] = {}
        self._order: list[str] = []

    @property
    def name(self) -> str:
        return "local"

    async def get(self, key: str) -> Ok[Option[T]]:
        if key in self._cache:
            # Move to end (most recent)
            self._order.remove(key)
            self._order.append(key)
            return Ok(Some(self._cache[key]))
        return Ok(Nothing())

    async def set(self, key: str, value: T) -> Ok[None]:
        if key in self._cache:
            self._order.remove(key)
        elif len(self._cache) >= self._max_size:
            # Evict oldest
            oldest = self._order.pop(0)
            del self._cache[oldest]

        self._cache[key] = value
        self._order.append(key)
        return Ok(None)

    async def delete(self, key: str) -> Ok[None]:
        if key in self._cache:
            del self._cache[key]
            self._order.remove(key)
        return Ok(None)

    async def delete_pattern(self, pattern: str) -> Ok[int]:
        import fnmatch

        keys_to_delete = [k for k in self._cache if fnmatch.fnmatch(k, pattern)]
        for key in keys_to_delete:
            del self._cache[key]
            self._order.remove(key)
        return Ok(len(keys_to_delete))


# ═══════════════════════════════════════════════════════════════════════════════
# Cache Result
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class CacheResult[T]:
    """Cache operation result with metadata."""

    value: T
    hit: bool
    tier: str | None
    ttl_remaining: timedelta | None


class CacheErrorKind(Enum):
    """Cache error kinds."""

    MISS = auto()
    CONNECTION = auto()
    SERIALIZATION = auto()
    TIMEOUT = auto()
    NO_FETCH = auto()


@dataclass(frozen=True, slots=True)
class CacheError:
    """Cache operation error."""

    kind: CacheErrorKind
    message: str


# ═══════════════════════════════════════════════════════════════════════════════
# Exports
# ═══════════════════════════════════════════════════════════════════════════════

__all__ = (
    "Tier",
    "LocalTier",
    "CacheResult",
    "CacheError",
    "CacheErrorKind",
)

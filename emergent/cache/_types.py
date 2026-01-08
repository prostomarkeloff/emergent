"""
Cache types.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from enum import Enum, auto
from typing import Protocol

# ═══════════════════════════════════════════════════════════════════════════════
# Tier Protocol — Users Implement This
# ═══════════════════════════════════════════════════════════════════════════════

class Tier[T](Protocol):
    """
    Cache tier protocol.

    Implement this for custom backends (Redis, Memcached, etc.)

    Example:
        class RedisTier[T]:
            def __init__(self, client: Redis, ttl: int | None = None):
                self.client = client
                self.ttl = ttl

            @property
            def name(self) -> str:
                return "redis"

            async def get(self, key: str) -> T | None:
                data = await self.client.get(key)
                return pickle.loads(data) if data else None

            async def set(self, key: str, value: T) -> None:
                data = pickle.dumps(value)
                await self.client.set(key, data, ex=self.ttl)

            async def delete(self, key: str) -> bool:
                return await self.client.delete(key) > 0

            async def delete_pattern(self, pattern: str) -> int:
                keys = await self.client.keys(pattern)
                if keys:
                    return await self.client.delete(*keys)
                return 0
    """

    @property
    def name(self) -> str:
        """Tier name for debugging."""
        ...

    async def get(self, key: str) -> T | None:
        """Get value. Returns None on miss."""
        ...

    async def set(self, key: str, value: T) -> None:
        """Set value."""
        ...

    async def delete(self, key: str) -> bool:
        """Delete key. Returns True if existed."""
        ...

    async def delete_pattern(self, pattern: str) -> int:
        """Delete keys matching pattern. Returns count."""
        ...


# ═══════════════════════════════════════════════════════════════════════════════
# Local Tier — In-Memory LRU (Default)
# ═══════════════════════════════════════════════════════════════════════════════

class LocalTier[T]:
    """
    In-memory LRU cache tier.

    Example:
        tier = LocalTier[User](max_size=1000)
    """

    def __init__(self, max_size: int = 1000) -> None:
        self._max_size = max_size
        self._cache: dict[str, T] = {}
        self._order: list[str] = []

    @property
    def name(self) -> str:
        return "local"

    async def get(self, key: str) -> T | None:
        if key in self._cache:
            # Move to end (most recent)
            self._order.remove(key)
            self._order.append(key)
            return self._cache[key]
        return None

    async def set(self, key: str, value: T) -> None:
        if key in self._cache:
            self._order.remove(key)
        elif len(self._cache) >= self._max_size:
            # Evict oldest
            oldest = self._order.pop(0)
            del self._cache[oldest]

        self._cache[key] = value
        self._order.append(key)

    async def delete(self, key: str) -> bool:
        if key in self._cache:
            del self._cache[key]
            self._order.remove(key)
            return True
        return False

    async def delete_pattern(self, pattern: str) -> int:
        import fnmatch
        keys_to_delete = [k for k in self._cache if fnmatch.fnmatch(k, pattern)]
        for key in keys_to_delete:
            del self._cache[key]
            self._order.remove(key)
        return len(keys_to_delete)


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

"""
Cache builder — fluent API.
"""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable
from kungfu import LazyCoroResult, Result, Ok, Error, Some
from emergent.cache._types import (
    Tier,
    CacheResult,
    CacheError,
)

# Type alias for tier with any error type
type AnyTier[T] = Tier[T, object]

# ═══════════════════════════════════════════════════════════════════════════════
# Key Function Type
# ═══════════════════════════════════════════════════════════════════════════════

type KeyFn[K] = Callable[[K], str]


# ═══════════════════════════════════════════════════════════════════════════════
# Cache Builder
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(slots=True, frozen=True)
class Cache[K, T, E]:
    """Fluent cache builder.

    Type parameters:
        K: Key input type
        T: Value type
        E: Error type from fetch

    Example:
        user_cache = (
            C.cache(make_key, fetch_user)
            .tier(local)
            .build()
        )
    """

    _key_fn: KeyFn[K]
    _fetch: Callable[[K], LazyCoroResult[T, E]]
    _tiers: tuple[AnyTier[T], ...]

    def tier(self, t: AnyTier[T]) -> Cache[K, T, E]:
        """Add cache tier."""
        return Cache(
            _key_fn=self._key_fn,
            _fetch=self._fetch,
            _tiers=(*self._tiers, t),
        )

    def build(self) -> CacheExecutor[K, T, E]:
        """Build executable cache."""
        return CacheExecutor(
            key_fn=self._key_fn,
            tiers=self._tiers,
            fetch=self._fetch,
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Cache Executor
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(slots=True, frozen=True)
class CacheExecutor[K, T, E]:
    """Compiled cache executor."""

    key_fn: KeyFn[K]
    tiers: tuple[AnyTier[T], ...]
    fetch: Callable[[K], LazyCoroResult[T, E]]

    def get(self, key: K) -> LazyCoroResult[CacheResult[T], CacheError | E]:
        """Get value from cache.

        Tries tiers in order, then falls back to fetch.
        On fetch success, populates all tiers.
        """
        cache_key = self.key_fn(key)
        tiers = self.tiers
        fetch_fn = self.fetch

        async def execute() -> Result[CacheResult[T], CacheError | E]:
            # Try each tier
            for t in tiers:
                match await t.get(cache_key):
                    case Ok(Some(value)):
                        return Ok(
                            CacheResult(
                                value=value,
                                hit=True,
                                tier=t.name,
                                ttl_remaining=None,
                            )
                        )
                    case _:
                        continue  # Miss or error — try next tier

            # Cache miss — fetch from source
            match await fetch_fn(key):
                case Ok(value):
                    # Populate all tiers (best effort)
                    for t in tiers:
                        await t.set(cache_key, value)

                    return Ok(
                        CacheResult(
                            value=value,
                            hit=False,
                            tier=None,
                            ttl_remaining=None,
                        )
                    )
                case Error(e):
                    return Error(e)

        return LazyCoroResult(execute)

    async def invalidate(self, key: K) -> Result[None, CacheError]:
        """Invalidate key in all tiers."""
        cache_key = self.key_fn(key)
        for t in self.tiers:
            await t.delete(cache_key)
        return Ok(None)

    async def invalidate_pattern(self, pattern: str) -> Result[int, CacheError]:
        """Invalidate keys matching pattern in all tiers."""
        total = 0
        for t in self.tiers:
            match await t.delete_pattern(pattern):
                case Ok(count):
                    total += count
                case Error(_):
                    pass  # Best effort
        return Ok(total)


# ═══════════════════════════════════════════════════════════════════════════════
# cache() — Entry Point (Type-Safe)
# ═══════════════════════════════════════════════════════════════════════════════


def cache[K, T, E](
    key: KeyFn[K],
    fetch: Callable[[K], LazyCoroResult[T, E]],
) -> Cache[K, T, E]:
    """
    Create cache builder with key function and fetch.

    Types are inferred from arguments — no manual annotation needed.

    Example:
        from emergent import cache as C

        def make_key(uid: UserId) -> str:
            return f"user:{uid.value}"

        def fetch_user(uid: UserId) -> LazyCoroResult[User, NotFoundError]:
            return L.catching_async(...)

        user_cache = (
            C.cache(make_key, fetch_user)
            .tier(C.LocalTier(max_size=100))
            .build()
        )

        result = await user_cache.get(user_id)
    """
    return Cache(
        _key_fn=key,
        _fetch=fetch,
        _tiers=(),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Exports
# ═══════════════════════════════════════════════════════════════════════════════

__all__ = ("Cache", "CacheExecutor", "cache")

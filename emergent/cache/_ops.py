"""
Cache operations — standalone utilities.
"""

from __future__ import annotations

from kungfu import LazyCoroResult, Result, Ok, Error
from emergent.cache._types import Tier, CacheError

# ═══════════════════════════════════════════════════════════════════════════════
# invalidate() — Single Key in Tier
# ═══════════════════════════════════════════════════════════════════════════════


def invalidate[T, E](t: Tier[T, E], key: str) -> LazyCoroResult[None, CacheError | E]:
    """Invalidate single cache key in tier.

    Example:
        result = await C.invalidate(local_tier, f"user:{uid}")
    """

    async def do_invalidate() -> Result[None, CacheError | E]:
        result = await t.delete(key)
        match result:
            case Ok(_):
                return Ok(None)
            case Error(e):
                return Error(e)

    return LazyCoroResult(do_invalidate)


# ═══════════════════════════════════════════════════════════════════════════════
# invalidate_pattern() — Pattern Match in Tier
# ═══════════════════════════════════════════════════════════════════════════════


def invalidate_pattern[T, E](t: Tier[T, E], pattern: str) -> LazyCoroResult[int, CacheError | E]:
    """Invalidate all keys matching pattern in tier.

    Example:
        count = await C.invalidate_pattern(local_tier, "user:*")

    Returns:
        Number of keys invalidated
    """

    async def do_invalidate() -> Result[int, CacheError | E]:
        result = await t.delete_pattern(pattern)
        match result:
            case Ok(count):
                return Ok(count)
            case Error(e):
                return Error(e)

    return LazyCoroResult(do_invalidate)


# ═══════════════════════════════════════════════════════════════════════════════
# Exports
# ═══════════════════════════════════════════════════════════════════════════════

__all__ = ("invalidate", "invalidate_pattern")

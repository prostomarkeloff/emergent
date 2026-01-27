"""
Cache operations — standalone utilities.
"""

from __future__ import annotations

from kungfu import LazyCoroResult
from combinators import lift as L
from emergent.cache._types import Tier, CacheError, CacheErrorKind

# ═══════════════════════════════════════════════════════════════════════════════
# invalidate() — Single Key in Tier
# ═══════════════════════════════════════════════════════════════════════════════


def invalidate[T](t: Tier[T], key: str) -> LazyCoroResult[bool, CacheError]:
    """
    Invalidate single cache key in tier.

    Example:
        result = await C.invalidate(local_tier, f"user:{uid}")
    """

    async def do_invalidate() -> bool:
        return await t.delete(key)

    return L.catching_async(
        do_invalidate,
        on_error=lambda e: CacheError(CacheErrorKind.CONNECTION, str(e)),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# invalidate_pattern() — Pattern Match in Tier
# ═══════════════════════════════════════════════════════════════════════════════


def invalidate_pattern[T](t: Tier[T], pattern: str) -> LazyCoroResult[int, CacheError]:
    """
    Invalidate all keys matching pattern in tier.

    Example:
        count = await C.invalidate_pattern(local_tier, "user:*")

    Returns:
        Number of keys invalidated
    """

    async def do_invalidate() -> int:
        return await t.delete_pattern(pattern)

    return L.catching_async(
        do_invalidate,
        on_error=lambda e: CacheError(CacheErrorKind.CONNECTION, str(e)),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Exports
# ═══════════════════════════════════════════════════════════════════════════════

__all__ = ("invalidate", "invalidate_pattern")

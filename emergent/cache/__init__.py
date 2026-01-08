"""
Cache — multi-tier caching.

    from emergent import cache as C

    user_cache = C.cache(key_fn, fetch_fn).tier(C.LocalTier(max_size=100)).build()
    result = await user_cache.get(user_id)
"""

from __future__ import annotations

from emergent.cache._types import (
    Tier,
    LocalTier,
    CacheResult,
    CacheError,
    CacheErrorKind,
)
from emergent.cache._builder import cache, Cache, CacheExecutor
from emergent.cache._ops import invalidate, invalidate_pattern

__all__ = (
    "Tier",
    "LocalTier",
    "CacheResult",
    "CacheError",
    "CacheErrorKind",
    "cache",
    "Cache",
    "CacheExecutor",
    "invalidate",
    "invalidate_pattern",
)

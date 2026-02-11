"""KV composition helpers — pure wrappers for common patterns.

    from emergent.wire.axis.storage import prefix_kv, tiered_kv, fallback_kv

    # Auto-prefix all keys
    users = prefix_kv(kv_store, "users:")

    # Cache-aside: L1 (fast) → L2 (slow)
    cached = tiered_kv(memory_kv, redis_kv)

    # Fallback on error
    resilient = fallback_kv(primary_kv, backup_kv)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING

from kungfu import Result, Ok, Error, Option, Some, Nothing

if TYPE_CHECKING:
    from emergent.wire.axis.storage._kv import KV


# ═══════════════════════════════════════════════════════════════════════════════
# Prefix KV — auto-prepend prefix to all keys
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class PrefixKV[T, E]:
    """KV wrapper that auto-prepends prefix to all keys.

    Example:
        users = PrefixKV(redis_kv, "users:")
        await users.set("alice", user)  # Actually sets "users:alice"
        await users.get("alice")        # Actually gets "users:alice"
    """

    inner: KV[T, E]
    prefix: str

    async def get(self, key: str) -> Result[Option[T], E]:
        """Get with prefixed key."""
        return await self.inner.get(self.prefix + key)

    async def set(self, key: str, value: T, ttl: timedelta | None = None) -> Result[None, E]:
        """Set with prefixed key."""
        return await self.inner.set(self.prefix + key, value, ttl)

    async def delete(self, key: str) -> Result[None, E]:
        """Delete with prefixed key."""
        return await self.inner.delete(self.prefix + key)


def prefix_kv[T, E](inner: KV[T, E], prefix: str) -> PrefixKV[T, E]:
    """Create KV with auto-prefixed keys.

    Args:
        inner: Underlying KV store
        prefix: Prefix to prepend to all keys

    Example:
        users = prefix_kv(redis, "users:")
        sessions = prefix_kv(redis, "sessions:")
    """
    return PrefixKV(inner, prefix)


# ═══════════════════════════════════════════════════════════════════════════════
# Tiered KV — cache-aside pattern (L1 → L2)
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class TieredKV[T, E]:
    """Two-tier KV with cache-aside pattern.

    Read: Check L1 → miss → check L2 → populate L1
    Write: Write to both L1 and L2

    Example:
        cached = TieredKV(memory_kv, redis_kv)
        # First read: miss L1, hit L2, populate L1
        # Second read: hit L1 (fast)
    """

    l1: KV[T, E]  # Fast tier (memory)
    l2: KV[T, E]  # Slow tier (disk/network)
    l1_ttl: timedelta | None = None  # TTL for L1 cache

    async def get(self, key: str) -> Result[Option[T], E]:
        """Get with cache-aside: L1 → L2 → populate L1."""
        # Try L1 first
        match await self.l1.get(key):
            case Ok(Some(value)):
                return Ok(Some(value))
            case Error(e):
                return Error(e)
            case _:
                pass  # L1 miss (Nothing), continue to L2

        # Try L2
        match await self.l2.get(key):
            case Ok(Some(value)):
                # Populate L1 cache
                await self.l1.set(key, value, self.l1_ttl)
                return Ok(Some(value))
            case result:
                return result

    async def set(self, key: str, value: T, ttl: timedelta | None = None) -> Result[None, E]:
        """Set to both tiers."""
        # Write to L2 first (authoritative)
        match await self.l2.set(key, value, ttl):
            case Error(e):
                return Error(e)
            case _:
                pass

        # Write to L1 (cache)
        l1_ttl = self.l1_ttl if ttl is None else min(ttl, self.l1_ttl) if self.l1_ttl else ttl
        return await self.l1.set(key, value, l1_ttl)

    async def delete(self, key: str) -> Result[None, E]:
        """Delete from both tiers."""
        # Delete from L1 first
        await self.l1.delete(key)
        # Delete from L2
        return await self.l2.delete(key)


def tiered_kv[T, E](
    l1: KV[T, E],
    l2: KV[T, E],
    l1_ttl: timedelta | None = None,
) -> TieredKV[T, E]:
    """Create two-tier KV with cache-aside pattern.

    Args:
        l1: Fast tier (memory cache)
        l2: Slow tier (persistent storage)
        l1_ttl: TTL for L1 cache entries

    Example:
        cached = tiered_kv(memory, redis, l1_ttl=timedelta(minutes=5))
    """
    return TieredKV(l1, l2, l1_ttl)


# ═══════════════════════════════════════════════════════════════════════════════
# Fallback KV — try primary, use secondary on error
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class FallbackKV[T, E]:
    """KV with fallback on error.

    Example:
        resilient = FallbackKV(primary_redis, backup_redis)
        # If primary fails, automatically tries backup
    """

    primary: KV[T, E]
    secondary: KV[T, E]

    async def get(self, key: str) -> Result[Option[T], E]:
        """Get from primary, fallback to secondary on error."""
        match await self.primary.get(key):
            case Ok(option):
                return Ok(option)
            case Error(_):
                return await self.secondary.get(key)

    async def set(self, key: str, value: T, ttl: timedelta | None = None) -> Result[None, E]:
        """Set to primary, fallback to secondary on error."""
        match await self.primary.set(key, value, ttl):
            case Ok(v):
                return Ok(v)
            case Error(_):
                return await self.secondary.set(key, value, ttl)

    async def delete(self, key: str) -> Result[None, E]:
        """Delete from primary, fallback to secondary on error."""
        match await self.primary.delete(key):
            case Ok(v):
                return Ok(v)
            case Error(_):
                return await self.secondary.delete(key)


def fallback_kv[T, E](primary: KV[T, E], secondary: KV[T, E]) -> FallbackKV[T, E]:
    """Create KV with fallback on error.

    Args:
        primary: Primary KV store
        secondary: Fallback KV store (used on primary error)

    Example:
        resilient = fallback_kv(primary_redis, backup_redis)
    """
    return FallbackKV(primary, secondary)


# ═══════════════════════════════════════════════════════════════════════════════
# Readonly KV — disable writes for safety
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class ReadonlyKV[T, E]:
    """Read-only KV wrapper.

    Disables set/delete operations for safety.

    Example:
        readonly = ReadonlyKV(production_kv)
        await readonly.get("key")  # OK
        await readonly.set("key", value)  # Returns Nothing
    """

    inner: KV[T, E]

    async def get(self, key: str) -> Result[Option[T], E]:
        """Get is allowed."""
        return await self.inner.get(key)

    async def set(
        self, key: str, value: T, ttl: timedelta | None = None
    ) -> Result[Option[None], E]:
        """Set is disabled — returns Nothing."""
        return Ok(Nothing())

    async def delete(self, key: str) -> Result[Option[None], E]:
        """Delete is disabled — returns Nothing."""
        return Ok(Nothing())


def readonly_kv[T, E](inner: KV[T, E]) -> ReadonlyKV[T, E]:
    """Create read-only KV wrapper.

    Args:
        inner: Underlying KV store

    Example:
        safe = readonly_kv(production_kv)
    """
    return ReadonlyKV(inner)


__all__ = (
    "PrefixKV",
    "TieredKV",
    "FallbackKV",
    "ReadonlyKV",
    "prefix_kv",
    "tiered_kv",
    "fallback_kv",
    "readonly_kv",
)

"""Tests for emergent.cache._types.

Covers:
    - LocalTier: get, set, delete, delete_pattern, LRU eviction, name property
    - CacheResult: creation, frozen behavior
    - CacheError: creation, frozen behavior
    - CacheErrorKind: all enum values
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from kungfu import Ok, Some, Nothing

from emergent.cache._types import (
    LocalTier,
    CacheResult,
    CacheError,
    CacheErrorKind,
)


# ═══════════════════════════════════════════════════════════════════════════════
# LocalTier — Basic Operations
# ═══════════════════════════════════════════════════════════════════════════════


class TestLocalTierBasicOps:
    @pytest.mark.asyncio
    async def test_name(self) -> None:
        tier = LocalTier[str]()
        assert tier.name == "local"

    @pytest.mark.asyncio
    async def test_get_missing_key(self) -> None:
        tier = LocalTier[str]()
        result = await tier.get("nonexistent")
        assert result == Ok(Nothing())

    @pytest.mark.asyncio
    async def test_set_and_get(self) -> None:
        tier = LocalTier[str]()
        await tier.set("key1", "value1")
        result = await tier.get("key1")
        assert result == Ok(Some("value1"))

    @pytest.mark.asyncio
    async def test_set_overwrites(self) -> None:
        tier = LocalTier[str]()
        await tier.set("key1", "old")
        await tier.set("key1", "new")
        result = await tier.get("key1")
        assert result == Ok(Some("new"))

    @pytest.mark.asyncio
    async def test_delete_existing_key(self) -> None:
        tier = LocalTier[str]()
        await tier.set("key1", "value1")
        result = await tier.delete("key1")
        assert result == Ok(None)

        get_result = await tier.get("key1")
        assert get_result == Ok(Nothing())

    @pytest.mark.asyncio
    async def test_delete_missing_key(self) -> None:
        tier = LocalTier[str]()
        result = await tier.delete("nonexistent")
        assert result == Ok(None)

    @pytest.mark.asyncio
    async def test_set_returns_ok_none(self) -> None:
        tier = LocalTier[str]()
        result = await tier.set("k", "v")
        assert result == Ok(None)

    @pytest.mark.asyncio
    async def test_delete_returns_ok_none(self) -> None:
        tier = LocalTier[str]()
        result = await tier.delete("k")
        assert result == Ok(None)


# ═══════════════════════════════════════════════════════════════════════════════
# LocalTier — Delete Pattern
# ═══════════════════════════════════════════════════════════════════════════════


class TestLocalTierDeletePattern:
    @pytest.mark.asyncio
    async def test_delete_pattern_matching(self) -> None:
        tier = LocalTier[str]()
        await tier.set("user:1", "alice")
        await tier.set("user:2", "bob")
        await tier.set("order:1", "pizza")

        result = await tier.delete_pattern("user:*")
        assert result == Ok(2)

        # Verify users deleted
        assert await tier.get("user:1") == Ok(Nothing())
        assert await tier.get("user:2") == Ok(Nothing())
        # Verify order still exists
        assert await tier.get("order:1") == Ok(Some("pizza"))

    @pytest.mark.asyncio
    async def test_delete_pattern_no_matches(self) -> None:
        tier = LocalTier[str]()
        await tier.set("key1", "v1")
        result = await tier.delete_pattern("nonexistent:*")
        assert result == Ok(0)

    @pytest.mark.asyncio
    async def test_delete_pattern_all(self) -> None:
        tier = LocalTier[str]()
        await tier.set("a", "1")
        await tier.set("b", "2")
        result = await tier.delete_pattern("*")
        assert result == Ok(2)


# ═══════════════════════════════════════════════════════════════════════════════
# LocalTier — LRU Eviction
# ═══════════════════════════════════════════════════════════════════════════════


class TestLocalTierLRU:
    @pytest.mark.asyncio
    async def test_evicts_oldest_when_full(self) -> None:
        tier = LocalTier[str](max_size=3)
        await tier.set("a", "1")
        await tier.set("b", "2")
        await tier.set("c", "3")

        # Adding 4th should evict "a" (oldest)
        await tier.set("d", "4")

        assert await tier.get("a") == Ok(Nothing())
        assert await tier.get("b") == Ok(Some("2"))
        assert await tier.get("c") == Ok(Some("3"))
        assert await tier.get("d") == Ok(Some("4"))

    @pytest.mark.asyncio
    async def test_get_refreshes_lru_order(self) -> None:
        tier = LocalTier[str](max_size=3)
        await tier.set("a", "1")
        await tier.set("b", "2")
        await tier.set("c", "3")

        # Access "a" to make it most recently used
        await tier.get("a")

        # Adding "d" should now evict "b" (oldest unused)
        await tier.set("d", "4")

        assert await tier.get("a") == Ok(Some("1"))
        assert await tier.get("b") == Ok(Nothing())
        assert await tier.get("c") == Ok(Some("3"))
        assert await tier.get("d") == Ok(Some("4"))

    @pytest.mark.asyncio
    async def test_set_existing_does_not_increase_size(self) -> None:
        tier = LocalTier[str](max_size=3)
        await tier.set("a", "1")
        await tier.set("b", "2")
        await tier.set("c", "3")

        # Overwriting "a" should not evict anything
        await tier.set("a", "updated")

        assert await tier.get("a") == Ok(Some("updated"))
        assert await tier.get("b") == Ok(Some("2"))
        assert await tier.get("c") == Ok(Some("3"))

    @pytest.mark.asyncio
    async def test_max_size_1(self) -> None:
        tier = LocalTier[str](max_size=1)
        await tier.set("a", "1")
        await tier.set("b", "2")

        assert await tier.get("a") == Ok(Nothing())
        assert await tier.get("b") == Ok(Some("2"))

    @pytest.mark.asyncio
    async def test_default_max_size_is_1000(self) -> None:
        tier = LocalTier[str]()
        # Access protected attribute via getattr to verify default without pyright complaint
        assert getattr(tier, "_max_size") == 1000


# ═══════════════════════════════════════════════════════════════════════════════
# CacheResult
# ═══════════════════════════════════════════════════════════════════════════════


class TestCacheResult:
    def test_creation_hit(self) -> None:
        result = CacheResult[str](
            value="cached",
            hit=True,
            tier="local",
            ttl_remaining=timedelta(seconds=30),
        )
        assert result.value == "cached"
        assert result.hit is True
        assert result.tier == "local"
        assert result.ttl_remaining == timedelta(seconds=30)

    def test_creation_miss(self) -> None:
        result = CacheResult[int](
            value=42,
            hit=False,
            tier=None,
            ttl_remaining=None,
        )
        assert result.value == 42
        assert result.hit is False
        assert result.tier is None
        assert result.ttl_remaining is None

    def test_frozen(self) -> None:
        result = CacheResult[str](
            value="v", hit=True, tier="local", ttl_remaining=None
        )
        with pytest.raises(AttributeError):
            result.value = "new"  # type: ignore[misc]


# ═══════════════════════════════════════════════════════════════════════════════
# CacheErrorKind
# ═══════════════════════════════════════════════════════════════════════════════


class TestCacheErrorKind:
    def test_all_kinds_exist(self) -> None:
        assert CacheErrorKind.MISS is not None
        assert CacheErrorKind.CONNECTION is not None
        assert CacheErrorKind.SERIALIZATION is not None
        assert CacheErrorKind.TIMEOUT is not None
        assert CacheErrorKind.NO_FETCH is not None

    def test_all_kinds_distinct(self) -> None:
        kinds = [
            CacheErrorKind.MISS,
            CacheErrorKind.CONNECTION,
            CacheErrorKind.SERIALIZATION,
            CacheErrorKind.TIMEOUT,
            CacheErrorKind.NO_FETCH,
        ]
        assert len(set(kinds)) == 5


# ═══════════════════════════════════════════════════════════════════════════════
# CacheError
# ═══════════════════════════════════════════════════════════════════════════════


class TestCacheError:
    def test_creation(self) -> None:
        err = CacheError(kind=CacheErrorKind.MISS, message="key not found")
        assert err.kind == CacheErrorKind.MISS
        assert err.message == "key not found"

    def test_connection_error(self) -> None:
        err = CacheError(kind=CacheErrorKind.CONNECTION, message="redis down")
        assert err.kind == CacheErrorKind.CONNECTION

    def test_frozen(self) -> None:
        err = CacheError(kind=CacheErrorKind.MISS, message="m")
        with pytest.raises(AttributeError):
            err.message = "changed"  # type: ignore[misc]

    def test_serialization_error(self) -> None:
        err = CacheError(
            kind=CacheErrorKind.SERIALIZATION, message="cannot pickle"
        )
        assert err.kind == CacheErrorKind.SERIALIZATION
        assert err.message == "cannot pickle"

    def test_timeout_error(self) -> None:
        err = CacheError(kind=CacheErrorKind.TIMEOUT, message="3s exceeded")
        assert err.kind == CacheErrorKind.TIMEOUT

    def test_no_fetch_error(self) -> None:
        err = CacheError(kind=CacheErrorKind.NO_FETCH, message="no fetch fn")
        assert err.kind == CacheErrorKind.NO_FETCH

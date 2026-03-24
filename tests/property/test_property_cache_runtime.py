# pyright: reportPrivateUsage=false
"""Property-based tests for cache hit/miss/eviction — LocalTier and CacheExecutor."""

from __future__ import annotations

import pytest
from kungfu import Ok, Some, Nothing, Result, LazyCoroResult

from emergent.cache._types import LocalTier, CacheResult
from emergent.cache._builder import cache, CacheExecutor


# ═══════════════════════════════════════════════════════════════════════════════
# LocalTier Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestLocalTierSetThenGet:
    """LocalTier: set then get returns value."""

    @pytest.mark.asyncio
    async def test_set_then_get(self) -> None:
        tier: LocalTier[int] = LocalTier(max_size=100)
        await tier.set("key1", 42)

        result = await tier.get("key1")
        assert isinstance(result, Ok)
        assert isinstance(result.value, Some)
        assert result.value.value == 42

    @pytest.mark.asyncio
    async def test_set_multiple_keys(self) -> None:
        tier: LocalTier[str] = LocalTier(max_size=100)
        await tier.set("a", "alpha")
        await tier.set("b", "beta")
        await tier.set("c", "gamma")

        for key, expected in [("a", "alpha"), ("b", "beta"), ("c", "gamma")]:
            result = await tier.get(key)
            assert isinstance(result, Ok)
            assert isinstance(result.value, Some)
            assert result.value.value == expected

    @pytest.mark.asyncio
    async def test_set_overwrites_existing(self) -> None:
        tier: LocalTier[int] = LocalTier(max_size=100)
        await tier.set("k", 1)
        await tier.set("k", 2)

        result = await tier.get("k")
        assert isinstance(result, Ok)
        assert isinstance(result.value, Some)
        assert result.value.value == 2


class TestLocalTierGetMissing:
    """LocalTier: get missing returns Nothing."""

    @pytest.mark.asyncio
    async def test_get_nonexistent_key(self) -> None:
        tier: LocalTier[int] = LocalTier(max_size=100)
        result = await tier.get("nonexistent")

        assert isinstance(result, Ok)
        assert isinstance(result.value, Nothing)

    @pytest.mark.asyncio
    async def test_empty_tier_get(self) -> None:
        tier: LocalTier[str] = LocalTier()
        result = await tier.get("anything")

        assert isinstance(result, Ok)
        assert isinstance(result.value, Nothing)


class TestLocalTierDelete:
    """LocalTier: delete removes entry."""

    @pytest.mark.asyncio
    async def test_delete_existing_key(self) -> None:
        tier: LocalTier[int] = LocalTier(max_size=100)
        await tier.set("key", 99)
        await tier.delete("key")

        result = await tier.get("key")
        assert isinstance(result, Ok)
        assert isinstance(result.value, Nothing)

    @pytest.mark.asyncio
    async def test_delete_nonexistent_is_noop(self) -> None:
        tier: LocalTier[int] = LocalTier(max_size=100)
        result = await tier.delete("nope")
        assert isinstance(result, Ok)

    @pytest.mark.asyncio
    async def test_delete_pattern(self) -> None:
        tier: LocalTier[int] = LocalTier(max_size=100)
        await tier.set("user:1", 1)
        await tier.set("user:2", 2)
        await tier.set("order:1", 10)

        result = await tier.delete_pattern("user:*")
        assert isinstance(result, Ok)
        assert result.value == 2

        # user keys gone
        r1 = await tier.get("user:1")
        assert isinstance(r1.value, Nothing)
        # order key still present
        r2 = await tier.get("order:1")
        assert isinstance(r2.value, Some)
        assert r2.value.value == 10


class TestLocalTierEviction:
    """LocalTier: LRU eviction when max_size exceeded."""

    @pytest.mark.asyncio
    async def test_evicts_oldest_when_full(self) -> None:
        tier: LocalTier[int] = LocalTier(max_size=3)
        await tier.set("a", 1)
        await tier.set("b", 2)
        await tier.set("c", 3)
        # Cache is full, next set evicts oldest ("a")
        await tier.set("d", 4)

        result_a = await tier.get("a")
        assert isinstance(result_a.value, Nothing)

        result_d = await tier.get("d")
        assert isinstance(result_d.value, Some)
        assert result_d.value.value == 4

    @pytest.mark.asyncio
    async def test_lru_access_prevents_eviction(self) -> None:
        tier: LocalTier[int] = LocalTier(max_size=3)
        await tier.set("a", 1)
        await tier.set("b", 2)
        await tier.set("c", 3)

        # Access "a" to make it most recently used
        await tier.get("a")

        # Now insert "d" — "b" should be evicted (oldest unused)
        await tier.set("d", 4)

        result_a = await tier.get("a")
        assert isinstance(result_a.value, Some)

        result_b = await tier.get("b")
        assert isinstance(result_b.value, Nothing)


# ═══════════════════════════════════════════════════════════════════════════════
# Cache Builder + Executor Tests
# ═══════════════════════════════════════════════════════════════════════════════


class FetchTracker:
    """Tracks how many times the fetch function has been called."""

    def __init__(self, return_value: int = 42) -> None:
        self.call_count = 0
        self._return_value = return_value

    def fetch(self, key: str) -> LazyCoroResult[int, str]:
        tracker = self

        async def _do_fetch() -> Result[int, str]:
            tracker.call_count += 1
            return Ok(tracker._return_value)

        return LazyCoroResult(_do_fetch)


class TestCacheBuilderProducesExecutor:
    """cache(key_fn, fetch_fn).tier(tier).build() produces CacheExecutor."""

    def test_build_returns_executor(self) -> None:
        tier: LocalTier[int] = LocalTier(max_size=100)
        tracker = FetchTracker()

        executor = cache(
            key=lambda k: f"prefix:{k}",
            fetch=tracker.fetch,
        ).tier(tier).build()

        assert isinstance(executor, CacheExecutor)

    def test_builder_accumulates_tiers(self) -> None:
        tier1: LocalTier[int] = LocalTier(max_size=100)
        tier2: LocalTier[int] = LocalTier(max_size=50)
        tracker = FetchTracker()

        executor = (
            cache(key=lambda k: k, fetch=tracker.fetch)
            .tier(tier1)
            .tier(tier2)
            .build()
        )

        assert len(executor.tiers) == 2


class TestCacheExecutorHitMiss:
    """CacheExecutor: first get triggers fetch, second get hits cache."""

    @pytest.mark.asyncio
    async def test_first_get_is_miss_calls_fetch(self) -> None:
        tier: LocalTier[int] = LocalTier(max_size=100)
        tracker = FetchTracker(return_value=99)

        executor = cache(
            key=lambda k: f"key:{k}",
            fetch=tracker.fetch,
        ).tier(tier).build()

        result = await executor.get("user1")

        assert isinstance(result, Ok)
        cache_result: CacheResult[int] = result.value
        assert cache_result.value == 99
        assert cache_result.hit is False
        assert cache_result.tier is None  # miss path, fetched from source
        assert tracker.call_count == 1

    @pytest.mark.asyncio
    async def test_second_get_is_hit_no_fetch(self) -> None:
        tier: LocalTier[int] = LocalTier(max_size=100)
        tracker = FetchTracker(return_value=77)

        executor = cache(
            key=lambda k: f"key:{k}",
            fetch=tracker.fetch,
        ).tier(tier).build()

        # First call — miss, triggers fetch
        await executor.get("user1")
        assert tracker.call_count == 1

        # Second call — hit, no fetch
        result = await executor.get("user1")

        assert isinstance(result, Ok)
        assert result.value.value == 77
        assert result.value.hit is True
        assert result.value.tier == "local"
        assert tracker.call_count == 1  # still 1, no additional fetch

    @pytest.mark.asyncio
    async def test_different_keys_each_trigger_fetch(self) -> None:
        tier: LocalTier[int] = LocalTier(max_size=100)
        tracker = FetchTracker(return_value=10)

        executor = cache(
            key=lambda k: k,
            fetch=tracker.fetch,
        ).tier(tier).build()

        await executor.get("a")
        await executor.get("b")
        await executor.get("c")

        assert tracker.call_count == 3

    @pytest.mark.asyncio
    async def test_invalidate_causes_refetch(self) -> None:
        tier: LocalTier[int] = LocalTier(max_size=100)
        tracker = FetchTracker(return_value=50)

        executor = cache(
            key=lambda k: k,
            fetch=tracker.fetch,
        ).tier(tier).build()

        await executor.get("x")
        assert tracker.call_count == 1

        await executor.invalidate("x")

        await executor.get("x")
        assert tracker.call_count == 2  # re-fetched after invalidation

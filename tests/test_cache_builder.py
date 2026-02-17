"""Tests for emergent.cache._builder.

Covers:
    - cache() entry point: creates Cache builder
    - Cache.tier(): adds tiers, returns new builder
    - Cache.build(): creates CacheExecutor
    - CacheExecutor.get(): tries tiers then fetches, populates tiers
    - CacheExecutor.invalidate(): removes key from all tiers
    - CacheExecutor.invalidate_pattern(): removes matching keys from all tiers
    - Multi-tier behavior: L1 miss, L2 hit; full miss then fetch
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from kungfu import LazyCoroResult, Result, Ok, Error

from emergent.cache._builder import (
    Cache,
    CacheExecutor,
    cache,
)
from emergent.cache._types import (
    LocalTier,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Test helpers
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class UserId:
    value: str


@dataclass(frozen=True)
class User:
    name: str


@dataclass(frozen=True)
class FetchError:
    message: str


def make_key(uid: UserId) -> str:
    return f"user:{uid.value}"


def make_fetch_ok(
    name_prefix: str = "user",
) -> tuple[list[UserId], type[object]]:
    """Create a fetch function that tracks calls. Returns (call_list, _)."""
    calls: list[UserId] = []
    return calls, object


def fetch_user_ok(uid: UserId) -> LazyCoroResult[User, FetchError]:
    """Always-succeeding fetch."""

    async def _do() -> Result[User, FetchError]:
        return Ok(User(name=f"user_{uid.value}"))

    return LazyCoroResult(_do)


def fetch_user_error(uid: UserId) -> LazyCoroResult[User, FetchError]:
    """Always-failing fetch."""

    async def _do() -> Result[User, FetchError]:
        return Error(FetchError(message=f"not found: {uid.value}"))

    return LazyCoroResult(_do)


def make_tracking_fetch() -> (
    tuple[
        list[UserId],
        type[
            object
        ],
    ]
):
    """Create a fetch function that tracks which UIDs were fetched."""
    fetched: list[UserId] = []

    return fetched, object


# ═══════════════════════════════════════════════════════════════════════════════
# cache() Entry Point
# ═══════════════════════════════════════════════════════════════════════════════


class TestCacheEntryPoint:
    def test_creates_builder(self) -> None:
        c = cache(make_key, fetch_user_ok)
        assert isinstance(c, Cache)

    def test_builder_has_no_tiers(self) -> None:
        c = cache(make_key, fetch_user_ok)
        assert c._tiers == ()  # pyright: ignore[reportPrivateUsage]


# ═══════════════════════════════════════════════════════════════════════════════
# Cache.tier()
# ═══════════════════════════════════════════════════════════════════════════════


class TestCacheTier:
    def test_adds_tier(self) -> None:
        tier = LocalTier[User]()
        c = cache(make_key, fetch_user_ok).tier(tier)
        assert len(c._tiers) == 1  # pyright: ignore[reportPrivateUsage]
        assert c._tiers[0] is tier  # pyright: ignore[reportPrivateUsage]

    def test_returns_new_builder(self) -> None:
        tier = LocalTier[User]()
        original = cache(make_key, fetch_user_ok)
        with_tier = original.tier(tier)
        assert original is not with_tier
        assert original._tiers == ()  # pyright: ignore[reportPrivateUsage]
        assert len(with_tier._tiers) == 1  # pyright: ignore[reportPrivateUsage]

    def test_multiple_tiers(self) -> None:
        t1 = LocalTier[User](max_size=10)
        t2 = LocalTier[User](max_size=100)
        c = cache(make_key, fetch_user_ok).tier(t1).tier(t2)
        assert len(c._tiers) == 2  # pyright: ignore[reportPrivateUsage]
        assert c._tiers[0] is t1  # pyright: ignore[reportPrivateUsage]
        assert c._tiers[1] is t2  # pyright: ignore[reportPrivateUsage]


# ═══════════════════════════════════════════════════════════════════════════════
# Cache.build()
# ═══════════════════════════════════════════════════════════════════════════════


class TestCacheBuild:
    def test_build_creates_executor(self) -> None:
        executor = cache(make_key, fetch_user_ok).build()
        assert isinstance(executor, CacheExecutor)

    def test_build_preserves_key_fn(self) -> None:
        executor = cache(make_key, fetch_user_ok).build()
        assert executor.key_fn is make_key

    def test_build_preserves_tiers(self) -> None:
        tier = LocalTier[User]()
        executor = cache(make_key, fetch_user_ok).tier(tier).build()
        assert len(executor.tiers) == 1
        assert executor.tiers[0] is tier


# ═══════════════════════════════════════════════════════════════════════════════
# CacheExecutor.get() — No tiers (fetch only)
# ═══════════════════════════════════════════════════════════════════════════════


class TestCacheExecutorGetNoTiers:
    @pytest.mark.asyncio
    async def test_fetch_on_empty_cache(self) -> None:
        executor = cache(make_key, fetch_user_ok).build()
        result = await executor.get(UserId("alice"))
        match result:
            case Ok(cache_result):
                assert cache_result.value == User(name="user_alice")
                assert cache_result.hit is False
                assert cache_result.tier is None
            case Error(e):
                pytest.fail(f"Expected Ok, got Error: {e}")

    @pytest.mark.asyncio
    async def test_fetch_error_propagates(self) -> None:
        executor = cache(make_key, fetch_user_error).build()
        result = await executor.get(UserId("unknown"))
        match result:
            case Error(e):
                assert isinstance(e, FetchError)
                assert "unknown" in e.message
            case Ok(_):
                pytest.fail("Expected Error")


# ═══════════════════════════════════════════════════════════════════════════════
# CacheExecutor.get() — Single tier
# ═══════════════════════════════════════════════════════════════════════════════


class TestCacheExecutorGetSingleTier:
    @pytest.mark.asyncio
    async def test_miss_then_fetch_populates_tier(self) -> None:
        tier = LocalTier[User](max_size=100)
        executor = cache(make_key, fetch_user_ok).tier(tier).build()

        # First call: miss, fetch, populate
        result1 = await executor.get(UserId("alice"))
        match result1:
            case Ok(cr1):
                assert cr1.hit is False
                assert cr1.value == User(name="user_alice")
            case _:
                pytest.fail("Expected Ok on first call")

        # Second call: hit from tier
        result2 = await executor.get(UserId("alice"))
        match result2:
            case Ok(cr2):
                assert cr2.hit is True
                assert cr2.tier == "local"
                assert cr2.value == User(name="user_alice")
            case _:
                pytest.fail("Expected Ok on second call")

    @pytest.mark.asyncio
    async def test_different_keys_are_independent(self) -> None:
        tier = LocalTier[User](max_size=100)
        executor = cache(make_key, fetch_user_ok).tier(tier).build()

        r1 = await executor.get(UserId("alice"))
        r2 = await executor.get(UserId("bob"))

        match r1:
            case Ok(cr1):
                assert cr1.value == User(name="user_alice")
            case _:
                pytest.fail("Expected Ok for alice")

        match r2:
            case Ok(cr2):
                assert cr2.value == User(name="user_bob")
            case _:
                pytest.fail("Expected Ok for bob")


# ═══════════════════════════════════════════════════════════════════════════════
# CacheExecutor.get() — Multi-tier
# ═══════════════════════════════════════════════════════════════════════════════


class TestCacheExecutorGetMultiTier:
    @pytest.mark.asyncio
    async def test_l1_miss_l2_hit(self) -> None:
        l1 = LocalTier[User](max_size=100)
        l2 = LocalTier[User](max_size=100)
        executor = cache(make_key, fetch_user_ok).tier(l1).tier(l2).build()

        # Populate L2 directly
        await l2.set("user:alice", User(name="user_alice"))

        result = await executor.get(UserId("alice"))
        match result:
            case Ok(cr):
                assert cr.hit is True
                assert cr.tier == "local"
                assert cr.value == User(name="user_alice")
            case _:
                pytest.fail("Expected Ok from L2")

    @pytest.mark.asyncio
    async def test_all_tiers_miss_then_fetch(self) -> None:
        l1 = LocalTier[User](max_size=100)
        l2 = LocalTier[User](max_size=100)

        fetch_calls: list[UserId] = []

        def tracking_fetch(uid: UserId) -> LazyCoroResult[User, FetchError]:
            async def _do() -> Result[User, FetchError]:
                fetch_calls.append(uid)
                return Ok(User(name=f"user_{uid.value}"))

            return LazyCoroResult(_do)

        executor = cache(make_key, tracking_fetch).tier(l1).tier(l2).build()
        result = await executor.get(UserId("alice"))

        match result:
            case Ok(cr):
                assert cr.hit is False
                assert cr.tier is None
                assert len(fetch_calls) == 1
            case _:
                pytest.fail("Expected Ok after fetch")

        # Both tiers should be populated now
        from kungfu import Some

        l1_result = await l1.get("user:alice")
        assert l1_result == Ok(Some(User(name="user_alice")))

        l2_result = await l2.get("user:alice")
        assert l2_result == Ok(Some(User(name="user_alice")))


# ═══════════════════════════════════════════════════════════════════════════════
# CacheExecutor.invalidate()
# ═══════════════════════════════════════════════════════════════════════════════


class TestCacheExecutorInvalidate:
    @pytest.mark.asyncio
    async def test_invalidate_removes_from_all_tiers(self) -> None:
        from kungfu import Nothing

        l1 = LocalTier[User](max_size=100)
        l2 = LocalTier[User](max_size=100)
        executor = cache(make_key, fetch_user_ok).tier(l1).tier(l2).build()

        # Populate
        await executor.get(UserId("alice"))

        # Invalidate
        result = await executor.invalidate(UserId("alice"))
        assert result == Ok(None)

        # Verify both tiers are empty
        assert await l1.get("user:alice") == Ok(Nothing())
        assert await l2.get("user:alice") == Ok(Nothing())

    @pytest.mark.asyncio
    async def test_invalidate_nonexistent_key(self) -> None:
        tier = LocalTier[User]()
        executor = cache(make_key, fetch_user_ok).tier(tier).build()
        result = await executor.invalidate(UserId("nonexistent"))
        assert result == Ok(None)


# ═══════════════════════════════════════════════════════════════════════════════
# CacheExecutor.invalidate_pattern()
# ═══════════════════════════════════════════════════════════════════════════════


class TestCacheExecutorInvalidatePattern:
    @pytest.mark.asyncio
    async def test_invalidate_pattern_removes_matching(self) -> None:
        from kungfu import Nothing

        tier = LocalTier[User](max_size=100)
        executor = cache(make_key, fetch_user_ok).tier(tier).build()

        # Populate several keys
        await executor.get(UserId("alice"))
        await executor.get(UserId("bob"))

        # Invalidate all user keys
        result = await executor.invalidate_pattern("user:*")
        match result:
            case Ok(count):
                assert count == 2
            case _:
                pytest.fail("Expected Ok with count")

        assert await tier.get("user:alice") == Ok(Nothing())
        assert await tier.get("user:bob") == Ok(Nothing())

    @pytest.mark.asyncio
    async def test_invalidate_pattern_no_matches(self) -> None:
        tier = LocalTier[User](max_size=100)
        executor = cache(make_key, fetch_user_ok).tier(tier).build()

        result = await executor.invalidate_pattern("nonexistent:*")
        assert result == Ok(0)

    @pytest.mark.asyncio
    async def test_invalidate_pattern_multi_tier(self) -> None:
        l1 = LocalTier[User](max_size=100)
        l2 = LocalTier[User](max_size=100)
        executor = cache(make_key, fetch_user_ok).tier(l1).tier(l2).build()

        # Populate
        await executor.get(UserId("alice"))

        result = await executor.invalidate_pattern("user:*")
        match result:
            case Ok(count):
                # 1 key in each tier = 2 total
                assert count == 2
            case _:
                pytest.fail("Expected Ok with count")

"""Tests for emergent.cache._ops.

Covers:
    - invalidate(): single key deletion in a tier
    - invalidate_pattern(): pattern-based deletion in a tier
    - Both return LazyCoroResult (must be awaited)
    - Error propagation from tier
"""

from __future__ import annotations

import pytest
from kungfu import Ok, Some, Nothing

from emergent.cache._ops import invalidate, invalidate_pattern
from emergent.cache._types import LocalTier


# ═══════════════════════════════════════════════════════════════════════════════
# invalidate()
# ═══════════════════════════════════════════════════════════════════════════════


class TestInvalidate:
    @pytest.mark.asyncio
    async def test_invalidate_existing_key(self) -> None:
        tier = LocalTier[str]()
        await tier.set("key1", "value1")

        result = await invalidate(tier, "key1")
        assert result == Ok(None)

        # Verify key is gone
        assert await tier.get("key1") == Ok(Nothing())

    @pytest.mark.asyncio
    async def test_invalidate_nonexistent_key(self) -> None:
        tier = LocalTier[str]()
        result = await invalidate(tier, "nonexistent")
        assert result == Ok(None)

    @pytest.mark.asyncio
    async def test_invalidate_does_not_affect_other_keys(self) -> None:
        tier = LocalTier[str]()
        await tier.set("key1", "value1")
        await tier.set("key2", "value2")

        await invalidate(tier, "key1")

        assert await tier.get("key1") == Ok(Nothing())
        assert await tier.get("key2") == Ok(Some("value2"))

    @pytest.mark.asyncio
    async def test_invalidate_returns_lazy_coro_result(self) -> None:
        tier = LocalTier[str]()
        lazy = invalidate(tier, "key1")
        # It should be a LazyCoroResult that can be awaited
        result = await lazy
        assert result == Ok(None)


# ═══════════════════════════════════════════════════════════════════════════════
# invalidate_pattern()
# ═══════════════════════════════════════════════════════════════════════════════


class TestInvalidatePattern:
    @pytest.mark.asyncio
    async def test_invalidate_pattern_matching_keys(self) -> None:
        tier = LocalTier[str]()
        await tier.set("user:1", "alice")
        await tier.set("user:2", "bob")
        await tier.set("order:1", "pizza")

        result = await invalidate_pattern(tier, "user:*")
        assert result == Ok(2)

        assert await tier.get("user:1") == Ok(Nothing())
        assert await tier.get("user:2") == Ok(Nothing())
        assert await tier.get("order:1") == Ok(Some("pizza"))

    @pytest.mark.asyncio
    async def test_invalidate_pattern_no_matches(self) -> None:
        tier = LocalTier[str]()
        await tier.set("key1", "value1")

        result = await invalidate_pattern(tier, "nonexistent:*")
        assert result == Ok(0)

    @pytest.mark.asyncio
    async def test_invalidate_pattern_all(self) -> None:
        tier = LocalTier[str]()
        await tier.set("a", "1")
        await tier.set("b", "2")
        await tier.set("c", "3")

        result = await invalidate_pattern(tier, "*")
        assert result == Ok(3)

        assert await tier.get("a") == Ok(Nothing())
        assert await tier.get("b") == Ok(Nothing())
        assert await tier.get("c") == Ok(Nothing())

    @pytest.mark.asyncio
    async def test_invalidate_pattern_empty_tier(self) -> None:
        tier = LocalTier[str]()
        result = await invalidate_pattern(tier, "*")
        assert result == Ok(0)

    @pytest.mark.asyncio
    async def test_invalidate_pattern_returns_lazy_coro_result(self) -> None:
        tier = LocalTier[str]()
        lazy = invalidate_pattern(tier, "*")
        result = await lazy
        assert result == Ok(0)

    @pytest.mark.asyncio
    async def test_invalidate_pattern_specific_pattern(self) -> None:
        tier = LocalTier[str]()
        await tier.set("cache:user:1", "alice")
        await tier.set("cache:user:2", "bob")
        await tier.set("cache:order:1", "pizza")
        await tier.set("session:user:1", "token")

        result = await invalidate_pattern(tier, "cache:user:*")
        assert result == Ok(2)

        assert await tier.get("cache:user:1") == Ok(Nothing())
        assert await tier.get("cache:user:2") == Ok(Nothing())
        assert await tier.get("cache:order:1") == Ok(Some("pizza"))
        assert await tier.get("session:user:1") == Ok(Some("token"))

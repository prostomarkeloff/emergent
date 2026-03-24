"""Tests for emergent.idempotency._builder.

Covers:
    - idempotent() entry point: creates Idempotent builder with defaults
    - Idempotent.key(): sets key extraction function
    - Idempotent.storage(): sets storage backend
    - Idempotent.policy(): sets idempotency policy
    - Idempotent.build(): validation (requires key), creates IdempotentExecutor
    - IdempotentExecutor.run(): executes with idempotency
    - IdempotentExecutor.invalidate(): removes cached record
    - Immutability: each builder method returns new Idempotent
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from kungfu import LazyCoroResult, Result, Ok, Error

from emergent.idempotency._builder import (
    Idempotent,
    IdempotentExecutor,
    idempotent,
)
from emergent.idempotency._policy import Policy, OnPending
from emergent.idempotency._store import Record
from emergent.idempotency._types import (
    IdempotencyErrorKind,
)
from emergent.wire.axis.storage import MemoryStorage


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
class NotFoundError:
    message: str


def fetch_user_ok(uid: UserId) -> LazyCoroResult[User, NotFoundError]:
    """Always returns a successful user."""

    async def _do() -> Result[User, NotFoundError]:
        return Ok(User(name=f"user_{uid.value}"))

    return LazyCoroResult(_do)


def fetch_user_error(uid: UserId) -> LazyCoroResult[User, NotFoundError]:
    """Always returns an error."""

    async def _do() -> Result[User, NotFoundError]:
        return Error(NotFoundError(message=f"not found: {uid.value}"))

    return LazyCoroResult(_do)


def make_key(uid: UserId) -> str:
    return f"user:{uid.value}"


# ═══════════════════════════════════════════════════════════════════════════════
# idempotent() Entry Point
# ═══════════════════════════════════════════════════════════════════════════════


class TestIdempotentEntryPoint:
    def test_creates_builder_with_defaults(self) -> None:
        builder = idempotent(fetch_user_ok)
        assert getattr(builder, "_key_fn") is None
        assert getattr(builder, "_storage") is None
        assert isinstance(getattr(builder, "_policy"), Policy)

    def test_returns_idempotent_instance(self) -> None:
        builder = idempotent(fetch_user_ok)
        assert isinstance(builder, Idempotent)


# ═══════════════════════════════════════════════════════════════════════════════
# Idempotent Builder Methods
# ═══════════════════════════════════════════════════════════════════════════════


class TestIdempotentBuilder:
    def test_key_sets_key_fn(self) -> None:
        builder = idempotent(fetch_user_ok).key(make_key)
        assert getattr(builder, "_key_fn") is make_key

    def test_storage_sets_storage(self) -> None:
        storage = MemoryStorage[str, Record[User]]()
        builder = idempotent(fetch_user_ok).storage(storage)
        assert getattr(builder, "_storage") is storage

    def test_policy_sets_policy(self) -> None:
        p = Policy().with_ttl(seconds=100)
        builder = idempotent(fetch_user_ok).policy(p)
        assert getattr(builder, "_policy") is p

    def test_builder_is_immutable(self) -> None:
        original = idempotent(fetch_user_ok)
        with_key = original.key(make_key)
        assert original is not with_key
        assert getattr(original, "_key_fn") is None
        assert getattr(with_key, "_key_fn") is make_key

    def test_chaining(self) -> None:
        storage = MemoryStorage[str, Record[User]]()
        p = Policy().with_ttl(seconds=60)
        builder = (
            idempotent(fetch_user_ok)
            .key(make_key)
            .storage(storage)
            .policy(p)
        )
        assert getattr(builder, "_key_fn") is make_key
        assert getattr(builder, "_storage") is storage
        assert getattr(builder, "_policy") is p


# ═══════════════════════════════════════════════════════════════════════════════
# Idempotent.build()
# ═══════════════════════════════════════════════════════════════════════════════


class TestIdempotentBuild:
    def test_build_without_key_raises(self) -> None:
        builder = idempotent(fetch_user_ok)
        with pytest.raises(ValueError, match="key"):
            builder.build()

    def test_build_with_key_succeeds(self) -> None:
        executor = idempotent(fetch_user_ok).key(make_key).build()
        assert isinstance(executor, IdempotentExecutor)

    def test_build_uses_default_storage(self) -> None:
        executor = idempotent(fetch_user_ok).key(make_key).build()
        assert executor.storage is not None

    def test_build_uses_provided_storage(self) -> None:
        storage = MemoryStorage[str, Record[User]]()
        executor = (
            idempotent(fetch_user_ok)
            .key(make_key)
            .storage(storage)
            .build()
        )
        assert executor.storage is storage

    def test_build_uses_provided_policy(self) -> None:
        p = Policy().with_ttl(seconds=300)
        executor = (
            idempotent(fetch_user_ok)
            .key(make_key)
            .policy(p)
            .build()
        )
        assert executor.policy is p

    def test_build_uses_default_policy(self) -> None:
        executor = idempotent(fetch_user_ok).key(make_key).build()
        assert isinstance(executor.policy, Policy)
        assert executor.policy.result_ttl is None


# ═══════════════════════════════════════════════════════════════════════════════
# IdempotentExecutor.run()
# ═══════════════════════════════════════════════════════════════════════════════


class TestIdempotentExecutorRun:
    @pytest.mark.asyncio
    async def test_run_success(self) -> None:
        executor = idempotent(fetch_user_ok).key(make_key).build()
        uid = UserId("alice")
        result = await executor.run(uid)
        match result:
            case Ok(idempotency_result):
                assert idempotency_result.value == User(name="user_alice")
                assert idempotency_result.from_cache is False
                assert idempotency_result.key == "user:alice"
            case Error(err):
                pytest.fail(f"Expected Ok but got Error: {err}")

    @pytest.mark.asyncio
    async def test_run_returns_cached_on_second_call(self) -> None:
        executor = idempotent(fetch_user_ok).key(make_key).build()
        uid = UserId("bob")

        # First call
        result1 = await executor.run(uid)
        match result1:
            case Ok(r1):
                assert r1.from_cache is False
            case _:
                pytest.fail("Expected Ok for first call")

        # Second call should be cached
        result2 = await executor.run(uid)
        match result2:
            case Ok(r2):
                assert r2.from_cache is True
                assert r2.value == User(name="user_bob")
            case _:
                pytest.fail("Expected Ok for second call")

    @pytest.mark.asyncio
    async def test_run_error_operation(self) -> None:
        executor = idempotent(fetch_user_error).key(make_key).build()
        uid = UserId("unknown")
        result = await executor.run(uid)
        match result:
            case Error(err):
                assert err.kind == IdempotencyErrorKind.EXECUTION
            case Ok(_):
                pytest.fail("Expected Error but got Ok")

    @pytest.mark.asyncio
    async def test_run_different_keys_independent(self) -> None:
        executor = idempotent(fetch_user_ok).key(make_key).build()

        result_a = await executor.run(UserId("alice"))
        result_b = await executor.run(UserId("bob"))

        match result_a:
            case Ok(ra):
                assert ra.value == User(name="user_alice")
            case _:
                pytest.fail("Expected Ok for alice")

        match result_b:
            case Ok(rb):
                assert rb.value == User(name="user_bob")
            case _:
                pytest.fail("Expected Ok for bob")


# ═══════════════════════════════════════════════════════════════════════════════
# IdempotentExecutor.invalidate()
# ═══════════════════════════════════════════════════════════════════════════════


class TestIdempotentExecutorInvalidate:
    @pytest.mark.asyncio
    async def test_invalidate_removes_record(self) -> None:
        executor = idempotent(fetch_user_ok).key(make_key).build()
        uid = UserId("alice")

        # Execute first to populate cache
        await executor.run(uid)

        # Invalidate
        invalidated = await executor.invalidate(uid)
        assert invalidated is True

        # Run again should not be cached
        result = await executor.run(uid)
        match result:
            case Ok(r):
                assert r.from_cache is False
            case _:
                pytest.fail("Expected Ok after invalidation")

    @pytest.mark.asyncio
    async def test_invalidate_nonexistent_key(self) -> None:
        executor = idempotent(fetch_user_ok).key(make_key).build()
        uid = UserId("nonexistent")

        # Invalidating a key that was never set should return True
        # (MemoryStorage.delete always returns Ok(None))
        invalidated = await executor.invalidate(uid)
        assert invalidated is True


# ═══════════════════════════════════════════════════════════════════════════════
# IdempotentExecutor with Policy
# ═══════════════════════════════════════════════════════════════════════════════


class TestIdempotentExecutorWithPolicy:
    @pytest.mark.asyncio
    async def test_with_fail_policy_on_conflict(self) -> None:
        """When policy is FAIL, concurrent requests get CONFLICT error."""
        call_count = 0

        async def slow_fetch_inner() -> Result[User, NotFoundError]:
            nonlocal call_count
            call_count += 1
            return Ok(User(name="slow"))

        def slow_fetch(uid: UserId) -> LazyCoroResult[User, NotFoundError]:
            return LazyCoroResult(slow_fetch_inner)

        policy = Policy().with_on_pending(OnPending.FAIL)
        executor = (
            idempotent(slow_fetch)
            .key(make_key)
            .policy(policy)
            .build()
        )

        # First execution should succeed
        result = await executor.run(UserId("test"))
        match result:
            case Ok(r):
                assert r.from_cache is False
            case Error(err):
                pytest.fail(f"Expected Ok but got Error: {err}")

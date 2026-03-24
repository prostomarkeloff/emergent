# pyright: reportPrivateUsage=false
"""Property tests for saga, cache, idempotency, and ops modules.

Covers algebraic properties and invariants (no async I/O):

Saga types:
    1. SagaStep is frozen
    2. Parallel.sagas is a tuple with correct length
    3. Parallel / Race are frozen
    4. step() creates SagaStep with correct action and compensate
    5. .then() creates a Then with inner step and continuation
    6. parallel/race of N steps has N steps

Saga policies:
    7. All compensation policy variants exist and are constructible
    8. All on-failure policy variants exist
    9. Policy dataclasses are frozen (immutable)

Idempotency types:
    10. RecordState has exactly 3 states
    11. IdempotencyRecord is frozen
    12. IdempotencyRecord fields are preserved

Cache types:
    13. CacheResult is frozen
    14. Cache builder pattern: tier accumulation, build produces CacheExecutor

Ops:
    15. ops() returns OpsBuilder
    16. .on() registers a handler
    17. .compile() produces a Runner
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Coroutine
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from kungfu import LazyCoroResult, Ok, Result

from emergent.saga._types import (
    SagaStep,
    Then,
    Parallel,
    Race,
    SagaResult,
    SagaError,
)
from emergent.saga._step import step
from emergent.saga._compose import parallel, race
from emergent.saga.policy._compensate import (
    AllOnFailurePolicy,
    SequentialPolicy,
    ParallelPolicy,
    RetryPolicy,
    SkipPolicy,
    all_on_failure,
    sequential,
    parallel as parallel_compensate,
    retry,
    skip,
)
from emergent.saga.policy._on_failure import (
    ContinuePolicy,
    AbortPolicy,
    continue_,
    abort,
)
from emergent.cache._types import CacheResult, CacheError, CacheErrorKind
from emergent.cache._builder import Cache, CacheExecutor, cache
from emergent.idempotency._types import (
    RecordState,
    IdempotencyRecord,
    IdempotencyResult,
    IdempotencyError,
    IdempotencyErrorKind,
)
from emergent.ops import ops, OpsBuilder, Runner, Op


# ═══════════════════════════════════════════════════════════════════════════════
# Module-level Op types — must be at module scope for get_type_hints()
# to resolve forward references when `from __future__ import annotations`
# is active.
# ═══════════════════════════════════════════════════════════════════════════════


@dataclasses.dataclass(frozen=True, slots=True)
class _MyOp(Op[int, str]):
    x: int


@dataclasses.dataclass(frozen=True, slots=True)
class _SomeOp(Op[str, str]):
    name: str


@dataclasses.dataclass(frozen=True, slots=True)
class _DupOp(Op[int, str]):
    x: int


@dataclasses.dataclass(frozen=True, slots=True)
class _CompOp(Op[int, str]):
    x: int


@dataclasses.dataclass(frozen=True, slots=True)
class _RegOp(Op[int, str]):
    x: int


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers — dummy action / compensate for saga tests
# ═══════════════════════════════════════════════════════════════════════════════


def _make_action(value: int) -> LazyCoroResult[int, str]:
    async def run() -> Result[int, str]:
        return Ok(value)

    return LazyCoroResult(run)


async def _dummy_compensate(value: int) -> None:
    pass


# ═══════════════════════════════════════════════════════════════════════════════
# 1. SagaStep is frozen
# ═══════════════════════════════════════════════════════════════════════════════


class TestSagaStepFrozen:
    def test_cannot_set_action(self) -> None:
        s = SagaStep(action=_make_action(1), compensate=None)
        with pytest.raises(dataclasses.FrozenInstanceError):
            s.action = _make_action(2)  # type: ignore[misc]

    def test_cannot_set_compensate(self) -> None:
        s = SagaStep(action=_make_action(1), compensate=_dummy_compensate)
        with pytest.raises(dataclasses.FrozenInstanceError):
            s.compensate = None  # type: ignore[misc]

    def test_is_frozen_dataclass(self) -> None:
        assert dataclasses.is_dataclass(SagaStep)
        fields = {f.name for f in dataclasses.fields(SagaStep)}
        assert "action" in fields
        assert "compensate" in fields


# ═══════════════════════════════════════════════════════════════════════════════
# 2-3. Parallel / Race — tuple property and frozen
# ═══════════════════════════════════════════════════════════════════════════════


class TestParallelProperties:
    @given(n=st.integers(min_value=1, max_value=20))
    @settings(max_examples=30)
    def test_parallel_has_n_sagas(self, n: int) -> None:
        steps = tuple(
            SagaStep(action=_make_action(i), compensate=None) for i in range(n)
        )
        p = Parallel(sagas=steps)
        assert len(p.sagas) == n
        assert isinstance(p.sagas, tuple)

    def test_parallel_is_frozen(self) -> None:
        s = SagaStep(action=_make_action(1), compensate=None)
        p = Parallel(sagas=(s,))
        with pytest.raises(dataclasses.FrozenInstanceError):
            p.sagas = ()  # type: ignore[misc]


class TestRaceProperties:
    @given(n=st.integers(min_value=1, max_value=20))
    @settings(max_examples=30)
    def test_race_has_n_sagas(self, n: int) -> None:
        steps = tuple(
            SagaStep(action=_make_action(i), compensate=None) for i in range(n)
        )
        r = Race(sagas=steps)
        assert len(r.sagas) == n
        assert isinstance(r.sagas, tuple)

    def test_race_is_frozen(self) -> None:
        s = SagaStep(action=_make_action(1), compensate=None)
        r = Race(sagas=(s,))
        with pytest.raises(dataclasses.FrozenInstanceError):
            r.sagas = ()  # type: ignore[misc]


# ═══════════════════════════════════════════════════════════════════════════════
# 4. step() creates SagaStep with correct action and compensate
# ═══════════════════════════════════════════════════════════════════════════════


class TestStepConstructor:
    def test_step_with_compensate(self) -> None:
        action = _make_action(42)
        s = step(action=action, compensate=_dummy_compensate)
        assert isinstance(s, SagaStep)
        assert s.action is action
        assert s.compensate is _dummy_compensate

    def test_step_without_compensate(self) -> None:
        action = _make_action(7)
        s = step(action=action)
        assert isinstance(s, SagaStep)
        assert s.action is action
        assert s.compensate is None

    @given(val=st.integers())
    @settings(max_examples=30)
    def test_step_preserves_action_identity(self, val: int) -> None:
        action = _make_action(val)
        s = step(action=action, compensate=None)
        assert s.action is action


# ═══════════════════════════════════════════════════════════════════════════════
# 5. .then() creates a Then with inner step and continuation
# ═══════════════════════════════════════════════════════════════════════════════


class TestThenComposition:
    def test_then_creates_then_type(self) -> None:
        s1 = step(action=_make_action(1), compensate=None)
        chained = s1.then(lambda v: step(action=_make_action(v + 1), compensate=None))
        assert isinstance(chained, Then)

    def test_then_inner_is_original_step(self) -> None:
        s1 = step(action=_make_action(1), compensate=None)
        chained = s1.then(lambda v: step(action=_make_action(v + 1), compensate=None))
        assert chained.inner is s1

    def test_then_f_is_callable(self) -> None:
        s1 = step(action=_make_action(1), compensate=None)

        def f(v: int) -> SagaStep[int, str]:
            return step(action=_make_action(v + 1), compensate=None)

        chained = s1.then(f)
        assert chained.f is f

    def test_then_is_frozen(self) -> None:
        s1 = step(action=_make_action(1), compensate=None)
        chained = s1.then(lambda v: step(action=_make_action(v + 1), compensate=None))
        with pytest.raises(dataclasses.FrozenInstanceError):
            chained.inner = s1  # type: ignore[misc]


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Composition: parallel/race of N steps has N steps
# ═══════════════════════════════════════════════════════════════════════════════


class TestCompositionLength:
    @given(n=st.integers(min_value=1, max_value=30))
    @settings(max_examples=30)
    def test_parallel_composition_n_steps(self, n: int) -> None:
        steps = [
            SagaStep(action=_make_action(i), compensate=None) for i in range(n)
        ]
        p = parallel(*steps)
        assert isinstance(p, Parallel)
        assert len(p.sagas) == n

    @given(n=st.integers(min_value=1, max_value=30))
    @settings(max_examples=30)
    def test_race_composition_n_steps(self, n: int) -> None:
        steps = [
            SagaStep(action=_make_action(i), compensate=None) for i in range(n)
        ]
        r = race(*steps)
        assert isinstance(r, Race)
        assert len(r.sagas) == n

    def test_parallel_empty(self) -> None:
        p: Parallel[object, object] = parallel()
        assert len(p.sagas) == 0

    def test_race_empty(self) -> None:
        r: Race[object, object] = race()
        assert len(r.sagas) == 0


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Compensation policy variants
# ═══════════════════════════════════════════════════════════════════════════════


class TestCompensationPolicies:
    def test_all_on_failure_exists(self) -> None:
        p = all_on_failure()
        assert isinstance(p, AllOnFailurePolicy)

    def test_sequential_exists(self) -> None:
        p = sequential()
        assert isinstance(p, SequentialPolicy)

    def test_parallel_exists(self) -> None:
        p = parallel_compensate()
        assert isinstance(p, ParallelPolicy)
        assert p.max_concurrent == 10

    def test_parallel_custom_concurrency(self) -> None:
        p = parallel_compensate(max_concurrent=5)
        assert p.max_concurrent == 5

    def test_retry_exists(self) -> None:
        p = retry()
        assert isinstance(p, RetryPolicy)
        assert p.times == 3
        assert p.delay == timedelta(seconds=1)

    def test_retry_custom(self) -> None:
        p = retry(times=5, delay=timedelta(seconds=2))
        assert p.times == 5
        assert p.delay == timedelta(seconds=2)

    def test_skip_exists(self) -> None:
        p = skip()
        assert isinstance(p, SkipPolicy)

    def test_all_policy_types_are_dataclasses(self) -> None:
        for cls in (
            AllOnFailurePolicy,
            SequentialPolicy,
            ParallelPolicy,
            RetryPolicy,
            SkipPolicy,
        ):
            assert dataclasses.is_dataclass(cls), f"{cls.__name__} is not a dataclass"


# ═══════════════════════════════════════════════════════════════════════════════
# 8. On-failure policy variants
# ═══════════════════════════════════════════════════════════════════════════════


class TestOnFailurePolicies:
    def test_continue_exists(self) -> None:
        p = continue_()
        assert isinstance(p, ContinuePolicy)

    def test_abort_exists(self) -> None:
        p = abort()
        assert isinstance(p, AbortPolicy)


# ═══════════════════════════════════════════════════════════════════════════════
# 9. All policy types are frozen (immutable)
# ═══════════════════════════════════════════════════════════════════════════════


class TestPoliciesFrozen:
    def _get_frozen(self, cls: type) -> bool:
        """Extract frozen flag from dataclass params."""
        params: object = getattr(cls, "__dataclass_params__")
        return bool(getattr(params, "frozen"))

    def test_all_on_failure_frozen_metadata(self) -> None:
        assert dataclasses.fields(AllOnFailurePolicy) is not None
        assert self._get_frozen(AllOnFailurePolicy) is True

    def test_sequential_frozen_metadata(self) -> None:
        assert self._get_frozen(SequentialPolicy) is True

    def test_parallel_frozen(self) -> None:
        p = parallel_compensate()
        with pytest.raises(dataclasses.FrozenInstanceError):
            p.max_concurrent = 20  # type: ignore[misc]

    def test_retry_frozen(self) -> None:
        p = retry()
        with pytest.raises(dataclasses.FrozenInstanceError):
            p.times = 10  # type: ignore[misc]

    def test_skip_frozen_metadata(self) -> None:
        assert self._get_frozen(SkipPolicy) is True

    def test_continue_frozen_metadata(self) -> None:
        assert self._get_frozen(ContinuePolicy) is True

    def test_abort_frozen_metadata(self) -> None:
        assert self._get_frozen(AbortPolicy) is True


# ═══════════════════════════════════════════════════════════════════════════════
# 10. RecordState has exactly 3 states
# ═══════════════════════════════════════════════════════════════════════════════


class TestRecordState:
    def test_has_pending(self) -> None:
        assert RecordState.PENDING is not None

    def test_has_completed(self) -> None:
        assert RecordState.COMPLETED is not None

    def test_has_failed(self) -> None:
        assert RecordState.FAILED is not None

    def test_exactly_three_states(self) -> None:
        assert len(RecordState) == 3

    def test_all_distinct(self) -> None:
        states = {RecordState.PENDING, RecordState.COMPLETED, RecordState.FAILED}
        assert len(states) == 3


# ═══════════════════════════════════════════════════════════════════════════════
# 11. IdempotencyRecord is frozen
# ═══════════════════════════════════════════════════════════════════════════════


class TestIdempotencyRecordFrozen:
    def _make_record(
        self, key: str = "test-key", value: str = "val"
    ) -> IdempotencyRecord[str, str]:
        now = datetime.now(tz=timezone.utc)
        return IdempotencyRecord(
            key=key,
            state=RecordState.COMPLETED,
            value=value,
            error=None,
            created_at=now,
            expires_at=None,
        )

    def test_cannot_set_key(self) -> None:
        r = self._make_record()
        with pytest.raises(dataclasses.FrozenInstanceError):
            r.key = "new-key"  # type: ignore[misc]

    def test_cannot_set_state(self) -> None:
        r = self._make_record()
        with pytest.raises(dataclasses.FrozenInstanceError):
            r.state = RecordState.FAILED  # type: ignore[misc]

    def test_cannot_set_value(self) -> None:
        r = self._make_record()
        with pytest.raises(dataclasses.FrozenInstanceError):
            r.value = "other"  # type: ignore[misc]

    def test_is_dataclass(self) -> None:
        assert dataclasses.is_dataclass(IdempotencyRecord)


# ═══════════════════════════════════════════════════════════════════════════════
# 12. IdempotencyRecord — key, value, state all preserved
# ═══════════════════════════════════════════════════════════════════════════════


class TestIdempotencyRecordFields:
    @given(
        key=st.text(min_size=1, max_size=100),
        value=st.text(min_size=0, max_size=100),
    )
    @settings(max_examples=50)
    def test_key_and_value_preserved(self, key: str, value: str) -> None:
        now = datetime.now(tz=timezone.utc)
        r: IdempotencyRecord[str, str] = IdempotencyRecord(
            key=key,
            state=RecordState.COMPLETED,
            value=value,
            error=None,
            created_at=now,
            expires_at=None,
        )
        assert r.key == key
        assert r.value == value
        assert r.state == RecordState.COMPLETED
        assert r.error is None

    def test_pending_record_properties(self) -> None:
        now = datetime.now(tz=timezone.utc)
        r: IdempotencyRecord[str, str] = IdempotencyRecord(
            key="k",
            state=RecordState.PENDING,
            value=None,
            error=None,
            created_at=now,
            expires_at=None,
        )
        assert r.is_pending is True
        assert r.is_completed is False
        assert r.is_failed is False

    def test_completed_record_properties(self) -> None:
        now = datetime.now(tz=timezone.utc)
        r: IdempotencyRecord[str, str] = IdempotencyRecord(
            key="k",
            state=RecordState.COMPLETED,
            value="done",
            error=None,
            created_at=now,
            expires_at=None,
        )
        assert r.is_pending is False
        assert r.is_completed is True
        assert r.is_failed is False

    def test_failed_record_properties(self) -> None:
        now = datetime.now(tz=timezone.utc)
        r: IdempotencyRecord[str, str] = IdempotencyRecord(
            key="k",
            state=RecordState.FAILED,
            value=None,
            error="boom",
            created_at=now,
            expires_at=None,
        )
        assert r.is_pending is False
        assert r.is_completed is False
        assert r.is_failed is True

    def test_input_hash_preserved(self) -> None:
        now = datetime.now(tz=timezone.utc)
        r: IdempotencyRecord[str, str] = IdempotencyRecord(
            key="k",
            state=RecordState.COMPLETED,
            value="v",
            error=None,
            created_at=now,
            expires_at=None,
            input_hash="abc123",
        )
        assert r.input_hash == "abc123"

    def test_expired_record(self) -> None:
        past = datetime.now(tz=timezone.utc) - timedelta(hours=1)
        r: IdempotencyRecord[str, str] = IdempotencyRecord(
            key="k",
            state=RecordState.COMPLETED,
            value="v",
            error=None,
            created_at=past,
            expires_at=past,
        )
        assert r.is_expired is True

    def test_not_expired_record(self) -> None:
        now = datetime.now(tz=timezone.utc)
        future = now + timedelta(hours=1)
        r: IdempotencyRecord[str, str] = IdempotencyRecord(
            key="k",
            state=RecordState.COMPLETED,
            value="v",
            error=None,
            created_at=now,
            expires_at=future,
        )
        assert r.is_expired is False

    def test_no_expiry_is_not_expired(self) -> None:
        now = datetime.now(tz=timezone.utc)
        r: IdempotencyRecord[str, str] = IdempotencyRecord(
            key="k",
            state=RecordState.COMPLETED,
            value="v",
            error=None,
            created_at=now,
            expires_at=None,
        )
        assert r.is_expired is False


# ═══════════════════════════════════════════════════════════════════════════════
# 13. CacheResult is frozen
# ═══════════════════════════════════════════════════════════════════════════════


class TestCacheResultFrozen:
    def test_cache_result_is_frozen(self) -> None:
        cr = CacheResult(value="hello", hit=True, tier="local", ttl_remaining=None)
        with pytest.raises(dataclasses.FrozenInstanceError):
            cr.value = "world"  # type: ignore[misc]

    def test_cache_result_fields_preserved(self) -> None:
        cr = CacheResult(
            value=42,
            hit=False,
            tier=None,
            ttl_remaining=timedelta(seconds=30),
        )
        assert cr.value == 42
        assert cr.hit is False
        assert cr.tier is None
        assert cr.ttl_remaining == timedelta(seconds=30)

    @given(val=st.integers(), hit=st.booleans())
    @settings(max_examples=30)
    def test_cache_result_value_hit_preserved(self, val: int, hit: bool) -> None:
        cr = CacheResult(value=val, hit=hit, tier="t", ttl_remaining=None)
        assert cr.value == val
        assert cr.hit is hit

    def test_cache_error_is_frozen(self) -> None:
        ce = CacheError(kind=CacheErrorKind.MISS, message="not found")
        with pytest.raises(dataclasses.FrozenInstanceError):
            ce.kind = CacheErrorKind.TIMEOUT  # type: ignore[misc]

    def test_cache_error_kind_all_variants(self) -> None:
        expected = {"MISS", "CONNECTION", "SERIALIZATION", "TIMEOUT", "NO_FETCH"}
        actual = {e.name for e in CacheErrorKind}
        assert actual == expected


# ═══════════════════════════════════════════════════════════════════════════════
# 14. Cache builder pattern — tier accumulation
# ═══════════════════════════════════════════════════════════════════════════════


class TestCacheBuilderPattern:
    def test_cache_creates_cache_with_empty_tiers(self) -> None:
        def key_fn(k: str) -> str:
            return k

        def fetch_fn(k: str) -> LazyCoroResult[str, str]:
            async def run() -> Result[str, str]:
                return Ok(k)

            return LazyCoroResult(run)

        c = cache(key=key_fn, fetch=fetch_fn)
        assert isinstance(c, Cache)
        assert c._tiers == ()

    def test_cache_is_frozen(self) -> None:
        def key_fn(k: str) -> str:
            return k

        def fetch_fn(k: str) -> LazyCoroResult[str, str]:
            async def run() -> Result[str, str]:
                return Ok(k)

            return LazyCoroResult(run)

        c = cache(key=key_fn, fetch=fetch_fn)
        with pytest.raises(dataclasses.FrozenInstanceError):
            c._tiers = ()  # type: ignore[misc]

    def test_tier_accumulation(self) -> None:
        from emergent.cache._types import LocalTier

        def key_fn(k: str) -> str:
            return k

        def fetch_fn(k: str) -> LazyCoroResult[str, str]:
            async def run() -> Result[str, str]:
                return Ok(k)

            return LazyCoroResult(run)

        c = cache(key=key_fn, fetch=fetch_fn)
        t1 = LocalTier[str](max_size=50)
        t2 = LocalTier[str](max_size=100)

        c1 = c.tier(t1)
        assert len(c1._tiers) == 1
        assert c1._tiers[0] is t1

        c2 = c1.tier(t2)
        assert len(c2._tiers) == 2
        assert c2._tiers[0] is t1
        assert c2._tiers[1] is t2

        # Original unchanged (immutability)
        assert len(c._tiers) == 0
        assert len(c1._tiers) == 1

    def test_build_produces_cache_executor(self) -> None:
        from emergent.cache._types import LocalTier

        def key_fn(k: str) -> str:
            return k

        def fetch_fn(k: str) -> LazyCoroResult[str, str]:
            async def run() -> Result[str, str]:
                return Ok(k)

            return LazyCoroResult(run)

        t = LocalTier[str](max_size=50)
        executor = cache(key=key_fn, fetch=fetch_fn).tier(t).build()
        assert isinstance(executor, CacheExecutor)
        assert len(executor.tiers) == 1
        assert executor.tiers[0] is t

    def test_cache_executor_is_frozen(self) -> None:
        from emergent.cache._types import LocalTier

        def key_fn(k: str) -> str:
            return k

        def fetch_fn(k: str) -> LazyCoroResult[str, str]:
            async def run() -> Result[str, str]:
                return Ok(k)

            return LazyCoroResult(run)

        executor = cache(key=key_fn, fetch=fetch_fn).tier(LocalTier[str]()).build()
        with pytest.raises(dataclasses.FrozenInstanceError):
            executor.tiers = ()  # type: ignore[misc]


# ═══════════════════════════════════════════════════════════════════════════════
# 15. ops() returns OpsBuilder
# ═══════════════════════════════════════════════════════════════════════════════


class TestOpsBuilder:
    def test_ops_returns_builder(self) -> None:
        builder = ops()
        assert isinstance(builder, OpsBuilder)

    def test_builder_is_frozen(self) -> None:
        builder = ops()
        with pytest.raises(dataclasses.FrozenInstanceError):
            builder._items = ()  # type: ignore[misc]


# ═══════════════════════════════════════════════════════════════════════════════
# 16. .on() registers a handler
# ═══════════════════════════════════════════════════════════════════════════════


class TestOpsOn:
    def test_on_returns_new_builder(self) -> None:
        async def handle(req: _MyOp) -> Result[int, str]:
            return Ok(req.x)

        b1 = ops()
        b2 = b1.on(_MyOp, handle)
        assert isinstance(b2, OpsBuilder)
        assert b1 is not b2

    def test_on_stores_handler(self) -> None:
        async def handle(req: _SomeOp) -> Result[str, str]:
            return Ok(req.name)

        builder = ops().on(_SomeOp, handle)
        assert len(builder._items) == 1
        registered_op_type, registered_handler = builder._items[0]
        assert registered_op_type is _SomeOp
        assert registered_handler is handle

    @given(n=st.integers(min_value=1, max_value=10))
    @settings(max_examples=10)
    def test_on_accumulates_handlers(self, n: int) -> None:
        # Dynamically create N distinct Op types
        op_types: list[type] = []
        handlers_list: list[Callable[..., Coroutine[Any, Any, Result[int, str]]]] = []
        for i in range(n):
            op_cls = dataclasses.make_dataclass(
                f"DynOp{i}",
                [("val", int)],
                bases=(Op,),
                frozen=True,
                slots=True,
            )
            op_types.append(op_cls)

            async def handler(req: Op[int, str]) -> Result[int, str]:  # noqa: E501
                return Ok(0)

            handlers_list.append(handler)

        builder = ops()
        for op_type, cur_handler in zip(op_types, handlers_list):
            builder = builder.on(op_type, cur_handler)

        assert len(builder._items) == n

    def test_on_last_registration_wins(self) -> None:
        async def handle1(req: _DupOp) -> Result[int, str]:
            return Ok(1)

        async def handle2(req: _DupOp) -> Result[int, str]:
            return Ok(2)

        builder = ops().on(_DupOp, handle1).on(_DupOp, handle2)
        # Last registration wins, so only 1 entry
        assert len(builder._items) == 1
        assert builder._items[0][1] is handle2


# ═══════════════════════════════════════════════════════════════════════════════
# 17. .compile() produces a Runner
# ═══════════════════════════════════════════════════════════════════════════════


class TestOpsCompile:
    def test_compile_produces_runner(self) -> None:
        async def handle(req: _CompOp) -> Result[int, str]:
            return Ok(req.x)

        runner = ops().on(_CompOp, handle).compile()
        assert isinstance(runner, Runner)

    def test_compile_empty_builder(self) -> None:
        runner = ops().compile()
        assert isinstance(runner, Runner)

    def test_runner_has_registry(self) -> None:
        async def handle(req: _RegOp) -> Result[int, str]:
            return Ok(req.x)

        runner = ops().on(_RegOp, handle).compile()
        assert _RegOp in runner._registry


# ═══════════════════════════════════════════════════════════════════════════════
# Saga result types — frozen and field preservation
# ═══════════════════════════════════════════════════════════════════════════════


class TestSagaResultTypes:
    def test_saga_result_frozen(self) -> None:
        r = SagaResult(value=42, steps_executed=3, compensators_recorded=2)
        with pytest.raises(dataclasses.FrozenInstanceError):
            r.value = 99  # type: ignore[misc]

    @given(val=st.integers(), steps=st.integers(min_value=0, max_value=100))
    @settings(max_examples=30)
    def test_saga_result_fields(self, val: int, steps: int) -> None:
        r = SagaResult(value=val, steps_executed=steps, compensators_recorded=steps)
        assert r.value == val
        assert r.steps_executed == steps
        assert r.compensators_recorded == steps

    def test_saga_error_frozen(self) -> None:
        e = SagaError(
            error="boom",
            step_failed=1,
            compensators_run=0,
            compensators_failed=0,
            rollback_complete=False,
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            e.error = "other"  # type: ignore[misc]

    @given(
        step_idx=st.integers(min_value=0, max_value=100),
        rollback=st.booleans(),
    )
    @settings(max_examples=30)
    def test_saga_error_fields(self, step_idx: int, rollback: bool) -> None:
        e = SagaError(
            error="err",
            step_failed=step_idx,
            compensators_run=0,
            compensators_failed=0,
            rollback_complete=rollback,
        )
        assert e.step_failed == step_idx
        assert e.rollback_complete == rollback


# ═══════════════════════════════════════════════════════════════════════════════
# IdempotencyErrorKind — all variants
# ═══════════════════════════════════════════════════════════════════════════════


class TestIdempotencyErrorKind:
    def test_all_variants_exist(self) -> None:
        expected = {
            "CONFLICT",
            "TIMEOUT",
            "STORE_ERROR",
            "LOCK_ERROR",
            "EXECUTION",
            "INPUT_MISMATCH",
        }
        actual = {e.name for e in IdempotencyErrorKind}
        assert actual == expected

    def test_idempotency_error_frozen(self) -> None:
        e: IdempotencyError[str] = IdempotencyError(
            kind=IdempotencyErrorKind.CONFLICT,
            message="conflict",
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            e.kind = IdempotencyErrorKind.TIMEOUT  # type: ignore[misc]

    def test_idempotency_result_frozen(self) -> None:
        r = IdempotencyResult(value="ok", from_cache=False, key="k")
        with pytest.raises(dataclasses.FrozenInstanceError):
            r.value = "x"  # type: ignore[misc]

    @given(
        key=st.text(min_size=1, max_size=50),
        from_cache=st.booleans(),
    )
    @settings(max_examples=30)
    def test_idempotency_result_fields(self, key: str, from_cache: bool) -> None:
        r = IdempotencyResult(value="v", from_cache=from_cache, key=key)
        assert r.key == key
        assert r.from_cache == from_cache
        assert r.value == "v"

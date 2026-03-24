# pyright: reportPrivateUsage=false
"""Property-based tests for saga execution — step, chain, composition types."""

from __future__ import annotations

import pytest
from kungfu import Result, Ok, Error, LazyCoroResult

from emergent.saga._types import (
    SagaStep,
    SagaResult,
    SagaError,
    Then,
    Parallel,
    Race,
)
from emergent.saga._step import step
from emergent.saga._compose import parallel, race
from emergent.saga._run import run, run_chain


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════


def make_ok_action(value: int) -> LazyCoroResult[int, str]:
    """Create an action that succeeds with the given value."""

    async def _action() -> Result[int, str]:
        return Ok(value)

    return LazyCoroResult(_action)


def make_fail_action(error: str) -> LazyCoroResult[int, str]:
    """Create an action that fails with the given error."""

    async def _action() -> Result[int, str]:
        return Error(error)

    return LazyCoroResult(_action)


class CompensationTracker:
    """Tracks which compensations have been called and with what values."""

    def __init__(self) -> None:
        self.calls: list[int] = []

    async def compensate(self, value: int) -> None:
        self.calls.append(value)


# ═══════════════════════════════════════════════════════════════════════════════
# Single Step Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestSingleStepSuccess:
    """Single step success: action returns Ok, result is Ok."""

    @pytest.mark.asyncio
    async def test_ok_action_produces_ok_result(self) -> None:
        s = step(make_ok_action(42))
        result = await run(s)

        assert isinstance(result, Ok)
        saga_result: SagaResult[int] = result.value
        assert saga_result.value == 42
        assert saga_result.steps_executed == 1

    @pytest.mark.asyncio
    async def test_ok_action_with_compensator_records_it(self) -> None:
        tracker = CompensationTracker()
        s = step(make_ok_action(99), compensate=tracker.compensate)
        result = await run(s)

        assert isinstance(result, Ok)
        assert result.value.compensators_recorded == 1
        # Compensator should NOT have been called (success path)
        assert tracker.calls == []


class TestSingleStepFailure:
    """Single step failure: action returns Error, result is Error."""

    @pytest.mark.asyncio
    async def test_error_action_produces_error_result(self) -> None:
        s = step(make_fail_action("something broke"))
        result = await run(s)

        assert isinstance(result, Error)
        saga_error: SagaError[str] = result.error
        assert saga_error.error == "something broke"
        assert saga_error.step_failed == 1
        assert saga_error.rollback_complete is True  # no compensators to run

    @pytest.mark.asyncio
    async def test_error_with_no_compensator(self) -> None:
        s = step(make_fail_action("fail"))
        result = await run(s)

        assert isinstance(result, Error)
        assert result.error.compensators_run == 0
        assert result.error.compensators_failed == 0


# ═══════════════════════════════════════════════════════════════════════════════
# Chain Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestChainBothSucceed:
    """Chain of 2 steps: both succeed -> Ok with final value."""

    @pytest.mark.asyncio
    async def test_chain_success(self) -> None:
        tracker1 = CompensationTracker()
        tracker2 = CompensationTracker()

        s1 = step(make_ok_action(10), compensate=tracker1.compensate)
        chain = s1.then(
            lambda v: step(make_ok_action(v + 5), compensate=tracker2.compensate)
        )

        result = await run_chain(chain)

        assert isinstance(result, Ok)
        assert result.value.value == 15
        assert result.value.steps_executed == 2
        # No compensators should have been called
        assert tracker1.calls == []
        assert tracker2.calls == []


class TestChainFirstFails:
    """Chain: first fails -> Error, no compensation needed (nothing succeeded)."""

    @pytest.mark.asyncio
    async def test_first_step_fails(self) -> None:
        tracker = CompensationTracker()

        s1 = step(make_fail_action("first broke"), compensate=tracker.compensate)
        chain = s1.then(
            lambda v: step(make_ok_action(v + 100))
        )

        result = await run_chain(chain)

        assert isinstance(result, Error)
        assert result.error.error == "first broke"
        assert result.error.step_failed == 1
        # Compensator was never recorded because action failed
        assert tracker.calls == []


class TestChainSecondFails:
    """Chain: second fails -> Error, compensation runs for first (which succeeded)."""

    @pytest.mark.asyncio
    async def test_second_step_fails_compensates_first(self) -> None:
        tracker1 = CompensationTracker()

        s1 = step(make_ok_action(42), compensate=tracker1.compensate)
        chain = s1.then(
            lambda v: step(make_fail_action("second broke"))
        )

        result = await run_chain(chain)

        assert isinstance(result, Error)
        assert result.error.error == "second broke"
        assert result.error.step_failed == 2
        # First step's compensator should have been called with the value 42
        assert tracker1.calls == [42]
        assert result.error.rollback_complete is True


# ═══════════════════════════════════════════════════════════════════════════════
# Composition Type Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestCompositionTypes:
    """step(action, compensate) creates SagaStep; .then creates Then;
    parallel/race create Parallel/Race."""

    def test_step_creates_saga_step(self) -> None:
        s = step(make_ok_action(1))
        assert isinstance(s, SagaStep)

    def test_step_with_compensator(self) -> None:
        tracker = CompensationTracker()
        comp_fn = tracker.compensate
        s = step(make_ok_action(1), compensate=comp_fn)
        assert isinstance(s, SagaStep)
        assert s.compensate is comp_fn

    def test_then_creates_then(self) -> None:
        s1 = step(make_ok_action(1))
        chain = s1.then(lambda v: step(make_ok_action(v + 1)))
        assert isinstance(chain, Then)
        assert chain.inner is s1

    def test_parallel_creates_parallel(self) -> None:
        s1 = step(make_ok_action(1))
        s2 = step(make_ok_action(2))
        par = parallel(s1, s2)
        assert isinstance(par, Parallel)
        assert len(par.sagas) == 2

    def test_race_creates_race(self) -> None:
        s1 = step(make_ok_action(1))
        s2 = step(make_ok_action(2))
        r = race(s1, s2)
        assert isinstance(r, Race)
        assert len(r.sagas) == 2


class TestSagaResultMetadata:
    """SagaResult and SagaError carry correct metadata."""

    @pytest.mark.asyncio
    async def test_success_metadata(self) -> None:
        tracker = CompensationTracker()
        s = step(make_ok_action(7), compensate=tracker.compensate)
        result = await run(s)

        assert isinstance(result, Ok)
        assert result.value.steps_executed == 1
        assert result.value.compensators_recorded == 1

    @pytest.mark.asyncio
    async def test_chain_success_metadata(self) -> None:
        t1 = CompensationTracker()
        t2 = CompensationTracker()

        chain = step(make_ok_action(1), compensate=t1.compensate).then(
            lambda v: step(make_ok_action(v * 2), compensate=t2.compensate)
        )
        result = await run_chain(chain)

        assert isinstance(result, Ok)
        assert result.value.steps_executed == 2
        assert result.value.compensators_recorded == 2

    @pytest.mark.asyncio
    async def test_error_metadata_tracks_compensator_counts(self) -> None:
        t1 = CompensationTracker()

        chain = step(make_ok_action(5), compensate=t1.compensate).then(
            lambda v: step(make_fail_action("boom"))
        )
        result = await run_chain(chain)

        assert isinstance(result, Error)
        assert result.error.compensators_run == 1
        assert result.error.compensators_failed == 0
        assert result.error.rollback_complete is True

"""Tests for saga runner — run, run_chain, run_compensators.

Covers: run_step, run_compensators, run (single step success/failure),
run_chain (success, inner failure, next failure), compensator recording
and rollback behavior.
"""

from __future__ import annotations

import pytest

from kungfu import Result, Ok, Error, LazyCoroResult

from emergent.saga._types import (
    SagaStep,
    Then,
    Parallel,
    Race,
)
from emergent.saga._run import (
    run,
    run_step,
    run_compensators,
    run_chain,
    run_parallel,
    run_race,
)


# ===============================================================================
# Helpers
# ===============================================================================


def make_step(
    value: str = "ok",
    error: str | None = None,
    compensate: bool = False,
    compensate_fail: bool = False,
) -> SagaStep[str, str]:
    """Create a SagaStep for testing."""

    async def action_fn() -> Result[str, str]:
        if error is not None:
            return Error(error)
        return Ok(value)

    comp_fn = None
    if compensate:
        if compensate_fail:
            async def failing_comp(val: str) -> None:
                raise RuntimeError(f"compensate failed for {val}")
            comp_fn = failing_comp
        else:
            async def good_comp(val: str) -> None:
                pass  # successful compensation
            comp_fn = good_comp

    return SagaStep(
        action=LazyCoroResult(action_fn),
        compensate=comp_fn,
    )


# ===============================================================================
# run_step
# ===============================================================================


class TestRunStep:
    @pytest.mark.asyncio
    async def test_success_records_compensator(self) -> None:
        compensators: list[tuple[str, object]] = []
        step = make_step(value="result", compensate=True)

        result = await run_step(step, compensators)  # type: ignore[arg-type]
        assert isinstance(result, Ok)
        assert result.value == "result"
        assert len(compensators) == 1

    @pytest.mark.asyncio
    async def test_success_no_compensator(self) -> None:
        compensators: list[tuple[str, object]] = []
        step = make_step(value="result", compensate=False)

        result = await run_step(step, compensators)  # type: ignore[arg-type]
        assert isinstance(result, Ok)
        assert len(compensators) == 0

    @pytest.mark.asyncio
    async def test_error_does_not_record_compensator(self) -> None:
        compensators: list[tuple[str, object]] = []
        step = make_step(error="fail", compensate=True)

        result = await run_step(step, compensators)  # type: ignore[arg-type]
        assert isinstance(result, Error)
        assert result.error == "fail"
        assert len(compensators) == 0


# ===============================================================================
# run_compensators
# ===============================================================================


class TestRunCompensators:
    @pytest.mark.asyncio
    async def test_empty_compensators(self) -> None:
        comp_run, comp_failed = await run_compensators([])
        assert comp_run == 0
        assert comp_failed == 0

    @pytest.mark.asyncio
    async def test_successful_compensators(self) -> None:
        async def comp(val: str) -> None:
            pass

        compensators = [("v1", comp), ("v2", comp)]
        comp_run, comp_failed = await run_compensators(compensators)  # type: ignore[arg-type]
        assert comp_run == 2
        assert comp_failed == 0

    @pytest.mark.asyncio
    async def test_failing_compensator(self) -> None:
        async def good_comp(val: str) -> None:
            pass

        async def bad_comp(val: str) -> None:
            raise RuntimeError("compensator exploded")

        compensators = [("v1", good_comp), ("v2", bad_comp)]
        comp_run, comp_failed = await run_compensators(compensators)  # type: ignore[arg-type]
        assert comp_run == 1
        assert comp_failed == 1

    @pytest.mark.asyncio
    async def test_compensators_run_in_reverse(self) -> None:
        order: list[str] = []

        async def comp_a(val: str) -> None:
            order.append("a")

        async def comp_b(val: str) -> None:
            order.append("b")

        compensators = [("first", comp_a), ("second", comp_b)]
        await run_compensators(compensators)  # type: ignore[arg-type]
        # Reverse order: second first, then first
        assert order == ["b", "a"]


# ===============================================================================
# run (single step)
# ===============================================================================


class TestRun:
    @pytest.mark.asyncio
    async def test_success(self) -> None:
        step = make_step(value="hello", compensate=True)
        result = await run(step)

        assert isinstance(result, Ok)
        assert result.value.value == "hello"
        assert result.value.steps_executed == 1
        assert result.value.compensators_recorded == 1

    @pytest.mark.asyncio
    async def test_success_no_compensator(self) -> None:
        step = make_step(value="hello")
        result = await run(step)

        assert isinstance(result, Ok)
        assert result.value.compensators_recorded == 0

    @pytest.mark.asyncio
    async def test_failure(self) -> None:
        step = make_step(error="oops")
        result = await run(step)

        assert isinstance(result, Error)
        assert result.error.error == "oops"
        assert result.error.step_failed == 1
        assert result.error.rollback_complete is True

    @pytest.mark.asyncio
    async def test_failure_with_compensators(self) -> None:
        """A step that fails doesn't record its own compensator."""
        step = make_step(error="fail", compensate=True)
        result = await run(step)

        assert isinstance(result, Error)
        assert result.error.compensators_run == 0
        assert result.error.compensators_failed == 0
        assert result.error.rollback_complete is True


# ===============================================================================
# run_chain (Then)
# ===============================================================================


class TestRunChain:
    @pytest.mark.asyncio
    async def test_chain_success(self) -> None:
        step1 = make_step(value="first", compensate=True)
        chain = Then(
            inner=step1,
            f=lambda v: make_step(value=f"second-after-{v}", compensate=True),
        )

        result = await run_chain(chain)  # type: ignore[arg-type]
        assert isinstance(result, Ok)
        assert result.value.value == "second-after-first"
        assert result.value.steps_executed == 2
        assert result.value.compensators_recorded == 2

    @pytest.mark.asyncio
    async def test_chain_inner_failure(self) -> None:
        step1 = make_step(error="inner-fail", compensate=True)
        chain = Then(
            inner=step1,
            f=lambda v: make_step(value="never-reached"),
        )

        result = await run_chain(chain)  # type: ignore[arg-type]
        assert isinstance(result, Error)
        assert result.error.error == "inner-fail"
        assert result.error.step_failed == 1

    @pytest.mark.asyncio
    async def test_chain_next_failure_runs_compensators(self) -> None:
        step1 = make_step(value="first", compensate=True)
        chain = Then(
            inner=step1,
            f=lambda v: make_step(error="second-fail", compensate=True),
        )

        result = await run_chain(chain)  # type: ignore[arg-type]
        assert isinstance(result, Error)
        assert result.error.error == "second-fail"
        assert result.error.step_failed == 2
        # step1 compensator should have run
        assert result.error.compensators_run >= 1
        assert result.error.rollback_complete is True


# ===============================================================================
# run_parallel
# ===============================================================================


class TestRunParallel:
    @pytest.mark.asyncio
    async def test_parallel_all_success(self) -> None:
        steps = (
            make_step(value="a", compensate=True),
            make_step(value="b", compensate=True),
            make_step(value="c"),
        )
        par = Parallel(sagas=steps)

        result = await run_parallel(par)
        assert isinstance(result, Ok)
        assert len(result.value.value) == 3
        assert set(result.value.value) == {"a", "b", "c"}
        assert result.value.steps_executed == 3

    @pytest.mark.asyncio
    async def test_parallel_one_failure(self) -> None:
        steps = (
            make_step(value="a", compensate=True),
            make_step(error="fail-b"),
            make_step(value="c", compensate=True),
        )
        par = Parallel(sagas=steps)

        result = await run_parallel(par)
        assert isinstance(result, Error)
        assert result.error.error == "fail-b"


# ===============================================================================
# run_race
# ===============================================================================


class TestRunRace:
    @pytest.mark.asyncio
    async def test_race_first_success(self) -> None:
        steps = (
            make_step(value="winner"),
            make_step(value="also-ok"),
        )
        race_expr = Race(sagas=steps)

        result = await run_race(race_expr)
        assert isinstance(result, Ok)
        assert result.value.steps_executed == 1

    @pytest.mark.asyncio
    async def test_race_all_fail(self) -> None:
        steps = (
            make_step(error="fail-a"),
            make_step(error="fail-b"),
        )
        race_expr = Race(sagas=steps)

        result = await run_race(race_expr)
        assert isinstance(result, Error)


# ===============================================================================
# Integration
# ===============================================================================


class TestSagaIntegration:
    @pytest.mark.asyncio
    async def test_chain_with_rollback_on_second_step(self) -> None:
        """Full scenario: step1 succeeds, step2 fails, step1 compensator runs."""
        rollback_log: list[str] = []

        async def comp1(val: str) -> None:
            rollback_log.append(f"undo:{val}")

        async def booked_action() -> Result[str, str]:
            return Ok("booked")

        step1 = SagaStep(
            action=LazyCoroResult(booked_action),
            compensate=comp1,
        )
        chain = Then(
            inner=step1,
            f=lambda v: make_step(error="payment-failed"),
        )

        result = await run_chain(chain)  # type: ignore[arg-type]
        assert isinstance(result, Error)
        assert result.error.error == "payment-failed"
        assert "undo:booked" in rollback_log

    @pytest.mark.asyncio
    async def test_compensator_failure_is_tracked(self) -> None:
        """Compensator that raises is tracked in failed count."""
        step1 = make_step(value="ok", compensate=True, compensate_fail=True)
        chain = Then(
            inner=step1,
            f=lambda v: make_step(error="boom"),
        )

        result = await run_chain(chain)  # type: ignore[arg-type]
        assert isinstance(result, Error)
        # The compensator for step1 should have failed
        assert result.error.compensators_failed >= 1
        assert result.error.rollback_complete is False

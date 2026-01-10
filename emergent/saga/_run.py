"""
Saga execution with automatic rollback.

Note: Uses combinators for parallel/race execution instead of raw asyncio.
"""

from __future__ import annotations

from combinators import parallel as C_parallel, race_ok, lift as L
from kungfu import Result, Ok, Error, LazyCoroResult

from emergent.saga._types import (
    SagaStep,
    SagaResult,
    SagaError,
    Then,
    Parallel,
    Race,
    CompensatorWithValue,
)

# ═══════════════════════════════════════════════════════════════════════════════
# Recorded Compensator
# ═══════════════════════════════════════════════════════════════════════════════

type RecordedCompensator[T] = tuple[T, CompensatorWithValue[T]]

# ═══════════════════════════════════════════════════════════════════════════════
# run_step() — Execute single step
# ═══════════════════════════════════════════════════════════════════════════════

async def run_step[T, E](
    step: SagaStep[T, E],
    compensators: list[RecordedCompensator[T]],
) -> Result[T, E]:
    """Execute single step, recording compensator on success."""
    result = await step.action
    match result:
        case Ok(value):
            if step.compensate is not None:
                compensators.append((value, step.compensate))
            return Ok(value)
        case Error(e):
            return Error(e)


# ═══════════════════════════════════════════════════════════════════════════════
# run_compensators() — Rollback
# ═══════════════════════════════════════════════════════════════════════════════

async def run_compensators[T](
    compensators: list[RecordedCompensator[T]],
) -> tuple[int, int]:
    """Run compensators in reverse. Returns (run, failed)."""
    comp_run = 0
    comp_failed = 0

    for value, comp in reversed(compensators):
        try:
            await comp(value)
            comp_run += 1
        except Exception:
            comp_failed += 1

    return comp_run, comp_failed


# ═══════════════════════════════════════════════════════════════════════════════
# run() — Execute Saga Step
# ═══════════════════════════════════════════════════════════════════════════════

async def run[T, E](
    saga: SagaStep[T, E],
) -> Result[SagaResult[T], SagaError[E]]:
    """
    Execute saga step with automatic rollback on failure.

    On success: returns SagaResult with value and metadata.
    On failure: runs compensators in reverse, returns SagaError.

    Example:
        from emergent import saga as S

        trip_saga = (
            S.step(book_flight, cancel_flight)
            .then(lambda f: S.step(book_hotel(f), cancel_hotel))
        )

        result = await S.run(trip_saga)

        match result:
            case Ok(r):
                print(f"Success: {r.value}")
            case Error(e):
                print(f"Failed at step {e.step_failed}")
    """
    compensators: list[RecordedCompensator[T]] = []

    result = await run_step(saga, compensators)

    match result:
        case Ok(value):
            return Ok(SagaResult(
                value=value,
                steps_executed=1,
                compensators_recorded=len(compensators),
            ))

        case Error(error):
            comp_run, comp_failed = await run_compensators(compensators)

            return Error(SagaError(
                error=error,
                step_failed=1,
                compensators_run=comp_run,
                compensators_failed=comp_failed,
                rollback_complete=comp_failed == 0,
            ))


# ═══════════════════════════════════════════════════════════════════════════════
# run_chain() — Execute Then chain
# ═══════════════════════════════════════════════════════════════════════════════

async def run_chain[T, U, E, E2](
    chain: Then[T, U, E, E2],
) -> Result[SagaResult[U], SagaError[E | E2]]:
    """
    Execute chained saga steps.

    Runs inner step, then applies f to get next step, and runs that.
    On any failure, compensators run in reverse.
    """
    compensators_t: list[RecordedCompensator[T]] = []
    compensators_u: list[RecordedCompensator[U]] = []
    steps = 0

    # Run inner step
    inner_result = await run_step(chain.inner, compensators_t)
    steps += 1

    match inner_result:
        case Ok(value):
            # Get next step
            next_step = chain.f(value)

            # Run next step
            next_result = await run_step(next_step, compensators_u)
            steps += 1

            match next_result:
                case Ok(final_value):
                    return Ok(SagaResult(
                        value=final_value,
                        steps_executed=steps,
                        compensators_recorded=len(compensators_t) + len(compensators_u),
                    ))

                case Error(e):
                    # Rollback next compensators first, then inner
                    comp_run1, comp_failed1 = await run_compensators(compensators_u)
                    comp_run2, comp_failed2 = await run_compensators(compensators_t)

                    return Error(SagaError(
                        error=e,
                        step_failed=steps,
                        compensators_run=comp_run1 + comp_run2,
                        compensators_failed=comp_failed1 + comp_failed2,
                        rollback_complete=(comp_failed1 + comp_failed2) == 0,
                    ))

        case Error(e):
            comp_run, comp_failed = await run_compensators(compensators_t)

            return Error(SagaError(
                error=e,
                step_failed=steps,
                compensators_run=comp_run,
                compensators_failed=comp_failed,
                rollback_complete=comp_failed == 0,
            ))


# ═══════════════════════════════════════════════════════════════════════════════
# run_parallel() — Execute Parallel
# ═══════════════════════════════════════════════════════════════════════════════

async def run_parallel[T, E](
    par: Parallel[T, E],
) -> Result[SagaResult[tuple[T, ...]], SagaError[E]]:
    """
    Execute saga steps in parallel.

    All must succeed. On any failure, compensators run for successful steps.

    Note: Uses combinators.parallel instead of asyncio.gather.
    """
    compensators: list[RecordedCompensator[T]] = []

    def make_op(s: SagaStep[T, E]) -> LazyCoroResult[Result[T, E], str]:
        """Wrap step execution into LazyCoroResult."""
        return L.catching_async(
            lambda step=s: run_step(step, compensators),
            on_error=str,
        )

    # Run all in parallel via combinators
    parallel_result = await C_parallel(*[make_op(s) for s in par.sagas])

    match parallel_result:
        case Error(_):
            # Parallel itself failed (shouldn't happen with catching_async)
            comp_run, comp_failed = await run_compensators(compensators)
            return Error(SagaError(
                error=par.sagas[0].action if par.sagas else None,  # type: ignore[arg-type]
                step_failed=0,
                compensators_run=comp_run,
                compensators_failed=comp_failed,
                rollback_complete=comp_failed == 0,
            ))
        case Ok(results):
            # results is list[Result[T, E]]
            errors = [r for r in results if isinstance(r, Error)]
            if errors:
                comp_run, comp_failed = await run_compensators(compensators)
                first_error = errors[0]

                return Error(SagaError(
                    error=first_error.value,
                    step_failed=len(par.sagas) - len(errors),
                    compensators_run=comp_run,
                    compensators_failed=comp_failed,
                    rollback_complete=comp_failed == 0,
                ))

            values = tuple(r.value for r in results if isinstance(r, Ok))
            return Ok(SagaResult(
                value=values,
                steps_executed=len(par.sagas),
                compensators_recorded=len(compensators),
            ))


# ═══════════════════════════════════════════════════════════════════════════════
# run_race() — Execute Race
# ═══════════════════════════════════════════════════════════════════════════════

async def run_race[T, E](
    race_expr: Race[T, E],
) -> Result[SagaResult[T], SagaError[E]]:
    """
    Race saga steps.

    First success wins. Pending tasks are cancelled.

    Note: Uses combinators.race_ok instead of asyncio.wait.
    """
    compensators: list[RecordedCompensator[T]] = []

    def make_op(s: SagaStep[T, E]) -> LazyCoroResult[T, E]:
        """Wrap step execution, unwrapping inner Result."""
        async def impl() -> Result[T, E]:
            step_result = await run_step(s, compensators)
            return step_result
        return LazyCoroResult(impl)

    # Race via combinators — first Ok wins
    race_result = await race_ok(*[make_op(s) for s in race_expr.sagas])

    match race_result:
        case Ok(value):
            return Ok(SagaResult(
                value=value,
                steps_executed=1,
                compensators_recorded=len(compensators),
            ))
        case Error(e):
            comp_run, comp_failed = await run_compensators(compensators)
            return Error(SagaError(
                error=e,
                step_failed=len(race_expr.sagas),
                compensators_run=comp_run,
                compensators_failed=comp_failed,
                rollback_complete=comp_failed == 0,
            ))


# ═══════════════════════════════════════════════════════════════════════════════
# Exports
# ═══════════════════════════════════════════════════════════════════════════════

__all__ = ("run", "run_chain", "run_parallel", "run_race")

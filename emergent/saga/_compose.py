"""
Saga composition operators.
"""

from __future__ import annotations

from emergent.saga._types import SagaStep, Parallel, Race

# ═══════════════════════════════════════════════════════════════════════════════
# parallel() — All Must Succeed
# ═══════════════════════════════════════════════════════════════════════════════


def parallel[T, E](
    *sagas: SagaStep[T, E],
) -> Parallel[T, E]:
    """
    Execute sagas in parallel, all must succeed.

    If any fails, others are cancelled and compensators run.

    Example:
        result = await S.run_parallel(
            S.parallel(
                S.step(book_flight, cancel_flight),
                S.step(book_hotel, cancel_hotel),
                S.step(book_car, cancel_car),
            )
        )
    """
    return Parallel(sagas=sagas)


# ═══════════════════════════════════════════════════════════════════════════════
# race() — First Success Wins
# ═══════════════════════════════════════════════════════════════════════════════


def race[T, E](
    *sagas: SagaStep[T, E],
) -> Race[T, E]:
    """
    Race sagas, first success wins.

    Pending sagas are cancelled on first success.

    Example:
        result = await S.run_race(
            S.race(
                S.step(book_via_api_1, cancel_1),
                S.step(book_via_api_2, cancel_2),
            )
        )
    """
    return Race(sagas=sagas)


# ═══════════════════════════════════════════════════════════════════════════════
# Exports
# ═══════════════════════════════════════════════════════════════════════════════

__all__ = ("parallel", "race")

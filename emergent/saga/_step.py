"""
Saga step creation.
"""

from __future__ import annotations

from collections.abc import Callable, Awaitable
from kungfu import LazyCoroResult
from combinators import lift as L

from emergent.saga._types import SagaStep, CompensatorWithValue

# ═══════════════════════════════════════════════════════════════════════════════
# step() — Primary Constructor
# ═══════════════════════════════════════════════════════════════════════════════


def step[T, E](
    action: LazyCoroResult[T, E],
    compensate: CompensatorWithValue[T] | None = None,
) -> SagaStep[T, E]:
    """
    Create a compensated saga step.

    Args:
        action: The operation to perform (LazyCoroResult)
        compensate: The compensation action if rollback needed

    Returns:
        SagaStep that can be chained with .then()

    Example:
        from emergent import saga as S
        from combinators import lift as L

        book = S.step(
            action=L.catching_async(
                lambda: api.book_flight(flight_id),
                on_error=lambda e: BookingError(str(e)),
            ),
            compensate=lambda booking: api.cancel_booking(booking.id),
        )

        # Chain steps
        trip = book.then(lambda b: S.step(
            action=L.catching_async(
                lambda: api.book_hotel(b.confirmation),
                on_error=lambda e: BookingError(str(e)),
            ),
            compensate=lambda h: api.cancel_hotel(h.id),
        ))
    """
    return SagaStep(action=action, compensate=compensate)


# ═══════════════════════════════════════════════════════════════════════════════
# from_async() — Create step from async callable
# ═══════════════════════════════════════════════════════════════════════════════


def from_async[T, E](
    action: Callable[[], Awaitable[T]],
    on_error: Callable[[Exception], E],
    compensate: CompensatorWithValue[T] | None = None,
) -> SagaStep[T, E]:
    """
    Create step from async callable with error handling.

    Example:
        S.from_async(
            lambda: api.book_flight(flight_id),
            on_error=lambda e: BookingError(str(e)),
            compensate=cancel_flight,
        )
    """
    return SagaStep(
        action=L.catching_async(action, on_error=on_error),
        compensate=compensate,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Exports
# ═══════════════════════════════════════════════════════════════════════════════

__all__ = ("step", "from_async")

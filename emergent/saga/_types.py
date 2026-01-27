"""
Saga types — core data structures.
"""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable, Awaitable
from kungfu import LazyCoroResult

# ═══════════════════════════════════════════════════════════════════════════════
# Compensator — Undo Action
# ═══════════════════════════════════════════════════════════════════════════════

type CompensatorWithValue[T] = Callable[[T], Awaitable[None]]
"""Compensation function that receives the action result and undoes it."""

type CompensatorVoid = Callable[[], Awaitable[None]]
"""Compensation function with no input."""

type AnyCompensator[T] = CompensatorWithValue[T] | CompensatorVoid
"""Either compensator type."""

# ═══════════════════════════════════════════════════════════════════════════════
# SagaStep — Single Step with Compensation
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class SagaStep[T, E]:
    """
    A single saga step: action + compensator.

    When action succeeds, compensator is recorded.
    If later step fails, compensators run in reverse.
    """

    action: LazyCoroResult[T, E]
    compensate: CompensatorWithValue[T] | None

    def then[U, E2](
        self,
        f: Callable[[T], SagaStep[U, E2]],
    ) -> Then[T, U, E, E2]:
        """Chain another saga step after this one."""
        return Then(self, f)


# ═══════════════════════════════════════════════════════════════════════════════
# Saga AST — Composition Operators
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Pure[T]:
    """Lift a value into saga."""

    value: T


@dataclass(frozen=True, slots=True)
class Then[T, U, E, E2]:
    """Sequential composition (monadic bind)."""

    inner: SagaStep[T, E]
    f: Callable[[T], SagaStep[U, E2]]


@dataclass(frozen=True, slots=True)
class Parallel[T, E]:
    """Parallel composition — all must succeed."""

    sagas: tuple[SagaStep[T, E], ...]


@dataclass(frozen=True, slots=True)
class Race[T, E]:
    """Race composition — first success wins."""

    sagas: tuple[SagaStep[T, E], ...]


# ═══════════════════════════════════════════════════════════════════════════════
# Result Types
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class SagaResult[T]:
    """Successful saga result with metadata."""

    value: T
    steps_executed: int
    compensators_recorded: int


@dataclass(frozen=True, slots=True)
class SagaError[E]:
    """Saga error with rollback status."""

    error: E
    step_failed: int
    compensators_run: int
    compensators_failed: int
    rollback_complete: bool


# ═══════════════════════════════════════════════════════════════════════════════
# Saga Type (union for run())
# ═══════════════════════════════════════════════════════════════════════════════

type SagaExpr[T, E] = (
    SagaStep[T, E] | Then[object, T, object, E] | Parallel[T, E] | Race[T, E]
)

# ═══════════════════════════════════════════════════════════════════════════════
# Exports
# ═══════════════════════════════════════════════════════════════════════════════

__all__ = (
    "CompensatorWithValue",
    "CompensatorVoid",
    "AnyCompensator",
    "SagaStep",
    "Pure",
    "Then",
    "Parallel",
    "Race",
    "SagaExpr",
    "SagaResult",
    "SagaError",
)

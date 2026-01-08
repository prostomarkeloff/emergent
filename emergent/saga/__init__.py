"""
Saga — distributed transactions with compensation.

    from emergent import saga as S

    saga = S.step(action, compensate).then(lambda v: S.step(action2, compensate2))
    result = await S.run_chain(saga)
"""

from __future__ import annotations

from emergent.saga._types import (
    CompensatorWithValue,
    CompensatorVoid,
    AnyCompensator,
    SagaStep,
    SagaResult,
    SagaError,
    Then,
    Parallel,
    Race,
)
from emergent.saga._step import step, from_async
from emergent.saga._run import run, run_chain, run_parallel, run_race
from emergent.saga._compose import parallel, race
from emergent.saga import policy

__all__ = (
    "CompensatorWithValue",
    "CompensatorVoid",
    "AnyCompensator",
    "SagaStep",
    "SagaResult",
    "SagaError",
    "Then",
    "Parallel",
    "Race",
    "step",
    "from_async",
    "run",
    "run_chain",
    "run_parallel",
    "run_race",
    "parallel",
    "race",
    "policy",
)

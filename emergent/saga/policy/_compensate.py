"""
Compensation policies.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

@dataclass(frozen=True, slots=True)
class AllOnFailurePolicy:
    """Compensate all completed steps on any failure."""
    pass

def all_on_failure() -> AllOnFailurePolicy:
    """Compensate all steps on failure."""
    return AllOnFailurePolicy()


@dataclass(frozen=True, slots=True)
class SequentialPolicy:
    """Run compensators sequentially (no parallelism)."""
    pass

def sequential() -> SequentialPolicy:
    """Run compensators one at a time."""
    return SequentialPolicy()


@dataclass(frozen=True, slots=True)
class ParallelPolicy:
    """Run compensators in parallel."""
    max_concurrent: int = 10

def parallel(max_concurrent: int = 10) -> ParallelPolicy:
    """Run compensators in parallel."""
    return ParallelPolicy(max_concurrent)


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Retry failed compensators."""
    times: int
    delay: timedelta

def retry(times: int = 3, delay: timedelta = timedelta(seconds=1)) -> RetryPolicy:
    """Retry compensators on failure."""
    return RetryPolicy(times, delay)


@dataclass(frozen=True, slots=True)
class SkipPolicy:
    """Skip compensation entirely."""
    pass

def skip() -> SkipPolicy:
    """No compensation."""
    return SkipPolicy()


__all__ = (
    "AllOnFailurePolicy",
    "all_on_failure",
    "SequentialPolicy",
    "sequential",
    "ParallelPolicy",
    "parallel",
    "RetryPolicy",
    "retry",
    "SkipPolicy",
    "skip",
)


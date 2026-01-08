"""
Graph execution policies.

Namespace: G.policy.*
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

# ═══════════════════════════════════════════════════════════════════════════════
# Policies
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True, slots=True)
class CacheAllPolicy:
    """Cache all node results."""
    pass

def cache_all() -> CacheAllPolicy:
    return CacheAllPolicy()


@dataclass(frozen=True, slots=True)
class ParallelMaxPolicy:
    """Limit parallel execution."""
    max_concurrent: int

def parallel_max(n: int) -> ParallelMaxPolicy:
    return ParallelMaxPolicy(n)


@dataclass(frozen=True, slots=True)
class TimeoutPolicy:
    """Timeout for resolution."""
    duration: timedelta

def timeout(seconds: float) -> TimeoutPolicy:
    return TimeoutPolicy(timedelta(seconds=seconds))


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Retry failed nodes."""
    times: int
    on: type[Exception] | None = None

def retry(times: int = 3, on: type[Exception] | None = None) -> RetryPolicy:
    return RetryPolicy(times, on)


# ═══════════════════════════════════════════════════════════════════════════════
# Exports
# ═══════════════════════════════════════════════════════════════════════════════

__all__ = (
    "CacheAllPolicy",
    "cache_all",
    "ParallelMaxPolicy",
    "parallel_max",
    "TimeoutPolicy",
    "timeout",
    "RetryPolicy",
    "retry",
)


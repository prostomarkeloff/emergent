"""
Timeout policy.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

@dataclass(frozen=True, slots=True)
class TimeoutPolicy:
    """Timeout for entire saga execution."""
    duration: timedelta

def timeout(seconds: float | None = None, duration: timedelta | None = None) -> TimeoutPolicy:
    """
    Set timeout for saga execution.
    
    Example:
        saga.policy(S.policy.timeout(seconds=60))
        saga.policy(S.policy.timeout(duration=timedelta(minutes=5)))
    """
    if duration is not None:
        return TimeoutPolicy(duration)
    if seconds is not None:
        return TimeoutPolicy(timedelta(seconds=seconds))
    raise ValueError("Must provide seconds or duration")


__all__ = ("TimeoutPolicy", "timeout")


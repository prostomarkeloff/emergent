"""
Saga execution policies.

Namespace: S.policy.*

Examples:
    saga.policy(S.policy.compensate.all_on_failure())
    saga.policy(S.policy.timeout(seconds=60))
"""

from __future__ import annotations

from emergent.saga.policy._compensate import (
    all_on_failure,
    sequential,
    parallel as parallel_compensate,
    retry,
    skip,
)
from emergent.saga.policy._timeout import timeout
from emergent.saga.policy._on_failure import continue_, abort


# Namespace objects
class compensate:
    """Compensation policies."""

    all_on_failure = staticmethod(all_on_failure)
    sequential = staticmethod(sequential)
    parallel = staticmethod(parallel_compensate)
    retry = staticmethod(retry)
    skip = staticmethod(skip)


class on_failure:
    """Failure handling policies."""

    continue_ = staticmethod(continue_)
    abort = staticmethod(abort)


__all__ = (
    "compensate",
    "on_failure",
    "timeout",
)

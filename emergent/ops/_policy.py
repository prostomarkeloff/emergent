"""
Ops policy types — thin configuration mapped onto existing primitives.

Reuse:
- Retry/timeout via `combinators.flow(...).retry(...).timeout(...)`.
- Idempotency via `emergent.idempotency` (Policy, Store, run_idempotent).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from emergent import idempotency as I


class RetryOn(Protocol):
    def __call__(self, err: object) -> bool: ...


@dataclass(frozen=True, slots=True)
class Retry:
    """Retry settings applied via combinators.flow().retry(...)."""
    times: int = 1
    backoff_initial: float = 0.1
    backoff_factor: float = 2.0
    backoff_max: float = 2.0
    jitter: bool = True
    retry_on: RetryOn | None = None


@dataclass(frozen=True, slots=True)
class Timeout:
    """Timeout budgets (seconds). Applied via combinators.flow().timeout(...)."""
    total: float | None = None
    di: float | None = None
    handler: float | None = None
    cancel_on_timeout: bool = True


# Idempotency concurrency shortcuts
WAIT = I.WAIT
FAIL = I.FAIL
FORCE = I.FORCE


@dataclass(frozen=True, slots=True)
class IdemSpec:
    """
    Idempotency specification for an op (reuses emergent.idempotency).

    - key: compute idempotency key from request
    - fingerprint: optional stable hash for collision detection
    - store: I.Store (Memory/SQLAlchemy/custom via store_from)
    - policy: I.Policy instance (WAIT/FAIL/FORCE, TTLs, etc.)
    """
    key: Callable[[object], str]
    policy: I.Policy
    store: I.Store[object] | None = None
    fingerprint: Callable[[object], str] | None = None


@dataclass(frozen=True, slots=True)
class Policy:
    """Full op policy; all fields are optional and reused from existing libs."""
    retry: Retry = Retry()
    timeout: Timeout = Timeout()
    idempotency: IdemSpec | None = None


__all__ = (
    "Retry",
    "Timeout",
    "IdemSpec",
    "Policy",
    "WAIT",
    "FAIL",
    "FORCE",
)

"""
Idempotency types — core data structures.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum, auto
from typing import Generic, TypeVar

T = TypeVar("T")
E = TypeVar("E")


# ═══════════════════════════════════════════════════════════════════════════════
# Record State — Operation Lifecycle
# ═══════════════════════════════════════════════════════════════════════════════


class RecordState(Enum):
    """
    State of an idempotency record.

    Lifecycle:
        PENDING → COMPLETED (success)
                → FAILED (error)
                → (expired/deleted)
    """

    PENDING = auto()
    COMPLETED = auto()
    FAILED = auto()


# ═══════════════════════════════════════════════════════════════════════════════
# Idempotency Record — Stored State
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class IdempotencyRecord(Generic[T, E]):
    """
    A stored idempotency record.

    Note: Generic over T (success type) and E (error type).
    Почему: Type safety — value только для COMPLETED, error только для FAILED.

    input_hash: Optional fingerprint of the original input.
    Зачем: Collision detection — разные inputs с одинаковым key.
    """

    key: str
    state: RecordState
    value: T | None
    error: E | None
    created_at: datetime
    expires_at: datetime | None
    input_hash: str | None = None

    @property
    def is_expired(self) -> bool:
        """Check if record has expired."""
        if self.expires_at is None:
            return False
        return datetime.now() > self.expires_at

    @property
    def is_pending(self) -> bool:
        return self.state == RecordState.PENDING

    @property
    def is_completed(self) -> bool:
        return self.state == RecordState.COMPLETED

    @property
    def is_failed(self) -> bool:
        return self.state == RecordState.FAILED


# ═══════════════════════════════════════════════════════════════════════════════
# Result Types
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class IdempotencyResult(Generic[T]):
    """
    Successful idempotency result with metadata.

    Note: from_cache indicates if result was cached vs freshly computed.
    """

    value: T
    from_cache: bool
    key: str


class IdempotencyErrorKind(Enum):
    """Kinds of idempotency errors."""

    CONFLICT = auto()  # Concurrent request with same key
    TIMEOUT = auto()  # Waiting for pending timed out
    STORE_ERROR = auto()  # Storage backend error
    LOCK_ERROR = auto()  # Failed to acquire lock
    EXECUTION = auto()  # Wrapped operation failed
    INPUT_MISMATCH = auto()  # Cached result has different input hash


@dataclass(frozen=True, slots=True)
class IdempotencyError(Generic[E]):
    """
    Idempotency operation error.

    Note: original_error содержит ошибку от wrapped operation (если EXECUTION).
    """

    kind: IdempotencyErrorKind
    message: str
    original_error: E | None = None


# ═══════════════════════════════════════════════════════════════════════════════
# Exports
# ═══════════════════════════════════════════════════════════════════════════════

__all__ = (
    "RecordState",
    "IdempotencyRecord",
    "IdempotencyResult",
    "IdempotencyError",
    "IdempotencyErrorKind",
)

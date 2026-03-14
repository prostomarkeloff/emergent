"""Idempotency storage helpers.

No separate Store protocol — just use generic storage with Record[T] as value type.

Usage:
    from emergent.wire.axis.storage import MemoryStorage
    from emergent.idempotency import Record, set_pending, set_completed

    storage = MemoryStorage[str, Record[str]]()

    await set_pending(storage, key, ttl)
    await set_completed(storage, key, value, ttl)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from kungfu import Result

from emergent.idempotency._types import RecordState, IdempotencyRecord
from emergent.wire.axis.storage import SetWithTTL, SetNX


# ═══════════════════════════════════════════════════════════════════════════════
# Record Type Alias
# ═══════════════════════════════════════════════════════════════════════════════


type Record[T] = IdempotencyRecord[T, Any]


# ═══════════════════════════════════════════════════════════════════════════════
# Store Error — Wrapper for graph error handling
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class StoreError:
    """Storage error wrapper for idempotency graphs."""

    message: str
    cause: object | None = None

    @classmethod
    def from_error(cls, err: object) -> StoreError:
        """Wrap any error as StoreError."""
        return cls(message=str(err), cause=err)


# ═══════════════════════════════════════════════════════════════════════════════
# Record Builders
# ═══════════════════════════════════════════════════════════════════════════════


def make_pending_record[T](
    key: str,
    ttl: timedelta | None,
    input_hash: str | None = None,
) -> Record[T]:
    """Create a PENDING record."""
    now = datetime.now(tz=timezone.utc)
    return IdempotencyRecord(
        key=key,
        state=RecordState.PENDING,
        value=None,
        error=None,
        created_at=now,
        expires_at=now + ttl if ttl else None,
        input_hash=input_hash,
    )


def make_completed_record[T](
    key: str,
    value: T,
    ttl: timedelta | None,
    *,
    created_at: datetime | None = None,
    input_hash: str | None = None,
) -> Record[T]:
    """Create a COMPLETED record."""
    now = datetime.now(tz=timezone.utc)
    return IdempotencyRecord(
        key=key,
        state=RecordState.COMPLETED,
        value=value,
        error=None,
        created_at=created_at or now,
        expires_at=now + ttl if ttl else None,
        input_hash=input_hash,
    )


def make_failed_record[T](
    key: str,
    error: Any,
    ttl: timedelta | None,
    *,
    created_at: datetime | None = None,
    input_hash: str | None = None,
) -> Record[T]:
    """Create a FAILED record."""
    now = datetime.now(tz=timezone.utc)
    return IdempotencyRecord(
        key=key,
        state=RecordState.FAILED,
        value=None,
        error=error,
        created_at=created_at or now,
        expires_at=now + ttl if ttl else None,
        input_hash=input_hash,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Domain Helper Functions — Work with any storage
# ═══════════════════════════════════════════════════════════════════════════════


async def set_pending[T, E](
    storage: SetNX[str, Record[T], E],
    key: str,
    ttl: timedelta | None,
    input_hash: str | None = None,
) -> Result[bool, E]:
    """Atomically set pending state via set_nx.

    Returns Ok(True) if set, Ok(False) if already exists.
    """
    record: Record[T] = make_pending_record(key, ttl, input_hash)
    return await storage.set_nx(key, record, ttl)


async def set_completed[T, E](
    storage: SetWithTTL[str, Record[T], E],
    key: str,
    value: T,
    ttl: timedelta | None,
    *,
    created_at: datetime | None = None,
    input_hash: str | None = None,
) -> Result[None, E]:
    """Store completed result."""
    record: Record[T] = make_completed_record(
        key, value, ttl, created_at=created_at, input_hash=input_hash
    )
    return await storage.set(key, record, ttl)


async def set_failed[T, E](
    storage: SetWithTTL[str, Record[T], E],
    key: str,
    error: Any,
    ttl: timedelta | None,
    *,
    created_at: datetime | None = None,
    input_hash: str | None = None,
) -> Result[None, E]:
    """Store failed result."""
    record: Record[T] = make_failed_record(
        key, error, ttl, created_at=created_at, input_hash=input_hash
    )
    return await storage.set(key, record, ttl)


# ═══════════════════════════════════════════════════════════════════════════════
# Exports
# ═══════════════════════════════════════════════════════════════════════════════


__all__ = (
    "Record",
    "StoreError",
    "make_pending_record",
    "make_completed_record",
    "make_failed_record",
    "set_pending",
    "set_completed",
    "set_failed",
)

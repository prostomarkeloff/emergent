"""
Idempotency store — typed storage protocol.

Store[T] — stores records with typed value T.
All methods return Result for explicit error handling.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol, Any, Generic, TypeVar, Callable, Awaitable

from kungfu import Result, Ok, Error

from emergent.idempotency._types import (
    RecordState,
    IdempotencyRecord,
)


T = TypeVar("T")
E = TypeVar("E")


# ═══════════════════════════════════════════════════════════════════════════════
# Store Error
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class StoreError:
    """Storage operation error."""

    message: str
    cause: Exception | None = None


# ═══════════════════════════════════════════════════════════════════════════════
# Store Protocol — Typed, Result-based
# ═══════════════════════════════════════════════════════════════════════════════


class Store(Protocol[T]):
    """
    Typed idempotency store protocol.

    Note: Generic over T — the type of value stored in completed records.
    All methods return Result for explicit error handling.

    Example — SQLAlchemy implementation:

        class PaymentStore(Store[Payment]):
            def __init__(self, session: AsyncSession):
                self.session = session

            async def get(self, key: str) -> Result[IdempotencyRecord[Payment, Any] | None, StoreError]:
                try:
                    row = await self.session.execute(
                        select(IdempotencyTable).where(IdempotencyTable.key == key)
                    )
                    if row := row.scalar_one_or_none():
                        return Ok(row.to_record())
                    return Ok(None)
                except Exception as e:
                    return Error(StoreError("Failed to get", e))

            # ... other methods
    """

    async def get(
        self, key: str
    ) -> Result[IdempotencyRecord[T, Any] | None, StoreError]:
        """Get existing record. Returns Ok(None) if not found."""
        ...

    async def set_pending(
        self,
        key: str,
        ttl: timedelta | None,
        input_hash: str | None = None,
    ) -> Result[bool, StoreError]:
        """
        Atomically set pending state.

        Returns Ok(True) if set, Ok(False) if already exists.
        Must be atomic (compare-and-swap).
        """
        ...

    async def set_completed(
        self,
        key: str,
        value: T,
        ttl: timedelta | None,
    ) -> Result[None, StoreError]:
        """Store completed result."""
        ...

    async def set_failed(
        self,
        key: str,
        error: Any,
        ttl: timedelta | None,
    ) -> Result[None, StoreError]:
        """Store failed result."""
        ...

    async def delete(self, key: str) -> Result[bool, StoreError]:
        """Delete record. Returns Ok(True) if existed."""
        ...


# ═══════════════════════════════════════════════════════════════════════════════
# Function-based Store Builder
# ═══════════════════════════════════════════════════════════════════════════════

type GetFn[T] = Callable[
    [str], Awaitable[Result[IdempotencyRecord[T, Any] | None, StoreError]]
]
type SetPendingFn = Callable[
    [str, timedelta | None, str | None], Awaitable[Result[bool, StoreError]]
]
type SetCompletedFn[T] = Callable[
    [str, T, timedelta | None], Awaitable[Result[None, StoreError]]
]
type SetFailedFn = Callable[
    [str, Any, timedelta | None], Awaitable[Result[None, StoreError]]
]
type DeleteFn = Callable[[str], Awaitable[Result[bool, StoreError]]]


@dataclass(frozen=True)
class FunctionalStore(Generic[T]):
    """
    Store built from functions.

    Example:
        store = store_from(
            get=my_repo.get_idempotency,
            set_pending=my_repo.create_pending,
            set_completed=my_repo.mark_completed,
            set_failed=my_repo.mark_failed,
            delete=my_repo.delete_record,
        )
    """

    _get: GetFn[T]
    _set_pending: SetPendingFn
    _set_completed: SetCompletedFn[T]
    _set_failed: SetFailedFn
    _delete: DeleteFn

    async def get(
        self, key: str
    ) -> Result[IdempotencyRecord[T, Any] | None, StoreError]:
        return await self._get(key)

    async def set_pending(
        self,
        key: str,
        ttl: timedelta | None,
        input_hash: str | None = None,
    ) -> Result[bool, StoreError]:
        return await self._set_pending(key, ttl, input_hash)

    async def set_completed(
        self,
        key: str,
        value: T,
        ttl: timedelta | None,
    ) -> Result[None, StoreError]:
        return await self._set_completed(key, value, ttl)

    async def set_failed(
        self,
        key: str,
        error: Any,
        ttl: timedelta | None,
    ) -> Result[None, StoreError]:
        return await self._set_failed(key, error, ttl)

    async def delete(self, key: str) -> Result[bool, StoreError]:
        return await self._delete(key)


def store_from(
    get: GetFn[T],
    set_pending: SetPendingFn,
    set_completed: SetCompletedFn[T],
    set_failed: SetFailedFn,
    delete: DeleteFn,
) -> FunctionalStore[T]:
    """
    Create Store from functions.

    Example:
        store = store_from(
            get=lambda key: repo.get_idempotency(key),
            set_pending=lambda key, ttl, hash: repo.create_pending(key, ttl, hash),
            set_completed=lambda key, val, ttl: repo.mark_completed(key, val, ttl),
            set_failed=lambda key, err, ttl: repo.mark_failed(key, err, ttl),
            delete=lambda key: repo.delete_record(key),
        )
    """
    return FunctionalStore(
        _get=get,
        _set_pending=set_pending,
        _set_completed=set_completed,
        _set_failed=set_failed,
        _delete=delete,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Memory Store — For Testing
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class _StoredRecord(Generic[T]):
    """Internal mutable record for MemoryStore."""

    key: str
    state: RecordState
    value: T | None
    error: Any
    created_at: datetime
    expires_at: datetime | None
    input_hash: str | None = None

    def to_record(self) -> IdempotencyRecord[T, Any]:
        return IdempotencyRecord(
            key=self.key,
            state=self.state,
            value=self.value,
            error=self.error,
            created_at=self.created_at,
            expires_at=self.expires_at,
            input_hash=self.input_hash,
        )


class MemoryStore(Generic[T]):
    """
    In-memory idempotency store.

    Note: Только для single-instance / тестов.
    Почему: Нет distributed lock, данные не переживут рестарт.
    """

    def __init__(self) -> None:
        self._records: dict[str, _StoredRecord[T]] = {}
        self._lock = asyncio.Lock()

    async def get(
        self, key: str
    ) -> Result[IdempotencyRecord[T, Any] | None, StoreError]:
        async with self._lock:
            record = self._records.get(key)
            if record is None:
                return Ok(None)

            if record.expires_at and datetime.now() > record.expires_at:
                del self._records[key]
                return Ok(None)

            return Ok(record.to_record())

    async def set_pending(
        self,
        key: str,
        ttl: timedelta | None,
        input_hash: str | None = None,
    ) -> Result[bool, StoreError]:
        async with self._lock:
            existing = self._records.get(key)
            if existing is not None:
                if existing.expires_at and datetime.now() > existing.expires_at:
                    del self._records[key]
                else:
                    return Ok(False)

            now = datetime.now()
            expires_at = now + ttl if ttl else None

            self._records[key] = _StoredRecord(
                key=key,
                state=RecordState.PENDING,
                value=None,
                error=None,
                created_at=now,
                expires_at=expires_at,
                input_hash=input_hash,
            )
            return Ok(True)

    async def set_completed(
        self,
        key: str,
        value: T,
        ttl: timedelta | None,
    ) -> Result[None, StoreError]:
        async with self._lock:
            existing = self._records.get(key)
            if existing is None:
                return Error(StoreError(f"No pending record for key: {key}"))

            now = datetime.now()
            expires_at = now + ttl if ttl else None

            existing.state = RecordState.COMPLETED
            existing.value = value
            existing.expires_at = expires_at
            return Ok(None)

    async def set_failed(
        self,
        key: str,
        error: Any,
        ttl: timedelta | None,
    ) -> Result[None, StoreError]:
        async with self._lock:
            existing = self._records.get(key)
            if existing is None:
                return Error(StoreError(f"No pending record for key: {key}"))

            now = datetime.now()
            expires_at = now + ttl if ttl else None

            existing.state = RecordState.FAILED
            existing.error = error
            existing.expires_at = expires_at
            return Ok(None)

    async def delete(self, key: str) -> Result[bool, StoreError]:
        async with self._lock:
            if key in self._records:
                del self._records[key]
                return Ok(True)
            return Ok(False)


# ═══════════════════════════════════════════════════════════════════════════════
# Exports
# ═══════════════════════════════════════════════════════════════════════════════

# Type alias for Store with Any value type
type StoreAny = Store[Any]


__all__ = (
    "StoreError",
    "Store",
    "StoreAny",
    "FunctionalStore",
    "store_from",
    "MemoryStore",
)

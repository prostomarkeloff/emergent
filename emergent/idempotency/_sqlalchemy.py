"""
SQLAlchemy integration — generic idempotency store for any model.

Usage:
    1. Add IdempotencyMixin to your model:

        class OrderTable(Base, IdempotencyMixin):
            __tablename__ = "orders"
            id: Mapped[str] = mapped_column(primary_key=True)
            customer_id: Mapped[str] = ...

    2. Create store with typed config:

        @dataclass
        class OrderConfig:
            order_id: str
            customer_id: str
            amount_cents: int

        store = SQLAlchemyStore(
            session_factory,
            model=OrderTable,
            to_pending=lambda key, cfg: OrderTable(
                id=cfg.order_id,
                idempotency_key=key,
                customer_id=cfg.customer_id,
                ...
            ),
        )

    3. Use:

        result = await (
            I.idempotent(process)
            .key(lambda req: req.key)
            .store(store.for_request(config))
            .build()
            .run(request)
        )
"""

from datetime import datetime, timedelta
from typing import Any, Protocol, TypeVar, Generic, Callable, cast, runtime_checkable

from sqlalchemy import select, String, DateTime, Text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.engine import CursorResult

from kungfu import Result, Ok, Error

from emergent.idempotency._types import IdempotencyRecord, RecordState
from emergent.idempotency._store import StoreError


# ═══════════════════════════════════════════════════════════════════════════════
# Idempotency Mixin — add to your SQLAlchemy model
# ═══════════════════════════════════════════════════════════════════════════════

class IdempotencyMixin:
    """
    Mixin for SQLAlchemy models with idempotency support.

    Adds columns:
    - idempotency_key: unique key for deduplication
    - idempotency_status: "pending" | "completed" | "failed"
    - idempotency_value: serialized result
    - idempotency_error: error message
    - idempotency_expires_at: optional TTL

    Example:
        class OrderTable(Base, IdempotencyMixin):
            __tablename__ = "orders"
            id: Mapped[str] = mapped_column(primary_key=True)
            # ... your fields ...
    """

    idempotency_key: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        unique=True,
        index=True,
    )

    idempotency_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="pending",
    )

    idempotency_value: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    idempotency_error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    idempotency_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Status enum
# ═══════════════════════════════════════════════════════════════════════════════

class IdempotencyStatus:
    """Status constants for idempotency_status column."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


# ═══════════════════════════════════════════════════════════════════════════════
# Protocol for idempotent models
# ═══════════════════════════════════════════════════════════════════════════════

@runtime_checkable
class IdempotentModel(Protocol):
    """Protocol for models with IdempotencyMixin."""

    @property
    def idempotency_key(self) -> str: ...
    @property
    def idempotency_status(self) -> str: ...
    @idempotency_status.setter
    def idempotency_status(self, value: str) -> None: ...
    @property
    def idempotency_value(self) -> str | None: ...
    @idempotency_value.setter
    def idempotency_value(self, value: str | None) -> None: ...
    @property
    def idempotency_error(self) -> str | None: ...
    @idempotency_error.setter
    def idempotency_error(self, value: str | None) -> None: ...
    @property
    def idempotency_expires_at(self) -> datetime | None: ...
    @idempotency_expires_at.setter
    def idempotency_expires_at(self, value: datetime | None) -> None: ...


M = TypeVar("M")
P = TypeVar("P")  # Pending data type


# ═══════════════════════════════════════════════════════════════════════════════
# Generic SQLAlchemy Store
# ═══════════════════════════════════════════════════════════════════════════════

class SQLAlchemyStore(Generic[M, P]):
    """
    Generic typed idempotency store for SQLAlchemy models.

    Type parameters:
        M: Model type (e.g., OrderTable)
        P: Pending data type (e.g., OrderPending dataclass)

    Example:
        @dataclass
        class OrderPending:
            order_id: str
            customer_id: str
            amount_cents: int

        store = SQLAlchemyStore(
            session_factory,
            model=OrderTable,
            to_pending=lambda key, data: OrderTable(
                id=data.order_id,
                idempotency_key=key,
                idempotency_status=IdempotencyStatus.PROCESSING,
                customer_id=data.customer_id,
                amount_cents=data.amount_cents,
                created_at=datetime.now(),
            ),
            to_insert=lambda m: sqlite_insert(OrderTable).values(...),
        )
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        model: type[M],
        to_pending: Callable[[str, P], M],
        to_insert: Callable[[M], Any],
    ) -> None:
        """
        Args:
            session_factory: SQLAlchemy async session factory
            model: Model class with IdempotencyMixin
            to_pending: Factory (key, pending_data) → pending model
            to_insert: Factory model → INSERT ... ON CONFLICT stmt
        """
        self._session_factory = session_factory
        self._model = model
        self._to_pending = to_pending
        self._to_insert = to_insert
        self._pending: P | None = None

    def with_pending(self, pending: P) -> "SQLAlchemyStore[M, P]":
        """
        Create store with pending data for this request.

        Example:
            store.with_pending(OrderPending(
                order_id="ord_123",
                customer_id="cust_456",
                amount_cents=9999,
            ))
        """
        new_store: SQLAlchemyStore[M, P] = SQLAlchemyStore(
            session_factory=self._session_factory,
            model=self._model,
            to_pending=self._to_pending,
            to_insert=self._to_insert,
        )
        new_store._pending = pending
        return new_store

    async def get(self, key: str) -> Result[IdempotencyRecord[str, str] | None, StoreError]:
        """Get record by idempotency_key."""
        try:
            async with self._session_factory() as session:
                stmt = select(self._model).where(
                    self._model.idempotency_key == key  # type: ignore[attr-defined]
                )
                result = await session.execute(stmt)
                row = result.scalar_one_or_none()

                if row is None:
                    return Ok(None)

                model = cast(IdempotentModel, row)

                # Check expiry
                if model.idempotency_expires_at and datetime.now() > model.idempotency_expires_at:
                    return Ok(None)

                return Ok(self._to_record(model))

        except Exception as e:
            return Error(StoreError(f"Failed to get: {e}", e))

    async def set_pending(
        self,
        key: str,
        ttl: timedelta | None,
        input_hash: str | None = None,
    ) -> Result[bool, StoreError]:
        """Create pending record atomically."""
        try:
            if self._pending is None:
                return Error(StoreError("Pending data not set. Call with_pending() first."))

            async with self._session_factory() as session:
                model = self._to_pending(key, self._pending)

                # Set expiry if TTL provided
                if ttl:
                    cast(IdempotentModel, model).idempotency_expires_at = datetime.now() + ttl

                stmt = self._to_insert(model)
                cursor = cast(CursorResult[Any], await session.execute(stmt))
                await session.commit()

                return Ok(cursor.rowcount > 0)

        except Exception as e:
            return Error(StoreError(f"Failed to set pending: {e}", e))

    async def set_completed(
        self,
        key: str,
        value: str,
        ttl: timedelta | None,
    ) -> Result[None, StoreError]:
        """Mark record as completed."""
        try:
            async with self._session_factory() as session:
                stmt = select(self._model).where(
                    self._model.idempotency_key == key  # type: ignore[attr-defined]
                )
                result = await session.execute(stmt)
                row = result.scalar_one_or_none()

                if row is None:
                    return Error(StoreError(f"Record not found: {key}"))

                model = cast(IdempotentModel, row)
                model.idempotency_status = IdempotencyStatus.COMPLETED
                model.idempotency_value = value
                if ttl:
                    model.idempotency_expires_at = datetime.now() + ttl

                await session.commit()
                return Ok(None)

        except Exception as e:
            return Error(StoreError(f"Failed to complete: {e}", e))

    async def set_failed(
        self,
        key: str,
        error: Any,
        ttl: timedelta | None,
    ) -> Result[None, StoreError]:
        """Mark record as failed."""
        try:
            async with self._session_factory() as session:
                stmt = select(self._model).where(
                    self._model.idempotency_key == key  # type: ignore[attr-defined]
                )
                result = await session.execute(stmt)
                row = result.scalar_one_or_none()

                if row is None:
                    return Error(StoreError(f"Record not found: {key}"))

                model = cast(IdempotentModel, row)
                model.idempotency_status = IdempotencyStatus.FAILED
                model.idempotency_error = str(error)
                if ttl:
                    model.idempotency_expires_at = datetime.now() + ttl

                await session.commit()
                return Ok(None)

        except Exception as e:
            return Error(StoreError(f"Failed to fail: {e}", e))

    async def delete(self, key: str) -> Result[bool, StoreError]:
        """Delete record."""
        try:
            async with self._session_factory() as session:
                stmt = select(self._model).where(
                    self._model.idempotency_key == key  # type: ignore[attr-defined]
                )
                result = await session.execute(stmt)
                row = result.scalar_one_or_none()

                if row is None:
                    return Ok(False)

                await session.delete(row)
                await session.commit()
                return Ok(True)

        except Exception as e:
            return Error(StoreError(f"Failed to delete: {e}", e))

    def _to_record(self, model: IdempotentModel) -> IdempotencyRecord[str, str]:
        """Convert model to IdempotencyRecord."""
        status = model.idempotency_status

        if status in (IdempotencyStatus.PENDING, IdempotencyStatus.PROCESSING):
            state = RecordState.PENDING
        elif status == IdempotencyStatus.COMPLETED:
            state = RecordState.COMPLETED
        elif status == IdempotencyStatus.FAILED:
            state = RecordState.FAILED
        else:
            state = RecordState.PENDING

        return IdempotencyRecord(
            key=model.idempotency_key,
            state=state,
            value=model.idempotency_value,
            error=model.idempotency_error,
            created_at=datetime.now(),
            expires_at=model.idempotency_expires_at,
            input_hash=None,
        )


__all__ = (
    "IdempotencyMixin",
    "IdempotencyStatus",
    "IdempotentModel",
    "SQLAlchemyStore",
)

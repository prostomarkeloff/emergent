"""Tests for SQLAlchemy idempotency store — SQLAlchemyStore, IdempotencyMixin,
IdempotencyStatus, IdempotentModel protocol.

Uses in-memory SQLite via aiosqlite.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import Integer, inspect as sa_inspect
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql.schema import ColumnDefault

from kungfu import Error, Ok

from emergent.idempotency._store import StoreError
from emergent.idempotency._types import IdempotencyRecord, RecordState
from emergent.idempotency.contrib._impls._sqlalchemy import (
    IdempotencyMixin,
    IdempotencyStatus,
    IdempotentModel,
    SQLAlchemyStore,
)


# ---------------------------------------------------------------------------
# Test model
# ---------------------------------------------------------------------------


class IdempotencyTestBase(DeclarativeBase):
    pass


class OrderTable(IdempotencyTestBase, IdempotencyMixin):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[str] = mapped_column(nullable=False)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_pending(key: str, customer_id: str) -> OrderTable:
    return OrderTable(
        customer_id=customer_id,
        idempotency_key=key,
        idempotency_status=IdempotencyStatus.PROCESSING,
    )


def _to_insert(model: OrderTable):
    """Build an INSERT ... ON CONFLICT DO NOTHING for SQLite."""
    values = {
        "customer_id": model.customer_id,
        "idempotency_key": model.idempotency_key,
        "idempotency_status": model.idempotency_status,
        "idempotency_value": model.idempotency_value,
        "idempotency_error": model.idempotency_error,
        "idempotency_expires_at": model.idempotency_expires_at,
    }
    stmt = sqlite_insert(OrderTable).values(**values)
    return stmt.on_conflict_do_nothing(index_elements=["idempotency_key"])


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def session() -> AsyncGenerator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    async with engine.begin() as conn:
        await conn.run_sync(IdempotencyTestBase.metadata.create_all)

    async with AsyncSession(engine, expire_on_commit=False) as sess:
        yield sess

    await engine.dispose()


@pytest_asyncio.fixture
async def store(session: AsyncSession) -> SQLAlchemyStore[OrderTable, str]:
    return SQLAlchemyStore(
        session=session,
        model=OrderTable,
        to_pending=_to_pending,
        to_insert=_to_insert,
    )


# ---------------------------------------------------------------------------
# IdempotencyMixin — columns exist on model
# ---------------------------------------------------------------------------


class TestIdempotencyMixin:
    def test_mixin_columns_exist(self) -> None:
        mapper = sa_inspect(OrderTable)
        col_names = {col.key for col in mapper.columns}
        expected = {
            "idempotency_key",
            "idempotency_status",
            "idempotency_value",
            "idempotency_error",
            "idempotency_expires_at",
        }
        assert expected.issubset(col_names)

    def test_idempotency_key_is_unique_and_indexed(self) -> None:
        mapper = sa_inspect(OrderTable)
        key_col = next(c for c in mapper.columns if c.key == "idempotency_key")
        assert key_col.unique is True
        assert key_col.index is True

    def test_idempotency_status_defaults_to_pending(self) -> None:
        mapper = sa_inspect(OrderTable)
        status_col = next(c for c in mapper.columns if c.key == "idempotency_status")
        default = status_col.default
        assert default is not None
        assert isinstance(default, ColumnDefault)
        assert default.arg == "pending"

    def test_nullable_columns(self) -> None:
        mapper = sa_inspect(OrderTable)
        value_col = next(c for c in mapper.columns if c.key == "idempotency_value")
        error_col = next(c for c in mapper.columns if c.key == "idempotency_error")
        expires_col = next(c for c in mapper.columns if c.key == "idempotency_expires_at")
        assert value_col.nullable is True
        assert error_col.nullable is True
        assert expires_col.nullable is True


# ---------------------------------------------------------------------------
# IdempotencyStatus — constants
# ---------------------------------------------------------------------------


class TestIdempotencyStatus:
    def test_pending(self) -> None:
        assert IdempotencyStatus.PENDING == "pending"

    def test_processing(self) -> None:
        assert IdempotencyStatus.PROCESSING == "processing"

    def test_completed(self) -> None:
        assert IdempotencyStatus.COMPLETED == "completed"

    def test_failed(self) -> None:
        assert IdempotencyStatus.FAILED == "failed"


# ---------------------------------------------------------------------------
# IdempotentModel protocol — isinstance check
# ---------------------------------------------------------------------------


class TestIdempotentModelProtocol:
    def test_order_table_is_idempotent_model(self) -> None:
        order = OrderTable(
            customer_id="cust-1",
            idempotency_key="key-1",
            idempotency_status="pending",
        )
        assert isinstance(order, IdempotentModel)

    def test_plain_object_is_not_idempotent_model(self) -> None:
        assert not isinstance("not-a-model", IdempotentModel)


# ---------------------------------------------------------------------------
# get()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_missing_key_returns_ok_none(
    store: SQLAlchemyStore[OrderTable, str],
) -> None:
    result = await store.get("nonexistent-key")
    assert isinstance(result, Ok)
    assert result.value is None


@pytest.mark.asyncio
async def test_get_existing_key_returns_ok_record(
    store: SQLAlchemyStore[OrderTable, str],
    session: AsyncSession,
) -> None:
    await store.set_pending("order-1", None, "cust-1")
    await session.commit()

    result = await store.get("order-1")
    assert isinstance(result, Ok)
    assert result.value is not None
    record = result.value
    assert isinstance(record, IdempotencyRecord)
    assert record.key == "order-1"
    assert record.state == RecordState.PENDING


@pytest.mark.asyncio
async def test_get_expired_key_returns_ok_none(
    store: SQLAlchemyStore[OrderTable, str],
    session: AsyncSession,
) -> None:
    # Set pending with a very short TTL already in the past
    past_ttl = timedelta(seconds=-1)
    await store.set_pending("expired-key", past_ttl, "cust-x")
    await session.commit()

    result = await store.get("expired-key")
    assert isinstance(result, Ok)
    assert result.value is None


# ---------------------------------------------------------------------------
# set_pending()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_pending_creates_record(
    store: SQLAlchemyStore[OrderTable, str],
    session: AsyncSession,
) -> None:
    result = await store.set_pending("pend-1", None, "cust-a")
    await session.commit()

    assert isinstance(result, Ok)
    assert result.value is True

    # Verify the record is in DB
    get_result = await store.get("pend-1")
    assert isinstance(get_result, Ok)
    assert get_result.value is not None
    assert get_result.value.key == "pend-1"
    assert get_result.value.state == RecordState.PENDING


@pytest.mark.asyncio
async def test_set_pending_with_ttl_sets_expires_at(
    store: SQLAlchemyStore[OrderTable, str],
    session: AsyncSession,
) -> None:
    ttl = timedelta(hours=1)
    before = datetime.now()
    result = await store.set_pending("pend-ttl", ttl, "cust-b")
    await session.commit()

    assert isinstance(result, Ok)

    get_result = await store.get("pend-ttl")
    assert isinstance(get_result, Ok)
    record = get_result.value
    assert record is not None
    assert record.expires_at is not None
    # The expires_at should be roughly now + 1 hour
    assert record.expires_at > before
    assert record.expires_at <= before + ttl + timedelta(seconds=5)


@pytest.mark.asyncio
async def test_set_pending_duplicate_key_returns_false(
    store: SQLAlchemyStore[OrderTable, str],
    session: AsyncSession,
) -> None:
    """ON CONFLICT DO NOTHING should return rowcount=0 for duplicates."""
    await store.set_pending("dup-key", None, "cust-1")
    await session.commit()

    result = await store.set_pending("dup-key", None, "cust-2")
    await session.commit()

    assert isinstance(result, Ok)
    assert result.value is False


# ---------------------------------------------------------------------------
# set_completed()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_completed_marks_as_completed(
    store: SQLAlchemyStore[OrderTable, str],
    session: AsyncSession,
) -> None:
    await store.set_pending("comp-1", None, "cust-a")
    await session.commit()

    result = await store.set_completed("comp-1", "result-value", None)
    await session.commit()

    assert isinstance(result, Ok)
    assert result.value is None

    get_result = await store.get("comp-1")
    assert isinstance(get_result, Ok)
    record = get_result.value
    assert record is not None
    assert record.state == RecordState.COMPLETED
    assert record.value == "result-value"


@pytest.mark.asyncio
async def test_set_completed_missing_key_returns_error(
    store: SQLAlchemyStore[OrderTable, str],
) -> None:
    result = await store.set_completed("no-such-key", "val", None)
    assert isinstance(result, Error)
    assert isinstance(result.error, StoreError)
    assert "Record not found" in result.error.message


@pytest.mark.asyncio
async def test_set_completed_with_ttl_sets_expires_at(
    store: SQLAlchemyStore[OrderTable, str],
    session: AsyncSession,
) -> None:
    await store.set_pending("comp-ttl", None, "cust-c")
    await session.commit()

    ttl = timedelta(minutes=30)
    before = datetime.now()
    await store.set_completed("comp-ttl", "done", ttl)
    await session.commit()

    get_result = await store.get("comp-ttl")
    assert isinstance(get_result, Ok)
    record = get_result.value
    assert record is not None
    assert record.expires_at is not None
    assert record.expires_at > before
    assert record.expires_at <= before + ttl + timedelta(seconds=5)


# ---------------------------------------------------------------------------
# set_failed()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_failed_marks_as_failed(
    store: SQLAlchemyStore[OrderTable, str],
    session: AsyncSession,
) -> None:
    await store.set_pending("fail-1", None, "cust-d")
    await session.commit()

    result = await store.set_failed("fail-1", "something broke", None)
    await session.commit()

    assert isinstance(result, Ok)
    assert result.value is None

    get_result = await store.get("fail-1")
    assert isinstance(get_result, Ok)
    record = get_result.value
    assert record is not None
    assert record.state == RecordState.FAILED
    assert record.error == "something broke"


@pytest.mark.asyncio
async def test_set_failed_missing_key_returns_error(
    store: SQLAlchemyStore[OrderTable, str],
) -> None:
    result = await store.set_failed("no-such-key", "err", None)
    assert isinstance(result, Error)
    assert isinstance(result.error, StoreError)
    assert "Record not found" in result.error.message


@pytest.mark.asyncio
async def test_set_failed_with_ttl_sets_expires_at(
    store: SQLAlchemyStore[OrderTable, str],
    session: AsyncSession,
) -> None:
    await store.set_pending("fail-ttl", None, "cust-e")
    await session.commit()

    ttl = timedelta(hours=2)
    before = datetime.now()
    await store.set_failed("fail-ttl", "timeout", ttl)
    await session.commit()

    get_result = await store.get("fail-ttl")
    assert isinstance(get_result, Ok)
    record = get_result.value
    assert record is not None
    assert record.expires_at is not None
    assert record.expires_at > before
    assert record.expires_at <= before + ttl + timedelta(seconds=5)


# ---------------------------------------------------------------------------
# delete()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_existing_key_returns_ok_true(
    store: SQLAlchemyStore[OrderTable, str],
    session: AsyncSession,
) -> None:
    await store.set_pending("del-1", None, "cust-f")
    await session.commit()

    result = await store.delete("del-1")
    await session.commit()

    assert isinstance(result, Ok)
    assert result.value is True

    # Verify it's gone
    get_result = await store.get("del-1")
    assert isinstance(get_result, Ok)
    assert get_result.value is None


@pytest.mark.asyncio
async def test_delete_missing_key_returns_ok_false(
    store: SQLAlchemyStore[OrderTable, str],
) -> None:
    result = await store.delete("nonexistent")
    assert isinstance(result, Ok)
    assert result.value is False


# ---------------------------------------------------------------------------
# _to_record() — status mapping
# ---------------------------------------------------------------------------


class _FakeIdempotentModel:
    """A simple IdempotentModel implementation for testing _to_record.

    Unlike OrderTable (which uses SQLAlchemy Mapped descriptors),
    this class directly satisfies the IdempotentModel protocol at
    the type level.
    """

    def __init__(
        self,
        *,
        idempotency_key: str = "key",
        idempotency_status: str = "pending",
        idempotency_value: str | None = None,
        idempotency_error: str | None = None,
        idempotency_expires_at: datetime | None = None,
    ) -> None:
        self.idempotency_key = idempotency_key
        self.idempotency_status = idempotency_status
        self.idempotency_value = idempotency_value
        self.idempotency_error = idempotency_error
        self.idempotency_expires_at = idempotency_expires_at


class _TestableStore(SQLAlchemyStore[OrderTable, str]):
    """Subclass that exposes _to_record for testing."""

    def to_record(self, model: IdempotentModel) -> IdempotencyRecord[str, str]:
        return self._to_record(model)


class TestToRecord:
    """Test the internal _to_record status mapping."""

    def _make_model(
        self,
        *,
        key: str = "key",
        status: str = "pending",
        value: str | None = None,
        error: str | None = None,
        expires_at: datetime | None = None,
    ) -> _FakeIdempotentModel:
        return _FakeIdempotentModel(
            idempotency_key=key,
            idempotency_status=status,
            idempotency_value=value,
            idempotency_error=error,
            idempotency_expires_at=expires_at,
        )

    def _store_instance(self) -> _TestableStore:
        # Session is unused for _to_record — pass a sentinel AsyncSession.
        # We use _TestableStore to expose _to_record publicly.
        return _TestableStore(
            session=AsyncSession(create_async_engine("sqlite+aiosqlite:///:memory:")),
            model=OrderTable,
            to_pending=_to_pending,
            to_insert=_to_insert,
        )

    def test_pending_maps_to_pending_state(self) -> None:
        s = self._store_instance()
        model = self._make_model(status=IdempotencyStatus.PENDING)
        record = s.to_record(model)
        assert record.state == RecordState.PENDING

    def test_processing_maps_to_pending_state(self) -> None:
        s = self._store_instance()
        model = self._make_model(status=IdempotencyStatus.PROCESSING)
        record = s.to_record(model)
        assert record.state == RecordState.PENDING

    def test_completed_maps_to_completed_state(self) -> None:
        s = self._store_instance()
        model = self._make_model(
            status=IdempotencyStatus.COMPLETED,
            value="result",
        )
        record = s.to_record(model)
        assert record.state == RecordState.COMPLETED
        assert record.value == "result"

    def test_failed_maps_to_failed_state(self) -> None:
        s = self._store_instance()
        model = self._make_model(
            status=IdempotencyStatus.FAILED,
            error="something went wrong",
        )
        record = s.to_record(model)
        assert record.state == RecordState.FAILED
        assert record.error == "something went wrong"

    def test_unknown_status_maps_to_pending_state(self) -> None:
        s = self._store_instance()
        model = self._make_model(status="some_unknown_status")
        record = s.to_record(model)
        assert record.state == RecordState.PENDING

    def test_record_key_matches_model_key(self) -> None:
        s = self._store_instance()
        model = self._make_model(key="my-unique-key")
        record = s.to_record(model)
        assert record.key == "my-unique-key"

    def test_record_expires_at_preserved(self) -> None:
        s = self._store_instance()
        future = datetime.now() + timedelta(hours=1)
        model = self._make_model(expires_at=future)
        record = s.to_record(model)
        assert record.expires_at == future

    def test_record_input_hash_always_none(self) -> None:
        s = self._store_instance()
        model = self._make_model()
        record = s.to_record(model)
        assert record.input_hash is None

    def test_record_is_idempotency_record(self) -> None:
        s = self._store_instance()
        model = self._make_model()
        record = s.to_record(model)
        assert isinstance(record, IdempotencyRecord)

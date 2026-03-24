"""Tests for emergent.idempotency._store.

Covers:
    - StoreError dataclass and from_error factory
    - make_pending_record: creates PENDING records with correct state, TTL, hash
    - make_completed_record: creates COMPLETED records with value, TTL, created_at
    - make_failed_record: creates FAILED records with error, TTL, created_at
    - set_pending: async helper using SetNX
    - set_completed: async helper using SetWithTTL
    - set_failed: async helper using SetWithTTL
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from kungfu import Ok, Some

from emergent.idempotency._store import (  # pyright: ignore[reportPrivateUsage]
    Record,
    StoreError,
    make_pending_record,
    make_completed_record,
    make_failed_record,
    set_pending,
    set_completed,
    set_failed,
)
from emergent.idempotency._types import RecordState
from emergent.wire.axis.storage import MemoryStorage


# ═══════════════════════════════════════════════════════════════════════════════
# StoreError
# ═══════════════════════════════════════════════════════════════════════════════


class TestStoreError:
    def test_store_error_creation(self) -> None:
        err = StoreError(message="connection failed")
        assert err.message == "connection failed"
        assert err.cause is None

    def test_store_error_with_cause(self) -> None:
        cause = RuntimeError("timeout")
        err = StoreError(message="storage error", cause=cause)
        assert err.message == "storage error"
        assert err.cause is cause

    def test_store_error_is_frozen(self) -> None:
        err = StoreError(message="test")
        with pytest.raises(AttributeError):
            err.message = "changed"  # type: ignore[misc]

    def test_from_error_wraps_exception(self) -> None:
        original = ValueError("invalid key")
        err = StoreError.from_error(original)
        assert err.message == "invalid key"
        assert err.cause is original

    def test_from_error_wraps_string(self) -> None:
        err = StoreError.from_error("simple error")
        assert err.message == "simple error"
        assert err.cause == "simple error"


# ═══════════════════════════════════════════════════════════════════════════════
# make_pending_record
# ═══════════════════════════════════════════════════════════════════════════════


class TestMakePendingRecord:
    def test_creates_pending_state(self) -> None:
        record: Record[str] = make_pending_record("key1", ttl=None)
        assert record.state == RecordState.PENDING
        assert record.key == "key1"
        assert record.value is None
        assert record.error is None
        assert record.input_hash is None

    def test_pending_with_ttl(self) -> None:
        ttl = timedelta(seconds=60)
        before = datetime.now(tz=timezone.utc)
        record: Record[str] = make_pending_record("key1", ttl=ttl)
        after = datetime.now(tz=timezone.utc)

        assert record.expires_at is not None
        assert before + ttl <= record.expires_at <= after + ttl

    def test_pending_without_ttl(self) -> None:
        record: Record[str] = make_pending_record("key1", ttl=None)
        assert record.expires_at is None

    def test_pending_with_input_hash(self) -> None:
        record: Record[str] = make_pending_record("key1", ttl=None, input_hash="abc123")
        assert record.input_hash == "abc123"

    def test_pending_created_at_is_now(self) -> None:
        before = datetime.now(tz=timezone.utc)
        record: Record[str] = make_pending_record("key1", ttl=None)
        after = datetime.now(tz=timezone.utc)
        assert before <= record.created_at <= after

    def test_pending_is_pending_property(self) -> None:
        record: Record[str] = make_pending_record("key1", ttl=None)
        assert record.is_pending is True
        assert record.is_completed is False
        assert record.is_failed is False


# ═══════════════════════════════════════════════════════════════════════════════
# make_completed_record
# ═══════════════════════════════════════════════════════════════════════════════


class TestMakeCompletedRecord:
    def test_creates_completed_state(self) -> None:
        record = make_completed_record("key1", "result_value", ttl=None)
        assert record.state == RecordState.COMPLETED
        assert record.key == "key1"
        assert record.value == "result_value"
        assert record.error is None

    def test_completed_with_ttl(self) -> None:
        ttl = timedelta(hours=1)
        before = datetime.now(tz=timezone.utc)
        record = make_completed_record("key1", 42, ttl=ttl)
        after = datetime.now(tz=timezone.utc)

        assert record.expires_at is not None
        assert before + ttl <= record.expires_at <= after + ttl

    def test_completed_without_ttl(self) -> None:
        record = make_completed_record("key1", "val", ttl=None)
        assert record.expires_at is None

    def test_completed_with_custom_created_at(self) -> None:
        custom_time = datetime(2024, 1, 1, 12, 0, 0)
        record = make_completed_record(
            "key1", "val", ttl=None, created_at=custom_time
        )
        assert record.created_at == custom_time

    def test_completed_without_created_at_uses_now(self) -> None:
        before = datetime.now(tz=timezone.utc)
        record = make_completed_record("key1", "val", ttl=None)
        after = datetime.now(tz=timezone.utc)
        assert before <= record.created_at <= after

    def test_completed_with_input_hash(self) -> None:
        record = make_completed_record(
            "key1", "val", ttl=None, input_hash="hash456"
        )
        assert record.input_hash == "hash456"

    def test_completed_is_completed_property(self) -> None:
        record = make_completed_record("key1", "val", ttl=None)
        assert record.is_completed is True
        assert record.is_pending is False
        assert record.is_failed is False


# ═══════════════════════════════════════════════════════════════════════════════
# make_failed_record
# ═══════════════════════════════════════════════════════════════════════════════


class TestMakeFailedRecord:
    def test_creates_failed_state(self) -> None:
        record: Record[str] = make_failed_record("key1", "some error", ttl=None)
        assert record.state == RecordState.FAILED
        assert record.key == "key1"
        assert record.value is None
        assert record.error == "some error"

    def test_failed_with_ttl(self) -> None:
        ttl = timedelta(minutes=5)
        before = datetime.now(tz=timezone.utc)
        record: Record[str] = make_failed_record("key1", "err", ttl=ttl)
        after = datetime.now(tz=timezone.utc)

        assert record.expires_at is not None
        assert before + ttl <= record.expires_at <= after + ttl

    def test_failed_without_ttl(self) -> None:
        record: Record[str] = make_failed_record("key1", "err", ttl=None)
        assert record.expires_at is None

    def test_failed_with_custom_created_at(self) -> None:
        custom_time = datetime(2024, 6, 15, 9, 30, 0)
        record: Record[str] = make_failed_record(
            "key1", "err", ttl=None, created_at=custom_time
        )
        assert record.created_at == custom_time

    def test_failed_with_input_hash(self) -> None:
        record: Record[str] = make_failed_record(
            "key1", "err", ttl=None, input_hash="hash789"
        )
        assert record.input_hash == "hash789"

    def test_failed_is_failed_property(self) -> None:
        record: Record[str] = make_failed_record("key1", "err", ttl=None)
        assert record.is_failed is True
        assert record.is_pending is False
        assert record.is_completed is False


# ═══════════════════════════════════════════════════════════════════════════════
# set_pending (async)
# ═══════════════════════════════════════════════════════════════════════════════


class TestSetPending:
    @pytest.mark.asyncio
    async def test_set_pending_returns_true_on_new_key(self) -> None:
        storage: MemoryStorage[str, Record[str]] = MemoryStorage()
        result = await set_pending(storage, "key1", ttl=None)
        assert result == Ok(True)

    @pytest.mark.asyncio
    async def test_set_pending_returns_false_on_existing_key(self) -> None:
        storage: MemoryStorage[str, Record[str]] = MemoryStorage()
        await set_pending(storage, "key1", ttl=None)
        result = await set_pending(storage, "key1", ttl=None)
        assert result == Ok(False)

    @pytest.mark.asyncio
    async def test_set_pending_stores_pending_record(self) -> None:
        storage: MemoryStorage[str, Record[str]] = MemoryStorage()
        await set_pending(storage, "key1", ttl=timedelta(seconds=60))

        get_result = await storage.get("key1")
        match get_result:
            case Ok(Some(record)):
                assert record.state == RecordState.PENDING
                assert record.key == "key1"
            case _:
                pytest.fail("Expected Ok(Some(record))")

    @pytest.mark.asyncio
    async def test_set_pending_with_input_hash(self) -> None:
        storage: MemoryStorage[str, Record[str]] = MemoryStorage()
        await set_pending(storage, "key1", ttl=None, input_hash="myhash")

        get_result = await storage.get("key1")
        match get_result:
            case Ok(Some(record)):
                assert record.input_hash == "myhash"
            case _:
                pytest.fail("Expected Ok(Some(record))")


# ═══════════════════════════════════════════════════════════════════════════════
# set_completed (async)
# ═══════════════════════════════════════════════════════════════════════════════


class TestSetCompleted:
    @pytest.mark.asyncio
    async def test_set_completed_stores_value(self) -> None:
        storage: MemoryStorage[str, Record[str]] = MemoryStorage()
        result = await set_completed(storage, "key1", "my_value", ttl=None)
        assert result == Ok(None)

        get_result = await storage.get("key1")
        match get_result:
            case Ok(Some(record)):
                assert record.state == RecordState.COMPLETED
                assert record.value == "my_value"
            case _:
                pytest.fail("Expected Ok(Some(record))")

    @pytest.mark.asyncio
    async def test_set_completed_overwrites_existing(self) -> None:
        storage: MemoryStorage[str, Record[str]] = MemoryStorage()
        await set_pending(storage, "key1", ttl=None)
        await set_completed(storage, "key1", "done", ttl=None)

        get_result = await storage.get("key1")
        match get_result:
            case Ok(Some(record)):
                assert record.state == RecordState.COMPLETED
                assert record.value == "done"
            case _:
                pytest.fail("Expected Ok(Some(record))")

    @pytest.mark.asyncio
    async def test_set_completed_with_created_at(self) -> None:
        storage: MemoryStorage[str, Record[str]] = MemoryStorage()
        custom_time = datetime(2024, 1, 1)
        await set_completed(
            storage, "key1", "val", ttl=None, created_at=custom_time
        )

        get_result = await storage.get("key1")
        match get_result:
            case Ok(Some(record)):
                assert record.created_at == custom_time
            case _:
                pytest.fail("Expected Ok(Some(record))")

    @pytest.mark.asyncio
    async def test_set_completed_with_input_hash(self) -> None:
        storage: MemoryStorage[str, Record[str]] = MemoryStorage()
        await set_completed(
            storage, "key1", "val", ttl=None, input_hash="hash_c"
        )

        get_result = await storage.get("key1")
        match get_result:
            case Ok(Some(record)):
                assert record.input_hash == "hash_c"
            case _:
                pytest.fail("Expected Ok(Some(record))")


# ═══════════════════════════════════════════════════════════════════════════════
# set_failed (async)
# ═══════════════════════════════════════════════════════════════════════════════


class TestSetFailed:
    @pytest.mark.asyncio
    async def test_set_failed_stores_error(self) -> None:
        storage: MemoryStorage[str, Record[str]] = MemoryStorage()
        result = await set_failed(storage, "key1", "error_msg", ttl=None)
        assert result == Ok(None)

        get_result = await storage.get("key1")
        match get_result:
            case Ok(Some(record)):
                assert record.state == RecordState.FAILED
                assert record.error == "error_msg"
                assert record.value is None
            case _:
                pytest.fail("Expected Ok(Some(record))")

    @pytest.mark.asyncio
    async def test_set_failed_with_ttl(self) -> None:
        storage: MemoryStorage[str, Record[str]] = MemoryStorage()
        await set_failed(
            storage, "key1", "err", ttl=timedelta(seconds=300)
        )

        get_result = await storage.get("key1")
        match get_result:
            case Ok(Some(record)):
                assert record.state == RecordState.FAILED
            case _:
                pytest.fail("Expected Ok(Some(record))")

    @pytest.mark.asyncio
    async def test_set_failed_with_created_at(self) -> None:
        storage: MemoryStorage[str, Record[str]] = MemoryStorage()
        custom_time = datetime(2024, 3, 15)
        await set_failed(
            storage, "key1", "err", ttl=None, created_at=custom_time
        )

        get_result = await storage.get("key1")
        match get_result:
            case Ok(Some(record)):
                assert record.created_at == custom_time
            case _:
                pytest.fail("Expected Ok(Some(record))")

    @pytest.mark.asyncio
    async def test_set_failed_with_input_hash(self) -> None:
        storage: MemoryStorage[str, Record[str]] = MemoryStorage()
        await set_failed(
            storage, "key1", "err", ttl=None, input_hash="hash_f"
        )

        get_result = await storage.get("key1")
        match get_result:
            case Ok(Some(record)):
                assert record.input_hash == "hash_f"
            case _:
                pytest.fail("Expected Ok(Some(record))")

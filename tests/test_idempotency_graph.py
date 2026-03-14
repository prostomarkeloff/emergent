"""Tests for idempotency graph — comprehensive coverage of all nodes and outcomes.

Covers: SpecNode, FetchRecordNode, CompletedRecordNode, FailedRecordNode,
PendingRecordNode, NoRecordNode, StoreErrorNode, ValidatedInputNode,
IdempotencyOutcome (all cases), FinalResultNode, run_idempotent.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from nodnod import NodeError
from kungfu import Result, Ok, Error, Some, Nothing

from emergent.idempotency._types import (
    IdempotencyRecord,
    RecordState,
    IdempotencyErrorKind,
)
from emergent.idempotency._store import StoreError
from emergent.idempotency._policy import Policy, OnPending
from emergent.idempotency._graph import (
    IdempotencySpec,
    SpecNode,
    FetchRecordNode,
    CompletedRecordNode,
    FailedRecordNode,
    PendingRecordNode,
    NoRecordNode,
    StoreErrorNode,
    ValidatedInputNode,
    OutcomeOk,
    OutcomeError,
    FinalResultNode,
    run_idempotent,
)


# ===============================================================================
# Helper: Fake storage for testing
# ===============================================================================


class FakeStorage:
    """Minimal storage mock for idempotency tests."""

    def __init__(
        self,
        get_result: Result[Some[IdempotencyRecord[str, str]] | Nothing, str] | None = None,
        set_result: Result[None, str] | None = None,
        set_nx_result: Result[bool, str] | None = None,
        delete_result: Result[None, str] | None = None,
    ) -> None:
        self._get_result = get_result if get_result is not None else Ok(Nothing())
        self._set_result = set_result if set_result is not None else Ok(None)
        self._set_nx_result = set_nx_result if set_nx_result is not None else Ok(True)
        self._delete_result = delete_result if delete_result is not None else Ok(None)
        self.get_calls: list[str] = []
        self.set_calls: list[tuple[str, object]] = []
        self.delete_calls: list[str] = []
        self.set_nx_calls: list[tuple[str, object]] = []

    async def get(self, key: str) -> Result[Some[IdempotencyRecord[str, str]] | Nothing, str]:
        self.get_calls.append(key)
        return self._get_result  # type: ignore[return-value]

    async def set(self, key: str, value: object, ttl: timedelta | None = None) -> Result[None, str]:
        self.set_calls.append((key, value))
        return self._set_result  # type: ignore[return-value]

    async def delete(self, key: str) -> Result[None, str]:
        self.delete_calls.append(key)
        return self._delete_result  # type: ignore[return-value]

    async def set_nx(self, key: str, value: object, ttl: timedelta | None = None) -> Result[bool, str]:
        self.set_nx_calls.append((key, value))
        return self._set_nx_result  # type: ignore[return-value]


def make_record(
    key: str = "test-key",
    state: RecordState = RecordState.COMPLETED,
    value: str | None = "result",
    error: str | None = None,
    expired: bool = False,
    input_hash: str | None = None,
) -> IdempotencyRecord[str, str]:
    now = datetime.now(tz=timezone.utc)
    expires_at = now - timedelta(hours=1) if expired else now + timedelta(hours=1)
    return IdempotencyRecord(
        key=key,
        state=state,
        value=value,
        error=error,
        created_at=now,
        expires_at=expires_at,
        input_hash=input_hash,
    )


def _noop_operation(_val: str) -> None:
    """No-op operation for tests that don't need a real one."""
    return None


def make_spec(
    key: str = "test-key",
    storage: FakeStorage | None = None,
    policy: Policy | None = None,
    input_hash: str | None = None,
    operation: object | None = None,
) -> IdempotencySpec:
    return IdempotencySpec(
        key=key,
        input_value="test-input",
        operation=operation or _noop_operation,
        storage=storage or FakeStorage(),  # type: ignore[arg-type]
        policy=policy or Policy(),
        input_hash=input_hash,
    )


# ===============================================================================
# SpecNode
# ===============================================================================


class TestSpecNode:
    def test_init(self) -> None:
        spec = make_spec()
        node = SpecNode(spec)
        assert node.spec is spec

    def test_compose(self) -> None:
        spec = make_spec()
        node = SpecNode.__compose__(spec)
        assert node.spec is spec


# ===============================================================================
# FetchRecordNode
# ===============================================================================


class TestFetchRecordNode:
    @pytest.mark.asyncio
    async def test_fetch_found_record(self) -> None:
        record = make_record()
        storage = FakeStorage(get_result=Ok(Some(record)))
        spec = make_spec(storage=storage)
        spec_node = SpecNode(spec)

        fetch_node = await FetchRecordNode.__compose__(spec_node)
        assert fetch_node.record is record
        assert fetch_node.spec is spec
        assert fetch_node.store_error is None

    @pytest.mark.asyncio
    async def test_fetch_no_record(self) -> None:
        storage = FakeStorage(get_result=Ok(Nothing()))
        spec = make_spec(storage=storage)
        spec_node = SpecNode(spec)

        fetch_node = await FetchRecordNode.__compose__(spec_node)
        assert fetch_node.record is None
        assert fetch_node.store_error is None

    @pytest.mark.asyncio
    async def test_fetch_store_error(self) -> None:
        storage = FakeStorage(get_result=Error("connection failed"))
        spec = make_spec(storage=storage)
        spec_node = SpecNode(spec)

        fetch_node = await FetchRecordNode.__compose__(spec_node)
        assert fetch_node.record is None
        assert fetch_node.store_error is not None
        assert "connection failed" in fetch_node.store_error.message


# ===============================================================================
# CompletedRecordNode
# ===============================================================================


class TestCompletedRecordNode:
    def test_compose_success(self) -> None:
        record = make_record(state=RecordState.COMPLETED)
        spec = make_spec()
        fetch = FetchRecordNode(record=record, spec=spec)

        node = CompletedRecordNode.__compose__(fetch)
        assert node.record is record
        assert node.spec is spec

    def test_compose_no_record_raises(self) -> None:
        spec = make_spec()
        fetch = FetchRecordNode(record=None, spec=spec)

        with pytest.raises(NodeError):
            CompletedRecordNode.__compose__(fetch)

    def test_compose_not_completed_raises(self) -> None:
        record = make_record(state=RecordState.PENDING)
        spec = make_spec()
        fetch = FetchRecordNode(record=record, spec=spec)

        with pytest.raises(NodeError):
            CompletedRecordNode.__compose__(fetch)

    def test_compose_expired_raises(self) -> None:
        record = make_record(state=RecordState.COMPLETED, expired=True)
        spec = make_spec()
        fetch = FetchRecordNode(record=record, spec=spec)

        with pytest.raises(NodeError):
            CompletedRecordNode.__compose__(fetch)


# ===============================================================================
# FailedRecordNode
# ===============================================================================


class TestFailedRecordNode:
    def test_compose_success(self) -> None:
        record = make_record(state=RecordState.FAILED, error="fail reason")
        spec = make_spec()
        fetch = FetchRecordNode(record=record, spec=spec)

        node = FailedRecordNode.__compose__(fetch)
        assert node.record is record

    def test_compose_no_record_raises(self) -> None:
        spec = make_spec()
        fetch = FetchRecordNode(record=None, spec=spec)

        with pytest.raises(NodeError):
            FailedRecordNode.__compose__(fetch)

    def test_compose_not_failed_raises(self) -> None:
        record = make_record(state=RecordState.COMPLETED)
        spec = make_spec()
        fetch = FetchRecordNode(record=record, spec=spec)

        with pytest.raises(NodeError):
            FailedRecordNode.__compose__(fetch)

    def test_compose_expired_raises(self) -> None:
        record = make_record(state=RecordState.FAILED, expired=True)
        spec = make_spec()
        fetch = FetchRecordNode(record=record, spec=spec)

        with pytest.raises(NodeError):
            FailedRecordNode.__compose__(fetch)


# ===============================================================================
# PendingRecordNode
# ===============================================================================


class TestPendingRecordNode:
    def test_compose_success(self) -> None:
        record = make_record(state=RecordState.PENDING)
        spec = make_spec()
        fetch = FetchRecordNode(record=record, spec=spec)

        node = PendingRecordNode.__compose__(fetch)
        assert node.record is record

    def test_compose_no_record_raises(self) -> None:
        spec = make_spec()
        fetch = FetchRecordNode(record=None, spec=spec)

        with pytest.raises(NodeError):
            PendingRecordNode.__compose__(fetch)

    def test_compose_not_pending_raises(self) -> None:
        record = make_record(state=RecordState.COMPLETED)
        spec = make_spec()
        fetch = FetchRecordNode(record=record, spec=spec)

        with pytest.raises(NodeError):
            PendingRecordNode.__compose__(fetch)


# ===============================================================================
# NoRecordNode
# ===============================================================================


class TestNoRecordNode:
    def test_compose_no_record(self) -> None:
        spec = make_spec()
        fetch = FetchRecordNode(record=None, spec=spec)

        node = NoRecordNode.__compose__(fetch)
        assert node.spec is spec

    def test_compose_expired_record(self) -> None:
        record = make_record(state=RecordState.COMPLETED, expired=True)
        spec = make_spec()
        fetch = FetchRecordNode(record=record, spec=spec)

        node = NoRecordNode.__compose__(fetch)
        assert node.spec is spec

    def test_compose_active_record_raises(self) -> None:
        record = make_record(state=RecordState.COMPLETED)
        spec = make_spec()
        fetch = FetchRecordNode(record=record, spec=spec)

        with pytest.raises(NodeError):
            NoRecordNode.__compose__(fetch)

    def test_compose_store_error_raises(self) -> None:
        spec = make_spec()
        fetch = FetchRecordNode(
            record=None,
            spec=spec,
            store_error=StoreError(message="db down"),
        )

        with pytest.raises(NodeError):
            NoRecordNode.__compose__(fetch)


# ===============================================================================
# StoreErrorNode
# ===============================================================================


class TestStoreErrorNode:
    def test_compose_with_error(self) -> None:
        spec = make_spec()
        error = StoreError(message="db down", cause=Exception("timeout"))
        fetch = FetchRecordNode(record=None, spec=spec, store_error=error)

        node = StoreErrorNode.__compose__(fetch)
        assert node.error is error
        assert node.spec is spec

    def test_compose_without_error_raises(self) -> None:
        spec = make_spec()
        fetch = FetchRecordNode(record=None, spec=spec)

        with pytest.raises(NodeError):
            StoreErrorNode.__compose__(fetch)


# ===============================================================================
# ValidatedInputNode
# ===============================================================================


class TestValidatedInputNode:
    def test_compose_no_input_hash_skips_validation(self) -> None:
        record = make_record(state=RecordState.COMPLETED, input_hash="abc")
        spec = make_spec(input_hash=None)
        completed = CompletedRecordNode(record=record, spec=spec)

        node = ValidatedInputNode.__compose__(completed)
        assert node.completed is completed

    def test_compose_no_record_hash_accepts(self) -> None:
        record = make_record(state=RecordState.COMPLETED, input_hash=None)
        spec = make_spec(input_hash="abc")
        completed = CompletedRecordNode(record=record, spec=spec)

        node = ValidatedInputNode.__compose__(completed)
        assert node.completed is completed

    def test_compose_matching_hash_accepts(self) -> None:
        record = make_record(state=RecordState.COMPLETED, input_hash="abc123")
        spec = make_spec(input_hash="abc123")
        completed = CompletedRecordNode(record=record, spec=spec)

        node = ValidatedInputNode.__compose__(completed)
        assert node.completed is completed

    def test_compose_mismatched_hash_raises(self) -> None:
        record = make_record(state=RecordState.COMPLETED, input_hash="abc")
        spec = make_spec(input_hash="xyz")
        completed = CompletedRecordNode(record=record, spec=spec)

        with pytest.raises(NodeError):
            ValidatedInputNode.__compose__(completed)


# ===============================================================================
# Outcome Types
# ===============================================================================


class TestOutcomeTypes:
    def test_outcome_ok(self) -> None:
        outcome = OutcomeOk(value="result", from_cache=True, key="k")
        assert outcome.value == "result"
        assert outcome.from_cache is True
        assert outcome.key == "k"

    def test_outcome_error(self) -> None:
        outcome = OutcomeError(
            kind=IdempotencyErrorKind.CONFLICT,
            message="conflict",
            original_error=None,
        )
        assert outcome.kind == IdempotencyErrorKind.CONFLICT
        assert outcome.message == "conflict"


# ===============================================================================
# FinalResultNode
# ===============================================================================


class TestFinalResultNode:
    def test_to_result_ok(self) -> None:
        outcome = OutcomeOk(value="success", from_cache=False, key="k")
        node = FinalResultNode(outcome)
        result = node.to_result()
        assert isinstance(result, Ok)
        assert result.value.value == "success"
        assert result.value.from_cache is False
        assert result.value.key == "k"

    def test_to_result_error(self) -> None:
        outcome = OutcomeError(
            kind=IdempotencyErrorKind.CONFLICT,
            message="conflict",
            original_error=None,
        )
        node = FinalResultNode(outcome)
        result = node.to_result()
        assert isinstance(result, Error)
        assert result.error.kind == IdempotencyErrorKind.CONFLICT
        assert result.error.message == "conflict"


# ===============================================================================
# run_idempotent — Integration Tests
# ===============================================================================


class TestRunIdempotentNewExecution:
    @pytest.mark.asyncio
    async def test_new_execution_success(self) -> None:
        """No existing record, operation succeeds."""

        async def operation(input_val: str) -> Result[str, str]:
            return Ok(f"processed:{input_val}")

        storage = FakeStorage(
            get_result=Ok(Nothing()),
            set_nx_result=Ok(True),
            set_result=Ok(None),
        )
        spec = IdempotencySpec(
            key="new-key",
            input_value="input",
            operation=operation,
            storage=storage,  # type: ignore[arg-type]
            policy=Policy(),
        )

        result = await run_idempotent(spec)
        assert isinstance(result, Ok)
        assert result.value.value == "processed:input"
        assert result.value.from_cache is False

    @pytest.mark.asyncio
    async def test_new_execution_operation_returns_error(self) -> None:
        """No existing record, operation returns Error."""

        async def operation(input_val: str) -> Result[str, str]:
            return Error("op failed")

        storage = FakeStorage(
            get_result=Ok(Nothing()),
            set_nx_result=Ok(True),
            delete_result=Ok(None),
        )
        spec = IdempotencySpec(
            key="fail-key",
            input_value="input",
            operation=operation,
            storage=storage,  # type: ignore[arg-type]
            policy=Policy(),
        )

        result = await run_idempotent(spec)
        assert isinstance(result, Error)
        assert result.error.kind == IdempotencyErrorKind.EXECUTION

    @pytest.mark.asyncio
    async def test_new_execution_operation_raises_exception(self) -> None:
        """No existing record, operation raises."""

        async def operation(input_val: str) -> Result[str, str]:
            raise RuntimeError("boom")

        storage = FakeStorage(
            get_result=Ok(Nothing()),
            set_nx_result=Ok(True),
            delete_result=Ok(None),
        )
        spec = IdempotencySpec(
            key="raise-key",
            input_value="input",
            operation=operation,
            storage=storage,  # type: ignore[arg-type]
            policy=Policy(),
        )

        result = await run_idempotent(spec)
        assert isinstance(result, Error)
        assert result.error.kind == IdempotencyErrorKind.EXECUTION
        assert "boom" in result.error.message


class TestRunIdempotentCachedResult:
    @pytest.mark.asyncio
    async def test_returns_cached_completed(self) -> None:
        """Completed record exists, returns cached."""
        record = make_record(state=RecordState.COMPLETED, value="cached-val")
        storage = FakeStorage(get_result=Ok(Some(record)))
        spec = IdempotencySpec(
            key="cached-key",
            input_value="input",
            operation=_noop_operation,
            storage=storage,  # type: ignore[arg-type]
            policy=Policy(),
        )

        result = await run_idempotent(spec)
        assert isinstance(result, Ok)
        assert result.value.value == "cached-val"
        assert result.value.from_cache is True

    @pytest.mark.asyncio
    async def test_returns_cached_failed(self) -> None:
        """Failed record exists, returns cached error."""
        record = make_record(state=RecordState.FAILED, error="past failure")
        storage = FakeStorage(get_result=Ok(Some(record)))
        spec = IdempotencySpec(
            key="fail-key",
            input_value="input",
            operation=_noop_operation,
            storage=storage,  # type: ignore[arg-type]
            policy=Policy(),
        )

        result = await run_idempotent(spec)
        assert isinstance(result, Error)
        assert result.error.kind == IdempotencyErrorKind.EXECUTION


class TestRunIdempotentPendingConflict:
    @pytest.mark.asyncio
    async def test_pending_with_fail_policy(self) -> None:
        """Pending record + FAIL policy => CONFLICT error."""
        record = make_record(state=RecordState.PENDING)
        storage = FakeStorage(get_result=Ok(Some(record)))
        policy = Policy().with_on_pending(OnPending.FAIL)
        spec = IdempotencySpec(
            key="pending-key",
            input_value="input",
            operation=_noop_operation,
            storage=storage,  # type: ignore[arg-type]
            policy=policy,
        )

        result = await run_idempotent(spec)
        assert isinstance(result, Error)
        assert result.error.kind == IdempotencyErrorKind.CONFLICT


class TestRunIdempotentStoreError:
    @pytest.mark.asyncio
    async def test_store_error_on_get(self) -> None:
        """Storage get() returns Error."""
        storage = FakeStorage(get_result=Error("storage down"))
        spec = IdempotencySpec(
            key="error-key",
            input_value="input",
            operation=_noop_operation,
            storage=storage,  # type: ignore[arg-type]
            policy=Policy(),
        )

        result = await run_idempotent(spec)
        assert isinstance(result, Error)
        assert result.error.kind == IdempotencyErrorKind.STORE_ERROR


class TestRunIdempotentSetNxConflict:
    @pytest.mark.asyncio
    async def test_race_set_nx_false_then_completed(self) -> None:
        """set_nx returns False (race), then get returns completed record."""
        completed_record = make_record(state=RecordState.COMPLETED, value="raced-value")

        call_count = 0

        class RaceStorage(FakeStorage):
            async def get(self, key: str) -> Result[Some[IdempotencyRecord[str, str]] | Nothing, str]:
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    return Ok(Nothing())  # First get: no record
                return Ok(Some(completed_record))  # Second get: race winner completed

            async def set_nx(self, key: str, value: object, ttl: timedelta | None = None) -> Result[bool, str]:
                return Ok(False)  # Lost the race

        storage = RaceStorage()
        spec = IdempotencySpec(
            key="race-key",
            input_value="input",
            operation=_noop_operation,
            storage=storage,  # type: ignore[arg-type]
            policy=Policy(),
        )

        result = await run_idempotent(spec)
        assert isinstance(result, Ok)
        assert result.value.value == "raced-value"
        assert result.value.from_cache is True


class TestRunIdempotentPersistFailed:
    @pytest.mark.asyncio
    async def test_persist_failed_stores_error(self) -> None:
        """Operation fails with persist_failed=True stores the error."""

        async def operation(input_val: str) -> Result[str, str]:
            return Error("op-error")

        storage = FakeStorage(
            get_result=Ok(Nothing()),
            set_nx_result=Ok(True),
            set_result=Ok(None),
        )
        policy = Policy().with_store_failed(True)
        spec = IdempotencySpec(
            key="persist-fail-key",
            input_value="input",
            operation=operation,
            storage=storage,  # type: ignore[arg-type]
            policy=policy,
        )

        result = await run_idempotent(spec)
        assert isinstance(result, Error)
        assert result.error.kind == IdempotencyErrorKind.EXECUTION
        # Should have called storage.set to persist the failed record
        assert len(storage.set_calls) > 0

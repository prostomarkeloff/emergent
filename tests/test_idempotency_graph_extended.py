"""Extended tests for emergent/idempotency/_graph.py — coverage gaps.

Covers the uncovered @case methods in IdempotencyOutcome:
- pending_wait: WAIT policy polling loop (completed, failed, disappeared, timeout, store error)
- pending_force: FORCE policy (delete + re-execute, error paths)
- input_mismatch: INPUT_MISMATCH case
- execute_new: store error on set_completed, persist_failed with custom TTL
- store_error: direct StoreErrorNode outcome
- cached_failed: FailedRecordNode outcome
- Race conditions: set_nx returns False with non-completed record
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from kungfu import Result, Ok, Error, Some, Nothing

from emergent.idempotency._types import (
    IdempotencyRecord,
    RecordState,
    IdempotencyErrorKind,
)
from emergent.idempotency._policy import Policy, OnPending
from emergent.idempotency._graph import (
    IdempotencySpec,
    OutcomeOk,
    OutcomeError,
    FinalResultNode,
    run_idempotent,
)


# ============================================================================
# Helpers
# ============================================================================


async def _noop_operation(_: str) -> Result[str, str]:
    """Typed no-op operation for specs that don't need a real operation."""
    return Ok("")


class FakeStorage:
    """Configurable fake storage for idempotency tests."""

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
    now = datetime.now()
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


# ============================================================================
# PendingWaitNode — WAIT policy
# ============================================================================


class TestPendingWait:
    @pytest.mark.asyncio
    async def test_wait_then_completed(self) -> None:
        """Pending record with WAIT policy; storage returns completed after polling."""
        completed_record = make_record(state=RecordState.COMPLETED, value="waited-result")
        call_count = 0

        class PollingStorage(FakeStorage):
            async def get(self, key: str) -> Result[Some[IdempotencyRecord[str, str]] | Nothing, str]:
                nonlocal call_count
                call_count += 1
                if call_count <= 1:
                    # First call: FetchRecordNode sees pending
                    return Ok(Some(make_record(state=RecordState.PENDING)))
                # Second call (during wait): completed
                return Ok(Some(completed_record))

        storage = PollingStorage()
        policy = Policy().with_on_pending(OnPending.WAIT).with_wait_timeout(seconds=2)
        spec = IdempotencySpec(
            key="wait-key",
            input_value="input",
            operation=_noop_operation,
            storage=storage,  # type: ignore[arg-type]
            policy=policy,
        )

        result = await run_idempotent(spec)
        assert isinstance(result, Ok)
        assert result.value.value == "waited-result"
        assert result.value.from_cache is True

    @pytest.mark.asyncio
    async def test_wait_then_failed(self) -> None:
        """Pending record with WAIT policy; storage returns failed after polling."""
        call_count = 0

        class PollingStorage(FakeStorage):
            async def get(self, key: str) -> Result[Some[IdempotencyRecord[str, str]] | Nothing, str]:
                nonlocal call_count
                call_count += 1
                if call_count <= 1:
                    return Ok(Some(make_record(state=RecordState.PENDING)))
                return Ok(Some(make_record(state=RecordState.FAILED, error="op-fail")))

        storage = PollingStorage()
        policy = Policy().with_on_pending(OnPending.WAIT).with_wait_timeout(seconds=2)
        spec = IdempotencySpec(
            key="wait-fail-key",
            input_value="input",
            operation=_noop_operation,
            storage=storage,  # type: ignore[arg-type]
            policy=policy,
        )

        result = await run_idempotent(spec)
        assert isinstance(result, Error)
        assert result.error.kind == IdempotencyErrorKind.EXECUTION

    @pytest.mark.asyncio
    async def test_wait_record_disappeared(self) -> None:
        """Pending record with WAIT policy; record disappears during wait."""
        call_count = 0

        class DisappearStorage(FakeStorage):
            async def get(self, key: str) -> Result[Some[IdempotencyRecord[str, str]] | Nothing, str]:
                nonlocal call_count
                call_count += 1
                if call_count <= 1:
                    return Ok(Some(make_record(state=RecordState.PENDING)))
                return Ok(Nothing())

        storage = DisappearStorage()
        policy = Policy().with_on_pending(OnPending.WAIT).with_wait_timeout(seconds=2)
        spec = IdempotencySpec(
            key="disappear-key",
            input_value="input",
            operation=_noop_operation,
            storage=storage,  # type: ignore[arg-type]
            policy=policy,
        )

        result = await run_idempotent(spec)
        assert isinstance(result, Error)
        assert result.error.kind == IdempotencyErrorKind.STORE_ERROR
        assert "disappeared" in result.error.message.lower()

    @pytest.mark.asyncio
    async def test_wait_timeout(self) -> None:
        """Pending record with WAIT policy; remains pending until timeout."""

        class AlwaysPendingStorage(FakeStorage):
            async def get(self, key: str) -> Result[Some[IdempotencyRecord[str, str]] | Nothing, str]:
                return Ok(Some(make_record(state=RecordState.PENDING)))

        storage = AlwaysPendingStorage()
        policy = Policy().with_on_pending(OnPending.WAIT).with_wait_timeout(seconds=0.3)
        spec = IdempotencySpec(
            key="timeout-key",
            input_value="input",
            operation=_noop_operation,
            storage=storage,  # type: ignore[arg-type]
            policy=policy,
        )

        result = await run_idempotent(spec)
        assert isinstance(result, Error)
        assert result.error.kind == IdempotencyErrorKind.TIMEOUT

    @pytest.mark.asyncio
    async def test_wait_store_error_during_poll(self) -> None:
        """Pending record with WAIT policy; storage.get() fails during poll."""
        call_count = 0

        class ErrorPollingStorage(FakeStorage):
            async def get(self, key: str) -> Result[Some[IdempotencyRecord[str, str]] | Nothing, str]:
                nonlocal call_count
                call_count += 1
                if call_count <= 1:
                    return Ok(Some(make_record(state=RecordState.PENDING)))
                return Error("poll-error")

        storage = ErrorPollingStorage()
        policy = Policy().with_on_pending(OnPending.WAIT).with_wait_timeout(seconds=2)
        spec = IdempotencySpec(
            key="poll-error-key",
            input_value="input",
            operation=_noop_operation,
            storage=storage,  # type: ignore[arg-type]
            policy=policy,
        )

        result = await run_idempotent(spec)
        assert isinstance(result, Error)
        assert result.error.kind == IdempotencyErrorKind.STORE_ERROR


# ============================================================================
# PendingForce — FORCE policy
# ============================================================================


class TestPendingForce:
    @pytest.mark.asyncio
    async def test_force_success(self) -> None:
        """FORCE policy: delete pending, execute new, succeed."""

        async def operation(input_val: str) -> Result[str, str]:
            return Ok(f"forced:{input_val}")

        class ForceStorage(FakeStorage):
            async def get(self, key: str) -> Result[Some[IdempotencyRecord[str, str]] | Nothing, str]:
                return Ok(Some(make_record(state=RecordState.PENDING)))

            async def delete(self, key: str) -> Result[None, str]:
                return Ok(None)

            async def set_nx(self, key: str, value: object, ttl: timedelta | None = None) -> Result[bool, str]:
                return Ok(True)

            async def set(self, key: str, value: object, ttl: timedelta | None = None) -> Result[None, str]:
                return Ok(None)

        storage = ForceStorage()
        policy = Policy().with_on_pending(OnPending.FORCE)
        spec = IdempotencySpec(
            key="force-key",
            input_value="input",
            operation=operation,
            storage=storage,  # type: ignore[arg-type]
            policy=policy,
        )

        result = await run_idempotent(spec)
        assert isinstance(result, Ok)
        assert result.value.value == "forced:input"
        assert result.value.from_cache is False

    @pytest.mark.asyncio
    async def test_force_delete_fails(self) -> None:
        """FORCE policy: delete fails -> STORE_ERROR."""

        class FailDeleteStorage(FakeStorage):
            async def get(self, key: str) -> Result[Some[IdempotencyRecord[str, str]] | Nothing, str]:
                return Ok(Some(make_record(state=RecordState.PENDING)))

            async def delete(self, key: str) -> Result[None, str]:
                return Error("delete-failed")

        storage = FailDeleteStorage()
        policy = Policy().with_on_pending(OnPending.FORCE)
        spec = IdempotencySpec(
            key="force-del-fail",
            input_value="input",
            operation=_noop_operation,
            storage=storage,  # type: ignore[arg-type]
            policy=policy,
        )

        result = await run_idempotent(spec)
        assert isinstance(result, Error)
        assert result.error.kind == IdempotencyErrorKind.STORE_ERROR

    @pytest.mark.asyncio
    async def test_force_set_nx_false(self) -> None:
        """FORCE policy: set_nx returns False (race during force)."""

        class RaceForceStorage(FakeStorage):
            async def get(self, key: str) -> Result[Some[IdempotencyRecord[str, str]] | Nothing, str]:
                return Ok(Some(make_record(state=RecordState.PENDING)))

            async def delete(self, key: str) -> Result[None, str]:
                return Ok(None)

            async def set_nx(self, key: str, value: object, ttl: timedelta | None = None) -> Result[bool, str]:
                return Ok(False)

        storage = RaceForceStorage()
        policy = Policy().with_on_pending(OnPending.FORCE)
        spec = IdempotencySpec(
            key="force-race",
            input_value="input",
            operation=_noop_operation,
            storage=storage,  # type: ignore[arg-type]
            policy=policy,
        )

        result = await run_idempotent(spec)
        assert isinstance(result, Error)
        assert result.error.kind == IdempotencyErrorKind.CONFLICT

    @pytest.mark.asyncio
    async def test_force_set_nx_error(self) -> None:
        """FORCE policy: set_nx returns Error."""

        class SetNxErrorStorage(FakeStorage):
            async def get(self, key: str) -> Result[Some[IdempotencyRecord[str, str]] | Nothing, str]:
                return Ok(Some(make_record(state=RecordState.PENDING)))

            async def delete(self, key: str) -> Result[None, str]:
                return Ok(None)

            async def set_nx(self, key: str, value: object, ttl: timedelta | None = None) -> Result[bool, str]:
                return Error("set-nx-fail")

        storage = SetNxErrorStorage()
        policy = Policy().with_on_pending(OnPending.FORCE)
        spec = IdempotencySpec(
            key="force-setnx-err",
            input_value="input",
            operation=_noop_operation,
            storage=storage,  # type: ignore[arg-type]
            policy=policy,
        )

        result = await run_idempotent(spec)
        assert isinstance(result, Error)
        assert result.error.kind == IdempotencyErrorKind.STORE_ERROR

    @pytest.mark.asyncio
    async def test_force_operation_raises_exception(self) -> None:
        """FORCE policy: operation raises exception."""

        async def exploding_op(input_val: str) -> Result[str, str]:
            raise RuntimeError("kaboom")

        class ForceOkStorage(FakeStorage):
            async def get(self, key: str) -> Result[Some[IdempotencyRecord[str, str]] | Nothing, str]:
                return Ok(Some(make_record(state=RecordState.PENDING)))

            async def delete(self, key: str) -> Result[None, str]:
                return Ok(None)

            async def set_nx(self, key: str, value: object, ttl: timedelta | None = None) -> Result[bool, str]:
                return Ok(True)

        storage = ForceOkStorage()
        policy = Policy().with_on_pending(OnPending.FORCE)
        spec = IdempotencySpec(
            key="force-boom",
            input_value="input",
            operation=exploding_op,
            storage=storage,  # type: ignore[arg-type]
            policy=policy,
        )

        result = await run_idempotent(spec)
        assert isinstance(result, Error)
        assert result.error.kind == IdempotencyErrorKind.EXECUTION
        assert "kaboom" in result.error.message

    @pytest.mark.asyncio
    async def test_force_operation_returns_error_persist_failed(self) -> None:
        """FORCE policy: operation returns Error with persist_failed=True."""

        async def failing_op(input_val: str) -> Result[str, str]:
            return Error("op-error")

        class ForceOkStorage(FakeStorage):
            async def get(self, key: str) -> Result[Some[IdempotencyRecord[str, str]] | Nothing, str]:
                return Ok(Some(make_record(state=RecordState.PENDING)))

            async def delete(self, key: str) -> Result[None, str]:
                return Ok(None)

            async def set_nx(self, key: str, value: object, ttl: timedelta | None = None) -> Result[bool, str]:
                return Ok(True)

            async def set(self, key: str, value: object, ttl: timedelta | None = None) -> Result[None, str]:
                return Ok(None)

        storage = ForceOkStorage()
        policy = Policy().with_on_pending(OnPending.FORCE).with_store_failed(True).with_failed_ttl(seconds=60)
        spec = IdempotencySpec(
            key="force-fail-persist",
            input_value="input",
            operation=failing_op,
            storage=storage,  # type: ignore[arg-type]
            policy=policy,
        )

        result = await run_idempotent(spec)
        assert isinstance(result, Error)
        assert result.error.kind == IdempotencyErrorKind.EXECUTION

    @pytest.mark.asyncio
    async def test_force_operation_returns_error_no_persist(self) -> None:
        """FORCE policy: operation returns Error with persist_failed=False."""

        async def failing_op(input_val: str) -> Result[str, str]:
            return Error("op-error")

        delete_calls: list[str] = []

        class ForceOkStorage(FakeStorage):
            async def get(self, key: str) -> Result[Some[IdempotencyRecord[str, str]] | Nothing, str]:
                return Ok(Some(make_record(state=RecordState.PENDING)))

            async def delete(self, key: str) -> Result[None, str]:
                delete_calls.append(key)
                return Ok(None)

            async def set_nx(self, key: str, value: object, ttl: timedelta | None = None) -> Result[bool, str]:
                return Ok(True)

        storage = ForceOkStorage()
        policy = Policy().with_on_pending(OnPending.FORCE).with_store_failed(False)
        spec = IdempotencySpec(
            key="force-fail-nopersist",
            input_value="input",
            operation=failing_op,
            storage=storage,  # type: ignore[arg-type]
            policy=policy,
        )

        result = await run_idempotent(spec)
        assert isinstance(result, Error)
        assert result.error.kind == IdempotencyErrorKind.EXECUTION

    @pytest.mark.asyncio
    async def test_force_set_completed_error(self) -> None:
        """FORCE policy: set_completed returns Error."""

        async def operation(input_val: str) -> Result[str, str]:
            return Ok("success")

        class SetFailStorage(FakeStorage):
            async def get(self, key: str) -> Result[Some[IdempotencyRecord[str, str]] | Nothing, str]:
                return Ok(Some(make_record(state=RecordState.PENDING)))

            async def delete(self, key: str) -> Result[None, str]:
                return Ok(None)

            async def set_nx(self, key: str, value: object, ttl: timedelta | None = None) -> Result[bool, str]:
                return Ok(True)

            async def set(self, key: str, value: object, ttl: timedelta | None = None) -> Result[None, str]:
                return Error("set-fail")

        storage = SetFailStorage()
        policy = Policy().with_on_pending(OnPending.FORCE)
        spec = IdempotencySpec(
            key="force-set-fail",
            input_value="input",
            operation=operation,
            storage=storage,  # type: ignore[arg-type]
            policy=policy,
        )

        result = await run_idempotent(spec)
        assert isinstance(result, Error)
        assert result.error.kind == IdempotencyErrorKind.STORE_ERROR


# ============================================================================
# InputHashMismatch
# ============================================================================


class TestInputHashMismatch:
    @pytest.mark.asyncio
    async def test_input_mismatch_returns_error(self) -> None:
        """Completed record with different input_hash returns INPUT_MISMATCH."""
        record = make_record(
            state=RecordState.COMPLETED,
            value="cached",
            input_hash="hash-A",
        )
        storage = FakeStorage(get_result=Ok(Some(record)))
        spec = IdempotencySpec(
            key="mismatch-key",
            input_value="input",
            operation=_noop_operation,
            storage=storage,  # type: ignore[arg-type]
            policy=Policy(),
            input_hash="hash-B",
        )

        result = await run_idempotent(spec)
        assert isinstance(result, Error)
        assert result.error.kind == IdempotencyErrorKind.INPUT_MISMATCH


# ============================================================================
# Execute New — additional paths
# ============================================================================


class TestExecuteNewExtended:
    @pytest.mark.asyncio
    async def test_set_nx_error(self) -> None:
        """set_pending returns Error."""
        storage = FakeStorage(
            get_result=Ok(Nothing()),
            set_nx_result=Error("set-nx-boom"),
        )
        spec = IdempotencySpec(
            key="setnx-err",
            input_value="input",
            operation=_noop_operation,
            storage=storage,  # type: ignore[arg-type]
            policy=Policy(),
        )

        result = await run_idempotent(spec)
        assert isinstance(result, Error)
        assert result.error.kind == IdempotencyErrorKind.STORE_ERROR

    @pytest.mark.asyncio
    async def test_set_completed_error(self) -> None:
        """Operation succeeds but set_completed fails."""

        async def operation(input_val: str) -> Result[str, str]:
            return Ok("value")

        storage = FakeStorage(
            get_result=Ok(Nothing()),
            set_nx_result=Ok(True),
            set_result=Error("set-completed-fail"),
        )
        spec = IdempotencySpec(
            key="set-fail-key",
            input_value="input",
            operation=operation,
            storage=storage,  # type: ignore[arg-type]
            policy=Policy(),
        )

        result = await run_idempotent(spec)
        assert isinstance(result, Error)
        assert result.error.kind == IdempotencyErrorKind.STORE_ERROR

    @pytest.mark.asyncio
    async def test_race_set_nx_false_then_not_completed(self) -> None:
        """set_nx returns False (race), then get returns non-completed record."""
        call_count = 0

        class RaceNotCompletedStorage(FakeStorage):
            async def get(self, key: str) -> Result[Some[IdempotencyRecord[str, str]] | Nothing, str]:
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    return Ok(Nothing())
                # Second get: pending (not completed)
                return Ok(Some(make_record(state=RecordState.PENDING)))

            async def set_nx(self, key: str, value: object, ttl: timedelta | None = None) -> Result[bool, str]:
                return Ok(False)

        storage = RaceNotCompletedStorage()
        spec = IdempotencySpec(
            key="race-pending",
            input_value="input",
            operation=_noop_operation,
            storage=storage,  # type: ignore[arg-type]
            policy=Policy(),
        )

        result = await run_idempotent(spec)
        assert isinstance(result, Error)
        assert result.error.kind == IdempotencyErrorKind.CONFLICT

    @pytest.mark.asyncio
    async def test_persist_failed_with_custom_ttl(self) -> None:
        """Operation fails with persist_failed=True and custom failed_result_ttl."""

        async def operation(input_val: str) -> Result[str, str]:
            return Error("fail-value")

        storage = FakeStorage(
            get_result=Ok(Nothing()),
            set_nx_result=Ok(True),
            set_result=Ok(None),
        )
        policy = (
            Policy()
            .with_ttl(hours=1)
            .with_store_failed(True)
            .with_failed_ttl(seconds=60)
        )
        spec = IdempotencySpec(
            key="persist-custom-ttl",
            input_value="input",
            operation=operation,
            storage=storage,  # type: ignore[arg-type]
            policy=policy,
        )

        result = await run_idempotent(spec)
        assert isinstance(result, Error)
        assert result.error.kind == IdempotencyErrorKind.EXECUTION
        # Should have called set to persist the failed record
        assert len(storage.set_calls) > 0


# ============================================================================
# StoreErrorNode direct outcome
# ============================================================================


class TestStoreErrorOutcome:
    @pytest.mark.asyncio
    async def test_store_error_outcome(self) -> None:
        """Storage get() returns Error -> StoreErrorNode -> STORE_ERROR outcome."""
        storage = FakeStorage(get_result=Error("storage down"))
        spec = IdempotencySpec(
            key="store-err",
            input_value="input",
            operation=_noop_operation,
            storage=storage,  # type: ignore[arg-type]
            policy=Policy(),
        )

        result = await run_idempotent(spec)
        assert isinstance(result, Error)
        assert result.error.kind == IdempotencyErrorKind.STORE_ERROR
        assert "storage down" in result.error.message


# ============================================================================
# FinalResultNode
# ============================================================================


class TestFinalResultNodeExtended:
    def test_to_result_ok_with_metadata(self) -> None:
        outcome = OutcomeOk(value="v", from_cache=True, key="k")
        node = FinalResultNode(outcome)
        result = node.to_result()
        assert isinstance(result, Ok)
        assert result.value.value == "v"
        assert result.value.from_cache is True
        assert result.value.key == "k"

    def test_to_result_error_with_original(self) -> None:
        original = RuntimeError("original")
        outcome = OutcomeError(
            kind=IdempotencyErrorKind.EXECUTION,
            message="exec fail",
            original_error=original,
        )
        node = FinalResultNode(outcome)
        result = node.to_result()
        assert isinstance(result, Error)
        assert result.error.kind == IdempotencyErrorKind.EXECUTION
        assert result.error.message == "exec fail"
        assert result.error.original_error is original

"""Tests for emergent.idempotency._types.

Covers:
    - RecordState enum values and lifecycle
    - IdempotencyRecord: is_expired, is_pending, is_completed, is_failed properties
    - IdempotencyRecord: frozen/immutable behavior
    - IdempotencyResult: value, from_cache, key
    - IdempotencyError: kind, message, original_error
    - IdempotencyErrorKind enum values
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from emergent.idempotency._types import (
    RecordState,
    IdempotencyRecord,
    IdempotencyResult,
    IdempotencyError,
    IdempotencyErrorKind,
)


# ═══════════════════════════════════════════════════════════════════════════════
# RecordState
# ═══════════════════════════════════════════════════════════════════════════════


class TestRecordState:
    def test_has_pending(self) -> None:
        assert RecordState.PENDING is not None

    def test_has_completed(self) -> None:
        assert RecordState.COMPLETED is not None

    def test_has_failed(self) -> None:
        assert RecordState.FAILED is not None

    def test_all_states_are_distinct(self) -> None:
        states = [RecordState.PENDING, RecordState.COMPLETED, RecordState.FAILED]
        assert len(set(states)) == 3


# ═══════════════════════════════════════════════════════════════════════════════
# IdempotencyRecord — is_expired
# ═══════════════════════════════════════════════════════════════════════════════


class TestIdempotencyRecordIsExpired:
    def test_not_expired_when_expires_at_is_none(self) -> None:
        record = IdempotencyRecord[str, str](
            key="k",
            state=RecordState.COMPLETED,
            value="v",
            error=None,
            created_at=datetime.now(tz=timezone.utc),
            expires_at=None,
        )
        assert record.is_expired is False

    def test_not_expired_when_expires_at_is_in_future(self) -> None:
        record = IdempotencyRecord[str, str](
            key="k",
            state=RecordState.COMPLETED,
            value="v",
            error=None,
            created_at=datetime.now(tz=timezone.utc),
            expires_at=datetime.now(tz=timezone.utc) + timedelta(hours=1),
        )
        assert record.is_expired is False

    def test_expired_when_expires_at_is_in_past(self) -> None:
        record = IdempotencyRecord[str, str](
            key="k",
            state=RecordState.COMPLETED,
            value="v",
            error=None,
            created_at=datetime.now(tz=timezone.utc) - timedelta(hours=2),
            expires_at=datetime.now(tz=timezone.utc) - timedelta(hours=1),
        )
        assert record.is_expired is True

    def test_expired_boundary_just_past(self) -> None:
        record = IdempotencyRecord[str, str](
            key="k",
            state=RecordState.COMPLETED,
            value="v",
            error=None,
            created_at=datetime.now(tz=timezone.utc) - timedelta(seconds=10),
            expires_at=datetime.now(tz=timezone.utc) - timedelta(milliseconds=1),
        )
        assert record.is_expired is True


# ═══════════════════════════════════════════════════════════════════════════════
# IdempotencyRecord — state properties
# ═══════════════════════════════════════════════════════════════════════════════


class TestIdempotencyRecordStateProperties:
    def _make_record(self, state: RecordState) -> IdempotencyRecord[str, str]:
        return IdempotencyRecord[str, str](
            key="k",
            state=state,
            value="v" if state == RecordState.COMPLETED else None,
            error="e" if state == RecordState.FAILED else None,
            created_at=datetime.now(tz=timezone.utc),
            expires_at=None,
        )

    def test_pending_state(self) -> None:
        record = self._make_record(RecordState.PENDING)
        assert record.is_pending is True
        assert record.is_completed is False
        assert record.is_failed is False

    def test_completed_state(self) -> None:
        record = self._make_record(RecordState.COMPLETED)
        assert record.is_pending is False
        assert record.is_completed is True
        assert record.is_failed is False

    def test_failed_state(self) -> None:
        record = self._make_record(RecordState.FAILED)
        assert record.is_pending is False
        assert record.is_completed is False
        assert record.is_failed is True


# ═══════════════════════════════════════════════════════════════════════════════
# IdempotencyRecord — frozen/immutable
# ═══════════════════════════════════════════════════════════════════════════════


class TestIdempotencyRecordImmutable:
    def test_cannot_modify_key(self) -> None:
        record = IdempotencyRecord[str, str](
            key="k",
            state=RecordState.PENDING,
            value=None,
            error=None,
            created_at=datetime.now(tz=timezone.utc),
            expires_at=None,
        )
        with pytest.raises(AttributeError):
            record.key = "new"  # type: ignore[misc]

    def test_cannot_modify_state(self) -> None:
        record = IdempotencyRecord[str, str](
            key="k",
            state=RecordState.PENDING,
            value=None,
            error=None,
            created_at=datetime.now(tz=timezone.utc),
            expires_at=None,
        )
        with pytest.raises(AttributeError):
            record.state = RecordState.COMPLETED  # type: ignore[misc]


# ═══════════════════════════════════════════════════════════════════════════════
# IdempotencyRecord — input_hash
# ═══════════════════════════════════════════════════════════════════════════════


class TestIdempotencyRecordInputHash:
    def test_default_input_hash_is_none(self) -> None:
        record = IdempotencyRecord[str, str](
            key="k",
            state=RecordState.PENDING,
            value=None,
            error=None,
            created_at=datetime.now(tz=timezone.utc),
            expires_at=None,
        )
        assert record.input_hash is None

    def test_custom_input_hash(self) -> None:
        record = IdempotencyRecord[str, str](
            key="k",
            state=RecordState.PENDING,
            value=None,
            error=None,
            created_at=datetime.now(tz=timezone.utc),
            expires_at=None,
            input_hash="sha256_abc",
        )
        assert record.input_hash == "sha256_abc"


# ═══════════════════════════════════════════════════════════════════════════════
# IdempotencyResult
# ═══════════════════════════════════════════════════════════════════════════════


class TestIdempotencyResult:
    def test_creation(self) -> None:
        result = IdempotencyResult[str](value="hello", from_cache=False, key="k1")
        assert result.value == "hello"
        assert result.from_cache is False
        assert result.key == "k1"

    def test_from_cache_true(self) -> None:
        result = IdempotencyResult[int](value=42, from_cache=True, key="k2")
        assert result.from_cache is True
        assert result.value == 42

    def test_frozen(self) -> None:
        result = IdempotencyResult[str](value="v", from_cache=False, key="k")
        with pytest.raises(AttributeError):
            result.value = "new"  # type: ignore[misc]


# ═══════════════════════════════════════════════════════════════════════════════
# IdempotencyErrorKind
# ═══════════════════════════════════════════════════════════════════════════════


class TestIdempotencyErrorKind:
    def test_all_kinds_exist(self) -> None:
        assert IdempotencyErrorKind.CONFLICT is not None
        assert IdempotencyErrorKind.TIMEOUT is not None
        assert IdempotencyErrorKind.STORE_ERROR is not None
        assert IdempotencyErrorKind.LOCK_ERROR is not None
        assert IdempotencyErrorKind.EXECUTION is not None
        assert IdempotencyErrorKind.INPUT_MISMATCH is not None

    def test_kinds_are_distinct(self) -> None:
        kinds = [
            IdempotencyErrorKind.CONFLICT,
            IdempotencyErrorKind.TIMEOUT,
            IdempotencyErrorKind.STORE_ERROR,
            IdempotencyErrorKind.LOCK_ERROR,
            IdempotencyErrorKind.EXECUTION,
            IdempotencyErrorKind.INPUT_MISMATCH,
        ]
        assert len(set(kinds)) == 6


# ═══════════════════════════════════════════════════════════════════════════════
# IdempotencyError
# ═══════════════════════════════════════════════════════════════════════════════


class TestIdempotencyError:
    def test_creation_without_original_error(self) -> None:
        err = IdempotencyError[str](
            kind=IdempotencyErrorKind.CONFLICT,
            message="concurrent request",
        )
        assert err.kind == IdempotencyErrorKind.CONFLICT
        assert err.message == "concurrent request"
        assert err.original_error is None

    def test_creation_with_original_error(self) -> None:
        original = ValueError("bad input")
        err = IdempotencyError[ValueError](
            kind=IdempotencyErrorKind.EXECUTION,
            message="operation failed",
            original_error=original,
        )
        assert err.kind == IdempotencyErrorKind.EXECUTION
        assert err.message == "operation failed"
        assert err.original_error is original

    def test_store_error_kind(self) -> None:
        err = IdempotencyError[str](
            kind=IdempotencyErrorKind.STORE_ERROR,
            message="redis down",
        )
        assert err.kind == IdempotencyErrorKind.STORE_ERROR

    def test_timeout_kind(self) -> None:
        err = IdempotencyError[str](
            kind=IdempotencyErrorKind.TIMEOUT,
            message="waited too long",
        )
        assert err.kind == IdempotencyErrorKind.TIMEOUT

    def test_input_mismatch_kind(self) -> None:
        err = IdempotencyError[str](
            kind=IdempotencyErrorKind.INPUT_MISMATCH,
            message="different input for same key",
        )
        assert err.kind == IdempotencyErrorKind.INPUT_MISMATCH

    def test_frozen(self) -> None:
        err = IdempotencyError[str](
            kind=IdempotencyErrorKind.CONFLICT,
            message="test",
        )
        with pytest.raises(AttributeError):
            err.message = "changed"  # type: ignore[misc]

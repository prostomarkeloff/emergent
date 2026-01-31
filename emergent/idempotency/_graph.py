"""
Idempotency graph — ALL logic as nodnod nodes.

No if/else duplication. Pure declarative graph with polymorphic routing.

Architecture:
    IdempotencySpec (injected)
         │
         ▼
    SpecNode
         │
         ▼
    FetchRecordNode
         │
         ├─────────────────────────────────────────────────┐
         │                                                 │
         ▼                                                 ▼
    RecordStateNode (validates record)          NoRecordNode (validates no record)
         │
         ├── CompletedRecordNode ──┐
         ├── FailedRecordNode ─────┼── IdempotencyOutcome (@polymorphic)
         └── PendingRecordNode ────┘             │
                                                 ▼
                                          FinalResultNode

Note: НЕ используем 'from __future__ import annotations' потому что
nodnod использует type hints в runtime для dependency resolution.
"""

import asyncio
from dataclasses import dataclass
from typing import Any, Protocol

from nodnod import NodeError, polymorphic, case

from kungfu import Result, Ok, Error

from emergent import graph as G
from emergent.idempotency._types import (
    RecordState,
    IdempotencyRecord,
    IdempotencyResult,
    IdempotencyError,
    IdempotencyErrorKind,
)
from emergent.idempotency._store import (
    Record,
    StoreError,
    set_pending,
    set_completed,
    set_failed,
)
from emergent.wire.axis.storage import Get, SetWithTTL, Delete, SetNX
from kungfu import Some, Nothing
from emergent.idempotency._policy import Policy, OnPending


# ═══════════════════════════════════════════════════════════════════════════════
# Storage Type — What idempotency needs from storage
# ═══════════════════════════════════════════════════════════════════════════════


class IdempotencyStorage(
    Get[str, Record[Any], Any],
    SetWithTTL[str, Record[Any], Any],
    Delete[str, Any],
    SetNX[str, Record[Any], Any],
    Protocol,
):
    """Storage interface for idempotency.

    Combines all required capabilities:
    - Get: fetch record by key
    - SetWithTTL: store record with expiration
    - Delete: remove record
    - SetNX: atomic set-if-not-exists for locking
    """

    ...


# ═══════════════════════════════════════════════════════════════════════════════
# Input — Spec (injected)
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class IdempotencySpec:
    """Complete specification for idempotent execution.

    Note: input_hash is optional fingerprint for collision detection.
    If provided, cached results are only returned if hash matches.
    """

    key: str
    input_value: Any
    operation: Any
    storage: IdempotencyStorage
    policy: Policy
    input_hash: str | None = None


# ═══════════════════════════════════════════════════════════════════════════════
# Entry Node
# ═══════════════════════════════════════════════════════════════════════════════


@G.node
class SpecNode:
    """Wraps IdempotencySpec for graph."""

    def __init__(self, spec: IdempotencySpec) -> None:
        self.spec = spec

    @classmethod
    def __compose__(cls, spec: IdempotencySpec) -> "SpecNode":
        return cls(spec)


# ═══════════════════════════════════════════════════════════════════════════════
# Fetch Record
# ═══════════════════════════════════════════════════════════════════════════════


@G.node
class FetchRecordNode:
    """Fetches existing record from store."""

    def __init__(
        self,
        record: IdempotencyRecord[Any, Any] | None,
        spec: IdempotencySpec,
        store_error: StoreError | None = None,
    ) -> None:
        self.record = record
        self.spec = spec
        self.store_error = store_error

    @classmethod
    async def __compose__(cls, spec_node: SpecNode) -> "FetchRecordNode":
        spec = spec_node.spec
        result = await spec.storage.get(spec.key)

        match result:
            case Ok(Some(record)):
                return cls(record, spec)
            case Ok(Nothing()):
                return cls(None, spec)
            case Error(err):
                return cls(None, spec, store_error=StoreError.from_error(err))
            case _:
                return cls(None, spec)


# ═══════════════════════════════════════════════════════════════════════════════
# State Nodes — Each validates a specific record state
# ═══════════════════════════════════════════════════════════════════════════════


@G.node
class CompletedRecordNode:
    """Validates: record exists, COMPLETED, not expired."""

    def __init__(
        self, record: IdempotencyRecord[Any, Any], spec: IdempotencySpec
    ) -> None:
        self.record = record
        self.spec = spec

    @classmethod
    def __compose__(cls, fetch: FetchRecordNode) -> "CompletedRecordNode":
        record = fetch.record
        if record is None:
            raise NodeError("No record")
        if record.state != RecordState.COMPLETED:
            raise NodeError("Not completed")
        if record.is_expired:
            raise NodeError("Expired")
        return cls(record, fetch.spec)


@G.node
class FailedRecordNode:
    """Validates: record exists, FAILED, not expired."""

    def __init__(
        self, record: IdempotencyRecord[Any, Any], spec: IdempotencySpec
    ) -> None:
        self.record = record
        self.spec = spec

    @classmethod
    def __compose__(cls, fetch: FetchRecordNode) -> "FailedRecordNode":
        record = fetch.record
        if record is None:
            raise NodeError("No record")
        if record.state != RecordState.FAILED:
            raise NodeError("Not failed")
        if record.is_expired:
            raise NodeError("Expired")
        return cls(record, fetch.spec)


@G.node
class PendingRecordNode:
    """Validates: record exists, PENDING."""

    def __init__(
        self, record: IdempotencyRecord[Any, Any], spec: IdempotencySpec
    ) -> None:
        self.record = record
        self.spec = spec

    @classmethod
    def __compose__(cls, fetch: FetchRecordNode) -> "PendingRecordNode":
        record = fetch.record
        if record is None:
            raise NodeError("No record")
        if record.state != RecordState.PENDING:
            raise NodeError("Not pending")
        return cls(record, fetch.spec)


@G.node
class NoRecordNode:
    """Validates: no record OR expired."""

    def __init__(self, spec: IdempotencySpec) -> None:
        self.spec = spec

    @classmethod
    def __compose__(cls, fetch: FetchRecordNode) -> "NoRecordNode":
        if fetch.store_error is not None:
            raise NodeError("Store error")
        record = fetch.record
        if record is not None and not record.is_expired:
            raise NodeError("Record exists")
        return cls(fetch.spec)


@G.node
class StoreErrorNode:
    """Validates: store returned error."""

    def __init__(self, error: StoreError, spec: IdempotencySpec) -> None:
        self.error = error
        self.spec = spec

    @classmethod
    def __compose__(cls, fetch: FetchRecordNode) -> "StoreErrorNode":
        if fetch.store_error is None:
            raise NodeError("No store error")
        return cls(fetch.store_error, fetch.spec)


@G.node
class ValidatedInputNode:
    """
    Validates: input_hash matches cached record (if fingerprinting enabled).

    Note: Только для completed records.
    Почему: Защита от коллизий — разные inputs с одинаковым key.
    """

    def __init__(self, completed: CompletedRecordNode) -> None:
        self.completed = completed

    @classmethod
    def __compose__(cls, completed: CompletedRecordNode) -> "ValidatedInputNode":
        spec = completed.spec
        record = completed.record

        # Skip validation if no hash provided
        if spec.input_hash is None:
            return cls(completed)

        # Validate hash matches
        if record.input_hash is None:
            # Record has no hash (legacy) — accept
            return cls(completed)

        if record.input_hash != spec.input_hash:
            raise NodeError("Input hash mismatch")

        return cls(completed)


# ═══════════════════════════════════════════════════════════════════════════════
# Outcome Types
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class OutcomeOk:
    """Successful outcome."""

    value: Any
    from_cache: bool
    key: str


@dataclass(frozen=True)
class OutcomeError:
    """Error outcome."""

    kind: IdempotencyErrorKind
    message: str
    original_error: Any | None


type Outcome = OutcomeOk | OutcomeError


# ═══════════════════════════════════════════════════════════════════════════════
# Polymorphic Outcome — Each case uses validated state nodes
# ═══════════════════════════════════════════════════════════════════════════════


@polymorphic[Outcome]
class IdempotencyOutcome:
    """
    Polymorphic router — each @case depends on validated state node.

    Note: Проверки уже сделаны в state nodes, здесь только логика.
    """

    @case
    def store_error(cls, node: StoreErrorNode) -> Outcome:
        """STORE_ERROR — storage operation failed."""
        return OutcomeError(
            kind=IdempotencyErrorKind.STORE_ERROR,
            message=node.error.message,
            original_error=node.error.cause,
        )

    @case
    def cached_completed(cls, validated: ValidatedInputNode) -> Outcome:
        """Return cached COMPLETED result (with input validation)."""
        node = validated.completed
        return OutcomeOk(
            value=node.record.value,
            from_cache=True,
            key=node.spec.key,
        )

    @case
    def input_mismatch(cls, completed: CompletedRecordNode) -> Outcome:
        """
        INPUT_MISMATCH error — cached result has different input.

        Note: Этот case выполнится если ValidatedInputNode fail.
        """
        spec = completed.spec
        if spec.input_hash is None:
            raise NodeError("No fingerprint")

        record = completed.record
        if record.input_hash is None:
            raise NodeError("No record hash")

        if record.input_hash == spec.input_hash:
            raise NodeError("Hash matches")

        return OutcomeError(
            kind=IdempotencyErrorKind.INPUT_MISMATCH,
            message=f"Key collision: {spec.key} (different input)",
            original_error=None,
        )

    @case
    def cached_failed(cls, node: FailedRecordNode) -> Outcome:
        """Return cached FAILED error."""
        return OutcomeError(
            kind=IdempotencyErrorKind.EXECUTION,
            message="Cached failure",
            original_error=node.record.error,
        )

    @case
    def pending_conflict(cls, node: PendingRecordNode) -> Outcome:
        """CONFLICT error (pending + FAIL policy)."""
        if node.spec.policy.conflict_strategy != OnPending.FAIL:
            raise NodeError("Policy not FAIL")
        return OutcomeError(
            kind=IdempotencyErrorKind.CONFLICT,
            message=f"Pending conflict: {node.spec.key}",
            original_error=None,
        )

    @case
    async def pending_force(cls, node: PendingRecordNode) -> Outcome:
        """FORCE: Override pending, execute anyway."""
        spec = node.spec
        if spec.policy.conflict_strategy != OnPending.FORCE:
            raise NodeError("Policy not FORCE")

        # Delete existing pending and execute as new
        match await spec.storage.delete(spec.key):
            case Error(err):
                wrapped = StoreError.from_error(err)
                return OutcomeError(
                    kind=IdempotencyErrorKind.STORE_ERROR,
                    message=wrapped.message,
                    original_error=wrapped.cause,
                )
            case _:
                pass

        # Acquire new slot (with input_hash)
        match await set_pending(spec.storage, spec.key, spec.policy.result_ttl, spec.input_hash):
            case Error(err):
                wrapped = StoreError.from_error(err)
                return OutcomeError(
                    kind=IdempotencyErrorKind.STORE_ERROR,
                    message=wrapped.message,
                    original_error=wrapped.cause,
                )
            case Ok(False):
                return OutcomeError(
                    kind=IdempotencyErrorKind.CONFLICT,
                    message="Race conflict during force",
                    original_error=None,
                )
            case _:
                pass

        # Execute
        try:
            raw_result = await spec.operation(spec.input_value)
            result: Result[Any, Any] = raw_result
        except Exception as e:
            await spec.storage.delete(spec.key)
            return OutcomeError(
                kind=IdempotencyErrorKind.EXECUTION,
                message=str(e),
                original_error=e,
            )

        # Store result
        match result:
            case Ok(value):
                match await set_completed(spec.storage, spec.key, value, spec.policy.result_ttl):
                    case Error(err):
                        wrapped = StoreError.from_error(err)
                        return OutcomeError(
                            kind=IdempotencyErrorKind.STORE_ERROR,
                            message=wrapped.message,
                            original_error=wrapped.cause,
                        )
                    case _:
                        return OutcomeOk(value=value, from_cache=False, key=spec.key)
            case Error(err):
                if spec.policy.persist_failed:
                    ttl = spec.policy.failed_result_ttl or spec.policy.result_ttl
                    await set_failed(spec.storage, spec.key, err, ttl)
                else:
                    await spec.storage.delete(spec.key)
                return OutcomeError(
                    kind=IdempotencyErrorKind.EXECUTION,
                    message="Operation returned Error",
                    original_error=err,
                )

    @case
    async def pending_wait(cls, node: PendingRecordNode) -> Outcome:
        """Wait for pending, return result."""
        spec = node.spec
        if spec.policy.conflict_strategy != OnPending.WAIT:
            raise NodeError("Policy not WAIT")

        timeout = spec.policy.pending_wait_timeout.total_seconds()
        poll_interval = 0.1
        elapsed = 0.0

        while elapsed < timeout:
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

            match await spec.storage.get(spec.key):
                case Error(err):
                    wrapped = StoreError.from_error(err)
                    return OutcomeError(
                        kind=IdempotencyErrorKind.STORE_ERROR,
                        message=wrapped.message,
                        original_error=wrapped.cause,
                    )
                case Ok(Nothing()):
                    return OutcomeError(
                        kind=IdempotencyErrorKind.STORE_ERROR,
                        message="Record disappeared",
                        original_error=None,
                    )
                case Ok(Some(new_record)):
                    if new_record.state == RecordState.COMPLETED:
                        return OutcomeOk(
                            value=new_record.value,
                            from_cache=True,
                            key=spec.key,
                        )
                    if new_record.state == RecordState.FAILED:
                        return OutcomeError(
                            kind=IdempotencyErrorKind.EXECUTION,
                            message="Operation failed while waiting",
                            original_error=new_record.error,
                        )
                    # Still pending, continue waiting
                case _:
                    pass

        return OutcomeError(
            kind=IdempotencyErrorKind.TIMEOUT,
            message="Timeout waiting for pending operation",
            original_error=None,
        )

    @case
    async def execute_new(cls, node: NoRecordNode) -> Outcome:
        """Execute operation (no record or expired)."""
        spec = node.spec

        # Acquire slot (with input_hash for collision detection)
        match await set_pending(spec.storage, spec.key, spec.policy.result_ttl, spec.input_hash):
            case Error(err):
                wrapped = StoreError.from_error(err)
                return OutcomeError(
                    kind=IdempotencyErrorKind.STORE_ERROR,
                    message=wrapped.message,
                    original_error=wrapped.cause,
                )
            case Ok(False):
                # Race — check if completed
                match await spec.storage.get(spec.key):
                    case Ok(Some(rec)) if rec.state == RecordState.COMPLETED:
                        return OutcomeOk(
                            value=rec.value,
                            from_cache=True,
                            key=spec.key,
                        )
                    case _:
                        return OutcomeError(
                            kind=IdempotencyErrorKind.CONFLICT,
                            message="Race conflict",
                            original_error=None,
                        )
            case _:
                pass

        # Execute
        try:
            raw_result = await spec.operation(spec.input_value)
            result: Result[Any, Any] = raw_result
        except Exception as e:
            await spec.storage.delete(spec.key)
            return OutcomeError(
                kind=IdempotencyErrorKind.EXECUTION,
                message=str(e),
                original_error=e,
            )

        # Store result
        match result:
            case Ok(value):
                match await set_completed(spec.storage, spec.key, value, spec.policy.result_ttl):
                    case Error(err):
                        wrapped = StoreError.from_error(err)
                        return OutcomeError(
                            kind=IdempotencyErrorKind.STORE_ERROR,
                            message=wrapped.message,
                            original_error=wrapped.cause,
                        )
                    case _:
                        return OutcomeOk(value=value, from_cache=False, key=spec.key)
            case Error(err):
                if spec.policy.persist_failed:
                    ttl = spec.policy.failed_result_ttl or spec.policy.result_ttl
                    await set_failed(spec.storage, spec.key, err, ttl)
                else:
                    await spec.storage.delete(spec.key)
                return OutcomeError(
                    kind=IdempotencyErrorKind.EXECUTION,
                    message="Operation returned Error",
                    original_error=err,
                )


# ═══════════════════════════════════════════════════════════════════════════════
# Final Node
# ═══════════════════════════════════════════════════════════════════════════════


@G.node
class FinalResultNode:
    """Converts Outcome to typed Result."""

    def __init__(self, outcome: Outcome) -> None:
        self.outcome = outcome

    @classmethod
    def __compose__(cls, outcome: IdempotencyOutcome) -> "FinalResultNode":
        return cls(outcome.value)

    def to_result(self) -> Result[IdempotencyResult[Any], IdempotencyError[Any]]:
        match self.outcome:
            case OutcomeOk(value=v, from_cache=fc, key=k):
                return Ok(IdempotencyResult(value=v, from_cache=fc, key=k))
            case OutcomeError(kind=kind, message=msg, original_error=orig):
                return Error(
                    IdempotencyError(kind=kind, message=msg, original_error=orig)
                )


# ═══════════════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════════════


async def run_idempotent(
    spec: IdempotencySpec,
) -> Result[IdempotencyResult[Any], IdempotencyError[Any]]:
    """Execute idempotent operation via graph."""
    node = await G.run(FinalResultNode).inject(spec)
    return node.to_result()


# ═══════════════════════════════════════════════════════════════════════════════
# Exports
# ═══════════════════════════════════════════════════════════════════════════════

__all__ = (
    "IdempotencyStorage",
    "IdempotencySpec",
    "Outcome",
    "OutcomeOk",
    "OutcomeError",
    "SpecNode",
    "FetchRecordNode",
    "CompletedRecordNode",
    "FailedRecordNode",
    "PendingRecordNode",
    "NoRecordNode",
    "ValidatedInputNode",
    "StoreErrorNode",
    "IdempotencyOutcome",
    "FinalResultNode",
    "run_idempotent",
)

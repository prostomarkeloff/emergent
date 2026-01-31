"""Idempotency — enterprise-grade idempotency engine via nodnod graphs.

    from emergent import idempotency as I
    from emergent.wire.axis.storage import MemoryStorage

    # Graph API
    storage = MemoryStorage[str, I.Record[str]]()
    spec = I.IdempotencySpec(
        key=f"payment:{order_id}",
        input_value=order_id,
        operation=process_payment,
        storage=storage,
        policy=I.Policy().with_ttl(seconds=3600),
    )
    result = await I.run_idempotent(spec)

    # Builder API
    executor = (
        I.idempotent(process_payment)
        .key(lambda oid: f"payment:{oid}")
        .storage(storage)  # optional, defaults to MemoryStorage
        .policy(I.Policy().with_ttl(seconds=3600))
        .build()
    )
    result = await executor.run(order_id)

Architecture — State nodes validate, polymorphic routes:

    IdempotencySpec
         │
         ▼
    SpecNode → FetchRecordNode
                     │
         ┌───────────┴───────────────┐
         │                           │
         ▼                           ▼
    CompletedRecordNode         NoRecordNode
    FailedRecordNode                 │
    PendingRecordNode                │
         │                           │
         └───────────┬───────────────┘
                     │
                     ▼
         IdempotencyOutcome (@polymorphic)
                     │
                     ▼
            FinalResultNode
"""

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
    make_pending_record,
    make_completed_record,
    make_failed_record,
    set_pending,
    set_completed,
    set_failed,
)
from emergent.idempotency._policy import (
    Policy,
    OnPending,
    WAIT,
    FAIL,
    FORCE,
)
from emergent.idempotency._graph import (
    IdempotencyStorage,
    IdempotencySpec,
    run_idempotent,
    Outcome,
    OutcomeOk,
    OutcomeError,
    SpecNode,
    FetchRecordNode,
    CompletedRecordNode,
    FailedRecordNode,
    PendingRecordNode,
    NoRecordNode,
    ValidatedInputNode,
    StoreErrorNode,
    IdempotencyOutcome,
    FinalResultNode,
)
from emergent.idempotency._builder import (
    idempotent,
    Idempotent,
    IdempotentExecutor,
)

__all__ = (
    # Types
    "RecordState",
    "IdempotencyRecord",
    "IdempotencyResult",
    "IdempotencyError",
    "IdempotencyErrorKind",
    # Storage helpers
    "Record",
    "StoreError",
    "make_pending_record",
    "make_completed_record",
    "make_failed_record",
    "set_pending",
    "set_completed",
    "set_failed",
    # Policy
    "Policy",
    "OnPending",
    "WAIT",
    "FAIL",
    "FORCE",
    # Spec & API
    "IdempotencyStorage",
    "IdempotencySpec",
    "run_idempotent",
    # Outcome
    "Outcome",
    "OutcomeOk",
    "OutcomeError",
    # Nodes
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
    # Builder
    "idempotent",
    "Idempotent",
    "IdempotentExecutor",
)

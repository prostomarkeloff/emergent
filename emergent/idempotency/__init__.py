"""
Idempotency — enterprise-grade idempotency engine via nodnod graphs.

    from emergent import idempotency as I

    # Graph API
    spec = I.IdempotencySpec(
        key=f"payment:{order_id}",
        input_value=order_id,
        operation=process_payment,
        store=I.MemoryStore(),
        policy=I.Policy().with_ttl(seconds=3600),
    )
    result = await I.run_idempotent(spec)

    # Builder API
    executor = (
        I.idempotent(process_payment)
        .key(lambda oid: f"payment:{oid}")
        .store(I.MemoryStore())
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
    Store,
    StoreError,
    FunctionalStore,
    store_from,
    MemoryStore,
)
from emergent.idempotency._policy import (
    Policy,
    OnPending,
    WAIT,
    FAIL,
    FORCE,
)
from emergent.idempotency._graph import (
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

# SQLAlchemy integration (optional import)
try:
    from emergent.idempotency._sqlalchemy import (
        IdempotencyMixin,
        IdempotencyStatus,
        IdempotentModel,
        SQLAlchemyStore,
    )
except ImportError:
    pass

__all__ = (
    # Types
    "RecordState",
    "IdempotencyRecord",
    "IdempotencyResult",
    "IdempotencyError",
    "IdempotencyErrorKind",
    # Store
    "Store",
    "StoreError",
    "FunctionalStore",
    "store_from",
    "MemoryStore",
    # Policy
    "Policy",
    "OnPending",
    "WAIT",
    "FAIL",
    "FORCE",
    # Spec & API
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
    # SQLAlchemy (optional)
    "IdempotencyMixin",
    "IdempotencyStatus",
    "IdempotentModel",
    "SQLAlchemyStore",
)

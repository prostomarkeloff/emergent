"""
Idempotency builder — fluent API over graph.
"""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable
from typing import Any

from kungfu import LazyCoroResult, Result

from emergent.idempotency._types import (
    IdempotencyResult,
    IdempotencyError,
)
from emergent.idempotency._graph import IdempotencyStorage
from emergent.idempotency._store import Record
from emergent.wire.axis.storage import MemoryStorage
from emergent.idempotency._policy import Policy


# ═══════════════════════════════════════════════════════════════════════════════
# Key Function Type
# ═══════════════════════════════════════════════════════════════════════════════

type KeyFn[K] = Callable[[K], str]


# ═══════════════════════════════════════════════════════════════════════════════
# Idempotent Builder
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(slots=True, frozen=True)
class Idempotent[K, T, E]:
    """Fluent idempotency builder."""

    _operation: Callable[[K], LazyCoroResult[T, E]]
    _key_fn: KeyFn[K] | None
    _storage: IdempotencyStorage | None
    _policy: Policy

    def key(self, fn: KeyFn[K]) -> Idempotent[K, T, E]:
        """Set key extraction function."""
        return Idempotent(
            _operation=self._operation,
            _key_fn=fn,
            _storage=self._storage,
            _policy=self._policy,
        )

    def storage(self, s: IdempotencyStorage) -> Idempotent[K, T, E]:
        """Set storage backend."""
        return Idempotent(
            _operation=self._operation,
            _key_fn=self._key_fn,
            _storage=s,
            _policy=self._policy,
        )

    def policy(self, p: Policy) -> Idempotent[K, T, E]:
        """Set idempotency policy."""
        return Idempotent(
            _operation=self._operation,
            _key_fn=self._key_fn,
            _storage=self._storage,
            _policy=p,
        )

    def build(self) -> IdempotentExecutor[K, T, E]:
        """Build executable."""
        if self._key_fn is None:
            raise ValueError("key() is required")

        storage: IdempotencyStorage = self._storage if self._storage is not None else MemoryStorage[str, Record[Any]]()

        return IdempotentExecutor(
            operation=self._operation,
            key_fn=self._key_fn,
            storage=storage,
            policy=self._policy,
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Idempotent Executor
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(slots=True, frozen=True)
class IdempotentExecutor[K, T, E]:
    """Compiled idempotent executor.

    Note: Thin wrapper — creates IdempotencySpec and runs graph.
    """

    operation: Callable[[K], LazyCoroResult[T, E]]
    key_fn: KeyFn[K]
    storage: IdempotencyStorage
    policy: Policy

    def run(
        self, input_val: K
    ) -> LazyCoroResult[IdempotencyResult[T], IdempotencyError[E]]:
        """Execute with idempotency via graph."""
        # Import here to avoid circular import
        from emergent.idempotency._graph import IdempotencySpec, run_idempotent

        key = self.key_fn(input_val)
        operation = self.operation
        storage = self.storage
        policy = self.policy

        async def execute() -> Result[IdempotencyResult[T], IdempotencyError[E]]:
            spec = IdempotencySpec(
                key=key,
                input_value=input_val,
                operation=operation,
                storage=storage,
                policy=policy,
            )
            return await run_idempotent(spec)

        return LazyCoroResult(execute)

    async def invalidate(self, input_val: K) -> bool:
        """Invalidate idempotency record."""
        from kungfu import Ok

        key = self.key_fn(input_val)
        result = await self.storage.delete(key)
        match result:
            case Ok(_):
                return True
            case _:
                return False


# ═══════════════════════════════════════════════════════════════════════════════
# idempotent() — Entry Point
# ═══════════════════════════════════════════════════════════════════════════════


def idempotent[K, T, E](
    operation: Callable[[K], LazyCoroResult[T, E]],
) -> Idempotent[K, T, E]:
    """Create idempotent wrapper for an operation.

    Example:
        from emergent.wire.axis.storage import MemoryStorage

        executor = (
            I.idempotent(fetch_user)
            .key(lambda uid: f"fetch_user:{uid.value}")
            .storage(MemoryStorage())  # optional, defaults to MemoryStorage
            .policy(I.Policy().with_ttl(seconds=3600))
            .build()
        )

        result = await executor.run(user_id)
    """
    return Idempotent(
        _operation=operation,
        _key_fn=None,
        _storage=None,
        _policy=Policy(),
    )


__all__ = (
    "Idempotent",
    "IdempotentExecutor",
    "idempotent",
)

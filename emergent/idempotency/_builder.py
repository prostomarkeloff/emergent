"""
Idempotency builder — fluent API over graph.
"""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable

from kungfu import LazyCoroResult, Result

from emergent.idempotency._types import (
    IdempotencyResult,
    IdempotencyError,
)
from emergent.idempotency._store import StoreAny, MemoryStore
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
    """
    Fluent idempotency builder.
    """
    _operation: Callable[[K], LazyCoroResult[T, E]]
    _key_fn: KeyFn[K] | None
    _store: StoreAny | None
    _policy: Policy

    def key(self, fn: KeyFn[K]) -> Idempotent[K, T, E]:
        """Set key extraction function."""
        return Idempotent(
            _operation=self._operation,
            _key_fn=fn,
            _store=self._store,
            _policy=self._policy,
        )

    def store(self, s: StoreAny) -> Idempotent[K, T, E]:
        """Set storage backend."""
        return Idempotent(
            _operation=self._operation,
            _key_fn=self._key_fn,
            _store=s,
            _policy=self._policy,
        )

    def policy(self, p: Policy) -> Idempotent[K, T, E]:
        """Set idempotency policy."""
        return Idempotent(
            _operation=self._operation,
            _key_fn=self._key_fn,
            _store=self._store,
            _policy=p,
        )

    def build(self) -> IdempotentExecutor[K, T, E]:
        """Build executable."""
        if self._key_fn is None:
            raise ValueError("key() is required")

        store: StoreAny = self._store if self._store is not None else MemoryStore()

        return IdempotentExecutor(
            operation=self._operation,
            key_fn=self._key_fn,
            store=store,
            policy=self._policy,
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Idempotent Executor
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass(slots=True, frozen=True)
class IdempotentExecutor[K, T, E]:
    """
    Compiled idempotent executor.

    Note: Thin wrapper — creates IdempotencySpec and runs graph.
    """
    operation: Callable[[K], LazyCoroResult[T, E]]
    key_fn: KeyFn[K]
    store: StoreAny
    policy: Policy

    def run(self, input_val: K) -> LazyCoroResult[IdempotencyResult[T], IdempotencyError[E]]:
        """Execute with idempotency via graph."""
        # Import here to avoid circular import
        from emergent.idempotency._graph import IdempotencySpec, run_idempotent

        key = self.key_fn(input_val)
        operation = self.operation
        store = self.store
        policy = self.policy

        async def execute() -> Result[IdempotencyResult[T], IdempotencyError[E]]:
            spec = IdempotencySpec(
                key=key,
                input_value=input_val,
                operation=operation,
                store=store,
                policy=policy,
            )
            return await run_idempotent(spec)

        return LazyCoroResult(execute)

    async def invalidate(self, input_val: K) -> bool:
        """Invalidate idempotency record."""
        from kungfu import Ok
        key = self.key_fn(input_val)
        result = await self.store.delete(key)
        match result:
            case Ok(deleted):
                return deleted
            case _:
                return False


# ═══════════════════════════════════════════════════════════════════════════════
# idempotent() — Entry Point
# ═══════════════════════════════════════════════════════════════════════════════

def idempotent[K, T, E](
    operation: Callable[[K], LazyCoroResult[T, E]],
) -> Idempotent[K, T, E]:
    """
    Create idempotent wrapper for an operation.

    Example:
        executor = (
            I.idempotent(fetch_user)
            .key(lambda uid: f"fetch_user:{uid.value}")
            .store(I.MemoryStore())
            .policy(I.Policy().with_ttl(seconds=3600))
            .build()
        )

        result = await executor.run(user_id)
    """
    return Idempotent(
        _operation=operation,
        _key_fn=None,
        _store=None,
        _policy=Policy(),
    )


__all__ = (
    "Idempotent",
    "IdempotentExecutor",
    "idempotent",
)

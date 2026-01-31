"""Memory providers — in-memory implementations for testing.

MemoryRelationalProvider — interpreted relational queries on list
MemoryKVProvider — in-memory key-value store
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from typing import Any, Callable, Generic, TypeVar

from emergent.wire.axis.query._relational import (
    RelationalQuerySet,
    Filter,
    OrderBy,
    Limit,
    Offset,
    Distinct,
)
from emergent.wire.axis.query._kv import (
    KVQuerySet,
    Get,
    Set,
    Delete,
    Exists,
    Scan,
    Keys,
)
from emergent.wire.axis.query._provider import NextId


T = TypeVar("T")


# ─── Memory Relational Provider ───────────────────────────────────────────────


class MemoryRelationalProvider(Generic[T]):
    """In-memory relational provider with transaction support.

    Interprets RelationalQuerySet on a list of entities.
    Supports atomic transactions via asyncio.Lock.

    Usage:
        provider = MemoryRelationalProvider[Transaction]()

        # Simple query
        result = await provider.fetch_many(query)

        # Atomic transaction
        async with provider.atomic():
            balance = await provider.fetch_many(balance_query)
            # ... compute ...
            await provider.insert(transaction)

        # With auto ID generation
        provider = MemoryRelationalProvider[User](
            next_id=PrefixedNextId("user_", SequenceNextId())
        )
        user = User(id=await provider.next_id(), name="Alice")
    """

    __slots__ = ("_data", "_key_fn", "_lock", "_next_id")

    def __init__(
        self,
        data: list[T] | None = None,
        key_fn: Callable[[T], Any] | None = None,
        next_id: NextId[Any] | None = None,
    ) -> None:
        self._data: list[T] = list(data) if data else []
        self._key_fn = key_fn
        self._lock = asyncio.Lock()
        self._next_id = next_id

    @asynccontextmanager
    async def atomic(self) -> AsyncIterator[None]:
        """Atomic transaction context.

        All operations within the context are serialized.

        Usage:
            async with provider.atomic():
                items = await provider.fetch_many(query)
                await provider.insert(new_item)
        """
        async with self._lock:
            yield

    async def next_id(self) -> Any:
        """Generate next ID in sequence.

        Requires next_id capability to be configured.

        Usage:
            provider = MemoryRelationalProvider[User](
                next_id=PrefixedNextId("user_", SequenceNextId())
            )
            user = User(id=await provider.next_id(), name="Alice")
        """
        if self._next_id is None:
            raise RuntimeError(
                "No next_id generator configured. "
                "Pass next_id= when creating the provider."
            )
        return await self._next_id.next_id()

    # ─── Data Management ──────────────────────────────────────────────────

    def add(self, entity: T) -> None:
        """Add entity to store."""
        self._data.append(entity)

    def clear(self) -> None:
        """Clear all data."""
        self._data.clear()

    @property
    def data(self) -> list[T]:
        """Access raw data."""
        return self._data

    # ─── Query Execution ──────────────────────────────────────────────────

    def _execute(self, query: RelationalQuerySet[T]) -> list[T]:
        """Execute query on data."""
        result = list(self._data)

        for op in query.ops:
            if isinstance(op, Filter):
                result = [item for item in result if op.expr.evaluate(item)]

            elif isinstance(op, OrderBy):
                for spec in reversed(op.specs):
                    result.sort(
                        key=lambda item: getattr(item, spec.field),
                        reverse=not spec.ascending,
                    )

            elif isinstance(op, Offset):
                result = result[op.count:]

            elif isinstance(op, Limit):
                result = result[:op.count]

            elif isinstance(op, Distinct):
                seen: set[Any] = set()
                unique: list[T] = []
                for item in result:
                    # Use tuple of all values as identity
                    if hasattr(item, "__dataclass_fields__"):
                        fields = getattr(item, "__dataclass_fields__")
                        key: Any = tuple(getattr(item, str(f)) for f in fields)
                    else:
                        key = id(item)
                    if key not in seen:
                        seen.add(key)
                        unique.append(item)
                result = unique

        return result

    async def fetch_one(self, query: RelationalQuerySet[T]) -> T | None:
        """Fetch single result."""
        results = self._execute(query.limit(1))
        return results[0] if results else None

    async def fetch_many(self, query: RelationalQuerySet[T]) -> list[T]:
        """Fetch all results."""
        return self._execute(query)

    async def count(self, query: RelationalQuerySet[T]) -> int:
        """Count results."""
        return len(self._execute(query))

    async def exists(self, query: RelationalQuerySet[T]) -> bool:
        """Check existence."""
        results = self._execute(query.limit(1))
        return len(results) > 0

    # ─── Mutations ────────────────────────────────────────────────────────

    async def insert(self, entity: T) -> T:
        """Insert entity."""
        self._data.append(entity)
        return entity

    async def update(self, entity: T) -> T:
        """Update entity (by key if key_fn set)."""
        if self._key_fn:
            key = self._key_fn(entity)
            for i, item in enumerate(self._data):
                if self._key_fn(item) == key:
                    self._data[i] = entity
                    return entity
        raise ValueError("Entity not found")

    async def delete(self, entity: T) -> None:
        """Delete entity."""
        if self._key_fn:
            key = self._key_fn(entity)
            self._data = [item for item in self._data if self._key_fn(item) != key]
        else:
            self._data.remove(entity)

    async def delete_where(self, query: RelationalQuerySet[T]) -> int:
        """Delete matching entities."""
        to_delete = set(id(item) for item in self._execute(query))
        original_len = len(self._data)
        self._data = [item for item in self._data if id(item) not in to_delete]
        return original_len - len(self._data)


# ─── Memory KV Provider ───────────────────────────────────────────────────────


class MemoryKVProvider(Generic[T]):
    """In-memory KV provider.

    Simple dict-based key-value store.
    Useful for testing.

    Usage:
        provider = MemoryKVProvider[User]()
        await provider.set(kv(User, key=lambda u: u.id).set("alice", user))
        result = await provider.get(kv(User, key=lambda u: u.id).get("alice"))
    """

    __slots__ = ("_data",)

    def __init__(self, data: dict[str, T] | None = None) -> None:
        self._data: dict[str, T] = dict(data) if data else {}

    @property
    def data(self) -> dict[str, T]:
        """Access raw data."""
        return self._data

    def clear(self) -> None:
        """Clear all data."""
        self._data.clear()

    async def get(self, query: KVQuerySet[T]) -> T | None:
        """Get by key."""
        if not isinstance(query.op, Get):
            raise TypeError(f"Expected Get op, got {type(query.op)}")
        return self._data.get(str(query.op.key))

    async def set(self, query: KVQuerySet[T]) -> None:
        """Set value."""
        if not isinstance(query.op, Set):
            raise TypeError(f"Expected Set op, got {type(query.op)}")
        self._data[str(query.op.key)] = query.op.value
        # TTL ignored in memory provider

    async def delete(self, query: KVQuerySet[T]) -> bool:
        """Delete by key."""
        if not isinstance(query.op, Delete):
            raise TypeError(f"Expected Delete op, got {type(query.op)}")
        key = str(query.op.key)
        if key in self._data:
            del self._data[key]
            return True
        return False

    async def exists(self, query: KVQuerySet[T]) -> bool:
        """Check existence."""
        if not isinstance(query.op, Exists):
            raise TypeError(f"Expected Exists op, got {type(query.op)}")
        return str(query.op.key) in self._data

    async def scan(self, query: KVQuerySet[T]) -> list[T]:
        """Scan by pattern."""
        if not isinstance(query.op, Scan):
            raise TypeError(f"Expected Scan op, got {type(query.op)}")
        import fnmatch
        pattern = query.op.pattern
        return [v for k, v in self._data.items() if fnmatch.fnmatch(k, pattern)]

    async def keys(self, query: KVQuerySet[T]) -> list[str]:
        """Get keys by pattern."""
        if not isinstance(query.op, Keys):
            raise TypeError(f"Expected Keys op, got {type(query.op)}")
        import fnmatch
        pattern = query.op.pattern
        return [k for k in self._data.keys() if fnmatch.fnmatch(k, pattern)]


__all__ = (
    "MemoryRelationalProvider",
    "MemoryKVProvider",
)

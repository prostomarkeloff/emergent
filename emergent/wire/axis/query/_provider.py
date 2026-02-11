"""Provider protocols — execute queries for specific spaces.

Provider is the Physical dimension of Query axis.
Each space has its own provider protocol.

    RelationalProvider — executes RelationalQuerySet
    KVProvider — executes KVQuerySet
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Sequence
from typing import Any, TypeVar, Protocol, Generic, runtime_checkable

from emergent.wire.axis.query._relational import RelationalQuerySet
from emergent.wire.axis.query._kv import KVQuerySet
from emergent.wire.axis.query._api import APIQuerySet
from emergent.wire.axis.query._sql import SQLRelationalQuerySet


T = TypeVar("T")
K = TypeVar("K")
V = TypeVar("V")


# ─── Relational Provider ──────────────────────────────────────────────────────


@runtime_checkable
class RelationalProvider(Protocol[T]):
    """Provider for RelationalQuerySet.

    Implements SQL-like query execution.
    """

    async def fetch_one(self, query: RelationalQuerySet[T]) -> T | None:
        """Fetch single result or None."""
        ...

    async def fetch_many(self, query: RelationalQuerySet[T]) -> list[T]:
        """Fetch all matching results."""
        ...

    async def count(self, query: RelationalQuerySet[T]) -> int:
        """Count matching results."""
        ...

    async def exists(self, query: RelationalQuerySet[T]) -> bool:
        """Check if any results exist."""
        ...

    async def aggregate(self, query: RelationalQuerySet[T]) -> dict[str, Any]:
        """Execute aggregate query.

        Returns dict mapping alias to aggregate value:
            {"total": 1000, "avg_balance": 100, "user_count": 10}

        Usage:
            q = (
                users
                .filter(lambda u: u.active == True)
                .aggregate(
                    total=lambda u: u.balance.sum(),
                    avg_balance=lambda u: u.balance.avg(),
                    user_count=lambda u: u.count(),
                )
            )
            result = await provider.aggregate(q)
        """
        ...


@runtime_checkable
class MutatingRelationalProvider(RelationalProvider[T], Protocol[T]):
    """Relational provider with mutation support."""

    async def insert(self, entity: T) -> T:
        """Insert new entity."""
        ...

    async def update(self, entity: T) -> T:
        """Update existing entity."""
        ...

    async def delete(self, entity: T) -> None:
        """Delete entity."""
        ...

    async def delete_where(self, query: RelationalQuerySet[T]) -> int:
        """Delete all matching. Returns count."""
        ...

    async def insert_many(self, entities: Sequence[T]) -> list[T]:
        """Bulk insert. Returns inserted entities."""
        ...

    async def upsert(self, entity: T) -> T:
        """Insert or update by key."""
        ...


@runtime_checkable
class SQLRelationalProvider(MutatingRelationalProvider[T], Protocol[T]):
    """Provider that supports SQL-specific operations.

    Extends MutatingRelationalProvider with:
    - delete_returning() — DELETE ... RETURNING

    The regular read methods (fetch_one, fetch_many, etc.) accept
    RelationalQuerySet. Use SQLRelationalQuerySet.to_relational()
    to strip SQL ops, or pass SQLRelationalQuerySet directly
    if the provider's implementation handles both.
    """

    async def delete_returning(self, query: SQLRelationalQuerySet[T]) -> list[T]:
        """DELETE ... RETURNING — delete and return deleted entities."""
        ...


# ─── KV Provider ──────────────────────────────────────────────────────────────


@runtime_checkable
class KVProvider(Protocol[K, V]):
    """Provider for KVQuerySet.

    Implements key-value operations.
    K = key type, V = value type.
    """

    async def get(self, query: KVQuerySet[K, V]) -> V | None:
        """Get value by key."""
        ...

    async def set(self, query: KVQuerySet[K, V]) -> None:
        """Set value."""
        ...

    async def delete(self, query: KVQuerySet[K, V]) -> bool:
        """Delete by key. Returns True if existed."""
        ...

    async def exists(self, query: KVQuerySet[K, V]) -> bool:
        """Check if key exists."""
        ...

    async def scan(self, query: KVQuerySet[K, V]) -> list[V]:
        """Scan by pattern."""
        ...

    async def keys(self, query: KVQuerySet[K, V]) -> list[K]:
        """Get keys by pattern."""
        ...


# ─── API Provider ────────────────────────────────────────────────────────────


@runtime_checkable
class APIProvider(Protocol[K, T]):
    """Provider for APIQuerySet.

    K = key type, T = entity type.
    Executes REST-ish API operations.
    """

    async def fetch_one(self, query: APIQuerySet[K, T]) -> T | None:
        """Execute get/list query, return single result."""
        ...

    async def fetch_many(self, query: APIQuerySet[K, T]) -> list[T]:
        """Execute list query, return all results."""
        ...

    async def execute(self, query: APIQuerySet[K, T]) -> T:
        """Execute create/update, return result."""
        ...

    async def delete(self, query: APIQuerySet[K, T]) -> bool:
        """Execute delete, return success."""
        ...


class APIListResult(Protocol[T]):
    """Result of list operation with pagination info."""

    @property
    def items(self) -> list[T]:
        """List of items."""
        ...

    @property
    def total(self) -> int | None:
        """Total count if available."""
        ...

    @property
    def next_cursor(self) -> str | None:
        """Next page cursor if available."""
        ...

    @property
    def has_more(self) -> bool:
        """Whether more pages exist."""
        ...


@runtime_checkable
class PaginatedAPIProvider(APIProvider[K, T], Protocol[K, T]):
    """API provider with pagination metadata."""

    async def fetch_page(self, query: APIQuerySet[K, T]) -> APIListResult[T]:
        """Execute list query, return result with pagination info."""
        ...


# ─── Capability Protocols ─────────────────────────────────────────────────────


class JoinCapability(Protocol):
    """Provider supports JOIN operations.

    Type-level marker for constraining provider input types.
    Not runtime_checkable — use for static typing only.
    """
    ...


class GroupByCapability(Protocol):
    """Provider supports GROUP BY.

    Type-level marker for constraining provider input types.
    """
    ...


class AggregateCapability(Protocol):
    """Provider supports aggregate operations.

    Type-level marker for constraining provider input types.
    """
    ...


class WindowCapability(Protocol):
    """Provider supports window functions.

    Type-level marker for constraining provider input types.
    """
    ...


@runtime_checkable
class TransactionCapability(Protocol):
    """Provider supports transactions."""

    async def begin(self) -> None: ...
    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...


# ─── ID Generation Capability ────────────────────────────────────────────────


ID = TypeVar("ID", covariant=True)


class NextId(Protocol[ID]):
    """Capability to generate next ID in sequence.

    Storage capability — providers can implement this to auto-generate IDs.

    Usage:
        provider = MemoryRelationalProvider[User](next_id=SequenceNextId())

        # In store
        user = User(id=await provider.next_id(), name="Alice")
        await provider.insert(user)
    """

    async def next_id(self) -> ID:
        """Generate next ID in sequence."""
        ...


class UuidNextId(NextId[str]):
    """Generate UUID strings."""

    __slots__ = ()

    async def next_id(self) -> str:
        return str(uuid.uuid4())


class SequenceNextId(NextId[int]):
    """Generate sequential integers starting from 1."""

    __slots__ = ("_counter", "_lock")

    def __init__(self, start: int = 1) -> None:
        self._counter = start - 1
        self._lock = asyncio.Lock()

    async def next_id(self) -> int:
        async with self._lock:
            self._counter += 1
            return self._counter


class PrefixedNextId(NextId[str], Generic[T]):
    """Wrap another NextId with a string prefix.

    Usage:
        next_id = PrefixedNextId("tx_", SequenceNextId())
        # Generates: "tx_1", "tx_2", "tx_3", ...
    """

    __slots__ = ("_prefix", "_inner")

    def __init__(self, prefix: str, inner: NextId[T]) -> None:
        self._prefix = prefix
        self._inner = inner

    async def next_id(self) -> str:
        inner_id = await self._inner.next_id()
        return f"{self._prefix}{inner_id}"


__all__ = (
    # Relational
    "RelationalProvider",
    "MutatingRelationalProvider",
    "SQLRelationalProvider",
    # KV
    "KVProvider",
    # API
    "APIProvider",
    "APIListResult",
    "PaginatedAPIProvider",
    # Capabilities
    "JoinCapability",
    "GroupByCapability",
    "AggregateCapability",
    "WindowCapability",
    "TransactionCapability",
    # ID Generation
    "NextId",
    "UuidNextId",
    "SequenceNextId",
    "PrefixedNextId",
)

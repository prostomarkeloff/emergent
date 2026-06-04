"""Memory providers — in-memory implementations for testing.

MemoryRelationalProvider — interpreted relational queries on list
MemoryKVProvider — in-memory key-value store
"""

from __future__ import annotations

import asyncio
import dataclasses
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Any, Callable, Generic, Never, TypeVar

from emergent._types import Result, Ok
from emergent.wire.axis.query._relational import (
    RelationalQuerySet,
    Aggregate,
)
from emergent.wire.axis.query._contexts import (
    MemoryQueryContext,
    MemoryQueryCompilable,
    MemoryAPIContext,
    MemoryAPICompilable,
)
from emergent.wire.compile._core import fold, ItemHandler
from emergent.wire.axis.query._aggregate import (
    AggregateSpec,
    AggHandler,
    Count,
    Sum,
    Avg,
    Min,
    Max,
    ArrayAgg,
    StringAgg,
    fold_aggregate,
)
from fnmatch import fnmatch

from emergent.wire.axis.query._kv import (
    KVQuerySet,
    KVGet,
    KVSet,
    KVDelete,
    Exists,
    Scan,
    Keys,
)
from emergent.wire.axis.query._api import (
    APIQuerySet,
    ListOp,
    GetOp,
    CreateOp,
    UpdateOp,
    DeleteOp,
    IncludeMod,
)
from emergent.wire.axis.query._provider import NextId


T = TypeVar("T")

type MemoryAggHandlers = dict[type, AggHandler[list[Any]]]
type AggResult = dict[str, Any]
type MemoryAPIHandlers = dict[type, ItemHandler[MemoryAPIContext]]


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
        """Atomic transaction context with rollback on error.

        All operations within the context are serialized.
        If an exception occurs, data is restored to pre-transaction state.

        Usage:
            async with provider.atomic():
                items = await provider.fetch_many(query)
                await provider.insert(new_item)
        """
        async with self._lock:
            snapshot = list(self._data)
            try:
                yield
            except BaseException:
                self._data[:] = snapshot
                raise

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

    def execute(self, query: RelationalQuerySet[T]) -> list[T]:
        """Execute query on data via fold() with MemoryQueryCompilable protocol."""
        ctx = MemoryQueryContext(data=list(self._data))
        result = fold(query.ops, ctx, MemoryQueryCompilable, "compile_memory_query")
        return result.data

    async def fetch_one(self, query: RelationalQuerySet[T]) -> T | None:
        """Fetch single result."""
        results = self.execute(query)
        return results[0] if results else None

    async def fetch_many(self, query: RelationalQuerySet[T]) -> list[T]:
        """Fetch all results."""
        return self.execute(query)

    async def count(self, query: RelationalQuerySet[T]) -> int:
        """Count results."""
        return len(self.execute(query))

    async def exists(self, query: RelationalQuerySet[T]) -> bool:
        """Check existence (short-circuits after first match)."""
        limited = query.limit(1)
        results = self.execute(limited)
        return len(results) > 0

    # ─── Mutations ────────────────────────────────────────────────────────

    async def insert(self, entity: T) -> T:
        """Insert entity."""
        self._data.append(entity)
        return entity

    async def update(self, entity: T) -> T:
        """Update entity by key."""
        if self._key_fn is None:
            raise TypeError("update() requires key_fn to identify entities")
        key = self._key_fn(entity)
        for i, item in enumerate(self._data):
            if self._key_fn(item) == key:
                self._data[i] = entity
                return entity
        raise ValueError(f"Entity with key {key!r} not found")

    async def delete(self, entity: T) -> None:
        """Delete entity."""
        if self._key_fn:
            key = self._key_fn(entity)
            self._data = [item for item in self._data if self._key_fn(item) != key]
        else:
            self._data.remove(entity)

    async def delete_where(self, query: RelationalQuerySet[T]) -> int:
        """Delete matching entities."""
        to_delete = set(id(item) for item in self.execute(query))
        original_len = len(self._data)
        self._data = [item for item in self._data if id(item) not in to_delete]
        return original_len - len(self._data)

    async def insert_many(self, entities: Sequence[T]) -> list[T]:
        """Bulk insert entities."""
        items = list(entities)
        self._data.extend(items)
        return items

    async def upsert(self, entity: T) -> T:
        """Insert or update by key."""
        if self._key_fn is None:
            raise TypeError("upsert() requires key_fn to identify entities")
        key = self._key_fn(entity)
        for i, item in enumerate(self._data):
            if self._key_fn(item) == key:
                self._data[i] = entity
                return entity
        self._data.append(entity)
        return entity

    # ─── Aggregation ──────────────────────────────────────────────────────

    async def aggregate(
        self,
        query: RelationalQuerySet[T],
        handlers: MemoryAggHandlers | None = None,
    ) -> AggResult:
        """Execute aggregate query.

        Args:
            query: Query with aggregate specs.
            handlers: Optional handler map for aggregate functions.
                      If None, uses built-in handlers. Pass custom handlers
                      to support custom AggregateFunc types.

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
            # {"total": 1000, "avg_balance": 100.0, "user_count": 10}
        """
        # Get filtered data (exclude Aggregate ops for data collection)
        non_agg_ops = tuple(op for op in query.ops if not isinstance(op, Aggregate))
        ctx = MemoryQueryContext(data=list(self._data))
        fold_result = fold(non_agg_ops, ctx, MemoryQueryCompilable, "compile_memory_query")
        data = fold_result.data

        agg_specs = query.aggregates
        h = handlers if handlers is not None else _make_memory_agg_handlers()

        result: AggResult = {}
        for spec in agg_specs:
            result[spec.alias] = fold_aggregate(spec, data, h)
        return result


def _get_non_null_values(data: list[Any], field: str) -> list[Any]:
    """Extract non-null field values from data list."""
    return [getattr(item, field) for item in data if getattr(item, field, None) is not None]


def _make_memory_agg_handlers() -> MemoryAggHandlers:
    """Build handler map for in-memory aggregate computation."""
    def handle_count(spec: AggregateSpec, data: list[Any]) -> Any:
        if spec.field is None:
            return len(data)
        return sum(1 for item in data if getattr(item, spec.field, None) is not None)

    def handle_sum(spec: AggregateSpec, data: list[Any]) -> Any:
        if spec.field is None:
            return None
        values = _get_non_null_values(data, spec.field)
        return sum(values) if values else None

    def handle_avg(spec: AggregateSpec, data: list[Any]) -> Any:
        if spec.field is None:
            return None
        values = _get_non_null_values(data, spec.field)
        return sum(values) / len(values) if values else None

    def handle_min(spec: AggregateSpec, data: list[Any]) -> Any:
        if spec.field is None:
            return None
        values = _get_non_null_values(data, spec.field)
        return min(values) if values else None

    def handle_max(spec: AggregateSpec, data: list[Any]) -> Any:
        if spec.field is None:
            return None
        values = _get_non_null_values(data, spec.field)
        return max(values) if values else None

    def handle_array_agg(spec: AggregateSpec, data: list[Any]) -> Any:
        if spec.field is None:
            return []
        return [getattr(item, spec.field) for item in data]

    def handle_string_agg(spec: AggregateSpec, data: list[Any]) -> Any:
        if not isinstance(spec.func, StringAgg):
            return ""
        sep = spec.func.separator
        if spec.field is None:
            return ""
        values = [str(getattr(item, spec.field)) for item in data if getattr(item, spec.field, None) is not None]
        return sep.join(values)

    return {
        Count: handle_count,
        Sum: handle_sum,
        Avg: handle_avg,
        Min: handle_min,
        Max: handle_max,
        ArrayAgg: handle_array_agg,
        StringAgg: handle_string_agg,
    }


# ─── Memory KV Provider ───────────────────────────────────────────────────────


K = TypeVar("K")
V = TypeVar("V")

type KVData[Kk, Vv] = dict[Kk, Vv]


class MemoryKVProvider(Generic[K, V]):
    """In-memory KV provider.

    Simple dict-based key-value store with direct dispatch.
    Generic over K (key type) and V (value type).
    Returns Result[T, Never] — memory KV never fails.

    Usage:
        provider = MemoryKVProvider[str, User]()
        await provider.set(kv(User, key=lambda u: u.name).set("alice", user))
        result = await provider.get(kv(User, key=lambda u: u.name).get("alice"))
    """

    __slots__ = ("_data",)

    def __init__(self, data: KVData[K, V] | None = None) -> None:
        self._data: KVData[K, V] = dict(data) if data else {}

    @property
    def data(self) -> KVData[K, V]:
        """Access raw data."""
        return self._data

    def clear(self) -> None:
        """Clear all data."""
        self._data.clear()

    async def get(self, query: KVQuerySet[K, V]) -> Result[V | None, Never]:
        """Get by key."""
        match query.op:
            case KVGet(key=key):
                return Ok(self._data.get(key))
            case _:
                raise TypeError(f"get() requires KVGet op, got {type(query.op)}")

    async def set(self, query: KVQuerySet[K, V]) -> Result[None, Never]:
        """Set value."""
        match query.op:
            case KVSet(key=key, value=value):
                self._data[key] = value
                return Ok(None)
            case _:
                raise TypeError(f"set() requires KVSet op, got {type(query.op)}")

    async def delete(self, query: KVQuerySet[K, V]) -> Result[bool, Never]:
        """Delete by key."""
        match query.op:
            case KVDelete(key=key):
                existed = key in self._data
                self._data.pop(key, None)
                return Ok(existed)
            case _:
                raise TypeError(f"delete() requires KVDelete op, got {type(query.op)}")

    async def exists(self, query: KVQuerySet[K, V]) -> Result[bool, Never]:
        """Check existence."""
        match query.op:
            case Exists(key=key):
                return Ok(key in self._data)
            case _:
                raise TypeError(f"exists() requires Exists op, got {type(query.op)}")

    async def scan(self, query: KVQuerySet[K, V]) -> Result[list[V], Never]:
        """Scan by pattern."""
        match query.op:
            case Scan(pattern=pattern):
                result = [v for k, v in self._data.items() if fnmatch(str(k), pattern)]
                return Ok(result)
            case _:
                raise TypeError(f"scan() requires Scan op, got {type(query.op)}")

    async def keys(self, query: KVQuerySet[K, V]) -> Result[list[K], Never]:
        """Get keys by pattern."""
        match query.op:
            case Keys(pattern=pattern):
                result = [k for k in self._data if fnmatch(str(k), pattern)]
                return Ok(result)
            case _:
                raise TypeError(f"keys() requires Keys op, got {type(query.op)}")


# ─── Memory API Provider ─────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class MemoryAPIListResult(Generic[T]):
    """Concrete APIListResult for memory provider."""

    items: list[T]
    total: int | None = None
    next_cursor: str | None = None
    has_more: bool = False


AK = TypeVar("AK")  # API key type


def _include_mod_memory_raise(
    mod: Any, ctx: MemoryAPIContext,
) -> MemoryAPIContext:
    """Handler override: IncludeMod raises for memory provider."""
    raise TypeError(
        "IncludeMod requires relation metadata. "
        "Memory provider does not support include."
    )


_MEMORY_API_INCLUDE_HANDLER: MemoryAPIHandlers = {
    IncludeMod: _include_mod_memory_raise,
}


class MemoryAPIProvider(Generic[AK, T]):
    """In-memory API provider.

    AK = key type, T = entity type.
    Interprets APIQuerySet on a list of entities.
    Implements APIProvider and PaginatedAPIProvider protocols.

    Usage:
        provider = MemoryAPIProvider[int, User](key_fn=lambda u: u.id)

        # Create
        q = api(User, key=lambda u: u.id).create(User(id=1, name="Alice"))
        user = await provider.execute(q)

        # List with filters
        q = api(User, key=lambda u: u.id).list().filter(lambda u: u.active == True).page(1, per_page=10)
        users = await provider.fetch_many(q)

        # Paginated
        result = await provider.fetch_page(q)
        print(result.items, result.total, result.has_more)
    """

    __slots__ = ("_data", "_key_fn", "_next_id")

    def __init__(
        self,
        data: list[T] | None = None,
        key_fn: Callable[[T], AK] | None = None,
        next_id: NextId[Any] | None = None,
    ) -> None:
        self._data: list[T] = list(data) if data else []
        self._key_fn = key_fn
        self._next_id = next_id

    @property
    def data(self) -> list[T]:
        """Access raw data."""
        return self._data

    def clear(self) -> None:
        """Clear all data."""
        self._data.clear()

    # ─── Modifier Application ─────────────────────────────────────────────

    def _apply_mods(
        self, data: list[T], query: APIQuerySet[AK, T]
    ) -> tuple[list[T], int | None, bool]:
        """Apply all mods via fold() and return typed result.

        Fold operates on list[object] (MemoryAPIContext erases T).
        Items remain T because fold only filters/sorts/slices — never adds
        foreign items. list invariance prevents expressing this in the type
        system, so the single assignment below is the unavoidable bridge.
        """
        ctx = MemoryAPIContext(data=list(data))
        result = fold(
            query.mods, ctx,
            MemoryAPICompilable, "compile_memory_api",
            _MEMORY_API_INCLUDE_HANDLER,
        )
        # Fold preserves element types (only filters/sorts/slices).
        # list is invariant so list[object] → list[T] cannot be expressed.
        items: list[T] = result.data
        return items, result.total, result.has_more

    # ─── Read Operations ──────────────────────────────────────────────────

    async def fetch_one(self, query: APIQuerySet[AK, T]) -> T | None:
        """Execute get query, return single result."""
        match query.op:
            case GetOp(id=entity_id):
                if self._key_fn is None:
                    raise TypeError("fetch_one(GetOp) requires key_fn")
                return next(
                    (item for item in self._data if self._key_fn(item) == entity_id),
                    None,
                )
            case ListOp():
                items, _, _ = self._apply_mods(self._data, query)
                return items[0] if items else None
            case _:
                raise TypeError(f"fetch_one() expects GetOp or ListOp, got {type(query.op)}")

    async def fetch_many(self, query: APIQuerySet[AK, T]) -> list[T]:
        """Execute list query, return all results."""
        if not isinstance(query.op, ListOp):
            raise TypeError(f"fetch_many() expects ListOp, got {type(query.op)}")
        items, _, _ = self._apply_mods(self._data, query)
        return items

    async def fetch_page(self, query: APIQuerySet[AK, T]) -> MemoryAPIListResult[T]:
        """Execute list query, return result with pagination info."""
        if not isinstance(query.op, ListOp):
            raise TypeError(f"fetch_page() expects ListOp, got {type(query.op)}")
        items, total, has_more = self._apply_mods(self._data, query)
        return MemoryAPIListResult(
            items=items,
            total=total if total is not None else len(items),
            has_more=has_more,
        )

    # ─── Write Operations ─────────────────────────────────────────────────

    async def execute(self, query: APIQuerySet[AK, T]) -> T:
        """Execute create/update, return result."""
        match query.op:
            case CreateOp(entity=entity):
                self._data.append(entity)
                return entity

            case UpdateOp(id=entity_id, entity=entity, partial=partial):
                if self._key_fn is None:
                    raise TypeError("execute(UpdateOp) requires key_fn")
                for i, item in enumerate(self._data):
                    if self._key_fn(item) == entity_id:
                        if partial:
                            # Merge non-None fields from update into existing
                            updates = {
                                f.name: getattr(entity, f.name)
                                for f in dataclasses.fields(entity)
                                if getattr(entity, f.name) is not None
                            }
                            merged = dataclasses.replace(item, **updates)
                            self._data[i] = merged
                            return merged
                        else:
                            self._data[i] = entity
                            return entity
                raise ValueError(f"Entity with id {entity_id} not found")

            case _:
                raise TypeError(f"execute() expects CreateOp or UpdateOp, got {type(query.op)}")

    async def delete(self, query: APIQuerySet[AK, T]) -> bool:
        """Execute delete, return success."""
        if not isinstance(query.op, DeleteOp):
            raise TypeError(f"delete() expects DeleteOp, got {type(query.op)}")
        if self._key_fn is None:
            raise TypeError("delete(DeleteOp) requires key_fn")
        entity_id = query.op.id
        original_len = len(self._data)
        self._data = [item for item in self._data if self._key_fn(item) != entity_id]
        return len(self._data) < original_len

    # ─── ID Generation ────────────────────────────────────────────────────

    async def next_id(self) -> Any:
        """Generate next ID in sequence."""
        if self._next_id is None:
            raise RuntimeError(
                "No next_id generator configured. "
                "Pass next_id= when creating the provider."
            )
        return await self._next_id.next_id()


__all__ = (
    "MemoryRelationalProvider",
    "MemoryKVProvider",
    "MemoryAPIProvider",
    "MemoryAPIListResult",
)

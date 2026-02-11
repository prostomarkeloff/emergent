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
from typing import Any, Callable, Generic, TypeVar

from emergent.wire.axis.query._relational import (
    RelationalQuerySet,
    Aggregate,
)
from emergent.wire.axis.query._fold import MEMORY_DIALECT
from emergent.wire.axis.query._aggregate import (
    Count,
    Sum,
    Avg,
    Min,
    Max,
    ArrayAgg,
    StringAgg,
)
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
    FilterMod,
    OrderMod,
    PageMod,
    CursorMod,
    OffsetMod,
    SelectMod,
    SearchMod,
    IncludeMod,
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
        """Execute query on data via fold_query."""
        return MEMORY_DIALECT.fold(query.ops, list(self._data))

    async def fetch_one(self, query: RelationalQuerySet[T]) -> T | None:
        """Fetch single result."""
        results = self._execute(query)
        return results[0] if results else None

    async def fetch_many(self, query: RelationalQuerySet[T]) -> list[T]:
        """Fetch all results."""
        return self._execute(query)

    async def count(self, query: RelationalQuerySet[T]) -> int:
        """Count results."""
        return len(self._execute(query))

    async def exists(self, query: RelationalQuerySet[T]) -> bool:
        """Check existence."""
        results = self._execute(query)
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
        to_delete = set(id(item) for item in self._execute(query))
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

    async def aggregate(self, query: RelationalQuerySet[T]) -> dict[str, Any]:
        """Execute aggregate query.

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
        data = MEMORY_DIALECT.fold(non_agg_ops, list(self._data))

        # Use introspection property from RelationalMixin
        agg_specs = query.aggregates

        # Compute aggregates using pattern matching on typed AggregateFunc
        result: dict[str, Any] = {}
        for spec in agg_specs:
            match spec.func:
                case Count():
                    if spec.field is None:
                        # COUNT(*) - count all rows
                        result[spec.alias] = len(data)
                    else:
                        # COUNT(field) - count non-null values
                        result[spec.alias] = sum(
                            1 for item in data
                            if getattr(item, spec.field, None) is not None
                        )

                case Sum():
                    if spec.field is None:
                        result[spec.alias] = None
                    else:
                        values = [
                            getattr(item, spec.field)
                            for item in data
                            if getattr(item, spec.field) is not None
                        ]
                        result[spec.alias] = sum(values) if values else None

                case Avg():
                    if spec.field is None:
                        result[spec.alias] = None
                    else:
                        values = [
                            getattr(item, spec.field)
                            for item in data
                            if getattr(item, spec.field) is not None
                        ]
                        result[spec.alias] = (
                            sum(values) / len(values) if values else None
                        )

                case Min():
                    if spec.field is None:
                        result[spec.alias] = None
                    else:
                        values = [
                            getattr(item, spec.field)
                            for item in data
                            if getattr(item, spec.field) is not None
                        ]
                        result[spec.alias] = min(values) if values else None

                case Max():
                    if spec.field is None:
                        result[spec.alias] = None
                    else:
                        values = [
                            getattr(item, spec.field)
                            for item in data
                            if getattr(item, spec.field) is not None
                        ]
                        result[spec.alias] = max(values) if values else None

                case ArrayAgg():
                    if spec.field is None:
                        result[spec.alias] = []
                    else:
                        result[spec.alias] = [
                            getattr(item, spec.field)
                            for item in data
                        ]

                case StringAgg(separator=sep):
                    if spec.field is None:
                        result[spec.alias] = ""
                    else:
                        values = [
                            str(getattr(item, spec.field))
                            for item in data
                            if getattr(item, spec.field) is not None
                        ]
                        result[spec.alias] = sep.join(values)

                case _:
                    raise TypeError(f"Unsupported aggregate: {type(spec.func)}")

        return result


# ─── Memory KV Provider ───────────────────────────────────────────────────────


K = TypeVar("K")
V = TypeVar("V")


class MemoryKVProvider(Generic[K, V]):
    """In-memory KV provider.

    Simple dict-based key-value store.
    Generic over K (key type) and V (value type).

    Usage:
        provider = MemoryKVProvider[str, User]()
        await provider.set(kv(User, key=lambda u: u.name).set("alice", user))
        result = await provider.get(kv(User, key=lambda u: u.name).get("alice"))
    """

    __slots__ = ("_data",)

    def __init__(self, data: dict[K, V] | None = None) -> None:
        self._data: dict[K, V] = dict(data) if data else {}

    @property
    def data(self) -> dict[K, V]:
        """Access raw data."""
        return self._data

    def clear(self) -> None:
        """Clear all data."""
        self._data.clear()

    async def get(self, query: KVQuerySet[K, V]) -> V | None:
        """Get by key."""
        if not isinstance(query.op, KVGet):
            raise TypeError(f"Expected KVGet op, got {type(query.op)}")
        return self._data.get(query.op.key)

    async def set(self, query: KVQuerySet[K, V]) -> None:
        """Set value."""
        if not isinstance(query.op, KVSet):
            raise TypeError(f"Expected KVSet op, got {type(query.op)}")
        self._data[query.op.key] = query.op.value
        # TTL ignored in memory provider

    async def delete(self, query: KVQuerySet[K, V]) -> bool:
        """Delete by key."""
        if not isinstance(query.op, KVDelete):
            raise TypeError(f"Expected KVDelete op, got {type(query.op)}")
        key = query.op.key
        if key in self._data:
            del self._data[key]
            return True
        return False

    async def exists(self, query: KVQuerySet[K, V]) -> bool:
        """Check existence."""
        if not isinstance(query.op, Exists):
            raise TypeError(f"Expected Exists op, got {type(query.op)}")
        return query.op.key in self._data

    async def scan(self, query: KVQuerySet[K, V]) -> list[V]:
        """Scan by pattern (matches against str(key))."""
        if not isinstance(query.op, Scan):
            raise TypeError(f"Expected Scan op, got {type(query.op)}")
        import fnmatch
        pattern = query.op.pattern
        return [v for k, v in self._data.items() if fnmatch.fnmatch(str(k), pattern)]

    async def keys(self, query: KVQuerySet[K, V]) -> list[K]:
        """Get keys by pattern (matches against str(key))."""
        if not isinstance(query.op, Keys):
            raise TypeError(f"Expected Keys op, got {type(query.op)}")
        import fnmatch
        pattern = query.op.pattern
        return [k for k in self._data.keys() if fnmatch.fnmatch(str(k), pattern)]


# ─── Memory API Provider ─────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class MemoryAPIListResult(Generic[T]):
    """Concrete APIListResult for memory provider."""

    items: list[T]
    total: int | None = None
    next_cursor: str | None = None
    has_more: bool = False


AK = TypeVar("AK")  # API key type


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

    def _apply_mods(self, data: list[T], query: APIQuerySet[AK, T]) -> list[T]:
        """Apply all modifiers to data list."""
        result = list(data)

        for mod in query.mods:
            match mod:
                case FilterMod(expr=expr):
                    result = [item for item in result if expr.evaluate(item)]

                case OrderMod(specs=specs):
                    for spec in reversed(specs):
                        result.sort(
                            key=lambda item, _f=spec.field: getattr(item, _f),
                            reverse=not spec.ascending,
                        )

                case SearchMod(query=search_query):
                    search_lower = search_query.lower()
                    result = [
                        item for item in result
                        if any(
                            search_lower in str(getattr(item, f.name, "")).lower()
                            for f in dataclasses.fields(item)  # type: ignore[arg-type]
                        )
                    ]

                case SelectMod(fields=fields):
                    result = [
                        {f: getattr(item, f) for f in fields}  # type: ignore[misc]
                        for item in result
                    ]

                case IncludeMod():
                    raise TypeError(
                        "IncludeMod requires relation metadata. "
                        "Memory provider does not support include."
                    )

                case PageMod() | CursorMod() | OffsetMod():
                    pass  # pagination handled separately

        return result

    def _apply_pagination(
        self, data: list[T], query: APIQuerySet[AK, T]
    ) -> tuple[list[T], int, bool]:
        """Apply pagination. Returns (page_items, total, has_more)."""
        total = len(data)

        for mod in query.mods:
            match mod:
                case PageMod(page=page, per_page=per_page):
                    start = (page - 1) * per_page
                    end = start + per_page
                    return data[start:end], total, end < total

                case OffsetMod(offset=offset, limit=limit):
                    end = offset + limit
                    return data[offset:end], total, end < total

                case CursorMod(cursor=cursor, limit=limit):
                    # Simple cursor = index as string
                    try:
                        start = int(cursor)
                    except (ValueError, TypeError):
                        start = 0
                    end = start + limit
                    return data[start:end], total, end < total

        return data, total, False

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
                filtered = self._apply_mods(self._data, query)
                return filtered[0] if filtered else None
            case _:
                raise TypeError(f"fetch_one() expects GetOp or ListOp, got {type(query.op)}")

    async def fetch_many(self, query: APIQuerySet[AK, T]) -> list[T]:
        """Execute list query, return all results."""
        if not isinstance(query.op, ListOp):
            raise TypeError(f"fetch_many() expects ListOp, got {type(query.op)}")
        filtered = self._apply_mods(self._data, query)
        items, _, _ = self._apply_pagination(filtered, query)
        return items

    async def fetch_page(self, query: APIQuerySet[AK, T]) -> MemoryAPIListResult[T]:
        """Execute list query, return result with pagination info."""
        if not isinstance(query.op, ListOp):
            raise TypeError(f"fetch_page() expects ListOp, got {type(query.op)}")
        filtered = self._apply_mods(self._data, query)
        items, total, has_more = self._apply_pagination(filtered, query)
        return MemoryAPIListResult(
            items=items,
            total=total,
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
                                for f in dataclasses.fields(entity)  # type: ignore[arg-type]
                                if getattr(entity, f.name) is not None
                            }
                            merged = dataclasses.replace(item, **updates)  # type: ignore[type-var]
                            self._data[i] = merged
                            return merged  # type: ignore[return-value]
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

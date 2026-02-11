"""Store — bundled QuerySet + Provider.

Store = QuerySet × Provider for convenience.
Instead of passing provider to every call, bundle them together.

    # Relational store
    users = relational_store(User, sql_provider)
    result = await users.filter(lambda u: u.active).fetch_many()

    # KV store
    cache = kv_store(User, key=lambda u: u.id, provider=redis_provider)
    user = await cache.get("alice")
"""

from __future__ import annotations

from typing import Any, Callable, Generic, TypeVar

K = TypeVar("K")
V = TypeVar("V")

from emergent.wire.axis.query._expr import Expr
from emergent.wire.axis.query._proxy import EntityProxy, FieldProxy, OrderSpec
from emergent.wire.axis.query._relational import RelationalQuerySet, relational
from emergent.wire.axis.query._aggregate import AggregateExpr
from emergent.wire.axis.query._kv import kv
from emergent.wire.axis.query._api import api, APIQuerySet
from emergent.wire.axis.query._provider import (
    RelationalProvider,
    MutatingRelationalProvider,
    KVProvider,
    APIProvider,
)

AK = TypeVar("AK")  # API key type


T = TypeVar("T")
Other = TypeVar("Other")


# ─── Relational Store ─────────────────────────────────────────────────────────


class RelationalStore(Generic[T]):
    """Relational QuerySet + Provider bundled.

    Usage:
        users = relational_store(User, sql_provider)

        # Query + execute in one chain
        result = await users.filter(lambda u: u.active).fetch_many()
        count = await users.filter(lambda u: u.balance > 100).count()
    """

    __slots__ = ("_entity", "_provider")

    def __init__(
        self,
        entity: type[T],
        provider: MutatingRelationalProvider[T],
    ) -> None:
        self._entity = entity
        self._provider = provider

    @property
    def entity(self) -> type[T]:
        return self._entity

    # ─── Query Building → BoundRelationalQuerySet ─────────────────────────

    def query(self) -> BoundRelationalQuerySet[T]:
        """Start empty query."""
        return BoundRelationalQuerySet(relational(self._entity), self._provider)

    def filter(
        self, predicate: Callable[[EntityProxy[T]], Expr]
    ) -> BoundRelationalQuerySet[T]:
        """Start with filter."""
        return BoundRelationalQuerySet(
            relational(self._entity).filter(predicate),
            self._provider,
        )

    def where(
        self, predicate: Callable[[EntityProxy[T]], Expr]
    ) -> BoundRelationalQuerySet[T]:
        """Alias for filter."""
        return self.filter(predicate)

    def order_by(
        self, *order_fns: Callable[[EntityProxy[T]], FieldProxy | OrderSpec]
    ) -> BoundRelationalQuerySet[T]:
        """Start with ordering."""
        return BoundRelationalQuerySet(
            relational(self._entity).order_by(*order_fns),
            self._provider,
        )

    def limit(self, count: int) -> BoundRelationalQuerySet[T]:
        """Start with limit."""
        return BoundRelationalQuerySet(
            relational(self._entity).limit(count),
            self._provider,
        )

    def select(
        self, *field_fns: Callable[[EntityProxy[T]], FieldProxy]
    ) -> BoundRelationalQuerySet[T]:
        """Start with projection."""
        return BoundRelationalQuerySet(
            relational(self._entity).select(*field_fns),
            self._provider,
        )

    def distinct(self) -> BoundRelationalQuerySet[T]:
        """Start with distinct."""
        return BoundRelationalQuerySet(
            relational(self._entity).distinct(),
            self._provider,
        )

    def all(self) -> BoundRelationalQuerySet[T]:
        """All entities (no filter)."""
        return self.query()

    # ─── Direct CRUD ──────────────────────────────────────────────────────

    async def insert(self, entity: T) -> T:
        """Insert new entity."""
        return await self._provider.insert(entity)

    async def update(self, entity: T) -> T:
        """Update entity."""
        return await self._provider.update(entity)

    async def delete(self, entity: T) -> None:
        """Delete entity."""
        await self._provider.delete(entity)


class BoundRelationalQuerySet(Generic[T]):
    """RelationalQuerySet bound to provider — chainable + executable."""

    __slots__ = ("_query", "_provider")

    def __init__(
        self,
        query: RelationalQuerySet[T],
        provider: RelationalProvider[T],
    ) -> None:
        self._query = query
        self._provider = provider

    # ─── Chainable (returns BoundRelationalQuerySet) ──────────────────────

    def filter(
        self, predicate: Callable[[EntityProxy[T]], Expr]
    ) -> BoundRelationalQuerySet[T]:
        return BoundRelationalQuerySet(self._query.filter(predicate), self._provider)

    def where(
        self, predicate: Callable[[EntityProxy[T]], Expr]
    ) -> BoundRelationalQuerySet[T]:
        return self.filter(predicate)

    def order_by(
        self, *order_fns: Callable[[EntityProxy[T]], FieldProxy | OrderSpec]
    ) -> BoundRelationalQuerySet[T]:
        return BoundRelationalQuerySet(self._query.order_by(*order_fns), self._provider)

    def limit(self, count: int) -> BoundRelationalQuerySet[T]:
        return BoundRelationalQuerySet(self._query.limit(count), self._provider)

    def offset(self, count: int) -> BoundRelationalQuerySet[T]:
        return BoundRelationalQuerySet(self._query.offset(count), self._provider)

    def paginate(self, page: int, per_page: int) -> BoundRelationalQuerySet[T]:
        return BoundRelationalQuerySet(self._query.paginate(page, per_page), self._provider)

    def select(
        self, *field_fns: Callable[[EntityProxy[T]], FieldProxy]
    ) -> BoundRelationalQuerySet[T]:
        return BoundRelationalQuerySet(self._query.select(*field_fns), self._provider)

    def distinct(self) -> BoundRelationalQuerySet[T]:
        return BoundRelationalQuerySet(self._query.distinct(), self._provider)

    def join(
        self,
        target: type[Other],
        on: Callable[[EntityProxy[T], EntityProxy[Other]], Expr],
        *,
        tablename: str | None = None,
    ) -> BoundRelationalQuerySet[T]:
        return BoundRelationalQuerySet(self._query.join(target, on, tablename=tablename), self._provider)

    def left_join(
        self,
        target: type[Other],
        on: Callable[[EntityProxy[T], EntityProxy[Other]], Expr],
        *,
        tablename: str | None = None,
    ) -> BoundRelationalQuerySet[T]:
        return BoundRelationalQuerySet(self._query.left_join(target, on, tablename=tablename), self._provider)

    def group_by(
        self, *field_fns: Callable[[EntityProxy[T]], FieldProxy]
    ) -> BoundRelationalQuerySet[T]:
        return BoundRelationalQuerySet(self._query.group_by(*field_fns), self._provider)

    def having(
        self, predicate: Callable[[EntityProxy[T]], Expr]
    ) -> BoundRelationalQuerySet[T]:
        return BoundRelationalQuerySet(self._query.having(predicate), self._provider)

    def aggregate(
        self,
        **aggregates: Callable[[EntityProxy[T]], AggregateExpr],
    ) -> BoundRelationalQuerySet[T]:
        """Add aggregates (chainable).

        Usage:
            result = await users.filter(...).aggregate(
                total=lambda u: u.balance.sum(),
                count=lambda u: u.count(),
            ).fetch_aggregates()
        """
        return BoundRelationalQuerySet(self._query.aggregate(**aggregates), self._provider)

    # ─── Terminal (executes) ──────────────────────────────────────────────

    async def fetch_one(self) -> T | None:
        """Execute, return single result."""
        return await self._provider.fetch_one(self._query)

    async def fetch_many(self) -> list[T]:
        """Execute, return all results."""
        return await self._provider.fetch_many(self._query)

    async def count(self) -> int:
        """Execute, return count."""
        return await self._provider.count(self._query)

    async def exists(self) -> bool:
        """Execute, check existence."""
        return await self._provider.exists(self._query)

    async def first(self) -> T | None:
        """Fetch first result."""
        return await self.limit(1).fetch_one()

    async def fetch_aggregates(self) -> dict[str, Any]:
        """Execute aggregate query.

        Usage:
            result = await users.filter(lambda u: u.active).aggregate(
                total=lambda u: u.balance.sum(),
                avg_balance=lambda u: u.balance.avg(),
                user_count=lambda u: u.count(),
            ).fetch_aggregates()
            # {"total": 1000, "avg_balance": 100.0, "user_count": 10}
        """
        return await self._provider.aggregate(self._query)

    # ─── Access raw query ─────────────────────────────────────────────────

    @property
    def query(self) -> RelationalQuerySet[T]:
        return self._query


def relational_store(
    entity: type[T],
    provider: MutatingRelationalProvider[T],
) -> RelationalStore[T]:
    """Create relational store.

    Usage:
        users = relational_store(User, sql_provider)
        active = await users.filter(lambda u: u.active).fetch_many()
    """
    return RelationalStore(entity, provider)


# ─── KV Store ─────────────────────────────────────────────────────────────────


class KVStore(Generic[K, V]):
    """KV QuerySet + Provider bundled.

    K = key type, V = value type.

    Usage:
        cache = kv_store(User, key=lambda u: u.id, provider=redis)

        user = await cache.get("alice")
        await cache.set("alice", user)
        await cache.delete("alice")
    """

    __slots__ = ("_entity", "_key_fn", "_provider")

    def __init__(
        self,
        entity: type[V],
        key_fn: Callable[[V], K],
        provider: KVProvider[K, V],
    ) -> None:
        self._entity = entity
        self._key_fn = key_fn
        self._provider = provider

    @property
    def entity(self) -> type[V]:
        return self._entity

    # ─── KV Operations ────────────────────────────────────────────────────

    async def get(self, key: K) -> V | None:
        """Get by key."""
        q = kv(self._entity, self._key_fn).get(key)
        return await self._provider.get(q)

    async def set(self, key: K, value: V, ttl: int | None = None) -> None:
        """Set value."""
        q = kv(self._entity, self._key_fn).set(key, value, ttl)
        await self._provider.set(q)

    async def put(self, entity: V, ttl: int | None = None) -> None:
        """Set using entity's key."""
        key = self._key_fn(entity)
        await self.set(key, entity, ttl)

    async def delete(self, key: K) -> bool:
        """Delete by key."""
        q = kv(self._entity, self._key_fn).delete(key)
        return await self._provider.delete(q)

    async def exists(self, key: K) -> bool:
        """Check if key exists."""
        q = kv(self._entity, self._key_fn).exists(key)
        return await self._provider.exists(q)

    async def scan(self, pattern: str) -> list[V]:
        """Scan by pattern."""
        q = kv(self._entity, self._key_fn).scan(pattern)
        return await self._provider.scan(q)

    async def keys(self, pattern: str = "*") -> list[K]:
        """Get keys by pattern."""
        q = kv(self._entity, self._key_fn).keys(pattern)
        return await self._provider.keys(q)


def kv_store(
    entity: type[V],
    key: Callable[[V], K],
    provider: KVProvider[K, V],
) -> KVStore[K, V]:
    """Create KV store.

    Usage:
        cache = kv_store(User, key=lambda u: u.id, provider=redis)
        user = await cache.get("alice")
    """
    return KVStore(entity, key, provider)


# ─── API Store ────────────────────────────────────────────────────────────────


class APIStore(Generic[AK, T]):
    """API QuerySet + Provider bundled.

    AK = key type, T = entity type.

    Usage:
        users = api_store(User, provider, key=lambda u: u.id)

        user = await users.get(123)
        all_active = await users.list().filter(lambda u: u.active == True).fetch_many()
        created = await users.create(User(id=0, name="Alice"))
    """

    __slots__ = ("_entity", "_provider", "_key_fn")

    def __init__(
        self,
        entity: type[T],
        provider: APIProvider[AK, T],
        key_fn: Callable[[T], AK],
    ) -> None:
        self._entity = entity
        self._provider = provider
        self._key_fn = key_fn

    @property
    def entity(self) -> type[T]:
        return self._entity

    # ─── Read ──────────────────────────────────────────────────────────────

    def list(self) -> BoundAPIQuerySet[AK, T]:
        """Start list query."""
        return BoundAPIQuerySet(api(self._entity, key=self._key_fn).list(), self._provider)

    async def get(self, id: AK) -> T | None:
        """Get by ID."""
        return await self._provider.fetch_one(api(self._entity, key=self._key_fn).get(id))

    # ─── Write ─────────────────────────────────────────────────────────────

    async def create(self, entity: T) -> T:
        """Create entity."""
        return await self._provider.execute(api(self._entity, key=self._key_fn).create(entity))

    async def update(self, id: AK, entity: T, *, partial: bool = False) -> T:
        """Update entity."""
        return await self._provider.execute(api(self._entity, key=self._key_fn).update(id, entity, partial=partial))

    async def delete(self, id: AK) -> bool:
        """Delete entity."""
        return await self._provider.delete(api(self._entity, key=self._key_fn).delete(id))


class BoundAPIQuerySet(Generic[AK, T]):
    """APIQuerySet bound to provider — chainable + executable."""

    __slots__ = ("_query", "_provider")

    def __init__(self, query: APIQuerySet[AK, T], provider: APIProvider[AK, T]) -> None:
        self._query = query
        self._provider = provider

    # ─── Chainable ─────────────────────────────────────────────────────────

    def filter(
        self, predicate: Callable[[EntityProxy[T]], Expr]
    ) -> BoundAPIQuerySet[AK, T]:
        return BoundAPIQuerySet(self._query.filter(predicate), self._provider)

    def order_by(
        self, *order_fns: Callable[[EntityProxy[T]], FieldProxy | OrderSpec]
    ) -> BoundAPIQuerySet[AK, T]:
        return BoundAPIQuerySet(self._query.order_by(*order_fns), self._provider)

    def page(self, page: int, per_page: int = 20) -> BoundAPIQuerySet[AK, T]:
        return BoundAPIQuerySet(self._query.page(page, per_page), self._provider)

    def offset(self, offset: int, limit: int = 20) -> BoundAPIQuerySet[AK, T]:
        return BoundAPIQuerySet(self._query.offset(offset, limit), self._provider)

    def search(self, query: str) -> BoundAPIQuerySet[AK, T]:
        return BoundAPIQuerySet(self._query.search(query), self._provider)

    # ─── Terminal ──────────────────────────────────────────────────────────

    async def fetch_one(self) -> T | None:
        return await self._provider.fetch_one(self._query)

    async def fetch_many(self) -> list[T]:
        return await self._provider.fetch_many(self._query)

    @property
    def query(self) -> APIQuerySet[AK, T]:
        return self._query


def api_store(
    entity: type[T],
    provider: APIProvider[AK, T],
    key: Callable[[T], AK],
) -> APIStore[AK, T]:
    """Create API store.

    Usage:
        users = api_store(User, memory_provider, key=lambda u: u.id)
        active = await users.list().filter(lambda u: u.active).fetch_many()
    """
    return APIStore(entity, provider, key)


__all__ = (
    # Relational
    "RelationalStore",
    "BoundRelationalQuerySet",
    "relational_store",
    # KV
    "KVStore",
    "kv_store",
    # API
    "APIStore",
    "BoundAPIQuerySet",
    "api_store",
)

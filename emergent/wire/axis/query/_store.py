"""Store — bundled QuerySet + Provider.

Store = Space × Provider for convenience.
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

from emergent.wire.axis.query._expr import Expr
from emergent.wire.axis.query._proxy import EntityProxy, FieldProxy, OrderSpec
from emergent.wire.axis.query._relational import RelationalQuerySet, relational
from emergent.wire.axis.query._aggregate import AggregateExpr
from emergent.wire.axis.query._kv import kv
from emergent.wire.axis.query._provider import (
    RelationalProvider,
    MutatingRelationalProvider,
    KVProvider,
)


T = TypeVar("T")


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

    def select(self, *fields: str) -> BoundRelationalQuerySet[T]:
        return BoundRelationalQuerySet(self._query.select(*fields), self._provider)

    def distinct(self) -> BoundRelationalQuerySet[T]:
        return BoundRelationalQuerySet(self._query.distinct(), self._provider)

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


class KVStore(Generic[T]):
    """KV QuerySet + Provider bundled.

    Usage:
        cache = kv_store(User, key=lambda u: u.id, provider=redis)

        user = await cache.get("alice")
        await cache.set("alice", user)
        await cache.delete("alice")
    """

    __slots__ = ("_entity", "_key_fn", "_provider")

    def __init__(
        self,
        entity: type[T],
        key_fn: Callable[[T], Any],
        provider: KVProvider[T],
    ) -> None:
        self._entity = entity
        self._key_fn = key_fn
        self._provider = provider

    @property
    def entity(self) -> type[T]:
        return self._entity

    # ─── KV Operations ────────────────────────────────────────────────────

    async def get(self, key: Any) -> T | None:
        """Get by key."""
        q = kv(self._entity, self._key_fn).get(key)
        return await self._provider.get(q)

    async def set(self, key: Any, value: T, ttl: int | None = None) -> None:
        """Set value."""
        q = kv(self._entity, self._key_fn).set(key, value, ttl)
        await self._provider.set(q)

    async def put(self, entity: T, ttl: int | None = None) -> None:
        """Set using entity's key."""
        key = self._key_fn(entity)
        await self.set(key, entity, ttl)

    async def delete(self, key: Any) -> bool:
        """Delete by key."""
        q = kv(self._entity, self._key_fn).delete(key)
        return await self._provider.delete(q)

    async def exists(self, key: Any) -> bool:
        """Check if key exists."""
        q = kv(self._entity, self._key_fn).exists(key)
        return await self._provider.exists(q)

    async def scan(self, pattern: str) -> list[T]:
        """Scan by pattern."""
        q = kv(self._entity, self._key_fn).scan(pattern)
        return await self._provider.scan(q)

    async def keys(self, pattern: str = "*") -> list[str]:
        """Get keys by pattern."""
        q = kv(self._entity, self._key_fn).keys(pattern)
        return await self._provider.keys(q)


def kv_store(
    entity: type[T],
    key: Callable[[T], Any],
    provider: KVProvider[T],
) -> KVStore[T]:
    """Create KV store.

    Usage:
        cache = kv_store(User, key=lambda u: u.id, provider=redis)
        user = await cache.get("alice")
    """
    return KVStore(entity, key, provider)


__all__ = (
    # Relational
    "RelationalStore",
    "BoundRelationalQuerySet",
    "relational_store",
    # KV
    "KVStore",
    "kv_store",
)

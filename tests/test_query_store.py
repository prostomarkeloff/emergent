"""Tests for Store layer — RelationalStore + KVStore + APIStore.

Extends existing tests to cover uncovered lines:
- BoundRelationalQuerySet: where, offset, select, distinct, join, left_join,
  group_by, having methods
- RelationalStore: where, select, distinct methods
- APIStore + BoundAPIQuerySet
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from emergent.wire.axis.query._store import (
    APIStore,
    BoundAPIQuerySet,
    BoundRelationalQuerySet,
    KVStore,
    RelationalStore,
    api_store,
    kv_store,
    relational_store,
)
from emergent.wire.axis.query.providers.memory import (
    MemoryAPIProvider,
    MemoryKVProvider,
    MemoryRelationalProvider,
)


@dataclass
class User:
    id: int
    name: str
    balance: float
    active: bool = True


@dataclass
class Order:
    id: int
    user_id: int
    amount: float


ALICE = User(1, "alice", 100.0)
BOB = User(2, "bob", 50.0, active=False)
CHARLIE = User(3, "charlie", 200.0)


# ===============================================================================
# RelationalStore
# ===============================================================================


class TestRelationalStore:
    @pytest.fixture
    def store(self) -> RelationalStore[User]:
        prov = MemoryRelationalProvider[User](
            data=[ALICE, BOB, CHARLIE],
            key_fn=lambda u: u.id,
        )
        return relational_store(User, prov)

    def test_entity(self, store: RelationalStore[User]) -> None:
        assert store.entity is User

    def test_query_returns_bound(self, store: RelationalStore[User]) -> None:
        q = store.query()
        assert isinstance(q, BoundRelationalQuerySet)

    def test_filter_returns_bound(self, store: RelationalStore[User]) -> None:
        q = store.filter(lambda u: u.balance > 0)
        assert isinstance(q, BoundRelationalQuerySet)

    def test_where_is_alias_for_filter(self, store: RelationalStore[User]) -> None:
        q = store.where(lambda u: u.balance > 0)
        assert isinstance(q, BoundRelationalQuerySet)

    def test_all_returns_bound(self, store: RelationalStore[User]) -> None:
        q = store.all()
        assert isinstance(q, BoundRelationalQuerySet)

    def test_select_returns_bound(self, store: RelationalStore[User]) -> None:
        q = store.select(lambda u: u.name)
        assert isinstance(q, BoundRelationalQuerySet)

    def test_distinct_returns_bound(self, store: RelationalStore[User]) -> None:
        q = store.distinct()
        assert isinstance(q, BoundRelationalQuerySet)

    @pytest.mark.asyncio
    async def test_where_fetch_many(self, store: RelationalStore[User]) -> None:
        result = await store.where(lambda u: u.balance > 75).fetch_many()
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_filter_fetch_many(self, store: RelationalStore[User]) -> None:
        result = await store.filter(lambda u: u.balance > 75).fetch_many()
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_filter_fetch_one(self, store: RelationalStore[User]) -> None:
        result = await store.filter(lambda u: u.name == "alice").fetch_one()
        assert result is not None
        assert result.name == "alice"

    @pytest.mark.asyncio
    async def test_count(self, store: RelationalStore[User]) -> None:
        cnt = await store.filter(lambda u: u.active == True).count()
        assert cnt == 2

    @pytest.mark.asyncio
    async def test_exists(self, store: RelationalStore[User]) -> None:
        assert await store.filter(lambda u: u.name == "alice").exists() is True
        assert await store.filter(lambda u: u.name == "nobody").exists() is False

    @pytest.mark.asyncio
    async def test_first(self, store: RelationalStore[User]) -> None:
        result = await store.order_by(lambda u: u.name).first()
        assert result is not None
        assert result.name == "alice"

    @pytest.mark.asyncio
    async def test_order_by(self, store: RelationalStore[User]) -> None:
        result = await store.order_by(lambda u: u.balance.desc()).fetch_many()
        assert result[0].name == "charlie"

    @pytest.mark.asyncio
    async def test_limit(self, store: RelationalStore[User]) -> None:
        result = await store.limit(2).fetch_many()
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_chaining(self, store: RelationalStore[User]) -> None:
        result = await (
            store
            .filter(lambda u: u.active == True)
            .order_by(lambda u: u.balance.desc())
            .limit(1)
            .fetch_many()
        )
        assert len(result) == 1
        assert result[0].name == "charlie"

    @pytest.mark.asyncio
    async def test_insert(self, store: RelationalStore[User]) -> None:
        new_user = User(4, "dave", 300.0)
        result = await store.insert(new_user)
        assert result is new_user
        all_users = await store.all().fetch_many()
        assert len(all_users) == 4

    @pytest.mark.asyncio
    async def test_update(self, store: RelationalStore[User]) -> None:
        updated = User(1, "alice_updated", 150.0)
        result = await store.update(updated)
        assert result.name == "alice_updated"

    @pytest.mark.asyncio
    async def test_delete(self, store: RelationalStore[User]) -> None:
        await store.delete(ALICE)
        all_users = await store.all().fetch_many()
        assert len(all_users) == 2


class TestBoundRelationalQuerySet:
    @pytest.fixture
    def bound(self) -> BoundRelationalQuerySet[User]:
        prov = MemoryRelationalProvider[User](
            data=[ALICE, BOB, CHARLIE],
            key_fn=lambda u: u.id,
        )
        return relational_store(User, prov).query()

    def test_where_is_alias_for_filter(self, bound: BoundRelationalQuerySet[User]) -> None:
        q = bound.where(lambda u: u.active == True)
        assert isinstance(q, BoundRelationalQuerySet)

    @pytest.mark.asyncio
    async def test_where_fetches_correctly(self, bound: BoundRelationalQuerySet[User]) -> None:
        result = await bound.where(lambda u: u.active == True).fetch_many()
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_offset(self, bound: BoundRelationalQuerySet[User]) -> None:
        result = await bound.order_by(lambda u: u.name).offset(1).fetch_many()
        assert len(result) == 2
        assert result[0].name == "bob"

    @pytest.mark.asyncio
    async def test_paginate(self, bound: BoundRelationalQuerySet[User]) -> None:
        result = await (
            bound
            .order_by(lambda u: u.name)
            .paginate(1, 2)
            .fetch_many()
        )
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_select(self, bound: BoundRelationalQuerySet[User]) -> None:
        q = bound.select(lambda u: u.name)
        assert isinstance(q, BoundRelationalQuerySet)

    @pytest.mark.asyncio
    async def test_distinct(self, bound: BoundRelationalQuerySet[User]) -> None:
        q = bound.distinct()
        assert isinstance(q, BoundRelationalQuerySet)

    def test_join(self, bound: BoundRelationalQuerySet[User]) -> None:
        q = bound.join(
            Order,
            lambda u, o: u.id == o.user_id,
        )
        assert isinstance(q, BoundRelationalQuerySet)

    def test_join_with_tablename(self, bound: BoundRelationalQuerySet[User]) -> None:
        q = bound.join(
            Order,
            lambda u, o: u.id == o.user_id,
            tablename="orders",
        )
        assert isinstance(q, BoundRelationalQuerySet)

    def test_left_join(self, bound: BoundRelationalQuerySet[User]) -> None:
        q = bound.left_join(
            Order,
            lambda u, o: u.id == o.user_id,
        )
        assert isinstance(q, BoundRelationalQuerySet)

    def test_left_join_with_tablename(self, bound: BoundRelationalQuerySet[User]) -> None:
        q = bound.left_join(
            Order,
            lambda u, o: u.id == o.user_id,
            tablename="orders",
        )
        assert isinstance(q, BoundRelationalQuerySet)

    def test_group_by(self, bound: BoundRelationalQuerySet[User]) -> None:
        q = bound.group_by(lambda u: u.active)
        assert isinstance(q, BoundRelationalQuerySet)

    def test_having(self, bound: BoundRelationalQuerySet[User]) -> None:
        q = bound.having(lambda u: u.balance > 100)
        assert isinstance(q, BoundRelationalQuerySet)

    @pytest.mark.asyncio
    async def test_aggregate(self, bound: BoundRelationalQuerySet[User]) -> None:
        result = await (
            bound
            .aggregate(total=lambda u: u.balance.sum())
            .fetch_aggregates()
        )
        assert result["total"] == 350.0

    def test_query_property(self, bound: BoundRelationalQuerySet[User]) -> None:
        q = bound.filter(lambda u: u.balance > 0)
        assert q.query is not None
        assert q.query.entity is User


# ===============================================================================
# KVStore
# ===============================================================================


class TestKVStore:
    @pytest.fixture
    def store(self) -> KVStore[str, User]:
        prov = MemoryKVProvider[str, User]()
        return kv_store(User, key=lambda u: str(u.id), provider=prov)

    def test_entity(self, store: KVStore[str, User]) -> None:
        assert store.entity is User

    @pytest.mark.asyncio
    async def test_set_and_get(self, store: KVStore[str, User]) -> None:
        await store.set("alice", ALICE)
        result = await store.get("alice")
        assert result is not None
        assert result.name == "alice"

    @pytest.mark.asyncio
    async def test_get_missing(self, store: KVStore[str, User]) -> None:
        result = await store.get("nobody")
        assert result is None

    @pytest.mark.asyncio
    async def test_put(self, store: KVStore[str, User]) -> None:
        await store.put(ALICE)
        result = await store.get(str(ALICE.id))
        assert result is not None

    @pytest.mark.asyncio
    async def test_put_with_ttl(self, store: KVStore[str, User]) -> None:
        await store.put(ALICE, ttl=3600)
        result = await store.get(str(ALICE.id))
        assert result is not None

    @pytest.mark.asyncio
    async def test_delete(self, store: KVStore[str, User]) -> None:
        await store.set("alice", ALICE)
        deleted = await store.delete("alice")
        assert deleted is True
        assert await store.get("alice") is None

    @pytest.mark.asyncio
    async def test_delete_missing(self, store: KVStore[str, User]) -> None:
        deleted = await store.delete("nobody")
        assert deleted is False

    @pytest.mark.asyncio
    async def test_exists(self, store: KVStore[str, User]) -> None:
        assert await store.exists("alice") is False
        await store.set("alice", ALICE)
        assert await store.exists("alice") is True

    @pytest.mark.asyncio
    async def test_scan(self, store: KVStore[str, User]) -> None:
        await store.set("user:1", ALICE)
        await store.set("user:2", BOB)
        await store.set("admin:3", CHARLIE)
        result = await store.scan("user:*")
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_keys(self, store: KVStore[str, User]) -> None:
        await store.set("a", ALICE)
        await store.set("b", BOB)
        keys = await store.keys("*")
        assert set(keys) == {"a", "b"}

    @pytest.mark.asyncio
    async def test_keys_default_pattern(self, store: KVStore[str, User]) -> None:
        await store.set("x", ALICE)
        await store.set("y", BOB)
        keys = await store.keys()
        assert len(keys) == 2


# ===============================================================================
# APIStore + BoundAPIQuerySet
# ===============================================================================


class TestAPIStore:
    @pytest.fixture
    def store(self) -> APIStore[int, User]:
        prov = MemoryAPIProvider[int, User](
            data=[ALICE, BOB, CHARLIE],
            key_fn=lambda u: u.id,
        )
        return api_store(User, prov, key=lambda u: u.id)

    def test_entity(self, store: APIStore[int, User]) -> None:
        assert store.entity is User

    def test_list_returns_bound(self, store: APIStore[int, User]) -> None:
        q = store.list()
        assert isinstance(q, BoundAPIQuerySet)

    @pytest.mark.asyncio
    async def test_get(self, store: APIStore[int, User]) -> None:
        result = await store.get(1)
        assert result is not None
        assert result.name == "alice"

    @pytest.mark.asyncio
    async def test_get_missing(self, store: APIStore[int, User]) -> None:
        result = await store.get(999)
        assert result is None

    @pytest.mark.asyncio
    async def test_create(self, store: APIStore[int, User]) -> None:
        new_user = User(4, "dave", 300.0)
        result = await store.create(new_user)
        assert result.name == "dave"

    @pytest.mark.asyncio
    async def test_update(self, store: APIStore[int, User]) -> None:
        updated = User(1, "alice_updated", 150.0)
        result = await store.update(1, updated)
        assert result.name == "alice_updated"

    @pytest.mark.asyncio
    async def test_update_partial(self, store: APIStore[int, User]) -> None:
        partial = User(1, "alice_partial", 100.0)
        result = await store.update(1, partial, partial=True)
        assert result.name == "alice_partial"

    @pytest.mark.asyncio
    async def test_delete(self, store: APIStore[int, User]) -> None:
        result = await store.delete(1)
        assert result is True

    @pytest.mark.asyncio
    async def test_delete_missing(self, store: APIStore[int, User]) -> None:
        result = await store.delete(999)
        assert result is False


class TestBoundAPIQuerySet:
    @pytest.fixture
    def bound(self) -> BoundAPIQuerySet[int, User]:
        prov = MemoryAPIProvider[int, User](
            data=[ALICE, BOB, CHARLIE],
            key_fn=lambda u: u.id,
        )
        return api_store(User, prov, key=lambda u: u.id).list()

    @pytest.mark.asyncio
    async def test_fetch_many(self, bound: BoundAPIQuerySet[int, User]) -> None:
        result = await bound.fetch_many()
        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_filter(self, bound: BoundAPIQuerySet[int, User]) -> None:
        result = await bound.filter(lambda u: u.active == True).fetch_many()
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_order_by(self, bound: BoundAPIQuerySet[int, User]) -> None:
        result = await bound.order_by(lambda u: u.balance.desc()).fetch_many()
        assert result[0].name == "charlie"

    @pytest.mark.asyncio
    async def test_page(self, bound: BoundAPIQuerySet[int, User]) -> None:
        result = await bound.page(1, per_page=2).fetch_many()
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_offset(self, bound: BoundAPIQuerySet[int, User]) -> None:
        result = await bound.offset(1, limit=2).fetch_many()
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_search(self, bound: BoundAPIQuerySet[int, User]) -> None:
        result = await bound.search("alice").fetch_many()
        assert len(result) == 1
        assert result[0].name == "alice"

    @pytest.mark.asyncio
    async def test_fetch_one(self, bound: BoundAPIQuerySet[int, User]) -> None:
        result = await bound.filter(lambda u: u.name == "alice").fetch_one()
        assert result is not None
        assert result.name == "alice"

    def test_query_property(self, bound: BoundAPIQuerySet[int, User]) -> None:
        q = bound.filter(lambda u: u.balance > 0)
        assert q.query is not None


# ===============================================================================
# Integration: Store Full Lifecycle
# ===============================================================================


class TestIntegrationStoreFullLifecycle:
    @pytest.mark.asyncio
    async def test_relational_store_lifecycle(self) -> None:
        prov = MemoryRelationalProvider[User](key_fn=lambda u: u.id)
        store = relational_store(User, prov)

        await store.insert(ALICE)
        await store.insert(BOB)
        await store.insert(CHARLIE)
        all_users = await store.all().fetch_many()
        assert len(all_users) == 3

        active = await store.filter(lambda u: u.active == True).fetch_many()
        assert len(active) == 2

        alice = await store.filter(lambda u: u.name == "alice").fetch_one()
        assert alice is not None
        assert alice.name == "alice"

        updated_alice = User(1, "alice_updated", 150.0)
        result = await store.update(updated_alice)
        assert result.name == "alice_updated"

        fetched = await store.filter(lambda u: u.id == 1).fetch_one()
        assert fetched is not None
        assert fetched.name == "alice_updated"

        await store.delete(BOB)
        remaining = await store.all().fetch_many()
        assert len(remaining) == 2
        names = {u.name for u in remaining}
        assert "bob" not in names

    @pytest.mark.asyncio
    async def test_kv_store_lifecycle(self) -> None:
        prov = MemoryKVProvider[str, User]()
        store = kv_store(User, key=lambda u: str(u.id), provider=prov)

        await store.set("alice", ALICE)
        await store.set("bob", BOB)

        alice = await store.get("alice")
        assert alice is not None
        assert alice.name == "alice"

        await store.put(CHARLIE)
        charlie = await store.get(str(CHARLIE.id))
        assert charlie is not None
        assert charlie.name == "charlie"

        await store.set("user:1", ALICE)
        await store.set("user:2", BOB)
        scanned = await store.scan("user:*")
        assert len(scanned) == 2

        deleted = await store.delete("alice")
        assert deleted is True
        assert await store.get("alice") is None

        assert await store.exists("bob") is True
        assert await store.exists("alice") is False

    @pytest.mark.asyncio
    async def test_api_store_lifecycle(self) -> None:
        prov = MemoryAPIProvider[int, User](key_fn=lambda u: u.id)
        store = api_store(User, prov, key=lambda u: u.id)

        user1 = await store.create(ALICE)
        assert user1.name == "alice"

        user2 = await store.create(BOB)
        assert user2.name == "bob"

        all_users = await store.list().fetch_many()
        assert len(all_users) == 2

        alice = await store.get(1)
        assert alice is not None
        assert alice.name == "alice"

        updated = User(1, "alice_v2", 999.0)
        result = await store.update(1, updated)
        assert result.name == "alice_v2"

        deleted = await store.delete(1)
        assert deleted is True

        remaining = await store.list().fetch_many()
        assert len(remaining) == 1

    @pytest.mark.asyncio
    async def test_relational_query_cached_in_kv(self) -> None:
        rel_prov = MemoryRelationalProvider[User](
            data=[ALICE, BOB, CHARLIE],
            key_fn=lambda u: u.id,
        )
        rel_store = relational_store(User, rel_prov)

        kv_prov = MemoryKVProvider[str, User]()
        cache = kv_store(User, key=lambda u: str(u.id), provider=kv_prov)

        rich = await (
            rel_store
            .filter(lambda u: u.balance >= 100)
            .order_by(lambda u: u.balance.desc())
            .fetch_many()
        )
        assert len(rich) == 2

        for user in rich:
            await cache.set(f"rich:{user.id}", user)

        cached = await cache.scan("rich:*")
        assert len(cached) == 2
        cached_names = {u.name for u in cached}
        assert cached_names == {"alice", "charlie"}

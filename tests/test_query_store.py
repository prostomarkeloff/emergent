"""Tests for Store layer — RelationalStore + KVStore."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from emergent.wire.axis.query._store import (
    BoundRelationalQuerySet,
    KVStore,
    RelationalStore,
    kv_store,
    relational_store,
)
from emergent.wire.axis.query.providers.memory import (
    MemoryKVProvider,
    MemoryRelationalProvider,
)


@dataclass
class User:
    id: int
    name: str
    balance: float
    active: bool = True


ALICE = User(1, "alice", 100.0)
BOB = User(2, "bob", 50.0, active=False)
CHARLIE = User(3, "charlie", 200.0)


# ═══════════════════════════════════════════════════════════════════════════════
# RelationalStore
# ═══════════════════════════════════════════════════════════════════════════════


class TestRelationalStore:
    @pytest.fixture
    def store(self):
        prov = MemoryRelationalProvider[User](
            data=[ALICE, BOB, CHARLIE],
            key_fn=lambda u: u.id,
        )
        return relational_store(User, prov)

    def test_entity(self, store):
        assert store.entity is User

    def test_query_returns_bound(self, store):
        q = store.query()
        assert isinstance(q, BoundRelationalQuerySet)

    def test_filter_returns_bound(self, store):
        q = store.filter(lambda u: u.balance > 0)
        assert isinstance(q, BoundRelationalQuerySet)

    def test_all_returns_bound(self, store):
        q = store.all()
        assert isinstance(q, BoundRelationalQuerySet)

    @pytest.mark.asyncio
    async def test_filter_fetch_many(self, store):
        result = await store.filter(lambda u: u.balance > 75).fetch_many()
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_filter_fetch_one(self, store):
        result = await store.filter(lambda u: u.name == "alice").fetch_one()
        assert result is not None
        assert result.name == "alice"

    @pytest.mark.asyncio
    async def test_count(self, store):
        cnt = await store.filter(lambda u: u.active == True).count()
        assert cnt == 2

    @pytest.mark.asyncio
    async def test_exists(self, store):
        assert await store.filter(lambda u: u.name == "alice").exists() is True
        assert await store.filter(lambda u: u.name == "nobody").exists() is False

    @pytest.mark.asyncio
    async def test_first(self, store):
        result = await store.order_by(lambda u: u.name).first()
        assert result is not None
        assert result.name == "alice"

    @pytest.mark.asyncio
    async def test_order_by(self, store):
        result = await store.order_by(lambda u: u.balance.desc()).fetch_many()
        assert result[0].name == "charlie"

    @pytest.mark.asyncio
    async def test_limit(self, store):
        result = await store.limit(2).fetch_many()
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_chaining(self, store):
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
    async def test_insert(self, store):
        new_user = User(4, "dave", 300.0)
        result = await store.insert(new_user)
        assert result is new_user
        all_users = await store.all().fetch_many()
        assert len(all_users) == 4

    @pytest.mark.asyncio
    async def test_update(self, store):
        updated = User(1, "alice_updated", 150.0)
        result = await store.update(updated)
        assert result.name == "alice_updated"

    @pytest.mark.asyncio
    async def test_delete(self, store):
        await store.delete(ALICE)
        all_users = await store.all().fetch_many()
        assert len(all_users) == 2


class TestBoundRelationalQuerySet:
    @pytest.fixture
    def bound(self):
        prov = MemoryRelationalProvider[User](
            data=[ALICE, BOB, CHARLIE],
            key_fn=lambda u: u.id,
        )
        return relational_store(User, prov).query()

    @pytest.mark.asyncio
    async def test_aggregate(self, bound):
        result = await (
            bound
            .aggregate(total=lambda u: u.balance.sum())
            .fetch_aggregates()
        )
        assert result["total"] == 350.0

    @pytest.mark.asyncio
    async def test_paginate(self, bound):
        result = await (
            bound
            .order_by(lambda u: u.name)
            .paginate(1, 2)
            .fetch_many()
        )
        assert len(result) == 2

    def test_query_property(self, bound):
        q = bound.filter(lambda u: u.balance > 0)
        assert q.query is not None
        assert q.query.entity is User


# ═══════════════════════════════════════════════════════════════════════════════
# KVStore
# ═══════════════════════════════════════════════════════════════════════════════


class TestKVStore:
    @pytest.fixture
    def store(self):
        prov = MemoryKVProvider[str, User]()
        return kv_store(User, key=lambda u: u.id, provider=prov)

    def test_entity(self, store):
        assert store.entity is User

    @pytest.mark.asyncio
    async def test_set_and_get(self, store):
        await store.set("alice", ALICE)
        result = await store.get("alice")
        assert result is not None
        assert result.name == "alice"

    @pytest.mark.asyncio
    async def test_get_missing(self, store):
        result = await store.get("nobody")
        assert result is None

    @pytest.mark.asyncio
    async def test_put(self, store):
        await store.put(ALICE)
        # Key extracted via key_fn = lambda u: u.id → 1
        result = await store.get(1)
        assert result is not None

    @pytest.mark.asyncio
    async def test_delete(self, store):
        await store.set("alice", ALICE)
        deleted = await store.delete("alice")
        assert deleted is True
        assert await store.get("alice") is None

    @pytest.mark.asyncio
    async def test_delete_missing(self, store):
        deleted = await store.delete("nobody")
        assert deleted is False

    @pytest.mark.asyncio
    async def test_exists(self, store):
        assert await store.exists("alice") is False
        await store.set("alice", ALICE)
        assert await store.exists("alice") is True

    @pytest.mark.asyncio
    async def test_scan(self, store):
        await store.set("user:1", ALICE)
        await store.set("user:2", BOB)
        await store.set("admin:3", CHARLIE)
        result = await store.scan("user:*")
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_keys(self, store):
        await store.set("a", ALICE)
        await store.set("b", BOB)
        keys = await store.keys("*")
        assert set(keys) == {"a", "b"}


# ─── Integration: Store Full Lifecycle ───────────────────────────────────────


class TestIntegrationStoreFullLifecycle:
    @pytest.mark.asyncio
    async def test_relational_store_lifecycle(self):
        prov = MemoryRelationalProvider[User](key_fn=lambda u: u.id)
        store = relational_store(User, prov)

        # Insert
        await store.insert(ALICE)
        await store.insert(BOB)
        await store.insert(CHARLIE)
        all_users = await store.all().fetch_many()
        assert len(all_users) == 3

        # Filter
        active = await store.filter(lambda u: u.active == True).fetch_many()
        assert len(active) == 2

        # Fetch one
        alice = await store.filter(lambda u: u.name == "alice").fetch_one()
        assert alice is not None
        assert alice.name == "alice"

        # Update
        updated_alice = User(1, "alice_updated", 150.0)
        result = await store.update(updated_alice)
        assert result.name == "alice_updated"

        fetched = await store.filter(lambda u: u.id == 1).fetch_one()
        assert fetched is not None
        assert fetched.name == "alice_updated"

        # Delete
        await store.delete(BOB)
        remaining = await store.all().fetch_many()
        assert len(remaining) == 2
        names = {u.name for u in remaining}
        assert "bob" not in names

    @pytest.mark.asyncio
    async def test_kv_store_lifecycle(self):
        prov = MemoryKVProvider[str, User]()
        store = kv_store(User, key=lambda u: u.id, provider=prov)

        # Set
        await store.set("alice", ALICE)
        await store.set("bob", BOB)

        # Get
        alice = await store.get("alice")
        assert alice is not None
        assert alice.name == "alice"

        # Put (uses key_fn)
        await store.put(CHARLIE)
        charlie = await store.get(CHARLIE.id)
        assert charlie is not None
        assert charlie.name == "charlie"

        # Scan
        await store.set("user:1", ALICE)
        await store.set("user:2", BOB)
        scanned = await store.scan("user:*")
        assert len(scanned) == 2

        # Delete
        deleted = await store.delete("alice")
        assert deleted is True
        assert await store.get("alice") is None

        # Exists
        assert await store.exists("bob") is True
        assert await store.exists("alice") is False

    @pytest.mark.asyncio
    async def test_relational_query_cached_in_kv(self):
        # Setup relational store
        rel_prov = MemoryRelationalProvider[User](
            data=[ALICE, BOB, CHARLIE],
            key_fn=lambda u: u.id,
        )
        rel_store = relational_store(User, rel_prov)

        # Setup KV store
        kv_prov = MemoryKVProvider[str, User]()
        cache = kv_store(User, key=lambda u: u.id, provider=kv_prov)

        # Query relational store for high-balance users
        rich = await (
            rel_store
            .filter(lambda u: u.balance >= 100)
            .order_by(lambda u: u.balance.desc())
            .fetch_many()
        )
        assert len(rich) == 2  # CHARLIE(200) and ALICE(100)

        # Cache in KV
        for user in rich:
            await cache.set(f"rich:{user.id}", user)

        # Verify cache
        cached = await cache.scan("rich:*")
        assert len(cached) == 2
        cached_names = {u.name for u in cached}
        assert cached_names == {"alice", "charlie"}

"""Tests for memory providers -- MemoryRelationalProvider + MemoryKVProvider."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from emergent.wire.axis.query._kv import KVQuerySet, kv
from emergent.wire.axis.query._provider import SequenceNextId, PrefixedNextId, UuidNextId
from emergent.wire.axis.query._relational import relational
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


ALICE = User(id=1, name="alice", balance=100.0)
BOB = User(id=2, name="bob", balance=50.0, active=False)
CHARLIE = User(id=3, name="charlie", balance=200.0)


# ═══════════════════════════════════════════════════════════════════════════════
# MemoryRelationalProvider
# ═══════════════════════════════════════════════════════════════════════════════


class TestMemoryRelationalFetch:
    @pytest.fixture
    def prov(self) -> MemoryRelationalProvider[User]:
        return MemoryRelationalProvider[User](
            data=[ALICE, BOB, CHARLIE],
            key_fn=lambda u: u.id,
        )

    @pytest.mark.asyncio
    async def test_fetch_many_all(self, prov: MemoryRelationalProvider[User]) -> None:
        result = await prov.fetch_many(relational(User))
        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_fetch_many_filter(self, prov: MemoryRelationalProvider[User]) -> None:
        q = relational(User).filter(lambda u: u.balance > 75)
        result = await prov.fetch_many(q)
        assert len(result) == 2
        names = {u.name for u in result}
        assert names == {"alice", "charlie"}

    @pytest.mark.asyncio
    async def test_fetch_one(self, prov: MemoryRelationalProvider[User]) -> None:
        q = relational(User).filter(lambda u: u.name == "alice")
        result = await prov.fetch_one(q)
        assert result is not None
        assert result.name == "alice"

    @pytest.mark.asyncio
    async def test_fetch_one_none(self, prov: MemoryRelationalProvider[User]) -> None:
        q = relational(User).filter(lambda u: u.name == "nobody")
        result = await prov.fetch_one(q)
        assert result is None

    @pytest.mark.asyncio
    async def test_count(self, prov: MemoryRelationalProvider[User]) -> None:
        assert await prov.count(relational(User)) == 3
        q = relational(User).filter(lambda u: u.active == True)
        assert await prov.count(q) == 2

    @pytest.mark.asyncio
    async def test_exists(self, prov: MemoryRelationalProvider[User]) -> None:
        assert await prov.exists(relational(User)) is True
        q = relational(User).filter(lambda u: u.name == "nobody")
        assert await prov.exists(q) is False

    @pytest.mark.asyncio
    async def test_order_by(self, prov: MemoryRelationalProvider[User]) -> None:
        q = relational(User).order_by(lambda u: u.balance.desc())
        result = await prov.fetch_many(q)
        assert [u.name for u in result] == ["charlie", "alice", "bob"]

    @pytest.mark.asyncio
    async def test_limit(self, prov: MemoryRelationalProvider[User]) -> None:
        q = relational(User).order_by(lambda u: u.name).limit(2)
        result = await prov.fetch_many(q)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_offset(self, prov: MemoryRelationalProvider[User]) -> None:
        q = relational(User).order_by(lambda u: u.name).offset(1)
        result = await prov.fetch_many(q)
        assert len(result) == 2  # skip first

    @pytest.mark.asyncio
    async def test_filter_order_limit(self, prov: MemoryRelationalProvider[User]) -> None:
        q = (
            relational(User)
            .filter(lambda u: u.active == True)
            .order_by(lambda u: u.balance.desc())
            .limit(1)
        )
        result = await prov.fetch_many(q)
        assert len(result) == 1
        assert result[0].name == "charlie"


class TestMemoryRelationalMutations:
    @pytest.fixture
    def prov(self) -> MemoryRelationalProvider[User]:
        return MemoryRelationalProvider[User](key_fn=lambda u: u.id)

    @pytest.mark.asyncio
    async def test_insert(self, prov: MemoryRelationalProvider[User]) -> None:
        result = await prov.insert(ALICE)
        assert result is ALICE
        assert len(prov.data) == 1

    @pytest.mark.asyncio
    async def test_update(self, prov: MemoryRelationalProvider[User]) -> None:
        await prov.insert(ALICE)
        updated = User(id=1, name="alice_updated", balance=150.0)
        result = await prov.update(updated)
        assert result.name == "alice_updated"
        assert len(prov.data) == 1

    @pytest.mark.asyncio
    async def test_update_not_found(self, prov: MemoryRelationalProvider[User]) -> None:
        with pytest.raises(ValueError, match="not found"):
            await prov.update(ALICE)

    @pytest.mark.asyncio
    async def test_delete(self, prov: MemoryRelationalProvider[User]) -> None:
        await prov.insert(ALICE)
        await prov.insert(BOB)
        await prov.delete(ALICE)
        assert len(prov.data) == 1
        assert prov.data[0].name == "bob"

    @pytest.mark.asyncio
    async def test_delete_where(self, prov: MemoryRelationalProvider[User]) -> None:
        await prov.insert(ALICE)
        await prov.insert(BOB)
        await prov.insert(CHARLIE)
        q = relational(User).filter(lambda u: u.balance < 100)
        deleted = await prov.delete_where(q)
        assert deleted == 1
        assert len(prov.data) == 2

    @pytest.mark.asyncio
    async def test_insert_many(self, prov: MemoryRelationalProvider[User]) -> None:
        result = await prov.insert_many([ALICE, BOB, CHARLIE])
        assert len(result) == 3
        assert len(prov.data) == 3

    @pytest.mark.asyncio
    async def test_insert_many_empty(self, prov: MemoryRelationalProvider[User]) -> None:
        result = await prov.insert_many([])
        assert result == []
        assert len(prov.data) == 0

    @pytest.mark.asyncio
    async def test_insert_many_returns_entities(self, prov: MemoryRelationalProvider[User]) -> None:
        result = await prov.insert_many([ALICE, BOB])
        assert result[0] is ALICE
        assert result[1] is BOB

    @pytest.mark.asyncio
    async def test_upsert_insert(self, prov: MemoryRelationalProvider[User]) -> None:
        result = await prov.upsert(ALICE)
        assert result is ALICE
        assert len(prov.data) == 1

    @pytest.mark.asyncio
    async def test_upsert_update(self, prov: MemoryRelationalProvider[User]) -> None:
        await prov.insert(ALICE)
        updated = User(id=1, name="alice_updated", balance=999.0)
        result = await prov.upsert(updated)
        assert result.name == "alice_updated"
        assert len(prov.data) == 1

    @pytest.mark.asyncio
    async def test_upsert_requires_key_fn(self) -> None:
        prov = MemoryRelationalProvider[User]()
        with pytest.raises(TypeError, match="upsert.*requires key_fn"):
            await prov.upsert(ALICE)


class TestMemoryRelationalAggregate:
    @pytest.fixture
    def prov(self) -> MemoryRelationalProvider[User]:
        return MemoryRelationalProvider[User](data=[ALICE, BOB, CHARLIE])

    @pytest.mark.asyncio
    async def test_count_star(self, prov: MemoryRelationalProvider[User]) -> None:
        q = relational(User).aggregate(cnt=lambda u: u.count())
        result = await prov.aggregate(q)
        assert result["cnt"] == 3

    @pytest.mark.asyncio
    async def test_count_field(self, prov: MemoryRelationalProvider[User]) -> None:
        q = relational(User).aggregate(cnt=lambda u: u.id.count())
        result = await prov.aggregate(q)
        assert result["cnt"] == 3

    @pytest.mark.asyncio
    async def test_sum(self, prov: MemoryRelationalProvider[User]) -> None:
        q = relational(User).aggregate(total=lambda u: u.balance.sum())
        result = await prov.aggregate(q)
        assert result["total"] == 350.0

    @pytest.mark.asyncio
    async def test_avg(self, prov: MemoryRelationalProvider[User]) -> None:
        q = relational(User).aggregate(avg_bal=lambda u: u.balance.avg())
        result = await prov.aggregate(q)
        assert abs(result["avg_bal"] - 350.0 / 3) < 0.01

    @pytest.mark.asyncio
    async def test_min_max(self, prov: MemoryRelationalProvider[User]) -> None:
        q = relational(User).aggregate(
            lo=lambda u: u.balance.min(),
            hi=lambda u: u.balance.max(),
        )
        result = await prov.aggregate(q)
        assert result["lo"] == 50.0
        assert result["hi"] == 200.0

    @pytest.mark.asyncio
    async def test_array_agg(self, prov: MemoryRelationalProvider[User]) -> None:
        q = relational(User).aggregate(names=lambda u: u.name.array_agg())
        result = await prov.aggregate(q)
        assert set(result["names"]) == {"alice", "bob", "charlie"}

    @pytest.mark.asyncio
    async def test_string_agg(self, prov: MemoryRelationalProvider[User]) -> None:
        q = relational(User).aggregate(names=lambda u: u.name.string_agg(","))
        result = await prov.aggregate(q)
        parts = set(result["names"].split(","))
        assert parts == {"alice", "bob", "charlie"}

    @pytest.mark.asyncio
    async def test_aggregate_with_filter(self, prov: MemoryRelationalProvider[User]) -> None:
        q = (
            relational(User)
            .filter(lambda u: u.active == True)
            .aggregate(cnt=lambda u: u.count())
        )
        result = await prov.aggregate(q)
        assert result["cnt"] == 2

    @pytest.mark.asyncio
    async def test_multiple_aggregates(self, prov: MemoryRelationalProvider[User]) -> None:
        q = relational(User).aggregate(
            cnt=lambda u: u.count(),
            total=lambda u: u.balance.sum(),
            avg_bal=lambda u: u.balance.avg(),
        )
        result = await prov.aggregate(q)
        assert result["cnt"] == 3
        assert result["total"] == 350.0


class TestAggregateEmptyDataset:
    @pytest.mark.asyncio
    async def test_count_empty(self) -> None:
        prov = MemoryRelationalProvider[User]()
        q = relational(User).aggregate(cnt=lambda u: u.count())
        result = await prov.aggregate(q)
        assert result["cnt"] == 0

    @pytest.mark.asyncio
    async def test_sum_empty(self) -> None:
        prov = MemoryRelationalProvider[User]()
        q = relational(User).aggregate(total=lambda u: u.balance.sum())
        result = await prov.aggregate(q)
        assert result["total"] is None

    @pytest.mark.asyncio
    async def test_avg_empty(self) -> None:
        prov = MemoryRelationalProvider[User]()
        q = relational(User).aggregate(avg=lambda u: u.balance.avg())
        result = await prov.aggregate(q)
        assert result["avg"] is None

    @pytest.mark.asyncio
    async def test_min_max_empty(self) -> None:
        prov = MemoryRelationalProvider[User]()
        q = relational(User).aggregate(
            lo=lambda u: u.balance.min(),
            hi=lambda u: u.balance.max(),
        )
        result = await prov.aggregate(q)
        assert result["lo"] is None
        assert result["hi"] is None


class TestMemoryRelationalNextId:
    @pytest.mark.asyncio
    async def test_sequence_next_id(self) -> None:
        prov = MemoryRelationalProvider[User](next_id=SequenceNextId())
        assert await prov.next_id() == 1
        assert await prov.next_id() == 2
        assert await prov.next_id() == 3

    @pytest.mark.asyncio
    async def test_prefixed_next_id(self) -> None:
        prov = MemoryRelationalProvider[User](
            next_id=PrefixedNextId("user_", SequenceNextId())
        )
        assert await prov.next_id() == "user_1"
        assert await prov.next_id() == "user_2"

    @pytest.mark.asyncio
    async def test_uuid_next_id(self) -> None:
        import uuid

        prov = MemoryRelationalProvider[User](next_id=UuidNextId())
        id1 = await prov.next_id()
        id2 = await prov.next_id()
        assert isinstance(id1, str)
        assert isinstance(id2, str)
        # Valid UUID format
        uuid.UUID(id1)
        uuid.UUID(id2)
        # Unique
        assert id1 != id2

    @pytest.mark.asyncio
    async def test_no_next_id_raises(self) -> None:
        prov = MemoryRelationalProvider[User]()
        with pytest.raises(RuntimeError, match="No next_id"):
            await prov.next_id()


class TestMemoryRelationalAtomic:
    @pytest.mark.asyncio
    async def test_atomic_context(self) -> None:
        prov = MemoryRelationalProvider[User](key_fn=lambda u: u.id)
        async with prov.atomic():
            await prov.insert(ALICE)
            await prov.insert(BOB)
        assert len(prov.data) == 2

    @pytest.mark.asyncio
    async def test_atomic_serializes_concurrent(self) -> None:
        import asyncio

        prov = MemoryRelationalProvider[User](key_fn=lambda u: u.id)
        counter = 0

        async def writer(user: User) -> None:
            nonlocal counter
            async with prov.atomic():
                await prov.insert(user)
                await asyncio.sleep(0.01)
                counter += 1

        await asyncio.gather(writer(ALICE), writer(BOB))
        assert len(prov.data) == 2
        assert counter == 2


# ═══════════════════════════════════════════════════════════════════════════════
# MemoryKVProvider
# ═══════════════════════════════════════════════════════════════════════════════


class TestKVQuerySetImmutability:
    def test_kv_queryset_immutable(self) -> None:
        q1 = kv(User, key=lambda u: u.name)
        q2 = q1.get("alice")
        assert q1.op is None  # unchanged
        assert q2.op is not None

    def test_kv_queryset_returns_new(self) -> None:
        q1 = kv(User, key=lambda u: u.name)
        q2 = q1.set("alice", User(id=0, name="Alice", balance=0, active=True))
        q3 = q1.delete("bob")
        assert q1 is not q2
        assert q1 is not q3
        assert q2 is not q3


class TestMemoryKV:
    @pytest.fixture
    def users_kv(self) -> KVQuerySet[str, User]:
        return kv(User, key=lambda u: u.name)

    @pytest.fixture
    def prov(self) -> MemoryKVProvider[str, User]:
        return MemoryKVProvider[str, User]()

    @pytest.mark.asyncio
    async def test_set_and_get(self, prov: MemoryKVProvider[str, User], users_kv: KVQuerySet[str, User]) -> None:
        await prov.set(users_kv.set("alice", ALICE))
        result = (await prov.get(users_kv.get("alice"))).unwrap()
        assert result is not None
        assert result.name == "alice"

    @pytest.mark.asyncio
    async def test_get_missing(self, prov: MemoryKVProvider[str, User], users_kv: KVQuerySet[str, User]) -> None:
        result = (await prov.get(users_kv.get("nobody"))).unwrap()
        assert result is None

    @pytest.mark.asyncio
    async def test_delete(self, prov: MemoryKVProvider[str, User], users_kv: KVQuerySet[str, User]) -> None:
        await prov.set(users_kv.set("alice", ALICE))
        deleted = (await prov.delete(users_kv.delete("alice"))).unwrap()
        assert deleted is True
        assert (await prov.get(users_kv.get("alice"))).unwrap() is None

    @pytest.mark.asyncio
    async def test_delete_missing(self, prov: MemoryKVProvider[str, User], users_kv: KVQuerySet[str, User]) -> None:
        deleted = (await prov.delete(users_kv.delete("nobody"))).unwrap()
        assert deleted is False

    @pytest.mark.asyncio
    async def test_exists(self, prov: MemoryKVProvider[str, User], users_kv: KVQuerySet[str, User]) -> None:
        assert (await prov.exists(users_kv.exists("alice"))).unwrap() is False
        await prov.set(users_kv.set("alice", ALICE))
        assert (await prov.exists(users_kv.exists("alice"))).unwrap() is True

    @pytest.mark.asyncio
    async def test_scan(self, prov: MemoryKVProvider[str, User], users_kv: KVQuerySet[str, User]) -> None:
        await prov.set(users_kv.set("user:alice", ALICE))
        await prov.set(users_kv.set("user:bob", BOB))
        await prov.set(users_kv.set("admin:charlie", CHARLIE))
        result = (await prov.scan(users_kv.scan("user:*"))).unwrap()
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_keys(self, prov: MemoryKVProvider[str, User], users_kv: KVQuerySet[str, User]) -> None:
        await prov.set(users_kv.set("a", ALICE))
        await prov.set(users_kv.set("b", BOB))
        keys = (await prov.keys(users_kv.keys("*"))).unwrap()
        assert set(keys) == {"a", "b"}

    @pytest.mark.asyncio
    async def test_put(self, prov: MemoryKVProvider[str, User], users_kv: KVQuerySet[str, User]) -> None:
        await prov.set(users_kv.put(ALICE))
        result = (await prov.get(users_kv.get(ALICE.name))).unwrap()
        assert result is not None
        assert result.name == "alice"

    @pytest.mark.asyncio
    async def test_put_extracts_key(self, prov: MemoryKVProvider[str, User], users_kv: KVQuerySet[str, User]) -> None:
        await prov.set(users_kv.put(BOB))
        assert (await prov.get(users_kv.get(BOB.name))).unwrap() is not None
        assert (await prov.get(users_kv.get(ALICE.name))).unwrap() is None

    @pytest.mark.asyncio
    async def test_set_with_ttl_accepted(self, prov: MemoryKVProvider[str, User], users_kv: KVQuerySet[str, User]) -> None:
        """TTL is accepted but silently ignored by memory provider."""
        await prov.set(users_kv.set("alice", ALICE, ttl=60))
        result = (await prov.get(users_kv.get("alice"))).unwrap()
        assert result is not None
        assert result.name == "alice"


class TestMemoryKVIntKeys:
    """Verify int keys are preserved, not converted to str."""

    @pytest.fixture
    def users_kv(self) -> KVQuerySet[int | str, User]:
        # Key type is int | str because these tests intentionally mix int and str
        # keys to verify the provider distinguishes them (no coercion).
        return kv(User, key=lambda u: u.id)

    @pytest.fixture
    def prov(self) -> MemoryKVProvider[int | str, User]:
        return MemoryKVProvider[int | str, User]()

    @pytest.mark.asyncio
    async def test_int_key_preserved(self, prov: MemoryKVProvider[int | str, User], users_kv: KVQuerySet[int | str, User]) -> None:
        await prov.set(users_kv.set(42, ALICE))
        assert (await prov.get(users_kv.get(42))).unwrap() is not None
        assert (await prov.get(users_kv.get("42"))).unwrap() is None  # str != int

    @pytest.mark.asyncio
    async def test_int_key_exists(self, prov: MemoryKVProvider[int | str, User], users_kv: KVQuerySet[int | str, User]) -> None:
        await prov.set(users_kv.set(1, ALICE))
        assert (await prov.exists(users_kv.exists(1))).unwrap() is True
        assert (await prov.exists(users_kv.exists("1"))).unwrap() is False

    @pytest.mark.asyncio
    async def test_int_key_delete(self, prov: MemoryKVProvider[int | str, User], users_kv: KVQuerySet[int | str, User]) -> None:
        await prov.set(users_kv.set(1, ALICE))
        assert (await prov.delete(users_kv.delete("1"))).unwrap() is False  # wrong type
        assert (await prov.delete(users_kv.delete(1))).unwrap() is True


# --- Integration: Relational Complex Pipeline --------------------------------


class TestIntegrationRelationalComplexPipeline:
    @pytest.fixture
    def prov(self) -> MemoryRelationalProvider[User]:
        users = [
            User(id=i, name=f"user_{i}", balance=float(i * 25), active=(i % 2 == 0))
            for i in range(1, 11)
        ]
        return MemoryRelationalProvider[User](data=users, key_fn=lambda u: u.id)

    @pytest.mark.asyncio
    async def test_filter_order_limit_top3(self, prov: MemoryRelationalProvider[User]) -> None:
        q = (
            relational(User)
            .filter(lambda u: u.active == True)
            .order_by(lambda u: u.balance.desc())
            .limit(3)
        )
        result = await prov.fetch_many(q)
        assert len(result) == 3
        # Active users: ids 2,4,6,8,10 with balances 50,100,150,200,250
        assert result[0].balance == 250.0
        assert result[1].balance == 200.0
        assert result[2].balance == 150.0

    @pytest.mark.asyncio
    async def test_aggregate_active_count_and_sum(self, prov: MemoryRelationalProvider[User]) -> None:
        q = (
            relational(User)
            .filter(lambda u: u.active == True)
            .aggregate(
                cnt=lambda u: u.count(),
                total=lambda u: u.balance.sum(),
                avg_bal=lambda u: u.balance.avg(),
            )
        )
        result = await prov.aggregate(q)
        assert result["cnt"] == 5
        assert result["total"] == 50.0 + 100.0 + 150.0 + 200.0 + 250.0
        assert abs(result["avg_bal"] - 150.0) < 0.01

    @pytest.mark.asyncio
    async def test_delete_where_low_balance(self, prov: MemoryRelationalProvider[User]) -> None:
        q = relational(User).filter(lambda u: u.balance < 50)
        deleted = await prov.delete_where(q)
        assert deleted == 1  # only user_1 (balance=25) is below 50
        remaining = await prov.fetch_many(relational(User))
        assert len(remaining) == 9

    @pytest.mark.asyncio
    async def test_upsert_existing_and_new(self, prov: MemoryRelationalProvider[User]) -> None:
        # Upsert existing user (id=1)
        updated = User(id=1, name="user_1_updated", balance=999.0, active=True)
        result = await prov.upsert(updated)
        assert result.name == "user_1_updated"
        assert len(prov.data) == 10  # count unchanged

        # Upsert new user (id=99)
        new_user = User(id=99, name="newcomer", balance=500.0, active=True)
        result = await prov.upsert(new_user)
        assert result.name == "newcomer"
        assert len(prov.data) == 11


class TestIntegrationKVWithRelational:
    @pytest.mark.asyncio
    async def test_relational_to_kv_roundtrip(self) -> None:
        # Setup relational provider
        rel_prov = MemoryRelationalProvider[User](
            data=[ALICE, BOB, CHARLIE],
            key_fn=lambda u: u.id,
        )

        # Query relational for active users
        active = await rel_prov.fetch_many(
            relational(User).filter(lambda u: u.active == True)
        )
        assert len(active) == 2  # ALICE and CHARLIE

        # Store in KV by id
        kv_prov = MemoryKVProvider[int, User]()
        users_kv = kv(User, key=lambda u: u.id)
        for user in active:
            await kv_prov.set(users_kv.set(user.id, user))

        # Retrieve from KV and verify
        for user in active:
            retrieved = (await kv_prov.get(users_kv.get(user.id))).unwrap()
            assert retrieved is not None
            assert retrieved.name == user.name
            assert retrieved.balance == user.balance

        # Verify BOB not in KV (inactive)
        assert (await kv_prov.get(users_kv.get(BOB.id))).unwrap() is None

"""Tests for memory providers — covers uncovered lines.

Focuses on:
- MemoryRelationalProvider: update without key_fn, delete without key_fn,
  add/clear/data methods
- MemoryKVProvider: wrong op type errors, clear method, data property
- MemoryAPIProvider: search modifier, select modifier, order modifier,
  cursor pagination, offset pagination, page pagination, partial update,
  fetch_page, next_id errors, include mod error, delete errors
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from emergent.wire.axis.query._api import api
from emergent.wire.axis.query._kv import KVQuerySet, kv
from emergent.wire.axis.query._provider import SequenceNextId
from emergent.wire.axis.query._relational import relational
from emergent.wire.axis.query.providers.memory import (
    MemoryAPIListResult,
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


ALICE = User(id=1, name="alice", balance=100.0)
BOB = User(id=2, name="bob", balance=50.0, active=False)
CHARLIE = User(id=3, name="charlie", balance=200.0)


# ===============================================================================
# MemoryRelationalProvider — uncovered lines
# ===============================================================================


class TestMemoryRelationalProviderDataManagement:
    def test_add(self) -> None:
        prov = MemoryRelationalProvider[User]()
        prov.add(ALICE)
        assert len(prov.data) == 1
        assert prov.data[0] is ALICE

    def test_clear(self) -> None:
        prov = MemoryRelationalProvider[User](data=[ALICE, BOB])
        assert len(prov.data) == 2
        prov.clear()
        assert len(prov.data) == 0

    def test_data_property(self) -> None:
        prov = MemoryRelationalProvider[User](data=[ALICE])
        assert prov.data == [ALICE]


class TestMemoryRelationalProviderMutationEdges:
    @pytest.mark.asyncio
    async def test_update_without_key_fn_raises(self) -> None:
        prov = MemoryRelationalProvider[User]()
        await prov.insert(ALICE)
        with pytest.raises(TypeError, match="update.*requires key_fn"):
            await prov.update(ALICE)

    @pytest.mark.asyncio
    async def test_delete_without_key_fn_removes_by_identity(self) -> None:
        prov = MemoryRelationalProvider[User]()
        await prov.insert(ALICE)
        await prov.insert(BOB)
        await prov.delete(ALICE)
        assert len(prov.data) == 1
        assert prov.data[0] is BOB

    @pytest.mark.asyncio
    async def test_delete_with_key_fn(self) -> None:
        prov = MemoryRelationalProvider[User](key_fn=lambda u: u.id)
        await prov.insert(ALICE)
        await prov.insert(BOB)
        await prov.delete(ALICE)
        assert len(prov.data) == 1
        assert prov.data[0].name == "bob"


class TestMemoryRelationalProviderAggregateEdges:
    @pytest.mark.asyncio
    async def test_sum_with_no_field(self) -> None:
        prov = MemoryRelationalProvider[User](data=[ALICE])
        q = relational(User).aggregate(total=lambda u: u.balance.sum())
        result = await prov.aggregate(q)
        assert result["total"] == 100.0

    @pytest.mark.asyncio
    async def test_avg_with_no_field(self) -> None:
        prov = MemoryRelationalProvider[User](data=[ALICE, CHARLIE])
        q = relational(User).aggregate(avg_bal=lambda u: u.balance.avg())
        result = await prov.aggregate(q)
        assert abs(result["avg_bal"] - 150.0) < 0.01

    @pytest.mark.asyncio
    async def test_min_max_with_data(self) -> None:
        prov = MemoryRelationalProvider[User](data=[ALICE, BOB, CHARLIE])
        q = relational(User).aggregate(
            lo=lambda u: u.balance.min(),
            hi=lambda u: u.balance.max(),
        )
        result = await prov.aggregate(q)
        assert result["lo"] == 50.0
        assert result["hi"] == 200.0

    @pytest.mark.asyncio
    async def test_array_agg_no_field(self) -> None:
        prov = MemoryRelationalProvider[User](data=[ALICE, BOB])
        q = relational(User).aggregate(names=lambda u: u.name.array_agg())
        result = await prov.aggregate(q)
        assert set(result["names"]) == {"alice", "bob"}

    @pytest.mark.asyncio
    async def test_string_agg_with_separator(self) -> None:
        prov = MemoryRelationalProvider[User](data=[ALICE, BOB])
        q = relational(User).aggregate(names=lambda u: u.name.string_agg(" | "))
        result = await prov.aggregate(q)
        assert "alice" in result["names"]
        assert "bob" in result["names"]
        assert " | " in result["names"]


# ===============================================================================
# MemoryKVProvider — uncovered lines
# ===============================================================================


class TestMemoryKVProviderEdges:
    @pytest.fixture
    def users_kv(self) -> KVQuerySet[int, User]:
        return kv(User, key=lambda u: u.id)

    @pytest.fixture
    def prov(self) -> MemoryKVProvider[int, User]:
        return MemoryKVProvider[int, User]()

    def test_data_property(self, prov: MemoryKVProvider[int, User]) -> None:
        assert prov.data == {}

    def test_clear(self) -> None:
        prov = MemoryKVProvider[int, User](data={1: ALICE})
        assert len(prov.data) == 1
        prov.clear()
        assert len(prov.data) == 0

    @pytest.mark.asyncio
    async def test_wrong_op_for_set_raises(self, prov: MemoryKVProvider[int, User], users_kv: KVQuerySet[int, User]) -> None:
        with pytest.raises(TypeError, match="Expected KVSet"):
            await prov.set(users_kv.get(1))

    @pytest.mark.asyncio
    async def test_wrong_op_for_delete_raises(self, prov: MemoryKVProvider[int, User], users_kv: KVQuerySet[int, User]) -> None:
        with pytest.raises(TypeError, match="Expected KVDelete"):
            await prov.delete(users_kv.get(1))

    @pytest.mark.asyncio
    async def test_wrong_op_for_exists_raises(self, prov: MemoryKVProvider[int, User], users_kv: KVQuerySet[int, User]) -> None:
        with pytest.raises(TypeError, match="Expected Exists"):
            await prov.exists(users_kv.get(1))

    @pytest.mark.asyncio
    async def test_wrong_op_for_scan_raises(self, prov: MemoryKVProvider[int, User], users_kv: KVQuerySet[int, User]) -> None:
        with pytest.raises(TypeError, match="Expected Scan"):
            await prov.scan(users_kv.get(1))

    @pytest.mark.asyncio
    async def test_wrong_op_for_keys_raises(self, prov: MemoryKVProvider[int, User], users_kv: KVQuerySet[int, User]) -> None:
        with pytest.raises(TypeError, match="Expected Keys"):
            await prov.keys(users_kv.get(1))

    @pytest.mark.asyncio
    async def test_init_with_data(self) -> None:
        prov = MemoryKVProvider[int, User](data={1: ALICE, 2: BOB})
        users = kv(User, key=lambda u: u.id)
        result = await prov.get(users.get(1))
        assert result is not None
        assert result.name == "alice"


# ===============================================================================
# MemoryAPIProvider — uncovered lines
# ===============================================================================


class TestMemoryAPIProviderFetchOne:
    @pytest.fixture
    def prov(self) -> MemoryAPIProvider[int, User]:
        return MemoryAPIProvider[int, User](
            data=[ALICE, BOB, CHARLIE],
            key_fn=lambda u: u.id,
        )

    @pytest.mark.asyncio
    async def test_fetch_one_get_op(self, prov: MemoryAPIProvider[int, User]) -> None:
        q = api(User, key=lambda u: u.id).get(1)
        result = await prov.fetch_one(q)
        assert result is not None
        assert result.name == "alice"

    @pytest.mark.asyncio
    async def test_fetch_one_get_missing(self, prov: MemoryAPIProvider[int, User]) -> None:
        q = api(User, key=lambda u: u.id).get(999)
        result = await prov.fetch_one(q)
        assert result is None

    @pytest.mark.asyncio
    async def test_fetch_one_list_op(self, prov: MemoryAPIProvider[int, User]) -> None:
        q = api(User, key=lambda u: u.id).list()
        result = await prov.fetch_one(q)
        assert result is not None

    @pytest.mark.asyncio
    async def test_fetch_one_list_op_empty(self) -> None:
        prov = MemoryAPIProvider[int, User](key_fn=lambda u: u.id)
        q = api(User, key=lambda u: u.id).list()
        result = await prov.fetch_one(q)
        assert result is None

    @pytest.mark.asyncio
    async def test_fetch_one_wrong_op_raises(self, prov: MemoryAPIProvider[int, User]) -> None:
        q = api(User, key=lambda u: u.id).create(ALICE)
        with pytest.raises(TypeError, match="fetch_one.*expects"):
            await prov.fetch_one(q)

    @pytest.mark.asyncio
    async def test_fetch_one_get_without_key_fn_raises(self) -> None:
        prov = MemoryAPIProvider[int, User](data=[ALICE])
        q = api(User, key=lambda u: u.id).get(1)
        with pytest.raises(TypeError, match="requires key_fn"):
            await prov.fetch_one(q)


class TestMemoryAPIProviderFetchMany:
    @pytest.fixture
    def prov(self) -> MemoryAPIProvider[int, User]:
        return MemoryAPIProvider[int, User](
            data=[ALICE, BOB, CHARLIE],
            key_fn=lambda u: u.id,
        )

    @pytest.mark.asyncio
    async def test_fetch_many_all(self, prov: MemoryAPIProvider[int, User]) -> None:
        q = api(User, key=lambda u: u.id).list()
        result = await prov.fetch_many(q)
        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_fetch_many_with_filter(self, prov: MemoryAPIProvider[int, User]) -> None:
        q = api(User, key=lambda u: u.id).list().filter(lambda u: u.active == True)
        result = await prov.fetch_many(q)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_fetch_many_with_order(self, prov: MemoryAPIProvider[int, User]) -> None:
        q = api(User, key=lambda u: u.id).list().order_by(lambda u: u.balance.desc())
        result = await prov.fetch_many(q)
        assert result[0].name == "charlie"

    @pytest.mark.asyncio
    async def test_fetch_many_with_search(self, prov: MemoryAPIProvider[int, User]) -> None:
        q = api(User, key=lambda u: u.id).list().search("alice")
        result = await prov.fetch_many(q)
        assert len(result) == 1
        assert result[0].name == "alice"

    @pytest.mark.asyncio
    async def test_fetch_many_with_page_pagination(self, prov: MemoryAPIProvider[int, User]) -> None:
        q = api(User, key=lambda u: u.id).list().page(1, per_page=2)
        result = await prov.fetch_many(q)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_fetch_many_with_offset_pagination(self, prov: MemoryAPIProvider[int, User]) -> None:
        q = api(User, key=lambda u: u.id).list().offset(1, limit=2)
        result = await prov.fetch_many(q)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_fetch_many_with_cursor_pagination(self, prov: MemoryAPIProvider[int, User]) -> None:
        q = api(User, key=lambda u: u.id).list().cursor("0", limit=2)
        result = await prov.fetch_many(q)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_fetch_many_with_invalid_cursor(self, prov: MemoryAPIProvider[int, User]) -> None:
        q = api(User, key=lambda u: u.id).list().cursor("invalid", limit=2)
        result = await prov.fetch_many(q)
        assert len(result) == 2  # defaults to start=0

    @pytest.mark.asyncio
    async def test_fetch_many_wrong_op_raises(self, prov: MemoryAPIProvider[int, User]) -> None:
        q = api(User, key=lambda u: u.id).get(1)
        with pytest.raises(TypeError, match="fetch_many.*expects"):
            await prov.fetch_many(q)

    @pytest.mark.asyncio
    async def test_include_mod_raises(self, prov: MemoryAPIProvider[int, User]) -> None:
        q = api(User, key=lambda u: u.id).list().include("posts")
        with pytest.raises(TypeError, match="IncludeMod"):
            await prov.fetch_many(q)


class TestMemoryAPIProviderFetchPage:
    @pytest.mark.asyncio
    async def test_fetch_page_basic(self) -> None:
        prov = MemoryAPIProvider[int, User](
            data=[ALICE, BOB, CHARLIE],
            key_fn=lambda u: u.id,
        )
        q = api(User, key=lambda u: u.id).list().page(1, per_page=2)
        result = await prov.fetch_page(q)
        assert isinstance(result, MemoryAPIListResult)
        assert len(result.items) == 2
        assert result.total == 3
        assert result.has_more is True

    @pytest.mark.asyncio
    async def test_fetch_page_last(self) -> None:
        prov = MemoryAPIProvider[int, User](
            data=[ALICE, BOB, CHARLIE],
            key_fn=lambda u: u.id,
        )
        q = api(User, key=lambda u: u.id).list().page(2, per_page=2)
        result = await prov.fetch_page(q)
        assert len(result.items) == 1
        assert result.has_more is False

    @pytest.mark.asyncio
    async def test_fetch_page_no_pagination(self) -> None:
        prov = MemoryAPIProvider[int, User](
            data=[ALICE, BOB],
            key_fn=lambda u: u.id,
        )
        q = api(User, key=lambda u: u.id).list()
        result = await prov.fetch_page(q)
        assert len(result.items) == 2
        assert result.has_more is False

    @pytest.mark.asyncio
    async def test_fetch_page_wrong_op_raises(self) -> None:
        prov = MemoryAPIProvider[int, User](key_fn=lambda u: u.id)
        q = api(User, key=lambda u: u.id).get(1)
        with pytest.raises(TypeError, match="fetch_page.*expects"):
            await prov.fetch_page(q)


class TestMemoryAPIProviderWrite:
    @pytest.fixture
    def prov(self) -> MemoryAPIProvider[int, User]:
        return MemoryAPIProvider[int, User](
            data=[ALICE, BOB],
            key_fn=lambda u: u.id,
        )

    @pytest.mark.asyncio
    async def test_create(self, prov: MemoryAPIProvider[int, User]) -> None:
        q = api(User, key=lambda u: u.id).create(CHARLIE)
        result = await prov.execute(q)
        assert result.name == "charlie"
        assert len(prov.data) == 3

    @pytest.mark.asyncio
    async def test_update_full(self, prov: MemoryAPIProvider[int, User]) -> None:
        updated = User(1, "alice_v2", 999.0)
        q = api(User, key=lambda u: u.id).update(1, updated)
        result = await prov.execute(q)
        assert result.name == "alice_v2"

    @pytest.mark.asyncio
    async def test_update_partial(self, prov: MemoryAPIProvider[int, User]) -> None:
        partial = User(1, "alice_partial", 100.0)
        q = api(User, key=lambda u: u.id).update(1, partial, partial=True)
        result = await prov.execute(q)
        assert result.name == "alice_partial"

    @pytest.mark.asyncio
    async def test_update_not_found_raises(self, prov: MemoryAPIProvider[int, User]) -> None:
        updated = User(999, "nobody", 0.0)
        q = api(User, key=lambda u: u.id).update(999, updated)
        with pytest.raises(ValueError, match="not found"):
            await prov.execute(q)

    @pytest.mark.asyncio
    async def test_update_without_key_fn_raises(self) -> None:
        prov = MemoryAPIProvider[int, User](data=[ALICE])
        q = api(User, key=lambda u: u.id).update(1, ALICE)
        with pytest.raises(TypeError, match="requires key_fn"):
            await prov.execute(q)

    @pytest.mark.asyncio
    async def test_execute_wrong_op_raises(self, prov: MemoryAPIProvider[int, User]) -> None:
        q = api(User, key=lambda u: u.id).list()
        with pytest.raises(TypeError, match="execute.*expects"):
            await prov.execute(q)


class TestMemoryAPIProviderDelete:
    @pytest.mark.asyncio
    async def test_delete_existing(self) -> None:
        prov = MemoryAPIProvider[int, User](
            data=[ALICE, BOB],
            key_fn=lambda u: u.id,
        )
        q = api(User, key=lambda u: u.id).delete(1)
        result = await prov.delete(q)
        assert result is True
        assert len(prov.data) == 1

    @pytest.mark.asyncio
    async def test_delete_missing(self) -> None:
        prov = MemoryAPIProvider[int, User](
            data=[ALICE],
            key_fn=lambda u: u.id,
        )
        q = api(User, key=lambda u: u.id).delete(999)
        result = await prov.delete(q)
        assert result is False

    @pytest.mark.asyncio
    async def test_delete_wrong_op_raises(self) -> None:
        prov = MemoryAPIProvider[int, User](key_fn=lambda u: u.id)
        q = api(User, key=lambda u: u.id).list()
        with pytest.raises(TypeError, match="delete.*expects"):
            await prov.delete(q)

    @pytest.mark.asyncio
    async def test_delete_without_key_fn_raises(self) -> None:
        prov = MemoryAPIProvider[int, User](data=[ALICE])
        q = api(User, key=lambda u: u.id).delete(1)
        with pytest.raises(TypeError, match="requires key_fn"):
            await prov.delete(q)


class TestMemoryAPIProviderNextId:
    @pytest.mark.asyncio
    async def test_next_id_with_generator(self) -> None:
        prov = MemoryAPIProvider[int, User](next_id=SequenceNextId())
        assert await prov.next_id() == 1
        assert await prov.next_id() == 2

    @pytest.mark.asyncio
    async def test_next_id_without_generator_raises(self) -> None:
        prov = MemoryAPIProvider[int, User]()
        with pytest.raises(RuntimeError, match="No next_id"):
            await prov.next_id()


class TestMemoryAPIProviderSelectMod:
    @pytest.mark.asyncio
    async def test_select_mod(self) -> None:
        prov = MemoryAPIProvider[int, User](
            data=[ALICE, BOB],
            key_fn=lambda u: u.id,
        )
        q = api(User, key=lambda u: u.id).list().select(lambda u: u.name, lambda u: u.id)
        result = await prov.fetch_many(q)
        # Select returns dicts in memory provider
        assert len(result) == 2


class TestMemoryAPIProviderMisc:
    def test_clear(self) -> None:
        prov = MemoryAPIProvider[int, User](data=[ALICE, BOB])
        assert len(prov.data) == 2
        prov.clear()
        assert len(prov.data) == 0

    def test_data_property(self) -> None:
        prov = MemoryAPIProvider[int, User](data=[ALICE])
        assert prov.data == [ALICE]

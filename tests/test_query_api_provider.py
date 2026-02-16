"""Tests for MemoryAPIProvider."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any

import pytest
import pytest_asyncio

from emergent.wire.axis.query._api import api, APIQuerySet
from emergent.wire.axis.query.providers.memory import MemoryAPIProvider, MemoryAPIListResult
from emergent.wire.axis.query._provider import SequenceNextId
from emergent.wire.axis.schema._universal import Identity


# ─── Test Entity ──────────────────────────────────────────────────────────────


@dataclass
class Item:
    id: Annotated[int, Identity]
    name: str
    price: float = 0.0
    active: bool = True


# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def prov():
    return MemoryAPIProvider[int, Item](
        key_fn=lambda x: x.id,
        next_id=SequenceNextId(),
    )


@pytest_asyncio.fixture
async def populated(prov):
    items = [
        Item(1, "Alpha", 10.0, True),
        Item(2, "Beta", 20.0, True),
        Item(3, "Gamma", 30.0, False),
        Item(4, "Delta", 5.0, True),
        Item(5, "Epsilon", 50.0, False),
    ]
    for item in items:
        await prov.execute(api(Item).create(item))
    return prov


# ─── Create ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create(prov):
    item = Item(1, "Alpha", 10.0)
    result = await prov.execute(api(Item).create(item))
    assert result.name == "Alpha"
    assert len(prov.data) == 1


@pytest.mark.asyncio
async def test_create_multiple(prov):
    await prov.execute(api(Item).create(Item(1, "A", 1.0)))
    await prov.execute(api(Item).create(Item(2, "B", 2.0)))
    assert len(prov.data) == 2


# ─── Get ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_existing(populated):
    result = await populated.fetch_one(api(Item).get(2))
    assert result is not None
    assert result.name == "Beta"


@pytest.mark.asyncio
async def test_get_missing(populated):
    result = await populated.fetch_one(api(Item).get(999))
    assert result is None


@pytest.mark.asyncio
async def test_get_requires_key_fn():
    prov = MemoryAPIProvider[int, Item]()
    with pytest.raises(TypeError, match="requires key_fn"):
        await prov.fetch_one(api(Item).get(1))


# ─── List ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_all(populated):
    result = await populated.fetch_many(api(Item).list())
    assert len(result) == 5


@pytest.mark.asyncio
async def test_list_empty(prov):
    result = await prov.fetch_many(api(Item).list())
    assert result == []


# ─── Filter ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_filter_boolean(populated):
    q = api(Item).list().filter(lambda x: x.active == True)
    result = await populated.fetch_many(q)
    assert len(result) == 3
    assert all(r.active for r in result)


@pytest.mark.asyncio
async def test_filter_comparison(populated):
    q = api(Item).list().filter(lambda x: x.price > 15)
    result = await populated.fetch_many(q)
    assert len(result) == 3
    assert all(r.price > 15 for r in result)


@pytest.mark.asyncio
async def test_filter_chained(populated):
    q = (
        api(Item).list()
        .filter(lambda x: x.active == True)
        .filter(lambda x: x.price >= 10)
    )
    result = await populated.fetch_many(q)
    assert len(result) == 2
    names = {r.name for r in result}
    assert names == {"Alpha", "Beta"}


# ─── Order ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_order_by_asc(populated):
    q = api(Item).list().order_by(lambda x: x.price)
    result = await populated.fetch_many(q)
    prices = [r.price for r in result]
    assert prices == sorted(prices)


@pytest.mark.asyncio
async def test_order_by_desc(populated):
    q = api(Item).list().order_by(lambda x: x.price.desc())
    result = await populated.fetch_many(q)
    prices = [r.price for r in result]
    assert prices == sorted(prices, reverse=True)


# ─── Pagination ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_page_pagination(populated):
    q = api(Item).list().order_by(lambda x: x.id).page(1, per_page=2)
    result = await populated.fetch_many(q)
    assert len(result) == 2
    assert result[0].id == 1
    assert result[1].id == 2


@pytest.mark.asyncio
async def test_page_pagination_second_page(populated):
    q = api(Item).list().order_by(lambda x: x.id).page(2, per_page=2)
    result = await populated.fetch_many(q)
    assert len(result) == 2
    assert result[0].id == 3


@pytest.mark.asyncio
async def test_offset_pagination(populated):
    q = api(Item).list().order_by(lambda x: x.id).offset(2, limit=2)
    result = await populated.fetch_many(q)
    assert len(result) == 2
    assert result[0].id == 3
    assert result[1].id == 4


@pytest.mark.asyncio
async def test_cursor_pagination(populated):
    q = api(Item).list().order_by(lambda x: x.id).cursor("2", limit=2)
    result = await populated.fetch_many(q)
    assert len(result) == 2
    assert result[0].id == 3


# ─── Search ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search(populated):
    q = api(Item).list().search("alpha")
    result = await populated.fetch_many(q)
    assert len(result) == 1
    assert result[0].name == "Alpha"


@pytest.mark.asyncio
async def test_search_case_insensitive(populated):
    q = api(Item).list().search("BETA")
    result = await populated.fetch_many(q)
    assert len(result) == 1
    assert result[0].name == "Beta"


@pytest.mark.asyncio
async def test_search_no_match(populated):
    q = api(Item).list().search("zzzzz")
    result = await populated.fetch_many(q)
    assert result == []


# ─── Update ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_full(populated):
    updated = Item(2, "Beta Updated", 99.0, False)
    result = await populated.execute(api(Item).update(2, updated))
    assert result.name == "Beta Updated"
    assert result.price == 99.0

    fetched = await populated.fetch_one(api(Item).get(2))
    assert fetched is not None
    assert fetched.name == "Beta Updated"


@pytest.mark.asyncio
async def test_update_partial(populated):
    """Partial update — only non-None fields are merged."""
    # Update only price, keep other fields
    partial = Item(2, None, 99.0, None)  # type: ignore[arg-type]
    result = await populated.execute(api(Item).update(2, partial, partial=True))

    assert result.name == "Beta"  # unchanged
    assert result.price == 99.0  # updated
    assert result.active is True  # unchanged (was True, partial has None)

    fetched = await populated.fetch_one(api(Item).get(2))
    assert fetched is not None
    assert fetched.name == "Beta"
    assert fetched.price == 99.0


@pytest.mark.asyncio
async def test_update_not_found(populated):
    with pytest.raises(ValueError, match="not found"):
        await populated.execute(api(Item).update(999, Item(999, "X", 0.0)))


@pytest.mark.asyncio
async def test_update_requires_key_fn():
    prov = MemoryAPIProvider[int, Item]()
    with pytest.raises(TypeError, match="requires key_fn"):
        await prov.execute(api(Item).update(1, Item(1, "X", 0.0)))


# ─── Delete ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_existing(populated):
    result = await populated.delete(api(Item).delete(3))
    assert result is True
    assert len(populated.data) == 4
    assert await populated.fetch_one(api(Item).get(3)) is None


@pytest.mark.asyncio
async def test_delete_missing(populated):
    result = await populated.delete(api(Item).delete(999))
    assert result is False
    assert len(populated.data) == 5


@pytest.mark.asyncio
async def test_delete_requires_key_fn():
    prov = MemoryAPIProvider[int, Item]()
    with pytest.raises(TypeError, match="requires key_fn"):
        await prov.delete(api(Item).delete(1))


# ─── fetch_page (PaginatedAPIProvider) ───────────────────────────────────────


@pytest.mark.asyncio
async def test_fetch_page_first(populated):
    q = api(Item).list().order_by(lambda x: x.id).page(1, per_page=2)
    result = await populated.fetch_page(q)
    assert isinstance(result, MemoryAPIListResult)
    assert len(result.items) == 2
    assert result.total == 5
    assert result.has_more is True


@pytest.mark.asyncio
async def test_fetch_page_last(populated):
    q = api(Item).list().order_by(lambda x: x.id).page(3, per_page=2)
    result = await populated.fetch_page(q)
    assert len(result.items) == 1
    assert result.total == 5
    assert result.has_more is False


@pytest.mark.asyncio
async def test_fetch_page_no_pagination(populated):
    q = api(Item).list()
    result = await populated.fetch_page(q)
    assert len(result.items) == 5
    assert result.total == 5
    assert result.has_more is False


# ─── Combined ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_filter_order_page(populated):
    q = (
        api(Item).list()
        .filter(lambda x: x.active == True)
        .order_by(lambda x: x.price.desc())
        .page(1, per_page=2)
    )
    result = await populated.fetch_many(q)
    assert len(result) == 2
    assert result[0].name == "Beta"  # price 20.0
    assert result[1].name == "Alpha"  # price 10.0


# ─── Error Cases ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fetch_many_wrong_op(populated):
    with pytest.raises(TypeError, match="expects ListOp"):
        await populated.fetch_many(api(Item).get(1))


@pytest.mark.asyncio
async def test_fetch_page_wrong_op(populated):
    with pytest.raises(TypeError, match="expects ListOp"):
        await populated.fetch_page(api(Item).get(1))


@pytest.mark.asyncio
async def test_execute_wrong_op(populated):
    with pytest.raises(TypeError, match="expects CreateOp or UpdateOp"):
        await populated.execute(api(Item).list())


@pytest.mark.asyncio
async def test_delete_wrong_op(populated):
    with pytest.raises(TypeError, match="expects DeleteOp"):
        await populated.delete(api(Item).list())


@pytest.mark.asyncio
async def test_fetch_one_wrong_op(populated):
    with pytest.raises(TypeError, match="expects GetOp or ListOp"):
        await populated.fetch_one(api(Item).create(Item(1, "X", 0.0)))


# ─── next_id ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_next_id(prov):
    assert await prov.next_id() == 1
    assert await prov.next_id() == 2


@pytest.mark.asyncio
async def test_next_id_not_configured():
    prov = MemoryAPIProvider[int, Item]()
    with pytest.raises(RuntimeError, match="No next_id"):
        await prov.next_id()


# ─── clear ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_clear(populated):
    assert len(populated.data) == 5
    populated.clear()
    assert len(populated.data) == 0


# ─── SelectMod / IncludeMod ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_select_mod(populated):
    """SelectMod projects items to dicts with only specified fields."""
    q = api(Item).list().select(lambda x: x.name, lambda x: x.price)
    items = await populated.fetch_many(q)
    assert len(items) == 5
    for item in items:
        assert set(item.keys()) == {"name", "price"}
    assert items[0]["name"] == "Alpha"


@pytest.mark.asyncio
async def test_include_mod_raises(populated):
    """IncludeMod raises TypeError — memory provider can't resolve relations."""
    q = api(Item).list().include("category")
    with pytest.raises(TypeError, match="IncludeMod requires relation metadata"):
        await populated.fetch_many(q)


# ─── Edge Cases ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_partial_update_all_none(populated):
    """Partial update where ALL fields are None — entity stays unchanged."""
    partial = Item(2, None, None, None)  # type: ignore[arg-type]
    result = await populated.execute(api(Item).update(2, partial, partial=True))

    # id is not None so it gets merged, but name/price/active stay from original
    fetched = await populated.fetch_one(api(Item).get(2))
    assert fetched is not None
    assert fetched.name == "Beta"
    assert fetched.price == 20.0
    assert fetched.active is True


@pytest.mark.asyncio
async def test_create_duplicate_id(prov):
    """Create with duplicate ID — no dedup, both stored (memory is simple list)."""
    await prov.execute(api(Item).create(Item(1, "Alpha", 10.0)))
    await prov.execute(api(Item).create(Item(1, "Alpha Copy", 20.0)))
    assert len(prov.data) == 2


# ─── Integration: API CRUD Lifecycle ────────────────────────────────────────


@pytest.mark.asyncio
class TestIntegrationAPICRUDLifecycle:
    async def test_full_lifecycle(self):
        prov = MemoryAPIProvider[int, Item](
            key_fn=lambda x: x.id,
            next_id=SequenceNextId(),
        )
        # Create 5 items
        items = [
            Item(1, "Alpha", 10.0, True),
            Item(2, "Beta", 20.0, True),
            Item(3, "Gamma", 30.0, False),
            Item(4, "Delta", 5.0, True),
            Item(5, "Epsilon", 50.0, False),
        ]
        for item in items:
            await prov.execute(api(Item).create(item))

        # List with filter: active only
        active = await prov.fetch_many(
            api(Item).list().filter(lambda x: x.active == True)
        )
        assert len(active) == 3

        # Get by id
        got = await prov.fetch_one(api(Item).get(2))
        assert got is not None
        assert got.name == "Beta"

        # Update price
        updated = Item(2, "Beta", 99.0, True)
        result = await prov.execute(api(Item).update(2, updated))
        assert result.price == 99.0

        # Delete
        deleted = await prov.delete(api(Item).delete(3))
        assert deleted is True

        # Verify count
        all_items = await prov.fetch_many(api(Item).list())
        assert len(all_items) == 4

    async def test_paginate_through_all(self):
        prov = MemoryAPIProvider[int, Item](
            key_fn=lambda x: x.id,
            next_id=SequenceNextId(),
        )
        for i in range(1, 6):
            await prov.execute(api(Item).create(Item(i, f"Item{i}", float(i * 10))))

        # Page 1
        page1 = await prov.fetch_many(
            api(Item).list().order_by(lambda x: x.id).page(1, per_page=2)
        )
        assert len(page1) == 2
        assert page1[0].id == 1
        assert page1[1].id == 2

        # Page 2
        page2 = await prov.fetch_many(
            api(Item).list().order_by(lambda x: x.id).page(2, per_page=2)
        )
        assert len(page2) == 2
        assert page2[0].id == 3
        assert page2[1].id == 4

        # Page 3 (partial)
        page3 = await prov.fetch_many(
            api(Item).list().order_by(lambda x: x.id).page(3, per_page=2)
        )
        assert len(page3) == 1
        assert page3[0].id == 5

    async def test_search_and_filter_combined(self):
        prov = MemoryAPIProvider[int, Item](
            key_fn=lambda x: x.id,
            next_id=SequenceNextId(),
        )
        await prov.execute(api(Item).create(Item(1, "Alpha Plus", 10.0, True)))
        await prov.execute(api(Item).create(Item(2, "Alpha Basic", 20.0, False)))
        await prov.execute(api(Item).create(Item(3, "Beta Plus", 30.0, True)))

        # Search "alpha" + filter active
        result = await prov.fetch_many(
            api(Item).list()
            .search("alpha")
            .filter(lambda x: x.active == True)
        )
        assert len(result) == 1
        assert result[0].name == "Alpha Plus"

    async def test_ordering_persists_through_operations(self):
        prov = MemoryAPIProvider[int, Item](
            key_fn=lambda x: x.id,
            next_id=SequenceNextId(),
        )
        for i in [3, 1, 5, 2, 4]:
            await prov.execute(api(Item).create(Item(i, f"Item{i}", float(i * 10))))

        result = await prov.fetch_many(
            api(Item).list()
            .filter(lambda x: x.active == True)
            .order_by(lambda x: x.price.desc())
        )
        prices = [r.price for r in result]
        assert prices == sorted(prices, reverse=True)

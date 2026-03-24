# pyright: reportPrivateUsage=false
"""Property-based tests for QuerySet and MemoryRelationalProvider.

Uses hypothesis to verify algebraic properties of relational query operations:
immutability, commutativity, idempotence, monotonicity, and subset preservation.

Also tests MemoryRelationalProvider mutations, MemoryKVProvider operations,
and aggregation functions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

import pytest
import hypothesis.strategies as st
from hypothesis import given, settings

from emergent.wire.axis.query._expr import (
    And,
    Const,
    Eq,
    Expr,
    Field,
    Gt,
    Lt,
)
from emergent.wire.axis.query._relational import (
    Distinct,
    Filter,
    Limit,
    Offset,
    OrderBy,
    Select,
    RelationalQuerySet,
    relational,
)
from emergent.wire.axis.query._proxy import OrderSpec
from emergent.wire.axis.query._kv import (
    kv,
)
from emergent.wire.axis.query.providers.memory import (
    MemoryRelationalProvider,
    MemoryKVProvider,
)


# ── Test entity ──────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Item:
    id: int
    value: int
    name: str
    active: bool = True


# ── Strategies ───────────────────────────────────────────────────────────────


st_name = st.text(
    alphabet=st.characters(categories=("L", "N")),
    min_size=1,
    max_size=10,
)

st_item = st.builds(
    Item,
    id=st.integers(min_value=0, max_value=1000),
    value=st.integers(min_value=-100, max_value=100),
    name=st_name,
    active=st.booleans(),
)

st_items = st.lists(st_item, min_size=0, max_size=50)


def st_filter_expr() -> st.SearchStrategy[Expr]:
    """Generate simple filter expressions over Item fields."""
    return st.one_of(
        st.builds(
            Eq,
            left=st.just(Field("active")),
            right=st.booleans().map(Const),
        ),
        st.builds(
            Gt,
            left=st.just(Field("value")),
            right=st.integers(min_value=-100, max_value=100).map(Const),
        ),
        st.builds(
            Lt,
            left=st.just(Field("value")),
            right=st.integers(min_value=-100, max_value=100).map(Const),
        ),
        st.builds(
            Eq,
            left=st.just(Field("id")),
            right=st.integers(min_value=0, max_value=1000).map(Const),
        ),
    )


def _execute(items: list[Item], qs: RelationalQuerySet[Item]) -> list[Item]:
    """Execute a query against items using MemoryRelationalProvider."""
    provider: MemoryRelationalProvider[Item] = MemoryRelationalProvider(data=items)
    return provider.execute(qs)


def _item_key(item: Item) -> tuple[int, int, str, bool]:
    return (item.id, item.value, item.name, item.active)


# ══════════════════════════════════════════════════════════════════════════════
# Property-based relational tests (original)
# ══════════════════════════════════════════════════════════════════════════════


# ── Property 1: Empty queryset ──────────────────────────────────────────────


def test_empty_queryset_has_no_ops() -> None:
    qs = relational(Item)
    assert qs.ops == ()


@given(items=st_items)
@settings(max_examples=50)
def test_empty_queryset_returns_all_data(items: list[Item]) -> None:
    qs = relational(Item)
    result = _execute(items, qs)
    assert result == items


# ── Property 2: Immutability ────────────────────────────────────────────────


@given(expr=st_filter_expr())
@settings(max_examples=50)
def test_filter_returns_new_queryset_original_unchanged(expr: Expr) -> None:
    original = relational(Item)
    filtered = RelationalQuerySet(entity=Item, ops=(Filter(expr),))
    # Original is untouched
    assert original.ops == ()
    # Filtered has the op
    assert len(filtered.ops) == 1
    assert original is not filtered


@given(n=st.integers(min_value=0, max_value=100))
@settings(max_examples=50)
def test_limit_returns_new_queryset_original_unchanged(n: int) -> None:
    original = relational(Item)
    limited = original.limit(n)
    assert original.ops == ()
    assert len(limited.ops) == 1
    assert original is not limited


# ── Property 3: Filter commutativity ────────────────────────────────────────


@given(items=st_items, expr_a=st_filter_expr(), expr_b=st_filter_expr())
@settings(max_examples=100)
def test_filter_commutativity(
    items: list[Item], expr_a: Expr, expr_b: Expr
) -> None:
    """filter(a).filter(b) gives same results as filter(b).filter(a)."""
    qs_ab = RelationalQuerySet(
        entity=Item, ops=(Filter(expr_a), Filter(expr_b))
    )
    qs_ba = RelationalQuerySet(
        entity=Item, ops=(Filter(expr_b), Filter(expr_a))
    )
    result_ab = _execute(items, qs_ab)
    result_ba = _execute(items, qs_ba)
    assert result_ab == result_ba


# ── Property 4: Filter-And equivalence ──────────────────────────────────────


@given(items=st_items, expr_a=st_filter_expr(), expr_b=st_filter_expr())
@settings(max_examples=100)
def test_filter_and_equivalence(
    items: list[Item], expr_a: Expr, expr_b: Expr
) -> None:
    """filter(a).filter(b) same results as filter(And(a, b))."""
    qs_chained = RelationalQuerySet(
        entity=Item, ops=(Filter(expr_a), Filter(expr_b))
    )
    qs_combined = RelationalQuerySet(
        entity=Item, ops=(Filter(And(expr_a, expr_b)),)
    )
    result_chained = _execute(items, qs_chained)
    result_combined = _execute(items, qs_combined)
    assert result_chained == result_combined


# ── Property 5: Limit monotonicity ──────────────────────────────────────────


@given(items=st_items, n=st.integers(min_value=0, max_value=200))
@settings(max_examples=100)
def test_limit_monotonicity(items: list[Item], n: int) -> None:
    """len(results of .limit(n)) <= n."""
    qs = RelationalQuerySet(entity=Item, ops=(Limit(n),))
    result = _execute(items, qs)
    assert len(result) <= n


# ── Property 6: Limit idempotence ───────────────────────────────────────────


@given(items=st_items, n=st.integers(min_value=0, max_value=200))
@settings(max_examples=100)
def test_limit_idempotence(items: list[Item], n: int) -> None:
    """limit(n).limit(n) same results as limit(n)."""
    qs_single = RelationalQuerySet(entity=Item, ops=(Limit(n),))
    qs_double = RelationalQuerySet(entity=Item, ops=(Limit(n), Limit(n)))
    result_single = _execute(items, qs_single)
    result_double = _execute(items, qs_double)
    assert result_single == result_double


# ── Property 7: Offset bounds ───────────────────────────────────────────────


@given(items=st_items, k=st.integers(min_value=0, max_value=200))
@settings(max_examples=100)
def test_offset_bounds(items: list[Item], k: int) -> None:
    """offset(k) on data of length L gives at most max(0, L - k) results."""
    qs = RelationalQuerySet(entity=Item, ops=(Offset(k),))
    result = _execute(items, qs)
    expected_max = max(0, len(items) - k)
    assert len(result) == expected_max


# ── Property 8: Distinct idempotence ────────────────────────────────────────


@given(items=st_items)
@settings(max_examples=100)
def test_distinct_idempotence(items: list[Item]) -> None:
    """distinct().distinct() same results as distinct()."""
    qs_single = RelationalQuerySet(entity=Item, ops=(Distinct(),))
    qs_double = RelationalQuerySet(entity=Item, ops=(Distinct(), Distinct()))
    result_single = _execute(items, qs_single)
    result_double = _execute(items, qs_double)
    assert result_single == result_double


@given(items=st_items)
@settings(max_examples=100)
def test_distinct_removes_duplicates(items: list[Item]) -> None:
    """distinct() results contain no duplicate items."""
    qs = RelationalQuerySet(entity=Item, ops=(Distinct(),))
    result = _execute(items, qs)
    keys = [_item_key(item) for item in result]
    assert len(keys) == len(set(keys))


# ── Property 9: Filter preserves subset ─────────────────────────────────────


@given(items=st_items, expr=st_filter_expr())
@settings(max_examples=100)
def test_filter_preserves_subset(items: list[Item], expr: Expr) -> None:
    """Results of filter(expr) is a subset of original data."""
    qs = RelationalQuerySet(entity=Item, ops=(Filter(expr),))
    result = _execute(items, qs)
    for item in result:
        assert item in items


# ── Composite properties ────────────────────────────────────────────────────


@given(
    items=st_items,
    expr=st_filter_expr(),
    n=st.integers(min_value=0, max_value=200),
)
@settings(max_examples=100)
def test_filter_then_limit_subset_of_filter_alone(
    items: list[Item], expr: Expr, n: int
) -> None:
    """filter(e).limit(n) is a subset of filter(e)."""
    qs_filter = RelationalQuerySet(entity=Item, ops=(Filter(expr),))
    qs_filter_limit = RelationalQuerySet(
        entity=Item, ops=(Filter(expr), Limit(n))
    )
    result_filter = _execute(items, qs_filter)
    result_filter_limit = _execute(items, qs_filter_limit)
    for item in result_filter_limit:
        assert item in result_filter


@given(
    items=st_items,
    k=st.integers(min_value=0, max_value=100),
    n=st.integers(min_value=0, max_value=100),
)
@settings(max_examples=100)
def test_offset_then_limit_consistent_with_slice(
    items: list[Item], k: int, n: int
) -> None:
    """offset(k).limit(n) equals items[k:k+n]."""
    qs = RelationalQuerySet(entity=Item, ops=(Offset(k), Limit(n)))
    result = _execute(items, qs)
    expected = items[k : k + n]
    assert result == expected


@given(
    items=st_items,
    expr=st_filter_expr(),
    k=st.integers(min_value=0, max_value=100),
)
@settings(max_examples=100)
def test_filter_then_offset_count_bounded(
    items: list[Item], expr: Expr, k: int
) -> None:
    """len(filter(e).offset(k)) <= max(0, len(filter(e)) - k)."""
    qs_filter = RelationalQuerySet(entity=Item, ops=(Filter(expr),))
    qs_filter_offset = RelationalQuerySet(
        entity=Item, ops=(Filter(expr), Offset(k))
    )
    result_filter = _execute(items, qs_filter)
    result_filter_offset = _execute(items, qs_filter_offset)
    expected_max = max(0, len(result_filter) - k)
    assert len(result_filter_offset) == expected_max


@given(
    items=st_items,
    n=st.integers(min_value=1, max_value=100),
    m=st.integers(min_value=1, max_value=100),
)
@settings(max_examples=100)
def test_smaller_limit_gives_fewer_or_equal_results(
    items: list[Item], n: int, m: int
) -> None:
    """If n <= m then len(limit(n)) <= len(limit(m))."""
    small, big = min(n, m), max(n, m)
    qs_small = RelationalQuerySet(entity=Item, ops=(Limit(small),))
    qs_big = RelationalQuerySet(entity=Item, ops=(Limit(big),))
    result_small = _execute(items, qs_small)
    result_big = _execute(items, qs_big)
    assert len(result_small) <= len(result_big)


@given(items=st_items, expr=st_filter_expr())
@settings(max_examples=100)
def test_filter_preserves_order(items: list[Item], expr: Expr) -> None:
    """Filtered results appear in the same relative order as input."""
    qs = RelationalQuerySet(entity=Item, ops=(Filter(expr),))
    result = _execute(items, qs)
    # Extract indices in original list
    result_ids = [id(item) for item in result]
    original_ids = [id(item) for item in items]
    indices = [original_ids.index(rid) for rid in result_ids]
    assert indices == sorted(indices)


# ══════════════════════════════════════════════════════════════════════════════
# Additional relational tests
# ══════════════════════════════════════════════════════════════════════════════


# ── OrderBy correctness ─────────────────────────────────────────────────────


@given(items=st_items)
@settings(max_examples=100)
def test_order_by_ascending_sorts_correctly(items: list[Item]) -> None:
    """After order_by on 'value' ascending, results are sorted."""
    qs = RelationalQuerySet(
        entity=Item,
        ops=(OrderBy(specs=(OrderSpec(field="value", ascending=True),)),),
    )
    result = _execute(items, qs)
    values = [item.value for item in result]
    assert values == sorted(values)


@given(items=st_items)
@settings(max_examples=100)
def test_order_by_descending_sorts_correctly(items: list[Item]) -> None:
    """After order_by on 'value' descending, results are reverse sorted."""
    qs = RelationalQuerySet(
        entity=Item,
        ops=(OrderBy(specs=(OrderSpec(field="value", ascending=False),)),),
    )
    result = _execute(items, qs)
    values = [item.value for item in result]
    assert values == sorted(values, reverse=True)


# ── Select projection ───────────────────────────────────────────────────────


@given(items=st_items)
@settings(max_examples=50)
def test_select_projection_returns_dicts_with_only_requested_keys(
    items: list[Item],
) -> None:
    """select('id', 'name') returns dicts with only those keys."""
    qs = RelationalQuerySet(
        entity=Item,
        ops=(Select(fields=("id", "name")),),
    )
    result = _execute(items, qs)
    for i, row in enumerate(result):
        assert isinstance(row, dict)
        row_dict = cast(dict[str, object], row)
        assert set(row_dict.keys()) == {"id", "name"}
        assert row_dict["id"] == items[i].id
        assert row_dict["name"] == items[i].name


# ── Filter + OrderBy + Limit composition ────────────────────────────────────


@given(
    items=st_items,
    threshold=st.integers(min_value=-100, max_value=100),
    n=st.integers(min_value=0, max_value=200),
)
@settings(max_examples=100)
def test_filter_order_by_limit_composition(
    items: list[Item], threshold: int, n: int
) -> None:
    """filter -> order_by -> limit: results are filtered, sorted, and limited."""
    expr = Gt(left=Field("value"), right=Const(threshold))
    qs = RelationalQuerySet(
        entity=Item,
        ops=(
            Filter(expr),
            OrderBy(specs=(OrderSpec(field="value", ascending=True),)),
            Limit(n),
        ),
    )
    result = _execute(items, qs)

    # All results pass the filter
    for item in result:
        assert item.value > threshold

    # Results are sorted by value ascending
    values = [item.value for item in result]
    assert values == sorted(values)

    # Result count is at most n
    assert len(result) <= n

    # Result count matches expected
    filtered_count = sum(1 for item in items if item.value > threshold)
    assert len(result) == min(n, filtered_count)


# ── Empty data ──────────────────────────────────────────────────────────────


def test_all_operations_on_empty_data() -> None:
    """All operations work on empty provider and return empty results."""
    empty: list[Item] = []

    # Filter on empty
    expr = Eq(left=Field("active"), right=Const(True))
    qs_filter = RelationalQuerySet(entity=Item, ops=(Filter(expr),))
    assert _execute(empty, qs_filter) == []

    # OrderBy on empty
    qs_order = RelationalQuerySet(
        entity=Item,
        ops=(OrderBy(specs=(OrderSpec(field="value", ascending=True),)),),
    )
    assert _execute(empty, qs_order) == []

    # Limit on empty
    qs_limit = RelationalQuerySet(entity=Item, ops=(Limit(10),))
    assert _execute(empty, qs_limit) == []

    # Offset on empty
    qs_offset = RelationalQuerySet(entity=Item, ops=(Offset(5),))
    assert _execute(empty, qs_offset) == []

    # Select on empty
    qs_select = RelationalQuerySet(
        entity=Item, ops=(Select(fields=("id", "name")),)
    )
    assert _execute(empty, qs_select) == []

    # Distinct on empty
    qs_distinct = RelationalQuerySet(entity=Item, ops=(Distinct(),))
    assert _execute(empty, qs_distinct) == []

    # Composed pipeline on empty
    qs_composed = RelationalQuerySet(
        entity=Item,
        ops=(
            Filter(expr),
            OrderBy(specs=(OrderSpec(field="value", ascending=True),)),
            Limit(10),
        ),
    )
    assert _execute(empty, qs_composed) == []


# ══════════════════════════════════════════════════════════════════════════════
# MemoryRelationalProvider mutation tests (async)
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_insert_increases_count() -> None:
    """After insert, len(data) increases by 1."""
    provider: MemoryRelationalProvider[Item] = MemoryRelationalProvider()
    assert len(provider.data) == 0

    item = Item(id=1, value=42, name="alpha")
    result = await provider.insert(item)

    assert result is item
    assert len(provider.data) == 1
    assert provider.data[0] is item


@pytest.mark.asyncio
async def test_insert_many_inserts_all_items() -> None:
    """insert_many inserts all items."""
    provider: MemoryRelationalProvider[Item] = MemoryRelationalProvider()
    items = [
        Item(id=1, value=10, name="a"),
        Item(id=2, value=20, name="b"),
        Item(id=3, value=30, name="c"),
    ]
    result = await provider.insert_many(items)

    assert len(result) == 3
    assert len(provider.data) == 3
    for original, stored in zip(items, provider.data):
        assert original is stored


@pytest.mark.asyncio
async def test_delete_removes_item() -> None:
    """After delete, item no longer in data."""
    item_a = Item(id=1, value=10, name="a")
    item_b = Item(id=2, value=20, name="b")
    provider: MemoryRelationalProvider[Item] = MemoryRelationalProvider(
        data=[item_a, item_b],
        key_fn=lambda i: i.id,
    )
    assert len(provider.data) == 2

    await provider.delete(item_a)

    assert len(provider.data) == 1
    assert provider.data[0] is item_b


@pytest.mark.asyncio
async def test_update_replaces_item() -> None:
    """After update with key_fn, item is replaced."""
    item = Item(id=1, value=10, name="original")
    provider: MemoryRelationalProvider[Item] = MemoryRelationalProvider(
        data=[item],
        key_fn=lambda i: i.id,
    )

    updated = Item(id=1, value=99, name="updated")
    result = await provider.update(updated)

    assert result is updated
    assert len(provider.data) == 1
    assert provider.data[0].name == "updated"
    assert provider.data[0].value == 99


@pytest.mark.asyncio
async def test_upsert_inserts_when_missing() -> None:
    """upsert on missing key inserts the entity."""
    provider: MemoryRelationalProvider[Item] = MemoryRelationalProvider(
        key_fn=lambda i: i.id,
    )
    assert len(provider.data) == 0

    item = Item(id=1, value=42, name="new")
    result = await provider.upsert(item)

    assert result is item
    assert len(provider.data) == 1
    assert provider.data[0] is item


@pytest.mark.asyncio
async def test_upsert_updates_when_existing() -> None:
    """upsert on existing key updates the entity."""
    original = Item(id=1, value=10, name="original")
    provider: MemoryRelationalProvider[Item] = MemoryRelationalProvider(
        data=[original],
        key_fn=lambda i: i.id,
    )

    updated = Item(id=1, value=99, name="updated")
    result = await provider.upsert(updated)

    assert result is updated
    assert len(provider.data) == 1
    assert provider.data[0].name == "updated"


@pytest.mark.asyncio
async def test_delete_where_removes_matching_items() -> None:
    """delete_where removes items matching the query."""
    items = [
        Item(id=1, value=10, name="a", active=True),
        Item(id=2, value=20, name="b", active=False),
        Item(id=3, value=30, name="c", active=True),
        Item(id=4, value=40, name="d", active=False),
    ]
    provider: MemoryRelationalProvider[Item] = MemoryRelationalProvider(data=items)

    # Delete all inactive items
    expr = Eq(left=Field("active"), right=Const(False))
    qs = RelationalQuerySet(entity=Item, ops=(Filter(expr),))
    deleted_count = await provider.delete_where(qs)

    assert deleted_count == 2
    assert len(provider.data) == 2
    for item in provider.data:
        assert item.active is True


# ══════════════════════════════════════════════════════════════════════════════
# MemoryKVProvider tests (async)
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_kv_set_then_get() -> None:
    """set(k, v) then get(k) returns v."""
    provider: MemoryKVProvider[str, Item] = MemoryKVProvider()
    item = Item(id=1, value=42, name="alice")

    qs_builder = kv(Item, key=lambda i: i.name)

    await provider.set(qs_builder.set("alice", item))
    result = await provider.get(qs_builder.get("alice"))

    assert result.unwrap() is item


@pytest.mark.asyncio
async def test_kv_get_missing_returns_none() -> None:
    """get on missing key returns Ok(None)."""
    provider: MemoryKVProvider[str, Item] = MemoryKVProvider()
    qs_builder = kv(Item, key=lambda i: i.name)

    result = await provider.get(qs_builder.get("nonexistent"))

    assert result.unwrap() is None


@pytest.mark.asyncio
async def test_kv_delete_returns_existed() -> None:
    """delete existing key returns Ok(True), missing returns Ok(False)."""
    provider: MemoryKVProvider[str, Item] = MemoryKVProvider()
    qs_builder = kv(Item, key=lambda i: i.name)
    item = Item(id=1, value=42, name="alice")

    await provider.set(qs_builder.set("alice", item))

    # Delete existing key
    result_existing = await provider.delete(qs_builder.delete("alice"))
    assert result_existing.unwrap() is True

    # Delete missing key
    result_missing = await provider.delete(qs_builder.delete("alice"))
    assert result_missing.unwrap() is False


@pytest.mark.asyncio
async def test_kv_exists() -> None:
    """exists on set key returns Ok(True), missing returns Ok(False)."""
    provider: MemoryKVProvider[str, Item] = MemoryKVProvider()
    qs_builder = kv(Item, key=lambda i: i.name)
    item = Item(id=1, value=42, name="alice")

    # Not yet set
    result_before = await provider.exists(qs_builder.exists("alice"))
    assert result_before.unwrap() is False

    await provider.set(qs_builder.set("alice", item))

    # Now set
    result_after = await provider.exists(qs_builder.exists("alice"))
    assert result_after.unwrap() is True


@pytest.mark.asyncio
async def test_kv_scan_by_pattern() -> None:
    """scan('user_*') finds matching keys."""
    provider: MemoryKVProvider[str, Item] = MemoryKVProvider()
    qs_builder = kv(Item, key=lambda i: i.name)

    items = [
        Item(id=1, value=10, name="user_alice"),
        Item(id=2, value=20, name="user_bob"),
        Item(id=3, value=30, name="admin_charlie"),
    ]
    for item in items:
        await provider.set(qs_builder.set(item.name, item))

    result = await provider.scan(qs_builder.scan("user_*"))
    scan_results = result.unwrap()
    assert len(scan_results) == 2
    scan_names = {item.name for item in scan_results}
    assert scan_names == {"user_alice", "user_bob"}


@pytest.mark.asyncio
async def test_kv_keys_by_pattern() -> None:
    """keys('user_*') returns matching keys."""
    provider: MemoryKVProvider[str, Item] = MemoryKVProvider()
    qs_builder = kv(Item, key=lambda i: i.name)

    items = [
        Item(id=1, value=10, name="user_alice"),
        Item(id=2, value=20, name="user_bob"),
        Item(id=3, value=30, name="admin_charlie"),
    ]
    for item in items:
        await provider.set(qs_builder.set(item.name, item))

    result = await provider.keys(qs_builder.keys("user_*"))
    key_results = result.unwrap()
    assert len(key_results) == 2
    assert set(key_results) == {"user_alice", "user_bob"}


# ══════════════════════════════════════════════════════════════════════════════
# Aggregation tests (async)
# ══════════════════════════════════════════════════════════════════════════════


def _make_agg_provider() -> MemoryRelationalProvider[Item]:
    """Create a provider with known data for aggregation tests."""
    items = [
        Item(id=1, value=10, name="a", active=True),
        Item(id=2, value=20, name="b", active=True),
        Item(id=3, value=30, name="c", active=False),
        Item(id=4, value=40, name="d", active=True),
        Item(id=5, value=50, name="e", active=False),
    ]
    return MemoryRelationalProvider(data=items)


@pytest.mark.asyncio
async def test_aggregate_count() -> None:
    """aggregate with Count() returns len(data)."""
    provider = _make_agg_provider()
    qs = relational(Item).aggregate(cnt=lambda u: u.count())

    result = await provider.aggregate(qs)

    assert result["cnt"] == 5


@pytest.mark.asyncio
async def test_aggregate_sum() -> None:
    """aggregate with Sum on numeric field."""
    provider = _make_agg_provider()
    qs = relational(Item).aggregate(total=lambda u: u.value.sum())

    result = await provider.aggregate(qs)

    assert result["total"] == 10 + 20 + 30 + 40 + 50


@pytest.mark.asyncio
async def test_aggregate_avg() -> None:
    """aggregate with Avg on numeric field."""
    provider = _make_agg_provider()
    qs = relational(Item).aggregate(avg_val=lambda u: u.value.avg())

    result = await provider.aggregate(qs)

    expected_avg = (10 + 20 + 30 + 40 + 50) / 5
    assert result["avg_val"] == expected_avg


@pytest.mark.asyncio
async def test_aggregate_min() -> None:
    """aggregate with Min on numeric field."""
    provider = _make_agg_provider()
    qs = relational(Item).aggregate(min_val=lambda u: u.value.min())

    result = await provider.aggregate(qs)

    assert result["min_val"] == 10


@pytest.mark.asyncio
async def test_aggregate_max() -> None:
    """aggregate with Max on numeric field."""
    provider = _make_agg_provider()
    qs = relational(Item).aggregate(max_val=lambda u: u.value.max())

    result = await provider.aggregate(qs)

    assert result["max_val"] == 50


@pytest.mark.asyncio
async def test_aggregate_multiple_specs() -> None:
    """Multiple aggregate specs in one call."""
    provider = _make_agg_provider()
    qs = relational(Item).aggregate(
        cnt=lambda u: u.count(),
        total=lambda u: u.value.sum(),
        avg_val=lambda u: u.value.avg(),
        min_val=lambda u: u.value.min(),
        max_val=lambda u: u.value.max(),
    )

    result = await provider.aggregate(qs)

    assert result["cnt"] == 5
    assert result["total"] == 150
    assert result["avg_val"] == 30.0
    assert result["min_val"] == 10
    assert result["max_val"] == 50


@pytest.mark.asyncio
async def test_aggregate_with_filter() -> None:
    """Aggregate respects preceding filter ops."""
    provider = _make_agg_provider()
    qs = (
        relational(Item)
        .filter(lambda u: u.active == True)  # noqa: E712
        .aggregate(
            cnt=lambda u: u.count(),
            total=lambda u: u.value.sum(),
        )
    )

    result = await provider.aggregate(qs)

    # Only active items: value 10, 20, 40
    assert result["cnt"] == 3
    assert result["total"] == 10 + 20 + 40


@pytest.mark.asyncio
async def test_aggregate_on_empty_data() -> None:
    """Aggregate on empty provider returns sensible defaults."""
    provider: MemoryRelationalProvider[Item] = MemoryRelationalProvider()
    qs = relational(Item).aggregate(
        cnt=lambda u: u.count(),
        total=lambda u: u.value.sum(),
        avg_val=lambda u: u.value.avg(),
        min_val=lambda u: u.value.min(),
        max_val=lambda u: u.value.max(),
    )

    result = await provider.aggregate(qs)

    assert result["cnt"] == 0
    # Sum/Avg/Min/Max on empty data returns None
    assert result["total"] is None
    assert result["avg_val"] is None
    assert result["min_val"] is None
    assert result["max_val"] is None


# ═══════════════════════════════════════════════════════════════════════════════
# BUG DETECTION: Select + Distinct crashes (dicts are unhashable)
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.xfail(
    reason="BUG: Distinct after Select crashes — Select returns dicts, "
    "Distinct._deduplicate tries to hash them, but dicts are unhashable",
    raises=TypeError,
    strict=True,
)
def test_select_then_distinct_crashes() -> None:
    """Select returns dicts, Distinct tries to hash them — TypeError."""
    data = [Item(id=1, value=10, name="a"), Item(id=1, value=10, name="a")]
    provider = MemoryRelationalProvider[Item](data=data)
    qs = RelationalQuerySet(
        entity=Item,
        ops=(Select(("id", "name")), Distinct()),
    )
    provider.execute(qs)


@pytest.mark.xfail(
    reason="BUG: Filter after Select crashes — Select returns dicts, "
    "Filter tries getattr on dicts which doesn't work as expected",
    raises=AttributeError,
    strict=True,
)
def test_select_then_filter_crashes() -> None:
    """Select returns dicts, Filter uses getattr — AttributeError."""
    data = [Item(id=1, value=10, name="a", active=True)]
    provider = MemoryRelationalProvider[Item](data=data)
    qs = RelationalQuerySet(
        entity=Item,
        ops=(Select(("id", "active")), Filter(Eq(Field("active"), Const(True)))),
    )
    provider.execute(qs)


# ═══════════════════════════════════════════════════════════════════════════════
# Stronger filter tests — nested expressions
# ═══════════════════════════════════════════════════════════════════════════════


@given(data=st_items, v1=st.integers(-100, 100), v2=st.integers(-100, 100))
def test_filter_and_equivalence_nested(
    data: list[Item], v1: int, v2: int
) -> None:
    """filter(And(Gt(x, v1), Lt(x, v2))) == filter(Gt(x,v1)).filter(Lt(x,v2)).

    Tests that nested And expressions behave identically to chained filters,
    even with contradictory bounds (v1 > v2 → empty result).
    """
    provider = MemoryRelationalProvider[Item](data=data)
    e1 = Gt(Field("value"), Const(v1))
    e2 = Lt(Field("value"), Const(v2))

    # Chained filters
    qs_chain = RelationalQuerySet(entity=Item, ops=(Filter(e1), Filter(e2)))
    # Single And filter
    qs_and = RelationalQuerySet(entity=Item, ops=(Filter(And(e1, e2)),))

    assert provider.execute(qs_chain) == provider.execute(qs_and)


@given(data=st_items, v=st.integers(-100, 100))
def test_filter_contradiction_gives_empty(data: list[Item], v: int) -> None:
    """filter(x > v AND x < v) always returns empty — no integer satisfies both."""
    provider = MemoryRelationalProvider[Item](data=data)
    expr = And(Gt(Field("value"), Const(v)), Lt(Field("value"), Const(v)))
    qs = RelationalQuerySet(entity=Item, ops=(Filter(expr),))
    assert provider.execute(qs) == []


@given(data=st.lists(st_item, min_size=1, max_size=50))
def test_filter_tautology_returns_all(data: list[Item]) -> None:
    """filter(x > -999 OR x <= -999) returns all items — tautology."""
    provider = MemoryRelationalProvider[Item](data=data)
    from emergent.wire.axis.query._expr import Or, Le
    tautology = Or(
        Gt(Field("value"), Const(-999)),
        Le(Field("value"), Const(-999)),
    )
    qs = RelationalQuerySet(entity=Item, ops=(Filter(tautology),))
    assert provider.execute(qs) == data

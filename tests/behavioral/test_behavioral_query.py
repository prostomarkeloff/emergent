"""Behavioral correctness tests for query execution.

Every assertion verifies that the returned DATA is correct — oracle is plain Python.
Uses hypothesis to generate random data and random queries.
"""

from __future__ import annotations

from dataclasses import dataclass

from hypothesis import given, settings, assume
import hypothesis.strategies as st

from emergent.wire.axis.query._relational import (
    RelationalQuerySet,
    Filter,
    OrderBy,
    Limit,
    Offset,
    Distinct,
    relational,
)
from emergent.wire.axis.query._expr import (
    Field,
    Const,
    Eq,
    Gt,
    Lt,
    Ge,
    Le,
    And,
    Or,
    Not,
    In,
    Contains,
    Between,
    Ne,
)
from emergent.wire.axis.query._proxy import OrderSpec
from emergent.wire.axis.query.providers.memory import MemoryRelationalProvider


# ─── Test Entity ──────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Item:
    id: int
    value: int
    name: str
    active: bool = True


NAMES = ["alice", "bob", "charlie", "dave"]

item_strategy = st.builds(
    Item,
    id=st.integers(0, 1000),
    value=st.integers(-50, 50),
    name=st.sampled_from(NAMES),
    active=st.booleans(),
)

items_strategy = st.lists(item_strategy, min_size=0, max_size=30)


def make_provider(data: list[Item]) -> MemoryRelationalProvider[Item]:
    return MemoryRelationalProvider[Item](data=list(data))


def qs() -> RelationalQuerySet[Item]:
    return relational(Item)


# ─── 1. Filter returns only matching items (Gt) ──────────────────────────────


@given(data=items_strategy, threshold=st.integers(-50, 50))
@settings(max_examples=100)
def test_filter_gt_returns_only_matching_items(
    data: list[Item], threshold: int
) -> None:
    provider = make_provider(data)
    expr = Gt(Field("value"), Const(threshold))
    result = provider.execute(qs().filter(lambda u: u.value > threshold))

    expected = [item for item in data if item.value > threshold]

    # Every returned item MUST have value > threshold
    for item in result:
        assert item.value > threshold, (
            f"Returned item {item} has value {item.value} <= {threshold}"
        )

    # Every item NOT returned MUST have value <= threshold
    result_ids = {id(item) for item in result}
    for item in data:
        if item.value > threshold:
            # must be in result
            assert item in result, (
                f"Item {item} with value > {threshold} was not returned"
            )

    # Count and content must match oracle
    assert result == expected


# ─── 2. Filter with Eq returns exact matches ─────────────────────────────────


@given(data=items_strategy)
@settings(max_examples=100)
def test_filter_eq_returns_exact_matches(data: list[Item]) -> None:
    assume(len(data) > 0)
    # Pick a name that actually exists in the data
    target_name = data[0].name

    provider = make_provider(data)
    result = provider.execute(qs().filter(lambda u: u.name == target_name))

    expected = [x for x in data if x.name == target_name]

    # Every returned item has that exact name
    for item in result:
        assert item.name == target_name, (
            f"Returned item {item} has name {item.name!r}, expected {target_name!r}"
        )

    assert result == expected


# ─── 3. Sort produces correctly ordered result (ascending) ───────────────────


@given(data=items_strategy)
@settings(max_examples=100)
def test_sort_ascending_produces_ordered_result(data: list[Item]) -> None:
    provider = make_provider(data)
    result = provider.execute(qs().order_by(lambda u: u.value.asc()))

    # result[i].value <= result[i+1].value for all i
    for i in range(len(result) - 1):
        assert result[i].value <= result[i + 1].value, (
            f"Not sorted ascending at index {i}: "
            f"{result[i].value} > {result[i + 1].value}"
        )

    # Same elements as input, just reordered
    assert sorted(result, key=lambda x: x.value) == result
    assert len(result) == len(data)


# ─── 4. Sort descending ──────────────────────────────────────────────────────


@given(data=items_strategy)
@settings(max_examples=100)
def test_sort_descending_produces_ordered_result(data: list[Item]) -> None:
    provider = make_provider(data)
    result = provider.execute(qs().order_by(lambda u: u.value.desc()))

    # result[i].value >= result[i+1].value for all i
    for i in range(len(result) - 1):
        assert result[i].value >= result[i + 1].value, (
            f"Not sorted descending at index {i}: "
            f"{result[i].value} < {result[i + 1].value}"
        )

    assert len(result) == len(data)


# ─── 5. Limit returns at most n items ─────────────────────────────────────────


@given(data=items_strategy, n=st.integers(0, 50))
@settings(max_examples=100)
def test_limit_returns_at_most_n_items(data: list[Item], n: int) -> None:
    provider = make_provider(data)
    result = provider.execute(qs().limit(n))

    assert len(result) == min(n, len(data)), (
        f"Expected {min(n, len(data))} items, got {len(result)}"
    )
    assert result == data[:n], (
        f"Limit result does not match first {n} items of data"
    )


# ─── 6. Offset skips first k items ───────────────────────────────────────────


@given(data=items_strategy, k=st.integers(0, 50))
@settings(max_examples=100)
def test_offset_skips_first_k_items(data: list[Item], k: int) -> None:
    provider = make_provider(data)
    result = provider.execute(qs().offset(k))

    expected = data[k:]
    assert result == expected, (
        f"Offset({k}) result does not match data[{k}:]"
    )


# ─── 7. Filter then Sort ─────────────────────────────────────────────────────


@given(data=items_strategy, threshold=st.integers(-50, 50))
@settings(max_examples=100)
def test_filter_then_sort(data: list[Item], threshold: int) -> None:
    provider = make_provider(data)
    result = provider.execute(
        qs()
        .filter(lambda u: u.value > threshold)
        .order_by(lambda u: u.value.asc())
    )

    # Every item has value > threshold
    for item in result:
        assert item.value > threshold

    # Result is sorted ascending
    for i in range(len(result) - 1):
        assert result[i].value <= result[i + 1].value

    # Matches oracle
    expected = sorted(
        [item for item in data if item.value > threshold],
        key=lambda x: x.value,
    )
    assert result == expected


# ─── 8. Filter commutativity ─────────────────────────────────────────────────


@given(data=items_strategy, threshold=st.integers(-50, 50))
@settings(max_examples=100)
def test_filter_commutativity(data: list[Item], threshold: int) -> None:
    provider = make_provider(data)

    # .filter(a).filter(b) in one order
    result_ab = provider.execute(
        qs()
        .filter(lambda u: u.value > threshold)
        .filter(lambda u: u.active == True)  # noqa: E712
    )

    # .filter(b).filter(a) in reverse order
    result_ba = provider.execute(
        qs()
        .filter(lambda u: u.active == True)  # noqa: E712
        .filter(lambda u: u.value > threshold)
    )

    # Python oracle
    expected = [item for item in data if item.value > threshold and item.active]

    assert result_ab == expected
    assert result_ba == expected
    assert result_ab == result_ba


# ─── 9. And equivalence ──────────────────────────────────────────────────────


@given(data=items_strategy, threshold=st.integers(-50, 50))
@settings(max_examples=100)
def test_and_equivalence(data: list[Item], threshold: int) -> None:
    provider = make_provider(data)

    # Two separate filters
    result_chained = provider.execute(
        qs()
        .filter(lambda u: u.value > threshold)
        .filter(lambda u: u.active == True)  # noqa: E712
    )

    # Single And expression
    result_and = provider.execute(
        qs().filter(lambda u: (u.value > threshold) & (u.active == True))  # noqa: E712
    )

    expected = [item for item in data if item.value > threshold and item.active]

    assert result_chained == expected
    assert result_and == expected
    assert result_chained == result_and


# ─── 10. Distinct removes duplicates ─────────────────────────────────────────


@given(data=items_strategy)
@settings(max_examples=100)
def test_distinct_removes_duplicates(data: list[Item]) -> None:
    # Intentionally add duplicates
    doubled = data + data
    provider = make_provider(doubled)
    result = provider.execute(qs().distinct())

    # No two items in result are equal (field-by-field)
    for i in range(len(result)):
        for j in range(i + 1, len(result)):
            assert result[i] != result[j], (
                f"Duplicate found at positions {i} and {j}: {result[i]}"
            )

    # All unique items from original data are present
    seen: set[tuple[int, int, str, bool]] = set()
    unique_expected: list[Item] = []
    for item in doubled:
        key = (item.id, item.value, item.name, item.active)
        if key not in seen:
            seen.add(key)
            unique_expected.append(item)

    assert result == unique_expected


# ─── 11. Limit + Offset = pagination ─────────────────────────────────────────


@given(
    data=items_strategy,
    offset_val=st.integers(0, 40),
    limit_val=st.integers(0, 40),
)
@settings(max_examples=100)
def test_limit_offset_pagination(
    data: list[Item], offset_val: int, limit_val: int
) -> None:
    provider = make_provider(data)
    result = provider.execute(qs().offset(offset_val).limit(limit_val))

    expected = data[offset_val : offset_val + limit_val]
    assert result == expected, (
        f"data[{offset_val}:{offset_val + limit_val}] != result"
    )


# ─── 12. Empty filter returns all ────────────────────────────────────────────


@given(data=items_strategy)
@settings(max_examples=100)
def test_empty_filter_returns_all(data: list[Item]) -> None:
    provider = make_provider(data)
    result = provider.execute(qs())

    assert result == data


# ─── 13. Filter with impossible condition returns empty ───────────────────────


@given(data=items_strategy)
@settings(max_examples=100)
def test_impossible_filter_returns_empty(data: list[Item]) -> None:
    # All values are in [-50, 50], so > 999999 is impossible
    provider = make_provider(data)
    result = provider.execute(
        qs().filter(lambda u: u.value > 999999)
    )

    assert result == []


# ─── 14. Or expression returns union of matches ──────────────────────────────


@given(data=items_strategy)
@settings(max_examples=100)
def test_or_expression_returns_union(data: list[Item]) -> None:
    provider = make_provider(data)
    result = provider.execute(
        qs().filter(lambda u: (u.name == "alice") | (u.name == "bob"))
    )

    expected = [item for item in data if item.name in ("alice", "bob")]
    assert result == expected

    for item in result:
        assert item.name in ("alice", "bob"), (
            f"Item {item} has name {item.name!r}, expected 'alice' or 'bob'"
        )


# ─── 15. Not negates a filter ────────────────────────────────────────────────


@given(data=items_strategy)
@settings(max_examples=100)
def test_not_negates_filter(data: list[Item]) -> None:
    provider = make_provider(data)
    result = provider.execute(
        qs().filter(lambda u: ~(u.active == True))  # noqa: E712
    )

    expected = [item for item in data if not item.active]
    assert result == expected

    for item in result:
        assert not item.active, (
            f"Item {item} has active=True but should have been filtered by Not"
        )


# ─── 16. Lt filter returns correct items ─────────────────────────────────────


@given(data=items_strategy, threshold=st.integers(-50, 50))
@settings(max_examples=100)
def test_filter_lt_returns_correct_items(
    data: list[Item], threshold: int
) -> None:
    provider = make_provider(data)
    result = provider.execute(
        qs().filter(lambda u: u.value < threshold)
    )

    expected = [item for item in data if item.value < threshold]
    assert result == expected

    for item in result:
        assert item.value < threshold


# ─── 17. Between filter is inclusive on both ends ─────────────────────────────


@given(
    data=items_strategy,
    low=st.integers(-50, 50),
    high=st.integers(-50, 50),
)
@settings(max_examples=100)
def test_between_filter_inclusive(
    data: list[Item], low: int, high: int
) -> None:
    assume(low <= high)
    provider = make_provider(data)
    result = provider.execute(
        qs().filter(lambda u: u.value.between(low, high))
    )

    expected = [item for item in data if low <= item.value <= high]
    assert result == expected

    for item in result:
        assert low <= item.value <= high, (
            f"Item value {item.value} not in [{low}, {high}]"
        )


# ─── 18. In filter matches membership ────────────────────────────────────────


@given(data=items_strategy, names=st.lists(st.sampled_from(NAMES), min_size=1, max_size=4))
@settings(max_examples=100)
def test_in_filter_matches_membership(
    data: list[Item], names: list[str]
) -> None:
    name_set = tuple(names)
    provider = make_provider(data)
    result = provider.execute(
        qs().filter(lambda u: u.name.in_(name_set))
    )

    expected = [item for item in data if item.name in name_set]
    assert result == expected

    for item in result:
        assert item.name in name_set


# ─── 19. Filter + Limit combination ──────────────────────────────────────────


@given(data=items_strategy, threshold=st.integers(-50, 50), n=st.integers(0, 30))
@settings(max_examples=100)
def test_filter_then_limit(data: list[Item], threshold: int, n: int) -> None:
    provider = make_provider(data)
    result = provider.execute(
        qs()
        .filter(lambda u: u.value > threshold)
        .limit(n)
    )

    filtered = [item for item in data if item.value > threshold]
    expected = filtered[:n]
    assert result == expected

    for item in result:
        assert item.value > threshold

    assert len(result) <= n


# ─── 20. Sort stability: equal values preserve insertion order ────────────────


@given(data=items_strategy)
@settings(max_examples=100)
def test_sort_stability(data: list[Item]) -> None:
    provider = make_provider(data)
    result = provider.execute(qs().order_by(lambda u: u.name.asc()))

    # Python's sort is stable, so items with the same name preserve order
    expected = sorted(data, key=lambda x: x.name)
    assert result == expected

    # Verify ordering
    for i in range(len(result) - 1):
        assert result[i].name <= result[i + 1].name


# ─── 21. Multiple sorts: last sort is primary ────────────────────────────────


@given(data=items_strategy)
@settings(max_examples=100)
def test_multiple_order_by(data: list[Item]) -> None:
    provider = make_provider(data)
    # Order by name asc, then by value desc within same name
    result = provider.execute(
        qs().order_by(lambda u: u.name.asc(), lambda u: u.value.desc())
    )

    # Oracle: sort by name asc, then value desc (stable)
    expected = sorted(data, key=lambda x: (x.name, -x.value))
    assert result == expected


# ─── 22. Ne filter (not equal) ────────────────────────────────────────────────


@given(data=items_strategy)
@settings(max_examples=100)
def test_ne_filter(data: list[Item]) -> None:
    assume(len(data) > 0)
    exclude_name = data[0].name

    provider = make_provider(data)
    result = provider.execute(
        qs().filter(lambda u: u.name != exclude_name)
    )

    expected = [item for item in data if item.name != exclude_name]
    assert result == expected

    for item in result:
        assert item.name != exclude_name


# ─── 23. Contains string filter ──────────────────────────────────────────────


@given(data=items_strategy, substring=st.sampled_from(["ali", "bob", "cha", "dav", "e", "z"]))
@settings(max_examples=100)
def test_contains_string_filter(data: list[Item], substring: str) -> None:
    provider = make_provider(data)
    result = provider.execute(
        qs().filter(lambda u: u.name.contains(substring))
    )

    expected = [item for item in data if substring in item.name]
    assert result == expected

    for item in result:
        assert substring in item.name


# ─── 24. Ge and Le filters ───────────────────────────────────────────────────


@given(data=items_strategy, threshold=st.integers(-50, 50))
@settings(max_examples=100)
def test_ge_le_filters(data: list[Item], threshold: int) -> None:
    provider = make_provider(data)

    result_ge = provider.execute(
        qs().filter(lambda u: u.value >= threshold)
    )
    expected_ge = [item for item in data if item.value >= threshold]
    assert result_ge == expected_ge

    result_le = provider.execute(
        qs().filter(lambda u: u.value <= threshold)
    )
    expected_le = [item for item in data if item.value <= threshold]
    assert result_le == expected_le


# ─── 25. Filter + Sort + Offset + Limit (full pipeline) ──────────────────────


@given(
    data=items_strategy,
    threshold=st.integers(-50, 50),
    offset_val=st.integers(0, 20),
    limit_val=st.integers(0, 20),
)
@settings(max_examples=100)
def test_full_pipeline(
    data: list[Item], threshold: int, offset_val: int, limit_val: int
) -> None:
    provider = make_provider(data)
    result = provider.execute(
        qs()
        .filter(lambda u: u.value > threshold)
        .order_by(lambda u: u.value.asc())
        .offset(offset_val)
        .limit(limit_val)
    )

    # Oracle: same pipeline in Python
    filtered = [item for item in data if item.value > threshold]
    sorted_items = sorted(filtered, key=lambda x: x.value)
    expected = sorted_items[offset_val : offset_val + limit_val]

    assert result == expected

    # Every returned item has value > threshold
    for item in result:
        assert item.value > threshold

    # Result is sorted
    for i in range(len(result) - 1):
        assert result[i].value <= result[i + 1].value

    assert len(result) <= limit_val

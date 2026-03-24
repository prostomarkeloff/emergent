# pyright: reportPrivateUsage=false
"""Property-based and deep unit tests for the query subsystem.

Targets uncovered lines in:
  _base_qs.py   — RelationalMixin chainable methods & introspection
  _fold.py      — fold_query, QueryDialect, memory handlers
  _store.py     — RelationalStore, KVStore, APIStore builders
  _api.py       — APIQuerySet builder pattern, mods, introspection
  _contexts.py  — QueryPhase, QueryCompiler, QueryCompilation, context types
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, cast

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

# ── Query subsystem imports ─────────────────────────────────────────────────

from emergent.wire.axis.query._relational import (
    Aggregate,
    Distinct,
    Filter,
    GroupBy,
    Having,
    Join,
    Limit,
    Offset,
    OrderBy,
    Select,
    RelationalQuerySet,
    relational,
)
from emergent.wire.axis.query._expr import (
    Eq,
    Field,
    Const,
    Gt,
    Expr,
)
from emergent.wire.axis.query._proxy import (
    OrderSpec,
)
from emergent.wire.axis.query._aggregate import (
    AggregateSpec,
    Count,
    Sum,
)
from emergent.wire.axis.query._fold import (
    MEMORY_DIALECT,
    MEMORY_HANDLERS,
    QueryDialect,
    fold_query,
)
from emergent.wire.axis.query._api import (
    APIQuerySet,
    ListOp,
    GetOp,
    CreateOp,
    UpdateOp,
    DeleteOp,
    PageMod,
    CursorMod,
    OffsetMod,
    SearchMod,
    IncludeMod,
    api,
)
from emergent.wire.axis.query._kv import (
    KVGet,
    KVSet,
    KVDelete,
    Exists,
    Scan,
    Keys,
    kv,
)
from emergent.wire.axis.query._store import (
    RelationalStore,
    BoundRelationalQuerySet,
    relational_store,
    KVStore,
    kv_store,
    APIStore,
    BoundAPIQuerySet,
    api_store,
)
from emergent.wire.axis.query._contexts import (
    MemoryQueryContext,
    MemoryAPIContext,
    MemoryKVContext,
    HTTPAPIContext,
    HTTPKVContext,
    MemoryQueryCompilable,
    MemoryAPICompilable,
    MemoryKVCompilable,
    HTTPKVCompilable,
    QueryPhase,
    QueryCompilation,
    QueryCompiler,
    MEMORY_RELATIONAL,
    MEMORY_API,
    MEMORY_KV,
    HTTP_API,
    HTTP_KV,
    SA_RELATIONAL,
    MEMORY_RELATIONAL_COMPILER,
    SA_COMPILER,
    MEMORY_API_COMPILER,
    HTTP_COMPILER,
    MEMORY_KV_COMPILER,
    HTTP_KV_COMPILER,
)


# ═════════════════════════════════════════════════════════════════════════════
# Fixtures / Entity Types
# ═════════════════════════════════════════════════════════════════════════════


@dataclass
class User:
    id: int
    name: str
    balance: float
    active: bool = True


@dataclass
class Post:
    id: int
    author_id: int
    title: str


@dataclass
class Item:
    id: int
    label: str


USERS = [
    User(1, "alice", 100.0, True),
    User(2, "bob", 50.0, False),
    User(3, "charlie", 200.0, True),
    User(4, "dave", 150.0, True),
    User(5, "eve", 75.0, False),
]


# ═════════════════════════════════════════════════════════════════════════════
# 1. _base_qs.py — RelationalMixin  (target 90%)
# ═════════════════════════════════════════════════════════════════════════════


class TestRelationalMixinFilter:
    """Filter / where via mixin."""

    def test_filter_creates_filter_op(self) -> None:
        q = relational(User).filter(lambda u: u.balance > 100)
        assert len(q.ops) == 1
        assert isinstance(q.ops[0], Filter)

    def test_where_is_alias_for_filter(self) -> None:
        q = relational(User).where(lambda u: u.name == "alice")
        assert len(q.ops) == 1
        assert isinstance(q.ops[0], Filter)

    def test_multiple_filters_chain(self) -> None:
        q = (
            relational(User)
            .filter(lambda u: u.balance > 0)
            .filter(lambda u: u.active == True)
            .filter(lambda u: u.name != "admin")
        )
        assert len(q.ops) == 3
        assert all(isinstance(op, Filter) for op in q.ops)


class TestRelationalMixinOrderBy:
    """Order-by via mixin."""

    def test_order_by_single_field(self) -> None:
        q = relational(User).order_by(lambda u: u.name)
        assert isinstance(q.ops[0], OrderBy)
        assert len(q.ops[0].specs) == 1
        assert q.ops[0].specs[0].ascending is True

    def test_order_by_desc(self) -> None:
        q = relational(User).order_by(lambda u: u.balance.desc())
        op = q.ops[0]
        assert isinstance(op, OrderBy)
        spec = op.specs[0]
        assert spec.field == "balance"
        assert spec.ascending is False

    def test_order_by_multiple_fields(self) -> None:
        q = relational(User).order_by(
            lambda u: u.name,
            lambda u: u.balance.desc(),
        )
        op = q.ops[0]
        assert isinstance(op, OrderBy)
        specs = op.specs
        assert len(specs) == 2
        assert specs[0] == OrderSpec("name", ascending=True)
        assert specs[1] == OrderSpec("balance", ascending=False)


class TestRelationalMixinPagination:
    """Limit / offset / paginate via mixin."""

    def test_limit(self) -> None:
        q = relational(User).limit(5)
        assert isinstance(q.ops[0], Limit)
        assert q.ops[0].count == 5

    def test_offset(self) -> None:
        q = relational(User).offset(10)
        assert isinstance(q.ops[0], Offset)
        assert q.ops[0].count == 10

    def test_paginate_page_2(self) -> None:
        q = relational(User).paginate(2, 25)
        assert isinstance(q.ops[0], Offset)
        assert q.ops[0].count == 25
        assert isinstance(q.ops[1], Limit)
        assert q.ops[1].count == 25

    @given(
        page=st.integers(min_value=1, max_value=1000),
        per_page=st.integers(min_value=1, max_value=1000),
    )
    @settings(max_examples=50)
    def test_paginate_property(self, page: int, per_page: int) -> None:
        q = relational(User).paginate(page, per_page)
        assert len(q.ops) == 2
        off = q.ops[0]
        lim = q.ops[1]
        assert isinstance(off, Offset)
        assert isinstance(lim, Limit)
        assert off.count == (page - 1) * per_page
        assert lim.count == per_page

    def test_paginate_page_0_raises(self) -> None:
        with pytest.raises(ValueError, match="page must be >= 1"):
            relational(User).paginate(0, 10)

    def test_paginate_per_page_0_raises(self) -> None:
        with pytest.raises(ValueError, match="per_page must be >= 1"):
            relational(User).paginate(1, 0)

    def test_paginate_negative_page_raises(self) -> None:
        with pytest.raises(ValueError, match="page must be >= 1"):
            relational(User).paginate(-5, 10)


class TestRelationalMixinProjection:
    """Select / distinct via mixin."""

    def test_select_single_field(self) -> None:
        q = relational(User).select(lambda u: u.name)
        assert isinstance(q.ops[0], Select)
        assert q.ops[0].fields == ("name",)

    def test_select_multiple_fields(self) -> None:
        q = relational(User).select(lambda u: u.id, lambda u: u.name, lambda u: u.balance)
        op = q.ops[0]
        assert isinstance(op, Select)
        assert op.fields == ("id", "name", "balance")

    def test_select_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="at least one field"):
            relational(User).select()

    def test_distinct(self) -> None:
        q = relational(User).distinct()
        assert isinstance(q.ops[0], Distinct)


class TestRelationalMixinSelectIsTerminal:
    """select() after other ops is fine; other ops after select() are not."""

    def test_filter_after_select_raises(self) -> None:
        q = relational(User).select(lambda u: u.name)
        with pytest.raises(TypeError, match="after .select"):
            q.filter(lambda u: u.name == "x")

    def test_order_by_after_select_raises(self) -> None:
        q = relational(User).select(lambda u: u.name)
        with pytest.raises(TypeError, match="after .select"):
            q.order_by(lambda u: u.name)

    def test_distinct_after_select_raises(self) -> None:
        q = relational(User).select(lambda u: u.name)
        with pytest.raises(TypeError, match="after .select"):
            q.distinct()

    def test_join_after_select_raises(self) -> None:
        q = relational(User).select(lambda u: u.name)
        with pytest.raises(TypeError, match="after .select"):
            q.join(Post, on=lambda u, p: u.id == p.author_id)

    def test_left_join_after_select_raises(self) -> None:
        q = relational(User).select(lambda u: u.name)
        with pytest.raises(TypeError, match="after .select"):
            q.left_join(Post, on=lambda u, p: u.id == p.author_id)

    def test_group_by_after_select_raises(self) -> None:
        q = relational(User).select(lambda u: u.name)
        with pytest.raises(TypeError, match="after .select"):
            q.group_by(lambda u: u.name)

    def test_having_after_select_raises(self) -> None:
        q = relational(User).select(lambda u: u.name)
        with pytest.raises(TypeError, match="after .select"):
            q.having(lambda u: u.balance > 0)

    def test_limit_after_select_allowed(self) -> None:
        q = relational(User).select(lambda u: u.name).limit(10)
        assert len(q.ops) == 2

    def test_offset_after_select_allowed(self) -> None:
        q = relational(User).select(lambda u: u.name).offset(5)
        assert len(q.ops) == 2


class TestRelationalMixinJoins:
    """Join / left_join via mixin."""

    def test_join(self) -> None:
        q = relational(User).join(Post, on=lambda u, p: u.id == p.author_id)
        op = q.ops[0]
        assert isinstance(op, Join)
        assert op.target is Post
        assert op.kind == "inner"
        assert op.tablename is None

    def test_left_join(self) -> None:
        q = relational(User).left_join(Post, on=lambda u, p: u.id == p.author_id)
        op = q.ops[0]
        assert isinstance(op, Join)
        assert op.kind == "left"

    def test_join_with_tablename(self) -> None:
        q = relational(User).join(
            Post, on=lambda u, p: u.id == p.author_id, tablename="posts"
        )
        op = q.ops[0]
        assert isinstance(op, Join)
        assert op.tablename == "posts"

    def test_left_join_with_tablename(self) -> None:
        q = relational(User).left_join(
            Post, on=lambda u, p: u.id == p.author_id, tablename="my_posts"
        )
        op = q.ops[0]
        assert isinstance(op, Join)
        assert op.tablename == "my_posts"


class TestRelationalMixinGroupBy:
    """Group-by / having / aggregate via mixin."""

    def test_group_by(self) -> None:
        q = relational(User).group_by(lambda u: u.name)
        assert isinstance(q.ops[0], GroupBy)
        assert q.ops[0].fields == ("name",)

    def test_group_by_multiple(self) -> None:
        q = relational(User).group_by(lambda u: u.name, lambda u: u.active)
        op = q.ops[0]
        assert isinstance(op, GroupBy)
        assert op.fields == ("name", "active")

    def test_group_by_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="at least one field"):
            relational(User).group_by()

    def test_having(self) -> None:
        q = relational(User).having(lambda u: u.balance > 100)
        assert isinstance(q.ops[0], Having)

    def test_aggregate_single(self) -> None:
        q = relational(User).aggregate(total=lambda u: u.balance.sum())
        assert isinstance(q.ops[0], Aggregate)
        specs = q.ops[0].specs
        assert len(specs) == 1
        assert specs[0].alias == "total"
        assert isinstance(specs[0].func, Sum)
        assert specs[0].field == "balance"

    def test_aggregate_multiple(self) -> None:
        q = relational(User).aggregate(
            total=lambda u: u.balance.sum(),
            avg_b=lambda u: u.balance.avg(),
            user_count=lambda u: u.count(),
        )
        op = q.ops[0]
        assert isinstance(op, Aggregate)
        specs = op.specs
        assert len(specs) == 3
        aliases = {s.alias for s in specs}
        assert aliases == {"total", "avg_b", "user_count"}

    def test_aggregate_count_star(self) -> None:
        q = relational(User).aggregate(cnt=lambda u: u.count())
        op = q.ops[0]
        assert isinstance(op, Aggregate)
        spec = op.specs[0]
        assert isinstance(spec.func, Count)
        assert spec.field is None  # COUNT(*)


class TestRelationalMixinIntrospection:
    """Introspection properties on RelationalMixin."""

    def test_filters_returns_exprs(self) -> None:
        q = (
            relational(User)
            .filter(lambda u: u.balance > 0)
            .filter(lambda u: u.name == "alice")
        )
        assert len(q.filters) == 2
        assert all(isinstance(f, Expr) for f in q.filters)

    def test_ordering_multi(self) -> None:
        q = relational(User).order_by(
            lambda u: u.name, lambda u: u.balance.desc()
        )
        ordering = q.ordering
        assert len(ordering) == 2
        assert ordering[0] == OrderSpec("name", ascending=True)
        assert ordering[1] == OrderSpec("balance", ascending=False)

    def test_ordering_from_multiple_order_by_ops(self) -> None:
        q = (
            relational(User)
            .order_by(lambda u: u.name)
            .order_by(lambda u: u.balance.desc())
        )
        ordering = q.ordering
        assert len(ordering) == 2

    def test_limit_value_present(self) -> None:
        assert relational(User).limit(42).limit_value == 42

    def test_limit_value_absent(self) -> None:
        assert relational(User).limit_value is None

    def test_offset_value_present(self) -> None:
        assert relational(User).offset(7).offset_value == 7

    def test_offset_value_absent(self) -> None:
        assert relational(User).offset_value is None

    def test_has_aggregates_false(self) -> None:
        assert relational(User).has_aggregates is False

    def test_has_aggregates_true(self) -> None:
        q = relational(User).aggregate(cnt=lambda u: u.count())
        assert q.has_aggregates is True

    def test_aggregates_empty(self) -> None:
        assert relational(User).aggregates == []

    def test_aggregates_populated(self) -> None:
        q = relational(User).aggregate(
            total=lambda u: u.balance.sum(),
            cnt=lambda u: u.count(),
        )
        aggs = q.aggregates
        assert len(aggs) == 2


class TestRelationalMixinImmutability:
    """Every method must return a new QuerySet, leaving original untouched."""

    @given(n=st.integers(min_value=0, max_value=100))
    @settings(max_examples=20)
    def test_limit_immutability(self, n: int) -> None:
        q0 = relational(User)
        q1 = q0.limit(n)
        assert q0.ops == ()
        assert len(q1.ops) == 1

    @given(n=st.integers(min_value=0, max_value=100))
    @settings(max_examples=20)
    def test_offset_immutability(self, n: int) -> None:
        q0 = relational(User)
        q1 = q0.offset(n)
        assert q0.ops == ()
        assert len(q1.ops) == 1

    def test_filter_immutability(self) -> None:
        q0 = relational(User)
        q1 = q0.filter(lambda u: u.balance > 0)
        assert q0.ops == ()
        assert len(q1.ops) == 1

    def test_order_by_immutability(self) -> None:
        q0 = relational(User)
        q0.order_by(lambda u: u.name)
        assert q0.ops == ()

    def test_chain_immutability(self) -> None:
        q0 = relational(User)
        q1 = q0.filter(lambda u: u.balance > 0)
        q2 = q1.order_by(lambda u: u.name)
        q3 = q2.limit(10)
        q4 = q3.offset(5)
        q5 = q4.distinct()
        assert q0.ops == ()
        assert len(q1.ops) == 1
        assert len(q2.ops) == 2
        assert len(q3.ops) == 3
        assert len(q4.ops) == 4
        assert len(q5.ops) == 5


# ═════════════════════════════════════════════════════════════════════════════
# 2. _fold.py — fold_query / QueryDialect / Memory handlers  (target 85%)
# ═════════════════════════════════════════════════════════════════════════════


class TestFoldQueryPrimitive:
    """Direct fold_query tests for uncovered paths."""

    def test_empty_ops_returns_initial(self) -> None:
        result = fold_query((), list(USERS), MEMORY_HANDLERS)
        assert len(result) == len(USERS)

    def test_filter_evaluates(self) -> None:
        ops = [Filter(Gt(Field("balance"), Const(100.0)))]
        result = fold_query(ops, list(USERS), MEMORY_HANDLERS)
        assert all(u.balance > 100 for u in result)

    def test_order_by_ascending(self) -> None:
        ops = [OrderBy((OrderSpec("name", ascending=True),))]
        result = fold_query(ops, list(USERS), MEMORY_HANDLERS)
        names = [u.name for u in result]
        assert names == sorted(names)

    def test_order_by_descending(self) -> None:
        ops = [OrderBy((OrderSpec("balance", ascending=False),))]
        result = fold_query(ops, list(USERS), MEMORY_HANDLERS)
        balances = [u.balance for u in result]
        assert balances == sorted(balances, reverse=True)

    def test_order_by_multi_key(self) -> None:
        data = [
            User(1, "a", 100.0, True),
            User(2, "a", 50.0, False),
            User(3, "b", 100.0, True),
        ]
        ops = [OrderBy((OrderSpec("name", True), OrderSpec("balance", False)))]
        result = fold_query(ops, data, MEMORY_HANDLERS)
        assert result[0].name == "a" and result[0].balance == 100.0
        assert result[1].name == "a" and result[1].balance == 50.0
        assert result[2].name == "b"

    def test_offset_slicing(self) -> None:
        ops = [Offset(3)]
        result = fold_query(ops, list(USERS), MEMORY_HANDLERS)
        assert len(result) == 2

    def test_limit_slicing(self) -> None:
        ops = [Limit(2)]
        result = fold_query(ops, list(USERS), MEMORY_HANDLERS)
        assert len(result) == 2

    def test_distinct_dataclass(self) -> None:
        data = list(USERS) + [User(1, "alice", 100.0, True)]
        ops = [Distinct()]
        result = fold_query(ops, data, MEMORY_HANDLERS)
        assert len(result) == len(USERS)

    def test_distinct_non_dataclass(self) -> None:
        data = [1, 2, 3, 2, 1, 4]
        ops = [Distinct()]
        result = fold_query(ops, data, MEMORY_HANDLERS)
        assert result == [1, 2, 3, 4]

    def test_select_produces_dicts(self) -> None:
        ops = [Select(("id", "name"))]
        result = fold_query(ops, list(USERS), MEMORY_HANDLERS)
        assert all(isinstance(r, dict) for r in result)
        for r in result:
            assert isinstance(r, dict)
            r_dict = cast(dict[str, object], r)
            assert set(r_dict.keys()) == {"id", "name"}

    def test_select_values_correct(self) -> None:
        ops = [Select(("name",))]
        result = fold_query(ops, [USERS[0]], MEMORY_HANDLERS)
        assert result == [{"name": "alice"}]

    def test_join_raises_unsupported(self) -> None:
        ops = [Join(Post, Eq(Field("id"), Field("author_id")), "inner", None)]
        with pytest.raises(TypeError, match="does not support Join"):
            fold_query(ops, list(USERS), MEMORY_HANDLERS)

    def test_group_by_raises_unsupported(self) -> None:
        ops = [GroupBy(("name",))]
        with pytest.raises(TypeError, match="does not support GroupBy"):
            fold_query(ops, list(USERS), MEMORY_HANDLERS)

    def test_having_raises_unsupported(self) -> None:
        ops = [Having(Gt(Field("balance"), Const(100.0)))]
        with pytest.raises(TypeError, match="does not support Having"):
            fold_query(ops, list(USERS), MEMORY_HANDLERS)

    def test_unknown_op_skipped(self) -> None:
        @dataclass(frozen=True)
        class Noop:
            pass

        ops = [Noop(), Limit(2)]
        result = fold_query(ops, list(USERS), MEMORY_HANDLERS)
        assert len(result) == 2


class TestQueryDialectDeep:
    """QueryDialect with_handler / without_handler / fold."""

    def test_fold_delegates(self) -> None:
        ops = [Limit(2)]
        result = MEMORY_DIALECT.fold(ops, list(USERS))
        assert len(result) == 2

    def test_with_handler_adds(self) -> None:
        @dataclass(frozen=True)
        class Tag:
            tag: str

        def handle(op: Tag, data: list[User]) -> list[User]:
            return data

        d = MEMORY_DIALECT.with_handler(Tag, handle)
        assert Tag in d.handlers

    def test_with_handler_replaces(self) -> None:
        """Replacing Filter handler changes behavior."""
        def noop_filter(op: Filter, data: list[object]) -> list[object]:
            return data

        d = MEMORY_DIALECT.with_handler(Filter, noop_filter)
        ops = [Filter(Gt(Field("balance"), Const(9999.0)))]
        result = d.fold(ops, list(USERS))
        assert len(result) == len(USERS)  # filter is now noop

    def test_without_handler_removes(self) -> None:
        d = MEMORY_DIALECT.without_handler(Filter)
        ops = [Filter(Gt(Field("balance"), Const(0.0)))]
        result = d.fold(ops, list(USERS))
        assert len(result) == len(USERS)  # filter skipped

    def test_without_handler_immutable(self) -> None:
        original_keys = set(MEMORY_DIALECT.handlers.keys())
        _ = MEMORY_DIALECT.without_handler(Filter)
        assert set(MEMORY_DIALECT.handlers.keys()) == original_keys

    def test_custom_context_type_dialect(self) -> None:
        def handle_filter(op: Filter, ctx: int) -> int:
            return ctx + 1

        d: QueryDialect[int] = QueryDialect(
            context_type=int,
            handlers={Filter: handle_filter},
        )
        ops = [Filter(Gt(Field("x"), Const(0))), Filter(Gt(Field("y"), Const(0)))]
        assert d.fold(ops, 0) == 2

    def test_aggregate_handler_passthrough(self) -> None:
        """Memory aggregate handler passes data through (handled by provider)."""
        specs = (AggregateSpec(Sum(), "balance", "total"),)
        ops = [Aggregate(specs)]
        result = fold_query(ops, list(USERS), MEMORY_HANDLERS)
        assert len(result) == len(USERS)


class TestFoldQueryProperty:
    """Property-based tests for fold_query."""

    @given(limit=st.integers(min_value=0, max_value=20))
    @settings(max_examples=30)
    def test_limit_never_exceeds(self, limit: int) -> None:
        ops = [Limit(limit)]
        result = fold_query(ops, list(USERS), MEMORY_HANDLERS)
        assert len(result) <= limit

    @given(offset=st.integers(min_value=0, max_value=20))
    @settings(max_examples=30)
    def test_offset_correct_count(self, offset: int) -> None:
        ops = [Offset(offset)]
        result = fold_query(ops, list(USERS), MEMORY_HANDLERS)
        assert len(result) == max(0, len(USERS) - offset)

    @given(
        limit=st.integers(min_value=0, max_value=10),
        offset=st.integers(min_value=0, max_value=10),
    )
    @settings(max_examples=30)
    def test_offset_then_limit(self, limit: int, offset: int) -> None:
        ops = [Offset(offset), Limit(limit)]
        result = fold_query(ops, list(USERS), MEMORY_HANDLERS)
        expected = USERS[offset:][:limit]
        assert len(result) == len(expected)


class TestFoldComplexPipeline:
    """Integration: complex pipelines through fold."""

    def test_filter_order_limit_offset_select(self) -> None:
        ops = [
            Filter(Gt(Field("balance"), Const(60.0))),
            OrderBy((OrderSpec("balance", ascending=True),)),
            Offset(1),
            Limit(2),
            Select(("name", "balance")),
        ]
        result = MEMORY_DIALECT.fold(ops, list(USERS))
        assert all(isinstance(r, dict) for r in result)
        assert len(result) == 2

    def test_distinct_then_filter(self) -> None:
        data = list(USERS) + [User(1, "alice", 100.0, True)]
        ops = [
            Distinct(),
            Filter(Gt(Field("balance"), Const(100.0))),
        ]
        result = MEMORY_DIALECT.fold(ops, data)
        assert all(u.balance > 100 for u in result)


# ═════════════════════════════════════════════════════════════════════════════
# 3. _store.py — Store builders and types  (target 80%)
# ═════════════════════════════════════════════════════════════════════════════


class TestRelationalStoreBuilder:
    """RelationalStore query building (no actual provider execution)."""

    def test_relational_store_entity(self) -> None:
        # Cannot execute without real provider, but can build
        class FakeProvider:
            pass

        store = RelationalStore(User, FakeProvider())  # type: ignore[arg-type]
        assert store.entity is User

    def test_relational_store_query_returns_bound(self) -> None:
        class FakeProvider:
            pass

        store = RelationalStore(User, FakeProvider())  # type: ignore[arg-type]
        bound = store.query()
        assert isinstance(bound, BoundRelationalQuerySet)
        assert bound.query.entity is User
        assert bound.query.ops == ()

    def test_relational_store_filter_builds_query(self) -> None:
        class FakeProvider:
            pass

        store = RelationalStore(User, FakeProvider())  # type: ignore[arg-type]
        bound = store.filter(lambda u: u.balance > 0)
        assert isinstance(bound, BoundRelationalQuerySet)
        assert len(bound.query.ops) == 1
        assert isinstance(bound.query.ops[0], Filter)

    def test_relational_store_where_builds_query(self) -> None:
        class FakeProvider:
            pass

        store = RelationalStore(User, FakeProvider())  # type: ignore[arg-type]
        bound = store.where(lambda u: u.balance > 0)
        assert isinstance(bound, BoundRelationalQuerySet)

    def test_relational_store_order_by(self) -> None:
        class FakeProvider:
            pass

        store = RelationalStore(User, FakeProvider())  # type: ignore[arg-type]
        bound = store.order_by(lambda u: u.name)
        assert isinstance(bound.query.ops[0], OrderBy)

    def test_relational_store_limit(self) -> None:
        class FakeProvider:
            pass

        store = RelationalStore(User, FakeProvider())  # type: ignore[arg-type]
        bound = store.limit(5)
        assert isinstance(bound.query.ops[0], Limit)

    def test_relational_store_select(self) -> None:
        class FakeProvider:
            pass

        store = RelationalStore(User, FakeProvider())  # type: ignore[arg-type]
        bound = store.select(lambda u: u.name)
        assert isinstance(bound.query.ops[0], Select)

    def test_relational_store_distinct(self) -> None:
        class FakeProvider:
            pass

        store = RelationalStore(User, FakeProvider())  # type: ignore[arg-type]
        bound = store.distinct()
        assert isinstance(bound.query.ops[0], Distinct)

    def test_relational_store_all(self) -> None:
        class FakeProvider:
            pass

        store = RelationalStore(User, FakeProvider())  # type: ignore[arg-type]
        bound = store.all()
        assert bound.query.ops == ()

    def test_relational_store_factory(self) -> None:
        class FakeProvider:
            pass

        store = relational_store(User, FakeProvider())  # type: ignore[arg-type]
        assert isinstance(store, RelationalStore)
        assert store.entity is User


class TestBoundRelationalQuerySetChaining:
    """BoundRelationalQuerySet chainable operations."""

    def _make_bound(self) -> BoundRelationalQuerySet[User]:
        class FakeProvider:
            pass

        store = RelationalStore(User, FakeProvider())  # type: ignore[arg-type]
        return store.query()

    def test_filter_chain(self) -> None:
        bound = self._make_bound().filter(lambda u: u.balance > 0)
        assert len(bound.query.ops) == 1

    def test_where_chain(self) -> None:
        bound = self._make_bound().where(lambda u: u.balance > 0)
        assert len(bound.query.ops) == 1

    def test_order_by_chain(self) -> None:
        bound = self._make_bound().order_by(lambda u: u.name)
        assert len(bound.query.ops) == 1

    def test_limit_chain(self) -> None:
        bound = self._make_bound().limit(10)
        assert len(bound.query.ops) == 1

    def test_offset_chain(self) -> None:
        bound = self._make_bound().offset(5)
        assert len(bound.query.ops) == 1

    def test_paginate_chain(self) -> None:
        bound = self._make_bound().paginate(2, 10)
        assert len(bound.query.ops) == 2

    def test_select_chain(self) -> None:
        bound = self._make_bound().select(lambda u: u.name)
        assert len(bound.query.ops) == 1

    def test_distinct_chain(self) -> None:
        bound = self._make_bound().distinct()
        assert len(bound.query.ops) == 1

    def test_join_chain(self) -> None:
        bound = self._make_bound().join(Post, on=lambda u, p: u.id == p.author_id)
        op = bound.query.ops[0]
        assert isinstance(op, Join)

    def test_left_join_chain(self) -> None:
        bound = self._make_bound().left_join(Post, on=lambda u, p: u.id == p.author_id)
        op = bound.query.ops[0]
        assert isinstance(op, Join) and op.kind == "left"

    def test_group_by_chain(self) -> None:
        bound = self._make_bound().group_by(lambda u: u.name)
        assert isinstance(bound.query.ops[0], GroupBy)

    def test_having_chain(self) -> None:
        bound = self._make_bound().having(lambda u: u.balance > 0)
        assert isinstance(bound.query.ops[0], Having)

    def test_aggregate_chain(self) -> None:
        bound = self._make_bound().aggregate(cnt=lambda u: u.count())
        assert isinstance(bound.query.ops[0], Aggregate)

    def test_complex_chain(self) -> None:
        bound = (
            self._make_bound()
            .filter(lambda u: u.balance > 0)
            .order_by(lambda u: u.name)
            .limit(10)
            .offset(5)
        )
        assert len(bound.query.ops) == 4


class TestKVStoreBuilder:
    """KV store builder + query building."""

    def test_kv_store_entity(self) -> None:
        class FakeKVProvider:
            pass

        store = KVStore(User, lambda u: u.id, FakeKVProvider())  # type: ignore[arg-type]
        assert store.entity is User

    def test_kv_store_factory(self) -> None:
        class FakeKVProvider:
            pass

        store = kv_store(User, lambda u: u.id, FakeKVProvider())  # type: ignore[arg-type]
        assert isinstance(store, KVStore)

    def test_kv_queryset_ops(self) -> None:
        q = kv(User, key=lambda u: u.id)
        assert q.ops == ()
        g = q.get(1)
        assert len(g.ops) == 1
        assert isinstance(g.op, KVGet)

    def test_kv_queryset_set(self) -> None:
        q = kv(User, key=lambda u: u.id).set(1, User(1, "a", 0.0))
        assert isinstance(q.op, KVSet)

    def test_kv_queryset_delete(self) -> None:
        q = kv(User, key=lambda u: u.id).delete(1)
        assert isinstance(q.op, KVDelete)

    def test_kv_queryset_exists(self) -> None:
        q = kv(User, key=lambda u: u.id).exists(1)
        assert isinstance(q.op, Exists)

    def test_kv_queryset_scan(self) -> None:
        q = kv(User, key=lambda u: u.id).scan("user:*")
        assert isinstance(q.op, Scan)

    def test_kv_queryset_keys(self) -> None:
        q = kv(User, key=lambda u: u.id).keys("user:*")
        assert isinstance(q.op, Keys)

    def test_kv_queryset_put(self) -> None:
        u = User(42, "test", 0.0)
        q = kv(User, key=lambda u: u.id).put(u)
        assert isinstance(q.op, KVSet)
        assert q.op.key == 42


class TestAPIStoreBuilder:
    """API store builder + query building."""

    def test_api_store_entity(self) -> None:
        class FakeAPIProvider:
            pass

        store = APIStore(User, FakeAPIProvider(), lambda u: u.id)  # type: ignore[arg-type]
        assert store.entity is User

    def test_api_store_factory(self) -> None:
        class FakeAPIProvider:
            pass

        store = api_store(User, FakeAPIProvider(), key=lambda u: u.id)  # type: ignore[arg-type]
        assert isinstance(store, APIStore)

    def test_api_store_list_returns_bound(self) -> None:
        class FakeAPIProvider:
            pass

        store = api_store(User, FakeAPIProvider(), key=lambda u: u.id)  # type: ignore[arg-type]
        bound = store.list()
        assert isinstance(bound, BoundAPIQuerySet)
        assert isinstance(bound.query.op, ListOp)

    def test_bound_api_filter(self) -> None:
        class FakeAPIProvider:
            pass

        store = api_store(User, FakeAPIProvider(), key=lambda u: u.id)  # type: ignore[arg-type]
        bound = store.list().filter(lambda u: u.active == True)
        assert len(bound.query.mods) == 1
        assert isinstance(bound.query.mods[0], Filter)

    def test_bound_api_order_by(self) -> None:
        class FakeAPIProvider:
            pass

        store = api_store(User, FakeAPIProvider(), key=lambda u: u.id)  # type: ignore[arg-type]
        bound = store.list().order_by(lambda u: u.name)
        assert len(bound.query.mods) == 1

    def test_bound_api_page(self) -> None:
        class FakeAPIProvider:
            pass

        store = api_store(User, FakeAPIProvider(), key=lambda u: u.id)  # type: ignore[arg-type]
        bound = store.list().page(2, 10)
        assert isinstance(bound.query.pagination, PageMod)

    def test_bound_api_offset(self) -> None:
        class FakeAPIProvider:
            pass

        store = api_store(User, FakeAPIProvider(), key=lambda u: u.id)  # type: ignore[arg-type]
        bound = store.list().offset(10, 20)
        assert isinstance(bound.query.pagination, OffsetMod)

    def test_bound_api_search(self) -> None:
        class FakeAPIProvider:
            pass

        store = api_store(User, FakeAPIProvider(), key=lambda u: u.id)  # type: ignore[arg-type]
        bound = store.list().search("alice")
        assert isinstance(bound.query.mods[-1], SearchMod)


# ═════════════════════════════════════════════════════════════════════════════
# 4. _api.py — APIQuerySet builder pattern  (target 85%)
# ═════════════════════════════════════════════════════════════════════════════


class TestAPIQuerySetOps:
    """CRUD operations on APIQuerySet."""

    def test_list(self) -> None:
        q = api(User, key=lambda u: u.id).list()
        assert isinstance(q.op, ListOp)

    def test_get(self) -> None:
        q = api(User, key=lambda u: u.id).get(42)
        assert isinstance(q.op, GetOp)
        assert q.op.id == 42

    def test_create(self) -> None:
        u = User(1, "alice", 100.0)
        q = api(User, key=lambda u: u.id).create(u)
        assert isinstance(q.op, CreateOp)
        assert q.op.entity is u

    def test_update(self) -> None:
        u = User(1, "alice", 200.0)
        q = api(User, key=lambda u: u.id).update(1, u)
        assert isinstance(q.op, UpdateOp)
        assert q.op.id == 1
        assert q.op.partial is False

    def test_update_partial(self) -> None:
        u = User(1, "alice", 200.0)
        q = api(User, key=lambda u: u.id).update(1, u, partial=True)
        assert isinstance(q.op, UpdateOp)
        assert q.op.partial is True

    def test_delete(self) -> None:
        q = api(User, key=lambda u: u.id).delete(1)
        assert isinstance(q.op, DeleteOp)
        assert q.op.id == 1


class TestAPIQuerySetMods:
    """Modifier methods on APIQuerySet."""

    def test_filter(self) -> None:
        q = cast(APIQuerySet[Any, User], api(User).list().filter(lambda u: u.active == True))
        assert len(q.mods) == 1
        assert isinstance(q.mods[0], Filter)

    def test_order_by(self) -> None:
        q = cast(APIQuerySet[Any, User], api(User).list().order_by(lambda u: u.name.asc()))
        assert len(q.mods) == 1
        assert isinstance(q.mods[0], OrderBy)

    def test_page(self) -> None:
        q = cast(APIQuerySet[Any, User], api(User).list().page(2, 50))
        assert isinstance(q.pagination, PageMod)
        assert q.pagination.page == 2
        assert q.pagination.per_page == 50

    def test_cursor(self) -> None:
        q = cast(APIQuerySet[Any, User], api(User).list().cursor("abc123", limit=30))
        assert isinstance(q.pagination, CursorMod)
        assert q.pagination.cursor == "abc123"
        assert q.pagination.limit == 30

    def test_offset(self) -> None:
        q = cast(APIQuerySet[Any, User], api(User).list().offset(100, limit=50))
        assert isinstance(q.pagination, OffsetMod)
        assert q.pagination.offset == 100
        assert q.pagination.limit == 50

    def test_select(self) -> None:
        q = cast(APIQuerySet[Any, User], api(User).list().select(lambda u: u.id, lambda u: u.name))
        assert len(q.mods) == 1
        assert isinstance(q.mods[0], Select)
        assert q.mods[0].fields == ("id", "name")

    def test_search(self) -> None:
        q = cast(APIQuerySet[Any, User], api(User).list().search("alice"))
        assert len(q.mods) == 1
        assert isinstance(q.mods[0], SearchMod)
        assert q.mods[0].query == "alice"

    def test_include(self) -> None:
        q = cast(APIQuerySet[Any, User], api(User).list().include("posts", "comments"))
        assert len(q.mods) == 1
        assert isinstance(q.mods[0], IncludeMod)
        assert q.mods[0].relations == ("posts", "comments")


class TestAPIQuerySetPaginationLastWins:
    """Pagination is last-wins: new pagination replaces old."""

    def test_page_replaces_page(self) -> None:
        q = cast(APIQuerySet[Any, User], api(User).list().page(1).page(2))
        assert isinstance(q.pagination, PageMod)
        assert q.pagination.page == 2
        # Only one pagination mod
        pag_mods = [m for m in q.mods if isinstance(m, (PageMod, CursorMod, OffsetMod))]
        assert len(pag_mods) == 1

    def test_cursor_replaces_page(self) -> None:
        q = cast(APIQuerySet[Any, User], api(User).list().page(1).cursor("abc"))
        assert isinstance(q.pagination, CursorMod)

    def test_offset_replaces_cursor(self) -> None:
        q = cast(APIQuerySet[Any, User], api(User).list().cursor("abc").offset(10))
        assert isinstance(q.pagination, OffsetMod)

    def test_page_replaces_offset(self) -> None:
        q = cast(APIQuerySet[Any, User], api(User).list().offset(10).page(3))
        assert isinstance(q.pagination, PageMod)
        assert q.pagination.page == 3


class TestAPIQuerySetImmutability:
    """Each method returns new APIQuerySet, original unchanged."""

    def test_list_immutability(self) -> None:
        q0 = cast(APIQuerySet[Any, User], api(User))
        q1 = q0.list()
        assert q0.op is None
        assert q1.op is not None

    def test_filter_immutability(self) -> None:
        q0 = cast(APIQuerySet[Any, User], api(User).list())
        q1 = q0.filter(lambda u: u.active == True)
        assert q0.mods == ()
        assert len(q1.mods) == 1

    def test_page_immutability(self) -> None:
        q0 = cast(APIQuerySet[Any, User], api(User).list())
        q1 = q0.page(1)
        assert q0.mods == ()
        assert len(q1.mods) == 1

    def test_search_immutability(self) -> None:
        q0 = cast(APIQuerySet[Any, User], api(User).list())
        q1 = q0.search("test")
        assert q0.mods == ()
        assert len(q1.mods) == 1

    def test_include_immutability(self) -> None:
        q0 = cast(APIQuerySet[Any, User], api(User).list())
        q1 = q0.include("posts")
        assert q0.mods == ()
        assert len(q1.mods) == 1


class TestAPIQuerySetIntrospection:
    """Introspection properties on APIQuerySet."""

    def test_filters_property(self) -> None:
        q = cast(APIQuerySet[Any, User], api(User)
            .list()
            .filter(lambda u: u.active == True)
            .filter(lambda u: u.balance > 0)
        )
        assert len(q.filters) == 2

    def test_ordering_property(self) -> None:
        q = cast(APIQuerySet[Any, User], api(User).list().order_by(lambda u: u.name, lambda u: u.balance.desc()))
        assert len(q.ordering) == 2
        assert q.ordering[0] == OrderSpec("name", ascending=True)
        assert q.ordering[1] == OrderSpec("balance", ascending=False)

    def test_pagination_none(self) -> None:
        q = cast(APIQuerySet[Any, User], api(User).list())
        assert q.pagination is None

    def test_ops_uniform_access(self) -> None:
        q = cast(APIQuerySet[Any, User], api(User).list().filter(lambda u: u.active == True).page(1))
        assert q.ops == q.mods
        assert len(q.ops) == 2

    def test_no_key_fn(self) -> None:
        q = cast(APIQuerySet[Any, User], api(User).list())
        assert q.key_fn is None


class TestAPIQuerySetComplexChain:
    """Complex chaining of APIQuerySet methods."""

    def test_list_filter_order_page_search_include(self) -> None:
        q = (
            api(User, key=lambda u: u.id)
            .list()
            .filter(lambda u: u.active == True)
            .order_by(lambda u: u.name)
            .page(1, per_page=20)
            .search("alice")
            .include("posts")
            .select(lambda u: u.id, lambda u: u.name)
        )
        assert isinstance(q.op, ListOp)
        assert len(q.mods) == 6
        assert isinstance(q.pagination, PageMod)
        assert len(q.filters) == 1
        assert len(q.ordering) == 1


# ═════════════════════════════════════════════════════════════════════════════
# 5. _contexts.py — QueryPhase, QueryCompiler, Compilation  (target 85%)
# ═════════════════════════════════════════════════════════════════════════════


class TestMemoryQueryContext:
    """MemoryQueryContext construction and basic use."""

    def test_construction(self) -> None:
        ctx = MemoryQueryContext(data=list(USERS))
        assert len(ctx.data) == 5

    def test_frozen(self) -> None:
        ctx = MemoryQueryContext(data=[])
        with pytest.raises(AttributeError):
            ctx.data = [1]  # type: ignore[misc]


class TestMemoryAPIContext:
    """MemoryAPIContext construction and defaults."""

    def test_defaults(self) -> None:
        ctx = MemoryAPIContext(data=[])
        assert ctx.total is None
        assert ctx.has_more is False

    def test_replace(self) -> None:
        ctx = MemoryAPIContext(data=[1, 2, 3])
        ctx2 = replace(ctx, data=[1], total=3, has_more=True)
        assert ctx2.total == 3
        assert ctx2.has_more is True
        assert len(ctx2.data) == 1


class TestMemoryKVContext:
    """MemoryKVContext mutable accumulator."""

    def test_construction(self) -> None:
        ctx = MemoryKVContext(store={})
        assert ctx.result is None

    def test_mutation(self) -> None:
        ctx = MemoryKVContext(store={"a": 1})
        ctx.result = 1
        assert ctx.result == 1


class TestHTTPAPIContext:
    """HTTPAPIContext construction."""

    def test_construction(self) -> None:
        ctx = HTTPAPIContext(
            params={},
            body=None,
            encode_filter=lambda e: {},
            apply_pagination=lambda p, m: None,
            is_body_filter=False,
        )
        assert ctx.params == {}
        assert ctx.body is None

    def test_optional_closures(self) -> None:
        ctx = HTTPAPIContext(
            params={},
            body=None,
            encode_filter=lambda e: {},
            apply_pagination=lambda p, m: None,
            is_body_filter=False,
            encode_order=None,
            encode_limit=None,
            encode_select=None,
        )
        assert ctx.encode_order is None


class TestHTTPKVContext:
    """HTTPKVContext defaults."""

    def test_defaults(self) -> None:
        ctx = HTTPKVContext()
        assert ctx.method == "GET"
        assert ctx.path == ""
        assert ctx.params is None
        assert ctx.body is None

    def test_encode_key_default(self) -> None:
        ctx = HTTPKVContext()
        assert ctx.encode_key("abc") == "abc"

    def test_encode_pattern_default(self) -> None:
        ctx = HTTPKVContext()
        assert ctx.encode_pattern("foo*") == {"pattern": "foo*"}

    def test_encode_value_default(self) -> None:
        ctx = HTTPKVContext()
        assert ctx.encode_value("hello", None) == {"value": "hello"}
        assert ctx.encode_value("hello", 60) == {"value": "hello", "ttl": 60}


class TestProtocolRuntimeCheckable:
    """Protocols are runtime_checkable — isinstance works."""

    def test_memory_query_compilable(self) -> None:
        f = Filter(Gt(Field("x"), Const(0)))
        assert isinstance(f, MemoryQueryCompilable)

    def test_memory_api_compilable(self) -> None:
        f = Filter(Gt(Field("x"), Const(0)))
        assert isinstance(f, MemoryAPICompilable)

    def test_memory_kv_compilable(self) -> None:
        op = KVGet("key")
        assert isinstance(op, MemoryKVCompilable)

    def test_http_kv_compilable(self) -> None:
        op = KVGet("key")
        assert isinstance(op, HTTPKVCompilable)


class TestQueryPhase:
    """QueryPhase — reified fold spec."""

    def test_construction(self) -> None:
        phase = MEMORY_RELATIONAL
        assert phase.protocol is MemoryQueryCompilable
        assert phase.method == "compile_memory_query"

    def test_fold_applies_ops(self) -> None:
        ctx = MemoryQueryContext(data=list(USERS))
        ops = [Filter(Gt(Field("balance"), Const(100.0)))]
        result = MEMORY_RELATIONAL.fold(ops, ctx)
        assert len(result.data) < len(USERS)

    def test_fold_empty_ops(self) -> None:
        ctx = MemoryQueryContext(data=list(USERS))
        result = MEMORY_RELATIONAL.fold([], ctx)
        assert len(result.data) == len(USERS)

    def test_with_handler(self) -> None:
        @dataclass(frozen=True)
        class Noop:
            pass

        def handle(op: Noop, ctx: MemoryQueryContext) -> MemoryQueryContext:
            return replace(ctx, data=[])

        phase = MEMORY_RELATIONAL.with_handler(Noop, handle)
        result = phase.fold([Noop()], MemoryQueryContext(data=list(USERS)))
        assert result.data == []

    def test_without_handler(self) -> None:
        @dataclass(frozen=True)
        class Noop:
            pass

        def handle(op: Noop, ctx: MemoryQueryContext) -> MemoryQueryContext:
            return replace(ctx, data=[])

        phase = MEMORY_RELATIONAL.with_handler(Noop, handle)
        phase2 = phase.without_handler(Noop)
        result = phase2.fold([Noop()], MemoryQueryContext(data=list(USERS)))
        # Noop handler removed, op skipped (open-world)
        assert len(result.data) == len(USERS)

    def test_without_handler_no_handlers(self) -> None:
        phase: QueryPhase[MemoryQueryContext] = QueryPhase(protocol=MemoryQueryCompilable, method="compile_memory_query", handlers=None)
        phase2 = phase.without_handler(Filter)
        assert phase2 is phase  # no change when handlers is None


class TestQueryCompilation:
    """QueryCompilation — typed result access."""

    def test_getitem(self) -> None:
        ctx = MemoryQueryContext(data=[1, 2])
        comp = QueryCompilation({MemoryQueryCompilable: ctx})
        assert comp[MEMORY_RELATIONAL] is ctx

    def test_getitem_missing_raises(self) -> None:
        comp = QueryCompilation({})
        with pytest.raises(KeyError):
            comp[MEMORY_RELATIONAL]

    def test_get_present(self) -> None:
        ctx = MemoryQueryContext(data=[])
        comp = QueryCompilation({MemoryQueryCompilable: ctx})
        assert comp.get(MEMORY_RELATIONAL) is ctx

    def test_get_missing(self) -> None:
        comp = QueryCompilation({})
        assert comp.get(MEMORY_RELATIONAL) is None

    def test_contains(self) -> None:
        ctx = MemoryQueryContext(data=[])
        comp = QueryCompilation({MemoryQueryCompilable: ctx})
        assert MEMORY_RELATIONAL in comp
        assert HTTP_API not in comp


class TestQueryCompiler:
    """QueryCompiler — composable multi-phase compiler."""

    def test_with_phase(self) -> None:
        compiler = QueryCompiler(phases=())
        compiler = compiler.with_phase(MEMORY_RELATIONAL)
        assert len(compiler) == 1

    def test_with_phase_duplicate_raises(self) -> None:
        compiler = QueryCompiler(phases=(MEMORY_RELATIONAL,))
        with pytest.raises(ValueError, match="already present"):
            compiler.with_phase(MEMORY_RELATIONAL)

    def test_without_phase_by_phase(self) -> None:
        compiler = QueryCompiler(phases=(MEMORY_RELATIONAL, MEMORY_API))
        compiler = compiler.without_phase(MEMORY_RELATIONAL)
        assert len(compiler) == 1

    def test_without_phase_by_protocol(self) -> None:
        compiler = QueryCompiler(phases=(MEMORY_RELATIONAL,))
        compiler = compiler.without_phase(MemoryQueryCompilable)
        assert len(compiler) == 0

    def test_add_left_biased(self) -> None:
        a = QueryCompiler(phases=(MEMORY_RELATIONAL,))
        b = QueryCompiler(phases=(MEMORY_API,))
        c = a + b
        assert len(c) == 2

    def test_add_idempotent(self) -> None:
        a = QueryCompiler(phases=(MEMORY_RELATIONAL,))
        c = a + a
        assert len(c) == 1

    def test_add_with_single_phase(self) -> None:
        a = QueryCompiler(phases=(MEMORY_RELATIONAL,))
        c = a + MEMORY_API
        assert len(c) == 2

    def test_radd_with_phase(self) -> None:
        a = QueryCompiler(phases=(MEMORY_RELATIONAL,))
        c = MEMORY_API + a
        assert len(c) == 2

    def test_or_right_biased(self) -> None:
        custom_phase: QueryPhase[MemoryQueryContext] = QueryPhase(
            protocol=MemoryQueryCompilable,
            method="compile_memory_query",
            handlers={Filter: lambda op, ctx: ctx},
        )
        a = QueryCompiler(phases=(MEMORY_RELATIONAL,))
        b = QueryCompiler(phases=(custom_phase,))
        c = a | b
        assert len(c) == 1
        # Right side wins
        assert c.phases[0] is custom_phase

    def test_or_with_single_phase(self) -> None:
        a = QueryCompiler(phases=(MEMORY_RELATIONAL,))
        custom: QueryPhase[MemoryQueryContext] = QueryPhase(
            protocol=MemoryQueryCompilable,
            method="compile_memory_query",
            handlers={Filter: lambda op, ctx: ctx},
        )
        c = a | custom
        assert c.phases[0] is custom

    def test_ror_with_phase(self) -> None:
        a = QueryCompiler(phases=(MEMORY_RELATIONAL,))
        c = MEMORY_API | a
        assert len(c) == 2

    def test_or_adds_new_protocols(self) -> None:
        a = QueryCompiler(phases=(MEMORY_RELATIONAL,))
        b = QueryCompiler(phases=(MEMORY_API,))
        c = a | b
        assert len(c) == 2

    def test_sub_by_compiler(self) -> None:
        a = QueryCompiler(phases=(MEMORY_RELATIONAL, MEMORY_API))
        b = QueryCompiler(phases=(MEMORY_API,))
        c = a - b
        assert len(c) == 1

    def test_sub_by_phase(self) -> None:
        a = QueryCompiler(phases=(MEMORY_RELATIONAL, MEMORY_API))
        c = a - MEMORY_API
        assert len(c) == 1

    def test_sub_by_protocol_type(self) -> None:
        a = QueryCompiler(phases=(MEMORY_RELATIONAL, MEMORY_API))
        c = a - MemoryAPICompilable
        assert len(c) == 1

    def test_and_intersection(self) -> None:
        a = QueryCompiler(phases=(MEMORY_RELATIONAL, MEMORY_API))
        b = QueryCompiler(phases=(MEMORY_API, HTTP_API))
        c = a & b
        assert len(c) == 1

    def test_contains_phase(self) -> None:
        compiler = MEMORY_RELATIONAL_COMPILER
        assert MEMORY_RELATIONAL in compiler
        assert MEMORY_API not in compiler

    def test_contains_protocol(self) -> None:
        compiler = MEMORY_RELATIONAL_COMPILER
        assert MemoryQueryCompilable in compiler

    def test_len(self) -> None:
        assert len(MEMORY_RELATIONAL_COMPILER) == 1
        assert len(QueryCompiler(phases=())) == 0

    def test_iter(self) -> None:
        phases = list(MEMORY_RELATIONAL_COMPILER)
        assert len(phases) == 1
        assert phases[0] is MEMORY_RELATIONAL

    def test_bool(self) -> None:
        assert bool(MEMORY_RELATIONAL_COMPILER)
        assert not bool(QueryCompiler(phases=()))

    def test_getitem(self) -> None:
        phase = MEMORY_RELATIONAL_COMPILER[MemoryQueryCompilable]
        assert phase is MEMORY_RELATIONAL

    def test_getitem_missing_raises(self) -> None:
        with pytest.raises(KeyError):
            MEMORY_RELATIONAL_COMPILER[MemoryAPICompilable]


class TestQueryCompilerCompile:
    """QueryCompiler.compile() integration."""

    def test_compile_single_phase(self) -> None:
        ctx = MemoryQueryContext(data=list(USERS))
        ops = [Filter(Gt(Field("balance"), Const(100.0)))]
        result = MEMORY_RELATIONAL_COMPILER.compile(
            ops, {MemoryQueryCompilable: ctx}
        )
        out = result[MEMORY_RELATIONAL]
        assert len(out.data) < len(USERS)

    def test_compile_empty_ops(self) -> None:
        ctx = MemoryQueryContext(data=list(USERS))
        result = MEMORY_RELATIONAL_COMPILER.compile([], {MemoryQueryCompilable: ctx})
        out = result[MEMORY_RELATIONAL]
        assert len(out.data) == len(USERS)


class TestPrebuiltCompilers:
    """Pre-built compiler constants exist and have correct phases."""

    def test_memory_relational_compiler(self) -> None:
        assert len(MEMORY_RELATIONAL_COMPILER) == 1
        assert MEMORY_RELATIONAL in MEMORY_RELATIONAL_COMPILER

    def test_sa_compiler(self) -> None:
        assert len(SA_COMPILER) == 1
        assert SA_RELATIONAL in SA_COMPILER

    def test_memory_api_compiler(self) -> None:
        assert len(MEMORY_API_COMPILER) == 1
        assert MEMORY_API in MEMORY_API_COMPILER

    def test_http_compiler(self) -> None:
        assert len(HTTP_COMPILER) == 1
        assert HTTP_API in HTTP_COMPILER

    def test_memory_kv_compiler(self) -> None:
        assert len(MEMORY_KV_COMPILER) == 1
        assert MEMORY_KV in MEMORY_KV_COMPILER

    def test_http_kv_compiler(self) -> None:
        assert len(HTTP_KV_COMPILER) == 1
        assert HTTP_KV in HTTP_KV_COMPILER


# ═════════════════════════════════════════════════════════════════════════════
# Self-compiling ops: compile_memory_api, compile_memory_query
# ═════════════════════════════════════════════════════════════════════════════


class TestSelfCompilingOpsMemoryAPI:
    """Ops compile_memory_api methods."""

    def test_page_mod_compile(self) -> None:
        ctx = MemoryAPIContext(data=list(range(100)))
        mod = PageMod(page=2, per_page=10)
        result = mod.compile_memory_api(ctx)
        assert len(result.data) == 10
        assert result.total == 100
        assert result.has_more is True

    def test_page_mod_last_page(self) -> None:
        ctx = MemoryAPIContext(data=list(range(25)))
        mod = PageMod(page=3, per_page=10)
        result = mod.compile_memory_api(ctx)
        assert len(result.data) == 5
        assert result.total == 25
        assert result.has_more is False

    def test_cursor_mod_compile(self) -> None:
        ctx = MemoryAPIContext(data=list(range(50)))
        mod = CursorMod(cursor="10", limit=5)
        result = mod.compile_memory_api(ctx)
        assert len(result.data) == 5
        assert result.total == 50

    def test_cursor_mod_invalid_cursor(self) -> None:
        ctx = MemoryAPIContext(data=list(range(10)))
        mod = CursorMod(cursor="invalid", limit=5)
        result = mod.compile_memory_api(ctx)
        # Falls back to start=0
        assert len(result.data) == 5

    def test_offset_mod_compile(self) -> None:
        ctx = MemoryAPIContext(data=list(range(30)))
        mod = OffsetMod(offset=10, limit=5)
        result = mod.compile_memory_api(ctx)
        assert len(result.data) == 5
        assert result.total == 30

    def test_offset_mod_no_more(self) -> None:
        ctx = MemoryAPIContext(data=list(range(10)))
        mod = OffsetMod(offset=8, limit=5)
        result = mod.compile_memory_api(ctx)
        assert len(result.data) == 2
        assert result.has_more is False

    def test_search_mod_compile(self) -> None:
        ctx = MemoryAPIContext(data=list(USERS))
        mod = SearchMod(query="alice")
        result = mod.compile_memory_api(ctx)
        assert len(result.data) == 1

    def test_search_mod_case_insensitive(self) -> None:
        ctx = MemoryAPIContext(data=list(USERS))
        mod = SearchMod(query="ALICE")
        result = mod.compile_memory_api(ctx)
        assert len(result.data) == 1

    def test_search_mod_no_match(self) -> None:
        ctx = MemoryAPIContext(data=list(USERS))
        mod = SearchMod(query="zzzzz")
        result = mod.compile_memory_api(ctx)
        assert len(result.data) == 0


class TestSelfCompilingOpsHTTPAPI:
    """Ops compile_http_api methods."""

    def test_search_mod_http(self) -> None:
        ctx = HTTPAPIContext(
            params={},
            body=None,
            encode_filter=lambda e: {},
            apply_pagination=lambda p, m: None,
            is_body_filter=False,
        )
        mod = SearchMod(query="test")
        result = mod.compile_http_api(ctx)
        assert result.params["q"] == "test"

    def test_include_mod_http(self) -> None:
        ctx = HTTPAPIContext(
            params={},
            body=None,
            encode_filter=lambda e: {},
            apply_pagination=lambda p, m: None,
            is_body_filter=False,
        )
        mod = IncludeMod(relations=("posts", "comments"))
        result = mod.compile_http_api(ctx)
        assert result.params["include"] == "posts,comments"

    def test_page_mod_http(self) -> None:
        applied: list[tuple[dict[str, object], object]] = []

        def apply_pagination(params: dict[str, object], mod: object) -> None:
            applied.append((params, mod))

        ctx = HTTPAPIContext(
            params={},
            body=None,
            encode_filter=lambda e: {},
            apply_pagination=apply_pagination,
            is_body_filter=False,
        )
        mod = PageMod(page=2, per_page=10)
        mod.compile_http_api(ctx)
        assert len(applied) == 1

    def test_filter_http_query_params(self) -> None:
        ctx = HTTPAPIContext(
            params={},
            body=None,
            encode_filter=lambda e: {"active": "true"},
            apply_pagination=lambda p, m: None,
            is_body_filter=False,
        )
        f = Filter(Gt(Field("balance"), Const(0)))
        f.compile_http_api(ctx)
        assert ctx.params.get("active") == "true"

    def test_filter_http_body(self) -> None:
        ctx = HTTPAPIContext(
            params={},
            body=None,
            encode_filter=lambda e: {"filter": "active"},
            apply_pagination=lambda p, m: None,
            is_body_filter=True,
        )
        f = Filter(Gt(Field("balance"), Const(0)))
        f.compile_http_api(ctx)
        assert ctx.body is not None
        assert ctx.body.get("filter") == "active"

    def test_filter_http_body_merge(self) -> None:
        ctx = HTTPAPIContext(
            params={},
            body={"existing": "data"},
            encode_filter=lambda e: {"filter": "new"},
            apply_pagination=lambda p, m: None,
            is_body_filter=True,
        )
        f = Filter(Gt(Field("balance"), Const(0)))
        f.compile_http_api(ctx)
        assert ctx.body is not None
        assert ctx.body.get("existing") == "data"
        assert ctx.body.get("filter") == "new"

    def test_order_by_http_with_encoder(self) -> None:
        ctx = HTTPAPIContext(
            params={},
            body=None,
            encode_filter=lambda e: {},
            apply_pagination=lambda p, m: None,
            is_body_filter=False,
            encode_order=lambda specs: {"sort": ",".join(s.field for s in specs)},
        )
        op = OrderBy((OrderSpec("name", True), OrderSpec("balance", False)))
        op.compile_http_api(ctx)
        assert ctx.params.get("sort") == "name,balance"

    def test_order_by_http_no_encoder(self) -> None:
        ctx = HTTPAPIContext(
            params={},
            body=None,
            encode_filter=lambda e: {},
            apply_pagination=lambda p, m: None,
            is_body_filter=False,
            encode_order=None,
        )
        op = OrderBy((OrderSpec("name", True),))
        op.compile_http_api(ctx)
        # No encoder, params unchanged
        assert "sort" not in ctx.params

    def test_limit_http_with_encoder(self) -> None:
        ctx = HTTPAPIContext(
            params={},
            body=None,
            encode_filter=lambda e: {},
            apply_pagination=lambda p, m: None,
            is_body_filter=False,
            encode_limit=lambda n: {"limit": n},
        )
        op = Limit(25)
        op.compile_http_api(ctx)
        assert ctx.params.get("limit") == 25

    def test_limit_http_no_encoder(self) -> None:
        ctx = HTTPAPIContext(
            params={},
            body=None,
            encode_filter=lambda e: {},
            apply_pagination=lambda p, m: None,
            is_body_filter=False,
            encode_limit=None,
        )
        op = Limit(25)
        op.compile_http_api(ctx)
        assert "limit" not in ctx.params

    def test_select_http_with_encoder(self) -> None:
        ctx = HTTPAPIContext(
            params={},
            body=None,
            encode_filter=lambda e: {},
            apply_pagination=lambda p, m: None,
            is_body_filter=False,
            encode_select=lambda fields: {"fields": ",".join(fields)},
        )
        op = Select(("id", "name"))
        op.compile_http_api(ctx)
        assert ctx.params.get("fields") == "id,name"

    def test_select_http_no_encoder(self) -> None:
        ctx = HTTPAPIContext(
            params={},
            body=None,
            encode_filter=lambda e: {},
            apply_pagination=lambda p, m: None,
            is_body_filter=False,
            encode_select=None,
        )
        op = Select(("id", "name"))
        op.compile_http_api(ctx)
        assert "fields" not in ctx.params


class TestSelfCompilingOpsMemoryQuery:
    """Ops compile_memory_query methods on relational types."""

    def test_filter_compile_memory_query(self) -> None:
        ctx = MemoryQueryContext(data=list(USERS))
        f = Filter(Gt(Field("balance"), Const(100.0)))
        result = f.compile_memory_query(ctx)
        for u in result.data:
            assert isinstance(u, User)
            assert u.balance > 100

    def test_order_by_compile_memory_query(self) -> None:
        ctx = MemoryQueryContext(data=list(USERS))
        op = OrderBy((OrderSpec("name", ascending=True),))
        result = op.compile_memory_query(ctx)
        names: list[str] = []
        for u in result.data:
            assert isinstance(u, User)
            names.append(u.name)
        assert names == sorted(names)

    def test_limit_compile_memory_query(self) -> None:
        ctx = MemoryQueryContext(data=list(USERS))
        result = Limit(2).compile_memory_query(ctx)
        assert len(result.data) == 2

    def test_offset_compile_memory_query(self) -> None:
        ctx = MemoryQueryContext(data=list(USERS))
        result = Offset(3).compile_memory_query(ctx)
        assert len(result.data) == 2

    def test_select_compile_memory_query(self) -> None:
        ctx = MemoryQueryContext(data=list(USERS))
        result = Select(("name",)).compile_memory_query(ctx)
        for r in result.data:
            assert isinstance(r, dict)
            assert "name" in r

    def test_distinct_compile_memory_query(self) -> None:
        data: list[object] = [*USERS, USERS[0]]
        ctx = MemoryQueryContext(data=data)
        result = Distinct().compile_memory_query(ctx)
        assert len(result.data) == len(USERS)

    def test_aggregate_passthrough(self) -> None:
        specs = (AggregateSpec(Count(), None, "cnt"),)
        ctx = MemoryQueryContext(data=list(USERS))
        result = Aggregate(specs).compile_memory_query(ctx)
        assert result.data == ctx.data  # unchanged


class TestSelfCompilingKVOps:
    """KV ops compile_memory_kv / compile_http_kv."""

    def test_kv_get_memory(self) -> None:
        ctx = MemoryKVContext(store={"alice": User(1, "alice", 100.0)})
        result = KVGet("alice").compile_memory_kv(ctx)
        assert result.result is not None
        assert isinstance(result.result, User)
        assert result.result.name == "alice"

    def test_kv_get_missing(self) -> None:
        ctx = MemoryKVContext(store={})
        result = KVGet("missing").compile_memory_kv(ctx)
        assert result.result is None

    def test_kv_set_memory(self) -> None:
        ctx = MemoryKVContext(store={})
        u = User(1, "alice", 100.0)
        KVSet("alice", u).compile_memory_kv(ctx)
        assert ctx.store["alice"] is u

    def test_kv_delete_memory(self) -> None:
        ctx = MemoryKVContext(store={"alice": User(1, "alice", 100.0)})
        result = KVDelete("alice").compile_memory_kv(ctx)
        assert result.result is True
        assert "alice" not in ctx.store

    def test_kv_delete_missing(self) -> None:
        ctx = MemoryKVContext(store={})
        result = KVDelete("alice").compile_memory_kv(ctx)
        assert result.result is False

    def test_kv_exists_memory(self) -> None:
        ctx = MemoryKVContext(store={"alice": 1})
        result = Exists("alice").compile_memory_kv(ctx)
        assert result.result is True

    def test_kv_exists_missing(self) -> None:
        ctx = MemoryKVContext(store={})
        result = Exists("alice").compile_memory_kv(ctx)
        assert result.result is False

    def test_kv_scan_memory(self) -> None:
        ctx = MemoryKVContext(store={"user:1": "a", "user:2": "b", "session:1": "c"})
        result = Scan("user:*").compile_memory_kv(ctx)
        scan_result = cast(list[object], result.result)
        assert len(scan_result) == 2

    def test_kv_keys_memory(self) -> None:
        ctx = MemoryKVContext(store={"user:1": "a", "user:2": "b", "session:1": "c"})
        result = Keys("user:*").compile_memory_kv(ctx)
        keys_result = cast(list[str], result.result)
        assert len(keys_result) == 2

    def test_kv_get_http(self) -> None:
        ctx = HTTPKVContext()
        result = KVGet("alice").compile_http_kv(ctx)
        assert result.method == "GET"
        assert result.path == "alice"

    def test_kv_set_http(self) -> None:
        ctx = HTTPKVContext()
        result = KVSet("alice", "value", ttl=60).compile_http_kv(ctx)
        assert result.method == "PUT"
        assert result.body is not None

    def test_kv_delete_http(self) -> None:
        ctx = HTTPKVContext()
        result = KVDelete("alice").compile_http_kv(ctx)
        assert result.method == "DELETE"

    def test_kv_exists_http(self) -> None:
        ctx = HTTPKVContext()
        result = Exists("alice").compile_http_kv(ctx)
        assert result.method == "HEAD"

    def test_kv_scan_http(self) -> None:
        ctx = HTTPKVContext()
        result = Scan("user:*").compile_http_kv(ctx)
        assert result.method == "GET"
        assert result.params is not None

    def test_kv_keys_http(self) -> None:
        ctx = HTTPKVContext()
        result = Keys("user:*").compile_http_kv(ctx)
        assert result.method == "GET"


# ═════════════════════════════════════════════════════════════════════════════
# Property-based: random chain composition
# ═════════════════════════════════════════════════════════════════════════════


# Strategy: random chain of relational ops
def _relational_chain_strategy() -> st.SearchStrategy[RelationalQuerySet[User]]:
    """Build random relational query chains."""

    def build(ops: list[str]) -> RelationalQuerySet[User]:
        q = relational(User)
        for op_name in ops:
            if op_name == "filter":
                q = q.filter(lambda u: u.balance > 0)
            elif op_name == "order_by":
                q = q.order_by(lambda u: u.name)
            elif op_name == "limit":
                q = q.limit(10)
            elif op_name == "offset":
                q = q.offset(5)
            elif op_name == "distinct":
                q = q.distinct()
        return q

    return st.lists(
        st.sampled_from(["filter", "order_by", "limit", "offset", "distinct"]),
        min_size=0,
        max_size=6,
    ).map(build)


class TestPropertyRandomChains:
    """Property-based tests for random chain composition."""

    @given(q=_relational_chain_strategy())
    @settings(max_examples=50)
    def test_entity_preserved(self, q: RelationalQuerySet[User]) -> None:
        assert q.entity is User

    @given(q=_relational_chain_strategy())
    @settings(max_examples=50)
    def test_ops_are_tuples(self, q: RelationalQuerySet[User]) -> None:
        assert isinstance(q.ops, tuple)

    @given(q=_relational_chain_strategy())
    @settings(max_examples=30)
    def test_fold_does_not_crash(self, q: RelationalQuerySet[User]) -> None:
        # Fold over the generated query should not raise
        result = MEMORY_DIALECT.fold(list(q.ops), list(USERS))
        assert isinstance(result, list)

"""Tests for RelationalQuerySet — building, ops, introspection."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

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
    relational,
)
from emergent.wire.axis.query._proxy import OrderSpec
from emergent.wire.axis.query._aggregate import Sum


@dataclass
class User:
    id: int
    name: str
    balance: float


@dataclass
class Post:
    id: int
    author_id: int
    title: str


# ─── Factory ─────────────────────────────────────────────────────────────────


class TestFactory:
    def test_relational_creates_empty(self):
        q = relational(User)
        assert q.entity is User
        assert q.ops == ()

    def test_immutable(self):
        q1 = relational(User)
        q2 = q1.filter(lambda u: u.balance > 0)
        assert q1.ops == ()  # unchanged
        assert len(q2.ops) == 1


# ─── Op Building ─────────────────────────────────────────────────────────────


class TestOpBuilding:
    def test_filter(self):
        q = relational(User).filter(lambda u: u.balance > 100)
        assert len(q.ops) == 1
        assert isinstance(q.ops[0], Filter)

    def test_where_alias(self):
        q = relational(User).where(lambda u: u.balance > 100)
        assert isinstance(q.ops[0], Filter)

    def test_order_by(self):
        q = relational(User).order_by(lambda u: u.name)
        assert isinstance(q.ops[0], OrderBy)

    def test_order_by_desc(self):
        q = relational(User).order_by(lambda u: u.balance.desc())
        op = q.ops[0]
        assert isinstance(op, OrderBy)
        assert op.specs[0].ascending is False

    def test_limit(self):
        q = relational(User).limit(10)
        assert isinstance(q.ops[0], Limit)
        assert q.ops[0].count == 10

    def test_offset(self):
        q = relational(User).offset(20)
        assert isinstance(q.ops[0], Offset)
        assert q.ops[0].count == 20

    def test_paginate(self):
        q = relational(User).paginate(3, 10)
        assert len(q.ops) == 2
        assert isinstance(q.ops[0], Offset)
        assert q.ops[0].count == 20  # (3-1) * 10
        assert isinstance(q.ops[1], Limit)
        assert q.ops[1].count == 10

    def test_paginate_page_1(self) -> None:
        q = relational(User).paginate(1, 25)
        op = q.ops[0]
        assert isinstance(op, Offset)
        assert op.count == 0  # offset

    def test_select(self):
        q = relational(User).select(lambda u: u.id, lambda u: u.name)
        assert isinstance(q.ops[0], Select)
        assert q.ops[0].fields == ("id", "name")

    def test_distinct(self):
        q = relational(User).distinct()
        assert isinstance(q.ops[0], Distinct)

    def test_join(self):
        q = relational(User).join(Post, on=lambda u, p: u.id == p.author_id)
        op = q.ops[0]
        assert isinstance(op, Join)
        assert op.target is Post
        assert op.kind == "inner"

    def test_left_join(self):
        q = relational(User).left_join(Post, on=lambda u, p: u.id == p.author_id)
        op = q.ops[0]
        assert isinstance(op, Join)
        assert op.kind == "left"

    def test_join_with_tablename(self) -> None:
        q = relational(User).join(Post, on=lambda u, p: u.id == p.author_id, tablename="posts")
        op = q.ops[0]
        assert isinstance(op, Join)
        assert op.tablename == "posts"

    def test_group_by(self):
        q = relational(User).group_by(lambda u: u.name)
        assert isinstance(q.ops[0], GroupBy)

    def test_having(self):
        q = relational(User).having(lambda u: u.balance > 100)
        assert isinstance(q.ops[0], Having)

    def test_aggregate(self):
        q = relational(User).aggregate(total=lambda u: u.balance.sum())
        assert isinstance(q.ops[0], Aggregate)
        specs = q.ops[0].specs
        assert len(specs) == 1
        assert specs[0].alias == "total"
        assert isinstance(specs[0].func, Sum)

    def test_chaining(self):
        q = (
            relational(User)
            .filter(lambda u: u.balance > 0)
            .order_by(lambda u: u.balance.desc())
            .limit(10)
        )
        assert len(q.ops) == 3
        assert isinstance(q.ops[0], Filter)
        assert isinstance(q.ops[1], OrderBy)
        assert isinstance(q.ops[2], Limit)


# ─── Validation ──────────────────────────────────────────────────────────────


class TestValidation:
    def test_limit_negative_raises(self):
        with pytest.raises(ValueError, match="non-negative"):
            relational(User).limit(-1)

    def test_offset_negative_raises(self):
        with pytest.raises(ValueError, match="non-negative"):
            relational(User).offset(-5)

    def test_limit_zero_ok(self) -> None:
        q = relational(User).limit(0)
        op = q.ops[0]
        assert isinstance(op, Limit)
        assert op.count == 0

    def test_paginate_page_zero_raises(self):
        with pytest.raises(ValueError, match="page must be >= 1"):
            relational(User).paginate(0, 10)

    def test_paginate_per_page_zero_raises(self):
        with pytest.raises(ValueError, match="per_page must be >= 1"):
            relational(User).paginate(1, 0)

    def test_select_empty_raises(self):
        with pytest.raises(ValueError, match="at least one field"):
            relational(User).select()

    def test_group_by_empty_raises(self):
        with pytest.raises(ValueError, match="at least one field"):
            relational(User).group_by()

    def test_select_is_terminal(self):
        """All ops that need entity attributes cannot follow select()."""
        q = relational(User).select(lambda u: u.name)
        with pytest.raises(TypeError, match="after .select"):
            q.filter(lambda u: u.name == "x")
        with pytest.raises(TypeError, match="after .select"):
            q.order_by(lambda u: u.name)
        with pytest.raises(TypeError, match="after .select"):
            q.distinct()
        with pytest.raises(TypeError, match="after .select"):
            q.join(Post, on=lambda u, p: u.id == p.author_id)
        with pytest.raises(TypeError, match="after .select"):
            q.left_join(Post, on=lambda u, p: u.id == p.author_id)
        with pytest.raises(TypeError, match="after .select"):
            q.group_by(lambda u: u.name)
        with pytest.raises(TypeError, match="after .select"):
            q.having(lambda u: u.balance > 0)

    def test_select_allows_limit_offset(self):
        """limit/offset/paginate are fine after select (no entity access)."""
        q = relational(User).select(lambda u: u.name).limit(10).offset(5)
        assert len(q.ops) == 3


# ─── Introspection ───────────────────────────────────────────────────────────


class TestIntrospection:
    def test_filters(self):
        q = relational(User).filter(lambda u: u.balance > 0).filter(lambda u: u.name == "alice")
        assert len(q.filters) == 2

    def test_ordering(self):
        q = relational(User).order_by(lambda u: u.name, lambda u: u.balance.desc())
        assert len(q.ordering) == 2
        assert q.ordering[0] == OrderSpec("name", ascending=True)
        assert q.ordering[1] == OrderSpec("balance", ascending=False)

    def test_limit_value(self):
        assert relational(User).limit(10).limit_value == 10
        assert relational(User).limit_value is None

    def test_offset_value(self):
        assert relational(User).offset(5).offset_value == 5
        assert relational(User).offset_value is None

    def test_has_aggregates(self):
        assert relational(User).has_aggregates is False
        q = relational(User).aggregate(cnt=lambda u: u.count())
        assert q.has_aggregates is True

    def test_aggregates(self):
        q = relational(User).aggregate(
            total=lambda u: u.balance.sum(),
            cnt=lambda u: u.count(),
        )
        assert len(q.aggregates) == 2
        aliases = {s.alias for s in q.aggregates}
        assert aliases == {"total", "cnt"}


# ─── Integration: Complex Query Chains ──────────────────────────────────────


class TestIntegrationComplexQueryChain:
    def test_filter_order_limit_offset_distinct_select_chain(self):
        q = (
            relational(User)
            .filter(lambda u: u.balance > 0)
            .order_by(lambda u: u.balance.desc())
            .limit(10)
            .offset(5)
            .distinct()
            .select(lambda u: u.id, lambda u: u.name)
        )
        assert len(q.ops) == 6
        assert isinstance(q.ops[0], Filter)
        assert isinstance(q.ops[1], OrderBy)
        assert isinstance(q.ops[2], Limit)
        assert isinstance(q.ops[3], Offset)
        assert isinstance(q.ops[4], Distinct)
        assert isinstance(q.ops[5], Select)

    def test_introspection_on_complex_chain(self):
        q = (
            relational(User)
            .filter(lambda u: u.balance > 0)
            .filter(lambda u: u.name != "admin")
            .order_by(lambda u: u.balance.desc(), lambda u: u.name)
            .limit(10)
            .offset(5)
        )
        assert len(q.filters) == 2
        assert len(q.ordering) == 2
        assert q.ordering[0] == OrderSpec("balance", ascending=False)
        assert q.ordering[1] == OrderSpec("name", ascending=True)
        assert q.limit_value == 10
        assert q.offset_value == 5

    def test_filter_join_group_by_having_aggregate(self):
        q = (
            relational(User)
            .filter(lambda u: u.balance > 0)
            .join(Post, on=lambda u, p: u.id == p.author_id)
            .group_by(lambda u: u.name)
            .having(lambda u: u.balance > 100)
            .aggregate(total=lambda u: u.balance.sum(), cnt=lambda u: u.count())
        )
        assert len(q.ops) == 5
        assert isinstance(q.ops[0], Filter)
        assert isinstance(q.ops[1], Join)
        assert isinstance(q.ops[2], GroupBy)
        assert isinstance(q.ops[3], Having)
        assert isinstance(q.ops[4], Aggregate)
        assert q.has_aggregates is True
        assert len(q.aggregates) == 2
        aliases = {s.alias for s in q.aggregates}
        assert aliases == {"total", "cnt"}

    def test_immutability_after_chaining(self):
        q0 = relational(User)
        q1 = q0.filter(lambda u: u.balance > 0)
        q2 = q1.order_by(lambda u: u.name)
        q3 = q2.limit(10)
        q4 = q3.offset(5)
        # Original queries are unchanged
        assert q0.ops == ()
        assert len(q1.ops) == 1
        assert len(q2.ops) == 2
        assert len(q3.ops) == 3
        assert len(q4.ops) == 4
        # Entity preserved
        assert q4.entity is User

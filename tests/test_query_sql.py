"""Tests for SQLRelationalQuerySet — window, for_update, returning."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from emergent.wire.axis.query._relational import Filter, Limit, OrderBy, relational
from emergent.wire.axis.query._sql import (
    ForUpdate,
    Returning,
    SQLRelationalQuerySet,
    Window,
    WindowBuilder,
    sql_relational,
)
from emergent.wire.axis.query._proxy import FieldProxy, OrderSpec
from emergent.wire.axis.query._window import (
    DenseRank,
    Lag,
    Lead,
    Ntile,
    Rank,
    RowNumber,
    WindowSpec,
)
from emergent.wire.axis.query._aggregate import Sum


@dataclass
class User:
    id: int
    name: str
    balance: float
    department: str = "eng"


# ─── Factory ─────────────────────────────────────────────────────────────────


class TestFactory:
    def test_sql_relational_creates_empty(self):
        q = sql_relational(User)
        assert q.entity is User
        assert q.ops == ()

    def test_is_sql_type(self):
        assert isinstance(sql_relational(User), SQLRelationalQuerySet)


# ─── Relational Ops (inherited) ──────────────────────────────────────────────


class TestRelationalOps:
    def test_filter(self):
        q = sql_relational(User).filter(lambda u: u.balance > 100)
        assert isinstance(q.ops[0], Filter)
        assert isinstance(q, SQLRelationalQuerySet)

    def test_order_by(self):
        q = sql_relational(User).order_by(lambda u: u.name)
        assert isinstance(q.ops[0], OrderBy)

    def test_limit(self):
        q = sql_relational(User).limit(10)
        assert isinstance(q.ops[0], Limit)

    def test_chaining_preserves_type(self):
        q = (
            sql_relational(User)
            .filter(lambda u: u.balance > 0)
            .order_by(lambda u: u.name)
            .limit(10)
        )
        assert isinstance(q, SQLRelationalQuerySet)
        assert len(q.ops) == 3


# ─── Window ──────────────────────────────────────────────────────────────────


class TestWindow:
    def test_window_row_number(self):
        q = sql_relational(User).window(
            rn=lambda u: u.row_number().over(
                partition_by=u.department,
                order_by=u.balance.desc(),
            ),
        )
        assert q.has_windows
        specs = q.windows
        assert len(specs) == 1
        assert specs[0].alias == "rn"
        assert isinstance(specs[0].func, RowNumber)
        assert specs[0].partition_by == ("department",)
        assert specs[0].order_by[0].ascending is False

    def test_window_aggregate_over(self):
        q = sql_relational(User).window(
            running_total=lambda u: u.balance.sum().over(
                partition_by=u.department,
            ),
        )
        specs = q.windows
        assert len(specs) == 1
        assert isinstance(specs[0].func, Sum)
        assert specs[0].field == "balance"

    def test_multiple_windows(self):
        q = sql_relational(User).window(
            rn=lambda u: u.row_number().over(order_by=u.id.asc()),
            rnk=lambda u: u.rank().over(order_by=u.balance.desc()),
        )
        assert len(q.windows) == 2
        aliases = {s.alias for s in q.windows}
        assert aliases == {"rn", "rnk"}

    def test_has_windows_false(self):
        assert sql_relational(User).has_windows is False


# ─── ForUpdate ───────────────────────────────────────────────────────────────


class TestForUpdate:
    def test_basic(self):
        q = sql_relational(User).for_update()
        assert q.has_for_update
        op = [op for op in q.ops if isinstance(op, ForUpdate)][0]
        assert op.nowait is False
        assert op.skip_locked is False

    def test_nowait(self):
        q = sql_relational(User).for_update(nowait=True)
        op = [op for op in q.ops if isinstance(op, ForUpdate)][0]
        assert op.nowait is True

    def test_skip_locked(self):
        q = sql_relational(User).for_update(skip_locked=True)
        op = [op for op in q.ops if isinstance(op, ForUpdate)][0]
        assert op.skip_locked is True

    def test_has_for_update_false(self):
        assert sql_relational(User).has_for_update is False


# ─── Returning ───────────────────────────────────────────────────────────────


class TestReturning:
    def test_returning_star(self):
        q = sql_relational(User).returning()
        assert q.has_returning
        op = [op for op in q.ops if isinstance(op, Returning)][0]
        assert op.fields == ()

    def test_returning_fields(self):
        q = sql_relational(User).returning("id", "name")
        op = [op for op in q.ops if isinstance(op, Returning)][0]
        assert op.fields == ("id", "name")

    def test_has_returning_false(self):
        assert sql_relational(User).has_returning is False


# ─── to_relational ───────────────────────────────────────────────────────────


class TestToRelational:
    def test_strips_sql_ops(self):
        q = (
            sql_relational(User)
            .filter(lambda u: u.balance > 0)
            .for_update(nowait=True)
            .window(rn=lambda u: u.row_number().over())
            .returning("id")
            .limit(10)
        )
        rel = q.to_relational()
        assert not isinstance(rel, SQLRelationalQuerySet)
        # Only universal ops remain
        assert len(rel.ops) == 2  # Filter + Limit
        assert isinstance(rel.ops[0], Filter)
        assert isinstance(rel.ops[1], Limit)

    def test_preserves_entity(self):
        q = sql_relational(User).filter(lambda u: u.balance > 0)
        assert q.to_relational().entity is User


# ─── Full Chain ──────────────────────────────────────────────────────────────


class TestFullChain:
    def test_complex_query(self):
        q = (
            sql_relational(User)
            .filter(lambda u: u.balance > 0)
            .window(
                rn=lambda u: u.row_number().over(
                    partition_by=u.department,
                    order_by=u.balance.desc(),
                ),
            )
            .for_update(nowait=True)
            .returning("id", "name")
            .order_by(lambda u: u.name)
            .limit(100)
        )
        assert len(q.ops) == 6
        assert q.has_windows
        assert q.has_for_update
        assert q.has_returning


# ─── WindowBuilder ───────────────────────────────────────────────────────────


class TestWindowBuilder:
    def test_no_over_args(self):
        wb = WindowBuilder(RowNumber(), None)
        spec = wb.over()
        assert isinstance(spec, WindowSpec)
        assert spec.partition_by == ()
        assert spec.order_by == ()

    def test_single_partition_by(self):
        wb = WindowBuilder(RowNumber(), None)
        spec = wb.over(partition_by=FieldProxy("department"))
        assert spec.partition_by == ("department",)

    def test_tuple_partition_by(self):
        wb = WindowBuilder(RowNumber(), None)
        spec = wb.over(partition_by=(FieldProxy("a"), FieldProxy("b")))
        assert spec.partition_by == ("a", "b")

    def test_invalid_partition_by_raises(self):
        wb = WindowBuilder(RowNumber(), None)
        with pytest.raises(TypeError, match="partition_by expects FieldProxy"):
            wb.over(partition_by=("not_a_proxy",))  # type: ignore

    def test_order_by_order_spec(self):
        wb = WindowBuilder(RowNumber(), None)
        spec = wb.over(order_by=OrderSpec("balance", ascending=False))
        assert spec.order_by == (OrderSpec("balance", ascending=False),)

    def test_order_by_field_proxy(self):
        wb = WindowBuilder(RowNumber(), None)
        spec = wb.over(order_by=FieldProxy("name"))
        assert spec.order_by == (OrderSpec("name", ascending=True),)

    def test_order_by_tuple(self):
        wb = WindowBuilder(RowNumber(), None)
        spec = wb.over(order_by=(
            OrderSpec("a", ascending=True),
            FieldProxy("b"),
        ))
        assert len(spec.order_by) == 2
        assert spec.order_by[1] == OrderSpec("b", ascending=True)

    def test_order_by_invalid_scalar_raises(self):
        wb = WindowBuilder(RowNumber(), None)
        with pytest.raises(TypeError, match="order_by expects OrderSpec, FieldProxy, or tuple"):
            wb.over(order_by="bad")  # type: ignore

    def test_order_by_invalid_tuple_element_raises(self):
        wb = WindowBuilder(RowNumber(), None)
        with pytest.raises(TypeError, match="order_by expects OrderSpec or FieldProxy"):
            wb.over(order_by=(OrderSpec("a", ascending=True), "bad"))  # type: ignore


# ─── Integration: SQL Complex Query ─────────────────────────────────────────


class TestIntegrationSQLComplexQuery:
    def test_filter_window_for_update_returning(self):
        q = (
            sql_relational(User)
            .filter(lambda u: u.balance > 0)
            .window(
                rn=lambda u: u.row_number().over(
                    partition_by=u.department,
                    order_by=u.balance.desc(),
                ),
            )
            .for_update(nowait=True)
            .returning("id", "name")
        )
        assert len(q.ops) == 4
        assert isinstance(q.ops[0], Filter)
        assert isinstance(q.ops[1], Window)
        assert isinstance(q.ops[2], ForUpdate)
        assert isinstance(q.ops[3], Returning)

        # Verify window spec
        assert q.has_windows is True
        specs = q.windows
        assert len(specs) == 1
        assert specs[0].alias == "rn"
        assert isinstance(specs[0].func, RowNumber)
        assert specs[0].partition_by == ("department",)
        assert len(specs[0].order_by) == 1
        assert specs[0].order_by[0].field == "balance"
        assert specs[0].order_by[0].ascending is False

        # Verify for_update
        assert q.has_for_update is True
        for_update_ops = [op for op in q.ops if isinstance(op, ForUpdate)]
        assert for_update_ops[0].nowait is True

        # Verify returning
        assert q.has_returning is True
        returning_ops = [op for op in q.ops if isinstance(op, Returning)]
        assert returning_ops[0].fields == ("id", "name")

    def test_to_relational_strips_sql_ops_keeps_filter(self):
        q = (
            sql_relational(User)
            .filter(lambda u: u.balance > 0)
            .window(rn=lambda u: u.row_number().over())
            .for_update(nowait=True)
            .returning("id", "name")
            .order_by(lambda u: u.name)
            .limit(50)
        )
        rel = q.to_relational()
        assert not isinstance(rel, SQLRelationalQuerySet)
        # Only universal ops: Filter, OrderBy, Limit
        assert len(rel.ops) == 3
        assert isinstance(rel.ops[0], Filter)
        assert isinstance(rel.ops[1], OrderBy)
        assert isinstance(rel.ops[2], Limit)
        assert rel.entity is User

    def test_window_partition_and_order_correctness(self):
        q = sql_relational(User).window(
            running_total=lambda u: u.balance.sum().over(
                partition_by=u.department,
                order_by=u.balance.asc(),
            ),
        )
        specs = q.windows
        assert len(specs) == 1
        spec = specs[0]
        assert spec.alias == "running_total"
        assert isinstance(spec.func, Sum)
        assert spec.field == "balance"
        assert spec.partition_by == ("department",)
        assert spec.order_by == (OrderSpec("balance", ascending=True),)

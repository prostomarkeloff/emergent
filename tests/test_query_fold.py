"""Tests for fold_query, QueryDialect, MEMORY_DIALECT."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from emergent.wire.axis.query._fold import (
    MEMORY_DIALECT,
    MEMORY_HANDLERS,
    QueryDialect,
    fold_query,
)
from emergent.wire.axis.query._relational import (
    Distinct,
    Filter,
    GroupBy,
    Join,
    Limit,
    Offset,
    OrderBy,
    Select,
    relational,
)
from emergent.wire.axis.query._expr import Eq, Field, Const, Gt
from emergent.wire.axis.query._proxy import OrderSpec


@dataclass
class User:
    id: int
    name: str
    balance: float


DATA = [
    User(1, "charlie", 200.0),
    User(2, "alice", 100.0),
    User(3, "bob", 50.0),
]


# ─── fold_query primitive ────────────────────────────────────────────────────


class TestFoldQuery:
    def test_empty_ops(self):
        result = fold_query((), list(DATA), MEMORY_HANDLERS)
        assert len(result) == 3

    def test_filter(self):
        ops = [Filter(Gt(Field("balance"), Const(75.0)))]
        result = fold_query(ops, list(DATA), MEMORY_HANDLERS)
        assert len(result) == 2

    def test_order_by(self):
        ops = [OrderBy((OrderSpec("name", ascending=True),))]
        result = fold_query(ops, list(DATA), MEMORY_HANDLERS)
        assert [u.name for u in result] == ["alice", "bob", "charlie"]

    def test_limit(self):
        ops = [Limit(2)]
        result = fold_query(ops, list(DATA), MEMORY_HANDLERS)
        assert len(result) == 2

    def test_offset(self):
        ops = [Offset(1)]
        result = fold_query(ops, list(DATA), MEMORY_HANDLERS)
        assert len(result) == 2

    def test_chain(self):
        ops = [
            Filter(Gt(Field("balance"), Const(0.0))),
            OrderBy((OrderSpec("balance", ascending=False),)),
            Limit(2),
        ]
        result = fold_query(ops, list(DATA), MEMORY_HANDLERS)
        assert len(result) == 2
        assert result[0].balance > result[1].balance

    def test_unknown_ops_skipped(self):
        @dataclass(frozen=True, slots=True)
        class UnknownOp:
            pass

        ops = [UnknownOp(), Filter(Gt(Field("balance"), Const(75.0)))]
        result = fold_query(ops, list(DATA), MEMORY_HANDLERS)
        assert len(result) == 2  # filter applied, unknown skipped

    def test_distinct(self):
        duped = DATA + [User(1, "charlie", 200.0)]
        ops = [Distinct()]
        result = fold_query(ops, duped, MEMORY_HANDLERS)
        assert len(result) == 3  # duplicate removed

    def test_select(self):
        """Select projects entities to dicts."""
        ops = [Select(("name", "balance"))]
        result = fold_query(ops, list(DATA), MEMORY_HANDLERS)
        assert isinstance(result[0], dict)
        assert set(result[0].keys()) == {"name", "balance"}

    def test_join_raises(self):
        ops = [Join(User, Eq(Field("id"), Field("id")), "inner", None)]
        with pytest.raises(TypeError, match="does not support Join"):
            fold_query(ops, list(DATA), MEMORY_HANDLERS)

    def test_group_by_raises(self):
        ops = [GroupBy(("name",))]
        with pytest.raises(TypeError, match="does not support GroupBy"):
            fold_query(ops, list(DATA), MEMORY_HANDLERS)


# ─── QueryDialect ────────────────────────────────────────────────────────────


class TestQueryDialect:
    def test_fold(self):
        ops = [Filter(Gt(Field("balance"), Const(75.0)))]
        result = MEMORY_DIALECT.fold(ops, list(DATA))
        assert len(result) == 2

    def test_with_handler(self):
        @dataclass(frozen=True, slots=True)
        class CustomOp:
            suffix: str

        def handle_custom(op: CustomOp, data: list[Any]) -> list[Any]:
            return [User(u.id, u.name + op.suffix, u.balance) for u in data]

        dialect = MEMORY_DIALECT.with_handler(CustomOp, handle_custom)
        ops = [CustomOp("!")]
        result = dialect.fold(ops, list(DATA))
        assert all(u.name.endswith("!") for u in result)

    def test_without_handler(self):
        dialect = MEMORY_DIALECT.without_handler(Filter)
        ops = [Filter(Gt(Field("balance"), Const(75.0)))]
        result = dialect.fold(ops, list(DATA))
        assert len(result) == 3  # filter silently skipped

    def test_immutable(self):
        original_handlers = set(MEMORY_DIALECT.handlers.keys())
        _ = MEMORY_DIALECT.without_handler(Filter)
        assert set(MEMORY_DIALECT.handlers.keys()) == original_handlers

    def test_distinct_non_dataclass_hashable(self):
        """Distinct works with non-dataclass hashable items (e.g. strings, ints)."""
        data = ["a", "b", "a", "c", "b"]
        ops = [Distinct()]
        result = fold_query(ops, data, MEMORY_HANDLERS)
        assert result == ["a", "b", "c"]

    def test_custom_context_type(self):
        def handle_filter(op: Filter, ctx: dict) -> dict:
            ctx["filters"] = ctx.get("filters", 0) + 1
            return ctx

        dialect: QueryDialect[dict] = QueryDialect(
            context_type=dict,
            handlers={Filter: handle_filter},
        )
        ops = [
            Filter(Gt(Field("x"), Const(1))),
            Filter(Gt(Field("y"), Const(2))),
        ]
        result = dialect.fold(ops, {})
        assert result["filters"] == 2


# ─── Integration: Fold Complex Pipeline ─────────────────────────────────────


class TestIntegrationFoldComplexPipeline:
    def test_five_op_pipeline(self):
        data = [
            User(1, "alice", 100.0),
            User(2, "bob", 50.0),
            User(3, "charlie", 200.0),
            User(4, "dave", 150.0),
            User(5, "eve", 75.0),
            User(6, "frank", 300.0),
        ]
        ops = [
            Filter(Gt(Field("balance"), Const(60.0))),   # removes bob (50)
            Filter(Gt(Field("balance"), Const(80.0))),   # removes eve (75)
            OrderBy((OrderSpec("balance", ascending=False),)),
            Limit(3),
            Offset(1),
        ]
        result = MEMORY_DIALECT.fold(ops, list(data))
        # After filters: alice(100), charlie(200), dave(150), frank(300)
        # After order desc: frank(300), charlie(200), dave(150), alice(100)
        # After limit 3: frank, charlie, dave
        # After offset 1: charlie, dave
        assert len(result) == 2
        assert result[0].name == "charlie"
        assert result[1].name == "dave"

    def test_custom_handler_mixed_with_standard(self):
        @dataclass(frozen=True, slots=True)
        class DoubleBalance:
            pass

        def handle_double(op: DoubleBalance, data: list) -> list:
            return [User(u.id, u.name, u.balance * 2) for u in data]

        dialect = MEMORY_DIALECT.with_handler(DoubleBalance, handle_double)
        ops = [
            Filter(Gt(Field("balance"), Const(60.0))),
            DoubleBalance(),
            OrderBy((OrderSpec("balance", ascending=True),)),
        ]
        result = dialect.fold(ops, list(DATA))
        # After filter: charlie(200), alice(100) survive (bob 50 removed)
        # After double: charlie(400), alice(200)
        # After order asc: alice(200), charlie(400)
        assert len(result) == 2
        assert result[0].balance == 200.0
        assert result[1].balance == 400.0

    def test_fold_preserves_data_identity_no_ops(self):
        data = list(DATA)
        result = fold_query((), data, MEMORY_HANDLERS)
        assert result == data

    def test_select_then_verify_dict_keys(self):
        ops = [
            Filter(Gt(Field("balance"), Const(60.0))),
            OrderBy((OrderSpec("name", ascending=True),)),
            Select(("id", "name")),
        ]
        result = MEMORY_DIALECT.fold(ops, list(DATA))
        assert all(isinstance(r, dict) for r in result)
        assert all(set(r.keys()) == {"id", "name"} for r in result)
        # Verify order: alice(100), charlie(200)
        assert result[0]["name"] == "alice"
        assert result[1]["name"] == "charlie"

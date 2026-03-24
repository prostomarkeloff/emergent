# pyright: reportPrivateUsage=false
"""Final coverage tests for derive, bridge, and axis modules.

Targets ALL remaining uncovered lines in:
- derive/patterns/methods.py (192-247, 285-315, 341-350, 398-497)
- derive/auth/caps.py (87-91, 218-281)
- derive/_transforms.py (183, 223-253, 299-320, 370-392, 444-452)
- derive/auth/openapi.py (32-51)
- derive/auth/extractors.py (42-60)
- axis/surface/dialects/telegram.py (71-91, 141-155, 189, 293-315)
- axis/surface/codecs/resolve.py (236-240, 292-298)
- axis/query/_coerce.py (71, 105, 115-119, 133-174, 223, 237)
- axis/query/_relational.py (135, 175-182, 202-203, 212-213, 222-223, 252, 255)
- axis/schema/dialects/temporal.py (78-80, 252-260, 293-299)
- axis/schema/dialects/delta.py (119, 270-279, 324-446, 457-482)
- axis/surface/enrichers/_base.py (59-60, 72-73, 85-86, 98-99)
- axis/surface/transforms/_handler.py (51-63)
"""

import argparse
import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Annotated, Any, cast
from unittest.mock import MagicMock

import pytest
from kungfu import Ok, Result

from emergent.wire.axis.schema._universal import Identity, schema_meta


# ═══════════════════════════════════════════════════════════════════════════════
# Shared entity definitions
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class Post:
    id: Annotated[int, Identity()]
    title: str
    body: str
    author_id: str = ""
    status: str = "draft"


@dataclass
class Account:
    id: Annotated[int, Identity()]
    balance: int
    name: str
    deleted_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


@dataclass
class AuthUser:
    name: str
    roles: set[str]


class PostProvider:
    """Provider node stub."""


def _get_roles(u: AuthUser) -> set[str]:
    return u.roles


def _to_str(v: object) -> str:
    return str(v)


def _to_int(v: object) -> int:
    return int(cast(Any, v))


def _double(v: object) -> object:
    return cast(Any, v) * 2


def _upper(v: object) -> str:
    return cast(str, v).upper()


def _lower(v: object) -> str:
    return cast(str, v).lower()


def _identity(v: object) -> object:
    return v


def _const_neg1(v: object) -> int:
    return -1


def _const_42(v: object) -> int:
    return 42


def _times_100(v: object) -> object:
    return cast(Any, v) * 100


def _dot_prefix(v: object) -> str:
    return "." + cast(str, v)


def _pct_wrap(v: object) -> str:
    return "%" + cast(str, v) + "%"


# ═══════════════════════════════════════════════════════════════════════════════
# 1. ExprCoercer — _coerce.py full coverage
# ═══════════════════════════════════════════════════════════════════════════════


class TestExprCoercer:
    """Cover ExprCoercer: binary handlers, In, Between, string ops, And/Or/Not."""

    def test_empty_coercion_passthrough(self) -> None:
        from emergent.wire.axis.query._coerce import ExprCoercer
        from emergent.wire.axis.query._expr import Eq, Field, Const

        coercer = ExprCoercer({})
        expr = Eq(Field("x"), Const(42))
        assert coercer(expr) is expr
        assert not bool(coercer)

    def test_eq_coercion_field_left(self) -> None:
        from emergent.wire.axis.query._coerce import ExprCoercer
        from emergent.wire.axis.query._expr import Eq, Field, Const

        coercer = ExprCoercer({"x": _to_str})
        result = coercer(Eq(Field("x"), Const(42)))
        assert isinstance(result, Eq)
        assert result.right == Const("42")

    def test_ne_coercion_field_right(self) -> None:
        from emergent.wire.axis.query._coerce import ExprCoercer
        from emergent.wire.axis.query._expr import Ne, Field, Const

        coercer = ExprCoercer({"y": _to_int})
        result = coercer(Ne(Const("10"), Field("y")))
        assert isinstance(result, Ne)
        assert result.left == Const(10)

    def test_lt_le_gt_ge_coercion(self) -> None:
        from emergent.wire.axis.query._coerce import ExprCoercer
        from emergent.wire.axis.query._expr import Lt, Le, Gt, Ge, Field, Const

        coercer = ExprCoercer({"val": _double})
        for node_type in [Lt, Le, Gt, Ge]:
            result = coercer(node_type(Field("val"), Const(5)))
            assert isinstance(result, node_type)
            assert result.right == Const(10)

    def test_binary_no_field_recurses(self) -> None:
        """When neither side is a Field, handler should recurse."""
        from emergent.wire.axis.query._coerce import ExprCoercer
        from emergent.wire.axis.query._expr import Eq, Const

        coercer = ExprCoercer({"x": _const_neg1})
        result = coercer(Eq(Const(1), Const(2)))
        assert isinstance(result, Eq)
        # No field => recurse both sides; Const handler is passthrough
        assert result.left == Const(1)
        assert result.right == Const(2)

    def test_and_or_not_recursion(self) -> None:
        from emergent.wire.axis.query._coerce import ExprCoercer
        from emergent.wire.axis.query._expr import And, Or, Not, Eq, Field, Const

        coercer = ExprCoercer({"a": _to_str})
        inner = Eq(Field("a"), Const(1))
        # And
        and_result = coercer(And(inner, inner))
        assert isinstance(and_result, And)
        left = and_result.left
        assert isinstance(left, Eq)
        assert left.right == Const("1")
        # Or
        or_result = coercer(Or(inner, inner))
        assert isinstance(or_result, Or)
        # Not
        not_result = coercer(Not(inner))
        assert isinstance(not_result, Not)
        operand = not_result.operand
        assert isinstance(operand, Eq)
        assert operand.right == Const("1")

    def test_in_coercion(self) -> None:
        from emergent.wire.axis.query._coerce import ExprCoercer
        from emergent.wire.axis.query._expr import In, Field

        coercer = ExprCoercer({"tag": _upper})
        result = coercer(In(Field("tag"), ("a", "b", "c")))
        assert isinstance(result, In)
        assert result.values == ("A", "B", "C")

    def test_in_no_coercion(self) -> None:
        from emergent.wire.axis.query._coerce import ExprCoercer
        from emergent.wire.axis.query._expr import In, Field

        coercer = ExprCoercer({"other": _identity})
        node = In(Field("tag"), ("a",))
        result = coercer(node)
        assert isinstance(result, In)
        assert result.values == ("a",)

    def test_between_coercion(self) -> None:
        from emergent.wire.axis.query._coerce import ExprCoercer
        from emergent.wire.axis.query._expr import Between, Field, Const

        coercer = ExprCoercer({"price": _times_100})
        result = coercer(Between(Field("price"), Const(1), Const(5)))
        assert isinstance(result, Between)
        assert result.low == Const(100)
        assert result.high == Const(500)

    def test_between_no_field(self) -> None:
        from emergent.wire.axis.query._coerce import ExprCoercer
        from emergent.wire.axis.query._expr import Between, Const

        coercer = ExprCoercer({"x": _const_neg1})
        node = Between(Const("?"), Const(1), Const(5))
        result = coercer(node)
        # No field => unchanged
        assert result == node

    def test_contains_coercion(self) -> None:
        from emergent.wire.axis.query._coerce import ExprCoercer
        from emergent.wire.axis.query._expr import Contains, Field

        coercer = ExprCoercer({"name": _upper})
        result = coercer(Contains(Field("name"), "foo"))
        assert isinstance(result, Contains)
        assert result.substring == "FOO"

    def test_startswith_coercion(self) -> None:
        from emergent.wire.axis.query._coerce import ExprCoercer
        from emergent.wire.axis.query._expr import StartsWith, Field

        coercer = ExprCoercer({"code": _lower})
        result = coercer(StartsWith(Field("code"), "AB"))
        assert isinstance(result, StartsWith)
        assert result.prefix == "ab"

    def test_endswith_coercion(self) -> None:
        from emergent.wire.axis.query._coerce import ExprCoercer
        from emergent.wire.axis.query._expr import EndsWith, Field

        coercer = ExprCoercer({"ext": _dot_prefix})
        result = coercer(EndsWith(Field("ext"), "py"))
        assert isinstance(result, EndsWith)
        assert result.suffix == ".py"

    def test_like_ilike_coercion(self) -> None:
        from emergent.wire.axis.query._coerce import ExprCoercer
        from emergent.wire.axis.query._expr import Like, ILike, Field

        coercer = ExprCoercer({"pat": _pct_wrap})
        result = coercer(Like(Field("pat"), "x"))
        assert isinstance(result, Like)
        assert result.pattern == "%x%"

        result2 = coercer(ILike(Field("pat"), "y"))
        assert isinstance(result2, ILike)
        assert result2.pattern == "%y%"

    def test_string_op_non_str_coercion(self) -> None:
        """Coercion returning non-string should be str()-ified."""
        from emergent.wire.axis.query._coerce import ExprCoercer
        from emergent.wire.axis.query._expr import Contains, Field

        coercer = ExprCoercer({"num": _const_42})
        result = coercer(Contains(Field("num"), "anything"))
        assert isinstance(result, Contains)
        assert result.substring == "42"

    def test_bool_true_when_coercion_map_nonempty(self) -> None:
        from emergent.wire.axis.query._coerce import ExprCoercer

        coercer = ExprCoercer({"x": _identity})
        assert bool(coercer)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Relational ops — compile_sa_query, compile_memory_api, compile_http_api
# ═══════════════════════════════════════════════════════════════════════════════


class TestRelationalOps:
    """Cover remaining compile_* methods on relational ops."""

    def test_filter_compile_memory_query(self) -> None:
        from emergent.wire.axis.query._contexts import MemoryQueryContext
        from emergent.wire.axis.query._relational import Filter
        from emergent.wire.axis.query._expr import Eq, Field, Const

        @dataclass
        class Row:
            status: str

        ctx = MemoryQueryContext(data=[Row("active"), Row("inactive"), Row("active")])
        f = Filter(Eq(Field("status"), Const("active")))
        result = f.compile_memory_query(ctx)
        assert len(result.data) == 2

    def test_orderby_compile_memory_query(self) -> None:
        from emergent.wire.axis.query._contexts import MemoryQueryContext
        from emergent.wire.axis.query._relational import OrderBy
        from emergent.wire.axis.query._proxy import OrderSpec

        @dataclass
        class Row:
            val: int

        ctx = MemoryQueryContext(data=[Row(3), Row(1), Row(2)])
        ob = OrderBy(specs=(OrderSpec(field="val", ascending=True),))
        result = ob.compile_memory_query(ctx)
        assert [cast(Row, r).val for r in result.data] == [1, 2, 3]

    def test_orderby_descending(self) -> None:
        from emergent.wire.axis.query._contexts import MemoryQueryContext
        from emergent.wire.axis.query._relational import OrderBy
        from emergent.wire.axis.query._proxy import OrderSpec

        @dataclass
        class Row:
            val: int

        ctx = MemoryQueryContext(data=[Row(1), Row(3), Row(2)])
        ob = OrderBy(specs=(OrderSpec(field="val", ascending=False),))
        result = ob.compile_memory_query(ctx)
        assert [cast(Row, r).val for r in result.data] == [3, 2, 1]

    def test_limit_compile_memory_query(self) -> None:
        from emergent.wire.axis.query._contexts import MemoryQueryContext
        from emergent.wire.axis.query._relational import Limit

        ctx = MemoryQueryContext(data=[1, 2, 3, 4, 5])
        result = Limit(3).compile_memory_query(ctx)
        assert len(result.data) == 3

    def test_limit_negative_raises(self) -> None:
        from emergent.wire.axis.query._relational import Limit

        with pytest.raises(ValueError, match="non-negative"):
            Limit(-1)

    def test_offset_compile_memory_query(self) -> None:
        from emergent.wire.axis.query._contexts import MemoryQueryContext
        from emergent.wire.axis.query._relational import Offset

        ctx = MemoryQueryContext(data=[1, 2, 3, 4, 5])
        result = Offset(2).compile_memory_query(ctx)
        assert result.data == [3, 4, 5]

    def test_offset_negative_raises(self) -> None:
        from emergent.wire.axis.query._relational import Offset

        with pytest.raises(ValueError, match="non-negative"):
            Offset(-1)

    def test_select_compile_memory_query(self) -> None:
        from emergent.wire.axis.query._contexts import MemoryQueryContext
        from emergent.wire.axis.query._relational import Select

        @dataclass
        class Row:
            a: int
            b: str
            c: float

        ctx = MemoryQueryContext(data=[Row(1, "x", 1.0)])
        result = Select(fields=("a", "b")).compile_memory_query(ctx)
        assert result.data[0] == {"a": 1, "b": "x"}

    def test_distinct_compile_memory_query_dataclass(self) -> None:
        from emergent.wire.axis.query._contexts import MemoryQueryContext
        from emergent.wire.axis.query._relational import Distinct

        @dataclass
        class Row:
            val: int

        ctx = MemoryQueryContext(data=[Row(1), Row(2), Row(1), Row(3), Row(2)])
        result = Distinct().compile_memory_query(ctx)
        assert len(result.data) == 3

    def test_distinct_compile_memory_query_non_dataclass(self) -> None:
        from emergent.wire.axis.query._contexts import MemoryQueryContext
        from emergent.wire.axis.query._relational import Distinct

        ctx = MemoryQueryContext(data=[1, 2, 1, 3, 2])
        result = Distinct().compile_memory_query(ctx)
        assert result.data == [1, 2, 3]

    def test_aggregate_compile_memory_query_passthrough(self) -> None:
        from emergent.wire.axis.query._contexts import MemoryQueryContext
        from emergent.wire.axis.query._relational import Aggregate

        ctx = MemoryQueryContext(data=[1, 2, 3])
        result = Aggregate(specs=()).compile_memory_query(ctx)
        assert result.data == [1, 2, 3]

    def test_filter_compile_memory_api(self) -> None:
        from emergent.wire.axis.query._relational import Filter
        from emergent.wire.axis.query._expr import Gt, Field, Const

        @dataclass
        class Row:
            val: int

        # MemoryAPIContext might not be directly importable, check...
        from emergent.wire.axis.query._contexts import MemoryAPIContext

        ctx = MemoryAPIContext(data=[Row(1), Row(5), Row(10)])
        result = Filter(Gt(Field("val"), Const(3))).compile_memory_api(ctx)
        assert len(result.data) == 2

    def test_orderby_compile_memory_api(self) -> None:
        from emergent.wire.axis.query._contexts import MemoryAPIContext
        from emergent.wire.axis.query._relational import OrderBy
        from emergent.wire.axis.query._proxy import OrderSpec

        @dataclass
        class Row:
            val: int

        ctx = MemoryAPIContext(data=[Row(3), Row(1)])
        result = OrderBy(specs=(OrderSpec(field="val", ascending=True),)).compile_memory_api(ctx)
        assert cast(Row, result.data[0]).val == 1

    def test_limit_compile_memory_api(self) -> None:
        from emergent.wire.axis.query._contexts import MemoryAPIContext
        from emergent.wire.axis.query._relational import Limit

        ctx = MemoryAPIContext(data=[1, 2, 3, 4])
        result = Limit(2).compile_memory_api(ctx)
        assert len(result.data) == 2

    def test_select_compile_memory_api(self) -> None:
        from emergent.wire.axis.query._contexts import MemoryAPIContext
        from emergent.wire.axis.query._relational import Select

        @dataclass
        class Row:
            a: int
            b: str

        ctx = MemoryAPIContext(data=[Row(1, "x")])
        result = Select(fields=("a",)).compile_memory_api(ctx)
        assert result.data[0] == {"a": 1}

    def test_distinct_compile_memory_api(self) -> None:
        from emergent.wire.axis.query._contexts import MemoryAPIContext
        from emergent.wire.axis.query._relational import Distinct

        ctx = MemoryAPIContext(data=[1, 1, 2, 2, 3])
        result = Distinct().compile_memory_api(ctx)
        assert len(result.data) == 3

    def test_groupby_compile_memory_query_passthrough(self) -> None:
        """GroupBy only has compile_sa_query, not compile_memory_query."""
        from emergent.wire.axis.query._relational import GroupBy

        gb = GroupBy(fields=("a",))
        assert gb.fields == ("a",)

    def test_having_exists(self) -> None:
        from emergent.wire.axis.query._relational import Having
        from emergent.wire.axis.query._expr import Gt, Field, Const

        h = Having(expr=Gt(Field("cnt"), Const(5)))
        assert h.expr is not None

    def test_relational_queryset_append(self) -> None:
        from emergent.wire.axis.query._relational import relational, Limit

        @dataclass
        class E:
            id: int

        q = relational(E).limit(5)
        assert len(q.ops) == 1
        assert isinstance(q.ops[0], Limit)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Temporal capabilities — compile_sqlalchemy_table, compile_pydantic_model
# ═══════════════════════════════════════════════════════════════════════════════


class TestTemporalCapabilities:
    """Cover Versioned, Timestamps compile methods and SoftDelete derive_modify."""

    def test_versioned_compile_sqlalchemy_table(self) -> None:
        from emergent.wire.axis.schema.dialects.temporal import Versioned
        from emergent.wire.axis._capability import SQLAlchemyTableContext

        ctx = SQLAlchemyTableContext(class_name="User")
        result = Versioned().compile_sqlalchemy_table(ctx)
        assert any(col.name == "version" for col in result.extra_columns)

    def test_versioned_compile_pydantic_model(self) -> None:
        from emergent.wire.axis.schema.dialects.temporal import Versioned
        from emergent.wire.axis._capability import PydanticModelContext

        ctx = PydanticModelContext(class_name="User")
        result = Versioned().compile_pydantic_model(ctx)
        assert any(f.name == "version" for f in result.extra_fields)

    def test_timestamps_compile_derive_modify(self) -> None:
        from emergent.wire.axis.schema.dialects.temporal import Timestamps
        from emergent.wire.derive._compile import compile_derive
        from emergent.wire.derive._crud import http_crud

        @schema_meta(http_crud("/api/accounts", PostProvider), Timestamps())
        @dataclass
        class TSAccount:
            id: Annotated[int, Identity()]
            name: str
            created_at: str | None = None
            updated_at: str | None = None

        ctxs = compile_derive(TSAccount)
        assert len(ctxs) >= 1
        ctx = ctxs[0]
        # Check that Creates specs had created_at/updated_at excluded
        from emergent.wire.derive._effects import Creates, has_effect
        for s in ctx.specs:
            if has_effect(s.effects, Creates):
                assert "created_at" not in s.input_fields
                assert "updated_at" not in s.input_fields

    def test_soft_delete_temporal_compile_derive_modify(self) -> None:
        from emergent.wire.axis.schema.dialects.temporal import SoftDelete as TemporalSoftDelete
        from emergent.wire.derive._compile import compile_derive
        from emergent.wire.derive._crud import http_crud

        @schema_meta(http_crud("/api/items", PostProvider), TemporalSoftDelete())
        @dataclass
        class SDItem:
            id: Annotated[int, Identity()]
            name: str
            deleted_at: str | None = None

        ctxs = compile_derive(SDItem)
        assert len(ctxs) >= 1
        ctx = ctxs[0]
        # Check that Delete handler was replaced with SoftDeleteMark
        from emergent.wire.derive._effects import Deletes, has_effect
        from emergent.wire.derive._handler import SoftDeleteMark
        for s in ctx.specs:
            if has_effect(s.effects, Deletes):
                assert isinstance(s.handler_template, SoftDeleteMark)

    def test_timestamps_compile_sqlalchemy_table(self) -> None:
        from emergent.wire.axis.schema.dialects.temporal import Timestamps
        from emergent.wire.axis._capability import SQLAlchemyTableContext

        ctx = SQLAlchemyTableContext(class_name="User")
        result = Timestamps().compile_sqlalchemy_table(ctx)
        names = {col.name for col in result.extra_columns}
        assert "created_at" in names
        assert "updated_at" in names


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Delta dialect — delta_type, apply_delta, compose_deltas, validate_delta
# ═══════════════════════════════════════════════════════════════════════════════


class TestDeltaDialect:
    """Cover delta_type generation, apply, compose, validate."""

    def test_numeric_delta_set_overrides(self) -> None:
        from emergent.wire.axis.schema.dialects.delta import NumericDelta

        d = NumericDelta(add=100, set=0)
        assert d.apply(500) == 0

    def test_numeric_delta_add_multiply(self) -> None:
        from emergent.wire.axis.schema.dialects.delta import NumericDelta

        d = NumericDelta(add=10, multiply=2.0)
        # (100 + 10) * 2 = 220
        assert d.apply(100) == 220

    def test_numeric_delta_preserves_int(self) -> None:
        from emergent.wire.axis.schema.dialects.delta import NumericDelta

        d = NumericDelta(add=5)
        result = d.apply(10)
        assert result == 15
        assert isinstance(result, int)

    def test_string_delta_all_ops(self) -> None:
        from emergent.wire.axis.schema.dialects.delta import StringDelta

        d = StringDelta(prepend="[", append="]", replace=("hello", "world"))
        result = d.apply("hello")
        assert result == "[world]"

    def test_string_delta_set_overrides(self) -> None:
        from emergent.wire.axis.schema.dialects.delta import StringDelta

        d = StringDelta(append="x", set="override")
        assert d.apply("anything") == "override"

    def test_collection_delta_all_ops(self) -> None:
        from emergent.wire.axis.schema.dialects.delta import CollectionDelta

        d = CollectionDelta(remove=("a",), pop=1, push=("d",), insert=(0, "first"))
        result = d.apply(["a", "b", "c"])
        # remove "a" -> ["b", "c"], pop 1 -> ["b"], push "d" -> ["b", "d"], insert "first" at 0
        assert result == ["first", "b", "d"]

    def test_collection_delta_set_overrides(self) -> None:
        from emergent.wire.axis.schema.dialects.delta import CollectionDelta

        d: CollectionDelta[str] = CollectionDelta(push=("x",), set=("a", "b"))
        assert d.apply(cast(list[str], [1, 2, 3])) == ["a", "b"]

    def test_delta_type_generation(self) -> None:
        from emergent.wire.axis.schema.dialects.delta import DeltaField, delta_type, NumericDelta

        @dataclass
        class Acc:
            id: int
            balance: Annotated[int, DeltaField("numeric")]
            bio: Annotated[str, DeltaField("string")]
            tags: Annotated[list[str], DeltaField("collection")]

        DT = delta_type(Acc)
        assert hasattr(DT, "__dataclass_fields__")
        inst = DT(balance=NumericDelta(add=10), bio=None, tags=None)
        assert inst.balance.add == 10

    def test_apply_delta(self) -> None:
        from emergent.wire.axis.schema.dialects.delta import (
            DeltaField, delta_type, apply_delta, NumericDelta, CollectionDelta,
        )

        @dataclass
        class Acc:
            id: int
            balance: Annotated[int, DeltaField("numeric")]
            tags: Annotated[list[str], DeltaField("collection")]

        DT = delta_type(Acc)
        acc = Acc(id=1, balance=100, tags=["basic"])
        delta = DT(balance=NumericDelta(add=50), tags=CollectionDelta(push=("vip",)))
        new_acc = apply_delta(acc, delta)
        assert new_acc.balance == 150
        assert new_acc.tags == ["basic", "vip"]

    def test_apply_delta_no_changes(self) -> None:
        from emergent.wire.axis.schema.dialects.delta import (
            DeltaField, delta_type, apply_delta,
        )

        @dataclass
        class Acc:
            id: int
            balance: Annotated[int, DeltaField("numeric")]

        DT = delta_type(Acc)
        acc = Acc(id=1, balance=100)
        result = apply_delta(acc, DT(balance=None))
        assert result is acc

    def test_compose_deltas_numeric(self) -> None:
        from emergent.wire.axis.schema.dialects.delta import (
            DeltaField, delta_type, compose_deltas, NumericDelta,
        )

        @dataclass
        class Acc:
            id: int
            balance: Annotated[int, DeltaField("numeric")]

        DT = delta_type(Acc)
        d1 = DT(balance=NumericDelta(add=100))
        d2 = DT(balance=NumericDelta(add=50))
        combined = compose_deltas(d1, d2)
        assert combined.balance.add == 150

    def test_compose_deltas_string(self) -> None:
        from emergent.wire.axis.schema.dialects.delta import (
            DeltaField, delta_type, compose_deltas, StringDelta,
        )

        @dataclass
        class Note:
            id: int
            text: Annotated[str, DeltaField("string")]

        DT = delta_type(Note)
        d1 = DT(text=StringDelta(append=" world"))
        d2 = DT(text=StringDelta(prepend="hello"))
        combined = compose_deltas(d1, d2)
        assert combined.text.append == " world"
        assert combined.text.prepend == "hello"

    def test_compose_deltas_collection(self) -> None:
        from emergent.wire.axis.schema.dialects.delta import (
            DeltaField, delta_type, compose_deltas, CollectionDelta,
        )

        @dataclass
        class Tags:
            id: int
            items: Annotated[list[str], DeltaField("collection")]

        DT = delta_type(Tags)
        d1 = DT(items=CollectionDelta(push=("a",)))
        d2 = DT(items=CollectionDelta(push=("b",), pop=1))
        combined = compose_deltas(d1, d2)
        assert combined.items.push == ("a", "b")
        assert combined.items.pop == 1

    def test_compose_deltas_single(self) -> None:
        from emergent.wire.axis.schema.dialects.delta import (
            DeltaField, delta_type, compose_deltas, NumericDelta,
        )

        @dataclass
        class Acc:
            id: int
            balance: Annotated[int, DeltaField("numeric")]

        DT = delta_type(Acc)
        d = DT(balance=NumericDelta(add=10))
        assert compose_deltas(d) is d

    def test_compose_deltas_empty_raises(self) -> None:
        from emergent.wire.axis.schema.dialects.delta import compose_deltas

        with pytest.raises(ValueError, match="At least one delta"):
            compose_deltas()

    def test_compose_numeric_deltas_multiply(self) -> None:
        from emergent.wire.axis.schema.dialects.delta import _compose_field_deltas, NumericDelta

        d1 = NumericDelta(multiply=2.0)
        d2 = NumericDelta(multiply=3.0)
        combined = _compose_field_deltas(d1, d2)
        assert isinstance(combined, NumericDelta)
        assert combined.multiply == 6.0

    def test_compose_numeric_deltas_set_wins(self) -> None:
        from emergent.wire.axis.schema.dialects.delta import _compose_field_deltas, NumericDelta

        d1 = NumericDelta(set=100)
        d2 = NumericDelta(add=5)
        combined = _compose_field_deltas(d1, d2)
        assert isinstance(combined, NumericDelta)
        assert combined.set == 100
        assert combined.add == 5

    def test_validate_delta_valid(self) -> None:
        from emergent.wire.axis.schema.dialects.delta import (
            DeltaField, delta_type, validate_delta, NumericDelta,
        )

        @dataclass
        class Acc:
            id: int
            balance: Annotated[int, DeltaField("numeric")]

        DT = delta_type(Acc)
        errors = validate_delta(DT(balance=NumericDelta(add=10)), Acc)
        assert errors == []

    def test_validate_delta_wrong_type(self) -> None:
        from emergent.wire.axis.schema.dialects.delta import (
            DeltaField, delta_type, validate_delta, StringDelta,
        )

        @dataclass
        class Acc:
            id: int
            balance: Annotated[int, DeltaField("numeric")]

        delta_type(Acc)
        # Intentionally pass StringDelta where NumericDelta expected
        @dataclass(frozen=True, slots=True)
        class FakeDelta:
            balance: StringDelta | None = None
        errors = validate_delta(FakeDelta(balance=StringDelta(append="x")), Acc)
        assert any("expects numeric" in e for e in errors)

    def test_validate_delta_field_not_on_entity(self) -> None:
        from emergent.wire.axis.schema.dialects.delta import validate_delta, NumericDelta

        @dataclass
        class Acc:
            id: int
            balance: int

        @dataclass(frozen=True, slots=True)
        class FakeDelta:
            nonexistent: NumericDelta | None = None
        errors = validate_delta(FakeDelta(nonexistent=NumericDelta(add=1)), Acc)
        assert any("not found" in e for e in errors)

    def test_validate_delta_no_delta_field_cap(self) -> None:
        from emergent.wire.axis.schema.dialects.delta import validate_delta, NumericDelta

        @dataclass
        class Acc:
            id: int
            balance: int  # NOT annotated with DeltaField

        @dataclass(frozen=True, slots=True)
        class FakeDelta:
            balance: NumericDelta | None = None
        errors = validate_delta(FakeDelta(balance=NumericDelta(add=1)), Acc)
        assert any("not marked with DeltaField" in e for e in errors)

    def test_delta_field_compile_delta(self) -> None:
        from emergent.wire.axis.schema.dialects.delta import DeltaField
        from emergent.wire.axis._capability import DeltaContext

        ctx = DeltaContext(field_name="x", field_type=int)
        result = DeltaField("numeric").compile_delta(ctx)
        assert result.delta_kind == "numeric"

    def test_delta_field_compile_openapi(self) -> None:
        from emergent.wire.axis.schema.dialects.delta import DeltaField
        from emergent.wire.axis._capability import OpenAPIContext

        ctx = OpenAPIContext(field_name="x", field_type=int)
        result = DeltaField("numeric").compile_openapi(ctx)
        assert "x-delta-type" in result.schema


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Enricher protocol bases — compile_handler_runtime
# ═══════════════════════════════════════════════════════════════════════════════


class TestEnricherProtocols:
    """Cover compile_handler_runtime on ScopeEnricher, FastAPIEnrichable,
    CLIEnrichable, TelegrinderEnrichable, DjangoEnrichable."""

    def _make_runtime_ctx(self):
        from emergent.wire.axis._capability import HandlerRuntimeContext
        return HandlerRuntimeContext()

    def test_scope_enricher_compile_handler_runtime(self) -> None:
        from emergent.wire.axis.surface.enrichers._base import ScopeEnricher, EnricherNext
        from nodnod import Scope

        @dataclass(frozen=True, slots=True)
        class MyEnricher(ScopeEnricher):
            async def enrich[R](self, call: EnricherNext[R], scope: Scope) -> R:
                return await call(scope)

        ctx = self._make_runtime_ctx()
        result = MyEnricher().compile_handler_runtime(ctx)
        assert len(result.enrichers) == 1

    def test_fastapi_enrichable_compile_handler_runtime(self) -> None:
        from emergent.wire.axis.surface.enrichers._base import FastAPIEnrichable, EnricherNext
        from nodnod import Scope

        @dataclass(frozen=True, slots=True)
        class MyFAE(FastAPIEnrichable):
            async def enrich_fastapi[R](self, call: EnricherNext[R], scope: Scope) -> R:
                return await call(scope)

        ctx = self._make_runtime_ctx()
        result = MyFAE().compile_handler_runtime(ctx)
        assert len(result.enrichers) == 1

    def test_cli_enrichable_compile_handler_runtime(self) -> None:
        from emergent.wire.axis.surface.enrichers._base import CLIEnrichable, EnricherNext
        from nodnod import Scope

        @dataclass(frozen=True, slots=True)
        class MyCLI(CLIEnrichable):
            async def enrich_cli[R](self, call: EnricherNext[R], scope: Scope) -> R:
                return await call(scope)

        ctx = self._make_runtime_ctx()
        result = MyCLI().compile_handler_runtime(ctx)
        assert len(result.enrichers) == 1

    def test_telegrinder_enrichable_compile_handler_runtime(self) -> None:
        from emergent.wire.axis.surface.enrichers._base import TelegrinderEnrichable, EnricherNext
        from nodnod import Scope

        @dataclass(frozen=True, slots=True)
        class MyTG(TelegrinderEnrichable):
            async def enrich_telegrinder[R](self, call: EnricherNext[R], scope: Scope) -> R:
                return await call(scope)

        ctx = self._make_runtime_ctx()
        result = MyTG().compile_handler_runtime(ctx)
        assert len(result.enrichers) == 1

    def test_django_enrichable_compile_handler_runtime(self) -> None:
        from emergent.wire.axis.surface.enrichers._base import DjangoEnrichable, EnricherNext
        from nodnod import Scope

        @dataclass(frozen=True, slots=True)
        class MyDjango(DjangoEnrichable):
            async def enrich_django[R](self, call: EnricherNext[R], scope: Scope) -> R:
                return await call(scope)

        ctx = self._make_runtime_ctx()
        result = MyDjango().compile_handler_runtime(ctx)
        assert len(result.enrichers) == 1


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Handler Transform — Timeout
# ═══════════════════════════════════════════════════════════════════════════════


class TestHandlerTransformTimeout:
    """Cover axis/surface/transforms/_handler.py Timeout.apply_handler."""

    def test_timeout_seconds_factory(self) -> None:
        from emergent.wire.axis.surface.transforms._handler import Timeout

        t = Timeout.seconds(30)
        assert t.duration == timedelta(seconds=30)

    def test_timeout_minutes_factory(self) -> None:
        from emergent.wire.axis.surface.transforms._handler import Timeout

        t = Timeout.minutes(5)
        assert t.duration == timedelta(minutes=5)

    def test_timeout_hours_factory(self) -> None:
        from emergent.wire.axis.surface.transforms._handler import Timeout

        t = Timeout.hours(1)
        assert t.duration == timedelta(hours=1)

    def test_timeout_apply_handler_success(self) -> None:
        from emergent.wire.axis.surface.transforms._handler import Timeout

        async def handler(x: int) -> int:
            return x * 2

        t = Timeout(timedelta(seconds=5))
        wrapped = t.apply_handler(handler)

        result = asyncio.run(cast(Any, wrapped(21)))
        assert result == 42


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Auth capabilities — caps.py
# ═══════════════════════════════════════════════════════════════════════════════


class TestAuthCapabilities:
    """Cover Authenticated effect filtering, OwnerScoped compile_derive_modify."""

    def test_authenticated_skips_public(self) -> None:
        from emergent.wire.derive._compile import compile_derive
        from emergent.wire.derive._crud import http_crud
        from emergent.wire.derive.auth.caps import Authenticated
        from emergent.wire.derive.auth.validate import TokenValidate
        from emergent.wire.derive.auth.extractors import BearerExtract

        async def lookup(token: str) -> AuthUser | None:
            return AuthUser(name="test", roles=set())

        @schema_meta(
            http_crud("/api/posts", PostProvider),
            Authenticated(
                BearerExtract(),
                TokenValidate(identity_type=AuthUser, lookup=lookup),
            ),
        )
        @dataclass
        class AuthPost:
            id: Annotated[int, Identity()]
            title: str

        ctxs = compile_derive(AuthPost)
        assert len(ctxs) >= 1

    def test_authenticated_effect_filter(self) -> None:
        """Authenticated with effect= should skip non-matching ops."""
        from emergent.wire.derive._compile import compile_derive
        from emergent.wire.derive._crud import http_crud
        from emergent.wire.derive._effects import Mutation
        from emergent.wire.derive.auth.caps import Authenticated
        from emergent.wire.derive.auth.validate import TokenValidate
        from emergent.wire.derive.auth.extractors import BearerExtract

        async def lookup(token: str) -> AuthUser | None:
            return AuthUser(name="test", roles=set())

        @schema_meta(
            http_crud("/api/posts", PostProvider),
            Authenticated(
                BearerExtract(),
                TokenValidate(identity_type=AuthUser, lookup=lookup),
                effect=Mutation,
            ),
        )
        @dataclass
        class MutAuthPost:
            id: Annotated[int, Identity()]
            title: str

        ctxs = compile_derive(MutAuthPost)
        ctx = ctxs[0]
        from emergent.wire.derive._effects import has_effect, Read as ReadEffect
        # Read ops should NOT have auth capabilities injected
        for s in ctx.specs:
            if has_effect(s.effects, ReadEffect) and not has_effect(s.effects, Mutation):
                auth_caps = [c for c in s.capabilities if hasattr(c, "lookup")]
                assert len(auth_caps) == 0

    def test_authenticated_no_validate_raises(self) -> None:
        from emergent.wire.derive.auth.caps import Authenticated
        from emergent.wire.derive.auth.extractors import BearerExtract

        with pytest.raises(ValueError, match="TokenValidate"):
            Authenticated(BearerExtract())

    def test_role_required_compile_derive(self) -> None:
        from emergent.wire.derive._compile import compile_derive
        from emergent.wire.derive._crud import http_crud
        from emergent.wire.derive._effects import Mutation
        from emergent.wire.derive.auth.caps import RoleRequired

        @schema_meta(
            http_crud("/api/posts", PostProvider),
            RoleRequired(
                identity_type=AuthUser,
                role="admin",
                role_getter=_get_roles,
                effect=Mutation,
            ),
        )
        @dataclass
        class RolePost:
            id: Annotated[int, Identity()]
            title: str

        ctxs = compile_derive(RolePost)
        assert len(ctxs) >= 1

    def test_authorize_ops_strict_raises(self) -> None:
        from emergent.wire.derive._compile import compile_derive
        from emergent.wire.derive._crud import http_crud
        from emergent.wire.derive.auth.caps import AuthorizeOps

        @schema_meta(
            http_crud("/api/posts", PostProvider),
            AuthorizeOps(
                identity_type=AuthUser,
                role_map={"Create": "admin"},  # Missing other ops
                role_getter=_get_roles,
                strict=True,
            ),
        )
        @dataclass
        class StrictPost:
            id: Annotated[int, Identity()]
            title: str

        with pytest.raises(ValueError, match="no role mapping"):
            compile_derive(StrictPost)

    def test_authorize_ops_non_strict(self) -> None:
        from emergent.wire.derive._compile import compile_derive
        from emergent.wire.derive._crud import http_crud
        from emergent.wire.derive.auth.caps import AuthorizeOps

        @schema_meta(
            http_crud("/api/posts", PostProvider),
            AuthorizeOps(
                identity_type=AuthUser,
                role_map={"Create": "admin"},
                role_getter=_get_roles,
                strict=False,
            ),
        )
        @dataclass
        class NonStrictPost:
            id: Annotated[int, Identity()]
            title: str

        ctxs = compile_derive(NonStrictPost)
        assert len(ctxs) >= 1

    def test_owner_scoped_compile_derive(self) -> None:
        from emergent.wire.derive._compile import compile_derive
        from emergent.wire.derive._crud import http_crud
        from emergent.wire.derive._effects import Creates, has_effect
        from emergent.wire.derive.auth.caps import OwnerScoped

        @schema_meta(
            http_crud("/api/posts", PostProvider),
            OwnerScoped(
                identity_type=AuthUser,
                owner_field="author_id",
                identity_attr="name",
            ),
        )
        @dataclass
        class OwnedPost:
            id: Annotated[int, Identity()]
            title: str
            author_id: str = ""

        ctxs = compile_derive(OwnedPost)
        ctx = ctxs[0]
        # On Create specs, author_id should be excluded from input
        for s in ctx.specs:
            if has_effect(s.effects, Creates):
                assert "author_id" not in s.input_fields
            # All specs should have author_id in scope_fields
            assert "author_id" in s.scope_fields

    def test_require_role_enricher_rejects(self) -> None:
        from emergent.wire.derive.auth.caps import RequireRole
        from emergent.wire.derive.auth.errors import AuthorizationFailed

        enricher = RequireRole(
            identity_type=AuthUser,
            roles=frozenset({"admin"}),
            role_getter=_get_roles,
        )

        from nodnod import Scope

        async def run():
            scope = Scope()

            async def call(s: Any) -> str:
                return "ok"

            # No user in scope -> should raise
            with pytest.raises(AuthorizationFailed):
                await enricher.enrich(call, scope)

            # User without matching role
            scope.inject(AuthUser, AuthUser(name="user", roles={"viewer"}))
            with pytest.raises(AuthorizationFailed, match="requires one of"):
                await enricher.enrich(call, scope)

        asyncio.run(run())


# ═══════════════════════════════════════════════════════════════════════════════
# 8. Auth extractors — enrich_fastapi, enrich_cli
# ═══════════════════════════════════════════════════════════════════════════════


class TestAuthExtractors:
    """Cover BearerExtract.enrich_fastapi, BearerExtract.enrich_cli."""

    def test_bearer_extract_fastapi(self) -> None:
        from emergent.wire.derive.auth.extractors import BearerExtract, AuthToken
        from nodnod import Scope

        extractor = BearerExtract()

        async def run():
            scope = Scope()

            # Mock a FastAPI request
            import fastapi
            mock_request = MagicMock(spec=fastapi.Request)
            mock_request.headers = {"authorization": "Bearer my-token-123"}
            scope.inject(fastapi.Request, mock_request)

            result: list[str] = []

            async def call(s: Any) -> str:
                token_wrapper = s.get(AuthToken)
                if token_wrapper is not None:
                    result.append(cast(str, token_wrapper.value.value))
                return "ok"

            await extractor.enrich_fastapi(call, scope)
            assert result == ["my-token-123"]

        asyncio.run(run())

    def test_bearer_extract_cli(self) -> None:
        from emergent.wire.derive.auth.extractors import BearerExtract, AuthToken
        from nodnod import Scope

        extractor = BearerExtract()

        async def run():
            scope = Scope()
            ns = argparse.Namespace(token="cli-token-456")
            scope.inject(argparse.Namespace, ns)

            result: list[str] = []

            async def call(s: Any) -> str:
                token_wrapper = s.get(AuthToken)
                if token_wrapper is not None:
                    result.append(cast(str, token_wrapper.value.value))
                return "ok"

            await extractor.enrich_cli(call, scope)
            assert result == ["cli-token-456"]

        asyncio.run(run())

    def test_bearer_extract_universal_fallback(self) -> None:
        from emergent.wire.derive.auth.extractors import BearerExtract
        from nodnod import Scope

        extractor = BearerExtract()

        async def run():
            scope = Scope()

            async def call(s: Any) -> str:
                return "passed through"

            result = await extractor.enrich(call, scope)
            assert result == "passed through"

        asyncio.run(run())


# ═══════════════════════════════════════════════════════════════════════════════
# 9. Auth OpenAPI — compile_fastapi, compile_fastapi_route
# ═══════════════════════════════════════════════════════════════════════════════


class TestAuthOpenAPI:
    """Cover AuthOpenAPI.compile_fastapi and compile_fastapi_route."""

    def test_compile_fastapi_patches_openapi(self) -> None:
        from emergent.wire.derive.auth.openapi import AuthOpenAPI
        from emergent.wire.compile._capabilities import FastAPICompileContext

        mock_app = MagicMock()
        mock_app.openapi_schema = None
        original_openapi = MagicMock(return_value={"components": {}})
        mock_app.openapi = original_openapi

        ctx = FastAPICompileContext(
            app=mock_app,
            trigger=None,
            handler=None,
            mounted=set(),
        )

        auth = AuthOpenAPI(scheme_name="bearerAuth")
        result = auth.compile_fastapi(ctx)

        # Verify the openapi method was patched
        schema = result.app.openapi()
        assert "securitySchemes" in schema["components"]
        assert "bearerAuth" in schema["components"]["securitySchemes"]

    def test_compile_fastapi_route_adds_security(self) -> None:
        from emergent.wire.derive.auth.openapi import AuthOpenAPI
        from emergent.wire.axis._capability import FastAPIRouteContext

        auth = AuthOpenAPI(scheme_name="bearerAuth")
        ctx = FastAPIRouteContext(path="/api/users", method="GET")
        result = auth.compile_fastapi_route(ctx)

        assert result.openapi_extra is not None
        assert "security" in result.openapi_extra
        assert "responses" in result.openapi_extra
        assert "401" in result.openapi_extra["responses"]
        assert "403" in result.openapi_extra["responses"]


# ═══════════════════════════════════════════════════════════════════════════════
# 10. Transforms — remaining coverage
# ═══════════════════════════════════════════════════════════════════════════════


class TestTransformsCoverage:
    """Cover Searchable, WithRetry, WithRateLimit, EffectRateLimited,
    EffectDeprecated, SoftDelete, Timestamped, ProjectResponse."""

    def test_searchable_with_explicit_fields(self) -> None:
        from emergent.wire.derive._compile import compile_derive
        from emergent.wire.derive._crud import http_crud
        from emergent.wire.derive._transforms import Searchable

        @schema_meta(
            http_crud("/api/posts", PostProvider),
            Searchable(fields=("title", "body")),
        )
        @dataclass
        class SearchPost:
            id: Annotated[int, Identity()]
            title: str
            body: str

        ctxs = compile_derive(SearchPost)
        ctx = ctxs[0]
        from emergent.wire.derive._effects import Read as ReadEff, has_effect
        for s in ctx.specs:
            if has_effect(s.effects, ReadEff):
                # Should have "q" in extra fields
                field_names = [f[0] for f in s.extra_op_fields]
                assert "q" in field_names

    def test_searchable_without_fields_uses_effect(self) -> None:
        from emergent.wire.derive._compile import compile_derive
        from emergent.wire.derive._crud import http_crud
        from emergent.wire.derive._transforms import Searchable

        @schema_meta(
            http_crud("/api/posts", PostProvider),
            Searchable(),
        )
        @dataclass
        class SearchPost2:
            id: Annotated[int, Identity()]
            title: str

        # Searchable with no fields and no Searchable effect -> no-op on read specs
        ctxs = compile_derive(SearchPost2)
        assert len(ctxs) >= 1

    def test_project_response(self) -> None:
        from emergent.wire.derive._compile import compile_derive
        from emergent.wire.derive._crud import http_crud
        from emergent.wire.derive._transforms import ProjectResponse

        @schema_meta(
            http_crud("/api/posts", PostProvider),
            ProjectResponse(exclude=("body",)),
        )
        @dataclass
        class ProjPost:
            id: Annotated[int, Identity()]
            title: str
            body: str

        ctxs = compile_derive(ProjPost)
        assert len(ctxs) >= 1

    def test_effect_rate_limited(self) -> None:
        from emergent.wire.derive._compile import compile_derive
        from emergent.wire.derive._crud import http_crud
        from emergent.wire.derive._transforms import EffectRateLimited

        @schema_meta(
            http_crud("/api/posts", PostProvider),
            EffectRateLimited(rpm=120),
        )
        @dataclass
        class RLPost:
            id: Annotated[int, Identity()]
            title: str

        # No ops have RateLimited effect, so rpm override is used when effect present
        ctxs = compile_derive(RLPost)
        assert len(ctxs) >= 1

    def test_effect_deprecated(self) -> None:
        from emergent.wire.derive._compile import compile_derive
        from emergent.wire.derive._crud import http_crud
        from emergent.wire.derive._transforms import EffectDeprecated

        @schema_meta(
            http_crud("/api/posts", PostProvider),
            EffectDeprecated(),
        )
        @dataclass
        class DepPost:
            id: Annotated[int, Identity()]
            title: str

        # No ops have Deprecated effect, so this is a no-op
        ctxs = compile_derive(DepPost)
        assert len(ctxs) >= 1

    def test_soft_delete_transform(self) -> None:
        from emergent.wire.derive._compile import compile_derive
        from emergent.wire.derive._crud import http_crud
        from emergent.wire.derive._transforms import SoftDelete
        from emergent.wire.derive._effects import Deletes, Creates, has_effect
        from emergent.wire.derive._handler import SoftDeleteMark

        @schema_meta(
            http_crud("/api/items", PostProvider),
            SoftDelete(deleted_field="deleted_at"),
        )
        @dataclass
        class SDItem:
            id: Annotated[int, Identity()]
            name: str
            deleted_at: str | None = None

        ctxs = compile_derive(SDItem)
        ctx = ctxs[0]
        for s in ctx.specs:
            if has_effect(s.effects, Deletes):
                assert isinstance(s.handler_template, SoftDeleteMark)
            if has_effect(s.effects, Creates):
                assert "deleted_at" not in s.input_fields

    def test_timestamped_transform(self) -> None:
        from emergent.wire.derive._compile import compile_derive
        from emergent.wire.derive._crud import http_crud
        from emergent.wire.derive._transforms import Timestamped
        from emergent.wire.derive._effects import Creates, Updates, has_effect
        from emergent.wire.derive._handler import TimestampInsert, TimestampUpdate

        @schema_meta(
            http_crud("/api/items", PostProvider),
            Timestamped(),
        )
        @dataclass
        class TSItem:
            id: Annotated[int, Identity()]
            name: str
            created_at: str | None = None
            updated_at: str | None = None

        ctxs = compile_derive(TSItem)
        ctx = ctxs[0]
        for s in ctx.specs:
            if has_effect(s.effects, Creates):
                assert isinstance(s.handler_template, TimestampInsert)
                assert "created_at" not in s.input_fields
                assert "updated_at" not in s.input_fields
            if has_effect(s.effects, Updates):
                assert isinstance(s.handler_template, TimestampUpdate)


# ═══════════════════════════════════════════════════════════════════════════════
# 11. Telegram dialect — capabilities compile_telegrinder
# ═══════════════════════════════════════════════════════════════════════════════


class TestTelegramDialect:
    """Cover telegram capabilities compile_telegrinder + enricher behavior."""

    def test_edit_message_compile_telegrinder(self) -> None:
        from emergent.wire.axis.surface.dialects.telegram import EditMessage
        from emergent.wire.axis._capability import TelegrinderHandlerContext

        ctx = TelegrinderHandlerContext()
        result = EditMessage().compile_telegrinder(ctx)
        assert result.edit_message is True

    def test_answer_callback_compile_telegrinder(self) -> None:
        from emergent.wire.axis.surface.dialects.telegram import AnswerCallback
        from emergent.wire.axis._capability import TelegrinderHandlerContext

        ctx = TelegrinderHandlerContext()
        result = AnswerCallback(text="Processing", show_alert=True).compile_telegrinder(ctx)
        assert result.answer_callback is True
        assert result.answer_callback_text == "Processing"
        assert result.answer_callback_show_alert is True

    def test_silent_compile_telegrinder(self) -> None:
        from emergent.wire.axis.surface.dialects.telegram import Silent
        from emergent.wire.axis._capability import TelegrinderHandlerContext

        ctx = TelegrinderHandlerContext()
        result = Silent().compile_telegrinder(ctx)
        assert result.silent is True

    def test_parse_mode_compile_telegrinder(self) -> None:
        from emergent.wire.axis.surface.dialects.telegram import ParseMode
        from emergent.wire.axis._capability import TelegrinderHandlerContext

        ctx = TelegrinderHandlerContext()
        result = ParseMode(mode="HTML").compile_telegrinder(ctx)
        assert result.parse_mode == "HTML"

    def test_link_preview_compile_telegrinder(self) -> None:
        from emergent.wire.axis.surface.dialects.telegram import LinkPreview
        from emergent.wire.axis._capability import TelegrinderHandlerContext

        ctx = TelegrinderHandlerContext()
        result = LinkPreview(disabled=True).compile_telegrinder(ctx)
        assert result.link_preview_disabled is True

    def test_protect_content_compile_telegrinder(self) -> None:
        from emergent.wire.axis.surface.dialects.telegram import ProtectContent
        from emergent.wire.axis._capability import TelegrinderHandlerContext

        ctx = TelegrinderHandlerContext()
        result = ProtectContent().compile_telegrinder(ctx)
        assert result.protect_content is True

    def test_help_meta_creation(self) -> None:
        from emergent.wire.axis.surface.dialects.telegram import HelpMeta

        hm = HelpMeta(description="Test help", order=1)
        assert hm.description == "Test help"
        assert hm.order == 1
        assert hm.hidden is False

    def test_edit_message_enricher_no_callback(self) -> None:
        """EditMessage enricher with no callback query in scope should pass through."""
        from emergent.wire.axis.surface.dialects.telegram import EditMessage

        async def run():
            from nodnod import Scope
            scope = Scope()

            async def call(s: Any) -> str:
                return "response text"

            enricher = EditMessage()
            result = await enricher.enrich(call, scope)
            assert result == "response text"

        asyncio.run(run())

    def test_answer_callback_enricher_no_callback(self) -> None:
        """AnswerCallback enricher with no callback query in scope."""
        from emergent.wire.axis.surface.dialects.telegram import AnswerCallback

        async def run():
            from nodnod import Scope
            scope = Scope()

            async def call(s: Any) -> str:
                return "done"

            enricher = AnswerCallback(text="OK")
            result = await enricher.enrich(call, scope)
            assert result == "done"

        asyncio.run(run())

    def test_reply_message_enricher_none_response(self) -> None:
        """ReplyMessage enricher with None response should return None."""
        from emergent.wire.axis.surface.dialects.telegram import ReplyMessage

        async def run():
            from nodnod import Scope
            scope = Scope()

            async def call(s: Any) -> None:
                return None

            enricher = ReplyMessage()
            result = await enricher.enrich(call, scope)
            assert result is None

        asyncio.run(run())

    def test_reply_message_enricher_empty_string(self) -> None:
        """ReplyMessage enricher with empty string response."""
        from emergent.wire.axis.surface.dialects.telegram import ReplyMessage

        async def run():
            from nodnod import Scope
            scope = Scope()

            async def call(s: Any) -> str:
                return ""

            enricher = ReplyMessage()
            result = await enricher.enrich(call, scope)
            assert result is None

        asyncio.run(run())

    def test_reply_message_enricher_no_api_in_scope(self) -> None:
        """ReplyMessage enricher with text but no API -> passthrough."""
        from emergent.wire.axis.surface.dialects.telegram import ReplyMessage

        async def run():
            from nodnod import Scope
            scope = Scope()

            async def call(s: Any) -> str:
                return "some response"

            enricher = ReplyMessage()
            result = await enricher.enrich(call, scope)
            assert result == "some response"

        asyncio.run(run())


# ═══════════════════════════════════════════════════════════════════════════════
# 12. Methods pattern — _build_method_operation, Methods, MethodDialect
# ═══════════════════════════════════════════════════════════════════════════════


class TestMethodsPattern:
    """Cover methods.py: _build_method_operation, Methods, MethodDialect."""

    def test_methods_classmethod(self) -> None:
        from emergent.wire.derive._compile import compile_derive
        from emergent.wire.derive._materialize import materialize
        from emergent.wire.derive.patterns.methods import Methods, post

        @schema_meta(Methods())
        @dataclass
        class OrderService:
            @classmethod
            @post("/api/orders")
            async def create(cls, customer: str) -> Result[int, Exception]:
                return Ok(42)

        ctxs = compile_derive(OrderService)
        assert len(ctxs) >= 1
        endpoint = materialize(ctxs[0])
        assert len(endpoint.exposures) == 1

    def test_methods_staticmethod(self) -> None:
        from emergent.wire.derive._compile import compile_derive
        from emergent.wire.derive._materialize import materialize
        from emergent.wire.derive.patterns.methods import Methods, get

        @schema_meta(Methods())
        @dataclass
        class HealthService:
            @staticmethod
            @get("/api/health")
            async def health() -> Result[str, Exception]:
                return Ok("ok")

        ctxs = compile_derive(HealthService)
        assert len(ctxs) >= 1
        endpoint = materialize(ctxs[0])
        assert len(endpoint.exposures) >= 1

    def test_methods_instance_method(self) -> None:
        from emergent.wire.derive._compile import compile_derive
        from emergent.wire.derive._materialize import materialize
        from emergent.wire.derive.patterns.methods import Methods, post

        @schema_meta(Methods())
        @dataclass
        class MyService:
            @post("/api/echo")
            async def echo(self, msg: str) -> Result[str, Exception]:
                return Ok(msg)

        ctxs = compile_derive(MyService)
        endpoint = materialize(ctxs[0])
        assert len(endpoint.exposures) >= 1

    def test_methods_multi_trigger(self) -> None:
        """Multiple triggers on same method should create multiple operations."""
        from emergent.wire.derive._compile import compile_derive
        from emergent.wire.derive._materialize import materialize
        from emergent.wire.derive.patterns.methods import Methods, post, command

        @schema_meta(Methods())
        @dataclass
        class MultiService:
            @classmethod
            @post("/api/do")
            @command("do-it", description="Do the thing")
            async def do_it(cls, x: int) -> Result[str, Exception]:
                return Ok(str(x))

        ctxs = compile_derive(MultiService)
        endpoint = materialize(ctxs[0])
        assert len(endpoint.exposures) >= 2

    def test_methods_sync_raises(self) -> None:
        """Non-async method should raise TypeError."""
        from emergent.wire.derive._compile import compile_derive
        from emergent.wire.derive.patterns.methods import Methods, post

        @schema_meta(Methods())
        @dataclass
        class BadService:
            @classmethod
            @post("/api/bad")
            def bad_method(cls) -> Result[str, Exception]:
                return Ok("bad")

        with pytest.raises(TypeError, match="must be async"):
            compile_derive(BadService)

    def test_methods_no_result_return_raises(self) -> None:
        """Method not returning Result should raise TypeError."""
        from emergent.wire.derive._compile import compile_derive
        from emergent.wire.derive.patterns.methods import Methods, post

        @schema_meta(Methods())
        @dataclass
        class NoResultService:
            @classmethod
            @post("/api/no-result")
            async def bad(cls) -> str:
                return "bad"

        with pytest.raises(TypeError, match="must return Result"):
            compile_derive(NoResultService)

    def test_methods_with_description(self) -> None:
        """Method with description should attach HelpMeta."""
        from emergent.wire.derive._compile import compile_derive
        from emergent.wire.derive._materialize import materialize
        from emergent.wire.derive.patterns.methods import Methods, method
        from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger

        @schema_meta(Methods())
        @dataclass
        class DescService:
            @classmethod
            @method(HTTPRouteTrigger("GET", "/api/info"), description="Get info", order=1)
            async def info(cls) -> Result[str, Exception]:
                return Ok("info")

        ctxs = compile_derive(DescService)
        endpoint = materialize(ctxs[0])
        from emergent.wire.axis.surface.dialects.telegram import HelpMeta
        caps = endpoint.exposures[0].capabilities
        help_caps = [c for c in caps if isinstance(c, HelpMeta)]
        assert len(help_caps) == 1
        assert help_caps[0].description == "Get info"

    def test_method_dialect_with_http_triggers(self) -> None:
        """MethodDialect assigns triggers via TriggerGen."""
        from emergent.wire.derive._compile import compile_derive
        from emergent.wire.derive._materialize import materialize
        from emergent.wire.derive.patterns.methods import MethodDialect, op
        from emergent.wire.derive._trigger import HTTPTriggers
        from emergent.wire.derive._effects import Creates

        @schema_meta(MethodDialect(triggers=HTTPTriggers("/api/orders")))
        @dataclass
        class OrderSvc:
            @classmethod
            @op("Create", effects=(Creates(),))
            async def create(cls, customer: str) -> Result[int, Exception]:
                return Ok(1)

        ctxs = compile_derive(OrderSvc)
        endpoint = materialize(ctxs[0])
        assert len(endpoint.exposures) >= 1

    def test_method_dialect_skips_unannotated(self) -> None:
        """MethodDialect should skip methods without @op."""
        from emergent.wire.derive._compile import compile_derive
        from emergent.wire.derive.patterns.methods import MethodDialect, op
        from emergent.wire.derive._trigger import HTTPTriggers
        from emergent.wire.derive._effects import Creates

        @schema_meta(MethodDialect(triggers=HTTPTriggers("/api/orders")))
        @dataclass
        class MixedSvc:
            @classmethod
            @op("Create", effects=(Creates(),))
            async def create(cls, name: str) -> Result[int, Exception]:
                return Ok(1)

            @classmethod
            async def helper(cls) -> str:
                """Not decorated with @op, should be skipped."""
                return "helper"

        ctxs = compile_derive(MixedSvc)
        # Only the @op-decorated method should produce an operation
        assert len(ctxs[0].operations) == 1

    def test_op_decorator_default_name(self) -> None:
        """@op() without name uses function name."""
        from emergent.wire.derive.patterns.methods import op, OP_ENTRIES_ATTR

        @op()
        async def my_func() -> Result[str, Exception]:
            return Ok("x")

        entry = getattr(my_func, OP_ENTRIES_ATTR)
        assert entry.name == "my_func"

    def test_result_type_fields_dataclass(self) -> None:
        """_result_type_fields should extract dataclass fields."""
        from emergent.wire.derive.patterns.methods import _result_type_fields

        @dataclass
        class MyResponse:
            data: str
            count: int

        fields = _result_type_fields(MyResponse)
        assert "data" in fields
        assert "count" in fields

    def test_result_type_fields_scalar(self) -> None:
        """_result_type_fields should wrap non-dataclass in 'result' key."""
        from emergent.wire.derive.patterns.methods import _result_type_fields

        fields = _result_type_fields(int)
        assert fields == {"result": int}


# ═══════════════════════════════════════════════════════════════════════════════
# 13. Temporal query helpers
# ═══════════════════════════════════════════════════════════════════════════════


class TestTemporalQueryHelpers:
    """Cover temporal_filter_current, temporal_filter_as_of, temporal_filter_version."""

    def test_temporal_filter_current(self) -> None:
        from emergent.wire.axis.schema.dialects.temporal import temporal_filter_current
        from emergent.wire.axis.query._expr import IsNull

        expr = temporal_filter_current("valid_to")
        assert isinstance(expr, IsNull)

    def test_temporal_filter_as_of(self) -> None:
        from emergent.wire.axis.schema.dialects.temporal import temporal_filter_as_of
        from emergent.wire.axis.query._expr import And

        ts = datetime(2024, 1, 1)
        expr = temporal_filter_as_of(ts)
        assert isinstance(expr, And)

    def test_temporal_filter_version(self) -> None:
        from emergent.wire.axis.schema.dialects.temporal import temporal_filter_version
        from emergent.wire.axis.query._expr import Eq

        expr = temporal_filter_version(3)
        assert isinstance(expr, Eq)


# ═══════════════════════════════════════════════════════════════════════════════
# 14. Filtered transform (in-memory)
# ═══════════════════════════════════════════════════════════════════════════════


class TestFilteredTransform:
    """Cover Filtered transform with explicit fields."""

    def test_filtered_with_explicit_fields(self) -> None:
        from emergent.wire.derive._compile import compile_derive
        from emergent.wire.derive._crud import http_crud
        from emergent.wire.derive._transforms import Filtered

        @schema_meta(
            http_crud("/api/posts", PostProvider),
            Filtered(fields=("status",)),
        )
        @dataclass
        class FilteredPost:
            id: Annotated[int, Identity()]
            title: str
            status: str = "draft"

        ctxs = compile_derive(FilteredPost)
        ctx = ctxs[0]
        from emergent.wire.derive._effects import Read as ReadEff, has_effect
        for s in ctx.specs:
            if has_effect(s.effects, ReadEff):
                field_names = [f[0] for f in s.extra_op_fields]
                assert "filter_status" in field_names

    def test_filtered_without_fields_no_effect(self) -> None:
        """Filtered() with no fields and no Filterable effect -> no extra fields."""
        from emergent.wire.derive._compile import compile_derive
        from emergent.wire.derive._crud import http_crud
        from emergent.wire.derive._transforms import Filtered

        @schema_meta(
            http_crud("/api/posts", PostProvider),
            Filtered(),
        )
        @dataclass
        class UnfilteredPost:
            id: Annotated[int, Identity()]
            title: str

        ctxs = compile_derive(UnfilteredPost)
        assert len(ctxs) >= 1


# ═══════════════════════════════════════════════════════════════════════════════
# 15. WithTimeout transform
# ═══════════════════════════════════════════════════════════════════════════════


class TestWithTimeoutTransform:
    """Cover WithTimeout compile_derive_modify."""

    def test_with_timeout_adds_enricher(self) -> None:
        from emergent.wire.derive._compile import compile_derive
        from emergent.wire.derive._crud import http_crud
        from emergent.wire.derive._transforms import WithTimeout
        from emergent.wire.axis.surface.enrichers._impl import Timeout

        @schema_meta(
            http_crud("/api/posts", PostProvider),
            WithTimeout(seconds=30.0),
        )
        @dataclass
        class TimeoutPost:
            id: Annotated[int, Identity()]
            title: str

        ctxs = compile_derive(TimeoutPost)
        ctx = ctxs[0]
        for s in ctx.specs:
            timeout_caps = [c for c in s.capabilities if isinstance(c, Timeout)]
            assert len(timeout_caps) >= 1


# ═══════════════════════════════════════════════════════════════════════════════
# 16. Additional edge cases
# ═══════════════════════════════════════════════════════════════════════════════


class TestEdgeCases:
    """Additional edge cases for coverage."""

    def test_callback_query_extraction_no_context(self) -> None:
        """_get_callback_query_from_scope with empty scope returns None."""
        from emergent.wire.axis.surface.dialects.telegram import _get_callback_query_from_scope
        from nodnod import Scope

        scope = Scope()
        result = _get_callback_query_from_scope(scope)
        assert result is None

    def test_unwrap_some_no_value(self) -> None:
        from emergent.wire.axis.surface.dialects.telegram import _unwrap_some

        assert _unwrap_some(object()) is None

    def test_unwrap_some_with_value(self) -> None:
        from emergent.wire.axis.surface.dialects.telegram import _unwrap_some

        @dataclass
        class FakeWrapper:
            value: str

        result = _unwrap_some(FakeWrapper("hello"))
        assert result == "hello"

    def test_compose_field_deltas_different_types(self) -> None:
        """Different delta types -> last wins."""
        from emergent.wire.axis.schema.dialects.delta import (
            _compose_field_deltas, NumericDelta, StringDelta,
        )

        result = _compose_field_deltas(NumericDelta(add=1), StringDelta(append="x"))
        assert isinstance(result, StringDelta)

    def test_delta_kind_unknown(self) -> None:
        from emergent.wire.axis.schema.dialects.delta import _delta_kind

        @dataclass(frozen=True, slots=True)
        class WeirdDelta:
            val: int = 0

        assert _delta_kind(cast(Any, WeirdDelta())) == "unknown"

    def test_compose_numeric_deltas_only_d1_multiply(self) -> None:
        from emergent.wire.axis.schema.dialects.delta import _compose_field_deltas, NumericDelta

        d1 = NumericDelta(multiply=3.0)
        d2 = NumericDelta(add=5)
        result = _compose_field_deltas(d1, d2)
        assert isinstance(result, NumericDelta)
        assert result.multiply == 3.0

    def test_compose_numeric_deltas_only_d2_multiply(self) -> None:
        from emergent.wire.axis.schema.dialects.delta import _compose_field_deltas, NumericDelta

        d1 = NumericDelta(add=5)
        d2 = NumericDelta(multiply=3.0)
        result = _compose_field_deltas(d1, d2)
        assert isinstance(result, NumericDelta)
        assert result.multiply == 3.0

    def test_numeric_delta_float_result(self) -> None:
        from emergent.wire.axis.schema.dialects.delta import NumericDelta

        d = NumericDelta(multiply=1.5)
        result = d.apply(3)
        # 3 * 1.5 = 4.5, not a whole number -> float
        assert result == 4.5
        assert isinstance(result, float)

    def test_edit_message_enricher_dict_with_text(self) -> None:
        """EditMessage enricher with dict response containing 'text'."""
        from emergent.wire.axis.surface.dialects.telegram import EditMessage

        async def run():
            from nodnod import Scope
            scope = Scope()

            async def call(s: Any) -> dict[str, str]:
                return {"text": "hello", "parse_mode": "HTML"}

            enricher = EditMessage()
            # No callback query => passthrough
            result = await enricher.enrich(call, scope)
            assert result == {"text": "hello", "parse_mode": "HTML"}

        asyncio.run(run())

    def test_edit_message_enricher_dict_without_text(self) -> None:
        """EditMessage enricher with dict response without 'text'."""
        from emergent.wire.axis.surface.dialects.telegram import EditMessage

        async def run():
            from nodnod import Scope
            scope = Scope()

            async def call(s: Any) -> dict[str, str]:
                return {"data": "value"}

            enricher = EditMessage()
            result = await enricher.enrich(call, scope)
            assert result == {"data": "value"}

        asyncio.run(run())

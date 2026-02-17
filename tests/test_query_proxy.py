"""Tests for proxy objects — FieldProxy, EntityProxy, build_expr, build_order.

Covers uncovered lines: array_any, array_all, array_overlap, _wrap with FieldProxy,
_wrap with Expr, JsonFieldProxy comparisons, FieldProxy and/or/invert operators,
window functions (lag, lead), EntityProxy window functions (row_number, rank,
dense_rank, ntile), FieldProxy.wrap static method, array_agg, string_agg.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from emergent.wire.axis.query._expr import (
    And,
    ArrayAll,
    ArrayAny,
    ArrayContains,
    ArrayOverlap,
    Between,
    Contains,
    EndsWith,
    Eq,
    Field,
    Ge,
    Gt,
    ILike,
    In,
    IsNotNull,
    IsNull,
    JsonContains,
    JsonExtract,
    JsonHasKey,
    Le,
    Like,
    Lt,
    Ne,
    Not,
    Or,
    Regex,
    StartsWith,
    Const,
)
from emergent.wire.axis.query._aggregate import (
    AggregateExpr,
    ArrayAgg,
    Avg,
    Count,
    Max,
    Min,
    StringAgg,
    Sum,
)
import emergent.wire.axis.query._proxy as _proxy_mod
from emergent.wire.axis.query._proxy import (
    EntityProxy,
    FieldProxy,
    JsonFieldProxy,
    OrderSpec,
    build_expr,
    build_order,
)

# Access private functions via getattr for testing internal behavior;
# pyright disallows direct use of private names from other modules.
_wrap_fn = getattr(_proxy_mod, "_wrap")
_entity_fields_fn = getattr(_proxy_mod, "_entity_fields")


@dataclass
class User:
    id: int
    name: str
    balance: float
    active: bool = True


# ===============================================================================
# FieldProxy
# ===============================================================================


class TestFieldProxy:
    def test_name(self) -> None:
        fp = FieldProxy("balance")
        assert fp.name == "balance"

    def test_eq(self) -> None:
        result = FieldProxy("name") == "alice"
        assert isinstance(result, Eq)

    def test_ne(self) -> None:
        result = FieldProxy("name") != "alice"
        assert isinstance(result, Ne)

    def test_lt(self) -> None:
        result = FieldProxy("balance") < 100
        assert isinstance(result, Lt)

    def test_le(self) -> None:
        result = FieldProxy("balance") <= 100
        assert isinstance(result, Le)

    def test_gt(self) -> None:
        result = FieldProxy("balance") > 100
        assert isinstance(result, Gt)

    def test_ge(self) -> None:
        result = FieldProxy("balance") >= 100
        assert isinstance(result, Ge)

    def test_and(self) -> None:
        a = FieldProxy("x") == 1
        b = FieldProxy("y") == 2
        result = a & b
        assert isinstance(result, And)

    def test_or(self) -> None:
        a = FieldProxy("x") == 1
        b = FieldProxy("y") == 2
        result = a | b
        assert isinstance(result, Or)

    def test_invert(self) -> None:
        result = ~(FieldProxy("active") == True)
        assert isinstance(result, Not)

    def test_in_(self) -> None:
        result = FieldProxy("role").in_(["admin", "mod"])
        assert isinstance(result, In)

    def test_contains(self) -> None:
        result = FieldProxy("name").contains("ali")
        assert isinstance(result, Contains)

    def test_startswith(self) -> None:
        result = FieldProxy("name").startswith("al")
        assert isinstance(result, StartsWith)

    def test_endswith(self) -> None:
        result = FieldProxy("name").endswith("ce")
        assert isinstance(result, EndsWith)

    def test_is_null(self) -> None:
        result = FieldProxy("deleted_at").is_null()
        assert isinstance(result, IsNull)

    def test_is_not_null(self) -> None:
        result = FieldProxy("deleted_at").is_not_null()
        assert isinstance(result, IsNotNull)

    def test_between(self) -> None:
        result = FieldProxy("balance").between(50, 200)
        assert isinstance(result, Between)

    def test_like(self) -> None:
        result = FieldProxy("email").like("%@gmail.com")
        assert isinstance(result, Like)

    def test_ilike(self) -> None:
        result = FieldProxy("email").ilike("%@GMAIL.COM")
        assert isinstance(result, ILike)

    def test_regex(self) -> None:
        result = FieldProxy("email").regex(r"^\w+@")
        assert isinstance(result, Regex)

    def test_array_contains(self) -> None:
        result = FieldProxy("tags").array_contains("vip")
        assert isinstance(result, ArrayContains)

    def test_array_any(self) -> None:
        result = FieldProxy("tags").array_any("vip", "admin")
        assert isinstance(result, ArrayAny)

    def test_array_all(self) -> None:
        result = FieldProxy("tags").array_all("vip", "verified")
        assert isinstance(result, ArrayAll)

    def test_array_overlap(self) -> None:
        result = FieldProxy("tags").array_overlap("a", "b")
        assert isinstance(result, ArrayOverlap)

    def test_json(self) -> None:
        result = FieldProxy("metadata").json("profile.name")
        assert isinstance(result, JsonFieldProxy)

    def test_json_contains(self) -> None:
        result = FieldProxy("metadata").json_contains({"role": "admin"})
        assert isinstance(result, JsonContains)

    def test_json_has_key(self) -> None:
        result = FieldProxy("metadata").json_has_key("profile")
        assert isinstance(result, JsonHasKey)

    def test_asc(self) -> None:
        result = FieldProxy("balance").asc()
        assert result == OrderSpec("balance", ascending=True)

    def test_desc(self) -> None:
        result = FieldProxy("balance").desc()
        assert result == OrderSpec("balance", ascending=False)

    # Aggregates

    def test_sum(self) -> None:
        result = FieldProxy("balance").sum()
        assert isinstance(result, AggregateExpr)
        assert isinstance(result.func, Sum)
        assert result.field == "balance"

    def test_avg(self) -> None:
        result = FieldProxy("balance").avg()
        assert isinstance(result.func, Avg)

    def test_count(self) -> None:
        result = FieldProxy("id").count()
        assert isinstance(result.func, Count)
        assert result.field == "id"

    def test_min(self) -> None:
        result = FieldProxy("balance").min()
        assert isinstance(result.func, Min)

    def test_max(self) -> None:
        result = FieldProxy("balance").max()
        assert isinstance(result.func, Max)

    def test_array_agg(self) -> None:
        result = FieldProxy("tags").array_agg()
        assert isinstance(result, AggregateExpr)
        assert isinstance(result.func, ArrayAgg)
        assert result.field == "tags"

    def test_string_agg(self) -> None:
        result = FieldProxy("name").string_agg(", ")
        assert isinstance(result, AggregateExpr)
        assert isinstance(result.func, StringAgg)
        assert result.func.separator == ", "
        assert result.field == "name"

    def test_string_agg_default_separator(self) -> None:
        result = FieldProxy("name").string_agg()
        assert isinstance(result.func, StringAgg)
        assert result.func.separator == ","

    # Window functions

    def test_lag(self) -> None:
        from emergent.wire.axis.query._sql import WindowBuilder
        result = FieldProxy("balance").lag()
        assert isinstance(result, WindowBuilder)

    def test_lag_with_offset(self) -> None:
        from emergent.wire.axis.query._sql import WindowBuilder
        result = FieldProxy("balance").lag(offset=2, default=0)
        assert isinstance(result, WindowBuilder)

    def test_lead(self) -> None:
        from emergent.wire.axis.query._sql import WindowBuilder
        result = FieldProxy("balance").lead()
        assert isinstance(result, WindowBuilder)

    def test_lead_with_offset(self) -> None:
        from emergent.wire.axis.query._sql import WindowBuilder
        result = FieldProxy("balance").lead(offset=3, default=None)
        assert isinstance(result, WindowBuilder)

    # Static wrap method

    def test_wrap_static_method(self) -> None:
        result = FieldProxy.wrap(42)
        assert isinstance(result, Const)
        # Const is Generic[T]; wrap returns Expr so T is unknown after isinstance narrowing
        assert result.value == 42  # pyright: ignore[reportUnknownMemberType] -- Const[T].value has unknown T from Expr return type

    def test_wrap_field_proxy(self) -> None:
        fp = FieldProxy("name")
        result = FieldProxy.wrap(fp)
        assert isinstance(result, Field)
        assert result.name == "name"

    def test_wrap_expr(self) -> None:
        expr = Eq(Field("x"), Const(1))
        result = FieldProxy.wrap(expr)
        assert result is expr

    # _ComparableMixin and/or/invert on FieldProxy itself

    def test_field_proxy_and_operator(self) -> None:
        fp = FieldProxy("active")
        other = Eq(Field("x"), Const(1))
        result = fp & other
        assert isinstance(result, And)

    def test_field_proxy_or_operator(self) -> None:
        fp = FieldProxy("active")
        other = Eq(Field("x"), Const(1))
        result = fp | other
        assert isinstance(result, Or)

    def test_field_proxy_invert_operator(self) -> None:
        fp = FieldProxy("active")
        result = ~fp
        assert isinstance(result, Not)


# ===============================================================================
# _wrap function
# ===============================================================================


class TestWrapFunction:
    def test_wrap_field_proxy(self) -> None:
        fp = FieldProxy("name")
        result = _wrap_fn(fp)
        assert isinstance(result, Field)
        assert result.name == "name"

    def test_wrap_expr_passthrough(self) -> None:
        expr = Eq(Field("x"), Const(1))
        result = _wrap_fn(expr)
        assert result is expr

    def test_wrap_raw_value(self) -> None:
        result = _wrap_fn(42)
        assert isinstance(result, Const)
        # Const is Generic[T]; _wrap returns Expr so T is unknown after isinstance narrowing
        assert result.value == 42  # pyright: ignore[reportUnknownMemberType] -- Const[T].value has unknown T from Expr return type

    def test_wrap_string(self) -> None:
        result = _wrap_fn("hello")
        assert isinstance(result, Const)
        # Const is Generic[T]; _wrap returns Expr so T is unknown after isinstance narrowing
        assert result.value == "hello"  # pyright: ignore[reportUnknownMemberType] -- Const[T].value has unknown T from Expr return type

    def test_wrap_none(self) -> None:
        result = _wrap_fn(None)
        assert isinstance(result, Const)
        # Const is Generic[T]; _wrap returns Expr so T is unknown after isinstance narrowing
        assert result.value is None  # pyright: ignore[reportUnknownMemberType] -- Const[T].value has unknown T from Expr return type


# ===============================================================================
# JsonFieldProxy
# ===============================================================================


class TestJsonFieldProxy:
    def test_eq(self) -> None:
        result = FieldProxy("metadata").json("profile.name") == "alice"
        assert isinstance(result, Eq)
        assert isinstance(result.left, JsonExtract)

    def test_ne(self) -> None:
        result = FieldProxy("metadata").json("profile.name") != "alice"
        assert isinstance(result, Ne)

    def test_lt(self) -> None:
        result = FieldProxy("data").json("score") < 50
        assert isinstance(result, Lt)

    def test_le(self) -> None:
        result = FieldProxy("data").json("score") <= 50
        assert isinstance(result, Le)

    def test_gt(self) -> None:
        result = FieldProxy("data").json("score") > 100
        assert isinstance(result, Gt)

    def test_ge(self) -> None:
        result = FieldProxy("data").json("score") >= 100
        assert isinstance(result, Ge)

    def test_is_null(self) -> None:
        result = FieldProxy("data").json("key").is_null()
        assert isinstance(result, IsNull)

    def test_is_not_null(self) -> None:
        result = FieldProxy("data").json("key").is_not_null()
        assert isinstance(result, IsNotNull)

    def test_and_operator(self) -> None:
        jp = FieldProxy("data").json("key")
        other = Eq(Field("x"), Const(1))
        result = jp & other
        assert isinstance(result, And)

    def test_or_operator(self) -> None:
        jp = FieldProxy("data").json("key")
        other = Eq(Field("x"), Const(1))
        result = jp | other
        assert isinstance(result, Or)

    def test_invert_operator(self) -> None:
        jp = FieldProxy("data").json("key")
        result = ~jp
        assert isinstance(result, Not)


# ===============================================================================
# EntityProxy
# ===============================================================================


class TestEntityProxy:
    def test_getattr_returns_field_proxy(self) -> None:
        proxy = EntityProxy(User)
        fp = proxy.balance
        assert isinstance(fp, FieldProxy)
        assert fp.name == "balance"

    def test_unknown_field_raises(self) -> None:
        proxy = EntityProxy(User)
        with pytest.raises(AttributeError, match="has no field"):
            proxy.nonexistent

    def test_count_star(self) -> None:
        proxy = EntityProxy(User)
        result = proxy.count()
        assert isinstance(result, AggregateExpr)
        assert isinstance(result.func, Count)
        assert result.field is None  # COUNT(*)

    # Window functions on EntityProxy

    def test_row_number(self) -> None:
        from emergent.wire.axis.query._sql import WindowBuilder
        proxy = EntityProxy(User)
        result = proxy.row_number()
        assert isinstance(result, WindowBuilder)

    def test_rank(self) -> None:
        from emergent.wire.axis.query._sql import WindowBuilder
        proxy = EntityProxy(User)
        result = proxy.rank()
        assert isinstance(result, WindowBuilder)

    def test_dense_rank(self) -> None:
        from emergent.wire.axis.query._sql import WindowBuilder
        proxy = EntityProxy(User)
        result = proxy.dense_rank()
        assert isinstance(result, WindowBuilder)

    def test_ntile(self) -> None:
        from emergent.wire.axis.query._sql import WindowBuilder
        proxy = EntityProxy(User)
        result = proxy.ntile(4)
        assert isinstance(result, WindowBuilder)


# ===============================================================================
# _entity_fields
# ===============================================================================


class TestEntityFields:
    def test_returns_none_for_plain_class(self) -> None:
        class PlainUser:
            pass

        assert _entity_fields_fn(PlainUser) is None

    def test_returns_fields_for_dataclass(self) -> None:
        fields = _entity_fields_fn(User)
        assert fields is not None
        assert "name" in fields
        assert "balance" in fields

    def test_plain_class_proxy_allows_any_field(self) -> None:
        class PlainUser:
            pass

        proxy = EntityProxy(PlainUser)
        fp = proxy.anything
        assert isinstance(fp, FieldProxy)
        assert fp.name == "anything"


# ===============================================================================
# build_expr
# ===============================================================================


class TestBuildExpr:
    def test_simple(self) -> None:
        expr = build_expr(User, lambda u: u.balance > 100)
        assert isinstance(expr, Gt)

    def test_compound(self) -> None:
        expr = build_expr(User, lambda u: (u.active == True) & (u.balance > 0))
        assert isinstance(expr, And)

    def test_evaluate(self) -> None:
        expr = build_expr(User, lambda u: u.name == "alice")
        user = User(id=1, name="alice", balance=100.0)
        assert expr.evaluate(user) is True


# ===============================================================================
# build_order
# ===============================================================================


class TestBuildOrder:
    def test_field_proxy_default_asc(self) -> None:
        spec = build_order(User, lambda u: u.name)
        assert spec == OrderSpec("name", ascending=True)

    def test_explicit_desc(self) -> None:
        spec = build_order(User, lambda u: u.balance.desc())
        assert spec == OrderSpec("balance", ascending=False)

    def test_explicit_asc(self) -> None:
        spec = build_order(User, lambda u: u.balance.asc())
        assert spec == OrderSpec("balance", ascending=True)


# ===============================================================================
# Integration: Proxy to Evaluation
# ===============================================================================


class TestIntegrationProxyToEvaluation:
    def test_proxy_built_expr_evaluates_correctly(self) -> None:
        expr = build_expr(User, lambda u: (u.balance > 50) & (u.active == True))
        alice = User(id=1, name="alice", balance=100.0, active=True)
        bob = User(id=2, name="bob", balance=30.0, active=True)
        charlie = User(id=3, name="charlie", balance=200.0, active=False)

        assert expr.evaluate(alice) is True
        assert expr.evaluate(bob) is False
        assert expr.evaluate(charlie) is False

    def test_proxy_expr_matches_hand_built(self) -> None:
        proxy_expr = build_expr(User, lambda u: u.name == "alice")
        hand_expr = FieldProxy("name") == "alice"

        alice = User(id=1, name="alice", balance=100.0)
        bob = User(id=2, name="bob", balance=50.0)

        assert proxy_expr.evaluate(alice) == hand_expr.evaluate(alice)
        assert proxy_expr.evaluate(bob) == hand_expr.evaluate(bob)

    def test_proxy_compound_logic(self) -> None:
        expr = build_expr(User, lambda u: (u.balance > 50) | (u.name == "bob"))
        assert expr.evaluate(User(id=1, name="alice", balance=100.0)) is True
        assert expr.evaluate(User(id=2, name="bob", balance=10.0)) is True
        assert expr.evaluate(User(id=3, name="charlie", balance=10.0)) is False

    def test_proxy_chained_comparisons(self) -> None:
        expr = build_expr(User, lambda u: (u.balance > 50) & (u.active == True))
        assert isinstance(expr, And)
        left = expr.left
        right = expr.right
        assert isinstance(left, Gt)
        assert isinstance(right, Eq)
        left_children = left.children()
        assert len(left_children) == 2
        assert left_children[0].evaluate(User(id=1, name="x", balance=99.0)) == 99.0

    def test_proxy_negation(self) -> None:
        expr = build_expr(User, lambda u: ~(u.active == True))
        assert isinstance(expr, Not)
        alice_active = User(id=1, name="alice", balance=100.0, active=True)
        alice_inactive = User(id=2, name="alice", balance=100.0, active=False)
        assert expr.evaluate(alice_active) is False
        assert expr.evaluate(alice_inactive) is True

    def test_between_through_proxy(self) -> None:
        expr = build_expr(User, lambda u: u.balance.between(50, 150))
        assert expr.evaluate(User(id=1, name="a", balance=100.0)) is True
        assert expr.evaluate(User(id=2, name="b", balance=200.0)) is False
        assert expr.evaluate(User(id=3, name="c", balance=50.0)) is True

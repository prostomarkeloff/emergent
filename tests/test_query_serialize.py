"""Tests for expression serialization — roundtrip + analysis."""

from __future__ import annotations

import pytest

from emergent.wire.axis.query._expr import (
    And,
    ArrayAll,
    ArrayAny,
    ArrayContains,
    ArrayOverlap,
    Between,
    Const,
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
)
from emergent.wire.axis.query._serialize import (
    expr_complexity,
    expr_depth,
    expr_fields,
    expr_from_dict,
    expr_repr,
    expr_to_dict,
)


# ─── Roundtrip Tests ─────────────────────────────────────────────────────────


ALL_EXPR_CASES = [
    ("field", Field("name")),
    ("const_int", Const(42)),
    ("const_str", Const("hello")),
    ("const_none", Const(None)),
    ("const_bool", Const(True)),
    ("eq", Eq(Field("name"), Const("alice"))),
    ("ne", Ne(Field("x"), Const(1))),
    ("lt", Lt(Field("x"), Const(10))),
    ("le", Le(Field("x"), Const(10))),
    ("gt", Gt(Field("x"), Const(10))),
    ("ge", Ge(Field("x"), Const(10))),
    ("and", And(Eq(Field("a"), Const(1)), Eq(Field("b"), Const(2)))),
    ("or", Or(Eq(Field("a"), Const(1)), Eq(Field("b"), Const(2)))),
    ("not", Not(Eq(Field("a"), Const(1)))),
    ("in", In(Field("status"), ("active", "pending"))),
    ("contains", Contains(Field("name"), "ali")),
    ("startswith", StartsWith(Field("name"), "al")),
    ("endswith", EndsWith(Field("name"), "ce")),
    ("is_null", IsNull(Field("x"))),
    ("is_not_null", IsNotNull(Field("x"))),
    ("between", Between(Field("x"), Const(10), Const(20))),
    ("like", Like(Field("email"), "%@gmail.com")),
    ("ilike", ILike(Field("email"), "%@GMAIL.COM")),
    ("regex", Regex(Field("email"), r"^\w+@\w+$")),
    ("array_contains", ArrayContains(Field("tags"), "vip")),
    ("array_any", ArrayAny(Field("tags"), ("vip", "admin"))),
    ("array_all", ArrayAll(Field("tags"), ("vip", "verified"))),
    ("array_overlap", ArrayOverlap(Field("tags"), ("a", "b"))),
    ("json_extract", JsonExtract(Field("meta"), "profile.name")),
    ("json_contains", JsonContains(Field("meta"), {"role": "admin"})),
    ("json_has_key", JsonHasKey(Field("meta"), "profile")),
]


@pytest.mark.parametrize("name,expr", ALL_EXPR_CASES, ids=[c[0] for c in ALL_EXPR_CASES])
def test_roundtrip(name: str, expr):
    serialized = expr_to_dict(expr)
    deserialized = expr_from_dict(serialized)
    assert deserialized == expr


def test_nested_roundtrip():
    expr = And(
        Or(Eq(Field("a"), Const(1)), Gt(Field("b"), Const(2))),
        Not(IsNull(Field("c"))),
    )
    assert expr_from_dict(expr_to_dict(expr)) == expr


def test_unknown_op_serialize_raises():
    class FakeExpr:
        pass

    with pytest.raises((ValueError, AttributeError)):
        expr_to_dict(FakeExpr())  # type: ignore


def test_unknown_op_deserialize_raises():
    with pytest.raises(ValueError, match="Unknown"):
        expr_from_dict({"op": "totally_fake"})


# ─── Analysis ────────────────────────────────────────────────────────────────


class TestExprFields:
    def test_single(self):
        assert expr_fields(Field("name")) == {"name"}

    def test_const_empty(self):
        assert expr_fields(Const(42)) == set()

    def test_comparison(self):
        expr = Eq(Field("name"), Const("alice"))
        assert expr_fields(expr) == {"name"}

    def test_multiple(self):
        expr = And(
            Eq(Field("name"), Const("alice")),
            Gt(Field("balance"), Const(100)),
        )
        assert expr_fields(expr) == {"name", "balance"}


class TestExprComplexity:
    def test_leaf(self):
        assert expr_complexity(Field("x")) == 1
        assert expr_complexity(Const(42)) == 1

    def test_binary(self):
        # Eq(Field, Const) = 3 nodes
        assert expr_complexity(Eq(Field("x"), Const(1))) == 3

    def test_nested(self):
        # And(Eq(F,C), Eq(F,C)) = 1 + 3 + 3 = 7
        expr = And(Eq(Field("a"), Const(1)), Eq(Field("b"), Const(2)))
        assert expr_complexity(expr) == 7


class TestExprDepth:
    def test_leaf(self):
        assert expr_depth(Field("x")) == 1

    def test_binary(self):
        assert expr_depth(Eq(Field("x"), Const(1))) == 2

    def test_nested(self):
        expr = And(Eq(Field("a"), Const(1)), Eq(Field("b"), Const(2)))
        assert expr_depth(expr) == 3


# ─── Human-readable repr ────────────────────────────────────────────────────


class TestExprRepr:
    def test_comparison(self):
        assert expr_repr(Eq(Field("x"), Const(1))) == "x == 1"

    def test_ne(self):
        assert expr_repr(Ne(Field("x"), Const(1))) == "x != 1"

    def test_lt_gt_le_ge(self):
        assert expr_repr(Lt(Field("x"), Const(10))) == "x < 10"
        assert expr_repr(Le(Field("x"), Const(10))) == "x <= 10"
        assert expr_repr(Gt(Field("x"), Const(10))) == "x > 10"
        assert expr_repr(Ge(Field("x"), Const(10))) == "x >= 10"

    def test_logical_and(self):
        expr = And(Eq(Field("a"), Const(1)), Gt(Field("b"), Const(2)))
        assert expr_repr(expr) == "(a == 1) & (b > 2)"

    def test_logical_or(self):
        expr = Or(Eq(Field("a"), Const(1)), Eq(Field("b"), Const(2)))
        assert expr_repr(expr) == "(a == 1) | (b == 2)"

    def test_not(self):
        assert expr_repr(Not(Eq(Field("x"), Const(1)))) == "~(x == 1)"

    def test_in(self):
        assert expr_repr(In(Field("status"), ("a", "b"))) == "status IN ('a', 'b')"

    def test_is_null(self):
        assert expr_repr(IsNull(Field("x"))) == "x IS NULL"
        assert expr_repr(IsNotNull(Field("x"))) == "x IS NOT NULL"

    def test_between(self):
        expr = Between(Field("x"), Const(10), Const(20))
        assert expr_repr(expr) == "x BETWEEN 10 AND 20"

    def test_like(self):
        assert expr_repr(Like(Field("email"), "%@gmail.com")) == "email LIKE '%@gmail.com'"

    def test_str_calls_expr_repr(self):
        expr = Gt(Field("balance"), Const(100))
        assert str(expr) == "balance > 100"

    def test_complex_nested(self):
        expr = And(
            Or(Eq(Field("a"), Const(1)), Gt(Field("b"), Const(2))),
            Not(IsNull(Field("c"))),
        )
        assert expr_repr(expr) == "((a == 1) | (b > 2)) & (~(c IS NULL))"

    def test_asymmetric(self):
        deep = And(And(Field("a"), Field("b")), Const(True))
        assert expr_depth(deep) == 3

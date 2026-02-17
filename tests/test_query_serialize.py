"""Tests for expression serialization — roundtrip + analysis + repr.

Covers uncovered lines: expr_repr for collection/null/pattern/array/json cases,
plus expr_from_dict edge cases for collection/array/json/pattern ops.
"""

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


# ===============================================================================
# Roundtrip Tests
# ===============================================================================


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
def test_roundtrip(name: str, expr: Field | Const[int]) -> None:
    serialized = expr_to_dict(expr)
    deserialized = expr_from_dict(serialized)
    assert deserialized == expr


def test_nested_roundtrip() -> None:
    expr = And(
        Or(Eq(Field("a"), Const(1)), Gt(Field("b"), Const(2))),
        Not(IsNull(Field("c"))),
    )
    assert expr_from_dict(expr_to_dict(expr)) == expr


def test_unknown_op_serialize_raises() -> None:
    class FakeExpr:
        pass

    with pytest.raises((ValueError, AttributeError)):
        expr_to_dict(FakeExpr())  # type: ignore[arg-type]


def test_unknown_op_deserialize_raises() -> None:
    with pytest.raises(ValueError, match="Unknown"):
        expr_from_dict({"op": "totally_fake"})


def test_missing_op_key_deserialize_raises() -> None:
    with pytest.raises(ValueError, match="Unknown"):
        expr_from_dict({"no_op_key": True})


# ===============================================================================
# Analysis
# ===============================================================================


class TestExprFields:
    def test_single(self) -> None:
        assert expr_fields(Field("name")) == {"name"}

    def test_const_empty(self) -> None:
        assert expr_fields(Const(42)) == set()

    def test_comparison(self) -> None:
        expr = Eq(Field("name"), Const("alice"))
        assert expr_fields(expr) == {"name"}

    def test_multiple(self) -> None:
        expr = And(
            Eq(Field("name"), Const("alice")),
            Gt(Field("balance"), Const(100)),
        )
        assert expr_fields(expr) == {"name", "balance"}

    def test_in_expr(self) -> None:
        expr = In(Field("status"), ("a", "b"))
        assert expr_fields(expr) == {"status"}

    def test_between_expr(self) -> None:
        expr = Between(Field("x"), Const(1), Const(10))
        assert expr_fields(expr) == {"x"}

    def test_json_extract_fields(self) -> None:
        expr = JsonExtract(Field("meta"), "name")
        assert expr_fields(expr) == {"meta"}

    def test_array_contains_fields(self) -> None:
        expr = ArrayContains(Field("tags"), "vip")
        assert expr_fields(expr) == {"tags"}


class TestExprComplexity:
    def test_leaf(self) -> None:
        assert expr_complexity(Field("x")) == 1
        assert expr_complexity(Const(42)) == 1

    def test_binary(self) -> None:
        assert expr_complexity(Eq(Field("x"), Const(1))) == 3

    def test_nested(self) -> None:
        expr = And(Eq(Field("a"), Const(1)), Eq(Field("b"), Const(2)))
        assert expr_complexity(expr) == 7

    def test_unary(self) -> None:
        expr = Not(Eq(Field("a"), Const(1)))
        assert expr_complexity(expr) == 4

    def test_is_null(self) -> None:
        expr = IsNull(Field("x"))
        assert expr_complexity(expr) == 2


class TestExprDepth:
    def test_leaf(self) -> None:
        assert expr_depth(Field("x")) == 1

    def test_binary(self) -> None:
        assert expr_depth(Eq(Field("x"), Const(1))) == 2

    def test_nested(self) -> None:
        expr = And(Eq(Field("a"), Const(1)), Eq(Field("b"), Const(2)))
        assert expr_depth(expr) == 3

    def test_deeply_nested(self) -> None:
        expr = And(
            Or(Eq(Field("a"), Const(1)), Gt(Field("b"), Const(2))),
            Not(IsNull(Field("c"))),
        )
        assert expr_depth(expr) == 4


# ===============================================================================
# Human-readable repr
# ===============================================================================


class TestExprRepr:
    def test_comparison(self) -> None:
        assert expr_repr(Eq(Field("x"), Const(1))) == "x == 1"

    def test_ne(self) -> None:
        assert expr_repr(Ne(Field("x"), Const(1))) == "x != 1"

    def test_lt_gt_le_ge(self) -> None:
        assert expr_repr(Lt(Field("x"), Const(10))) == "x < 10"
        assert expr_repr(Le(Field("x"), Const(10))) == "x <= 10"
        assert expr_repr(Gt(Field("x"), Const(10))) == "x > 10"
        assert expr_repr(Ge(Field("x"), Const(10))) == "x >= 10"

    def test_logical_and(self) -> None:
        expr = And(Eq(Field("a"), Const(1)), Gt(Field("b"), Const(2)))
        assert expr_repr(expr) == "(a == 1) & (b > 2)"

    def test_logical_or(self) -> None:
        expr = Or(Eq(Field("a"), Const(1)), Eq(Field("b"), Const(2)))
        assert expr_repr(expr) == "(a == 1) | (b == 2)"

    def test_not(self) -> None:
        assert expr_repr(Not(Eq(Field("x"), Const(1)))) == "~(x == 1)"

    def test_in(self) -> None:
        assert expr_repr(In(Field("status"), ("a", "b"))) == "status IN ('a', 'b')"

    def test_contains(self) -> None:
        assert expr_repr(Contains(Field("name"), "ali")) == "name.contains('ali')"

    def test_startswith(self) -> None:
        assert expr_repr(StartsWith(Field("name"), "al")) == "name.startswith('al')"

    def test_endswith(self) -> None:
        assert expr_repr(EndsWith(Field("name"), "ce")) == "name.endswith('ce')"

    def test_is_null(self) -> None:
        assert expr_repr(IsNull(Field("x"))) == "x IS NULL"
        assert expr_repr(IsNotNull(Field("x"))) == "x IS NOT NULL"

    def test_between(self) -> None:
        expr = Between(Field("x"), Const(10), Const(20))
        assert expr_repr(expr) == "x BETWEEN 10 AND 20"

    def test_like(self) -> None:
        assert expr_repr(Like(Field("email"), "%@gmail.com")) == "email LIKE '%@gmail.com'"

    def test_ilike(self) -> None:
        assert expr_repr(ILike(Field("email"), "%@GMAIL.COM")) == "email ILIKE '%@GMAIL.COM'"

    def test_regex(self) -> None:
        result = expr_repr(Regex(Field("email"), r"^\w+$"))
        assert "email" in result
        assert "~" in result

    def test_array_contains(self) -> None:
        result = expr_repr(ArrayContains(Field("tags"), "vip"))
        assert "tags" in result
        assert "@>" in result

    def test_array_any(self) -> None:
        result = expr_repr(ArrayAny(Field("tags"), ("vip", "admin")))
        assert "tags" in result
        assert "ANY" in result

    def test_array_all(self) -> None:
        result = expr_repr(ArrayAll(Field("tags"), ("vip", "verified")))
        assert "tags" in result
        assert "ALL" in result

    def test_array_overlap(self) -> None:
        result = expr_repr(ArrayOverlap(Field("tags"), ("a", "b")))
        assert "tags" in result
        assert "&&" in result

    def test_json_extract(self) -> None:
        result = expr_repr(JsonExtract(Field("meta"), "profile.name"))
        assert "meta" in result
        assert "profile.name" in result

    def test_json_contains(self) -> None:
        result = expr_repr(JsonContains(Field("meta"), {"role": "admin"}))
        assert "meta" in result
        assert "@>" in result

    def test_json_has_key(self) -> None:
        result = expr_repr(JsonHasKey(Field("meta"), "profile"))
        assert "meta" in result
        assert "?" in result

    def test_const(self) -> None:
        assert expr_repr(Const(42)) == "42"
        assert expr_repr(Const("hello")) == "'hello'"
        assert expr_repr(Const(None)) == "None"
        assert expr_repr(Const(True)) == "True"

    def test_field(self) -> None:
        assert expr_repr(Field("balance")) == "balance"

    def test_str_calls_expr_repr(self) -> None:
        expr = Gt(Field("balance"), Const(100))
        assert str(expr) == "balance > 100"

    def test_complex_nested(self) -> None:
        expr = And(
            Or(Eq(Field("a"), Const(1)), Gt(Field("b"), Const(2))),
            Not(IsNull(Field("c"))),
        )
        assert expr_repr(expr) == "((a == 1) | (b > 2)) & (~(c IS NULL))"

    def test_asymmetric(self) -> None:
        deep = And(And(Field("a"), Field("b")), Const(True))
        assert expr_depth(deep) == 3


# ===============================================================================
# Integration: Serialize Roundtrip
# ===============================================================================


class TestIntegrationSerializeRoundtrip:
    def test_complex_nested_roundtrip(self) -> None:
        expr = And(
            Or(
                Eq(Field("name"), Const("alice")),
                And(
                    Gt(Field("balance"), Const(100)),
                    Not(IsNull(Field("deleted_at"))),
                ),
            ),
            In(Field("role"), ("admin", "moderator")),
        )
        serialized = expr_to_dict(expr)
        deserialized = expr_from_dict(serialized)
        assert deserialized == expr

    def test_expr_fields_on_complex_tree(self) -> None:
        expr = And(
            Or(
                Eq(Field("name"), Const("alice")),
                Gt(Field("balance"), Const(100)),
            ),
            Not(IsNull(Field("deleted_at"))),
        )
        fields = expr_fields(expr)
        assert fields == {"name", "balance", "deleted_at"}

    def test_expr_complexity_on_complex_tree(self) -> None:
        expr = And(
            Or(
                Eq(Field("name"), Const("alice")),
                Gt(Field("balance"), Const(100)),
            ),
            Not(IsNull(Field("deleted_at"))),
        )
        assert expr_complexity(expr) == 11

    def test_expr_depth_on_complex_tree(self) -> None:
        expr = And(
            Or(
                Eq(Field("name"), Const("alice")),
                Gt(Field("balance"), Const(100)),
            ),
            Not(IsNull(Field("deleted_at"))),
        )
        assert expr_depth(expr) == 4

    def test_expr_repr_readable(self) -> None:
        expr = And(
            Or(
                Eq(Field("name"), Const("alice")),
                Gt(Field("balance"), Const(100)),
            ),
            Not(IsNull(Field("deleted_at"))),
        )
        result = expr_repr(expr)
        assert "name == 'alice'" in result
        assert "balance > 100" in result
        assert "IS NULL" in result
        assert "&" in result
        assert "|" in result

    def test_double_roundtrip(self) -> None:
        expr = Or(
            And(
                Ge(Field("score"), Const(90)),
                Like(Field("email"), "%@corp.com"),
            ),
            Between(Field("age"), Const(18), Const(65)),
        )
        first_pass = expr_from_dict(expr_to_dict(expr))
        second_pass = expr_from_dict(expr_to_dict(first_pass))
        assert second_pass == expr

    def test_array_roundtrip(self) -> None:
        """Verify all array ops survive roundtrip."""
        for expr in [
            ArrayContains(Field("tags"), "vip"),
            ArrayAny(Field("tags"), ("a", "b")),
            ArrayAll(Field("tags"), ("x", "y")),
            ArrayOverlap(Field("tags"), ("m", "n")),
        ]:
            assert expr_from_dict(expr_to_dict(expr)) == expr

    def test_json_roundtrip(self) -> None:
        """Verify all JSON ops survive roundtrip."""
        for expr in [
            JsonExtract(Field("meta"), "path.key"),
            JsonContains(Field("meta"), {"k": "v"}),
            JsonHasKey(Field("meta"), "key"),
        ]:
            assert expr_from_dict(expr_to_dict(expr)) == expr

    def test_pattern_roundtrip(self) -> None:
        """Verify all pattern ops survive roundtrip."""
        for expr in [
            Like(Field("name"), "%test%"),
            ILike(Field("name"), "%TEST%"),
            Regex(Field("name"), r"^\w+$"),
        ]:
            assert expr_from_dict(expr_to_dict(expr)) == expr

    def test_collection_roundtrip(self) -> None:
        """Verify all collection ops survive roundtrip."""
        for expr in [
            Contains(Field("name"), "test"),
            StartsWith(Field("name"), "pre"),
            EndsWith(Field("name"), "suf"),
        ]:
            assert expr_from_dict(expr_to_dict(expr)) == expr

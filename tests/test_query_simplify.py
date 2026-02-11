"""Tests for expression simplification — boolean algebra rules."""

from __future__ import annotations

from emergent.wire.axis.query._expr import And, Const, Eq, Field, Like, Not, Or
from emergent.wire.axis.query._simplify import (
    flatten_and,
    flatten_or,
    simplify_expr,
    unflatten_and,
    unflatten_or,
)


X = Field("x")
Y = Field("y")
Z = Field("z")
TRUE = Const(True)
FALSE = Const(False)
EQ_X = Eq(X, Const(1))
EQ_Y = Eq(Y, Const(2))


# ─── And simplifications ────────────────────────────────────────────────────


class TestSimplifyAnd:
    def test_and_x_true(self):
        assert simplify_expr(And(EQ_X, TRUE)) == EQ_X

    def test_and_true_x(self):
        assert simplify_expr(And(TRUE, EQ_X)) == EQ_X

    def test_and_x_false(self):
        assert simplify_expr(And(EQ_X, FALSE)) == FALSE

    def test_and_false_x(self):
        assert simplify_expr(And(FALSE, EQ_X)) == FALSE

    def test_and_x_x(self):
        assert simplify_expr(And(EQ_X, EQ_X)) == EQ_X

    def test_and_no_simplification(self):
        expr = And(EQ_X, EQ_Y)
        result = simplify_expr(expr)
        assert result == expr


# ─── Or simplifications ──────────────────────────────────────────────────────


class TestSimplifyOr:
    def test_or_x_true(self):
        assert simplify_expr(Or(EQ_X, TRUE)) == TRUE

    def test_or_true_x(self):
        assert simplify_expr(Or(TRUE, EQ_X)) == TRUE

    def test_or_x_false(self):
        assert simplify_expr(Or(EQ_X, FALSE)) == EQ_X

    def test_or_false_x(self):
        assert simplify_expr(Or(FALSE, EQ_X)) == EQ_X

    def test_or_x_x(self):
        assert simplify_expr(Or(EQ_X, EQ_X)) == EQ_X

    def test_or_no_simplification(self):
        expr = Or(EQ_X, EQ_Y)
        result = simplify_expr(expr)
        assert result == expr


# ─── Not simplifications ─────────────────────────────────────────────────────


class TestSimplifyNot:
    def test_double_negation(self):
        assert simplify_expr(Not(Not(EQ_X))) == EQ_X

    def test_not_true(self):
        assert simplify_expr(Not(TRUE)) == FALSE

    def test_not_false(self):
        assert simplify_expr(Not(FALSE)) == TRUE

    def test_not_no_simplification(self):
        expr = Not(EQ_X)
        result = simplify_expr(expr)
        assert result == expr


# ─── Nested simplification ───────────────────────────────────────────────────


class TestSimplifyNested:
    def test_nested_and_true(self):
        # And(And(x, True), y) → And(x, y)
        inner = And(EQ_X, TRUE)
        expr = And(inner, EQ_Y)
        result = simplify_expr(expr)
        assert isinstance(result, And)
        assert result.left == EQ_X
        assert result.right == EQ_Y

    def test_nested_not_not_not(self):
        # Not(Not(Not(x))) → Not(x)
        expr = Not(Not(Not(EQ_X)))
        result = simplify_expr(expr)
        assert isinstance(result, Not)
        # Inner should be EQ_X
        assert result.operand == EQ_X


# ─── Flatten / Unflatten ─────────────────────────────────────────────────────


class TestFlatten:
    def test_flatten_and(self):
        expr = And(And(EQ_X, EQ_Y), Eq(Z, Const(3)))
        parts = flatten_and(expr)
        assert len(parts) == 3

    def test_flatten_or(self):
        expr = Or(Or(EQ_X, EQ_Y), Eq(Z, Const(3)))
        parts = flatten_or(expr)
        assert len(parts) == 3

    def test_flatten_non_and(self):
        parts = flatten_and(EQ_X)
        assert parts == [EQ_X]

    def test_unflatten_and_empty(self):
        assert unflatten_and([]) == TRUE

    def test_unflatten_and_single(self):
        assert unflatten_and([EQ_X]) == EQ_X

    def test_unflatten_and_many(self):
        result = unflatten_and([EQ_X, EQ_Y, Eq(Z, Const(3))])
        assert isinstance(result, And)

    def test_unflatten_or_empty(self):
        assert unflatten_or([]) == FALSE

    def test_unflatten_or_single(self):
        assert unflatten_or([EQ_X]) == EQ_X

    def test_roundtrip_flatten_unflatten_and(self):
        expr = And(And(EQ_X, EQ_Y), Eq(Z, Const(3)))
        parts = flatten_and(expr)
        rebuilt = unflatten_and(parts)
        # Verify same parts when re-flattened
        assert flatten_and(rebuilt) == parts


# ─── Passthrough (non-optimizable expressions) ─────────────────────────────


class TestSimplifyPassthrough:
    def test_comparison_unchanged(self):
        expr = Eq(X, Const(1))
        assert simplify_expr(expr) == expr

    def test_like_unchanged(self):
        expr = Like(X, "%foo%")
        assert simplify_expr(expr) == expr

    def test_field_unchanged(self):
        assert simplify_expr(X) == X

    def test_const_unchanged(self):
        assert simplify_expr(Const(42)) == Const(42)

    def test_children_simplified_in_and(self):
        # And(Const(True), Eq(x, 1)) → Eq(x, 1)
        expr = And(TRUE, Eq(X, Const(1)))
        result = simplify_expr(expr)
        assert result == Eq(X, Const(1))

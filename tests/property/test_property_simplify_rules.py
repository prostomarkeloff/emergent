# pyright: reportPrivateUsage=false
"""Property-based tests that each simplification rule ACTUALLY fires.

Each test constructs a specific simplifiable pattern from random
non-trivial sub-expressions and verifies the STRUCTURAL transformation
(not just idempotence). Sub-expressions are comparisons that cannot be
accidentally simplified themselves.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from emergent.wire.axis.query._expr import (
    And,
    Const,
    Eq,
    Expr,
    Field,
    Gt,
    Lt,
    Not,
    Or,
)
from typing import cast
from emergent.wire.axis.query._simplify import simplify_expr


# ─── Strategies ──────────────────────────────────────────────────────────────

# Non-trivial expressions that simplify_expr will NOT simplify on their own:
# comparisons like Eq(Field("a"), Const(1)), Gt(Field("b"), Const(2)), etc.
_non_trivial_exprs: st.SearchStrategy[Expr] = st.one_of(
    st.builds(Eq, st.just(Field("a")), st.just(Const(1))),
    st.builds(Gt, st.just(Field("b")), st.just(Const(2))),
    st.builds(Lt, st.just(Field("c")), st.just(Const(3))),
    st.builds(Eq, st.just(Field("d")), st.just(Const(42))),
    st.builds(Gt, st.just(Field("e")), st.just(Const(99))),
)

_x_st = _non_trivial_exprs
_y_st = _non_trivial_exprs


# ─── And rules ───────────────────────────────────────────────────────────────


@given(x=_x_st)
@settings(max_examples=50)
def test_and_x_true_unwraps(x: Expr) -> None:
    """And(x, Const(True)) -> not isinstance(result, And) -- unwraps to x."""
    result = simplify_expr(And(x, Const(True)))
    assert not isinstance(result, And), f"Expected non-And, got {result}"
    assert result == x


@given(x=_x_st)
@settings(max_examples=50)
def test_and_true_x_unwraps(x: Expr) -> None:
    """And(Const(True), x) -> not isinstance(result, And) -- unwraps to x."""
    result = simplify_expr(And(Const(True), x))
    assert not isinstance(result, And), f"Expected non-And, got {result}"
    assert result == x


@given(x=_x_st)
@settings(max_examples=50)
def test_and_x_false_is_false(x: Expr) -> None:
    """And(x, Const(False)) -> isinstance(result, Const) and result.value is False."""
    result = simplify_expr(And(x, Const(False)))
    assert isinstance(result, Const), f"Expected Const, got {type(result).__name__}"
    assert cast(Const[bool], result).value is False


@given(x=_x_st)
@settings(max_examples=50)
def test_and_false_x_is_false(x: Expr) -> None:
    """And(Const(False), x) -> isinstance(result, Const) and result.value is False."""
    result = simplify_expr(And(Const(False), x))
    assert isinstance(result, Const), f"Expected Const, got {type(result).__name__}"
    assert cast(Const[bool], result).value is False


@given(x=_x_st)
@settings(max_examples=50)
def test_and_x_x_identity(x: Expr) -> None:
    """And(x, x) -> result == x (identity by equality)."""
    result = simplify_expr(And(x, x))
    assert result == x


# ─── Or rules ────────────────────────────────────────────────────────────────


@given(x=_x_st)
@settings(max_examples=50)
def test_or_x_true_is_true(x: Expr) -> None:
    """Or(x, Const(True)) -> isinstance(result, Const) and result.value is True."""
    result = simplify_expr(Or(x, Const(True)))
    assert isinstance(result, Const), f"Expected Const, got {type(result).__name__}"
    assert cast(Const[bool], result).value is True


@given(x=_x_st)
@settings(max_examples=50)
def test_or_true_x_is_true(x: Expr) -> None:
    """Or(Const(True), x) -> isinstance(result, Const) and result.value is True."""
    result = simplify_expr(Or(Const(True), x))
    assert isinstance(result, Const), f"Expected Const, got {type(result).__name__}"
    assert cast(Const[bool], result).value is True


@given(x=_x_st)
@settings(max_examples=50)
def test_or_x_false_unwraps(x: Expr) -> None:
    """Or(x, Const(False)) -> not isinstance(result, Or) -- unwraps to x."""
    result = simplify_expr(Or(x, Const(False)))
    assert not isinstance(result, Or), f"Expected non-Or, got {result}"
    assert result == x


@given(x=_x_st)
@settings(max_examples=50)
def test_or_false_x_unwraps(x: Expr) -> None:
    """Or(Const(False), x) -> not isinstance(result, Or) -- unwraps to x."""
    result = simplify_expr(Or(Const(False), x))
    assert not isinstance(result, Or), f"Expected non-Or, got {result}"
    assert result == x


@given(x=_x_st)
@settings(max_examples=50)
def test_or_x_x_identity(x: Expr) -> None:
    """Or(x, x) -> result == x (identity by equality)."""
    result = simplify_expr(Or(x, x))
    assert result == x


# ─── Not rules ───────────────────────────────────────────────────────────────


@given(x=_x_st)
@settings(max_examples=50)
def test_not_not_double_negation(x: Expr) -> None:
    """Not(Not(x)) -> not isinstance(result, Not) -- double negation eliminated."""
    result = simplify_expr(Not(Not(x)))
    assert not isinstance(result, Not), f"Expected non-Not, got {result}"
    assert result == x


def test_not_true_is_false() -> None:
    """Not(Const(True)) -> result == Const(False)."""
    result = simplify_expr(Not(Const(True)))
    assert result == Const(False)


def test_not_false_is_true() -> None:
    """Not(Const(False)) -> result == Const(True)."""
    result = simplify_expr(Not(Const(False)))
    assert result == Const(True)


# ─── Recursive rules ────────────────────────────────────────────────────────


@given(x=_x_st, y=_y_st)
@settings(max_examples=50)
def test_recursive_and_inner_true(x: Expr, y: Expr) -> None:
    """And(And(x, Const(True)), y) -> inner And simplified away.
    When x != y: result is And(x, y).
    When x == y: And(x, x) rule fires, result is x."""
    expr = And(And(x, Const(True)), y)
    result = simplify_expr(expr)
    if x == y:
        # And(x, x) -> x fires after inner simplification
        assert result == x
    else:
        # Inner And(x, True) -> x, so result is And(x, y)
        assert isinstance(result, And), f"Expected And, got {type(result).__name__}"
        assert result.left == x, (
            f"Inner And not simplified: expected left={x}, got left={result.left}"
        )
        assert result.right == y


@given(x=_x_st, y=_y_st)
@settings(max_examples=50)
def test_recursive_or_inner_false(x: Expr, y: Expr) -> None:
    """Or(And(x, Const(False)), y) -> inner And simplified to Const(False),
    then Or(Const(False), y) -> y."""
    expr = Or(And(x, Const(False)), y)
    result = simplify_expr(expr)
    # And(x, False) -> Const(False), then Or(Const(False), y) -> y
    assert result == y, (
        f"Recursive simplification failed: expected {y}, got {result}"
    )
    assert not isinstance(result, Or), (
        f"Or should have been eliminated, got {result}"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Mutation-killing tests — targeted at surviving mutants
# ═══════════════════════════════════════════════════════════════════════════════


@given(x=_x_st)
@settings(max_examples=50)
def test_and_false_left_only_still_false(x: Expr) -> None:
    """And(Const(False), x) where x is NOT false -> result is Const(False).

    Kills mutant: L75 `or` -> `and` in `_is_false(left_s) or _is_false(right_s)`.
    With `and`, only And(Const(False), Const(False)) returns False — misses this.
    """
    result = simplify_expr(And(Const(False), x))
    assert isinstance(result, Const)
    assert cast(Const[bool], result).value is False


@given(x=_x_st)
@settings(max_examples=50)
def test_and_false_right_only_still_false(x: Expr) -> None:
    """And(x, Const(False)) where x is NOT false -> result is Const(False).

    Same mutant kill — tests right-false separately from left-false.
    """
    result = simplify_expr(And(x, Const(False)))
    assert isinstance(result, Const)
    assert cast(Const[bool], result).value is False


def test_and_false_false_value_is_false_not_true() -> None:
    """And(Const(False), Const(False)) must return Const(False), not Const(True).

    Kills mutant: L76 `Const(False)` -> `Const(True)`.
    """
    result = simplify_expr(And(Const(False), Const(False)))
    assert isinstance(result, Const)
    assert cast(Const[bool], result).value is False
    assert cast(Const[bool], result).value is not True


@given(x=_x_st)
@settings(max_examples=50)
def test_identity_optimization_and(x: Expr) -> None:
    """When simplification changes children, result is new And, not original.

    Kills mutant: L83 `or` -> `and` in identity check.
    Inner And(x, True) simplifies left to x, right is True→x. Result should
    be structurally different from input.
    """
    inner = And(x, Const(True))  # simplifies to x
    outer = And(inner, x)  # simplifies to And(x, x) then to x
    result = simplify_expr(outer)
    assert result == x  # fully simplified
    assert result is not outer  # not the original object


@given(x=_x_st)
@settings(max_examples=50)
def test_identity_optimization_or(x: Expr) -> None:
    """Same for Or — when children change, new Or is returned.

    Kills mutant: L107 `or` -> `and` in identity check.
    """
    inner = Or(x, Const(False))  # simplifies to x
    outer = Or(inner, x)  # simplifies to Or(x, x) then to x
    result = simplify_expr(outer)
    assert result == x


def test_simplify_children_actually_simplifies() -> None:
    """_simplify_children must apply changes when children changed.

    Kills mutant: L203 `not changes` -> `changes`.
    If flipped, _simplify_children returns original when children changed
    and reconstructs when nothing changed — backwards.
    """
    from emergent.wire.axis.query._expr import Between

    # Between(Field("x"), And(Field("y"), Const(True)), Const(5))
    # _simplify_children should simplify the And inside Between
    inner_and = And(Field("y"), Const(True))
    expr = Between(Field("x"), inner_and, Const(5))
    result = simplify_expr(expr)

    # The inner And(y, True) should be simplified to Field("y")
    assert isinstance(result, Between)
    assert result.low == Field("y"), (
        f"Inner And not simplified in Between.low: got {result.low}"
    )
    assert result.low is not inner_and  # must be different object


def test_is_true_returns_true_not_none() -> None:
    """_is_true(Const(True)) must return True (bool), not None.

    Kills mutant: L205/213/221 `return value` -> `return None`.
    Python treats None as falsy so returning None acts like False in `if`,
    but the function's contract is to return bool.
    """
    from emergent.wire.axis.query._simplify import _is_true, _is_false

    assert _is_true(Const(True)) is True
    assert _is_true(Const(False)) is False
    assert _is_true(Field("x")) is False

    assert _is_false(Const(False)) is True
    assert _is_false(Const(True)) is False
    assert _is_false(Field("x")) is False

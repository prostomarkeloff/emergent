"""Behavioral tests for expression coercion — query semantics are preserved.

Every test builds an Expr, applies ExprCoercer, and verifies that
evaluation results are semantically correct on corresponding data.
"""

from __future__ import annotations

from dataclasses import dataclass

from emergent.wire.axis.query._coerce import ExprCoercer
from emergent.wire.axis.query._expr import (
    Eq,
    Ne,
    Gt,
    Lt,
    Ge,
    Le,
    And,
    Or,
    Not,
    In,
    Field,
    Const,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Helper: simple object for expr evaluation
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class Obj:
    """Minimal object for Expr.evaluate()."""
    value: int = 0
    x: int = 0
    y: int = 0
    status: str = ""


# ═══════════════════════════════════════════════════════════════════════════════
# Coerced expr evaluates same on coerced data
# ═══════════════════════════════════════════════════════════════════════════════


def test_coerced_expr_evaluates_correctly_on_coerced_data() -> None:
    """Coercion: value * 2.
    Original: Eq(Field('value'), Const(5)) on entity with value=5 -> True.
    Coerced: Eq(Field('value'), Const(10)) on entity with value=10 -> True (same semantics).
    """
    coercer = ExprCoercer({"value": lambda x: x * 2})

    original_expr = Eq(Field("value"), Const(5))
    coerced_expr = coercer(original_expr)

    # Original evaluates true on original data
    original_obj = Obj(value=5)
    assert original_expr.evaluate(original_obj) is True

    # Coerced evaluates true on coerced data
    coerced_obj = Obj(value=10)
    assert coerced_expr.evaluate(coerced_obj) is True

    # The coerced expr's Const value was actually transformed
    assert coerced_expr.right.value == 10  # type: ignore[union-attr]


def test_coercion_preserves_rejection_semantics() -> None:
    """Coercion preserves False results too: value=3 does NOT match Const(5)."""
    coercer = ExprCoercer({"value": lambda x: x * 2})

    original_expr = Eq(Field("value"), Const(5))
    coerced_expr = coercer(original_expr)

    # Original rejects wrong value
    assert original_expr.evaluate(Obj(value=3)) is False

    # Coerced rejects wrong coerced value (6 != 10)
    assert coerced_expr.evaluate(Obj(value=6)) is False


# ═══════════════════════════════════════════════════════════════════════════════
# No-op coercer preserves expr identity
# ═══════════════════════════════════════════════════════════════════════════════


def test_noop_coercer_preserves_expr_identity() -> None:
    """ExprCoercer({}) returns the exact same expr object (identity)."""
    expr = Eq(Field("value"), Const(5))
    coercer = ExprCoercer({})

    result = coercer(expr)
    assert result is expr


def test_noop_coercer_preserves_evaluation() -> None:
    """ExprCoercer({}) does not change evaluation results."""
    expr = Gt(Field("value"), Const(3))
    coercer = ExprCoercer({})

    result = coercer(expr)
    assert result.evaluate(Obj(value=5)) is True
    assert result.evaluate(Obj(value=2)) is False


# ═══════════════════════════════════════════════════════════════════════════════
# Coercion is idempotent on evaluation
# ═══════════════════════════════════════════════════════════════════════════════


def test_coercion_semantics_preserved_across_data_transform() -> None:
    """Coerced expr on coerced data gives same truth value as original on original data.

    If coercion is f(x) = x + 10, and original expr matches value=5,
    then coerced expr matches value=15 (the coerced value of 5).
    """
    coerce_fn = lambda x: x + 10
    coercer = ExprCoercer({"value": coerce_fn})

    expr = Eq(Field("value"), Const(5))
    coerced = coercer(expr)

    # Original matches value=5
    assert expr.evaluate(Obj(value=5)) is True
    # Coerced matches value=15 (= coerce_fn(5))
    assert coerced.evaluate(Obj(value=15)) is True

    # Original rejects value=3
    assert expr.evaluate(Obj(value=3)) is False
    # Coerced rejects value=13 (= coerce_fn(3))
    assert coerced.evaluate(Obj(value=13)) is False


def test_coercion_semantics_preserved_gt() -> None:
    """Coerced Gt expr on coerced data gives same truth value as original on original."""
    coerce_fn = lambda v: v * 3
    coercer = ExprCoercer({"x": coerce_fn})

    expr = Gt(Field("x"), Const(10))
    coerced = coercer(expr)

    # Original: x > 10 — true for x=11, false for x=10
    assert expr.evaluate(Obj(x=11)) is True
    assert expr.evaluate(Obj(x=10)) is False

    # Coerced: x > 30 — true for x=31 (coerced 11 would be 33 > 30), false for x=30
    assert coerced.evaluate(Obj(x=31)) is True
    assert coerced.evaluate(Obj(x=30)) is False


# ═══════════════════════════════════════════════════════════════════════════════
# And/Or coercion recurses correctly
# ═══════════════════════════════════════════════════════════════════════════════


def test_and_coercion_recurses_both_sides() -> None:
    """coerce(And(Eq(x, 1), Gt(x, 0))) with x:*2 transforms both sub-exprs."""
    coercer = ExprCoercer({"x": lambda v: v * 2})

    expr = And(
        Eq(Field("x"), Const(1)),
        Gt(Field("x"), Const(0)),
    )
    coerced = coercer(expr)

    # On coerced data: x=2 should match Eq(x, 2) and Gt(x, 0) => True AND True
    assert coerced.evaluate(Obj(x=2)) is True

    # On original data with wrong coerced value: x=1 matches Eq(x, 2)? No => False
    assert coerced.evaluate(Obj(x=1)) is False


def test_or_coercion_recurses_both_sides() -> None:
    """coerce(Or(Eq(x, 5), Eq(x, 10))) with x:*2 -> Or(Eq(x,10), Eq(x,20))."""
    coercer = ExprCoercer({"x": lambda v: v * 2})

    expr = Or(
        Eq(Field("x"), Const(5)),
        Eq(Field("x"), Const(10)),
    )
    coerced = coercer(expr)

    # x=10 matches left side (5*2=10)
    assert coerced.evaluate(Obj(x=10)) is True
    # x=20 matches right side (10*2=20)
    assert coerced.evaluate(Obj(x=20)) is True
    # x=5 matches neither coerced side
    assert coerced.evaluate(Obj(x=5)) is False


def test_nested_and_or_coercion() -> None:
    """And(Or(...), Eq(...)) coerces all leaves."""
    coercer = ExprCoercer({"x": lambda v: v + 100})

    expr = And(
        Or(Eq(Field("x"), Const(1)), Eq(Field("x"), Const(2))),
        Gt(Field("x"), Const(0)),
    )
    coerced = coercer(expr)

    # x=101 should match: Or(Eq(x, 101), Eq(x, 102)) -> True, Gt(x, 100) -> True
    assert coerced.evaluate(Obj(x=101)) is True

    # x=100 should fail: Or(Eq(x, 101), Eq(x, 102)) -> False
    assert coerced.evaluate(Obj(x=100)) is False


# ═══════════════════════════════════════════════════════════════════════════════
# In coercion transforms all values
# ═══════════════════════════════════════════════════════════════════════════════


def test_in_coercion_transforms_all_values() -> None:
    """coerce(In(Field('x'), (1, 2, 3))) with x:*2 -> In(Field('x'), (2, 4, 6))."""
    coercer = ExprCoercer({"x": lambda v: v * 2})

    expr = In(Field("x"), (1, 2, 3))
    coerced = coercer(expr)

    # Coerced values: 2, 4, 6
    assert coerced.evaluate(Obj(x=2)) is True
    assert coerced.evaluate(Obj(x=4)) is True
    assert coerced.evaluate(Obj(x=6)) is True

    # Original values should NOT match coerced expr
    assert coerced.evaluate(Obj(x=1)) is False
    assert coerced.evaluate(Obj(x=3)) is False


def test_in_coercion_with_no_matching_field_unchanged() -> None:
    """In on field 'y' with coercion only for 'x' passes through unchanged."""
    coercer = ExprCoercer({"x": lambda v: v * 2})

    expr = In(Field("y"), (10, 20, 30))
    coerced = coercer(expr)

    # Values unchanged — original values still match
    assert coerced.evaluate(Obj(y=10)) is True
    assert coerced.evaluate(Obj(y=20)) is True
    assert coerced.evaluate(Obj(y=5)) is False


# ═══════════════════════════════════════════════════════════════════════════════
# Not coercion
# ═══════════════════════════════════════════════════════════════════════════════


def test_not_coercion_propagates() -> None:
    """Not(Eq(x, 5)) with x:*2 -> Not(Eq(x, 10))."""
    coercer = ExprCoercer({"x": lambda v: v * 2})

    expr = Not(Eq(Field("x"), Const(5)))
    coerced = coercer(expr)

    # x=10 matches inner Eq => Not(True) => False
    assert coerced.evaluate(Obj(x=10)) is False
    # x=9 does not match inner Eq => Not(False) => True
    assert coerced.evaluate(Obj(x=9)) is True


# ═══════════════════════════════════════════════════════════════════════════════
# Multiple field coercion
# ═══════════════════════════════════════════════════════════════════════════════


def test_multi_field_coercion() -> None:
    """Coercion applies independently per field."""
    coercer = ExprCoercer({
        "x": lambda v: v * 2,
        "y": lambda v: v + 100,
    })

    expr = And(
        Eq(Field("x"), Const(5)),
        Eq(Field("y"), Const(10)),
    )
    coerced = coercer(expr)

    # x coerced: 5*2=10, y coerced: 10+100=110
    assert coerced.evaluate(Obj(x=10, y=110)) is True
    assert coerced.evaluate(Obj(x=10, y=10)) is False
    assert coerced.evaluate(Obj(x=5, y=110)) is False


# ═══════════════════════════════════════════════════════════════════════════════
# Comparison operators all coerce correctly
# ═══════════════════════════════════════════════════════════════════════════════


def test_lt_coercion() -> None:
    """Lt(Field('x'), Const(10)) with x:*3 -> Lt(Field('x'), Const(30))."""
    coercer = ExprCoercer({"x": lambda v: v * 3})

    expr = Lt(Field("x"), Const(10))
    coerced = coercer(expr)

    assert coerced.evaluate(Obj(x=29)) is True
    assert coerced.evaluate(Obj(x=30)) is False


def test_le_coercion() -> None:
    """Le(Field('x'), Const(10)) with x:*3 -> Le(Field('x'), Const(30))."""
    coercer = ExprCoercer({"x": lambda v: v * 3})

    expr = Le(Field("x"), Const(10))
    coerced = coercer(expr)

    assert coerced.evaluate(Obj(x=30)) is True
    assert coerced.evaluate(Obj(x=31)) is False


def test_ge_coercion() -> None:
    """Ge(Field('x'), Const(10)) with x:*3 -> Ge(Field('x'), Const(30))."""
    coercer = ExprCoercer({"x": lambda v: v * 3})

    expr = Ge(Field("x"), Const(10))
    coerced = coercer(expr)

    assert coerced.evaluate(Obj(x=30)) is True
    assert coerced.evaluate(Obj(x=29)) is False


def test_ne_coercion() -> None:
    """Ne(Field('x'), Const(5)) with x:*2 -> Ne(Field('x'), Const(10))."""
    coercer = ExprCoercer({"x": lambda v: v * 2})

    expr = Ne(Field("x"), Const(5))
    coerced = coercer(expr)

    assert coerced.evaluate(Obj(x=10)) is False  # 10 == 10, so Ne is False
    assert coerced.evaluate(Obj(x=9)) is True    # 9 != 10, so Ne is True

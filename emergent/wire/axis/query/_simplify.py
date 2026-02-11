"""Expression simplification — boolean algebra optimizations.

Pure functions for expression tree optimization.

    from emergent.wire.axis.query import simplify_expr, normalize_expr

    # Simplify redundant expressions
    simplified = simplify_expr(And(x, Const(True)))  # → x

    # Normalize to canonical form
    normalized = normalize_expr(expr)
"""

from __future__ import annotations

import dataclasses as _dc
from typing import Any, cast

from emergent.wire.axis.query._expr import (
    Expr,
    Const,
    And,
    Or,
    Not,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Simplification Rules
# ═══════════════════════════════════════════════════════════════════════════════


def simplify_expr(expr: Expr) -> Expr:
    """Simplify expression using boolean algebra rules.

    Rules applied:
        - And(x, True) → x
        - And(x, False) → False
        - And(x, x) → x
        - Or(x, True) → True
        - Or(x, False) → x
        - Or(x, x) → x
        - Not(Not(x)) → x
        - Not(True) → False
        - Not(False) → True

    Args:
        expr: Expression to simplify

    Returns:
        Simplified expression

    Example:
        # And with True
        simplify_expr(And(Field("x"), Const(True)))
        # → Field("x")

        # Double negation
        simplify_expr(Not(Not(Field("x"))))
        # → Field("x")
    """
    match expr:
        # And simplifications
        case And(left=left, right=right):
            left_s = simplify_expr(left)
            right_s = simplify_expr(right)

            # And(x, True) → x
            if _is_true(right_s):
                return left_s
            if _is_true(left_s):
                return right_s

            # And(x, False) → False
            if _is_false(left_s) or _is_false(right_s):
                return Const(False)

            # And(x, x) → x
            if left_s == right_s:
                return left_s

            # Return simplified if changed
            if left_s is not left or right_s is not right:
                return And(left_s, right_s)
            return expr

        # Or simplifications
        case Or(left=left, right=right):
            left_s = simplify_expr(left)
            right_s = simplify_expr(right)

            # Or(x, True) → True
            if _is_true(left_s) or _is_true(right_s):
                return Const(True)

            # Or(x, False) → x
            if _is_false(right_s):
                return left_s
            if _is_false(left_s):
                return right_s

            # Or(x, x) → x
            if left_s == right_s:
                return left_s

            # Return simplified if changed
            if left_s is not left or right_s is not right:
                return Or(left_s, right_s)
            return expr

        # Not simplifications
        case Not(operand=operand):
            inner = simplify_expr(operand)

            # Not(Not(x)) → x
            if isinstance(inner, Not):
                return inner.operand

            # Not(True) → False
            if _is_true(inner):
                return Const(False)

            # Not(False) → True
            if _is_false(inner):
                return Const(True)

            if inner is not operand:
                return Not(inner)
            return expr

        # All other nodes — recursively simplify Expr children
        case _:
            return _simplify_children(expr)


# ═══════════════════════════════════════════════════════════════════════════════
# Flattening — flatten nested And/Or
# ═══════════════════════════════════════════════════════════════════════════════


def flatten_and(expr: Expr) -> list[Expr]:
    """Flatten nested And into list of conjuncts.

    And(And(a, b), c) → [a, b, c]
    """
    match expr:
        case And(left=left, right=right):
            return flatten_and(left) + flatten_and(right)
        case _:
            return [expr]


def flatten_or(expr: Expr) -> list[Expr]:
    """Flatten nested Or into list of disjuncts.

    Or(Or(a, b), c) → [a, b, c]
    """
    match expr:
        case Or(left=left, right=right):
            return flatten_or(left) + flatten_or(right)
        case _:
            return [expr]


def unflatten_and(exprs: list[Expr]) -> Expr:
    """Build And tree from list of conjuncts."""
    if not exprs:
        return Const(True)
    result = exprs[0]
    for e in exprs[1:]:
        result = And(result, e)
    return result


def unflatten_or(exprs: list[Expr]) -> Expr:
    """Build Or tree from list of disjuncts."""
    if not exprs:
        return Const(False)
    result = exprs[0]
    for e in exprs[1:]:
        result = Or(result, e)
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _simplify_children(expr: Expr) -> Expr:
    """Recursively simplify all Expr children of a node.

    Uses dataclass fields introspection to find Expr children,
    simplifies them, and reconstructs the node only if something changed.
    """
    changes: dict[str, Expr] = {}
    for f in _dc.fields(expr):  # type: ignore[arg-type]
        val = getattr(expr, f.name)
        if isinstance(val, Expr):
            simplified = simplify_expr(val)
            if simplified is not val:
                changes[f.name] = simplified
    if not changes:
        return expr
    return _dc.replace(expr, **changes)  # type: ignore[type-var]


def _is_true(expr: Expr) -> bool:
    """Check if expression is Const(True)."""
    if isinstance(expr, Const):
        val: Any = cast(Const[Any], expr).value
        return val is True
    return False


def _is_false(expr: Expr) -> bool:
    """Check if expression is Const(False)."""
    if isinstance(expr, Const):
        val: Any = cast(Const[Any], expr).value
        return val is False
    return False




__all__ = (
    "simplify_expr",
    "flatten_and",
    "flatten_or",
    "unflatten_and",
    "unflatten_or",
)

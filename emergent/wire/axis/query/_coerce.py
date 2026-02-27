"""Expr coercion — AST transform that applies storage coercion to query values.

ExprCoercer is a compiled artifact: compile once from capabilities, use with any Expr.
Produced by compile_sa's assembler, stored on Compilation.expr_transform.

    from emergent.wire.axis.query._coerce import ExprCoercer

    coercer = ExprCoercer({"payload": to_storage_fn})
    coerced_expr = coercer(expr)  # Const values transformed for storage
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from emergent.wire.axis.query._expr import (
    Expr,
    Field,
    Const,
    Eq,
    Ne,
    Lt,
    Le,
    Gt,
    Ge,
    And,
    Or,
    Not,
    In,
    Between,
    Contains,
    StartsWith,
    EndsWith,
    Like,
    ILike,
)


@dataclass(frozen=True, slots=True)
class ExprCoercer:
    """Compiled Expr transform — coerces Const values at comparison nodes.

    Produced by backend assemblers (compile_sa, etc.), stored on Compilation.
    No-op when coercion map is empty.
    """

    _coercion: Mapping[str, Callable[[object], object]]

    def __call__(self, expr: Expr) -> Expr:
        if not self._coercion:
            return expr
        return _coerce_expr(expr, self._coercion)

    def __bool__(self) -> bool:
        return bool(self._coercion)


# ═══════════════════════════════════════════════════════════════════════════════
# Pure AST walk — the engine
# ═══════════════════════════════════════════════════════════════════════════════


def _coerce_const(field_name: str, value: object, coercion: Mapping[str, Callable[[object], object]]) -> object:
    """Apply coercion to a raw value if the field has a coercion function."""
    fn = coercion.get(field_name)
    if fn is not None:
        return fn(value)
    return value


def _field_name(expr: Expr) -> str | None:
    """Extract field name from a Field node, or None."""
    if isinstance(expr, Field):
        return expr.name
    return None


def _coerce_binary(
    left: Expr,
    right: Expr,
    coercion: Mapping[str, Callable[[object], object]],
    node_type: type,
) -> Expr:
    """Coerce a binary comparison node (Eq, Ne, Lt, Le, Gt, Ge).

    If one side is Field and other is Const, apply coercion to the Const value.
    """
    l_name = _field_name(left)
    r_name = _field_name(right)

    new_left = left
    new_right = right

    if l_name is not None and isinstance(right, Const):
        new_right = Const(_coerce_const(l_name, right.value, coercion))
    elif r_name is not None and isinstance(left, Const):
        new_left = Const(_coerce_const(r_name, left.value, coercion))
    else:
        new_left = _coerce_expr(left, coercion)
        new_right = _coerce_expr(right, coercion)

    return node_type(left=new_left, right=new_right)


def _coerce_expr(expr: Expr, coercion: Mapping[str, Callable[[object], object]]) -> Expr:
    """Walk Expr AST, coerce Const values for fields with coercion."""
    match expr:
        # Binary comparisons
        case Eq(left=left, right=right):
            return _coerce_binary(left, right, coercion, Eq)
        case Ne(left=left, right=right):
            return _coerce_binary(left, right, coercion, Ne)
        case Lt(left=left, right=right):
            return _coerce_binary(left, right, coercion, Lt)
        case Le(left=left, right=right):
            return _coerce_binary(left, right, coercion, Le)
        case Gt(left=left, right=right):
            return _coerce_binary(left, right, coercion, Gt)
        case Ge(left=left, right=right):
            return _coerce_binary(left, right, coercion, Ge)

        # Logical — recurse
        case And(left=left, right=right):
            return And(left=_coerce_expr(left, coercion), right=_coerce_expr(right, coercion))
        case Or(left=left, right=right):
            return Or(left=_coerce_expr(left, coercion), right=_coerce_expr(right, coercion))
        case Not(operand=operand):
            return Not(operand=_coerce_expr(operand, coercion))

        # In — coerce each value
        case In(field=field, values=values):
            name = _field_name(field)
            if name is not None:
                fn = coercion.get(name)
                if fn is not None:
                    return In(field=field, values=[fn(v) for v in values])
            return expr

        # Between — coerce low/high
        case Between(field=field, low=low, high=high):
            name = _field_name(field)
            if name is not None:
                new_low = Const(_coerce_const(name, low.value, coercion)) if isinstance(low, Const) else low
                new_high = Const(_coerce_const(name, high.value, coercion)) if isinstance(high, Const) else high
                return Between(field=field, low=new_low, high=new_high)
            return expr

        # String ops — coerce the string argument
        case Contains(field=field, substring=substring):
            name = _field_name(field)
            if name is not None:
                return Contains(field=field, substring=_coerce_const(name, substring, coercion))
            return expr
        case StartsWith(field=field, prefix=prefix):
            name = _field_name(field)
            if name is not None:
                return StartsWith(field=field, prefix=_coerce_const(name, prefix, coercion))
            return expr
        case EndsWith(field=field, suffix=suffix):
            name = _field_name(field)
            if name is not None:
                return EndsWith(field=field, suffix=_coerce_const(name, suffix, coercion))
            return expr
        case Like(field=field, pattern=pattern):
            name = _field_name(field)
            if name is not None:
                return Like(field=field, pattern=_coerce_const(name, pattern, coercion))
            return expr
        case ILike(field=field, pattern=pattern):
            name = _field_name(field)
            if name is not None:
                return ILike(field=field, pattern=_coerce_const(name, pattern, coercion))
            return expr

        # Everything else — pass through unchanged
        case _:
            return expr


__all__ = (
    "ExprCoercer",
)

"""Expr coercion — AST transform that applies storage coercion to query values.

ExprCoercer is a compiled artifact: compile once from capabilities, use with any Expr.
Produced by compile_sa's assembler, stored on Compilation.expr_transform.

    from emergent.wire.axis.query._coerce import ExprCoercer

    coercer = ExprCoercer({"payload": to_storage_fn})
    coerced_expr = coercer(expr)  # Const values transformed for storage

Open-world via fold_expr: unknown Expr types pass through unchanged.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TypeGuard

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
    ExprHandler,
    fold_expr,
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
        return fold_expr(expr, _build_coerce_handlers(self._coercion), default=_passthrough)

    def __bool__(self) -> bool:
        return bool(self._coercion)


# ═══════════════════════════════════════════════════════════════════════════════
# Handler construction — closures over coercion map
# ═══════════════════════════════════════════════════════════════════════════════


def _passthrough(node: Expr, recurse: Callable[[Expr], Expr]) -> Expr:
    """Default handler: pass through unknown Expr types unchanged (open-world)."""
    return node


def _coerce_const(field_name: str, value: object, coercion: Mapping[str, Callable[[object], object]]) -> object:
    """Apply coercion to a raw value if the field has a coercion function."""
    fn = coercion.get(field_name)
    if fn is not None:
        return fn(value)
    return value


def _is_const(expr: Expr) -> TypeGuard[Const[object]]:
    """Narrow Expr to Const[object] — avoids Const[Unknown] from plain isinstance."""
    return isinstance(expr, Const)


def _field_name(expr: Expr) -> str | None:
    """Extract field name from a Field node, or None."""
    if isinstance(expr, Field):
        return expr.name
    return None


def _make_binary_handler(
    node_type: type[Eq] | type[Ne] | type[Lt] | type[Le] | type[Gt] | type[Ge],
    coercion: Mapping[str, Callable[[object], object]],
) -> ExprHandler[Expr]:
    """Create a handler for binary comparison nodes (Eq, Ne, Lt, Le, Gt, Ge).

    If one side is Field and other is Const, apply coercion to the Const value.
    """
    def handler(node: Expr, recurse: Callable[[Expr], Expr]) -> Expr:
        children = node.children()
        if len(children) < 2:
            return node
        left, right = children[0], children[1]
        l_name = _field_name(left)
        r_name = _field_name(right)

        new_left: Expr = left
        new_right: Expr = right

        if l_name is not None and _is_const(right):
            new_right = Const(_coerce_const(l_name, right.value, coercion))
        elif r_name is not None and _is_const(left):
            new_left = Const(_coerce_const(r_name, left.value, coercion))
        else:
            new_left = recurse(left)
            new_right = recurse(right)

        return node_type(left=new_left, right=new_right)
    return handler


def _make_field_string_handler(
    node_type: type[Contains] | type[StartsWith] | type[EndsWith] | type[Like] | type[ILike],
    attr_name: str,
    coercion: Mapping[str, Callable[[object], object]],
) -> ExprHandler[Expr]:
    """Create a handler for field+string ops (Contains, StartsWith, EndsWith, Like, ILike)."""
    def handler(node: Expr, recurse: Callable[[Expr], Expr]) -> Expr:
        if not isinstance(node, (Contains, StartsWith, EndsWith, Like, ILike)):
            return node
        name = _field_name(node.field)
        if name is None:
            return node
        value: object = getattr(node, attr_name)
        coerced = _coerce_const(name, value, coercion)
        coerced_str = coerced if isinstance(coerced, str) else str(coerced)
        return node_type(field=node.field, **{attr_name: coerced_str})
    return handler


def _and_handler(node: Expr, recurse: Callable[[Expr], Expr]) -> Expr:
    if isinstance(node, And):
        return And(left=recurse(node.left), right=recurse(node.right))
    return node


def _or_handler(node: Expr, recurse: Callable[[Expr], Expr]) -> Expr:
    if isinstance(node, Or):
        return Or(left=recurse(node.left), right=recurse(node.right))
    return node


def _not_handler(node: Expr, recurse: Callable[[Expr], Expr]) -> Expr:
    if isinstance(node, Not):
        return Not(operand=recurse(node.operand))
    return node


def _in_handler(coercion: Mapping[str, Callable[[object], object]]) -> ExprHandler[Expr]:
    def handler(node: Expr, recurse: Callable[[Expr], Expr]) -> Expr:
        if isinstance(node, In):
            return _coerce_in(node, coercion)
        return node
    return handler


def _between_handler(coercion: Mapping[str, Callable[[object], object]]) -> ExprHandler[Expr]:
    def handler(node: Expr, recurse: Callable[[Expr], Expr]) -> Expr:
        if isinstance(node, Between):
            return _coerce_between(node, coercion)
        return node
    return handler


def _build_coerce_handlers(
    coercion: Mapping[str, Callable[[object], object]],
) -> dict[type, ExprHandler[Expr]]:
    """Build handler map for coercion — closures capture the coercion map."""
    handlers: dict[type, ExprHandler[Expr]] = {
        # Leaf nodes — pass through
        Field: _passthrough,
        Const: _passthrough,

        # Binary comparisons — coerce Const values
        Eq: _make_binary_handler(Eq, coercion),
        Ne: _make_binary_handler(Ne, coercion),
        Lt: _make_binary_handler(Lt, coercion),
        Le: _make_binary_handler(Le, coercion),
        Gt: _make_binary_handler(Gt, coercion),
        Ge: _make_binary_handler(Ge, coercion),

        # Logical — recurse children
        And: _and_handler,
        Or: _or_handler,
        Not: _not_handler,

        # In — coerce each value
        In: _in_handler(coercion),

        # Between — coerce low/high
        Between: _between_handler(coercion),

        # String ops — coerce the string argument
        Contains: _make_field_string_handler(Contains, "substring", coercion),
        StartsWith: _make_field_string_handler(StartsWith, "prefix", coercion),
        EndsWith: _make_field_string_handler(EndsWith, "suffix", coercion),
        Like: _make_field_string_handler(Like, "pattern", coercion),
        ILike: _make_field_string_handler(ILike, "pattern", coercion),
    }
    return handlers


def _coerce_in(node: In, coercion: Mapping[str, Callable[[object], object]]) -> Expr:
    """Coerce In values."""
    name = _field_name(node.field)
    if name is not None:
        fn = coercion.get(name)
        if fn is not None:
            return In(field=node.field, values=tuple(fn(v) for v in node.values))
    return node


def _coerce_between(node: Between, coercion: Mapping[str, Callable[[object], object]]) -> Expr:
    """Coerce Between low/high."""
    name = _field_name(node.field)
    if name is not None:
        new_low: Expr = node.low
        new_high: Expr = node.high
        if _is_const(node.low):
            new_low = Const(_coerce_const(name, node.low.value, coercion))
        if _is_const(node.high):
            new_high = Const(_coerce_const(name, node.high.value, coercion))
        return Between(field=node.field, low=new_low, high=new_high)
    return node


__all__ = (
    "ExprCoercer",
)

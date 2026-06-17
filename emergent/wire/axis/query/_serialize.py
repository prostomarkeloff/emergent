"""Expression serialization — pure functions for expr ↔ dict conversion.

Enables: caching, logging, debugging, transmission.

    from emergent.wire.axis.query import serialize

    # Serialize
    data = serialize.expr_to_dict(user.balance > 100)

    # Deserialize
    expr = serialize.expr_from_dict(data)

    # Extract fields
    fields = serialize.expr_fields(expr)  # {"balance"}

Open-world via fold_expr: pass custom handler maps to handle custom Expr types.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from emergent.wire.axis.query._expr import (
    Expr,
    Field,
    Const,
    # Comparison
    Eq,
    Ne,
    Lt,
    Le,
    Gt,
    Ge,
    # Logical
    And,
    Or,
    Not,
    # Collection
    In,
    Contains,
    StartsWith,
    EndsWith,
    # Null
    IsNull,
    IsNotNull,
    # Range
    Between,
    # Pattern
    Like,
    ILike,
    Regex,
    # Array
    ArrayContains,
    ArrayAny,
    ArrayAll,
    ArrayOverlap,
    # JSON
    JsonExtract,
    JsonContains,
    JsonHasKey,
    # Fold
    ExprHandler,
    fold_expr,
)

type DictNode = dict[str, Any]
type SerializeHandlers = dict[type, ExprHandler[DictNode]]
type SerializeHandlerMap = Mapping[type, ExprHandler[DictNode]]
type DeserializeFn = Callable[[DictNode, Callable[[DictNode], Expr]], Expr]
type DeserializeRegistry = dict[str, DeserializeFn]
type DeserializeRegistryMap = Mapping[str, DeserializeFn]
type ReprHandlers = dict[type, ExprHandler[str]]
type ReprHandlerMap = Mapping[type, ExprHandler[str]]


# ═══════════════════════════════════════════════════════════════════════════════
# Expression → Dict
# ═══════════════════════════════════════════════════════════════════════════════


def _serialize_node(node: Expr, recurse: Callable[[Expr], DictNode]) -> DictNode:
    """Delegate serialization to the node's own ``serialize_node``.

    Each concrete Expr describes its own dict shape (see ``_expr.py``), so the
    handler only needs to forward the recurse callback — attribute access stays
    on the concrete type, never on the ``Expr`` base.
    """
    return node.serialize_node(recurse)


def _make_serialize_handlers() -> SerializeHandlers:
    """Build handler map for Expr → dict serialization.

    Every built-in node delegates to its own ``serialize_node``. The per-type
    map is preserved so callers can override individual nodes via
    :meth:`ExprDialect.with_handler` (open-world extension).
    """
    return {
        # Leaf
        Field: _serialize_node,
        Const: _serialize_node,

        # Comparison
        Eq: _serialize_node,
        Ne: _serialize_node,
        Lt: _serialize_node,
        Le: _serialize_node,
        Gt: _serialize_node,
        Ge: _serialize_node,

        # Logical
        And: _serialize_node,
        Or: _serialize_node,
        Not: _serialize_node,

        # Collection
        In: _serialize_node,
        Contains: _serialize_node,
        StartsWith: _serialize_node,
        EndsWith: _serialize_node,

        # Null
        IsNull: _serialize_node,
        IsNotNull: _serialize_node,

        # Range
        Between: _serialize_node,

        # Pattern
        Like: _serialize_node,
        ILike: _serialize_node,
        Regex: _serialize_node,

        # Array
        ArrayContains: _serialize_node,
        ArrayAny: _serialize_node,
        ArrayAll: _serialize_node,
        ArrayOverlap: _serialize_node,

        # JSON
        JsonExtract: _serialize_node,
        JsonContains: _serialize_node,
        JsonHasKey: _serialize_node,
    }


def expr_to_dict(
    expr: Expr,
    handlers: SerializeHandlerMap | None = None,
) -> DictNode:
    """Serialize expression to JSON-compatible dict.

    Args:
        expr: Expression to serialize
        handlers: Optional handler map. If None, uses built-in handlers.
                  Pass custom handlers to support custom Expr types.

    Returns:
        Dict representation

    Example:
        expr = Eq(Field("name"), Const("alice"))
        data = expr_to_dict(expr)
        # {"op": "eq", "left": {"op": "field", "name": "name"},
        #  "right": {"op": "const", "value": "alice"}}
    """
    return fold_expr(expr, handlers if handlers is not None else _make_serialize_handlers())


# ═══════════════════════════════════════════════════════════════════════════════
# Dict → Expression
# ═══════════════════════════════════════════════════════════════════════════════

# Deserialization dispatches on string keys (not Expr types),
# so it uses a dict-keyed registry rather than fold_expr.


def _make_deserialize_registry() -> DeserializeRegistry:
    """Build registry for dict → Expr deserialization."""
    registry: DeserializeRegistry = {}

    # Leaf
    registry["field"] = lambda d, _r: Field(d["name"])
    registry["const"] = lambda d, _r: Const(d["value"])

    # Comparison
    for op, cls in [("eq", Eq), ("ne", Ne), ("lt", Lt), ("le", Le), ("gt", Gt), ("ge", Ge)]:
        registry[op] = lambda d, r, c=cls: c(r(d["left"]), r(d["right"]))

    # Logical
    registry["and"] = lambda d, r: And(r(d["left"]), r(d["right"]))
    registry["or"] = lambda d, r: Or(r(d["left"]), r(d["right"]))
    registry["not"] = lambda d, r: Not(r(d["operand"]))

    # Collection
    registry["in"] = lambda d, r: In(r(d["field"]), tuple(d["values"]))
    registry["contains"] = lambda d, r: Contains(r(d["field"]), d["substring"])
    registry["startswith"] = lambda d, r: StartsWith(r(d["field"]), d["prefix"])
    registry["endswith"] = lambda d, r: EndsWith(r(d["field"]), d["suffix"])

    # Null
    registry["is_null"] = lambda d, r: IsNull(r(d["field"]))
    registry["is_not_null"] = lambda d, r: IsNotNull(r(d["field"]))

    # Range
    registry["between"] = lambda d, r: Between(r(d["field"]), r(d["low"]), r(d["high"]))

    # Pattern
    registry["like"] = lambda d, r: Like(r(d["field"]), d["pattern"])
    registry["ilike"] = lambda d, r: ILike(r(d["field"]), d["pattern"])
    registry["regex"] = lambda d, r: Regex(r(d["field"]), d["pattern"])

    # Array
    registry["array_contains"] = lambda d, r: ArrayContains(r(d["field"]), d["value"])
    registry["array_any"] = lambda d, r: ArrayAny(r(d["field"]), tuple(d["values"]))
    registry["array_all"] = lambda d, r: ArrayAll(r(d["field"]), tuple(d["values"]))
    registry["array_overlap"] = lambda d, r: ArrayOverlap(r(d["field"]), tuple(d["values"]))

    # JSON
    registry["json_extract"] = lambda d, r: JsonExtract(r(d["field"]), d["path"])
    registry["json_contains"] = lambda d, r: JsonContains(r(d["field"]), d["value"])
    registry["json_has_key"] = lambda d, r: JsonHasKey(r(d["field"]), d["key"])

    return registry


def expr_from_dict(
    data: DictNode,
    registry: DeserializeRegistryMap | None = None,
) -> Expr:
    """Deserialize expression from dict.

    Args:
        data: Dict representation
        registry: Optional string-keyed handler registry. If None, uses built-in.
                  Pass custom registry to support custom op names.

    Returns:
        Expression object

    Example:
        data = {"op": "eq", "left": {"op": "field", "name": "name"},
                "right": {"op": "const", "value": "alice"}}
        expr = expr_from_dict(data)
        # Eq(Field("name"), Const("alice"))
    """
    reg = registry if registry is not None else _make_deserialize_registry()

    def recurse(d: DictNode) -> Expr:
        op = d.get("op")
        if isinstance(op, str):
            factory = reg.get(op)
            if factory is not None:
                return factory(d, recurse)
        raise ValueError(f"Unknown operation: {op}")

    return recurse(data)


# ═══════════════════════════════════════════════════════════════════════════════
# Expression Analysis
# ═══════════════════════════════════════════════════════════════════════════════


def expr_fields(expr: Expr) -> set[str]:
    """Extract all field names referenced in expression.

    Already open-world via children().

    Args:
        expr: Expression to analyze

    Returns:
        Set of field names

    Example:
        expr = And(Eq(Field("name"), Const("alice")),
                   Gt(Field("balance"), Const(100)))
        fields = expr_fields(expr)
        # {"name", "balance"}
    """
    if isinstance(expr, Field):
        return {expr.name}
    result: set[str] = set()
    for child in expr.children():
        result |= expr_fields(child)
    return result


def expr_complexity(expr: Expr) -> int:
    """Calculate expression complexity (node count).

    Already open-world via children().

    Args:
        expr: Expression to analyze

    Returns:
        Number of nodes in expression tree
    """
    return 1 + sum(expr_complexity(c) for c in expr.children())


def expr_depth(expr: Expr) -> int:
    """Calculate expression tree depth.

    Already open-world via children().

    Args:
        expr: Expression to analyze

    Returns:
        Maximum depth of expression tree
    """
    children = expr.children()
    if not children:
        return 1
    return 1 + max(expr_depth(c) for c in children)


# ═══════════════════════════════════════════════════════════════════════════════
# Expression Repr
# ═══════════════════════════════════════════════════════════════════════════════


def _repr_node(node: Expr, recurse: Callable[[Expr], str]) -> str:
    """Delegate repr rendering to the node's own ``repr_node``.

    Mirror of :func:`_serialize_node`: each concrete Expr knows how to render
    itself, so the handler only forwards the recurse callback.
    """
    return node.repr_node(recurse)


def _make_repr_handlers() -> ReprHandlers:
    """Build handler map for Expr → human-readable string.

    Every built-in node delegates to its own ``repr_node``. The per-type map is
    preserved for open-world override via :meth:`ExprDialect.with_handler`.
    """
    return {
        # Leaf
        Field: _repr_node,
        Const: _repr_node,

        # Comparison
        Eq: _repr_node,
        Ne: _repr_node,
        Lt: _repr_node,
        Le: _repr_node,
        Gt: _repr_node,
        Ge: _repr_node,

        # Logical
        And: _repr_node,
        Or: _repr_node,
        Not: _repr_node,

        # Collection
        In: _repr_node,
        Contains: _repr_node,
        StartsWith: _repr_node,
        EndsWith: _repr_node,

        # Null
        IsNull: _repr_node,
        IsNotNull: _repr_node,

        # Range
        Between: _repr_node,

        # Pattern
        Like: _repr_node,
        ILike: _repr_node,
        Regex: _repr_node,

        # Array
        ArrayContains: _repr_node,
        ArrayAny: _repr_node,
        ArrayAll: _repr_node,
        ArrayOverlap: _repr_node,

        # JSON
        JsonExtract: _repr_node,
        JsonContains: _repr_node,
        JsonHasKey: _repr_node,
    }


def expr_repr(
    expr: Expr,
    handlers: ReprHandlerMap | None = None,
) -> str:
    """Human-readable expression string.

    Unlike __repr__ (dataclass default, exact structure),
    this produces scannable output for debugging:

        >>> expr_repr(And(Gt(Field("balance"), Const(100)), Eq(Field("active"), Const(True))))
        '(balance > 100) & (active == True)'

    Args:
        expr: Expression to format
        handlers: Optional handler map. If None, uses built-in handlers.
                  Pass custom handlers to support custom Expr types.

    Returns:
        Human-readable string
    """
    h = handlers if handlers is not None else _make_repr_handlers()
    return fold_expr(expr, h, default=lambda n, _r: repr(n))


__all__ = (
    "expr_to_dict",
    "expr_from_dict",
    "expr_fields",
    "expr_complexity",
    "expr_depth",
    "expr_repr",
    # Factories for building handler maps (for extension)
    "_make_serialize_handlers",
    "_make_repr_handlers",
    "_make_deserialize_registry",
)

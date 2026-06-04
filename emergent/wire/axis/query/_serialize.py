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
from typing import Any, cast

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


# ═══════════════════════════════════════════════════════════════════════════════
# Expression → Dict
# ═══════════════════════════════════════════════════════════════════════════════


def _binary_dict(op_name: str) -> ExprHandler[dict[str, Any]]:
    """Handler factory for binary ops (left/right)."""
    def handler(node: Expr, recurse: Callable[[Expr], dict[str, Any]]) -> dict[str, Any]:
        return {"op": op_name, "left": recurse(node.left), "right": recurse(node.right)}
    return handler


def _make_serialize_handlers() -> dict[type, ExprHandler[dict[str, Any]]]:
    """Build handler map for Expr → dict serialization."""
    return {
        # Leaf
        Field: lambda n, _r: {"op": "field", "name": n.name},
        Const: lambda n, _r: {"op": "const", "value": cast(Const[Any], n).value},

        # Comparison
        Eq: _binary_dict("eq"),
        Ne: _binary_dict("ne"),
        Lt: _binary_dict("lt"),
        Le: _binary_dict("le"),
        Gt: _binary_dict("gt"),
        Ge: _binary_dict("ge"),

        # Logical
        And: _binary_dict("and"),
        Or: _binary_dict("or"),
        Not: lambda n, r: {"op": "not", "operand": r(n.operand)},

        # Collection
        In: lambda n, r: {"op": "in", "field": r(n.field), "values": list(n.values)},
        Contains: lambda n, r: {"op": "contains", "field": r(n.field), "substring": n.substring},
        StartsWith: lambda n, r: {"op": "startswith", "field": r(n.field), "prefix": n.prefix},
        EndsWith: lambda n, r: {"op": "endswith", "field": r(n.field), "suffix": n.suffix},

        # Null
        IsNull: lambda n, r: {"op": "is_null", "field": r(n.field)},
        IsNotNull: lambda n, r: {"op": "is_not_null", "field": r(n.field)},

        # Range
        Between: lambda n, r: {"op": "between", "field": r(n.field), "low": r(n.low), "high": r(n.high)},

        # Pattern
        Like: lambda n, r: {"op": "like", "field": r(n.field), "pattern": n.pattern},
        ILike: lambda n, r: {"op": "ilike", "field": r(n.field), "pattern": n.pattern},
        Regex: lambda n, r: {"op": "regex", "field": r(n.field), "pattern": n.pattern},

        # Array
        ArrayContains: lambda n, r: {"op": "array_contains", "field": r(n.field), "value": n.value},
        ArrayAny: lambda n, r: {"op": "array_any", "field": r(n.field), "values": list(n.values)},
        ArrayAll: lambda n, r: {"op": "array_all", "field": r(n.field), "values": list(n.values)},
        ArrayOverlap: lambda n, r: {"op": "array_overlap", "field": r(n.field), "values": list(n.values)},

        # JSON
        JsonExtract: lambda n, r: {"op": "json_extract", "field": r(n.field), "path": n.path},
        JsonContains: lambda n, r: {"op": "json_contains", "field": r(n.field), "value": n.value},
        JsonHasKey: lambda n, r: {"op": "json_has_key", "field": r(n.field), "key": n.key},
    }


def expr_to_dict(
    expr: Expr,
    handlers: Mapping[type, ExprHandler[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
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


def _make_deserialize_registry() -> dict[str, Callable[[dict[str, Any], Callable[[dict[str, Any]], Expr]], Expr]]:
    """Build registry for dict → Expr deserialization."""
    registry: dict[str, Callable[[dict[str, Any], Callable[[dict[str, Any]], Expr]], Expr]] = {}

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
    data: dict[str, Any],
    registry: Mapping[str, Callable[[dict[str, Any], Callable[[dict[str, Any]], Expr]], Expr]] | None = None,
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

    def recurse(d: dict[str, Any]) -> Expr:
        op = d.get("op")
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


def _binary_repr(op_symbol: str) -> ExprHandler[str]:
    """Handler factory for binary comparison repr."""
    def handler(node: Expr, recurse: Callable[[Expr], str]) -> str:
        return f"{recurse(node.left)} {op_symbol} {recurse(node.right)}"
    return handler


def _make_repr_handlers() -> dict[type, ExprHandler[str]]:
    """Build handler map for Expr → human-readable string."""
    return {
        # Leaf
        Field: lambda n, _r: n.name,
        Const: lambda n, _r: repr(cast(Const[Any], n).value),

        # Comparison
        Eq: _binary_repr("=="),
        Ne: _binary_repr("!="),
        Lt: _binary_repr("<"),
        Le: _binary_repr("<="),
        Gt: _binary_repr(">"),
        Ge: _binary_repr(">="),

        # Logical
        And: lambda n, r: f"({r(n.left)}) & ({r(n.right)})",
        Or: lambda n, r: f"({r(n.left)}) | ({r(n.right)})",
        Not: lambda n, r: f"~({r(n.operand)})",

        # Collection
        In: lambda n, r: f"{r(n.field)} IN {n.values!r}",
        Contains: lambda n, r: f"{r(n.field)}.contains({n.substring!r})",
        StartsWith: lambda n, r: f"{r(n.field)}.startswith({n.prefix!r})",
        EndsWith: lambda n, r: f"{r(n.field)}.endswith({n.suffix!r})",

        # Null
        IsNull: lambda n, r: f"{r(n.field)} IS NULL",
        IsNotNull: lambda n, r: f"{r(n.field)} IS NOT NULL",

        # Range
        Between: lambda n, r: f"{r(n.field)} BETWEEN {r(n.low)} AND {r(n.high)}",

        # Pattern
        Like: lambda n, r: f"{r(n.field)} LIKE {n.pattern!r}",
        ILike: lambda n, r: f"{r(n.field)} ILIKE {n.pattern!r}",
        Regex: lambda n, r: f"{r(n.field)} ~ {n.pattern!r}",

        # Array
        ArrayContains: lambda n, r: f"{r(n.field)} @> {n.value!r}",
        ArrayAny: lambda n, r: f"{r(n.field)} && ANY {n.values!r}",
        ArrayAll: lambda n, r: f"{r(n.field)} @> ALL {n.values!r}",
        ArrayOverlap: lambda n, r: f"{r(n.field)} && {n.values!r}",

        # JSON
        JsonExtract: lambda n, r: f"{r(n.field)}->>'{n.path}'",
        JsonContains: lambda n, r: f"{r(n.field)} @> {n.value!r}",
        JsonHasKey: lambda n, r: f"{r(n.field)} ? {n.key!r}",
    }


def expr_repr(
    expr: Expr,
    handlers: Mapping[type, ExprHandler[str]] | None = None,
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

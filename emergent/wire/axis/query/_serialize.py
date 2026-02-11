"""Expression serialization — pure functions for expr ↔ dict conversion.

Enables: caching, logging, debugging, transmission.

    from emergent.wire.axis.query import serialize

    # Serialize
    data = serialize.expr_to_dict(user.balance > 100)

    # Deserialize
    expr = serialize.expr_from_dict(data)

    # Extract fields
    fields = serialize.expr_fields(expr)  # {"balance"}
"""

from __future__ import annotations

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
)


# ═══════════════════════════════════════════════════════════════════════════════
# Expression → Dict
# ═══════════════════════════════════════════════════════════════════════════════


def expr_to_dict(expr: Expr) -> dict[str, Any]:
    """Serialize expression to JSON-compatible dict.

    Args:
        expr: Expression to serialize

    Returns:
        Dict representation

    Example:
        expr = Eq(Field("name"), Const("alice"))
        data = expr_to_dict(expr)
        # {"op": "eq", "left": {"op": "field", "name": "name"},
        #  "right": {"op": "const", "value": "alice"}}
    """
    # Handle Const separately — generic T can't be inferred by pyright in pattern match.
    # Cast to Const[Any]: Const[T].value serializes to JSON-compatible Any for dict output.
    if isinstance(expr, Const):
        c = cast(Const[Any], expr)
        return {"op": "const", "value": c.value}

    match expr:
        # Leaf nodes
        case Field(name=name):
            return {"op": "field", "name": name}

        # Comparison
        case Eq(left=left, right=right):
            return {"op": "eq", "left": expr_to_dict(left), "right": expr_to_dict(right)}

        case Ne(left=left, right=right):
            return {"op": "ne", "left": expr_to_dict(left), "right": expr_to_dict(right)}

        case Lt(left=left, right=right):
            return {"op": "lt", "left": expr_to_dict(left), "right": expr_to_dict(right)}

        case Le(left=left, right=right):
            return {"op": "le", "left": expr_to_dict(left), "right": expr_to_dict(right)}

        case Gt(left=left, right=right):
            return {"op": "gt", "left": expr_to_dict(left), "right": expr_to_dict(right)}

        case Ge(left=left, right=right):
            return {"op": "ge", "left": expr_to_dict(left), "right": expr_to_dict(right)}

        # Logical
        case And(left=left, right=right):
            return {"op": "and", "left": expr_to_dict(left), "right": expr_to_dict(right)}

        case Or(left=left, right=right):
            return {"op": "or", "left": expr_to_dict(left), "right": expr_to_dict(right)}

        case Not(operand=operand):
            return {"op": "not", "operand": expr_to_dict(operand)}

        # Collection
        case In(field=field, values=values):
            return {
                "op": "in",
                "field": expr_to_dict(field),
                "values": list(values),
            }

        case Contains(field=field, substring=substring):
            return {"op": "contains", "field": expr_to_dict(field), "substring": substring}

        case StartsWith(field=field, prefix=prefix):
            return {"op": "startswith", "field": expr_to_dict(field), "prefix": prefix}

        case EndsWith(field=field, suffix=suffix):
            return {"op": "endswith", "field": expr_to_dict(field), "suffix": suffix}

        # Null
        case IsNull(field=field):
            return {"op": "is_null", "field": expr_to_dict(field)}

        case IsNotNull(field=field):
            return {"op": "is_not_null", "field": expr_to_dict(field)}

        # Range
        case Between(field=field, low=low, high=high):
            return {
                "op": "between",
                "field": expr_to_dict(field),
                "low": expr_to_dict(low),
                "high": expr_to_dict(high),
            }

        # Pattern
        case Like(field=field, pattern=pattern):
            return {"op": "like", "field": expr_to_dict(field), "pattern": pattern}

        case ILike(field=field, pattern=pattern):
            return {"op": "ilike", "field": expr_to_dict(field), "pattern": pattern}

        case Regex(field=field, pattern=pattern):
            return {"op": "regex", "field": expr_to_dict(field), "pattern": pattern}

        # Array
        case ArrayContains(field=field, value=value):
            return {
                "op": "array_contains",
                "field": expr_to_dict(field),
                "value": value,
            }

        case ArrayAny(field=field, values=values):
            return {
                "op": "array_any",
                "field": expr_to_dict(field),
                "values": list(values),
            }

        case ArrayAll(field=field, values=values):
            return {
                "op": "array_all",
                "field": expr_to_dict(field),
                "values": list(values),
            }

        case ArrayOverlap(field=field, values=values):
            return {
                "op": "array_overlap",
                "field": expr_to_dict(field),
                "values": list(values),
            }

        # JSON
        case JsonExtract(field=field, path=path):
            return {"op": "json_extract", "field": expr_to_dict(field), "path": path}

        case JsonContains(field=field, value=value):
            return {
                "op": "json_contains",
                "field": expr_to_dict(field),
                "value": value,
            }

        case JsonHasKey(field=field, key=key):
            return {"op": "json_has_key", "field": expr_to_dict(field), "key": key}

        case _:
            raise ValueError(f"Unknown expression type: {type(expr).__name__}: {expr!r}")




# ═══════════════════════════════════════════════════════════════════════════════
# Dict → Expression
# ═══════════════════════════════════════════════════════════════════════════════


def expr_from_dict(data: dict[str, Any]) -> Expr:
    """Deserialize expression from dict.

    Args:
        data: Dict representation

    Returns:
        Expression object

    Example:
        data = {"op": "eq", "left": {"op": "field", "name": "name"},
                "right": {"op": "const", "value": "alice"}}
        expr = expr_from_dict(data)
        # Eq(Field("name"), Const("alice"))
    """
    op = data.get("op")

    match op:
        # Leaf nodes
        case "field":
            return Field(data["name"])

        case "const":
            return Const(data["value"])

        # Comparison
        case "eq":
            return Eq(expr_from_dict(data["left"]), expr_from_dict(data["right"]))

        case "ne":
            return Ne(expr_from_dict(data["left"]), expr_from_dict(data["right"]))

        case "lt":
            return Lt(expr_from_dict(data["left"]), expr_from_dict(data["right"]))

        case "le":
            return Le(expr_from_dict(data["left"]), expr_from_dict(data["right"]))

        case "gt":
            return Gt(expr_from_dict(data["left"]), expr_from_dict(data["right"]))

        case "ge":
            return Ge(expr_from_dict(data["left"]), expr_from_dict(data["right"]))

        # Logical
        case "and":
            return And(expr_from_dict(data["left"]), expr_from_dict(data["right"]))

        case "or":
            return Or(expr_from_dict(data["left"]), expr_from_dict(data["right"]))

        case "not":
            return Not(expr_from_dict(data["operand"]))

        # Collection
        case "in":
            return In(expr_from_dict(data["field"]), tuple(data["values"]))

        case "contains":
            return Contains(expr_from_dict(data["field"]), data["substring"])

        case "startswith":
            return StartsWith(expr_from_dict(data["field"]), data["prefix"])

        case "endswith":
            return EndsWith(expr_from_dict(data["field"]), data["suffix"])

        # Null
        case "is_null":
            return IsNull(expr_from_dict(data["field"]))

        case "is_not_null":
            return IsNotNull(expr_from_dict(data["field"]))

        # Range
        case "between":
            return Between(
                expr_from_dict(data["field"]),
                expr_from_dict(data["low"]),
                expr_from_dict(data["high"]),
            )

        # Pattern
        case "like":
            return Like(expr_from_dict(data["field"]), data["pattern"])

        case "ilike":
            return ILike(expr_from_dict(data["field"]), data["pattern"])

        case "regex":
            return Regex(expr_from_dict(data["field"]), data["pattern"])

        # Array
        case "array_contains":
            return ArrayContains(expr_from_dict(data["field"]), data["value"])

        case "array_any":
            return ArrayAny(expr_from_dict(data["field"]), tuple(data["values"]))

        case "array_all":
            return ArrayAll(expr_from_dict(data["field"]), tuple(data["values"]))

        case "array_overlap":
            return ArrayOverlap(expr_from_dict(data["field"]), tuple(data["values"]))

        # JSON
        case "json_extract":
            return JsonExtract(expr_from_dict(data["field"]), data["path"])

        case "json_contains":
            return JsonContains(expr_from_dict(data["field"]), data["value"])

        case "json_has_key":
            return JsonHasKey(expr_from_dict(data["field"]), data["key"])

        case _:
            raise ValueError(f"Unknown operation: {op}")


# ═══════════════════════════════════════════════════════════════════════════════
# Expression Analysis
# ═══════════════════════════════════════════════════════════════════════════════


def expr_fields(expr: Expr) -> set[str]:
    """Extract all field names referenced in expression.

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

    Useful for optimization decisions.

    Args:
        expr: Expression to analyze

    Returns:
        Number of nodes in expression tree
    """
    return 1 + sum(expr_complexity(c) for c in expr.children())


def expr_depth(expr: Expr) -> int:
    """Calculate expression tree depth.

    Args:
        expr: Expression to analyze

    Returns:
        Maximum depth of expression tree
    """
    children = expr.children()
    if not children:
        return 1
    return 1 + max(expr_depth(c) for c in children)


def expr_repr(expr: Expr) -> str:
    """Human-readable expression string.

    Unlike __repr__ (dataclass default, exact structure),
    this produces scannable output for debugging:

        >>> expr_repr(And(Gt(Field("balance"), Const(100)), Eq(Field("active"), Const(True))))
        '(balance > 100) & (active == True)'

    Args:
        expr: Expression to format

    Returns:
        Human-readable string
    """
    if isinstance(expr, Const):
        return repr(expr.value)

    match expr:
        case Field(name=n):
            return n

        # Comparison
        case Eq(left=l, right=r):
            return f"{expr_repr(l)} == {expr_repr(r)}"
        case Ne(left=l, right=r):
            return f"{expr_repr(l)} != {expr_repr(r)}"
        case Lt(left=l, right=r):
            return f"{expr_repr(l)} < {expr_repr(r)}"
        case Le(left=l, right=r):
            return f"{expr_repr(l)} <= {expr_repr(r)}"
        case Gt(left=l, right=r):
            return f"{expr_repr(l)} > {expr_repr(r)}"
        case Ge(left=l, right=r):
            return f"{expr_repr(l)} >= {expr_repr(r)}"

        # Logical
        case And(left=l, right=r):
            return f"({expr_repr(l)}) & ({expr_repr(r)})"
        case Or(left=l, right=r):
            return f"({expr_repr(l)}) | ({expr_repr(r)})"
        case Not(operand=o):
            return f"~({expr_repr(o)})"

        # Collection
        case In(field=f, values=v):
            return f"{expr_repr(f)} IN {v!r}"
        case Contains(field=f, substring=s):
            return f"{expr_repr(f)}.contains({s!r})"
        case StartsWith(field=f, prefix=p):
            return f"{expr_repr(f)}.startswith({p!r})"
        case EndsWith(field=f, suffix=s):
            return f"{expr_repr(f)}.endswith({s!r})"

        # Null
        case IsNull(field=f):
            return f"{expr_repr(f)} IS NULL"
        case IsNotNull(field=f):
            return f"{expr_repr(f)} IS NOT NULL"

        # Range
        case Between(field=f, low=lo, high=hi):
            return f"{expr_repr(f)} BETWEEN {expr_repr(lo)} AND {expr_repr(hi)}"

        # Pattern
        case Like(field=f, pattern=p):
            return f"{expr_repr(f)} LIKE {p!r}"
        case ILike(field=f, pattern=p):
            return f"{expr_repr(f)} ILIKE {p!r}"
        case Regex(field=f, pattern=p):
            return f"{expr_repr(f)} ~ {p!r}"

        # Array
        case ArrayContains(field=f, value=v):
            return f"{expr_repr(f)} @> {v!r}"
        case ArrayAny(field=f, values=v):
            return f"{expr_repr(f)} && ANY {v!r}"
        case ArrayAll(field=f, values=v):
            return f"{expr_repr(f)} @> ALL {v!r}"
        case ArrayOverlap(field=f, values=v):
            return f"{expr_repr(f)} && {v!r}"

        # JSON
        case JsonExtract(field=f, path=p):
            return f"{expr_repr(f)}->>'{p}'"
        case JsonContains(field=f, value=v):
            return f"{expr_repr(f)} @> {v!r}"
        case JsonHasKey(field=f, key=k):
            return f"{expr_repr(f)} ? {k!r}"

        case _:
            return repr(expr)


__all__ = (
    "expr_to_dict",
    "expr_from_dict",
    "expr_fields",
    "expr_complexity",
    "expr_depth",
    "expr_repr",
)

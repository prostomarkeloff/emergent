"""Query explain — self-description of query operations.

Two layers:
  1. Dict-returning: explain_ops() — structured data for tools/analysis
  2. Human-readable: format_ops() — formats from explain_ops() dicts

Symmetric with fold_query: handlers passed as argument, not global.
Open-world: unknown ops produce minimal description (type name only).

    from emergent.wire.axis.query._explain import (
        explain_ops, format_ops,
        RELATIONAL_EXPLAIN, API_EXPLAIN, KV_EXPLAIN,
    )

    # Dict layer
    info = explain_ops(query.ops, RELATIONAL_EXPLAIN)

    # Human-readable
    text = format_ops(query.ops, RELATIONAL_EXPLAIN)

    # Compose with custom handler
    my = RELATIONAL_EXPLAIN_DIALECT.with_handler(MyOp, my_handler)
    text = my.format(query.ops)
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from emergent.wire.axis.query._api import (
    CreateOp,
    CursorMod,
    DeleteOp,
    FilterMod,
    GetOp,
    IncludeMod,
    ListOp,
    OffsetMod,
    OrderMod,
    PageMod,
    SearchMod,
    SelectMod,
    UpdateOp,
)
from emergent.wire.axis.query._kv import (
    Exists,
    Keys,
    KVDelete,
    KVGet,
    KVSet,
    Scan,
)
from emergent.wire.axis.query._relational import (
    Aggregate,
    Distinct,
    Filter,
    GroupBy,
    Having,
    Join,
    Limit,
    Offset,
    OrderBy,
    Select,
)
from emergent.wire.axis.query._serialize import expr_fields


# ═══════════════════════════════════════════════════════════════════════════════
# Core Primitives
# ═══════════════════════════════════════════════════════════════════════════════


type ExplainHandler = Callable[[Any], dict[str, Any]]


def explain_ops(
    ops: Sequence[object],
    handlers: Mapping[type, ExplainHandler],
) -> list[dict[str, Any]]:
    """Explain a sequence of query ops as structured dicts.

    Each op is dispatched to its handler by exact type.
    Unknown ops produce minimal dict with just the type name (open-world).

    Args:
        ops: Sequence of query operations to explain
        handlers: Handlers keyed by op type

    Returns:
        List of dicts, one per op

    Example:
        info = explain_ops(query.ops, RELATIONAL_EXPLAIN)
    """
    result: list[dict[str, Any]] = []
    for op in ops:
        handler = handlers.get(type(op))
        if handler is not None:
            result.append(handler(op))
        else:
            result.append({"op": type(op).__name__})
    return result


def format_ops(
    ops: Sequence[object],
    handlers: Mapping[type, ExplainHandler],
) -> str:
    """Human-readable explanation of query ops.

    Formats from explain_ops() dicts — same two-layer pattern as
    compile/_explain.py.

    Example:
        print(format_ops(query.ops, RELATIONAL_EXPLAIN))
        #   1. Filter: expr=balance > 100, fields=balance
        #   2. OrderBy: specs=name ASC
        #   3. Limit: count=10
    """
    entries = explain_ops(ops, handlers)
    if not entries:
        return "(empty)"
    lines: list[str] = []
    for i, entry in enumerate(entries, 1):
        lines.append(f"  {i}. {_format_entry(entry)}")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# ExplainDialect — named handler bundle (symmetric with QueryDialect)
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class ExplainDialect:
    """Explain dialect — reified explain handler set.

    Symmetric to QueryDialect. Immutable value.
    Use .with_handler() / .without_handler() for customization.
    """

    handlers: Mapping[type, ExplainHandler]

    def explain(self, ops: Sequence[object]) -> list[dict[str, Any]]:
        """Run explain_ops with this dialect's handlers."""
        return explain_ops(ops, self.handlers)

    def format(self, ops: Sequence[object]) -> str:
        """Run format_ops with this dialect's handlers."""
        return format_ops(ops, self.handlers)

    def with_handler(
        self, op_type: type, handler: ExplainHandler
    ) -> ExplainDialect:
        """Return new dialect with added/replaced handler. Immutable."""
        merged = {**self.handlers, op_type: handler}
        return replace(self, handlers=merged)

    def without_handler(self, op_type: type) -> ExplainDialect:
        """Return new dialect without handler for given op type. Immutable."""
        filtered = {k: v for k, v in self.handlers.items() if k is not op_type}
        return replace(self, handlers=filtered)


# ═══════════════════════════════════════════════════════════════════════════════
# Formatters (dict → str)
# ═══════════════════════════════════════════════════════════════════════════════


def _format_entry(entry: dict[str, Any]) -> str:
    """Format one explain dict as a human-readable line."""
    op_name = entry.get("op", "?")
    rest = {k: v for k, v in entry.items() if k != "op"}
    if not rest:
        return str(op_name)
    parts = ", ".join(f"{k}={_format_value(v)}" for k, v in rest.items())
    return f"{op_name}: {parts}"


def _format_value(v: Any) -> str:
    """Format a dict value for human-readable output."""
    if isinstance(v, (list, tuple)):
        return ", ".join(str(x) for x in v)
    return str(v)


# ═══════════════════════════════════════════════════════════════════════════════
# Relational Handlers
# ═══════════════════════════════════════════════════════════════════════════════


def _explain_filter(op: Filter) -> dict[str, Any]:
    return {
        "op": "Filter",
        "expr": str(op.expr),
        "fields": sorted(expr_fields(op.expr)),
    }


def _explain_order_by(op: OrderBy) -> dict[str, Any]:
    return {
        "op": "OrderBy",
        "specs": [
            f"{s.field} {'ASC' if s.ascending else 'DESC'}" for s in op.specs
        ],
    }


def _explain_limit(op: Limit) -> dict[str, Any]:
    return {"op": "Limit", "count": op.count}


def _explain_offset(op: Offset) -> dict[str, Any]:
    return {"op": "Offset", "count": op.count}


def _explain_select(op: Select) -> dict[str, Any]:
    return {"op": "Select", "fields": list(op.fields)}


def _explain_join(op: Join) -> dict[str, Any]:
    return {
        "op": "Join",
        "target": op.target.__name__,
        "kind": op.kind,
        "on": str(op.on),
    }


def _explain_group_by(op: GroupBy) -> dict[str, Any]:
    return {"op": "GroupBy", "fields": list(op.fields)}


def _explain_having(op: Having) -> dict[str, Any]:
    return {"op": "Having", "expr": str(op.expr)}


def _explain_distinct(op: Distinct) -> dict[str, Any]:
    return {"op": "Distinct"}


def _explain_aggregate(op: Aggregate) -> dict[str, Any]:
    return {
        "op": "Aggregate",
        "specs": [
            f"{s.alias}={type(s.func).__name__}({s.field or '*'})"
            for s in op.specs
        ],
    }


RELATIONAL_EXPLAIN: Mapping[type, ExplainHandler] = {
    Filter: _explain_filter,
    OrderBy: _explain_order_by,
    Limit: _explain_limit,
    Offset: _explain_offset,
    Select: _explain_select,
    Join: _explain_join,
    GroupBy: _explain_group_by,
    Having: _explain_having,
    Distinct: _explain_distinct,
    Aggregate: _explain_aggregate,
}


# ═══════════════════════════════════════════════════════════════════════════════
# KV Handlers
# ═══════════════════════════════════════════════════════════════════════════════


def _explain_kv_get(op: KVGet[Any]) -> dict[str, Any]:
    return {"op": "Get", "key": repr(op.key)}


def _explain_kv_set(op: KVSet[Any, Any]) -> dict[str, Any]:
    d: dict[str, Any] = {"op": "Set", "key": repr(op.key)}
    if op.ttl is not None:
        d["ttl"] = op.ttl
    return d


def _explain_kv_delete(op: KVDelete[Any]) -> dict[str, Any]:
    return {"op": "Delete", "key": repr(op.key)}


def _explain_exists(op: Exists[Any]) -> dict[str, Any]:
    return {"op": "Exists", "key": repr(op.key)}


def _explain_scan(op: Scan) -> dict[str, Any]:
    return {"op": "Scan", "pattern": op.pattern}


def _explain_keys(op: Keys) -> dict[str, Any]:
    return {"op": "Keys", "pattern": op.pattern}


KV_EXPLAIN: Mapping[type, ExplainHandler] = {
    KVGet: _explain_kv_get,
    KVSet: _explain_kv_set,
    KVDelete: _explain_kv_delete,
    Exists: _explain_exists,
    Scan: _explain_scan,
    Keys: _explain_keys,
}


# ═══════════════════════════════════════════════════════════════════════════════
# API Handlers
# ═══════════════════════════════════════════════════════════════════════════════


def _explain_list_op(op: ListOp) -> dict[str, Any]:
    return {"op": "List"}


def _explain_get_op(op: GetOp[Any]) -> dict[str, Any]:
    return {"op": "Get", "id": repr(op.id)}


def _explain_create_op(op: CreateOp[Any]) -> dict[str, Any]:
    return {"op": "Create", "entity_type": type(op.entity).__name__}


def _explain_update_op(op: UpdateOp[Any, Any]) -> dict[str, Any]:
    method = "Patch" if op.partial else "Update"
    return {"op": method, "id": repr(op.id)}


def _explain_delete_op(op: DeleteOp[Any]) -> dict[str, Any]:
    return {"op": "Delete", "id": repr(op.id)}


def _explain_filter_mod(op: FilterMod) -> dict[str, Any]:
    return {
        "op": "Filter",
        "expr": str(op.expr),
        "fields": sorted(expr_fields(op.expr)),
    }


def _explain_order_mod(op: OrderMod) -> dict[str, Any]:
    return {
        "op": "OrderBy",
        "specs": [
            f"{s.field} {'ASC' if s.ascending else 'DESC'}" for s in op.specs
        ],
    }


def _explain_page_mod(op: PageMod) -> dict[str, Any]:
    return {"op": "Page", "page": op.page, "per_page": op.per_page}


def _explain_cursor_mod(op: CursorMod) -> dict[str, Any]:
    return {"op": "Cursor", "cursor": op.cursor, "limit": op.limit}


def _explain_offset_mod(op: OffsetMod) -> dict[str, Any]:
    return {"op": "Offset", "offset": op.offset, "limit": op.limit}


def _explain_select_mod(op: SelectMod) -> dict[str, Any]:
    return {"op": "Select", "fields": list(op.fields)}


def _explain_search_mod(op: SearchMod) -> dict[str, Any]:
    return {"op": "Search", "query": op.query}


def _explain_include_mod(op: IncludeMod) -> dict[str, Any]:
    return {"op": "Include", "relations": list(op.relations)}


API_EXPLAIN: Mapping[type, ExplainHandler] = {
    ListOp: _explain_list_op,
    GetOp: _explain_get_op,
    CreateOp: _explain_create_op,
    UpdateOp: _explain_update_op,
    DeleteOp: _explain_delete_op,
    FilterMod: _explain_filter_mod,
    OrderMod: _explain_order_mod,
    PageMod: _explain_page_mod,
    CursorMod: _explain_cursor_mod,
    OffsetMod: _explain_offset_mod,
    SelectMod: _explain_select_mod,
    SearchMod: _explain_search_mod,
    IncludeMod: _explain_include_mod,
}


# ═══════════════════════════════════════════════════════════════════════════════
# Pre-built Dialects
# ═══════════════════════════════════════════════════════════════════════════════

RELATIONAL_EXPLAIN_DIALECT: ExplainDialect = ExplainDialect(
    handlers=RELATIONAL_EXPLAIN
)
API_EXPLAIN_DIALECT: ExplainDialect = ExplainDialect(handlers=API_EXPLAIN)
KV_EXPLAIN_DIALECT: ExplainDialect = ExplainDialect(handlers=KV_EXPLAIN)


__all__ = (
    # Core
    "ExplainHandler",
    "explain_ops",
    "format_ops",
    # Dialect
    "ExplainDialect",
    # Handler sets (immutable constants)
    "RELATIONAL_EXPLAIN",
    "API_EXPLAIN",
    "KV_EXPLAIN",
    # Pre-built dialects
    "RELATIONAL_EXPLAIN_DIALECT",
    "API_EXPLAIN_DIALECT",
    "KV_EXPLAIN_DIALECT",
)

"""Query fold — handler-only op dispatch (legacy).

NOTE: Providers now use ``fold()`` from ``emergent.wire.compile._core``
with protocol dispatch (``MemoryQueryCompilable`` / ``SAQueryCompilable``).
Ops are self-compiling capabilities — see ``_contexts.py`` for protocols.

``fold_query`` and ``QueryDialect`` remain valid as simpler handler-only
fold primitives (no protocol fallback, pure handler map dispatch).
Use them when you need a lightweight fold without protocols.

    from emergent.wire.axis.query import fold_query, QueryDialect

    # Direct fold with handler map
    result = fold_query(query.ops, list(data), my_handlers)

    # Via dialect
    dialect = QueryDialect(context_type=list, handlers=my_handlers)
    result = dialect.fold(query.ops, list(data))

For provider-level query compilation, prefer:

    from emergent.wire.compile._core import fold
    from emergent.wire.axis.query._contexts import (
        MemoryQueryContext, MemoryQueryCompilable,
    )

    ctx = MemoryQueryContext(data=list(data))
    result = fold(query.ops, ctx, MemoryQueryCompilable, "compile_memory_query")
"""

from __future__ import annotations

from collections.abc import Callable, Hashable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from emergent.wire.axis.query._relational import (
    Aggregate,
    Filter,
    OrderBy,
    Limit,
    Offset,
    Distinct,
    Select,
    Join,
    GroupBy,
    Having,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Core Fold Primitive
# ═══════════════════════════════════════════════════════════════════════════════


type OpHandler[Ctx] = Callable[[Any, Ctx], Ctx]


def fold_query[Ctx](
    ops: Sequence[object],
    initial: Ctx,
    handlers: Mapping[type, OpHandler[Ctx]],
) -> Ctx:
    """Universal query-level op fold — THE query primitive.

    Iterates ops, dispatches to handler by exact type.
    No protocol fallback (ops are pure data).
    Unknown ops silently skipped (open-world: new ops don't break old dialects).

    Args:
        ops: Sequence of query operations to fold over
        initial: Starting context (list[T] for memory, str for SQL, etc.)
        handlers: Handlers keyed by op type — REQUIRED (no protocol fallback)

    Returns:
        Final accumulated context after all ops applied

    Example:
        result = fold_query(query.ops, list(data), MEMORY_HANDLERS)
    """
    ctx = initial
    for op in ops:
        handler = handlers.get(type(op))
        if handler is not None:
            ctx = handler(op, ctx)
    return ctx


# ═══════════════════════════════════════════════════════════════════════════════
# QueryDialect — named handler bundle
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class QueryDialect[Ctx]:
    """Query dialect descriptor — reified op handler set.

    Symmetric to CompilationPhase[Ctx] in compile/.
    Immutable value. Use .with_handler() / .without_handler() for customization.

    No ``initial`` factory — unlike CompilationPhase, query context is highly
    variable (list[T] for memory, SQL builder for SQL, dict for Mongo).
    Caller provides initial value directly.

    Attributes:
        context_type: Type of the fold context (for type identification)
        handlers: Op handlers keyed by op type
    """

    context_type: type[Ctx]
    handlers: Mapping[type, OpHandler[Ctx]]

    def fold(self, ops: Sequence[object], initial: Ctx) -> Ctx:
        """Run fold_query with this dialect's handlers."""
        return fold_query(ops, initial, self.handlers)

    def with_handler(
        self, op_type: type, handler: OpHandler[Ctx]
    ) -> QueryDialect[Ctx]:
        """Return new dialect with added/replaced handler. Immutable."""
        merged = {**self.handlers, op_type: handler}
        return replace(self, handlers=merged)

    def without_handler(self, op_type: type) -> QueryDialect[Ctx]:
        """Return new dialect without handler for given op type. Immutable."""
        filtered = {k: v for k, v in self.handlers.items() if k is not op_type}
        return replace(self, handlers=filtered)


# ═══════════════════════════════════════════════════════════════════════════════
# Memory Dialect — in-memory list interpretation
# ═══════════════════════════════════════════════════════════════════════════════


def _handle_filter(op: Filter, data: list[Any]) -> list[Any]:
    """Filter items by expression evaluation."""
    return [item for item in data if op.expr.evaluate(item)]


def _handle_order_by(op: OrderBy, data: list[Any]) -> list[Any]:
    """Sort items by order specs (stable multi-key sort via reversed iteration)."""
    result = list(data)
    for spec in reversed(op.specs):
        result.sort(
            key=lambda item, _f=spec.field: getattr(item, _f),
            reverse=not spec.ascending,
        )
    return result


def _handle_offset(op: Offset, data: list[Any]) -> list[Any]:
    """Skip first N items."""
    return data[op.count:]


def _handle_limit(op: Limit, data: list[Any]) -> list[Any]:
    """Take first N items."""
    return data[:op.count]


def _handle_distinct(op: Distinct, data: list[Hashable]) -> list[Hashable]:
    """Remove duplicates. Items must be hashable (dataclasses are via field tuples)."""
    import dataclasses

    seen: set[Hashable] = set()
    unique: list[Hashable] = []
    for item in data:
        if dataclasses.is_dataclass(item):
            key: Hashable = tuple(
                getattr(item, f.name) for f in dataclasses.fields(item)
            )
        else:
            key = item
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def _handle_select(op: Select, data: list[Any]) -> list[Any]:
    """Select projection — return dicts with specified fields only."""
    return [{f: getattr(item, f) for f in op.fields} for item in data]  # type: ignore[misc]


def _unsupported(name: str) -> OpHandler[list[Any]]:
    """Create handler that raises for unsupported ops."""
    def handler(op: Any, data: list[Any]) -> list[Any]:
        raise TypeError(
            f"Memory dialect does not support {name}. "
            f"Use a SQL provider for this operation."
        )
    return handler


MEMORY_HANDLERS: Mapping[type, OpHandler[list[Any]]] = {
    Filter: _handle_filter,
    OrderBy: _handle_order_by,
    Offset: _handle_offset,
    Limit: _handle_limit,
    Distinct: _handle_distinct,
    Select: _handle_select,
    Aggregate: lambda op, data: data,  # handled by provider.aggregate(), not fold
    Join: _unsupported("Join"),
    GroupBy: _unsupported("GroupBy"),
    Having: _unsupported("Having"),
}

MEMORY_DIALECT: QueryDialect[list[Any]] = QueryDialect(
    context_type=list,
    handlers=MEMORY_HANDLERS,
)


__all__ = (
    "OpHandler",
    "fold_query",
    "QueryDialect",
    "MEMORY_HANDLERS",
    "MEMORY_DIALECT",
)

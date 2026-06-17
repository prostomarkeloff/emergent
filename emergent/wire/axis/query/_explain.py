"""Query explain — self-description of query operations via fold.

Each op (Filter, OrderBy, Limit, KVGet, ListOp, ...) implements
``compile_explain(ctx: ExplainContext) -> ExplainContext`` — same
self-compilation pattern as every other emergent axis. There is no
external dispatch table; fold finds ops via ExplainCompilable Protocol
and accumulates typed ExplainEntry values into the context.

    from emergent.wire.axis.query import relational
    from emergent.wire.axis.query._explain import explain, format_query

    q = relational(User).filter(...).limit(10)

    entries = explain(q.ops)          # tuple[ExplainEntry, ...]
    print(format_query(q.ops))        # "  1. Filter: ...\\n  2. Limit: count=10"

Custom ops that implement compile_explain participate automatically —
open-world, same as compile_pydantic / compile_sa_query / compile_verify_*.

The old handler-dict API (``RELATIONAL_EXPLAIN``, ``ExplainDialect``,
``explain_ops(ops, handlers)``) is kept as a backward-compatibility
layer that routes through the same fold.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from emergent.wire.axis._explain import (
    ExplainContext,
    ExplainNode,
    ExplainValue,
    Explainable,
    explain_nodes,
    to_dict,
)


type ExplainDict = dict[str, Any]
type ExplainDictList = list[dict[str, Any]]

# An op is an arbitrary self-describing value (open-world fold input). The alias
# keeps ``type(op)`` a known ``type[object]`` (not ``type[Unknown]`` as ``Any``
# would give) while staying out of the banned bare-``object`` annotation form.
type OpValue = object


# ═══════════════════════════════════════════════════════════════════════════════
# Primary API — typed self-compilation via fold (shared Explainable protocol)
# ═══════════════════════════════════════════════════════════════════════════════


def explain(ops: Sequence[OpValue]) -> tuple[ExplainNode, ...]:
    """Fold ops through Explainable — typed nodes.

    Open-world: ops that do not implement compile_explain are silently
    skipped (emergent's standard fold semantics).

        nodes = explain(query.ops)
        for n in nodes:
            print(n.kind, dict(n.fields))
    """
    return explain_nodes(ops)


def format_query(ops: Sequence[OpValue]) -> str:
    """Human-readable query explanation — formats from typed ExplainNode.

        print(format_query(q.ops))
        #   1. Filter: expr=balance > 100, fields=balance
        #   2. OrderBy: specs=name ASC
        #   3. Limit: count=10
    """
    return _format_entries(explain(ops))


def _format_entries(nodes: Sequence[ExplainNode]) -> str:
    if not nodes:
        return "(empty)"
    lines: list[str] = []
    for i, n in enumerate(nodes, 1):
        if n.fields:
            parts = ", ".join(f"{k}={v}" for k, v in n.fields)
            lines.append(f"  {i}. {n.kind}: {parts}")
        else:
            lines.append(f"  {i}. {n.kind}")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# Backward-compat layer — old handler-dict API routes through the fold
# ═══════════════════════════════════════════════════════════════════════════════
#
# The old explain_ops(ops, handlers) returned list[dict[str, Any]]; entries
# were produced by handler functions keyed by op type. We keep the surface
# stable by:
#   1. running the fold (self-compilation via compile_explain)
#   2. for any op_type in handlers, using the handler output directly — this
#      preserves override semantics used by tests and custom dialects
#   3. converting ExplainEntry to the historic dict shape


type ExplainHandler = Callable[[Any], dict[str, Any]]
type HandlerMap = Mapping[type, ExplainHandler]


def _entry_to_dict(node: ExplainNode) -> ExplainDict:
    return to_dict(node, type_key="op")


def explain_ops(
    ops: Sequence[OpValue],
    handlers: HandlerMap | None = None,
) -> ExplainDictList:
    """Backward-compat: dict-layer explain with optional handler overrides.

    Per-op:
      - If a handler is registered for op's exact type, call it.
      - Else if op implements compile_explain, fold-derive an ExplainNode
        and convert to dict.
      - Else return minimal ``{"op": <type_name>}``.
    """
    handlers = handlers or {}
    result: ExplainDictList = []
    for op in ops:
        op_t = type(op)
        if op_t in handlers:
            result.append(handlers[op_t](op))
            continue
        if isinstance(op, Explainable):
            ctx = op.compile_explain(ExplainContext())
            if ctx.nodes:
                result.append(_entry_to_dict(ctx.nodes[-1]))
                continue
        result.append({"op": op_t.__name__})
    return result


def format_ops(
    ops: Sequence[OpValue],
    handlers: HandlerMap | None = None,
) -> str:
    """Backward-compat: human-readable from dict layer."""
    entries = explain_ops(ops, handlers)
    if not entries:
        return "(empty)"
    lines: list[str] = []
    for i, entry in enumerate(entries, 1):
        lines.append(f"  {i}. {_format_entry(entry)}")
    return "\n".join(lines)


def _format_entry(entry: ExplainDict) -> str:
    op_name = entry.get("op", "?")
    rest = {k: v for k, v in entry.items() if k != "op"}
    if not rest:
        return str(op_name)
    parts = ", ".join(f"{k}={_format_value(v)}" for k, v in rest.items())
    return f"{op_name}: {parts}"


def _format_value(v: ExplainValue) -> str:
    if isinstance(v, (list, tuple)):
        return ", ".join(str(x) for x in v)
    return str(v)


# ═══════════════════════════════════════════════════════════════════════════════
# ExplainDialect — backward-compat thin wrapper over EXPLAIN_QUERY
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class ExplainDialect:
    """Backward-compat wrapper. Carries optional per-type handler overrides
    that short-circuit the op's own compile_explain when the op_type matches.

    Prefer :func:`explain` / :func:`format_query` directly — they already
    do open-world self-compilation via fold.
    """

    handlers: HandlerMap

    def explain(self, ops: Sequence[Any]) -> ExplainDictList:
        return explain_ops(ops, self.handlers)

    def format(self, ops: Sequence[Any]) -> str:
        return format_ops(ops, self.handlers)

    def with_handler(
        self, op_type: type, handler: ExplainHandler
    ) -> ExplainDialect:
        merged = {**self.handlers, op_type: handler}
        return replace(self, handlers=merged)

    def without_handler(self, op_type: type) -> ExplainDialect:
        filtered = {k: v for k, v in self.handlers.items() if k is not op_type}
        return replace(self, handlers=filtered)


# Empty handler maps — kept as constants for API compatibility. All ops are
# self-compiling now; no registry needed.
RELATIONAL_EXPLAIN: HandlerMap = {}
API_EXPLAIN: HandlerMap = {}
KV_EXPLAIN: HandlerMap = {}

RELATIONAL_EXPLAIN_DIALECT: ExplainDialect = ExplainDialect(handlers={})
API_EXPLAIN_DIALECT: ExplainDialect = ExplainDialect(handlers={})
KV_EXPLAIN_DIALECT: ExplainDialect = ExplainDialect(handlers={})


__all__ = (
    # Primary API
    "explain",
    "format_query",
    # Backward-compat
    "ExplainHandler",
    "explain_ops",
    "format_ops",
    "ExplainDialect",
    "RELATIONAL_EXPLAIN",
    "API_EXPLAIN",
    "KV_EXPLAIN",
    "RELATIONAL_EXPLAIN_DIALECT",
    "API_EXPLAIN_DIALECT",
    "KV_EXPLAIN_DIALECT",
)

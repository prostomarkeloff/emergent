"""Storage explain — self-description of storage patterns and composition.

Two layers:
  1. Dict-returning: storage_dict() — structured data for tools/analysis
  2. Human-readable: explain_storage() — formats from storage_dict()

    from emergent.wire.axis.storage._explain import (
        storage_dict, explain_storage, STORAGE_EXPLAIN,
    )

    data = storage_dict(my_kv)           # -> dict
    text = explain_storage(my_kv)        # -> str

Dispatch now goes through the shared `Explainable` protocol (each store carries a
`compile_explain` method); the external `STORAGE_EXPLAIN` map is kept (empty) for
API compatibility and as the per-type override channel. Open-world: unknown types
get the generic `_unknown_dict` fallback. Recursive: composition wrappers (PrefixKV,
TieredKV, ...) expand their inner stores via `ctx.child`.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Mapping
from dataclasses import replace
from typing import Any

from emergent.wire.axis._explain import (
    ExplainContext,
    ExplainNode,
    Explainable,
    to_dict,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Types
# ═══════════════════════════════════════════════════════════════════════════════


type ExplainDict = dict[str, Any]
type StorageExplainHandler = Callable[[Any, _ExplainCtx], dict[str, Any]]
type HandlerMap = Mapping[type, StorageExplainHandler]


class _ExplainCtx:
    """Recursive explain driver — per-type override → protocol → fallback.

    Kept (tests reference it as the custom-handler signature `(store, ctx)`). It
    threads an `ExplainCtx` whose `child` re-enters this dispatch, so a custom
    handler propagates to nested stores at any depth.
    """

    __slots__ = ("handlers", "_ctx")

    def __init__(self, handlers: HandlerMap) -> None:
        self.handlers = handlers
        self._ctx = ExplainContext(resolve=self._resolve)

    def _resolve(self, store: Any, ctx: ExplainContext) -> ExplainNode:
        handler = self.handlers.get(type(store))
        if handler is not None:
            return ExplainNode(type(store).__name__, raw=handler(store, self))
        if isinstance(store, Explainable):
            return store.compile_explain(replace(ctx, nodes=())).nodes[-1]
        return ExplainNode(type(store).__name__, raw=_unknown_dict(store))

    def explain(self, store: Any) -> ExplainDict:
        """Recursively explain a store into a dict."""
        return to_dict(self._ctx.explain(store), type_key="type")


# ═══════════════════════════════════════════════════════════════════════════════
# Fallback for unknown types
# ═══════════════════════════════════════════════════════════════════════════════


def _unknown_dict(obj: Any) -> ExplainDict:
    """Fallback for unknown types."""
    d: ExplainDict = {"type": type(obj).__name__}
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        for f in dataclasses.fields(obj):
            val = getattr(obj, f.name)
            if isinstance(val, type):
                d[f.name] = val.__name__
            elif isinstance(val, (str, int, float, bool, type(None))):
                d[f.name] = val
            else:
                d[f.name] = type(val).__name__
    return d


# ═══════════════════════════════════════════════════════════════════════════════
# Handler map — empty (stores self-describe via Explainable); override channel
# ═══════════════════════════════════════════════════════════════════════════════


STORAGE_EXPLAIN: HandlerMap = {}


# ═══════════════════════════════════════════════════════════════════════════════
# Dict-returning layer — structured data
# ═══════════════════════════════════════════════════════════════════════════════


def storage_dict(
    store: Any,
    handlers: HandlerMap | None = None,
) -> ExplainDict:
    """Storage pattern/wrapper as structured dict.

    Args:
        store: Storage instance (KV, Queue, PrefixKV, TieredKV, etc.)
        handlers: Per-type override handlers (default: none — all stores
            self-describe via their `compile_explain`)

    Returns:
        Dict describing the storage tree. Composition wrappers
        include nested dicts for their inner stores.

    Example:
        data = storage_dict(my_tiered_kv)
        data["type"]    # "TieredKV"
        data["l1"]      # nested dict for L1
        data["l2"]      # nested dict for L2
    """
    effective = handlers if handlers is not None else STORAGE_EXPLAIN
    ctx = _ExplainCtx(effective)
    return ctx.explain(store)


# ═══════════════════════════════════════════════════════════════════════════════
# Human-readable layer — formats from dicts
# ═══════════════════════════════════════════════════════════════════════════════


def explain_storage(
    store: Any,
    handlers: HandlerMap | None = None,
) -> str:
    """Human-readable explanation of a storage pattern. Formats from storage_dict().

    Example:
        print(explain_storage(my_tiered_kv))
        # TieredKV:
        #   L1: PrefixKV(prefix="cache:")
        #     inner: KV(codec=JsonCodec, backend=MemoryStorage)
        #   L2: KV(codec=PickleCodec, backend=RedisBackend)
        #   l1_ttl: 300.0s
    """
    data = storage_dict(store, handlers)
    return _format_storage(data, indent=0)


# ═══════════════════════════════════════════════════════════════════════════════
# Formatters (dict → str)
# ═══════════════════════════════════════════════════════════════════════════════


def _format_storage(data: ExplainDict, indent: int) -> str:
    """Recursively format a storage dict as human-readable string."""
    prefix = "  " * indent
    type_name = data.get("type", "?")

    # Leaf nodes (KV, Queue, etc.) — single line
    nested_keys = [k for k, v in data.items() if isinstance(v, dict) and k != "type"]
    scalar_keys = [
        k for k in data
        if k != "type" and k not in nested_keys
    ]

    if not nested_keys:
        # All scalar — format as single line
        if scalar_keys:
            parts = ", ".join(f"{k}={_format_scalar(data[k])}" for k in scalar_keys)
            return f"{prefix}{type_name}({parts})"
        return f"{prefix}{type_name}"

    # Has nested children — multi-line
    lines: list[str] = [f"{prefix}{type_name}:"]

    for k in scalar_keys:
        lines.append(f"{prefix}  {k}: {_format_scalar(data[k])}")

    for k in nested_keys:
        child = data[k]
        child_str = _format_storage(child, indent + 1).lstrip()
        lines.append(f"{prefix}  {k}: {child_str}")

    return "\n".join(lines)


def _format_scalar(v: Any) -> str:
    """Format a scalar value for output."""
    if isinstance(v, float):
        return f"{v}s"
    if isinstance(v, str):
        return repr(v)
    return str(v)


__all__ = (
    # Types
    "StorageExplainHandler",
    # Dict layer
    "storage_dict",
    # Human-readable layer
    "explain_storage",
    # Pre-built handlers
    "STORAGE_EXPLAIN",
)

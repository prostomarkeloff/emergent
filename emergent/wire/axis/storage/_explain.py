"""Storage explain — self-description of storage patterns and composition.

Two layers:
  1. Dict-returning: storage_dict() — structured data for tools/analysis
  2. Human-readable: explain_storage() — formats from storage_dict()

    from emergent.wire.axis.storage._explain import (
        storage_dict, explain_storage, STORAGE_EXPLAIN,
    )

    data = storage_dict(my_kv)           # -> dict
    text = explain_storage(my_kv)        # -> str

Open-world: unknown types get generic fallback.
Recursive: composition wrappers (PrefixKV, TieredKV, etc.) expand their inner stores.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Mapping
from typing import Any

from emergent.wire.axis.storage._kv import KV, KVNX
from emergent.wire.axis.storage._queue import Queue, QueueFull
from emergent.wire.axis.storage._pubsub import PubSub
from emergent.wire.axis.storage._lock import Lock, LockExtend
from emergent.wire.axis.storage._counter import Counter, CounterFull
from emergent.wire.axis.storage._compose import PrefixKV, TieredKV, FallbackKV, ReadonlyKV


# ═══════════════════════════════════════════════════════════════════════════════
# Types
# ═══════════════════════════════════════════════════════════════════════════════


type ExplainDict = dict[str, Any]
type StorageExplainHandler = Callable[[Any, _ExplainCtx], dict[str, Any]]
type HandlerMap = Mapping[type, StorageExplainHandler]


class _ExplainCtx:
    """Internal context for recursive explain calls."""

    __slots__ = ("handlers",)

    def __init__(self, handlers: HandlerMap) -> None:
        self.handlers = handlers

    def explain(self, store: Any) -> ExplainDict:
        """Recursively explain a store."""
        handler = self.handlers.get(type(store))
        if handler is not None:
            return handler(store, self)
        return _unknown_dict(store)


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _codec_name(codec: Any) -> str:
    """Get human-readable codec name."""
    return type(codec).__name__


def _backend_name(backend: Any) -> str:
    """Get human-readable backend name."""
    return type(backend).__name__


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
# Pattern Handlers
# ═══════════════════════════════════════════════════════════════════════════════


def _explain_kv(store: KV[Any, Any], ctx: _ExplainCtx) -> ExplainDict:
    return {
        "type": "KV",
        "codec": _codec_name(store.codec),
        "backend": _backend_name(store.backend),
    }


def _explain_kvnx(store: KVNX[Any, Any], ctx: _ExplainCtx) -> ExplainDict:
    return {
        "type": "KVNX",
        "codec": _codec_name(store.codec),
        "backend": _backend_name(store.backend),
    }


def _explain_queue(store: Queue[Any, Any], ctx: _ExplainCtx) -> ExplainDict:
    return {
        "type": "Queue",
        "codec": _codec_name(store.codec),
        "backend": _backend_name(store.backend),
    }


def _explain_queue_full(store: QueueFull[Any, Any], ctx: _ExplainCtx) -> ExplainDict:
    return {
        "type": "QueueFull",
        "codec": _codec_name(store.codec),
        "backend": _backend_name(store.backend),
    }


def _explain_pubsub(store: PubSub[Any, Any], ctx: _ExplainCtx) -> ExplainDict:
    return {
        "type": "PubSub",
        "codec": _codec_name(store.codec),
        "backend": _backend_name(store.backend),
    }


def _explain_lock(store: Lock[Any], ctx: _ExplainCtx) -> ExplainDict:
    return {
        "type": "Lock",
        "backend": _backend_name(store.backend),
    }


def _explain_lock_extend(store: LockExtend[Any], ctx: _ExplainCtx) -> ExplainDict:
    return {
        "type": "LockExtend",
        "backend": _backend_name(store.backend),
    }


def _explain_counter(store: Counter[Any], ctx: _ExplainCtx) -> ExplainDict:
    return {
        "type": "Counter",
        "backend": _backend_name(store.backend),
    }


def _explain_counter_full(store: CounterFull[Any], ctx: _ExplainCtx) -> ExplainDict:
    return {
        "type": "CounterFull",
        "backend": _backend_name(store.backend),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Composition Handlers (recursive)
# ═══════════════════════════════════════════════════════════════════════════════


def _explain_prefix_kv(store: PrefixKV[Any, Any], ctx: _ExplainCtx) -> ExplainDict:
    return {
        "type": "PrefixKV",
        "prefix": store.prefix,
        "inner": ctx.explain(store.inner),
    }


def _explain_tiered_kv(store: TieredKV[Any, Any], ctx: _ExplainCtx) -> ExplainDict:
    d: ExplainDict = {
        "type": "TieredKV",
        "l1": ctx.explain(store.l1),
        "l2": ctx.explain(store.l2),
    }
    if store.l1_ttl is not None:
        d["l1_ttl"] = store.l1_ttl.total_seconds()
    return d


def _explain_fallback_kv(store: FallbackKV[Any, Any], ctx: _ExplainCtx) -> ExplainDict:
    return {
        "type": "FallbackKV",
        "primary": ctx.explain(store.primary),
        "secondary": ctx.explain(store.secondary),
    }


def _explain_readonly_kv(store: ReadonlyKV[Any, Any], ctx: _ExplainCtx) -> ExplainDict:
    return {
        "type": "ReadonlyKV",
        "inner": ctx.explain(store.inner),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Pre-built handler mapping
# ═══════════════════════════════════════════════════════════════════════════════


STORAGE_EXPLAIN: HandlerMap = {
    # Patterns
    KV: _explain_kv,
    KVNX: _explain_kvnx,
    Queue: _explain_queue,
    QueueFull: _explain_queue_full,
    PubSub: _explain_pubsub,
    Lock: _explain_lock,
    LockExtend: _explain_lock_extend,
    Counter: _explain_counter,
    CounterFull: _explain_counter_full,
    # Composition wrappers (recursive)
    PrefixKV: _explain_prefix_kv,
    TieredKV: _explain_tiered_kv,
    FallbackKV: _explain_fallback_kv,
    ReadonlyKV: _explain_readonly_kv,
}


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
        handlers: Custom handlers (default: STORAGE_EXPLAIN)

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

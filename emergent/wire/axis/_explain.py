"""Axis-spanning self-description — one `Explainable` protocol for every axis.

This is the shared substrate that unifies the per-axis "explain" mechanisms
(query / surface / storage / derive). Every self-describing object — a query op,
a surface trigger/codec, a storage store, a derivation spec — implements the same
method, following emergent's universal `compile_*(self, ctx) -> ctx` convention:

    def compile_explain(self, ctx: ExplainContext) -> ExplainContext: ...

So a sequence of items is described exactly like every other compilation pass —
by folding them through the protocol:

    ctx = fold(items, ExplainContext(), Explainable, "compile_explain")

`ExplainContext` is the accumulator (a tuple of `ExplainNode`s). `ExplainNode` is
the recursive value (kind + scalar fields + keyed children). A leaf adds one node
via `ctx.add(...)`; a tree node recurses into its children with `ctx.explain(child)`
and embeds the resulting node. One renderer (`to_dict`) turns a node into the
historic dict shape; each axis keeps its own human-readable formatter on top.

Dispatch follows the same three tiers as the universal `fold` primitive: a per-type
override handler → the `Explainable` protocol → a reflection fallback. Overrides
return plain dicts (handler signatures vary per axis); `ExplainNode.raw` is the
escape hatch that carries such a dict verbatim through the tree.

`Any` appears where this layer is genuinely reflective over arbitrary user objects
(the same choice the `fold` primitive and every per-axis explain module already
make): the inputs are open-world values, not a fixed protocol.

This module imports only stdlib/typing at load time; axes import *down* into it
(no cycles). It is distinct from `schema/_explain.py` (field-capability
introspection) and `compile/_explain.py` (compilation-trace events).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field, replace
from typing import Any, Protocol, runtime_checkable

# ═══════════════════════════════════════════════════════════════════════════════
# Value types
# ═══════════════════════════════════════════════════════════════════════════════

# Scalar payloads a self-described field may carry — a closed union, no Any.
type ExplainValue = str | int | float | bool | None | tuple[str, ...] | list[str]
type ExplainFields = tuple[tuple[str, ExplainValue], ...]
# A child slot is either one node or an ordered list of nodes (e.g. exposures).
type ExplainChild = "ExplainNode | tuple[ExplainNode, ...]"
# Rendered dict shape + the override escape-hatch payload. Reflective/open-world,
# so the value type is Any (as in every per-axis explain module's `JsonDict`).
type ExplainDict = dict[str, Any]
type ExplainRaw = Mapping[str, Any]
# A single-object dispatcher an axis may inject for override-aware recursion.
type ExplainResolve = Callable[[Any, "ExplainContext"], "ExplainNode"]


@dataclass(frozen=True, slots=True)
class ExplainNode:
    """One self-described node: a kind label + scalar fields + keyed children.

    `raw` is the override escape hatch: when set, `to_dict` returns it verbatim
    and ignores `fields`/`children`. It carries a custom handler's dict result
    (handler signatures vary per axis, so the dict — not a re-parsed node — is the
    faithful unit), exactly as the legacy `Mapping[type, Callable[..., dict]]`
    registries produced.
    """

    kind: str
    fields: ExplainFields = ()
    children: tuple[tuple[str, ExplainChild], ...] = ()
    raw: ExplainRaw | None = None


@dataclass(frozen=True, slots=True)
class ExplainContext:
    """Accumulator threaded through `compile_explain` — the fold context.

    `nodes` collects the nodes added during a fold pass. `resolve` lets an axis
    inject override-aware single-object dispatch (storage's deep custom handlers);
    when absent, `explain` does the standard protocol → reflection dispatch.

    A flat leaf returns `ctx.add(node)`. A tree node builds child nodes with
    `ctx.explain(child)` and returns `ctx.add(parent_with_children)`.
    """

    nodes: tuple[ExplainNode, ...] = ()
    resolve: ExplainResolve | None = field(default=None)

    def add(self, node: ExplainNode) -> ExplainContext:
        """Append a node — the `compile_explain` accumulator step."""
        return replace(self, nodes=(*self.nodes, node))

    def explain(self, obj: Any) -> ExplainNode:
        """Describe one child object into a single node (for tree recursion).

        Override handler → `Explainable` protocol → reflection fallback. The
        protocol path folds the child on a fresh accumulator (preserving
        `resolve`) and takes the node it produced.
        """
        if self.resolve is not None:
            return self.resolve(obj, self)
        if isinstance(obj, Explainable):
            return obj.compile_explain(replace(self, nodes=())).nodes[-1]
        return reflect_node(obj)


@runtime_checkable
class Explainable(Protocol):
    """Structural marker — an object that self-describes into an `ExplainContext`."""

    def compile_explain(self, ctx: ExplainContext) -> ExplainContext: ...


def explain_nodes(
    items: Iterable[Any],
    *,
    resolve: ExplainResolve | None = None,
) -> tuple[ExplainNode, ...]:
    """Fold a sequence of items through `Explainable` — the standard entry point.

    Uses the universal `fold` primitive: unknown items are silently skipped.
    """
    from emergent.wire.compile._core import fold

    initial = ExplainContext(resolve=resolve)
    result = fold(items, initial, Explainable, "compile_explain")
    return result.nodes


# ═══════════════════════════════════════════════════════════════════════════════
# Reflection fallback + the inherited default mixin
# ═══════════════════════════════════════════════════════════════════════════════


@runtime_checkable
class _Named(Protocol):
    __name__: str


def callable_name(fn: Callable[..., Any]) -> str:
    """Name of a callable, falling back to repr when it has no ``__name__``."""
    if isinstance(fn, _Named):
        return fn.__name__
    return repr(fn)


def _scalarize(val: Any) -> ExplainValue:
    """Collapse a field value to an `ExplainValue` for the generic default.

    type → its name; scalar → itself; tuple/list of str → as a list; anything
    else → `str(val)`. Axes whose legacy fallback used a different collapse rule
    (storage's typename, surface's raw value) keep their own `_unknown_dict` /
    `_dataclass_dict`; this is only the generic `AutoExplain`/`reflect_node` rule.
    """
    if isinstance(val, type):
        return val.__name__
    if isinstance(val, bool | int | float | str) or val is None:
        return val
    if isinstance(val, (tuple, list)) and all(isinstance(x, str) for x in val):
        return [str(x) for x in val]
    return str(val)


def reflect_node(obj: Any) -> ExplainNode:
    """Generic reflection — kind = class name, scalar fields via `_scalarize`.

    The shared fallback for objects that implement neither a custom
    `compile_explain` nor an axis-specific handler. Reads frozen/slots dataclass
    fields by name (no ``__dict__`` exists under ``slots=True``).
    """
    kind = type(obj).__name__
    if not dataclasses.is_dataclass(obj) or isinstance(obj, type):
        return ExplainNode(kind=kind)
    pairs = tuple(
        (f.name, _scalarize(getattr(obj, f.name))) for f in dataclasses.fields(obj)
    )
    return ExplainNode(kind=kind, fields=pairs)


class AutoExplain:
    """Mixin — inherit to get the generic reflection `compile_explain` for free.

    Generalizes query's former `AutoPrintable`. Leaves whose desired output is
    "kind + scalar fields" inherit it as-is; everything with a semantic label,
    a custom value format, or children overrides `compile_explain`. `__slots__=()`
    so it composes cleanly with `@dataclass(frozen=True, slots=True)` classes.
    """

    __slots__ = ()

    def compile_explain(self, ctx: ExplainContext) -> ExplainContext:
        return ctx.add(reflect_node(self))


# ═══════════════════════════════════════════════════════════════════════════════
# Renderer — node → historic dict shape
# ═══════════════════════════════════════════════════════════════════════════════


def to_dict(node: ExplainNode, *, type_key: str | None) -> ExplainDict:
    """Render a node to the historic dict shape.

    `type_key` names the kind slot — `"type"` (surface/storage/derive), `"op"`
    (query), or `None` to omit it (container dicts that carry no kind). `raw`
    short-circuits to the verbatim override dict. Insertion order is
    kind → fields → children, reproducing every legacy dict.
    """
    if node.raw is not None:
        return dict(node.raw)
    out: ExplainDict = {}
    if type_key is not None:
        out[type_key] = node.kind
    for key, value in node.fields:
        out[key] = value
    for key, child in node.children:
        if isinstance(child, tuple):
            out[key] = [to_dict(c, type_key=type_key) for c in child]
        else:
            out[key] = to_dict(child, type_key=type_key)
    return out


__all__ = (
    "ExplainValue",
    "ExplainFields",
    "ExplainChild",
    "ExplainDict",
    "ExplainRaw",
    "ExplainResolve",
    "ExplainNode",
    "ExplainContext",
    "Explainable",
    "explain_nodes",
    "reflect_node",
    "AutoExplain",
    "to_dict",
    "callable_name",
)

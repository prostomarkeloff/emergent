"""Derivelib explain — self-description of derivation pipelines.

Two layers:
  1. Dict-returning: opspec_dict(), step_dict(), derivation_dict(), entity_derivation_dict()
  2. Human-readable: explain_entity(), explain_derivation(), explain_opspec()

    from derivelib._explain import explain_entity, entity_derivation_dict

    data = entity_derivation_dict(User)     # -> dict
    text = explain_entity(User)             # -> str

Open-world: unknown step types get generic fallback, never crash.
Handler dispatch: pre-built DERIVE_EXPLAIN mapping, extensible by users.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Mapping
from typing import Any

from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger
from emergent.wire.axis.surface.triggers.cli import CLITrigger

from derivelib._derivation import Derivation, Step
from derivelib._derive import get_derivations, get_exposures, get_patterns
from derivelib._fold import fold_derive, materialize
from derivelib._opspec import OpSpec


# =============================================================================
# Types
# =============================================================================

# Recursive JSON-like type for explain dicts. Explain output is inherently
# heterogeneous (str, int, bool, None, nested dicts/lists). This captures
# the full structure without Any.
type ExplainValue = str | int | float | bool | None | list[ExplainValue] | dict[str, ExplainValue]
type ExplainDict = dict[str, ExplainValue]

type DeriveExplainHandler = Callable[[Step], ExplainDict]


# =============================================================================
# ExplainValue Narrowing Helpers
# =============================================================================


def _dicts(val: ExplainValue) -> list[ExplainDict]:
    """Narrow ExplainValue → list of dicts (filtering non-dict elements)."""
    return [x for x in val if isinstance(x, dict)] if isinstance(val, list) else []


def _str(val: ExplainValue, default: str = "?") -> str:
    """Narrow ExplainValue → str with fallback."""
    return val if isinstance(val, str) else str(val) if val is not None else default


def _dict(val: ExplainValue) -> ExplainDict:
    """Narrow ExplainValue → dict, empty dict if not a dict."""
    return val if isinstance(val, dict) else {}


def _int(val: ExplainValue, default: int = 0) -> int:
    """Narrow ExplainValue → int with fallback."""
    return val if isinstance(val, int) else default


# =============================================================================
# Generic Helpers
# =============================================================================


def _iter_to_explain(items: Any) -> list[ExplainValue]:
    """Convert an iterable to list of ExplainValue.

    Separate function to avoid isinstance(Any, tuple) → tuple[Unknown, ...]
    narrowing. Iterating Any directly yields Any elements, not Unknown.
    """
    return [_field_to_explain(e) for e in items]


def _field_to_explain(val: Any) -> ExplainValue:
    """Convert a single dataclass field value to ExplainValue.

    Any: dataclass field values from vars() are dict[str, Any] per typeshed;
    isinstance narrows Any→tuple[Unknown, ...] (unrecoverable), so Any is
    the only viable parameter type for generic dataclass introspection.
    """
    if isinstance(val, type):
        return val.__name__
    if isinstance(val, (str, int, float, bool, type(None))):
        return val
    if isinstance(val, tuple):
        return _iter_to_explain(val)
    return type(val).__name__


def _get_field_value(obj: object, name: str) -> Any:
    """Get dataclass field value, returning Any to break pyright's Unknown chain.

    getattr on DataclassInstance returns Unknown; this function re-types
    through its Any return annotation.
    """
    return getattr(obj, name)


def _dataclass_dict(obj: object) -> ExplainDict:
    """Any frozen dataclass -> dict via dataclass fields contract."""
    d: ExplainDict = {"type": type(obj).__name__}
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        for f in dataclasses.fields(obj):
            d[f.name] = _field_to_explain(_get_field_value(obj, f.name))
    return d


def _trigger_dict(trigger: object) -> ExplainDict:
    """Trigger -> structured dict."""
    if isinstance(trigger, HTTPRouteTrigger):
        return {"type": "HTTPRouteTrigger", "method": trigger.method, "path": trigger.path}
    if isinstance(trigger, CLITrigger):
        d: ExplainDict = {"type": "CLITrigger", "command": trigger.command}
        if trigger.description:
            d["description"] = trigger.description
        return d
    return _dataclass_dict(trigger)


def _trigger_short(trigger: object) -> str:
    """Trigger -> short human-readable label."""
    if isinstance(trigger, HTTPRouteTrigger):
        return f"{trigger.method} {trigger.path}"
    if isinstance(trigger, CLITrigger):
        return f"{trigger.command} (cli)"
    return type(trigger).__name__


def _effect_dict(effect: object) -> ExplainDict:
    """Effect -> structured dict (same pattern as capability dict)."""
    return _dataclass_dict(effect)


def _effect_repr(effect: object) -> str:
    """Effect -> short human-readable string."""
    name = type(effect).__name__
    if dataclasses.is_dataclass(effect) and not isinstance(effect, type):
        fields = dataclasses.fields(effect)
        if not fields:
            return name
        parts: list[str] = []
        for f in fields:
            val = getattr(effect, f.name)
            if val != f.default:
                parts.append(f"{f.name}={val!r}")
        if parts:
            return f"{name}({', '.join(parts)})"
    return name


# =============================================================================
# Step Handlers
# =============================================================================


def _explain_inspect_entity(step: Step) -> ExplainDict:
    return {"type": "InspectEntity"}


def _explain_require_identity(step: Step) -> ExplainDict:
    return {"type": "RequireIdentity"}


def _explain_exclude_schema_fields(step: Step) -> ExplainDict:
    from derivelib.axes.schema import ExcludeSchemaFields
    s = step if isinstance(step, ExcludeSchemaFields) else step
    return {"type": "ExcludeSchemaFields", "names": list(getattr(s, "names", ()))}


def _explain_require_fields(step: Step) -> ExplainDict:
    return {"type": "RequireFields", "names": list(getattr(step, "names", ()))}


def _explain_bind_provider(step: Step) -> ExplainDict:
    node = getattr(step, "node_type", None)
    d: ExplainDict = {"type": "BindProvider"}
    if node is not None:
        d["node"] = node.__name__ if isinstance(node, type) else str(node)
    return d


def _explain_set_base_query(step: Step) -> ExplainDict:
    return {"type": "SetBaseQuery"}


def _explain_set_custom_base_query(step: Step) -> ExplainDict:
    return {"type": "SetCustomBaseQuery"}


def _explain_derive_op(step: Step) -> ExplainDict:
    from derivelib.axes.surface import DeriveOp
    if not isinstance(step, DeriveOp):
        return _dataclass_dict(step)
    d: ExplainDict = {
        "type": "DeriveOp",
        "name": step.name,
        "input_proj": type(step.input_proj).__name__,
        "output": type(step.output).__name__,
        "trigger": _trigger_dict(step.trigger),
    }
    if step.effects:
        d["effects"] = [_effect_dict(e) for e in step.effects]
    if step.capabilities:
        d["capabilities"] = [_dataclass_dict(c) for c in step.capabilities]
    if step.extra_op_fields:
        d["extra_op_fields"] = [name for name, _ in step.extra_op_fields]
    if step.extra_request_fields:
        d["extra_request_fields"] = [fs[0] for fs in step.extra_request_fields]
    return d


def _explain_expose_op(step: Step) -> ExplainDict:
    from derivelib.axes.surface import ExposeOp
    if not isinstance(step, ExposeOp):
        return _dataclass_dict(step)
    d: ExplainDict = {
        "type": "ExposeOp",
        "op_type": step.op_type.__name__,
        "trigger": _trigger_dict(step.trigger),
    }
    if step.capabilities:
        d["capabilities"] = [_dataclass_dict(c) for c in step.capabilities]
    return d


def _explain_add_global_cap(step: Step) -> ExplainDict:
    from derivelib.axes.surface import AddGlobalCap
    if not isinstance(step, AddGlobalCap):
        return _dataclass_dict(step)
    return {
        "type": "AddGlobalCap",
        "cap": _dataclass_dict(step.cap),
    }


def _explain_adapt_base_query(step: Step) -> ExplainDict:
    return {"type": "AdaptBaseQuery"}


def _explain_expose_method(step: Step) -> ExplainDict:
    from derivelib.patterns.methods import ExposeMethod
    if not isinstance(step, ExposeMethod):
        return _dataclass_dict(step)
    d: ExplainDict = {
        "type": "ExposeMethod",
        "service": step.service.__name__,
        "method": step.method_name,
        "trigger": _trigger_dict(step.trigger),
    }
    if step.capabilities:
        d["capabilities"] = [_dataclass_dict(c) for c in step.capabilities]
    if step.suffix:
        d["suffix"] = step.suffix
    return d


# =============================================================================
# Pre-built Handler Mapping
# =============================================================================


def _build_handlers() -> dict[type, DeriveExplainHandler]:
    """Build handler mapping. Lazy imports to avoid cycles."""
    from derivelib.axes.schema import (
        InspectEntity,
        RequireIdentity,
        ExcludeSchemaFields,
        RequireFields,
    )
    from derivelib.axes.query import BindProvider, SetBaseQuery, SetCustomBaseQuery
    from derivelib.axes.surface import DeriveOp, ExposeOp, AddGlobalCap
    from derivelib.adapt import AdaptBaseQuery
    from derivelib.patterns.methods import ExposeMethod

    return {
        InspectEntity: _explain_inspect_entity,
        RequireIdentity: _explain_require_identity,
        ExcludeSchemaFields: _explain_exclude_schema_fields,
        RequireFields: _explain_require_fields,
        BindProvider: _explain_bind_provider,
        SetBaseQuery: _explain_set_base_query,
        SetCustomBaseQuery: _explain_set_custom_base_query,
        DeriveOp: _explain_derive_op,
        ExposeOp: _explain_expose_op,
        AddGlobalCap: _explain_add_global_cap,
        AdaptBaseQuery: _explain_adapt_base_query,
        ExposeMethod: _explain_expose_method,
    }


_handlers_cache: dict[type, DeriveExplainHandler] | None = None


def _get_handlers() -> dict[type, DeriveExplainHandler]:
    global _handlers_cache
    if _handlers_cache is None:
        _handlers_cache = _build_handlers()
    return _handlers_cache


class _LazyHandlers(Mapping[type, DeriveExplainHandler]):
    """Lazy Mapping that builds handlers on first access."""

    def __getitem__(self, key: type) -> DeriveExplainHandler:
        return _get_handlers()[key]

    def __contains__(self, key: object) -> bool:
        if not isinstance(key, type):
            return False
        return key in _get_handlers()

    def __iter__(self):  # noqa: ANN204
        return iter(_get_handlers())

    def __len__(self) -> int:
        return len(_get_handlers())


DERIVE_EXPLAIN: Mapping[type, DeriveExplainHandler] = _LazyHandlers()


# =============================================================================
# Dict Layer
# =============================================================================


def opspec_dict(spec: OpSpec) -> ExplainDict:
    """OpSpec -> structured dict.

    Shows the operation description before materialization:
    name, entity, input fields, response shape, trigger, effects, capabilities.
    """
    d: ExplainDict = {
        "name": spec.name,
        "entity_name": spec.entity_name,
        "input_fields": list(spec.input_fields.keys()),
        "response_spec": type(spec.response_spec).__name__,
        "trigger": _trigger_dict(spec.trigger),
    }
    if spec.effects:
        d["effects"] = [_effect_dict(e) for e in spec.effects]
    if spec.capabilities:
        d["capabilities"] = [_dataclass_dict(c) for c in spec.capabilities]
    return d


def step_dict(
    step: Step,
    handlers: Mapping[type, DeriveExplainHandler] | None = None,
) -> ExplainDict:
    """Single derivation step -> structured dict.

    Dispatches to pre-built handlers for known types.
    Falls back to _dataclass_dict for unknown types.
    """
    effective = handlers if handlers is not None else DERIVE_EXPLAIN
    handler = effective.get(type(step))
    if handler is not None:
        return handler(step)
    return _dataclass_dict(step)


def derivation_dict(
    steps: Derivation,
    handlers: Mapping[type, DeriveExplainHandler] | None = None,
) -> ExplainDict:
    """Full derivation (tuple of steps) -> structured dict.

    Args:
        steps: Ordered tuple of derivation steps
        handlers: Custom handlers (default: DERIVE_EXPLAIN)

    Returns:
        Dict with step_count and per-step dicts.
    """
    return {
        "step_count": len(steps),
        "steps": [step_dict(s, handlers) for s in steps],
    }


def entity_derivation_dict(
    entity: type,
    handlers: Mapping[type, DeriveExplainHandler] | None = None,
) -> ExplainDict:
    """@derive-decorated entity -> full derivation dict.

    Compiles each pattern, folds through axes, and shows:
    - Pattern type and step count
    - Per-step dicts
    - Accumulated OpSpecs from fold result
    - Direct operations and provider info

    Args:
        entity: Entity class decorated with @derive
        handlers: Custom handlers (default: DERIVE_EXPLAIN)
    """
    patterns = get_patterns(entity)
    exposures = get_exposures(entity)
    derivation_transforms = get_derivations(entity)

    result: ExplainDict = {
        "entity": entity.__name__,
        "pattern_count": len(patterns),
        "patterns": [],
    }

    pattern_list: list[ExplainValue] = []
    # type[object] lets fold_derive infer EntityT = object (not Unknown).
    entity_cls: type[object] = entity
    for pattern in patterns:
        steps = pattern.compile(entity)
        ctx = fold_derive(steps, entity_cls)
        surface = ctx.surface
        pattern_data: ExplainDict = {
            "pattern_type": type(pattern).__name__,
            "step_count": len(steps),
            "steps": [step_dict(s, handlers) for s in steps],
            "specs": [opspec_dict(s) for s in surface.specs],
        }
        if surface.operations:
            pattern_data["direct_operations"] = len(surface.operations)
        provider_node = ctx.query.provider_node
        if provider_node is not None:
            pattern_data["provider_node"] = provider_node.__name__
        pattern_list.append(pattern_data)

    result["patterns"] = pattern_list

    if exposures:
        result["direct_exposures"] = len(exposures)
    if derivation_transforms:
        result["transforms"] = len(derivation_transforms)

    return result


def dialect_dict(d: object) -> ExplainDict:
    """Dialect pattern -> structured dict showing ops + trigger config.

    Args:
        d: Dialect instance
    """
    from derivelib._dialect import Dialect

    if not isinstance(d, Dialect):
        return _dataclass_dict(d)

    result: ExplainDict = {
        "type": "Dialect",
        "op_count": len(d.ops),
        "ops": [_op_descriptor_dict(op) for op in d.ops],
        "triggers": type(d.triggers).__name__,
    }
    if d.capabilities:
        result["capabilities"] = [_dataclass_dict(c) for c in d.capabilities]
    result["adapt"] = d.adapt
    return result


def _op_descriptor_dict(op: object) -> ExplainDict:
    """Op descriptor -> structured dict."""
    from derivelib._dialect import Op

    if not isinstance(op, Op):
        return _dataclass_dict(op)

    d: ExplainDict = {
        "name": op.name,
        "input_proj": type(op.input_proj).__name__,
        "output": type(op.output).__name__,
        "handler_template": type(op.handler_template).__name__,
    }
    if op.effects:
        d["effects"] = [_effect_dict(e) for e in op.effects]
    if op.capabilities:
        d["capabilities"] = [_dataclass_dict(c) for c in op.capabilities]
    return d


# =============================================================================
# Human-Readable Layer
# =============================================================================


def explain_opspec(spec: OpSpec) -> str:
    """Human-readable explanation of a single OpSpec."""
    trigger_str = _trigger_short(spec.trigger)
    fields_str = ", ".join(spec.input_fields.keys()) if spec.input_fields else "(none)"
    resp_str = type(spec.response_spec).__name__

    line = f"{spec.name}: {fields_str} -> {resp_str} [{trigger_str}]"

    parts: list[str] = [line]
    if spec.effects:
        effects_str = ", ".join(_effect_repr(e) for e in spec.effects)
        parts.append(f"  effects: {effects_str}")
    if spec.capabilities:
        caps_str = ", ".join(_dataclass_repr(c) for c in spec.capabilities)
        parts.append(f"  caps: {caps_str}")

    return "\n".join(parts)


def explain_derivation(
    steps: Derivation,
    handlers: Mapping[type, DeriveExplainHandler] | None = None,
) -> str:
    """Human-readable explanation of a derivation (tuple of steps)."""
    lines: list[str] = [f"Derivation ({len(steps)} steps):"]

    for i, step in enumerate(steps, 1):
        d = step_dict(step, handlers)
        _step_type = d.get("type", "?")
        detail = _format_step_short(d)
        lines.append(f"  {i}. {detail}")

    return "\n".join(lines)


def explain_entity(
    entity: type,
    handlers: Mapping[type, DeriveExplainHandler] | None = None,
) -> str:
    """Human-readable explanation of a @derive-decorated entity.

    Shows patterns, steps, and accumulated OpSpecs.

    Example:
        print(explain_entity(User))
        # === User Derivation ===
        #   1 pattern
        #   Pattern #1: Dialect (6 ops, HTTPTriggers)
        #     Steps (10): ...
        #     OpSpecs (5): ...
    """
    data = entity_derivation_dict(entity, handlers)
    return _format_entity(data)


# =============================================================================
# Formatters (dict -> str)
# =============================================================================


def _dataclass_repr(obj: object) -> str:
    """Dataclass -> short repr string."""
    name = type(obj).__name__
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        fields = dataclasses.fields(obj)
        if not fields:
            return name
        parts: list[str] = []
        for f in fields:
            val = getattr(obj, f.name)
            if isinstance(val, type):
                parts.append(f"{f.name}={val.__name__}")
            else:
                parts.append(f"{f.name}={val!r}")
        return f"{name}({', '.join(parts)})"
    return name


def _format_step_short(d: ExplainDict) -> str:
    """Format a single step dict as a short line."""
    step_type = _str(d.get("type", "?"))

    if step_type == "DeriveOp":
        name = _str(d.get("name", "?"))
        trigger = _dict(d.get("trigger", {}))
        trigger_str = _trigger_short_from_dict(trigger)
        line = f'DeriveOp "{name}" -> {trigger_str}'

        # Input/output on next line
        _proj = d.get("input_proj", "?")
        _output = d.get("output", "?")
        extras: list[str] = []

        # Effects
        effects = _dicts(d.get("effects", []))
        if effects:
            effect_strs = [_format_effect_short(e) for e in effects]
            extras.append(f"effects: {', '.join(effect_strs)}")

        if extras:
            line += "\n       " + "; ".join(extras)
        return line

    if step_type == "BindProvider":
        node = d.get("node", "?")
        return f"BindProvider(node={node})"

    if step_type == "ExcludeSchemaFields":
        names_val = d.get("names", [])
        name_strs = [_str(n) for n in names_val] if isinstance(names_val, list) else []
        return f"ExcludeSchemaFields({', '.join(name_strs)})"

    if step_type == "RequireFields":
        names_val = d.get("names", [])
        name_strs = [_str(n) for n in names_val] if isinstance(names_val, list) else []
        return f"RequireFields({', '.join(name_strs)})"

    if step_type == "ExposeMethod":
        service = _str(d.get("service", "?"))
        method_name = _str(d.get("method", "?"))
        trigger = _dict(d.get("trigger", {}))
        trigger_str = _trigger_short_from_dict(trigger)
        line = f"ExposeMethod {service}.{method_name} -> {trigger_str}"
        caps = _dicts(d.get("capabilities", []))
        if caps:
            cap_strs = [_str(c.get("type", "?")) for c in caps]
            line += f"\n       caps: {', '.join(cap_strs)}"
        return line

    if step_type == "ExposeOp":
        op_type = d.get("op_type", "?")
        trigger = _dict(d.get("trigger", {}))
        trigger_str = _trigger_short_from_dict(trigger)
        return f"ExposeOp({op_type}) -> {trigger_str}"

    if step_type == "AddGlobalCap":
        cap = d.get("cap", {})
        cap_type = cap.get("type", "?") if isinstance(cap, dict) else "?"
        return f"AddGlobalCap({cap_type})"

    # Simple steps (InspectEntity, RequireIdentity, SetBaseQuery, etc.)
    return step_type


def _trigger_short_from_dict(d: ExplainDict) -> str:
    """Trigger dict -> short label."""
    t = _str(d.get("type", "?"))
    if t == "HTTPRouteTrigger":
        return f"{_str(d.get('method', '?'))} {_str(d.get('path', '?'))}"
    if t == "CLITrigger":
        return f"{_str(d.get('command', '?'))} (cli)"
    return t


def _format_effect_short(d: ExplainDict) -> str:
    """Effect dict -> short string."""
    name = _str(d.get("type", "?"))
    fields = {k: v for k, v in d.items() if k != "type"}
    if not fields:
        return name
    # Only show non-default values (heuristic: skip 0, "", False, empty)
    non_default = {k: v for k, v in fields.items() if v not in (0, "", False, (), [])}
    if not non_default:
        return name
    parts = ", ".join(str(v) for v in non_default.values())
    return f"{name}({parts})"


def _format_entity(data: ExplainDict) -> str:
    """Format entity_derivation_dict as human-readable string."""
    entity_name = _str(data.get("entity", "?"))
    pattern_count = _int(data.get("pattern_count", 0))
    patterns = _dicts(data.get("patterns", []))

    p_word = "pattern" if pattern_count == 1 else "patterns"
    lines: list[str] = [
        f"=== {entity_name} Derivation ===",
        f"  {pattern_count} {p_word}",
    ]

    for i, pat in enumerate(patterns, 1):
        lines.append("")
        pat_type = _str(pat.get("pattern_type", "?"))
        step_count = _int(pat.get("step_count", 0))
        provider = pat.get("provider_node")

        header_parts = [f"Pattern #{i}: {pat_type}"]
        if provider:
            header_parts.append(f"provider={provider}")
        lines.append(f"  {', '.join(header_parts)}")

        # Steps
        steps = _dicts(pat.get("steps", []))
        lines.append(f"    Steps ({step_count}):")
        for j, step_d in enumerate(steps, 1):
            detail = _format_step_short(step_d)
            # Indent multi-line details
            detail_lines = detail.split("\n")
            lines.append(f"      {j}. {detail_lines[0]}")
            for extra_line in detail_lines[1:]:
                lines.append(f"         {extra_line}")

        # OpSpecs
        specs = _dicts(pat.get("specs", []))
        if specs:
            lines.append(f"    OpSpecs ({len(specs)}):")
            for spec_d in specs:
                spec_name = _str(spec_d.get("name", "?"))
                entity_n = _str(spec_d.get("entity_name", "?"))
                trigger = _dict(spec_d.get("trigger", {}))
                trigger_str = _trigger_short_from_dict(trigger)
                _resp = spec_d.get("response_spec", "?")
                lines.append(
                    f"      {spec_name}: "
                    f"{spec_name}{entity_n}Request -> {spec_name}{entity_n}Response "
                    f"[{trigger_str}]"
                )

        # Direct operations
        direct_ops = pat.get("direct_operations")
        if direct_ops:
            lines.append(f"    Direct operations: {direct_ops}")

    # Direct exposures / transforms (from @derive decorator)
    direct_exposures = data.get("direct_exposures")
    if direct_exposures:
        lines.append(f"\n  Direct exposures: {direct_exposures}")

    transforms = data.get("transforms")
    if transforms:
        lines.append(f"  Transforms: {transforms}")

    return "\n".join(lines)


# =============================================================================
# Full Trace — schema → derivation → materialized surface
# =============================================================================


def _schema_summary_dict(entity: type) -> ExplainDict:
    """Schema layer summary for full trace.

    Uses SchemaCtx (same as fold_derive pass 1) for fields + identity.
    Reads schema_meta for entity-level capabilities (SoftDelete, Timestamps, etc.).
    """
    from emergent.wire.axis.schema._universal import get_schema_meta

    from derivelib._ctx import SchemaCtx

    ctx = SchemaCtx.from_entity(entity)

    field_list: list[ExplainValue] = []
    for name, info in ctx.fields.items():
        fd: ExplainDict = {
            "name": name,
            "type": info.base_type.__name__ if isinstance(info.base_type, type) else str(info.base_type),
        }
        if name in ctx.identity_fields:
            fd["identity"] = True
        if info.is_optional:
            fd["optional"] = True
        if info.has_default:
            fd["has_default"] = True
        caps = info.universal
        if caps:
            fd["capabilities"] = [type(c).__name__ for c in caps]
        field_list.append(fd)

    d: ExplainDict = {
        "field_count": len(ctx.fields),
        "identity_count": len(ctx.identity_fields),
        "fields": field_list,
    }

    meta_caps = get_schema_meta(entity)
    if meta_caps:
        d["meta"] = [_dataclass_dict(m) for m in meta_caps]

    return d


def _endpoint_summary_dict(endpoint: object) -> ExplainDict:
    """Endpoint layer summary for full trace.

    Shows each exposure: trigger, request/response types (from RRC codec),
    and capability type names.
    """
    from emergent.wire.axis.surface import Endpoint as WireEndpoint
    from emergent.wire.axis.surface.codecs.rrc import RequestResponseCodec

    if not isinstance(endpoint, WireEndpoint):
        return {"exposure_count": 0, "exposures": []}

    exposure_list: list[ExplainValue] = []
    for exp in endpoint.exposures:
        ed: ExplainDict = {
            "trigger": _trigger_dict(exp.trigger),
        }
        codec = exp.codec
        if isinstance(codec, RequestResponseCodec):
            ed["request"] = codec.request.__name__
            ed["response"] = codec.response.__name__
        else:
            ed["codec"] = type(codec).__name__
        if exp.capabilities:
            ed["capabilities"] = [type(c).__name__ for c in exp.capabilities]
        exposure_list.append(ed)

    return {
        "exposure_count": len(endpoint.exposures),
        "exposures": exposure_list,
    }


def full_entity_dict(
    entity: type,
    handlers: Mapping[type, DeriveExplainHandler] | None = None,
) -> ExplainDict:
    """Full trace: schema → derivation → materialized surface.

    Three layers:
    1. Schema: entity fields, identity, universal capabilities, schema_meta
    2. Derivation: patterns, steps, OpSpecs, direct operations (same fold as entity_derivation_dict)
    3. Surface: materialized endpoints with triggers, request/response types, capabilities

    Single fold per pattern — derivation info and surface topology extracted from the same fold_derive + materialize pass.

    Args:
        entity: Entity class decorated with @derive
        handlers: Custom step handlers (default: DERIVE_EXPLAIN)

    Example::

        data = full_entity_dict(User)
        data["schema"]["field_count"]                # 3
        data["derivation"]["pattern_count"]          # 1
        data["surface"]["endpoint_count"]            # 1
        data["surface"]["endpoints"][0]["exposures"] # exposure dicts
    """
    patterns = get_patterns(entity)
    direct_exposures = get_exposures(entity)
    entity_cls: type[object] = entity

    # 1. Schema layer
    schema_data = _schema_summary_dict(entity)

    # 2 + 3. Derivation + Surface (fold once, materialize)
    pattern_dicts: list[ExplainValue] = []
    endpoint_dicts: list[ExplainValue] = []

    for pattern in patterns:
        steps = pattern.compile(entity)
        ctx = fold_derive(steps, entity_cls)
        surface = ctx.surface

        # Derivation info
        pat_d: ExplainDict = {
            "pattern_type": type(pattern).__name__,
            "step_count": len(steps),
            "steps": [step_dict(s, handlers) for s in steps],
            "specs": [opspec_dict(s) for s in surface.specs],
        }
        if surface.operations:
            pat_d["direct_operations"] = len(surface.operations)
        if ctx.query.provider_node is not None:
            pat_d["provider_node"] = ctx.query.provider_node.__name__
        pattern_dicts.append(pat_d)

        # Surface info (materialize and explain)
        endpoint = materialize(ctx)
        endpoint_dicts.append(_endpoint_summary_dict(endpoint))

    # Direct exposures (from @derive(exposure_obj))
    if direct_exposures:
        from emergent.wire.axis.surface import Endpoint as WireEndpoint, empty_runner

        ep = WireEndpoint(runner=empty_runner(), exposures=list(direct_exposures))
        endpoint_dicts.append(_endpoint_summary_dict(ep))

    return {
        "entity": entity.__name__,
        "schema": schema_data,
        "derivation": {
            "pattern_count": len(patterns),
            "patterns": pattern_dicts,
        },
        "surface": {
            "endpoint_count": len(endpoint_dicts),
            "endpoints": endpoint_dicts,
        },
    }


def explain_full(
    *entities: type,
    handlers: Mapping[type, DeriveExplainHandler] | None = None,
) -> str:
    """Human-readable full trace: schema → derivation → materialized surface.

    Shows three layers per entity:
    1. Schema — fields, identity, capabilities
    2. Derivation — patterns, step chain, ops/direct operations
    3. Surface — final exposure topology (trigger + request/response + caps)

    Example::

        print(explain_full(User))
        # === User (full trace) ===
        #
        #   Schema: 3 fields (1 identity)
        #     id (int) [Identity]
        #     name (str)
        #     email (str) [Unique]
        #
        #   Derivation: 1 pattern
        #     Pattern #1: Dialect (11 steps), provider=Users
        #       steps: InspectEntity → RequireIdentity → BindProvider → ...
        #       ops: List, Get, Create, Update, Patch, Delete
        #
        #   Surface: 6 exposures across 1 endpoint
        #     GET /api/users [ListUserRequest → ListUserResponse]
        #     GET /api/users/{id} [GetUserRequest → GetUserResponse]
        #     ...
    """
    parts: list[str] = []
    for entity in entities:
        data = full_entity_dict(entity, handlers)
        parts.append(_format_full(data))
    return "\n\n".join(parts)


# =============================================================================
# Full Trace Formatter (dict → str)
# =============================================================================


def _format_full(data: ExplainDict) -> str:
    """Format full_entity_dict as human-readable string."""
    entity_name = _str(data.get("entity", "?"))
    lines: list[str] = [f"=== {entity_name} (full trace) ==="]

    # --- Schema ---
    schema = _dict(data.get("schema", {}))
    field_count = _int(schema.get("field_count", 0))
    id_count = _int(schema.get("identity_count", 0))
    lines.append("")
    lines.append(f"  Schema: {field_count} fields ({id_count} identity)")

    for fd in _dicts(schema.get("fields", [])):
        name = _str(fd.get("name", "?"))
        type_name = _str(fd.get("type", "?"))
        markers: list[str] = []
        if fd.get("identity"):
            markers.append("Identity")
        if fd.get("optional"):
            markers.append("optional")
        caps_val = fd.get("capabilities")
        if isinstance(caps_val, list):
            for c in caps_val:
                cap_name = _str(c)
                if cap_name != "Identity":
                    markers.append(cap_name)
        suffix = f" [{', '.join(markers)}]" if markers else ""
        lines.append(f"    {name} ({type_name}){suffix}")

    meta = _dicts(schema.get("meta", []))
    if meta:
        meta_strs = [_str(m.get("type", "?")) for m in meta]
        lines.append(f"    meta: {', '.join(meta_strs)}")

    # --- Derivation ---
    derivation = _dict(data.get("derivation", {}))
    pattern_count = _int(derivation.get("pattern_count", 0))
    patterns = _dicts(derivation.get("patterns", []))

    lines.append("")
    p_word = "pattern" if pattern_count == 1 else "patterns"
    lines.append(f"  Derivation: {pattern_count} {p_word}")

    for i, pat in enumerate(patterns, 1):
        pat_type = _str(pat.get("pattern_type", "?"))
        step_count = _int(pat.get("step_count", 0))
        provider = pat.get("provider_node")

        header = f"    Pattern #{i}: {pat_type} ({step_count} steps)"
        if provider:
            header += f", provider={_str(provider)}"
        lines.append(header)

        # Step chain (compact: type names joined with →)
        steps = _dicts(pat.get("steps", []))
        step_names: list[str] = []
        for s in steps:
            stype = _str(s.get("type", "?"))
            if stype == "DeriveOp":
                step_names.append(f'DeriveOp("{_str(s.get("name", "?"))}")')
            elif stype == "ExposeMethod":
                step_names.append(f'{_str(s.get("service", "?"))}.{_str(s.get("method", "?"))}')
            else:
                step_names.append(stype)
        lines.append(f"      steps: {' → '.join(step_names)}")

        # OpSpecs (compact)
        specs = _dicts(pat.get("specs", []))
        if specs:
            spec_names = [_str(s.get("name", "?")) for s in specs]
            lines.append(f"      ops: {', '.join(spec_names)}")

        direct_ops = pat.get("direct_operations")
        if direct_ops:
            lines.append(f"      direct operations: {direct_ops}")

    # --- Surface ---
    surface = _dict(data.get("surface", {}))
    endpoints = _dicts(surface.get("endpoints", []))

    total_exposures = sum(_int(ep.get("exposure_count", 0)) for ep in endpoints)
    ep_count = len(endpoints)
    lines.append("")
    ep_word = "endpoint" if ep_count == 1 else "endpoints"
    lines.append(f"  Surface: {total_exposures} exposures across {ep_count} {ep_word}")

    for ep in endpoints:
        for exp_d in _dicts(ep.get("exposures", [])):
            trigger = _dict(exp_d.get("trigger", {}))
            trigger_str = _trigger_short_from_dict(trigger)

            req = exp_d.get("request")
            resp = exp_d.get("response")
            if req and resp:
                codec_info = f" [{_str(req)} → {_str(resp)}]"
            elif exp_d.get("codec"):
                codec_info = f" [{_str(exp_d.get('codec'))}]"
            else:
                codec_info = ""

            caps_val = exp_d.get("capabilities")
            caps_str = ""
            if isinstance(caps_val, list) and caps_val:
                cap_names = [_str(c) for c in caps_val]
                caps_str = f"\n      caps: {', '.join(cap_names)}"

            lines.append(f"    {trigger_str}{codec_info}{caps_str}")

    return "\n".join(lines)


__all__ = (
    # Types
    "DeriveExplainHandler",
    # Pre-built handlers
    "DERIVE_EXPLAIN",
    # Dict layer
    "opspec_dict",
    "step_dict",
    "derivation_dict",
    "entity_derivation_dict",
    "dialect_dict",
    # Full trace
    "full_entity_dict",
    # Human-readable layer
    "explain_opspec",
    "explain_derivation",
    "explain_entity",
    "explain_full",
)

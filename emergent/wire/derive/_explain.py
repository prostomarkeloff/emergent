"""Explain — self-description of derive pipelines.

DeriveCtx is self-describing: specs, operations, capabilities are all
inspectable frozen data. No traversal of Step tuples needed.

    from emergent.wire.derive._explain import explain_derive, derive_dict

    ctx = compile_derive(User)
    data = derive_dict(ctx)   # -> dict
    text = explain_derive(ctx) # -> str
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

from emergent.wire.axis.surface.triggers.cli import CLITrigger
from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger

if TYPE_CHECKING:
    from emergent.wire.derive._ctx import DeriveCtx
    from emergent.wire.derive._opspec import OpSpec

type ExplainValue = str | int | float | bool | None | list[ExplainValue] | dict[str, ExplainValue]
type ExplainDict = dict[str, ExplainValue]


# ═══════════════════════════════════════════════════════════════════════════════
# Dict layer
# ═══════════════════════════════════════════════════════════════════════════════


def trigger_dict(trigger: object) -> ExplainDict:
    """Trigger -> explain dict."""
    if isinstance(trigger, HTTPRouteTrigger):
        return {"type": "http", "method": trigger.method, "path": trigger.path}
    if isinstance(trigger, CLITrigger):
        return {"type": "cli", "command": trigger.command}
    return {"type": type(trigger).__name__}


def effect_dict(effect: object) -> ExplainDict:
    """Effect -> explain dict."""
    d: ExplainDict = {"type": type(effect).__name__}
    if dataclasses.is_dataclass(effect):
        for f in dataclasses.fields(effect):
            val = getattr(effect, f.name)
            if isinstance(val, str | int | float | bool | None):
                d[f.name] = val
    return d


def capability_dict(cap: object) -> ExplainDict:
    """Capability -> explain dict."""
    d: ExplainDict = {"type": type(cap).__name__}
    if dataclasses.is_dataclass(cap):
        for f in dataclasses.fields(cap):
            val = getattr(cap, f.name)
            if isinstance(val, str | int | float | bool | None):
                d[f.name] = val
    return d


def _handler_info(template: object) -> ExplainValue:
    """Handler template -> explain value (str or dict with steps)."""
    from emergent.wire.derive._handler import WrappedTemplate
    from emergent.wire.derive._pipeline import Pipeline

    if isinstance(template, Pipeline):
        return {
            "type": "Pipeline",
            "steps": [type(s).__name__ for s in template.steps],
        }
    if isinstance(template, WrappedTemplate):
        return {
            "type": "WrappedTemplate",
            "inner": _handler_info(template.inner),
        }
    return type(template).__name__


def spec_dict(spec: OpSpec) -> ExplainDict:
    """OpSpec -> explain dict."""
    return {
        "name": spec.name,
        "entity": spec.entity_name,
        "input_fields": list(spec.input_fields.keys()),
        "trigger": trigger_dict(spec.trigger),
        "effects": [effect_dict(e) for e in spec.effects],
        "capabilities": [capability_dict(c) for c in spec.capabilities],
        "handler": _handler_info(spec.handler_template),
        "response": type(spec.response_spec).__name__,
    }


def derive_dict(ctx: DeriveCtx) -> ExplainDict:
    """DeriveCtx -> full explain dict."""
    return {
        "entity": ctx.entity.__name__,
        "fields": list(ctx.fields.keys()),
        "identity_fields": list(ctx.identity_fields.keys()),
        "provider_node": (
            ctx.provider_node.__name__ if ctx.provider_node is not None else None
        ),
        "has_base_query": ctx.base_query is not None,
        "specs": [spec_dict(s) for s in ctx.specs],
        "operations_count": len(ctx.operations),
        "global_capabilities": [capability_dict(c) for c in ctx.capabilities],
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Human-readable layer
# ═══════════════════════════════════════════════════════════════════════════════


def _trigger_short(trigger: object) -> str:
    if isinstance(trigger, HTTPRouteTrigger):
        return f"{trigger.method} {trigger.path}"
    if isinstance(trigger, CLITrigger):
        return f"CLI {trigger.command}"
    return type(trigger).__name__


def _effects_short(effects: tuple[object, ...]) -> str:
    if not effects:
        return ""
    names = [type(e).__name__ for e in effects]
    return f" [{', '.join(names)}]"


def explain_spec(spec: OpSpec) -> str:
    """OpSpec -> one-line summary."""
    trigger = _trigger_short(spec.trigger)
    effects = _effects_short(spec.effects)
    fields_str = ", ".join(spec.input_fields.keys())
    return f"  {spec.name}: {trigger}{effects} ({fields_str})"


def explain_derive(ctx: DeriveCtx) -> str:
    """DeriveCtx -> human-readable multi-line summary."""
    lines: list[str] = []
    lines.append(f"Entity: {ctx.entity.__name__}")
    lines.append(f"  Fields: {', '.join(ctx.fields.keys())}")
    if ctx.identity_fields:
        lines.append(f"  Identity: {', '.join(ctx.identity_fields.keys())}")
    if ctx.provider_node:
        lines.append(f"  Provider: {ctx.provider_node.__name__}")
    if ctx.base_query is not None:
        lines.append("  Query: relational")

    if ctx.specs:
        lines.append(f"Operations ({len(ctx.specs)} specs):")
        for s in ctx.specs:
            lines.append(explain_spec(s))

    if ctx.operations:
        lines.append(f"Direct operations: {len(ctx.operations)}")
        for op_type, _handler, exposure_obj in ctx.operations:
            trigger = _trigger_short(exposure_obj.trigger)
            lines.append(f"  {op_type.__name__}: {trigger}")

    if ctx.capabilities:
        cap_names = [type(c).__name__ for c in ctx.capabilities]
        lines.append(f"Global capabilities: {', '.join(cap_names)}")

    return "\n".join(lines)


def explain_entity(entity: type) -> str:
    """Compile and explain an entity."""
    from emergent.wire.derive._compile import compile_derive

    ctxs = compile_derive(entity)
    return "\n\n".join(explain_derive(ctx) for ctx in ctxs)


__all__ = (
    "ExplainDict",
    "ExplainValue",
    "derive_dict",
    "explain_derive",
    "explain_entity",
    "explain_spec",
    "spec_dict",
    "trigger_dict",
)

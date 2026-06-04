"""Explain API — self-description of compilation.

Two layers:
  1. Dict-returning: trace_dict(), field_dict() — structured data for tools/analysis
  2. Human-readable: explain(), explain_field() — formats from dicts

    from emergent.wire.compile import Axes, trace_dict, explain

    axes = Axes.traced()
    Model = to_pydantic(User, axes)

    data = trace_dict(axes)     # -> dict
    text = explain(axes)        # -> str (formats from trace_dict)

## Open-world tracing

Tracing is automatic for any compiler that uses compile_fields() or
scan_and_wrap() — both read axes.trace. Custom compilers get tracing
for free. No trace kwarg threading needed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from emergent.wire.compile._core import Axes
    from emergent.wire.compile._trace import (
        FieldPhaseTrace,
        FieldTrace,
        FoldStep,
        FoldTrace,
        ListCollector,
        ScanEvent,
        TypeTrace,
        WrapEvent,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# TypedDict shapes for the structured trace
# ═══════════════════════════════════════════════════════════════════════════════


class StepDict(TypedDict):
    capability: str
    dispatch: str
    changed: bool


class FoldTraceDict(TypedDict):
    protocol: str
    method: str
    items_total: int
    items_applied: int
    steps: list[StepDict]


class PhaseTraceDict(TypedDict):
    phase: str
    fold: FoldTraceDict


class FieldTraceDict(TypedDict):
    field: str
    type: str
    capabilities: list[str]
    phases: list[PhaseTraceDict]


# "class" is a Python reserved word — functional TypedDict syntax handles it.
TypeTraceDict = TypedDict(
    "TypeTraceDict",
    {"class": str, "fields": list[FieldTraceDict]},
)


class ScanDict(TypedDict):
    trigger_type: str
    trigger: str
    codec: str
    capabilities: list[str]


class WrapDict(TypedDict):
    codec: str
    trigger: str
    result: str


class TraceDict(TypedDict):
    types: list[TypeTraceDict]
    scan: list[ScanDict]
    wrap: list[WrapDict]


# ═══════════════════════════════════════════════════════════════════════════════
# Collector extraction
# ═══════════════════════════════════════════════════════════════════════════════


def _get_collector(axes: Axes) -> ListCollector | None:
    from emergent.wire.compile._trace import ListCollector

    if axes.trace is not None and isinstance(axes.trace, ListCollector):
        return axes.trace
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# Dict-returning layer — structured data
# ═══════════════════════════════════════════════════════════════════════════════


def trace_dict(axes: Axes) -> TraceDict:
    """Full compilation trace as structured dict.

        data = trace_dict(axes)
        data["types"]        # list of type traces
        data["scan"]         # list of scan events
        data["wrap"]         # list of wrap events
    """
    collector = _get_collector(axes)
    if collector is None:
        return TraceDict(types=[], scan=[], wrap=[])

    return TraceDict(
        types=[_type_trace_dict(tt) for tt in collector.type_traces],
        scan=[_scan_dict(se) for se in collector.scan_events],
        wrap=[_wrap_dict(we) for we in collector.wrap_events],
    )


def field_dict(axes: Axes, field_name: str) -> FieldTraceDict | None:
    """One field's compilation trace as dict.

        d = field_dict(axes, "email")
        d["capabilities"]     # ["MaxLen", "Unique", "Description"]
        d["phases"]           # list of phase dicts
    """
    ft = get_field_trace(axes, field_name)
    if ft is None:
        return None
    return _field_trace_dict(ft)


def type_dict(axes: Axes, cls_name: str) -> TypeTraceDict | None:
    """One type's compilation trace as dict."""
    collector = _get_collector(axes)
    if collector is None:
        return None
    for tt in collector.type_traces:
        if tt.cls_name == cls_name:
            return _type_trace_dict(tt)
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# Dict converters (trace events → plain dicts)
# ═══════════════════════════════════════════════════════════════════════════════


def _step_dict(step: FoldStep) -> StepDict:
    return StepDict(
        capability=step.item_type,
        dispatch=step.dispatch,
        changed=step.changed,
    )


def _fold_trace_dict(ft: FoldTrace) -> FoldTraceDict:
    return FoldTraceDict(
        protocol=ft.protocol,
        method=ft.method,
        items_total=ft.items_total,
        items_applied=ft.items_applied,
        steps=[_step_dict(s) for s in ft.steps],
    )


def _phase_trace_dict(fpt: FieldPhaseTrace) -> PhaseTraceDict:
    return PhaseTraceDict(
        phase=fpt.phase,
        fold=_fold_trace_dict(fpt.fold),
    )


def _field_trace_dict(ft: FieldTrace) -> FieldTraceDict:
    return FieldTraceDict(
        field=ft.field_name,
        type=ft.field_type,
        capabilities=list(ft.capabilities),
        phases=[_phase_trace_dict(p) for p in ft.phases],
    )


def _type_trace_dict(tt: TypeTrace) -> TypeTraceDict:
    return TypeTraceDict(
        {"class": tt.cls_name, "fields": [_field_trace_dict(f) for f in tt.fields]},
    )


def _scan_dict(se: ScanEvent) -> ScanDict:
    return ScanDict(
        trigger_type=se.trigger_type,
        trigger=se.trigger_repr,
        codec=se.codec_type,
        capabilities=list(se.capabilities),
    )


def _wrap_dict(we: WrapEvent) -> WrapDict:
    return WrapDict(
        codec=we.codec_type,
        trigger=we.trigger_repr,
        result=we.result_type,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Human-readable layer — formats from dicts
# ═══════════════════════════════════════════════════════════════════════════════


def explain(axes: Axes) -> str:
    """Human-readable compilation trace. Formats from trace_dict().

        axes = Axes.traced()
        Model = to_pydantic(User, axes)
        print(explain(axes))
    """
    data = trace_dict(axes)
    if not data["types"] and not data["scan"] and not data["wrap"]:
        return "(tracing not enabled -- use Axes.traced())"
    return _format_trace(data)


def explain_field(axes: Axes, field_name: str) -> str:
    """Human-readable trace of one field. Formats from field_dict()."""
    d = field_dict(axes, field_name)
    if d is None:
        return f"(field '{field_name}' not found in trace)"
    return _format_field(d)


def explain_type(axes: Axes, cls_name: str) -> str:
    """Human-readable trace of one type. Formats from type_dict()."""
    d = type_dict(axes, cls_name)
    if d is None:
        return f"(type '{cls_name}' not found in trace)"
    return _format_type(d)


# ═══════════════════════════════════════════════════════════════════════════════
# Structured query (raw trace events)
# ═══════════════════════════════════════════════════════════════════════════════


def get_field_trace(axes: Axes, field_name: str) -> FieldTrace | None:
    """Get raw FieldTrace for programmatic inspection."""
    collector = _get_collector(axes)
    if collector is None:
        return None
    for ft in collector.field_traces:
        if ft.field_name == field_name:
            return ft
    return None


def get_phase_trace(
    axes: Axes, field_name: str, phase: str
) -> FieldPhaseTrace | None:
    """Get raw phase trace for a specific field and phase."""
    ft = get_field_trace(axes, field_name)
    if ft is None:
        return None
    for fpt in ft.phases:
        if fpt.phase == phase:
            return fpt
    return None


def changed_fields(axes: Axes, phase: str) -> list[str]:
    """Field names where at least one capability changed context in the given phase."""
    collector = _get_collector(axes)
    if collector is None:
        return []
    result: list[str] = []
    for ft in collector.field_traces:
        for fpt in ft.phases:
            if fpt.phase == phase and any(s.changed for s in fpt.fold.steps):
                result.append(ft.field_name)
                break
    return result


def active_capabilities(axes: Axes, field_name: str) -> list[str]:
    """Capability type names that actually changed context for a field (any phase)."""
    ft = get_field_trace(axes, field_name)
    if ft is None:
        return []
    seen: set[str] = set()
    result: list[str] = []
    for fpt in ft.phases:
        for step in fpt.fold.steps:
            if step.changed and step.item_type not in seen:
                seen.add(step.item_type)
                result.append(step.item_type)
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# Formatters (dict → str)
# ═══════════════════════════════════════════════════════════════════════════════


def _format_trace(data: TraceDict) -> str:
    lines: list[str] = []
    for td in data["types"]:
        lines.append(_format_type(td))

    scan = data["scan"]
    if scan:
        lines.append("")
        lines.append("=== Scan ===")
        for s in scan:
            caps = f"  [{len(s['capabilities'])} caps]" if s["capabilities"] else ""
            lines.append(f"  {s['trigger']} -> {s['codec']}{caps}")

    wrap = data["wrap"]
    if wrap:
        lines.append("")
        lines.append("=== Wrap ===")
        for w in wrap:
            lines.append(f"  {w['codec']} -> {w['result']}  ({w['trigger']})")

    return "\n".join(lines)


def _format_type(td: TypeTraceDict) -> str:
    lines = [f"=== {td['class']} ==="]
    for fd in td["fields"]:
        lines.append(_format_field(fd))
    return "\n".join(lines)


def _format_field(fd: FieldTraceDict) -> str:
    lines: list[str] = []
    lines.append(f"  {fd['field']} ({fd['type']}):")
    caps = fd["capabilities"]
    if caps:
        lines.append(f"    [{', '.join(caps)}]")
    for pd in fd["phases"]:
        parts: list[str] = []
        for step in pd["fold"]["steps"]:
            cap = step["capability"]
            if step["dispatch"] == "skipped":
                parts.append(f"{cap} (skipped)")
            elif step["changed"]:
                parts.append(f"{cap} ({step['dispatch']}) [changed]")
            else:
                parts.append(f"{cap} ({step['dispatch']})")
        if parts:
            lines.append(f"    {pd['phase']}: {' | '.join(parts)}")
    return "\n".join(lines)


__all__ = (
    # TypedDicts (for consumers wanting typed access)
    "TraceDict",
    "TypeTraceDict",
    "FieldTraceDict",
    "PhaseTraceDict",
    "FoldTraceDict",
    "StepDict",
    "ScanDict",
    "WrapDict",
    # Dict layer
    "trace_dict",
    "field_dict",
    "type_dict",
    # Human-readable layer
    "explain",
    "explain_field",
    "explain_type",
    # Structured query
    "get_field_trace",
    "get_phase_trace",
    "changed_fields",
    "active_capabilities",
)

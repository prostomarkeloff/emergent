"""Compilation trace — structured event model for self-describing compilation.

Zero-overhead when disabled. TraceCollector protocol + ListCollector default.
All events are frozen dataclasses — immutable, serializable, inspectable.

    from emergent.wire.compile import Axes, explain

    axes = Axes.traced()
    Model = to_pydantic(User, axes)
    print(explain(axes))

## Trace hierarchy

    TypeTrace (one per compile_fields call)
      └─ FieldTrace (one per field)
           └─ FieldPhaseTrace (one per field x phase)
                └─ FoldTrace (one fold() invocation)
                     └─ FoldStep (one capability dispatch)

## Surface events

    ScanEvent — (trigger, handler) match from scan_and_wrap
    WrapEvent — codec adapter wrapping
    CapabilityEvent — runtime capability application
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable


# ═══════════════════════════════════════════════════════════════════════════════
# Trace Events — immutable records
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class FoldStep:
    """One capability dispatch within a fold.

    Records what capability was applied, how it was dispatched,
    and the context state before/after.

    Context snapshots are the actual frozen dataclass values —
    no defensive copy needed since all contexts are immutable.
    """

    item_type: str
    dispatch: Literal["handler", "protocol", "skipped"]
    method: str
    context_before: Any
    context_after: Any
    changed: bool


@dataclass(frozen=True, slots=True)
class FoldTrace:
    """Complete trace of one fold() invocation.

    Example: folding field `email`'s capabilities through PydanticCompilable.
    """

    protocol: str
    method: str
    initial: Any
    final: Any
    steps: tuple[FoldStep, ...]
    items_total: int
    items_applied: int


@dataclass(frozen=True, slots=True)
class FieldPhaseTrace:
    """One field x one compilation phase."""

    field_name: str
    field_type: str
    phase: str  # context_type.__name__
    fold: FoldTrace


@dataclass(frozen=True, slots=True)
class FieldTrace:
    """All phases for one field."""

    field_name: str
    field_type: str
    capabilities: tuple[str, ...]
    phases: tuple[FieldPhaseTrace, ...]


@dataclass(frozen=True, slots=True)
class TypeTrace:
    """Full compile_fields() trace for one type."""

    cls_name: str
    fields: tuple[FieldTrace, ...]


@dataclass(frozen=True, slots=True)
class ScanEvent:
    """One (trigger, handler) match from scan_and_wrap."""

    trigger_type: str
    trigger_repr: str
    codec_type: str
    capabilities: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class WrapEvent:
    """One codec adapter wrapping."""

    codec_type: str
    trigger_repr: str
    result_type: str


@dataclass(frozen=True, slots=True)
class CapabilityEvent:
    """Runtime capability application (response transforms, route config, etc.)."""

    cap_type: str
    phase: Literal["response_transform", "fastapi_route", "fastapi_compile"]
    before: Any
    after: Any


# ═══════════════════════════════════════════════════════════════════════════════
# TraceCollector — protocol for event accumulation
# ═══════════════════════════════════════════════════════════════════════════════


@runtime_checkable
class TraceCollector(Protocol):
    """Protocol for accumulating trace events.

    Implementations choose their own storage strategy:
    - ListCollector: accumulates to lists (default, for explain())
    - Custom: stream to file, send to tracing backend, etc.
    """

    def fold_step(self, step: FoldStep) -> None: ...
    def fold_complete(self, trace: FoldTrace) -> None: ...
    def field_phase(self, trace: FieldPhaseTrace) -> None: ...
    def field_complete(self, trace: FieldTrace) -> None: ...
    def type_complete(self, trace: TypeTrace) -> None: ...
    def scan(self, event: ScanEvent) -> None: ...
    def wrap(self, event: WrapEvent) -> None: ...
    def capability(self, event: CapabilityEvent) -> None: ...


# ═══════════════════════════════════════════════════════════════════════════════
# ListCollector — default implementation
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class ListCollector:
    """Accumulates all events to lists. Primary implementation for explain().

    Mutable — accumulates during compilation, then queried after.
    """

    fold_steps: list[FoldStep] = field(default_factory=lambda: list[FoldStep]())
    fold_traces: list[FoldTrace] = field(default_factory=lambda: list[FoldTrace]())
    field_phases: list[FieldPhaseTrace] = field(default_factory=lambda: list[FieldPhaseTrace]())
    field_traces: list[FieldTrace] = field(default_factory=lambda: list[FieldTrace]())
    type_traces: list[TypeTrace] = field(default_factory=lambda: list[TypeTrace]())
    scan_events: list[ScanEvent] = field(default_factory=lambda: list[ScanEvent]())
    wrap_events: list[WrapEvent] = field(default_factory=lambda: list[WrapEvent]())
    capability_events: list[CapabilityEvent] = field(default_factory=lambda: list[CapabilityEvent]())

    def fold_step(self, step: FoldStep) -> None:
        self.fold_steps.append(step)

    def fold_complete(self, trace: FoldTrace) -> None:
        self.fold_traces.append(trace)

    def field_phase(self, trace: FieldPhaseTrace) -> None:
        self.field_phases.append(trace)

    def field_complete(self, trace: FieldTrace) -> None:
        self.field_traces.append(trace)

    def type_complete(self, trace: TypeTrace) -> None:
        self.type_traces.append(trace)

    def scan(self, event: ScanEvent) -> None:
        self.scan_events.append(event)

    def wrap(self, event: WrapEvent) -> None:
        self.wrap_events.append(event)

    def capability(self, event: CapabilityEvent) -> None:
        self.capability_events.append(event)


__all__ = (
    # Events
    "FoldStep",
    "FoldTrace",
    "FieldPhaseTrace",
    "FieldTrace",
    "TypeTrace",
    "ScanEvent",
    "WrapEvent",
    "CapabilityEvent",
    # Protocol + implementation
    "TraceCollector",
    "ListCollector",
)

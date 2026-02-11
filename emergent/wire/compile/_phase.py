"""Compilation phases — open-world compiler infrastructure.

CompilationPhase[Ctx] reifies the (context_type, protocol, initial) triple.
compile_fields() runs all phases in one pass.

    from emergent.wire.compile._phase import (
        CompilationPhase, FieldCompilation, compile_fields,
        PYDANTIC_PHASE, OPENAPI_PHASE, ARGPARSE_PHASE,
        REQUEST_BUILD_PHASE, TG_INPUT_PHASE, TG_RENDER_PHASE,
    )

    compiled = compile_fields(User, axes, [PYDANTIC_PHASE, OPENAPI_PHASE])
    for fc in compiled:
        pydantic_ctx = fc[PYDANTIC_PHASE]   # typed PydanticContext
        openapi_ctx = fc[OPENAPI_PHASE]     # typed OpenAPIContext

## User-defined phase (no emergent changes needed)

    @dataclass(frozen=True, slots=True)
    class GraphQLContext:
        field_name: str
        field_type: type
        graphql_type: str | None = None

    class GraphQLCompilable(Protocol):
        def compile_graphql(self, ctx: GraphQLContext) -> GraphQLContext: ...

    GRAPHQL_PHASE = CompilationPhase(
        GraphQLContext, GraphQLCompilable,
        initial=lambda n, t: GraphQLContext(n, t),
    )

    compiled = compile_fields(User, axes, [PYDANTIC_PHASE, GRAPHQL_PHASE])
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, Callable

from emergent.wire.axis._capability import (
    Capability,
    PydanticContext,
    OpenAPIContext,
    ArgparseContext,
    RequestBuildContext,
    TelegrinderInputContext,
    TelegrinderRenderContext,
    PydanticCompilable,
    OpenAPICompilable,
    ArgparseCompilable,
    RequestBuildCompilable,
    TelegrinderInputCompilable,
    TelegrinderRenderCompilable,
)
from emergent.wire.axis.schema import FieldInfo
from emergent.wire.compile._core import Axes, CapabilityHandler, fold_field, traced_fold


# ═══════════════════════════════════════════════════════════════════════════════
# CompilationPhase — one fold pass descriptor
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class CompilationPhase[Ctx]:
    """One fold pass descriptor — reified phase identity.

    Identified by context_type — no strings anywhere.
    Method name auto-derived from protocol's compile_* method.
    Immutable value. Use .with_handlers() for custom handler overrides.

    Args:
        context_type: Type of the fold context (PydanticContext, etc.)
        protocol: Protocol with exactly one compile_* method
        initial: Factory (field_name, field_type) → initial context
        handlers: Optional custom handlers keyed by capability type
    """

    context_type: type[Ctx]
    protocol: type
    initial: Callable[[str, type], Ctx]
    handlers: Mapping[type[Capability], CapabilityHandler[Ctx]] | None = None
    _method: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        for attr in vars(self.protocol):
            if attr.startswith("compile_"):
                object.__setattr__(self, "_method", attr)
                return
        raise ValueError(f"No compile_* method on {self.protocol}")

    @property
    def method(self) -> str:
        return self._method

    def with_handlers(
        self,
        handlers: Mapping[type[Capability], CapabilityHandler[Ctx]] | None,
    ) -> CompilationPhase[Ctx]:
        """Return new phase with handlers merged. Immutable."""
        if handlers is None:
            return self
        merged: dict[type[Capability], CapabilityHandler[Ctx]] = {
            **(self.handlers or {}),
            **handlers,
        }
        return replace(self, handlers=merged)


# ═══════════════════════════════════════════════════════════════════════════════
# FieldCompilation — per-field multi-phase result
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class FieldCompilation:
    """Per-field multi-phase compilation result.

    Use __getitem__ with a phase constant to get typed context:

        fc[PYDANTIC_PHASE]  → PydanticContext
        fc[OPENAPI_PHASE]   → OpenAPIContext

    Type narrowing works via isinstance + generic __getitem__.
    """

    name: str
    info: FieldInfo
    _contexts: dict[type, object]

    def __getitem__[Ctx](self, phase: CompilationPhase[Ctx]) -> Ctx:
        result = self._contexts[phase.context_type]
        if not isinstance(result, phase.context_type):
            raise TypeError(f"Expected {phase.context_type}, got {type(result)}")
        return result


# ═══════════════════════════════════════════════════════════════════════════════
# compile_fields — universal compilation kernel
# ═══════════════════════════════════════════════════════════════════════════════


def compile_fields(
    cls: type,
    axes: Axes,
    phases: Sequence[CompilationPhase[Any]],
) -> list[FieldCompilation]:
    """Universal compilation kernel — runs all phases in one pass.

    Pure function: (class, axes, phases) → list[FieldCompilation].
    Each field gets each phase's fold applied independently.
    Phases are order-independent (each fold is isolated).

    When axes.trace is set, emits FieldPhaseTrace/FieldTrace/TypeTrace events
    for self-describing compilation. Zero overhead when trace is None.

    Raises ValueError on duplicate context_type in phases.

    Example:
        compiled = compile_fields(User, axes, [PYDANTIC_PHASE, OPENAPI_PHASE])
        for fc in compiled:
            pydantic = fc[PYDANTIC_PHASE]   # PydanticContext
            openapi = fc[OPENAPI_PHASE]     # OpenAPIContext
    """
    # Check for duplicate context_types
    seen: set[type] = set()
    for phase in phases:
        if phase.context_type in seen:
            raise ValueError(f"Duplicate context_type: {phase.context_type}")
        seen.add(phase.context_type)

    fields = axes.schema(cls)
    trace = axes.trace
    result: list[FieldCompilation] = []

    field_traces: list[Any] = [] if trace is not None else []

    for name, info in fields.items():
        contexts: dict[type, object] = {}
        phase_traces: list[Any] = [] if trace is not None else []

        for phase in phases:
            ctx = phase.initial(name, info.base_type)
            if trace is not None:
                ctx, fold_trace = traced_fold(
                    info.capabilities, ctx,
                    phase.protocol, phase.method, phase.handlers,
                    trace,
                )
                from emergent.wire.compile._trace import FieldPhaseTrace

                fpt = FieldPhaseTrace(
                    field_name=name,
                    field_type=info.base_type.__qualname__,
                    phase=phase.context_type.__name__,
                    fold=fold_trace,
                )
                trace.field_phase(fpt)
                phase_traces.append(fpt)
            else:
                ctx = fold_field(info, ctx, phase.protocol, phase.method, phase.handlers)
            contexts[phase.context_type] = ctx

        result.append(FieldCompilation(name, info, contexts))

        if trace is not None:
            from emergent.wire.compile._trace import FieldTrace

            ft = FieldTrace(
                field_name=name,
                field_type=info.base_type.__qualname__,
                capabilities=tuple(type(c).__qualname__ for c in info.capabilities),
                phases=tuple(phase_traces),
            )
            trace.field_complete(ft)
            field_traces.append(ft)

    if trace is not None:
        from emergent.wire.compile._trace import TypeTrace

        trace.type_complete(TypeTrace(
            cls_name=cls.__qualname__,
            fields=tuple(field_traces),
        ))

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# Pre-built Phase Constants
# ═══════════════════════════════════════════════════════════════════════════════
#
# Named functions (not lambdas) for serialization and clarity.
# Lazy imports where needed (pydantic, openapi type mapping).


def _pydantic_initial(name: str, field_type: type) -> PydanticContext:
    from pydantic.fields import FieldInfo as PydanticFieldInfo

    return PydanticContext(name, field_type, PydanticFieldInfo())


def _openapi_initial(name: str, field_type: type) -> OpenAPIContext:
    from emergent.wire.compile._schema import _python_type_to_json_schema

    schema = _python_type_to_json_schema(field_type)
    return OpenAPIContext(name, field_type, schema=schema)


def _argparse_initial(name: str, field_type: type) -> ArgparseContext:
    return ArgparseContext(name, field_type)


def _request_build_initial(name: str, field_type: type) -> RequestBuildContext:
    return RequestBuildContext(name, field_type)


def _tg_input_initial(name: str, field_type: type) -> TelegrinderInputContext:
    return TelegrinderInputContext(name, field_type)


def _tg_render_initial(name: str, field_type: type) -> TelegrinderRenderContext:
    return TelegrinderRenderContext(name, field_type)


PYDANTIC_PHASE = CompilationPhase(PydanticContext, PydanticCompilable, _pydantic_initial)
OPENAPI_PHASE = CompilationPhase(OpenAPIContext, OpenAPICompilable, _openapi_initial)
ARGPARSE_PHASE = CompilationPhase(ArgparseContext, ArgparseCompilable, _argparse_initial)
REQUEST_BUILD_PHASE = CompilationPhase(
    RequestBuildContext, RequestBuildCompilable, _request_build_initial
)
TG_INPUT_PHASE = CompilationPhase(
    TelegrinderInputContext, TelegrinderInputCompilable, _tg_input_initial
)
TG_RENDER_PHASE = CompilationPhase(
    TelegrinderRenderContext, TelegrinderRenderCompilable, _tg_render_initial
)

# Phase groups for derivelib
FASTAPI_PHASES = (PYDANTIC_PHASE, OPENAPI_PHASE)
CLI_PHASES = (ARGPARSE_PHASE,)
TG_PHASES = (TG_INPUT_PHASE, TG_RENDER_PHASE, REQUEST_BUILD_PHASE)


__all__ = (
    # Core
    "CompilationPhase",
    "FieldCompilation",
    "compile_fields",
    # Pre-built phases
    "PYDANTIC_PHASE",
    "OPENAPI_PHASE",
    "ARGPARSE_PHASE",
    "REQUEST_BUILD_PHASE",
    "TG_INPUT_PHASE",
    "TG_RENDER_PHASE",
    # Phase groups
    "FASTAPI_PHASES",
    "CLI_PHASES",
    "TG_PHASES",
)

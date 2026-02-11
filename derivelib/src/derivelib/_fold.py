"""fold_steps — THE derivation primitive.

v4: Uses wire's generic fold(). No deps.

    from emergent.wire.compile import fold       # THE universal primitive
    from derivelib._fold import fold_steps       # alias for derivation

Two-pass orchestration via fold_derive:
  Pass 1: SCHEMA_PHASE.fold(steps, ...) → SchemaCtx
  Pass 2: QUERY_PHASE → STORAGE_PHASE → SURFACE_PHASE (sequential)

    from derivelib._fold import fold_derive, materialize, DerivationPhase

    derivation = pattern.compile(entity)
    ctx = fold_derive(derivation, entity)
    endpoint = materialize(ctx)
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from emergent.ops import ops as ops_builder
from emergent.wire.axis.surface import Endpoint, Exposure
from emergent.wire.compile._core import fold, ItemHandler

from ._ctx import (
    DerivationCtx,
    QueryCtx,
    SchemaCtx,
    StorageCtx,
    SurfaceCtx,
)
from ._derivation import Derivation, Step
from ._protocols import (
    QueryDerivable,
    SchemaDerivable,
    StorageDerivable,
    SurfaceDerivable,
)


# ═══════════════════════════════════════════════════════════════════════════════
# fold_steps — alias for wire's generic fold
# ═══════════════════════════════════════════════════════════════════════════════


type StepHandler[Ctx] = Callable[[Step, Ctx], Ctx]

# Reuse wire's generic fold directly
fold_steps = fold


# ═══════════════════════════════════════════════════════════════════════════════
# DerivationPhase — one fold pass descriptor (symmetric with CompilationPhase)
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class DerivationPhase:
    """One derivation fold pass — symmetric with CompilationPhase.

    Identified by context_type — no strings anywhere.
    Method name auto-derived from protocol's derive_* method.

    Not generic: the type safety comes from the fold() method which
    delegates to wire's fold[Ctx]() — the Ctx type is preserved
    through the initial argument, not through DerivationPhase itself.

    Handlers are passed to fold() rather than stored on the phase,
    because the handler type depends on Ctx which is only known at
    the fold call site.

    Args:
        context_type: Type of the fold context (SchemaCtx, QueryCtx, etc.)
        protocol: Protocol with exactly one derive_* method
    """

    context_type: type
    protocol: type
    _method: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        for attr in dir(self.protocol):
            if attr.startswith("derive_"):
                object.__setattr__(self, "_method", attr)
                return
        msg = f"No derive_* method on {self.protocol}"
        raise ValueError(msg)

    @property
    def method(self) -> str:
        return self._method

    def fold[Ctx](
        self,
        steps: Derivation,
        initial: Ctx,
        handlers: Mapping[type, ItemHandler[Ctx]] | None = None,
    ) -> Ctx:
        """Run fold with this phase's protocol and optional handlers."""
        return fold(steps, initial, self.protocol, self._method, handlers)


# ═══════════════════════════════════════════════════════════════════════════════
# Phase Constants
# ═══════════════════════════════════════════════════════════════════════════════

SCHEMA_PHASE = DerivationPhase(SchemaCtx, SchemaDerivable)
QUERY_PHASE = DerivationPhase(QueryCtx, QueryDerivable)
STORAGE_PHASE = DerivationPhase(StorageCtx, StorageDerivable)
SURFACE_PHASE = DerivationPhase(SurfaceCtx, SurfaceDerivable)


# ═══════════════════════════════════════════════════════════════════════════════
# fold_derive — two-pass orchestration via phases
# ═══════════════════════════════════════════════════════════════════════════════


def fold_derive[EntityT](
    steps: Derivation,
    entity: type[EntityT],
    *,
    schema_phase: DerivationPhase = SCHEMA_PHASE,
    query_phase: DerivationPhase = QUERY_PHASE,
    storage_phase: DerivationPhase = STORAGE_PHASE,
    surface_phase: DerivationPhase = SURFACE_PHASE,
) -> DerivationCtx[EntityT]:
    """Two-pass derivation fold via phases.

    Pass 1: schema (inspect entity, validate constraints)
    Pass 2: query → storage → surface (sequential, each sees prior results)

    No deps — infrastructure resolved via compose.Node at runtime.

    Args:
        steps: Ordered sequence of derivation steps
        entity: Entity type being derived
        schema_phase: Phase for schema axis (pass 1)
        query_phase: Phase for query axis (pass 2)
        storage_phase: Phase for storage axis (pass 2)
        surface_phase: Phase for surface axis (pass 2)

    Returns:
        DerivationCtx with all axes folded
    """
    # Pass 1: Schema
    schema_ctx = schema_phase.fold(steps, SchemaCtx.from_entity(entity))

    # Pass 2: Sequential — query → storage → surface
    query_ctx = query_phase.fold(steps, QueryCtx(schema=schema_ctx))
    storage_ctx = storage_phase.fold(steps, StorageCtx(schema=schema_ctx))
    surface_ctx = surface_phase.fold(
        steps,
        SurfaceCtx(schema=schema_ctx, query=query_ctx, storage=storage_ctx),
    )

    return DerivationCtx(
        schema=schema_ctx,
        query=query_ctx,
        storage=storage_ctx,
        surface=surface_ctx,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# materialize — DerivationCtx → Endpoint
# ═══════════════════════════════════════════════════════════════════════════════


def materialize[EntityT](ctx: DerivationCtx[EntityT]) -> Endpoint:
    """Convert folded DerivationCtx into wire Endpoint.

    Two paths:
    - specs: OpSpec descriptions → build_from_spec() → types + handler + exposure
    - operations: direct (OpType, handler, Exposure) tuples (from ExposeOp)

    Both paths merge into a single ops-based Runner + Exposures.
    """
    if not ctx.surface.specs and not ctx.surface.operations:
        from emergent.wire.axis.surface import empty_runner
        return Endpoint(runner=empty_runner(), exposures=[])

    from derivelib._opspec import build_from_spec

    builder = ops_builder()
    exposures: list[Exposure] = []

    # Direct operations first (fixed paths like /export before parameterized /{id})
    for op_type, handler, exposure_obj in ctx.surface.operations:
        builder = builder.on(op_type, handler)

        if ctx.surface.capabilities:
            exposure_obj = replace(
                exposure_obj,
                capabilities=(*exposure_obj.capabilities, *ctx.surface.capabilities),
            )
        exposures.append(exposure_obj)

    # Build from specs (DeriveOp path — may have parameterized paths)
    for spec in ctx.surface.specs:
        op_type, handler, exposure_obj = build_from_spec(spec, ctx.surface)

        builder = builder.on(op_type, handler)

        if ctx.surface.capabilities:
            exposure_obj = replace(
                exposure_obj,
                capabilities=(*exposure_obj.capabilities, *ctx.surface.capabilities),
            )
        exposures.append(exposure_obj)

    runner = builder.compile()
    return Endpoint(runner=runner, exposures=exposures)


__all__ = (
    "StepHandler",
    "fold_steps",
    "DerivationPhase",
    "SCHEMA_PHASE",
    "QUERY_PHASE",
    "STORAGE_PHASE",
    "SURFACE_PHASE",
    "fold_derive",
    "materialize",
)

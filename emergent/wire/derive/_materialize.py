"""materialize — DeriveCtx -> wire Endpoint.

    from emergent.wire.derive import compile_derive, materialize

    ctx = compile_derive(User)
    endpoint = materialize(ctx)

Converts DeriveCtx into a wire Endpoint with ops Runner + Exposures.
Uses build_from_spec from _opspec — no derivelib bridging needed.
"""

from __future__ import annotations

from dataclasses import replace

from emergent.ops import ops as ops_builder
from emergent.wire.axis.surface import Endpoint, Exposure, empty_runner
from emergent.wire.derive._ctx import DeriveCtx
from emergent.wire.derive._metadata import DerivedMetadata
from emergent.wire.derive._opspec import build_from_spec


def materialize[EntityT](ctx: DeriveCtx[EntityT]) -> Endpoint:
    """Convert DeriveCtx into wire Endpoint.

    Two paths:
    - specs: OpSpec descriptions -> build_from_spec() -> types + handler + exposure
    - operations: direct (OpType, handler, Exposure) tuples

    Both paths merge into a single ops-based Runner + Exposures.
    """
    if not ctx.specs and not ctx.operations:
        return Endpoint(runner=empty_runner(), exposures=())

    builder = ops_builder()
    exposures: list[Exposure] = []

    # Direct operations first (fixed paths like /export before parameterized /{id})
    for op_type, handler, exposure_obj in ctx.operations:
        builder = builder.on(op_type, handler)

        if ctx.capabilities:
            exposure_obj = replace(
                exposure_obj,
                capabilities=(*exposure_obj.capabilities, *ctx.capabilities),
            )
        exposures.append(exposure_obj)

    # Build from specs (OpSpec path)
    for spec in ctx.specs:
        op_type, handler, exposure_obj = build_from_spec(spec, ctx)

        builder = builder.on(op_type, handler)

        # Attach derivation metadata so target compilers can inspect origin
        metadata = DerivedMetadata(
            entity=ctx.entity,
            entity_name=spec.entity_name,
            spec_name=spec.name,
            source=spec.source,
            effects=spec.effects,
            identity_fields=tuple(ctx.identity_fields.keys()),
            handler_template_type=type(spec.handler_template).__name__,
        )
        exposure_obj = replace(
            exposure_obj,
            capabilities=(*exposure_obj.capabilities, metadata),
        )

        if ctx.capabilities:
            exposure_obj = replace(
                exposure_obj,
                capabilities=(*exposure_obj.capabilities, *ctx.capabilities),
            )
        exposures.append(exposure_obj)

    runner = builder.compile()
    return Endpoint(runner=runner, exposures=tuple(exposures))


__all__ = ("materialize",)

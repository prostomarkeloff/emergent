"""Op + OpSpec + build_from_spec — operation description and materialization.

Op: transport-agnostic operation descriptor (business logic).
OpSpec: pure data description of a derived operation (intermediate representation).
build_from_spec: OpSpec + DeriveCtx -> types + handler + exposure.

KEY DIFFERENCE from derivelib: build_from_spec takes DeriveCtx directly.
No SurfaceCtx bridging needed.

    from emergent.wire.derive._opspec import Op, OpSpec, build_from_spec
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from emergent.wire.axis.surface import Exposure, Trigger
from emergent.wire.axis.surface.capabilities import SurfaceCapability
from emergent.wire.axis.surface.codecs import rrc

from emergent.wire.derive._codegen import (
    AnnotationValue,
    FieldSpec,
    annotate_handler,
    create_dataclass,
    create_request_type,
    create_response_type,
)
from emergent.wire.derive._ctx import DeriveCtx, Operation, OperationHandler
from emergent.wire.derive._effects import DerivationEffect
from emergent.wire.derive._errors import DomainError
from emergent.wire.derive._handler import HandlerSpec, HandlerTemplate
from emergent.wire.derive._project import ResponseSpec, response_converter, response_fields


# ═══════════════════════════════════════════════════════════════════════════════
# Op — transport-agnostic operation descriptor
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Op:
    """Transport-agnostic operation descriptor.

    Describes WHAT an operation does (business logic),
    not WHERE it's exposed (transport).

        LIST = Op("List", no_fields(), list_response(), FetchMany(), effects=(Read(),))
        CREATE = Op("Create", non_id(), entity_response(), InsertNew(), effects=(Creates(),))
    """

    name: str
    input_proj: "FieldProjection"  # noqa: F821
    output: ResponseSpec
    handler_template: HandlerTemplate
    capabilities: tuple[SurfaceCapability, ...] = ()
    extra_op_fields: tuple[tuple[str, type], ...] = ()
    extra_request_fields: tuple[tuple[str, type], ...] = ()
    effects: tuple[DerivationEffect, ...] = ()
    codec_factory: Callable[[type, type], Exposure] | None = None
    scope_fields: tuple[str, ...] = ()


# ═══════════════════════════════════════════════════════════════════════════════
# OpSpec — pure data description of a derived operation
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class OpSpec:
    """Pure data description of a derived operation. No types generated yet.

    Inspectable, transformable, serializable. Types are built
    only when build_from_spec() is called during materialization.
    """

    name: str
    entity_name: str
    input_fields: Mapping[str, AnnotationValue]
    request_fields: Mapping[str, AnnotationValue]
    response_spec: ResponseSpec
    handler_template: HandlerTemplate
    trigger: Trigger
    capabilities: tuple[SurfaceCapability, ...] = ()
    effects: tuple[DerivationEffect, ...] = ()
    codec_factory: Callable[[type, type], Exposure] | None = None
    extra_op_fields: tuple[tuple[str, type], ...] = ()
    extra_request_fields: tuple[FieldSpec, ...] = ()
    scope_fields: tuple[str, ...] = ()
    source: str = ""


# ═══════════════════════════════════════════════════════════════════════════════
# build_from_spec — OpSpec + DeriveCtx → Operation
# ═══════════════════════════════════════════════════════════════════════════════


def build_from_spec[EntityT](spec: OpSpec, ctx: DeriveCtx[EntityT]) -> Operation[EntityT, DomainError]:
    """Build Op type, handler, and Exposure from an OpSpec.

    Takes DeriveCtx directly — no SurfaceCtx bridging needed.
    """
    # Op fields = projected input + extra (plain types for handler dispatch)
    op_field_list: list[FieldSpec] = [*spec.input_fields.items(), *spec.extra_op_fields]

    # Request fields = annotated input + extra (may include Annotated types)
    req_field_list: list[FieldSpec] = list(spec.request_fields.items()) + list(
        spec.extra_request_fields
    )

    # Create Op type
    op_type = create_dataclass(
        f"{spec.entity_name}{spec.name}Op", op_field_list, frozen=True
    )

    # Create Request type with to_domain baked in
    request_type = create_request_type(
        f"{spec.name}{spec.entity_name}Request", req_field_list, op_type
    )

    # Resolve response from DeriveCtx directly
    resp_fields = response_fields(spec.response_spec, ctx)
    converter = response_converter(spec.response_spec, ctx)

    # Create Response type with from_domain baked in
    response_type = create_response_type(
        f"{spec.name}{spec.entity_name}Response", resp_fields, converter
    )

    # Build handler spec from DeriveCtx directly
    handler_spec = HandlerSpec(
        entity=ctx.entity,
        entity_name=ctx.entity.__name__,
        identity_names=ctx.identity_names(),
        non_identity_names=tuple(ctx.non_identity_fields().keys()),
        base_query=ctx.base_query,
        scope_fields=spec.scope_fields,
        effects=spec.effects,
    )

    # Build handler from template, annotate with op_type for runner dispatch
    handler = spec.handler_template.build(handler_spec)
    annotated_handler: OperationHandler[EntityT, DomainError] = annotate_handler(handler, op_type)

    # Build exposure
    codec_fn = spec.codec_factory if spec.codec_factory is not None else rrc
    codec = codec_fn(request_type, response_type)
    exposure = Exposure(
        trigger=spec.trigger, codec=codec, capabilities=spec.capabilities
    )

    return op_type, annotated_handler, exposure


__all__ = (
    "Op",
    "OpSpec",
    "build_from_spec",
)

"""OpSpec — pure data description of a derived operation.

Steps accumulate OpSpecs. materialize() builds artifacts from them.
This separates "what to build" from "how to build it".

    from derivelib._opspec import OpSpec, build_from_spec

    # Step accumulates spec:
    spec = OpSpec(name="Get", entity_name="User", ...)
    ctx = ctx.add_spec(spec)

    # Materializer builds types from spec:
    op_type, handler, exposure = build_from_spec(spec, surface_ctx)
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from emergent.wire.axis.surface import Exposure, Trigger
from emergent.wire.axis.surface.capabilities import SurfaceCapability
from emergent.wire.axis.surface.codecs import rrc

from derivelib._codegen import (
    AnnotationValue,
    FieldSpec,
    annotate_handler,
    create_dataclass,
    create_request_type,
    create_response_type,
)
from derivelib._ctx import Operation, OperationHandler, SurfaceCtx
from derivelib._effects import DerivationEffect
from derivelib._errors import DomainError
from derivelib._project import ResponseSpec, response_converter, response_fields
from derivelib._protocols import HandlerSpec, HandlerTemplate


@dataclass(frozen=True, slots=True)
class OpSpec:
    """Pure data description of a derived operation. No types generated yet.

    Inspectable, transformable, serializable. Types are built
    only when build_from_spec() is called during materialization.
    """

    name: str
    entity_name: str
    input_fields: Mapping[str, AnnotationValue]
    request_fields: Mapping[str, AnnotationValue]  # may contain Annotated[T, *caps] type forms
    response_spec: ResponseSpec
    handler_template: HandlerTemplate
    trigger: Trigger
    capabilities: tuple[SurfaceCapability, ...] = ()
    effects: tuple[DerivationEffect, ...] = ()
    codec_factory: Callable[[type, type], Exposure] | None = None
    extra_op_fields: tuple[tuple[str, type], ...] = ()
    extra_request_fields: tuple[FieldSpec, ...] = ()


def build_from_spec[EntityT](spec: OpSpec, ctx: SurfaceCtx[EntityT]) -> Operation[EntityT, DomainError]:
    """Build Op type, handler, and Exposure from an OpSpec.

    This is the materialization step — all type generation happens here.
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

    # Create Request type with to_domain baked in (no setattr)
    request_type = create_request_type(
        f"{spec.name}{spec.entity_name}Request", req_field_list, op_type
    )

    # Resolve response via pure data accessors
    resp_fields = response_fields(spec.response_spec, ctx.schema)
    converter = response_converter(spec.response_spec, ctx.schema)

    # Create Response type with from_domain baked in (no setattr)
    response_type = create_response_type(
        f"{spec.name}{spec.entity_name}Response", resp_fields, converter
    )

    # Build handler spec — precisely what the template needs
    handler_spec = HandlerSpec(
        entity=ctx.schema.entity,
        entity_name=ctx.schema.entity.__name__,
        identity_names=ctx.schema.identity_names(),
        non_identity_names=tuple(ctx.schema.non_identity_fields().keys()),
        base_query=ctx.get_base_query(),
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
    "OpSpec",
    "build_from_spec",
)

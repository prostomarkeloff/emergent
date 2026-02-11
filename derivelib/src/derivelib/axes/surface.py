"""Surface axis steps — generic derivation primitives.

Steps implement SurfaceDerivable and run in pass 2 of fold_derive.
These are THE building blocks for derivation dialects.

Generic steps:
- DeriveOp: derive operation from entity schema + projections + templates
- ExposeOp: wire existing op/handler into exposure (no derivation)
- AddGlobalCap: add capability to all exposures

Dialect-specific steps (CRUD, game_api, etc.) compose these.
derivelib does NOT know what CRUD or HTTP is.

    from derivelib.axes.surface import DeriveOp, ExposeOp, HandlerTemplate
    from derivelib._project import id_only, entity_response

    # Generic — any dialect can use:
    DeriveOp("Get", id_only(), entity_response(), MyHandlerTemplate(), trigger)
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from emergent.wire.axis.surface import Exposure, Trigger
from emergent.wire.axis.surface.capabilities import SurfaceCapability
from emergent.wire.axis.surface.codecs import rrc

from derivelib._codegen import annotate_handler
from derivelib._ctx import OperationHandler, SurfaceCtx
from derivelib._effects import DerivationEffect
from derivelib._errors import DomainError
from derivelib._opspec import OpSpec
from derivelib._project import FieldProjection, ResponseSpec

# Import from kernel — HandlerTemplate, WrappedTemplate, wrap_template
# live in _protocols.py now (kernel concept, used across many modules)
from derivelib._protocols import HandlerTemplate, WrappedTemplate, wrap_template

if TYPE_CHECKING:
    from derivelib._dialect import Op
    from derivelib._opspec import FieldSpec


# ═══════════════════════════════════════════════════════════════════════════════
# DeriveOp — THE generic derivation step
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class DeriveOp:
    """Derive one operation from entity schema.

    Creates Op type, Request type, Response type, handler — all derived
    from entity schema via projections + handler template.

    This is THE workhorse step. Dialects compose these.

    Args:
        name: Operation name (used for generated type names)
        input_proj: Which entity fields → request/op input
        output: Response shape (fields + converter)
        handler_template: How to build the handler body
        trigger: Trigger for the exposure
        capabilities: Exposure capabilities
        extra_op_fields: Additional fields on Op type (plain types)
        extra_request_fields: Additional fields on Request type (may include Annotated)
    """

    name: str
    input_proj: FieldProjection
    output: ResponseSpec
    handler_template: HandlerTemplate
    trigger: Trigger
    capabilities: tuple[SurfaceCapability, ...] = ()
    extra_op_fields: tuple[tuple[str, type], ...] = ()
    extra_request_fields: tuple[FieldSpec, ...] = ()
    codec_factory: Callable[[type, type], Exposure] | None = None
    effects: tuple[DerivationEffect, ...] = ()
    source: Op | None = None

    def derive_surface[EntityT](self, ctx: SurfaceCtx[EntityT]) -> SurfaceCtx[EntityT]:
        schema = ctx.schema
        entity_name = schema.entity.__name__

        # Project input fields from schema
        in_fields = self.input_proj.project(schema)

        # Annotated fields — preserve Annotated capabilities for wire compiler
        annotated_fields = schema.annotated_field_types(only=set(in_fields.keys()))

        # Accumulate spec — types built later in materialize()
        spec = OpSpec(
            name=self.name,
            entity_name=entity_name,
            input_fields=in_fields,
            request_fields=dict(annotated_fields),
            response_spec=self.output,
            handler_template=self.handler_template,
            trigger=self.trigger,
            capabilities=self.capabilities,
            effects=self.effects,
            codec_factory=self.codec_factory,
            extra_op_fields=self.extra_op_fields,
            extra_request_fields=self.extra_request_fields,
        )
        return ctx.add_spec(spec)


# ═══════════════════════════════════════════════════════════════════════════════
# ExposeOp — wire existing op/handler (no derivation)
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class ExposeOp[T]:
    """Wire existing op/handler into exposure.

    For when you already have Op type, handler, Request, Response.
    No schema derivation — direct wiring. Use this for custom
    domains (game, auth, etc.) where ops are hand-written.

    Error type is always DomainError (matches SurfaceCtx constraint).
    """

    op_type: type
    handler: OperationHandler[T, DomainError]
    request_type: type
    response_type: type
    trigger: Trigger
    capabilities: tuple[SurfaceCapability, ...] = ()

    def derive_surface(self, ctx: SurfaceCtx[T]) -> SurfaceCtx[T]:
        annotated = annotate_handler(self.handler, self.op_type)
        codec = rrc(self.request_type, self.response_type)
        exposure = Exposure(
            trigger=self.trigger, codec=codec, capabilities=self.capabilities
        )
        return ctx.add_operation((self.op_type, annotated, exposure))


# ═══════════════════════════════════════════════════════════════════════════════
# AddGlobalCap — add capability to all exposures
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class AddGlobalCap:
    """Add a global capability to all exposures."""

    cap: SurfaceCapability

    def derive_surface[EntityT](self, ctx: SurfaceCtx[EntityT]) -> SurfaceCtx[EntityT]:
        return ctx.add_capability(self.cap)


# ═══════════════════════════════════════════════════════════════════════════════
# Convenience Constructors
# ═══════════════════════════════════════════════════════════════════════════════


def derive_op(
    name: str,
    input_proj: FieldProjection,
    output: ResponseSpec,
    handler_template: HandlerTemplate,
    trigger: Trigger,
    *caps: SurfaceCapability,
    extra_op_fields: tuple[tuple[str, type], ...] = (),
    extra_request_fields: tuple[FieldSpec, ...] = (),
) -> DeriveOp:
    """Create DeriveOp step."""
    return DeriveOp(
        name=name,
        input_proj=input_proj,
        output=output,
        handler_template=handler_template,
        trigger=trigger,
        capabilities=caps,
        extra_op_fields=extra_op_fields,
        extra_request_fields=extra_request_fields,
    )


def expose_op[T](
    op_type: type,
    handler: OperationHandler[T, DomainError],
    request_type: type,
    response_type: type,
    trigger: Trigger,
    *caps: SurfaceCapability,
) -> ExposeOp[T]:
    """Create ExposeOp step."""
    return ExposeOp(
        op_type=op_type,
        handler=handler,
        request_type=request_type,
        response_type=response_type,
        trigger=trigger,
        capabilities=caps,
    )


def add_global_cap(cap: SurfaceCapability) -> AddGlobalCap:
    """Create AddGlobalCap step."""
    return AddGlobalCap(cap=cap)


__all__ = (
    # Protocols (re-exported from _protocols for backward compat)
    "HandlerTemplate",
    # Composition (re-exported from _protocols for backward compat)
    "WrappedTemplate",
    "wrap_template",
    # Generic steps
    "DeriveOp",
    "ExposeOp",
    "AddGlobalCap",
    # Constructors
    "derive_op",
    "expose_op",
    "add_global_cap",
)

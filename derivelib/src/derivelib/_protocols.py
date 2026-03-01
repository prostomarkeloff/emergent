"""Step protocols + handler template protocol — open-world derivation dispatch.

Each step implements 1+ protocols declaring which axes it touches.
fold_derive checks isinstance() — same pattern as fold_field.

HandlerTemplate is the protocol for building handlers from Op type + context.
Lives here (not in axes/surface.py) because it's a kernel concept used by
_handler_templates.py, _dialect.py, adapt.py, and axes/surface.py.

    from derivelib._protocols import SchemaDerivable, SurfaceDerivable, HandlerTemplate

    @dataclass(frozen=True, slots=True)
    class MyStep:
        '''Step that touches schema and surface.'''

        def derive_schema(self, ctx: SchemaCtx) -> SchemaCtx:
            ...

        def derive_surface(self, ctx: SurfaceCtx) -> SurfaceCtx:
            ...

    # MyStep satisfies both SchemaDerivable and SurfaceDerivable
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from ._ctx import SchemaCtx, QueryCtx, StorageCtx, SurfaceCtx

if TYPE_CHECKING:
    from emergent.wire.axis.query import MutatingRelationalProvider, RelationalQuerySet
    from emergent.wire.axis.surface.capabilities import SurfaceCapability

    from derivelib._ctx import OperationHandler
    from derivelib._effects import DerivationEffect
    from derivelib._errors import DomainError


# ═══════════════════════════════════════════════════════════════════════════════
# Axis Protocols
# ═══════════════════════════════════════════════════════════════════════════════


@runtime_checkable
class SchemaDerivable(Protocol):
    """Step that touches Schema axis (pass 1)."""

    def derive_schema[EntityT](self, ctx: SchemaCtx[EntityT]) -> SchemaCtx[EntityT]: ...


@runtime_checkable
class QueryDerivable(Protocol):
    """Step that touches Query axis (pass 2)."""

    def derive_query[EntityT](self, ctx: QueryCtx[EntityT]) -> QueryCtx[EntityT]: ...


@runtime_checkable
class StorageDerivable(Protocol):
    """Step that touches Storage axis (pass 2)."""

    def derive_storage[EntityT](self, ctx: StorageCtx[EntityT]) -> StorageCtx[EntityT]: ...


@runtime_checkable
class SurfaceDerivable(Protocol):
    """Step that touches Surface axis (pass 2)."""

    def derive_surface[EntityT](self, ctx: SurfaceCtx[EntityT]) -> SurfaceCtx[EntityT]: ...


class FullDerivable(
    SchemaDerivable, QueryDerivable, StorageDerivable, SurfaceDerivable, Protocol
):
    """Step that touches ALL axes (rare, for cross-cutting concerns)."""

    ...


# ═══════════════════════════════════════════════════════════════════════════════
# TransformableStep — transform-algebra-visible interface
# ═══════════════════════════════════════════════════════════════════════════════


@runtime_checkable
class TransformableStep(Protocol):
    """Step visible to the transform algebra.

    Steps implementing this protocol can be filtered by effect,
    receive capabilities, and participate in the DerivationT algebra.

    DeriveOp implements this naturally (already has all 3 fields).
    Custom steps (workflow, methods, TG) opt in by adding effects.
    """

    @property
    def name(self) -> str: ...

    @property
    def effects(self) -> tuple[DerivationEffect, ...]: ...

    @property
    def capabilities(self) -> tuple[SurfaceCapability, ...]: ...


def replace_caps[S: TransformableStep](
    step: S,
    capabilities: tuple[SurfaceCapability, ...],
) -> S:
    """Replace capabilities on any TransformableStep.

    Uses dataclasses.replace() — all TransformableStep implementors
    are frozen dataclasses, but Python's type system cannot express
    "Protocol that is also a dataclass" (no Dataclass protocol with
    replace() support exists).
    """
    from dataclasses import replace
    return replace(step, capabilities=capabilities)  # type: ignore[type-var]


# ═══════════════════════════════════════════════════════════════════════════════
# HandlerSpec — precise data for handler construction
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class HandlerSpec[EntityT]:
    """Precisely what a handler template needs — not the entire SurfaceCtx.

    Built by the materializer from SurfaceCtx, passed to HandlerTemplate.build().

    Attributes:
        entity: The entity dataclass type (e.g., User, Post).
        entity_name: entity.__name__, used for error messages and type naming.
        identity_names: Tuple of identity field names (e.g., ("id",) or ("user_id", "post_id")).
        non_identity_names: Tuple of non-identity field names (e.g., ("name", "email")).
        base_query: Pre-built relational query from query axis, or None if no query configured.
    """

    entity: type[EntityT]
    entity_name: str
    identity_names: tuple[str, ...]
    non_identity_names: tuple[str, ...]
    base_query: RelationalQuerySet[EntityT] | None


# ═══════════════════════════════════════════════════════════════════════════════
# HasProvider Protocol — typed access to op.provider in handler templates
# ═══════════════════════════════════════════════════════════════════════════════


class HasProvider[E](Protocol):
    """Protocol for dynamically-generated ops with a relational provider.

    Replaces unbounded OpT in handler templates. Gives pyright
    typed access to op.provider instead of attribute error on TypeVar.
    """

    @property
    def provider(self) -> MutatingRelationalProvider[E]: ...


# ═══════════════════════════════════════════════════════════════════════════════
# HandlerTemplate Protocol
# ═══════════════════════════════════════════════════════════════════════════════


@runtime_checkable
class HandlerTemplate(Protocol):
    """Template for building a handler from Op type + handler spec.

    Dialect-specific: CRUD has FetchMany, FetchOneById, etc.
    Game dialects have their own. The protocol is generic.

    Result type uses Any because handler templates return varying types
    (EntityT, list[EntityT], dict[str, ...]) and kungfu's Ok[T] is invariant,
    making a common Result supertype impossible without Any.
    """

    def build[EntityT](self, spec: HandlerSpec[EntityT]) -> OperationHandler[Any, DomainError]: ...


class WrapperFn(Protocol):
    """Rank-2 wrapper function protocol — generic over entity type.

    A WrapperFn takes an inner handler + spec and returns a new handler,
    working for any EntityT. Used by WrappedTemplate and wrap_by_effect.
    """

    def __call__[EntityT](
        self,
        inner: OperationHandler[EntityT, DomainError],
        spec: HandlerSpec[EntityT],
    ) -> OperationHandler[EntityT, DomainError]: ...


@dataclass(frozen=True, slots=True)
class WrappedTemplate:
    """Compose handler templates: inner handler wrapped by an outer function.

    The wrapper receives the built inner handler plus build context,
    returns a new handler that can call inner, add before/after logic, etc.

        audited = WrappedTemplate(InsertNew(), audit_wrapper)

        def audit_wrapper(inner, spec):
            async def handler(op):
                result = await inner(op)
                log_audit(op, result)
                return result
            return handler
    """

    inner: HandlerTemplate
    wrapper: WrapperFn

    def build[EntityT](self, spec: HandlerSpec[EntityT]) -> OperationHandler[EntityT, DomainError]:
        handler = self.inner.build(spec)
        return self.wrapper(handler, spec)


def wrap_template(
    inner: HandlerTemplate,
    wrapper: WrapperFn,
) -> WrappedTemplate:
    """Wrap a handler template with before/after logic.

        def validate_unique(inner, spec):
            field = "email"
            async def handler(op):
                existing = await op.provider.fetch_one(...)
                if existing:
                    return Error(AlreadyExists(...))
                return await inner(op)
            return handler

        VALIDATED_CREATE = Op("Create", ..., wrap_template(InsertNew(), validate_unique))
    """
    return WrappedTemplate(inner=inner, wrapper=wrapper)


__all__ = (
    # Axis protocols
    "SchemaDerivable",
    "QueryDerivable",
    "StorageDerivable",
    "SurfaceDerivable",
    "FullDerivable",
    # Transform algebra
    "TransformableStep",
    "replace_caps",
    # Handler spec
    "HandlerSpec",
    # Provider protocol
    "HasProvider",
    # Handler template
    "HandlerTemplate",
    "WrapperFn",
    "WrappedTemplate",
    "wrap_template",
)

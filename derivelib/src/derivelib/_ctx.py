"""Per-axis derivation contexts — accumulated state during fold_derive.

Two-pass fold:
  Pass 1: SchemaCtx (inspect entity, validate constraints)
  Pass 2: QueryCtx, StorageCtx, SurfaceCtx (with frozen SchemaCtx)

v4: No deps. Infrastructure resolved via compose.Node at runtime.
    Contexts store node TYPES, not instances.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field as dataclass_field, replace
from typing import TYPE_CHECKING

from emergent.wire.axis._capability import Capability
from emergent.wire.axis.query import RelationalQuerySet
from emergent.wire.axis.schema import FieldInfo, inspect_type, fields_with_capability
from emergent.wire.axis.surface import Exposure
from emergent.wire.axis.surface.capabilities import SurfaceCapability


def _make_annotated(base_type: type, capabilities: tuple[Capability, ...]) -> type:
    """Build Annotated[base_type, *caps] at runtime.

    Pyright treats Annotated as a special form and doesn't model
    __getitem__ on it. No static alternative exists for building
    Annotated types dynamically — this is a fundamental limitation of
    the typing module's runtime API having no static type.
    """
    import typing

    # typing.Annotated is a _SpecialForm; subscripting calls __getitem__.
    # Pyright doesn't model this — getattr is the only way without Any/ignore.
    args: tuple[type | Capability, ...] = (base_type, *capabilities)
    getitem: Callable[[tuple[type | Capability, ...]], type] = getattr(typing, "Annotated").__getitem__
    return getitem(args)

if TYPE_CHECKING:
    from kungfu import Result
    from derivelib._builders import ExposureBuilder
    from derivelib._errors import DomainError
    from derivelib._opspec import OpSpec


# ═══════════════════════════════════════════════════════════════════════════════
# Schema Axis Context (Pass 1)
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class SchemaCtx[EntityT]:
    """Schema axis context — accumulated during pass 1.

    Immutable. Steps return new SchemaCtx via dataclasses.replace().
    Supports composite identity (multiple fields with Identity).
    """

    entity: type[EntityT]
    fields: dict[str, FieldInfo]
    identity_fields: dict[str, FieldInfo] = dataclass_field(default_factory=lambda: dict[str, FieldInfo]())

    @staticmethod
    def from_entity[E](entity: type[E]) -> SchemaCtx[E]:
        """Create initial SchemaCtx by inspecting entity type."""
        from emergent.wire.axis.schema._universal import Identity

        fields = inspect_type(entity)
        id_triples = fields_with_capability(entity, Identity)
        id_fields = {name: info for name, info, _cap in id_triples}
        return SchemaCtx(entity=entity, fields=fields, identity_fields=id_fields)

    def identity_names(self) -> tuple[str, ...]:
        """All identity field names."""
        return tuple(self.identity_fields.keys())

    def non_identity_fields(self) -> dict[str, FieldInfo]:
        """Get fields excluding all identity fields."""
        return {
            name: info
            for name, info in self.fields.items()
            if name not in self.identity_fields
        }

    def field_types(self, exclude: tuple[str, ...] = ()) -> dict[str, type]:
        """Get {name: base_type} dict, optionally excluding fields."""
        return {
            name: info.base_type
            for name, info in self.fields.items()
            if name not in exclude
        }

    def annotated_field_types(
        self, exclude: tuple[str, ...] = (), only: set[str] | None = None,
    ) -> dict[str, type]:
        """Get {name: Annotated[base_type, *caps]} dict — preserves schema capabilities.

        Use for Request/Response types that go through the wire compiler.
        The compiler reads capabilities for Pydantic validation, OpenAPI docs, CLI help.
        """
        result: dict[str, type] = {}
        for name, info in self.fields.items():
            if name in exclude:
                continue
            if only is not None and name not in only:
                continue
            if info.capabilities:
                result[name] = _make_annotated(info.base_type, info.capabilities)
            else:
                result[name] = info.base_type
        return result


# ═══════════════════════════════════════════════════════════════════════════════
# Query Axis Context (Pass 2)
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class QueryCtx[EntityT]:
    """Query axis context — accumulated during pass 2.

    schema is frozen from pass 1.
    provider_node is a nodnod node TYPE for compose.Node resolution.
    """

    schema: SchemaCtx[EntityT]
    provider_node: type | None = None
    base_query: RelationalQuerySet[EntityT] | None = None


# ═══════════════════════════════════════════════════════════════════════════════
# Storage Axis Context (Pass 2)
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class StorageCtx[EntityT]:
    """Storage axis context — accumulated during pass 2.

    schema is frozen from pass 1.
    backend_node is a nodnod node TYPE for compose.Node resolution.
    """

    schema: SchemaCtx[EntityT]
    backend_node: type | None = None


# ═══════════════════════════════════════════════════════════════════════════════
# Surface Axis Context (Pass 2)
# ═══════════════════════════════════════════════════════════════════════════════


# Operation triple: (OpType, handler, Exposure)
# Handler signature is (op: T) -> Result[R, E] — generic over dynamically-created
# Op types, so the callable signature cannot be fully expressed statically.
type OperationHandler[T, E] = Callable[..., Awaitable[Result[T, E]]]
type Operation[T, E] = tuple[type, OperationHandler[T, E], Exposure]


@dataclass(frozen=True, slots=True)
class SurfaceCtx[EntityT]:
    """Surface axis context — accumulated during pass 2.

    schema is frozen from pass 1.
    query/storage set by fold_derive after those phases complete.

    Two accumulation paths:
    - specs: OpSpec descriptions (from DeriveOp) — materialized later
    - operations: direct (OpType, handler, Exposure) tuples (from ExposeOp)
    """

    schema: SchemaCtx[EntityT]
    query: QueryCtx[EntityT] | None = None
    storage: StorageCtx[EntityT] | None = None
    specs: tuple[OpSpec, ...] = ()
    operations: tuple[Operation[EntityT, DomainError], ...] = ()
    capabilities: tuple[SurfaceCapability, ...] = ()

    def get_base_query(self) -> RelationalQuerySet[EntityT] | None:
        """Get base query from query context."""
        if self.query is not None:
            return self.query.base_query
        return None

    def add_spec(self, spec: OpSpec) -> SurfaceCtx[EntityT]:
        """Return new ctx with OpSpec appended."""
        return replace(self, specs=(*self.specs, spec))

    def add_operation(self, op: Operation[EntityT, DomainError]) -> SurfaceCtx[EntityT]:
        """Return new ctx with direct operation appended."""
        return replace(self, operations=(*self.operations, op))

    def add_exposure(self, builder: ExposureBuilder[EntityT, DomainError]) -> SurfaceCtx[EntityT]:
        """Build ExposureBuilder and add resulting operation.

        Eliminates the 3-tuple dance::

            # before:
            _, h, exp = exposure(...).request(...).handler(...).trigger(...).build()
            return ctx.add_operation((_, h, exp))

            # after:
            return ctx.add_exposure(
                exposure(...).request(...).handler(...).trigger(...)
            )
        """
        return self.add_operation(builder.build())

    def add_capability(self, cap: SurfaceCapability) -> SurfaceCtx[EntityT]:
        """Return new ctx with global capability appended."""
        return replace(self, capabilities=(*self.capabilities, cap))


# ═══════════════════════════════════════════════════════════════════════════════
# Full Derivation Context
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class DerivationCtx[EntityT]:
    """Full derivation context — all axes bundled after fold_derive."""

    schema: SchemaCtx[EntityT]
    query: QueryCtx[EntityT]
    storage: StorageCtx[EntityT]
    surface: SurfaceCtx[EntityT]


__all__ = (
    "SchemaCtx",
    "QueryCtx",
    "StorageCtx",
    "SurfaceCtx",
    "OperationHandler",
    "Operation",
    "DerivationCtx",
)

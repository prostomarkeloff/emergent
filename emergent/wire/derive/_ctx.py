"""Unified derivation context — accumulated state during compile_derive.

Two-phase fold over @schema_meta capabilities:
  Phase 1: DeriveGeneratable (CRUD generates OpSpecs)
  Phase 2: DeriveModifiable (Paginated/SoftDelete transform specs)

    from emergent.wire.derive import DeriveCtx, compile_derive

    ctx = compile_derive(User)
    endpoint = materialize(ctx)
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field as dataclass_field, replace
from typing import Any, TYPE_CHECKING, Never

from emergent.wire.axis._explain import ExplainContext, ExplainNode
from emergent.wire.axis.query import RelationalQuerySet
from emergent.wire.axis.schema import FieldInfo, fields_with_capability, inspect_type
from emergent.wire.axis.surface import Exposure
from emergent.wire.axis.surface.capabilities import SurfaceCapability
from emergent.wire.derive._codegen import AnnotationValue, make_annotation
from emergent.wire.derive._query_strategy import (
    NoQueryStrategy,
    QueryStrategy,
    RelationalStrategy,
)

if TYPE_CHECKING:
    from emergent.wire.axis.query._expr import Expr
    from emergent.wire.axis.query._proxy import EntityProxy


if TYPE_CHECKING:
    from kungfu import Result

    from emergent.wire.derive._errors import DomainError
    from emergent.wire.derive._handler import WrapperFn
    from emergent.wire.derive._opspec import OpSpec


# Operation triple: (OpType, handler, Exposure)
type OperationHandler[T, E] = Callable[..., Awaitable[Result[T, E]]]
type Operation[T, E] = tuple[type, OperationHandler[T, E], Exposure]

# ── Named type aliases (house style: alias instead of inline dict[...]) ──
type FieldMap = dict[str, FieldInfo]
type FieldTypeMap = dict[str, AnnotationValue]


@dataclass(frozen=True, slots=True)
class DeriveCtx[EntityT]:
    """Unified derivation context — accumulated during compile_derive.

    Merges derivelib's SchemaCtx + QueryCtx + SurfaceCtx into one flat
    dataclass. All axes visible to every compile_derive_* method.

    Immutable. Methods return new DeriveCtx via dataclasses.replace().
    """

    entity: type[EntityT]
    fields: FieldMap = dataclass_field(
        default_factory=lambda: dict[str, FieldInfo]()
    )
    identity_fields: FieldMap = dataclass_field(
        default_factory=lambda: dict[str, FieldInfo]()
    )
    # Query axis
    # NoQueryStrategy is a phantom-typed empty frozen dataclass — covariant.
    # Never is the bottom type, so NoQueryStrategy[Never] is a subtype of
    # QueryStrategy[EntityT] for any EntityT.
    query_strategy: QueryStrategy[EntityT] = dataclass_field(
        default_factory=lambda: NoQueryStrategy[Never]()
    )
    # Surface axis
    specs: tuple[OpSpec, ...] = ()
    operations: tuple[Operation[object, DomainError], ...] = ()
    capabilities: tuple[SurfaceCapability, ...] = ()

    def compile_explain(self, ctx: ExplainContext) -> ExplainContext:
        """Self-describe via the shared `Explainable` protocol.

        Derive's dict projection is bespoke (semantic trigger labels,
        scalar-only effect/capability reflection), so it is carried verbatim
        as `raw` rather than restructured into shared node fields/children.
        """
        from emergent.wire.derive._explain import derive_dict

        return ctx.add(ExplainNode(type(self).__name__, raw=derive_dict(self)))

    # ─── Backward-compat properties (query axis) ─────────────────

    @property
    def provider_node(self) -> type | None:
        """Provider node type, if relational strategy."""
        if isinstance(self.query_strategy, RelationalStrategy):
            return self.query_strategy.provider_node
        return None

    @property
    def base_query(self) -> RelationalQuerySet[EntityT] | None:
        """Base query, if relational strategy."""
        if isinstance(self.query_strategy, RelationalStrategy):
            return self.query_strategy.base_query
        return None

    @staticmethod
    def from_entity[E](entity: type[E]) -> DeriveCtx[E]:
        """Create initial DeriveCtx by inspecting entity type."""
        from emergent.wire.axis.schema._universal import Identity

        fields = inspect_type(entity)
        id_triples = fields_with_capability(entity, Identity)
        id_fields = {name: info for name, info, _cap in id_triples}
        return DeriveCtx(entity=entity, fields=fields, identity_fields=id_fields)

    @staticmethod
    def from_subject[S](subject: type[S]) -> DeriveCtx[S]:
        """Create DeriveCtx from any type. No field inspection, no identity requirement.

        For non-entity subjects (services, configs, plain classes) that don't have
        structured fields. Capabilities on the subject drive all derivation logic.
        """
        return DeriveCtx(entity=subject)

    # ─── Schema helpers (from SchemaCtx) ─────────────────────────────

    def identity_names(self) -> tuple[str, ...]:
        """All identity field names."""
        return tuple(self.identity_fields.keys())

    def non_identity_fields(self) -> FieldMap:
        """Get fields excluding all identity fields."""
        return {
            name: info
            for name, info in self.fields.items()
            if name not in self.identity_fields
        }

    def field_types(self, exclude: tuple[str, ...] = ()) -> FieldTypeMap:
        """Get {name: base_type} dict, optionally excluding fields."""
        return {
            name: info.base_type
            for name, info in self.fields.items()
            if name not in exclude
        }

    def annotated_field_types(
        self, exclude: tuple[str, ...] = (), only: set[str] | None = None,
    ) -> FieldTypeMap:
        """Get {name: Annotated[base_type, *caps]} dict — preserves schema capabilities.

        Use for Request/Response types that go through the wire compiler.
        The compiler reads capabilities for Pydantic validation, OpenAPI docs, CLI help.
        """
        result: FieldTypeMap = {}
        for name, info in self.fields.items():
            if name in exclude:
                continue
            if only is not None and name not in only:
                continue
            if info.capabilities:
                result[name] = make_annotation(info.base_type, *info.capabilities)
            else:
                result[name] = info.base_type
        return result

    # ─── Surface helpers (from SurfaceCtx) ───────────────────────────

    def add_spec(self, spec: OpSpec) -> DeriveCtx[EntityT]:
        """Return new ctx with OpSpec appended."""
        return replace(self, specs=(*self.specs, spec))

    def add_operation(self, op: Operation[Any, DomainError]) -> DeriveCtx[EntityT]:
        """Return new ctx with direct operation appended."""
        return replace(self, operations=(*self.operations, op))

    def add_capability(self, cap: SurfaceCapability) -> DeriveCtx[EntityT]:
        """Return new ctx with global capability appended."""
        return replace(self, capabilities=(*self.capabilities, cap))

    # ─── Spec transform helpers (for DeriveModifiable) ─────────────

    def replace_handler(
        self,
        effect: type,
        template: Any,
    ) -> DeriveCtx[EntityT]:
        """Replace handler_template on specs matching effect type.

            ctx = ctx.replace_handler(Deletes, SoftDeleteMark("deleted_at"))
        """
        from emergent.wire.derive._effects import has_effect

        return replace(self, specs=tuple(
            replace(s, handler_template=template) if has_effect(s.effects, effect) else s
            for s in self.specs
        ))

    def exclude_fields(
        self,
        effect: type,
        exclude: frozenset[str],
    ) -> DeriveCtx[EntityT]:
        """Remove fields from input_fields/request_fields on specs matching effect.

            ctx = ctx.exclude_fields(Creates, frozenset({"created_at", "updated_at"}))
        """
        from emergent.wire.derive._effects import has_effect

        new_specs: list[OpSpec] = []
        for s in self.specs:
            if has_effect(s.effects, effect):
                s = replace(
                    s,
                    input_fields={k: v for k, v in s.input_fields.items() if k not in exclude},
                    request_fields={k: v for k, v in s.request_fields.items() if k not in exclude},
                )
            new_specs.append(s)
        return replace(self, specs=tuple(new_specs))

    def filter_query(
        self,
        fn: Callable[[EntityProxy[EntityT]], Expr],
    ) -> DeriveCtx[EntityT]:
        """Apply filter function to base_query. No-op if not relational.

            ctx = ctx.filter_query(lambda e: e.deleted_at.is_null())
        """
        if not isinstance(self.query_strategy, RelationalStrategy):
            return self
        new_strategy = replace(
            self.query_strategy,
            base_query=self.query_strategy.base_query.filter(fn),
        )
        return replace(self, query_strategy=new_strategy)

    def reject_by_effect(self, effect: type) -> DeriveCtx[EntityT]:
        """Remove specs matching effect type.

            ctx = ctx.reject_by_effect(Mutation)  # readonly
        """
        from emergent.wire.derive._effects import has_effect

        return replace(self, specs=tuple(
            s for s in self.specs if not has_effect(s.effects, effect)
        ))

    def select_by_effect(self, effect: type) -> DeriveCtx[EntityT]:
        """Keep only specs matching effect type.

            ctx = ctx.select_by_effect(Mutation)  # mutations only
        """
        from emergent.wire.derive._effects import has_effect

        return replace(self, specs=tuple(
            s for s in self.specs if has_effect(s.effects, effect)
        ))

    def add_spec_capability(
        self,
        cap: SurfaceCapability,
        effect: type | None = None,
    ) -> DeriveCtx[EntityT]:
        """Add capability to specs, optionally filtered by effect.

            ctx = ctx.add_spec_capability(AuthCap())           # all specs
            ctx = ctx.add_spec_capability(AuthCap(), Mutation)  # mutations only
        """
        from emergent.wire.derive._effects import has_effect

        if effect is None:
            return replace(self, specs=tuple(
                replace(s, capabilities=(*s.capabilities, cap))
                for s in self.specs
            ))
        return replace(self, specs=tuple(
            replace(s, capabilities=(*s.capabilities, cap))
            if has_effect(s.effects, effect) else s
            for s in self.specs
        ))

    def wrap_handler(
        self,
        effect: type,
        wrapper: WrapperFn,
    ) -> DeriveCtx[EntityT]:
        """Wrap handler on specs matching effect with WrappedTemplate.

            ctx = ctx.wrap_handler(Read, my_wrapper_fn)
        """
        from emergent.wire.derive._effects import has_effect
        from emergent.wire.derive._handler import WrappedTemplate

        return replace(self, specs=tuple(
            replace(s, handler_template=WrappedTemplate(inner=s.handler_template, wrapper=wrapper))
            if has_effect(s.effects, effect) else s
            for s in self.specs
        ))

    def map_specs_by_effect(
        self,
        effect: type,
        fn: Callable[[OpSpec], OpSpec],
    ) -> DeriveCtx[EntityT]:
        """Transform specs matching effect with a function.

            ctx = ctx.map_specs_by_effect(Read, lambda s: replace(s, output=PaginatedResponse()))
        """
        from emergent.wire.derive._effects import has_effect

        return replace(self, specs=tuple(
            fn(s) if has_effect(s.effects, effect) else s
            for s in self.specs
        ))


__all__ = (
    "DeriveCtx",
    "OperationHandler",
    "Operation",
)

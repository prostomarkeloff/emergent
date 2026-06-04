"""Compilation phases — open-world compiler infrastructure.

CompilationPhase[Ctx] reifies the (context_type, protocol, initial) triple.
compile_fields() runs all field-level phases in one pass.
compile_entity() wraps compile_fields() and adds entity-level folds.

    from emergent.wire.compile._phase import (
        CompilationPhase, FieldCompilation, EntityCompilation, compile_entity,
        PYDANTIC_PHASE, OPENAPI_PHASE, ARGPARSE_PHASE,
    )

    ec = compile_entity(User, axes, [PYDANTIC_PHASE, OPENAPI_PHASE])
    for fc in ec:
        pydantic_ctx = fc[PYDANTIC_PHASE]   # typed PydanticContext
        openapi_ctx = fc[OPENAPI_PHASE]     # typed OpenAPIContext

    # Entity-level (from @schema_meta)
    model_ctx = ec[PYDANTIC_MODEL_FOLD]     # typed PydanticModelContext

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

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from emergent.wire.axis.query._expr import Expr

from emergent.wire.axis._capability import (
    Capability,
    PydanticContext,
    PydanticModelContext,
    OpenAPIContext,
    OpenAPISchemaContext,
    ArgparseContext,
    RequestBuildContext,
    TelegrinderInputContext,
    TelegrinderRenderContext,
    ConstraintsContext,
    QuerySchemaContext,
    StorageFieldContext,
    PydanticCompilable,
    PydanticModelCompilable,
    OpenAPICompilable,
    OpenAPISchemaCompilable,
    ArgparseCompilable,
    RequestBuildCompilable,
    TelegrinderInputCompilable,
    TelegrinderRenderCompilable,
    ConstraintsCompilable,
    QuerySchemaCompilable,
    StorageFieldCompilable,
)
from emergent.wire.axis.schema import FieldInfo
from emergent.wire.compile._core import Axes, CapabilityHandler, fold_field, fold_schema, traced_fold


# ═══════════════════════════════════════════════════════════════════════════════
# EntityFold — entity-level fold descriptor (companion to CompilationPhase)
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class EntityFold[EntityCtx]:
    """Entity-level fold descriptor — folds @schema_meta capabilities.

    Companion to a field-level CompilationPhase. Lives on phase.entity.
    Describes how to fold schema-level capabilities (SchemaName, Abstract, etc.)
    into an entity-level context.

    Args:
        context_type: Type of entity-level context (PydanticModelContext, etc.)
        protocol: Protocol with exactly one compile_* method for entity-level fold
        initial: Factory (class_name: str) → initial entity context
    """

    context_type: type[EntityCtx]
    protocol: type
    initial: Callable[[str], EntityCtx]
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


# ═══════════════════════════════════════════════════════════════════════════════
# CompilationPhase — one fold pass descriptor
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class CompilationPhase[Ctx]:
    """One fold pass descriptor — reified phase identity.

    Identified by context_type — no strings anywhere.
    Method name auto-derived from protocol's compile_* method.
    Immutable value. Use .with_handlers() for custom handler overrides.

    Optional entity-level fold: set via entity= or .with_entity().
    When present, compile_entity() runs fold_schema() for this phase too.

    Args:
        context_type: Type of the fold context (PydanticContext, etc.)
        protocol: Protocol with exactly one compile_* method
        initial: Factory (field_name, field_type) → initial context
        handlers: Optional custom handlers keyed by capability type
        entity: Optional entity-level fold (folds @schema_meta capabilities)
    """

    context_type: type[Ctx]
    protocol: type
    initial: Callable[[str, type], Ctx]
    handlers: Mapping[type[Capability], CapabilityHandler[Ctx]] | None = None
    # Any — heterogeneous entity fold (EntityFold[PydanticModelContext],
    # EntityFold[OpenAPISchemaContext], etc.). Python has no existential types;
    # Any is the correct erasure for heterogeneous generic storage.
    entity: EntityFold[Any] | None = None
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

    def with_entity(self, entity_fold: EntityFold[Any]) -> CompilationPhase[Ctx]:
        """Return new phase with entity-level fold attached. Immutable."""
        return replace(self, entity=entity_fold)

    def without_entity(self) -> CompilationPhase[Ctx]:
        """Return new phase with entity-level fold removed. Immutable."""
        return replace(self, entity=None)

    def same_slot(self, other: CompilationPhase[Any]) -> bool:
        """True if other occupies the same context_type slot."""
        return self.context_type is other.context_type

    def __add__(self, other: CompilationPhase[Any] | SchemaCompiler) -> SchemaCompiler:
        """Lift to SchemaCompiler and combine."""
        if isinstance(other, CompilationPhase):
            return SchemaCompiler(phases=(self, other))
        return SchemaCompiler(phases=(self,)) + other

    def __radd__(self, other: CompilationPhase[Any] | SchemaCompiler) -> SchemaCompiler:
        if isinstance(other, CompilationPhase):
            return SchemaCompiler(phases=(other, self))
        return other + SchemaCompiler(phases=(self,))


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
# EntityCompilation — field-level + entity-level compilation result
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class EntityCompilation:
    """Complete entity compilation — fields + entity-level contexts.

    Returned by compile_entity() and SchemaCompiler.compile().
    Provides typed access to entity-level contexts by EntityFold key.

    Example::

        ec = FASTAPI_SCHEMA.compile(User, axes)

        # Entity-level (from @schema_meta)
        model_ctx = ec[PYDANTIC_MODEL_FOLD]   # PydanticModelContext

        # Field-level (same as before)
        for fc in ec:
            pydantic_ctx = fc[PYDANTIC_PHASE]  # PydanticContext

    Backward-compatible: iterating yields FieldCompilation.
    """

    fields: tuple[FieldCompilation, ...]
    _entity_contexts: dict[type, object]

    def __getitem__[EntityCtx](self, fold: EntityFold[EntityCtx]) -> EntityCtx:
        """Get typed entity-level context by EntityFold key."""
        ctx = self._entity_contexts.get(fold.context_type)
        if ctx is None:
            raise KeyError(
                f"No entity context for {fold.context_type.__name__}"
            )
        # dict stores heterogeneous contexts as object; generic EntityCtx
        # on EntityFold provides correct static type at call site.
        # Same pattern as FieldCompilation.__getitem__.
        return ctx

    def get[EntityCtx](self, fold: EntityFold[EntityCtx]) -> EntityCtx | None:
        """Get typed entity context, or None if not present."""
        # Same heterogeneous dict → typed return bridge as __getitem__
        return self._entity_contexts.get(fold.context_type)

    def has_entity(self, fold: EntityFold[Any]) -> bool:
        """Check if entity context exists for this fold."""
        return fold.context_type in self._entity_contexts

    # Backward compat — iteration yields FieldCompilation
    def __iter__(self) -> Iterator[FieldCompilation]:
        return iter(self.fields)

    def __len__(self) -> int:
        return len(self.fields)


# ═══════════════════════════════════════════════════════════════════════════════
# compile_fields — field-level compilation kernel
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
        contexts: dict[type, Any] = {}
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
# compile_entity — field-level + entity-level compilation
# ═══════════════════════════════════════════════════════════════════════════════


def compile_entity(
    cls: type,
    axes: Axes,
    phases: Sequence[CompilationPhase[Any]],
) -> EntityCompilation:
    """Full entity compilation — field folds + entity-level folds.

    Wraps compile_fields() and adds entity-level folds for phases that
    have an EntityFold companion. Entity-level folds iterate @schema_meta
    capabilities via fold_schema().

    Pure function: (class, axes, phases) → EntityCompilation.
    Entity-level folds are optional — phases without .entity are skipped.

    Example::

        ec = compile_entity(User, axes, [PYDANTIC_PHASE, OPENAPI_PHASE])
        model_ctx = ec[PYDANTIC_MODEL_FOLD]  # PydanticModelContext
        for fc in ec:
            pydantic = fc[PYDANTIC_PHASE]    # PydanticContext
    """
    # 1. Field-level (existing, unchanged)
    field_compilations = compile_fields(cls, axes, phases)

    # 2. Entity-level folds (new)
    entity_contexts: dict[type, Any] = {}
    trace = axes.trace

    for phase in phases:
        if phase.entity is None:
            continue
        ef = phase.entity
        ctx = ef.initial(cls.__name__)
        ctx = fold_schema(cls, ctx, ef.protocol, ef.method, trace=trace)
        entity_contexts[ef.context_type] = ctx

    return EntityCompilation(
        fields=tuple(field_compilations),
        _entity_contexts=entity_contexts,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Pre-built Phase Constants
# ═══════════════════════════════════════════════════════════════════════════════
#
# Named functions (not lambdas) for serialization and clarity.
# Lazy imports where needed (pydantic, openapi type mapping).


def _openapi_initial(name: str, field_type: type) -> OpenAPIContext:
    from emergent.wire.compile._schema import type_to_json_schema

    schema = type_to_json_schema(field_type)
    return OpenAPIContext(name, field_type, schema=schema)


def _argparse_initial(name: str, field_type: type) -> ArgparseContext:
    return ArgparseContext(name, field_type)


def _request_build_initial(name: str, field_type: type) -> RequestBuildContext:
    return RequestBuildContext(name, field_type)


def _tg_input_initial(name: str, field_type: type) -> TelegrinderInputContext:
    return TelegrinderInputContext(name, field_type)


def _tg_render_initial(name: str, field_type: type) -> TelegrinderRenderContext:
    return TelegrinderRenderContext(name, field_type)


def _constraints_initial(name: str, field_type: type) -> ConstraintsContext:
    return ConstraintsContext(field_name=name, field_type=field_type)


def _query_schema_initial(name: str, field_type: type) -> QuerySchemaContext:
    return QuerySchemaContext(field_name=name, field_type=field_type)


# Entity-level fold constants (folds @schema_meta capabilities)
PYDANTIC_MODEL_FOLD: EntityFold[PydanticModelContext] = EntityFold(
    PydanticModelContext, PydanticModelCompilable,
    lambda name: PydanticModelContext(class_name=name),
)
OPENAPI_SCHEMA_FOLD: EntityFold[OpenAPISchemaContext] = EntityFold(
    OpenAPISchemaContext, OpenAPISchemaCompilable,
    lambda name: OpenAPISchemaContext(class_name=name),
)



def _pydantic_initial(name: str, field_type: type) -> PydanticContext:
    from pydantic.fields import FieldInfo
    return PydanticContext(name, field_type, FieldInfo())


PYDANTIC_PHASE = CompilationPhase(
    PydanticContext, PydanticCompilable, _pydantic_initial,
    entity=PYDANTIC_MODEL_FOLD,
)
OPENAPI_PHASE = CompilationPhase(
    OpenAPIContext, OpenAPICompilable, _openapi_initial,
    entity=OPENAPI_SCHEMA_FOLD,
)
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
CONSTRAINTS_PHASE = CompilationPhase(
    ConstraintsContext, ConstraintsCompilable, _constraints_initial
)
QUERY_SCHEMA_PHASE = CompilationPhase(
    QuerySchemaContext, QuerySchemaCompilable, _query_schema_initial
)


def _storage_field_initial(name: str, field_type: type) -> StorageFieldContext:
    return StorageFieldContext(field_name=name, field_type=field_type)


STORAGE_FIELD_PHASE = CompilationPhase(
    StorageFieldContext, StorageFieldCompilable, _storage_field_initial
)

# Phase groups for derivelib
FASTAPI_PHASES = (PYDANTIC_PHASE, OPENAPI_PHASE)
CLI_PHASES = (ARGPARSE_PHASE,)
TG_PHASES = (TG_INPUT_PHASE, TG_RENDER_PHASE, REQUEST_BUILD_PHASE)


# ═══════════════════════════════════════════════════════════════════════════════
# Compilation — generic typed compilation result
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Compilation[T, Model]:
    """Typed compilation result — generic over entity and backend model.

    SA:    Compilation[User, DeclarativeBase]
    Mongo: Compilation[User, dict]

    Produced by backend assemblers (compile_sa, compile_mongo, etc.).
    Used by stores, mapping functions, compile_expr.

    fields holds the per-field compilation results. All storage metadata
    (identity, coercion) is read from STORAGE_FIELD_PHASE — one fold, no combining.
    """

    model: type[Model]
    entity: type[T]
    fields: tuple[FieldCompilation, ...]

    @property
    def identity_field(self) -> str | None:
        """Find the identity field name from compiled fields."""
        for fc in self.fields:
            meta = fc[STORAGE_FIELD_PHASE]
            if meta.is_identity:
                return fc.name
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# SchemaCompiler — composable phase compilation
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class SchemaCompiler:
    """Composable schema compiler — compile once, assemble many.

    Functorial projection: (entity × axes) → FieldCompilation^n.
    Phase configuration determines which output axes are computed.
    Phases identified by context_type — the natural identity key.

    Algebraic operations (keyed by context_type):
        compiler_a + compiler_b     # left-biased union (idempotent)
        compiler_a | compiler_b     # right-biased merge (override)
        compiler_a - compiler_b     # restriction (remove phases)
        compiler_a & compiler_b     # intersection
        phase in compiler           # membership by context_type
        compiler[PydanticContext]    # lookup by context_type

    Laws:
        A + A == A                  (idempotent)
        (A + B) + C == A + (B + C)  (associative)
        A + empty == A              (identity)

    Example::

        FULLSTACK = FASTAPI_SCHEMA + SA_SCHEMA
        ec = FULLSTACK.compile(User, axes)
        PydanticModel = assemble_pydantic(User, ec)
        sa_compiled = assemble_sa(User, ec)
    """

    phases: tuple[CompilationPhase[Any], ...]

    def compile(self, cls: type, axes: Axes) -> EntityCompilation:
        """Compile all phases — field-level + entity-level — in one pass."""
        return compile_entity(cls, axes, list(self.phases))

    # ─── Lego operations (context_type matching) ──────────────────────

    def with_phase(self, phase: CompilationPhase[Any]) -> SchemaCompiler:
        """Add phase. Raises ValueError if context_type already present."""
        if any(p.context_type is phase.context_type for p in self.phases):
            raise ValueError(
                f"context_type {phase.context_type.__name__} already present — "
                f"use replace_phase() or | for override"
            )
        return replace(self, phases=(*self.phases, phase))

    def with_phases(self, *phases: CompilationPhase[Any]) -> SchemaCompiler:
        """Add multiple phases. Raises ValueError on context_type conflict."""
        result = self
        for phase in phases:
            result = result.with_phase(phase)
        return result

    def without_phase(self, phase: CompilationPhase[Any] | type) -> SchemaCompiler:
        """Remove by context_type. Accepts phase or bare type."""
        key = phase.context_type if isinstance(phase, CompilationPhase) else phase
        return replace(self, phases=tuple(p for p in self.phases if p.context_type is not key))

    def replace_phase(
        self,
        old: CompilationPhase[Any] | type,
        new: CompilationPhase[Any],
    ) -> SchemaCompiler:
        """Replace by context_type match. Raises KeyError if not found."""
        key = old.context_type if isinstance(old, CompilationPhase) else old
        if not any(p.context_type is key for p in self.phases):
            raise KeyError(f"No phase with context_type {key.__name__}")
        return replace(self, phases=tuple(new if p.context_type is key else p for p in self.phases))

    # ─── Algebraic operations (keyed by context_type) ─────────────────

    def __add__(self, other: SchemaCompiler | CompilationPhase[Any]) -> SchemaCompiler:
        """Left-biased union. Idempotent: A + A == A."""
        if isinstance(other, CompilationPhase):
            other = SchemaCompiler(phases=(other,))
        seen = {p.context_type for p in self.phases}
        extra = tuple(p for p in other.phases if p.context_type not in seen)
        return SchemaCompiler(phases=(*self.phases, *extra))

    def __radd__(self, other: CompilationPhase[Any]) -> SchemaCompiler:
        return SchemaCompiler(phases=(other,)) + self

    def __or__(self, other: SchemaCompiler | CompilationPhase[Any]) -> SchemaCompiler:
        """Right-biased merge. Other's phases override self's by context_type."""
        if isinstance(other, CompilationPhase):
            other = SchemaCompiler(phases=(other,))
        override = {p.context_type: p for p in other.phases}
        self_keys = {p.context_type for p in self.phases}
        result = [override.get(p.context_type, p) for p in self.phases]
        for p in other.phases:
            if p.context_type not in self_keys:
                result.append(p)
        return SchemaCompiler(phases=tuple(result))

    def __ror__(self, other: CompilationPhase[Any]) -> SchemaCompiler:
        return SchemaCompiler(phases=(other,)) | self

    def __sub__(self, other: SchemaCompiler | CompilationPhase[Any] | type) -> SchemaCompiler:
        """Restriction — remove by context_type."""
        if isinstance(other, SchemaCompiler):
            remove_keys: set[type] = {p.context_type for p in other.phases}
        elif isinstance(other, CompilationPhase):
            remove_keys = {other.context_type}
        else:
            # other: type — bare context type class
            remove_keys = {other}
        return SchemaCompiler(phases=tuple(p for p in self.phases if p.context_type not in remove_keys))

    def __and__(self, other: SchemaCompiler) -> SchemaCompiler:
        """Intersection by context_type. Self's versions retained."""
        other_keys = {p.context_type for p in other.phases}
        return SchemaCompiler(phases=tuple(p for p in self.phases if p.context_type in other_keys))

    def __contains__(self, item: CompilationPhase[Any] | type) -> bool:
        """Membership by context_type. Accepts CompilationPhase or bare type."""
        if isinstance(item, CompilationPhase):
            return any(p.context_type is item.context_type for p in self.phases)
        return any(p.context_type is item for p in self.phases)

    def __len__(self) -> int:
        return len(self.phases)

    def __iter__(self) -> Iterator[CompilationPhase[Any]]:
        return iter(self.phases)

    def __bool__(self) -> bool:
        return len(self.phases) > 0

    def __getitem__(self, context_type: type) -> CompilationPhase[Any]:
        """Lookup phase by context_type. Raises KeyError if not found."""
        for p in self.phases:
            if p.context_type is context_type:
                return p
        raise KeyError(context_type)


# Pre-built schema compilers — lego pieces
FASTAPI_SCHEMA = SchemaCompiler(phases=FASTAPI_PHASES)
CLI_SCHEMA = SchemaCompiler(phases=CLI_PHASES)
TG_SCHEMA = SchemaCompiler(phases=TG_PHASES)
CONSTRAINTS_SCHEMA = SchemaCompiler(phases=(CONSTRAINTS_PHASE,))
STORAGE_SCHEMA = SchemaCompiler(phases=(STORAGE_FIELD_PHASE,))


# ═══════════════════════════════════════════════════════════════════════════════
# Universal Storage Operations — any backend
# ═══════════════════════════════════════════════════════════════════════════════


def to_storage_dict(
    entity: Any,
    fields: tuple[FieldCompilation, ...],
) -> dict[str, Any]:
    """Entity → storage dict. Applies to_storage coercion from STORAGE_FIELD_PHASE.

    Universal — SA, Mongo, Pandas, Redis all use this.

        data = to_storage_dict(user, compiled.fields)
        # SA:    model_cls(**data)
        # Mongo: collection.insert_one(data)
    """
    data: dict[str, Any] = {}
    for fc in fields:
        meta = fc[STORAGE_FIELD_PHASE]
        value = getattr(entity, fc.name)
        if meta.to_storage is not None:
            value = meta.to_storage(value)
        data[fc.name] = value
    return data


def from_storage[T](
    getter: Callable[[str], Any],
    entity_cls: type[T],
    fields: tuple[FieldCompilation, ...],
) -> T:
    """Storage → entity. Applies from_storage coercion from STORAGE_FIELD_PHASE.

    Universal — getter abstracts the backend:
        SA:     lambda n: getattr(model_instance, n)
        Mongo:  lambda n: doc[n]
        Pandas: lambda n: row[n]

    Auto-reconstructs Enum values from their stored representation.
    """
    from enum import Enum as _Enum

    data: dict[str, Any] = {}
    for fc in fields:
        meta = fc[STORAGE_FIELD_PHASE]
        value = getter(fc.name)
        if meta.from_storage is not None:
            value = meta.from_storage(value)
        # Reconstruct enums: storage returns raw str/int, entity expects Enum
        declared = fc.info.base_type
        if (
            isinstance(declared, type)
            and issubclass(declared, _Enum)
            and not isinstance(value, declared)
            and value is not None
        ):
            value = declared(value)
        data[fc.name] = value
    return entity_cls(**data)


def coerce_expr(
    expr: "Expr",
    fields: tuple[FieldCompilation, ...],
) -> "Expr":
    """Coerce query Expr values for storage. to_storage IS the query coercer.

    Universal — any backend with query support.
    """
    from emergent.wire.axis.query._coerce import ExprCoercer

    coercion: dict[str, Callable[[Any], Any]] = {}
    for fc in fields:
        meta = fc[STORAGE_FIELD_PHASE]
        if meta.to_storage is not None:
            coercion[fc.name] = meta.to_storage
    if not coercion:
        return expr
    return ExprCoercer(coercion)(expr)


__all__ = (
    # Core
    "EntityFold",
    "CompilationPhase",
    "FieldCompilation",
    "EntityCompilation",
    "compile_fields",
    "compile_entity",
    "Compilation",
    # Composable schema compiler
    "SchemaCompiler",
    # Universal storage operations
    "to_storage_dict",
    "from_storage",
    "coerce_expr",
    # Pre-built entity folds
    "PYDANTIC_MODEL_FOLD",
    "OPENAPI_SCHEMA_FOLD",
    # Pre-built phases
    "PYDANTIC_PHASE",
    "OPENAPI_PHASE",
    "ARGPARSE_PHASE",
    "REQUEST_BUILD_PHASE",
    "TG_INPUT_PHASE",
    "TG_RENDER_PHASE",
    "CONSTRAINTS_PHASE",
    "QUERY_SCHEMA_PHASE",
    "STORAGE_FIELD_PHASE",
    # Phase groups
    "FASTAPI_PHASES",
    "CLI_PHASES",
    "TG_PHASES",
    # Pre-built schema compilers
    "FASTAPI_SCHEMA",
    "CLI_SCHEMA",
    "TG_SCHEMA",
    "CONSTRAINTS_SCHEMA",
    "STORAGE_SCHEMA",
)

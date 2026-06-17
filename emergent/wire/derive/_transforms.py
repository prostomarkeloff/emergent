"""Derivation transforms — DeriveModifiable SchemaCapabilities.

All derivelib transforms expressed as capabilities using DeriveCtx methods.

    from emergent.wire.derive._transforms import (
        Paginated, Sorted, Readonly, MutationsOnly, WithoutDelete,
        Filtered, Searchable, ProjectResponse,
        WithTimeout, WithRetry, WithRateLimit, EffectRateLimited, EffectDeprecated,
    )

    @schema_meta(http_crud("/api/users", P), Paginated(50), Sorted("name"), Readonly())
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, TYPE_CHECKING, TypeGuard

from emergent.wire.axis.schema._universal import SchemaCapability
from emergent.wire.derive._effects import (
    DerivationEffect,
    Deletes,
    Filterable,
    Mutation,
    Pageable,
    Read,
    Searchable as SearchableEffect,
    Sortable,
    RateLimited as RateLimitedEffect,
    Deprecated as DeprecatedEffect,
    get_effect,
    has_effect,
)

if TYPE_CHECKING:
    from kungfu import Result

    from nodnod import Scope

    from emergent.wire.axis.query._expr import Expr
    from emergent.wire.axis.query._proxy import EntityProxy
    from emergent.wire.derive._ctx import DeriveCtx, OperationHandler
    from emergent.wire.derive._errors import DomainError
    from emergent.wire.derive._handler import HandlerSpec
    from emergent.wire.derive._opspec import OpSpec


def _is_list_of_objects(val: Any) -> TypeGuard[list[Any]]:
    """TypeGuard that narrows object to list[object] instead of list[Unknown].

    isinstance(x, list) narrows to list[Unknown] in pyright strict mode,
    making all element access produce Unknown-typed values. This TypeGuard
    avoids that by narrowing directly to list[object].
    """
    return isinstance(val, list)


# ═══════════════════════════════════════════════════════════════════════════════
# Wrapper helpers — proper WrapperFn-satisfying classes for in-memory transforms
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class _FilterWrapperFn:
    """WrapperFn for in-memory field filtering."""

    fields: tuple[str, ...]

    def __call__[EntityT](
        self,
        inner: OperationHandler[object, DomainError],
        spec: HandlerSpec[EntityT],
    ) -> OperationHandler[object, DomainError]:
        ff = self.fields

        async def handler(**kwargs: object) -> Result[object, DomainError]:
            from kungfu import Ok

            result: Result[object, DomainError] = await inner(**kwargs)
            if not isinstance(result, Ok):
                return result
            val = result.value
            if not _is_list_of_objects(val):
                return result
            op = kwargs.get("op")
            filtered: list[object] = val
            for fname in ff:
                fval = getattr(op, f"filter_{fname}", None)
                if fval is not None:
                    filtered = [
                        item for item in filtered
                        if str(getattr(item, fname, "")) == str(fval)
                    ]
            return Ok(filtered)

        return handler


@dataclass(frozen=True, slots=True)
class _SearchWrapperFn:
    """WrapperFn for in-memory full-text search."""

    fields: tuple[str, ...]

    def __call__[EntityT](
        self,
        inner: OperationHandler[object, DomainError],
        spec: HandlerSpec[EntityT],
    ) -> OperationHandler[object, DomainError]:
        sf = self.fields

        async def handler(**kwargs: object) -> Result[object, DomainError]:
            from kungfu import Ok

            result: Result[object, DomainError] = await inner(**kwargs)
            if not isinstance(result, Ok):
                return result
            op = kwargs.get("op")
            q_val: str | None = getattr(op, "q", None) if op is not None else None
            if q_val is None:
                return result
            val = result.value
            if not _is_list_of_objects(val):
                return result
            q_lower = str(q_val).lower()
            matched: list[object] = [
                item for item in val
                if any(q_lower in str(getattr(item, f, "")).lower() for f in sf)
            ]
            return Ok(matched)

        return handler


# ═══════════════════════════════════════════════════════════════════════════════
# Query Enrichment Transforms
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Paginated(SchemaCapability):
    """Replace Pageable ops with paginated handler + response.

        @schema_meta(http_crud("/api/users", P), Paginated(50))
    """

    page_size: int = 20

    def compile_derive_modify[T](self, ctx: DeriveCtx[T]) -> DeriveCtx[T]:
        from emergent.wire.derive._handler import PaginatedFetchMany
        from emergent.wire.derive._project import PaginatedResponse

        new_specs: list[OpSpec] = []
        for s in ctx.specs:
            if has_effect(s.effects, Pageable):
                eff = get_effect(s.effects, Pageable)
                size = self.page_size or (eff.default_size if eff else 20)
                s = replace(
                    s,
                    handler_template=PaginatedFetchMany(page_size=size),
                    response_spec=PaginatedResponse(),
                    extra_op_fields=(
                        *s.extra_op_fields,
                        ("page", int, 1), ("page_size", int, size),
                    ),
                    extra_request_fields=(
                        *s.extra_request_fields,
                        ("page", int, 1), ("page_size", int, size),
                    ),
                )
            new_specs.append(s)
        return replace(ctx, specs=tuple(new_specs))


@dataclass(frozen=True, slots=True)
class Sorted(SchemaCapability):
    """Replace Sortable ops with sorted handler.

        @schema_meta(http_crud("/api/users", P), Sorted("name", "desc"))
    """

    default_sort: str | None = None
    default_order: str = "asc"

    def compile_derive_modify[T](self, ctx: DeriveCtx[T]) -> DeriveCtx[T]:
        from emergent.wire.derive._handler import SortedFetchMany

        new_specs: list[OpSpec] = []
        for s in ctx.specs:
            if has_effect(s.effects, Sortable):
                eff = get_effect(s.effects, Sortable)
                sort = self.default_sort or (eff.default_field if eff else None)
                order = self.default_order or (eff.default_order if eff else "asc")
                s = replace(
                    s,
                    handler_template=SortedFetchMany(
                        default_sort=sort,
                        default_order=order,
                    ),
                    extra_op_fields=(
                        *s.extra_op_fields,
                        ("sort", str, sort or ""), ("order", str, order),
                    ),
                    extra_request_fields=(
                        *s.extra_request_fields,
                        ("sort", str, sort or ""), ("order", str, order),
                    ),
                )
            new_specs.append(s)
        return replace(ctx, specs=tuple(new_specs))


# ═══════════════════════════════════════════════════════════════════════════════
# Effect-Based Filters
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Readonly(SchemaCapability):
    """Remove mutation operations. Keep reads only.

        @schema_meta(http_crud("/api/users", P), Readonly())
    """

    def compile_derive_modify[T](self, ctx: DeriveCtx[T]) -> DeriveCtx[T]:
        return ctx.reject_by_effect(Mutation)


@dataclass(frozen=True, slots=True)
class MutationsOnly(SchemaCapability):
    """Keep only mutation operations. Remove reads.

        @schema_meta(http_crud("/api/users", P), MutationsOnly())
    """

    def compile_derive_modify[T](self, ctx: DeriveCtx[T]) -> DeriveCtx[T]:
        return ctx.select_by_effect(Mutation)


@dataclass(frozen=True, slots=True)
class WithoutDelete(SchemaCapability):
    """Remove delete operations.

        @schema_meta(http_crud("/api/users", P), WithoutDelete())
    """

    def compile_derive_modify[T](self, ctx: DeriveCtx[T]) -> DeriveCtx[T]:
        return ctx.reject_by_effect(Deletes)


# ═══════════════════════════════════════════════════════════════════════════════
# Response Projection
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class ProjectResponse(SchemaCapability):
    """Exclude fields from response on Read ops.

        @schema_meta(http_crud("/api/users", P), ProjectResponse(exclude=("secret",)))
    """

    exclude: tuple[str, ...]
    effect: type[DerivationEffect] = Read

    def compile_derive_modify[T](self, ctx: DeriveCtx[T]) -> DeriveCtx[T]:
        from emergent.wire.derive._project import EntityResponse, ListResponse

        exclude = self.exclude

        def _project(s: OpSpec) -> OpSpec:
            if isinstance(s.response_spec, ListResponse):
                return replace(s, response_spec=ListResponse(exclude=exclude))
            if isinstance(s.response_spec, EntityResponse):
                return replace(s, response_spec=EntityResponse(exclude=exclude))
            return s

        return ctx.map_specs_by_effect(self.effect, _project)


# ═══════════════════════════════════════════════════════════════════════════════
# In-Memory Filtering & Search
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Filtered(SchemaCapability):
    """Add field filtering to Read ops.

    WARNING: Filtering is done IN-MEMORY after fetching all data.

    Explicit fields → all Read ops. No fields → only Filterable ops.

        @schema_meta(http_crud("/api/users", P), Filtered("name", "status"))
    """

    fields: tuple[str, ...] = ()

    def compile_derive_modify[T](self, ctx: DeriveCtx[T]) -> DeriveCtx[T]:
        from emergent.wire.derive._handler import WrappedTemplate

        new_specs: list[OpSpec] = []
        for s in ctx.specs:
            if not has_effect(s.effects, Read):
                new_specs.append(s)
                continue

            ffields = self.fields
            if not ffields:
                eff = get_effect(s.effects, Filterable)
                if eff is None:
                    new_specs.append(s)
                    continue
                ffields = eff.fields

            if not ffields:
                new_specs.append(s)
                continue

            filter_params = tuple(
                (f"filter_{name}", str | None, None) for name in ffields
            )

            s = replace(
                s,
                extra_op_fields=(*s.extra_op_fields, *filter_params),
                extra_request_fields=(*s.extra_request_fields, *filter_params),
                handler_template=WrappedTemplate(
                    inner=s.handler_template,
                    wrapper=_FilterWrapperFn(fields=ffields),
                ),
            )
            new_specs.append(s)
        return replace(ctx, specs=tuple(new_specs))


@dataclass(frozen=True, slots=True)
class Searchable(SchemaCapability):
    """Add full-text search to Read ops.

    WARNING: Search is done IN-MEMORY after fetching all data.

    Explicit fields → all Read ops. No fields → only Searchable ops.

        @schema_meta(http_crud("/api/users", P), Searchable("name", "bio"))
    """

    fields: tuple[str, ...] = ()

    def compile_derive_modify[T](self, ctx: DeriveCtx[T]) -> DeriveCtx[T]:
        from emergent.wire.derive._handler import WrappedTemplate

        new_specs: list[OpSpec] = []
        for s in ctx.specs:
            if not has_effect(s.effects, Read):
                new_specs.append(s)
                continue

            sfields = self.fields
            if not sfields:
                eff = get_effect(s.effects, SearchableEffect)
                if eff is None:
                    new_specs.append(s)
                    continue
                sfields = eff.fields

            if not sfields:
                new_specs.append(s)
                continue

            s = replace(
                s,
                extra_op_fields=(*s.extra_op_fields, ("q", str | None, None)),
                extra_request_fields=(*s.extra_request_fields, ("q", str | None, None)),
                handler_template=WrappedTemplate(
                    inner=s.handler_template,
                    wrapper=_SearchWrapperFn(fields=sfields),
                ),
            )
            new_specs.append(s)
        return replace(ctx, specs=tuple(new_specs))


# ═══════════════════════════════════════════════════════════════════════════════
# Enricher Transforms
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class WithTimeout(SchemaCapability):
    """Add Timeout enricher to all operations.

        @schema_meta(http_crud("/api/users", P), WithTimeout(30.0))
    """

    seconds: float

    def compile_derive_modify[T](self, ctx: DeriveCtx[T]) -> DeriveCtx[T]:
        from emergent.wire.axis.surface.enrichers import Timeout

        return ctx.add_spec_capability(Timeout(seconds=self.seconds))


@dataclass(frozen=True, slots=True)
class WithRetry(SchemaCapability):
    """Add Retry enricher to mutation operations.

        @schema_meta(http_crud("/api/users", P), WithRetry(3))
    """

    max_retries: int = 3

    def compile_derive_modify[T](self, ctx: DeriveCtx[T]) -> DeriveCtx[T]:
        from combinators.control import RetryPolicy
        from emergent.wire.axis.surface.enrichers import Retry

        return ctx.add_spec_capability(
            Retry(policy=RetryPolicy[Exception].fixed(times=self.max_retries)),
            Mutation,
        )


@dataclass(frozen=True, slots=True)
class WithRateLimit(SchemaCapability):
    """Add RateLimit enricher to ALL operations unconditionally.

        @schema_meta(http_crud("/api/users", P), WithRateLimit(rpm=60))
    """

    rpm: int

    def compile_derive_modify[T](self, ctx: DeriveCtx[T]) -> DeriveCtx[T]:
        from combinators.concurrency import RateLimitPolicy
        from emergent.wire.axis.surface.enrichers import RateLimit

        return ctx.add_spec_capability(
            RateLimit(policy=RateLimitPolicy(max_per_second=self.rpm / 60.0))
        )


@dataclass(frozen=True, slots=True)
class EffectRateLimited(SchemaCapability):
    """Add rate limiting to ops declaring RateLimited effect.

    Different from WithRateLimit which applies to ALL ops unconditionally.

        @schema_meta(http_crud("/api/users", P), EffectRateLimited())
    """

    rpm: int | None = None

    def compile_derive_modify[T](self, ctx: DeriveCtx[T]) -> DeriveCtx[T]:
        from combinators.concurrency import RateLimitPolicy
        from emergent.wire.axis.surface.enrichers import RateLimit

        new_specs: list[OpSpec] = []
        for s in ctx.specs:
            eff = get_effect(s.effects, RateLimitedEffect)
            rate = self.rpm if self.rpm is not None else (eff.rpm if eff else None)
            if rate is not None:
                cap = RateLimit(policy=RateLimitPolicy(max_per_second=rate / 60.0))
                s = replace(s, capabilities=(*s.capabilities, cap))
            new_specs.append(s)
        return replace(ctx, specs=tuple(new_specs))


@dataclass(frozen=True, slots=True)
class EffectDeprecated(SchemaCapability):
    """Add deprecation warning to ops declaring Deprecated effect.

        @schema_meta(http_crud("/api/users", P), EffectDeprecated())
    """

    def compile_derive_modify[T](self, ctx: DeriveCtx[T]) -> DeriveCtx[T]:
        from emergent.wire.axis.surface.capabilities import ScopeEnricher, EnricherNext

        @dataclass(frozen=True, slots=True)
        class DeprecationInfo:
            since: str = ""
            message: str = ""

        @dataclass(frozen=True, slots=True)
        class DeprecationEnricher(ScopeEnricher):
            since: str = ""
            message: str = ""

            async def enrich[R](self, call: EnricherNext[R], scope: Scope) -> R:
                scope.inject(DeprecationInfo, DeprecationInfo(since=self.since, message=self.message))
                return await call(scope)

        new_specs: list[OpSpec] = []
        for s in ctx.specs:
            eff = get_effect(s.effects, DeprecatedEffect)
            if eff is not None:
                enricher = DeprecationEnricher(since=eff.since, message=eff.message)
                s = replace(s, capabilities=(*s.capabilities, enricher))
            new_specs.append(s)
        return replace(ctx, specs=tuple(new_specs))


# ═══════════════════════════════════════════════════════════════════════════════
# Composed Transforms — wire up existing handlers into higher-level patterns
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class SoftDelete(SchemaCapability):
    """Replace hard delete with soft-delete (set deleted_at, filter query).

        @schema_meta(http_crud("/api/users", P), SoftDelete())
    """

    deleted_field: str = "deleted_at"

    def compile_derive_modify[T](self, ctx: DeriveCtx[T]) -> DeriveCtx[T]:
        from emergent.wire.derive._effects import Creates
        from emergent.wire.derive._handler import SoftDeleteMark

        field = self.deleted_field
        ctx = ctx.replace_handler(Deletes, SoftDeleteMark(field))

        def _soft_delete_filter(e: EntityProxy[T]) -> Expr:
            from emergent.wire.axis.query._proxy import FieldProxy

            proxy: FieldProxy = getattr(e, field)
            return proxy.is_null()

        ctx = ctx.filter_query(_soft_delete_filter)
        return ctx.exclude_fields(Creates, frozenset({field}))


@dataclass(frozen=True, slots=True)
class Timestamped(SchemaCapability):
    """Auto-set created_at/updated_at on create and update.

        @schema_meta(http_crud("/api/users", P), Timestamped())
    """

    created_field: str = "created_at"
    updated_field: str = "updated_at"

    def compile_derive_modify[T](self, ctx: DeriveCtx[T]) -> DeriveCtx[T]:
        from emergent.wire.derive._effects import Creates, Updates
        from emergent.wire.derive._handler import TimestampInsert, TimestampUpdate

        cf, uf = self.created_field, self.updated_field
        ctx = ctx.replace_handler(Creates, TimestampInsert(cf, uf))
        ctx = ctx.replace_handler(Updates, TimestampUpdate(uf))
        return ctx.exclude_fields(Creates, frozenset({cf, uf}))


# ═══════════════════════════════════════════════════════════════════════════════
# Additional Effect-Based Filters
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class WithoutCreate(SchemaCapability):
    """Remove create operations.

        @schema_meta(http_crud("/api/users", P), WithoutCreate())
    """

    def compile_derive_modify[T](self, ctx: DeriveCtx[T]) -> DeriveCtx[T]:
        from emergent.wire.derive._effects import Creates

        return ctx.reject_by_effect(Creates)


@dataclass(frozen=True, slots=True)
class CreateOnly(SchemaCapability):
    """Keep only create operations.

        @schema_meta(http_crud("/api/users", P), CreateOnly())
    """

    def compile_derive_modify[T](self, ctx: DeriveCtx[T]) -> DeriveCtx[T]:
        from emergent.wire.derive._effects import Creates

        return ctx.select_by_effect(Creates)


@dataclass(frozen=True, slots=True)
class UpdateOnly(SchemaCapability):
    """Keep only update operations.

        @schema_meta(http_crud("/api/users", P), UpdateOnly())
    """

    def compile_derive_modify[T](self, ctx: DeriveCtx[T]) -> DeriveCtx[T]:
        from emergent.wire.derive._effects import Updates

        return ctx.select_by_effect(Updates)


@dataclass(frozen=True, slots=True)
class OnlyOps(SchemaCapability):
    """Keep only operations matching given names.

        @schema_meta(http_crud("/api/users", P), OnlyOps(("List", "Get")))
    """

    ops: tuple[str, ...]

    def compile_derive_modify[T](self, ctx: DeriveCtx[T]) -> DeriveCtx[T]:
        allowed = frozenset(self.ops)
        return replace(ctx, specs=tuple(s for s in ctx.specs if s.name in allowed))


__all__ = (
    # Query enrichment
    "Paginated",
    "Sorted",
    # Effect filters
    "Readonly",
    "MutationsOnly",
    "WithoutDelete",
    "WithoutCreate",
    "CreateOnly",
    "UpdateOnly",
    "OnlyOps",
    # Response projection
    "ProjectResponse",
    # Composed transforms
    "SoftDelete",
    "Timestamped",
    # In-memory filtering & search
    "Filtered",
    "Searchable",
    # Enrichers
    "WithTimeout",
    "WithRetry",
    "WithRateLimit",
    # Effect-aware
    "EffectRateLimited",
    "EffectDeprecated",
)

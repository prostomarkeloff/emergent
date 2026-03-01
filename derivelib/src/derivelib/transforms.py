"""Derivation transforms — fold-based dispatch on effects.

Primitives (fold-based, same pattern as adapt._fold_caps):

    reject_by_effect(Mutation)      — remove steps with effect
    select_by_effect(Mutation)      — keep only steps with effect
    map_by_effect({Mutation: fn})   — fold effects → transform steps
    map_all_ops(fn)                 — transform all DeriveOp steps

Semantic transforms (thin wrappers over primitives):

    readonly()                      — reject_by_effect(Mutation)
    mutations_only()                — select_by_effect(Mutation)
    without_delete()                — reject_by_effect(Deletes)
    add_capability(cap, Mutation)   — map_by_effect + add cap
    paginated(20)                   — map_by_effect on FetchMany handler

Use with Dialect.chain() for pattern composition:

    @derive(
        http_crud("/api/users", provider_node=Users)
            .chain(readonly(), paginated(20))
    )
    @dataclass
    class User: ...
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from typing import Any, TYPE_CHECKING

from derivelib._derivation import Derivation, DerivationT, Step
from derivelib._dialect import Op
from derivelib._effects import (
    Deprecated,
    DerivationEffect,
    Deletes,
    Filterable,
    Mutation,
    Pageable,
    RateLimited,
    Read,
    Searchable,
    Sortable,
    has_effect,
    get_effect,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Fold Primitives — effect-dispatched DerivationT constructors
# ═══════════════════════════════════════════════════════════════════════════════


from derivelib._protocols import TransformableStep as _Transformable, replace_caps
from derivelib.axes.surface import DeriveOp as _DeriveOp

if TYPE_CHECKING:
    from kungfu import Result
    from nodnod import Scope

    from emergent.wire.axis.surface import Trigger
    from emergent.wire.axis.surface.capabilities import SurfaceCapability

    from derivelib._ctx import OperationHandler
    from derivelib._errors import DomainError
    from derivelib._protocols import HandlerSpec, HandlerTemplate, HasProvider, WrapperFn

type EffectHandler[S: _Transformable] = Callable[[DerivationEffect, S], S | None]


def _fold_effects[S: _Transformable](
    effects: tuple[DerivationEffect, ...],
    step: S,
    handlers: dict[type, EffectHandler[S]],
) -> S | None:
    """Dispatch step's effects through handler table via isinstance.

    Supports effect hierarchy: Creates extends Mutation, so
    handlers={Mutation: fn} matches effects=(Creates(),).

    First matching (effect, handler) pair wins.
    Handler returns None → step dropped. No match → step unchanged.
    """
    for eff in effects:
        for handler_type, handler_fn in handlers.items():
            if isinstance(eff, handler_type):
                return handler_fn(eff, step)
    return step


def map_by_effect(
    handlers: dict[type, EffectHandler[_Transformable]],
) -> DerivationT:
    """Fold-based DerivationT: dispatch on effects through handler table.

    For each TransformableStep, fold its effects. First matching handler transforms it.
    Handler returns None → step removed. No match → step unchanged.
    Non-transformable steps pass through.

        from derivelib._effects import Mutation
        from derivelib.transforms import map_by_effect

        # Double capabilities on mutations:
        map_by_effect({Mutation: lambda eff, op: replace_caps(op, (*op.capabilities, extra))})
    """
    def transform(steps: Derivation) -> Derivation:
        result: list[Step] = []
        for s in steps:
            if isinstance(s, _Transformable):
                out = _fold_effects(s.effects, s, handlers)
                if out is not None:
                    result.append(out)
            else:
                result.append(s)
        return tuple(result)
    return transform


def reject_by_effect(*effect_types: type[DerivationEffect]) -> DerivationT:
    """Remove TransformableStep steps that have any of the given effects.

    Non-transformable steps pass through.

        reject_by_effect(Mutation)           # remove all mutations
        reject_by_effect(Mutation, Deletes)  # remove mutations OR deletes
    """
    handlers: dict[type, EffectHandler[_Transformable]] = {
        et: lambda _eff, _op: None for et in effect_types
    }
    return map_by_effect(handlers)


def select_by_effect(*effect_types: type[DerivationEffect]) -> DerivationT:
    """Keep only TransformableStep steps that have any of the given effects.

    Non-transformable steps (preamble) always pass through.

        select_by_effect(Mutation)  # keep only mutations
        select_by_effect(Read)      # keep only reads
    """
    type_set = set(effect_types)

    def transform(steps: Derivation) -> Derivation:
        return tuple(
            s for s in steps
            if not isinstance(s, _Transformable)
            or any(has_effect(s.effects, et) for et in type_set)
        )
    return transform


def map_all_ops(fn: Callable[[_DeriveOp], _DeriveOp]) -> DerivationT:
    """Transform all DeriveOp steps. Non-DeriveOp steps pass through.

        map_all_ops(lambda op: replace(op, capabilities=(*op.capabilities, cap)))
    """
    def transform(steps: Derivation) -> Derivation:
        from derivelib.axes.surface import DeriveOp

        return tuple(fn(s) if isinstance(s, DeriveOp) else s for s in steps)
    return transform


# ═══════════════════════════════════════════════════════════════════════════════
# Semantic Transforms — thin wrappers over fold primitives
# ═══════════════════════════════════════════════════════════════════════════════


def readonly() -> DerivationT:
    """Remove mutation operations. Keep reads + non-DeriveOp steps."""
    return reject_by_effect(Mutation)


def mutations_only() -> DerivationT:
    """Keep only mutation operations + non-DeriveOp steps."""
    return select_by_effect(Mutation)


def without_delete() -> DerivationT:
    """Remove delete operations."""
    return reject_by_effect(Deletes)


def without_ops(*ops: Op) -> DerivationT:
    """Remove operations by Op identity.

        from derivelib.patterns.crud import DELETE
        .chain(without_ops(DELETE))
    """
    def transform(steps: Derivation) -> Derivation:
        from derivelib.axes.surface import DeriveOp
        return tuple(
            s for s in steps
            if not isinstance(s, DeriveOp) or not any(s.source is o for o in ops)
        )
    return transform


def only_ops(*ops: Op) -> DerivationT:
    """Keep only given operations + non-DeriveOp steps.

        from derivelib.patterns.crud import LIST, GET
        .chain(only_ops(LIST, GET))
    """
    def transform(steps: Derivation) -> Derivation:
        from derivelib.axes.surface import DeriveOp
        return tuple(
            s for s in steps
            if not isinstance(s, DeriveOp) or any(s.source is o for o in ops)
        )
    return transform


# ═══════════════════════════════════════════════════════════════════════════════
# Capability Injection — fold-based
# ═══════════════════════════════════════════════════════════════════════════════


def project_response(
    exclude: tuple[str, ...],
    effect: type[DerivationEffect] = Read,
) -> DerivationT:
    """Exclude fields from response on operations with given effect.

    Replaces EntityResponse/ListResponse with projected versions.
    Other ResponseSpec types pass through unchanged.

        .chain(project_response(exclude=("active_at",)))
        .chain(project_response(exclude=("secret",), effect=Read))
    """
    from derivelib._project import EntityResponse, ListResponse

    def _project(_eff: DerivationEffect, op: _DeriveOp) -> _DeriveOp:
        if isinstance(op.output, ListResponse):
            return replace(op, output=ListResponse(exclude=exclude))
        if isinstance(op.output, EntityResponse):
            return replace(op, output=EntityResponse(exclude=exclude))
        return op

    return map_by_effect({effect: _project})


def wrap_by_effect(
    effect: type[DerivationEffect],
    make_wrapper: Callable[[_DeriveOp], WrapperFn],
) -> DerivationT:
    """Wrap handler templates on ops with given effect.

    make_wrapper receives the DeriveOp and returns a wrapper function
    compatible with WrappedTemplate (inner, spec) -> handler.

        wrap_by_effect(Mutation, lambda op: my_wrapper_factory(op.name))
    """
    from derivelib._protocols import WrappedTemplate

    def _wrap(_eff: DerivationEffect, op: _DeriveOp) -> _DeriveOp:
        return replace(
            op,
            handler_template=WrappedTemplate(
                inner=op.handler_template,
                wrapper=make_wrapper(op),
            ),
        )

    return map_by_effect({effect: _wrap})


def map_all_transformable(fn: Callable[[_Transformable], _Transformable]) -> DerivationT:
    """Transform all TransformableStep steps. Non-transformable steps pass through.

        map_all_transformable(lambda s: replace_caps(s, (*s.capabilities, cap)))
    """
    def transform(steps: Derivation) -> Derivation:
        return tuple(fn(s) if isinstance(s, _Transformable) else s for s in steps)
    return transform


def add_capability(
    cap: SurfaceCapability,
    effect: type[DerivationEffect] | None = None,
) -> DerivationT:
    """Add capability to TransformableStep steps, optionally filtered by effect type.

        # All transformable steps:
        .chain(add_capability(CORSCap()))

        # Only mutations:
        .chain(add_capability(AuthCap(), Mutation))
    """
    def _add(_eff: DerivationEffect, s: _Transformable) -> _Transformable:
        return replace_caps(s, (*s.capabilities, cap))

    if effect is None:
        return map_all_transformable(lambda s: replace_caps(s, (*s.capabilities, cap)))
    return map_by_effect({effect: _add})


# ═══════════════════════════════════════════════════════════════════════════════
# Handler / Trigger Swaps
# ═══════════════════════════════════════════════════════════════════════════════


def swap_handler(op: Op, new_template: HandlerTemplate) -> DerivationT:
    """Replace handler template on a DeriveOp by Op identity.

        from derivelib.patterns.crud import DELETE
        .chain(swap_handler(DELETE, SoftDeleteMark()))
    """
    def transform(steps: Derivation) -> Derivation:
        from derivelib.axes.surface import DeriveOp
        return tuple(
            replace(s, handler_template=new_template)
            if isinstance(s, DeriveOp) and s.source is op
            else s
            for s in steps
        )
    return transform


def swap_trigger(op: Op, new_trigger: Trigger) -> DerivationT:
    """Replace trigger on a DeriveOp by Op identity.

        from derivelib.patterns.crud import GET
        .chain(swap_trigger(GET, CLITrigger("fetch")))
    """
    def transform(steps: Derivation) -> Derivation:
        from derivelib.axes.surface import DeriveOp
        return tuple(
            replace(s, trigger=new_trigger)
            if isinstance(s, DeriveOp) and s.source is op
            else s
            for s in steps
        )
    return transform


def rename_ops(mapping: dict[Op, str]) -> DerivationT:
    """Rename operations by Op identity.

        from derivelib.patterns.crud import LIST, GET
        .chain(rename_ops({LIST: "Search", GET: "Fetch"}))
    """
    def transform(steps: Derivation) -> Derivation:
        from derivelib.axes.surface import DeriveOp
        result: list[Step] = []
        for s in steps:
            if isinstance(s, DeriveOp):
                for src_op, new_name in mapping.items():
                    if s.source is src_op:
                        s = replace(s, name=new_name)
                        break
            result.append(s)
        return tuple(result)
    return transform


# ═══════════════════════════════════════════════════════════════════════════════
# Query Enrichment Transforms
# ═══════════════════════════════════════════════════════════════════════════════


def paginated(page_size: int | None = None) -> DerivationT:
    """Replace handler with PaginatedFetchMany on ops declaring Pageable effect.

    page_size arg overrides effect default. If None, reads from Pageable.default_size.

        .chain(paginated())      # use effect default (Pageable.default_size)
        .chain(paginated(50))    # explicit override
    """
    def transform(steps: Derivation) -> Derivation:
        from derivelib.axes.surface import DeriveOp
        from derivelib._handler_templates import PaginatedFetchMany
        from derivelib._project import PaginatedResponse

        result: list[Step] = []
        for s in steps:
            if isinstance(s, DeriveOp) and has_effect(s.effects, Pageable):
                eff = get_effect(s.effects, Pageable)
                size = page_size if page_size is not None else (eff.default_size if eff else 20)
                scope = getattr(s.handler_template, "scope_fields", ())
                s = replace(
                    s,
                    handler_template=PaginatedFetchMany(
                        page_size=size,
                        scope_fields=scope,
                    ),
                    output=PaginatedResponse(),
                    extra_op_fields=(
                        *s.extra_op_fields,
                        ("page", int), ("page_size", int),
                    ),
                    extra_request_fields=(
                        *s.extra_request_fields,
                        ("page", int), ("page_size", int),
                    ),
                )
            result.append(s)
        return tuple(result)
    return transform


def sorted_list(default_sort: str | None = None, default_order: str | None = None) -> DerivationT:
    """Add sort parameters and sorting handler to ops declaring Sortable effect.

    Replaces handler with SortedFetchMany that sorts in-memory after fetch.
    Args override effect defaults. If None, reads from Sortable.default_field/default_order.

        .chain(sorted_list())                  # use effect defaults
        .chain(sorted_list("name", "desc"))    # explicit override
    """
    def transform(steps: Derivation) -> Derivation:
        from derivelib.axes.surface import DeriveOp
        from derivelib._handler_templates import SortedFetchMany

        result: list[Step] = []
        for s in steps:
            if isinstance(s, DeriveOp) and has_effect(s.effects, Sortable):
                eff = get_effect(s.effects, Sortable)
                sort = default_sort or (eff.default_field if eff else None)
                order = default_order or (eff.default_order if eff else "asc")
                scope = getattr(s.handler_template, "scope_fields", ())
                s = replace(
                    s,
                    handler_template=SortedFetchMany(
                        default_sort=sort,
                        default_order=order,
                        scope_fields=scope,
                    ),
                    extra_op_fields=(
                        *s.extra_op_fields,
                        ("sort", str), ("order", str),
                    ),
                    extra_request_fields=(
                        *s.extra_request_fields,
                        ("sort", str), ("order", str),
                    ),
                )
            result.append(s)
        return tuple(result)
    return transform


# ═══════════════════════════════════════════════════════════════════════════════
# Enricher Transforms (wire ScopeEnricher capabilities)
# ═══════════════════════════════════════════════════════════════════════════════


def with_timeout(seconds: float) -> DerivationT:
    """Add Timeout enricher to all operations."""
    from emergent.wire.axis.surface.enrichers import Timeout
    return add_capability(Timeout(seconds=seconds))


def with_retry(max_retries: int = 3) -> DerivationT:
    """Add Retry enricher to mutation operations."""
    from combinators.control import RetryPolicy
    from emergent.wire.axis.surface.enrichers import Retry
    return add_capability(Retry(policy=RetryPolicy[Exception].fixed(times=max_retries)), Mutation)


def with_rate_limit(rpm: int) -> DerivationT:
    """Add RateLimit enricher to ALL operations unconditionally.

    See also: rate_limited() — only targets ops declaring RateLimited effect.
    """
    from combinators.concurrency import RateLimitPolicy
    from emergent.wire.axis.surface.enrichers import RateLimit
    return add_capability(RateLimit(policy=RateLimitPolicy(max_per_second=rpm / 60.0)))


# ═══════════════════════════════════════════════════════════════════════════════
# Effect-Aware Transforms — dispatch on new effects
# ═══════════════════════════════════════════════════════════════════════════════


def _filter_list(items: Any, filter_fields: tuple[str, ...], op: Any) -> Any:
    """Post-filter list items by field values from op.

    Any: isinstance(EntityT, list) narrows to list[Unknown]; element types
    are unrecoverable from a type parameter. Any breaks the Unknown chain.
    """
    filtered: Any = list(items)
    for fname in filter_fields:
        fval = getattr(op, f"filter_{fname}", None)
        if fval is not None:
            filtered = [
                e for e in filtered
                if str(getattr(e, fname, "")) == str(fval)
            ]
    return filtered


def _make_filter_wrapper(
    filter_fields: tuple[str, ...],
) -> WrapperFn:
    """Build WrappedTemplate wrapper that post-filters results by field values."""
    from kungfu import Ok

    def wrapper[EntityT](
        inner: OperationHandler[EntityT, DomainError],
        spec: HandlerSpec[EntityT],
    ) -> OperationHandler[EntityT, DomainError]:
        async def handler(op: HasProvider[EntityT]) -> Result[EntityT, DomainError]:
            result = await inner(op=op)
            if not isinstance(result, Ok):
                return result

            val = result.value
            if not isinstance(val, list):
                return result

            return Ok(_filter_list(val, filter_fields, op))

        return handler

    return wrapper


def filtered(*fields: str) -> DerivationT:
    """Add field filtering to Read ops.

    WARNING: Filtering is done IN-MEMORY after fetching all data.
    Not suitable for large datasets. For production use with large tables,
    implement query-level filtering in a custom handler template.

    Explicit fields → all Read ops. No fields → only Filterable ops, reads from effect.
    Adds optional filter_{field} query params. Wraps handler to post-filter.

        .chain(filtered("name", "status"))
        .chain(filtered())  # from Filterable effect
    """
    def transform(steps: Derivation) -> Derivation:
        from derivelib.axes.surface import DeriveOp
        from derivelib._protocols import WrappedTemplate

        result: list[Step] = []
        for s in steps:
            if not isinstance(s, DeriveOp) or not has_effect(s.effects, Read):
                result.append(s)
                continue

            # Determine filter fields: explicit args or from effect
            if fields:
                ffields = fields
            else:
                eff = get_effect(s.effects, Filterable)
                if eff is None:
                    result.append(s)
                    continue
                ffields = eff.fields

            if not ffields:
                result.append(s)
                continue

            # Add filter_{name} optional params
            filter_params = tuple(
                (f"filter_{name}", str | None) for name in ffields
            )
            s = replace(
                s,
                extra_op_fields=(*s.extra_op_fields, *filter_params),
                extra_request_fields=(*s.extra_request_fields, *filter_params),
                handler_template=WrappedTemplate(
                    inner=s.handler_template,
                    wrapper=_make_filter_wrapper(ffields),
                ),
            )
            result.append(s)
        return tuple(result)
    return transform


def _search_list(items: Any, q_lower: str, search_fields: tuple[str, ...]) -> Any:
    """Search list items across fields for query match.

    Any: isinstance(EntityT, list) narrows to list[Unknown]; element types
    are unrecoverable from a type parameter. Any breaks the Unknown chain.
    """
    return [
        e for e in items
        if any(
            q_lower in str(getattr(e, f, "")).lower()
            for f in search_fields
        )
    ]


def _make_search_wrapper(
    search_fields: tuple[str, ...],
) -> WrapperFn:
    """Build WrappedTemplate wrapper that searches across fields."""
    from kungfu import Ok

    def wrapper[EntityT](
        inner: OperationHandler[EntityT, DomainError],
        spec: HandlerSpec[EntityT],
    ) -> OperationHandler[EntityT, DomainError]:
        async def handler(op: HasProvider[EntityT]) -> Result[EntityT, DomainError]:
            result = await inner(op=op)
            if not isinstance(result, Ok):
                return result

            q = getattr(op, "q", None)
            if q is None:
                return result

            val = result.value
            if not isinstance(val, list):
                return result

            return Ok(_search_list(val, str(q).lower(), search_fields))

        return handler

    return wrapper


def searchable(*fields: str) -> DerivationT:
    """Add full-text search to Read ops.

    WARNING: Search is done IN-MEMORY after fetching all data.
    Not suitable for large datasets. For production use with large tables,
    implement query-level search in a custom handler template.

    Adds ?q= query param. Wraps handler to filter items where any
    searchable field contains the query string (case-insensitive).

    Explicit fields → all Read ops. No fields → only Searchable ops.

        .chain(searchable("name", "bio"))
        .chain(searchable())  # from Searchable effect
    """
    def transform(steps: Derivation) -> Derivation:
        from derivelib.axes.surface import DeriveOp
        from derivelib._protocols import WrappedTemplate

        result: list[Step] = []
        for s in steps:
            if not isinstance(s, DeriveOp) or not has_effect(s.effects, Read):
                result.append(s)
                continue

            # Determine search fields: explicit args or from effect
            if fields:
                sfields = fields
            else:
                eff = get_effect(s.effects, Searchable)
                if eff is None:
                    result.append(s)
                    continue
                sfields = eff.fields

            if not sfields:
                result.append(s)
                continue

            # Add ?q= param
            s = replace(
                s,
                extra_op_fields=(*s.extra_op_fields, ("q", str | None)),
                extra_request_fields=(*s.extra_request_fields, ("q", str | None)),
                handler_template=WrappedTemplate(
                    inner=s.handler_template,
                    wrapper=_make_search_wrapper(sfields),
                ),
            )
            result.append(s)
        return tuple(result)
    return transform


def rate_limited(rpm: int | None = None) -> DerivationT:
    """Add rate limiting to steps declaring RateLimited effect.

    rpm arg overrides effect default. If None, reads from RateLimited.rpm.
    Different from with_rate_limit() which applies to ALL ops unconditionally.

        .chain(rate_limited())      # from RateLimited effect
        .chain(rate_limited(30))    # explicit override
    """
    def transform(steps: Derivation) -> Derivation:
        from combinators.concurrency import RateLimitPolicy
        from emergent.wire.axis.surface.enrichers import RateLimit

        result: list[Step] = []
        for s in steps:
            if isinstance(s, _Transformable):
                eff = get_effect(s.effects, RateLimited)
                rate = rpm if rpm is not None else (eff.rpm if eff else None)
                if rate is not None:
                    cap = RateLimit(policy=RateLimitPolicy(max_per_second=rate / 60.0))
                    s = replace_caps(s, (*s.capabilities, cap))
            result.append(s)
        return tuple(result)
    return transform


def deprecated() -> DerivationT:
    """Add deprecation warning capability to ops declaring Deprecated effect.

    Reads since/message from Deprecated effect. Adds a ScopeEnricher
    that sets deprecation info on scope for compilers to consume.

        .chain(deprecated())
    """
    from dataclasses import dataclass as _dataclass

    from emergent.wire.axis.surface.capabilities import ScopeEnricher, EnricherNext

    @_dataclass(frozen=True, slots=True)
    class DeprecationInfo:
        """Deprecation metadata injected into scope."""

        since: str = ""
        message: str = ""

    @_dataclass(frozen=True, slots=True)
    class DeprecationEnricher(ScopeEnricher):
        """Enricher: attach deprecation metadata to scope for compiler targets."""

        since: str = ""
        message: str = ""

        async def enrich[R](self, call: EnricherNext[R], scope: Scope) -> R:
            scope.inject(DeprecationInfo, DeprecationInfo(since=self.since, message=self.message))
            return await call(scope)

    def transform(steps: Derivation) -> Derivation:
        result: list[Step] = []
        for s in steps:
            if isinstance(s, _Transformable):
                eff = get_effect(s.effects, Deprecated)
                if eff is not None:
                    enricher = DeprecationEnricher(since=eff.since, message=eff.message)
                    s = replace_caps(s, (*s.capabilities, enricher))
            result.append(s)
        return tuple(result)
    return transform


def with_effect(op: Op, *effects: DerivationEffect) -> DerivationT:
    """Add effects to a DeriveOp by Op identity.

        from derivelib.patterns.crud import LIST, CREATE

        .chain(with_effect(LIST, Filterable(("name",))))
        .chain(with_effect(CREATE, Validated()))
    """
    def transform(steps: Derivation) -> Derivation:
        from derivelib.axes.surface import DeriveOp

        return tuple(
            replace(s, effects=(*s.effects, *effects))
            if isinstance(s, DeriveOp) and s.source is op
            else s
            for s in steps
        )
    return transform


# ═══════════════════════════════════════════════════════════════════════════════
# Methods Transforms — operate on ExposeMethod steps
# ═══════════════════════════════════════════════════════════════════════════════


def map_methods(fn: Callable[[Step], Step]) -> DerivationT:
    """Transform all ExposeMethod steps. Non-ExposeMethod steps pass through.

    Analogous to map_all_ops for DeriveOp.

        from derivelib.transforms import map_methods
        map_methods(lambda m: replace(m, capabilities=(*m.capabilities, cap)))
    """
    def transform(steps: Derivation) -> Derivation:
        from derivelib.patterns.methods import ExposeMethod
        return tuple(fn(s) if isinstance(s, ExposeMethod) else s for s in steps)
    return transform


def add_method_capability(*caps: SurfaceCapability) -> DerivationT:
    """Add capabilities to all ExposeMethod steps.

    Analogous to add_capability for DeriveOp.

        methods.chain(add_method_capability(AuthCap()))
    """
    def transform(steps: Derivation) -> Derivation:
        from derivelib.patterns.methods import ExposeMethod
        return tuple(
            replace(s, capabilities=(*s.capabilities, *caps))
            if isinstance(s, ExposeMethod) else s
            for s in steps
        )
    return transform


__all__ = (
    # Fold primitives
    "map_by_effect",
    "reject_by_effect",
    "select_by_effect",
    "map_all_ops",
    "map_all_transformable",
    # Response projection
    "project_response",
    # Handler wrapping
    "wrap_by_effect",
    # Semantic transforms
    "readonly",
    "mutations_only",
    "without_delete",
    "without_ops",
    "only_ops",
    # Capability injection
    "add_capability",
    # Handler / trigger swaps
    "swap_handler",
    "swap_trigger",
    "rename_ops",
    # Query enrichment
    "paginated",
    "sorted_list",
    # Enrichers
    "with_timeout",
    "with_retry",
    "with_rate_limit",
    # Effect-aware transforms
    "filtered",
    "searchable",
    "rate_limited",
    "deprecated",
    "with_effect",
    # Methods transforms
    "map_methods",
    "add_method_capability",
)

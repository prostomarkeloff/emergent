"""Derivation transforms — proxy to emergent.wire.derive capability classes.

DEPRECATED: Use emergent.wire.derive transforms directly.
derivelib will be removed in emergent 1.0.0.

Semantic transforms (thin wrappers returning wire.derive capabilities):

    readonly()                      -> Readonly()
    mutations_only()                -> MutationsOnly()
    without_delete()                -> WithoutDelete()
    paginated(20)                   -> Paginated(page_size=20)
    sorted_list("name", "desc")    -> Sorted(default_sort="name", default_order="desc")

Use with .chain() for pattern composition:

    @derive(
        http_crud("/api/users", provider_node=Users)
            .chain(readonly(), paginated(20))
    )
    @dataclass
    class User: ...
"""

from __future__ import annotations

from emergent.wire.axis.schema._universal import SchemaCapability
from emergent.wire.derive._effects import DerivationEffect, Read
from emergent.wire.derive._transforms import (
    EffectDeprecated as _EffectDeprecated,
    EffectRateLimited as _EffectRateLimited,
    Filtered as _Filtered,
    MutationsOnly as _MutationsOnly,
    Paginated as _Paginated,
    ProjectResponse as _ProjectResponse,
    Readonly as _Readonly,
    Searchable as _Searchable,
    Sorted as _Sorted,
    WithoutDelete as _WithoutDelete,
    WithRateLimit as _WithRateLimit,
    WithRetry as _WithRetry,
    WithTimeout as _WithTimeout,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Semantic Transforms — return wire.derive SchemaCapability instances
# ═══════════════════════════════════════════════════════════════════════════════


def readonly() -> SchemaCapability:
    """Remove mutation operations. Keep reads only."""
    return _Readonly()


def mutations_only() -> SchemaCapability:
    """Keep only mutation operations."""
    return _MutationsOnly()


def without_delete() -> SchemaCapability:
    """Remove delete operations."""
    return _WithoutDelete()


def paginated(page_size: int | None = None) -> SchemaCapability:
    """Add pagination to list operations.

        .chain(paginated())      # default page size (20)
        .chain(paginated(50))    # explicit page size
    """
    return _Paginated(page_size=page_size or 20)


def sorted_list(
    default_sort: str | None = None,
    default_order: str | None = None,
) -> SchemaCapability:
    """Add sorting to list operations.

        .chain(sorted_list())                  # use effect defaults
        .chain(sorted_list("name", "desc"))    # explicit override
    """
    return _Sorted(
        default_sort=default_sort,
        default_order=default_order or "asc",
    )


def project_response(
    exclude: tuple[str, ...],
    effect: type[DerivationEffect] = Read,
) -> SchemaCapability:
    """Exclude fields from response on operations with given effect.

        .chain(project_response(exclude=("active_at",)))
        .chain(project_response(exclude=("secret",), effect=Read))
    """
    return _ProjectResponse(exclude=exclude, effect=effect)


def filtered(*fields: str) -> SchemaCapability:
    """Add field filtering to Read ops.

        .chain(filtered("name", "status"))
        .chain(filtered())  # from Filterable effect
    """
    return _Filtered(fields=fields)


def searchable(*fields: str) -> SchemaCapability:
    """Add full-text search to Read ops.

        .chain(searchable("name", "bio"))
        .chain(searchable())  # from Searchable effect
    """
    return _Searchable(fields=fields)


# ═══════════════════════════════════════════════════════════════════════════════
# Enricher Transforms
# ═══════════════════════════════════════════════════════════════════════════════


def with_timeout(seconds: float) -> SchemaCapability:
    """Add Timeout enricher to all operations."""
    return _WithTimeout(seconds=seconds)


def with_retry(max_retries: int = 3) -> SchemaCapability:
    """Add Retry enricher to mutation operations."""
    return _WithRetry(max_retries=max_retries)


def with_rate_limit(rpm: int) -> SchemaCapability:
    """Add RateLimit enricher to ALL operations unconditionally."""
    return _WithRateLimit(rpm=rpm)


# ═══════════════════════════════════════════════════════════════════════════════
# Effect-Aware Transforms
# ═══════════════════════════════════════════════════════════════════════════════


def rate_limited(rpm: int | None = None) -> SchemaCapability:
    """Add rate limiting to steps declaring RateLimited effect.

        .chain(rate_limited())      # from RateLimited effect
        .chain(rate_limited(30))    # explicit override
    """
    return _EffectRateLimited(rpm=rpm)


def deprecated() -> SchemaCapability:
    """Add deprecation warning capability to ops declaring Deprecated effect."""
    return _EffectDeprecated()


# ═══════════════════════════════════════════════════════════════════════════════
# Blocked low-level transforms — raise ImportError
# ═══════════════════════════════════════════════════════════════════════════════

_REMOVED_MSG = (
    "derivelib.transforms.{name}() has been removed. "
    "Use emergent.wire.derive directly for low-level transforms. "
    "derivelib will be removed in emergent 1.0.0."
)

_REMOVED_NAMES = frozenset({
    "map_by_effect",
    "reject_by_effect",
    "select_by_effect",
    "map_all_ops",
    "map_all_transformable",
    "without_ops",
    "only_ops",
    "wrap_by_effect",
    "add_capability",
    "swap_handler",
    "swap_trigger",
    "rename_ops",
    "with_effect",
    "map_methods",
    "add_method_capability",
})


def __getattr__(name: str) -> object:
    if name in _REMOVED_NAMES:
        raise ImportError(_REMOVED_MSG.format(name=name))
    raise AttributeError(f"module 'derivelib.transforms' has no attribute {name!r}")


__all__ = (
    # Semantic transforms
    "readonly",
    "mutations_only",
    "without_delete",
    # Response projection
    "project_response",
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
)

"""Derivation effects — protocol-based operation classifiers.

Effects are to derivation what capabilities are to compilation.
They classify operations by WHAT they do, enabling semantic dispatch
in DerivationT transforms via isinstance-based handler tables.

    Wire capabilities: compile-time annotations on types, dispatched by compilers.
    Derivation effects: derive-time annotations on ops, dispatched by transforms.

NOTHING IS SPECIAL. Built-in effects (Read, Mutation, etc.) use the exact
same mechanism as any user-defined effect.

    # Built-in effect — no special treatment:
    @dataclass(frozen=True, slots=True)
    class Read(DerivationEffect): ...

    # User effect — identical pattern:
    @dataclass(frozen=True, slots=True)
    class Auditable(DerivationEffect):
        level: str = "info"

    # Both dispatched the same way:
    reject_by_effect(Mutation)    # works
    reject_by_effect(Auditable)   # works identically

    map_by_effect({Mutation: fn})     # works
    map_by_effect({Auditable: fn})    # works identically

    # Effects can carry data:
    audit = get_effect(op.effects, Auditable)
    if audit: print(audit.level)  # "debug"

Hierarchy:
    Creates, Updates, Deletes extend Mutation.
    isinstance(Creates(), Mutation) → True.
    This means: effects=(Creates(),) is sufficient — no need to tag Mutation() separately.
    has_effect(effects, Mutation) matches Creates/Updates/Deletes automatically.
    map_by_effect({Mutation: fn}) matches Creates/Updates/Deletes automatically.

Data-carrying effects:
    Pageable(default_size=50) — transforms read config from the effect.
    Sortable(default_field="name") — op is self-describing.
    Cacheable(ttl=300) — no need to repeat config in transform args.
"""

from __future__ import annotations

from dataclasses import dataclass


# ═══════════════════════════════════════════════════════════════════════════════
# Root Base Class
# ═══════════════════════════════════════════════════════════════════════════════


class DerivationEffect:
    """Root marker for derivation-phase effects.

    Parallel to wire's Capability, but for derivation transforms.
    Custom effects subclass this. Transforms dispatch on effects
    via isinstance — open-world, extensible by anyone.

    Unlike a Protocol, this is nominal: isinstance checks require
    actual subclassing, so arbitrary objects do NOT match.
    """


# ═══════════════════════════════════════════════════════════════════════════════
# Semantic Effects — WHAT the operation does
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Read(DerivationEffect):
    """Operation reads data without modification."""


@dataclass(frozen=True, slots=True)
class Mutation(DerivationEffect):
    """Operation modifies data.

    Base class for Creates, Updates, Deletes.
    isinstance(Creates(), Mutation) → True.
    """


@dataclass(frozen=True, slots=True)
class Idempotent(DerivationEffect):
    """Operation is safe to retry (same input → same outcome)."""


# ═══════════════════════════════════════════════════════════════════════════════
# Mutation Sub-Effects — finer-grained mutation classification
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Creates(Mutation):
    """Operation creates new entities. Implies Mutation."""


@dataclass(frozen=True, slots=True)
class Updates(Mutation):
    """Operation updates existing entities. Implies Mutation."""


@dataclass(frozen=True, slots=True)
class Deletes(Mutation):
    """Operation deletes entities. Implies Mutation."""


# ═══════════════════════════════════════════════════════════════════════════════
# Query-Characteristic Effects — HOW the operation queries data
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Pageable(DerivationEffect):
    """Operation supports pagination (page + page_size).

    default_size is read by paginated() transform as fallback.
    """

    default_size: int = 20


@dataclass(frozen=True, slots=True)
class Sortable(DerivationEffect):
    """Operation supports sorting (sort + order).

    default_field/default_order are read by sorted_list() transform as fallback.
    """

    default_field: str = ""
    default_order: str = "asc"


@dataclass(frozen=True, slots=True)
class Cacheable(DerivationEffect):
    """Operation result can be cached.

    ttl=0 means no default — use transform argument.
    """

    ttl: int = 0


@dataclass(frozen=True, slots=True)
class Filterable(DerivationEffect):
    """Operation supports field-level filtering (e.g. ?name=X&status=active).

    fields lists which entity fields can be filtered on.
    Empty tuple = all non-identity fields (resolved by transform).

        LIST = Op("List", ..., effects=(Read(), Filterable(("name", "status"))))
    """

    fields: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Searchable(DerivationEffect):
    """Operation supports full-text search across fields (e.g. ?q=term).

    fields lists which entity fields are searched.
    Empty tuple = all string fields (resolved by transform).

        LIST = Op("List", ..., effects=(Read(), Searchable(("name", "bio"))))
    """

    fields: tuple[str, ...] = ()


# ═══════════════════════════════════════════════════════════════════════════════
# Access Control Effects
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Public(DerivationEffect):
    """Operation is public — skip authentication.

    Used by require_auth() to bypass auth on specific ops.

        LOGIN = Op("Login", ..., effects=(Creates(), Public()))
    """


@dataclass(frozen=True, slots=True)
class RateLimited(DerivationEffect):
    """Operation has per-endpoint rate limiting.

    rpm is read by rate_limited() transform as default.

        LIST = Op("List", ..., effects=(Read(), RateLimited(rpm=100)))
    """

    rpm: int = 60


# ═══════════════════════════════════════════════════════════════════════════════
# Data Integrity Effects
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Validated(DerivationEffect):
    """Operation input requires domain validation beyond type checking.

    Marker for transforms that add custom validation enrichers.

        CREATE = Op("Create", ..., effects=(Creates(), Validated()))
    """


@dataclass(frozen=True, slots=True)
class Versioned(DerivationEffect):
    """Operation supports optimistic concurrency control (ETag / version field).

    version_field names the entity field holding the version counter.

        UPDATE = Op("Update", ..., effects=(Updates(), Versioned(version_field="ver")))
    """

    version_field: str = "version"


@dataclass(frozen=True, slots=True)
class Bulk(DerivationEffect):
    """Operation supports batch execution.

    max_batch_size limits items per request.

        CREATE = Op("Create", ..., effects=(Creates(), Bulk(max_batch_size=50)))
    """

    max_batch_size: int = 100


# ═══════════════════════════════════════════════════════════════════════════════
# Observability Effects
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Auditable(DerivationEffect):
    """Operation mutations should be audit-logged.

    level is read by audited() transform as default.

        CREATE = Op("Create", ..., effects=(Creates(), Auditable(level="debug")))
    """

    level: str = "info"


@dataclass(frozen=True, slots=True)
class Emits(DerivationEffect):
    """Operation emits events on success.

    event names the event channel/type.

        CREATE = Op("Create", ..., effects=(Creates(), Emits(event="user.created")))
    """

    event: str = ""


@dataclass(frozen=True, slots=True)
class Deprecated(DerivationEffect):
    """Operation is deprecated — adds deprecation headers/warnings.

    since = version/date when deprecated. message = migration guidance.

        OLD_LIST = Op("OldList", ..., effects=(Read(), Deprecated(since="v2", message="Use List")))
    """

    since: str = ""
    message: str = ""


# ═══════════════════════════════════════════════════════════════════════════════
# Dispatch Helpers
# ═══════════════════════════════════════════════════════════════════════════════


def has_effect(effects: tuple[DerivationEffect, ...], effect_type: type) -> bool:
    """Check if any effect is an instance of effect_type.

    Supports hierarchy: has_effect((Creates(),), Mutation) → True.

        if has_effect(op.effects, Mutation):
            ...  # this op mutates data (including Creates/Updates/Deletes)
    """
    return any(isinstance(e, effect_type) for e in effects)


def get_effect[T](effects: tuple[DerivationEffect, ...], effect_type: type[T]) -> T | None:
    """Get first effect of given type, or None.

    Supports hierarchy: get_effect((Creates(),), Mutation) → Creates().

        pageable = get_effect(op.effects, Pageable)
        if pageable is not None:
            print(pageable.default_size)  # 20
    """
    for e in effects:
        if isinstance(e, effect_type):
            return e
    return None


__all__ = (
    # Root
    "DerivationEffect",
    # Semantic effects
    "Read",
    "Mutation",
    "Idempotent",
    # Mutation sub-effects
    "Creates",
    "Updates",
    "Deletes",
    # Query-characteristic effects
    "Pageable",
    "Sortable",
    "Cacheable",
    "Filterable",
    "Searchable",
    # Access control effects
    "Public",
    "RateLimited",
    # Data integrity effects
    "Validated",
    "Versioned",
    "Bulk",
    # Observability effects
    "Auditable",
    "Emits",
    "Deprecated",
    # Dispatch helpers
    "has_effect",
    "get_effect",
)

"""Derivation effects — protocol-based operation classifiers.

Effects classify operations by WHAT they do, enabling semantic dispatch
in transforms via isinstance-based handler tables.

    Wire capabilities: compile-time annotations on types, dispatched by compilers.
    Derivation effects: derive-time annotations on ops, dispatched by transforms.

Hierarchy: Creates, Updates, Deletes extend Mutation.
isinstance(Creates(), Mutation) -> True.
has_effect(effects, Mutation) matches all three automatically.
"""

from __future__ import annotations

from dataclasses import dataclass


class DerivationEffect:
    """Root marker for derivation-phase effects.

    Custom effects subclass this. Transforms dispatch on effects
    via isinstance — open-world, extensible by anyone.
    """


# ═══════════════════════════════════════════════════════════════════════════════
# Semantic Effects
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Read(DerivationEffect):
    """Operation reads data without modification."""


@dataclass(frozen=True, slots=True)
class Mutation(DerivationEffect):
    """Operation modifies data. Base for Creates, Updates, Deletes."""


@dataclass(frozen=True, slots=True)
class Idempotent(DerivationEffect):
    """Operation is safe to retry (same input -> same outcome)."""


# ═══════════════════════════════════════════════════════════════════════════════
# Mutation Sub-Effects
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
# Query-Characteristic Effects
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Pageable(DerivationEffect):
    """Operation supports pagination."""
    default_size: int = 20


@dataclass(frozen=True, slots=True)
class Sortable(DerivationEffect):
    """Operation supports sorting."""
    default_field: str = ""
    default_order: str = "asc"


@dataclass(frozen=True, slots=True)
class Cacheable(DerivationEffect):
    """Operation result can be cached. ttl=0 means use transform argument."""
    ttl: int = 0


@dataclass(frozen=True, slots=True)
class Filterable(DerivationEffect):
    """Operation supports field-level filtering. Empty fields = all non-identity."""
    fields: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Searchable(DerivationEffect):
    """Operation supports full-text search. Empty fields = all string fields."""
    fields: tuple[str, ...] = ()


# ═══════════════════════════════════════════════════════════════════════════════
# Access Control Effects
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Public(DerivationEffect):
    """Operation is public — skip authentication."""


@dataclass(frozen=True, slots=True)
class RateLimited(DerivationEffect):
    """Operation has per-endpoint rate limiting."""
    rpm: int = 60


# ═══════════════════════════════════════════════════════════════════════════════
# Data Integrity Effects
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Validated(DerivationEffect):
    """Operation input requires domain validation beyond type checking."""


@dataclass(frozen=True, slots=True)
class Versioned(DerivationEffect):
    """Operation supports optimistic concurrency control."""
    version_field: str = "version"


@dataclass(frozen=True, slots=True)
class Bulk(DerivationEffect):
    """Operation supports batch execution."""
    max_batch_size: int = 100


# ═══════════════════════════════════════════════════════════════════════════════
# Observability Effects
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Auditable(DerivationEffect):
    """Operation mutations should be audit-logged."""
    level: str = "info"


@dataclass(frozen=True, slots=True)
class Emits(DerivationEffect):
    """Operation emits events on success."""
    event: str = ""


@dataclass(frozen=True, slots=True)
class Deprecated(DerivationEffect):
    """Operation is deprecated — adds deprecation headers/warnings."""
    since: str = ""
    message: str = ""


# ═══════════════════════════════════════════════════════════════════════════════
# Dispatch Helpers
# ═══════════════════════════════════════════════════════════════════════════════


def has_effect(effects: tuple[DerivationEffect, ...], effect_type: type) -> bool:
    """Check if any effect is an instance of effect_type.

    Supports hierarchy: has_effect((Creates(),), Mutation) -> True.
    """
    return any(isinstance(e, effect_type) for e in effects)


def get_effect[T](effects: tuple[DerivationEffect, ...], effect_type: type[T]) -> T | None:
    """Get first effect of given type, or None.

    Supports hierarchy: get_effect((Creates(),), Mutation) -> Creates().
    """
    for e in effects:
        if isinstance(e, effect_type):
            return e
    return None


__all__ = (
    "DerivationEffect",
    "Read", "Mutation", "Idempotent",
    "Creates", "Updates", "Deletes",
    "Pageable", "Sortable", "Cacheable", "Filterable", "Searchable",
    "Public", "RateLimited",
    "Validated", "Versioned", "Bulk",
    "Auditable", "Emits", "Deprecated",
    "has_effect", "get_effect",
)

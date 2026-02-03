"""Query dialect — field-level query capabilities.

Annotations for query axis features. Providers read these to validate
and optimize queries.

    from emergent.wire.axis.schema.dialects import query

    @dataclass
    class User:
        id: Annotated[int, Identity]
        email: Annotated[str, Unique, query.Filterable(), query.Sortable()]
        balance: Annotated[int, query.Aggregatable(Sum, Avg, Min, Max)]
        tags: Annotated[list[str], query.ArrayQueryable()]
        metadata: Annotated[dict, query.JsonQueryable()]

Provider uses these to:
    - Validate filter operators match Operators() capability
    - Validate aggregates use allowed functions
    - Optimize queries (e.g., use indexes for Filterable fields)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from emergent.wire.axis.schema._universal import SchemaAxisCapability


class QueryCapability(SchemaAxisCapability):
    """Base for query-specific capabilities."""

    pass


# ═══════════════════════════════════════════════════════════════════════════════
# Field Capabilities
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Filterable(QueryCapability):
    """Field can be filtered.

    Usage:
        email: Annotated[str, query.Filterable()]
    """
    pass


@dataclass(frozen=True, slots=True)
class Sortable(QueryCapability):
    """Field can be sorted.

    Usage:
        created_at: Annotated[datetime, query.Sortable()]
    """
    pass


@dataclass(frozen=True, slots=True)
class Selectable(QueryCapability):
    """Field can be selected (sparse fieldsets).

    Usage:
        profile: Annotated[Profile, query.Selectable()]
    """
    pass


@dataclass(frozen=True, slots=True)
class Searchable(QueryCapability):
    """Field participates in full-text search.

    Usage:
        description: Annotated[str, query.Searchable()]
    """
    pass


@dataclass(frozen=True, slots=True)
class Aggregatable(QueryCapability):
    """Field can be aggregated with specified functions.

    Usage:
        balance: Annotated[int, query.Aggregatable(Sum, Avg, Min, Max)]
        id: Annotated[int, query.Aggregatable(Count)]  # only count

    Empty tuple = all standard aggregates allowed.
    """
    functions: tuple[type, ...]

    def __init__(self, *functions: type) -> None:
        # Import here to avoid circular imports
        if functions:
            object.__setattr__(self, "functions", functions)
        else:
            # Default: all standard aggregate functions
            from emergent.wire.axis.query._aggregate import (
                Sum, Avg, Min, Max, Count,
            )
            object.__setattr__(self, "functions", (Sum, Avg, Min, Max, Count))


# ═══════════════════════════════════════════════════════════════════════════════
# Operator Constraints
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Operators(QueryCapability):
    """Allowed filter operators for this field.

    Operators are typed (Expr subclasses), not strings.

    Usage:
        from emergent.wire.axis.query import Eq, Gt, Lt, In

        status: Annotated[str, query.Operators(Eq, In)]  # only equality and in_
        balance: Annotated[int, query.Operators(Eq, Gt, Lt)]  # equality and comparison
    """
    allowed: tuple[type, ...]

    def __init__(self, *operators: type) -> None:
        object.__setattr__(self, "allowed", operators)


# ═══════════════════════════════════════════════════════════════════════════════
# Special Field Types
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class JsonQueryable(QueryCapability):
    """Field supports JSON path queries.

    Usage:
        metadata: Annotated[dict, query.JsonQueryable()]

    Enables:
        .filter(lambda u: u.metadata.json("profile.name") == "alice")
        .filter(lambda u: u.metadata.json_contains({"role": "admin"}))
        .filter(lambda u: u.metadata.json_has_key("verified"))
    """
    pass


@dataclass(frozen=True, slots=True)
class ArrayQueryable(QueryCapability):
    """Field supports array operations.

    Usage:
        tags: Annotated[list[str], query.ArrayQueryable()]

    Enables:
        .filter(lambda u: u.tags.array_contains("vip"))
        .filter(lambda u: u.tags.array_any("vip", "admin"))
        .filter(lambda u: u.tags.array_all("verified", "active"))
    """
    pass


@dataclass(frozen=True, slots=True)
class FullTextIndexed(QueryCapability):
    """Field has full-text index.

    Usage:
        content: Annotated[str, query.FullTextIndexed()]
        content: Annotated[str, query.FullTextIndexed(language="russian")]
    """
    language: str = "english"


# ═══════════════════════════════════════════════════════════════════════════════
# Utility
# ═══════════════════════════════════════════════════════════════════════════════


def has_capability(annotations: tuple[Any, ...], cap_type: type[QueryCapability]) -> bool:
    """Check if annotations contain a specific query capability."""
    return any(isinstance(ann, cap_type) for ann in annotations)


def get_capability(
    annotations: tuple[Any, ...],
    cap_type: type[QueryCapability],
) -> QueryCapability | None:
    """Get specific query capability from annotations."""
    for ann in annotations:
        if isinstance(ann, cap_type):
            return ann
    return None


def get_operators(annotations: tuple[Any, ...]) -> tuple[type, ...] | None:
    """Get allowed operators from annotations."""
    cap = get_capability(annotations, Operators)
    if isinstance(cap, Operators):
        return cap.allowed
    return None


def get_aggregate_functions(annotations: tuple[Any, ...]) -> tuple[type, ...] | None:
    """Get allowed aggregate functions from annotations."""
    cap = get_capability(annotations, Aggregatable)
    if isinstance(cap, Aggregatable):
        return cap.functions
    return None


__all__ = (
    # Base
    "QueryCapability",
    # Field capabilities
    "Filterable",
    "Sortable",
    "Selectable",
    "Searchable",
    "Aggregatable",
    # Operator constraints
    "Operators",
    # Special field types
    "JsonQueryable",
    "ArrayQueryable",
    "FullTextIndexed",
    # Utility
    "has_capability",
    "get_capability",
    "get_operators",
    "get_aggregate_functions",
)

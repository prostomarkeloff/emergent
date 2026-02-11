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

from dataclasses import dataclass, replace
from typing import Any, TYPE_CHECKING

from emergent.wire.axis.schema._universal import SchemaAxisCapability
from emergent.wire.axis._capability import openapi_schema

if TYPE_CHECKING:
    from emergent.wire.axis._capability import OpenAPIContext, QuerySchemaContext


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

    def compile_query_schema(self, ctx: "QuerySchemaContext") -> "QuerySchemaContext":
        return replace(ctx, filterable=True)

    def compile_openapi(self, ctx: "OpenAPIContext") -> "OpenAPIContext":
        return openapi_schema(ctx, **{"x-filterable": True})


@dataclass(frozen=True, slots=True)
class Sortable(QueryCapability):
    """Field can be sorted.

    Usage:
        created_at: Annotated[datetime, query.Sortable()]
    """

    def compile_query_schema(self, ctx: "QuerySchemaContext") -> "QuerySchemaContext":
        return replace(ctx, sortable=True)

    def compile_openapi(self, ctx: "OpenAPIContext") -> "OpenAPIContext":
        return openapi_schema(ctx, **{"x-sortable": True})


@dataclass(frozen=True, slots=True)
class Selectable(QueryCapability):
    """Field can be selected (sparse fieldsets).

    Usage:
        profile: Annotated[Profile, query.Selectable()]
    """

    def compile_query_schema(self, ctx: "QuerySchemaContext") -> "QuerySchemaContext":
        return replace(ctx, selectable=True)

    def compile_openapi(self, ctx: "OpenAPIContext") -> "OpenAPIContext":
        return openapi_schema(ctx, **{"x-selectable": True})


@dataclass(frozen=True, slots=True)
class Searchable(QueryCapability):
    """Field participates in full-text search.

    Usage:
        description: Annotated[str, query.Searchable()]
    """

    def compile_query_schema(self, ctx: "QuerySchemaContext") -> "QuerySchemaContext":
        return replace(ctx, searchable=True)

    def compile_openapi(self, ctx: "OpenAPIContext") -> "OpenAPIContext":
        return openapi_schema(ctx, **{"x-searchable": True})


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

    def compile_query_schema(self, ctx: "QuerySchemaContext") -> "QuerySchemaContext":
        return replace(ctx, aggregatable=True, aggregate_functions=self.functions)

    def compile_openapi(self, ctx: "OpenAPIContext") -> "OpenAPIContext":
        return openapi_schema(ctx, **{"x-aggregatable": True})


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

    def compile_query_schema(self, ctx: "QuerySchemaContext") -> "QuerySchemaContext":
        return replace(ctx, operators=self.allowed)

    def compile_openapi(self, ctx: "OpenAPIContext") -> "OpenAPIContext":
        return openapi_schema(ctx, **{"x-operators": [op.__name__ for op in self.allowed]})


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

    def compile_query_schema(self, ctx: "QuerySchemaContext") -> "QuerySchemaContext":
        return replace(ctx, json_queryable=True)

    def compile_openapi(self, ctx: "OpenAPIContext") -> "OpenAPIContext":
        return openapi_schema(ctx, **{"x-json-queryable": True})


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

    def compile_query_schema(self, ctx: "QuerySchemaContext") -> "QuerySchemaContext":
        return replace(ctx, array_queryable=True)

    def compile_openapi(self, ctx: "OpenAPIContext") -> "OpenAPIContext":
        return openapi_schema(ctx, **{"x-array-queryable": True})


@dataclass(frozen=True, slots=True)
class FullTextIndexed(QueryCapability):
    """Field has full-text index.

    Usage:
        content: Annotated[str, query.FullTextIndexed()]
        content: Annotated[str, query.FullTextIndexed(language="russian")]
    """
    language: str = "english"

    def compile_query_schema(self, ctx: "QuerySchemaContext") -> "QuerySchemaContext":
        return replace(ctx, full_text_indexed=True, fti_language=self.language)

    def compile_openapi(self, ctx: "OpenAPIContext") -> "OpenAPIContext":
        return openapi_schema(ctx, **{
            "x-full-text-indexed": True,
            "x-fti-language": self.language,
        })


# ═══════════════════════════════════════════════════════════════════════════════
# Fold-based query — use fold_field to read query capabilities
# ═══════════════════════════════════════════════════════════════════════════════


def fold_query_schema(field_info: Any) -> "QuerySchemaContext":
    """Fold all query capabilities for a field into QuerySchemaContext.

    This is the canonical way to read query capabilities — through fold, not info.get().
    """
    from emergent.wire.compile._core import fold_field
    from emergent.wire.axis._capability import QuerySchemaContext, QuerySchemaCompilable

    return fold_field(
        field_info,
        QuerySchemaContext(field_name=field_info.name, field_type=field_info.base_type),
        QuerySchemaCompilable,
        "compile_query_schema",
    )


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
    # Fold-based query
    "fold_query_schema",
)

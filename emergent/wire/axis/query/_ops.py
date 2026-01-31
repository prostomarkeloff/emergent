"""Query operations — building blocks for QuerySet.

Operations form an immutable list that describes the query:

    [Filter(expr), OrderBy("balance", desc=True), Limit(50)]

Provider walks this list to compile or interpret the query.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from emergent.wire.axis.query._expr import Expr
from emergent.wire.axis.query._proxy import OrderSpec


# ─── Base ─────────────────────────────────────────────────────────────────────


class Op:
    """Base query operation."""

    pass


# ─── Universal Operations (all spaces support) ────────────────────────────────


@dataclass(frozen=True, slots=True)
class Filter(Op):
    """Filter by expression: WHERE clause."""

    expr: Expr


@dataclass(frozen=True, slots=True)
class OrderBy(Op):
    """Order results: ORDER BY clause."""

    specs: tuple[OrderSpec, ...]


@dataclass(frozen=True, slots=True)
class Limit(Op):
    """Limit number of results: LIMIT clause."""

    count: int


@dataclass(frozen=True, slots=True)
class Offset(Op):
    """Skip first N results: OFFSET clause."""

    count: int


@dataclass(frozen=True, slots=True)
class Select(Op):
    """Project specific fields: SELECT clause.

    Empty tuple = all fields (SELECT *)
    """

    fields: tuple[str, ...]


# ─── KV Operations ────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Get(Op):
    """Get by primary key."""

    key: Any


@dataclass(frozen=True, slots=True)
class Set(Op):
    """Set/upsert entity."""

    key: Any
    value: Any


@dataclass(frozen=True, slots=True)
class Delete(Op):
    """Delete by primary key."""

    key: Any


@dataclass(frozen=True, slots=True)
class Exists(Op):
    """Check if key exists."""

    key: Any


# ─── Relational Operations (extended) ─────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Join(Op):
    """Join with another entity.

    Example: users.join(Post, on=lambda u, p: u.id == p.author_id)
    """

    target: type
    on: Expr
    join_type: str = "inner"  # inner, left, right, outer


@dataclass(frozen=True, slots=True)
class GroupBy(Op):
    """Group by fields."""

    fields: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Having(Op):
    """Filter groups (after GROUP BY)."""

    expr: Expr


@dataclass(frozen=True, slots=True)
class Distinct(Op):
    """Remove duplicates."""

    pass


# ─── Aggregate Operations ─────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Count(Op):
    """Count results."""

    pass


@dataclass(frozen=True, slots=True)
class Sum(Op):
    """Sum field values."""

    field: str


@dataclass(frozen=True, slots=True)
class Avg(Op):
    """Average field values."""

    field: str


@dataclass(frozen=True, slots=True)
class Min(Op):
    """Minimum field value."""

    field: str


@dataclass(frozen=True, slots=True)
class Max(Op):
    """Maximum field value."""

    field: str


__all__ = (
    # Base
    "Op",
    # Universal
    "Filter",
    "OrderBy",
    "Limit",
    "Offset",
    "Select",
    # KV
    "Get",
    "Set",
    "Delete",
    "Exists",
    # Relational
    "Join",
    "GroupBy",
    "Having",
    "Distinct",
    # Aggregate
    "Count",
    "Sum",
    "Avg",
    "Min",
    "Max",
)

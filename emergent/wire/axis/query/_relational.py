"""Relational QuerySet — SQL-like operations.

For SQL databases and in-memory collections.

    users = relational(User)

    q = (
        users
            .filter(lambda u: u.active == True)
            .filter(lambda u: u.balance > 100)
            .order_by(lambda u: u.balance.desc())
            .limit(50)
    )

    result = await sql_provider.fetch_many(q)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generic, Literal, TypeVar

from emergent.wire.axis.query._expr import Expr
from emergent.wire.axis.query._proxy import OrderSpec
from emergent.wire.axis.query._aggregate import AggregateFunc
from emergent.wire.axis.query._base_qs import RelationalMixin


T = TypeVar("T")


# ─── Operations ───────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Filter:
    """WHERE clause."""
    expr: Expr


@dataclass(frozen=True, slots=True)
class OrderBy:
    """ORDER BY clause."""
    specs: tuple[OrderSpec, ...]


@dataclass(frozen=True, slots=True)
class Limit:
    """LIMIT clause."""
    count: int

    def __post_init__(self) -> None:
        if self.count < 0:
            raise ValueError(f"LIMIT must be non-negative, got {self.count}")


@dataclass(frozen=True, slots=True)
class Offset:
    """OFFSET clause."""
    count: int

    def __post_init__(self) -> None:
        if self.count < 0:
            raise ValueError(f"OFFSET must be non-negative, got {self.count}")


@dataclass(frozen=True, slots=True)
class Select:
    """SELECT projection (empty = all)."""
    fields: tuple[str, ...]


JoinKind = Literal["inner", "left", "right", "outer"]


@dataclass(frozen=True, slots=True)
class Join:
    """JOIN clause."""
    target: type
    on: Expr
    kind: JoinKind = "inner"
    tablename: str | None = None


@dataclass(frozen=True, slots=True)
class GroupBy:
    """GROUP BY clause."""
    fields: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Having:
    """HAVING clause (filter after GROUP BY)."""
    expr: Expr


@dataclass(frozen=True, slots=True)
class Distinct:
    """DISTINCT modifier."""
    pass


@dataclass(frozen=True, slots=True)
class AggregateSpec:
    """Single aggregate specification.

    Created by lambda in aggregate():
        .aggregate(total=lambda u: u.balance.sum())
        # → AggregateSpec(func=Sum(), field="balance", alias="total")
    """

    func: AggregateFunc  # Typed! Not string
    field: str | None  # None for COUNT(*)
    alias: str


@dataclass(frozen=True, slots=True)
class Aggregate:
    """Aggregate operation.

    Contains multiple aggregate specs to compute.
    """

    specs: tuple[AggregateSpec, ...]


# Union type for all relational ops
RelationalOp = Filter | OrderBy | Limit | Offset | Select | Join | GroupBy | Having | Distinct | Aggregate


# ─── QuerySet ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RelationalQuerySet(RelationalMixin[T], Generic[T]):
    """Relational query — SQL-like operations.

    Immutable. Each method returns new QuerySet.
    """

    entity: type[T]
    ops: tuple[RelationalOp, ...] = field(default_factory=tuple)

    def _append(self, op: RelationalOp) -> RelationalQuerySet[T]:
        return RelationalQuerySet(entity=self.entity, ops=(*self.ops, op))


def relational(entity: type[T]) -> RelationalQuerySet[T]:
    """Create relational QuerySet for entity.

    Usage:
        users = relational(User)
        q = users.filter(lambda u: u.active == True).limit(10)
    """
    return RelationalQuerySet(entity=entity)


__all__ = (
    # Operations
    "Filter",
    "OrderBy",
    "Limit",
    "Offset",
    "Select",
    "Join",
    "GroupBy",
    "Having",
    "Distinct",
    "AggregateSpec",
    "Aggregate",
    "RelationalOp",
    # QuerySet
    "RelationalQuerySet",
    "relational",
)

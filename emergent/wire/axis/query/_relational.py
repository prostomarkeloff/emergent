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
from typing import Callable, Generic, TypeVar

from emergent.wire.axis.query._expr import Expr
from emergent.wire.axis.query._proxy import (
    EntityProxy,
    FieldProxy,
    OrderSpec,
    build_expr,
    build_order,
)


T = TypeVar("T")
Other = TypeVar("Other")


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


@dataclass(frozen=True, slots=True)
class Offset:
    """OFFSET clause."""
    count: int


@dataclass(frozen=True, slots=True)
class Select:
    """SELECT projection (empty = all)."""
    fields: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Join:
    """JOIN clause."""
    target: type
    on: Expr
    kind: str = "inner"  # inner, left, right, outer


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


# Union type for all relational ops
RelationalOp = Filter | OrderBy | Limit | Offset | Select | Join | GroupBy | Having | Distinct


# ─── QuerySet ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RelationalQuerySet(Generic[T]):
    """Relational query — SQL-like operations.

    Immutable. Each method returns new QuerySet.
    """

    entity: type[T]
    ops: tuple[RelationalOp, ...] = field(default_factory=tuple)

    def _append(self, op: RelationalOp) -> RelationalQuerySet[T]:
        return RelationalQuerySet(entity=self.entity, ops=(*self.ops, op))

    # ─── Filtering ────────────────────────────────────────────────────────

    def filter(self, predicate: Callable[[EntityProxy[T]], Expr]) -> RelationalQuerySet[T]:
        """Add WHERE condition.

        The predicate receives a proxy object. Field access and operators
        build expressions at runtime.

        Usage:
            .filter(lambda u: u.balance > 100)
            .filter(lambda u: (u.active == True) & (u.role == "admin"))
        """
        expr = build_expr(self.entity, predicate)
        return self._append(Filter(expr))

    def where(self, predicate: Callable[[EntityProxy[T]], Expr]) -> RelationalQuerySet[T]:
        """Alias for filter()."""
        return self.filter(predicate)

    # ─── Ordering ─────────────────────────────────────────────────────────

    def order_by(
        self, *order_fns: Callable[[EntityProxy[T]], FieldProxy | OrderSpec]
    ) -> RelationalQuerySet[T]:
        """Add ORDER BY.

        The order function receives a proxy object. Access field and call
        .asc() or .desc() for direction.

        Usage:
            .order_by(lambda u: u.balance.desc())
            .order_by(lambda u: u.name, lambda u: u.created_at.desc())
        """
        specs = tuple(build_order(self.entity, fn) for fn in order_fns)
        return self._append(OrderBy(specs))

    # ─── Pagination ───────────────────────────────────────────────────────

    def limit(self, count: int) -> RelationalQuerySet[T]:
        """Add LIMIT."""
        return self._append(Limit(count))

    def offset(self, count: int) -> RelationalQuerySet[T]:
        """Add OFFSET."""
        return self._append(Offset(count))

    def paginate(self, page: int, per_page: int) -> RelationalQuerySet[T]:
        """Convenience: offset + limit for pagination."""
        return self.offset((page - 1) * per_page).limit(per_page)

    # ─── Projection ───────────────────────────────────────────────────────

    def select(self, *fields: str) -> RelationalQuerySet[T]:
        """SELECT specific fields only."""
        return self._append(Select(fields))

    def distinct(self) -> RelationalQuerySet[T]:
        """SELECT DISTINCT."""
        return self._append(Distinct())

    # ─── Joins ────────────────────────────────────────────────────────────

    def join(
        self,
        target: type[Other],
        on: Callable[[EntityProxy[T], EntityProxy[Other]], Expr],
    ) -> RelationalQuerySet[T]:
        """INNER JOIN.

        Usage:
            .join(Post, on=lambda u, p: u.id == p.author_id)
        """
        left_proxy = EntityProxy(self.entity)
        right_proxy = EntityProxy(target)
        expr = on(left_proxy, right_proxy)
        return self._append(Join(target, expr, "inner"))

    def left_join(
        self,
        target: type[Other],
        on: Callable[[EntityProxy[T], EntityProxy[Other]], Expr],
    ) -> RelationalQuerySet[T]:
        """LEFT JOIN."""
        left_proxy = EntityProxy(self.entity)
        right_proxy = EntityProxy(target)
        expr = on(left_proxy, right_proxy)
        return self._append(Join(target, expr, "left"))

    # ─── Grouping ─────────────────────────────────────────────────────────

    def group_by(self, *field_fns: Callable[[EntityProxy[T]], FieldProxy]) -> RelationalQuerySet[T]:
        """GROUP BY fields.

        Usage:
            .group_by(lambda u: u.role)
        """
        fields = tuple(fn(EntityProxy(self.entity)).name for fn in field_fns)
        return self._append(GroupBy(fields))

    def having(self, predicate: Callable[[EntityProxy[T]], Expr]) -> RelationalQuerySet[T]:
        """HAVING clause (filter after GROUP BY)."""
        expr = build_expr(self.entity, predicate)
        return self._append(Having(expr))

    # ─── Introspection ────────────────────────────────────────────────────

    @property
    def filters(self) -> list[Expr]:
        """All filter expressions."""
        return [op.expr for op in self.ops if isinstance(op, Filter)]

    @property
    def ordering(self) -> list[OrderSpec]:
        """All order specs."""
        result: list[OrderSpec] = []
        for op in self.ops:
            if isinstance(op, OrderBy):
                result.extend(op.specs)
        return result

    @property
    def limit_value(self) -> int | None:
        for op in self.ops:
            if isinstance(op, Limit):
                return op.count
        return None

    @property
    def offset_value(self) -> int | None:
        for op in self.ops:
            if isinstance(op, Offset):
                return op.count
        return None


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
    "RelationalOp",
    # QuerySet
    "RelationalQuerySet",
    "relational",
)

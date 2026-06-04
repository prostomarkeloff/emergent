"""Shared relational QuerySet methods — mixin for deduplication.

Both RelationalQuerySet and SQLRelationalQuerySet share identical
filter/order_by/limit/join/group_by/aggregate/etc. methods.
This mixin provides them once; subclasses only define _append().
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Generic, TypeVar

from emergent.wire.axis.query._aggregate import AggregateExpr
from emergent.wire.axis.query._expr import Expr
from emergent.wire.axis.query._proxy import (
    EntityProxy,
    FieldProxy,
    OrderSpec,
    build_expr,
    build_order,
)

if TYPE_CHECKING:
    from typing import Self
    from emergent.wire.axis.query._relational import AggregateSpec

T = TypeVar("T")
Other = TypeVar("Other")


class RelationalMixin(Generic[T]):
    """Shared relational operations for any QuerySet that has entity + ops + _append.

    Subclasses must be frozen dataclasses with:
        entity: type[T]
        ops: tuple[..., ...]

    And define:
        def _append(self, op) -> Self: ...
    """

    # These are filled by the dataclass; declared here for type checker only.
    entity: type[T]
    ops: tuple[Any, ...]

    def _append(self, op: Any) -> Self: ...

    def _check_no_select(self, method: str) -> None:
        """Raise if ops already contain Select — Select is terminal."""
        from emergent.wire.axis.query._relational import Select
        if any(isinstance(op, Select) for op in self.ops):
            raise TypeError(
                f".{method}() after .select() is not allowed — "
                f"select() changes the result type from entities to dicts. "
                f"Move .select() to the end of the chain."
            )

    # ─── Filtering ────────────────────────────────────────────────────────

    def filter(self, predicate: Callable[[EntityProxy[T]], Expr]) -> Self:
        """Add WHERE condition.

        Usage:
            .filter(lambda u: u.balance > 100)
            .filter(lambda u: (u.active == True) & (u.role == "admin"))
        """
        self._check_no_select("filter")
        expr = build_expr(self.entity, predicate)
        from emergent.wire.axis.query._relational import Filter
        return self._append(Filter(expr))

    def where(self, predicate: Callable[[EntityProxy[T]], Expr]) -> Self:
        """Alias for filter()."""
        return self.filter(predicate)

    # ─── Ordering ─────────────────────────────────────────────────────────

    def order_by(
        self, *order_fns: Callable[[EntityProxy[T]], FieldProxy | OrderSpec]
    ) -> Self:
        """Add ORDER BY.

        Usage:
            .order_by(lambda u: u.balance.desc())
            .order_by(lambda u: u.name, lambda u: u.created_at.desc())
        """
        self._check_no_select("order_by")
        from emergent.wire.axis.query._relational import OrderBy
        specs = tuple(build_order(self.entity, fn) for fn in order_fns)
        return self._append(OrderBy(specs))

    # ─── Pagination ───────────────────────────────────────────────────────

    def limit(self, count: int) -> Self:
        """Add LIMIT."""
        from emergent.wire.axis.query._relational import Limit
        return self._append(Limit(count))

    def offset(self, count: int) -> Self:
        """Add OFFSET."""
        from emergent.wire.axis.query._relational import Offset
        return self._append(Offset(count))

    def paginate(self, page: int, per_page: int) -> Self:
        """Convenience: offset + limit for pagination.

        Args:
            page: Page number (1-based, must be >= 1)
            per_page: Items per page (must be >= 1)
        """
        if page < 1:
            raise ValueError(f"page must be >= 1, got {page}")
        if per_page < 1:
            raise ValueError(f"per_page must be >= 1, got {per_page}")
        return self.offset((page - 1) * per_page).limit(per_page)

    # ─── Projection ───────────────────────────────────────────────────────

    def select(self, *field_fns: Callable[[EntityProxy[T]], FieldProxy]) -> Self:
        """SELECT specific fields only.

        Usage:
            .select(lambda u: u.name, lambda u: u.email)
        """
        if not field_fns:
            raise ValueError("select() requires at least one field")
        from emergent.wire.axis.query._relational import Select
        proxy = EntityProxy(self.entity)
        fields = tuple(fn(proxy).name for fn in field_fns)
        return self._append(Select(fields))

    def distinct(self) -> Self:
        """SELECT DISTINCT."""
        self._check_no_select("distinct")
        from emergent.wire.axis.query._relational import Distinct
        return self._append(Distinct())

    # ─── Joins ────────────────────────────────────────────────────────────

    def join(
        self,
        target: type[Other],
        on: Callable[[EntityProxy[T], EntityProxy[Other]], Expr],
        *,
        tablename: str | None = None,
    ) -> Self:
        """INNER JOIN.

        Usage:
            .join(Post, on=lambda u, p: u.id == p.author_id, tablename="posts")
        """
        self._check_no_select("join")
        from emergent.wire.axis.query._relational import Join
        left_proxy = EntityProxy(self.entity)
        right_proxy = EntityProxy(target)
        expr = on(left_proxy, right_proxy)
        return self._append(Join(target, expr, "inner", tablename))

    def left_join(
        self,
        target: type[Other],
        on: Callable[[EntityProxy[T], EntityProxy[Other]], Expr],
        *,
        tablename: str | None = None,
    ) -> Self:
        """LEFT JOIN."""
        self._check_no_select("left_join")
        from emergent.wire.axis.query._relational import Join
        left_proxy = EntityProxy(self.entity)
        right_proxy = EntityProxy(target)
        expr = on(left_proxy, right_proxy)
        return self._append(Join(target, expr, "left", tablename))

    # ─── Grouping ─────────────────────────────────────────────────────────

    def group_by(self, *field_fns: Callable[[EntityProxy[T]], FieldProxy]) -> Self:
        """GROUP BY fields.

        Usage:
            .group_by(lambda u: u.role)
        """
        self._check_no_select("group_by")
        if not field_fns:
            raise ValueError("group_by() requires at least one field")
        from emergent.wire.axis.query._relational import GroupBy
        fields = tuple(fn(EntityProxy(self.entity)).name for fn in field_fns)
        return self._append(GroupBy(fields))

    def having(self, predicate: Callable[[EntityProxy[T]], Expr]) -> Self:
        """HAVING clause (filter after GROUP BY)."""
        self._check_no_select("having")
        from emergent.wire.axis.query._relational import Having
        expr = build_expr(self.entity, predicate)
        return self._append(Having(expr))

    # ─── Aggregation ──────────────────────────────────────────────────────

    def aggregate(
        self,
        **aggregates: Callable[[EntityProxy[T]], AggregateExpr],
    ) -> Self:
        """Add aggregates.

        Usage:
            .aggregate(
                total=lambda u: u.balance.sum(),
                avg_balance=lambda u: u.balance.avg(),
                user_count=lambda u: u.count(),
            )
        """
        from emergent.wire.axis.query._relational import Aggregate, AggregateSpec
        proxy = EntityProxy(self.entity)
        specs: list[AggregateSpec] = []
        for alias, agg_fn in aggregates.items():
            expr = agg_fn(proxy)
            specs.append(AggregateSpec(func=expr.func, field=expr.field, alias=alias))
        return self._append(Aggregate(tuple(specs)))

    # ─── Introspection ────────────────────────────────────────────────────

    @property
    def filters(self) -> list[Expr]:
        """All filter expressions."""
        from emergent.wire.axis.query._relational import Filter
        return [op.expr for op in self.ops if isinstance(op, Filter)]

    @property
    def ordering(self) -> list[OrderSpec]:
        """All order specs."""
        from emergent.wire.axis.query._relational import OrderBy
        result: list[OrderSpec] = []
        for op in self.ops:
            if isinstance(op, OrderBy):
                result.extend(op.specs)
        return result

    @property
    def limit_value(self) -> int | None:
        from emergent.wire.axis.query._relational import Limit
        for op in self.ops:
            if isinstance(op, Limit):
                return op.count
        return None

    @property
    def offset_value(self) -> int | None:
        from emergent.wire.axis.query._relational import Offset
        for op in self.ops:
            if isinstance(op, Offset):
                return op.count
        return None

    @property
    def has_aggregates(self) -> bool:
        """Check if query has aggregates."""
        from emergent.wire.axis.query._relational import Aggregate
        return any(isinstance(op, Aggregate) for op in self.ops)

    @property
    def aggregates(self) -> list[AggregateSpec]:
        """All aggregate specs."""
        from emergent.wire.axis.query._relational import Aggregate
        result: list[AggregateSpec] = []
        for op in self.ops:
            if isinstance(op, Aggregate):
                result.extend(op.specs)
        return result

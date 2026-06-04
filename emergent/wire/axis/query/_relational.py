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

Ops are self-compiling capabilities — each implements compile_memory_query
and compile_sa_query, dispatched via fold() from _core.py. Symmetric with
compile-axis capabilities (compile_pydantic, compile_openapi, etc.).
"""

from __future__ import annotations

import dataclasses as _dc
from dataclasses import dataclass, field, replace
from typing import Any, TYPE_CHECKING, Generic, Hashable, Literal, TypeVar

from emergent.wire.axis.query._expr import Expr
from emergent.wire.axis.query._proxy import OrderSpec
from emergent.wire.axis.query._aggregate import AggregateSpec
from emergent.wire.axis.query._base_qs import RelationalMixin
from emergent.wire.axis._explain import AutoExplain, ExplainContext, ExplainNode

if TYPE_CHECKING:
    from emergent.wire.axis.query._contexts import (
        MemoryQueryContext, SAQueryContext,
        MemoryAPIContext, HTTPAPIContext,
    )


T = TypeVar("T")


# ─── Operations ───────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Filter:
    """WHERE / filter clause — cross-compilable.

    Implements 4 protocols: memory_query, sa_query, memory_api, http_api.
    Same op works for relational AND API backends.
    """
    expr: Expr

    def compile_memory_query(self, ctx: MemoryQueryContext) -> MemoryQueryContext:
        return replace(ctx, data=[item for item in ctx.data if self.expr.evaluate(item)])

    def compile_sa_query(self, ctx: SAQueryContext) -> SAQueryContext:
        clause = ctx.compile_expr(self.expr)
        return replace(ctx, stmt=ctx.stmt.where(clause))

    def compile_memory_api(self, ctx: MemoryAPIContext) -> MemoryAPIContext:
        return replace(ctx, data=[item for item in ctx.data if self.expr.evaluate(item)])

    def compile_http_api(self, ctx: HTTPAPIContext) -> HTTPAPIContext:
        filter_data = ctx.encode_filter(self.expr)
        if ctx.is_body_filter:
            if ctx.body is None:
                ctx.body = {}
            ctx.body.update(filter_data)
        else:
            ctx.params.update(filter_data)
        return ctx

    def compile_explain(self, ctx: ExplainContext) -> ExplainContext:
        from emergent.wire.axis.query._serialize import expr_fields
        return ctx.add(ExplainNode(kind="Filter", fields=(
            ("expr", str(self.expr)),
            ("fields", sorted(expr_fields(self.expr))),
        )))


@dataclass(frozen=True, slots=True)
class OrderBy:
    """ORDER BY clause — cross-compilable.

    Implements 4 protocols: memory_query, sa_query, memory_api, http_api.
    """
    specs: tuple[OrderSpec, ...]

    def compile_memory_query(self, ctx: MemoryQueryContext) -> MemoryQueryContext:
        result = list(ctx.data)
        for spec in reversed(self.specs):
            result.sort(
                key=lambda item, _f=spec.field: getattr(item, _f),
                reverse=not spec.ascending,
            )
        return replace(ctx, data=result)

    def compile_sa_query(self, ctx: SAQueryContext) -> SAQueryContext:
        stmt = ctx.stmt
        for spec in self.specs:
            col = ctx.get_column(spec.field)
            ordered = ctx.asc(col) if spec.ascending else ctx.desc(col)
            stmt = stmt.order_by(ordered)
        return replace(ctx, stmt=stmt)

    def compile_memory_api(self, ctx: MemoryAPIContext) -> MemoryAPIContext:
        result = list(ctx.data)
        for spec in reversed(self.specs):
            result.sort(
                key=lambda item, _f=spec.field: getattr(item, _f),
                reverse=not spec.ascending,
            )
        return replace(ctx, data=result)

    def compile_http_api(self, ctx: HTTPAPIContext) -> HTTPAPIContext:
        if ctx.encode_order is not None:
            ctx.params.update(ctx.encode_order(self.specs))
        return ctx

    def compile_explain(self, ctx: ExplainContext) -> ExplainContext:
        specs = [
            f"{s.field} {'ASC' if s.ascending else 'DESC'}" for s in self.specs
        ]
        return ctx.add(ExplainNode(kind="OrderBy", fields=(("specs", specs),)))


@dataclass(frozen=True, slots=True)
class Limit:
    """LIMIT clause — cross-compilable.

    Implements 4 protocols: memory_query, sa_query, memory_api, http_api.
    """
    count: int

    def __post_init__(self) -> None:
        if self.count < 0:
            raise ValueError(f"LIMIT must be non-negative, got {self.count}")

    def compile_memory_query(self, ctx: MemoryQueryContext) -> MemoryQueryContext:
        return replace(ctx, data=ctx.data[:self.count])

    def compile_sa_query(self, ctx: SAQueryContext) -> SAQueryContext:
        return replace(ctx, stmt=ctx.stmt.limit(self.count))

    def compile_memory_api(self, ctx: MemoryAPIContext) -> MemoryAPIContext:
        return replace(ctx, data=ctx.data[:self.count])

    def compile_http_api(self, ctx: HTTPAPIContext) -> HTTPAPIContext:
        if ctx.encode_limit is not None:
            ctx.params.update(ctx.encode_limit(self.count))
        return ctx

    def compile_explain(self, ctx: ExplainContext) -> ExplainContext:
        return ctx.add(ExplainNode(kind="Limit", fields=(("count", self.count),)))


@dataclass(frozen=True, slots=True)
class Offset:
    """OFFSET clause."""
    count: int

    def __post_init__(self) -> None:
        if self.count < 0:
            raise ValueError(f"OFFSET must be non-negative, got {self.count}")

    def compile_memory_query(self, ctx: MemoryQueryContext) -> MemoryQueryContext:
        return replace(ctx, data=ctx.data[self.count:])

    def compile_sa_query(self, ctx: SAQueryContext) -> SAQueryContext:
        return replace(ctx, stmt=ctx.stmt.offset(self.count))

    def compile_explain(self, ctx: ExplainContext) -> ExplainContext:
        return ctx.add(ExplainNode(kind="Offset", fields=(("count", self.count),)))


@dataclass(frozen=True, slots=True)
class Select:
    """SELECT projection (empty = all) — cross-compilable.

    Implements 4 protocols: memory_query, sa_query, memory_api, http_api.
    """
    fields: tuple[str, ...]

    def compile_memory_query(self, ctx: MemoryQueryContext) -> MemoryQueryContext:
        projected: list[Any] = [
            {f: getattr(item, f) for f in self.fields}
            for item in ctx.data
        ]
        return replace(ctx, data=projected)

    def compile_sa_query(self, ctx: SAQueryContext) -> SAQueryContext:
        return replace(ctx, stmt=ctx.select_columns(ctx.stmt, self.fields))

    def compile_memory_api(self, ctx: MemoryAPIContext) -> MemoryAPIContext:
        projected: list[Any] = [
            {f: getattr(item, f) for f in self.fields}
            for item in ctx.data
        ]
        return replace(ctx, data=projected)

    def compile_http_api(self, ctx: HTTPAPIContext) -> HTTPAPIContext:
        if ctx.encode_select is not None:
            ctx.params.update(ctx.encode_select(self.fields))
        return ctx

    def compile_explain(self, ctx: ExplainContext) -> ExplainContext:
        return ctx.add(ExplainNode(kind="Select", fields=(
            ("fields", list(self.fields)),
        )))


JoinKind = Literal["inner", "left", "right", "outer"]


@dataclass(frozen=True, slots=True)
class Join:
    """JOIN clause."""
    target: type
    on: Expr
    kind: JoinKind = "inner"
    tablename: str | None = None

    def compile_sa_query(self, ctx: SAQueryContext) -> SAQueryContext:
        new_stmt = ctx.join(ctx.stmt, self.target, self.on, self.kind, self.tablename)
        return replace(ctx, stmt=new_stmt)

    def compile_explain(self, ctx: ExplainContext) -> ExplainContext:
        return ctx.add(ExplainNode(kind="Join", fields=(
            ("target", self.target.__name__),
            ("kind", self.kind),
            ("on", str(self.on)),
        )))


@dataclass(frozen=True, slots=True)
class GroupBy(AutoExplain):
    """GROUP BY clause."""
    fields: tuple[str, ...]

    def compile_sa_query(self, ctx: SAQueryContext) -> SAQueryContext:
        cols = [ctx.get_column(f) for f in self.fields]
        return replace(ctx, stmt=ctx.stmt.group_by(*cols))

    def compile_explain(self, ctx: ExplainContext) -> ExplainContext:
        return ctx.add(ExplainNode(kind="GroupBy", fields=(
            ("fields", list(self.fields)),
        )))


@dataclass(frozen=True, slots=True)
class Having:
    """HAVING clause (filter after GROUP BY)."""
    expr: Expr

    def compile_sa_query(self, ctx: SAQueryContext) -> SAQueryContext:
        clause = ctx.compile_expr(self.expr)
        return replace(ctx, stmt=ctx.stmt.having(clause))

    def compile_explain(self, ctx: ExplainContext) -> ExplainContext:
        return ctx.add(ExplainNode(kind="Having", fields=(("expr", str(self.expr)),)))


@dataclass(frozen=True, slots=True)
class Distinct:
    """DISTINCT modifier — cross-compilable.

    Implements 3 protocols: memory_query, sa_query, memory_api.
    """

    def compile_explain(self, ctx: ExplainContext) -> ExplainContext:
        return ctx.add(ExplainNode(kind="Distinct"))

    def _deduplicate(self, data: list[Any]) -> list[Any]:
        seen: set[Hashable] = set()
        unique: list[Any] = []
        for item in data:
            if _dc.is_dataclass(item):
                key: Hashable = tuple(
                    getattr(item, f.name) for f in _dc.fields(item)
                )
            else:
                key = item
            if key not in seen:
                seen.add(key)
                unique.append(item)
        return unique

    def compile_memory_query(self, ctx: MemoryQueryContext) -> MemoryQueryContext:
        return replace(ctx, data=self._deduplicate(ctx.data))

    def compile_sa_query(self, ctx: SAQueryContext) -> SAQueryContext:
        return replace(ctx, stmt=ctx.stmt.distinct())

    def compile_memory_api(self, ctx: MemoryAPIContext) -> MemoryAPIContext:
        return replace(ctx, data=self._deduplicate(ctx.data))


@dataclass(frozen=True, slots=True)
class Aggregate:
    """Aggregate operation.

    Contains multiple aggregate specs to compute.
    Handled by provider.aggregate() method, not by fold.
    """

    specs: tuple[AggregateSpec, ...]

    def compile_memory_query(self, ctx: MemoryQueryContext) -> MemoryQueryContext:
        # Aggregate is handled by provider.aggregate(), not by fold.
        # Pass through unchanged.
        return ctx

    def compile_sa_query(self, ctx: SAQueryContext) -> SAQueryContext:
        # Aggregate is handled by provider.aggregate(), not by fold.
        return ctx

    def compile_explain(self, ctx: ExplainContext) -> ExplainContext:
        specs = [
            f"{s.alias}={type(s.func).__name__}({s.field or '*'})"
            for s in self.specs
        ]
        return ctx.add(ExplainNode(kind="Aggregate", fields=(("specs", specs),)))


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

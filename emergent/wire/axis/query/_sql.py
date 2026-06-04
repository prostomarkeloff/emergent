"""SQL-specific query operations and QuerySet.

Extends the universal RelationalQuerySet with operations that only
SQL databases support: window functions, row locking, RETURNING.

    from emergent.wire.axis.query import sql_relational, SQLRelationalQuerySet

    q = (
        sql_relational(User)
            .filter(lambda u: u.balance > 0)
            .window(
                row_num=lambda u: u.row_number().over(
                    partition_by=u.department,
                    order_by=u.salary.desc(),
                ),
            )
            .for_update(nowait=True)
    )

Open-world compatible: universal providers silently skip SQL ops.
Use .to_relational() to strip SQL ops for universal providers.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Callable, Generic, TypeVar

if TYPE_CHECKING:
    from emergent.wire.axis.query._contexts import SAQueryContext

from emergent.wire.axis.query._aggregate import AggregateFunc
from emergent.wire.axis.query._base_qs import RelationalMixin
from emergent.wire.axis.query._proxy import (
    EntityProxy,
    FieldProxy,
    OrderSpec,
)
from emergent.wire.axis.query._relational import (
    RelationalOp,
    RelationalQuerySet,
)
from emergent.wire.axis.query._window import WindowSpec


T = TypeVar("T")


# ═══════════════════════════════════════════════════════════════════════════════
# SQL-Specific Operations
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Window:
    """Window function operation.

    Contains named window specifications computed as extra columns.

        Window(specs=(
            WindowSpec(func=RowNumber(), field=None,
                       partition_by=("dept",), order_by=(...,), alias="rn"),
        ))
    """

    specs: tuple[WindowSpec, ...]

    def compile_sa_query(self, ctx: SAQueryContext) -> SAQueryContext:
        stmt = ctx.stmt
        for spec in self.specs:
            win_col = ctx.window_func(spec)
            stmt = stmt.add_columns(win_col)
        return replace(ctx, stmt=stmt)


@dataclass(frozen=True, slots=True)
class ForUpdate:
    """Row locking — SELECT ... FOR UPDATE.

        ForUpdate()                          # basic lock
        ForUpdate(nowait=True)               # fail immediately if locked
        ForUpdate(skip_locked=True)          # skip locked rows
    """

    nowait: bool = False
    skip_locked: bool = False

    def compile_sa_query(self, ctx: SAQueryContext) -> SAQueryContext:
        return replace(ctx, stmt=ctx.stmt.with_for_update(
            nowait=self.nowait, skip_locked=self.skip_locked,
        ))


@dataclass(frozen=True, slots=True)
class Returning:
    """RETURNING clause — get values back after mutations.

        Returning(fields=())                 # RETURNING *
        Returning(fields=("id", "name"))     # RETURNING id, name
    """

    fields: tuple[str, ...]

    def compile_sa_query(self, ctx: SAQueryContext) -> SAQueryContext:
        # Returning is not applicable to SELECT; used by delete_returning().
        return ctx


# Union of SQL-specific ops
SQLOp = Window | ForUpdate | Returning

# Combined union: relational + SQL
SQLRelationalOp = RelationalOp | SQLOp


# ═══════════════════════════════════════════════════════════════════════════════
# WindowBuilder — intermediate builder for .over() chaining
# ═══════════════════════════════════════════════════════════════════════════════


class WindowBuilder:
    """Intermediate builder for window specification.

    Created by proxy methods, finalized by .over():

        u.row_number().over(partition_by=u.department, order_by=u.salary.desc())

    The .over() call resolves proxy arguments into concrete strings
    and returns a WindowSpec.
    """

    __slots__ = ("_func", "_field")

    def __init__(self, func: AggregateFunc, field: str | None) -> None:
        self._func = func
        self._field = field

    def over(
        self,
        partition_by: FieldProxy | tuple[FieldProxy, ...] | None = None,
        order_by: OrderSpec | tuple[OrderSpec, ...] | FieldProxy | tuple[FieldProxy, ...] | None = None,
    ) -> WindowSpec:
        """Finalize window specification with OVER clause.

        Args:
            partition_by: Field(s) to partition by.
            order_by: OrderSpec(s) or FieldProxy(s) for ordering.

        Returns:
            WindowSpec ready for inclusion in Window op.
        """
        # Resolve partition_by
        pb: tuple[str, ...] = ()
        if partition_by is not None:
            if isinstance(partition_by, FieldProxy):
                pb = (partition_by.name,)
            else:
                names: list[str] = []
                for p in partition_by:
                    if not isinstance(p, FieldProxy):
                        raise TypeError(f"partition_by expects FieldProxy, got {type(p)}")
                    names.append(p.name)
                pb = tuple(names)

        # Resolve order_by
        ob: tuple[OrderSpec, ...] = ()
        if order_by is not None:
            if isinstance(order_by, OrderSpec):
                ob = (order_by,)
            elif isinstance(order_by, FieldProxy):
                ob = (OrderSpec(order_by.name, ascending=True),)
            else:
                # Runtime guard: callers may pass invalid types (e.g. str) despite type signature.
                if not isinstance(order_by, Iterable) or isinstance(order_by, str):
                    raise TypeError(f"order_by expects OrderSpec, FieldProxy, or tuple, got {type(order_by)}")
                resolved: list[OrderSpec] = []
                for o in order_by:
                    if isinstance(o, OrderSpec):
                        resolved.append(o)
                    elif isinstance(o, FieldProxy):
                        resolved.append(OrderSpec(o.name, ascending=True))
                    else:
                        raise TypeError(f"order_by expects OrderSpec or FieldProxy, got {type(o)}")
                ob = tuple(resolved)

        # Alias will be set by SQLRelationalQuerySet.window()
        return WindowSpec(
            func=self._func,
            field=self._field,
            partition_by=pb,
            order_by=ob,
            alias="",  # placeholder, set by caller
        )


# ═══════════════════════════════════════════════════════════════════════════════
# SQLRelationalQuerySet
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class SQLRelationalQuerySet(RelationalMixin[T], Generic[T]):
    """SQL-specific relational query.

    Extends RelationalQuerySet with SQL-only operations:
    - window() — window functions (ROW_NUMBER, RANK, SUM OVER, etc.)
    - for_update() — row locking
    - returning() — RETURNING clause for mutations

    Immutable. Each method returns new QuerySet.

    Usage:
        q = (
            sql_relational(User)
                .filter(lambda u: u.active == True)
                .window(
                    row_num=lambda u: u.row_number().over(
                        partition_by=u.department,
                        order_by=u.salary.desc(),
                    ),
                )
                .for_update(nowait=True)
                .returning("id", "name")
        )
    """

    entity: type[T]
    ops: tuple[SQLRelationalOp, ...] = field(default_factory=tuple)

    def _append(self, op: SQLRelationalOp) -> SQLRelationalQuerySet[T]:
        return SQLRelationalQuerySet(entity=self.entity, ops=(*self.ops, op))

    # ─── SQL-Specific Operations ──────────────────────────────────────────

    def window(
        self,
        **windows: Callable[[EntityProxy[T]], WindowSpec],
    ) -> SQLRelationalQuerySet[T]:
        """Add window functions.

        Each kwarg is alias=lambda that returns a WindowSpec:

            .window(
                row_num=lambda u: u.row_number().over(
                    partition_by=u.department,
                    order_by=u.salary.desc(),
                ),
                running_total=lambda u: u.balance.sum().over(
                    partition_by=u.department,
                ),
            )
        """
        proxy = EntityProxy(self.entity)
        specs: list[WindowSpec] = []

        for alias, win_fn in windows.items():
            spec = win_fn(proxy)
            # Set the alias from the kwarg name
            spec = WindowSpec(
                func=spec.func,
                field=spec.field,
                partition_by=spec.partition_by,
                order_by=spec.order_by,
                alias=alias,
            )
            specs.append(spec)

        return self._append(Window(tuple(specs)))

    def for_update(
        self,
        nowait: bool = False,
        skip_locked: bool = False,
    ) -> SQLRelationalQuerySet[T]:
        """Add FOR UPDATE row locking.

            .for_update()                    # basic lock
            .for_update(nowait=True)         # NOWAIT
            .for_update(skip_locked=True)    # SKIP LOCKED
        """
        return self._append(ForUpdate(nowait=nowait, skip_locked=skip_locked))

    def returning(self, *fields: str) -> SQLRelationalQuerySet[T]:
        """Add RETURNING clause for mutations.

            .returning()                 # RETURNING *
            .returning("id", "name")     # RETURNING id, name
        """
        return self._append(Returning(fields))

    # ─── SQL Introspection ────────────────────────────────────────────────

    @property
    def has_windows(self) -> bool:
        """Check if query has window functions."""
        return any(isinstance(op, Window) for op in self.ops)

    @property
    def windows(self) -> list[WindowSpec]:
        """All window specs."""
        result: list[WindowSpec] = []
        for op in self.ops:
            if isinstance(op, Window):
                result.extend(op.specs)
        return result

    @property
    def has_for_update(self) -> bool:
        """Check if query has FOR UPDATE."""
        return any(isinstance(op, ForUpdate) for op in self.ops)

    @property
    def has_returning(self) -> bool:
        """Check if query has RETURNING."""
        return any(isinstance(op, Returning) for op in self.ops)

    # ─── Conversion ───────────────────────────────────────────────────────

    _SQL_ONLY: frozenset[type] = frozenset({Window, ForUpdate, Returning})

    def to_relational(self) -> RelationalQuerySet[T]:
        """Strip SQL ops, returning universal RelationalQuerySet.

        Useful for passing to universal providers (memory, etc.)
        that don't understand SQL-specific operations.

        Open-world: excludes known SQL-only types. New universal ops
        pass through automatically.
        """
        universal: list[RelationalOp] = []
        for op in self.ops:
            if not isinstance(op, (Window, ForUpdate, Returning)):
                universal.append(op)
        return RelationalQuerySet(entity=self.entity, ops=tuple(universal))


def sql_relational(entity: type[T]) -> SQLRelationalQuerySet[T]:
    """Create SQL relational QuerySet for entity.

    Usage:
        users = sql_relational(User)
        q = users.filter(lambda u: u.active == True).for_update()
    """
    return SQLRelationalQuerySet(entity=entity)


__all__ = (
    # SQL ops
    "Window",
    "ForUpdate",
    "Returning",
    "SQLOp",
    "SQLRelationalOp",
    # Builder
    "WindowBuilder",
    # QuerySet
    "SQLRelationalQuerySet",
    "sql_relational",
)

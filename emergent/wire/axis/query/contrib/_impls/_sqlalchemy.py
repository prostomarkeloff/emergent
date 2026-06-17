"""SQLAlchemy relational provider — production database backend.

IMPORTANT: Caller owns the session and transaction. Provider does NOT commit.

Usage:
    from emergent.wire.axis.query.contrib import sqlalchemy as sa_query

    # Option A: inline (per-request session)
    provider = sa_query.provider(session, User, "users")

    # Option B: store factory (configure once, bind per-request)
    UserStore = sa_query.store(User, "users")
    provider = UserStore(session)

    # Query
    users = await provider.fetch_many(
        relational(User).filter(lambda u: u.active == True).limit(10)
    )

    # Mutate
    await provider.insert(User(id=0, name="Alice"))
    await session.commit()  # caller commits!

Requires: sqlalchemy[asyncio]
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from sqlalchemy import CursorResult, delete, func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.sql import ColumnElement, Subquery

from emergent.wire.axis.query._relational import (
    RelationalQuerySet,
    AggregateSpec,
)
from emergent.wire.axis.query._aggregate import (
    Count,
    Sum,
    Avg,
    Min,
    Max,
    ArrayAgg,
    StringAgg,
)
from emergent.wire.axis.query._sql import (
    Returning,
    SQLRelationalQuerySet,
)
from emergent.wire.axis.query._contexts import SAQueryContext, SAQueryCompilable
from emergent.wire.axis.query._window import (
    WindowSpec,
    RowNumber,
    Rank,
    DenseRank,
    Ntile,
    Lag,
    Lead,
)
from emergent.wire.axis.query._provider import NextId
from emergent.wire.compile._core import fold

# Reuse from compile target
from emergent.wire.compile._phase import Compilation, to_storage_dict
from emergent.wire.compile.targets.sqlalchemy import (
    compile_sa,
    compile_expr as _compile_expr_raw,
    entity_to_model,
    model_to_entity,
)


T = TypeVar("T")

type StrAnyMap = dict[str, Any]
type TypeAnyMap = dict[type, Any]
type WindowHandlerMap = dict[type, Callable[[WindowSpec], Any]]
type WindowHandlerMapping = Mapping[type, Callable[[WindowSpec], Any]]
type AggHandlerMap = dict[type, Callable[[AggregateSpec, Any], Any]]
type AggHandlerMapping = Mapping[type, Callable[[AggregateSpec, Any], Any]]


# ═══════════════════════════════════════════════════════════════════════════════
# NextId strategies for SQL databases
# ═══════════════════════════════════════════════════════════════════════════════


class AutoIncrementNextId:
    """Placeholder for DB-assigned autoincrement IDs.

    Returns 0. The provider's insert() detects this and excludes the
    identity column, letting the database assign the real ID via
    autoincrement. After flush, the model instance has the DB-assigned ID.
    """

    __slots__ = ()

    async def next_id(self) -> int:
        return 0


@dataclass(slots=True)
class SASequenceNextId:
    """Query a named database sequence for next ID.

    Useful when you need the ID before insert (e.g., for pre-insert
    references or UUID sequences managed by the database).
    """

    _session: AsyncSession
    _sequence_name: str

    async def next_id(self) -> int:
        from sqlalchemy import Sequence

        seq = Sequence(self._sequence_name)
        result = await self._session.execute(seq)
        return result.scalar_one()


# ═══════════════════════════════════════════════════════════════════════════════
# Core Provider
# ═══════════════════════════════════════════════════════════════════════════════


class SQLAlchemyRelationalProvider(Generic[T]):
    """SQLAlchemy async relational provider.

    Implements MutatingRelationalProvider[T] protocol.
    Caller owns session — provider does NOT commit.
    """

    __slots__ = ("_session", "_compiled", "_next_id")

    def __init__(
        self,
        session: AsyncSession,
        compiled: Compilation[T, DeclarativeBase],
        next_id: NextId[Any] | None = None,
    ) -> None:
        self._session = session
        self._compiled = compiled
        self._next_id: Any = next_id if next_id is not None else AutoIncrementNextId()

    # ─── NextId ────────────────────────────────────────────────────────────

    async def next_id(self) -> Any:
        """Generate next ID. Default: 0 (autoincrement placeholder)."""
        return await self._next_id.next_id()

    # ─── Read Operations ───────────────────────────────────────────────────

    async def fetch_one(self, query: RelationalQuerySet[T]) -> T | None:
        stmt = self._compile_query(query).limit(1)
        result = await self._session.execute(stmt)
        row = result.scalars().first()
        return model_to_entity(row, self._compiled) if row is not None else None

    async def fetch_many(self, query: RelationalQuerySet[T]) -> list[T]:
        stmt = self._compile_query(query)
        result = await self._session.execute(stmt)
        rows = result.scalars().all()
        return [model_to_entity(row, self._compiled) for row in rows]

    async def count(self, query: RelationalQuerySet[T]) -> int:
        subq = self._compile_query(query).subquery()
        stmt = select(func.count()).select_from(subq)
        result = await self._session.execute(stmt)
        return result.scalar_one()

    async def exists(self, query: RelationalQuerySet[T]) -> bool:
        stmt = self._compile_query(query).limit(1)
        result = await self._session.execute(stmt)
        return result.first() is not None

    async def aggregate(self, query: RelationalQuerySet[T]) -> StrAnyMap:
        agg_specs = query.aggregates

        if not agg_specs:
            return {}

        # Compile base query with all ops (Filter/Join/GroupBy/Having),
        # then wrap as subquery so aggregates run on the correct row set.
        base = self._compile_query(query).subquery()
        agg_cols = [
            self._compile_aggregate_func(spec, base) for spec in agg_specs
        ]
        stmt = select(*agg_cols).select_from(base)

        result = await self._session.execute(stmt)
        row = result.one()
        return {spec.alias: row[i] for i, spec in enumerate(agg_specs)}

    # ─── Write Operations ──────────────────────────────────────────────────

    async def insert(self, entity: T) -> T:
        if not dataclasses.is_dataclass(entity) or isinstance(entity, type):
            raise TypeError(f"insert() requires a dataclass entity, got {type(entity).__name__}")
        data = to_storage_dict(entity, self._compiled.fields)

        # Exclude any identity column still holding the autoincrement
        # placeholder (0 or None) so the database assigns the real value.
        # Composite keys (association tables) carry several identity columns;
        # only the placeholders are dropped, real key values are kept.
        for identity in self._compiled.identity_fields:
            if data.get(identity) in (0, None):
                data.pop(identity, None)

        model_instance = self._compiled.model(**data)
        self._session.add(model_instance)
        await self._session.flush()

        return model_to_entity(model_instance, self._compiled)

    async def update(self, entity: T) -> T:
        model_instance = entity_to_model(entity, self._compiled)
        merged = await self._session.merge(model_instance)
        await self._session.flush()
        return model_to_entity(merged, self._compiled)

    async def delete(self, entity: T) -> None:
        identity_fields = self._compiled.identity_fields
        if identity_fields:
            # session.get takes a scalar for a single key, a tuple (in PK
            # column order) for a composite key.
            values = tuple(getattr(entity, name) for name in identity_fields)
            key = values[0] if len(values) == 1 else values
            existing = await self._session.get(self._compiled.model, key)
            if existing is not None:
                await self._session.delete(existing)
                await self._session.flush()
        else:
            model_instance = entity_to_model(entity, self._compiled)
            merged = await self._session.merge(model_instance)
            await self._session.delete(merged)
            await self._session.flush()

    def _pk_match(
        self, query: RelationalQuerySet[T] | SQLRelationalQuerySet[T]
    ) -> "tuple[ColumnElement[Any], Subquery]":
        """Build the primary-key match expression for a bulk delete.

        Returns (key, subquery) where `key.in_(select(subquery))` selects the
        rows the query identifies. For a single key the match is on one column;
        for a composite key it is on the column tuple (in PK order), so only
        rows matching the whole key are affected.

        Any: SQLAlchemy's ColumnElement is generic over the column's Python
        type, and a composite key mixes heterogeneous column types — there is
        no single concrete parameter that covers them.
        """
        pk_cols = [
            getattr(self._compiled.model, name)
            for name in self._compiled.identity_fields
        ]
        subq = self._compile_query(query).with_only_columns(*pk_cols).subquery()
        key = pk_cols[0] if len(pk_cols) == 1 else tuple_(*pk_cols)
        return key, subq

    async def delete_where(self, query: RelationalQuerySet[T]) -> int:
        if not self._compiled.identity_fields:
            raise TypeError(
                "delete_where() requires an identity field on the entity "
                "(annotate a field with Identity)"
            )
        key, subq = self._pk_match(query)
        stmt = delete(self._compiled.model).where(key.in_(select(subq)))
        result = await self._session.execute(stmt)
        await self._session.flush()
        # A DELETE statement yields a CursorResult, which exposes rowcount; the
        # generic Result base does not. The narrowing reflects the runtime type.
        assert isinstance(result, CursorResult)
        return result.rowcount

    async def delete_returning(self, query: SQLRelationalQuerySet[T]) -> list[T]:
        """DELETE ... RETURNING — delete rows and return deleted entities.

        Uses SQL RETURNING clause to get deleted entities in a single query.
        Requires a database that supports RETURNING (PostgreSQL, SQLite 3.35+).

            deleted = await provider.delete_returning(
                sql_relational(User)
                    .filter(lambda u: u.active == False)
                    .returning()
            )
        """
        if not self._compiled.identity_fields:
            raise TypeError(
                "delete_returning() requires an identity field on the entity "
                "(annotate a field with Identity)"
            )

        # Build WHERE clause matching the (possibly composite) primary key.
        key, subq = self._pk_match(query)
        stmt = delete(self._compiled.model).where(key.in_(select(subq)))

        # Add RETURNING columns
        returning_fields = self._extract_returning_fields(query)
        if returning_fields:
            cols = [getattr(self._compiled.model, f) for f in returning_fields]
            stmt = stmt.returning(*cols)
        else:
            # RETURNING * — return all columns
            stmt = stmt.returning(self._compiled.model)

        result = await self._session.execute(stmt)
        rows = result.fetchall()
        await self._session.flush()

        if returning_fields:
            # Partial RETURNING returns only the selected columns, so the rows are
            # field dicts that cannot be reconstructed into full entities. The
            # SQLRelationalProvider protocol (axis/query/_provider.py) exposes a single
            # list[T] surface for both shapes — callers requesting partial fields opt
            # out of the entity contract and read the dicts directly. Widening the
            # public protocol return to admit projection rows would break the documented
            # `delete_returning -> list[entity]` API, so the heterogeneity is absorbed
            # here as list[Any] (the one place it is unavoidable) rather than leaked out.
            partial_rows: list[Any] = [
                {f: row[i] for i, f in enumerate(returning_fields)}
                for row in rows
            ]
            return partial_rows
        # Full RETURNING — reconstruct entities (sound: model_to_entity returns T).
        return [model_to_entity(row[0], self._compiled) for row in rows]

    # ─── Query Compilation ─────────────────────────────────────────────────

    def _build_sa_context(self) -> SAQueryContext:
        """Build SAQueryContext with closures over compiled model.

        Each closure captures self._compiled so ops never import sqlalchemy.
        Symmetric with compile-axis contexts (PydanticContext, etc.).
        """
        compiled = self._compiled
        model = compiled.model

        def get_column(name: str) -> Any:
            return getattr(model, name)

        def do_compile_expr(expr: Any) -> Any:
            return _compile_expr_raw(expr, compiled)

        def asc(col: Any) -> Any:
            return col.asc()

        def desc(col: Any) -> Any:
            return col.desc()

        def do_join(stmt: Any, target: type, on_expr: Any, kind: str, tablename: str | None) -> Any:
            if tablename is None:
                raise TypeError(
                    f"Join target {target.__name__} requires explicit tablename. "
                    f"Use .join({target.__name__}, on=..., tablename='...')"
                )
            base = next(
                (cls for cls in model.__mro__
                 if issubclass(cls, DeclarativeBase) and cls is not model and cls is not DeclarativeBase),
                None,
            )
            join_compiled: Compilation[Any, DeclarativeBase] = compile_sa(target, tablename, base=base)
            on_clause = _compile_expr_raw(on_expr, compiled, join_compiled)
            if kind == "right":
                raise NotImplementedError(
                    "RIGHT JOIN is not supported via SA .join(); restructure as LEFT JOIN with swapped operands"
                )
            return stmt.join(
                join_compiled.model,
                on_clause,
                isouter=(kind in ("left", "outer")),
                full=(kind == "outer"),
            )

        def window_func(spec: Any) -> Any:
            return self._compile_window_spec(spec)

        def select_columns(stmt: Any, fields: Any) -> Any:
            cols = [getattr(model, f) for f in fields]
            return select(*cols).select_from(model)

        return SAQueryContext(
            stmt=select(model),
            get_column=get_column,
            compile_expr=do_compile_expr,
            asc=asc,
            desc=desc,
            join=do_join,
            window_func=window_func,
            select_columns=select_columns,
        )

    def _compile_query(self, query: RelationalQuerySet[T] | SQLRelationalQuerySet[T]) -> Any:
        """Compile RelationalQuerySet or SQLRelationalQuerySet ops to SQLAlchemy Select.

        Uses fold() with SAQueryCompilable protocol — ops compile themselves.
        """
        ctx = self._build_sa_context()
        result = fold(query.ops, ctx, SAQueryCompilable, "compile_sa_query")
        return result.stmt

    # ─── Returning Helpers ─────────────────────────────────────────────────

    @staticmethod
    def _extract_returning_fields(query: SQLRelationalQuerySet[T]) -> tuple[str, ...]:
        """Extract RETURNING fields from query ops. Empty = RETURNING *."""
        for op in query.ops:
            if isinstance(op, Returning):
                return op.fields
        return ()

    # ─── Window Compilation ───────────────────────────────────────────────

    def _compile_window_spec(self, spec: WindowSpec) -> Any:
        """Compile WindowSpec to SA func().over().label() expression."""
        sa_func = self._compile_window_func(spec)

        # Build over() kwargs
        over_kw: StrAnyMap = {}
        if spec.partition_by:
            over_kw["partition_by"] = [
                getattr(self._compiled.model, f) for f in spec.partition_by
            ]
        if spec.order_by:
            order_cols: list[Any] = []
            for o in spec.order_by:
                col = getattr(self._compiled.model, o.field)
                order_cols.append(col.asc() if o.ascending else col.desc())
            over_kw["order_by"] = order_cols

        return sa_func.over(**over_kw).label(spec.alias)

    def _compile_window_func(self, spec: WindowSpec, handlers: WindowHandlerMapping | None = None) -> Any:
        """Compile WindowSpec function to SA func expression.

        Args:
            spec: Window specification.
            handlers: Optional handler map keyed by AggregateFunc/WindowFunc type.
                      If None, uses built-in handlers.
        """
        h = handlers if handlers is not None else self._make_window_func_handlers()
        handler = h.get(type(spec.func))
        if handler is not None:
            return handler(spec)
        raise TypeError(f"Unsupported window function: {type(spec.func).__name__}")

    def _make_window_func_handlers(self) -> WindowHandlerMap:
        """Build handler map for window function compilation. Closures capture model."""
        model = self._compiled.model

        def _col_or_none(spec: WindowSpec) -> Any:
            return getattr(model, spec.field) if spec.field else None

        def _lag_lead(sa_fn: Any, spec: WindowSpec) -> Any:
            from emergent.wire.axis.query._window import Lag, Lead
            if not isinstance(spec.func, (Lag, Lead)):
                raise TypeError(f"Expected Lag/Lead, got {type(spec.func)}")
            col = _col_or_none(spec)
            offset = spec.func.offset
            default = spec.func.default
            args: list[Any] = [col, offset] if col is not None else [offset]
            if default is not None:
                args.append(default)
            return sa_fn(*args)

        def _numeric_window(spec: WindowSpec) -> Any:
            if spec.field is None:
                raise TypeError(f"{type(spec.func).__name__} window requires a field")
            col = getattr(model, spec.field)
            fn_map: TypeAnyMap = {Sum: func.sum, Avg: func.avg, Min: func.min, Max: func.max}
            sa_fn = fn_map.get(type(spec.func))
            if sa_fn is None:
                raise TypeError(f"Unsupported numeric window: {type(spec.func).__name__}")
            return sa_fn(col)

        return {
            RowNumber: lambda _s: func.row_number(),
            Rank: lambda _s: func.rank(),
            DenseRank: lambda _s: func.dense_rank(),
            Ntile: lambda s: func.ntile(s.func.num_buckets if isinstance(s.func, Ntile) else 1),
            Lag: lambda s: _lag_lead(func.lag, s),
            Lead: lambda s: _lag_lead(func.lead, s),
            Count: lambda s: func.count(getattr(model, s.field)) if s.field else func.count(),
            Sum: _numeric_window,
            Avg: _numeric_window,
            Min: _numeric_window,
            Max: _numeric_window,
        }

    def _resolve_agg_col(self, spec: AggregateSpec, source: Any = None) -> Any:
        """Resolve column reference for aggregate — from model or subquery."""
        if spec.field is None:
            return None
        if source is not None:
            return source.c[spec.field]
        return getattr(self._compiled.model, spec.field)

    def _compile_aggregate_func(self, spec: AggregateSpec, source: Any = None, handlers: AggHandlerMapping | None = None) -> Any:
        """Compile AggregateSpec to SA func().label().

        Args:
            spec: Aggregate specification.
            source: Subquery or None (uses model).
            handlers: Optional handler map keyed by AggregateFunc type.
                      If None, uses built-in handlers.
        """
        col = self._resolve_agg_col(spec, source)
        h = handlers if handlers is not None else _make_sa_agg_handlers()
        handler = h.get(type(spec.func))
        if handler is not None:
            return handler(spec, col).label(spec.alias)
        raise TypeError(f"Unsupported aggregate: {type(spec.func).__name__}")


def _make_sa_agg_handlers() -> AggHandlerMap:
    """Build handler map for SA aggregate function compilation.

    Each handler takes (spec, resolved_col) and returns a SA func expression
    (before .label()). The col may be None for COUNT(*).
    """
    def _require_col(spec: AggregateSpec, col: Any, name: str) -> Any:
        if col is None:
            raise TypeError(f"{name} requires a field")
        return col

    fn_map = {Sum: func.sum, Avg: func.avg, Min: func.min, Max: func.max}

    return {
        Count: lambda spec, col: func.count() if col is None else func.count(col),
        Sum: lambda spec, col: fn_map[Sum](_require_col(spec, col, "Sum")),
        Avg: lambda spec, col: fn_map[Avg](_require_col(spec, col, "Avg")),
        Min: lambda spec, col: fn_map[Min](_require_col(spec, col, "Min")),
        Max: lambda spec, col: fn_map[Max](_require_col(spec, col, "Max")),
        ArrayAgg: lambda spec, col: func.array_agg(_require_col(spec, col, "ArrayAgg")),
        StringAgg: lambda spec, col: func.string_agg(
            _require_col(spec, col, "StringAgg"),
            spec.func.separator if isinstance(spec.func, StringAgg) else ",",
        ),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Store Factory (configure once, bind session per request)
# ═══════════════════════════════════════════════════════════════════════════════


class SQLAlchemyRelationalStore(Generic[T]):
    """Configure once at startup, bind session per request.

    Usage:
        UserStore = sa_query.store(User, "users")

        # Per-request:
        async with session_factory() as session:
            users = UserStore(session)
            await users.insert(User(...))
            await session.commit()
    """

    __slots__ = ("_compiled", "_next_id_factory")

    def __init__(
        self,
        entity: type[T],
        tablename: str,
        base: type[DeclarativeBase] | None = None,
        next_id: NextId[Any] | None = None,
    ) -> None:
        self._compiled = compile_sa(entity, tablename, base)
        self._next_id_factory = next_id

    @property
    def model(self) -> type[DeclarativeBase]:
        """The compiled SQLAlchemy model class."""
        return self._compiled.model

    def bind(self, session: AsyncSession) -> SQLAlchemyRelationalProvider[T]:
        """Bind to a session, returning a provider."""
        return SQLAlchemyRelationalProvider(
            session=session,
            compiled=self._compiled,
            next_id=self._next_id_factory,
        )

    def __call__(self, session: AsyncSession) -> SQLAlchemyRelationalProvider[T]:
        """Shorthand for bind()."""
        return self.bind(session)


# ═══════════════════════════════════════════════════════════════════════════════
# Factory Functions
# ═══════════════════════════════════════════════════════════════════════════════


def provider(
    session: AsyncSession,
    entity: type[T],
    tablename: str,
    base: type[DeclarativeBase] | None = None,
    next_id: NextId[Any] | None = None,
) -> SQLAlchemyRelationalProvider[T]:
    """Create inline provider (model compiled per call).

    For repeated use, prefer store() which compiles the model once.
    """
    compiled = compile_sa(entity, tablename, base)
    return SQLAlchemyRelationalProvider(
        session=session,
        compiled=compiled,
        next_id=next_id,
    )


def store(
    entity: type[T],
    tablename: str,
    base: type[DeclarativeBase] | None = None,
    next_id: NextId[Any] | None = None,
) -> SQLAlchemyRelationalStore[T]:
    """Create store factory (compile model once, bind session later)."""
    return SQLAlchemyRelationalStore(
        entity=entity,
        tablename=tablename,
        base=base,
        next_id=next_id,
    )


__all__ = (
    # Provider
    "SQLAlchemyRelationalProvider",
    # Store
    "SQLAlchemyRelationalStore",
    # NextId strategies
    "AutoIncrementNextId",
    "SASequenceNextId",
    # Factory functions
    "provider",
    "store",
)

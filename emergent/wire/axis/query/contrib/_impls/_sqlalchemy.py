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
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase

from emergent.wire.axis.query._relational import (
    RelationalQuerySet,
    Filter,
    OrderBy,
    Limit,
    Offset,
    Select,
    Join,
    GroupBy,
    Having,
    Distinct,
    Aggregate,
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
    Window,
    ForUpdate,
    Returning,
    SQLRelationalQuerySet,
)
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

# Reuse from compile target
from emergent.wire.compile._phase import Compilation
from emergent.wire.compile.targets.sqlalchemy import (
    compile_sa,
    compile_expr,
    entity_to_model,
    model_to_entity,
)


T = TypeVar("T")


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

    async def aggregate(self, query: RelationalQuerySet[T]) -> dict[str, Any]:
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
        data = dataclasses.asdict(entity)

        # If identity field has autoincrement placeholder (0 or None),
        # exclude it so the database assigns the real ID.
        identity = self._compiled.identity_field
        if identity and data.get(identity) in (0, None, ""):
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
        identity = self._compiled.identity_field
        if identity:
            key = getattr(entity, identity)
            existing = await self._session.get(self._compiled.model, key)
            if existing is not None:
                await self._session.delete(existing)
                await self._session.flush()
        else:
            model_instance = entity_to_model(entity, self._compiled)
            merged = await self._session.merge(model_instance)
            await self._session.delete(merged)
            await self._session.flush()

    async def delete_where(self, query: RelationalQuerySet[T]) -> int:
        identity = self._compiled.identity_field
        if identity is None:
            raise TypeError(
                "delete_where() requires an identity field on the entity "
                "(annotate a field with Identity)"
            )
        pk = getattr(self._compiled.model, identity)
        subq = (
            self._compile_query(query)
            .with_only_columns(pk)
            .subquery()
        )
        stmt = delete(self._compiled.model).where(pk.in_(select(subq)))
        result = await self._session.execute(stmt)
        await self._session.flush()
        return result.rowcount  # type: ignore[return-value]

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
        identity = self._compiled.identity_field
        if identity is None:
            raise TypeError(
                "delete_returning() requires an identity field on the entity "
                "(annotate a field with Identity)"
            )

        # Build WHERE clause from query filters
        pk = getattr(self._compiled.model, identity)
        subq = (
            self._compile_query(query)
            .with_only_columns(pk)
            .subquery()
        )
        stmt = delete(self._compiled.model).where(pk.in_(select(subq)))

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
            # Partial RETURNING — return dicts (not full entities)
            return [  # type: ignore[return-value]
                {f: row[i] for i, f in enumerate(returning_fields)}
                for row in rows
            ]
        # Full RETURNING — reconstruct entities
        return [model_to_entity(row[0], self._compiled) for row in rows]

    # ─── Query Compilation ─────────────────────────────────────────────────

    def _compile_query(self, query: RelationalQuerySet[T] | SQLRelationalQuerySet[T]) -> Any:
        """Compile RelationalQuerySet or SQLRelationalQuerySet ops to SQLAlchemy Select."""
        stmt = select(self._compiled.model)

        for op in query.ops:
            match op:
                case Filter(expr=expr):
                    stmt = stmt.where(compile_expr(expr, self._compiled))

                case OrderBy(specs=specs):
                    for spec in specs:
                        col = getattr(self._compiled.model, spec.field)
                        stmt = stmt.order_by(
                            col.asc() if spec.ascending else col.desc()
                        )

                case Limit(count=count):
                    stmt = stmt.limit(count)

                case Offset(count=count):
                    stmt = stmt.offset(count)

                case Distinct():
                    stmt = stmt.distinct()

                case Select(fields=fields):
                    cols = [getattr(self._compiled.model, f) for f in fields]
                    stmt = select(*cols).select_from(self._compiled.model)

                case GroupBy(fields=fields):
                    cols = [getattr(self._compiled.model, f) for f in fields]
                    stmt = stmt.group_by(*cols)

                case Having(expr=expr):
                    stmt = stmt.having(compile_expr(expr, self._compiled))

                case Join(target=target, on=on_expr, kind=kind, tablename=tbl):
                    if tbl is None:
                        raise TypeError(
                            f"Join target {target.__name__} requires explicit tablename. "
                            f"Use .join({target.__name__}, on=..., tablename='...')"
                        )
                    # Use the same DeclarativeBase as the main model
                    base = next(
                        (cls for cls in self._compiled.model.__mro__
                         if issubclass(cls, DeclarativeBase) and cls is not self._compiled.model and cls is not DeclarativeBase),
                        None,
                    )
                    join_compiled = compile_sa(target, tbl, base=base)
                    on_clause = compile_expr(on_expr, self._compiled, join_compiled)
                    stmt = stmt.join(
                        join_compiled.model,
                        on_clause,
                        isouter=(kind in ("left", "outer")),
                        full=(kind == "outer"),
                    )

                case Aggregate():
                    pass  # handled in aggregate() method

                # SQL-specific ops
                case Window(specs=specs):
                    win_cols = [self._compile_window_spec(s) for s in specs]
                    stmt = stmt.add_columns(*win_cols)

                case ForUpdate(nowait=nw, skip_locked=sl):
                    stmt = stmt.with_for_update(nowait=nw, skip_locked=sl)

                case Returning():
                    pass  # not applicable to SELECT; used by delete_returning()

        return stmt

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
        over_kw: dict[str, Any] = {}
        if spec.partition_by:
            over_kw["partition_by"] = [
                getattr(self._compiled.model, f) for f in spec.partition_by
            ]
        if spec.order_by:
            order_cols = []
            for o in spec.order_by:
                col = getattr(self._compiled.model, o.field)
                order_cols.append(col.asc() if o.ascending else col.desc())
            over_kw["order_by"] = order_cols

        return sa_func.over(**over_kw).label(spec.alias)

    def _compile_window_func(self, spec: WindowSpec) -> Any:
        """Compile WindowSpec function to SA func expression."""
        match spec.func:
            case RowNumber():
                return func.row_number()
            case Rank():
                return func.rank()
            case DenseRank():
                return func.dense_rank()
            case Ntile(num_buckets=n):
                return func.ntile(n)
            case Lag(offset=offset, default=default):
                col = getattr(self._compiled.model, spec.field) if spec.field else None
                args = [col, offset] if col is not None else [offset]
                if default is not None:
                    args.append(default)
                return func.lag(*args)
            case Lead(offset=offset, default=default):
                col = getattr(self._compiled.model, spec.field) if spec.field else None
                args = [col, offset] if col is not None else [offset]
                if default is not None:
                    args.append(default)
                return func.lead(*args)
            # Aggregate functions used as window functions
            case Count():
                if spec.field:
                    return func.count(getattr(self._compiled.model, spec.field))
                return func.count()
            case Sum() | Avg() | Min() | Max():
                if spec.field is None:
                    raise TypeError(f"{type(spec.func).__name__} window requires a field")
                col = getattr(self._compiled.model, spec.field)
                fn_map = {Sum: func.sum, Avg: func.avg, Min: func.min, Max: func.max}
                return fn_map[type(spec.func)](col)
            case _:
                raise TypeError(f"Unsupported window function: {type(spec.func)}")

    def _resolve_agg_col(self, spec: AggregateSpec, source: Any = None) -> Any:
        """Resolve column reference for aggregate — from model or subquery."""
        target = source if source is not None else self._compiled.model
        if spec.field is None:
            return None
        return target.c[spec.field] if source is not None else getattr(target, spec.field)

    def _compile_aggregate_func(self, spec: AggregateSpec, source: Any = None) -> Any:
        """Compile AggregateSpec to SA func().label(). source=subquery or None=model."""
        col = self._resolve_agg_col(spec, source)
        match spec.func:
            case Count():
                sa_fn = func.count() if col is None else func.count(col)
            case Sum() | Avg() | Min() | Max():
                if col is None:
                    raise TypeError(f"{type(spec.func).__name__} requires a field")
                fn_map = {Sum: func.sum, Avg: func.avg, Min: func.min, Max: func.max}
                sa_fn = fn_map[type(spec.func)](col)
            case ArrayAgg():
                if col is None:
                    raise TypeError("ArrayAgg requires a field")
                sa_fn = func.array_agg(col)
            case StringAgg(separator=sep):
                if col is None:
                    raise TypeError("StringAgg requires a field")
                sa_fn = func.string_agg(col, sep)
            case _:
                raise TypeError(f"Unsupported aggregate: {type(spec.func)}")
        return sa_fn.label(spec.alias)


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

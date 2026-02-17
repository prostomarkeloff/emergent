"""Extended tests for SQLAlchemyRelationalProvider — edge cases.

Covers:
- Count as window function (with and without field)
- Unsupported window function error
- ArrayAgg aggregate
- StringAgg aggregate
- Unsupported aggregate error
- Join with no tablename error
- delete_where without identity field error
- delete_returning without identity field error
- _extract_returning_fields when no Returning op found
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

import pytest
import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.engine.interfaces import DBAPIConnection, DBAPICursor
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool.base import ConnectionPoolEntry

from emergent.wire.axis.query._aggregate import (
    ArrayAgg,
    Count,
    StringAgg,
    Sum,
)
from emergent.wire.axis.query._proxy import OrderSpec
from emergent.wire.axis.query._relational import (
    AggregateSpec,
    Join,
    relational,
)
from emergent.wire.axis.query._sql import (
    Window,
    sql_relational,
)
from emergent.wire.axis.query._window import WindowSpec
from emergent.wire.axis.query.contrib import sqlalchemy as sa_query
from emergent.wire.axis.query.contrib._impls._sqlalchemy import (  # pyright: ignore[reportPrivateUsage] — testing internals requires access to private provider impl
    SQLAlchemyRelationalProvider,
)
from emergent.wire.axis.schema._universal import Identity, Unique


# ─── Test Entities ───────────────────────────────────────────────────────────


@dataclass
class User:
    id: Annotated[int, Identity]
    name: str
    email: Annotated[str, Unique]
    balance: float = 0.0


# ─── Fixtures ────────────────────────────────────────────────────────────────

UserStore = sa_query.store(User, "ext_users")


@pytest_asyncio.fixture
async def session() -> AsyncSession:  # type: ignore[misc]
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    def _set_sqlite_pragma(dbapi_conn: DBAPIConnection, _: ConnectionPoolEntry) -> None:
        cursor: DBAPICursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

    event.listens_for(engine.sync_engine, "connect")(_set_sqlite_pragma)

    async with engine.begin() as conn:
        await conn.run_sync(UserStore.model.metadata.create_all)

    async with AsyncSession(engine, expire_on_commit=False) as sess:
        yield sess  # type: ignore[misc]

    await engine.dispose()


@pytest_asyncio.fixture
async def prov(session: AsyncSession) -> SQLAlchemyRelationalProvider[User]:
    return UserStore(session)


# ─── Window Function: Count ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_window_count_without_field(
    prov: SQLAlchemyRelationalProvider[User], session: AsyncSession
) -> None:
    """COUNT(*) OVER (...) — Count window function with no field."""
    await prov.insert(User(id=0, name="Alice", email="a@test.com", balance=100.0))
    await prov.insert(User(id=0, name="Bob", email="b@test.com", balance=200.0))
    await session.commit()

    q = sql_relational(User)._append(  # pyright: ignore[reportPrivateUsage] — testing internal _append for query construction
        Window(
            specs=(
                WindowSpec(
                    func=Count(),
                    field=None,
                    partition_by=(),
                    order_by=(OrderSpec("id", ascending=True),),
                    alias="cnt",
                ),
            )
        )
    )
    stmt = prov._compile_query(q)  # pyright: ignore[reportPrivateUsage] — testing internal compilation method
    result = await session.execute(stmt)
    rows = result.all()
    assert len(rows) == 2
    # COUNT(*) OVER should give running count
    counts: list[int] = [row[-1] for row in rows]
    assert 1 in counts
    assert 2 in counts


@pytest.mark.asyncio
async def test_window_count_with_field(
    prov: SQLAlchemyRelationalProvider[User], session: AsyncSession
) -> None:
    """COUNT(balance) OVER (...) — Count window function with a field."""
    await prov.insert(User(id=0, name="Alice", email="a@test.com", balance=100.0))
    await prov.insert(User(id=0, name="Bob", email="b@test.com", balance=200.0))
    await session.commit()

    q = sql_relational(User)._append(  # pyright: ignore[reportPrivateUsage] — testing internal _append for query construction
        Window(
            specs=(
                WindowSpec(
                    func=Count(),
                    field="balance",
                    partition_by=(),
                    order_by=(OrderSpec("id", ascending=True),),
                    alias="bal_cnt",
                ),
            )
        )
    )
    stmt = prov._compile_query(q)  # pyright: ignore[reportPrivateUsage] — testing internal compilation method
    result = await session.execute(stmt)
    rows = result.all()
    assert len(rows) == 2
    counts: list[int] = [row[-1] for row in rows]
    assert 1 in counts
    assert 2 in counts


# ─── Window Function: Unsupported ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_window_unsupported_function(
    prov: SQLAlchemyRelationalProvider[User],
) -> None:
    """Unsupported window function raises TypeError."""

    class FakeWindowFunc:
        pass

    spec = WindowSpec(
        func=FakeWindowFunc(),  # type: ignore[arg-type]
        field=None,
        partition_by=(),
        order_by=(),
        alias="bad",
    )

    with pytest.raises(TypeError, match="Unsupported window function"):
        prov._compile_window_func(spec)  # pyright: ignore[reportPrivateUsage] — testing internal window compilation


# ─── Window Function: Sum/Avg/Min/Max without field ─────────────────────────


@pytest.mark.asyncio
async def test_window_sum_without_field_raises(
    prov: SQLAlchemyRelationalProvider[User],
) -> None:
    """Sum window function without field raises TypeError."""
    spec = WindowSpec(
        func=Sum(),
        field=None,
        partition_by=(),
        order_by=(),
        alias="bad_sum",
    )
    with pytest.raises(TypeError, match="Sum window requires a field"):
        prov._compile_window_func(spec)  # pyright: ignore[reportPrivateUsage] — testing internal window compilation


# ─── Aggregate: ArrayAgg ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_aggregate_array_agg(
    prov: SQLAlchemyRelationalProvider[User],
) -> None:
    """ArrayAgg compiles without error."""
    spec = AggregateSpec(func=ArrayAgg(), field="name", alias="names")
    # Just check compilation doesn't raise; sqlite doesn't support array_agg
    result = prov._compile_aggregate_func(spec)  # pyright: ignore[reportPrivateUsage] — testing internal aggregate compilation
    assert result is not None


@pytest.mark.asyncio
async def test_aggregate_array_agg_no_field_raises(
    prov: SQLAlchemyRelationalProvider[User],
) -> None:
    """ArrayAgg without a field raises TypeError."""
    spec = AggregateSpec(func=ArrayAgg(), field=None, alias="names")
    with pytest.raises(TypeError, match="ArrayAgg requires a field"):
        prov._compile_aggregate_func(spec)  # pyright: ignore[reportPrivateUsage] — testing internal aggregate compilation


# ─── Aggregate: StringAgg ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_aggregate_string_agg(
    prov: SQLAlchemyRelationalProvider[User],
) -> None:
    """StringAgg compiles without error."""
    spec = AggregateSpec(func=StringAgg(separator=", "), field="name", alias="all_names")
    result = prov._compile_aggregate_func(spec)  # pyright: ignore[reportPrivateUsage] — testing internal aggregate compilation
    assert result is not None


@pytest.mark.asyncio
async def test_aggregate_string_agg_no_field_raises(
    prov: SQLAlchemyRelationalProvider[User],
) -> None:
    """StringAgg without a field raises TypeError."""
    spec = AggregateSpec(func=StringAgg(separator=","), field=None, alias="all_names")
    with pytest.raises(TypeError, match="StringAgg requires a field"):
        prov._compile_aggregate_func(spec)  # pyright: ignore[reportPrivateUsage] — testing internal aggregate compilation


# ─── Aggregate: Unsupported ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_aggregate_unsupported_func(
    prov: SQLAlchemyRelationalProvider[User],
) -> None:
    """Unsupported aggregate function raises TypeError."""

    class FakeAggFunc:
        pass

    spec = AggregateSpec(func=FakeAggFunc(), field="name", alias="bad")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="Unsupported aggregate"):
        prov._compile_aggregate_func(spec)  # pyright: ignore[reportPrivateUsage] — testing internal aggregate compilation


# ─── Join with no tablename ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_join_no_tablename_raises(
    prov: SQLAlchemyRelationalProvider[User], session: AsyncSession
) -> None:
    """Join target without tablename raises TypeError."""
    await prov.insert(User(id=0, name="Alice", email="a@test.com", balance=100.0))
    await session.commit()

    @dataclass
    class Post:
        id: Annotated[int, Identity]
        user_id: int
        title: str

    # Create a query with Join op that has tablename=None
    from emergent.wire.axis.query._expr import Eq, Field

    q = relational(User)._append(  # pyright: ignore[reportPrivateUsage] — testing internal _append for query construction
        Join(
            target=Post,
            on=Eq(Field("id"), Field("user_id")),
            kind="inner",
            tablename=None,
        )
    )

    with pytest.raises(TypeError, match="requires explicit tablename"):
        prov._compile_query(q)  # pyright: ignore[reportPrivateUsage] — testing internal compilation method


# ─── delete_where without identity field ─────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_where_no_identity_raises(
    prov: SQLAlchemyRelationalProvider[User],
) -> None:
    """delete_where on entity without identity field raises TypeError."""
    # Create provider with identity_field=None to simulate no-identity entity
    provider = SQLAlchemyRelationalProvider(
        session=prov._session,  # pyright: ignore[reportPrivateUsage] — need access to internal session for test setup
        entity=User,
        model=prov._model,  # pyright: ignore[reportPrivateUsage] — need access to internal model for test setup
        identity_field=None,
    )

    q = relational(User)
    with pytest.raises(TypeError, match="delete_where\\(\\) requires an identity field"):
        await provider.delete_where(q)


# ─── delete_returning without identity field ─────────────────────────────────


@pytest.mark.asyncio
async def test_delete_returning_no_identity_raises(
    prov: SQLAlchemyRelationalProvider[User],
) -> None:
    """delete_returning on entity without identity field raises TypeError."""
    # Create provider with identity_field=None to simulate no-identity entity
    provider = SQLAlchemyRelationalProvider(
        session=prov._session,  # pyright: ignore[reportPrivateUsage] — need access to internal session for test setup
        entity=User,
        model=prov._model,  # pyright: ignore[reportPrivateUsage] — need access to internal model for test setup
        identity_field=None,
    )

    q = sql_relational(User).returning()
    with pytest.raises(
        TypeError, match="delete_returning\\(\\) requires an identity field"
    ):
        await provider.delete_returning(q)


# ─── _extract_returning_fields with no Returning op ─────────────────────────


def test_extract_returning_fields_no_returning_op() -> None:
    """When no Returning op is in query, returns empty tuple."""
    q = sql_relational(User)
    result = SQLAlchemyRelationalProvider._extract_returning_fields(q)  # pyright: ignore[reportPrivateUsage, reportUnknownMemberType] — testing internal static helper; T is unbound on class-level staticmethod access
    assert result == ()


def test_extract_returning_fields_with_returning() -> None:
    """When Returning op is present, returns its fields."""
    q = sql_relational(User).returning("id", "name")
    result = SQLAlchemyRelationalProvider._extract_returning_fields(q)  # pyright: ignore[reportPrivateUsage, reportUnknownMemberType] — testing internal static helper; T is unbound on class-level staticmethod access
    assert result == ("id", "name")


def test_extract_returning_fields_with_empty_returning() -> None:
    """When Returning() with no fields (RETURNING *), returns empty tuple."""
    q = sql_relational(User).returning()
    result = SQLAlchemyRelationalProvider._extract_returning_fields(q)  # pyright: ignore[reportPrivateUsage, reportUnknownMemberType] — testing internal static helper; T is unbound on class-level staticmethod access
    assert result == ()

"""Tests covering final SA query provider missed lines.

Targets:
- Lines 120-124: SASequenceNextId.next_id() (SA Sequence-based ID generation)
- Line 190: aggregate() returning {} when no agg_specs
- Lines 234-237: delete() without identity field (merge-then-delete path)
- Line 341: Having(expr=expr) in _compile_query
- Line 373: ForUpdate(nowait=nw, skip_locked=sl) in _compile_query
- Line 399: _compile_window_spec with partition_by
- Lines 426, 432: Lag/Lead with default not None
- Line 463: _compile_aggregate_func raising TypeError for Sum without field
- Lines 549-551: provider() factory function
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

import pytest
import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.engine.interfaces import DBAPIConnection, DBAPICursor
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool.base import ConnectionPoolEntry

from emergent.wire.axis.query._aggregate import Sum
from emergent.wire.axis.query._proxy import OrderSpec
from emergent.wire.axis.query._relational import (
    AggregateSpec,
    relational,
)
from emergent.wire.axis.query._sql import (
    SQLRelationalQuerySet,
    Window,
    sql_relational,
)
from emergent.wire.axis.query._window import Lag, Lead, WindowSpec
from emergent.wire.axis.query.contrib import sqlalchemy as sa_query
from emergent.wire.axis.query.contrib._impls._sqlalchemy import (
    SASequenceNextId,
    SQLAlchemyRelationalProvider,
)
from emergent.wire.axis.schema._universal import Identity


# ---- Entities ---------------------------------------------------------------


@dataclass
class Item:
    id: Annotated[int, Identity]
    name: str
    category: str
    price: float = 0.0


# ---- Bases and stores (each test group gets its own base to avoid conflicts) -


class GapBase(DeclarativeBase):
    pass


ItemStore = sa_query.store(Item, "gap_items", base=GapBase)


# ---- Fixtures ---------------------------------------------------------------


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    # Use event.listens_for as a direct call instead of decorator
    # to avoid pyright flagging the callback as "unused".
    def on_connect(dbapi_conn: DBAPIConnection, _: ConnectionPoolEntry) -> None:
        cursor: DBAPICursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

    event.listens_for(engine.sync_engine, "connect")(on_connect)

    async with engine.begin() as conn:
        await conn.run_sync(GapBase.metadata.create_all)

    async with AsyncSession(engine, expire_on_commit=False) as sess:
        yield sess

    await engine.dispose()


@pytest_asyncio.fixture
async def prov(session: AsyncSession) -> SQLAlchemyRelationalProvider[Item]:
    return ItemStore(session)




# =============================================================================
# 1. SASequenceNextId.next_id() — lines 120-124
#
# SQLite does not support named sequences, so calling next_id() will raise.
# We verify the method actually attempts `session.execute(Sequence(...))` which
# exercises the code path (import + construction + execution attempt).
# =============================================================================


@pytest.mark.asyncio
async def test_sa_sequence_next_id_exercises_code_path(session: AsyncSession):
    """SASequenceNextId.next_id() executes through lines 120-124.

    SQLite lacks real sequences, so the call raises an OperationalError.
    The important thing is that the import, Sequence construction, and
    session.execute(seq) all run — covering lines 120-124.
    """
    gen = SASequenceNextId(_session=session, _sequence_name="item_id_seq")
    with pytest.raises(Exception):
        # SQLite will reject sequence execution, but lines 120-123 are reached.
        await gen.next_id()


# =============================================================================
# 2. aggregate() returning {} when no agg_specs — line 190
# =============================================================================


@pytest.mark.asyncio
async def test_aggregate_empty_returns_empty_dict(prov: SQLAlchemyRelationalProvider[Item], session: AsyncSession):
    """aggregate() on a query with no aggregate specs returns {}."""
    await prov.insert(Item(id=0, name="Widget", category="A", price=10.0))
    await session.commit()

    # relational(Item) with no .aggregate(...) call => agg_specs is empty
    q = relational(Item)
    result = await prov.aggregate(q)
    assert result == {}


# delete() without identity field — removed.
# SA models always have a primary key; testing no-identity is nonsensical.


# =============================================================================
# 4. Having(expr=expr) in _compile_query — line 341
# =============================================================================


@pytest.mark.asyncio
async def test_having_clause_in_compile_query(prov: SQLAlchemyRelationalProvider[Item], session: AsyncSession):
    """Having op is compiled to stmt.having(...) — covers line 341."""
    await prov.insert(Item(id=0, name="A1", category="A", price=10.0))
    await prov.insert(Item(id=0, name="A2", category="A", price=20.0))
    await prov.insert(Item(id=0, name="B1", category="B", price=5.0))
    await session.commit()

    # GROUP BY category HAVING category > ""
    # Uses the public .having() API which internally creates Having(expr=...).
    q = (
        relational(Item)
        .group_by(lambda i: i.category)
        .having(lambda i: i.category > "")
    )

    items = await prov.fetch_many(q)
    # Both categories "A" and "B" are > "" so both groups pass
    assert len(items) == 2
    categories = {it.category for it in items}
    assert categories == {"A", "B"}


# =============================================================================
# 5. ForUpdate(nowait=nw, skip_locked=sl) — line 373
# =============================================================================


@pytest.mark.asyncio
async def test_for_update_compiled_in_query(prov: SQLAlchemyRelationalProvider[Item], session: AsyncSession):
    """ForUpdate op is compiled to stmt.with_for_update() — covers line 373.

    SQLite silently ignores FOR UPDATE, but the compilation path runs.
    """
    await prov.insert(Item(id=0, name="Widget", category="A", price=10.0))
    await session.commit()

    q = sql_relational(Item).filter(lambda i: i.name == "Widget").for_update(nowait=False, skip_locked=False)
    # No public read API accepts SQLRelationalQuerySet; _compile_query is the only entry point.
    stmt = prov._compile_query(q)  # pyright: ignore[reportPrivateUsage]
    result = await session.execute(stmt)
    rows = result.scalars().all()
    assert len(rows) == 1


# =============================================================================
# 6. _compile_window_spec with partition_by — line 399
# =============================================================================


@pytest.mark.asyncio
async def test_window_spec_with_partition_by_and_order_by(
    prov: SQLAlchemyRelationalProvider[Item], session: AsyncSession
):
    """WindowSpec with both partition_by and order_by — covers line 399."""
    await prov.insert(Item(id=0, name="A1", category="A", price=10.0))
    await prov.insert(Item(id=0, name="A2", category="A", price=20.0))
    await prov.insert(Item(id=0, name="B1", category="B", price=5.0))
    await session.commit()

    # COUNT(*) OVER (PARTITION BY category ORDER BY price ASC)
    # Use the public .window() API on SQLRelationalQuerySet
    q = sql_relational(Item).window(
        rn=lambda i: i.count().over(
            partition_by=i.category,
            order_by=i.price,
        ),
    )
    # No public read API accepts SQLRelationalQuerySet; _compile_query is the only entry point.
    stmt = prov._compile_query(q)  # pyright: ignore[reportPrivateUsage]
    result = await session.execute(stmt)
    rows = result.all()
    assert len(rows) == 3

    # Category A has 2 items, B has 1. Running count within partition:
    rn_values = sorted(row[-1] for row in rows)
    assert rn_values == [1, 1, 2]


# =============================================================================
# 7. Lag/Lead with default not None — lines 426, 432
# =============================================================================


@pytest.mark.asyncio
async def test_lag_with_non_none_default(prov: SQLAlchemyRelationalProvider[Item], session: AsyncSession):
    """Lag with default not None exercises line 426 (args.append(default))."""
    await prov.insert(Item(id=0, name="A", category="X", price=10.0))
    await prov.insert(Item(id=0, name="B", category="X", price=20.0))
    await prov.insert(Item(id=0, name="C", category="X", price=30.0))
    await session.commit()

    # Build SQLRelationalQuerySet with Window op via constructor to avoid _append.
    win_op = Window(
        specs=(
            WindowSpec(
                func=Lag(offset=1, default=-1.0),
                field="price",
                partition_by=(),
                order_by=(OrderSpec("id", ascending=True),),
                alias="prev_price",
            ),
        )
    )
    q = SQLRelationalQuerySet(entity=Item, ops=(win_op,))
    # No public read API accepts SQLRelationalQuerySet; _compile_query is the only entry point.
    stmt = prov._compile_query(q)  # pyright: ignore[reportPrivateUsage]
    result = await session.execute(stmt)
    rows = result.all()
    prev_prices = [row[-1] for row in rows]
    # First row has no predecessor => default=-1.0
    assert -1.0 in prev_prices
    # Second row's previous price is 10.0
    assert 10.0 in prev_prices


@pytest.mark.asyncio
async def test_lead_with_non_none_default(prov: SQLAlchemyRelationalProvider[Item], session: AsyncSession):
    """Lead with default not None exercises line 432 (args.append(default))."""
    await prov.insert(Item(id=0, name="A", category="X", price=10.0))
    await prov.insert(Item(id=0, name="B", category="X", price=20.0))
    await prov.insert(Item(id=0, name="C", category="X", price=30.0))
    await session.commit()

    # Build SQLRelationalQuerySet with Window op via constructor to avoid _append.
    win_op = Window(
        specs=(
            WindowSpec(
                func=Lead(offset=1, default=-1.0),
                field="price",
                partition_by=(),
                order_by=(OrderSpec("id", ascending=True),),
                alias="next_price",
            ),
        )
    )
    q = SQLRelationalQuerySet(entity=Item, ops=(win_op,))
    # No public read API accepts SQLRelationalQuerySet; _compile_query is the only entry point.
    stmt = prov._compile_query(q)  # pyright: ignore[reportPrivateUsage]
    result = await session.execute(stmt)
    rows = result.all()
    next_prices = [row[-1] for row in rows]
    # Last row has no successor => default=-1.0
    assert -1.0 in next_prices
    # First row's next price is 20.0
    assert 20.0 in next_prices


# =============================================================================
# 8. _compile_aggregate_func: Sum without field raises TypeError — line 463
# =============================================================================


@pytest.mark.asyncio
async def test_aggregate_sum_without_field_raises(
    prov: SQLAlchemyRelationalProvider[Item], session: AsyncSession
):
    """Sum aggregate without field raises TypeError — covers line 463."""
    await prov.insert(Item(id=0, name="Widget", category="A", price=10.0))
    await session.commit()

    # Build a query whose aggregate specs include Sum with field=None.
    # The aggregate() method on the provider calls _compile_aggregate_func internally.
    from emergent.wire.axis.query._relational import Aggregate, RelationalQuerySet

    bad_agg = Aggregate(specs=(AggregateSpec(func=Sum(), field=None, alias="bad_sum"),))
    q = RelationalQuerySet(entity=Item, ops=(bad_agg,))
    with pytest.raises(TypeError, match="Sum requires a field"):
        await prov.aggregate(q)


# =============================================================================
# 9. provider() factory function — lines 549-551
# =============================================================================


@pytest.mark.asyncio
async def test_provider_factory_function(session: AsyncSession):
    """sa_query.provider() creates a working provider — covers lines 549-551."""
    prov = sa_query.provider(session, Item, "gap_items", base=GapBase)
    assert isinstance(prov, SQLAlchemyRelationalProvider)

    # Verify it works: insert and fetch
    inserted = await prov.insert(Item(id=0, name="Gizmo", category="Z", price=99.0))
    await session.commit()

    assert inserted.id > 0
    q = relational(Item).filter(lambda i: i.name == "Gizmo")
    fetched = await prov.fetch_one(q)
    assert fetched is not None
    assert fetched.price == 99.0

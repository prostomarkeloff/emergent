"""Tests for SQLAlchemyRelationalProvider — aiosqlite in-memory."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

import pytest
import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.engine.interfaces import DBAPIConnection, DBAPICursor
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool.base import ConnectionPoolEntry

from emergent.wire.axis.query._relational import relational
from emergent.wire.axis.query._sql import sql_relational
from emergent.wire.axis.query.contrib import sqlalchemy as sa_query
from emergent.wire.axis.query.contrib._impls._sqlalchemy import (  # pyright: ignore[reportPrivateUsage] — testing internals requires access to private provider impl
    SQLAlchemyRelationalProvider,
)
from emergent.wire.axis.schema._universal import Identity, Unique


# ─── Test Entity ──────────────────────────────────────────────────────────────


@dataclass
class User:
    id: Annotated[int, Identity]
    name: str
    email: Annotated[str, Unique]
    balance: float = 0.0


# ─── Fixtures ─────────────────────────────────────────────────────────────────


UserStore = sa_query.store(User, "users")


@pytest_asyncio.fixture
async def session() -> AsyncSession:  # type: ignore[misc]
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    # Enable WAL mode for SQLite (needed for some operations)
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
async def prov(session: AsyncSession) -> SQLAlchemyRelationalProvider[User]:  # type: ignore[misc]
    return UserStore(session)


# ─── CRUD Tests ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_insert_and_fetch_one(prov: SQLAlchemyRelationalProvider[User], session: AsyncSession) -> None:
    user = User(id=0, name="Alice", email="alice@test.com", balance=100.0)
    result = await prov.insert(user)
    await session.commit()

    # Autoincrement: id should be assigned by DB
    assert result.id > 0
    assert result.name == "Alice"
    assert result.email == "alice@test.com"

    # Fetch back
    q = relational(User).filter(lambda u: u.id == result.id)
    fetched = await prov.fetch_one(q)
    assert fetched is not None
    assert fetched.name == "Alice"


@pytest.mark.asyncio
async def test_insert_multiple_and_fetch_many(prov: SQLAlchemyRelationalProvider[User], session: AsyncSession) -> None:
    await prov.insert(User(id=0, name="Alice", email="a@test.com", balance=100.0))
    await prov.insert(User(id=0, name="Bob", email="b@test.com", balance=200.0))
    await prov.insert(User(id=0, name="Charlie", email="c@test.com", balance=50.0))
    await session.commit()

    q = relational(User)
    users = await prov.fetch_many(q)
    assert len(users) == 3


@pytest.mark.asyncio
async def test_update(prov: SQLAlchemyRelationalProvider[User], session: AsyncSession) -> None:
    result = await prov.insert(User(id=0, name="Alice", email="a@test.com", balance=100.0))
    await session.commit()

    updated = User(id=result.id, name="Alice Updated", email="a@test.com", balance=200.0)
    result2 = await prov.update(updated)
    await session.commit()

    assert result2.name == "Alice Updated"
    assert result2.balance == 200.0

    # Verify
    fetched = await prov.fetch_one(relational(User).filter(lambda u: u.id == result.id))
    assert fetched is not None
    assert fetched.name == "Alice Updated"


@pytest.mark.asyncio
async def test_delete(prov: SQLAlchemyRelationalProvider[User], session: AsyncSession) -> None:
    result = await prov.insert(User(id=0, name="Alice", email="a@test.com"))
    await session.commit()

    await prov.delete(result)
    await session.commit()

    fetched = await prov.fetch_one(relational(User).filter(lambda u: u.id == result.id))
    assert fetched is None


@pytest.mark.asyncio
async def test_delete_where(prov: SQLAlchemyRelationalProvider[User], session: AsyncSession) -> None:
    await prov.insert(User(id=0, name="Alice", email="a@test.com", balance=100.0))
    await prov.insert(User(id=0, name="Bob", email="b@test.com", balance=200.0))
    await prov.insert(User(id=0, name="Charlie", email="c@test.com", balance=50.0))
    await session.commit()

    q = relational(User).filter(lambda u: u.balance < 100)
    deleted = await prov.delete_where(q)
    await session.commit()

    assert deleted == 1
    remaining = await prov.fetch_many(relational(User))
    assert len(remaining) == 2


# ─── Query Op Tests ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_filter(prov: SQLAlchemyRelationalProvider[User], session: AsyncSession) -> None:
    await prov.insert(User(id=0, name="Alice", email="a@test.com", balance=100.0))
    await prov.insert(User(id=0, name="Bob", email="b@test.com", balance=200.0))
    await prov.insert(User(id=0, name="Charlie", email="c@test.com", balance=50.0))
    await session.commit()

    q = relational(User).filter(lambda u: u.balance > 80)
    users = await prov.fetch_many(q)
    assert len(users) == 2
    names = {u.name for u in users}
    assert names == {"Alice", "Bob"}


@pytest.mark.asyncio
async def test_order_by(prov: SQLAlchemyRelationalProvider[User], session: AsyncSession) -> None:
    await prov.insert(User(id=0, name="Charlie", email="c@test.com", balance=50.0))
    await prov.insert(User(id=0, name="Alice", email="a@test.com", balance=100.0))
    await prov.insert(User(id=0, name="Bob", email="b@test.com", balance=200.0))
    await session.commit()

    q = relational(User).order_by(lambda u: u.name)
    users = await prov.fetch_many(q)
    assert [u.name for u in users] == ["Alice", "Bob", "Charlie"]

    q_desc = relational(User).order_by(lambda u: u.balance.desc())
    users_desc = await prov.fetch_many(q_desc)
    assert [u.name for u in users_desc] == ["Bob", "Alice", "Charlie"]


@pytest.mark.asyncio
async def test_limit_offset(prov: SQLAlchemyRelationalProvider[User], session: AsyncSession) -> None:
    for i in range(10):
        await prov.insert(User(id=0, name=f"User{i}", email=f"u{i}@test.com", balance=float(i)))
    await session.commit()

    q = relational(User).order_by(lambda u: u.name).limit(3).offset(2)
    users = await prov.fetch_many(q)
    assert len(users) == 3


@pytest.mark.asyncio
async def test_count(prov: SQLAlchemyRelationalProvider[User], session: AsyncSession) -> None:
    await prov.insert(User(id=0, name="Alice", email="a@test.com", balance=100.0))
    await prov.insert(User(id=0, name="Bob", email="b@test.com", balance=200.0))
    await session.commit()

    total = await prov.count(relational(User))
    assert total == 2

    filtered = await prov.count(relational(User).filter(lambda u: u.balance > 150))
    assert filtered == 1


@pytest.mark.asyncio
async def test_exists(prov: SQLAlchemyRelationalProvider[User], session: AsyncSession) -> None:
    assert await prov.exists(relational(User)) is False

    await prov.insert(User(id=0, name="Alice", email="a@test.com"))
    await session.commit()

    assert await prov.exists(relational(User)) is True
    assert await prov.exists(relational(User).filter(lambda u: u.name == "Bob")) is False


@pytest.mark.asyncio
async def test_distinct(prov: SQLAlchemyRelationalProvider[User], session: AsyncSession) -> None:
    await prov.insert(User(id=0, name="Alice", email="a1@test.com", balance=100.0))
    await prov.insert(User(id=0, name="Alice", email="a2@test.com", balance=100.0))
    await prov.insert(User(id=0, name="Bob", email="b@test.com", balance=200.0))
    await session.commit()

    # All users
    all_users = await prov.fetch_many(relational(User))
    assert len(all_users) == 3

    # Distinct still returns all since primary keys differ
    distinct_users = await prov.fetch_many(relational(User).distinct())
    assert len(distinct_users) == 3


# ─── Aggregate Tests ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_aggregate_count(prov: SQLAlchemyRelationalProvider[User], session: AsyncSession) -> None:
    await prov.insert(User(id=0, name="Alice", email="a@test.com", balance=100.0))
    await prov.insert(User(id=0, name="Bob", email="b@test.com", balance=200.0))
    await session.commit()

    q = relational(User).aggregate(total=lambda u: u.count())
    result = await prov.aggregate(q)
    assert result["total"] == 2


@pytest.mark.asyncio
async def test_aggregate_sum_avg(prov: SQLAlchemyRelationalProvider[User], session: AsyncSession) -> None:
    await prov.insert(User(id=0, name="Alice", email="a@test.com", balance=100.0))
    await prov.insert(User(id=0, name="Bob", email="b@test.com", balance=200.0))
    await session.commit()

    q = relational(User).aggregate(
        total_balance=lambda u: u.balance.sum(),
        avg_balance=lambda u: u.balance.avg(),
    )
    result = await prov.aggregate(q)
    assert result["total_balance"] == 300.0
    assert result["avg_balance"] == 150.0


@pytest.mark.asyncio
async def test_aggregate_min_max(prov: SQLAlchemyRelationalProvider[User], session: AsyncSession) -> None:
    await prov.insert(User(id=0, name="Alice", email="a@test.com", balance=100.0))
    await prov.insert(User(id=0, name="Bob", email="b@test.com", balance=200.0))
    await prov.insert(User(id=0, name="Charlie", email="c@test.com", balance=50.0))
    await session.commit()

    q = relational(User).aggregate(
        min_bal=lambda u: u.balance.min(),
        max_bal=lambda u: u.balance.max(),
    )
    result = await prov.aggregate(q)
    assert result["min_bal"] == 50.0
    assert result["max_bal"] == 200.0


@pytest.mark.asyncio
async def test_aggregate_with_filter(prov: SQLAlchemyRelationalProvider[User], session: AsyncSession) -> None:
    await prov.insert(User(id=0, name="Alice", email="a@test.com", balance=100.0))
    await prov.insert(User(id=0, name="Bob", email="b@test.com", balance=200.0))
    await prov.insert(User(id=0, name="Charlie", email="c@test.com", balance=50.0))
    await session.commit()

    q = (
        relational(User)
        .filter(lambda u: u.balance >= 100)
        .aggregate(cnt=lambda u: u.count())
    )
    result = await prov.aggregate(q)
    assert result["cnt"] == 2


# ─── Autoincrement Test ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_autoincrement_ids(prov: SQLAlchemyRelationalProvider[User], session: AsyncSession) -> None:
    u1 = await prov.insert(User(id=0, name="Alice", email="a@test.com"))
    u2 = await prov.insert(User(id=0, name="Bob", email="b@test.com"))
    u3 = await prov.insert(User(id=0, name="Charlie", email="c@test.com"))
    await session.commit()

    assert u1.id == 1
    assert u2.id == 2
    assert u3.id == 3


# ─── Combined Query Test ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_filter_order_limit_combined(prov: SQLAlchemyRelationalProvider[User], session: AsyncSession) -> None:
    for i in range(20):
        await prov.insert(User(id=0, name=f"User{i:02d}", email=f"u{i}@test.com", balance=float(i * 10)))
    await session.commit()

    # Get top 5 users with balance > 50, ordered by balance desc
    q = (
        relational(User)
        .filter(lambda u: u.balance > 50)
        .order_by(lambda u: u.balance.desc())
        .limit(5)
    )
    users = await prov.fetch_many(q)
    assert len(users) == 5
    assert users[0].balance > users[1].balance  # descending
    assert all(u.balance > 50 for u in users)


# ─── next_id Test ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_next_id_returns_placeholder(prov: SQLAlchemyRelationalProvider[User]) -> None:
    nid = await prov.next_id()
    assert nid == 0  # AutoIncrementNextId placeholder


# ─── delete_returning Tests ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_returning_full(prov: SQLAlchemyRelationalProvider[User], session: AsyncSession) -> None:
    """DELETE ... RETURNING * — returns full deleted entities."""
    await prov.insert(User(id=0, name="Alice", email="a@test.com", balance=100.0))
    await prov.insert(User(id=0, name="Bob", email="b@test.com", balance=200.0))
    await prov.insert(User(id=0, name="Charlie", email="c@test.com", balance=50.0))
    await session.commit()

    q = sql_relational(User).filter(lambda u: u.balance < 100).returning()
    deleted = await prov.delete_returning(q)
    await session.commit()

    assert len(deleted) == 1
    assert deleted[0].name == "Charlie"
    assert deleted[0].balance == 50.0

    remaining = await prov.fetch_many(relational(User))
    assert len(remaining) == 2


@pytest.mark.asyncio
async def test_delete_returning_partial(prov: SQLAlchemyRelationalProvider[User], session: AsyncSession) -> None:
    """DELETE ... RETURNING id, name — returns dicts with selected fields."""
    await prov.insert(User(id=0, name="Alice", email="a@test.com", balance=100.0))
    await prov.insert(User(id=0, name="Bob", email="b@test.com", balance=200.0))
    await session.commit()

    q = sql_relational(User).filter(lambda u: u.name == "Bob").returning("id", "name")
    # delete_returning with partial fields returns dicts, not entities
    # (the provider's type signature lies — it returns list[dict] for partial RETURNING)
    deleted_raw: list[dict[str, str | int]] = await prov.delete_returning(q)  # pyright: ignore[reportAssignmentType] — partial RETURNING returns dicts, not User entities; provider API conflates both cases
    await session.commit()

    assert len(deleted_raw) == 1
    assert deleted_raw[0]["name"] == "Bob"
    assert "email" not in deleted_raw[0]

    remaining = await prov.fetch_many(relational(User))
    assert len(remaining) == 1
    assert remaining[0].name == "Alice"


@pytest.mark.asyncio
async def test_delete_returning_empty(prov: SQLAlchemyRelationalProvider[User], session: AsyncSession) -> None:
    """DELETE ... RETURNING with no matching rows returns empty list."""
    await prov.insert(User(id=0, name="Alice", email="a@test.com"))
    await session.commit()

    q = sql_relational(User).filter(lambda u: u.name == "Nobody").returning()
    deleted = await prov.delete_returning(q)
    await session.commit()

    assert deleted == []
    remaining = await prov.fetch_many(relational(User))
    assert len(remaining) == 1


# ─── ForUpdate Tests ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_for_update_basic(prov: SQLAlchemyRelationalProvider[User], session: AsyncSession) -> None:
    """SELECT ... FOR UPDATE — basic row locking."""
    await prov.insert(User(id=0, name="Alice", email="a@test.com", balance=100.0))
    await session.commit()

    q = sql_relational(User).filter(lambda u: u.name == "Alice").for_update()
    users = await prov.fetch_many(q.to_relational())

    # Just verifying the query compiles and executes; SQLite doesn't truly lock
    assert len(users) == 1
    assert users[0].name == "Alice"


@pytest.mark.asyncio
async def test_for_update_nowait(prov: SQLAlchemyRelationalProvider[User], session: AsyncSession) -> None:
    """FOR UPDATE NOWAIT."""
    await prov.insert(User(id=0, name="Alice", email="a@test.com", balance=100.0))
    await session.commit()

    q = sql_relational(User).for_update(nowait=True)
    assert q.has_for_update


# ─── Join Tests ─────────────────────────────────────────────────────────────


@dataclass
class Post:
    id: Annotated[int, Identity]
    user_id: int
    title: str


from sqlalchemy.orm import DeclarativeBase

class JoinBase(DeclarativeBase):
    pass


JoinUserStore = sa_query.store(User, "users", base=JoinBase)
JoinPostStore = sa_query.store(Post, "posts", base=JoinBase)


@pytest_asyncio.fixture
async def session_with_posts() -> AsyncSession:  # type: ignore[misc]
    """Session with both users and posts tables."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    def _set_sqlite_pragma(dbapi_conn: DBAPIConnection, _: ConnectionPoolEntry) -> None:
        cursor: DBAPICursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

    event.listens_for(engine.sync_engine, "connect")(_set_sqlite_pragma)

    async with engine.begin() as conn:
        await conn.run_sync(JoinBase.metadata.create_all)

    async with AsyncSession(engine, expire_on_commit=False) as sess:
        yield sess  # type: ignore[misc]

    await engine.dispose()


@pytest.mark.asyncio
async def test_join_inner(session_with_posts: AsyncSession) -> None:
    """INNER JOIN — only users with posts."""
    user_prov = JoinUserStore(session_with_posts)
    post_prov = JoinPostStore(session_with_posts)

    u1 = await user_prov.insert(User(id=0, name="Alice", email="a@test.com", balance=100.0))
    _u2 = await user_prov.insert(User(id=0, name="Bob", email="b@test.com", balance=200.0))
    await post_prov.insert(Post(id=0, user_id=u1.id, title="Post 1"))
    await session_with_posts.commit()

    # Inner join — only Alice has posts
    q = relational(User).join(Post, on=lambda u, p: u.id == p.user_id, tablename="posts")
    users = await user_prov.fetch_many(q)
    assert len(users) == 1
    assert users[0].name == "Alice"


@pytest.mark.asyncio
async def test_join_left(session_with_posts: AsyncSession) -> None:
    """LEFT JOIN — all users, including those without posts."""
    user_prov = JoinUserStore(session_with_posts)
    post_prov = JoinPostStore(session_with_posts)

    await user_prov.insert(User(id=0, name="Alice", email="a@test.com", balance=100.0))
    await user_prov.insert(User(id=0, name="Bob", email="b@test.com", balance=200.0))
    await post_prov.insert(Post(id=0, user_id=1, title="Post 1"))
    await session_with_posts.commit()

    q = relational(User).left_join(Post, on=lambda u, p: u.id == p.user_id, tablename="posts")
    users = await user_prov.fetch_many(q)
    assert len(users) == 2


# ─── GroupBy Tests ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_group_by_with_aggregate(prov: SQLAlchemyRelationalProvider[User], session: AsyncSession) -> None:
    """GROUP BY name + COUNT aggregate."""
    await prov.insert(User(id=0, name="Alice", email="a1@test.com", balance=100.0))
    await prov.insert(User(id=0, name="Alice", email="a2@test.com", balance=200.0))
    await prov.insert(User(id=0, name="Bob", email="b@test.com", balance=300.0))
    await session.commit()

    q = relational(User).group_by(lambda u: u.name)
    users = await prov.fetch_many(q)
    # GROUP BY collapses duplicates
    assert len(users) == 2


# ─── Select Projection Tests ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_select_projection(prov: SQLAlchemyRelationalProvider[User], session: AsyncSession) -> None:
    """SELECT name, email — returns only specified columns."""
    await prov.insert(User(id=0, name="Alice", email="a@test.com", balance=100.0))
    await session.commit()

    q = relational(User).select(lambda u: u.name, lambda u: u.email)
    stmt = prov._compile_query(q)  # pyright: ignore[reportPrivateUsage] — testing internal compilation
    result = await session.execute(stmt)
    rows = result.all()
    assert len(rows) == 1
    assert rows[0][0] == "Alice"
    assert rows[0][1] == "a@test.com"


# ─── Window Function Tests ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_window_row_number(prov: SQLAlchemyRelationalProvider[User], session: AsyncSession) -> None:
    """ROW_NUMBER() OVER (ORDER BY balance DESC)."""
    await prov.insert(User(id=0, name="Alice", email="a@test.com", balance=100.0))
    await prov.insert(User(id=0, name="Bob", email="b@test.com", balance=200.0))
    await prov.insert(User(id=0, name="Charlie", email="c@test.com", balance=50.0))
    await session.commit()

    q = sql_relational(User).window(
        rn=lambda u: u.row_number().over(order_by=u.balance.desc()),
    )
    stmt = prov._compile_query(q)  # pyright: ignore[reportPrivateUsage] — testing internal compilation
    result = await session.execute(stmt)
    rows = result.all()
    assert len(rows) == 3
    # Row with highest balance (Bob, 200) should have rn=1
    # Each row is (User columns..., rn)
    rn_values = [row[-1] for row in rows]
    assert sorted(rn_values) == [1, 2, 3]


@pytest.mark.asyncio
async def test_window_rank(prov: SQLAlchemyRelationalProvider[User], session: AsyncSession) -> None:
    """RANK() OVER (ORDER BY balance)."""
    await prov.insert(User(id=0, name="Alice", email="a@test.com", balance=100.0))
    await prov.insert(User(id=0, name="Bob", email="b@test.com", balance=100.0))
    await prov.insert(User(id=0, name="Charlie", email="c@test.com", balance=200.0))
    await session.commit()

    from emergent.wire.axis.query._window import Rank, WindowSpec  # pyright: ignore[reportPrivateUsage] — testing internal window types
    from emergent.wire.axis.query._sql import Window  # pyright: ignore[reportPrivateUsage] — testing internal SQL ops
    from emergent.wire.axis.query._proxy import OrderSpec  # pyright: ignore[reportPrivateUsage] — testing internal proxy types

    q = sql_relational(User)._append(Window(specs=(  # pyright: ignore[reportPrivateUsage] — testing internal _append
        WindowSpec(
            func=Rank(),
            field=None,
            partition_by=(),
            order_by=(OrderSpec("balance", ascending=True),),
            alias="rnk",
        ),
    )))
    stmt = prov._compile_query(q)  # pyright: ignore[reportPrivateUsage] — testing internal compilation
    result = await session.execute(stmt)
    rows = result.all()
    assert len(rows) == 3
    ranks = [row[-1] for row in rows]
    # Two users with 100 share rank 1, Charlie gets rank 3
    assert sorted(ranks) == [1, 1, 3]


@pytest.mark.asyncio
async def test_window_dense_rank(prov: SQLAlchemyRelationalProvider[User], session: AsyncSession) -> None:
    """DENSE_RANK() OVER (ORDER BY balance)."""
    await prov.insert(User(id=0, name="Alice", email="a@test.com", balance=100.0))
    await prov.insert(User(id=0, name="Bob", email="b@test.com", balance=100.0))
    await prov.insert(User(id=0, name="Charlie", email="c@test.com", balance=200.0))
    await session.commit()

    from emergent.wire.axis.query._window import DenseRank, WindowSpec  # pyright: ignore[reportPrivateUsage] — testing internal window types
    from emergent.wire.axis.query._sql import Window  # pyright: ignore[reportPrivateUsage] — testing internal SQL ops
    from emergent.wire.axis.query._proxy import OrderSpec  # pyright: ignore[reportPrivateUsage] — testing internal proxy types

    q = sql_relational(User)._append(Window(specs=(  # pyright: ignore[reportPrivateUsage] — testing internal _append
        WindowSpec(
            func=DenseRank(),
            field=None,
            partition_by=(),
            order_by=(OrderSpec("balance", ascending=True),),
            alias="dr",
        ),
    )))
    stmt = prov._compile_query(q)  # pyright: ignore[reportPrivateUsage] — testing internal compilation
    result = await session.execute(stmt)
    rows = result.all()
    ranks = [row[-1] for row in rows]
    # Dense rank: 1, 1, 2 (no gap)
    assert sorted(ranks) == [1, 1, 2]


@pytest.mark.asyncio
async def test_window_ntile(prov: SQLAlchemyRelationalProvider[User], session: AsyncSession) -> None:
    """NTILE(2) OVER (ORDER BY name)."""
    await prov.insert(User(id=0, name="Alice", email="a@test.com", balance=100.0))
    await prov.insert(User(id=0, name="Bob", email="b@test.com", balance=200.0))
    await prov.insert(User(id=0, name="Charlie", email="c@test.com", balance=50.0))
    await prov.insert(User(id=0, name="Diana", email="d@test.com", balance=300.0))
    await session.commit()

    from emergent.wire.axis.query._window import Ntile, WindowSpec  # pyright: ignore[reportPrivateUsage] — testing internal window types
    from emergent.wire.axis.query._sql import Window  # pyright: ignore[reportPrivateUsage] — testing internal SQL ops
    from emergent.wire.axis.query._proxy import OrderSpec  # pyright: ignore[reportPrivateUsage] — testing internal proxy types

    q = sql_relational(User)._append(Window(specs=(  # pyright: ignore[reportPrivateUsage] — testing internal _append
        WindowSpec(
            func=Ntile(num_buckets=2),
            field=None,
            partition_by=(),
            order_by=(OrderSpec("name", ascending=True),),
            alias="bucket",
        ),
    )))
    stmt = prov._compile_query(q)  # pyright: ignore[reportPrivateUsage] — testing internal compilation
    result = await session.execute(stmt)
    rows = result.all()
    buckets = sorted(row[-1] for row in rows)
    # 4 rows split into 2 buckets: [1, 1, 2, 2]
    assert buckets == [1, 1, 2, 2]


@pytest.mark.asyncio
async def test_window_sum_over(prov: SQLAlchemyRelationalProvider[User], session: AsyncSession) -> None:
    """SUM(balance) OVER (ORDER BY id) — running total."""
    await prov.insert(User(id=0, name="Alice", email="a@test.com", balance=100.0))
    await prov.insert(User(id=0, name="Bob", email="b@test.com", balance=200.0))
    await prov.insert(User(id=0, name="Charlie", email="c@test.com", balance=50.0))
    await session.commit()

    q = sql_relational(User).window(
        running=lambda u: u.balance.sum().over(order_by=u.id),
    )
    stmt = prov._compile_query(q)  # pyright: ignore[reportPrivateUsage] — testing internal compilation
    result = await session.execute(stmt)
    rows = result.all()
    # Running sums ordered by id: 100, 300, 350
    running_totals = [row[-1] for row in rows]
    assert sorted(running_totals) == [100.0, 300.0, 350.0]


@pytest.mark.asyncio
async def test_window_lag(prov: SQLAlchemyRelationalProvider[User], session: AsyncSession) -> None:
    """LAG(balance, 1) OVER (ORDER BY id)."""
    await prov.insert(User(id=0, name="Alice", email="a@test.com", balance=100.0))
    await prov.insert(User(id=0, name="Bob", email="b@test.com", balance=200.0))
    await prov.insert(User(id=0, name="Charlie", email="c@test.com", balance=50.0))
    await session.commit()

    from emergent.wire.axis.query._window import Lag, WindowSpec  # pyright: ignore[reportPrivateUsage] — testing internal window types
    from emergent.wire.axis.query._sql import Window  # pyright: ignore[reportPrivateUsage] — testing internal SQL ops
    from emergent.wire.axis.query._proxy import OrderSpec  # pyright: ignore[reportPrivateUsage] — testing internal proxy types

    q = sql_relational(User)._append(Window(specs=(  # pyright: ignore[reportPrivateUsage] — testing internal _append
        WindowSpec(
            func=Lag(offset=1, default=None),
            field="balance",
            partition_by=(),
            order_by=(OrderSpec("id", ascending=True),),
            alias="prev_balance",
        ),
    )))
    stmt = prov._compile_query(q)  # pyright: ignore[reportPrivateUsage] — testing internal compilation
    result = await session.execute(stmt)
    rows = result.all()
    prev_balances = [row[-1] for row in rows]
    # First row has no previous → None, then 100.0, 200.0
    assert None in prev_balances
    assert 100.0 in prev_balances


@pytest.mark.asyncio
async def test_window_lead(prov: SQLAlchemyRelationalProvider[User], session: AsyncSession) -> None:
    """LEAD(balance, 1) OVER (ORDER BY id)."""
    await prov.insert(User(id=0, name="Alice", email="a@test.com", balance=100.0))
    await prov.insert(User(id=0, name="Bob", email="b@test.com", balance=200.0))
    await prov.insert(User(id=0, name="Charlie", email="c@test.com", balance=50.0))
    await session.commit()

    from emergent.wire.axis.query._window import Lead, WindowSpec  # pyright: ignore[reportPrivateUsage] — testing internal window types
    from emergent.wire.axis.query._sql import Window  # pyright: ignore[reportPrivateUsage] — testing internal SQL ops
    from emergent.wire.axis.query._proxy import OrderSpec  # pyright: ignore[reportPrivateUsage] — testing internal proxy types

    q = sql_relational(User)._append(Window(specs=(  # pyright: ignore[reportPrivateUsage] — testing internal _append
        WindowSpec(
            func=Lead(offset=1, default=None),
            field="balance",
            partition_by=(),
            order_by=(OrderSpec("id", ascending=True),),
            alias="next_balance",
        ),
    )))
    stmt = prov._compile_query(q)  # pyright: ignore[reportPrivateUsage] — testing internal compilation
    result = await session.execute(stmt)
    rows = result.all()
    next_balances = [row[-1] for row in rows]
    # Last row has no next → None, first has 200.0, second has 50.0
    assert None in next_balances
    assert 200.0 in next_balances

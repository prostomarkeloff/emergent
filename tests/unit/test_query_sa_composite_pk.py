"""Composite primary-key support in SQLAlchemyRelationalProvider.

Association tables declare more than one Identity field (a composite primary
key). The provider must then:

  * report every key column via identity_fields (not just the first);
  * insert keeping real key values, dropping only placeholders;
  * delete a single entity by the whole key tuple (session.get needs a tuple);
  * delete_where matching the column tuple, so a filter that selects a subset
    does not over-delete rows that merely share one key column.

Regression: previously the provider used a single identity_field, which made
session.get receive a scalar (wrong row / error) and delete_where match a
single column with IN (over-deletion). Uses in-memory SQLite via aiosqlite.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Annotated

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from emergent.wire.axis.query._relational import relational
from emergent.wire.axis.query.contrib import sqlalchemy as sa_query
from emergent.wire.axis.query.contrib._impls._sqlalchemy import (
    SQLAlchemyRelationalProvider,
)
from emergent.wire.axis.schema._universal import Identity


# ─── Composite-PK entity ───────────────────────────────────────────────────────


@dataclass
class Membership:
    """group_id + user_id form the composite primary key."""

    group_id: Annotated[int, Identity]
    user_id: Annotated[int, Identity]
    role: str = "member"


MembershipStore = sa_query.store(Membership, "memberships")


@pytest_asyncio.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(MembershipStore.model.metadata.create_all)
    async with AsyncSession(engine, expire_on_commit=False) as sess:
        yield sess
    await engine.dispose()


@pytest_asyncio.fixture
async def prov(session: AsyncSession) -> SQLAlchemyRelationalProvider[Membership]:
    return MembershipStore(session)


def _keys(rows: list[Membership]) -> set[tuple[int, int]]:
    return {(r.group_id, r.user_id) for r in rows}


# ─── insert keeps real composite key values ────────────────────────────────────


@pytest.mark.asyncio
async def test_insert_persists_full_composite_key(
    prov: SQLAlchemyRelationalProvider[Membership],
) -> None:
    await prov.insert(Membership(group_id=1, user_id=1, role="owner"))
    rows = await prov.fetch_many(relational(Membership))
    assert _keys(rows) == {(1, 1)}
    assert rows[0].role == "owner"


# ─── single-entity delete uses the key tuple ───────────────────────────────────


@pytest.mark.asyncio
async def test_delete_entity_removes_only_that_composite_row(
    prov: SQLAlchemyRelationalProvider[Membership],
) -> None:
    await prov.insert(Membership(group_id=1, user_id=1))
    await prov.insert(Membership(group_id=1, user_id=2))
    await prov.insert(Membership(group_id=2, user_id=1))

    # (1, 1) shares group_id with (1, 2) and user_id with (2, 1): a scalar key
    # would mis-target one of those. The tuple key removes exactly (1, 1).
    await prov.delete(Membership(group_id=1, user_id=1))

    rows = await prov.fetch_many(relational(Membership))
    assert _keys(rows) == {(1, 2), (2, 1)}


# ─── delete_where matches the column tuple (no over-deletion) ──────────────────


@pytest.mark.asyncio
async def test_delete_where_matches_full_key_no_overdeletion(
    prov: SQLAlchemyRelationalProvider[Membership],
) -> None:
    await prov.insert(Membership(group_id=1, user_id=1))
    await prov.insert(Membership(group_id=1, user_id=2))
    await prov.insert(Membership(group_id=2, user_id=2))

    # Filter selects {(1, 2), (2, 2)}. A single-column IN on group_id would map
    # to group_id IN (1, 2) and wrongly also delete (1, 1). The tuple match
    # deletes only the two rows the filter identifies.
    deleted = await prov.delete_where(
        relational(Membership).filter(lambda m: m.user_id == 2)
    )
    assert deleted == 2

    rows = await prov.fetch_many(relational(Membership))
    assert _keys(rows) == {(1, 1)}

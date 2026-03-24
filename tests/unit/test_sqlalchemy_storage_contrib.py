"""Tests for SQLAlchemy storage contrib — compile_model, entity_to_model, model_to_entity,
SQLAlchemyStorage, sqlalchemy factory, SQLAlchemyStore/BoundSQLAlchemyStore, StorageError.

Uses in-memory SQLite via aiosqlite.
"""

from __future__ import annotations

import dataclasses
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Annotated

import pytest
import pytest_asyncio
from sqlalchemy import Column, inspect as sa_inspect
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapper

from kungfu import Nothing, Ok, Some

from emergent.wire.axis.schema._universal import Identity, MaxLen, Unique
from emergent.wire.axis.storage.contrib._impls._sqlalchemy import (
    BoundSQLAlchemyStore,
    SQLAlchemyStorage,
    SQLAlchemyStore,
    StorageError,
    compile_sa,
    compile_model,
    entity_to_model,
    model_to_entity,
    sqlalchemy,
    store,
)


# ─── Test Entities ────────────────────────────────────────────────────────────


@dataclass
class User:
    id: Annotated[int, Identity]
    name: str
    email: Annotated[str, Unique, MaxLen(128)]
    score: int = 0


@dataclass
class Tag:
    """Entity without Identity — for testing missing-PK path."""

    label: str
    value: str


# ─── Shared Declarative Base (isolates metadata per test module) ───────────────


class StorageTestBase(DeclarativeBase):
    pass


# ─── DB Fixtures ─────────────────────────────────────────────────────────────


UserStoreFact = store(User, "test_users", base=StorageTestBase)


@pytest_asyncio.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    async with engine.begin() as conn:
        await conn.run_sync(StorageTestBase.metadata.create_all)

    async with AsyncSession(engine, expire_on_commit=False) as sess:
        yield sess

    await engine.dispose()


@pytest_asyncio.fixture
async def storage(session: AsyncSession) -> SQLAlchemyStorage[User]:
    return SQLAlchemyStorage(
        session=session,
        entity=User,
        tablename="test_users",
        base=StorageTestBase,
    )


@pytest_asyncio.fixture
async def bound(session: AsyncSession) -> BoundSQLAlchemyStore[User]:
    return UserStoreFact.bind(session)


# ─── compile_model ────────────────────────────────────────────────────────────


class TestCompileModel:
    def test_returns_a_class(self) -> None:
        model = compile_model(User, "cm_users", base=StorageTestBase)
        assert isinstance(model, type)

    def test_model_has_correct_tablename(self) -> None:
        model = compile_model(User, "cm_tablename_users", base=StorageTestBase)
        assert model.__tablename__ == "cm_tablename_users"

    def test_model_columns_match_entity_fields(self) -> None:
        model = compile_model(User, "cm_cols_users", base=StorageTestBase)
        mapper: Mapper[User] = sa_inspect(model)
        col_names: set[str] = {col.key for col in mapper.columns}
        field_names = {f.name for f in dataclasses.fields(User)}
        assert field_names.issubset(col_names)

    def test_identity_field_is_primary_key(self) -> None:
        model = compile_model(User, "cm_pk_users", base=StorageTestBase)
        mapper: Mapper[User] = sa_inspect(model)
        pk_cols: set[str] = {col.key for col in mapper.columns if col.primary_key}
        assert "id" in pk_cols

    def test_identity_field_on_compilation(self) -> None:
        compiled = compile_sa(User, "cm_ident_users", base=StorageTestBase)
        assert compiled.identity_field == "id"

    def test_non_dataclass_raises(self) -> None:
        class NotADataclass:
            pass

        with pytest.raises(TypeError):
            compile_model(NotADataclass, "bad_table", base=StorageTestBase)  # type: ignore[arg-type]

    def test_max_len_produces_string_column(self) -> None:
        model = compile_model(User, "cm_maxlen_users", base=StorageTestBase)
        mapper: Mapper[User] = sa_inspect(model)
        email_col: Column[str] = next(c for c in mapper.columns if c.key == "email")
        # SQLAlchemy String with explicit length
        col_type_name = type(email_col.type).__name__
        assert col_type_name == "String"


# ─── entity_to_model / model_to_entity ───────────────────────────────────────


class TestEntityMapping:
    def test_entity_to_model_creates_model_instance(self) -> None:
        compiled = compile_sa(User, "em_users", base=StorageTestBase)
        user = User(id=1, name="Alice", email="alice@example.com", score=10)
        model_inst = entity_to_model(user, compiled)
        assert model_inst.id == 1
        assert model_inst.name == "Alice"
        assert model_inst.email == "alice@example.com"
        assert model_inst.score == 10

    def test_model_to_entity_restores_original(self) -> None:
        compiled = compile_sa(User, "me_users", base=StorageTestBase)
        user = User(id=2, name="Bob", email="bob@example.com", score=42)
        model_inst = entity_to_model(user, compiled)
        restored = model_to_entity(model_inst, compiled)
        assert restored == user

    def test_round_trip_preserves_all_fields(self) -> None:
        compiled = compile_sa(User, "rt_users", base=StorageTestBase)
        original = User(id=99, name="Carol", email="carol@example.com", score=7)
        model_inst = entity_to_model(original, compiled)
        result = model_to_entity(model_inst, compiled)
        assert result.id == original.id
        assert result.name == original.name
        assert result.email == original.email
        assert result.score == original.score

    def test_entity_to_model_raises_for_non_dataclass(self) -> None:
        compiled = compile_sa(User, "err_users", base=StorageTestBase)

        with pytest.raises(TypeError):
            entity_to_model("not-a-dataclass", compiled)

    def test_model_to_entity_raises_for_non_dataclass_class(self) -> None:
        compiled = compile_sa(User, "err2_users", base=StorageTestBase)
        user = User(id=1, name="Alice", email="a@b.com")
        model_inst = entity_to_model(user, compiled)

        # Create a fake compilation with a non-dataclass entity
        from emergent.wire.compile._phase import Compilation
        bad_compiled = Compilation(
            model=compiled.model,
            entity=str,
            fields=(),
        )
        with pytest.raises(TypeError):
            model_to_entity(model_inst, bad_compiled)


# ─── StorageError ─────────────────────────────────────────────────────────────


class TestStorageError:
    def test_is_dataclass(self) -> None:
        assert dataclasses.is_dataclass(StorageError)

    def test_stores_message(self) -> None:
        err = StorageError(message="something went wrong")
        assert err.message == "something went wrong"

    def test_stores_cause(self) -> None:
        cause = ValueError("original")
        err = StorageError(message="wrapped", cause=cause)
        assert err.cause is cause

    def test_cause_defaults_to_none(self) -> None:
        err = StorageError(message="no cause")
        assert err.cause is None


# ─── SQLAlchemyStorage KV operations ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_storage_set_and_get(storage: SQLAlchemyStorage[User], session: AsyncSession) -> None:
    user = User(id=1, name="Alice", email="alice@example.com", score=5)
    set_result = await storage.set(user)
    await session.commit()

    assert isinstance(set_result, Ok)
    assert set_result.value.id == 1

    get_result = await storage.get(1)
    assert isinstance(get_result, Ok)
    assert isinstance(get_result.value, Some)
    fetched = get_result.value.value
    assert fetched.name == "Alice"
    assert fetched.email == "alice@example.com"


@pytest.mark.asyncio
async def test_storage_get_missing_key_returns_nothing(
    storage: SQLAlchemyStorage[User],
) -> None:
    result = await storage.get(9999)
    assert isinstance(result, Ok)
    assert isinstance(result.value, Nothing)


@pytest.mark.asyncio
async def test_storage_set_overwrites_existing(
    storage: SQLAlchemyStorage[User], session: AsyncSession
) -> None:
    user = User(id=10, name="Original", email="orig@example.com", score=0)
    await storage.set(user)
    await session.commit()

    updated = User(id=10, name="Updated", email="orig@example.com", score=99)
    await storage.set(updated)
    await session.commit()

    result = await storage.get(10)
    assert isinstance(result, Ok)
    assert isinstance(result.value, Some)
    assert result.value.value.name == "Updated"
    assert result.value.value.score == 99


@pytest.mark.asyncio
async def test_storage_delete_removes_entry(
    storage: SQLAlchemyStorage[User], session: AsyncSession
) -> None:
    user = User(id=20, name="Dave", email="dave@example.com")
    await storage.set(user)
    await session.commit()

    del_result = await storage.delete(20)
    await session.commit()

    assert isinstance(del_result, Ok)
    assert del_result.value is True

    get_after = await storage.get(20)
    assert isinstance(get_after, Ok)
    assert isinstance(get_after.value, Nothing)


@pytest.mark.asyncio
async def test_storage_delete_nonexistent_returns_false(
    storage: SQLAlchemyStorage[User],
) -> None:
    result = await storage.delete(88888)
    assert isinstance(result, Ok)
    assert result.value is False


# ─── sqlalchemy() factory ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sqlalchemy_factory_returns_working_storage(session: AsyncSession) -> None:
    stg = sqlalchemy(session, User, "test_users", base=StorageTestBase)
    assert isinstance(stg, SQLAlchemyStorage)
    assert stg.entity is User

    user = User(id=50, name="Eve", email="eve@example.com")
    result = await stg.set(user)
    await session.commit()
    assert isinstance(result, Ok)

    fetch = await stg.get(50)
    assert isinstance(fetch, Ok)
    assert isinstance(fetch.value, Some)
    assert fetch.value.value.name == "Eve"


# ─── SQLAlchemyStore / BoundSQLAlchemyStore ───────────────────────────────────


@pytest.mark.asyncio
async def test_store_pattern_bind_and_set_get(
    bound: BoundSQLAlchemyStore[User], session: AsyncSession
) -> None:
    user = User(id=100, name="Frank", email="frank@example.com", score=3)
    set_result = await bound.set(user)
    await session.commit()

    assert isinstance(set_result, Ok)

    get_result = await bound.get(100)
    assert isinstance(get_result, Ok)
    assert isinstance(get_result.value, Some)
    assert get_result.value.value.name == "Frank"


@pytest.mark.asyncio
async def test_store_callable_shortcut(session: AsyncSession) -> None:
    bound_via_call = UserStoreFact(session)
    assert isinstance(bound_via_call, BoundSQLAlchemyStore)

    user = User(id=200, name="Grace", email="grace@example.com")
    await bound_via_call.set(user)
    await session.commit()

    result = await bound_via_call.get(200)
    assert isinstance(result, Ok)
    assert isinstance(result.value, Some)
    assert result.value.value.name == "Grace"


def test_sqlalchemy_store_exposes_entity_and_tablename() -> None:
    s = SQLAlchemyStore(User, "store_meta_users", base=StorageTestBase)
    assert s.entity is User
    assert s.tablename == "store_meta_users"


def test_store_factory_function_returns_sqlalchemy_store() -> None:
    s = store(User, "factory_users", base=StorageTestBase)
    assert isinstance(s, SQLAlchemyStore)
    assert s.entity is User

"""Tests for SQLAlchemy storage exception/error branches.

Covers the `except Exception as e: return Error(StorageError(...))` paths in both
SQLAlchemyStorage and BoundSQLAlchemyStore, plus edge cases for compile_model schema
parameter and BoundSQLAlchemyStore properties.

Uses mocked sessions that raise on execute/merge/flush/delete to trigger error branches.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase

from kungfu import Error

from emergent.wire.axis.schema._universal import Identity, MaxLen, Unique, schema_meta
from emergent.wire.axis.schema.dialects.sql import CompositeIndex, CompositeUnique, PrimaryKey
from emergent.wire.axis.storage.contrib._impls._sqlalchemy import (
    BoundSQLAlchemyStore,
    SQLAlchemyStorage,
    StorageError,
    compile_model,
    compile_sa,
)


# ─── Test Entities ────────────────────────────────────────────────────────────


@dataclass
class User:
    id: Annotated[int, Identity]
    name: str
    email: Annotated[str, Unique, MaxLen(128)]
    score: int = 0


# ─── Separate Base per test module (isolates metadata) ────────────────────────


class ErrorTestBase(DeclarativeBase):
    pass


# Compile model once (reused across tests)
UserModel = compile_model(User, "err_users", base=ErrorTestBase)


# ─── Helper: build a mock session that raises on async calls ─────────────────


def _make_failing_session(error_msg: str = "DB connection lost") -> AsyncMock:
    """Create an AsyncMock session whose execute/merge/flush/delete all raise."""
    mock_session = AsyncMock(spec=AsyncSession)
    exc = RuntimeError(error_msg)
    mock_session.execute.side_effect = exc
    mock_session.merge.side_effect = exc
    mock_session.flush.side_effect = exc
    mock_session.delete.side_effect = exc
    return mock_session


# ═══════════════════════════════════════════════════════════════════════════════
# 1. SQLAlchemyStorage — exception branches (10 methods)
# ═══════════════════════════════════════════════════════════════════════════════


def _make_storage_with_failing_session(
    error_msg: str = "DB connection lost",
) -> SQLAlchemyStorage[User]:
    """Build SQLAlchemyStorage[User] with a mock session that raises."""
    mock_session = _make_failing_session(error_msg)
    # Use proper constructor — compile_model reuses existing table from ErrorTestBase
    return SQLAlchemyStorage(
        session=mock_session,
        entity=User,
        tablename="err_users",
        base=ErrorTestBase,
    )


class TestSQLAlchemyStorageGetError:
    @pytest.mark.asyncio
    async def test_get_exception_returns_error(self) -> None:
        storage = _make_storage_with_failing_session()
        result = await storage.get(1)

        assert isinstance(result, Error)
        err = result.error
        assert isinstance(err, StorageError)
        assert "Failed to get" in err.message
        assert isinstance(err.cause, RuntimeError)

    @pytest.mark.asyncio
    async def test_get_error_includes_cause_message(self) -> None:
        storage = _make_storage_with_failing_session("unique error 42")
        result = await storage.get(99)

        assert isinstance(result, Error)
        assert "unique error 42" in result.error.message


class TestSQLAlchemyStorageSetError:
    @pytest.mark.asyncio
    async def test_set_exception_returns_error(self) -> None:
        storage = _make_storage_with_failing_session()
        user = User(id=1, name="Alice", email="a@a.com", score=10)
        result = await storage.set(user)

        assert isinstance(result, Error)
        err = result.error
        assert isinstance(err, StorageError)
        assert "Failed to set" in err.message
        assert isinstance(err.cause, RuntimeError)


class TestSQLAlchemyStorageDeleteError:
    @pytest.mark.asyncio
    async def test_delete_exception_returns_error(self) -> None:
        storage = _make_storage_with_failing_session()
        result = await storage.delete(1)

        assert isinstance(result, Error)
        err = result.error
        assert isinstance(err, StorageError)
        assert "Failed to delete" in err.message
        assert isinstance(err.cause, RuntimeError)


class TestSQLAlchemyStorageExistsError:
    @pytest.mark.asyncio
    async def test_exists_exception_returns_error(self) -> None:
        storage = _make_storage_with_failing_session()
        result = await storage.exists(1)

        assert isinstance(result, Error)
        err = result.error
        assert isinstance(err, StorageError)
        assert "Failed to check exists" in err.message
        assert isinstance(err.cause, RuntimeError)


class TestSQLAlchemyStorageFindError:
    @pytest.mark.asyncio
    async def test_find_exception_returns_error(self) -> None:
        storage = _make_storage_with_failing_session()
        result = await storage.find(lambda u: u.score > 50)

        assert isinstance(result, Error)
        err = result.error
        assert isinstance(err, StorageError)
        assert "Failed to find" in err.message
        assert isinstance(err.cause, RuntimeError)


class TestSQLAlchemyStorageFindOneError:
    @pytest.mark.asyncio
    async def test_find_one_exception_returns_error(self) -> None:
        storage = _make_storage_with_failing_session()
        result = await storage.find_one(lambda u: u.name == "Alice")

        assert isinstance(result, Error)
        err = result.error
        assert isinstance(err, StorageError)
        assert "Failed to find_one" in err.message
        assert isinstance(err.cause, RuntimeError)


class TestSQLAlchemyStorageCountError:
    @pytest.mark.asyncio
    async def test_count_exception_returns_error(self) -> None:
        storage = _make_storage_with_failing_session()
        result = await storage.count()

        assert isinstance(result, Error)
        err = result.error
        assert isinstance(err, StorageError)
        assert "Failed to count" in err.message
        assert isinstance(err.cause, RuntimeError)

    @pytest.mark.asyncio
    async def test_count_with_predicate_exception_returns_error(self) -> None:
        storage = _make_storage_with_failing_session()
        result = await storage.count(lambda u: u.score > 0)

        assert isinstance(result, Error)
        assert "Failed to count" in result.error.message


class TestSQLAlchemyStorageDeleteWhereError:
    @pytest.mark.asyncio
    async def test_delete_where_exception_returns_error(self) -> None:
        storage = _make_storage_with_failing_session()
        result = await storage.delete_where(lambda u: u.score < 10)

        assert isinstance(result, Error)
        err = result.error
        assert isinstance(err, StorageError)
        assert "Failed to delete_where" in err.message
        assert isinstance(err.cause, RuntimeError)


class TestSQLAlchemyStorageSetManyError:
    @pytest.mark.asyncio
    async def test_set_many_exception_returns_error(self) -> None:
        storage = _make_storage_with_failing_session()
        users = [User(id=1, name="A", email="a@a.com")]
        result = await storage.set_many(users)

        assert isinstance(result, Error)
        err = result.error
        assert isinstance(err, StorageError)
        assert "Failed to set_many" in err.message
        assert isinstance(err.cause, RuntimeError)


class TestSQLAlchemyStorageAllError:
    @pytest.mark.asyncio
    async def test_all_exception_returns_error(self) -> None:
        storage = _make_storage_with_failing_session()
        result = await storage.all()

        assert isinstance(result, Error)
        err = result.error
        assert isinstance(err, StorageError)
        assert "Failed to get all" in err.message
        assert isinstance(err.cause, RuntimeError)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. BoundSQLAlchemyStore — exception branches (10 methods)
# ═══════════════════════════════════════════════════════════════════════════════


_user_compiled = compile_sa(User, "err_users", base=ErrorTestBase)


def _make_bound_with_failing_session(
    error_msg: str = "DB connection lost",
) -> BoundSQLAlchemyStore[User]:
    """Build BoundSQLAlchemyStore[User] with a mock session that raises."""
    mock_session = _make_failing_session(error_msg)
    return BoundSQLAlchemyStore(
        session=mock_session,
        compiled=_user_compiled,
    )


class TestBoundStoreGetError:
    @pytest.mark.asyncio
    async def test_get_exception_returns_error(self) -> None:
        bound = _make_bound_with_failing_session()
        result = await bound.get(1)

        assert isinstance(result, Error)
        err = result.error
        assert isinstance(err, StorageError)
        assert "Failed to get" in err.message
        assert isinstance(err.cause, RuntimeError)

    @pytest.mark.asyncio
    async def test_get_error_includes_cause_message(self) -> None:
        bound = _make_bound_with_failing_session("connection refused")
        result = await bound.get(42)

        assert isinstance(result, Error)
        assert "connection refused" in result.error.message


class TestBoundStoreSetError:
    @pytest.mark.asyncio
    async def test_set_exception_returns_error(self) -> None:
        bound = _make_bound_with_failing_session()
        user = User(id=1, name="Alice", email="a@a.com", score=10)
        result = await bound.set(user)

        assert isinstance(result, Error)
        err = result.error
        assert isinstance(err, StorageError)
        assert "Failed to set" in err.message
        assert isinstance(err.cause, RuntimeError)


class TestBoundStoreDeleteError:
    @pytest.mark.asyncio
    async def test_delete_exception_returns_error(self) -> None:
        bound = _make_bound_with_failing_session()
        result = await bound.delete(1)

        assert isinstance(result, Error)
        err = result.error
        assert isinstance(err, StorageError)
        assert "Failed to delete" in err.message
        assert isinstance(err.cause, RuntimeError)


class TestBoundStoreExistsError:
    @pytest.mark.asyncio
    async def test_exists_exception_returns_error(self) -> None:
        bound = _make_bound_with_failing_session()
        result = await bound.exists(1)

        assert isinstance(result, Error)
        err = result.error
        assert isinstance(err, StorageError)
        assert "Failed to check exists" in err.message
        assert isinstance(err.cause, RuntimeError)


class TestBoundStoreFindError:
    @pytest.mark.asyncio
    async def test_find_exception_returns_error(self) -> None:
        bound = _make_bound_with_failing_session()
        result = await bound.find(lambda u: u.score > 50)

        assert isinstance(result, Error)
        err = result.error
        assert isinstance(err, StorageError)
        assert "Failed to find" in err.message
        assert isinstance(err.cause, RuntimeError)


class TestBoundStoreFindOneError:
    @pytest.mark.asyncio
    async def test_find_one_exception_returns_error(self) -> None:
        bound = _make_bound_with_failing_session()
        result = await bound.find_one(lambda u: u.name == "Alice")

        assert isinstance(result, Error)
        err = result.error
        assert isinstance(err, StorageError)
        assert "Failed to find_one" in err.message
        assert isinstance(err.cause, RuntimeError)


class TestBoundStoreCountError:
    @pytest.mark.asyncio
    async def test_count_exception_returns_error(self) -> None:
        bound = _make_bound_with_failing_session()
        result = await bound.count()

        assert isinstance(result, Error)
        err = result.error
        assert isinstance(err, StorageError)
        assert "Failed to count" in err.message
        assert isinstance(err.cause, RuntimeError)

    @pytest.mark.asyncio
    async def test_count_with_predicate_exception_returns_error(self) -> None:
        bound = _make_bound_with_failing_session()
        result = await bound.count(lambda u: u.score > 0)

        assert isinstance(result, Error)
        assert "Failed to count" in result.error.message


class TestBoundStoreDeleteWhereError:
    @pytest.mark.asyncio
    async def test_delete_where_exception_returns_error(self) -> None:
        bound = _make_bound_with_failing_session()
        result = await bound.delete_where(lambda u: u.score < 10)

        assert isinstance(result, Error)
        err = result.error
        assert isinstance(err, StorageError)
        assert "Failed to delete_where" in err.message
        assert isinstance(err.cause, RuntimeError)


class TestBoundStoreSetManyError:
    @pytest.mark.asyncio
    async def test_set_many_exception_returns_error(self) -> None:
        bound = _make_bound_with_failing_session()
        users = [User(id=1, name="A", email="a@a.com")]
        result = await bound.set_many(users)

        assert isinstance(result, Error)
        err = result.error
        assert isinstance(err, StorageError)
        assert "Failed to set_many" in err.message
        assert isinstance(err.cause, RuntimeError)


class TestBoundStoreAllError:
    @pytest.mark.asyncio
    async def test_all_exception_returns_error(self) -> None:
        bound = _make_bound_with_failing_session()
        result = await bound.all()

        assert isinstance(result, Error)
        err = result.error
        assert isinstance(err, StorageError)
        assert "Failed to get all" in err.message
        assert isinstance(err.cause, RuntimeError)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Edge Cases — no identity field, compile_model schema, properties
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class NoIdentityEntity:
    """Entity with PrimaryKey (for SQLAlchemy) but no Identity (for emergent)."""
    pk: Annotated[int, PrimaryKey()]
    name: str
    value: int = 0


class TestCompileSaRejectsNoIdentity:
    """compile_sa raises TypeError when entity has no Identity field."""

    def test_no_identity_raises_type_error(self) -> None:
        class NoIdBase(DeclarativeBase):
            pass

        with pytest.raises(TypeError, match="has no field annotated with Identity"):
            compile_sa(NoIdentityEntity, "no_identity_test", base=NoIdBase)


class TestCompileModelSchemaParameter:
    """compile_model with schema= sets __table_args__."""

    def test_compile_model_with_schema_sets_table_args(self) -> None:
        class SchemaTestBase(DeclarativeBase):
            pass

        model = compile_model(User, "schema_users", base=SchemaTestBase, schema="myschema")
        table_args = getattr(model, "__table_args__", None)
        assert table_args is not None
        assert table_args["schema"] == "myschema"

    def test_compile_model_without_schema_has_no_table_args(self) -> None:
        class NoSchemaBase(DeclarativeBase):
            pass

        model = compile_model(User, "noschema_users", base=NoSchemaBase)
        # __table_args__ either doesn't exist or wasn't set as a dict with "schema"
        table_args = getattr(model, "__table_args__", None)
        if table_args is not None:
            assert "schema" not in table_args


class TestCompileModelTableLevelIndexesConstraints:
    """Table-level CompositeIndex/CompositeUnique materialize as named DDL.

    Regression guard: previously these capabilities populated the table context
    but were dropped by the assembler (name/unique/access-method silently lost),
    so a generated model diverged from a hand-written schema.
    """

    def test_named_unique_index_and_constraint_materialize(self) -> None:
        @schema_meta(
            CompositeUnique("email", "tenant_id", name="uq_email_tenant"),
            CompositeIndex("status", "created_at", name="ix_status_created", unique=True, using="btree"),
        )
        @dataclass
        class Account:
            id: Annotated[int, Identity]
            email: str
            tenant_id: int
            status: str
            created_at: str

        class TableArgsBase(DeclarativeBase):
            pass

        model = compile_sa(Account, "accounts", base=TableArgsBase).model
        table = model.__table__  # type: ignore[attr-defined]

        index_by_name = {ix.name: ix for ix in table.indexes}
        assert "ix_status_created" in index_by_name
        ix = index_by_name["ix_status_created"]
        assert ix.unique is True
        assert [c.name for c in ix.columns] == ["status", "created_at"]
        # access method carried through, dialect-neutral (applied to dialects that have one)
        assert ix.dialect_options["postgresql"]["using"] == "btree"

        unique_constraint_names = {
            c.name for c in table.constraints if type(c).__name__ == "UniqueConstraint"
        }
        assert "uq_email_tenant" in unique_constraint_names


class TestBoundSQLAlchemyStoreProperties:
    """BoundSQLAlchemyStore.entity and .model properties."""

    def test_entity_property_returns_entity_class(self) -> None:
        mock_session = AsyncMock(spec=AsyncSession)
        bound = BoundSQLAlchemyStore(
            session=mock_session,
            compiled=_user_compiled,
        )

        assert bound.entity is User

    def test_model_property_returns_model_class(self) -> None:
        mock_session = AsyncMock(spec=AsyncSession)
        bound = BoundSQLAlchemyStore(
            session=mock_session,
            compiled=_user_compiled,
        )

        assert bound.model is UserModel


class TestSQLAlchemyStorageProperties:
    """SQLAlchemyStorage.entity and .model properties."""

    def test_entity_property(self) -> None:
        storage = SQLAlchemyStorage(
            session=AsyncMock(spec=AsyncSession),
            entity=User,
            tablename="err_users",
            base=ErrorTestBase,
        )

        assert storage.entity is User

    def test_model_property(self) -> None:
        storage = SQLAlchemyStorage(
            session=AsyncMock(spec=AsyncSession),
            entity=User,
            tablename="err_users",
            base=ErrorTestBase,
        )

        assert storage.model is UserModel

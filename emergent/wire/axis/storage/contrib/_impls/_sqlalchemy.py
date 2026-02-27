"""SQLAlchemy storage backend — runtime store operations.

IMPORTANT: Backend does NOT own transactions. Caller provides session, caller commits.

Compilation (compile_sa, compile_expr, entity_to_model, model_to_entity)
lives in emergent.wire.compile.targets.sqlalchemy.

Usage:
    from emergent.wire.axis.storage.contrib import sqlalchemy

    @dataclass
    class User:
        id: Annotated[int, Identity]
        email: Annotated[str, Unique, MaxLen(255)]
        balance: Annotated[int, Min(0)]

    UserStore = sqlalchemy.store(User, "users")

    async with session_factory() as session:
        users = UserStore(session)

        await users.set(user)
        user = await users.get(123)
        await users.delete(123)

        await session.commit()  # Caller commits!

Requires: sqlalchemy[asyncio]
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import (
    delete,
    func,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase

from kungfu import Result, Ok, Error, Option, Some, Nothing

from emergent.wire.axis.query._proxy import EntityProxy, build_expr

# Compilation — lives in compile/_phase.py
from emergent.wire.compile._phase import Compilation
from emergent.wire.compile.targets.sqlalchemy import (
    SA_TYPE_MAP as SA_TYPE_MAP,
    SA_PHASE as SA_PHASE,
    SA_PHASES as SA_PHASES,
    compile_sa as compile_sa,
    compile_model as compile_model,
    compile_expr as compile_expr,
    entity_to_model as entity_to_model,
    model_to_entity as model_to_entity,
)
from emergent.wire.axis.query._expr import Expr

if TYPE_CHECKING:
    from sqlalchemy.engine import CursorResult


# ═══════════════════════════════════════════════════════════════════════════════
# Storage Error
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class StorageError:
    """Storage operation error."""
    message: str
    cause: Exception | None = None


# ═══════════════════════════════════════════════════════════════════════════════
# Store Pattern — separates configuration from session
# ═══════════════════════════════════════════════════════════════════════════════


class SQLAlchemyStore[T]:
    """Store factory — configure once, use with any session.

    Separates storage configuration from session lifecycle.
    Model is compiled once at store creation via compile_sa.

    Usage:
        # Configure once (at app startup)
        UserStore = SQLAlchemyStore(User, "users")

        # Use with any session
        async with session_factory() as session:
            users = UserStore(session)
            await users.set(user)
            await session.commit()
    """

    __slots__ = ("_tablename", "_compiled")

    _tablename: str
    _compiled: Compilation[T, DeclarativeBase]

    def __init__(
        self,
        entity: type[T],
        tablename: str,
        base: type[DeclarativeBase] | None = None,
        schema: str | None = None,
    ) -> None:
        self._tablename = tablename
        self._compiled = compile_sa(entity, tablename, base, schema)

    @property
    def entity(self) -> type[T]:
        return self._compiled.entity

    @property
    def model(self) -> type[DeclarativeBase]:
        return self._compiled.model

    @property
    def tablename(self) -> str:
        return self._tablename

    def bind(self, session: AsyncSession) -> BoundSQLAlchemyStore[T]:
        """Bind store to session — returns object with all storage operations."""
        return BoundSQLAlchemyStore(
            session=session,
            compiled=self._compiled,
        )

    def __call__(self, session: AsyncSession) -> BoundSQLAlchemyStore[T]:
        """Shortcut for bind(session)."""
        return self.bind(session)


class BoundSQLAlchemyStore[T]:
    """Store bound to a session — provides all storage operations.

    Created by SQLAlchemyStore.bind(session) or SQLAlchemyStore(session).

    IMPORTANT: Does NOT own transactions. Caller commits.
    """

    __slots__ = ("_session", "_compiled")

    _session: AsyncSession
    _compiled: Compilation[T, DeclarativeBase]

    def __init__(
        self,
        session: AsyncSession,
        compiled: Compilation[T, DeclarativeBase],
    ) -> None:
        self._session = session
        self._compiled = compiled

    @property
    def entity(self) -> type[T]:
        return self._compiled.entity

    @property
    def model(self) -> type[DeclarativeBase]:
        return self._compiled.model

    # ─── KV Operations ────────────────────────────────────────────────────────

    async def get(self, key: object) -> Result[Option[T], StorageError]:
        """Get entity by primary key."""
        try:
            stmt = select(self._compiled.model).where(
                getattr(self._compiled.model, self._compiled.identity_field) == key
            )
            result = await self._session.execute(stmt)
            row = result.scalar_one_or_none()

            if row is None:
                return Ok(Nothing())

            return Ok(Some(model_to_entity(row, self._compiled)))

        except Exception as e:
            return Error(StorageError(f"Failed to get: {e}", e))

    async def set(self, entity: T) -> Result[T, StorageError]:
        """Insert or update entity (upsert by primary key)."""
        try:
            model_instance = entity_to_model(entity, self._compiled)
            merged = await self._session.merge(model_instance)
            await self._session.flush()
            return Ok(model_to_entity(merged, self._compiled))

        except Exception as e:
            return Error(StorageError(f"Failed to set: {e}", e))

    async def delete(self, key: object) -> Result[bool, StorageError]:
        """Delete entity by primary key. Returns True if existed."""
        try:
            stmt = select(self._compiled.model).where(
                getattr(self._compiled.model, self._compiled.identity_field) == key
            )
            result = await self._session.execute(stmt)
            row = result.scalar_one_or_none()

            if row is None:
                return Ok(False)

            await self._session.delete(row)
            return Ok(True)

        except Exception as e:
            return Error(StorageError(f"Failed to delete: {e}", e))

    async def exists(self, key: object) -> Result[bool, StorageError]:
        """Check if entity exists by primary key."""
        try:
            stmt = select(func.count()).select_from(self._compiled.model).where(
                getattr(self._compiled.model, self._compiled.identity_field) == key
            )
            result = await self._session.execute(stmt)
            count_val: int = result.scalar_one()
            return Ok(count_val > 0)

        except Exception as e:
            return Error(StorageError(f"Failed to check exists: {e}", e))

    # ─── Relational Operations ────────────────────────────────────────────────

    async def find(
        self,
        predicate: Callable[[EntityProxy[T]], Expr],
    ) -> Result[list[T], StorageError]:
        """Find all entities matching predicate."""
        try:
            expr = build_expr(self._compiled.entity, predicate)
            where_clause = compile_expr(expr, self._compiled)

            stmt = select(self._compiled.model).where(where_clause)
            result = await self._session.execute(stmt)
            rows = result.scalars().all()

            entities = [model_to_entity(row, self._compiled) for row in rows]
            return Ok(entities)

        except Exception as e:
            return Error(StorageError(f"Failed to find: {e}", e))

    async def find_one(
        self,
        predicate: Callable[[EntityProxy[T]], Expr],
    ) -> Result[Option[T], StorageError]:
        """Find single entity matching predicate."""
        try:
            expr = build_expr(self._compiled.entity, predicate)
            where_clause = compile_expr(expr, self._compiled)

            stmt = select(self._compiled.model).where(where_clause).limit(1)
            result = await self._session.execute(stmt)
            row = result.scalar_one_or_none()

            if row is None:
                return Ok(Nothing())

            return Ok(Some(model_to_entity(row, self._compiled)))

        except Exception as e:
            return Error(StorageError(f"Failed to find_one: {e}", e))

    async def count(
        self,
        predicate: Callable[[EntityProxy[T]], Expr] | None = None,
    ) -> Result[int, StorageError]:
        """Count entities, optionally filtered."""
        try:
            stmt = select(func.count()).select_from(self._compiled.model)

            if predicate is not None:
                expr = build_expr(self._compiled.entity, predicate)
                where_clause = compile_expr(expr, self._compiled)
                stmt = stmt.where(where_clause)

            result = await self._session.execute(stmt)
            count_val: int = result.scalar_one()
            return Ok(count_val)

        except Exception as e:
            return Error(StorageError(f"Failed to count: {e}", e))

    async def delete_where(
        self,
        predicate: Callable[[EntityProxy[T]], Expr],
    ) -> Result[int, StorageError]:
        """Delete all entities matching predicate. Returns count."""
        try:
            expr = build_expr(self._compiled.entity, predicate)
            where_clause = compile_expr(expr, self._compiled)

            stmt = delete(self._compiled.model).where(where_clause)
            cursor: CursorResult[tuple[object, ...]] = await self._session.execute(stmt)  # type: ignore[assignment]
            return Ok(cursor.rowcount)

        except Exception as e:
            return Error(StorageError(f"Failed to delete_where: {e}", e))

    # ─── Bulk Operations ──────────────────────────────────────────────────────

    async def set_many(self, entities: Sequence[T]) -> Result[list[T], StorageError]:
        """Insert or update multiple entities."""
        try:
            results: list[T] = []
            for ent in entities:
                model_instance = entity_to_model(ent, self._compiled)
                merged = await self._session.merge(model_instance)
                results.append(model_to_entity(merged, self._compiled))
            await self._session.flush()
            return Ok(results)

        except Exception as e:
            return Error(StorageError(f"Failed to set_many: {e}", e))

    async def all(self) -> Result[list[T], StorageError]:
        """Get all entities."""
        try:
            stmt = select(self._compiled.model)
            result = await self._session.execute(stmt)
            rows = result.scalars().all()
            entities = [model_to_entity(row, self._compiled) for row in rows]
            return Ok(entities)

        except Exception as e:
            return Error(StorageError(f"Failed to get all: {e}", e))


# ═══════════════════════════════════════════════════════════════════════════════
# Backwards-Compat Alias
# ═══════════════════════════════════════════════════════════════════════════════


class SQLAlchemyStorage[T](BoundSQLAlchemyStore[T]):
    """Backwards-compat: old API that takes session in __init__.

    Prefer SQLAlchemyStore (configure once) + .bind(session).
    """

    def __init__(
        self,
        session: AsyncSession,
        entity: type[T],
        tablename: str,
        base: type[DeclarativeBase] | None = None,
        schema: str | None = None,
    ) -> None:
        compiled = compile_sa(entity, tablename, base, schema)
        super().__init__(
            session=session,
            compiled=compiled,
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Factory Functions
# ═══════════════════════════════════════════════════════════════════════════════


def store[T](
    entity: type[T],
    tablename: str,
    base: type[DeclarativeBase] | None = None,
    schema: str | None = None,
) -> SQLAlchemyStore[T]:
    """Create SQLAlchemy store factory.

    Store separates configuration from session — configure once, use with any session.
    Model is compiled once at creation.

    Example:
        from emergent.wire.axis.storage.contrib import sqlalchemy

        UserStore = sqlalchemy.store(User, "users")

        async with session_factory() as session:
            users = UserStore(session)
            await users.set(User(id=1, email="alice@example.com"))
            await session.commit()
    """
    return SQLAlchemyStore(
        entity=entity,
        tablename=tablename,
        base=base,
        schema=schema,
    )


def sqlalchemy[T](
    session: AsyncSession,
    entity: type[T],
    tablename: str,
    base: type[DeclarativeBase] | None = None,
    schema: str | None = None,
) -> SQLAlchemyStorage[T]:
    """Create bound SQLAlchemy storage for entity (convenience one-liner).

    Compiles model and binds to session in one call.
    Prefer store() for production — compile once, bind many.

    Example:
        async with session_factory() as session:
            users = sqlalchemy(session, User, "users")
            await users.set(User(id=1, email="alice@example.com"))
            await session.commit()
    """
    return SQLAlchemyStorage(
        session=session,
        entity=entity,
        tablename=tablename,
        base=base,
        schema=schema,
    )


__all__ = (
    # Compilation
    "compile_sa",
    "compile_model",
    # Expression compiler
    "compile_expr",
    # Mapping
    "entity_to_model",
    "model_to_entity",
    # Storage error
    "StorageError",
    # Store (factory pattern) — primary API
    "SQLAlchemyStore",
    "BoundSQLAlchemyStore",
    "store",
    # Convenience one-liner
    "sqlalchemy",
    # Backwards-compat alias
    "SQLAlchemyStorage",
)

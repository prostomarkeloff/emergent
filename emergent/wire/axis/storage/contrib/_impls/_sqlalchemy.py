"""SQLAlchemy storage backend — unified storage with model generation.

IMPORTANT: Backend does NOT own transactions. Caller provides session, caller commits.

Usage:
    from emergent.wire.axis import storage
    from emergent.wire.axis.schema import Identity, Unique, MaxLen

    @dataclass
    class User:
        id: Annotated[int, Identity]
        email: Annotated[str, Unique, MaxLen(255)]
        balance: Annotated[int, Min(0)]

    async with session_factory() as session:
        users = storage.sqlalchemy(
            session,
            entity=User,
            tablename="users",
        )

        # KV-style by primary key
        await users.set(user)
        user = await users.get(123)
        await users.delete(123)

        # Relational queries
        active = await users.find(lambda u: u.balance > 0)
        one = await users.find_one(lambda u: u.email == "alice@example.com")

        await session.commit()  # Caller commits!

Requires: sqlalchemy[asyncio]
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Generic, TypeVar, cast

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    delete,
    func,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.engine import CursorResult

from kungfu import Result, Ok, Error, Option, Some, Nothing

from emergent.wire.axis.schema._inspect import inspect_dataclass, FieldInfo
from emergent.wire.compile._core import fold_field
from emergent.wire.axis._capability import (
    SQLAlchemyContext, SQLAlchemyCompilable,
    ConstraintsContext, ConstraintsCompilable,
)
from emergent.wire.axis.query._expr import (
    Expr,
    Field,
    Const,
    Eq,
    Ne,
    Lt,
    Le,
    Gt,
    Ge,
    And,
    Or,
    Not,
    In,
    Contains,
    StartsWith,
    EndsWith,
    IsNull,
    IsNotNull,
    Between,
    Like,
    ILike,
    Regex,
    JsonExtract,
    JsonContains,
    JsonHasKey,
    ArrayContains,
    ArrayAny,
    ArrayAll,
    ArrayOverlap,
)
from emergent.wire.axis.query._proxy import EntityProxy, build_expr


T = TypeVar("T")


# ═══════════════════════════════════════════════════════════════════════════════
# Type Mapping
# ═══════════════════════════════════════════════════════════════════════════════


def _python_type_to_sqlalchemy(
    py_type: type[Any],
    max_length: int | None = None,
    type_override: Any = None,
) -> Any:
    """Map Python type to SQLAlchemy column type.

    Pure function — reads pre-computed values from fold results,
    never raw capabilities.
    """
    if type_override is not None:
        return Text

    if py_type is int:
        return Integer
    elif py_type is float:
        return Float
    elif py_type is bool:
        return Boolean
    elif py_type is str:
        if max_length:
            return String(max_length)
        return String(255)  # Default string length
    elif py_type is datetime:
        return DateTime
    else:
        return Text


def _get_identity_field(fields: dict[str, FieldInfo]) -> str | None:
    """Find field marked with Identity capability via fold."""
    for name, info in fields.items():
        ctx = fold_field(
            info,
            ConstraintsContext(field_name=name, field_type=info.base_type),
            ConstraintsCompilable,
            "compile_constraints",
        )
        if ctx.is_identity:
            return name
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# Model Compiler
# ═══════════════════════════════════════════════════════════════════════════════


class _GeneratedBase(DeclarativeBase):
    """Base class for generated models."""
    pass


def compile_model(
    entity: type[T],
    tablename: str,
    base: type[DeclarativeBase] | None = None,
    schema: str | None = None,
) -> type[Any]:
    """Compile dataclass with schema annotations to SQLAlchemy model.

    Reads capabilities from entity fields:
    - Identity → primary_key=True
    - Unique → unique=True
    - MaxLen(n) → String(n)
    - Ref(Target) → ForeignKey
    - sql.Index(...) → Index
    - sql.ServerDefault(...) → server_default
    - sql.PrimaryKey → primary_key=True
    - sql.ForeignKey(...) → ForeignKey

    Args:
        entity: Dataclass with Annotated fields
        tablename: SQL table name
        base: SQLAlchemy declarative base (default: auto-created)
        schema: Database schema (optional)

    Returns:
        SQLAlchemy model class
    """
    if not dataclasses.is_dataclass(entity):
        raise TypeError(f"{entity} must be a dataclass")

    # Use provided base or create new one
    model_base = base or _GeneratedBase

    # Check if table already exists in this base's metadata — reuse it
    if tablename in model_base.metadata.tables:
        # Find existing model class for this table
        for mapper in model_base.registry.mappers:
            if hasattr(mapper.class_, '__tablename__') and mapper.class_.__tablename__ == tablename:
                return mapper.class_

    # Inspect entity fields
    fields = inspect_dataclass(entity)
    identity_field = _get_identity_field(fields)

    # Build column definitions
    columns: dict[str, Any] = {
        "__tablename__": tablename,
    }

    if schema:
        columns["__table_args__"] = {"schema": schema}

    for name, info in fields.items():
        # Fold constraints (for max_length, identity, etc.)
        constraints_ctx = fold_field(
            info,
            ConstraintsContext(field_name=name, field_type=info.base_type),
            ConstraintsCompilable,
            "compile_constraints",
        )

        # Fold all capabilities → SQLAlchemyContext
        sa_ctx = fold_field(
            info,
            SQLAlchemyContext(field_name=name, field_type=info.base_type),
            SQLAlchemyCompilable,
            "compile_sqlalchemy",
        )

        # Determine column type from fold results (no raw capability reads)
        col_type = _python_type_to_sqlalchemy(
            info.base_type,
            max_length=constraints_ctx.max_length,
            type_override=sa_ctx.column_kwargs.get("type_"),
        )

        # Extract column kwargs from fold result
        col_kwargs: dict[str, Any] = dict(sa_ctx.column_kwargs)
        col_kwargs.setdefault("nullable", info.is_optional)

        # Extract FK config → SA ForeignKey instance
        fk_target = col_kwargs.pop("fk_target", None)
        fk_ondelete = col_kwargs.pop("fk_ondelete", None)
        fk_onupdate = col_kwargs.pop("fk_onupdate", None)

        fk_instance: ForeignKey | None = None
        if fk_target is not None:
            fk_instance = ForeignKey(
                fk_target,
                ondelete=fk_ondelete or "CASCADE",
                onupdate=fk_onupdate or "CASCADE",
            )

        # Create column
        if fk_instance is not None:
            columns[name] = Column(col_type, fk_instance, **col_kwargs)
        else:
            columns[name] = Column(col_type, **col_kwargs)

    # Create model class dynamically
    model_name = f"{entity.__name__}Model"
    model_class: type[Any] = type(model_name, (model_base,), columns)

    # Store reference to original entity for mapping
    model_class._entity_class = entity  # type: ignore[attr-defined]
    model_class._identity_field = identity_field  # type: ignore[attr-defined]

    return model_class


# ═══════════════════════════════════════════════════════════════════════════════
# Expression Compiler
# ═══════════════════════════════════════════════════════════════════════════════


def compile_expr(expr: Expr, model: type[Any], *extra_models: type[Any]) -> Any:
    """Compile query Expr to SQLAlchemy column expression.

    For join ON clauses, pass the join model as extra_models so fields
    from both sides resolve correctly.
    """
    match expr:
        case Field(name=name):
            if hasattr(model, name):
                return getattr(model, name)
            for m in extra_models:
                if hasattr(m, name):
                    return getattr(m, name)
            return getattr(model, name)  # raises AttributeError

        case Const():
            return cast(Any, expr).value

        case Eq(left=left, right=right):
            return compile_expr(left, model, *extra_models) == compile_expr(right, model, *extra_models)

        case Ne(left=left, right=right):
            return compile_expr(left, model, *extra_models) != compile_expr(right, model, *extra_models)

        case Lt(left=left, right=right):
            return compile_expr(left, model, *extra_models) < compile_expr(right, model, *extra_models)

        case Le(left=left, right=right):
            return compile_expr(left, model, *extra_models) <= compile_expr(right, model, *extra_models)

        case Gt(left=left, right=right):
            return compile_expr(left, model, *extra_models) > compile_expr(right, model, *extra_models)

        case Ge(left=left, right=right):
            return compile_expr(left, model, *extra_models) >= compile_expr(right, model, *extra_models)

        case And(left=left, right=right):
            from sqlalchemy import and_
            return and_(compile_expr(left, model, *extra_models), compile_expr(right, model, *extra_models))

        case Or(left=left, right=right):
            from sqlalchemy import or_
            return or_(compile_expr(left, model, *extra_models), compile_expr(right, model, *extra_models))

        case Not(operand=operand):
            from sqlalchemy import not_
            return not_(compile_expr(operand, model, *extra_models))

        case In(field=field, values=values):
            return compile_expr(field, model, *extra_models).in_(values)

        case Contains(field=field, substring=substring):
            return compile_expr(field, model, *extra_models).contains(substring)

        case StartsWith(field=field, prefix=prefix):
            return compile_expr(field, model, *extra_models).startswith(prefix)

        case EndsWith(field=field, suffix=suffix):
            return compile_expr(field, model, *extra_models).endswith(suffix)

        case IsNull(field=field):
            return compile_expr(field, model, *extra_models).is_(None)

        case IsNotNull(field=field):
            return compile_expr(field, model, *extra_models).isnot(None)

        case Between(field=field, low=low, high=high):
            return compile_expr(field, model, *extra_models).between(
                compile_expr(low, model, *extra_models), compile_expr(high, model, *extra_models)
            )

        case Like(field=field, pattern=pattern):
            return compile_expr(field, model, *extra_models).like(pattern)

        case ILike(field=field, pattern=pattern):
            return compile_expr(field, model, *extra_models).ilike(pattern)

        case Regex(field=field, pattern=pattern):
            return compile_expr(field, model, *extra_models).regexp_match(pattern)

        case JsonExtract(field=field, path=path):
            col = compile_expr(field, model, *extra_models)
            for key in path.split("."):
                col = col[key]
            return col

        case JsonContains(field=field, value=value):
            return compile_expr(field, model, *extra_models).contains(value)

        case JsonHasKey(field=field, key=key):
            return compile_expr(field, model, *extra_models).has_key(key)

        case ArrayContains(field=field, value=value):
            return compile_expr(field, model, *extra_models).contains([value])

        case ArrayAny(field=field, values=values):
            return compile_expr(field, model, *extra_models).overlap(list(values))

        case ArrayAll(field=field, values=values):
            return compile_expr(field, model, *extra_models).contains(list(values))

        case ArrayOverlap(field=field, values=values):
            return compile_expr(field, model, *extra_models).overlap(list(values))

        case _:
            raise TypeError(f"Unsupported expression type: {type(expr)}")


# ═══════════════════════════════════════════════════════════════════════════════
# Entity <-> Model Mapping
# ═══════════════════════════════════════════════════════════════════════════════


def entity_to_model(entity: object, model_class: type[Any]) -> Any:
    """Convert dataclass entity to SQLAlchemy model instance."""
    if not dataclasses.is_dataclass(entity):
        raise TypeError(f"{entity} must be a dataclass instance")

    data = dataclasses.asdict(entity)  # type: ignore[arg-type]
    return model_class(**data)


def model_to_entity(model: Any, entity_class: type[T]) -> T:
    """Convert SQLAlchemy model instance to dataclass entity."""
    if not dataclasses.is_dataclass(entity_class):
        raise TypeError(f"{entity_class} must be a dataclass")

    # Get field names from entity class
    field_names = [f.name for f in dataclasses.fields(entity_class)]

    # Extract values from model
    data = {name: getattr(model, name) for name in field_names}

    return entity_class(**data)


# ═══════════════════════════════════════════════════════════════════════════════
# Storage Error
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class StorageError:
    """Storage operation error."""
    message: str
    cause: Exception | None = None


# ═══════════════════════════════════════════════════════════════════════════════
# SQLAlchemy Storage Backend
# ═══════════════════════════════════════════════════════════════════════════════


class SQLAlchemyStorage(Generic[T]):
    """SQLAlchemy storage backend with auto-generated model.

    IMPORTANT: Does NOT own transactions. Receives session, does NOT commit.
    Caller is responsible for transaction boundaries.

    Provides:
    - KV-style access by primary key: get, set, delete
    - Relational queries: find, find_one, count, exists

    Usage:
        async with session_factory() as session:
            users = SQLAlchemyStorage(
                session,
                entity=User,
                tablename="users",
            )

            # KV operations
            await users.set(user)
            user = await users.get(123)
            await users.delete(123)

            # Queries
            active = await users.find(lambda u: u.balance > 0)

            await session.commit()  # Caller commits!
    """

    __slots__ = ("_session", "_entity", "_model", "_identity_field")

    _session: AsyncSession
    _entity: type[T]
    _model: type[Any]
    _identity_field: str | None

    def __init__(
        self,
        session: AsyncSession,
        entity: type[T],
        tablename: str,
        base: type[DeclarativeBase] | None = None,
        schema: str | None = None,
    ) -> None:
        """
        Args:
            session: SQLAlchemy async session (caller owns it)
            entity: Dataclass with schema annotations
            tablename: SQL table name
            base: SQLAlchemy declarative base (optional)
            schema: Database schema (optional)
        """
        self._session = session
        self._entity = entity
        self._model = compile_model(entity, tablename, base, schema)
        self._identity_field = self._model._identity_field  # type: ignore[attr-defined]

    @property
    def entity(self) -> type[T]:
        """Entity dataclass type."""
        return self._entity

    @property
    def model(self) -> type[Any]:
        """Generated SQLAlchemy model class."""
        return self._model

    # ─── KV Operations (by primary key) ───────────────────────────────────────

    async def get(self, key: Any) -> Result[Option[T], StorageError]:
        """Get entity by primary key."""
        if self._identity_field is None:
            return Error(StorageError("No Identity field defined"))

        try:
            stmt = select(self._model).where(
                getattr(self._model, self._identity_field) == key
            )
            result = await self._session.execute(stmt)
            row = result.scalar_one_or_none()

            if row is None:
                return Ok(Nothing())

            return Ok(Some(model_to_entity(row, self._entity)))

        except Exception as e:
            return Error(StorageError(f"Failed to get: {e}", e))

    async def set(self, entity: T) -> Result[T, StorageError]:
        """Insert or update entity (upsert by primary key)."""
        try:
            model_instance = entity_to_model(entity, self._model)
            merged = await self._session.merge(model_instance)
            await self._session.flush()
            return Ok(model_to_entity(merged, self._entity))

        except Exception as e:
            return Error(StorageError(f"Failed to set: {e}", e))

    async def delete(self, key: Any) -> Result[bool, StorageError]:
        """Delete entity by primary key. Returns True if existed."""
        if self._identity_field is None:
            return Error(StorageError("No Identity field defined"))

        try:
            stmt = select(self._model).where(
                getattr(self._model, self._identity_field) == key
            )
            result = await self._session.execute(stmt)
            row = result.scalar_one_or_none()

            if row is None:
                return Ok(False)

            await self._session.delete(row)
            return Ok(True)

        except Exception as e:
            return Error(StorageError(f"Failed to delete: {e}", e))

    async def exists(self, key: Any) -> Result[bool, StorageError]:
        """Check if entity exists by primary key."""
        if self._identity_field is None:
            return Error(StorageError("No Identity field defined"))

        try:
            stmt = select(func.count()).select_from(self._model).where(
                getattr(self._model, self._identity_field) == key
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
            expr = build_expr(self._entity, predicate)
            where_clause = compile_expr(expr, self._model)

            stmt = select(self._model).where(where_clause)
            result = await self._session.execute(stmt)
            rows = result.scalars().all()

            entities = [model_to_entity(row, self._entity) for row in rows]
            return Ok(entities)

        except Exception as e:
            return Error(StorageError(f"Failed to find: {e}", e))

    async def find_one(
        self,
        predicate: Callable[[EntityProxy[T]], Expr],
    ) -> Result[Option[T], StorageError]:
        """Find single entity matching predicate."""
        try:
            expr = build_expr(self._entity, predicate)
            where_clause = compile_expr(expr, self._model)

            stmt = select(self._model).where(where_clause).limit(1)
            result = await self._session.execute(stmt)
            row = result.scalar_one_or_none()

            if row is None:
                return Ok(Nothing())

            return Ok(Some(model_to_entity(row, self._entity)))

        except Exception as e:
            return Error(StorageError(f"Failed to find_one: {e}", e))

    async def count(
        self,
        predicate: Callable[[EntityProxy[T]], Expr] | None = None,
    ) -> Result[int, StorageError]:
        """Count entities, optionally filtered."""
        try:
            stmt = select(func.count()).select_from(self._model)

            if predicate is not None:
                expr = build_expr(self._entity, predicate)
                where_clause = compile_expr(expr, self._model)
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
            expr = build_expr(self._entity, predicate)
            where_clause = compile_expr(expr, self._model)

            stmt = delete(self._model).where(where_clause)
            cursor = cast(CursorResult[Any], await self._session.execute(stmt))
            return Ok(cursor.rowcount)

        except Exception as e:
            return Error(StorageError(f"Failed to delete_where: {e}", e))

    # ─── Bulk Operations ──────────────────────────────────────────────────────

    async def set_many(self, entities: list[T]) -> Result[list[T], StorageError]:
        """Insert or update multiple entities."""
        try:
            results: list[T] = []
            for ent in entities:
                model_instance = entity_to_model(ent, self._model)
                merged = await self._session.merge(model_instance)
                results.append(model_to_entity(merged, self._entity))
            await self._session.flush()
            return Ok(results)

        except Exception as e:
            return Error(StorageError(f"Failed to set_many: {e}", e))

    async def all(self) -> Result[list[T], StorageError]:
        """Get all entities."""
        try:
            stmt = select(self._model)
            result = await self._session.execute(stmt)
            rows = result.scalars().all()
            entities = [model_to_entity(row, self._entity) for row in rows]
            return Ok(entities)

        except Exception as e:
            return Error(StorageError(f"Failed to get all: {e}", e))


# ═══════════════════════════════════════════════════════════════════════════════
# Factory Function
# ═══════════════════════════════════════════════════════════════════════════════


def sqlalchemy(
    session: AsyncSession,
    entity: type[T],
    tablename: str,
    base: type[DeclarativeBase] | None = None,
    schema: str | None = None,
) -> SQLAlchemyStorage[T]:
    """Create SQLAlchemy storage for entity.

    Generates SQLAlchemy model from entity schema annotations.

    Args:
        session: SQLAlchemy async session
        entity: Dataclass with Annotated fields
        tablename: SQL table name
        base: SQLAlchemy declarative base (optional)
        schema: Database schema (optional)

    Returns:
        SQLAlchemyStorage instance

    Example:
        @dataclass
        class User:
            id: Annotated[int, Identity]
            email: Annotated[str, Unique, MaxLen(255)]

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


# ═══════════════════════════════════════════════════════════════════════════════
# Store Pattern — separates configuration from session
# ═══════════════════════════════════════════════════════════════════════════════


class SQLAlchemyStore(Generic[T]):
    """Store factory — configure once, use with any session.

    Separates storage configuration from session lifecycle.
    Model is compiled once at store creation.

    Usage:
        # Configure once (at app startup)
        UserStore = SQLAlchemyStore(User, "users")

        # Use with any session
        async with session_factory() as session:
            users = UserStore.bind(session)
            await users.set(user)
            await session.commit()

        # Or use context manager
        async with session_factory() as session:
            async with UserStore.session(session) as users:
                await users.set(user)
            # auto-flush on exit (no commit)
    """

    __slots__ = ("_entity", "_tablename", "_base", "_schema", "_model", "_identity_field")

    _entity: type[T]
    _tablename: str
    _base: type[DeclarativeBase] | None
    _schema: str | None
    _model: type[Any]
    _identity_field: str | None

    def __init__(
        self,
        entity: type[T],
        tablename: str,
        base: type[DeclarativeBase] | None = None,
        schema: str | None = None,
    ) -> None:
        """
        Args:
            entity: Dataclass with schema annotations
            tablename: SQL table name
            base: SQLAlchemy declarative base (optional)
            schema: Database schema (optional)
        """
        self._entity = entity
        self._tablename = tablename
        self._base = base
        self._schema = schema
        # Compile model once
        self._model = compile_model(entity, tablename, base, schema)
        self._identity_field = self._model._identity_field  # type: ignore[attr-defined]

    @property
    def entity(self) -> type[T]:
        """Entity dataclass type."""
        return self._entity

    @property
    def model(self) -> type[Any]:
        """Generated SQLAlchemy model class."""
        return self._model

    @property
    def tablename(self) -> str:
        """SQL table name."""
        return self._tablename

    def bind(self, session: AsyncSession) -> BoundSQLAlchemyStore[T]:
        """Bind store to session.

        Returns a BoundSQLAlchemyStore with all storage operations.

        Usage:
            async with session_factory() as session:
                users = UserStore.bind(session)
                await users.set(user)
                await session.commit()
        """
        return BoundSQLAlchemyStore(
            session=session,
            entity=self._entity,
            model=self._model,
            identity_field=self._identity_field,
        )

    def __call__(self, session: AsyncSession) -> BoundSQLAlchemyStore[T]:
        """Shortcut for bind(session).

        Usage:
            users = UserStore(session)
        """
        return self.bind(session)


class BoundSQLAlchemyStore(Generic[T]):
    """Store bound to a session — provides all storage operations.

    Created by SQLAlchemyStore.bind(session).

    IMPORTANT: Does NOT own transactions. Caller commits.
    """

    __slots__ = ("_session", "_entity", "_model", "_identity_field")

    _session: AsyncSession
    _entity: type[T]
    _model: type[Any]
    _identity_field: str | None

    def __init__(
        self,
        session: AsyncSession,
        entity: type[T],
        model: type[Any],
        identity_field: str | None,
    ) -> None:
        self._session = session
        self._entity = entity
        self._model = model
        self._identity_field = identity_field

    @property
    def entity(self) -> type[T]:
        """Entity dataclass type."""
        return self._entity

    @property
    def model(self) -> type[Any]:
        """SQLAlchemy model class."""
        return self._model

    # ─── KV Operations ────────────────────────────────────────────────────────

    async def get(self, key: Any) -> Result[Option[T], StorageError]:
        """Get entity by primary key."""
        if self._identity_field is None:
            return Error(StorageError("No Identity field defined"))

        try:
            stmt = select(self._model).where(
                getattr(self._model, self._identity_field) == key
            )
            result = await self._session.execute(stmt)
            row = result.scalar_one_or_none()

            if row is None:
                return Ok(Nothing())

            return Ok(Some(model_to_entity(row, self._entity)))

        except Exception as e:
            return Error(StorageError(f"Failed to get: {e}", e))

    async def set(self, entity: T) -> Result[T, StorageError]:
        """Insert or update entity (upsert by primary key)."""
        try:
            model_instance = entity_to_model(entity, self._model)
            merged = await self._session.merge(model_instance)
            await self._session.flush()
            return Ok(model_to_entity(merged, self._entity))

        except Exception as e:
            return Error(StorageError(f"Failed to set: {e}", e))

    async def delete(self, key: Any) -> Result[bool, StorageError]:
        """Delete entity by primary key. Returns True if existed."""
        if self._identity_field is None:
            return Error(StorageError("No Identity field defined"))

        try:
            stmt = select(self._model).where(
                getattr(self._model, self._identity_field) == key
            )
            result = await self._session.execute(stmt)
            row = result.scalar_one_or_none()

            if row is None:
                return Ok(False)

            await self._session.delete(row)
            return Ok(True)

        except Exception as e:
            return Error(StorageError(f"Failed to delete: {e}", e))

    async def exists(self, key: Any) -> Result[bool, StorageError]:
        """Check if entity exists by primary key."""
        if self._identity_field is None:
            return Error(StorageError("No Identity field defined"))

        try:
            stmt = select(func.count()).select_from(self._model).where(
                getattr(self._model, self._identity_field) == key
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
            expr = build_expr(self._entity, predicate)
            where_clause = compile_expr(expr, self._model)

            stmt = select(self._model).where(where_clause)
            result = await self._session.execute(stmt)
            rows = result.scalars().all()

            entities = [model_to_entity(row, self._entity) for row in rows]
            return Ok(entities)

        except Exception as e:
            return Error(StorageError(f"Failed to find: {e}", e))

    async def find_one(
        self,
        predicate: Callable[[EntityProxy[T]], Expr],
    ) -> Result[Option[T], StorageError]:
        """Find single entity matching predicate."""
        try:
            expr = build_expr(self._entity, predicate)
            where_clause = compile_expr(expr, self._model)

            stmt = select(self._model).where(where_clause).limit(1)
            result = await self._session.execute(stmt)
            row = result.scalar_one_or_none()

            if row is None:
                return Ok(Nothing())

            return Ok(Some(model_to_entity(row, self._entity)))

        except Exception as e:
            return Error(StorageError(f"Failed to find_one: {e}", e))

    async def count(
        self,
        predicate: Callable[[EntityProxy[T]], Expr] | None = None,
    ) -> Result[int, StorageError]:
        """Count entities, optionally filtered."""
        try:
            stmt = select(func.count()).select_from(self._model)

            if predicate is not None:
                expr = build_expr(self._entity, predicate)
                where_clause = compile_expr(expr, self._model)
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
            expr = build_expr(self._entity, predicate)
            where_clause = compile_expr(expr, self._model)

            stmt = delete(self._model).where(where_clause)
            cursor = cast(CursorResult[Any], await self._session.execute(stmt))
            return Ok(cursor.rowcount)

        except Exception as e:
            return Error(StorageError(f"Failed to delete_where: {e}", e))

    # ─── Bulk Operations ──────────────────────────────────────────────────────

    async def set_many(self, entities: list[T]) -> Result[list[T], StorageError]:
        """Insert or update multiple entities."""
        try:
            results: list[T] = []
            for ent in entities:
                model_instance = entity_to_model(ent, self._model)
                merged = await self._session.merge(model_instance)
                results.append(model_to_entity(merged, self._entity))
            await self._session.flush()
            return Ok(results)

        except Exception as e:
            return Error(StorageError(f"Failed to set_many: {e}", e))

    async def all(self) -> Result[list[T], StorageError]:
        """Get all entities."""
        try:
            stmt = select(self._model)
            result = await self._session.execute(stmt)
            rows = result.scalars().all()
            entities = [model_to_entity(row, self._entity) for row in rows]
            return Ok(entities)

        except Exception as e:
            return Error(StorageError(f"Failed to get all: {e}", e))


def store(
    entity: type[T],
    tablename: str,
    base: type[DeclarativeBase] | None = None,
    schema: str | None = None,
) -> SQLAlchemyStore[T]:
    """Create SQLAlchemy store factory.

    Store separates configuration from session — configure once, use with any session.
    Model is compiled once at creation.

    Args:
        entity: Dataclass with Annotated fields
        tablename: SQL table name
        base: SQLAlchemy declarative base (optional)
        schema: Database schema (optional)

    Returns:
        SQLAlchemyStore factory

    Example:
        # Configure once (at app startup)
        from emergent.wire.axis.storage.contrib import sqlalchemy

        UserStore = sqlalchemy.store(User, "users")

        # Use with any session
        async with session_factory() as session:
            users = UserStore(session)  # or UserStore.bind(session)

            await users.set(User(id=1, email="alice@example.com"))
            user = await users.get(1)

            await session.commit()
    """
    return SQLAlchemyStore(
        entity=entity,
        tablename=tablename,
        base=base,
        schema=schema,
    )


__all__ = (
    # Model compiler
    "compile_model",
    # Expression compiler
    "compile_expr",
    # Mapping
    "entity_to_model",
    "model_to_entity",
    # Storage (inline)
    "StorageError",
    "SQLAlchemyStorage",
    "sqlalchemy",
    # Store (factory pattern)
    "SQLAlchemyStore",
    "BoundSQLAlchemyStore",
    "store",
)

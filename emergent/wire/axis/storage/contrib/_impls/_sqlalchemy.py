"""SQLAlchemy storage backend — unified storage with model generation.

IMPORTANT: Backend does NOT own transactions. Caller provides session, caller commits.

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

import dataclasses
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

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

from kungfu import Result, Ok, Error, Option, Some, Nothing

from emergent.wire.axis.schema._inspect import inspect_dataclass, FieldInfo
from emergent.wire.axis._capability import (
    SQLAlchemyContext, SQLAlchemyCompilable,
    ConstraintsContext, ConstraintsCompilable,
    CoercionContext, CoercionCompilable,
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

if TYPE_CHECKING:
    from sqlalchemy.engine import CursorResult


# ═══════════════════════════════════════════════════════════════════════════════
# Type Mapping
# ═══════════════════════════════════════════════════════════════════════════════


def _default_column_type(
    py_type: type,
    max_length: int | None = None,
) -> type:
    """Map Python type to SQLAlchemy column type.

    Pure function — no post-fold fallback. Used to set initial SA context
    from coercion-aware base type.
    """
    if py_type is int:
        return Integer
    if py_type is float:
        return Float
    if py_type is bool:
        return Boolean
    if py_type is str:
        if max_length:
            return String(max_length)  # type: ignore[return-value]
        return Text
    if py_type is datetime:
        return DateTime
    return Text


def _get_identity_field(fields: Mapping[str, FieldInfo]) -> str | None:
    """Find field marked with Identity capability via fold."""
    from emergent.wire.compile._core import fold_field

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


# Type alias for the coercion map stored on compiled models
type _CoercionMap = dict[str, tuple[Callable[[object], object], Callable[[object], object]]]


def compile_model[T](
    entity: type[T],
    tablename: str,
    base: type[DeclarativeBase] | None = None,
    schema: str | None = None,
) -> type[DeclarativeBase]:
    """Compile dataclass with schema annotations to SQLAlchemy model.

    Three-fold compilation per field:
    1. Constraints fold — max_length, identity, unique, etc.
    2. Coercion fold — storage_type + to/from callables (Coerce, custom CoercionCompilable)
    3. SA fold — column_type (initial from coercion-aware base), column_kwargs (PK, FK, nullable, etc.)

    Returns:
        SQLAlchemy model class with _field_coercion and _identity_field attrs.
    """
    from emergent.wire.compile._core import fold_field

    if not dataclasses.is_dataclass(entity):
        raise TypeError(f"{entity} must be a dataclass")

    model_base = base or _GeneratedBase

    # Reuse existing model if table already compiled
    if tablename in model_base.metadata.tables:
        for mapper in model_base.registry.mappers:
            if hasattr(mapper.class_, '__tablename__') and mapper.class_.__tablename__ == tablename:
                return mapper.class_

    fields = inspect_dataclass(entity)
    identity_field = _get_identity_field(fields)

    # Build column definitions + coercion map
    attrs: dict[str, Column[object] | str | dict[str, str]] = {
        "__tablename__": tablename,  # type: ignore[dict-item]
    }

    if schema:
        attrs["__table_args__"] = {"schema": schema}  # type: ignore[assignment]

    field_coercion: _CoercionMap = {}

    for name, info in fields.items():
        # FOLD 1: Constraints (max_length, identity, etc.)
        constraints_ctx = fold_field(
            info,
            ConstraintsContext(field_name=name, field_type=info.base_type),
            ConstraintsCompilable,
            "compile_constraints",
        )

        # FOLD 2: Coercion (BEFORE SA — provides storage_type)
        coercion_ctx = fold_field(
            info,
            CoercionContext(field_name=name, field_type=info.base_type),
            CoercionCompilable,
            "compile_coercion",
        )
        if coercion_ctx.to_storage is not None and coercion_ctx.from_storage is not None:
            field_coercion[name] = (coercion_ctx.to_storage, coercion_ctx.from_storage)

        # Use storage_type from coercion (if Coerce present) → correct base for column type
        base_type = coercion_ctx.storage_type if coercion_ctx.storage_type is not None else info.base_type

        # FOLD 3: SA context — initial column_type derived from coercion-aware base_type
        sa_ctx = fold_field(
            info,
            SQLAlchemyContext(
                field_name=name,
                field_type=info.base_type,
                column_type=_default_column_type(base_type, max_length=constraints_ctx.max_length),
            ),
            SQLAlchemyCompilable,
            "compile_sqlalchemy",
        )

        # column_type is now fully resolved — either from default, Coerce's storage_type, or SA capabilities
        col_type = sa_ctx.column_type

        # Column kwargs
        col_kwargs: dict[str, str | int | bool | None] = dict(sa_ctx.column_kwargs)

        col_kwargs.setdefault("nullable", info.is_optional)

        # Extract FK config
        fk_target = col_kwargs.pop("fk_target", None)
        fk_ondelete = col_kwargs.pop("fk_ondelete", None)
        fk_onupdate = col_kwargs.pop("fk_onupdate", None)

        fk_instance: ForeignKey | None = None
        if fk_target is not None:
            fk_instance = ForeignKey(
                fk_target,
                ondelete=str(fk_ondelete or "CASCADE"),
                onupdate=str(fk_onupdate or "CASCADE"),
            )

        if fk_instance is not None:
            attrs[name] = Column(col_type, fk_instance, **col_kwargs)  # type: ignore[arg-type]
        else:
            attrs[name] = Column(col_type, **col_kwargs)  # type: ignore[arg-type]

    # Create model class
    model_name = f"{entity.__name__}Model"
    model_class = type(model_name, (model_base,), attrs)

    # Attach metadata used by entity<->model mapping
    model_class._entity_class = entity  # type: ignore[attr-defined]
    model_class._identity_field = identity_field  # type: ignore[attr-defined]
    model_class._field_coercion = field_coercion  # type: ignore[attr-defined]

    return model_class  # type: ignore[return-value]


# ═══════════════════════════════════════════════════════════════════════════════
# Expression Compiler
# ═══════════════════════════════════════════════════════════════════════════════


def compile_expr(expr: Expr, model: type[DeclarativeBase], *extra_models: type[DeclarativeBase]) -> object:
    """Compile query Expr to SQLAlchemy column expression."""
    match expr:
        case Field(name=name):
            if hasattr(model, name):
                return getattr(model, name)
            for m in extra_models:
                if hasattr(m, name):
                    return getattr(m, name)
            return getattr(model, name)  # raises AttributeError

        case Const(value=value):
            return value

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
            return compile_expr(field, model, *extra_models).in_(values)  # type: ignore[union-attr]

        case Contains(field=field, substring=substring):
            return compile_expr(field, model, *extra_models).contains(substring)  # type: ignore[union-attr]

        case StartsWith(field=field, prefix=prefix):
            return compile_expr(field, model, *extra_models).startswith(prefix)  # type: ignore[union-attr]

        case EndsWith(field=field, suffix=suffix):
            return compile_expr(field, model, *extra_models).endswith(suffix)  # type: ignore[union-attr]

        case IsNull(field=field):
            return compile_expr(field, model, *extra_models).is_(None)  # type: ignore[union-attr]

        case IsNotNull(field=field):
            return compile_expr(field, model, *extra_models).isnot(None)  # type: ignore[union-attr]

        case Between(field=field, low=low, high=high):
            return compile_expr(field, model, *extra_models).between(  # type: ignore[union-attr]
                compile_expr(low, model, *extra_models), compile_expr(high, model, *extra_models)
            )

        case Like(field=field, pattern=pattern):
            return compile_expr(field, model, *extra_models).like(pattern)  # type: ignore[union-attr]

        case ILike(field=field, pattern=pattern):
            return compile_expr(field, model, *extra_models).ilike(pattern)  # type: ignore[union-attr]

        case Regex(field=field, pattern=pattern):
            return compile_expr(field, model, *extra_models).regexp_match(pattern)  # type: ignore[union-attr]

        case JsonExtract(field=field, path=path):
            col = compile_expr(field, model, *extra_models)
            for key in path.split("."):
                col = col[key]  # type: ignore[index]
            return col

        case JsonContains(field=field, value=value):
            return compile_expr(field, model, *extra_models).contains(value)  # type: ignore[union-attr]

        case JsonHasKey(field=field, key=key):
            return compile_expr(field, model, *extra_models).has_key(key)  # type: ignore[union-attr]

        case ArrayContains(field=field, value=value):
            return compile_expr(field, model, *extra_models).contains([value])  # type: ignore[union-attr]

        case ArrayAny(field=field, values=values):
            return compile_expr(field, model, *extra_models).overlap(list(values))  # type: ignore[union-attr]

        case ArrayAll(field=field, values=values):
            return compile_expr(field, model, *extra_models).contains(list(values))  # type: ignore[union-attr]

        case ArrayOverlap(field=field, values=values):
            return compile_expr(field, model, *extra_models).overlap(list(values))  # type: ignore[union-attr]

        case _:
            raise TypeError(f"Unsupported expression type: {type(expr)}")


# ═══════════════════════════════════════════════════════════════════════════════
# Entity <-> Model Mapping
# ═══════════════════════════════════════════════════════════════════════════════


def entity_to_model[T](entity: T, model_class: type[DeclarativeBase]) -> DeclarativeBase:
    """Convert dataclass entity to SQLAlchemy model instance.

    Applies to_storage coercion from _field_coercion map.
    """
    if not dataclasses.is_dataclass(entity):
        raise TypeError(f"{entity} must be a dataclass instance")

    coercion: _CoercionMap = getattr(model_class, "_field_coercion", {})
    data: dict[str, object] = {}

    for f in dataclasses.fields(entity):  # type: ignore[arg-type]
        value = getattr(entity, f.name)
        to_storage_fn = coercion.get(f.name)
        if to_storage_fn is not None:
            value = to_storage_fn[0](value)
        data[f.name] = value

    return model_class(**data)


def model_to_entity[T](model: DeclarativeBase, entity_class: type[T]) -> T:
    """Convert SQLAlchemy model instance to dataclass entity.

    Applies from_storage coercion from _field_coercion map.
    """
    if not dataclasses.is_dataclass(entity_class):
        raise TypeError(f"{entity_class} must be a dataclass")

    model_class = type(model)
    coercion: _CoercionMap = getattr(model_class, "_field_coercion", {})
    fields = inspect_dataclass(entity_class)
    data: dict[str, object] = {}

    for name in fields:
        value = getattr(model, name)
        from_storage_fn = coercion.get(name)
        if from_storage_fn is not None:
            value = from_storage_fn[1](value)
        data[name] = value

    return entity_class(**data)


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
    Model is compiled once at store creation.

    Usage:
        # Configure once (at app startup)
        UserStore = SQLAlchemyStore(User, "users")

        # Use with any session
        async with session_factory() as session:
            users = UserStore(session)
            await users.set(user)
            await session.commit()
    """

    __slots__ = ("_entity", "_tablename", "_base", "_schema", "_model", "_identity_field")

    _entity: type[T]
    _tablename: str
    _base: type[DeclarativeBase] | None
    _schema: str | None
    _model: type[DeclarativeBase]
    _identity_field: str | None

    def __init__(
        self,
        entity: type[T],
        tablename: str,
        base: type[DeclarativeBase] | None = None,
        schema: str | None = None,
    ) -> None:
        self._entity = entity
        self._tablename = tablename
        self._base = base
        self._schema = schema
        self._model = compile_model(entity, tablename, base, schema)
        self._identity_field = self._model._identity_field  # type: ignore[attr-defined]

    @property
    def entity(self) -> type[T]:
        return self._entity

    @property
    def model(self) -> type[DeclarativeBase]:
        return self._model

    @property
    def tablename(self) -> str:
        return self._tablename

    def bind(self, session: AsyncSession) -> BoundSQLAlchemyStore[T]:
        """Bind store to session — returns object with all storage operations."""
        return BoundSQLAlchemyStore(
            session=session,
            entity=self._entity,
            model=self._model,
            identity_field=self._identity_field,
        )

    def __call__(self, session: AsyncSession) -> BoundSQLAlchemyStore[T]:
        """Shortcut for bind(session)."""
        return self.bind(session)


class BoundSQLAlchemyStore[T]:
    """Store bound to a session — provides all storage operations.

    Created by SQLAlchemyStore.bind(session) or SQLAlchemyStore(session).

    IMPORTANT: Does NOT own transactions. Caller commits.
    """

    __slots__ = ("_session", "_entity", "_model", "_identity_field")

    _session: AsyncSession
    _entity: type[T]
    _model: type[DeclarativeBase]
    _identity_field: str | None

    def __init__(
        self,
        session: AsyncSession,
        entity: type[T],
        model: type[DeclarativeBase],
        identity_field: str | None,
    ) -> None:
        self._session = session
        self._entity = entity
        self._model = model
        self._identity_field = identity_field

    @property
    def entity(self) -> type[T]:
        return self._entity

    @property
    def model(self) -> type[DeclarativeBase]:
        return self._model

    # ─── KV Operations ────────────────────────────────────────────────────────

    async def get(self, key: object) -> Result[Option[T], StorageError]:
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

    async def delete(self, key: object) -> Result[bool, StorageError]:
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

    async def exists(self, key: object) -> Result[bool, StorageError]:
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
        model = compile_model(entity, tablename, base, schema)
        identity_field: str | None = model._identity_field  # type: ignore[attr-defined]
        super().__init__(
            session=session,
            entity=entity,
            model=model,
            identity_field=identity_field,
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
    # Model compiler
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

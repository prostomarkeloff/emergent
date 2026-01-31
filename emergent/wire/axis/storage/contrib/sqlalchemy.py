"""SQLAlchemy storage backend.

    from emergent.wire.axis.storage.contrib import sqlalchemy

    @dataclass
    class User:
        id: Annotated[int, Identity]
        email: Annotated[str, Unique, MaxLen(255)]

    async with session_factory() as session:
        users = sqlalchemy.sqlalchemy(session, User, "users")

        await users.set(User(id=1, email="alice@example.com"))
        user = await users.get(1)

        await session.commit()

Requires: sqlalchemy[asyncio]
"""

try:
    from emergent.wire.axis.storage.contrib._impls._sqlalchemy import (
        # Model compiler
        compile_model as compile_model,
        # Expression compiler
        compile_expr as compile_expr,
        # Mapping
        entity_to_model as entity_to_model,
        model_to_entity as model_to_entity,
        # Storage (inline)
        StorageError as StorageError,
        SQLAlchemyStorage as SQLAlchemyStorage,
        sqlalchemy as sqlalchemy,
        # Store (factory pattern)
        SQLAlchemyStore as SQLAlchemyStore,
        BoundSQLAlchemyStore as BoundSQLAlchemyStore,
        store as store,
    )

    __all__ = (
        "compile_model",
        "compile_expr",
        "entity_to_model",
        "model_to_entity",
        "StorageError",
        "SQLAlchemyStorage",
        "sqlalchemy",
        "SQLAlchemyStore",
        "BoundSQLAlchemyStore",
        "store",
    )

except ImportError as e:
    _msg = f"sqlalchemy is required for SQLAlchemy storage: {e}"

    def _raise_import_error(*_args: object, **_kwargs: object) -> None:
        raise ImportError(_msg)

    # Stubs that raise on use
    compile_model = _raise_import_error  # type: ignore[assignment]
    compile_expr = _raise_import_error  # type: ignore[assignment]
    entity_to_model = _raise_import_error  # type: ignore[assignment]
    model_to_entity = _raise_import_error  # type: ignore[assignment]
    sqlalchemy = _raise_import_error  # type: ignore[assignment]

    __all__ = ("sqlalchemy",)

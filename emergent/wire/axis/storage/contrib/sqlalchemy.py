"""SQLAlchemy storage backend.

    from emergent.wire.axis.storage.contrib import sqlalchemy

    @dataclass
    class User:
        id: Annotated[int, Identity]
        email: Annotated[str, Unique, MaxLen(255)]

    UserStore = sqlalchemy.store(User, "users")

    async with session_factory() as session:
        users = UserStore(session)
        await users.set(User(id=1, email="alice@example.com"))
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
        # Storage error
        StorageError as StorageError,
        # Store (factory pattern) — primary API
        SQLAlchemyStore as SQLAlchemyStore,
        BoundSQLAlchemyStore as BoundSQLAlchemyStore,
        store as store,
        # Convenience one-liner
        sqlalchemy as sqlalchemy,
        # Backwards-compat alias
        SQLAlchemyStorage as SQLAlchemyStorage,
    )

    __all__ = (
        "compile_model",
        "compile_expr",
        "entity_to_model",
        "model_to_entity",
        "StorageError",
        "SQLAlchemyStore",
        "BoundSQLAlchemyStore",
        "store",
        "sqlalchemy",
        "SQLAlchemyStorage",
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

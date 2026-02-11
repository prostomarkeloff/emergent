"""SQLAlchemy relational provider — production database backend.

    from emergent.wire.axis.query.contrib import sqlalchemy as sa_query

    # Store factory (configure once)
    UserStore = sa_query.store(User, "users")

    # Per-request
    provider = UserStore(session)
    users = await provider.fetch_many(relational(User).filter(lambda u: u.active))
    await provider.insert(User(id=0, name="Alice"))
    await session.commit()

Requires: sqlalchemy[asyncio]
"""

try:
    from emergent.wire.axis.query.contrib._impls._sqlalchemy import (
        # Provider
        SQLAlchemyRelationalProvider as SQLAlchemyRelationalProvider,
        # Store
        SQLAlchemyRelationalStore as SQLAlchemyRelationalStore,
        # NextId strategies
        AutoIncrementNextId as AutoIncrementNextId,
        SASequenceNextId as SASequenceNextId,
        # Factory functions
        provider as provider,
        store as store,
    )

    __all__ = (
        "SQLAlchemyRelationalProvider",
        "SQLAlchemyRelationalStore",
        "AutoIncrementNextId",
        "SASequenceNextId",
        "provider",
        "store",
    )

except ImportError as e:
    _msg = f"sqlalchemy[asyncio] is required for SQLAlchemy relational provider: {e}"

    def _raise_import_error(*_args: object, **_kwargs: object) -> None:
        raise ImportError(_msg)

    provider = _raise_import_error  # type: ignore[assignment]
    store = _raise_import_error  # type: ignore[assignment]

    __all__ = ("provider", "store")

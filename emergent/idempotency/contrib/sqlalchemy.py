"""
SQLAlchemy integration for emergent.idempotency (optional dependency).

    from emergent.idempotency.contrib import sqlalchemy
    # store = sqlalchemy.SQLAlchemyStore(...)
"""

try:
    from ._impls._sqlalchemy import (
        IdempotencyMixin,
        IdempotencyStatus,
        IdempotentModel,
        SQLAlchemyStore,
    )
except ImportError:  # pragma: no cover - SQLAlchemy not installed
    pass

__all__ = (
    "IdempotencyMixin",
    "IdempotencyStatus",
    "IdempotentModel",
    "SQLAlchemyStore",
)

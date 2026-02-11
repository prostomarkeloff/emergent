"""Storage contrib backends.

    from emergent.wire.axis.storage.contrib import sqlalchemy
    from emergent.wire.axis.storage.contrib import event_store

    users = sqlalchemy.sqlalchemy(session, User, "users")

Note: Each backend is optional and requires its dependency.
"""

__all__: list[str] = []

# SQLAlchemy (optional)
try:
    from emergent.wire.axis.storage.contrib import sqlalchemy as sqlalchemy

    __all__.append("sqlalchemy")
except ImportError:
    pass

# Event Store (optional)
try:
    from emergent.wire.axis.storage.contrib import event_store as event_store

    __all__.append("event_store")
except ImportError:
    pass

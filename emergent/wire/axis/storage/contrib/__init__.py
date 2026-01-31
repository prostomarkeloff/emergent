"""Storage contrib backends.

    from emergent.wire.axis.storage.contrib import sqlalchemy

    users = sqlalchemy.sqlalchemy(session, User, "users")
"""

from emergent.wire.axis.storage.contrib import sqlalchemy

__all__ = ("sqlalchemy",)

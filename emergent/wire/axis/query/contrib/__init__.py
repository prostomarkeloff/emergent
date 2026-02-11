"""Query contrib providers.

    from emergent.wire.axis.query.contrib import http
    from emergent.wire.axis.query.contrib import sqlalchemy

Note: Each provider is optional and requires its dependency.
"""

__all__: list[str] = []

# HTTP provider (requires httpx)
try:
    from emergent.wire.axis.query.contrib import http as http

    __all__.append("http")
except ImportError:
    pass

# SQLAlchemy relational provider (requires sqlalchemy[asyncio])
try:
    from emergent.wire.axis.query.contrib import sqlalchemy as sqlalchemy

    __all__.append("sqlalchemy")
except ImportError:
    pass

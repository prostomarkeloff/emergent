"""QuerySet Spaces — query dialects.

Space defines WHAT operations are available for a query language.
Different backends speak different languages.

    RelationalSpace — filter, join, group_by, window (SQL)
    KVSpace — get, set, delete, scan (Redis, KV stores)
    DocumentSpace — filter, nested, array (MongoDB)
    APISpace — list, get, create, update, delete (REST APIs)

Space is the Semantic dimension of Query axis.
Provider is the Physical dimension.

    Space × Provider = Concrete Store
"""

from __future__ import annotations

from abc import ABC


# ─── Base Space ───────────────────────────────────────────────────────────────


class Space(ABC):
    """Base for query spaces.

    Space defines the vocabulary of operations.
    Subclasses add specific operation methods.
    """
    pass


# ─── Relational Space ─────────────────────────────────────────────────────────


class RelationalSpace(Space):
    """Relational query space — SQL-like operations.

    Operations: filter, order_by, limit, offset, select, join, group_by, having
    Providers: SQLProvider, MemoryProvider
    """
    pass


# ─── KV Space ─────────────────────────────────────────────────────────────────


class KVSpace(Space):
    """Key-Value query space — simple CRUD by key.

    Operations: get, set, delete, exists, scan
    Providers: RedisProvider, MemoryKVProvider
    """
    pass


# ─── Document Space ───────────────────────────────────────────────────────────


class DocumentSpace(KVSpace):
    """Document query space — nested queries + KV.

    Extends KV with: filter, nested, array_contains, array_any
    Providers: MongoProvider
    """
    pass


# ─── API Space ────────────────────────────────────────────────────────────────


class APISpace(Space):
    """REST API query space — CRUD over HTTP.

    Operations: list, get, create, update, delete
    Providers: HTTPProvider
    """
    pass


__all__ = (
    "Space",
    "RelationalSpace",
    "KVSpace",
    "DocumentSpace",
    "APISpace",
)

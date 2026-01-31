"""Query axis — entity-first data access via QuerySet Spaces.

Each space defines its own query language:
- RelationalSpace — filter, join, group_by (SQL-like)
- KVSpace — get, set, delete, scan (Redis-like)

Space × Provider = Store

    # Relational
    users = relational_store(User, sql_provider)
    result = await users.filter(lambda u: u.active).fetch_many()

    # KV
    cache = kv_store(User, key=lambda u: u.id, provider=redis)
    user = await cache.get("alice")

Low-level (build query, pass to provider separately):

    q = relational(User).filter(lambda u: u.balance > 0).limit(10)
    result = await provider.fetch_many(q)

High-level (store bundles query + provider):

    result = await users.filter(lambda u: u.balance > 0).limit(10).fetch_many()
"""

# Expressions
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
)

# Proxy (for building expressions from lambdas)
from emergent.wire.axis.query._proxy import (
    FieldProxy,
    OrderSpec,
    EntityProxy,
    build_expr,
    build_order,
)

# Spaces
from emergent.wire.axis.query._space import (
    Space,
    RelationalSpace,
    KVSpace,
    DocumentSpace,
    APISpace,
)

# Relational QuerySet
from emergent.wire.axis.query._relational import (
    RelationalQuerySet,
    relational,
    # Ops
    Filter,
    OrderBy,
    Limit,
    Offset,
    Select,
    Join,
    GroupBy,
    Having,
    Distinct,
)

# KV QuerySet
from emergent.wire.axis.query._kv import (
    KVQuerySet,
    kv,
    # Ops
    Get,
    Set,
    Delete,
    Exists,
    Scan,
    Keys,
)

# API QuerySet
from emergent.wire.axis.query._api import (
    APIQuerySet,
    api,
    # Ops
    ListOp,
    GetOp,
    CreateOp,
    UpdateOp,
    DeleteOp,
    APIOp,
    # Mods
    FilterMod,
    OrderMod,
    PageMod,
    CursorMod,
    OffsetMod,
    SelectMod,
    SearchMod,
    IncludeMod,
    APIMod,
)

# Providers
from emergent.wire.axis.query._provider import (
    RelationalProvider,
    MutatingRelationalProvider,
    KVProvider,
    APIProvider,
    APIListResult,
    PaginatedAPIProvider,
    JoinCapability,
    GroupByCapability,
    WindowCapability,
    TransactionCapability,
    # ID Generation
    NextId,
    UuidNextId,
    SequenceNextId,
    PrefixedNextId,
)

# Stores (bundled QuerySet + Provider)
from emergent.wire.axis.query._store import (
    RelationalStore,
    BoundRelationalQuerySet,
    relational_store,
    KVStore,
    kv_store,
)

# Memory providers
from emergent.wire.axis.query.providers import (
    MemoryRelationalProvider,
    MemoryKVProvider,
)


__all__ = (
    # Expressions
    "Expr",
    "Field",
    "Const",
    "Eq", "Ne", "Lt", "Le", "Gt", "Ge",
    "And", "Or", "Not",
    "In", "Contains", "StartsWith", "EndsWith",
    "IsNull", "IsNotNull",
    # Proxy
    "FieldProxy",
    "OrderSpec",
    "EntityProxy",
    "build_expr",
    "build_order",
    # Spaces
    "Space",
    "RelationalSpace",
    "KVSpace",
    "DocumentSpace",
    "APISpace",
    # Relational
    "RelationalQuerySet",
    "relational",
    "Filter", "OrderBy", "Limit", "Offset", "Select",
    "Join", "GroupBy", "Having", "Distinct",
    # KV
    "KVQuerySet",
    "kv",
    "Get", "Set", "Delete", "Exists", "Scan", "Keys",
    # API
    "APIQuerySet",
    "api",
    "ListOp", "GetOp", "CreateOp", "UpdateOp", "DeleteOp", "APIOp",
    "FilterMod", "OrderMod", "PageMod", "CursorMod", "OffsetMod",
    "SelectMod", "SearchMod", "IncludeMod", "APIMod",
    # Providers
    "RelationalProvider",
    "MutatingRelationalProvider",
    "KVProvider",
    "APIProvider",
    "APIListResult",
    "PaginatedAPIProvider",
    "JoinCapability",
    "GroupByCapability",
    "WindowCapability",
    "TransactionCapability",
    # ID Generation
    "NextId",
    "UuidNextId",
    "SequenceNextId",
    "PrefixedNextId",
    # Stores
    "RelationalStore",
    "BoundRelationalQuerySet",
    "relational_store",
    "KVStore",
    "kv_store",
    # Memory
    "MemoryRelationalProvider",
    "MemoryKVProvider",
)

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
    # Range
    Between,
    # Pattern matching
    Like,
    ILike,
    Regex,
    # Array operators
    ArrayContains,
    ArrayAny,
    ArrayAll,
    ArrayOverlap,
    # JSON operators
    JsonExtract,
    JsonContains,
    JsonHasKey,
)

# Proxy (for building expressions from lambdas)
from emergent.wire.axis.query._proxy import (
    FieldProxy,
    JsonFieldProxy,
    OrderSpec,
    EntityProxy,
    build_expr,
    build_order,
)

# Aggregates (typed, no strings)
from emergent.wire.axis.query._aggregate import (
    AggregateFunc,
    Count,
    Sum,
    Avg,
    Min,
    Max,
    ArrayAgg,
    StringAgg,
    AggregateExpr,
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
    AggregateSpec,
    Aggregate,
)

# KV QuerySet
from emergent.wire.axis.query._kv import (
    KVQuerySet,
    kv,
    # Ops (new names)
    KVGet,
    KVSet,
    KVDelete,
    Exists,
    Scan,
    Keys,
    # Backward compat aliases
    Get,
    Set,
    Delete,
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
    AggregateCapability,
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
    # Expressions — base
    "Expr",
    "Field",
    "Const",
    # Expressions — comparison
    "Eq", "Ne", "Lt", "Le", "Gt", "Ge",
    # Expressions — logical
    "And", "Or", "Not",
    # Expressions — collection
    "In", "Contains", "StartsWith", "EndsWith",
    # Expressions — null checks
    "IsNull", "IsNotNull",
    # Expressions — range
    "Between",
    # Expressions — pattern matching
    "Like", "ILike", "Regex",
    # Expressions — array
    "ArrayContains", "ArrayAny", "ArrayAll", "ArrayOverlap",
    # Expressions — JSON
    "JsonExtract", "JsonContains", "JsonHasKey",
    # Proxy
    "FieldProxy",
    "JsonFieldProxy",
    "OrderSpec",
    "EntityProxy",
    "build_expr",
    "build_order",
    # Aggregates (typed, no strings!)
    "AggregateFunc",
    "Count", "Sum", "Avg", "Min", "Max",
    "ArrayAgg", "StringAgg",
    "AggregateExpr",
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
    "AggregateSpec", "Aggregate",
    # KV
    "KVQuerySet",
    "kv",
    "KVGet", "KVSet", "KVDelete", "Exists", "Scan", "Keys",
    # KV backward compat
    "Get", "Set", "Delete",
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
    "AggregateCapability",
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

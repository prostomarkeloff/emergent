"""Query axis — entity-first data access via QuerySets.

Each QuerySet defines its own query language:
- RelationalQuerySet — filter, join, group_by (SQL-like)
- KVQuerySet — get, set, delete, scan (Redis-like)
- APIQuerySet — list, get, create, update, delete (REST-like)

QuerySet × Provider = Store

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
    SQLRelationalProvider,
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
    APIStore,
    BoundAPIQuerySet,
    api_store,
)

# Window functions
from emergent.wire.axis.query._window import (
    WindowFunc,
    RowNumber,
    Rank,
    DenseRank,
    Ntile,
    Lag,
    Lead,
    WindowSpec,
)

# SQL-specific QuerySet
from emergent.wire.axis.query._sql import (
    Window,
    ForUpdate,
    Returning,
    SQLOp,
    SQLRelationalOp,
    WindowBuilder,
    SQLRelationalQuerySet,
    sql_relational,
)

# Memory providers
from emergent.wire.axis.query.providers import (
    MemoryRelationalProvider,
    MemoryKVProvider,
    MemoryAPIProvider,
    MemoryAPIListResult,
)

# Coercion — Expr AST transform for storage coercion
from emergent.wire.axis.query._coerce import (
    ExprCoercer,
)

# Serialization — pure functions for expr ↔ dict conversion
from emergent.wire.axis.query import _serialize as serialize
from emergent.wire.axis.query._serialize import (
    expr_to_dict,
    expr_from_dict,
    expr_fields,
    expr_complexity,
    expr_depth,
    expr_repr,
)

# Simplification — boolean algebra optimizations
from emergent.wire.axis.query import _simplify as simplify
from emergent.wire.axis.query._simplify import (
    simplify_expr,
    flatten_and,
    flatten_or,
    unflatten_and,
    unflatten_or,
)

# Fold layer — open-world op dispatch for query compilation
from emergent.wire.axis.query._fold import (
    OpHandler,
    fold_query,
    QueryDialect,
    MEMORY_HANDLERS,
    MEMORY_DIALECT,
)

# Explain layer — self-description of query operations
from emergent.wire.axis.query._explain import (
    ExplainHandler,
    explain_ops,
    format_ops,
    ExplainDialect,
    RELATIONAL_EXPLAIN,
    API_EXPLAIN,
    KV_EXPLAIN,
    RELATIONAL_EXPLAIN_DIALECT,
    API_EXPLAIN_DIALECT,
    KV_EXPLAIN_DIALECT,
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
    "Get", "Delete",
    # API
    "APIQuerySet",
    "api",
    "ListOp", "GetOp", "CreateOp", "UpdateOp", "DeleteOp", "APIOp",
    "FilterMod", "OrderMod", "PageMod", "CursorMod", "OffsetMod",
    "SelectMod", "SearchMod", "IncludeMod", "APIMod",
    # Providers
    "RelationalProvider",
    "MutatingRelationalProvider",
    "SQLRelationalProvider",
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
    "APIStore",
    "BoundAPIQuerySet",
    "api_store",
    # Window functions
    "WindowFunc",
    "RowNumber", "Rank", "DenseRank", "Ntile", "Lag", "Lead",
    "WindowSpec",
    # SQL-specific
    "Window", "ForUpdate", "Returning",
    "SQLOp", "SQLRelationalOp",
    "WindowBuilder",
    "SQLRelationalQuerySet",
    "sql_relational",
    # Memory
    "MemoryRelationalProvider",
    "MemoryKVProvider",
    "MemoryAPIProvider",
    "MemoryAPIListResult",
    # Serialization namespace
    "serialize",
    # Serialization functions
    "expr_to_dict",
    "expr_from_dict",
    "expr_fields",
    "expr_complexity",
    "expr_depth",
    "expr_repr",
    # Simplification namespace
    "simplify",
    # Simplification functions
    "simplify_expr",
    "flatten_and",
    "flatten_or",
    "unflatten_and",
    "unflatten_or",
    # Coercion
    "ExprCoercer",
    # Fold layer
    "OpHandler",
    "fold_query",
    "QueryDialect",
    "MEMORY_HANDLERS",
    "MEMORY_DIALECT",
    # Explain layer
    "ExplainHandler",
    "explain_ops",
    "format_ops",
    "ExplainDialect",
    "RELATIONAL_EXPLAIN",
    "API_EXPLAIN",
    "KV_EXPLAIN",
    "RELATIONAL_EXPLAIN_DIALECT",
    "API_EXPLAIN_DIALECT",
    "KV_EXPLAIN_DIALECT",
)

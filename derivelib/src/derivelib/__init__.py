"""derivelib — DEPRECATED proxy to emergent.wire.derive.

derivelib will be removed in emergent 1.0.0.
Use emergent.wire.derive directly for all derivation needs.

    from emergent.wire.derive import compile_derive, materialize, http_crud
    from emergent.wire.axis.schema._universal import schema_meta

    @schema_meta(http_crud("/api/users", provider_node=UserProvider))
    @dataclass
    class User:
        id: Annotated[int, Identity]
        email: str

    ctx = compile_derive(User)
    endpoint = materialize(ctx)
"""

from __future__ import annotations

import warnings
from typing import TYPE_CHECKING, Any

warnings.warn(
    "derivelib is deprecated. Use emergent.wire.derive directly. "
    "derivelib will be removed in emergent 1.0.0.",
    DeprecationWarning,
    stacklevel=2,
)

if TYPE_CHECKING:
    from emergent.wire.axis.surface import Application

# ═══════════════════════════════════════════════════════════════════════════════
# Pattern Derivation (proxy to wire.derive)
# ═══════════════════════════════════════════════════════════════════════════════

from ._derive import (
    # Decorator
    derive,
    # Accessors
    get_patterns,
    get_exposures,
    get_derivations,
    # Derivation
    derive_application,
    derive_endpoints,
    derive_from_decorated,
    # Application builders
    build_application,
    build_endpoint,
    build_application_from_decorated,
)

# ═══════════════════════════════════════════════════════════════════════════════
# Domain errors (re-export from wire.derive)
# ═══════════════════════════════════════════════════════════════════════════════

from emergent.wire.derive._errors import (
    ProblemDetail,
    NotFound,
    AlreadyExists,
    InvalidData,
    DomainError,
)

# ═══════════════════════════════════════════════════════════════════════════════
# Error capabilities (re-export from wire.derive)
# ═══════════════════════════════════════════════════════════════════════════════

from emergent.wire.derive._error_caps import (
    ErrorTransform,
    ProblemResponse,
    ERROR_CAPS,
)

# ═══════════════════════════════════════════════════════════════════════════════
# Effects (re-export from wire.derive)
# ═══════════════════════════════════════════════════════════════════════════════

from emergent.wire.derive._effects import (
    DerivationEffect,
    Read,
    Mutation,
    Idempotent,
    Creates,
    Updates,
    Deletes,
    Pageable,
    Sortable,
    Cacheable,
    Filterable,
    Searchable,
    Public,
    RateLimited,
    Validated,
    Versioned,
    Bulk,
    Auditable,
    Emits,
    Deprecated,
    has_effect,
    get_effect,
)

# ═══════════════════════════════════════════════════════════════════════════════
# Field projections + response specs (re-export from wire.derive)
# ═══════════════════════════════════════════════════════════════════════════════

from emergent.wire.derive._project import (
    FieldProjection,
    ResponseSpec,
    response_fields,
    response_converter,
    AllFields,
    IdOnly,
    NonId,
    RequiredNonId,
    NoFields,
    SelectFields,
    ExcludeFields,
    ExcludeFromProjection,
    OptionalNonId,
    MergeProjection,
    EntityResponse,
    ListResponse,
    OkResponse,
    PaginatedResponse,
    CountResponse,
    EmptyResponse,
    CursorPaginatedResponse,
    CustomResponse,
    all_fields,
    id_only,
    non_id,
    required_non_id,
    no_fields,
    fields,
    exclude,
    optional_non_id,
    merge,
    entity_response,
    list_response,
    ok_response,
    paginated_response,
    count_response,
    empty_response,
    cursor_paginated_response,
    custom_response,
    dict_converter,
)

# exclude_from re-export
from emergent.wire.derive._project import exclude_from as exclude_from

# ═══════════════════════════════════════════════════════════════════════════════
# Handler templates (re-export from wire.derive)
# ═══════════════════════════════════════════════════════════════════════════════

from emergent.wire.derive._handler import (
    HandlerTemplate,
    HandlerSpec,
    WrappedTemplate,
    wrap_template,
    FetchMany,
    FetchOneById,
    InsertNew,
    UpdateExisting,
    DeleteOne,
    PaginatedFetchMany,
    CachedFetchOneById,
    PatchExisting,
    SortedFetchMany,
)

# ═══════════════════════════════════════════════════════════════════════════════
# Query helpers (re-export from wire.derive)
# ═══════════════════════════════════════════════════════════════════════════════

from emergent.wire.derive._query_helpers import (
    filter_by_identity,
    identity_values,
    scoped_query,
    identity_query,
    fetch_by_identity,
    fetch_or_not_found,
    not_found_error,
    serialize_op_fields,
    provider_field,
    id_path,
)

# ═══════════════════════════════════════════════════════════════════════════════
# Codegen (re-export from wire.derive)
# ═══════════════════════════════════════════════════════════════════════════════

from emergent.wire.derive._codegen import (
    create_dataclass,
    set_type_name,
    create_request_type,
    create_response_type,
    annotate_handler,
)

# ═══════════════════════════════════════════════════════════════════════════════
# Builders (re-export from wire.derive)
# ═══════════════════════════════════════════════════════════════════════════════

from emergent.wire.derive._builders import (
    ExposureBuilder,
    exposure,
    EndpointBuilder,
    endpoint_builder,
)

# ═══════════════════════════════════════════════════════════════════════════════
# Explain (re-export from wire.derive)
# ═══════════════════════════════════════════════════════════════════════════════

from emergent.wire.derive._explain import (
    explain_derive,
    explain_entity,
    derive_dict,
)

# ═══════════════════════════════════════════════════════════════════════════════
# Transforms (from rewritten transforms.py)
# ═══════════════════════════════════════════════════════════════════════════════

from .transforms import (
    # Semantic transforms
    readonly,
    mutations_only,
    without_delete,
    # Response projection
    project_response,
    # Query enrichment
    paginated,
    sorted_list,
    # Enrichers
    with_timeout,
    with_retry,
    with_rate_limit,
    # Effect-aware transforms
    filtered,
    searchable,
    rate_limited,
    deprecated,
)

# ═══════════════════════════════════════════════════════════════════════════════
# Subpackages
# ═══════════════════════════════════════════════════════════════════════════════

from . import patterns

# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════


def memory_node(key_field: str = "id", auto_id: bool = True) -> type:
    """Create a scalar_node backed by in-memory relational provider.

    Replaces the 8-line @scalar_node + MemoryRelationalProvider boilerplate::

        Users = memory_node()

    Equivalent to::

        @scalar_node
        class Users:
            @classmethod
            def __compose__(cls) -> MutatingRelationalProvider:
                return MemoryRelationalProvider(
                    key_fn=lambda x: getattr(x, "id"),
                    next_id=SequenceNextId(),
                )
    """
    from nodnod import scalar_node
    from emergent.wire.axis.query import MutatingRelationalProvider, SequenceNextId
    from emergent.wire.axis.query.providers.memory import MemoryRelationalProvider

    next_id = SequenceNextId() if auto_id else None
    # Any: entity type unknown at node creation — resolved at compose time.
    store: MemoryRelationalProvider[Any] = MemoryRelationalProvider(
        key_fn=lambda x: getattr(x, key_field),
        next_id=next_id,
    )

    @scalar_node
    class _Node:
        @classmethod
        def __compose__(cls) -> MutatingRelationalProvider[Any]:
            return store

    return _Node


def endpoint_count(app: Application) -> int:
    """Count total exposures across all endpoints in an Application."""
    return sum(len(ep.exposures) for ep in app.endpoints)


# ═══════════════════════════════════════════════════════════════════════════════
# Blocked imports — low-level API removed
# ═══════════════════════════════════════════════════════════════════════════════

_BLOCKED_NAMES = frozenset({
    # Old contexts
    "SchemaCtx", "QueryCtx", "StorageCtx", "SurfaceCtx", "DerivationCtx",
    # Old protocols
    "SchemaDerivable", "QueryDerivable", "StorageDerivable", "SurfaceDerivable",
    "FullDerivable",
    # Old core types
    "Step", "Derivation", "DerivationT",
    "Pattern", "ExposureT",
    # Old fold infrastructure
    "StepHandler", "fold_steps", "DerivationPhase",
    "SCHEMA_PHASE", "QUERY_PHASE", "STORAGE_PHASE", "SURFACE_PHASE",
    "fold_derive", "materialize",
    # Old dialect infrastructure
    "Op", "TriggerGen", "Dialect", "ChainedPattern",
    "DEFAULT_REST_ROUTES", "HTTPTriggers", "NestedHTTPTriggers", "CLITriggers",
    "dialect", "with_caps", "select_ops", "exclude_ops", "by_effect",
    # Old surface step
    "DeriveOp",
    # Old adaptation
    "AdaptationDialect", "default_adaptation",
    # Old opspec
    "OpSpec", "build_from_spec",
    # Old low-level transforms
    "map_by_effect", "reject_by_effect", "select_by_effect",
    "map_all_ops", "without_ops", "only_ops",
    "wrap_by_effect", "add_capability",
    "swap_handler", "swap_trigger", "rename_ops",
    "with_effect", "map_methods", "add_method_capability",
    # Old explain internals
    "DeriveExplainHandler", "DERIVE_EXPLAIN",
    "opspec_dict", "step_dict", "derivation_dict",
    "entity_derivation_dict", "dialect_dict", "full_entity_dict",
    "explain_opspec", "explain_derivation", "explain_full",
    # axes subpackage
    "axes",
})

_BLOCKED_MSG = (
    "derivelib.{name} has been removed. "
    "Use emergent.wire.derive directly. "
    "derivelib will be removed in emergent 1.0.0."
)


def __getattr__(name: str) -> object:
    if name in _BLOCKED_NAMES:
        raise ImportError(_BLOCKED_MSG.format(name=name))
    raise AttributeError(f"module 'derivelib' has no attribute {name!r}")


# ═══════════════════════════════════════════════════════════════════════════════
# Exports
# ═══════════════════════════════════════════════════════════════════════════════

__all__ = (
    # Pattern Derivation
    "derive",
    "get_patterns",
    "get_exposures",
    "get_derivations",
    "derive_application",
    "derive_endpoints",
    "derive_from_decorated",
    "build_application",
    "build_endpoint",
    "build_application_from_decorated",
    # Generic domain errors
    "ProblemDetail",
    "NotFound",
    "AlreadyExists",
    "InvalidData",
    "DomainError",
    # Generic error capabilities
    "ErrorTransform",
    "ProblemResponse",
    "ERROR_CAPS",
    # Effects
    "DerivationEffect",
    "Read",
    "Mutation",
    "Idempotent",
    "Creates",
    "Updates",
    "Deletes",
    "Pageable",
    "Sortable",
    "Cacheable",
    "Filterable",
    "Searchable",
    "Public",
    "RateLimited",
    "Validated",
    "Versioned",
    "Bulk",
    "Auditable",
    "Emits",
    "Deprecated",
    "has_effect",
    "get_effect",
    # Handler templates
    "HandlerTemplate",
    "HandlerSpec",
    "WrappedTemplate",
    "wrap_template",
    "FetchMany",
    "FetchOneById",
    "InsertNew",
    "UpdateExisting",
    "DeleteOne",
    "PaginatedFetchMany",
    "CachedFetchOneById",
    "PatchExisting",
    "SortedFetchMany",
    # Field projections + response specs
    "FieldProjection",
    "ResponseSpec",
    "response_fields",
    "response_converter",
    "AllFields",
    "IdOnly",
    "NonId",
    "RequiredNonId",
    "NoFields",
    "SelectFields",
    "ExcludeFields",
    "ExcludeFromProjection",
    "OptionalNonId",
    "MergeProjection",
    "EntityResponse",
    "ListResponse",
    "OkResponse",
    "PaginatedResponse",
    "CountResponse",
    "EmptyResponse",
    "CursorPaginatedResponse",
    "CustomResponse",
    "all_fields",
    "id_only",
    "non_id",
    "required_non_id",
    "no_fields",
    "fields",
    "exclude",
    "optional_non_id",
    "merge",
    "entity_response",
    "list_response",
    "ok_response",
    "paginated_response",
    "count_response",
    "empty_response",
    "cursor_paginated_response",
    "custom_response",
    "dict_converter",
    # Query helpers
    "filter_by_identity",
    "identity_values",
    "scoped_query",
    "identity_query",
    "fetch_by_identity",
    "not_found_error",
    "fetch_or_not_found",
    "serialize_op_fields",
    "provider_field",
    "id_path",
    # Codegen
    "create_dataclass",
    "set_type_name",
    "create_request_type",
    "create_response_type",
    "annotate_handler",
    "ExposureBuilder",
    "exposure",
    "EndpointBuilder",
    "endpoint_builder",
    # Explain
    "explain_derive",
    "explain_entity",
    "derive_dict",
    # Transforms
    "readonly",
    "mutations_only",
    "without_delete",
    "project_response",
    "paginated",
    "sorted_list",
    "with_timeout",
    "with_retry",
    "with_rate_limit",
    "filtered",
    "searchable",
    "rate_limited",
    "deprecated",
    # Helpers
    "memory_node",
    "endpoint_count",
    # Subpackages
    "patterns",
)

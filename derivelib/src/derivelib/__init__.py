"""derivelib — Derivation algebra over wire IR.

Dogfoods emergent.wire: reads schema/query/surface primitives,
generates wire Applications via two-pass fold.

    from derivelib import derive, build_application_from_decorated
    from derivelib.patterns import http_crud

    @derive(http_crud("/api/users", provider_node=UserProvider))
    @dataclass
    class User:
        id: Annotated[int, Identity]
        email: str

    app = build_application_from_decorated(User)

For wire primitives (triggers, codecs, schema, query, storage),
import directly from emergent.wire.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from emergent.wire.axis.surface import Application

# ═══════════════════════════════════════════════════════════════════════════════
# Pattern Derivation
# ═══════════════════════════════════════════════════════════════════════════════

from ._derive import (
    # Types
    Pattern,
    ExposureT,
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
# Multi-Axis Derivation Infrastructure
# ═══════════════════════════════════════════════════════════════════════════════

# Contexts
from ._ctx import (
    SchemaCtx,
    QueryCtx,
    StorageCtx,
    SurfaceCtx,
    DerivationCtx,
)

# Protocols
from ._protocols import (
    SchemaDerivable,
    QueryDerivable,
    StorageDerivable,
    SurfaceDerivable,
    FullDerivable,
    HandlerTemplate,
    HandlerSpec,
    WrappedTemplate,
    wrap_template,
)

# Generic domain errors
from ._errors import (
    ProblemDetail,
    NotFound,
    AlreadyExists,
    InvalidData,
    DomainError,
)

# Generic error capabilities
from ._error_caps import (
    ErrorTransform,
    ProblemResponse,
    ERROR_CAPS,
)

# Generic query helpers
from ._query_helpers import (
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

# OpSpec (inspectable operation description)
from ._opspec import (
    OpSpec,
    build_from_spec,
)

# Generic handler templates
from ._handler_templates import (
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

# Derivation core types
from ._derivation import (
    Step,
    Derivation,
    DerivationT,
)

# Fold primitive + phases
from ._fold import (
    StepHandler,
    fold_steps,
    DerivationPhase,
    SCHEMA_PHASE,
    QUERY_PHASE,
    STORAGE_PHASE,
    SURFACE_PHASE,
    fold_derive,
    materialize,
)

# Field projections + response specs
from ._project import (
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
    exclude_from as exclude_from,
)

# Adaptation
from .adapt import (  # noqa: F401
    AdaptationDialect as AdaptationDialect,
    default_adaptation as default_adaptation,
)

# Effects (derivation-phase capabilities)
from ._effects import (
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

# Transforms
from .transforms import (
    # Fold primitives
    map_by_effect,
    reject_by_effect,
    select_by_effect,
    map_all_ops,
    # Semantic transforms
    readonly,
    mutations_only,
    without_delete,
    without_ops,
    only_ops,
    # Response projection
    project_response,
    # Handler wrapping
    wrap_by_effect,
    # Capability injection
    add_capability,
    # Handler / trigger swaps
    swap_handler,
    swap_trigger,
    rename_ops,
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
    with_effect,
    # Methods transforms
    map_methods,
    add_method_capability,
)

# Dialect infrastructure
from ._dialect import (
    Op,
    TriggerGen,
    Dialect,
    ChainedPattern,
    DEFAULT_REST_ROUTES,
    HTTPTriggers,
    NestedHTTPTriggers,
    CLITriggers,
    dialect,
    with_caps,
    select_ops,
    exclude_ops,
    by_effect,
)

# Codegen infrastructure (for custom patterns)
from ._codegen import (
    create_dataclass,
    set_type_name,
    create_request_type,
    create_response_type,
    annotate_handler,
    ExposureBuilder,
    exposure,
    EndpointBuilder,
    endpoint_builder,
)

# Surface step (re-export for convenience)
from .axes.surface import DeriveOp

# Explain — derivation pipeline introspection
from ._explain import (
    DeriveExplainHandler,
    DERIVE_EXPLAIN,
    opspec_dict,
    step_dict,
    derivation_dict,
    entity_derivation_dict,
    dialect_dict,
    full_entity_dict,
    explain_opspec,
    explain_derivation,
    explain_entity,
    explain_full,
)

# Per-axis step libraries
from . import axes

# Patterns
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
    """Count total exposures across all endpoints in an Application.

    Replaces the repeated ``sum(len(ep.exposures) for ep in app.endpoints)``::

        app = build_application_from_decorated(User)
        print(f"{endpoint_count(app)} endpoints")
    """
    return sum(len(ep.exposures) for ep in app.endpoints)


# ═══════════════════════════════════════════════════════════════════════════════
# Exports
# ═══════════════════════════════════════════════════════════════════════════════

__all__ = (
    # Pattern Derivation
    "Pattern",
    "ExposureT",
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
    # Contexts
    "SchemaCtx",
    "QueryCtx",
    "StorageCtx",
    "SurfaceCtx",
    "DerivationCtx",
    # Protocols
    "SchemaDerivable",
    "QueryDerivable",
    "StorageDerivable",
    "SurfaceDerivable",
    "FullDerivable",
    "HandlerTemplate",
    "HandlerSpec",
    "WrappedTemplate",
    "wrap_template",
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
    # Generic query helpers
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
    # Generic handler templates
    "FetchMany",
    "FetchOneById",
    "InsertNew",
    "UpdateExisting",
    "DeleteOne",
    "PaginatedFetchMany",
    "CachedFetchOneById",
    "PatchExisting",
    "SortedFetchMany",
    # OpSpec
    "OpSpec",
    "build_from_spec",
    # Derivation core types
    "Step",
    "Derivation",
    "DerivationT",
    # Fold
    "StepHandler",
    "fold_steps",
    "DerivationPhase",
    "SCHEMA_PHASE",
    "QUERY_PHASE",
    "STORAGE_PHASE",
    "SURFACE_PHASE",
    "fold_derive",
    "materialize",
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
    # Transforms
    "map_by_effect",
    "reject_by_effect",
    "select_by_effect",
    "map_all_ops",
    "readonly",
    "mutations_only",
    "without_delete",
    "without_ops",
    "only_ops",
    "project_response",
    "wrap_by_effect",
    "add_capability",
    "swap_handler",
    "swap_trigger",
    "rename_ops",
    "paginated",
    "sorted_list",
    "with_timeout",
    "with_retry",
    "with_rate_limit",
    "filtered",
    "searchable",
    "rate_limited",
    "deprecated",
    "with_effect",
    # Methods transforms
    "map_methods",
    "add_method_capability",
    # Dialect
    "Op",
    "TriggerGen",
    "Dialect",
    "ChainedPattern",
    "DEFAULT_REST_ROUTES",
    "HTTPTriggers",
    "NestedHTTPTriggers",
    "CLITriggers",
    "dialect",
    "with_caps",
    "select_ops",
    "exclude_ops",
    "by_effect",
    # Explain
    "DeriveExplainHandler",
    "DERIVE_EXPLAIN",
    "opspec_dict",
    "step_dict",
    "derivation_dict",
    "entity_derivation_dict",
    "dialect_dict",
    "full_entity_dict",
    "explain_opspec",
    "explain_derivation",
    "explain_entity",
    "explain_full",
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
    # Surface step
    "DeriveOp",
    # Helpers
    "memory_node",
    "endpoint_count",
    # Subpackages
    "axes",
    "patterns",
)

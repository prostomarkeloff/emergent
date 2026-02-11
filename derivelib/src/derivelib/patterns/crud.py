"""CRUD dialect — built on generic dialect infrastructure.

CRUD = 6 Ops (List, Get, Create, Update, Patch, Delete) + error transforms.
Transport-agnostic — use http_crud(), cli_crud(), or dialect() with custom triggers.

CRUD is NOT special. It's 6 Op descriptors with CRUD-specific handler templates.
Anyone can build their own dialect the same way.

    from derivelib.patterns.crud import http_crud, LIST, GET

    @derive(http_crud("/api/users", provider_node=UserProvider))
    @dataclass
    class User:
        id: Annotated[int, Identity]
        name: str

    # Read-only:
    @derive(http_crud("/api/users", provider_node=UserProvider, ops=(LIST, GET)))
"""

from __future__ import annotations

from emergent.wire.axis.surface.capabilities import SurfaceCapability

from derivelib._dialect import (
    CLITriggers,
    Dialect,
    HTTPTriggers,
    Op,
    TriggerGen,
    dialect,
)
from derivelib._effects import Cacheable, Creates, Deletes, Idempotent, Pageable, Read, Sortable, Updates
from derivelib._project import (
    all_fields,
    entity_response,
    id_only,
    list_response,
    merge,
    no_fields,
    non_id,
    ok_response,
    optional_non_id,
)

# Re-exports from extracted modules (backward compatibility)
from derivelib._errors import (  # noqa: F401
    AlreadyExists,
    DomainError as CRUDError,  # Deprecated: use DomainError from derivelib directly
    InvalidData,
    NotFound,
    ProblemDetail,
)
from derivelib._query_helpers import (  # noqa: F401
    filter_by_identity as filter_by_identity,
    identity_values as identity_values,
)
from derivelib._handler_templates import (  # noqa: F401
    CachedFetchOneById,
    DeleteOne,
    FetchMany,
    FetchOneById,
    InsertNew,
    PaginatedFetchMany,
    PatchExisting,
    UpdateExisting,
)

# Error transform capabilities — extracted to _error_caps.py, re-exported for backward compat
from derivelib._error_caps import ErrorTransform as CRUDErrorTransform, ProblemResponse, ERROR_CAPS  # noqa: F401


# ═══════════════════════════════════════════════════════════════════════════════
# CRUD Ops — transport-agnostic operation descriptors
# ═══════════════════════════════════════════════════════════════════════════════

LIST = Op("List", no_fields(), list_response(), FetchMany(), effects=(Read(), Pageable(), Sortable()))
GET = Op("Get", id_only(), entity_response(), FetchOneById(), effects=(Read(), Idempotent(), Cacheable()))
CREATE = Op("Create", non_id(), entity_response(), InsertNew(), effects=(Creates(),))
UPDATE = Op("Update", all_fields(), entity_response(), UpdateExisting(), effects=(Updates(), Idempotent()))
PATCH = Op("Patch", merge(id_only(), optional_non_id()), entity_response(), PatchExisting(), effects=(Updates(), Idempotent()))
DELETE = Op("Delete", id_only(), ok_response(), DeleteOne(), effects=(Deletes(), Idempotent()))

ALL_CRUD_OPS = (LIST, GET, CREATE, UPDATE, PATCH, DELETE)
MUTATION_CRUD_OPS = (CREATE, UPDATE, PATCH, DELETE)
READ_CRUD_OPS = (LIST, GET)

CRUD_ERROR_CAPS = ERROR_CAPS


# ═══════════════════════════════════════════════════════════════════════════════
# CRUD Dialect — thin wrapper around dialect()
# ═══════════════════════════════════════════════════════════════════════════════


def crud(
    triggers: TriggerGen,
    provider_node: type,
    *caps: SurfaceCapability,
    ops: tuple[Op, ...] | None = None,
) -> Dialect:
    """CRUD dialect = standard ops + error transforms.

        crud(HTTPTriggers("/api/users"), UserProvider)
        crud(CLITriggers("user"), UserProvider)
        crud(HTTPTriggers("/api/users"), UserProvider, ops=(LIST, GET))
    """
    return dialect(
        *(ops or ALL_CRUD_OPS),
        triggers=triggers,
        provider_node=provider_node,
        capabilities=(*caps, *CRUD_ERROR_CAPS),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Presets
# ═══════════════════════════════════════════════════════════════════════════════


def http_crud(
    base_path: str,
    provider_node: type,
    *caps: SurfaceCapability,
    ops: tuple[Op, ...] | None = None,
) -> Dialect:
    """HTTP CRUD dialect."""
    return crud(HTTPTriggers(base_path), provider_node, *caps, ops=ops)


def cli_crud(
    prefix: str,
    provider_node: type,
    *caps: SurfaceCapability,
    ops: tuple[Op, ...] | None = None,
) -> Dialect:
    """CLI CRUD dialect."""
    return crud(CLITriggers(prefix), provider_node, *caps, ops=ops)


# ═══════════════════════════════════════════════════════════════════════════════
# Exports
# ═══════════════════════════════════════════════════════════════════════════════

__all__ = (
    # CRUD Ops (the building blocks)
    "LIST",
    "GET",
    "CREATE",
    "UPDATE",
    "PATCH",
    "DELETE",
    "ALL_CRUD_OPS",
    "MUTATION_CRUD_OPS",
    "READ_CRUD_OPS",
    "CRUD_ERROR_CAPS",
    # Errors + RFC 7807
    "ProblemDetail",
    "NotFound",
    "AlreadyExists",
    "InvalidData",
    "CRUDError",
    # Error transforms
    "CRUDErrorTransform",
    "ProblemResponse",
    # Handler templates (reusable building blocks)
    "FetchMany",
    "FetchOneById",
    "InsertNew",
    "UpdateExisting",
    "DeleteOne",
    # Enriched handler templates
    "PaginatedFetchMany",
    "CachedFetchOneById",
    "PatchExisting",
    # Pattern
    "crud",
    # Presets
    "http_crud",
    "cli_crud",
)

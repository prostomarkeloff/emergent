"""CRUD pattern — proxy to emergent.wire.derive.

DEPRECATED: Use emergent.wire.derive directly.
derivelib will be removed in emergent 1.0.0.

    from derivelib.patterns.crud import http_crud, LIST, GET

    @derive(http_crud("/api/users", provider_node=UserProvider))
    @dataclass
    class User:
        id: Annotated[int, Identity]
        name: str
"""

from __future__ import annotations

from emergent.wire.axis.surface.capabilities import SurfaceCapability
from emergent.wire.derive._crud import (
    ALL_CRUD_OPS,
    CREATE,
    CRUD,
    DELETE,
    GET,
    LIST,
    MUTATION_CRUD_OPS,
    PATCH,
    READ_CRUD_OPS,
    UPDATE,
)
from emergent.wire.derive._crud import (
    crud as _wire_crud,
    http_crud as _wire_http_crud,
    cli_crud as _wire_cli_crud,
)
from emergent.wire.derive._error_caps import (
    ERROR_CAPS,
    ErrorTransform as CRUDErrorTransform,
    ProblemResponse,
)
from emergent.wire.derive._errors import (
    AlreadyExists,
    DomainError as CRUDError,
    InvalidData,
    NotFound,
    ProblemDetail,
)
from emergent.wire.derive._handler import (
    CachedFetchOneById,
    DeleteOne,
    FetchMany,
    FetchOneById,
    InsertNew,
    PaginatedFetchMany,
    PatchExisting,
    UpdateExisting,
)
from emergent.wire.derive._opspec import Op

from derivelib._compat import ChainableCapability

CRUD_ERROR_CAPS = ERROR_CAPS


def crud(
    triggers: object,
    provider_node: type,
    *caps: SurfaceCapability,
    ops: tuple[Op, ...] | None = None,
) -> ChainableCapability:
    """CRUD pattern with .chain() support.

        crud(HTTPTriggers("/api/users"), UserProvider)
        crud(HTTPTriggers("/api/users"), UserProvider, ops=(LIST, GET))
    """
    inner = _wire_crud(triggers, provider_node, *caps, ops=ops)
    return ChainableCapability(inner=inner)


def http_crud(
    base_path: str,
    provider_node: type,
    *caps: SurfaceCapability,
    ops: tuple[Op, ...] | None = None,
) -> ChainableCapability:
    """HTTP CRUD pattern with .chain() support."""
    inner = _wire_http_crud(base_path, provider_node, *caps, ops=ops)
    return ChainableCapability(inner=inner)


def cli_crud(
    prefix: str,
    provider_node: type,
    *caps: SurfaceCapability,
    ops: tuple[Op, ...] | None = None,
) -> ChainableCapability:
    """CLI CRUD pattern with .chain() support."""
    inner = _wire_cli_crud(prefix, provider_node, *caps, ops=ops)
    return ChainableCapability(inner=inner)


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

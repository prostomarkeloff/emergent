"""derivelib.patterns — proxy to emergent.wire.derive patterns.

DEPRECATED: Use emergent.wire.derive directly.
derivelib will be removed in emergent 1.0.0.

    from derivelib.patterns import http_crud

    @derive(http_crud("/api/users", provider_node=UserProvider))
    @dataclass
    class User:
        id: Annotated[int, Identity]
        email: str
"""

from .crud import (
    # CRUD Ops (the building blocks)
    LIST,
    GET,
    CREATE,
    UPDATE,
    PATCH,
    DELETE,
    ALL_CRUD_OPS,
    MUTATION_CRUD_OPS,
    READ_CRUD_OPS,
    CRUD_ERROR_CAPS,
    # Errors + RFC 7807
    ProblemDetail,
    ProblemResponse,
    CRUDErrorTransform,
    NotFound,
    AlreadyExists,
    InvalidData,
    CRUDError,
    # Handler templates
    FetchMany,
    FetchOneById,
    InsertNew,
    UpdateExisting,
    DeleteOne,
    # Pattern
    crud,
    # Presets
    http_crud,
    cli_crud,
)

from .nested import (
    NestedCrudPattern,
    nested_http_crud,
)

from .methods import (
    methods,
    MethodsPattern,
    method,
    post,
    get,
    put,
    delete,
    patch,
    command,
)

__all__: list[str] = [
    # CRUD Ops
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
    "ProblemResponse",
    "CRUDErrorTransform",
    "NotFound",
    "AlreadyExists",
    "InvalidData",
    "CRUDError",
    # Handler templates
    "FetchMany",
    "FetchOneById",
    "InsertNew",
    "UpdateExisting",
    "DeleteOne",
    # Pattern
    "crud",
    # Presets
    "http_crud",
    "cli_crud",
    # Nested
    "NestedCrudPattern",
    "nested_http_crud",
    # Methods
    "MethodsPattern",
    "methods",
    "method",
    "post",
    "get",
    "put",
    "delete",
    "patch",
    "command",
]

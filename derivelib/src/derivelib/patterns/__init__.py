"""derivelib.patterns — Derivation dialects built from generic primitives.

CRUD = schema × query × surface (via Op descriptors from derivelib._dialect)

Provider resolved at runtime via compose.Node (nodnod node composition).
CRUD is just ONE dialect — anyone can build their own.

    from derivelib import derive, build_application
    from derivelib.patterns import http_crud

    @derive(http_crud("/api/users", provider_node=UserProvider))
    @dataclass
    class User:
        id: Annotated[int, Identity]
        email: str

    app = build_application_from_decorated(User)
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
    ExposeMethod,
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
    "ExposeMethod",
]

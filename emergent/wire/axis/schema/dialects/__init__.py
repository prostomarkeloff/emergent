"""Schema dialects — backend-specific capabilities.

Each dialect provides capabilities that only its compiler understands.
Other compilers ignore these annotations.

    from emergent.wire.axis.schema.dialects import sql, openapi, cli, api

    @dataclass
    class User:
        email: Annotated[str,
            Unique,                      # Universal
            sql.Index("idx_email"),      # SQL only
            openapi.Format("email"),     # OpenAPI only
        ]

    @dataclass
    class Register:
        login: Annotated[str, cli.Help("Username"), cli.Positional()]
        verbose: Annotated[bool, cli.Flag("-v", "--verbose")]

    @dataclass
    class APIUser:
        id: Annotated[str, Identity, api.PathParam()]
        name: Annotated[str, api.Filterable, api.Sortable]
"""

from emergent.wire.axis.schema.dialects import sql, openapi, pydantic, cli, api

__all__ = ("sql", "openapi", "pydantic", "cli", "api")

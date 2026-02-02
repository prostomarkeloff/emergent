"""Schema dialects — target-specific capabilities.

Each dialect provides capabilities that only its compiler understands.
Other compilers ignore these annotations.

    from emergent.wire.axis.schema.dialects import sql, openapi, cli, css, tg

    @dataclass
    class User:
        email: Annotated[str,
            Unique,                      # Universal
            sql.Index("idx_email"),      # SQL compiler
            openapi.Format("email"),     # OpenAPI compiler
        ]

    @dataclass
    class Register:
        login: Annotated[str, cli.Help("Username"), cli.Positional()]

    @dataclass
    class DashboardResponse:
        balance: Annotated[Decimal,
            ui.Money(),                  # UI semantic (universal)
            css.Class("text-green-500"), # HTML/React/Vue compiler
            tg.Bold(), tg.Emoji("💰"),   # Telegram compiler
        ]
"""

from emergent.wire.axis.schema.dialects import sql, openapi, pydantic, cli, api, tg, compose, query

__all__ = ("sql", "openapi", "pydantic", "cli", "api", "tg", "compose", "query")

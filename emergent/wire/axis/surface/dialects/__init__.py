"""Surface dialects — target-specific capabilities.

Like schema dialects (sql, openapi, pydantic), surface dialects
contain target-specific capabilities that only certain compilers read.

    from emergent.wire.axis.surface.dialects import http, telegram, cli

    endpoint(runner).expose(
        trigger, codec,
        http.Tag.of("users"),
        http.BearerAuth.jwt(),
        telegram.EditMessage(),
        cli.Help("List users"),
    )
"""

from emergent.wire.axis.surface.dialects import http
from emergent.wire.axis.surface.dialects import telegram
from emergent.wire.axis.surface.dialects import cli

__all__ = (
    "http",
    "telegram",
    "cli",
)

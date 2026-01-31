"""
Triggers — describe how endpoints are exposed (e.g., HTTP routes, CLI subcommands).

    from emergent.wire.axis.surface import triggers

    triggers.http.HTTPRouteTrigger(...)
    triggers.cli.CLITrigger(...)
    triggers.telegrinder.TelegrindTrigger(...)
"""

from emergent.wire.axis.surface.triggers import http, cli, telegrinder


__all__ = ("http", "cli", "telegrinder")

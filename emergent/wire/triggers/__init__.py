"""
Triggers — describe how endpoints are exposed (e.g., HTTP routes, CLI subcommands).

    from emergent.wire.triggers.http import HTTPRouteTrigger
    from emergent.wire.triggers.cli import CLITrigger
    from emergent.wire.triggers.telegrinder import TelegrindTrigger
"""

from emergent.wire.triggers import http, cli, telegrinder


__all__ = ("http", "cli", "telegrinder")

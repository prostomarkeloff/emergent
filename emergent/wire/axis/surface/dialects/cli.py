"""CLI surface dialect — CLI command-level capabilities.

These capabilities configure CLI subcommand metadata.
Only the CLI compiler reads them; HTTP/TG compilers ignore.

    from emergent.wire.axis.surface.dialects import cli as cli_cmd

    endpoint(runner).expose(
        CLITrigger("users", "List users"),
        codec,
        cli_cmd.Help("List all registered users"),
        cli_cmd.Epilog("Outputs in table format"),
    )
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from emergent.wire.axis._capability import cli_command
from emergent.wire.axis.surface.capabilities._base import SurfaceCapability

if TYPE_CHECKING:
    from emergent.wire.axis._capability import CLICommandContext


@dataclass(frozen=True, slots=True)
class Help(SurfaceCapability):
    """Subcommand help text (one-liner shown in parent command list).

    Usage:
        cli_cmd.Help("List all registered users")
    """

    text: str

    def compile_cli(self, ctx: CLICommandContext) -> CLICommandContext:
        return cli_command(ctx, help=self.text)


@dataclass(frozen=True, slots=True)
class Description(SurfaceCapability):
    """Subcommand description (shown in subcommand's own --help).

    Argparse distinguishes help (one-liner in parent list)
    from description (shown at top of subcommand's --help).

    Usage:
        cli_cmd.Description("List all registered users with optional filters")
    """

    text: str

    def compile_cli(self, ctx: CLICommandContext) -> CLICommandContext:
        return cli_command(ctx, description=self.text)


@dataclass(frozen=True, slots=True)
class Epilog(SurfaceCapability):
    """Subcommand epilog text (shown at bottom of --help).

    Usage:
        cli_cmd.Epilog("Examples:\\n  my-tool users --format=json")
    """

    text: str

    def compile_cli(self, ctx: CLICommandContext) -> CLICommandContext:
        return cli_command(ctx, epilog=self.text)


@dataclass(frozen=True, slots=True)
class Hidden(SurfaceCapability):
    """Hide subcommand from help listing.

    The command still works — it's just not shown in parent --help.

    Usage:
        cli_cmd.Hidden()
    """

    def compile_cli(self, ctx: CLICommandContext) -> CLICommandContext:
        return cli_command(ctx, hidden=True)


__all__ = (
    "Help",
    "Description",
    "Epilog",
    "Hidden",
)

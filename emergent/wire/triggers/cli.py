"""CLI trigger — expose endpoints as argparse subcommands."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Any, Sequence


@dataclass(frozen=True, slots=True)
class CLITrigger:
    """Trigger for CLI subcommand.

    Only carries the subcommand identity. Arguments are derived
    from the codec's request type by the CLI compiler — same way
    FastAPI derives route params from BaseModel fields.

        trigger = CLITrigger(command="scan", description="Scan path")
    """

    command: str
    description: str = ""


@dataclass(frozen=True, slots=True)
class CLIMeta:
    """Typed metadata for CLI argument generation.

    Attached to dataclass fields via ``cli_field()``.
    The CLI compiler reads this to generate argparse arguments.
    """

    help: str = ""
    choices: Sequence[str] | None = None
    cli_name: str | None = None
    cli_action: str | None = None


_CLI_META_KEY = "__cli__"


def cli_field(
    default: Any = dataclasses.MISSING,
    *,
    help: str = "",
    choices: Sequence[str] | None = None,
    cli_name: str | None = None,
    cli_action: str | None = None,
) -> Any:
    """Create a dataclass field with typed CLI metadata.

    @dataclass
    class ScanRequest:
        path: str = cli_field(help="Path to scan")
        format: str = cli_field("tree", help="Output format",
                                choices=["tree", "json"])
        is_async: bool = cli_field(True, cli_name="--sync",
                                   cli_action="store_false",
                                   help="Generate sync")
    """
    meta = CLIMeta(
        help=help,
        choices=choices,
        cli_name=cli_name,
        cli_action=cli_action,
    )
    metadata = {_CLI_META_KEY: meta}

    if default is dataclasses.MISSING:
        return dataclasses.field(metadata=metadata)
    return dataclasses.field(default=default, metadata=metadata)


def get_cli_meta(f: dataclasses.Field[Any]) -> CLIMeta | None:
    """Extract CLIMeta from a dataclass field, if present."""
    return f.metadata.get(_CLI_META_KEY)  # type: ignore[union-attr]

"""CLI trigger — expose endpoints as argparse subcommands."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CLITrigger:
    """Trigger for CLI subcommand.

    Only carries the subcommand identity. Arguments are derived
    from the codec's request type by the CLI compiler:
    - Plain dataclass fields → CLI arguments (type inferred)
    - Fields with defaults → optional flags (--field-name)
    - Fields without defaults → positional arguments
    - bool fields with default=False → --flag (store_true)
    - list fields → nargs="*"

    For custom CLI behavior, use schema capabilities:
    - cli.Help("description") → argparse help text
    - cli.Choices(["a", "b"]) → argparse choices
    - cli.Name("--custom") → custom argument name

        trigger = CLITrigger(command="scan", description="Scan path")
    """

    command: str
    description: str = ""

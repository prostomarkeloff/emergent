"""Emergent CLI app with state inspection command.

Run:
    python -m examples.cross_compile.emergent_cli state
"""

import json
from dataclasses import dataclass

from emergent.wire.axis.surface import Application, endpoint, empty_runner
from emergent.wire.axis.surface.codecs import immediate_factory
from emergent.wire.axis.surface.triggers.cli import CLITrigger
from emergent.wire.compile.targets import cli

from examples.cross_compile.store import get_state


# ─── Responses ──────────────────────────────────────────────────────────────


@dataclass
class StateResponse:
    """Storage state as JSON."""
    data: dict[str, dict[str, str]]

    def __str__(self) -> str:
        if not self.data:
            return "Storage is empty."
        return json.dumps(self.data, indent=2, ensure_ascii=False)


# ─── Application ────────────────────────────────────────────────────────────


app = Application().mount(
    endpoint(empty_runner()).expose(
        CLITrigger("state", "Show storage state"),
        immediate_factory(lambda: StateResponse(data=get_state())),
    ),
)


# ─── Compile ────────────────────────────────────────────────────────────────


cli_parser = cli.compile(app, prog="emergent-cli")


if __name__ == "__main__":
    cli.cli_run(cli_parser)

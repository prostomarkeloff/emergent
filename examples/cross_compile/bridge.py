"""Cross-compile FastAPI notes app to CLI.

Demonstrates bridge capabilities:
1. WrapAsDelegate - preserves handler signature
2. IsolateGlobal - symbol rewriting (replaces _notes with wire KV storage)
3. AddTrigger - adds CLI triggers for cross-compilation

Run:
    python -m examples.cross_compile notes-list
    python -m examples.cross_compile notes-create "Hello" "World"
    python -m examples.cross_compile state
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from emergent.wire.bridge import (
    AddTrigger,
    WrapAsDelegate,
    IsolateGlobal,
)
from emergent.wire.bridge.bridgers import fastapi
from emergent.wire.bridge._core import ExtractedHandler
from emergent.wire.axis.surface import endpoint, empty_runner
from emergent.wire.axis.surface.codecs import immediate_factory
from emergent.wire.axis.surface.triggers.cli import CLITrigger
from emergent.wire.compile.targets import cli

from examples.cross_compile.legacy_fastapi.app import app as fastapi_app
from examples.cross_compile.store import create_notes, get_state


# ─── State Command ──────────────────────────────────────────────────────────


@dataclass
class StateResponse:
    """Storage state as JSON."""
    data: dict[str, dict[str, str]]

    def __str__(self) -> str:
        if not self.data:
            return "Storage is empty."
        return json.dumps(self.data, indent=2, ensure_ascii=False)


# ─── CLI Trigger Builder ────────────────────────────────────────────────────


def build_cli_trigger(handler: ExtractedHandler[object, ..., object]) -> CLITrigger:
    """Build CLI trigger from extracted handler."""
    name = handler.name or "unknown"

    # Convert snake_case to kebab-case: list_notes → notes-list
    parts = name.split("_")
    if len(parts) == 2:
        cli_name = f"{parts[1]}-{parts[0]}"
    else:
        cli_name = name.replace("_", "-")

    return CLITrigger(command=cli_name, description=handler.description or f"Execute {name}")


# ─── Bridge FastAPI → Wire Application ──────────────────────────────────────


wire_app = fastapi.extract(
    fastapi_app,
    capabilities=(
        # Wrap handlers as DelegateCodec (preserves FastAPI signature)
        WrapAsDelegate(),

        # Symbol rewriting: replace legacy `_notes` dict with wire KV storage
        # IsolateGlobal is a Purifier - wraps each handler:
        #   1. Before: setattr(module, "_notes", create_notes())
        #   2. Call handler (uses injected KV-backed storage)
        #   3. After: restore original _notes
        # FileStorage persists to disk, so data survives across CLI calls
        IsolateGlobal(
            module_path="examples.cross_compile.legacy_fastapi.app",
            attr_name="_notes",
            factory=create_notes,
        ),

        # Add CLI triggers for cross-compilation
        AddTrigger(
            trigger_type=CLITrigger,
            builder=build_cli_trigger,
        ),
    ),
)


# ─── Add Native Commands ────────────────────────────────────────────────────


wire_app = wire_app.mount(
    endpoint(empty_runner()).expose(
        CLITrigger("state", "Show storage state"),
        immediate_factory(lambda: StateResponse(data=get_state())),
    ),
)


# ─── Compile to CLI ─────────────────────────────────────────────────────────


cli_parser = cli.compile(wire_app, prog="notes-cli")


if __name__ == "__main__":
    cli.cli_run(cli_parser)

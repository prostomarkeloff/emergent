"""Base types for bridgers — cross-compilation support.

AddTrigger capability enables cross-compilation:
- Extract from FastAPI → add CLI triggers → compile to CLI
- Extract from Django → add Telegram triggers → compile to Telegram bot

    from emergent.wire.bridge.bridgers import fastapi
    from emergent.wire.bridge.bridgers._base import AddTrigger

    wire_app = build_application(
        app,
        capabilities=(
            AddTrigger(
                CLITrigger,
                builder=lambda e: CLITrigger(e.name.replace("/", "_")),
            ),
        ),
    )

    # Compile to BOTH targets
    fastapi_app = compile.fastapi(wire_app)  # Uses HTTPRouteTrigger
    cli_app = compile.cli(wire_app)          # Uses CLITrigger
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from emergent.wire.bridge._capabilities import BridgeCapability, BridgeContext

if TYPE_CHECKING:
    from emergent.wire.bridge._types import Extracted, RouteData


@dataclass(frozen=True, slots=True)
class AddTrigger(BridgeCapability):
    """Add additional trigger for cross-compilation.

    Enables compiling the same handler to multiple targets.
    Each compiler scans for its trigger type — adding triggers
    makes the handler visible to more compilers.

    Example::

        from emergent.wire.axis.surface.triggers.cli import CLITrigger

        # FastAPI → CLI
        wire_app = build_application(
            app,
            capabilities=(
                AddTrigger(
                    trigger_type=CLITrigger,
                    builder=lambda e: CLITrigger(
                        name=e.name.replace("/", "-").strip("-"),
                        description=e.description,
                    ),
                ),
            ),
        )

        # Now both work:
        fastapi_app = compile.fastapi(wire_app)  # Original HTTP triggers
        cli_app = compile.cli(wire_app)          # Added CLI triggers

    Note:
        AddTrigger stores (trigger_type, builder) in wire.additional_triggers.
        The build_application() function reads these and creates multiple
        exposures per endpoint.
    """

    trigger_type: type
    builder: Callable[[Extracted[RouteData]], object]

    def compile_bridge[T, **P, R](
        self, ctx: BridgeContext[T, P, R]
    ) -> BridgeContext[T, P, R]:
        """Add trigger to additional_triggers list."""
        new_wire = replace(
            ctx.wire,
            additional_triggers=(
                *ctx.wire.additional_triggers,
                (self.trigger_type, self.builder),
            ),
        )
        return replace(ctx, wire=new_wire)


__all__ = ("AddTrigger",)

"""Unified extraction — like _execute.py for compile.

Sources just provide the pieces, extraction logic is unified.
Capabilities set codec/op_type/op_handler — extraction just passes through.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from emergent.wire.bridge._capabilities import (
    AnyHandler,
    BridgeCapability,
    BridgeContext,
    apply_bridge_capabilities,
    apply_purifiers,
)
from emergent.wire.bridge._core import BridgeAxes, ExtractedHandler

if TYPE_CHECKING:
    from emergent.wire.axis.surface.capabilities._base import SurfaceCapability


def extract_handler_unified[T, **P, R](
    trigger_data: T,
    handler: AnyHandler[P, R],
    axes: BridgeAxes,
    capabilities: Sequence[BridgeCapability] = (),
    extra_surface_caps: Sequence[SurfaceCapability] = (),
) -> ExtractedHandler[T, P, R] | None:
    """Unified handler extraction — sources just call this.

    Like execute_rrc_unified() — does all the work.
    Capabilities are self-contained — they set codec/op_type/op_handler.

    Args:
        trigger_data: Source-specific trigger data.
        handler: Original handler callable.
        axes: Extraction axes with inspector.
        capabilities: Bridge capabilities to apply.
        extra_surface_caps: Additional surface capabilities to add.

    Returns:
        ExtractedHandler or None if skipped.
    """
    # 1. Inspect handler
    request_type = axes.inspector.request_type(handler)
    response_type = axes.inspector.response_type(handler)

    # 2. Build initial context
    ctx: BridgeContext[T, P, R] = BridgeContext(
        trigger_data=trigger_data,
        handler=handler,
        request_type=request_type,
        response_type=response_type,
        name=getattr(handler, "__name__", None),
        description=getattr(handler, "__doc__", None),
        surface_capabilities=tuple(extra_surface_caps),
    )

    # 3. Apply BridgeCompilable capabilities (set codec/op_type/op_handler)
    ctx = apply_bridge_capabilities(ctx, capabilities)
    if ctx.skip:
        return None

    # 4. Apply Purifier capabilities to handler
    wrapped_handler = apply_purifiers(ctx.handler, capabilities)

    # 5. Return extracted handler — capabilities already set everything
    return ExtractedHandler(
        trigger_data=ctx.trigger_data,
        handler=wrapped_handler,
        codec=ctx.codec,
        op_type=ctx.op_type,
        op_handler=ctx.op_handler,
        name=ctx.name,
        description=ctx.description,
        deprecated=ctx.deprecated,
        surface_capabilities=ctx.surface_capabilities,
    )


__all__ = ("extract_handler_unified",)

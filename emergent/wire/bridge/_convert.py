"""Convert extracted handlers to wire Application.

Thin layer — just collects what capabilities set and assembles.
Does NOT know about specific capabilities.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from emergent.wire.bridge._core import ExtractedHandler, TriggerBuilder

if TYPE_CHECKING:
    from emergent.ops._graph import Runner
    from emergent.wire.axis.surface._app import Application


def to_application[T, **P, R](
    handlers: Sequence[ExtractedHandler[T, P, R]],
    runner: Runner,
    trigger_builder: TriggerBuilder[T],
) -> Application:
    """Convert handlers to wire Application.

    Thin layer:
    1. Collect op_type/op_handler from handlers
    2. Build runner with collected ops
    3. Create endpoints with codecs from handlers

    Args:
        handlers: Extracted handlers to convert.
        runner: Base runner (fallback if no ops collected).
        trigger_builder: Builder for converting trigger data to wire Trigger.

    Returns:
        Wire Application with endpoints.
    """
    from emergent.ops import ops
    from emergent.wire.axis.surface._app import application
    from emergent.wire.axis.surface._endpoint import endpoint

    app = application()

    # 1. Collect op_type/op_handler pairs
    ops_builder = ops()
    has_ops = False
    for h in handlers:
        if h.op_type is not None and h.op_handler is not None:
            ops_builder = ops_builder.on(h.op_type, h.op_handler)
            has_ops = True

    # 2. Build runner
    final_runner = ops_builder.compile() if has_ops else runner

    # 3. Create endpoints (skip handlers without codec)
    for h in handlers:
        if h.codec is None:
            continue

        trigger = trigger_builder.build(h.trigger_data)
        ep = endpoint(final_runner).expose(
            trigger,
            h.codec,
            *h.surface_capabilities,
        )
        app = app.mount(ep)

    return app


__all__ = ("to_application",)

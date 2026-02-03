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
    1. Warn if handlers have op_type (dynamic registration not supported)
    2. Create endpoints with codecs from handlers

    Args:
        handlers: Extracted handlers to convert.
        runner: Runner for endpoint execution.
        trigger_builder: Builder for converting trigger data to wire Trigger.

    Returns:
        Wire Application with endpoints.

    Warns:
        When handlers have op_type set (not supported).
        When handlers are skipped due to missing codec.
    """
    import warnings

    from emergent.wire.axis.surface._app import application
    from emergent.wire.axis.surface._endpoint import endpoint

    app = application()

    # 1. Check for handlers with op_type/op_handler (not yet supported)
    # Runner is already compiled, so we can't add new ops dynamically.
    # This is a design placeholder for future extensibility.
    handlers_with_ops = [h for h in handlers if h.wire.op_type is not None]
    if handlers_with_ops:
        names = [h.name for h in handlers_with_ops if h.name][:3]
        names_info = f" ({', '.join(names)})" if names else ""
        warnings.warn(
            f"{len(handlers_with_ops)} handler(s) have op_type set{names_info}, "
            f"but dynamic op registration is not supported. "
            f"Use OpsBuilder to register ops before compiling to Runner.",
            stacklevel=2,
        )

    # 2. Create endpoints (warn about handlers without codec)
    skipped_count = 0
    skipped_names: list[str] = []
    for h in handlers:
        if h.wire.codec is None:
            skipped_count += 1
            if h.name:
                skipped_names.append(h.name)
            continue

        # Primary trigger
        trigger = trigger_builder.build(h.trigger_data)
        ep = endpoint(runner).expose(
            trigger,
            h.wire.codec,
            *h.wire.surface_capabilities,
        )

        # Additional triggers for cross-compilation
        for _trigger_type, builder in h.wire.additional_triggers:
            additional_trigger = builder(h)
            ep = ep.expose(
                additional_trigger,
                h.wire.codec,
                *h.wire.surface_capabilities,
            )

        app = app.mount(ep)

    # 3. Warn about skipped handlers
    if skipped_count > 0:
        names_info = f" ({', '.join(skipped_names[:5])}{'...' if len(skipped_names) > 5 else ''})" if skipped_names else ""
        warnings.warn(
            f"{skipped_count} handler(s) skipped due to missing codec{names_info}. "
            f"Use WrapAsDelegate or another codec-setting capability.",
            stacklevel=2,
        )

    return app


__all__ = ("to_application",)

"""Build Application from framework source — main entry point.

    from emergent.wire.bridge import build_application

    # Auto-detect framework
    wire_app = build_application(fastapi_app)

    # With capabilities
    wire_app = build_application(
        fastapi_app,
        capabilities=(
            InferFromFastAPI(),
            MapDepends({get_db: test_db_factory}),
        ),
    )

    # With custom registry
    from emergent.wire.bridge._registry import get_default_registry
    my_registry = get_default_registry().with_bridger(DJANGO_BRIDGER)
    wire_app = build_application(django_app, registry=my_registry)

Symmetric to compile:
    fastapi_app = fastapi_compile(wire_app, axes)  # compile
    wire_app = build_application(fastapi_app)      # bridge
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, TYPE_CHECKING

from emergent.wire.bridge._axes import BridgeAxes
from emergent.wire.bridge._capabilities import (
    BridgeCapability,
    BridgeCapabilityHandler,
    BridgeContext,
    apply_bridge_capabilities,
    apply_purifiers,
)
from emergent.wire.bridge._core import WireData
from emergent.wire.bridge._registry import BridgeRegistry
from emergent.wire.bridge._types import Extracted, RouteData

if TYPE_CHECKING:
    from emergent.wire.axis.surface._app import Application
    from emergent.wire.axis.surface._endpoint import Endpoint


# ═══════════════════════════════════════════════════════════════════════════════
# BridgeContext Builder
# ═══════════════════════════════════════════════════════════════════════════════


def _extracted_to_context[R: RouteData](
    extracted: Extracted[R],
) -> BridgeContext[R, ..., Any]:
    """Convert Extracted to BridgeContext for capability processing."""
    return BridgeContext(
        trigger_data=extracted.route,
        handler=extracted.handler,
        request_type=None,
        response_type=None,
        name=extracted.name,
        description=extracted.description,
        deprecated=extracted.deprecated,
        wire=WireData(),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Main Entry Point
# ═══════════════════════════════════════════════════════════════════════════════


def build_application(
    source: Any,
    capabilities: Sequence[BridgeCapability] = (),
    *,
    axes: BridgeAxes | None = None,
    registry: BridgeRegistry | None = None,
    handlers: Mapping[type[BridgeCapability], BridgeCapabilityHandler] | None = None,
) -> Application:
    """Convert framework source to wire Application.

    Symmetric to compile:
        fastapi_app = fastapi_compile(wire_app, axes)  # compile
        wire_app = build_application(fastapi_app)      # bridge

    Args:
        source: Framework application (FastAPI, Django, etc.).
        capabilities: Bridge capabilities to apply.
        axes: Optional BridgeAxes for customization.
        registry: Optional BridgeRegistry override (takes precedence over axes.registry).
        handlers: Optional custom capability handlers for fold_bridge.

    Returns:
        Wire Application with extracted endpoints.
    """
    from emergent.wire.axis.surface import application, empty_runner, endpoint
    from emergent.wire.bridge._registry import get_default_registry

    # 1. Resolve axes
    if axes is None:
        axes = BridgeAxes.default()

    # 2. Resolve registry: explicit param > axes.registry > default
    _registry = registry or axes.registry
    if _registry is None:
        _registry = get_default_registry()

    # 3. Detect framework
    bridger = _registry.detect(source)
    if bridger is None:
        msg = f"No bridger found for source type {type(source).__name__}"
        raise ValueError(msg)

    extractors = bridger.extractor
    to_wire = bridger.to_wire

    # 4. Extract all routes
    all_extracted: list[Extracted[RouteData]] = []
    if extractors.can_extract(source):
        all_extracted = list(extractors.extract(source))

    if not all_extracted:
        return application()

    # 5. Process each extracted route
    runner = empty_runner()
    endpoints: list[Endpoint] = []

    for extracted in all_extracted:
        # 5a. Convert to BridgeContext
        ctx = _extracted_to_context(extracted)

        # 5b. Apply bridge capabilities (with custom handlers)
        ctx = apply_bridge_capabilities(ctx, capabilities, handlers)

        if ctx.skip:
            continue

        # 5c. Apply purifiers to handler
        purified_handler = apply_purifiers(ctx.handler, capabilities)

        # 5d. Convert to wire primitives
        trigger = to_wire.to_trigger(extracted.route)

        # Use codec from wire data or build from ToWire
        codec = ctx.wire.codec
        if codec is None:
            codec = to_wire.to_codec(extracted.route, purified_handler)

        # 5e. Build endpoint
        ep = endpoint(runner).expose(
            trigger,
            codec,
            *ctx.wire.surface_capabilities,
        )

        # 5f. Add additional triggers for cross-compilation
        for _trigger_type, builder in ctx.wire.additional_triggers:
            additional_trigger = builder(extracted)
            ep = ep.expose(
                additional_trigger,
                codec,
                *ctx.wire.surface_capabilities,
            )

        endpoints.append(ep)

    # 6. Build application
    wire_app = application()
    for ep in endpoints:
        wire_app = wire_app.mount(ep)

    return wire_app


__all__ = ("build_application",)

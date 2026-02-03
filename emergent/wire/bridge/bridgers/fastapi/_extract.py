"""FastAPI extraction — extract FastAPI app to wire Application.

    from emergent.wire.bridge.bridgers import fastapi

    wire_app = fastapi.extract(legacy_app)
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from emergent.wire.bridge._capabilities import (
    BridgeCapability,
    BridgeContext,
    apply_bridge_capabilities,
    apply_purifiers,
)
from emergent.wire.bridge._core import WireData
from emergent.wire.bridge.bridgers.fastapi._capabilities import MapDepends
from emergent.wire.bridge.bridgers.fastapi._scanner import (
    FastAPIAppProtocol,
    FastAPIInspector,
)
from emergent.wire.bridge.bridgers.fastapi._triggers import FastAPITriggerData

from emergent.wire.axis.surface.codecs.delegate import DelegateCodec

if TYPE_CHECKING:
    from emergent.wire.axis.surface._app import Application
    from emergent.wire.axis.surface._endpoint import Endpoint
    from emergent.wire.axis.surface.capabilities import SurfaceCapability


def extract(
    app: FastAPIAppProtocol,
    capabilities: Sequence[BridgeCapability] = (),
    *,
    warn_unextracted: bool = True,
) -> Application:
    """Extract FastAPI app to wire Application.

    Extracts ALL aspects:
    - HTTP routes -> HTTPRouteTrigger x DelegateCodec
    - WebSocket routes -> WebSocketTrigger x DelegateCodec
    - Lifecycle -> StartupTrigger/ShutdownTrigger x DelegateCodec
    - Exception handlers -> ExceptionTrigger x DelegateCodec
    - Middleware -> Application.capabilities (as MiddlewareWrapper)

    Args:
        app: FastAPI application instance.
        capabilities: Bridge capabilities to apply to HTTP routes.
        warn_unextracted: Warn about features that couldn't be extracted.

    Returns:
        Wire Application with all extracted exposures.

    Example::

        from emergent.wire.bridge.bridgers import fastapi

        wire_app = fastapi.extract(legacy_fastapi_app)

        # Compile to any target
        from emergent.wire.compile.targets import fastapi as fastapi_target
        new_fastapi = fastapi_target.compile(wire_app)
    """
    import warnings

    from emergent.wire.axis.surface import (
        ExceptionTrigger,
        ShutdownTrigger,
        StartupTrigger,
        WebSocketTrigger,
        application,
        empty_runner,
        endpoint,
    )
    from emergent.wire.axis.surface.codecs.delegate import delegate
    from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger

    try:
        from fastapi.routing import APIRoute
    except ImportError as e:
        msg = "fastapi required for FastAPI bridge: pip install fastapi"
        raise ImportError(msg) from e

    # WebSocketRoute may not be available in older FastAPI versions
    try:
        from starlette.routing import WebSocketRoute
    except ImportError:
        WebSocketRoute = None  # type: ignore[misc, assignment]

    # Collect mapped depends from capabilities
    mapped_depends: set[object] = set()
    for cap in capabilities:
        if isinstance(cap, MapDepends):
            mapped_depends.update(cap.depends_map.keys())
            mapped_depends.update(cap.scope_map.keys())

    inspector = FastAPIInspector()
    runner = empty_runner()

    # Collect all endpoints
    endpoints: list[Endpoint] = []

    # --- HTTP Routes ---
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue

        # Warn about unhandled Depends()
        depends_params = inspector.get_depends_params(route.endpoint)
        for param_name, dep_func in depends_params:
            if dep_func not in mapped_depends and warn_unextracted:
                handler_name = getattr(route.endpoint, "__name__", "handler")
                warnings.warn(
                    f"Handler '{handler_name}' has Depends() param '{param_name}' "
                    f"that is not mapped. Use MapDepends capability.",
                    stacklevel=2,
                )

        # Extract for each method
        methods = route.methods or {"GET"}
        for method in methods:
            # Create bridge context for capability pipeline
            route_deprecated: bool = getattr(route, "deprecated", False) or False
            trigger_data: FastAPITriggerData = {
                "method": method,
                "path": route.path,
                "name": getattr(route, "name", None),
                "tags": list(getattr(route, "tags", [])),
                "deprecated": route_deprecated,
            }

            ctx: BridgeContext[FastAPITriggerData, ..., object] = BridgeContext(
                trigger_data=trigger_data,
                handler=route.endpoint,
                request_type=inspector.request_type(route.endpoint),
                response_type=inspector.response_type(route.endpoint),
                name=getattr(route.endpoint, "__name__", None),
                description=getattr(route.endpoint, "__doc__", None),
                deprecated=route_deprecated,
                wire=WireData(),
            )

            # Apply bridge capabilities (including AddTrigger, WrapAsDelegate, etc.)
            ctx = apply_bridge_capabilities(ctx, capabilities)

            # Skip if marked
            if ctx.skip:
                continue

            # Apply purifiers to handler
            purified_handler = apply_purifiers(ctx.handler, capabilities)

            # Create primary trigger
            trigger = HTTPRouteTrigger(
                method=method,  # type: ignore[arg-type]
                path=route.path,
            )

            # Build endpoint with codec from wire data (or default delegate)
            codec = ctx.wire.codec
            if codec is None:
                codec = delegate(purified_handler, response=ctx.response_type)
            elif isinstance(codec, DelegateCodec):
                # Replace handler with purified version
                codec = delegate(purified_handler, response=codec.response)

            ep = endpoint(runner).expose(
                trigger,
                codec,
                *ctx.wire.surface_capabilities,
            )

            # Add additional triggers for cross-compilation
            for _trigger_type, builder in ctx.wire.additional_triggers:
                # Create ExtractedHandler for builder
                from emergent.wire.bridge._core import ExtractedHandler
                extracted: ExtractedHandler[FastAPITriggerData, ..., object] = ExtractedHandler(
                    trigger_data=trigger_data,
                    handler=purified_handler,
                    name=ctx.name,
                    description=ctx.description,
                    wire=ctx.wire,
                )
                additional_trigger = builder(extracted)
                ep = ep.expose(
                    additional_trigger,
                    codec,
                    *ctx.wire.surface_capabilities,
                )

            endpoints.append(ep)

    # --- WebSocket Routes ---
    if WebSocketRoute is not None:
        for route in app.routes:
            if not isinstance(route, WebSocketRoute):
                continue

            ws_path: str = getattr(route, "path", "")
            ws_name: str | None = getattr(route, "name", None)
            ws_endpoint = getattr(route, "endpoint", None)

            if ws_endpoint is not None:
                ws_trigger = WebSocketTrigger(path=ws_path, name=ws_name)
                ws_ep = endpoint(runner).expose(ws_trigger, delegate(ws_endpoint))
                endpoints.append(ws_ep)

    # --- Lifecycle ---
    for i, handler in enumerate(app.router.on_startup):
        startup_trigger = StartupTrigger(order=i)
        startup_ep = endpoint(runner).expose(startup_trigger, delegate(handler))
        endpoints.append(startup_ep)

    for i, handler in enumerate(app.router.on_shutdown):
        shutdown_trigger = ShutdownTrigger(order=i)
        shutdown_ep = endpoint(runner).expose(shutdown_trigger, delegate(handler))
        endpoints.append(shutdown_ep)

    # --- Exception Handlers ---
    for exc_type, handler in app.exception_handlers.items():
        # Skip non-exception types and starlette defaults
        if not isinstance(exc_type, type) or not issubclass(exc_type, Exception):
            continue
        if exc_type.__module__.startswith("starlette"):
            continue

        exc_trigger = ExceptionTrigger(exception_type=exc_type)
        exc_ep = endpoint(runner).expose(exc_trigger, delegate(handler))
        endpoints.append(exc_ep)

    # --- Middleware -> Application.capabilities ---
    app_capabilities: list[SurfaceCapability] = []
    if app.user_middleware and warn_unextracted:
        warnings.warn(
            f"{len(app.user_middleware)} middleware found. "
            f"Middleware extraction requires manual mapping.",
            stacklevel=2,
        )

    # Build application
    wire_app = application(capabilities=tuple(app_capabilities))
    for ep in endpoints:
        wire_app = wire_app.mount(ep)

    return wire_app


__all__ = ("extract",)

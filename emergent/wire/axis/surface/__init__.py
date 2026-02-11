"""Surface axis — API surface composition.

Where endpoints live. The visible boundary between
internal domain logic and external clients.

    from emergent.wire.axis import surface
    from emergent.wire.axis.surface import capabilities as C

    # Primitives
    app = surface.application()
    endpoint = surface.endpoint(runner)
    stack = surface.app_stack().root(app).mount("sub", other_app)

    # Scan
    pairs = surface.scan(app, HTTPRouteTrigger)

    # Codecs (how to execute)
    from emergent.wire.axis.surface import codecs
    codec = codecs.rrc(Request, Response)

    # Triggers (where to attach)
    from emergent.wire.axis.surface import triggers
    trigger = triggers.http.HTTPRouteTrigger("GET", "/users")

    # Capabilities (modifiers) — all behavior via capabilities
    endpoint = surface.endpoint(runner).expose(
        trigger,
        codec,
        C.enricher.Provide(type=AuthUser, ...),  # auth
        C.enricher.Timeout(seconds=5.0),         # timeout
    )
"""

from emergent.wire.axis.surface._endpoint import Endpoint, endpoint
from emergent.wire.axis.surface._app import Application, application
from emergent.wire.axis.surface._stack import AppStack, app_stack
from emergent.wire.axis.surface._handler import Handler
from emergent.wire.axis.surface._scan import scan, scan_endpoint, scan_stack, StackView
from emergent.wire.axis.surface._types import Trigger, Codec, Exposure

# Submodules
from emergent.wire.axis.surface import codecs, triggers, capabilities

# Re-export commonly used triggers at package level
from emergent.wire.axis.surface.triggers import (
    StartupTrigger,
    ShutdownTrigger,
    ExceptionTrigger,
    WebSocketTrigger,
)

from emergent.wire.axis.surface._explain import (
    SurfaceExplainHandler,
    application_dict,
    endpoint_dict,
    exposure_dict,
    explain_application,
    explain_endpoint,
    SURFACE_EXPLAIN,
)

# Empty runner for immediate codecs
from emergent.ops import ops as _ops, Runner as _Runner


def empty_runner() -> _Runner:
    """Create empty runner for immediate codecs.

    Example::

        endpoint(empty_runner()).expose(
            TelegrindTrigger(Command("help")),
            immediate(HelpResponse),
        )
    """
    return _ops().compile()


__all__ = (
    # Core
    "Endpoint",
    "endpoint",
    "Application",
    "application",
    "AppStack",
    "app_stack",
    "Handler",
    # Scan
    "scan",
    "scan_endpoint",
    "scan_stack",
    "StackView",
    # Types
    "Trigger",
    "Codec",
    "Exposure",
    # Common triggers (re-exported for convenience)
    "StartupTrigger",
    "ShutdownTrigger",
    "ExceptionTrigger",
    "WebSocketTrigger",
    # Submodules
    "codecs",
    "triggers",
    "capabilities",
    # Helper
    "empty_runner",
    # Explain
    "SurfaceExplainHandler",
    "application_dict",
    "endpoint_dict",
    "exposure_dict",
    "explain_application",
    "explain_endpoint",
    "SURFACE_EXPLAIN",
)

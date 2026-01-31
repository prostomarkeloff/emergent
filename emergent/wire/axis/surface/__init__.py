"""Surface axis — API surface composition.

Where endpoints live. The visible boundary between
internal domain logic and external clients.

    from emergent.wire.axis import surface

    # Primitives
    app = surface.application()
    endpoint = surface.endpoint(runner).expose(trigger, codec)
    stack = surface.app_stack().root(app).mount("sub", other_app)

    # Codecs (how to execute)
    from emergent.wire.axis.surface import codecs
    codec = codecs.rrc(Request, Response).build()

    # Triggers (where to attach)
    from emergent.wire.axis.surface import triggers
    trigger = triggers.http.HTTPRouteTrigger("GET", "/users")

    # Scope (middleware — what context to inject)
    from emergent.wire.axis.surface import scope
    auth_mw = scope.inject(AuthUser).using(runner).from_request(fn).on_reject(fn).build()

    # Capabilities (modifiers for Trigger × Codec space)
    from emergent.wire.axis.surface import capabilities as C
    C.Prefix.of("api", "v1")
    C.Tag.of("auth")
    C.Timeout.seconds(30)
"""

from emergent.wire.axis.surface._endpoint import Endpoint, endpoint
from emergent.wire.axis.surface._app import Application, application
from emergent.wire.axis.surface._stack import AppStack, app_stack
from emergent.wire._handler import Handler

# Submodules
from emergent.wire.axis.surface import codecs, triggers, scope, capabilities

__all__ = (
    "Endpoint",
    "endpoint",
    "Application",
    "application",
    "AppStack",
    "app_stack",
    "Handler",
    "codecs",
    "triggers",
    "scope",
    "capabilities",
)

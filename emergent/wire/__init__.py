"""
Wire — expose ops via triggers and codecs.

    from emergent import ops as O
    from emergent.wire import endpoint, Application, inject
    from emergent.wire.triggers.http import HTTPRouteTrigger
    from emergent.wire.codecs import rrc

    # runner = O.ops() ... .compile()
    # auth_mw = inject(AuthUser).using(auth_runner).from_request(fn).on_reject(fn).build()
    # codec = rrc(Request, Response).use(auth_mw).build()
    # endp = endpoint(runner).expose(HTTPRouteTrigger("GET", "/users/{id}"), codec)
    # app = Application().mount(endp)
"""

# Core primitives from surface axis
from emergent.wire.axis.surface._endpoint import (
    Endpoint,
    endpoint,
)
from emergent.wire.axis.surface._app import Application, application
from emergent.wire.axis.surface._stack import AppStack, app_stack
from emergent.wire._handler import Handler
from emergent.wire._scan import scan, scan_endpoint, scan_stack, StackView
from emergent.wire._types import (
    Trigger,
    Codec,
    Exposure,
)

# Scope enrichment (middleware)
from emergent.wire.axis.surface.scope import (
    inject,
    Middleware,
    StatefulMiddleware,
)

# Common codecs and triggers (from surface axis)
from emergent.wire.axis.surface.codecs.rrc import RequestResponseCodec, RRCBuilder, rrc
from emergent.wire.axis.surface.triggers.http import (
    HTTPRouteTrigger,
    Method,
    Path,
    Header,
    Headers,
)
from emergent.wire.axis.surface.triggers.cli import CLITrigger

# Subpackages — codecs and triggers are aliases to surface axis
from emergent.wire.axis.surface import codecs, triggers
from emergent.wire import contrib, axis

# Axes re-exports
from emergent.wire.axis import surface, storage

__all__ = (
    # Core API
    "Endpoint",
    "endpoint",
    "Application",
    "application",
    "AppStack",
    "app_stack",
    "Handler",
    "scan",
    "scan_endpoint",
    "scan_stack",
    "StackView",
    "Trigger",
    "Codec",
    "Exposure",
    # Scope enrichment (middleware)
    "inject",
    "Middleware",
    "StatefulMiddleware",
    # Built-ins
    "RequestResponseCodec",
    "RRCBuilder",
    "rrc",
    "HTTPRouteTrigger",
    "Method",
    "Path",
    "Header",
    "Headers",
    "CLITrigger",
    # Subpackages
    "codecs",
    "triggers",
    "contrib",
    "axis",
    # Axes
    "surface",
    "storage",
)

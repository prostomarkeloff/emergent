"""
Wire — expose ops via triggers and codecs.

    from emergent import ops as O
    from emergent.wire import endpoint, Application
    from emergent.wire.triggers.http import HTTPRouteTrigger
    from emergent.wire.codecs.rrc import RequestResponseCodec

    # runner = O.ops() ... .compile()
    # endp = endpoint(runner).expose(
    #     HTTPRouteTrigger("GET", "/users/{id}"),
    #     RequestResponseCodec(Request, Response),
    # )
    # app = Application().mount(endp)
"""

from emergent.wire._endpoint import (
    Endpoint,
    endpoint,
)
from emergent.wire._app import Application, application
from emergent.wire._stack import AppStack, app_stack
from emergent.wire._handler import Handler
from emergent.wire._middleware import Middleware, middleware
from emergent.wire._scan import scan, scan_endpoint, scan_stack, StackView
from emergent.wire._types import (
    Trigger,
    Codec,
    Exposure,
)

# Common codecs and triggers
from emergent.wire.codecs.rrc import RequestResponseCodec, RRCBuilder, rrc
from emergent.wire.triggers.http import (
    HTTPRouteTrigger,
    Method,
    Path,
    Header,
    Headers,
)
from emergent.wire.triggers.cli import CLITrigger

# Subpackages
from emergent.wire import codecs, triggers, contrib

__all__ = (
    # Core API
    "Endpoint",
    "endpoint",
    "Application",
    "application",
    "AppStack",
    "app_stack",
    "Handler",
    "Middleware",
    "middleware",
    "scan",
    "scan_endpoint",
    "scan_stack",
    "StackView",
    "Trigger",
    "Codec",
    "Exposure",
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
)

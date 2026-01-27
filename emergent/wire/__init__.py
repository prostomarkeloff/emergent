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
from emergent.wire._types import (
    Trigger,
    Codec,
    Exposure,
)

# Common codecs and triggers
from emergent.wire.codecs.rrc import RequestResponseCodec
from emergent.wire.triggers.http import (
    HTTPRouteTrigger,
    Method,
    Path,
    Header,
    Headers,
)

# Subpackages
from emergent.wire import codecs, triggers, contrib

__all__ = (
    # Core API
    "Endpoint",
    "endpoint",
    "Application",
    "application",
    "Trigger",
    "Codec",
    "Exposure",
    # Built-ins
    "RequestResponseCodec",
    "HTTPRouteTrigger",
    "Method",
    "Path",
    "Header",
    "Headers",
    # Subpackages
    "codecs",
    "triggers",
    "contrib",
)

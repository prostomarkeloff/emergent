"""FastAPI bridger — extract FastAPI apps to wire Application.

    from emergent.wire.bridge.bridgers import fastapi
    from emergent.wire.bridge import extract, build_application

    # Extract specific route types
    http_routes = extract(app, fastapi.HTTPRouteData)
    ws_routes = extract(app, fastapi.WebSocketRouteData)

    # Build wire Application
    wire_app = build_application(
        app,
        capabilities=(
            fastapi.InferFromFastAPI(),
            fastapi.MapDepends({get_db: test_db}),
        ),
    )

DESIGN PRINCIPLE: No hidden heuristics.
- Type inference via explicit InferFromFastAPI capability
- Composable extractors for each route type
- ToWire converts RouteData → Trigger + Codec
"""

from emergent.wire.bridge.bridgers.fastapi import _capabilities as capabilities

# Capabilities
from emergent.wire.bridge.bridgers.fastapi._capabilities import (
    DEFAULT_INFERENCE,
    InferFromFastAPI,
    MapDepends,
    ParsedParam,
    parse_fastapi_handler,
)

# Route types
from emergent.wire.bridge.bridgers.fastapi._routes import (
    ExceptionHandlerData,
    HTTPRouteData,
    LifespanData,
    MiddlewareData,
    WebSocketRouteData,
)

# Extractors
from emergent.wire.bridge.bridgers.fastapi._extractors import (
    FASTAPI_EXTRACTORS,
    ExceptionHandlerExtractor,
    HTTPRouteExtractor,
    LifespanExtractor,
    MountedAppExtractor,
    WebSocketExtractor,
    create_fastapi_extractors,
    is_fastapi_app,
)

# ToWire
from emergent.wire.bridge.bridgers.fastapi._to_wire import (
    FASTAPI_TO_WIRE,
    ExceptionHandlerToWire,
    HTTPToWire,
    LifespanToWire,
    WebSocketToWire,
)

# FrameworkBridger — open-world bundle
from emergent.wire.bridge._registry import FrameworkBridger

FASTAPI_BRIDGER = FrameworkBridger(
    name="fastapi",
    can_bridge=is_fastapi_app,
    extractor=FASTAPI_EXTRACTORS,
    to_wire=FASTAPI_TO_WIRE,
)

__all__ = (
    # Capabilities module
    "capabilities",
    # Inference capabilities
    "InferFromFastAPI",
    "DEFAULT_INFERENCE",
    "MapDepends",
    # Introspection
    "ParsedParam",
    "parse_fastapi_handler",
    # Route types
    "HTTPRouteData",
    "WebSocketRouteData",
    "LifespanData",
    "ExceptionHandlerData",
    "MiddlewareData",
    # Detection
    "is_fastapi_app",
    # Extractors
    "HTTPRouteExtractor",
    "WebSocketExtractor",
    "LifespanExtractor",
    "ExceptionHandlerExtractor",
    "MountedAppExtractor",
    "create_fastapi_extractors",
    "FASTAPI_EXTRACTORS",
    # ToWire
    "HTTPToWire",
    "WebSocketToWire",
    "LifespanToWire",
    "ExceptionHandlerToWire",
    "FASTAPI_TO_WIRE",
    # Open-world bridger bundle
    "FrameworkBridger",
    "FASTAPI_BRIDGER",
)

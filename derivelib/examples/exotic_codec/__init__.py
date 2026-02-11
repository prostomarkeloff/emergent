"""Exotic codec stress test — custom codec + compiler + derivation, zero wire changes.

Proves wire's open-world extensibility: define a new codec, extend the
FastAPI compiler, build a derivelib pattern. All in userland.

THREE codecs in ONE application:
  - ServerSentEventsCodec (custom) — stream entities as SSE events
  - RequestResponseCodec (standard) — create entities via JSON
  - ImmediateFactoryCodec (standard) — static health endpoint

    uv run python -m derivelib.examples.exotic_codec

    curl -X POST http://localhost:8000/sensors -H 'Content-Type: application/json' \
         -d '{"name": "temp-1", "location": "lab", "value": 23.5, "unit": "C"}'
    curl -N http://localhost:8000/sensors/stream
    curl http://localhost:8000/sensors/health
"""

from .codec import ServerSentEventsCodec
from .codec import sse as sse
from .execute import execute_sse, execute_sse_unified
from .compiler import SSE_COMPILER, wrap_sse_fastapi, serialize_entity, format_sse_stream
from .pattern import EventStreamAPI, StreamAPITriggers, STREAM, CREATE
from .app import Sensor, app, fastapi_app

__all__ = (
    # Codec (type carrier)
    "ServerSentEventsCodec",
    "sse",
    # Execution (unified pipeline)
    "execute_sse",
    "execute_sse_unified",
    # Compiler (thin adapter + serialization)
    "SSE_COMPILER",
    "wrap_sse_fastapi",
    "serialize_entity",
    "format_sse_stream",
    # Pattern
    "EventStreamAPI",
    "StreamAPITriggers",
    "STREAM",
    "CREATE",
    # Application
    "Sensor",
    "app",
    "fastapi_app",
)

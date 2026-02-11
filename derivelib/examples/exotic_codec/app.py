"""Application — sensor monitoring with 3 codec types.

Domain:
  - Sensor: id, name, location, value, unit

Endpoints:
  GET  /sensors/stream → SSE event stream (ServerSentEventsCodec)
  POST /sensors        → create sensor (RequestResponseCodec)
  GET  /sensors/health → health check (ImmediateFactoryCodec)

    uv run python -m derivelib.examples.exotic_codec
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from nodnod import scalar_node

from emergent.wire.axis.query import MutatingRelationalProvider, SequenceNextId
from emergent.wire.axis.query.providers.memory import MemoryRelationalProvider
from emergent.wire.axis.schema import Identity
from emergent.wire.axis.surface import Exposure
from emergent.wire.axis.surface.codecs.immediate import immediate_factory
from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger

from derivelib import derive, build_application_from_decorated

from .compiler import SSE_COMPILER
from .pattern import EventStreamAPI


# ═══════════════════════════════════════════════════════════════════════════════
# Provider (shared instance — persists across requests)
# ═══════════════════════════════════════════════════════════════════════════════


_sensor_provider: MutatingRelationalProvider[Sensor] = MemoryRelationalProvider(
    key_fn=lambda x: x.id, next_id=SequenceNextId(),
)


@scalar_node
class Sensors:
    @classmethod
    def __compose__(cls) -> MutatingRelationalProvider[Sensor]:
        return _sensor_provider


# ═══════════════════════════════════════════════════════════════════════════════
# Health endpoint — ImmediateFactoryCodec (no runner, no ops)
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class HealthResponse:
    status: str
    entity: str
    codec: str

    @classmethod
    def produce(cls) -> HealthResponse:
        return cls(status="ok", entity="Sensor", codec="ImmediateCodec")


health_exposure = Exposure(
    trigger=HTTPRouteTrigger("GET", "/sensors/health"),
    codec=immediate_factory(HealthResponse.produce),
    capabilities=(),
)


# ═══════════════════════════════════════════════════════════════════════════════
# Entity
# ═══════════════════════════════════════════════════════════════════════════════


@derive(
    EventStreamAPI("/sensors", provider_node=Sensors),  # SSE + RRC via pattern
    health_exposure,                                      # Immediate via direct exposure
)
@dataclass
class Sensor:
    id: Annotated[int, Identity]
    name: str
    location: str
    value: float
    unit: str


# ═══════════════════════════════════════════════════════════════════════════════
# Build
# ═══════════════════════════════════════════════════════════════════════════════


app = build_application_from_decorated(Sensor)

from emergent.wire.compile.targets import fastapi as fastapi_target  # noqa: E402

fastapi_app = fastapi_target.compile(app, compiler=SSE_COMPILER)

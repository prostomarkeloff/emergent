"""EventStreamAPI — custom derivelib pattern using SSE codec.

Custom building blocks:
  - STREAM op with codec_factory=sse (ServerSentEventsCodec)
  - CREATE op with standard rrc (RequestResponseCodec)
  - StreamAPITriggers — custom TriggerGen routing Stream → GET /path/stream

Reuses standard derivelib infrastructure:
  - Dialect, DeriveOp, fold_derive, materialize
  - FetchMany, InsertNew handler templates
  - entity_response(), non_id() projections
  - compose.Node provider resolution

    from derivelib.examples.exotic_codec.pattern import EventStreamAPI

    @derive(EventStreamAPI("/sensors", provider_node=Sensors))
    @dataclass
    class Sensor: ...
"""

from __future__ import annotations

from dataclasses import dataclass
from derivelib._derivation import Derivation

from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger, Method

from typing import Any as _Any

from derivelib import (
    dialect,
    DerivationEffect, Read, Creates,
    no_fields, non_id, entity_response,
    FetchMany, InsertNew,
)
from derivelib._dialect import Op
from derivelib.patterns.crud import CRUD_ERROR_CAPS

from .codec import sse


# ═══════════════════════════════════════════════════════════════════════════════
# Custom Effect — user-defined, nothing special vs built-in Read/Mutation
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Streams(DerivationEffect):
    """SSE streaming effect. User-defined — same mechanism as built-in effects."""


# ═══════════════════════════════════════════════════════════════════════════════
# Codec factory wrapper — adapts sse to match Op's codec_factory signature
# ═══════════════════════════════════════════════════════════════════════════════


def _sse_codec_factory(request: type, event_type: type) -> _Any:
    """Wrapper adapting sse to Op's codec_factory signature.

    Op's codec_factory is typed as Callable[[type, type], Exposure] in derivelib,
    but this is a type error in the derivelib core. The actual usage in
    _opspec.py line 109 shows it returns a Codec (object), which is then wrapped
    in Exposure at line 110-111.

    We use Any for return type because no alternative exists:
    1. The derivelib type annotation says Exposure, actual usage is Codec (object)
    2. Can't return Exposure (sse returns ServerSentEventsCodec[EventT], not Exposure)
    3. Can't return object (type checker rejects object as not assignable to Exposure)
    4. ServerSentEventsCodec[EventT] has partially unknown EventT from `type` parameter
    5. Can't use cast() or type: ignore (forbidden by project rules)

    At runtime: sse returns ServerSentEventsCodec, which is treated as Codec (object),
    then wrapped in Exposure by build_from_spec. This is correct runtime behavior.
    The type system can't express this without fixing derivelib's Op.codec_factory type.
    """
    # Call sse and immediately return as Any to avoid partially unknown warnings
    # sse() returns ServerSentEventsCodec[EventT] where EventT comes from event_type: type
    # Since type doesn't carry runtime type info, pyright sees EventT as Unknown
    # The Any return type makes this acceptable
    from emergent.wire.axis.surface.codecs.rrc import ToDomain
    from emergent.ops._graph import Op as DomainOp

    req_typed: type[ToDomain[DomainOp[object, object]]] = request
    event_typed: _Any = event_type  # Use Any to avoid Unknown propagation
    codec_result: _Any = sse(req_typed, event_typed)
    return codec_result


# ═══════════════════════════════════════════════════════════════════════════════
# Custom TriggerGen
# ═══════════════════════════════════════════════════════════════════════════════


_REST_ROUTES: dict[str, tuple[Method, bool]] = {
    "List": ("GET", False),
    "Get": ("GET", True),
    "Create": ("POST", False),
    "Update": ("PUT", True),
    "Delete": ("DELETE", True),
}


@dataclass(frozen=True, slots=True)
class StreamAPITriggers:
    """Trigger gen: Stream → GET /path/stream, rest → standard REST.

    Implements TriggerGen protocol: (entity, Op) → Trigger.

    Extends _REST_ROUTES with custom "Stream" mapping.
    Unknown ops fall through to POST /path/<op_name>.
    """

    base_path: str

    def __call__(self, entity: type, op: Op) -> HTTPRouteTrigger | None:
        path = self.base_path.rstrip("/")
        if op.name == "Stream":
            return HTTPRouteTrigger(method="GET", path=f"{path}/stream")
        if op.name in _REST_ROUTES:
            method, has_id = _REST_ROUTES[op.name]
            suffix = self._id_suffix(entity) if has_id else ""
            return HTTPRouteTrigger(method=method, path=path + suffix)
        return HTTPRouteTrigger(method="POST", path=f"{path}/{op.name.lower()}")

    def _id_suffix(self, entity: type) -> str:
        from emergent.wire.axis.schema import fields_with_capability
        from emergent.wire.axis.schema._universal import Identity

        id_triples = fields_with_capability(entity, Identity)
        if not id_triples:
            return "/{id}"
        return "/" + "/".join(f"{{{name}}}" for name, _, _ in id_triples)


# ═══════════════════════════════════════════════════════════════════════════════
# Custom Ops — SSE stream + RRC create
# ═══════════════════════════════════════════════════════════════════════════════


STREAM: Op = Op(
    "Stream",
    no_fields(),
    entity_response(),
    FetchMany(),
    effects=(Read(), Streams()),
    codec_factory=_sse_codec_factory,  # ← custom codec instead of rrc
)
"""SSE stream op — fetches all entities, streams as SSE events.

Uses FetchMany handler template (returns Ok(list[entity])).
codec_factory=sse makes DeriveOp create ServerSentEventsCodec
instead of RequestResponseCodec.

effects=(Read(), Streams()) — Read is built-in, Streams is user-defined.
Both dispatched identically by map_by_effect / reject_by_effect.
"""

CREATE: Op = Op(
    "Create",
    non_id(),
    entity_response(),
    InsertNew(),
    effects=(Creates(),),
)
"""Standard RRC create op — inserts entity, returns JSON response."""


# ═══════════════════════════════════════════════════════════════════════════════
# Pattern
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class EventStreamAPI:
    """Custom pattern: SSE stream + RRC create.

    Generates:
      GET  /path/stream → SSE event stream (ServerSentEventsCodec)
      POST /path        → create entity (RequestResponseCodec)

    Uses standard derivelib Dialect infrastructure:
    - inspect_entity + require_identity (preamble)
    - bind_provider + base_query (query axis)
    - DeriveOp per op (surface axis)

    The only exotic part: STREAM op has codec_factory=sse.
    Everything else is standard derivelib machinery.

    Example::

        @derive(EventStreamAPI("/sensors", provider_node=Sensors))
        @dataclass
        class Sensor:
            id: Annotated[int, Identity]
            name: str
            value: float
    """

    base_path: str
    provider_node: type

    def compile(self, entity: type) -> Derivation:
        return dialect(
            STREAM, CREATE,
            triggers=StreamAPITriggers(self.base_path),
            provider_node=self.provider_node,
            capabilities=CRUD_ERROR_CAPS,
        ).compile(entity)


__all__ = (
    "StreamAPITriggers",
    "STREAM",
    "CREATE",
    "EventStreamAPI",
)

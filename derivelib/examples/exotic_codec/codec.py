"""ServerSentEventsCodec — custom codec type.

Codec = pure type carrier. Carries request type + event entity type.
No serialization, no execution — that's the compiler's job.

Same pattern as wire's codecs:
  - RequestResponseCodec: request + response types
  - StatefulCodec: flow + key_node + response types
  - ServerSentEventsCodec: request + event_type types

    from derivelib.examples.exotic_codec.codec import sse, ServerSentEventsCodec

    STREAM = Op("Stream", ..., codec_factory=sse)
"""

from __future__ import annotations

from dataclasses import dataclass

from emergent.ops._graph import Op
from emergent.wire.axis.surface.codecs.rrc import ToDomain


@dataclass(frozen=True, slots=True)
class ServerSentEventsCodec[EventT]:
    """Server-Sent Events streaming codec.

    Type carrier only:
      - request: type implementing ToDomain[Op[object, object]] (request → domain op)
      - event_type: type of each SSE event entity

    How events are serialized (JSON, protobuf, custom) is decided
    by the compiler adapter, not the codec.
    """

    request: type[ToDomain[Op[object, object]]]
    event_type: type[EventT]


def sse[EventT](
    request: type[ToDomain[Op[object, object]]],
    event_type: type[EventT],
) -> ServerSentEventsCodec[EventT]:
    """Create SSE codec.

    Drop-in where rrc() would go. Used as codec_factory on Op:

        Op("Stream", ..., codec_factory=sse)

    DeriveOp calls codec_factory(RequestType, ResponseType).
    For SSE, ResponseType becomes event_type.

    Note: The codec_factory type annotation in Op expects Callable[[type, type], Exposure],
    but it's actually used to create a Codec which is then wrapped in Exposure by
    build_from_spec. This is a type inconsistency in the derivelib core, but at
    runtime ServerSentEventsCodec (which is a Codec = object) works correctly.
    """
    return ServerSentEventsCodec(request=request, event_type=event_type)


__all__ = (
    "ServerSentEventsCodec",
    "sse",
)

"""PubSub pattern — publish/subscribe with typed codec.

PubSub = Publish + Subscribe capabilities composed with Codec.

    events = pubsub(redis, JsonCodec[Event]())
    await events.publish("channel", event)

    async for event in events.subscribe("channel"):
        handle(event)
"""

from dataclasses import dataclass
from typing import Protocol, AsyncIterator

from kungfu import Result

from emergent.wire.axis._explain import ExplainContext, ExplainNode
from emergent.wire.axis.storage._codec import Codec
from emergent.wire.axis.storage._result import map_result
from emergent.wire.axis.storage._capabilities import (
    Publish as PublishCap,
    Subscribe as SubscribeCap,
)


# ═══════════════════════════════════════════════════════════════════════════════
# PubSub Backend — composition of capabilities
# ═══════════════════════════════════════════════════════════════════════════════


class PubSubBackend[E](
    PublishCap[str, bytes, E],
    SubscribeCap[str, bytes, E],
    Protocol,
):
    """Backend with PubSub capabilities. Publish + Subscribe."""
    ...


# ═══════════════════════════════════════════════════════════════════════════════
# PubSub Store — typed wrapper
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class PubSub[T, E]:
    """Typed publish/subscribe.

    Combines backend (capabilities) with codec (serialization).

    Example:
        events = PubSub(redis, JsonCodec[Event]())

        await events.publish("events", event)

        async for result in events.subscribe("events"):
            match result:
                case Ok(event): handle(event)
                case Error(e): log(e)
    """

    backend: PubSubBackend[E]
    codec: Codec[T]

    def compile_explain(self, ctx: ExplainContext) -> ExplainContext:
        return ctx.add(
            ExplainNode(
                "PubSub",
                (
                    ("codec", type(self.codec).__name__),
                    ("backend", type(self.backend).__name__),
                ),
            )
        )

    async def publish(self, channel: str, value: T) -> Result[None, E]:
        """Publish typed value to channel."""
        return await self.backend.publish(channel, self.codec.encode(value))

    async def subscribe(self, channel: str) -> AsyncIterator[Result[T, E]]:
        """Subscribe to channel, yields typed values."""
        async for result in self.backend.subscribe(channel):
            yield map_result(result, self.codec.decode)


def pubsub[T, E](backend: PubSubBackend[E], codec: Codec[T]) -> PubSub[T, E]:
    """Create typed pubsub."""
    return PubSub(backend, codec)


__all__ = ("PubSubBackend", "PubSub", "pubsub")

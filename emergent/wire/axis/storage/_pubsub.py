"""PubSub pattern — publish/subscribe with typed codec.

PubSub = Publish + Subscribe capabilities composed with Codec.

    events = pubsub(redis, JsonCodec[Event]())
    await events.publish("channel", event)

    async for event in events.subscribe("channel"):
        handle(event)
"""

from dataclasses import dataclass
from typing import Protocol, AsyncIterator

from kungfu import Result, Ok, Error

from emergent.wire.axis.storage._codec import Codec
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

    async def publish(self, channel: str, value: T) -> Result[None, E]:
        """Publish typed value to channel."""
        data = self.codec.encode(value)
        return await self.backend.publish(channel, data)

    async def subscribe(self, channel: str) -> AsyncIterator[Result[T, E]]:
        """Subscribe to channel, yields typed values."""
        async for result in self.backend.subscribe(channel):
            match result:
                case Ok(data):
                    yield Ok(self.codec.decode(data))
                case Error(e):
                    yield Error(e)


def pubsub[T, E](backend: PubSubBackend[E], codec: Codec[T]) -> PubSub[T, E]:
    """Create typed pubsub."""
    return PubSub(backend, codec)


__all__ = ("PubSubBackend", "PubSub", "pubsub")

"""Queue pattern — FIFO queue with typed codec.

Queue = Push + Pop capabilities composed with Codec.

    orders = queue(redis, JsonCodec[Order]())
    await orders.push(order)
    order = await orders.pop()
"""

from dataclasses import dataclass
from typing import Protocol

from kungfu import Result, Option

from emergent.wire.axis._explain import ExplainContext, ExplainNode
from emergent.wire.axis.storage._codec import Codec
from emergent.wire.axis.storage._result import map_option
from emergent.wire.axis.storage._capabilities import (
    Push as PushCap,
    Pop as PopCap,
    Peek as PeekCap,
    Len as LenCap,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Queue Backend — composition of capabilities
# ═══════════════════════════════════════════════════════════════════════════════


class QueueBackend[E](
    PushCap[bytes, E],
    PopCap[bytes, E],
    Protocol,
):
    """Backend with Queue capabilities. Push + Pop."""
    ...


class QueueBackendFull[E](
    PushCap[bytes, E],
    PopCap[bytes, E],
    PeekCap[bytes, E],
    LenCap[E],
    Protocol,
):
    """Backend with full Queue capabilities. Push + Pop + Peek + Len."""
    ...


# ═══════════════════════════════════════════════════════════════════════════════
# Queue Store — typed wrapper
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Queue[T, E]:
    """Typed FIFO queue.

    Combines backend (capabilities) with codec (serialization).

    Example:
        orders = Queue(redis, JsonCodec[Order]())

        await orders.push(order)
        match await orders.pop():
            case Ok(Some(order)): ...
            case Ok(Nothing()): ...  # empty
            case Error(e): ...
    """

    backend: QueueBackend[E]
    codec: Codec[T]

    def compile_explain(self, ctx: ExplainContext) -> ExplainContext:
        return ctx.add(
            ExplainNode(
                "Queue",
                (
                    ("codec", type(self.codec).__name__),
                    ("backend", type(self.backend).__name__),
                ),
            )
        )

    async def push(self, value: T) -> Result[None, E]:
        """Push typed value to queue."""
        return await self.backend.push(self.codec.encode(value))

    async def pop(self) -> Result[Option[T], E]:
        """Pop typed value from queue."""
        return map_option(await self.backend.pop(), self.codec.decode)


@dataclass(frozen=True, slots=True)
class QueueFull[T, E]:
    """Typed FIFO queue with peek and length.

    Like Queue but also supports peek() and length().
    """

    backend: QueueBackendFull[E]
    codec: Codec[T]

    def compile_explain(self, ctx: ExplainContext) -> ExplainContext:
        return ctx.add(
            ExplainNode(
                "QueueFull",
                (
                    ("codec", type(self.codec).__name__),
                    ("backend", type(self.backend).__name__),
                ),
            )
        )

    async def push(self, value: T) -> Result[None, E]:
        """Push typed value to queue."""
        return await self.backend.push(self.codec.encode(value))

    async def pop(self) -> Result[Option[T], E]:
        """Pop typed value from queue."""
        return map_option(await self.backend.pop(), self.codec.decode)

    async def peek(self) -> Result[Option[T], E]:
        """Peek at front without removing."""
        return map_option(await self.backend.peek(), self.codec.decode)

    async def length(self) -> Result[int, E]:
        """Get queue length."""
        return await self.backend.length()


def queue[T, E](backend: QueueBackend[E], codec: Codec[T]) -> Queue[T, E]:
    """Create typed queue."""
    return Queue(backend, codec)


def queue_full[T, E](backend: QueueBackendFull[E], codec: Codec[T]) -> QueueFull[T, E]:
    """Create typed queue with peek and length."""
    return QueueFull(backend, codec)


__all__ = ("QueueBackend", "QueueBackendFull", "Queue", "QueueFull", "queue", "queue_full")

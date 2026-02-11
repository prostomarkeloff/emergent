"""Realtime events — publish mutations to event bus.

EventBus = in-memory pub/sub (list of async callbacks)
with_events(bus) = DerivationT that wraps mutation handlers
to publish events after success.

    from examples.ultimate.realtime import EventBus, with_events

    bus = EventBus()

    @derive(
        http_crud("/items", provider_node=Items)
            .chain(with_events(bus, channel="items"))
    )
    @dataclass
    class Item: ...

    # Subscribe to events:
    @bus.on("items")
    async def handle(event):
        print(event)
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import datetime, UTC

from kungfu import Ok, Result

from typing import TYPE_CHECKING

from derivelib import (
    DerivationT, Mutation,
    HandlerSpec, WrappedTemplate,
    serialize_op_fields, map_by_effect,
)
from derivelib._ctx import OperationHandler
from derivelib._effects import DerivationEffect
from derivelib._protocols import WrapperFn
from derivelib.axes.surface import DeriveOp

if TYPE_CHECKING:
    from derivelib._errors import DomainError


# ═══════════════════════════════════════════════════════════════════════════════
# Event + EventBus — in-memory pub/sub
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Event:
    """One mutation event."""

    channel: str
    operation: str
    entity_type: str
    timestamp: str
    payload: str  # JSON


class EventBus:
    """In-memory event bus with channel-based subscriptions.

        bus = EventBus()

        @bus.on("items")
        async def handler(event: Event) -> None:
            print(event.operation, event.payload)

        # Or subscribe inline:
        bus.subscribe("items", my_handler)
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[Callable[[Event], Awaitable[None]]]] = {}
        self._all_handlers: list[Callable[[Event], Awaitable[None]]] = []
        self.history: list[Event] = []

    def subscribe(
        self,
        channel: str,
        handler: Callable[[Event], Awaitable[None]],
    ) -> None:
        self._handlers.setdefault(channel, []).append(handler)

    def on(
        self, channel: str,
    ) -> Callable[
        [Callable[[Event], Awaitable[None]]],
        Callable[[Event], Awaitable[None]],
    ]:
        """Decorator for subscribing to a channel."""

        def decorator(
            fn: Callable[[Event], Awaitable[None]],
        ) -> Callable[[Event], Awaitable[None]]:
            self.subscribe(channel, fn)
            return fn

        return decorator

    def on_all(
        self, fn: Callable[[Event], Awaitable[None]],
    ) -> Callable[[Event], Awaitable[None]]:
        """Subscribe to ALL channels."""
        self._all_handlers.append(fn)
        return fn

    async def publish(self, event: Event) -> None:
        self.history.append(event)
        for handler in self._handlers.get(event.channel, []):
            await handler(event)
        for handler in self._all_handlers:
            await handler(event)


# ═══════════════════════════════════════════════════════════════════════════════
# Handler Wrapper — publish after success
# ═══════════════════════════════════════════════════════════════════════════════


def _make_event_wrapper(
    bus: EventBus,
    channel: str,
    op_name: str,
) -> WrapperFn:
    """Wrap handler: on success, publish Event to bus."""

    def wrapper[EntityT](inner: OperationHandler[EntityT, DomainError], spec: HandlerSpec[EntityT]) -> OperationHandler[EntityT, DomainError]:
        async def handler(op: object) -> Result[EntityT, DomainError]:
            result = await inner(op)
            if isinstance(result, Ok):
                event = Event(
                    channel=channel,
                    operation=op_name,
                    entity_type=spec.entity_name,
                    timestamp=datetime.now(UTC).isoformat(),
                    payload=serialize_op_fields(op, spec.non_identity_names),
                )
                await bus.publish(event)
            return result

        return handler

    return wrapper


# ═══════════════════════════════════════════════════════════════════════════════
# with_events — DerivationT
# ═══════════════════════════════════════════════════════════════════════════════


def with_events(
    bus: EventBus,
    channel: str = "default",
) -> DerivationT:
    """Publish events on mutations. Reads pass through.

        .chain(with_events(bus, channel="articles"))
    """

    def _add(_eff: DerivationEffect, op: DeriveOp) -> DeriveOp:
        wrapped = WrappedTemplate(
            inner=op.handler_template,
            wrapper=_make_event_wrapper(bus, channel, op.name),
        )
        return replace(op, handler_template=wrapped)

    return map_by_effect({Mutation: _add})


__all__ = (
    # Event types
    "Event",
    "EventBus",
    # Transform
    "with_events",
)

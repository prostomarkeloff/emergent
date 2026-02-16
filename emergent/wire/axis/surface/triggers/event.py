"""Event trigger — handle application-level events.

    endpoint(runner).expose(
        EventTrigger(OrderCreated),
        delegate(handle_order),
    )
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

Ev = TypeVar("Ev")


@dataclass(frozen=True, slots=True)
class EventTrigger(Generic[Ev]):
    """Fires when an event of the specified type is dispatched.

    Attributes:
        event_type: Event class to handle.

    Example::

        @dataclass
        class OrderCreated:
            order_id: int
            total: float

        endpoint(runner).expose(
            EventTrigger(OrderCreated),
            rrc(OrderRequest, OrderResponse),
        )
    """

    event_type: type[Ev]


__all__ = ("EventTrigger",)

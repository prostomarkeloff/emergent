"""ToWire protocol — RouteData → Trigger + Codec.

    from emergent.wire.bridge import ToWire

    class FastAPIToWire(ToWire[HTTPRouteData]):
        def to_trigger(self, route: HTTPRouteData) -> Trigger:
            return HTTPRouteTrigger(route.method, route.path)

        def to_codec(self, route: HTTPRouteData, handler: Callable) -> Codec:
            return delegate(handler, response=route.response_type)

Converts framework-specific route data to wire primitives.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from emergent.wire.bridge._types import RouteData

if TYPE_CHECKING:
    from emergent.wire.axis.surface._types import Codec, Trigger


# ═══════════════════════════════════════════════════════════════════════════════
# ToWire Protocol
# ═══════════════════════════════════════════════════════════════════════════════


@runtime_checkable
class ToWire[R_contra: RouteData](Protocol):
    """Protocol for converting RouteData to wire Trigger + Codec.

    Each framework implements this for its route types.
    Type parameter R_contra is contravariant — accepts RouteData or subtypes.

    Example::

        class FastAPIToWire:
            def to_trigger(self, route: HTTPRouteData) -> Trigger:
                return HTTPRouteTrigger(route.method, route.path)

            def to_codec(
                self, route: HTTPRouteData, handler: Callable
            ) -> Codec:
                return delegate(handler, response=route.response_type)
    """

    def to_trigger(self, route: R_contra) -> Trigger:
        """Convert route data to wire Trigger."""
        ...

    def to_codec(self, route: R_contra, handler: Callable[..., object]) -> Codec:
        """Convert route data + handler to wire Codec."""
        ...


# ═══════════════════════════════════════════════════════════════════════════════
# Composition
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class ComposedToWire:
    """Composed ToWire — tries converters in order."""

    converters: tuple[tuple[type, object], ...]  # (route_type, converter)

    def to_trigger(self, route: RouteData) -> Trigger:
        """Find matching converter and convert to Trigger."""
        for route_type, converter in self.converters:
            if isinstance(route, route_type):
                return converter.to_trigger(route)  # type: ignore[union-attr]
        msg = f"No ToWire converter for route type {type(route).__name__}"
        raise TypeError(msg)

    def to_codec(self, route: RouteData, handler: Callable[..., object]) -> Codec:
        """Find matching converter and convert to Codec."""
        for route_type, converter in self.converters:
            if isinstance(route, route_type):
                return converter.to_codec(route, handler)  # type: ignore[union-attr]
        msg = f"No ToWire converter for route type {type(route).__name__}"
        raise TypeError(msg)


def compose_to_wire(
    *converters: tuple[type, object],
) -> ToWire[RouteData]:
    """Compose multiple ToWire converters.

    Each converter handles specific route types.
    Runtime dispatch based on route type.

    Example::

        combined = compose_to_wire(
            (HTTPRouteData, HTTPToWire()),
            (WebSocketRouteData, WebSocketToWire()),
            (LifespanData, LifespanToWire()),
        )

        # Use combined
        trigger = combined.to_trigger(http_route)  # HTTPRouteTrigger
        trigger = combined.to_trigger(ws_route)    # WebSocketTrigger
    """
    return ComposedToWire(converters=converters)


__all__ = (
    "ToWire",
    "ComposedToWire",
    "compose_to_wire",
)

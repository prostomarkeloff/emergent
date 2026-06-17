"""FastAPI ToWire — convert route data to wire Trigger + Codec.

    from emergent.wire.bridge.bridgers.fastapi import FASTAPI_TO_WIRE

    trigger = FASTAPI_TO_WIRE.to_trigger(http_route)
    codec = FASTAPI_TO_WIRE.to_codec(http_route, handler)
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

from emergent.wire.axis.surface.triggers.http import Method
from emergent.wire.bridge._to_wire import ToWire, compose_to_wire
from emergent.wire.bridge._types import RouteData
from emergent.wire.bridge.bridgers.fastapi._routes import (
    ExceptionHandlerData,
    HTTPRouteData,
    LifespanData,
    WebSocketRouteData,
)

if TYPE_CHECKING:
    from emergent.wire.axis.surface._types import Codec, Trigger


def _as_method(method: str) -> Method:
    """Narrow a raw HTTP method string to the Method literal.

    FastAPI/Starlette routes carry methods as plain strings; the wire
    HTTPRouteTrigger requires a Method literal. Validate at the boundary and
    fail explicitly on an unsupported verb rather than silently widening.
    Each branch returns the literal directly so the result type is exactly Method.
    """
    upper = method.upper()
    if upper == "GET":
        return "GET"
    if upper == "POST":
        return "POST"
    if upper == "PUT":
        return "PUT"
    if upper == "DELETE":
        return "DELETE"
    if upper == "PATCH":
        return "PATCH"
    msg = f"Unsupported HTTP method: {method!r}"
    raise ValueError(msg)


# ═══════════════════════════════════════════════════════════════════════════════
# HTTP ToWire
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class HTTPToWire:
    """Convert HTTPRouteData to wire Trigger + Codec."""

    def to_trigger(self, route: HTTPRouteData) -> Trigger:
        """Convert to HTTPRouteTrigger."""
        from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger

        return HTTPRouteTrigger(
            method=_as_method(route.method),
            path=route.path,
        )

    def to_codec(
        self, route: HTTPRouteData, handler: Callable[..., Any]
    ) -> Codec:
        """Convert to delegate codec."""
        from emergent.wire.axis.surface.codecs.delegate import delegate

        return delegate(handler, response=route.response_model)


# ═══════════════════════════════════════════════════════════════════════════════
# WebSocket ToWire
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class WebSocketToWire:
    """Convert WebSocketRouteData to wire Trigger + Codec."""

    def to_trigger(self, route: WebSocketRouteData) -> Trigger:
        """Convert to WebSocketTrigger."""
        from emergent.wire.axis.surface import WebSocketTrigger

        return WebSocketTrigger(path=route.path, name=route.name)

    def to_codec(
        self, route: WebSocketRouteData, handler: Callable[..., Any]
    ) -> Codec:
        """Convert to delegate codec."""
        from emergent.wire.axis.surface.codecs.delegate import delegate

        return delegate(handler)


# ═══════════════════════════════════════════════════════════════════════════════
# Lifespan ToWire
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class LifespanToWire:
    """Convert LifespanData to wire Trigger + Codec."""

    def to_trigger(self, route: LifespanData) -> Trigger:
        """Convert to StartupTrigger or ShutdownTrigger."""
        from emergent.wire.axis.surface import ShutdownTrigger, StartupTrigger

        if route.kind == "startup":
            return StartupTrigger(order=route.order)
        elif route.kind == "shutdown":
            return ShutdownTrigger(order=route.order)
        else:
            msg = f"Unknown lifespan kind: {route.kind}"
            raise ValueError(msg)

    def to_codec(
        self, route: LifespanData, handler: Callable[..., Any]
    ) -> Codec:
        """Convert to delegate codec."""
        from emergent.wire.axis.surface.codecs.delegate import delegate

        return delegate(handler)


# ═══════════════════════════════════════════════════════════════════════════════
# Exception Handler ToWire
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class ExceptionHandlerToWire:
    """Convert ExceptionHandlerData to wire Trigger + Codec."""

    def to_trigger(self, route: ExceptionHandlerData) -> Trigger:
        """Convert to ExceptionTrigger."""
        from emergent.wire.axis.surface import ExceptionTrigger

        return ExceptionTrigger(exception_type=route.exception_type)

    def to_codec(
        self, route: ExceptionHandlerData, handler: Callable[..., Any]
    ) -> Codec:
        """Convert to delegate codec."""
        from emergent.wire.axis.surface.codecs.delegate import delegate

        return delegate(handler)


# ═══════════════════════════════════════════════════════════════════════════════
# Composed FastAPI ToWire
# ═══════════════════════════════════════════════════════════════════════════════


FASTAPI_TO_WIRE: ToWire[RouteData] = compose_to_wire(
    (HTTPRouteData, HTTPToWire()),
    (WebSocketRouteData, WebSocketToWire()),
    (LifespanData, LifespanToWire()),
    (ExceptionHandlerData, ExceptionHandlerToWire()),
)


__all__ = (
    # Individual converters
    "HTTPToWire",
    "WebSocketToWire",
    "LifespanToWire",
    "ExceptionHandlerToWire",
    # Composed
    "FASTAPI_TO_WIRE",
)

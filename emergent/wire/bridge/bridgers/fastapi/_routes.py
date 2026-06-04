"""FastAPI route data types — like Trigger in surface axis.

    from emergent.wire.bridge.bridgers.fastapi import (
        HTTPRouteData,
        WebSocketRouteData,
        LifespanData,
        ExceptionHandlerData,
    )

Each type captures framework-specific route information.
"""

from __future__ import annotations

from typing import Any

from dataclasses import dataclass, field


# ═══════════════════════════════════════════════════════════════════════════════
# HTTP Route
# ═══════════════════════════════════════════════════════════════════════════════


def _empty_tags() -> tuple[str, ...]:
    return ()


@dataclass(frozen=True, slots=True)
class HTTPRouteData:
    """HTTP route data extracted from FastAPI.

    Captures all route metadata from FastAPI/Starlette.

    Attributes:
        method: HTTP method (GET, POST, etc.).
        path: URL path pattern.
        name: Route name (for reverse URL lookup).
        tags: OpenAPI tags.
        deprecated: Deprecation flag.
        response_model: Response model class if specified.
        status_code: HTTP status code.
        operation_id: OpenAPI operation ID.
        summary: OpenAPI summary.
        description: OpenAPI description.
    """

    method: str
    path: str
    name: str | None = None
    tags: tuple[str, ...] = field(default_factory=_empty_tags)
    deprecated: bool = False
    response_model: type | None = None
    status_code: int = 200
    operation_id: str | None = None
    summary: str | None = None
    description: str | None = None


# ═══════════════════════════════════════════════════════════════════════════════
# WebSocket Route
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class WebSocketRouteData:
    """WebSocket route data extracted from FastAPI.

    Attributes:
        path: URL path pattern.
        name: Route name.
    """

    path: str
    name: str | None = None


# ═══════════════════════════════════════════════════════════════════════════════
# Lifespan/Lifecycle
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class LifespanData:
    """Lifecycle event data (startup/shutdown).

    Attributes:
        kind: Event type — "startup" or "shutdown".
        order: Execution order (lower = earlier).
    """

    kind: str  # "startup" | "shutdown"
    order: int = 0


# ═══════════════════════════════════════════════════════════════════════════════
# Exception Handler
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class ExceptionHandlerData:
    """Exception handler data.

    Attributes:
        exception_type: Exception class this handler catches.
    """

    exception_type: type[Exception]


# ═══════════════════════════════════════════════════════════════════════════════
# Middleware (for documentation, not directly extracted as routes)
# ═══════════════════════════════════════════════════════════════════════════════


def _empty_options() -> dict[str, Any]:
    return {}


@dataclass(frozen=True, slots=True)
class MiddlewareData:
    """Middleware data (informational).

    Middleware is converted to Application.capabilities, not routes.
    This type is for documentation/introspection.

    Attributes:
        middleware_class: Middleware class.
        options: Middleware options dict.
    """

    middleware_class: type
    options: dict[str, object] = field(default_factory=_empty_options)


__all__ = (
    "HTTPRouteData",
    "WebSocketRouteData",
    "LifespanData",
    "ExceptionHandlerData",
    "MiddlewareData",
)

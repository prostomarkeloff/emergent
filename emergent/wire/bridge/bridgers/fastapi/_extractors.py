"""FastAPI extractors — extract routes from FastAPI app.

    from emergent.wire.bridge.bridgers.fastapi import (
        HTTPRouteExtractor,
        WebSocketExtractor,
        LifespanExtractor,
        FASTAPI_EXTRACTORS,
    )

Each extractor handles one route kind, composable via compose_extractors.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from emergent.wire.bridge._extractor import Extractor, compose_extractors
from emergent.wire.bridge._types import Extracted, RouteData
from emergent.wire.bridge.bridgers.fastapi._routes import (
    ExceptionHandlerData,
    HTTPRouteData,
    LifespanData,
    WebSocketRouteData,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Detection
# ═══════════════════════════════════════════════════════════════════════════════


def is_fastapi_app(source: object) -> bool:
    """Check if source is a FastAPI application."""
    # Check for FastAPI type
    type_name = type(source).__name__
    if type_name == "FastAPI":
        return True

    # Check for Starlette (FastAPI inherits from it)
    if type_name == "Starlette":
        return True

    # Check for router attribute (duck typing)
    if hasattr(source, "routes") and hasattr(source, "router"):
        return True

    return False


# ═══════════════════════════════════════════════════════════════════════════════
# HTTP Route Extractor
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class HTTPRouteExtractor:
    """Extract HTTP routes from FastAPI app.

    Handles APIRoute instances, yields one Extracted per method.
    """

    def can_extract(self, source: object) -> bool:
        """Check if source has routes we can extract."""
        return hasattr(source, "routes")

    def extract(self, source: object) -> Iterator[Extracted[RouteData]]:
        """Yield HTTPRouteData for each route/method pair."""
        try:
            from fastapi.routing import APIRoute
        except ImportError:
            return

        routes = getattr(source, "routes", [])

        for route in routes:
            if not isinstance(route, APIRoute):
                continue

            endpoint = route.endpoint
            if endpoint is None or not callable(endpoint):
                continue

            # Extract metadata
            name = getattr(route, "name", None)
            tags = tuple(getattr(route, "tags", []))
            deprecated = getattr(route, "deprecated", False) or False
            response_model = getattr(route, "response_model", None)
            status_code = getattr(route, "status_code", 200)
            operation_id = getattr(route, "operation_id", None)
            summary = getattr(route, "summary", None)
            description = getattr(route, "description", None)

            # Yield one Extracted per method
            methods = route.methods or {"GET"}
            for method in methods:
                route_data = HTTPRouteData(
                    method=method,
                    path=route.path,
                    name=name,
                    tags=tags,
                    deprecated=deprecated,
                    response_model=response_model,
                    status_code=status_code,
                    operation_id=operation_id,
                    summary=summary,
                    description=description,
                )

                yield Extracted(
                    route=route_data,
                    handler=endpoint,
                    name=getattr(endpoint, "__name__", name),
                    description=getattr(endpoint, "__doc__", description),
                    deprecated=deprecated,
                )


# ═══════════════════════════════════════════════════════════════════════════════
# WebSocket Extractor
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class WebSocketExtractor:
    """Extract WebSocket routes from FastAPI app."""

    def can_extract(self, source: object) -> bool:
        """Check if source has routes."""
        return hasattr(source, "routes")

    def extract(self, source: object) -> Iterator[Extracted[RouteData]]:
        """Yield WebSocketRouteData for each WebSocket route."""
        try:
            from starlette.routing import WebSocketRoute
        except ImportError:
            return

        routes = getattr(source, "routes", [])

        for route in routes:
            if not isinstance(route, WebSocketRoute):
                continue

            endpoint = getattr(route, "endpoint", None)
            if endpoint is None or not callable(endpoint):
                continue

            path = getattr(route, "path", "")
            name = getattr(route, "name", None)

            route_data = WebSocketRouteData(
                path=path,
                name=name,
            )

            yield Extracted(
                route=route_data,
                handler=endpoint,
                name=getattr(endpoint, "__name__", name),
                description=getattr(endpoint, "__doc__", None),
            )


# ═══════════════════════════════════════════════════════════════════════════════
# Lifespan Extractor
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class LifespanExtractor:
    """Extract lifecycle handlers (startup/shutdown) from FastAPI app."""

    def can_extract(self, source: object) -> bool:
        """Check if source has router with lifecycle hooks."""
        router = getattr(source, "router", None)
        if router is None:
            return False
        return hasattr(router, "on_startup") or hasattr(router, "on_shutdown")

    def extract(self, source: object) -> Iterator[Extracted[RouteData]]:
        """Yield LifespanData for each startup/shutdown handler."""
        router = getattr(source, "router", None)
        if router is None:
            return

        # Startup handlers
        on_startup = getattr(router, "on_startup", [])
        for i, handler in enumerate(on_startup):
            if not callable(handler):
                continue

            route_data = LifespanData(kind="startup", order=i)

            yield Extracted(
                route=route_data,
                handler=handler,
                name=getattr(handler, "__name__", f"startup_{i}"),
                description=getattr(handler, "__doc__", None),
            )

        # Shutdown handlers
        on_shutdown = getattr(router, "on_shutdown", [])
        for i, handler in enumerate(on_shutdown):
            if not callable(handler):
                continue

            route_data = LifespanData(kind="shutdown", order=i)

            yield Extracted(
                route=route_data,
                handler=handler,
                name=getattr(handler, "__name__", f"shutdown_{i}"),
                description=getattr(handler, "__doc__", None),
            )


# ═══════════════════════════════════════════════════════════════════════════════
# Exception Handler Extractor
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class ExceptionHandlerExtractor:
    """Extract exception handlers from FastAPI app."""

    # Skip Starlette's default handlers
    skip_modules: tuple[str, ...] = ("starlette.",)

    def can_extract(self, source: object) -> bool:
        """Check if source has exception handlers."""
        return hasattr(source, "exception_handlers")

    def extract(self, source: object) -> Iterator[Extracted[RouteData]]:
        """Yield ExceptionHandlerData for each exception handler."""
        handlers = getattr(source, "exception_handlers", {})

        for exc_type, handler in handlers.items():
            # Skip non-exception types
            if not isinstance(exc_type, type) or not issubclass(exc_type, Exception):
                continue

            # Skip framework defaults
            module = getattr(exc_type, "__module__", "")
            if any(module.startswith(skip) for skip in self.skip_modules):
                continue

            if not callable(handler):
                continue

            route_data = ExceptionHandlerData(exception_type=exc_type)

            yield Extracted(
                route=route_data,
                handler=handler,
                name=getattr(handler, "__name__", f"handle_{exc_type.__name__}"),
                description=getattr(handler, "__doc__", None),
            )


# ═══════════════════════════════════════════════════════════════════════════════
# Mounted App Extractor (recursive)
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class MountedAppExtractor:
    """Extract routes from mounted sub-applications.

    Recursively extracts from Mount routes.
    """

    inner: Extractor[RouteData]

    def can_extract(self, source: object) -> bool:
        """Check if source has routes."""
        return hasattr(source, "routes")

    def extract(self, source: object) -> Iterator[Extracted[RouteData]]:
        """Yield routes from mounted apps, with path prefix."""
        try:
            from starlette.routing import Mount
        except ImportError:
            return

        routes = getattr(source, "routes", [])

        for route in routes:
            if not isinstance(route, Mount):
                continue

            # Get mounted app
            app = getattr(route, "app", None)
            if app is None:
                continue

            # Get mount path prefix
            prefix = getattr(route, "path", "")

            # Extract from inner app
            if self.inner.can_extract(app):
                for extracted in self.inner.extract(app):
                    # Prepend prefix to path if applicable
                    new_route = _prepend_path(extracted.route, prefix)
                    yield Extracted(
                        route=new_route,
                        handler=extracted.handler,
                        name=extracted.name,
                        description=extracted.description,
                        deprecated=extracted.deprecated,
                        metadata=extracted.metadata,
                    )


def _prepend_path(route: RouteData, prefix: str) -> RouteData:
    """Prepend path prefix to route using dataclass inspection."""
    import dataclasses

    # Only process dataclass instances (not classes)
    if not dataclasses.is_dataclass(route) or isinstance(route, type):
        return route

    # Check if route has 'path' field
    field_names = {f.name for f in dataclasses.fields(route)}
    if "path" not in field_names:
        return route

    current_path: str = getattr(route, "path")
    new_path = f"{prefix.rstrip('/')}/{current_path.lstrip('/')}"

    # route is a dataclass instance, safe to replace
    return dataclasses.replace(route, path=new_path)  # type: ignore[type-var]


# ═══════════════════════════════════════════════════════════════════════════════
# Composed FastAPI Extractor
# ═══════════════════════════════════════════════════════════════════════════════


def create_fastapi_extractors() -> Extractor[RouteData]:
    """Create composed extractor for all FastAPI route types.

    Includes:
    - HTTP routes
    - WebSocket routes
    - Lifespan (startup/shutdown)
    - Exception handlers
    - Mounted sub-apps (recursive)
    """
    base_extractors: Extractor[RouteData] = compose_extractors(
        HTTPRouteExtractor(),
        WebSocketExtractor(),
        LifespanExtractor(),
        ExceptionHandlerExtractor(),
    )

    # Add mounted app extractor with recursive reference
    return compose_extractors(
        base_extractors,
        MountedAppExtractor(inner=base_extractors),
    )


# Default composed extractor
FASTAPI_EXTRACTORS: Extractor[RouteData] = create_fastapi_extractors()


__all__ = (
    # Detection
    "is_fastapi_app",
    # Individual extractors
    "HTTPRouteExtractor",
    "WebSocketExtractor",
    "LifespanExtractor",
    "ExceptionHandlerExtractor",
    "MountedAppExtractor",
    # Factory
    "create_fastapi_extractors",
    # Default composed
    "FASTAPI_EXTRACTORS",
)

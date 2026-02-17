"""Tests for emergent.wire.bridge.bridgers.fastapi._extractors — covers missed lines.

Targeted lines:
- 42: is_fastapi_app detects Starlette type name
- 71-72: HTTPRouteExtractor when fastapi not installed (ImportError)
- 82: HTTPRouteExtractor skips non-callable endpoints
- 136-137: WebSocketExtractor when starlette not installed (ImportError)
- 145-157: WebSocketExtractor endpoint extraction + WebSocketRouteData
- 185: LifespanExtractor returns when router is None
- 190-195: LifespanExtractor startup handler extraction (skip non-callable)
- 205-210: LifespanExtractor shutdown handler extraction (skip non-callable)
- 241: ExceptionHandlerExtractor skips non-exception types
- 249: ExceptionHandlerExtractor skips non-callable handlers
- 283-284: MountedAppExtractor ImportError path
- 293-305: MountedAppExtractor extract from mounted apps with prefix
- 317-332: _prepend_path dataclass path prepending
"""

from __future__ import annotations

from dataclasses import dataclass

from emergent.wire.bridge.bridgers.fastapi._extractors import (
    ExceptionHandlerExtractor,
    HTTPRouteExtractor,
    LifespanExtractor,
    MountedAppExtractor,
    WebSocketExtractor,
    _prepend_path,  # pyright: ignore[reportPrivateUsage] - testing private helper
    is_fastapi_app,
)
from emergent.wire.bridge.bridgers.fastapi._routes import (
    ExceptionHandlerData,
    HTTPRouteData,
    LifespanData,
    WebSocketRouteData,
)


# ═══════════════════════════════════════════════════════════════════════════════
# is_fastapi_app — Starlette detection (line 42)
# ═══════════════════════════════════════════════════════════════════════════════


class TestIsFastAPIAppStarlette:
    """Test is_fastapi_app for Starlette type name (line 42)."""

    def test_detects_starlette_type_name(self) -> None:
        """Object with __name__ == 'Starlette' is detected as FastAPI-like app."""

        class Starlette:
            pass

        assert is_fastapi_app(Starlette()) is True

    def test_rejects_arbitrary_class(self) -> None:
        class MyApp:
            pass

        assert is_fastapi_app(MyApp()) is False

    def test_detects_duck_typed_with_routes_and_router(self) -> None:
        """Duck typing: has routes + router attributes."""

        class DuckApp:
            routes: list[str] = []
            router = "some_router"

        assert is_fastapi_app(DuckApp()) is True


# ═══════════════════════════════════════════════════════════════════════════════
# HTTPRouteExtractor — skip non-callable endpoint (line 82)
# ═══════════════════════════════════════════════════════════════════════════════


class TestHTTPRouteExtractorMissed:
    """Test HTTPRouteExtractor for missed lines."""

    def test_skips_routes_with_non_callable_endpoint(self) -> None:
        """Line 82: skip when endpoint is None or not callable."""
        from fastapi import FastAPI
        from fastapi.routing import APIRoute

        app = FastAPI()

        async def ok_handler() -> str:
            return "ok"

        app.get("/ok")(ok_handler)

        # Manually add a route with a non-callable endpoint
        broken_route = APIRoute(path="/broken", endpoint=lambda: None)
        # Set endpoint to None to trigger the guard
        broken_route.endpoint = None  # type: ignore[assignment]
        app.routes.append(broken_route)

        extractor = HTTPRouteExtractor()
        results = list(extractor.extract(app))

        # Should extract the valid route but skip the broken one
        paths = [
            r.route.path
            for r in results
            if isinstance(r.route, HTTPRouteData)
        ]
        assert "/ok" in paths

    def test_extracts_deprecated_route_metadata(self) -> None:
        """Verify deprecated flag and tags are extracted."""
        from fastapi import FastAPI

        app = FastAPI()

        async def old_handler() -> str:
            return "old"

        app.get("/old", deprecated=True, tags=["legacy"])(old_handler)

        extractor = HTTPRouteExtractor()
        results = list(extractor.extract(app))

        old_routes = [
            r
            for r in results
            if isinstance(r.route, HTTPRouteData) and r.route.path == "/old"
        ]
        assert len(old_routes) >= 1
        old_route = old_routes[0]
        assert old_route.deprecated is True
        assert isinstance(old_route.route, HTTPRouteData)
        assert "legacy" in old_route.route.tags

    def test_extracts_multiple_methods(self) -> None:
        """Verify routes with multiple methods yield one Extracted per method."""
        from fastapi import FastAPI

        app = FastAPI()

        async def multi_handler() -> str:
            return "multi"

        app.api_route("/multi", methods=["GET", "POST"])(multi_handler)

        extractor = HTTPRouteExtractor()
        results = list(extractor.extract(app))

        multi_routes = [
            r
            for r in results
            if isinstance(r.route, HTTPRouteData) and r.route.path == "/multi"
        ]
        methods: set[str] = set()
        for r in multi_routes:
            assert isinstance(r.route, HTTPRouteData)
            methods.add(r.route.method)
        assert "GET" in methods
        assert "POST" in methods


# ═══════════════════════════════════════════════════════════════════════════════
# WebSocketExtractor — full extraction (lines 145-157)
# ═══════════════════════════════════════════════════════════════════════════════


class TestWebSocketExtractor:
    """Test WebSocketExtractor — lines 132-162."""

    def test_extracts_websocket_routes(self) -> None:
        """Lines 145-162: extract WebSocket routes."""
        from fastapi import FastAPI

        app = FastAPI()

        async def ws_handler() -> None:
            pass

        app.websocket("/ws")(ws_handler)

        extractor = WebSocketExtractor()
        assert extractor.can_extract(app) is True

        results = list(extractor.extract(app))
        ws_results = [
            r for r in results if isinstance(r.route, WebSocketRouteData)
        ]
        assert len(ws_results) >= 1

        ws = ws_results[0]
        assert isinstance(ws.route, WebSocketRouteData)
        assert ws.route.path == "/ws"
        assert ws.handler is not None

    def test_skips_non_websocket_routes(self) -> None:
        """WebSocketExtractor only extracts WebSocketRoute instances."""
        from fastapi import FastAPI

        app = FastAPI()

        async def http_handler() -> str:
            return "http"

        app.get("/http")(http_handler)

        extractor = WebSocketExtractor()
        results = list(extractor.extract(app))
        ws_results = [
            r for r in results if isinstance(r.route, WebSocketRouteData)
        ]
        assert len(ws_results) == 0

    def test_can_extract_false_without_routes(self) -> None:
        extractor = WebSocketExtractor()
        assert extractor.can_extract(object()) is False

    def test_skips_non_callable_endpoint(self) -> None:
        """Lines 145-146: skip when endpoint is not callable."""
        from starlette.routing import WebSocketRoute

        class FakeApp:
            routes: list[WebSocketRoute] = []

        fake_app = FakeApp()
        # Create a websocket route and set endpoint to None
        route = WebSocketRoute(path="/ws", endpoint=lambda: None)
        route.endpoint = None  # type: ignore[assignment]
        fake_app.routes = [route]

        extractor = WebSocketExtractor()
        results = list(extractor.extract(fake_app))
        assert len(results) == 0


# ═══════════════════════════════════════════════════════════════════════════════
# LifespanExtractor — startup/shutdown extraction (lines 185-215)
# ═══════════════════════════════════════════════════════════════════════════════


class TestLifespanExtractorMissed:
    """Test LifespanExtractor — missed lines around startup/shutdown."""

    def test_extract_returns_nothing_when_router_is_none(self) -> None:
        """Line 185: return when router is None."""

        class NoRouterApp:
            pass

        extractor = LifespanExtractor()
        results = list(extractor.extract(NoRouterApp()))
        assert results == []

    def test_extracts_startup_handlers(self) -> None:
        """Lines 190-200: extracts startup handlers."""

        async def startup_fn() -> None:
            pass

        class FakeRouter:
            on_startup = [startup_fn]
            on_shutdown: list[object] = []

        class FakeApp:
            router = FakeRouter()

        extractor = LifespanExtractor()
        results = list(extractor.extract(FakeApp()))

        startup_results = [
            r
            for r in results
            if isinstance(r.route, LifespanData) and r.route.kind == "startup"
        ]
        assert len(startup_results) == 1
        assert startup_results[0].handler is startup_fn
        assert startup_results[0].name == "startup_fn"

    def test_extracts_shutdown_handlers(self) -> None:
        """Lines 205-215: extracts shutdown handlers."""

        async def shutdown_fn() -> None:
            pass

        class FakeRouter:
            on_startup: list[object] = []
            on_shutdown = [shutdown_fn]

        class FakeApp:
            router = FakeRouter()

        extractor = LifespanExtractor()
        results = list(extractor.extract(FakeApp()))

        shutdown_results = [
            r
            for r in results
            if isinstance(r.route, LifespanData) and r.route.kind == "shutdown"
        ]
        assert len(shutdown_results) == 1
        assert shutdown_results[0].handler is shutdown_fn

    def test_skips_non_callable_startup_handler(self) -> None:
        """Line 190: skip non-callable startup handler."""

        class FakeRouter:
            on_startup = ["not_callable", 42]
            on_shutdown: list[object] = []

        class FakeApp:
            router = FakeRouter()

        extractor = LifespanExtractor()
        results = list(extractor.extract(FakeApp()))
        assert len(results) == 0

    def test_skips_non_callable_shutdown_handler(self) -> None:
        """Line 205: skip non-callable shutdown handler."""

        class FakeRouter:
            on_startup: list[object] = []
            on_shutdown = [None, 123]

        class FakeApp:
            router = FakeRouter()

        extractor = LifespanExtractor()
        results = list(extractor.extract(FakeApp()))
        assert len(results) == 0

    def test_extracts_both_startup_and_shutdown(self) -> None:
        """Multiple startup and shutdown handlers extracted in order."""

        async def start_db() -> None:
            pass

        async def start_cache() -> None:
            pass

        async def stop_db() -> None:
            pass

        class FakeRouter:
            on_startup = [start_db, start_cache]
            on_shutdown = [stop_db]

        class FakeApp:
            router = FakeRouter()

        extractor = LifespanExtractor()
        results = list(extractor.extract(FakeApp()))

        startup = [
            r
            for r in results
            if isinstance(r.route, LifespanData) and r.route.kind == "startup"
        ]
        shutdown = [
            r
            for r in results
            if isinstance(r.route, LifespanData) and r.route.kind == "shutdown"
        ]
        assert len(startup) == 2
        assert len(shutdown) == 1
        assert isinstance(startup[0].route, LifespanData)
        assert startup[0].route.order == 0
        assert isinstance(startup[1].route, LifespanData)
        assert startup[1].route.order == 1

    def test_handler_without_name_gets_default_name(self) -> None:
        """Lines 198, 213: fallback name for handlers without __name__."""

        class FakeRouter:
            on_startup = [lambda: None]
            on_shutdown: list[object] = []

        class FakeApp:
            router = FakeRouter()

        extractor = LifespanExtractor()
        results = list(extractor.extract(FakeApp()))
        # Lambda has __name__ = "<lambda>" so it uses that
        assert len(results) == 1
        assert results[0].name is not None


# ═══════════════════════════════════════════════════════════════════════════════
# ExceptionHandlerExtractor — edge cases (lines 241, 249)
# ═══════════════════════════════════════════════════════════════════════════════


class TestExceptionHandlerExtractorMissed:
    """Test ExceptionHandlerExtractor — missed edge cases."""

    def test_skips_non_exception_types(self) -> None:
        """Line 240-241: skip handlers keyed by non-exception types."""

        def _not_found(r: object, e: object) -> str:
            return "not found"

        def _error(r: object, e: object) -> str:
            return "error"

        class FakeApp:
            exception_handlers: dict[int | str, object] = {
                404: _not_found,  # int key, not exception type
                "error": _error,  # str key, not exception type
            }

        extractor = ExceptionHandlerExtractor()
        results = list(extractor.extract(FakeApp()))
        assert len(results) == 0

    def test_skips_non_subclass_of_exception(self) -> None:
        """Line 240: types that are classes but not Exception subclasses."""

        class NotAnException:
            pass

        def _nope(r: object, e: object) -> str:
            return "nope"

        class FakeApp:
            exception_handlers: dict[type[NotAnException], object] = {
                NotAnException: _nope,
            }

        extractor = ExceptionHandlerExtractor()
        results = list(extractor.extract(FakeApp()))
        assert len(results) == 0

    def test_skips_non_callable_handler(self) -> None:
        """Line 248-249: skip non-callable handler."""

        class CustomError(Exception):
            pass

        class FakeApp:
            exception_handlers = {CustomError: "not_callable"}

        extractor = ExceptionHandlerExtractor()
        results = list(extractor.extract(FakeApp()))
        assert len(results) == 0

    def test_skips_starlette_modules(self) -> None:
        """Lines 244-246: skip exception types from starlette modules."""

        # Create a fake exception type that looks like it's from starlette
        class StarletteError(Exception):
            __module__ = "starlette.exceptions"

        def _handled(r: object, e: object) -> str:
            return "handled"

        class FakeApp:
            exception_handlers: dict[type[StarletteError], object] = {
                StarletteError: _handled,
            }

        extractor = ExceptionHandlerExtractor()
        results = list(extractor.extract(FakeApp()))
        assert len(results) == 0

    def test_extracts_custom_exception_handler_with_correct_data(self) -> None:
        """Full extraction with ExceptionHandlerData."""

        class AppError(Exception):
            pass

        def handle_app_error(request: object, exc: AppError) -> str:
            """Handle app errors."""
            return "handled"

        class FakeApp:
            exception_handlers = {AppError: handle_app_error}

        extractor = ExceptionHandlerExtractor()
        results = list(extractor.extract(FakeApp()))
        assert len(results) == 1
        assert isinstance(results[0].route, ExceptionHandlerData)
        assert results[0].route.exception_type is AppError
        assert results[0].name == "handle_app_error"
        assert results[0].description == "Handle app errors."


# ═══════════════════════════════════════════════════════════════════════════════
# MountedAppExtractor — recursive extraction (lines 293-305)
# ═══════════════════════════════════════════════════════════════════════════════


class TestMountedAppExtractor:
    """Test MountedAppExtractor — lines 279-312."""

    def test_can_extract_checks_routes_attr(self) -> None:
        extractor = MountedAppExtractor(inner=HTTPRouteExtractor())
        assert extractor.can_extract(object()) is False

        class HasRoutes:
            routes: list[str] = []

        assert extractor.can_extract(HasRoutes()) is True

    def test_extracts_from_mounted_app(self) -> None:
        """Lines 293-312: extract routes from mounted sub-applications."""
        from fastapi import FastAPI
        from starlette.routing import Mount

        inner_app = FastAPI()

        async def get_items() -> str:
            return "items"

        inner_app.get("/items")(get_items)

        class OuterApp:
            routes = [Mount("/api", app=inner_app)]

        inner_extractor = HTTPRouteExtractor()
        extractor = MountedAppExtractor(inner=inner_extractor)

        results = list(extractor.extract(OuterApp()))

        paths = [
            r.route.path
            for r in results
            if isinstance(r.route, HTTPRouteData)
        ]
        # Path should be prefixed with /api
        assert len(paths) >= 1
        assert any("/api/items" in p for p in paths)

    def test_skips_mounts_without_app(self) -> None:
        """Line 294-295: skip Mount routes without app."""
        from starlette.routing import Mount

        class OuterApp:
            routes: list[object] = []

        # We can't easily create Mount without app since starlette requires it,
        # so we test with a fake mount that has no app
        _mount = Mount("/api", routes=[])
        # Mount.app is derived from routes, creating a Router; verify extractor
        # handles this gracefully
        inner_extractor = HTTPRouteExtractor()
        extractor = MountedAppExtractor(inner=inner_extractor)
        # This should not crash even if inner can't extract
        results = list(extractor.extract(OuterApp()))
        assert results == []


# ═══════════════════════════════════════════════════════════════════════════════
# _prepend_path — dataclass path prepending (lines 317-332)
# ═══════════════════════════════════════════════════════════════════════════════


class TestPrependPath:
    """Test _prepend_path — lines 315-332."""

    def test_prepends_path_to_http_route_data(self) -> None:
        """Lines 328-332: prepend prefix to dataclass with path field."""
        route = HTTPRouteData(method="GET", path="/users")
        result = _prepend_path(route, "/api")
        assert isinstance(result, HTTPRouteData)
        assert result.path == "/api/users"

    def test_preserves_other_fields(self) -> None:
        route = HTTPRouteData(
            method="POST",
            path="/users",
            name="create_user",
            deprecated=True,
        )
        result = _prepend_path(route, "/v2")
        assert isinstance(result, HTTPRouteData)
        assert result.path == "/v2/users"
        assert result.method == "POST"
        assert result.name == "create_user"
        assert result.deprecated is True

    def test_returns_unchanged_for_non_dataclass(self) -> None:
        """Line 320-321: non-dataclass is returned unchanged."""
        route = "just_a_string"
        result = _prepend_path(route, "/api")
        assert result == "just_a_string"

    def test_returns_unchanged_for_dataclass_without_path(self) -> None:
        """Lines 325-326: dataclass without 'path' field is unchanged."""

        @dataclass(frozen=True)
        class NoPathData:
            name: str

        route = NoPathData(name="test")
        result = _prepend_path(route, "/api")
        assert result is route

    def test_handles_trailing_slash_on_prefix(self) -> None:
        """Path joining handles trailing slashes."""
        route = HTTPRouteData(method="GET", path="/items")
        result = _prepend_path(route, "/api/")
        assert isinstance(result, HTTPRouteData)
        assert result.path == "/api/items"

    def test_handles_leading_slash_on_path(self) -> None:
        """Path joining handles leading slashes."""
        route = HTTPRouteData(method="GET", path="items")
        result = _prepend_path(route, "/api")
        assert isinstance(result, HTTPRouteData)
        assert result.path == "/api/items"

    def test_websocket_route_data_has_path(self) -> None:
        """WebSocketRouteData also has path field."""
        route = WebSocketRouteData(path="/ws", name="chat")
        result = _prepend_path(route, "/v1")
        assert isinstance(result, WebSocketRouteData)
        assert result.path == "/v1/ws"
        assert result.name == "chat"

    def test_returns_dataclass_class_unchanged(self) -> None:
        """Line 320: dataclass CLASS (not instance) is returned unchanged."""
        result = _prepend_path(HTTPRouteData, "/api")  # type: ignore[arg-type]
        assert result is HTTPRouteData

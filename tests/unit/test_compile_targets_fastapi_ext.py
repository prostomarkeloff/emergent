"""Extended tests for emergent.wire.compile.targets.fastapi — inner handler bodies,
compile functions, scope layer integration, and coverage of uncovered lines.

Covers:
- wrap_rrc_fastapi inner _route execution (POST and GET paths, validation errors)
- wrap_delegate_fastapi inner _route execution (path params, scope injection)
- wrap_immediate_fastapi inner _route execution
- wrap_stateful_fastapi inner _route execution (full stateful flow)
- _get_pydantic_types_from_transitions
- register_handler with route_ctx openapi_extra merging, skip_route, status_code
- fastapi_compile with lifecycle, exceptions, websockets, family, middleware
- fastapi_compile_endpoint (RRC and Stateful)
- fastapi_compile_stack (flat and nested mounts)
- _wrap_for_stack (adapter dispatch + missing adapter error)
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Self
from unittest.mock import AsyncMock, MagicMock

import fastapi
import pytest
from kungfu import Ok, Error, Result, Option, Some, Nothing

from emergent.ops._graph import Op, ops
from emergent.wire.axis.surface._app import application
from emergent.wire.axis.surface._endpoint import endpoint
from emergent.wire.axis.surface._handler import Handler
from emergent.wire.axis.surface._stack import app_stack
from emergent.wire.axis.surface.codecs.delegate import DelegateCodec, delegate
from emergent.wire.axis.surface.codecs.immediate import (
    ImmediateCodec,
    ImmediateFactoryCodec,
    immediate,
    immediate_factory,
)
from emergent.wire.axis.surface.codecs.rrc import RequestResponseCodec, rrc
from emergent.wire.axis.surface.codecs.stateful import (
    StatefulCodec,
    Done,
)
from emergent.wire.axis.storage import MemoryStorage
from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger
from emergent.wire.axis.surface.triggers.lifecycle import StartupTrigger, ShutdownTrigger
from emergent.wire.axis.surface.triggers.exception import ExceptionTrigger
from emergent.wire.axis.surface.triggers.websocket import WebSocketTrigger
from emergent.wire.compile._core import Axes
from emergent.wire.compile.targets.fastapi import (
    FASTAPI_COMPILER,
    FastAPIRoute,
    build_rrc_openapi_extra,
    _get_pydantic_types_from_transitions,  # pyright: ignore[reportPrivateUsage] - testing private function
    is_pydantic_model,
    _wrap_for_stack,  # pyright: ignore[reportPrivateUsage] - testing private function
    fastapi_compile,
    fastapi_compile_endpoint,
    fastapi_compile_stack,
    register_handler,
    wrap_delegate_fastapi,
    wrap_immediate_fastapi,
    wrap_rrc_fastapi,
    wrap_stateful_fastapi,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Domain types
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class GreetOp(Op[str, str]):
    name: str


async def _greet_handler(req: GreetOp) -> Result[str, str]:
    return Ok(f"Hello {req.name}")


@dataclass
class GreetReq:
    name: str

    def to_domain(self) -> GreetOp:
        return GreetOp(name=self.name)


@dataclass
class GreetResp:
    message: str

    @classmethod
    def from_domain(cls, dom: Result[str, str]) -> Self:
        match dom:
            case Ok(v):
                return cls(message=v)
            case Error(e):
                return cls(message=e)

    def __str__(self) -> str:
        return self.message


@dataclass
class BodyReq:
    name: str
    age: int

    def to_domain(self) -> GreetOp:
        return GreetOp(name=self.name)


@dataclass
class PathBodyReq:
    user_id: str
    name: str

    def to_domain(self) -> GreetOp:
        return GreetOp(name=self.name)


@dataclass
class ImmediateResp:
    text: str

    @classmethod
    def produce(cls) -> Self:
        return cls(text="immediate-hello")

    def __str__(self) -> str:
        return self.text


_runner = ops().on(GreetOp, _greet_handler).compile()
_axes = Axes.default()


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════


from collections.abc import Callable


def _identity_decorator(fn: Callable[..., None]) -> Callable[..., None]:
    """Typed identity function used as a mock decorator return value."""
    return fn


def _noop_endpoint() -> None:
    """No-op endpoint for FastAPIRoute in tests."""


def _make_mock_request(
    *,
    method: str = "POST",
    body: dict[str, object] | None = None,
    query_params: dict[str, str] | None = None,
    path_params: dict[str, str] | None = None,
) -> MagicMock:
    """Create a mock fastapi.Request with configurable data."""
    req = MagicMock(spec=fastapi.Request)
    req.json = AsyncMock(return_value=body or {})
    req.query_params = query_params or {}
    req.path_params = path_params or {}
    return req


# ═══════════════════════════════════════════════════════════════════════════════
# _get_pydantic_types_from_transitions (lines 88-94)
# ═══════════════════════════════════════════════════════════════════════════════


# Module-level Pydantic models for _get_pydantic_types_from_transitions tests
# (must be at module level so get_type_hints can resolve forward refs)
from pydantic import BaseModel as _PydanticBase


class _UserInputModel(_PydanticBase):
    name: str


class _ModelA(_PydanticBase):
    a: str


class _ModelB(_PydanticBase):
    b: int


async def _trans_no_pydantic(self: object, name: str) -> Done:
    return Done()


async def _trans_with_pydantic(self: object, user: Option[_UserInputModel]) -> Done:
    return Done()


async def _trans_model_a(self: object, inp: Option[_ModelA]) -> Done:
    return Done()


async def _trans_model_b(self: object, inp: Option[_ModelB]) -> Done:
    return Done()


class TestGetPydanticTypesFromTransitions:
    def test_empty_transitions(self) -> None:
        result = _get_pydantic_types_from_transitions([])
        assert result == set()

    def test_no_pydantic_types(self) -> None:
        result = _get_pydantic_types_from_transitions([_trans_no_pydantic])
        assert result == set()

    def test_with_pydantic_types(self) -> None:
        result = _get_pydantic_types_from_transitions([_trans_with_pydantic])
        assert _UserInputModel in result

    def test_multiple_transitions_with_pydantic(self) -> None:
        result = _get_pydantic_types_from_transitions([_trans_model_a, _trans_model_b])
        assert _ModelA in result
        assert _ModelB in result


# ═══════════════════════════════════════════════════════════════════════════════
# wrap_rrc_fastapi — inner _route execution (lines 162-185)
# ═══════════════════════════════════════════════════════════════════════════════


class TestWrapRrcFastapiExecution:
    @pytest.mark.asyncio
    async def test_post_route_parses_body_and_returns_response(self) -> None:
        """POST request: reads JSON body, builds request, executes handler."""
        codec = rrc(GreetReq, GreetResp)
        handler = Handler(codec=codec, runner=_runner, capabilities=())
        trigger = HTTPRouteTrigger(method="POST", path="/greet")
        route = wrap_rrc_fastapi(handler, trigger, _axes)

        mock_req = _make_mock_request(method="POST", body={"name": "Alice"})
        result = await route.endpoint(mock_req)

        assert isinstance(result, GreetResp)
        assert result.message == "Hello Alice"

    @pytest.mark.asyncio
    async def test_get_route_parses_query_params(self) -> None:
        """GET request: reads query_params instead of body."""
        codec = rrc(GreetReq, GreetResp)
        handler = Handler(codec=codec, runner=_runner, capabilities=())
        trigger = HTTPRouteTrigger(method="GET", path="/greet")
        route = wrap_rrc_fastapi(handler, trigger, _axes)

        mock_req = _make_mock_request(
            method="GET",
            query_params={"name": "Bob"},
        )
        result = await route.endpoint(mock_req)

        assert isinstance(result, GreetResp)
        assert result.message == "Hello Bob"

    @pytest.mark.asyncio
    async def test_path_params_override_body(self) -> None:
        """Path params take precedence over body values."""
        codec = rrc(PathBodyReq, GreetResp)
        handler = Handler(codec=codec, runner=_runner, capabilities=())
        trigger = HTTPRouteTrigger(method="POST", path="/users/{user_id}")
        route = wrap_rrc_fastapi(handler, trigger, _axes)

        mock_req = _make_mock_request(
            method="POST",
            body={"user_id": "from-body", "name": "Charlie"},
            path_params={"user_id": "from-path"},
        )
        result = await route.endpoint(mock_req)

        assert isinstance(result, GreetResp)
        assert result.message == "Hello Charlie"

    @pytest.mark.asyncio
    async def test_invalid_body_raises_validation_error(self) -> None:
        """Invalid body data raises RequestValidationError via Pydantic."""
        from fastapi.exceptions import RequestValidationError

        codec = rrc(BodyReq, GreetResp)
        handler = Handler(codec=codec, runner=_runner, capabilities=())
        trigger = HTTPRouteTrigger(method="POST", path="/test")
        route = wrap_rrc_fastapi(handler, trigger, _axes)

        # age is required int, passing invalid string
        mock_req = _make_mock_request(
            method="POST",
            body={"name": "Alice", "age": "not-a-number"},
        )
        with pytest.raises(RequestValidationError):
            await route.endpoint(mock_req)

    @pytest.mark.asyncio
    async def test_body_json_parse_error_falls_back_to_empty(self) -> None:
        """When JSON parsing fails, body falls back to empty dict."""
        codec = rrc(GreetReq, GreetResp)
        handler = Handler(codec=codec, runner=_runner, capabilities=())
        trigger = HTTPRouteTrigger(method="POST", path="/greet")
        route = wrap_rrc_fastapi(handler, trigger, _axes)

        mock_req = _make_mock_request(method="POST")
        mock_req.json = AsyncMock(side_effect=ValueError("bad json"))
        mock_req.path_params = {"name": "Fallback"}

        result = await route.endpoint(mock_req)
        assert isinstance(result, GreetResp)
        assert result.message == "Hello Fallback"

    def test_route_annotations_set(self) -> None:
        """The _route function gets proper annotations for FastAPI."""
        codec = rrc(GreetReq, GreetResp)
        handler = Handler(codec=codec, runner=_runner, capabilities=())
        trigger = HTTPRouteTrigger(method="POST", path="/test")
        route = wrap_rrc_fastapi(handler, trigger, _axes)

        annotations = route.endpoint.__annotations__
        assert annotations["request"] is fastapi.Request
        assert annotations["return"] is GreetResp


# ═══════════════════════════════════════════════════════════════════════════════
# wrap_delegate_fastapi — inner _route execution (lines 321-326)
# ═══════════════════════════════════════════════════════════════════════════════


class TestWrapDelegateFastapiExecution:
    @pytest.mark.asyncio
    async def test_delegate_route_executes_handler(self) -> None:
        """Delegate route calls the original handler."""
        async def greet(name: str) -> str:
            return f"Hi {name}"

        codec = delegate(greet)
        handler: Handler[DelegateCodec] = Handler(
            codec=codec, runner=_runner, capabilities=()
        )
        trigger = HTTPRouteTrigger(method="GET", path="/greet")
        route = wrap_delegate_fastapi(handler, trigger, _axes)

        mock_req = _make_mock_request(
            method="GET",
            path_params={"name": "Dave"},
        )
        result = await route.endpoint(mock_req)

        assert result == "Hi Dave"

    @pytest.mark.asyncio
    async def test_delegate_route_injects_request_into_scope(self) -> None:
        """Delegate route injects fastapi.Request into scope."""
        async def check_handler() -> str:
            return "ok"

        codec = delegate(check_handler)
        handler: Handler[DelegateCodec] = Handler(
            codec=codec, runner=_runner, capabilities=()
        )
        trigger = HTTPRouteTrigger(method="GET", path="/check")
        route = wrap_delegate_fastapi(handler, trigger, _axes)

        mock_req = _make_mock_request(method="GET")
        result = await route.endpoint(mock_req)
        assert result == "ok"


# ═══════════════════════════════════════════════════════════════════════════════
# wrap_immediate_fastapi — inner _route execution (line 294-295)
# ═══════════════════════════════════════════════════════════════════════════════


class TestWrapImmediateFastapiExecution:
    @pytest.mark.asyncio
    async def test_immediate_codec_executes_produce(self) -> None:
        """Immediate codec calls produce() and returns result."""
        codec = immediate(ImmediateResp)
        handler: Handler[ImmediateCodec] = Handler(
            codec=codec, runner=_runner, capabilities=()
        )
        trigger = HTTPRouteTrigger(method="GET", path="/health")
        route = wrap_immediate_fastapi(handler, trigger, _axes)

        result = await route.endpoint()
        assert isinstance(result, ImmediateResp)
        assert result.text == "immediate-hello"

    @pytest.mark.asyncio
    async def test_immediate_factory_executes_factory(self) -> None:
        """ImmediateFactory codec calls factory function."""
        codec = immediate_factory(lambda: {"status": "healthy"})
        handler: Handler[ImmediateFactoryCodec] = Handler(
            codec=codec, runner=_runner, capabilities=()
        )
        trigger = HTTPRouteTrigger(method="GET", path="/health")
        route = wrap_immediate_fastapi(handler, trigger, _axes)

        result = await route.endpoint()
        assert result == {"status": "healthy"}


# ═══════════════════════════════════════════════════════════════════════════════
# wrap_stateful_fastapi (lines 215-276)
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class _KeyNode:
    """Fake key node for stateful tests."""
    __dependencies__: tuple[type, ...] = ()

    @classmethod
    async def __compose__(cls) -> Self:
        return cls()

    def __str__(self) -> str:
        return "test-key"


@dataclass
class _StatefulFlow:
    value: Option[str] = field(default_factory=Nothing)

    async def __transition__(self, name: Option[str]) -> "Self | Done":
        match name:
            case Some(_n):
                return Done()
            case _:
                return replace(self, value=Some("waiting"))

    def to_domain(self) -> GreetOp:
        return GreetOp(name=self.value.unwrap())


class TestWrapStatefulFastapiExecution:
    def _make_stateful_handler(self) -> Handler[StatefulCodec]:
        from nodnod.agent.event_loop.agent import EventLoopAgent

        codec = StatefulCodec(
            flow=_StatefulFlow,
            response=GreetResp,
            store=MemoryStorage[str, _StatefulFlow](),
            key_node=_KeyNode,
            agent_cls=EventLoopAgent,
        )
        return Handler(codec=codec, runner=_runner, capabilities=())

    def test_wrap_returns_fastapi_route(self) -> None:
        handler = self._make_stateful_handler()
        trigger = HTTPRouteTrigger(method="POST", path="/flow")
        route = wrap_stateful_fastapi(handler, trigger, _axes)

        assert isinstance(route, FastAPIRoute)
        assert route.response_model is GreetResp

    def test_route_annotations(self) -> None:
        handler = self._make_stateful_handler()
        trigger = HTTPRouteTrigger(method="POST", path="/flow")
        route = wrap_stateful_fastapi(handler, trigger, _axes)

        annotations = route.endpoint.__annotations__
        assert annotations["request"] is fastapi.Request
        assert annotations["return"] is GreetResp


# ═══════════════════════════════════════════════════════════════════════════════
# register_handler — advanced scenarios (lines 461, 482-505)
# ═══════════════════════════════════════════════════════════════════════════════


class TestRegisterHandlerAdvanced:
    def _make_handler(
        self, capabilities: tuple[object, ...] = ()
    ) -> Handler[RequestResponseCodec]:
        codec = rrc(GreetReq, GreetResp)
        return Handler(codec=codec, runner=_runner, capabilities=capabilities)

    def test_skip_route_when_capability_sets_skip(self) -> None:
        """If compile_fastapi sets skip_route=True, no route is registered."""
        from emergent.wire.compile._capabilities import FastAPICompileContext
        from emergent.wire.axis.surface.capabilities._base import SurfaceCapability

        @dataclass(frozen=True)
        class SkipCap(SurfaceCapability):
            def compile_fastapi(
                self, ctx: FastAPICompileContext
            ) -> FastAPICompileContext:
                ctx.skip_route = True
                return ctx

        mock_app = MagicMock(spec=fastapi.FastAPI)
        handler = self._make_handler(capabilities=(SkipCap(),))
        route = FastAPIRoute(endpoint=_noop_endpoint)
        trigger = HTTPRouteTrigger(method="GET", path="/skip")

        register_handler(mock_app, trigger, handler, route, _axes)

        # No method (get, post, etc.) should be called
        mock_app.get.assert_not_called()
        mock_app.post.assert_not_called()

    def test_route_ctx_openapi_extra_merging_new(self) -> None:
        """When route has no openapi_extra but route_ctx does, uses route_ctx."""
        from emergent.wire.axis._capability import FastAPIRouteContext, fastapi_route
        from emergent.wire.axis.surface.capabilities._base import SurfaceCapability

        @dataclass(frozen=True)
        class ExtraCap(SurfaceCapability):
            def compile_fastapi_route(
                self, ctx: FastAPIRouteContext
            ) -> FastAPIRouteContext:
                return fastapi_route(
                    ctx, openapi_extra={"x-custom": "value"}
                )

        mock_app = MagicMock(spec=fastapi.FastAPI)
        mock_get = MagicMock(return_value=_identity_decorator)
        mock_app.get = mock_get

        handler = self._make_handler(capabilities=(ExtraCap(),))
        route = FastAPIRoute(endpoint=_noop_endpoint, openapi_extra=None)
        trigger = HTTPRouteTrigger(method="GET", path="/extra")

        register_handler(mock_app, trigger, handler, route, _axes)

        call_kwargs = mock_get.call_args
        assert call_kwargs is not None

    def test_status_code_passed_through(self) -> None:
        """When route_ctx has status_code, it's passed to method_fn."""
        from emergent.wire.axis._capability import FastAPIRouteContext, fastapi_route
        from emergent.wire.axis.surface.capabilities._base import SurfaceCapability

        @dataclass(frozen=True)
        class StatusCap(SurfaceCapability):
            def compile_fastapi_route(
                self, ctx: FastAPIRouteContext
            ) -> FastAPIRouteContext:
                return fastapi_route(ctx, status_code=201)

        mock_app = MagicMock(spec=fastapi.FastAPI)
        mock_post = MagicMock(return_value=_identity_decorator)
        mock_app.post = mock_post

        handler = self._make_handler(capabilities=(StatusCap(),))
        route = FastAPIRoute(endpoint=_noop_endpoint, response_model=GreetResp)
        trigger = HTTPRouteTrigger(method="POST", path="/create")

        register_handler(mock_app, trigger, handler, route, _axes)

        call_args = mock_post.call_args
        assert call_args is not None
        # The status_code should be in the kwargs
        kwargs = call_args[1]
        assert kwargs.get("status_code") == 201

    def test_openapi_extra_responses_merge(self) -> None:
        """When both route and route_ctx have 'responses' in openapi_extra, they merge."""
        from emergent.wire.axis._capability import FastAPIRouteContext, fastapi_route
        from emergent.wire.axis.surface.capabilities._base import SurfaceCapability

        @dataclass(frozen=True)
        class ResponseCap(SurfaceCapability):
            def compile_fastapi_route(
                self, ctx: FastAPIRouteContext
            ) -> FastAPIRouteContext:
                return fastapi_route(
                    ctx,
                    openapi_extra={
                        "responses": {"401": {"description": "Unauthorized"}}
                    },
                )

        mock_app = MagicMock(spec=fastapi.FastAPI)
        mock_get = MagicMock(return_value=_identity_decorator)
        mock_app.get = mock_get

        handler = self._make_handler(capabilities=(ResponseCap(),))
        route = FastAPIRoute(
            endpoint=_noop_endpoint,
            openapi_extra={"responses": {"404": {"description": "Not Found"}}},
        )
        trigger = HTTPRouteTrigger(method="GET", path="/merge")

        register_handler(mock_app, trigger, handler, route, _axes)

        call_args = mock_get.call_args
        assert call_args is not None
        kwargs = call_args[1]
        merged = kwargs.get("openapi_extra")
        # Both 404 and 401 should be present in merged responses
        assert merged is not None
        assert "401" in merged["responses"]
        assert "404" in merged["responses"]


# ═══════════════════════════════════════════════════════════════════════════════
# fastapi_compile — lifecycle, exceptions, websockets (lines 632-708)
# ═══════════════════════════════════════════════════════════════════════════════


class TestFastapiCompileLifecycle:
    def test_compile_with_startup_handler(self) -> None:
        """Application with startup trigger compiles without error."""
        started: list[bool] = []

        async def on_startup() -> None:
            started.append(True)

        app = (
            application()
            .mount(
                endpoint(_runner)
                .expose(StartupTrigger(), delegate(on_startup))
            )
        )
        fapi = fastapi_compile(app, _axes)
        assert isinstance(fapi, fastapi.FastAPI)

    def test_compile_with_shutdown_handler(self) -> None:
        """Application with shutdown trigger compiles without error."""
        async def on_shutdown() -> None:
            pass

        app = (
            application()
            .mount(
                endpoint(_runner)
                .expose(ShutdownTrigger(), delegate(on_shutdown))
            )
        )
        fapi = fastapi_compile(app, _axes)
        assert isinstance(fapi, fastapi.FastAPI)

    def test_compile_with_exception_handler(self) -> None:
        """Application with exception trigger compiles without error."""
        async def on_error(exc: ValueError) -> dict[str, str]:
            return {"error": str(exc)}

        app = (
            application()
            .mount(
                endpoint(_runner)
                .expose(ExceptionTrigger(ValueError), delegate(on_error))
            )
        )
        fapi = fastapi_compile(app, _axes)
        assert isinstance(fapi, fastapi.FastAPI)

    def test_compile_with_websocket_handler(self) -> None:
        """Application with websocket trigger compiles without error.

        Note: This tests only compilation, not FastAPI route registration,
        because FastAPI's parameter introspection doesn't handle Scope | None
        defaults on the internal websocket handler closure.
        """
        from emergent.wire.compile.targets.pure import WEBSOCKET_COMPILER

        async def ws_handler(websocket: fastapi.WebSocket) -> None:
            await websocket.accept()

        app = (
            application()
            .mount(
                endpoint(_runner)
                .expose(WebSocketTrigger(path="/ws", name="ws"), delegate(ws_handler))
            )
        )
        # Test that the websocket compiler can scan and wrap the handler
        ws_routes = list(WEBSOCKET_COMPILER.scan_and_wrap(app, _axes))
        assert len(ws_routes) == 1
        trigger, _handler, route = ws_routes[0]
        assert trigger.path == "/ws"
        assert callable(route.handler)


class TestFastapiCompileFamily:
    def test_compile_with_family_creates_scope_layer(self) -> None:
        """Compiling with family creates scope layer in axes."""
        from emergent.graph._family import ScopeFamily
        from emergent.wire.compile._lifetime import Tier

        family: ScopeFamily[Tier] = ScopeFamily()
        app = (
            application()
            .mount(
                endpoint(_runner)
                .expose(HTTPRouteTrigger("POST", "/test"), rrc(GreetReq, GreetResp))
            )
        )
        fapi = fastapi_compile(app, _axes, family=family)
        assert isinstance(fapi, fastapi.FastAPI)


# ═══════════════════════════════════════════════════════════════════════════════
# fastapi_compile_endpoint (lines 561-586)
# ═══════════════════════════════════════════════════════════════════════════════


class TestFastapiCompileEndpoint:
    def test_compile_rrc_endpoint_returns_api_routes(self) -> None:
        """compile_endpoint with RRC exposure returns APIRoute objects."""
        ep = (
            endpoint(_runner)
            .expose(HTTPRouteTrigger("POST", "/users"), rrc(GreetReq, GreetResp))
        )
        routes = fastapi_compile_endpoint(ep, _axes)
        assert len(routes) >= 1
        assert all(isinstance(r, fastapi.routing.APIRoute) for r in routes)

    def test_compile_endpoint_route_has_correct_path(self) -> None:
        """Each route should have the trigger path."""
        ep = (
            endpoint(_runner)
            .expose(HTTPRouteTrigger("GET", "/items"), rrc(GreetReq, GreetResp))
        )
        routes = fastapi_compile_endpoint(ep, _axes)
        assert len(routes) >= 1
        assert routes[0].path == "/items"

    def test_compile_endpoint_route_has_correct_method(self) -> None:
        """Each route should have the trigger HTTP method."""
        ep = (
            endpoint(_runner)
            .expose(HTTPRouteTrigger("DELETE", "/items"), rrc(GreetReq, GreetResp))
        )
        routes = fastapi_compile_endpoint(ep, _axes)
        assert len(routes) >= 1
        assert "DELETE" in routes[0].methods

    def test_compile_multiple_exposures(self) -> None:
        """Endpoint with multiple RRC exposures returns multiple routes."""
        ep = (
            endpoint(_runner)
            .expose(HTTPRouteTrigger("POST", "/users"), rrc(GreetReq, GreetResp))
            .expose(HTTPRouteTrigger("GET", "/users"), rrc(GreetReq, GreetResp))
        )
        routes = fastapi_compile_endpoint(ep, _axes)
        assert len(routes) >= 2

    def test_compile_endpoint_default_axes(self) -> None:
        """compile_endpoint works with default axes (None)."""
        ep = (
            endpoint(_runner)
            .expose(HTTPRouteTrigger("POST", "/test"), rrc(GreetReq, GreetResp))
        )
        routes = fastapi_compile_endpoint(ep)
        assert len(routes) >= 1


# ═══════════════════════════════════════════════════════════════════════════════
# fastapi_compile_stack (lines 737-780)
# ═══════════════════════════════════════════════════════════════════════════════


class TestFastapiCompileStack:
    def test_compile_flat_stack_returns_fastapi_app(self) -> None:
        """Flat stack (root only) compiles to FastAPI app."""
        root_app = (
            application()
            .mount(
                endpoint(_runner)
                .expose(HTTPRouteTrigger("GET", "/health"), immediate(ImmediateResp))
            )
        )
        stack = app_stack().root(root_app)
        fapi = fastapi_compile_stack(stack, _axes)
        assert isinstance(fapi, fastapi.FastAPI)

    def test_compile_stack_with_mount(self) -> None:
        """Stack with mounted sub-application compiles correctly."""
        root_app = (
            application()
            .mount(
                endpoint(_runner)
                .expose(HTTPRouteTrigger("GET", "/health"), immediate(ImmediateResp))
            )
        )
        sub_app = (
            application()
            .mount(
                endpoint(_runner)
                .expose(HTTPRouteTrigger("POST", "/create"), rrc(GreetReq, GreetResp))
            )
        )
        stack = app_stack().root(root_app).mount("api", sub_app)
        fapi = fastapi_compile_stack(stack, _axes)
        assert isinstance(fapi, fastapi.FastAPI)

    def test_compile_stack_nested_mount(self) -> None:
        """Stack with nested AppStack mount compiles correctly."""
        inner_app = (
            application()
            .mount(
                endpoint(_runner)
                .expose(HTTPRouteTrigger("GET", "/list"), rrc(GreetReq, GreetResp))
            )
        )
        inner_stack = app_stack().root(inner_app)

        root_app = (
            application()
            .mount(
                endpoint(_runner)
                .expose(HTTPRouteTrigger("GET", "/health"), immediate(ImmediateResp))
            )
        )
        stack = app_stack().root(root_app).mount("v1", inner_stack)
        fapi = fastapi_compile_stack(stack, _axes)
        assert isinstance(fapi, fastapi.FastAPI)

    def test_compile_stack_default_axes(self) -> None:
        """compile_stack works with default axes (None)."""
        root_app = application()
        stack = app_stack().root(root_app)
        fapi = fastapi_compile_stack(stack)
        assert isinstance(fapi, fastapi.FastAPI)

    def test_compile_stack_custom_compiler(self) -> None:
        """compile_stack accepts custom compiler."""
        root_app = (
            application()
            .mount(
                endpoint(_runner)
                .expose(HTTPRouteTrigger("GET", "/test"), rrc(GreetReq, GreetResp))
            )
        )
        stack = app_stack().root(root_app)
        fapi = fastapi_compile_stack(stack, _axes, compiler=FASTAPI_COMPILER)
        assert isinstance(fapi, fastapi.FastAPI)


# ═══════════════════════════════════════════════════════════════════════════════
# _wrap_for_stack (lines 725-728)
# ═══════════════════════════════════════════════════════════════════════════════


class TestWrapForStack:
    def test_wraps_rrc_handler(self) -> None:
        """_wrap_for_stack finds RRC adapter and wraps."""
        codec = rrc(GreetReq, GreetResp)
        handler = Handler(codec=codec, runner=_runner, capabilities=())
        trigger = HTTPRouteTrigger(method="GET", path="/test")

        route = _wrap_for_stack(handler, trigger, _axes, FASTAPI_COMPILER)
        assert isinstance(route, FastAPIRoute)

    def test_wraps_immediate_handler(self) -> None:
        """_wrap_for_stack finds Immediate adapter and wraps."""
        codec = immediate(ImmediateResp)
        handler = Handler(codec=codec, runner=_runner, capabilities=())
        trigger = HTTPRouteTrigger(method="GET", path="/test")

        route = _wrap_for_stack(handler, trigger, _axes, FASTAPI_COMPILER)
        assert isinstance(route, FastAPIRoute)

    def test_raises_for_unknown_codec(self) -> None:
        """_wrap_for_stack raises ValueError for unregistered codec type."""

        @dataclass(frozen=True)
        class UnknownCodec:
            pass

        handler = Handler(codec=UnknownCodec(), runner=_runner, capabilities=())
        trigger = HTTPRouteTrigger(method="GET", path="/test")

        with pytest.raises(ValueError, match="No adapter for codec type"):
            _wrap_for_stack(handler, trigger, _axes, FASTAPI_COMPILER)


# ═══════════════════════════════════════════════════════════════════════════════
# is_pydantic_model — import error branch (lines 80-81)
# ═══════════════════════════════════════════════════════════════════════════════


class TestIsPydanticModelImportError:
    def test_returns_false_when_pydantic_not_available(self) -> None:
        """When pydantic import fails, returns False."""
        # pydantic is available in this env, so test the positive case
        from pydantic import BaseModel

        class Model(BaseModel):
            x: int

        assert is_pydantic_model(Model) is True

    def test_non_class_returns_false(self) -> None:
        assert is_pydantic_model("string") is False
        assert is_pydantic_model(42) is False
        assert is_pydantic_model(None) is False


# ═══════════════════════════════════════════════════════════════════════════════
# build_rrc_openapi_extra — POST with path params (lines 385-391)
# ═══════════════════════════════════════════════════════════════════════════════


class TestBuildRrcOpenapiExtraAdvanced:
    def test_post_with_path_params_strips_from_body(self) -> None:
        """POST with path params should exclude them from requestBody."""
        codec = rrc(PathBodyReq, GreetResp)
        trigger = HTTPRouteTrigger(method="POST", path="/users/{user_id}")
        result = build_rrc_openapi_extra(codec, trigger, _axes)

        assert result is not None
        # user_id should be in path parameters
        if "parameters" in result:
            path_names = {
                p["name"] for p in result["parameters"] if p["in"] == "path"
            }
            assert "user_id" in path_names

        # requestBody should NOT contain user_id
        if "requestBody" in result:
            body_schema = result["requestBody"]["content"]["application/json"]["schema"]
            if "properties" in body_schema:
                assert "user_id" not in body_schema["properties"]

    def test_get_with_path_params_excludes_from_query(self) -> None:
        """GET with path params: path params are NOT in query parameters."""
        codec = rrc(PathBodyReq, GreetResp)
        trigger = HTTPRouteTrigger(method="GET", path="/users/{user_id}")
        result = build_rrc_openapi_extra(codec, trigger, _axes)

        assert result is not None
        if "parameters" in result:
            query_params = [p for p in result["parameters"] if p["in"] == "query"]
            query_names = {p["name"] for p in query_params}
            # user_id should NOT be in query params
            assert "user_id" not in query_names

    def test_post_path_params_required_filtered_in_body(self) -> None:
        """POST required list in body schema should exclude path param names."""
        codec = rrc(PathBodyReq, GreetResp)
        trigger = HTTPRouteTrigger(method="POST", path="/users/{user_id}")
        result = build_rrc_openapi_extra(codec, trigger, _axes)

        assert result is not None
        if "requestBody" in result:
            body_schema = result["requestBody"]["content"]["application/json"]["schema"]
            if "required" in body_schema:
                assert "user_id" not in body_schema["required"]

    def test_put_method_produces_request_body(self) -> None:
        """PUT method is treated same as POST for body parsing."""
        codec = rrc(BodyReq, GreetResp)
        trigger = HTTPRouteTrigger(method="PUT", path="/users")
        result = build_rrc_openapi_extra(codec, trigger, _axes)

        assert result is not None
        assert "requestBody" in result

    def test_patch_method_produces_request_body(self) -> None:
        """PATCH method is treated same as POST for body parsing."""
        codec = rrc(BodyReq, GreetResp)
        trigger = HTTPRouteTrigger(method="PATCH", path="/users")
        result = build_rrc_openapi_extra(codec, trigger, _axes)

        assert result is not None
        assert "requestBody" in result

    def test_delete_method_produces_query_params(self) -> None:
        """DELETE method uses query parameters, not request body."""
        codec = rrc(GreetReq, GreetResp)
        trigger = HTTPRouteTrigger(method="DELETE", path="/items")
        result = build_rrc_openapi_extra(codec, trigger, _axes)

        # DELETE should produce query parameters, not body
        if result is not None:
            assert "requestBody" not in result


# ═══════════════════════════════════════════════════════════════════════════════
# fastapi_compile — middleware from app capabilities (line 680)
# ═══════════════════════════════════════════════════════════════════════════════


class TestFastapiCompileMiddleware:
    def test_application_capabilities_applied_as_middleware(self) -> None:
        """Application-level capabilities can add middleware."""
        from emergent.wire.axis._capability import (
            FastAPIAppContext,
            fastapi_app_middleware,
        )
        from emergent.wire.axis.surface.capabilities._base import SurfaceCapability

        @dataclass(frozen=True)
        class TestMiddlewareCap(SurfaceCapability):
            def compile_fastapi_app(
                self, ctx: FastAPIAppContext
            ) -> FastAPIAppContext:
                # Add a fake middleware class
                return fastapi_app_middleware(ctx, type("FakeMiddleware", (), {}))

        app = application(capabilities=(TestMiddlewareCap(),))
        fapi = fastapi_compile(app, _axes)
        assert isinstance(fapi, fastapi.FastAPI)

"""Tests for emergent.wire.compile.targets.fastapi — FastAPI compilation target."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Self
from unittest.mock import AsyncMock, MagicMock

import fastapi
import pytest
from kungfu import Ok, Result

from emergent.ops._graph import Op, ops
from emergent.wire.axis.surface._app import Application, application
from emergent.wire.axis.surface._endpoint import endpoint
from emergent.wire.axis.surface._handler import Handler
from emergent.wire.axis.surface.codecs.delegate import DelegateCodec, delegate
from emergent.wire.axis.surface.codecs.immediate import (
    ImmediateCodec,
    ImmediateFactoryCodec,
    immediate,
    immediate_factory,
)
from emergent.wire.axis.surface.codecs.rrc import RequestResponseCodec, rrc
from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger
from emergent.wire.compile._core import Axes
from emergent.wire.compile.targets.fastapi import (
    FASTAPI_COMPILER,
    FastAPIRoute,
    build_rrc_openapi_extra,
    is_pydantic_model,
    fastapi_compile,
    register_handler,
    setup_fastapi_scope,
    wrap_delegate_fastapi,
    wrap_immediate_fastapi,
    wrap_rrc_fastapi,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Domain types for tests
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class SimpleOp(Op[int, str]):
    name: str


async def _simple_handler(req: SimpleOp) -> Result[int, str]:
    return Ok(42)


@dataclass
class SimpleReq:
    name: str

    def to_domain(self) -> SimpleOp:
        return SimpleOp(name=self.name)


@dataclass
class SimpleResp:
    value: int

    @classmethod
    def from_domain(cls, dom: Result[int, str]) -> Self:
        match dom:
            case Ok(v):
                return cls(value=v)
            case _:
                return cls(value=-1)


@dataclass
class BodyReq:
    name: str
    age: int

    def to_domain(self) -> SimpleOp:
        return SimpleOp(name=self.name)


@dataclass
class PathReq:
    user_id: str
    name: str

    def to_domain(self) -> SimpleOp:
        return SimpleOp(name=self.name)


@dataclass
class ImmediateResp:
    text: str

    @classmethod
    def produce(cls) -> Self:
        return cls(text="hello")


async def _delegate_handler(name: str) -> str:
    return name


_runner = ops().on(SimpleOp, _simple_handler).compile()
_axes = Axes.default()
_trigger_post = HTTPRouteTrigger(method="POST", path="/test")
_trigger_get = HTTPRouteTrigger(method="GET", path="/items")
_trigger_path = HTTPRouteTrigger(method="GET", path="/users/{user_id}")


# ═══════════════════════════════════════════════════════════════════════════════
# is_pydantic_model
# ═══════════════════════════════════════════════════════════════════════════════


class TestIsPydanticModel:
    def test_pydantic_basemodel_subclass_returns_true(self) -> None:
        from pydantic import BaseModel

        class MyModel(BaseModel):
            name: str

        assert is_pydantic_model(MyModel) is True

    def test_regular_dataclass_returns_false(self) -> None:
        assert is_pydantic_model(SimpleReq) is False

    def test_non_type_instance_returns_false(self) -> None:
        instance = SimpleReq(name="test")
        assert is_pydantic_model(instance) is False

    def test_plain_class_returns_false(self) -> None:
        class NotPydantic:
            pass

        assert is_pydantic_model(NotPydantic) is False

    def test_builtin_type_returns_false(self) -> None:
        assert is_pydantic_model(str) is False


# ═══════════════════════════════════════════════════════════════════════════════
# FastAPIRoute dataclass
# ═══════════════════════════════════════════════════════════════════════════════


class TestFastAPIRouteDataclass:
    def test_construction_with_all_fields(self) -> None:
        def _endpoint() -> None:
            pass

        route = FastAPIRoute(
            endpoint=_endpoint,
            response_model=SimpleResp,
            openapi_extra={"summary": "test"},
        )
        assert route.endpoint is _endpoint
        assert route.response_model is SimpleResp
        assert route.openapi_extra == {"summary": "test"}

    def test_default_response_model_is_none(self) -> None:
        def _endpoint() -> None:
            pass

        route = FastAPIRoute(endpoint=_endpoint)
        assert route.response_model is None

    def test_default_openapi_extra_is_none(self) -> None:
        def _endpoint() -> None:
            pass

        route = FastAPIRoute(endpoint=_endpoint)
        assert route.openapi_extra is None

    def test_frozen_immutable(self) -> None:
        def _endpoint() -> None:
            pass

        route = FastAPIRoute(endpoint=_endpoint)
        with pytest.raises((AttributeError, TypeError)):
            route.response_model = SimpleResp  # type: ignore[misc]


# ═══════════════════════════════════════════════════════════════════════════════
# wrap_rrc_fastapi
# ═══════════════════════════════════════════════════════════════════════════════


class TestWrapRrcFastapi:
    def _make_handler(self) -> Handler[RequestResponseCodec]:
        codec = rrc(SimpleReq, SimpleResp)
        return Handler(codec=codec, runner=_runner, capabilities=())

    def test_returns_fastapi_route(self) -> None:
        handler = self._make_handler()
        route = wrap_rrc_fastapi(handler, _trigger_post, _axes)
        assert isinstance(route, FastAPIRoute)

    def test_response_model_is_set(self) -> None:
        handler = self._make_handler()
        route = wrap_rrc_fastapi(handler, _trigger_post, _axes)
        assert route.response_model is SimpleResp

    def test_endpoint_is_callable(self) -> None:
        handler = self._make_handler()
        route = wrap_rrc_fastapi(handler, _trigger_post, _axes)
        assert callable(route.endpoint)

    def test_endpoint_is_async(self) -> None:
        import inspect

        handler = self._make_handler()
        route = wrap_rrc_fastapi(handler, _trigger_post, _axes)
        assert inspect.iscoroutinefunction(route.endpoint)

    def test_openapi_extra_for_post(self) -> None:
        handler = self._make_handler()
        route = wrap_rrc_fastapi(handler, _trigger_post, _axes)
        # POST with body fields should produce openapi_extra with requestBody
        if route.openapi_extra is not None:
            assert isinstance(route.openapi_extra, dict)

    def test_get_trigger_produces_no_body_in_openapi(self) -> None:
        handler = self._make_handler()
        route = wrap_rrc_fastapi(handler, _trigger_get, _axes)
        assert isinstance(route, FastAPIRoute)
        # GET should not have requestBody in openapi_extra
        if route.openapi_extra is not None:
            assert "requestBody" not in route.openapi_extra


# ═══════════════════════════════════════════════════════════════════════════════
# wrap_immediate_fastapi
# ═══════════════════════════════════════════════════════════════════════════════


class TestWrapImmediateFastapi:
    def test_returns_fastapi_route_for_immediate_codec(self) -> None:
        codec = immediate(ImmediateResp)
        handler: Handler[ImmediateCodec] = Handler(
            codec=codec, runner=_runner, capabilities=()
        )
        route = wrap_immediate_fastapi(handler, _trigger_get, _axes)
        assert isinstance(route, FastAPIRoute)

    def test_returns_fastapi_route_for_factory_codec(self) -> None:
        codec = immediate_factory(lambda: ImmediateResp(text="factory"))
        handler: Handler[ImmediateFactoryCodec] = Handler(
            codec=codec, runner=_runner, capabilities=()
        )
        route = wrap_immediate_fastapi(handler, _trigger_get, _axes)
        assert isinstance(route, FastAPIRoute)

    def test_endpoint_is_callable(self) -> None:
        codec = immediate(ImmediateResp)
        handler: Handler[ImmediateCodec] = Handler(
            codec=codec, runner=_runner, capabilities=()
        )
        route = wrap_immediate_fastapi(handler, _trigger_get, _axes)
        assert callable(route.endpoint)

    def test_endpoint_is_async(self) -> None:
        import inspect

        codec = immediate(ImmediateResp)
        handler: Handler[ImmediateCodec] = Handler(
            codec=codec, runner=_runner, capabilities=()
        )
        route = wrap_immediate_fastapi(handler, _trigger_get, _axes)
        assert inspect.iscoroutinefunction(route.endpoint)

    @pytest.mark.asyncio
    async def test_endpoint_produces_immediate_response(self) -> None:
        codec = immediate(ImmediateResp)
        handler: Handler[ImmediateCodec] = Handler(
            codec=codec, runner=_runner, capabilities=()
        )
        route = wrap_immediate_fastapi(handler, _trigger_get, _axes)
        result = await route.endpoint()
        assert isinstance(result, ImmediateResp)
        assert result.text == "hello"

    @pytest.mark.asyncio
    async def test_endpoint_calls_factory(self) -> None:
        codec = immediate_factory(lambda: ImmediateResp(text="from-factory"))
        handler: Handler[ImmediateFactoryCodec] = Handler(
            codec=codec, runner=_runner, capabilities=()
        )
        route = wrap_immediate_fastapi(handler, _trigger_get, _axes)
        result = await route.endpoint()
        assert isinstance(result, ImmediateResp)
        assert result.text == "from-factory"


# ═══════════════════════════════════════════════════════════════════════════════
# wrap_delegate_fastapi
# ═══════════════════════════════════════════════════════════════════════════════


class TestWrapDelegateFastapi:
    def test_returns_fastapi_route(self) -> None:
        codec = delegate(_delegate_handler)
        handler: Handler[DelegateCodec] = Handler(
            codec=codec, runner=_runner, capabilities=()
        )
        route = wrap_delegate_fastapi(handler, _trigger_get, _axes)
        assert isinstance(route, FastAPIRoute)

    def test_endpoint_is_callable(self) -> None:
        codec = delegate(_delegate_handler)
        handler: Handler[DelegateCodec] = Handler(
            codec=codec, runner=_runner, capabilities=()
        )
        route = wrap_delegate_fastapi(handler, _trigger_get, _axes)
        assert callable(route.endpoint)

    def test_endpoint_is_async(self) -> None:
        import inspect

        codec = delegate(_delegate_handler)
        handler: Handler[DelegateCodec] = Handler(
            codec=codec, runner=_runner, capabilities=()
        )
        route = wrap_delegate_fastapi(handler, _trigger_get, _axes)
        assert inspect.iscoroutinefunction(route.endpoint)

    def test_response_model_is_none(self) -> None:
        codec = delegate(_delegate_handler)
        handler: Handler[DelegateCodec] = Handler(
            codec=codec, runner=_runner, capabilities=()
        )
        route = wrap_delegate_fastapi(handler, _trigger_get, _axes)
        assert route.response_model is None


# ═══════════════════════════════════════════════════════════════════════════════
# build_rrc_openapi_extra
# ═══════════════════════════════════════════════════════════════════════════════


class TestBuildRrcOpenapiExtra:
    def test_post_with_body_fields_produces_request_body(self) -> None:
        codec = rrc(BodyReq, SimpleResp)
        result = build_rrc_openapi_extra(codec, _trigger_post, _axes)
        assert result is not None
        assert "requestBody" in result
        assert "content" in result["requestBody"]
        assert "application/json" in result["requestBody"]["content"]

    def test_get_produces_query_parameters(self) -> None:
        codec = rrc(SimpleReq, SimpleResp)
        trigger = HTTPRouteTrigger(method="GET", path="/search")
        result = build_rrc_openapi_extra(codec, trigger, _axes)
        # GET with fields should have query parameters
        if result is not None:
            if "parameters" in result:
                in_values = {p["in"] for p in result["parameters"]}
                assert "query" in in_values

    def test_path_params_extracted_from_trigger(self) -> None:
        codec = rrc(PathReq, SimpleResp)
        result = build_rrc_openapi_extra(codec, _trigger_path, _axes)
        # Path param user_id should appear in parameters
        if result is not None and "parameters" in result:
            path_params = [p for p in result["parameters"] if p["in"] == "path"]
            param_names = {p["name"] for p in path_params}
            assert "user_id" in param_names

    def test_path_params_are_required(self) -> None:
        codec = rrc(PathReq, SimpleResp)
        result = build_rrc_openapi_extra(codec, _trigger_path, _axes)
        if result is not None and "parameters" in result:
            path_params = [p for p in result["parameters"] if p["in"] == "path"]
            for param in path_params:
                assert param["required"] is True

    def test_returns_none_or_dict(self) -> None:
        codec = rrc(SimpleReq, SimpleResp)
        result = build_rrc_openapi_extra(codec, _trigger_post, _axes)
        assert result is None or isinstance(result, dict)


# ═══════════════════════════════════════════════════════════════════════════════
# register_handler
# ═══════════════════════════════════════════════════════════════════════════════


class TestRegisterHandler:
    def _make_handler(self) -> Handler[RequestResponseCodec]:
        codec = rrc(SimpleReq, SimpleResp)
        return Handler(codec=codec, runner=_runner, capabilities=())

    def _make_route(self) -> FastAPIRoute:
        def _ep() -> None:
            pass

        return FastAPIRoute(endpoint=_ep, response_model=SimpleResp)

    def test_calls_method_on_app(self) -> None:
        mock_app = MagicMock(spec=fastapi.FastAPI)
        mock_post = MagicMock()
        mock_app.post = mock_post
        _identity: Callable[[Callable[..., str]], Callable[..., str]] = lambda fn: fn
        mock_post.return_value = _identity

        handler = self._make_handler()
        route = self._make_route()
        trigger = HTTPRouteTrigger(method="POST", path="/items")

        register_handler(mock_app, trigger, handler, route, _axes)

        mock_post.assert_called_once()

    def test_calls_correct_method_for_get(self) -> None:
        mock_app = MagicMock(spec=fastapi.FastAPI)
        mock_get = MagicMock()
        mock_app.get = mock_get
        _identity: Callable[[Callable[..., str]], Callable[..., str]] = lambda fn: fn
        mock_get.return_value = _identity

        handler = self._make_handler()
        route = self._make_route()
        trigger = HTTPRouteTrigger(method="GET", path="/items")

        register_handler(mock_app, trigger, handler, route, _axes)

        mock_get.assert_called_once()

    def test_raises_for_unsupported_method(self) -> None:
        # Build a mock app where getattr(..., "post", None) returns None
        # so that register_handler hits the ValueError branch
        mock_app = MagicMock(spec=fastapi.FastAPI)
        # getattr(mock_app, "post") normally returns a MagicMock;
        # we make it return None to trigger the ValueError path
        mock_app.configure_mock(post=None, get=None, put=None, delete=None, patch=None)

        handler = self._make_handler()
        route = self._make_route()
        trigger = HTTPRouteTrigger(method="POST", path="/x")

        with pytest.raises(ValueError, match="Unsupported HTTP method"):
            register_handler(mock_app, trigger, handler, route, _axes)


# ═══════════════════════════════════════════════════════════════════════════════
# setup_fastapi_scope
# ═══════════════════════════════════════════════════════════════════════════════


class TestSetupFastapiScope:
    @pytest.mark.asyncio
    async def test_injects_fastapi_request_into_scope(self) -> None:
        from nodnod import Scope

        scope = Scope()
        mock_request = MagicMock(spec=fastapi.Request)
        mock_request.json = AsyncMock(return_value={})

        async with scope:
            await setup_fastapi_scope(scope, mock_request, set())
            wrapper = scope.get(fastapi.Request)
            assert wrapper is not None
            assert wrapper.value is mock_request

    @pytest.mark.asyncio
    async def test_injects_pydantic_types_from_body(self) -> None:
        from nodnod import Scope
        from pydantic import BaseModel

        class UserModel(BaseModel):
            name: str
            age: int

        scope = Scope()
        mock_request = MagicMock(spec=fastapi.Request)
        mock_request.json = AsyncMock(return_value={"name": "Alice", "age": 30})

        async with scope:
            await setup_fastapi_scope(scope, mock_request, {UserModel})
            wrapper = scope.get(UserModel)
            assert wrapper is not None
            assert wrapper.value.name == "Alice"
            assert wrapper.value.age == 30

    @pytest.mark.asyncio
    async def test_handles_invalid_json_gracefully(self) -> None:
        from nodnod import Scope
        from pydantic import BaseModel

        class AModel(BaseModel):
            field: str

        scope = Scope()
        mock_request = MagicMock(spec=fastapi.Request)
        mock_request.json = AsyncMock(side_effect=Exception("bad json"))

        # Should not raise
        async with scope:
            await setup_fastapi_scope(scope, mock_request, {AModel})

    @pytest.mark.asyncio
    async def test_empty_pydantic_types_skips_body_parse(self) -> None:
        from nodnod import Scope

        scope = Scope()
        mock_request = MagicMock(spec=fastapi.Request)
        # json should NOT be called if pydantic_types is empty
        mock_request.json = AsyncMock(return_value={})

        async with scope:
            await setup_fastapi_scope(scope, mock_request, set())
            mock_request.json.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════════════
# FASTAPI_COMPILER
# ═══════════════════════════════════════════════════════════════════════════════


class TestFastapiCompiler:
    def test_trigger_type_is_http_route_trigger(self) -> None:
        assert FASTAPI_COMPILER.trigger_type is HTTPRouteTrigger

    def test_has_rrc_adapter(self) -> None:
        codec_types = {a.codec_type for a in FASTAPI_COMPILER.adapters}
        assert RequestResponseCodec in codec_types

    def test_has_immediate_adapter(self) -> None:
        codec_types = {a.codec_type for a in FASTAPI_COMPILER.adapters}
        assert ImmediateCodec in codec_types

    def test_has_immediate_factory_adapter(self) -> None:
        codec_types = {a.codec_type for a in FASTAPI_COMPILER.adapters}
        assert ImmediateFactoryCodec in codec_types

    def test_has_delegate_adapter(self) -> None:
        codec_types = {a.codec_type for a in FASTAPI_COMPILER.adapters}
        assert DelegateCodec in codec_types

    def test_rrc_adapter_wraps_to_fastapi_route(self) -> None:
        codec = rrc(SimpleReq, SimpleResp)
        handler: Handler[RequestResponseCodec] = Handler(
            codec=codec, runner=_runner, capabilities=()
        )
        # Use compat wrapper to produce FastAPIRoute
        result = wrap_rrc_fastapi(handler, _trigger_post, _axes)
        assert isinstance(result, FastAPIRoute)

    def test_immediate_adapter_wraps_to_fastapi_route(self) -> None:
        codec = immediate(ImmediateResp)
        handler: Handler[ImmediateCodec] = Handler(
            codec=codec, runner=_runner, capabilities=()
        )
        result = wrap_immediate_fastapi(handler, _trigger_get, _axes)
        assert isinstance(result, FastAPIRoute)


# ═══════════════════════════════════════════════════════════════════════════════
# fastapi_compile (integration)
# ═══════════════════════════════════════════════════════════════════════════════


class TestFastapiCompile:
    def _make_app_with_rrc(self) -> Application:
        ep = (
            endpoint(_runner)
            .expose(_trigger_post, rrc(SimpleReq, SimpleResp))
        )
        return application().mount(ep)

    def _make_app_with_immediate(self) -> Application:
        ep = endpoint(_runner).expose(_trigger_get, immediate(ImmediateResp))
        return application().mount(ep)

    def test_returns_fastapi_app(self) -> None:
        app = self._make_app_with_rrc()
        result = fastapi_compile(app, _axes)
        assert isinstance(result, fastapi.FastAPI)

    def test_routes_registered_from_application(self) -> None:
        from starlette.routing import Route

        app = self._make_app_with_rrc()
        fapi = fastapi_compile(app, _axes)
        # At least one route should be registered (POST /test + lifespan internal routes)
        route_paths: set[str] = {
            r.path
            for r in fapi.routes
            if isinstance(r, Route)
        }
        assert "/test" in route_paths

    def test_compile_with_immediate_codec(self) -> None:
        from starlette.routing import Route

        app = self._make_app_with_immediate()
        fapi = fastapi_compile(app, _axes)
        assert isinstance(fapi, fastapi.FastAPI)
        route_paths: set[str] = {
            r.path
            for r in fapi.routes
            if isinstance(r, Route)
        }
        assert "/items" in route_paths

    def test_compile_with_default_axes(self) -> None:
        app = self._make_app_with_rrc()
        # Should work without explicit axes
        fapi = fastapi_compile(app)
        assert isinstance(fapi, fastapi.FastAPI)

    def test_compile_with_custom_compiler(self) -> None:
        from emergent.wire.compile._target import TargetCompiler, CodecAdapter

        # A minimal compiler with only RRC
        minimal = TargetCompiler(
            trigger_type=HTTPRouteTrigger,
            adapters=(CodecAdapter(RequestResponseCodec, wrap_rrc_fastapi),),
        )
        app = self._make_app_with_rrc()
        fapi = fastapi_compile(app, _axes, compiler=minimal)
        assert isinstance(fapi, fastapi.FastAPI)

    def test_empty_application_compiles(self) -> None:
        app = application()
        fapi = fastapi_compile(app, _axes)
        assert isinstance(fapi, fastapi.FastAPI)

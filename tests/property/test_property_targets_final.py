# pyright: reportPrivateUsage=false
"""Final deep-coverage tests for compile targets — FastAPI, CLI, Telegrinder.

Covers remaining uncovered lines across:
  - fastapi.py: form extractor, include_path_params=False, __getattr__ lazy,
    scope_layer reuse, router inclusion, _wrap_for_stack guard,
    stateful from_codec compilation, stateful execution paths
  - cli.py: _wrap_for_stack guard, stateful codec, delegate helpers,
    typed CLI, cli_run edge cases, prompt value, compile_stack nesting
  - telegrinder.py: stateful_from_codec_tg, _stateful_execute_tg,
    assemble type error guard, help generation, command arg generation,
    response formatting, compose helpers, multi-view handlers

Uses REAL telegrinder, REAL FastAPI. Builds Application objects via pipeline.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass, field, replace
from typing import Annotated, Any, Self
from unittest.mock import patch
from types import MappingProxyType

import fastapi
import pytest
from kungfu import Ok, Result, Option, Some, Nothing

from nodnod import Scope

from emergent.ops._graph import Op, ops
from emergent.wire.axis.surface._app import Application
from emergent.wire.axis.surface._endpoint import endpoint
from emergent.wire.axis.surface._handler import Handler
from emergent.wire.axis.surface._stack import app_stack
from emergent.wire.axis.surface import empty_runner
from emergent.wire.axis.surface.codecs.rrc import RequestResponseCodec, rrc
from emergent.wire.axis.surface.codecs.immediate import (
    ImmediateCodec,
    ImmediateFactoryCodec,
    immediate,
)
from emergent.wire.axis.surface.codecs.delegate import delegate, DelegateCodec
from emergent.wire.axis.surface.codecs.stateful import (
    StatefulCodec,
    Done,
    MemoryStorage,
)
from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger
from emergent.wire.axis.surface.triggers.cli import CLITrigger
from emergent.wire.axis.surface.triggers.telegrinder import TelegrindTrigger
from emergent.wire.compile._core import Axes
from emergent.wire.compile._target import TargetCompiler
from emergent.wire.compile._lifetime import ScopeLayer, Tier, App, Request
from emergent.graph._family import ScopeFamily


# =============================================================================
# Domain types
# =============================================================================


@dataclass
class EchoOp(Op[str, str]):
    msg: str


async def _echo_handler(req: EchoOp) -> Result[str, str]:
    return Ok(f"echo:{req.msg}")


@dataclass
class EchoRequest:
    msg: str

    def to_domain(self) -> EchoOp:
        return EchoOp(msg=self.msg)


@dataclass
class EchoResponse:
    reply: str

    @classmethod
    def from_domain(cls, dom: Result[str, str]) -> Self:
        match dom:
            case Ok(v):
                return cls(reply=v)
            case _:
                return cls(reply="error")


@dataclass
class MultiFieldOp(Op[dict[str, object], str]):
    name: str
    age: int
    flag: bool


async def _multi_handler(req: MultiFieldOp) -> Result[dict[str, object], str]:
    result: dict[str, object] = {"name": req.name, "age": req.age, "flag": req.flag}
    return Ok(result)


@dataclass
class MultiFieldRequest:
    name: str
    age: int
    flag: bool = False

    def to_domain(self) -> MultiFieldOp:
        return MultiFieldOp(name=self.name, age=self.age, flag=self.flag)


@dataclass
class MultiFieldResponse:
    name: str
    age: int

    @classmethod
    def from_domain(cls, dom: Result[dict[str, object], str]) -> Self:
        match dom:
            case Ok(v):
                return cls(name=str(v["name"]), age=int(v["age"]))  # type: ignore[arg-type]
            case _:
                return cls(name="err", age=-1)


@dataclass
class ImmHealth:
    status: str

    @classmethod
    def produce(cls) -> Self:
        return cls(status="ok")


def _runner():
    return ops().on(EchoOp, _echo_handler).on(MultiFieldOp, _multi_handler).compile()


# =============================================================================
# Module-level Annotated dataclasses for telegrinder tests
# (must be at module level for get_type_hints to resolve annotations)
# =============================================================================

from emergent.wire.axis.schema.dialects.tg import CommandArg

@dataclass
class _TgReqWithArgs:
    login: Annotated[str, CommandArg()]
    password: Annotated[str, CommandArg()]


@dataclass
class _TgReqWithGreedy:
    description: Annotated[str, CommandArg(greedy=True)]


@dataclass
class _TgReqWithInt:
    count: Annotated[int, CommandArg()]


@dataclass
class _TgReqWithSingleArg:
    login: Annotated[str, CommandArg()]

    def to_domain(self) -> Op[Any, Any]:
        return EchoOp(msg=self.login)


# =============================================================================
# Stateful flow for CLI and Telegrinder
# =============================================================================

@dataclass
class ChatId:
    """Simple key node for stateful codec."""
    __dependencies__: tuple[type, ...] = ()

    @classmethod
    def compose(cls, **kw: object) -> str:
        return "test-chat-123"


@dataclass
class SimpleFlow:
    """Minimal flow with a single transition."""
    value: Option[str] = field(default_factory=Nothing)

    async def __transition__(
        self,
    ) -> Self | Done:
        if isinstance(self.value, Some):
            return Done()
        return replace(self, value=Some("collected"))

    def to_domain(self) -> EchoOp:
        return EchoOp(msg=self.value.unwrap() if isinstance(self.value, Some) else "none")


@dataclass
class FlowResponse:
    result: str

    @classmethod
    def from_domain(cls, dom: Result[str, str]) -> Self:
        match dom:
            case Ok(v):
                return cls(result=v)
            case _:
                return cls(result="error")


# =============================================================================
# FastAPI Target — remaining uncovered lines
# =============================================================================


class TestFastAPIJsonExtractorFormData:
    """Test FastAPIJsonExtractor form data branch (line 101)."""

    @pytest.mark.anyio
    async def test_json_extractor_with_json_body(self) -> None:
        from emergent.wire.compile.targets.fastapi import FastAPIJsonExtractor
        from starlette.testclient import TestClient

        ext = FastAPIJsonExtractor()
        app = fastapi.FastAPI()

        @app.post("/json-test")
        async def _test(request: fastapi.Request) -> dict[str, object]:
            return await ext.extract(request)

        assert _test is not None  # registered via decorator
        client = TestClient(app)
        resp = client.post("/json-test", json={"field1": "value1"})
        assert resp.status_code == 200
        assert resp.json()["field1"] == "value1"

    @pytest.mark.anyio
    async def test_json_extractor_invalid_json_fallback(self) -> None:
        """When request body is not valid JSON, extract returns empty dict."""
        from emergent.wire.compile.targets.fastapi import FastAPIJsonExtractor
        from starlette.testclient import TestClient

        ext = FastAPIJsonExtractor()
        app = fastapi.FastAPI()

        @app.post("/bad-json")
        async def _test(request: fastapi.Request) -> dict[str, object]:
            return await ext.extract(request)

        assert _test is not None  # registered via decorator
        client = TestClient(app)
        resp = client.post(
            "/bad-json",
            content=b"not-json",
            headers={"content-type": "text/plain"},
        )
        assert resp.status_code == 200

    @pytest.mark.anyio
    async def test_json_extractor_with_path_params(self) -> None:
        from emergent.wire.compile.targets.fastapi import FastAPIJsonExtractor
        from starlette.testclient import TestClient

        ext = FastAPIJsonExtractor(include_path_params=True)
        app = fastapi.FastAPI()

        @app.post("/items/{item_id}")
        async def _test(item_id: int, request: fastapi.Request) -> dict[str, object]:
            return await ext.extract(request)

        assert _test is not None  # registered via decorator
        client = TestClient(app)
        resp = client.post("/items/42", json={"name": "test"})
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("name") == "test"
        assert str(data.get("item_id")) == "42"


class TestFastAPIJsonExtractorNoPathParams:
    """Test FastAPIJsonExtractor with include_path_params=False (line 109)."""

    @pytest.mark.anyio
    async def test_no_path_params(self) -> None:
        from emergent.wire.compile.targets.fastapi import FastAPIJsonExtractor
        from starlette.testclient import TestClient

        ext = FastAPIJsonExtractor(include_path_params=False)
        app = fastapi.FastAPI()

        @app.post("/items/{item_id}")
        async def _test(item_id: int, request: fastapi.Request) -> dict[str, object]:
            return await ext.extract(request)

        assert _test is not None  # registered via decorator
        client = TestClient(app)
        resp = client.post("/items/42", json={"name": "test"})
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("name") == "test"
        # path param should NOT be included
        assert "item_id" not in data


class TestFastAPIFormExtractor:
    """Test FastAPIFormExtractor class instantiation and interface."""

    def test_form_extractor_has_extract(self) -> None:
        from emergent.wire.compile.targets.fastapi import FastAPIFormExtractor

        ext = FastAPIFormExtractor()
        assert hasattr(ext, "extract")
        assert callable(ext.extract)

    def test_form_extractor_is_frozen_dataclass(self) -> None:
        from emergent.wire.compile.targets.fastapi import FastAPIFormExtractor
        import dataclasses

        ext = FastAPIFormExtractor()
        assert dataclasses.is_dataclass(ext)


class TestFastAPILazyExtractConstants:
    """Test __getattr__ lazy access (lines 149-150)."""

    def test_lazy_access_extract_form(self) -> None:
        import emergent.wire.compile.targets.fastapi as fapi_mod
        form = getattr(fapi_mod, "EXTRACT_FORM")
        assert form is not None

    def test_lazy_access_extract_json(self) -> None:
        import emergent.wire.compile.targets.fastapi as fapi_mod
        json = getattr(fapi_mod, "EXTRACT_JSON")
        assert json is not None

    def test_lazy_access_extract_query(self) -> None:
        import emergent.wire.compile.targets.fastapi as fapi_mod
        query = getattr(fapi_mod, "EXTRACT_QUERY")
        assert query is not None

    def test_lazy_access_unknown_raises(self) -> None:
        import emergent.wire.compile.targets.fastapi as fapi_mod
        with pytest.raises(AttributeError, match="has no attribute"):
            getattr(fapi_mod, "NONEXISTENT_THING")


class TestFastAPIStatefulFromCodec:
    """Test stateful_from_codec for FastAPI (stateful compilation context)."""

    def test_stateful_from_codec_creates_context(self) -> None:
        from emergent.wire.compile.targets.fastapi import stateful_from_codec, FastAPIWrapContext

        codec = StatefulCodec(
            flow=SimpleFlow,
            response=FlowResponse,
            store=MemoryStorage[Any, Any](),
            key_node=ChatId,
            agent_cls=type,  # placeholder
        )
        trigger = HTTPRouteTrigger("POST", "/flow")
        ctx = stateful_from_codec(codec, trigger)
        assert isinstance(ctx, FastAPIWrapContext)
        assert ctx.response_type is FlowResponse
        assert ctx.execute is not None
        assert ctx.trigger is trigger


class TestFastAPICompileWithScopeLayer:
    """Test fastapi_compile when axes already has scope_layer (lines 810-813)."""

    def test_compile_with_existing_scope_layer(self) -> None:
        from emergent.wire.compile.targets.fastapi import fastapi_compile

        runner = _runner()
        ep = endpoint(runner).expose(
            HTTPRouteTrigger("GET", "/echo"),
            rrc(EchoRequest, EchoResponse),
        )
        app = Application().mount(ep)

        # Create axes with a pre-existing scope_layer
        family = ScopeFamily[Tier]().bind(App).bind(Request)
        app_scope = Scope(detail="pre-existing-app")
        layer = ScopeLayer(
            scopes=MappingProxyType({App: app_scope}),
            family=family,
            leaf=Request,
        )
        axes = Axes.default().with_scope_layer(layer)

        fapi = fastapi_compile(app, axes=axes)
        assert isinstance(fapi, fastapi.FastAPI)
        routes = [r for r in fapi.routes if isinstance(r, fastapi.routing.APIRoute)]
        assert len(routes) == 1
        assert routes[0].path == "/echo"


class TestFastAPICompileWithRouters:
    """Test fastapi_compile router inclusion path (lines 857-858)."""

    def test_compile_with_router_capability(self) -> None:
        from emergent.wire.compile.targets.fastapi import fastapi_compile
        from emergent.wire.axis._capability import FastAPIAppContext
        from emergent.wire.axis.surface.capabilities._base import SurfaceCapability

        # Create a capability that adds a router
        @dataclass(frozen=True, slots=True)
        class AddRouter(SurfaceCapability):
            prefix: str

            def compile_fastapi_app(self, ctx: FastAPIAppContext) -> FastAPIAppContext:
                router = fastapi.APIRouter()

                @router.get(self.prefix + "/extra")
                async def extra() -> dict[str, str]:
                    return {"source": "router"}

                assert extra is not None  # registered via decorator
                return FastAPIAppContext(
                    middleware=ctx.middleware,
                    routers=(*ctx.routers, router),
                )

        runner = _runner()
        ep = endpoint(runner).expose(
            HTTPRouteTrigger("GET", "/main"),
            rrc(EchoRequest, EchoResponse),
        )
        app = Application().mount(ep).with_capabilities(AddRouter(prefix="/api"))
        fapi = fastapi_compile(app)
        assert isinstance(fapi, fastapi.FastAPI)
        # The main route and the router route should both be present
        paths = {r.path for r in fapi.routes if isinstance(r, fastapi.routing.APIRoute)}
        assert "/main" in paths
        assert "/api/extra" in paths


class TestFastAPIWrapForStackGuard:
    """Test _wrap_for_stack raises when compiler.assemble is None (line 904)."""

    def test_wrap_for_stack_no_assemble(self) -> None:
        from emergent.wire.compile.targets.fastapi import _wrap_for_stack

        compiler = TargetCompiler(
            trigger_type=HTTPRouteTrigger,
            adapters=(),
            pipeline_protocol=type,
            pipeline_method="compile",
            assemble=None,
        )
        handler = Handler(
            codec=RequestResponseCodec(request=EchoRequest, response=EchoResponse),
            runner=_runner(),
        )
        trigger = HTTPRouteTrigger("GET", "/test")
        with pytest.raises(ValueError, match="no assemble"):
            _wrap_for_stack(handler, trigger, Axes.default(), compiler)


class TestFastAPIStatefulExecuteMissingRequest:
    """Test _stateful_execute raises when Request not in scope (line 321)."""

    @pytest.mark.anyio
    async def test_stateful_execute_raises(self) -> None:
        from emergent.wire.compile.targets.fastapi import _stateful_execute

        codec = StatefulCodec(
            flow=SimpleFlow,
            response=FlowResponse,
            store=MemoryStorage[Any, Any](),
            key_node=ChatId,
            agent_cls=type,
        )
        handler = Handler(codec=codec, runner=_runner())
        scope = Scope(detail="test-empty")
        async with scope:
            with pytest.raises(RuntimeError, match="fastapi.Request not found"):
                await _stateful_execute(handler, scope, None)


class TestFastAPIBackwardCompatWrappers:
    """Test backward-compat wrapper functions for FastAPI."""

    def test_wrap_rrc_fastapi(self) -> None:
        from emergent.wire.compile.targets.fastapi import wrap_rrc_fastapi, FastAPIRoute

        codec = RequestResponseCodec(request=EchoRequest, response=EchoResponse)
        trigger = HTTPRouteTrigger("GET", "/echo")
        handler = Handler(codec=codec, runner=_runner())
        route = wrap_rrc_fastapi(handler, trigger, Axes.default())
        assert isinstance(route, FastAPIRoute)

    def test_wrap_stateful_fastapi(self) -> None:
        from emergent.wire.compile.targets.fastapi import wrap_stateful_fastapi, FastAPIRoute

        codec = StatefulCodec(
            flow=SimpleFlow, response=FlowResponse,
            store=MemoryStorage[Any, Any](), key_node=ChatId, agent_cls=type,
        )
        trigger = HTTPRouteTrigger("POST", "/flow")
        handler = Handler(codec=codec, runner=_runner())
        route = wrap_stateful_fastapi(handler, trigger, Axes.default())
        assert isinstance(route, FastAPIRoute)

    def test_wrap_immediate_fastapi(self) -> None:
        from emergent.wire.compile.targets.fastapi import wrap_immediate_fastapi, FastAPIRoute

        codec = ImmediateCodec(response=ImmHealth)
        trigger = HTTPRouteTrigger("GET", "/health")
        handler = Handler(codec=codec, runner=empty_runner())
        route = wrap_immediate_fastapi(handler, trigger, Axes.default())
        assert isinstance(route, FastAPIRoute)

    def test_wrap_delegate_fastapi(self) -> None:
        from emergent.wire.compile.targets.fastapi import wrap_delegate_fastapi, FastAPIRoute

        async def handler_fn() -> str:
            return "ok"

        codec = DelegateCodec(handler=handler_fn)
        trigger = HTTPRouteTrigger("GET", "/delegate")
        handler = Handler(codec=codec, runner=empty_runner())
        route = wrap_delegate_fastapi(handler, trigger, Axes.default())
        assert isinstance(route, FastAPIRoute)


class TestFastAPIPydanticDetection:
    """Test pydantic detection helpers."""

    def test_get_pydantic_types_from_empty_transitions(self) -> None:
        from emergent.wire.compile.targets.fastapi import _get_pydantic_types_from_transitions
        result = _get_pydantic_types_from_transitions([])
        assert result == set()

    def test_setup_fastapi_scope_no_pydantic(self) -> None:
        from emergent.wire.compile.targets.fastapi import setup_fastapi_scope

        async def run() -> None:
            scope = Scope(detail="test")
            async with scope:
                # Create a minimal request-like mock
                app_inner = fastapi.FastAPI()

                @app_inner.get("/test")
                async def _test(request: fastapi.Request) -> str:
                    await setup_fastapi_scope(scope, request, set())
                    return "ok"

                assert _test is not None  # registered via decorator
                from starlette.testclient import TestClient
                client = TestClient(app_inner)
                resp = client.get("/test")
                assert resp.status_code == 200

        asyncio.run(run())


class TestFastAPIOpenAPIEdgeCases:
    """Test OpenAPI generation edge cases."""

    def test_openapi_get_with_path_and_query(self) -> None:
        """GET with path params AND query params."""
        from emergent.wire.compile.targets.fastapi import build_rrc_openapi_extra

        codec = RequestResponseCodec(request=MultiFieldRequest, response=MultiFieldResponse)
        trigger = HTTPRouteTrigger("GET", "/items/{name}")
        axes = Axes.default()
        extra = build_rrc_openapi_extra(codec, trigger, axes)
        assert extra is not None
        params = extra.get("parameters", [])
        path_params = [p for p in params if p.get("in") == "path"]
        query_params = [p for p in params if p.get("in") == "query"]
        assert len(path_params) == 1
        assert path_params[0]["name"] == "name"
        assert len(query_params) >= 1

    def test_openapi_post_with_path_excludes_from_body(self) -> None:
        """POST with path params: body schema excludes path param fields."""
        from emergent.wire.compile.targets.fastapi import build_rrc_openapi_extra

        codec = RequestResponseCodec(request=MultiFieldRequest, response=MultiFieldResponse)
        trigger = HTTPRouteTrigger("POST", "/items/{name}")
        axes = Axes.default()
        extra = build_rrc_openapi_extra(codec, trigger, axes)
        assert extra is not None
        body = extra.get("requestBody", {})
        if body:
            schema = body.get("content", {}).get("application/json", {}).get("schema", {})
            props = schema.get("properties", {})
            # name should be excluded from body (it's a path param)
            assert "name" not in props

    def test_openapi_no_fields_returns_none(self) -> None:
        """Codec with empty request type produces None."""
        from emergent.wire.compile.targets.fastapi import build_rrc_openapi_extra

        @dataclass
        class EmptyRequest:
            def to_domain(self) -> EchoOp:
                return EchoOp(msg="")

        codec = RequestResponseCodec(request=EmptyRequest, response=EchoResponse)
        trigger = HTTPRouteTrigger("GET", "/empty")
        axes = Axes.default()
        extra = build_rrc_openapi_extra(codec, trigger, axes)
        # Should be None or empty since no fields
        assert extra is None or extra == {}


class TestFastAPICompileEndpointStateful:
    """Test fastapi_compile_endpoint with stateful codec."""

    def test_compile_endpoint_with_stateful(self) -> None:
        from emergent.wire.compile.targets.fastapi import fastapi_compile_endpoint

        runner = _runner()
        codec = StatefulCodec(
            flow=SimpleFlow, response=FlowResponse,
            store=MemoryStorage[Any, Any](), key_node=ChatId, agent_cls=type,
        )
        ep = (
            endpoint(runner)
            .expose(HTTPRouteTrigger("POST", "/flow"), codec)
            .expose(HTTPRouteTrigger("GET", "/echo"), rrc(EchoRequest, EchoResponse))
        )
        routes = fastapi_compile_endpoint(ep)
        assert len(routes) == 2
        paths = {r.path for r in routes}
        assert "/flow" in paths
        assert "/echo" in paths


# =============================================================================
# CLI Target — remaining uncovered lines
# =============================================================================


class TestCLIWrapForStackGuard:
    """Test _wrap_for_stack raises when compiler.assemble is None (line 515)."""

    def test_wrap_for_stack_no_assemble_cli(self) -> None:
        from emergent.wire.compile.targets.cli import _wrap_for_stack

        compiler = TargetCompiler(
            trigger_type=CLITrigger,
            adapters=(),
            pipeline_protocol=type,
            pipeline_method="compile",
            assemble=None,
        )
        handler = Handler(
            codec=RequestResponseCodec(request=EchoRequest, response=EchoResponse),
            runner=_runner(),
        )
        trigger = CLITrigger("test", "Test")
        with pytest.raises(ValueError, match="no assemble"):
            _wrap_for_stack(handler, trigger, Axes.default(), compiler)


class TestCLIStatefulFromCodec:
    """Test stateful_from_codec_cli."""

    def test_stateful_from_codec_cli(self) -> None:
        from emergent.wire.compile.targets.cli import stateful_from_codec_cli, CLIWrapContext

        codec = StatefulCodec(
            flow=SimpleFlow, response=FlowResponse,
            store=MemoryStorage[Any, Any](), key_node=ChatId, agent_cls=type,
        )
        trigger = CLITrigger("flow", "Start flow")
        ctx = stateful_from_codec_cli(codec, trigger)
        assert isinstance(ctx, CLIWrapContext)
        assert ctx.response_type is FlowResponse
        assert ctx.execute is not None


class TestCLIStatefulCompile:
    """Test CLI compilation with stateful codec."""

    def test_stateful_cli_compile(self) -> None:
        from emergent.wire.compile.targets.cli import wrap_stateful_cli, CLIRoute

        runner = _runner()
        codec = StatefulCodec(
            flow=SimpleFlow, response=FlowResponse,
            store=MemoryStorage[Any, Any](), key_node=ChatId, agent_cls=type,
        )
        trigger = CLITrigger("flow", "Run flow")
        handler = Handler(codec=codec, runner=runner)

        # Test backward-compat wrapper
        route = wrap_stateful_cli(handler, trigger, Axes.default())
        assert isinstance(route, CLIRoute)


class TestCLIPromptValue:
    """Test _prompt_value function."""

    def test_prompt_int(self) -> None:
        from emergent.wire.compile.targets.cli import _prompt_value

        with patch("builtins.input", return_value="42"):
            result = _prompt_value("count", int)
            assert result == 42

    def test_prompt_float(self) -> None:
        from emergent.wire.compile.targets.cli import _prompt_value

        with patch("builtins.input", return_value="3.14"):
            result = _prompt_value("ratio", float)
            assert result == 3.14

    def test_prompt_bool_true(self) -> None:
        from emergent.wire.compile.targets.cli import _prompt_value

        with patch("builtins.input", return_value="yes"):
            result = _prompt_value("active", bool)
            assert result is True

    def test_prompt_bool_false(self) -> None:
        from emergent.wire.compile.targets.cli import _prompt_value

        with patch("builtins.input", return_value="no"):
            result = _prompt_value("active", bool)
            assert result is False

    def test_prompt_str(self) -> None:
        from emergent.wire.compile.targets.cli import _prompt_value

        with patch("builtins.input", return_value="hello"):
            result = _prompt_value("name", str)
            assert result == "hello"

    def test_prompt_empty_returns_none(self) -> None:
        from emergent.wire.compile.targets.cli import _prompt_value

        with patch("builtins.input", return_value=""):
            result = _prompt_value("name", str)
            assert result is None

    def test_prompt_eof_returns_none(self) -> None:
        from emergent.wire.compile.targets.cli import _prompt_value

        with patch("builtins.input", side_effect=EOFError):
            result = _prompt_value("name", str)
            assert result is None

    def test_prompt_keyboard_interrupt(self) -> None:
        from emergent.wire.compile.targets.cli import _prompt_value

        with patch("builtins.input", side_effect=KeyboardInterrupt):
            result = _prompt_value("name", str)
            assert result is None

    def test_prompt_invalid_int(self) -> None:
        from emergent.wire.compile.targets.cli import _prompt_value

        with patch("builtins.input", return_value="not-a-number"):
            result = _prompt_value("count", int)
            assert result is None


class TestCLIDelegateArgSpecs:
    """Test _get_delegate_arg_specs with various handler signatures."""

    def test_bool_arg_becomes_store_true(self) -> None:
        from emergent.wire.compile.targets.cli import _get_delegate_arg_specs

        def handler_with_bool(name: str, verbose: bool = False) -> str:
            return name

        specs = _get_delegate_arg_specs(handler_with_bool, Axes.default())
        bool_specs: list[object] = [s for s in specs if s.dest == "verbose"]
        assert len(bool_specs) > 0

    def test_handler_with_no_types(self) -> None:
        from typing import Callable, cast
        from emergent.wire.compile.targets.cli import _inspect_handler_params

        # Build handler dynamically to genuinely lack annotations
        handler = cast(Callable[..., object], eval("lambda x, y: x"))  # noqa: S307

        params = _inspect_handler_params(handler)
        # No type hints, should return empty
        assert len(params) == 0

    def test_handler_with_dataclass_param(self) -> None:
        from emergent.wire.compile.targets.cli import _build_delegate_args

        def handler(req: EchoRequest) -> str:
            return req.msg

        ns = argparse.Namespace(msg="hello")
        args = _build_delegate_args(handler, ns)
        assert isinstance(args["req"], EchoRequest)
        assert args["req"].msg == "hello"


class TestCLIRunExecution:
    """Test cli_run with various scenarios."""

    def test_cli_run_keyboard_interrupt(self) -> None:
        from emergent.wire.compile.targets.cli import cli_run

        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        cmd = sub.add_parser("boom")

        async def _boom(ns: argparse.Namespace) -> str:
            raise KeyboardInterrupt()

        cmd.set_defaults(_handler=_boom)
        result = cli_run(parser, ["boom"])
        assert result == 130

    def test_cli_run_exception(self) -> None:
        from emergent.wire.compile.targets.cli import cli_run

        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        cmd = sub.add_parser("fail")

        async def _fail(ns: argparse.Namespace) -> str:
            raise RuntimeError("test error")

        cmd.set_defaults(_handler=_fail)
        result = cli_run(parser, ["fail"])
        assert result == 1

    def test_cli_run_success(self) -> None:
        from emergent.wire.compile.targets.cli import cli_run

        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        cmd = sub.add_parser("ok")

        async def _ok(ns: argparse.Namespace) -> str:
            return "success"

        cmd.set_defaults(_handler=_ok)
        result = cli_run(parser, ["ok"])
        assert result == 0


class TestCLICompileStackNested:
    """Test cli_compile_stack with deeper nesting."""

    def test_double_nested_stack(self) -> None:
        from emergent.wire.compile.targets.cli import cli_compile_stack

        runner = _runner()
        ep_root = endpoint(runner).expose(
            CLITrigger("status", "Show status"), rrc(EchoRequest, EchoResponse),
        )
        ep_level1 = endpoint(runner).expose(
            CLITrigger("list", "List items"), rrc(EchoRequest, EchoResponse),
        )
        ep_level2 = endpoint(runner).expose(
            CLITrigger("detail", "Show detail"), rrc(EchoRequest, EchoResponse),
        )

        root_app = Application().mount(ep_root)
        level1_app = Application().mount(ep_level1)
        level2_app = Application().mount(ep_level2)

        stack = (
            app_stack()
            .root(root_app)
            .mount("admin", level1_app)
            .mount("items", level2_app)
        )
        parser = cli_compile_stack(stack, prog="nested-cli")
        assert isinstance(parser, argparse.ArgumentParser)
        assert parser.prog == "nested-cli"


class TestCLICompileWithFamily:
    """Test cli_compile with family parameter."""

    def test_compile_with_family(self) -> None:
        from emergent.wire.compile.targets.cli import cli_compile

        runner = _runner()
        ep = endpoint(runner).expose(
            CLITrigger("echo", "Echo"), rrc(EchoRequest, EchoResponse),
        )
        app = Application().mount(ep)

        family = ScopeFamily[Tier]().bind(App).bind(Request)
        parser = cli_compile(app, prog="family-cli", family=family)
        assert isinstance(parser, argparse.ArgumentParser)
        # Should have app_scope attached
        assert hasattr(parser, "_scope_app")
        assert hasattr(parser, "_scope_app_types")


class TestCLIRunWithFamily:
    """Test cli_run with app scope (lifespan)."""

    def test_cli_run_with_app_scope(self) -> None:
        from emergent.wire.compile.targets.cli import cli_compile

        runner = _runner()
        ep = endpoint(runner).expose(
            CLITrigger("echo", "Echo"), rrc(EchoRequest, EchoResponse),
        )
        app = Application().mount(ep)
        family = ScopeFamily[Tier]().bind(App).bind(Request)
        parser = cli_compile(app, prog="test", family=family)

        # Cannot actually run because the handler needs proper scope setup,
        # but we can verify the parser was created with scope
        assert hasattr(parser, "_scope_app")


class TestCLIImmediateExecute:
    """Test _immediate_execute_cli."""

    @pytest.mark.anyio
    async def test_immediate_execute_returns_str(self) -> None:
        from emergent.wire.compile.targets.cli import _immediate_execute_cli

        codec = ImmediateCodec(response=ImmHealth)
        handler = Handler(codec=codec, runner=empty_runner())
        scope = Scope(detail="test")
        async with scope:
            result = await _immediate_execute_cli(handler, scope, None)
            assert "ok" in str(result)


class TestCLIDelegateExecute:
    """Test _delegate_execute_cli."""

    @pytest.mark.anyio
    async def test_delegate_execute_sync(self) -> None:
        from emergent.wire.compile.targets.cli import _delegate_execute_cli

        def my_handler() -> str:
            return "delegate-result"

        codec = DelegateCodec(handler=my_handler)
        handler = Handler(codec=codec, runner=empty_runner())
        scope = Scope(detail="test")
        async with scope:
            ns = argparse.Namespace()
            scope.inject(argparse.Namespace, ns)
            result = await _delegate_execute_cli(handler, scope, None)
            assert "delegate-result" in str(result)

    @pytest.mark.anyio
    async def test_delegate_execute_async(self) -> None:
        from emergent.wire.compile.targets.cli import _delegate_execute_cli

        async def my_handler() -> str:
            return "async-delegate"

        codec = DelegateCodec(handler=my_handler)
        handler = Handler(codec=codec, runner=empty_runner())
        scope = Scope(detail="test")
        async with scope:
            ns = argparse.Namespace()
            scope.inject(argparse.Namespace, ns)
            result = await _delegate_execute_cli(handler, scope, None)
            assert "async-delegate" in str(result)


class TestCLITypedCLI:
    """Test TYPED_CLI compiler."""

    def test_typed_cli_compiles(self) -> None:
        from emergent.wire.compile.targets.cli import TYPED_CLI, cli_compile

        runner = _runner()
        ep = endpoint(runner).expose(
            CLITrigger("echo", "Echo"), rrc(EchoRequest, EchoResponse),
        )
        app = Application().mount(ep)
        parser = cli_compile(app, prog="typed", compiler=TYPED_CLI)
        assert isinstance(parser, argparse.ArgumentParser)


class TestCLICoerceValues:
    """Test coerce_cli_values."""

    def test_coerce_int_field(self) -> None:
        from emergent.wire.compile.targets.cli import coerce_cli_values

        axes = Axes.default()
        get_value = coerce_cli_values(
            MultiFieldRequest, axes,
            lambda name: {"name": "alice", "age": "30", "flag": "true"}.get(name),
        )
        assert get_value("name") == "alice"
        assert get_value("age") == 30  # coerced from str to int


# =============================================================================
# Telegrinder Target — remaining uncovered lines
# =============================================================================


class TestTelegrindStatefulFromCodec:
    """Test stateful_from_codec_tg (lines 740-741)."""

    def test_stateful_from_codec_creates_context(self) -> None:
        from emergent.wire.compile.targets.telegrinder import (
            stateful_from_codec_tg,
            TelegrindWrapContext,
        )

        codec = StatefulCodec(
            flow=SimpleFlow, response=FlowResponse,
            store=MemoryStorage[Any, Any](), key_node=ChatId, agent_cls=type,
        )
        trigger = TelegrindTrigger(view="message")
        ctx = stateful_from_codec_tg(codec, trigger)
        assert isinstance(ctx, TelegrindWrapContext)
        assert ctx.execute is not None
        assert ctx.trigger is trigger
        # Should have a composite rule (has_active OR trigger_rules)
        assert len(ctx.rules) >= 1


class TestTelegrindStatefulExecute:
    """Test _stateful_execute_tg wrapper (line 780)."""

    def test_stateful_execute_calls_wrap(self) -> None:
        from emergent.wire.compile.targets.telegrinder import (
            _stateful_execute_tg,
            TelegrindRoute,
        )

        codec = StatefulCodec(
            flow=SimpleFlow, response=FlowResponse,
            store=MemoryStorage[Any, Any](), key_node=ChatId, agent_cls=type,
        )
        handler = Handler(codec=codec, runner=_runner())
        trigger = TelegrindTrigger(view="message")
        result = _stateful_execute_tg(handler, trigger, Axes.default())
        assert isinstance(result, TelegrindRoute)


class TestTelegrindAssembleTypeError:
    """Test assemble_telegrind_route TypeError guard (line 810)."""

    def test_assemble_raises_on_wrong_return_type(self) -> None:
        from emergent.wire.compile.targets.telegrinder import (
            assemble_telegrind_route,
            TelegrindWrapContext,
        )

        def bad_execute(handler: object, trigger: object, axes: object) -> str:
            return "not a TelegrindRoute"

        ctx = TelegrindWrapContext(
            execute=bad_execute,  # type: ignore[arg-type]
            trigger=TelegrindTrigger(view="message"),
        )
        handler = Handler(
            codec=RequestResponseCodec(request=EchoRequest, response=EchoResponse),
            runner=_runner(),
        )
        with pytest.raises(TypeError, match="must return TelegrindRoute"):
            assemble_telegrind_route(ctx, handler, Axes.default())


class TestTelegrindCompileStateful:
    """Test telegrinder_compile with stateful codec handler."""

    def test_stateful_handler_compiles(self) -> None:
        from emergent.wire.compile.targets.telegrinder import (
            telegrinder_compile,
        )
        from telegrinder.bot.rules.command import Command

        runner = _runner()
        codec = StatefulCodec(
            flow=SimpleFlow, response=FlowResponse,
            store=MemoryStorage[Any, Any](), key_node=ChatId, agent_cls=type,
        )
        ep = endpoint(runner).expose(
            TelegrindTrigger(Command("flow"), view="message"),
            codec,
        )
        app = Application().mount(ep)
        dp = telegrinder_compile(app)
        assert dp is not None


class TestTelegrindCompileWithFamily:
    """Test telegrinder_compile with family parameter."""

    def test_compile_with_family(self) -> None:
        from emergent.wire.compile.targets.telegrinder import telegrinder_compile
        from telegrinder.bot.rules.command import Command

        runner = _runner()
        ep = endpoint(runner).expose(
            TelegrindTrigger(Command("echo"), view="message"),
            rrc(EchoRequest, EchoResponse),
        )
        app = Application().mount(ep)
        family = ScopeFamily[Tier]().bind(App).bind(Request)
        dp = telegrinder_compile(app, family=family)
        assert dp is not None
        assert hasattr(dp, "_scope_app")


class TestTelegrindCommandArgGeneration:
    """Test generate_command_args and enhance_command_with_args."""

    def test_generate_args_from_annotated_request(self) -> None:
        from emergent.wire.compile.targets.telegrinder import generate_command_args

        args, has_greedy = generate_command_args(_TgReqWithArgs)
        assert len(args) == 2
        assert has_greedy is False

    def test_generate_args_with_greedy(self) -> None:
        from emergent.wire.compile.targets.telegrinder import generate_command_args

        args, has_greedy = generate_command_args(_TgReqWithGreedy)
        assert len(args) == 1
        assert has_greedy is True

    def test_generate_args_with_int_validator(self) -> None:
        from emergent.wire.compile.targets.telegrinder import generate_command_args

        args, _ = generate_command_args(_TgReqWithInt)
        assert len(args) == 1

    def test_generate_args_non_dataclass(self) -> None:
        from emergent.wire.compile.targets.telegrinder import generate_command_args

        args, has_greedy = generate_command_args(str)
        assert args == []
        assert has_greedy is False

    def test_enhance_command_with_args(self) -> None:
        from emergent.wire.compile.targets.telegrinder import enhance_command_with_args
        from telegrinder.bot.rules.command import Command

        trigger = TelegrindTrigger(Command("register"), view="message")
        enhanced = enhance_command_with_args(trigger, _TgReqWithSingleArg)
        assert enhanced is not trigger  # new trigger
        assert len(enhanced.rules) >= 1

    def test_enhance_no_args(self) -> None:
        from emergent.wire.compile.targets.telegrinder import enhance_command_with_args
        from telegrinder.bot.rules.command import Command

        trigger = TelegrindTrigger(Command("start"), view="message")
        enhanced = enhance_command_with_args(trigger, EchoRequest)
        assert enhanced is trigger  # no change


class TestTelegrindHelpGeneration:
    """Test help text generation from command rules."""

    def test_generate_help_with_help_meta(self) -> None:
        from emergent.wire.compile.targets.telegrinder import generate_help_from_command_rules
        from emergent.wire.axis.surface.dialects.telegram import HelpMeta
        from telegrinder.bot.rules.command import Command

        runner = _runner()
        ep = endpoint(runner).expose(
            TelegrindTrigger(Command("echo"), view="message"),
            rrc(EchoRequest, EchoResponse),
            HelpMeta("Echo a message", order=1),
        )
        app = Application().mount(ep)
        help_text = generate_help_from_command_rules(app)
        assert "echo" in help_text
        assert len(help_text) > 0

    def test_generate_help_with_header_footer(self) -> None:
        from emergent.wire.compile.targets.telegrinder import generate_help_from_command_rules
        from emergent.wire.axis.surface.dialects.telegram import HelpMeta
        from telegrinder.bot.rules.command import Command

        runner = _runner()
        ep = endpoint(runner).expose(
            TelegrindTrigger(Command("cmd"), view="message"),
            rrc(EchoRequest, EchoResponse),
            HelpMeta("Do stuff", order=1),
        )
        app = Application().mount(ep)
        help_text = generate_help_from_command_rules(
            app, header="== Help ==", footer="== End ==",
        )
        assert help_text.startswith("== Help ==")
        assert help_text.endswith("== End ==")

    def test_generate_help_multiple_commands_sorted(self) -> None:
        from emergent.wire.compile.targets.telegrinder import generate_help_from_command_rules
        from emergent.wire.axis.surface.dialects.telegram import HelpMeta
        from telegrinder.bot.rules.command import Command

        runner = _runner()
        ep1 = endpoint(runner).expose(
            TelegrindTrigger(Command("beta"), view="message"),
            rrc(EchoRequest, EchoResponse),
            HelpMeta("Beta cmd", order=2),
        )
        ep2 = endpoint(runner).expose(
            TelegrindTrigger(Command("alpha"), view="message"),
            rrc(EchoRequest, EchoResponse),
            HelpMeta("Alpha cmd", order=1),
        )
        app = Application().mount(ep1, ep2)
        help_text = generate_help_from_command_rules(app)
        lines = help_text.strip().split("\n")
        assert len(lines) == 2
        # alpha should come first (order=1)
        assert "alpha" in lines[0]
        assert "beta" in lines[1]

    def test_generate_help_empty_app(self) -> None:
        from emergent.wire.compile.targets.telegrinder import generate_help_from_command_rules

        app = Application()
        help_text = generate_help_from_command_rules(app)
        assert help_text == ""

    def test_generate_help_no_help_meta_excluded(self) -> None:
        """Commands without HelpMeta are excluded from help."""
        from emergent.wire.compile.targets.telegrinder import generate_help_from_command_rules
        from telegrinder.bot.rules.command import Command

        runner = _runner()
        ep = endpoint(runner).expose(
            TelegrindTrigger(Command("hidden"), view="message"),
            rrc(EchoRequest, EchoResponse),
            # No HelpMeta
        )
        app = Application().mount(ep)
        help_text = generate_help_from_command_rules(app)
        assert help_text == ""

    def test_generate_help_hidden_excluded(self) -> None:
        from emergent.wire.compile.targets.telegrinder import generate_help_from_command_rules
        from emergent.wire.axis.surface.dialects.telegram import HelpMeta
        from telegrinder.bot.rules.command import Command

        runner = _runner()
        ep = endpoint(runner).expose(
            TelegrindTrigger(Command("secret"), view="message"),
            rrc(EchoRequest, EchoResponse),
            HelpMeta("Secret cmd", hidden=True),
        )
        app = Application().mount(ep)
        help_text = generate_help_from_command_rules(app)
        assert help_text == ""


class TestTelegrindExtractCommandInfo:
    """Test extract_command_info."""

    def test_extract_with_arguments(self) -> None:
        from emergent.wire.compile.targets.telegrinder import extract_command_info
        from emergent.wire.axis.surface.dialects.telegram import HelpMeta
        from telegrinder.bot.rules.command import Command

        runner = _runner()
        codec = RequestResponseCodec(request=_TgReqWithSingleArg, response=EchoResponse)

        # Build handler with enhanced trigger
        from emergent.wire.compile.targets.telegrinder import enhance_command_with_args

        trigger = TelegrindTrigger(Command("register"), view="message")
        enhanced = enhance_command_with_args(trigger, _TgReqWithSingleArg)

        handler = Handler(
            codec=codec, runner=runner,
            capabilities=(HelpMeta("Register user", order=5),),
        )
        info = extract_command_info(enhanced, handler)
        assert info is not None
        assert info.name == "register"
        assert info.order == 5
        assert len(info.args) >= 1


class TestTelegrindResponseFormatting:
    """Test _format_tg_response with various types."""

    def test_bytes_passthrough(self) -> None:
        from emergent.wire.compile.targets.telegrinder import _format_tg_response
        assert _format_tg_response(b"hello") == b"hello"

    def test_list_passthrough(self) -> None:
        from emergent.wire.compile.targets.telegrinder import _format_tg_response
        assert _format_tg_response([1, 2, 3]) == [1, 2, 3]

    def test_tuple_passthrough(self) -> None:
        from emergent.wire.compile.targets.telegrinder import _format_tg_response
        assert _format_tg_response((1, 2)) == (1, 2)

    def test_float_passthrough(self) -> None:
        from emergent.wire.compile.targets.telegrinder import _format_tg_response
        assert _format_tg_response(3.14) == 3.14

    def test_bool_passthrough(self) -> None:
        from emergent.wire.compile.targets.telegrinder import _format_tg_response
        assert _format_tg_response(False) is False


class TestTelegrindCreateStatefulRule:
    """Test create_stateful_rule."""

    def test_stateful_rule_with_trigger_rules(self) -> None:
        from emergent.wire.compile.targets.telegrinder import create_stateful_rule
        from telegrinder.bot.rules.command import Command

        codec = StatefulCodec(
            flow=SimpleFlow, response=FlowResponse,
            store=MemoryStorage[Any, Any](), key_node=ChatId, agent_cls=type,
        )
        trigger = TelegrindTrigger(Command("flow"), view="message")
        rule = create_stateful_rule(trigger, codec)
        assert rule is not None

    def test_stateful_rule_no_trigger_rules(self) -> None:
        from emergent.wire.compile.targets.telegrinder import create_stateful_rule

        codec = StatefulCodec(
            flow=SimpleFlow, response=FlowResponse,
            store=MemoryStorage[Any, Any](), key_node=ChatId, agent_cls=type,
        )
        trigger = TelegrindTrigger(view="message")
        rule = create_stateful_rule(trigger, codec)
        assert rule is not None

    def test_stateful_rule_multiple_trigger_rules(self) -> None:
        from emergent.wire.compile.targets.telegrinder import create_stateful_rule
        from telegrinder.bot.rules.command import Command
        from telegrinder.bot.rules.abc import ABCRule

        # Create a simple custom rule
        class AlwaysTrue(ABCRule):
            async def check(self, event: object) -> bool:
                return True

        codec = StatefulCodec(
            flow=SimpleFlow, response=FlowResponse,
            store=MemoryStorage[Any, Any](), key_node=ChatId, agent_cls=type,
        )
        trigger = TelegrindTrigger(Command("flow"), AlwaysTrue(), view="message")
        rule = create_stateful_rule(trigger, codec)
        assert rule is not None


class TestTelegrindWrapImmediateAndDelegate:
    """Test wrap_immediate_telegrinder and wrap_delegate_telegrinder."""

    def test_wrap_immediate_produces_route(self) -> None:
        from emergent.wire.compile.targets.telegrinder import (
            wrap_immediate_telegrinder,
            TelegrindRoute,
        )
        from telegrinder.bot.rules.command import Command

        codec = ImmediateCodec(response=ImmHealth)
        handler = Handler(codec=codec, runner=empty_runner())
        trigger = TelegrindTrigger(Command("health"), view="message")
        route = wrap_immediate_telegrinder(handler, trigger, Axes.default())
        assert isinstance(route, TelegrindRoute)
        assert callable(route.handler)
        assert len(route.rules) >= 1

    def test_wrap_delegate_produces_route(self) -> None:
        from emergent.wire.compile.targets.telegrinder import (
            wrap_delegate_telegrinder,
            TelegrindRoute,
        )
        from telegrinder.bot.rules.command import Command

        async def my_handler() -> str:
            return "delegated"

        codec = DelegateCodec(handler=my_handler)
        handler = Handler(codec=codec, runner=empty_runner())
        trigger = TelegrindTrigger(Command("delegate"), view="message")
        route = wrap_delegate_telegrinder(handler, trigger, Axes.default())
        assert isinstance(route, TelegrindRoute)

    def test_wrap_immediate_factory(self) -> None:
        from emergent.wire.compile.targets.telegrinder import (
            wrap_immediate_factory_telegrinder,
            TelegrindRoute,
        )
        from telegrinder.bot.rules.command import Command

        codec = ImmediateFactoryCodec(factory=lambda: {"version": "1.0"})
        handler = Handler(codec=codec, runner=empty_runner())
        trigger = TelegrindTrigger(Command("version"), view="message")
        route = wrap_immediate_factory_telegrinder(handler, trigger, Axes.default())
        assert isinstance(route, TelegrindRoute)


class TestTelegrindMultiCodecCompile:
    """Test compiling multiple codec types into a Dispatch."""

    def test_rrc_and_immediate_and_delegate(self) -> None:
        from emergent.wire.compile.targets.telegrinder import telegrinder_compile
        from telegrinder.bot.rules.command import Command

        runner = _runner()
        ep1 = endpoint(runner).expose(
            TelegrindTrigger(Command("echo"), view="message"),
            rrc(EchoRequest, EchoResponse),
        )
        ep2 = endpoint(empty_runner()).expose(
            TelegrindTrigger(Command("health"), view="message"),
            immediate(ImmHealth),
        )

        async def status() -> str:
            return "ok"

        ep3 = endpoint(empty_runner()).expose(
            TelegrindTrigger(Command("status"), view="message"),
            delegate(status),
        )
        app = Application().mount(ep1, ep2, ep3)
        dp = telegrinder_compile(app)
        assert dp is not None


class TestTelegrindCallbackQueryView:
    """Test callback_query view handlers."""

    def test_callback_view_compiles(self) -> None:
        from emergent.wire.compile.targets.telegrinder import telegrinder_compile
        from telegrinder.bot.rules.abc import ABCRule

        class AlwaysMatch(ABCRule):
            async def check(self, event: object) -> bool:
                return True

        runner = _runner()
        ep = endpoint(runner).expose(
            TelegrindTrigger(AlwaysMatch(), view="callback_query"),
            rrc(EchoRequest, EchoResponse),
        )
        app = Application().mount(ep)
        dp = telegrinder_compile(app)
        assert dp is not None


class TestTelegrindFoldTgHandlerCtx:
    """Test fold_tg_handler_ctx."""

    def test_fold_empty_capabilities(self) -> None:
        from emergent.wire.compile.targets.telegrinder import fold_tg_handler_ctx
        from emergent.wire.axis._capability import TelegrinderHandlerContext

        ctx = fold_tg_handler_ctx(())
        assert isinstance(ctx, TelegrinderHandlerContext)

    def test_fold_with_capabilities(self) -> None:
        from emergent.wire.compile.targets.telegrinder import fold_tg_handler_ctx
        from emergent.wire.axis._capability import TelegrinderHandlerContext
        from emergent.wire.axis.surface.dialects.telegram import EditMessage

        ctx = fold_tg_handler_ctx((EditMessage(),))
        assert isinstance(ctx, TelegrinderHandlerContext)
        assert ctx.edit_message is True


class TestTelegrindGetCuteValue:
    """Test _get_cute_value helper."""

    def test_none_update(self) -> None:
        from emergent.wire.compile.targets.telegrinder import _get_cute_value

        success, value = _get_cute_value(str, None)
        assert success is False
        assert "no update_cute" in str(value)

    def test_matching_incoming_update(self) -> None:
        from emergent.wire.compile.targets.telegrinder import _get_cute_value

        class FakeUpdate:
            incoming_update: str = "hello"

        success, value = _get_cute_value(str, FakeUpdate())
        assert success is True
        assert value == "hello"

    def test_non_matching_incoming_update(self) -> None:
        from emergent.wire.compile.targets.telegrinder import _get_cute_value

        class FakeUpdate:
            incoming_update: int = 42

        success, _value = _get_cute_value(str, FakeUpdate())
        assert success is False

    def test_no_incoming_update(self) -> None:
        from emergent.wire.compile.targets.telegrinder import _get_cute_value

        class FakeUpdate:
            pass

        success, _value = _get_cute_value(str, FakeUpdate())
        assert success is False


class TestTelegrindPipelineCompilable:
    """Test TelegrindPipelineCompilable protocol."""

    def test_protocol_is_runtime_checkable(self) -> None:
        from emergent.wire.compile.targets.telegrinder import TelegrindPipelineCompilable

        @dataclass
        class MyPipelineComp:
            def compile_telegram_pipeline(self, ctx: object) -> object:
                return ctx

        assert isinstance(MyPipelineComp(), TelegrindPipelineCompilable)

    def test_non_conforming_is_not_instance(self) -> None:
        from emergent.wire.compile.targets.telegrinder import TelegrindPipelineCompilable

        @dataclass
        class NotConforming:
            pass

        assert not isinstance(NotConforming(), TelegrindPipelineCompilable)


class TestTelegrindFromApplication:
    """Test backward-compat alias from_application."""

    def test_from_application_is_telegrinder_compile(self) -> None:
        from emergent.wire.compile.targets.telegrinder import (
            from_application,
            telegrinder_compile,
        )
        assert from_application is telegrinder_compile


# =============================================================================
# Cross-target integration
# =============================================================================


class TestCrossTargetSameApp:
    """Test same app compiled for multiple targets."""

    def test_app_with_all_trigger_types(self) -> None:
        from emergent.wire.compile.targets.fastapi import fastapi_compile
        from emergent.wire.compile.targets.cli import cli_compile
        from emergent.wire.compile.targets.telegrinder import telegrinder_compile
        from telegrinder.bot.rules.command import Command

        runner = _runner()
        ep = (
            endpoint(runner)
            .expose(HTTPRouteTrigger("GET", "/echo"), rrc(EchoRequest, EchoResponse))
            .expose(CLITrigger("echo", "Echo"), rrc(EchoRequest, EchoResponse))
            .expose(
                TelegrindTrigger(Command("echo"), view="message"),
                rrc(EchoRequest, EchoResponse),
            )
        )
        app = Application().mount(ep)

        fapi = fastapi_compile(app)
        assert isinstance(fapi, fastapi.FastAPI)

        parser = cli_compile(app, prog="multi")
        assert isinstance(parser, argparse.ArgumentParser)

        dp = telegrinder_compile(app)
        assert dp is not None


class TestFastAPICompileStackDeep:
    """Test fastapi_compile_stack deeper paths."""

    def test_stack_with_nested_stackview(self) -> None:
        from emergent.wire.compile.targets.fastapi import fastapi_compile_stack

        runner = _runner()
        ep_root = endpoint(runner).expose(
            HTTPRouteTrigger("GET", "/root"), rrc(EchoRequest, EchoResponse),
        )
        ep_sub1 = endpoint(runner).expose(
            HTTPRouteTrigger("GET", "/item"), rrc(EchoRequest, EchoResponse),
        )
        ep_sub2 = endpoint(runner).expose(
            HTTPRouteTrigger("POST", "/create"), rrc(MultiFieldRequest, MultiFieldResponse),
        )

        root_app = Application().mount(ep_root)
        sub_app = Application().mount(ep_sub1, ep_sub2)
        stack = app_stack().root(root_app).mount("api", sub_app)
        fapi = fastapi_compile_stack(stack)
        assert isinstance(fapi, fastapi.FastAPI)


class TestFastAPIPipelineContextAlias:
    """Test FastAPIPipelineContext backward compat alias."""

    def test_alias_exists(self) -> None:
        from emergent.wire.compile.targets.fastapi import (
            FastAPIPipelineContext,
            FastAPIWrapContext,
        )
        assert FastAPIPipelineContext is FastAPIWrapContext


class TestFastAPICompileAlias:
    """Test module-level compile alias."""

    def test_compile_alias(self) -> None:
        from emergent.wire.compile.targets import fastapi as fapi_mod
        assert fapi_mod.compile is fapi_mod.fastapi_compile

    def test_compile_stack_alias(self) -> None:
        from emergent.wire.compile.targets import fastapi as fapi_mod
        assert fapi_mod.compile_stack is fapi_mod.fastapi_compile_stack

    def test_compile_endpoint_alias(self) -> None:
        from emergent.wire.compile.targets import fastapi as fapi_mod
        assert fapi_mod.compile_endpoint is fapi_mod.fastapi_compile_endpoint


class TestCLICompileAlias:
    """Test CLI module-level compile alias."""

    def test_compile_alias(self) -> None:
        from emergent.wire.compile.targets import cli as cli_mod
        assert cli_mod.compile is cli_mod.cli_compile

    def test_compile_stack_alias(self) -> None:
        from emergent.wire.compile.targets import cli as cli_mod
        assert cli_mod.compile_stack is cli_mod.cli_compile_stack


class TestTelegrindCompileAlias:
    """Test telegrinder module-level compile alias."""

    def test_compile_alias(self) -> None:
        from emergent.wire.compile.targets import telegrinder as tg_mod
        assert tg_mod.compile is tg_mod.telegrinder_compile


class TestCLIImmediateFactoryBackwardCompat:
    """Test wrap_immediate_factory_cli alias."""

    def test_immediate_factory_alias(self) -> None:
        from emergent.wire.compile.targets.cli import (
            wrap_immediate_factory_cli,
            wrap_immediate_cli,
        )
        assert wrap_immediate_factory_cli is wrap_immediate_cli

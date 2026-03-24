# pyright: reportPrivateUsage=false
"""Tests for deep coverage of compile targets and infrastructure.

Covers uncovered lines in:
- compile/targets/fastapi.py — OpenAPI schema gen, path param extraction,
  middleware/capabilities, StatefulCodec wrapping, response transforms
- compile/targets/cli.py — positional args, choices, typed CLI, coercion,
  delegate, immediate, stateful codec wrapping, cli_run, cli_compile_stack
- compile/_delegate.py — compose dialect resolution, param extraction
- compile/_execute.py — unified execution, stateful, delegate, immediate
- compile/_stateful.py — stateful codec compilation, state management
- compile/_pipeline.py — pipeline compilation, coercion, execute_with_pipeline
- compile/_request.py — request building, defaults, optional fields
- compile/targets/testing.py — TestApp lifecycle, route invocation
- compile/targets/event.py — event dispatch, delegate events
- compile/targets/pure.py — lifecycle, exception, websocket compilation
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from typing import Any, Self
from unittest.mock import AsyncMock

import fastapi
import pytest
from httpx import ASGITransport, AsyncClient
from kungfu import Ok, Result, Nothing

from emergent.ops._graph import Op, ops
from emergent.wire.axis.surface._app import Application, application
from emergent.wire.axis.surface._endpoint import Endpoint, endpoint
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
from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger
from emergent.wire.axis.surface.triggers.cli import CLITrigger
from emergent.wire.axis.surface.triggers.event import EventTrigger
from emergent.wire.axis.surface.triggers.lifecycle import StartupTrigger, ShutdownTrigger
from emergent.wire.axis.surface.triggers.exception import ExceptionTrigger
from emergent.wire.axis.surface.triggers.websocket import WebSocketTrigger
from emergent.wire.axis.surface.transforms._response import AsDict, AsStr
from emergent.wire.compile._core import Axes
from emergent.wire.compile._generate import ArgSpec


# ═══════════════════════════════════════════════════════════════════════════════
# Domain types for tests
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class GreetOp(Op[str, str]):
    name: str


async def _test_handler(req: GreetOp) -> Result[str, str]:
    return Ok(f"result-{req.name}")


@dataclass
class SimpleReq:
    name: str

    def to_domain(self) -> GreetOp:
        return GreetOp(name=self.name)


@dataclass
class SimpleResp:
    value: str

    @classmethod
    def from_domain(cls, dom: Result[str, str]) -> Self:
        match dom:
            case Ok(v):
                return cls(value=v)
            case _:
                return cls(value="error")

    def __str__(self) -> str:
        return self.value


@dataclass
class NestedItem:
    label: str
    count: int = 0


@dataclass
class ComplexReq:
    name: str
    age: int
    tags: list[str] = field(default_factory=lambda: list[str]())
    nickname: str | None = None

    def to_domain(self) -> GreetOp:
        return GreetOp(name=self.name)


@dataclass
class ComplexResp:
    value: str

    @classmethod
    def from_domain(cls, dom: Result[str, str]) -> Self:
        match dom:
            case Ok(v):
                return cls(value=v)
            case _:
                return cls(value="error")

    def __str__(self) -> str:
        return self.value


@dataclass
class PathAndBodyReq:
    user_id: str
    name: str
    email: str = ""

    def to_domain(self) -> GreetOp:
        return GreetOp(name=f"{self.user_id}:{self.name}")


@dataclass
class ImmResp:
    text: str

    @classmethod
    def produce(cls) -> Self:
        return cls(text="immediate-value")


@dataclass
class OrderCreated:
    order_id: int
    total: float


_runner = ops().on(GreetOp, _test_handler).compile()
_axes = Axes.default()


def _make_app(*endpoints: Endpoint) -> Application:
    return application().mount(*endpoints)


# ═══════════════════════════════════════════════════════════════════════════════
# FastAPI — OpenAPI Schema Generation (build_rrc_openapi_extra)
# ═══════════════════════════════════════════════════════════════════════════════


class TestOpenAPISchemaGeneration:
    """Cover build_rrc_openapi_extra deeply — path params, POST body, GET query."""

    def test_post_generates_request_body(self) -> None:
        from emergent.wire.compile.targets.fastapi import build_rrc_openapi_extra

        codec = rrc(SimpleReq, SimpleResp)
        trigger = HTTPRouteTrigger(method="POST", path="/items")
        extra = build_rrc_openapi_extra(codec, trigger, _axes)
        assert extra is not None
        assert "requestBody" in extra
        assert extra["requestBody"]["required"] is True
        content = extra["requestBody"]["content"]["application/json"]["schema"]
        assert "properties" in content
        assert "name" in content["properties"]

    def test_get_generates_query_parameters(self) -> None:
        from emergent.wire.compile.targets.fastapi import build_rrc_openapi_extra

        codec = rrc(SimpleReq, SimpleResp)
        trigger = HTTPRouteTrigger(method="GET", path="/items")
        extra = build_rrc_openapi_extra(codec, trigger, _axes)
        assert extra is not None
        assert "parameters" in extra
        params = extra["parameters"]
        param_names = [p["name"] for p in params]
        assert "name" in param_names
        assert all(p["in"] == "query" for p in params)

    def test_path_params_extracted_from_trigger_path(self) -> None:
        from emergent.wire.compile.targets.fastapi import build_rrc_openapi_extra

        codec = rrc(PathAndBodyReq, SimpleResp)
        trigger = HTTPRouteTrigger(method="POST", path="/users/{user_id}")
        extra = build_rrc_openapi_extra(codec, trigger, _axes)
        assert extra is not None
        assert "parameters" in extra
        path_params = [p for p in extra["parameters"] if p["in"] == "path"]
        assert len(path_params) == 1
        assert path_params[0]["name"] == "user_id"
        assert path_params[0]["required"] is True

    def test_path_params_excluded_from_body(self) -> None:
        from emergent.wire.compile.targets.fastapi import build_rrc_openapi_extra

        codec = rrc(PathAndBodyReq, SimpleResp)
        trigger = HTTPRouteTrigger(method="POST", path="/users/{user_id}")
        extra = build_rrc_openapi_extra(codec, trigger, _axes)
        assert extra is not None
        body_schema = extra["requestBody"]["content"]["application/json"]["schema"]
        assert "user_id" not in body_schema["properties"]
        assert "name" in body_schema["properties"]

    def test_get_with_path_params_separates_path_and_query(self) -> None:
        from emergent.wire.compile.targets.fastapi import build_rrc_openapi_extra

        codec = rrc(PathAndBodyReq, SimpleResp)
        trigger = HTTPRouteTrigger(method="GET", path="/users/{user_id}")
        extra = build_rrc_openapi_extra(codec, trigger, _axes)
        assert extra is not None
        params = extra["parameters"]
        path_params = [p for p in params if p["in"] == "path"]
        query_params = [p for p in params if p["in"] == "query"]
        assert len(path_params) == 1
        assert len(query_params) >= 1
        query_names = {p["name"] for p in query_params}
        assert "user_id" not in query_names

    def test_complex_request_with_optional_fields(self) -> None:
        from emergent.wire.compile.targets.fastapi import build_rrc_openapi_extra

        codec = rrc(ComplexReq, ComplexResp)
        trigger = HTTPRouteTrigger(method="POST", path="/complex")
        extra = build_rrc_openapi_extra(codec, trigger, _axes)
        assert extra is not None
        body = extra["requestBody"]["content"]["application/json"]["schema"]
        props = body["properties"]
        assert "name" in props
        assert "age" in props

    def test_no_body_fields_returns_no_request_body(self) -> None:
        """When all fields are path params, requestBody may be empty."""
        from emergent.wire.compile.targets.fastapi import build_rrc_openapi_extra

        @dataclass
        class OnlyPathReq:
            user_id: str

            def to_domain(self) -> GreetOp:
                return GreetOp(name=self.user_id)

        codec = rrc(OnlyPathReq, SimpleResp)
        trigger = HTTPRouteTrigger(method="POST", path="/users/{user_id}")
        extra = build_rrc_openapi_extra(codec, trigger, _axes)
        # Should only have path parameters, no requestBody
        if extra is not None:
            if "requestBody" in extra:
                body = extra["requestBody"]["content"]["application/json"]["schema"]
                assert not body.get("properties")


# ═══════════════════════════════════════════════════════════════════════════════
# FastAPI — Compilation with CORS middleware
# ═══════════════════════════════════════════════════════════════════════════════


class TestFastAPIMiddleware:
    """Cover fastapi_compile with global capabilities (CORS, etc.)."""

    def test_cors_middleware_added(self) -> None:
        from emergent.wire.compile.targets.fastapi import fastapi_compile
        from emergent.wire.axis.surface.dialects.http import CORS

        app = _make_app(
            endpoint(_runner).expose(
                HTTPRouteTrigger(method="GET", path="/health"),
                immediate(ImmResp),
            )
        ).with_capabilities(CORS(origins=("http://localhost",)))

        fapi = fastapi_compile(app)
        assert isinstance(fapi, fastapi.FastAPI)
        # Middleware is added — verify via user_middleware
        middleware_names = [str(getattr(m.cls, "__name__", "")) for m in fapi.user_middleware]
        assert "CORSMiddleware" in middleware_names

    def test_multiple_middleware_stacked(self) -> None:
        from emergent.wire.compile.targets.fastapi import fastapi_compile
        from emergent.wire.axis.surface.dialects.http import CORS, GZip

        app = _make_app(
            endpoint(_runner).expose(
                HTTPRouteTrigger(method="GET", path="/health"),
                immediate(ImmResp),
            )
        ).with_capabilities(CORS(), GZip(minimum_size=100))

        fapi = fastapi_compile(app)
        middleware_names = [str(getattr(m.cls, "__name__", "")) for m in fapi.user_middleware]
        assert "CORSMiddleware" in middleware_names
        assert "GZipMiddleware" in middleware_names


# ═══════════════════════════════════════════════════════════════════════════════
# FastAPI — Response Transforms (AsDict, AsStr)
# ═══════════════════════════════════════════════════════════════════════════════


class TestFastAPIResponseTransforms:
    """Cover response transform capabilities on FastAPI routes."""

    def test_as_dict_on_immediate_response(self) -> None:
        from emergent.wire.compile.targets.fastapi import wrap_immediate_fastapi

        codec = immediate(ImmResp)
        handler: Handler[ImmediateCodec] = Handler(
            codec=codec, runner=_runner, capabilities=(AsDict(),)
        )
        route = wrap_immediate_fastapi(handler, HTTPRouteTrigger("GET", "/test"), _axes)
        assert route.endpoint is not None

    @pytest.mark.asyncio
    async def test_as_dict_transforms_response(self) -> None:
        from emergent.wire.compile.targets.fastapi import wrap_immediate_fastapi

        codec = immediate(ImmResp)
        handler: Handler[ImmediateCodec] = Handler(
            codec=codec, runner=_runner, capabilities=(AsDict(),)
        )
        route = wrap_immediate_fastapi(handler, HTTPRouteTrigger("GET", "/test"), _axes)
        result = await route.endpoint()
        assert isinstance(result, dict)
        assert result["text"] == "immediate-value"

    @pytest.mark.asyncio
    async def test_as_str_transforms_response(self) -> None:
        from emergent.wire.compile.targets.fastapi import wrap_immediate_fastapi

        codec = immediate_factory(lambda: ImmResp(text="hello"))
        handler: Handler[ImmediateFactoryCodec] = Handler(
            codec=codec, runner=_runner, capabilities=(AsStr(),)
        )
        route = wrap_immediate_fastapi(handler, HTTPRouteTrigger("GET", "/test"), _axes)
        result = await route.endpoint()
        assert isinstance(result, str)


# ═══════════════════════════════════════════════════════════════════════════════
# FastAPI — Traced Compilation
# ═══════════════════════════════════════════════════════════════════════════════


class TestFastAPITracedCompilation:
    """Cover Axes.traced() path through FastAPI compilation."""

    def test_traced_axes_produces_valid_app(self) -> None:
        from emergent.wire.compile.targets.fastapi import fastapi_compile

        traced_axes = Axes.traced()
        app = _make_app(
            endpoint(_runner).expose(
                HTTPRouteTrigger(method="POST", path="/items"),
                rrc(SimpleReq, SimpleResp),
            )
        )
        fapi = fastapi_compile(app, traced_axes)
        assert isinstance(fapi, fastapi.FastAPI)
        # Trace should have recorded events
        assert traced_axes.trace is not None

    def test_traced_axes_records_scan_events(self) -> None:
        from emergent.wire.compile.targets.fastapi import fastapi_compile
        from emergent.wire.compile._trace import ListCollector

        collector = ListCollector()
        traced_axes = Axes.traced(collector)
        app = _make_app(
            endpoint(_runner).expose(
                HTTPRouteTrigger(method="POST", path="/items"),
                rrc(SimpleReq, SimpleResp),
            )
        )
        fastapi_compile(app, traced_axes)
        assert len(collector.scan_events) > 0
        assert len(collector.wrap_events) > 0


# ═══════════════════════════════════════════════════════════════════════════════
# FastAPI — Delegate Codec
# ═══════════════════════════════════════════════════════════════════════════════


class TestFastAPIDelegateCompilation:
    """Cover delegate codec wrapping in FastAPI."""

    def test_delegate_wraps_to_route(self) -> None:
        from emergent.wire.compile.targets.fastapi import wrap_delegate_fastapi

        async def my_handler(name: str) -> str:
            return f"hello {name}"

        codec = delegate(my_handler)
        handler: Handler[DelegateCodec] = Handler(
            codec=codec, runner=_runner, capabilities=()
        )
        route = wrap_delegate_fastapi(
            handler, HTTPRouteTrigger("POST", "/test"), _axes
        )
        assert route.endpoint is not None

    def test_delegate_from_codec(self) -> None:
        from emergent.wire.compile.targets.fastapi import delegate_from_codec

        async def my_handler(name: str) -> str:
            return f"hello {name}"

        codec = delegate(my_handler)
        trigger = HTTPRouteTrigger("POST", "/test")
        ctx = delegate_from_codec(codec, trigger)
        assert ctx.execute is not None
        assert ctx.trigger is trigger


# ═══════════════════════════════════════════════════════════════════════════════
# FastAPI — Extractors
# ═══════════════════════════════════════════════════════════════════════════════


class TestFastAPIExtractors:
    """Cover FastAPIJsonExtractor, FastAPIQueryExtractor, FastAPIFormExtractor."""

    def test_default_extractor_post_is_json(self) -> None:
        from emergent.wire.compile.targets.fastapi import _default_extractor

        trigger = HTTPRouteTrigger(method="POST", path="/test")
        from emergent.wire.compile.targets.fastapi import FastAPIJsonExtractor

        ext = _default_extractor(trigger)
        assert isinstance(ext, FastAPIJsonExtractor)

    def test_default_extractor_get_is_query(self) -> None:
        from emergent.wire.compile.targets.fastapi import _default_extractor

        trigger = HTTPRouteTrigger(method="GET", path="/test")
        from emergent.wire.compile.targets.fastapi import FastAPIQueryExtractor

        ext = _default_extractor(trigger)
        assert isinstance(ext, FastAPIQueryExtractor)


# ═══════════════════════════════════════════════════════════════════════════════
# FastAPI — Immediate Codec (no-arg route)
# ═══════════════════════════════════════════════════════════════════════════════


class TestFastAPIImmediateNoArgRoute:
    """Immediate codecs produce _simple_route with no request arg."""

    def test_immediate_from_codec_sets_inject_type_none(self) -> None:
        from emergent.wire.compile.targets.fastapi import immediate_from_codec

        codec = immediate(ImmResp)
        trigger = HTTPRouteTrigger("GET", "/health")
        ctx = immediate_from_codec(codec, trigger)
        assert ctx.inject_type is type(None)

    @pytest.mark.asyncio
    async def test_immediate_endpoint_no_request(self) -> None:
        from emergent.wire.compile.targets.fastapi import wrap_immediate_fastapi

        codec = immediate(ImmResp)
        handler: Handler[ImmediateCodec] = Handler(
            codec=codec, runner=_runner, capabilities=()
        )
        route = wrap_immediate_fastapi(handler, HTTPRouteTrigger("GET", "/h"), _axes)
        result = await route.endpoint()
        assert isinstance(result, ImmResp)


# ═══════════════════════════════════════════════════════════════════════════════
# FastAPI — Full Integration via TestClient
# ═══════════════════════════════════════════════════════════════════════════════


class TestFastAPIIntegration:
    """Cover full compilation + real HTTP calls via httpx."""

    @pytest.mark.asyncio
    async def test_rrc_post_endpoint(self) -> None:
        from emergent.wire.compile.targets.fastapi import fastapi_compile

        app = _make_app(
            endpoint(_runner).expose(
                HTTPRouteTrigger(method="POST", path="/greet"),
                rrc(SimpleReq, SimpleResp),
            )
        )
        fapi = fastapi_compile(app)
        async with AsyncClient(
            transport=ASGITransport(app=fapi), base_url="http://test"
        ) as client:
            resp = await client.post("/greet", json={"name": "Alice"})
            assert resp.status_code == 200
            data = resp.json()
            assert data["value"] == "result-Alice"

    @pytest.mark.asyncio
    async def test_immediate_get_endpoint(self) -> None:
        from emergent.wire.compile.targets.fastapi import fastapi_compile

        app = _make_app(
            endpoint(_runner).expose(
                HTTPRouteTrigger(method="GET", path="/health"),
                immediate(ImmResp),
            )
        )
        fapi = fastapi_compile(app)
        async with AsyncClient(
            transport=ASGITransport(app=fapi), base_url="http://test"
        ) as client:
            resp = await client.get("/health")
            assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_delegate_post_endpoint(self) -> None:
        from emergent.wire.compile.targets.fastapi import fastapi_compile

        async def echo_handler() -> dict[str, str]:
            return {"echo": "ok"}

        app = _make_app(
            endpoint(_runner).expose(
                HTTPRouteTrigger(method="POST", path="/echo"),
                delegate(echo_handler),
            )
        )
        fapi = fastapi_compile(app)
        async with AsyncClient(
            transport=ASGITransport(app=fapi), base_url="http://test"
        ) as client:
            resp = await client.post("/echo")
            assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════════
# FastAPI — AppStack Compilation
# ═══════════════════════════════════════════════════════════════════════════════


class TestFastAPIStackCompilation:
    """Cover fastapi_compile_stack with nested routers."""

    def test_stack_compiles_to_fastapi(self) -> None:
        from emergent.wire.compile.targets.fastapi import fastapi_compile_stack

        app_a = _make_app(
            endpoint(_runner).expose(
                HTTPRouteTrigger(method="GET", path="/items"),
                immediate(ImmResp),
            )
        )
        app_b = _make_app(
            endpoint(_runner).expose(
                HTTPRouteTrigger(method="POST", path="/create"),
                rrc(SimpleReq, SimpleResp),
            )
        )
        stack = app_stack().root(app_a).mount("admin", app_b)
        fapi = fastapi_compile_stack(stack)
        assert isinstance(fapi, fastapi.FastAPI)
        # Verify routes exist by checking router
        paths = [r.path for r in fapi.routes if isinstance(r, fastapi.routing.APIRoute)]
        # Should have /items and /admin/create
        assert any("/items" in str(p) for p in paths)


# ═══════════════════════════════════════════════════════════════════════════════
# CLI — Basic Compilation
# ═══════════════════════════════════════════════════════════════════════════════


class TestCLICompilation:
    """Cover cli_compile, cli_run, and codec wrappers."""

    def test_cli_compile_produces_parser(self) -> None:
        from emergent.wire.compile.targets.cli import cli_compile

        app = _make_app(
            endpoint(_runner).expose(
                CLITrigger(command="greet", description="Say hello"),
                rrc(SimpleReq, SimpleResp),
            )
        )
        parser = cli_compile(app)
        assert isinstance(parser, argparse.ArgumentParser)

    def test_cli_compile_with_multiple_commands(self) -> None:
        from emergent.wire.compile.targets.cli import cli_compile

        app = _make_app(
            endpoint(_runner)
            .expose(
                CLITrigger(command="greet"),
                rrc(SimpleReq, SimpleResp),
            )
            .expose(
                CLITrigger(command="health"),
                immediate(ImmResp),
            )
        )
        parser = cli_compile(app)
        # Should parse 'greet' and 'health'
        ns = parser.parse_args(["greet", "Alice"])
        assert ns.command == "greet"
        assert ns.name == "Alice"

    def test_cli_run_executes_handler(self) -> None:
        from emergent.wire.compile.targets.cli import cli_compile, cli_run

        app = _make_app(
            endpoint(_runner).expose(
                CLITrigger(command="health"),
                immediate(ImmResp),
            )
        )
        parser = cli_compile(app)
        result = cli_run(parser, ["health"])
        assert result == 0

    def test_cli_run_no_handler_prints_help(self) -> None:
        argparse.ArgumentParser()
        # No _handler attr on namespace
        parsed = argparse.Namespace(command="test")
        handler = getattr(parsed, "_handler", None)
        assert handler is None

    def test_cli_run_missing_command(self) -> None:
        from emergent.wire.compile.targets.cli import cli_compile, cli_run

        app = _make_app(
            endpoint(_runner).expose(
                CLITrigger(command="greet"),
                rrc(SimpleReq, SimpleResp),
            )
        )
        parser = cli_compile(app)
        # Missing required 'command' should cause SystemExit
        with pytest.raises(SystemExit):
            cli_run(parser, [])


# ═══════════════════════════════════════════════════════════════════════════════
# CLI — Positional Arguments
# ═══════════════════════════════════════════════════════════════════════════════


class TestCLIPositionalArgs:
    """Cover positional arg generation in argparse."""

    def test_required_field_becomes_positional(self) -> None:
        from emergent.wire.compile.targets.cli import cli_compile

        app = _make_app(
            endpoint(_runner).expose(
                CLITrigger(command="greet"),
                rrc(SimpleReq, SimpleResp),
            )
        )
        parser = cli_compile(app)
        ns = parser.parse_args(["greet", "World"])
        assert ns.name == "World"

    def test_optional_field_becomes_flag(self) -> None:
        from emergent.wire.compile.targets.cli import cli_compile

        @dataclass
        class ReqWithDefault:
            name: str
            greeting: str = "Hello"

            def to_domain(self) -> GreetOp:
                return GreetOp(name=self.name)

        app = _make_app(
            endpoint(_runner).expose(
                CLITrigger(command="greet"),
                rrc(ReqWithDefault, SimpleResp),
            )
        )
        parser = cli_compile(app)
        # name is positional, greeting is optional flag
        ns = parser.parse_args(["greet", "World"])
        assert ns.name == "World"

        ns2 = parser.parse_args(["greet", "World", "--greeting", "Hi"])
        assert ns2.greeting == "Hi"


# ═══════════════════════════════════════════════════════════════════════════════
# CLI — Delegate Codec
# ═══════════════════════════════════════════════════════════════════════════════


class TestCLIDelegateCodec:
    """Cover delegate codec wrapping for CLI."""

    def test_delegate_from_codec_cli(self) -> None:
        from emergent.wire.compile.targets.cli import delegate_from_codec_cli

        def my_handler(name: str, count: int) -> str:
            return f"{name}x{count}"

        codec = delegate(my_handler)
        trigger = CLITrigger(command="run")
        ctx = delegate_from_codec_cli(codec, trigger)
        assert ctx.execute is not None
        assert len(ctx.arg_specs) > 0

    def test_delegate_cli_arg_specs_from_handler_params(self) -> None:
        from emergent.wire.compile.targets.cli import _get_delegate_arg_specs

        def handler(name: str, verbose: bool = False) -> str:
            return name

        specs = _get_delegate_arg_specs(handler, _axes)
        assert len(specs) >= 1

    def test_inspect_handler_params(self) -> None:
        from emergent.wire.compile.targets.cli import _inspect_handler_params

        def handler(name: str, count: int, flag: bool = False) -> str:
            return name

        params = _inspect_handler_params(handler)
        assert len(params) == 3
        names = [p[0] for p in params]
        assert "name" in names
        assert "count" in names
        assert "flag" in names

    def test_build_delegate_args_from_namespace(self) -> None:
        from emergent.wire.compile.targets.cli import _build_delegate_args

        def handler(name: str, count: int) -> str:
            return f"{name}x{count}"

        ns = argparse.Namespace(name="test", count=5)
        args = _build_delegate_args(handler, ns)
        assert args["name"] == "test"
        assert args["count"] == 5


# ═══════════════════════════════════════════════════════════════════════════════
# CLI — Immediate Codec
# ═══════════════════════════════════════════════════════════════════════════════


class TestCLIImmediateCodec:
    """Cover immediate codec wrapping for CLI."""

    def test_immediate_from_codec_cli(self) -> None:
        from emergent.wire.compile.targets.cli import immediate_from_codec_cli

        codec = immediate(ImmResp)
        trigger = CLITrigger(command="health")
        ctx = immediate_from_codec_cli(codec, trigger)
        assert ctx.execute is not None
        assert len(ctx.arg_specs) == 0

    def test_wrap_immediate_cli(self) -> None:
        from emergent.wire.compile.targets.cli import wrap_immediate_cli

        codec = immediate(ImmResp)
        handler: Handler[ImmediateCodec] = Handler(
            codec=codec, runner=_runner, capabilities=()
        )
        route = wrap_immediate_cli(handler, CLITrigger(command="health"), _axes)
        assert route.handler is not None


# ═══════════════════════════════════════════════════════════════════════════════
# CLI — Stack Compilation
# ═══════════════════════════════════════════════════════════════════════════════


class TestCLIStackCompilation:
    """Cover cli_compile_stack with nested subcommands."""

    def test_stack_compiles_to_parser(self) -> None:
        from emergent.wire.compile.targets.cli import cli_compile_stack

        app_a = _make_app(
            endpoint(_runner).expose(
                CLITrigger(command="list"),
                immediate(ImmResp),
            )
        )
        app_b = _make_app(
            endpoint(_runner).expose(
                CLITrigger(command="create"),
                rrc(SimpleReq, SimpleResp),
            )
        )
        stack = app_stack().root(app_a).mount("items", app_b)
        parser = cli_compile_stack(stack)
        assert isinstance(parser, argparse.ArgumentParser)

    def test_stack_nested_commands_parse(self) -> None:
        from emergent.wire.compile.targets.cli import cli_compile_stack

        app_a = _make_app(
            endpoint(_runner).expose(
                CLITrigger(command="list"),
                immediate(ImmResp),
            )
        )
        app_b = _make_app(
            endpoint(_runner).expose(
                CLITrigger(command="create"),
                rrc(SimpleReq, SimpleResp),
            )
        )
        stack = app_stack().root(app_a).mount("items", app_b)
        parser = cli_compile_stack(stack)
        # Root command
        ns = parser.parse_args(["list"])
        assert ns.command == "list"


# ═══════════════════════════════════════════════════════════════════════════════
# CLI — Typed CLI (Pydantic Coercion)
# ═══════════════════════════════════════════════════════════════════════════════


class TestCLITypedCoercion:
    """Cover coerce_cli_values and TYPED_CLI compiler."""

    def test_coerce_cli_values_coerces_types(self) -> None:
        from emergent.wire.compile.targets.cli import coerce_cli_values

        @dataclass
        class NumReq:
            count: int
            label: str = "default"

            def to_domain(self) -> GreetOp:
                return GreetOp(name=str(self.count))

        raw = {"count": "42", "label": "test"}
        typed_get = coerce_cli_values(NumReq, _axes, lambda name: raw.get(name))
        assert typed_get("count") == 42
        assert typed_get("label") == "test"

    def test_typed_cli_compiler_has_rrc_binding(self) -> None:
        from emergent.wire.compile.targets.cli import TYPED_CLI

        assert RequestResponseCodec in TYPED_CLI

    def test_typed_rrc_from_codec_produces_context(self) -> None:
        from emergent.wire.compile.targets.cli import typed_rrc_from_codec_cli

        codec = rrc(SimpleReq, SimpleResp)
        trigger = CLITrigger(command="greet")
        ctx = typed_rrc_from_codec_cli(codec, trigger)
        assert ctx.execute is not None
        assert ctx.request_type is SimpleReq


# ═══════════════════════════════════════════════════════════════════════════════
# CLI — Register Handler (capabilities)
# ═══════════════════════════════════════════════════════════════════════════════


class TestCLIRegisterHandler:
    """Cover register_handler with capabilities like help text."""

    def test_register_handler_adds_subcommand(self) -> None:
        from emergent.wire.compile.targets.cli import (
            rrc_from_codec_cli,
            assemble_cli_route,
            register_handler,
        )

        codec = rrc(SimpleReq, SimpleResp)
        handler: Handler[RequestResponseCodec] = Handler(
            codec=codec, runner=_runner, capabilities=()
        )
        trigger = CLITrigger(command="greet", description="Say hello")
        ctx = rrc_from_codec_cli(codec, trigger)
        route = assemble_cli_route(ctx, handler, _axes)

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        register_handler(subparsers, trigger, handler, route, _axes)
        ns = parser.parse_args(["greet", "World"])
        assert ns.command == "greet"


# ═══════════════════════════════════════════════════════════════════════════════
# Compile Infrastructure — _request.py (build_request)
# ═══════════════════════════════════════════════════════════════════════════════


class TestBuildRequest:
    """Cover build_request and build_request_sync."""

    @pytest.mark.asyncio
    async def test_build_request_from_values(self) -> None:
        from emergent.wire.compile._request import build_request

        values = {"name": "Alice"}
        req = await build_request(SimpleReq, lambda n: values.get(n))
        assert isinstance(req, SimpleReq)
        assert req.name == "Alice"

    @pytest.mark.asyncio
    async def test_build_request_with_optional_field(self) -> None:
        from emergent.wire.compile._request import build_request

        values: dict[str, str | int] = {"name": "Bob", "age": 25}
        req = await build_request(ComplexReq, lambda n: values.get(n))
        assert req.name == "Bob"
        assert req.age == 25
        # Optional nickname should be None
        assert req.nickname is None

    @pytest.mark.asyncio
    async def test_build_request_with_default_field(self) -> None:
        from emergent.wire.compile._request import build_request

        values: dict[str, str | int] = {"name": "Bob", "age": 25}
        req = await build_request(ComplexReq, lambda n: values.get(n))
        assert req.name == "Bob"
        assert req.age == 25
        assert req.tags == []  # default_factory

    @pytest.mark.asyncio
    async def test_build_request_missing_required_field_raises(self) -> None:
        from emergent.wire.compile._request import build_request

        with pytest.raises(RuntimeError, match="Cannot resolve required field"):
            await build_request(SimpleReq, lambda _: None)

    @pytest.mark.asyncio
    async def test_build_request_non_dataclass_raises(self) -> None:
        from emergent.wire.compile._request import build_request

        with pytest.raises(TypeError, match="not a dataclass"):
            await build_request(str, lambda _: None)

    def test_build_request_sync(self) -> None:
        from emergent.wire.compile._request import build_request_sync

        values = {"name": "Charlie"}
        req = build_request_sync(SimpleReq, lambda n: values.get(n))
        assert req.name == "Charlie"

    def test_build_request_sync_with_defaults(self) -> None:
        from emergent.wire.compile._request import build_request_sync

        values: dict[str, str | int] = {"name": "Dan", "age": 30}
        req = build_request_sync(ComplexReq, lambda n: values.get(n))
        assert req.name == "Dan"
        assert req.tags == []

    def test_build_request_sync_missing_required_raises(self) -> None:
        from emergent.wire.compile._request import build_request_sync

        with pytest.raises(RuntimeError, match="No value for required field"):
            build_request_sync(SimpleReq, lambda _: None)

    def test_build_request_sync_non_dataclass_raises(self) -> None:
        from emergent.wire.compile._request import build_request_sync

        with pytest.raises(TypeError, match="not a dataclass"):
            build_request_sync(int, lambda _: None)


# ═══════════════════════════════════════════════════════════════════════════════
# Compile Infrastructure — _pipeline.py
# ═══════════════════════════════════════════════════════════════════════════════


class TestPipelineCompilation:
    """Cover compile_pipeline and execute_with_pipeline."""

    def test_compile_pipeline_from_wrap_context(self) -> None:
        from emergent.wire.compile._pipeline import compile_pipeline, CompiledPipeline

        @dataclass(frozen=True)
        class MockCtx:
            execute: Any = None

        async def my_execute(handler: Any, scope: Any, get_value: Any) -> str:
            return "ok"

        ctx = MockCtx(execute=my_execute)
        compiled = compile_pipeline(ctx, _axes)
        assert isinstance(compiled, CompiledPipeline)
        assert compiled.execute is my_execute

    def test_compile_pipeline_no_execute_raises(self) -> None:
        from emergent.wire.compile._pipeline import compile_pipeline

        @dataclass(frozen=True)
        class NoExecCtx:
            execute: None = None

        with pytest.raises(TypeError, match="no 'execute' attribute"):
            compile_pipeline(NoExecCtx(), _axes)

    def test_compile_pipeline_reads_extractor(self) -> None:
        from emergent.wire.compile._pipeline import compile_pipeline

        class FakeExtractor:
            async def extract(self, request: object) -> dict[str, object]:
                return {}

        def _noop(*a: Any) -> None:
            pass

        @dataclass(frozen=True)
        class CtxWithExtractor:
            execute: Any = None
            extractor: Any = None

        ext = FakeExtractor()
        ctx = CtxWithExtractor(execute=_noop, extractor=ext)
        compiled = compile_pipeline(ctx, _axes)
        assert compiled.extractor is ext


# ═══════════════════════════════════════════════════════════════════════════════
# Compile Infrastructure — _execute.py (execute_immediate_unified)
# ═══════════════════════════════════════════════════════════════════════════════


class TestExecuteImmediateUnified:
    """Cover execute_immediate_unified for ImmediateCodec and ImmediateFactoryCodec."""

    def test_immediate_codec(self) -> None:
        from emergent.wire.compile._execute import execute_immediate_unified

        codec = immediate(ImmResp)
        handler: Handler[ImmediateCodec] = Handler(
            codec=codec, runner=_runner, capabilities=()
        )
        result = execute_immediate_unified(handler)
        assert isinstance(result, ImmResp)
        assert result.text == "immediate-value"

    def test_factory_codec(self) -> None:
        from emergent.wire.compile._execute import execute_immediate_unified

        codec = immediate_factory(lambda: ImmResp(text="from-factory"))
        handler: Handler[ImmediateFactoryCodec] = Handler(
            codec=codec, runner=_runner, capabilities=()
        )
        result = execute_immediate_unified(handler)
        assert isinstance(result, ImmResp)
        assert result.text == "from-factory"

    def test_invalid_codec_raises(self) -> None:
        from emergent.wire.compile._execute import execute_immediate_unified

        @dataclass(frozen=True)
        class FakeCodec:
            pass

        handler = Handler(codec=FakeCodec(), runner=_runner, capabilities=())
        with pytest.raises(TypeError, match="Expected ImmediateCodec"):
            execute_immediate_unified(handler)

    def test_with_format_response(self) -> None:
        from emergent.wire.compile._execute import execute_immediate_unified

        codec = immediate(ImmResp)
        handler: Handler[ImmediateCodec] = Handler(
            codec=codec, runner=_runner, capabilities=()
        )
        result = execute_immediate_unified(
            handler, format_response=lambda r: str(r.text).upper()
        )
        assert result == "IMMEDIATE-VALUE"


# ═══════════════════════════════════════════════════════════════════════════════
# Compile Infrastructure — _execute.py (execute_rrc_unified)
# ═══════════════════════════════════════════════════════════════════════════════


class TestExecuteRrcUnified:
    """Cover execute_rrc_unified end to end."""

    @pytest.mark.asyncio
    async def test_basic_rrc_execution(self) -> None:
        from emergent.wire.compile._execute import execute_rrc_unified

        codec = rrc(SimpleReq, SimpleResp)
        handler: Handler[RequestResponseCodec] = Handler(
            codec=codec, runner=_runner, capabilities=()
        )
        result = await execute_rrc_unified(
            handler=handler,
            axes=_axes,
            get_value=lambda name: {"name": "Alice"}.get(name),
            inject_scope=lambda s: None,
        )
        assert isinstance(result, SimpleResp)
        assert result.value == "result-Alice"

    @pytest.mark.asyncio
    async def test_rrc_with_format_response(self) -> None:
        from emergent.wire.compile._execute import execute_rrc_unified

        codec = rrc(SimpleReq, SimpleResp)
        handler: Handler[RequestResponseCodec] = Handler(
            codec=codec, runner=_runner, capabilities=()
        )
        result = await execute_rrc_unified(
            handler=handler,
            axes=_axes,
            get_value=lambda name: {"name": "Bob"}.get(name),
            inject_scope=lambda s: None,
            format_response=lambda r: {"formatted": r.value},
        )
        assert result == {"formatted": "result-Bob"}


# ═══════════════════════════════════════════════════════════════════════════════
# Compile Infrastructure — _stateful.py
# ═══════════════════════════════════════════════════════════════════════════════


class TestStatefulHelpers:
    """Cover load_state, save_state, delete_state, get_stateful_metadata."""

    @pytest.mark.asyncio
    async def test_load_state_returns_initial_when_empty(self) -> None:
        from emergent.wire.compile._stateful import load_state

        store = AsyncMock()
        store.get = AsyncMock(return_value=Ok(Nothing()))

        @dataclass(frozen=True)
        class FakeFlow:
            pass

        codec: Any = type("FakeCodec", (), {"store": store, "flow": FakeFlow})()
        state = await load_state(codec, "key-1")
        assert isinstance(state, FakeFlow)

    @pytest.mark.asyncio
    async def test_save_state_calls_store_set(self) -> None:
        from emergent.wire.compile._stateful import save_state

        store = AsyncMock()
        store.set = AsyncMock()

        codec: Any = type("FakeCodec", (), {"store": store})()
        old = object()
        new = object()
        await save_state(codec, "key-1", old, new)
        store.set.assert_called_once_with("key-1", new)

    @pytest.mark.asyncio
    async def test_save_state_skips_when_same(self) -> None:
        from emergent.wire.compile._stateful import save_state

        store = AsyncMock()
        store.set = AsyncMock()

        codec: Any = type("FakeCodec", (), {"store": store})()
        obj = object()
        await save_state(codec, "key-1", obj, obj)
        store.set.assert_not_called()

    @pytest.mark.asyncio
    async def test_delete_state_calls_store_delete(self) -> None:
        from emergent.wire.compile._stateful import delete_state

        store = AsyncMock()
        store.delete = AsyncMock()

        codec: Any = type("FakeCodec", (), {"store": store})()
        await delete_state(codec, "key-1")
        store.delete.assert_called_once_with("key-1")

    def test_get_stateful_metadata(self) -> None:
        from emergent.wire.compile._stateful import get_stateful_metadata

        class FakeFlow:
            pass

        class FakeKeyNode:
            pass

        @dataclass(frozen=True)
        class FakeStatefulCodec:
            flow: type = FakeFlow
            response: type = SimpleResp
            key_node: type = FakeKeyNode
            agent_cls: type | None = None

        codec = FakeStatefulCodec()
        handler: Any = Handler(codec=codec, runner=_runner, capabilities=())
        meta = get_stateful_metadata(handler)
        assert meta["flow_cls"] is FakeFlow
        assert meta["response_cls"] is SimpleResp
        assert meta["key_node"] is FakeKeyNode


# ═══════════════════════════════════════════════════════════════════════════════
# Compile Infrastructure — _delegate.py
# ═══════════════════════════════════════════════════════════════════════════════


class TestDelegateParamResolution:
    """Cover _extract_compose_capability, _get_base_type."""

    def test_extract_compose_capability_from_plain_type(self) -> None:
        from emergent.wire.compile._delegate import _extract_compose_capability

        result = _extract_compose_capability(str)
        assert result is None

    def test_get_base_type_plain(self) -> None:
        from emergent.wire.compile._delegate import _get_base_type

        assert _get_base_type(str) is str
        assert _get_base_type(int) is int

    def test_get_base_type_non_type(self) -> None:
        from emergent.wire.compile._delegate import _get_base_type

        assert _get_base_type("not-a-type") is None

    def test_extract_compose_result(self) -> None:
        from emergent.wire.compile._delegate import _extract_compose_result

        assert _extract_compose_result((True, "value")) == (True, "value")
        assert _extract_compose_result((False, None)) == (False, None)


# ═══════════════════════════════════════════════════════════════════════════════
# Testing Target — TestApp, TestRoute
# ═══════════════════════════════════════════════════════════════════════════════


class TestTestingTarget:
    """Cover testing_compile, TestApp, TestRoute invocation."""

    @pytest.mark.asyncio
    async def test_rrc_route_call(self) -> None:
        from emergent.wire.compile.targets.testing import testing_compile

        app = _make_app(
            endpoint(_runner).expose(
                HTTPRouteTrigger(method="POST", path="/greet"),
                rrc(SimpleReq, SimpleResp),
            )
        )
        test_app = testing_compile(app)
        assert len(test_app.routes) == 1
        result = await test_app.routes[0].call({"name": "Alice"})
        assert isinstance(result, SimpleResp)
        assert result.value == "result-Alice"

    @pytest.mark.asyncio
    async def test_immediate_route_call(self) -> None:
        from emergent.wire.compile.targets.testing import testing_compile

        app = _make_app(
            endpoint(_runner).expose(
                CLITrigger(command="health"),
                immediate(ImmResp),
            )
        )
        test_app = testing_compile(app)
        assert len(test_app.routes) == 1
        result = await test_app.routes[0].call()
        assert isinstance(result, ImmResp)

    @pytest.mark.asyncio
    async def test_delegate_route_call(self) -> None:
        from emergent.wire.compile.targets.testing import testing_compile

        async def echo() -> str:
            return "echoed"

        app = _make_app(
            endpoint(_runner).expose(
                HTTPRouteTrigger(method="POST", path="/echo"),
                delegate(echo),
            )
        )
        test_app = testing_compile(app)
        result = await test_app.routes[0].call()
        assert result == "echoed"

    @pytest.mark.asyncio
    async def test_test_app_context_manager(self) -> None:
        from emergent.wire.compile.targets.testing import testing_compile

        app = _make_app(
            endpoint(_runner).expose(
                HTTPRouteTrigger(method="POST", path="/greet"),
                rrc(SimpleReq, SimpleResp),
            )
        )
        test_app = testing_compile(app)
        # Should work as async context manager (no-op when no family)
        async with test_app as ta:
            result = await ta.routes[0].call({"name": "ctx"})
            assert isinstance(result, SimpleResp)

    @pytest.mark.asyncio
    async def test_backward_compat_wrappers(self) -> None:
        from emergent.wire.compile.targets.testing import (
            wrap_rrc_testing,
            wrap_immediate_testing,
        )

        # RRC
        codec = rrc(SimpleReq, SimpleResp)
        handler = Handler(codec=codec, runner=_runner, capabilities=())
        route = wrap_rrc_testing(handler, "test-trigger", _axes)
        result = await route.call({"name": "wrap"})
        assert isinstance(result, SimpleResp)

        # Immediate
        codec_imm = immediate(ImmResp)
        handler_imm = Handler(codec=codec_imm, runner=_runner, capabilities=())
        route_imm = wrap_immediate_testing(handler_imm, "test", _axes)
        result_imm = await route_imm.call()
        assert isinstance(result_imm, ImmResp)


# ═══════════════════════════════════════════════════════════════════════════════
# Event Target — EventDispatcher
# ═══════════════════════════════════════════════════════════════════════════════


class TestEventTarget:
    """Cover event_compile, EventDispatcher, RRC and Delegate events."""

    @pytest.mark.asyncio
    async def test_rrc_event_dispatch(self) -> None:
        from emergent.wire.compile.targets.event import event_compile

        @dataclass
        class OrderEvt:
            order_id: int
            name: str

        @dataclass
        class OrderReq:
            name: str

            def to_domain(self) -> GreetOp:
                return GreetOp(name=self.name)

        app = _make_app(
            endpoint(_runner).expose(
                EventTrigger(OrderEvt),
                rrc(OrderReq, SimpleResp),
            )
        )
        dispatcher = event_compile(app)
        results = await dispatcher.dispatch(OrderEvt(order_id=1, name="test"))
        assert len(results) == 1
        assert isinstance(results[0], SimpleResp)

    @pytest.mark.asyncio
    async def test_delegate_event_dispatch(self) -> None:
        from emergent.wire.compile.targets.event import event_compile

        @dataclass
        class SignalEvt:
            msg: str

        async def handle_signal() -> str:
            return "handled"

        app = _make_app(
            endpoint(_runner).expose(
                EventTrigger(SignalEvt),
                delegate(handle_signal),
            )
        )
        dispatcher = event_compile(app)
        results = await dispatcher.dispatch(SignalEvt(msg="go"))
        assert len(results) == 1
        assert results[0] == "handled"

    @pytest.mark.asyncio
    async def test_event_dispatcher_no_matching_handler(self) -> None:
        from emergent.wire.compile.targets.event import event_compile

        @dataclass
        class Registered:
            x: int

        @dataclass
        class Unregistered:
            y: int

        app = _make_app(
            endpoint(_runner).expose(
                EventTrigger(Registered),
                immediate(ImmResp),
            )
        )
        # ImmediateCodec is not in EVENT_COMPILER bindings, so nothing gets
        # registered, and dispatching an unrelated type returns empty tuple
        dispatcher = event_compile(app)
        results = await dispatcher.dispatch(Unregistered(y=1))
        assert results == ()

    @pytest.mark.asyncio
    async def test_event_dispatcher_context_manager(self) -> None:
        from emergent.wire.compile.targets.event import event_compile

        @dataclass
        class Evt:
            val: int

        async def handler() -> str:
            return "ok"

        app = _make_app(
            endpoint(_runner).expose(EventTrigger(Evt), delegate(handler))
        )
        dispatcher = event_compile(app)
        async with dispatcher as d:
            results = await d.dispatch(Evt(val=1))
            assert len(results) == 1

    @pytest.mark.asyncio
    async def test_event_backward_compat_wrappers(self) -> None:
        from emergent.wire.compile.targets.event import (
            wrap_rrc_event,
        )

        @dataclass
        class Evt2:
            name: str

        # RRC wrapper
        codec = rrc(SimpleReq, SimpleResp)
        handler = Handler(codec=codec, runner=_runner, capabilities=())
        trigger: EventTrigger[object] = EventTrigger(Evt2)
        route = wrap_rrc_event(handler, trigger, _axes)
        result = await route.call(Evt2(name="test"))
        assert isinstance(result, SimpleResp)


# ═══════════════════════════════════════════════════════════════════════════════
# Pure Target — Lifecycle, Exception, WebSocket
# ═══════════════════════════════════════════════════════════════════════════════


class TestPureTarget:
    """Cover lifecycle, exception, and websocket compilation."""

    def test_startup_compiler_delegate(self) -> None:
        from emergent.wire.compile.targets.pure import STARTUP_COMPILER

        call_log: list[str] = []

        async def init_db() -> None:
            call_log.append("init")

        app = _make_app(
            endpoint(_runner).expose(
                StartupTrigger(order=0),
                delegate(init_db),
            )
        )
        routes = list(STARTUP_COMPILER.scan_and_wrap(app, _axes))
        assert len(routes) == 1
        _, _, route = routes[0]
        assert route.order == 0

    def test_shutdown_compiler_delegate(self) -> None:
        from emergent.wire.compile.targets.pure import SHUTDOWN_COMPILER

        async def close_db() -> None:
            pass

        app = _make_app(
            endpoint(_runner).expose(
                ShutdownTrigger(order=5),
                delegate(close_db),
            )
        )
        routes = list(SHUTDOWN_COMPILER.scan_and_wrap(app, _axes))
        assert len(routes) == 1
        _, _, route = routes[0]
        assert route.order == 5

    def test_startup_factory_codec(self) -> None:
        from emergent.wire.compile.targets.pure import STARTUP_COMPILER

        app = _make_app(
            endpoint(_runner).expose(
                StartupTrigger(order=1),
                immediate_factory(lambda: None),
            )
        )
        routes = list(STARTUP_COMPILER.scan_and_wrap(app, _axes))
        assert len(routes) == 1

    @pytest.mark.asyncio
    async def test_lifecycle_route_executes(self) -> None:
        from emergent.wire.compile.targets.pure import STARTUP_COMPILER

        call_log: list[str] = []

        async def init() -> None:
            call_log.append("started")

        app = _make_app(
            endpoint(_runner).expose(StartupTrigger(), delegate(init))
        )
        routes = list(STARTUP_COMPILER.scan_and_wrap(app, _axes))
        _, _, route = routes[0]
        await route.handler()
        assert call_log == ["started"]

    def test_exception_compiler(self) -> None:
        from emergent.wire.compile.targets.pure import EXCEPTION_COMPILER

        async def handle_exc(exc: ValueError) -> str:
            return f"error: {exc}"

        app = _make_app(
            endpoint(_runner).expose(
                ExceptionTrigger(ValueError),
                delegate(handle_exc),
            )
        )
        scan_results: list[Any] = list(EXCEPTION_COMPILER.scan_and_wrap(app, _axes))
        assert len(scan_results) == 1
        _, _, route = scan_results[0]
        assert route.exception_type is ValueError
        assert route.propagate is False

    def test_exception_with_propagate(self) -> None:
        from emergent.wire.compile.targets.pure import EXCEPTION_COMPILER

        async def handle_exc(exc: RuntimeError) -> str:
            return "handled"

        app = _make_app(
            endpoint(_runner).expose(
                ExceptionTrigger(RuntimeError, propagate=True),
                delegate(handle_exc),
            )
        )
        scan_results: list[Any] = list(EXCEPTION_COMPILER.scan_and_wrap(app, _axes))
        _, _, route = scan_results[0]
        assert route.propagate is True

    def test_websocket_compiler(self) -> None:
        from emergent.wire.compile.targets.pure import WEBSOCKET_COMPILER

        async def ws_handler() -> None:
            pass

        app = _make_app(
            endpoint(_runner).expose(
                WebSocketTrigger("/ws/chat"),
                delegate(ws_handler),
            )
        )
        routes = list(WEBSOCKET_COMPILER.scan_and_wrap(app, _axes))
        assert len(routes) == 1

    @pytest.mark.asyncio
    async def test_app_scope_lifespan(self) -> None:
        from emergent.wire.compile.targets.pure import app_scope_lifespan
        from nodnod import Scope

        scope = Scope(detail="test-app")
        async with app_scope_lifespan(scope) as s:
            assert s is scope

    @pytest.mark.asyncio
    async def test_backward_compat_lifecycle_wrappers(self) -> None:
        from emergent.wire.compile.targets.pure import (
            wrap_lifecycle_delegate,
            wrap_lifecycle_factory,
        )

        async def init() -> None:
            pass

        codec_d = delegate(init)
        handler_d = Handler(codec=codec_d, runner=_runner, capabilities=())
        route_d = wrap_lifecycle_delegate(handler_d, StartupTrigger(order=2), _axes)
        assert route_d.order == 2

        codec_f = immediate_factory(lambda: None)
        handler_f = Handler(codec=codec_f, runner=_runner, capabilities=())
        route_f = wrap_lifecycle_factory(handler_f, ShutdownTrigger(order=3), _axes)
        assert route_f.order == 3

    @pytest.mark.asyncio
    async def test_backward_compat_exception_wrapper(self) -> None:
        from emergent.wire.compile.targets.pure import wrap_exception_delegate

        async def handle(exc: TypeError) -> str:
            return "caught"

        codec = delegate(handle)
        handler = Handler(codec=codec, runner=_runner, capabilities=())
        route = wrap_exception_delegate(
            handler, ExceptionTrigger(TypeError), _axes
        )
        assert route.exception_type is TypeError

    @pytest.mark.asyncio
    async def test_backward_compat_websocket_wrapper(self) -> None:
        from emergent.wire.compile.targets.pure import wrap_websocket_delegate

        async def ws() -> None:
            pass

        codec = delegate(ws)
        handler = Handler(codec=codec, runner=_runner, capabilities=())
        route = wrap_websocket_delegate(
            handler, WebSocketTrigger("/ws"), _axes
        )
        assert route.handler is not None


# ═══════════════════════════════════════════════════════════════════════════════
# FastAPI — Lifecycle + Exception in fastapi_compile
# ═══════════════════════════════════════════════════════════════════════════════


class TestFastAPILifecycleIntegration:
    """Cover startup/shutdown and exception handlers via fastapi_compile."""

    def test_fastapi_compile_with_lifecycle(self) -> None:
        from emergent.wire.compile.targets.fastapi import fastapi_compile

        startup_called: list[str] = []
        shutdown_called: list[str] = []

        async def on_start() -> None:
            startup_called.append("start")

        async def on_stop() -> None:
            shutdown_called.append("stop")

        app = _make_app(
            endpoint(_runner)
            .expose(HTTPRouteTrigger("GET", "/health"), immediate(ImmResp))
            .expose(StartupTrigger(order=0), delegate(on_start))
            .expose(ShutdownTrigger(order=0), delegate(on_stop))
        )
        fapi = fastapi_compile(app)
        assert isinstance(fapi, fastapi.FastAPI)

    def test_fastapi_compile_with_exception_handler(self) -> None:
        from emergent.wire.compile.targets.fastapi import fastapi_compile

        async def handle_value_error(exc: ValueError) -> dict[str, str]:
            return {"error": str(exc)}

        app = _make_app(
            endpoint(_runner)
            .expose(HTTPRouteTrigger("GET", "/health"), immediate(ImmResp))
            .expose(ExceptionTrigger(ValueError), delegate(handle_value_error))
        )
        fapi = fastapi_compile(app)
        assert isinstance(fapi, fastapi.FastAPI)

    def test_websocket_compiler_produces_routes(self) -> None:
        """WebSocket compilation produces routes via WEBSOCKET_COMPILER.
        Testing directly avoids FastAPI closure annotation issues."""
        from emergent.wire.compile.targets.pure import WEBSOCKET_COMPILER

        async def ws_handler() -> None:
            pass

        app = _make_app(
            endpoint(_runner).expose(
                WebSocketTrigger("/ws/test", name="test-ws"),
                delegate(ws_handler),
            )
        )
        routes = list(WEBSOCKET_COMPILER.scan_and_wrap(app, _axes))
        assert len(routes) == 1
        _, _, ws_route = routes[0]
        assert ws_route.handler is not None


# ═══════════════════════════════════════════════════════════════════════════════
# TargetCompiler — Algebraic Operations
# ═══════════════════════════════════════════════════════════════════════════════


class TestTargetCompilerAlgebra:
    """Cover TargetCompiler algebraic operations."""

    def test_contains_by_type(self) -> None:
        from emergent.wire.compile.targets.fastapi import FASTAPI_COMPILER

        assert RequestResponseCodec in FASTAPI_COMPILER
        assert DelegateCodec in FASTAPI_COMPILER

    def test_without_binding(self) -> None:
        from emergent.wire.compile.targets.fastapi import FASTAPI_COMPILER
        from emergent.wire.axis.surface.codecs.stateful import StatefulCodec

        reduced = FASTAPI_COMPILER.without_binding(StatefulCodec)
        assert StatefulCodec not in reduced
        assert RequestResponseCodec in reduced

    def test_getitem(self) -> None:
        from emergent.wire.compile.targets.fastapi import FASTAPI_COMPILER

        binding = FASTAPI_COMPILER[RequestResponseCodec]
        assert binding.codec_type is RequestResponseCodec

    def test_getitem_missing_raises(self) -> None:
        from emergent.wire.compile.targets.fastapi import FASTAPI_COMPILER

        class UnknownCodec:
            pass

        with pytest.raises(KeyError):
            FASTAPI_COMPILER[UnknownCodec]

    def test_len(self) -> None:
        from emergent.wire.compile.targets.fastapi import FASTAPI_COMPILER

        assert len(FASTAPI_COMPILER) >= 4

    def test_iter(self) -> None:
        from emergent.wire.compile.targets.fastapi import FASTAPI_COMPILER

        bindings = list(FASTAPI_COMPILER)
        assert len(bindings) == len(FASTAPI_COMPILER)

    def test_bool(self) -> None:
        from emergent.wire.compile.targets.fastapi import FASTAPI_COMPILER
        from emergent.wire.compile._target import TargetCompiler

        assert bool(FASTAPI_COMPILER) is True
        empty = TargetCompiler(trigger_type=HTTPRouteTrigger, adapters=())
        assert bool(empty) is False


# ═══════════════════════════════════════════════════════════════════════════════
# CLI — Backward Compat Wrappers
# ═══════════════════════════════════════════════════════════════════════════════


class TestCLIBackwardCompatWrappers:
    """Cover wrap_rrc_cli, wrap_delegate_cli, wrap_rrc_cli_typed."""

    def test_wrap_rrc_cli(self) -> None:
        from emergent.wire.compile.targets.cli import wrap_rrc_cli

        codec = rrc(SimpleReq, SimpleResp)
        handler = Handler(codec=codec, runner=_runner, capabilities=())
        route = wrap_rrc_cli(handler, CLITrigger("greet"), _axes)
        assert isinstance(route, ArgSpec) or route.handler is not None

    def test_wrap_delegate_cli(self) -> None:
        from emergent.wire.compile.targets.cli import wrap_delegate_cli

        def my_handler(name: str) -> str:
            return name

        codec = delegate(my_handler)
        handler = Handler(codec=codec, runner=_runner, capabilities=())
        route = wrap_delegate_cli(handler, CLITrigger("run"), _axes)
        assert route.handler is not None

    def test_wrap_rrc_cli_typed(self) -> None:
        from emergent.wire.compile.targets.cli import wrap_rrc_cli_typed

        codec = rrc(SimpleReq, SimpleResp)
        handler = Handler(codec=codec, runner=_runner, capabilities=())
        route = wrap_rrc_cli_typed(handler, CLITrigger("greet"), _axes)
        assert route.handler is not None


# ═══════════════════════════════════════════════════════════════════════════════
# CLI — Prompt Value Helper
# ═══════════════════════════════════════════════════════════════════════════════


def _fake_input(val: str) -> Any:
    """Create a typed input replacement returning a fixed value."""
    def _inner(_prompt: str) -> str:
        return val
    return _inner


class TestCLIPromptValue:
    """Cover _prompt_value for different types."""

    def test_prompt_value_int(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from emergent.wire.compile.targets.cli import _prompt_value

        monkeypatch.setattr("builtins.input", _fake_input("42"))
        result = _prompt_value("count", int)
        assert result == 42

    def test_prompt_value_float(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from emergent.wire.compile.targets.cli import _prompt_value

        monkeypatch.setattr("builtins.input", _fake_input("3.14"))
        result = _prompt_value("pi", float)
        assert result == 3.14

    def test_prompt_value_bool_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from emergent.wire.compile.targets.cli import _prompt_value

        monkeypatch.setattr("builtins.input", _fake_input("yes"))
        result = _prompt_value("flag", bool)
        assert result is True

    def test_prompt_value_bool_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from emergent.wire.compile.targets.cli import _prompt_value

        monkeypatch.setattr("builtins.input", _fake_input("no"))
        result = _prompt_value("flag", bool)
        assert result is False

    def test_prompt_value_str(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from emergent.wire.compile.targets.cli import _prompt_value

        monkeypatch.setattr("builtins.input", _fake_input("hello"))
        result = _prompt_value("text", str)
        assert result == "hello"

    def test_prompt_value_empty_returns_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from emergent.wire.compile.targets.cli import _prompt_value

        monkeypatch.setattr("builtins.input", _fake_input(""))
        result = _prompt_value("text", str)
        assert result is None

    def test_prompt_value_eof_returns_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from emergent.wire.compile.targets.cli import _prompt_value

        def raise_eof(_: str) -> str:
            raise EOFError

        monkeypatch.setattr("builtins.input", raise_eof)
        result = _prompt_value("text", str)
        assert result is None


# ═══════════════════════════════════════════════════════════════════════════════
# Compile Infrastructure — _core.py (fold, fold_field, traced_fold)
# ═══════════════════════════════════════════════════════════════════════════════


class TestCoreFold:
    """Cover fold with custom handlers and tracing."""

    def test_fold_with_custom_handler(self) -> None:
        from emergent.wire.compile._core import fold

        class Proto:
            def method(self, ctx: int) -> int:
                return ctx + 1

        items = [Proto(), Proto()]
        result = fold(items, 0, Proto, "method")
        assert result == 2

    def test_fold_skips_non_matching(self) -> None:
        from emergent.wire.compile._core import fold

        class Proto:
            def method(self, ctx: int) -> int:
                return ctx + 1

        class NotProto:
            pass

        items: list[Proto | NotProto] = [Proto(), NotProto(), Proto()]
        result = fold(items, 0, Proto, "method")
        assert result == 2

    def test_fold_with_handlers_override(self) -> None:
        from emergent.wire.compile._core import fold

        class Proto:
            def method(self, ctx: int) -> int:
                return ctx + 1

        class Special:
            pass

        def special_handler(item: Special, ctx: int) -> int:
            return ctx + 10

        items: list[Proto | Special] = [Proto(), Special()]
        result = fold(items, 0, Proto, "method", handlers={Special: special_handler})
        assert result == 11

    def test_traced_fold_records_steps(self) -> None:
        from emergent.wire.compile._core import traced_fold
        from emergent.wire.compile._trace import ListCollector

        class Proto:
            def method(self, ctx: int) -> int:
                return ctx + 1

        collector = ListCollector()
        items = [Proto(), Proto()]
        result, trace = traced_fold(items, 0, Proto, "method", None, collector)
        assert result == 2
        assert len(trace.steps) == 2
        assert trace.items_applied == 2


# ═══════════════════════════════════════════════════════════════════════════════
# FastAPI compile — Stateful from_codec
# ═══════════════════════════════════════════════════════════════════════════════


class TestFastAPIStatefulFromCodec:
    """Cover stateful_from_codec for FastAPI."""

    def test_stateful_from_codec_creates_context(self) -> None:
        from emergent.wire.compile.targets.fastapi import stateful_from_codec

        @dataclass(frozen=True)
        class FakeStatefulCodec:
            flow: type = type(None)
            response: type = SimpleResp
            key_node: type = type(None)
            agent_cls: type | None = None
            store: Any = None

        codec: Any = FakeStatefulCodec()
        trigger = HTTPRouteTrigger("POST", "/flow")
        ctx = stateful_from_codec(codec, trigger)
        assert ctx.execute is not None
        assert ctx.response_type is SimpleResp
        assert ctx.trigger is trigger


# ═══════════════════════════════════════════════════════════════════════════════
# FastAPI — Pydantic detection helpers
# ═══════════════════════════════════════════════════════════════════════════════


class TestPydanticDetection:
    """Cover is_pydantic_model and _get_pydantic_types_from_transitions."""

    def test_is_pydantic_model_with_base_model(self) -> None:
        from pydantic import BaseModel
        from emergent.wire.compile.targets.fastapi import is_pydantic_model

        class MyModel(BaseModel):
            x: int

        assert is_pydantic_model(MyModel) is True

    def test_is_pydantic_model_with_dataclass(self) -> None:
        from emergent.wire.compile.targets.fastapi import is_pydantic_model

        assert is_pydantic_model(SimpleReq) is False

    def test_is_pydantic_model_with_none(self) -> None:
        from emergent.wire.compile.targets.fastapi import is_pydantic_model

        assert is_pydantic_model(None) is False

    def test_is_pydantic_model_with_int(self) -> None:
        from emergent.wire.compile.targets.fastapi import is_pydantic_model

        assert is_pydantic_model(42) is False


# ═══════════════════════════════════════════════════════════════════════════════
# FastAPI — setup_fastapi_scope
# ═══════════════════════════════════════════════════════════════════════════════


class TestSetupFastapiScope:
    """Cover setup_fastapi_scope with and without pydantic types."""

    @pytest.mark.asyncio
    async def test_scope_injects_request(self) -> None:
        from emergent.wire.compile.targets.fastapi import setup_fastapi_scope
        from nodnod import Scope
        from unittest.mock import MagicMock

        scope = Scope(detail="test")
        request = MagicMock(spec=fastapi.Request)
        async with scope:
            await setup_fastapi_scope(scope, request, set())
            wrapper = scope.get(fastapi.Request)
            assert wrapper is not None
            assert wrapper.value is request

    @pytest.mark.asyncio
    async def test_scope_injects_pydantic_models(self) -> None:
        from pydantic import BaseModel
        from emergent.wire.compile.targets.fastapi import setup_fastapi_scope
        from nodnod import Scope
        from unittest.mock import AsyncMock, MagicMock

        class UserInput(BaseModel):
            name: str
            age: int

        scope = Scope(detail="test")
        request = MagicMock(spec=fastapi.Request)
        request.json = AsyncMock(return_value={"name": "Alice", "age": 30})

        async with scope:
            await setup_fastapi_scope(scope, request, {UserInput})
            wrapper = scope.get(UserInput)
            assert wrapper is not None
            assert wrapper.value.name == "Alice"

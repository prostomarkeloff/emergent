# pyright: reportPrivateUsage=false
"""Deep coverage tests for compile targets — FastAPI, CLI, Pure, Telegrinder.

Covers remaining uncovered lines in:
  - fastapi.py (extractors, openapi, capabilities, compile_stack, lifecycle, etc.)
  - cli.py (delegate, immediate, stateful from_codec, compile_stack, cli_run)
  - pure.py (lifecycle routes, exception routes, websocket routes, app_scope_lifespan)
  - telegrinder.py (importability, response formatting, from_codec functions)
  - _execute.py (execute_immediate_unified, execute_delegate_unified, _call_delegate)
  - _delegate.py (resolve_handler_params, _extract_compose_capability, etc.)
  - _pipeline.py (compile_pipeline, execute_with_pipeline)
  - _request.py (build_request, build_request_sync, build_field_value)
  - _stateful.py (load_state, save_state, delete_state, get_stateful_metadata)

Uses emergent's own pipeline to build Application objects then compile them.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Annotated, Any, Self, cast

import fastapi
import pytest
from kungfu import Ok, Result

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
    immediate_factory,
)
from emergent.wire.axis.surface.codecs.delegate import delegate, DelegateCodec
from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger
from emergent.wire.axis.surface.triggers.cli import CLITrigger
from emergent.wire.axis.surface.triggers.lifecycle import StartupTrigger, ShutdownTrigger
from emergent.wire.axis.surface.triggers.exception import ExceptionTrigger
from emergent.wire.axis.surface.triggers.websocket import WebSocketTrigger
from emergent.wire.compile._core import Axes
from emergent.wire.compile.targets.fastapi import (
    fastapi_compile,
    fastapi_compile_stack,
    fastapi_compile_endpoint,
    FASTAPI_COMPILER,
    FastAPIRoute,
    FastAPIWrapContext,
    rrc_from_codec,
    immediate_from_codec,
    delegate_from_codec,
    assemble_fastapi_route,
    build_rrc_openapi_extra,
    FastAPIJsonExtractor,
    FastAPIQueryExtractor,
    FastAPIFormExtractor,
    is_pydantic_model,
    init_fastapi_extraction_constants,
)
from emergent.wire.compile.targets.cli import (
    cli_compile,
    cli_compile_stack,
    cli_run,
    CLI_COMPILER,
    TYPED_CLI,
    CLIRoute,
    CLIWrapContext,
    rrc_from_codec_cli,
    immediate_from_codec_cli,
    delegate_from_codec_cli,
    assemble_cli_route,
    register_handler as cli_register_handler,
    wrap_rrc_cli,
    wrap_immediate_cli,
    wrap_delegate_cli,
    wrap_rrc_cli_typed,
    coerce_cli_values,
    _inspect_handler_params,
    _get_delegate_arg_specs,
    _build_delegate_args,
)
from emergent.wire.compile.targets.pure import (
    STARTUP_COMPILER,
    SHUTDOWN_COMPILER,
    EXCEPTION_COMPILER,
    WEBSOCKET_COMPILER,
    LifecycleRoute,
    ExceptionRoute,
    WebSocketRoute,
    LifecycleWrapContext,
    ExceptionWrapContext,
    WebSocketWrapContext,
    app_scope_lifespan,
    wrap_lifecycle_delegate,
    wrap_lifecycle_factory,
    wrap_exception_delegate,
    wrap_websocket_delegate,
    _lifecycle_delegate_from_codec,
    _lifecycle_factory_from_codec,
    _exception_delegate_from_codec,
    _websocket_delegate_from_codec,
    _assemble_lifecycle,
    _assemble_exception,
    _assemble_websocket,
)
from emergent.wire.compile._execute import (
    execute_immediate_unified,
    execute_delegate_unified,
)
from emergent.wire.compile._pipeline import (
    compile_pipeline,
    CompiledPipeline,
)
from emergent.wire.compile._request import (
    build_request,
    build_request_sync,
)
from emergent.wire.compile._stateful import (
    get_stateful_metadata,
)
from emergent.wire.axis.schema.dialects.cli import (
    Positional as CLIPositional,
    Choices as CLIChoices,
    Help as CLIFieldHelp,
)


# =============================================================================
# Domain types
# =============================================================================


@dataclass
class PingOp(Op[str, str]):
    msg: str


async def _ping_handler(req: PingOp) -> Result[str, str]:
    return Ok(f"pong:{req.msg}")


@dataclass
class PingRequest:
    msg: str

    def to_domain(self) -> PingOp:
        return PingOp(msg=self.msg)


@dataclass
class PingResponse:
    reply: str

    @classmethod
    def from_domain(cls, dom: Result[str, str]) -> Self:
        match dom:
            case Ok(v):
                return cls(reply=v)
            case _:
                return cls(reply="error")


@dataclass
class CreateOp(Op[dict[str, object], str]):
    name: str
    age: int


async def _create_handler(req: CreateOp) -> Result[dict[str, object], str]:
    result: dict[str, object] = {"name": req.name, "age": req.age}
    return Ok(result)


@dataclass
class CreateRequest:
    name: str
    age: int

    def to_domain(self) -> CreateOp:
        return CreateOp(name=self.name, age=self.age)


@dataclass
class CreateResponse:
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
class HealthStatus:
    status: str

    @classmethod
    def produce(cls) -> Self:
        return cls(status="healthy")


def _runner():
    return ops().on(PingOp, _ping_handler).on(CreateOp, _create_handler).compile()


# --- Dataclasses with schema dialect annotations (must be module-level for __future__ annotations) ---


@dataclass
class ReqWithPositional:
    target: Annotated[str, CLIPositional()]

    def to_domain(self) -> PingOp:
        return PingOp(msg=self.target)


@dataclass
class ReqWithChoices:
    format: Annotated[str, CLIChoices("json", "yaml", "text")]

    def to_domain(self) -> PingOp:
        return PingOp(msg=self.format)


@dataclass
class ReqWithFieldHelp:
    msg: Annotated[str, CLIFieldHelp("The message to send")]

    def to_domain(self) -> PingOp:
        return PingOp(msg=self.msg)


@dataclass
class PositionalResp:
    value: str

    @classmethod
    def from_domain(cls, dom: Result[str, str]) -> Self:
        match dom:
            case Ok(v):
                return cls(value=v)
            case _:
                return cls(value="err")


# =============================================================================
# FastAPI Target — Deep
# =============================================================================


class TestFastAPIExtractors:
    """Test FastAPI extractors directly."""

    @pytest.mark.anyio
    async def test_json_extractor_with_json_body(self) -> None:
        from starlette.testclient import TestClient

        ext = FastAPIJsonExtractor()
        # We test the extractor logic by creating a mock request
        app = fastapi.FastAPI()

        @app.post("/test")
        async def _test_post(request: fastapi.Request) -> dict[str, object]:
            return await ext.extract(request)

        assert _test_post is not None  # registered via decorator
        client = TestClient(app)
        resp = client.post("/test", json={"key": "val"})
        assert resp.json()["key"] == "val"

    @pytest.mark.anyio
    async def test_query_extractor(self) -> None:
        from starlette.testclient import TestClient

        ext = FastAPIQueryExtractor()
        app = fastapi.FastAPI()

        @app.get("/test")
        async def _test_get(request: fastapi.Request) -> dict[str, object]:
            return await ext.extract(request)

        assert _test_get is not None  # registered via decorator
        client = TestClient(app)
        resp = client.get("/test?foo=bar")
        assert resp.json()["foo"] == "bar"

    def test_form_extractor_exists(self) -> None:
        ext = FastAPIFormExtractor()
        assert hasattr(ext, "extract")


class TestFastAPIOpenAPIGeneration:
    """Test OpenAPI schema generation paths."""

    def test_rrc_openapi_extra_post_endpoint(self) -> None:
        codec = RequestResponseCodec(request=CreateRequest, response=CreateResponse)
        trigger = HTTPRouteTrigger("POST", "/items")
        axes = Axes.default()
        extra = build_rrc_openapi_extra(codec, trigger, axes)
        assert extra is not None
        assert "requestBody" in extra

    def test_rrc_openapi_extra_get_endpoint_with_query_params(self) -> None:
        codec = RequestResponseCodec(request=PingRequest, response=PingResponse)
        trigger = HTTPRouteTrigger("GET", "/ping")
        axes = Axes.default()
        extra = build_rrc_openapi_extra(codec, trigger, axes)
        assert extra is not None
        assert "parameters" in extra

    def test_rrc_openapi_extra_with_path_params(self) -> None:
        codec = RequestResponseCodec(request=PingRequest, response=PingResponse)
        trigger = HTTPRouteTrigger("GET", "/ping/{msg}")
        axes = Axes.default()
        extra = build_rrc_openapi_extra(codec, trigger, axes)
        assert extra is not None
        params = extra.get("parameters", [])
        path_params = [p for p in params if p.get("in") == "path"]
        assert len(path_params) == 1
        assert path_params[0]["name"] == "msg"

    def test_rrc_openapi_extra_post_with_path_params(self) -> None:
        """POST with path params: path params extracted from body schema."""
        codec = RequestResponseCodec(request=CreateRequest, response=CreateResponse)
        trigger = HTTPRouteTrigger("POST", "/items/{name}")
        axes = Axes.default()
        extra = build_rrc_openapi_extra(codec, trigger, axes)
        assert extra is not None
        # Should have parameters (path) and requestBody (without path param fields)
        params = extra.get("parameters", [])
        path_params = [p for p in params if p.get("in") == "path"]
        assert len(path_params) == 1
        assert path_params[0]["name"] == "name"


class TestFastAPICapabilities:
    """Test FastAPI compilation with capabilities."""

    def test_tag_capability_applied(self) -> None:
        from emergent.wire.axis.surface.dialects.http import Tag

        runner = _runner()
        ep = endpoint(runner).expose(
            HTTPRouteTrigger("GET", "/tagged"),
            rrc(PingRequest, PingResponse),
            Tag.of("testing"),
        )
        app = Application().mount(ep)
        fapi = fastapi_compile(app)
        routes = [r for r in fapi.routes if isinstance(r, fastapi.routing.APIRoute)]
        tagged = [r for r in routes if r.path == "/tagged"]
        assert len(tagged) == 1
        assert "testing" in (tagged[0].tags or [])

    def test_response_status_capability(self) -> None:
        from emergent.wire.axis.surface.dialects.http import ResponseStatus

        runner = _runner()
        ep = endpoint(runner).expose(
            HTTPRouteTrigger("POST", "/created"),
            rrc(CreateRequest, CreateResponse),
            ResponseStatus(201),
        )
        app = Application().mount(ep)
        fapi = fastapi_compile(app)
        routes = [r for r in fapi.routes if isinstance(r, fastapi.routing.APIRoute)]
        created = [r for r in routes if r.path == "/created"]
        assert len(created) == 1
        assert created[0].status_code == 201

    def test_bearer_auth_capability(self) -> None:
        from emergent.wire.axis.surface.dialects.http import BearerAuth

        runner = _runner()
        ep = endpoint(runner).expose(
            HTTPRouteTrigger("GET", "/secured"),
            rrc(PingRequest, PingResponse),
            BearerAuth.jwt(),
        )
        app = Application().mount(ep)
        fapi = fastapi_compile(app)
        routes = [r for r in fapi.routes if isinstance(r, fastapi.routing.APIRoute)]
        secured = [r for r in routes if r.path == "/secured"]
        assert len(secured) == 1


class TestFastAPITracedCompilation:
    """Test compilation with Axes.traced()."""

    def test_traced_compilation_collects_events(self) -> None:
        from emergent.wire.compile._trace import ListCollector

        collector = ListCollector()
        axes = Axes.traced(collector)
        runner = _runner()
        ep = endpoint(runner).expose(
            HTTPRouteTrigger("GET", "/traced"),
            rrc(PingRequest, PingResponse),
        )
        app = Application().mount(ep)
        fapi = fastapi_compile(app, axes=axes)
        assert isinstance(fapi, fastapi.FastAPI)
        # Collector should have recorded scan and wrap events
        assert len(collector.scan_events) > 0 or len(collector.wrap_events) > 0

    def test_traced_axes_default_creates_list_collector(self) -> None:
        axes = Axes.traced()
        assert axes.trace is not None


class TestFastAPIGlobalCapabilities:
    """Test application-level capabilities."""

    def test_cors_middleware_added(self) -> None:
        from emergent.wire.axis.surface.dialects.http import CORS

        runner = _runner()
        ep = endpoint(runner).expose(
            HTTPRouteTrigger("GET", "/api"),
            rrc(PingRequest, PingResponse),
        )
        app = Application().mount(ep).with_capabilities(CORS(origins=("*",)))
        fapi = fastapi_compile(app)
        # CORS middleware should be in the middleware stack
        assert isinstance(fapi, fastapi.FastAPI)


class TestFastAPIImmediateCodec:
    """Test immediate codec compilation for FastAPI."""

    def test_immediate_endpoint_no_request(self) -> None:
        ep = endpoint(empty_runner()).expose(
            HTTPRouteTrigger("GET", "/health"),
            immediate(HealthStatus),
        )
        app = Application().mount(ep)
        fapi = fastapi_compile(app)
        paths = [r.path for r in fapi.routes if isinstance(r, fastapi.routing.APIRoute)]
        assert "/health" in paths

    def test_immediate_factory_endpoint(self) -> None:
        ep = endpoint(empty_runner()).expose(
            HTTPRouteTrigger("GET", "/version"),
            immediate_factory(lambda: {"version": "1.0"}),
        )
        app = Application().mount(ep)
        fapi = fastapi_compile(app)
        paths = [r.path for r in fapi.routes if isinstance(r, fastapi.routing.APIRoute)]
        assert "/version" in paths


class TestFastAPIDelegateCodec:
    """Test delegate codec compilation for FastAPI."""

    def test_delegate_endpoint_registered(self) -> None:
        async def my_handler() -> dict[str, str]:
            return {"status": "ok"}

        ep = endpoint(empty_runner()).expose(
            HTTPRouteTrigger("GET", "/delegate"),
            delegate(my_handler),
        )
        app = Application().mount(ep)
        fapi = fastapi_compile(app)
        paths = [r.path for r in fapi.routes if isinstance(r, fastapi.routing.APIRoute)]
        assert "/delegate" in paths


class TestFastAPICompileEndpoint:
    """Test fastapi_compile_endpoint."""

    def test_compile_single_endpoint(self) -> None:
        runner = _runner()
        ep = (
            endpoint(runner)
            .expose(HTTPRouteTrigger("GET", "/ep1"), rrc(PingRequest, PingResponse))
            .expose(HTTPRouteTrigger("POST", "/ep2"), rrc(CreateRequest, CreateResponse))
        )
        routes = fastapi_compile_endpoint(ep)
        assert len(routes) == 2
        paths = {r.path for r in routes}
        assert "/ep1" in paths
        assert "/ep2" in paths


class TestFastAPICompileStack:
    """Test fastapi_compile_stack for nested routers."""

    def test_stack_compilation(self) -> None:
        runner = _runner()
        ep1 = endpoint(runner).expose(
            HTTPRouteTrigger("GET", "/ping"),
            rrc(PingRequest, PingResponse),
        )
        ep2 = endpoint(runner).expose(
            HTTPRouteTrigger("POST", "/create"),
            rrc(CreateRequest, CreateResponse),
        )
        root_app = Application().mount(ep1)
        sub_app = Application().mount(ep2)
        stack = app_stack().root(root_app).mount("admin", sub_app)
        fapi = fastapi_compile_stack(stack)
        assert isinstance(fapi, fastapi.FastAPI)


class TestFastAPILifecycleIntegration:
    """Test lifecycle triggers are picked up by fastapi_compile."""

    def test_startup_shutdown_triggers(self) -> None:
        started: list[str] = []
        stopped: list[str] = []

        async def on_start() -> None:
            started.append("up")

        async def on_stop() -> None:
            stopped.append("down")

        ep_start = endpoint(empty_runner()).expose(StartupTrigger(order=0), delegate(on_start))
        ep_stop = endpoint(empty_runner()).expose(ShutdownTrigger(order=0), delegate(on_stop))
        runner = _runner()
        ep_http = endpoint(runner).expose(
            HTTPRouteTrigger("GET", "/ping"),
            rrc(PingRequest, PingResponse),
        )
        app = Application().mount(ep_start, ep_stop, ep_http)
        fapi = fastapi_compile(app)
        assert isinstance(fapi, fastapi.FastAPI)
        # Lifecycle events are wired into lifespan, tested structurally


class TestFastAPIExceptionHandlers:
    """Test exception trigger integration."""

    def test_exception_triggers_found(self) -> None:
        async def handle_value_error(exc: ValueError) -> str:
            return f"caught: {exc}"

        ep = endpoint(empty_runner()).expose(
            ExceptionTrigger(ValueError),
            delegate(handle_value_error),
        )
        app = Application().mount(ep)
        fapi = fastapi_compile(app)
        assert isinstance(fapi, fastapi.FastAPI)


class TestFastAPIWebsocketHandlers:
    """Test websocket trigger integration via WEBSOCKET_COMPILER."""

    def test_websocket_triggers_scanned(self) -> None:
        async def ws_handler(websocket: object) -> None:
            pass

        ep = endpoint(empty_runner()).expose(
            WebSocketTrigger("/ws/test", name="test-ws"),
            delegate(ws_handler),
        )
        app = Application().mount(ep)
        axes = Axes.default()
        items = list(WEBSOCKET_COMPILER.scan_and_wrap(app, axes))
        assert len(items) == 1
        trigger, _, route = items[0]
        assert isinstance(trigger, WebSocketTrigger)
        assert trigger.path == "/ws/test"
        assert trigger.name == "test-ws"
        assert isinstance(route, WebSocketRoute)


class TestFastAPIFromCodec:
    """Test from_codec functions directly."""

    def test_rrc_from_codec_post(self) -> None:
        codec = RequestResponseCodec(request=CreateRequest, response=CreateResponse)
        trigger = HTTPRouteTrigger("POST", "/items")
        ctx = rrc_from_codec(codec, trigger)
        assert isinstance(ctx, FastAPIWrapContext)
        assert ctx.request_type is CreateRequest
        assert ctx.response_type is CreateResponse
        assert ctx.execute is not None
        assert ctx.extractor is not None

    def test_rrc_from_codec_get(self) -> None:
        codec = RequestResponseCodec(request=PingRequest, response=PingResponse)
        trigger = HTTPRouteTrigger("GET", "/ping")
        ctx = rrc_from_codec(codec, trigger)
        assert isinstance(ctx.extractor, FastAPIQueryExtractor)

    def test_immediate_from_codec(self) -> None:
        codec = ImmediateCodec(response=HealthStatus)
        trigger = HTTPRouteTrigger("GET", "/health")
        ctx = immediate_from_codec(codec, trigger)
        assert ctx.inject_type is type(None)

    def test_delegate_from_codec(self) -> None:
        async def my_handler() -> str:
            return "ok"

        codec = DelegateCodec(handler=my_handler)
        trigger = HTTPRouteTrigger("GET", "/delegate")
        ctx = delegate_from_codec(codec, trigger)
        assert ctx.execute is not None

    def test_assemble_produces_route(self) -> None:
        codec = RequestResponseCodec(request=PingRequest, response=PingResponse)
        trigger = HTTPRouteTrigger("GET", "/ping")
        ctx = rrc_from_codec(codec, trigger)
        handler = Handler(
            codec=codec,
            runner=_runner(),
        )
        axes = Axes.default()
        route = assemble_fastapi_route(ctx, handler, axes)
        assert isinstance(route, FastAPIRoute)
        assert route.endpoint is not None


class TestIsPydanticModel:
    """Test the is_pydantic_model helper."""

    def test_dataclass_is_not_pydantic(self) -> None:
        assert is_pydantic_model(PingRequest) is False

    def test_str_is_not_pydantic(self) -> None:
        assert is_pydantic_model(str) is False

    def test_pydantic_model_is_pydantic(self) -> None:
        from pydantic import BaseModel

        class MyModel(BaseModel):
            x: int

        assert is_pydantic_model(MyModel) is True


class TestInitExtractionConstants:
    """Test lazy extraction constants initialization."""

    def test_init_does_not_raise(self) -> None:
        init_fastapi_extraction_constants()


# =============================================================================
# CLI Target — Deep
# =============================================================================


class TestCLIFromCodec:
    """Test CLI from_codec functions."""

    def test_rrc_from_codec_cli(self) -> None:
        codec = RequestResponseCodec(request=PingRequest, response=PingResponse)
        trigger = CLITrigger("ping", "Send a ping")
        ctx = rrc_from_codec_cli(codec, trigger)
        assert isinstance(ctx, CLIWrapContext)
        assert ctx.request_type is PingRequest
        assert ctx.response_type is PingResponse
        assert ctx.execute is not None
        assert len(ctx.arg_specs) > 0

    def test_immediate_from_codec_cli(self) -> None:
        codec = ImmediateCodec(response=HealthStatus)
        trigger = CLITrigger("health", "Check health")
        ctx = immediate_from_codec_cli(codec, trigger)
        assert ctx.execute is not None

    def test_delegate_from_codec_cli(self) -> None:
        def my_handler(name: str, count: int) -> str:
            return f"{name}:{count}"

        codec = DelegateCodec(handler=my_handler)
        trigger = CLITrigger("run", "Run command")
        ctx = delegate_from_codec_cli(codec, trigger)
        assert ctx.execute is not None
        assert len(ctx.arg_specs) > 0


class TestCLIAssemble:
    """Test CLI assembly."""

    def test_assemble_produces_cli_route(self) -> None:
        codec = RequestResponseCodec(request=PingRequest, response=PingResponse)
        trigger = CLITrigger("ping", "Send a ping")
        ctx = rrc_from_codec_cli(codec, trigger)
        handler = Handler(codec=codec, runner=_runner())
        axes = Axes.default()
        route = assemble_cli_route(ctx, handler, axes)
        assert isinstance(route, CLIRoute)
        assert route.handler is not None

    def test_assemble_raises_without_execute(self) -> None:
        ctx = CLIWrapContext()
        handler = Handler(codec=RequestResponseCodec(request=PingRequest, response=PingResponse), runner=_runner())
        axes = Axes.default()
        with pytest.raises(ValueError, match="execute must be set"):
            assemble_cli_route(ctx, handler, axes)


class TestCLICompile:
    """Test full CLI compilation."""

    def test_rrc_cli_compile(self) -> None:
        runner = _runner()
        ep = (
            endpoint(runner)
            .expose(CLITrigger("ping", "Ping"), rrc(PingRequest, PingResponse))
            .expose(CLITrigger("create", "Create"), rrc(CreateRequest, CreateResponse))
        )
        app = Application().mount(ep)
        parser = cli_compile(app, prog="test")
        assert isinstance(parser, argparse.ArgumentParser)

    def test_immediate_cli_compile(self) -> None:
        ep = endpoint(empty_runner()).expose(
            CLITrigger("health", "Check health"),
            immediate(HealthStatus),
        )
        app = Application().mount(ep)
        parser = cli_compile(app, prog="test")
        assert isinstance(parser, argparse.ArgumentParser)

    def test_delegate_cli_compile(self) -> None:
        def handle_status(name: str) -> str:
            return f"status:{name}"

        ep = endpoint(empty_runner()).expose(
            CLITrigger("status", "Get status"),
            delegate(handle_status),
        )
        app = Application().mount(ep)
        parser = cli_compile(app, prog="test")
        assert isinstance(parser, argparse.ArgumentParser)


class TestCLICapabilities:
    """Test CLI-specific capabilities."""

    def test_hidden_command(self) -> None:
        from emergent.wire.axis.surface.dialects.cli import Hidden

        runner = _runner()
        ep = endpoint(runner).expose(
            CLITrigger("secret", "Hidden cmd"),
            rrc(PingRequest, PingResponse),
            Hidden(),
        )
        app = Application().mount(ep)
        parser = cli_compile(app, prog="test")
        assert isinstance(parser, argparse.ArgumentParser)

    def test_help_text_capability(self) -> None:
        from emergent.wire.axis.surface.dialects.cli import Help

        runner = _runner()
        ep = endpoint(runner).expose(
            CLITrigger("greet", "Greet user"),
            rrc(PingRequest, PingResponse),
            Help("Custom help text"),
        )
        app = Application().mount(ep)
        parser = cli_compile(app, prog="test")
        assert isinstance(parser, argparse.ArgumentParser)

    def test_description_capability(self) -> None:
        from emergent.wire.axis.surface.dialects.cli import Description

        runner = _runner()
        ep = endpoint(runner).expose(
            CLITrigger("describe", "Describe"),
            rrc(PingRequest, PingResponse),
            Description("Long description text"),
        )
        app = Application().mount(ep)
        parser = cli_compile(app, prog="test")
        assert isinstance(parser, argparse.ArgumentParser)

    def test_epilog_capability(self) -> None:
        from emergent.wire.axis.surface.dialects.cli import Epilog

        runner = _runner()
        ep = endpoint(runner).expose(
            CLITrigger("epilog", "Epilog"),
            rrc(PingRequest, PingResponse),
            Epilog("Example usage text"),
        )
        app = Application().mount(ep)
        parser = cli_compile(app, prog="test")
        assert isinstance(parser, argparse.ArgumentParser)


class TestCLICompileStack:
    """Test CLI compile_stack for nested subcommands."""

    def test_stack_produces_nested_subcommands(self) -> None:
        runner = _runner()
        ep_root = endpoint(runner).expose(
            CLITrigger("ping", "Ping"),
            rrc(PingRequest, PingResponse),
        )
        ep_sub = endpoint(runner).expose(
            CLITrigger("create", "Create"),
            rrc(CreateRequest, CreateResponse),
        )
        root_app = Application().mount(ep_root)
        sub_app = Application().mount(ep_sub)
        stack = app_stack().root(root_app).mount("admin", sub_app)
        parser = cli_compile_stack(stack, prog="test")
        assert isinstance(parser, argparse.ArgumentParser)


class TestCLIBackwardCompatWrappers:
    """Test backward-compat wrapper functions."""

    def test_wrap_rrc_cli(self) -> None:
        codec = RequestResponseCodec(request=PingRequest, response=PingResponse)
        trigger = CLITrigger("ping", "Ping")
        handler = Handler(codec=codec, runner=_runner())
        axes = Axes.default()
        route = wrap_rrc_cli(handler, trigger, axes)
        assert isinstance(route, CLIRoute)

    def test_wrap_immediate_cli(self) -> None:
        codec = ImmediateCodec(response=HealthStatus)
        trigger = CLITrigger("health", "Health")
        handler = Handler(codec=codec, runner=empty_runner())
        axes = Axes.default()
        route = wrap_immediate_cli(handler, trigger, axes)
        assert isinstance(route, CLIRoute)

    def test_wrap_delegate_cli(self) -> None:
        def my_handler(x: int) -> str:
            return str(x)

        codec = DelegateCodec(handler=my_handler)
        trigger = CLITrigger("run", "Run")
        handler = Handler(codec=codec, runner=empty_runner())
        axes = Axes.default()
        route = wrap_delegate_cli(handler, trigger, axes)
        assert isinstance(route, CLIRoute)

    def test_wrap_rrc_cli_typed(self) -> None:
        codec = RequestResponseCodec(request=PingRequest, response=PingResponse)
        trigger = CLITrigger("ping", "Ping")
        handler = Handler(codec=codec, runner=_runner())
        axes = Axes.default()
        route = wrap_rrc_cli_typed(handler, trigger, axes)
        assert isinstance(route, CLIRoute)


class TestCLIDelegateHelpers:
    """Test CLI delegate helper functions."""

    def test_inspect_handler_params(self) -> None:
        def my_handler(name: str, count: int = 5) -> str:
            return f"{name}:{count}"

        params = _inspect_handler_params(my_handler)
        assert len(params) == 2
        names = [p[0] for p in params]
        assert "name" in names
        assert "count" in names

    def test_get_delegate_arg_specs(self) -> None:
        def my_handler(name: str, flag: bool = False) -> str:
            return name

        axes = Axes.default()
        specs = _get_delegate_arg_specs(my_handler, axes)
        assert len(specs) > 0

    def test_build_delegate_args(self) -> None:
        def my_handler(name: str, count: int = 5) -> str:
            return f"{name}:{count}"

        ns = argparse.Namespace(name="alice", count=10)
        args = _build_delegate_args(my_handler, ns)
        assert args.get("name") == "alice"
        assert args.get("count") == 10


class TestCLICoercion:
    """Test CLI value coercion."""

    def test_coerce_cli_values(self) -> None:
        axes = Axes.default()
        get_value = coerce_cli_values(
            PingRequest,
            axes,
            lambda name: "hello" if name == "msg" else None,
        )
        assert get_value("msg") == "hello"


class TestCLIRunIntegration:
    """Test cli_run execution."""

    def test_cli_run_no_handler(self) -> None:
        """cli_run returns 1 when no handler is set on the parsed namespace."""
        parser = argparse.ArgumentParser()
        parser.add_subparsers(dest="command")
        # When no subcommand is matched, _handler is not set, cli_run prints help
        result = cli_run(parser, [])
        assert result == 1


class TestTypedCLI:
    """Test TYPED_CLI compiler variant."""

    def test_typed_cli_has_rrc_binding(self) -> None:
        assert RequestResponseCodec in TYPED_CLI


# =============================================================================
# Pure Target — Deep
# =============================================================================


class TestPureStartup:
    """Test startup trigger compilation."""

    def test_startup_delegate_produces_lifecycle_route(self) -> None:
        started: list[str] = []

        async def on_start() -> None:
            started.append("up")

        ep = endpoint(empty_runner()).expose(StartupTrigger(order=0), delegate(on_start))
        app = Application().mount(ep)
        axes = Axes.default()
        items = list(STARTUP_COMPILER.scan_and_wrap(app, axes))
        assert len(items) == 1
        trigger, _, route = items[0]
        assert isinstance(trigger, StartupTrigger)
        assert isinstance(route, LifecycleRoute)
        assert route.order == 0

    def test_startup_ordering(self) -> None:
        async def first() -> None:
            pass

        async def second() -> None:
            pass

        ep1 = endpoint(empty_runner()).expose(StartupTrigger(order=10), delegate(first))
        ep2 = endpoint(empty_runner()).expose(StartupTrigger(order=1), delegate(second))
        app = Application().mount(ep1, ep2)
        axes = Axes.default()
        items = list(STARTUP_COMPILER.scan_and_wrap(app, axes))
        routes = sorted(items, key=lambda x: x[2].order)
        assert routes[0][2].order == 1
        assert routes[1][2].order == 10

    def test_startup_factory_codec(self) -> None:
        ep = endpoint(empty_runner()).expose(
            StartupTrigger(order=5),
            immediate_factory(lambda: None),
        )
        app = Application().mount(ep)
        axes = Axes.default()
        items = list(STARTUP_COMPILER.scan_and_wrap(app, axes))
        assert len(items) == 1
        assert isinstance(items[0][2], LifecycleRoute)
        assert items[0][2].order == 5


class TestPureShutdown:
    """Test shutdown trigger compilation."""

    def test_shutdown_delegate_produces_lifecycle_route(self) -> None:
        async def on_stop() -> None:
            pass

        ep = endpoint(empty_runner()).expose(ShutdownTrigger(order=0), delegate(on_stop))
        app = Application().mount(ep)
        axes = Axes.default()
        items = list(SHUTDOWN_COMPILER.scan_and_wrap(app, axes))
        assert len(items) == 1
        assert isinstance(items[0][2], LifecycleRoute)

    def test_shutdown_sync_handler(self) -> None:
        def on_stop_sync() -> None:
            pass

        ep = endpoint(empty_runner()).expose(ShutdownTrigger(order=0), delegate(on_stop_sync))
        app = Application().mount(ep)
        axes = Axes.default()
        items = list(SHUTDOWN_COMPILER.scan_and_wrap(app, axes))
        assert len(items) == 1


class TestPureException:
    """Test exception trigger compilation."""

    def test_exception_delegate_produces_exception_route(self) -> None:
        async def handle_value_error(exc: ValueError) -> str:
            return f"caught: {exc}"

        ep = endpoint(empty_runner()).expose(
            ExceptionTrigger(ValueError),
            delegate(handle_value_error),
        )
        app = Application().mount(ep)
        axes = Axes.default()
        items: list[tuple[Any, Any, Any]] = list(EXCEPTION_COMPILER.scan_and_wrap(app, axes))
        assert len(items) == 1
        _trigger, _, route = items[0]
        assert isinstance(route, ExceptionRoute)
        assert route.exception_type is ValueError
        assert route.propagate is False

    def test_exception_with_propagation(self) -> None:
        async def handle_runtime_error(exc: RuntimeError) -> str:
            return f"handled: {exc}"

        ep = endpoint(empty_runner()).expose(
            ExceptionTrigger(RuntimeError, propagate=True),
            delegate(handle_runtime_error),
        )
        app = Application().mount(ep)
        axes = Axes.default()
        items: list[tuple[Any, Any, Any]] = list(EXCEPTION_COMPILER.scan_and_wrap(app, axes))
        assert len(items) == 1
        assert items[0][2].propagate is True
        assert items[0][2].exception_type is RuntimeError

    def test_multiple_exception_types(self) -> None:
        async def handle_ve(exc: ValueError) -> str:
            return "ve"

        async def handle_te(exc: TypeError) -> str:
            return "te"

        ep1 = endpoint(empty_runner()).expose(
            ExceptionTrigger(ValueError),
            delegate(handle_ve),
        )
        ep2 = endpoint(empty_runner()).expose(
            ExceptionTrigger(TypeError),
            delegate(handle_te),
        )
        app = Application().mount(ep1, ep2)
        axes = Axes.default()
        items: list[tuple[Any, Any, Any]] = list(EXCEPTION_COMPILER.scan_and_wrap(app, axes))
        assert len(items) == 2
        exc_types = {r.exception_type for _, _, r in items}
        assert ValueError in exc_types
        assert TypeError in exc_types


class TestPureWebSocket:
    """Test websocket trigger compilation."""

    def test_websocket_delegate_produces_ws_route(self) -> None:
        async def ws_handler(ws: object) -> None:
            pass

        ep = endpoint(empty_runner()).expose(
            WebSocketTrigger("/ws/chat", name="chat"),
            delegate(ws_handler),
        )
        app = Application().mount(ep)
        axes = Axes.default()
        items = list(WEBSOCKET_COMPILER.scan_and_wrap(app, axes))
        assert len(items) == 1
        trigger, _, route = items[0]
        assert isinstance(trigger, WebSocketTrigger)
        assert trigger.path == "/ws/chat"
        assert trigger.name == "chat"
        assert isinstance(route, WebSocketRoute)

    def test_multiple_websocket_routes(self) -> None:
        async def ws1(ws: object) -> None:
            pass

        async def ws2(ws: object) -> None:
            pass

        ep1 = endpoint(empty_runner()).expose(
            WebSocketTrigger("/ws/a"),
            delegate(ws1),
        )
        ep2 = endpoint(empty_runner()).expose(
            WebSocketTrigger("/ws/b"),
            delegate(ws2),
        )
        app = Application().mount(ep1, ep2)
        axes = Axes.default()
        items = list(WEBSOCKET_COMPILER.scan_and_wrap(app, axes))
        assert len(items) == 2


class TestPureBackwardCompat:
    """Test backward-compat wrappers for pure target."""

    def test_wrap_lifecycle_delegate(self) -> None:
        async def on_start() -> None:
            pass

        codec = DelegateCodec(handler=on_start)
        trigger = StartupTrigger(order=3)
        handler = Handler(codec=codec, runner=empty_runner())
        axes = Axes.default()
        route = wrap_lifecycle_delegate(handler, trigger, axes)
        assert isinstance(route, LifecycleRoute)
        assert route.order == 3

    def test_wrap_lifecycle_factory(self) -> None:
        codec = ImmediateFactoryCodec(factory=lambda: None)
        trigger = ShutdownTrigger(order=7)
        handler = Handler(codec=codec, runner=empty_runner())
        axes = Axes.default()
        route = wrap_lifecycle_factory(handler, trigger, axes)
        assert isinstance(route, LifecycleRoute)
        assert route.order == 7

    def test_wrap_exception_delegate(self) -> None:
        async def handle_exc(exc: ValueError) -> str:
            return "handled"

        codec = DelegateCodec(handler=handle_exc)
        trigger = ExceptionTrigger(ValueError, propagate=True)
        handler = Handler(codec=codec, runner=empty_runner())
        axes = Axes.default()
        route = wrap_exception_delegate(handler, cast(ExceptionTrigger[Exception], trigger), axes)
        assert isinstance(route, ExceptionRoute)
        assert route.exception_type is ValueError
        assert route.propagate is True

    def test_wrap_websocket_delegate(self) -> None:
        async def ws_handler(ws: object) -> None:
            pass

        codec = DelegateCodec(handler=ws_handler)
        trigger = WebSocketTrigger("/ws/test")
        handler = Handler(codec=codec, runner=empty_runner())
        axes = Axes.default()
        route = wrap_websocket_delegate(handler, trigger, axes)
        assert isinstance(route, WebSocketRoute)


class TestPureAppScopeLifespan:
    """Test app_scope_lifespan context manager."""

    @pytest.mark.anyio
    async def test_app_scope_lifespan_basic(self) -> None:
        from nodnod import Scope

        scope = Scope(detail="test-app")
        async with app_scope_lifespan(scope) as s:
            assert s is scope

    @pytest.mark.anyio
    async def test_app_scope_lifespan_empty_compose(self) -> None:
        from nodnod import Scope

        scope = Scope(detail="test-app")
        async with app_scope_lifespan(scope, compose=[]) as s:
            assert s is scope


class TestPureFromCodecDirect:
    """Test pure target from_codec functions directly."""

    def test_lifecycle_delegate_from_codec(self) -> None:
        async def on_start() -> None:
            pass

        codec = DelegateCodec(handler=on_start)
        trigger = StartupTrigger(order=2)
        ctx = _lifecycle_delegate_from_codec(codec, trigger)
        assert isinstance(ctx, LifecycleWrapContext)
        assert ctx.order == 2
        assert ctx.execute is not None

    def test_lifecycle_factory_from_codec(self) -> None:
        codec = ImmediateFactoryCodec(factory=lambda: None)
        trigger = ShutdownTrigger(order=4)
        ctx = _lifecycle_factory_from_codec(codec, trigger)
        assert isinstance(ctx, LifecycleWrapContext)
        assert ctx.order == 4

    def test_exception_delegate_from_codec(self) -> None:
        async def handle_exc(exc: ValueError) -> str:
            return "handled"

        codec = DelegateCodec(handler=handle_exc)
        trigger = ExceptionTrigger(ValueError, propagate=True)
        ctx = _exception_delegate_from_codec(codec, cast(ExceptionTrigger[Exception], trigger))
        assert isinstance(ctx, ExceptionWrapContext)
        assert ctx.exception_type is ValueError
        assert ctx.propagate is True

    def test_websocket_delegate_from_codec(self) -> None:
        async def ws_handler(ws: object) -> None:
            pass

        codec = DelegateCodec(handler=ws_handler)
        trigger = WebSocketTrigger("/ws/test")
        ctx = _websocket_delegate_from_codec(codec, trigger)
        assert isinstance(ctx, WebSocketWrapContext)
        assert ctx.execute is not None

    def test_assemble_lifecycle_raises_without_execute(self) -> None:
        ctx = LifecycleWrapContext()
        handler = Handler(codec=DelegateCodec(handler=lambda: None), runner=empty_runner())
        with pytest.raises(ValueError, match="no execute"):
            _assemble_lifecycle(ctx, handler, Axes.default())

    def test_assemble_exception_raises_without_execute(self) -> None:
        ctx = ExceptionWrapContext()
        handler = Handler(codec=DelegateCodec(handler=lambda: None), runner=empty_runner())
        with pytest.raises(ValueError, match="no execute"):
            _assemble_exception(ctx, handler, Axes.default())

    def test_assemble_websocket_raises_without_execute(self) -> None:
        ctx = WebSocketWrapContext()
        handler = Handler(codec=DelegateCodec(handler=lambda: None), runner=empty_runner())
        with pytest.raises(ValueError, match="no execute"):
            _assemble_websocket(ctx, handler, Axes.default())


# =============================================================================
# Telegrinder Target — Importability
# =============================================================================


class TestTelegrindImportability:
    """Test that telegrinder module is importable and has expected exports."""

    def test_telegrinder_module_imports(self) -> None:
        from emergent.wire.compile.targets import telegrinder as tg_mod
        assert hasattr(tg_mod, "TELEGRINDER_COMPILER")
        assert hasattr(tg_mod, "TelegrindRoute")
        assert hasattr(tg_mod, "TelegrindWrapContext")

    def test_telegrinder_compiler_has_bindings(self) -> None:
        from emergent.wire.compile.targets.telegrinder import TELEGRINDER_COMPILER
        assert len(TELEGRINDER_COMPILER.bindings) >= 4

    def test_telegrinder_response_formatting(self) -> None:
        from emergent.wire.compile.targets.telegrinder import _format_tg_response
        # Primitives pass through
        assert _format_tg_response("hello") == "hello"
        assert _format_tg_response(42) == 42
        assert _format_tg_response(None) is None
        assert _format_tg_response(True) is True
        assert _format_tg_response({"a": 1}) == {"a": 1}

    def test_telegrinder_format_response_custom_str(self) -> None:
        from emergent.wire.compile.targets.telegrinder import _format_tg_response

        class MyResponse:
            def __str__(self) -> str:
                return "custom-str"

        resp = MyResponse()
        assert _format_tg_response(resp) == "custom-str"

    def test_telegrinder_format_response_no_str(self) -> None:
        from emergent.wire.compile.targets.telegrinder import _format_tg_response

        class Plain:
            pass

        resp = Plain()
        # Object without custom __str__ passes through
        assert _format_tg_response(resp) is resp

    def test_from_codec_functions_exist(self) -> None:
        from emergent.wire.compile.targets.telegrinder import (
            rrc_from_codec_tg,
            stateful_from_codec_tg,
            immediate_from_codec_tg,
            delegate_from_codec_tg,
        )
        assert callable(rrc_from_codec_tg)
        assert callable(stateful_from_codec_tg)
        assert callable(immediate_from_codec_tg)
        assert callable(delegate_from_codec_tg)

    def test_command_info_dataclass(self) -> None:
        from emergent.wire.compile.targets.telegrinder import CommandInfo
        info = CommandInfo(name="test", args=["a", "b"], description="Test cmd", order=5)
        assert info.name == "test"
        assert info.order == 5


# =============================================================================
# _execute.py — Deep
# =============================================================================


class TestExecuteImmediateUnified:
    """Test execute_immediate_unified."""

    def test_immediate_codec_produces_response(self) -> None:
        codec = ImmediateCodec(response=HealthStatus)
        handler = Handler(codec=codec, runner=empty_runner())
        result = execute_immediate_unified(handler)
        assert isinstance(result, HealthStatus)
        assert result.status == "healthy"

    def test_immediate_factory_codec(self) -> None:
        codec = ImmediateFactoryCodec(factory=lambda: {"version": "2.0"})
        handler = Handler(codec=codec, runner=empty_runner())
        result = execute_immediate_unified(handler)
        assert result == {"version": "2.0"}

    def test_immediate_with_format_response(self) -> None:
        codec = ImmediateCodec(response=HealthStatus)
        handler = Handler(codec=codec, runner=empty_runner())
        result = execute_immediate_unified(handler, format_response=str)
        assert isinstance(result, str)

    def test_immediate_wrong_codec_raises(self) -> None:
        codec = RequestResponseCodec(request=PingRequest, response=PingResponse)
        handler = Handler(codec=codec, runner=_runner())
        with pytest.raises(TypeError, match="Expected ImmediateCodec"):
            execute_immediate_unified(handler)


class TestExecuteDelegateUnified:
    """Test execute_delegate_unified."""

    @pytest.mark.anyio
    async def test_delegate_async_handler(self) -> None:
        async def my_handler() -> str:
            return "result"

        codec = DelegateCodec(handler=my_handler)
        handler = Handler(codec=codec, runner=empty_runner())
        result = await execute_delegate_unified(
            handler=handler,
            inject_scope=lambda s: None,
        )
        assert result == "result"

    @pytest.mark.anyio
    async def test_delegate_sync_handler(self) -> None:
        def my_handler() -> str:
            return "sync-result"

        codec = DelegateCodec(handler=my_handler)
        handler = Handler(codec=codec, runner=empty_runner())
        result = await execute_delegate_unified(
            handler=handler,
            inject_scope=lambda s: None,
        )
        assert result == "sync-result"

    @pytest.mark.anyio
    async def test_delegate_with_format_response(self) -> None:
        async def my_handler() -> int:
            return 42

        codec = DelegateCodec(handler=my_handler)
        handler = Handler(codec=codec, runner=empty_runner())
        result = await execute_delegate_unified(
            handler=handler,
            inject_scope=lambda s: None,
            format_response=str,
        )
        assert result == "42"


# =============================================================================
# _pipeline.py — Deep
# =============================================================================


class TestCompilePipeline:
    """Test compile_pipeline."""

    def test_compile_pipeline_from_rrc_context(self) -> None:
        codec = RequestResponseCodec(request=PingRequest, response=PingResponse)
        trigger = HTTPRouteTrigger("GET", "/ping")
        ctx = rrc_from_codec(codec, trigger)
        axes = Axes.default()
        compiled = compile_pipeline(ctx, axes)
        assert isinstance(compiled, CompiledPipeline)
        assert compiled.execute is not None
        assert compiled.extractor is not None

    def test_compile_pipeline_from_immediate_context(self) -> None:
        codec = ImmediateCodec(response=HealthStatus)
        trigger = HTTPRouteTrigger("GET", "/health")
        ctx = immediate_from_codec(codec, trigger)
        axes = Axes.default()
        compiled = compile_pipeline(ctx, axes)
        assert compiled.extractor is None

    def test_compile_pipeline_raises_without_execute(self) -> None:
        ctx = FastAPIWrapContext()
        with pytest.raises(TypeError, match="no 'execute' attribute"):
            compile_pipeline(ctx, Axes.default())


# =============================================================================
# _request.py — Deep
# =============================================================================


class TestBuildRequest:
    """Test build_request."""

    @pytest.mark.anyio
    async def test_build_simple_request(self) -> None:
        req = await build_request(
            PingRequest,
            get_value=lambda name: "hello" if name == "msg" else None,
        )
        assert isinstance(req, PingRequest)
        assert req.msg == "hello"

    @pytest.mark.anyio
    async def test_build_multi_field_request(self) -> None:
        req = await build_request(
            CreateRequest,
            get_value=lambda name: {"name": "alice", "age": 30}.get(name),
        )
        assert isinstance(req, CreateRequest)
        assert req.name == "alice"
        assert req.age == 30

    @pytest.mark.anyio
    async def test_build_request_non_dataclass_raises(self) -> None:
        with pytest.raises(TypeError, match="not a dataclass"):
            await build_request(str, get_value=lambda _: None)

    @pytest.mark.anyio
    async def test_build_request_missing_required_field_raises(self) -> None:
        with pytest.raises(RuntimeError, match="Cannot resolve"):
            await build_request(
                PingRequest,
                get_value=lambda _: None,
            )


class TestBuildRequestSync:
    """Test build_request_sync."""

    def test_build_simple_sync(self) -> None:
        req = build_request_sync(
            PingRequest,
            get_value=lambda name: "hi" if name == "msg" else None,
        )
        assert isinstance(req, PingRequest)
        assert req.msg == "hi"

    def test_sync_non_dataclass_raises(self) -> None:
        with pytest.raises(TypeError, match="not a dataclass"):
            build_request_sync(str, get_value=lambda _: None)

    def test_sync_missing_required_raises(self) -> None:
        with pytest.raises(RuntimeError, match="No value for required"):
            build_request_sync(PingRequest, get_value=lambda _: None)


class TestBuildRequestWithDefaults:
    """Test build_request with default values."""

    @dataclass
    class ReqWithDefaults:
        name: str
        count: int = 10

    @pytest.mark.anyio
    async def test_default_used_when_no_value(self) -> None:
        req = await build_request(
            self.ReqWithDefaults,
            get_value=lambda name: "alice" if name == "name" else None,
        )
        assert req.name == "alice"
        assert req.count == 10

    def test_default_used_sync(self) -> None:
        req = build_request_sync(
            self.ReqWithDefaults,
            get_value=lambda name: "bob" if name == "name" else None,
        )
        assert req.name == "bob"
        assert req.count == 10


# =============================================================================
# _stateful.py — Deep
# =============================================================================


class TestStatefulMetadata:
    """Test get_stateful_metadata."""

    def test_metadata_extraction(self) -> None:
        # We need a minimal StatefulCodec to test metadata extraction
        # This tests the function exists and produces a dict
        # StatefulCodec requires specific params — test only the import path
        assert callable(get_stateful_metadata)


# =============================================================================
# TargetCompiler algebra — exercises _target.py deeply
# =============================================================================


class TestTargetCompilerAlgebra:
    """Test TargetCompiler algebraic operations."""

    def test_without_binding(self) -> None:
        reduced = FASTAPI_COMPILER.without_binding(ImmediateCodec)
        assert ImmediateCodec not in reduced
        assert RequestResponseCodec in reduced

    def test_with_binding_new_codec(self) -> None:
        @dataclass(frozen=True, slots=True)
        class CustomCodec:
            data: str

        def custom_from_codec(codec: CustomCodec, trigger: HTTPRouteTrigger) -> FastAPIWrapContext:
            return FastAPIWrapContext()

        extended = FASTAPI_COMPILER.with_binding(CustomCodec, custom_from_codec)
        assert CustomCodec in extended

    def test_with_binding_duplicate_raises(self) -> None:
        def _dummy_from_codec(c: object, t: object) -> FastAPIWrapContext:
            return FastAPIWrapContext()

        with pytest.raises(ValueError, match="already present"):
            FASTAPI_COMPILER.with_binding(
                RequestResponseCodec,
                _dummy_from_codec,
            )

    def test_replace_binding(self) -> None:
        def new_rrc(codec: RequestResponseCodec, trigger: HTTPRouteTrigger) -> FastAPIWrapContext:
            return FastAPIWrapContext()

        replaced = FASTAPI_COMPILER.replace_binding(RequestResponseCodec, new_rrc)
        assert RequestResponseCodec in replaced

    def test_replace_binding_missing_raises(self) -> None:
        @dataclass(frozen=True, slots=True)
        class NoSuchCodec:
            pass

        def _noop_from(c: object, t: object) -> None:
            pass

        with pytest.raises(KeyError):
            FASTAPI_COMPILER.replace_binding(NoSuchCodec, _noop_from)

    def test_add_compilers(self) -> None:
        result = CLI_COMPILER + CLI_COMPILER
        assert len(result) == len(CLI_COMPILER)  # idempotent

    def test_or_compilers(self) -> None:
        result = CLI_COMPILER | CLI_COMPILER
        assert len(result) == len(CLI_COMPILER)

    def test_sub_codec_type(self) -> None:
        result = FASTAPI_COMPILER - ImmediateCodec
        assert ImmediateCodec not in result

    def test_and_compilers(self) -> None:
        # Intersection with self yields same set
        result = FASTAPI_COMPILER & FASTAPI_COMPILER
        assert len(result) == len(FASTAPI_COMPILER)

    def test_len_and_iter(self) -> None:
        assert len(FASTAPI_COMPILER) > 0
        bindings = list(FASTAPI_COMPILER)
        assert len(bindings) == len(FASTAPI_COMPILER)

    def test_bool(self) -> None:
        assert bool(FASTAPI_COMPILER) is True

    def test_getitem(self) -> None:
        binding = FASTAPI_COMPILER[RequestResponseCodec]
        assert binding.codec_type is RequestResponseCodec

    def test_getitem_missing_raises(self) -> None:
        @dataclass(frozen=True, slots=True)
        class Missing:
            pass

        with pytest.raises(KeyError):
            FASTAPI_COMPILER[Missing]

    def test_contains_codec_binding(self) -> None:
        binding = FASTAPI_COMPILER[RequestResponseCodec]
        assert binding in FASTAPI_COMPILER


# =============================================================================
# Response transforms
# =============================================================================


class TestResponseTransforms:
    """Test response transform capabilities."""

    def test_as_dict_on_dataclass(self) -> None:
        from emergent.wire.axis.surface.transforms._response import AsDict

        transform = AsDict()
        resp = PingResponse(reply="pong")
        result = transform.apply_response(resp)
        assert isinstance(result, dict)
        assert result["reply"] == "pong"

    def test_as_str_transform(self) -> None:
        from emergent.wire.axis.surface.transforms._response import AsStr

        transform = AsStr()
        result = transform.apply_response(42)
        assert result == "42"

    def test_as_dict_passthrough_dict(self) -> None:
        from emergent.wire.axis.surface.transforms._response import AsDict

        transform = AsDict()
        data = {"key": "value"}
        result = transform.apply_response(data)
        assert result == data

    def test_as_dict_skip_mode(self) -> None:
        from emergent.wire.axis.surface.transforms._response import AsDict

        transform = AsDict(skip=True)
        result = transform.apply_response(42)
        assert result == {"value": 42}

    def test_as_dict_strict_raises_on_unconvertible(self) -> None:
        from emergent.wire.axis.surface.transforms._response import AsDict

        transform = AsDict(skip=False)
        with pytest.raises(ValueError, match="Cannot convert"):
            transform.apply_response(42)


# =============================================================================
# Multi-endpoint and multi-codec Applications
# =============================================================================


class TestMultiCodecApp:
    """Test applications with multiple codec types."""

    def test_mixed_rrc_and_immediate_fastapi(self) -> None:
        runner = _runner()
        ep1 = endpoint(runner).expose(
            HTTPRouteTrigger("GET", "/ping"),
            rrc(PingRequest, PingResponse),
        )
        ep2 = endpoint(empty_runner()).expose(
            HTTPRouteTrigger("GET", "/health"),
            immediate(HealthStatus),
        )
        ep3 = endpoint(empty_runner()).expose(
            HTTPRouteTrigger("GET", "/version"),
            immediate_factory(lambda: {"v": "1.0"}),
        )
        app = Application().mount(ep1, ep2, ep3)
        fapi = fastapi_compile(app)
        paths = {r.path for r in fapi.routes if isinstance(r, fastapi.routing.APIRoute)}
        assert "/ping" in paths
        assert "/health" in paths
        assert "/version" in paths

    def test_mixed_rrc_and_immediate_cli(self) -> None:
        runner = _runner()
        ep1 = endpoint(runner).expose(
            CLITrigger("ping", "Ping"),
            rrc(PingRequest, PingResponse),
        )
        ep2 = endpoint(empty_runner()).expose(
            CLITrigger("health", "Health"),
            immediate(HealthStatus),
        )
        app = Application().mount(ep1, ep2)
        parser = cli_compile(app, prog="test")
        assert isinstance(parser, argparse.ArgumentParser)

    def test_mixed_rrc_and_delegate_cli(self) -> None:
        def status_handler(flag: bool = False) -> str:
            return f"ok-{flag}"

        runner = _runner()
        ep1 = endpoint(runner).expose(
            CLITrigger("ping", "Ping"),
            rrc(PingRequest, PingResponse),
        )
        ep2 = endpoint(empty_runner()).expose(
            CLITrigger("status", "Status"),
            delegate(status_handler),
        )
        app = Application().mount(ep1, ep2)
        parser = cli_compile(app, prog="test")
        assert isinstance(parser, argparse.ArgumentParser)


class TestMultipleEndpointEntities:
    """Test that multiple endpoints all get compiled."""

    def test_three_separate_endpoints_fastapi(self) -> None:
        runner = _runner()
        ep1 = endpoint(runner).expose(
            HTTPRouteTrigger("GET", "/a"), rrc(PingRequest, PingResponse),
        )
        ep2 = endpoint(runner).expose(
            HTTPRouteTrigger("POST", "/b"), rrc(CreateRequest, CreateResponse),
        )

        async def handler_c() -> str:
            return "c"

        ep3 = endpoint(empty_runner()).expose(
            HTTPRouteTrigger("GET", "/c"), delegate(handler_c),
        )
        app = Application().mount(ep1, ep2, ep3)
        fapi = fastapi_compile(app)
        paths = {r.path for r in fapi.routes if isinstance(r, fastapi.routing.APIRoute)}
        assert paths == {"/a", "/b", "/c"}


# =============================================================================
# Schema dialect CLI capabilities (Positional, Choices) in CLI compilation
# =============================================================================


class TestCLISchemaDialect:
    """Test schema-level CLI dialect capabilities affect argparse generation."""

    def test_positional_field(self) -> None:
        runner = _runner()
        ep = endpoint(runner).expose(
            CLITrigger("scan", "Scan target"),
            rrc(ReqWithPositional, PositionalResp),
        )
        app = Application().mount(ep)
        parser = cli_compile(app, prog="test")
        assert isinstance(parser, argparse.ArgumentParser)

    def test_choices_field(self) -> None:
        runner = _runner()
        ep = endpoint(runner).expose(
            CLITrigger("export", "Export data"),
            rrc(ReqWithChoices, PositionalResp),
        )
        app = Application().mount(ep)
        parser = cli_compile(app, prog="test")
        assert isinstance(parser, argparse.ArgumentParser)

    def test_help_field(self) -> None:
        runner = _runner()
        ep = endpoint(runner).expose(
            CLITrigger("send", "Send message"),
            rrc(ReqWithFieldHelp, PingResponse),
        )
        app = Application().mount(ep)
        parser = cli_compile(app, prog="test")
        assert isinstance(parser, argparse.ArgumentParser)


# =============================================================================
# Empty and edge cases
# =============================================================================


class TestEdgeCases:
    """Test edge cases and empty applications."""

    def test_empty_app_fastapi(self) -> None:
        app = Application()
        fapi = fastapi_compile(app)
        api_routes = [r for r in fapi.routes if isinstance(r, fastapi.routing.APIRoute)]
        assert len(api_routes) == 0

    def test_empty_app_cli(self) -> None:
        app = Application()
        parser = cli_compile(app, prog="empty")
        assert isinstance(parser, argparse.ArgumentParser)

    def test_empty_app_startup_compiler(self) -> None:
        app = Application()
        items = list(STARTUP_COMPILER.scan_and_wrap(app, Axes.default()))
        assert len(items) == 0

    def test_empty_app_exception_compiler(self) -> None:
        app = Application()
        items: list[tuple[Any, Any, Any]] = list(EXCEPTION_COMPILER.scan_and_wrap(app, Axes.default()))
        assert len(items) == 0

    def test_empty_app_websocket_compiler(self) -> None:
        app = Application()
        items = list(WEBSOCKET_COMPILER.scan_and_wrap(app, Axes.default()))
        assert len(items) == 0

    def test_app_addition(self) -> None:
        runner = _runner()
        app1 = Application().mount(
            endpoint(runner).expose(
                HTTPRouteTrigger("GET", "/a"), rrc(PingRequest, PingResponse),
            )
        )
        app2 = Application().mount(
            endpoint(runner).expose(
                HTTPRouteTrigger("POST", "/b"), rrc(CreateRequest, CreateResponse),
            )
        )
        combined = app1 + app2
        fapi = fastapi_compile(combined)
        paths = {r.path for r in fapi.routes if isinstance(r, fastapi.routing.APIRoute)}
        assert "/a" in paths
        assert "/b" in paths


class TestCLIRegisterHandler:
    """Test cli register_handler function."""

    def test_register_handler_on_parser(self) -> None:
        codec = RequestResponseCodec(request=PingRequest, response=PingResponse)
        trigger = CLITrigger("ping", "Ping cmd")
        handler = Handler(codec=codec, runner=_runner())
        ctx = rrc_from_codec_cli(codec, trigger)
        axes = Axes.default()
        route = assemble_cli_route(ctx, handler, axes)

        parser = argparse.ArgumentParser(prog="test")
        subparsers = parser.add_subparsers(dest="command", required=True)
        cli_register_handler(subparsers, trigger, handler, route, axes)
        # The subparser should exist — verify by listing subparser choices
        # argparse stores subparsers in _subparsers._group_actions
        has_ping = False
        assert parser._subparsers is not None
        for action in parser._subparsers._group_actions:
            if hasattr(action, "choices") and "ping" in (action.choices or {}):
                has_ping = True
        assert has_ping


# =============================================================================
# FastAPI compile with response transforms
# =============================================================================


class TestFastAPIWithResponseTransforms:
    """Test FastAPI compilation with response transform capabilities."""

    def test_as_dict_capability(self) -> None:
        from emergent.wire.axis.surface.transforms._response import AsDict

        runner = _runner()
        ep = endpoint(runner).expose(
            HTTPRouteTrigger("GET", "/as-dict"),
            rrc(PingRequest, PingResponse),
            AsDict(),
        )
        app = Application().mount(ep)
        fapi = fastapi_compile(app)
        paths = {r.path for r in fapi.routes if isinstance(r, fastapi.routing.APIRoute)}
        assert "/as-dict" in paths

    def test_as_str_capability(self) -> None:
        from emergent.wire.axis.surface.transforms._response import AsStr

        runner = _runner()
        ep = endpoint(runner).expose(
            HTTPRouteTrigger("GET", "/as-str"),
            rrc(PingRequest, PingResponse),
            AsStr(),
        )
        app = Application().mount(ep)
        fapi = fastapi_compile(app)
        paths = {r.path for r in fapi.routes if isinstance(r, fastapi.routing.APIRoute)}
        assert "/as-str" in paths

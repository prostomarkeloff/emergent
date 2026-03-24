# pyright: reportPrivateUsage=false
"""Tests for compile targets — FastAPI, CLI, Pure, Testing, Event.

Uses emergent's OWN compilation pipeline to build fixtures.
Tests structural properties of each compiled target output.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Any, Self

import fastapi
import pytest
from kungfu import Ok, Result

from emergent.ops._graph import Op, ops
from emergent.wire.axis.surface._app import Application
from emergent.wire.axis.surface._endpoint import endpoint
from emergent.wire.axis.surface import empty_runner
from emergent.wire.axis.surface.codecs.rrc import RequestResponseCodec, rrc
from emergent.wire.axis.surface.codecs.immediate import (
    ImmediateCodec,
    immediate,
    immediate_factory,
)
from emergent.wire.axis.surface.codecs.delegate import delegate, DelegateCodec
from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger
from emergent.wire.axis.surface.triggers.cli import CLITrigger
from emergent.wire.axis.surface.triggers.event import EventTrigger
from emergent.wire.axis.surface.triggers.lifecycle import StartupTrigger, ShutdownTrigger
from emergent.wire.axis.surface.triggers.exception import ExceptionTrigger
from emergent.wire.axis.surface.triggers.websocket import WebSocketTrigger
from emergent.wire.compile._core import Axes
from emergent.wire.compile.targets.fastapi import (
    fastapi_compile,
    FASTAPI_COMPILER,
)
from emergent.wire.compile.targets.cli import (
    cli_compile,
    CLI_COMPILER,
)
from emergent.wire.compile.targets.testing import (
    testing_compile as compile_for_testing,
    TESTING_COMPILER,
    TestApp as WireTestApp,
    TestRoute as WireTestRoute,
)
from emergent.wire.compile.targets.event import (
    event_compile,
    EVENT_COMPILER,
    EventDispatcher,
    EventRoute,
)
from emergent.wire.compile.targets.pure import (
    STARTUP_COMPILER,
    SHUTDOWN_COMPILER,
    EXCEPTION_COMPILER,
    WEBSOCKET_COMPILER,
    LifecycleRoute,
    ExceptionRoute,
    WebSocketRoute,
)


# =============================================================================
# Helpers
# =============================================================================


def _get_subparsers_actions(parser: argparse.ArgumentParser) -> list[argparse._SubParsersAction[argparse.ArgumentParser]]:
    """Extract SubParsersAction from parser, safely narrowing Optional."""
    assert parser._subparsers is not None
    return [
        action for action in parser._subparsers._actions
        if isinstance(action, argparse._SubParsersAction)
    ]


def _get_choices(parser: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser]:
    """Get the choices dict from the first SubParsersAction."""
    actions = _get_subparsers_actions(parser)
    assert len(actions) >= 1
    return actions[0].choices


# =============================================================================
# Domain types
# =============================================================================


@dataclass
class GetUserOp(Op[dict[str, object], str]):
    user_id: int


async def _get_user_handler(req: GetUserOp) -> Result[dict[str, object], str]:
    result: dict[str, object] = {"id": req.user_id, "name": "Alice"}
    return Ok(result)


@dataclass
class CreateUserOp(Op[dict[str, object], str]):
    name: str
    age: int


async def _create_user_handler(req: CreateUserOp) -> Result[dict[str, object], str]:
    result: dict[str, object] = {"name": req.name, "age": req.age}
    return Ok(result)


@dataclass
class GetUserRequest:
    user_id: int

    def to_domain(self) -> GetUserOp:
        return GetUserOp(user_id=self.user_id)


@dataclass
class GetUserResponse:
    user_id: int
    name: str

    @classmethod
    def from_domain(cls, dom: Result[dict[str, object], str]) -> Self:
        match dom:
            case Ok(v):
                return cls(user_id=int(v["id"]), name=str(v["name"]))  # type: ignore[arg-type]
            case _:
                return cls(user_id=-1, name="error")


@dataclass
class CreateUserRequest:
    name: str
    age: int

    def to_domain(self) -> CreateUserOp:
        return CreateUserOp(name=self.name, age=self.age)


@dataclass
class CreateUserResponse:
    name: str
    age: int

    @classmethod
    def from_domain(cls, dom: Result[dict[str, object], str]) -> Self:
        match dom:
            case Ok(v):
                return cls(name=str(v["name"]), age=int(v["age"]))  # type: ignore[arg-type]
            case _:
                return cls(name="error", age=-1)


@dataclass
class ImmediateHealth:
    status: str

    @classmethod
    def produce(cls) -> Self:
        return cls(status="ok")


@dataclass
class OrderCreated:
    order_id: int
    total: float


@dataclass
class OrderCancelled:
    order_id: int
    reason: str


# --- Extra entity for multi-type tests ---


@dataclass
class TypeTestOp(Op[str, str]):
    flag: bool
    count: int
    label: str


async def _type_test_handler(req: TypeTestOp) -> Result[str, str]:
    return Ok(f"{req.flag}-{req.count}-{req.label}")


@dataclass
class TypeTestReq:
    flag: bool
    count: int
    label: str

    def to_domain(self) -> TypeTestOp:
        return TypeTestOp(flag=self.flag, count=self.count, label=self.label)


@dataclass
class TypeTestResp:
    value: str

    @classmethod
    def from_domain(cls, dom: Result[str, str]) -> Self:
        match dom:
            case Ok(v):
                return cls(value=v)
            case _:
                return cls(value="err")


@dataclass
class HandleOrderOp(Op[str, str]):
    order_id: int
    total: float


async def _handle_order(req: HandleOrderOp) -> Result[str, str]:
    return Ok(f"processed-{req.order_id}")


@dataclass
class OrderEventRequest:
    order_id: int
    total: float

    def to_domain(self) -> HandleOrderOp:
        return HandleOrderOp(order_id=self.order_id, total=self.total)


@dataclass
class OrderEventResponse:
    result: str

    @classmethod
    def from_domain(cls, dom: Result[str, str]) -> Self:
        match dom:
            case Ok(v):
                return cls(result=v)
            case _:
                return cls(result="error")


# =============================================================================
# Runners
# =============================================================================


def _user_runner():
    return ops().on(GetUserOp, _get_user_handler).on(CreateUserOp, _create_user_handler).compile()


def _order_runner():
    return ops().on(HandleOrderOp, _handle_order).compile()


# =============================================================================
# Application builders
# =============================================================================


def _http_app() -> Application:
    """Application with HTTP triggers — for FastAPI."""
    runner = _user_runner()
    ep = (
        endpoint(runner)
        .expose(HTTPRouteTrigger("GET", "/users/{user_id}"), rrc(GetUserRequest, GetUserResponse))
        .expose(HTTPRouteTrigger("POST", "/users"), rrc(CreateUserRequest, CreateUserResponse))
    )
    return Application().mount(ep)


def _http_app_with_immediate() -> Application:
    """HTTP app with immediate health endpoint."""
    runner = _user_runner()
    ep = (
        endpoint(runner)
        .expose(HTTPRouteTrigger("GET", "/users/{user_id}"), rrc(GetUserRequest, GetUserResponse))
    )
    health_ep = endpoint(empty_runner()).expose(
        HTTPRouteTrigger("GET", "/health"),
        immediate(ImmediateHealth),
    )
    return Application().mount(ep, health_ep)


def _cli_app() -> Application:
    """Application with CLI triggers."""
    runner = _user_runner()
    ep = (
        endpoint(runner)
        .expose(CLITrigger("get-user", "Get a user by ID"), rrc(GetUserRequest, GetUserResponse))
        .expose(CLITrigger("create-user", "Create a new user"), rrc(CreateUserRequest, CreateUserResponse))
    )
    return Application().mount(ep)


def _mixed_trigger_app() -> Application:
    """Application with both HTTP and CLI triggers on same runner."""
    runner = _user_runner()
    ep = (
        endpoint(runner)
        .expose(HTTPRouteTrigger("GET", "/users/{user_id}"), rrc(GetUserRequest, GetUserResponse))
        .expose(CLITrigger("get-user", "Get a user"), rrc(GetUserRequest, GetUserResponse))
    )
    return Application().mount(ep)


def _event_app() -> Application:
    """Application with event triggers."""
    runner = _order_runner()
    ep = endpoint(runner).expose(
        EventTrigger(OrderCreated),
        rrc(OrderEventRequest, OrderEventResponse),
    )
    return Application().mount(ep)


def _delegate_app_http() -> Application:
    """HTTP app with delegate codec."""
    async def handle_status() -> dict[str, str]:
        return {"status": "running"}

    ep = endpoint(empty_runner()).expose(
        HTTPRouteTrigger("GET", "/status"),
        delegate(handle_status),
    )
    return Application().mount(ep)


def _lifecycle_app() -> Application:
    """Application with startup/shutdown triggers."""
    started: list[str] = []
    stopped: list[str] = []

    async def on_start() -> None:
        started.append("started")

    async def on_stop() -> None:
        stopped.append("stopped")

    ep_start = endpoint(empty_runner()).expose(StartupTrigger(order=0), delegate(on_start))
    ep_stop = endpoint(empty_runner()).expose(ShutdownTrigger(order=0), delegate(on_stop))
    return Application().mount(ep_start, ep_stop)


def _exception_app() -> Application:
    """Application with exception handler."""
    async def handle_value_error(exc: ValueError) -> str:
        return f"caught: {exc}"

    ep = endpoint(empty_runner()).expose(
        ExceptionTrigger(ValueError),
        delegate(handle_value_error),
    )
    return Application().mount(ep)


def _websocket_app() -> Application:
    """Application with websocket handler."""
    async def ws_handler(websocket: object) -> None:
        pass

    ep = endpoint(empty_runner()).expose(
        WebSocketTrigger("/ws/chat", name="chat"),
        delegate(ws_handler),
    )
    return Application().mount(ep)


def _multi_event_app() -> Application:
    """Application with multiple event types."""
    runner = _order_runner()
    ep1 = endpoint(runner).expose(
        EventTrigger(OrderCreated),
        rrc(OrderEventRequest, OrderEventResponse),
    )

    async def handle_cancel(evt: OrderCancelled) -> str:
        return f"cancelled-{evt.order_id}"

    ep2 = endpoint(empty_runner()).expose(
        EventTrigger(OrderCancelled),
        delegate(handle_cancel),
    )
    return Application().mount(ep1, ep2)


# =============================================================================
# 1. FastAPI Target
# =============================================================================


class TestFastapiCompilation:
    """FastAPI compilation produces a FastAPI app with routes."""

    def test_compile_produces_fastapi_app(self) -> None:
        app = _http_app()
        fapi = fastapi_compile(app)
        assert isinstance(fapi, fastapi.FastAPI)

    def test_routes_registered_for_rrc_endpoints(self) -> None:
        app = _http_app()
        fapi = fastapi_compile(app)
        paths = [r.path for r in fapi.routes if isinstance(r, fastapi.routing.APIRoute)]
        assert "/users/{user_id}" in paths
        assert "/users" in paths

    def test_methods_match_triggers(self) -> None:
        app = _http_app()
        fapi = fastapi_compile(app)
        route_map: dict[str, set[str]] = {}
        for r in fapi.routes:
            if isinstance(r, fastapi.routing.APIRoute):
                route_map[r.path] = r.methods or set()
        assert "GET" in route_map.get("/users/{user_id}", set())
        assert "POST" in route_map.get("/users", set())

    def test_immediate_codec_produces_route(self) -> None:
        app = _http_app_with_immediate()
        fapi = fastapi_compile(app)
        paths = [r.path for r in fapi.routes if isinstance(r, fastapi.routing.APIRoute)]
        assert "/health" in paths

    def test_delegate_codec_produces_route(self) -> None:
        app = _delegate_app_http()
        fapi = fastapi_compile(app)
        paths = [r.path for r in fapi.routes if isinstance(r, fastapi.routing.APIRoute)]
        assert "/status" in paths

    def test_empty_app_produces_empty_fastapi(self) -> None:
        app = Application()
        fapi = fastapi_compile(app)
        api_routes = [r for r in fapi.routes if isinstance(r, fastapi.routing.APIRoute)]
        assert len(api_routes) == 0

    def test_only_http_triggers_are_included(self) -> None:
        """CLI triggers on same app are ignored by FastAPI compiler."""
        app = _mixed_trigger_app()
        fapi = fastapi_compile(app)
        api_routes = [r for r in fapi.routes if isinstance(r, fastapi.routing.APIRoute)]
        # Only the HTTP trigger should appear
        assert len(api_routes) == 1
        assert api_routes[0].path == "/users/{user_id}"

    def test_websocket_triggers_found_by_ws_compiler(self) -> None:
        """WebSocket triggers are found by the WEBSOCKET_COMPILER (pure target)."""
        app = _websocket_app()
        axes = Axes.default()
        items = list(WEBSOCKET_COMPILER.scan_and_wrap(app, axes))
        assert len(items) == 1
        trigger, _handler, route = items[0]
        assert isinstance(trigger, WebSocketTrigger)
        assert trigger.path == "/ws/chat"
        assert isinstance(route, WebSocketRoute)


class TestFastapiCompilationMultipleEndpoints:
    """FastAPI compilation with multiple endpoints."""

    def test_multiple_endpoints_all_routes_present(self) -> None:
        runner = _user_runner()
        ep1 = endpoint(runner).expose(
            HTTPRouteTrigger("GET", "/users/{user_id}"),
            rrc(GetUserRequest, GetUserResponse),
        )
        ep2 = endpoint(runner).expose(
            HTTPRouteTrigger("POST", "/users"),
            rrc(CreateUserRequest, CreateUserResponse),
        )
        app = Application().mount(ep1, ep2)
        fapi = fastapi_compile(app)
        paths = {r.path for r in fapi.routes if isinstance(r, fastapi.routing.APIRoute)}
        assert "/users/{user_id}" in paths
        assert "/users" in paths

    def test_combined_apps_have_all_routes(self) -> None:
        app1 = _http_app()
        app2 = _delegate_app_http()
        combined = app1 + app2
        fapi = fastapi_compile(combined)
        paths = {r.path for r in fapi.routes if isinstance(r, fastapi.routing.APIRoute)}
        assert "/users/{user_id}" in paths
        assert "/users" in paths
        assert "/status" in paths


# =============================================================================
# 2. CLI Target
# =============================================================================


class TestCliCompilation:
    """CLI compilation produces argparse parser with subcommands."""

    def test_compile_produces_argument_parser(self) -> None:
        app = _cli_app()
        parser = cli_compile(app, prog="test-cli")
        assert isinstance(parser, argparse.ArgumentParser)

    def test_subcommands_match_triggers(self) -> None:
        app = _cli_app()
        parser = cli_compile(app, prog="test-cli")
        # Parse with known subcommands to check they exist
        # argparse stores subparsers info
        spa = _get_subparsers_actions(parser)
        assert len(spa) == 1
        choices = spa[0].choices
        assert "get-user" in choices
        assert "create-user" in choices

    def test_prog_name_is_set(self) -> None:
        app = _cli_app()
        parser = cli_compile(app, prog="my-tool")
        assert parser.prog == "my-tool"

    def test_only_cli_triggers_are_included(self) -> None:
        """HTTP triggers on same app are ignored by CLI compiler."""
        app = _mixed_trigger_app()
        parser = cli_compile(app, prog="test")
        spa = _get_subparsers_actions(parser)
        assert len(spa) == 1
        choices = spa[0].choices
        assert "get-user" in choices
        # HTTP trigger should NOT be in choices
        assert "/users/{user_id}" not in choices

    def test_empty_app_produces_parser_with_no_commands(self) -> None:
        app = Application()
        parser = cli_compile(app, prog="test")
        spa = _get_subparsers_actions(parser)
        # Subparsers action exists but with no choices
        if spa:
            assert len(spa[0].choices) == 0

    def test_rrc_request_fields_become_arguments(self) -> None:
        """Fields from the RRC request type appear as CLI arguments."""
        app = _cli_app()
        parser = cli_compile(app, prog="test")
        choices = _get_choices(parser)
        get_user_parser = choices["get-user"]
        # get_user_parser should have an argument for user_id
        arg_dests = {a.dest for a in get_user_parser._actions if a.dest != "help" and a.dest != "_handler"}
        assert "user_id" in arg_dests

    def test_create_user_fields_become_arguments(self) -> None:
        """CreateUser request fields (name, age) appear as CLI arguments."""
        app = _cli_app()
        parser = cli_compile(app, prog="test")
        choices = _get_choices(parser)
        create_parser = choices["create-user"]
        arg_dests = {a.dest for a in create_parser._actions if a.dest != "help" and a.dest != "_handler"}
        assert "name" in arg_dests
        assert "age" in arg_dests


class TestCliCompilationDelegate:
    """CLI compilation with delegate codec."""

    def test_delegate_appears_as_subcommand(self) -> None:
        async def my_handler(name: str) -> str:
            return f"hello {name}"

        ep = endpoint(empty_runner()).expose(
            CLITrigger("greet", "Greet someone"),
            delegate(my_handler),
        )
        app = Application().mount(ep)
        parser = cli_compile(app, prog="test")
        choices = _get_choices(parser)
        assert "greet" in choices


# =============================================================================
# 3. Testing Target
# =============================================================================


class TestTestingCompilation:
    """Testing compilation produces TestApp with callable routes."""

    def test_compile_produces_test_app(self) -> None:
        app = _http_app()
        test_app = compile_for_testing(app)
        assert isinstance(test_app, WireTestApp)

    def test_routes_count_matches_exposures(self) -> None:
        app = _http_app()
        test_app = compile_for_testing(app)
        # Two exposures: GET /users/{user_id} and POST /users
        assert len(test_app.routes) == 2

    def test_routes_are_test_route_instances(self) -> None:
        app = _http_app()
        test_app = compile_for_testing(app)
        for route in test_app.routes:
            assert isinstance(route, WireTestRoute)

    def test_triggers_preserved_on_routes(self) -> None:
        app = _http_app()
        test_app = compile_for_testing(app)
        triggers = [r.trigger for r in test_app.routes]
        trigger_classes = {type(t) for t in triggers}
        assert HTTPRouteTrigger in trigger_classes

    def test_mixed_triggers_all_included(self) -> None:
        """Testing compiler accepts ANY trigger type (trigger_type=object)."""
        app = _mixed_trigger_app()
        test_app = compile_for_testing(app)
        # Both HTTP and CLI triggers should be included
        assert len(test_app.routes) == 2

    @pytest.mark.asyncio
    async def test_rrc_route_is_callable(self) -> None:
        """TestRoute.call() executes the handler pipeline."""
        app = _http_app()
        test_app = compile_for_testing(app)
        # Find the GET route (has user_id field)
        for route in test_app.routes:
            if isinstance(route.trigger, HTTPRouteTrigger) and route.trigger.method == "GET":
                result = await route.call({"user_id": 42})
                assert result is not None
                break
        else:
            pytest.fail("GET route not found")

    @pytest.mark.asyncio
    async def test_rrc_route_returns_response_type(self) -> None:
        app = _http_app()
        test_app = compile_for_testing(app)
        for route in test_app.routes:
            if isinstance(route.trigger, HTTPRouteTrigger) and route.trigger.method == "GET":
                result = await route.call({"user_id": 1})
                assert isinstance(result, GetUserResponse)
                assert result.user_id == 1
                assert result.name == "Alice"
                break

    @pytest.mark.asyncio
    async def test_post_route_callable(self) -> None:
        app = _http_app()
        test_app = compile_for_testing(app)
        for route in test_app.routes:
            if isinstance(route.trigger, HTTPRouteTrigger) and route.trigger.method == "POST":
                result = await route.call({"name": "Bob", "age": 30})
                assert isinstance(result, CreateUserResponse)
                assert result.name == "Bob"
                assert result.age == 30
                break
        else:
            pytest.fail("POST route not found")

    def test_empty_app_produces_empty_test_app(self) -> None:
        app = Application()
        test_app = compile_for_testing(app)
        assert len(test_app.routes) == 0

    @pytest.mark.asyncio
    async def test_immediate_codec_route_callable(self) -> None:
        ep = endpoint(empty_runner()).expose(
            HTTPRouteTrigger("GET", "/health"),
            immediate(ImmediateHealth),
        )
        app = Application().mount(ep)
        test_app = compile_for_testing(app)
        assert len(test_app.routes) == 1
        result = await test_app.routes[0].call()
        assert isinstance(result, ImmediateHealth)
        assert result.status == "ok"

    @pytest.mark.asyncio
    async def test_delegate_codec_route_callable(self) -> None:
        async def simple_handler() -> str:
            return "delegate-result"

        ep = endpoint(empty_runner()).expose(
            HTTPRouteTrigger("GET", "/simple"),
            delegate(simple_handler),
        )
        app = Application().mount(ep)
        test_app = compile_for_testing(app)
        assert len(test_app.routes) == 1
        result = await test_app.routes[0].call()
        assert result == "delegate-result"


class TestTestingCompilationMultipleEntities:
    """Testing compilation with different entity shapes."""

    @pytest.mark.asyncio
    async def test_different_field_types(self) -> None:
        runner = ops().on(TypeTestOp, _type_test_handler).compile()
        ep = endpoint(runner).expose(
            HTTPRouteTrigger("POST", "/typed"),
            rrc(TypeTestReq, TypeTestResp),
        )
        app = Application().mount(ep)
        test_app = compile_for_testing(app)
        result = await test_app.routes[0].call({"flag": True, "count": 5, "label": "xyz"})
        assert isinstance(result, TypeTestResp)
        assert result.value == "True-5-xyz"


# =============================================================================
# 4. Pure Target (Lifecycle, Exception, WebSocket)
# =============================================================================


class TestPureLifecycleCompilation:
    """Pure target compiles startup/shutdown handlers."""

    def test_startup_compiler_finds_startup_triggers(self) -> None:
        app = _lifecycle_app()
        axes = Axes.default()
        items = list(STARTUP_COMPILER.scan_and_wrap(app, axes))
        assert len(items) == 1
        trigger, _handler, route = items[0]
        assert isinstance(trigger, StartupTrigger)
        assert isinstance(route, LifecycleRoute)

    def test_shutdown_compiler_finds_shutdown_triggers(self) -> None:
        app = _lifecycle_app()
        axes = Axes.default()
        items = list(SHUTDOWN_COMPILER.scan_and_wrap(app, axes))
        assert len(items) == 1
        trigger, _handler, route = items[0]
        assert isinstance(trigger, ShutdownTrigger)
        assert isinstance(route, LifecycleRoute)

    def test_lifecycle_order_propagated(self) -> None:
        async def fn() -> None:
            pass

        ep1 = endpoint(empty_runner()).expose(StartupTrigger(order=10), delegate(fn))
        ep2 = endpoint(empty_runner()).expose(StartupTrigger(order=5), delegate(fn))
        app = Application().mount(ep1, ep2)
        axes = Axes.default()
        items = list(STARTUP_COMPILER.scan_and_wrap(app, axes))
        orders = [route.order for _, _, route in items]
        assert 10 in orders
        assert 5 in orders

    @pytest.mark.asyncio
    async def test_startup_handler_called(self) -> None:
        called: list[str] = []

        async def on_start() -> None:
            called.append("started")

        ep = endpoint(empty_runner()).expose(StartupTrigger(), delegate(on_start))
        app = Application().mount(ep)
        axes = Axes.default()
        items = list(STARTUP_COMPILER.scan_and_wrap(app, axes))
        assert len(items) == 1
        _, _, route = items[0]
        await route.handler()
        assert called == ["started"]

    def test_startup_compiler_ignores_http_triggers(self) -> None:
        app = _http_app()
        axes = Axes.default()
        items = list(STARTUP_COMPILER.scan_and_wrap(app, axes))
        assert len(items) == 0


class TestPureExceptionCompilation:
    """Pure target compiles exception handlers."""

    def test_exception_compiler_finds_exception_triggers(self) -> None:
        app = _exception_app()
        axes = Axes.default()
        items: list[Any] = list(EXCEPTION_COMPILER.scan_and_wrap(app, axes))
        assert len(items) == 1
        trigger, _handler, route = items[0]
        assert isinstance(trigger, ExceptionTrigger)
        assert isinstance(route, ExceptionRoute)
        assert route.exception_type is ValueError

    def test_exception_compiler_ignores_http_triggers(self) -> None:
        app = _http_app()
        axes = Axes.default()
        items: list[Any] = list(EXCEPTION_COMPILER.scan_and_wrap(app, axes))
        assert len(items) == 0


class TestPureWebsocketCompilation:
    """Pure target compiles websocket handlers."""

    def test_websocket_compiler_finds_ws_triggers(self) -> None:
        app = _websocket_app()
        axes = Axes.default()
        items = list(WEBSOCKET_COMPILER.scan_and_wrap(app, axes))
        assert len(items) == 1
        trigger, _handler, route = items[0]
        assert isinstance(trigger, WebSocketTrigger)
        assert isinstance(route, WebSocketRoute)

    def test_websocket_compiler_ignores_http_triggers(self) -> None:
        app = _http_app()
        axes = Axes.default()
        items = list(WEBSOCKET_COMPILER.scan_and_wrap(app, axes))
        assert len(items) == 0


# =============================================================================
# 5. Event Target
# =============================================================================


class TestEventCompilation:
    """Event compilation produces EventDispatcher with type routing."""

    def test_compile_produces_event_dispatcher(self) -> None:
        app = _event_app()
        dispatcher = event_compile(app)
        assert isinstance(dispatcher, EventDispatcher)

    def test_event_type_registered_in_routes(self) -> None:
        app = _event_app()
        dispatcher = event_compile(app)
        assert OrderCreated in dispatcher.routes

    def test_event_routes_are_event_route_instances(self) -> None:
        app = _event_app()
        dispatcher = event_compile(app)
        for route_tuple in dispatcher.routes.values():
            for route in route_tuple:
                assert isinstance(route, EventRoute)

    def test_multiple_event_types_separated(self) -> None:
        app = _multi_event_app()
        dispatcher = event_compile(app)
        assert OrderCreated in dispatcher.routes
        assert OrderCancelled in dispatcher.routes
        assert len(dispatcher.routes[OrderCreated]) == 1
        assert len(dispatcher.routes[OrderCancelled]) == 1

    @pytest.mark.asyncio
    async def test_dispatch_routes_to_correct_handler(self) -> None:
        app = _event_app()
        dispatcher = event_compile(app)
        event = OrderCreated(order_id=42, total=99.99)
        results = await dispatcher.dispatch(event)
        assert len(results) == 1
        response = results[0]
        assert isinstance(response, OrderEventResponse)
        assert response.result == "processed-42"

    @pytest.mark.asyncio
    async def test_dispatch_unregistered_event_returns_empty(self) -> None:
        app = _event_app()
        dispatcher = event_compile(app)
        results = await dispatcher.dispatch(OrderCancelled(order_id=1, reason="test"))
        assert results == ()

    def test_empty_app_produces_empty_dispatcher(self) -> None:
        app = Application()
        dispatcher = event_compile(app)
        assert len(dispatcher.routes) == 0

    def test_event_compiler_ignores_http_triggers(self) -> None:
        app = _http_app()
        axes = Axes.default()
        items = list(EVENT_COMPILER.scan_and_wrap(app, axes))
        assert len(items) == 0


class TestEventCompilationDelegate:
    """Event compilation with delegate codec."""

    @pytest.mark.asyncio
    async def test_delegate_event_handler(self) -> None:
        results: list[str] = []

        async def handle_cancel(evt: OrderCancelled) -> str:
            results.append(f"cancelled-{evt.order_id}")
            return f"cancelled-{evt.order_id}"

        ep = endpoint(empty_runner()).expose(
            EventTrigger(OrderCancelled),
            delegate(handle_cancel),
        )
        app = Application().mount(ep)
        dispatcher = event_compile(app)
        assert OrderCancelled in dispatcher.routes


# =============================================================================
# 6. Cross-Target Properties
# =============================================================================


class TestCrossTargetProperties:
    """Properties that hold across multiple targets."""

    def test_same_app_compiles_to_different_targets(self) -> None:
        """An app with both HTTP and CLI triggers compiles to both targets."""
        app = _mixed_trigger_app()
        fapi = fastapi_compile(app)
        parser = cli_compile(app, prog="test")
        test_app = compile_for_testing(app)

        # FastAPI gets only HTTP routes
        api_routes = [r for r in fapi.routes if isinstance(r, fastapi.routing.APIRoute)]
        assert len(api_routes) == 1

        # CLI gets only CLI commands
        choices = _get_choices(parser)
        assert len(choices) == 1

        # Testing gets everything
        assert len(test_app.routes) == 2

    def test_compilation_is_idempotent(self) -> None:
        """Compiling the same app twice gives structurally equal results."""
        app = _http_app()
        fapi1 = fastapi_compile(app)
        fapi2 = fastapi_compile(app)
        routes1 = {r.path for r in fapi1.routes if isinstance(r, fastapi.routing.APIRoute)}
        routes2 = {r.path for r in fapi2.routes if isinstance(r, fastapi.routing.APIRoute)}
        assert routes1 == routes2

    def test_compilation_preserves_app_immutability(self) -> None:
        """Compiling does not mutate the original Application."""
        app = _http_app()
        original_endpoints = app.endpoints
        fastapi_compile(app)
        cli_compile(Application().mount(*[
            endpoint(ep.runner).expose(CLITrigger("cmd"), rrc(GetUserRequest, GetUserResponse))
            for ep in app.endpoints
        ]))
        assert app.endpoints is original_endpoints


class TestCompilerInstances:
    """Compiler instances have correct structure."""

    def test_fastapi_compiler_trigger_type(self) -> None:
        assert FASTAPI_COMPILER.trigger_type is HTTPRouteTrigger

    def test_cli_compiler_trigger_type(self) -> None:
        assert CLI_COMPILER.trigger_type is CLITrigger

    def test_testing_compiler_trigger_type(self) -> None:
        # Testing uses `object` to match any trigger
        assert TESTING_COMPILER.trigger_type is object

    def test_event_compiler_trigger_type(self) -> None:
        assert EVENT_COMPILER.trigger_type is EventTrigger

    def test_startup_compiler_trigger_type(self) -> None:
        assert STARTUP_COMPILER.trigger_type is StartupTrigger

    def test_shutdown_compiler_trigger_type(self) -> None:
        assert SHUTDOWN_COMPILER.trigger_type is ShutdownTrigger

    def test_exception_compiler_trigger_type(self) -> None:
        assert EXCEPTION_COMPILER.trigger_type is ExceptionTrigger

    def test_websocket_compiler_trigger_type(self) -> None:
        assert WEBSOCKET_COMPILER.trigger_type is WebSocketTrigger

    def test_fastapi_compiler_has_rrc_binding(self) -> None:
        assert RequestResponseCodec in FASTAPI_COMPILER

    def test_cli_compiler_has_rrc_binding(self) -> None:
        assert RequestResponseCodec in CLI_COMPILER

    def test_event_compiler_has_rrc_binding(self) -> None:
        assert RequestResponseCodec in EVENT_COMPILER

    def test_testing_compiler_has_rrc_binding(self) -> None:
        assert RequestResponseCodec in TESTING_COMPILER

    def test_fastapi_compiler_has_delegate_binding(self) -> None:
        assert DelegateCodec in FASTAPI_COMPILER

    def test_cli_compiler_has_delegate_binding(self) -> None:
        assert DelegateCodec in CLI_COMPILER

    def test_fastapi_compiler_has_immediate_binding(self) -> None:
        assert ImmediateCodec in FASTAPI_COMPILER


# =============================================================================
# 7. Lifecycle Integration in FastAPI
# =============================================================================


class TestFastapiLifecycleIntegration:
    """FastAPI compile integrates lifecycle triggers as lifespan."""

    def test_fastapi_with_lifecycle_compiles(self) -> None:
        """An app combining HTTP + lifecycle triggers compiles to FastAPI."""
        runner = _user_runner()
        ep = endpoint(runner).expose(
            HTTPRouteTrigger("GET", "/users/{user_id}"),
            rrc(GetUserRequest, GetUserResponse),
        )
        async def on_start() -> None:
            pass

        lifecycle_ep = endpoint(empty_runner()).expose(
            StartupTrigger(), delegate(on_start),
        )
        app = Application().mount(ep, lifecycle_ep)
        fapi = fastapi_compile(app)
        assert isinstance(fapi, fastapi.FastAPI)
        api_routes = [r for r in fapi.routes if isinstance(r, fastapi.routing.APIRoute)]
        assert len(api_routes) == 1

    def test_fastapi_with_exception_handler_compiles(self) -> None:
        """An app combining HTTP + exception triggers compiles to FastAPI."""
        app = _http_app() + _exception_app()
        fapi = fastapi_compile(app)
        assert isinstance(fapi, fastapi.FastAPI)


# =============================================================================
# 8. Immediate Factory Codec
# =============================================================================


class TestImmediateFactoryCodec:
    """Immediate factory codec compiles across targets."""

    def test_fastapi_immediate_factory(self) -> None:
        ep = endpoint(empty_runner()).expose(
            HTTPRouteTrigger("GET", "/version"),
            immediate_factory(lambda: ImmediateHealth(status="v1.0")),
        )
        app = Application().mount(ep)
        fapi = fastapi_compile(app)
        paths = [r.path for r in fapi.routes if isinstance(r, fastapi.routing.APIRoute)]
        assert "/version" in paths

    @pytest.mark.asyncio
    async def test_testing_immediate_factory(self) -> None:
        ep = endpoint(empty_runner()).expose(
            HTTPRouteTrigger("GET", "/version"),
            immediate_factory(lambda: ImmediateHealth(status="v2.0")),
        )
        app = Application().mount(ep)
        test_app = compile_for_testing(app)
        result = await test_app.routes[0].call()
        assert isinstance(result, ImmediateHealth)
        assert result.status == "v2.0"

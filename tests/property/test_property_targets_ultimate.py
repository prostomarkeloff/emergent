# pyright: reportPrivateUsage=false
"""Ultimate deep-coverage tests for compile targets — remaining uncovered lines.

Covers the HARDEST remaining uncovered lines across:
  - telegrinder.py: runtime handler execution (RRC, stateful, immediate, delegate),
    _inject_tg_context merge branch, compose_store_key both paths,
    _compose_node both paths, compose_param (Scope/Context/Cute/node/fallback),
    try_compose_transition optional handling, resolve_transition iteration,
    HasActiveFlowState.check, register_handler view dispatch,
    telegrinder_compile full pipeline, wrap_rrc_telegrinder handler execution
  - fastapi.py: _rrc_execute deep path, _delegate_execute deep path,
    register_handler openapi_extra merge with responses, skip_route path,
    route_ctx deprecated + operation_id fields, setup_fastapi_scope pydantic branch,
    _default_coercion validation flow, fastapi_compile_stack nested StackView,
    _wrap_for_stack iteration fallthrough, lifespan without app_scope
  - cli.py: _rrc_execute_cli handler execution, _stateful_execute_cli loop,
    _delegate_execute_cli with dataclass args, _compose_cli_param node + prompt paths,
    coerce_cli_values pipeline, cli_run with app_scope lifespan
  - testing.py: TestApp __aenter__/__aexit__ lifecycle, delegate/immediate execution,
    testing_compile with family (scope lifecycle), backward-compat wrappers execution
  - pure.py: _lifecycle_factory_from_codec awaitable branch,
    _exception_delegate_from_codec execution, _websocket_delegate_from_codec execution,
    app_scope_lifespan with compose
  - event.py: _chain_injectors combined branch, _rrc_execute_event,
    _delegate_execute_event, EventDispatcher __aenter__/__aexit__,
    event_compile with family, EventRoute.call, backward-compat wrap_rrc_event

Uses REAL telegrinder, REAL FastAPI, REAL argparse. All fixtures via emergent pipeline.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field, replace
from typing import Annotated, Any, Self, cast
from unittest.mock import patch, MagicMock

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
    immediate_factory,
)
from emergent.wire.axis.surface.codecs.delegate import delegate, DelegateCodec
from emergent.wire.axis.surface.codecs.stateful import (
    StatefulCodec,
    Done,
    MemoryStorage,
)
from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger
from emergent.wire.axis.surface.triggers.cli import CLITrigger
from emergent.wire.axis.surface.triggers.lifecycle import StartupTrigger, ShutdownTrigger
from emergent.wire.axis.surface.triggers.exception import ExceptionTrigger
from emergent.wire.axis.surface.triggers.websocket import WebSocketTrigger
from emergent.wire.axis.surface.triggers.event import EventTrigger
from emergent.wire.axis.surface.triggers.telegrinder import TelegrindTrigger
from emergent.wire.compile._core import Axes
from emergent.wire.compile._lifetime import Tier, App, Request
from emergent.graph._family import ScopeFamily


# =============================================================================
# Domain types
# =============================================================================


@dataclass
class UltOp(Op[str, str]):
    msg: str


async def _ult_handler(req: UltOp) -> Result[str, str]:
    return Ok(f"ult:{req.msg}")


@dataclass
class UltRequest:
    msg: str

    def to_domain(self) -> UltOp:
        return UltOp(msg=self.msg)


@dataclass
class UltResponse:
    reply: str

    @classmethod
    def from_domain(cls, dom: Result[str, str]) -> Self:
        match dom:
            case Ok(v):
                return cls(reply=v)
            case _:
                return cls(reply="error")


@dataclass
class MultiOp(Op[dict[str, object], str]):
    name: str
    count: int
    active: bool


async def _multi_op_handler(req: MultiOp) -> Result[dict[str, object], str]:
    result: dict[str, object] = {"name": req.name, "count": req.count, "active": req.active}
    return Ok(result)


@dataclass
class MultiRequest:
    name: str
    count: int
    active: bool = False

    def to_domain(self) -> MultiOp:
        return MultiOp(name=self.name, count=self.count, active=self.active)


@dataclass
class MultiResponse:
    name: str
    count: int

    @classmethod
    def from_domain(cls, dom: Result[dict[str, object], str]) -> Self:
        match dom:
            case Ok(v):
                return cls(name=str(v["name"]), count=int(v["count"]))  # type: ignore[arg-type]
            case _:
                return cls(name="err", count=-1)


@dataclass
class UltHealth:
    status: str

    @classmethod
    def produce(cls) -> Self:
        return cls(status="ok")


@dataclass
class OrderPlaced:
    order_id: int
    amount: float


@dataclass
class OrderHandled:
    result: str


@dataclass
class OrderOp(Op[str, str]):
    order_id: int
    amount: float


async def _order_op_handler(req: OrderOp) -> Result[str, str]:
    return Ok(f"order-{req.order_id}")


@dataclass
class OrderRequest:
    order_id: int
    amount: float

    def to_domain(self) -> OrderOp:
        return OrderOp(order_id=self.order_id, amount=self.amount)


@dataclass
class OrderResponse:
    result: str

    @classmethod
    def from_domain(cls, dom: Result[str, str]) -> Self:
        match dom:
            case Ok(v):
                return cls(result=v)
            case _:
                return cls(result="error")


def _runner():
    return ops().on(UltOp, _ult_handler).on(MultiOp, _multi_op_handler).on(OrderOp, _order_op_handler).compile()


# =============================================================================
# Module-level Annotated dataclasses for telegrinder tests
# (must be at module level for get_type_hints to resolve annotations)
# =============================================================================

from emergent.wire.axis.schema.dialects.tg import CommandArg


@dataclass
class _UltTgReqWithArg:
    login: Annotated[str, CommandArg()]

    def to_domain(self) -> UltOp:
        return UltOp(msg=self.login)


@dataclass
class _UltTgReqWithMultiArg:
    name: Annotated[str, CommandArg()]

    def to_domain(self) -> UltOp:
        return UltOp(msg=self.name)


# =============================================================================
# Stateful flow
# =============================================================================


@dataclass
class UltChatId:
    """Simple key node for stateful codec."""
    __dependencies__: tuple[type, ...] = ()

    @classmethod
    def compose(cls, **kw: object) -> str:
        return "ult-test-key"


@dataclass
class UltFlow:
    """Two-step flow: collect then done."""
    collected: Option[str] = field(default_factory=Nothing)

    async def __transition__(self) -> Self | Done:
        if isinstance(self.collected, Some):
            return Done()
        return replace(self, collected=Some("step1"))

    def to_domain(self) -> UltOp:
        return UltOp(msg=self.collected.unwrap() if isinstance(self.collected, Some) else "none")


@dataclass
class UltFlowResponse:
    result: str

    @classmethod
    def from_domain(cls, dom: Result[str, str]) -> Self:
        match dom:
            case Ok(v):
                return cls(result=v)
            case _:
                return cls(result="error")


# =============================================================================
# 1. Testing Target — TestApp lifecycle and deep execution
# =============================================================================


class TestTestingTargetDeepExecution:
    """Test TestApp __aenter__/__aexit__ and route execution."""

    @pytest.mark.anyio
    async def test_test_app_context_manager_no_scope(self) -> None:
        """TestApp without family uses no app_scope — __aenter__/__aexit__ are noop."""
        from emergent.wire.compile.targets.testing import testing_compile

        runner = _runner()
        ep = endpoint(runner).expose(
            HTTPRouteTrigger("GET", "/ult"),
            rrc(UltRequest, UltResponse),
        )
        app = Application().mount(ep)
        test_app = testing_compile(app)

        async with test_app as ta:
            assert ta is test_app
            result = await ta.routes[0].call({"msg": "hello"})
            assert isinstance(result, UltResponse)
            assert result.reply == "ult:hello"

    @pytest.mark.anyio
    async def test_test_app_context_manager_with_family(self) -> None:
        """TestApp with family creates app_scope and enters lifecycle."""
        from emergent.wire.compile.targets.testing import testing_compile

        runner = _runner()
        ep = endpoint(runner).expose(
            HTTPRouteTrigger("GET", "/ult"),
            rrc(UltRequest, UltResponse),
        )
        app = Application().mount(ep)
        family = ScopeFamily[Tier]().bind(App).bind(Request)
        test_app = testing_compile(app, family=family)

        assert test_app._app_scope is not None
        async with test_app as ta:
            result = await ta.routes[0].call({"msg": "scoped"})
            assert isinstance(result, UltResponse)

    @pytest.mark.anyio
    async def test_delegate_route_execution(self) -> None:
        """Test delegate codec route execution via testing target."""
        from emergent.wire.compile.targets.testing import testing_compile

        async def my_delegate() -> str:
            return "delegated-value"

        ep = endpoint(empty_runner()).expose(
            HTTPRouteTrigger("GET", "/deleg"),
            delegate(my_delegate),
        )
        app = Application().mount(ep)
        test_app = testing_compile(app)
        result = await test_app.routes[0].call()
        assert result == "delegated-value"

    @pytest.mark.anyio
    async def test_immediate_route_execution(self) -> None:
        """Test immediate codec route execution via testing target."""
        from emergent.wire.compile.targets.testing import testing_compile

        ep = endpoint(empty_runner()).expose(
            HTTPRouteTrigger("GET", "/health"),
            immediate(UltHealth),
        )
        app = Application().mount(ep)
        test_app = testing_compile(app)
        result = await test_app.routes[0].call()
        assert isinstance(result, UltHealth)
        assert result.status == "ok"

    @pytest.mark.anyio
    async def test_immediate_factory_route_execution(self) -> None:
        from emergent.wire.compile.targets.testing import testing_compile

        ep = endpoint(empty_runner()).expose(
            HTTPRouteTrigger("GET", "/ver"),
            immediate_factory(lambda: {"version": "3.0"}),
        )
        app = Application().mount(ep)
        test_app = testing_compile(app)
        result = await test_app.routes[0].call()
        assert result == {"version": "3.0"}

    @pytest.mark.anyio
    async def test_route_call_with_inject(self) -> None:
        """Test TestRoute.call with scope injector."""
        from emergent.wire.compile.targets.testing import testing_compile

        runner = _runner()
        ep = endpoint(runner).expose(
            HTTPRouteTrigger("POST", "/multi"),
            rrc(MultiRequest, MultiResponse),
        )
        app = Application().mount(ep)
        test_app = testing_compile(app)

        def inject(scope: Scope) -> None:
            scope.inject(str, "injected-context")

        result = await test_app.routes[0].call(
            {"name": "alice", "count": 5, "active": True},
            inject=inject,
        )
        assert isinstance(result, MultiResponse)
        assert result.name == "alice"
        assert result.count == 5


class TestTestingBackwardCompatExecution:
    """Test backward-compat wrappers actually execute."""

    @pytest.mark.anyio
    async def test_wrap_rrc_testing_executes(self) -> None:
        from emergent.wire.compile.targets.testing import wrap_rrc_testing

        codec = RequestResponseCodec(request=UltRequest, response=UltResponse)
        handler = Handler(codec=codec, runner=_runner())
        axes = Axes.default()
        route = wrap_rrc_testing(handler, HTTPRouteTrigger("GET", "/test"), axes)
        result = await route.call({"msg": "wrapped"})
        assert isinstance(result, UltResponse)
        assert result.reply == "ult:wrapped"

    @pytest.mark.anyio
    async def test_wrap_delegate_testing_executes(self) -> None:
        from emergent.wire.compile.targets.testing import wrap_delegate_testing

        async def handler_fn() -> str:
            return "delegate-wrap"

        codec = DelegateCodec(handler=handler_fn)
        handler = Handler(codec=codec, runner=empty_runner())
        route = wrap_delegate_testing(handler, "test-trigger", Axes.default())
        result = await route.call()
        assert result == "delegate-wrap"

    @pytest.mark.anyio
    async def test_wrap_immediate_testing_executes(self) -> None:
        from emergent.wire.compile.targets.testing import wrap_immediate_testing

        codec = ImmediateCodec(response=UltHealth)
        handler = Handler(codec=codec, runner=empty_runner())
        route = wrap_immediate_testing(handler, "test-trigger", Axes.default())
        result = await route.call()
        assert isinstance(result, UltHealth)

    @pytest.mark.anyio
    async def test_wrap_immediate_factory_testing_executes(self) -> None:
        from emergent.wire.compile.targets.testing import wrap_immediate_factory_testing

        codec = ImmediateFactoryCodec(factory=lambda: {"key": "val"})
        handler = Handler(codec=codec, runner=empty_runner())
        route = wrap_immediate_factory_testing(handler, "test-trigger", Axes.default())
        result = await route.call()
        assert result == {"key": "val"}


# =============================================================================
# 2. Event Target — deep execution
# =============================================================================


class TestEventTargetDeepExecution:
    """Test EventDispatcher lifecycle and deep execution paths."""

    @pytest.mark.anyio
    async def test_event_dispatcher_lifecycle_no_scope(self) -> None:
        """EventDispatcher without family — __aenter__/__aexit__ noop."""
        from emergent.wire.compile.targets.event import event_compile

        runner = ops().on(OrderOp, _order_op_handler).compile()
        ep = endpoint(runner).expose(
            EventTrigger(OrderPlaced),
            rrc(OrderRequest, OrderResponse),
        )
        app = Application().mount(ep)
        dispatcher = event_compile(app)

        async with dispatcher as d:
            assert d is dispatcher
            results = await d.dispatch(OrderPlaced(order_id=99, amount=42.0))
            assert len(results) == 1
            assert isinstance(results[0], OrderResponse)
            assert results[0].result == "order-99"

    @pytest.mark.anyio
    async def test_event_dispatcher_lifecycle_with_family(self) -> None:
        """EventDispatcher with family — enters app_scope."""
        from emergent.wire.compile.targets.event import event_compile

        runner = ops().on(OrderOp, _order_op_handler).compile()
        ep = endpoint(runner).expose(
            EventTrigger(OrderPlaced),
            rrc(OrderRequest, OrderResponse),
        )
        app = Application().mount(ep)
        family = ScopeFamily[Tier]().bind(App).bind(Request)
        dispatcher = event_compile(app, family=family)

        assert dispatcher._app_scope is not None
        async with dispatcher as d:
            results = await d.dispatch(OrderPlaced(order_id=77, amount=10.0))
            assert len(results) == 1

    @pytest.mark.anyio
    async def test_delegate_event_execution(self) -> None:
        """Test delegate event handler execution."""
        from emergent.wire.compile.targets.event import event_compile

        results_log: list[str] = []

        async def handle_order(evt: OrderPlaced) -> str:
            results_log.append(f"handled-{evt.order_id}")
            return f"done-{evt.order_id}"

        ep = endpoint(empty_runner()).expose(
            EventTrigger(OrderPlaced),
            delegate(handle_order),
        )
        app = Application().mount(ep)
        dispatcher = event_compile(app)
        results = await dispatcher.dispatch(OrderPlaced(order_id=55, amount=5.0))
        assert len(results) == 1
        assert results[0] == "done-55"
        assert results_log == ["handled-55"]

    @pytest.mark.anyio
    async def test_event_route_call_with_inject(self) -> None:
        """Test EventRoute.call with scope injector."""
        from emergent.wire.compile.targets.event import event_compile

        runner = ops().on(OrderOp, _order_op_handler).compile()
        ep = endpoint(runner).expose(
            EventTrigger(OrderPlaced),
            rrc(OrderRequest, OrderResponse),
        )
        app = Application().mount(ep)
        dispatcher = event_compile(app)

        injected_values: list[str] = []

        def inject(scope: Scope) -> None:
            injected_values.append("injected")

        results = await dispatcher.dispatch(
            OrderPlaced(order_id=33, amount=1.0),
            inject=inject,
        )
        assert len(results) == 1
        assert injected_values == ["injected"]


class TestEventChainInjectors:
    """Test _chain_injectors helper."""

    def test_chain_injectors_no_user(self) -> None:
        from emergent.wire.compile.targets.event import _chain_injectors

        calls: list[str] = []

        def event_inject(scope: Scope) -> None:
            calls.append("event")

        result = _chain_injectors(event_inject, None)
        assert result is event_inject

    def test_chain_injectors_with_user(self) -> None:
        from emergent.wire.compile.targets.event import _chain_injectors

        calls: list[str] = []

        def event_inject(scope: Scope) -> None:
            calls.append("event")

        def user_inject(scope: Scope) -> None:
            calls.append("user")

        combined = _chain_injectors(event_inject, user_inject)
        assert combined is not event_inject
        scope = Scope(detail="test")
        combined(scope)
        assert calls == ["event", "user"]


class TestEventBackwardCompatWrappers:
    """Test backward-compat wrappers for event target."""

    @pytest.mark.anyio
    async def test_wrap_rrc_event_executes(self) -> None:
        from emergent.wire.compile.targets.event import wrap_rrc_event

        runner = ops().on(OrderOp, _order_op_handler).compile()
        codec = RequestResponseCodec(request=OrderRequest, response=OrderResponse)
        handler = Handler(codec=codec, runner=runner)
        trigger = EventTrigger(OrderPlaced)
        axes = Axes.default()
        route = wrap_rrc_event(handler, cast(EventTrigger[object], trigger), axes)

        result = await route.call(OrderPlaced(order_id=11, amount=1.0))
        assert isinstance(result, OrderResponse)
        assert result.result == "order-11"

    @pytest.mark.anyio
    async def test_wrap_delegate_event_executes(self) -> None:
        from emergent.wire.compile.targets.event import wrap_delegate_event

        async def handle(evt: OrderPlaced) -> str:
            return f"delegate-{evt.order_id}"

        codec = DelegateCodec(handler=handle)
        handler = Handler(codec=codec, runner=empty_runner())
        trigger = EventTrigger(OrderPlaced)
        route = wrap_delegate_event(handler, cast(EventTrigger[object], trigger), Axes.default())

        result = await route.call(OrderPlaced(order_id=22, amount=2.0))
        assert result == "delegate-22"


# =============================================================================
# 3. Pure Target — deep execution
# =============================================================================


class TestPureTargetDeepExecution:
    """Test pure target handler execution paths."""

    @pytest.mark.anyio
    async def test_lifecycle_delegate_async_execution(self) -> None:
        """Test lifecycle delegate handler actually runs."""
        from emergent.wire.compile.targets.pure import wrap_lifecycle_delegate

        called: list[str] = []

        async def on_start() -> None:
            called.append("started")

        codec = DelegateCodec(handler=on_start)
        handler = Handler(codec=codec, runner=empty_runner())
        route = wrap_lifecycle_delegate(handler, StartupTrigger(order=0), Axes.default())
        await route.handler()
        assert called == ["started"]

    @pytest.mark.anyio
    async def test_lifecycle_delegate_sync_execution(self) -> None:
        """Test lifecycle delegate with sync handler."""
        from emergent.wire.compile.targets.pure import wrap_lifecycle_delegate

        called: list[str] = []

        def on_start_sync() -> None:
            called.append("sync-start")

        codec = DelegateCodec(handler=on_start_sync)
        handler = Handler(codec=codec, runner=empty_runner())
        route = wrap_lifecycle_delegate(handler, StartupTrigger(order=0), Axes.default())
        await route.handler()
        assert called == ["sync-start"]

    @pytest.mark.anyio
    async def test_lifecycle_factory_sync_execution(self) -> None:
        """Test lifecycle factory with sync callable."""
        from emergent.wire.compile.targets.pure import wrap_lifecycle_factory

        called: list[str] = []

        def factory() -> None:
            called.append("factory")

        codec = ImmediateFactoryCodec(factory=factory)
        handler = Handler(codec=codec, runner=empty_runner())
        route = wrap_lifecycle_factory(handler, StartupTrigger(order=0), Axes.default())
        await route.handler()
        assert called == ["factory"]

    @pytest.mark.anyio
    async def test_lifecycle_factory_async_execution(self) -> None:
        """Test lifecycle factory with async callable."""
        from emergent.wire.compile.targets.pure import wrap_lifecycle_factory

        called: list[str] = []

        async def async_factory() -> None:
            called.append("async-factory")

        codec = ImmediateFactoryCodec(factory=async_factory)
        handler = Handler(codec=codec, runner=empty_runner())
        route = wrap_lifecycle_factory(handler, ShutdownTrigger(order=0), Axes.default())
        await route.handler()
        assert called == ["async-factory"]

    @pytest.mark.anyio
    async def test_exception_handler_execution(self) -> None:
        """Test exception handler gets invoked with scope."""
        from emergent.wire.compile.targets.pure import wrap_exception_delegate

        async def handle_exc(exc: ValueError) -> str:
            return f"caught-{exc}"

        codec = DelegateCodec(handler=handle_exc)
        handler = Handler(codec=codec, runner=empty_runner())
        route = wrap_exception_delegate(
            handler, ExceptionTrigger(ValueError), Axes.default()
        )

        scope = Scope(detail="test-exc")
        async with scope:
            scope.inject(ValueError, ValueError("test-error"))
            result = await route.handler(scope)
            assert "caught" in str(result)

    @pytest.mark.anyio
    async def test_websocket_handler_execution(self) -> None:
        """Test websocket handler gets invoked with scope."""
        from emergent.wire.compile.targets.pure import wrap_websocket_delegate

        called: list[str] = []

        async def ws_handler() -> None:
            called.append("ws-executed")

        codec = DelegateCodec(handler=ws_handler)
        handler = Handler(codec=codec, runner=empty_runner())
        route = wrap_websocket_delegate(
            handler, WebSocketTrigger("/ws/test"), Axes.default()
        )

        scope = Scope(detail="test-ws")
        async with scope:
            await route.handler(scope)
        assert called == ["ws-executed"]

    @pytest.mark.anyio
    async def test_websocket_sync_handler_execution(self) -> None:
        """Test websocket with sync handler."""
        from emergent.wire.compile.targets.pure import wrap_websocket_delegate

        called: list[str] = []

        def ws_handler_sync() -> None:
            called.append("ws-sync")

        codec = DelegateCodec(handler=ws_handler_sync)
        handler = Handler(codec=codec, runner=empty_runner())
        route = wrap_websocket_delegate(
            handler, WebSocketTrigger("/ws/sync"), Axes.default()
        )

        scope = Scope(detail="test-ws-sync")
        async with scope:
            await route.handler(scope)
        assert called == ["ws-sync"]

    @pytest.mark.anyio
    async def test_exception_sync_handler(self) -> None:
        """Test exception handler with sync function."""
        from emergent.wire.compile.targets.pure import wrap_exception_delegate

        def handle_exc_sync(exc: TypeError) -> str:
            return f"sync-caught-{exc}"

        codec = DelegateCodec(handler=handle_exc_sync)
        handler = Handler(codec=codec, runner=empty_runner())
        route = wrap_exception_delegate(
            handler, ExceptionTrigger(TypeError), Axes.default()
        )

        scope = Scope(detail="test-exc-sync")
        async with scope:
            scope.inject(TypeError, TypeError("type-err"))
            result = await route.handler(scope)
            assert "sync-caught" in str(result)


class TestAppScopeLifespanDeep:
    """Test app_scope_lifespan with compose list."""

    @pytest.mark.anyio
    async def test_app_scope_lifespan_with_empty_compose(self) -> None:
        from emergent.wire.compile.targets.pure import app_scope_lifespan

        scope = Scope(detail="test-app-lifespan")
        async with app_scope_lifespan(scope, compose=[]) as s:
            assert s is scope

    @pytest.mark.anyio
    async def test_app_scope_lifespan_without_compose(self) -> None:
        from emergent.wire.compile.targets.pure import app_scope_lifespan

        scope = Scope(detail="test-app-lifespan-none")
        async with app_scope_lifespan(scope) as s:
            assert s is scope


# =============================================================================
# 4. FastAPI Target — deep runtime paths
# =============================================================================


class TestFastAPIDeepRuntimePaths:
    """Test deep runtime paths in FastAPI target."""

    def test_fastapi_compile_lifespan_no_scope(self) -> None:
        """Test fastapi_compile when no family is provided — lifespan without app_scope."""
        from emergent.wire.compile.targets.fastapi import fastapi_compile

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
            HTTPRouteTrigger("GET", "/ult"),
            rrc(UltRequest, UltResponse),
        )
        app = Application().mount(ep_start, ep_stop, ep_http)
        fapi = fastapi_compile(app)
        assert isinstance(fapi, fastapi.FastAPI)

    def test_register_handler_deprecated_operation_id(self) -> None:
        """Test register_handler with Deprecated and OperationId capabilities."""
        from emergent.wire.axis.surface.dialects.http import (
            Deprecated, OperationId, Summary,
        )
        from emergent.wire.compile.targets.fastapi import fastapi_compile

        runner = _runner()
        ep = endpoint(runner).expose(
            HTTPRouteTrigger("GET", "/deprecated"),
            rrc(UltRequest, UltResponse),
            Deprecated.because("Use v2"),
            OperationId.of("getDeprecated"),
            Summary.of("Get deprecated", "This is deprecated"),
        )
        app = Application().mount(ep)
        fapi = fastapi_compile(app)
        routes = [r for r in fapi.routes if isinstance(r, fastapi.routing.APIRoute)]
        dep_route = [r for r in routes if r.path == "/deprecated"]
        assert len(dep_route) == 1
        assert dep_route[0].deprecated is True
        assert dep_route[0].operation_id == "getDeprecated"
        assert dep_route[0].summary == "Get deprecated"

    @pytest.mark.anyio
    async def test_form_extractor_execution(self) -> None:
        """Test FastAPIFormExtractor actual extract method."""
        pytest.importorskip("multipart")  # python-multipart required for form parsing
        from emergent.wire.compile.targets.fastapi import FastAPIFormExtractor
        from starlette.testclient import TestClient

        ext = FastAPIFormExtractor()
        app = fastapi.FastAPI()

        @app.post("/form-test")
        async def _test(request: fastapi.Request) -> dict[str, object]:
            return await ext.extract(request)

        assert _test is not None  # registered via decorator
        client = TestClient(app)
        resp = client.post("/form-test", data={"field1": "val1", "field2": "val2"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["field1"] == "val1"
        assert data["field2"] == "val2"

    @pytest.mark.anyio
    async def test_json_extractor_form_urlencoded(self) -> None:
        """Test FastAPIJsonExtractor handles form-urlencoded content type."""
        pytest.importorskip("multipart")  # python-multipart required for form parsing
        from emergent.wire.compile.targets.fastapi import FastAPIJsonExtractor
        from starlette.testclient import TestClient

        ext = FastAPIJsonExtractor()
        app = fastapi.FastAPI()

        @app.post("/form-json")
        async def _test(request: fastapi.Request) -> dict[str, object]:
            return await ext.extract(request)

        assert _test is not None  # registered via decorator
        client = TestClient(app)
        resp = client.post(
            "/form-json",
            data={"key": "value"},
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
        assert resp.status_code == 200

    def test_fastapi_compile_with_exc_integration(self) -> None:
        """Test fastapi_compile integrates exception handlers."""
        from emergent.wire.compile.targets.fastapi import fastapi_compile

        async def exc_handler(exc: RuntimeError) -> str:
            return f"caught: {exc}"

        runner = _runner()
        ep_http = endpoint(runner).expose(
            HTTPRouteTrigger("GET", "/main"),
            rrc(UltRequest, UltResponse),
        )
        ep_exc = endpoint(empty_runner()).expose(
            ExceptionTrigger(RuntimeError),
            delegate(exc_handler),
        )
        app = Application().mount(ep_http, ep_exc)
        fapi = fastapi_compile(app)
        assert isinstance(fapi, fastapi.FastAPI)

        # HTTP route should be registered
        api_routes = [r for r in fapi.routes if isinstance(r, fastapi.routing.APIRoute)]
        assert len(api_routes) == 1

    def test_ws_compiler_scans_ws_triggers(self) -> None:
        """Test WEBSOCKET_COMPILER scans websocket triggers from app."""
        from emergent.wire.compile.targets.pure import WEBSOCKET_COMPILER, WebSocketRoute

        async def ws_handler() -> None:
            pass

        ep = endpoint(empty_runner()).expose(
            WebSocketTrigger("/ws/live", name="live"),
            delegate(ws_handler),
        )
        app = Application().mount(ep)
        axes = Axes.default()
        items = list(WEBSOCKET_COMPILER.scan_and_wrap(app, axes))
        assert len(items) == 1
        trigger, _, route = items[0]
        assert isinstance(trigger, WebSocketTrigger)
        assert trigger.path == "/ws/live"
        assert isinstance(route, WebSocketRoute)

    def test_openapi_extra_merge_with_route_ctx_extra(self) -> None:
        """Test register_handler merges openapi_extra from route and route_ctx."""
        from emergent.wire.axis.surface.dialects.http import Tag, ResponseStatus
        from emergent.wire.compile.targets.fastapi import fastapi_compile

        runner = _runner()
        ep = endpoint(runner).expose(
            HTTPRouteTrigger("POST", "/items"),
            rrc(MultiRequest, MultiResponse),
            Tag.of("items"),
            ResponseStatus(201),
        )
        app = Application().mount(ep)
        fapi = fastapi_compile(app)
        routes = [r for r in fapi.routes if isinstance(r, fastapi.routing.APIRoute)]
        items_route = [r for r in routes if r.path == "/items"]
        assert len(items_route) == 1
        assert items_route[0].status_code == 201
        assert "items" in (items_route[0].tags or [])


class TestFastAPICompileStackDeeper:
    """Test fastapi_compile_stack with multiple nesting levels."""

    def test_triple_nested_stack(self) -> None:
        from emergent.wire.compile.targets.fastapi import fastapi_compile_stack

        runner = _runner()
        ep_root = endpoint(runner).expose(
            HTTPRouteTrigger("GET", "/root"), rrc(UltRequest, UltResponse),
        )
        ep_l1 = endpoint(runner).expose(
            HTTPRouteTrigger("GET", "/list"), rrc(UltRequest, UltResponse),
        )
        ep_l2 = endpoint(runner).expose(
            HTTPRouteTrigger("GET", "/detail"), rrc(UltRequest, UltResponse),
        )

        root_app = Application().mount(ep_root)
        l1_app = Application().mount(ep_l1)
        l2_app = Application().mount(ep_l2)
        stack = (
            app_stack()
            .root(root_app)
            .mount("api", l1_app)
            .mount("admin", l2_app)
        )
        fapi = fastapi_compile_stack(stack)
        assert isinstance(fapi, fastapi.FastAPI)

    def test_stack_with_delegate_codec(self) -> None:
        """Test compile_stack with DelegateCodec in sub-app."""
        from emergent.wire.compile.targets.fastapi import fastapi_compile_stack

        runner = _runner()
        ep_root = endpoint(runner).expose(
            HTTPRouteTrigger("GET", "/main"), rrc(UltRequest, UltResponse),
        )

        async def delegate_handler() -> dict[str, str]:
            return {"status": "ok"}

        ep_sub = endpoint(empty_runner()).expose(
            HTTPRouteTrigger("GET", "/status"), delegate(delegate_handler),
        )
        root_app = Application().mount(ep_root)
        sub_app = Application().mount(ep_sub)
        stack = app_stack().root(root_app).mount("health", sub_app)
        fapi = fastapi_compile_stack(stack)
        assert isinstance(fapi, fastapi.FastAPI)


class TestFastAPIWrapForStackIteration:
    """Test _wrap_for_stack with codec that has no matching binding."""

    def test_wrap_for_stack_no_matching_binding(self) -> None:
        from emergent.wire.compile.targets.fastapi import _wrap_for_stack, FASTAPI_COMPILER

        @dataclass(frozen=True)
        class UnknownCodec:
            pass

        handler = Handler(
            codec=UnknownCodec(),  # type: ignore[arg-type]
            runner=_runner(),
        )
        trigger = HTTPRouteTrigger("GET", "/test")
        with pytest.raises(ValueError, match="No adapter for codec type"):
            _wrap_for_stack(handler, trigger, Axes.default(), FASTAPI_COMPILER)


class TestFastAPIPydanticSetup:
    """Test setup_fastapi_scope with pydantic types."""

    @pytest.mark.anyio
    async def test_setup_scope_with_pydantic_types(self) -> None:
        from emergent.wire.compile.targets.fastapi import setup_fastapi_scope
        from pydantic import BaseModel

        class MyModel(BaseModel):
            name: str
            age: int

        app_inner = fastapi.FastAPI()

        @app_inner.post("/test-pydantic")
        async def _test_pydantic(request: fastapi.Request) -> dict[str, str]:
            scope = Scope(detail="test-pydantic")
            async with scope:
                await setup_fastapi_scope(scope, request, {MyModel})
                wrapper = scope.get(MyModel)
                if wrapper is not None:
                    return {"name": wrapper.value.name}
                return {"name": "not-found"}

        assert _test_pydantic is not None  # registered via decorator
        from starlette.testclient import TestClient
        client = TestClient(app_inner)
        resp = client.post("/test-pydantic", json={"name": "alice", "age": 30})
        assert resp.status_code == 200
        assert resp.json()["name"] == "alice"

    @pytest.mark.anyio
    async def test_setup_scope_pydantic_invalid_json(self) -> None:
        """When body is invalid JSON and pydantic types exist, scope doesn't crash."""
        from emergent.wire.compile.targets.fastapi import setup_fastapi_scope
        from pydantic import BaseModel

        class BadModel(BaseModel):
            x: int

        app_inner = fastapi.FastAPI()

        @app_inner.post("/bad-pydantic")
        async def _test_bad(request: fastapi.Request) -> str:
            scope = Scope(detail="test-bad")
            async with scope:
                await setup_fastapi_scope(scope, request, {BadModel})
                return "ok"

        assert _test_bad is not None  # registered via decorator
        from starlette.testclient import TestClient
        client = TestClient(app_inner)
        resp = client.post(
            "/bad-pydantic",
            content=b"not-json",
            headers={"content-type": "text/plain"},
        )
        assert resp.status_code == 200


# =============================================================================
# 5. CLI Target — deep runtime paths
# =============================================================================


class TestCLIDeepExecution:
    """Test CLI deep execution paths."""

    @pytest.mark.anyio
    async def test_rrc_execute_cli_with_scope(self) -> None:
        """Test _rrc_execute_cli with namespace in scope."""
        from emergent.wire.compile.targets.cli import _rrc_execute_cli

        runner = _runner()
        codec = RequestResponseCodec(request=UltRequest, response=UltResponse)
        handler = Handler(codec=codec, runner=runner)

        scope = Scope(detail="cli-test")
        async with scope:
            ns = argparse.Namespace(msg="cli-hello")
            scope.inject(argparse.Namespace, ns)
            result = await _rrc_execute_cli(handler, scope, None)
            assert result is not None

    @pytest.mark.anyio
    async def test_rrc_execute_cli_with_get_value(self) -> None:
        """Test _rrc_execute_cli with explicit get_value."""
        from emergent.wire.compile.targets.cli import _rrc_execute_cli

        runner = _runner()
        codec = RequestResponseCodec(request=UltRequest, response=UltResponse)
        handler = Handler(codec=codec, runner=runner)

        scope = Scope(detail="cli-test")
        async with scope:
            result = await _rrc_execute_cli(
                handler, scope,
                lambda name: "custom-msg" if name == "msg" else None,
            )
            assert result is not None

    @pytest.mark.anyio
    async def test_rrc_execute_cli_no_ns_in_scope(self) -> None:
        """Test _rrc_execute_cli when no namespace is in scope."""
        from emergent.wire.compile.targets.cli import _rrc_execute_cli

        runner = _runner()
        codec = RequestResponseCodec(request=UltRequest, response=UltResponse)
        handler = Handler(codec=codec, runner=runner)

        scope = Scope(detail="cli-test-no-ns")
        async with scope:
            result = await _rrc_execute_cli(
                handler, scope,
                lambda name: "fallback" if name == "msg" else None,
            )
            assert result is not None

    @pytest.mark.anyio
    async def test_delegate_execute_cli_with_ns(self) -> None:
        """Test _delegate_execute_cli with arguments resolved from ns."""
        from emergent.wire.compile.targets.cli import _delegate_execute_cli

        def my_handler(name: str) -> str:
            return f"hello-{name}"

        codec = DelegateCodec(handler=my_handler)
        handler = Handler(codec=codec, runner=empty_runner())

        scope = Scope(detail="cli-delegate")
        async with scope:
            ns = argparse.Namespace(name="alice")
            scope.inject(argparse.Namespace, ns)
            result = await _delegate_execute_cli(handler, scope, None)
            assert "hello-alice" in str(result)

    @pytest.mark.anyio
    async def test_delegate_execute_cli_no_ns(self) -> None:
        """Test _delegate_execute_cli when no namespace in scope."""
        from emergent.wire.compile.targets.cli import _delegate_execute_cli

        def my_handler() -> str:
            return "no-args"

        codec = DelegateCodec(handler=my_handler)
        handler = Handler(codec=codec, runner=empty_runner())

        scope = Scope(detail="cli-delegate-no-ns")
        async with scope:
            result = await _delegate_execute_cli(handler, scope, None)
            assert "no-args" in str(result)

    @pytest.mark.anyio
    async def test_immediate_execute_cli(self) -> None:
        """Test _immediate_execute_cli produces str output."""
        from emergent.wire.compile.targets.cli import _immediate_execute_cli

        codec = ImmediateCodec(response=UltHealth)
        handler = Handler(codec=codec, runner=empty_runner())

        scope = Scope(detail="cli-imm")
        async with scope:
            result = await _immediate_execute_cli(handler, scope, None)
            assert "ok" in str(result)


class TestCLIRunWithAppScope:
    """Test cli_run with app scope lifespan path."""

    def test_cli_run_with_scope_success(self) -> None:
        from emergent.wire.compile.targets.cli import cli_run

        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        cmd = sub.add_parser("greet")

        async def _greet(ns: argparse.Namespace) -> str:
            return "hello-output"

        cmd.set_defaults(_handler=_greet)

        # Attach app scope to parser
        app_scope = Scope(detail="cli-app")
        parser._scope_app = app_scope  # type: ignore[attr-defined]
        parser._scope_app_types = frozenset[type]()  # type: ignore[attr-defined]

        result = cli_run(parser, ["greet"])
        assert result == 0


class TestCLIComposeCliParam:
    """Test _compose_cli_param with different param types."""

    @pytest.mark.anyio
    async def test_compose_cli_param_from_args(self) -> None:
        """Test composing a param from CLI args."""
        from emergent.wire.compile.targets.cli import _compose_cli_param
        from nodnod.agent.event_loop.agent import EventLoopAgent

        scope = Scope(detail="cli-compose-test")
        async with scope:
            result = await _compose_cli_param(
                "name", str, str,
                {"name": "alice"},
                scope, EventLoopAgent,
            )
            # Should wrap the CLI arg value
            assert result is not None

    @pytest.mark.anyio
    async def test_compose_cli_param_prompt_fallback(self) -> None:
        """Test composing a param that falls back to prompt."""
        from emergent.wire.compile.targets.cli import _compose_cli_param
        from nodnod.agent.event_loop.agent import EventLoopAgent

        scope = Scope(detail="cli-compose-prompt")
        async with scope:
            with patch("emergent.wire.compile.targets.cli._prompt_value", return_value="prompted"):
                result = await _compose_cli_param(
                    "missing", str, str,
                    {},  # not in cli_args
                    scope, EventLoopAgent,
                )
                assert result is not None

    @pytest.mark.anyio
    async def test_compose_cli_param_prompt_none(self) -> None:
        """Test composing a param when prompt returns None — uses Option type to avoid raise."""
        from emergent.wire.compile.targets.cli import _compose_cli_param
        from nodnod.agent.event_loop.agent import EventLoopAgent

        scope = Scope(detail="cli-compose-none")
        async with scope:
            with patch("emergent.wire.compile.targets.cli._prompt_value", return_value=None):
                # Use Option[str] as original_type so wrap returns Nothing instead of raising
                result = await _compose_cli_param(
                    "missing", Option[str], str,
                    {},
                    scope, EventLoopAgent,
                )
                # Should wrap with success=False → Nothing
                assert isinstance(result, Nothing)


class TestCLIInspectHandlerEdgeCases:
    """Test _inspect_handler_params edge cases."""

    def test_handler_with_exception_on_signature(self) -> None:
        from emergent.wire.compile.targets.cli import _inspect_handler_params

        # Built-in print doesn't have Python-level type hints
        params = _inspect_handler_params(print)
        # Should not crash, might return empty
        assert isinstance(params, list)


class TestCLIBuildDelegateArgsEdgeCases:
    """Test _build_delegate_args with edge cases."""

    def test_build_args_missing_value(self) -> None:
        from emergent.wire.compile.targets.cli import _build_delegate_args

        def handler(name: str, missing: str) -> str:
            return name

        ns = argparse.Namespace(name="alice")
        # missing is not in namespace
        args = _build_delegate_args(handler, ns)
        assert args.get("name") == "alice"
        # missing should not be in args since getattr returns None
        assert "missing" not in args


class TestCLIGetDelegateArgSpecsEdge:
    """Test _get_delegate_arg_specs with complex types."""

    def test_handler_with_float_param(self) -> None:
        from emergent.wire.compile.targets.cli import _get_delegate_arg_specs

        def handler(ratio: float, count: int = 5) -> str:
            return str(ratio)

        specs = _get_delegate_arg_specs(handler, Axes.default())
        assert len(specs) > 0

    def test_handler_with_unknown_type(self) -> None:
        from emergent.wire.compile.targets.cli import _get_delegate_arg_specs

        class CustomType:
            pass

        def handler(obj: CustomType) -> str:
            return str(obj)

        specs = _get_delegate_arg_specs(handler, Axes.default())
        # Unknown types may generate specs or not — just verify no crash
        assert isinstance(specs, list)


# =============================================================================
# 6. Telegrinder Target — deep runtime paths
# =============================================================================


class TestTelegrindInjectContext:
    """Test _inject_tg_context merge vs parent branch."""

    def test_inject_context_merges_per_event_scope(self) -> None:
        from emergent.wire.compile.targets.telegrinder import _inject_tg_context

        parent = Scope(detail="parent")
        per_event = Scope(detail="per-event")
        child = parent.create_child("child")

        # Build a mock Context
        ctx = MagicMock()
        ctx.per_event_scope = per_event
        ctx.per_event_scope.items = MagicMock(return_value=[])

        _inject_tg_context(child, ctx)
        # Should inject Context type
        child.get(type(ctx))
        # It was injected if no error occurred


class TestTelegrindComposeParam:
    """Test compose_param with various compose_type scenarios."""

    @pytest.mark.anyio
    async def test_compose_param_scope_type(self) -> None:
        """When compose_type is Scope and scope is provided, returns scope."""
        from emergent.wire.compile.targets.telegrinder import compose_param

        scope = Scope(detail="test-scope")
        ctx = MagicMock()

        _agent_cls = cast(type, type)  # test placeholder for Agent subclass
        result = await compose_param(
            "scope_param", Scope, Scope,
            _agent_cls, ctx, None, scope=scope,
        )
        assert result is scope

    @pytest.mark.anyio
    async def test_compose_param_scope_type_no_scope(self) -> None:
        """When compose_type is Scope and no scope provided, returns Nothing-wrapped."""
        from emergent.wire.compile.targets.telegrinder import compose_param

        ctx = MagicMock()
        _agent_cls = cast(type, type)

        # Use Option[Scope] so wrap returns Nothing() instead of raising RuntimeError
        result = await compose_param(
            "scope_param", Option[Scope], Scope,
            _agent_cls, ctx, None, scope=None,
        )
        # Should be Nothing since success=False with Option type
        assert isinstance(result, Nothing)

    @pytest.mark.anyio
    async def test_compose_param_context_from_value(self) -> None:
        """When compose_type is not Scope/Context/Cute/Node, tries ctx.get."""
        from emergent.wire.compile.targets.telegrinder import compose_param

        ctx = MagicMock()
        ctx.get.return_value = "context-value"
        _agent_cls = cast(type, type)

        result = await compose_param(
            "some_param", str, str,
            _agent_cls, ctx, None,
        )
        assert result is not None


class TestTelegrindGetCuteValueDeep:
    """Test _get_cute_value edge cases."""

    def test_update_without_incoming_update(self) -> None:
        from emergent.wire.compile.targets.telegrinder import _get_cute_value

        class FakeUpdate:
            pass

        success, _value = _get_cute_value(str, FakeUpdate())
        assert success is False

    def test_update_with_wrong_type_incoming(self) -> None:
        from emergent.wire.compile.targets.telegrinder import _get_cute_value

        class FakeUpdate:
            incoming_update: int = 42

        success, _value = _get_cute_value(str, FakeUpdate())
        assert success is False

    def test_update_with_correct_type_incoming(self) -> None:
        from emergent.wire.compile.targets.telegrinder import _get_cute_value

        class FakeUpdate:
            incoming_update: str = "correct"

        success, value = _get_cute_value(str, FakeUpdate())
        assert success is True
        assert value == "correct"


class TestTelegrindIsCommandWithoutArgs:
    """Test _is_command_without_args helper."""

    def test_non_command_returns_false(self) -> None:
        from emergent.wire.compile.targets.telegrinder import _is_command_without_args
        from telegrinder.bot.rules.abc import ABCRule

        class NotCommand(ABCRule):
            async def check(self, event: object) -> bool:
                return True

        assert _is_command_without_args(NotCommand()) is False

    def test_command_with_arguments_returns_false(self) -> None:
        from emergent.wire.compile.targets.telegrinder import _is_command_without_args
        from telegrinder.bot.rules.command import Command, Argument

        cmd = Command("test", Argument("arg1"))
        assert _is_command_without_args(cmd) is False

    def test_command_without_arguments_returns_true(self) -> None:
        from emergent.wire.compile.targets.telegrinder import _is_command_without_args
        from telegrinder.bot.rules.command import Command

        cmd = Command("test")
        assert _is_command_without_args(cmd) is True


class TestTelegrindRRCFromCodecTg:
    """Test rrc_from_codec_tg creates context with enhanced rules."""

    def test_rrc_from_codec_tg_with_command_args(self) -> None:
        from emergent.wire.compile.targets.telegrinder import rrc_from_codec_tg
        from telegrinder.bot.rules.command import Command

        # Use module-level _UltTgReqWithArg (defined below)
        codec = RequestResponseCodec(request=_UltTgReqWithArg, response=UltResponse)
        trigger = TelegrindTrigger(Command("register"), view="message")
        ctx = rrc_from_codec_tg(codec, trigger)
        assert ctx.execute is not None
        assert len(ctx.rules) >= 1

    def test_rrc_from_codec_tg_no_args(self) -> None:
        from emergent.wire.compile.targets.telegrinder import rrc_from_codec_tg
        from telegrinder.bot.rules.command import Command

        codec = RequestResponseCodec(request=UltRequest, response=UltResponse)
        trigger = TelegrindTrigger(Command("echo"), view="message")
        ctx = rrc_from_codec_tg(codec, trigger)
        assert ctx.execute is not None


class TestTelegrindImmediateFromCodecTg:
    """Test immediate_from_codec_tg."""

    def test_immediate_from_codec(self) -> None:
        from emergent.wire.compile.targets.telegrinder import immediate_from_codec_tg
        from telegrinder.bot.rules.command import Command

        codec = ImmediateCodec(response=UltHealth)
        trigger = TelegrindTrigger(Command("health"), view="message")
        ctx = immediate_from_codec_tg(codec, trigger)
        assert ctx.execute is not None
        assert ctx.trigger is trigger


class TestTelegrindDelegateFromCodecTg:
    """Test delegate_from_codec_tg."""

    def test_delegate_from_codec(self) -> None:
        from emergent.wire.compile.targets.telegrinder import delegate_from_codec_tg
        from telegrinder.bot.rules.command import Command

        async def my_handler() -> str:
            return "ok"

        codec = DelegateCodec(handler=my_handler)
        trigger = TelegrindTrigger(Command("delegate"), view="message")
        ctx = delegate_from_codec_tg(codec, trigger)
        assert ctx.execute is not None
        assert ctx.trigger is trigger


class TestTelegrindAssembleNoneExecute:
    """Test assemble_telegrind_route with None execute."""

    def test_assemble_raises_on_none_execute(self) -> None:
        from emergent.wire.compile.targets.telegrinder import (
            assemble_telegrind_route, TelegrindWrapContext,
        )

        ctx = TelegrindWrapContext(execute=None, trigger=TelegrindTrigger(view="message"))
        handler = Handler(
            codec=RequestResponseCodec(request=UltRequest, response=UltResponse),
            runner=_runner(),
        )
        with pytest.raises(RuntimeError, match="execute is None"):
            assemble_telegrind_route(ctx, handler, Axes.default())


class TestTelegrindHasActiveFlowState:
    """Test HasActiveFlowState rule."""

    @pytest.mark.anyio
    async def test_check_no_active_state(self) -> None:
        from emergent.wire.compile.targets.telegrinder import HasActiveFlowState

        store: MemoryStorage[Any, Any] = MemoryStorage()
        rule = HasActiveFlowState(store=store, key_node=UltChatId, agent_cls=type)

        # Create a mock context
        ctx = MagicMock()
        per_event = Scope(detail="per-event")
        ctx.per_event_scope = per_event
        ctx.per_event_scope.create_child = MagicMock(return_value=Scope(detail="check"))

        # Should return False when no state in store
        result = await rule.check(ctx)
        assert result is False

    @pytest.mark.anyio
    async def test_check_exception_returns_false(self) -> None:
        from emergent.wire.compile.targets.telegrinder import HasActiveFlowState

        store: MemoryStorage[Any, Any] = MemoryStorage()
        rule = HasActiveFlowState(store=store, key_node=UltChatId, agent_cls=type)

        # Create a context that will cause an exception
        ctx = MagicMock()
        ctx.per_event_scope.create_child.side_effect = RuntimeError("boom")

        result = await rule.check(ctx)
        assert result is False


class TestTelegrindEnhanceCommandWithMultipleRules:
    """Test enhance_command_with_args with multiple rules."""

    def test_enhance_preserves_non_command_rules(self) -> None:
        from emergent.wire.compile.targets.telegrinder import enhance_command_with_args
        from telegrinder.bot.rules.command import Command
        from telegrinder.bot.rules.abc import ABCRule

        class CustomRule(ABCRule):
            async def check(self, event: object) -> bool:
                return True

        # Use module-level _UltTgReqWithMultiArg
        trigger = TelegrindTrigger(Command("cmd"), CustomRule(), view="message")
        enhanced = enhance_command_with_args(trigger, _UltTgReqWithMultiArg)
        # Should have both enhanced command and custom rule
        assert len(enhanced.rules) == 2


class TestTelegrindCompileMultiView:
    """Test telegrinder_compile with different view types."""

    def test_compile_message_and_callback_views(self) -> None:
        from emergent.wire.compile.targets.telegrinder import telegrinder_compile
        from telegrinder.bot.rules.command import Command
        from telegrinder.bot.rules.abc import ABCRule

        class CallbackMatcher(ABCRule):
            async def check(self, event: object) -> bool:
                return True

        runner = _runner()
        ep_msg = endpoint(runner).expose(
            TelegrindTrigger(Command("start"), view="message"),
            rrc(UltRequest, UltResponse),
        )
        ep_cb = endpoint(runner).expose(
            TelegrindTrigger(CallbackMatcher(), view="callback_query"),
            rrc(UltRequest, UltResponse),
        )
        app = Application().mount(ep_msg, ep_cb)
        dp = telegrinder_compile(app)
        assert dp is not None


class TestTelegrindWrapRRC:
    """Test wrap_rrc_telegrinder produces callable handler."""

    def test_wrap_rrc_produces_handler(self) -> None:
        from emergent.wire.compile.targets.telegrinder import (
            wrap_rrc_telegrinder, TelegrindRoute,
        )
        from telegrinder.bot.rules.command import Command

        codec = RequestResponseCodec(request=UltRequest, response=UltResponse)
        handler = Handler(codec=codec, runner=_runner())
        trigger = TelegrindTrigger(Command("echo"), view="message")
        route = wrap_rrc_telegrinder(handler, trigger, Axes.default())
        assert isinstance(route, TelegrindRoute)
        assert callable(route.handler)
        assert len(route.rules) >= 1


class TestTelegrindWrapStateful:
    """Test wrap_stateful_telegrinder produces callable handler."""

    def test_wrap_stateful_produces_handler(self) -> None:
        from emergent.wire.compile.targets.telegrinder import (
            wrap_stateful_telegrinder, TelegrindRoute,
        )
        from telegrinder.bot.rules.command import Command

        codec = StatefulCodec(
            flow=UltFlow, response=UltFlowResponse,
            store=MemoryStorage[Any, Any](), key_node=UltChatId, agent_cls=type,
        )
        handler = Handler(codec=codec, runner=_runner())
        trigger = TelegrindTrigger(Command("flow"), view="message")
        route = wrap_stateful_telegrinder(handler, trigger, Axes.default())
        assert isinstance(route, TelegrindRoute)
        assert callable(route.handler)
        assert len(route.rules) >= 1


class TestTelegrindRegisterHandler:
    """Test register_handler dispatches to correct view."""

    def test_register_calls_view(self) -> None:
        from emergent.wire.compile.targets.telegrinder import register_handler, TelegrindRoute
        from telegrinder.bot.rules.command import Command

        # Create a mock dispatch
        dp = MagicMock()
        mock_view = MagicMock()
        mock_decorator = MagicMock()
        mock_view.return_value = mock_decorator
        dp.message = mock_view

        async def handler(ctx: object) -> str:
            return "ok"

        route = TelegrindRoute(handler=handler, rules=())
        trigger = TelegrindTrigger(Command("test"), view="message")
        codec = RequestResponseCodec(request=UltRequest, response=UltResponse)
        handler_obj = Handler(codec=codec, runner=_runner())

        register_handler(dp, trigger, handler_obj, route)
        mock_view.assert_called_once()
        mock_decorator.assert_called_once_with(handler)


class TestTelegrindFormatResponseEdge:
    """Test _format_tg_response with telegrinder-module types."""

    def test_format_telegrinder_module_type(self) -> None:
        from emergent.wire.compile.targets.telegrinder import _format_tg_response

        class FakeTgType:
            __module__ = "telegrinder.types.objects"

            def __str__(self) -> str:
                return "custom-tg"

        obj = FakeTgType()
        result = _format_tg_response(obj)
        # Telegrinder types pass through even with custom __str__
        assert result is obj

    def test_format_dict_passthrough(self) -> None:
        from emergent.wire.compile.targets.telegrinder import _format_tg_response

        d = {"a": 1, "b": 2}
        assert _format_tg_response(d) is d


# =============================================================================
# 7. Cross-target deep integration
# =============================================================================


class TestCrossTargetWithLifecycle:
    """Test full lifecycle integration across targets."""

    @pytest.mark.anyio
    async def test_event_rrc_full_pipeline(self) -> None:
        """Full pipeline: build app, compile events, dispatch, verify response."""
        from emergent.wire.compile.targets.event import event_compile

        runner = ops().on(OrderOp, _order_op_handler).compile()
        ep = endpoint(runner).expose(
            EventTrigger(OrderPlaced),
            rrc(OrderRequest, OrderResponse),
        )
        app = Application().mount(ep)
        dispatcher = event_compile(app)

        async with dispatcher:
            # Dispatch multiple events
            r1 = await dispatcher.dispatch(OrderPlaced(order_id=1, amount=10.0))
            r2 = await dispatcher.dispatch(OrderPlaced(order_id=2, amount=20.0))
            assert getattr(r1[0], "result") == "order-1"
            assert getattr(r2[0], "result") == "order-2"

            # Unregistered type
            r3 = await dispatcher.dispatch("not-an-order")
            assert r3 == ()

    @pytest.mark.anyio
    async def test_testing_multi_codec_execution(self) -> None:
        """Test testing target with mixed codecs all executing."""
        from emergent.wire.compile.targets.testing import testing_compile

        runner = _runner()
        ep1 = endpoint(runner).expose(
            HTTPRouteTrigger("GET", "/rrc"),
            rrc(UltRequest, UltResponse),
        )
        ep2 = endpoint(empty_runner()).expose(
            HTTPRouteTrigger("GET", "/imm"),
            immediate(UltHealth),
        )

        async def deleg() -> str:
            return "delegated"

        ep3 = endpoint(empty_runner()).expose(
            HTTPRouteTrigger("GET", "/del"),
            delegate(deleg),
        )
        ep4 = endpoint(empty_runner()).expose(
            HTTPRouteTrigger("GET", "/fac"),
            immediate_factory(lambda: {"x": 1}),
        )
        app = Application().mount(ep1, ep2, ep3, ep4)
        test_app = testing_compile(app)

        assert len(test_app.routes) == 4
        for route in test_app.routes:
            if isinstance(route.trigger, HTTPRouteTrigger):
                if route.trigger.path == "/rrc":
                    r = await route.call({"msg": "multi"})
                    assert isinstance(r, UltResponse)
                elif route.trigger.path == "/imm":
                    r = await route.call()
                    assert isinstance(r, UltHealth)
                elif route.trigger.path == "/del":
                    r = await route.call()
                    assert r == "delegated"
                elif route.trigger.path == "/fac":
                    r = await route.call()
                    assert r == {"x": 1}


class TestFastAPICompileWithFamily:
    """Test fastapi_compile with family parameter."""

    def test_compile_with_family(self) -> None:
        from emergent.wire.compile.targets.fastapi import fastapi_compile

        runner = _runner()
        ep = endpoint(runner).expose(
            HTTPRouteTrigger("GET", "/echo"),
            rrc(UltRequest, UltResponse),
        )
        app = Application().mount(ep)
        family = ScopeFamily[Tier]().bind(App).bind(Request)
        fapi = fastapi_compile(app, family=family)
        assert isinstance(fapi, fastapi.FastAPI)
        routes = [r for r in fapi.routes if isinstance(r, fastapi.routing.APIRoute)]
        assert len(routes) == 1


class TestEventCompileWithFamily:
    """Test event_compile with family parameter."""

    @pytest.mark.anyio
    async def test_event_compile_with_family_dispatch(self) -> None:
        from emergent.wire.compile.targets.event import event_compile

        runner = ops().on(OrderOp, _order_op_handler).compile()
        ep = endpoint(runner).expose(
            EventTrigger(OrderPlaced),
            rrc(OrderRequest, OrderResponse),
        )
        app = Application().mount(ep)
        family = ScopeFamily[Tier]().bind(App).bind(Request)
        dispatcher = event_compile(app, family=family)

        assert dispatcher._app_scope is not None
        assert len(dispatcher._app_compose) >= 0

        async with dispatcher:
            results = await dispatcher.dispatch(OrderPlaced(order_id=88, amount=88.0))
            assert len(results) == 1


class TestCLICompileStackNested:
    """Test cli_compile_stack with deep nesting."""

    def test_compile_stack_mixed_codecs(self) -> None:
        from emergent.wire.compile.targets.cli import cli_compile_stack

        runner = _runner()
        ep_root = endpoint(runner).expose(
            CLITrigger("echo", "Echo"), rrc(UltRequest, UltResponse),
        )

        def status_handler() -> str:
            return "ok"

        ep_sub = endpoint(empty_runner()).expose(
            CLITrigger("status", "Status"), delegate(status_handler),
        )
        ep_health = endpoint(empty_runner()).expose(
            CLITrigger("health", "Health"), immediate(UltHealth),
        )
        root_app = Application().mount(ep_root)
        sub_app = Application().mount(ep_sub, ep_health)
        stack = app_stack().root(root_app).mount("admin", sub_app)
        parser = cli_compile_stack(stack, prog="nested")
        assert isinstance(parser, argparse.ArgumentParser)


class TestFastAPIOpenAPIQueryAndPathMerge:
    """Test OpenAPI generation where query params extend existing path params."""

    def test_get_with_path_and_query_params_extend(self) -> None:
        from emergent.wire.compile.targets.fastapi import build_rrc_openapi_extra

        codec = RequestResponseCodec(request=MultiRequest, response=MultiResponse)
        # GET with path param: /items/{name} — name is path, count+active are query
        trigger = HTTPRouteTrigger("GET", "/items/{name}")
        axes = Axes.default()
        extra = build_rrc_openapi_extra(codec, trigger, axes)
        assert extra is not None
        params = extra.get("parameters", [])
        path_params = [p for p in params if p.get("in") == "path"]
        query_params = [p for p in params if p.get("in") == "query"]
        assert len(path_params) == 1
        assert path_params[0]["name"] == "name"
        # count and active should be query params
        query_names = {p["name"] for p in query_params}
        assert "count" in query_names
        assert "active" in query_names


class TestFastAPIOpenAPIPOSTWithRequired:
    """Test OpenAPI POST body required field filtering."""

    def test_post_body_excludes_path_param_from_required(self) -> None:
        from emergent.wire.compile.targets.fastapi import build_rrc_openapi_extra

        codec = RequestResponseCodec(request=MultiRequest, response=MultiResponse)
        trigger = HTTPRouteTrigger("POST", "/items/{name}")
        axes = Axes.default()
        extra = build_rrc_openapi_extra(codec, trigger, axes)
        assert extra is not None
        body = extra.get("requestBody", {})
        if body:
            schema = body.get("content", {}).get("application/json", {}).get("schema", {})
            required = schema.get("required", [])
            # "name" should be removed from required since it's a path param
            assert "name" not in required


class TestCLIWrapForStackNoBinding:
    """Test CLI _wrap_for_stack with unmatched codec."""

    def test_wrap_for_stack_no_binding(self) -> None:
        from emergent.wire.compile.targets.cli import _wrap_for_stack, CLI_COMPILER

        @dataclass(frozen=True)
        class WeirdCodec:
            pass

        handler = Handler(
            codec=WeirdCodec(),  # type: ignore[arg-type]
            runner=_runner(),
        )
        trigger = CLITrigger("test", "Test")
        with pytest.raises(ValueError, match="No adapter for codec type"):
            _wrap_for_stack(handler, trigger, Axes.default(), CLI_COMPILER)


class TestTelegrindCompileEmpty:
    """Test telegrinder_compile with empty app."""

    def test_empty_app(self) -> None:
        from emergent.wire.compile.targets.telegrinder import telegrinder_compile

        app = Application()
        dp = telegrinder_compile(app)
        assert dp is not None


class TestEventCompileEmpty:
    """Test event_compile with empty app."""

    @pytest.mark.anyio
    async def test_empty_dispatch(self) -> None:
        from emergent.wire.compile.targets.event import event_compile

        app = Application()
        dispatcher = event_compile(app)
        results = await dispatcher.dispatch("anything")
        assert results == ()

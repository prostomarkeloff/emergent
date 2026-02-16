"""Tests for EventTrigger — self-contained event dispatch.

Covers:
1. EventTrigger creation + generic type
2. event_compile with RRC — event fields build request, runner executes Op
3. event_compile with DelegateCodec — handler receives event via Composer
4. dispatch routes to correct handler by event type
5. Multiple handlers per event type
6. Family/scope lifecycle via async context manager
7. explain_application shows [Event OrderCreated] in output
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from kungfu import Ok, Result

from nodnod import Scope

from emergent.ops import ops as _ops, Op, Returning
from emergent.wire.axis.surface._app import Application, application
from emergent.wire.axis.surface._endpoint import Endpoint, endpoint
from emergent.wire.axis.surface._types import Exposure
from emergent.wire.axis.surface.triggers.event import EventTrigger
from emergent.wire.axis.surface.codecs.rrc import RequestResponseCodec, rrc
from emergent.wire.axis.surface.codecs.delegate import DelegateCodec, delegate
from emergent.wire.axis.surface._explain import (
    explain_application,
    exposure_dict,
    SURFACE_EXPLAIN,
)
from emergent.wire.compile._core import Axes
from emergent.wire.compile._target import TargetCompiler, CodecAdapter
from emergent.wire.compile.targets.event import (
    EventRoute,
    EventDispatcher,
    EVENT_COMPILER,
    event_compile,
    wrap_rrc_event,
    wrap_delegate_event,
)
from emergent.wire.compile._lifetime import Tier, App, Request, ScopeLayer
from emergent.graph._family import ScopeFamily
from emergent.wire.axis.surface.enrichers import ScopeEnricher, EnricherNext, Passthrough


# ─── Domain types ──────────────────────────────────────────────────────────


@dataclass
class OrderCreated:
    order_id: int
    total: float


@dataclass
class UserSignedUp:
    user_id: int
    email: str


# ─── RRC domain types ─────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ProcessOrderOp(Op[str, str]):
    order_id: int
    total: float


@dataclass(frozen=True, slots=True)
class ProcessOrderRequest:
    order_id: int
    total: float

    def to_domain(self) -> ProcessOrderOp:
        return ProcessOrderOp(order_id=self.order_id, total=self.total)


@dataclass(frozen=True, slots=True)
class ProcessOrderResponse:
    message: str

    @classmethod
    def from_domain(cls, result: Result[str, str]) -> ProcessOrderResponse:
        match result:
            case Ok(value):
                return cls(message=value)
            case _:
                return cls(message="error")


async def _handle_process_order(req: ProcessOrderOp) -> Result[str, str]:
    return Ok(f"Order {req.order_id} processed for ${req.total}")


# ─── Helpers ───────────────────────────────────────────────────────────────


def _runner() -> Any:
    return _ops().on(ProcessOrderOp, _handle_process_order).compile()


# ═══════════════════════════════════════════════════════════════════════════════
# 1. EventTrigger creation + generic type
# ═══════════════════════════════════════════════════════════════════════════════


class TestEventTriggerBasic:
    def test_creation(self):
        trigger = EventTrigger(OrderCreated)
        assert trigger.event_type is OrderCreated

    def test_frozen(self):
        trigger = EventTrigger(OrderCreated)
        with pytest.raises(AttributeError):
            trigger.event_type = UserSignedUp  # type: ignore[misc]

    def test_equality(self):
        t1 = EventTrigger(OrderCreated)
        t2 = EventTrigger(OrderCreated)
        assert t1 == t2

    def test_inequality(self):
        t1 = EventTrigger(OrderCreated)
        t2 = EventTrigger(UserSignedUp)
        assert t1 != t2

    def test_expose_on_endpoint(self):
        runner = _runner()
        ep = endpoint(runner).expose(
            EventTrigger(OrderCreated),
            rrc(ProcessOrderRequest, ProcessOrderResponse),
        )
        assert len(ep.exposures) == 1
        assert isinstance(ep.exposures[0].trigger, EventTrigger)
        assert ep.exposures[0].trigger.event_type is OrderCreated


# ═══════════════════════════════════════════════════════════════════════════════
# 2. event_compile with RRC
# ═══════════════════════════════════════════════════════════════════════════════


class TestEventCompileRRC:
    @pytest.mark.asyncio
    async def test_rrc_event_dispatch(self):
        runner = _runner()
        app = application().mount(
            endpoint(runner).expose(
                EventTrigger(OrderCreated),
                rrc(ProcessOrderRequest, ProcessOrderResponse),
            )
        )
        dispatcher = event_compile(app)
        event = OrderCreated(order_id=42, total=99.99)
        results = await dispatcher.dispatch(event)
        assert len(results) == 1
        response = results[0]
        assert isinstance(response, ProcessOrderResponse)
        assert "42" in response.message
        assert "99.99" in response.message

    @pytest.mark.asyncio
    async def test_rrc_no_matching_event(self):
        runner = _runner()
        app = application().mount(
            endpoint(runner).expose(
                EventTrigger(OrderCreated),
                rrc(ProcessOrderRequest, ProcessOrderResponse),
            )
        )
        dispatcher = event_compile(app)
        results = await dispatcher.dispatch(UserSignedUp(user_id=1, email="a@b.com"))
        assert results == ()


# ═══════════════════════════════════════════════════════════════════════════════
# 3. event_compile with DelegateCodec
# ═══════════════════════════════════════════════════════════════════════════════


class TestEventCompileDelegate:
    @pytest.mark.asyncio
    async def test_delegate_event_dispatch(self):
        received: list[OrderCreated] = []

        async def handle_order(event: OrderCreated) -> str:
            received.append(event)
            return f"handled {event.order_id}"

        runner = _runner()
        app = application().mount(
            endpoint(runner).expose(
                EventTrigger(OrderCreated),
                delegate(handle_order),
            )
        )
        dispatcher = event_compile(app)
        event = OrderCreated(order_id=7, total=50.0)
        results = await dispatcher.dispatch(event)
        assert len(results) == 1
        assert results[0] == "handled 7"
        assert len(received) == 1
        assert received[0] is event


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Dispatch routes to correct handler by event type
# ═══════════════════════════════════════════════════════════════════════════════


class TestEventRouting:
    @pytest.mark.asyncio
    async def test_routes_by_type(self):
        order_results: list[str] = []
        user_results: list[str] = []

        async def handle_order(event: OrderCreated) -> str:
            msg = f"order:{event.order_id}"
            order_results.append(msg)
            return msg

        async def handle_user(event: UserSignedUp) -> str:
            msg = f"user:{event.user_id}"
            user_results.append(msg)
            return msg

        runner = _runner()
        app = application().mount(
            endpoint(runner).expose(
                EventTrigger(OrderCreated),
                delegate(handle_order),
            ),
            endpoint(runner).expose(
                EventTrigger(UserSignedUp),
                delegate(handle_user),
            ),
        )
        dispatcher = event_compile(app)

        await dispatcher.dispatch(OrderCreated(order_id=1, total=10.0))
        assert len(order_results) == 1
        assert len(user_results) == 0

        await dispatcher.dispatch(UserSignedUp(user_id=2, email="x@y.com"))
        assert len(order_results) == 1
        assert len(user_results) == 1


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Multiple handlers per event type
# ═══════════════════════════════════════════════════════════════════════════════


class TestMultipleHandlers:
    @pytest.mark.asyncio
    async def test_multiple_handlers_same_event(self):
        calls: list[str] = []

        async def handler_a(event: OrderCreated) -> str:
            calls.append("a")
            return "a"

        async def handler_b(event: OrderCreated) -> str:
            calls.append("b")
            return "b"

        runner = _runner()
        app = application().mount(
            endpoint(runner).expose(
                EventTrigger(OrderCreated),
                delegate(handler_a),
            ),
            endpoint(runner).expose(
                EventTrigger(OrderCreated),
                delegate(handler_b),
            ),
        )
        dispatcher = event_compile(app)
        results = await dispatcher.dispatch(OrderCreated(order_id=1, total=1.0))
        assert len(results) == 2
        assert set(results) == {"a", "b"}
        assert len(calls) == 2


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Family/scope lifecycle via async context manager
# ═══════════════════════════════════════════════════════════════════════════════


class TestEventDispatcherLifecycle:
    @pytest.mark.asyncio
    async def test_context_manager_no_family(self):
        runner = _runner()
        app = application().mount(
            endpoint(runner).expose(
                EventTrigger(OrderCreated),
                rrc(ProcessOrderRequest, ProcessOrderResponse),
            )
        )
        dispatcher = event_compile(app)
        async with dispatcher as d:
            assert d is dispatcher
            results = await d.dispatch(OrderCreated(order_id=1, total=10.0))
            assert len(results) == 1

    @pytest.mark.asyncio
    async def test_context_manager_with_family(self):
        family: ScopeFamily[Tier] = ScopeFamily[Tier]()

        async def handle_order(event: OrderCreated) -> str:
            return f"handled {event.order_id}"

        runner = _runner()
        app = application().mount(
            endpoint(runner).expose(
                EventTrigger(OrderCreated),
                delegate(handle_order),
            )
        )
        dispatcher = event_compile(app, family=family)
        async with dispatcher as d:
            results = await d.dispatch(OrderCreated(order_id=99, total=5.0))
            assert len(results) == 1
            assert results[0] == "handled 99"


# ═══════════════════════════════════════════════════════════════════════════════
# 7. explain_application shows [Event OrderCreated]
# ═══════════════════════════════════════════════════════════════════════════════


class TestEventExplain:
    def test_exposure_dict(self):
        exp = Exposure(
            trigger=EventTrigger(OrderCreated),
            codec=delegate(lambda: None),
        )
        d = exposure_dict(exp)
        assert d["trigger"]["type"] == "EventTrigger"
        assert d["trigger"]["event_type"] == "OrderCreated"

    def test_explain_application_format(self):
        runner = _runner()
        app = application().mount(
            endpoint(runner).expose(
                EventTrigger(OrderCreated),
                delegate(lambda ev: None),
            )
        )
        text = explain_application(app)
        assert "Event OrderCreated" in text
        assert "DelegateCodec" in text

    def test_event_trigger_in_surface_explain(self):
        assert EventTrigger in SURFACE_EXPLAIN


# ═══════════════════════════════════════════════════════════════════════════════
# EVENT_COMPILER — scan_and_wrap
# ═══════════════════════════════════════════════════════════════════════════════


class TestEventCompiler:
    def test_scan_rrc(self):
        runner = _runner()
        app = application().mount(
            endpoint(runner).expose(
                EventTrigger(OrderCreated),
                rrc(ProcessOrderRequest, ProcessOrderResponse),
            )
        )
        results = list(EVENT_COMPILER.scan_and_wrap(app, Axes.default()))
        assert len(results) == 1
        trigger, handler, route = results[0]
        assert isinstance(trigger, EventTrigger)
        assert trigger.event_type is OrderCreated
        assert isinstance(route, EventRoute)

    def test_scan_delegate(self):
        runner = _runner()
        app = application().mount(
            endpoint(runner).expose(
                EventTrigger(OrderCreated),
                delegate(lambda ev: None),
            )
        )
        results = list(EVENT_COMPILER.scan_and_wrap(app, Axes.default()))
        assert len(results) == 1
        _, _, route = results[0]
        assert isinstance(route, EventRoute)
        assert route.event_type is OrderCreated

    def test_scan_no_match(self):
        """Non-event triggers are ignored."""
        from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger

        runner = _runner()
        app = application().mount(
            endpoint(runner).expose(
                HTTPRouteTrigger("GET", "/test"),
                rrc(ProcessOrderRequest, ProcessOrderResponse),
            )
        )
        results = list(EVENT_COMPILER.scan_and_wrap(app, Axes.default()))
        assert len(results) == 0

    def test_compiler_extensible(self):
        """Can extend EVENT_COMPILER with custom codec."""

        @dataclass(frozen=True, slots=True)
        class CustomEventCodec:
            version: int = 1

        def wrap_custom(handler: Any, trigger: Any, axes: Any) -> EventRoute:
            async def invoke(event: object, inject: Any) -> object:
                return "custom"

            return EventRoute(
                event_type=trigger.event_type,
                trigger=trigger,
                _invoke=invoke,
            )

        extended = EVENT_COMPILER.with_codec(CustomEventCodec, wrap_custom)
        assert len(extended.adapters) == 3


# ═══════════════════════════════════════════════════════════════════════════════
# INTEGRATION TESTS
# ═══════════════════════════════════════════════════════════════════════════════


# ─── Shared domain types for integration tests ───────────────────────────────


@dataclass(frozen=True, slots=True)
class Config:
    env: str
    max_retries: int


@dataclass(frozen=True, slots=True)
class ValidateOrderOp(Op[str, str]):
    order_id: int
    total: float


@dataclass(frozen=True, slots=True)
class ValidateOrderRequest:
    order_id: int
    total: float

    def to_domain(self) -> ValidateOrderOp:
        return ValidateOrderOp(order_id=self.order_id, total=self.total)


@dataclass(frozen=True, slots=True)
class ValidateOrderResponse:
    message: str

    @classmethod
    def from_domain(cls, dom: Result[str, str]) -> ValidateOrderResponse:
        match dom:
            case Ok(value):
                return cls(message=value)
            case _:
                return cls(message="error")


async def _handle_validate_order(req: ValidateOrderOp) -> Result[str, str]:
    return Ok(f"validated:{req.order_id}:${req.total}")


def _validate_runner() -> Any:
    return _ops().on(ValidateOrderOp, _handle_validate_order).compile()


# ═══════════════════════════════════════════════════════════════════════════════
# Integration 1: Enricher Chain — Inject + Validate + short-circuit
# ═══════════════════════════════════════════════════════════════════════════════


class TestEnricherChain:
    """Inject config into scope, Validate event data, short-circuit on failure."""

    @pytest.mark.asyncio
    async def test_valid_event_gets_config_and_result(self):
        from emergent.wire.axis.surface.enrichers import Inject, Validate

        config = Config(env="test", max_retries=3)
        runner = _validate_runner()

        app = application().mount(
            endpoint(runner).expose(
                EventTrigger(OrderCreated),
                rrc(ValidateOrderRequest, ValidateOrderResponse),
                Inject(type=Config, value=config),
                Validate(
                    extract=lambda scope: scope.retrieve(type(None)),
                    predicate=lambda _: True,
                    on_invalid=lambda _: ValidateOrderResponse(message="invalid"),
                ),
            )
        )
        dispatcher = event_compile(app)
        results = await dispatcher.dispatch(OrderCreated(order_id=10, total=25.0))
        assert len(results) == 1
        resp = results[0]
        assert isinstance(resp, ValidateOrderResponse)
        assert "validated:10" in resp.message
        assert "25.0" in resp.message

    @pytest.mark.asyncio
    async def test_invalid_event_short_circuits(self):
        from emergent.wire.axis.surface.enrichers import Inject, Validate

        config = Config(env="test", max_retries=3)
        runner = _validate_runner()

        # Validate extracts the event from scope and checks total > 0
        app = application().mount(
            endpoint(runner).expose(
                EventTrigger(OrderCreated),
                rrc(ValidateOrderRequest, ValidateOrderResponse),
                Inject(type=Config, value=config),
                Validate(
                    extract=lambda scope: scope.retrieve(OrderCreated).value.value,
                    predicate=lambda ev: ev.total > 0,
                    on_invalid=lambda ev: ValidateOrderResponse(
                        message=f"invalid:total={ev.total}"
                    ),
                ),
            )
        )
        dispatcher = event_compile(app)

        # Valid event
        results = await dispatcher.dispatch(OrderCreated(order_id=1, total=50.0))
        assert len(results) == 1
        assert "validated:1" in results[0].message

        # Invalid event (total <= 0)
        results = await dispatcher.dispatch(OrderCreated(order_id=2, total=-5.0))
        assert len(results) == 1
        assert "invalid:total=-5.0" in results[0].message


# ═══════════════════════════════════════════════════════════════════════════════
# Integration 2: Custom ScopeEnricher — Auth-like pattern
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class AuthUser:
    user_id: int
    name: str


@dataclass(frozen=True, slots=True)
class AuthToken:
    token: str


@dataclass(frozen=True, slots=True)
class EventAuth(ScopeEnricher):
    """Auth enricher for events — validates token, injects AuthUser or short-circuits."""

    valid_tokens: dict[str, AuthUser]

    async def enrich(self, call: Any, scope: Any) -> Any:
        from kungfu import Some
        token_result = scope.retrieve(AuthToken)
        match token_result:
            case Some(v):
                token_val: AuthToken = v.value
                user = self.valid_tokens.get(token_val.token)
                if user is not None:
                    scope.inject(AuthUser, user)
                    return await call(scope)
                return {"error": "invalid_token"}
            case _:
                return {"error": "no_token"}


class TestCustomScopeEnricher:
    """Auth-like enricher pattern on events."""

    @pytest.mark.asyncio
    async def test_valid_token_injects_auth_user(self):
        valid_tokens = {"abc123": AuthUser(user_id=42, name="Alice")}
        received_users: list[AuthUser] = []

        async def handler(event: OrderCreated, user: AuthUser) -> dict[str, object]:
            received_users.append(user)
            return {"order": event.order_id, "user": user.name}

        runner = _runner()
        app = application().mount(
            endpoint(runner).expose(
                EventTrigger(OrderCreated),
                delegate(handler),
                EventAuth(valid_tokens=valid_tokens),
            )
        )
        dispatcher = event_compile(app)

        # Inject AuthToken into scope via dispatch inject
        results = await dispatcher.dispatch(
            OrderCreated(order_id=1, total=10.0),
            inject=lambda scope: scope.inject(AuthToken, AuthToken(token="abc123")),
        )
        assert len(results) == 1
        assert results[0] == {"order": 1, "user": "Alice"}
        assert len(received_users) == 1
        assert received_users[0].user_id == 42

    @pytest.mark.asyncio
    async def test_invalid_token_short_circuits(self):
        valid_tokens = {"abc123": AuthUser(user_id=42, name="Alice")}
        handler_called = False

        async def handler(event: OrderCreated) -> str:
            nonlocal handler_called
            handler_called = True
            return "should not reach"

        runner = _runner()
        app = application().mount(
            endpoint(runner).expose(
                EventTrigger(OrderCreated),
                delegate(handler),
                EventAuth(valid_tokens=valid_tokens),
            )
        )
        dispatcher = event_compile(app)

        results = await dispatcher.dispatch(
            OrderCreated(order_id=1, total=10.0),
            inject=lambda scope: scope.inject(AuthToken, AuthToken(token="bad")),
        )
        assert len(results) == 1
        assert results[0] == {"error": "invalid_token"}
        assert not handler_called

    @pytest.mark.asyncio
    async def test_missing_token_short_circuits(self):
        valid_tokens = {"abc123": AuthUser(user_id=42, name="Alice")}

        async def handler(event: OrderCreated) -> str:
            return "should not reach"

        runner = _runner()
        app = application().mount(
            endpoint(runner).expose(
                EventTrigger(OrderCreated),
                delegate(handler),
                EventAuth(valid_tokens=valid_tokens),
            )
        )
        dispatcher = event_compile(app)
        results = await dispatcher.dispatch(OrderCreated(order_id=1, total=10.0))
        assert len(results) == 1
        assert results[0] == {"error": "no_token"}


# ═══════════════════════════════════════════════════════════════════════════════
# Integration 3: Response Transforms — AsDict + custom Transform
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class OrderResult:
    order_id: int
    status: str


class TestResponseTransforms:
    """AsDict + custom Transform applied after event execution."""

    @pytest.mark.asyncio
    async def test_asdict_converts_dataclass_response(self):
        from emergent.wire.axis.surface.transforms import AsDict

        runner = _validate_runner()
        app = application().mount(
            endpoint(runner).expose(
                EventTrigger(OrderCreated),
                rrc(ValidateOrderRequest, ValidateOrderResponse),
                AsDict(),
            )
        )
        dispatcher = event_compile(app)
        results = await dispatcher.dispatch(OrderCreated(order_id=5, total=100.0))
        assert len(results) == 1
        assert isinstance(results[0], dict)
        assert "message" in results[0]
        assert "validated:5" in results[0]["message"]

    @pytest.mark.asyncio
    async def test_custom_transform_wraps_in_envelope(self):
        from emergent.wire.axis.surface.transforms import Transform

        runner = _validate_runner()
        app = application().mount(
            endpoint(runner).expose(
                EventTrigger(OrderCreated),
                rrc(ValidateOrderRequest, ValidateOrderResponse),
                Transform(fn=lambda r: {"data": r, "ok": True}),
            )
        )
        dispatcher = event_compile(app)
        results = await dispatcher.dispatch(OrderCreated(order_id=7, total=50.0))
        assert len(results) == 1
        envelope = results[0]
        assert isinstance(envelope, dict)
        assert envelope["ok"] is True
        assert isinstance(envelope["data"], ValidateOrderResponse)

    @pytest.mark.asyncio
    async def test_asdict_then_transform_pipeline(self):
        from emergent.wire.axis.surface.transforms import AsDict, Transform

        runner = _validate_runner()
        app = application().mount(
            endpoint(runner).expose(
                EventTrigger(OrderCreated),
                rrc(ValidateOrderRequest, ValidateOrderResponse),
                AsDict(),
                Transform(fn=lambda d: {"envelope": d, "version": 2}),
            )
        )
        dispatcher = event_compile(app)
        results = await dispatcher.dispatch(OrderCreated(order_id=3, total=75.0))
        assert len(results) == 1
        envelope = results[0]
        assert envelope["version"] == 2
        assert isinstance(envelope["envelope"], dict)
        assert "validated:3" in envelope["envelope"]["message"]


# ═══════════════════════════════════════════════════════════════════════════════
# Integration 4: Enricher Ordering — nested middleware stack
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class TrackEnricher(ScopeEnricher):
    """Records enter/exit to a shared list for ordering verification."""

    name: str
    log: list[str]

    async def enrich(self, call: Any, scope: Any) -> Any:
        self.log.append(f"{self.name}_enter")
        result = await call(scope)
        self.log.append(f"{self.name}_exit")
        return result


class TestEnricherOrdering:
    """Verify enricher chain builds e1(e2(handler)) — outer runs first."""

    @pytest.mark.asyncio
    async def test_ordering_outer_inner_handler(self):
        log: list[str] = []

        async def handler(event: OrderCreated) -> str:
            log.append("handler")
            return "done"

        runner = _runner()
        app = application().mount(
            endpoint(runner).expose(
                EventTrigger(OrderCreated),
                delegate(handler),
                TrackEnricher(name="outer", log=log),
                TrackEnricher(name="inner", log=log),
            )
        )
        dispatcher = event_compile(app)
        results = await dispatcher.dispatch(OrderCreated(order_id=1, total=1.0))
        assert results[0] == "done"
        assert log == [
            "outer_enter",
            "inner_enter",
            "handler",
            "inner_exit",
            "outer_exit",
        ]

    @pytest.mark.asyncio
    async def test_three_enrichers_ordering(self):
        log: list[str] = []

        async def handler(event: OrderCreated) -> str:
            log.append("handler")
            return "ok"

        runner = _runner()
        app = application().mount(
            endpoint(runner).expose(
                EventTrigger(OrderCreated),
                delegate(handler),
                TrackEnricher(name="a", log=log),
                TrackEnricher(name="b", log=log),
                TrackEnricher(name="c", log=log),
            )
        )
        dispatcher = event_compile(app)
        await dispatcher.dispatch(OrderCreated(order_id=1, total=1.0))
        assert log == [
            "a_enter", "b_enter", "c_enter",
            "handler",
            "c_exit", "b_exit", "a_exit",
        ]


# ═══════════════════════════════════════════════════════════════════════════════
# Integration 5: Mixed Triggers — same Application, HTTP + Event + CLI
# ═══════════════════════════════════════════════════════════════════════════════


class TestMixedTriggers:
    """event_compile only picks up EventTrigger routes, ignores others."""

    def test_event_compile_filters_by_trigger_type(self):
        from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger
        from emergent.wire.axis.surface.triggers.cli import CLITrigger

        runner = _runner()
        app = application().mount(
            # HTTP route — should be ignored
            endpoint(runner).expose(
                HTTPRouteTrigger("GET", "/orders"),
                rrc(ProcessOrderRequest, ProcessOrderResponse),
            ),
            # CLI command — should be ignored
            endpoint(runner).expose(
                CLITrigger("process-order"),
                rrc(ProcessOrderRequest, ProcessOrderResponse),
            ),
            # Event trigger — should be picked up
            endpoint(runner).expose(
                EventTrigger(OrderCreated),
                rrc(ProcessOrderRequest, ProcessOrderResponse),
            ),
            # Another event trigger
            endpoint(runner).expose(
                EventTrigger(UserSignedUp),
                delegate(lambda ev: f"user:{ev.user_id}"),
            ),
        )
        dispatcher = event_compile(app)
        # Only event routes should be present
        assert OrderCreated in dispatcher.routes
        assert UserSignedUp in dispatcher.routes
        assert len(dispatcher.routes) == 2

    @pytest.mark.asyncio
    async def test_mixed_app_event_dispatch_works(self):
        from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger

        runner = _runner()
        app = application().mount(
            endpoint(runner).expose(
                HTTPRouteTrigger("GET", "/orders"),
                rrc(ProcessOrderRequest, ProcessOrderResponse),
            ),
            endpoint(runner).expose(
                EventTrigger(OrderCreated),
                rrc(ProcessOrderRequest, ProcessOrderResponse),
            ),
        )
        dispatcher = event_compile(app)
        results = await dispatcher.dispatch(OrderCreated(order_id=99, total=10.0))
        assert len(results) == 1
        assert isinstance(results[0], ProcessOrderResponse)
        assert "99" in results[0].message


# ═══════════════════════════════════════════════════════════════════════════════
# Integration 6: Multi-event-type + multi-handler fan-out
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class OrderShipped:
    order_id: int
    carrier: str


@dataclass
class OrderCancelled:
    order_id: int
    reason: str


class TestMultiEventFanOut:
    """Multiple event types, multiple handlers per type, per-handler enrichers."""

    @pytest.mark.asyncio
    async def test_fan_out_routing(self):
        notification_log: list[str] = []
        analytics_log: list[str] = []
        shipping_log: list[str] = []
        cancel_log: list[str] = []

        async def notify_order(event: OrderCreated) -> str:
            msg = f"notify:{event.order_id}"
            notification_log.append(msg)
            return msg

        async def track_order(event: OrderCreated) -> str:
            msg = f"analytics:{event.order_id}"
            analytics_log.append(msg)
            return msg

        async def handle_shipped(event: OrderShipped) -> str:
            msg = f"shipped:{event.order_id}:{event.carrier}"
            shipping_log.append(msg)
            return msg

        async def handle_cancelled(event: OrderCancelled) -> str:
            msg = f"cancelled:{event.order_id}:{event.reason}"
            cancel_log.append(msg)
            return msg

        runner = _runner()
        app = application().mount(
            # OrderCreated — 2 handlers
            endpoint(runner).expose(
                EventTrigger(OrderCreated),
                delegate(notify_order),
            ),
            endpoint(runner).expose(
                EventTrigger(OrderCreated),
                delegate(track_order),
            ),
            # OrderShipped — 1 handler
            endpoint(runner).expose(
                EventTrigger(OrderShipped),
                delegate(handle_shipped),
            ),
            # OrderCancelled — 1 handler
            endpoint(runner).expose(
                EventTrigger(OrderCancelled),
                delegate(handle_cancelled),
            ),
        )
        dispatcher = event_compile(app)

        # Dispatch OrderCreated → 2 handlers
        results = await dispatcher.dispatch(OrderCreated(order_id=1, total=100.0))
        assert len(results) == 2
        assert set(results) == {"notify:1", "analytics:1"}
        assert len(notification_log) == 1
        assert len(analytics_log) == 1

        # Dispatch OrderShipped → 1 handler
        results = await dispatcher.dispatch(OrderShipped(order_id=1, carrier="FedEx"))
        assert len(results) == 1
        assert results[0] == "shipped:1:FedEx"

        # Dispatch OrderCancelled → 1 handler
        results = await dispatcher.dispatch(OrderCancelled(order_id=2, reason="fraud"))
        assert len(results) == 1
        assert results[0] == "cancelled:2:fraud"

        # Unknown event → empty
        results = await dispatcher.dispatch(UserSignedUp(user_id=99, email="x@y.com"))
        assert results == ()

    @pytest.mark.asyncio
    async def test_per_handler_enricher_isolation(self):
        """Each handler has its own enricher — they don't interfere."""
        log_a: list[str] = []
        log_b: list[str] = []

        async def handler_a(event: OrderCreated) -> str:
            return "a"

        async def handler_b(event: OrderCreated) -> str:
            return "b"

        runner = _runner()
        app = application().mount(
            endpoint(runner).expose(
                EventTrigger(OrderCreated),
                delegate(handler_a),
                TrackEnricher(name="enrich_a", log=log_a),
            ),
            endpoint(runner).expose(
                EventTrigger(OrderCreated),
                delegate(handler_b),
                TrackEnricher(name="enrich_b", log=log_b),
            ),
        )
        dispatcher = event_compile(app)
        results = await dispatcher.dispatch(OrderCreated(order_id=1, total=1.0))
        assert len(results) == 2
        # Enricher A only ran for handler A
        assert log_a == ["enrich_a_enter", "enrich_a_exit"]
        # Enricher B only ran for handler B
        assert log_b == ["enrich_b_enter", "enrich_b_exit"]


# ═══════════════════════════════════════════════════════════════════════════════
# Integration 7: ScopeFamily lifecycle — App-tier nodes composed once
# ═══════════════════════════════════════════════════════════════════════════════


class TestScopeFamilyLifecycle:
    """App-tier nodes are composed once, not per-dispatch."""

    @pytest.mark.asyncio
    async def test_app_tier_composed_once(self):
        from nodnod import scalar_node

        compose_count = 0

        @dataclass(frozen=True, slots=True)
        class AppConfig:
            env: str

        @scalar_node
        class AppConfigNode:
            """nodnod-compatible node — composed at App tier."""

            @classmethod
            def __compose__(cls) -> AppConfig:
                nonlocal compose_count
                compose_count += 1
                return AppConfig(env="production")

        received_events: list[OrderCreated] = []

        async def handler(event: OrderCreated) -> str:
            received_events.append(event)
            return f"handled:{event.order_id}"

        runner = _runner()
        family: ScopeFamily[Tier] = ScopeFamily[Tier]().bind(App, AppConfigNode)

        app = application().mount(
            endpoint(runner).expose(
                EventTrigger(OrderCreated),
                delegate(handler),
            )
        )
        dispatcher = event_compile(app, family=family)
        async with dispatcher:
            r1 = await dispatcher.dispatch(OrderCreated(order_id=1, total=10.0))
            r2 = await dispatcher.dispatch(OrderCreated(order_id=2, total=20.0))
            r3 = await dispatcher.dispatch(OrderCreated(order_id=3, total=30.0))

        assert len(r1) == 1
        assert len(r2) == 1
        assert len(r3) == 1
        assert r1[0] == "handled:1"
        assert r2[0] == "handled:2"
        assert r3[0] == "handled:3"
        # App-tier node composed exactly once during __aenter__
        assert compose_count == 1

    @pytest.mark.asyncio
    async def test_family_no_app_bindings_still_works(self):
        """Empty family should still work — no nodes to compose."""
        async def handler(event: OrderCreated) -> str:
            return f"ok:{event.order_id}"

        runner = _runner()
        family: ScopeFamily[Tier] = ScopeFamily[Tier]()

        app = application().mount(
            endpoint(runner).expose(
                EventTrigger(OrderCreated),
                delegate(handler),
            )
        )
        dispatcher = event_compile(app, family=family)
        async with dispatcher:
            results = await dispatcher.dispatch(OrderCreated(order_id=5, total=1.0))
        assert results[0] == "ok:5"


# ═══════════════════════════════════════════════════════════════════════════════
# Integration 8: User inject — dispatch with external scope injection
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class DBConn:
    url: str


class TestUserInject:
    """User-provided inject lambda merges with event inject."""

    @pytest.mark.asyncio
    async def test_user_inject_reaches_delegate_handler(self):
        received_db: list[DBConn] = []

        async def handler(event: OrderCreated, db: DBConn) -> str:
            received_db.append(db)
            return f"order:{event.order_id}:db={db.url}"

        runner = _runner()
        app = application().mount(
            endpoint(runner).expose(
                EventTrigger(OrderCreated),
                delegate(handler),
            )
        )
        mock_db = DBConn(url="sqlite://test.db")
        dispatcher = event_compile(app)
        results = await dispatcher.dispatch(
            OrderCreated(order_id=10, total=5.0),
            inject=lambda scope: scope.inject(DBConn, mock_db),
        )
        assert len(results) == 1
        assert "order:10" in results[0]
        assert "sqlite://test.db" in results[0]
        assert len(received_db) == 1
        assert received_db[0] is mock_db

    @pytest.mark.asyncio
    async def test_user_inject_with_rrc(self):
        """User inject available in RRC scope — enrichers can see it."""
        from emergent.wire.axis.surface.enrichers import Validate

        runner = _validate_runner()
        app = application().mount(
            endpoint(runner).expose(
                EventTrigger(OrderCreated),
                rrc(ValidateOrderRequest, ValidateOrderResponse),
                Validate(
                    extract=lambda scope: scope.retrieve(DBConn),
                    predicate=lambda result: result is not None,
                    on_invalid=lambda _: ValidateOrderResponse(message="no_db"),
                ),
            )
        )
        dispatcher = event_compile(app)

        # With inject — db is in scope → validation passes
        results = await dispatcher.dispatch(
            OrderCreated(order_id=1, total=10.0),
            inject=lambda scope: scope.inject(DBConn, DBConn(url="pg://prod")),
        )
        assert len(results) == 1
        assert "validated:1" in results[0].message


# ═══════════════════════════════════════════════════════════════════════════════
# Integration 9: Tracing — Axes.traced() captures scan/wrap events
# ═══════════════════════════════════════════════════════════════════════════════


class TestTracing:
    """Axes.traced() captures ScanEvent and WrapEvent during compilation."""

    def test_traced_captures_scan_and_wrap_events(self):
        from emergent.wire.compile._trace import ListCollector, ScanEvent, WrapEvent

        collector = ListCollector()
        runner = _runner()
        app = application().mount(
            endpoint(runner).expose(
                EventTrigger(OrderCreated),
                rrc(ProcessOrderRequest, ProcessOrderResponse),
            ),
            endpoint(runner).expose(
                EventTrigger(UserSignedUp),
                delegate(lambda ev: f"user:{ev.user_id}"),
            ),
        )
        axes = Axes.traced(collector)
        dispatcher = event_compile(app, axes=axes)

        # Should have 2 scan events (one per matched exposure)
        assert len(collector.scan_events) == 2

        # Check scan events
        rrc_scan = [e for e in collector.scan_events if e.codec_type == "RequestResponseCodec"]
        delegate_scan = [e for e in collector.scan_events if e.codec_type == "DelegateCodec"]
        assert len(rrc_scan) == 1
        assert len(delegate_scan) == 1
        assert "OrderCreated" in rrc_scan[0].trigger_repr
        assert "UserSignedUp" in delegate_scan[0].trigger_repr

        # Should have 2 wrap events
        assert len(collector.wrap_events) == 2
        wrap_types = {e.codec_type for e in collector.wrap_events}
        assert "RequestResponseCodec" in wrap_types
        assert "DelegateCodec" in wrap_types

        # All wrap events produce EventRoute
        for we in collector.wrap_events:
            assert we.result_type == "EventRoute"

    def test_traced_captures_capabilities(self):
        from emergent.wire.compile._trace import ListCollector

        collector = ListCollector()
        runner = _runner()
        app = application().mount(
            endpoint(runner).expose(
                EventTrigger(OrderCreated),
                rrc(ProcessOrderRequest, ProcessOrderResponse),
                Passthrough(),
            ),
        )
        axes = Axes.traced(collector)
        event_compile(app, axes=axes)

        assert len(collector.scan_events) == 1
        assert "Passthrough" in collector.scan_events[0].capabilities

    def test_default_axes_no_trace(self):
        """Axes.default() has no trace — zero overhead."""
        axes = Axes.default()
        assert axes.trace is None

    def test_traced_creates_list_collector_by_default(self):
        from emergent.wire.compile._trace import ListCollector

        axes = Axes.traced()
        assert isinstance(axes.trace, ListCollector)


# ═══════════════════════════════════════════════════════════════════════════════
# Integration 10: E2E — realistic order processing pipeline
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Timestamp:
    value: str


@dataclass(frozen=True, slots=True)
class CreateOrderOp(Op[str, str]):
    order_id: int
    total: float


@dataclass(frozen=True, slots=True)
class CreateOrderRequest:
    order_id: int
    total: float

    def to_domain(self) -> CreateOrderOp:
        return CreateOrderOp(order_id=self.order_id, total=self.total)


@dataclass(frozen=True, slots=True)
class CreateOrderResponse:
    message: str

    @classmethod
    def from_domain(cls, dom: Result[str, str]) -> CreateOrderResponse:
        match dom:
            case Ok(value):
                return cls(message=value)
            case _:
                return cls(message="error")


@dataclass
class OrderPlaced:
    order_id: int
    total: float


class TestE2EPipeline:
    """Full end-to-end: domain ops + RRC codec + enrichers + response transforms + dispatch lifecycle."""

    @pytest.mark.asyncio
    async def test_full_pipeline(self):
        from emergent.wire.axis.surface.enrichers import Inject
        from emergent.wire.axis.surface.transforms import AsDict

        # Build ops runner
        async def handle_create_order(req: CreateOrderOp) -> Result[str, str]:
            return Ok(f"order#{req.order_id}:total={req.total}")

        runner = _ops().on(CreateOrderOp, handle_create_order).compile()

        # Notification handler
        notifications: list[str] = []

        async def notify(event: OrderPlaced) -> str:
            msg = f"notification:order#{event.order_id}"
            notifications.append(msg)
            return msg

        ts = Timestamp(value="2024-01-01T00:00:00Z")

        app = application().mount(
            # RRC handler with enrichers + response transform
            endpoint(runner).expose(
                EventTrigger(OrderPlaced),
                rrc(CreateOrderRequest, CreateOrderResponse),
                Inject(type=Timestamp, value=ts),
                AsDict(),
            ),
            # Delegate handler for notifications
            endpoint(runner).expose(
                EventTrigger(OrderPlaced),
                delegate(notify),
            ),
        )

        family: ScopeFamily[Tier] = ScopeFamily[Tier]()
        dispatcher = event_compile(app, family=family)

        async with dispatcher:
            results = await dispatcher.dispatch(
                OrderPlaced(order_id=42, total=199.99)
            )

        assert len(results) == 2

        # RRC result is a dict (due to AsDict transform)
        dict_results = [r for r in results if isinstance(r, dict)]
        str_results = [r for r in results if isinstance(r, str)]

        assert len(dict_results) == 1
        assert len(str_results) == 1

        # Verify RRC pipeline
        order_dict = dict_results[0]
        assert "message" in order_dict
        assert "order#42" in order_dict["message"]
        assert "199.99" in order_dict["message"]

        # Verify delegate notification
        assert str_results[0] == "notification:order#42"
        assert len(notifications) == 1

    @pytest.mark.asyncio
    async def test_multi_dispatch_with_lifecycle(self):
        from emergent.wire.axis.surface.enrichers import Inject
        from emergent.wire.axis.surface.transforms import Transform

        async def handle_create_order(req: CreateOrderOp) -> Result[str, str]:
            return Ok(f"created:{req.order_id}")

        runner = _ops().on(CreateOrderOp, handle_create_order).compile()

        app = application().mount(
            endpoint(runner).expose(
                EventTrigger(OrderPlaced),
                rrc(CreateOrderRequest, CreateOrderResponse),
                Inject(type=Config, value=Config(env="prod", max_retries=5)),
                Transform(fn=lambda r: {"response": r, "env": "prod"}),
            ),
        )

        family: ScopeFamily[Tier] = ScopeFamily[Tier]()
        dispatcher = event_compile(app, family=family)

        async with dispatcher:
            # Multiple dispatches within same lifecycle
            r1 = await dispatcher.dispatch(OrderPlaced(order_id=1, total=10.0))
            r2 = await dispatcher.dispatch(OrderPlaced(order_id=2, total=20.0))
            r3 = await dispatcher.dispatch(OrderPlaced(order_id=3, total=30.0))

        for i, results in enumerate([r1, r2, r3], start=1):
            assert len(results) == 1
            envelope = results[0]
            assert isinstance(envelope, dict)
            assert envelope["env"] == "prod"
            assert isinstance(envelope["response"], CreateOrderResponse)
            assert f"created:{i}" in envelope["response"].message

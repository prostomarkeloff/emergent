"""Tests for surface axis — endpoint, application, stack, scan, codecs, transforms, enrichers."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Self

import pytest

from emergent.ops import ops as _ops
from emergent.wire.axis.surface._endpoint import Endpoint, endpoint
from emergent.wire.axis.surface._app import Application, application
from emergent.wire.axis.surface._stack import AppStack, app_stack
from emergent.wire.axis.surface._handler import Handler
from emergent.wire.axis.surface._scan import scan, scan_endpoint, scan_stack, StackView
from emergent.wire.axis.surface._types import Exposure
from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger
from emergent.wire.axis.surface.triggers.cli import CLITrigger
from emergent.wire.axis.surface.codecs.rrc import RequestResponseCodec, rrc
from emergent.wire.axis.surface.codecs.delegate import DelegateCodec, delegate
from emergent.wire.axis.surface.codecs.immediate import (
    ImmediateCodec,
    ImmediateFactoryCodec,
    immediate,
    immediate_factory,
)
from emergent.wire.axis.surface.codecs.stateful import (
    Done,
    TransitionResult,
    transition,
    get_transitions,
    has_transitions,
    parse_transition_result,
    stateful,
    StatefulCodec,
)
from emergent.wire.axis.surface.transforms._trigger import URLPath, Prefix, StripPrefix
from emergent.wire.axis.surface.transforms._response import AsDict, AsStr, Transform
from emergent.wire.axis.surface.enrichers._base import ScopeEnricher
from emergent.wire.axis.surface.enrichers._impl import Inject, chain_enrichers
from emergent.wire.axis.surface.capabilities._helpers import (
    find_capability,
    find_all_capabilities,
    has_capability,
    merge_capabilities,
    override_capability,
    remove_capability,
    deduplicate_capabilities,
    filter_by_protocol,
)
from emergent.wire.axis.surface.capabilities._base import SurfaceCapability
from emergent.wire.axis.surface.transforms._base import ResponseTransform

from kungfu import Some, Nothing


# ---------------------------------------------------------------------------
# Helpers / Fixtures
# ---------------------------------------------------------------------------


def _runner():
    return _ops().compile()


@dataclass
class Req:
    pass


@dataclass
class Resp:
    pass


@dataclass(frozen=True)
class MockCap:
    name: str = "test"


@dataclass(frozen=True)
class AnotherCap:
    value: int = 0


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Endpoint builder
# ═══════════════════════════════════════════════════════════════════════════════


class TestEndpoint:
    def test_endpoint_factory_creates_empty_endpoint(self):
        ep = endpoint(_runner())
        assert isinstance(ep, Endpoint)
        assert ep.exposures == []

    def test_expose_returns_new_endpoint_with_exposure(self):
        runner = _runner()
        trigger = HTTPRouteTrigger("GET", "/users")
        codec = rrc(Req, Resp)
        ep = endpoint(runner).expose(trigger, codec)

        assert len(ep.exposures) == 1
        assert ep.exposures[0].trigger is trigger
        assert ep.exposures[0].codec is codec
        assert ep.runner is runner

    def test_expose_is_immutable(self):
        runner = _runner()
        ep1 = endpoint(runner)
        ep2 = ep1.expose(HTTPRouteTrigger("GET", "/a"), rrc(Req, Resp))
        ep3 = ep2.expose(HTTPRouteTrigger("POST", "/b"), rrc(Req, Resp))

        assert len(ep1.exposures) == 0
        assert len(ep2.exposures) == 1
        assert len(ep3.exposures) == 2

    def test_expose_accumulates_multiple_exposures(self):
        http_trigger = HTTPRouteTrigger("GET", "/users")
        cli_trigger = CLITrigger("list-users")
        codec = rrc(Req, Resp)

        ep = (
            endpoint(_runner())
            .expose(http_trigger, codec)
            .expose(cli_trigger, codec)
        )
        assert len(ep.exposures) == 2
        assert isinstance(ep.exposures[0].trigger, HTTPRouteTrigger)
        assert isinstance(ep.exposures[1].trigger, CLITrigger)

    def test_expose_with_capabilities(self):
        cap = MockCap("auth")
        ep = endpoint(_runner()).expose(
            HTTPRouteTrigger("GET", "/secure"),
            rrc(Req, Resp),
            cap,
        )
        assert len(ep.exposures) == 1
        assert ep.exposures[0].capabilities == (cap,)

    def test_expose_with_multiple_capabilities(self):
        cap1 = MockCap("auth")
        cap2 = AnotherCap(42)
        ep = endpoint(_runner()).expose(
            HTTPRouteTrigger("GET", "/secure"),
            rrc(Req, Resp),
            cap1,
            cap2,
        )
        assert ep.exposures[0].capabilities == (cap1, cap2)

    def test_from_runner_classmethod(self):
        runner = _runner()
        ep = Endpoint.from_runner(runner)
        assert ep.runner is runner
        assert ep.exposures == []


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Application
# ═══════════════════════════════════════════════════════════════════════════════


class TestApplication:
    def test_application_factory_creates_empty(self):
        app = application()
        assert isinstance(app, Application)
        assert app.endpoints == []
        assert app.capabilities == ()

    def test_application_with_global_capabilities(self):
        cap = MockCap("cors")
        app = application(capabilities=(cap,))
        assert app.capabilities == (cap,)

    def test_mount_endpoints(self):
        ep1 = endpoint(_runner()).expose(
            HTTPRouteTrigger("GET", "/a"), rrc(Req, Resp)
        )
        ep2 = endpoint(_runner()).expose(
            HTTPRouteTrigger("POST", "/b"), rrc(Req, Resp)
        )
        app = application().mount(ep1, ep2)
        assert len(app.endpoints) == 2

    def test_mount_is_immutable(self):
        ep = endpoint(_runner()).expose(
            HTTPRouteTrigger("GET", "/a"), rrc(Req, Resp)
        )
        app1 = application()
        app2 = app1.mount(ep)
        assert len(app1.endpoints) == 0
        assert len(app2.endpoints) == 1

    def test_mount_preserves_capabilities(self):
        cap = MockCap("cors")
        ep = endpoint(_runner()).expose(
            HTTPRouteTrigger("GET", "/a"), rrc(Req, Resp)
        )
        app = application(capabilities=(cap,)).mount(ep)
        assert app.capabilities == (cap,)
        assert len(app.endpoints) == 1

    def test_with_capabilities_adds(self):
        cap1 = MockCap("cors")
        cap2 = AnotherCap(1)
        app = application(capabilities=(cap1,)).with_capabilities(cap2)
        assert app.capabilities == (cap1, cap2)

    def test_with_capabilities_is_immutable(self):
        app1 = application()
        app2 = app1.with_capabilities(MockCap("x"))
        assert app1.capabilities == ()
        assert len(app2.capabilities) == 1

    def test_add_operator_merges_endpoints_and_capabilities(self):
        ep1 = endpoint(_runner()).expose(
            HTTPRouteTrigger("GET", "/a"), rrc(Req, Resp)
        )
        ep2 = endpoint(_runner()).expose(
            HTTPRouteTrigger("POST", "/b"), rrc(Req, Resp)
        )
        cap1 = MockCap("cors")
        cap2 = AnotherCap(1)

        app1 = application(capabilities=(cap1,)).mount(ep1)
        app2 = application(capabilities=(cap2,)).mount(ep2)
        combined = app1 + app2

        assert len(combined.endpoints) == 2
        assert combined.capabilities == (cap1, cap2)

    def test_merge_multiple_apps(self):
        ep1 = endpoint(_runner()).expose(
            HTTPRouteTrigger("GET", "/a"), rrc(Req, Resp)
        )
        ep2 = endpoint(_runner()).expose(
            HTTPRouteTrigger("GET", "/b"), rrc(Req, Resp)
        )
        ep3 = endpoint(_runner()).expose(
            HTTPRouteTrigger("GET", "/c"), rrc(Req, Resp)
        )
        app1 = application().mount(ep1)
        app2 = application(capabilities=(MockCap("x"),)).mount(ep2)
        app3 = application(capabilities=(AnotherCap(1),)).mount(ep3)

        merged = app1.merge(app2, app3)
        assert len(merged.endpoints) == 3
        assert len(merged.capabilities) == 2

    def test_merge_no_args_returns_copy(self):
        app = application(capabilities=(MockCap("x"),))
        merged = app.merge()
        assert merged.capabilities == app.capabilities
        assert merged.endpoints == app.endpoints


# ═══════════════════════════════════════════════════════════════════════════════
# 3. AppStack
# ═══════════════════════════════════════════════════════════════════════════════


class TestAppStack:
    def test_app_stack_factory_creates_empty(self):
        stack = app_stack()
        assert isinstance(stack, AppStack)
        assert stack.root_app.endpoints == []
        assert stack.mounts == {}

    def test_root_sets_root_application(self):
        ep = endpoint(_runner()).expose(
            HTTPRouteTrigger("GET", "/scan"), rrc(Req, Resp)
        )
        app = application().mount(ep)
        stack = app_stack().root(app)
        assert len(stack.root_app.endpoints) == 1

    def test_root_is_immutable(self):
        ep = endpoint(_runner()).expose(
            HTTPRouteTrigger("GET", "/a"), rrc(Req, Resp)
        )
        stack1 = app_stack()
        stack2 = stack1.root(application().mount(ep))
        assert len(stack1.root_app.endpoints) == 0
        assert len(stack2.root_app.endpoints) == 1

    def test_mount_application_at_prefix(self):
        sub = application().mount(
            endpoint(_runner()).expose(CLITrigger("op"), rrc(Req, Resp))
        )
        stack = app_stack().mount("new", sub)
        assert "new" in stack.mounts
        assert isinstance(stack.mounts["new"], Application)

    def test_mount_nested_stack(self):
        inner_stack = app_stack().root(
            application().mount(
                endpoint(_runner()).expose(CLITrigger("inner"), rrc(Req, Resp))
            )
        )
        outer = app_stack().mount("nested", inner_stack)
        assert isinstance(outer.mounts["nested"], AppStack)

    def test_mount_is_immutable(self):
        sub = application()
        stack1 = app_stack()
        stack2 = stack1.mount("sub", sub)
        assert stack1.mounts == {}
        assert "sub" in stack2.mounts

    def test_chained_root_and_mount(self):
        root_app = application().mount(
            endpoint(_runner()).expose(CLITrigger("scan"), rrc(Req, Resp))
        )
        sub_app = application().mount(
            endpoint(_runner()).expose(CLITrigger("op"), rrc(Req, Resp))
        )
        stack = app_stack().root(root_app).mount("new", sub_app)
        assert len(stack.root_app.endpoints) == 1
        assert "new" in stack.mounts

    def test_multiple_root_calls_accumulate(self):
        ep1 = endpoint(_runner()).expose(CLITrigger("a"), rrc(Req, Resp))
        ep2 = endpoint(_runner()).expose(CLITrigger("b"), rrc(Req, Resp))
        stack = (
            app_stack()
            .root(application().mount(ep1))
            .root(application().mount(ep2))
        )
        assert len(stack.root_app.endpoints) == 2


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Scan functions
# ═══════════════════════════════════════════════════════════════════════════════


class TestScan:
    def test_scan_endpoint_by_trigger_type(self):
        ep = (
            endpoint(_runner())
            .expose(HTTPRouteTrigger("GET", "/users"), rrc(Req, Resp))
            .expose(CLITrigger("list"), rrc(Req, Resp))
        )
        http_pairs = scan_endpoint(ep, HTTPRouteTrigger)
        assert len(http_pairs) == 1
        trigger, handler = http_pairs[0]
        assert isinstance(trigger, HTTPRouteTrigger)
        assert trigger.path == "/users"
        assert isinstance(handler, Handler)

    def test_scan_endpoint_by_trigger_and_codec(self):
        ep = (
            endpoint(_runner())
            .expose(HTTPRouteTrigger("GET", "/a"), rrc(Req, Resp))
            .expose(HTTPRouteTrigger("GET", "/b"), delegate(lambda: None))
        )
        pairs = scan_endpoint(ep, HTTPRouteTrigger, RequestResponseCodec)
        assert len(pairs) == 1
        assert pairs[0][0].path == "/a"

    def test_scan_endpoint_no_match(self):
        ep = endpoint(_runner()).expose(
            HTTPRouteTrigger("GET", "/a"), rrc(Req, Resp)
        )
        pairs = scan_endpoint(ep, CLITrigger)
        assert pairs == []

    def test_scan_app(self):
        ep1 = endpoint(_runner()).expose(
            HTTPRouteTrigger("GET", "/a"), rrc(Req, Resp)
        )
        ep2 = endpoint(_runner()).expose(
            HTTPRouteTrigger("POST", "/b"), rrc(Req, Resp)
        )
        ep3 = endpoint(_runner()).expose(
            CLITrigger("x"), rrc(Req, Resp)
        )
        app = application().mount(ep1, ep2, ep3)

        http_pairs = scan(app, HTTPRouteTrigger)
        assert len(http_pairs) == 2

        cli_pairs = scan(app, CLITrigger)
        assert len(cli_pairs) == 1

    def test_scan_app_with_codec_filter(self):
        ep1 = endpoint(_runner()).expose(
            HTTPRouteTrigger("GET", "/rrc"), rrc(Req, Resp)
        )
        ep2 = endpoint(_runner()).expose(
            HTTPRouteTrigger("GET", "/delegate"), delegate(lambda: None)
        )
        app = application().mount(ep1, ep2)

        rrc_pairs = scan(app, HTTPRouteTrigger, RequestResponseCodec)
        assert len(rrc_pairs) == 1

        delegate_pairs = scan(app, HTTPRouteTrigger, DelegateCodec)
        assert len(delegate_pairs) == 1

    def test_scan_empty_app(self):
        app = application()
        pairs = scan(app, HTTPRouteTrigger)
        assert pairs == []

    def test_handler_carries_codec_runner_capabilities(self):
        runner = _runner()
        cap = MockCap("auth")
        codec = rrc(Req, Resp)
        ep = endpoint(runner).expose(
            HTTPRouteTrigger("GET", "/x"), codec, cap,
        )
        pairs = scan_endpoint(ep, HTTPRouteTrigger)
        _, handler = pairs[0]
        assert handler.codec is codec
        assert handler.runner is runner
        assert handler.capabilities == (cap,)


class TestScanStack:
    def test_scan_stack_root(self):
        ep = endpoint(_runner()).expose(
            CLITrigger("scan"), rrc(Req, Resp)
        )
        stack = app_stack().root(application().mount(ep))
        view = scan_stack(stack, CLITrigger)

        assert isinstance(view, StackView)
        assert len(view.root) == 1
        assert view.mounts == {}

    def test_scan_stack_with_mounts(self):
        root_ep = endpoint(_runner()).expose(
            CLITrigger("scan"), rrc(Req, Resp)
        )
        sub_ep = endpoint(_runner()).expose(
            CLITrigger("op"), rrc(Req, Resp)
        )
        stack = (
            app_stack()
            .root(application().mount(root_ep))
            .mount("new", application().mount(sub_ep))
        )
        view = scan_stack(stack, CLITrigger)
        assert len(view.root) == 1
        assert "new" in view.mounts
        mount_pairs = view.mounts["new"]
        assert isinstance(mount_pairs, list)
        assert len(mount_pairs) == 1

    def test_scan_stack_nested_stacks(self):
        inner_ep = endpoint(_runner()).expose(
            CLITrigger("deep"), rrc(Req, Resp)
        )
        inner_stack = app_stack().root(application().mount(inner_ep))
        outer_stack = app_stack().mount("nested", inner_stack)

        view = scan_stack(outer_stack, CLITrigger)
        assert "nested" in view.mounts
        nested_view = view.mounts["nested"]
        assert isinstance(nested_view, StackView)
        assert len(nested_view.root) == 1

    def test_scan_stack_filters_by_trigger(self):
        ep = endpoint(_runner()).expose(
            HTTPRouteTrigger("GET", "/a"), rrc(Req, Resp)
        )
        stack = app_stack().root(application().mount(ep))

        cli_view = scan_stack(stack, CLITrigger)
        assert cli_view.root == []

        http_view = scan_stack(stack, HTTPRouteTrigger)
        assert len(http_view.root) == 1


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Handler
# ═══════════════════════════════════════════════════════════════════════════════


class TestHandler:
    def test_handler_dataclass(self):
        runner = _runner()
        codec = rrc(Req, Resp)
        h = Handler(codec=codec, runner=runner)
        assert h.codec is codec
        assert h.runner is runner
        assert h.capabilities == ()

    def test_handler_with_capabilities(self):
        cap = MockCap("x")
        h = Handler(codec=rrc(Req, Resp), runner=_runner(), capabilities=(cap,))
        assert h.capabilities == (cap,)


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Codecs — RRC, Delegate, Immediate
# ═══════════════════════════════════════════════════════════════════════════════


class TestRRCCodec:
    def test_rrc_factory(self):
        codec = rrc(Req, Resp)
        assert isinstance(codec, RequestResponseCodec)
        assert codec.request is Req
        assert codec.response is Resp

    def test_rrc_frozen(self):
        codec = rrc(Req, Resp)
        with pytest.raises(AttributeError):
            codec.request = Req  # type: ignore[misc]


class TestDelegateCodec:
    def test_delegate_basic(self):
        def handler():
            return "result"

        codec = delegate(handler)
        assert isinstance(codec, DelegateCodec)
        assert codec.handler is handler
        assert isinstance(codec.response, Nothing)

    def test_delegate_with_response(self):
        def handler():
            return Resp()

        codec = delegate(handler, response=Resp)
        assert isinstance(codec.response, Some)
        assert codec.response.unwrap() is Resp

    def test_delegate_frozen(self):
        codec = delegate(lambda: None)
        with pytest.raises(AttributeError):
            codec.handler = None  # type: ignore[misc]


class TestImmediateCodec:
    def test_immediate_with_producing_class(self):
        @dataclass
        class HelpResponse:
            text: str = "Help!"

            @classmethod
            def produce(cls) -> Self:
                return cls(text="Help!")

        codec = immediate(HelpResponse)
        assert isinstance(codec, ImmediateCodec)
        assert codec.response is HelpResponse

        # Verify the produce protocol works
        result = codec.response.produce()
        assert result.text == "Help!"

    def test_immediate_factory_with_lambda(self):
        codec = immediate_factory(lambda: {"text": "hello"})
        assert isinstance(codec, ImmediateFactoryCodec)
        assert codec.factory() == {"text": "hello"}

    def test_immediate_factory_closure(self):
        captured = "dynamic text"
        codec = immediate_factory(lambda: captured)
        assert codec.factory() == "dynamic text"

    def test_immediate_frozen(self):
        @dataclass
        class X:
            @classmethod
            def produce(cls):
                return cls()

        codec = immediate(X)
        with pytest.raises(AttributeError):
            codec.response = X  # type: ignore[misc]


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Stateful codec
# ═══════════════════════════════════════════════════════════════════════════════


class TestStatefulTransition:
    def test_transition_decorator_marks_method(self):
        @dataclass
        class Flow:
            @transition
            async def step(self):
                pass

        assert getattr(Flow.step, "__is_transition__", False) is True

    def test_get_transitions_finds_decorated(self):
        @dataclass
        class Flow:
            @transition
            async def http(self):
                pass

            @transition
            async def cli(self):
                pass

        transitions = get_transitions(Flow)
        assert len(transitions) == 2

    def test_get_transitions_fallback_to_dunder(self):
        @dataclass
        class Flow:
            async def __transition__(self):
                pass

        transitions = get_transitions(Flow)
        assert len(transitions) == 1

    def test_get_transitions_empty_if_none(self):
        @dataclass
        class Flow:
            pass

        transitions = get_transitions(Flow)
        assert transitions == []

    def test_has_transitions_true(self):
        @dataclass
        class Flow:
            @transition
            async def step(self):
                pass

        assert has_transitions(Flow) is True

    def test_has_transitions_false(self):
        @dataclass
        class Flow:
            pass

        assert has_transitions(Flow) is False


class TestDone:
    def test_done_is_frozen_dataclass(self):
        d = Done()
        assert isinstance(d, Done)
        with pytest.raises((AttributeError, TypeError)):
            d.x = 1  # type: ignore[attr-defined]


class TestParseTransitionResult:
    def test_state_only(self):
        @dataclass
        class S:
            x: int = 1

        state = S()
        result = parse_transition_result(state)
        assert isinstance(result, TransitionResult)
        assert result.state_or_done is state
        assert isinstance(result.response, Nothing)
        assert result.is_terminal is False

    def test_done_terminal(self):
        done = Done()
        result = parse_transition_result(done)
        assert result.state_or_done is done
        assert isinstance(result.response, Nothing)
        assert result.is_terminal is True

    def test_state_with_response(self):
        @dataclass
        class S:
            x: int = 1

        state = S()
        result = parse_transition_result((state, "intermediate"))
        assert result.state_or_done is state
        assert isinstance(result.response, Some)
        assert result.response.unwrap() == "intermediate"
        assert result.is_terminal is False

    def test_done_with_response(self):
        done = Done()
        result = parse_transition_result((done, "final"))
        assert isinstance(result.state_or_done, Done)
        assert isinstance(result.response, Some)
        assert result.response.unwrap() == "final"
        assert result.is_terminal is True


class TestStatefulBuilder:
    def test_build_requires_key(self):
        @dataclass
        class Flow:
            async def __transition__(self):
                pass

            def to_domain(self):
                pass

        with pytest.raises(ValueError, match="key_node is required"):
            stateful(Flow, Resp).build()

    def test_build_requires_transitions(self):
        @dataclass
        class Flow:
            def to_domain(self):
                pass

        class FakeKey:
            pass

        with pytest.raises(ValueError, match="must define __transition__"):
            stateful(Flow, Resp).key(FakeKey).build()

    def test_build_requires_to_domain(self):
        @dataclass
        class Flow:
            @transition
            async def step(self):
                pass

        class FakeKey:
            pass

        with pytest.raises(ValueError, match="must define to_domain"):
            stateful(Flow, Resp).key(FakeKey).build()

    def test_build_success(self):
        @dataclass
        class Flow:
            @transition
            async def step(self):
                pass

            def to_domain(self):
                pass

        class FakeKey:
            pass

        codec = stateful(Flow, Resp).key(FakeKey).build()
        assert isinstance(codec, StatefulCodec)
        assert codec.flow is Flow
        assert codec.response is Resp
        assert codec.key_node is FakeKey


# ═══════════════════════════════════════════════════════════════════════════════
# 8. Transforms
# ═══════════════════════════════════════════════════════════════════════════════


class TestURLPath:
    def test_of_creates_path(self):
        p = URLPath.of("api", "v1")
        assert str(p) == "/api/v1"

    def test_root(self):
        p = URLPath.root()
        assert str(p) == "/"

    def test_division_appends_segment(self):
        p = URLPath.of("api") / "v1" / "users"
        assert str(p) == "/api/v1/users"

    def test_join_with_leading_slash(self):
        p = URLPath.of("api", "v1")
        result = p.join("/users")
        assert result == "/api/v1/users"

    def test_join_without_leading_slash(self):
        p = URLPath.of("api", "v1")
        result = p.join("users")
        assert result == "/api/v1/users"

    def test_auto_absolute(self):
        # URLPath.__post_init__ ensures path is absolute
        p = URLPath.of("relative")
        assert str(p).startswith("/")

    def test_single_segment(self):
        p = URLPath.of("health")
        assert str(p) == "/health"


class TestPrefix:
    def test_prefix_of(self):
        prefix = Prefix.of("api", "v1")
        assert str(prefix.path) == "/api/v1"

    def test_apply_trigger_prepends_path(self):
        prefix = Prefix.of("api", "v1")
        trigger = HTTPRouteTrigger("GET", "/users")
        result = prefix.apply_trigger(trigger)
        assert result.path == "/api/v1/users"
        assert result.method == "GET"

    def test_apply_trigger_preserves_method_and_headers(self):
        prefix = Prefix.of("api")
        trigger = HTTPRouteTrigger("POST", "/items", headers=frozenset({"X-Custom"}))
        result = prefix.apply_trigger(trigger)
        assert result.method == "POST"
        assert result.headers == frozenset({"X-Custom"})

    def test_apply_trigger_root_path(self):
        prefix = Prefix.of("api")
        trigger = HTTPRouteTrigger("GET", "/")
        result = prefix.apply_trigger(trigger)
        assert result.path == "/api/"


class TestStripPrefix:
    def test_strip_prefix_removes_matching(self):
        strip = StripPrefix.of("api")
        trigger = HTTPRouteTrigger("GET", "/api/users")
        result = strip.apply_trigger(trigger)
        assert result.path == "/users"

    def test_strip_prefix_no_match_passes_through(self):
        strip = StripPrefix.of("admin")
        trigger = HTTPRouteTrigger("GET", "/api/users")
        result = strip.apply_trigger(trigger)
        assert result.path == "/api/users"

    def test_strip_prefix_exact_match_becomes_root(self):
        strip = StripPrefix.of("api")
        trigger = HTTPRouteTrigger("GET", "/api")
        result = strip.apply_trigger(trigger)
        assert result.path == "/"


class TestAsDict:
    def test_dataclass_to_dict(self):
        @dataclass
        class Item:
            name: str
            price: float

        transform = AsDict()
        result = transform.apply_response(Item("widget", 9.99))
        assert result == {"name": "widget", "price": 9.99}

    def test_dict_passthrough(self):
        transform = AsDict()
        d = {"key": "value"}
        result = transform.apply_response(d)
        assert result == d

    def test_non_convertible_raises(self):
        transform = AsDict()
        with pytest.raises(ValueError, match="Cannot convert"):
            transform.apply_response(42)

    def test_non_convertible_skip_mode(self):
        transform = AsDict(skip=True)
        result = transform.apply_response(42)
        assert result == {"value": 42}

    def test_object_with_to_dict(self):
        class Obj:
            def to_dict(self):
                return {"x": 1}

        transform = AsDict()
        result = transform.apply_response(Obj())
        assert result == {"x": 1}


class TestAsStr:
    def test_int_to_str(self):
        transform = AsStr()
        assert transform.apply_response(42) == "42"

    def test_str_passthrough(self):
        transform = AsStr()
        assert transform.apply_response("hello") == "hello"

    def test_object_uses_dunder_str(self):
        class Obj:
            def __str__(self):
                return "custom"

        assert AsStr().apply_response(Obj()) == "custom"


class TestTransform:
    def test_custom_fn(self):
        t = Transform(fn=str.upper)
        assert t.apply_response("hello") == "HELLO"

    def test_lambda_transform(self):
        t = Transform(fn=lambda x: x * 2)
        assert t.apply_response(5) == 10

    def test_dict_wrapping(self):
        t = Transform(fn=lambda r: {"data": r, "status": "ok"})
        assert t.apply_response("payload") == {"data": "payload", "status": "ok"}


# ═══════════════════════════════════════════════════════════════════════════════
# 9. Enrichers
# ═══════════════════════════════════════════════════════════════════════════════


class TestInjectEnricher:
    def test_inject_creation_with_value(self):
        inject = Inject(type=str, value="hello")
        assert inject.type is str
        assert inject.value == "hello"
        assert inject.factory is None

    def test_inject_creation_with_factory(self):
        inject = Inject(type=int, factory=lambda s: 42)
        assert inject.type is int
        assert inject.factory is not None


class TestChainEnrichers:
    def test_chain_empty_returns_handler(self):
        async def handler(scope):
            return "result"

        chained = chain_enrichers((), handler)
        # chained should be the same handler when no enrichers
        assert chained is handler

    def test_chain_wraps_single_enricher(self):
        async def handler(scope):
            return "result"

        enricher = Inject(type=str, value="test")
        chained = chain_enrichers((enricher,), handler)
        # chained should be a wrapper, not the handler itself
        assert chained is not handler


# ═══════════════════════════════════════════════════════════════════════════════
# 10. Capability Helpers
# ═══════════════════════════════════════════════════════════════════════════════


class TestCapabilityHelpers:
    def test_find_capability_found(self):
        cap = MockCap("auth")
        caps = (cap, AnotherCap(1))
        result = find_capability(caps, MockCap)
        assert result is cap

    def test_find_capability_not_found(self):
        caps = (AnotherCap(1),)
        result = find_capability(caps, MockCap)
        assert result is None

    def test_find_capability_returns_first(self):
        caps = (MockCap("first"), MockCap("second"))
        result = find_capability(caps, MockCap)
        assert result.name == "first"

    def test_find_all_capabilities(self):
        caps = (MockCap("a"), AnotherCap(1), MockCap("b"))
        result = find_all_capabilities(caps, MockCap)
        assert len(result) == 2
        assert result[0].name == "a"
        assert result[1].name == "b"

    def test_find_all_capabilities_empty(self):
        caps = (AnotherCap(1),)
        result = find_all_capabilities(caps, MockCap)
        assert result == ()

    def test_has_capability_true(self):
        caps = (MockCap("x"),)
        assert has_capability(caps, MockCap) is True

    def test_has_capability_false(self):
        caps = (AnotherCap(1),)
        assert has_capability(caps, MockCap) is False

    def test_has_capability_empty_tuple(self):
        assert has_capability((), MockCap) is False

    def test_merge_capabilities_later_overrides(self):
        base = (MockCap("old"),)
        override = (MockCap("new"),)
        merged = merge_capabilities(base, override)
        # last wins by type
        mock_caps = [c for c in merged if isinstance(c, MockCap)]
        assert len(mock_caps) == 1
        assert mock_caps[0].name == "new"

    def test_merge_capabilities_different_types_preserved(self):
        base = (MockCap("x"),)
        extra = (AnotherCap(5),)
        merged = merge_capabilities(base, extra)
        assert len(merged) == 2

    def test_override_capability(self):
        caps = (MockCap("old"), AnotherCap(1))
        result = override_capability(caps, MockCap("new"))
        mock_caps = [c for c in result if isinstance(c, MockCap)]
        assert len(mock_caps) == 1
        assert mock_caps[0].name == "new"
        # AnotherCap still there
        assert any(isinstance(c, AnotherCap) for c in result)

    def test_remove_capability(self):
        caps = (MockCap("x"), AnotherCap(1), MockCap("y"))
        result = remove_capability(caps, MockCap)
        assert len(result) == 1
        assert isinstance(result[0], AnotherCap)

    def test_remove_capability_not_present(self):
        caps = (AnotherCap(1),)
        result = remove_capability(caps, MockCap)
        assert len(result) == 1

    def test_deduplicate_capabilities(self):
        caps = (MockCap("first"), AnotherCap(1), MockCap("second"))
        result = deduplicate_capabilities(caps)
        mock_caps = [c for c in result if isinstance(c, MockCap)]
        assert len(mock_caps) == 1
        # last one wins
        assert mock_caps[0].name == "second"

    def test_filter_by_protocol(self):
        as_dict = AsDict()
        as_str = AsStr()
        caps = (MockCap("x"), as_dict, as_str)
        response_transforms = filter_by_protocol(caps, ResponseTransform)
        assert as_dict in response_transforms
        assert as_str in response_transforms


# ═══════════════════════════════════════════════════════════════════════════════
# 11. Integration — endpoint to scan pipeline
# ═══════════════════════════════════════════════════════════════════════════════


class TestEndpointToScanIntegration:
    """End-to-end: build endpoints, mount in app, scan for triggers."""

    def test_multi_target_endpoint(self):
        """One runner, three exposures (HTTP + CLI + HTTP)."""
        runner = _runner()
        codec = rrc(Req, Resp)

        ep = (
            endpoint(runner)
            .expose(HTTPRouteTrigger("GET", "/users"), codec)
            .expose(CLITrigger("list-users", "List all users"), codec)
            .expose(HTTPRouteTrigger("POST", "/users"), codec)
        )
        app = application().mount(ep)

        http_pairs = scan(app, HTTPRouteTrigger)
        assert len(http_pairs) == 2

        cli_pairs = scan(app, CLITrigger)
        assert len(cli_pairs) == 1
        cli_trigger, cli_handler = cli_pairs[0]
        assert cli_trigger.command == "list-users"
        assert cli_handler.runner is runner

    def test_merged_apps_scan(self):
        """Scan across merged applications."""
        app1 = application().mount(
            endpoint(_runner()).expose(
                HTTPRouteTrigger("GET", "/a"), rrc(Req, Resp)
            )
        )
        app2 = application().mount(
            endpoint(_runner()).expose(
                HTTPRouteTrigger("GET", "/b"), rrc(Req, Resp)
            )
        )
        combined = app1 + app2
        pairs = scan(combined, HTTPRouteTrigger)
        assert len(pairs) == 2
        paths = {t.path for t, _ in pairs}
        assert paths == {"/a", "/b"}

    def test_stack_with_mixed_triggers(self):
        """AppStack with root HTTP and mounted CLI."""
        http_app = application().mount(
            endpoint(_runner()).expose(
                HTTPRouteTrigger("GET", "/health"), rrc(Req, Resp)
            )
        )
        cli_app = application().mount(
            endpoint(_runner()).expose(
                CLITrigger("migrate"), rrc(Req, Resp)
            )
        )
        stack = app_stack().root(http_app).mount("tools", cli_app)

        http_view = scan_stack(stack, HTTPRouteTrigger)
        assert len(http_view.root) == 1
        assert "tools" in http_view.mounts
        # tools app has no HTTP triggers
        tools_http = http_view.mounts["tools"]
        assert isinstance(tools_http, list)
        assert len(tools_http) == 0

        cli_view = scan_stack(stack, CLITrigger)
        assert len(cli_view.root) == 0
        tools_cli = cli_view.mounts["tools"]
        assert isinstance(tools_cli, list)
        assert len(tools_cli) == 1


# ═══════════════════════════════════════════════════════════════════════════════
# 12. Exposure dataclass
# ═══════════════════════════════════════════════════════════════════════════════


class TestExposure:
    def test_exposure_is_frozen(self):
        exp = Exposure(
            trigger=HTTPRouteTrigger("GET", "/x"),
            codec=rrc(Req, Resp),
        )
        with pytest.raises(AttributeError):
            exp.trigger = CLITrigger("y")  # type: ignore[misc]

    def test_exposure_default_capabilities_empty(self):
        exp = Exposure(
            trigger=HTTPRouteTrigger("GET", "/x"),
            codec=rrc(Req, Resp),
        )
        assert exp.capabilities == ()

    def test_exposure_with_capabilities(self):
        cap = MockCap("auth")
        exp = Exposure(
            trigger=HTTPRouteTrigger("GET", "/x"),
            codec=rrc(Req, Resp),
            capabilities=(cap,),
        )
        assert exp.capabilities == (cap,)


# ═══════════════════════════════════════════════════════════════════════════════
# 13. Integration — Full surface pipeline with mixed triggers/codecs
# ═══════════════════════════════════════════════════════════════════════════════


class TestIntegrationFullSurfacePipeline:
    """Build a realistic multi-trigger, multi-codec app and verify scan, handler,
    and capability wiring work together end-to-end."""

    def _build_app(self) -> Application:
        """Realistic app: HTTP RRC + HTTP Delegate + CLI RRC + Event RRC."""

        @dataclass
        class CreateUserReq:
            name: str = ""

        @dataclass
        class CreateUserResp:
            user_id: int = 0

        @dataclass
        class OrderEvent:
            order_id: int = 0

        from emergent.wire.axis.surface.triggers.event import EventTrigger

        runner = _runner()
        as_dict = AsDict()
        inject_cap = Inject(type=str, value="injected")

        # Endpoint 1: HTTP RRC + CLI RRC (multi-exposure)
        ep1 = (
            endpoint(runner)
            .expose(
                HTTPRouteTrigger("POST", "/users"),
                rrc(CreateUserReq, CreateUserResp),
                as_dict,
                inject_cap,
            )
            .expose(
                CLITrigger("create-user"),
                rrc(CreateUserReq, CreateUserResp),
            )
        )

        # Endpoint 2: HTTP Delegate
        ep2 = endpoint(runner).expose(
            HTTPRouteTrigger("GET", "/health"),
            delegate(lambda: "ok"),
        )

        # Endpoint 3: Event trigger
        ep3 = endpoint(runner).expose(
            EventTrigger(event_type=OrderEvent),
            rrc(OrderEvent, CreateUserResp),
        )

        return application(capabilities=(MockCap("cors"),)).mount(ep1, ep2, ep3)

    def test_scan_http_returns_all_http_handlers(self):
        app = self._build_app()
        pairs = scan(app, HTTPRouteTrigger)
        assert len(pairs) == 2
        paths = {t.path for t, _ in pairs}
        assert paths == {"/users", "/health"}

    def test_scan_http_rrc_only(self):
        app = self._build_app()
        pairs = scan(app, HTTPRouteTrigger, RequestResponseCodec)
        assert len(pairs) == 1
        assert pairs[0][0].path == "/users"

    def test_scan_http_delegate_only(self):
        app = self._build_app()
        pairs = scan(app, HTTPRouteTrigger, DelegateCodec)
        assert len(pairs) == 1
        assert pairs[0][0].path == "/health"

    def test_scan_cli_returns_cli_only(self):
        app = self._build_app()
        pairs = scan(app, CLITrigger)
        assert len(pairs) == 1
        assert pairs[0][0].command == "create-user"

    def test_scan_event_returns_event_only(self):
        from emergent.wire.axis.surface.triggers.event import EventTrigger

        app = self._build_app()
        pairs = scan(app, EventTrigger)
        assert len(pairs) == 1

    def test_handler_carries_exposure_capabilities(self):
        """Capabilities set on expose() flow through to Handler via scan."""
        app = self._build_app()
        pairs = scan(app, HTTPRouteTrigger, RequestResponseCodec)
        _, handler = pairs[0]
        assert has_capability(handler.capabilities, AsDict)
        assert has_capability(handler.capabilities, Inject)

    def test_handler_without_caps_has_empty_tuple(self):
        app = self._build_app()
        pairs = scan(app, CLITrigger)
        _, handler = pairs[0]
        assert handler.capabilities == ()


# ═══════════════════════════════════════════════════════════════════════════════
# 14. Integration — Capability flow through AppStack hierarchy
# ═══════════════════════════════════════════════════════════════════════════════


class TestIntegrationCapabilityFlowThroughStack:
    """AppStack with root + mounts, global and per-exposure capabilities."""

    def test_stack_scan_preserves_capabilities(self):
        """Capabilities on individual exposures survive scan_stack."""
        cap = AsDict()
        root_app = application().mount(
            endpoint(_runner()).expose(
                HTTPRouteTrigger("GET", "/root"),
                rrc(Req, Resp),
                cap,
            )
        )
        sub_app = application().mount(
            endpoint(_runner()).expose(
                HTTPRouteTrigger("GET", "/sub"),
                rrc(Req, Resp),
            )
        )
        stack = app_stack().root(root_app).mount("admin", sub_app)
        view = scan_stack(stack, HTTPRouteTrigger)

        # Root handler has AsDict
        _, root_handler = view.root[0]
        assert has_capability(root_handler.capabilities, AsDict)

        # Sub handler has no caps
        sub_pairs = view.mounts["admin"]
        assert isinstance(sub_pairs, list)
        _, sub_handler = sub_pairs[0]
        assert sub_handler.capabilities == ()

    def test_nested_stack_scan_depth(self):
        """Three-level nesting: root → mount → nested mount via AppStack."""
        inner_app = application().mount(
            endpoint(_runner()).expose(CLITrigger("deep"), rrc(Req, Resp))
        )
        inner_stack = app_stack().root(inner_app)
        mid_app = application().mount(
            endpoint(_runner()).expose(CLITrigger("mid"), rrc(Req, Resp))
        )
        mid_stack = app_stack().root(mid_app).mount("inner", inner_stack)
        outer = app_stack().mount("mid", mid_stack)

        view = scan_stack(outer, CLITrigger)
        assert len(view.root) == 0
        mid_view = view.mounts["mid"]
        assert isinstance(mid_view, StackView)
        assert len(mid_view.root) == 1
        inner_view = mid_view.mounts["inner"]
        assert isinstance(inner_view, StackView)
        assert len(inner_view.root) == 1

    def test_stack_codec_filter(self):
        """scan_stack filters by codec type across hierarchy."""
        root_app = application().mount(
            endpoint(_runner())
            .expose(HTTPRouteTrigger("GET", "/a"), rrc(Req, Resp))
            .expose(HTTPRouteTrigger("GET", "/b"), delegate(lambda: None))
        )
        sub_app = application().mount(
            endpoint(_runner()).expose(
                HTTPRouteTrigger("POST", "/c"), rrc(Req, Resp),
            )
        )
        stack = app_stack().root(root_app).mount("api", sub_app)

        rrc_view = scan_stack(stack, HTTPRouteTrigger, RequestResponseCodec)
        assert len(rrc_view.root) == 1
        assert rrc_view.root[0][0].path == "/a"
        api_pairs = rrc_view.mounts["api"]
        assert isinstance(api_pairs, list)
        assert len(api_pairs) == 1

    def test_stack_with_global_app_capabilities(self):
        """Global capabilities on Application are separate from Handler caps."""
        cap = MockCap("auth")
        root_app = application(capabilities=(cap,)).mount(
            endpoint(_runner()).expose(
                HTTPRouteTrigger("GET", "/x"), rrc(Req, Resp),
            )
        )
        stack = app_stack().root(root_app)
        # App-level caps
        assert root_app.capabilities == (cap,)
        # Handler-level caps are empty (not inherited from app)
        view = scan_stack(stack, HTTPRouteTrigger)
        _, handler = view.root[0]
        assert handler.capabilities == ()


# ═══════════════════════════════════════════════════════════════════════════════
# 15. Integration — Stateful codec full lifecycle
# ═══════════════════════════════════════════════════════════════════════════════


class TestIntegrationStatefulCodecLifecycle:
    """Build a stateful codec, test all transition parse patterns, and verify
    the codec carries correct structure through endpoint/scan."""

    def test_stateful_multi_transition_flow(self):
        """Flow with multiple @transition methods, verify all found."""

        @dataclass
        class WizardFlow:
            step: int = 0

            @transition
            async def set_name(self, name: str = ""):
                return replace(self, step=1)

            @transition
            async def set_email(self, email: str = ""):
                return replace(self, step=2)

            @transition
            async def confirm(self):
                return Done()

            def to_domain(self):
                return {"step": self.step}

        class FakeKey:
            pass

        transitions = get_transitions(WizardFlow)
        assert len(transitions) == 3
        names = {t.__name__ for t in transitions}
        assert names == {"set_name", "set_email", "confirm"}

        codec = stateful(WizardFlow, Resp).key(FakeKey).build()
        assert codec.flow is WizardFlow
        assert codec.key_node is FakeKey

    def test_parse_all_transition_result_variants(self):
        """All four variants: state, done, (state, resp), (done, resp)."""

        @dataclass
        class S:
            x: int = 0

        # State only
        r1 = parse_transition_result(S(x=1))
        assert not r1.is_terminal
        assert isinstance(r1.response, Nothing)

        # Done only
        r2 = parse_transition_result(Done())
        assert r2.is_terminal
        assert isinstance(r2.response, Nothing)

        # State + response
        r3 = parse_transition_result((S(x=2), "progress"))
        assert not r3.is_terminal
        assert isinstance(r3.response, Some)
        assert r3.response.unwrap() == "progress"

        # Done + response
        r4 = parse_transition_result((Done(), "final"))
        assert r4.is_terminal
        assert isinstance(r4.response, Some)
        assert r4.response.unwrap() == "final"

    def test_cancelled_is_terminal_done(self):
        """Cancelled extends Done — parse_transition_result marks terminal."""
        from emergent.wire.axis.surface.codecs.stateful import Cancelled

        r = parse_transition_result(Cancelled())
        assert r.is_terminal
        assert isinstance(r.state_or_done, Cancelled)

    def test_stateful_endpoint_scanned_as_stateful_codec(self):
        """Stateful codec on endpoint is scannable by StatefulCodec type."""

        @dataclass
        class SimpleFlow:
            @transition
            async def step(self):
                return Done()

            def to_domain(self):
                return {}

        class FakeKey:
            pass

        codec = stateful(SimpleFlow, Resp).key(FakeKey).build()
        ep = endpoint(_runner()).expose(CLITrigger("wizard"), codec)
        pairs = scan_endpoint(ep, CLITrigger, StatefulCodec)
        assert len(pairs) == 1
        _, handler = pairs[0]
        assert isinstance(handler.codec, StatefulCodec)
        assert handler.codec.flow is SimpleFlow

    def test_stateful_with_dunder_transition(self):
        """Flow using __transition__ instead of @transition decorator."""

        @dataclass
        class LegacyFlow:
            async def __transition__(self, input: str = ""):
                return Done()

            def to_domain(self):
                return {}

        transitions = get_transitions(LegacyFlow)
        assert len(transitions) == 1
        assert transitions[0].__name__ == "__transition__"

    def test_stateful_builder_chaining(self):
        """Builder pattern: stateful().key().build() with store."""

        @dataclass
        class Flow:
            @transition
            async def step(self):
                return Done()

            def to_domain(self):
                return {}

        class MyKey:
            pass

        # Verify builder returns StatefulCodec with all fields
        codec = stateful(Flow, Resp).key(MyKey).build()
        assert isinstance(codec, StatefulCodec)
        assert codec.flow is Flow
        assert codec.response is Resp
        assert codec.key_node is MyKey


# ═══════════════════════════════════════════════════════════════════════════════
# 16. Integration — Enricher + Transform composition
# ═══════════════════════════════════════════════════════════════════════════════


class TestIntegrationEnricherTransformComposition:
    """Enrichers and response transforms on the same endpoint.
    Verify chain_enrichers ordering and filter_by_protocol classification."""

    @pytest.mark.anyio
    async def test_chain_enrichers_ordering(self):
        """chain_enrichers builds e1(e2(handler)) — first is outermost."""
        from nodnod import Scope
        from emergent.wire.axis.surface.enrichers._impl import Passthrough

        call_order: list[str] = []

        @dataclass(frozen=True, slots=True)
        class TrackEnricher(ScopeEnricher):
            label: str

            async def enrich(self, call, scope):
                call_order.append(f"{self.label}_enter")
                result = await call(scope)
                call_order.append(f"{self.label}_exit")
                return result

        async def handler(scope: Scope) -> str:
            call_order.append("handler")
            return "ok"

        enrichers = (TrackEnricher(label="outer"), TrackEnricher(label="inner"))
        chained = chain_enrichers(enrichers, handler)

        scope = Scope()
        async with scope:
            result = await chained(scope)

        assert result == "ok"
        assert call_order == [
            "outer_enter", "inner_enter", "handler", "inner_exit", "outer_exit"
        ]

    @pytest.mark.anyio
    async def test_inject_enricher_provides_value_to_scope(self):
        """Inject enricher injects value into scope before handler."""
        from nodnod import Scope

        @dataclass
        class Config:
            db_url: str = "postgres://localhost"

        config = Config()
        enricher = Inject(type=Config, value=config)

        received: list[Config] = []

        async def handler(scope: Scope) -> str:
            retrieved = scope.retrieve(Config)
            assert isinstance(retrieved, Some)
            received.append(retrieved.unwrap().value)
            return "done"

        chained = chain_enrichers((enricher,), handler)
        scope = Scope()
        async with scope:
            await chained(scope)

        assert len(received) == 1
        assert received[0] is config

    @pytest.mark.anyio
    async def test_inject_factory_enricher(self):
        """Inject with factory= produces value from scope."""
        from nodnod import Scope

        enricher = Inject(type=int, factory=lambda scope: 42)

        async def handler(scope: Scope) -> int:
            opt = scope.retrieve(int)
            assert isinstance(opt, Some)
            return opt.unwrap().value

        chained = chain_enrichers((enricher,), handler)
        scope = Scope()
        async with scope:
            result = await chained(scope)

        assert result == 42

    def test_filter_enrichers_vs_transforms(self):
        """filter_by_protocol correctly separates enrichers from transforms."""
        inject = Inject(type=str, value="x")
        as_dict = AsDict()
        as_str = AsStr()
        transform = Transform(fn=lambda x: x)
        mock = MockCap("tag")

        caps: tuple[SurfaceCapability, ...] = (inject, as_dict, as_str, transform, mock)

        enrichers = filter_by_protocol(caps, ScopeEnricher)
        assert len(enrichers) == 1
        assert enrichers[0] is inject

        transforms = filter_by_protocol(caps, ResponseTransform)
        assert len(transforms) == 3
        assert as_dict in transforms
        assert as_str in transforms
        assert transform in transforms

    def test_endpoint_with_mixed_capabilities_scanned(self):
        """Endpoint with enrichers + transforms — all carried through scan."""
        inject = Inject(type=str, value="x")
        as_dict = AsDict()
        transform = Transform(fn=str.upper)

        ep = endpoint(_runner()).expose(
            HTTPRouteTrigger("GET", "/api"),
            rrc(Req, Resp),
            inject,
            as_dict,
            transform,
        )
        app = application().mount(ep)
        pairs = scan(app, HTTPRouteTrigger)
        _, handler = pairs[0]

        assert len(handler.capabilities) == 3
        assert has_capability(handler.capabilities, Inject)
        assert has_capability(handler.capabilities, AsDict)
        assert has_capability(handler.capabilities, Transform)


# ═══════════════════════════════════════════════════════════════════════════════
# 17. Integration — Capability helpers full pipeline
# ═══════════════════════════════════════════════════════════════════════════════


class TestIntegrationCapabilityHelpersPipeline:
    """Full pipeline: merge, override, deduplicate, filter, find, remove
    applied to capabilities from real endpoints."""

    def test_merge_override_deduplicate_pipeline(self):
        """merge → override → deduplicate produces clean result."""
        base = (MockCap("auth"), AnotherCap(1), AsDict())
        extra = (MockCap("cors"), AsStr())

        # merge: MockCap("auth") → MockCap("cors") (overridden by later)
        merged = merge_capabilities(base, extra)
        mock_caps = find_all_capabilities(merged, MockCap)
        assert len(mock_caps) == 1
        assert mock_caps[0].name == "cors"

        # Override AsDict with AsDict(skip=True)
        overridden = override_capability(merged, AsDict(skip=True))
        found = find_capability(overridden, AsDict)
        assert found is not None
        assert found.skip is True

        # Deduplicate (idempotent after merge)
        deduped = deduplicate_capabilities(overridden)
        assert len(deduped) == len(overridden)

    def test_remove_and_verify_absence(self):
        """remove_capability + has_capability chain."""
        caps: tuple[SurfaceCapability, ...] = (
            MockCap("x"), AnotherCap(1), AsDict(), Inject(type=str, value="v"),
        )

        # Remove Inject
        result = remove_capability(caps, Inject)
        assert not has_capability(result, Inject)
        assert has_capability(result, MockCap)
        assert has_capability(result, AsDict)
        assert len(result) == 3

    def test_filter_find_roundtrip(self):
        """filter_by_protocol then find_capability within filtered set."""
        inject = Inject(type=str, value="x")
        as_dict = AsDict()
        as_str = AsStr()
        caps: tuple[SurfaceCapability, ...] = (inject, as_dict, as_str, MockCap("tag"))

        transforms = filter_by_protocol(caps, ResponseTransform)
        # find within transforms
        found = find_capability(transforms, AsDict)
        assert found is as_dict

        # find_all within transforms
        all_transforms = find_all_capabilities(transforms, ResponseTransform)
        assert len(all_transforms) == 2

    def test_capabilities_from_scanned_handlers(self):
        """Extract capabilities from handlers produced by scan, then manipulate."""
        ep1 = endpoint(_runner()).expose(
            HTTPRouteTrigger("GET", "/a"),
            rrc(Req, Resp),
            AsDict(),
            MockCap("auth"),
        )
        ep2 = endpoint(_runner()).expose(
            HTTPRouteTrigger("GET", "/b"),
            rrc(Req, Resp),
            AsStr(),
            MockCap("rate-limit"),
        )
        app = application().mount(ep1, ep2)
        pairs = scan(app, HTTPRouteTrigger)

        # Merge capabilities from both handlers
        all_caps = merge_capabilities(
            pairs[0][1].capabilities,
            pairs[1][1].capabilities,
        )
        # MockCap from ep2 overrides MockCap from ep1 (same type)
        mock = find_capability(all_caps, MockCap)
        assert mock is not None
        assert mock.name == "rate-limit"

        # Both transform types present
        assert has_capability(all_caps, AsDict)
        assert has_capability(all_caps, AsStr)

    def test_deduplicate_preserves_last_of_each_type(self):
        """Multiple same-type caps → deduplicate keeps last."""
        caps: tuple[SurfaceCapability, ...] = (
            MockCap("first"),
            AnotherCap(1),
            MockCap("second"),
            AnotherCap(2),
            MockCap("third"),
        )
        deduped = deduplicate_capabilities(caps)
        assert len(deduped) == 2
        mock = find_capability(deduped, MockCap)
        assert mock is not None
        assert mock.name == "third"
        another = find_capability(deduped, AnotherCap)
        assert another is not None
        assert another.value == 2


# ═══════════════════════════════════════════════════════════════════════════════
# 18. Integration — Application merge complex topology
# ═══════════════════════════════════════════════════════════════════════════════


class TestIntegrationApplicationMergeTopology:
    """Multiple apps with various topologies merged via + and .merge()."""

    def test_triple_merge_preserves_all_endpoints(self):
        eps = [
            endpoint(_runner()).expose(
                HTTPRouteTrigger("GET", f"/ep{i}"), rrc(Req, Resp),
            )
            for i in range(3)
        ]
        apps = [application().mount(ep) for ep in eps]
        merged = apps[0].merge(apps[1], apps[2])
        pairs = scan(merged, HTTPRouteTrigger)
        assert len(pairs) == 3
        paths = {t.path for t, _ in pairs}
        assert paths == {"/ep0", "/ep1", "/ep2"}

    def test_add_operator_associativity(self):
        """(a + b) + c == a + (b + c) in terms of endpoint count."""
        eps = [
            endpoint(_runner()).expose(
                HTTPRouteTrigger("GET", f"/x{i}"), rrc(Req, Resp),
            )
            for i in range(3)
        ]
        a = application().mount(eps[0])
        b = application().mount(eps[1])
        c = application().mount(eps[2])

        left = (a + b) + c
        right = a + (b + c)
        assert len(left.endpoints) == len(right.endpoints) == 3

    def test_merge_accumulates_capabilities(self):
        app1 = application(capabilities=(MockCap("cors"),))
        app2 = application(capabilities=(AnotherCap(42),))
        app3 = application(capabilities=(MockCap("auth"),))
        merged = app1.merge(app2, app3)
        # All capabilities accumulated
        assert len(merged.capabilities) == 3
        # Order: app1 caps + app2 caps + app3 caps
        assert isinstance(merged.capabilities[0], MockCap)
        assert isinstance(merged.capabilities[1], AnotherCap)
        assert isinstance(merged.capabilities[2], MockCap)

    def test_merge_with_mixed_codec_types(self):
        """Merge apps with different codec types — scan by codec still works."""
        rrc_app = application().mount(
            endpoint(_runner()).expose(
                HTTPRouteTrigger("GET", "/rrc"), rrc(Req, Resp),
            )
        )
        delegate_app = application().mount(
            endpoint(_runner()).expose(
                HTTPRouteTrigger("GET", "/delegate"), delegate(lambda: "ok"),
            )
        )
        immediate_app = application().mount(
            endpoint(_runner()).expose(
                HTTPRouteTrigger("GET", "/immediate"),
                immediate_factory(lambda: "hello"),
            )
        )
        merged = rrc_app + delegate_app + immediate_app

        all_http = scan(merged, HTTPRouteTrigger)
        assert len(all_http) == 3

        rrc_only = scan(merged, HTTPRouteTrigger, RequestResponseCodec)
        assert len(rrc_only) == 1
        assert rrc_only[0][0].path == "/rrc"

        delegate_only = scan(merged, HTTPRouteTrigger, DelegateCodec)
        assert len(delegate_only) == 1
        assert delegate_only[0][0].path == "/delegate"

        immediate_only = scan(merged, HTTPRouteTrigger, ImmediateFactoryCodec)
        assert len(immediate_only) == 1
        assert immediate_only[0][0].path == "/immediate"

    def test_empty_app_merge_is_identity(self):
        """Merging with empty app doesn't change anything."""
        ep = endpoint(_runner()).expose(
            HTTPRouteTrigger("GET", "/x"), rrc(Req, Resp),
        )
        app = application(capabilities=(MockCap("x"),)).mount(ep)
        merged = app + application()
        assert len(merged.endpoints) == 1
        assert len(merged.capabilities) == 1

    def test_trigger_transform_applied_before_scan(self):
        """Prefix transform modifies trigger paths."""
        prefix = Prefix.of("api", "v1")
        trigger = HTTPRouteTrigger("GET", "/users")
        transformed = prefix.apply_trigger(trigger)

        ep = endpoint(_runner()).expose(transformed, rrc(Req, Resp))
        app = application().mount(ep)
        pairs = scan(app, HTTPRouteTrigger)
        assert pairs[0][0].path == "/api/v1/users"

        # Chain: Prefix then StripPrefix = roundtrip
        strip = StripPrefix.of("api/v1")
        restored = strip.apply_trigger(transformed)
        assert restored.path == "/users"

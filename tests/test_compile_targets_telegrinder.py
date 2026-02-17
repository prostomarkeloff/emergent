"""Tests for emergent.wire.compile.targets.telegrinder.

Covers:
- _format_tg_response — passthrough and conversion rules
- TelegrindRoute — dataclass structure
- wrap_rrc_telegrinder / wrap_delegate_telegrinder / wrap_immediate_telegrinder
- TELEGRINDER_COMPILER — correct adapters registered
- enhance_command_with_args — CommandArg annotation → Argument generation
- telegrinder_compile — returns Dispatch, handlers registered
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Self
from unittest.mock import MagicMock

import pytest
from kungfu import Ok, Error, Result

from emergent.wire.compile.targets.telegrinder import (
    _format_tg_response as _format_tg_response,  # pyright: ignore[reportPrivateUsage] - testing private helper intentionally
    TelegrindRoute,
    TELEGRINDER_COMPILER,
    telegrinder_compile,
    wrap_rrc_telegrinder,
    wrap_delegate_telegrinder,
    wrap_immediate_telegrinder,
    enhance_command_with_args,
)
from emergent.wire.axis.surface.triggers.telegrinder import TelegrindTrigger
from emergent.wire.axis.surface.codecs.rrc import RequestResponseCodec, rrc
from emergent.wire.axis.surface.codecs.immediate import (
    ImmediateCodec,
    ImmediateFactoryCodec,
    immediate,
)
from emergent.wire.axis.surface.codecs.delegate import DelegateCodec, delegate
from emergent.wire.axis.surface.codecs.stateful import StatefulCodec
from emergent.wire.axis.surface._handler import Handler
from emergent.wire.axis.surface._app import Application
from emergent.wire.axis.surface._endpoint import endpoint
from emergent.wire.compile._core import Axes
from emergent.wire.compile._target import CodecAdapter
from telegrinder.bot.rules.command import Command
from telegrinder.bot.rules.abc import ABCRule
from telegrinder.bot.dispatch.context import Context
from emergent.ops._graph import Op
from emergent.wire.axis.schema.dialects.tg import CommandArg as TgCommandArg


# ═══════════════════════════════════════════════════════════════════════════════
# Domain fixtures — minimal types that satisfy codec protocols
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class _EchoOp(Op[str, str]):
    name: str


@dataclass
class _EchoReq:
    name: str

    def to_domain(self) -> _EchoOp:
        return _EchoOp(name=self.name)


@dataclass
class _EchoResp:
    text: str

    @classmethod
    def from_domain(cls, dom: Result[str, str]) -> Self:
        match dom:
            case Ok(v):
                return cls(text=v)
            case Error(e):
                return cls(text=str(e))

    def __str__(self) -> str:
        return self.text


def _make_axes() -> Axes:
    return Axes.default()


def _make_runner() -> MagicMock:
    """Return a mock Runner — we don't execute domain logic in unit tests."""
    return MagicMock()


def _make_rrc_handler() -> Handler[RequestResponseCodec]:
    return Handler(
        codec=RequestResponseCodec(request=_EchoReq, response=_EchoResp),
        runner=_make_runner(),
        capabilities=(),
    )


def _make_trigger(*rules: ABCRule, view: str = "message") -> TelegrindTrigger:
    return TelegrindTrigger(*rules, view=view)


# ═══════════════════════════════════════════════════════════════════════════════
# _format_tg_response
# ═══════════════════════════════════════════════════════════════════════════════


class TestFormatTgResponse:
    """Passthrough types, telegrinder types, and custom __str__ conversion."""

    def test_str_passthrough(self) -> None:
        assert _format_tg_response("hello") == "hello"
        assert isinstance(_format_tg_response("hello"), str)

    def test_int_passthrough(self) -> None:
        assert _format_tg_response(42) == 42

    def test_float_passthrough(self) -> None:
        assert _format_tg_response(3.14) == 3.14

    def test_bool_passthrough(self) -> None:
        assert _format_tg_response(True) is True

    def test_none_passthrough(self) -> None:
        assert _format_tg_response(None) is None

    def test_dict_passthrough(self) -> None:
        d = {"key": "value"}
        assert _format_tg_response(d) is d

    def test_list_passthrough(self) -> None:
        lst = [1, 2, 3]
        assert _format_tg_response(lst) is lst

    def test_bytes_passthrough(self) -> None:
        b = b"data"
        assert _format_tg_response(b) is b

    def test_tuple_passthrough(self) -> None:
        t = (1, 2)
        assert _format_tg_response(t) is t

    def test_custom_class_with_str_returns_string(self) -> None:
        """Class with custom __str__ → str(response)."""

        class MyResponse:
            def __str__(self) -> str:
                return "formatted output"

        result = _format_tg_response(MyResponse())
        assert result == "formatted output"
        assert isinstance(result, str)

    def test_custom_class_without_str_returns_as_is(self) -> None:
        """Class without custom __str__ (uses default object.__str__) → returned as-is."""

        class NoStr:
            pass

        obj = NoStr()
        result = _format_tg_response(obj)
        assert result is obj

    def test_telegrinder_type_passthrough(self) -> None:
        """Instances whose class.__module__ starts with 'telegrinder' pass through."""

        class FakeTgType:
            pass

        FakeTgType.__module__ = "telegrinder.types.something"
        obj = FakeTgType()
        result = _format_tg_response(obj)
        assert result is obj

    def test_telegrinder_subpackage_passthrough(self) -> None:
        """Deeper telegrinder submodule path still passes through."""

        class FakeTgNested:
            def __str__(self) -> str:
                # Even if __str__ is defined, telegrinder types skip conversion
                return "this should not be returned as str"

        FakeTgNested.__module__ = "telegrinder.bot.cute_types.message"
        obj = FakeTgNested()
        result = _format_tg_response(obj)
        assert result is obj


# ═══════════════════════════════════════════════════════════════════════════════
# TelegrindRoute — dataclass structure
# ═══════════════════════════════════════════════════════════════════════════════


class TestTelegrindRoute:
    def test_construction(self) -> None:
        def dummy_handler(ctx: object) -> object:
            return None

        rule = MagicMock(spec=ABCRule)
        route = TelegrindRoute(handler=dummy_handler, rules=(rule,))
        assert route.handler is dummy_handler
        assert route.rules == (rule,)

    def test_empty_rules(self) -> None:
        def dummy_handler(ctx: object) -> object:
            return None

        route = TelegrindRoute(handler=dummy_handler, rules=())
        assert route.rules == ()

    def test_frozen(self) -> None:
        """TelegrindRoute is a frozen dataclass — mutation raises."""

        def dummy_handler(ctx: object) -> object:
            return None

        route = TelegrindRoute(handler=dummy_handler, rules=())
        with pytest.raises((AttributeError, TypeError)):
            route.rules = (MagicMock(),)  # type: ignore[misc]

    def test_handler_is_callable(self) -> None:
        called = False

        def real_handler(ctx: Context) -> str:
            nonlocal called
            called = True
            return "ok"

        route = TelegrindRoute(handler=real_handler, rules=())
        route.handler(MagicMock(spec=Context))
        assert called


# ═══════════════════════════════════════════════════════════════════════════════
# wrap_rrc_telegrinder
# ═══════════════════════════════════════════════════════════════════════════════


class TestWrapRrcTelegrinder:
    def test_returns_telegrind_route(self) -> None:
        trigger = _make_trigger(Command("echo"))
        handler = _make_rrc_handler()
        route = wrap_rrc_telegrinder(handler, trigger, _make_axes())
        assert isinstance(route, TelegrindRoute)

    def test_handler_is_callable(self) -> None:
        trigger = _make_trigger(Command("echo"))
        handler = _make_rrc_handler()
        route = wrap_rrc_telegrinder(handler, trigger, _make_axes())
        assert callable(route.handler)

    def test_rules_propagated_from_trigger(self) -> None:
        """Rules from trigger are transferred to route."""
        cmd = Command("echo")
        trigger = _make_trigger(cmd)
        handler = _make_rrc_handler()
        route = wrap_rrc_telegrinder(handler, trigger, _make_axes())
        # Rules are a tuple of ABCRule instances
        assert len(route.rules) >= 1
        assert all(isinstance(r, ABCRule) for r in route.rules)


# ═══════════════════════════════════════════════════════════════════════════════
# wrap_delegate_telegrinder
# ═══════════════════════════════════════════════════════════════════════════════


class TestWrapDelegateTelegrinder:
    def test_returns_telegrind_route(self) -> None:
        async def my_handler() -> str:
            return "ok"

        trigger = _make_trigger(Command("del"))
        handler: Handler[DelegateCodec] = Handler(
            codec=DelegateCodec(handler=my_handler),
            runner=_make_runner(),
            capabilities=(),
        )
        route = wrap_delegate_telegrinder(handler, trigger, _make_axes())
        assert isinstance(route, TelegrindRoute)

    def test_handler_callable(self) -> None:
        async def my_handler() -> str:
            return "ok"

        trigger = _make_trigger(Command("del"))
        handler: Handler[DelegateCodec] = Handler(
            codec=DelegateCodec(handler=my_handler),
            runner=_make_runner(),
            capabilities=(),
        )
        route = wrap_delegate_telegrinder(handler, trigger, _make_axes())
        assert callable(route.handler)

    def test_rules_match_trigger(self) -> None:
        cmd = Command("del")
        trigger = _make_trigger(cmd)

        async def my_handler() -> str:
            return "ok"

        handler: Handler[DelegateCodec] = Handler(
            codec=DelegateCodec(handler=my_handler),
            runner=_make_runner(),
            capabilities=(),
        )
        route = wrap_delegate_telegrinder(handler, trigger, _make_axes())
        assert len(route.rules) == len(trigger.rules)


# ═══════════════════════════════════════════════════════════════════════════════
# wrap_immediate_telegrinder
# ═══════════════════════════════════════════════════════════════════════════════


class TestWrapImmediateTelegrinder:
    def test_immediate_codec_returns_route(self) -> None:
        @dataclass
        class HelpResp:
            text: str

            @classmethod
            def produce(cls) -> Self:
                return cls(text="Help!")

        trigger = _make_trigger(Command("help"))
        handler: Handler[ImmediateCodec] = Handler(
            codec=ImmediateCodec(response=HelpResp),
            runner=_make_runner(),
            capabilities=(),
        )
        route = wrap_immediate_telegrinder(handler, trigger, _make_axes())
        assert isinstance(route, TelegrindRoute)

    def test_immediate_factory_codec_returns_route(self) -> None:
        trigger = _make_trigger(Command("help"))
        handler: Handler[ImmediateFactoryCodec] = Handler(
            codec=ImmediateFactoryCodec(factory=lambda: "static response"),
            runner=_make_runner(),
            capabilities=(),
        )
        route = wrap_immediate_telegrinder(handler, trigger, _make_axes())
        assert isinstance(route, TelegrindRoute)

    def test_immediate_rules_from_trigger(self) -> None:
        cmd = Command("help")
        trigger = _make_trigger(cmd)

        @dataclass
        class HelpResp:
            @classmethod
            def produce(cls) -> Self:
                return cls()

        handler: Handler[ImmediateCodec] = Handler(
            codec=ImmediateCodec(response=HelpResp),
            runner=_make_runner(),
            capabilities=(),
        )
        route = wrap_immediate_telegrinder(handler, trigger, _make_axes())
        assert len(route.rules) == len(trigger.rules)


# ═══════════════════════════════════════════════════════════════════════════════
# TELEGRINDER_COMPILER
# ═══════════════════════════════════════════════════════════════════════════════


class TestTelegrindCompiler:
    def test_trigger_type_is_telegrind_trigger(self) -> None:
        assert TELEGRINDER_COMPILER.trigger_type is TelegrindTrigger

    def test_has_rrc_adapter(self) -> None:
        codec_types = {a.codec_type for a in TELEGRINDER_COMPILER.adapters}
        assert RequestResponseCodec in codec_types

    def test_has_stateful_adapter(self) -> None:
        codec_types = {a.codec_type for a in TELEGRINDER_COMPILER.adapters}
        assert StatefulCodec in codec_types

    def test_has_immediate_adapter(self) -> None:
        codec_types = {a.codec_type for a in TELEGRINDER_COMPILER.adapters}
        assert ImmediateCodec in codec_types

    def test_has_immediate_factory_adapter(self) -> None:
        codec_types = {a.codec_type for a in TELEGRINDER_COMPILER.adapters}
        assert ImmediateFactoryCodec in codec_types

    def test_has_delegate_adapter(self) -> None:
        codec_types = {a.codec_type for a in TELEGRINDER_COMPILER.adapters}
        assert DelegateCodec in codec_types

    def test_all_adapters_are_codec_adapter_instances(self) -> None:
        for adapter in TELEGRINDER_COMPILER.adapters:
            assert isinstance(adapter, CodecAdapter)

    def test_adapters_have_callable_wraps(self) -> None:
        for adapter in TELEGRINDER_COMPILER.adapters:
            assert callable(adapter.wrap)


# ═══════════════════════════════════════════════════════════════════════════════
# Module-level dataclasses for enhance_command_with_args tests
# (must be at module level so get_type_hints can resolve Annotated types)
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class _PlainReq:
    """Request with no CommandArg annotations."""
    name: str


@dataclass
class _RegisterReq:
    """Request with one CommandArg field."""
    login: Annotated[str, TgCommandArg()]


@dataclass
class _MultiArgReq:
    """Request with multiple CommandArg fields."""
    login: Annotated[str, TgCommandArg()]
    password: Annotated[str, TgCommandArg()]


@dataclass
class _SingleFieldReq:
    """Request with one CommandArg field for view-preservation test."""
    field: Annotated[str, TgCommandArg()]


# ═══════════════════════════════════════════════════════════════════════════════
# enhance_command_with_args
# ═══════════════════════════════════════════════════════════════════════════════


class TestEnhanceCommandWithArgs:
    def test_no_command_arg_annotations_unchanged(self) -> None:
        """Request without tg.CommandArg → trigger unchanged."""
        cmd = Command("greet")
        trigger = _make_trigger(cmd)
        result = enhance_command_with_args(trigger, _PlainReq)
        # Rules should still be present and the Command should have no arguments
        assert len(result.rules) == len(trigger.rules)
        for rule in result.rules:
            if isinstance(rule, Command):
                assert not rule.arguments

    def test_with_command_arg_adds_argument(self) -> None:
        """Request with tg.CommandArg → Command rule gets Argument appended."""
        cmd = Command("register")
        trigger = _make_trigger(cmd)
        result = enhance_command_with_args(trigger, _RegisterReq)

        # The Command in the result should have arguments
        enhanced_commands = [r for r in result.rules if isinstance(r, Command)]
        assert len(enhanced_commands) == 1
        enhanced_cmd = enhanced_commands[0]
        assert len(enhanced_cmd.arguments) == 1
        assert enhanced_cmd.arguments[0].name == "login"

    def test_multiple_command_args_all_added(self) -> None:
        """Multiple CommandArg fields → multiple Arguments in Command."""
        cmd = Command("register")
        trigger = _make_trigger(cmd)
        result = enhance_command_with_args(trigger, _MultiArgReq)

        enhanced_commands = [r for r in result.rules if isinstance(r, Command)]
        assert len(enhanced_commands) == 1
        enhanced_cmd = enhanced_commands[0]
        assert len(enhanced_cmd.arguments) == 2
        arg_names = [a.name for a in enhanced_cmd.arguments]
        assert "login" in arg_names
        assert "password" in arg_names

    def test_view_preserved_after_enhancement(self) -> None:
        """The trigger's view attribute is preserved after enhancement."""
        trigger = TelegrindTrigger(Command("cmd"), view="callback_query")
        result = enhance_command_with_args(trigger, _SingleFieldReq)
        assert result.view == "callback_query"

    def test_non_dataclass_request_returns_trigger_unchanged(self) -> None:
        """Non-dataclass request type → trigger returned unchanged."""
        trigger = _make_trigger(Command("cmd"))
        result = enhance_command_with_args(trigger, str)
        assert len(result.rules) == len(trigger.rules)


# ═══════════════════════════════════════════════════════════════════════════════
# telegrinder_compile
# ═══════════════════════════════════════════════════════════════════════════════


class TestTelegrindCompile:
    def test_returns_dispatch(self) -> None:
        from telegrinder.bot.dispatch import Dispatch

        app = Application()
        dp = telegrinder_compile(app)
        assert isinstance(dp, Dispatch)

    def test_empty_app_returns_empty_dispatch(self) -> None:
        from telegrinder.bot.dispatch import Dispatch

        app = Application()
        dp = telegrinder_compile(app)
        assert isinstance(dp, Dispatch)

    def test_axes_default_used_when_none(self) -> None:
        """When axes=None, compilation still succeeds using Axes.default()."""
        from telegrinder.bot.dispatch import Dispatch

        app = Application()
        dp = telegrinder_compile(app, axes=None)
        assert isinstance(dp, Dispatch)

    def test_handler_registered_in_dispatch(self) -> None:
        """An app with one RRC endpoint should register a handler on Dispatch."""
        from telegrinder.bot.dispatch import Dispatch

        runner = _make_runner()
        app = Application().mount(
            endpoint(runner).expose(
                _make_trigger(Command("test")),
                rrc(_EchoReq, _EchoResp),
            )
        )
        dp = telegrinder_compile(app)
        assert isinstance(dp, Dispatch)
        # Message view should have at least one handler registered after compile
        assert hasattr(dp, "message")

    def test_compile_with_custom_axes(self) -> None:
        """Explicit Axes is accepted and forwarded correctly."""
        from telegrinder.bot.dispatch import Dispatch

        axes = Axes.default()
        app = Application()
        dp = telegrinder_compile(app, axes=axes)
        assert isinstance(dp, Dispatch)

    def test_immediate_endpoint_registered(self) -> None:
        """Immediate codec endpoint compiles without error."""
        from telegrinder.bot.dispatch import Dispatch

        @dataclass
        class HelpResp:
            @classmethod
            def produce(cls) -> Self:
                return cls()

        runner = _make_runner()
        app = Application().mount(
            endpoint(runner).expose(
                _make_trigger(Command("help")),
                immediate(HelpResp),
            )
        )
        dp = telegrinder_compile(app)
        assert isinstance(dp, Dispatch)

    def test_delegate_endpoint_registered(self) -> None:
        """Delegate codec endpoint compiles without error."""
        from telegrinder.bot.dispatch import Dispatch

        async def my_delegate_fn() -> str:
            return "hello"

        runner = _make_runner()
        app = Application().mount(
            endpoint(runner).expose(
                _make_trigger(Command("delegate")),
                delegate(my_delegate_fn),
            )
        )
        dp = telegrinder_compile(app)
        assert isinstance(dp, Dispatch)

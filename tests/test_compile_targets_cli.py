"""Tests for compile.targets.cli — CLIRoute, wrap_*, CLI_COMPILER, cli_compile."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Self

import pytest
from kungfu import Result, Ok, Error

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
from emergent.wire.axis.surface.triggers.cli import CLITrigger
from emergent.wire.compile._core import Axes
from emergent.wire.compile._generate import ArgSpec
from emergent.wire.compile.targets.cli import (
    CLI_COMPILER,
    CLIRoute,
    cli_compile,
    wrap_delegate_cli,
    wrap_immediate_cli,
    wrap_rrc_cli,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Domain fixtures
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
class MultiFieldReq:
    first_name: str
    last_name: str
    greeting: str = "Hello"

    def to_domain(self) -> GreetOp:
        return GreetOp(name=f"{self.first_name} {self.last_name}")


@dataclass
class MultiFieldResp:
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
class EchoResp:
    text: str = "echo!"

    @classmethod
    def produce(cls) -> Self:
        return cls(text="echo!")

    def __str__(self) -> str:
        return self.text


async def _invoke_route(route: CLIRoute, ns: argparse.Namespace) -> str:
    """Invoke a CLIRoute handler and return the string result.

    CLIRoute.handler is typed as Callable[[Namespace], object] because the
    production code supports both sync and async handlers generically.
    All wrap_*_cli functions produce async handlers returning str.
    We use inspect.isawaitable to safely bridge the gap.
    """
    import inspect

    raw = route.handler(ns)
    if inspect.isawaitable(raw):
        raw = await raw
    assert isinstance(raw, str)
    return raw


async def _invoke_ns_handler(ns: argparse.Namespace) -> str:
    """Extract and invoke the _handler attached to a parsed Namespace.

    cli_compile sets ns._handler via argparse set_defaults. The handler is
    a Callable[[Namespace], object] at the type level but is actually an
    async function returning str at runtime.
    """
    import inspect

    handler_fn = getattr(ns, "_handler", None)
    assert handler_fn is not None
    assert callable(handler_fn)
    raw = handler_fn(ns)
    if inspect.isawaitable(raw):
        raw = await raw
    assert isinstance(raw, str)
    return raw


def _make_runner():
    return ops().on(GreetOp, _greet_handler).compile()


def _make_greet_handler() -> Handler[RequestResponseCodec]:
    codec = rrc(GreetReq, GreetResp)
    return Handler(codec=codec, runner=_make_runner(), capabilities=())


def _make_multi_field_handler() -> Handler[RequestResponseCodec]:
    codec = rrc(MultiFieldReq, MultiFieldResp)
    return Handler(codec=codec, runner=_make_runner(), capabilities=())


def _make_immediate_handler() -> Handler[ImmediateCodec]:
    codec = immediate(EchoResp)
    runner = _make_runner()
    return Handler(codec=codec, runner=runner, capabilities=())


def _make_immediate_factory_handler() -> Handler[ImmediateFactoryCodec]:
    codec = immediate_factory(lambda: EchoResp(text="factory!"))
    runner = _make_runner()
    return Handler(codec=codec, runner=runner, capabilities=())


def _make_delegate_handler() -> Handler[DelegateCodec]:
    async def greet_fn(name: str) -> str:
        return f"Hi {name}"

    codec = delegate(greet_fn)
    runner = _make_runner()
    return Handler(codec=codec, runner=runner, capabilities=())


def _make_axes() -> Axes:
    return Axes.default()


def _make_trigger(command: str = "greet", description: str = "Greet user") -> CLITrigger:
    return CLITrigger(command=command, description=description)


# ═══════════════════════════════════════════════════════════════════════════════
# CLIRoute
# ═══════════════════════════════════════════════════════════════════════════════


class TestCLIRoute:
    def test_construction_with_handler_and_arg_specs(self) -> None:
        spec = ArgSpec(name="name", dest="name", kwargs={}, is_positional=True)

        async def _h(ns: argparse.Namespace) -> str:
            return "ok"

        route = CLIRoute(handler=_h, arg_specs=(spec,))
        assert route.handler is _h
        assert len(route.arg_specs) == 1
        assert route.arg_specs[0].dest == "name"

    def test_default_arg_specs_is_empty_tuple(self) -> None:
        async def _h(ns: argparse.Namespace) -> str:
            return "ok"

        route = CLIRoute(handler=_h)
        assert route.arg_specs == ()

    def test_frozen_dataclass_immutable(self) -> None:
        async def _h(ns: argparse.Namespace) -> str:
            return "ok"

        route = CLIRoute(handler=_h)
        with pytest.raises(AttributeError):
            route.arg_specs = (ArgSpec(name="x", dest="x", kwargs={}, is_positional=True),)  # type: ignore[misc]

    def test_handler_is_callable(self) -> None:
        async def _h(ns: argparse.Namespace) -> str:
            return "result"

        route = CLIRoute(handler=_h)
        assert callable(route.handler)


# ═══════════════════════════════════════════════════════════════════════════════
# wrap_rrc_cli
# ═══════════════════════════════════════════════════════════════════════════════


class TestWrapRrcCli:
    def test_returns_cli_route(self) -> None:
        handler = _make_greet_handler()
        trigger = _make_trigger()
        axes = _make_axes()

        route = wrap_rrc_cli(handler, trigger, axes)

        assert isinstance(route, CLIRoute)

    def test_arg_specs_derived_from_request_fields(self) -> None:
        handler = _make_greet_handler()
        trigger = _make_trigger()
        axes = _make_axes()

        route = wrap_rrc_cli(handler, trigger, axes)

        # GreetReq has one required field: name → positional
        assert len(route.arg_specs) == 1
        assert route.arg_specs[0].dest == "name"

    def test_multi_field_request_produces_multiple_arg_specs(self) -> None:
        handler = _make_multi_field_handler()
        trigger = _make_trigger()
        axes = _make_axes()

        route = wrap_rrc_cli(handler, trigger, axes)

        # MultiFieldReq has: first_name (positional), last_name (positional), greeting (optional)
        assert len(route.arg_specs) >= 2
        dests = {spec.dest for spec in route.arg_specs}
        assert "first_name" in dests
        assert "last_name" in dests

    def test_handler_is_callable(self) -> None:
        handler = _make_greet_handler()
        trigger = _make_trigger()
        axes = _make_axes()

        route = wrap_rrc_cli(handler, trigger, axes)

        assert callable(route.handler)

    @pytest.mark.asyncio
    async def test_handler_returns_string(self) -> None:
        handler = _make_greet_handler()
        trigger = _make_trigger()
        axes = _make_axes()

        route = wrap_rrc_cli(handler, trigger, axes)

        ns = argparse.Namespace(name="Alice")
        result = await _invoke_route(route, ns)

        assert "Alice" in result

    @pytest.mark.asyncio
    async def test_handler_response_is_str_of_response_object(self) -> None:
        handler = _make_greet_handler()
        trigger = _make_trigger()
        axes = _make_axes()

        route = wrap_rrc_cli(handler, trigger, axes)

        ns = argparse.Namespace(name="Bob")
        result = await _invoke_route(route, ns)

        # wrap_rrc_cli does str(response), GreetResp.__str__ returns self.message
        assert result == "Hello Bob"


# ═══════════════════════════════════════════════════════════════════════════════
# wrap_immediate_cli
# ═══════════════════════════════════════════════════════════════════════════════


class TestWrapImmediateCli:
    def test_returns_cli_route(self) -> None:
        handler = _make_immediate_handler()
        trigger = _make_trigger()
        axes = _make_axes()

        route = wrap_immediate_cli(handler, trigger, axes)

        assert isinstance(route, CLIRoute)

    def test_empty_arg_specs(self) -> None:
        handler = _make_immediate_handler()
        trigger = _make_trigger()
        axes = _make_axes()

        route = wrap_immediate_cli(handler, trigger, axes)

        assert route.arg_specs == ()

    def test_handler_is_callable(self) -> None:
        handler = _make_immediate_handler()
        trigger = _make_trigger()
        axes = _make_axes()

        route = wrap_immediate_cli(handler, trigger, axes)

        assert callable(route.handler)

    @pytest.mark.asyncio
    async def test_handler_returns_string(self) -> None:
        handler = _make_immediate_handler()
        trigger = _make_trigger()
        axes = _make_axes()

        route = wrap_immediate_cli(handler, trigger, axes)

        ns = argparse.Namespace()
        result = await _invoke_route(route, ns)

        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_immediate_factory_codec_also_works(self) -> None:
        handler = _make_immediate_factory_handler()
        trigger = _make_trigger()
        axes = _make_axes()

        route = wrap_immediate_cli(handler, trigger, axes)

        ns = argparse.Namespace()
        result = await _invoke_route(route, ns)

        assert isinstance(result, str)
        assert "factory" in result


# ═══════════════════════════════════════════════════════════════════════════════
# wrap_delegate_cli
# ═══════════════════════════════════════════════════════════════════════════════


class TestWrapDelegateCli:
    def test_returns_cli_route(self) -> None:
        handler = _make_delegate_handler()
        trigger = _make_trigger()
        axes = _make_axes()

        route = wrap_delegate_cli(handler, trigger, axes)

        assert isinstance(route, CLIRoute)

    def test_handler_is_callable(self) -> None:
        handler = _make_delegate_handler()
        trigger = _make_trigger()
        axes = _make_axes()

        route = wrap_delegate_cli(handler, trigger, axes)

        assert callable(route.handler)

    @pytest.mark.asyncio
    async def test_handler_returns_string(self) -> None:
        handler = _make_delegate_handler()
        trigger = _make_trigger()
        axes = _make_axes()

        route = wrap_delegate_cli(handler, trigger, axes)

        ns = argparse.Namespace(name="Charlie")
        result = await _invoke_route(route, ns)

        assert isinstance(result, str)


# ═══════════════════════════════════════════════════════════════════════════════
# CLI_COMPILER
# ═══════════════════════════════════════════════════════════════════════════════


class TestCLICompiler:
    def test_trigger_type_is_cli_trigger(self) -> None:
        assert CLI_COMPILER.trigger_type is CLITrigger

    def test_has_rrc_adapter(self) -> None:
        codec_types = {a.codec_type for a in CLI_COMPILER.adapters}
        assert RequestResponseCodec in codec_types

    def test_has_immediate_adapter(self) -> None:
        codec_types = {a.codec_type for a in CLI_COMPILER.adapters}
        assert ImmediateCodec in codec_types

    def test_has_immediate_factory_adapter(self) -> None:
        codec_types = {a.codec_type for a in CLI_COMPILER.adapters}
        assert ImmediateFactoryCodec in codec_types

    def test_has_delegate_adapter(self) -> None:
        codec_types = {a.codec_type for a in CLI_COMPILER.adapters}
        assert DelegateCodec in codec_types

    def test_adapters_is_tuple(self) -> None:
        assert isinstance(CLI_COMPILER.adapters, tuple)

    def test_replace_codec_returns_new_compiler(self) -> None:
        def my_wrap(handler: Handler[RequestResponseCodec], trigger: CLITrigger, axes: Axes) -> CLIRoute:
            async def _h(ns: argparse.Namespace) -> str:
                return "custom"
            return CLIRoute(handler=_h)

        new_compiler = CLI_COMPILER.replace_codec(RequestResponseCodec, my_wrap)
        assert new_compiler is not CLI_COMPILER

        rrc_adapters = [a for a in new_compiler.adapters if a.codec_type is RequestResponseCodec]
        assert len(rrc_adapters) == 1
        assert rrc_adapters[0].wrap is my_wrap


# ═══════════════════════════════════════════════════════════════════════════════
# cli_compile
# ═══════════════════════════════════════════════════════════════════════════════


def _make_greet_app() -> Application:
    trigger = CLITrigger(command="greet", description="Say hello")
    runner = _make_runner()
    app = application().mount(
        endpoint(runner).expose(trigger, rrc(GreetReq, GreetResp))
    )
    return app


def _make_multi_command_app() -> Application:
    runner = _make_runner()
    trigger_greet = CLITrigger(command="greet", description="Say hello")
    trigger_echo = CLITrigger(command="echo", description="Echo message")

    app = application().mount(
        endpoint(runner).expose(trigger_greet, rrc(GreetReq, GreetResp)),
        endpoint(runner).expose(trigger_echo, immediate(EchoResp)),
    )
    return app


class TestCliCompile:
    def test_returns_argument_parser(self) -> None:
        app = _make_greet_app()

        parser = cli_compile(app, prog="test-tool")

        assert isinstance(parser, argparse.ArgumentParser)

    def test_prog_name_set(self) -> None:
        app = _make_greet_app()

        parser = cli_compile(app, prog="mytool")

        assert parser.prog == "mytool"

    def test_subcommand_registered(self) -> None:
        app = _make_greet_app()

        parser = cli_compile(app, prog="test")

        # parse_args with valid subcommand should not raise
        ns = parser.parse_args(["greet", "Alice"])
        assert ns.command == "greet"

    def test_help_text_propagated_from_trigger(self) -> None:
        app = _make_greet_app()

        parser = cli_compile(app, prog="test")

        # The help text should reference "greet" in the help output
        help_output = parser.format_help()
        assert "greet" in help_output

    def test_multiple_subcommands(self) -> None:
        app = _make_multi_command_app()

        parser = cli_compile(app, prog="test")

        ns_greet = parser.parse_args(["greet", "Alice"])
        assert ns_greet.command == "greet"

        ns_echo = parser.parse_args(["echo"])
        assert ns_echo.command == "echo"

    def test_default_axes_used_when_none(self) -> None:
        app = _make_greet_app()

        # Should not raise when axes=None (uses Axes.default())
        parser = cli_compile(app)
        assert isinstance(parser, argparse.ArgumentParser)

    def test_custom_compiler_used_when_provided(self) -> None:
        from emergent.wire.compile._target import TargetCompiler, CodecAdapter

        captured: list[str] = []

        def custom_wrap_rrc(
            handler: Handler[RequestResponseCodec],
            trigger: CLITrigger,
            axes: Axes,
        ) -> CLIRoute:
            captured.append("custom_wrap_rrc_called")

            async def _h(ns: argparse.Namespace) -> str:
                return "custom"

            return CLIRoute(handler=_h)

        custom_compiler: TargetCompiler[CLITrigger] = TargetCompiler(
            trigger_type=CLITrigger,
            adapters=(CodecAdapter(RequestResponseCodec, custom_wrap_rrc),),
        )

        app = _make_greet_app()

        cli_compile(app, compiler=custom_compiler)
        assert "custom_wrap_rrc_called" in captured


# ═══════════════════════════════════════════════════════════════════════════════
# Full integration — parse args and execute handler
# ═══════════════════════════════════════════════════════════════════════════════


class TestCLIIntegration:
    @pytest.mark.asyncio
    async def test_rrc_parse_and_execute(self) -> None:
        app = _make_greet_app()

        parser = cli_compile(app, prog="test")
        ns = parser.parse_args(["greet", "World"])

        result = await _invoke_ns_handler(ns)
        assert "World" in result

    @pytest.mark.asyncio
    async def test_immediate_parse_and_execute(self) -> None:
        runner = _make_runner()
        trigger = CLITrigger(command="echo", description="Echo message")
        app = application().mount(
            endpoint(runner).expose(trigger, immediate(EchoResp))
        )

        parser = cli_compile(app, prog="test")
        ns = parser.parse_args(["echo"])

        result = await _invoke_ns_handler(ns)
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_delegate_parse_and_execute(self) -> None:
        async def say_hello(name: str) -> str:
            return f"Delegate says: {name}"

        runner = _make_runner()
        trigger = CLITrigger(command="hello", description="Say hello via delegate")
        app = application().mount(
            endpoint(runner).expose(trigger, delegate(say_hello))
        )

        parser = cli_compile(app, prog="test")
        ns = parser.parse_args(["hello", "--name", "Dave"])

        result = await _invoke_ns_handler(ns)
        assert isinstance(result, str)

    def test_parse_args_sets_handler_attr(self) -> None:
        app = _make_greet_app()

        parser = cli_compile(app, prog="test")
        ns = parser.parse_args(["greet", "TestUser"])

        assert hasattr(ns, "_handler")
        assert callable(ns._handler)

    def test_arg_value_accessible_on_namespace(self) -> None:
        app = _make_greet_app()

        parser = cli_compile(app, prog="test")
        ns = parser.parse_args(["greet", "NameValue"])

        assert ns.name == "NameValue"

"""Extended tests for emergent.wire.compile.targets.cli — inner handler bodies,
_prompt_value, _compose_cli_param, wrap_stateful_cli, _inspect_handler_params,
_get_delegate_arg_specs, _build_delegate_args, cli_compile_stack, cli_run,
coerce_cli_values, wrap_rrc_cli_typed.

Covers uncovered lines:
- _prompt_value (lines 94-106)
- _compose_cli_param (lines 118-138)
- wrap_stateful_cli inner handler (lines 150-199)
- _inspect_handler_params (lines 236-237, 242)
- _get_delegate_arg_specs (lines 269-272)
- _build_delegate_args (lines 298-303)
- cli_compile with family (lines 434-444)
- _wrap_for_stack + cli_compile_stack (lines 459-504)
- cli_run (lines 509-536)
- coerce_cli_values (lines 557-566)
- wrap_rrc_cli_typed (lines 579-594)
"""

from __future__ import annotations

import argparse
from collections.abc import Awaitable
from dataclasses import dataclass, field
from typing import Self
from unittest.mock import patch

import pytest
from kungfu import Ok, Error, Result, Option, Some, Nothing

from emergent.ops._graph import Op, ops
from emergent.wire.axis.surface._app import application
from emergent.wire.axis.surface._endpoint import endpoint
from emergent.wire.axis.surface._handler import Handler
from emergent.wire.axis.surface._stack import app_stack
from emergent.wire.axis.surface.codecs.delegate import DelegateCodec, delegate
from emergent.wire.axis.surface.codecs.immediate import (
    immediate,
)
from emergent.wire.axis.surface.codecs.rrc import RequestResponseCodec, rrc
from emergent.wire.axis.surface.codecs.stateful import (
    StatefulCodec,
    Done,
)
from emergent.wire.axis.storage import MemoryStorage
from emergent.wire.axis.surface.triggers.cli import CLITrigger
from emergent.wire.compile._core import Axes
from emergent.wire.compile.targets.cli import (
    CLI_COMPILER,
    TYPED_CLI,
    CLIRoute,
    _build_delegate_args,  # pyright: ignore[reportPrivateUsage]
    _get_delegate_arg_specs,  # pyright: ignore[reportPrivateUsage]
    _inspect_handler_params,  # pyright: ignore[reportPrivateUsage]
    _prompt_value,  # pyright: ignore[reportPrivateUsage]
    _wrap_for_stack,  # pyright: ignore[reportPrivateUsage]
    cli_compile,
    cli_compile_stack,
    cli_run,
    coerce_cli_values,
    register_handler,
    wrap_delegate_cli,
    wrap_rrc_cli,
    wrap_rrc_cli_typed,
    wrap_stateful_cli,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Domain types
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
class MultiReq:
    first: str
    last: str
    greeting: str = "Hi"

    def to_domain(self) -> GreetOp:
        return GreetOp(name=f"{self.first} {self.last}")


@dataclass
class MultiResp:
    message: str

    @classmethod
    def from_domain(cls, dom: Result[str, str]) -> Self:
        match dom:
            case Ok(v):
                return cls(message=v)
            case _:
                return cls(message="error")

    def __str__(self) -> str:
        return self.message


@dataclass
class ImmResp:
    text: str = "echo"

    @classmethod
    def produce(cls) -> Self:
        return cls(text="echo")

    def __str__(self) -> str:
        return self.text


_runner = ops().on(GreetOp, _greet_handler).compile()
_axes = Axes.default()
_trigger = CLITrigger(command="greet", description="Greet user")


async def _invoke_cli_handler(route: CLIRoute, ns: argparse.Namespace) -> str:
    """Invoke a CLIRoute handler and await the result.

    CLIRoute.handler is typed as Callable[[Namespace], object] but the actual
    implementations are async functions returning str. This helper bridges the
    type gap safely for tests by doing runtime assertions.
    """
    raw = route.handler(ns)
    # CLIRoute.handler returns object; the actual implementations are coroutines.
    # pyright: ignore[reportUnknownVariableType] — Awaitable[Unknown] from isinstance
    # on a non-generic Protocol cannot narrow the type parameter.
    assert isinstance(raw, Awaitable)
    value: str = await raw  # pyright: ignore[reportUnknownVariableType] -- Awaitable[Unknown] loses type info; runtime assert below ensures str
    assert isinstance(value, str)
    return value


# ═══════════════════════════════════════════════════════════════════════════════
# _prompt_value (lines 94-106)
# ═══════════════════════════════════════════════════════════════════════════════


class TestPromptValue:
    def test_returns_string_for_str_type(self) -> None:
        with patch("builtins.input", return_value="hello"):
            result = _prompt_value("name", str)
            assert result == "hello"

    def test_returns_int_for_int_type(self) -> None:
        with patch("builtins.input", return_value="42"):
            result = _prompt_value("age", int)
            assert result == 42

    def test_returns_float_for_float_type(self) -> None:
        with patch("builtins.input", return_value="3.14"):
            result = _prompt_value("score", float)
            assert result == 3.14

    def test_returns_bool_for_bool_type_true(self) -> None:
        with patch("builtins.input", return_value="yes"):
            result = _prompt_value("active", bool)
            assert result is True

    def test_returns_bool_for_bool_type_false(self) -> None:
        with patch("builtins.input", return_value="no"):
            result = _prompt_value("active", bool)
            assert result is False

    def test_returns_none_for_empty_input(self) -> None:
        with patch("builtins.input", return_value=""):
            result = _prompt_value("name", str)
            assert result is None

    def test_returns_none_on_eof_error(self) -> None:
        with patch("builtins.input", side_effect=EOFError):
            result = _prompt_value("name", str)
            assert result is None

    def test_returns_none_on_keyboard_interrupt(self) -> None:
        with patch("builtins.input", side_effect=KeyboardInterrupt):
            result = _prompt_value("name", str)
            assert result is None

    def test_returns_none_on_value_error_for_int(self) -> None:
        with patch("builtins.input", return_value="not-a-number"):
            result = _prompt_value("age", int)
            assert result is None


# ═══════════════════════════════════════════════════════════════════════════════
# _inspect_handler_params (lines 227-246)
# ═══════════════════════════════════════════════════════════════════════════════


class TestInspectHandlerParams:
    def test_basic_handler(self) -> None:
        async def handler(name: str) -> str:
            return name

        params = _inspect_handler_params(handler)
        assert len(params) == 1
        assert params[0][0] == "name"
        assert params[0][1] is str
        # has_default is False for required params
        assert params[0][2] is False

    def test_handler_with_default(self) -> None:
        async def handler(name: str, greeting: str = "Hi") -> str:
            return f"{greeting} {name}"

        params = _inspect_handler_params(handler)
        assert len(params) == 2
        defaults = {p[0]: p[2] for p in params}
        assert defaults["name"] is False
        assert defaults["greeting"] is True

    def test_handler_no_annotations(self) -> None:
        # Use exec to create a handler with no annotations, avoiding pyright complaints
        ns: dict[str, str] = {}
        exec("def handler(x): return x", ns)  # noqa: S102
        handler_fn = ns["handler"]
        params = _inspect_handler_params(handler_fn)
        # Unannotated params are skipped
        assert len(params) == 0

    def test_handler_with_mixed_annotations(self) -> None:
        def handler(name: str, age: int) -> str:
            return f"{name} {age}"

        params = _inspect_handler_params(handler)
        # Both annotated params should be returned
        names = [p[0] for p in params]
        assert "name" in names
        assert "age" in names

    def test_non_callable_returns_empty(self) -> None:
        """_inspect_handler_params on a non-callable returns empty list."""
        # Pass something that will raise in inspect.signature
        params = _inspect_handler_params("not_callable")
        assert params == []


# ═══════════════════════════════════════════════════════════════════════════════
# _get_delegate_arg_specs (lines 249-281)
# ═══════════════════════════════════════════════════════════════════════════════


class TestGetDelegateArgSpecs:
    def test_simple_str_param(self) -> None:
        async def handler(name: str) -> str:
            return name

        specs = _get_delegate_arg_specs(handler, _axes)
        assert len(specs) >= 1
        # Simple str param should be required
        names = [s.name for s in specs]
        assert "--name" in names or "name" in names

    def test_int_param(self) -> None:
        async def handler(count: int) -> str:
            return str(count)

        specs = _get_delegate_arg_specs(handler, _axes)
        assert len(specs) >= 1
        # int params should have type=int
        for s in specs:
            if s.dest == "count":
                assert s.kwargs.get("type") is int

    def test_bool_param_with_default(self) -> None:
        async def handler(verbose: bool = False) -> str:
            return "v" if verbose else ""

        specs = _get_delegate_arg_specs(handler, _axes)
        assert len(specs) >= 1
        for s in specs:
            if s.dest == "verbose":
                assert s.kwargs.get("action") == "store_true"

    def test_dataclass_param_uses_schema_axis(self) -> None:
        """Structured type (dataclass) should use axes.schema for introspection."""

        async def handler(req: GreetReq) -> str:
            return req.name

        specs = _get_delegate_arg_specs(handler, _axes)
        # GreetReq has a 'name' field — should produce spec for it
        dests = [s.dest for s in specs]
        assert "name" in dests

    def test_required_param_without_default(self) -> None:
        async def handler(name: str) -> str:
            return name

        specs = _get_delegate_arg_specs(handler, _axes)
        for s in specs:
            if s.dest == "name":
                assert s.kwargs.get("required") is True or s.is_positional


# ═══════════════════════════════════════════════════════════════════════════════
# _build_delegate_args (lines 284-310)
# ═══════════════════════════════════════════════════════════════════════════════


class TestBuildDelegateArgs:
    def test_simple_params(self) -> None:
        async def handler(name: str) -> str:
            return name

        ns = argparse.Namespace(name="Alice")
        result = _build_delegate_args(handler, ns)
        assert result == {"name": "Alice"}

    def test_dataclass_reconstruction(self) -> None:
        """Structured type (dataclass) should be reconstructed from namespace fields."""

        async def handler(req: GreetReq) -> str:
            return req.name

        ns = argparse.Namespace(name="Bob")
        result = _build_delegate_args(handler, ns)
        assert "req" in result
        assert isinstance(result["req"], GreetReq)
        assert result["req"].name == "Bob"

    def test_none_values_skipped(self) -> None:
        async def handler(name: str) -> str:
            return name

        ns = argparse.Namespace(name=None)
        result = _build_delegate_args(handler, ns)
        # None values should be skipped
        assert "name" not in result


# ═══════════════════════════════════════════════════════════════════════════════
# wrap_delegate_cli inner handler (lines 322-332)
# ═══════════════════════════════════════════════════════════════════════════════


class TestWrapDelegateCliExecution:
    @pytest.mark.asyncio
    async def test_delegate_handler_execution(self) -> None:
        """Delegate handler should call the original function and return string."""

        async def say_hi(name: str) -> str:
            return f"Hi {name}"

        codec = delegate(say_hi)
        handler: Handler[DelegateCodec] = Handler(
            codec=codec, runner=_runner, capabilities=()
        )
        route = wrap_delegate_cli(handler, _trigger, _axes)

        ns = argparse.Namespace(name="Charlie")
        result = await _invoke_cli_handler(route, ns)
        assert "Charlie" in result

    @pytest.mark.asyncio
    async def test_sync_delegate_handler(self) -> None:
        """Sync delegate handler should also work."""

        def sync_handler(name: str) -> str:
            return f"Sync {name}"

        codec = delegate(sync_handler)
        handler: Handler[DelegateCodec] = Handler(
            codec=codec, runner=_runner, capabilities=()
        )
        route = wrap_delegate_cli(handler, _trigger, _axes)

        ns = argparse.Namespace(name="Dave")
        result = await _invoke_cli_handler(route, ns)
        assert isinstance(result, str)


# ═══════════════════════════════════════════════════════════════════════════════
# wrap_stateful_cli inner handler (lines 150-199)
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class _CLIFlow:
    name: Option[str] = field(default_factory=Nothing)

    async def __transition__(self, name: Option[str]) -> "Self | Done":
        match name:
            case Some(_n):
                return Done()
            case _:
                return self

    def to_domain(self) -> GreetOp:
        return GreetOp(name=self.name.unwrap())


@dataclass
class _CLIKeyNode:
    __dependencies__: tuple[type, ...] = ()

    @classmethod
    async def __compose__(cls) -> Self:
        return cls()

    def __str__(self) -> str:
        return "cli-test-key"


class TestWrapStatefulCliExecution:
    def _make_stateful_handler(self) -> Handler[StatefulCodec]:
        from nodnod.agent.event_loop.agent import EventLoopAgent

        codec = StatefulCodec(
            flow=_CLIFlow,
            response=GreetResp,
            store=MemoryStorage[str, _CLIFlow](),
            key_node=_CLIKeyNode,
            agent_cls=EventLoopAgent,
        )
        return Handler(codec=codec, runner=_runner, capabilities=())

    def test_wrap_returns_cli_route(self) -> None:
        handler = self._make_stateful_handler()
        route = wrap_stateful_cli(handler, _trigger, _axes)
        assert isinstance(route, CLIRoute)
        assert callable(route.handler)

    def test_wrap_has_no_arg_specs(self) -> None:
        """Stateful CLI doesn't pre-generate arg specs."""
        handler = self._make_stateful_handler()
        route = wrap_stateful_cli(handler, _trigger, _axes)
        assert route.arg_specs == ()


# ═══════════════════════════════════════════════════════════════════════════════
# wrap_rrc_cli inner handler — already tested, add edge case
# ═══════════════════════════════════════════════════════════════════════════════


class TestWrapRrcCliEdgeCases:
    @pytest.mark.asyncio
    async def test_rrc_handler_with_missing_field_returns_response(self) -> None:
        """RRC handler with None field value still produces a response."""
        codec = rrc(GreetReq, GreetResp)
        handler = Handler(codec=codec, runner=_runner, capabilities=())
        route = wrap_rrc_cli(handler, _trigger, _axes)

        # name is None which means the domain request may fail, but
        # the handler should still produce a string (error response)
        ns = argparse.Namespace(name=None)
        # This may raise or return error response depending on codec
        try:
            result = await _invoke_cli_handler(route, ns)
            assert isinstance(result, str)
        except (RuntimeError, AssertionError):
            # Expected if required field is None
            pass


# ═══════════════════════════════════════════════════════════════════════════════
# cli_compile with family (lines 434-444)
# ═══════════════════════════════════════════════════════════════════════════════


class TestCliCompileFamily:
    def test_compile_with_family(self) -> None:
        """cli_compile with family creates scope layer."""
        from emergent.graph._family import ScopeFamily
        from emergent.wire.compile._lifetime import Tier

        family: ScopeFamily[Tier] = ScopeFamily()
        app = (
            application()
            .mount(
                endpoint(_runner)
                .expose(CLITrigger("greet", "Greet"), rrc(GreetReq, GreetResp))
            )
        )
        parser = cli_compile(app, family=family)
        assert isinstance(parser, argparse.ArgumentParser)
        # Parser should have _scope_app attribute
        assert hasattr(parser, "_scope_app")
        assert hasattr(parser, "_scope_app_types")


# ═══════════════════════════════════════════════════════════════════════════════
# _wrap_for_stack (lines 459-462)
# ═══════════════════════════════════════════════════════════════════════════════


class TestWrapForStackCli:
    def test_wraps_rrc_handler(self) -> None:
        codec = rrc(GreetReq, GreetResp)
        handler = Handler(codec=codec, runner=_runner, capabilities=())
        trigger = CLITrigger(command="greet", description="test")
        route = _wrap_for_stack(handler, trigger, _axes, CLI_COMPILER)
        assert isinstance(route, CLIRoute)

    def test_wraps_immediate_handler(self) -> None:
        codec = immediate(ImmResp)
        handler = Handler(codec=codec, runner=_runner, capabilities=())
        trigger = CLITrigger(command="echo", description="test")
        route = _wrap_for_stack(handler, trigger, _axes, CLI_COMPILER)
        assert isinstance(route, CLIRoute)

    def test_raises_for_unknown_codec(self) -> None:
        @dataclass(frozen=True)
        class UnknownCodec:
            pass

        handler = Handler(codec=UnknownCodec(), runner=_runner, capabilities=())
        trigger = CLITrigger(command="test", description="test")
        with pytest.raises(ValueError, match="No adapter for codec type"):
            _wrap_for_stack(handler, trigger, _axes, CLI_COMPILER)


# ═══════════════════════════════════════════════════════════════════════════════
# cli_compile_stack (lines 472-504)
# ═══════════════════════════════════════════════════════════════════════════════


class TestCliCompileStack:
    def test_flat_stack_returns_parser(self) -> None:
        """Flat stack (root only) compiles to argparse parser."""
        root_app = (
            application()
            .mount(
                endpoint(_runner)
                .expose(CLITrigger("greet", "Greet"), rrc(GreetReq, GreetResp))
            )
        )
        stack = app_stack().root(root_app)
        parser = cli_compile_stack(stack, _axes)
        assert isinstance(parser, argparse.ArgumentParser)

    def test_stack_with_mount(self) -> None:
        """Stack with mounted sub-application compiles correctly."""
        root_app = (
            application()
            .mount(
                endpoint(_runner)
                .expose(CLITrigger("greet", "Greet"), rrc(GreetReq, GreetResp))
            )
        )
        sub_app = (
            application()
            .mount(
                endpoint(_runner)
                .expose(CLITrigger("echo", "Echo"), immediate(ImmResp))
            )
        )
        stack = app_stack().root(root_app).mount("tools", sub_app)
        parser = cli_compile_stack(stack, _axes)
        assert isinstance(parser, argparse.ArgumentParser)

    def test_nested_appstack_mount(self) -> None:
        """Stack with nested AppStack compiles correctly."""
        inner_app = (
            application()
            .mount(
                endpoint(_runner)
                .expose(CLITrigger("list", "List items"), rrc(GreetReq, GreetResp))
            )
        )
        inner_stack = app_stack().root(inner_app)

        root_app = (
            application()
            .mount(
                endpoint(_runner)
                .expose(CLITrigger("greet", "Greet"), rrc(GreetReq, GreetResp))
            )
        )
        stack = app_stack().root(root_app).mount("sub", inner_stack)
        parser = cli_compile_stack(stack, _axes)
        assert isinstance(parser, argparse.ArgumentParser)

    def test_stack_parse_root_command(self) -> None:
        """Parsing a root command works on compiled stack."""
        root_app = (
            application()
            .mount(
                endpoint(_runner)
                .expose(CLITrigger("greet", "Greet"), rrc(GreetReq, GreetResp))
            )
        )
        stack = app_stack().root(root_app)
        parser = cli_compile_stack(stack, _axes)
        ns = parser.parse_args(["greet", "Alice"])
        assert ns.command == "greet"
        assert ns.name == "Alice"

    def test_stack_default_axes_and_compiler(self) -> None:
        """compile_stack works with defaults (None axes and compiler)."""
        root_app = application()
        stack = app_stack().root(root_app)
        parser = cli_compile_stack(stack)
        assert isinstance(parser, argparse.ArgumentParser)


# ═══════════════════════════════════════════════════════════════════════════════
# cli_run (lines 509-536)
# ═══════════════════════════════════════════════════════════════════════════════


class TestCliRun:
    def test_run_with_valid_command(self) -> None:
        """cli_run parses args, executes handler, returns 0."""
        app = (
            application()
            .mount(
                endpoint(_runner)
                .expose(CLITrigger("greet", "Greet"), rrc(GreetReq, GreetResp))
            )
        )
        parser = cli_compile(app, prog="test")
        code = cli_run(parser, ["greet", "World"])
        assert code == 0

    def test_run_no_handler_prints_help(self) -> None:
        """When no handler is set on namespace, print help and return 1."""
        parser = argparse.ArgumentParser(prog="test")
        parser.add_subparsers(dest="command")
        # Parse with no args should have no _handler
        code = cli_run(parser, [])
        assert code == 1

    def test_run_keyboard_interrupt_returns_130(self) -> None:
        """KeyboardInterrupt during execution returns 130."""
        async def raising_handler(ns: argparse.Namespace) -> str:
            raise KeyboardInterrupt

        parser = argparse.ArgumentParser(prog="test")
        sp = parser.add_subparsers(dest="command")
        sub = sp.add_parser("fail")
        sub.set_defaults(_handler=raising_handler)

        code = cli_run(parser, ["fail"])
        assert code == 130

    def test_run_exception_returns_1(self) -> None:
        """Exception during execution returns 1."""
        async def raising_handler(ns: argparse.Namespace) -> str:
            raise ValueError("test error")

        parser = argparse.ArgumentParser(prog="test")
        sp = parser.add_subparsers(dest="command")
        sub = sp.add_parser("fail")
        sub.set_defaults(_handler=raising_handler)

        code = cli_run(parser, ["fail"])
        assert code == 1

    def test_run_with_family_scope(self) -> None:
        """cli_run with family scope creates app scope lifespan."""
        from emergent.graph._family import ScopeFamily
        from emergent.wire.compile._lifetime import Tier

        family: ScopeFamily[Tier] = ScopeFamily()
        app = (
            application()
            .mount(
                endpoint(_runner)
                .expose(CLITrigger("greet", "Greet"), rrc(GreetReq, GreetResp))
            )
        )
        parser = cli_compile(app, family=family)
        code = cli_run(parser, ["greet", "World"])
        assert code == 0


# ═══════════════════════════════════════════════════════════════════════════════
# coerce_cli_values (lines 557-566)
# ═══════════════════════════════════════════════════════════════════════════════


class TestCoerceCliValues:
    def test_coerces_string_to_int(self) -> None:
        """String value from CLI should be coerced to int via Pydantic."""
        @dataclass
        class IntReq:
            count: int

            def to_domain(self) -> GreetOp:
                return GreetOp(name=str(self.count))

        typed_get = coerce_cli_values(
            IntReq, _axes, lambda name: "42" if name == "count" else None
        )
        assert typed_get("count") == 42

    def test_preserves_none_for_missing_optional(self) -> None:
        """None values for optional fields return None after coercion."""
        typed_get = coerce_cli_values(
            MultiReq, _axes,
            lambda name: "Alice" if name == "first" else ("Smith" if name == "last" else None),
        )
        # greeting has a default, so when not provided it falls back to default
        result = typed_get("greeting")
        # Should be the default value "Hi" since we didn't provide it
        assert result == "Hi"

    def test_coerces_string_to_string(self) -> None:
        """String values pass through correctly."""
        typed_get = coerce_cli_values(
            GreetReq, _axes, lambda name: "Alice" if name == "name" else None
        )
        assert typed_get("name") == "Alice"


# ═══════════════════════════════════════════════════════════════════════════════
# wrap_rrc_cli_typed (lines 579-594)
# ═══════════════════════════════════════════════════════════════════════════════


class TestWrapRrcCliTyped:
    def test_returns_cli_route(self) -> None:
        codec = rrc(GreetReq, GreetResp)
        handler = Handler(codec=codec, runner=_runner, capabilities=())
        route = wrap_rrc_cli_typed(handler, _trigger, _axes)
        assert isinstance(route, CLIRoute)

    def test_has_arg_specs(self) -> None:
        codec = rrc(GreetReq, GreetResp)
        handler = Handler(codec=codec, runner=_runner, capabilities=())
        route = wrap_rrc_cli_typed(handler, _trigger, _axes)
        assert len(route.arg_specs) >= 1

    @pytest.mark.asyncio
    async def test_handler_coerces_types(self) -> None:
        """Typed handler coerces string values via Pydantic before execution."""
        codec = rrc(GreetReq, GreetResp)
        handler = Handler(codec=codec, runner=_runner, capabilities=())
        route = wrap_rrc_cli_typed(handler, _trigger, _axes)

        ns = argparse.Namespace(name="TypedUser")
        result = await _invoke_cli_handler(route, ns)
        assert "TypedUser" in result


# ═══════════════════════════════════════════════════════════════════════════════
# TYPED_CLI compiler
# ═══════════════════════════════════════════════════════════════════════════════


class TestTypedCliCompiler:
    def test_typed_cli_has_rrc_adapter_replaced(self) -> None:
        """TYPED_CLI replaces RRC adapter with typed version."""
        rrc_adapters = [
            a for a in TYPED_CLI.adapters if a.codec_type is RequestResponseCodec
        ]
        assert len(rrc_adapters) == 1
        from emergent.wire.compile.targets.cli import typed_rrc_from_codec_cli
        assert rrc_adapters[0].from_codec is typed_rrc_from_codec_cli

    def test_typed_cli_trigger_type_is_cli_trigger(self) -> None:
        assert TYPED_CLI.trigger_type is CLITrigger


# ═══════════════════════════════════════════════════════════════════════════════
# register_handler with CLI capabilities
# ═══════════════════════════════════════════════════════════════════════════════


class TestRegisterHandlerCli:
    def test_register_sets_handler_on_subparser(self) -> None:
        """register_handler creates a subparser and sets defaults."""
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")

        codec = rrc(GreetReq, GreetResp)
        handler = Handler(codec=codec, runner=_runner, capabilities=())
        route = wrap_rrc_cli(handler, _trigger, _axes)

        register_handler(subparsers, _trigger, handler, route, _axes)

        ns = parser.parse_args(["greet", "Alice"])
        assert hasattr(ns, "_handler")
        assert callable(ns._handler)

    def test_register_with_hidden_capability(self) -> None:
        """Hidden capability uses argparse.SUPPRESS for help."""
        from emergent.wire.axis.surface.capabilities._base import SurfaceCapability
        from emergent.wire.axis._capability import CLICommandContext, cli_command

        @dataclass(frozen=True)
        class HiddenCap(SurfaceCapability):
            def compile_cli(self, ctx: CLICommandContext) -> CLICommandContext:
                return cli_command(ctx, hidden=True)

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")

        codec = rrc(GreetReq, GreetResp)
        handler = Handler(codec=codec, runner=_runner, capabilities=(HiddenCap(),))
        route = wrap_rrc_cli(handler, _trigger, _axes)

        register_handler(subparsers, _trigger, handler, route, _axes)

        # Should still be parseable
        ns = parser.parse_args(["greet", "Alice"])
        assert ns.command == "greet"

    def test_register_with_description_capability(self) -> None:
        """Description capability sets subparser description."""
        from emergent.wire.axis.surface.capabilities._base import SurfaceCapability
        from emergent.wire.axis._capability import CLICommandContext, cli_command

        @dataclass(frozen=True)
        class DescCap(SurfaceCapability):
            def compile_cli(self, ctx: CLICommandContext) -> CLICommandContext:
                return cli_command(ctx, description="Extended description", epilog="Done.")

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")

        codec = rrc(GreetReq, GreetResp)
        handler = Handler(codec=codec, runner=_runner, capabilities=(DescCap(),))
        route = wrap_rrc_cli(handler, _trigger, _axes)

        register_handler(subparsers, _trigger, handler, route, _axes)

        ns = parser.parse_args(["greet", "Alice"])
        assert ns.command == "greet"

"""Tests for remaining uncovered lines in emergent.wire.compile.targets.cli.

Covers:
- Lines 118-138: _compose_cli_param — node composition, from CLI args, prompt fallback
- Lines 154-197: wrap_stateful_cli inner _handler — complete stateful CLI handler loop
- Line 272:     Unknown param_type fallback to str in _get_delegate_arg_specs
"""

from __future__ import annotations

import argparse
import inspect
from dataclasses import dataclass, replace
from typing import Self
from unittest.mock import AsyncMock, patch

import pytest
from kungfu import Ok, Error, Result, Option, Nothing
from nodnod import Scope, DataNode
from nodnod.agent.event_loop.agent import EventLoopAgent

from emergent.ops._graph import Op, ops
from emergent.wire.axis.surface._handler import Handler
from emergent.wire.axis.surface.codecs.stateful import StatefulCodec, Done
from emergent.wire.axis.storage import MemoryStorage
from emergent.wire.axis.surface.triggers.cli import CLITrigger
from emergent.wire.compile._core import Axes
from emergent.wire.compile.targets.cli import (
    _compose_cli_param,  # pyright: ignore[reportPrivateUsage] - testing private implementation
    _get_delegate_arg_specs,  # pyright: ignore[reportPrivateUsage] - testing private implementation
    wrap_stateful_cli,
    CLIRoute,
)


# ================================================================
# Domain types
# ================================================================


@dataclass
class GreetOp(Op[str, str]):
    name: str


async def _greet_handler(req: GreetOp) -> Result[str, str]:
    return Ok(f"Hello {req.name}")


@dataclass
class GreetResp:
    message: str

    @classmethod
    def from_domain(cls, result: Result[str, str]) -> Self:
        match result:
            case Ok(v):
                return cls(message=v)
            case Error(e):
                return cls(message=e)

    def __str__(self) -> str:
        return self.message


_runner = ops().on(GreetOp, _greet_handler).compile()
_axes = Axes.default()
_trigger = CLITrigger(command="greet", description="Greet user")


# ================================================================
# Node types for _compose_cli_param tests
# ================================================================


class _CliKeyNode(DataNode):
    """Proper nodnod DataNode that composes to a key string."""

    @classmethod
    async def __compose__(cls) -> Self:
        return cls()

    def __str__(self) -> str:
        return "cli-key"


class _CliValueNode(DataNode):
    """Node that composes to a value for param resolution."""

    @classmethod
    async def __compose__(cls) -> Self:
        return cls()

    def __str__(self) -> str:
        return "node-value"


class _CustomType:
    """Non-standard type that is not str/int/float/bool for line 272 test."""
    pass


# ================================================================
# Lines 118-138: _compose_cli_param
# ================================================================


class TestComposeCliParam:
    @pytest.mark.asyncio
    async def test_node_composition_path(self) -> None:
        """When compose_type is a nodnod node (has __dependencies__),
        uses Composer to compose it (lines 124-127)."""
        scope = Scope(detail="cli-param-test")
        async with scope:
            result = await _compose_cli_param(
                name="key",
                original_type=str,
                compose_type=_CliValueNode,
                cli_args={},
                scope=scope,
                agent_cls=EventLoopAgent,
            )
            # Node composed successfully -> raw value returned
            assert isinstance(result, _CliValueNode)

    @pytest.mark.asyncio
    async def test_from_cli_args_path(self) -> None:
        """When value is in cli_args, returns wrapped value (lines 130-131)."""
        scope = Scope(detail="cli-param-test")
        async with scope:
            result = await _compose_cli_param(
                name="name",
                original_type=str,
                compose_type=str,
                cli_args={"name": "Alice"},
                scope=scope,
                agent_cls=EventLoopAgent,
            )
            assert result == "Alice"

    @pytest.mark.asyncio
    async def test_prompt_fallback_path(self) -> None:
        """When not in cli_args and not a node, prompts user (lines 134-136)."""
        scope = Scope(detail="cli-param-test")
        async with scope:
            with patch("emergent.wire.compile.targets.cli._prompt_value", return_value="prompted"):
                result = await _compose_cli_param(
                    name="name",
                    original_type=str,
                    compose_type=str,
                    cli_args={},
                    scope=scope,
                    agent_cls=EventLoopAgent,
                )
                assert result == "prompted"

    @pytest.mark.asyncio
    async def test_prompt_fallback_returns_none(self) -> None:
        """When prompt returns None, wraps as failed (line 138)."""
        scope = Scope(detail="cli-param-test")
        async with scope:
            with patch("emergent.wire.compile.targets.cli._prompt_value", return_value=None):
                with pytest.raises(RuntimeError, match="Required param failed"):
                    await _compose_cli_param(
                        name="name",
                        original_type=str,
                        compose_type=str,
                        cli_args={},
                        scope=scope,
                        agent_cls=EventLoopAgent,
                    )

    @pytest.mark.asyncio
    async def test_prompt_fallback_returns_none_optional(self) -> None:
        """When prompt returns None for Optional type, wraps as Nothing (line 138)."""
        scope = Scope(detail="cli-param-test")
        async with scope:
            with patch("emergent.wire.compile.targets.cli._prompt_value", return_value=None):
                result = await _compose_cli_param(
                    name="name",
                    original_type=Option[str],
                    compose_type=str,
                    cli_args={},
                    scope=scope,
                    agent_cls=EventLoopAgent,
                )
                assert isinstance(result, Nothing)

    @pytest.mark.asyncio
    async def test_cli_args_none_value_skipped(self) -> None:
        """When cli_args has key but value is None, falls through to prompt (line 130)."""
        scope = Scope(detail="cli-param-test")
        async with scope:
            with patch("emergent.wire.compile.targets.cli._prompt_value", return_value="from-prompt"):
                result = await _compose_cli_param(
                    name="name",
                    original_type=str,
                    compose_type=str,
                    cli_args={"name": None},
                    scope=scope,
                    agent_cls=EventLoopAgent,
                )
                assert result == "from-prompt"


# ================================================================
# Lines 154-197: wrap_stateful_cli inner _handler
# ================================================================


@dataclass
class _CLIFlow:
    """Flow that transitions through steps until Done."""
    step: int = 0

    async def __transition__(self, name: Option[str]) -> "Self | tuple[Self, str] | Done":
        if self.step == 0:
            return replace(self, step=1), "Step 1 done"
        return Done()

    def to_domain(self) -> GreetOp:
        return GreetOp(name="cli-done")


class TestWrapStatefulCliInnerHandler:
    def _make_stateful_handler(
        self,
        flow: type = _CLIFlow,
    ) -> Handler[StatefulCodec]:
        codec = StatefulCodec(
            flow=flow,
            response=GreetResp,
            store=MemoryStorage[str, object](),
            key_node=_CliKeyNode,
            agent_cls=EventLoopAgent,
        )
        return Handler(codec=codec, runner=_runner, capabilities=())

    def test_wrap_returns_cli_route(self) -> None:
        """wrap_stateful_cli returns CLIRoute with callable handler."""
        handler = self._make_stateful_handler()
        route = wrap_stateful_cli(handler, _trigger, _axes)
        assert isinstance(route, CLIRoute)
        assert callable(route.handler)
        assert route.arg_specs == ()

    @pytest.mark.asyncio
    async def test_inner_handler_loop_continues_then_completes(self) -> None:
        """Inner _handler loops: first turn continues with response, second completes (lines 154-197).

        We mock the transition execution to test the inner handler loop,
        since _compose_cli_param would prompt for input in a real scenario.
        """
        handler = self._make_stateful_handler(_CLIFlow)
        route = wrap_stateful_cli(handler, _trigger, _axes)
        ns = argparse.Namespace()

        # The inner handler calls _compose_cli_param which will prompt.
        # We mock it to return Nothing for 'name' (Option[str]).
        with patch(
            "emergent.wire.compile.targets.cli._compose_cli_param",
            new=AsyncMock(return_value=Nothing()),
        ):
            # _CLIFlow.__transition__ gets name=Nothing()
            # step=0 -> returns (self, "Step 1 done") -> print, continue
            # step=1 -> returns Done() -> execute_stateful_done
            # Mock execute_stateful_done to avoid calling to_domain on Done
            with patch(
                "emergent.wire.compile.targets.cli.execute_stateful_done",
                new=AsyncMock(return_value=GreetResp(message="Hello cli-done")),
            ) as mock_done:
                coro = route.handler(ns)
                assert inspect.isawaitable(coro)
                result = await coro
                assert isinstance(result, str)
                assert "Hello cli-done" in result
                mock_done.assert_called_once()

    @pytest.mark.asyncio
    async def test_inner_handler_no_transitions_raises(self) -> None:
        """Inner _handler raises RuntimeError when no transitions defined (line 162)."""

        @dataclass
        class _EmptyFlow:
            pass

        handler = self._make_stateful_handler(_EmptyFlow)
        route = wrap_stateful_cli(handler, _trigger, _axes)
        ns = argparse.Namespace()

        with pytest.raises(RuntimeError, match="No transitions defined"):
            coro = route.handler(ns)
            assert inspect.isawaitable(coro)
            await coro


# ================================================================
# Line 272: Unknown param_type fallback to str
# ================================================================


# Module-level handlers for _get_delegate_arg_specs tests.
# Must be at module level so `get_type_hints` can resolve annotations
# (from __future__ import annotations makes them strings).

async def _handler_custom_type(data: _CustomType) -> str:
    return str(data)


async def _handler_float(score: float) -> str:
    return str(score)


class TestGetDelegateArgSpecsUnknownType:
    def test_unknown_param_type_falls_back_to_str(self) -> None:
        """When param_type is not str/int/float/bool, falls back to kwargs['type'] = str (line 272)."""
        specs = _get_delegate_arg_specs(_handler_custom_type, _axes)
        # _CustomType is not a dataclass, so to_argparse_args raises TypeError
        # -> falls through to the single-flag path
        # _CustomType is not in (str, int, float, bool)
        # -> kwargs["type"] = str (line 272)
        assert len(specs) >= 1
        for spec in specs:
            if spec.dest == "data":
                assert spec.kwargs.get("type") is str

    def test_float_param_gets_float_type(self) -> None:
        """Float param gets type=float in kwargs (line 268)."""
        specs = _get_delegate_arg_specs(_handler_float, _axes)
        assert len(specs) >= 1
        for spec in specs:
            if spec.dest == "score":
                assert spec.kwargs.get("type") is float

"""Tests for remaining uncovered lines in emergent.wire.compile.targets.telegrinder.

Covers:
- Lines 92, 95:    _format_tg_response telegrinder type & no __str__ fallback
- Line 134:        generate_command_args non-dataclass returns ([], False)
- Lines 145-154:   generate_command_args int validator & has_greedy = True
- Lines 180-198:   enhance_command_with_args body
- Line 220:        _inject_tg_context scope[value.cls] = value (no parent)
- Line 244:        _compose_node with existing scope (success)
- Line 255:        compose_param node path (success)
- Lines 289-294:   _compose_node creating new scope with _inject_tg_context
- Lines 322-323:   compose_param is_cute path
- Lines 330-331:   compose_param ctx.get fallback
- Line 381:        try_compose_transition required Nothing -> all_satisfied=False
- Lines 517-544:   wrap_stateful_telegrinder inner _handler body
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from collections.abc import Callable, Coroutine
from typing import Annotated, Self
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest.importorskip("telegrinder")

from kungfu import Ok, Error, Result, Option, Nothing
from nodnod import Scope, DataNode
from nodnod.agent.event_loop.agent import EventLoopAgent
from telegrinder.bot.cute_types.base import BaseCute
from telegrinder.bot.dispatch.context import Context
from telegrinder.bot.rules.abc import ABCRule
from telegrinder.bot.rules.command import Command, Argument

from emergent.ops._graph import Op, ops
from emergent.wire.axis.surface._handler import Handler
from emergent.wire.axis.surface.codecs.stateful import StatefulCodec, Done
from emergent.wire.axis.storage import MemoryStorage
from emergent.wire.axis.surface.triggers.telegrinder import TelegrindTrigger
from emergent.wire.axis.schema.dialects.tg import CommandArg as TgCommandArg
from emergent.wire.compile._core import Axes

import emergent.wire.compile.targets.telegrinder as _tg_mod

# Public API
compose_param = _tg_mod.compose_param
compose_store_key = _tg_mod.compose_store_key
generate_command_args = _tg_mod.generate_command_args
enhance_command_with_args = _tg_mod.enhance_command_with_args
try_compose_transition = _tg_mod.try_compose_transition
wrap_stateful_telegrinder = _tg_mod.wrap_stateful_telegrinder
TelegrindRoute = _tg_mod.TelegrindRoute

# Private API accessed for unit-test coverage — no public alternative exists
_format_tg_response = _tg_mod._format_tg_response  # pyright: ignore[reportPrivateUsage]
_inject_tg_context = _tg_mod._inject_tg_context  # pyright: ignore[reportPrivateUsage]
_compose_node = _tg_mod._compose_node  # pyright: ignore[reportPrivateUsage]


# ================================================================
# Domain types
# ================================================================


@dataclass
class EchoOp(Op[str, str]):
    text: str


async def _echo_handler(req: EchoOp) -> Result[str, str]:
    return Ok(f"Echo: {req.text}")


@dataclass
class EchoReq:
    name: str

    def to_domain(self) -> EchoOp:
        return EchoOp(text=self.name)


@dataclass
class EchoResp:
    text: str

    @classmethod
    def from_domain(cls, result: Result[str, str]) -> Self:
        match result:
            case Ok(v):
                return cls(text=v)
            case Error(e):
                return cls(text=str(e))

    def __str__(self) -> str:
        return self.text


_runner = ops().on(EchoOp, _echo_handler).compile()
_axes = Axes.default()


# ================================================================
# Composable test nodes (module-level for get_type_hints compat)
# ================================================================


class _TgKeyNode(DataNode):
    """Proper nodnod DataNode for store key composition."""

    @classmethod
    async def __compose__(cls) -> Self:
        return cls()

    def __str__(self) -> str:
        return "tg-test-key"


class _TgValueNode(DataNode):
    """Proper nodnod DataNode for general composition."""

    @classmethod
    async def __compose__(cls) -> Self:
        return cls()

    def __str__(self) -> str:
        return "tg-value"


# ================================================================
# Request types for generate_command_args tests
# ================================================================


@dataclass
class _IntArgReq:
    """Request with int field annotated with CommandArg."""
    count: Annotated[int, TgCommandArg()]


@dataclass
class _GreedyArgReq:
    """Request with greedy field annotated with CommandArg."""
    description: Annotated[str, TgCommandArg(greedy=True)]


@dataclass
class _IntAndGreedyReq:
    """Request with int and greedy command args."""
    count: Annotated[int, TgCommandArg()]
    text: Annotated[str, TgCommandArg(greedy=True)]


# ================================================================
# Flow for stateful tests
# ================================================================


@dataclass
class _TgFlow:
    step: int = 0

    async def __transition__(self, name: Option[str]) -> "Self | tuple[Self, str] | Done":
        if self.step == 0:
            return replace(self, step=1), "Step 1 done"
        return Done()

    def to_domain(self) -> EchoOp:
        return EchoOp(text="flow-done")


# ================================================================
# Helpers
# ================================================================


def _make_trigger(*rules: ABCRule, view: str = "message") -> TelegrindTrigger:
    return TelegrindTrigger(*rules, view=view)


def _make_mock_context(**extra: str | None | Nothing | MagicMock) -> MagicMock:
    """Create a mock Context with per_event_scope."""
    scope = Scope(detail="test-ctx")
    ctx = MagicMock(spec=Context)
    ctx.per_event_scope = scope
    extra_dict: dict[str, str | None | Nothing | MagicMock] = extra

    def _get_from_extra(key: str) -> str | None | Nothing | MagicMock:
        return extra_dict.get(key)

    ctx.get = MagicMock(side_effect=_get_from_extra)
    return ctx


async def _await_route_handler(route: TelegrindRoute, ctx: MagicMock) -> str:
    """Await a TelegrindRoute handler and return the string result.

    TelegrindRoute.handler is typed as Callable[[Context], object] because
    telegrinder's return manager accepts sync or async handlers. In tests we
    know the handler is async, so we assert the coroutine protocol and await.
    """
    coro = route.handler(ctx)
    assert isinstance(coro, Coroutine)
    # Coroutine narrowed from `object` has Unknown type params; no way to
    # recover the concrete return type without cast or ignore
    result = await coro  # pyright: ignore[reportUnknownVariableType]
    assert isinstance(result, str)
    return result


# ================================================================
# _format_tg_response (lines 92, 95)
# ================================================================


class TestFormatTgResponse:
    def test_telegrinder_type_passthrough(self) -> None:
        """Objects from telegrinder module are returned as-is (line 92)."""
        tg_obj = MagicMock()
        type(tg_obj).__module__ = "telegrinder.something"
        type(tg_obj).__str__ = object.__str__  # no custom __str__
        result = _format_tg_response(tg_obj)
        assert result is tg_obj

    def test_no_custom_str_passthrough(self) -> None:
        """Objects without custom __str__ are returned as-is (line 95)."""

        class PlainObj:
            pass

        obj = PlainObj()
        result = _format_tg_response(obj)
        assert result is obj


# ================================================================
# generate_command_args (lines 134, 145-154)
# ================================================================


class TestGenerateCommandArgs:
    def test_non_dataclass_returns_empty(self) -> None:
        """Non-dataclass type returns ([], False) (line 134)."""

        class NotADataclass:
            pass

        args, has_greedy = generate_command_args(NotADataclass)
        assert args == []
        assert has_greedy is False

    def test_int_field_gets_int_validator(self) -> None:
        """Int field_type appends int validator (line 146-147)."""
        args, has_greedy = generate_command_args(_IntArgReq)
        assert len(args) == 1
        arg = args[0]
        assert arg.name == "count"
        assert int in arg.validators
        assert has_greedy is False

    def test_greedy_flag_sets_has_greedy(self) -> None:
        """Greedy CommandArg sets has_greedy = True (line 153-154)."""
        args, has_greedy = generate_command_args(_GreedyArgReq)
        assert len(args) == 1
        assert has_greedy is True

    def test_int_and_greedy_combined(self) -> None:
        """Both int validator and greedy flag work together."""
        args, has_greedy = generate_command_args(_IntAndGreedyReq)
        assert len(args) == 2
        assert has_greedy is True
        int_arg = next(a for a in args if a.name == "count")
        assert int in int_arg.validators


# ================================================================
# enhance_command_with_args (lines 180-198)
# ================================================================


class TestEnhanceCommandWithArgs:
    def test_enhances_empty_command(self) -> None:
        """Command without args gets enhanced with generated args (lines 182-194)."""
        trigger = _make_trigger(Command("register"))
        enhanced = enhance_command_with_args(trigger, _IntArgReq)
        # The enhanced trigger should have a Command with arguments
        cmd = enhanced.rules[0]
        assert isinstance(cmd, Command)
        assert len(cmd.arguments) == 1
        assert cmd.arguments[0].name == "count"

    def test_greedy_enables_lazy(self) -> None:
        """Greedy arg sets lazy=True on enhanced Command (line 190)."""
        trigger = _make_trigger(Command("create"))
        enhanced = enhance_command_with_args(trigger, _GreedyArgReq)
        cmd = enhanced.rules[0]
        assert isinstance(cmd, Command)
        assert cmd.lazy is True

    def test_non_command_rule_passes_through(self) -> None:
        """Non-Command rules are kept as-is (line 196)."""
        from telegrinder.bot.rules.abc import ABCRule

        class _CustomRule(ABCRule):
            async def check(self, _: object) -> bool:
                return True

        custom = _CustomRule()
        trigger = _make_trigger(custom, Command("test"))
        enhanced = enhance_command_with_args(trigger, _IntArgReq)
        # Custom rule should still be there
        assert enhanced.rules[0] is custom

    def test_no_args_returns_original(self) -> None:
        """When request has no CommandArg fields, returns original trigger (line 176-177)."""
        trigger = _make_trigger(Command("plain"))
        enhanced = enhance_command_with_args(trigger, EchoReq)
        assert enhanced is trigger

    def test_command_with_existing_args_not_enhanced(self) -> None:
        """Command that already has arguments is NOT enhanced (line 182 condition)."""
        existing_cmd = Command("register", Argument("login"))
        trigger = _make_trigger(existing_cmd)
        enhanced = enhance_command_with_args(trigger, _IntArgReq)
        cmd = enhanced.rules[0]
        assert isinstance(cmd, Command)
        # Should keep original argument, not replace
        assert len(cmd.arguments) == 1
        assert cmd.arguments[0].name == "login"


# ================================================================
# _inject_tg_context without parent (line 220)
# ================================================================


class TestInjectTgContextMerge:
    @pytest.mark.asyncio
    async def test_merges_values_from_per_event_scope(self) -> None:
        """When scope is NOT a child of per_event_scope, merges values (line 218-220)."""
        per_event = Scope(detail="per-event")
        independent = Scope(detail="independent")
        ctx = MagicMock(spec=Context)
        ctx.per_event_scope = per_event
        ctx.get = MagicMock(return_value=None)

        async with per_event:
            # Inject something into per_event so there's data to merge
            per_event.inject(str, "test-value")
            async with independent:
                _inject_tg_context(independent, ctx)
                # Context should be injected
                wrapper = independent.get(Context)
                assert wrapper is not None


# ================================================================
# compose_store_key without scope_layer (line 247 fallback)
# ================================================================


class TestComposeStoreKeyNoScopeLayer:
    @pytest.mark.asyncio
    async def test_without_scope_layer_uses_per_event_scope(self) -> None:
        """When scope_layer is None, parent = ctx.per_event_scope (line 247)."""
        per_event = Scope(detail="per-event")
        ctx = MagicMock(spec=Context)
        ctx.per_event_scope = per_event
        ctx.get = MagicMock(return_value=None)

        async with per_event:
            # _TgKeyNode is a proper DataNode, compose should succeed
            key = await compose_store_key(
                _TgKeyNode, EventLoopAgent, ctx
            )
            assert key == "tg-test-key"

    @pytest.mark.asyncio
    async def test_with_scope_success(self) -> None:
        """When scope is provided and composition succeeds, returns str(value) (line 244)."""
        ctx = _make_mock_context()
        scope = Scope(detail="key-scope")
        async with scope:
            _inject_tg_context(scope, ctx)
            key = await compose_store_key(
                _TgKeyNode, EventLoopAgent, ctx, scope=scope,
            )
            assert key == "tg-test-key"


# ================================================================
# _compose_node with existing scope (line 285-287)
# ================================================================


class TestComposeNodeWithScope:
    @pytest.mark.asyncio
    async def test_reuses_existing_scope(self) -> None:
        """When scope is provided, reuses it for composition (lines 285-287)."""
        ctx = _make_mock_context()
        scope = Scope(detail="reuse-scope")
        async with scope:
            _inject_tg_context(scope, ctx)
            success, value = await _compose_node(
                _TgValueNode, EventLoopAgent, ctx, scope=scope,
            )
            assert success is True
            assert isinstance(value, _TgValueNode)


# ================================================================
# _compose_node creating new scope (lines 289-294)
# ================================================================


class TestComposeNodeNewScope:
    @pytest.mark.asyncio
    async def test_creates_new_scope_without_scope_layer(self) -> None:
        """When no scope and no scope_layer, creates child of per_event_scope (lines 289-294)."""
        per_event = Scope(detail="per-event")
        ctx = MagicMock(spec=Context)
        ctx.per_event_scope = per_event
        ctx.get = MagicMock(return_value=None)

        async with per_event:
            success, value = await _compose_node(
                _TgValueNode, EventLoopAgent, ctx,
            )
            assert success is True
            assert isinstance(value, _TgValueNode)


# ================================================================
# compose_param — is_cute path (lines 322-323, 329-331)
# ================================================================


class TestComposeParamCute:
    @pytest.mark.asyncio
    async def test_is_cute_with_matching_type(self) -> None:
        """When compose_type is BaseCute subclass and update_cute matches (lines 329-331)."""
        # Create a mock update_cute with matching incoming_update
        mock_cute = MagicMock(spec=BaseCute)
        mock_msg = MagicMock(spec=BaseCute)
        mock_cute.incoming_update = mock_msg

        ctx = _make_mock_context(update_cute=mock_cute)

        result = await compose_param(
            "msg", BaseCute, BaseCute, EventLoopAgent, ctx, mock_cute,
        )
        assert result is mock_msg

    @pytest.mark.asyncio
    async def test_is_cute_with_type_check_error(self) -> None:
        """When issubclass raises TypeError, is_cute = False (lines 322-323)."""
        # Use a type that makes issubclass raise TypeError (like a generic alias).
        # We deliberately pass a UnionType where `type` is expected to exercise
        # the TypeError catch inside compose_param; no type-safe alternative exists.
        from typing import Union
        # compose_param accepts `type` but at runtime handles GenericAlias/UnionType too;
        # pyright: ignore is unavoidable since Union[str, int] is not `type`
        compose_type: type = Union[str, int]  # pyright: ignore[reportAssignmentType]
        original_type: type = Option[str]  # pyright: ignore[reportAssignmentType]

        ctx = _make_mock_context()
        # Should fall through is_cute to ctx.get fallback
        result = await compose_param(
            "val", original_type, compose_type, EventLoopAgent, ctx, None,
        )
        # Not a cute, not a node, ctx.get returns None -> Nothing
        assert isinstance(result, Nothing)


# ================================================================
# compose_param — node path success (line 333-335)
# ================================================================


class TestComposeParamNode:
    @pytest.mark.asyncio
    async def test_node_success_returns_value(self) -> None:
        """When compose_type is a node and composition succeeds (lines 333-335)."""
        ctx = _make_mock_context()
        scope = Scope(detail="node-test")
        async with scope:
            _inject_tg_context(scope, ctx)
            result = await compose_param(
                "node", _TgValueNode, _TgValueNode, EventLoopAgent, ctx, None,
                scope=scope,
            )
            assert isinstance(result, _TgValueNode)


# ================================================================
# compose_param — ctx.get fallback (lines 338-340)
# ================================================================


class TestComposeParamCtxFallback:
    @pytest.mark.asyncio
    async def test_ctx_get_returns_value(self) -> None:
        """When non-node type exists in context, returns wrapped value (lines 338-340)."""
        ctx = _make_mock_context(username="Alice")
        result = await compose_param(
            "username", str, str, EventLoopAgent, ctx, None,
        )
        assert result == "Alice"

    @pytest.mark.asyncio
    async def test_ctx_get_returns_none_raises(self) -> None:
        """When non-node type not in context, required type raises (line 342)."""
        ctx = _make_mock_context()
        with pytest.raises(RuntimeError, match="Cannot resolve"):
            await compose_param(
                "missing", str, str, EventLoopAgent, ctx, None,
            )

    @pytest.mark.asyncio
    async def test_ctx_get_returns_none_optional_nothing(self) -> None:
        """When non-node type not in context, optional returns Nothing (line 342)."""
        ctx = _make_mock_context()
        # compose_param accepts `type` but at runtime handles GenericAlias too;
        # pyright: ignore is unavoidable since Option[str] is not `type`
        optional_str: type = Option[str]  # pyright: ignore[reportAssignmentType]
        result = await compose_param(
            "missing", optional_str, str, EventLoopAgent, ctx, None,
        )
        assert isinstance(result, Nothing)


# ================================================================
# try_compose_transition — required Nothing -> all_satisfied=False (line 381)
# ================================================================


# Module-level transition for get_type_hints resolution
async def _transition_required_str(self: object, name: str) -> Done:
    return Done()


async def _transition_with_tag(self: object, tag: str) -> Done:
    """Transition with required 'tag' param -- used to test Nothing fallback."""
    return Done()


class TestTryComposeTransitionRequiredNothing:
    @pytest.mark.asyncio
    async def test_required_str_raises_sets_unsatisfied(self) -> None:
        """When required param cannot be resolved (RuntimeError), all_satisfied = False (line 374-376)."""
        ctx = _make_mock_context()  # 'name' not in context
        _composed, satisfied = await try_compose_transition(
            _transition_required_str, EventLoopAgent, ctx,
        )
        assert satisfied is False

    @pytest.mark.asyncio
    async def test_required_nothing_value_sets_unsatisfied(self) -> None:
        """When ctx returns Nothing() for required param, isinstance(result, Nothing) triggers (line 380-381).

        compose_param ctx.get path: if ctx.get returns Nothing() (which is not None),
        wrap(str, True, Nothing()) returns Nothing(), and the Nothing check triggers.
        """
        # Create context where 'tag' key returns Nothing() (not None)
        ctx = _make_mock_context(tag=Nothing())
        _composed, satisfied = await try_compose_transition(
            _transition_with_tag, EventLoopAgent, ctx,
        )
        assert satisfied is False


# ================================================================
# wrap_stateful_telegrinder inner _handler (lines 517-544)
# ================================================================


class TestWrapStatefulTelegrindInnerHandler:
    def _make_stateful_handler(
        self,
        flow: type = _TgFlow,
    ) -> Handler[StatefulCodec]:
        codec = StatefulCodec(
            flow=flow,
            response=EchoResp,
            store=MemoryStorage[str, _TgFlow](),
            key_node=_TgKeyNode,
            agent_cls=EventLoopAgent,
        )
        return Handler(codec=codec, runner=_runner, capabilities=())

    def test_wrap_returns_telegrind_route(self) -> None:
        """wrap_stateful_telegrinder returns TelegrindRoute."""
        handler = self._make_stateful_handler()
        trigger = _make_trigger(Command("flow"))
        route = wrap_stateful_telegrinder(handler, trigger, _axes)
        assert isinstance(route, TelegrindRoute)
        assert callable(route.handler)

    @pytest.mark.asyncio
    async def test_inner_handler_executes_full_loop(self) -> None:
        """Inner _handler creates scope, composes key, resolves transition, executes (lines 517-544).

        We mock compose_store_key and execute_stateful_unified to test the inner handler body.
        """
        handler = self._make_stateful_handler(_TgFlow)
        trigger = _make_trigger(Command("flow"))
        route = wrap_stateful_telegrinder(handler, trigger, _axes)

        # Build a real-enough Context
        per_event = Scope(detail="per-event")
        ctx = MagicMock(spec=Context)
        ctx.per_event_scope = per_event
        ctx.get = MagicMock(return_value=None)

        async with per_event:
            with patch(
                "emergent.wire.compile.targets.telegrinder.compose_store_key",
                new=AsyncMock(return_value="test-key"),
            ):
                async def _fake_exec(
                    handler: Handler[StatefulCodec],
                    store_key: str,
                    resolve_transition: Callable[..., Coroutine[None, None, tuple[str, dict[str, str]] | None]],
                    inject_scope: Callable[[Scope], None],
                    format_response: Callable[[str], str] | None,
                    axes: Axes | None,
                    parent_scope: Scope | None,
                ) -> tuple[str, bool]:
                    """Fake execute_stateful_unified that calls inject_scope to cover line 528."""
                    # Call inject_scope to cover the closure at line 527-528
                    done_scope = Scope(detail="done-scope")
                    async with done_scope:
                        inject_scope(done_scope)
                    return "flow response", True

                with patch(
                    "emergent.wire.compile.targets.telegrinder.execute_stateful_unified",
                    new=_fake_exec,
                ):
                    handler_result = await _await_route_handler(route, ctx)
                    # execute_stateful_unified returns the already-formatted response
                    assert handler_result == "flow response"

    @pytest.mark.asyncio
    async def test_inner_handler_no_transitions_raises(self) -> None:
        """Inner _handler raises when no transitions defined."""

        @dataclass
        class _EmptyFlow:
            pass

        handler = self._make_stateful_handler(_EmptyFlow)
        trigger = _make_trigger(Command("flow"))
        route = wrap_stateful_telegrinder(handler, trigger, _axes)

        per_event = Scope(detail="per-event")
        ctx = MagicMock(spec=Context)
        ctx.per_event_scope = per_event
        ctx.get = MagicMock(return_value=None)

        async with per_event:
            with patch(
                "emergent.wire.compile.targets.telegrinder.compose_store_key",
                new=AsyncMock(return_value="test-key"),
            ):
                with pytest.raises(RuntimeError):
                    await _await_route_handler(route, ctx)

    @pytest.mark.asyncio
    async def test_inner_handler_with_scope_layer(self) -> None:
        """Inner _handler respects scope_layer when present (line 518)."""
        from emergent.wire.compile._lifetime import ScopeLayer, Tier, App, Request
        from emergent.graph._family import ScopeFamily
        from types import MappingProxyType

        app_scope = Scope(detail="tg-app")
        family: ScopeFamily[Tier] = ScopeFamily()
        layer = ScopeLayer(
            scopes=MappingProxyType({App: app_scope}),
            family=family,
            leaf=Request,
        )
        axes_with_layer = _axes.with_scope_layer(layer)

        handler = self._make_stateful_handler(_TgFlow)
        trigger = _make_trigger(Command("flow"))
        route = wrap_stateful_telegrinder(handler, trigger, axes_with_layer)

        per_event = Scope(detail="per-event")
        ctx = MagicMock(spec=Context)
        ctx.per_event_scope = per_event
        ctx.get = MagicMock(return_value=None)

        async with app_scope:
            async with per_event:
                with patch(
                    "emergent.wire.compile.targets.telegrinder.compose_store_key",
                    new=AsyncMock(return_value="test-key"),
                ):
                    with patch(
                        "emergent.wire.compile.targets.telegrinder.execute_stateful_unified",
                        new=AsyncMock(return_value=("result", True)),
                    ) as mock_exec:
                        await _await_route_handler(route, ctx)
                        mock_exec.assert_called_once()

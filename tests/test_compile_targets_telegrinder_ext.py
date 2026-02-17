"""Extended tests for emergent.wire.compile.targets.telegrinder — inner handler
bodies, composition helpers, state management, help generation, and compilation.

Covers uncovered lines:
- _inject_tg_context (lines 217-221)
- compose_store_key (lines 238-256)
- _get_cute_value (lines 261-267)
- _compose_node (lines 283-294)
- compose_param (lines 314-342)
- try_compose_transition (lines 357-383)
- resolve_transition (lines 397-403)
- TelegrindRoute structure
- wrap_rrc_telegrinder inner handler execution (lines 436-439)
- wrap_stateful_telegrinder inner handler (lines 509-548)
- wrap_immediate_telegrinder inner handler execution (line 564)
- wrap_delegate_telegrinder inner handler execution (lines 587-590)
- HasActiveFlowState.check (lines 471-485)
- create_stateful_rule (lines 490-500)
- register_handler (lines 604-615)
- telegrinder_compile with family (lines 661-671)
- CommandInfo, extract_command_info (lines 702-730)
- generate_help_from_command_rules (lines 746-773)
- fold_tg_handler_ctx
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Self
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from kungfu import Ok, Error, Result, Option, Some, Nothing

from emergent.ops._graph import Op, ops
from emergent.wire.axis.surface._app import Application, application
from emergent.wire.axis.surface._endpoint import endpoint
from emergent.wire.axis.surface._handler import Handler
from emergent.wire.axis.surface.codecs.delegate import DelegateCodec
from emergent.wire.axis.surface.codecs.immediate import (
    ImmediateCodec,
    ImmediateFactoryCodec,
)
from emergent.wire.axis.surface.codecs.rrc import rrc
from emergent.wire.axis.surface.codecs.stateful import (
    StatefulCodec,
    Done,
)
from emergent.wire.axis.storage import MemoryStorage
from emergent.wire.axis.surface.triggers.telegrinder import TelegrindTrigger
from emergent.wire.axis.surface.dialects.telegram import HelpMeta
from emergent.wire.compile._core import Axes

from nodnod import Scope
from nodnod.agent.event_loop.agent import EventLoopAgent
from telegrinder.bot.dispatch import Dispatch
from telegrinder.bot.dispatch.context import Context
from telegrinder.bot.rules.abc import ABCRule, OrRule
from telegrinder.bot.rules.command import Command, Argument

from emergent.wire.compile.targets.telegrinder import (
    CommandInfo,
    HasActiveFlowState,
    TelegrindRoute,
    _get_cute_value,  # pyright: ignore[reportPrivateUsage]  # testing private helper
    _inject_tg_context,  # pyright: ignore[reportPrivateUsage]  # testing private helper
    compose_param,
    compose_store_key,
    create_stateful_rule,
    extract_command_info,
    fold_tg_handler_ctx,
    generate_help_from_command_rules,
    register_handler,
    resolve_transition,
    telegrinder_compile,
    try_compose_transition,
    wrap_delegate_telegrinder,
    wrap_immediate_telegrinder,
    wrap_rrc_telegrinder,
    wrap_stateful_telegrinder,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Domain types
# ═══════════════════════════════════════════════════════════════════════════════


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
    def from_domain(cls, dom: Result[str, str]) -> Self:
        match dom:
            case Ok(v):
                return cls(text=v)
            case Error(e):
                return cls(text=str(e))

    def __str__(self) -> str:
        return self.text


@dataclass
class ImmResp:
    text: str = "help"

    @classmethod
    def produce(cls) -> Self:
        return cls(text="help-text")

    def __str__(self) -> str:
        return self.text


@dataclass
class _TgKeyNode:
    __dependencies__: tuple[type, ...] = ()

    @classmethod
    async def __compose__(cls) -> Self:
        return cls()

    def __str__(self) -> str:
        return "tg-test-key"


@dataclass
class _TgFlow:
    value: Option[str] = field(default_factory=Nothing)

    async def __transition__(self, name: Option[str]) -> "Self | Done":
        match name:
            case Some(_n):
                return Done()
            case _:
                return self

    def to_domain(self) -> EchoOp:
        return EchoOp(text=self.value.unwrap())


_runner = ops().on(EchoOp, _echo_handler).compile()
_mock_runner = MagicMock()
_axes = Axes.default()


def _make_trigger(*rules: ABCRule, view: str = "message") -> TelegrindTrigger:
    return TelegrindTrigger(*rules, view=view)


def _make_mock_context(**extra: object) -> Context:
    """Create a mock telegrinder Context with a minimal per_event_scope."""
    scope = Scope(detail="test-ctx")
    ctx = MagicMock(spec=Context)
    ctx.per_event_scope = scope

    def _get_extra(key: str) -> object | None:
        return extra.get(key)

    ctx.get = MagicMock(side_effect=_get_extra)
    return ctx


# ═══════════════════════════════════════════════════════════════════════════════
# _inject_tg_context (lines 217-221)
# ═══════════════════════════════════════════════════════════════════════════════


class TestInjectTgContext:
    @pytest.mark.asyncio
    async def test_injects_context_into_scope(self) -> None:
        """_inject_tg_context adds Context to scope."""
        ctx = _make_mock_context()
        scope = Scope(detail="test")
        async with scope:
            _inject_tg_context(scope, ctx)
            wrapper = scope.get(Context)
            assert wrapper is not None

    @pytest.mark.asyncio
    async def test_merges_per_event_scope_when_not_parent(self) -> None:
        """When scope is not a child of per_event_scope, merges values."""
        per_event = Scope(detail="per-event")
        ctx = MagicMock(spec=Context)
        ctx.per_event_scope = per_event
        ctx.get = MagicMock(return_value=None)

        scope = Scope(detail="test-independent")
        async with per_event:
            async with scope:
                _inject_tg_context(scope, ctx)
                wrapper = scope.get(Context)
                assert wrapper is not None


# ═══════════════════════════════════════════════════════════════════════════════
# compose_store_key (lines 238-256)
# ═══════════════════════════════════════════════════════════════════════════════


class TestComposeStoreKey:
    @pytest.mark.asyncio
    async def test_compose_with_scope_failure_raises(self) -> None:
        """compose_store_key with scope raises when composition fails."""
        ctx = _make_mock_context()
        scope = Scope(detail="key-scope")

        @dataclass
        class _BadKeyNode:
            __dependencies__: tuple[type, ...] = ()

        async with scope:
            with pytest.raises(RuntimeError, match="Failed to compose key_node"):
                await compose_store_key(
                    _BadKeyNode, EventLoopAgent, ctx, scope=scope
                )

    @pytest.mark.asyncio
    async def test_compose_without_scope_failure_raises(self) -> None:
        """compose_store_key without scope raises when composition fails."""
        per_event = Scope(detail="per-event")
        ctx = MagicMock(spec=Context)
        ctx.per_event_scope = per_event
        ctx.get = MagicMock(return_value=None)

        @dataclass
        class _BadKeyNode2:
            __dependencies__: tuple[type, ...] = ()

        async with per_event:
            with pytest.raises(RuntimeError, match="Failed to compose key_node"):
                await compose_store_key(
                    _BadKeyNode2, EventLoopAgent, ctx
                )


# ═══════════════════════════════════════════════════════════════════════════════
# _get_cute_value (lines 261-267)
# ═══════════════════════════════════════════════════════════════════════════════


class TestGetCuteValue:
    def test_returns_false_when_update_cute_is_none(self) -> None:
        success, value = _get_cute_value(str, None)
        assert success is False
        assert "no update_cute" in str(value)

    def test_returns_true_when_type_matches(self) -> None:
        """When incoming_update is an instance of compose_type, returns True."""
        mock_cute = MagicMock()
        mock_cute.incoming_update = "hello"
        success, value = _get_cute_value(str, mock_cute)
        assert success is True
        assert value == "hello"

    def test_returns_false_when_type_mismatches(self) -> None:
        """When incoming_update type doesn't match, returns False."""
        mock_cute = MagicMock()
        mock_cute.incoming_update = 42
        success, value = _get_cute_value(str, mock_cute)
        assert success is False
        assert "not str" in str(value)


# ═══════════════════════════════════════════════════════════════════════════════
# compose_param (lines 314-342)
# ═══════════════════════════════════════════════════════════════════════════════


class TestComposeParam:
    @pytest.mark.asyncio
    async def test_compose_scope_type_with_scope(self) -> None:
        """When compose_type is Scope and scope is provided, returns scope."""
        ctx = _make_mock_context()
        scope = Scope(detail="test")
        async with scope:
            result = await compose_param(
                "s", Scope, Scope, EventLoopAgent, ctx, None, scope=scope
            )
            assert result is scope

    @pytest.mark.asyncio
    async def test_compose_scope_type_without_scope(self) -> None:
        """When compose_type is Scope but no scope, wraps as failed."""
        ctx = _make_mock_context()
        result = await compose_param(
            "s",
            Option[Scope],  # pyright: ignore[reportArgumentType]  # GenericAlias accepted at runtime
            Scope, EventLoopAgent, ctx, None,
        )
        # Should be Nothing since scope is not available
        assert isinstance(result, Nothing)

    @pytest.mark.asyncio
    async def test_compose_context_type(self) -> None:
        """When compose_type is Context, returns wrapped Context."""
        ctx = _make_mock_context()
        result = await compose_param(
            "ctx", Context, Context, EventLoopAgent, ctx, None
        )
        assert result is ctx

    @pytest.mark.asyncio
    async def test_compose_context_from_value(self) -> None:
        """When value exists in context, returns it."""
        ctx = _make_mock_context(username="Alice")
        result = await compose_param(
            "username", str, str, EventLoopAgent, ctx, None
        )
        assert result == "Alice"

    @pytest.mark.asyncio
    async def test_compose_unresolvable_returns_error(self) -> None:
        """When type cannot be resolved, returns failure."""
        ctx = _make_mock_context()
        with pytest.raises(RuntimeError, match="Cannot resolve"):
            await compose_param(
                "missing", str, str, EventLoopAgent, ctx, None
            )

    @pytest.mark.asyncio
    async def test_compose_optional_unresolvable_returns_nothing(self) -> None:
        """When optional type cannot be resolved, returns Nothing."""
        ctx = _make_mock_context()
        result = await compose_param(
            "missing",
            Option[str],  # pyright: ignore[reportArgumentType]  # GenericAlias accepted at runtime
            str, EventLoopAgent, ctx, None,
        )
        assert isinstance(result, Nothing)

    @pytest.mark.asyncio
    async def test_compose_node_type_optional_fails_gracefully(self) -> None:
        """When compose_type is a node that fails, optional wraps as Nothing."""
        @dataclass
        class _FailNode:
            __dependencies__: tuple[type, ...] = ()

        ctx = _make_mock_context()
        scope = Scope(detail="node-test")
        async with scope:
            _inject_tg_context(scope, ctx)
            result = await compose_param(
                "key",
                Option[_FailNode],  # pyright: ignore[reportArgumentType]  # GenericAlias accepted at runtime
                _FailNode, EventLoopAgent, ctx, None,
                scope=scope,
            )
            assert isinstance(result, Nothing)


# ═══════════════════════════════════════════════════════════════════════════════
# try_compose_transition (lines 357-383)
# ═══════════════════════════════════════════════════════════════════════════════


# Module-level transition methods for type hint resolution
async def _transition_with_ctx(self: object, ctx: Context) -> Done:
    return Done()


async def _transition_with_str(self: object, name: str) -> Done:
    return Done()


class TestTryComposeTransition:
    @pytest.mark.asyncio
    async def test_all_satisfied_returns_true(self) -> None:
        """When all params are resolvable, returns (composed, True)."""
        ctx = _make_mock_context()
        composed, satisfied = await try_compose_transition(
            _transition_with_ctx, EventLoopAgent, ctx
        )
        assert satisfied is True
        assert "ctx" in composed

    @pytest.mark.asyncio
    async def test_unsatisfied_required_returns_false(self) -> None:
        """When required param cannot be resolved, returns (_, False)."""
        ctx = _make_mock_context()  # no 'name' in context
        _composed, satisfied = await try_compose_transition(
            _transition_with_str, EventLoopAgent, ctx
        )
        assert satisfied is False


# ═══════════════════════════════════════════════════════════════════════════════
# resolve_transition (lines 397-403)
# ═══════════════════════════════════════════════════════════════════════════════


class TestResolveTransition:
    @pytest.mark.asyncio
    async def test_resolves_first_satisfiable(self) -> None:
        """Returns first transition whose deps are satisfiable."""
        ctx = _make_mock_context()
        result = await resolve_transition(
            [_transition_with_str, _transition_with_ctx],
            EventLoopAgent,
            ctx,
        )
        assert result is not None
        method, _composed = result
        # _transition_with_str should fail (no 'name'), _transition_with_ctx succeeds
        assert method is _transition_with_ctx

    @pytest.mark.asyncio
    async def test_returns_none_when_none_satisfiable(self) -> None:
        """Returns None when no transition is satisfiable."""
        ctx = _make_mock_context()
        result = await resolve_transition(
            [_transition_with_str],
            EventLoopAgent,
            ctx,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_with_scope(self) -> None:
        """resolve_transition threads scope through."""
        ctx = _make_mock_context()
        scope = Scope(detail="resolve-test")
        async with scope:
            _inject_tg_context(scope, ctx)
            result = await resolve_transition(
                [_transition_with_ctx],
                EventLoopAgent,
                ctx,
                scope=scope,
            )
            assert result is not None


# ═══════════════════════════════════════════════════════════════════════════════
# HasActiveFlowState.check (lines 471-485)
# ═══════════════════════════════════════════════════════════════════════════════


class TestHasActiveFlowState:
    @pytest.mark.asyncio
    async def test_returns_false_when_composition_fails(self) -> None:
        """check returns False when key_node composition fails (exception path)."""
        store: MemoryStorage[str, object] = MemoryStorage()
        rule = HasActiveFlowState(
            store=store, key_node=_TgKeyNode, agent_cls=EventLoopAgent
        )
        ctx = _make_mock_context()

        # Create a real scope for per_event_scope
        scope = Scope(detail="check-scope")
        ctx.per_event_scope = scope
        async with scope:
            result = await rule.check(ctx)
        # Returns False because _TgKeyNode is not a real nodnod node,
        # so compose_store_key raises, which is caught and returns False
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_true_when_state_exists(self) -> None:
        """check returns True when store has state for the composed key."""
        store: MemoryStorage[str, object] = MemoryStorage()
        await store.set("mocked-key", {"some": "state"})

        rule = HasActiveFlowState(
            store=store, key_node=_TgKeyNode, agent_cls=EventLoopAgent
        )
        ctx = _make_mock_context()
        scope = Scope(detail="check-scope")
        ctx.per_event_scope = scope

        # Mock compose_store_key to return our mocked key
        async with scope:
            with patch(
                "emergent.wire.compile.targets.telegrinder.compose_store_key",
                new=AsyncMock(return_value="mocked-key"),
            ):
                result = await rule.check(ctx)
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_when_no_state(self) -> None:
        """check returns False when store has no state for key."""
        store: MemoryStorage[str, object] = MemoryStorage()

        rule = HasActiveFlowState(
            store=store, key_node=_TgKeyNode, agent_cls=EventLoopAgent
        )
        ctx = _make_mock_context()
        scope = Scope(detail="check-scope")
        ctx.per_event_scope = scope

        async with scope:
            with patch(
                "emergent.wire.compile.targets.telegrinder.compose_store_key",
                new=AsyncMock(return_value="nonexistent-key"),
            ):
                result = await rule.check(ctx)
        assert result is False


# ═══════════════════════════════════════════════════════════════════════════════
# create_stateful_rule (lines 490-500)
# ═══════════════════════════════════════════════════════════════════════════════


class TestCreateStatefulRule:
    def test_no_trigger_rules_returns_state_rule_only(self) -> None:
        """When trigger has no rules, returns just HasActiveFlowState."""
        codec = StatefulCodec(
            flow=_TgFlow,
            response=EchoResp,
            store=MemoryStorage[str, object](),
            key_node=_TgKeyNode,
            agent_cls=EventLoopAgent,
        )
        trigger = _make_trigger()  # no rules
        rule = create_stateful_rule(trigger, codec)
        assert isinstance(rule, HasActiveFlowState)

    def test_single_trigger_rule_returns_or_rule(self) -> None:
        """When trigger has one rule, returns OrRule(trigger_rule, state_rule)."""
        codec = StatefulCodec(
            flow=_TgFlow,
            response=EchoResp,
            store=MemoryStorage[str, object](),
            key_node=_TgKeyNode,
            agent_cls=EventLoopAgent,
        )
        trigger = _make_trigger(Command("flow"))
        rule = create_stateful_rule(trigger, codec)
        assert isinstance(rule, OrRule)

    def test_multiple_trigger_rules_returns_or_and_rule(self) -> None:
        """When trigger has multiple rules, creates AndRule then OrRule."""
        codec = StatefulCodec(
            flow=_TgFlow,
            response=EchoResp,
            store=MemoryStorage[str, object](),
            key_node=_TgKeyNode,
            agent_cls=EventLoopAgent,
        )
        rule1 = Command("flow")
        rule2 = Command("alternative")
        trigger = _make_trigger(rule1, rule2)
        rule = create_stateful_rule(trigger, codec)
        assert isinstance(rule, OrRule)


# ═══════════════════════════════════════════════════════════════════════════════
# wrap_rrc_telegrinder inner handler (lines 436-439)
# ═══════════════════════════════════════════════════════════════════════════════


class TestWrapRrcTelegrindExecution:
    @pytest.mark.asyncio
    async def test_handler_executes_and_returns_response(self) -> None:
        """The inner _handler calls execute_rrc_unified and returns formatted response."""
        handler_obj = Handler(
            codec=rrc(EchoReq, EchoResp),
            runner=_runner,
            capabilities=(),
        )
        trigger = _make_trigger(Command("echo"))
        route = wrap_rrc_telegrinder(handler_obj, trigger, _axes)

        # Create a real Context with per_event_scope
        scope = Scope(detail="per-event")
        ctx = MagicMock(spec=Context)
        ctx.per_event_scope = scope
        def _side_effect(key: str) -> str | None:
            return "TestUser" if key == "name" else None

        ctx.get = MagicMock(side_effect=_side_effect)

        async with scope:
            # TelegrindRoute.handler is typed as Callable[[Context], object] but
            # actual handlers are async — the type annotation doesn't capture Awaitable
            result: object = await route.handler(ctx)  # pyright: ignore[reportGeneralTypeIssues, reportUnknownVariableType]
            assert isinstance(result, str)
            assert "TestUser" in result


# ═══════════════════════════════════════════════════════════════════════════════
# wrap_immediate_telegrinder inner handler (line 564)
# ═══════════════════════════════════════════════════════════════════════════════


class TestWrapImmediateTelegrindExecution:
    @pytest.mark.asyncio
    async def test_handler_returns_immediate_response(self) -> None:
        """Immediate handler returns formatted response."""
        handler_obj: Handler[ImmediateCodec] = Handler(
            codec=ImmediateCodec(response=ImmResp),
            runner=_mock_runner,
            capabilities=(),
        )
        trigger = _make_trigger(Command("help"))
        route = wrap_immediate_telegrinder(handler_obj, trigger, _axes)

        ctx = _make_mock_context()
        # TelegrindRoute.handler typed as Callable[[Context], object] but actual is async
        result: object = await route.handler(ctx)  # pyright: ignore[reportGeneralTypeIssues, reportUnknownVariableType]
        # ImmResp has __str__, so _format_tg_response converts to str
        assert result == "help-text"

    @pytest.mark.asyncio
    async def test_factory_handler_returns_response(self) -> None:
        """ImmediateFactory handler calls factory and returns formatted response."""
        handler_obj: Handler[ImmediateFactoryCodec] = Handler(
            codec=ImmediateFactoryCodec(factory=lambda: "static-response"),
            runner=_mock_runner,
            capabilities=(),
        )
        trigger = _make_trigger(Command("help"))
        route = wrap_immediate_telegrinder(handler_obj, trigger, _axes)

        ctx = _make_mock_context()
        # TelegrindRoute.handler typed as Callable[[Context], object] but actual is async
        result: object = await route.handler(ctx)  # pyright: ignore[reportGeneralTypeIssues, reportUnknownVariableType]
        assert result == "static-response"


# ═══════════════════════════════════════════════════════════════════════════════
# wrap_delegate_telegrinder inner handler (lines 587-590)
# ═══════════════════════════════════════════════════════════════════════════════


class TestWrapDelegateTelegrindExecution:
    @pytest.mark.asyncio
    async def test_handler_calls_delegate_function(self) -> None:
        """Delegate handler calls the original function."""
        async def my_handler() -> str:
            return "delegate-result"

        handler_obj: Handler[DelegateCodec] = Handler(
            codec=DelegateCodec(handler=my_handler),
            runner=_mock_runner,
            capabilities=(),
        )
        trigger = _make_trigger(Command("test"))
        route = wrap_delegate_telegrinder(handler_obj, trigger, _axes)

        scope = Scope(detail="per-event")
        ctx = MagicMock(spec=Context)
        ctx.per_event_scope = scope
        ctx.get = MagicMock(return_value=None)

        async with scope:
            # TelegrindRoute.handler typed as Callable[[Context], object] but actual is async
            result: object = await route.handler(ctx)  # pyright: ignore[reportGeneralTypeIssues, reportUnknownVariableType]
            assert result == "delegate-result"


# ═══════════════════════════════════════════════════════════════════════════════
# wrap_stateful_telegrinder (lines 509-548)
# ═══════════════════════════════════════════════════════════════════════════════


class TestWrapStatefulTelegrindRoute:
    def _make_stateful_handler(self) -> Handler[StatefulCodec]:
        codec = StatefulCodec(
            flow=_TgFlow,
            response=EchoResp,
            store=MemoryStorage[str, object](),
            key_node=_TgKeyNode,
            agent_cls=EventLoopAgent,
        )
        return Handler(codec=codec, runner=_runner, capabilities=())

    def test_returns_telegrind_route(self) -> None:
        handler = self._make_stateful_handler()
        trigger = _make_trigger(Command("flow"))
        route = wrap_stateful_telegrinder(handler, trigger, _axes)
        assert isinstance(route, TelegrindRoute)

    def test_route_has_composite_rule(self) -> None:
        """Stateful route should have a composite rule (OrRule)."""
        handler = self._make_stateful_handler()
        trigger = _make_trigger(Command("flow"))
        route = wrap_stateful_telegrinder(handler, trigger, _axes)
        assert len(route.rules) == 1
        assert isinstance(route.rules[0], OrRule)


# ═══════════════════════════════════════════════════════════════════════════════
# register_handler (lines 604-615)
# ═══════════════════════════════════════════════════════════════════════════════


def _identity_decorator(fn: object) -> object:
    return fn


class TestRegisterHandlerTelegrind:
    def test_registers_on_dispatch_view(self) -> None:
        """register_handler calls dp.<view>(*rules)(handler)."""
        dp = MagicMock(spec=Dispatch)
        mock_view = MagicMock()
        mock_view.return_value = _identity_decorator
        dp.message = mock_view

        handler_obj = Handler(
            codec=rrc(EchoReq, EchoResp),
            runner=_mock_runner,
            capabilities=(),
        )
        trigger = _make_trigger(Command("test"), view="message")
        route = TelegrindRoute(
            handler=lambda ctx: "ok",
            rules=(Command("test"),),
        )

        register_handler(dp, trigger, handler_obj, route)
        mock_view.assert_called_once()

    def test_registers_on_callback_query_view(self) -> None:
        """register_handler uses the trigger's view attribute."""
        dp = MagicMock(spec=Dispatch)
        mock_view = MagicMock()
        mock_view.return_value = _identity_decorator
        dp.callback_query = mock_view

        handler_obj = Handler(
            codec=rrc(EchoReq, EchoResp),
            runner=_mock_runner,
            capabilities=(),
        )
        trigger = _make_trigger(Command("test"), view="callback_query")
        route = TelegrindRoute(
            handler=lambda ctx: "ok",
            rules=(Command("test"),),
        )

        register_handler(dp, trigger, handler_obj, route)
        mock_view.assert_called_once()


# ═══════════════════════════════════════════════════════════════════════════════
# telegrinder_compile with family (lines 661-671)
# ═══════════════════════════════════════════════════════════════════════════════


class TestTelegrindCompileFamily:
    def test_compile_with_family(self) -> None:
        """telegrinder_compile with family creates scope layer."""
        from emergent.graph._family import ScopeFamily
        from emergent.wire.compile._lifetime import Tier

        family: ScopeFamily[Tier] = ScopeFamily()
        app = (
            application()
            .mount(
                endpoint(_mock_runner)
                .expose(_make_trigger(Command("test")), rrc(EchoReq, EchoResp))
            )
        )
        dp = telegrinder_compile(app, family=family)
        assert isinstance(dp, Dispatch)
        assert hasattr(dp, "_scope_app")
        assert hasattr(dp, "_scope_app_types")


# ═══════════════════════════════════════════════════════════════════════════════
# CommandInfo and extract_command_info (lines 684-730)
# ═══════════════════════════════════════════════════════════════════════════════


class TestCommandInfo:
    def test_construction(self) -> None:
        info = CommandInfo(name="start", args=["login"], description="Start bot")
        assert info.name == "start"
        assert info.args == ["login"]
        assert info.description == "Start bot"
        assert info.order == 100

    def test_custom_order(self) -> None:
        info = CommandInfo(name="start", args=[], description="Start", order=1)
        assert info.order == 1


class TestExtractCommandInfo:
    def test_returns_none_when_no_command_rule(self) -> None:
        """No Command rule in trigger -> returns None."""
        trigger = _make_trigger()
        handler = Handler(
            codec=rrc(EchoReq, EchoResp),
            runner=_mock_runner,
            capabilities=(),
        )
        result = extract_command_info(trigger, handler)
        assert result is None

    def test_returns_none_when_no_help_meta(self) -> None:
        """Command rule but no HelpMeta capability -> returns None."""
        trigger = _make_trigger(Command("start"))
        handler = Handler(
            codec=rrc(EchoReq, EchoResp),
            runner=_mock_runner,
            capabilities=(),
        )
        result = extract_command_info(trigger, handler)
        assert result is None

    def test_returns_command_info_with_help_meta(self) -> None:
        """Command rule + HelpMeta -> returns CommandInfo."""
        trigger = _make_trigger(Command("start"))
        handler = Handler(
            codec=rrc(EchoReq, EchoResp),
            runner=_mock_runner,
            capabilities=(HelpMeta(description="Start the bot", order=1),),
        )
        result = extract_command_info(trigger, handler)
        assert result is not None
        assert result.name == "start"
        assert result.description == "Start the bot"
        assert result.order == 1

    def test_returns_none_when_help_meta_hidden(self) -> None:
        """HelpMeta with hidden=True -> returns None."""
        trigger = _make_trigger(Command("admin"))
        handler = Handler(
            codec=rrc(EchoReq, EchoResp),
            runner=_mock_runner,
            capabilities=(HelpMeta(description="Admin", hidden=True),),
        )
        result = extract_command_info(trigger, handler)
        assert result is None

    def test_extracts_args_from_command(self) -> None:
        """Command with arguments -> args list populated."""
        cmd = Command("register", Argument("login"), Argument("password"))
        trigger = _make_trigger(cmd)
        handler = Handler(
            codec=rrc(EchoReq, EchoResp),
            runner=_mock_runner,
            capabilities=(HelpMeta(description="Register"),),
        )
        result = extract_command_info(trigger, handler)
        assert result is not None
        assert "login" in result.args
        assert "password" in result.args


# ═══════════════════════════════════════════════════════════════════════════════
# generate_help_from_command_rules (lines 746-773)
# ═══════════════════════════════════════════════════════════════════════════════


class TestGenerateHelpFromCommandRules:
    def test_empty_app_returns_empty(self) -> None:
        app = Application()
        result = generate_help_from_command_rules(app)
        assert result == ""

    def test_single_command_generates_help(self) -> None:
        app = (
            application()
            .mount(
                endpoint(_mock_runner)
                .expose(
                    _make_trigger(Command("start")),
                    rrc(EchoReq, EchoResp),
                    HelpMeta(description="Start the bot", order=1),
                )
            )
        )
        result = generate_help_from_command_rules(app)
        assert "/start" in result

    def test_multiple_commands_sorted_by_order(self) -> None:
        app = (
            application()
            .mount(
                endpoint(_mock_runner)
                .expose(
                    _make_trigger(Command("help")),
                    rrc(EchoReq, EchoResp),
                    HelpMeta(description="Show help", order=99),
                )
            )
            .mount(
                endpoint(_mock_runner)
                .expose(
                    _make_trigger(Command("start")),
                    rrc(EchoReq, EchoResp),
                    HelpMeta(description="Start bot", order=1),
                )
            )
        )
        result = generate_help_from_command_rules(app)
        # start should appear before help due to order
        start_pos = result.find("/start")
        help_pos = result.find("/help")
        assert start_pos < help_pos

    def test_with_header_and_footer(self) -> None:
        app = (
            application()
            .mount(
                endpoint(_mock_runner)
                .expose(
                    _make_trigger(Command("start")),
                    rrc(EchoReq, EchoResp),
                    HelpMeta(description="Start"),
                )
            )
        )
        result = generate_help_from_command_rules(
            app, header="=== Commands ===", footer="=== End ==="
        )
        assert result.startswith("=== Commands ===")
        assert result.endswith("=== End ===")

    def test_custom_template(self) -> None:
        app = (
            application()
            .mount(
                endpoint(_mock_runner)
                .expose(
                    _make_trigger(Command("start")),
                    rrc(EchoReq, EchoResp),
                    HelpMeta(description="Start bot"),
                )
            )
        )
        result = generate_help_from_command_rules(
            app, template="/{name} — {description}"
        )
        assert "/start — Start bot" in result

    def test_with_args_in_template(self) -> None:
        cmd = Command("register", Argument("login"), Argument("password"))
        app = (
            application()
            .mount(
                endpoint(_mock_runner)
                .expose(
                    _make_trigger(cmd),
                    rrc(EchoReq, EchoResp),
                    HelpMeta(description="Register"),
                )
            )
        )
        result = generate_help_from_command_rules(app)
        assert "<login>" in result
        assert "<password>" in result

    def test_hidden_commands_excluded(self) -> None:
        app = (
            application()
            .mount(
                endpoint(_mock_runner)
                .expose(
                    _make_trigger(Command("admin")),
                    rrc(EchoReq, EchoResp),
                    HelpMeta(description="Admin", hidden=True),
                )
            )
            .mount(
                endpoint(_mock_runner)
                .expose(
                    _make_trigger(Command("start")),
                    rrc(EchoReq, EchoResp),
                    HelpMeta(description="Start"),
                )
            )
        )
        result = generate_help_from_command_rules(app)
        assert "/admin" not in result
        assert "/start" in result

    def test_custom_separator(self) -> None:
        app = (
            application()
            .mount(
                endpoint(_mock_runner)
                .expose(
                    _make_trigger(Command("a")),
                    rrc(EchoReq, EchoResp),
                    HelpMeta(description="A", order=1),
                )
            )
            .mount(
                endpoint(_mock_runner)
                .expose(
                    _make_trigger(Command("b")),
                    rrc(EchoReq, EchoResp),
                    HelpMeta(description="B", order=2),
                )
            )
        )
        result = generate_help_from_command_rules(app, separator=" | ")
        assert " | " in result


# ═══════════════════════════════════════════════════════════════════════════════
# fold_tg_handler_ctx
# ═══════════════════════════════════════════════════════════════════════════════


class TestFoldTgHandlerCtx:
    def test_empty_capabilities(self) -> None:
        from emergent.wire.axis._capability import TelegrinderHandlerContext

        ctx = fold_tg_handler_ctx(())
        assert isinstance(ctx, TelegrinderHandlerContext)
        assert ctx.edit_message is False
        assert ctx.silent is False

    def test_with_telegram_capabilities(self) -> None:
        from emergent.wire.axis._capability import TelegrinderHandlerContext
        from emergent.wire.axis.surface.dialects.telegram import Silent, ParseMode

        ctx = fold_tg_handler_ctx((Silent(), ParseMode(mode="HTML")))
        assert isinstance(ctx, TelegrinderHandlerContext)
        assert ctx.silent is True
        assert ctx.parse_mode == "HTML"

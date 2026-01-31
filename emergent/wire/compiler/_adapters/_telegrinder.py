"""Telegrinder adapter — functional compiler for telegrinder Dispatch.

    from emergent.wire.compiler import Axes, telegrinder_compile

    axes = Axes.default()
    dispatch = telegrinder_compile(wire_app, axes)
"""

from __future__ import annotations

from typing import Any, Callable, cast

from kungfu import Ok, Some, Nothing
from telegrinder.bot.cute_types.base import BaseCute
from telegrinder.bot.cute_types.message import MessageCute
from telegrinder.bot.dispatch import Dispatch
from telegrinder.bot.dispatch.context import Context
from telegrinder.bot.rules.abc import ABCRule, AndRule, OrRule
from nodnod import compose  # type: ignore[reportUnknownVariableType]

from emergent.wire._handler import Handler
from emergent.wire._scan import scan
from emergent.wire.axis.surface._app import Application
from emergent.wire.axis.surface.codecs.rrc import RequestResponseCodec
from emergent.wire.axis.surface.codecs.stateful import (
    StatefulCodec,
    StateStore,
    get_transitions,
)
from emergent.wire.axis.surface.codecs.resolve import get_method_params, wrap
from emergent.wire.axis.surface.triggers.telegrinder import TelegrindTrigger

from emergent.wire.compiler._core import Axes
from emergent.wire.compiler._rrc import execute_rrc
from emergent.wire.compiler._stateful import (
    execute_stateful_turn,
    execute_stateful_done,
    load_state,
    save_state,
    delete_state,
)

# ═══════════════════════════════════════════════════════════════════════════════
# Composition Helpers
# ═══════════════════════════════════════════════════════════════════════════════


async def compose_store_key(
    key_node: type,
    agent_cls: type,
    ctx: Context,
) -> str:
    """Compose key_node to get store key string."""
    agent = agent_cls.build({key_node})  # type: ignore[reportUnknownMemberType]
    async with compose(key_node, ctx, agent=agent) as result:  # type: ignore[reportUnknownVariableType]
        match result:
            case Ok(value):  # type: ignore[reportUnknownVariableType]
                return str(cast(Any, value))
            case _:  # type: ignore[reportUnknownVariableType]
                raise RuntimeError(f"Failed to compose key_node: {result}")


def _get_cute_value(compose_type: type, update_cute: Any) -> tuple[bool, Any]:
    """Extract cute type value from update_cute."""
    if update_cute is None:
        return False, "no update_cute"

    is_message = compose_type is MessageCute or (
        hasattr(compose_type, "__name__") and "Message" in compose_type.__name__
    )
    if is_message:
        cute_value = update_cute.message
        if cute_value is not None:
            return True, cute_value.unwrap()
        return False, "no message"

    return False, f"unsupported cute: {compose_type}"


async def _compose_node(
    compose_type: type,
    agent_cls: type,
    ctx: Context,
) -> tuple[bool, Any]:
    """Compose nodnod node."""
    agent = agent_cls.build({compose_type})  # type: ignore[reportUnknownMemberType]
    async with compose(compose_type, ctx, agent=agent) as result:  # type: ignore[reportUnknownVariableType]
        match result:
            case Ok(value):  # type: ignore[reportUnknownVariableType]
                return True, cast(Any, value)
            case _:  # type: ignore[reportUnknownVariableType]
                return False, "composition failed"


async def compose_param(
    name: str,
    original_type: type,
    compose_type: type,
    agent_cls: type,
    ctx: Context,
    update_cute: Any,
) -> Any:
    """Compose single __transition__ parameter."""
    is_context = compose_type is Context
    try:
        is_cute = issubclass(compose_type, BaseCute)
    except TypeError:
        is_cute = False
    is_node = hasattr(compose_type, "__dependencies__")

    if is_context:
        return wrap(original_type, True, ctx)

    if is_cute:
        success, value = _get_cute_value(compose_type, update_cute)
        return wrap(original_type, success, value)

    if is_node:
        success, value = await _compose_node(compose_type, agent_cls, ctx)
        return wrap(original_type, success, value)

    # Try telegrinder's compose
    async with compose(compose_type, ctx, agent_cls=agent_cls) as result:  # type: ignore[reportUnknownVariableType]
        match result:
            case Ok(value):  # type: ignore[reportUnknownVariableType]
                return wrap(original_type, True, value)
            case _:  # type: ignore[reportUnknownVariableType]
                return wrap(original_type, False, "composition failed")


async def try_compose_transition(
    method: Callable[..., Any],
    agent_cls: type,
    ctx: Context,
) -> tuple[dict[str, Any], bool]:
    """Try to compose params for transition. Returns (composed, all_satisfied)."""
    from kungfu import Option, Result
    from typing import get_origin

    params = get_method_params(method)
    update_cute = ctx.get("update_cute")
    composed: dict[str, Any] = {}
    all_satisfied = True

    for name, (original_type, compose_type) in params.items():
        origin = get_origin(original_type)
        is_optional = origin is Option or origin is Result

        result = await compose_param(
            name, original_type, compose_type, agent_cls, ctx, update_cute
        )
        composed[name] = result

        if not is_optional:
            if isinstance(result, Nothing):
                all_satisfied = False

    return composed, all_satisfied


async def resolve_transition(
    transitions: list[Callable[..., Any]],
    agent_cls: type,
    ctx: Context,
) -> tuple[Callable[..., Any], dict[str, Any]] | None:
    """Resolve first transition whose deps are satisfiable."""
    for method in transitions:
        composed, satisfied = await try_compose_transition(method, agent_cls, ctx)
        if satisfied:
            return method, composed
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# RRC Handler
# ═══════════════════════════════════════════════════════════════════════════════


def wrap_rrc_telegrinder(
    handler: Handler[RequestResponseCodec],
    axes: Axes,
) -> Any:
    """Wrap RRC handler for telegrinder."""
    req_cls = handler.codec.request

    async def _handler(req: Any) -> str:
        response = await execute_rrc(handler, req)
        return str(response)

    _handler.__annotations__ = {"req": req_cls, "return": str}
    return _handler


# ═══════════════════════════════════════════════════════════════════════════════
# Stateful Handler
# ═══════════════════════════════════════════════════════════════════════════════


class HasActiveFlowState(ABCRule):
    """Rule that matches if user has active flow state."""

    def __init__(
        self,
        store: StateStore[Any],
        key_node: type,
        agent_cls: type,
    ) -> None:
        self.store = store
        self.key_node = key_node
        self._agent_cls = agent_cls

    async def check(self, ctx: Context) -> bool:
        try:
            store_key = await compose_store_key(self.key_node, self._agent_cls, ctx)
            match await self.store.get(store_key):
                case Ok(Some(_)):
                    return True
                case _:
                    return False
        except RuntimeError:
            return False


def wrap_stateful_telegrinder(
    handler: Handler[StatefulCodec],
    axes: Axes,
) -> Any:
    """Wrap StatefulCodec handler for telegrinder."""
    codec = handler.codec
    agent_cls = codec.agent_cls
    transitions = get_transitions(codec.flow)

    async def _handler(ctx: Context) -> Any:
        # 1. Get store key
        store_key = await compose_store_key(codec.key_node, agent_cls, ctx)

        # 2. Load state
        state = await load_state(codec, store_key)

        # 3. Resolve transition
        resolved = await resolve_transition(transitions, agent_cls, ctx)
        if resolved is None:
            raise RuntimeError("No transition resolvable")

        method, composed = resolved

        # 4. Execute transition
        new_state, response, is_terminal = await execute_stateful_turn(
            handler, state, method, composed
        )

        # 5. Continue or Done
        if not is_terminal:
            await save_state(codec, store_key, state, new_state)
            return response

        # 6. Done
        _, rejection, final = await execute_stateful_done(handler, new_state)
        await delete_state(codec, store_key)

        if rejection is not None:
            return str(rejection)
        return str(final)

    _handler.__annotations__ = {"ctx": Context, "return": Any}
    return _handler


# ═══════════════════════════════════════════════════════════════════════════════
# Registration
# ═══════════════════════════════════════════════════════════════════════════════


def create_stateful_rule(trigger: TelegrindTrigger, codec: StatefulCodec) -> ABCRule:
    """Create composite rule: trigger_rules OR has_active_state."""
    state_rule = HasActiveFlowState(
        store=codec.store,
        key_node=codec.key_node,
        agent_cls=codec.agent_cls,
    )

    if not trigger.rules:
        return state_rule

    initial = trigger.rules[0] if len(trigger.rules) == 1 else AndRule(*trigger.rules)
    return OrRule(initial, state_rule)


def register_handler(
    dp: Dispatch,
    trigger: TelegrindTrigger,
    handler: Handler[Any],
    axes: Axes,
) -> None:
    """Register handler on dispatch."""
    view = getattr(dp, trigger.view)

    if isinstance(handler.codec, RequestResponseCodec):
        view(*trigger.rules)(wrap_rrc_telegrinder(handler, axes))
    elif isinstance(handler.codec, StatefulCodec):
        rule = create_stateful_rule(trigger, handler.codec)
        view(rule)(wrap_stateful_telegrinder(handler, axes))


# ═══════════════════════════════════════════════════════════════════════════════
# Compilation
# ═══════════════════════════════════════════════════════════════════════════════


def telegrinder_compile(app: Application, axes: Axes | None = None) -> Dispatch:
    """Compile wire Application to telegrinder Dispatch.

    Args:
        app: Wire application
        axes: Axes context (default: Axes.default())

    Returns:
        telegrinder Dispatch
    """
    axes = axes or Axes.default()
    dp = Dispatch()

    for trigger, handler in scan(app, TelegrindTrigger, RequestResponseCodec):
        register_handler(dp, trigger, handler, axes)

    for trigger, handler in scan(app, TelegrindTrigger, StatefulCodec):
        register_handler(dp, trigger, handler, axes)

    return dp


__all__ = (
    "telegrinder_compile",
    "wrap_rrc_telegrinder",
    "wrap_stateful_telegrinder",
    "register_handler",
    "compose_store_key",
    "resolve_transition",
    "HasActiveFlowState",
)

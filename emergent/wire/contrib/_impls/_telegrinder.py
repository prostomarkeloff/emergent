"""Telegrinder compiler — compile wire Application to telegrinder Dispatch.

    from emergent.wire.contrib import telegrinder

    dp = telegrinder.from_application(app)
    bot = Telegrinder(api, dispatch=dp)
    bot.run_forever()
"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING, cast

from kungfu import Ok, Error, Some, Nothing
from telegrinder.bot.cute_types.base import BaseCute
from telegrinder.bot.cute_types.message import MessageCute
from telegrinder.bot.dispatch import Dispatch
from telegrinder.bot.dispatch.context import Context
from telegrinder.bot.rules.abc import ABCRule, AndRule, OrRule
from telegrinder.node.compose import compose  # type: ignore

from emergent.wire._app import Application
from emergent.wire._endpoint import Endpoint
from emergent.wire._handler import Handler
from emergent.wire._scan import scan, scan_endpoint
from emergent.wire.codecs.rrc import RequestResponseCodec, execute as rrc_execute
from emergent.wire.codecs.resolve import get_transition_params, wrap
from emergent.wire.codecs.stateful import (
    StatefulCodec,
    StateStore,
    parse_transition_result,
    run_middlewares,
)
from emergent.wire.triggers.telegrinder import TelegrindTrigger

if TYPE_CHECKING:
    from nodnod.agent.base import Agent


# ─── Composition Helpers ───────────────────────────────────────────────────────


async def _compose_store_key(
    key_node: type,
    agent_cls: type[Agent],
    ctx: Context,
) -> str:
    """Compose key_node to get store key string."""
    agent = agent_cls.build({key_node})
    async with compose(key_node, ctx, agent=agent) as result:  # type: ignore
        match result:
            case Ok(value):  # type: ignore
                return str(cast(Any, value))
            case Error(err):
                raise RuntimeError(f"Failed to compose key_node: {err}")
            case _:
                raise RuntimeError("Unexpected compose result")


def _get_cute_value(compose_type: type, update_cute: Any) -> tuple[bool, Any]:
    """Extract cute type value from update_cute. Returns (success, value_or_error)."""
    if update_cute is None:
        return False, "no update_cute in context"

    is_message = compose_type is MessageCute or (
        hasattr(compose_type, "__name__") and "Message" in compose_type.__name__
    )
    if is_message:
        cute_value = update_cute.message
        if cute_value is not None:
            return True, cute_value.unwrap()
        return False, "no message in update"

    return False, f"unsupported cute type: {compose_type}"


async def _compose_node(
    compose_type: type,
    agent_cls: type[Agent],
    ctx: Context,
) -> tuple[bool, Any]:
    """Compose a nodnod Node. Returns (success, value_or_error)."""
    agent = agent_cls.build({compose_type})
    async with compose(compose_type, ctx, agent=agent) as result:  # type: ignore
        match result:
            case Ok(value):  # type: ignore
                return True, cast(Any, value)
            case Error(_):
                return False, "composition failed"
            case _:
                return False, "unexpected compose result"


async def _compose_unknown(
    compose_type: type,
    agent_cls: type[Agent],
    ctx: Context,
) -> tuple[bool, Any]:
    """Try to compose unknown type via telegrinder. Returns (success, value_or_error)."""
    async with compose(compose_type, ctx, agent_cls=agent_cls) as result:
        match result:
            case Ok(value):
                return True, value
            case Error(_):
                return False, "composition failed"
            case _:
                return False, "unexpected compose result"


async def _compose_param(
    name: str,
    original_type: type,
    compose_type: type,
    agent_cls: type[Agent],
    ctx: Context,
    update_cute: Any,
) -> Any:
    """Compose a single __transition__ parameter."""
    # Determine type category
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

    # Unknown — try telegrinder's compose
    success, value = await _compose_unknown(compose_type, agent_cls, ctx)
    return wrap(original_type, success, value)


async def _compose_transition_params(
    params: dict[str, tuple[type, type]],
    agent_cls: type[Agent],
    ctx: Context,
) -> dict[str, Any]:
    """Compose all __transition__ parameters."""
    update_cute = ctx.get("update_cute")
    composed: dict[str, Any] = {}

    for name, (original_type, compose_type) in params.items():
        composed[name] = await _compose_param(
            name, original_type, compose_type, agent_cls, ctx, update_cute
        )

    return composed


# ─── State Flow Helpers ────────────────────────────────────────────────────────


async def _handle_continue(
    store: StateStore[Any],
    store_key: str,
    old_state: Any,
    new_state: Any,
    response: Any,
) -> Any:
    """Handle non-terminal transition result."""
    # Only save if state changed (prevents ghost states)
    if new_state is not old_state:
        await store.set(store_key, new_state)

    match response:
        case Some(resp):  # type: ignore
            return cast(Any, resp)
        case Nothing():
            return None
        case _:
            return None


async def _handle_done(
    handler: Handler[StatefulCodec],
    store: StateStore[Any],
    store_key: str,
    state: Any,
) -> str:
    """Handle terminal (Done) transition — run middlewares, execute op, format response."""
    codec = handler.codec

    # Run middlewares
    scope_extras, rejection = await run_middlewares(codec.middlewares, state)
    if isinstance(rejection, Some):
        await store.delete(store_key)
        return str(rejection.unwrap())

    # Execute: to_domain() → Op → runner.run() → from_domain()
    op = state.to_domain()
    op_result = await handler.runner.run(op, scope_extras=scope_extras)
    final_response = codec.response.from_domain(op_result)

    await store.delete(store_key)
    return str(final_response)


# ─── HasActiveFlowState Rule ───────────────────────────────────────────────────


class HasActiveFlowState(ABCRule):
    """Rule that matches if user has active flow state."""

    def __init__(
        self,
        store: StateStore[Any],
        key_node: type,
        agent_cls: type[Agent],
    ) -> None:
        self.store = store
        self.key_node = key_node
        self._agent_cls = agent_cls

    async def check(self, ctx: Context) -> bool:
        """Check if user has active state in store."""
        try:
            store_key = await _compose_store_key(self.key_node, self._agent_cls, ctx)
            state = await self.store.get(store_key)
            return state is not None
        except RuntimeError:
            return False


# ─── Handler Wrappers ──────────────────────────────────────────────────────────


def _wrap_rrc_handler(handler: Handler[RequestResponseCodec]) -> Any:
    """Wrap RRC Handler in telegrinder-compatible async function."""
    req_cls = handler.codec.request

    async def _handler(req: Any) -> str:
        response = await rrc_execute(handler, req)
        return str(response)

    _handler.__annotations__ = {"req": req_cls, "return": str}
    return _handler


def _wrap_stateful_handler(handler: Handler[StatefulCodec]) -> Any:
    """Wrap StatefulCodec Handler in telegrinder-compatible async function."""
    codec = handler.codec
    params = get_transition_params(codec.flow)

    async def _handler(ctx: Context) -> Any:
        # 1. Get store key
        store_key = await _compose_store_key(codec.key_node, codec.agent_cls, ctx)

        # 2. Load or create state
        state = await codec.store.get(store_key) or codec.flow()

        # 3. Compose params and call transition
        composed = await _compose_transition_params(params, codec.agent_cls, ctx)
        raw_result = await state.__transition__(**composed)
        result = parse_transition_result(raw_result)

        # 4. Handle result
        if not result.is_terminal:
            return await _handle_continue(
                codec.store, store_key, state, result.state_or_done, result.response
            )

        return await _handle_done(handler, codec.store, store_key, state)

    _handler.__annotations__ = {"ctx": Context, "return": Any}
    return _handler


# ─── Dispatch Building ─────────────────────────────────────────────────────────


def _create_stateful_rule(trigger: TelegrindTrigger, codec: StatefulCodec) -> ABCRule:
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


def _register_pair(
    dp: Dispatch,
    trigger: TelegrindTrigger,
    handler: Handler[Any],
) -> None:
    """Register a single trigger-handler pair on dispatch."""
    view = getattr(dp, trigger.view)

    if isinstance(handler.codec, RequestResponseCodec):
        view(*trigger.rules)(_wrap_rrc_handler(handler))
    elif isinstance(handler.codec, StatefulCodec):
        rule = _create_stateful_rule(trigger, handler.codec)
        view(rule)(_wrap_stateful_handler(handler))


def add_endpoint_to_dispatch(dp: Dispatch, endp: Endpoint) -> None:
    """Register endpoint's telegrinder exposures on dispatch."""
    for trigger, handler in scan_endpoint(endp, TelegrindTrigger, RequestResponseCodec):
        _register_pair(dp, trigger, handler)

    for trigger, handler in scan_endpoint(endp, TelegrindTrigger, StatefulCodec):
        _register_pair(dp, trigger, handler)


def from_application(app: Application) -> Dispatch:
    """Compile wire Application to telegrinder Dispatch."""
    dp = Dispatch()

    for trigger, handler in scan(app, TelegrindTrigger, RequestResponseCodec):
        _register_pair(dp, trigger, handler)

    for trigger, handler in scan(app, TelegrindTrigger, StatefulCodec):
        _register_pair(dp, trigger, handler)

    return dp

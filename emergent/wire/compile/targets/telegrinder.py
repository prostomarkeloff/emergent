"""Telegrinder adapter — functional compiler for telegrinder Dispatch.

    from emergent.wire.compile import Axes, telegrinder_compile

    axes = Axes.default()
    dispatch = telegrinder_compile(wire_app, axes)

## Command Argument Generation

The compiler auto-generates `Argument` rules from request fields annotated with
`tg.CommandArg()`. This enables DRY command parsing:

    from emergent.wire.axis.schema.dialects import tg

    @dataclass
    class RegisterRequest:
        login: Annotated[str, tg.CommandArg()]
        password: Annotated[str, tg.CommandArg()]

    # Compiler generates: Command("register", Argument("login"), Argument("password"))

The `enhance_command_with_args()` function inspects request type and enhances
Command rules with generated Arguments.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, cast

from kungfu import Ok, Some, Nothing
from telegrinder.bot.cute_types.base import BaseCute
from telegrinder.bot.cute_types.message import MessageCute
from telegrinder.bot.dispatch import Dispatch
from telegrinder.bot.dispatch.context import Context
from telegrinder.bot.rules.abc import ABCRule, AndRule, OrRule
from telegrinder.bot.rules.command import Command, Argument
from telegrinder.api import API
from telegrinder.types import Update
from nodnod import Scope
from nodnod.agent.base import Agent

from emergent.wire.axis.surface._handler import Handler
from emergent.wire.axis.surface._scan import scan
from emergent.wire.axis.surface.capabilities import SurfaceCapability
from emergent.wire.axis.surface.capabilities import tg as tg_cap
from emergent.wire.axis.surface._app import Application
from emergent.wire.axis.surface.codecs.rrc import RequestResponseCodec
from emergent.wire.axis.surface.codecs.stateful import (
    StatefulCodec,
    StateStore,
    get_transitions,
)
from emergent.wire.axis.surface.codecs.immediate import ImmediateCodec, ImmediateFactoryCodec
from emergent.wire.axis.surface.codecs.resolve import get_method_params, wrap
from emergent.wire.axis.surface.triggers.telegrinder import TelegrindTrigger

from emergent.wire.compile._core import Axes, scan_all_codecs
from emergent.wire.compile._execute import execute_rrc_unified, execute_immediate_unified
from emergent.wire.compile._request import compose_node_value
from emergent.wire.compile._stateful import (
    execute_stateful_turn,
    execute_stateful_done,
    load_state,
    save_state,
    delete_state,
)
from emergent.wire.axis.schema._inspect import inspect_dataclass
from emergent.wire.axis.schema.dialects.tg import CommandArg


# ═══════════════════════════════════════════════════════════════════════════════
# Capability Helpers
# ═══════════════════════════════════════════════════════════════════════════════


def find_edit_message_cap(
    capabilities: tuple[SurfaceCapability, ...],
) -> tg_cap.EditMessage | None:
    """Find EditMessage capability if present."""
    for cap in capabilities:
        if isinstance(cap, tg_cap.EditMessage):
            return cap
    return None


def find_answer_callback_cap(
    capabilities: tuple[SurfaceCapability, ...],
) -> tg_cap.AnswerCallback | None:
    """Find AnswerCallback capability if present."""
    for cap in capabilities:
        if isinstance(cap, tg_cap.AnswerCallback):
            return cap
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# Command Argument Generation
# ═══════════════════════════════════════════════════════════════════════════════


def generate_command_args(request_cls: type) -> tuple[list[Argument], bool]:
    """Generate telegrinder Arguments from request fields with tg.CommandArg.

    Inspects request dataclass for fields annotated with tg.CommandArg()
    and generates corresponding telegrinder Argument objects.

    Args:
        request_cls: Request dataclass type

    Returns:
        Tuple of (Argument list, has_greedy) where has_greedy indicates
        if any argument has greedy=True (captures rest of line)
    """
    import dataclasses
    if not dataclasses.is_dataclass(request_cls):
        return [], False

    fields = inspect_dataclass(request_cls)
    args: list[Argument] = []
    has_greedy = False

    for name, info in fields.items():
        cmd_arg = info.get(CommandArg)
        if cmd_arg is not None:
            validators: list[Any] = []
            # Add type validator for int fields
            if info.base_type is int:
                validators.append(int)
            args.append(Argument(
                name=name,
                validators=validators,
                optional=cmd_arg.optional,  # type: ignore[union-attr]
            ))
            if cmd_arg.greedy:  # type: ignore[union-attr]
                has_greedy = True

    return args, has_greedy


def enhance_command_with_args(
    trigger: TelegrindTrigger,
    request_cls: type,
) -> TelegrindTrigger:
    """Enhance Command rule in trigger with generated Arguments.

    If trigger contains a Command rule without arguments, and request has
    tg.CommandArg fields, generates Arguments and creates enhanced Command.

    Args:
        trigger: Original trigger
        request_cls: Request dataclass type

    Returns:
        Enhanced trigger with Command arguments, or original if no enhancement needed
    """
    args, has_greedy = generate_command_args(request_cls)
    if not args:
        return trigger

    # Find Command rule and enhance it
    new_rules: list[ABCRule] = []
    for rule in trigger.rules:
        if isinstance(rule, Command) and not rule.arguments:
            # Create new Command with generated arguments
            # Use lazy=True if any argument is greedy (captures rest of line)
            enhanced = Command(
                rule.names,
                *args,
                prefixes=rule.prefixes,
                separator=rule.separator,
                lazy=has_greedy or rule.lazy,
                validate_mention=rule.validate_mention,
                ignore_case=rule.ignore_case,
            )
            new_rules.append(enhanced)
        else:
            new_rules.append(rule)

    return TelegrindTrigger(*new_rules, view=trigger.view)


# ═══════════════════════════════════════════════════════════════════════════════
# Composition Helpers
# ═══════════════════════════════════════════════════════════════════════════════


async def compose_store_key(
    key_node: type,
    agent_cls: type[Agent],
    ctx: Context,
) -> str:
    """Compose key_node to get store key string.

    Uses nodnod's agent system with Context and Update injected into scope.
    """
    agent = agent_cls.build({key_node})

    async with Scope() as scope:
        # Inject Context, Update, and API so nodes can access them
        scope.inject(Context, ctx)
        scope.inject(Update, ctx.update)
        scope.inject(API, ctx.api)

        await agent.run(local_scope=scope, mapped_scopes={})

        result = scope.retrieve(key_node)
        match result:
            case Some(value):
                return str(value.value)
            case Nothing():
                raise RuntimeError(f"Failed to compose key_node: {key_node.__name__}")


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
    agent_cls: type[Agent],
    ctx: Context,
) -> tuple[bool, Any]:
    """Compose nodnod node with Context and Update injected.

    Delegates to unified compose_node_value() with telegrinder-specific scope setup.
    """
    async with Scope() as scope:
        scope.inject(Context, ctx)
        scope.inject(Update, ctx.update)
        scope.inject(API, ctx.api)
        return await compose_node_value(compose_type, agent_cls, scope)


async def compose_param(
    name: str,
    original_type: type,
    compose_type: type,
    agent_cls: type[Agent],
    ctx: Context,
    update_cute: Any,
) -> Any:
    """Compose single __transition__ parameter.

    Handles Context, Cute types, and nodnod nodes.
    """
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

    # For non-node types, try to get from context
    ctx_value = ctx.get(name)
    if ctx_value is not None:
        return wrap(original_type, True, ctx_value)

    return wrap(original_type, False, f"Cannot resolve {name}: {compose_type}")


async def try_compose_transition(
    method: Callable[..., Any],
    agent_cls: type[Agent],
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
    agent_cls: type[Agent],
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
) -> Callable[[Context], object]:
    """Wrap RRC handler for telegrinder — trivial with unified execution."""
    edit_message_cap = find_edit_message_cap(handler.capabilities)

    async def _handler(ctx: Context) -> object:
        def inject_scope(scope: Scope) -> None:
            scope.inject(Context, ctx)
            scope.inject(Update, ctx.update)
            scope.inject(API, ctx.api)

        response = await execute_rrc_unified(
            handler=handler,
            axes=axes,
            get_value=lambda name: ctx.get(name),
            inject_scope=inject_scope,
        )

        # EditMessage capability — edit instead of sending new message
        if edit_message_cap is not None and isinstance(response, dict) and "text" in response:
            response_dict = cast(dict[str, Any], response)
            text = str(response_dict.pop("text"))
            if await edit_message_cap.deliver(ctx, text, **response_dict):
                return None

        return response

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
) -> Callable[[Context], object]:
    """Wrap StatefulCodec handler for telegrinder."""
    codec = handler.codec
    agent_cls = codec.agent_cls
    transitions = get_transitions(codec.flow)

    async def _handler(ctx: Context) -> object:
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

        # 6. Done — execute with enrichers
        async with Scope() as done_scope:
            done_scope.inject(Context, ctx)
            done_scope.inject(Update, ctx.update)
            done_scope.inject(API, ctx.api)
            final = await execute_stateful_done(handler, new_state, done_scope)

        await delete_state(codec, store_key)
        return final

    return _handler


# ═══════════════════════════════════════════════════════════════════════════════
# Immediate Handlers
# ═══════════════════════════════════════════════════════════════════════════════


def wrap_immediate_telegrinder(
    handler: Handler[Any],
    axes: Axes,
) -> Callable[[Context], object]:
    """Wrap Immediate codecs for telegrinder — trivial with unified execution."""
    edit_message_cap = find_edit_message_cap(handler.capabilities)

    async def _handler(ctx: Context) -> object:
        response = execute_immediate_unified(handler)

        # EditMessage capability — telegrinder-specific delivery
        if edit_message_cap is not None and isinstance(response, dict) and "text" in response:
            response_dict = cast(dict[str, Any], response)
            text = str(response_dict.pop("text"))
            if await edit_message_cap.deliver(ctx, text, **response_dict):
                return None

        return response

    return _handler


# Alias for backwards compatibility
wrap_immediate_factory_telegrinder = wrap_immediate_telegrinder


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


def register_handler[C](
    dp: Dispatch,
    trigger: TelegrindTrigger,
    handler: Handler[C],
    axes: Axes,
) -> None:
    """Register handler on dispatch.

    For RRC handlers, enhances Command rules with Arguments generated
    from request fields annotated with tg.CommandArg().
    """
    view = getattr(dp, trigger.view)

    if isinstance(handler.codec, RequestResponseCodec):
        # Enhance trigger with generated Command arguments
        rrc_handler = cast(Handler[RequestResponseCodec], handler)
        enhanced = enhance_command_with_args(trigger, handler.codec.request)
        view(*enhanced.rules)(wrap_rrc_telegrinder(rrc_handler, axes))
    elif isinstance(handler.codec, StatefulCodec):
        stateful_handler = cast(Handler[StatefulCodec], handler)
        rule = create_stateful_rule(trigger, handler.codec)
        view(rule)(wrap_stateful_telegrinder(stateful_handler, axes))
    elif isinstance(handler.codec, ImmediateCodec):
        immediate_handler = cast(Handler[ImmediateCodec], handler)
        view(*trigger.rules)(wrap_immediate_telegrinder(immediate_handler, axes))
    elif isinstance(handler.codec, ImmediateFactoryCodec):
        factory_handler = cast(Handler[ImmediateFactoryCodec], handler)
        view(*trigger.rules)(wrap_immediate_factory_telegrinder(factory_handler, axes))


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

    # Unified compile loop
    scan_all_codecs(
        app,
        TelegrindTrigger,
        lambda trigger, handler: register_handler(dp, trigger, handler, axes),
    )

    return dp


# ═══════════════════════════════════════════════════════════════════════════════
# Help Generation
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class CommandInfo:
    """Info about a command for help generation."""
    name: str
    args: list[str]
    request_cls: type | None = None
    decorator_description: str | None = None
    decorator_order: int = 100


def extract_command_info[C](
    trigger: TelegrindTrigger,
    handler: Handler[C],
) -> CommandInfo | None:
    """Extract command info from trigger and handler."""
    from emergent.wire.axis.schema.dialects.tg.help import get_command

    cmd_rule: Command | None = None
    for rule in trigger.rules:
        if isinstance(rule, Command):
            cmd_rule = rule
            break

    if cmd_rule is None:
        return None

    names_list = list(cmd_rule.names) if cmd_rule.names else []
    name = names_list[0] if names_list else "unknown"

    args: list[str] = []
    request_cls: type | None = None
    decorator_description: str | None = None
    decorator_order: int = 100

    if isinstance(handler.codec, RequestResponseCodec):
        request_cls = handler.codec.request
        generated, _ = generate_command_args(request_cls)
        args = [a.name for a in generated]

        help_meta = get_command(request_cls)
        decorator_description = help_meta.description
        decorator_order = help_meta.order
    elif isinstance(handler.codec, StatefulCodec):
        request_cls = handler.codec.flow
        # Stateful flows don't have command args
        args = []

        help_meta = get_command(request_cls)
        decorator_description = help_meta.description
        decorator_order = help_meta.order

    return CommandInfo(
        name=name,
        args=args,
        request_cls=request_cls,
        decorator_description=decorator_description,
        decorator_order=decorator_order,
    )


def generate_help_from_command_rules(
    app: Application,
    *,
    get_description: Callable[[type], str] | None = None,
    descriptions: dict[type, Callable[[], str]] | None = None,
    order: list[type] | None = None,
    template: str = "/{name} {args}",
    header: str = "",
    footer: str = "",
    separator: str = "\n",
) -> str:
    """Generate help text from Application's Telegram command rules.

    Supports two approaches:
    1. Decorators on request classes (@tg.help.command, @tg.help.hidden)
    2. Explicit parameters (get_description, descriptions, order)

    Explicit parameters ALWAYS override decorators.
    """
    from emergent.wire.axis.schema.dialects.tg.help import is_hidden

    commands: list[CommandInfo] = []

    for trigger, handler in scan(app, TelegrindTrigger, RequestResponseCodec):
        info = extract_command_info(trigger, handler)
        if info and info.request_cls and not is_hidden(info.request_cls):
            commands.append(info)

    for trigger, handler in scan(app, TelegrindTrigger, ImmediateCodec):
        info = extract_command_info(trigger, handler)
        if info:
            commands.append(info)

    for trigger, handler in scan(app, TelegrindTrigger, StatefulCodec):
        info = extract_command_info(trigger, handler)
        if info and info.request_cls and not is_hidden(info.request_cls):
            commands.append(info)

    if order:
        order_map = {cls: i for i, cls in enumerate(order)}
        commands.sort(key=lambda c: order_map.get(c.request_cls, 999) if c.request_cls else 999)
    else:
        commands.sort(key=lambda c: c.decorator_order)

    lines: list[str] = []
    for cmd in commands:
        desc = ""
        if cmd.request_cls:
            if descriptions and cmd.request_cls in descriptions:
                desc = descriptions[cmd.request_cls]()
            elif get_description:
                desc = get_description(cmd.request_cls)
            elif cmd.decorator_description:
                desc = cmd.decorator_description

        args_str = " ".join(f"<{arg}>" for arg in cmd.args)
        line = template.format(
            name=cmd.name,
            args=args_str,
            description=desc,
        ).strip()
        lines.append(line)

    parts: list[str] = []
    if header:
        parts.append(header)
    if lines:
        parts.append(separator.join(lines))
    if footer:
        parts.append(footer)

    return "\n".join(parts)


# Alias for backwards compatibility
from_application = telegrinder_compile


__all__ = (
    "telegrinder_compile",
    "from_application",
    "wrap_rrc_telegrinder",
    "wrap_stateful_telegrinder",
    "wrap_immediate_telegrinder",
    "wrap_immediate_factory_telegrinder",
    "register_handler",
    "compose_store_key",
    "resolve_transition",
    "HasActiveFlowState",
    "CommandInfo",
    "extract_command_info",
    "generate_help_from_command_rules",
    # Capability helpers
    "find_edit_message_cap",
    "find_answer_callback_cap",
)


# Alias for cleaner API
compile = telegrinder_compile

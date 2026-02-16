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
from telegrinder.bot.cute_types.callback_query import CallbackQueryCute
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
from emergent.wire.axis.surface.codecs.delegate import DelegateCodec
from emergent.wire.axis.surface.codecs.resolve import get_method_params, wrap
from emergent.wire.axis.surface.triggers.telegrinder import TelegrindTrigger

from emergent.wire.compile._core import Axes, fold_field, fold
from emergent.wire.compile._target import CodecAdapter, TargetCompiler
from emergent.wire.compile._execute import (
    execute_rrc_unified,
    execute_immediate_unified,
    execute_stateful_unified,
)
from emergent.wire.compile._lifetime import ScopeLayer, Tier, App, Request
from emergent.graph._family import ScopeFamily
from emergent.wire.axis.schema._inspect import inspect_dataclass


# ═══════════════════════════════════════════════════════════════════════════════
# Response Formatting
# ═══════════════════════════════════════════════════════════════════════════════

# Types that telegrinder's return manager already handles natively.
_PASSTHROUGH_TYPES = (str, int, float, bool, bytes, dict, list, tuple, type(None))


def _format_tg_response(response: object) -> object:
    """Convert response to str for telegrinder's return manager.

    Only converts types that:
    1. Are NOT primitives/collections (return manager handles those)
    2. Are NOT from telegrinder itself (HTML etc. have dedicated managers)
    3. Define a custom __str__ (not the default object.__str__)
    """
    tp = type(response)
    if tp in _PASSTHROUGH_TYPES:
        return response
    if getattr(tp, "__module__", "").startswith("telegrinder"):
        return response
    if tp.__str__ is not object.__str__:
        return str(response)
    return response
from emergent.wire.axis._capability import (
    TelegrinderInputCompilable, TelegrinderInputContext,
    TelegrinderHandlerContext, TelegrinderCompilable,
)


def fold_tg_handler_ctx(
    capabilities: tuple[SurfaceCapability, ...],
) -> TelegrinderHandlerContext:
    """Fold handler capabilities into TelegrinderHandlerContext."""
    return fold(
        capabilities,
        TelegrinderHandlerContext(),
        TelegrinderCompilable,
        "compile_telegrinder",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Command Argument Generation
# ═══════════════════════════════════════════════════════════════════════════════


def generate_command_args(request_cls: type) -> tuple[list[Argument], bool]:
    """Generate telegrinder Arguments from request fields with tg.CommandArg.

    Uses fold_field to read TelegrinderInputContext from capabilities,
    then generates corresponding telegrinder Argument objects.

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
        ctx = TelegrinderInputContext(field_name=name, field_type=info.base_type)
        ctx = fold_field(info, ctx, TelegrinderInputCompilable, "compile_telegrinder_input")

        if ctx.is_command_arg:
            validators: list[Any] = []
            if ctx.field_type is int:
                validators.append(int)
            args.append(Argument(
                name=name,
                validators=validators,
                optional=ctx.optional,
            ))
            if ctx.greedy:
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


def _inject_tg_context(scope: Scope, ctx: Context) -> None:
    """Inject telegrinder context into scope for nodnod composition.

    When ``per_event_scope`` is already an ancestor, Update and API are
    reachable through the parent chain — only Context is added.
    Otherwise Update and API are injected explicitly.
    """
    if not scope.has_parent(ctx.per_event_scope):
        scope.inject(Update, ctx.update)
        scope.inject(API, ctx.api)
    scope.inject(Context, ctx)


async def compose_store_key(
    key_node: type,
    agent_cls: type[Agent],
    ctx: Context,
    *,
    scope: Scope | None = None,
    scope_layer: ScopeLayer | None = None,
) -> str:
    """Compose key_node to get store key string.

    Uses nodnod's agent system with Context and Update injected into scope.
    When *scope* is provided, reuses it instead of creating a new one.
    When *scope_layer* is provided, creates a child of the app scope.
    """
    from emergent.graph._compose import Composer

    if scope is not None:
        composer = Composer.create(scope, agent_cls)
        success, value = await composer.compose(key_node)
        if success:
            return str(value)
        raise RuntimeError(f"Failed to compose key_node: {key_node.__name__}")

    parent = scope_layer.parent if scope_layer else ctx.per_event_scope
    new_scope = parent.create_child("tg-store-key")
    async with new_scope:
        _inject_tg_context(new_scope, ctx)

        composer = Composer.create(new_scope, agent_cls)
        success, value = await composer.compose(key_node)
        if success:
            return str(value)
        raise RuntimeError(f"Failed to compose key_node: {key_node.__name__}")


def _get_cute_value(compose_type: type, update_cute: Any) -> tuple[bool, Any]:
    """Extract cute type value from update_cute via incoming_update."""
    if update_cute is None:
        return False, "no update_cute"

    incoming = update_cute.incoming_update
    if isinstance(incoming, compose_type):
        return True, incoming
    return False, f"update is {type(incoming).__name__}, not {compose_type.__name__}"


async def _compose_node(
    compose_type: type,
    agent_cls: type[Agent],
    ctx: Context,
    *,
    scope: Scope | None = None,
    scope_layer: ScopeLayer | None = None,
) -> tuple[bool, Any]:
    """Compose nodnod node with Context and Update injected.

    When *scope* is provided, reuses it instead of creating a new one.
    When *scope_layer* is provided, creates a child of the app scope.
    """
    from emergent.graph._compose import Composer

    if scope is not None:
        composer = Composer.create(scope, agent_cls)
        return await composer.compose(compose_type)

    parent = scope_layer.parent if scope_layer else ctx.per_event_scope
    new_scope = parent.create_child("tg-compose")
    async with new_scope:
        _inject_tg_context(new_scope, ctx)
        composer = Composer.create(new_scope, agent_cls)
        return await composer.compose(compose_type)


async def compose_param(
    name: str,
    original_type: type,
    compose_type: type,
    agent_cls: type[Agent],
    ctx: Context,
    update_cute: Any,
    *,
    scope: Scope | None = None,
) -> Any:
    """Compose single __transition__ parameter.

    Handles Scope, Context, Cute types, and nodnod nodes.
    When *scope* is provided, threads it to nodnod composition and
    resolves ``scope: Scope`` params directly.
    """
    # Thread the compiler's scope to transitions that request it
    if compose_type is Scope:
        if scope is not None:
            return scope
        return wrap(original_type, False, "no scope available")

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
        success, value = await _compose_node(compose_type, agent_cls, ctx, scope=scope)
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
    *,
    scope: Scope | None = None,
) -> tuple[dict[str, Any], bool]:
    """Try to compose params for transition. Returns (composed, all_satisfied).

    When *scope* is provided, threads it to compose_param for nodnod
    composition reuse and ``scope: Scope`` resolution.
    """
    from kungfu import Option, Result
    from typing import get_origin

    params = get_method_params(method)
    update_cute = ctx.get("update_cute")
    composed: dict[str, Any] = {}
    all_satisfied = True

    for name, (original_type, compose_type) in params.items():
        origin = get_origin(original_type)
        is_optional = origin is Option or origin is Result

        try:
            result = await compose_param(
                name, original_type, compose_type, agent_cls, ctx, update_cute,
                scope=scope,
            )
        except RuntimeError:
            all_satisfied = False
            break
        composed[name] = result

        if not is_optional:
            if isinstance(result, Nothing):
                all_satisfied = False

    return composed, all_satisfied


async def resolve_transition(
    transitions: list[Callable[..., Any]],
    agent_cls: type[Agent],
    ctx: Context,
    *,
    scope: Scope | None = None,
) -> tuple[Callable[..., Any], dict[str, Any]] | None:
    """Resolve first transition whose deps are satisfiable.

    When *scope* is provided, threads it through to transitions.
    """
    for method in transitions:
        composed, satisfied = await try_compose_transition(
            method, agent_cls, ctx, scope=scope,
        )
        if satisfied:
            return method, composed
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# TelegrindRoute — structured wrap result (NO heuristics in registration)
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class TelegrindRoute:
    """Structured result of wrapping a handler for telegrinder.

    The wrap function knows its codec and fills ALL metadata.
    Registration reads ONLY from this — zero codec sniffing.
    """

    handler: Callable[[Context], object]
    rules: tuple[ABCRule, ...]


# ═══════════════════════════════════════════════════════════════════════════════
# RRC Handler
# ═══════════════════════════════════════════════════════════════════════════════


def wrap_rrc_telegrinder(
    handler: Handler[RequestResponseCodec],
    trigger: TelegrindTrigger,
    axes: Axes,
) -> TelegrindRoute:
    """Wrap RRC handler for telegrinder. Returns handler + enhanced rules."""
    tg_ctx = fold_tg_handler_ctx(handler.capabilities)
    edit_message_cap = tg_ctx.edit_message_cap

    async def _handler(ctx: Context) -> object:
        def inject_scope(scope: Scope) -> None:
            _inject_tg_context(scope, ctx)

        response = await execute_rrc_unified(
            handler=handler,
            axes=axes,
            get_value=lambda name: ctx.get(name),
            inject_scope=inject_scope,
            format_response=_format_tg_response,
        )

        # EditMessage capability — edit instead of sending new message
        if edit_message_cap is not None and isinstance(response, dict) and "text" in response:
            response_dict = cast(dict[str, Any], response)
            text = str(response_dict.pop("text"))
            if await edit_message_cap.deliver(ctx, text, **response_dict):
                return None

        return response

    # Rule preparation: enhance Command rules with generated Arguments
    enhanced = enhance_command_with_args(trigger, handler.codec.request)
    return TelegrindRoute(handler=_handler, rules=tuple(enhanced.rules))


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
            # Use per_event_scope as parent — it already has Update & API
            # injected by telegrinder's dispatch.  We only add Context
            # (same as telegrinder's own run_agent does for local scopes).
            scope = ctx.per_event_scope.create_child("check-active-flow")
            scope.inject(Context, ctx)

            store_key = await compose_store_key(
                self.key_node, self._agent_cls, ctx, scope=scope,
            )
            match await self.store.get(store_key):
                case Ok(Some(_)):
                    return True
                case _:
                    return False
        except Exception:
            return False


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


def wrap_stateful_telegrinder(
    handler: Handler[StatefulCodec],
    trigger: TelegrindTrigger,
    axes: Axes,
) -> TelegrindRoute:
    """Wrap StatefulCodec handler for telegrinder. Returns handler + composite rule."""
    codec = handler.codec
    agent_cls = codec.agent_cls
    transitions = get_transitions(codec.flow)

    async def _handler(ctx: Context) -> object:
        # Single scope for the entire handler — no duplicates.
        # Transitions that declare ``scope: Scope`` receive this scope,
        # and nodnod node composition reuses it instead of creating ad-hoc ones.
        layer = axes.scope_layer
        parent = layer.parent if layer else ctx.per_event_scope
        scope = parent.create_child("tg-stateful")
        async with scope:
            _inject_tg_context(scope, ctx)

            store_key = await compose_store_key(
                codec.key_node, agent_cls, ctx, scope=scope,
            )

            def inject_done_scope(done_scope: Scope) -> None:
                _inject_tg_context(done_scope, ctx)

            async def _resolve() -> tuple[Any, dict[str, Any]] | None:
                return await resolve_transition(
                    transitions, agent_cls, ctx, scope=scope,
                )

            response, _is_done = await execute_stateful_unified(
                handler=handler,
                store_key=store_key,
                resolve_transition=_resolve,
                inject_scope=inject_done_scope,
                format_response=_format_tg_response,
                axes=axes,
            )
        return response

    # Rule: trigger_rules OR has_active_state
    rule = create_stateful_rule(trigger, codec)
    return TelegrindRoute(handler=_handler, rules=(rule,))


# ═══════════════════════════════════════════════════════════════════════════════
# Immediate Handlers
# ═══════════════════════════════════════════════════════════════════════════════


def wrap_immediate_telegrinder(
    handler: Handler[Any],
    trigger: TelegrindTrigger,
    axes: Axes,
) -> TelegrindRoute:
    """Wrap Immediate codecs for telegrinder."""

    async def _handler(ctx: Context) -> object:
        return execute_immediate_unified(handler, format_response=_format_tg_response)

    return TelegrindRoute(handler=_handler, rules=tuple(trigger.rules))


# Alias for backwards compatibility
wrap_immediate_factory_telegrinder = wrap_immediate_telegrinder


# ═══════════════════════════════════════════════════════════════════════════════
# Delegate Handler
# ═══════════════════════════════════════════════════════════════════════════════


def wrap_delegate_telegrinder(
    handler: Handler[DelegateCodec],
    trigger: TelegrindTrigger,
    axes: Axes,
) -> TelegrindRoute:
    """Wrap DelegateCodec handler for telegrinder."""
    from emergent.wire.compile._execute import execute_delegate_unified

    tg_ctx = fold_tg_handler_ctx(handler.capabilities)

    async def _handler(ctx: Context) -> object:
        def inject_scope(scope: Scope) -> None:
            _inject_tg_context(scope, ctx)

        result = await execute_delegate_unified(
            handler=handler,
            inject_scope=inject_scope,
            axes=axes,
        )

        if tg_ctx.answer_callback and trigger.view == "callback_query":
            await ctx.update_cute.incoming_update.answer(
                text=tg_ctx.answer_callback_text,
                show_alert=tg_ctx.answer_callback_show_alert,
            )

        return result

    return TelegrindRoute(handler=_handler, rules=tuple(trigger.rules))


# ═══════════════════════════════════════════════════════════════════════════════
# Registration — reads ONLY from TelegrindRoute
# ═══════════════════════════════════════════════════════════════════════════════


def register_handler(
    dp: Dispatch,
    trigger: TelegrindTrigger,
    handler: Handler[Any],
    route: TelegrindRoute,
) -> None:
    """Register pre-wrapped handler on dispatch.

    Reads ONLY from TelegrindRoute — zero codec sniffing.
    """
    view = getattr(dp, trigger.view)
    view(*route.rules)(route.handler)


# ═══════════════════════════════════════════════════════════════════════════════
# Compilation
# ═══════════════════════════════════════════════════════════════════════════════


TELEGRINDER_COMPILER: TargetCompiler[TelegrindTrigger] = TargetCompiler(
    trigger_type=TelegrindTrigger,
    adapters=(
        CodecAdapter(RequestResponseCodec, wrap_rrc_telegrinder),
        CodecAdapter(StatefulCodec, wrap_stateful_telegrinder),
        CodecAdapter(ImmediateCodec, wrap_immediate_telegrinder),
        CodecAdapter(ImmediateFactoryCodec, wrap_immediate_factory_telegrinder),
        CodecAdapter(DelegateCodec, wrap_delegate_telegrinder),
    ),
)


def telegrinder_compile(
    app: Application,
    axes: Axes | None = None,
    compiler: TargetCompiler[TelegrindTrigger] | None = None,
    family: ScopeFamily[Tier] | None = None,
) -> Dispatch:
    """Compile wire Application to telegrinder Dispatch.

    Args:
        app: Wire application
        axes: Axes context (default: Axes.default())
        compiler: TargetCompiler (default: TELEGRINDER_COMPILER). Pass custom
                  compiler to add/swap/remove codec adapters.
        family: Optional ScopeFamily for tiered scope management. When provided,
                an App scope is composed once at startup and Request scopes
                inherit from it. mapped_scopes routes node results to tiers.

    Returns:
        telegrinder Dispatch
    """
    base_axes = axes or Axes.default()
    _compiler = compiler or TELEGRINDER_COMPILER
    request_axes = base_axes
    dp = Dispatch()

    if family is not None:
        from types import MappingProxyType

        app_scope = Scope(detail="tg-app")
        layer = ScopeLayer(
            scopes=MappingProxyType({App: app_scope}),
            family=family,
            leaf=Request,
        )
        request_axes = base_axes.with_scope_layer(layer)
        dp._scope_app = app_scope  # type: ignore[attr-defined]
        dp._scope_app_types = family.types_for(App)  # type: ignore[attr-defined]

    for trigger, handler, route in _compiler.scan_and_wrap(app, request_axes):
        register_handler(dp, trigger, handler, route)

    return dp


# ═══════════════════════════════════════════════════════════════════════════════
# Help Generation
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class CommandInfo:
    """Info about a command for help generation."""
    name: str
    args: list[str]
    description: str
    order: int = 100


def extract_command_info[C](
    trigger: TelegrindTrigger,
    handler: Handler[C],
) -> CommandInfo | None:
    """Extract command info from trigger and handler.

    Reads ONLY from HelpMeta capability. No codec sniffing.
    No HelpMeta = not visible in help.
    """
    from emergent.wire.axis.surface.dialects.telegram import HelpMeta

    cmd_rule: Command | None = None
    for rule in trigger.rules:
        if isinstance(rule, Command):
            cmd_rule = rule
            break

    if cmd_rule is None:
        return None

    name = list(cmd_rule.names)[0] if cmd_rule.names else "unknown"

    # Args from the Command rule itself (no codec sniffing)
    args = [a.name for a in cmd_rule.arguments]

    # HelpMeta capability is THE source
    for cap in handler.capabilities:
        if isinstance(cap, HelpMeta):
            if cap.hidden:
                return None
            return CommandInfo(
                name=name,
                args=args,
                description=cap.description,
                order=cap.order,
            )

    return None  # No HelpMeta = not visible in help


def generate_help_from_command_rules(
    app: Application,
    *,
    template: str = "/{name} {args}",
    header: str = "",
    footer: str = "",
    separator: str = "\n",
) -> str:
    """Generate help text from Application's Telegram command rules.

    Capability-driven: reads ONLY from HelpMeta capabilities.
    No HelpMeta on an exposure = excluded from help.
    """
    commands: list[CommandInfo] = []

    for trigger, handler in scan(app, TelegrindTrigger):
        info = extract_command_info(trigger, handler)
        if info is not None:
            commands.append(info)

    commands.sort(key=lambda c: c.order)

    lines: list[str] = []
    for cmd in commands:
        args_str = " ".join(f"<{arg}>" for arg in cmd.args)
        line = template.format(
            name=cmd.name,
            args=args_str,
            description=cmd.description,
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
    "TelegrindRoute",
    "TELEGRINDER_COMPILER",
    "wrap_rrc_telegrinder",
    "wrap_stateful_telegrinder",
    "wrap_immediate_telegrinder",
    "wrap_immediate_factory_telegrinder",
    "wrap_delegate_telegrinder",
    "register_handler",
    "compose_store_key",
    "resolve_transition",
    "HasActiveFlowState",
    "CommandInfo",
    "extract_command_info",
    "generate_help_from_command_rules",
    # Capability helpers
    "fold_tg_handler_ctx",
)


# Alias for cleaner API
compile = telegrinder_compile

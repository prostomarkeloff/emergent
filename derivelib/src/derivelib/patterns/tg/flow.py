"""tg_flow pattern — multi-step Telegram conversation from annotated dataclass.

Compiles annotated entity fields → StatefulCodec flow class with @transition methods.

    from derivelib.patterns.tg.flow import tg_flow, TextInput, Inline, Confirm

    @derive(tg_flow(command="start", key_node=ChatIdNode))
    @dataclass
    class Registration:
        name: Annotated[str, TextInput("What's your name?")]
        role: Annotated[str, Inline("Role?", admin="Admin", user="User")]

        async def finish(self, db: ...) -> Result[FinishResult, DomainError]:
            ...

Exchange types (defined in widget.py, re-exported here):
- TextInput(prompt) — collect text from message
- Inline(prompt, **options) — inline keyboard single selection
- Confirm(prompt) — yes/no inline keyboard
- Counter(prompt) — interactive +/- stepper
- Multiselect(prompt, **options) — toggleable multi-choice
- Prefilled() — pre-filled from context (not prompted)

Validation annotations:
- MinLen(n), MaxLen(n), Pattern(regex)

The pattern generates:
1. A flow class with Option[T] fields + @transition methods
2. An Op type from entity fields
3. A handler that calls entity.finish()
4. StatefulCodec wrapping the flow
5. TelegrindTrigger exposures on message + callback_query views
"""

from __future__ import annotations

import hashlib
import inspect
import json
import warnings
from enum import Enum
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field, make_dataclass, replace
from typing import (
    TYPE_CHECKING,
    Annotated,
    Protocol as TypingProtocol,
    get_args,
    get_origin,
    get_type_hints,
)

if TYPE_CHECKING:
    from derivelib._dialect import ChainedPattern
    from nodnod.agent.base import Agent

from kungfu import Error, Nothing, Ok, Option, Result, Some
from nodnod import Scope

from telegrinder.bot.cute_types.callback_query import CallbackQueryCute
from telegrinder.bot.cute_types.message import MessageCute
from telegrinder.bot.dispatch.context import Context
from telegrinder.bot.rules.command import Command
from telegrinder.bot.rules.payload import PayloadModelRule
from telegrinder.tools.keyboard import InlineButton, InlineKeyboard
from telegrinder.types.objects import InlineKeyboardMarkup, ReplyKeyboardMarkup

from emergent.wire.axis.schema.dialects.tg import CommandArg
from emergent.wire.axis.storage import MemoryStorage
from emergent.wire.axis.surface import Exposure
from emergent.wire.axis.surface.capabilities import ScopeEnricher, EnricherNext
from emergent.wire.axis.surface.capabilities._base import SurfaceCapability
from emergent.wire.axis.surface.codecs.stateful import (
    Done,
    StatefulCodec,
    transition,
)
from emergent.wire.axis.surface.triggers.telegrinder import TelegrindTrigger

from derivelib._codegen import FieldSpec, create_dataclass, create_sentinel_operation
from derivelib._ctx import SurfaceCtx
from derivelib._derivation import Derivation, DerivationT
from derivelib._errors import DomainError
from derivelib.axes.schema import inspect_entity

# Widget types — defined in widget.py, re-exported here for backward compat
from derivelib.patterns.tg.uilib.theme import DEFAULT_THEME, UITheme
from derivelib.patterns.tg.widget import (
    Advance,
    AnyKeyboard,
    Case,
    Confirm,
    ContactInput,
    Counter,
    DatePicker,
    DocumentInput,
    DynamicInline,
    DynamicMultiselect,
    DynamicRadio,
    EnumInline,
    FlowWidget,
    Inline,
    ListBuilder,
    LocationInput,
    MaxLen,
    MediaGroupInput,
    MinLen,
    Multiselect,
    NoOp,
    NumberInput,
    OPTIONS_ENTRIES_ATTR,
    Pattern,
    PhotoInput,
    PinInput,
    Radio,
    Rating,
    RecurrencePicker,
    Reject,
    ScrollingInline,
    Slider,
    Stay,
    SummaryReview,
    TextInput,
    TimePicker,
    TimeSlotPicker,
    Toggle,
    VideoInput,
    VoiceInput,
    WidgetContext,
    options,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Mode enums
# ═══════════════════════════════════════════════════════════════════════════════


class ShowMode(Enum):
    """Controls how flow prompts are rendered.

    SEND (default): always send a new message for each prompt.
    EDIT: edit the previous message in place (clean chat).
    DELETE_AND_SEND: delete old message + send new (for media type changes).
    """

    SEND = "send"
    EDIT = "edit"
    DELETE_AND_SEND = "delete_and_send"


class LaunchMode(Enum):
    """Controls what happens when user re-enters a flow they're already in.

    STANDARD (default): command text is treated as field input.
    RESET: reset the flow, start fresh.
    EXCLUSIVE: block with "already in progress" message.
    SINGLE_TOP: re-send current prompt, continue where left off.
    """

    STANDARD = "standard"
    RESET = "reset"
    EXCLUSIVE = "exclusive"
    SINGLE_TOP = "single_top"


# ═══════════════════════════════════════════════════════════════════════════════
# Annotations (flow-specific, not widgets)
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Prefilled:
    """Pre-filled from context (not prompted).

    Used for fields that come from redirect context, not user input.

        project_id: Annotated[int, Prefilled()]
    """


@dataclass(frozen=True, slots=True)
class When:
    """Conditional field — only prompted when predicate returns True.

    Predicate receives a dict of currently collected field values.
    Fields not yet collected have value None.

        priority: Annotated[str, Inline("..."), When(lambda v: v.get("kind") == "bug")]
    """

    predicate: Callable[[dict[str, object]], bool]


# ═══════════════════════════════════════════════════════════════════════════════
# Flow stack — sub-flow navigation
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class StackFrame:
    """A paused parent flow on the stack."""

    command: str
    result: object | None = None


class FlowStackStorage(TypingProtocol):
    """Protocol for flow stack storage backends.

    Implement push/pop keyed by user identifier string.
    """

    def push(self, key: str, frame: StackFrame) -> None: ...
    def pop(self, key: str) -> StackFrame | None: ...


class FlowStack:
    """In-memory flow stack (default implementation of FlowStackStorage).

    Tracks parent flows so sub-flows can return to the caller.

        stack = FlowStack()                        # in-memory default
        with_stacking(stack=my_redis_stack)         # custom backend
    """

    def __init__(self) -> None:
        self._data: dict[str, list[StackFrame]] = {}

    def push(self, key: str, frame: StackFrame) -> None:
        self._data.setdefault(key, []).append(frame)

    def pop(self, key: str) -> StackFrame | None:
        frames = self._data.get(key, [])
        return frames.pop() if frames else None


# ═══════════════════════════════════════════════════════════════════════════════
# FinishResult — flow completion result
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class FinishResult:
    """Result from flow finish() — what happens after completion.

        return Ok(FinishResult.message("Done!"))
        return Ok(FinishResult.then("Created!", command="tasks", project_id=42))
    """

    text: str
    next_command: str | None = None
    is_sub_flow: bool = False
    context: dict[str, int | str | float | bool] = field(
        default_factory=lambda: dict[str, int | str | float | bool](),
    )
    reply_markup: InlineKeyboardMarkup | ReplyKeyboardMarkup | None = None

    @staticmethod
    def with_keyboard(text: str, markup: InlineKeyboardMarkup | ReplyKeyboardMarkup) -> FinishResult:
        """Text response with keyboard."""
        return FinishResult(text=text, reply_markup=markup)

    @staticmethod
    def message(text: str) -> FinishResult:
        """Simple text response after flow completes."""
        return FinishResult(text=text)

    @staticmethod
    def then(
        text: str,
        command: str,
        **context: int | str | float | bool,
    ) -> FinishResult:
        """Text response + redirect to another command."""
        return FinishResult(text=text, next_command=command, context=context)

    @staticmethod
    def sub_flow(
        text: str,
        command: str,
        **context: int | str | float | bool,
    ) -> FinishResult:
        """Text response + push current flow to stack, start sub-flow.

        When the sub-flow completes, the stack is popped and the user
        is directed back to the parent flow.

        Requires ``with_stacking()`` transform on the pattern.
        """
        return FinishResult(
            text=text, next_command=command, is_sub_flow=True, context=context,
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Field classification
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class FlowField:
    """Classified entity field for flow generation."""

    name: str
    base_type: type
    exchange: FlowWidget | Prefilled
    validators: tuple[MinLen | MaxLen | Pattern, ...]
    is_optional: bool  # str | None → optional, can /skip
    command_arg: CommandArg | None = None
    when: When | None = None


def _classify_fields(entity: type) -> list[FlowField]:
    """Inspect entity and classify fields by exchange annotation."""
    hints = get_type_hints(entity, include_extras=True)
    result: list[FlowField] = []

    for name, hint in hints.items():
        annotations: tuple[object, ...] = ()
        base_type = hint

        if get_origin(hint) is Annotated:
            args = get_args(hint)
            base_type = args[0]
            annotations = args[1:]

        # Find exchange annotation
        exchange: FlowWidget | Prefilled | None = None
        validators: list[MinLen | MaxLen | Pattern] = []
        cmd_arg: CommandArg | None = None
        when_cond: When | None = None

        for ann in annotations:
            if isinstance(ann, (FlowWidget, Prefilled)):
                exchange = ann
            elif isinstance(ann, (MinLen, MaxLen, Pattern)):
                validators.append(ann)
            elif isinstance(ann, CommandArg):
                cmd_arg = ann
            elif isinstance(ann, When):
                when_cond = ann

        # CommandArg without explicit exchange → implicitly Prefilled
        if exchange is None and cmd_arg is not None:
            exchange = Prefilled()

        if exchange is None:
            continue

        # Check if optional (str | None)
        is_optional = False
        origin = get_origin(base_type)
        if origin is type(str | None):  # types.UnionType
            type_args = get_args(base_type)
            non_none = [t for t in type_args if t is not type(None)]
            if len(non_none) == 1:
                base_type = non_none[0]
                is_optional = True

        result.append(FlowField(
            name=name,
            base_type=base_type,
            exchange=exchange,
            validators=tuple(validators),
            is_optional=is_optional,
            command_arg=cmd_arg,
            when=when_cond,
        ))

    return result


def _extract_compose_deps(fn: Callable[..., object]) -> list[tuple[str, type]]:
    """Extract compose.Node dependencies from a callable's type hints.

    Returns list of (param_name, node_type) pairs — one per compose.Node param.
    Works on any callable: finish(), @options providers, etc.
    """
    from emergent.wire.axis.schema.dialects.compose import Node as ComposeNode

    try:
        hints = get_type_hints(fn, include_extras=True)
    except Exception:
        return []

    deps: list[tuple[str, type]] = []
    for name, hint in hints.items():
        if name in ("self", "cls", "return"):
            continue
        if get_origin(hint) is Annotated:
            args = get_args(hint)
            for ann in args[1:]:
                if isinstance(ann, ComposeNode):
                    deps.append((name, ann.node_type))
                    break
    return deps


def _extract_finish_compose_deps(entity: type) -> list[tuple[str, type]]:
    """Extract compose.Node dependencies from entity.finish() type hints."""
    finish = getattr(entity, "finish", None)
    if finish is None:
        return []
    return _extract_compose_deps(finish)


def _discover_options(entity: type) -> dict[str, Callable[..., object]]:
    """Scan entity classmethods for @options decorators.

    Returns {field_name: bound_method} for each @options-decorated provider.
    Handles both decorator orders: @classmethod @options and @options @classmethod.
    """
    result: dict[str, Callable[..., object]] = {}
    for attr_name in dir(entity):
        if attr_name.startswith("__"):
            continue
        raw = inspect.getattr_static(entity, attr_name, None)
        if raw is None:
            continue
        entries = getattr(raw, OPTIONS_ENTRIES_ATTR, [])
        if not entries and isinstance(raw, (classmethod, staticmethod)):
            entries = getattr(raw.__func__, OPTIONS_ENTRIES_ATTR, [])
        for entry in entries:
            result[entry.field_name] = getattr(entity, attr_name)
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# When helpers — field value resolution and active-field navigation
# ═══════════════════════════════════════════════════════════════════════════════


def _resolve_field_values(
    state: object,
    all_fields: list[FlowField],
) -> dict[str, object]:
    """Build dict of currently collected field values for When predicates.

    Returns field_name → value (unwrapped from Some) or None if not yet collected.
    """
    values: dict[str, object] = {}
    for ff in all_fields:
        val = getattr(state, ff.name)
        match val:
            case Some(v):
                values[ff.name] = v
            case _:
                values[ff.name] = None
    return values


def _find_next_active(
    state: object,
    from_step: int,
    prompted: list[FlowField],
    all_fields: list[FlowField],
) -> int | None:
    """Find next active (When-true) prompted field index after from_step.

    Returns index into prompted list, or None if no more active fields.
    """
    values = _resolve_field_values(state, all_fields)
    for i in range(from_step + 1, len(prompted)):
        ff = prompted[i]
        if ff.when is None or ff.when.predicate(values):
            return i
    return None


def _find_prev_active(
    state: object,
    from_step: int,
    prompted: list[FlowField],
    all_fields: list[FlowField],
) -> int | None:
    """Find previous active (When-true) prompted field index before from_step.

    Returns index into prompted list, or None if at start.
    """
    values = _resolve_field_values(state, all_fields)
    for i in range(from_step - 1, -1, -1):
        ff = prompted[i]
        if ff.when is None or ff.when.predicate(values):
            return i
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# Flow class generation
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class _FlowCallbackData:
    """Callback data for flow inline buttons.

    Encodes flow identity + selected value. Used by the callback_query
    transition to route inline button presses to the correct flow.
    """

    flow: str  # flow name (short hash)
    value: str  # selected option key


class _HasToDomain(TypingProtocol):
    def to_domain(self) -> object: ...


class _FlowDone(Done):
    """Done subclass that carries the final flow state.

    execute_stateful_done calls state.to_domain() on the Done object.
    This subclass delegates to the accumulated flow state so to_domain()
    works correctly.

    Done is @dataclass(frozen=True, slots=True), so we must declare
    __slots__ for new attrs and use object.__setattr__ to bypass frozen.
    """

    __slots__ = ("_flow_state",)

    def __init__(self, flow_state: _HasToDomain) -> None:
        object.__setattr__(self, "_flow_state", flow_state)

    def to_domain(self) -> object:
        return self._flow_state.to_domain()


def _flow_name_hash(entity: type) -> str:
    """Collision-resistant flow name from fully qualified class name."""
    qualified = f"{entity.__module__}.{entity.__qualname__}"
    return hashlib.sha256(qualified.encode()).hexdigest()[:8]


def _widget_ctx(
    ff: FlowField,
    flow_name: str,
    state: object,
    all_fields: list[FlowField] | None = None,
    theme: UITheme = DEFAULT_THEME,
) -> WidgetContext:
    """Build WidgetContext for a FlowField from current flow state."""
    flow_state: dict[str, object] = {}
    if all_fields is not None:
        flow_state = _resolve_field_values(state, all_fields)
    # Read cached dynamic options from flow state (_dyn_opts field)
    dyn_opts: dict[str, Mapping[str, str]] = getattr(state, "_dyn_opts", {})
    field_opts: Mapping[str, str] = dyn_opts.get(ff.name, {})
    return WidgetContext(
        flow_name=flow_name,
        field_name=ff.name,
        current_value=getattr(state, ff.name),
        base_type=ff.base_type,
        validators=ff.validators,
        is_optional=ff.is_optional,
        flow_state=flow_state,
        dynamic_options=field_opts,
        theme=theme,
    )


def _generate_flow_class(
    entity: type,
    flow_fields: list[FlowField],
    op_type: type,
    flow_name: str,
    show_mode: ShowMode = ShowMode.SEND,
    launch_mode: LaunchMode = LaunchMode.STANDARD,
    command: str = "",
    options_providers: Mapping[str, Callable[..., object]] | None = None,
    shows_progress: bool = False,
    shows_summary: bool = False,
    theme: UITheme = DEFAULT_THEME,
    agent_cls: type[Agent] | None = None,
) -> type:
    """Generate a flow class with Option[T] fields and @transition methods.

    The flow class:
    - Has one Option[T] field per prompted (non-Prefilled) field
    - Has a `_step` int tracking the current collection step
    - Has @transition methods for message and callback_query
    - Has to_domain() that constructs the Op from accumulated state
    """
    prompted_fields = [f for f in flow_fields if not isinstance(f.exchange, Prefilled)]
    has_callback = shows_summary or any(
        isinstance(f.exchange, FlowWidget) and f.exchange.needs_callback
        for f in prompted_fields
    )

    # Build the flow class namespace
    _entity = entity
    _op_type = op_type
    _flow_fields = flow_fields
    _prompted = prompted_fields
    _flow_name = flow_name
    _show_mode = show_mode
    _launch_mode = launch_mode
    _command = command
    _options_map = options_providers or {}
    _shows_progress = shows_progress
    _shows_summary = shows_summary
    _theme = theme
    _agent_cls = agent_cls

    def _progress_prefix(step_idx: int) -> str:
        """Build progress prefix like '[2/8] ' for with_progress."""
        total = len(_prompted)
        pos = step_idx + 1
        bar_len = min(total, 10)
        filled = round(pos / total * bar_len) if total > 0 else 0
        bar = "\u2588" * filled + "\u2591" * (bar_len - filled)
        return f"{bar} {pos}/{total}\n\n"

    async def _resolve_field_options(
        field_name: str,
        state: object,
        scope: Scope | None = None,
    ) -> Mapping[str, str]:
        """Resolve dynamic options for a field via its @options provider.

        Inspects the provider signature — parameters matching flow field names
        get injected with the current field values (cascade support).
        compose.* deps are resolved via the compiler's threaded Composer.
        """
        if field_name not in _options_map:
            return {}
        provider = _options_map[field_name]
        sig = inspect.signature(provider)
        values = _resolve_field_values(state, _flow_fields)

        # Resolve compose.* deps via the compiler's scope
        compose_kwargs: dict[str, object] = {}
        if scope is not None:
            from emergent.graph._compose import Composer

            composer = Composer.create(scope, _agent_cls)
            compose_kwargs = await composer.resolve_params(provider)

        kwargs: dict[str, object] = {}
        for param_name in sig.parameters:
            if param_name in compose_kwargs:
                kwargs[param_name] = compose_kwargs[param_name]
            elif param_name in values and values[param_name] is not None:
                kwargs[param_name] = values[param_name]
        return await provider(**kwargs)

    def _current_field(self: object) -> FlowField | None:
        """Get current prompted field based on _step."""
        step: int = getattr(self, "_step")
        if step >= len(_prompted):
            return None
        return _prompted[step]

    async def _advance_or_done(
        next_state: object,
        current_step: int,
        send: Callable[[str, AnyKeyboard | None], Awaitable[int]],
        scope: Scope | None = None,
    ) -> object:
        """Send next prompt (advance) or return Done (all fields collected).

        Uses _find_next_active to skip When-false fields.
        send returns message_id (used for ShowMode.EDIT tracking).
        scope: nodnod Scope for compose.Node resolution in @options providers.
        """
        next_idx = _find_next_active(next_state, current_step, _prompted, _flow_fields)
        if next_idx is not None:
            next_state = replace(next_state, _step=next_idx)
            next_ff = _prompted[next_idx]
            # Resolve dynamic options for next field if needed
            if next_ff.name in _options_map:
                opts = await _resolve_field_options(next_ff.name, next_state, scope)
                if opts:
                    cur_dyn: dict[str, Mapping[str, str]] = {**getattr(next_state, "_dyn_opts")}
                    cur_dyn[next_ff.name] = opts
                    next_state = replace(next_state, _dyn_opts=cur_dyn)
                elif next_ff.is_optional:
                    # Auto-skip: no options available for optional dynamic field
                    next_state = replace(next_state, **{next_ff.name: Some(None)})
                    return await _advance_or_done(next_state, next_idx, send, scope)
            widget = next_ff.exchange
            if isinstance(widget, FlowWidget):
                w_ctx = _widget_ctx(next_ff, _flow_name, next_state, _flow_fields, theme=_theme)
                text, kb = await widget.render(w_ctx)
                if _shows_progress:
                    text = _progress_prefix(next_idx) + text
                msg_id = await send(text, kb)
            else:
                msg_id = await send("", None)
            if _show_mode in (ShowMode.EDIT, ShowMode.DELETE_AND_SEND):
                next_state = replace(next_state, _msg_id=msg_id)
            return next_state
        # All fields done — show summary or finish
        if _shows_summary:
            return await _show_summary(next_state, send)
        return _FlowDone(next_state)

    async def _show_summary(
        state: object,
        send: Callable[[str, AnyKeyboard | None], Awaitable[int]],
    ) -> object:
        """Render auto-summary of all collected fields for confirmation."""
        values = _resolve_field_values(state, _flow_fields)
        lines: list[str] = []
        for ff in _flow_fields:
            v = values.get(ff.name)
            if v is None:
                continue
            label = ff.name.replace("_", " ").title()
            lines.append(f"  {label}: {v}")
        text = "Review your answers:\n\n" + "\n".join(lines) if lines else "(no data)"
        kb = InlineKeyboard()
        kb.add(InlineButton(
            text=_theme.action.done,
            callback_data=json.dumps({"flow": _flow_name, "value": "_summary:ok"}),
        ))
        next_state = replace(state, _step=len(_prompted), _summary_pending=True)
        msg_id = await send(text, kb)
        if _show_mode in (ShowMode.EDIT, ShowMode.DELETE_AND_SEND):
            next_state = replace(next_state, _msg_id=msg_id)
        return next_state

    # Collect fields sourced from command args (for initial pre-fill)
    _cmd_arg_fields = [f for f in flow_fields if f.command_arg is not None]

    # --- send factory: message context ---
    def _make_send_for_message(
        message: MessageCute, msg_id: int, chat_id: int,
    ) -> Callable[[str, AnyKeyboard | None], Awaitable[int]]:
        """Build a send function for message transitions based on ShowMode."""
        if _show_mode is ShowMode.EDIT:
            async def _send(text: str, kb: AnyKeyboard | None) -> int:
                if kb is not None and not isinstance(kb.get_markup(), InlineKeyboardMarkup):
                    # Reply keyboard can't be used with edit — fall back to send
                    warnings.warn(
                        "ShowMode.EDIT: widget returned a reply keyboard "
                        "which is incompatible with edit_message_text. "
                        "Falling back to send_message.",
                        stacklevel=2,
                    )
                    result = await message.answer(text, reply_markup=kb.get_markup())
                    match result:
                        case Ok(sent):
                            return sent.message_id
                        case _:
                            return 0
                if msg_id == 0:
                    if kb is not None:
                        result = await message.answer(text, reply_markup=kb.get_markup())
                    else:
                        result = await message.answer(text)
                    match result:
                        case Ok(sent):
                            return sent.message_id
                        case _:
                            return 0
                else:
                    if kb is not None:
                        await message.ctx_api.edit_message_text(
                            chat_id=chat_id, message_id=msg_id,
                            text=text, reply_markup=kb.get_markup(),
                        )
                    else:
                        await message.ctx_api.edit_message_text(
                            chat_id=chat_id, message_id=msg_id, text=text,
                        )
                    return msg_id
        elif _show_mode is ShowMode.DELETE_AND_SEND:
            async def _send(text: str, kb: AnyKeyboard | None) -> int:
                if msg_id != 0:
                    await message.ctx_api.delete_message(
                        chat_id=chat_id, message_id=msg_id,
                    )
                if kb is not None:
                    result = await message.answer(text, reply_markup=kb.get_markup())
                else:
                    result = await message.answer(text)
                match result:
                    case Ok(sent):
                        return sent.message_id
                    case _:
                        return 0
        else:
            async def _send(text: str, kb: AnyKeyboard | None) -> int:
                if kb is not None:
                    await message.answer(text, reply_markup=kb.get_markup())
                else:
                    await message.answer(text)
                return 0
        return _send

    # --- send factory: callback context ---
    def _make_send_for_callback(
        callback: CallbackQueryCute, chat_id: int,
    ) -> Callable[[str, AnyKeyboard | None], Awaitable[int]]:
        """Build a send function for callback transitions based on ShowMode."""
        if _show_mode is ShowMode.EDIT:
            async def _send_cb(text: str, kb: AnyKeyboard | None) -> int:
                if kb is not None and not isinstance(kb.get_markup(), InlineKeyboardMarkup):
                    # Reply keyboard can't be used with edit — fall back to send
                    warnings.warn(
                        "ShowMode.EDIT: widget returned a reply keyboard "
                        "which is incompatible with edit_text. "
                        "Falling back to send_message.",
                        stacklevel=2,
                    )
                    send_result = await callback.ctx_api.send_message(
                        chat_id=chat_id, text=text, reply_markup=kb.get_markup(),
                    )
                    match send_result:
                        case Ok(sent):
                            return sent.message_id
                        case _:
                            return 0
                await callback.edit_text(
                    text, reply_markup=kb.get_markup() if kb else None,
                )
                match callback.message_id:
                    case Some(mid):
                        return mid
                    case _:
                        return 0
        elif _show_mode is ShowMode.DELETE_AND_SEND:
            async def _send_cb(text: str, kb: AnyKeyboard | None) -> int:
                if kb is not None:
                    send_result = await callback.ctx_api.send_message(
                        chat_id=chat_id, text=text, reply_markup=kb.get_markup(),
                    )
                else:
                    send_result = await callback.ctx_api.send_message(
                        chat_id=chat_id, text=text,
                    )
                match send_result:
                    case Ok(sent):
                        return sent.message_id
                    case _:
                        return 0
        else:
            async def _send_cb(text: str, kb: AnyKeyboard | None) -> int:
                if kb is not None:
                    await callback.ctx_api.send_message(
                        chat_id=chat_id, text=text, reply_markup=kb.get_markup(),
                    )
                else:
                    await callback.ctx_api.send_message(chat_id=chat_id, text=text)
                return 0
        return _send_cb

    # --- enter flow helper ---
    async def _enter_flow(
        state: object,
        ctx: Context,
        send: Callable[[str, AnyKeyboard | None], Awaitable[int]],
        scope: Scope | None = None,
    ) -> object:
        """Pre-fill cmd args, find first active field, render first widget.

        Shared by initial entry and LaunchMode.RESET.
        """
        updates: dict[str, object] = {"_initial": False}
        for caf in _cmd_arg_fields:
            value = ctx.get(caf.name)
            if value is not None:
                updates[caf.name] = Some(value)
        next_state = replace(state, **updates)
        first_idx = _find_next_active(next_state, -1, _prompted, _flow_fields)
        if first_idx is None:
            return _FlowDone(next_state)
        next_state = replace(next_state, _step=first_idx)
        first_ff = _prompted[first_idx]
        # Resolve dynamic options for first field if needed
        if first_ff.name in _options_map:
            opts = await _resolve_field_options(first_ff.name, next_state, scope)
            if opts:
                cur_dyn: dict[str, Mapping[str, str]] = {**getattr(next_state, "_dyn_opts")}
                cur_dyn[first_ff.name] = opts
                next_state = replace(next_state, _dyn_opts=cur_dyn)
            elif first_ff.is_optional:
                # Auto-skip: no options available for optional dynamic field
                next_state = replace(next_state, **{first_ff.name: Some(None)})
                return await _advance_or_done(next_state, first_idx, send, scope)
        first_widget = first_ff.exchange
        if isinstance(first_widget, FlowWidget):
            w_ctx = _widget_ctx(first_ff, _flow_name, next_state, _flow_fields, theme=_theme)
            text, kb = await first_widget.render(w_ctx)
            if _shows_progress:
                text = _progress_prefix(first_idx) + text
            sent_msg_id = await send(text, kb)
        else:
            sent_msg_id = 0
        if _show_mode in (ShowMode.EDIT, ShowMode.DELETE_AND_SEND):
            next_state = replace(next_state, _msg_id=sent_msg_id)
        return next_state

    # --- transition: from_message ---
    # State updates use dataclasses.replace() on frozen dc — always creates
    # a NEW object, so save_state's identity check (new is not old) passes.
    async def from_message(self: object, message: MessageCute, ctx: Context, scope: Scope) -> object:
        # Summary pending — reject text, wait for confirmation callback
        if _shows_summary and getattr(self, "_summary_pending", False):
            await message.answer(_theme.errors.use_buttons)
            return self

        ff = _current_field(self)
        if ff is None:
            return _FlowDone(self)

        step: int = getattr(self, "_step")

        _send = _make_send_for_message(
            message, getattr(self, "_msg_id"), message.chat.id,
        )

        # Resolve widget for current field
        widget = ff.exchange
        if not isinstance(widget, FlowWidget):
            return _FlowDone(self)

        # Initial entry (command trigger) → pre-fill command args, send first prompt
        if getattr(self, "_initial"):
            return await _enter_flow(self, ctx, _send, scope)

        # LaunchMode re-entry detection
        if not getattr(self, "_initial") and _launch_mode is not LaunchMode.STANDARD:
            match message.text:
                case Some(txt) if txt.startswith(f"/{_command}"):
                    if _launch_mode is LaunchMode.RESET:
                        return await _enter_flow(flow_cls(), ctx, _send, scope)
                    elif _launch_mode is LaunchMode.EXCLUSIVE:
                        await message.answer(f"Already in /{_command}. Send /cancel to abort.")
                        return self
                    elif _launch_mode is LaunchMode.SINGLE_TOP:
                        w_ctx = _widget_ctx(ff, _flow_name, self, _flow_fields, theme=_theme)
                        text, kb = await widget.render(w_ctx)
                        await _send(text, kb)
                        return self
                case _:
                    pass

        # Handle /skip for optional fields
        match message.text:
            case Some(txt) if txt.strip() == "/skip" and ff.is_optional:
                next_state = replace(self, **{ff.name: Some(None)})
                return await _advance_or_done(next_state, step, _send, scope)
            case _:
                pass

        # Dispatch to widget (receives full MessageCute)
        w_ctx = _widget_ctx(ff, _flow_name, self, _flow_fields, theme=_theme)
        msg_result = await widget.handle_message(message, w_ctx)

        match msg_result:
            case Advance(value=v):
                next_state = replace(self, **{ff.name: Some(v)})
                return await _advance_or_done(next_state, step, _send, scope)
            case Stay(new_value=nv):
                next_state = replace(self, **{ff.name: Some(nv)})
                new_ctx = _widget_ctx(ff, _flow_name, next_state, _flow_fields, theme=_theme)
                text, kb = await widget.render(new_ctx)
                if _shows_progress:
                    text = _progress_prefix(step) + text
                msg_id = await _send(text, kb)
                if _show_mode in (ShowMode.EDIT, ShowMode.DELETE_AND_SEND):
                    next_state = replace(next_state, _msg_id=msg_id)
                return next_state
            case Reject(message=msg):
                if widget.needs_callback:
                    prompt_text, kb = await widget.render(w_ctx)
                    if kb is not None:
                        await message.answer(
                            f"{prompt_text}\n\n{msg}",
                            reply_markup=kb.get_markup(),
                        )
                    else:
                        await message.answer(msg)
                else:
                    await message.answer(msg)
                return self
            case _:
                return self

    # --- transition: from_callback ---
    async def from_callback(self: object, callback: CallbackQueryCute, scope: Scope) -> object:
        # Summary confirmation — check before _current_field (which returns None during summary)
        if _shows_summary and getattr(self, "_summary_pending", False):
            match callback.data:
                case Some(raw_data):
                    try:
                        parsed = json.loads(raw_data)
                        if parsed.get("flow") == _flow_name and parsed.get("value") == "_summary:ok":
                            await callback.answer()
                            return _FlowDone(self)
                    except (json.JSONDecodeError, KeyError, TypeError):
                        pass
                case _:
                    pass
            return self

        ff = _current_field(self)
        if ff is None:
            return _FlowDone(self)

        step: int = getattr(self, "_step")

        match callback.data:
            case Some(raw_data):
                pass
            case _:
                return self

        try:
            parsed = json.loads(raw_data)
            cb_data = _FlowCallbackData(flow=parsed["flow"], value=parsed["value"])
        except (json.JSONDecodeError, KeyError, TypeError):
            return self

        if cb_data.flow != _flow_name:
            return self

        widget = ff.exchange
        if not isinstance(widget, FlowWidget):
            return self

        w_ctx = _widget_ctx(ff, _flow_name, self, _flow_fields, theme=_theme)
        cb_result = await widget.handle_callback(cb_data.value, w_ctx)

        match cb_result:
            case NoOp():
                await callback.answer()
                return self

            case Stay(new_value=nv):
                await callback.answer()
                next_state = replace(self, **{ff.name: Some(nv)})
                new_ctx = replace(w_ctx, current_value=Some(nv))
                text, kb = await widget.render(new_ctx)
                if _shows_progress:
                    text = _progress_prefix(step) + text
                if kb is not None:
                    if not isinstance(kb.get_markup(), InlineKeyboardMarkup):
                        # Reply keyboard can't be used with edit — fall back to send
                        warnings.warn(
                            "ShowMode.EDIT: widget returned a reply keyboard "
                            "which is incompatible with edit_text. "
                            "Falling back to send_message.",
                            stacklevel=2,
                        )
                        chat_id = callback.from_user.id
                        await callback.ctx_api.send_message(
                            chat_id=chat_id, text=text, reply_markup=kb.get_markup(),
                        )
                    else:
                        await callback.edit_text(text, reply_markup=kb.get_markup())
                return next_state

            case Advance(value=v, summary=s):
                await callback.answer()
                next_state = replace(self, **{ff.name: Some(v)})
                selection_text = f"{widget.prompt}\n\n{s}"

                chat_id = callback.from_user.id
                _send_cb = _make_send_for_callback(callback, chat_id)

                if _show_mode is ShowMode.EDIT:
                    result = await _advance_or_done(next_state, step, _send_cb, scope)
                    if isinstance(result, _FlowDone):
                        await callback.edit_text(selection_text)
                    return result

                else:
                    await callback.edit_text(selection_text)
                    return await _advance_or_done(next_state, step, _send_cb, scope)

            case Reject(message=msg):
                await callback.answer(msg)
                return self

        return self

    # --- to_domain ---
    def to_domain(self: object) -> object:
        """Construct Op from accumulated state."""
        kw: dict[str, str | int | float | bool | None] = {}
        for ff in _flow_fields:
            val: Option[str | int | float | bool | None] = getattr(self, ff.name)
            match val:
                case Some(v):
                    kw[ff.name] = v
                case _:
                    kw[ff.name] = None
        return _op_type(**kw)

    # Build flow dataclass using make_dataclass directly.
    # Field type is `object` — Option[T] is a TypeAliasType that make_dataclass
    # cannot handle as annotation; `object` is the honest fallback.
    flow_dc_fields_spec: list[tuple[str, type, int | bool | Nothing]] = [
        (ff.name, object, field(default_factory=Nothing)) for ff in flow_fields
    ]
    flow_dc_fields_spec.append(("_step", int, 0))
    flow_dc_fields_spec.append(("_initial", bool, True))
    flow_dc_fields_spec.append(("_msg_id", int, 0))
    flow_dc_fields_spec.append(("_dyn_opts", object, field(default_factory=dict)))
    if _shows_summary:
        flow_dc_fields_spec.append(("_summary_pending", bool, False))

    ns: dict[str, Callable[..., object]] = {
        "to_domain": to_domain,
        "from_message": transition(from_message),
    }
    if has_callback:
        ns["from_callback"] = transition(from_callback)

    flow_name_str = f"_{entity.__name__}Flow"
    flow_cls = make_dataclass(
        flow_name_str,
        flow_dc_fields_spec,
        frozen=True,
        namespace=ns,
    )
    flow_cls.__name__ = flow_name_str
    flow_cls.__qualname__ = flow_name_str

    return flow_cls


# ═══════════════════════════════════════════════════════════════════════════════
# Flow response type
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class _FlowResponse:
    """Response wrapper for flow completion.

    __str__ is required: the telegrinder compiler's _format_tg_response
    only converts to string when ``type.__str__ is not object.__str__``.
    Without it the response object is passed as-is and silently dropped.
    """

    text: str = ""
    next_command: str | None = None
    is_sub_flow: bool = False
    reply_markup: InlineKeyboardMarkup | ReplyKeyboardMarkup | None = None

    def __str__(self) -> str:
        return self.text

    @classmethod
    def from_domain(cls, result: Result[FinishResult, DomainError]) -> _FlowResponse:
        match result:
            case Ok(finish_result):
                return cls(
                    text=finish_result.text,
                    next_command=finish_result.next_command,
                    is_sub_flow=finish_result.is_sub_flow,
                    reply_markup=finish_result.reply_markup,
                )
            case Error(err):
                return cls(text=f"Error: {err}")


# ═══════════════════════════════════════════════════════════════════════════════
# _FlowFinishEnricher — send flow finish with optional reply_markup
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class _FlowFinishEnricher(ScopeEnricher):
    """Send flow finish response with optional reply_markup.

    Replaces ReplyMessage on callback exposure. Also added to message exposure
    to handle keyboard case.

    Behavior:
    - Callback + keyboard → send message with keyboard, return None
    - Callback + no keyboard → send plain message, return None
    - Message + keyboard → send message with keyboard, return None
    - Message + no keyboard → pass through (return response), normal str flow
    """

    async def enrich[R](self, call: EnricherNext[R], scope: Scope) -> R:
        from kungfu import Some
        from telegrinder.api import API as _API
        from telegrinder.types.objects import Update as _Update

        response = await call(scope)
        if response is None:
            return None  # type: ignore[return-value]

        has_keyboard = (
            isinstance(response, _FlowResponse)
            and response.reply_markup is not None
        )

        api_wrapper = scope.get(_API)
        update_wrapper = scope.get(_Update)
        if api_wrapper is None or update_wrapper is None:
            return response

        api: _API = api_wrapper.value
        update: _Update = update_wrapper.value

        # Determine if callback context
        is_callback = isinstance(update.callback_query, Some)

        if not has_keyboard and not is_callback:
            return response  # message view, no keyboard → normal str flow

        text = str(response)
        if not text:
            return None  # type: ignore[return-value]

        # Extract chat_id
        chat_id: int | None = None
        match update.callback_query:
            case Some(cq):
                match cq.message:
                    case Some(msg):
                        chat_id = msg.v.chat.id
                    case _:
                        pass
            case _:
                pass
        if chat_id is None:
            match update.message:
                case Some(msg):
                    chat_id = msg.chat.id
                case _:
                    pass
        if chat_id is None:
            return response

        # Send with or without keyboard
        if has_keyboard:
            await api.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=response.reply_markup,  # type: ignore[union-attr]
            )
        else:
            await api.send_message(chat_id=chat_id, text=text)

        return None  # type: ignore[return-value]


# ═══════════════════════════════════════════════════════════════════════════════
# FlowSurfaceStep — THE surface derivation step
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class FlowSurfaceStep:
    """Generate StatefulCodec from entity fields and expose on telegrinder.

    This is the workhorse step for tg_flow. It:
    1. Classifies entity fields by exchange annotation
    2. Generates a flow class with transitions
    3. Creates Op type + handler calling entity.finish()
    4. Builds StatefulCodec
    5. Creates exposures on message + callback_query views
    """

    command: str
    key_node: type
    capabilities: tuple[SurfaceCapability, ...]
    supports_cancel: bool = False
    supports_back: bool = False
    description: str | None = None
    order: int = 100
    stack: FlowStackStorage | None = None
    show_mode: ShowMode = ShowMode.SEND
    launch_mode: LaunchMode = LaunchMode.STANDARD
    shows_progress: bool = False
    shows_summary: bool = False
    theme: UITheme = field(default_factory=UITheme)
    agent_cls: type[Agent] | None = None

    def derive_surface[EntityT](self, ctx: SurfaceCtx[EntityT]) -> SurfaceCtx[EntityT]:
        entity = ctx.schema.entity
        flow_fields = _classify_fields(entity)
        options_providers = _discover_options(entity)

        if not flow_fields:
            raise ValueError(
                f"{entity.__name__} has no fields with exchange annotations "
                f"(TextInput, Inline, Confirm, Prefilled, Counter, Multiselect)"
            )

        if not hasattr(entity, "finish"):
            raise ValueError(
                f"{entity.__name__} must define a finish() method"
            )

        # Generate collision-resistant flow name for callback routing
        flow_name = _flow_name_hash(entity)

        # Create Op type from all flow fields
        op_fields: list[FieldSpec] = []
        for ff in flow_fields:
            if ff.is_optional:
                op_fields.append((ff.name, ff.base_type | None))
            else:
                op_fields.append((ff.name, ff.base_type))

        op_type = create_dataclass(
            f"{entity.__name__}FlowOp",
            op_fields,
            frozen=True,
        )

        # Generate flow class
        flow_cls = _generate_flow_class(
            entity, flow_fields, op_type, flow_name,
            show_mode=self.show_mode,
            launch_mode=self.launch_mode,
            command=self.command,
            options_providers=options_providers,
            shows_progress=self.shows_progress,
            shows_summary=self.shows_summary,
            theme=self.theme,
            agent_cls=self.agent_cls,
        )

        # Build handler that calls entity.finish()
        _entity = entity

        # Extract compose.Node deps from finish() so the ops runner resolves them
        compose_deps = _extract_finish_compose_deps(entity)
        _compose_dep_names = [name for name, _ in compose_deps]

        async def _base_handler(**kwargs: object) -> Result[FinishResult, DomainError]:
            op = kwargs["op"]
            # Reconstruct entity from op fields
            kw: dict[str, str | int | float | bool | None] = {}
            for ff in flow_fields:
                kw[ff.name] = getattr(op, ff.name)
            instance = _entity(**kw)
            # getattr avoids reportAttributeAccessIssue on runtime-defined finish()
            finish_fn = getattr(instance, "finish")
            finish_kwargs = {name: kwargs[name] for name in _compose_dep_names}
            return await finish_fn(**finish_kwargs)

        # Wrap handler with stack management if stacking is enabled
        _stack = self.stack
        _self_command = self.command

        if _stack is not None:
            _key_node_type = self.key_node

            async def handler(**kwargs: object) -> Result[FinishResult, DomainError]:
                result = await _base_handler(**kwargs)
                stack_key = str(kwargs["_flow_stack_key"])
                match result:
                    case Ok(finish):
                        if finish.is_sub_flow and finish.next_command is not None:
                            _stack.push(stack_key, StackFrame(command=_self_command))
                            return Ok(FinishResult.message(
                                f"{finish.text}\n\nSend /{finish.next_command} to continue."
                            ))
                        parent = _stack.pop(stack_key)
                        if parent is not None:
                            return Ok(FinishResult.message(
                                f"{finish.text}\n\nSend /{parent.command} to go back."
                            ))
                return result
        else:
            handler = _base_handler

        # Set annotations + signature for nodnod resolution in ops runner.
        # _create_node_for_handler reads both inspect.signature and get_type_hints.
        _handler_annotations: dict[str, type] = {
            "op": op_type,
            **{name: node_type for name, node_type in compose_deps},
        }
        _handler_params = [
            inspect.Parameter("op", inspect.Parameter.POSITIONAL_OR_KEYWORD),
            *[
                inspect.Parameter(name, inspect.Parameter.POSITIONAL_OR_KEYWORD)
                for name, _ in compose_deps
            ],
        ]
        if _stack is not None:
            _handler_annotations["_flow_stack_key"] = self.key_node
            _handler_params.append(
                inspect.Parameter("_flow_stack_key", inspect.Parameter.POSITIONAL_OR_KEYWORD),
            )
        handler.__annotations__ = _handler_annotations
        handler.__signature__ = inspect.Signature(parameters=_handler_params)  # type: ignore[attr-defined]

        # Build StatefulCodec
        from nodnod.agent.event_loop.agent import EventLoopAgent

        _flow_agent_cls = self.agent_cls or EventLoopAgent
        codec = StatefulCodec(
            flow=flow_cls,
            response=_FlowResponse,
            store=MemoryStorage[str, Done](),
            key_node=self.key_node,
            agent_cls=_flow_agent_cls,
        )

        # Exposure on dp.message (command trigger + active state)
        # Enhance Command with Arguments from tg.CommandArg fields
        cmd_arg_fields = [f for f in flow_fields if f.command_arg is not None]
        if cmd_arg_fields:
            from telegrinder.bot.rules.command import Argument
            args: list[Argument] = []
            has_greedy = False
            for caf in cmd_arg_fields:
                validators: list[type] = []
                if caf.base_type is int:
                    validators.append(int)
                args.append(Argument(
                    name=caf.name,
                    validators=validators,
                    optional=caf.command_arg.optional if caf.command_arg else False,
                ))
                if caf.command_arg and caf.command_arg.greedy:
                    has_greedy = True
            message_trigger = TelegrindTrigger(
                Command(self.command, *args, lazy=has_greedy), view="message",
            )
        else:
            message_trigger = TelegrindTrigger(Command(self.command), view="message")
        message_caps: tuple[SurfaceCapability, ...] = (*self.capabilities, _FlowFinishEnricher())
        if self.description is not None:
            from emergent.wire.axis.surface.dialects.telegram import HelpMeta
            message_caps = (*message_caps, HelpMeta(description=self.description, order=self.order))
        message_exposure = Exposure(
            trigger=message_trigger,
            codec=codec,
            capabilities=tuple(message_caps),
        )

        # Handler already has annotations + signature set above for nodnod
        ctx = ctx.add_operation((op_type, handler, message_exposure))

        # If flow has callback-based fields, also register on callback_query
        has_callback = self.shows_summary or any(
            isinstance(ff.exchange, FlowWidget) and ff.exchange.needs_callback
            for ff in flow_fields
            if not isinstance(ff.exchange, Prefilled)
        )

        if has_callback:
            from emergent.wire.compile.targets.telegrinder import HasActiveFlowState

            # Include HasActiveFlowState so the callback handler only matches
            # when THIS flow has an active state. Without it, multiple flows
            # sharing PayloadModelRule(_FlowCallbackData) collide — the first
            # registered handler eats the callback even on flow-name mismatch.
            cb_trigger = TelegrindTrigger(
                PayloadModelRule(_FlowCallbackData),
                HasActiveFlowState(codec.store, self.key_node, _flow_agent_cls),
                view="callback_query",
            )
            cb_exposure = Exposure(
                trigger=cb_trigger,
                codec=codec,
                capabilities=(*self.capabilities, _FlowFinishEnricher()),
            )

            # Same handler + codec, different view registration
            ctx = ctx.add_operation((op_type, handler, cb_exposure))

        # ── Cancel / Back — separate DelegateCodec exposures ──
        # These are NOT transitions. They are independent handlers that
        # directly manipulate the store, using Command rules + HasActiveFlowState.

        if self.supports_cancel or self.supports_back:
            from emergent.wire.compile.targets.telegrinder import (
                HasActiveFlowState,
                compose_store_key,
            )
            from emergent.wire.axis.surface.codecs.delegate import delegate

            prompted_fields = [
                f for f in flow_fields if not isinstance(f.exchange, Prefilled)
            ]
            _store = codec.store
            _key_node = self.key_node
            _agent_cls = _flow_agent_cls

        _flow_theme = self.theme

        if self.supports_cancel:
            async def _cancel_handler(message: MessageCute, ctx: Context) -> None:
                store_key = await compose_store_key(_key_node, _agent_cls, ctx)
                await _store.delete(store_key)
                await message.answer(_flow_theme.action.cancel)

            cancel_trigger = TelegrindTrigger(
                Command("cancel"),
                HasActiveFlowState(_store, _key_node, _agent_cls),
                view="message",
            )
            cancel_exposure = Exposure(
                trigger=cancel_trigger,
                codec=delegate(_cancel_handler),
                capabilities=(),
            )
            cancel_op, cancel_noop = create_sentinel_operation(
                f"{entity.__name__}CancelOp",
            )
            ctx = ctx.add_operation(
                (cancel_op, cancel_noop, cancel_exposure)
            )

        if self.supports_back:
            _back_prompted = prompted_fields
            _back_all_fields = flow_fields
            _back_flow_name = flow_name

            async def _render_and_send(
                ff: FlowField, state: object, message: MessageCute,
            ) -> None:
                widget = ff.exchange
                if isinstance(widget, FlowWidget):
                    w_ctx = _widget_ctx(ff, _back_flow_name, state, _back_all_fields, theme=_flow_theme)
                    prompt, kb = await widget.render(w_ctx)
                else:
                    prompt, kb = "", None
                if kb is not None:
                    await message.answer(prompt, reply_markup=kb.get_markup())
                else:
                    await message.answer(prompt)

            async def _back_handler(message: MessageCute, ctx: Context) -> None:
                store_key = await compose_store_key(_key_node, _agent_cls, ctx)
                state_result = await _store.get(store_key)
                match state_result:
                    case Ok(Some(state)):
                        step: int = getattr(state, "_step")
                        prev_idx = _find_prev_active(
                            state, step, _back_prompted, _back_all_fields,
                        )
                        if prev_idx is not None:
                            prev_ff = _back_prompted[prev_idx]
                            new_state = replace(
                                state,
                                **{prev_ff.name: Nothing(), "_step": prev_idx},
                            )
                            await _store.set(store_key, new_state)
                            await _render_and_send(prev_ff, new_state, message)
                        else:
                            current_ff = _back_prompted[step]
                            await _render_and_send(current_ff, state, message)
                    case _:
                        pass

            back_trigger = TelegrindTrigger(
                Command("back"),
                HasActiveFlowState(_store, _key_node, _agent_cls),
                view="message",
            )
            back_exposure = Exposure(
                trigger=back_trigger,
                codec=delegate(_back_handler),
                capabilities=(),
            )
            back_op, back_noop = create_sentinel_operation(
                f"{entity.__name__}BackOp",
            )
            ctx = ctx.add_operation(
                (back_op, back_noop, back_exposure)
            )

        return ctx


# ═══════════════════════════════════════════════════════════════════════════════
# TGFlowPattern — the Pattern
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class TGFlowPattern:
    """Pattern: annotated dataclass → StatefulCodec flow.

    Implements the Pattern protocol (has .compile(entity) -> Derivation).

        @derive(tg_flow(command="start", key_node=ChatIdNode))
        @dataclass
        class Registration:
            name: Annotated[str, TextInput("What's your name?")]
            ...
    """

    command: str
    key_node: type
    capabilities: tuple[SurfaceCapability, ...] = ()
    description: str | None = None
    order: int = 100
    show_mode: ShowMode = ShowMode.SEND
    launch_mode: LaunchMode = LaunchMode.STANDARD
    theme: UITheme = field(default_factory=UITheme)
    agent_cls: type[Agent] | None = None

    def chain(self, *transforms: DerivationT) -> ChainedPattern:
        """Chain DerivationT transforms after compile."""
        from derivelib._dialect import ChainedPattern as _ChainedPattern
        return _ChainedPattern(self, transforms)

    def compile(self, entity: type) -> Derivation:
        from derivelib._derivation import Step

        steps: list[Step] = [
            inspect_entity(),
            FlowSurfaceStep(
                command=self.command,
                key_node=self.key_node,
                capabilities=self.capabilities,
                description=self.description,
                order=self.order,
                show_mode=self.show_mode,
                launch_mode=self.launch_mode,
                theme=self.theme,
                agent_cls=self.agent_cls,
            ),
        ]
        return tuple(steps)


def tg_flow(
    command: str,
    key_node: type,
    *caps: SurfaceCapability,
    description: str | None = None,
    order: int = 100,
    show_mode: ShowMode = ShowMode.SEND,
    launch_mode: LaunchMode = LaunchMode.STANDARD,
    theme: UITheme | None = None,
    agent_cls: type[Agent] | None = None,
) -> TGFlowPattern:
    """Create TG flow pattern.

    Args:
        command: Telegram command name (e.g., "start" → /start).
        key_node: nodnod node type for session routing (e.g., ChatIdNode).
        *caps: Surface capabilities.
        description: Help description for /help generation.
        order: Sort order for /help generation.
        show_mode: How prompts are rendered (SEND or EDIT).
        launch_mode: What happens on re-entry to running flow.

    Returns:
        TGFlowPattern — use with @derive().

    Example::

        @derive(tg_flow(command="register", key_node=ChatIdNode, description="Register"))
        @dataclass
        class Registration:
            name: Annotated[str, TextInput("What's your name?")]
            role: Annotated[str, Inline("Role?", admin="Admin", user="User")]

            async def finish(self, db: ...) -> Result[FinishResult, DomainError]:
                ...
    """
    return TGFlowPattern(
        command=command,
        key_node=key_node,
        capabilities=caps,
        description=description,
        order=order,
        show_mode=show_mode,
        launch_mode=launch_mode,
        theme=theme if theme is not None else DEFAULT_THEME,
        agent_cls=agent_cls,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Transforms — with_cancel, with_back, with_stacking
# ═══════════════════════════════════════════════════════════════════════════════


def _flow_step_transform(**updates: object) -> DerivationT:
    """Create a DerivationT that replaces attrs on FlowSurfaceStep instances."""

    def transform(steps: Derivation) -> Derivation:
        return tuple(
            replace(s, **updates) if isinstance(s, FlowSurfaceStep) else s
            for s in steps
        )

    return transform


def with_cancel() -> DerivationT:
    """Add /cancel support to flow.

    When user sends /cancel during a flow, the state is deleted
    and a cancellation message is sent. No Op is executed.

    Uses the Cancelled wire marker — execute_stateful_unified
    skips Op execution and deletes state on Cancelled.
    """
    return _flow_step_transform(supports_cancel=True)


def with_back() -> DerivationT:
    """Add /back support to flow (go to previous step).

    When user sends /back during a flow, the previous field is
    cleared and its prompt is re-sent.
    """
    return _flow_step_transform(supports_back=True)


def with_stacking(stack: FlowStackStorage | None = None) -> DerivationT:
    """Add sub-flow stacking to flow.

    When a flow finishes with ``FinishResult.sub_flow()``, the current
    command is pushed onto the stack. When the sub-flow completes
    normally, the stack is popped and the user is directed back.

    The stack key is derived from the flow's key_node (resolved by nodnod),
    so it works with any node type — no hardcoded user/chat IDs.

    Args:
        stack: Custom storage backend (must implement FlowStackStorage).
               Defaults to in-memory FlowStack.

    Example::

        shared_stack = FlowStack()

        @derive(tg_flow(...).chain(with_stacking(shared_stack)))
        @dataclass
        class CreateProject:
            ...
            async def finish(self, ...) -> Result[FinishResult, DomainError]:
                return Ok(FinishResult.sub_flow("Project created!", command="invite"))
    """
    actual_stack: FlowStackStorage = stack if stack is not None else FlowStack()
    return _flow_step_transform(stack=actual_stack)


def with_show_mode(mode: ShowMode) -> DerivationT:
    """Set the ShowMode for flow prompts.

    SEND (default): always send new message for each prompt.
    EDIT: edit previous message in place (clean chat).
    """
    return _flow_step_transform(show_mode=mode)


def with_launch_mode(mode: LaunchMode) -> DerivationT:
    """Set the LaunchMode for flow re-entry behavior.

    STANDARD (default): command text treated as field input.
    RESET: reset flow, start fresh.
    EXCLUSIVE: block with 'already in progress' message.
    SINGLE_TOP: re-send current prompt.
    """
    return _flow_step_transform(launch_mode=mode)


def with_progress() -> DerivationT:
    """Add step progress indicator to flow prompts.

    Each prompt is prefixed with a visual progress bar showing
    current step position relative to total prompted fields::

        \u2588\u2588\u2588\u2591\u2591\u2591\u2591\u2591\u2591\u2591 3/10

        What's your name?

    Skipped (When-false) fields are still counted in the total —
    the bar shows position within the full flow, not just active fields.

    Example::

        @derive(tg_flow(...).chain(with_progress()))
        @dataclass
        class LongForm:
            ...
    """
    return _flow_step_transform(shows_progress=True)


def with_summary() -> DerivationT:
    """Add auto-summary confirmation step before flow finish.

    After all fields are collected, a summary of all field values
    is shown with a confirmation button. The flow only completes
    when the user confirms.

    Summary renders each field as ``Label: value`` using the field
    name title-cased. Fields with None values are omitted.

    Example::

        @derive(tg_flow(...).chain(with_summary()))
        @dataclass
        class Order:
            item: Annotated[str, TextInput("What item?")]
            qty: Annotated[int, Counter("How many?")]

            async def finish(self, ...) -> Result[FinishResult, DomainError]:
                ...
    """
    return _flow_step_transform(shows_summary=True)


# ═══════════════════════════════════════════════════════════════════════════════
# Exports
# ═══════════════════════════════════════════════════════════════════════════════


__all__ = (
    # Pattern
    "tg_flow",
    "TGFlowPattern",
    # Exchange annotations (re-exported from widget.py)
    "TextInput",
    "Inline",
    "Confirm",
    "Prefilled",
    "Counter",
    "Multiselect",
    "Toggle",
    "PhotoInput",
    "DocumentInput",
    "LocationInput",
    "VideoInput",
    "VoiceInput",
    "ContactInput",
    "Radio",
    "DatePicker",
    "ScrollingInline",
    "EnumInline",
    "Rating",
    "TimePicker",
    "NumberInput",
    "ListBuilder",
    "Slider",
    "PinInput",
    "MediaGroupInput",
    "TimeSlotPicker",
    "RecurrencePicker",
    "SummaryReview",
    "DynamicInline",
    "DynamicRadio",
    "DynamicMultiselect",
    "options",
    "Case",
    # Widget protocol + result types (re-exported from widget.py)
    "FlowWidget",
    "AnyKeyboard",
    "WidgetContext",
    "Stay",
    "Advance",
    "Reject",
    "NoOp",
    # Mode enums
    "ShowMode",
    "LaunchMode",
    # Validation annotations (re-exported from widget.py)
    "MinLen",
    "MaxLen",
    "Pattern",
    # Conditional
    "When",
    # Flow stack
    "FlowStackStorage",
    "FlowStack",
    "StackFrame",
    # Result
    "FinishResult",
    # Step
    "FlowSurfaceStep",
    # Transforms
    "with_cancel",
    "with_back",
    "with_stacking",
    "with_show_mode",
    "with_launch_mode",
    "with_progress",
    "with_summary",
)

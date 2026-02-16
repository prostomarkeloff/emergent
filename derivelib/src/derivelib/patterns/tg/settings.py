"""tg_settings pattern — settings overview with inline field editing via flow widgets.

Shows current values, tap a field to edit with the appropriate widget,
save on confirm. Reuses browse and flow/widget infrastructure.

    from derivelib.patterns.tg.settings import tg_settings, on_save, format_settings

    @derive(tg_settings(command="settings", key_node=UserId))
    @dataclass
    class PlayerSettings:
        codename: Annotated[str, TextInput("Enter codename:")]
        notifications: Annotated[bool, Confirm("Enable notifications?")]
        preferred_bet: Annotated[int, Counter("Default bet:", min=10, max=1000, step=10)]

        @classmethod
        @query
        async def load(cls, uid: ...) -> PlayerSettings: ...

        @classmethod
        @on_save
        async def save(cls, settings: PlayerSettings, uid: ...) -> None: ...

The pattern generates:
1. Command handler — run @query, render overview, field buttons
2. Callback handler — field edit entry, widget interactions, save
3. Message handler (if any field has needs_callback=False) — text input for editing
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import (
    TYPE_CHECKING,
)

if TYPE_CHECKING:
    from derivelib._dialect import ChainedPattern
    from nodnod.agent.base import Agent

from kungfu import Some
from nodnod import Scope

from emergent.graph._compose import Composer

from telegrinder.bot.cute_types.callback_query import CallbackQueryCute
from telegrinder.bot.cute_types.message import MessageCute
from telegrinder.bot.dispatch.context import Context
from telegrinder.bot.rules.abc import ABCRule
from telegrinder.bot.rules.command import Command
from telegrinder.bot.rules.payload import PayloadModelRule
from telegrinder.tools.keyboard import InlineButton, InlineKeyboard

from emergent.wire.axis.surface.capabilities._base import SurfaceCapability
from emergent.wire.axis.surface.dialects.telegram import AnswerCallback
from emergent.wire.axis.surface.triggers.telegrinder import TelegrindTrigger

from derivelib._ctx import SurfaceCtx
from derivelib._derivation import Derivation, DerivationT
from derivelib.axes.schema import inspect_entity

# ═══════════════════════════════════════════════════════════════════════════════
# Reuse from browse.py
# ═══════════════════════════════════════════════════════════════════════════════

from derivelib.patterns.tg.browse import (
    query,
    _resolve_method_di,
    _find_query_method,
    _default_render_card,
    _iter_entity_methods,
)
from derivelib.patterns.tg._shared import (
    add_delegate_exposure,
    msg_user_key,
)

# ═══════════════════════════════════════════════════════════════════════════════
# Reuse from flow.py
# ═══════════════════════════════════════════════════════════════════════════════

from derivelib.patterns.tg.flow import (
    _classify_fields,
    FlowField,
    _FlowCallbackData,
    _flow_name_hash,
    Prefilled,
)

# ═══════════════════════════════════════════════════════════════════════════════
# Reuse from widget.py
# ═══════════════════════════════════════════════════════════════════════════════

from derivelib.patterns.tg.uilib.theme import DEFAULT_THEME, UITheme
from derivelib.patterns.tg.widget import (
    FlowWidget,
    WidgetContext,
    Advance,
    Stay,
    Reject,
    NoOp,
)

F = Callable[..., object]

# ═══════════════════════════════════════════════════════════════════════════════
# Decorators — @on_save, @format_settings
# ═══════════════════════════════════════════════════════════════════════════════

ON_SAVE_ATTR = "__settings_on_save__"
FORMAT_SETTINGS_ATTR = "__settings_format__"


def on_save(fn: F) -> F:
    """Mark classmethod as settings persistence handler.

    Called after a field is edited and confirmed via widget.
    Receives the updated entity + compose params.

        @classmethod
        @on_save
        async def save(cls, settings: PlayerSettings, uid: ...) -> None: ...
    """
    setattr(fn, ON_SAVE_ATTR, True)
    return fn


def format_settings(fn: F) -> F:
    """Mark classmethod as custom settings overview renderer.

    Receives the settings entity, returns formatted text.

        @classmethod
        @format_settings
        def render(cls, s: PlayerSettings) -> str:
            return f"Codename: {s.codename}\\nBet: {s.preferred_bet}"
    """
    setattr(fn, FORMAT_SETTINGS_ATTR, True)
    return fn


def _find_on_save(entity: type) -> str | None:
    """Find the @on_save-decorated method name."""
    for name, fn in _iter_entity_methods(entity):
        if getattr(fn, ON_SAVE_ATTR, False):
            return name
    return None


def _find_format_settings(entity: type) -> str | None:
    """Find the @format_settings-decorated method name."""
    for name, fn in _iter_entity_methods(entity):
        if getattr(fn, FORMAT_SETTINGS_ATTR, False):
            return name
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# Callback routing rule
# ═══════════════════════════════════════════════════════════════════════════════


class _SettingsNameCheck(ABCRule):
    """Check that _FlowCallbackData.flow matches our settings name.

    Used as ``PayloadModelRule(_FlowCallbackData) & _SettingsNameCheck(name)``
    so each settings entity only matches its own callbacks.
    """

    def __init__(self, settings_name: str) -> None:
        self._settings_name = settings_name

    def check(self, context: Context) -> bool:
        model = context.get("model")
        if not isinstance(model, _FlowCallbackData):
            return False
        return model.flow == self._settings_name


# ═══════════════════════════════════════════════════════════════════════════════
# Session state
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class SettingsSession:
    """In-memory state for an active settings session."""

    editing_field: str = ""  # "" = overview, "fieldname" = editing


# ═══════════════════════════════════════════════════════════════════════════════
# SettingsSurfaceStep — THE surface derivation step
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class SettingsSurfaceStep:
    """Generate DelegateCodec handlers for settings command + callbacks + messages.

    Creates up to 3 exposures:
    1. Command handler (dp.message) — run @query, render overview, field buttons
    2. Callback handler (dp.callback_query) — field entry, widget cb, save
    3. Message handler (dp.message) — text input when editing (only if needed)
    """

    command: str
    key_node: type
    capabilities: tuple[SurfaceCapability, ...]
    description: str | None = None
    order: int = 100
    theme: UITheme = field(default_factory=UITheme)
    agent_cls: type[Agent] | None = None

    def derive_surface[EntityT](self, ctx: SurfaceCtx[EntityT]) -> SurfaceCtx[EntityT]:
        entity = ctx.schema.entity
        query_method_name = _find_query_method(entity)
        on_save_name = _find_on_save(entity)
        format_name = _find_format_settings(entity)

        if query_method_name is None:
            raise ValueError(
                f"{entity.__name__} must have a @query-decorated method"
            )

        # Classify fields to find which have widgets
        flow_fields = _classify_fields(entity)
        prompted_fields = [f for f in flow_fields if not isinstance(f.exchange, Prefilled)]

        if not prompted_fields:
            raise ValueError(
                f"{entity.__name__} has no editable fields with widget annotations"
            )

        # Generate settings name for callback routing
        settings_name = _flow_name_hash(entity)

        # Closures
        _entity = entity
        _query_name = query_method_name
        _on_save_name = on_save_name
        _format_name = format_name
        _prompted = prompted_fields
        _settings_name = settings_name
        _theme = self.theme
        _agent_cls = self.agent_cls

        # Check if any field needs message handling (needs_callback=False)
        _has_message_fields = any(
            isinstance(f.exchange, FlowWidget) and not f.exchange.needs_callback
            for f in _prompted
        )

        # Session store: user_key → SettingsSession
        _sessions: dict[str, SettingsSession] = {}

        async def _run_query(scope: Scope) -> EntityT:
            """Run @query to load current settings."""
            method = getattr(_entity, _query_name)
            composer = Composer.create(scope, _agent_cls)
            resolved = await _resolve_method_di(method, composer)
            return await method(**resolved)

        async def _run_save(updated: object, scope: Scope) -> None:
            """Run @on_save with the updated entity."""
            if _on_save_name is None:
                return
            method = getattr(_entity, _on_save_name)
            composer = Composer.create(scope, _agent_cls)
            resolved = await _resolve_method_di(
                method, composer, entity_in_scope=(type(updated), updated),
            )
            await method(**resolved)

        def _render_overview(settings_obj: object) -> str:
            """Render settings overview text."""
            if _format_name is not None:
                formatter = getattr(_entity, _format_name)
                return formatter(settings_obj)
            return _default_render_card(settings_obj)

        def _build_overview_keyboard(settings_obj: object) -> InlineKeyboard:
            """Build keyboard with one button per editable field."""
            kb = InlineKeyboard()
            for ff in _prompted:
                current = getattr(settings_obj, ff.name, None)
                display = _format_field_value(current)
                label = ff.name.replace("_", " ").title()
                kb.add(InlineButton(
                    text=f"{label}: {display}",
                    callback_data=json.dumps({
                        "flow": _settings_name,
                        "value": f"field:{ff.name}",
                    }),
                ))
                kb.row()
            return kb

        def _format_field_value(value: object) -> str:
            """Format a field value for display."""
            if value is None:
                return _theme.display.none_value
            if isinstance(value, bool):
                return _theme.display.bool_true if value else _theme.display.bool_false
            return str(value)

        def _find_field(name: str) -> FlowField | None:
            """Find a prompted field by name."""
            for ff in _prompted:
                if ff.name == name:
                    return ff
            return None

        def _widget_ctx(ff: FlowField, current_value: object) -> WidgetContext:
            """Build WidgetContext for a field."""
            from kungfu import Some as _Some, Nothing
            cv = _Some(current_value) if current_value is not None else Nothing()
            return WidgetContext(
                flow_name=_settings_name,
                field_name=ff.name,
                current_value=cv,
                base_type=ff.base_type,
                validators=ff.validators,
                is_optional=ff.is_optional,
                theme=_theme,
            )

        # --- Command handler ---
        async def command_handler(message: MessageCute, scope: Scope) -> None:
            key = msg_user_key(message)
            _sessions[key] = SettingsSession()

            settings_obj = await _run_query(scope)
            text = _render_overview(settings_obj)
            kb = _build_overview_keyboard(settings_obj)
            await message.answer(text, reply_markup=kb.get_markup())

        # --- Callback handler ---
        async def callback_handler(cb: CallbackQueryCute, scope: Scope) -> None:
            match cb.data:
                case Some(raw_data):
                    pass
                case _:
                    return

            try:
                parsed = json.loads(raw_data)
                cb_data = _FlowCallbackData(flow=parsed["flow"], value=parsed["value"])
            except (json.JSONDecodeError, KeyError, TypeError):
                return

            if cb_data.flow != _settings_name:
                return

            key = str(cb.from_user.id)
            session = _sessions.get(key, SettingsSession())

            # Overview mode — handle field selection and back
            if session.editing_field == "":
                if cb_data.value.startswith("field:"):
                    field_name = cb_data.value[6:]
                    ff = _find_field(field_name)
                    if ff is None:
                        return

                    session.editing_field = field_name
                    _sessions[key] = session

                    # Render widget with current value
                    settings_obj = await _run_query(scope)
                    current = getattr(settings_obj, field_name, None)
                    widget = ff.exchange
                    if isinstance(widget, FlowWidget):
                        w_ctx = _widget_ctx(ff, current)
                        text, kb = await widget.render(w_ctx)
                        # Add back button
                        if kb is None:
                            kb = InlineKeyboard()
                        kb.add(InlineButton(
                            text=_theme.nav.back,
                            callback_data=json.dumps({
                                "flow": _settings_name,
                                "value": "back",
                            }),
                        ))
                        await cb.edit_text(text, reply_markup=kb.get_markup())
                    await cb.answer()

                elif cb_data.value == "back":
                    await cb.answer()

                return

            # Editing mode — handle widget interactions
            ff = _find_field(session.editing_field)
            if ff is None:
                session.editing_field = ""
                _sessions[key] = session
                return

            # Handle "back" button
            if cb_data.value == "back":
                session.editing_field = ""
                _sessions[key] = session

                settings_obj = await _run_query(scope)
                text = _render_overview(settings_obj)
                kb = _build_overview_keyboard(settings_obj)
                await cb.edit_text(text, reply_markup=kb.get_markup())
                await cb.answer()
                return

            widget = ff.exchange
            if not isinstance(widget, FlowWidget):
                return

            settings_obj = await _run_query(scope)
            current = getattr(settings_obj, session.editing_field, None)
            w_ctx = _widget_ctx(ff, current)

            cb_result = await widget.handle_callback(cb_data.value, w_ctx)

            match cb_result:
                case Advance(value=v):
                    # Save the updated setting
                    updated = dataclasses.replace(settings_obj, **{session.editing_field: v})
                    await _run_save(updated, scope)

                    session.editing_field = ""
                    _sessions[key] = session

                    # Re-render overview
                    fresh = await _run_query(scope)
                    text = _render_overview(fresh)
                    kb = _build_overview_keyboard(fresh)
                    await cb.edit_text(text, reply_markup=kb.get_markup())
                    await cb.answer()

                case Stay(new_value=nv):
                    # Re-render widget with updated state
                    text, kb = await widget.render(_widget_ctx(ff, nv))
                    if kb is None:
                        kb = InlineKeyboard()
                    kb.add(InlineButton(
                        text=_theme.nav.back,
                        callback_data=json.dumps({
                            "flow": _settings_name,
                            "value": "back",
                        }),
                    ))
                    await cb.edit_text(text, reply_markup=kb.get_markup())
                    await cb.answer()

                case Reject(message=msg):
                    await cb.answer(msg, show_alert=True)

                case NoOp():
                    await cb.answer()

        # --- Message handler (for text-input fields) ---
        async def message_handler(message: MessageCute, scope: Scope) -> None:
            key = msg_user_key(message)
            session = _sessions.get(key)
            if session is None or session.editing_field == "":
                return

            ff = _find_field(session.editing_field)
            if ff is None:
                return

            widget = ff.exchange
            if not isinstance(widget, FlowWidget):
                return

            settings_obj = await _run_query(scope)
            current = getattr(settings_obj, session.editing_field, None)
            w_ctx = _widget_ctx(ff, current)

            msg_result = await widget.handle_message(message, w_ctx)

            match msg_result:
                case Advance(value=v):
                    updated = dataclasses.replace(settings_obj, **{session.editing_field: v})
                    await _run_save(updated, scope)

                    session.editing_field = ""
                    _sessions[key] = session

                    fresh = await _run_query(scope)
                    text = _render_overview(fresh)
                    kb = _build_overview_keyboard(fresh)
                    await message.answer(text, reply_markup=kb.get_markup())

                case Stay(new_value=nv):
                    text, kb = await widget.render(_widget_ctx(ff, nv))
                    if kb is None:
                        kb = InlineKeyboard()
                    kb.add(InlineButton(
                        text=_theme.nav.back,
                        callback_data=json.dumps({
                            "flow": _settings_name,
                            "value": "back",
                        }),
                    ))
                    await message.answer(text, reply_markup=kb.get_markup())

                case Reject(message=msg):
                    await message.answer(msg)

        # --- Build exposures ---

        # 1. Command handler (dp.message)
        cmd_trigger = TelegrindTrigger(Command(self.command), view="message")
        ctx = add_delegate_exposure(
            ctx, command_handler, cmd_trigger, self.capabilities,
            f"{entity.__name__}SettingsOp",
            description=self.description, order=self.order,
        )

        # 2. Callback handler (dp.callback_query)
        cb_trigger = TelegrindTrigger(
            PayloadModelRule(_FlowCallbackData) & _SettingsNameCheck(_settings_name),
            view="callback_query",
        )
        ctx = add_delegate_exposure(
            ctx, callback_handler, cb_trigger,
            (*self.capabilities, AnswerCallback()),
            f"{entity.__name__}SettingsCbOp",
        )

        # 3. Message handler (dp.message) — only if text input fields exist
        if _has_message_fields:
            # Custom rule: only match when this user has an active editing session
            _key_node = self.key_node
            _sess_ref = _sessions

            class _HasActiveEdit(ABCRule):
                """Match only when user is editing a text-input field."""

                def check(self, context: Context) -> bool:
                    # Extract user key from the update
                    from telegrinder.types import Update
                    update = context.get("update")
                    if update is None or not isinstance(update, Update):
                        return False
                    match update.message:
                        case Some(msg):
                            from_user = msg.from_user
                            if isinstance(from_user, Some):
                                uid_key = str(from_user.value.id)
                            else:
                                uid_key = str(msg.chat.id)
                        case _:
                            return False
                    session = _sess_ref.get(uid_key)
                    if session is None or session.editing_field == "":
                        return False
                    ff = _find_field(session.editing_field)
                    if ff is None:
                        return False
                    widget = ff.exchange
                    return isinstance(widget, FlowWidget) and not widget.needs_callback

            msg_trigger = TelegrindTrigger(_HasActiveEdit(), view="message")
            ctx = add_delegate_exposure(
                ctx, message_handler, msg_trigger, self.capabilities,
                f"{entity.__name__}SettingsMsgOp",
            )

        return ctx


# ═══════════════════════════════════════════════════════════════════════════════
# TGSettingsPattern — the Pattern
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class TGSettingsPattern:
    """Pattern: annotated entity -> settings page with inline field editing.

        @derive(tg_settings(command="settings", key_node=UserId))
        @dataclass
        class PlayerSettings:
            codename: Annotated[str, TextInput("Enter codename:")]
            ...

            @classmethod
            @query
            async def load(cls, uid: ...) -> PlayerSettings: ...

            @classmethod
            @on_save
            async def save(cls, settings: PlayerSettings, uid: ...) -> None: ...
    """

    command: str
    key_node: type
    capabilities: tuple[SurfaceCapability, ...] = ()
    description: str | None = None
    order: int = 100
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
            SettingsSurfaceStep(
                command=self.command,
                key_node=self.key_node,
                capabilities=self.capabilities,
                description=self.description,
                order=self.order,
                theme=self.theme,
                agent_cls=self.agent_cls,
            ),
        ]
        return tuple(steps)


def tg_settings(
    command: str,
    key_node: type,
    *caps: SurfaceCapability,
    description: str | None = None,
    order: int = 100,
    theme: UITheme | None = None,
    agent_cls: type[Agent] | None = None,
) -> TGSettingsPattern:
    """Create TG settings pattern.

    Args:
        command: Telegram command name (e.g., "settings" -> /settings).
        key_node: nodnod node for session routing.
        *caps: Surface capabilities.
        description: Help description for /help generation.
        order: Sort order for /help generation.

    Returns:
        TGSettingsPattern -- use with @derive().

    Example::

        @derive(tg_settings(command="settings", key_node=UserId,
                             description="Player settings", order=7))
        @dataclass
        class PlayerSettings:
            codename: Annotated[str, TextInput("Enter codename:")]
            notifications: Annotated[bool, Confirm("Enable notifications?")]
            preferred_bet: Annotated[int, Counter("Bet:", min=10, max=1000)]

            @classmethod
            @query
            async def load(cls, uid: ...) -> PlayerSettings:
                return PlayerSettings(...)

            @classmethod
            @on_save
            async def save(cls, settings: PlayerSettings, uid: ...) -> None:
                ...
    """
    return TGSettingsPattern(
        command=command,
        key_node=key_node,
        capabilities=caps,
        description=description,
        order=order,
        theme=theme if theme is not None else DEFAULT_THEME,
        agent_cls=agent_cls,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Exports
# ═══════════════════════════════════════════════════════════════════════════════


__all__ = (
    # Pattern
    "tg_settings",
    "TGSettingsPattern",
    # Step
    "SettingsSurfaceStep",
    # Decorators
    "on_save",
    "format_settings",
    # Session
    "SettingsSession",
    # Re-export query for user convenience
    "query",
)

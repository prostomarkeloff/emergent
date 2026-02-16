"""tg_browse pattern — paginated Telegram entity browsing with actions.

Compiles annotated entity class → DelegateCodec handlers for command + inline navigation.

    from derivelib.patterns.tg.browse import tg_browse, query, action, ActionResult

    @derive(tg_browse(command="tasks", provider_node=TaskStore, key_node=ChatIdNode, page_size=5))
    @dataclass
    class TaskCard:
        id: Annotated[int, Identity]
        title: Annotated[str, tg.Bold()]

        @classmethod
        @query
        async def my_tasks(cls, db: ...) -> BrowseSource[TaskCard]: ...

        @classmethod
        @action("Open")
        async def open_task(cls, entity: TaskCard) -> ActionResult: ...

The pattern generates:
1. A command handler (DelegateCodec) that fetches first page and renders card + buttons
2. A callback handler (DelegateCodec) for navigation (prev/next) and action buttons
3. BrowseCB callback_data model for routing

Browse state (current page, context) is stored in MemoryStorage keyed by chat_id.
"""

from __future__ import annotations

import inspect
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import (
    TYPE_CHECKING,
    Generic,
    Protocol,
    TypeVar,
    runtime_checkable,
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

from emergent.wire.axis.surface import Exposure
from emergent.wire.axis.surface.capabilities._base import SurfaceCapability
from emergent.wire.axis.surface.codecs.delegate import DelegateCodec
from emergent.wire.axis.surface.dialects.telegram import AnswerCallback
from emergent.wire.axis.surface.triggers.telegrinder import TelegrindTrigger

from derivelib._codegen import create_sentinel_operation
from derivelib._ctx import SurfaceCtx
from derivelib._derivation import Derivation, DerivationT
from derivelib.axes.schema import inspect_entity
from derivelib.patterns.tg.uilib.theme import DEFAULT_THEME, UITheme
from derivelib.patterns.tg.uilib.keyboard import build_nav_keyboard

T_co = TypeVar("T_co", covariant=True)
T = TypeVar("T")
F = TypeVar("F", bound=Callable[..., object])


QUERY_ATTR = "__browse_query__"
ACTION_ATTR = "__browse_action__"
ACTION_ROW_ATTR = "__browse_action_row__"
FORMAT_CARD_ATTR = "__browse_format_card__"
VIEW_FILTER_ATTR = "__browse_view_filters__"


# ═══════════════════════════════════════════════════════════════════════════════
# BrowseSource — protocol for paginated data
# ═══════════════════════════════════════════════════════════════════════════════


@runtime_checkable
class BrowseSource(Protocol[T_co]):
    """Protocol for paginated data sources.

    Implementations provide page-based access to entity lists.

        class RelationalBrowseSource(BrowseSource[T]):
            async def fetch_page(self, offset: int, limit: int) -> list[T]: ...
            async def count(self) -> int: ...
    """

    async def fetch_page(self, offset: int, limit: int) -> Sequence[T_co]: ...
    async def count(self) -> int: ...


@dataclass
class ListBrowseSource(Generic[T]):
    """Simple in-memory BrowseSource backed by a list."""

    items: list[T]

    async def fetch_page(self, offset: int, limit: int) -> Sequence[T]:
        return self.items[offset : offset + limit]

    async def count(self) -> int:
        return len(self.items)


# ═══════════════════════════════════════════════════════════════════════════════
# ActionResult — return type for @action handlers
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class ActionResult:
    """Result from a browse action handler.

    Determines what happens after the action executes.
    """

    kind: str  # "refresh", "redirect", "stay", "confirm"
    message: str = ""
    command: str = ""
    redirect_context: tuple[object, ...] = ()
    confirm_prompt: str = ""

    @staticmethod
    def refresh(message: str = "") -> ActionResult:
        """Re-render current page after mutation."""
        return ActionResult(kind="refresh", message=message)

    @staticmethod
    def redirect(command: str, *context: object) -> ActionResult:
        """Redirect to another browse/flow/command.

        Context objects are stored and injected into the target command's
        @query/@action methods via compose.Retrieve.

            return ActionResult.redirect("tasks", project)
        """
        return ActionResult(kind="redirect", command=command, redirect_context=context)

    @staticmethod
    def stay(message: str = "") -> ActionResult:
        """Show message but don't change the page."""
        return ActionResult(kind="stay", message=message)

    @staticmethod
    def confirm(prompt: str) -> ActionResult:
        """Show confirmation dialog before proceeding."""
        return ActionResult(kind="confirm", confirm_prompt=prompt)


# ═══════════════════════════════════════════════════════════════════════════════
# Decorators — @query, @action, @format_card
# ═══════════════════════════════════════════════════════════════════════════════


def query(fn: F) -> F:
    """Mark classmethod as browse data source factory.

    The method should return a BrowseSource[EntityType].

        @classmethod
        @query
        async def my_tasks(cls, db: ...) -> BrowseSource[TaskCard]:
            return relational_source(db, relational(TaskCard).filter(...))
    """
    setattr(fn, QUERY_ATTR, True)
    return fn


@dataclass(frozen=True, slots=True)
class _ActionEntry:
    """Metadata for an @action-decorated method."""

    label: str
    method_name: str
    row: int = 0


def action(label: str, *, row: int = 0) -> Callable[[F], F]:
    """Mark classmethod as browse entity action.

    Args:
        label: Button label shown to user.
        row: Keyboard row number (actions with same row share a row).

        @classmethod
        @action("Open")
        async def open_task(cls, entity: TaskCard) -> ActionResult:
            return ActionResult.redirect("task_detail", entity)
    """

    def decorator(fn: F) -> F:
        setattr(fn, ACTION_ATTR, label)
        setattr(fn, ACTION_ROW_ATTR, row)
        return fn

    return decorator


def format_card(fn: F) -> F:
    """Mark classmethod as custom card renderer.

    The method receives the entity and returns formatted text.

        @classmethod
        @format_card
        def render(cls, entity: TaskCard) -> str:
            return f"**{entity.title}**\\n{entity.description}"
    """
    setattr(fn, FORMAT_CARD_ATTR, True)
    return fn


@dataclass(frozen=True, slots=True)
class _ViewFilter:
    """Metadata for a @view_filter-decorated filter tab."""

    label: str
    key: str


def view_filter(label: str, key: str = "") -> Callable[[F], F]:
    """Register a named filter tab for browse.

    Stacks multiple filters on the same @query method.

        @view_filter("Active", key="active")
        @view_filter("Done", key="done")
        @classmethod
        @query
        async def stories(cls, db: ..., filter_key: str = "") -> BrowseSource[Board]: ...
    """

    def decorator(fn: F) -> F:
        existing: list[_ViewFilter] = list(getattr(fn, VIEW_FILTER_ATTR, []))
        vf_key = key or label.lower().replace(" ", "_")
        existing.append(_ViewFilter(label=label, key=vf_key))
        setattr(fn, VIEW_FILTER_ATTR, existing)
        return fn

    return decorator


# ═══════════════════════════════════════════════════════════════════════════════
# Callback data model
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class BrowseCB:
    """Callback data for browse navigation and actions.

    Kept compact to fit Telegram's 64-byte callback_data limit.
    Uses short field names and MsgPack serialization.

    Fields:
        b: browse identifier (short name)
        a: action ("prev", "next", or action method name)
        e: entity ID (0 for navigation)
        p: page number
    """

    b: str  # browse name
    a: str  # action
    e: int = 0  # entity id
    p: int = 0  # page


# ═══════════════════════════════════════════════════════════════════════════════
# Browse session state
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class BrowseSession:
    """In-memory state for an active browse session."""

    page: int = 0
    filter_key: str = ""
    search_query: str = ""


# ═══════════════════════════════════════════════════════════════════════════════
# Entity scanning — find @query, @action, @format_card
# ═══════════════════════════════════════════════════════════════════════════════


def _iter_entity_methods(entity: type) -> Sequence[tuple[str, Callable[..., object]]]:
    """Iterate public methods of entity, yielding (name, unwrapped_fn).

    Shared scanning logic for @query, @action, @format_card discovery.
    """
    results: list[tuple[str, Callable[..., object]]] = []
    for name in dir(entity):
        if name.startswith("_"):
            continue
        raw = inspect.getattr_static(entity, name, None)
        if raw is None:
            continue
        fn = getattr(raw, "__func__", raw)
        results.append((name, fn))
    return results


def _find_query_method(entity: type) -> str | None:
    """Find the single @query-decorated method name.

    Raises if more than one @query method is found — browse entities
    must have exactly one query source (use filter_key for filtering).
    """
    found: list[str] = []
    for name, fn in _iter_entity_methods(entity):
        if getattr(fn, QUERY_ATTR, False):
            found.append(name)
    if len(found) > 1:
        raise ValueError(
            f"{entity.__name__} has {len(found)} @query methods ({', '.join(found)}), "
            f"but only one is allowed. Use @view_filter + filter_key parameter instead."
        )
    return found[0] if found else None


def _find_actions(entity: type) -> list[_ActionEntry]:
    """Find all @action-decorated methods."""
    actions: list[_ActionEntry] = []
    for name, fn in _iter_entity_methods(entity):
        label = getattr(fn, ACTION_ATTR, None)
        if label is not None:
            act_row = getattr(fn, ACTION_ROW_ATTR, 0)
            actions.append(_ActionEntry(label=label, method_name=name, row=act_row))
    return actions


def _find_format_card(entity: type) -> str | None:
    """Find the @format_card-decorated method name."""
    for name, fn in _iter_entity_methods(entity):
        if getattr(fn, FORMAT_CARD_ATTR, False):
            return name
    return None


def _find_view_filters(entity: type) -> list[_ViewFilter]:
    """Find @view_filter-decorated filters on the @query method."""
    for _name, fn in _iter_entity_methods(entity):
        filters = getattr(fn, VIEW_FILTER_ATTR, None)
        if filters is not None:
            return list(filters)
    return []


# ═══════════════════════════════════════════════════════════════════════════════
# Default card rendering
# ═══════════════════════════════════════════════════════════════════════════════


class _BrowseNameCheck(ABCRule):
    """Checks that deserialized BrowseCB.b matches expected browse_name.

    Used as ``PayloadModelRule(BrowseCB) & _BrowseNameCheck(name)`` so each
    browse entity's callback handler only matches its own callbacks.
    PayloadModelRule stores the model in context["model"]; this rule reads it.
    """

    def __init__(self, browse_name: str) -> None:
        self._browse_name = browse_name

    def check(self, context: Context) -> bool:
        model = context.get("model")
        if not isinstance(model, BrowseCB):
            return False
        return model.b == self._browse_name


def _default_render_card(entity: object) -> str:
    """Default entity card rendering — field: value format."""
    import dataclasses

    if not dataclasses.is_dataclass(entity):
        return str(entity)

    lines: list[str] = []
    for f in dataclasses.fields(entity):
        value = getattr(entity, f.name)
        if value is not None:
            lines.append(f"{f.name}: {value}")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# DI resolution — resolve compose params for @query/@action at runtime
# ═══════════════════════════════════════════════════════════════════════════════


async def _resolve_method_di(
    method: Callable[..., object],
    composer: Composer,
    entity_in_scope: tuple[type, object] | None = None,
) -> dict[str, object]:
    """Resolve compose.* params for a method using the compiler's Composer.

    Delegates to Composer.resolve_params. The scope is
    threaded from the compiler — no duplicate scope creation.

    For @action methods, entity_in_scope=(EntityClass, instance) injects
    the card entity into scope so it resolves by type
    (e.g. ``entity: TaskCard`` → scope has TaskCard → resolved).
    """
    if entity_in_scope is not None:
        composer.scope.inject(entity_in_scope[0], entity_in_scope[1])
    return await composer.resolve_params(method)


# ═══════════════════════════════════════════════════════════════════════════════
# BrowseSurfaceStep — THE surface derivation step
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class BrowseSurfaceStep:
    """Generate DelegateCodec handlers for browse command + callbacks.

    Creates two exposures:
    1. Command handler (dp.message) — fetches first page, renders, sends
    2. Callback handler (dp.callback_query) — handles nav + action buttons

    DI resolution: handlers declare MessageCute/CallbackQueryCute + Context,
    resolved by the compiler from scope. @query/@action compose params
    resolved at runtime via _resolve_method_di (same pattern as compose_store_key).
    """

    command: str
    key_node: type
    page_size: int
    empty_text: str
    capabilities: tuple[SurfaceCapability, ...]
    browse_name: str
    description: str | None = None
    order: int = 100
    theme: UITheme = field(default_factory=UITheme)
    agent_cls: type[Agent] | None = None

    def derive_surface[EntityT](self, ctx: SurfaceCtx[EntityT]) -> SurfaceCtx[EntityT]:
        entity = ctx.schema.entity
        query_method_name = _find_query_method(entity)
        actions = _find_actions(entity)
        format_card_name = _find_format_card(entity)

        if query_method_name is None:
            raise ValueError(
                f"{entity.__name__} must have a @query-decorated method"
            )

        # Get identity field name (for entity ID in callbacks)
        id_field_name = "id"
        if ctx.schema.identity_fields:
            id_field_name = next(iter(ctx.schema.identity_fields))

        # Closures for handlers
        _entity = entity
        _query_name = query_method_name
        _actions = actions
        _format_name = format_card_name
        _id_field = id_field_name
        _page_size = self.page_size
        _empty_text = self.empty_text
        _browse_name = self.browse_name
        _view_filters = _find_view_filters(entity)
        _theme = self.theme
        _agent_cls = self.agent_cls

        # Session store: chat_id → BrowseSession
        _sessions: dict[str, BrowseSession] = {}

        # Redirect context store: (chat_id, command) → objects
        _redirect_store: dict[tuple[str, str], tuple[object, ...]] = {}

        async def _run_query(
            scope: Scope,
            session: BrowseSession | None = None,
        ) -> BrowseSource[EntityT]:
            """Run @query method with compose params + filter/search from session."""
            method = getattr(_entity, _query_name)
            composer = Composer.create(scope, _agent_cls)
            resolved = await _resolve_method_di(method, composer)
            if session is not None:
                sig = inspect.signature(method)
                if "filter_key" in sig.parameters and session.filter_key:
                    resolved["filter_key"] = session.filter_key
                if "search_query" in sig.parameters and session.search_query:
                    resolved["search_query"] = session.search_query
            return await method(**resolved)

        async def _run_action(
            action_method_name: str,
            card: object,
            scope: Scope,
            confirmed: bool = False,
        ) -> ActionResult:
            """Run @action method with card + compose params resolved from scope.

            The card entity is injected into scope by its runtime type so
            resolve_handler_params resolves it (e.g. ``m: Mission`` → scope[Mission] → card).
            When confirmed=True, injects confirmed=True if method declares it.
            """
            method = getattr(_entity, action_method_name)
            composer = Composer.create(scope, _agent_cls)
            resolved = await _resolve_method_di(method, composer, entity_in_scope=(type(card), card))
            if confirmed:
                sig = inspect.signature(method)
                if "confirmed" in sig.parameters:
                    resolved["confirmed"] = True
            return await method(**resolved)

        def _render(entity_obj: object) -> str:
            """Render entity card."""
            if _format_name is not None:
                formatter = getattr(_entity, _format_name)
                return formatter(entity_obj)
            return _default_render_card(entity_obj)

        def _get_entity_id(entity_obj: object) -> int:
            """Get entity ID for callback routing."""
            return getattr(entity_obj, _id_field, 0)

        def _render_page(
            items: Sequence[object],
            page: int,
            total: int,
            prefix: str = "",
            filter_key: str = "",
        ) -> tuple[str, InlineKeyboard]:
            """Render items into text + navigation keyboard."""
            total_pages = max(1, (total + _page_size - 1) // _page_size)
            texts: list[str] = []
            entity_ids: list[int] = []
            for item in items:
                texts.append(_render(item))
                entity_ids.append(_get_entity_id(item))
            text = "\n\n".join(texts) if texts else _empty_text
            if prefix:
                text = f"{prefix}\n\n{text}"
            kb = build_nav_keyboard(
                _browse_name, page, total_pages, entity_ids, _actions,
                theme=_theme, view_filters=_view_filters, active_filter=filter_key,
            )
            return text, kb

        async def _query_and_render(
            scope: Scope,
            session: BrowseSession,
            prefix: str = "",
        ) -> tuple[str, InlineKeyboard] | None:
            """Run query, count, fetch page, render. Returns None if empty."""
            source = await _run_query(scope, session)
            total = await source.count()
            if total == 0:
                return None
            offset = session.page * _page_size
            items = await source.fetch_page(offset, _page_size)
            return _render_page(
                items, session.page, total,
                prefix=prefix, filter_key=session.filter_key,
            )

        def _msg_user_key(message: MessageCute) -> str:
            """Session key — user ID when available, fallback to chat ID."""
            if isinstance(message.from_user, Some):
                return str(message.from_user.value.id)
            return str(message.chat.id)

        # --- Command handler (DelegateCodec) ---
        # Declares MessageCute + Context — compiler resolves both from scope.
        # @query/@action compose params resolved at runtime via _resolve_method_di.
        async def command_handler(message: MessageCute, scope: Scope) -> None:
            key = _msg_user_key(message)
            session = BrowseSession(page=0)
            _sessions[key] = session

            result = await _query_and_render(scope, session)
            if result is None:
                await message.answer(_empty_text)
                return
            text, kb = result
            await message.answer(text, reply_markup=kb.get_markup())

        # --- Search handler (DelegateCodec) ---
        # Handles text messages when user has an active browse session.
        async def search_handler(message: MessageCute, scope: Scope) -> None:
            key = _msg_user_key(message)
            session = _sessions.get(key)
            if session is None:
                return

            match message.text:
                case Some(txt):
                    search_text = txt.strip()
                case _:
                    return

            session.search_query = search_text
            session.page = 0
            _sessions[key] = session

            result = await _query_and_render(scope, session)
            if result is None:
                await message.answer(f"No results for \"{search_text}\".")
                return
            text, kb = result
            await message.answer(text, reply_markup=kb.get_markup())

        # --- Callback handler (DelegateCodec) ---
        # cb.answer() is handled by AnswerCallback capability via fold.
        # Only show_alert needs explicit answer (before auto-answer, first wins).
        async def callback_handler(cb: CallbackQueryCute, scope: Scope) -> None:
            match cb.data:
                case Some(raw_data):
                    pass
                case _:
                    return

            try:
                parsed = json.loads(raw_data)
                cb_data = BrowseCB(**parsed)
            except (json.JSONDecodeError, KeyError, TypeError):
                return

            if cb_data.b != _browse_name:
                return

            key = str(cb.from_user.id)
            session = _sessions.get(key, BrowseSession())

            # Tab switching
            if cb_data.a.startswith("_tab_"):
                tab_key = cb_data.a[5:]
                session.filter_key = tab_key
                session.page = 0
                _sessions[key] = session

                result = await _query_and_render(scope, session)
                if result is not None:
                    text, kb = result
                    await cb.edit_text(text, reply_markup=kb.get_markup())

            elif cb_data.a in ("prev", "next"):
                session.page = cb_data.p
                _sessions[key] = session

                result = await _query_and_render(scope, session)
                if result is not None:
                    text, kb = result
                    await cb.edit_text(text, reply_markup=kb.get_markup())

            elif cb_data.a == "noop":
                return

            else:
                # Handle _confirm_ prefix (user clicked Yes on confirm dialog)
                action_name = cb_data.a
                is_confirmed = action_name.startswith("_confirm_")
                if is_confirmed:
                    action_name = action_name[9:]

                action_entry = next(
                    (a for a in _actions if a.method_name == action_name),
                    None,
                )
                if action_entry is None:
                    return

                # Fetch entity by ID
                source = await _run_query(scope, session)
                total = await source.count()
                items = await source.fetch_page(0, total)
                target = None
                for item in items:
                    if _get_entity_id(item) == cb_data.e:
                        target = item
                        break

                if target is None:
                    await cb.edit_text(_theme.display.entity_not_found)
                    return

                result: ActionResult = await _run_action(
                    action_entry.method_name, target, scope,
                    confirmed=is_confirmed,
                )
                # Guard: already confirmed but action returns confirm again
                if is_confirmed and result.kind == "confirm":
                    result = ActionResult.refresh()

                if result.kind == "refresh":
                    render_result = await _query_and_render(
                        scope, session, prefix=result.message,
                    )
                    if render_result is not None:
                        text, kb = render_result
                        await cb.edit_text(text, reply_markup=kb.get_markup())

                elif result.kind == "stay":
                    if result.message:
                        await cb.answer(result.message, show_alert=True)

                elif result.kind == "redirect":
                    if result.redirect_context:
                        _redirect_store[(key, result.command)] = result.redirect_context
                    await cb.edit_text(
                        f"{result.message}\n\n/{result.command}" if result.message
                        else f"/{result.command}",
                    )

                elif result.kind == "confirm":
                    kb = InlineKeyboard()
                    kb.add(InlineButton(
                        text=_theme.action.yes,
                        callback_data=BrowseCB(
                            b=_browse_name,
                            a=f"_confirm_{action_entry.method_name}",
                            e=cb_data.e,
                        ),
                    ))
                    kb.add(InlineButton(
                        text=_theme.action.no,
                        callback_data=BrowseCB(b=_browse_name, a="noop"),
                    ))
                    await cb.edit_text(result.confirm_prompt, reply_markup=kb.get_markup())

        # --- Build exposures ---

        # Command handler exposure (dp.message)
        cmd_trigger = TelegrindTrigger(Command(self.command), view="message")
        cmd_codec = DelegateCodec(handler=command_handler)
        cmd_caps: tuple[SurfaceCapability, ...] = self.capabilities
        if self.description is not None:
            from emergent.wire.axis.surface.dialects.telegram import HelpMeta
            cmd_caps = (*cmd_caps, HelpMeta(description=self.description, order=self.order))
        cmd_exposure = Exposure(
            trigger=cmd_trigger,
            codec=cmd_codec,
            capabilities=tuple(cmd_caps),
        )

        op_type, op_handler = create_sentinel_operation(f"{entity.__name__}BrowseOp")
        ctx = ctx.add_operation((op_type, op_handler, cmd_exposure))

        # Callback handler exposure (dp.callback_query)
        cb_trigger = TelegrindTrigger(
            PayloadModelRule(BrowseCB) & _BrowseNameCheck(_browse_name),
            view="callback_query",
        )
        cb_codec = DelegateCodec(handler=callback_handler)
        cb_exposure = Exposure(
            trigger=cb_trigger,
            codec=cb_codec,
            capabilities=(*self.capabilities, AnswerCallback()),
        )

        cb_op_type, cb_op_handler = create_sentinel_operation(f"{entity.__name__}BrowseCbOp")
        ctx = ctx.add_operation((cb_op_type, cb_op_handler, cb_exposure))

        return ctx


# ═══════════════════════════════════════════════════════════════════════════════
# TGBrowsePattern — the Pattern
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class TGBrowsePattern:
    """Pattern: annotated entity class → paginated TG browse.

    Implements the Pattern protocol (has .compile(entity) -> Derivation).

        @derive(tg_browse(command="tasks", provider_node=TaskStore,
                          key_node=ChatIdNode, page_size=5))
        @dataclass
        class TaskCard:
            id: Annotated[int, Identity]
            ...
    """

    command: str
    provider_node: type
    key_node: type
    page_size: int = 5
    empty_text: str = "Nothing found."
    capabilities: tuple[SurfaceCapability, ...] = ()
    cb_prefix: str = ""
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

        browse_name = self.cb_prefix or entity.__name__[:6].lower()

        steps: list[Step] = [
            inspect_entity(),
            BrowseSurfaceStep(
                command=self.command,
                key_node=self.key_node,
                page_size=self.page_size,
                empty_text=self.empty_text,
                capabilities=self.capabilities,
                browse_name=browse_name,
                description=self.description,
                order=self.order,
                theme=self.theme,
                agent_cls=self.agent_cls,
            ),
        ]
        return tuple(steps)


def tg_browse(
    command: str,
    provider_node: type,
    key_node: type,
    page_size: int = 5,
    empty_text: str = "Nothing found.",
    *caps: SurfaceCapability,
    cb_prefix: str = "",
    description: str | None = None,
    order: int = 100,
    theme: UITheme | None = None,
    agent_cls: type[Agent] | None = None,
) -> TGBrowsePattern:
    """Create TG browse pattern.

    Args:
        command: Telegram command name (e.g., "tasks" → /tasks).
        provider_node: nodnod node for data provider.
        key_node: nodnod node for session routing.
        page_size: Items per page.
        empty_text: Message when no items found.
        *caps: Surface capabilities.
        cb_prefix: Short prefix for callback_data (auto-generated if empty).
        description: Help description for /help generation.
        order: Sort order for /help generation.

    Returns:
        TGBrowsePattern — use with @derive().

    Example::

        @derive(tg_browse(command="tasks", provider_node=TaskStore,
                          key_node=ChatIdNode, page_size=5,
                          description="Browse tasks", order=1))
        @dataclass
        class TaskCard:
            id: Annotated[int, Identity]
            title: str

            @classmethod
            @query
            async def my_tasks(cls, db: ...) -> BrowseSource[TaskCard]:
                return ListBrowseSource([...])

            @classmethod
            @action("Open")
            async def open_task(cls, entity: TaskCard) -> ActionResult:
                return ActionResult.redirect("task", task_id=entity.id)
    """
    return TGBrowsePattern(
        command=command,
        provider_node=provider_node,
        key_node=key_node,
        page_size=page_size,
        empty_text=empty_text,
        capabilities=caps,
        cb_prefix=cb_prefix,
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
    "tg_browse",
    "TGBrowsePattern",
    # Source
    "BrowseSource",
    "ListBrowseSource",
    # Result
    "ActionResult",
    # Decorators
    "query",
    "action",
    "format_card",
    "view_filter",
    # Session
    "BrowseSession",
    # Callback data
    "BrowseCB",
    # Step
    "BrowseSurfaceStep",
)

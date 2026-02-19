"""Shared runtime helpers for TG card patterns (browse, dashboard, search).

Deduplicates common closures: entity scanning, DI resolution, callback
parsing, action dispatch (including confirm flow fix), exposure building,
and paginated rendering.

_shared.py imports from browse.py (one-directional). browse.py does NOT
import from _shared — browse keeps its own closure implementations.
dashboard.py, search.py, settings.py import helpers from here.
"""

from __future__ import annotations

import inspect
import json
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from kungfu import Some

from emergent.graph._compose import Composer

from telegrinder.bot.cute_types.callback_query import CallbackQueryCute
from telegrinder.bot.cute_types.message import MessageCute
from telegrinder.tools.keyboard import InlineButton, InlineKeyboard

from emergent.wire.axis.surface import Exposure
from emergent.wire.axis.surface.capabilities._base import SurfaceCapability
from emergent.wire.axis.surface.codecs.delegate import DelegateCodec
from emergent.wire.axis.surface.triggers.telegrinder import TelegrindTrigger

from derivelib._codegen import create_sentinel_operation
from derivelib._ctx import SurfaceCtx
from derivelib.patterns.tg.browse import (
    ActionConfirm,
    ActionRedirect,
    ActionRefresh,
    ActionResult,
    ActionResultT,
    ActionStay,
    BrowseCB,
    BrowseSession,
    _ActionEntry,
    _ViewFilter,
    _default_render_card,
    _find_actions,
    _find_format_card,
    _find_query_method,
    _find_view_filters,
    _resolve_method_di,
)
from derivelib.patterns.tg.uilib.keyboard import build_nav_keyboard
from derivelib.patterns.tg.uilib.theme import UITheme

from datetime import timedelta

from kungfu import Ok

from emergent.wire.axis.storage import MemoryStorage


# ═══════════════════════════════════════════════════════════════════════════════
# SessionStore — typed wrapper over MemoryStorage with TTL
# ═══════════════════════════════════════════════════════════════════════════════


class SessionStore[K, V]:
    """Thin typed wrapper over MemoryStorage — unwraps Result+Option.

    Replaces raw ``dict[K, V]`` session stores in TG patterns with
    proper MemoryStorage backing + automatic 1h TTL to prevent leaks.
    """

    def __init__(self, ttl: timedelta = timedelta(hours=1)) -> None:
        self._storage: MemoryStorage[K, V] = MemoryStorage()
        self._ttl = ttl

    async def get(self, key: K) -> V | None:
        result = await self._storage.get(key)
        match result:
            case Ok(opt):
                match opt:
                    case Some(v):
                        return v
                    case _:
                        return None
            case _:
                return None

    async def get_or(self, key: K, default: V) -> V:
        value = await self.get(key)
        return value if value is not None else default

    async def set(self, key: K, value: V) -> None:
        await self._storage.set(key, value, self._ttl)

    async def delete(self, key: K) -> None:
        await self._storage.delete(key)

    async def contains(self, key: K) -> bool:
        return await self.get(key) is not None


# ═══════════════════════════════════════════════════════════════════════════════
# Entity inspection
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class CardEntityInfo:
    """Scanned metadata for a card entity (browse/dashboard/search)."""

    entity: type
    query_name: str
    actions: list[_ActionEntry]
    format_name: str | None
    id_field: str
    view_filters: list[_ViewFilter]


def inspect_card_entity[EntityT](ctx: SurfaceCtx[EntityT]) -> CardEntityInfo:
    """Common entity scanning for browse/dashboard/search derive_surface.

    Validates @query exists, finds @actions, @format_card, identity field,
    @view_filters. Replaces ~15 lines of boilerplate per pattern.
    """
    entity = ctx.schema.entity
    query_name = _find_query_method(entity)
    if query_name is None:
        raise ValueError(
            f"{entity.__name__} must have a @query-decorated method"
        )
    id_field = "id"
    if ctx.schema.identity_fields:
        id_field = next(iter(ctx.schema.identity_fields))
    return CardEntityInfo(
        entity=entity,
        query_name=query_name,
        actions=_find_actions(entity),
        format_name=_find_format_card(entity),
        id_field=id_field,
        view_filters=_find_view_filters(entity),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# User key
# ═══════════════════════════════════════════════════════════════════════════════


def msg_user_key(message: MessageCute) -> str:
    """Session key — user ID when available, fallback to chat ID."""
    if isinstance(message.from_user, Some):
        return str(message.from_user.value.id)
    return str(message.chat.id)


# ═══════════════════════════════════════════════════════════════════════════════
# Callback parsing
# ═══════════════════════════════════════════════════════════════════════════════


def parse_browse_cb(
    cb: CallbackQueryCute,
    expected_name: str,
) -> BrowseCB | None:
    """Parse BrowseCB from callback, validate name matches.

    Returns None if data is missing, unparseable, or name mismatch.
    """
    match cb.data:
        case Some(raw_data):
            pass
        case _:
            return None
    try:
        parsed = json.loads(raw_data)
        cb_data = BrowseCB(**parsed)
    except (json.JSONDecodeError, KeyError, TypeError):
        return None
    if cb_data.b != expected_name:
        return None
    return cb_data


# ═══════════════════════════════════════════════════════════════════════════════
# Rendering
# ═══════════════════════════════════════════════════════════════════════════════


def render_card(
    entity_cls: type,
    format_name: str | None,
    entity_obj: object,
) -> str:
    """Render entity card using @format_card or default renderer."""
    if format_name is not None:
        return getattr(entity_cls, format_name)(entity_obj)
    return _default_render_card(entity_obj)


def get_entity_id(entity_obj: object, id_field: str) -> int:
    """Get entity ID for callback routing."""
    return getattr(entity_obj, id_field, 0)


def render_page(
    info: CardEntityInfo,
    items: Sequence[object],
    page: int,
    total: int,
    *,
    page_size: int,
    name: str,
    empty_text: str,
    theme: UITheme,
    prefix: str = "",
    active_filter: str = "",
) -> tuple[str, InlineKeyboard]:
    """Render entity list into text + navigation keyboard."""
    total_pages = max(1, (total + page_size - 1) // page_size)
    texts: list[str] = []
    entity_ids: list[int] = []
    for item in items:
        texts.append(render_card(info.entity, info.format_name, item))
        entity_ids.append(get_entity_id(item, info.id_field))
    text = "\n\n".join(texts) if texts else empty_text
    if prefix:
        text = f"{prefix}\n\n{text}"
    kb = build_nav_keyboard(
        name, page, total_pages, entity_ids, info.actions,
        theme=theme, view_filters=info.view_filters, active_filter=active_filter,
    )
    return text, kb


async def query_and_render(
    info: CardEntityInfo,
    composer: Composer,
    session: BrowseSession,
    *,
    page_size: int,
    name: str,
    empty_text: str,
    theme: UITheme,
    prefix: str = "",
) -> tuple[str, InlineKeyboard] | None:
    """Run query, count, fetch page, render. Returns None if empty."""
    source = await run_query_di(
        info.entity, info.query_name, composer,
        filter_key=session.filter_key,
        search_query=session.search_query,
    )
    total = await source.count()
    if total == 0:
        return None
    offset = session.page * page_size
    items = await source.fetch_page(offset, page_size)
    return render_page(
        info, items, session.page, total,
        page_size=page_size, name=name, empty_text=empty_text,
        theme=theme, prefix=prefix, active_filter=session.filter_key,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# DI resolution
# ═══════════════════════════════════════════════════════════════════════════════


async def run_query_di(
    entity_cls: type,
    query_name: str,
    composer: Composer,
    *,
    filter_key: str = "",
    search_query: str = "",
) -> object:
    """Run @query method with DI + optional filter/search params."""
    method = getattr(entity_cls, query_name)
    resolved = await _resolve_method_di(method, composer)
    sig = inspect.signature(method)
    if "filter_key" in sig.parameters and filter_key:
        resolved["filter_key"] = filter_key
    if "search_query" in sig.parameters and search_query:
        resolved["search_query"] = search_query
    return await method(**resolved)


async def run_action_di(
    entity_cls: type,
    action_method_name: str,
    card: object,
    composer: Composer,
    *,
    confirmed: bool = False,
) -> ActionResultT:
    """Run @action method with DI. Injects confirmed=True when applicable.

    Actions that want confirm-awareness declare ``confirmed: bool = False``
    in their signature. On the second call (after user clicks Yes),
    confirmed=True is injected so the action can distinguish first-click
    from confirmed invocation.
    """
    method = getattr(entity_cls, action_method_name)
    resolved = await _resolve_method_di(
        method, composer,
        entity_in_scope=(type(card), card),
    )
    if confirmed:
        sig = inspect.signature(method)
        if "confirmed" in sig.parameters:
            resolved["confirmed"] = True
    return await method(**resolved)


# ═══════════════════════════════════════════════════════════════════════════════
# Action result dispatch (with confirm fix)
# ═══════════════════════════════════════════════════════════════════════════════


async def dispatch_action_result(
    result: ActionResultT,
    cb: CallbackQueryCute,
    name: str,
    action_method_name: str,
    entity_id: int,
    theme: UITheme,
    refresh: Callable[[str], Awaitable[tuple[str, InlineKeyboard] | None]],
    *,
    redirect_store: SessionStore[tuple[str, str], tuple[object, ...]] | None = None,
    user_key: str = "",
) -> None:
    """Handle ActionResult — shared by browse, dashboard, search.

    Args:
        result: The action result to dispatch.
        cb: Telegram callback query to respond on.
        name: Pattern name for callback routing (browse_name etc).
        action_method_name: The action's method name (for confirm dialog).
        entity_id: Entity ID (for confirm callback data).
        theme: UI theme.
        refresh: Async callable(prefix) → (text, kb) | None for re-rendering.
        redirect_store: Optional SessionStore for redirect context (browse/search).
        user_key: User key for redirect store keying.
    """
    if isinstance(result, ActionRefresh):
        render_result = await refresh(result.message)
        if render_result is not None:
            text, kb = render_result
            await cb.edit_text(text, reply_markup=kb.get_markup())

    elif isinstance(result, ActionStay):
        if result.message:
            await cb.answer(result.message, show_alert=True)

    elif isinstance(result, ActionRedirect):
        if redirect_store is not None and result.redirect_context and user_key:
            await redirect_store.set((user_key, result.command), result.redirect_context)
        await cb.edit_text(
            f"{result.message}\n\n/{result.command}" if result.message
            else f"/{result.command}",
        )

    elif isinstance(result, ActionConfirm):
        confirm_kb = InlineKeyboard()
        confirm_kb.add(InlineButton(
            text=theme.action.yes,
            callback_data=BrowseCB(
                b=name,
                a=f"_confirm_{action_method_name}",
                e=entity_id,
            ),
        ))
        confirm_kb.add(InlineButton(
            text=theme.action.no,
            callback_data=BrowseCB(b=name, a="noop"),
        ))
        await cb.edit_text(result.prompt, reply_markup=confirm_kb.get_markup())


async def handle_action_callback(
    cb_data: BrowseCB,
    cb: CallbackQueryCute,
    info: CardEntityInfo,
    composer: Composer,
    name: str,
    theme: UITheme,
    fetch_entity: Callable[[], Awaitable[object | None]],
    refresh: Callable[[str], Awaitable[tuple[str, InlineKeyboard] | None]],
    *,
    redirect_store: SessionStore[tuple[str, str], tuple[object, ...]] | None = None,
    user_key: str = "",
) -> None:
    """Handle action/confirm callback — shared by browse, dashboard, search.

    Handles _confirm_ prefix (strips it, re-runs action with confirmed=True).
    Guards infinite confirm loops by treating re-confirm as refresh.
    """
    action_name = cb_data.a
    is_confirmed = action_name.startswith("_confirm_")
    if is_confirmed:
        action_name = action_name[9:]

    action_entry = next(
        (a for a in info.actions if a.method_name == action_name),
        None,
    )
    if action_entry is None:
        return

    target = await fetch_entity()
    if target is None:
        await cb.edit_text(theme.display.entity_not_found)
        return

    result = await run_action_di(
        info.entity, action_entry.method_name, target, composer,
        confirmed=is_confirmed,
    )
    # Guard: already confirmed but action returns confirm again → treat as refresh
    if is_confirmed and isinstance(result, ActionConfirm):
        result = ActionRefresh()

    await dispatch_action_result(
        result, cb, name, action_entry.method_name,
        cb_data.e, theme, refresh,
        redirect_store=redirect_store, user_key=user_key,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Exposure building
# ═══════════════════════════════════════════════════════════════════════════════


def add_delegate_exposure[EntityT](
    ctx: SurfaceCtx[EntityT],
    handler: Callable[..., object],
    trigger: TelegrindTrigger,
    capabilities: tuple[SurfaceCapability, ...],
    op_name: str,
    *,
    description: str | None = None,
    order: int = 100,
) -> SurfaceCtx[EntityT]:
    """Build DelegateCodec exposure + sentinel op and add to ctx."""
    caps = capabilities
    if description is not None:
        from emergent.wire.axis.surface.dialects.telegram import HelpMeta
        caps = (*caps, HelpMeta(description=description, order=order))
    exposure = Exposure(
        trigger=trigger,
        codec=DelegateCodec(handler=handler),
        capabilities=tuple(caps),
    )
    op_type, op_handler = create_sentinel_operation(op_name)
    return ctx.add_operation((op_type, op_handler, exposure))

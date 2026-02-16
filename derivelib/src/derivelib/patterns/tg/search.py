"""tg_search pattern — search-first paginated Telegram entity browsing.

Like tg_browse, but starts with a search prompt. The user sends a text query,
then browses paginated results with actions.

    from derivelib.patterns.tg.search import tg_search
    from derivelib.patterns.tg.browse import query, action, format_card, BrowseSource

    @derive(tg_search(command="search", key_node=ChatIdNode))
    @dataclass
    class ProductSearch:
        id: Annotated[int, Identity]
        name: str
        price: float

        @classmethod
        @query
        async def find(cls, db: DB, search_query: str = "") -> BrowseSource[ProductSearch]:
            return db.search_products(search_query)

        @classmethod
        @format_card
        def render(cls, p: ProductSearch) -> str:
            return f"**{p.name}** — ${p.price}"

        @classmethod
        @action("Buy")
        async def buy(cls, entity: ProductSearch) -> ActionResult: ...

Flow:
1. User sends /search → bot asks search prompt
2. User sends text → bot queries, shows paginated results
3. User navigates pages, clicks actions
4. User can type new text to search again

Reuses decorators (@query, @action, @format_card, @view_filter) and infrastructure
(BrowseSource, BrowseCB, ActionResult) from tg_browse.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

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
from telegrinder.tools.keyboard import InlineKeyboard
from telegrinder.types.objects import Update

from emergent.wire.axis.surface.capabilities._base import SurfaceCapability
from emergent.wire.axis.surface.dialects.telegram import AnswerCallback
from emergent.wire.axis.surface.triggers.telegrinder import TelegrindTrigger

from derivelib._ctx import SurfaceCtx
from derivelib._derivation import Derivation, DerivationT
from derivelib.axes.schema import inspect_entity
from derivelib.patterns.tg.browse import (
    BrowseCB,
    BrowseSession,
    _BrowseNameCheck,
)
from derivelib.patterns.tg._shared import (
    add_delegate_exposure,
    get_entity_id,
    handle_action_callback,
    inspect_card_entity,
    msg_user_key,
    parse_browse_cb,
    query_and_render,
    run_query_di,
)
from derivelib.patterns.tg.uilib.theme import DEFAULT_THEME, UITheme


# ═══════════════════════════════════════════════════════════════════════════════
# Session check rule
# ═══════════════════════════════════════════════════════════════════════════════


class _HasActiveSearchSession(ABCRule):
    """Rule: matches text messages from users with an active search session.

    Rejects commands (starting with /) so they route to Command rules instead.
    """

    def __init__(self, sessions: dict[str, BrowseSession]) -> None:
        self._sessions = sessions

    def check(self, update: Update, ctx: Context) -> bool:
        match update.message:
            case Some(msg):
                # Skip commands — let Command rules handle them
                match msg.text:
                    case Some(txt) if txt.startswith("/"):
                        return False
                    case _:
                        pass
                # Extract user key
                match msg.from_:
                    case Some(user):
                        key = str(user.id)
                    case _:
                        key = str(msg.chat.id)
                return key in self._sessions
            case _:
                return False


# ═══════════════════════════════════════════════════════════════════════════════
# SearchSurfaceStep — THE surface derivation step
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class SearchSurfaceStep:
    """Generate DelegateCodec handlers for search command + text + callbacks.

    Creates three exposures:
    1. Command handler (dp.message, Command rule) — sends search prompt
    2. Text handler (dp.message, HasActiveSearch rule) — captures search text, shows results
    3. Callback handler (dp.callback_query) — handles nav + action buttons

    Reuses browse infrastructure for pagination, rendering, and actions.
    """

    command: str
    key_node: type
    prompt: str
    page_size: int
    empty_text: str
    capabilities: tuple[SurfaceCapability, ...]
    search_name: str
    description: str | None = None
    order: int = 100
    theme: UITheme = field(default_factory=UITheme)
    agent_cls: type[Agent] | None = None

    def derive_surface[EntityT](self, ctx: SurfaceCtx[EntityT]) -> SurfaceCtx[EntityT]:
        info = inspect_card_entity(ctx)

        _page_size = self.page_size
        _empty_text = self.empty_text
        _search_name = self.search_name
        _theme = self.theme
        _prompt = self.prompt
        _agent_cls = self.agent_cls

        # Session store: user_key → BrowseSession
        _sessions: dict[str, BrowseSession] = {}

        # Redirect context store
        _redirect_store: dict[tuple[str, str], tuple[object, ...]] = {}

        async def _do_query_and_render(
            scope: Scope,
            session: BrowseSession,
            prefix: str = "",
        ) -> tuple[str, InlineKeyboard] | None:
            composer = Composer.create(scope, _agent_cls)
            return await query_and_render(
                info, composer, session,
                page_size=_page_size, name=_search_name,
                empty_text=_empty_text, theme=_theme,
                prefix=prefix,
            )

        # --- Command handler: send search prompt ---
        async def command_handler(message: MessageCute, ctx: Context) -> None:
            key = msg_user_key(message)
            _sessions[key] = BrowseSession(page=0, search_query="")
            await message.answer(_prompt)

        # --- Text handler: receive search query, show results ---
        async def text_handler(message: MessageCute, scope: Scope) -> None:
            key = msg_user_key(message)
            session = _sessions.get(key)
            if session is None:
                return

            match message.text:
                case Some(txt):
                    search_text = txt.strip()
                case _:
                    return

            if search_text.startswith("/"):
                return

            session.search_query = search_text
            session.page = 0
            _sessions[key] = session

            result = await _do_query_and_render(scope, session)
            if result is None:
                await message.answer(f'No results for "{search_text}".')
                return
            text, kb = result
            await message.answer(text, reply_markup=kb.get_markup())

        # --- Callback handler: pagination + actions ---
        async def callback_handler(cb: CallbackQueryCute, scope: Scope) -> None:
            cb_data = parse_browse_cb(cb, _search_name)
            if cb_data is None:
                return

            key = str(cb.from_user.id)
            session = _sessions.get(key, BrowseSession())

            # Tab switching
            if cb_data.a.startswith("_tab_"):
                tab_key = cb_data.a[5:]
                session.filter_key = tab_key
                session.page = 0
                _sessions[key] = session

                result = await _do_query_and_render(scope, session)
                if result is not None:
                    text, kb = result
                    await cb.edit_text(text, reply_markup=kb.get_markup())

            elif cb_data.a in ("prev", "next"):
                session.page = cb_data.p
                _sessions[key] = session

                result = await _do_query_and_render(scope, session)
                if result is not None:
                    text, kb = result
                    await cb.edit_text(text, reply_markup=kb.get_markup())

            elif cb_data.a == "noop":
                return

            else:
                # Action button (including confirm flow via handle_action_callback)
                composer = Composer.create(scope, _agent_cls)

                async def fetch_entity() -> object | None:
                    source = await run_query_di(
                        info.entity, info.query_name, composer,
                        filter_key=session.filter_key,
                        search_query=session.search_query,
                    )
                    total = await source.count()
                    items: Sequence[object] = await source.fetch_page(0, total)
                    for item in items:
                        if get_entity_id(item, info.id_field) == cb_data.e:
                            return item
                    return None

                async def refresh(prefix: str) -> tuple[str, InlineKeyboard] | None:
                    return await _do_query_and_render(scope, session, prefix=prefix)

                await handle_action_callback(
                    cb_data, cb, info, composer, _search_name, _theme,
                    fetch_entity, refresh,
                    redirect_store=_redirect_store,
                    user_key=key,
                )

        # --- Build exposures ---

        # 1. Command handler (/search)
        cmd_trigger = TelegrindTrigger(Command(self.command), view="message")
        ctx = add_delegate_exposure(
            ctx, command_handler, cmd_trigger, self.capabilities,
            f"{info.entity.__name__}SearchOp",
            description=self.description, order=self.order,
        )

        # 2. Text handler (message without command, when session active)
        text_trigger = TelegrindTrigger(
            _HasActiveSearchSession(_sessions),
            view="message",
        )
        ctx = add_delegate_exposure(
            ctx, text_handler, text_trigger, self.capabilities,
            f"{info.entity.__name__}SearchTextOp",
        )

        # 3. Callback handler (pagination + actions)
        cb_trigger = TelegrindTrigger(
            PayloadModelRule(BrowseCB) & _BrowseNameCheck(_search_name),
            view="callback_query",
        )
        ctx = add_delegate_exposure(
            ctx, callback_handler, cb_trigger,
            (*self.capabilities, AnswerCallback()),
            f"{info.entity.__name__}SearchCbOp",
        )

        return ctx


# ═══════════════════════════════════════════════════════════════════════════════
# TGSearchPattern — the Pattern
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class TGSearchPattern:
    """Pattern: annotated entity class → search-first TG browse.

    Like tg_browse, but begins with a search prompt rather than showing
    all items. The user sends text, then browses paginated results.

        @derive(tg_search(command="search", key_node=ChatIdNode))
        @dataclass
        class ProductSearch:
            id: Annotated[int, Identity]
            name: str

            @classmethod
            @query
            async def find(cls, db: DB, search_query: str = "") -> BrowseSource: ...

            @classmethod
            @action("Buy")
            async def buy(cls, entity: ProductSearch) -> ActionResult: ...
    """

    command: str
    key_node: type
    prompt: str = "What are you looking for?"
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

        search_name = self.cb_prefix or f"s{entity.__name__[:5].lower()}"

        steps: list[Step] = [
            inspect_entity(),
            SearchSurfaceStep(
                command=self.command,
                key_node=self.key_node,
                prompt=self.prompt,
                page_size=self.page_size,
                empty_text=self.empty_text,
                capabilities=self.capabilities,
                search_name=search_name,
                description=self.description,
                order=self.order,
                theme=self.theme,
                agent_cls=self.agent_cls,
            ),
        ]
        return tuple(steps)


def tg_search(
    command: str,
    key_node: type,
    *caps: SurfaceCapability,
    prompt: str = "What are you looking for?",
    page_size: int = 5,
    empty_text: str = "Nothing found.",
    cb_prefix: str = "",
    description: str | None = None,
    order: int = 100,
    theme: UITheme | None = None,
    agent_cls: type[Agent] | None = None,
) -> TGSearchPattern:
    """Create TG search pattern.

    Args:
        command: Telegram command name (e.g., "search" -> /search).
        key_node: nodnod node for session routing (e.g., ChatIdNode).
        *caps: Surface capabilities.
        prompt: Search prompt shown after /command.
        page_size: Items per page.
        empty_text: Message when no results found.
        cb_prefix: Short prefix for callback_data (auto-generated if empty).
        description: Help description for /help generation.
        order: Sort order for /help generation.

    Returns:
        TGSearchPattern — use with @derive().

    Example::

        @derive(tg_search(command="search", key_node=ChatIdNode,
                           prompt="What are you looking for?"))
        @dataclass
        class ProductSearch:
            id: Annotated[int, Identity]
            name: str

            @classmethod
            @query
            async def find(cls, db: DB, search_query: str = "") -> BrowseSource[ProductSearch]:
                return db.search(search_query)

            @classmethod
            @format_card
            def render(cls, p: ProductSearch) -> str:
                return f"**{p.name}**"

            @classmethod
            @action("View")
            async def view(cls, entity: ProductSearch) -> ActionResult:
                return ActionResult.stay(f"Details: {entity.name}")
    """
    return TGSearchPattern(
        command=command,
        key_node=key_node,
        prompt=prompt,
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
    "tg_search",
    "TGSearchPattern",
    # Step
    "SearchSurfaceStep",
)

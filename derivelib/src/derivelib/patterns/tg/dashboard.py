"""tg_dashboard pattern — single-entity interactive card for Telegram.

Like tg_browse but without pagination. The @query method returns the entity
directly (not a BrowseSource). Ideal for dashboards, game tables, status pages.

    from derivelib.patterns.tg.dashboard import tg_dashboard, query, action, ActionResult

    @derive(tg_dashboard(command="roulette", key_node=UserId))
    @dataclass
    class RouletteTable:
        id: Annotated[int, Identity]
        bet: int = 50

        @classmethod
        @query
        async def table(cls, uid: ...) -> RouletteTable: ...

        @classmethod
        @action("Spin")
        async def spin(cls, t: RouletteTable) -> ActionResult: ...

The pattern generates:
1. A command handler (DelegateCodec) that runs @query, renders, sends
2. A callback handler (DelegateCodec) for action buttons and filter tabs
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from derivelib._dialect import ChainedPattern
    from nodnod.agent.base import Agent

from nodnod import Scope

from emergent.graph._compose import Composer

from telegrinder.bot.cute_types.callback_query import CallbackQueryCute
from telegrinder.bot.cute_types.message import MessageCute
from telegrinder.bot.rules.command import Command
from telegrinder.bot.rules.payload import PayloadModelRule
from telegrinder.tools.keyboard import InlineKeyboard

from emergent.wire.axis.surface.capabilities._base import SurfaceCapability
from emergent.wire.axis.surface.dialects.telegram import AnswerCallback
from emergent.wire.axis.surface.triggers.telegrinder import TelegrindTrigger

from derivelib._ctx import SurfaceCtx
from derivelib._derivation import Derivation, DerivationT
from derivelib.axes.schema import inspect_entity

# Re-exports from browse (user convenience)
from derivelib.patterns.tg.browse import (
    ActionResult,
    BrowseCB,
    _BrowseNameCheck,
    action,
    format_card,
    query,
    view_filter,
)
from derivelib.patterns.tg._shared import (
    add_delegate_exposure,
    get_entity_id,
    handle_action_callback,
    inspect_card_entity,
    msg_user_key,
    parse_browse_cb,
    render_card,
    run_query_di,
)
from derivelib.patterns.tg.uilib.keyboard import build_nav_keyboard
from derivelib.patterns.tg.uilib.theme import DEFAULT_THEME, UITheme


# ═══════════════════════════════════════════════════════════════════════════════
# DashboardSurfaceStep — THE surface derivation step
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class DashboardSurfaceStep:
    """Generate DelegateCodec handlers for dashboard command + callbacks.

    Creates two exposures:
    1. Command handler (dp.message) — runs @query → single entity → render → send
    2. Callback handler (dp.callback_query) — handles action buttons + filter tabs

    Key difference from BrowseSurfaceStep: @query returns entity directly,
    no pagination, no entity-by-ID search loop.
    """

    command: str
    key_node: type
    empty_text: str
    capabilities: tuple[SurfaceCapability, ...]
    dashboard_name: str
    description: str | None = None
    order: int = 100
    theme: UITheme = field(default_factory=UITheme)
    agent_cls: type[Agent] | None = None

    def derive_surface[EntityT](self, ctx: SurfaceCtx[EntityT]) -> SurfaceCtx[EntityT]:
        info = inspect_card_entity(ctx)

        _dashboard_name = self.dashboard_name
        _empty_text = self.empty_text
        _theme = self.theme
        _agent_cls = self.agent_cls

        # Session store: user_key → active_filter
        _filter_state: dict[str, str] = {}

        def _render_dashboard(
            entity_obj: object,
            prefix: str = "",
            filter_key: str = "",
        ) -> tuple[str, InlineKeyboard]:
            """Render single entity into text + keyboard (total_pages=1 hides nav)."""
            text = render_card(info.entity, info.format_name, entity_obj)
            if prefix:
                text = f"{prefix}\n\n{text}"
            eid = get_entity_id(entity_obj, info.id_field)
            kb = build_nav_keyboard(
                _dashboard_name, 0, 1, [eid], info.actions,
                theme=_theme, view_filters=info.view_filters, active_filter=filter_key,
            )
            return text, kb

        # --- Command handler (DelegateCodec) ---
        async def command_handler(message: MessageCute, scope: Scope) -> None:
            key = msg_user_key(message)
            filter_key = _filter_state.get(key, "")
            composer = Composer.create(scope, _agent_cls)

            entity_obj = await run_query_di(
                info.entity, info.query_name, composer,
                filter_key=filter_key,
            )
            if entity_obj is None:
                await message.answer(_empty_text)
                return

            text, kb = _render_dashboard(entity_obj, filter_key=filter_key)
            await message.answer(text, reply_markup=kb.get_markup())

        # --- Callback handler (DelegateCodec) ---
        async def callback_handler(cb: CallbackQueryCute, scope: Scope) -> None:
            cb_data = parse_browse_cb(cb, _dashboard_name)
            if cb_data is None:
                return

            key = str(cb.from_user.id)
            filter_key = _filter_state.get(key, "")
            composer = Composer.create(scope, _agent_cls)

            # Tab switching
            if cb_data.a.startswith("_tab_"):
                tab_key = cb_data.a[5:]
                filter_key = tab_key
                _filter_state[key] = tab_key

                entity_obj = await run_query_di(
                    info.entity, info.query_name, composer,
                    filter_key=filter_key,
                )
                if entity_obj is not None:
                    text, kb = _render_dashboard(entity_obj, filter_key=filter_key)
                    await cb.edit_text(text, reply_markup=kb.get_markup())

            elif cb_data.a == "noop":
                return

            else:
                # Action button (including confirm flow via handle_action_callback)
                async def fetch_entity() -> object | None:
                    return await run_query_di(
                        info.entity, info.query_name, composer,
                        filter_key=filter_key,
                    )

                async def refresh(prefix: str) -> tuple[str, InlineKeyboard] | None:
                    fresh = await fetch_entity()
                    if fresh is None:
                        return None
                    return _render_dashboard(fresh, prefix=prefix, filter_key=filter_key)

                await handle_action_callback(
                    cb_data, cb, info, composer, _dashboard_name, _theme,
                    fetch_entity, refresh,
                )

        # --- Build exposures ---
        cmd_trigger = TelegrindTrigger(Command(self.command), view="message")
        ctx = add_delegate_exposure(
            ctx, command_handler, cmd_trigger, self.capabilities,
            f"{info.entity.__name__}DashboardOp",
            description=self.description, order=self.order,
        )

        cb_trigger = TelegrindTrigger(
            PayloadModelRule(BrowseCB) & _BrowseNameCheck(_dashboard_name),
            view="callback_query",
        )
        ctx = add_delegate_exposure(
            ctx, callback_handler, cb_trigger,
            (*self.capabilities, AnswerCallback()),
            f"{info.entity.__name__}DashboardCbOp",
        )

        return ctx


# ═══════════════════════════════════════════════════════════════════════════════
# TGDashboardPattern — the Pattern
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class TGDashboardPattern:
    """Pattern: annotated entity class -> single-entity TG dashboard.

    Like TGBrowsePattern but @query returns entity directly, no pagination.

        @derive(tg_dashboard(command="roulette", key_node=UserId))
        @dataclass
        class RouletteTable:
            id: Annotated[int, Identity]
            ...
    """

    command: str
    key_node: type
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

        dashboard_name = self.cb_prefix or entity.__name__[:6].lower()

        steps: list[Step] = [
            inspect_entity(),
            DashboardSurfaceStep(
                command=self.command,
                key_node=self.key_node,
                empty_text=self.empty_text,
                capabilities=self.capabilities,
                dashboard_name=dashboard_name,
                description=self.description,
                order=self.order,
                theme=self.theme,
                agent_cls=self.agent_cls,
            ),
        ]
        return tuple(steps)


def tg_dashboard(
    command: str,
    key_node: type,
    empty_text: str = "Nothing found.",
    *caps: SurfaceCapability,
    cb_prefix: str = "",
    description: str | None = None,
    order: int = 100,
    theme: UITheme | None = None,
    agent_cls: type[Agent] | None = None,
) -> TGDashboardPattern:
    """Create TG dashboard pattern.

    Args:
        command: Telegram command name (e.g., "roulette" -> /roulette).
        key_node: nodnod node for session routing.
        empty_text: Message when query returns None.
        *caps: Surface capabilities.
        cb_prefix: Short prefix for callback_data (auto-generated if empty).
        description: Help description for /help generation.
        order: Sort order for /help generation.

    Returns:
        TGDashboardPattern -- use with @derive().

    Example::

        @derive(tg_dashboard(command="roulette", key_node=UserId,
                              description="Spin the wheel", order=2))
        @dataclass
        class RouletteTable:
            id: Annotated[int, Identity]
            bet: int = 50

            @classmethod
            @query
            async def table(cls, uid: ...) -> RouletteTable:
                return RouletteTable(bet=50, balance=1000)

            @classmethod
            @action("Spin")
            async def spin(cls, t: RouletteTable) -> ActionResult:
                return ActionResult.refresh("Result!")
    """
    return TGDashboardPattern(
        command=command,
        key_node=key_node,
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
    "tg_dashboard",
    "TGDashboardPattern",
    # Step
    "DashboardSurfaceStep",
    # Re-exports from browse (user convenience)
    "query",
    "action",
    "format_card",
    "view_filter",
    "ActionResult",
)

"""Telegrinder-specific surface capabilities.

Transport-specific capabilities for Telegram bot interactions.
Only the telegrinder adapter reads these; other adapters ignore them.

These capabilities use the compile_telegrinder() pattern for consistency
with the schema axis capabilities. Runtime behavior uses deliver() method.

Usage:
    from emergent.wire.axis.surface.capabilities import tg

    endpoint(runner).expose(
        TelegrindTrigger(CallbackDataMarkup("game:<id>:<cell>")),
        rrc(MoveRequest, GameBoardResponse),
        tg.EditMessage(),    # edit instead of reply
        AsDict(),            # universal: convert to dict
    )
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from telegrinder.bot.dispatch.context import Context
from telegrinder.bot.cute_types import CallbackQueryCute
from telegrinder.types.objects import InlineKeyboardMarkup

from emergent.wire.axis._capability import (
    TelegrinderHandlerContext,
    telegrinder_handler,
)
from ._base import SurfaceCapability


@dataclass(frozen=True, slots=True)
class EditMessage(SurfaceCapability):
    """Edit the original message instead of sending a new one.

    For callback queries: edit_text() instead of sending new message.
    Telegrinder adapter calls `deliver()` when this capability is present.

    Usage:
        endpoint(runner).expose(
            TelegrindTrigger(CallbackDataMarkup("action:<id>")),
            rrc(Request, Response),
            tg.EditMessage(),
        )
    """

    def compile_telegrinder(self, ctx: TelegrinderHandlerContext) -> TelegrinderHandlerContext:
        """Mark handler for message editing."""
        return telegrinder_handler(ctx, edit_message=True)

    async def deliver(
        self,
        ctx: Context,
        text: str,
        *,
        reply_markup: InlineKeyboardMarkup | None = None,
        parse_mode: str | None = None,
        **extra: Any,
    ) -> bool:
        """Edit message instead of sending new one.

        Args:
            ctx: Telegrinder Context
            text: Message text
            reply_markup: Optional inline keyboard
            parse_mode: Optional parse mode (HTML, Markdown, etc.)
            **extra: Additional params for edit_text

        Returns:
            True if delivered (edited), False if not applicable.
        """
        # Try different possible keys for callback query
        cq = ctx.get("callback_query") or ctx.get("update_cute")
        if cq is None:
            return False

        # If we got update_cute, extract callback_query from it
        if hasattr(cq, "callback_query"):
            maybe_cq = cq.callback_query
            if maybe_cq is not None:
                cq = maybe_cq.unwrap() if hasattr(maybe_cq, "unwrap") else maybe_cq

        callback_query: CallbackQueryCute = cq
        await callback_query.answer()
        await callback_query.edit_text(
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
            **extra,
        )
        return True


@dataclass(frozen=True, slots=True)
class AnswerCallback(SurfaceCapability):
    """Control callback query answer behavior.

    Usage:
        tg.AnswerCallback()                    # just answer()
        tg.AnswerCallback(show_alert=True)     # answer with alert popup
        tg.AnswerCallback(text="Processing")   # answer with toast text
    """

    text: str | None = None
    show_alert: bool = False
    cache_time: int | None = None

    def compile_telegrinder(self, ctx: TelegrinderHandlerContext) -> TelegrinderHandlerContext:
        """Mark handler for callback answering."""
        return telegrinder_handler(
            ctx,
            answer_callback=True,
            answer_callback_text=self.text,
            answer_callback_show_alert=self.show_alert,
        )


@dataclass(frozen=True, slots=True)
class Silent(SurfaceCapability):
    """Send message without notification sound.

    Usage:
        endpoint(runner).expose(
            TelegrindTrigger(Command("notify")),
            rrc(Request, Response),
            tg.Silent(),
        )
    """

    def compile_telegrinder(self, ctx: TelegrinderHandlerContext) -> TelegrinderHandlerContext:
        """Mark handler for silent message sending."""
        return telegrinder_handler(ctx, silent=True)


__all__ = (
    "EditMessage",
    "AnswerCallback",
    "Silent",
)

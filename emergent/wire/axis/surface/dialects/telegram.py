"""Telegram dialect — Telegrinder-specific capabilities.

Transport-specific capabilities for Telegram bot interactions.
Only the telegrinder adapter reads these; other adapters ignore them.

These capabilities use the compile_telegrinder() pattern for consistency
with the schema axis capabilities. Runtime behavior uses deliver() method.

Usage:
    from emergent.wire.axis.surface.dialects import telegram

    endpoint(runner).expose(
        TelegrindTrigger(CallbackDataMarkup("game:<id>:<cell>")),
        rrc(MoveRequest, GameBoardResponse),
        telegram.EditMessage(),    # edit instead of reply
        AsDict(),                  # universal: convert to dict
    )
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

from emergent.wire.axis._capability import (
    TelegrinderHandlerContext,
    telegrinder_handler,
)
from emergent.wire.axis.surface.capabilities._base import SurfaceCapability
from emergent.wire.axis.surface.enrichers._base import ScopeEnricher, EnricherNext

if TYPE_CHECKING:
    from nodnod import Scope
    from telegrinder.bot.dispatch.context import Context
    from telegrinder.types.objects import InlineKeyboardMarkup


@dataclass(frozen=True, slots=True)
class HelpMeta(SurfaceCapability):
    """Help metadata for /help generation. Capability-driven.

    Attach to any exposure to make it visible in help output.
    No HelpMeta = not visible in help.

    Usage:
        endpoint(runner).expose(
            TelegrindTrigger(Command("register")),
            rrc(RegisterRequest, TokenResponse),
            telegram.HelpMeta("Register new account", order=1),
        )
    """

    description: str
    order: int = 100
    hidden: bool = False


@dataclass(frozen=True, slots=True)
class EditMessage(SurfaceCapability):
    """Edit the original message instead of sending a new one.

    For callback queries: edit_text() instead of sending new message.
    Telegrinder adapter calls `deliver()` when this capability is present.

    Usage:
        endpoint(runner).expose(
            TelegrindTrigger(CallbackDataMarkup("action:<id>")),
            rrc(Request, Response),
            telegram.EditMessage(),
        )
    """

    def compile_telegrinder(self, ctx: TelegrinderHandlerContext) -> TelegrinderHandlerContext:
        """Mark handler for message editing."""
        return telegrinder_handler(ctx, edit_message=True, edit_message_cap=self)

    async def deliver(
        self,
        ctx: "Context",
        text: str,
        *,
        reply_markup: "InlineKeyboardMarkup | None" = None,
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

        callback_query: Any = cq  # CallbackQueryCute at runtime
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
        telegram.AnswerCallback()                    # just answer()
        telegram.AnswerCallback(show_alert=True)     # answer with alert popup
        telegram.AnswerCallback(text="Processing")   # answer with toast text
    """

    text: str | None = None
    show_alert: bool = False
    cache_time: int | None = None

    def compile_telegrinder(self, ctx: TelegrinderHandlerContext) -> TelegrinderHandlerContext:
        """Mark handler for callback answering."""
        return telegrinder_handler(
            ctx,
            answer_callback=True,
            answer_callback_cap=self,
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
            telegram.Silent(),
        )
    """

    def compile_telegrinder(self, ctx: TelegrinderHandlerContext) -> TelegrinderHandlerContext:
        """Mark handler for silent message sending."""
        return telegrinder_handler(ctx, silent=True)


@dataclass(frozen=True, slots=True)
class ParseMode(SurfaceCapability):
    """Per-handler parse mode override.

    Overrides the bot-level parse mode for this specific handler.

    Usage:
        telegram.ParseMode("HTML")
        telegram.ParseMode("MarkdownV2")
    """

    mode: str

    def compile_telegrinder(self, ctx: TelegrinderHandlerContext) -> TelegrinderHandlerContext:
        """Set parse mode for this handler."""
        return telegrinder_handler(ctx, parse_mode=self.mode)


@dataclass(frozen=True, slots=True)
class LinkPreview(SurfaceCapability):
    """Control link preview behavior.

    Usage:
        telegram.LinkPreview(disabled=True)   # disable link previews
    """

    disabled: bool = True

    def compile_telegrinder(self, ctx: TelegrinderHandlerContext) -> TelegrinderHandlerContext:
        """Set link preview behavior."""
        return telegrinder_handler(ctx, link_preview_disabled=self.disabled)


@dataclass(frozen=True, slots=True)
class ProtectContent(SurfaceCapability):
    """Prevent message forwarding and saving.

    Usage:
        telegram.ProtectContent()
    """

    def compile_telegrinder(self, ctx: TelegrinderHandlerContext) -> TelegrinderHandlerContext:
        """Mark handler for content protection."""
        return telegrinder_handler(ctx, protect_content=True)


@dataclass(frozen=True, slots=True)
class ReplyMessage(ScopeEnricher):
    """Send response as a new chat message instead of callback answer.

    For callback_query handlers where the response should appear as a regular
    chat message (not a toast popup from event.answer()).

    The enricher wraps the core handler, sends the response via API.send_message,
    and returns None so telegrinder's return manager does nothing.

    Usage:
        endpoint(runner).expose(
            TelegrindTrigger(PayloadModelRule(Model), view="callback_query"),
            stateful_codec,
            telegram.ReplyMessage(),
        )
    """

    async def enrich[R](self, call: EnricherNext[R], scope: "Scope") -> R:
        from kungfu import Some
        from telegrinder.api import API as _API
        from telegrinder.types.objects import Update as _Update

        response = await call(scope)
        if response is None:
            return None  # type: ignore[return-value]

        text = str(response)
        if not text:
            return None  # type: ignore[return-value]

        api_wrapper = scope.get(_API)
        update_wrapper = scope.get(_Update)
        if api_wrapper is None or update_wrapper is None:
            return response

        api: _API = api_wrapper.value
        update: _Update = update_wrapper.value

        match update.callback_query:
            case Some(cq):
                match cq.message:
                    case Some(msg):
                        await api.send_message(chat_id=msg.v.chat.id, text=text)
                        return None  # type: ignore[return-value]
                    case _:
                        return response
            case _:
                return response


__all__ = (
    "HelpMeta",
    "EditMessage",
    "AnswerCallback",
    "Silent",
    "ParseMode",
    "LinkPreview",
    "ProtectContent",
    "ReplyMessage",
)

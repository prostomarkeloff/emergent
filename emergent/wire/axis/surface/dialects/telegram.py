"""Telegram dialect — Telegrinder-specific capabilities.

Transport-specific capabilities for Telegram bot interactions.
Only the telegrinder adapter reads these; other adapters ignore them.

EditMessage and AnswerCallback are ScopeEnrichers — they post-process the
handler response using the standard enricher chain (same mechanism as
ResponseTransform in FastAPI). No custom wrapping in wrap functions or
register_handler needed.

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


# ═══════════════════════════════════════════════════════════════════════════════
# Callback Query Extraction
# ═══════════════════════════════════════════════════════════════════════════════


def _get_callback_query_from_scope(scope: "Scope") -> Any | None:
    """Extract CallbackQueryCute from scope via telegrinder Context.

    Returns None if no callback query is available (e.g. message handler).
    """
    from telegrinder.bot.dispatch.context import Context as _Context
    from telegrinder.bot.cute_types.callback_query import CallbackQueryCute as _CQCute

    ctx_wrapper = scope.get(_Context)
    if ctx_wrapper is None:
        return None

    ctx: _Context = ctx_wrapper.value

    cq = ctx.get("callback_query")
    if cq is not None:
        return cq

    update_cute = ctx.get("update_cute")
    if update_cute is None:
        return None

    incoming = update_cute.incoming_update
    if isinstance(incoming, _CQCute):
        return incoming

    return None


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
class EditMessage(ScopeEnricher):
    """Edit the original message instead of sending a new one.

    For callback queries: edit_text() instead of sending new message.
    Implemented as ScopeEnricher — post-processes response via the standard
    enricher chain (same mechanism as ResponseTransform in FastAPI).

    Usage:
        endpoint(runner).expose(
            TelegrindTrigger(CallbackDataMarkup("action:<id>")),
            rrc(Request, Response),
            telegram.EditMessage(),
        )
    """

    def compile_telegrinder(self, ctx: TelegrinderHandlerContext) -> TelegrinderHandlerContext:
        """Mark handler for message editing (metadata)."""
        return telegrinder_handler(ctx, edit_message=True)

    async def enrich[R](self, call: EnricherNext[R], scope: "Scope") -> R:
        response = await call(scope)

        cq = _get_callback_query_from_scope(scope)
        if cq is None:
            return response

        await cq.answer()

        if isinstance(response, str):
            await cq.edit_text(text=response)
            return None  # type: ignore[return-value]

        if isinstance(response, dict) and "text" in response:
            text = str(response.pop("text"))
            await cq.edit_text(text=text, **response)
            return None  # type: ignore[return-value]

        return response


@dataclass(frozen=True, slots=True)
class AnswerCallback(ScopeEnricher):
    """Control callback query answer behavior.

    Implemented as ScopeEnricher — answers the callback query after handler
    execution via the standard enricher chain.

    Usage:
        telegram.AnswerCallback()                    # just answer()
        telegram.AnswerCallback(show_alert=True)     # answer with alert popup
        telegram.AnswerCallback(text="Processing")   # answer with toast text
    """

    text: str | None = None
    show_alert: bool = False
    cache_time: int | None = None

    def compile_telegrinder(self, ctx: TelegrinderHandlerContext) -> TelegrinderHandlerContext:
        """Mark handler for callback answering (metadata)."""
        return telegrinder_handler(
            ctx,
            answer_callback=True,
            answer_callback_text=self.text,
            answer_callback_show_alert=self.show_alert,
        )

    async def enrich[R](self, call: EnricherNext[R], scope: "Scope") -> R:
        response = await call(scope)

        cq = _get_callback_query_from_scope(scope)
        if cq is not None:
            await cq.answer(
                text=self.text,
                show_alert=self.show_alert,
            )

        return response


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

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
from typing import Any, Protocol, TYPE_CHECKING, runtime_checkable

from emergent.wire.axis._capability import (
    TelegrinderHandlerContext,
    telegrinder_handler,
)
from emergent.wire.axis.surface.capabilities._base import SurfaceCapability
from emergent.wire.axis.surface.enrichers._base import ScopeEnricher, EnricherNext
from emergent.wire._telegrinder_compat import (
    Context as _ContextProto,
    CallbackQueryCute as _CQCuteProto,
    API as _APIProto,
    Update as _UpdateProto,
)

if TYPE_CHECKING:
    from nodnod import Scope

type RespDict = dict[str, Any]


# Runtime-checkable duck-typing protocols for telegrinder's optional cute types.
# telegrinder is an optional dependency, so its concrete classes are not importable
# here; these protocols let us probe attributes via isinstance without reflection.
@runtime_checkable
class _HasValue(Protocol):
    value: Any


@runtime_checkable
class _HasIncomingUpdate(Protocol):
    incoming_update: Any


@runtime_checkable
class _HasMessage(Protocol):
    message: Any


@runtime_checkable
class _HasV(Protocol):
    v: Any


@runtime_checkable
class _HasChat(Protocol):
    chat: Any


@runtime_checkable
class _HasId(Protocol):
    id: Any


def _unwrap_some(obj: Any) -> Any | None:
    """Extract .value from a Some instance typed as object.

    This avoids passing Some[Unknown] directly to getattr, which triggers
    reportUnknownArgumentType when Some is narrowed from object via isinstance.
    """
    return obj.value if isinstance(obj, _HasValue) else None


# ═══════════════════════════════════════════════════════════════════════════════
# Callback Query Extraction
# ═══════════════════════════════════════════════════════════════════════════════


def _get_callback_query_from_scope(scope: Scope) -> _CQCuteProto | None:
    """Extract CallbackQueryCute from scope via telegrinder Context.

    Returns None if no callback query is available (e.g. message handler).
    Uses the compat protocol for static typing; at runtime telegrinder's
    real Context is in scope.
    """
    ctx_wrapper = scope.get(_ContextProto)
    if ctx_wrapper is None:
        return None

    # nodnod scope.get() returns a wrapper whose .value holds the real object.
    # The wrapper type is opaque to pyright, so we annotate explicitly.
    ctx: _ContextProto = ctx_wrapper.value

    cq: Any | None = ctx.get("callback_query")
    if cq is not None:
        return cq

    update_cute: Any | None = ctx.get("update_cute")
    if update_cute is None:
        return None

    # telegrinder cute types expose incoming_update attribute
    incoming: Any | None = update_cute.incoming_update if isinstance(update_cute, _HasIncomingUpdate) else None
    if incoming is None:
        return None

    # Check at runtime if it's a CallbackQueryCute via class name
    # (telegrinder is an optional dep so we can't use isinstance)
    if incoming.__class__.__name__ == "CallbackQueryCute":
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

    async def enrich[R](self, call: EnricherNext[R], scope: Scope) -> R:
        response = await call(scope)

        cq = _get_callback_query_from_scope(scope)
        if cq is None:
            return response

        await cq.answer()

        if isinstance(response, str):
            await cq.edit_text(text=response)
            return None

        if isinstance(response, dict):
            resp_dict: RespDict = response
            if "text" in resp_dict:
                text = str(resp_dict.pop("text"))
                await cq.edit_text(text=text, **resp_dict)
                return None
            return response

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

    async def enrich[R](self, call: EnricherNext[R], scope: Scope) -> R:
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

    async def enrich[R](self, call: EnricherNext[R], scope: Scope) -> R:
        response = await call(scope)
        if response is None:
            return None

        text = str(response)
        if not text:
            return None

        api_wrapper = scope.get(_APIProto)
        update_wrapper = scope.get(_UpdateProto)
        if api_wrapper is None or update_wrapper is None:
            return response

        # nodnod wrapper .value is opaque to pyright
        api: _APIProto = api_wrapper.value
        update: _UpdateProto = update_wrapper.value

        cb_query: Any = update.callback_query
        # Extract .value before isinstance narrows to Some[Unknown]
        cq_value: Any | None = _unwrap_some(cb_query)
        if cq_value is None:
            return response

        msg_option: Any | None = cq_value.message if isinstance(cq_value, _HasMessage) else None
        if msg_option is None:
            return response

        msg_value: Any | None = _unwrap_some(msg_option)
        if msg_value is None:
            return response
        v: Any = msg_value.v if isinstance(msg_value, _HasV) else msg_value
        chat: Any | None = v.chat if isinstance(v, _HasChat) else None
        chat_id: Any | None = (chat.id if isinstance(chat, _HasId) else None) if chat is not None else None
        if chat_id is not None:
            await api.send_message(chat_id=chat_id, text=text)
            return None
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

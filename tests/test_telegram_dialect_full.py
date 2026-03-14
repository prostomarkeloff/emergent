"""Extended tests for surface/dialects/telegram.py — covers ReplyMessage enricher and edge cases.

The existing test_telegram_dialect.py covers HelpMeta, EditMessage, AnswerCallback, Silent,
ParseMode, LinkPreview, ProtectContent, and _get_callback_query_from_scope.

This file covers:
- ReplyMessage enricher: all branches (None response, empty text, no API/Update,
  callback_query with message, callback_query without message, no callback_query)
- AnswerCallback with cache_time
- LinkPreview disabled=False
- EditMessage and AnswerCallback compile_handler_runtime enricher registration
"""

from __future__ import annotations

import importlib.util
from unittest.mock import AsyncMock, MagicMock

import pytest

pytestmark = pytest.mark.skipif(
    not importlib.util.find_spec("telegrinder"),
    reason="telegrinder not installed",
)
from nodnod import Scope

from kungfu import Some, Nothing

from emergent.wire.axis.surface.dialects.telegram import (
    ReplyMessage,
    AnswerCallback,
    LinkPreview,
    EditMessage,
    HelpMeta,
    Silent,
    ParseMode,
    ProtectContent,
)
from emergent.wire.axis._capability import (
    TelegrinderHandlerContext,
    HandlerRuntimeContext,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers — scope mocking for ReplyMessage
# ═══════════════════════════════════════════════════════════════════════════════


def _scope_for_reply(
    api: MagicMock | None = None,
    update: MagicMock | None = None,
) -> MagicMock:
    """Build mock scope for ReplyMessage tests.

    scope.get(API) returns api_wrapper, scope.get(Update) returns update_wrapper.
    """
    from emergent.wire._telegrinder_compat import API as _APIProto, Update as _UpdateProto

    api_wrapper = None
    if api is not None:
        api_wrapper = MagicMock()
        api_wrapper.value = api

    update_wrapper = None
    if update is not None:
        update_wrapper = MagicMock()
        update_wrapper.value = update

    def get_side_effect(key: type) -> MagicMock | None:
        if key is _APIProto:
            return api_wrapper
        if key is _UpdateProto:
            return update_wrapper
        return None

    scope = MagicMock()
    scope.get = MagicMock(side_effect=get_side_effect)
    return scope


def _make_update_with_callback(chat_id: int = 123) -> MagicMock:
    """Build a mock Update with callback_query.message.v.chat.id."""
    msg_v = MagicMock()
    msg_v.chat = MagicMock()
    msg_v.chat.id = chat_id

    msg = MagicMock()
    msg.v = msg_v

    cq = MagicMock()
    cq.message = Some(msg)

    update = MagicMock()
    update.callback_query = Some(cq)
    return update


def _make_update_with_callback_no_message() -> MagicMock:
    """Build a mock Update with callback_query but no message."""
    cq = MagicMock()
    cq.message = Nothing()

    update = MagicMock()
    update.callback_query = Some(cq)
    return update


def _make_update_no_callback() -> MagicMock:
    """Build a mock Update without callback_query."""
    update = MagicMock()
    update.callback_query = Nothing()
    return update


# ═══════════════════════════════════════════════════════════════════════════════
# ReplyMessage
# ═══════════════════════════════════════════════════════════════════════════════


class TestReplyMessage:
    """Covers ReplyMessage.enrich: all branches."""

    @pytest.mark.asyncio
    async def test_none_response_returns_none(self) -> None:
        """When handler returns None, enricher returns None immediately."""
        rm = ReplyMessage()
        scope = _scope_for_reply()

        async def handler(s: Scope) -> None:
            return None

        result = await rm.enrich(handler, scope)
        assert result is None

    @pytest.mark.asyncio
    async def test_empty_text_returns_none(self) -> None:
        """When str(response) is empty, returns None."""
        rm = ReplyMessage()
        scope = _scope_for_reply()

        async def handler(s: Scope) -> str:
            return ""

        result = await rm.enrich(handler, scope)
        assert result is None

    @pytest.mark.asyncio
    async def test_no_api_in_scope_returns_response(self) -> None:
        """When API is not in scope, returns response unchanged."""
        rm = ReplyMessage()
        update = _make_update_with_callback()
        scope = _scope_for_reply(api=None, update=update)

        async def handler(s: Scope) -> str:
            return "hello"

        result = await rm.enrich(handler, scope)
        assert result == "hello"

    @pytest.mark.asyncio
    async def test_no_update_in_scope_returns_response(self) -> None:
        """When Update is not in scope, returns response unchanged."""
        rm = ReplyMessage()
        api = AsyncMock()
        scope = _scope_for_reply(api=api, update=None)

        async def handler(s: Scope) -> str:
            return "hello"

        result = await rm.enrich(handler, scope)
        assert result == "hello"

    @pytest.mark.asyncio
    async def test_callback_with_message_sends_and_returns_none(self) -> None:
        """Full path: callback_query with message sends message and returns None."""
        rm = ReplyMessage()
        api = AsyncMock()
        api.send_message = AsyncMock()
        update = _make_update_with_callback(chat_id=42)
        scope = _scope_for_reply(api=api, update=update)

        async def handler(s: Scope) -> str:
            return "hello world"

        result = await rm.enrich(handler, scope)
        assert result is None
        api.send_message.assert_awaited_once_with(chat_id=42, text="hello world")

    @pytest.mark.asyncio
    async def test_callback_without_message_returns_response(self) -> None:
        """callback_query exists but no message -- returns response."""
        rm = ReplyMessage()
        api = AsyncMock()
        update = _make_update_with_callback_no_message()
        scope = _scope_for_reply(api=api, update=update)

        async def handler(s: Scope) -> str:
            return "hello"

        result = await rm.enrich(handler, scope)
        assert result == "hello"

    @pytest.mark.asyncio
    async def test_no_callback_query_returns_response(self) -> None:
        """No callback_query in update -- returns response."""
        rm = ReplyMessage()
        api = AsyncMock()
        update = _make_update_no_callback()
        scope = _scope_for_reply(api=api, update=update)

        async def handler(s: Scope) -> str:
            return "hello"

        result = await rm.enrich(handler, scope)
        assert result == "hello"

    @pytest.mark.asyncio
    async def test_non_string_response_converted(self) -> None:
        """Non-string response is converted via str() before sending."""
        rm = ReplyMessage()
        api = AsyncMock()
        api.send_message = AsyncMock()
        update = _make_update_with_callback(chat_id=99)
        scope = _scope_for_reply(api=api, update=update)

        async def handler(s: Scope) -> int:
            return 12345

        result = await rm.enrich(handler, scope)
        assert result is None
        api.send_message.assert_awaited_once_with(chat_id=99, text="12345")

    def test_compile_handler_runtime(self) -> None:
        """ReplyMessage registers itself as an enricher."""
        rm = ReplyMessage()
        ctx = HandlerRuntimeContext()
        result = rm.compile_handler_runtime(ctx)
        assert rm in result.enrichers


# ═══════════════════════════════════════════════════════════════════════════════
# AnswerCallback — additional coverage
# ═══════════════════════════════════════════════════════════════════════════════


class TestAnswerCallbackExtended:
    def test_cache_time_attribute(self) -> None:
        """AnswerCallback stores cache_time."""
        ac = AnswerCallback(cache_time=300)
        assert ac.cache_time == 300

    def test_default_cache_time_is_none(self) -> None:
        ac = AnswerCallback()
        assert ac.cache_time is None

    def test_all_params(self) -> None:
        """AnswerCallback with all params set."""
        ac = AnswerCallback(text="Done", show_alert=True, cache_time=60)
        assert ac.text == "Done"
        assert ac.show_alert is True
        assert ac.cache_time == 60

    def test_compile_telegrinder_all_params(self) -> None:
        """compile_telegrinder sets answer_callback and related metadata."""
        ac = AnswerCallback(text="Hi", show_alert=True)
        ctx = TelegrinderHandlerContext()
        result = ac.compile_telegrinder(ctx)
        assert result.answer_callback is True
        assert result.answer_callback_text == "Hi"
        assert result.answer_callback_show_alert is True


# ═══════════════════════════════════════════════════════════════════════════════
# LinkPreview — disabled=False
# ═══════════════════════════════════════════════════════════════════════════════


class TestLinkPreviewExtended:
    def test_disabled_false(self) -> None:
        """LinkPreview(disabled=False) does not disable previews."""
        lp = LinkPreview(disabled=False)
        ctx = TelegrinderHandlerContext()
        result = lp.compile_telegrinder(ctx)
        assert result.link_preview_disabled is False

    def test_default_is_disabled(self) -> None:
        """Default LinkPreview() disables previews."""
        lp = LinkPreview()
        assert lp.disabled is True
        ctx = TelegrinderHandlerContext()
        result = lp.compile_telegrinder(ctx)
        assert result.link_preview_disabled is True


# ═══════════════════════════════════════════════════════════════════════════════
# EditMessage — compile_handler_runtime
# ═══════════════════════════════════════════════════════════════════════════════


class TestEditMessageExtended:
    def test_compile_handler_runtime_adds_to_enrichers(self) -> None:
        """EditMessage registers itself as enricher via compile_handler_runtime."""
        em = EditMessage()
        ctx = HandlerRuntimeContext()
        result = em.compile_handler_runtime(ctx)
        assert em in result.enrichers

    def test_compile_handler_runtime_preserves_existing(self) -> None:
        """Existing enrichers are preserved when adding EditMessage."""
        em = EditMessage()
        sentinel = MagicMock()
        ctx = HandlerRuntimeContext(enrichers=(sentinel,))
        result = em.compile_handler_runtime(ctx)
        assert sentinel in result.enrichers
        assert em in result.enrichers
        assert len(result.enrichers) == 2


# ═══════════════════════════════════════════════════════════════════════════════
# Multiple capabilities composition
# ═══════════════════════════════════════════════════════════════════════════════


class TestCapabilityComposition:
    def test_multiple_capabilities_compose(self) -> None:
        """Multiple capabilities fold correctly onto a single context."""
        ctx = TelegrinderHandlerContext()
        ctx = EditMessage().compile_telegrinder(ctx)
        ctx = Silent().compile_telegrinder(ctx)
        ctx = ParseMode(mode="HTML").compile_telegrinder(ctx)
        ctx = LinkPreview(disabled=True).compile_telegrinder(ctx)
        ctx = ProtectContent().compile_telegrinder(ctx)

        assert ctx.edit_message is True
        assert ctx.silent is True
        assert ctx.parse_mode == "HTML"
        assert ctx.link_preview_disabled is True
        assert ctx.protect_content is True

    def test_answer_callback_after_edit(self) -> None:
        """Both EditMessage and AnswerCallback can be set on same context."""
        ctx = TelegrinderHandlerContext()
        ctx = EditMessage().compile_telegrinder(ctx)
        ctx = AnswerCallback(text="Done", show_alert=True).compile_telegrinder(ctx)

        assert ctx.edit_message is True
        assert ctx.answer_callback is True
        assert ctx.answer_callback_text == "Done"
        assert ctx.answer_callback_show_alert is True


# ═══════════════════════════════════════════════════════════════════════════════
# HelpMeta — frozen, order, hidden
# ═══════════════════════════════════════════════════════════════════════════════


class TestHelpMetaExtended:
    def test_frozen(self) -> None:
        """HelpMeta is frozen dataclass."""
        h = HelpMeta(description="Test")
        with pytest.raises(AttributeError):
            h.description = "Changed"  # type: ignore[misc]

    def test_order_comparison(self) -> None:
        """HelpMeta instances can be sorted by order."""
        h1 = HelpMeta(description="First", order=1)
        h2 = HelpMeta(description="Second", order=2)
        h3 = HelpMeta(description="Third", order=100)
        sorted_items = sorted([h3, h1, h2], key=lambda h: h.order)
        assert sorted_items[0].description == "First"
        assert sorted_items[1].description == "Second"
        assert sorted_items[2].description == "Third"

"""Tests for surface/dialects/telegram.py — HelpMeta, EditMessage, AnswerCallback, Silent, etc."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from nodnod import Scope

from emergent.wire.axis.surface.dialects.telegram import (
    HelpMeta,
    EditMessage,
    AnswerCallback,
    Silent,
    ParseMode,
    LinkPreview,
    ProtectContent,
    _get_callback_query_from_scope,  # pyright: ignore[reportPrivateUsage] - testing private helper
)
from emergent.wire.axis._capability import (
    TelegrinderHandlerContext,
    HandlerRuntimeContext,
)
from emergent.wire.axis.surface.enrichers import chain_enrichers


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers — scope mocking
# ═══════════════════════════════════════════════════════════════════════════════


def _scope_with_cq(cq: MagicMock) -> MagicMock:
    """Build mock scope whose Context.get("callback_query") returns *cq*."""
    from telegrinder.bot.dispatch.context import Context as _Context

    tg_ctx = MagicMock()
    tg_ctx.get = MagicMock(side_effect=lambda key: cq if key == "callback_query" else None)  # pyright: ignore[reportUnknownLambdaType] - MagicMock.get side_effect lambda

    ctx_wrapper = MagicMock()
    ctx_wrapper.value = tg_ctx

    scope = MagicMock()
    scope.get = MagicMock(side_effect=lambda key: ctx_wrapper if key is _Context else None)  # pyright: ignore[reportUnknownLambdaType] - MagicMock.get side_effect lambda
    return scope


def _scope_with_update_cute(incoming: object) -> MagicMock:
    """Build mock scope whose Context.get("update_cute").incoming_update is *incoming*."""
    from telegrinder.bot.dispatch.context import Context as _Context

    update_cute = MagicMock()
    update_cute.incoming_update = incoming

    tg_ctx = MagicMock()
    tg_ctx.get = MagicMock(
        side_effect=lambda key: update_cute if key == "update_cute" else None,  # pyright: ignore[reportUnknownLambdaType] - MagicMock.get side_effect lambda
    )

    ctx_wrapper = MagicMock()
    ctx_wrapper.value = tg_ctx

    scope = MagicMock()
    scope.get = MagicMock(side_effect=lambda key: ctx_wrapper if key is _Context else None)  # pyright: ignore[reportUnknownLambdaType] - MagicMock.get side_effect lambda
    return scope


def _scope_no_context() -> MagicMock:
    """Build mock scope that has no telegrinder Context."""
    scope = MagicMock()
    scope.get = MagicMock(return_value=None)
    return scope


def _scope_no_cq() -> MagicMock:
    """Build mock scope with Context but no callback query anywhere."""
    from telegrinder.bot.dispatch.context import Context as _Context

    tg_ctx = MagicMock()
    tg_ctx.get = MagicMock(return_value=None)

    ctx_wrapper = MagicMock()
    ctx_wrapper.value = tg_ctx

    scope = MagicMock()
    scope.get = MagicMock(side_effect=lambda key: ctx_wrapper if key is _Context else None)  # pyright: ignore[reportUnknownLambdaType] - MagicMock.get side_effect lambda
    return scope


def _make_cq() -> MagicMock:
    """Build a mock CallbackQueryCute with async answer/edit_text."""
    cq = MagicMock()
    cq.answer = AsyncMock()
    cq.edit_text = AsyncMock()
    return cq


# ═══════════════════════════════════════════════════════════════════════════════
# _get_callback_query_from_scope
# ═══════════════════════════════════════════════════════════════════════════════


class TestGetCallbackQueryFromScope:
    def test_no_context_in_scope(self) -> None:
        scope = _scope_no_context()
        assert _get_callback_query_from_scope(scope) is None

    def test_via_callback_query_key(self) -> None:
        cq = _make_cq()
        scope = _scope_with_cq(cq)
        assert _get_callback_query_from_scope(scope) is cq

    def test_via_update_cute_incoming(self) -> None:
        from telegrinder.bot.cute_types.callback_query import CallbackQueryCute

        cq = MagicMock(spec=CallbackQueryCute)
        scope = _scope_with_update_cute(cq)
        assert _get_callback_query_from_scope(scope) is cq

    def test_update_cute_not_callback_query(self) -> None:
        """update_cute exists but incoming is a MessageCute, not CallbackQueryCute."""
        from telegrinder.bot.cute_types.message import MessageCute

        msg = MagicMock(spec=MessageCute)
        scope = _scope_with_update_cute(msg)
        assert _get_callback_query_from_scope(scope) is None

    def test_no_callback_query_no_update_cute(self) -> None:
        scope = _scope_no_cq()
        assert _get_callback_query_from_scope(scope) is None


# ═══════════════════════════════════════════════════════════════════════════════
# HelpMeta
# ═══════════════════════════════════════════════════════════════════════════════


class TestHelpMeta:
    def test_basic_creation(self) -> None:
        h = HelpMeta(description="Register new account", order=1)
        assert h.description == "Register new account"
        assert h.order == 1
        assert h.hidden is False

    def test_hidden(self) -> None:
        h = HelpMeta(description="Admin", hidden=True)
        assert h.hidden is True

    def test_default_order(self) -> None:
        h = HelpMeta(description="Test")
        assert h.order == 100


# ═══════════════════════════════════════════════════════════════════════════════
# EditMessage
# ═══════════════════════════════════════════════════════════════════════════════


class TestEditMessage:
    def test_compile_telegrinder(self) -> None:
        em = EditMessage()
        ctx = TelegrinderHandlerContext()
        result = em.compile_telegrinder(ctx)
        assert result.edit_message is True

    def test_is_enricher(self) -> None:
        """EditMessage registers itself as an enricher via compile_handler_runtime."""
        em = EditMessage()
        rt_ctx = HandlerRuntimeContext()
        result = em.compile_handler_runtime(rt_ctx)
        assert em in result.enrichers

    # --- enrich: dict with "text" → edit + return None ---

    @pytest.mark.asyncio
    async def test_enrich_dict_with_text(self) -> None:
        em = EditMessage()
        cq = _make_cq()
        scope = _scope_with_cq(cq)

        async def handler(s: Scope) -> dict[str, str]:
            return {"text": "Hello"}

        result = await em.enrich(handler, scope)
        assert result is None
        cq.answer.assert_awaited_once()
        cq.edit_text.assert_awaited_once_with(text="Hello")

    @pytest.mark.asyncio
    async def test_enrich_dict_with_text_and_extras(self) -> None:
        """Extra dict keys are forwarded to edit_text as kwargs."""
        em = EditMessage()
        cq = _make_cq()
        scope = _scope_with_cq(cq)

        async def handler(s: Scope) -> dict[str, object]:
            return {"text": "Hello", "parse_mode": "HTML"}

        result = await em.enrich(handler, scope)
        assert result is None
        cq.edit_text.assert_awaited_once_with(text="Hello", parse_mode="HTML")

    # --- enrich: str response → edit + return None ---

    @pytest.mark.asyncio
    async def test_enrich_str_response(self) -> None:
        em = EditMessage()
        cq = _make_cq()
        scope = _scope_with_cq(cq)

        async def handler(s: Scope) -> str:
            return "Hello"

        result = await em.enrich(handler, scope)
        assert result is None
        cq.answer.assert_awaited_once()
        cq.edit_text.assert_awaited_once_with(text="Hello")

    # --- enrich: dict WITHOUT "text" → answer + passthrough ---

    @pytest.mark.asyncio
    async def test_enrich_dict_without_text(self) -> None:
        em = EditMessage()
        cq = _make_cq()
        scope = _scope_with_cq(cq)

        response = {"data": 42}

        async def handler(s: Scope) -> dict[str, int]:
            return response

        result = await em.enrich(handler, scope)
        assert result is response
        cq.answer.assert_awaited_once()
        cq.edit_text.assert_not_awaited()

    # --- enrich: non-str/non-dict response → answer + passthrough ---

    @pytest.mark.asyncio
    async def test_enrich_non_str_non_dict(self) -> None:
        em = EditMessage()
        cq = _make_cq()
        scope = _scope_with_cq(cq)

        async def handler(s: Scope) -> int:
            return 42

        result = await em.enrich(handler, scope)
        assert result == 42
        cq.answer.assert_awaited_once()
        cq.edit_text.assert_not_awaited()

    # --- enrich: no callback query → passthrough, no answer ---

    @pytest.mark.asyncio
    async def test_enrich_no_callback_query(self) -> None:
        em = EditMessage()
        scope = _scope_no_cq()

        async def handler(s: Scope) -> str:
            return "Hello"

        result = await em.enrich(handler, scope)
        assert result == "Hello"

    @pytest.mark.asyncio
    async def test_enrich_no_context(self) -> None:
        em = EditMessage()
        scope = _scope_no_context()

        async def handler(s: Scope) -> str:
            return "Hello"

        result = await em.enrich(handler, scope)
        assert result == "Hello"


# ═══════════════════════════════════════════════════════════════════════════════
# AnswerCallback
# ═══════════════════════════════════════════════════════════════════════════════


class TestAnswerCallback:
    def test_default(self) -> None:
        ac = AnswerCallback()
        assert ac.text is None
        assert ac.show_alert is False

    def test_with_text(self) -> None:
        ac = AnswerCallback(text="Processing")
        assert ac.text == "Processing"

    def test_with_alert(self) -> None:
        ac = AnswerCallback(show_alert=True)
        assert ac.show_alert is True

    def test_compile_telegrinder(self) -> None:
        ac = AnswerCallback(text="Done", show_alert=True)
        ctx = TelegrinderHandlerContext()
        result = ac.compile_telegrinder(ctx)
        assert result.answer_callback is True
        assert result.answer_callback_text == "Done"
        assert result.answer_callback_show_alert is True

    def test_is_enricher(self) -> None:
        """AnswerCallback registers itself as an enricher via compile_handler_runtime."""
        ac = AnswerCallback()
        rt_ctx = HandlerRuntimeContext()
        result = ac.compile_handler_runtime(rt_ctx)
        assert ac in result.enrichers

    @pytest.mark.asyncio
    async def test_enrich_with_callback_query(self) -> None:
        ac = AnswerCallback(text="Done", show_alert=True)
        cq = _make_cq()
        scope = _scope_with_cq(cq)

        async def handler(s: Scope) -> str:
            return "response"

        result = await ac.enrich(handler, scope)
        assert result == "response"
        cq.answer.assert_awaited_once_with(text="Done", show_alert=True)

    @pytest.mark.asyncio
    async def test_enrich_default_params(self) -> None:
        """Default AnswerCallback answers with text=None, show_alert=False."""
        ac = AnswerCallback()
        cq = _make_cq()
        scope = _scope_with_cq(cq)

        async def handler(s: Scope) -> str:
            return "ok"

        result = await ac.enrich(handler, scope)
        assert result == "ok"
        cq.answer.assert_awaited_once_with(text=None, show_alert=False)

    @pytest.mark.asyncio
    async def test_enrich_no_callback_query(self) -> None:
        ac = AnswerCallback(text="Done")
        scope = _scope_no_cq()

        async def handler(s: Scope) -> str:
            return "response"

        result = await ac.enrich(handler, scope)
        assert result == "response"

    @pytest.mark.asyncio
    async def test_enrich_no_context(self) -> None:
        ac = AnswerCallback()
        scope = _scope_no_context()

        async def handler(s: Scope) -> str:
            return "response"

        result = await ac.enrich(handler, scope)
        assert result == "response"


# ═══════════════════════════════════════════════════════════════════════════════
# Enricher Chain Composition
# ═══════════════════════════════════════════════════════════════════════════════


class TestEnricherChain:
    """Verify EditMessage and AnswerCallback compose correctly in chain."""

    @pytest.mark.asyncio
    async def test_answer_then_edit(self) -> None:
        """AnswerCallback runs, then EditMessage edits the response."""
        ac = AnswerCallback(text="Processing")
        em = EditMessage()
        cq = _make_cq()
        scope = _scope_with_cq(cq)

        async def core(s: Scope) -> dict[str, str]:
            return {"text": "Done"}

        # chain_enrichers wraps core with enrichers in order
        chained = chain_enrichers((ac, em), core)
        result = await chained(scope)

        # EditMessage edits and returns None
        assert result is None
        # AnswerCallback answers first (outermost)
        cq.answer.assert_awaited()
        cq.edit_text.assert_awaited_once_with(text="Done")

    @pytest.mark.asyncio
    async def test_chain_no_callback_query(self) -> None:
        """Both enrichers are no-ops when there's no callback query."""
        ac = AnswerCallback(text="Done")
        em = EditMessage()
        scope = _scope_no_cq()

        async def core(s: Scope) -> str:
            return "hello"

        chained = chain_enrichers((ac, em), core)
        result = await chained(scope)
        assert result == "hello"


# ═══════════════════════════════════════════════════════════════════════════════
# fold_tg_handler_ctx — verify after cap-ref removal
# ═══════════════════════════════════════════════════════════════════════════════


class TestFoldTgHandlerCtx:
    """Verify fold_tg_handler_ctx works correctly after removing cap refs."""

    def test_fold_edit_message(self) -> None:
        from emergent.wire.compile.targets.telegrinder import fold_tg_handler_ctx

        em = EditMessage()
        ctx = fold_tg_handler_ctx((em,))
        assert ctx.edit_message is True
        assert not hasattr(ctx, "edit_message_cap") or not hasattr(TelegrinderHandlerContext, "edit_message_cap")

    def test_fold_answer_callback(self) -> None:
        from emergent.wire.compile.targets.telegrinder import fold_tg_handler_ctx

        ac = AnswerCallback(text="Hi", show_alert=True)
        ctx = fold_tg_handler_ctx((ac,))
        assert ctx.answer_callback is True
        assert ctx.answer_callback_text == "Hi"
        assert ctx.answer_callback_show_alert is True

    def test_fold_multiple(self) -> None:
        from emergent.wire.compile.targets.telegrinder import fold_tg_handler_ctx

        caps = (
            EditMessage(),
            AnswerCallback(text="Hi"),
            Silent(),
            ParseMode(mode="HTML"),
        )
        ctx = fold_tg_handler_ctx(caps)
        assert ctx.edit_message is True
        assert ctx.answer_callback is True
        assert ctx.answer_callback_text == "Hi"
        assert ctx.silent is True
        assert ctx.parse_mode == "HTML"

    def test_fold_empty(self) -> None:
        from emergent.wire.compile.targets.telegrinder import fold_tg_handler_ctx

        ctx = fold_tg_handler_ctx(())
        assert ctx.edit_message is False
        assert ctx.answer_callback is False
        assert ctx.silent is False
        assert ctx.parse_mode is None


# ═══════════════════════════════════════════════════════════════════════════════
# Silent
# ═══════════════════════════════════════════════════════════════════════════════


class TestSilent:
    def test_compile_telegrinder(self) -> None:
        s = Silent()
        ctx = TelegrinderHandlerContext()
        result = s.compile_telegrinder(ctx)
        assert result.silent is True


# ═══════════════════════════════════════════════════════════════════════════════
# ParseMode
# ═══════════════════════════════════════════════════════════════════════════════


class TestParseMode:
    def test_html(self) -> None:
        pm = ParseMode(mode="HTML")
        ctx = TelegrinderHandlerContext()
        result = pm.compile_telegrinder(ctx)
        assert result.parse_mode == "HTML"

    def test_markdown(self) -> None:
        pm = ParseMode(mode="MarkdownV2")
        ctx = TelegrinderHandlerContext()
        result = pm.compile_telegrinder(ctx)
        assert result.parse_mode == "MarkdownV2"


# ═══════════════════════════════════════════════════════════════════════════════
# LinkPreview
# ═══════════════════════════════════════════════════════════════════════════════


class TestLinkPreview:
    def test_disabled(self) -> None:
        lp = LinkPreview(disabled=True)
        ctx = TelegrinderHandlerContext()
        result = lp.compile_telegrinder(ctx)
        assert result.link_preview_disabled is True


# ═══════════════════════════════════════════════════════════════════════════════
# ProtectContent
# ═══════════════════════════════════════════════════════════════════════════════


class TestProtectContent:
    def test_compile_telegrinder(self) -> None:
        pc = ProtectContent()
        ctx = TelegrinderHandlerContext()
        result = pc.compile_telegrinder(ctx)
        assert result.protect_content is True

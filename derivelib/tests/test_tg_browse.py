"""Tests for derivelib.patterns.tg_browse — paginated TG entity browsing."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Annotated

from kungfu import Ok, Result

from emergent.wire.axis.schema import Identity
from emergent.wire.axis.surface.codecs.delegate import DelegateCodec
from emergent.wire.axis.surface.triggers.telegrinder import TelegrindTrigger
from telegrinder.bot.rules.command import Command
from telegrinder.bot.rules.payload import PayloadModelRule

from derivelib._derive import derive, derive_endpoints
from derivelib._errors import DomainError
from derivelib.patterns.tg.browse import (
    ACTION_ATTR,
    FORMAT_CARD_ATTR,
    QUERY_ATTR,
    ActionResult,
    BrowseCB,
    BrowseSession,
    BrowseSource,
    BrowseSurfaceStep,
    ListBrowseSource,
    TGBrowsePattern,
    _ActionEntry,
    _default_render_card,
    _find_actions,
    _find_format_card,
    _find_query_method,
    action,
    format_card,
    query,
    tg_browse,
)
from derivelib.patterns.tg.uilib.keyboard import build_nav_keyboard
from derivelib.patterns.tg.uilib.theme import DEFAULT_THEME


# ═══════════════════════════════════════════════════════════════════════════════
# ActionResult
# ═══════════════════════════════════════════════════════════════════════════════


class TestActionResult:
    def test_refresh(self) -> None:
        ar = ActionResult.refresh("Updated!")
        assert ar.kind == "refresh"
        assert ar.message == "Updated!"

    def test_refresh_no_message(self) -> None:
        ar = ActionResult.refresh()
        assert ar.kind == "refresh"
        assert ar.message == ""

    def test_redirect(self) -> None:
        ar = ActionResult.redirect("tasks", 42)
        assert ar.kind == "redirect"
        assert ar.command == "tasks"
        assert ar.redirect_context == (42,)

    def test_stay(self) -> None:
        ar = ActionResult.stay("Info shown")
        assert ar.kind == "stay"
        assert ar.message == "Info shown"

    def test_confirm(self) -> None:
        ar = ActionResult.confirm("Delete this?")
        assert ar.kind == "confirm"
        assert ar.confirm_prompt == "Delete this?"


# ═══════════════════════════════════════════════════════════════════════════════
# ListBrowseSource
# ═══════════════════════════════════════════════════════════════════════════════


class TestListBrowseSource:
    def test_count(self) -> None:
        src = ListBrowseSource(items=[1, 2, 3])
        assert asyncio.run(src.count()) == 3

    def test_fetch_page(self) -> None:
        src = ListBrowseSource(items=[10, 20, 30, 40, 50])
        page = asyncio.run(src.fetch_page(1, 2))
        assert list(page) == [20, 30]

    def test_fetch_page_beyond_end(self) -> None:
        src = ListBrowseSource(items=[1, 2])
        page = asyncio.run(src.fetch_page(5, 3))
        assert list(page) == []

    def test_empty_source(self) -> None:
        src: ListBrowseSource[int] = ListBrowseSource(items=[])
        assert asyncio.run(src.count()) == 0


# ═══════════════════════════════════════════════════════════════════════════════
# BrowseCB
# ═══════════════════════════════════════════════════════════════════════════════


class TestBrowseCB:
    def test_construction(self) -> None:
        cb = BrowseCB(b="tasks", a="next", e=0, p=2)
        assert cb.b == "tasks"
        assert cb.a == "next"
        assert cb.e == 0
        assert cb.p == 2

    def test_defaults(self) -> None:
        cb = BrowseCB(b="t", a="prev")
        assert cb.e == 0
        assert cb.p == 0


# ═══════════════════════════════════════════════════════════════════════════════
# BrowseSession
# ═══════════════════════════════════════════════════════════════════════════════


class TestBrowseSession:
    def test_defaults(self) -> None:
        s = BrowseSession()
        assert s.page == 0

    def test_mutation(self) -> None:
        s = BrowseSession()
        s.page = 3
        assert s.page == 3


# ═══════════════════════════════════════════════════════════════════════════════
# Decorators: @query, @action, @format_card
# ═══════════════════════════════════════════════════════════════════════════════


class TestQueryDecorator:
    def test_sets_attr(self) -> None:
        @query
        async def my_query():
            pass

        assert getattr(my_query, QUERY_ATTR) is True

    def test_preserves_function(self) -> None:
        @query
        async def my_query():
            return 42

        assert my_query.__name__ == "my_query"


class TestActionDecorator:
    def test_sets_label(self) -> None:
        @action("Open")
        async def open_task():
            pass

        assert getattr(open_task, ACTION_ATTR) == "Open"

    def test_different_labels(self) -> None:
        @action("Delete")
        async def delete_task():
            pass

        assert getattr(delete_task, ACTION_ATTR) == "Delete"


class TestFormatCardDecorator:
    def test_sets_attr(self) -> None:
        @format_card
        def render(entity):
            return str(entity)

        assert getattr(render, FORMAT_CARD_ATTR) is True


# ═══════════════════════════════════════════════════════════════════════════════
# Entity scanning: _find_query_method, _find_actions, _find_format_card
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class SampleCard:
    id: int
    title: str

    @classmethod
    @query
    async def my_tasks(cls) -> BrowseSource[SampleCard]:
        return ListBrowseSource(items=[])

    @classmethod
    @action("Open")
    async def open_task(cls, entity: SampleCard) -> ActionResult:
        return ActionResult.stay()

    @classmethod
    @action("Delete")
    async def delete_task(cls, entity: SampleCard) -> ActionResult:
        return ActionResult.confirm("Sure?")

    @classmethod
    @format_card
    def render(cls, entity: SampleCard) -> str:
        return f"[{entity.id}] {entity.title}"


class TestFindQueryMethod:
    def test_finds_query(self) -> None:
        name = _find_query_method(SampleCard)
        assert name == "my_tasks"

    def test_returns_none_when_missing(self) -> None:
        @dataclass
        class NoQuery:
            value: int = 0

        assert _find_query_method(NoQuery) is None


class TestFindActions:
    def test_finds_all_actions(self) -> None:
        actions = _find_actions(SampleCard)
        labels = {a.label for a in actions}
        assert "Open" in labels
        assert "Delete" in labels

    def test_returns_empty_when_none(self) -> None:
        @dataclass
        class NoActions:
            value: int = 0

        assert _find_actions(NoActions) == []

    def test_action_entry_has_method_name(self) -> None:
        actions = _find_actions(SampleCard)
        names = {a.method_name for a in actions}
        assert "open_task" in names
        assert "delete_task" in names


class TestFindFormatCard:
    def test_finds_format_card(self) -> None:
        name = _find_format_card(SampleCard)
        assert name == "render"

    def test_returns_none_when_missing(self) -> None:
        @dataclass
        class NoFormat:
            value: int = 0

        assert _find_format_card(NoFormat) is None


# ═══════════════════════════════════════════════════════════════════════════════
# _default_render_card
# ═══════════════════════════════════════════════════════════════════════════════


class TestDefaultRenderCard:
    def test_renders_dataclass_fields(self) -> None:
        @dataclass
        class Item:
            id: int
            name: str

        text = _default_render_card(Item(id=1, name="Test"))
        assert "id: 1" in text
        assert "name: Test" in text

    def test_skips_none_fields(self) -> None:
        @dataclass
        class Item:
            id: int
            desc: str | None = None

        text = _default_render_card(Item(id=1))
        assert "id: 1" in text
        assert "desc" not in text

    def test_non_dataclass_uses_str(self) -> None:
        text = _default_render_card("plain string")
        assert text == "plain string"


# ═══════════════════════════════════════════════════════════════════════════════
# _build_nav_keyboard
# ═══════════════════════════════════════════════════════════════════════════════


class TestBuildNavKeyboard:
    def test_first_page_no_prev(self) -> None:
        kb = build_nav_keyboard("t", page=0, total_pages=3, entity_ids=[1], actions=[], theme=DEFAULT_THEME)
        # Should not have prev button on first page
        markup = kb.get_markup()
        # Get all button texts from the keyboard
        texts = []
        for row in markup.inline_keyboard:
            for btn in row:
                texts.append(btn.text)
        assert "◀️ Prev" not in texts
        assert "Next ▶️" in texts

    def test_last_page_no_next(self) -> None:
        kb = build_nav_keyboard("t", page=2, total_pages=3, entity_ids=[1], actions=[], theme=DEFAULT_THEME)
        markup = kb.get_markup()
        texts = []
        for row in markup.inline_keyboard:
            for btn in row:
                texts.append(btn.text)
        assert "◀️ Prev" in texts
        assert "Next ▶️" not in texts

    def test_middle_page_both_buttons(self) -> None:
        kb = build_nav_keyboard("t", page=1, total_pages=3, entity_ids=[1], actions=[], theme=DEFAULT_THEME)
        markup = kb.get_markup()
        texts = []
        for row in markup.inline_keyboard:
            for btn in row:
                texts.append(btn.text)
        assert "◀️ Prev" in texts
        assert "Next ▶️" in texts

    def test_page_counter_shown(self) -> None:
        kb = build_nav_keyboard("t", page=1, total_pages=5, entity_ids=[1], actions=[], theme=DEFAULT_THEME)
        markup = kb.get_markup()
        texts = []
        for row in markup.inline_keyboard:
            for btn in row:
                texts.append(btn.text)
        assert "2/5" in texts

    def test_action_buttons_added(self) -> None:
        actions = [_ActionEntry(label="Open", method_name="open_task")]
        kb = build_nav_keyboard("t", page=0, total_pages=1, entity_ids=[1], actions=actions, theme=DEFAULT_THEME)
        markup = kb.get_markup()
        texts = []
        for row in markup.inline_keyboard:
            for btn in row:
                texts.append(btn.text)
        assert "Open" in texts


# ═══════════════════════════════════════════════════════════════════════════════
# TGBrowsePattern
# ═══════════════════════════════════════════════════════════════════════════════


class FakeProvider:
    pass


class FakeKeyNode:
    pass


class TestTGBrowsePattern:
    def test_construction(self) -> None:
        p = TGBrowsePattern(
            command="tasks",
            provider_node=FakeProvider,
            key_node=FakeKeyNode,
        )
        assert p.command == "tasks"
        assert p.page_size == 5
        assert p.empty_text == "Nothing found."

    def test_compile_returns_derivation(self) -> None:
        @dataclass
        class Card:
            id: int

            @classmethod
            @query
            async def items(cls) -> BrowseSource[Card]:
                return ListBrowseSource(items=[])

        p = TGBrowsePattern(command="cards", provider_node=FakeProvider, key_node=FakeKeyNode)
        derivation = p.compile(Card)
        assert len(derivation) == 2  # inspect_entity + BrowseSurfaceStep

    def test_compile_second_step_is_browse_surface(self) -> None:
        @dataclass
        class Card:
            id: int

            @classmethod
            @query
            async def items(cls) -> BrowseSource[Card]:
                return ListBrowseSource(items=[])

        p = TGBrowsePattern(command="cards", provider_node=FakeProvider, key_node=FakeKeyNode)
        derivation = p.compile(Card)
        assert isinstance(derivation[1], BrowseSurfaceStep)

    def test_tg_browse_factory(self) -> None:
        p = tg_browse(command="tasks", provider_node=FakeProvider, key_node=FakeKeyNode, page_size=10)
        assert isinstance(p, TGBrowsePattern)
        assert p.page_size == 10

    def test_custom_empty_text(self) -> None:
        p = tg_browse(command="x", provider_node=FakeProvider, key_node=FakeKeyNode, empty_text="No items.")
        assert p.empty_text == "No items."

    def test_cb_prefix(self) -> None:
        p = tg_browse(command="x", provider_node=FakeProvider, key_node=FakeKeyNode, cb_prefix="tsk")
        assert p.cb_prefix == "tsk"


# ═══════════════════════════════════════════════════════════════════════════════
# End-to-end: derive + compile
# ═══════════════════════════════════════════════════════════════════════════════


class TestEndToEnd:
    def test_browse_compiles_to_two_exposures(self) -> None:
        @dataclass
        class TaskCard:
            id: Annotated[int, Identity]
            title: str = ""

            @classmethod
            @query
            async def all_tasks(cls) -> BrowseSource[TaskCard]:
                return ListBrowseSource(items=[])

        pattern = tg_browse(command="tasks", provider_node=FakeProvider, key_node=FakeKeyNode)
        endpoints = derive_endpoints(TaskCard, pattern)
        assert len(endpoints) == 1
        assert len(endpoints[0].exposures) == 2

    def test_exposures_have_correct_views(self) -> None:
        @dataclass
        class Card:
            id: Annotated[int, Identity]

            @classmethod
            @query
            async def items(cls) -> BrowseSource[Card]:
                return ListBrowseSource(items=[])

        endpoints = derive_endpoints(
            Card,
            tg_browse(command="cards", provider_node=FakeProvider, key_node=FakeKeyNode),
        )
        views = {e.trigger.view for e in endpoints[0].exposures}
        assert "message" in views
        assert "callback_query" in views

    def test_codecs_are_delegate(self) -> None:
        @dataclass
        class Card:
            id: Annotated[int, Identity]

            @classmethod
            @query
            async def items(cls) -> BrowseSource[Card]:
                return ListBrowseSource(items=[])

        endpoints = derive_endpoints(
            Card,
            tg_browse(command="cards", provider_node=FakeProvider, key_node=FakeKeyNode),
        )
        for exp in endpoints[0].exposures:
            assert isinstance(exp.codec, DelegateCodec)

    def test_message_trigger_is_command(self) -> None:
        @dataclass
        class Card:
            id: Annotated[int, Identity]

            @classmethod
            @query
            async def items(cls) -> BrowseSource[Card]:
                return ListBrowseSource(items=[])

        endpoints = derive_endpoints(
            Card,
            tg_browse(command="cards", provider_node=FakeProvider, key_node=FakeKeyNode),
        )
        msg_exp = next(e for e in endpoints[0].exposures if e.trigger.view == "message")
        assert isinstance(msg_exp.trigger.rules[0], Command)

    def test_callback_trigger_is_payload_model(self) -> None:
        @dataclass
        class Card:
            id: Annotated[int, Identity]

            @classmethod
            @query
            async def items(cls) -> BrowseSource[Card]:
                return ListBrowseSource(items=[])

        endpoints = derive_endpoints(
            Card,
            tg_browse(command="cards", provider_node=FakeProvider, key_node=FakeKeyNode),
        )
        cb_exp = next(e for e in endpoints[0].exposures if e.trigger.view == "callback_query")
        from telegrinder.bot.rules.abc import AndRule
        rule = cb_exp.trigger.rules[0]
        assert isinstance(rule, AndRule)
        assert isinstance(rule.rules[0], PayloadModelRule)

    def test_with_actions(self) -> None:
        @dataclass
        class Card:
            id: Annotated[int, Identity]
            title: str = ""

            @classmethod
            @query
            async def items(cls) -> BrowseSource[Card]:
                return ListBrowseSource(items=[])

            @classmethod
            @action("Open")
            async def open_card(cls, entity: Card) -> ActionResult:
                return ActionResult.stay()

        endpoints = derive_endpoints(
            Card,
            tg_browse(command="cards", provider_node=FakeProvider, key_node=FakeKeyNode),
        )
        # Should still compile with actions
        assert len(endpoints[0].exposures) == 2

    def test_with_format_card(self) -> None:
        @dataclass
        class Card:
            id: Annotated[int, Identity]
            title: str = ""

            @classmethod
            @query
            async def items(cls) -> BrowseSource[Card]:
                return ListBrowseSource(items=[])

            @classmethod
            @format_card
            def render(cls, entity: Card) -> str:
                return f"#{entity.id}: {entity.title}"

        endpoints = derive_endpoints(
            Card,
            tg_browse(command="cards", provider_node=FakeProvider, key_node=FakeKeyNode),
        )
        assert len(endpoints[0].exposures) == 2

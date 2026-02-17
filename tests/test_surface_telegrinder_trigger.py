"""Tests for TelegrinderTrigger and its TelegrindTrigger alias.

Covers construction, default view, custom view, frozen immutability,
and the backward-compatibility alias.
"""

from __future__ import annotations

import dataclasses
import pytest

from emergent.wire.axis.surface.triggers.telegrinder import (
    TelegrinderTrigger,
    TelegrindTrigger,
)


# ─── Minimal rule stand-ins (no external dependencies) ───────────────────────
#
# telegrinder.bot.rules.abc.ABCRule is only available at TYPE_CHECKING time in
# the production module, so a duck-typed stand-in is all we need here.


class FakeRule:
    """Minimal object that looks like a telegrinder ABCRule for testing."""

    def __init__(self, name: str) -> None:
        self.name = name

    def __repr__(self) -> str:
        return f"FakeRule({self.name!r})"


# ─── Construction & default view ─────────────────────────────────────────────


def test_default_view_is_message() -> None:
    rule = FakeRule("command")
    trigger = TelegrinderTrigger(rule)  # type: ignore[arg-type]

    assert trigger.view == "message"


def test_rules_stored_as_tuple_single() -> None:
    rule = FakeRule("command")
    trigger = TelegrinderTrigger(rule)  # type: ignore[arg-type]

    assert trigger.rules == (rule,)
    assert isinstance(trigger.rules, tuple)


def test_rules_stored_as_tuple_multiple() -> None:
    rule1 = FakeRule("command")
    rule2 = FakeRule("text_match")
    trigger = TelegrinderTrigger(rule1, rule2)  # type: ignore[arg-type]

    assert trigger.rules == (rule1, rule2)
    assert len(trigger.rules) == 2


def test_custom_view_callback_query() -> None:
    rule = FakeRule("data_match")
    trigger = TelegrinderTrigger(rule, view="callback_query")  # type: ignore[arg-type]

    assert trigger.view == "callback_query"
    assert trigger.rules == (rule,)


def test_custom_view_arbitrary_string() -> None:
    rule = FakeRule("inline")
    trigger = TelegrinderTrigger(rule, view="inline_query")  # type: ignore[arg-type]

    assert trigger.view == "inline_query"


# ─── Frozen immutability ──────────────────────────────────────────────────────


def test_frozen_prevents_view_assignment() -> None:
    rule = FakeRule("command")
    trigger = TelegrinderTrigger(rule)  # type: ignore[arg-type]

    with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
        trigger.view = "callback_query"  # type: ignore[misc]


def test_frozen_prevents_rules_assignment() -> None:
    rule = FakeRule("command")
    trigger = TelegrinderTrigger(rule)  # type: ignore[arg-type]

    with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
        trigger.rules = ()  # type: ignore[misc]


# ─── TelegrindTrigger alias ───────────────────────────────────────────────────


def test_telegrind_trigger_alias_is_same_class() -> None:
    assert TelegrindTrigger is TelegrinderTrigger


def test_telegrind_trigger_alias_creates_same_instance_type() -> None:
    rule = FakeRule("command")
    trigger = TelegrindTrigger(rule)  # type: ignore[arg-type]

    assert isinstance(trigger, TelegrinderTrigger)
    assert trigger.view == "message"
    assert trigger.rules == (rule,)

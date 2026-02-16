"""Tests for TGApp — unified TG pattern coordinator."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

import pytest

from emergent.wire.axis.schema import Identity

from derivelib._derive import derive_endpoints
from derivelib.patterns.tg.app import TGApp
from derivelib.patterns.tg.browse import (
    ActionResult,
    BrowseSource,
    ListBrowseSource,
    TGBrowsePattern,
    action,
    query,
)
from derivelib.patterns.tg.dashboard import TGDashboardPattern
from derivelib.patterns.tg.flow import ShowMode, TextInput, TGFlowPattern
from derivelib.patterns.tg.registry import (
    CallbackCollision,
    CallbackRegistry,
    CommandCollision,
)
from derivelib.patterns.tg.settings import TGSettingsPattern
from derivelib.patterns.tg.uilib.theme import DEFAULT_THEME, UITheme, ActionUI


# ═══════════════════════════════════════════════════════════════════════════════
# CallbackRegistry
# ═══════════════════════════════════════════════════════════════════════════════


class TestCallbackRegistry:
    def test_register_command(self) -> None:
        reg = CallbackRegistry()
        reg.register_command("start", "flow", "Start flow")
        assert len(reg.commands) == 1
        assert reg.commands[0].command == "start"

    def test_command_collision(self) -> None:
        reg = CallbackRegistry()
        reg.register_command("start", "flow")
        with pytest.raises(CommandCollision, match="already registered"):
            reg.register_command("start", "browse")

    def test_register_callback(self) -> None:
        reg = CallbackRegistry()
        reg.register_callback("tasks", "browse", "tasks")
        assert len(reg.callback_namespaces) == 1

    def test_callback_collision(self) -> None:
        reg = CallbackRegistry()
        reg.register_callback("taskca", "browse", "taskcards")
        with pytest.raises(CallbackCollision, match="collision"):
            reg.register_callback("taskca", "dashboard", "taskcategories")

    def test_commands_sorted_by_order(self) -> None:
        reg = CallbackRegistry()
        reg.register_command("z_last", "flow", order=99)
        reg.register_command("a_first", "flow", order=1)
        reg.register_command("m_mid", "flow", order=50)
        cmds = reg.commands
        assert [c.command for c in cmds] == ["a_first", "m_mid", "z_last"]

    def test_different_commands_same_prefix_ok(self) -> None:
        """Different commands can coexist if they have different cb_prefixes."""
        reg = CallbackRegistry()
        reg.register_command("tasks", "browse")
        reg.register_command("teams", "browse")
        reg.register_callback("tasks", "browse", "tasks")
        reg.register_callback("teams", "browse", "teams")
        assert len(reg.commands) == 2
        assert len(reg.callback_namespaces) == 2


# ═══════════════════════════════════════════════════════════════════════════════
# TGApp — construction & shared state
# ═══════════════════════════════════════════════════════════════════════════════


class FakeKeyNode:
    pass


class FakeProvider:
    pass


class TestTGAppConstruction:
    def test_default_theme(self) -> None:
        tg = TGApp(key_node=FakeKeyNode)
        assert tg.theme == DEFAULT_THEME

    def test_custom_theme(self) -> None:
        custom = UITheme(action=ActionUI(done="OK"))
        tg = TGApp(key_node=FakeKeyNode, theme=custom)
        assert tg.theme.action.done == "OK"

    def test_empty_commands(self) -> None:
        tg = TGApp(key_node=FakeKeyNode)
        assert len(tg.commands) == 0


# ═══════════════════════════════════════════════════════════════════════════════
# TGApp.flow()
# ═══════════════════════════════════════════════════════════════════════════════


class TestTGAppFlow:
    def test_returns_flow_pattern(self) -> None:
        tg = TGApp(key_node=FakeKeyNode)
        p = tg.flow("register", description="Sign up")
        assert isinstance(p, TGFlowPattern)

    def test_shared_key_node(self) -> None:
        tg = TGApp(key_node=FakeKeyNode)
        p = tg.flow("register")
        assert p.key_node is FakeKeyNode

    def test_shared_theme(self) -> None:
        custom = UITheme(action=ActionUI(done="OK"))
        tg = TGApp(key_node=FakeKeyNode, theme=custom)
        p = tg.flow("register")
        assert p.theme.action.done == "OK"

    def test_description_and_order(self) -> None:
        tg = TGApp(key_node=FakeKeyNode)
        p = tg.flow("register", description="Sign up", order=5)
        assert p.description == "Sign up"
        assert p.order == 5

    def test_show_mode(self) -> None:
        tg = TGApp(key_node=FakeKeyNode)
        p = tg.flow("register", show_mode=ShowMode.EDIT)
        assert p.show_mode == ShowMode.EDIT

    def test_registers_command(self) -> None:
        tg = TGApp(key_node=FakeKeyNode)
        tg.flow("register", description="Sign up", order=1)
        assert len(tg.commands) == 1
        assert tg.commands[0].command == "register"
        assert tg.commands[0].pattern_kind == "flow"

    def test_duplicate_command_raises(self) -> None:
        tg = TGApp(key_node=FakeKeyNode)
        tg.flow("start")
        with pytest.raises(CommandCollision):
            tg.flow("start")


# ═══════════════════════════════════════════════════════════════════════════════
# TGApp.browse()
# ═══════════════════════════════════════════════════════════════════════════════


class TestTGAppBrowse:
    def test_returns_browse_pattern(self) -> None:
        tg = TGApp(key_node=FakeKeyNode)
        p = tg.browse("tasks", provider_node=FakeProvider)
        assert isinstance(p, TGBrowsePattern)

    def test_shared_key_node(self) -> None:
        tg = TGApp(key_node=FakeKeyNode)
        p = tg.browse("tasks", provider_node=FakeProvider)
        assert p.key_node is FakeKeyNode

    def test_page_size(self) -> None:
        tg = TGApp(key_node=FakeKeyNode)
        p = tg.browse("tasks", provider_node=FakeProvider, page_size=10)
        assert p.page_size == 10

    def test_auto_cb_prefix_from_command(self) -> None:
        tg = TGApp(key_node=FakeKeyNode)
        p = tg.browse("tasks", provider_node=FakeProvider)
        assert p.cb_prefix == "tasks"  # command[:6]

    def test_auto_cb_prefix_truncated(self) -> None:
        tg = TGApp(key_node=FakeKeyNode)
        p = tg.browse("longtaskname", provider_node=FakeProvider)
        assert p.cb_prefix == "longta"  # first 6 chars

    def test_explicit_cb_prefix(self) -> None:
        tg = TGApp(key_node=FakeKeyNode)
        p = tg.browse("tasks", provider_node=FakeProvider, cb_prefix="tsk")
        assert p.cb_prefix == "tsk"

    def test_registers_command_and_callback(self) -> None:
        tg = TGApp(key_node=FakeKeyNode)
        tg.browse("tasks", provider_node=FakeProvider)
        assert len(tg.commands) == 1
        assert len(tg.registry.callback_namespaces) == 1

    def test_callback_collision_detected(self) -> None:
        tg = TGApp(key_node=FakeKeyNode)
        tg.browse("abcdef", provider_node=FakeProvider)  # prefix = "abcdef"
        with pytest.raises(CallbackCollision):
            tg.dashboard("abcdefgh")  # prefix = "abcdef" - collision!

    def test_different_cb_prefixes_ok(self) -> None:
        tg = TGApp(key_node=FakeKeyNode)
        tg.browse("taskca", provider_node=FakeProvider)  # prefix = "taskca"
        tg.dashboard("taskcb")  # prefix = "taskcb" - different, ok
        assert len(tg.registry.callback_namespaces) == 2


# ═══════════════════════════════════════════════════════════════════════════════
# TGApp.dashboard()
# ═══════════════════════════════════════════════════════════════════════════════


class TestTGAppDashboard:
    def test_returns_dashboard_pattern(self) -> None:
        tg = TGApp(key_node=FakeKeyNode)
        p = tg.dashboard("roulette")
        assert isinstance(p, TGDashboardPattern)

    def test_shared_key_node(self) -> None:
        tg = TGApp(key_node=FakeKeyNode)
        p = tg.dashboard("roulette")
        assert p.key_node is FakeKeyNode

    def test_auto_cb_prefix(self) -> None:
        tg = TGApp(key_node=FakeKeyNode)
        p = tg.dashboard("roulette")
        assert p.cb_prefix == "roulet"  # command[:6]

    def test_empty_text(self) -> None:
        tg = TGApp(key_node=FakeKeyNode)
        p = tg.dashboard("roulette", empty_text="No table.")
        assert p.empty_text == "No table."


# ═══════════════════════════════════════════════════════════════════════════════
# TGApp.settings()
# ═══════════════════════════════════════════════════════════════════════════════


class TestTGAppSettings:
    def test_returns_settings_pattern(self) -> None:
        tg = TGApp(key_node=FakeKeyNode)
        p = tg.settings("config")
        assert isinstance(p, TGSettingsPattern)

    def test_shared_key_node(self) -> None:
        tg = TGApp(key_node=FakeKeyNode)
        p = tg.settings("config")
        assert p.key_node is FakeKeyNode

    def test_registers_command_only(self) -> None:
        """Settings uses SHA256 for callbacks — no prefix registration needed."""
        tg = TGApp(key_node=FakeKeyNode)
        tg.settings("config")
        assert len(tg.commands) == 1
        assert len(tg.registry.callback_namespaces) == 0


# ═══════════════════════════════════════════════════════════════════════════════
# Cross-pattern coordination
# ═══════════════════════════════════════════════════════════════════════════════


class TestCrossPatternCoordination:
    def test_flow_and_browse_different_commands(self) -> None:
        tg = TGApp(key_node=FakeKeyNode)
        tg.flow("register")
        tg.browse("tasks", provider_node=FakeProvider)
        assert len(tg.commands) == 2

    def test_command_collision_across_kinds(self) -> None:
        """Same command name across different pattern kinds is a collision."""
        tg = TGApp(key_node=FakeKeyNode)
        tg.flow("start")
        with pytest.raises(CommandCollision):
            tg.browse("start", provider_node=FakeProvider)

    def test_commands_ordered(self) -> None:
        tg = TGApp(key_node=FakeKeyNode)
        tg.settings("config", order=99)
        tg.flow("register", order=1, description="Sign up")
        tg.dashboard("roulette", order=50, description="Spin")
        cmds = tg.commands
        assert [c.command for c in cmds] == ["register", "roulette", "config"]

    def test_full_bot_setup(self) -> None:
        """Typical bot: flow + browse + dashboard + settings — no collisions."""
        tg = TGApp(key_node=FakeKeyNode)
        f = tg.flow("register", description="Sign up", order=1)
        b = tg.browse("tasks", provider_node=FakeProvider, description="My tasks", order=2)
        d = tg.dashboard("roulette", description="Spin", order=3)
        s = tg.settings("config", description="Settings", order=4)

        assert isinstance(f, TGFlowPattern)
        assert isinstance(b, TGBrowsePattern)
        assert isinstance(d, TGDashboardPattern)
        assert isinstance(s, TGSettingsPattern)
        assert len(tg.commands) == 4

        # All share the same key_node
        assert f.key_node is FakeKeyNode
        assert b.key_node is FakeKeyNode
        assert d.key_node is FakeKeyNode
        assert s.key_node is FakeKeyNode


# ═══════════════════════════════════════════════════════════════════════════════
# End-to-end: TGApp → derive → endpoints
# ═══════════════════════════════════════════════════════════════════════════════


class TestTGAppEndToEnd:
    def test_flow_compiles(self) -> None:
        """Pattern from TGApp compiles through derive_endpoints."""
        tg = TGApp(key_node=FakeKeyNode)
        pattern = tg.flow("register")

        @dataclass
        class Registration:
            name: Annotated[str, TextInput("Name?")]

            @classmethod
            async def finish(cls, reg: Registration) -> None:
                pass

        endpoints = derive_endpoints(Registration, pattern)
        assert len(endpoints) == 1
        assert len(endpoints[0].exposures) >= 1

    def test_browse_compiles(self) -> None:
        tg = TGApp(key_node=FakeKeyNode)
        pattern = tg.browse("tasks", provider_node=FakeProvider)

        @dataclass
        class TaskCard:
            id: Annotated[int, Identity]

            @classmethod
            @query
            async def items(cls) -> BrowseSource[TaskCard]:
                return ListBrowseSource(items=[])

        endpoints = derive_endpoints(TaskCard, pattern)
        assert len(endpoints) == 1
        assert len(endpoints[0].exposures) == 2  # command + callback

    def test_dashboard_compiles(self) -> None:
        tg = TGApp(key_node=FakeKeyNode)
        pattern = tg.dashboard("roulette")

        @dataclass
        class Table:
            id: Annotated[int, Identity]
            bet: int = 50

            @classmethod
            @query
            async def load(cls) -> Table:
                return Table(id=1)

            @classmethod
            @action("Spin")
            async def spin(cls, t: Table) -> ActionResult:
                return ActionResult.refresh("Result!")

        endpoints = derive_endpoints(Table, pattern)
        assert len(endpoints) == 1
        assert len(endpoints[0].exposures) == 2

"""Tests for derivelib.patterns.tg_methods — Telegram trigger decorators."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from kungfu import Ok, Result

from emergent.wire.axis.schema import Identity
from emergent.wire.axis.surface.codecs.delegate import DelegateCodec
from emergent.wire.axis.surface.codecs.rrc import RequestResponseCodec
from emergent.wire.axis.surface.triggers.telegrinder import TelegrindTrigger
from telegrinder.bot.rules.command import Command
from telegrinder.bot.rules.payload import PayloadModelRule

from derivelib._derive import derive, derive_endpoints
from derivelib._errors import DomainError
from derivelib.patterns.methods import (
    ExposeMethod,
    MethodsPattern,
    TRIGGER_ENTRIES_ATTR,
    methods,
)
from derivelib.patterns.tg.methods import (
    DELEGATE_ENTRIES_ATTR,
    ExposeDelegateMethod,
    _DelegateEntry,
    tg_callback,
    tg_command,
    tg_delegate,
)


# ═══════════════════════════════════════════════════════════════════════════════
# tg_command
# ═══════════════════════════════════════════════════════════════════════════════


class TestTGCommand:
    def test_creates_telegrinder_trigger(self) -> None:
        @tg_command("start")
        async def handler() -> Result[str, DomainError]:
            return Ok("hi")

        entries = getattr(handler, TRIGGER_ENTRIES_ATTR, [])
        assert len(entries) == 1
        trigger = entries[0].trigger
        assert isinstance(trigger, TelegrindTrigger)

    def test_view_is_message(self) -> None:
        @tg_command("start")
        async def handler() -> Result[str, DomainError]:
            return Ok("hi")

        trigger = getattr(handler, TRIGGER_ENTRIES_ATTR)[0].trigger
        assert trigger.view == "message"

    def test_rule_is_command(self) -> None:
        @tg_command("help")
        async def handler() -> Result[str, DomainError]:
            return Ok("help")

        trigger = getattr(handler, TRIGGER_ENTRIES_ATTR)[0].trigger
        assert len(trigger.rules) == 1
        assert isinstance(trigger.rules[0], Command)

    def test_classmethod_stacking(self) -> None:
        @dataclass
        class SVC:
            @classmethod
            @tg_command("start")
            async def start(cls) -> Result[str, DomainError]:
                return Ok("hi")

        raw = SVC.__dict__["start"]
        assert isinstance(raw, classmethod)
        fn = raw.__func__
        entries = getattr(fn, TRIGGER_ENTRIES_ATTR, [])
        assert len(entries) == 1

    def test_capabilities_passed(self) -> None:
        class FakeCap:
            pass

        cap = FakeCap()

        @tg_command("start", cap)
        async def handler() -> Result[str, DomainError]:
            return Ok("hi")

        entries = getattr(handler, TRIGGER_ENTRIES_ATTR)
        assert cap in entries[0].capabilities


# ═══════════════════════════════════════════════════════════════════════════════
# tg_callback
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class MoveCard:
    card_id: int
    column_id: int


class TestTGCallback:
    def test_creates_telegrinder_trigger(self) -> None:
        @tg_callback(MoveCard)
        async def handler() -> Result[str, DomainError]:
            return Ok("")

        entries = getattr(handler, TRIGGER_ENTRIES_ATTR, [])
        assert len(entries) == 1
        trigger = entries[0].trigger
        assert isinstance(trigger, TelegrindTrigger)

    def test_view_is_callback_query(self) -> None:
        @tg_callback(MoveCard)
        async def handler() -> Result[str, DomainError]:
            return Ok("")

        trigger = getattr(handler, TRIGGER_ENTRIES_ATTR)[0].trigger
        assert trigger.view == "callback_query"

    def test_rule_is_payload_model(self) -> None:
        @tg_callback(MoveCard)
        async def handler() -> Result[str, DomainError]:
            return Ok("")

        trigger = getattr(handler, TRIGGER_ENTRIES_ATTR)[0].trigger
        assert len(trigger.rules) == 1
        assert isinstance(trigger.rules[0], PayloadModelRule)

    def test_classmethod_stacking(self) -> None:
        @dataclass
        class SVC:
            @classmethod
            @tg_callback(MoveCard)
            async def move(cls) -> Result[str, DomainError]:
                return Ok("")

        raw = SVC.__dict__["move"]
        assert isinstance(raw, classmethod)
        fn = raw.__func__
        entries = getattr(fn, TRIGGER_ENTRIES_ATTR, [])
        assert len(entries) == 1
        assert entries[0].trigger.view == "callback_query"


# ═══════════════════════════════════════════════════════════════════════════════
# tg_delegate
# ═══════════════════════════════════════════════════════════════════════════════


class TestTGDelegate:
    def test_stores_delegate_entry(self) -> None:
        @tg_delegate(Command("admin"))
        async def handler() -> None:
            pass

        entries = getattr(handler, DELEGATE_ENTRIES_ATTR, [])
        assert len(entries) == 1
        assert isinstance(entries[0], _DelegateEntry)

    def test_does_not_store_trigger_entry(self) -> None:
        @tg_delegate(Command("admin"))
        async def handler() -> None:
            pass

        trigger_entries = getattr(handler, TRIGGER_ENTRIES_ATTR, [])
        assert len(trigger_entries) == 0

    def test_view_defaults_to_message(self) -> None:
        @tg_delegate(Command("admin"))
        async def handler() -> None:
            pass

        entry = getattr(handler, DELEGATE_ENTRIES_ATTR)[0]
        assert entry.trigger.view == "message"

    def test_view_callback_query(self) -> None:
        @tg_delegate(PayloadModelRule(MoveCard), view="callback_query")
        async def handler() -> None:
            pass

        entry = getattr(handler, DELEGATE_ENTRIES_ATTR)[0]
        assert entry.trigger.view == "callback_query"

    def test_accepts_raw_rules(self) -> None:
        @tg_delegate(Command("admin"), PayloadModelRule(MoveCard))
        async def handler() -> None:
            pass

        entry = getattr(handler, DELEGATE_ENTRIES_ATTR)[0]
        assert len(entry.trigger.rules) == 2

    def test_classmethod_stacking(self) -> None:
        @dataclass
        class SVC:
            @classmethod
            @tg_delegate(Command("admin"))
            async def admin(cls) -> None:
                pass

        raw = SVC.__dict__["admin"]
        assert isinstance(raw, classmethod)
        fn = raw.__func__
        entries = getattr(fn, DELEGATE_ENTRIES_ATTR, [])
        assert len(entries) == 1

    def test_caps_passed(self) -> None:
        class FakeCap:
            pass

        cap = FakeCap()

        @tg_delegate(Command("x"), caps=(cap,))
        async def handler() -> None:
            pass

        entry = getattr(handler, DELEGATE_ENTRIES_ATTR)[0]
        assert cap in entry.capabilities


# ═══════════════════════════════════════════════════════════════════════════════
# MethodsPattern integration — mixed trigger + delegate entries
# ═══════════════════════════════════════════════════════════════════════════════


class TestMethodsPatternIntegration:
    def test_compile_finds_tg_command(self) -> None:
        @dataclass
        class SVC:
            @classmethod
            @tg_command("start")
            async def start(cls) -> Result[str, DomainError]:
                return Ok("hi")

        pattern = MethodsPattern()
        steps = pattern.compile(SVC)
        expose_steps = [s for s in steps if isinstance(s, ExposeMethod)]
        assert len(expose_steps) == 1

    def test_compile_finds_tg_delegate(self) -> None:
        @dataclass
        class SVC:
            @classmethod
            @tg_delegate(Command("admin"))
            async def admin(cls) -> None:
                pass

        pattern = MethodsPattern()
        steps = pattern.compile(SVC)
        delegate_steps = [s for s in steps if isinstance(s, ExposeDelegateMethod)]
        assert len(delegate_steps) == 1

    def test_compile_mixed_trigger_and_delegate(self) -> None:
        @dataclass
        class SVC:
            @classmethod
            @tg_command("help")
            async def help_cmd(cls) -> Result[str, DomainError]:
                return Ok("help")

            @classmethod
            @tg_delegate(Command("admin"))
            async def admin(cls) -> None:
                pass

            @classmethod
            @tg_callback(MoveCard)
            async def move(cls) -> Result[str, DomainError]:
                return Ok("")

        pattern = MethodsPattern()
        steps = pattern.compile(SVC)
        expose_steps = [s for s in steps if isinstance(s, ExposeMethod)]
        delegate_steps = [s for s in steps if isinstance(s, ExposeDelegateMethod)]
        assert len(expose_steps) == 2  # tg_command + tg_callback
        assert len(delegate_steps) == 1  # tg_delegate

    def test_no_methods_empty(self) -> None:
        @dataclass
        class SVC:
            value: int = 0

        pattern = MethodsPattern()
        steps = pattern.compile(SVC)
        # Only inspect_entity step
        expose_steps = [s for s in steps if isinstance(s, (ExposeMethod, ExposeDelegateMethod))]
        assert len(expose_steps) == 0


# ═══════════════════════════════════════════════════════════════════════════════
# End-to-end: derive + compile
# ═══════════════════════════════════════════════════════════════════════════════


class TestEndToEnd:
    def test_tg_command_compiles_to_endpoint(self) -> None:
        @dataclass
        class SVC:
            id: Annotated[int, Identity]

            @classmethod
            @tg_command("help")
            async def help_cmd(cls) -> Result[str, DomainError]:
                return Ok("help text")

        endpoints = derive_endpoints(SVC, methods)
        assert len(endpoints) == 1
        assert len(endpoints[0].exposures) == 1

        exp = endpoints[0].exposures[0]
        assert isinstance(exp.trigger, TelegrindTrigger)
        assert isinstance(exp.codec, RequestResponseCodec)
        assert exp.trigger.view == "message"

    def test_tg_callback_compiles_to_endpoint(self) -> None:
        @dataclass
        class SVC:
            id: Annotated[int, Identity]

            @classmethod
            @tg_callback(MoveCard)
            async def move(cls, card_id: int, column_id: int) -> Result[str, DomainError]:
                return Ok("moved")

        endpoints = derive_endpoints(SVC, methods)
        assert len(endpoints) == 1
        assert len(endpoints[0].exposures) == 1

        exp = endpoints[0].exposures[0]
        assert isinstance(exp.trigger, TelegrindTrigger)
        assert exp.trigger.view == "callback_query"

    def test_tg_delegate_compiles_to_delegate_codec(self) -> None:
        @dataclass
        class SVC:
            id: Annotated[int, Identity]

            @classmethod
            @tg_delegate(Command("admin"))
            async def admin(cls) -> None:
                pass

        endpoints = derive_endpoints(SVC, methods)
        assert len(endpoints) == 1
        assert len(endpoints[0].exposures) == 1

        exp = endpoints[0].exposures[0]
        assert isinstance(exp.trigger, TelegrindTrigger)
        assert isinstance(exp.codec, DelegateCodec)

    def test_mixed_compiles_to_multiple_exposures(self) -> None:
        @dataclass
        class SVC:
            id: Annotated[int, Identity]

            @classmethod
            @tg_command("help")
            async def help_cmd(cls) -> Result[str, DomainError]:
                return Ok("help")

            @classmethod
            @tg_delegate(Command("admin"))
            async def admin(cls) -> None:
                pass

        endpoints = derive_endpoints(SVC, methods)
        assert len(endpoints) == 1
        assert len(endpoints[0].exposures) == 2

        codecs = {type(e.codec).__name__ for e in endpoints[0].exposures}
        assert "RequestResponseCodec" in codecs
        assert "DelegateCodec" in codecs

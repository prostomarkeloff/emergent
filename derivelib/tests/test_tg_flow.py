"""Tests for derivelib.patterns.tg_flow — multi-step TG conversation pattern."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date
from typing import Annotated
from unittest.mock import MagicMock

from kungfu import Nothing, Ok, Option, Result, Some

from emergent.wire.axis.schema import Identity
from emergent.wire.axis.surface.codecs.delegate import DelegateCodec
from emergent.wire.axis.surface.codecs.stateful import Cancelled, StatefulCodec
from emergent.wire.axis.surface.triggers.telegrinder import TelegrindTrigger
from telegrinder.bot.rules.command import Command
from telegrinder.bot.rules.payload import PayloadModelRule

from derivelib._derive import derive, derive_endpoints
from derivelib._errors import DomainError
from derivelib.patterns.tg.flow import (
    Case,
    Confirm,
    Counter,
    DatePicker,
    DocumentInput,
    FinishResult,
    FlowStack,
    FlowStackStorage,
    FlowSurfaceStep,
    Inline,
    LaunchMode,
    LocationInput,
    MaxLen,
    MinLen,
    Multiselect,
    Pattern,
    PhotoInput,
    Prefilled,
    Radio,
    ScrollingInline,
    ShowMode,
    StackFrame,
    TGFlowPattern,
    TextInput,
    When,
    _FlowCallbackData,
    _classify_fields,
    _find_next_active,
    _find_prev_active,
    _flow_name_hash,
    _generate_flow_class,
    _resolve_field_values,
    tg_flow,
    with_back,
    with_cancel,
    with_launch_mode,
    with_show_mode,
    with_stacking,
)
from derivelib.patterns.tg.widget import (
    Advance,
    FlowWidget,
    NoOp,
    Reject,
    Stay,
    WidgetContext,
    _validate_text,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Mock MessageCute helper
# ═══════════════════════════════════════════════════════════════════════════════


def _mock_message(
    text: str | None = None,
    photo: list[object] | None = None,
    document: object | None = None,
    location: object | None = None,
) -> MagicMock:
    """Create a mock MessageCute for widget handle_message tests."""
    msg = MagicMock()
    msg.text = Some(text) if text is not None else Nothing()
    msg.photo = Some(photo) if photo is not None else Nothing()
    msg.document = Some(document) if document is not None else Nothing()
    msg.location = Some(location) if location is not None else Nothing()
    return msg


# ═══════════════════════════════════════════════════════════════════════════════
# Exchange annotations
# ═══════════════════════════════════════════════════════════════════════════════


class TestTextInput:
    def test_construction(self) -> None:
        ti = TextInput("What is your name?")
        assert ti.prompt == "What is your name?"

    def test_frozen(self) -> None:
        ti = TextInput("prompt")
        try:
            ti.prompt = "other"  # type: ignore[misc]
            assert False, "should be frozen"
        except AttributeError:
            pass


class TestInline:
    def test_construction_with_options(self) -> None:
        il = Inline("Choose role:", admin="Admin", user="User")
        assert il.prompt == "Choose role:"
        assert il.options == {"admin": "Admin", "user": "User"}

    def test_no_options(self) -> None:
        il = Inline("Choose:")
        assert il.options == {}


class TestConfirm:
    def test_defaults(self) -> None:
        c = Confirm("Accept?")
        assert c.prompt == "Accept?"
        assert c.yes_label == "Yes"
        assert c.no_label == "No"

    def test_custom_labels(self) -> None:
        c = Confirm("Sure?", yes_label="Yep", no_label="Nah")
        assert c.yes_label == "Yep"
        assert c.no_label == "Nah"


class TestPrefilled:
    def test_construction(self) -> None:
        p = Prefilled()
        assert isinstance(p, Prefilled)


# ═══════════════════════════════════════════════════════════════════════════════
# Validation annotations
# ═══════════════════════════════════════════════════════════════════════════════


class TestMinLen:
    def test_construction(self) -> None:
        v = MinLen(3)
        assert v.length == 3


class TestMaxLen:
    def test_construction(self) -> None:
        v = MaxLen(50)
        assert v.length == 50


class TestPattern:
    def test_construction(self) -> None:
        v = Pattern(r"^\d{4}$")
        assert v.regex == r"^\d{4}$"


# ═══════════════════════════════════════════════════════════════════════════════
# FinishResult
# ═══════════════════════════════════════════════════════════════════════════════


class TestFinishResult:
    def test_message(self) -> None:
        fr = FinishResult.message("Done!")
        assert fr.text == "Done!"
        assert fr.next_command is None
        assert fr.context == {}

    def test_then(self) -> None:
        fr = FinishResult.then("Created!", command="tasks", project_id=42)
        assert fr.text == "Created!"
        assert fr.next_command == "tasks"
        assert fr.context == {"project_id": 42}

    def test_then_no_context(self) -> None:
        fr = FinishResult.then("ok", command="home")
        assert fr.next_command == "home"
        assert fr.context == {}


# ═══════════════════════════════════════════════════════════════════════════════
# _validate_text
# ═══════════════════════════════════════════════════════════════════════════════


class TestValidateText:
    def test_passes_no_validators(self) -> None:
        assert _validate_text("hello", ()) is None

    def test_min_len_pass(self) -> None:
        assert _validate_text("abc", (MinLen(3),)) is None

    def test_min_len_fail(self) -> None:
        err = _validate_text("ab", (MinLen(3),))
        assert err is not None
        assert "min 3" in err

    def test_max_len_pass(self) -> None:
        assert _validate_text("abc", (MaxLen(5),)) is None

    def test_max_len_fail(self) -> None:
        err = _validate_text("abcdef", (MaxLen(5),))
        assert err is not None
        assert "max 5" in err

    def test_pattern_pass(self) -> None:
        assert _validate_text("2024", (Pattern(r"^\d{4}$"),)) is None

    def test_pattern_fail(self) -> None:
        err = _validate_text("abcd", (Pattern(r"^\d{4}$"),))
        assert err is not None
        assert "Invalid format" in err

    def test_multiple_validators_first_fails(self) -> None:
        err = _validate_text("x", (MinLen(2), MaxLen(10)))
        assert err is not None
        assert "min 2" in err

    def test_multiple_validators_all_pass(self) -> None:
        assert _validate_text("hello", (MinLen(2), MaxLen(10))) is None


# ═══════════════════════════════════════════════════════════════════════════════
# _classify_fields
# ═══════════════════════════════════════════════════════════════════════════════


class TestClassifyFields:
    def test_text_input_field(self) -> None:
        @dataclass
        class E:
            name: Annotated[str, TextInput("Name?")]

        fields = _classify_fields(E)
        assert len(fields) == 1
        assert fields[0].name == "name"
        assert fields[0].base_type is str
        assert isinstance(fields[0].exchange, TextInput)
        assert not fields[0].is_optional

    def test_inline_field(self) -> None:
        @dataclass
        class E:
            role: Annotated[str, Inline("Role?", admin="Admin", user="User")]

        fields = _classify_fields(E)
        assert len(fields) == 1
        assert isinstance(fields[0].exchange, Inline)
        assert fields[0].exchange.options == {"admin": "Admin", "user": "User"}

    def test_confirm_field(self) -> None:
        @dataclass
        class E:
            accept: Annotated[bool, Confirm("OK?")]

        fields = _classify_fields(E)
        assert len(fields) == 1
        assert isinstance(fields[0].exchange, Confirm)
        assert fields[0].base_type is bool

    def test_prefilled_field(self) -> None:
        @dataclass
        class E:
            project_id: Annotated[int, Prefilled()]

        fields = _classify_fields(E)
        assert len(fields) == 1
        assert isinstance(fields[0].exchange, Prefilled)

    def test_skips_unannotated_fields(self) -> None:
        @dataclass
        class E:
            name: Annotated[str, TextInput("Name?")]
            boring: int = 0

        fields = _classify_fields(E)
        assert len(fields) == 1
        assert fields[0].name == "name"

    def test_validators_collected(self) -> None:
        @dataclass
        class E:
            name: Annotated[str, TextInput("Name?"), MinLen(2), MaxLen(50)]

        fields = _classify_fields(E)
        assert len(fields[0].validators) == 2
        assert isinstance(fields[0].validators[0], MinLen)
        assert isinstance(fields[0].validators[1], MaxLen)

    def test_optional_field(self) -> None:
        @dataclass
        class E:
            bio: Annotated[str | None, TextInput("Bio?")]

        fields = _classify_fields(E)
        assert len(fields) == 1
        assert fields[0].is_optional

    def test_mixed_fields(self) -> None:
        @dataclass
        class E:
            name: Annotated[str, TextInput("Name?")]
            role: Annotated[str, Inline("Role?", a="A")]
            accept: Annotated[bool, Confirm("OK?")]
            pid: Annotated[int, Prefilled()]

        fields = _classify_fields(E)
        assert len(fields) == 4
        exchanges = [type(f.exchange).__name__ for f in fields]
        assert "TextInput" in exchanges
        assert "Inline" in exchanges
        assert "Confirm" in exchanges
        assert "Prefilled" in exchanges

    def test_empty_entity(self) -> None:
        @dataclass
        class E:
            value: int = 0

        fields = _classify_fields(E)
        assert len(fields) == 0


# ═══════════════════════════════════════════════════════════════════════════════
# _generate_flow_class
# ═══════════════════════════════════════════════════════════════════════════════


class TestGenerateFlowClass:
    def _make_flow(self) -> type:
        @dataclass
        class Reg:
            name: Annotated[str, TextInput("Name?")]
            role: Annotated[str, Inline("Role?", admin="Admin")]

        from derivelib._codegen import create_dataclass

        fields = _classify_fields(Reg)
        op_type = create_dataclass("RegOp", [(f.name, f.base_type) for f in fields], frozen=True)
        return _generate_flow_class(Reg, fields, op_type, "Reg")

    def test_flow_has_option_fields(self) -> None:
        flow_cls = self._make_flow()
        inst = flow_cls()
        assert getattr(inst, "name") == Nothing()
        assert getattr(inst, "role") == Nothing()

    def test_flow_has_step_counter(self) -> None:
        flow_cls = self._make_flow()
        inst = flow_cls()
        assert getattr(inst, "_step") == 0

    def test_flow_has_to_domain(self) -> None:
        flow_cls = self._make_flow()
        assert hasattr(flow_cls, "to_domain")

    def test_flow_has_from_message(self) -> None:
        flow_cls = self._make_flow()
        assert hasattr(flow_cls, "from_message")

    def test_flow_has_from_callback_when_inline(self) -> None:
        flow_cls = self._make_flow()
        # Has Inline field → should have from_callback
        assert hasattr(flow_cls, "from_callback")

    def test_flow_no_callback_when_only_text(self) -> None:
        @dataclass
        class E:
            name: Annotated[str, TextInput("Name?")]
            age: Annotated[str, TextInput("Age?")]

        from derivelib._codegen import create_dataclass

        fields = _classify_fields(E)
        op_type = create_dataclass("EOp", [(f.name, f.base_type) for f in fields], frozen=True)
        flow_cls = _generate_flow_class(E, fields, op_type, "E")
        assert not hasattr(flow_cls, "from_callback")

    def test_to_domain_constructs_op(self) -> None:
        @dataclass
        class E:
            name: Annotated[str, TextInput("Name?")]

        from derivelib._codegen import create_dataclass

        fields = _classify_fields(E)
        op_type = create_dataclass("EOp", [(f.name, f.base_type) for f in fields], frozen=True)
        flow_cls = _generate_flow_class(E, fields, op_type, "E")

        inst = flow_cls(name=Some("Alice"), _step=1)
        op = inst.to_domain()
        assert getattr(op, "name") == "Alice"

    def test_to_domain_none_for_empty(self) -> None:
        @dataclass
        class E:
            name: Annotated[str, TextInput("Name?")]

        from derivelib._codegen import create_dataclass

        fields = _classify_fields(E)
        op_type = create_dataclass("EOp", [(f.name, f.base_type) for f in fields], frozen=True)
        flow_cls = _generate_flow_class(E, fields, op_type, "E")

        inst = flow_cls()
        op = inst.to_domain()
        assert getattr(op, "name") is None

    def test_flow_is_frozen(self) -> None:
        flow_cls = self._make_flow()
        inst = flow_cls()
        try:
            inst.name = Some("Alice")  # type: ignore[misc]
            assert False, "should be frozen"
        except AttributeError:
            pass


# ═══════════════════════════════════════════════════════════════════════════════
# _flow_name_hash
# ═══════════════════════════════════════════════════════════════════════════════


class TestFlowNameHash:
    def test_returns_8_char_hex(self) -> None:
        @dataclass
        class Foo:
            pass

        h = _flow_name_hash(Foo)
        assert len(h) == 8
        assert all(c in "0123456789abcdef" for c in h)

    def test_deterministic(self) -> None:
        @dataclass
        class Bar:
            pass

        assert _flow_name_hash(Bar) == _flow_name_hash(Bar)

    def test_different_classes_differ(self) -> None:
        @dataclass
        class A:
            pass

        @dataclass
        class B:
            pass

        assert _flow_name_hash(A) != _flow_name_hash(B)


# ═══════════════════════════════════════════════════════════════════════════════
# FlowCallbackData
# ═══════════════════════════════════════════════════════════════════════════════


class TestFlowCallbackData:
    def test_construction(self) -> None:
        fcd = _FlowCallbackData(flow="Reg", value="admin")
        assert fcd.flow == "Reg"
        assert fcd.value == "admin"


# ═══════════════════════════════════════════════════════════════════════════════
# TGFlowPattern
# ═══════════════════════════════════════════════════════════════════════════════


class FakeKeyNode:
    pass


class TestTGFlowPattern:
    def test_construction(self) -> None:
        p = TGFlowPattern(command="start", key_node=FakeKeyNode)
        assert p.command == "start"
        assert p.key_node is FakeKeyNode
        assert p.capabilities == ()

    def test_compile_returns_derivation(self) -> None:
        @dataclass
        class E:
            name: Annotated[str, TextInput("Name?")]

            async def finish(self) -> Result[FinishResult, DomainError]:
                return Ok(FinishResult.message("done"))

        p = TGFlowPattern(command="start", key_node=FakeKeyNode)
        derivation = p.compile(E)
        assert len(derivation) == 2  # inspect_entity + FlowSurfaceStep

    def test_compile_second_step_is_flow_surface(self) -> None:
        @dataclass
        class E:
            name: Annotated[str, TextInput("Name?")]

            async def finish(self) -> Result[FinishResult, DomainError]:
                return Ok(FinishResult.message("done"))

        p = TGFlowPattern(command="start", key_node=FakeKeyNode)
        derivation = p.compile(E)
        assert isinstance(derivation[1], FlowSurfaceStep)

    def test_tg_flow_factory(self) -> None:
        p = tg_flow(command="register", key_node=FakeKeyNode)
        assert isinstance(p, TGFlowPattern)
        assert p.command == "register"


# ═══════════════════════════════════════════════════════════════════════════════
# Transforms
# ═══════════════════════════════════════════════════════════════════════════════


class TestTransforms:
    def test_with_cancel_sets_flag(self) -> None:
        step = FlowSurfaceStep(command="start", key_node=FakeKeyNode, capabilities=())
        steps = (step,)
        result = with_cancel()(steps)
        assert isinstance(result[0], FlowSurfaceStep)
        assert result[0].supports_cancel is True
        assert result[0].supports_back is False

    def test_with_back_sets_flag(self) -> None:
        step = FlowSurfaceStep(command="start", key_node=FakeKeyNode, capabilities=())
        steps = (step,)
        result = with_back()(steps)
        assert isinstance(result[0], FlowSurfaceStep)
        assert result[0].supports_back is True
        assert result[0].supports_cancel is False

    def test_cancel_and_back_combined(self) -> None:
        step = FlowSurfaceStep(command="start", key_node=FakeKeyNode, capabilities=())
        steps = (step,)
        result = with_cancel()(with_back()(steps))
        assert result[0].supports_cancel is True
        assert result[0].supports_back is True

    def test_transforms_pass_through_non_flow_steps(self) -> None:
        """Non-FlowSurfaceStep steps are left unchanged."""
        sentinel = object()
        step = FlowSurfaceStep(command="x", key_node=FakeKeyNode, capabilities=())
        steps = (sentinel, step)
        result = with_cancel()(steps)
        assert result[0] is sentinel
        assert result[1].supports_cancel is True


# ═══════════════════════════════════════════════════════════════════════════════
# Cancelled marker
# ═══════════════════════════════════════════════════════════════════════════════


class TestCancelled:
    def test_is_done_subclass(self) -> None:
        from emergent.wire.axis.surface.codecs.stateful import Done
        assert issubclass(Cancelled, Done)

    def test_isinstance_done(self) -> None:
        from emergent.wire.axis.surface.codecs.stateful import Done
        c = Cancelled()
        assert isinstance(c, Done)

    def test_is_terminal(self) -> None:
        from emergent.wire.axis.surface.codecs.stateful import parse_transition_result
        result = parse_transition_result(Cancelled())
        assert result.is_terminal is True


# ═══════════════════════════════════════════════════════════════════════════════
# Flow generation with cancel/back flags
# ═══════════════════════════════════════════════════════════════════════════════


class TestCancelBackExposures:
    """Cancel/back are separate DelegateCodec exposures, not in-transition logic."""

    def test_cancel_generates_extra_exposure(self) -> None:
        """with_cancel() adds a DelegateCodec exposure with Command('cancel')."""

        @dataclass
        class Reg:
            id: Annotated[int, Identity]
            name: Annotated[str, TextInput("Name?")]

            async def finish(self) -> Result[FinishResult, DomainError]:
                return Ok(FinishResult.message("done"))

        pattern = tg_flow(command="reg", key_node=FakeKeyNode).chain(with_cancel())
        endpoints = derive_endpoints(Reg, pattern)
        assert len(endpoints) == 1

        # Text-only flow: 1 message + 1 cancel = 2 exposures
        exposures = endpoints[0].exposures
        assert len(exposures) == 2

        # Find the cancel exposure (DelegateCodec)
        cancel_exps = [e for e in exposures if isinstance(e.codec, DelegateCodec)]
        assert len(cancel_exps) == 1
        cancel_exp = cancel_exps[0]
        assert cancel_exp.trigger.view == "message"

        # Should have Command("cancel") rule
        has_cancel_cmd = any(
            isinstance(r, Command) and "cancel" in r.names
            for r in cancel_exp.trigger.rules
        )
        assert has_cancel_cmd

    def test_back_generates_extra_exposure(self) -> None:
        """with_back() adds a DelegateCodec exposure with Command('back')."""

        @dataclass
        class Reg:
            id: Annotated[int, Identity]
            name: Annotated[str, TextInput("Name?")]

            async def finish(self) -> Result[FinishResult, DomainError]:
                return Ok(FinishResult.message("done"))

        pattern = tg_flow(command="reg", key_node=FakeKeyNode).chain(with_back())
        endpoints = derive_endpoints(Reg, pattern)

        exposures = endpoints[0].exposures
        assert len(exposures) == 2

        back_exps = [e for e in exposures if isinstance(e.codec, DelegateCodec)]
        assert len(back_exps) == 1
        back_exp = back_exps[0]

        has_back_cmd = any(
            isinstance(r, Command) and "back" in r.names
            for r in back_exp.trigger.rules
        )
        assert has_back_cmd

    def test_cancel_and_back_generate_two_extra_exposures(self) -> None:
        """Both transforms together add 2 DelegateCodec exposures."""

        @dataclass
        class Reg:
            id: Annotated[int, Identity]
            name: Annotated[str, TextInput("Name?")]

            async def finish(self) -> Result[FinishResult, DomainError]:
                return Ok(FinishResult.message("done"))

        pattern = tg_flow(command="reg", key_node=FakeKeyNode).chain(
            with_cancel(), with_back(),
        )
        endpoints = derive_endpoints(Reg, pattern)

        exposures = endpoints[0].exposures
        # 1 message + 1 cancel + 1 back = 3
        assert len(exposures) == 3

        delegate_exps = [e for e in exposures if isinstance(e.codec, DelegateCodec)]
        assert len(delegate_exps) == 2

    def test_inline_flow_with_cancel(self) -> None:
        """Inline flow + cancel: message + callback + cancel = 3 exposures."""

        @dataclass
        class Reg:
            id: Annotated[int, Identity]
            name: Annotated[str, TextInput("Name?")]
            role: Annotated[str, Inline("Role?", admin="Admin", user="User")]

            async def finish(self) -> Result[FinishResult, DomainError]:
                return Ok(FinishResult.message("done"))

        pattern = tg_flow(command="reg", key_node=FakeKeyNode).chain(with_cancel())
        endpoints = derive_endpoints(Reg, pattern)

        exposures = endpoints[0].exposures
        # message + callback_query + cancel = 3
        assert len(exposures) == 3

        views = {e.trigger.view for e in exposures}
        assert "message" in views
        assert "callback_query" in views


# ═══════════════════════════════════════════════════════════════════════════════
# End-to-end: derive + compile
# ═══════════════════════════════════════════════════════════════════════════════


class TestEndToEnd:
    def test_text_only_flow_one_exposure(self) -> None:
        """Text-only flow → 1 exposure (message only)."""

        @dataclass
        class Reg:
            id: Annotated[int, Identity]
            name: Annotated[str, TextInput("Name?")]

            async def finish(self) -> Result[FinishResult, DomainError]:
                return Ok(FinishResult.message("done"))

        pattern = tg_flow(command="register", key_node=FakeKeyNode)
        endpoints = derive_endpoints(Reg, pattern)
        assert len(endpoints) == 1
        # Text-only: only message exposure
        assert len(endpoints[0].exposures) == 1
        exp = endpoints[0].exposures[0]
        assert isinstance(exp.trigger, TelegrindTrigger)
        assert isinstance(exp.codec, StatefulCodec)
        assert exp.trigger.view == "message"

    def test_inline_flow_two_exposures(self) -> None:
        """Flow with Inline field → 2 exposures (message + callback_query)."""

        @dataclass
        class Reg:
            id: Annotated[int, Identity]
            name: Annotated[str, TextInput("Name?")]
            role: Annotated[str, Inline("Role?", admin="Admin", user="User")]

            async def finish(self) -> Result[FinishResult, DomainError]:
                return Ok(FinishResult.message("done"))

        pattern = tg_flow(command="register", key_node=FakeKeyNode)
        endpoints = derive_endpoints(Reg, pattern)
        assert len(endpoints) == 1
        assert len(endpoints[0].exposures) == 2

        views = {e.trigger.view for e in endpoints[0].exposures}
        assert "message" in views
        assert "callback_query" in views

    def test_confirm_flow_two_exposures(self) -> None:
        """Flow with Confirm field → 2 exposures (message + callback_query)."""

        @dataclass
        class Tos:
            id: Annotated[int, Identity]
            accept: Annotated[bool, Confirm("Accept TOS?")]

            async def finish(self) -> Result[FinishResult, DomainError]:
                return Ok(FinishResult.message("ok"))

        pattern = tg_flow(command="tos", key_node=FakeKeyNode)
        endpoints = derive_endpoints(Tos, pattern)
        assert len(endpoints[0].exposures) == 2

    def test_codec_is_stateful(self) -> None:
        @dataclass
        class E:
            id: Annotated[int, Identity]
            name: Annotated[str, TextInput("Name?")]

            async def finish(self) -> Result[FinishResult, DomainError]:
                return Ok(FinishResult.message("done"))

        endpoints = derive_endpoints(E, tg_flow(command="test", key_node=FakeKeyNode))
        for exp in endpoints[0].exposures:
            assert isinstance(exp.codec, StatefulCodec)

    def test_message_trigger_has_command_rule(self) -> None:
        @dataclass
        class E:
            id: Annotated[int, Identity]
            name: Annotated[str, TextInput("Name?")]

            async def finish(self) -> Result[FinishResult, DomainError]:
                return Ok(FinishResult.message("done"))

        endpoints = derive_endpoints(E, tg_flow(command="reg", key_node=FakeKeyNode))
        msg_exp = next(e for e in endpoints[0].exposures if e.trigger.view == "message")
        assert isinstance(msg_exp.trigger.rules[0], Command)

    def test_chain_with_transforms(self) -> None:
        @dataclass
        class E:
            id: Annotated[int, Identity]
            name: Annotated[str, TextInput("Name?")]

            async def finish(self) -> Result[FinishResult, DomainError]:
                return Ok(FinishResult.message("done"))

        pattern = tg_flow(command="reg", key_node=FakeKeyNode).chain(with_cancel())
        endpoints = derive_endpoints(E, pattern)
        assert len(endpoints) == 1
        # Text-only + cancel = 2 exposures
        assert len(endpoints[0].exposures) == 2


# ═══════════════════════════════════════════════════════════════════════════════
# Inline columns
# ═══════════════════════════════════════════════════════════════════════════════


class TestInlineColumns:
    def test_default_columns(self) -> None:
        il = Inline("Choose:", a="A", b="B")
        assert il.columns == 1

    def test_custom_columns(self) -> None:
        il = Inline("Size:", columns=3, xs="XS", s="S", m="M")
        assert il.columns == 3
        assert il.options == {"xs": "XS", "s": "S", "m": "M"}


# ═══════════════════════════════════════════════════════════════════════════════
# When annotation
# ═══════════════════════════════════════════════════════════════════════════════


class TestWhen:
    def test_construction(self) -> None:
        w = When(lambda v: v.get("kind") == "bug")
        assert callable(w.predicate)

    def test_predicate_true(self) -> None:
        w = When(lambda v: v.get("kind") == "bug")
        assert w.predicate({"kind": "bug"}) is True

    def test_predicate_false(self) -> None:
        w = When(lambda v: v.get("kind") == "bug")
        assert w.predicate({"kind": "feature"}) is False

    def test_predicate_missing_key(self) -> None:
        w = When(lambda v: v.get("kind") == "bug")
        assert w.predicate({}) is False


class TestClassifyFieldsWhen:
    def test_when_picked_up(self) -> None:
        @dataclass
        class E:
            kind: Annotated[str, Inline("Kind:", bug="Bug", feature="Feature")]
            severity: Annotated[str, Inline("Severity:", high="H", low="L"), When(lambda v: v.get("kind") == "bug")]

        fields = _classify_fields(E)
        assert len(fields) == 2
        assert fields[0].when is None
        assert fields[1].when is not None
        assert fields[1].when.predicate({"kind": "bug"}) is True

    def test_when_absent_by_default(self) -> None:
        @dataclass
        class E:
            name: Annotated[str, TextInput("Name?")]

        fields = _classify_fields(E)
        assert fields[0].when is None


# ═══════════════════════════════════════════════════════════════════════════════
# When helpers — _resolve_field_values, _find_next_active, _find_prev_active
# ═══════════════════════════════════════════════════════════════════════════════


class TestResolveFieldValues:
    def test_collected_values_unwrapped(self) -> None:
        @dataclass
        class E:
            kind: Annotated[str, Inline("Kind:", a="A")]
            name: Annotated[str, TextInput("Name?")]

        fields = _classify_fields(E)
        from derivelib._codegen import create_dataclass
        op_type = create_dataclass("EOp", [(f.name, f.base_type) for f in fields], frozen=True)
        flow_cls = _generate_flow_class(E, fields, op_type, "E")
        state = flow_cls(kind=Some("a"), name=Nothing())

        values = _resolve_field_values(state, fields)
        assert values == {"kind": "a", "name": None}

    def test_all_empty(self) -> None:
        @dataclass
        class E:
            x: Annotated[str, TextInput("X?")]

        fields = _classify_fields(E)
        from derivelib._codegen import create_dataclass
        op_type = create_dataclass("EOp", [(f.name, f.base_type) for f in fields], frozen=True)
        flow_cls = _generate_flow_class(E, fields, op_type, "E")
        state = flow_cls()

        values = _resolve_field_values(state, fields)
        assert values == {"x": None}


class TestFindNextActive:
    def _setup(self) -> tuple[type, list[object], list[object]]:
        @dataclass
        class E:
            kind: Annotated[str, Inline("Kind:", bug="Bug", feat="Feature")]
            severity: Annotated[str, Inline("Sev:", h="H", l="L"), When(lambda v: v.get("kind") == "bug")]
            title: Annotated[str, TextInput("Title?")]

        fields = _classify_fields(E)
        prompted = [f for f in fields if not isinstance(f.exchange, Prefilled)]
        from derivelib._codegen import create_dataclass
        op_type = create_dataclass("EOp", [(f.name, f.base_type) for f in fields], frozen=True)
        flow_cls = _generate_flow_class(E, fields, op_type, "E")
        return flow_cls, prompted, fields

    def test_next_unconditional(self) -> None:
        flow_cls, prompted, fields = self._setup()
        state = flow_cls(kind=Some("feat"))
        # From step 0 (kind=feat), severity has When(kind==bug) → skip, next is title (idx 2)
        result = _find_next_active(state, 0, prompted, fields)
        assert result == 2

    def test_next_conditional_true(self) -> None:
        flow_cls, prompted, fields = self._setup()
        state = flow_cls(kind=Some("bug"))
        # From step 0 (kind=bug), severity When passes → next is severity (idx 1)
        result = _find_next_active(state, 0, prompted, fields)
        assert result == 1

    def test_next_none_at_end(self) -> None:
        flow_cls, prompted, fields = self._setup()
        state = flow_cls(kind=Some("feat"), title=Some("t"))
        # From step 2 (title), no more fields
        result = _find_next_active(state, 2, prompted, fields)
        assert result is None

    def test_find_first_active(self) -> None:
        flow_cls, prompted, fields = self._setup()
        state = flow_cls()
        # From -1, first field (kind) has no When → returns 0
        result = _find_next_active(state, -1, prompted, fields)
        assert result == 0


class TestFindPrevActive:
    def _setup(self) -> tuple[type, list[object], list[object]]:
        @dataclass
        class E:
            kind: Annotated[str, Inline("Kind:", bug="Bug", feat="Feature")]
            severity: Annotated[str, Inline("Sev:", h="H", l="L"), When(lambda v: v.get("kind") == "bug")]
            title: Annotated[str, TextInput("Title?")]

        fields = _classify_fields(E)
        prompted = [f for f in fields if not isinstance(f.exchange, Prefilled)]
        from derivelib._codegen import create_dataclass
        op_type = create_dataclass("EOp", [(f.name, f.base_type) for f in fields], frozen=True)
        flow_cls = _generate_flow_class(E, fields, op_type, "E")
        return flow_cls, prompted, fields

    def test_prev_skips_inactive(self) -> None:
        flow_cls, prompted, fields = self._setup()
        state = flow_cls(kind=Some("feat"), title=Some("t"))
        # From step 2 (title), kind=feat → severity inactive → prev is kind (idx 0)
        result = _find_prev_active(state, 2, prompted, fields)
        assert result == 0

    def test_prev_includes_active(self) -> None:
        flow_cls, prompted, fields = self._setup()
        state = flow_cls(kind=Some("bug"), severity=Some("h"))
        # From step 2 (title), kind=bug → severity active → prev is severity (idx 1)
        result = _find_prev_active(state, 2, prompted, fields)
        assert result == 1

    def test_prev_none_at_start(self) -> None:
        flow_cls, prompted, fields = self._setup()
        state = flow_cls()
        result = _find_prev_active(state, 0, prompted, fields)
        assert result is None


# ═══════════════════════════════════════════════════════════════════════════════
# FlowStack
# ═══════════════════════════════════════════════════════════════════════════════


class TestFlowStack:
    def test_push_pop(self) -> None:
        stack = FlowStack()
        stack.push("user1", StackFrame(command="parent"))
        frame = stack.pop("user1")
        assert frame is not None
        assert frame.command == "parent"

    def test_pop_empty(self) -> None:
        stack = FlowStack()
        assert stack.pop("user1") is None

    def test_lifo_order(self) -> None:
        stack = FlowStack()
        stack.push("u", StackFrame(command="a"))
        stack.push("u", StackFrame(command="b"))
        assert stack.pop("u") == StackFrame(command="b")
        assert stack.pop("u") == StackFrame(command="a")
        assert stack.pop("u") is None

    def test_isolation_by_key(self) -> None:
        stack = FlowStack()
        stack.push("u1", StackFrame(command="x"))
        stack.push("u2", StackFrame(command="y"))
        assert stack.pop("u1") == StackFrame(command="x")
        assert stack.pop("u2") == StackFrame(command="y")

    def test_implements_protocol(self) -> None:
        stack = FlowStack()
        # Structural check: has push and pop methods
        assert hasattr(stack, "push")
        assert hasattr(stack, "pop")


class TestStackFrame:
    def test_frozen(self) -> None:
        f = StackFrame(command="test")
        try:
            f.command = "other"  # type: ignore[misc]
            assert False, "should be frozen"
        except AttributeError:
            pass


# ═══════════════════════════════════════════════════════════════════════════════
# FinishResult.sub_flow
# ═══════════════════════════════════════════════════════════════════════════════


class TestFinishResultSubFlow:
    def test_sub_flow(self) -> None:
        fr = FinishResult.sub_flow("Created!", command="invite")
        assert fr.text == "Created!"
        assert fr.next_command == "invite"
        assert fr.is_sub_flow is True
        assert fr.context == {}

    def test_sub_flow_with_context(self) -> None:
        fr = FinishResult.sub_flow("Done", command="next", project_id=42)
        assert fr.context == {"project_id": 42}
        assert fr.is_sub_flow is True

    def test_message_not_sub_flow(self) -> None:
        fr = FinishResult.message("Done!")
        assert fr.is_sub_flow is False

    def test_then_not_sub_flow(self) -> None:
        fr = FinishResult.then("Done!", command="next")
        assert fr.is_sub_flow is False


# ═══════════════════════════════════════════════════════════════════════════════
# with_stacking transform
# ═══════════════════════════════════════════════════════════════════════════════


class TestWithStacking:
    def test_sets_stack_on_flow_surface_step(self) -> None:
        step = FlowSurfaceStep(command="test", key_node=FakeKeyNode, capabilities=())
        assert step.stack is None
        result = with_stacking()(((step,)))[0]
        assert isinstance(result, FlowSurfaceStep)
        assert result.stack is not None

    def test_custom_stack(self) -> None:
        custom = FlowStack()
        step = FlowSurfaceStep(command="test", key_node=FakeKeyNode, capabilities=())
        result = with_stacking(custom)(((step,)))[0]
        assert result.stack is custom

    def test_shared_stack_across_flows(self) -> None:
        shared = FlowStack()
        step1 = FlowSurfaceStep(command="a", key_node=FakeKeyNode, capabilities=())
        step2 = FlowSurfaceStep(command="b", key_node=FakeKeyNode, capabilities=())
        r1 = with_stacking(shared)(((step1,)))[0]
        r2 = with_stacking(shared)(((step2,)))[0]
        assert r1.stack is r2.stack is shared

    def test_passes_through_non_flow_steps(self) -> None:
        sentinel = object()
        step = FlowSurfaceStep(command="x", key_node=FakeKeyNode, capabilities=())
        result = with_stacking()((sentinel, step))
        assert result[0] is sentinel
        assert result[1].stack is not None


# ═══════════════════════════════════════════════════════════════════════════════
# Counter exchange type
# ═══════════════════════════════════════════════════════════════════════════════


class TestCounter:
    def test_construction(self) -> None:
        c = Counter("How many?")
        assert c.prompt == "How many?"
        assert c.min == 0
        assert c.max == 999999
        assert c.step == 1
        assert c.default == 0

    def test_custom_values(self) -> None:
        c = Counter("Qty:", min=1, max=100, step=5, default=10)
        assert c.min == 1
        assert c.max == 100
        assert c.step == 5
        assert c.default == 10

    def test_frozen(self) -> None:
        c = Counter("X")
        try:
            c.prompt = "Y"  # type: ignore[misc]
            raise AssertionError("Should be frozen")
        except AttributeError:
            pass


class TestMultiselect:
    def test_construction(self) -> None:
        ms = Multiselect("Tags:", python="Python", rust="Rust")
        assert ms.prompt == "Tags:"
        assert ms.options == {"python": "Python", "rust": "Rust"}
        assert ms.columns == 1
        assert ms.min_selected == 0
        assert ms.max_selected == 0

    def test_columns_and_constraints(self) -> None:
        ms = Multiselect("Tags:", columns=2, min_selected=1, max_selected=3, a="A", b="B")
        assert ms.columns == 2
        assert ms.min_selected == 1
        assert ms.max_selected == 3
        assert ms.options == {"a": "A", "b": "B"}

    def test_frozen(self) -> None:
        ms = Multiselect("X", a="A")
        try:
            ms.prompt = "Y"  # type: ignore[misc]
            raise AssertionError("Should be frozen")
        except AttributeError:
            pass


# ═══════════════════════════════════════════════════════════════════════════════
# ShowMode and LaunchMode enums
# ═══════════════════════════════════════════════════════════════════════════════


class TestShowMode:
    def test_values(self) -> None:
        assert ShowMode.SEND.value == "send"
        assert ShowMode.EDIT.value == "edit"
        assert ShowMode.DELETE_AND_SEND.value == "delete_and_send"

    def test_members(self) -> None:
        assert len(ShowMode) == 3


class TestLaunchMode:
    def test_values(self) -> None:
        assert LaunchMode.STANDARD.value == "standard"
        assert LaunchMode.RESET.value == "reset"
        assert LaunchMode.EXCLUSIVE.value == "exclusive"
        assert LaunchMode.SINGLE_TOP.value == "single_top"

    def test_members(self) -> None:
        assert len(LaunchMode) == 4


# ═══════════════════════════════════════════════════════════════════════════════
# _classify_fields with Counter / Multiselect
# ═══════════════════════════════════════════════════════════════════════════════


class TestClassifyFieldsCounter:
    def test_counter_field_recognized(self) -> None:
        @dataclass
        class E:
            qty: Annotated[int, Counter("How many?", min=1, max=50)]

        fields = _classify_fields(E)
        assert len(fields) == 1
        assert fields[0].name == "qty"
        assert isinstance(fields[0].exchange, Counter)
        assert fields[0].base_type is int

    def test_counter_defaults(self) -> None:
        @dataclass
        class E:
            amount: Annotated[int, Counter("Amount:")]

        fields = _classify_fields(E)
        ex = fields[0].exchange
        assert isinstance(ex, Counter)
        assert ex.default == 0
        assert ex.step == 1


class TestClassifyFieldsMultiselect:
    def test_multiselect_field_recognized(self) -> None:
        @dataclass
        class E:
            tags: Annotated[str, Multiselect("Tags:", python="Python", rust="Rust")]

        fields = _classify_fields(E)
        assert len(fields) == 1
        assert fields[0].name == "tags"
        assert isinstance(fields[0].exchange, Multiselect)
        assert fields[0].base_type is str

    def test_multiselect_with_constraints(self) -> None:
        @dataclass
        class E:
            items: Annotated[str, Multiselect("Pick:", min_selected=1, max_selected=3, a="A")]

        fields = _classify_fields(E)
        ex = fields[0].exchange
        assert isinstance(ex, Multiselect)
        assert ex.min_selected == 1
        assert ex.max_selected == 3


# ═══════════════════════════════════════════════════════════════════════════════
# Widget render tests (replaces _build_*_keyboard and _prompt_content tests)
# ═══════════════════════════════════════════════════════════════════════════════


def _make_ctx(
    flow_name: str = "abc123",
    field_name: str = "field",
    current_value: object = Nothing(),
    base_type: type = str,
    validators: tuple[MinLen | MaxLen | Pattern, ...] = (),
    is_optional: bool = False,
    flow_state: dict[str, object] | None = None,
) -> WidgetContext:
    return WidgetContext(
        flow_name=flow_name,
        field_name=field_name,
        current_value=current_value,
        base_type=base_type,
        validators=validators,
        is_optional=is_optional,
        flow_state=flow_state or {},
    )


class TestCounterRender:
    def test_has_four_buttons(self) -> None:
        counter = Counter("How many?", min=0, max=10, step=1, default=5)
        ctx = _make_ctx(field_name="qty", base_type=int)
        text, kb = asyncio.run(counter.render(ctx))
        assert text == "How many?"
        assert kb is not None
        markup = kb.get_markup()
        # Row 1: [−] [5] [+], Row 2: [Done]
        buttons = [b for row in markup.inline_keyboard for b in row]
        assert len(buttons) == 4

    def test_value_displayed_default(self) -> None:
        import json
        counter = Counter("How many?", min=0, max=10, step=1, default=5)
        ctx = _make_ctx(field_name="qty", base_type=int)
        _, kb = asyncio.run(counter.render(ctx))
        assert kb is not None
        markup = kb.get_markup()
        # Middle button of first row shows default value
        value_btn = markup.inline_keyboard[0][1]
        assert value_btn.text == "5"
        data = json.loads(value_btn.callback_data.unwrap())
        assert data["value"] == "counter:noop"

    def test_value_displayed_from_state(self) -> None:
        counter = Counter("How many?", min=0, max=10, step=1, default=5)
        ctx = _make_ctx(field_name="qty", base_type=int, current_value=Some(7))
        _, kb = asyncio.run(counter.render(ctx))
        assert kb is not None
        assert kb.get_markup().inline_keyboard[0][1].text == "7"

    def test_returns_keyboard_with_default(self) -> None:
        counter = Counter("Qty:", default=5)
        ctx = _make_ctx(field_name="qty", base_type=int)
        text, kb = asyncio.run(counter.render(ctx))
        assert text == "Qty:"
        assert kb is not None
        assert kb.get_markup().inline_keyboard[0][1].text == "5"


class TestMultiselectRender:
    def test_unchecked_buttons(self) -> None:
        ms = Multiselect("Tags:", a="Alpha", b="Beta")
        ctx = _make_ctx(field_name="tags")
        _, kb = asyncio.run(ms.render(ctx))
        assert kb is not None
        markup = kb.get_markup()
        buttons = [b for row in markup.inline_keyboard for b in row]
        # 2 options + 1 done
        assert len(buttons) == 3
        assert "\u2b1c" in buttons[0].text  # unchecked
        assert "\u2b1c" in buttons[1].text

    def test_checked_buttons(self) -> None:
        ms = Multiselect("Tags:", a="Alpha", b="Beta")
        ctx = _make_ctx(field_name="tags", current_value=Some("a"))
        _, kb = asyncio.run(ms.render(ctx))
        assert kb is not None
        markup = kb.get_markup()
        buttons = [b for row in markup.inline_keyboard for b in row]
        assert "\u2705" in buttons[0].text  # checked
        assert "\u2b1c" in buttons[1].text  # unchecked

    def test_done_button(self) -> None:
        import json
        ms = Multiselect("Tags:", a="Alpha", b="Beta")
        ctx = _make_ctx(field_name="tags")
        _, kb = asyncio.run(ms.render(ctx))
        assert kb is not None
        markup = kb.get_markup()
        buttons = [b for row in markup.inline_keyboard for b in row]
        done_btn = buttons[-1]
        assert "Done" in done_btn.text
        data = json.loads(done_btn.callback_data.unwrap())
        assert data["value"] == "ms:done"

    def test_returns_keyboard_unchecked(self) -> None:
        ms = Multiselect("Tags:", a="A", b="B")
        ctx = _make_ctx(field_name="tags")
        text, kb = asyncio.run(ms.render(ctx))
        assert text == "Tags:"
        assert kb is not None
        buttons = [b for row in kb.get_markup().inline_keyboard for b in row]
        assert all("\u2b1c" in b.text for b in buttons[:-1])

    def test_reads_selected_from_state(self) -> None:
        ms = Multiselect("Tags:", a="A", b="B")
        ctx = _make_ctx(field_name="tags", current_value=Some("a"))
        _, kb = asyncio.run(ms.render(ctx))
        assert kb is not None
        buttons = [b for row in kb.get_markup().inline_keyboard for b in row]
        assert "\u2705" in buttons[0].text  # 'a' checked
        assert "\u2b1c" in buttons[1].text  # 'b' unchecked


# ═══════════════════════════════════════════════════════════════════════════════
# with_show_mode / with_launch_mode transforms
# ═══════════════════════════════════════════════════════════════════════════════


class TestWithShowMode:
    def test_sets_show_mode(self) -> None:
        step = FlowSurfaceStep(command="x", key_node=FakeKeyNode, capabilities=())
        result = with_show_mode(ShowMode.EDIT)((step,))
        assert result[0].show_mode is ShowMode.EDIT

    def test_default_is_send(self) -> None:
        step = FlowSurfaceStep(command="x", key_node=FakeKeyNode, capabilities=())
        assert step.show_mode is ShowMode.SEND

    def test_passes_through_non_flow_steps(self) -> None:
        sentinel = object()
        step = FlowSurfaceStep(command="x", key_node=FakeKeyNode, capabilities=())
        result = with_show_mode(ShowMode.EDIT)((sentinel, step))
        assert result[0] is sentinel
        assert result[1].show_mode is ShowMode.EDIT


class TestWithLaunchMode:
    def test_sets_launch_mode(self) -> None:
        step = FlowSurfaceStep(command="x", key_node=FakeKeyNode, capabilities=())
        result = with_launch_mode(LaunchMode.EXCLUSIVE)((step,))
        assert result[0].launch_mode is LaunchMode.EXCLUSIVE

    def test_default_is_standard(self) -> None:
        step = FlowSurfaceStep(command="x", key_node=FakeKeyNode, capabilities=())
        assert step.launch_mode is LaunchMode.STANDARD

    def test_all_modes(self) -> None:
        step = FlowSurfaceStep(command="x", key_node=FakeKeyNode, capabilities=())
        for mode in LaunchMode:
            result = with_launch_mode(mode)((step,))
            assert result[0].launch_mode is mode


# ═══════════════════════════════════════════════════════════════════════════════
# End-to-end: Counter / Multiselect produce correct exposures
# ═══════════════════════════════════════════════════════════════════════════════


class TestCounterEndToEnd:
    def test_counter_flow_two_exposures(self) -> None:
        @dataclass
        class E:
            id: Annotated[int, Identity]
            qty: Annotated[int, Counter("How many?")]

            async def finish(self) -> Result[FinishResult, DomainError]:
                return Ok(FinishResult.message("done"))

        pattern = tg_flow(command="count", key_node=FakeKeyNode)
        endpoints = derive_endpoints(E, pattern)
        assert len(endpoints) == 1
        # Counter needs callback_query → 2 exposures (message + callback_query)
        assert len(endpoints[0].exposures) == 2
        views = {e.trigger.view for e in endpoints[0].exposures}
        assert views == {"message", "callback_query"}


class TestMultiselectEndToEnd:
    def test_multiselect_flow_two_exposures(self) -> None:
        @dataclass
        class E:
            id: Annotated[int, Identity]
            tags: Annotated[str, Multiselect("Tags:", a="A", b="B")]

            async def finish(self) -> Result[FinishResult, DomainError]:
                return Ok(FinishResult.message("done"))

        pattern = tg_flow(command="select", key_node=FakeKeyNode)
        endpoints = derive_endpoints(E, pattern)
        assert len(endpoints) == 1
        assert len(endpoints[0].exposures) == 2
        views = {e.trigger.view for e in endpoints[0].exposures}
        assert views == {"message", "callback_query"}


class TestFlowClassWithMsgId:
    """Verify _msg_id field is added to generated flow class."""

    def test_has_msg_id_field(self) -> None:
        @dataclass
        class E:
            name: Annotated[str, TextInput("Name?")]

        fields = _classify_fields(E)
        from derivelib._codegen import create_dataclass as _cd
        op_type = _cd("Op", [("name", str)], frozen=True)
        flow_cls = _generate_flow_class(E, fields, op_type, "hash1")
        inst = flow_cls()
        assert getattr(inst, "_msg_id") == 0

    def test_msg_id_in_counter_flow(self) -> None:
        @dataclass
        class E:
            qty: Annotated[int, Counter("Qty:")]

        fields = _classify_fields(E)
        from derivelib._codegen import create_dataclass as _cd
        op_type = _cd("Op", [("qty", int)], frozen=True)
        flow_cls = _generate_flow_class(E, fields, op_type, "hash1")
        inst = flow_cls()
        assert getattr(inst, "_msg_id") == 0


class TestShowModeOnPattern:
    def test_tg_flow_accepts_show_mode(self) -> None:
        p = tg_flow(command="x", key_node=FakeKeyNode, show_mode=ShowMode.EDIT)
        assert p.show_mode is ShowMode.EDIT

    def test_tg_flow_default_send(self) -> None:
        p = tg_flow(command="x", key_node=FakeKeyNode)
        assert p.show_mode is ShowMode.SEND


class TestLaunchModeOnPattern:
    def test_tg_flow_accepts_launch_mode(self) -> None:
        p = tg_flow(command="x", key_node=FakeKeyNode, launch_mode=LaunchMode.EXCLUSIVE)
        assert p.launch_mode is LaunchMode.EXCLUSIVE

    def test_tg_flow_default_standard(self) -> None:
        p = tg_flow(command="x", key_node=FakeKeyNode)
        assert p.launch_mode is LaunchMode.STANDARD


# ═══════════════════════════════════════════════════════════════════════════════
# FlowWidget protocol tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestFlowWidgetProtocol:
    """Verify all widget types satisfy isinstance(w, FlowWidget)."""

    def test_text_input_is_flow_widget(self) -> None:
        assert isinstance(TextInput("Name?"), FlowWidget)

    def test_inline_is_flow_widget(self) -> None:
        assert isinstance(Inline("Role?", admin="Admin"), FlowWidget)

    def test_confirm_is_flow_widget(self) -> None:
        assert isinstance(Confirm("OK?"), FlowWidget)

    def test_counter_is_flow_widget(self) -> None:
        assert isinstance(Counter("Qty:"), FlowWidget)

    def test_multiselect_is_flow_widget(self) -> None:
        assert isinstance(Multiselect("Tags:", a="A"), FlowWidget)

    def test_prefilled_is_not_flow_widget(self) -> None:
        assert not isinstance(Prefilled(), FlowWidget)


class TestWidgetNeedsCallback:
    def test_text_input_no_callback(self) -> None:
        assert TextInput("X").needs_callback is False

    def test_inline_needs_callback(self) -> None:
        assert Inline("X", a="A").needs_callback is True

    def test_confirm_needs_callback(self) -> None:
        assert Confirm("X").needs_callback is True

    def test_counter_needs_callback(self) -> None:
        assert Counter("X").needs_callback is True

    def test_multiselect_needs_callback(self) -> None:
        assert Multiselect("X", a="A").needs_callback is True


class TestWidgetHandleMessage:
    """TextInput returns Advance, button-based widgets return Reject."""

    def test_text_input_advance(self) -> None:
        ti = TextInput("Name?")
        ctx = _make_ctx(base_type=str)
        result = asyncio.run(ti.handle_message(_mock_message(text="Alice"), ctx))
        assert isinstance(result, Advance)
        assert result.value == "Alice"

    def test_text_input_int_coerce(self) -> None:
        ti = TextInput("Age?")
        ctx = _make_ctx(base_type=int)
        result = asyncio.run(ti.handle_message(_mock_message(text="25"), ctx))
        assert isinstance(result, Advance)
        assert result.value == 25

    def test_text_input_int_reject(self) -> None:
        ti = TextInput("Age?")
        ctx = _make_ctx(base_type=int)
        result = asyncio.run(ti.handle_message(_mock_message(text="abc"), ctx))
        assert isinstance(result, Reject)

    def test_text_input_validation_reject(self) -> None:
        ti = TextInput("Name?")
        ctx = _make_ctx(base_type=str, validators=(MinLen(3),))
        result = asyncio.run(ti.handle_message(_mock_message(text="ab"), ctx))
        assert isinstance(result, Reject)

    def test_text_input_no_text_reject(self) -> None:
        ti = TextInput("Name?")
        ctx = _make_ctx(base_type=str)
        result = asyncio.run(ti.handle_message(_mock_message(), ctx))
        assert isinstance(result, Reject)

    def test_inline_rejects_message(self) -> None:
        il = Inline("Role?", admin="Admin")
        ctx = _make_ctx()
        result = asyncio.run(il.handle_message(_mock_message(text="admin"), ctx))
        assert isinstance(result, Reject)

    def test_confirm_rejects_message(self) -> None:
        c = Confirm("OK?")
        ctx = _make_ctx()
        result = asyncio.run(c.handle_message(_mock_message(text="yes"), ctx))
        assert isinstance(result, Reject)

    def test_counter_rejects_message(self) -> None:
        c = Counter("Qty:")
        ctx = _make_ctx()
        result = asyncio.run(c.handle_message(_mock_message(text="5"), ctx))
        assert isinstance(result, Reject)

    def test_multiselect_rejects_message(self) -> None:
        ms = Multiselect("Tags:", a="A")
        ctx = _make_ctx()
        result = asyncio.run(ms.handle_message(_mock_message(text="a"), ctx))
        assert isinstance(result, Reject)


class TestWidgetHandleCallback:
    """Widget callback handling returns appropriate result types."""

    def test_inline_advance(self) -> None:
        il = Inline("Role?", admin="Admin", user="User")
        ctx = _make_ctx()
        result = asyncio.run(il.handle_callback("admin", ctx))
        assert isinstance(result, Advance)
        assert result.value == "admin"
        assert "Admin" in result.summary

    def test_inline_unknown_noop(self) -> None:
        il = Inline("Role?", admin="Admin")
        ctx = _make_ctx()
        result = asyncio.run(il.handle_callback("unknown", ctx))
        assert isinstance(result, NoOp)

    def test_confirm_yes(self) -> None:
        c = Confirm("OK?")
        ctx = _make_ctx()
        result = asyncio.run(c.handle_callback("yes", ctx))
        assert isinstance(result, Advance)
        assert result.value is True

    def test_confirm_no(self) -> None:
        c = Confirm("OK?")
        ctx = _make_ctx()
        result = asyncio.run(c.handle_callback("no", ctx))
        assert isinstance(result, Advance)
        assert result.value is False

    def test_counter_inc(self) -> None:
        c = Counter("Qty:", min=0, max=10, step=1, default=5)
        ctx = _make_ctx(current_value=Some(5))
        result = asyncio.run(c.handle_callback("counter:inc", ctx))
        assert isinstance(result, Stay)
        assert result.new_value == 6

    def test_counter_dec(self) -> None:
        c = Counter("Qty:", min=0, max=10, step=1, default=5)
        ctx = _make_ctx(current_value=Some(5))
        result = asyncio.run(c.handle_callback("counter:dec", ctx))
        assert isinstance(result, Stay)
        assert result.new_value == 4

    def test_counter_done(self) -> None:
        c = Counter("Qty:", default=5)
        ctx = _make_ctx(current_value=Some(5))
        result = asyncio.run(c.handle_callback("counter:done", ctx))
        assert isinstance(result, Advance)
        assert result.value == 5

    def test_counter_noop(self) -> None:
        c = Counter("Qty:")
        ctx = _make_ctx()
        result = asyncio.run(c.handle_callback("counter:noop", ctx))
        assert isinstance(result, NoOp)

    def test_counter_clamp_max(self) -> None:
        c = Counter("Qty:", min=0, max=10, step=5)
        ctx = _make_ctx(current_value=Some(8))
        result = asyncio.run(c.handle_callback("counter:inc", ctx))
        assert isinstance(result, Stay)
        assert result.new_value == 10

    def test_counter_clamp_min(self) -> None:
        c = Counter("Qty:", min=0, max=10, step=5)
        ctx = _make_ctx(current_value=Some(3))
        result = asyncio.run(c.handle_callback("counter:dec", ctx))
        assert isinstance(result, Stay)
        assert result.new_value == 0

    def test_multiselect_toggle_on(self) -> None:
        ms = Multiselect("Tags:", a="A", b="B")
        ctx = _make_ctx()
        result = asyncio.run(ms.handle_callback("ms:a", ctx))
        assert isinstance(result, Stay)
        assert result.new_value == "a"

    def test_multiselect_toggle_off(self) -> None:
        ms = Multiselect("Tags:", a="A", b="B")
        ctx = _make_ctx(current_value=Some("a"))
        result = asyncio.run(ms.handle_callback("ms:a", ctx))
        assert isinstance(result, Stay)
        assert result.new_value == ""

    def test_multiselect_max_reject(self) -> None:
        ms = Multiselect("Tags:", max_selected=1, a="A", b="B")
        ctx = _make_ctx(current_value=Some("a"))
        result = asyncio.run(ms.handle_callback("ms:b", ctx))
        assert isinstance(result, Reject)

    def test_multiselect_done_advance(self) -> None:
        ms = Multiselect("Tags:", a="A", b="B")
        ctx = _make_ctx(current_value=Some("a,b"))
        result = asyncio.run(ms.handle_callback("ms:done", ctx))
        assert isinstance(result, Advance)
        assert "a" in result.value
        assert "b" in result.value

    def test_multiselect_min_reject(self) -> None:
        ms = Multiselect("Tags:", min_selected=1, a="A", b="B")
        ctx = _make_ctx()
        result = asyncio.run(ms.handle_callback("ms:done", ctx))
        assert isinstance(result, Reject)

    def test_text_input_rejects_callback(self) -> None:
        ti = TextInput("Name?")
        ctx = _make_ctx()
        result = asyncio.run(ti.handle_callback("anything", ctx))
        assert isinstance(result, Reject)


# ═══════════════════════════════════════════════════════════════════════════════
# PhotoInput widget
# ═══════════════════════════════════════════════════════════════════════════════


class TestPhotoInput:
    def test_construction(self) -> None:
        pi = PhotoInput("Send photo:")
        assert pi.prompt == "Send photo:"
        assert pi.needs_callback is False

    def test_is_flow_widget(self) -> None:
        assert isinstance(PhotoInput("X"), FlowWidget)

    def test_render(self) -> None:
        pi = PhotoInput("Send photo:")
        ctx = _make_ctx()
        text, kb = asyncio.run(pi.render(ctx))
        assert text == "Send photo:"
        assert kb is None

    def test_handle_message_with_photo(self) -> None:
        pi = PhotoInput("Send photo:")
        ctx = _make_ctx()
        photo = MagicMock()
        photo.file_id = "photo_file_123"
        result = asyncio.run(pi.handle_message(_mock_message(photo=[photo]), ctx))
        assert isinstance(result, Advance)
        assert result.value == "photo_file_123"

    def test_handle_message_no_photo_reject(self) -> None:
        pi = PhotoInput("Send photo:")
        ctx = _make_ctx()
        result = asyncio.run(pi.handle_message(_mock_message(text="hello"), ctx))
        assert isinstance(result, Reject)

    def test_handle_callback_reject(self) -> None:
        pi = PhotoInput("Send photo:")
        ctx = _make_ctx()
        result = asyncio.run(pi.handle_callback("anything", ctx))
        assert isinstance(result, Reject)


# ═══════════════════════════════════════════════════════════════════════════════
# DocumentInput widget
# ═══════════════════════════════════════════════════════════════════════════════


class TestDocumentInput:
    def test_construction(self) -> None:
        di = DocumentInput("Upload file:")
        assert di.prompt == "Upload file:"
        assert di.needs_callback is False

    def test_is_flow_widget(self) -> None:
        assert isinstance(DocumentInput("X"), FlowWidget)

    def test_handle_message_with_document(self) -> None:
        di = DocumentInput("Upload file:")
        ctx = _make_ctx()
        doc = MagicMock()
        doc.file_id = "doc_file_456"
        result = asyncio.run(di.handle_message(_mock_message(document=doc), ctx))
        assert isinstance(result, Advance)
        assert result.value == "doc_file_456"

    def test_handle_message_no_document_reject(self) -> None:
        di = DocumentInput("Upload file:")
        ctx = _make_ctx()
        result = asyncio.run(di.handle_message(_mock_message(text="hello"), ctx))
        assert isinstance(result, Reject)


# ═══════════════════════════════════════════════════════════════════════════════
# LocationInput widget
# ═══════════════════════════════════════════════════════════════════════════════


class TestLocationInput:
    def test_construction(self) -> None:
        li = LocationInput("Share location:")
        assert li.prompt == "Share location:"
        assert li.needs_callback is False

    def test_is_flow_widget(self) -> None:
        assert isinstance(LocationInput("X"), FlowWidget)

    def test_handle_message_with_location(self) -> None:
        li = LocationInput("Share location:")
        ctx = _make_ctx()
        loc = MagicMock()
        loc.latitude = 55.7558
        loc.longitude = 37.6173
        result = asyncio.run(li.handle_message(_mock_message(location=loc), ctx))
        assert isinstance(result, Advance)
        assert result.value == (55.7558, 37.6173)

    def test_handle_message_no_location_reject(self) -> None:
        li = LocationInput("Share location:")
        ctx = _make_ctx()
        result = asyncio.run(li.handle_message(_mock_message(text="hello"), ctx))
        assert isinstance(result, Reject)


# ═══════════════════════════════════════════════════════════════════════════════
# Radio widget
# ═══════════════════════════════════════════════════════════════════════════════


class TestRadio:
    def test_construction(self) -> None:
        r = Radio("Role:", admin="Admin", user="User")
        assert r.prompt == "Role:"
        assert r.options == {"admin": "Admin", "user": "User"}
        assert r.needs_callback is True

    def test_is_flow_widget(self) -> None:
        assert isinstance(Radio("X", a="A"), FlowWidget)

    def test_render_has_done_button(self) -> None:
        r = Radio("Role:", admin="Admin", user="User")
        ctx = _make_ctx()
        _, kb = asyncio.run(r.render(ctx))
        assert kb is not None
        buttons = [b for row in kb.get_markup().inline_keyboard for b in row]
        assert any("Done" in b.text for b in buttons)

    def test_select_returns_stay(self) -> None:
        r = Radio("Role:", admin="Admin", user="User")
        ctx = _make_ctx()
        result = asyncio.run(r.handle_callback("radio:admin", ctx))
        assert isinstance(result, Stay)
        assert result.new_value == "admin"

    def test_done_without_selection_reject(self) -> None:
        r = Radio("Role:", admin="Admin", user="User")
        ctx = _make_ctx()
        result = asyncio.run(r.handle_callback("radio:done", ctx))
        assert isinstance(result, Reject)

    def test_done_with_selection_advance(self) -> None:
        r = Radio("Role:", admin="Admin", user="User")
        ctx = _make_ctx(current_value=Some("admin"))
        result = asyncio.run(r.handle_callback("radio:done", ctx))
        assert isinstance(result, Advance)
        assert result.value == "admin"
        assert "Admin" in result.summary

    def test_rejects_message(self) -> None:
        r = Radio("Role:", admin="Admin")
        ctx = _make_ctx()
        result = asyncio.run(r.handle_message(_mock_message(text="admin"), ctx))
        assert isinstance(result, Reject)


# ═══════════════════════════════════════════════════════════════════════════════
# DatePicker widget
# ═══════════════════════════════════════════════════════════════════════════════


class TestDatePicker:
    def test_construction(self) -> None:
        dp = DatePicker("When?")
        assert dp.prompt == "When?"
        assert dp.needs_callback is True

    def test_is_flow_widget(self) -> None:
        assert isinstance(DatePicker("X"), FlowWidget)

    def test_render_day_view(self) -> None:
        dp = DatePicker("When?")
        ctx = _make_ctx()
        text, kb = asyncio.run(dp.render(ctx))
        assert text == "When?"
        assert kb is not None

    def test_prev_month_stay(self) -> None:
        dp = DatePicker("When?")
        ctx = _make_ctx(current_value=Some({"year": 2024, "month": 3, "view": "day"}))
        result = asyncio.run(dp.handle_callback("dp:pm", ctx))
        assert isinstance(result, Stay)
        vs = result.new_value
        assert vs["month"] == 2
        assert vs["year"] == 2024

    def test_next_month_stay(self) -> None:
        dp = DatePicker("When?")
        ctx = _make_ctx(current_value=Some({"year": 2024, "month": 12, "view": "day"}))
        result = asyncio.run(dp.handle_callback("dp:nm", ctx))
        assert isinstance(result, Stay)
        vs = result.new_value
        assert vs["month"] == 1
        assert vs["year"] == 2025

    def test_select_day_advance(self) -> None:
        dp = DatePicker("When?")
        ctx = _make_ctx(current_value=Some({"year": 2024, "month": 3, "view": "day"}))
        result = asyncio.run(dp.handle_callback("dp:d:2024-03-15", ctx))
        assert isinstance(result, Advance)
        assert result.value == date(2024, 3, 15)

    def test_month_view_switch(self) -> None:
        dp = DatePicker("When?")
        ctx = _make_ctx(current_value=Some({"year": 2024, "month": 3, "view": "day"}))
        result = asyncio.run(dp.handle_callback("dp:mv", ctx))
        assert isinstance(result, Stay)
        assert result.new_value["view"] == "month"

    def test_select_month_back_to_day(self) -> None:
        dp = DatePicker("When?")
        ctx = _make_ctx(current_value=Some({"year": 2024, "month": 3, "view": "month"}))
        result = asyncio.run(dp.handle_callback("dp:m:6", ctx))
        assert isinstance(result, Stay)
        assert result.new_value["month"] == 6
        assert result.new_value["view"] == "day"

    def test_noop(self) -> None:
        dp = DatePicker("When?")
        ctx = _make_ctx()
        result = asyncio.run(dp.handle_callback("dp:noop", ctx))
        assert isinstance(result, NoOp)

    def test_rejects_message(self) -> None:
        dp = DatePicker("When?")
        ctx = _make_ctx()
        result = asyncio.run(dp.handle_message(_mock_message(text="hello"), ctx))
        assert isinstance(result, Reject)


# ═══════════════════════════════════════════════════════════════════════════════
# ScrollingInline widget
# ═══════════════════════════════════════════════════════════════════════════════


class TestScrollingInline:
    def test_construction(self) -> None:
        si = ScrollingInline("Category:", page_size=3, a="A", b="B", c="C", d="D")
        assert si.prompt == "Category:"
        assert si.page_size == 3
        assert si.needs_callback is True

    def test_is_flow_widget(self) -> None:
        assert isinstance(ScrollingInline("X", a="A"), FlowWidget)

    def test_render_first_page(self) -> None:
        si = ScrollingInline("Category:", page_size=2, a="A", b="B", c="C", d="D")
        ctx = _make_ctx()
        text, kb = asyncio.run(si.render(ctx))
        assert text == "Category:"
        assert kb is not None

    def test_next_page_stay(self) -> None:
        si = ScrollingInline("X", page_size=2, a="A", b="B", c="C")
        ctx = _make_ctx(current_value=Some(0))
        result = asyncio.run(si.handle_callback("si:next", ctx))
        assert isinstance(result, Stay)
        assert result.new_value == 1

    def test_prev_page_stay(self) -> None:
        si = ScrollingInline("X", page_size=2, a="A", b="B", c="C")
        ctx = _make_ctx(current_value=Some(1))
        result = asyncio.run(si.handle_callback("si:prev", ctx))
        assert isinstance(result, Stay)
        assert result.new_value == 0

    def test_select_option_advance(self) -> None:
        si = ScrollingInline("X", a="Alpha", b="Beta")
        ctx = _make_ctx()
        result = asyncio.run(si.handle_callback("a", ctx))
        assert isinstance(result, Advance)
        assert result.value == "a"
        assert "Alpha" in result.summary

    def test_noop(self) -> None:
        si = ScrollingInline("X", a="A")
        ctx = _make_ctx()
        result = asyncio.run(si.handle_callback("si:noop", ctx))
        assert isinstance(result, NoOp)

    def test_rejects_message(self) -> None:
        si = ScrollingInline("X", a="A")
        ctx = _make_ctx()
        result = asyncio.run(si.handle_message(_mock_message(text="a"), ctx))
        assert isinstance(result, Reject)


# ═══════════════════════════════════════════════════════════════════════════════
# Case widget
# ═══════════════════════════════════════════════════════════════════════════════


class TestCase:
    def test_construction(self) -> None:
        c = Case("status", active="Active!", archived="Archived.")
        assert c.selector == "status"
        assert c.options == {"active": "Active!", "archived": "Archived."}
        assert c.needs_callback is True

    def test_is_flow_widget(self) -> None:
        assert isinstance(Case("sel", a="A"), FlowWidget)

    def test_render_resolves_text(self) -> None:
        c = Case("status", active="Active!", archived="Archived.")
        ctx = _make_ctx(flow_state={"status": "active"})
        text, kb = asyncio.run(c.render(ctx))
        assert text == "Active!"
        assert kb is not None

    def test_render_no_match(self) -> None:
        c = Case("status", active="Active!")
        ctx = _make_ctx(flow_state={"status": "unknown"})
        text, kb = asyncio.run(c.render(ctx))
        assert "no variant" in text

    def test_callback_ok_advance(self) -> None:
        c = Case("status", active="Active!")
        ctx = _make_ctx(flow_state={"status": "active"})
        result = asyncio.run(c.handle_callback("case:ok", ctx))
        assert isinstance(result, Advance)
        assert result.value == "Active!"

    def test_message_also_advances(self) -> None:
        c = Case("status", active="Active!")
        ctx = _make_ctx(flow_state={"status": "active"})
        result = asyncio.run(c.handle_message(_mock_message(text="anything"), ctx))
        assert isinstance(result, Advance)


# ═══════════════════════════════════════════════════════════════════════════════
# New widget FlowWidget protocol checks
# ═══════════════════════════════════════════════════════════════════════════════


class TestNewWidgetProtocol:
    def test_photo_input_is_flow_widget(self) -> None:
        assert isinstance(PhotoInput("X"), FlowWidget)

    def test_document_input_is_flow_widget(self) -> None:
        assert isinstance(DocumentInput("X"), FlowWidget)

    def test_location_input_is_flow_widget(self) -> None:
        assert isinstance(LocationInput("X"), FlowWidget)

    def test_radio_is_flow_widget(self) -> None:
        assert isinstance(Radio("X", a="A"), FlowWidget)

    def test_date_picker_is_flow_widget(self) -> None:
        assert isinstance(DatePicker("X"), FlowWidget)

    def test_scrolling_inline_is_flow_widget(self) -> None:
        assert isinstance(ScrollingInline("X", a="A"), FlowWidget)

    def test_case_is_flow_widget(self) -> None:
        assert isinstance(Case("sel", a="A"), FlowWidget)


# ═══════════════════════════════════════════════════════════════════════════════
# New widget needs_callback checks
# ═══════════════════════════════════════════════════════════════════════════════


class TestNewWidgetNeedsCallback:
    def test_photo_input_no_callback(self) -> None:
        assert PhotoInput("X").needs_callback is False

    def test_document_input_no_callback(self) -> None:
        assert DocumentInput("X").needs_callback is False

    def test_location_input_no_callback(self) -> None:
        assert LocationInput("X").needs_callback is False

    def test_radio_needs_callback(self) -> None:
        assert Radio("X", a="A").needs_callback is True

    def test_date_picker_needs_callback(self) -> None:
        assert DatePicker("X").needs_callback is True

    def test_scrolling_inline_needs_callback(self) -> None:
        assert ScrollingInline("X", a="A").needs_callback is True

    def test_case_needs_callback(self) -> None:
        assert Case("sel", a="A").needs_callback is True


# ═══════════════════════════════════════════════════════════════════════════════
# StackFrame.result field
# ═══════════════════════════════════════════════════════════════════════════════


class TestStackFrameResult:
    def test_default_result_none(self) -> None:
        f = StackFrame(command="test")
        assert f.result is None

    def test_result_preserved(self) -> None:
        f = StackFrame(command="test", result={"key": "value"})
        assert f.result == {"key": "value"}


# ═══════════════════════════════════════════════════════════════════════════════
# ShowMode.DELETE_AND_SEND
# ═══════════════════════════════════════════════════════════════════════════════


class TestDeleteAndSend:
    def test_with_show_mode_delete_and_send(self) -> None:
        step = FlowSurfaceStep(command="x", key_node=FakeKeyNode, capabilities=())
        result = with_show_mode(ShowMode.DELETE_AND_SEND)((step,))
        assert result[0].show_mode is ShowMode.DELETE_AND_SEND

    def test_tg_flow_accepts_delete_and_send(self) -> None:
        p = tg_flow(command="x", key_node=FakeKeyNode, show_mode=ShowMode.DELETE_AND_SEND)
        assert p.show_mode is ShowMode.DELETE_AND_SEND


# ═══════════════════════════════════════════════════════════════════════════════
# Browse exports
# ═══════════════════════════════════════════════════════════════════════════════


class TestBrowseExports:
    def test_view_filter_importable(self) -> None:
        from derivelib.patterns.tg.browse import view_filter
        assert callable(view_filter)

    def test_browse_session_importable(self) -> None:
        from derivelib.patterns.tg.browse import BrowseSession
        s = BrowseSession()
        assert s.page == 0
        assert s.filter_key == ""
        assert s.search_query == ""

    def test_view_filter_stacks(self) -> None:
        from derivelib.patterns.tg.browse import view_filter, VIEW_FILTER_ATTR

        @view_filter("Active", key="active")
        @view_filter("Done", key="done")
        def my_query() -> None:
            pass

        filters = getattr(my_query, VIEW_FILTER_ATTR)
        assert len(filters) == 2
        keys = [f.key for f in filters]
        assert "done" in keys
        assert "active" in keys

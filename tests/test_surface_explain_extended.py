"""Extended tests for emergent/wire/axis/surface/_explain.py — coverage gaps.

Covers missed lines:
- _explain_telegrinder_trigger (TelegrinderTrigger handler)
- _explain_event_trigger (EventTrigger handler)
- _explain_stateful (StatefulCodec handler)
- _explain_immediate_factory (ImmediateFactoryCodec handler)
- _format_trigger_short for TelegrinderTrigger and EventTrigger
- _format_exposure for StatefulCodec, ImmediateCodec, DelegateCodec detail lines
- _format_value with list/tuple
- _format_obj_short with no rest fields
- HTTP trigger with headers
- explain_endpoint for various codec types
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Self

from kungfu import Result, Ok, Error

from emergent.ops._graph import Op
from emergent.wire.axis.surface._app import application
from emergent.wire.axis.surface._endpoint import endpoint
from emergent.wire.axis.surface._types import Exposure
from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger
from emergent.wire.axis.surface.triggers.cli import CLITrigger
from emergent.wire.axis.surface.triggers.event import EventTrigger
from emergent.wire.axis.surface.codecs.rrc import RequestResponseCodec
from emergent.wire.axis.surface.codecs.immediate import ImmediateFactoryCodec
from emergent.wire.axis.surface.codecs.stateful import StatefulCodec
from emergent.wire.axis.surface._explain import exposure_dict, explain_application, explain_endpoint  # pyright: ignore[reportPrivateUsage] - testing private module
import emergent.wire.axis.surface._explain as _explain_mod  # pyright: ignore[reportPrivateUsage] - testing private helpers
from emergent.ops import ops as _ops
from emergent.wire.axis.storage import MemoryStorage

# Access private helpers through the module. Each line has pyright: ignore
# because these are private functions being tested directly.
_tg_trigger = _explain_mod._explain_telegrinder_trigger  # pyright: ignore[reportPrivateUsage]
_event_trigger = _explain_mod._explain_event_trigger  # pyright: ignore[reportPrivateUsage]
_stateful = _explain_mod._explain_stateful  # pyright: ignore[reportPrivateUsage]
_imm_factory = _explain_mod._explain_immediate_factory  # pyright: ignore[reportPrivateUsage]
_http_trigger = _explain_mod._explain_http_trigger  # pyright: ignore[reportPrivateUsage]
_dc_dict = _explain_mod._dataclass_dict  # pyright: ignore[reportPrivateUsage]
_unk_dict = _explain_mod._unknown_dict  # pyright: ignore[reportPrivateUsage]
_obj_short = _explain_mod._format_obj_short  # pyright: ignore[reportPrivateUsage]
_fval = _explain_mod._format_value  # pyright: ignore[reportPrivateUsage]
_ftrig = _explain_mod._format_trigger_short  # pyright: ignore[reportPrivateUsage]
_fexp = _explain_mod._format_exposure  # pyright: ignore[reportPrivateUsage]


# ============================================================================
# Helpers
# ============================================================================


@dataclass
class _GreetOp(Op[str, str]):
    name: str


def _runner():  # noqa: ANN202
    return _ops().compile()


@dataclass
class Req:
    value: str = ""

    def to_domain(self) -> _GreetOp:
        return _GreetOp(name=self.value)


@dataclass
class Resp:
    result: str = ""

    @classmethod
    def from_domain(cls, dom: Result[str, str]) -> Self:
        match dom:
            case Ok(v):
                return cls(result=v)
            case Error(e):
                return cls(result=e)


@dataclass
class OrderEvent:
    order_id: int


# ============================================================================
# Event Trigger explain
# ============================================================================


class TestExplainEventTrigger:
    def test_event_trigger_dict(self) -> None:
        trigger: EventTrigger[object] = EventTrigger(OrderEvent)
        d = _event_trigger(trigger)
        assert d["type"] == "EventTrigger"
        assert d["event_type"] == "OrderEvent"

    def test_event_trigger_in_exposure(self) -> None:
        exp = Exposure(
            trigger=EventTrigger(OrderEvent),
            codec=RequestResponseCodec(Req, Resp),
        )
        d = exposure_dict(exp)
        assert d["trigger"]["type"] == "EventTrigger"
        assert d["trigger"]["event_type"] == "OrderEvent"

    def test_event_trigger_format_short(self) -> None:
        d = {"type": "EventTrigger", "event_type": "OrderEvent"}
        result = _ftrig(d)
        assert "Event OrderEvent" in result


# ============================================================================
# Telegrinder Trigger explain
# ============================================================================


class TestExplainTelegrinderTrigger:
    def test_telegrinder_trigger_no_rules(self) -> None:
        """TelegrinderTrigger without rules."""
        from emergent.wire.axis.surface.triggers.telegrinder import TelegrinderTrigger

        trigger = TelegrinderTrigger(view="message")
        d = _tg_trigger(trigger)
        assert d["type"] == "TelegrinderTrigger"
        assert d["view"] == "message"
        assert "rules" not in d

    def test_telegrinder_trigger_with_rules(self) -> None:
        """TelegrinderTrigger with mock rules."""
        from emergent.wire.axis.surface.triggers.telegrinder import TelegrinderTrigger
        from telegrinder.bot.rules.abc import ABCRule

        class FakeRule(ABCRule):
            async def check(self, *_args: object, **_kwargs: object) -> bool:
                return True

        trigger = TelegrinderTrigger(FakeRule(), view="callback_query")
        d = _tg_trigger(trigger)
        assert d["type"] == "TelegrinderTrigger"
        assert d["view"] == "callback_query"
        assert "rules" in d
        assert d["rules"] == ["FakeRule"]

    def test_telegrinder_trigger_format_short_with_rules(self) -> None:
        d = {
            "type": "TelegrinderTrigger",
            "view": "message",
            "rules": ["Command", "Text"],
        }
        result = _ftrig(d)
        assert "tg:message(Command, Text)" in result

    def test_telegrinder_trigger_format_short_no_rules(self) -> None:
        d = {"type": "TelegrinderTrigger", "view": "message"}
        result = _ftrig(d)
        assert "tg:message()" in result

    def test_telegrinder_trigger_in_exposure(self) -> None:
        from emergent.wire.axis.surface.triggers.telegrinder import TelegrinderTrigger

        exp = Exposure(
            trigger=TelegrinderTrigger(view="message"),
            codec=RequestResponseCodec(Req, Resp),
        )
        d = exposure_dict(exp)
        assert d["trigger"]["type"] == "TelegrinderTrigger"


# ============================================================================
# Stateful Codec explain
# ============================================================================


class TestExplainStatefulCodec:
    def test_stateful_codec_dict(self) -> None:
        @dataclass
        class BetFlow:
            pass

        class ChatId:
            pass

        codec = StatefulCodec(
            flow=BetFlow,
            response=Resp,
            store=MemoryStorage[str, BetFlow](),
            key_node=ChatId,
            agent_cls=type,
        )
        d = _stateful(codec)
        assert d["type"] == "StatefulCodec"
        assert d["flow"] == "BetFlow"
        assert d["response"] == "Resp"
        assert d["key_node"] == "ChatId"

    def test_stateful_codec_with_non_type_response(self) -> None:
        """When response is not a type (e.g. Union), uses str()."""
        @dataclass
        class MyFlow:
            pass

        class KeyNode:
            pass

        codec = StatefulCodec(
            flow=MyFlow,
            response=Resp | str,
            store=MemoryStorage[str, MyFlow](),
            key_node=KeyNode,
            agent_cls=type,
        )
        d = _stateful(codec)
        assert d["type"] == "StatefulCodec"
        # response is a UnionType, shown as str
        assert "response" in d

    def test_stateful_codec_in_exposure_format(self) -> None:
        """StatefulCodec in _format_exposure shows flow and response."""
        @dataclass
        class MyFlow:
            pass

        class KeyNode:
            pass

        codec = StatefulCodec(
            flow=MyFlow,
            response=Resp,
            store=MemoryStorage[str, MyFlow](),
            key_node=KeyNode,
            agent_cls=type,
        )
        exp = Exposure(
            trigger=HTTPRouteTrigger("POST", "/bet"),
            codec=codec,
        )
        d = exposure_dict(exp)
        assert d["codec"]["type"] == "StatefulCodec"

        # Test formatting
        exp_data = {
            "trigger": {"type": "HTTPRouteTrigger", "method": "POST", "path": "/bet"},
            "codec": {"type": "StatefulCodec", "flow": "MyFlow", "response": "Resp"},
        }
        text = _fexp(exp_data)
        assert "flow: MyFlow" in text
        assert "response: Resp" in text


# ============================================================================
# ImmediateFactory Codec explain
# ============================================================================


class TestExplainImmediateFactoryCodec:
    def test_immediate_factory_dict(self) -> None:
        def my_factory() -> Resp:
            return Resp()

        codec = ImmediateFactoryCodec(factory=my_factory)
        d = _imm_factory(codec)
        assert d["type"] == "ImmediateFactoryCodec"
        assert d["factory"] == "my_factory"

    def test_immediate_factory_lambda(self) -> None:
        def _make_resp() -> Resp:
            return Resp()

        codec = ImmediateFactoryCodec(factory=_make_resp)
        d = _imm_factory(codec)
        assert d["type"] == "ImmediateFactoryCodec"
        # Named function has __name__ = "_make_resp"
        assert "_make_resp" in d["factory"]


# ============================================================================
# Immediate Codec explain
# ============================================================================


class TestExplainImmediateCodec:
    def test_immediate_codec_format_in_exposure(self) -> None:
        """ImmediateCodec in _format_exposure shows response."""
        exp_data = {
            "trigger": {"type": "CLITrigger", "command": "help"},
            "codec": {"type": "ImmediateCodec", "response": "HelpResp"},
        }
        text = _fexp(exp_data)
        assert "response: HelpResp" in text


# ============================================================================
# Delegate Codec explain
# ============================================================================


class TestExplainDelegateCodecFormat:
    def test_delegate_format_in_exposure(self) -> None:
        """DelegateCodec in _format_exposure shows handler."""
        exp_data = {
            "trigger": {"type": "HTTPRouteTrigger", "method": "POST", "path": "/hook"},
            "codec": {"type": "DelegateCodec", "handler": "handle_webhook"},
        }
        text = _fexp(exp_data)
        assert "handler: handle_webhook" in text


# ============================================================================
# HTTP Trigger with headers
# ============================================================================


class TestExplainHTTPTriggerHeaders:
    def test_http_trigger_with_headers(self) -> None:
        trigger = HTTPRouteTrigger("GET", "/data", headers=frozenset({"X-Token", "X-Version"}))
        d = _http_trigger(trigger)
        assert d["type"] == "HTTPRouteTrigger"
        assert "headers" in d
        assert d["headers"] == sorted(["X-Token", "X-Version"])

    def test_http_trigger_without_headers(self) -> None:
        trigger = HTTPRouteTrigger("GET", "/data")
        d = _http_trigger(trigger)
        assert "headers" not in d


# ============================================================================
# Format helpers
# ============================================================================


class TestFormatHelpers:
    def test_format_obj_short_no_fields(self) -> None:
        d = {"type": "EmptyThing"}
        result = _obj_short(d)
        assert result == "EmptyThing"

    def test_format_obj_short_with_fields(self) -> None:
        d = {"type": "Cap", "value": 42}
        result = _obj_short(d)
        assert "Cap" in result
        assert "42" in result

    def test_format_value_list(self) -> None:
        result = _fval(["a", "b", "c"])
        assert "a, b, c" == result

    def test_format_value_tuple(self) -> None:
        result = _fval(("x", "y"))
        assert "x, y" == result

    def test_format_value_scalar(self) -> None:
        result = _fval(42)
        assert result == "42"

    def test_format_value_string(self) -> None:
        result = _fval("hello")
        assert result == "'hello'"

    def test_format_trigger_short_unknown(self) -> None:
        d = {"type": "CustomTrigger", "channel": "live"}
        result = _ftrig(d)
        assert "CustomTrigger" in result


# ============================================================================
# _dataclass_dict and _unknown_dict
# ============================================================================


class TestDataclassDict:
    def test_dataclass_obj(self) -> None:
        @dataclass(frozen=True)
        class Dc:
            x: int
            y: str

        d = _dc_dict(Dc(x=1, y="hi"))
        assert d["type"] == "Dc"
        assert d["x"] == 1
        assert d["y"] == "hi"

    def test_non_dataclass(self) -> None:
        d = _dc_dict("just a string")
        assert d["type"] == "str"

    def test_dataclass_with_type_field(self) -> None:
        """Type-valued fields get __name__."""
        @dataclass(frozen=True)
        class WithType:
            cls: type

        d = _dc_dict(WithType(cls=int))
        assert d["cls"] == "int"

    def test_unknown_dict(self) -> None:
        d = _unk_dict("anything")
        assert d["type"] == "str"


# ============================================================================
# Integration: Full application with all trigger/codec types
# ============================================================================


class TestIntegrationAllTriggerCodecTypes:
    def test_explain_with_event_trigger(self) -> None:
        ep = endpoint(_runner()).expose(
            EventTrigger(OrderEvent),
            RequestResponseCodec(Req, Resp),
        )
        app = application().mount(ep)
        text = explain_application(app)
        assert "Event OrderEvent" in text
        assert "RequestResponseCodec" in text

    def test_explain_with_immediate_factory(self) -> None:
        def make_help() -> Resp:
            return Resp()

        ep = endpoint(_runner()).expose(
            CLITrigger("help"),
            ImmediateFactoryCodec(factory=make_help),
        )
        text = explain_endpoint(ep)
        assert "help (cli)" in text
        assert "ImmediateFactoryCodec" in text

    def test_application_singular_endpoint(self) -> None:
        """Single endpoint => '1 endpoint' (not '1 endpoints')."""
        ep = endpoint(_runner()).expose(
            HTTPRouteTrigger("GET", "/x"),
            RequestResponseCodec(Req, Resp),
        )
        app = application().mount(ep)
        text = explain_application(app)
        assert "1 endpoint)" in text

    def test_application_singular_global_cap(self) -> None:
        """Single global cap => '1 global cap' (not '1 global caps')."""
        @dataclass(frozen=True)
        class OneCap:
            name: str = "single"

        app = application(capabilities=(OneCap(),))
        text = explain_application(app)
        assert "1 global cap)" in text

    def test_application_multiple_global_caps(self) -> None:
        """Multiple global caps => 'N global caps'."""
        @dataclass(frozen=True)
        class CapA:
            name: str = "a"

        @dataclass(frozen=True)
        class CapB:
            name: str = "b"

        app = application(capabilities=(CapA(), CapB()))
        text = explain_application(app)
        assert "2 global caps)" in text

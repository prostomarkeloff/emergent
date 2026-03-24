"""Tests for compile._explain — trace_dict, field_dict, explain, formatters, structured queries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Self

from kungfu import Ok, Result

from emergent.wire.compile._core import Axes
from emergent.wire.compile._trace import ListCollector
from emergent.wire.compile._explain import (
    _get_collector,  # pyright: ignore[reportPrivateUsage] -- testing private helper directly
    trace_dict,
    field_dict,
    type_dict,
    explain,
    explain_field,
    explain_type,
    get_field_trace,
    get_phase_trace,
    changed_fields,
    active_capabilities,
)
from emergent.wire.compile._generate import to_pydantic
from emergent.wire.axis.schema import MaxLen, MinLen, Min, Max
from emergent.ops._graph import Op, ops


# ═══════════════════════════════════════════════════════════════════════════════
# Domain types for tracing
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class TraceUser:
    name: Annotated[str, MinLen(1), MaxLen(100)]
    age: Annotated[int, Min(0), Max(150)]
    bio: str | None = None


@dataclass
class SimpleEntity:
    value: str


# ═══════════════════════════════════════════════════════════════════════════════
# Scan/wrap test types (module-level for get_type_hints compatibility)
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class _PingOp(Op[str, str]):
    pass


@dataclass(frozen=True, slots=True)
class _PingReq:
    def to_domain(self) -> _PingOp:
        return _PingOp()


@dataclass(frozen=True, slots=True)
class _PingResp:
    msg: str

    @classmethod
    def from_domain(cls, dom: Result[str, str]) -> Self:
        match dom:
            case Ok(v):
                return cls(msg=v)
            case _:
                return cls(msg="err")


async def _ping_handler(op: _PingOp) -> Result[str, str]:
    return Ok("pong")


# ═══════════════════════════════════════════════════════════════════════════════
# _get_collector
# ═══════════════════════════════════════════════════════════════════════════════


class TestGetCollector:
    def test_none_when_no_trace(self) -> None:
        axes = Axes.default()
        assert _get_collector(axes) is None

    def test_returns_collector_when_traced(self) -> None:
        collector = ListCollector()
        axes = Axes.traced(collector)
        assert _get_collector(axes) is collector


# ═══════════════════════════════════════════════════════════════════════════════
# trace_dict
# ═══════════════════════════════════════════════════════════════════════════════


class TestTraceDict:
    def test_empty_when_no_trace(self) -> None:
        axes = Axes.default()
        assert trace_dict(axes) == {}

    def test_has_types_scan_wrap_keys(self) -> None:
        collector = ListCollector()
        axes = Axes.traced(collector)
        to_pydantic(TraceUser, axes)
        data = trace_dict(axes)
        assert "types" in data
        assert "scan" in data
        assert "wrap" in data

    def test_type_traces_captured(self) -> None:
        collector = ListCollector()
        axes = Axes.traced(collector)
        to_pydantic(TraceUser, axes)
        data = trace_dict(axes)
        assert len(data["types"]) >= 1
        cls_names = [t["class"] for t in data["types"]]
        assert "TraceUser" in cls_names

    def test_field_traces_in_type(self) -> None:
        collector = ListCollector()
        axes = Axes.traced(collector)
        to_pydantic(TraceUser, axes)
        data = trace_dict(axes)
        user_type = next(t for t in data["types"] if t["class"] == "TraceUser")
        field_names = [f["field"] for f in user_type["fields"]]
        assert "name" in field_names
        assert "age" in field_names


# ═══════════════════════════════════════════════════════════════════════════════
# field_dict
# ═══════════════════════════════════════════════════════════════════════════════


class TestFieldDict:
    def test_returns_none_for_missing_field(self) -> None:
        collector = ListCollector()
        axes = Axes.traced(collector)
        to_pydantic(TraceUser, axes)
        assert field_dict(axes, "nonexistent") is None

    def test_returns_dict_for_existing_field(self) -> None:
        collector = ListCollector()
        axes = Axes.traced(collector)
        to_pydantic(TraceUser, axes)
        result = field_dict(axes, "name")
        assert result is not None
        assert result["field"] == "name"
        assert "capabilities" in result
        assert "phases" in result

    def test_capabilities_listed(self) -> None:
        collector = ListCollector()
        axes = Axes.traced(collector)
        to_pydantic(TraceUser, axes)
        result = field_dict(axes, "name")
        assert result is not None
        assert len(result["capabilities"]) > 0


# ═══════════════════════════════════════════════════════════════════════════════
# type_dict
# ═══════════════════════════════════════════════════════════════════════════════


class TestTypeDict:
    def test_returns_none_for_missing_type(self) -> None:
        collector = ListCollector()
        axes = Axes.traced(collector)
        to_pydantic(TraceUser, axes)
        assert type_dict(axes, "NonExistent") is None

    def test_returns_dict_for_existing_type(self) -> None:
        collector = ListCollector()
        axes = Axes.traced(collector)
        to_pydantic(TraceUser, axes)
        result = type_dict(axes, "TraceUser")
        assert result is not None
        assert result["class"] == "TraceUser"
        assert "fields" in result

    def test_returns_none_when_no_trace(self) -> None:
        axes = Axes.default()
        assert type_dict(axes, "TraceUser") is None


# ═══════════════════════════════════════════════════════════════════════════════
# explain (human-readable)
# ═══════════════════════════════════════════════════════════════════════════════


class TestExplain:
    def test_no_tracing_message(self) -> None:
        axes = Axes.default()
        result = explain(axes)
        assert "tracing not enabled" in result

    def test_contains_type_name(self) -> None:
        collector = ListCollector()
        axes = Axes.traced(collector)
        to_pydantic(TraceUser, axes)
        result = explain(axes)
        assert "TraceUser" in result

    def test_contains_field_names(self) -> None:
        collector = ListCollector()
        axes = Axes.traced(collector)
        to_pydantic(TraceUser, axes)
        result = explain(axes)
        assert "name" in result
        assert "age" in result


# ═══════════════════════════════════════════════════════════════════════════════
# explain_field
# ═══════════════════════════════════════════════════════════════════════════════


class TestExplainField:
    def test_missing_field_message(self) -> None:
        collector = ListCollector()
        axes = Axes.traced(collector)
        to_pydantic(TraceUser, axes)
        result = explain_field(axes, "missing")
        assert "not found" in result

    def test_existing_field_has_content(self) -> None:
        collector = ListCollector()
        axes = Axes.traced(collector)
        to_pydantic(TraceUser, axes)
        result = explain_field(axes, "name")
        assert "name" in result


# ═══════════════════════════════════════════════════════════════════════════════
# explain_type
# ═══════════════════════════════════════════════════════════════════════════════


class TestExplainType:
    def test_missing_type_message(self) -> None:
        collector = ListCollector()
        axes = Axes.traced(collector)
        to_pydantic(TraceUser, axes)
        result = explain_type(axes, "Missing")
        assert "not found" in result

    def test_existing_type_has_content(self) -> None:
        collector = ListCollector()
        axes = Axes.traced(collector)
        to_pydantic(TraceUser, axes)
        result = explain_type(axes, "TraceUser")
        assert "TraceUser" in result


# ═══════════════════════════════════════════════════════════════════════════════
# Structured queries: get_field_trace, get_phase_trace, changed_fields, active_capabilities
# ═══════════════════════════════════════════════════════════════════════════════


class TestStructuredQuery:
    def test_get_field_trace_found(self) -> None:
        collector = ListCollector()
        axes = Axes.traced(collector)
        to_pydantic(TraceUser, axes)
        ft = get_field_trace(axes, "name")
        assert ft is not None
        assert ft.field_name == "name"

    def test_get_field_trace_not_found(self) -> None:
        collector = ListCollector()
        axes = Axes.traced(collector)
        to_pydantic(TraceUser, axes)
        assert get_field_trace(axes, "missing") is None

    def test_get_field_trace_no_collector(self) -> None:
        axes = Axes.default()
        assert get_field_trace(axes, "name") is None

    def test_get_phase_trace_found(self) -> None:
        collector = ListCollector()
        axes = Axes.traced(collector)
        to_pydantic(TraceUser, axes)
        fpt = get_phase_trace(axes, "name", "PydanticContext")
        assert fpt is not None
        assert fpt.phase == "PydanticContext"

    def test_get_phase_trace_missing_field(self) -> None:
        collector = ListCollector()
        axes = Axes.traced(collector)
        to_pydantic(TraceUser, axes)
        assert get_phase_trace(axes, "missing", "PydanticContext") is None

    def test_get_phase_trace_missing_phase(self) -> None:
        collector = ListCollector()
        axes = Axes.traced(collector)
        to_pydantic(TraceUser, axes)
        assert get_phase_trace(axes, "name", "nonexistent_phase") is None

    def test_changed_fields_no_collector(self) -> None:
        axes = Axes.default()
        assert changed_fields(axes, "PydanticContext") == []

    def test_changed_fields_returns_changed(self) -> None:
        collector = ListCollector()
        axes = Axes.traced(collector)
        to_pydantic(TraceUser, axes)
        result = changed_fields(axes, "PydanticContext")
        # name and age have capabilities that change pydantic context
        assert isinstance(result, list)

    def test_active_capabilities_no_field(self) -> None:
        collector = ListCollector()
        axes = Axes.traced(collector)
        to_pydantic(TraceUser, axes)
        assert active_capabilities(axes, "missing") == []

    def test_active_capabilities_for_annotated_field(self) -> None:
        collector = ListCollector()
        axes = Axes.traced(collector)
        to_pydantic(TraceUser, axes)
        caps = active_capabilities(axes, "name")
        # name has MinLen and MaxLen
        assert len(caps) > 0


# ═══════════════════════════════════════════════════════════════════════════════
# Scan / wrap event formatting
# ═══════════════════════════════════════════════════════════════════════════════


class TestScanWrapFormatting:
    """Covers _scan_dict, _wrap_dict and formatting in _format_trace."""

    def test_scan_events_in_trace(self) -> None:
        from emergent.wire.axis.surface import endpoint, application
        from emergent.wire.axis.surface.codecs.rrc import rrc
        from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger
        from emergent.wire.compile.targets.testing import testing_compile

        runner = ops().on(_PingOp, _ping_handler).compile()
        app = application().mount(
            endpoint(runner).expose(
                HTTPRouteTrigger("GET", "/ping"),
                rrc(_PingReq, _PingResp),
            )
        )
        collector = ListCollector()
        axes = Axes.traced(collector)
        testing_compile(app, axes=axes)

        data = trace_dict(axes)
        assert len(data["scan"]) == 1
        assert data["scan"][0]["codec"] == "RequestResponseCodec"

        text = explain(axes)
        assert "Scan" in text
        assert "Wrap" in text

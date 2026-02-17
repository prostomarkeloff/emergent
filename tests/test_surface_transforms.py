"""Tests for surface transforms — handler transforms and response transforms.

Covers:
- _handler.py: Timeout (seconds/minutes/hours factory methods, apply_handler wrapping)
- _response.py: protocol checks (HasToDict, HasAsDict, HasModelDump, HasDict, DataclassInstance),
  to_dict_from_protocol, try_convert_to_dict, is_dict_convertible, convert_dataclass_to_dict,
  AsDict (strict + skip), AsStr, Transform, TransformAsync
"""

from __future__ import annotations

import asyncio
import dataclasses
from dataclasses import dataclass
from datetime import timedelta

import pytest

from emergent.wire.axis.surface.transforms._handler import Timeout
from emergent.wire.axis.surface.transforms._response import (
    # Protocols
    HasToDict,
    HasAsDict,
    HasModelDump,
    HasDict,
    DataclassInstance,
    # Functions
    to_dict_from_protocol,
    try_convert_to_dict,
    is_dict_convertible,
    convert_dataclass_to_dict,
    # Capabilities
    AsDict,
    AsStr,
    Transform,
    TransformAsync,
)
from emergent.wire.axis._capability import HandlerRuntimeContext


# ═══════════════════════════════════════════════════════════════════════════════
# Test domain types
# ═══════════════════════════════════════════════════════════════════════════════


class ObjWithToDict:
    def to_dict(self) -> dict[str, object]:
        return {"source": "to_dict"}


class ObjWithAsDict:
    def asdict(self) -> dict[str, object]:
        return {"source": "asdict"}


class ObjWithModelDump:
    def model_dump(self) -> dict[str, object]:
        return {"source": "model_dump"}


class ObjWithDict:
    def dict(self) -> dict[str, object]:
        return {"source": "dict"}


@dataclass
class SimpleData:
    name: str
    value: int


class PlainObject:
    """Not convertible to dict."""
    pass


# ═══════════════════════════════════════════════════════════════════════════════
# Timeout
# ═══════════════════════════════════════════════════════════════════════════════


class TestTimeout:
    def test_seconds_factory(self) -> None:
        t = Timeout.seconds(30)
        assert t.duration == timedelta(seconds=30)

    def test_minutes_factory(self) -> None:
        t = Timeout.minutes(5)
        assert t.duration == timedelta(minutes=5)

    def test_hours_factory(self) -> None:
        t = Timeout.hours(2)
        assert t.duration == timedelta(hours=2)

    def test_direct_construction(self) -> None:
        t = Timeout(timedelta(seconds=45))
        assert t.duration.total_seconds() == 45.0

    @pytest.mark.asyncio
    async def test_apply_handler_wraps_async(self) -> None:
        """apply_handler wraps an async handler and preserves return value."""
        t = Timeout.seconds(5)

        async def my_handler(x: int) -> str:
            return f"result:{x}"

        wrapped = t.apply_handler(my_handler)
        result = await wrapped(42)
        assert result == "result:42"

    @pytest.mark.asyncio
    async def test_apply_handler_propagates_error(self) -> None:
        """Wrapped handler propagates exceptions."""
        t = Timeout.seconds(5)

        async def failing_handler() -> str:
            raise ValueError("boom")

        wrapped = t.apply_handler(failing_handler)
        with pytest.raises(ValueError, match="boom"):
            await wrapped()

    @pytest.mark.asyncio
    async def test_apply_handler_timeout_fires(self) -> None:
        """Handler that exceeds timeout raises TimeoutError."""
        t = Timeout.seconds(0.01)

        async def slow_handler() -> str:
            await asyncio.sleep(10)
            return "never"

        wrapped = t.apply_handler(slow_handler)
        with pytest.raises((TimeoutError, asyncio.TimeoutError, Exception)):
            await wrapped()

    def test_frozen_dataclass(self) -> None:
        """Timeout is a frozen dataclass."""
        t = Timeout.seconds(10)
        with pytest.raises(dataclasses.FrozenInstanceError):
            t.duration = timedelta(seconds=20)  # type: ignore[misc]


# ═══════════════════════════════════════════════════════════════════════════════
# Protocol Checks
# ═══════════════════════════════════════════════════════════════════════════════


class TestProtocols:
    def test_has_to_dict(self) -> None:
        obj = ObjWithToDict()
        assert isinstance(obj, HasToDict)

    def test_has_as_dict(self) -> None:
        obj = ObjWithAsDict()
        assert isinstance(obj, HasAsDict)

    def test_has_model_dump(self) -> None:
        obj = ObjWithModelDump()
        assert isinstance(obj, HasModelDump)

    def test_has_dict(self) -> None:
        obj = ObjWithDict()
        assert isinstance(obj, HasDict)

    def test_dataclass_instance(self) -> None:
        obj = SimpleData(name="test", value=1)
        assert isinstance(obj, DataclassInstance)

    def test_plain_object_not_protocol(self) -> None:
        obj = PlainObject()
        assert not isinstance(obj, HasToDict)
        assert not isinstance(obj, HasAsDict)
        assert not isinstance(obj, HasModelDump)


# ═══════════════════════════════════════════════════════════════════════════════
# to_dict_from_protocol
# ═══════════════════════════════════════════════════════════════════════════════


class TestToDictFromProtocol:
    def test_dict_passthrough(self) -> None:
        d: dict[str, object] = {"key": "value"}
        result = to_dict_from_protocol(d)
        assert result == {"key": "value"}

    def test_to_dict_method(self) -> None:
        obj = ObjWithToDict()
        result = to_dict_from_protocol(obj)
        assert result == {"source": "to_dict"}

    def test_asdict_method(self) -> None:
        obj = ObjWithAsDict()
        result = to_dict_from_protocol(obj)
        assert result == {"source": "asdict"}

    def test_model_dump_method(self) -> None:
        obj = ObjWithModelDump()
        result = to_dict_from_protocol(obj)
        assert result == {"source": "model_dump"}

    def test_dict_method_pydantic_v1(self) -> None:
        obj = ObjWithDict()
        result = to_dict_from_protocol(obj)
        assert result == {"source": "dict"}

    def test_priority_order_to_dict_first(self) -> None:
        """When object has both to_dict and asdict, to_dict wins."""

        class Both:
            def to_dict(self) -> dict[str, object]:
                return {"method": "to_dict"}

            def asdict(self) -> dict[str, object]:
                return {"method": "asdict"}

        result = to_dict_from_protocol(Both())
        assert result["method"] == "to_dict"


# ═══════════════════════════════════════════════════════════════════════════════
# try_convert_to_dict
# ═══════════════════════════════════════════════════════════════════════════════


class TestTryConvertToDict:
    def test_delegates_to_protocol(self) -> None:
        obj = ObjWithToDict()
        result = try_convert_to_dict(obj)
        assert result == {"source": "to_dict"}

    def test_dict_passthrough(self) -> None:
        d: dict[str, object] = {"x": 1}
        result = try_convert_to_dict(d)
        assert result == {"x": 1}


# ═══════════════════════════════════════════════════════════════════════════════
# is_dict_convertible
# ═══════════════════════════════════════════════════════════════════════════════


class TestIsDictConvertible:
    def test_always_true_for_protocol_objects(self) -> None:
        """is_dict_convertible always returns True (type guarantees convertibility)."""
        assert is_dict_convertible(ObjWithToDict()) is True
        assert is_dict_convertible(ObjWithAsDict()) is True
        assert is_dict_convertible(ObjWithModelDump()) is True
        assert is_dict_convertible(ObjWithDict()) is True


# ═══════════════════════════════════════════════════════════════════════════════
# convert_dataclass_to_dict
# ═══════════════════════════════════════════════════════════════════════════════


class TestConvertDataclassToDict:
    def test_dataclass_instance(self) -> None:
        obj = SimpleData(name="test", value=42)
        result = convert_dataclass_to_dict(obj)
        assert result == {"name": "test", "value": 42}

    def test_non_dataclass_raises(self) -> None:
        """Non-dataclass raises TypeError."""
        with pytest.raises(TypeError, match="is not a dataclass instance"):
            convert_dataclass_to_dict(PlainObject())  # type: ignore[arg-type]

    def test_dataclass_class_not_instance_raises(self) -> None:
        """Dataclass class (not instance) raises TypeError."""
        with pytest.raises(TypeError, match="is not a dataclass instance"):
            convert_dataclass_to_dict(SimpleData)  # type: ignore[arg-type]


# ═══════════════════════════════════════════════════════════════════════════════
# AsDict
# ═══════════════════════════════════════════════════════════════════════════════


class TestAsDict:
    def test_dict_passthrough(self) -> None:
        transform = AsDict()
        result = transform.apply_response({"key": "value"})
        assert result == {"key": "value"}

    def test_to_dict_protocol(self) -> None:
        transform = AsDict()
        result = transform.apply_response(ObjWithToDict())
        assert result == {"source": "to_dict"}

    def test_asdict_protocol(self) -> None:
        transform = AsDict()
        result = transform.apply_response(ObjWithAsDict())
        assert result == {"source": "asdict"}

    def test_model_dump_protocol(self) -> None:
        transform = AsDict()
        result = transform.apply_response(ObjWithModelDump())
        assert result == {"source": "model_dump"}

    def test_dict_protocol_v1(self) -> None:
        transform = AsDict()
        result = transform.apply_response(ObjWithDict())
        assert result == {"source": "dict"}

    def test_dataclass_instance(self) -> None:
        transform = AsDict()
        obj = SimpleData(name="test", value=1)
        result = transform.apply_response(obj)
        assert result == {"name": "test", "value": 1}

    def test_unconvertible_strict_raises(self) -> None:
        """Default (skip=False) raises ValueError for unconvertible objects."""
        transform = AsDict()
        with pytest.raises(ValueError, match="Cannot convert"):
            transform.apply_response(42)

    def test_unconvertible_skip_wraps(self) -> None:
        """skip=True wraps unconvertible value in {"value": ...}."""
        transform = AsDict(skip=True)
        result = transform.apply_response(42)
        assert result == {"value": 42}

    def test_compile_handler_runtime(self) -> None:
        """AsDict registers itself as response_transform."""
        transform = AsDict()
        ctx = HandlerRuntimeContext()
        result = transform.compile_handler_runtime(ctx)
        assert transform in result.response_transforms


# ═══════════════════════════════════════════════════════════════════════════════
# AsStr
# ═══════════════════════════════════════════════════════════════════════════════


class TestAsStr:
    def test_str_conversion(self) -> None:
        transform = AsStr()
        result = transform.apply_response(42)
        assert result == "42"

    def test_str_passthrough(self) -> None:
        transform = AsStr()
        result = transform.apply_response("hello")
        assert result == "hello"

    def test_object_str(self) -> None:
        transform = AsStr()
        obj = SimpleData(name="x", value=1)
        result = transform.apply_response(obj)
        assert isinstance(result, str)

    def test_none_conversion(self) -> None:
        transform = AsStr()
        result = transform.apply_response(None)
        assert result == "None"

    def test_compile_handler_runtime(self) -> None:
        """AsStr registers itself as response_transform."""
        transform = AsStr()
        ctx = HandlerRuntimeContext()
        result = transform.compile_handler_runtime(ctx)
        assert transform in result.response_transforms


# ═══════════════════════════════════════════════════════════════════════════════
# Transform
# ═══════════════════════════════════════════════════════════════════════════════


class TestTransform:
    def test_basic_transform(self) -> None:
        transform: Transform[int, str] = Transform(fn=lambda x: f"value:{x}")
        result = transform.apply_response(42)
        assert result == "value:42"

    def test_dict_wrapping(self) -> None:
        transform: Transform[str, dict[str, str]] = Transform(
            fn=lambda r: {"data": r, "status": "ok"}
        )
        result = transform.apply_response("hello")
        assert result == {"data": "hello", "status": "ok"}

    def test_identity_transform(self) -> None:
        transform: Transform[int, int] = Transform(fn=lambda x: x)
        result = transform.apply_response(99)
        assert result == 99

    def test_compile_handler_runtime(self) -> None:
        transform: Transform[int, str] = Transform(fn=str)
        ctx = HandlerRuntimeContext()
        result = transform.compile_handler_runtime(ctx)
        assert transform in result.response_transforms


# ═══════════════════════════════════════════════════════════════════════════════
# TransformAsync
# ═══════════════════════════════════════════════════════════════════════════════


class TestTransformAsync:
    @pytest.mark.asyncio
    async def test_async_transform(self) -> None:
        async def async_fn(x: int) -> str:
            return f"async:{x}"

        transform: TransformAsync[int, str] = TransformAsync(fn=async_fn)
        result = await transform.apply_response(42)
        assert result == "async:42"

    @pytest.mark.asyncio
    async def test_async_transform_with_awaitable(self) -> None:
        async def serialize(data: SimpleData) -> dict[str, object]:
            return {"name": data.name, "value": data.value}

        transform: TransformAsync[SimpleData, dict[str, object]] = TransformAsync(fn=serialize)
        obj = SimpleData(name="test", value=1)
        result = await transform.apply_response(obj)
        assert result == {"name": "test", "value": 1}

    def test_compile_handler_runtime(self) -> None:
        async def noop(x: int) -> int:
            return x

        transform: TransformAsync[int, int] = TransformAsync(fn=noop)
        ctx = HandlerRuntimeContext()
        result = transform.compile_handler_runtime(ctx)
        assert transform in result.response_transforms

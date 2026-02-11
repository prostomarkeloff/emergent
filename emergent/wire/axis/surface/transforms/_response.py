"""Response transform capabilities."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Awaitable, Callable, Generic, Protocol, runtime_checkable, TypeVar, ClassVar, cast

from ._base import ResponseTransform


# ═══════════════════════════════════════════════════════════════════════════════
# Protocols for dict conversion
# ═══════════════════════════════════════════════════════════════════════════════


@runtime_checkable
class HasToDict(Protocol):
    """Object with to_dict() method."""
    def to_dict(self) -> dict[str, object]: ...


@runtime_checkable
class HasAsDict(Protocol):
    """Object with asdict() method."""
    def asdict(self) -> dict[str, object]: ...


@runtime_checkable
class HasModelDump(Protocol):
    """Pydantic v2 model."""
    def model_dump(self) -> dict[str, object]: ...


@runtime_checkable
class HasDict(Protocol):
    """Pydantic v1 model."""
    def dict(self) -> dict[str, object]: ...


@runtime_checkable
class DataclassInstance(Protocol):
    """Protocol for dataclass instances.

    Dataclasses have __dataclass_fields__ as a class attribute.
    """
    __dataclass_fields__: ClassVar[dict[str, dataclasses.Field[object]]]


# ═══════════════════════════════════════════════════════════════════════════════
# Type Variables and Aliases
# ═══════════════════════════════════════════════════════════════════════════════

K = TypeVar("K")
V = TypeVar("V")

# Type for objects that can be converted to dict
DictConvertible = HasToDict | HasAsDict | HasModelDump | HasDict | dict[str, object]


# ═══════════════════════════════════════════════════════════════════════════════
# Conversion Logic
# ═══════════════════════════════════════════════════════════════════════════════


def to_dict_from_protocol(obj: DictConvertible) -> dict[str, object]:
    """Convert protocol-compatible object to dict.

    For objects that implement one of: to_dict, asdict, model_dump, dict.
    """
    if isinstance(obj, dict):
        return obj
    if isinstance(obj, HasToDict):
        return obj.to_dict()
    if isinstance(obj, HasAsDict):
        return obj.asdict()
    if isinstance(obj, HasModelDump):
        return obj.model_dump()
    # HasDict - Pydantic v1
    return obj.dict()


def try_convert_to_dict(obj: DictConvertible) -> dict[str, object]:
    """Convert DictConvertible to dict."""
    return to_dict_from_protocol(obj)


def is_dict_convertible(obj: HasToDict | HasAsDict | HasModelDump | HasDict) -> bool:
    """Check if object can be converted to dict via protocol.

    The parameter type already guarantees convertibility.
    This function returns True for type narrowing purposes.
    """
    return True  # Type already guarantees convertibility


def convert_dataclass_to_dict(obj: DataclassInstance) -> dict[str, object]:
    """Convert dataclass instance to dict."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        result: dict[str, object] = dict(dataclasses.asdict(obj))
        return result
    raise TypeError(f"{type(obj).__name__} is not a dataclass instance")


# ═══════════════════════════════════════════════════════════════════════════════
# Capabilities
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class AsDict(ResponseTransform):
    """Convert response to dict.

    Supports dataclasses, Pydantic models, objects with to_dict()/asdict().

    Usage:
        # Strict (default) — raises ValueError if can't convert
        AsDict()

        # Lenient — passes through if can't convert
        AsDict(skip=True)
    """

    skip: bool = False

    def apply_response(self, response: object) -> dict[str, object]:
        """Convert response to dict."""
        if isinstance(response, dict):
            # Cast needed because isinstance(x, dict) narrows to dict[Unknown, Unknown]
            raw = cast(dict[str, object], response)
            return raw
        if isinstance(response, (HasToDict, HasAsDict, HasModelDump, HasDict)):
            return to_dict_from_protocol(response)
        if dataclasses.is_dataclass(response) and not isinstance(response, type):
            return dict(dataclasses.asdict(response))
        if self.skip:
            return {"value": response}
        raise ValueError(f"Cannot convert {type(response).__name__} to dict")


@dataclass(frozen=True, slots=True)
class AsStr(ResponseTransform):
    """Convert response to string via __str__.

    Usage:
        endpoint(runner).expose(
            TelegrindTrigger(Command("help")),
            immediate_factory(lambda: HelpResponse(text)),
            AsStr(),
        )

    Useful for telegrinder's str_manager.
    """

    def apply_response(self, response: object) -> str:
        """Convert response to string."""
        return str(response)


T = TypeVar("T")
R = TypeVar("R")


@dataclass(frozen=True, slots=True)
class Transform(ResponseTransform, Generic[T, R]):
    """Transform response after handler.

    Example::

        Transform(fn=lambda r: r.model_dump())
        Transform(fn=lambda r: {"data": r, "status": "ok"})
    """

    fn: Callable[[T], R]

    def apply_response(self, response: T) -> R:
        return self.fn(response)


@dataclass(frozen=True, slots=True)
class TransformAsync(ResponseTransform, Generic[T, R]):
    """Async transform response after handler.

    Example::

        TransformAsync(fn=async_serialize)
    """

    fn: Callable[[T], Awaitable[R]]

    def apply_response(self, response: T) -> Awaitable[R]:
        return self.fn(response)


__all__ = (
    # Protocols
    "HasToDict",
    "HasAsDict",
    "HasModelDump",
    "HasDict",
    "DataclassInstance",
    "DictConvertible",
    # Functions
    "to_dict_from_protocol",
    "try_convert_to_dict",
    "is_dict_convertible",
    "convert_dataclass_to_dict",
    # Capabilities
    "AsDict",
    "AsStr",
    "Transform",
    "TransformAsync",
)

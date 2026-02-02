"""Response transform capabilities."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Protocol, runtime_checkable, TypeVar, ClassVar

from ._base import SurfaceCapability


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
class AsDict(SurfaceCapability):
    """Convert response to dict.

    Supports dataclasses, Pydantic models, objects with to_dict()/asdict().

    Usage:
        # Strict (default) — raises ValueError if can't convert
        AsDict()

        # Lenient — passes through if can't convert
        AsDict(skip=True)
    """

    skip: bool = False

    def apply_response_dict(self, response: DictConvertible) -> dict[str, object]:
        """Convert DictConvertible response to dict."""
        return to_dict_from_protocol(response)

    def apply_response_dataclass(self, response: DataclassInstance) -> dict[str, object]:
        """Convert dataclass response to dict."""
        return convert_dataclass_to_dict(response)


@dataclass(frozen=True, slots=True)
class AsStr(SurfaceCapability):
    """Convert response to string via __str__.

    Usage:
        endpoint(runner).expose(
            TelegrindTrigger(Command("help")),
            immediate_factory(lambda: HelpResponse(text)),
            AsStr(),
        )

    Useful for telegrinder's str_manager.
    """

    def apply_response_str(self, response: str) -> str:
        """Pass through string response."""
        return response

    def apply_response_protocol(self, response: HasToDict | HasAsDict | HasModelDump | HasDict) -> str:
        """Convert protocol object to string."""
        return str(response)

    def apply_response_dataclass(self, response: DataclassInstance) -> str:
        """Convert dataclass to string."""
        return str(response)


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
)

"""Compiler core — axes context and common types.

Functional compiler infrastructure. Axes passed explicitly, no global state.

    from emergent.wire.compiler import Axes, compile_handler

    axes = Axes.default()
    handler = compile_handler(handler, axes, my_wrapper)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, TypeVar

from emergent.wire.axis.schema import inspect_dataclass, FieldInfo
from emergent.wire.axis.schema import (
    MinLen,
    MaxLen,
    Min,
    Max,
    Pattern,
    OneOf,
    Identity,
    Unique,
)

# ═══════════════════════════════════════════════════════════════════════════════
# Axes Context
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Axes:
    """Multi-axis context for compilation.

    Passed explicitly to all compiler functions.
    No global state, easy to test.

    Attributes:
        schema: Function to inspect dataclass fields with capabilities.
    """

    schema: Callable[[type], dict[str, FieldInfo]]

    @classmethod
    def default(cls) -> Axes:
        """Create default axes with standard introspection."""
        return cls(schema=inspect_dataclass)


# ═══════════════════════════════════════════════════════════════════════════════
# Field Constraint Extraction
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class FieldConstraints:
    """Extracted constraints from schema capabilities.

    Universal representation that any framework can use.
    """

    min_length: int | None = None
    max_length: int | None = None
    min_value: float | None = None
    max_value: float | None = None
    pattern: str | None = None
    choices: tuple[Any, ...] | None = None
    is_identity: bool = False
    is_unique: bool = False
    is_optional: bool = False


def extract_constraints(info: FieldInfo) -> FieldConstraints:
    """Extract universal constraints from FieldInfo.

    Pure function: FieldInfo → FieldConstraints
    """
    min_length: int | None = None
    max_length: int | None = None
    min_value: float | None = None
    max_value: float | None = None
    pattern: str | None = None
    choices: tuple[Any, ...] | None = None
    is_identity = False
    is_unique = False

    for cap in info.universal:
        match cap:
            case MinLen(value=v):
                min_length = v
            case MaxLen(value=v):
                max_length = v
            case Min(value=v):
                min_value = v
            case Max(value=v):
                max_value = v
            case Pattern(regex=r):
                pattern = r
            case OneOf(values=vs):
                choices = vs
            case Identity():
                is_identity = True
            case Unique():
                is_unique = True
            case _:
                pass  # Other capabilities ignored

    return FieldConstraints(
        min_length=min_length,
        max_length=max_length,
        min_value=min_value,
        max_value=max_value,
        pattern=pattern,
        choices=choices,
        is_identity=is_identity,
        is_unique=is_unique,
        is_optional=info.is_optional,
    )


def extract_all_constraints(
    cls: type, axes: Axes
) -> dict[str, tuple[type, FieldConstraints]]:
    """Extract constraints for all fields of a dataclass.

    Returns: {field_name: (base_type, constraints)}
    """
    fields = axes.schema(cls)
    return {
        name: (info.base_type, extract_constraints(info))
        for name, info in fields.items()
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Handler Wrapper Type
# ═══════════════════════════════════════════════════════════════════════════════

T = TypeVar("T")

# Wrapper transforms async handler into framework-specific artifact
Wrapper = Callable[[Callable[..., Any]], T]


__all__ = (
    "Axes",
    "FieldConstraints",
    "extract_constraints",
    "extract_all_constraints",
    "Wrapper",
)

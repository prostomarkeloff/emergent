"""Pydantic dialect — Pydantic-specific capabilities.

These are IGNORED by other compilers (SQLAlchemy, JSON Schema, etc.).

    from emergent.wire.axis.schema.dialects import pydantic as pyd

    @dataclass
    class User:
        email: Annotated[str, Unique, pyd.Strict()]
"""

from dataclasses import dataclass
from typing import Any, Callable

from emergent.wire.axis.schema._universal import Capability


class PydanticCapability(Capability):
    """Base for Pydantic-specific capabilities."""
    pass


# ═══════════════════════════════════════════════════════════════════════════════
# Validation Mode
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Strict(PydanticCapability):
    """Enable strict mode (no coercion)."""
    pass


@dataclass(frozen=True, slots=True)
class Coerce(PydanticCapability):
    """Explicitly allow coercion."""
    pass


# ═══════════════════════════════════════════════════════════════════════════════
# Field Configuration
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Alias(PydanticCapability):
    """Field alias for serialization/deserialization."""
    name: str


@dataclass(frozen=True, slots=True)
class AliasPath(PydanticCapability):
    """Nested alias path."""
    path: tuple[str | int, ...]

    def __init__(self, *path: str | int) -> None:
        object.__setattr__(self, "path", path)


@dataclass(frozen=True, slots=True)
class Exclude(PydanticCapability):
    """Exclude from serialization."""
    pass


@dataclass(frozen=True, slots=True)
class Include(PydanticCapability):
    """Explicitly include in serialization."""
    pass


# ═══════════════════════════════════════════════════════════════════════════════
# Validation
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class ValidatorBefore(PydanticCapability):
    """Run validator before standard validation.

    Example:
        pyd.ValidatorBefore(lambda v: v.strip() if isinstance(v, str) else v)
    """
    func: Callable[[Any], Any]


@dataclass(frozen=True, slots=True)
class ValidatorAfter(PydanticCapability):
    """Run validator after standard validation."""
    func: Callable[[Any], Any]


@dataclass(frozen=True, slots=True)
class ValidatorWrap(PydanticCapability):
    """Wrap standard validation."""
    func: Callable[[Any, Callable[[Any], Any]], Any]


__all__ = (
    "PydanticCapability",
    # Validation Mode
    "Strict",
    "Coerce",
    # Field Configuration
    "Alias",
    "AliasPath",
    "Exclude",
    "Include",
    # Validation
    "ValidatorBefore",
    "ValidatorAfter",
    "ValidatorWrap",
)

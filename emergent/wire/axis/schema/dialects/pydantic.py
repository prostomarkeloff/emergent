"""Pydantic dialect — Pydantic-specific capabilities.

These are IGNORED by other compilers (SQLAlchemy, JSON Schema, etc.).

    from emergent.wire.axis.schema.dialects import pydantic as pyd

    @dataclass
    class User:
        email: Annotated[str, Unique, pyd.Strict()]
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

from emergent.wire.axis.schema._universal import SchemaAxisCapability
from emergent.wire.axis._capability import pydantic_metadata, pydantic_field

if TYPE_CHECKING:
    from emergent.wire.axis._capability import PydanticContext


class PydanticCapability(SchemaAxisCapability):
    """Base for Pydantic-specific capabilities."""

    pass


# ═══════════════════════════════════════════════════════════════════════════════
# Validation Mode
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Strict(PydanticCapability):
    """Enable strict mode (no coercion)."""

    def compile_pydantic(self, ctx: "PydanticContext") -> "PydanticContext":
        from pydantic.fields import FieldInfo as PydFieldInfo

        return pydantic_metadata(ctx, *PydFieldInfo(strict=True).metadata)


@dataclass(frozen=True, slots=True)
class Coerce(PydanticCapability):
    """Explicitly allow coercion."""

    def compile_pydantic(self, ctx: "PydanticContext") -> "PydanticContext":
        from pydantic.fields import FieldInfo as PydFieldInfo

        return pydantic_metadata(ctx, *PydFieldInfo(strict=False).metadata)


# ═══════════════════════════════════════════════════════════════════════════════
# Field Configuration
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class AliasPath(PydanticCapability):
    """Nested alias path."""
    path: tuple[str | int, ...]

    def __init__(self, first: str, *rest: str | int) -> None:
        object.__setattr__(self, "path", (first, *rest))

    def compile_pydantic(self, ctx: "PydanticContext") -> "PydanticContext":
        from pydantic import AliasPath as PydAliasPath

        first, *rest = self.path
        alias = PydAliasPath(str(first), *rest)
        return pydantic_field(ctx, lambda fi: setattr(fi, "validation_alias", alias))


@dataclass(frozen=True, slots=True)
class Exclude(PydanticCapability):
    """Exclude from serialization."""

    def compile_pydantic(self, ctx: "PydanticContext") -> "PydanticContext":
        return pydantic_field(ctx, lambda fi: setattr(fi, "exclude", True))


@dataclass(frozen=True, slots=True)
class Include(PydanticCapability):
    """Explicitly include in serialization."""

    def compile_pydantic(self, ctx: "PydanticContext") -> "PydanticContext":
        return pydantic_field(ctx, lambda fi: setattr(fi, "exclude", False))


# ═══════════════════════════════════════════════════════════════════════════════
# Validation
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class ValidatorBefore(PydanticCapability):
    """Run validator before standard validation.

    Example:
        pyd.ValidatorBefore(lambda v: v.strip() if isinstance(v, str) else v)
    """
    func: Callable[[object], object]

    def compile_pydantic(self, ctx: "PydanticContext") -> "PydanticContext":
        from pydantic import BeforeValidator

        return pydantic_metadata(ctx, BeforeValidator(self.func))


@dataclass(frozen=True, slots=True)
class ValidatorAfter(PydanticCapability):
    """Run validator after standard validation."""
    func: Callable[[object], object]

    def compile_pydantic(self, ctx: "PydanticContext") -> "PydanticContext":
        from pydantic import AfterValidator

        return pydantic_metadata(ctx, AfterValidator(self.func))


@dataclass(frozen=True, slots=True)
class ValidatorWrap(PydanticCapability):
    """Wrap standard validation."""
    func: Callable[[object, Callable[[object], object]], object]

    def compile_pydantic(self, ctx: "PydanticContext") -> "PydanticContext":
        from pydantic import WrapValidator

        return pydantic_metadata(ctx, WrapValidator(self.func))


__all__ = (
    "PydanticCapability",
    # Validation Mode
    "Strict",
    "Coerce",
    # Field Configuration
    "AliasPath",
    "Exclude",
    "Include",
    # Validation
    "ValidatorBefore",
    "ValidatorAfter",
    "ValidatorWrap",
)

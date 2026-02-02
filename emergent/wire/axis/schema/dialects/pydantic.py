"""Pydantic dialect — Pydantic-specific capabilities.

These are IGNORED by other compilers (SQLAlchemy, JSON Schema, etc.).

    from emergent.wire.axis.schema.dialects import pydantic as pyd

    @dataclass
    class User:
        email: Annotated[str, Unique, pyd.Strict()]
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Callable

from emergent.wire.axis.schema._universal import Capability

if TYPE_CHECKING:
    from emergent.wire.axis._capability import PydanticContext


class PydanticCapability(Capability):
    """Base for Pydantic-specific capabilities."""
    pass


# ═══════════════════════════════════════════════════════════════════════════════
# Validation Mode
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Strict(PydanticCapability):
    """Enable strict mode (no coercion)."""

    def compile_pydantic(self, ctx: "PydanticContext") -> "PydanticContext":
        from pydantic.fields import FieldInfo
        fi = copy.deepcopy(ctx.field_info)
        # strict is stored in metadata as Strict(strict=True)
        fi.metadata.extend(FieldInfo(strict=True).metadata)
        return replace(ctx, field_info=fi)


@dataclass(frozen=True, slots=True)
class Coerce(PydanticCapability):
    """Explicitly allow coercion."""

    def compile_pydantic(self, ctx: "PydanticContext") -> "PydanticContext":
        from pydantic.fields import FieldInfo
        fi = copy.deepcopy(ctx.field_info)
        # strict=False stored in metadata
        fi.metadata.extend(FieldInfo(strict=False).metadata)
        return replace(ctx, field_info=fi)


# ═══════════════════════════════════════════════════════════════════════════════
# Field Configuration
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Alias(PydanticCapability):
    """Field alias for serialization/deserialization."""
    name: str

    def compile_pydantic(self, ctx: "PydanticContext") -> "PydanticContext":
        fi = copy.deepcopy(ctx.field_info)
        fi.alias = self.name
        return replace(ctx, field_info=fi)


@dataclass(frozen=True, slots=True)
class AliasPath(PydanticCapability):
    """Nested alias path."""
    path: tuple[str | int, ...]

    def __init__(self, first: str, *rest: str | int) -> None:
        object.__setattr__(self, "path", (first, *rest))

    def compile_pydantic(self, ctx: "PydanticContext") -> "PydanticContext":
        from pydantic import AliasPath as PydAliasPath
        fi = copy.deepcopy(ctx.field_info)
        first, *rest = self.path
        # first must be str, rest can be str | int
        fi.validation_alias = PydAliasPath(str(first), *rest)
        return replace(ctx, field_info=fi)


@dataclass(frozen=True, slots=True)
class Exclude(PydanticCapability):
    """Exclude from serialization."""

    def compile_pydantic(self, ctx: "PydanticContext") -> "PydanticContext":
        fi = copy.deepcopy(ctx.field_info)
        fi.exclude = True
        return replace(ctx, field_info=fi)


@dataclass(frozen=True, slots=True)
class Include(PydanticCapability):
    """Explicitly include in serialization."""

    def compile_pydantic(self, ctx: "PydanticContext") -> "PydanticContext":
        fi = copy.deepcopy(ctx.field_info)
        fi.exclude = False
        return replace(ctx, field_info=fi)


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
        fi = copy.deepcopy(ctx.field_info)
        fi.metadata.append(BeforeValidator(self.func))
        return replace(ctx, field_info=fi)


@dataclass(frozen=True, slots=True)
class ValidatorAfter(PydanticCapability):
    """Run validator after standard validation."""
    func: Callable[[object], object]

    def compile_pydantic(self, ctx: "PydanticContext") -> "PydanticContext":
        from pydantic import AfterValidator
        fi = copy.deepcopy(ctx.field_info)
        fi.metadata.append(AfterValidator(self.func))
        return replace(ctx, field_info=fi)


@dataclass(frozen=True, slots=True)
class ValidatorWrap(PydanticCapability):
    """Wrap standard validation."""
    func: Callable[[object, Callable[[object], object]], object]

    def compile_pydantic(self, ctx: "PydanticContext") -> "PydanticContext":
        from pydantic import WrapValidator
        fi = copy.deepcopy(ctx.field_info)
        fi.metadata.append(WrapValidator(self.func))
        return replace(ctx, field_info=fi)


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

"""Universal schema capabilities — understood by ALL compilers.

These describe data semantics, not backend-specific implementation details.
Compilers translate universal capabilities to backend-specific constructs.

    # Universal (all compilers understand)
    email: Annotated[str, Unique, MaxLen(255)]

    # Compiler translates:
    # - SQLAlchemy: Column(String(255), unique=True)
    # - JSON Schema: {"type": "string", "maxLength": 255}
    # - Pydantic: Field(max_length=255)

## Extension

Custom capabilities can implement compilation protocols for specific targets:

    from emergent.wire.axis.schema import Capability
    from emergent.wire.axis.schema._compilable import OpenAPICompilable

    @dataclass(frozen=True, slots=True)
    class Encrypted(Capability):
        algorithm: str = "AES-256"

        # Implement protocol for OpenAPI target
        def to_openapi(self) -> dict:
            return {"format": "encrypted", "x-algorithm": self.algorithm}

        # Implement protocol for SQLAlchemy target
        def to_sqlalchemy(self, field_name: str, field_type: type) -> TypeDecorator:
            return EncryptedType(self.algorithm)

See `_compilable.py` for available protocols:
- OpenAPICompilable (to_openapi)
- SQLAlchemyCompilable (to_sqlalchemy)
- PydanticCompilable (to_pydantic)
- CLICompilable (to_cli)
- ProtobufCompilable (to_protobuf)
"""

from dataclasses import dataclass
from typing import Any

from emergent.wire.axis.schema._compilable import (
    OpenAPISchema,
    PydanticSchema,
    CLISchema,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Base
# ═══════════════════════════════════════════════════════════════════════════════


class Capability:
    """Base for all schema capabilities (universal and dialect-specific).

    Capabilities are pure data describing constraints/metadata.
    To customize compilation for specific targets, implement protocols
    from `_compilable.py` (e.g., OpenAPICompilable, PydanticCompilable).
    """
    pass


class UniversalCapability(Capability):
    """Base for universal capabilities — all compilers understand these.

    Built-in universal capabilities implement compilation protocols
    for common targets (OpenAPI, Pydantic, etc.).
    """
    pass


# ═══════════════════════════════════════════════════════════════════════════════
# Identity & Uniqueness
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Identity(UniversalCapability):
    """This field is the entity identifier.

    Compilers translate to:
    - SQL: PRIMARY KEY (+ AUTOINCREMENT for int)
    - JSON Schema: (no direct equivalent, informational)
    - Protobuf: (field ordering hint)
    """
    pass


@dataclass(frozen=True, slots=True)
class Unique(UniversalCapability):
    """Field value must be unique across all entities.

    Compilers translate to:
    - SQL: UNIQUE constraint (+ INDEX typically)
    - JSON Schema: (via uniqueItems in array context)
    - Pydantic: (custom validator)
    """
    pass


# ═══════════════════════════════════════════════════════════════════════════════
# References
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Ref(UniversalCapability):
    """Reference to another entity.

    Compilers translate to:
    - SQL: FOREIGN KEY + INDEX
    - JSON Schema: $ref
    - Protobuf: message field
    """
    target: type | str
    on_delete: str = "CASCADE"  # CASCADE, SET_NULL, RESTRICT
    on_update: str = "CASCADE"


# ═══════════════════════════════════════════════════════════════════════════════
# Value Constraints — Numbers
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Min(UniversalCapability):
    """Minimum value (inclusive)."""
    value: int | float

    def to_openapi(self) -> OpenAPISchema:
        return {"minimum": self.value}

    def to_pydantic(self) -> PydanticSchema:
        return {"ge": self.value}


@dataclass(frozen=True, slots=True)
class Max(UniversalCapability):
    """Maximum value (inclusive)."""
    value: int | float

    def to_openapi(self) -> OpenAPISchema:
        return {"maximum": self.value}

    def to_pydantic(self) -> PydanticSchema:
        return {"le": self.value}


@dataclass(frozen=True, slots=True)
class ExclusiveMin(UniversalCapability):
    """Minimum value (exclusive)."""
    value: int | float

    def to_openapi(self) -> OpenAPISchema:
        return {"exclusiveMinimum": self.value}

    def to_pydantic(self) -> PydanticSchema:
        return {"gt": self.value}


@dataclass(frozen=True, slots=True)
class ExclusiveMax(UniversalCapability):
    """Maximum value (exclusive)."""
    value: int | float

    def to_openapi(self) -> OpenAPISchema:
        return {"exclusiveMaximum": self.value}

    def to_pydantic(self) -> PydanticSchema:
        return {"lt": self.value}


@dataclass(frozen=True, slots=True)
class MultipleOf(UniversalCapability):
    """Value must be multiple of n."""
    value: int | float

    def to_openapi(self) -> OpenAPISchema:
        return {"multipleOf": self.value}

    def to_pydantic(self) -> PydanticSchema:
        return {"multiple_of": self.value}


# ═══════════════════════════════════════════════════════════════════════════════
# Value Constraints — Strings/Collections
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class MinLen(UniversalCapability):
    """Minimum length for strings/arrays."""
    value: int

    def to_openapi(self) -> OpenAPISchema:
        return {"minLength": self.value}

    def to_pydantic(self) -> PydanticSchema:
        return {"min_length": self.value}


@dataclass(frozen=True, slots=True)
class MaxLen(UniversalCapability):
    """Maximum length for strings/arrays."""
    value: int

    def to_openapi(self) -> OpenAPISchema:
        return {"maxLength": self.value}

    def to_pydantic(self) -> PydanticSchema:
        return {"max_length": self.value}


@dataclass(frozen=True, slots=True)
class Pattern(UniversalCapability):
    """String must match regex pattern."""
    regex: str

    def to_openapi(self) -> OpenAPISchema:
        return {"pattern": self.regex}

    def to_pydantic(self) -> PydanticSchema:
        return {"pattern": self.regex}


# ═══════════════════════════════════════════════════════════════════════════════
# Enums & Unions
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class OneOf(UniversalCapability):
    """Value must be one of specified literals (enum).

    Usage:
        status: Annotated[str, OneOf("pending", "active", "done")]
    """
    values: tuple[Any, ...]

    def __init__(self, *values: Any) -> None:
        object.__setattr__(self, "values", values)

    def to_openapi(self) -> OpenAPISchema:
        return {"enum": list(self.values)}


@dataclass(frozen=True, slots=True)
class Either(UniversalCapability):
    """Tagged union — value is one of specified types.

    Usage:
        result: Annotated[Success | Failure, Either(discriminator="type")]

    Compilers translate to:
    - SQL: JSON with discriminator or separate tables
    - JSON Schema: oneOf with discriminator
    - Pydantic: discriminated union
    - Protobuf: oneof
    """
    discriminator: str = "type"


# ═══════════════════════════════════════════════════════════════════════════════
# Composition
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Embedded(UniversalCapability):
    """Nested structure should be embedded inline, not normalized.

    Usage:
        address: Annotated[Address, Embedded]

    Compilers translate to:
    - SQL: JSON column (not separate table)
    - JSON Schema: inline object definition
    - Pydantic: nested model
    """
    pass


# ═══════════════════════════════════════════════════════════════════════════════
# Documentation
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Doc(UniversalCapability):
    """Human-readable description."""
    text: str

    def to_openapi(self) -> OpenAPISchema:
        return {"description": self.text}

    def to_pydantic(self) -> PydanticSchema:
        return {"description": self.text}

    def to_cli(self) -> CLISchema:
        return {"help": self.text}


@dataclass(frozen=True, slots=True)
class Deprecated(UniversalCapability):
    """Mark field as deprecated."""
    reason: str | None = None

    def to_openapi(self) -> OpenAPISchema:
        return {"deprecated": True}

    def to_pydantic(self) -> PydanticSchema:
        return {"deprecated": self.reason or True}


__all__ = (
    # Base
    "Capability",
    "UniversalCapability",
    # Identity & Uniqueness
    "Identity",
    "Unique",
    # References
    "Ref",
    # Value Constraints — Numbers
    "Min",
    "Max",
    "ExclusiveMin",
    "ExclusiveMax",
    "MultipleOf",
    # Value Constraints — Strings/Collections
    "MinLen",
    "MaxLen",
    "Pattern",
    # Enums & Unions
    "OneOf",
    "Either",
    # Composition
    "Embedded",
    # Documentation
    "Doc",
    "Deprecated",
)

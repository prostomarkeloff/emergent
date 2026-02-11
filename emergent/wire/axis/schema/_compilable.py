"""Schema TypedDicts — strict types for compilation contexts.

These TypedDicts define the structure of framework-specific schemas.
Used by compilation contexts in capability._contexts.

    from emergent.wire.axis.schema._compilable import OpenAPISchema

    @dataclass(frozen=True, slots=True)
    class OpenAPIContext:
        schema: OpenAPISchema  # TypedDict with OpenAPI fields
"""

from __future__ import annotations

from typing import Any, TypedDict


# ═══════════════════════════════════════════════════════════════════════════════
# OpenAPI / JSON Schema
# ═══════════════════════════════════════════════════════════════════════════════


class OpenAPISchema(TypedDict, total=False):
    """OpenAPI/JSON Schema properties for a field."""
    # Validation
    minimum: int | float
    maximum: int | float
    exclusiveMinimum: int | float
    exclusiveMaximum: int | float
    multipleOf: int | float
    minLength: int
    maxLength: int
    pattern: str
    enum: list[Any]
    # Format
    format: str
    # Documentation
    description: str
    deprecated: bool
    # Extensions (x-*)
    # Use Any for custom extensions since they're user-defined


# ═══════════════════════════════════════════════════════════════════════════════
# SQLAlchemy
# ═══════════════════════════════════════════════════════════════════════════════


class SQLAlchemyConfig(TypedDict, total=False):
    """SQLAlchemy Column configuration."""
    type: Any  # TypeDecorator or Column type
    index: bool
    unique: bool
    nullable: bool
    primary_key: bool
    default: Any
    server_default: str


__all__ = (
    "OpenAPISchema",
    "SQLAlchemyConfig",
)

"""OpenAPI dialect — OpenAPI-specific capabilities.

These are IGNORED by other compilers (SQLAlchemy, Pydantic, etc.).

    from emergent.wire.axis.schema.dialects import openapi

    @dataclass
    class User:
        email: Annotated[str, Unique, openapi.Format("email")]
        website: Annotated[str, openapi.Format("uri")]
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from emergent.wire.axis.schema._universal import Capability

if TYPE_CHECKING:
    from emergent.wire.axis._capability import OpenAPIContext

# Type for OpenAPI example values
ExampleValue = str | int | float | bool | None | list["ExampleValue"] | dict[str, "ExampleValue"]


class OpenAPICapability(Capability):
    """Base for OpenAPI-specific capabilities."""
    pass


# ═══════════════════════════════════════════════════════════════════════════════
# Format
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Format(OpenAPICapability):
    """String format hint.

    Standard formats: date-time, date, time, duration, email, hostname,
    ipv4, ipv6, uri, uri-reference, uuid, regex, binary, byte, password, etc.

    Example:
        email: Annotated[str, openapi.Format("email")]
    """
    format: str

    def compile_openapi(self, ctx: "OpenAPIContext") -> "OpenAPIContext":
        from emergent.wire.axis._capability import openapi_schema
        return openapi_schema(ctx, format=self.format)


# ═══════════════════════════════════════════════════════════════════════════════
# Content
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class ContentMediaType(OpenAPICapability):
    """Media type of string content.

    Example:
        image_data: Annotated[str, openapi.ContentMediaType("image/png")]
    """
    media_type: str

    def compile_openapi(self, ctx: "OpenAPIContext") -> "OpenAPIContext":
        from emergent.wire.axis._capability import openapi_schema
        return openapi_schema(ctx, contentMediaType=self.media_type)


@dataclass(frozen=True, slots=True)
class ContentEncoding(OpenAPICapability):
    """Encoding of string content.

    Example:
        data: Annotated[str, openapi.ContentEncoding("base64")]
    """
    encoding: str

    def compile_openapi(self, ctx: "OpenAPIContext") -> "OpenAPIContext":
        from emergent.wire.axis._capability import openapi_schema
        return openapi_schema(ctx, contentEncoding=self.encoding)


# ═══════════════════════════════════════════════════════════════════════════════
# Documentation
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Title(OpenAPICapability):
    """Schema title."""
    title: str

    def compile_openapi(self, ctx: "OpenAPIContext") -> "OpenAPIContext":
        from emergent.wire.axis._capability import openapi_schema
        return openapi_schema(ctx, title=self.title)


@dataclass(frozen=True, slots=True)
class Description(OpenAPICapability):
    """Schema description."""
    description: str

    def compile_openapi(self, ctx: "OpenAPIContext") -> "OpenAPIContext":
        from emergent.wire.axis._capability import openapi_schema
        return openapi_schema(ctx, description=self.description)


@dataclass(frozen=True, slots=True)
class Examples(OpenAPICapability):
    """Example values for documentation."""
    values: tuple[ExampleValue, ...]

    def __init__(self, *values: ExampleValue) -> None:
        object.__setattr__(self, "values", values)

    def compile_openapi(self, ctx: "OpenAPIContext") -> "OpenAPIContext":
        from emergent.wire.axis._capability import openapi_schema
        return openapi_schema(ctx, examples=list(self.values))


@dataclass(frozen=True, slots=True)
class Default(OpenAPICapability):
    """Default value in schema."""
    value: ExampleValue

    def compile_openapi(self, ctx: "OpenAPIContext") -> "OpenAPIContext":
        from emergent.wire.axis._capability import openapi_schema
        return openapi_schema(ctx, default=self.value)


@dataclass(frozen=True, slots=True)
class ReadOnly(OpenAPICapability):
    """Field is read-only."""

    def compile_openapi(self, ctx: "OpenAPIContext") -> "OpenAPIContext":
        from emergent.wire.axis._capability import openapi_schema
        return openapi_schema(ctx, readOnly=True)


@dataclass(frozen=True, slots=True)
class WriteOnly(OpenAPICapability):
    """Field is write-only (e.g., password)."""

    def compile_openapi(self, ctx: "OpenAPIContext") -> "OpenAPIContext":
        from emergent.wire.axis._capability import openapi_schema
        return openapi_schema(ctx, writeOnly=True)


@dataclass(frozen=True, slots=True)
class Deprecated(OpenAPICapability):
    """Mark field as deprecated."""

    def compile_openapi(self, ctx: "OpenAPIContext") -> "OpenAPIContext":
        from emergent.wire.axis._capability import openapi_schema
        return openapi_schema(ctx, deprecated=True)


# ═══════════════════════════════════════════════════════════════════════════════
# Schema Composition
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Ref(OpenAPICapability):
    """Explicit $ref to another schema.

    Example:
        address: Annotated[Address, openapi.Ref("#/components/schemas/Address")]
    """
    ref: str

    def compile_openapi(self, ctx: "OpenAPIContext") -> "OpenAPIContext":
        from emergent.wire.axis._capability import openapi_schema
        return openapi_schema(ctx, **{"$ref": self.ref})


@dataclass(frozen=True, slots=True)
class Discriminator(OpenAPICapability):
    """Discriminator for polymorphic schemas.

    Example:
        pet: Annotated[Pet, openapi.Discriminator("petType", {"dog": Dog, "cat": Cat})]
    """
    property_name: str
    mapping: dict[str, type] | None = None

    def compile_openapi(self, ctx: "OpenAPIContext") -> "OpenAPIContext":
        from emergent.wire.axis._capability import openapi_schema, JsonSchemaValue
        disc: dict[str, JsonSchemaValue] = {"propertyName": self.property_name}
        if self.mapping:
            disc["mapping"] = {k: v.__name__ for k, v in self.mapping.items()}
        return openapi_schema(ctx, discriminator=disc)


__all__ = (
    "OpenAPICapability",
    # Format
    "Format",
    # Content
    "ContentMediaType",
    "ContentEncoding",
    # Documentation
    "Title",
    "Description",
    "Examples",
    "Default",
    "ReadOnly",
    "WriteOnly",
    "Deprecated",
    # Composition
    "Ref",
    "Discriminator",
)

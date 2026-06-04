"""OpenAPI dialect — OpenAPI-specific capabilities.

These are IGNORED by other compilers (SQLAlchemy, Pydantic, etc.).
For cross-target capabilities (ReadOnly, WriteOnly, Deprecated, etc.)
use universal capabilities from emergent.wire.axis.schema.

    from emergent.wire.axis.schema.dialects import openapi

    @dataclass
    class User:
        email: Annotated[str, Unique, openapi.Format("email")]
        website: Annotated[str, openapi.Format("uri")]
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import TYPE_CHECKING

from emergent.wire.axis.schema._universal import SchemaAxisCapability

if TYPE_CHECKING:
    from emergent.wire.axis._capability import OpenAPIContext, OpenAPISchemaContext, JsonSchemaValue

# Type for OpenAPI example values
ExampleValue = str | int | float | bool | None | list["ExampleValue"] | dict[str, "ExampleValue"]

type TypeMapping = dict[str, type]
type DiscriminatorSchema = dict[str, "JsonSchemaValue"]


class OpenAPICapability(SchemaAxisCapability):
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
    """OpenAPI-only description.

    For cross-target descriptions, use universal Doc() instead.
    """
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
    """Default value in OpenAPI schema.

    For Python-level defaults, use field(default=...) instead.
    """
    value: ExampleValue

    def compile_openapi(self, ctx: "OpenAPIContext") -> "OpenAPIContext":
        from emergent.wire.axis._capability import openapi_schema
        return openapi_schema(ctx, default=self.value)


@dataclass(frozen=True, slots=True)
class Discriminator(OpenAPICapability):
    """Polymorphism discriminator for inheritance.

    Example:
        @schema_meta(Discriminator("type", {"dog": Dog, "cat": Cat}))
        @dataclass
        class Pet: ...

    OpenAPI: discriminator object
    """

    field: str
    mapping: MappingProxyType[str, type]

    def __init__(self, field: str, mapping: TypeMapping) -> None:
        object.__setattr__(self, "field", field)
        object.__setattr__(self, "mapping", MappingProxyType(mapping))

    def compile_openapi_schema(
        self, ctx: "OpenAPISchemaContext"
    ) -> "OpenAPISchemaContext":
        disc: DiscriminatorSchema = {"propertyName": self.field}
        if self.mapping:
            disc["mapping"] = {k: v.__name__ for k, v in self.mapping.items()}
        return replace(ctx, schema={**ctx.schema, "discriminator": disc})


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
    # Schema-level
    "Discriminator",
)

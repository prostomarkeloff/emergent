"""OpenAPI dialect — OpenAPI-specific capabilities.

These are IGNORED by other compilers (SQLAlchemy, Pydantic, etc.).

    from emergent.wire.axis.schema.dialects import openapi

    @dataclass
    class User:
        email: Annotated[str, Unique, openapi.Format("email")]
        website: Annotated[str, openapi.Format("uri")]
"""

from dataclasses import dataclass
from typing import Any

from emergent.wire.axis.schema._universal import Capability


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


@dataclass(frozen=True, slots=True)
class ContentEncoding(OpenAPICapability):
    """Encoding of string content.

    Example:
        data: Annotated[str, openapi.ContentEncoding("base64")]
    """
    encoding: str


# ═══════════════════════════════════════════════════════════════════════════════
# Documentation
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Title(OpenAPICapability):
    """Schema title."""
    title: str


@dataclass(frozen=True, slots=True)
class Description(OpenAPICapability):
    """Schema description."""
    description: str


@dataclass(frozen=True, slots=True)
class Examples(OpenAPICapability):
    """Example values for documentation."""
    values: tuple[Any, ...]

    def __init__(self, *values: Any) -> None:
        object.__setattr__(self, "values", values)


@dataclass(frozen=True, slots=True)
class Default(OpenAPICapability):
    """Default value in schema."""
    value: Any


@dataclass(frozen=True, slots=True)
class ReadOnly(OpenAPICapability):
    """Field is read-only."""
    pass


@dataclass(frozen=True, slots=True)
class WriteOnly(OpenAPICapability):
    """Field is write-only (e.g., password)."""
    pass


@dataclass(frozen=True, slots=True)
class Deprecated(OpenAPICapability):
    """Mark field as deprecated."""
    pass


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


@dataclass(frozen=True, slots=True)
class Discriminator(OpenAPICapability):
    """Discriminator for polymorphic schemas.

    Example:
        pet: Annotated[Pet, openapi.Discriminator("petType", {"dog": Dog, "cat": Cat})]
    """
    property_name: str
    mapping: dict[str, type] | None = None


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

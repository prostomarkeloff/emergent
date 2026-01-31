"""Schema compilation protocols — opt-in interfaces for custom capabilities.

Capabilities are pure data. To customize compilation for a specific target,
implement the corresponding protocol.

    @dataclass(frozen=True, slots=True)
    class Encrypted(Capability):
        algorithm: str = "AES-256"

        # Opt-in: implement protocols for targets you care about
        def to_openapi(self) -> OpenAPISchema:
            return {"format": "encrypted", "x-algorithm": self.algorithm}

        def to_sqlalchemy(self, field_name: str, field_type: type) -> SQLAlchemyConfig:
            return {"type": EncryptedType(self.algorithm)}

Compilers check `isinstance(cap, Protocol)` and call the method if implemented.
No magic, no registry, no global state.

NOTE: These protocols are for SCHEMA compilation (data shape).
For runtime behavior (middleware, rate limiting, etc.) use wire/axis/surface.
"""

from __future__ import annotations

from typing import Any, Protocol, TypedDict, runtime_checkable


# ═══════════════════════════════════════════════════════════════════════════════
# Return Types — strict TypedDicts
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


class PydanticSchema(TypedDict, total=False):
    """Pydantic Field() kwargs."""
    # Numeric constraints
    ge: int | float
    gt: int | float
    le: int | float
    lt: int | float
    multiple_of: int | float
    # String constraints
    min_length: int
    max_length: int
    pattern: str
    # Documentation
    description: str
    deprecated: str | bool
    # Other
    strict: bool
    alias: str


class CLISchema(TypedDict, total=False):
    """argparse add_argument() kwargs."""
    help: str
    metavar: str
    type: type
    choices: list[Any]
    required: bool
    default: Any
    nargs: str | int
    action: str


class SQLAlchemyConfig(TypedDict, total=False):
    """SQLAlchemy Column configuration."""
    type: Any  # TypeDecorator or Column type
    index: bool
    unique: bool
    nullable: bool
    primary_key: bool
    default: Any
    server_default: str


class ProtobufSchema(TypedDict, total=False):
    """Protobuf field options."""
    field_number: int
    packed: bool
    deprecated: bool


# ═══════════════════════════════════════════════════════════════════════════════
# OpenAPI / JSON Schema
# ═══════════════════════════════════════════════════════════════════════════════


@runtime_checkable
class OpenAPICompilable(Protocol):
    """Capability that compiles to OpenAPI/JSON Schema properties.

    Return dict is merged into field schema.

    Example:
        def to_openapi(self) -> OpenAPISchema:
            return {"format": "email", "maxLength": 255}
    """

    def to_openapi(self) -> OpenAPISchema:
        """Return OpenAPI schema properties."""
        ...


# ═══════════════════════════════════════════════════════════════════════════════
# SQLAlchemy
# ═══════════════════════════════════════════════════════════════════════════════


@runtime_checkable
class SQLAlchemyCompilable(Protocol):
    """Capability that compiles to SQLAlchemy column configuration.

    Example:
        def to_sqlalchemy(self, field_name: str, field_type: type) -> SQLAlchemyConfig:
            return {"index": True, "unique": True}
    """

    def to_sqlalchemy(self, field_name: str, field_type: type) -> SQLAlchemyConfig:
        """Return SQLAlchemy column configuration."""
        ...


# ═══════════════════════════════════════════════════════════════════════════════
# Pydantic
# ═══════════════════════════════════════════════════════════════════════════════


@runtime_checkable
class PydanticCompilable(Protocol):
    """Capability that compiles to Pydantic field configuration.

    Return dict is passed to Field() constructor.

    Example:
        def to_pydantic(self) -> PydanticSchema:
            return {"max_length": 255, "pattern": r"^[a-z]+$"}
    """

    def to_pydantic(self) -> PydanticSchema:
        """Return Pydantic Field kwargs."""
        ...


# ═══════════════════════════════════════════════════════════════════════════════
# CLI (argparse)
# ═══════════════════════════════════════════════════════════════════════════════


@runtime_checkable
class CLICompilable(Protocol):
    """Capability that compiles to argparse argument configuration.

    Example:
        def to_cli(self) -> CLISchema:
            return {"help": "Username for login", "metavar": "USER"}
    """

    def to_cli(self) -> CLISchema:
        """Return argparse add_argument kwargs."""
        ...


# ═══════════════════════════════════════════════════════════════════════════════
# Protobuf
# ═══════════════════════════════════════════════════════════════════════════════


@runtime_checkable
class ProtobufCompilable(Protocol):
    """Capability that compiles to Protobuf field options.

    Example:
        def to_protobuf(self) -> ProtobufSchema:
            return {"field_number": 1, "packed": True}
    """

    def to_protobuf(self) -> ProtobufSchema:
        """Return Protobuf field options."""
        ...


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════


def compile_openapi(capabilities: list[Any]) -> dict[str, Any]:
    """Compile all OpenAPI-compatible capabilities to schema dict."""
    result: dict[str, Any] = {}
    for cap in capabilities:
        if isinstance(cap, OpenAPICompilable):
            result.update(cap.to_openapi())
    return result


def compile_pydantic(capabilities: list[Any]) -> dict[str, Any]:
    """Compile all Pydantic-compatible capabilities to Field kwargs."""
    result: dict[str, Any] = {}
    for cap in capabilities:
        if isinstance(cap, PydanticCompilable):
            result.update(cap.to_pydantic())
    return result


def compile_cli(capabilities: list[Any]) -> dict[str, Any]:
    """Compile all CLI-compatible capabilities to add_argument kwargs."""
    result: dict[str, Any] = {}
    for cap in capabilities:
        if isinstance(cap, CLICompilable):
            result.update(cap.to_cli())
    return result


__all__ = (
    # Protocols
    "OpenAPICompilable",
    "SQLAlchemyCompilable",
    "PydanticCompilable",
    "CLICompilable",
    "ProtobufCompilable",
    # Helpers
    "compile_openapi",
    "compile_pydantic",
    "compile_cli",
)

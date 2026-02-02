"""Universal schema capabilities — understood by ALL compilers.

    email: Annotated[str, Unique, MaxLen(255)]

    # Compiler translates:
    # - Pydantic: Field(max_length=255)
    # - OpenAPI: {"maxLength": 255}
    # - SQLAlchemy: Column(String(255), unique=True)

## Custom Capabilities

    from emergent.wire.axis._capability import PydanticContext, OpenAPIContext, openapi_schema
    import copy

    @dataclass(frozen=True, slots=True)
    class Sensitive(UniversalCapability):
        def compile_pydantic(self, ctx: PydanticContext) -> PydanticContext:
            from dataclasses import replace
            fi = copy.deepcopy(ctx.field_info)
            fi.json_schema_extra = {"writeOnly": True}
            return replace(ctx, field_info=fi)

        def compile_openapi(self, ctx: OpenAPIContext) -> OpenAPIContext:
            return openapi_schema(ctx, writeOnly=True)
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from emergent.wire.axis._capability import Capability as RootCapability

# Type for enum values (JSON-compatible primitives)
EnumValue = str | int | float | bool | None

if TYPE_CHECKING:
    from emergent.wire.axis._capability import (
        # Field-level
        PydanticContext,
        OpenAPIContext,
        ArgparseContext,
        SQLAlchemyContext,
        # Schema-level
        PydanticModelContext,
        OpenAPISchemaContext,
        SQLAlchemyTableContext,
        # Types
        JsonSchemaValue,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Base
# ═══════════════════════════════════════════════════════════════════════════════


class Capability(RootCapability):
    """Base for all schema capabilities."""
    pass


class UniversalCapability(Capability):
    """Base for universal capabilities — all compilers understand."""
    pass


# ═══════════════════════════════════════════════════════════════════════════════
# Schema-Level
# ═══════════════════════════════════════════════════════════════════════════════


_SCHEMA_META_ATTR = "__schema_capabilities__"


class SchemaCapability(Capability):
    """Schema-level capability — applied to whole class via @schema_meta."""
    pass


def schema_meta(*capabilities: SchemaCapability):
    """Attach schema-level capabilities to a class."""
    def decorator(cls: type) -> type:
        existing = getattr(cls, _SCHEMA_META_ATTR, ())
        setattr(cls, _SCHEMA_META_ATTR, (*existing, *capabilities))
        return cls
    return decorator


def get_schema_meta(cls: type) -> tuple[SchemaCapability, ...]:
    """Get all schema-level capabilities from a class."""
    return getattr(cls, _SCHEMA_META_ATTR, ())


def get_schema_capability(cls: type, cap_type: type[SchemaCapability]) -> SchemaCapability | None:
    """Get specific schema capability by type."""
    for cap in get_schema_meta(cls):
        if isinstance(cap, cap_type):
            return cap
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# Universal Schema-Level Capabilities
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class SchemaName(SchemaCapability):
    """Override model/table/schema name.

    Example:
        @schema_meta(SchemaName("users"))
        @dataclass
        class User: ...

    SQL: __tablename__ = "users"
    Pydantic: model title
    OpenAPI: schema title
    """
    value: str

    def compile_pydantic_model(self, ctx: "PydanticModelContext") -> "PydanticModelContext":
        return replace(ctx, title=self.value)

    def compile_openapi_schema(self, ctx: "OpenAPISchemaContext") -> "OpenAPISchemaContext":
        return replace(ctx, schema={**ctx.schema, "title": self.value})

    def compile_sqlalchemy_table(self, ctx: "SQLAlchemyTableContext") -> "SQLAlchemyTableContext":
        return replace(ctx, table_name=self.value)


@dataclass(frozen=True, slots=True)
class SchemaDoc(SchemaCapability):
    """Schema-level description.

    Example:
        @schema_meta(SchemaDoc("Represents a user in the system"))
        @dataclass
        class User: ...
    """
    description: str

    def compile_pydantic_model(self, ctx: "PydanticModelContext") -> "PydanticModelContext":
        return replace(ctx, description=self.description)

    def compile_openapi_schema(self, ctx: "OpenAPISchemaContext") -> "OpenAPISchemaContext":
        return replace(ctx, schema={**ctx.schema, "description": self.description})


@dataclass(frozen=True, slots=True)
class CompositeUnique(SchemaCapability):
    """Unique constraint across multiple fields.

    Example:
        @schema_meta(CompositeUnique("email", "tenant_id"))
        @dataclass
        class User: ...

    SQL: UNIQUE(email, tenant_id)
    """
    fields: tuple[str, ...]
    name: str | None = None

    def __init__(self, *fields: str, name: str | None = None) -> None:
        object.__setattr__(self, "fields", fields)
        object.__setattr__(self, "name", name)

    def compile_sqlalchemy_table(self, ctx: "SQLAlchemyTableContext") -> "SQLAlchemyTableContext":
        return replace(ctx, constraints=(*ctx.constraints, self.fields))


@dataclass(frozen=True, slots=True)
class CompositeIndex(SchemaCapability):
    """Index across multiple fields.

    Example:
        @schema_meta(CompositeIndex("status", "created_at", name="idx_status_date"))
        @dataclass
        class Order: ...

    SQL: CREATE INDEX
    """
    fields: tuple[str, ...]
    name: str | None = None
    unique: bool = False

    def __init__(self, *fields: str, name: str | None = None, unique: bool = False) -> None:
        object.__setattr__(self, "fields", fields)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "unique", unique)

    def compile_sqlalchemy_table(self, ctx: "SQLAlchemyTableContext") -> "SQLAlchemyTableContext":
        return replace(ctx, indexes=(*ctx.indexes, self.fields))


@dataclass(frozen=True, slots=True)
class Discriminator(SchemaCapability):
    """Polymorphism discriminator for inheritance.

    Example:
        @schema_meta(Discriminator("type", {"dog": Dog, "cat": Cat}))
        @dataclass
        class Pet: ...

    SQL: discriminator column
    Pydantic: tagged union discriminator
    OpenAPI: discriminator object
    """
    field: str
    mapping: dict[str, type]

    def compile_openapi_schema(self, ctx: "OpenAPISchemaContext") -> "OpenAPISchemaContext":
        disc: dict[str, JsonSchemaValue] = {"propertyName": self.field}
        if self.mapping:
            disc["mapping"] = {k: v.__name__ for k, v in self.mapping.items()}
        return replace(ctx, schema={**ctx.schema, "discriminator": disc})


@dataclass(frozen=True, slots=True)
class Abstract(SchemaCapability):
    """Mark schema as abstract (no direct instantiation).

    Example:
        @schema_meta(Abstract())
        @dataclass
        class BaseEntity: ...

    SQL: no table created
    Pydantic: cannot instantiate directly
    """

    def compile_pydantic_model(self, ctx: "PydanticModelContext") -> "PydanticModelContext":
        return replace(ctx, is_abstract=True)

    def compile_sqlalchemy_table(self, ctx: "SQLAlchemyTableContext") -> "SQLAlchemyTableContext":
        return replace(ctx, is_abstract=True)


# ═══════════════════════════════════════════════════════════════════════════════
# Identity & Uniqueness
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Identity(UniversalCapability):
    """Entity identifier → SQL PRIMARY KEY."""

    def compile_sqlalchemy(self, ctx: "SQLAlchemyContext") -> "SQLAlchemyContext":
        from emergent.wire.axis._capability import sqlalchemy_column
        return sqlalchemy_column(ctx, primary_key=True)


@dataclass(frozen=True, slots=True)
class Unique(UniversalCapability):
    """Unique constraint → SQL UNIQUE."""

    def compile_sqlalchemy(self, ctx: "SQLAlchemyContext") -> "SQLAlchemyContext":
        from emergent.wire.axis._capability import sqlalchemy_column
        return sqlalchemy_column(ctx, unique=True)


# ═══════════════════════════════════════════════════════════════════════════════
# References
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Ref(UniversalCapability):
    """Reference to another entity → SQL FOREIGN KEY."""
    target: type | str
    on_delete: str = "CASCADE"
    on_update: str = "CASCADE"


# ═══════════════════════════════════════════════════════════════════════════════
# Numbers
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Min(UniversalCapability):
    """Minimum value (inclusive)."""
    value: int | float

    def compile_pydantic(self, ctx: "PydanticContext") -> "PydanticContext":
        from annotated_types import Ge
        fi = copy.deepcopy(ctx.field_info)
        fi.metadata.append(Ge(ge=self.value))
        return replace(ctx, field_info=fi)

    def compile_openapi(self, ctx: "OpenAPIContext") -> "OpenAPIContext":
        from emergent.wire.axis._capability import openapi_schema
        return openapi_schema(ctx, minimum=self.value)


@dataclass(frozen=True, slots=True)
class Max(UniversalCapability):
    """Maximum value (inclusive)."""
    value: int | float

    def compile_pydantic(self, ctx: "PydanticContext") -> "PydanticContext":
        from annotated_types import Le
        fi = copy.deepcopy(ctx.field_info)
        fi.metadata.append(Le(le=self.value))
        return replace(ctx, field_info=fi)

    def compile_openapi(self, ctx: "OpenAPIContext") -> "OpenAPIContext":
        from emergent.wire.axis._capability import openapi_schema
        return openapi_schema(ctx, maximum=self.value)


@dataclass(frozen=True, slots=True)
class ExclusiveMin(UniversalCapability):
    """Minimum value (exclusive)."""
    value: int | float

    def compile_pydantic(self, ctx: "PydanticContext") -> "PydanticContext":
        from annotated_types import Gt
        fi = copy.deepcopy(ctx.field_info)
        fi.metadata.append(Gt(gt=self.value))
        return replace(ctx, field_info=fi)

    def compile_openapi(self, ctx: "OpenAPIContext") -> "OpenAPIContext":
        from emergent.wire.axis._capability import openapi_schema
        return openapi_schema(ctx, exclusiveMinimum=self.value)


@dataclass(frozen=True, slots=True)
class ExclusiveMax(UniversalCapability):
    """Maximum value (exclusive)."""
    value: int | float

    def compile_pydantic(self, ctx: "PydanticContext") -> "PydanticContext":
        from annotated_types import Lt
        fi = copy.deepcopy(ctx.field_info)
        fi.metadata.append(Lt(lt=self.value))
        return replace(ctx, field_info=fi)

    def compile_openapi(self, ctx: "OpenAPIContext") -> "OpenAPIContext":
        from emergent.wire.axis._capability import openapi_schema
        return openapi_schema(ctx, exclusiveMaximum=self.value)


@dataclass(frozen=True, slots=True)
class MultipleOf(UniversalCapability):
    """Value must be multiple of n."""
    value: int | float

    def compile_pydantic(self, ctx: "PydanticContext") -> "PydanticContext":
        from annotated_types import MultipleOf as ATMultipleOf
        fi = copy.deepcopy(ctx.field_info)
        fi.metadata.append(ATMultipleOf(multiple_of=self.value))
        return replace(ctx, field_info=fi)

    def compile_openapi(self, ctx: "OpenAPIContext") -> "OpenAPIContext":
        from emergent.wire.axis._capability import openapi_schema
        return openapi_schema(ctx, multipleOf=self.value)


# ═══════════════════════════════════════════════════════════════════════════════
# Strings/Collections
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class MinLen(UniversalCapability):
    """Minimum length."""
    value: int

    def compile_pydantic(self, ctx: "PydanticContext") -> "PydanticContext":
        from annotated_types import MinLen as ATMinLen
        fi = copy.deepcopy(ctx.field_info)
        fi.metadata.append(ATMinLen(min_length=self.value))
        return replace(ctx, field_info=fi)

    def compile_openapi(self, ctx: "OpenAPIContext") -> "OpenAPIContext":
        from emergent.wire.axis._capability import openapi_schema
        return openapi_schema(ctx, minLength=self.value)


@dataclass(frozen=True, slots=True)
class MaxLen(UniversalCapability):
    """Maximum length."""
    value: int

    def compile_pydantic(self, ctx: "PydanticContext") -> "PydanticContext":
        from annotated_types import MaxLen as ATMaxLen
        fi = copy.deepcopy(ctx.field_info)
        fi.metadata.append(ATMaxLen(max_length=self.value))
        return replace(ctx, field_info=fi)

    def compile_openapi(self, ctx: "OpenAPIContext") -> "OpenAPIContext":
        from emergent.wire.axis._capability import openapi_schema
        return openapi_schema(ctx, maxLength=self.value)


@dataclass(frozen=True, slots=True)
class Pattern(UniversalCapability):
    """Regex pattern."""
    regex: str

    def compile_pydantic(self, ctx: "PydanticContext") -> "PydanticContext":
        from pydantic.fields import FieldInfo
        fi = copy.deepcopy(ctx.field_info)
        # Pattern is stored in metadata as _PydanticGeneralMetadata
        fi.metadata.extend(FieldInfo(pattern=self.regex).metadata)
        return replace(ctx, field_info=fi)

    def compile_openapi(self, ctx: "OpenAPIContext") -> "OpenAPIContext":
        from emergent.wire.axis._capability import openapi_schema
        return openapi_schema(ctx, pattern=self.regex)


# ═══════════════════════════════════════════════════════════════════════════════
# Enums & Unions
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class OneOf(UniversalCapability):
    """Enum values."""
    values: tuple[EnumValue, ...]

    def __init__(self, *values: EnumValue) -> None:
        object.__setattr__(self, "values", values)

    def compile_openapi(self, ctx: "OpenAPIContext") -> "OpenAPIContext":
        from emergent.wire.axis._capability import openapi_schema
        return openapi_schema(ctx, enum=list(self.values))

    def compile_argparse(self, ctx: "ArgparseContext") -> "ArgparseContext":
        from emergent.wire.axis._capability import argparse_arg
        return argparse_arg(ctx, choices=list(self.values))


@dataclass(frozen=True, slots=True)
class Either(UniversalCapability):
    """Tagged union."""
    discriminator: str = "type"


@dataclass(frozen=True, slots=True)
class Embedded(UniversalCapability):
    """Embedded inline (not normalized)."""
    pass


# ═══════════════════════════════════════════════════════════════════════════════
# Documentation
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Doc(UniversalCapability):
    """Description."""
    text: str

    def compile_pydantic(self, ctx: "PydanticContext") -> "PydanticContext":
        fi = copy.deepcopy(ctx.field_info)
        fi.description = self.text
        return replace(ctx, field_info=fi)

    def compile_openapi(self, ctx: "OpenAPIContext") -> "OpenAPIContext":
        from emergent.wire.axis._capability import openapi_schema
        return openapi_schema(ctx, description=self.text)

    def compile_argparse(self, ctx: "ArgparseContext") -> "ArgparseContext":
        from emergent.wire.axis._capability import argparse_arg
        return argparse_arg(ctx, help=self.text)


@dataclass(frozen=True, slots=True)
class Deprecated(UniversalCapability):
    """Mark as deprecated."""
    reason: str | None = None

    def compile_pydantic(self, ctx: "PydanticContext") -> "PydanticContext":
        fi = copy.deepcopy(ctx.field_info)
        fi.deprecated = self.reason or True
        return replace(ctx, field_info=fi)

    def compile_openapi(self, ctx: "OpenAPIContext") -> "OpenAPIContext":
        from emergent.wire.axis._capability import openapi_schema
        return openapi_schema(ctx, deprecated=True)


__all__ = (
    "Capability",
    "UniversalCapability",
    # Schema-level
    "SchemaCapability",
    "schema_meta",
    "get_schema_meta",
    "get_schema_capability",
    "SchemaName",
    "SchemaDoc",
    "CompositeUnique",
    "CompositeIndex",
    "Discriminator",
    "Abstract",
    # Field-level
    "Identity",
    "Unique",
    "Ref",
    "Min",
    "Max",
    "ExclusiveMin",
    "ExclusiveMax",
    "MultipleOf",
    "MinLen",
    "MaxLen",
    "Pattern",
    "OneOf",
    "Either",
    "Embedded",
    "Doc",
    "Deprecated",
)

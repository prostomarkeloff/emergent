"""Universal schema capabilities — understood by ALL compilers.

    email: Annotated[str, Unique, MaxLen(255)]

    # Compiler translates:
    # - Pydantic: Field(max_length=255)
    # - OpenAPI: {"maxLength": 255}
    # - SQLAlchemy: Column(String(255), unique=True)

## Custom Capabilities

    from emergent.wire.axis._capability import PydanticContext, OpenAPIContext, openapi_schema, pydantic_extra

    @dataclass(frozen=True, slots=True)
    class Sensitive(UniversalCapability):
        def compile_pydantic(self, ctx: PydanticContext) -> PydanticContext:
            return pydantic_extra(ctx, writeOnly=True)

        def compile_openapi(self, ctx: OpenAPIContext) -> OpenAPIContext:
            return openapi_schema(ctx, writeOnly=True)
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from emergent.wire.axis._capability import (
    Capability as RootCapability,
    openapi_schema,
    argparse_arg,
    sqlalchemy_column,
    pydantic_metadata,
    pydantic_extra,
    pydantic_field,
)

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
        # Constraints
        ConstraintsContext,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Base
# ═══════════════════════════════════════════════════════════════════════════════


class SchemaAxisCapability(RootCapability):
    """Base for all schema axis capabilities.

    Inherits from root Capability to maintain the capability hierarchy.
    All dialect capabilities (sql, openapi, pydantic, cli, etc.) inherit from this.
    """

    pass


class UniversalCapability(SchemaAxisCapability):
    """Base for universal capabilities — all compilers understand."""

    pass


# ═══════════════════════════════════════════════════════════════════════════════
# Schema-Level
# ═══════════════════════════════════════════════════════════════════════════════


_SCHEMA_META_ATTR = "__schema_capabilities__"


class SchemaCapability(SchemaAxisCapability):
    """Schema-level capability — applied to whole class via @schema_meta."""

    pass


def schema_meta(*capabilities: SchemaCapability):
    """Attach schema-level capabilities to a class."""

    def decorator[T](cls: T) -> T:
        existing = getattr(cls, _SCHEMA_META_ATTR, ())
        setattr(cls, _SCHEMA_META_ATTR, (*existing, *capabilities))
        return cls

    return decorator


def get_schema_meta(cls: type) -> tuple[SchemaCapability, ...]:
    """Get all schema-level capabilities from a class."""
    return getattr(cls, _SCHEMA_META_ATTR, ())


def get_schema_capability(
    cls: type, cap_type: type[SchemaCapability]
) -> SchemaCapability | None:
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

    def compile_pydantic_model(
        self, ctx: "PydanticModelContext"
    ) -> "PydanticModelContext":
        return replace(ctx, title=self.value)

    def compile_openapi_schema(
        self, ctx: "OpenAPISchemaContext"
    ) -> "OpenAPISchemaContext":
        return replace(ctx, schema={**ctx.schema, "title": self.value})

    def compile_sqlalchemy_table(
        self, ctx: "SQLAlchemyTableContext"
    ) -> "SQLAlchemyTableContext":
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

    def compile_pydantic_model(
        self, ctx: "PydanticModelContext"
    ) -> "PydanticModelContext":
        return replace(ctx, description=self.description)

    def compile_openapi_schema(
        self, ctx: "OpenAPISchemaContext"
    ) -> "OpenAPISchemaContext":
        return replace(ctx, schema={**ctx.schema, "description": self.description})


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

    def compile_pydantic_model(
        self, ctx: "PydanticModelContext"
    ) -> "PydanticModelContext":
        return replace(ctx, is_abstract=True)

    def compile_sqlalchemy_table(
        self, ctx: "SQLAlchemyTableContext"
    ) -> "SQLAlchemyTableContext":
        return replace(ctx, is_abstract=True)


# ═══════════════════════════════════════════════════════════════════════════════
#   & Uniqueness
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Identity(UniversalCapability):
    """Entity identifier → SQL PRIMARY KEY."""

    def compile_sqlalchemy(self, ctx: "SQLAlchemyContext") -> "SQLAlchemyContext":
        return sqlalchemy_column(ctx, primary_key=True)

    def compile_constraints(self, ctx: "ConstraintsContext") -> "ConstraintsContext":
        return replace(ctx, is_identity=True)


@dataclass(frozen=True, slots=True)
class Unique(UniversalCapability):
    """Unique constraint → SQL UNIQUE."""

    def compile_sqlalchemy(self, ctx: "SQLAlchemyContext") -> "SQLAlchemyContext":
        return sqlalchemy_column(ctx, unique=True)

    def compile_constraints(self, ctx: "ConstraintsContext") -> "ConstraintsContext":
        return replace(ctx, is_unique=True)


# ═══════════════════════════════════════════════════════════════════════════════
# References
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Ref(UniversalCapability):
    """Reference to another entity → SQL FOREIGN KEY."""

    target: type | str
    on_delete: str = "CASCADE"
    on_update: str = "CASCADE"

    def _resolve_fk_target(self) -> str:
        """Resolve target to 'table.column' string for SA ForeignKey."""
        if isinstance(self.target, str):
            return self.target
        table = getattr(
            self.target, "__tablename__",
            self.target.__name__.lower(),
        )
        return f"{table}.id"

    def compile_sqlalchemy(self, ctx: SQLAlchemyContext) -> SQLAlchemyContext:
        return sqlalchemy_column(ctx,
            fk_target=self._resolve_fk_target(),
            fk_ondelete=self.on_delete,
            fk_onupdate=self.on_update,
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Numbers
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Min(UniversalCapability):
    """Minimum value (inclusive)."""

    value: int | float

    def compile_pydantic(self, ctx: "PydanticContext") -> "PydanticContext":
        from annotated_types import Ge

        return pydantic_metadata(ctx, Ge(ge=self.value))

    def compile_openapi(self, ctx: "OpenAPIContext") -> "OpenAPIContext":
        return openapi_schema(ctx, minimum=self.value)

    def compile_constraints(self, ctx: "ConstraintsContext") -> "ConstraintsContext":
        return replace(ctx, min_value=self.value)


@dataclass(frozen=True, slots=True)
class Max(UniversalCapability):
    """Maximum value (inclusive)."""

    value: int | float

    def compile_pydantic(self, ctx: "PydanticContext") -> "PydanticContext":
        from annotated_types import Le

        return pydantic_metadata(ctx, Le(le=self.value))

    def compile_openapi(self, ctx: "OpenAPIContext") -> "OpenAPIContext":
        return openapi_schema(ctx, maximum=self.value)

    def compile_constraints(self, ctx: "ConstraintsContext") -> "ConstraintsContext":
        return replace(ctx, max_value=self.value)


@dataclass(frozen=True, slots=True)
class ExclusiveMin(UniversalCapability):
    """Minimum value (exclusive)."""

    value: int | float

    def compile_pydantic(self, ctx: "PydanticContext") -> "PydanticContext":
        from annotated_types import Gt

        return pydantic_metadata(ctx, Gt(gt=self.value))

    def compile_openapi(self, ctx: "OpenAPIContext") -> "OpenAPIContext":
        return openapi_schema(ctx, exclusiveMinimum=self.value)

    def compile_constraints(self, ctx: "ConstraintsContext") -> "ConstraintsContext":
        return replace(ctx, exclusive_min=self.value)


@dataclass(frozen=True, slots=True)
class ExclusiveMax(UniversalCapability):
    """Maximum value (exclusive)."""

    value: int | float

    def compile_pydantic(self, ctx: "PydanticContext") -> "PydanticContext":
        from annotated_types import Lt

        return pydantic_metadata(ctx, Lt(lt=self.value))

    def compile_openapi(self, ctx: "OpenAPIContext") -> "OpenAPIContext":
        return openapi_schema(ctx, exclusiveMaximum=self.value)

    def compile_constraints(self, ctx: "ConstraintsContext") -> "ConstraintsContext":
        return replace(ctx, exclusive_max=self.value)


@dataclass(frozen=True, slots=True)
class MultipleOf(UniversalCapability):
    """Value must be multiple of n."""

    value: int | float

    def compile_pydantic(self, ctx: "PydanticContext") -> "PydanticContext":
        from annotated_types import MultipleOf as ATMultipleOf

        return pydantic_metadata(ctx, ATMultipleOf(multiple_of=self.value))

    def compile_openapi(self, ctx: "OpenAPIContext") -> "OpenAPIContext":
        return openapi_schema(ctx, multipleOf=self.value)

    def compile_constraints(self, ctx: "ConstraintsContext") -> "ConstraintsContext":
        return replace(ctx, multiple_of=self.value)


# ═══════════════════════════════════════════════════════════════════════════════
# Strings/Collections
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class MinLen(UniversalCapability):
    """Minimum length."""

    value: int

    def compile_pydantic(self, ctx: "PydanticContext") -> "PydanticContext":
        from annotated_types import MinLen as ATMinLen

        return pydantic_metadata(ctx, ATMinLen(min_length=self.value))

    def compile_openapi(self, ctx: "OpenAPIContext") -> "OpenAPIContext":
        return openapi_schema(ctx, minLength=self.value)

    def compile_constraints(self, ctx: "ConstraintsContext") -> "ConstraintsContext":
        return replace(ctx, min_length=self.value)


@dataclass(frozen=True, slots=True)
class MaxLen(UniversalCapability):
    """Maximum length."""

    value: int

    def compile_pydantic(self, ctx: "PydanticContext") -> "PydanticContext":
        from annotated_types import MaxLen as ATMaxLen

        return pydantic_metadata(ctx, ATMaxLen(max_length=self.value))

    def compile_openapi(self, ctx: "OpenAPIContext") -> "OpenAPIContext":
        return openapi_schema(ctx, maxLength=self.value)

    def compile_constraints(self, ctx: "ConstraintsContext") -> "ConstraintsContext":
        return replace(ctx, max_length=self.value)


@dataclass(frozen=True, slots=True)
class Pattern(UniversalCapability):
    """Regex pattern."""

    regex: str

    def compile_pydantic(self, ctx: "PydanticContext") -> "PydanticContext":
        from pydantic.fields import FieldInfo as PydFieldInfo

        return pydantic_field(ctx, lambda fi: fi.metadata.extend(PydFieldInfo(pattern=self.regex).metadata))

    def compile_openapi(self, ctx: "OpenAPIContext") -> "OpenAPIContext":
        return openapi_schema(ctx, pattern=self.regex)

    def compile_constraints(self, ctx: "ConstraintsContext") -> "ConstraintsContext":
        return replace(ctx, pattern=self.regex)


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
        return openapi_schema(ctx, enum=list(self.values))

    def compile_argparse(self, ctx: "ArgparseContext") -> "ArgparseContext":
        return argparse_arg(ctx, choices=list(self.values))

    def compile_constraints(self, ctx: "ConstraintsContext") -> "ConstraintsContext":
        return replace(ctx, choices=self.values)


@dataclass(frozen=True, slots=True)
class Nested(UniversalCapability):
    """Ownership relation — child lifecycle tied to parent.

    Unlike Ref (FK reference, independent lifecycle),
    Nested implies aggregation/composition — child belongs to parent.

    Args:
        cascade: Cascade behavior ("all", "delete", "save-update", "none")
        meta: Override nested type's schema_meta at this usage site

    Example:
        # Simple ownership
        items: Annotated[list[OrderItem], Nested]

        # With cascade control
        items: Annotated[list[OrderItem], Nested(cascade="delete")]

        # With schema_meta override for nested type at this usage
        items: Annotated[list[OrderItem], Nested(meta=(SchemaName("order_items"),))]
    """

    cascade: str = "all"
    meta: tuple["SchemaCapability", ...] = ()

    def compile_openapi(self, ctx: "OpenAPIContext") -> "OpenAPIContext":
        return openapi_schema(ctx, **{"x-nested": True, "x-cascade": self.cascade})


@dataclass(frozen=True, slots=True)
class Embedded(UniversalCapability):
    """Inline nested structure — NOT normalized.

    - SQL: JSON column or denormalized columns
    - Pydantic: nested model
    - OpenAPI: inline schema

    Args:
        format: Storage format ("json" or "flatten")
        meta: Override nested type's schema_meta at this usage site

    Example:
        address: Annotated[Address, Embedded]
        address: Annotated[Address, Embedded(format="json")]
        address: Annotated[Address, Embedded(format="flatten")]  # Denormalized columns
        address: Annotated[Address, Embedded(meta=(SchemaName("billing"),))]
    """

    format: str = "json"
    meta: tuple["SchemaCapability", ...] = ()

    def compile_openapi(self, ctx: "OpenAPIContext") -> "OpenAPIContext":
        return openapi_schema(ctx, **{"x-embedded": True, "x-format": self.format})


# ═══════════════════════════════════════════════════════════════════════════════
# Documentation
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Doc(UniversalCapability):
    """Description."""

    text: str

    def compile_pydantic(self, ctx: "PydanticContext") -> "PydanticContext":
        return pydantic_field(ctx, lambda fi: setattr(fi, "description", self.text))

    def compile_openapi(self, ctx: "OpenAPIContext") -> "OpenAPIContext":
        return openapi_schema(ctx, description=self.text)

    def compile_argparse(self, ctx: "ArgparseContext") -> "ArgparseContext":
        return argparse_arg(ctx, help=self.text)


@dataclass(frozen=True, slots=True)
class Deprecated(UniversalCapability):
    """Mark as deprecated."""

    reason: str | None = None

    def compile_pydantic(self, ctx: "PydanticContext") -> "PydanticContext":
        return pydantic_field(ctx, lambda fi: setattr(fi, "deprecated", self.reason or True))

    def compile_openapi(self, ctx: "OpenAPIContext") -> "OpenAPIContext":
        return openapi_schema(ctx, deprecated=True)


# ═══════════════════════════════════════════════════════════════════════════════
# Access Control
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class ReadOnly(UniversalCapability):
    """Field is read-only — set by server, not by client.

    The field appears in responses but cannot be set via API requests.

    Example:
        @dataclass
        class User:
            id: Annotated[int, Identity, ReadOnly]
            created_at: Annotated[datetime, ReadOnly]

    Pydantic: json_schema_extra readOnly
    OpenAPI: readOnly: true
    """

    def compile_pydantic(self, ctx: "PydanticContext") -> "PydanticContext":
        return pydantic_extra(ctx, readOnly=True)

    def compile_openapi(self, ctx: "OpenAPIContext") -> "OpenAPIContext":
        return openapi_schema(ctx, readOnly=True)


@dataclass(frozen=True, slots=True)
class WriteOnly(UniversalCapability):
    """Field is write-only — accepted on input, excluded from output.

    The field can be set in requests but is never returned in responses.

    Example:
        @dataclass
        class User:
            password: Annotated[str, WriteOnly]

    Pydantic: json_schema_extra writeOnly
    OpenAPI: writeOnly: true
    """

    def compile_pydantic(self, ctx: "PydanticContext") -> "PydanticContext":
        return pydantic_extra(ctx, writeOnly=True)

    def compile_openapi(self, ctx: "OpenAPIContext") -> "OpenAPIContext":
        return openapi_schema(ctx, writeOnly=True)


@dataclass(frozen=True, slots=True)
class Sensitive(UniversalCapability):
    """Sensitive data — masked in repr, write-only, format: password.

    Superset of WriteOnly: additionally hides from repr and
    sets OpenAPI format to "password" for UI masking.

    Example:
        @dataclass
        class Credentials:
            password: Annotated[str, Sensitive]
            api_key: Annotated[str, Sensitive]

    Pydantic: repr=False, json_schema_extra writeOnly
    OpenAPI: writeOnly: true, format: "password"
    """

    def compile_pydantic(self, ctx: "PydanticContext") -> "PydanticContext":
        def _mutate(fi):  # type: (FieldInfo) -> None
            fi.repr = False
            existing = dict(fi.json_schema_extra) if fi.json_schema_extra else {}
            existing["writeOnly"] = True
            fi.json_schema_extra = existing

        return pydantic_field(ctx, _mutate)

    def compile_openapi(self, ctx: "OpenAPIContext") -> "OpenAPIContext":
        return openapi_schema(ctx, writeOnly=True, format="password")


@dataclass(frozen=True, slots=True)
class Immutable(UniversalCapability):
    """Field settable on create, immutable after.

    Unlike ReadOnly (never writable by client), Immutable allows
    the client to set the value on creation but prevents changes.

    Example:
        @dataclass
        class User:
            username: Annotated[str, Immutable]  # set once, never changed

    OpenAPI: x-immutable: true
    SQLAlchemy: onupdate marker
    """

    def compile_openapi(self, ctx: "OpenAPIContext") -> "OpenAPIContext":
        return openapi_schema(ctx, **{"x-immutable": True})


# ═══════════════════════════════════════════════════════════════════════════════
# Nullability
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Nullable(UniversalCapability):
    """Field explicitly accepts null/None.

    Use when a field is semantically nullable independent of
    Python's type annotation (e.g., database column nullability).

    Example:
        @dataclass
        class User:
            middle_name: Annotated[str, Nullable]

    OpenAPI: nullable: true
    SQLAlchemy: nullable=True
    """

    def compile_openapi(self, ctx: "OpenAPIContext") -> "OpenAPIContext":
        return openapi_schema(ctx, nullable=True)

    def compile_sqlalchemy(self, ctx: "SQLAlchemyContext") -> "SQLAlchemyContext":
        return sqlalchemy_column(ctx, nullable=True)


# ═══════════════════════════════════════════════════════════════════════════════
# Naming
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Alias(UniversalCapability):
    """Alternative name for serialization, storage, and CLI.

    The Python field name is the canonical name. Alias provides
    the external name used by each target.

    Example:
        @dataclass
        class Event:
            event_type: Annotated[str, Alias("type")]
            created_at: Annotated[datetime, Alias("createdAt")]

    Pydantic: alias for JSON serialization
    OpenAPI: x-alias hint
    SQLAlchemy: column name
    Argparse: argument name
    """

    name: str

    def compile_pydantic(self, ctx: "PydanticContext") -> "PydanticContext":
        return pydantic_field(ctx, lambda fi: setattr(fi, "alias", self.name))

    def compile_openapi(self, ctx: "OpenAPIContext") -> "OpenAPIContext":
        return openapi_schema(ctx, **{"x-alias": self.name})

    def compile_sqlalchemy(self, ctx: "SQLAlchemyContext") -> "SQLAlchemyContext":
        return sqlalchemy_column(ctx, name=self.name)

    def compile_argparse(self, ctx: "ArgparseContext") -> "ArgparseContext":
        return replace(ctx, arg_names=(f"--{self.name}",))


# ═══════════════════════════════════════════════════════════════════════════════
# Computed
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Computed(UniversalCapability):
    """Derived/virtual field — value computed at runtime, not settable.

    Implies ReadOnly semantically. The actual computation is
    handled by the runtime/handler layer, not the schema axis.

    Example:
        @dataclass
        class User:
            first_name: Annotated[str, MaxLen(50)]
            last_name: Annotated[str, MaxLen(50)]
            full_name: Annotated[str, Computed]

    OpenAPI: readOnly: true, x-computed: true
    SQLAlchemy: computed marker
    """

    def compile_pydantic(self, ctx: "PydanticContext") -> "PydanticContext":
        return pydantic_extra(ctx, readOnly=True)

    def compile_openapi(self, ctx: "OpenAPIContext") -> "OpenAPIContext":
        return openapi_schema(ctx, readOnly=True, **{"x-computed": True})


__all__ = (
    "SchemaAxisCapability",
    "UniversalCapability",
    # Schema-level (class-level)
    "SchemaCapability",
    "schema_meta",
    "get_schema_meta",
    "get_schema_capability",
    "SchemaName",
    "SchemaDoc",
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
    "Nested",
    "Embedded",
    "Doc",
    "Deprecated",
    # Access control
    "ReadOnly",
    "WriteOnly",
    "Sensitive",
    "Immutable",
    # Nullability
    "Nullable",
    # Naming
    "Alias",
    # Computed
    "Computed",
)

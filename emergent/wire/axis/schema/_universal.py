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

import types
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, TypeGuard

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
    from collections.abc import Callable

    from pydantic.fields import FieldInfo

    from emergent.wire.axis._capability import (
        # Field-level
        PydanticContext,
        OpenAPIContext,
        ArgparseContext,
        SQLAlchemyContext,
        StorageFieldContext,
        # Schema-level
        PydanticModelContext,
        OpenAPISchemaContext,
        SQLAlchemyTableContext,
        # Constraints
        ConstraintsContext,
    )
    from emergent.wire.verify._length import LengthVerifyCtx
    from emergent.wire.verify._numeric import NumericVerifyCtx
    from emergent.wire.verify._semantics import SemanticsVerifyCtx


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

    def compile_storage_field(self, ctx: "StorageFieldContext") -> "StorageFieldContext":
        return replace(ctx, is_identity=True)

    def compile_verify_semantics(self, ctx: "SemanticsVerifyCtx") -> "SemanticsVerifyCtx":
        return replace(ctx, is_identity=True)


@dataclass(frozen=True, slots=True)
class Unique(UniversalCapability):
    """Unique constraint → SQL UNIQUE."""

    def compile_sqlalchemy(self, ctx: "SQLAlchemyContext") -> "SQLAlchemyContext":
        return sqlalchemy_column(ctx, unique=True)

    def compile_constraints(self, ctx: "ConstraintsContext") -> "ConstraintsContext":
        return replace(ctx, is_unique=True)

    def compile_verify_semantics(self, ctx: "SemanticsVerifyCtx") -> "SemanticsVerifyCtx":
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

    def compile_verify_numeric(self, ctx: "NumericVerifyCtx") -> "NumericVerifyCtx":
        return replace(ctx, lower_bound=float(self.value))


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

    def compile_verify_numeric(self, ctx: "NumericVerifyCtx") -> "NumericVerifyCtx":
        return replace(ctx, upper_bound=float(self.value))


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

    def compile_verify_numeric(self, ctx: "NumericVerifyCtx") -> "NumericVerifyCtx":
        return replace(ctx, exclusive_lower=float(self.value))


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

    def compile_verify_numeric(self, ctx: "NumericVerifyCtx") -> "NumericVerifyCtx":
        return replace(ctx, exclusive_upper=float(self.value))


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

    def compile_verify_numeric(self, ctx: "NumericVerifyCtx") -> "NumericVerifyCtx":
        return replace(ctx, multiple_of=float(self.value))


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

    def compile_verify_length(self, ctx: "LengthVerifyCtx") -> "LengthVerifyCtx":
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

    def compile_sqlalchemy(self, ctx: "SQLAlchemyContext") -> "SQLAlchemyContext":
        """Refine str column: Text → String(n)."""
        if ctx.field_type is str:
            from sqlalchemy import String

            return replace(ctx, column_type=String(self.value))
        return ctx

    def compile_verify_length(self, ctx: "LengthVerifyCtx") -> "LengthVerifyCtx":
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

    def compile_verify_length(self, ctx: "LengthVerifyCtx") -> "LengthVerifyCtx":
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

    def compile_verify_semantics(self, ctx: "SemanticsVerifyCtx") -> "SemanticsVerifyCtx":
        return replace(ctx, is_read_only=True)


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

    def compile_verify_semantics(self, ctx: "SemanticsVerifyCtx") -> "SemanticsVerifyCtx":
        return replace(ctx, is_write_only=True)


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
        def _mutate(fi: FieldInfo) -> None:
            fi.repr = False
            extra = fi.json_schema_extra
            if isinstance(extra, dict):
                fi.json_schema_extra = {**extra, "writeOnly": True}
            else:
                fi.json_schema_extra = {"writeOnly": True}

        return pydantic_field(ctx, _mutate)

    def compile_openapi(self, ctx: "OpenAPIContext") -> "OpenAPIContext":
        return openapi_schema(ctx, writeOnly=True, format="password")

    def compile_verify_semantics(self, ctx: "SemanticsVerifyCtx") -> "SemanticsVerifyCtx":
        return replace(ctx, is_sensitive=True, is_write_only=True)


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

    def compile_verify_semantics(self, ctx: "SemanticsVerifyCtx") -> "SemanticsVerifyCtx":
        return replace(ctx, is_immutable=True)


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

    def compile_verify_semantics(self, ctx: "SemanticsVerifyCtx") -> "SemanticsVerifyCtx":
        return replace(ctx, is_nullable=True)


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

    def compile_verify_semantics(self, ctx: "SemanticsVerifyCtx") -> "SemanticsVerifyCtx":
        return replace(ctx, is_computed=True)


# ═══════════════════════════════════════════════════════════════════════════════
# Storage Coercion
# ═══════════════════════════════════════════════════════════════════════════════


class _Miss:
    """Sentinel for _extract_attr miss — distinct from any real value including None."""
    __slots__ = ()


_MISS = _Miss()


def _extract_attr(target: type, obj: object, name: str) -> object | _Miss:
    """Extract attribute, checking isinstance first to avoid Unknown propagation.

    When isinstance narrows to e.g. Some[Unknown], accessing .value produces Unknown.
    This helper does isinstance + getattr in one step so the caller never sees the
    narrowed Unknown-parameterized type.

    Returns the attribute value if obj is an instance of target, otherwise _MISS.
    """
    if isinstance(obj, target):
        return getattr(obj, name)
    return _MISS


def _is_tuple(v: object) -> TypeGuard[tuple[object, ...]]:
    """TypeGuard: narrow object to tuple[object, ...] without Unknown propagation."""
    return isinstance(v, tuple)


def _is_list(v: object) -> TypeGuard[list[object]]:
    """TypeGuard: narrow object to list[object] without Unknown propagation."""
    return isinstance(v, list)


def _is_set(v: object) -> TypeGuard[set[object]]:
    """TypeGuard: narrow object to set[object] without Unknown propagation."""
    return isinstance(v, set)


def _is_frozenset(v: object) -> TypeGuard[frozenset[object]]:
    """TypeGuard: narrow object to frozenset[object] without Unknown propagation."""
    return isinstance(v, frozenset)


def _is_dict(v: object) -> TypeGuard[dict[str, object]]:
    """TypeGuard: narrow object to dict[str, object] without Unknown propagation.

    json.loads always produces dict[str, ...] so str keys are guaranteed.
    """
    return isinstance(v, dict)


def _resolve_coerce(
    origin: object,
) -> tuple[
    "Callable[[object], object] | None",
    "Callable[[object], object] | None",
    type | None,
]:
    """Pure dispatch — resolve coercion fns + storage base type for known types.

    Returns (to_storage, from_storage, storage_type) or (None, None, None).
    origin is typed as object because it may be a type, TypeAliasType, or UnionType.
    """
    if origin is tuple:
        def _tuple_to(v: object) -> object:
            return list(v) if _is_tuple(v) else v

        def _tuple_from(v: object) -> object:
            return tuple(v) if _is_list(v) else v

        return (_tuple_to, _tuple_from, list)
    if origin is set:
        def _set_to(v: object) -> object:
            return list(v) if _is_set(v) else v

        def _set_from(v: object) -> object:
            return set(v) if _is_list(v) else v

        return (_set_to, _set_from, list)
    if origin is frozenset:
        def _frozenset_to(v: object) -> object:
            return list(v) if _is_frozenset(v) else v

        def _frozenset_from(v: object) -> object:
            return frozenset(v) if _is_list(v) else v

        return (_frozenset_to, _frozenset_from, list)

    from kungfu import Option, Some, Nothing
    if origin is Option:
        def _to(v: object) -> object:
            # _extract_attr avoids Unknown from isinstance narrowing on erased generics
            val = _extract_attr(Some, v, "value")
            if not isinstance(val, _Miss):
                return val
            if isinstance(v, Nothing):
                return None
            return v

        def _from(v: object) -> object:
            return Nothing() if v is None else Some(v)

        return (_to, _from, None)  # storage_type resolved in __init__ from source args

    from kungfu import Sum
    if origin is Sum:
        import json

        def _sum_to(v: object) -> object:
            # _extract_attr avoids Unknown from isinstance narrowing on erased generics
            raw = _extract_attr(Sum, v, "v")
            if not isinstance(raw, _Miss):
                return json.dumps({"_t": type(raw).__name__, "_v": raw})
            return v

        def _sum_from(v: object) -> object:
            # Generic fallback — Coerce.__init__ overrides with Sum-aware version
            parsed: object = json.loads(v) if isinstance(v, str) else v
            if _is_dict(parsed):
                return parsed["_v"] if "_v" in parsed else parsed
            return parsed

        return (_sum_to, _sum_from, str)  # stored as JSON text

    # Result[T, E] = Ok[T] | Error[E] — type alias, not a class.
    # Coerce(Result) → origin is the TypeAliasType.
    # Coerce(Result[int, str]) → alias expands to Ok[int] | Error[str] (UnionType).
    from kungfu import Result, Ok, Error

    _is_result = origin is Result
    if not _is_result:
        if isinstance(origin, types.UnionType):
            union_args: tuple[object, ...] = origin.__args__
            _origins = {getattr(a, "__origin__", a) for a in union_args}
            _is_result = _origins == {Ok, Error}

    if _is_result:
        import json

        def _result_to(v: object) -> object:
            # _extract_attr avoids Unknown from isinstance narrowing on erased generics
            ok_val = _extract_attr(Ok, v, "value")
            if not isinstance(ok_val, _Miss):
                return json.dumps({"ok": True, "v": ok_val})
            err_val = _extract_attr(Error, v, "error")
            if not isinstance(err_val, _Miss):
                return json.dumps({"ok": False, "e": err_val})
            return v

        def _result_from(v: object) -> object:
            parsed: object = json.loads(v) if isinstance(v, str) else v
            if _is_dict(parsed):
                ok_flag = parsed.get("ok")
                if ok_flag:
                    v_val: object = parsed["v"]
                    return Ok(v_val)
                e_val: object = parsed["e"]
                return Error(e_val)
            return v

        return (_result_to, _result_from, str)  # stored as JSON text

    return (None, None, None)


@dataclass(frozen=True, slots=True)
class Coerce(UniversalCapability):
    """Storage coercion — self-contained fold participant.

    Resolves to/from functions + storage base type at construction.
    Backend reads folded StorageFieldContext — never touches Coerce directly.

    Usage:
        email: Annotated[Option[str], Nullable, Coerce(Option[str])]
        tags: Annotated[tuple[str, ...], Coerce(tuple)]
        custom: Annotated[X, Coerce(X, to_storage=my_to, from_storage=my_from)]

    Extension (open-world via fold):
        @dataclass(frozen=True, slots=True)
        class MyCoerce(UniversalCapability):
            def compile_storage_field(self, ctx: StorageFieldContext) -> StorageFieldContext:
                return replace(ctx, to_storage=..., from_storage=..., storage_type=...)
    """

    to_storage: "Callable[[object], object]"
    from_storage: "Callable[[object], object]"
    storage_type: type | None

    def __init__(
        self,
        source: type,
        *,
        to_storage: "Callable[[object], object] | None" = None,
        from_storage: "Callable[[object], object] | None" = None,
    ) -> None:
        origin: object = getattr(source, "__origin__", source)
        default_to, default_from, default_storage = _resolve_coerce(origin)

        resolved_to = to_storage if to_storage is not None else default_to
        resolved_from = from_storage if from_storage is not None else default_from

        if resolved_to is None or resolved_from is None:
            raise TypeError(
                f"No built-in coercion for {source!r}. "
                "Provide to_storage= and from_storage= overrides, "
                "or create a custom capability implementing compile_storage_field."
            )

        # Resolve storage_type: for Option[str] → str (from __args__)
        storage = default_storage
        source_args: tuple[type, ...] = getattr(source, "__args__", ())
        if storage is None and source_args:
            from kungfu import Option
            if origin is Option:
                storage = source_args[0]

        # Sum-aware from_storage: reconstruct Sum[*Ts] with type discrimination
        from kungfu import Sum
        if origin is Sum:
            sum_args: tuple[type, ...] = getattr(source, "__args__", ())
            type_lookup: dict[str, type] = {t.__name__: t for t in sum_args}
            sum_source = source

            def _sum_from_typed(v: object) -> object:
                import json
                parsed: object = json.loads(v) if isinstance(v, str) else v
                if _is_dict(parsed) and "_t" in parsed:
                    raw: object = parsed["_v"]
                    tag: object = parsed["_t"]
                    t = type_lookup.get(tag) if isinstance(tag, str) else None
                    if t is not None:
                        raw = t(raw)
                    return sum_source(raw)
                return v

            resolved_from = _sum_from_typed
            storage = str

        object.__setattr__(self, "to_storage", resolved_to)
        object.__setattr__(self, "from_storage", resolved_from)
        object.__setattr__(self, "storage_type", storage)

    def compile_storage_field(self, ctx: "StorageFieldContext") -> "StorageFieldContext":
        return replace(
            ctx,
            to_storage=self.to_storage,
            from_storage=self.from_storage,
            storage_type=self.storage_type,
        )

    def compile_sqlalchemy(self, ctx: "SQLAlchemyContext") -> "SQLAlchemyContext":
        """Remap column_type using type_map from context."""
        if self.storage_type is not None:
            col_type = ctx.type_map.get(self.storage_type, ctx.column_type)
            return replace(ctx, column_type=col_type)
        return ctx


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
    # Coercion
    "Coerce",
)

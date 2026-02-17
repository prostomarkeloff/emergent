"""Extended tests for emergent/wire/axis/schema/_universal.py — coverage gaps.

Covers missed compile_* methods on capabilities:
- SchemaName: compile_pydantic_model, compile_openapi_schema, compile_sqlalchemy_table
- SchemaDoc: compile_pydantic_model, compile_openapi_schema
- Abstract: compile_pydantic_model, compile_sqlalchemy_table
- Identity: compile_sqlalchemy, compile_constraints
- Unique: compile_sqlalchemy, compile_constraints
- Ref: compile_sqlalchemy with string target and type target
- Min/Max/ExclusiveMin/ExclusiveMax/MultipleOf: compile_pydantic, compile_openapi, compile_constraints
- MinLen/MaxLen: compile_pydantic, compile_openapi, compile_constraints
- Pattern: compile_pydantic, compile_openapi, compile_constraints
- OneOf: compile_openapi, compile_argparse, compile_constraints
- Nested/Embedded: compile_openapi
- Doc: compile_pydantic, compile_openapi, compile_argparse
- Deprecated: compile_pydantic, compile_openapi
- ReadOnly/WriteOnly: compile_pydantic, compile_openapi
- Sensitive: compile_pydantic, compile_openapi
- Immutable: compile_openapi
- Nullable: compile_openapi, compile_sqlalchemy
- Alias: compile_pydantic, compile_openapi, compile_sqlalchemy, compile_argparse
- Computed: compile_pydantic, compile_openapi
"""

from __future__ import annotations

from pydantic.fields import FieldInfo as PydFieldInfo

from emergent.wire.axis._capability import (
    PydanticContext,
    OpenAPIContext,
    ArgparseContext,
    SQLAlchemyContext,
    PydanticModelContext,
    OpenAPISchemaContext,
    SQLAlchemyTableContext,
    ConstraintsContext,
)
from emergent.wire.axis.schema._universal import (
    SchemaName,
    SchemaDoc,
    Abstract,
    Identity,
    Unique,
    Ref,
    Min,
    Max,
    ExclusiveMin,
    ExclusiveMax,
    MultipleOf,
    MinLen,
    MaxLen,
    Pattern,
    OneOf,
    Nested,
    Embedded,
    Doc,
    Deprecated,
    ReadOnly,
    WriteOnly,
    Sensitive,
    Immutable,
    Nullable,
    Alias,
    Computed,
    schema_meta,
    get_schema_meta,
    get_schema_capability,
)


# ============================================================================
# Helpers — context factories
# ============================================================================


def _pydantic_ctx(field_name: str = "test_field") -> PydanticContext:
    fi = PydFieldInfo()
    return PydanticContext(field_name=field_name, field_type=str, field_info=fi)


def _openapi_ctx(field_name: str = "test_field") -> OpenAPIContext:
    return OpenAPIContext(field_name=field_name, field_type=str, schema={})


def _argparse_ctx(field_name: str = "test_field") -> ArgparseContext:
    return ArgparseContext(field_name=field_name, field_type=str)


def _sqlalchemy_ctx(field_name: str = "test_field") -> SQLAlchemyContext:
    return SQLAlchemyContext(field_name=field_name, field_type=str)


def _pydantic_model_ctx(class_name: str = "TestModel") -> PydanticModelContext:
    return PydanticModelContext(class_name=class_name)


def _openapi_schema_ctx(class_name: str = "TestModel") -> OpenAPISchemaContext:
    return OpenAPISchemaContext(class_name=class_name)


def _sqlalchemy_table_ctx(class_name: str = "TestModel") -> SQLAlchemyTableContext:
    return SQLAlchemyTableContext(class_name=class_name)


def _constraints_ctx(field_name: str = "test_field") -> ConstraintsContext:
    return ConstraintsContext(field_name=field_name, field_type=int)


# ============================================================================
# Schema-Level Capabilities
# ============================================================================


class TestSchemaName:
    def test_compile_pydantic_model(self) -> None:
        cap = SchemaName("users")
        ctx = _pydantic_model_ctx()
        result = cap.compile_pydantic_model(ctx)
        assert result.title == "users"

    def test_compile_openapi_schema(self) -> None:
        cap = SchemaName("users")
        ctx = _openapi_schema_ctx()
        result = cap.compile_openapi_schema(ctx)
        assert result.schema["title"] == "users"

    def test_compile_sqlalchemy_table(self) -> None:
        cap = SchemaName("users")
        ctx = _sqlalchemy_table_ctx()
        result = cap.compile_sqlalchemy_table(ctx)
        assert result.table_name == "users"


class TestSchemaDoc:
    def test_compile_pydantic_model(self) -> None:
        cap = SchemaDoc("Describes a user")
        ctx = _pydantic_model_ctx()
        result = cap.compile_pydantic_model(ctx)
        assert result.description == "Describes a user"

    def test_compile_openapi_schema(self) -> None:
        cap = SchemaDoc("Describes a user")
        ctx = _openapi_schema_ctx()
        result = cap.compile_openapi_schema(ctx)
        assert result.schema["description"] == "Describes a user"


class TestAbstract:
    def test_compile_pydantic_model(self) -> None:
        cap = Abstract()
        ctx = _pydantic_model_ctx()
        result = cap.compile_pydantic_model(ctx)
        assert result.is_abstract is True

    def test_compile_sqlalchemy_table(self) -> None:
        cap = Abstract()
        ctx = _sqlalchemy_table_ctx()
        result = cap.compile_sqlalchemy_table(ctx)
        assert result.is_abstract is True


# ============================================================================
# Identity & Uniqueness
# ============================================================================


class TestIdentity:
    def test_compile_sqlalchemy(self) -> None:
        cap = Identity()
        ctx = _sqlalchemy_ctx()
        result = cap.compile_sqlalchemy(ctx)
        assert result.column_kwargs["primary_key"] is True

    def test_compile_constraints(self) -> None:
        cap = Identity()
        ctx = _constraints_ctx()
        result = cap.compile_constraints(ctx)
        assert result.is_identity is True


class TestUnique:
    def test_compile_sqlalchemy(self) -> None:
        cap = Unique()
        ctx = _sqlalchemy_ctx()
        result = cap.compile_sqlalchemy(ctx)
        assert result.column_kwargs["unique"] is True

    def test_compile_constraints(self) -> None:
        cap = Unique()
        ctx = _constraints_ctx()
        result = cap.compile_constraints(ctx)
        assert result.is_unique is True


# ============================================================================
# References
# ============================================================================


class TestRef:
    def test_compile_sqlalchemy_string_target(self) -> None:
        cap = Ref(target="users.id")
        ctx = _sqlalchemy_ctx()
        result = cap.compile_sqlalchemy(ctx)
        assert result.column_kwargs["fk_target"] == "users.id"
        assert result.column_kwargs["fk_ondelete"] == "CASCADE"
        assert result.column_kwargs["fk_onupdate"] == "CASCADE"

    def test_compile_sqlalchemy_type_target_with_tablename(self) -> None:
        class UserModel:
            __tablename__ = "app_users"

        cap = Ref(target=UserModel)
        ctx = _sqlalchemy_ctx()
        result = cap.compile_sqlalchemy(ctx)
        assert result.column_kwargs["fk_target"] == "app_users.id"

    def test_compile_sqlalchemy_type_target_without_tablename(self) -> None:
        class Team:
            pass

        cap = Ref(target=Team)
        ctx = _sqlalchemy_ctx()
        result = cap.compile_sqlalchemy(ctx)
        assert result.column_kwargs["fk_target"] == "team.id"

    def test_custom_on_delete(self) -> None:
        cap = Ref(target="orders.id", on_delete="SET NULL", on_update="NO ACTION")
        ctx = _sqlalchemy_ctx()
        result = cap.compile_sqlalchemy(ctx)
        assert result.column_kwargs["fk_ondelete"] == "SET NULL"
        assert result.column_kwargs["fk_onupdate"] == "NO ACTION"


# ============================================================================
# Numbers
# ============================================================================


class TestMin:
    def test_compile_pydantic(self) -> None:
        cap = Min(value=0)
        ctx = _pydantic_ctx()
        result = cap.compile_pydantic(ctx)
        # Pydantic metadata should have Ge
        metadata_types = [type(m).__name__ for m in result.field_info.metadata]
        assert "Ge" in metadata_types

    def test_compile_openapi(self) -> None:
        cap = Min(value=0)
        ctx = _openapi_ctx()
        result = cap.compile_openapi(ctx)
        assert result.schema["minimum"] == 0

    def test_compile_constraints(self) -> None:
        cap = Min(value=5)
        ctx = _constraints_ctx()
        result = cap.compile_constraints(ctx)
        assert result.min_value == 5


class TestMax:
    def test_compile_pydantic(self) -> None:
        cap = Max(value=100)
        ctx = _pydantic_ctx()
        result = cap.compile_pydantic(ctx)
        metadata_types = [type(m).__name__ for m in result.field_info.metadata]
        assert "Le" in metadata_types

    def test_compile_openapi(self) -> None:
        cap = Max(value=100)
        ctx = _openapi_ctx()
        result = cap.compile_openapi(ctx)
        assert result.schema["maximum"] == 100

    def test_compile_constraints(self) -> None:
        cap = Max(value=100)
        ctx = _constraints_ctx()
        result = cap.compile_constraints(ctx)
        assert result.max_value == 100


class TestExclusiveMin:
    def test_compile_pydantic(self) -> None:
        cap = ExclusiveMin(value=0)
        ctx = _pydantic_ctx()
        result = cap.compile_pydantic(ctx)
        metadata_types = [type(m).__name__ for m in result.field_info.metadata]
        assert "Gt" in metadata_types

    def test_compile_openapi(self) -> None:
        cap = ExclusiveMin(value=0)
        ctx = _openapi_ctx()
        result = cap.compile_openapi(ctx)
        assert result.schema["exclusiveMinimum"] == 0

    def test_compile_constraints(self) -> None:
        cap = ExclusiveMin(value=3)
        ctx = _constraints_ctx()
        result = cap.compile_constraints(ctx)
        assert result.exclusive_min == 3


class TestExclusiveMax:
    def test_compile_pydantic(self) -> None:
        cap = ExclusiveMax(value=99)
        ctx = _pydantic_ctx()
        result = cap.compile_pydantic(ctx)
        metadata_types = [type(m).__name__ for m in result.field_info.metadata]
        assert "Lt" in metadata_types

    def test_compile_openapi(self) -> None:
        cap = ExclusiveMax(value=99)
        ctx = _openapi_ctx()
        result = cap.compile_openapi(ctx)
        assert result.schema["exclusiveMaximum"] == 99

    def test_compile_constraints(self) -> None:
        cap = ExclusiveMax(value=99)
        ctx = _constraints_ctx()
        result = cap.compile_constraints(ctx)
        assert result.exclusive_max == 99


class TestMultipleOf:
    def test_compile_pydantic(self) -> None:
        cap = MultipleOf(value=5)
        ctx = _pydantic_ctx()
        result = cap.compile_pydantic(ctx)
        metadata_types = [type(m).__name__ for m in result.field_info.metadata]
        assert "MultipleOf" in metadata_types

    def test_compile_openapi(self) -> None:
        cap = MultipleOf(value=5)
        ctx = _openapi_ctx()
        result = cap.compile_openapi(ctx)
        assert result.schema["multipleOf"] == 5

    def test_compile_constraints(self) -> None:
        cap = MultipleOf(value=5)
        ctx = _constraints_ctx()
        result = cap.compile_constraints(ctx)
        assert result.multiple_of == 5


# ============================================================================
# Strings / Collections
# ============================================================================


class TestMinLen:
    def test_compile_pydantic(self) -> None:
        cap = MinLen(value=3)
        ctx = _pydantic_ctx()
        result = cap.compile_pydantic(ctx)
        metadata_types = [type(m).__name__ for m in result.field_info.metadata]
        assert "MinLen" in metadata_types

    def test_compile_openapi(self) -> None:
        cap = MinLen(value=3)
        ctx = _openapi_ctx()
        result = cap.compile_openapi(ctx)
        assert result.schema["minLength"] == 3

    def test_compile_constraints(self) -> None:
        cap = MinLen(value=3)
        ctx = _constraints_ctx()
        result = cap.compile_constraints(ctx)
        assert result.min_length == 3


class TestMaxLen:
    def test_compile_pydantic(self) -> None:
        cap = MaxLen(value=255)
        ctx = _pydantic_ctx()
        result = cap.compile_pydantic(ctx)
        metadata_types = [type(m).__name__ for m in result.field_info.metadata]
        assert "MaxLen" in metadata_types

    def test_compile_openapi(self) -> None:
        cap = MaxLen(value=255)
        ctx = _openapi_ctx()
        result = cap.compile_openapi(ctx)
        assert result.schema["maxLength"] == 255

    def test_compile_constraints(self) -> None:
        cap = MaxLen(value=255)
        ctx = _constraints_ctx()
        result = cap.compile_constraints(ctx)
        assert result.max_length == 255


class TestPattern:
    def test_compile_pydantic(self) -> None:
        cap = Pattern(regex=r"^\w+$")
        ctx = _pydantic_ctx()
        result = cap.compile_pydantic(ctx)
        # Pattern compiles via pydantic_field with FieldInfo
        assert result.field_info is not ctx.field_info

    def test_compile_openapi(self) -> None:
        cap = Pattern(regex=r"^\w+$")
        ctx = _openapi_ctx()
        result = cap.compile_openapi(ctx)
        assert result.schema["pattern"] == r"^\w+$"

    def test_compile_constraints(self) -> None:
        cap = Pattern(regex=r"^\d{3}$")
        ctx = _constraints_ctx()
        result = cap.compile_constraints(ctx)
        assert result.pattern == r"^\d{3}$"


# ============================================================================
# Enums & Unions
# ============================================================================


class TestOneOf:
    def test_compile_openapi(self) -> None:
        cap = OneOf("a", "b", "c")
        ctx = _openapi_ctx()
        result = cap.compile_openapi(ctx)
        assert result.schema["enum"] == ["a", "b", "c"]

    def test_compile_argparse(self) -> None:
        cap = OneOf("x", "y")
        ctx = _argparse_ctx()
        result = cap.compile_argparse(ctx)
        assert result.kwargs["choices"] == ["x", "y"]

    def test_compile_constraints(self) -> None:
        cap = OneOf(1, 2, 3)
        ctx = _constraints_ctx()
        result = cap.compile_constraints(ctx)
        assert result.choices == (1, 2, 3)

    def test_init_stores_values_as_tuple(self) -> None:
        cap = OneOf("a", "b", "c")
        assert cap.values == ("a", "b", "c")


class TestNested:
    def test_compile_openapi(self) -> None:
        cap = Nested()
        ctx = _openapi_ctx()
        result = cap.compile_openapi(ctx)
        assert result.schema["x-nested"] is True
        assert result.schema["x-cascade"] == "all"

    def test_compile_openapi_custom_cascade(self) -> None:
        cap = Nested(cascade="delete")
        ctx = _openapi_ctx()
        result = cap.compile_openapi(ctx)
        assert result.schema["x-cascade"] == "delete"


class TestEmbedded:
    def test_compile_openapi(self) -> None:
        cap = Embedded()
        ctx = _openapi_ctx()
        result = cap.compile_openapi(ctx)
        assert result.schema["x-embedded"] is True
        assert result.schema["x-format"] == "json"

    def test_compile_openapi_flatten(self) -> None:
        cap = Embedded(format="flatten")
        ctx = _openapi_ctx()
        result = cap.compile_openapi(ctx)
        assert result.schema["x-format"] == "flatten"


# ============================================================================
# Documentation
# ============================================================================


class TestDoc:
    def test_compile_pydantic(self) -> None:
        cap = Doc(text="Help text")
        ctx = _pydantic_ctx()
        result = cap.compile_pydantic(ctx)
        assert result.field_info.description == "Help text"

    def test_compile_openapi(self) -> None:
        cap = Doc(text="Description")
        ctx = _openapi_ctx()
        result = cap.compile_openapi(ctx)
        assert result.schema["description"] == "Description"

    def test_compile_argparse(self) -> None:
        cap = Doc(text="CLI help")
        ctx = _argparse_ctx()
        result = cap.compile_argparse(ctx)
        assert result.kwargs["help"] == "CLI help"


class TestDeprecated:
    def test_compile_pydantic_with_reason(self) -> None:
        cap = Deprecated(reason="Use v2")
        ctx = _pydantic_ctx()
        result = cap.compile_pydantic(ctx)
        assert result.field_info.deprecated == "Use v2"

    def test_compile_pydantic_without_reason(self) -> None:
        cap = Deprecated()
        ctx = _pydantic_ctx()
        result = cap.compile_pydantic(ctx)
        assert result.field_info.deprecated is True

    def test_compile_openapi(self) -> None:
        cap = Deprecated(reason="Old")
        ctx = _openapi_ctx()
        result = cap.compile_openapi(ctx)
        assert result.schema["deprecated"] is True


# ============================================================================
# Access Control
# ============================================================================


class TestReadOnly:
    def test_compile_pydantic(self) -> None:
        cap = ReadOnly()
        ctx = _pydantic_ctx()
        result = cap.compile_pydantic(ctx)
        extra = result.field_info.json_schema_extra
        assert isinstance(extra, dict)
        assert extra["readOnly"] is True

    def test_compile_openapi(self) -> None:
        cap = ReadOnly()
        ctx = _openapi_ctx()
        result = cap.compile_openapi(ctx)
        assert result.schema["readOnly"] is True


class TestWriteOnly:
    def test_compile_pydantic(self) -> None:
        cap = WriteOnly()
        ctx = _pydantic_ctx()
        result = cap.compile_pydantic(ctx)
        extra = result.field_info.json_schema_extra
        assert isinstance(extra, dict)
        assert extra["writeOnly"] is True

    def test_compile_openapi(self) -> None:
        cap = WriteOnly()
        ctx = _openapi_ctx()
        result = cap.compile_openapi(ctx)
        assert result.schema["writeOnly"] is True


class TestSensitive:
    def test_compile_pydantic(self) -> None:
        cap = Sensitive()
        ctx = _pydantic_ctx()
        result = cap.compile_pydantic(ctx)
        assert result.field_info.repr is False
        extra = result.field_info.json_schema_extra
        assert isinstance(extra, dict)
        assert extra["writeOnly"] is True

    def test_compile_openapi(self) -> None:
        cap = Sensitive()
        ctx = _openapi_ctx()
        result = cap.compile_openapi(ctx)
        assert result.schema["writeOnly"] is True
        assert result.schema["format"] == "password"


class TestImmutable:
    def test_compile_openapi(self) -> None:
        cap = Immutable()
        ctx = _openapi_ctx()
        result = cap.compile_openapi(ctx)
        assert result.schema["x-immutable"] is True


# ============================================================================
# Nullability
# ============================================================================


class TestNullable:
    def test_compile_openapi(self) -> None:
        cap = Nullable()
        ctx = _openapi_ctx()
        result = cap.compile_openapi(ctx)
        assert result.schema["nullable"] is True

    def test_compile_sqlalchemy(self) -> None:
        cap = Nullable()
        ctx = _sqlalchemy_ctx()
        result = cap.compile_sqlalchemy(ctx)
        assert result.column_kwargs["nullable"] is True


# ============================================================================
# Naming
# ============================================================================


class TestAlias:
    def test_compile_pydantic(self) -> None:
        cap = Alias(name="createdAt")
        ctx = _pydantic_ctx()
        result = cap.compile_pydantic(ctx)
        assert result.field_info.alias == "createdAt"

    def test_compile_openapi(self) -> None:
        cap = Alias(name="createdAt")
        ctx = _openapi_ctx()
        result = cap.compile_openapi(ctx)
        assert result.schema["x-alias"] == "createdAt"

    def test_compile_sqlalchemy(self) -> None:
        cap = Alias(name="created_at")
        ctx = _sqlalchemy_ctx()
        result = cap.compile_sqlalchemy(ctx)
        assert result.column_kwargs["name"] == "created_at"

    def test_compile_argparse(self) -> None:
        cap = Alias(name="output-dir")
        ctx = _argparse_ctx()
        result = cap.compile_argparse(ctx)
        assert result.arg_names == ("--output-dir",)


# ============================================================================
# Computed
# ============================================================================


class TestComputed:
    def test_compile_pydantic(self) -> None:
        cap = Computed()
        ctx = _pydantic_ctx()
        result = cap.compile_pydantic(ctx)
        extra = result.field_info.json_schema_extra
        assert isinstance(extra, dict)
        assert extra["readOnly"] is True

    def test_compile_openapi(self) -> None:
        cap = Computed()
        ctx = _openapi_ctx()
        result = cap.compile_openapi(ctx)
        assert result.schema["readOnly"] is True
        assert result.schema["x-computed"] is True


# ============================================================================
# Schema meta utilities
# ============================================================================


class TestSchemaMetaUtils:
    def test_get_schema_meta_empty(self) -> None:
        class Plain:
            pass

        assert get_schema_meta(Plain) == ()

    def test_get_schema_meta_with_caps(self) -> None:
        @schema_meta(SchemaName("items"), SchemaDoc("Item table"))
        class Item:
            pass

        meta = get_schema_meta(Item)
        assert len(meta) == 2
        assert isinstance(meta[0], SchemaName)
        assert isinstance(meta[1], SchemaDoc)

    def test_get_schema_capability_found(self) -> None:
        @schema_meta(SchemaName("items"))
        class Item:
            pass

        cap = get_schema_capability(Item, SchemaName)
        assert cap is not None
        assert isinstance(cap, SchemaName)
        assert cap.value == "items"

    def test_get_schema_capability_not_found(self) -> None:
        @schema_meta(SchemaName("items"))
        class Item:
            pass

        cap = get_schema_capability(Item, SchemaDoc)
        assert cap is None

    def test_schema_meta_stacks(self) -> None:
        """Applying schema_meta multiple times appends capabilities."""
        @schema_meta(SchemaDoc("Second"))
        @schema_meta(SchemaName("items"))
        class Item:
            pass

        meta = get_schema_meta(Item)
        assert len(meta) == 2

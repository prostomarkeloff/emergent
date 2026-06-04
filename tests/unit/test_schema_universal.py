"""Tests for emergent.wire.axis.schema._universal — universal capabilities + schema meta."""

from dataclasses import dataclass, FrozenInstanceError
from typing import Annotated

import pytest

from emergent.wire.axis.schema._universal import (
    # Hierarchy
    SchemaAxisCapability,
    UniversalCapability,
    SchemaCapability,
    # Schema meta
    schema_meta,
    get_schema_meta,
    get_schema_capability,
    # Schema-level
    SchemaName,
    SchemaDoc,
    Abstract,
    # Field-level
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
)
from emergent.wire.axis.schema.dialects.sql import CompositeUnique, CompositeIndex
from emergent.wire.axis.schema.dialects.openapi import Discriminator
from emergent.wire.axis._capability import (
    PydanticContext,
    OpenAPIContext,
    ArgparseContext,
    SQLAlchemyContext,
    SQLAlchemyTableContext,
    SQLAlchemyCompilable,
    PydanticModelContext,
    OpenAPISchemaContext,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Hierarchy
# ═══════════════════════════════════════════════════════════════════════════════


class TestHierarchy:
    def test_universal_is_schema_axis(self):
        assert issubclass(UniversalCapability, SchemaAxisCapability)

    def test_schema_capability_is_schema_axis(self):
        assert issubclass(SchemaCapability, SchemaAxisCapability)

    def test_identity_is_universal(self):
        assert issubclass(Identity, UniversalCapability)
        assert isinstance(Identity(), UniversalCapability)

    def test_schema_name_is_schema_capability(self):
        assert issubclass(SchemaName, SchemaCapability)


# ═══════════════════════════════════════════════════════════════════════════════
# Schema Meta
# ═══════════════════════════════════════════════════════════════════════════════


class TestSchemaMeta:
    def test_schema_meta_decorator(self):
        @schema_meta(SchemaName("users"))
        @dataclass
        class User:
            id: int

        caps = get_schema_meta(User)
        assert len(caps) == 1
        assert isinstance(caps[0], SchemaName)
        assert caps[0].value == "users"

    def test_schema_meta_multiple(self):
        @schema_meta(SchemaName("users"), SchemaDoc("The users table"))
        @dataclass
        class User:
            id: int

        caps = get_schema_meta(User)
        assert len(caps) == 2

    def test_schema_meta_stacking(self):
        @schema_meta(SchemaDoc("Extra"))
        @schema_meta(SchemaName("users"))
        @dataclass
        class User:
            id: int

        caps = get_schema_meta(User)
        assert len(caps) == 2

    def test_get_schema_meta_no_meta(self):
        @dataclass
        class Plain:
            id: int

        assert get_schema_meta(Plain) == ()

    def test_get_schema_capability(self) -> None:
        @schema_meta(SchemaName("users"), SchemaDoc("desc"))
        @dataclass
        class User:
            id: int

        name = get_schema_capability(User, SchemaName)
        assert name is not None
        assert isinstance(name, SchemaName)
        assert name.value == "users"

        abstract = get_schema_capability(User, Abstract)
        assert abstract is None


# ═══════════════════════════════════════════════════════════════════════════════
# Schema-Level Capabilities
# ═══════════════════════════════════════════════════════════════════════════════


class TestSchemaName:
    def test_frozen(self):
        sn = SchemaName("users")
        with pytest.raises((FrozenInstanceError, AttributeError)):
            sn.value = "other"  # type: ignore[misc]

    def test_compile_pydantic_model(self):
        sn = SchemaName("UserAccount")
        ctx = PydanticModelContext(class_name="User")
        result = sn.compile_pydantic_model(ctx)
        assert result.title == "UserAccount"

    def test_compile_openapi_schema(self):
        sn = SchemaName("UserAccount")
        ctx = OpenAPISchemaContext(class_name="User")
        result = sn.compile_openapi_schema(ctx)
        assert result.schema["title"] == "UserAccount"

    def test_compile_sqlalchemy_table(self):
        sn = SchemaName("user_accounts")
        ctx = SQLAlchemyTableContext(class_name="User")
        result = sn.compile_sqlalchemy_table(ctx)
        assert result.table_name == "user_accounts"


class TestSchemaDoc:
    def test_compile_pydantic_model(self):
        sd = SchemaDoc("A user entity")
        ctx = PydanticModelContext(class_name="User")
        result = sd.compile_pydantic_model(ctx)
        assert result.description == "A user entity"

    def test_compile_openapi_schema(self):
        sd = SchemaDoc("A user entity")
        ctx = OpenAPISchemaContext(class_name="User")
        result = sd.compile_openapi_schema(ctx)
        assert result.schema["description"] == "A user entity"


class TestCompositeUnique:
    def test_varargs_init(self):
        cu = CompositeUnique("email", "tenant_id")
        assert cu.fields == ("email", "tenant_id")
        assert cu.name is None

    def test_named(self):
        cu = CompositeUnique("a", "b", name="uq_ab")
        assert cu.name == "uq_ab"

    def test_compile_sqlalchemy_table(self):
        cu = CompositeUnique("email", "org_id")
        ctx = SQLAlchemyTableContext(class_name="User")
        result = cu.compile_sqlalchemy_table(ctx)
        assert len(result.constraints) == 1
        assert result.constraints[0].fields == ("email", "org_id")


class TestCompositeIndex:
    def test_varargs_init(self):
        ci = CompositeIndex("status", "created_at")
        assert ci.fields == ("status", "created_at")
        assert ci.unique is False

    def test_unique_index(self):
        ci = CompositeIndex("a", "b", unique=True)
        assert ci.unique is True

    def test_compile_sqlalchemy_table(self):
        ci = CompositeIndex("status", "created_at")
        ctx = SQLAlchemyTableContext(class_name="Order")
        result = ci.compile_sqlalchemy_table(ctx)
        assert len(result.indexes) == 1
        assert result.indexes[0].fields == ("status", "created_at")
        assert result.indexes[0].unique is False


class TestDiscriminator:
    def test_basic(self):
        class Dog:
            pass

        class Cat:
            pass

        d = Discriminator(field="type", mapping={"dog": Dog, "cat": Cat})
        assert d.field == "type"

    def test_compile_openapi_schema(self) -> None:
        class Dog:
            pass

        d = Discriminator(field="type", mapping={"dog": Dog})
        ctx = OpenAPISchemaContext(class_name="Pet")
        result = d.compile_openapi_schema(ctx)
        disc = result.schema["discriminator"]
        assert isinstance(disc, dict)
        assert disc["propertyName"] == "type"
        mapping = disc["mapping"]
        assert isinstance(mapping, dict)
        assert mapping["dog"] == "Dog"


class TestAbstract:
    def test_compile_pydantic_model(self):
        a = Abstract()
        ctx = PydanticModelContext(class_name="Base")
        result = a.compile_pydantic_model(ctx)
        assert result.is_abstract is True

    def test_compile_sqlalchemy_table(self):
        a = Abstract()
        ctx = SQLAlchemyTableContext(class_name="Base")
        result = a.compile_sqlalchemy_table(ctx)
        assert result.is_abstract is True


# ═══════════════════════════════════════════════════════════════════════════════
# Field-Level Capabilities — Identity & Uniqueness
# ═══════════════════════════════════════════════════════════════════════════════


class TestIdentity:
    def test_instance_and_class_forms(self):
        assert isinstance(Identity(), Identity)
        assert isinstance(Identity, type)

    def test_compile_sqlalchemy(self):
        cap = Identity()
        ctx = SQLAlchemyContext(field_name="id", field_type=int)
        result = cap.compile_sqlalchemy(ctx)
        assert result.column_kwargs["primary_key"] is True


class TestUnique:
    def test_compile_sqlalchemy(self):
        cap = Unique()
        ctx = SQLAlchemyContext(field_name="email", field_type=str)
        result = cap.compile_sqlalchemy(ctx)
        assert result.column_kwargs["unique"] is True


# ═══════════════════════════════════════════════════════════════════════════════
# Field-Level — References
# ═══════════════════════════════════════════════════════════════════════════════


class TestRef:
    def test_default_cascade(self):
        ref = Ref(target="Team")
        assert ref.on_delete == "CASCADE"
        assert ref.on_update == "CASCADE"

    def test_custom_cascade(self):
        ref = Ref(target="Team", on_delete="SET NULL")
        assert ref.on_delete == "SET NULL"

    def test_compile_sqlalchemy(self):
        class Team:
            __tablename__ = "teams"

        ref = Ref(target=Team, on_delete="SET NULL", on_update="CASCADE")
        ctx = SQLAlchemyContext(field_name="team_id", field_type=int)
        result = ref.compile_sqlalchemy(ctx)
        assert result.column_kwargs["fk_target"] == "teams.id"
        assert result.column_kwargs["fk_ondelete"] == "SET NULL"
        assert result.column_kwargs["fk_onupdate"] == "CASCADE"

    def test_compile_sqlalchemy_string_target(self):
        ref = Ref(target="teams.id")
        ctx = SQLAlchemyContext(field_name="team_id", field_type=int)
        result = ref.compile_sqlalchemy(ctx)
        assert result.column_kwargs["fk_target"] == "teams.id"

    def test_resolve_fk_target_with_tablename(self) -> None:
        class Order:
            __tablename__ = "orders"

        ref = Ref(target=Order)
        # Testing private API deliberately
        assert ref._resolve_fk_target() == "orders.id"  # pyright: ignore[reportPrivateUsage]

    def test_resolve_fk_target_fallback(self) -> None:
        class User:
            pass

        ref = Ref(target=User)
        # Testing private API deliberately
        assert ref._resolve_fk_target() == "user.id"  # pyright: ignore[reportPrivateUsage]

    def test_protocol_compliance(self):
        ref = Ref(target="teams.id")
        assert isinstance(ref, SQLAlchemyCompilable)


# ═══════════════════════════════════════════════════════════════════════════════
# Field-Level — Numerics
# ═══════════════════════════════════════════════════════════════════════════════


class TestNumericCapabilities:
    def test_min_compile_openapi(self):
        cap = Min(0)
        ctx = OpenAPIContext(field_name="age", field_type=int)
        result = cap.compile_openapi(ctx)
        assert result.schema["minimum"] == 0

    def test_max_compile_openapi(self):
        cap = Max(100)
        ctx = OpenAPIContext(field_name="score", field_type=int)
        result = cap.compile_openapi(ctx)
        assert result.schema["maximum"] == 100

    def test_exclusive_min_compile_openapi(self):
        cap = ExclusiveMin(0)
        ctx = OpenAPIContext(field_name="price", field_type=float)
        result = cap.compile_openapi(ctx)
        assert result.schema["exclusiveMinimum"] == 0

    def test_exclusive_max_compile_openapi(self):
        cap = ExclusiveMax(1000)
        ctx = OpenAPIContext(field_name="price", field_type=float)
        result = cap.compile_openapi(ctx)
        assert result.schema["exclusiveMaximum"] == 1000

    def test_multiple_of_compile_openapi(self):
        cap = MultipleOf(5)
        ctx = OpenAPIContext(field_name="quantity", field_type=int)
        result = cap.compile_openapi(ctx)
        assert result.schema["multipleOf"] == 5

    def test_min_compile_pydantic(self):
        from pydantic.fields import FieldInfo as PydFieldInfo

        cap = Min(0)
        fi = PydFieldInfo(annotation=int)
        ctx = PydanticContext(field_name="age", field_type=int, field_info=fi)
        result = cap.compile_pydantic(ctx)
        assert len(result.field_info.metadata) > 0


# ═══════════════════════════════════════════════════════════════════════════════
# Field-Level — Strings/Collections
# ═══════════════════════════════════════════════════════════════════════════════


class TestStringCapabilities:
    def test_minlen_compile_openapi(self):
        cap = MinLen(3)
        ctx = OpenAPIContext(field_name="name", field_type=str)
        result = cap.compile_openapi(ctx)
        assert result.schema["minLength"] == 3

    def test_maxlen_compile_openapi(self):
        cap = MaxLen(255)
        ctx = OpenAPIContext(field_name="email", field_type=str)
        result = cap.compile_openapi(ctx)
        assert result.schema["maxLength"] == 255

    def test_pattern_compile_openapi(self):
        cap = Pattern(r"^[a-z]+$")
        ctx = OpenAPIContext(field_name="slug", field_type=str)
        result = cap.compile_openapi(ctx)
        assert result.schema["pattern"] == r"^[a-z]+$"


# ═══════════════════════════════════════════════════════════════════════════════
# Field-Level — Enums & Unions
# ═══════════════════════════════════════════════════════════════════════════════


class TestOneOf:
    def test_varargs(self):
        cap = OneOf("a", "b", "c")
        assert cap.values == ("a", "b", "c")

    def test_compile_openapi(self):
        cap = OneOf("draft", "published", "archived")
        ctx = OpenAPIContext(field_name="status", field_type=str)
        result = cap.compile_openapi(ctx)
        assert result.schema["enum"] == ["draft", "published", "archived"]

    def test_compile_argparse(self):
        cap = OneOf("json", "yaml")
        ctx = ArgparseContext(field_name="format", field_type=str)
        result = cap.compile_argparse(ctx)
        assert result.kwargs["choices"] == ["json", "yaml"]


class TestNested:
    def test_defaults(self):
        n = Nested()
        assert n.cascade == "all"
        assert n.meta == ()

    def test_with_meta(self):
        n = Nested(meta=(SchemaName("items"),))
        assert len(n.meta) == 1

    def test_compile_openapi(self):
        n = Nested()
        ctx = OpenAPIContext(field_name="items", field_type=list)
        result = n.compile_openapi(ctx)
        assert result.schema["x-nested"] is True


class TestEmbedded:
    def test_defaults(self):
        e = Embedded()
        assert e.format == "json"
        assert e.meta == ()


# ═══════════════════════════════════════════════════════════════════════════════
# Field-Level — Documentation
# ═══════════════════════════════════════════════════════════════════════════════


class TestDoc:
    def test_compile_openapi(self):
        cap = Doc("User email address")
        ctx = OpenAPIContext(field_name="email", field_type=str)
        result = cap.compile_openapi(ctx)
        assert result.schema["description"] == "User email address"

    def test_compile_argparse(self):
        cap = Doc("Username to register")
        ctx = ArgparseContext(field_name="login", field_type=str)
        result = cap.compile_argparse(ctx)
        assert result.kwargs["help"] == "Username to register"


class TestDeprecated:
    def test_no_reason(self):
        d = Deprecated()
        assert d.reason is None

    def test_with_reason(self):
        d = Deprecated(reason="Use email instead")
        assert d.reason == "Use email instead"

    def test_compile_openapi(self):
        d = Deprecated()
        ctx = OpenAPIContext(field_name="login", field_type=str)
        result = d.compile_openapi(ctx)
        assert result.schema["deprecated"] is True


# ═══════════════════════════════════════════════════════════════════════════════
# Field-Level — Access Control
# ═══════════════════════════════════════════════════════════════════════════════


class TestAccessControl:
    def test_readonly_openapi(self):
        cap = ReadOnly()
        ctx = OpenAPIContext(field_name="id", field_type=int)
        result = cap.compile_openapi(ctx)
        assert result.schema["readOnly"] is True

    def test_writeonly_openapi(self):
        cap = WriteOnly()
        ctx = OpenAPIContext(field_name="password", field_type=str)
        result = cap.compile_openapi(ctx)
        assert result.schema["writeOnly"] is True

    def test_sensitive_openapi(self):
        cap = Sensitive()
        ctx = OpenAPIContext(field_name="secret", field_type=str)
        result = cap.compile_openapi(ctx)
        assert result.schema["writeOnly"] is True
        assert result.schema["format"] == "password"

    def test_immutable_openapi(self):
        cap = Immutable()
        ctx = OpenAPIContext(field_name="username", field_type=str)
        result = cap.compile_openapi(ctx)
        assert result.schema["x-immutable"] is True


# ═══════════════════════════════════════════════════════════════════════════════
# Field-Level — Nullable, Alias, Computed
# ═══════════════════════════════════════════════════════════════════════════════


class TestNullable:
    def test_compile_openapi(self):
        cap = Nullable()
        ctx = OpenAPIContext(field_name="middle_name", field_type=str)
        result = cap.compile_openapi(ctx)
        assert result.schema["nullable"] is True

    def test_compile_sqlalchemy(self):
        cap = Nullable()
        ctx = SQLAlchemyContext(field_name="middle_name", field_type=str)
        result = cap.compile_sqlalchemy(ctx)
        assert result.column_kwargs["nullable"] is True


class TestAlias:
    def test_compile_openapi(self):
        cap = Alias("type")
        ctx = OpenAPIContext(field_name="event_type", field_type=str)
        result = cap.compile_openapi(ctx)
        assert result.schema["x-alias"] == "type"

    def test_compile_sqlalchemy(self):
        cap = Alias("event_type_col")
        ctx = SQLAlchemyContext(field_name="event_type", field_type=str)
        result = cap.compile_sqlalchemy(ctx)
        assert result.column_kwargs["name"] == "event_type_col"

    def test_compile_argparse(self):
        cap = Alias("type")
        ctx = ArgparseContext(field_name="event_type", field_type=str)
        result = cap.compile_argparse(ctx)
        assert result.arg_names == ("--type",)


class TestComputed:
    def test_compile_openapi(self):
        cap = Computed()
        ctx = OpenAPIContext(field_name="full_name", field_type=str)
        result = cap.compile_openapi(ctx)
        assert result.schema["readOnly"] is True
        assert result.schema["x-computed"] is True


# ═══════════════════════════════════════════════════════════════════════════════
# All capabilities are frozen
# ═══════════════════════════════════════════════════════════════════════════════


class TestFrozenness:
    @pytest.mark.parametrize(
        "cap",
        [
            Identity(),
            Unique(),
            Ref(target="X"),
            Min(0),
            Max(100),
            MinLen(1),
            MaxLen(255),
            Pattern(r"x"),
            OneOf("a"),
            Doc("x"),
            Deprecated(),
            ReadOnly(),
            WriteOnly(),
            Sensitive(),
            Immutable(),
            Nullable(),
            Alias("x"),
            Computed(),
            SchemaName("x"),
            SchemaDoc("x"),
            Abstract(),
        ],
    )
    def test_frozen(self, cap: SchemaAxisCapability) -> None:
        """All capabilities are frozen dataclasses."""
        import dataclasses

        assert dataclasses.is_dataclass(cap)
        # __dataclass_params__ is an internal CPython attr not in type stubs;
        # its type and members are unknown to pyright
        params = type(cap).__dataclass_params__  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType, reportUnknownVariableType]
        assert params.frozen is True  # pyright: ignore[reportUnknownMemberType]


# ═══════════════════════════════════════════════════════════════════════════════
# Integration: Multi-target capability compilation pipeline
# ═══════════════════════════════════════════════════════════════════════════════


class TestIntegrationMultiTargetCompilation:
    """Compile the same entity's capabilities across multiple targets
    (OpenAPI, SQLAlchemy, Pydantic, Argparse) and verify consistency."""

    def test_identity_compiles_across_targets(self):
        """Identity → PK in SQL, nothing special in OpenAPI."""
        cap = Identity()
        sql_ctx = SQLAlchemyContext(field_name="id", field_type=int)
        sql_result = cap.compile_sqlalchemy(sql_ctx)
        assert sql_result.column_kwargs["primary_key"] is True

    def test_field_capabilities_compile_to_all_targets(self) -> None:
        """A fully-annotated field compiles correctly to all targets."""
        from emergent.wire.compile._core import fold_field
        from emergent.wire.axis.schema._inspect import inspect_type

        @dataclass
        class Product:
            id: Annotated[int, Identity]
            name: Annotated[str, MaxLen(100), MinLen(1), Doc("Product name")]
            price: Annotated[float, Min(0), Max(10000)]
            status: Annotated[str, OneOf("draft", "active", "archived")]

        fields = inspect_type(Product)

        from emergent.wire.axis._capability import OpenAPICompilable, ArgparseCompilable

        # OpenAPI compilation
        name_openapi = fold_field(
            fields["name"],
            OpenAPIContext(field_name="name", field_type=str),
            OpenAPICompilable,
            "compile_openapi",
        )
        assert name_openapi.schema["maxLength"] == 100
        assert name_openapi.schema["minLength"] == 1
        assert name_openapi.schema["description"] == "Product name"

        price_openapi = fold_field(
            fields["price"],
            OpenAPIContext(field_name="price", field_type=float),
            OpenAPICompilable,
            "compile_openapi",
        )
        assert price_openapi.schema["minimum"] == 0
        assert price_openapi.schema["maximum"] == 10000

        status_openapi = fold_field(
            fields["status"],
            OpenAPIContext(field_name="status", field_type=str),
            OpenAPICompilable,
            "compile_openapi",
        )
        assert status_openapi.schema["enum"] == ["draft", "active", "archived"]

        # SQL compilation
        id_sql = fold_field(
            fields["id"],
            SQLAlchemyContext(field_name="id", field_type=int),
            SQLAlchemyCompilable,
            "compile_sqlalchemy",
        )
        assert id_sql.column_kwargs["primary_key"] is True

        # Argparse compilation
        status_argparse = fold_field(
            fields["status"],
            ArgparseContext(field_name="status", field_type=str),
            ArgparseCompilable,
            "compile_argparse",
        )
        assert status_argparse.kwargs["choices"] == ["draft", "active", "archived"]


class TestIntegrationSchemaMetaComposition:
    """Schema-level capabilities compose across targets and stacking."""

    def test_schema_meta_stacked_and_compiled(self) -> None:
        """Stacked schema_meta compiles to SQL table + Pydantic model + OpenAPI schema."""
        @schema_meta(SchemaDoc("User account entity"))
        @schema_meta(SchemaName("user_accounts"))
        @dataclass
        class User:
            id: Annotated[int, Identity]
            email: Annotated[str, Unique, MaxLen(255)]

        caps = get_schema_meta(User)
        assert len(caps) == 2

        # Get SchemaName and SchemaDoc — narrow from SchemaCapability to concrete types
        name_cap = get_schema_capability(User, SchemaName)
        doc_cap = get_schema_capability(User, SchemaDoc)
        assert name_cap is not None
        assert doc_cap is not None
        assert isinstance(name_cap, SchemaName)
        assert isinstance(doc_cap, SchemaDoc)

        # SQL table context
        sql_ctx = SQLAlchemyTableContext(class_name="User")
        sql_result = name_cap.compile_sqlalchemy_table(sql_ctx)
        assert sql_result.table_name == "user_accounts"

        # Pydantic model context
        pyd_ctx = PydanticModelContext(class_name="User")
        pyd_name = name_cap.compile_pydantic_model(pyd_ctx)
        assert pyd_name.title == "user_accounts"
        pyd_doc = doc_cap.compile_pydantic_model(pyd_ctx)
        assert pyd_doc.description == "User account entity"

        # OpenAPI schema context
        oa_ctx = OpenAPISchemaContext(class_name="User")
        oa_name = name_cap.compile_openapi_schema(oa_ctx)
        assert oa_name.schema["title"] == "user_accounts"
        oa_doc = doc_cap.compile_openapi_schema(oa_ctx)
        assert oa_doc.schema["description"] == "User account entity"

    def test_abstract_affects_sql_and_pydantic(self):
        """Abstract marks both SQL table and Pydantic model as abstract."""
        cap = Abstract()

        sql_result = cap.compile_sqlalchemy_table(SQLAlchemyTableContext(class_name="Base"))
        assert sql_result.is_abstract is True

        pyd_result = cap.compile_pydantic_model(PydanticModelContext(class_name="Base"))
        assert pyd_result.is_abstract is True

    def test_composite_constraints_with_schema_meta(self) -> None:
        """CompositeUnique + CompositeIndex + SchemaName all compile together."""
        # CompositeUnique/CompositeIndex are SQLCapability (SchemaAxisCapability),
        # not SchemaCapability — but schema_meta works at runtime via duck typing
        @schema_meta(
            SchemaName("orders"),
            CompositeUnique("user_id", "product_id", name="uq_user_product"),  # pyright: ignore[reportArgumentType]  # SQLCapability not SchemaCapability, works at runtime
            CompositeIndex("status", "created_at"),  # pyright: ignore[reportArgumentType]  # SQLCapability not SchemaCapability, works at runtime
        )
        @dataclass
        class Order:
            id: Annotated[int, Identity]
            user_id: int
            product_id: int
            status: str
            created_at: str

        caps = get_schema_meta(Order)
        assert len(caps) == 3

        # Compile table context
        ctx = SQLAlchemyTableContext(class_name="Order")

        name = get_schema_capability(Order, SchemaName)
        assert name is not None
        assert isinstance(name, SchemaName)
        table_result = name.compile_sqlalchemy_table(ctx)
        assert table_result.table_name == "orders"

        # CompositeUnique/CompositeIndex are not SchemaCapability subtypes —
        # find them directly from the meta tuple instead of get_schema_capability
        cu: CompositeUnique | None = None
        ci: CompositeIndex | None = None
        for cap in caps:
            if isinstance(cap, CompositeUnique):
                cu = cap
            elif isinstance(cap, CompositeIndex):
                ci = cap

        assert cu is not None
        cu_result = cu.compile_sqlalchemy_table(ctx)
        assert len(cu_result.constraints) == 1
        assert cu_result.constraints[0].fields == ("user_id", "product_id")
        # name now propagates through compilation (previously dropped)
        assert cu_result.constraints[0].name == "uq_user_product"

        assert ci is not None
        ci_result = ci.compile_sqlalchemy_table(ctx)
        assert len(ci_result.indexes) == 1

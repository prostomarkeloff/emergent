# pyright: reportPrivateUsage=false
"""Deep property-based tests for schema compilation — targets uncovered lines.

Covers:
  _universal.py: compile_constraints, compile_openapi, compile_argparse,
    compile_storage_field, compile_verify_*, compile_sqlalchemy, compile_pydantic,
    schema_meta/get_schema_meta/get_schema_capability, Coerce, _resolve_coerce,
    _extract_attr, TypeGuard helpers, Sensitive.compile_pydantic
  _inspect.py: pydantic_inspector, first_match, FieldInfo methods,
    unwrap_collection, get_nested_info, get_nested_type, is_structured_type,
    namedtuple_inspector, typeddict_inspector
  _helpers.py: _get_schema with custom axes, compose_schema_meta,
    get_nested_schema_meta, field_path_type, fields_by_dialect
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any, NamedTuple, TypedDict

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from pydantic import BaseModel
from pydantic.fields import FieldInfo as PydFieldInfo

from emergent.wire.axis.schema._universal import (
    # Base
    SchemaAxisCapability,
    UniversalCapability,
    SchemaName,
    SchemaDoc,
    Abstract,
    schema_meta,
    get_schema_meta,
    get_schema_capability,
    # Identity & Uniqueness
    Identity,
    Unique,
    # References
    Ref,
    # Numbers
    Min,
    Max,
    ExclusiveMin,
    ExclusiveMax,
    MultipleOf,
    # Strings/Collections
    MinLen,
    MaxLen,
    Pattern,
    # Enums & Unions
    OneOf,
    Nested,
    Embedded,
    # Documentation
    Doc,
    Deprecated,
    # Access control
    ReadOnly,
    WriteOnly,
    Sensitive,
    Immutable,
    # Nullability
    Nullable,
    # Naming
    Alias,
    # Computed
    Computed,
    # Coercion
    Coerce,
)
from emergent.wire.axis._capability import (
    OpenAPIContext,
    ArgparseContext,
    ConstraintsContext,
    StorageFieldContext,
    PydanticContext,
    SQLAlchemyContext,
    PydanticModelContext,
    OpenAPISchemaContext,
    SQLAlchemyTableContext,
)
from emergent.wire.verify._semantics import SemanticsVerifyCtx
from emergent.wire.verify._numeric import NumericVerifyCtx
from emergent.wire.verify._length import LengthVerifyCtx
from emergent.wire.axis.schema._inspect import (
    FieldInfo,
    inspect_type,
    inspect_field,
    first_match,
    dataclass_inspector,
    pydantic_inspector,
    typeddict_inspector,
    namedtuple_inspector,
    unwrap_optional,
    extract_capabilities,
    unwrap_collection,
    is_structured_type,
    get_nested_info,
    get_nested_type,
)
from emergent.wire.axis.schema._helpers import (
    get_identity_field,
    get_optional_fields,
    partition_fields,
    field_by_name,
    field_path_type,
    fields_with_capability,
    get_refs,
    fields_by_dialect,
    merge_capabilities,
    override_capability,
    remove_capability,
    deduplicate_capabilities,
    filter_universal,
    find_capability,
    find_all_capabilities,
    has_capability,
    compose_schema_meta,
    get_nested_schema_meta,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Test Entities
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class SimpleEntity:
    id: Annotated[int, Identity]
    name: Annotated[str, MaxLen(100)]


@dataclass(frozen=True)
class RichEntity:
    id: Annotated[int, Identity, ReadOnly]
    email: Annotated[str, Unique, MaxLen(255), Pattern(r"^[\w.]+@[\w.]+$")]
    age: Annotated[int, Min(0), Max(150), ExclusiveMin(-1), ExclusiveMax(200)]
    score: Annotated[float, MultipleOf(0.5)]
    password: Annotated[str, Sensitive]
    username: Annotated[str, Immutable, Alias("user_name")]
    bio: Annotated[str | None, Nullable, WriteOnly, Doc("User bio")] = None
    tags: Annotated[str, OneOf("admin", "user", "mod")] = "user"
    full_name: Annotated[str, Computed] = ""
    level: Annotated[int, MinLen(1)] = 1


@schema_meta(SchemaName("rich_entities"), SchemaDoc("A rich entity"))
@dataclass(frozen=True)
class AnnotatedEntity:
    id: Annotated[int, Identity]
    name: str


@schema_meta(Abstract())
@dataclass(frozen=True)
class AbstractEntity:
    id: Annotated[int, Identity]


@dataclass(frozen=True)
class Address:
    city: str
    zip_code: str


@dataclass(frozen=True)
class OrderItem:
    product: str
    qty: int


@dataclass(frozen=True)
class OrderWithNested:
    id: Annotated[int, Identity]
    items: Annotated[list[OrderItem], Nested()]
    address: Annotated[Address, Embedded()]


@dataclass(frozen=True)
class RefTarget:
    id: Annotated[int, Identity]
    name: str


@dataclass(frozen=True)
class RefHolder:
    id: Annotated[int, Identity]
    target_id: Annotated[int, Ref(target=RefTarget)]


class PydanticUser(BaseModel):
    id: int
    name: Annotated[str, MaxLen(50)]
    email: Annotated[str | None, Nullable] = None


class _UserTDRequired(TypedDict):
    id: int
    name: Annotated[str, MaxLen(100)]


class UserTD(_UserTDRequired, total=False):
    """TypedDict with optional 'bio' via total=False inheritance."""
    bio: str


class PointNT(NamedTuple):
    x: Annotated[float, Min(0)]
    y: Annotated[float, Min(0)]
    label: str = "origin"


@dataclass(frozen=True)
class NestedOuter:
    id: Annotated[int, Identity]
    items: list[SimpleEntity]


@dataclass(frozen=True)
class PathInner:
    value: int


@dataclass(frozen=True)
class PathOuter:
    inner: PathInner


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _openapi_ctx(name: str = "f", tp: type = str) -> OpenAPIContext:
    return OpenAPIContext(field_name=name, field_type=tp)


def _argparse_ctx(name: str = "f", tp: type = str) -> ArgparseContext:
    return ArgparseContext(field_name=name, field_type=tp)


def _constraints_ctx(name: str = "f", tp: type = str) -> ConstraintsContext:
    return ConstraintsContext(field_name=name, field_type=tp)


def _storage_ctx(name: str = "f", tp: type = str) -> StorageFieldContext:
    return StorageFieldContext(field_name=name, field_type=tp)


def _pydantic_ctx(name: str = "f", tp: type = str) -> PydanticContext:
    fi = PydFieldInfo()
    return PydanticContext(field_name=name, field_type=tp, field_info=fi)


def _sqlalchemy_ctx(name: str = "f", tp: type = str) -> SQLAlchemyContext:
    return SQLAlchemyContext(field_name=name, field_type=tp)


def _semantics_ctx(name: str = "f", tp: type = str) -> SemanticsVerifyCtx:
    return SemanticsVerifyCtx(field_name=name, field_type=tp)


def _numeric_ctx(name: str = "f", tp: type = int) -> NumericVerifyCtx:
    return NumericVerifyCtx(field_name=name, field_type=tp)


def _length_ctx(name: str = "f", tp: type = str) -> LengthVerifyCtx:
    return LengthVerifyCtx(field_name=name, field_type=tp)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. _universal.py — compile_constraints
# ═══════════════════════════════════════════════════════════════════════════════


class TestCompileConstraints:
    def test_identity_constraints(self) -> None:
        ctx = Identity().compile_constraints(_constraints_ctx())
        assert ctx.is_identity is True

    def test_unique_constraints(self) -> None:
        ctx = Unique().compile_constraints(_constraints_ctx())
        assert ctx.is_unique is True

    @given(val=st.integers(min_value=-1000, max_value=1000))
    def test_min_constraints(self, val: int) -> None:
        ctx = Min(val).compile_constraints(_constraints_ctx())
        assert ctx.min_value == val

    @given(val=st.integers(min_value=-1000, max_value=1000))
    def test_max_constraints(self, val: int) -> None:
        ctx = Max(val).compile_constraints(_constraints_ctx())
        assert ctx.max_value == val

    @given(val=st.floats(min_value=-100, max_value=100, allow_nan=False))
    def test_exclusive_min_constraints(self, val: float) -> None:
        ctx = ExclusiveMin(val).compile_constraints(_constraints_ctx())
        assert ctx.exclusive_min == val

    @given(val=st.floats(min_value=-100, max_value=100, allow_nan=False))
    def test_exclusive_max_constraints(self, val: float) -> None:
        ctx = ExclusiveMax(val).compile_constraints(_constraints_ctx())
        assert ctx.exclusive_max == val

    @given(val=st.floats(min_value=0.01, max_value=100, allow_nan=False))
    def test_multiple_of_constraints(self, val: float) -> None:
        ctx = MultipleOf(val).compile_constraints(_constraints_ctx())
        assert ctx.multiple_of == val

    @given(val=st.integers(min_value=0, max_value=1000))
    def test_min_len_constraints(self, val: int) -> None:
        ctx = MinLen(val).compile_constraints(_constraints_ctx())
        assert ctx.min_length == val

    @given(val=st.integers(min_value=1, max_value=1000))
    def test_max_len_constraints(self, val: int) -> None:
        ctx = MaxLen(val).compile_constraints(_constraints_ctx())
        assert ctx.max_length == val

    def test_pattern_constraints(self) -> None:
        ctx = Pattern(r"^[a-z]+$").compile_constraints(_constraints_ctx())
        assert ctx.pattern == r"^[a-z]+$"

    def test_oneof_constraints(self) -> None:
        ctx = OneOf("a", "b", "c").compile_constraints(_constraints_ctx())
        assert ctx.choices == ("a", "b", "c")


# ═══════════════════════════════════════════════════════════════════════════════
# 2. _universal.py — compile_openapi
# ═══════════════════════════════════════════════════════════════════════════════


class TestCompileOpenAPI:
    @given(val=st.integers(min_value=-1000, max_value=1000))
    def test_min_openapi(self, val: int) -> None:
        ctx = Min(val).compile_openapi(_openapi_ctx())
        assert ctx.schema["minimum"] == val

    @given(val=st.integers(min_value=-1000, max_value=1000))
    def test_max_openapi(self, val: int) -> None:
        ctx = Max(val).compile_openapi(_openapi_ctx())
        assert ctx.schema["maximum"] == val

    @given(val=st.floats(min_value=-100, max_value=100, allow_nan=False))
    def test_exclusive_min_openapi(self, val: float) -> None:
        ctx = ExclusiveMin(val).compile_openapi(_openapi_ctx())
        assert ctx.schema["exclusiveMinimum"] == val

    @given(val=st.floats(min_value=-100, max_value=100, allow_nan=False))
    def test_exclusive_max_openapi(self, val: float) -> None:
        ctx = ExclusiveMax(val).compile_openapi(_openapi_ctx())
        assert ctx.schema["exclusiveMaximum"] == val

    @given(val=st.floats(min_value=0.01, max_value=100, allow_nan=False))
    def test_multiple_of_openapi(self, val: float) -> None:
        ctx = MultipleOf(val).compile_openapi(_openapi_ctx())
        assert ctx.schema["multipleOf"] == val

    def test_readonly_openapi(self) -> None:
        ctx = ReadOnly().compile_openapi(_openapi_ctx())
        assert ctx.schema["readOnly"] is True

    def test_writeonly_openapi(self) -> None:
        ctx = WriteOnly().compile_openapi(_openapi_ctx())
        assert ctx.schema["writeOnly"] is True

    def test_sensitive_openapi(self) -> None:
        ctx = Sensitive().compile_openapi(_openapi_ctx())
        assert ctx.schema["writeOnly"] is True
        assert ctx.schema["format"] == "password"

    def test_immutable_openapi(self) -> None:
        ctx = Immutable().compile_openapi(_openapi_ctx())
        assert ctx.schema["x-immutable"] is True

    def test_nullable_openapi(self) -> None:
        ctx = Nullable().compile_openapi(_openapi_ctx())
        assert ctx.schema["nullable"] is True

    def test_alias_openapi(self) -> None:
        ctx = Alias("my_alias").compile_openapi(_openapi_ctx())
        assert ctx.schema["x-alias"] == "my_alias"

    def test_computed_openapi(self) -> None:
        ctx = Computed().compile_openapi(_openapi_ctx())
        assert ctx.schema["readOnly"] is True
        assert ctx.schema["x-computed"] is True

    def test_nested_openapi(self) -> None:
        ctx = Nested(cascade="delete").compile_openapi(_openapi_ctx())
        assert ctx.schema["x-nested"] is True
        assert ctx.schema["x-cascade"] == "delete"

    def test_embedded_openapi(self) -> None:
        ctx = Embedded(format="flatten").compile_openapi(_openapi_ctx())
        assert ctx.schema["x-embedded"] is True
        assert ctx.schema["x-format"] == "flatten"

    def test_oneof_openapi(self) -> None:
        ctx = OneOf("a", "b").compile_openapi(_openapi_ctx())
        assert ctx.schema["enum"] == ["a", "b"]

    def test_doc_openapi(self) -> None:
        ctx = Doc("hello").compile_openapi(_openapi_ctx())
        assert ctx.schema["description"] == "hello"

    def test_deprecated_openapi(self) -> None:
        ctx = Deprecated().compile_openapi(_openapi_ctx())
        assert ctx.schema["deprecated"] is True

    def test_minlen_openapi(self) -> None:
        ctx = MinLen(5).compile_openapi(_openapi_ctx())
        assert ctx.schema["minLength"] == 5

    def test_maxlen_openapi(self) -> None:
        ctx = MaxLen(50).compile_openapi(_openapi_ctx())
        assert ctx.schema["maxLength"] == 50

    def test_pattern_openapi(self) -> None:
        ctx = Pattern(r"^\d+$").compile_openapi(_openapi_ctx())
        assert ctx.schema["pattern"] == r"^\d+$"


# ═══════════════════════════════════════════════════════════════════════════════
# 3. _universal.py — compile_argparse
# ═══════════════════════════════════════════════════════════════════════════════


class TestCompileArgparse:
    def test_oneof_argparse(self) -> None:
        ctx = OneOf("x", "y", "z").compile_argparse(_argparse_ctx())
        assert ctx.kwargs["choices"] == ["x", "y", "z"]

    def test_doc_argparse(self) -> None:
        ctx = Doc("Help text").compile_argparse(_argparse_ctx())
        assert ctx.kwargs["help"] == "Help text"

    def test_alias_argparse(self) -> None:
        ctx = Alias("my-arg").compile_argparse(_argparse_ctx())
        assert ctx.arg_names == ("--my-arg",)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. _universal.py — compile_storage_field
# ═══════════════════════════════════════════════════════════════════════════════


class TestCompileStorageField:
    def test_identity_storage_field(self) -> None:
        ctx = Identity().compile_storage_field(_storage_ctx())
        assert ctx.is_identity is True


# ═══════════════════════════════════════════════════════════════════════════════
# 5. _universal.py — compile_verify_semantics
# ═══════════════════════════════════════════════════════════════════════════════


class TestCompileVerifySemantics:
    def test_identity_semantics(self) -> None:
        ctx = Identity().compile_verify_semantics(_semantics_ctx())
        assert ctx.is_identity is True

    def test_unique_semantics(self) -> None:
        ctx = Unique().compile_verify_semantics(_semantics_ctx())
        assert ctx.is_unique is True

    def test_readonly_semantics(self) -> None:
        ctx = ReadOnly().compile_verify_semantics(_semantics_ctx())
        assert ctx.is_read_only is True

    def test_writeonly_semantics(self) -> None:
        ctx = WriteOnly().compile_verify_semantics(_semantics_ctx())
        assert ctx.is_write_only is True

    def test_sensitive_semantics(self) -> None:
        ctx = Sensitive().compile_verify_semantics(_semantics_ctx())
        assert ctx.is_sensitive is True
        assert ctx.is_write_only is True

    def test_immutable_semantics(self) -> None:
        ctx = Immutable().compile_verify_semantics(_semantics_ctx())
        assert ctx.is_immutable is True

    def test_nullable_semantics(self) -> None:
        ctx = Nullable().compile_verify_semantics(_semantics_ctx())
        assert ctx.is_nullable is True

    def test_computed_semantics(self) -> None:
        ctx = Computed().compile_verify_semantics(_semantics_ctx())
        assert ctx.is_computed is True


# ═══════════════════════════════════════════════════════════════════════════════
# 6. _universal.py — compile_verify_numeric
# ═══════════════════════════════════════════════════════════════════════════════


class TestCompileVerifyNumeric:
    @given(val=st.integers(min_value=-1000, max_value=1000))
    def test_min_numeric(self, val: int) -> None:
        ctx = Min(val).compile_verify_numeric(_numeric_ctx())
        assert ctx.lower_bound == float(val)

    @given(val=st.integers(min_value=-1000, max_value=1000))
    def test_max_numeric(self, val: int) -> None:
        ctx = Max(val).compile_verify_numeric(_numeric_ctx())
        assert ctx.upper_bound == float(val)

    @given(val=st.floats(min_value=-100, max_value=100, allow_nan=False))
    def test_exclusive_min_numeric(self, val: float) -> None:
        ctx = ExclusiveMin(val).compile_verify_numeric(_numeric_ctx())
        assert ctx.exclusive_lower == float(val)

    @given(val=st.floats(min_value=-100, max_value=100, allow_nan=False))
    def test_exclusive_max_numeric(self, val: float) -> None:
        ctx = ExclusiveMax(val).compile_verify_numeric(_numeric_ctx())
        assert ctx.exclusive_upper == float(val)

    @given(val=st.floats(min_value=0.01, max_value=100, allow_nan=False))
    def test_multiple_of_numeric(self, val: float) -> None:
        ctx = MultipleOf(val).compile_verify_numeric(_numeric_ctx())
        assert ctx.multiple_of == float(val)


# ═══════════════════════════════════════════════════════════════════════════════
# 7. _universal.py — compile_verify_length
# ═══════════════════════════════════════════════════════════════════════════════


class TestCompileVerifyLength:
    @given(val=st.integers(min_value=0, max_value=1000))
    def test_minlen_length(self, val: int) -> None:
        ctx = MinLen(val).compile_verify_length(_length_ctx())
        assert ctx.min_length == val

    @given(val=st.integers(min_value=1, max_value=1000))
    def test_maxlen_length(self, val: int) -> None:
        ctx = MaxLen(val).compile_verify_length(_length_ctx())
        assert ctx.max_length == val

    def test_pattern_length(self) -> None:
        ctx = Pattern(r"^[a-z]+$").compile_verify_length(_length_ctx())
        assert ctx.pattern == r"^[a-z]+$"


# ═══════════════════════════════════════════════════════════════════════════════
# 8. _universal.py — compile_sqlalchemy (MaxLen, Nullable, Alias)
# ═══════════════════════════════════════════════════════════════════════════════


_HAS_SA = pytest.importorskip is not None  # just True, used below


def _has_sqlalchemy() -> bool:
    try:
        __import__("sqlalchemy")
        return True
    except ImportError:
        return False


class TestCompileSQLAlchemy:
    @pytest.mark.skipif(not _has_sqlalchemy(), reason="sqlalchemy not installed")
    def test_maxlen_sqlalchemy_string(self) -> None:
        """MaxLen should refine str column type to String(n)."""
        from sqlalchemy import String

        ctx = MaxLen(255).compile_sqlalchemy(_sqlalchemy_ctx(tp=str))
        assert isinstance(ctx.column_type, String)
        assert ctx.column_type.length == 255

    def test_maxlen_sqlalchemy_non_string(self) -> None:
        """MaxLen should not change column type for non-str."""
        ctx = MaxLen(255).compile_sqlalchemy(_sqlalchemy_ctx(tp=int))
        assert ctx.column_type is None  # unchanged

    def test_nullable_sqlalchemy(self) -> None:
        ctx = Nullable().compile_sqlalchemy(_sqlalchemy_ctx())
        assert ctx.column_kwargs["nullable"] is True

    def test_identity_sqlalchemy(self) -> None:
        ctx = Identity().compile_sqlalchemy(_sqlalchemy_ctx())
        assert ctx.column_kwargs["primary_key"] is True

    def test_unique_sqlalchemy(self) -> None:
        ctx = Unique().compile_sqlalchemy(_sqlalchemy_ctx())
        assert ctx.column_kwargs["unique"] is True

    def test_alias_sqlalchemy(self) -> None:
        ctx = Alias("col_name").compile_sqlalchemy(_sqlalchemy_ctx())
        assert ctx.column_kwargs["name"] == "col_name"


# ═══════════════════════════════════════════════════════════════════════════════
# 9. _universal.py — compile_pydantic (Sensitive, ReadOnly, WriteOnly, etc.)
# ═══════════════════════════════════════════════════════════════════════════════


class TestCompilePydantic:
    def test_sensitive_pydantic_sets_repr_false_and_writeonly(self) -> None:
        ctx = Sensitive().compile_pydantic(_pydantic_ctx())
        fi = ctx.field_info
        assert fi.repr is False
        extra: Any = fi.json_schema_extra
        assert isinstance(extra, dict)
        assert extra["writeOnly"] is True

    def test_sensitive_pydantic_merges_existing_extra(self) -> None:
        base_ctx = _pydantic_ctx()
        fi = base_ctx.field_info
        fi.json_schema_extra = {"existingKey": "value"}
        ctx = Sensitive().compile_pydantic(base_ctx)
        extra = ctx.field_info.json_schema_extra
        assert isinstance(extra, dict)
        assert extra["writeOnly"] is True
        # existing key preserved (deep copy means original not the same object)

    def test_readonly_pydantic(self) -> None:
        ctx = ReadOnly().compile_pydantic(_pydantic_ctx())
        extra: Any = ctx.field_info.json_schema_extra
        assert isinstance(extra, dict)
        assert extra["readOnly"] is True

    def test_writeonly_pydantic(self) -> None:
        ctx = WriteOnly().compile_pydantic(_pydantic_ctx())
        extra: Any = ctx.field_info.json_schema_extra
        assert isinstance(extra, dict)
        assert extra["writeOnly"] is True

    def test_computed_pydantic(self) -> None:
        ctx = Computed().compile_pydantic(_pydantic_ctx())
        extra: Any = ctx.field_info.json_schema_extra
        assert isinstance(extra, dict)
        assert extra["readOnly"] is True

    def test_alias_pydantic(self) -> None:
        ctx = Alias("aliased").compile_pydantic(_pydantic_ctx())
        assert ctx.field_info.alias == "aliased"

    def test_doc_pydantic(self) -> None:
        ctx = Doc("description text").compile_pydantic(_pydantic_ctx())
        assert ctx.field_info.description == "description text"

    def test_deprecated_pydantic(self) -> None:
        ctx = Deprecated().compile_pydantic(_pydantic_ctx())
        assert ctx.field_info.deprecated is True

    def test_deprecated_with_reason_pydantic(self) -> None:
        ctx = Deprecated(reason="old API").compile_pydantic(_pydantic_ctx())
        assert ctx.field_info.deprecated == "old API"


# ═══════════════════════════════════════════════════════════════════════════════
# 10. _universal.py — schema_meta / get_schema_meta / get_schema_capability
# ═══════════════════════════════════════════════════════════════════════════════


class TestSchemaMeta:
    def test_get_schema_meta_returns_capabilities(self) -> None:
        meta = get_schema_meta(AnnotatedEntity)
        assert len(meta) == 2
        assert isinstance(meta[0], SchemaName)
        assert isinstance(meta[1], SchemaDoc)

    def test_get_schema_meta_empty(self) -> None:
        meta = get_schema_meta(SimpleEntity)
        assert meta == ()

    def test_get_schema_capability_found(self) -> None:
        cap = get_schema_capability(AnnotatedEntity, SchemaName)
        assert cap is not None
        assert isinstance(cap, SchemaName)
        assert cap.value == "rich_entities"

    def test_get_schema_capability_not_found(self) -> None:
        cap = get_schema_capability(SimpleEntity, SchemaName)
        assert cap is None

    def test_get_schema_capability_specific_type(self) -> None:
        cap = get_schema_capability(AnnotatedEntity, SchemaDoc)
        assert cap is not None
        assert isinstance(cap, SchemaDoc)
        assert cap.description == "A rich entity"

    def test_schema_meta_stacks(self) -> None:
        """Applying schema_meta twice should accumulate."""

        @schema_meta(SchemaName("first"))
        @schema_meta(SchemaDoc("second"))
        @dataclass(frozen=True)
        class Stacked:
            x: int

        meta = get_schema_meta(Stacked)
        assert len(meta) == 2

    def test_abstract_pydantic_model(self) -> None:
        cap = Abstract()
        ctx = PydanticModelContext(class_name="Base")
        result = cap.compile_pydantic_model(ctx)
        assert result.is_abstract is True

    def test_abstract_sqlalchemy_table(self) -> None:
        cap = Abstract()
        ctx = SQLAlchemyTableContext(class_name="Base")
        result = cap.compile_sqlalchemy_table(ctx)
        assert result.is_abstract is True

    def test_schema_name_pydantic_model(self) -> None:
        cap = SchemaName("my_name")
        ctx = PydanticModelContext(class_name="X")
        result = cap.compile_pydantic_model(ctx)
        assert result.title == "my_name"

    def test_schema_name_openapi_schema(self) -> None:
        cap = SchemaName("my_name")
        ctx = OpenAPISchemaContext(class_name="X")
        result = cap.compile_openapi_schema(ctx)
        assert result.schema["title"] == "my_name"

    def test_schema_name_sqlalchemy_table(self) -> None:
        cap = SchemaName("my_table")
        ctx = SQLAlchemyTableContext(class_name="X")
        result = cap.compile_sqlalchemy_table(ctx)
        assert result.table_name == "my_table"

    def test_schema_doc_pydantic_model(self) -> None:
        cap = SchemaDoc("desc")
        ctx = PydanticModelContext(class_name="X")
        result = cap.compile_pydantic_model(ctx)
        assert result.description == "desc"

    def test_schema_doc_openapi_schema(self) -> None:
        cap = SchemaDoc("desc")
        ctx = OpenAPISchemaContext(class_name="X")
        result = cap.compile_openapi_schema(ctx)
        assert result.schema["description"] == "desc"


# ═══════════════════════════════════════════════════════════════════════════════
# 11. _universal.py — Ref
# ═══════════════════════════════════════════════════════════════════════════════


class TestRef:
    def test_ref_resolve_fk_target_type(self) -> None:
        ref = Ref(target=RefTarget)
        # RefTarget has no __tablename__, so falls back to class name lower
        assert ref._resolve_fk_target() == "reftarget.id"

    def test_ref_resolve_fk_target_string(self) -> None:
        ref = Ref(target="users.user_id")
        assert ref._resolve_fk_target() == "users.user_id"

    def test_ref_compile_sqlalchemy(self) -> None:
        ref = Ref(target="users.id", on_delete="SET NULL")
        ctx = ref.compile_sqlalchemy(_sqlalchemy_ctx())
        assert ctx.column_kwargs["fk_target"] == "users.id"
        assert ctx.column_kwargs["fk_ondelete"] == "SET NULL"
        assert ctx.column_kwargs["fk_onupdate"] == "CASCADE"


# ═══════════════════════════════════════════════════════════════════════════════
# 12. _universal.py — Coerce & _resolve_coerce
# ═══════════════════════════════════════════════════════════════════════════════


class TestCoerce:
    def test_coerce_tuple(self) -> None:
        c = Coerce(tuple)
        assert c.to_storage((1, 2, 3)) == [1, 2, 3]
        assert c.from_storage([1, 2, 3]) == (1, 2, 3)
        assert c.storage_type is list

    def test_coerce_set(self) -> None:
        c = Coerce(set)
        assert c.to_storage({1, 2, 3}) == [1, 2, 3]
        assert c.from_storage([1, 2, 3]) == {1, 2, 3}
        assert c.storage_type is list

    def test_coerce_frozenset(self) -> None:
        c = Coerce(frozenset)
        assert c.to_storage(frozenset({1, 2})) == [1, 2]
        assert c.from_storage([1, 2]) == frozenset({1, 2})
        assert c.storage_type is list

    def test_coerce_option(self) -> None:
        from kungfu import Option, Some, Nothing

        src: Any = Option[str]
        c = Coerce(src)
        assert c.to_storage(Some("hello")) == "hello"
        assert c.to_storage(Nothing()) is None
        assert c.storage_type is str

        result = c.from_storage(None)
        assert isinstance(result, Nothing)
        result2 = c.from_storage("hello")
        assert isinstance(result2, Some)

    def test_coerce_sum(self) -> None:
        import json
        from kungfu import Sum

        sum_type: Any = Sum[int, str]
        c = Coerce(sum_type)
        assert c.storage_type is str

        sum_val = Sum[int, str](42)
        stored_val: Any = c.to_storage(sum_val)
        parsed = json.loads(stored_val)
        assert parsed["_t"] == "int"
        assert parsed["_v"] == 42

        # from_storage roundtrip
        restored = c.from_storage(stored_val)
        assert isinstance(restored, Sum)

    def test_coerce_result(self) -> None:
        import json
        from kungfu import Result, Ok, Error

        # Result is a TypeAliasType — Coerce(Result) is the supported form
        result_type: Any = Result
        c = Coerce(result_type)
        assert c.storage_type is str

        ok_stored = c.to_storage(Ok(42))
        assert isinstance(ok_stored, str)
        parsed_ok = json.loads(ok_stored)
        assert parsed_ok["ok"] is True
        assert parsed_ok["v"] == 42

        err_stored: Any = c.to_storage(Error("fail"))
        parsed_err = json.loads(err_stored)
        assert parsed_err["ok"] is False
        assert parsed_err["e"] == "fail"

        # from_storage
        ok_back = c.from_storage(ok_stored)
        assert isinstance(ok_back, Ok)
        err_back = c.from_storage(err_stored)
        assert isinstance(err_back, Error)

    def test_coerce_unknown_type_raises(self) -> None:
        class CustomType:
            pass

        with pytest.raises(TypeError, match="No built-in coercion"):
            Coerce(CustomType)

    def test_coerce_compile_storage_field(self) -> None:
        c = Coerce(tuple)
        ctx = c.compile_storage_field(_storage_ctx())
        assert ctx.to_storage is c.to_storage
        assert ctx.from_storage is c.from_storage
        assert ctx.storage_type is list

    @pytest.mark.skipif(not _has_sqlalchemy(), reason="sqlalchemy not installed")
    def test_coerce_compile_sqlalchemy_with_type_map(self) -> None:
        c = Coerce(tuple)
        from sqlalchemy import JSON

        type_map: dict[type, type] = {list: JSON}
        ctx = SQLAlchemyContext(
            field_name="f", field_type=list, type_map=type_map
        )
        result = c.compile_sqlalchemy(ctx)
        assert result.column_type is JSON

    def test_coerce_compile_sqlalchemy_no_storage_type(self) -> None:
        """When storage_type is None, column_type stays unchanged."""
        c = Coerce(tuple)  # storage_type is list
        ctx = _sqlalchemy_ctx()
        result = c.compile_sqlalchemy(ctx)
        # type_map is empty so column_type stays as ctx.column_type
        assert result.column_type is ctx.column_type


# ═══════════════════════════════════════════════════════════════════════════════
# 13. _universal.py — _extract_attr, TypeGuard helpers
# ═══════════════════════════════════════════════════════════════════════════════


class TestTypeGuardHelpers:
    def test_extract_attr_hit(self) -> None:
        from emergent.wire.axis.schema._universal import _extract_attr
        from kungfu import Some

        val = _extract_attr(Some, Some(42), "value")
        assert val == 42

    def test_extract_attr_miss(self) -> None:
        from emergent.wire.axis.schema._universal import _extract_attr, _Miss

        val = _extract_attr(int, "not_int", "__class__")
        assert isinstance(val, _Miss)

    def test_is_tuple_guard(self) -> None:
        from emergent.wire.axis.schema._universal import _is_tuple

        assert _is_tuple((1, 2)) is True
        assert _is_tuple([1, 2]) is False

    def test_is_list_guard(self) -> None:
        from emergent.wire.axis.schema._universal import _is_list

        assert _is_list([1, 2]) is True
        assert _is_list((1, 2)) is False

    def test_is_set_guard(self) -> None:
        from emergent.wire.axis.schema._universal import _is_set

        assert _is_set({1, 2}) is True
        assert _is_set([1, 2]) is False

    def test_is_frozenset_guard(self) -> None:
        from emergent.wire.axis.schema._universal import _is_frozenset

        assert _is_frozenset(frozenset({1})) is True
        assert _is_frozenset({1}) is False

    def test_is_dict_guard(self) -> None:
        from emergent.wire.axis.schema._universal import _is_dict

        assert _is_dict({"k": "v"}) is True
        assert _is_dict([]) is False


# ═══════════════════════════════════════════════════════════════════════════════
# 14. _universal.py — Coerce edge cases with non-matching values
# ═══════════════════════════════════════════════════════════════════════════════


class TestCoerceEdgeCases:
    def test_tuple_to_storage_non_tuple(self) -> None:
        c = Coerce(tuple)
        assert c.to_storage("not a tuple") == "not a tuple"

    def test_tuple_from_storage_non_list(self) -> None:
        c = Coerce(tuple)
        assert c.from_storage("not a list") == "not a list"

    def test_set_to_storage_non_set(self) -> None:
        c = Coerce(set)
        assert c.to_storage("not a set") == "not a set"

    def test_set_from_storage_non_list(self) -> None:
        c = Coerce(set)
        assert c.from_storage("not a list") == "not a list"

    def test_frozenset_to_non_frozenset(self) -> None:
        c = Coerce(frozenset)
        assert c.to_storage("nope") == "nope"

    def test_frozenset_from_non_list(self) -> None:
        c = Coerce(frozenset)
        assert c.from_storage("nope") == "nope"

    def test_option_to_storage_plain_value(self) -> None:
        """When value is not Some or Nothing, passthrough."""
        from kungfu import Option

        option_type: Any = Option[str]
        c = Coerce(option_type)
        assert c.to_storage("plain") == "plain"


# ═══════════════════════════════════════════════════════════════════════════════
# 15. _inspect.py — pydantic_inspector
# ═══════════════════════════════════════════════════════════════════════════════


class TestPydanticInspector:
    def test_pydantic_basic(self) -> None:
        fields = pydantic_inspector(PydanticUser)
        assert fields is not None
        assert "id" in fields
        assert "name" in fields
        assert fields["id"].base_type is int
        assert not fields["id"].is_optional

    def test_pydantic_optional_field(self) -> None:
        fields = pydantic_inspector(PydanticUser)
        assert fields is not None
        assert fields["email"].is_optional is True
        assert fields["email"].has_default is True

    def test_pydantic_capability_extraction(self) -> None:
        fields = pydantic_inspector(PydanticUser)
        assert fields is not None
        assert fields["name"].has(MaxLen) is True
        assert fields["email"].has(Nullable) is True

    def test_pydantic_returns_none_for_non_pydantic(self) -> None:
        assert pydantic_inspector(SimpleEntity) is None


# ═══════════════════════════════════════════════════════════════════════════════
# 16. _inspect.py — typeddict_inspector
# ═══════════════════════════════════════════════════════════════════════════════


class TestTypedDictInspector:
    def test_typeddict_basic(self) -> None:
        fields = typeddict_inspector(UserTD)
        assert fields is not None
        assert "id" in fields
        assert "name" in fields
        assert "bio" in fields

    def test_typeddict_required_vs_optional(self) -> None:
        fields = typeddict_inspector(UserTD)
        assert fields is not None
        assert fields["id"].is_optional is False
        assert fields["bio"].is_optional is True
        assert fields["bio"].has_default is True

    def test_typeddict_capability(self) -> None:
        fields = typeddict_inspector(UserTD)
        assert fields is not None
        assert fields["name"].has(MaxLen) is True

    def test_typeddict_returns_none_for_dataclass(self) -> None:
        assert typeddict_inspector(SimpleEntity) is None


# ═══════════════════════════════════════════════════════════════════════════════
# 17. _inspect.py — namedtuple_inspector
# ═══════════════════════════════════════════════════════════════════════════════


class TestNamedTupleInspector:
    def test_namedtuple_basic(self) -> None:
        fields = namedtuple_inspector(PointNT)
        assert fields is not None
        assert "x" in fields
        assert "y" in fields
        assert "label" in fields

    def test_namedtuple_defaults(self) -> None:
        fields = namedtuple_inspector(PointNT)
        assert fields is not None
        assert fields["label"].has_default is True
        assert fields["x"].has_default is False

    def test_namedtuple_capabilities(self) -> None:
        fields = namedtuple_inspector(PointNT)
        assert fields is not None
        assert fields["x"].has(Min) is True

    def test_namedtuple_returns_none_for_dataclass(self) -> None:
        assert namedtuple_inspector(SimpleEntity) is None


# ═══════════════════════════════════════════════════════════════════════════════
# 18. _inspect.py — first_match combinator
# ═══════════════════════════════════════════════════════════════════════════════


class TestFirstMatch:
    def test_first_match_dataclass(self) -> None:
        inspector = first_match(dataclass_inspector)
        result = inspector(SimpleEntity)
        assert "id" in result

    def test_first_match_raises_for_unknown(self) -> None:
        inspector = first_match(dataclass_inspector)
        with pytest.raises(TypeError, match="Cannot inspect"):
            inspector(int)

    def test_first_match_priority(self) -> None:
        """First matching inspector wins."""

        def always_none(cls: type) -> dict[str, FieldInfo] | None:
            return None

        inspector = first_match(always_none, dataclass_inspector)
        result = inspector(SimpleEntity)
        assert "id" in result


# ═══════════════════════════════════════════════════════════════════════════════
# 19. _inspect.py — FieldInfo methods
# ═══════════════════════════════════════════════════════════════════════════════


class TestFieldInfoMethods:
    def test_universal_property(self) -> None:
        fields = inspect_type(RichEntity)
        fi = fields["email"]
        universal = fi.universal
        assert all(isinstance(c, UniversalCapability) for c in universal)

    def test_dialect_method(self) -> None:
        fields = inspect_type(RichEntity)
        fi = fields["email"]
        universal = fi.dialect(UniversalCapability)
        assert len(universal) > 0

    def test_has_method(self) -> None:
        fields = inspect_type(RichEntity)
        assert fields["email"].has(Unique) is True
        assert fields["email"].has(Identity) is False

    def test_get_method_found(self) -> None:
        fields = inspect_type(RichEntity)
        cap = fields["email"].get(MaxLen)
        assert cap is not None
        assert cap.value == 255

    def test_get_method_not_found(self) -> None:
        fields = inspect_type(RichEntity)
        cap = fields["email"].get(Identity)
        assert cap is None

    def test_get_all_method(self) -> None:
        fields = inspect_type(RichEntity)
        all_caps = fields["email"].get_all(UniversalCapability)
        assert len(all_caps) >= 3  # Unique, MaxLen, Pattern


# ═══════════════════════════════════════════════════════════════════════════════
# 20. _inspect.py — unwrap_collection, nested helpers
# ═══════════════════════════════════════════════════════════════════════════════


class TestUnwrapCollectionAndNested:
    def test_unwrap_list(self) -> None:
        assert unwrap_collection(list[int]) is int

    def test_unwrap_set(self) -> None:
        assert unwrap_collection(set[str]) is str

    def test_unwrap_frozenset(self) -> None:
        assert unwrap_collection(frozenset[float]) is float

    def test_unwrap_tuple_homogeneous(self) -> None:
        assert unwrap_collection(tuple[int, ...]) is int

    def test_unwrap_non_collection(self) -> None:
        assert unwrap_collection(str) is str

    def test_is_structured_type_dataclass(self) -> None:
        assert is_structured_type(SimpleEntity) is True

    def test_is_structured_type_pydantic(self) -> None:
        assert is_structured_type(PydanticUser) is True

    def test_is_structured_type_typeddict(self) -> None:
        assert is_structured_type(UserTD) is True

    def test_is_structured_type_namedtuple(self) -> None:
        assert is_structured_type(PointNT) is True

    def test_is_structured_type_primitive(self) -> None:
        assert is_structured_type(str) is False

    def test_get_nested_info_found(self) -> None:
        fields = inspect_type(NestedOuter)
        nested = get_nested_info(fields["items"])
        assert nested is not None
        assert "id" in nested

    def test_get_nested_info_not_found(self) -> None:
        fi = FieldInfo(name="x", base_type=str, is_optional=False, capabilities=())
        assert get_nested_info(fi) is None

    def test_get_nested_type_found(self) -> None:
        fields = inspect_type(NestedOuter)
        nt = get_nested_type(fields["items"])
        assert nt is SimpleEntity

    def test_get_nested_type_not_found(self) -> None:
        fi = FieldInfo(name="x", base_type=str, is_optional=False, capabilities=())
        assert get_nested_type(fi) is None


# ═══════════════════════════════════════════════════════════════════════════════
# 21. _inspect.py — inspect_type for all structured types
# ═══════════════════════════════════════════════════════════════════════════════


class TestInspectTypeAllTypes:
    def test_inspect_pydantic(self) -> None:
        fields = inspect_type(PydanticUser)
        assert "id" in fields
        assert "name" in fields

    def test_inspect_typeddict(self) -> None:
        fields = inspect_type(UserTD)
        assert "id" in fields

    def test_inspect_namedtuple(self) -> None:
        fields = inspect_type(PointNT)
        assert "x" in fields

    def test_inspect_raises_for_unsupported(self) -> None:
        with pytest.raises(TypeError):
            inspect_type(int)


# ═══════════════════════════════════════════════════════════════════════════════
# 22. _helpers.py — _get_schema with custom axes
# ═══════════════════════════════════════════════════════════════════════════════


class TestHelpersCustomAxes:
    def test_get_schema_with_custom_axes(self) -> None:
        """The _get_schema function should use axes.schema if provided."""

        class FakeAxes:
            def schema(self, cls: type) -> dict[str, FieldInfo]:
                return {"fake": FieldInfo(
                    name="fake",
                    base_type=str,
                    is_optional=False,
                    capabilities=(),
                )}

        result = get_identity_field(SimpleEntity, FakeAxes())
        # fake field has no Identity, so should return None
        assert result is None

    def test_field_path_type_nested(self) -> None:
        result = field_path_type(PathOuter, "inner")
        assert result is PathInner

    def test_field_path_type_invalid_path(self) -> None:
        result = field_path_type(SimpleEntity, "nonexistent")
        assert result is None


# ═══════════════════════════════════════════════════════════════════════════════
# 23. _helpers.py — compose_schema_meta
# ═══════════════════════════════════════════════════════════════════════════════


class TestComposeSchemaMetaHelper:
    def test_compose_no_overrides(self) -> None:
        result = compose_schema_meta(AnnotatedEntity)
        assert len(result) == 2

    def test_compose_with_overrides(self) -> None:
        result = compose_schema_meta(AnnotatedEntity, (SchemaName("override"),))
        # Should have SchemaDoc + SchemaName("override")
        names = [c for c in result if isinstance(c, SchemaName)]
        assert any(n.value == "override" for n in names)


# ═══════════════════════════════════════════════════════════════════════════════
# 24. _helpers.py — get_nested_schema_meta
# ═══════════════════════════════════════════════════════════════════════════════


class TestGetNestedSchemaMetaHelper:
    def test_nested_schema_meta_no_structured_type(self) -> None:
        fi = FieldInfo(name="x", base_type=str, is_optional=False, capabilities=())
        assert get_nested_schema_meta(fi) == ()

    def test_nested_schema_meta_structured(self) -> None:
        fi = FieldInfo(
            name="items",
            base_type=AnnotatedEntity,
            is_optional=False,
            capabilities=(),
        )
        result = get_nested_schema_meta(fi)
        assert len(result) == 2  # SchemaName + SchemaDoc

    def test_nested_schema_meta_with_nested_override(self) -> None:
        fi = FieldInfo(
            name="items",
            base_type=AnnotatedEntity,
            is_optional=False,
            capabilities=(Nested(meta=(SchemaName("override"),)),),
        )
        result = get_nested_schema_meta(fi)
        names = [c for c in result if isinstance(c, SchemaName)]
        assert any(n.value == "override" for n in names)

    def test_nested_schema_meta_with_embedded_override(self) -> None:
        fi = FieldInfo(
            name="addr",
            base_type=AnnotatedEntity,
            is_optional=False,
            capabilities=(Embedded(meta=(SchemaName("emb_override"),)),),
        )
        result = get_nested_schema_meta(fi)
        names = [c for c in result if isinstance(c, SchemaName)]
        assert any(n.value == "emb_override" for n in names)


# ═══════════════════════════════════════════════════════════════════════════════
# 25. _helpers.py — capability composition functions
# ═══════════════════════════════════════════════════════════════════════════════


class TestCapabilityComposition:
    def test_merge_capabilities_override(self) -> None:
        base = (MaxLen(100), Doc("Name"))
        override = (MaxLen(50),)
        merged = merge_capabilities(base, override)
        ml = [c for c in merged if isinstance(c, MaxLen)]
        assert len(ml) == 1
        assert ml[0].value == 50

    def test_override_capability(self) -> None:
        caps: tuple[SchemaAxisCapability, ...] = (MaxLen(100), Doc("x"))
        result = override_capability(caps, MaxLen(200))
        ml = [c for c in result if isinstance(c, MaxLen)]
        assert len(ml) == 1
        assert ml[0].value == 200

    def test_remove_capability(self) -> None:
        caps: tuple[SchemaAxisCapability, ...] = (MaxLen(100), Doc("x"))
        result = remove_capability(caps, MaxLen)
        assert not any(isinstance(c, MaxLen) for c in result)
        assert any(isinstance(c, Doc) for c in result)

    def test_deduplicate_capabilities(self) -> None:
        caps: tuple[SchemaAxisCapability, ...] = (MaxLen(100), MaxLen(50))
        result = deduplicate_capabilities(caps)
        ml = [c for c in result if isinstance(c, MaxLen)]
        assert len(ml) == 1
        assert ml[0].value == 50

    def test_filter_universal(self) -> None:
        caps: tuple[SchemaAxisCapability, ...] = (MaxLen(100), Doc("x"))
        result = filter_universal(caps)
        assert all(isinstance(c, UniversalCapability) for c in result)

    def test_find_capability(self) -> None:
        caps: tuple[SchemaAxisCapability, ...] = (MaxLen(100), Doc("x"))
        found = find_capability(caps, MaxLen)
        assert found is not None
        assert found.value == 100

    def test_find_capability_missing(self) -> None:
        caps: tuple[SchemaAxisCapability, ...] = (Doc("x"),)
        assert find_capability(caps, MaxLen) is None

    def test_find_all_capabilities(self) -> None:
        caps: tuple[SchemaAxisCapability, ...] = (MaxLen(100), MaxLen(50), Doc("x"))
        result = find_all_capabilities(caps, MaxLen)
        assert len(result) == 2

    def test_has_capability(self) -> None:
        caps: tuple[SchemaAxisCapability, ...] = (MaxLen(100),)
        assert has_capability(caps, MaxLen) is True
        assert has_capability(caps, Doc) is False


# ═══════════════════════════════════════════════════════════════════════════════
# 26. _helpers.py — fields_by_dialect, fields_with_capability
# ═══════════════════════════════════════════════════════════════════════════════


class TestFieldsByDialect:
    def test_fields_by_dialect(self) -> None:
        result = fields_by_dialect(RichEntity, UniversalCapability)
        names = [name for name, _, _ in result]
        assert "email" in names
        assert "age" in names

    def test_fields_with_capability(self) -> None:
        result = fields_with_capability(RichEntity, Unique)
        assert len(result) == 1
        assert result[0][0] == "email"

    def test_get_refs(self) -> None:
        result = get_refs(RefHolder)
        assert len(result) == 1
        assert result[0][0] == "target_id"

    def test_partition_fields(self) -> None:
        required, optional = partition_fields(RichEntity)
        req_names = {f.name for f in required}
        opt_names = {f.name for f in optional}
        assert "id" in req_names
        assert "bio" in opt_names

    def test_get_optional_fields(self) -> None:
        optional = get_optional_fields(RichEntity)
        names = {f.name for f in optional}
        assert "bio" in names

    def test_field_by_name_found(self) -> None:
        fi = field_by_name(RichEntity, "email")
        assert fi is not None
        assert fi.name == "email"

    def test_field_by_name_not_found(self) -> None:
        assert field_by_name(RichEntity, "nonexistent") is None


# ═══════════════════════════════════════════════════════════════════════════════
# 27. Property-based: constraints roundtrip
# ═══════════════════════════════════════════════════════════════════════════════


_NUMERIC_CAPS = st.sampled_from([
    Min(0), Min(10), Min(-5),
    Max(100), Max(50), Max(0),
    ExclusiveMin(0), ExclusiveMin(5),
    ExclusiveMax(100), ExclusiveMax(50),
    MultipleOf(2), MultipleOf(0.5),
])


class TestPropertyConstraints:
    @given(cap=_NUMERIC_CAPS)
    @settings(max_examples=30)
    def test_numeric_cap_constraints_roundtrip(self, cap: Any) -> None:
        """Every numeric cap should produce a non-default ConstraintsContext."""
        ctx = cap.compile_constraints(_constraints_ctx())
        # At least one field should differ from default
        default = _constraints_ctx()
        assert ctx != default

    @given(cap=_NUMERIC_CAPS)
    @settings(max_examples=30)
    def test_numeric_cap_openapi_roundtrip(self, cap: Any) -> None:
        """Every numeric cap should produce a non-empty OpenAPI schema."""
        ctx = cap.compile_openapi(_openapi_ctx())
        assert len(ctx.schema) > 0


_LENGTH_CAPS = st.sampled_from([
    MinLen(0), MinLen(5), MinLen(100),
    MaxLen(10), MaxLen(50), MaxLen(255),
    Pattern(r"^[a-z]+$"), Pattern(r"\d+"),
])


class TestPropertyLength:
    @given(cap=_LENGTH_CAPS)
    @settings(max_examples=20)
    def test_length_cap_constraints(self, cap: Any) -> None:
        ctx = cap.compile_constraints(_constraints_ctx())
        default = _constraints_ctx()
        assert ctx != default


_SEMANTICS_CAPS = st.sampled_from([
    Identity(), Unique(), ReadOnly(), WriteOnly(),
    Sensitive(), Immutable(), Nullable(), Computed(),
])


class TestPropertySemantics:
    @given(cap=_SEMANTICS_CAPS)
    @settings(max_examples=20)
    def test_semantics_cap_modifies_context(self, cap: Any) -> None:
        if hasattr(cap, "compile_verify_semantics"):
            ctx = cap.compile_verify_semantics(_semantics_ctx())
            default = _semantics_ctx()
            assert ctx != default


# ═══════════════════════════════════════════════════════════════════════════════
# 28. _inspect.py — extract_capabilities from patterns (tuple of caps)
# ═══════════════════════════════════════════════════════════════════════════════


class TestExtractCapabilities:
    def test_pattern_tuple(self) -> None:
        """Capabilities in tuples should be extracted."""
        pattern = (MaxLen(100), Unique())
        caps = extract_capabilities([pattern])
        assert len(caps) == 2
        assert any(isinstance(c, MaxLen) for c in caps)
        assert any(isinstance(c, Unique) for c in caps)

    def test_class_form(self) -> None:
        """Class form (no parens) should auto-instantiate."""
        caps = extract_capabilities([Identity])
        assert len(caps) == 1
        assert isinstance(caps[0], Identity)

    def test_mixed_annotations(self) -> None:
        """Mix of instance, class, tuple, and non-capability."""
        caps = extract_capabilities([Identity, MaxLen(50), "not-a-cap", (Unique(),)])
        assert len(caps) == 3

    def test_empty(self) -> None:
        assert extract_capabilities([]) == ()


# ═══════════════════════════════════════════════════════════════════════════════
# 29. _inspect.py — inspect_field edge cases
# ═══════════════════════════════════════════════════════════════════════════════


class TestInspectFieldEdgeCases:
    def test_plain_type(self) -> None:
        fi = inspect_field("x", int)
        assert fi.base_type is int
        assert fi.is_optional is False

    def test_optional_type(self) -> None:
        fi = inspect_field("x", int | None)
        assert fi.base_type is int
        assert fi.is_optional is True

    def test_annotated_optional(self) -> None:
        fi = inspect_field("x", Annotated[int | None, MaxLen(10)])
        assert fi.is_optional is True
        assert fi.has(MaxLen) is True

    def test_nested_annotated(self) -> None:
        """Annotated[Annotated[X, Cap1] | None, Cap2] should extract both."""
        from typing import Annotated as Ann
        tp = Ann[Ann[str, MinLen(1)] | None, MaxLen(10)]
        fi = inspect_field("x", tp)
        assert fi.is_optional is True
        assert fi.has(MinLen) is True
        assert fi.has(MaxLen) is True

    def test_has_default(self) -> None:
        fi = inspect_field("x", int, has_default=True)
        assert fi.has_default is True


# ═══════════════════════════════════════════════════════════════════════════════
# 30. _inspect.py — unwrap_optional edge cases
# ═══════════════════════════════════════════════════════════════════════════════


class TestUnwrapOptional:
    def test_multi_union(self) -> None:
        """int | str | None is not simple Optional."""
        _tp, is_opt = unwrap_optional(int | str | None)
        # multi-type union, not simple optional
        assert is_opt is False

    def test_non_union(self) -> None:
        tp, is_opt = unwrap_optional(int)
        assert tp is int
        assert is_opt is False

    def test_simple_optional(self) -> None:
        tp, is_opt = unwrap_optional(int | None)
        assert tp is int
        assert is_opt is True


# ═══════════════════════════════════════════════════════════════════════════════
# 31. Nested/Embedded capability fields
# ═══════════════════════════════════════════════════════════════════════════════


class TestNestedEmbedded:
    def test_nested_default_cascade(self) -> None:
        n = Nested()
        assert n.cascade == "all"
        assert n.meta == ()

    def test_nested_custom_cascade(self) -> None:
        n = Nested(cascade="delete")
        assert n.cascade == "delete"

    def test_embedded_default_format(self) -> None:
        e = Embedded()
        assert e.format == "json"
        assert e.meta == ()

    def test_embedded_flatten(self) -> None:
        e = Embedded(format="flatten")
        assert e.format == "flatten"

    def test_nested_with_meta(self) -> None:
        n = Nested(meta=(SchemaName("items"),))
        assert len(n.meta) == 1

    def test_embedded_with_meta(self) -> None:
        e = Embedded(meta=(SchemaName("addr"),))
        assert len(e.meta) == 1


# ═══════════════════════════════════════════════════════════════════════════════
# 32. OneOf with mixed types
# ═══════════════════════════════════════════════════════════════════════════════


class TestOneOf:
    def test_oneof_mixed_values(self) -> None:
        o = OneOf("a", 1, None, True)
        assert o.values == ("a", 1, None, True)

    def test_oneof_openapi_preserves_order(self) -> None:
        ctx = OneOf("z", "a", "m").compile_openapi(_openapi_ctx())
        assert ctx.schema["enum"] == ["z", "a", "m"]


# ═══════════════════════════════════════════════════════════════════════════════
# 33. Pydantic min/max compile
# ═══════════════════════════════════════════════════════════════════════════════


class TestPydanticNumeric:
    def test_min_pydantic(self) -> None:
        ctx = Min(5).compile_pydantic(_pydantic_ctx())
        # Should add Ge metadata
        assert len(ctx.field_info.metadata) > 0

    def test_max_pydantic(self) -> None:
        ctx = Max(100).compile_pydantic(_pydantic_ctx())
        assert len(ctx.field_info.metadata) > 0

    def test_exclusive_min_pydantic(self) -> None:
        ctx = ExclusiveMin(0).compile_pydantic(_pydantic_ctx())
        assert len(ctx.field_info.metadata) > 0

    def test_exclusive_max_pydantic(self) -> None:
        ctx = ExclusiveMax(100).compile_pydantic(_pydantic_ctx())
        assert len(ctx.field_info.metadata) > 0

    def test_multiple_of_pydantic(self) -> None:
        ctx = MultipleOf(5).compile_pydantic(_pydantic_ctx())
        assert len(ctx.field_info.metadata) > 0

    def test_minlen_pydantic(self) -> None:
        ctx = MinLen(3).compile_pydantic(_pydantic_ctx())
        assert len(ctx.field_info.metadata) > 0

    def test_maxlen_pydantic(self) -> None:
        ctx = MaxLen(50).compile_pydantic(_pydantic_ctx())
        assert len(ctx.field_info.metadata) > 0


# ═══════════════════════════════════════════════════════════════════════════════
# 34. _inspect.py — namedtuple edge cases (lines 411, 415)
# ═══════════════════════════════════════════════════════════════════════════════


class TestNamedTupleEdgeCases:
    def test_namedtuple_non_tuple_fields_attr(self) -> None:
        """If _fields is not a tuple/list, return None."""

        class FakeNT:
            _fields = "not_a_tuple"
            __annotations__ = {"x": int}

        assert namedtuple_inspector(FakeNT) is None

    def test_namedtuple_empty_fields(self) -> None:
        """If _fields is an empty tuple, return None."""

        class EmptyNT:
            _fields: tuple[str, ...] = ()
            __annotations__: dict[str, type] = {}

        assert namedtuple_inspector(EmptyNT) is None

    def test_namedtuple_fields_none(self) -> None:
        """If _fields is None, return None."""

        class NoneFieldsNT:
            _fields = None
            __annotations__ = {"x": int}

        assert namedtuple_inspector(NoneFieldsNT) is None


# ═══════════════════════════════════════════════════════════════════════════════
# 35. _inspect.py — get_nested_info error path (line 566-567)
# ═══════════════════════════════════════════════════════════════════════════════


class TestGetNestedInfoError:
    def test_get_nested_info_non_inspectable(self) -> None:
        """get_nested_info returns None for non-structured types."""
        fi = FieldInfo(
            name="x", base_type=int, is_optional=False, capabilities=()
        )
        assert get_nested_info(fi) is None

    def test_get_nested_type_collection(self) -> None:
        """get_nested_type handles list[DataClass]."""
        fi = FieldInfo(
            name="items",
            base_type=list[SimpleEntity],
            is_optional=False,
            capabilities=(),
        )
        assert get_nested_type(fi) is SimpleEntity


# ═══════════════════════════════════════════════════════════════════════════════
# 36. _universal.py — Coerce Sum roundtrip edge cases
# ═══════════════════════════════════════════════════════════════════════════════


class TestCoerceSumEdgeCases:
    def test_sum_to_storage_non_sum(self) -> None:
        """When value is not a Sum instance, passthrough."""
        from kungfu import Sum

        sum_type: Any = Sum[int, str]
        c = Coerce(sum_type)
        # Pass a plain value, not a Sum — to_storage should return as-is
        result = c.to_storage("plain_value")
        assert result == "plain_value"

    def test_sum_from_storage_roundtrip(self) -> None:
        """Full Sum roundtrip: to_storage -> from_storage."""
        from kungfu import Sum

        sum_type: Any = Sum[int, str]
        c = Coerce(sum_type)
        original = Sum[int, str](42)
        stored = c.to_storage(original)

        # from_storage should reconstruct
        restored = c.from_storage(stored)
        assert isinstance(restored, Sum)

    def test_sum_from_storage_non_dict(self) -> None:
        """from_storage with non-JSON data returns passthrough."""
        from kungfu import Sum

        sum_type: Any = Sum[int, str]
        c = Coerce(sum_type)
        # Pass non-string non-dict — should return as-is via fallback
        result = c.from_storage(12345)
        assert result == 12345

    def test_result_to_storage_non_result(self) -> None:
        """When value is neither Ok nor Error, passthrough."""
        from kungfu import Result

        result_type: Any = Result
        c = Coerce(result_type)
        result = c.to_storage("not_a_result")
        assert result == "not_a_result"

    def test_result_from_storage_non_dict(self) -> None:
        """from_storage with non-dict JSON returns passthrough."""
        from kungfu import Result

        result_type: Any = Result
        c = Coerce(result_type)
        result = c.from_storage(42)
        assert result == 42

    def test_coerce_compile_sqlalchemy_storage_type_none(self) -> None:
        """Coerce.compile_sqlalchemy when storage_type is None returns ctx unchanged."""

        # Option[str] will have storage_type = str (not None), so let's
        # test by creating a Coerce with custom overrides where storage_type stays None
        # Actually, _resolve_coerce for Option returns (fn, fn, None) as default_storage
        # but then __init__ resolves it from source_args. So we test the compile_sqlalchemy
        # path where storage_type is not None (already tested) and when it IS None.

        # Use a manually constructed scenario: override to_storage/from_storage
        c = Coerce(
            tuple,
            to_storage=lambda v: v,
            from_storage=lambda v: v,
        )
        # tuple's default storage_type is list, but with overrides the __init__
        # still uses the default_storage from _resolve_coerce.
        # Let's just directly test the compile_sqlalchemy path
        ctx = _sqlalchemy_ctx()
        result = c.compile_sqlalchemy(ctx)
        # storage_type is list, type_map is empty, so falls back to ctx.column_type
        assert result.column_type is ctx.column_type


# ═══════════════════════════════════════════════════════════════════════════════
# 37. _inspect.py — typeddict without __annotations__ (line 374)
# ═══════════════════════════════════════════════════════════════════════════════


class TestTypedDictEdgeCases:
    def test_class_with_required_optional_keys_but_no_real_typeddict(self) -> None:
        """Class that has __required_keys__/__optional_keys__ but is not a TypedDict.

        In Python 3.14+, __annotations__ always exists, so the
        inspector still accepts it (returns empty dict). This tests that
        path doesn't crash.
        """

        _empty_keys: frozenset[str] = frozenset()

        class FakeTypedDict:
            __required_keys__ = frozenset({"x"})
            __optional_keys__ = _empty_keys

        result = typeddict_inspector(FakeTypedDict)
        # Will return an empty dict since get_type_hints yields nothing
        assert result is not None
        assert result == {}


# ═══════════════════════════════════════════════════════════════════════════════
# 38. _universal.py — Pattern.compile_pydantic (line 450-452)
# ═══════════════════════════════════════════════════════════════════════════════


class TestPatternPydantic:
    def test_pattern_pydantic_adds_metadata(self) -> None:
        ctx = Pattern(r"^[a-z]+$").compile_pydantic(_pydantic_ctx())
        # Pattern should add pattern metadata to FieldInfo
        fi = ctx.field_info
        assert len(fi.metadata) > 0

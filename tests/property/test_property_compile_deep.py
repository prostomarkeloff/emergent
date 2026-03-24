# pyright: reportPrivateUsage=false
"""Property-based and deep unit tests for wire/compile pure-logic modules.

Covers uncovered paths in:
  - _schema.py: type_to_json_schema, _structured_type_to_json_schema,
                assemble_openapi, to_openapi_schema, to_json_schema,
                _convert_openapi_to_json_schema
  - _explain.py: explain, explain_field, explain_type, trace_dict, field_dict,
                 type_dict, changed_fields, active_capabilities
  - _generate.py: assemble_pydantic, to_pydantic, assemble_argparse, to_argparse_args
  - _lifetime.py: ScopeLayer, Tier
  - _capabilities.py: fold_handler_runtime, apply_response_capabilities,
                      _merge_openapi, _update_refs
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Annotated, Any, Optional

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from emergent.wire.compile._core import Axes
from emergent.wire.compile._schema import (
    type_to_json_schema,
    DEFAULT_JSON_TYPE_MAP,
    _structured_type_to_json_schema,
    _convert_openapi_to_json_schema,
    to_openapi_schema,
    to_json_schema,
)
from emergent.wire.compile._explain import (
    explain,
    explain_field,
    explain_type,
    trace_dict,
    field_dict,
    type_dict,
    changed_fields,
    active_capabilities,
    get_field_trace,
    get_phase_trace,
)
from emergent.wire.compile._generate import (
    to_pydantic,
    to_argparse_args,
    assemble_pydantic,
    assemble_argparse,
    ArgSpec,
)
from emergent.wire.compile._lifetime import (
    Tier,
    App,
    Request,
    ScopeLayer,
)
from emergent.wire.compile._capabilities import (
    fold_handler_runtime,
    apply_response_capabilities,
    _merge_openapi,
    _update_refs,
)
from emergent.wire.axis._capability import HandlerRuntimeContext
from emergent.wire.axis.schema import (
    Identity,
    MaxLen,
    MinLen,
    Min,
    Max,
    Doc,
    Unique,
    Pattern,
    OneOf,
    Alias,
)
from emergent.wire.compile._phase import (
    PYDANTIC_PHASE,
    ARGPARSE_PHASE,
    SchemaCompiler,
)


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_names(tags: Any) -> list[str]:
    """Extract tag names from a list of tag dicts."""
    return [t["name"] for t in tags]


# ---------------------------------------------------------------------------
# Test entities — module level
# ---------------------------------------------------------------------------


@dataclass
class SimpleEntity:
    name: str
    age: int


@dataclass
class AnnotatedEntity:
    email: Annotated[str, MaxLen(255), Doc("User email")]
    score: Annotated[int, Min(0), Max(100)]
    tag: Annotated[str, MinLen(1)]


@dataclass
class OptionalEntity:
    name: str
    nickname: str | None = None
    bio: Optional[str] = None


@dataclass
class ComplexEntity:
    id: Annotated[int, Identity]
    username: Annotated[str, Unique, MaxLen(64), MinLen(3)]
    email: Annotated[str, MaxLen(255), Pattern(r"^[\w.]+@[\w.]+$")]
    roles: list[str] = field(default_factory=lambda: list[str]())
    metadata: dict[str, int] = field(default_factory=lambda: dict[str, int]())


@dataclass
class NestedEntity:
    inner: SimpleEntity
    value: int = 0


@dataclass
class AliasedEntity:
    user_name: Annotated[str, Alias("userName")]
    user_age: int = 0


@dataclass
class ChoiceEntity:
    status: Annotated[str, OneOf("active", "inactive", "pending")]
    priority: int = 1


@dataclass
class EmptyEntity:
    pass


@dataclass
class ManyFieldsEntity:
    a: int
    b: str
    c: float
    d: bool
    e: int = 0
    f: str = "x"


# ---------------------------------------------------------------------------
# _schema.py tests
# ---------------------------------------------------------------------------


BASIC_TYPES = [int, str, float, bool, bytes, type(None)]


class TestTypeToJsonSchemaDeterminism:
    """Same type always produces the same schema."""

    @given(st.sampled_from(BASIC_TYPES))
    def test_same_type_same_schema(self, py_type: type) -> None:
        s1 = type_to_json_schema(py_type)
        s2 = type_to_json_schema(py_type)
        assert s1 == s2

    @given(st.sampled_from(BASIC_TYPES))
    def test_result_is_fresh_dict(self, py_type: type) -> None:
        """Each call returns a new dict (not shared mutable state)."""
        s1 = type_to_json_schema(py_type)
        s2 = type_to_json_schema(py_type)
        assert s1 is not s2

    def test_multiple_calls_consistency(self) -> None:
        for _ in range(20):
            assert type_to_json_schema(int) == {"type": "integer"}


class TestBasicTypeMapping:
    """int->integer, str->string, float->number, bool->boolean."""

    def test_int(self) -> None:
        assert type_to_json_schema(int) == {"type": "integer"}

    def test_str(self) -> None:
        assert type_to_json_schema(str) == {"type": "string"}

    def test_float(self) -> None:
        assert type_to_json_schema(float) == {"type": "number"}

    def test_bool(self) -> None:
        assert type_to_json_schema(bool) == {"type": "boolean"}

    def test_bytes(self) -> None:
        assert type_to_json_schema(bytes) == {"type": "string", "format": "byte"}

    def test_none_type(self) -> None:
        assert type_to_json_schema(type(None)) == {"type": "null"}


class TestOptionalHandling:
    """Optional[int] or int|None produces nullable schema."""

    def test_int_or_none(self) -> None:
        schema = type_to_json_schema(int | None)
        assert schema.get("nullable") is True
        assert schema["type"] == "integer"

    def test_str_or_none(self) -> None:
        schema = type_to_json_schema(str | None)
        assert schema.get("nullable") is True
        assert schema["type"] == "string"

    def test_float_or_none(self) -> None:
        schema = type_to_json_schema(float | None)
        assert schema.get("nullable") is True
        assert schema["type"] == "number"

    def test_bool_or_none(self) -> None:
        schema = type_to_json_schema(bool | None)
        assert schema.get("nullable") is True
        assert schema["type"] == "boolean"


class TestListType:
    """list[int] -> {"type":"array","items":{"type":"integer"}}"""

    def test_list_int(self) -> None:
        schema = type_to_json_schema(list[int])
        assert schema == {"type": "array", "items": {"type": "integer"}}

    def test_list_str(self) -> None:
        schema = type_to_json_schema(list[str])
        assert schema == {"type": "array", "items": {"type": "string"}}

    def test_list_of_list(self) -> None:
        schema = type_to_json_schema(list[list[int]])
        assert schema == {
            "type": "array",
            "items": {"type": "array", "items": {"type": "integer"}},
        }


class TestDictType:
    """dict[str,int] -> {"type":"object","additionalProperties":{"type":"integer"}}"""

    def test_dict_str_int(self) -> None:
        schema = type_to_json_schema(dict[str, int])
        assert schema == {
            "type": "object",
            "additionalProperties": {"type": "integer"},
        }

    def test_dict_str_str(self) -> None:
        schema = type_to_json_schema(dict[str, str])
        assert schema == {
            "type": "object",
            "additionalProperties": {"type": "string"},
        }


class TestUnionHandling:
    """int|str -> {"anyOf":[...]}"""

    def test_int_or_str(self) -> None:
        schema = type_to_json_schema(int | str)
        assert "anyOf" in schema
        types_in_union = [s["type"] for s in schema["anyOf"]]
        assert "integer" in types_in_union
        assert "string" in types_in_union

    def test_three_way_union(self) -> None:
        schema = type_to_json_schema(int | str | float)
        assert "anyOf" in schema
        assert len(schema["anyOf"]) == 3


class TestSetAndFrozenset:
    """set[T] and frozenset[T] produce array with uniqueItems."""

    def test_set_int(self) -> None:
        schema = type_to_json_schema(set[int])
        assert schema["type"] == "array"
        assert schema["uniqueItems"] is True
        assert schema["items"] == {"type": "integer"}

    def test_frozenset_str(self) -> None:
        schema = type_to_json_schema(frozenset[str])
        assert schema["type"] == "array"
        assert schema["uniqueItems"] is True
        assert schema["items"] == {"type": "string"}


class TestTupleType:
    """tuple[int, str] -> fixed-length array, tuple[int, ...] -> variable array."""

    def test_fixed_tuple(self) -> None:
        schema = type_to_json_schema(tuple[int, str])
        assert schema["type"] == "array"
        assert schema["minItems"] == 2
        assert schema["maxItems"] == 2
        assert len(schema["items"]) == 2

    def test_variable_tuple(self) -> None:
        schema = type_to_json_schema(tuple[int, ...])
        assert schema["type"] == "array"
        assert schema["items"] == {"type": "integer"}
        assert "minItems" not in schema


class TestNestedDataclass:
    """Dataclass with fields -> object schema with properties and required."""

    def test_simple_entity(self) -> None:
        schema = _structured_type_to_json_schema(SimpleEntity)
        assert schema["type"] == "object"
        assert "name" in schema["properties"]
        assert "age" in schema["properties"]
        assert "name" in schema["required"]
        assert "age" in schema["required"]

    def test_optional_entity(self) -> None:
        schema = _structured_type_to_json_schema(OptionalEntity)
        assert schema["type"] == "object"
        assert "name" in schema["properties"]
        # Optional fields should not be in required
        required = schema.get("required", [])
        assert "name" in required
        assert "nickname" not in required
        assert "bio" not in required

    def test_via_type_to_json_schema(self) -> None:
        """type_to_json_schema delegates to _structured_type_to_json_schema for dataclasses."""
        schema = type_to_json_schema(SimpleEntity)
        assert schema["type"] == "object"
        assert "name" in schema["properties"]


class TestCustomTypeMap:
    """Custom type map extends the defaults."""

    def test_custom_type(self) -> None:
        @dataclass
        class MySpecial:
            pass

        custom_map = {
            **DEFAULT_JSON_TYPE_MAP,
            MySpecial: {"type": "string", "format": "my-special"},
        }
        schema = type_to_json_schema(MySpecial, custom_map)
        assert schema == {"type": "string", "format": "my-special"}

    def test_override_builtin(self) -> None:
        custom_map = {
            **DEFAULT_JSON_TYPE_MAP,
            int: {"type": "string", "format": "int-as-string"},
        }
        schema = type_to_json_schema(int, custom_map)
        assert schema == {"type": "string", "format": "int-as-string"}


class TestUnknownTypeFallback:
    """Unknown types default to {"type": "object"}."""

    def test_unknown_class(self) -> None:
        class Opaque:
            pass

        schema = type_to_json_schema(Opaque)
        assert schema == {"type": "object"}


class TestToJsonSchemaRoundtrip:
    """to_json_schema produces valid schema dict with $schema key."""

    def test_simple_entity(self) -> None:
        axes = Axes.default()
        schema = to_json_schema(SimpleEntity, axes)
        assert "$schema" in schema
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert schema["type"] == "object"
        assert "properties" in schema

    def test_with_schema_id(self) -> None:
        axes = Axes.default()
        schema = to_json_schema(SimpleEntity, axes, schema_id="urn:simple")
        assert schema["$id"] == "urn:simple"

    def test_without_schema_id(self) -> None:
        axes = Axes.default()
        schema = to_json_schema(SimpleEntity, axes)
        assert "$id" not in schema


class TestConvertOpenapiToJsonSchema:
    """_convert_openapi_to_json_schema handles nullable conversion."""

    def test_nullable_string(self) -> None:
        schema: dict[str, object] = {"type": "string", "nullable": True}
        _convert_openapi_to_json_schema(schema)
        assert "nullable" not in schema
        assert schema["type"] == ["string", "null"]

    def test_nullable_integer(self) -> None:
        schema: dict[str, object] = {"type": "integer", "nullable": True}
        _convert_openapi_to_json_schema(schema)
        assert schema["type"] == ["integer", "null"]

    def test_no_nullable(self) -> None:
        schema: dict[str, object] = {"type": "string"}
        _convert_openapi_to_json_schema(schema)
        assert schema["type"] == "string"

    def test_nested_properties(self) -> None:
        schema: dict[str, object] = {
            "type": "object",
            "properties": {
                "name": {"type": "string", "nullable": True},
            },
        }
        _convert_openapi_to_json_schema(schema)
        props = schema["properties"]
        assert isinstance(props, dict)
        assert props["name"]["type"] == ["string", "null"]

    def test_nullable_type_already_list(self) -> None:
        schema: dict[str, Any] = {"type": ["string", "integer"], "nullable": True}
        _convert_openapi_to_json_schema(schema)
        assert "null" in schema["type"]

    def test_nullable_type_list_already_has_null(self) -> None:
        schema: dict[str, Any] = {"type": ["string", "null"], "nullable": True}
        _convert_openapi_to_json_schema(schema)
        # Should not duplicate null
        type_list: list[str] = schema["type"]
        assert isinstance(type_list, list)
        assert type_list.count("null") == 1

    def test_anyof_recursion(self) -> None:
        schema: dict[str, Any] = {
            "anyOf": [
                {"type": "string", "nullable": True},
                {"type": "integer"},
            ]
        }
        _convert_openapi_to_json_schema(schema)
        assert schema["anyOf"][0]["type"] == ["string", "null"]
        assert schema["anyOf"][1]["type"] == "integer"

    def test_items_recursion_dict(self) -> None:
        schema: dict[str, Any] = {
            "type": "array",
            "items": {"type": "string", "nullable": True},
        }
        _convert_openapi_to_json_schema(schema)
        assert schema["items"]["type"] == ["string", "null"]

    def test_items_recursion_list(self) -> None:
        schema: dict[str, Any] = {
            "type": "array",
            "items": [
                {"type": "string", "nullable": True},
                {"type": "integer"},
            ],
        }
        _convert_openapi_to_json_schema(schema)
        assert schema["items"][0]["type"] == ["string", "null"]

    def test_oneof_recursion(self) -> None:
        schema: dict[str, Any] = {
            "oneOf": [{"type": "string", "nullable": True}]
        }
        _convert_openapi_to_json_schema(schema)
        assert schema["oneOf"][0]["type"] == ["string", "null"]

    def test_allof_recursion(self) -> None:
        schema: dict[str, Any] = {
            "allOf": [{"type": "number", "nullable": True}]
        }
        _convert_openapi_to_json_schema(schema)
        assert schema["allOf"][0]["type"] == ["number", "null"]


class TestAssembleOpenapi:
    """assemble_openapi compiles entity through OPENAPI_PHASE."""

    def test_simple_entity(self) -> None:
        axes = Axes.default()
        schema = to_openapi_schema(SimpleEntity, axes)
        assert schema["type"] == "object"
        assert "name" in schema["properties"]
        assert "age" in schema["properties"]
        assert "name" in schema["required"]

    def test_annotated_entity(self) -> None:
        axes = Axes.default()
        schema = to_openapi_schema(AnnotatedEntity, axes)
        assert schema["type"] == "object"
        props = schema["properties"]
        assert "email" in props
        assert "score" in props
        # MaxLen(255) should set maxLength
        assert props["email"].get("maxLength") == 255

    def test_optional_entity_required(self) -> None:
        axes = Axes.default()
        schema = to_openapi_schema(OptionalEntity, axes)
        required = schema.get("required", [])
        assert "name" in required
        assert "nickname" not in required

    def test_empty_entity(self) -> None:
        axes = Axes.default()
        schema = to_openapi_schema(EmptyEntity, axes)
        assert schema["type"] == "object"
        assert schema["properties"] == {}
        # No required key when empty
        assert "required" not in schema

    def test_complex_entity_constraints(self) -> None:
        axes = Axes.default()
        schema = to_openapi_schema(ComplexEntity, axes)
        props = schema["properties"]
        assert props["username"].get("maxLength") == 64
        assert props["email"].get("maxLength") == 255


# ---------------------------------------------------------------------------
# _explain.py tests
# ---------------------------------------------------------------------------


class TestTraceDict:
    """trace_dict returns structured data after traced compilation."""

    def test_traced_compilation_produces_events(self) -> None:
        axes = Axes.traced()
        to_pydantic(SimpleEntity, axes)
        data = trace_dict(axes)
        assert data != {}
        assert "types" in data
        assert len(data["types"]) > 0

    def test_non_traced_returns_empty(self) -> None:
        axes = Axes.default()
        data = trace_dict(axes)
        assert data == {}

    def test_trace_has_correct_class_name(self) -> None:
        axes = Axes.traced()
        to_pydantic(SimpleEntity, axes)
        data = trace_dict(axes)
        cls_names = [t["class"] for t in data["types"]]
        assert "SimpleEntity" in cls_names

    def test_trace_fields_match_entity(self) -> None:
        axes = Axes.traced()
        to_pydantic(SimpleEntity, axes)
        data = trace_dict(axes)
        type_data = data["types"][0]
        field_names = [f["field"] for f in type_data["fields"]]
        assert "name" in field_names
        assert "age" in field_names


class TestExplain:
    """explain() returns non-empty human-readable string."""

    def test_explain_traced(self) -> None:
        axes = Axes.traced()
        to_pydantic(SimpleEntity, axes)
        result = explain(axes)
        assert isinstance(result, str)
        assert len(result) > 0
        assert "SimpleEntity" in result

    def test_explain_non_traced(self) -> None:
        axes = Axes.default()
        result = explain(axes)
        assert "tracing not enabled" in result

    def test_explain_contains_field_names(self) -> None:
        axes = Axes.traced()
        to_pydantic(AnnotatedEntity, axes)
        result = explain(axes)
        assert "email" in result
        assert "score" in result


class TestExplainField:
    """explain_field() returns field-specific trace info."""

    def test_existing_field(self) -> None:
        axes = Axes.traced()
        to_pydantic(SimpleEntity, axes)
        result = explain_field(axes, "name")
        assert isinstance(result, str)
        assert "name" in result

    def test_nonexistent_field(self) -> None:
        axes = Axes.traced()
        to_pydantic(SimpleEntity, axes)
        result = explain_field(axes, "nonexistent")
        assert "not found" in result

    def test_non_traced(self) -> None:
        axes = Axes.default()
        result = explain_field(axes, "name")
        assert "not found" in result


class TestExplainType:
    """explain_type() returns type-specific trace info."""

    def test_existing_type(self) -> None:
        axes = Axes.traced()
        to_pydantic(SimpleEntity, axes)
        result = explain_type(axes, "SimpleEntity")
        assert isinstance(result, str)
        assert "SimpleEntity" in result

    def test_nonexistent_type(self) -> None:
        axes = Axes.traced()
        to_pydantic(SimpleEntity, axes)
        result = explain_type(axes, "NonExistent")
        assert "not found" in result


class TestFieldDict:
    """field_dict() returns structured data for a single field."""

    def test_existing_field(self) -> None:
        axes = Axes.traced()
        to_pydantic(AnnotatedEntity, axes)
        d = field_dict(axes, "email")
        assert d is not None
        assert d["field"] == "email"
        assert "capabilities" in d
        assert "phases" in d

    def test_nonexistent_field(self) -> None:
        axes = Axes.traced()
        to_pydantic(SimpleEntity, axes)
        d = field_dict(axes, "nonexistent")
        assert d is None

    def test_non_traced(self) -> None:
        axes = Axes.default()
        d = field_dict(axes, "name")
        assert d is None


class TestTypeDict:
    """type_dict() returns structured data for a single type."""

    def test_existing_type(self) -> None:
        axes = Axes.traced()
        to_pydantic(SimpleEntity, axes)
        d = type_dict(axes, "SimpleEntity")
        assert d is not None
        assert d["class"] == "SimpleEntity"
        assert "fields" in d

    def test_nonexistent_type(self) -> None:
        axes = Axes.traced()
        to_pydantic(SimpleEntity, axes)
        d = type_dict(axes, "NoSuch")
        assert d is None

    def test_non_traced(self) -> None:
        axes = Axes.default()
        d = type_dict(axes, "SimpleEntity")
        assert d is None


class TestChangedFields:
    """changed_fields returns subset of all fields."""

    def test_annotated_entity_has_changed(self) -> None:
        axes = Axes.traced()
        to_pydantic(AnnotatedEntity, axes)
        # OpenAPIContext is one of the phase names used
        changed = changed_fields(axes, "OpenAPIContext")
        all_fields = ["email", "score", "tag"]
        # changed is a subset of all fields
        for f in changed:
            assert f in all_fields

    def test_simple_entity_may_have_no_changes(self) -> None:
        axes = Axes.traced()
        # SimpleEntity has no capabilities, so no field should be changed
        # by any schema capability in OpenAPI phase
        to_openapi_schema(SimpleEntity, axes)
        changed = changed_fields(axes, "OpenAPIContext")
        # SimpleEntity fields have no capabilities - nothing to change
        assert isinstance(changed, list)

    def test_non_traced(self) -> None:
        axes = Axes.default()
        changed = changed_fields(axes, "OpenAPIContext")
        assert changed == []

    def test_changed_is_subset_of_all(self) -> None:
        axes = Axes.traced()
        to_pydantic(ComplexEntity, axes)
        changed = changed_fields(axes, "PydanticContext")
        all_field_names = {"id", "username", "email", "roles", "metadata"}
        assert set(changed).issubset(all_field_names)


class TestActiveCapabilities:
    """active_capabilities returns subset of all capabilities."""

    def test_annotated_field(self) -> None:
        axes = Axes.traced()
        to_pydantic(AnnotatedEntity, axes)
        active = active_capabilities(axes, "email")
        # active should be a list of capability type names
        assert isinstance(active, list)
        # MaxLen and Doc are on email
        # active capabilities are those that actually changed context

    def test_no_capabilities_field(self) -> None:
        axes = Axes.traced()
        to_pydantic(SimpleEntity, axes)
        active = active_capabilities(axes, "name")
        # name has no capabilities, so active should be empty
        assert active == []

    def test_nonexistent_field(self) -> None:
        axes = Axes.traced()
        to_pydantic(SimpleEntity, axes)
        active = active_capabilities(axes, "nonexistent")
        assert active == []

    def test_non_traced(self) -> None:
        axes = Axes.default()
        active = active_capabilities(axes, "name")
        assert active == []


class TestGetFieldTrace:
    """get_field_trace returns raw FieldTrace."""

    def test_existing(self) -> None:
        axes = Axes.traced()
        to_pydantic(SimpleEntity, axes)
        ft = get_field_trace(axes, "name")
        assert ft is not None
        assert ft.field_name == "name"

    def test_nonexistent(self) -> None:
        axes = Axes.traced()
        to_pydantic(SimpleEntity, axes)
        ft = get_field_trace(axes, "nope")
        assert ft is None


class TestGetPhaseTrace:
    """get_phase_trace returns raw FieldPhaseTrace."""

    def test_existing_phase(self) -> None:
        axes = Axes.traced()
        to_pydantic(SimpleEntity, axes)
        fpt = get_phase_trace(axes, "name", "PydanticContext")
        assert fpt is not None
        assert fpt.phase == "PydanticContext"

    def test_nonexistent_phase(self) -> None:
        axes = Axes.traced()
        to_pydantic(SimpleEntity, axes)
        fpt = get_phase_trace(axes, "name", "NonExistentPhase")
        assert fpt is None


# ---------------------------------------------------------------------------
# _generate.py tests
# ---------------------------------------------------------------------------


class TestToPydantic:
    """to_pydantic produces valid Pydantic model."""

    def test_returns_type(self) -> None:
        from pydantic import BaseModel

        axes = Axes.default()
        Model = to_pydantic(SimpleEntity, axes)
        assert isinstance(Model, type)
        assert issubclass(Model, BaseModel)

    def test_model_name_matches_entity(self) -> None:
        axes = Axes.default()
        Model = to_pydantic(SimpleEntity, axes)
        assert Model.__name__ == "SimpleEntity"

    def test_model_has_same_fields(self) -> None:
        axes = Axes.default()
        Model = to_pydantic(SimpleEntity, axes)
        model_fields = set(Model.model_fields.keys())
        assert "name" in model_fields
        assert "age" in model_fields

    def test_annotated_entity_fields(self) -> None:
        axes = Axes.default()
        Model = to_pydantic(AnnotatedEntity, axes)
        model_fields = set(Model.model_fields.keys())
        assert model_fields == {"email", "score", "tag"}

    def test_optional_entity_defaults(self) -> None:
        axes = Axes.default()
        Model = to_pydantic(OptionalEntity, axes)
        # Should be able to create with defaults
        instance: Any = Model(name="test")
        assert instance.nickname is None
        assert instance.bio is None

    def test_model_validation(self) -> None:
        axes = Axes.default()
        Model = to_pydantic(SimpleEntity, axes)
        instance: Any = Model(name="Alice", age=30)
        assert instance.name == "Alice"
        assert instance.age == 30

    def test_complex_entity_all_fields(self) -> None:
        axes = Axes.default()
        Model = to_pydantic(ComplexEntity, axes)
        model_fields = set(Model.model_fields.keys())
        assert model_fields == {"id", "username", "email", "roles", "metadata"}

    def test_many_fields_entity(self) -> None:
        axes = Axes.default()
        Model = to_pydantic(ManyFieldsEntity, axes)
        assert len(Model.model_fields) == 6

    def test_pydantic_model_with_defaults(self) -> None:
        axes = Axes.default()
        Model = to_pydantic(ManyFieldsEntity, axes)
        instance: Any = Model(a=1, b="hi", c=3.14, d=True)
        assert instance.e == 0
        assert instance.f == "x"


class TestAssemblePydantic:
    """assemble_pydantic produces valid model from EntityCompilation."""

    def test_from_entity_compilation(self) -> None:
        from pydantic import BaseModel

        axes = Axes.default()
        ec = SchemaCompiler(phases=(PYDANTIC_PHASE,)).compile(SimpleEntity, axes)
        Model = assemble_pydantic(SimpleEntity, ec)
        assert issubclass(Model, BaseModel)
        assert set(Model.model_fields.keys()) == {"name", "age"}


class TestToArgparseArgs:
    """to_argparse_args produces ArgSpec list."""

    def test_returns_list(self) -> None:
        axes = Axes.default()
        specs = to_argparse_args(SimpleEntity, axes)
        assert isinstance(specs, list)
        assert len(specs) > 0

    def test_field_names_present(self) -> None:
        axes = Axes.default()
        specs = to_argparse_args(SimpleEntity, axes)
        dests = [s.dest for s in specs]
        assert "name" in dests
        assert "age" in dests

    def test_argspec_structure(self) -> None:
        axes = Axes.default()
        specs = to_argparse_args(SimpleEntity, axes)
        for spec in specs:
            assert isinstance(spec, ArgSpec)
            assert isinstance(spec.name, str)
            assert isinstance(spec.dest, str)
            assert isinstance(spec.kwargs, dict)

    def test_optional_fields_are_flags(self) -> None:
        axes = Axes.default()
        specs = to_argparse_args(OptionalEntity, axes)
        optional_specs = [s for s in specs if s.dest in ("nickname", "bio")]
        for s in optional_specs:
            # Optional fields should be non-positional (flags with --)
            assert not s.is_positional

    def test_required_fields_are_positional(self) -> None:
        axes = Axes.default()
        specs = to_argparse_args(SimpleEntity, axes)
        for s in specs:
            # Required fields without defaults should be positional
            assert s.is_positional

    def test_many_fields(self) -> None:
        axes = Axes.default()
        specs = to_argparse_args(ManyFieldsEntity, axes)
        assert len(specs) == 6


class TestAssembleArgparse:
    """assemble_argparse produces specs from EntityCompilation."""

    def test_from_entity_compilation(self) -> None:
        axes = Axes.default()
        ec = SchemaCompiler(phases=(ARGPARSE_PHASE,)).compile(SimpleEntity, axes)
        specs = assemble_argparse(SimpleEntity, ec)
        assert len(specs) == 2
        dests = {s.dest for s in specs}
        assert dests == {"name", "age"}


# ---------------------------------------------------------------------------
# _lifetime.py tests
# ---------------------------------------------------------------------------


class TestTier:
    """Tier hierarchy and immutability."""

    def test_app_has_no_parent(self) -> None:
        assert App.parent is None

    def test_request_parent_is_app(self) -> None:
        assert Request.parent is App

    def test_custom_tier_chain(self) -> None:
        t1 = Tier()
        t2 = Tier(parent=t1)
        t3 = Tier(parent=t2)
        assert t3.parent is t2
        assert t3.parent is not None
        assert t3.parent.parent is t1
        assert t3.parent.parent is not None
        assert t3.parent.parent.parent is None

    def test_tier_is_frozen(self) -> None:
        with pytest.raises(AttributeError):
            App.parent = Request  # type: ignore[misc]


class TestScopeLayer:
    """ScopeLayer immutability and tier chain walking."""

    def _make_scope_layer(self) -> ScopeLayer:
        """Build a minimal ScopeLayer for testing."""
        from emergent.graph._family import ScopeFamily

        family: ScopeFamily[Tier] = ScopeFamily()
        # We need a mock scope. Use a simple object.
        mock_scope = object()
        return ScopeLayer(
            scopes={App: mock_scope},  # type: ignore[dict-item]
            family=family,
            leaf=Request,
        )

    def test_with_scope_returns_new_object(self) -> None:
        layer = self._make_scope_layer()
        mock_scope2 = object()
        new_layer = layer.with_scope(Request, mock_scope2)  # type: ignore[arg-type]
        assert new_layer is not layer
        assert Request in new_layer.scopes
        assert Request not in layer.scopes

    def test_parent_walks_up(self) -> None:
        layer = self._make_scope_layer()
        # leaf is Request, parent is App; App is in scopes
        parent_scope = layer.parent
        assert parent_scope is layer.scopes[App]

    def test_parent_missing_raises(self) -> None:
        from emergent.graph._family import ScopeFamily

        family: ScopeFamily[Tier] = ScopeFamily()
        layer = ScopeLayer(
            scopes={},
            family=family,
            leaf=Request,
        )
        with pytest.raises(LookupError):
            _ = layer.parent

    def test_scope_layer_is_frozen(self) -> None:
        layer = self._make_scope_layer()
        with pytest.raises(AttributeError):
            layer.leaf = App  # type: ignore[misc]

    def test_with_scope_preserves_family(self) -> None:
        layer = self._make_scope_layer()
        mock = object()
        new_layer = layer.with_scope(Request, mock)  # type: ignore[arg-type]
        assert new_layer.family is layer.family

    def test_with_scope_preserves_leaf(self) -> None:
        layer = self._make_scope_layer()
        mock = object()
        new_layer = layer.with_scope(Request, mock)  # type: ignore[arg-type]
        assert new_layer.leaf is layer.leaf

    def test_deep_tier_chain_parent(self) -> None:
        """3-level hierarchy: only root scope exists, parent walks correctly."""
        from emergent.graph._family import ScopeFamily

        root = Tier()
        middle = Tier(parent=root)
        leaf = Tier(parent=middle)

        family: ScopeFamily[Tier] = ScopeFamily()
        root_scope = object()
        layer = ScopeLayer(
            scopes={root: root_scope},  # type: ignore[dict-item]
            family=family,
            leaf=leaf,
        )
        # Should walk leaf->middle->root and find root_scope
        assert layer.parent is root_scope


# ---------------------------------------------------------------------------
# _capabilities.py tests
# ---------------------------------------------------------------------------


class TestFoldHandlerRuntime:
    """fold_handler_runtime with empty capabilities."""

    def test_empty_caps_returns_default(self) -> None:
        ctx = fold_handler_runtime(())
        assert isinstance(ctx, HandlerRuntimeContext)
        assert ctx.enrichers == ()
        assert ctx.response_transforms == ()

    def test_result_is_handler_runtime_context(self) -> None:
        ctx = fold_handler_runtime(())
        assert isinstance(ctx, HandlerRuntimeContext)


class TestApplyResponseCapabilities:
    """apply_response_capabilities with empty caps is identity."""

    def test_empty_caps_identity(self) -> None:
        response = {"status": "ok"}
        result = apply_response_capabilities(response, ())
        assert result == response
        assert result is response

    def test_preserves_type(self) -> None:
        result = apply_response_capabilities(42, ())
        assert result == 42

    def test_string_response(self) -> None:
        result = apply_response_capabilities("hello", ())
        assert result == "hello"


class TestUpdateRefs:
    """_update_refs replaces $ref strings recursively."""

    def test_simple_ref(self) -> None:
        obj: dict[str, object] = {"$ref": "#/old/path"}
        _update_refs(obj, "#/old/path", "#/new/path")
        assert obj["$ref"] == "#/new/path"

    def test_no_match(self) -> None:
        obj: dict[str, object] = {"$ref": "#/other/path"}
        _update_refs(obj, "#/old/path", "#/new/path")
        assert obj["$ref"] == "#/other/path"

    def test_nested_dict(self) -> None:
        obj: dict[str, object] = {
            "schema": {"$ref": "#/old/path"},
        }
        _update_refs(obj, "#/old/path", "#/new/path")
        assert obj["schema"]["$ref"] == "#/new/path"  # type: ignore[index]

    def test_in_list(self) -> None:
        obj: dict[str, object] = {
            "items": [{"$ref": "#/old/path"}, {"$ref": "#/other"}],
        }
        _update_refs(obj, "#/old/path", "#/new/path")
        assert obj["items"][0]["$ref"] == "#/new/path"  # type: ignore[index]
        assert obj["items"][1]["$ref"] == "#/other"  # type: ignore[index]

    def test_deeply_nested(self) -> None:
        obj: dict[str, object] = {
            "a": {"b": {"c": {"$ref": "#/old/path"}}},
        }
        _update_refs(obj, "#/old/path", "#/new/path")
        assert obj["a"]["b"]["c"]["$ref"] == "#/new/path"  # type: ignore[index]

    def test_multiple_refs(self) -> None:
        obj: dict[str, object] = {
            "x": {"$ref": "#/old/path"},
            "y": {"$ref": "#/old/path"},
        }
        _update_refs(obj, "#/old/path", "#/new/path")
        assert obj["x"]["$ref"] == "#/new/path"  # type: ignore[index]
        assert obj["y"]["$ref"] == "#/new/path"  # type: ignore[index]

    def test_non_string_values_ignored(self) -> None:
        obj: dict[str, object] = {"$ref": 123}
        _update_refs(obj, "#/old/path", "#/new/path")
        assert obj["$ref"] == 123

    def test_empty_dict(self) -> None:
        obj: dict[str, object] = {}
        _update_refs(obj, "#/old/path", "#/new/path")
        assert obj == {}

    def test_list_at_top_level(self) -> None:
        obj: list[object] = [{"$ref": "#/old/path"}]
        _update_refs(obj, "#/old/path", "#/new/path")
        assert obj[0]["$ref"] == "#/new/path"  # type: ignore[index]


class TestMergeOpenapi:
    """_merge_openapi merges source OpenAPI into target."""

    def test_merge_paths(self) -> None:
        target: dict[str, object] = {"paths": {}, "tags": []}
        source: dict[str, object] = {
            "paths": {
                "/users": {
                    "get": {
                        "summary": "List users",
                        "responses": {"200": {"description": "OK"}},
                    }
                }
            },
        }
        _merge_openapi(target, source, "/api", "legacy")
        assert "/api/users" in target["paths"]  # type: ignore[operator]

    def test_merge_adds_source_tag(self) -> None:
        target: dict[str, object] = {"paths": {}, "tags": []}
        source: dict[str, object] = {"paths": {}}
        _merge_openapi(target, source, "/api", "myapp")
        tags: Any = target["tags"]
        assert isinstance(tags, list)
        tag_names = _extract_names(tags)
        assert "myapp" in tag_names

    def test_merge_definitions_to_components(self) -> None:
        target: dict[str, object] = {"paths": {}, "tags": []}
        source: dict[str, object] = {
            "paths": {},
            "definitions": {
                "User": {"type": "object", "properties": {"name": {"type": "string"}}},
            },
        }
        _merge_openapi(target, source, "/api", "legacy")
        assert "components" in target
        assert "schemas" in target["components"]  # type: ignore[operator]
        assert "LegacyUser" in target["components"]["schemas"]  # type: ignore[operator]

    def test_merge_with_base_path(self) -> None:
        target: dict[str, object] = {"paths": {}, "tags": []}
        source: dict[str, object] = {
            "basePath": "/v1",
            "paths": {
                "/items": {"get": {"summary": "Items"}},
            },
        }
        _merge_openapi(target, source, "/api", "svc")
        assert "/api/v1/items" in target["paths"]  # type: ignore[operator]

    def test_merge_swagger_body_param_to_request_body(self) -> None:
        target: dict[str, object] = {"paths": {}, "tags": []}
        source: dict[str, object] = {
            "paths": {
                "/create": {
                    "post": {
                        "parameters": [
                            {
                                "in": "body",
                                "name": "body",
                                "required": True,
                                "schema": {"type": "object"},
                            }
                        ],
                        "responses": {"201": {"description": "Created"}},
                    }
                }
            },
        }
        _merge_openapi(target, source, "/api", "svc")
        post_spec = target["paths"]["/api/create"]["post"]  # type: ignore[index]
        assert "requestBody" in post_spec
        assert "parameters" not in post_spec

    def test_merge_swagger_response_schema_to_content(self) -> None:
        target: dict[str, object] = {"paths": {}, "tags": []}
        source: dict[str, object] = {
            "paths": {
                "/item": {
                    "get": {
                        "responses": {
                            "200": {
                                "description": "OK",
                                "schema": {"type": "object"},
                            }
                        },
                    }
                }
            },
        }
        _merge_openapi(target, source, "/api", "svc")
        paths: Any = target["paths"]
        get_spec: Any = paths["/api/item"]["get"]
        resp_200: Any = get_spec["responses"]["200"]
        assert "content" in resp_200
        assert "schema" not in resp_200

    def test_merge_source_tags(self) -> None:
        target: dict[str, object] = {"paths": {}, "tags": []}
        source: dict[str, object] = {
            "paths": {},
            "tags": [
                {"name": "users", "description": "User endpoints"},
            ],
        }
        _merge_openapi(target, source, "/api", "svc")
        tags: Any = target["tags"]
        assert isinstance(tags, list)
        tag_names = _extract_names(tags)
        assert "svc:users" in tag_names


# ---------------------------------------------------------------------------
# Property-based tests using hypothesis
# ---------------------------------------------------------------------------


class TestPropertyBased:
    """Property-based tests using hypothesis for deeper coverage."""

    @given(st.sampled_from(BASIC_TYPES))
    def test_type_to_json_schema_always_returns_dict(self, py_type: type) -> None:
        result = type_to_json_schema(py_type)
        assert isinstance(result, dict)

    @given(st.sampled_from(BASIC_TYPES))
    def test_type_to_json_schema_has_type_key(self, py_type: type) -> None:
        result = type_to_json_schema(py_type)
        assert "type" in result

    @given(st.sampled_from(BASIC_TYPES))
    @settings(max_examples=30)
    def test_nullable_wrapping_preserves_type(self, py_type: type) -> None:
        """T|None should preserve the inner type's schema."""
        assume(py_type is not type(None))
        base_schema = type_to_json_schema(py_type)
        nullable_type = py_type | None
        nullable_schema = type_to_json_schema(nullable_type)
        assert nullable_schema.get("nullable") is True
        assert nullable_schema["type"] == base_schema["type"]

    @given(
        st.sampled_from(BASIC_TYPES),
        st.sampled_from(BASIC_TYPES),
    )
    @settings(max_examples=30)
    def test_union_of_two_different_types(self, t1: type, t2: type) -> None:
        """Union of two non-null types produces anyOf."""
        assume(t1 is not t2)
        assume(t1 is not type(None) and t2 is not type(None))
        union_type = t1 | t2
        schema = type_to_json_schema(union_type)
        # Two non-null types => anyOf with exactly 2 entries
        assert "anyOf" in schema
        assert len(schema["anyOf"]) == 2

    @given(st.sampled_from(BASIC_TYPES))
    def test_list_of_type_always_array(self, py_type: type) -> None:
        assume(py_type is not type(None))
        schema = type_to_json_schema(list[py_type])
        assert schema["type"] == "array"
        assert "items" in schema

    @given(st.sampled_from([SimpleEntity, AnnotatedEntity, OptionalEntity, ComplexEntity]))
    @settings(max_examples=10)
    def test_to_openapi_schema_always_object(self, cls: type) -> None:
        axes = Axes.default()
        schema = to_openapi_schema(cls, axes)
        assert schema["type"] == "object"
        assert "properties" in schema

    @given(st.sampled_from([SimpleEntity, AnnotatedEntity, OptionalEntity, ComplexEntity]))
    @settings(max_examples=10)
    def test_to_json_schema_has_dollar_schema(self, cls: type) -> None:
        axes = Axes.default()
        schema = to_json_schema(cls, axes)
        assert "$schema" in schema

    @given(st.sampled_from([SimpleEntity, AnnotatedEntity, OptionalEntity, ComplexEntity]))
    @settings(max_examples=10)
    def test_pydantic_model_has_correct_field_count(self, cls: type) -> None:
        from dataclasses import fields as dc_fields

        axes = Axes.default()
        Model = to_pydantic(cls, axes)
        expected = {f.name for f in dc_fields(cls)}
        actual = set(Model.model_fields.keys())
        assert actual == expected

    @given(st.sampled_from([SimpleEntity, AnnotatedEntity, OptionalEntity, ComplexEntity]))
    @settings(max_examples=10)
    def test_argparse_specs_dest_matches_fields(self, cls: type) -> None:
        from dataclasses import fields as dc_fields

        axes = Axes.default()
        specs = to_argparse_args(cls, axes)
        expected = {f.name for f in dc_fields(cls)}
        actual = {s.dest for s in specs}
        assert actual == expected

    @given(st.sampled_from([SimpleEntity, AnnotatedEntity, ComplexEntity]))
    @settings(max_examples=10)
    def test_traced_explain_non_empty(self, cls: type) -> None:
        axes = Axes.traced()
        to_pydantic(cls, axes)
        result = explain(axes)
        assert len(result) > 0

    @given(st.text(min_size=1, max_size=50))
    @settings(max_examples=20)
    def test_update_refs_with_random_keys(self, key: str) -> None:
        old_ref = f"#/definitions/{key}"
        new_ref = f"#/components/schemas/{key}"
        obj: dict[str, object] = {"$ref": old_ref}
        _update_refs(obj, old_ref, new_ref)
        assert obj["$ref"] == new_ref


# ---------------------------------------------------------------------------
# Edge cases and cross-module integration
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge cases and cross-module interactions."""

    def test_empty_entity_pydantic(self) -> None:
        """EmptyEntity with zero fields produces valid model."""
        axes = Axes.default()
        Model = to_pydantic(EmptyEntity, axes)
        instance = Model()
        assert instance is not None

    def test_empty_entity_argparse(self) -> None:
        axes = Axes.default()
        specs = to_argparse_args(EmptyEntity, axes)
        assert specs == []

    def test_empty_entity_openapi(self) -> None:
        axes = Axes.default()
        schema = to_openapi_schema(EmptyEntity, axes)
        assert schema == {"type": "object", "properties": {}}

    def test_traced_does_not_change_compilation_result(self) -> None:
        """Tracing should not affect the resulting model."""
        axes_normal = Axes.default()
        axes_traced = Axes.traced()
        Model1 = to_pydantic(SimpleEntity, axes_normal)
        Model2 = to_pydantic(SimpleEntity, axes_traced)
        assert set(Model1.model_fields.keys()) == set(Model2.model_fields.keys())

    def test_traced_does_not_change_openapi_result(self) -> None:
        axes_normal = Axes.default()
        axes_traced = Axes.traced()
        s1 = to_openapi_schema(AnnotatedEntity, axes_normal)
        s2 = to_openapi_schema(AnnotatedEntity, axes_traced)
        assert s1 == s2

    def test_traced_does_not_change_json_schema_result(self) -> None:
        axes_normal = Axes.default()
        axes_traced = Axes.traced()
        s1 = to_json_schema(SimpleEntity, axes_normal)
        s2 = to_json_schema(SimpleEntity, axes_traced)
        assert s1 == s2

    def test_convert_openapi_nullable_null_type_noop(self) -> None:
        """nullable on type=null should not create double null."""
        schema: dict[str, object] = {"type": "null", "nullable": True}
        _convert_openapi_to_json_schema(schema)
        # nullable removed, but type was null so nothing changes
        assert "nullable" not in schema
        assert schema["type"] == "null"

    def test_choice_entity_openapi(self) -> None:
        axes = Axes.default()
        schema = to_openapi_schema(ChoiceEntity, axes)
        props = schema["properties"]
        status_schema = props["status"]
        assert "enum" in status_schema
        assert set(status_schema["enum"]) == {"active", "inactive", "pending"}

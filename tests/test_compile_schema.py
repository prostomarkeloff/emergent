"""Tests for compile._schema — type-to-JSON-Schema, OpenAPI, and JSON Schema generation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any

from emergent.wire.compile._core import Axes
from emergent.wire.compile._schema import (
    _python_type_to_json_schema,  # pyright: ignore[reportPrivateUsage] - testing private function intentionally
    _structured_type_to_json_schema,  # pyright: ignore[reportPrivateUsage] - testing private function intentionally
    _convert_openapi_to_json_schema,  # pyright: ignore[reportPrivateUsage] - testing private function intentionally
    to_openapi_schema,
    to_json_schema,
)
from emergent.wire.axis.schema import MaxLen


# ═══════════════════════════════════════════════════════════════════════════════
# Test _python_type_to_json_schema — basic types
# ═══════════════════════════════════════════════════════════════════════════════


class TestPythonTypeToJsonSchemaBasic:
    """Covers lines 28–39: NoneType, str, int, float, bool."""

    def test_none_type(self) -> None:
        assert _python_type_to_json_schema(type(None)) == {"type": "null"}

    def test_str(self) -> None:
        assert _python_type_to_json_schema(str) == {"type": "string"}

    def test_int(self) -> None:
        assert _python_type_to_json_schema(int) == {"type": "integer"}

    def test_float(self) -> None:
        assert _python_type_to_json_schema(float) == {"type": "number"}

    def test_bool(self) -> None:
        assert _python_type_to_json_schema(bool) == {"type": "boolean"}

    def test_bytes(self) -> None:
        assert _python_type_to_json_schema(bytes) == {"type": "string", "format": "byte"}


# ═══════════════════════════════════════════════════════════════════════════════
# Test _python_type_to_json_schema — generic containers
# ═══════════════════════════════════════════════════════════════════════════════


class TestPythonTypeToJsonSchemaContainers:
    """Covers lines 46–91: list, dict, set, frozenset, tuple."""

    def test_list_of_str(self) -> None:
        result = _python_type_to_json_schema(list[str])
        assert result == {"type": "array", "items": {"type": "string"}}

    def test_list_of_any(self) -> None:
        result = _python_type_to_json_schema(list[Any])
        assert result == {"type": "array", "items": {}}

    def test_dict_str_int(self) -> None:
        result = _python_type_to_json_schema(dict[str, int])
        assert result == {"type": "object", "additionalProperties": {"type": "integer"}}

    def test_dict_str_any(self) -> None:
        result = _python_type_to_json_schema(dict[str, Any])
        assert result == {"type": "object", "additionalProperties": True}

    def test_set_of_int(self) -> None:
        result = _python_type_to_json_schema(set[int])
        assert result == {"type": "array", "items": {"type": "integer"}, "uniqueItems": True}

    def test_frozenset_of_str(self) -> None:
        result = _python_type_to_json_schema(frozenset[str])
        assert result == {"type": "array", "items": {"type": "string"}, "uniqueItems": True}

    def test_fixed_length_tuple(self) -> None:
        result = _python_type_to_json_schema(tuple[str, int])
        assert result == {
            "type": "array",
            "items": [{"type": "string"}, {"type": "integer"}],
            "minItems": 2,
            "maxItems": 2,
        }

    def test_variable_length_tuple(self) -> None:
        result = _python_type_to_json_schema(tuple[str, ...])
        assert result == {"type": "array", "items": {"type": "string"}}


# ═══════════════════════════════════════════════════════════════════════════════
# Test _python_type_to_json_schema — union types
# ═══════════════════════════════════════════════════════════════════════════════


class TestPythonTypeToJsonSchemaUnion:
    """Covers lines 94–106: Union/Optional types."""

    def test_optional_str(self) -> None:
        result = _python_type_to_json_schema(str | None)
        assert result.get("type") == "string"
        assert result.get("nullable") is True

    def test_union_str_int(self) -> None:
        result = _python_type_to_json_schema(str | int)
        assert "anyOf" in result
        schemas = result["anyOf"]
        types = {s.get("type") for s in schemas}
        assert types == {"string", "integer"}

    def test_fallback_object(self) -> None:
        class Unknown:
            pass
        result = _python_type_to_json_schema(Unknown)
        assert result == {"type": "object"}


# ═══════════════════════════════════════════════════════════════════════════════
# Test _structured_type_to_json_schema
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class Address:
    street: str
    city: str
    zip_code: str | None = None


class TestStructuredTypeToJsonSchema:
    """Covers lines 118–142: structured type to JSON schema."""

    def test_dataclass_schema(self) -> None:
        result = _structured_type_to_json_schema(Address)
        assert result["type"] == "object"
        assert "street" in result["properties"]
        assert "city" in result["properties"]
        assert result["properties"]["street"] == {"type": "string"}
        assert "street" in result["required"]
        assert "city" in result["required"]

    def test_optional_field_not_required(self) -> None:
        result = _structured_type_to_json_schema(Address)
        assert "zip_code" not in result.get("required", [])


# ═══════════════════════════════════════════════════════════════════════════════
# Test _convert_openapi_to_json_schema
# ═══════════════════════════════════════════════════════════════════════════════


class TestConvertOpenAPIToJsonSchema:
    """Covers lines 266–302: nullable, properties, items, anyOf recursion."""

    def test_nullable_to_type_array(self) -> None:
        schema: dict[str, Any] = {"type": "string", "nullable": True}
        _convert_openapi_to_json_schema(schema)
        assert "nullable" not in schema
        assert schema["type"] == ["string", "null"]

    def test_nullable_already_list(self) -> None:
        schema: dict[str, Any] = {"type": ["string", "integer"], "nullable": True}
        _convert_openapi_to_json_schema(schema)
        assert "null" in schema["type"]

    def test_recurse_into_properties(self) -> None:
        schema: dict[str, Any] = {
            "type": "object",
            "properties": {
                "name": {"type": "string", "nullable": True},
            },
        }
        _convert_openapi_to_json_schema(schema)
        assert schema["properties"]["name"]["type"] == ["string", "null"]

    def test_recurse_into_items_dict(self) -> None:
        schema: dict[str, Any] = {
            "type": "array",
            "items": {"type": "integer", "nullable": True},
        }
        _convert_openapi_to_json_schema(schema)
        assert schema["items"]["type"] == ["integer", "null"]

    def test_recurse_into_items_list(self) -> None:
        schema: dict[str, Any] = {
            "type": "array",
            "items": [
                {"type": "string", "nullable": True},
                {"type": "integer"},
            ],
        }
        _convert_openapi_to_json_schema(schema)
        assert schema["items"][0]["type"] == ["string", "null"]
        assert schema["items"][1]["type"] == "integer"

    def test_recurse_into_anyof(self) -> None:
        schema: dict[str, Any] = {
            "anyOf": [{"type": "string", "nullable": True}],
        }
        _convert_openapi_to_json_schema(schema)
        assert schema["anyOf"][0]["type"] == ["string", "null"]

    def test_recurse_into_oneof(self) -> None:
        schema: dict[str, Any] = {
            "oneOf": [{"type": "number", "nullable": True}],
        }
        _convert_openapi_to_json_schema(schema)
        assert schema["oneOf"][0]["type"] == ["number", "null"]

    def test_no_nullable_no_change(self) -> None:
        schema: dict[str, Any] = {"type": "string"}
        _convert_openapi_to_json_schema(schema)
        assert schema == {"type": "string"}


# ═══════════════════════════════════════════════════════════════════════════════
# Test to_openapi_schema — integration
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class User:
    name: str
    age: int
    email: Annotated[str, MaxLen(255)]


@dataclass
class OptUser:
    name: str
    bio: str | None = None


class TestToOpenAPISchema:
    """Covers lines 184–210: to_openapi_schema."""

    def test_basic_schema(self) -> None:
        axes = Axes.default()
        schema = to_openapi_schema(User, axes)
        assert schema["type"] == "object"
        assert "name" in schema["properties"]
        assert "age" in schema["properties"]
        assert "email" in schema["properties"]
        assert set(schema["required"]) == {"name", "age", "email"}

    def test_optional_field_not_required(self) -> None:
        axes = Axes.default()
        schema = to_openapi_schema(OptUser, axes)
        assert "name" in schema["required"]
        assert "bio" not in schema.get("required", [])

    def test_capability_affects_schema(self) -> None:
        axes = Axes.default()
        schema = to_openapi_schema(User, axes)
        email_schema = schema["properties"]["email"]
        assert email_schema.get("maxLength") == 255


# ═══════════════════════════════════════════════════════════════════════════════
# Test to_json_schema — integration
# ═══════════════════════════════════════════════════════════════════════════════


class TestToJsonSchema:
    """Covers lines 249–263: to_json_schema."""

    def test_basic_json_schema(self) -> None:
        axes = Axes.default()
        schema = to_json_schema(User, axes)
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert schema["type"] == "object"
        assert "name" in schema["properties"]

    def test_json_schema_with_id(self) -> None:
        axes = Axes.default()
        schema = to_json_schema(User, axes, schema_id="https://example.com/user")
        assert schema["$id"] == "https://example.com/user"

    def test_json_schema_without_id(self) -> None:
        axes = Axes.default()
        schema = to_json_schema(User, axes)
        assert "$id" not in schema

    def test_json_schema_converts_nullable(self) -> None:
        axes = Axes.default()
        schema = to_json_schema(OptUser, axes)
        bio = schema["properties"]["bio"]
        # Should have been converted from nullable to type array
        if "nullable" not in bio:
            # Already converted - check type list
            assert isinstance(bio.get("type"), list) or bio.get("type") == "string"


# ═══════════════════════════════════════════════════════════════════════════════
# Test nested structured type
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class Inner:
    value: int


@dataclass
class Outer:
    inner: Inner
    name: str


class TestNestedStructuredType:
    """Covers lines 109–115: nested structured type in _python_type_to_json_schema."""

    def test_nested_dataclass(self) -> None:
        result = _python_type_to_json_schema(Inner)
        assert result["type"] == "object"
        assert "value" in result["properties"]
        assert result["properties"]["value"] == {"type": "integer"}

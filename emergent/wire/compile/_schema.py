"""Schema generation — pure functions for OpenAPI/JSON Schema.

    from emergent.wire.compile import to_openapi_schema, to_json_schema

    schema = to_openapi_schema(User, axes)
    json_schema = to_json_schema(User, axes)
"""

from __future__ import annotations

import types
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Union, TYPE_CHECKING, cast, get_args, get_origin

from emergent.wire.compile._core import Axes
from emergent.wire.compile._phase import (
    CompilationPhase,
    EntityCompilation,
    FieldCompilation,
    SchemaCompiler,
    OPENAPI_PHASE,
)

if TYPE_CHECKING:
    from emergent.wire.axis._capability import OpenAPIContext


# Type alias for JSON Schema dict
JsonSchemaDict = dict[str, Any]


# ═══════════════════════════════════════════════════════════════════════════════
# Open-World Type → JSON Schema Mapping
# ═══════════════════════════════════════════════════════════════════════════════
#
# Type maps are DATA, not behavior. Users extend by adding entries.
# The mapping function interprets the data. Zero code changes needed
# to support custom types.


DEFAULT_JSON_TYPE_MAP: Mapping[type, JsonSchemaDict] = {
    type(None): {"type": "null"},
    str: {"type": "string"},
    int: {"type": "integer"},
    float: {"type": "number"},
    bool: {"type": "boolean"},
    bytes: {"type": "string", "format": "byte"},
}


def type_to_json_schema(
    py_type: type | Any,
    type_map: Mapping[type, JsonSchemaDict] = DEFAULT_JSON_TYPE_MAP,
) -> JsonSchemaDict:
    """Map Python type to JSON Schema. Open-world via type_map parameter.

    Basic types looked up in type_map. Generic types (list[X], dict[K,V],
    Optional[X], tuple[X,...]) handled structurally with recursive calls.

    Extend by passing a custom type_map::

        my_map = {**DEFAULT_JSON_TYPE_MAP, MyType: {"type": "string", "format": "custom"}}
        schema = type_to_json_schema(MyType, my_map)
    """
    # Exact match in type map
    if py_type in type_map:
        return dict(type_map[py_type])

    # Structural dispatch on generic origins
    origin = get_origin(py_type)

    if origin is list:
        args = get_args(py_type) or (Any,)
        item_type = args[0] if args else Any
        return {
            "type": "array",
            "items": type_to_json_schema(item_type, type_map) if item_type is not Any else {},
        }

    if origin is dict:
        args = get_args(py_type) or (str, Any)
        value_type = args[1] if len(args) > 1 else Any
        return {
            "type": "object",
            "additionalProperties": type_to_json_schema(value_type, type_map)
            if value_type is not Any
            else True,
        }

    if origin is set or origin is frozenset:
        args = get_args(py_type) or (Any,)
        item_type = args[0] if args else Any
        return {
            "type": "array",
            "items": type_to_json_schema(item_type, type_map) if item_type is not Any else {},
            "uniqueItems": True,
        }

    if origin is tuple:
        args = get_args(py_type)
        if args and args[-1] is not ...:
            return {
                "type": "array",
                "items": [type_to_json_schema(t, type_map) for t in args],
                "minItems": len(args),
                "maxItems": len(args),
            }
        else:
            item_type = args[0] if args else Any
            return {
                "type": "array",
                "items": type_to_json_schema(item_type, type_map) if item_type is not Any else {},
            }

    # Union types (types.UnionType on 3.10-3.13 for X | Y, typing.Union for Union[X, Y])
    if origin is Union or origin is types.UnionType:
        args = get_args(py_type)
        schemas = [type_to_json_schema(t, type_map) for t in args]
        null_schemas = [s for s in schemas if s.get("type") == "null"]
        non_null = [s for s in schemas if s.get("type") != "null"]

        if len(non_null) == 1 and null_schemas:
            result = non_null[0].copy()
            result["nullable"] = True
            return result
        return {"anyOf": schemas}

    # Structured types (dataclass, Pydantic, etc.)
    from emergent.wire.axis.schema import is_structured_type
    if isinstance(py_type, type) and is_structured_type(py_type):
        return _structured_type_to_json_schema(py_type, type_map)

    # Default: object
    return {"type": "object"}


def _structured_type_to_json_schema(
    cls: type,
    type_map: Mapping[type, JsonSchemaDict] = DEFAULT_JSON_TYPE_MAP,
) -> JsonSchemaDict:
    """Generate JSON Schema for a structured type (dataclass, Pydantic, etc.)."""
    from emergent.wire.axis.schema import inspect_type

    try:
        fields = inspect_type(cls)
    except TypeError:
        return {"type": "object"}

    properties: JsonSchemaDict = {}
    required: list[str] = []

    for name, field_info in fields.items():
        properties[name] = type_to_json_schema(field_info.base_type, type_map)
        if not field_info.is_optional:
            required.append(name)

    result: JsonSchemaDict = {"type": "object", "properties": properties}
    if required:
        result["required"] = required

    return result


def make_openapi_initial(
    type_map: Mapping[type, JsonSchemaDict] = DEFAULT_JSON_TYPE_MAP,
) -> Callable[[str, type], "OpenAPIContext"]:
    """Factory for OpenAPI initial function with custom type map.

    The initial function closes over the type map. Users create custom phases::

        from emergent.wire.compile._schema import DEFAULT_JSON_TYPE_MAP, make_openapi_initial

        my_map = {**DEFAULT_JSON_TYPE_MAP, MyType: {"type": "string", "format": "custom"}}
        my_phase = CompilationPhase(OpenAPIContext, OpenAPICompilable, make_openapi_initial(my_map))
    """
    from emergent.wire.axis._capability import OpenAPIContext

    def _initial(name: str, field_type: type) -> OpenAPIContext:
        schema = type_to_json_schema(field_type, type_map)
        return OpenAPIContext(name, field_type, schema=schema)

    return _initial


# Backward compat aliases
python_type_to_json_schema = type_to_json_schema
_python_type_to_json_schema = type_to_json_schema


# ═══════════════════════════════════════════════════════════════════════════════
# OpenAPI Schema Generation
# ═══════════════════════════════════════════════════════════════════════════════


def assemble_openapi(
    cls: type,
    fields: EntityCompilation | Sequence[FieldCompilation],
    phase: CompilationPhase[Any] = OPENAPI_PHASE,
) -> dict[str, Any]:
    """Assemble OpenAPI schema from compiled fields.

    Accepts EntityCompilation or a sequence of FieldCompilation.

    Use with SchemaCompiler for composable compilation::

        compiler = FASTAPI_SCHEMA + SA_SCHEMA
        ec = compiler.compile(User, axes)
        schema = assemble_openapi(User, ec)
    """
    from emergent.wire.axis.schema.dialects.compose import ComposeCapability

    field_seq = fields.fields if isinstance(fields, EntityCompilation) else fields
    properties: dict[str, Any] = {}
    required: list[str] = []

    for fc in field_seq:
        # Skip compose.Node fields — resolved at runtime by nodnod, not from request body
        if fc.info.has(ComposeCapability):
            continue

        ctx = fc[phase]
        properties[fc.name] = ctx.schema

        if not fc.info.is_optional:
            required.append(fc.name)

    result: dict[str, Any] = {
        "type": "object",
        "properties": properties,
    }

    if required:
        result["required"] = required

    return result


def to_openapi_schema(
    cls: type,
    axes: Axes,
    *,
    ref_prefix: str = "#/components/schemas/",
) -> dict[str, Any]:
    """Generate OpenAPI 3.x schema from dataclass + capabilities.

    Thin assembler over SchemaCompiler + assemble_openapi.

    Args:
        cls: Dataclass to generate schema for
        axes: Axes context with schema inspector
        ref_prefix: Prefix for $ref URLs

    Returns:
        OpenAPI schema dict

    Example:
        @dataclass
        class User:
            email: Annotated[str, MaxLen(255), openapi.Format("email")]
            age: Annotated[int, Min(0), Max(150)]

        schema = to_openapi_schema(User, axes)
        # {
        #   "type": "object",
        #   "properties": {
        #     "email": {"type": "string", "maxLength": 255, "format": "email"},
        #     "age": {"type": "integer", "minimum": 0, "maximum": 150}
        #   },
        #   "required": ["email", "age"]
        # }
    """
    ec = SchemaCompiler(phases=(OPENAPI_PHASE,)).compile(cls, axes)
    return assemble_openapi(cls, ec)


# ═══════════════════════════════════════════════════════════════════════════════
# JSON Schema Generation
# ═══════════════════════════════════════════════════════════════════════════════


def to_json_schema(
    cls: type,
    axes: Axes,
    *,
    schema_id: str | None = None,
) -> dict[str, Any]:
    """Generate JSON Schema from dataclass + capabilities.

    Args:
        cls: Dataclass to generate schema for
        axes: Axes context with schema inspector
        schema_id: Optional $id for the schema

    Returns:
        JSON Schema dict

    Example:
        @dataclass
        class User:
            name: Annotated[str, MinLen(1), MaxLen(100)]
            age: Annotated[int, Min(0)]

        schema = to_json_schema(User, axes)
        # {
        #   "$schema": "https://json-schema.org/draft/2020-12/schema",
        #   "type": "object",
        #   "properties": {...},
        #   "required": [...]
        # }
    """
    # Use OpenAPI generation as base (compatible)
    openapi_schema = to_openapi_schema(cls, axes)

    # Convert to JSON Schema format
    result: dict[str, Any] = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        **openapi_schema,
    }

    if schema_id:
        result["$id"] = schema_id

    # Convert OpenAPI-specific fields to JSON Schema
    _convert_openapi_to_json_schema(result)

    return result


def _convert_openapi_to_json_schema(schema: dict[str, Any]) -> None:
    """Convert OpenAPI-specific fields to JSON Schema in-place."""
    # nullable → type array with null
    if schema.get("nullable"):
        del schema["nullable"]
        current_type = schema.get("type")
        if current_type and current_type != "null":
            if isinstance(current_type, list):
                type_list = cast(list[str], current_type)
                if "null" not in type_list:
                    type_list.append("null")
            else:
                schema["type"] = [current_type, "null"]

    # Recurse into properties
    props = schema.get("properties")
    if isinstance(props, dict):
        props_dict = cast(dict[str, dict[str, Any]], props)
        for prop_schema in props_dict.values():
            _convert_openapi_to_json_schema(prop_schema)

    # Recurse into items
    items = schema.get("items")
    if isinstance(items, dict):
        _convert_openapi_to_json_schema(cast(dict[str, Any], items))
    elif isinstance(items, list):
        items_list = cast(list[dict[str, Any]], items)
        for item in items_list:
            _convert_openapi_to_json_schema(item)

    # Recurse into anyOf/oneOf/allOf
    for key in ("anyOf", "oneOf", "allOf"):
        arr = schema.get(key)
        if isinstance(arr, list):
            arr_list = cast(list[dict[str, Any]], arr)
            for sub_schema in arr_list:
                _convert_openapi_to_json_schema(sub_schema)


__all__ = (
    "assemble_openapi",
    "to_openapi_schema",
    "to_json_schema",
)

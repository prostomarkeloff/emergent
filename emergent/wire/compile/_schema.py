"""Schema generation — pure functions for OpenAPI/JSON Schema.

    from emergent.wire.compile import to_openapi_schema, to_json_schema

    schema = to_openapi_schema(User, axes)
    json_schema = to_json_schema(User, axes)
"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING, cast

from emergent.wire.compile._core import Axes
from emergent.wire.compile._phase import compile_fields, OPENAPI_PHASE

if TYPE_CHECKING:
    from emergent.wire.axis.schema._inspect import FieldInfo


# ═══════════════════════════════════════════════════════════════════════════════
# Type to JSON Schema Type Mapping
# ═══════════════════════════════════════════════════════════════════════════════


def _python_type_to_json_schema(py_type: type | Any) -> dict[str, Any]:
    """Map Python type to JSON Schema type."""
    # Handle None
    if py_type is type(None):
        return {"type": "null"}

    # Basic types
    if py_type is str:
        return {"type": "string"}
    if py_type is int:
        return {"type": "integer"}
    if py_type is float:
        return {"type": "number"}
    if py_type is bool:
        return {"type": "boolean"}

    # bytes
    if py_type is bytes:
        return {"type": "string", "format": "byte"}

    # Check for list/dict/etc via origin
    origin = getattr(py_type, "__origin__", None)

    if origin is list:
        args = getattr(py_type, "__args__", (Any,))
        item_type = args[0] if args else Any
        return {
            "type": "array",
            "items": _python_type_to_json_schema(item_type) if item_type is not Any else {},
        }

    if origin is dict:
        args = getattr(py_type, "__args__", (str, Any))
        value_type = args[1] if len(args) > 1 else Any
        return {
            "type": "object",
            "additionalProperties": _python_type_to_json_schema(value_type)
            if value_type is not Any
            else True,
        }

    if origin is set or origin is frozenset:
        args = getattr(py_type, "__args__", (Any,))
        item_type = args[0] if args else Any
        return {
            "type": "array",
            "items": _python_type_to_json_schema(item_type) if item_type is not Any else {},
            "uniqueItems": True,
        }

    if origin is tuple:
        args = getattr(py_type, "__args__", ())
        if args and args[-1] is not ...:
            # Fixed-length tuple
            return {
                "type": "array",
                "items": [_python_type_to_json_schema(t) for t in args],
                "minItems": len(args),
                "maxItems": len(args),
            }
        else:
            # Variable-length tuple
            item_type = args[0] if args else Any
            return {
                "type": "array",
                "items": _python_type_to_json_schema(item_type) if item_type is not Any else {},
            }

    # Union types
    if origin is type(int | str):  # UnionType
        args = getattr(py_type, "__args__", ())
        schemas = [_python_type_to_json_schema(t) for t in args]
        # Check if it's Optional (has null)
        null_schemas = [s for s in schemas if s.get("type") == "null"]
        non_null = [s for s in schemas if s.get("type") != "null"]

        if len(non_null) == 1 and null_schemas:
            # Optional[X] → add nullable
            result = non_null[0].copy()
            result["nullable"] = True
            return result
        return {"anyOf": schemas}

    # Check for structured types (dataclass, Pydantic, etc.)
    from emergent.wire.axis.schema import is_structured_type, inspect_type
    if isinstance(py_type, type) and is_structured_type(py_type):
        # Recursively generate schema for nested structured type
        return _structured_type_to_json_schema(py_type)

    # Default: object
    return {"type": "object"}


def _structured_type_to_json_schema(cls: type) -> dict[str, Any]:
    """Generate JSON Schema for a structured type (dataclass, Pydantic, etc.)."""
    from emergent.wire.axis.schema import inspect_type

    try:
        fields = inspect_type(cls)
    except TypeError:
        return {"type": "object"}

    properties: dict[str, Any] = {}
    required: list[str] = []

    for name, field_info in fields.items():
        properties[name] = _python_type_to_json_schema(field_info.base_type)
        if not field_info.is_optional:
            required.append(name)

    result: dict[str, Any] = {
        "type": "object",
        "properties": properties,
    }
    if required:
        result["required"] = required

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# OpenAPI Schema Generation
# ═══════════════════════════════════════════════════════════════════════════════


def to_openapi_schema(
    cls: type,
    axes: Axes,
    *,
    ref_prefix: str = "#/components/schemas/",
) -> dict[str, Any]:
    """Generate OpenAPI 3.x schema from dataclass + capabilities.

    Thin assembler over compile_fields + OPENAPI_PHASE.

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
    from emergent.wire.axis.schema.dialects.compose import ComposeCapability

    compiled = compile_fields(cls, axes, [OPENAPI_PHASE])

    properties: dict[str, Any] = {}
    required: list[str] = []

    for fc in compiled:
        # Skip compose.Node fields — resolved at runtime by nodnod, not from request body
        if fc.info.has(ComposeCapability):
            continue

        ctx = fc[OPENAPI_PHASE]
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
    "to_openapi_schema",
    "to_json_schema",
)

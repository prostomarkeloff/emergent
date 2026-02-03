"""Schema introspection — pure composable type inspection.

Unified inspection for ANY structured type (dataclass, Pydantic, TypedDict, NamedTuple).

    from emergent.wire.axis.schema import inspect_type, FieldInfo

    # Works for any supported type
    fields = inspect_type(User)  # dataclass, Pydantic, TypedDict, NamedTuple

    for name, info in fields.items():
        print(f"{name}: {info.base_type}")
        print(f"  universal: {info.universal}")
        print(f"  sql: {info.dialect('sql')}")

## Architecture: Pure Composable Inspectors

Inspector = pure function: `type -> dict[str, FieldInfo] | None`
- Returns fields dict if it can handle the type
- Returns None if it can't (passes to next inspector)

Compose with `first_match` combinator:

    inspect_type = first_match(
        dataclass_inspector,
        pydantic_inspector,
        typeddict_inspector,
        namedtuple_inspector,
    )

Custom composition:

    my_inspector = first_match(
        attrs_inspector,  # prioritize attrs
        dataclass_inspector,
        pydantic_inspector,
    )
    axes = Axes(schema=my_inspector)
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Annotated, Any, Union, get_args, get_origin, get_type_hints

from emergent.wire.axis.schema._universal import SchemaAxisCapability, UniversalCapability
from emergent.wire.axis.schema.dialects.sql import SQLCapability
from emergent.wire.axis.schema.dialects.openapi import OpenAPICapability
from emergent.wire.axis.schema.dialects.pydantic import PydanticCapability
from emergent.wire.axis.schema.dialects.cli import CLICapability
from emergent.wire.axis.schema.dialects.tg import TelegramCapability
from emergent.wire.axis.schema.dialects.compose import ComposeCapability
from emergent.wire.axis.schema.dialects.api import APICapability


# ═══════════════════════════════════════════════════════════════════════════════
# Type Alias
# ═══════════════════════════════════════════════════════════════════════════════


# Inspector: pure function that inspects a type, returns None if can't handle
type Inspector = Callable[[type], dict[str, FieldInfo] | None]


# ═══════════════════════════════════════════════════════════════════════════════
# Dialect Registry (for FieldInfo.dialect())
# ═══════════════════════════════════════════════════════════════════════════════


DIALECT_BASES: dict[str, type[SchemaAxisCapability]] = {
    "sql": SQLCapability,
    "openapi": OpenAPICapability,
    "pydantic": PydanticCapability,
    "cli": CLICapability,
    "tg": TelegramCapability,
    "compose": ComposeCapability,
    "api": APICapability,
}


# ═══════════════════════════════════════════════════════════════════════════════
# Field Info
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class FieldInfo:
    """Extracted information about a structured type field."""

    name: str
    base_type: type
    is_optional: bool
    capabilities: list[SchemaAxisCapability]

    @property
    def universal(self) -> list[UniversalCapability]:
        """Get universal capabilities."""
        return [c for c in self.capabilities if isinstance(c, UniversalCapability)]

    def dialect(self, name: str) -> list[SchemaAxisCapability]:
        """Get capabilities for specific dialect."""
        base = DIALECT_BASES.get(name)
        if base is None:
            return []
        return [c for c in self.capabilities if isinstance(c, base)]

    def has(self, cap_type: type[SchemaAxisCapability]) -> bool:
        """Check if field has specific capability type."""
        return any(isinstance(c, cap_type) for c in self.capabilities)

    def get[C: SchemaAxisCapability](self, cap_type: type[C]) -> C | None:
        """Get first capability of specific type."""
        for c in self.capabilities:
            if isinstance(c, cap_type):
                return c
        return None

    def get_all[C: SchemaAxisCapability](self, cap_type: type[C]) -> list[C]:
        """Get all capabilities of specific type."""
        return [c for c in self.capabilities if isinstance(c, cap_type)]


# ═══════════════════════════════════════════════════════════════════════════════
# Type Helpers (pure functions)
# ═══════════════════════════════════════════════════════════════════════════════


def unwrap_optional(type_hint: Any) -> tuple[Any, bool]:
    """Unwrap Optional[X] or X | None to (X, True), or (type_hint, False)."""
    origin = get_origin(type_hint)

    # Union type (X | None or Optional[X])
    if origin is Union:
        args = get_args(type_hint)
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1 and type(None) in args:
            return non_none[0], True
        # Multi-type union, not simple Optional
        return type_hint, False

    return type_hint, False


def unwrap_annotated(type_hint: Any) -> tuple[Any, list[Any]]:
    """Unwrap Annotated[X, ...] to (X, [annotations])."""
    if get_origin(type_hint) is Annotated:
        args = get_args(type_hint)
        return args[0], list(args[1:])
    return type_hint, []


def extract_capabilities(annotations: list[Any]) -> list[SchemaAxisCapability]:
    """Extract SchemaAxisCapability instances from annotations."""
    capabilities: list[SchemaAxisCapability] = []

    for ann in annotations:
        if isinstance(ann, SchemaAxisCapability):
            capabilities.append(ann)
        elif isinstance(ann, tuple):
            # Pattern — tuple of capabilities
            for item in ann:  # type: ignore[union-attr]
                if isinstance(item, SchemaAxisCapability):
                    capabilities.append(item)

    return capabilities


def inspect_field(name: str, type_hint: Any) -> FieldInfo:
    """Inspect a single field type hint.

    Pure function. Handles:
    - Annotated[X, Cap1, Cap2, ...]
    - Optional[X] / X | None
    - Patterns (tuples of capabilities)
    """
    # Step 1: Unwrap Annotated
    inner_type, annotations = unwrap_annotated(type_hint)

    # Step 2: Check for Optional
    base_type, is_optional = unwrap_optional(inner_type)

    # Step 3: If base is still Annotated (nested), unwrap again
    if get_origin(base_type) is Annotated:
        base_type, more_annotations = unwrap_annotated(base_type)
        annotations.extend(more_annotations)
        # Re-check optional on the new base
        base_type, is_optional_inner = unwrap_optional(base_type)
        is_optional = is_optional or is_optional_inner

    # Step 4: Extract capabilities
    capabilities = extract_capabilities(annotations)

    return FieldInfo(
        name=name,
        base_type=base_type,
        is_optional=is_optional,
        capabilities=capabilities,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Combinator: first_match
# ═══════════════════════════════════════════════════════════════════════════════


def first_match(*inspectors: Inspector) -> Callable[[type], dict[str, FieldInfo]]:
    """Compose inspectors — first non-None result wins.

    Pure combinator. Creates a new function from inspector functions.

    Args:
        *inspectors: Inspector functions to try in order.

    Returns:
        Combined inspector function that raises TypeError if none match.

    Example::

        inspect_type = first_match(
            dataclass_inspector,
            pydantic_inspector,
            typeddict_inspector,
        )

        # Custom priority
        my_inspector = first_match(
            attrs_inspector,
            dataclass_inspector,
        )
    """
    def combined(cls: type) -> dict[str, FieldInfo]:
        for inspector in inspectors:
            result = inspector(cls)
            if result is not None:
                return result
        raise TypeError(
            f"Cannot inspect {cls.__name__}: no inspector handles this type. "
            f"Supported: dataclass, Pydantic model, TypedDict, NamedTuple."
        )
    return combined


# ═══════════════════════════════════════════════════════════════════════════════
# Individual Inspectors (pure functions)
# ═══════════════════════════════════════════════════════════════════════════════


def dataclass_inspector(cls: type) -> dict[str, FieldInfo] | None:
    """Inspect standard dataclass. Returns None if not a dataclass."""
    if not dataclasses.is_dataclass(cls):
        return None

    hints = get_type_hints(cls, include_extras=True)
    result: dict[str, FieldInfo] = {}

    for field in dataclasses.fields(cls):
        type_hint = hints.get(field.name, field.type)
        result[field.name] = inspect_field(field.name, type_hint)

    return result


def pydantic_inspector(cls: type) -> dict[str, FieldInfo] | None:
    """Inspect Pydantic v2 model. Returns None if not a Pydantic model."""
    if not hasattr(cls, "model_fields"):
        return None

    result: dict[str, FieldInfo] = {}
    model_fields: dict[str, Any] = getattr(cls, "model_fields", {})

    for field_name, pydantic_field in model_fields.items():
        # Get annotation from Pydantic field
        annotation: Any = getattr(pydantic_field, "annotation", None)
        if annotation is None:
            annotation = str

        # Check if required
        is_required_fn = getattr(pydantic_field, "is_required", None)
        is_optional = not (is_required_fn() if callable(is_required_fn) else True)

        # Extract base type and capabilities from annotation
        base_type, annotations = unwrap_annotated(annotation)
        base_type, is_optional_from_type = unwrap_optional(base_type)
        is_optional = is_optional or is_optional_from_type

        capabilities = extract_capabilities(annotations)

        result[str(field_name)] = FieldInfo(
            name=str(field_name),
            base_type=base_type,
            is_optional=is_optional,
            capabilities=capabilities,
        )

    return result


def typeddict_inspector(cls: type) -> dict[str, FieldInfo] | None:
    """Inspect TypedDict. Returns None if not a TypedDict."""
    # TypedDict has __required_keys__ and __optional_keys__
    if not (hasattr(cls, "__required_keys__") and hasattr(cls, "__optional_keys__")):
        return None

    # Also check it's not a regular class that happens to have these
    if not hasattr(cls, "__annotations__"):
        return None

    result: dict[str, FieldInfo] = {}
    required_keys: frozenset[str] = getattr(cls, "__required_keys__", frozenset())
    hints = get_type_hints(cls, include_extras=True)

    for field_name, type_hint in hints.items():
        is_optional = field_name not in required_keys
        base_type, annotations = unwrap_annotated(type_hint)
        base_type, is_optional_from_type = unwrap_optional(base_type)
        is_optional = is_optional or is_optional_from_type
        capabilities = extract_capabilities(annotations)

        result[field_name] = FieldInfo(
            name=field_name,
            base_type=base_type,
            is_optional=is_optional,
            capabilities=capabilities,
        )

    return result


def namedtuple_inspector(cls: type) -> dict[str, FieldInfo] | None:
    """Inspect NamedTuple. Returns None if not a NamedTuple."""
    # NamedTuple has _fields tuple and __annotations__
    if not (hasattr(cls, "_fields") and hasattr(cls, "__annotations__")):
        return None

    # Check _fields is a tuple of strings (NamedTuple convention)
    # NamedTuple._fields is always tuple[str, ...] per Python spec
    fields_attr: Sequence[str] | None = getattr(cls, "_fields", None)
    if fields_attr is None or not isinstance(fields_attr, (tuple, list)):
        return None

    field_names = list(fields_attr)
    if not field_names:
        return None

    result: dict[str, FieldInfo] = {}
    hints = get_type_hints(cls, include_extras=True)
    defaults: dict[str, object] = getattr(cls, "_field_defaults", {})

    for field_name in field_names:
        type_hint = hints.get(field_name, str)
        has_default = field_name in defaults

        base_type, annotations = unwrap_annotated(type_hint)
        base_type, is_optional_from_type = unwrap_optional(base_type)
        is_optional = has_default or is_optional_from_type
        capabilities = extract_capabilities(annotations)

        result[field_name] = FieldInfo(
            name=field_name,
            base_type=base_type,
            is_optional=is_optional,
            capabilities=capabilities,
        )

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# Default Composition
# ═══════════════════════════════════════════════════════════════════════════════


# Default inspector — handles dataclass, Pydantic, TypedDict, NamedTuple
inspect_type = first_match(
    dataclass_inspector,
    pydantic_inspector,
    typeddict_inspector,
    namedtuple_inspector,
)

# Backwards compatibility alias
inspect_dataclass = inspect_type


__all__ = (
    # Core types
    "FieldInfo",
    "Inspector",
    # Combinator
    "first_match",
    # Individual inspectors (for custom composition)
    "dataclass_inspector",
    "pydantic_inspector",
    "typeddict_inspector",
    "namedtuple_inspector",
    # Default composed inspector
    "inspect_type",
    # Backwards compat
    "inspect_dataclass",
    # Helpers
    "inspect_field",
    "unwrap_optional",
    "unwrap_annotated",
    "extract_capabilities",
    # Dialect registry
    "DIALECT_BASES",
)

"""Schema introspection — extract capabilities from dataclass fields.

    from emergent.wire.axis.schema import inspect_dataclass, inspect_field

    # Get all field info
    fields = inspect_dataclass(User)
    for name, info in fields.items():
        print(f"{name}: {info.base_type}")
        print(f"  universal: {info.universal}")
        print(f"  sql: {info.dialect('sql')}")

    # Filter by dialect
    sql_caps = info.dialect('sql')
"""

import dataclasses
from dataclasses import dataclass
from typing import Annotated, Any, Union, get_args, get_origin, get_type_hints

from emergent.wire.axis.schema._universal import Capability, UniversalCapability
from emergent.wire.axis.schema.dialects.sql import SQLCapability
from emergent.wire.axis.schema.dialects.openapi import OpenAPICapability
from emergent.wire.axis.schema.dialects.pydantic import PydanticCapability
from emergent.wire.axis.schema.dialects.cli import CLICapability
from emergent.wire.axis.schema.dialects.tg import TelegramCapability
from emergent.wire.axis.schema.dialects.compose import ComposeCapability
from emergent.wire.axis.schema.dialects.api import APICapability


# ═══════════════════════════════════════════════════════════════════════════════
# Dialect Registry
# ═══════════════════════════════════════════════════════════════════════════════


DIALECT_BASES: dict[str, type[Capability]] = {
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
    """Extracted information about a dataclass field."""

    name: str
    base_type: type
    is_optional: bool
    capabilities: list[Capability]

    @property
    def universal(self) -> list[UniversalCapability]:
        """Get universal capabilities."""
        return [c for c in self.capabilities if isinstance(c, UniversalCapability)]

    def dialect(self, name: str) -> list[Capability]:
        """Get capabilities for specific dialect."""
        base = DIALECT_BASES.get(name)
        if base is None:
            return []
        return [c for c in self.capabilities if isinstance(c, base)]

    def has(self, cap_type: type[Capability]) -> bool:
        """Check if field has specific capability type."""
        return any(isinstance(c, cap_type) for c in self.capabilities)

    def get(self, cap_type: type[Capability]) -> Capability | None:
        """Get first capability of specific type."""
        for c in self.capabilities:
            if isinstance(c, cap_type):
                return c
        return None

    def get_all(self, cap_type: type[Capability]) -> list[Capability]:
        """Get all capabilities of specific type."""
        return [c for c in self.capabilities if isinstance(c, cap_type)]


# ═══════════════════════════════════════════════════════════════════════════════
# Type Helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _unwrap_optional(type_hint: Any) -> tuple[Any, bool]:
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


def _unwrap_annotated(type_hint: Any) -> tuple[Any, list[Any]]:
    """Unwrap Annotated[X, ...] to (X, [annotations])."""
    if get_origin(type_hint) is Annotated:
        args = get_args(type_hint)
        return args[0], list(args[1:])
    return type_hint, []


def _extract_capabilities(annotations: list[Any]) -> list[Capability]:
    """Extract Capability instances from annotations."""
    capabilities: list[Capability] = []

    for ann in annotations:
        if isinstance(ann, Capability):
            capabilities.append(ann)
        elif isinstance(ann, tuple):
            # Pattern — tuple of capabilities
            for item in ann:  # type: ignore[union-attr]
                if isinstance(item, Capability):
                    capabilities.append(item)

    return capabilities


# ═══════════════════════════════════════════════════════════════════════════════
# Inspection Functions
# ═══════════════════════════════════════════════════════════════════════════════


def inspect_field(name: str, type_hint: Any) -> FieldInfo:
    """Inspect a single field type hint.

    Handles:
    - Annotated[X, Cap1, Cap2, ...]
    - Optional[X] / X | None
    - Patterns (tuples of capabilities)
    """
    # Step 1: Unwrap Annotated
    inner_type, annotations = _unwrap_annotated(type_hint)

    # Step 2: Check for Optional
    base_type, is_optional = _unwrap_optional(inner_type)

    # Step 3: If base is still Annotated (nested), unwrap again
    if get_origin(base_type) is Annotated:
        base_type, more_annotations = _unwrap_annotated(base_type)
        annotations.extend(more_annotations)
        # Re-check optional on the new base
        base_type, is_optional_inner = _unwrap_optional(base_type)
        is_optional = is_optional or is_optional_inner

    # Step 4: Extract capabilities
    capabilities = _extract_capabilities(annotations)

    return FieldInfo(
        name=name,
        base_type=base_type,
        is_optional=is_optional,
        capabilities=capabilities,
    )


def inspect_dataclass(cls: type) -> dict[str, FieldInfo]:
    """Inspect all fields of a dataclass.

    Returns dict mapping field name to FieldInfo.
    """
    if not dataclasses.is_dataclass(cls):
        raise TypeError(f"{cls} is not a dataclass")

    hints = get_type_hints(cls, include_extras=True)
    result: dict[str, FieldInfo] = {}

    for field in dataclasses.fields(cls):
        type_hint = hints.get(field.name, field.type)
        result[field.name] = inspect_field(field.name, type_hint)

    return result


def get_table_capabilities(cls: type) -> list[Capability]:
    """Get table-level capabilities from class annotations.

    Table-level capabilities can be defined via __annotations__ on the class
    or via class-level Annotated types.
    """
    # Check for __schema_capabilities__ class attribute
    if hasattr(cls, "__schema_capabilities__"):
        caps = getattr(cls, "__schema_capabilities__")
        if isinstance(caps, (list, tuple)):
            result: list[Capability] = []
            for c in caps:  # type: ignore[reportUnknownVariableType]
                if isinstance(c, Capability):
                    result.append(c)
            return result
    return []


__all__ = (
    "FieldInfo",
    "inspect_field",
    "inspect_dataclass",
    "get_table_capabilities",
    "DIALECT_BASES",
)

"""Schema helpers — pure functions for schema navigation and capability composition.

from emergent.wire.axis.schema import helpers

# Find identity field
id_field = helpers.get_identity_field(User)

# Get required fields
required = helpers.get_required_fields(User)

# Find fields with specific capability
unique_fields = helpers.fields_with_capability(User, Unique)

# With custom Axes (for custom inspectors)
from emergent.wire.compile import Axes
axes = Axes(schema=my_custom_inspector)
id_field = helpers.get_identity_field(User, axes)
"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from emergent.wire.axis.schema._universal import (
        SchemaAxisCapability,
        UniversalCapability,
        Ref,
    )
    from emergent.wire.axis.schema._inspect import FieldInfo


type FieldMap = dict[str, "FieldInfo"]
type CapabilityByType = dict[type, "SchemaAxisCapability"]

# Type alias for schema inspector function
SchemaInspector = Callable[[type], FieldMap]


def _get_schema(cls: type, axes: Any | None) -> FieldMap:
    """Get schema using axes if provided, otherwise default inspect_type."""
    if axes is not None and hasattr(axes, "schema"):
        return axes.schema(cls)
    from emergent.wire.axis.schema._inspect import inspect_type

    return inspect_type(cls)


# ═══════════════════════════════════════════════════════════════════════════════
# Schema Navigation
# ═══════════════════════════════════════════════════════════════════════════════


def get_identity_field(cls: type, axes: Any | None = None) -> FieldInfo | None:
    """Find field with Identity capability.

    Args:
        cls: Class to inspect
        axes: Optional Axes with custom schema inspector

    Returns:
        FieldInfo for identity field or None

    Example:
        id_field = get_identity_field(User)
        if id_field:
            print(f"Primary key: {id_field.name}")

        # With custom Axes
        id_field = get_identity_field(User, axes)
    """
    from emergent.wire.axis.schema._universal import Identity

    fields = _get_schema(cls, axes)
    for info in fields.values():
        if info.has(Identity):
            return info
    return None


def get_required_fields(cls: type, axes: Any | None = None) -> list[FieldInfo]:
    """Get fields that are not optional.

    Args:
        cls: Class to inspect
        axes: Optional Axes with custom schema inspector

    Returns:
        List of required FieldInfo objects
    """
    fields = _get_schema(cls, axes)
    return [f for f in fields.values() if not f.is_optional]


def get_optional_fields(cls: type, axes: Any | None = None) -> list[FieldInfo]:
    """Get fields that are optional.

    Args:
        cls: Class to inspect
        axes: Optional Axes with custom schema inspector

    Returns:
        List of optional FieldInfo objects
    """
    fields = _get_schema(cls, axes)
    return [f for f in fields.values() if f.is_optional]


def partition_fields(
    cls: type, axes: Any | None = None
) -> tuple[list[FieldInfo], list[FieldInfo]]:
    """Split fields into required and optional.

    Args:
        cls: Class to inspect
        axes: Optional Axes with custom schema inspector

    Returns:
        Tuple of (required_fields, optional_fields)

    Example:
        required, optional = partition_fields(User)
    """
    fields = _get_schema(cls, axes)
    required: list[FieldInfo] = []
    optional: list[FieldInfo] = []
    for f in fields.values():
        if f.is_optional:
            optional.append(f)
        else:
            required.append(f)
    return required, optional


def field_by_name(cls: type, name: str, axes: Any | None = None) -> FieldInfo | None:
    """Get FieldInfo by field name.

    Args:
        cls: Class to inspect
        name: Field name
        axes: Optional Axes with custom schema inspector

    Returns:
        FieldInfo or None if not found
    """
    fields = _get_schema(cls, axes)
    return fields.get(name)


def field_path_type(cls: type, path: str, axes: Any | None = None) -> type | None:
    """Resolve nested field type by dot-separated path.

    Args:
        cls: Root class
        path: Dot-separated path (e.g., "user.address.city")
        axes: Optional Axes with custom schema inspector

    Returns:
        Type at path or None if path invalid

    Example:
        # Given: Order.user -> User, User.address -> Address, Address.city -> str
        city_type = field_path_type(Order, "user.address.city")
        # Returns: str
    """
    parts = path.split(".")
    current = cls

    for part in parts:
        fields = _get_schema(current, axes)
        if part not in fields:
            return None
        current = fields[part].base_type

    return current


def fields_with_capability[C: SchemaAxisCapability](
    cls: type,
    cap_type: type[C],
    axes: Any | None = None,
) -> list[tuple[str, FieldInfo, C]]:
    """Find all fields with specific capability.

    Args:
        cls: Class to inspect
        cap_type: Capability type to find
        axes: Optional Axes with custom schema inspector

    Returns:
        List of (field_name, field_info, capability) tuples

    Example:
        unique_fields = fields_with_capability(User, Unique)
        for name, info, cap in unique_fields:
            print(f"{name} is unique")
    """
    result: list[tuple[str, FieldInfo, C]] = []
    fields = _get_schema(cls, axes)

    for name, info in fields.items():
        cap = info.get(cap_type)
        if cap is not None:
            result.append((name, info, cap))

    return result


def get_refs(
    cls: type, axes: Any | None = None
) -> list[tuple[str, FieldInfo, Ref]]:
    """Find all Ref fields (foreign key relationships).

    Args:
        cls: Class to inspect
        axes: Optional Axes with custom schema inspector

    Returns:
        List of (field_name, field_info, Ref) tuples

    Example:
        refs = get_refs(Order)
        for name, info, ref in refs:
            print(f"{name} references {ref.target}")
    """
    from emergent.wire.axis.schema._universal import Ref

    return fields_with_capability(cls, Ref, axes)


def fields_by_dialect[D: SchemaAxisCapability](
    cls: type,
    dialect: type[D],
    axes: Any | None = None,
) -> list[tuple[str, FieldInfo, tuple[D, ...]]]:
    """Get all fields with capabilities of specific dialect.

    Args:
        cls: Class to inspect
        dialect: Dialect base type (e.g. SQLCapability, CLICapability)
        axes: Optional Axes with custom schema inspector

    Returns:
        List of (field_name, field_info, dialect_capabilities) tuples
    """
    result: list[tuple[str, FieldInfo, tuple[D, ...]]] = []
    fields = _get_schema(cls, axes)

    for name, info in fields.items():
        dialect_caps = info.dialect(dialect)
        if dialect_caps:
            result.append((name, info, dialect_caps))

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# Capability Composition
# ═══════════════════════════════════════════════════════════════════════════════


def merge_capabilities(
    *cap_tuples: tuple[SchemaAxisCapability, ...],
) -> tuple[SchemaAxisCapability, ...]:
    """Merge capability tuples, later overrides earlier by type.

    Args:
        *cap_tuples: Variable number of capability tuples

    Returns:
        Merged tuple with one capability per type

    Example:
        base = (MaxLen(100), Doc("Name"))
        override = (MaxLen(50),)  # Override MaxLen
        merged = merge_capabilities(base, override)
        # Result: (Doc("Name"), MaxLen(50))
    """
    seen: CapabilityByType = {}
    for caps in cap_tuples:
        for cap in caps:
            seen[type(cap)] = cap
    return tuple(seen.values())


def override_capability(
    caps: tuple[SchemaAxisCapability, ...],
    new_cap: SchemaAxisCapability,
) -> tuple[SchemaAxisCapability, ...]:
    """Replace capability of same type with new one.

    Args:
        caps: Original capabilities
        new_cap: New capability to insert

    Returns:
        New tuple with capability replaced
    """
    cap_type = type(new_cap)
    result = [cap for cap in caps if not isinstance(cap, cap_type)]
    result.append(new_cap)
    return tuple(result)


def remove_capability(
    caps: tuple[SchemaAxisCapability, ...],
    cap_type: type[SchemaAxisCapability],
) -> tuple[SchemaAxisCapability, ...]:
    """Remove all capabilities of specific type.

    Args:
        caps: Original capabilities
        cap_type: Type to remove

    Returns:
        New tuple without capabilities of that type
    """
    return tuple(cap for cap in caps if not isinstance(cap, cap_type))


def deduplicate_capabilities(
    caps: tuple[SchemaAxisCapability, ...],
) -> tuple[SchemaAxisCapability, ...]:
    """Remove duplicate capabilities (by type, keep last).

    Delegates to merge_capabilities — same semantics for single tuple.

    Args:
        caps: Capabilities that may have duplicates

    Returns:
        Deduplicated tuple
    """
    return merge_capabilities(caps)


def filter_by_dialect[D: SchemaAxisCapability](
    caps: tuple[SchemaAxisCapability, ...],
    dialect: type[D],
) -> tuple[D, ...]:
    """Get capabilities for specific dialect.

    Args:
        caps: Capabilities to filter
        dialect: Dialect base type (e.g. SQLCapability, CLICapability)

    Returns:
        Tuple of capabilities matching that dialect type
    """
    return tuple(cap for cap in caps if isinstance(cap, dialect))


def filter_universal(
    caps: tuple[SchemaAxisCapability, ...],
) -> tuple[UniversalCapability, ...]:
    """Get only universal capabilities.

    Currently a no-op: UniversalCapability is aliased to SchemaAxisCapability,
    so every schema cap is universal and all of them are kept. When
    UniversalCapability becomes a distinct subtype, reintroduce an
    ``isinstance(cap, UniversalCapability)`` filter here so dialect caps are
    dropped automatically. Dialect separation today is done by filter_by_dialect.
    """
    return tuple(caps)


# ═══════════════════════════════════════════════════════════════════════════════
# Capability Queries
# ═══════════════════════════════════════════════════════════════════════════════


def find_capability[C: SchemaAxisCapability](
    caps: tuple[SchemaAxisCapability, ...],
    cap_type: type[C],
) -> C | None:
    """Get first capability of specific type.

    Args:
        caps: Tuple of capabilities
        cap_type: Type to find

    Returns:
        First matching capability or None
    """
    for cap in caps:
        if isinstance(cap, cap_type):
            return cap
    return None


def find_all_capabilities[C: SchemaAxisCapability](
    caps: tuple[SchemaAxisCapability, ...],
    cap_type: type[C],
) -> tuple[C, ...]:
    """Get all capabilities of specific type.

    Args:
        caps: Tuple of capabilities
        cap_type: Type to find

    Returns:
        Tuple of matching capabilities
    """
    return tuple(cap for cap in caps if isinstance(cap, cap_type))


def has_capability(
    caps: tuple[SchemaAxisCapability, ...],
    cap_type: type[SchemaAxisCapability],
) -> bool:
    """Check if capability of type exists.

    Args:
        caps: Tuple of capabilities
        cap_type: Type to check

    Returns:
        True if capability exists
    """
    return any(isinstance(cap, cap_type) for cap in caps)


# ═══════════════════════════════════════════════════════════════════════════════
# Schema Meta Composition
# ═══════════════════════════════════════════════════════════════════════════════


def compose_schema_meta(
    cls: type,
    overrides: tuple[SchemaAxisCapability, ...] = (),
) -> tuple[SchemaAxisCapability, ...]:
    """Get schema_meta with overrides applied.

    Later capabilities override earlier by type.

    Args:
        cls: Class to get schema_meta from
        overrides: Capabilities to override/add

    Returns:
        Combined schema_meta tuple

    Example:
        # Get Address schema_meta but override name
        caps = compose_schema_meta(Address, (SchemaName("billing"),))
    """
    from emergent.wire.axis.schema._universal import get_schema_meta

    base = get_schema_meta(cls)
    if not overrides:
        return base
    return deduplicate_capabilities((*base, *overrides))


def get_nested_schema_meta(field_info: "FieldInfo") -> tuple[SchemaAxisCapability, ...]:
    """Get effective schema_meta for nested type including field-level overrides.

    Reads Nested.meta or Embedded.meta if present and merges with
    nested type's own schema_meta.

    Args:
        field_info: FieldInfo that may contain a nested structured type

    Returns:
        Combined schema_meta tuple, empty if not a nested type

    Example:
        fields = inspect_type(Order)
        nested_caps = get_nested_schema_meta(fields["items"])
    """
    from emergent.wire.axis.schema._universal import Nested, Embedded, get_schema_meta
    from emergent.wire.axis.schema._inspect import unwrap_collection, is_structured_type

    inner = unwrap_collection(field_info.base_type)
    if not is_structured_type(inner):
        return ()

    # Get base schema_meta from nested type
    base = get_schema_meta(inner)

    # Check for override in Nested or Embedded capability
    nested = field_info.get(Nested)
    embedded = field_info.get(Embedded)

    overrides: tuple[SchemaAxisCapability, ...] = ()
    if nested is not None and nested.meta:
        overrides = nested.meta
    elif embedded is not None and embedded.meta:
        overrides = embedded.meta

    if not overrides:
        return base

    return deduplicate_capabilities((*base, *overrides))


__all__ = (
    # Navigation
    "get_identity_field",
    "get_required_fields",
    "get_optional_fields",
    "partition_fields",
    "field_by_name",
    "field_path_type",
    "fields_with_capability",
    "get_refs",
    "fields_by_dialect",
    # Composition
    "merge_capabilities",
    "override_capability",
    "remove_capability",
    "deduplicate_capabilities",
    "filter_by_dialect",
    "filter_universal",
    # Queries
    "find_capability",
    "find_all_capabilities",
    "has_capability",
    # Schema meta composition
    "compose_schema_meta",
    "get_nested_schema_meta",
)

"""Schema introspection — pure composable type inspection.

Unified inspection for ANY structured type (dataclass, Pydantic, TypedDict, NamedTuple).

    from emergent.wire.axis.schema import inspect_type, FieldInfo
    from emergent.wire.axis.schema.dialects.sql import SQLCapability

    # Works for any supported type
    fields = inspect_type(User)  # dataclass, Pydantic, TypedDict, NamedTuple

    for name, info in fields.items():
        print(f"{name}: {info.base_type}")
        print(f"  universal: {info.universal}")
        print(f"  sql: {info.dialect(SQLCapability)}")

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
from typing import (
    Annotated,
    Any,
    Protocol,
    Union,
    get_args,
    get_origin,
    get_type_hints,
    runtime_checkable,
)

from emergent.wire.axis.schema._universal import (
    SchemaAxisCapability,
    UniversalCapability,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Type Alias
# ═══════════════════════════════════════════════════════════════════════════════


# Inspector: pure function that inspects a type, returns None if can't handle
type Inspector = Callable[[type], dict[str, FieldInfo] | None]


# ═══════════════════════════════════════════════════════════════════════════════
# Field Info
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class FieldInfo:
    """Extracted information about a structured type field."""

    name: str
    base_type: type
    is_optional: bool
    capabilities: tuple[SchemaAxisCapability, ...]
    has_default: bool = False

    @property
    def universal(self) -> tuple[UniversalCapability, ...]:
        """Get universal capabilities."""
        return tuple(c for c in self.capabilities if isinstance(c, UniversalCapability))

    def dialect[D: SchemaAxisCapability](self, base: type[D]) -> tuple[D, ...]:
        """Get capabilities for specific dialect by base type.

        No global registry — pass the dialect base class directly.

        Example::

            from emergent.wire.axis.schema.dialects.sql import SQLCapability
            sql_caps = field_info.dialect(SQLCapability)

            # Equivalent to:
            sql_caps = field_info.get_all(SQLCapability)
        """
        return tuple(c for c in self.capabilities if isinstance(c, base))

    def has(self, cap_type: type[SchemaAxisCapability]) -> bool:
        """Check if field has specific capability type."""
        return any(isinstance(c, cap_type) for c in self.capabilities)

    def get[C: SchemaAxisCapability](self, cap_type: type[C]) -> C | None:
        """Get first capability of specific type."""
        for c in self.capabilities:
            if isinstance(c, cap_type):
                return c
        return None

    def get_all[C: SchemaAxisCapability](self, cap_type: type[C]) -> tuple[C, ...]:
        """Get all capabilities of specific type."""
        return tuple(c for c in self.capabilities if isinstance(c, cap_type))


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


def _to_capability(ann: object) -> SchemaAxisCapability | None:
    """Convert annotation to capability instance.

    Supports both:
    - Instance: Identity() → use as-is
    - Class: Identity → instantiate with no args
    """
    if isinstance(ann, SchemaAxisCapability):
        return ann
    if isinstance(ann, type) and issubclass(ann, SchemaAxisCapability):
        # Class form — instantiate (works for no-arg capabilities like Identity, Unique)
        return ann()
    return None


def extract_capabilities(annotations: list[Any]) -> tuple[SchemaAxisCapability, ...]:
    """Extract SchemaAxisCapability instances from annotations.

    Supports both class and instance forms:
    - Annotated[int, Identity] — class form, auto-instantiated
    - Annotated[int, Identity()] — instance form
    - Annotated[int, MaxLen(255)] — instance with args
    """
    capabilities: list[SchemaAxisCapability] = []

    for ann in annotations:
        cap = _to_capability(ann)
        if cap is not None:
            capabilities.append(cap)
        elif isinstance(ann, tuple):
            # Pattern — tuple of capabilities
            for item in ann:  # type: ignore[union-attr]
                cap = _to_capability(item)
                if cap is not None:
                    capabilities.append(cap)

    return tuple(capabilities)


def inspect_field(
    name: str, type_hint: Any, *, has_default: bool = False
) -> FieldInfo:
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
        has_default=has_default,
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
        has_default = (
            field.default is not dataclasses.MISSING
            or field.default_factory is not dataclasses.MISSING
        )
        result[field.name] = inspect_field(
            field.name, type_hint, has_default=has_default
        )

    return result


def pydantic_inspector(cls: type) -> dict[str, FieldInfo] | None:
    """Inspect Pydantic v2 model. Returns None if not a Pydantic model."""
    if not hasattr(cls, "model_fields"):
        return None

    result: dict[str, FieldInfo] = {}
    model_fields: dict[str, Any] = getattr(cls, "model_fields", {})

    # Use get_type_hints to preserve Annotated metadata that pydantic strips
    try:
        hints = get_type_hints(cls, include_extras=True)
    except Exception:
        hints = {}

    for field_name, pydantic_field in model_fields.items():
        # Prefer get_type_hints (preserves Annotated metadata);
        # fall back to pydantic_field.annotation + .metadata
        annotation: Any = hints.get(field_name)
        if annotation is None:
            annotation = getattr(pydantic_field, "annotation", None)
            if annotation is None:
                annotation = str

        # Check if required
        is_required_fn = getattr(pydantic_field, "is_required", None)
        is_optional = not (is_required_fn() if callable(is_required_fn) else True)

        # Extract base type and capabilities from annotation
        base_type, annotations = unwrap_annotated(annotation)

        # If get_type_hints didn't preserve Annotated (annotations empty),
        # fall back to pydantic's .metadata which stores non-pydantic metadata
        if not annotations:
            extra_meta = getattr(pydantic_field, "metadata", None)
            if extra_meta:
                annotations = list(extra_meta)

        base_type, is_optional_from_type = unwrap_optional(base_type)
        is_optional = is_optional or is_optional_from_type

        capabilities = extract_capabilities(annotations)

        # has_default: pydantic field is not required (has default or default_factory)
        has_default = not (is_required_fn() if callable(is_required_fn) else True)

        result[str(field_name)] = FieldInfo(
            name=str(field_name),
            base_type=base_type,
            is_optional=is_optional,
            capabilities=capabilities,
            has_default=has_default,
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

        # TypedDict: optional keys are "not required" → has_default
        has_default = field_name not in required_keys

        result[field_name] = FieldInfo(
            name=field_name,
            base_type=base_type,
            is_optional=is_optional,
            capabilities=capabilities,
            has_default=has_default,
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
            has_default=has_default,
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


# ═══════════════════════════════════════════════════════════════════════════════
# Structured Type Protocols
# ═══════════════════════════════════════════════════════════════════════════════


@runtime_checkable
class PydanticModel(Protocol):
    """Protocol for Pydantic v2 models."""

    model_fields: dict[str, object]


@runtime_checkable
class TypedDictType(Protocol):
    """Protocol for TypedDict types."""

    __required_keys__: frozenset[str]
    __optional_keys__: frozenset[str]


@runtime_checkable
class NamedTupleType(Protocol):
    """Protocol for NamedTuple types."""

    _fields: tuple[str, ...]
    __annotations__: dict[str, type]


# ═══════════════════════════════════════════════════════════════════════════════
# Nested Type Helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _is_dataclass_type(tp: type) -> bool:
    """Check if type is a dataclass."""
    return dataclasses.is_dataclass(tp)


def _is_pydantic_model(tp: type) -> bool:
    """Check if type is a Pydantic v2 model."""
    return hasattr(tp, "model_fields")


def _is_typeddict(tp: type) -> bool:
    """Check if type is a TypedDict."""
    return hasattr(tp, "__required_keys__") and hasattr(tp, "__optional_keys__")


def _is_namedtuple(tp: type) -> bool:
    """Check if type is a NamedTuple."""
    return hasattr(tp, "_fields") and hasattr(tp, "__annotations__")


def is_structured_type(tp: type) -> bool:
    """Check if type is a structured type we can inspect.

    Detects: dataclass, Pydantic v2, TypedDict, NamedTuple.

    Example:
        is_structured_type(User)  # True (dataclass)
        is_structured_type(str)   # False (primitive)
    """
    return (
        _is_dataclass_type(tp)
        or _is_pydantic_model(tp)
        or _is_typeddict(tp)
        or _is_namedtuple(tp)
    )


def unwrap_collection(tp: type) -> type:
    """Unwrap list[X], set[X], frozenset[X], tuple[X, ...] to get inner type X.

    Returns original type if not a collection.

    Example:
        unwrap_collection(list[User])  # User
        unwrap_collection(User)        # User
    """
    origin = get_origin(tp)
    if origin in (list, set, frozenset):
        args = get_args(tp)
        if args and isinstance(args[0], type):
            return args[0]
    if origin is tuple:
        args = get_args(tp)
        # tuple[X, ...] = homogeneous tuple
        if args and len(args) == 2 and args[1] is ... and isinstance(args[0], type):
            return args[0]
    return tp


def get_nested_info(field_info: FieldInfo) -> dict[str, FieldInfo] | None:
    """If field's base_type is a structured type, return its fields. Otherwise None.

    Handles collections (list[User] -> User fields).

    Example:
        fields = inspect_type(Order)
        user_fields = get_nested_info(fields["user"])  # User's fields or None
    """
    inner = unwrap_collection(field_info.base_type)

    if not is_structured_type(inner):
        return None

    try:
        return inspect_type(inner)
    except TypeError:
        return None


def get_nested_type(field_info: FieldInfo) -> type | None:
    """Get the nested structured type from a field, or None.

    Handles collections (list[User] -> User).

    Example:
        fields = inspect_type(Order)
        nested = get_nested_type(fields["items"])  # OrderItem or None
    """
    inner = unwrap_collection(field_info.base_type)
    if is_structured_type(inner):
        return inner
    return None


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
    # Nested type helpers
    "is_structured_type",
    "unwrap_collection",
    "get_nested_info",
    "get_nested_type",
)

"""Delta dialect — field-level change tracking for event sourcing.

Provides capabilities for:
- Delta fields: mark fields that support incremental updates
- Delta types: generated types for field changes
- Delta operations: add, set, append, remove, etc.

Usage:
    from emergent.wire.axis.schema.dialects.delta import (
        DeltaField, NumericDelta, StringDelta, CollectionDelta,
        delta_type, apply_delta
    )

    @dataclass
    class Account:
        id: Annotated[int, Identity]
        balance: Annotated[int, DeltaField("numeric")]
        tags: Annotated[list[str], DeltaField("collection")]

    # Generate delta type
    AccountDelta = delta_type(Account)

    # Create delta
    delta = AccountDelta(
        balance=NumericDelta(add=100),
        tags=CollectionDelta(push=("vip",)),
    )

    # Apply delta
    new_account = apply_delta(account, delta)
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields as dc_fields, make_dataclass, replace as dc_replace
from typing import TYPE_CHECKING, Any, Generic, Literal, TypeVar, cast

from emergent.wire.axis.schema._universal import SchemaAxisCapability

if TYPE_CHECKING:
    from emergent.wire.axis._capability import DeltaContext, OpenAPIContext

T = TypeVar("T")
E = TypeVar("E")


# ============================================================================
# Delta Field Capability
# ============================================================================


@dataclass(frozen=True, slots=True)
class DeltaField(SchemaAxisCapability):
    """Mark field as supporting delta operations.

    Delta types:
    - "numeric": supports add, subtract, multiply, set
    - "string": supports append, prepend, replace, set
    - "collection": supports push, pop, insert, remove, set

    Example:
        @dataclass
        class Account:
            balance: Annotated[int, DeltaField("numeric")]
            notes: Annotated[str, DeltaField("string")]
            tags: Annotated[list[str], DeltaField("collection")]
    """

    delta_type: Literal["numeric", "string", "collection"]

    def compile_delta(self, ctx: "DeltaContext") -> "DeltaContext":
        from dataclasses import replace
        return replace(ctx, delta_kind=self.delta_type)

    def compile_openapi(self, ctx: "OpenAPIContext") -> "OpenAPIContext":
        from emergent.wire.axis._capability import openapi_schema
        return openapi_schema(ctx, **{"x-delta-type": self.delta_type})


# ============================================================================
# Delta Operations
# ============================================================================


@dataclass(frozen=True, slots=True)
class NumericDelta:
    """Delta operations for numeric fields.

    Operations are applied in order: add → multiply → set.
    If set is provided, it overrides other operations.

    Example:
        NumericDelta(add=100)           # balance += 100
        NumericDelta(add=-50)           # balance -= 50
        NumericDelta(multiply=1.1)      # balance *= 1.1
        NumericDelta(set=0)             # balance = 0
    """

    add: int | float | None = None
    multiply: float | None = None
    set: int | float | None = None

    def apply(self, value: int | float) -> int | float:
        """Apply delta to value."""
        if self.set is not None:
            return self.set

        result: int | float = value
        if self.add is not None:
            result = result + self.add
        if self.multiply is not None:
            result = result * self.multiply

        # Preserve int type if original was int and result is whole number
        if isinstance(value, int):
            int_result = int(result)
            if float(result) == float(int_result):
                return int_result
        return result


@dataclass(frozen=True, slots=True)
class StringDelta:
    """Delta operations for string fields.

    Operations are applied in order: prepend → append → replace → set.
    If set is provided, it overrides other operations.

    Example:
        StringDelta(append=" (updated)")
        StringDelta(prepend="[URGENT] ")
        StringDelta(replace=("old", "new"))
        StringDelta(set="completely new value")
    """

    append: str | None = None
    prepend: str | None = None
    replace: tuple[str, str] | None = None  # (old, new)
    set: str | None = None

    def apply(self, value: str) -> str:
        """Apply delta to value."""
        if self.set is not None:
            return self.set

        result = value
        if self.prepend is not None:
            result = self.prepend + result
        if self.append is not None:
            result = result + self.append
        if self.replace is not None:
            old, new = self.replace
            result = result.replace(old, new)

        return result


@dataclass(frozen=True, slots=True)
class CollectionDelta(Generic[T]):
    """Delta operations for collection fields.

    Operations are applied in order: remove → pop → push → insert → set.
    If set is provided, it overrides other operations.

    Example:
        CollectionDelta(push=("new_item",))
        CollectionDelta(pop=1)  # Remove 1 from end
        CollectionDelta(remove=("old_item",))
        CollectionDelta(insert=(0, "first"))  # Insert at index 0
        CollectionDelta(set=("a", "b", "c"))
    """

    push: tuple[T, ...] = ()
    pop: int = 0  # Number to pop from end
    remove: tuple[T, ...] = ()
    insert: tuple[int, T] | None = None  # (index, value)
    set: tuple[T, ...] | None = None

    def apply(self, value: list[T]) -> list[T]:
        """Apply delta to value."""
        if self.set is not None:
            return list(self.set)

        result = list(value)

        # Remove specified items
        for item in self.remove:
            if item in result:
                result.remove(item)

        # Pop from end
        for _ in range(self.pop):
            if result:
                result.pop()

        # Push to end
        result.extend(self.push)

        # Insert at index
        if self.insert is not None:
            index, item = self.insert
            result.insert(index, item)

        return result


# Type alias for any delta
AnyDelta = NumericDelta | StringDelta | CollectionDelta[Any]


# ============================================================================
# Delta Type Generator
# ============================================================================


def delta_type(entity: type[E]) -> type:
    """Generate delta type from entity.

    Inspects entity fields for DeltaField capabilities and creates
    a corresponding delta dataclass.

    Example:
        @dataclass
        class Account:
            id: int
            balance: Annotated[int, DeltaField("numeric")]
            tags: Annotated[list[str], DeltaField("collection")]

        AccountDelta = delta_type(Account)
        # Generates:
        # @dataclass
        # class AccountDelta:
        #     balance: NumericDelta | None = None
        #     tags: CollectionDelta[str] | None = None

    Returns:
        Generated delta dataclass type.
    """
    from emergent.wire.axis.schema import inspect_type
    from emergent.wire.compile._core import fold_field
    from emergent.wire.axis._capability import DeltaContext, DeltaCompilable

    fields_info = inspect_type(entity)
    # make_dataclass accepts various tuple formats including (name, type, field_spec)
    delta_fields: list[tuple[str, Any, Any]] = []

    for name, info in fields_info.items():
        ctx = fold_field(
            info,
            DeltaContext(field_name=name, field_type=info.base_type),
            DeltaCompilable,
            "compile_delta",
        )
        if ctx.delta_kind is None:
            continue

        match ctx.delta_kind:
            case "numeric":
                delta_fields.append((
                    name,
                    cast(type, NumericDelta | None),
                    field(default=None),
                ))
            case "string":
                delta_fields.append((
                    name,
                    cast(type, StringDelta | None),
                    field(default=None),
                ))
            case "collection":
                # Extract element type from list[T]
                delta_fields.append((
                    name,
                    cast(type, CollectionDelta[Any] | None),
                    field(default=None),
                ))
            case _:
                msg = f"Unknown delta kind: {ctx.delta_kind!r}"
                raise ValueError(msg)

    return make_dataclass(
        f"{entity.__name__}Delta",
        delta_fields,
        frozen=True,
        slots=True,
    )


# ============================================================================
# Delta Application
# ============================================================================


def apply_delta(entity: E, delta: Any) -> E:
    """Apply delta to entity, returning new entity.

    Works with frozen dataclasses. Does not mutate original.

    Example:
        account = Account(id=1, balance=100, tags=["basic"])
        delta = AccountDelta(
            balance=NumericDelta(add=50),
            tags=CollectionDelta(push=("premium",)),
        )
        new_account = apply_delta(account, delta)
        # new_account.balance == 150
        # new_account.tags == ["basic", "premium"]

    Returns:
        New entity instance with delta applied.
    """
    changes: dict[str, Any] = {}

    for delta_field in dc_fields(delta):
        field_delta = getattr(delta, delta_field.name)
        if field_delta is None:
            continue

        current_value = getattr(entity, delta_field.name)
        new_value = field_delta.apply(current_value)
        changes[delta_field.name] = new_value

    if not changes:
        return entity

    # Cast needed: dc_replace requires DataclassInstance but E is generic TypeVar
    # Safe at runtime: apply_delta is only called with dataclass instances
    return cast(E, dc_replace(cast(Any, entity), **changes))


def compose_deltas(*deltas: Any) -> Any:
    """Compose multiple deltas into one.

    Later deltas override earlier ones for the same field.
    For numeric deltas, additions are summed.

    Example:
        d1 = AccountDelta(balance=NumericDelta(add=100))
        d2 = AccountDelta(balance=NumericDelta(add=50))
        combined = compose_deltas(d1, d2)
        # combined.balance == NumericDelta(add=150)
    """
    if not deltas:
        raise ValueError("At least one delta required")

    if len(deltas) == 1:
        return deltas[0]

    # Cast needed: type() returns concrete class at runtime, but pyright
    # cannot infer the type from *deltas varargs
    delta_type_cls = cast(type[Any], type(deltas[0]))
    composed: dict[str, Any] = {}

    for delta in deltas:
        for delta_field in dc_fields(delta):
            field_delta = getattr(delta, delta_field.name)
            if field_delta is None:
                continue

            existing = composed.get(delta_field.name)
            if existing is None:
                composed[delta_field.name] = field_delta
            else:
                # Compose same-type deltas
                composed[delta_field.name] = _compose_field_deltas(existing, field_delta)

    return delta_type_cls(**composed)


def _compose_field_deltas(d1: AnyDelta, d2: AnyDelta) -> AnyDelta:
    """Compose two field deltas of the same type."""
    if isinstance(d1, NumericDelta) and isinstance(d2, NumericDelta):
        # Sum additions, multiply multipliers, last set wins
        add = None
        if d1.add is not None or d2.add is not None:
            add = (d1.add or 0) + (d2.add or 0)

        multiply = None
        if d1.multiply is not None and d2.multiply is not None:
            multiply = d1.multiply * d2.multiply
        elif d2.multiply is not None:
            multiply = d2.multiply
        elif d1.multiply is not None:
            multiply = d1.multiply

        set_val = d2.set if d2.set is not None else d1.set

        return NumericDelta(add=add, multiply=multiply, set=set_val)

    if isinstance(d1, StringDelta) and isinstance(d2, StringDelta):
        # Last non-None wins for each operation
        return StringDelta(
            append=d2.append if d2.append is not None else d1.append,
            prepend=d2.prepend if d2.prepend is not None else d1.prepend,
            replace=d2.replace if d2.replace is not None else d1.replace,
            set=d2.set if d2.set is not None else d1.set,
        )

    # Check CollectionDelta using attribute check to avoid generic type issues
    if hasattr(d1, "push") and hasattr(d2, "push"):
        d1_coll = cast(CollectionDelta[Any], d1)
        d2_coll = cast(CollectionDelta[Any], d2)
        # Combine pushes/removes, sum pops, last set/insert wins
        return CollectionDelta(
            push=(*d1_coll.push, *d2_coll.push),
            pop=d1_coll.pop + d2_coll.pop,
            remove=(*d1_coll.remove, *d2_coll.remove),
            insert=d2_coll.insert if d2_coll.insert is not None else d1_coll.insert,
            set=d2_coll.set if d2_coll.set is not None else d1_coll.set,
        )

    # Different types - last wins
    return d2


# ============================================================================
# Delta Validation
# ============================================================================


def validate_delta(delta: Any, entity_type: type) -> list[str]:
    """Validate delta against entity type.

    Checks:
    - All delta fields exist on entity
    - Delta types match field types
    - Numeric deltas don't overflow (optional)

    Returns:
        List of validation error messages (empty if valid).
    """
    from emergent.wire.axis.schema import inspect_type
    from emergent.wire.compile._core import fold_field
    from emergent.wire.axis._capability import DeltaContext, DeltaCompilable

    errors: list[str] = []
    fields_info = inspect_type(entity_type)

    for delta_field in dc_fields(delta):
        field_delta = getattr(delta, delta_field.name)
        if field_delta is None:
            continue

        if delta_field.name not in fields_info:
            errors.append(f"Field '{delta_field.name}' not found on {entity_type.__name__}")
            continue

        info = fields_info[delta_field.name]
        ctx = fold_field(
            info,
            DeltaContext(field_name=delta_field.name, field_type=info.base_type),
            DeltaCompilable,
            "compile_delta",
        )

        if ctx.delta_kind is None:
            errors.append(
                f"Field '{delta_field.name}' is not marked with DeltaField capability"
            )
            continue

        # Type check
        expected = ctx.delta_kind
        actual = _delta_kind(field_delta)
        if expected != actual:
            errors.append(
                f"Field '{delta_field.name}' expects {expected} delta, got {actual}"
            )

    return errors


def _delta_kind(delta: AnyDelta) -> str:
    """Get delta kind string."""
    if isinstance(delta, NumericDelta):
        return "numeric"
    if isinstance(delta, StringDelta):
        return "string"
    # Use hasattr for CollectionDelta to avoid generic type issues with isinstance
    if hasattr(delta, "push"):
        return "collection"
    return "unknown"


# ============================================================================
# Exports
# ============================================================================

__all__ = (
    # Capability
    "DeltaField",
    # Delta types
    "NumericDelta",
    "StringDelta",
    "CollectionDelta",
    "AnyDelta",
    # Type generation
    "delta_type",
    # Application
    "apply_delta",
    "compose_deltas",
    # Validation
    "validate_delta",
)

"""Compiler core — axes context, fold primitive, and common types.

Functional compiler infrastructure. Axes passed explicitly, no global state.

    from emergent.wire.compile import Axes, fold_field

    axes = Axes.default()

## fold_field — THE compilation primitive

    ctx = fold_field(field_info, initial_ctx, PydanticCompilable, "compile_pydantic")

Every compilation target uses the same fold: iterate capabilities,
call compile_* on each that implements the protocol, accumulate context.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Callable, Protocol, TYPE_CHECKING

from emergent.wire.axis.schema import inspect_dataclass, FieldInfo

if TYPE_CHECKING:
    from nodnod import Scope
    from emergent.wire.compile._trace import TraceCollector
    from emergent.wire.compile._lifetime import ScopeLayer
from emergent.wire.axis._capability import Capability, ConstraintsContext, ConstraintsCompilable

# ═══════════════════════════════════════════════════════════════════════════════
# Scope Setup Protocol
# ═══════════════════════════════════════════════════════════════════════════════


class ScopeSetup(Protocol):
    """Protocol for framework-specific scope setup.

    Each framework injects its own types into nodnod Scope.
    This abstracts the setup so adapters can share code.

    Example:
        class FastAPIScopeSetup:
            def __init__(self, request: Request, pydantic_types: set[type]):
                self.request = request
                self.pydantic_types = pydantic_types

            async def setup(self, scope: Scope) -> None:
                scope.inject(Request, self.request)
                # ... pydantic handling
    """

    async def setup(self, scope: Scope) -> None:
        """Inject framework-specific types into scope."""
        ...


# ═══════════════════════════════════════════════════════════════════════════════
# Axes Context
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Axes:
    """Multi-axis context for compilation.

    Passed explicitly to all compiler functions.
    No global state, easy to test.

    Attributes:
        schema: Function to inspect dataclass fields with capabilities.
        trace: Optional trace collector. None = no tracing (zero overhead).
    """

    schema: Callable[[type], dict[str, FieldInfo]]
    trace: TraceCollector | None = None
    scope_layer: ScopeLayer | None = None

    @classmethod
    def default(cls) -> Axes:
        """Create default axes with standard introspection."""
        return cls(schema=inspect_dataclass)

    @classmethod
    def traced(cls, collector: TraceCollector | None = None) -> Axes:
        """Create default axes with tracing enabled.

        If no collector provided, creates a ListCollector.

            axes = Axes.traced()
            Model = to_pydantic(User, axes)
            print(explain(axes))
        """
        from emergent.wire.compile._trace import ListCollector

        return cls(
            schema=inspect_dataclass,
            trace=collector if collector is not None else ListCollector(),
        )

    def with_scope_layer(self, layer: ScopeLayer) -> Axes:
        """Return new Axes with scope_layer set."""
        return Axes(
            schema=self.schema,
            trace=self.trace,
            scope_layer=layer,
        )


# ═══════════════════════════════════════════════════════════════════════════════
# fold — THE universal primitive
# ═══════════════════════════════════════════════════════════════════════════════


from collections.abc import Iterable


type ItemHandler[Ctx] = Callable[[Any, Ctx], Ctx]
type CapabilityHandler[Ctx] = Callable[[Capability, Ctx], Ctx]


def fold[Ctx](
    items: Iterable[Any],
    initial: Ctx,
    protocol: type,
    method: str,
    handlers: Mapping[type, ItemHandler[Ctx]] | None = None,
    *,
    trace: TraceCollector | None = None,
) -> Ctx:
    """Generic protocol-dispatch fold — THE universal primitive.

    Iterates items, calls method on each that implements protocol.
    Custom handlers override protocol dispatch by item type.
    Unknown items silently skipped (open-world).

    When trace is set, delegates to traced_fold() for full trace emission.
    Zero overhead when trace is None (default) — just one branch prediction.

    Used by:
        fold_field — fold over field.capabilities (compile)
        target compilers — fold over surface capabilities (FastAPICompilable, etc.)
        derivelib.fold_steps — fold over derivation steps (derive)

    Args:
        items: Iterable of items to fold over
        initial: Starting context
        protocol: Protocol type to check (isinstance)
        method: Method name to call (getattr)
        handlers: Optional custom handlers keyed by item type
        trace: Optional trace collector (keyword-only)

    Returns:
        Final accumulated context after all items applied
    """
    if trace is not None:
        result, _ = traced_fold(items, initial, protocol, method, handlers, trace)
        return result
    ctx = initial
    for item in items:
        item_cls: type = item.__class__
        if handlers and item_cls in handlers:
            ctx = handlers[item_cls](item, ctx)
        elif isinstance(item, protocol):
            ctx = getattr(item, method)(ctx)
    return ctx


def fold_field[Ctx](
    field: FieldInfo,
    initial: Ctx,
    protocol: type,
    compile_method: str,
    handlers: Mapping[type[Capability], CapabilityHandler[Ctx]] | None = None,
    *,
    trace: TraceCollector | None = None,
) -> Ctx:
    """Field-level capability fold — thin wrapper over fold().

    Example:
        ctx = fold_field(field, PydanticContext(...), PydanticCompilable, "compile_pydantic")
    """
    return fold(field.capabilities, initial, protocol, compile_method, handlers, trace=trace)


def fold_schema[Ctx](
    cls: type,
    initial: Ctx,
    protocol: type,
    compile_method: str,
    *,
    trace: TraceCollector | None = None,
) -> Ctx:
    """Schema-level capability fold — iterates get_schema_meta(cls).

    Example:
        ctx = fold_schema(cls, TgHelpContext(), TgHelpCompilable, "compile_tg_help")
    """
    from emergent.wire.axis.schema._universal import get_schema_meta
    return fold(get_schema_meta(cls), initial, protocol, compile_method, trace=trace)


def traced_fold[Ctx](
    items: Iterable[Any],
    initial: Ctx,
    protocol: type,
    method: str,
    handlers: Mapping[type, ItemHandler[Ctx]] | None,
    collector: TraceCollector,
) -> tuple[Ctx, Any]:
    """fold() with trace emission. Returns (result_ctx, FoldTrace).

    Same logic as fold() but records a FoldStep per item and emits
    a FoldTrace on completion. fold() itself is never touched.

    The production hot path (fold) has zero overhead.
    This function is only called when axes.trace is set.
    """
    from emergent.wire.compile._trace import FoldStep, FoldTrace

    ctx = initial
    steps: list[FoldStep] = []
    items_applied = 0

    for item in items:
        item_cls: type = item.__class__
        ctx_before = ctx

        if handlers and item_cls in handlers:
            ctx = handlers[item_cls](item, ctx)
            dispatch = "handler"
        elif isinstance(item, protocol):
            ctx = getattr(item, method)(ctx)
            dispatch = "protocol"
        else:
            dispatch = "skipped"

        step = FoldStep(
            item_type=item_cls.__qualname__,
            dispatch=dispatch,
            method=method,
            context_before=ctx_before,
            context_after=ctx,
            changed=ctx_before is not ctx,
        )
        collector.fold_step(step)
        steps.append(step)

        if dispatch != "skipped":
            items_applied += 1

    fold_trace = FoldTrace(
        protocol=protocol.__qualname__,
        method=method,
        initial=initial,
        final=ctx,
        steps=tuple(steps),
        items_total=len(steps),
        items_applied=items_applied,
    )
    collector.fold_complete(fold_trace)
    return ctx, fold_trace


# ═══════════════════════════════════════════════════════════════════════════════
# Field Constraint Extraction
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class FieldConstraints:
    """Extracted constraints from schema capabilities.

    Universal representation that any framework can use.
    """

    min_length: int | None = None
    max_length: int | None = None
    min_value: float | None = None
    max_value: float | None = None
    pattern: str | None = None
    choices: tuple[Any, ...] | None = None
    is_identity: bool = False
    is_unique: bool = False
    is_optional: bool = False


def extract_constraints(info: FieldInfo) -> FieldConstraints:
    """Extract universal constraints from FieldInfo.

    Pure function: FieldInfo → FieldConstraints.
    Uses fold_field through ConstraintsCompilable protocol.
    """
    ctx = fold_field(
        info,
        ConstraintsContext(field_name=info.name, field_type=info.base_type),
        ConstraintsCompilable,
        "compile_constraints",
    )
    return FieldConstraints(
        min_length=ctx.min_length,
        max_length=ctx.max_length,
        min_value=ctx.min_value,
        max_value=ctx.max_value,
        pattern=ctx.pattern,
        choices=ctx.choices,
        is_identity=ctx.is_identity,
        is_unique=ctx.is_unique,
        is_optional=info.is_optional,
    )


def extract_all_constraints(
    cls: type, axes: Axes
) -> dict[str, tuple[type, FieldConstraints]]:
    """Extract constraints for all fields of a dataclass.

    Returns: {field_name: (base_type, constraints)}
    """
    fields = axes.schema(cls)
    return {
        name: (info.base_type, extract_constraints(info))
        for name, info in fields.items()
    }


__all__ = (
    "ScopeSetup",
    "Axes",
    "ItemHandler",
    "CapabilityHandler",
    "fold",
    "fold_field",
    "fold_schema",
    "traced_fold",
    "FieldConstraints",
    "extract_constraints",
    "extract_all_constraints",
)

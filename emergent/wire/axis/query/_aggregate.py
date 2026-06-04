"""Aggregate expressions — typed, no strings.

Aggregate functions are typed capabilities, not string identifiers.

    from emergent.wire.axis.query._aggregate import Sum, Avg, Count

    # In FieldProxy methods:
    u.balance.sum()  → AggregateExpr(Sum(), "balance")
    u.count()        → AggregateExpr(Count(), None)

Providers pattern-match on AggregateFunc types:

    match spec.func:
        case Sum(): result = sum(values)
        case Avg(): result = sum(values) / len(values)
        case Count(): result = len(data)
"""

from __future__ import annotations

from abc import ABC
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from emergent.wire.axis.query._proxy import FieldProxy, OrderSpec
    from emergent.wire.axis.query._window import WindowSpec

_Ctx = TypeVar("_Ctx")


# ═══════════════════════════════════════════════════════════════════════════════
# Aggregate Functions (typed, not strings)
# ═══════════════════════════════════════════════════════════════════════════════


class AggregateFunc(ABC):
    """Base for aggregate functions.

    Subclasses are markers that providers pattern-match on.
    No string identifiers — fully typed.
    """

    pass


@dataclass(frozen=True, slots=True)
class Count(AggregateFunc):
    """COUNT aggregate.

    Usage:
        u.count()       → COUNT(*)     when field is None
        u.id.count()    → COUNT(id)    when field is set
    """

    pass


@dataclass(frozen=True, slots=True)
class Sum(AggregateFunc):
    """SUM aggregate.

    Usage:
        u.balance.sum() → SUM(balance)
    """

    pass


@dataclass(frozen=True, slots=True)
class Avg(AggregateFunc):
    """AVG aggregate.

    Usage:
        u.balance.avg() → AVG(balance)
    """

    pass


@dataclass(frozen=True, slots=True)
class Min(AggregateFunc):
    """MIN aggregate.

    Usage:
        u.balance.min() → MIN(balance)
    """

    pass


@dataclass(frozen=True, slots=True)
class Max(AggregateFunc):
    """MAX aggregate.

    Usage:
        u.balance.max() → MAX(balance)
    """

    pass


@dataclass(frozen=True, slots=True)
class ArrayAgg(AggregateFunc):
    """ARRAY_AGG aggregate — collect values into array.

    Usage:
        u.name.array_agg() → ARRAY_AGG(name)
    """

    pass


@dataclass(frozen=True, slots=True)
class StringAgg(AggregateFunc):
    """STRING_AGG aggregate — concatenate values with separator.

    Usage:
        u.name.string_agg(", ") → STRING_AGG(name, ', ')
    """

    separator: str = ","


# ═══════════════════════════════════════════════════════════════════════════════
# Aggregate Spec — func + field + alias
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class AggregateSpec:
    """Single aggregate specification.

    Created by lambda in aggregate():
        .aggregate(total=lambda u: u.balance.sum())
        # → AggregateSpec(func=Sum(), field="balance", alias="total")
    """

    func: AggregateFunc  # Typed! Not string
    field: str | None  # None for COUNT(*)
    alias: str


# ═══════════════════════════════════════════════════════════════════════════════
# Aggregate Expression
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class AggregateExpr:
    """Typed aggregate expression = function + field.

    Combines an AggregateFunc with optional field name.
    COUNT(*) has field=None, others have field name.

    Created by FieldProxy methods:
        u.balance.sum()  → AggregateExpr(Sum(), "balance")
        u.count()        → AggregateExpr(Count(), None)

    Can be used in window context via .over():
        u.balance.sum().over(partition_by=u.department)
    """

    func: AggregateFunc
    field: str | None  # None for COUNT(*)

    def over(
        self,
        partition_by: FieldProxy | tuple[FieldProxy, ...] | None = None,
        order_by: OrderSpec | tuple[OrderSpec, ...] | FieldProxy | tuple[FieldProxy, ...] | None = None,
    ) -> WindowSpec:
        """Create window specification from this aggregate.

        Usage:
            u.balance.sum().over(partition_by=u.department, order_by=u.salary.desc())

        Returns:
            WindowSpec with this aggregate function.
        """
        from emergent.wire.axis.query._sql import WindowBuilder

        return WindowBuilder(self.func, self.field).over(partition_by, order_by)


# ═══════════════════════════════════════════════════════════════════════════════
# Aggregate Fold — flat dispatch over AggregateFunc types
# ═══════════════════════════════════════════════════════════════════════════════


type AggHandler[Ctx] = Callable[[AggregateSpec, Ctx], object]
type AggHandlerMap[Ctx] = Mapping[type[AggregateFunc], Callable[[AggregateSpec, Ctx], Any]]


def fold_aggregate(
    spec: AggregateSpec,
    ctx: _Ctx,
    handlers: AggHandlerMap[_Ctx],
) -> Any:
    """Dispatch aggregate computation by AggregateFunc type.

    Flat dispatch (not recursive like fold_expr). Looks up handler
    for spec.func's type, calls it with spec and context.

    Args:
        spec: AggregateSpec containing func, field, alias
        handlers: Handlers keyed by AggregateFunc subclass type
        ctx: Provider-specific context (list for memory, SA model for SQL)

    Returns:
        Computed aggregate value

    Raises:
        TypeError: If no handler for the func type
    """
    handler = handlers.get(type(spec.func))
    if handler is not None:
        return handler(spec, ctx)
    raise TypeError(f"Unsupported aggregate: {type(spec.func).__name__}")


__all__ = (
    # Base
    "AggregateFunc",
    # Functions
    "Count",
    "Sum",
    "Avg",
    "Min",
    "Max",
    "ArrayAgg",
    "StringAgg",
    # Spec
    "AggregateSpec",
    # Expression
    "AggregateExpr",
    # Fold
    "AggHandler",
    "fold_aggregate",
)

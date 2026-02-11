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
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from emergent.wire.axis.query._proxy import FieldProxy, OrderSpec
    from emergent.wire.axis.query._window import WindowSpec


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
    # Expression
    "AggregateExpr",
)

"""Window function types — SQL-specific aggregate extensions.

Window functions compute values across rows related to the current row,
without collapsing them into groups.

    ROW_NUMBER() OVER (PARTITION BY department ORDER BY salary DESC)

These extend AggregateFunc because window functions like SUM, AVG
can also be used in OVER() clauses. Window-only functions (ROW_NUMBER,
RANK, etc.) have no meaning outside a window context.

    from emergent.wire.axis.query._window import RowNumber, Rank, WindowSpec

    # Window-only functions:
    RowNumber(), Rank(), DenseRank(), Ntile(4)

    # Aggregate functions in window context:
    Sum(), Avg() — already exist in _aggregate.py, reused via .over()
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from emergent.wire.axis.query._aggregate import AggregateFunc
from emergent.wire.axis.query._proxy import OrderSpec


# ═══════════════════════════════════════════════════════════════════════════════
# Window-Only Functions (no meaning outside OVER clause)
# ═══════════════════════════════════════════════════════════════════════════════


class WindowFunc(AggregateFunc):
    """Base for window-only functions.

    Extends AggregateFunc because window functions participate in the
    same compilation pipeline as aggregates, but they ONLY make sense
    in an OVER() clause (unlike SUM which works both ways).
    """

    pass


@dataclass(frozen=True, slots=True)
class RowNumber(WindowFunc):
    """ROW_NUMBER() — sequential row numbering within partition."""

    pass


@dataclass(frozen=True, slots=True)
class Rank(WindowFunc):
    """RANK() — rank with gaps on ties."""

    pass


@dataclass(frozen=True, slots=True)
class DenseRank(WindowFunc):
    """DENSE_RANK() — rank without gaps on ties."""

    pass


@dataclass(frozen=True, slots=True)
class Ntile(WindowFunc):
    """NTILE(n) — distribute rows into n roughly equal buckets."""

    num_buckets: int


@dataclass(frozen=True, slots=True)
class Lag(WindowFunc):
    """LAG(field, offset, default) — access previous row's value."""

    offset: int = 1
    default: Any = None


@dataclass(frozen=True, slots=True)
class Lead(WindowFunc):
    """LEAD(field, offset, default) — access next row's value."""

    offset: int = 1
    default: Any = None


# ═══════════════════════════════════════════════════════════════════════════════
# Window Specification
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class WindowSpec:
    """Complete window specification = func + field + OVER clause.

    Combines the window/aggregate function with partitioning and ordering.

        WindowSpec(
            func=RowNumber(),
            field=None,           # ROW_NUMBER doesn't need a field
            partition_by=("department",),
            order_by=(OrderSpec("salary", ascending=False),),
            alias="row_num",
        )
    """

    func: AggregateFunc
    field: str | None
    partition_by: tuple[str, ...]
    order_by: tuple[OrderSpec, ...]
    alias: str


__all__ = (
    # Base
    "WindowFunc",
    # Window-only functions
    "RowNumber",
    "Rank",
    "DenseRank",
    "Ntile",
    "Lag",
    "Lead",
    # Specification
    "WindowSpec",
)

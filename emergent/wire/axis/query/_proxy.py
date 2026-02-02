"""Proxy objects for lambda-based expression building.

Allows natural Python syntax in filter lambdas:

    .filter(lambda u: u.balance > 100)

The lambda receives a Proxy object, and operators build Expr AST:
    u.balance → FieldProxy("balance")
    u.balance > 100 → Gt(Field("balance"), Const(100))
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Generic, TypeVar, Callable

from emergent.wire.axis.query._expr import (
    Expr,
    Field,
    Const,
    Eq,
    Ne,
    Lt,
    Le,
    Gt,
    Ge,
    And,
    Or,
    Not,
    In,
    Contains,
    StartsWith,
    EndsWith,
    IsNull,
    IsNotNull,
    # Range
    Between,
    # Pattern matching
    Like,
    ILike,
    Regex,
    # Array operators
    ArrayContains,
    ArrayAny,
    ArrayAll,
    ArrayOverlap,
    # JSON operators
    JsonExtract,
    JsonContains,
    JsonHasKey,
)

from emergent.wire.axis.query._aggregate import (
    AggregateExpr,
    Count,
    Sum,
    Avg,
    Min,
    Max,
    ArrayAgg,
    StringAgg,
)


T = TypeVar("T")


class FieldProxy:
    """Proxy for field access that builds Expr on operators.

    Usage:
        proxy = EntityProxy(User)
        expr = proxy.balance > 100  # → Gt(Field("balance"), Const(100))
    """

    __slots__ = ("name",)

    def __init__(self, name: str) -> None:
        self.name = name

    def _to_expr(self) -> Field:
        return Field(self.name)

    @staticmethod
    def wrap(value: Any) -> Expr:
        """Wrap value as Expr if not already.

        Converts:
        - FieldProxy → Field expression
        - Expr → unchanged
        - other → Const(value)
        """
        if isinstance(value, FieldProxy):
            return value._to_expr()
        if isinstance(value, Expr):
            return value
        return Const(value)

    # Alias for internal use
    _wrap = wrap

    # Comparison operators

    def __eq__(self, other: Any) -> Expr:  # type: ignore[override]
        return Eq(self._to_expr(), self._wrap(other))

    def __ne__(self, other: Any) -> Expr:  # type: ignore[override]
        return Ne(self._to_expr(), self._wrap(other))

    def __lt__(self, other: Any) -> Expr:
        return Lt(self._to_expr(), self._wrap(other))

    def __le__(self, other: Any) -> Expr:
        return Le(self._to_expr(), self._wrap(other))

    def __gt__(self, other: Any) -> Expr:
        return Gt(self._to_expr(), self._wrap(other))

    def __ge__(self, other: Any) -> Expr:
        return Ge(self._to_expr(), self._wrap(other))

    # Logical operators (use & | ~ instead of and or not)

    def __and__(self, other: Expr) -> Expr:
        return And(self._to_expr(), other)

    def __or__(self, other: Expr) -> Expr:
        return Or(self._to_expr(), other)

    def __invert__(self) -> Expr:
        return Not(self._to_expr())

    # Collection methods

    def in_(self, values: list[Any] | tuple[Any, ...]) -> Expr:
        """Check membership: u.status.in_(["active", "pending"])"""
        return In(self._to_expr(), tuple(values))

    def contains(self, substring: str) -> Expr:
        """String contains: u.name.contains("alice")"""
        return Contains(self._to_expr(), substring)

    def startswith(self, prefix: str) -> Expr:
        """String starts with: u.name.startswith("al")"""
        return StartsWith(self._to_expr(), prefix)

    def endswith(self, suffix: str) -> Expr:
        """String ends with: u.name.endswith("ice")"""
        return EndsWith(self._to_expr(), suffix)

    # Null checks

    def is_null(self) -> Expr:
        """Null check: u.deleted_at.is_null()"""
        return IsNull(self._to_expr())

    def is_not_null(self) -> Expr:
        """Not null check: u.email.is_not_null()"""
        return IsNotNull(self._to_expr())

    # Ordering (for order_by)

    def asc(self) -> OrderSpec:
        """Ascending order: u.balance.asc()"""
        return OrderSpec(self.name, ascending=True)

    def desc(self) -> OrderSpec:
        """Descending order: u.balance.desc()"""
        return OrderSpec(self.name, ascending=False)

    # ─── Range ──────────────────────────────────────────────────────────────────

    def between(self, low: Any, high: Any) -> Expr:
        """Range check: u.balance.between(100, 1000)"""
        return Between(self._to_expr(), self._wrap(low), self._wrap(high))

    # ─── Pattern Matching ───────────────────────────────────────────────────────

    def like(self, pattern: str) -> Expr:
        """SQL LIKE: u.email.like('%@gmail.com')

        Pattern: % = any chars, _ = single char.
        """
        return Like(self._to_expr(), pattern)

    def ilike(self, pattern: str) -> Expr:
        """Case-insensitive LIKE: u.email.ilike('%@GMAIL.COM')"""
        return ILike(self._to_expr(), pattern)

    def regex(self, pattern: str) -> Expr:
        """Regex match: u.email.regex(r'^\\w+@\\w+\\.\\w+$')"""
        return Regex(self._to_expr(), pattern)

    # ─── Array Operators ────────────────────────────────────────────────────────

    def array_contains(self, value: Any) -> Expr:
        """Array contains value: u.tags.array_contains('vip')"""
        return ArrayContains(self._to_expr(), value)

    def array_any(self, *values: Any) -> Expr:
        """Array contains any of values: u.tags.array_any('vip', 'admin')"""
        return ArrayAny(self._to_expr(), values)

    def array_all(self, *values: Any) -> Expr:
        """Array contains all values: u.tags.array_all('vip', 'verified')"""
        return ArrayAll(self._to_expr(), values)

    def array_overlap(self, *values: Any) -> Expr:
        """Arrays have overlap: u.tags.array_overlap('a', 'b')"""
        return ArrayOverlap(self._to_expr(), values)

    # ─── JSON Operators ─────────────────────────────────────────────────────────

    def json(self, path: str) -> "JsonFieldProxy":
        """JSON path access: u.metadata.json('profile.name') == 'alice'

        Path is dot-separated: "profile.name" or "users.0.name"
        Returns a JsonFieldProxy that supports comparison operators.
        """
        return JsonFieldProxy(self._to_expr(), path)

    def json_contains(self, value: Any) -> Expr:
        """JSON contains value/structure: u.metadata.json_contains({'role': 'admin'})"""
        return JsonContains(self._to_expr(), value)

    def json_has_key(self, key: str) -> Expr:
        """JSON has key: u.metadata.json_has_key('profile')"""
        return JsonHasKey(self._to_expr(), key)

    # ─── Aggregates ─────────────────────────────────────────────────────────────

    def sum(self) -> AggregateExpr:
        """SUM(field): u.balance.sum()"""
        return AggregateExpr(Sum(), self.name)

    def avg(self) -> AggregateExpr:
        """AVG(field): u.balance.avg()"""
        return AggregateExpr(Avg(), self.name)

    def min(self) -> AggregateExpr:
        """MIN(field): u.balance.min()"""
        return AggregateExpr(Min(), self.name)

    def max(self) -> AggregateExpr:
        """MAX(field): u.balance.max()"""
        return AggregateExpr(Max(), self.name)

    def count(self) -> AggregateExpr:
        """COUNT(field): u.id.count()"""
        return AggregateExpr(Count(), self.name)

    def array_agg(self) -> AggregateExpr:
        """ARRAY_AGG(field): u.tags.array_agg()"""
        return AggregateExpr(ArrayAgg(), self.name)

    def string_agg(self, separator: str = ",") -> AggregateExpr:
        """STRING_AGG(field, sep): u.name.string_agg(', ')"""
        return AggregateExpr(StringAgg(separator), self.name)


class JsonFieldProxy:
    """Proxy for JSON path that supports comparison operators.

    Created by FieldProxy.json():
        u.metadata.json('profile.name') == 'alice'
        # → Eq(JsonExtract(Field("metadata"), "profile.name"), Const("alice"))
    """

    __slots__ = ("_base", "_path")

    def __init__(self, base: Expr, path: str) -> None:
        self._base = base
        self._path = path

    def _to_expr(self) -> JsonExtract:
        return JsonExtract(self._base, self._path)

    # Comparison operators

    def __eq__(self, other: Any) -> Expr:  # type: ignore[override]
        return Eq(self._to_expr(), FieldProxy.wrap(other))

    def __ne__(self, other: Any) -> Expr:  # type: ignore[override]
        return Ne(self._to_expr(), FieldProxy.wrap(other))

    def __lt__(self, other: Any) -> Expr:
        return Lt(self._to_expr(), FieldProxy.wrap(other))

    def __le__(self, other: Any) -> Expr:
        return Le(self._to_expr(), FieldProxy.wrap(other))

    def __gt__(self, other: Any) -> Expr:
        return Gt(self._to_expr(), FieldProxy.wrap(other))

    def __ge__(self, other: Any) -> Expr:
        return Ge(self._to_expr(), FieldProxy.wrap(other))

    # Null checks

    def is_null(self) -> Expr:
        """JSON path value is null."""
        return IsNull(self._to_expr())

    def is_not_null(self) -> Expr:
        """JSON path value is not null."""
        return IsNotNull(self._to_expr())


@dataclass(frozen=True, slots=True)
class OrderSpec:
    """Ordering specification for a field."""

    field: str
    ascending: bool = True


class EntityProxy(Generic[T]):
    """Proxy for entity that creates FieldProxy on attribute access.

    Usage:
        proxy = EntityProxy(User)
        expr = (lambda u: u.balance > 100)(proxy)
    """

    __slots__ = ("_entity",)

    def __init__(self, entity: type[T]) -> None:
        self._entity = entity

    def __getattr__(self, name: str) -> FieldProxy:
        # Validate field exists on entity
        # For now, just create proxy
        return FieldProxy(name)

    def count(self) -> AggregateExpr:
        """COUNT(*) without field reference.

        Usage:
            .aggregate(user_count=lambda u: u.count())
        """
        return AggregateExpr(Count(), None)


def build_expr(entity: type[T], predicate: Callable[[EntityProxy[T]], Expr]) -> Expr:
    """Build Expr from a lambda predicate.

    Usage:
        expr = build_expr(User, lambda u: u.balance > 100)
        # → Gt(Field("balance"), Const(100))
    """
    proxy = EntityProxy(entity)
    return predicate(proxy)


def build_order(
    entity: type[T], order_fn: Callable[[EntityProxy[T]], FieldProxy | OrderSpec]
) -> OrderSpec:
    """Build OrderSpec from a lambda.

    Usage:
        order = build_order(User, lambda u: u.balance.desc())
        # → OrderSpec("balance", ascending=False)

        order = build_order(User, lambda u: u.name)
        # → OrderSpec("name", ascending=True)
    """
    proxy = EntityProxy(entity)
    result = order_fn(proxy)

    if isinstance(result, OrderSpec):
        return result
    # FieldProxy case — default to ascending
    return OrderSpec(result.name, ascending=True)


__all__ = (
    "FieldProxy",
    "JsonFieldProxy",
    "OrderSpec",
    "EntityProxy",
    "build_expr",
    "build_order",
)

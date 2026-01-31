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
    def _wrap(value: Any) -> Expr:
        """Wrap value as Expr if not already."""
        if isinstance(value, FieldProxy):
            return value._to_expr()
        if isinstance(value, Expr):
            return value
        return Const(value)

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
    "OrderSpec",
    "EntityProxy",
    "build_expr",
    "build_order",
)

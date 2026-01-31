"""Expression AST — predicates for filtering.

Expressions are built from lambdas via proxy objects:

    .filter(lambda u: u.balance > 100)
    # becomes: Gt(Field("balance"), Const(100))

Provider compiles Expr to backend-specific form:
    SQL: WHERE balance > 100
    Memory: filter(lambda u: u.balance > 100, users)
    HTTP: ?balance_gt=100
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Generic, TypeVar


T = TypeVar("T")


# ─── Base ─────────────────────────────────────────────────────────────────────


class Expr(ABC):
    """Base expression node."""

    @abstractmethod
    def evaluate(self, obj: Any) -> Any:
        """Evaluate expression against an object (for interpreted mode)."""
        ...


# ─── Leaf Nodes ───────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Field(Expr):
    """Field reference: u.balance → Field("balance")"""

    name: str

    def evaluate(self, obj: Any) -> Any:
        return getattr(obj, self.name)


@dataclass(frozen=True, slots=True)
class Const(Expr, Generic[T]):
    """Constant value: 100 → Const(100)"""

    value: T

    def evaluate(self, obj: Any) -> T:
        return self.value


# ─── Comparison Operators ─────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Eq(Expr):
    """Equality: u.name == "alice" → Eq(Field("name"), Const("alice"))"""

    left: Expr
    right: Expr

    def evaluate(self, obj: Any) -> bool:
        return self.left.evaluate(obj) == self.right.evaluate(obj)


@dataclass(frozen=True, slots=True)
class Ne(Expr):
    """Not equal: u.name != "alice"""

    left: Expr
    right: Expr

    def evaluate(self, obj: Any) -> bool:
        return self.left.evaluate(obj) != self.right.evaluate(obj)


@dataclass(frozen=True, slots=True)
class Lt(Expr):
    """Less than: u.balance < 100"""

    left: Expr
    right: Expr

    def evaluate(self, obj: Any) -> bool:
        return self.left.evaluate(obj) < self.right.evaluate(obj)


@dataclass(frozen=True, slots=True)
class Le(Expr):
    """Less than or equal: u.balance <= 100"""

    left: Expr
    right: Expr

    def evaluate(self, obj: Any) -> bool:
        return self.left.evaluate(obj) <= self.right.evaluate(obj)


@dataclass(frozen=True, slots=True)
class Gt(Expr):
    """Greater than: u.balance > 100"""

    left: Expr
    right: Expr

    def evaluate(self, obj: Any) -> bool:
        return self.left.evaluate(obj) > self.right.evaluate(obj)


@dataclass(frozen=True, slots=True)
class Ge(Expr):
    """Greater than or equal: u.balance >= 100"""

    left: Expr
    right: Expr

    def evaluate(self, obj: Any) -> bool:
        return self.left.evaluate(obj) >= self.right.evaluate(obj)


# ─── Logical Operators ────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class And(Expr):
    """Logical AND: (u.active == True) & (u.balance > 0)"""

    left: Expr
    right: Expr

    def evaluate(self, obj: Any) -> bool:
        return self.left.evaluate(obj) and self.right.evaluate(obj)


@dataclass(frozen=True, slots=True)
class Or(Expr):
    """Logical OR: (u.role == "admin") | (u.role == "moderator")"""

    left: Expr
    right: Expr

    def evaluate(self, obj: Any) -> bool:
        return self.left.evaluate(obj) or self.right.evaluate(obj)


@dataclass(frozen=True, slots=True)
class Not(Expr):
    """Logical NOT: ~(u.deleted)"""

    operand: Expr

    def evaluate(self, obj: Any) -> bool:
        return not self.operand.evaluate(obj)


# ─── Collection Operators ─────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class In(Expr):
    """Membership: u.status.in_(["active", "pending"])"""

    field: Expr
    values: tuple[Any, ...]

    def evaluate(self, obj: Any) -> bool:
        return self.field.evaluate(obj) in self.values


@dataclass(frozen=True, slots=True)
class Contains(Expr):
    """String contains: u.name.contains("alice")"""

    field: Expr
    substring: str

    def evaluate(self, obj: Any) -> bool:
        return self.substring in str(self.field.evaluate(obj))


@dataclass(frozen=True, slots=True)
class StartsWith(Expr):
    """String starts with: u.name.startswith("al")"""

    field: Expr
    prefix: str

    def evaluate(self, obj: Any) -> bool:
        return str(self.field.evaluate(obj)).startswith(self.prefix)


@dataclass(frozen=True, slots=True)
class EndsWith(Expr):
    """String ends with: u.name.endswith("ice")"""

    field: Expr
    suffix: str

    def evaluate(self, obj: Any) -> bool:
        return str(self.field.evaluate(obj)).endswith(self.suffix)


# ─── Null Checks ──────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class IsNull(Expr):
    """Null check: u.deleted_at.is_null()"""

    field: Expr

    def evaluate(self, obj: Any) -> bool:
        val = self.field.evaluate(obj)
        return val is None


@dataclass(frozen=True, slots=True)
class IsNotNull(Expr):
    """Not null check: u.email.is_not_null()"""

    field: Expr

    def evaluate(self, obj: Any) -> bool:
        val = self.field.evaluate(obj)
        return val is not None


__all__ = (
    # Base
    "Expr",
    # Leaf
    "Field",
    "Const",
    # Comparison
    "Eq",
    "Ne",
    "Lt",
    "Le",
    "Gt",
    "Ge",
    # Logical
    "And",
    "Or",
    "Not",
    # Collection
    "In",
    "Contains",
    "StartsWith",
    "EndsWith",
    # Null
    "IsNull",
    "IsNotNull",
)

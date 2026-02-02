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

    def __and__(self, other: "Expr") -> "Expr":
        """Logical AND: (u.active == True) & (u.balance > 0)"""
        return And(self, other)

    def __or__(self, other: "Expr") -> "Expr":
        """Logical OR: (u.role == "admin") | (u.role == "mod")"""
        return Or(self, other)

    def __invert__(self) -> "Expr":
        """Logical NOT: ~(u.deleted)"""
        return Not(self)


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


# ─── Range Operators ─────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Between(Expr):
    """Range check: field BETWEEN low AND high (inclusive).

    Usage:
        u.balance.between(100, 1000)
    """

    field: Expr
    low: Expr
    high: Expr

    def evaluate(self, obj: Any) -> bool:
        val = self.field.evaluate(obj)
        low_val = self.low.evaluate(obj)
        high_val = self.high.evaluate(obj)
        return low_val <= val <= high_val


# ─── Pattern Matching ────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Like(Expr):
    """SQL LIKE pattern: % = any chars, _ = single char.

    Usage:
        u.email.like('%@gmail.com')
    """

    field: Expr
    pattern: str

    def evaluate(self, obj: Any) -> bool:
        import fnmatch

        val = str(self.field.evaluate(obj))
        # Convert SQL LIKE to fnmatch: % -> *, _ -> ?
        glob = self.pattern.replace("%", "*").replace("_", "?")
        return fnmatch.fnmatch(val, glob)


@dataclass(frozen=True, slots=True)
class ILike(Expr):
    """Case-insensitive LIKE.

    Usage:
        u.email.ilike('%@GMAIL.COM')
    """

    field: Expr
    pattern: str

    def evaluate(self, obj: Any) -> bool:
        import fnmatch

        val = str(self.field.evaluate(obj)).lower()
        glob = self.pattern.lower().replace("%", "*").replace("_", "?")
        return fnmatch.fnmatch(val, glob)


@dataclass(frozen=True, slots=True)
class Regex(Expr):
    """Regex match.

    Usage:
        u.email.regex(r'^\\w+@\\w+\\.\\w+$')
    """

    field: Expr
    pattern: str

    def evaluate(self, obj: Any) -> bool:
        import re

        val = str(self.field.evaluate(obj))
        return bool(re.search(self.pattern, val))


# ─── Array Operators ─────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ArrayContains(Expr):
    """Array contains value: tags @> ['vip'].

    Usage:
        u.tags.array_contains('vip')
    """

    field: Expr
    value: Any

    def evaluate(self, obj: Any) -> bool:
        arr = self.field.evaluate(obj)
        if not isinstance(arr, (list, tuple, set, frozenset)):
            return False
        return self.value in arr


@dataclass(frozen=True, slots=True)
class ArrayAny(Expr):
    """Array contains any of values.

    Usage:
        u.tags.array_any('vip', 'admin')
    """

    field: Expr
    values: tuple[Any, ...]

    def evaluate(self, obj: Any) -> bool:
        arr = self.field.evaluate(obj)
        if not isinstance(arr, (list, tuple, set, frozenset)):
            return False
        return any(v in arr for v in self.values)


@dataclass(frozen=True, slots=True)
class ArrayAll(Expr):
    """Array contains all of values.

    Usage:
        u.tags.array_all('vip', 'verified')
    """

    field: Expr
    values: tuple[Any, ...]

    def evaluate(self, obj: Any) -> bool:
        arr = self.field.evaluate(obj)
        if not isinstance(arr, (list, tuple, set, frozenset)):
            return False
        return all(v in arr for v in self.values)


@dataclass(frozen=True, slots=True)
class ArrayOverlap(Expr):
    """Arrays have overlap (at least one common element).

    Usage:
        u.tags.array_overlap('a', 'b')
    """

    field: Expr
    values: tuple[Any, ...]

    def evaluate(self, obj: Any) -> bool:
        arr = self.field.evaluate(obj)
        if not isinstance(arr, (list, tuple, set, frozenset)):
            return False
        return bool(set(arr) & set(self.values))


# ─── JSON Operators ──────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class JsonExtract(Expr):
    """Extract value from JSON by path.

    Usage:
        u.metadata.json('profile.name') == 'alice'

    Path is dot-separated: "profile.name" or "users.0.name"
    """

    field: Expr
    path: str

    def evaluate(self, obj: Any) -> Any:
        val = self.field.evaluate(obj)
        for key in self.path.split("."):
            if isinstance(val, dict):
                val = val.get(key)
            elif isinstance(val, (list, tuple)) and key.isdigit():
                idx = int(key)
                val = val[idx] if 0 <= idx < len(val) else None
            else:
                return None
        return val


@dataclass(frozen=True, slots=True)
class JsonContains(Expr):
    """JSON contains value/structure.

    Usage:
        u.metadata.json_contains({'role': 'admin'})
    """

    field: Expr
    value: Any

    def evaluate(self, obj: Any) -> bool:
        val = self.field.evaluate(obj)
        if isinstance(val, dict) and isinstance(self.value, dict):
            return all(val.get(k) == v for k, v in self.value.items())
        return val == self.value


@dataclass(frozen=True, slots=True)
class JsonHasKey(Expr):
    """JSON has key.

    Usage:
        u.metadata.json_has_key('profile')
    """

    field: Expr
    key: str

    def evaluate(self, obj: Any) -> bool:
        val = self.field.evaluate(obj)
        if isinstance(val, dict):
            return self.key in val
        return False


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
    # Range
    "Between",
    # Pattern
    "Like",
    "ILike",
    "Regex",
    # Array
    "ArrayContains",
    "ArrayAny",
    "ArrayAll",
    "ArrayOverlap",
    # JSON
    "JsonExtract",
    "JsonContains",
    "JsonHasKey",
)

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

import dataclasses as _dc
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Generic, TypeVar


T = TypeVar("T")
R = TypeVar("R")


# Non-narrowing type checks — prevent pyright from narrowing Any to
# dict[Unknown, Unknown] / list[Unknown] etc. in JSON/array evaluate() methods.
def _is_dict(v: Any) -> bool:
    return isinstance(v, dict)


def _is_seq(v: Any) -> bool:
    return isinstance(v, (list, tuple))


def _is_collection(v: Any) -> bool:
    return isinstance(v, (list, tuple, set, frozenset))


# ─── Base ─────────────────────────────────────────────────────────────────────


class Expr(ABC):
    """Base expression node."""

    @abstractmethod
    def evaluate(self, obj: Any) -> Any:
        """Evaluate expression against an object (for interpreted mode)."""
        ...

    def children(self) -> tuple[Expr, ...]:
        """Return all Expr sub-expressions.

        Inspects dataclass fields automatically — no overrides needed.
        Leaf nodes (Field, Const) return ().
        Binary ops (Eq, And, ...) return (left, right).
        Between returns (field, low, high). Etc.
        """
        return tuple(
            getattr(self, f.name)
            for f in _dc.fields(self)
            if isinstance(getattr(self, f.name), Expr)
        )

    def __str__(self) -> str:
        from emergent.wire.axis.query._serialize import expr_repr
        return expr_repr(self)

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
        try:
            return getattr(obj, self.name)
        except AttributeError:
            raise AttributeError(
                f"Field {self.name!r} not found on {type(obj).__name__}"
            ) from None


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

    def __post_init__(self) -> None:
        import re

        re.compile(self.pattern)

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
        arr: Any = self.field.evaluate(obj)
        if not _is_collection(arr):
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
        val: Any = self.field.evaluate(obj)
        for key in self.path.split("."):
            if _is_dict(val):
                val = val.get(key)
            elif _is_seq(val) and key.isdigit():
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
        val: Any = self.field.evaluate(obj)
        if _is_dict(val) and _is_dict(self.value):
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


# ─── Expr Fold — tree catamorphism ────────────────────────────────────────────


type ExprHandler[R] = Callable[["Expr", Callable[["Expr"], R]], R]


def fold_expr(
    expr: Expr,
    handlers: Mapping[type, ExprHandler[R]],
    *,
    default: ExprHandler[R] | None = None,
) -> R:
    """Tree fold over Expr AST — symmetric with fold() from _core.py.

    Two-level dispatch per node:
      1. handler map (priority) — exact type lookup
      2. default (fallback) — catch-all for unknown nodes
      3. raise TypeError (closed-world) — if neither handles

    Each handler receives (node, recurse) where recurse applies the same
    dispatch to child nodes. This is the tree analog of fold()'s linear
    protocol dispatch.

    Args:
        expr: Root expression node
        handlers: Handlers keyed by Expr subclass type
        default: Optional fallback handler for unmatched types

    Returns:
        Result of folding the expression tree
    """
    def recurse(node: Expr) -> R:
        node_type = type(node)
        handler = handlers.get(node_type)
        if handler is not None:
            return handler(node, recurse)
        if default is not None:
            return default(node, recurse)
        raise TypeError(f"No handler for {node_type.__name__}")
    return recurse(expr)


@dataclass(frozen=True, slots=True)
class ExprDialect(Generic[R]):
    """Expr dialect descriptor — reified handler set for Expr tree fold.

    Symmetric with QueryDialect and CompilationPhase.
    Immutable value. Use .with_handler() / .without_handler() for customization.

    Usage:
        dialect = ExprDialect(handlers={Field: ..., Eq: ..., ...})
        result = dialect.fold(expr)

        # Extend with custom Expr type:
        my_dialect = dialect.with_handler(MyCustomExpr, my_handler)
    """

    handlers: Mapping[type, ExprHandler[R]]
    default: ExprHandler[R] | None = None

    def fold(self, expr: Expr) -> R:
        """Run fold_expr with this dialect's handlers."""
        return fold_expr(expr, self.handlers, default=self.default)

    def with_handler(
        self, expr_type: type, handler: ExprHandler[R]
    ) -> ExprDialect[R]:
        """Return new dialect with added/replaced handler. Immutable."""
        merged = {**self.handlers, expr_type: handler}
        return ExprDialect(handlers=merged, default=self.default)

    def without_handler(self, expr_type: type) -> ExprDialect[R]:
        """Return new dialect without handler for given type. Immutable."""
        filtered = {k: v for k, v in self.handlers.items() if k is not expr_type}
        return ExprDialect(handlers=filtered, default=self.default)


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
    # Fold
    "ExprHandler",
    "fold_expr",
    "ExprDialect",
)

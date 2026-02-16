"""Tests for expression AST — evaluate, children, operators."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from emergent.wire.axis.query._expr import (
    And,
    ArrayAll,
    ArrayAny,
    ArrayContains,
    ArrayOverlap,
    Between,
    Const,
    Contains,
    EndsWith,
    Eq,
    Expr,
    Field,
    Ge,
    Gt,
    ILike,
    In,
    IsNotNull,
    IsNull,
    JsonContains,
    JsonExtract,
    JsonHasKey,
    Le,
    Like,
    Lt,
    Ne,
    Not,
    Or,
    Regex,
    StartsWith,
)


@dataclass
class User:
    name: str
    balance: float
    active: bool = True
    role: str = "user"
    email: str = "alice@test.com"
    deleted_at: str | None = None
    tags: list[str] | None = None
    metadata: dict | None = None


ALICE = User(name="alice", balance=100.0, email="alice@gmail.com", tags=["vip", "verified"], metadata={"profile": {"name": "Alice"}, "role": "admin"})
BOB = User(name="bob", balance=50.0, active=False, role="admin", email="bob@yahoo.com", tags=["admin"], metadata={"profile": {"name": "Bob"}})
CHARLIE = User(name="charlie", balance=200.0, deleted_at="2024-01-01", tags=[], metadata={})


# ─── Leaf Nodes ──────────────────────────────────────────────────────────────


class TestField:
    def test_evaluate(self):
        assert Field("name").evaluate(ALICE) == "alice"
        assert Field("balance").evaluate(BOB) == 50.0

    def test_evaluate_missing_field(self):
        with pytest.raises(AttributeError, match="'nonexistent' not found on User"):
            Field("nonexistent").evaluate(ALICE)

    def test_children_empty(self):
        assert Field("name").children() == ()

    def test_frozen(self):
        with pytest.raises(AttributeError):
            Field("x").name = "y"  # type: ignore[misc]


class TestConst:
    def test_evaluate(self):
        assert Const(42).evaluate(ALICE) == 42
        assert Const("hello").evaluate(BOB) == "hello"
        assert Const(None).evaluate(CHARLIE) is None

    def test_children_empty(self):
        assert Const(100).children() == ()


# ─── Comparison Operators ────────────────────────────────────────────────────


class TestComparison:
    def test_eq(self):
        expr = Eq(Field("name"), Const("alice"))
        assert expr.evaluate(ALICE) is True
        assert expr.evaluate(BOB) is False

    def test_ne(self):
        expr = Ne(Field("name"), Const("alice"))
        assert expr.evaluate(ALICE) is False
        assert expr.evaluate(BOB) is True

    def test_lt(self):
        expr = Lt(Field("balance"), Const(75.0))
        assert expr.evaluate(BOB) is True
        assert expr.evaluate(ALICE) is False

    def test_le(self):
        expr = Le(Field("balance"), Const(100.0))
        assert expr.evaluate(ALICE) is True
        assert expr.evaluate(CHARLIE) is False

    def test_gt(self):
        expr = Gt(Field("balance"), Const(100.0))
        assert expr.evaluate(CHARLIE) is True
        assert expr.evaluate(ALICE) is False

    def test_ge(self):
        expr = Ge(Field("balance"), Const(100.0))
        assert expr.evaluate(ALICE) is True
        assert expr.evaluate(BOB) is False

    def test_children(self):
        expr = Eq(Field("name"), Const("alice"))
        children = expr.children()
        assert len(children) == 2
        assert isinstance(children[0], Field)
        assert isinstance(children[1], Const)


# ─── Logical Operators ───────────────────────────────────────────────────────


class TestLogical:
    def test_and(self):
        expr = And(Eq(Field("active"), Const(True)), Gt(Field("balance"), Const(50.0)))
        assert expr.evaluate(ALICE) is True
        assert expr.evaluate(BOB) is False  # not active

    def test_or(self):
        expr = Or(Eq(Field("role"), Const("admin")), Gt(Field("balance"), Const(150.0)))
        assert expr.evaluate(BOB) is True  # admin
        assert expr.evaluate(CHARLIE) is True  # balance > 150
        assert expr.evaluate(ALICE) is False

    def test_not(self):
        expr = Not(Eq(Field("active"), Const(True)))
        assert expr.evaluate(ALICE) is False
        assert expr.evaluate(BOB) is True

    def test_children(self):
        inner = Eq(Field("x"), Const(1))
        assert Not(inner).children() == (inner,)
        assert len(And(inner, inner).children()) == 2

    def test_operator_and(self):
        a = Eq(Field("x"), Const(1))
        b = Eq(Field("y"), Const(2))
        result = a & b
        assert isinstance(result, And)

    def test_operator_or(self):
        a = Eq(Field("x"), Const(1))
        b = Eq(Field("y"), Const(2))
        result = a | b
        assert isinstance(result, Or)

    def test_operator_invert(self):
        a = Eq(Field("x"), Const(1))
        result = ~a
        assert isinstance(result, Not)


# ─── Collection Operators ────────────────────────────────────────────────────


class TestCollection:
    def test_in(self):
        expr = In(Field("role"), ("admin", "moderator"))
        assert expr.evaluate(BOB) is True
        assert expr.evaluate(ALICE) is False

    def test_contains(self):
        expr = Contains(Field("name"), "lic")
        assert expr.evaluate(ALICE) is True
        assert expr.evaluate(BOB) is False

    def test_startswith(self):
        expr = StartsWith(Field("name"), "al")
        assert expr.evaluate(ALICE) is True
        assert expr.evaluate(BOB) is False

    def test_endswith(self):
        expr = EndsWith(Field("name"), "ob")
        assert expr.evaluate(BOB) is True
        assert expr.evaluate(ALICE) is False


# ─── Null Checks ─────────────────────────────────────────────────────────────


class TestNullChecks:
    def test_is_null(self):
        expr = IsNull(Field("deleted_at"))
        assert expr.evaluate(ALICE) is True
        assert expr.evaluate(CHARLIE) is False

    def test_is_not_null(self):
        expr = IsNotNull(Field("deleted_at"))
        assert expr.evaluate(CHARLIE) is True
        assert expr.evaluate(ALICE) is False


# ─── Range ───────────────────────────────────────────────────────────────────


class TestBetween:
    def test_between_inclusive(self):
        expr = Between(Field("balance"), Const(50.0), Const(150.0))
        assert expr.evaluate(ALICE) is True   # 100
        assert expr.evaluate(BOB) is True     # 50 (inclusive)
        assert expr.evaluate(CHARLIE) is False  # 200


# ─── Pattern Matching ────────────────────────────────────────────────────────


class TestPattern:
    def test_like(self):
        expr = Like(Field("email"), "%@gmail.com")
        assert expr.evaluate(ALICE) is True
        assert expr.evaluate(BOB) is False

    def test_ilike(self):
        expr = ILike(Field("email"), "%@GMAIL.COM")
        assert expr.evaluate(ALICE) is True
        assert expr.evaluate(BOB) is False

    def test_like_underscore(self):
        expr = Like(Field("name"), "bo_")
        assert expr.evaluate(BOB) is True
        assert expr.evaluate(ALICE) is False

    def test_regex(self):
        expr = Regex(Field("email"), r"^[a-z]+@[a-z]+\.[a-z]+$")
        assert expr.evaluate(ALICE) is True
        assert expr.evaluate(BOB) is True


# ─── Array Operators ─────────────────────────────────────────────────────────


class TestArray:
    def test_array_contains(self):
        expr = ArrayContains(Field("tags"), "vip")
        assert expr.evaluate(ALICE) is True
        assert expr.evaluate(BOB) is False

    def test_array_any(self):
        expr = ArrayAny(Field("tags"), ("vip", "premium"))
        assert expr.evaluate(ALICE) is True
        assert expr.evaluate(BOB) is False

    def test_array_all(self):
        expr = ArrayAll(Field("tags"), ("vip", "verified"))
        assert expr.evaluate(ALICE) is True
        assert expr.evaluate(BOB) is False

    def test_array_overlap(self):
        expr = ArrayOverlap(Field("tags"), ("admin", "vip"))
        assert expr.evaluate(ALICE) is True
        assert expr.evaluate(BOB) is True  # has "admin"
        assert expr.evaluate(CHARLIE) is False  # empty tags

    def test_non_array_returns_false(self):
        @dataclass
        class Item:
            tags: str = "not_a_list"

        expr = ArrayContains(Field("tags"), "vip")
        assert expr.evaluate(Item()) is False


# ─── JSON Operators ──────────────────────────────────────────────────────────


class TestJson:
    def test_json_extract(self):
        expr = JsonExtract(Field("metadata"), "profile.name")
        assert expr.evaluate(ALICE) == "Alice"
        assert expr.evaluate(BOB) == "Bob"

    def test_json_extract_missing(self):
        expr = JsonExtract(Field("metadata"), "nonexistent.path")
        assert expr.evaluate(ALICE) is None

    def test_json_extract_nested_index(self):
        @dataclass
        class Item:
            data: dict

        item = Item(data={"items": ["a", "b", "c"]})
        expr = JsonExtract(Field("data"), "items.1")
        assert expr.evaluate(item) == "b"

    def test_json_contains(self):
        expr = JsonContains(Field("metadata"), {"role": "admin"})
        assert expr.evaluate(ALICE) is True
        assert expr.evaluate(BOB) is False

    def test_json_has_key(self):
        expr = JsonHasKey(Field("metadata"), "profile")
        assert expr.evaluate(ALICE) is True
        assert expr.evaluate(CHARLIE) is False  # empty dict

    def test_json_has_key_non_dict(self):
        @dataclass
        class Item:
            metadata: str = "not_a_dict"

        assert JsonHasKey(Field("metadata"), "x").evaluate(Item()) is False

    def test_json_extract_intermediate_none(self):
        """Path traverses a key whose value is None — returns None."""
        @dataclass
        class Item:
            data: dict

        item = Item(data={"a": None})
        expr = JsonExtract(Field("data"), "a.b.c")
        assert expr.evaluate(item) is None

    def test_json_extract_non_digit_key_on_list(self):
        """Non-digit key on a list returns None."""
        @dataclass
        class Item:
            data: dict

        item = Item(data={"items": ["a", "b"]})
        expr = JsonExtract(Field("data"), "items.name")
        assert expr.evaluate(item) is None


# ─── Regex Edge Cases ───────────────────────────────────────────────────────


class TestRegexEdge:
    def test_invalid_pattern_raises(self):
        import re

        expr = Regex(Field("name"), "[invalid")
        with pytest.raises(re.error):
            expr.evaluate(ALICE)


# ─── Between Edge Cases ─────────────────────────────────────────────────────


class TestBetweenEdge:
    def test_between_strings(self):
        """Between works with string comparison."""
        expr = Between(Field("name"), Const("alice"), Const("charlie"))
        assert expr.evaluate(ALICE) is True   # "alice" <= "alice" <= "charlie"
        assert expr.evaluate(BOB) is True     # "alice" <= "bob" <= "charlie"
        assert expr.evaluate(CHARLIE) is True  # "alice" <= "charlie" <= "charlie"


# ─── Like/ILike Edge Cases ──────────────────────────────────────────────────


class TestLikeEdge:
    def test_like_percent_and_underscore(self):
        """% matches any chars, _ matches single char."""
        expr = Like(Field("email"), "%@%")
        assert expr.evaluate(ALICE) is True
        assert expr.evaluate(BOB) is True

    def test_ilike_underscore(self):
        """Case-insensitive _ wildcard."""
        expr = ILike(Field("name"), "BO_")
        assert expr.evaluate(BOB) is True
        assert expr.evaluate(ALICE) is False


# ─── Integration: Complex Expression Trees ──────────────────────────────────


class TestIntegrationComplexExpressionTree:
    def test_deeply_nested_boolean_logic(self):
        # (balance > 25 AND name != "bob") OR (active AND balance < 35)
        expr = Or(
            And(Gt(Field("balance"), Const(25)), Ne(Field("name"), Const("bob"))),
            And(Eq(Field("active"), Const(True)), Lt(Field("balance"), Const(35))),
        )
        # ALICE: balance=100 > 25 AND name="alice" != "bob" => True => True
        assert expr.evaluate(ALICE) is True
        # BOB: balance=50 > 25 AND name="bob" != "bob" => False; active=False AND ... => False
        assert expr.evaluate(BOB) is False
        # CHARLIE: balance=200 > 25 AND name="charlie" != "bob" => True => True
        assert expr.evaluate(CHARLIE) is True

    def test_combined_json_and_array_ops(self):
        # metadata has key "profile" AND tags contains "vip"
        expr = And(
            JsonHasKey(Field("metadata"), "profile"),
            ArrayContains(Field("tags"), "vip"),
        )
        assert expr.evaluate(ALICE) is True   # has profile + has vip tag
        assert expr.evaluate(BOB) is False     # has profile but no vip tag
        assert expr.evaluate(CHARLIE) is False  # no profile key (empty dict) + empty tags

    def test_json_extract_with_comparison(self):
        # metadata->>profile.name == "Alice" AND tags overlap ("vip", "admin")
        expr = And(
            Eq(JsonExtract(Field("metadata"), "profile.name"), Const("Alice")),
            ArrayOverlap(Field("tags"), ("vip", "admin")),
        )
        assert expr.evaluate(ALICE) is True
        assert expr.evaluate(BOB) is False  # profile.name is "Bob"

    def test_collect_all_leaf_fields_via_children(self):
        expr = Or(
            And(Gt(Field("balance"), Const(25)), Ne(Field("name"), Const("bob"))),
            And(Eq(Field("active"), Const(True)), Lt(Field("balance"), Const(35))),
        )
        # Collect all Field nodes via recursive children traversal
        def collect_fields(e: Expr) -> list[str]:
            if isinstance(e, Field):
                return [e.name]
            result: list[str] = []
            for child in e.children():
                result.extend(collect_fields(child))
            return result

        fields = collect_fields(expr)
        assert set(fields) == {"balance", "name", "active"}
        # balance appears twice
        assert fields.count("balance") == 2

    def test_triple_nested_not(self):
        # NOT(NOT(NOT(active == True)))
        expr = Not(Not(Not(Eq(Field("active"), Const(True)))))
        # Triple negation of True => False
        assert expr.evaluate(ALICE) is False  # active=True => True => Not => False
        assert expr.evaluate(BOB) is True     # active=False => False => Not => True

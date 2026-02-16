"""Tests for proxy objects — FieldProxy, EntityProxy, build_expr, build_order."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from emergent.wire.axis.query._expr import (
    Contains,
    EndsWith,
    Eq,
    Ge,
    Gt,
    In,
    IsNotNull,
    IsNull,
    Le,
    Lt,
    Ne,
    StartsWith,
    Between,
    Like,
    ILike,
    Regex,
    ArrayContains,
    JsonExtract,
    JsonContains,
    JsonHasKey,
    And,
    Or,
    Not,
)
from emergent.wire.axis.query._aggregate import AggregateExpr, Sum, Avg, Count, Min, Max
from emergent.wire.axis.query._proxy import (
    EntityProxy,
    FieldProxy,
    JsonFieldProxy,
    OrderSpec,
    build_expr,
    build_order,
)


@dataclass
class User:
    id: int
    name: str
    balance: float
    active: bool = True


# ─── FieldProxy ──────────────────────────────────────────────────────────────


class TestFieldProxy:
    def test_name(self):
        fp = FieldProxy("balance")
        assert fp.name == "balance"

    def test_eq(self):
        result = FieldProxy("name") == "alice"
        assert isinstance(result, Eq)

    def test_ne(self):
        result = FieldProxy("name") != "alice"
        assert isinstance(result, Ne)

    def test_lt(self):
        result = FieldProxy("balance") < 100
        assert isinstance(result, Lt)

    def test_le(self):
        result = FieldProxy("balance") <= 100
        assert isinstance(result, Le)

    def test_gt(self):
        result = FieldProxy("balance") > 100
        assert isinstance(result, Gt)

    def test_ge(self):
        result = FieldProxy("balance") >= 100
        assert isinstance(result, Ge)

    def test_and(self):
        a = FieldProxy("x") == 1
        b = FieldProxy("y") == 2
        result = a & b
        assert isinstance(result, And)

    def test_or(self):
        a = FieldProxy("x") == 1
        b = FieldProxy("y") == 2
        result = a | b
        assert isinstance(result, Or)

    def test_invert(self):
        result = ~(FieldProxy("active") == True)
        assert isinstance(result, Not)

    def test_in_(self):
        result = FieldProxy("role").in_(["admin", "mod"])
        assert isinstance(result, In)

    def test_contains(self):
        result = FieldProxy("name").contains("ali")
        assert isinstance(result, Contains)

    def test_startswith(self):
        result = FieldProxy("name").startswith("al")
        assert isinstance(result, StartsWith)

    def test_endswith(self):
        result = FieldProxy("name").endswith("ce")
        assert isinstance(result, EndsWith)

    def test_is_null(self):
        result = FieldProxy("deleted_at").is_null()
        assert isinstance(result, IsNull)

    def test_is_not_null(self):
        result = FieldProxy("deleted_at").is_not_null()
        assert isinstance(result, IsNotNull)

    def test_between(self):
        result = FieldProxy("balance").between(50, 200)
        assert isinstance(result, Between)

    def test_like(self):
        result = FieldProxy("email").like("%@gmail.com")
        assert isinstance(result, Like)

    def test_ilike(self):
        result = FieldProxy("email").ilike("%@GMAIL.COM")
        assert isinstance(result, ILike)

    def test_regex(self):
        result = FieldProxy("email").regex(r"^\w+@")
        assert isinstance(result, Regex)

    def test_array_contains(self):
        result = FieldProxy("tags").array_contains("vip")
        assert isinstance(result, ArrayContains)

    def test_json(self):
        result = FieldProxy("metadata").json("profile.name")
        assert isinstance(result, JsonFieldProxy)

    def test_json_contains(self):
        result = FieldProxy("metadata").json_contains({"role": "admin"})
        assert isinstance(result, JsonContains)

    def test_json_has_key(self):
        result = FieldProxy("metadata").json_has_key("profile")
        assert isinstance(result, JsonHasKey)

    def test_asc(self):
        result = FieldProxy("balance").asc()
        assert result == OrderSpec("balance", ascending=True)

    def test_desc(self):
        result = FieldProxy("balance").desc()
        assert result == OrderSpec("balance", ascending=False)

    # Aggregates

    def test_sum(self):
        result = FieldProxy("balance").sum()
        assert isinstance(result, AggregateExpr)
        assert isinstance(result.func, Sum)
        assert result.field == "balance"

    def test_avg(self):
        result = FieldProxy("balance").avg()
        assert isinstance(result.func, Avg)

    def test_count(self):
        result = FieldProxy("id").count()
        assert isinstance(result.func, Count)
        assert result.field == "id"

    def test_min(self):
        result = FieldProxy("balance").min()
        assert isinstance(result.func, Min)

    def test_max(self):
        result = FieldProxy("balance").max()
        assert isinstance(result.func, Max)


# ─── JsonFieldProxy ──────────────────────────────────────────────────────────


class TestJsonFieldProxy:
    def test_eq(self):
        result = FieldProxy("metadata").json("profile.name") == "alice"
        assert isinstance(result, Eq)
        assert isinstance(result.left, JsonExtract)

    def test_gt(self):
        result = FieldProxy("data").json("score") > 100
        assert isinstance(result, Gt)


# ─── EntityProxy ─────────────────────────────────────────────────────────────


class TestEntityProxy:
    def test_getattr_returns_field_proxy(self):
        proxy = EntityProxy(User)
        fp = proxy.balance
        assert isinstance(fp, FieldProxy)
        assert fp.name == "balance"

    def test_unknown_field_raises(self):
        proxy = EntityProxy(User)
        with pytest.raises(AttributeError, match="has no field"):
            proxy.nonexistent

    def test_count_star(self):
        proxy = EntityProxy(User)
        result = proxy.count()
        assert isinstance(result, AggregateExpr)
        assert isinstance(result.func, Count)
        assert result.field is None  # COUNT(*)


# ─── build_expr ──────────────────────────────────────────────────────────────


class TestEntityFields:
    def test_returns_none_for_plain_class(self):
        """Non-dataclass/non-typed-dict returns None (no validation)."""
        from emergent.wire.axis.query._proxy import _entity_fields

        class PlainUser:
            pass

        assert _entity_fields(PlainUser) is None

    def test_returns_fields_for_dataclass(self):
        from emergent.wire.axis.query._proxy import _entity_fields

        fields = _entity_fields(User)
        assert fields is not None
        assert "name" in fields
        assert "balance" in fields

    def test_plain_class_proxy_allows_any_field(self):
        """EntityProxy for plain class allows any field access (no validation)."""
        class PlainUser:
            pass

        proxy = EntityProxy(PlainUser)
        fp = proxy.anything
        assert isinstance(fp, FieldProxy)
        assert fp.name == "anything"


class TestBuildExpr:
    def test_simple(self):
        expr = build_expr(User, lambda u: u.balance > 100)
        assert isinstance(expr, Gt)

    def test_compound(self):
        expr = build_expr(User, lambda u: (u.active == True) & (u.balance > 0))
        assert isinstance(expr, And)

    def test_evaluate(self):
        expr = build_expr(User, lambda u: u.name == "alice")
        user = User(id=1, name="alice", balance=100.0)
        assert expr.evaluate(user) is True


# ─── build_order ─────────────────────────────────────────────────────────────


class TestBuildOrder:
    def test_field_proxy_default_asc(self):
        spec = build_order(User, lambda u: u.name)
        assert spec == OrderSpec("name", ascending=True)

    def test_explicit_desc(self):
        spec = build_order(User, lambda u: u.balance.desc())
        assert spec == OrderSpec("balance", ascending=False)

    def test_explicit_asc(self):
        spec = build_order(User, lambda u: u.balance.asc())
        assert spec == OrderSpec("balance", ascending=True)


# ─── Integration: Proxy to Evaluation ───────────────────────────────────────


class TestIntegrationProxyToEvaluation:
    def test_proxy_built_expr_evaluates_correctly(self):
        expr = build_expr(User, lambda u: (u.balance > 50) & (u.active == True))
        alice = User(id=1, name="alice", balance=100.0, active=True)
        bob = User(id=2, name="bob", balance=30.0, active=True)
        charlie = User(id=3, name="charlie", balance=200.0, active=False)

        assert expr.evaluate(alice) is True
        assert expr.evaluate(bob) is False   # balance <= 50
        assert expr.evaluate(charlie) is False  # not active

    def test_proxy_expr_matches_hand_built(self):
        proxy_expr = build_expr(User, lambda u: u.name == "alice")
        # Hand-built using FieldProxy (which wraps to Field/Const internally)
        hand_expr = FieldProxy("name") == "alice"

        alice = User(id=1, name="alice", balance=100.0)
        bob = User(id=2, name="bob", balance=50.0)

        assert proxy_expr.evaluate(alice) == hand_expr.evaluate(alice)
        assert proxy_expr.evaluate(bob) == hand_expr.evaluate(bob)

    def test_proxy_compound_logic(self):
        # (balance > 50) | (name == "bob")
        expr = build_expr(User, lambda u: (u.balance > 50) | (u.name == "bob"))
        assert expr.evaluate(User(id=1, name="alice", balance=100.0)) is True
        assert expr.evaluate(User(id=2, name="bob", balance=10.0)) is True
        assert expr.evaluate(User(id=3, name="charlie", balance=10.0)) is False

    def test_proxy_chained_comparisons(self):
        expr = build_expr(User, lambda u: (u.balance > 50) & (u.active == True))
        assert isinstance(expr, And)
        left = expr.left
        right = expr.right
        assert isinstance(left, Gt)
        assert isinstance(right, Eq)
        # Verify field references via children
        left_children = left.children()
        assert len(left_children) == 2
        assert left_children[0].evaluate(User(id=1, name="x", balance=99.0)) == 99.0

    def test_proxy_negation(self):
        expr = build_expr(User, lambda u: ~(u.active == True))
        assert isinstance(expr, Not)
        alice_active = User(id=1, name="alice", balance=100.0, active=True)
        alice_inactive = User(id=2, name="alice", balance=100.0, active=False)
        assert expr.evaluate(alice_active) is False
        assert expr.evaluate(alice_inactive) is True

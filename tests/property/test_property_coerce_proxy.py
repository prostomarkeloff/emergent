# pyright: reportPrivateUsage=false
"""Property tests for ExprCoercer and the FieldProxy / EntityProxy system.

Tests expression coercion (AST transforms on Const values) and proxy-based
expression building from attribute access and operators.
"""

from __future__ import annotations

from hypothesis import given, assume
import hypothesis.strategies as st
import pytest

from emergent.wire.axis.query._coerce import ExprCoercer
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
    In,
    Between,
    Contains,
    StartsWith,
    EndsWith,
    Like,
    ILike,
    IsNull,
    IsNotNull,
    ArrayContains,
    ArrayAny,
    ArrayAll,
    ArrayOverlap,
    JsonExtract,
)
from emergent.wire.axis.query._proxy import (
    FieldProxy,
    JsonFieldProxy,
    OrderSpec,
    EntityProxy,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Strategies
# ═══════════════════════════════════════════════════════════════════════════════

field_names = st.text(
    alphabet=st.characters(whitelist_categories=("Ll",), whitelist_characters="_"),
    min_size=1,
    max_size=20,
)

scalar_values = st.one_of(
    st.integers(min_value=-10_000, max_value=10_000),
    st.floats(allow_nan=False, allow_infinity=False),
    st.text(min_size=0, max_size=50),
    st.booleans(),
)

# Binary comparison node types paired with their constructor
BINARY_TYPES: list[type[Eq] | type[Ne] | type[Lt] | type[Le] | type[Gt] | type[Ge]] = [
    Eq, Ne, Lt, Le, Gt, Ge,
]


def make_binary(
    node_type: type[Eq] | type[Ne] | type[Lt] | type[Le] | type[Gt] | type[Ge],
    field_name: str,
    value: object,
) -> Expr:
    """Build a binary comparison expression: node_type(Field(name), Const(value))."""
    return node_type(left=Field(field_name), right=Const(value))


# ═══════════════════════════════════════════════════════════════════════════════
# Coercion tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestExprCoercerEq:
    """Coercion applies str() to Eq."""

    @given(value=st.integers())
    def test_coercion_applies_to_eq(self, value: int) -> None:
        coercer = ExprCoercer({"x": str})
        original = Eq(Field("x"), Const(value))
        result = coercer(original)
        assert result == Eq(Field("x"), Const(str(value)))


class TestExprCoercerAllBinaryTypes:
    """Coercion applies to all six binary comparison types."""

    @given(value=st.integers())
    @pytest.mark.parametrize("node_type", BINARY_TYPES, ids=lambda t: t.__name__)
    def test_coercion_applies_to_binary(
        self, node_type: type[Eq] | type[Ne] | type[Lt] | type[Le] | type[Gt] | type[Ge], value: int
    ) -> None:
        coercer = ExprCoercer({"x": str})
        original = make_binary(node_type, "x", value)
        result = coercer(original)
        expected = make_binary(node_type, "x", str(value))
        assert result == expected


class TestExprCoercerIn:
    """Coercion applies to each value inside In."""

    @given(values=st.lists(st.integers(), min_size=1, max_size=10))
    def test_coercion_applies_to_in_values(self, values: list[int]) -> None:
        coercer = ExprCoercer({"x": str})
        original = In(field=Field("x"), values=tuple(values))
        result = coercer(original)
        assert isinstance(result, In)
        assert result.values == tuple(str(v) for v in values)


class TestExprCoercerBetween:
    """Coercion applies to Between low and high."""

    @given(low=st.integers(), high=st.integers())
    def test_coercion_applies_to_between(self, low: int, high: int) -> None:
        coercer = ExprCoercer({"x": str})
        original = Between(field=Field("x"), low=Const(low), high=Const(high))
        result = coercer(original)
        assert isinstance(result, Between)
        assert result.low == Const(str(low))
        assert result.high == Const(str(high))


class TestExprCoercerNoMatch:
    """No coercion when field is not in the coercion map."""

    @given(value=st.integers(), field_name=field_names)
    def test_no_coercion_when_field_not_in_map(self, value: int, field_name: str) -> None:
        coercer = ExprCoercer({"other_field_zzz": str})
        assume(field_name != "other_field_zzz")
        original = Eq(Field(field_name), Const(value))
        result = coercer(original)
        assert result == original


class TestExprCoercerIdempotence:
    """Coercing twice with an idempotent function gives the same result."""

    @given(value=scalar_values)
    def test_coercion_idempotence(self, value: object) -> None:
        coercer = ExprCoercer({"x": str})
        original = Eq(Field("x"), Const(value))
        once = coercer(original)
        twice = coercer(once)
        assert once == twice


class TestExprCoercerPreservesType:
    """Coerced expression retains the same node type."""

    @given(value=st.integers())
    @pytest.mark.parametrize("node_type", BINARY_TYPES, ids=lambda t: t.__name__)
    def test_coercion_preserves_structure(
        self, node_type: type[Eq] | type[Ne] | type[Lt] | type[Le] | type[Gt] | type[Ge], value: int
    ) -> None:
        coercer = ExprCoercer({"x": str})
        original = make_binary(node_type, "x", value)
        result = coercer(original)
        assert type(result) is node_type


class TestExprCoercerDeepTraversal:
    """Coercion reaches leaves inside And/Or."""

    @given(v1=st.integers(), v2=st.integers())
    def test_deep_coercion_and(self, v1: int, v2: int) -> None:
        coercer = ExprCoercer({"x": str})
        inner_left = Eq(Field("x"), Const(v1))
        inner_right = Gt(Field("x"), Const(v2))
        original = And(left=inner_left, right=inner_right)
        result = coercer(original)
        assert isinstance(result, And)
        assert result.left == Eq(Field("x"), Const(str(v1)))
        assert result.right == Gt(Field("x"), Const(str(v2)))

    @given(v1=st.integers(), v2=st.integers())
    def test_deep_coercion_or(self, v1: int, v2: int) -> None:
        coercer = ExprCoercer({"x": str})
        inner_left = Lt(Field("x"), Const(v1))
        inner_right = Ne(Field("x"), Const(v2))
        original = Or(left=inner_left, right=inner_right)
        result = coercer(original)
        assert isinstance(result, Or)
        assert result.left == Lt(Field("x"), Const(str(v1)))
        assert result.right == Ne(Field("x"), Const(str(v2)))

    @given(v1=st.integers(), v2=st.integers(), v3=st.integers())
    def test_deep_coercion_nested_and_or(self, v1: int, v2: int, v3: int) -> None:
        coercer = ExprCoercer({"x": str})
        leaf1 = Eq(Field("x"), Const(v1))
        leaf2 = Gt(Field("x"), Const(v2))
        leaf3 = Le(Field("x"), Const(v3))
        original = And(left=Or(left=leaf1, right=leaf2), right=leaf3)
        result = coercer(original)
        assert isinstance(result, And)
        assert isinstance(result.left, Or)
        assert result.left.left == Eq(Field("x"), Const(str(v1)))
        assert result.left.right == Gt(Field("x"), Const(str(v2)))
        assert result.right == Le(Field("x"), Const(str(v3)))


def _str_upper(v: object) -> object:
    """Wrapper for str.upper that matches Callable[[object], object]."""
    assert isinstance(v, str)
    return v.upper()


class TestExprCoercerStringOps:
    """Coercion applies to string-based expression types."""

    def test_coercion_contains(self) -> None:
        coercer = ExprCoercer({"name": _str_upper})
        original = Contains(field=Field("name"), substring="alice")
        result = coercer(original)
        assert isinstance(result, Contains)
        assert result.substring == "ALICE"

    def test_coercion_startswith(self) -> None:
        coercer = ExprCoercer({"name": _str_upper})
        original = StartsWith(field=Field("name"), prefix="al")
        result = coercer(original)
        assert isinstance(result, StartsWith)
        assert result.prefix == "AL"

    def test_coercion_endswith(self) -> None:
        coercer = ExprCoercer({"name": _str_upper})
        original = EndsWith(field=Field("name"), suffix="ice")
        result = coercer(original)
        assert isinstance(result, EndsWith)
        assert result.suffix == "ICE"

    def test_coercion_like(self) -> None:
        coercer = ExprCoercer({"email": _str_upper})
        original = Like(field=Field("email"), pattern="%@gmail.com")
        result = coercer(original)
        assert isinstance(result, Like)
        assert result.pattern == "%@GMAIL.COM"

    def test_coercion_ilike(self) -> None:
        coercer = ExprCoercer({"email": _str_upper})
        original = ILike(field=Field("email"), pattern="%@gmail.com")
        result = coercer(original)
        assert isinstance(result, ILike)
        assert result.pattern == "%@GMAIL.COM"


class TestExprCoercerEmpty:
    """Empty coercion map is a no-op."""

    @given(value=st.integers())
    def test_empty_coercion_is_noop(self, value: int) -> None:
        coercer = ExprCoercer({})
        original = Eq(Field("x"), Const(value))
        result = coercer(original)
        # With empty map, the expr is returned as-is (identity short-circuit)
        assert result is original


# ═══════════════════════════════════════════════════════════════════════════════
# Proxy tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestFieldProxyComparisons:
    """proxy.x <op> value produces the right Expr node."""

    @given(value=scalar_values)
    def test_eq(self, value: object) -> None:
        proxy = FieldProxy("x")
        result = proxy == value
        assert result == Eq(Field("x"), Const(value))

    @given(value=scalar_values)
    def test_ne(self, value: object) -> None:
        proxy = FieldProxy("x")
        result = proxy != value
        assert result == Ne(Field("x"), Const(value))

    @given(value=st.integers())
    def test_lt(self, value: int) -> None:
        proxy = FieldProxy("x")
        result = proxy < value
        assert result == Lt(Field("x"), Const(value))

    @given(value=st.integers())
    def test_le(self, value: int) -> None:
        proxy = FieldProxy("x")
        result = proxy <= value
        assert result == Le(Field("x"), Const(value))

    @given(value=st.integers())
    def test_gt(self, value: int) -> None:
        proxy = FieldProxy("x")
        result = proxy > value
        assert result == Gt(Field("x"), Const(value))

    @given(value=st.integers())
    def test_ge(self, value: int) -> None:
        proxy = FieldProxy("x")
        result = proxy >= value
        assert result == Ge(Field("x"), Const(value))


class TestFieldProxyIn:
    """proxy.x.in_([...]) produces In(Field("x"), (...))."""

    @given(values=st.lists(st.integers(), min_size=1, max_size=10))
    def test_in_method(self, values: list[int]) -> None:
        proxy = FieldProxy("x")
        result = proxy.in_(values)
        assert result == In(Field("x"), tuple(values))


class TestFieldProxyStringMethods:
    """String methods produce correct Expr nodes."""

    @given(sub=st.text(min_size=1, max_size=20))
    def test_contains(self, sub: str) -> None:
        proxy = FieldProxy("name")
        result = proxy.contains(sub)
        assert result == Contains(Field("name"), sub)

    @given(prefix=st.text(min_size=1, max_size=20))
    def test_startswith(self, prefix: str) -> None:
        proxy = FieldProxy("name")
        result = proxy.startswith(prefix)
        assert result == StartsWith(Field("name"), prefix)

    @given(suffix=st.text(min_size=1, max_size=20))
    def test_endswith(self, suffix: str) -> None:
        proxy = FieldProxy("name")
        result = proxy.endswith(suffix)
        assert result == EndsWith(Field("name"), suffix)


class TestFieldProxyNullChecks:
    """Null/not-null produce IsNull / IsNotNull."""

    def test_is_null(self) -> None:
        proxy = FieldProxy("x")
        result = proxy.is_null()
        assert result == IsNull(Field("x"))

    def test_is_not_null(self) -> None:
        proxy = FieldProxy("x")
        result = proxy.is_not_null()
        assert result == IsNotNull(Field("x"))


class TestFieldProxyBetween:
    """proxy.x.between(lo, hi) produces Between with Const wrappers."""

    @given(lo=st.integers(), hi=st.integers())
    def test_between(self, lo: int, hi: int) -> None:
        proxy = FieldProxy("x")
        result = proxy.between(lo, hi)
        assert result == Between(Field("x"), Const(lo), Const(hi))


class TestFieldProxyLikeIlike:
    """like / ilike produce Like / ILike nodes."""

    @given(pattern=st.text(min_size=1, max_size=30))
    def test_like(self, pattern: str) -> None:
        proxy = FieldProxy("name")
        result = proxy.like(pattern)
        assert result == Like(Field("name"), pattern)

    @given(pattern=st.text(min_size=1, max_size=30))
    def test_ilike(self, pattern: str) -> None:
        proxy = FieldProxy("name")
        result = proxy.ilike(pattern)
        assert result == ILike(Field("name"), pattern)


class TestFieldProxyOrderSpec:
    """desc() / asc() produce OrderSpec."""

    @given(name=field_names)
    def test_desc(self, name: str) -> None:
        proxy = FieldProxy(name)
        result = proxy.desc()
        assert result == OrderSpec(name, ascending=False)

    @given(name=field_names)
    def test_asc(self, name: str) -> None:
        proxy = FieldProxy(name)
        result = proxy.asc()
        assert result == OrderSpec(name, ascending=True)


class TestFieldProxyArrayOps:
    """Array operator methods produce correct Expr nodes."""

    @given(value=scalar_values)
    def test_array_contains(self, value: object) -> None:
        proxy = FieldProxy("tags")
        result = proxy.array_contains(value)
        assert result == ArrayContains(Field("tags"), value)

    def test_array_any(self) -> None:
        proxy = FieldProxy("tags")
        result = proxy.array_any("vip", "admin")
        assert result == ArrayAny(Field("tags"), ("vip", "admin"))

    def test_array_all(self) -> None:
        proxy = FieldProxy("tags")
        result = proxy.array_all("vip", "verified")
        assert result == ArrayAll(Field("tags"), ("vip", "verified"))

    def test_array_overlap(self) -> None:
        proxy = FieldProxy("tags")
        result = proxy.array_overlap("a", "b")
        assert result == ArrayOverlap(Field("tags"), ("a", "b"))


class TestEntityProxyAttributeAccess:
    """EntityProxy.__getattr__ consistently returns FieldProxy."""

    @given(name=field_names)
    def test_attribute_access_produces_field_proxy(self, name: str) -> None:
        # Plain class has no inspectable fields, so _fields is None and
        # any attribute access is allowed — returns FieldProxy.
        class Opaque:
            pass

        proxy = EntityProxy(Opaque)
        fp = proxy.__getattr__(name)
        assert isinstance(fp, FieldProxy)
        assert fp.name == name


class TestFieldProxyJson:
    """proxy.field.json(path) returns JsonFieldProxy that supports comparisons."""

    def test_json_proxy_eq(self) -> None:
        proxy = FieldProxy("metadata")
        jp = proxy.json("profile.name")
        assert isinstance(jp, JsonFieldProxy)
        result = jp == "alice"
        assert result == Eq(JsonExtract(Field("metadata"), "profile.name"), Const("alice"))

    @given(value=st.integers())
    def test_json_proxy_gt(self, value: int) -> None:
        proxy = FieldProxy("data")
        result = proxy.json("score") > value
        assert result == Gt(JsonExtract(Field("data"), "score"), Const(value))


class TestFieldProxyToExpr:
    """FieldProxy.to_expr() returns Field with the correct name."""

    @given(name=field_names)
    def test_to_expr(self, name: str) -> None:
        proxy = FieldProxy(name)
        expr = proxy.to_expr()
        assert expr == Field(name)

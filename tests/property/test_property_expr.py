# pyright: reportPrivateUsage=false
"""Property-based tests for Expression AST.

Covers ALL 25+ expression types' evaluate() methods, boolean algebra laws,
operator overloads, and children() introspection using hypothesis.
"""

from __future__ import annotations

import fnmatch
import types

import hypothesis.strategies as st
import pytest
from hypothesis import given, settings

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
    StartsWith,
)

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

FIELD_NAMES = ("x", "y", "z")

# Integer range kept small to make comparisons more interesting
# (not always True or always False).
_small_ints = st.integers(min_value=-3, max_value=3)

# Strings for name field — short, printable, no wildcards to avoid fnmatch issues.
_names = st.text(
    alphabet=st.sampled_from("abcdefghijklmnopqrstuvwxyz"),
    min_size=0,
    max_size=8,
)

# Tags for array ops — small set of known tag values.
_tag_values = ("vip", "admin", "user", "mod", "verified", "new", "test")
_tag_lists = st.lists(
    st.sampled_from(_tag_values), min_size=0, max_size=5
)

# Metadata keys/values for JSON ops.
_meta_keys = st.sampled_from(("key", "role", "level", "profile", "score"))
_meta_values = st.one_of(
    st.text(
        alphabet=st.sampled_from("abcdefghijklmnopqrstuvwxyz"),
        min_size=1,
        max_size=5,
    ),
    _small_ints,
)
_metadata_dicts = st.dictionaries(_meta_keys, _meta_values, min_size=0, max_size=4)


def _bool_leaf() -> st.SearchStrategy[Expr]:
    """Leaf boolean expressions: comparisons of fields against constants."""
    field = st.sampled_from(FIELD_NAMES).map(Field)
    const = _small_ints.map(Const)

    eq = st.tuples(field, const).map(lambda t: Eq(t[0], t[1]))
    gt = st.tuples(field, const).map(lambda t: Gt(t[0], t[1]))
    lt = st.tuples(field, const).map(lambda t: Lt(t[0], t[1]))

    # Also allow Const(True) / Const(False) as trivial boolean leaves.
    bool_const: st.SearchStrategy[Expr] = st.sampled_from(
        [Const(True), Const(False)]
    )

    return st.one_of(eq, gt, lt, bool_const)


def bool_expr(max_leaves: int = 15) -> st.SearchStrategy[Expr]:
    """Recursively-built boolean expression trees with bounded size."""
    return st.recursive(
        _bool_leaf(),
        lambda children: st.one_of(
            st.tuples(children, children).map(lambda t: And(t[0], t[1])),
            st.tuples(children, children).map(lambda t: Or(t[0], t[1])),
            children.map(Not),
        ),
        max_leaves=max_leaves,
    )


def data_object() -> st.SearchStrategy[types.SimpleNamespace]:
    """SimpleNamespace with integer fields x, y, z."""
    return st.builds(
        types.SimpleNamespace,
        x=_small_ints,
        y=_small_ints,
        z=_small_ints,
    )


def rich_data_object() -> st.SearchStrategy[types.SimpleNamespace]:
    """SimpleNamespace with all field types needed for comprehensive testing."""
    return st.builds(
        types.SimpleNamespace,
        x=_small_ints,
        y=_small_ints,
        z=_small_ints,
        name=_names,
        active=st.booleans(),
        val=st.one_of(st.none(), _small_ints),
        tags=_tag_lists,
        metadata=_metadata_dicts,
    )


# Shared settings -- keep example counts reasonable for CI.
_settings = settings(max_examples=200, deadline=None)

# Fewer examples for complex/slow tests.
_settings_light = settings(max_examples=100, deadline=None)


# ===========================================================================
# SECTION 1: Boolean Algebra Laws (existing tests, preserved)
# ===========================================================================


# ---------------------------------------------------------------------------
# 1. And commutativity
# ---------------------------------------------------------------------------


@_settings
@given(a=bool_expr(), b=bool_expr(), obj=data_object())
def test_and_commutativity(a: Expr, b: Expr, obj: types.SimpleNamespace) -> None:
    assert And(a, b).evaluate(obj) == And(b, a).evaluate(obj)


# ---------------------------------------------------------------------------
# 2. Or commutativity
# ---------------------------------------------------------------------------


@_settings
@given(a=bool_expr(), b=bool_expr(), obj=data_object())
def test_or_commutativity(a: Expr, b: Expr, obj: types.SimpleNamespace) -> None:
    assert Or(a, b).evaluate(obj) == Or(b, a).evaluate(obj)


# ---------------------------------------------------------------------------
# 3. And associativity
# ---------------------------------------------------------------------------


@_settings
@given(a=bool_expr(), b=bool_expr(), c=bool_expr(), obj=data_object())
def test_and_associativity(
    a: Expr, b: Expr, c: Expr, obj: types.SimpleNamespace
) -> None:
    assert And(And(a, b), c).evaluate(obj) == And(a, And(b, c)).evaluate(obj)


# ---------------------------------------------------------------------------
# 4. Or associativity
# ---------------------------------------------------------------------------


@_settings
@given(a=bool_expr(), b=bool_expr(), c=bool_expr(), obj=data_object())
def test_or_associativity(
    a: Expr, b: Expr, c: Expr, obj: types.SimpleNamespace
) -> None:
    assert Or(Or(a, b), c).evaluate(obj) == Or(a, Or(b, c)).evaluate(obj)


# ---------------------------------------------------------------------------
# 5. De Morgan 1: ~(a & b) == (~a) | (~b)
# ---------------------------------------------------------------------------


@_settings
@given(a=bool_expr(), b=bool_expr(), obj=data_object())
def test_de_morgan_1(a: Expr, b: Expr, obj: types.SimpleNamespace) -> None:
    assert Not(And(a, b)).evaluate(obj) == Or(Not(a), Not(b)).evaluate(obj)


# ---------------------------------------------------------------------------
# 6. De Morgan 2: ~(a | b) == (~a) & (~b)
# ---------------------------------------------------------------------------


@_settings
@given(a=bool_expr(), b=bool_expr(), obj=data_object())
def test_de_morgan_2(a: Expr, b: Expr, obj: types.SimpleNamespace) -> None:
    assert Not(Or(a, b)).evaluate(obj) == And(Not(a), Not(b)).evaluate(obj)


# ---------------------------------------------------------------------------
# 7. Double negation: ~~a == a
# ---------------------------------------------------------------------------


@_settings
@given(a=bool_expr(), obj=data_object())
def test_double_negation(a: Expr, obj: types.SimpleNamespace) -> None:
    assert Not(Not(a)).evaluate(obj) == a.evaluate(obj)


# ---------------------------------------------------------------------------
# 8. And identity: a & True == a
# ---------------------------------------------------------------------------


@_settings
@given(a=bool_expr(), obj=data_object())
def test_and_identity(a: Expr, obj: types.SimpleNamespace) -> None:
    assert And(a, Const(True)).evaluate(obj) == a.evaluate(obj)


# ---------------------------------------------------------------------------
# 9. Or identity: a | False == a
# ---------------------------------------------------------------------------


@_settings
@given(a=bool_expr(), obj=data_object())
def test_or_identity(a: Expr, obj: types.SimpleNamespace) -> None:
    assert Or(a, Const(False)).evaluate(obj) == a.evaluate(obj)


# ---------------------------------------------------------------------------
# 10. And zero: a & False == False
# ---------------------------------------------------------------------------


@_settings
@given(a=bool_expr(), obj=data_object())
def test_and_zero(a: Expr, obj: types.SimpleNamespace) -> None:
    assert And(a, Const(False)).evaluate(obj) is False


# ---------------------------------------------------------------------------
# 11. Or zero: a | True == True
# ---------------------------------------------------------------------------


@_settings
@given(a=bool_expr(), obj=data_object())
def test_or_zero(a: Expr, obj: types.SimpleNamespace) -> None:
    assert Or(a, Const(True)).evaluate(obj) is True


# ---------------------------------------------------------------------------
# 12. And idempotence: a & a == a
# ---------------------------------------------------------------------------


@_settings
@given(a=bool_expr(), obj=data_object())
def test_and_idempotence(a: Expr, obj: types.SimpleNamespace) -> None:
    assert And(a, a).evaluate(obj) == a.evaluate(obj)


# ---------------------------------------------------------------------------
# 13. Or idempotence: a | a == a
# ---------------------------------------------------------------------------


@_settings
@given(a=bool_expr(), obj=data_object())
def test_or_idempotence(a: Expr, obj: types.SimpleNamespace) -> None:
    assert Or(a, a).evaluate(obj) == a.evaluate(obj)


# ===========================================================================
# SECTION 2: Leaf Node Evaluation
# ===========================================================================


@_settings
@given(obj=rich_data_object())
def test_field_evaluate_x(obj: types.SimpleNamespace) -> None:
    assert Field("x").evaluate(obj) == obj.x


@_settings
@given(obj=rich_data_object())
def test_field_evaluate_name(obj: types.SimpleNamespace) -> None:
    assert Field("name").evaluate(obj) == obj.name


@_settings
@given(v=_small_ints, obj=rich_data_object())
def test_const_evaluate(v: int, obj: types.SimpleNamespace) -> None:
    assert Const(v).evaluate(obj) == v


def test_field_missing_attribute() -> None:
    obj = types.SimpleNamespace(x=1)
    with pytest.raises(AttributeError, match="Field 'nonexistent' not found"):
        Field("nonexistent").evaluate(obj)


# ===========================================================================
# SECTION 3: Comparison Operators Evaluation
# ===========================================================================


@_settings
@given(obj=rich_data_object(), v=_small_ints)
def test_eq_evaluation(obj: types.SimpleNamespace, v: int) -> None:
    result = Eq(Field("x"), Const(v)).evaluate(obj)
    assert result == (obj.x == v)


@_settings
@given(obj=rich_data_object(), v=_small_ints)
def test_ne_evaluation(obj: types.SimpleNamespace, v: int) -> None:
    result = Ne(Field("x"), Const(v)).evaluate(obj)
    assert result == (obj.x != v)


@_settings
@given(obj=rich_data_object(), v=_small_ints)
def test_lt_evaluation(obj: types.SimpleNamespace, v: int) -> None:
    result = Lt(Field("x"), Const(v)).evaluate(obj)
    assert result == (obj.x < v)


@_settings
@given(obj=rich_data_object(), v=_small_ints)
def test_le_evaluation(obj: types.SimpleNamespace, v: int) -> None:
    result = Le(Field("x"), Const(v)).evaluate(obj)
    assert result == (obj.x <= v)


@_settings
@given(obj=rich_data_object(), v=_small_ints)
def test_gt_evaluation(obj: types.SimpleNamespace, v: int) -> None:
    result = Gt(Field("x"), Const(v)).evaluate(obj)
    assert result == (obj.x > v)


@_settings
@given(obj=rich_data_object(), v=_small_ints)
def test_ge_evaluation(obj: types.SimpleNamespace, v: int) -> None:
    result = Ge(Field("x"), Const(v)).evaluate(obj)
    assert result == (obj.x >= v)


# Comparison between two fields
@_settings
@given(obj=rich_data_object())
def test_eq_field_to_field(obj: types.SimpleNamespace) -> None:
    result = Eq(Field("x"), Field("y")).evaluate(obj)
    assert result == (obj.x == obj.y)


@_settings
@given(obj=rich_data_object())
def test_lt_field_to_field(obj: types.SimpleNamespace) -> None:
    result = Lt(Field("x"), Field("y")).evaluate(obj)
    assert result == (obj.x < obj.y)


# Ne is the negation of Eq
@_settings
@given(obj=rich_data_object(), v=_small_ints)
def test_ne_is_not_eq(obj: types.SimpleNamespace, v: int) -> None:
    eq_result = Eq(Field("x"), Const(v)).evaluate(obj)
    ne_result = Ne(Field("x"), Const(v)).evaluate(obj)
    assert ne_result == (not eq_result)


# Lt and Ge are complements
@_settings
@given(obj=rich_data_object(), v=_small_ints)
def test_lt_ge_complement(obj: types.SimpleNamespace, v: int) -> None:
    lt_result = Lt(Field("x"), Const(v)).evaluate(obj)
    ge_result = Ge(Field("x"), Const(v)).evaluate(obj)
    assert lt_result == (not ge_result)


# Gt and Le are complements
@_settings
@given(obj=rich_data_object(), v=_small_ints)
def test_gt_le_complement(obj: types.SimpleNamespace, v: int) -> None:
    gt_result = Gt(Field("x"), Const(v)).evaluate(obj)
    le_result = Le(Field("x"), Const(v)).evaluate(obj)
    assert gt_result == (not le_result)


# ===========================================================================
# SECTION 4: Collection Operators
# ===========================================================================


@_settings
@given(
    obj=rich_data_object(),
    values=st.frozensets(_small_ints, min_size=1, max_size=5).map(tuple),
)
def test_in_evaluation(obj: types.SimpleNamespace, values: tuple[int, ...]) -> None:
    result = In(Field("x"), values).evaluate(obj)
    assert result == (obj.x in values)


@_settings
@given(obj=rich_data_object())
def test_in_empty_values(obj: types.SimpleNamespace) -> None:
    result = In(Field("x"), ()).evaluate(obj)
    assert result is False


@_settings
@given(
    obj=rich_data_object(),
    sub=st.text(
        alphabet=st.sampled_from("abcdefghijklmnopqrstuvwxyz"),
        min_size=0,
        max_size=3,
    ),
)
def test_contains_evaluation(obj: types.SimpleNamespace, sub: str) -> None:
    result = Contains(Field("name"), sub).evaluate(obj)
    assert result == (sub in str(obj.name))


@_settings
@given(
    obj=rich_data_object(),
    prefix=st.text(
        alphabet=st.sampled_from("abcdefghijklmnopqrstuvwxyz"),
        min_size=0,
        max_size=3,
    ),
)
def test_startswith_evaluation(obj: types.SimpleNamespace, prefix: str) -> None:
    result = StartsWith(Field("name"), prefix).evaluate(obj)
    assert result == str(obj.name).startswith(prefix)


@_settings
@given(
    obj=rich_data_object(),
    suffix=st.text(
        alphabet=st.sampled_from("abcdefghijklmnopqrstuvwxyz"),
        min_size=0,
        max_size=3,
    ),
)
def test_endswith_evaluation(obj: types.SimpleNamespace, suffix: str) -> None:
    result = EndsWith(Field("name"), suffix).evaluate(obj)
    assert result == str(obj.name).endswith(suffix)


# ===========================================================================
# SECTION 5: Null Checks
# ===========================================================================


@_settings
@given(obj=rich_data_object())
def test_isnull_evaluation(obj: types.SimpleNamespace) -> None:
    result = IsNull(Field("val")).evaluate(obj)
    assert result == (obj.val is None)


@_settings
@given(obj=rich_data_object())
def test_isnotnull_evaluation(obj: types.SimpleNamespace) -> None:
    result = IsNotNull(Field("val")).evaluate(obj)
    assert result == (obj.val is not None)


# IsNull and IsNotNull are complements
@_settings
@given(obj=rich_data_object())
def test_isnull_isnotnull_complement(obj: types.SimpleNamespace) -> None:
    is_null = IsNull(Field("val")).evaluate(obj)
    is_not_null = IsNotNull(Field("val")).evaluate(obj)
    assert is_null == (not is_not_null)


# ===========================================================================
# SECTION 6: Range (Between)
# ===========================================================================


@_settings
@given(obj=rich_data_object(), lo=_small_ints, hi=_small_ints)
def test_between_evaluation(
    obj: types.SimpleNamespace, lo: int, hi: int
) -> None:
    result = Between(Field("x"), Const(lo), Const(hi)).evaluate(obj)
    assert result == (lo <= obj.x <= hi)


@_settings
@given(obj=rich_data_object(), lo=_small_ints, hi=_small_ints)
def test_between_equivalent_to_and_of_le_ge(
    obj: types.SimpleNamespace, lo: int, hi: int
) -> None:
    """Between(f, lo, hi) == And(Ge(f, lo), Le(f, hi))."""
    between_result = Between(Field("x"), Const(lo), Const(hi)).evaluate(obj)
    and_result = And(
        Ge(Field("x"), Const(lo)), Le(Field("x"), Const(hi))
    ).evaluate(obj)
    assert between_result == and_result


# Between with field expressions for bounds
@_settings
@given(obj=rich_data_object())
def test_between_with_field_bounds(obj: types.SimpleNamespace) -> None:
    result = Between(Field("x"), Field("y"), Field("z")).evaluate(obj)
    assert result == (obj.y <= obj.x <= obj.z)


# ===========================================================================
# SECTION 7: Pattern Matching (Like / ILike)
# ===========================================================================


@_settings_light
@given(obj=rich_data_object())
def test_like_percent_wildcard(obj: types.SimpleNamespace) -> None:
    """Like with % should match any characters."""
    pattern = "%"
    result = Like(Field("name"), pattern).evaluate(obj)
    # % -> * in fnmatch, matches everything
    assert result is True


@_settings_light
@given(obj=rich_data_object())
def test_like_prefix_match(obj: types.SimpleNamespace) -> None:
    """Like('ab%') should match names starting with 'ab'."""
    result = Like(Field("name"), "ab%").evaluate(obj)
    glob = "ab*"
    expected = fnmatch.fnmatch(str(obj.name), glob)
    assert result == expected


@_settings_light
@given(obj=rich_data_object())
def test_like_suffix_match(obj: types.SimpleNamespace) -> None:
    """Like('%cd') should match names ending with 'cd'."""
    result = Like(Field("name"), "%cd").evaluate(obj)
    glob = "*cd"
    expected = fnmatch.fnmatch(str(obj.name), glob)
    assert result == expected


@_settings_light
@given(obj=rich_data_object())
def test_like_contains_match(obj: types.SimpleNamespace) -> None:
    """Like('%ab%') should match names containing 'ab'."""
    result = Like(Field("name"), "%ab%").evaluate(obj)
    glob = "*ab*"
    expected = fnmatch.fnmatch(str(obj.name), glob)
    assert result == expected


@_settings_light
@given(obj=rich_data_object())
def test_like_underscore_single_char(obj: types.SimpleNamespace) -> None:
    """Like('_') should match single-character names only."""
    result = Like(Field("name"), "_").evaluate(obj)
    glob = "?"
    expected = fnmatch.fnmatch(str(obj.name), glob)
    assert result == expected


@_settings_light
@given(obj=rich_data_object())
def test_ilike_case_insensitive(obj: types.SimpleNamespace) -> None:
    """ILike should be case-insensitive."""
    # Since our names are lowercase, test with uppercase pattern
    result = ILike(Field("name"), "%AB%").evaluate(obj)
    val = str(obj.name).lower()
    glob = "*ab*"
    expected = fnmatch.fnmatch(val, glob)
    assert result == expected


@_settings_light
@given(obj=rich_data_object())
def test_ilike_matches_like_when_same_case(obj: types.SimpleNamespace) -> None:
    """ILike with lowercase pattern on lowercase name should match Like."""
    pattern = "%ab%"
    like_result = Like(Field("name"), pattern).evaluate(obj)
    ilike_result = ILike(Field("name"), pattern).evaluate(obj)
    # Since names are lowercase and pattern is lowercase, results should match.
    assert like_result == ilike_result


# ===========================================================================
# SECTION 8: Array Operators
# ===========================================================================


@_settings
@given(
    obj=rich_data_object(),
    value=st.sampled_from(_tag_values),
)
def test_array_contains_evaluation(
    obj: types.SimpleNamespace, value: str
) -> None:
    result = ArrayContains(Field("tags"), value).evaluate(obj)
    assert result == (value in obj.tags)


@_settings
@given(
    obj=rich_data_object(),
    values=st.frozensets(
        st.sampled_from(_tag_values), min_size=1, max_size=4
    ).map(tuple),
)
def test_array_any_evaluation(
    obj: types.SimpleNamespace, values: tuple[str, ...]
) -> None:
    result = ArrayAny(Field("tags"), values).evaluate(obj)
    assert result == any(v in obj.tags for v in values)


@_settings
@given(
    obj=rich_data_object(),
    values=st.frozensets(
        st.sampled_from(_tag_values), min_size=1, max_size=4
    ).map(tuple),
)
def test_array_all_evaluation(
    obj: types.SimpleNamespace, values: tuple[str, ...]
) -> None:
    result = ArrayAll(Field("tags"), values).evaluate(obj)
    assert result == all(v in obj.tags for v in values)


@_settings
@given(
    obj=rich_data_object(),
    values=st.frozensets(
        st.sampled_from(_tag_values), min_size=1, max_size=4
    ).map(tuple),
)
def test_array_overlap_evaluation(
    obj: types.SimpleNamespace, values: tuple[str, ...]
) -> None:
    result = ArrayOverlap(Field("tags"), values).evaluate(obj)
    assert result == bool(set(obj.tags) & set(values))


# ArrayContains on non-collection returns False
def test_array_contains_non_collection() -> None:
    obj = types.SimpleNamespace(tags="not_a_list")
    assert ArrayContains(Field("tags"), "x").evaluate(obj) is False


def test_array_any_non_collection() -> None:
    obj = types.SimpleNamespace(tags=42)
    assert ArrayAny(Field("tags"), ("a", "b")).evaluate(obj) is False


def test_array_all_non_collection() -> None:
    obj = types.SimpleNamespace(tags=42)
    assert ArrayAll(Field("tags"), ("a", "b")).evaluate(obj) is False


def test_array_overlap_non_collection() -> None:
    obj = types.SimpleNamespace(tags=42)
    assert ArrayOverlap(Field("tags"), ("a", "b")).evaluate(obj) is False


# ArrayAll with empty values tuple is always True (vacuous truth)
def test_array_all_empty_values() -> None:
    obj = types.SimpleNamespace(tags=["a", "b"])
    assert ArrayAll(Field("tags"), ()).evaluate(obj) is True


# ArrayAny with empty values tuple is always False
def test_array_any_empty_values() -> None:
    obj = types.SimpleNamespace(tags=["a", "b"])
    assert ArrayAny(Field("tags"), ()).evaluate(obj) is False


# ArrayOverlap implies ArrayAny
@_settings
@given(
    obj=rich_data_object(),
    values=st.frozensets(
        st.sampled_from(_tag_values), min_size=1, max_size=4
    ).map(tuple),
)
def test_array_overlap_implies_array_any(
    obj: types.SimpleNamespace, values: tuple[str, ...]
) -> None:
    """ArrayOverlap and ArrayAny should agree."""
    overlap = ArrayOverlap(Field("tags"), values).evaluate(obj)
    any_result = ArrayAny(Field("tags"), values).evaluate(obj)
    assert overlap == any_result


# ArrayAll implies ArrayContains for each element
@_settings_light
@given(
    obj=rich_data_object(),
    values=st.frozensets(
        st.sampled_from(_tag_values), min_size=1, max_size=3
    ).map(tuple),
)
def test_array_all_implies_each_contains(
    obj: types.SimpleNamespace, values: tuple[str, ...]
) -> None:
    all_result = ArrayAll(Field("tags"), values).evaluate(obj)
    if all_result:
        for v in values:
            assert ArrayContains(Field("tags"), v).evaluate(obj) is True


# ===========================================================================
# SECTION 9: JSON Operators
# ===========================================================================


@_settings
@given(obj=rich_data_object(), key=_meta_keys)
def test_json_has_key_evaluation(
    obj: types.SimpleNamespace, key: str
) -> None:
    result = JsonHasKey(Field("metadata"), key).evaluate(obj)
    assert result == (key in obj.metadata)


@_settings
@given(obj=rich_data_object(), key=_meta_keys)
def test_json_extract_simple_key(
    obj: types.SimpleNamespace, key: str
) -> None:
    result = JsonExtract(Field("metadata"), key).evaluate(obj)
    expected = obj.metadata.get(key)
    assert result == expected


def test_json_extract_nested_path() -> None:
    obj = types.SimpleNamespace(
        metadata={"profile": {"name": "alice", "age": 30}}
    )
    result = JsonExtract(Field("metadata"), "profile.name").evaluate(obj)
    assert result == "alice"


def test_json_extract_array_index() -> None:
    obj = types.SimpleNamespace(metadata={"items": ["a", "b", "c"]})
    result = JsonExtract(Field("metadata"), "items.1").evaluate(obj)
    assert result == "b"


def test_json_extract_missing_path() -> None:
    obj = types.SimpleNamespace(metadata={"a": 1})
    result = JsonExtract(Field("metadata"), "nonexistent.deep").evaluate(obj)
    assert result is None


def test_json_extract_index_out_of_range() -> None:
    obj = types.SimpleNamespace(metadata={"items": [1, 2]})
    result = JsonExtract(Field("metadata"), "items.99").evaluate(obj)
    assert result is None


@_settings
@given(obj=rich_data_object())
def test_json_contains_dict_subset(obj: types.SimpleNamespace) -> None:
    """JsonContains with a dict checks key-value subset."""
    if obj.metadata:
        # Pick a single key-value from metadata to test containment
        key = next(iter(obj.metadata))
        subset = {key: obj.metadata[key]}
        result = JsonContains(Field("metadata"), subset).evaluate(obj)
        assert result is True


def test_json_contains_partial_dict() -> None:
    obj = types.SimpleNamespace(metadata={"role": "admin", "level": 5})
    assert JsonContains(Field("metadata"), {"role": "admin"}).evaluate(obj) is True
    assert JsonContains(Field("metadata"), {"role": "user"}).evaluate(obj) is False


def test_json_contains_full_match() -> None:
    obj = types.SimpleNamespace(metadata={"role": "admin"})
    assert (
        JsonContains(Field("metadata"), {"role": "admin"}).evaluate(obj) is True
    )


def test_json_contains_non_dict_equality() -> None:
    """When field is not a dict, JsonContains falls back to equality."""
    obj = types.SimpleNamespace(metadata="hello")
    assert JsonContains(Field("metadata"), "hello").evaluate(obj) is True
    assert JsonContains(Field("metadata"), "world").evaluate(obj) is False


def test_json_has_key_non_dict() -> None:
    obj = types.SimpleNamespace(metadata="not_a_dict")
    assert JsonHasKey(Field("metadata"), "key").evaluate(obj) is False


# ===========================================================================
# SECTION 10: Operator Overloads
# ===========================================================================


@_settings
@given(obj=rich_data_object(), v=_small_ints)
def test_and_operator_overload(obj: types.SimpleNamespace, v: int) -> None:
    """expr1 & expr2 should produce And(expr1, expr2)."""
    e1 = Eq(Field("x"), Const(v))
    e2 = Gt(Field("y"), Const(0))
    overloaded = e1 & e2
    explicit = And(e1, e2)
    assert overloaded.evaluate(obj) == explicit.evaluate(obj)


@_settings
@given(obj=rich_data_object(), v=_small_ints)
def test_or_operator_overload(obj: types.SimpleNamespace, v: int) -> None:
    """expr1 | expr2 should produce Or(expr1, expr2)."""
    e1 = Eq(Field("x"), Const(v))
    e2 = Lt(Field("y"), Const(0))
    overloaded = e1 | e2
    explicit = Or(e1, e2)
    assert overloaded.evaluate(obj) == explicit.evaluate(obj)


@_settings
@given(obj=rich_data_object(), v=_small_ints)
def test_not_operator_overload(obj: types.SimpleNamespace, v: int) -> None:
    """~expr should produce Not(expr)."""
    e = Eq(Field("x"), Const(v))
    overloaded = ~e
    explicit = Not(e)
    assert overloaded.evaluate(obj) == explicit.evaluate(obj)


def test_and_operator_returns_and_type() -> None:
    e1 = Field("x")
    e2 = Field("y")
    result = e1 & e2
    assert isinstance(result, And)


def test_or_operator_returns_or_type() -> None:
    e1 = Field("x")
    e2 = Field("y")
    result = e1 | e2
    assert isinstance(result, Or)


def test_not_operator_returns_not_type() -> None:
    e = Field("x")
    result = ~e
    assert isinstance(result, Not)


# Chained operator overloads
@_settings
@given(obj=rich_data_object())
def test_chained_operators(obj: types.SimpleNamespace) -> None:
    """(a & b) | (~c) should evaluate correctly."""
    a = Gt(Field("x"), Const(0))
    b = Lt(Field("y"), Const(0))
    c = Eq(Field("z"), Const(0))
    expr = (a & b) | (~c)
    expected = Or(And(a, b), Not(c)).evaluate(obj)
    assert expr.evaluate(obj) == expected


# ===========================================================================
# SECTION 11: children() Method
# ===========================================================================


def test_children_field() -> None:
    assert Field("x").children() == ()


def test_children_const() -> None:
    assert Const(42).children() == ()


def test_children_eq() -> None:
    a, b = Field("x"), Const(1)
    assert Eq(a, b).children() == (a, b)


def test_children_ne() -> None:
    a, b = Field("x"), Const(1)
    assert Ne(a, b).children() == (a, b)


def test_children_lt() -> None:
    a, b = Field("x"), Const(1)
    assert Lt(a, b).children() == (a, b)


def test_children_le() -> None:
    a, b = Field("x"), Const(1)
    assert Le(a, b).children() == (a, b)


def test_children_gt() -> None:
    a, b = Field("x"), Const(1)
    assert Gt(a, b).children() == (a, b)


def test_children_ge() -> None:
    a, b = Field("x"), Const(1)
    assert Ge(a, b).children() == (a, b)


def test_children_and() -> None:
    a, b = Field("x"), Field("y")
    assert And(a, b).children() == (a, b)


def test_children_or() -> None:
    a, b = Field("x"), Field("y")
    assert Or(a, b).children() == (a, b)


def test_children_not() -> None:
    a = Field("x")
    assert Not(a).children() == (a,)


def test_children_in() -> None:
    f = Field("x")
    expr = In(f, (1, 2, 3))
    # In.values is a tuple of ints, not Expr nodes, so only field is returned
    assert expr.children() == (f,)


def test_children_contains() -> None:
    f = Field("name")
    expr = Contains(f, "al")
    assert expr.children() == (f,)


def test_children_startswith() -> None:
    f = Field("name")
    expr = StartsWith(f, "al")
    assert expr.children() == (f,)


def test_children_endswith() -> None:
    f = Field("name")
    expr = EndsWith(f, "ce")
    assert expr.children() == (f,)


def test_children_isnull() -> None:
    f = Field("val")
    assert IsNull(f).children() == (f,)


def test_children_isnotnull() -> None:
    f = Field("val")
    assert IsNotNull(f).children() == (f,)


def test_children_between() -> None:
    f, lo, hi = Field("x"), Const(1), Const(10)
    assert Between(f, lo, hi).children() == (f, lo, hi)


def test_children_like() -> None:
    f = Field("name")
    assert Like(f, "%test%").children() == (f,)


def test_children_ilike() -> None:
    f = Field("name")
    assert ILike(f, "%test%").children() == (f,)


def test_children_array_contains() -> None:
    f = Field("tags")
    expr = ArrayContains(f, "vip")
    assert expr.children() == (f,)


def test_children_array_any() -> None:
    f = Field("tags")
    expr = ArrayAny(f, ("a", "b"))
    assert expr.children() == (f,)


def test_children_array_all() -> None:
    f = Field("tags")
    expr = ArrayAll(f, ("a", "b"))
    assert expr.children() == (f,)


def test_children_array_overlap() -> None:
    f = Field("tags")
    expr = ArrayOverlap(f, ("a", "b"))
    assert expr.children() == (f,)


def test_children_json_extract() -> None:
    f = Field("metadata")
    expr = JsonExtract(f, "key")
    assert expr.children() == (f,)


def test_children_json_contains() -> None:
    f = Field("metadata")
    expr = JsonContains(f, {"k": "v"})
    assert expr.children() == (f,)


def test_children_json_has_key() -> None:
    f = Field("metadata")
    expr = JsonHasKey(f, "key")
    assert expr.children() == (f,)


# ===========================================================================
# SECTION 12: Compositional / Cross-Type Properties
# ===========================================================================


@_settings
@given(obj=rich_data_object(), v=_small_ints)
def test_not_eq_equals_ne(obj: types.SimpleNamespace, v: int) -> None:
    """Not(Eq(f, v)) should agree with Ne(f, v)."""
    not_eq = Not(Eq(Field("x"), Const(v))).evaluate(obj)
    ne = Ne(Field("x"), Const(v)).evaluate(obj)
    assert not_eq == ne


@_settings
@given(obj=rich_data_object(), v=_small_ints)
def test_not_lt_equals_ge(obj: types.SimpleNamespace, v: int) -> None:
    """Not(Lt(f, v)) should agree with Ge(f, v)."""
    not_lt = Not(Lt(Field("x"), Const(v))).evaluate(obj)
    ge = Ge(Field("x"), Const(v)).evaluate(obj)
    assert not_lt == ge


@_settings
@given(obj=rich_data_object(), v=_small_ints)
def test_not_gt_equals_le(obj: types.SimpleNamespace, v: int) -> None:
    """Not(Gt(f, v)) should agree with Le(f, v)."""
    not_gt = Not(Gt(Field("x"), Const(v))).evaluate(obj)
    le = Le(Field("x"), Const(v)).evaluate(obj)
    assert not_gt == le


@_settings
@given(obj=rich_data_object())
def test_not_isnull_equals_isnotnull(obj: types.SimpleNamespace) -> None:
    """Not(IsNull(f)) == IsNotNull(f)."""
    not_null = Not(IsNull(Field("val"))).evaluate(obj)
    is_not_null = IsNotNull(Field("val")).evaluate(obj)
    assert not_null == is_not_null


@_settings
@given(obj=rich_data_object())
def test_contains_implies_like(obj: types.SimpleNamespace) -> None:
    """Contains(f, 'ab') should agree with Like(f, '%ab%')."""
    contains = Contains(Field("name"), "ab").evaluate(obj)
    like = Like(Field("name"), "%ab%").evaluate(obj)
    assert contains == like


@_settings
@given(obj=rich_data_object())
def test_startswith_implies_like(obj: types.SimpleNamespace) -> None:
    """StartsWith(f, 'ab') should agree with Like(f, 'ab%')."""
    sw = StartsWith(Field("name"), "ab").evaluate(obj)
    like = Like(Field("name"), "ab%").evaluate(obj)
    assert sw == like


@_settings
@given(obj=rich_data_object())
def test_endswith_implies_like(obj: types.SimpleNamespace) -> None:
    """EndsWith(f, 'ab') should agree with Like(f, '%ab')."""
    ew = EndsWith(Field("name"), "ab").evaluate(obj)
    like = Like(Field("name"), "%ab").evaluate(obj)
    assert ew == like


# Distributive law: a & (b | c) == (a & b) | (a & c)
@_settings
@given(a=bool_expr(), b=bool_expr(), c=bool_expr(), obj=data_object())
def test_and_distributes_over_or(
    a: Expr, b: Expr, c: Expr, obj: types.SimpleNamespace
) -> None:
    lhs = And(a, Or(b, c)).evaluate(obj)
    rhs = Or(And(a, b), And(a, c)).evaluate(obj)
    assert lhs == rhs


# Absorption: a & (a | b) == a, a | (a & b) == a
@_settings
@given(a=bool_expr(), b=bool_expr(), obj=data_object())
def test_absorption_and(a: Expr, b: Expr, obj: types.SimpleNamespace) -> None:
    assert And(a, Or(a, b)).evaluate(obj) == a.evaluate(obj)


@_settings
@given(a=bool_expr(), b=bool_expr(), obj=data_object())
def test_absorption_or(a: Expr, b: Expr, obj: types.SimpleNamespace) -> None:
    assert Or(a, And(a, b)).evaluate(obj) == a.evaluate(obj)


# Complement: a & ~a == False, a | ~a == True
@_settings
@given(a=bool_expr(), obj=data_object())
def test_complement_and(a: Expr, obj: types.SimpleNamespace) -> None:
    assert And(a, Not(a)).evaluate(obj) is False


@_settings
@given(a=bool_expr(), obj=data_object())
def test_complement_or(a: Expr, obj: types.SimpleNamespace) -> None:
    assert Or(a, Not(a)).evaluate(obj) is True


# ===========================================================================
# SECTION 13: Frozen / Immutable Guarantees
# ===========================================================================


def test_field_is_frozen() -> None:
    f = Field("x")
    with pytest.raises(AttributeError):
        f.name = "y"  # type: ignore[misc]


def test_const_is_frozen() -> None:
    c = Const(42)
    with pytest.raises(AttributeError):
        c.value = 99  # type: ignore[misc]


def test_eq_is_frozen() -> None:
    e = Eq(Field("x"), Const(1))
    with pytest.raises(AttributeError):
        e.left = Field("y")  # type: ignore[misc]


def test_and_is_frozen() -> None:
    a = And(Field("x"), Field("y"))
    with pytest.raises(AttributeError):
        a.left = Field("z")  # type: ignore[misc]

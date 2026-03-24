# pyright: reportPrivateUsage=false
"""Property-based tests for expression serialization roundtrip and analysis.

Uses hypothesis to generate arbitrary Expr trees and verify invariants:
- Serialization roundtrip faithfulness
- Field extraction completeness
- Complexity positivity
- Depth bounds
- Repr determinism and non-emptiness
"""

from __future__ import annotations


import hypothesis.strategies as st
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
    Lt,
    Like,
    Ne,
    Not,
    Or,
    StartsWith,
)
from emergent.wire.axis.query._serialize import (
    expr_complexity,
    expr_depth,
    expr_fields,
    expr_from_dict,
    expr_repr,
    expr_to_dict,
)

# ─── Strategies ──────────────────────────────────────────────────────────────

FIELD_NAMES = ("id", "name", "balance", "active", "email")

field_strategy = st.sampled_from(FIELD_NAMES).map(Field)

# JSON-serializable primitives that survive dict roundtrip faithfully.
# Exclude: tuple (becomes list), NaN/Inf (not JSON-serializable),
# complex objects, etc.
json_primitive = st.one_of(
    st.integers(min_value=-(2**31), max_value=2**31),
    st.text(min_size=0, max_size=10, alphabet=st.characters(categories=("L", "N", "P", "Z"))),
    st.booleans(),
    st.none(),
    st.floats(allow_nan=False, allow_infinity=False, allow_subnormal=False),
)

const_strategy = json_primitive.map(Const)

# Leaf nodes: Field or Const
leaf_strategy = st.one_of(field_strategy, const_strategy)

# Non-empty short strings for pattern/substring/prefix/suffix/path/key
short_text = st.text(min_size=1, max_size=8, alphabet=st.characters(categories=("L", "N")))

# Tuple of JSON primitives for In/ArrayAny/ArrayAll/ArrayOverlap values
value_tuple = st.lists(json_primitive, min_size=1, max_size=4).map(tuple)


def expr_strategy() -> st.SearchStrategy[Expr]:
    """Build a comprehensive Expr generator covering all types (except Regex)."""
    return st.recursive(
        leaf_strategy,
        lambda children: st.one_of(
            # Comparison (binary: left, right are arbitrary exprs)
            st.tuples(children, children).map(lambda lr: Eq(lr[0], lr[1])),
            st.tuples(children, children).map(lambda lr: Ne(lr[0], lr[1])),
            st.tuples(children, children).map(lambda lr: Lt(lr[0], lr[1])),
            st.tuples(children, children).map(lambda lr: Le(lr[0], lr[1])),
            st.tuples(children, children).map(lambda lr: Gt(lr[0], lr[1])),
            st.tuples(children, children).map(lambda lr: Ge(lr[0], lr[1])),
            # Logical
            st.tuples(children, children).map(lambda lr: And(lr[0], lr[1])),
            st.tuples(children, children).map(lambda lr: Or(lr[0], lr[1])),
            children.map(Not),
            # Collection — field arg is always a Field for semantic validity,
            # but the serializer handles any Expr, so we use field_strategy.
            st.tuples(field_strategy, value_tuple).map(lambda fv: In(fv[0], fv[1])),
            st.tuples(field_strategy, short_text).map(lambda fs: Contains(fs[0], fs[1])),
            st.tuples(field_strategy, short_text).map(lambda fs: StartsWith(fs[0], fs[1])),
            st.tuples(field_strategy, short_text).map(lambda fs: EndsWith(fs[0], fs[1])),
            # Null
            field_strategy.map(IsNull),
            field_strategy.map(IsNotNull),
            # Range — field, low, high are exprs
            st.tuples(field_strategy, children, children).map(
                lambda flh: Between(flh[0], flh[1], flh[2])
            ),
            # Pattern (no Regex)
            st.tuples(field_strategy, short_text).map(lambda fp: Like(fp[0], fp[1])),
            st.tuples(field_strategy, short_text).map(lambda fp: ILike(fp[0], fp[1])),
            # Array
            st.tuples(field_strategy, json_primitive).map(
                lambda fv: ArrayContains(fv[0], fv[1])
            ),
            st.tuples(field_strategy, value_tuple).map(lambda fv: ArrayAny(fv[0], fv[1])),
            st.tuples(field_strategy, value_tuple).map(lambda fv: ArrayAll(fv[0], fv[1])),
            st.tuples(field_strategy, value_tuple).map(
                lambda fv: ArrayOverlap(fv[0], fv[1])
            ),
            # JSON
            st.tuples(field_strategy, short_text).map(lambda fp: JsonExtract(fp[0], fp[1])),
            st.tuples(field_strategy, json_primitive).map(
                lambda fv: JsonContains(fv[0], fv[1])
            ),
            st.tuples(field_strategy, short_text).map(lambda fk: JsonHasKey(fk[0], fk[1])),
        ),
        max_leaves=15,
    )


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _collect_field_names(expr: Expr) -> set[str]:
    """Manually collect all Field.name values by walking the tree."""
    if isinstance(expr, Field):
        return {expr.name}
    result: set[str] = set()
    for child in expr.children():
        result |= _collect_field_names(child)
    return result


# ─── Properties ──────────────────────────────────────────────────────────────


@given(e=expr_strategy())
@settings(max_examples=500, deadline=None)
def test_serialization_roundtrip(e: Expr) -> None:
    """expr_from_dict(expr_to_dict(e)) == e for all valid expressions."""
    serialized = expr_to_dict(e)
    deserialized = expr_from_dict(serialized)
    assert deserialized == e, (
        f"Roundtrip failed:\n  original:     {e!r}\n  serialized:   {serialized}\n  deserialized: {deserialized!r}"
    )


@given(e=expr_strategy())
@settings(max_examples=500, deadline=None)
def test_field_extraction_completeness(e: Expr) -> None:
    """expr_fields(e) equals the set of all Field.name values in the tree."""
    expected = _collect_field_names(e)
    actual = expr_fields(e)
    assert actual == expected, (
        f"Field extraction mismatch:\n  expected: {expected}\n  actual:   {actual}\n  expr:     {e!r}"
    )


@given(e=expr_strategy())
@settings(max_examples=500, deadline=None)
def test_complexity_positivity(e: Expr) -> None:
    """expr_complexity(e) >= 1 for all expressions."""
    c = expr_complexity(e)
    assert c >= 1, f"Complexity {c} < 1 for {e!r}"


@given(e=expr_strategy())
@settings(max_examples=500, deadline=None)
def test_depth_bounded_by_complexity(e: Expr) -> None:
    """expr_depth(e) <= expr_complexity(e) for all expressions.

    Depth counts the longest path, complexity counts all nodes.
    A linear chain has depth == complexity; branching makes depth < complexity.
    """
    d = expr_depth(e)
    c = expr_complexity(e)
    assert d <= c, f"Depth {d} > complexity {c} for {e!r}"


@given(e=expr_strategy())
@settings(max_examples=500, deadline=None)
def test_repr_non_empty(e: Expr) -> None:
    """len(expr_repr(e)) > 0 for all expressions."""
    r = expr_repr(e)
    assert len(r) > 0, f"Repr is empty for {e!r}"


@given(e=expr_strategy())
@settings(max_examples=500, deadline=None)
def test_repr_contains_field_names(e: Expr) -> None:
    """expr_repr mentions every field referenced in the expression."""
    fields = expr_fields(e)
    r = expr_repr(e)
    for f in fields:
        assert f in r, f"Field {f!r} missing from repr {r!r}"


@given(e=expr_strategy())
@settings(max_examples=500, deadline=None)
def test_double_serialization_roundtrip(e: Expr) -> None:
    """Two roundtrips produce identical results — no drift."""
    once = expr_from_dict(expr_to_dict(e))
    twice = expr_from_dict(expr_to_dict(once))
    assert once == twice

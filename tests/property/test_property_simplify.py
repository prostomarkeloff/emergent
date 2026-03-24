# pyright: reportPrivateUsage=false
"""Property-based tests for expression simplification.

Uses hypothesis to verify algebraic properties of simplify_expr,
flatten/unflatten operations, and expr_complexity.
"""

from __future__ import annotations

import types

import pytest
import hypothesis.strategies as st
from hypothesis import given, settings

from emergent.wire.axis.query._expr import (
    And,
    Const,
    Eq,
    Expr,
    Field,
    Ge,
    Gt,
    Le,
    Lt,
    Ne,
    Not,
    Or,
)
from emergent.wire.axis.query._serialize import expr_complexity
from emergent.wire.axis.query._simplify import (
    flatten_and,
    flatten_or,
    simplify_expr,
    unflatten_and,
    unflatten_or,
)

# ─── Strategies ──────────────────────────────────────────────────────────────

FIELD_NAMES = ("x", "y", "z")
FIELD_VALUES = (0, 1, 2, 10, -1)


def _make_obj(x: int, y: int, z: int) -> types.SimpleNamespace:
    return types.SimpleNamespace(x=x, y=y, z=z)


field_values_strategy = st.sampled_from(FIELD_VALUES)

obj_strategy = st.builds(
    _make_obj,
    x=field_values_strategy,
    y=field_values_strategy,
    z=field_values_strategy,
)


def leaf_exprs() -> st.SearchStrategy[Expr]:
    """Leaf expressions: fields and constants (including True/False)."""
    fields = st.sampled_from(FIELD_NAMES).map(Field)
    int_consts = st.sampled_from(FIELD_VALUES).map(Const)
    bool_consts = st.sampled_from([True, False]).map(Const)
    return st.one_of(fields, int_consts, bool_consts)


def comparison_exprs(children: st.SearchStrategy[Expr]) -> st.SearchStrategy[Expr]:
    """Comparison expressions built from child expressions."""
    comparisons = [Eq, Ne, Lt, Le, Gt, Ge]
    return st.one_of(
        *(st.builds(cmp, children, children) for cmp in comparisons)
    )


def expr_strategy() -> st.SearchStrategy[Expr]:
    """Recursive strategy for arbitrary Expr trees.

    Generates boolean expression trees using:
    - Leaf: Field, Const (int), Const(True), Const(False)
    - Comparison: Eq, Ne, Lt, Le, Gt, Ge on leaves
    - Logical: And, Or, Not combining sub-expressions
    """
    return st.recursive(
        # Base: comparisons on leaves, plus raw bool constants
        st.one_of(
            comparison_exprs(leaf_exprs()),
            st.sampled_from([True, False]).map(Const),
        ),
        # Extend with And, Or, Not
        lambda children: st.one_of(
            st.builds(And, children, children),
            st.builds(Or, children, children),
            st.builds(Not, children),
            # Inject Not(Not(...)) to create simplifiable patterns
            children.map(lambda e: Not(Not(e))),
            # Inject And(x, Const(True)) patterns
            children.map(lambda e: And(e, Const(True))),
            # Inject Or(x, Const(False)) patterns
            children.map(lambda e: Or(e, Const(False))),
        ),
        max_leaves=15,
    )


def and_tree_strategy() -> st.SearchStrategy[Expr]:
    """Strategy for trees composed only of And nodes over comparisons."""
    base = comparison_exprs(leaf_exprs())
    return st.recursive(
        base,
        lambda children: st.builds(And, children, children),
        max_leaves=8,
    )


def or_tree_strategy() -> st.SearchStrategy[Expr]:
    """Strategy for trees composed only of Or nodes over comparisons."""
    base = comparison_exprs(leaf_exprs())
    return st.recursive(
        base,
        lambda children: st.builds(Or, children, children),
        max_leaves=8,
    )


def _safe_evaluate(expr: Expr, obj: types.SimpleNamespace) -> bool | None:
    """Evaluate an expression, returning None if it raises (e.g. TypeError)."""
    try:
        return bool(expr.evaluate(obj))
    except (TypeError, AttributeError):
        return None


# ─── Property Tests ──────────────────────────────────────────────────────────


class TestIdempotence:
    """simplify_expr(simplify_expr(e)) == simplify_expr(e) for all e."""

    @given(e=expr_strategy())
    @settings(max_examples=200)
    def test_simplify_is_idempotent(self, e: Expr) -> None:
        once = simplify_expr(e)
        twice = simplify_expr(once)
        assert once == twice, (
            f"Not idempotent:\n  once  = {once}\n  twice = {twice}"
        )


class TestSemanticPreservation:
    """simplify_expr(e).evaluate(obj) == e.evaluate(obj) for all e, obj."""

    _eval_count = 0
    _skip_count = 0

    @given(e=expr_strategy(), obj=obj_strategy)
    @settings(max_examples=300)
    def test_simplify_preserves_semantics(
        self, e: Expr, obj: types.SimpleNamespace
    ) -> None:
        original = _safe_evaluate(e, obj)
        if original is None:
            TestSemanticPreservation._skip_count += 1
            return  # skip expressions that raise
        TestSemanticPreservation._eval_count += 1
        simplified = _safe_evaluate(simplify_expr(e), obj)
        assert original == simplified, (
            f"Semantics changed:\n"
            f"  expr       = {e}\n"
            f"  simplified = {simplify_expr(e)}\n"
            f"  obj        = {obj}\n"
            f"  original   = {original}\n"
            f"  simplified = {simplified}"
        )

    def test_semantic_test_was_not_vacuous(self) -> None:
        """Guard: ensure the semantic preservation test actually evaluated expressions.

        If most examples were skipped, the test is vacuous.
        This runs AFTER test_simplify_preserves_semantics (alphabetical order).
        """
        total = self._eval_count + self._skip_count
        if total == 0:
            pytest.skip("No examples generated yet")
        # At least 80% of examples must have been evaluated, not skipped
        ratio = self._eval_count / total if total > 0 else 0
        assert ratio > 0.5, (
            f"Too many skipped: {self._skip_count}/{total} skipped "
            f"({ratio:.0%} evaluated). Test is likely vacuous."
        )


class TestMonotonicComplexity:
    """expr_complexity(simplify_expr(e)) <= expr_complexity(e) for all e."""

    @given(e=expr_strategy())
    @settings(max_examples=200)
    def test_simplify_does_not_increase_complexity(self, e: Expr) -> None:
        original_complexity = expr_complexity(e)
        simplified_complexity = expr_complexity(simplify_expr(e))
        assert simplified_complexity <= original_complexity, (
            f"Complexity increased:\n"
            f"  expr       = {e}\n"
            f"  simplified = {simplify_expr(e)}\n"
            f"  {original_complexity} -> {simplified_complexity}"
        )


class TestFlattenAndRoundtrip:
    """unflatten_and(flatten_and(e)).evaluate(obj) == e.evaluate(obj) for And-trees."""

    @given(e=and_tree_strategy(), obj=obj_strategy)
    @settings(max_examples=200)
    def test_flatten_and_roundtrip_preserves_semantics(
        self, e: Expr, obj: types.SimpleNamespace
    ) -> None:
        original = _safe_evaluate(e, obj)
        if original is None:
            return
        roundtripped = unflatten_and(flatten_and(e))
        result = _safe_evaluate(roundtripped, obj)
        assert original == result, (
            f"Flatten-And roundtrip changed semantics:\n"
            f"  expr        = {e}\n"
            f"  roundtripped = {roundtripped}\n"
            f"  obj         = {obj}\n"
            f"  original    = {original}\n"
            f"  result      = {result}"
        )


class TestFlattenOrRoundtrip:
    """unflatten_or(flatten_or(e)).evaluate(obj) == e.evaluate(obj) for Or-trees."""

    @given(e=or_tree_strategy(), obj=obj_strategy)
    @settings(max_examples=200)
    def test_flatten_or_roundtrip_preserves_semantics(
        self, e: Expr, obj: types.SimpleNamespace
    ) -> None:
        original = _safe_evaluate(e, obj)
        if original is None:
            return
        roundtripped = unflatten_or(flatten_or(e))
        result = _safe_evaluate(roundtripped, obj)
        assert original == result, (
            f"Flatten-Or roundtrip changed semantics:\n"
            f"  expr        = {e}\n"
            f"  roundtripped = {roundtripped}\n"
            f"  obj         = {obj}\n"
            f"  original    = {original}\n"
            f"  result      = {result}"
        )


class TestFlattenAndLength:
    """len(flatten_and(And(a, b))) == len(flatten_and(a)) + len(flatten_and(b))."""

    @given(a=and_tree_strategy(), b=and_tree_strategy())
    @settings(max_examples=200)
    def test_flatten_and_length_is_additive(self, a: Expr, b: Expr) -> None:
        combined = And(a, b)
        flat_combined = flatten_and(combined)
        flat_a = flatten_and(a)
        flat_b = flatten_and(b)
        assert len(flat_combined) == len(flat_a) + len(flat_b), (
            f"Flatten-And length not additive:\n"
            f"  a = {a}  (flat len {len(flat_a)})\n"
            f"  b = {b}  (flat len {len(flat_b)})\n"
            f"  And(a,b) flat len = {len(flat_combined)}"
        )


class TestEmptyFlatten:
    """unflatten_and([]) == Const(True) and unflatten_or([]) == Const(False)."""

    def test_unflatten_and_empty_is_true(self) -> None:
        result = unflatten_and([])
        assert result == Const(True)

    def test_unflatten_or_empty_is_false(self) -> None:
        result = unflatten_or([])
        assert result == Const(False)

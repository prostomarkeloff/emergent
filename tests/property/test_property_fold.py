# pyright: reportPrivateUsage=false
"""Property-based tests for the fold() primitive.

Uses hypothesis to verify algebraic properties of fold:
identity, single-item equivalence, open-world skip,
handler precedence, sequential composition, traced equivalence.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from hypothesis import given
from hypothesis import strategies as st

from emergent.wire.compile._core import fold
from emergent.wire.compile._trace import ListCollector


# ═══════════════════════════════════════════════════════════════════════════════
# Test-local types
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class FoldCtx:
    """Immutable accumulator context for property tests."""

    value: int


@runtime_checkable
class FoldCompilable(Protocol):
    """Protocol — capabilities that can compile into FoldCtx."""

    def compile_test(self, ctx: FoldCtx) -> FoldCtx: ...


@dataclass(frozen=True, slots=True)
class AddCap:
    """Capability that adds a fixed amount to ctx.value."""

    amount: int

    def compile_test(self, ctx: FoldCtx) -> FoldCtx:
        return FoldCtx(value=ctx.value + self.amount)


@dataclass(frozen=True, slots=True)
class MulCap:
    """Capability that multiplies ctx.value by a fixed factor."""

    factor: int

    def compile_test(self, ctx: FoldCtx) -> FoldCtx:
        return FoldCtx(value=ctx.value * self.factor)


@dataclass(frozen=True, slots=True)
class UnknownItem:
    """An item that does NOT implement FoldCompilable."""

    data: int


# ═══════════════════════════════════════════════════════════════════════════════
# Strategies
# ═══════════════════════════════════════════════════════════════════════════════

st_ctx = st.builds(FoldCtx, value=st.integers(min_value=-1000, max_value=1000))

st_add_cap = st.builds(AddCap, amount=st.integers(min_value=-100, max_value=100))
st_mul_cap = st.builds(MulCap, factor=st.integers(min_value=-10, max_value=10))
st_unknown = st.builds(UnknownItem, data=st.integers(min_value=-100, max_value=100))

st_capability = st.one_of(st_add_cap, st_mul_cap)
st_any_item = st.one_of(st_add_cap, st_mul_cap, st_unknown)

st_cap_list = st.lists(st_capability, max_size=20)
st_any_list = st.lists(st_any_item, max_size=20)


PROTO = FoldCompilable
METHOD = "compile_test"


# ═══════════════════════════════════════════════════════════════════════════════
# Property 1: Identity — fold of empty list returns initial unchanged
# ═══════════════════════════════════════════════════════════════════════════════


@given(initial=st_ctx)
def test_identity(initial: FoldCtx) -> None:
    """fold([], initial, proto, method) == initial for any initial context."""
    result = fold([], initial, PROTO, METHOD)
    assert result == initial


# ═══════════════════════════════════════════════════════════════════════════════
# Property 2: Single-item equivalence
# ═══════════════════════════════════════════════════════════════════════════════


@given(initial=st_ctx, cap=st_capability)
def test_single_item_equivalence(initial: FoldCtx, cap: AddCap | MulCap) -> None:
    """fold([cap], init, proto, method) == cap.compile_test(init)."""
    result = fold([cap], initial, PROTO, METHOD)
    expected = cap.compile_test(initial)
    assert result == expected


# ═══════════════════════════════════════════════════════════════════════════════
# Property 3: Open-world skip — unknown items don't crash, don't change ctx
# ═══════════════════════════════════════════════════════════════════════════════


@given(initial=st_ctx, unknowns=st.lists(st_unknown, min_size=1, max_size=20))
def test_open_world_skip(initial: FoldCtx, unknowns: list[UnknownItem]) -> None:
    """fold([unknown_items], init, proto, method) == init."""
    result = fold(unknowns, initial, PROTO, METHOD)
    assert result == initial


# ═══════════════════════════════════════════════════════════════════════════════
# Property 4: Handler precedence — handler wins over protocol dispatch
# ═══════════════════════════════════════════════════════════════════════════════


@given(initial=st_ctx, cap=st_add_cap)
def test_handler_precedence(initial: FoldCtx, cap: AddCap) -> None:
    """When both handler and protocol match, handler wins."""

    def handler_fn(item: AddCap, ctx: FoldCtx) -> FoldCtx:
        # Handler does something different: subtracts instead of adding
        return FoldCtx(value=ctx.value - item.amount)

    handlers = {AddCap: handler_fn}

    result = fold([cap], initial, PROTO, METHOD, handlers)
    expected_handler = FoldCtx(value=initial.value - cap.amount)
    expected_protocol = cap.compile_test(initial)

    assert result == expected_handler
    # Confirm the handler result differs from protocol result (unless amount is 0)
    if cap.amount != 0:
        assert result != expected_protocol


# ═══════════════════════════════════════════════════════════════════════════════
# Property 5: Composition / sequential — fold(a+b) == fold(b, fold(a, ...))
# ═══════════════════════════════════════════════════════════════════════════════


@given(initial=st_ctx, a=st_cap_list, b=st_cap_list)
def test_composition(
    initial: FoldCtx, a: list[AddCap | MulCap], b: list[AddCap | MulCap]
) -> None:
    """fold(a + b, init, ...) == fold(b, fold(a, init, ...), ...)."""
    combined = fold(a + b, initial, PROTO, METHOD)
    intermediate = fold(a, initial, PROTO, METHOD)
    sequential = fold(b, intermediate, PROTO, METHOD)
    assert combined == sequential


# ═══════════════════════════════════════════════════════════════════════════════
# Property 6: Traced equivalence — trace doesn't affect result
# ═══════════════════════════════════════════════════════════════════════════════


@given(initial=st_ctx, items=st_any_list)
def test_traced_equivalence(
    initial: FoldCtx, items: list[AddCap | MulCap | UnknownItem]
) -> None:
    """fold(..., trace=None) result equals fold(..., trace=collector) result."""
    result_untraced = fold(items, initial, PROTO, METHOD, trace=None)
    collector = ListCollector()
    result_traced = fold(items, initial, PROTO, METHOD, trace=collector)
    assert result_untraced == result_traced


# ═══════════════════════════════════════════════════════════════════════════════
# Property 7: Handler uses exact-type dispatch, not isinstance
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class SubAddCap(AddCap):
    """Subclass of AddCap — handler for AddCap should NOT match this."""
    pass


@given(initial=st_ctx, amount=st.integers(min_value=-100, max_value=100))
def test_handler_exact_type_not_isinstance(initial: FoldCtx, amount: int) -> None:
    """Handler for AddCap does NOT intercept SubAddCap — exact-type dispatch."""
    sub = SubAddCap(amount=amount)

    def handler_fn(item: AddCap, ctx: FoldCtx) -> FoldCtx:
        return FoldCtx(value=ctx.value * 999)  # obviously different

    handlers = {AddCap: handler_fn}

    result = fold([sub], initial, PROTO, METHOD, handlers)
    # SubAddCap implements FoldCompilable via inheritance,
    # so protocol dispatch should apply (not the handler).
    expected = sub.compile_test(initial)
    assert result == expected


# ═══════════════════════════════════════════════════════════════════════════════
# Property 8: Order matters — fold is a left-fold, not commutative
# ═══════════════════════════════════════════════════════════════════════════════


def test_fold_is_not_commutative() -> None:
    """fold([Add(2), Mul(3)]) != fold([Mul(3), Add(2)]) in general."""
    ctx = FoldCtx(value=1)
    ab = fold([AddCap(2), MulCap(3)], ctx, PROTO, METHOD)  # (1+2)*3 = 9
    ba = fold([MulCap(3), AddCap(2)], ctx, PROTO, METHOD)  # (1*3)+2 = 5
    assert ab != ba
    assert ab == FoldCtx(value=9)
    assert ba == FoldCtx(value=5)

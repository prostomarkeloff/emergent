# pyright: reportPrivateUsage=false
"""Property-based tests for SchemaCompiler and TargetCompiler algebraic laws.

Uses hypothesis to verify that the algebraic operations on SchemaCompiler
and TargetCompiler satisfy identity, idempotence, associativity,
commutativity (for &), annihilation, and size bounds.
"""

from __future__ import annotations


import hypothesis.strategies as st
from hypothesis import given

from emergent.wire.compile._phase import CompilationPhase, SchemaCompiler
from emergent.wire.compile._target import CodecBinding, TargetCompiler


# ═══════════════════════════════════════════════════════════════════════════════
# Fixture pool: 10 unique context types + matching protocols
# ═══════════════════════════════════════════════════════════════════════════════


def _make_ctx_and_protocol(i: int) -> tuple[type, type]:
    """Create a unique (context_type, protocol) pair for index i."""
    ctx_cls = type(f"Ctx{i}", (), {})

    # Protocol needs a compile_* method — use a namespace dict
    def _compile_method(self: object, ctx: object) -> object:
        return ctx

    proto_cls = type(
        f"Proto{i}",
        (),
        {f"compile_test{i}": _compile_method},
    )
    return ctx_cls, proto_cls


_POOL: list[tuple[type, type]] = [_make_ctx_and_protocol(i) for i in range(10)]
_CTX_TYPES: list[type] = [ctx for ctx, _ in _POOL]
_PROTO_TYPES: list[type] = [proto for _, proto in _POOL]


def _make_phase(i: int) -> CompilationPhase[object]:
    ctx_cls, proto_cls = _POOL[i]
    return CompilationPhase(
        context_type=ctx_cls,
        protocol=proto_cls,
        initial=lambda name, tp, _c=ctx_cls: _c(),
    )


_PHASES: list[CompilationPhase[object]] = [_make_phase(i) for i in range(10)]

EMPTY_SCHEMA = SchemaCompiler(phases=())


# ═══════════════════════════════════════════════════════════════════════════════
# Fixture pool for TargetCompiler: 10 unique codec types
# ═══════════════════════════════════════════════════════════════════════════════

_TRIGGER_TYPE = type("TestTrigger", (), {})

_CODEC_TYPES: list[type] = [type(f"Codec{i}", (), {}) for i in range(10)]


def _make_binding(i: int) -> CodecBinding[object]:
    return CodecBinding(
        codec_type=_CODEC_TYPES[i],
        from_codec=lambda *args, **kwargs: None,
    )


_BINDINGS: list[CodecBinding[object]] = [_make_binding(i) for i in range(10)]


def _empty_target() -> TargetCompiler[object]:
    return TargetCompiler(trigger_type=_TRIGGER_TYPE, adapters=())


# ═══════════════════════════════════════════════════════════════════════════════
# Hypothesis strategies
# ═══════════════════════════════════════════════════════════════════════════════

# Strategy: pick a subset of indices [0..9], build phases from them
_index_subsets = st.frozensets(st.integers(min_value=0, max_value=9))


@st.composite
def schema_compilers(draw: st.DrawFn) -> SchemaCompiler:
    indices = draw(_index_subsets)
    phases = tuple(_PHASES[i] for i in sorted(indices))
    return SchemaCompiler(phases=phases)


@st.composite
def target_compilers(draw: st.DrawFn) -> TargetCompiler[object]:
    indices = draw(_index_subsets)
    adapters = tuple(_BINDINGS[i] for i in sorted(indices))
    return TargetCompiler(trigger_type=_TRIGGER_TYPE, adapters=adapters)


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _schema_ctx_types(c: SchemaCompiler) -> set[type]:
    """Extract the set of context_types from a SchemaCompiler."""
    return {p.context_type for p in c.phases}


def _schema_ctx_list(c: SchemaCompiler) -> list[type]:
    """Extract ordered list of context_types from a SchemaCompiler."""
    return [p.context_type for p in c.phases]


def _target_codec_types(c: TargetCompiler[object]) -> set[type]:
    """Extract the set of codec_types from a TargetCompiler."""
    return {b.codec_type for b in c.adapters}


def _target_codec_list(c: TargetCompiler[object]) -> list[type]:  # noqa: F811
    """Extract ordered list of codec_types from a TargetCompiler."""
    _ = _target_codec_list  # self-reference to mark as used
    return [b.codec_type for b in c.adapters]


# Build a disjoint pair strategy for the roundtrip test
@st.composite
def disjoint_schema_pair(draw: st.DrawFn) -> tuple[SchemaCompiler, SchemaCompiler]:
    """Two SchemaCompilers with disjoint context_type sets."""
    all_indices = list(range(10))
    # Draw a partition point
    split = draw(st.integers(min_value=0, max_value=10))
    a_indices = draw(
        st.frozensets(st.sampled_from(all_indices[:split]) if split > 0 else st.nothing())
    )
    b_indices = draw(
        st.frozensets(
            st.sampled_from(all_indices[split:]) if split < 10 else st.nothing()
        )
    )
    a = SchemaCompiler(phases=tuple(_PHASES[i] for i in sorted(a_indices)))
    b = SchemaCompiler(phases=tuple(_PHASES[i] for i in sorted(b_indices)))
    return a, b


@st.composite
def disjoint_target_pair(
    draw: st.DrawFn,
) -> tuple[TargetCompiler[object], TargetCompiler[object]]:
    """Two TargetCompilers with disjoint codec_type sets."""
    all_indices = list(range(10))
    split = draw(st.integers(min_value=0, max_value=10))
    a_indices = draw(
        st.frozensets(st.sampled_from(all_indices[:split]) if split > 0 else st.nothing())
    )
    b_indices = draw(
        st.frozensets(
            st.sampled_from(all_indices[split:]) if split < 10 else st.nothing()
        )
    )
    a = TargetCompiler(
        trigger_type=_TRIGGER_TYPE,
        adapters=tuple(_BINDINGS[i] for i in sorted(a_indices)),
    )
    b = TargetCompiler(
        trigger_type=_TRIGGER_TYPE,
        adapters=tuple(_BINDINGS[i] for i in sorted(b_indices)),
    )
    return a, b


# ═══════════════════════════════════════════════════════════════════════════════
# SchemaCompiler property tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestSchemaCompilerAddition:
    """Tests for + (left-biased union)."""

    @given(a=schema_compilers())
    def test_add_identity_right(self, a: SchemaCompiler) -> None:
        """A + empty == A — preserves exact phases."""
        result = a + EMPTY_SCHEMA
        assert _schema_ctx_list(result) == _schema_ctx_list(a)
        # Identity must preserve instances, not just types
        for rp, ap in zip(result.phases, a.phases):
            assert rp is ap

    @given(a=schema_compilers())
    def test_add_identity_left(self, a: SchemaCompiler) -> None:
        """empty + A == A — preserves exact phases."""
        result = EMPTY_SCHEMA + a
        assert _schema_ctx_list(result) == _schema_ctx_list(a)

    @given(a=schema_compilers())
    def test_add_idempotent(self, a: SchemaCompiler) -> None:
        """A + A == A — no duplicates, left instances kept."""
        result = a + a
        assert len(result) == len(a)
        assert _schema_ctx_list(result) == _schema_ctx_list(a)
        # Must keep original (left) instances
        for rp, ap in zip(result.phases, a.phases):
            assert rp is ap

    @given(a=schema_compilers(), b=schema_compilers(), c=schema_compilers())
    def test_add_associative(self, a: SchemaCompiler, b: SchemaCompiler, c: SchemaCompiler) -> None:
        """(A + B) + C == A + (B + C) — same ordered context_type list."""
        left = (a + b) + c
        right = a + (b + c)
        assert _schema_ctx_list(left) == _schema_ctx_list(right)

    @given(a=schema_compilers(), b=schema_compilers())
    def test_add_left_biased(self, a: SchemaCompiler, b: SchemaCompiler) -> None:
        """When A and B overlap, A's instances are kept (left wins)."""
        result = a + b
        overlap = _schema_ctx_types(a) & _schema_ctx_types(b)
        for p in result.phases:
            if p.context_type in overlap:
                # Must be A's instance, not B's
                a_phase = next(ap for ap in a.phases if ap.context_type is p.context_type)
                assert p is a_phase


class TestSchemaCompilerMerge:
    """Tests for | (right-biased merge)."""

    @given(a=schema_compilers())
    def test_merge_identity_right(self, a: SchemaCompiler) -> None:
        """A | empty == A — preserves phases."""
        result = a | EMPTY_SCHEMA
        assert _schema_ctx_list(result) == _schema_ctx_list(a)

    @given(a=schema_compilers())
    def test_merge_identity_left(self, a: SchemaCompiler) -> None:
        """empty | A == A — preserves phases."""
        result = EMPTY_SCHEMA | a
        assert _schema_ctx_list(result) == _schema_ctx_list(a)

    @given(a=schema_compilers())
    def test_merge_idempotent(self, a: SchemaCompiler) -> None:
        """A | A == A."""
        result = a | a
        assert len(result) == len(a)
        assert _schema_ctx_list(result) == _schema_ctx_list(a)

    @given(a=schema_compilers(), b=schema_compilers(), c=schema_compilers())
    def test_merge_associative(self, a: SchemaCompiler, b: SchemaCompiler, c: SchemaCompiler) -> None:
        """(A | B) | C == A | (B | C) — same ordered context_type list."""
        left = (a | b) | c
        right = a | (b | c)
        assert _schema_ctx_list(left) == _schema_ctx_list(right)

    @given(a=schema_compilers(), b=schema_compilers())
    def test_merge_right_biased(self, a: SchemaCompiler, b: SchemaCompiler) -> None:
        """When A and B overlap, B's instances win (right overrides)."""
        result = a | b
        overlap = _schema_ctx_types(a) & _schema_ctx_types(b)
        for p in result.phases:
            if p.context_type in overlap:
                # Must be B's instance, not A's
                b_phase = next(bp for bp in b.phases if bp.context_type is p.context_type)
                assert p is b_phase


class TestSchemaCompilerRestriction:
    """Tests for - (restriction)."""

    @given(a=schema_compilers())
    def test_sub_identity(self, a: SchemaCompiler) -> None:
        """A - empty == A."""
        result = a - EMPTY_SCHEMA
        assert _schema_ctx_types(result) == _schema_ctx_types(a)

    @given(a=schema_compilers())
    def test_sub_annihilation(self, a: SchemaCompiler) -> None:
        """A - A == empty."""
        result = a - a
        assert len(result) == 0

    @given(pair=disjoint_schema_pair())
    def test_sub_roundtrip(self, pair: tuple[SchemaCompiler, SchemaCompiler]) -> None:
        """(A + B) - B == A when A & B disjoint."""
        a, b = pair
        result = (a + b) - b
        assert _schema_ctx_types(result) == _schema_ctx_types(a)


class TestSchemaCompilerIntersection:
    """Tests for & (intersection)."""

    @given(a=schema_compilers())
    def test_and_idempotent(self, a: SchemaCompiler) -> None:
        """A & A == A."""
        result = a & a
        assert len(result) == len(a)
        assert _schema_ctx_types(result) == _schema_ctx_types(a)

    @given(a=schema_compilers(), b=schema_compilers())
    def test_and_commutative(self, a: SchemaCompiler, b: SchemaCompiler) -> None:
        """A & B == B & A — same set of context_types."""
        left = a & b
        right = b & a
        assert _schema_ctx_types(left) == _schema_ctx_types(right)

    @given(a=schema_compilers(), b=schema_compilers(), c=schema_compilers())
    def test_and_associative(self, a: SchemaCompiler, b: SchemaCompiler, c: SchemaCompiler) -> None:
        """(A & B) & C == A & (B & C)."""
        left = (a & b) & c
        right = a & (b & c)
        assert _schema_ctx_types(left) == _schema_ctx_types(right)

    @given(a=schema_compilers())
    def test_and_zero(self, a: SchemaCompiler) -> None:
        """A & empty == empty."""
        result = a & EMPTY_SCHEMA
        assert len(result) == 0


class TestSchemaCompilerBounds:
    """Size bound properties."""

    @given(a=schema_compilers(), b=schema_compilers())
    def test_union_bound(self, a: SchemaCompiler, b: SchemaCompiler) -> None:
        """len(A + B) <= len(A) + len(B)."""
        result = a + b
        assert len(result) <= len(a) + len(b)

    @given(a=schema_compilers(), b=schema_compilers())
    def test_intersection_bound(self, a: SchemaCompiler, b: SchemaCompiler) -> None:
        """len(A & B) <= min(len(A), len(B))."""
        result = a & b
        assert len(result) <= min(len(a), len(b))


# ═══════════════════════════════════════════════════════════════════════════════
# TargetCompiler property tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestTargetCompilerAddition:
    """Tests for + (left-biased union)."""

    @given(a=target_compilers())
    def test_add_identity_right(self, a: TargetCompiler[object]) -> None:
        """A + empty == A."""
        result = a + _empty_target()
        assert _target_codec_types(result) == _target_codec_types(a)

    @given(a=target_compilers())
    def test_add_identity_left(self, a: TargetCompiler[object]) -> None:
        """empty + A == A."""
        result = _empty_target() + a
        assert _target_codec_types(result) == _target_codec_types(a)

    @given(a=target_compilers())
    def test_add_idempotent(self, a: TargetCompiler[object]) -> None:
        """A + A == A."""
        result = a + a
        assert len(result) == len(a)
        assert _target_codec_types(result) == _target_codec_types(a)

    @given(a=target_compilers(), b=target_compilers(), c=target_compilers())
    def test_add_associative(
        self,
        a: TargetCompiler[object],
        b: TargetCompiler[object],
        c: TargetCompiler[object],
    ) -> None:
        """(A + B) + C == A + (B + C) — same codec_types."""
        left = (a + b) + c
        right = a + (b + c)
        assert _target_codec_types(left) == _target_codec_types(right)


class TestTargetCompilerMerge:
    """Tests for | (right-biased merge)."""

    @given(a=target_compilers())
    def test_merge_identity_right(self, a: TargetCompiler[object]) -> None:
        """A | empty == A."""
        result = a | _empty_target()
        assert _target_codec_types(result) == _target_codec_types(a)

    @given(a=target_compilers())
    def test_merge_identity_left(self, a: TargetCompiler[object]) -> None:
        """empty | A == A."""
        result = _empty_target() | a
        assert _target_codec_types(result) == _target_codec_types(a)

    @given(a=target_compilers())
    def test_merge_idempotent(self, a: TargetCompiler[object]) -> None:
        """A | A == A."""
        result = a | a
        assert len(result) == len(a)
        assert _target_codec_types(result) == _target_codec_types(a)

    @given(a=target_compilers(), b=target_compilers(), c=target_compilers())
    def test_merge_associative(
        self,
        a: TargetCompiler[object],
        b: TargetCompiler[object],
        c: TargetCompiler[object],
    ) -> None:
        """(A | B) | C == A | (B | C) — same codec_types."""
        left = (a | b) | c
        right = a | (b | c)
        assert _target_codec_types(left) == _target_codec_types(right)


class TestTargetCompilerRestriction:
    """Tests for - (restriction)."""

    @given(a=target_compilers())
    def test_sub_identity(self, a: TargetCompiler[object]) -> None:
        """A - empty == A."""
        result = a - _empty_target()
        assert _target_codec_types(result) == _target_codec_types(a)

    @given(a=target_compilers())
    def test_sub_annihilation(self, a: TargetCompiler[object]) -> None:
        """A - A == empty."""
        result = a - a
        assert len(result) == 0

    @given(pair=disjoint_target_pair())
    def test_sub_roundtrip(
        self, pair: tuple[TargetCompiler[object], TargetCompiler[object]]
    ) -> None:
        """(A + B) - B == A when A & B disjoint."""
        a, b = pair
        result = (a + b) - b
        assert _target_codec_types(result) == _target_codec_types(a)


class TestTargetCompilerIntersection:
    """Tests for & (intersection)."""

    @given(a=target_compilers())
    def test_and_idempotent(self, a: TargetCompiler[object]) -> None:
        """A & A == A."""
        result = a & a
        assert len(result) == len(a)
        assert _target_codec_types(result) == _target_codec_types(a)

    @given(a=target_compilers(), b=target_compilers())
    def test_and_commutative(
        self, a: TargetCompiler[object], b: TargetCompiler[object]
    ) -> None:
        """A & B == B & A — same set of codec_types."""
        left = a & b
        right = b & a
        assert _target_codec_types(left) == _target_codec_types(right)

    @given(a=target_compilers(), b=target_compilers(), c=target_compilers())
    def test_and_associative(
        self,
        a: TargetCompiler[object],
        b: TargetCompiler[object],
        c: TargetCompiler[object],
    ) -> None:
        """(A & B) & C == A & (B & C)."""
        left = (a & b) & c
        right = a & (b & c)
        assert _target_codec_types(left) == _target_codec_types(right)

    @given(a=target_compilers())
    def test_and_zero(self, a: TargetCompiler[object]) -> None:
        """A & empty == empty."""
        result = a & _empty_target()
        assert len(result) == 0


class TestTargetCompilerBounds:
    """Size bound properties."""

    @given(a=target_compilers(), b=target_compilers())
    def test_union_bound(
        self, a: TargetCompiler[object], b: TargetCompiler[object]
    ) -> None:
        """len(A + B) <= len(A) + len(B)."""
        result = a + b
        assert len(result) <= len(a) + len(b)

    @given(a=target_compilers(), b=target_compilers())
    def test_intersection_bound(
        self, a: TargetCompiler[object], b: TargetCompiler[object]
    ) -> None:
        """len(A & B) <= min(len(A), len(B))."""
        result = a & b
        assert len(result) <= min(len(a), len(b))

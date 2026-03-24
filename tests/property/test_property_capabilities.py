# pyright: reportPrivateUsage=false
"""Property-based tests for universal schema capabilities' compile methods.

Tests compile_constraints, compile_openapi, and compile_argparse for ALL
universal capabilities to ensure they correctly modify their respective contexts.
Uses hypothesis for random value generation where applicable.
"""

from __future__ import annotations


import hypothesis.strategies as st
from hypothesis import given, settings

from emergent.wire.axis._capability import (
    ConstraintsContext,
    OpenAPIContext,
    ArgparseContext,
    ConstraintsCompilable,
    OpenAPICompilable,
    ArgparseCompilable,
)
from emergent.wire.axis.schema._universal import (
    Identity,
    Unique,
    Min,
    Max,
    ExclusiveMin,
    ExclusiveMax,
    MultipleOf,
    MinLen,
    MaxLen,
    Pattern,
    OneOf,
    Doc,
    Deprecated,
    ReadOnly,
    WriteOnly,
    Sensitive,
    Immutable,
    Nullable,
    Embedded,
    Computed,
    Alias,
)
from emergent.wire.compile._core import fold


# ═══════════════════════════════════════════════════════════════════════════════
# Context factories
# ═══════════════════════════════════════════════════════════════════════════════


def _constraints_ctx() -> ConstraintsContext:
    return ConstraintsContext(field_name="test", field_type=int)


def _openapi_ctx() -> OpenAPIContext:
    return OpenAPIContext(field_name="test", field_type=int, schema={})


def _argparse_ctx() -> ArgparseContext:
    return ArgparseContext(field_name="test", field_type=int)


# ═══════════════════════════════════════════════════════════════════════════════
# Constraints compilation
# ═══════════════════════════════════════════════════════════════════════════════


@given(v=st.integers(min_value=-10_000, max_value=10_000) | st.floats(allow_nan=False, allow_infinity=False))
@settings(max_examples=50)
def test_min_compile_constraints(v: int | float) -> None:
    ctx = _constraints_ctx()
    result = Min(v).compile_constraints(ctx)
    assert result.min_value == v


@given(v=st.integers(min_value=-10_000, max_value=10_000) | st.floats(allow_nan=False, allow_infinity=False))
@settings(max_examples=50)
def test_max_compile_constraints(v: int | float) -> None:
    ctx = _constraints_ctx()
    result = Max(v).compile_constraints(ctx)
    assert result.max_value == v


@given(v=st.integers(min_value=0, max_value=10_000))
@settings(max_examples=50)
def test_minlen_compile_constraints(v: int) -> None:
    ctx = _constraints_ctx()
    result = MinLen(v).compile_constraints(ctx)
    assert result.min_length == v


@given(v=st.integers(min_value=0, max_value=10_000))
@settings(max_examples=50)
def test_maxlen_compile_constraints(v: int) -> None:
    ctx = _constraints_ctx()
    result = MaxLen(v).compile_constraints(ctx)
    assert result.max_length == v


@given(p=st.from_regex(r"[a-zA-Z0-9.*+?^${}()|\\[\]]+", fullmatch=True))
@settings(max_examples=50)
def test_pattern_compile_constraints(p: str) -> None:
    ctx = _constraints_ctx()
    result = Pattern(p).compile_constraints(ctx)
    assert result.pattern == p


@given(vs=st.lists(st.one_of(st.text(max_size=20), st.integers(), st.floats(allow_nan=False, allow_infinity=False)), min_size=1, max_size=10))
@settings(max_examples=50)
def test_oneof_compile_constraints(vs: list[str | int | float]) -> None:
    ctx = _constraints_ctx()
    result = OneOf(*vs).compile_constraints(ctx)
    assert result.choices == tuple(vs)


def test_identity_compile_constraints() -> None:
    ctx = _constraints_ctx()
    result = Identity().compile_constraints(ctx)
    assert result.is_identity is True


def test_unique_compile_constraints() -> None:
    ctx = _constraints_ctx()
    result = Unique().compile_constraints(ctx)
    assert result.is_unique is True


@given(v=st.integers(min_value=-10_000, max_value=10_000) | st.floats(allow_nan=False, allow_infinity=False))
@settings(max_examples=50)
def test_exclusive_min_compile_constraints(v: int | float) -> None:
    ctx = _constraints_ctx()
    result = ExclusiveMin(v).compile_constraints(ctx)
    assert result.exclusive_min == v


@given(v=st.integers(min_value=-10_000, max_value=10_000) | st.floats(allow_nan=False, allow_infinity=False))
@settings(max_examples=50)
def test_exclusive_max_compile_constraints(v: int | float) -> None:
    ctx = _constraints_ctx()
    result = ExclusiveMax(v).compile_constraints(ctx)
    assert result.exclusive_max == v


@given(v=st.integers(min_value=1, max_value=1000) | st.floats(min_value=0.1, max_value=1000.0, allow_nan=False, allow_infinity=False))
@settings(max_examples=50)
def test_multiple_of_compile_constraints(v: int | float) -> None:
    ctx = _constraints_ctx()
    result = MultipleOf(v).compile_constraints(ctx)
    assert result.multiple_of == v


# ═══════════════════════════════════════════════════════════════════════════════
# Constraints immutability: original context unchanged after compile
# ═══════════════════════════════════════════════════════════════════════════════


@given(v=st.integers(min_value=0, max_value=100))
@settings(max_examples=20)
def test_constraints_immutability(v: int) -> None:
    """Original context must remain unchanged after compile (frozen dataclass)."""
    ctx = _constraints_ctx()
    _ = Min(v).compile_constraints(ctx)
    assert ctx.min_value is None
    assert ctx.max_value is None
    assert ctx.min_length is None
    assert ctx.max_length is None
    assert ctx.pattern is None
    assert ctx.choices is None
    assert ctx.is_identity is False
    assert ctx.is_unique is False


# ═══════════════════════════════════════════════════════════════════════════════
# OpenAPI compilation
# ═══════════════════════════════════════════════════════════════════════════════


@given(v=st.integers(min_value=-10_000, max_value=10_000) | st.floats(allow_nan=False, allow_infinity=False))
@settings(max_examples=50)
def test_min_compile_openapi(v: int | float) -> None:
    ctx = _openapi_ctx()
    result = Min(v).compile_openapi(ctx)
    assert result.schema["minimum"] == v


@given(v=st.integers(min_value=-10_000, max_value=10_000) | st.floats(allow_nan=False, allow_infinity=False))
@settings(max_examples=50)
def test_max_compile_openapi(v: int | float) -> None:
    ctx = _openapi_ctx()
    result = Max(v).compile_openapi(ctx)
    assert result.schema["maximum"] == v


@given(v=st.integers(min_value=0, max_value=10_000))
@settings(max_examples=50)
def test_minlen_compile_openapi(v: int) -> None:
    ctx = _openapi_ctx()
    result = MinLen(v).compile_openapi(ctx)
    assert result.schema["minLength"] == v


@given(v=st.integers(min_value=0, max_value=10_000))
@settings(max_examples=50)
def test_maxlen_compile_openapi(v: int) -> None:
    ctx = _openapi_ctx()
    result = MaxLen(v).compile_openapi(ctx)
    assert result.schema["maxLength"] == v


@given(p=st.from_regex(r"[a-zA-Z0-9.*+?^$]+", fullmatch=True))
@settings(max_examples=50)
def test_pattern_compile_openapi(p: str) -> None:
    ctx = _openapi_ctx()
    result = Pattern(p).compile_openapi(ctx)
    assert result.schema["pattern"] == p


@given(vs=st.lists(st.one_of(st.text(max_size=20), st.integers()), min_size=1, max_size=10))
@settings(max_examples=50)
def test_oneof_compile_openapi(vs: list[str | int]) -> None:
    ctx = _openapi_ctx()
    result = OneOf(*vs).compile_openapi(ctx)
    assert result.schema["enum"] == list(vs)


@given(t=st.text(min_size=1, max_size=200))
@settings(max_examples=50)
def test_doc_compile_openapi(t: str) -> None:
    ctx = _openapi_ctx()
    result = Doc(t).compile_openapi(ctx)
    assert result.schema["description"] == t


def test_deprecated_compile_openapi_no_reason() -> None:
    ctx = _openapi_ctx()
    result = Deprecated().compile_openapi(ctx)
    assert result.schema["deprecated"] is True


@given(reason=st.text(min_size=1, max_size=100))
@settings(max_examples=20)
def test_deprecated_compile_openapi_with_reason(reason: str) -> None:
    ctx = _openapi_ctx()
    result = Deprecated(reason).compile_openapi(ctx)
    assert result.schema["deprecated"] is True


def test_readonly_compile_openapi() -> None:
    ctx = _openapi_ctx()
    result = ReadOnly().compile_openapi(ctx)
    assert result.schema["readOnly"] is True


def test_writeonly_compile_openapi() -> None:
    ctx = _openapi_ctx()
    result = WriteOnly().compile_openapi(ctx)
    assert result.schema["writeOnly"] is True


def test_sensitive_compile_openapi() -> None:
    ctx = _openapi_ctx()
    result = Sensitive().compile_openapi(ctx)
    assert result.schema["writeOnly"] is True
    assert result.schema["format"] == "password"


def test_immutable_compile_openapi() -> None:
    ctx = _openapi_ctx()
    result = Immutable().compile_openapi(ctx)
    assert result.schema["x-immutable"] is True


def test_nullable_compile_openapi() -> None:
    ctx = _openapi_ctx()
    result = Nullable().compile_openapi(ctx)
    assert result.schema["nullable"] is True


def test_embedded_compile_openapi() -> None:
    ctx = _openapi_ctx()
    result = Embedded().compile_openapi(ctx)
    assert result.schema["x-embedded"] is True
    assert result.schema["x-format"] == "json"


def test_embedded_flatten_compile_openapi() -> None:
    ctx = _openapi_ctx()
    result = Embedded(format="flatten").compile_openapi(ctx)
    assert result.schema["x-embedded"] is True
    assert result.schema["x-format"] == "flatten"


def test_computed_compile_openapi() -> None:
    ctx = _openapi_ctx()
    result = Computed().compile_openapi(ctx)
    assert result.schema["readOnly"] is True
    assert result.schema["x-computed"] is True


@given(v=st.integers(min_value=-10_000, max_value=10_000) | st.floats(allow_nan=False, allow_infinity=False))
@settings(max_examples=50)
def test_exclusive_min_compile_openapi(v: int | float) -> None:
    ctx = _openapi_ctx()
    result = ExclusiveMin(v).compile_openapi(ctx)
    assert result.schema["exclusiveMinimum"] == v


@given(v=st.integers(min_value=-10_000, max_value=10_000) | st.floats(allow_nan=False, allow_infinity=False))
@settings(max_examples=50)
def test_exclusive_max_compile_openapi(v: int | float) -> None:
    ctx = _openapi_ctx()
    result = ExclusiveMax(v).compile_openapi(ctx)
    assert result.schema["exclusiveMaximum"] == v


@given(v=st.integers(min_value=1, max_value=1000) | st.floats(min_value=0.1, max_value=1000.0, allow_nan=False, allow_infinity=False))
@settings(max_examples=50)
def test_multiple_of_compile_openapi(v: int | float) -> None:
    ctx = _openapi_ctx()
    result = MultipleOf(v).compile_openapi(ctx)
    assert result.schema["multipleOf"] == v


@given(name=st.text(min_size=1, max_size=50, alphabet=st.characters(categories=("L", "N"))))
@settings(max_examples=20)
def test_alias_compile_openapi(name: str) -> None:
    ctx = _openapi_ctx()
    result = Alias(name).compile_openapi(ctx)
    assert result.schema["x-alias"] == name


# ═══════════════════════════════════════════════════════════════════════════════
# OpenAPI immutability: original schema unchanged
# ═══════════════════════════════════════════════════════════════════════════════


def test_openapi_immutability() -> None:
    """Original OpenAPI context schema must remain empty after compile."""
    ctx = _openapi_ctx()
    _ = Min(5).compile_openapi(ctx)
    assert ctx.schema == {}


# ═══════════════════════════════════════════════════════════════════════════════
# Argparse compilation
# ═══════════════════════════════════════════════════════════════════════════════


@given(t=st.text(min_size=1, max_size=200))
@settings(max_examples=50)
def test_doc_compile_argparse(t: str) -> None:
    ctx = _argparse_ctx()
    result = Doc(t).compile_argparse(ctx)
    assert result.kwargs["help"] == t


@given(vs=st.lists(st.one_of(st.text(max_size=20), st.integers()), min_size=1, max_size=10))
@settings(max_examples=50)
def test_oneof_compile_argparse(vs: list[str | int]) -> None:
    ctx = _argparse_ctx()
    result = OneOf(*vs).compile_argparse(ctx)
    assert result.kwargs["choices"] == list(vs)


@given(name=st.text(min_size=1, max_size=30, alphabet=st.characters(categories=("L", "N"))))
@settings(max_examples=20)
def test_alias_compile_argparse(name: str) -> None:
    ctx = _argparse_ctx()
    result = Alias(name).compile_argparse(ctx)
    assert result.arg_names == (f"--{name}",)


# ═══════════════════════════════════════════════════════════════════════════════
# Argparse immutability
# ═══════════════════════════════════════════════════════════════════════════════


def test_argparse_immutability() -> None:
    """Original argparse context kwargs must remain empty after compile."""
    ctx = _argparse_ctx()
    _ = Doc("hello").compile_argparse(ctx)
    assert dict(ctx.kwargs) == {}


# ═══════════════════════════════════════════════════════════════════════════════
# Composition: multiple capabilities via fold
# ═══════════════════════════════════════════════════════════════════════════════


@given(
    lo=st.integers(min_value=-1000, max_value=0),
    hi=st.integers(min_value=1, max_value=1000),
)
@settings(max_examples=50)
def test_min_max_compose_constraints(lo: int, hi: int) -> None:
    """Folding [Min(lo), Max(hi)] sets both min_value and max_value."""
    ctx = _constraints_ctx()
    caps = [Min(lo), Max(hi)]
    result = fold(caps, ctx, ConstraintsCompilable, "compile_constraints")
    assert result.min_value == lo
    assert result.max_value == hi


@given(
    lo=st.integers(min_value=1, max_value=50),
    hi=st.integers(min_value=51, max_value=200),
)
@settings(max_examples=50)
def test_minlen_maxlen_compose_constraints(lo: int, hi: int) -> None:
    """Folding [MinLen(lo), MaxLen(hi)] sets both min_length and max_length."""
    ctx = _constraints_ctx()
    caps = [MinLen(lo), MaxLen(hi)]
    result = fold(caps, ctx, ConstraintsCompilable, "compile_constraints")
    assert result.min_length == lo
    assert result.max_length == hi


def test_identity_unique_compose_constraints() -> None:
    """Folding [Identity, Unique] sets both flags."""
    ctx = _constraints_ctx()
    caps = [Identity(), Unique()]
    result = fold(caps, ctx, ConstraintsCompilable, "compile_constraints")
    assert result.is_identity is True
    assert result.is_unique is True


@given(
    lo=st.integers(min_value=-1000, max_value=0),
    hi=st.integers(min_value=1, max_value=1000),
)
@settings(max_examples=50)
def test_min_max_compose_openapi(lo: int, hi: int) -> None:
    """Folding [Min(lo), Max(hi)] adds both minimum and maximum to OpenAPI schema."""
    ctx = _openapi_ctx()
    caps = [Min(lo), Max(hi)]
    result = fold(caps, ctx, OpenAPICompilable, "compile_openapi")
    assert result.schema["minimum"] == lo
    assert result.schema["maximum"] == hi


# ═══════════════════════════════════════════════════════════════════════════════
# Order independence for commutative capabilities
# ═══════════════════════════════════════════════════════════════════════════════


@given(
    lo=st.integers(min_value=-1000, max_value=0),
    hi=st.integers(min_value=1, max_value=1000),
)
@settings(max_examples=50)
def test_min_max_order_independence_constraints(lo: int, hi: int) -> None:
    """Min + Max is commutative for constraints: order does not matter."""
    ctx = _constraints_ctx()
    result_a = fold([Min(lo), Max(hi)], ctx, ConstraintsCompilable, "compile_constraints")
    result_b = fold([Max(hi), Min(lo)], ctx, ConstraintsCompilable, "compile_constraints")
    assert result_a == result_b


@given(
    lo=st.integers(min_value=-1000, max_value=0),
    hi=st.integers(min_value=1, max_value=1000),
)
@settings(max_examples=50)
def test_min_max_order_independence_openapi(lo: int, hi: int) -> None:
    """Min + Max is commutative for OpenAPI: schema content identical regardless of order."""
    ctx = _openapi_ctx()
    result_a = fold([Min(lo), Max(hi)], ctx, OpenAPICompilable, "compile_openapi")
    result_b = fold([Max(hi), Min(lo)], ctx, OpenAPICompilable, "compile_openapi")
    assert result_a.schema == result_b.schema


@given(
    lo=st.integers(min_value=1, max_value=50),
    hi=st.integers(min_value=51, max_value=200),
)
@settings(max_examples=50)
def test_minlen_maxlen_order_independence(lo: int, hi: int) -> None:
    """MinLen + MaxLen is commutative for constraints."""
    ctx = _constraints_ctx()
    result_a = fold([MinLen(lo), MaxLen(hi)], ctx, ConstraintsCompilable, "compile_constraints")
    result_b = fold([MaxLen(hi), MinLen(lo)], ctx, ConstraintsCompilable, "compile_constraints")
    assert result_a == result_b


# ═══════════════════════════════════════════════════════════════════════════════
# OneOf: last one wins (overwrite semantics)
# ═══════════════════════════════════════════════════════════════════════════════


def test_oneof_last_wins_constraints() -> None:
    """When two OneOf are folded, the last one's values replace the first."""
    ctx = _constraints_ctx()
    caps = [OneOf("a", "b"), OneOf("x", "y", "z")]
    result = fold(caps, ctx, ConstraintsCompilable, "compile_constraints")
    assert result.choices == ("x", "y", "z")


def test_oneof_last_wins_openapi() -> None:
    """When two OneOf are folded, the last one's enum replaces the first."""
    ctx = _openapi_ctx()
    caps = [OneOf("a", "b"), OneOf("x", "y", "z")]
    result = fold(caps, ctx, OpenAPICompilable, "compile_openapi")
    assert result.schema["enum"] == ["x", "y", "z"]


# ═══════════════════════════════════════════════════════════════════════════════
# Mixed-axis fold: capabilities without matching protocol are skipped
# ═══════════════════════════════════════════════════════════════════════════════


def test_non_matching_capabilities_skipped_in_fold() -> None:
    """Capabilities that don't implement the target protocol are silently skipped."""
    ctx = _constraints_ctx()
    # Doc does not implement ConstraintsCompilable
    caps = [Min(0), Doc("ignored"), Max(100)]
    result = fold(caps, ctx, ConstraintsCompilable, "compile_constraints")
    assert result.min_value == 0
    assert result.max_value == 100


def test_non_matching_capabilities_skipped_openapi() -> None:
    """Capabilities that don't implement OpenAPICompilable are silently skipped."""
    ctx = _openapi_ctx()
    # Unique does not implement OpenAPICompilable
    caps = [Min(5), Unique(), Max(10)]
    result = fold(caps, ctx, OpenAPICompilable, "compile_openapi")
    assert result.schema["minimum"] == 5
    assert result.schema["maximum"] == 10
    assert "unique" not in result.schema


# ═══════════════════════════════════════════════════════════════════════════════
# Full composition: realistic field with many capabilities
# ═══════════════════════════════════════════════════════════════════════════════


def test_full_field_constraints_composition() -> None:
    """Realistic field: Identity + Unique + MinLen + MaxLen + Pattern."""
    ctx = ConstraintsContext(field_name="email", field_type=str)
    caps = [Identity(), Unique(), MinLen(5), MaxLen(255), Pattern(r"^.+@.+$")]
    result = fold(caps, ctx, ConstraintsCompilable, "compile_constraints")
    assert result.is_identity is True
    assert result.is_unique is True
    assert result.min_length == 5
    assert result.max_length == 255
    assert result.pattern == r"^.+@.+$"
    # field_name and field_type preserved
    assert result.field_name == "email"
    assert result.field_type is str


def test_full_field_openapi_composition() -> None:
    """Realistic field: Min + Max + Doc + Deprecated + ReadOnly."""
    ctx = OpenAPIContext(field_name="score", field_type=float, schema={})
    caps = [Min(0), Max(100), Doc("Player score"), Deprecated("Use rank instead"), ReadOnly()]
    result = fold(caps, ctx, OpenAPICompilable, "compile_openapi")
    assert result.schema["minimum"] == 0
    assert result.schema["maximum"] == 100
    assert result.schema["description"] == "Player score"
    assert result.schema["deprecated"] is True
    assert result.schema["readOnly"] is True
    # field_name preserved
    assert result.field_name == "score"


def test_full_field_argparse_composition() -> None:
    """Realistic field: Doc + OneOf + Alias."""
    ctx = ArgparseContext(field_name="mode", field_type=str)
    caps = [Doc("Operating mode"), OneOf("fast", "slow", "auto"), Alias("m")]
    result = fold(caps, ctx, ArgparseCompilable, "compile_argparse")
    assert result.kwargs["help"] == "Operating mode"
    assert result.kwargs["choices"] == ["fast", "slow", "auto"]
    assert result.arg_names == ("--m",)

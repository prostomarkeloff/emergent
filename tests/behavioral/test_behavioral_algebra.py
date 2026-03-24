"""Compiler algebra behavioral tests — verify algebraic operations produce correct compilation output.

Every assertion checks a VALUE or BEHAVIOR, never structure.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Annotated

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from emergent.wire.axis._capability import (
    ArgparseContext,
    ConstraintsContext,
    OpenAPICompilable,
    OpenAPIContext,
    StorageFieldContext,
    openapi_schema,
)
from emergent.wire.axis.schema._universal import (
    Identity,
    Max,
    MaxLen,
    Min,
    OneOf,
    UniversalCapability,
)
from emergent.wire.compile._core import Axes
from emergent.wire.compile._phase import (
    ARGPARSE_PHASE,
    CONSTRAINTS_PHASE,
    CONSTRAINTS_SCHEMA,
    FASTAPI_SCHEMA,
    OPENAPI_PHASE,
    STORAGE_FIELD_PHASE,
    STORAGE_SCHEMA,
    CompilationPhase,
    SchemaCompiler,
    compile_entity,
    compile_fields,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

axes = Axes.default()


@dataclass(frozen=True, slots=True)
class SampleEntity:
    id: Annotated[int, Identity]
    name: Annotated[str, MaxLen(100)]
    score: Annotated[int, Min(0), Max(100)]
    status: Annotated[str, OneOf("a", "b", "c")]


# ---------------------------------------------------------------------------
# 1. A + B compiles everything A and B can compile
# ---------------------------------------------------------------------------


def test_add_has_both_contexts():
    compiler = CONSTRAINTS_SCHEMA + STORAGE_SCHEMA
    ec = compiler.compile(SampleEntity, axes)
    for fc in ec:
        # Both phases produce results — access must not raise
        _ = fc[CONSTRAINTS_PHASE]
        _ = fc[STORAGE_FIELD_PHASE]


def test_add_constraints_values_correct():
    compiler = CONSTRAINTS_SCHEMA + STORAGE_SCHEMA
    ec = compiler.compile(SampleEntity, axes)
    for fc in ec:
        if fc.name == "name":
            assert fc[CONSTRAINTS_PHASE].max_length == 100
        if fc.name == "id":
            assert fc[CONSTRAINTS_PHASE].is_identity is True
            assert fc[STORAGE_FIELD_PHASE].is_identity is True
        if fc.name == "score":
            assert fc[CONSTRAINTS_PHASE].min_value == 0
            assert fc[CONSTRAINTS_PHASE].max_value == 100


def test_add_storage_values_correct():
    compiler = CONSTRAINTS_SCHEMA + STORAGE_SCHEMA
    ec = compiler.compile(SampleEntity, axes)
    for fc in ec:
        if fc.name == "id":
            assert fc[STORAGE_FIELD_PHASE].is_identity is True
        if fc.name == "name":
            assert fc[STORAGE_FIELD_PHASE].is_identity is False


def test_add_openapi_and_constraints():
    compiler = SchemaCompiler(phases=(OPENAPI_PHASE,)) + CONSTRAINTS_SCHEMA
    ec = compiler.compile(SampleEntity, axes)
    for fc in ec:
        if fc.name == "name":
            assert fc[OPENAPI_PHASE].schema["maxLength"] == 100
            assert fc[CONSTRAINTS_PHASE].max_length == 100


# ---------------------------------------------------------------------------
# 2. A | B overrides A's results with B's
# ---------------------------------------------------------------------------


def _custom_openapi_initial(name: str, field_type: type) -> OpenAPIContext:
    """Custom initial that injects a marker into the schema."""
    return OpenAPIContext(name, field_type, schema={"x-custom": True})


CUSTOM_OPENAPI_PHASE = CompilationPhase(
    OpenAPIContext, OpenAPICompilable, _custom_openapi_initial,
)


def test_override_replaces_phase():
    original = SchemaCompiler(phases=(OPENAPI_PHASE,))
    overridden = original | SchemaCompiler(phases=(CUSTOM_OPENAPI_PHASE,))
    ec = overridden.compile(SampleEntity, axes)
    for fc in ec:
        schema = fc[OPENAPI_PHASE].schema
        # The custom initial injects x-custom marker
        assert schema.get("x-custom") is True


def test_override_preserves_capability_effects():
    """Custom phase still gets capability folds applied (MaxLen, etc.)."""
    overridden = SchemaCompiler(phases=(OPENAPI_PHASE,)) | SchemaCompiler(
        phases=(CUSTOM_OPENAPI_PHASE,)
    )
    ec = overridden.compile(SampleEntity, axes)
    for fc in ec:
        if fc.name == "name":
            schema = fc[OPENAPI_PHASE].schema
            assert schema["maxLength"] == 100
            assert schema.get("x-custom") is True


def test_override_original_not_present():
    """After override, original initial is NOT used (no base type mapping)."""
    original = SchemaCompiler(phases=(OPENAPI_PHASE,))
    overridden = original | SchemaCompiler(phases=(CUSTOM_OPENAPI_PHASE,))
    ec_original = original.compile(SampleEntity, axes)
    ec_overridden = overridden.compile(SampleEntity, axes)

    for fc_orig, fc_over in zip(ec_original, ec_overridden):
        if fc_orig.name == "name":
            # Original has type-based initial schema (e.g., "type": "string")
            # Custom has x-custom marker
            assert "x-custom" not in fc_orig[OPENAPI_PHASE].schema
            assert fc_over[OPENAPI_PHASE].schema.get("x-custom") is True


# ---------------------------------------------------------------------------
# 3. A - B removes B's compilation
# ---------------------------------------------------------------------------


def test_subtract_removes_phase():
    compiler = FASTAPI_SCHEMA - OPENAPI_PHASE
    ec = compiler.compile(SampleEntity, axes)
    for fc in ec:
        with pytest.raises(KeyError):
            fc[OPENAPI_PHASE]


def test_subtract_keeps_remaining():
    """FASTAPI_SCHEMA = Pydantic + OpenAPI. Remove OpenAPI, Pydantic stays."""
    compiler = FASTAPI_SCHEMA - OPENAPI_PHASE
    ec = compiler.compile(SampleEntity, axes)
    from emergent.wire.compile._phase import PYDANTIC_PHASE
    for fc in ec:
        # Pydantic context must still exist
        pydantic_ctx = fc[PYDANTIC_PHASE]
        assert pydantic_ctx.field_name == fc.name


def test_subtract_by_compiler():
    compiler = (CONSTRAINTS_SCHEMA + STORAGE_SCHEMA) - STORAGE_SCHEMA
    ec = compiler.compile(SampleEntity, axes)
    for fc in ec:
        _ = fc[CONSTRAINTS_PHASE]  # must exist
        with pytest.raises(KeyError):
            fc[STORAGE_FIELD_PHASE]


def test_subtract_nonexistent_is_noop():
    compiler = CONSTRAINTS_SCHEMA - STORAGE_FIELD_PHASE
    ec = compiler.compile(SampleEntity, axes)
    for fc in ec:
        _ = fc[CONSTRAINTS_PHASE]  # still present


# ---------------------------------------------------------------------------
# 4. A & B keeps only shared phases
# ---------------------------------------------------------------------------


def test_intersection_keeps_shared():
    left = CONSTRAINTS_SCHEMA + SchemaCompiler(phases=(OPENAPI_PHASE,)) + STORAGE_SCHEMA
    right = CONSTRAINTS_SCHEMA + STORAGE_SCHEMA
    result = left & right
    ec = result.compile(SampleEntity, axes)
    for fc in ec:
        _ = fc[CONSTRAINTS_PHASE]
        _ = fc[STORAGE_FIELD_PHASE]
        with pytest.raises(KeyError):
            fc[OPENAPI_PHASE]


def test_intersection_values_preserved():
    left = CONSTRAINTS_SCHEMA + SchemaCompiler(phases=(OPENAPI_PHASE,)) + STORAGE_SCHEMA
    right = CONSTRAINTS_SCHEMA + STORAGE_SCHEMA
    result = left & right
    ec = result.compile(SampleEntity, axes)
    for fc in ec:
        if fc.name == "name":
            assert fc[CONSTRAINTS_PHASE].max_length == 100
        if fc.name == "id":
            assert fc[STORAGE_FIELD_PHASE].is_identity is True


def test_intersection_with_disjoint_is_empty():
    left = CONSTRAINTS_SCHEMA
    right = STORAGE_SCHEMA
    result = left & right
    assert len(result) == 0


# ---------------------------------------------------------------------------
# 5. Adding unrelated phases doesn't change existing results
# ---------------------------------------------------------------------------


def test_adding_phases_doesnt_change_constraints():
    ec_constraints = CONSTRAINTS_SCHEMA.compile(SampleEntity, axes)
    ec_combined = (CONSTRAINTS_SCHEMA + STORAGE_SCHEMA).compile(SampleEntity, axes)
    for fc_c, fc_comb in zip(ec_constraints, ec_combined):
        assert fc_c[CONSTRAINTS_PHASE].max_length == fc_comb[CONSTRAINTS_PHASE].max_length
        assert fc_c[CONSTRAINTS_PHASE].min_value == fc_comb[CONSTRAINTS_PHASE].min_value
        assert fc_c[CONSTRAINTS_PHASE].max_value == fc_comb[CONSTRAINTS_PHASE].max_value
        assert fc_c[CONSTRAINTS_PHASE].is_identity == fc_comb[CONSTRAINTS_PHASE].is_identity
        assert fc_c[CONSTRAINTS_PHASE].choices == fc_comb[CONSTRAINTS_PHASE].choices


def test_adding_openapi_doesnt_change_constraints():
    ec_constraints = CONSTRAINTS_SCHEMA.compile(SampleEntity, axes)
    ec_combined = (CONSTRAINTS_SCHEMA + SchemaCompiler(phases=(OPENAPI_PHASE,))).compile(
        SampleEntity, axes
    )
    for fc_c, fc_comb in zip(ec_constraints, ec_combined):
        c1 = fc_c[CONSTRAINTS_PHASE]
        c2 = fc_comb[CONSTRAINTS_PHASE]
        assert c1.max_length == c2.max_length
        assert c1.min_value == c2.min_value
        assert c1.max_value == c2.max_value
        assert c1.is_identity == c2.is_identity
        assert c1.is_unique == c2.is_unique


def test_adding_argparse_doesnt_change_storage():
    ec_storage = STORAGE_SCHEMA.compile(SampleEntity, axes)
    ec_combined = (STORAGE_SCHEMA + SchemaCompiler(phases=(ARGPARSE_PHASE,))).compile(
        SampleEntity, axes
    )
    for fc_s, fc_comb in zip(ec_storage, ec_combined):
        s1 = fc_s[STORAGE_FIELD_PHASE]
        s2 = fc_comb[STORAGE_FIELD_PHASE]
        assert s1.is_identity == s2.is_identity
        assert s1.to_storage == s2.to_storage
        assert s1.from_storage == s2.from_storage


# ---------------------------------------------------------------------------
# 6. Algebra laws
# ---------------------------------------------------------------------------


def test_idempotent_add():
    """A + A == A (same compilation result)."""
    ec_single = CONSTRAINTS_SCHEMA.compile(SampleEntity, axes)
    ec_double = (CONSTRAINTS_SCHEMA + CONSTRAINTS_SCHEMA).compile(SampleEntity, axes)
    for fc1, fc2 in zip(ec_single, ec_double):
        c1 = fc1[CONSTRAINTS_PHASE]
        c2 = fc2[CONSTRAINTS_PHASE]
        assert c1.max_length == c2.max_length
        assert c1.is_identity == c2.is_identity


def test_add_identity_element():
    """A + empty == A."""
    empty = SchemaCompiler(phases=())
    ec_a = CONSTRAINTS_SCHEMA.compile(SampleEntity, axes)
    ec_ae = (CONSTRAINTS_SCHEMA + empty).compile(SampleEntity, axes)
    for fc1, fc2 in zip(ec_a, ec_ae):
        assert fc1[CONSTRAINTS_PHASE].max_length == fc2[CONSTRAINTS_PHASE].max_length


def test_add_associative():
    """(A + B) + C produces same results as A + (B + C)."""
    a = CONSTRAINTS_SCHEMA
    b = STORAGE_SCHEMA
    c = SchemaCompiler(phases=(OPENAPI_PHASE,))
    ec_left = ((a + b) + c).compile(SampleEntity, axes)
    ec_right = (a + (b + c)).compile(SampleEntity, axes)
    for fc_l, fc_r in zip(ec_left, ec_right):
        assert fc_l[CONSTRAINTS_PHASE].max_length == fc_r[CONSTRAINTS_PHASE].max_length
        assert fc_l[STORAGE_FIELD_PHASE].is_identity == fc_r[STORAGE_FIELD_PHASE].is_identity
        assert fc_l[OPENAPI_PHASE].schema == fc_r[OPENAPI_PHASE].schema


# ---------------------------------------------------------------------------
# 7. Phase membership
# ---------------------------------------------------------------------------


def test_contains_by_phase():
    compiler = CONSTRAINTS_SCHEMA + STORAGE_SCHEMA
    assert CONSTRAINTS_PHASE in compiler
    assert STORAGE_FIELD_PHASE in compiler
    assert OPENAPI_PHASE not in compiler


def test_contains_by_type():
    compiler = CONSTRAINTS_SCHEMA + STORAGE_SCHEMA
    assert ConstraintsContext in compiler
    assert StorageFieldContext in compiler
    assert OpenAPIContext not in compiler


# ---------------------------------------------------------------------------
# 8. Subtraction + Add = restore
# ---------------------------------------------------------------------------


def test_subtract_then_add_restores():
    original = CONSTRAINTS_SCHEMA + STORAGE_SCHEMA
    removed = original - STORAGE_FIELD_PHASE
    restored = removed + STORAGE_SCHEMA
    ec = restored.compile(SampleEntity, axes)
    for fc in ec:
        if fc.name == "id":
            assert fc[CONSTRAINTS_PHASE].is_identity is True
            assert fc[STORAGE_FIELD_PHASE].is_identity is True


# ---------------------------------------------------------------------------
# 9. Override (|) on multi-phase compiler
# ---------------------------------------------------------------------------


def test_override_single_in_multi():
    """Override just OpenAPI in a multi-phase compiler."""
    multi = CONSTRAINTS_SCHEMA + SchemaCompiler(phases=(OPENAPI_PHASE,))
    overridden = multi | SchemaCompiler(phases=(CUSTOM_OPENAPI_PHASE,))
    ec = overridden.compile(SampleEntity, axes)
    for fc in ec:
        # Constraints unchanged
        if fc.name == "name":
            assert fc[CONSTRAINTS_PHASE].max_length == 100
        # OpenAPI uses custom initial
        schema = fc[OPENAPI_PHASE].schema
        assert schema.get("x-custom") is True


# ---------------------------------------------------------------------------
# 10. Compiler length
# ---------------------------------------------------------------------------


def test_compiler_length():
    assert len(CONSTRAINTS_SCHEMA) == 1
    assert len(CONSTRAINTS_SCHEMA + STORAGE_SCHEMA) == 2
    assert len(FASTAPI_SCHEMA) == 2  # Pydantic + OpenAPI
    assert len(FASTAPI_SCHEMA - OPENAPI_PHASE) == 1


# ---------------------------------------------------------------------------
# 11. Compiler bool
# ---------------------------------------------------------------------------


def test_compiler_bool():
    assert bool(CONSTRAINTS_SCHEMA)
    assert not bool(SchemaCompiler(phases=()))


# ---------------------------------------------------------------------------
# 12. Getitem lookup
# ---------------------------------------------------------------------------


def test_getitem_returns_phase():
    compiler = CONSTRAINTS_SCHEMA + STORAGE_SCHEMA
    phase = compiler[ConstraintsContext]
    assert phase.context_type is ConstraintsContext


def test_getitem_missing_raises():
    with pytest.raises(KeyError):
        CONSTRAINTS_SCHEMA[OpenAPIContext]


# ---------------------------------------------------------------------------
# 13. with_phase / without_phase
# ---------------------------------------------------------------------------


def test_with_phase_adds():
    compiler = CONSTRAINTS_SCHEMA.with_phase(STORAGE_FIELD_PHASE)
    ec = compiler.compile(SampleEntity, axes)
    for fc in ec:
        _ = fc[CONSTRAINTS_PHASE]
        _ = fc[STORAGE_FIELD_PHASE]


def test_with_phase_duplicate_raises():
    with pytest.raises(ValueError):
        CONSTRAINTS_SCHEMA.with_phase(CONSTRAINTS_PHASE)


def test_without_phase_removes():
    compiler = (CONSTRAINTS_SCHEMA + STORAGE_SCHEMA).without_phase(STORAGE_FIELD_PHASE)
    ec = compiler.compile(SampleEntity, axes)
    for fc in ec:
        _ = fc[CONSTRAINTS_PHASE]
        with pytest.raises(KeyError):
            fc[STORAGE_FIELD_PHASE]


# ---------------------------------------------------------------------------
# 14. Hypothesis: random compiler subsets produce deterministic results
# ---------------------------------------------------------------------------

PHASE_POOL = [CONSTRAINTS_PHASE, OPENAPI_PHASE, ARGPARSE_PHASE, STORAGE_FIELD_PHASE]


@given(
    phase_indices=st.lists(
        st.integers(min_value=0, max_value=len(PHASE_POOL) - 1),
        min_size=1,
        max_size=len(PHASE_POOL),
        unique=True,
    )
)
@settings(max_examples=30)
def test_hypothesis_random_compiler_deterministic(phase_indices: list[int]):
    phases = tuple(PHASE_POOL[i] for i in phase_indices)
    compiler = SchemaCompiler(phases=phases)
    ec1 = compiler.compile(SampleEntity, axes)
    ec2 = compiler.compile(SampleEntity, axes)
    for fc1, fc2 in zip(ec1, ec2):
        for phase in phases:
            ctx1 = fc1[phase]
            ctx2 = fc2[phase]
            assert ctx1 == ctx2


# ---------------------------------------------------------------------------
# 15. Hypothesis: every phase in compiler produces a value (no crash)
# ---------------------------------------------------------------------------


@given(
    phase_indices=st.lists(
        st.integers(min_value=0, max_value=len(PHASE_POOL) - 1),
        min_size=1,
        max_size=len(PHASE_POOL),
        unique=True,
    )
)
@settings(max_examples=30)
def test_hypothesis_every_phase_produces_value(phase_indices: list[int]):
    phases = tuple(PHASE_POOL[i] for i in phase_indices)
    compiler = SchemaCompiler(phases=phases)
    ec = compiler.compile(SampleEntity, axes)
    for fc in ec:
        for phase in phases:
            ctx = fc[phase]
            assert ctx is not None
            assert ctx.field_name == fc.name


# ---------------------------------------------------------------------------
# 16. Phase addition via CompilationPhase.__add__
# ---------------------------------------------------------------------------


def test_phase_add_creates_compiler():
    compiler = CONSTRAINTS_PHASE + STORAGE_FIELD_PHASE
    ec = compiler.compile(SampleEntity, axes)
    for fc in ec:
        if fc.name == "id":
            assert fc[CONSTRAINTS_PHASE].is_identity is True
            assert fc[STORAGE_FIELD_PHASE].is_identity is True


def test_phase_add_to_compiler():
    compiler = CONSTRAINTS_PHASE + STORAGE_SCHEMA
    assert len(compiler) == 2
    ec = compiler.compile(SampleEntity, axes)
    for fc in ec:
        _ = fc[CONSTRAINTS_PHASE]
        _ = fc[STORAGE_FIELD_PHASE]


# ---------------------------------------------------------------------------
# 17. Intersection preserves left versions
# ---------------------------------------------------------------------------


def test_intersection_left_biased():
    """A & B keeps A's versions of shared phases."""
    a = SchemaCompiler(phases=(CUSTOM_OPENAPI_PHASE,))
    b = SchemaCompiler(phases=(OPENAPI_PHASE,))
    result = a & b
    ec = result.compile(SampleEntity, axes)
    for fc in ec:
        # Should use CUSTOM initial (x-custom marker), not standard
        assert fc[OPENAPI_PHASE].schema.get("x-custom") is True

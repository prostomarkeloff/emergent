# pyright: reportPrivateUsage=false
"""Property-based tests for end-to-end compilation pipeline.

Tests compile_entity, EntityCompilation, SchemaCompiler.compile,
traced vs untraced equivalence, duplicate-phase rejection, and
empty-phase compilation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any, cast

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from emergent.wire.axis.schema._inspect import inspect_dataclass
from emergent.wire.axis.schema._universal import (
    Identity,
    Unique,
    Min,
    Max,
    MinLen,
    MaxLen,
    OneOf,
    Doc,
    Pattern,
)
from emergent.wire.compile._core import Axes
from emergent.wire.compile._phase import (
    CompilationPhase,
    EntityFold,
    FieldCompilation,
    EntityCompilation,
    compile_entity,
    SchemaCompiler,
    CONSTRAINTS_PHASE,
    OPENAPI_PHASE,
    ARGPARSE_PHASE,
    STORAGE_FIELD_PHASE,
    OPENAPI_SCHEMA_FOLD,
)


# ===============================================================================
# Test Entities -- fixed at module level, sampled by hypothesis
# ===============================================================================


@dataclass(frozen=True)
class P1:
    """Two plain fields."""

    x: int
    y: str


@dataclass(frozen=True)
class P2:
    """Identity + constrained fields."""

    id: Annotated[int, Identity]
    name: Annotated[str, MinLen(1), MaxLen(100)]
    score: Annotated[int, Min(0), Max(1000)]


@dataclass(frozen=True)
class P3:
    """OneOf enum constraint."""

    tag: Annotated[str, OneOf("a", "b", "c")]


@dataclass(frozen=True)
class P4:
    """Multiple constraints on multiple fields."""

    id: Annotated[int, Identity, Unique]
    email: Annotated[str, MaxLen(255), Unique]
    slug: Annotated[str, Pattern(r"^[a-z]+$")]


@dataclass(frozen=True)
class P5:
    """Doc metadata."""

    note: Annotated[str, Doc("a note")]


ALL_ENTITIES: list[type] = [P1, P2, P3, P4, P5]

# Phases that do not need pydantic
SAFE_PHASES: list[CompilationPhase[Any]] = [
    CONSTRAINTS_PHASE,
    OPENAPI_PHASE,
    ARGPARSE_PHASE,
    STORAGE_FIELD_PHASE,
]

entity_st = st.sampled_from(ALL_ENTITIES)


# ===============================================================================
# 1. compile_entity returns EntityCompilation with correct field count
# ===============================================================================


@given(entity=entity_st)
@settings(max_examples=50)
def test_compile_entity_field_count(entity: type) -> None:
    """compile_entity produces EntityCompilation with field count
    matching inspect_dataclass."""
    axes = Axes.default()
    ec = compile_entity(entity, axes, list(SAFE_PHASES))
    expected_count = len(inspect_dataclass(entity))
    assert isinstance(ec, EntityCompilation)
    assert len(ec) == expected_count


# ===============================================================================
# 2. EntityCompilation iteration yields FieldCompilation in order
# ===============================================================================


@given(entity=entity_st)
@settings(max_examples=50)
def test_ec_iteration_order(entity: type) -> None:
    """Iteration yields FieldCompilation for each field, in the order
    matching inspect_dataclass."""
    axes = Axes.default()
    ec = compile_entity(entity, axes, list(SAFE_PHASES))
    field_names_from_inspect = list(inspect_dataclass(entity).keys())
    field_names_from_ec = [fc.name for fc in ec]
    assert field_names_from_ec == field_names_from_inspect
    for fc in ec:
        assert isinstance(fc, FieldCompilation)


# ===============================================================================
# 3. EntityCompilation len matches field count
# ===============================================================================


@given(entity=entity_st)
@settings(max_examples=50)
def test_ec_len_matches_field_count(entity: type) -> None:
    """len(ec) matches the number of fields on the entity."""
    axes = Axes.default()
    ec = compile_entity(entity, axes, list(SAFE_PHASES))
    assert len(ec) == len(list(ec))
    assert len(ec) == len(ec.fields)


# ===============================================================================
# 4. has_entity is True when phase has EntityFold (OPENAPI_PHASE)
# ===============================================================================


def test_has_entity_true_for_openapi() -> None:
    """OPENAPI_PHASE has an EntityFold, so ec.has_entity(OPENAPI_SCHEMA_FOLD)
    must be True."""
    axes = Axes.default()
    ec = compile_entity(P1, axes, [OPENAPI_PHASE])
    fold = cast(EntityFold[object], OPENAPI_SCHEMA_FOLD)  # widen for has_entity signature
    assert ec.has_entity(fold) is True


# ===============================================================================
# 5. has_entity is False when phase has no EntityFold (ARGPARSE_PHASE)
# ===============================================================================


def test_has_entity_false_for_argparse() -> None:
    """ARGPARSE_PHASE has no EntityFold, so ec.has_entity(OPENAPI_SCHEMA_FOLD)
    must be False when only ARGPARSE_PHASE is compiled."""
    axes = Axes.default()
    ec = compile_entity(P1, axes, [ARGPARSE_PHASE])
    fold = cast(EntityFold[object], OPENAPI_SCHEMA_FOLD)  # widen for has_entity signature
    assert ec.has_entity(fold) is False


# ===============================================================================
# 6. SchemaCompiler.compile == compile_entity — same fields
# ===============================================================================


@given(entity=entity_st)
@settings(max_examples=50)
def test_schema_compiler_matches_compile_entity(entity: type) -> None:
    """SchemaCompiler.compile(cls, axes) produces same field-level
    results as compile_entity(cls, axes, list(compiler.phases))."""
    compiler = SchemaCompiler(phases=tuple(SAFE_PHASES))
    axes = Axes.default()

    ec_compiler = compiler.compile(entity, axes)
    ec_direct = compile_entity(entity, axes, list(compiler.phases))

    assert len(ec_compiler) == len(ec_direct)
    for fc_c, fc_d in zip(ec_compiler, ec_direct):
        assert fc_c.name == fc_d.name
        for phase in SAFE_PHASES:
            assert fc_c[phase] == fc_d[phase]


# ===============================================================================
# 7. Traced Axes compilation produces same field-level contexts as untraced
# ===============================================================================


@given(entity=entity_st)
@settings(max_examples=50)
def test_traced_matches_untraced(entity: type) -> None:
    """Traced compilation produces the same per-field, per-phase
    contexts as untraced compilation."""
    axes_default = Axes.default()
    axes_traced = Axes.traced()

    ec_default = compile_entity(entity, axes_default, list(SAFE_PHASES))
    ec_traced = compile_entity(entity, axes_traced, list(SAFE_PHASES))

    assert len(ec_default) == len(ec_traced)
    for fc_d, fc_t in zip(ec_default, ec_traced):
        assert fc_d.name == fc_t.name
        for phase in SAFE_PHASES:
            assert fc_d[phase] == fc_t[phase], (
                f"Traced differs for {entity.__name__}.{fc_d.name} "
                f"in {phase.context_type.__name__}"
            )


# ===============================================================================
# 8. Duplicate context_type in phases list raises ValueError
# ===============================================================================


def test_duplicate_context_type_raises() -> None:
    """Passing two phases with the same context_type raises ValueError."""
    axes = Axes.default()
    with pytest.raises(ValueError, match="Duplicate context_type"):
        compile_entity(P1, axes, [ARGPARSE_PHASE, ARGPARSE_PHASE])


# ===============================================================================
# 9. compile_entity with empty phases list — fields present, contexts empty
# ===============================================================================


@given(entity=entity_st)
@settings(max_examples=50)
def test_empty_phases_has_fields_no_contexts(entity: type) -> None:
    """compile_entity with empty phases list produces EntityCompilation
    with correct field count but no phase contexts available."""
    axes = Axes.default()
    ec = compile_entity(entity, axes, [])
    expected_count = len(inspect_dataclass(entity))
    assert len(ec) == expected_count
    for fc in ec:
        # No phases were compiled, so accessing any phase should raise KeyError
        with pytest.raises(KeyError):
            fc[ARGPARSE_PHASE]


# ===============================================================================
# 10. ec[phase] returns correct typed context for each field
# ===============================================================================


@given(entity=entity_st)
@settings(max_examples=50)
def test_ec_getitem_returns_correct_type(entity: type) -> None:
    """fc[phase] returns an instance of phase.context_type for each
    field and each phase."""
    axes = Axes.default()
    ec = compile_entity(entity, axes, list(SAFE_PHASES))
    for fc in ec:
        for phase in SAFE_PHASES:
            ctx = fc[phase]
            assert isinstance(ctx, phase.context_type), (
                f"Expected {phase.context_type.__name__}, "
                f"got {type(ctx).__name__} for "
                f"{entity.__name__}.{fc.name}"
            )

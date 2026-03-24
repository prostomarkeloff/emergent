# pyright: reportPrivateUsage=false
"""Cross-axis consistency tests — schema capabilities propagate to ALL compilation phases.

The core promise: a capability added to a field appears in ALL phase outputs that
handle it. For example, MaxLen(100) on a str field produces:
  - ConstraintsContext.max_length == 100
  - OpenAPIContext.schema has "maxLength": 100

Uses hypothesis for property-based testing across entities and constraint values.
"""

from dataclasses import dataclass
from typing import Annotated

import hypothesis.strategies as st
from hypothesis import given, settings

from emergent.wire.axis._capability import (
    ConstraintsContext,
    OpenAPIContext,
    StorageFieldContext,
)
from emergent.wire.axis.schema._universal import (
    Doc,
    Identity,
    Max,
    MaxLen,
    Min,
    MinLen,
    OneOf,
    Pattern,
    Unique,
)
from emergent.wire.compile._core import (
    Axes,
    extract_all_constraints,
)
from emergent.wire.compile._phase import (
    ARGPARSE_PHASE,
    CONSTRAINTS_PHASE,
    CompilationPhase,
    OPENAPI_PHASE,
    STORAGE_FIELD_PHASE,
    compile_fields,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Test Entities
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class E_Full:
    id: Annotated[int, Identity]
    name: Annotated[str, MinLen(1), MaxLen(100)]
    score: Annotated[int, Min(0), Max(1000)]
    email: Annotated[str, Unique, MaxLen(255)]


@dataclass
class E_Minimal:
    x: int
    y: str


@dataclass
class E_OneOf:
    status: Annotated[str, OneOf("active", "inactive")]


@dataclass
class E_Pattern:
    code: Annotated[str, Pattern(r"^[A-Z]{3}$")]


@dataclass
class E_Doc:
    note: Annotated[str, Doc("A note field")]


ALL_ENTITIES: list[type] = [E_Full, E_Minimal, E_OneOf, E_Pattern, E_Doc]

# Phases that do not require complex setup (avoiding PYDANTIC_PHASE)
SAFE_PHASES = [CONSTRAINTS_PHASE, OPENAPI_PHASE, ARGPARSE_PHASE, STORAGE_FIELD_PHASE]


# ═══════════════════════════════════════════════════════════════════════════════
# Strategies
# ═══════════════════════════════════════════════════════════════════════════════

entity_strategy = st.sampled_from(ALL_ENTITIES)
positive_int_strategy = st.integers(min_value=1, max_value=10_000)
non_negative_int_strategy = st.integers(min_value=0, max_value=10_000)
phase_subset_strategy = st.lists(
    st.sampled_from(SAFE_PHASES),
    min_size=1,
    max_size=len(SAFE_PHASES),
    unique_by=lambda p: p.context_type,
)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Field name consistency
# ═══════════════════════════════════════════════════════════════════════════════


@given(entity=entity_strategy, phases=phase_subset_strategy)
@settings(max_examples=50)
def test_field_name_consistency(entity: type, phases: list[CompilationPhase[object]]) -> None:
    """compile_fields with any phase subset returns the same field names."""
    axes = Axes.default()
    compiled = compile_fields(entity, axes, phases)
    expected_fields = axes.schema(entity)
    actual_names = {fc.name for fc in compiled}
    assert actual_names == set(expected_fields.keys())


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Field count consistency
# ═══════════════════════════════════════════════════════════════════════════════


@given(entity=entity_strategy, phases=phase_subset_strategy)
@settings(max_examples=50)
def test_field_count_consistency(entity: type, phases: list[CompilationPhase[object]]) -> None:
    """compile_fields with any phases returns the same number of FieldCompilations."""
    axes = Axes.default()
    compiled = compile_fields(entity, axes, phases)
    expected_fields = axes.schema(entity)
    assert len(compiled) == len(expected_fields)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Constraints match OpenAPI
# ═══════════════════════════════════════════════════════════════════════════════


@given(entity=entity_strategy)
@settings(max_examples=20)
def test_constraints_match_openapi(entity: type) -> None:
    """If ConstraintsContext has a value, OpenAPIContext.schema has the matching key."""
    axes = Axes.default()
    compiled = compile_fields(entity, axes, [CONSTRAINTS_PHASE, OPENAPI_PHASE])

    for fc in compiled:
        constraints: ConstraintsContext = fc[CONSTRAINTS_PHASE]
        openapi: OpenAPIContext = fc[OPENAPI_PHASE]

        if constraints.max_length is not None:
            assert openapi.schema.get("maxLength") == constraints.max_length, (
                f"{fc.name}: max_length={constraints.max_length} "
                f"but openapi maxLength={openapi.schema.get('maxLength')}"
            )

        if constraints.min_length is not None:
            assert openapi.schema.get("minLength") == constraints.min_length, (
                f"{fc.name}: min_length={constraints.min_length} "
                f"but openapi minLength={openapi.schema.get('minLength')}"
            )

        if constraints.min_value is not None:
            assert openapi.schema.get("minimum") == constraints.min_value, (
                f"{fc.name}: min_value={constraints.min_value} "
                f"but openapi minimum={openapi.schema.get('minimum')}"
            )

        if constraints.max_value is not None:
            assert openapi.schema.get("maximum") == constraints.max_value, (
                f"{fc.name}: max_value={constraints.max_value} "
                f"but openapi maximum={openapi.schema.get('maximum')}"
            )

        if constraints.pattern is not None:
            assert openapi.schema.get("pattern") == constraints.pattern, (
                f"{fc.name}: pattern={constraints.pattern} "
                f"but openapi pattern={openapi.schema.get('pattern')}"
            )

        if constraints.choices is not None:
            assert openapi.schema.get("enum") == list(constraints.choices), (
                f"{fc.name}: choices={constraints.choices} "
                f"but openapi enum={openapi.schema.get('enum')}"
            )


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Constraints match identity in StorageFieldContext
# ═══════════════════════════════════════════════════════════════════════════════


@given(entity=entity_strategy)
@settings(max_examples=20)
def test_constraints_match_identity(entity: type) -> None:
    """If ConstraintsContext.is_identity is True, StorageFieldContext.is_identity is True."""
    axes = Axes.default()
    compiled = compile_fields(entity, axes, [CONSTRAINTS_PHASE, STORAGE_FIELD_PHASE])

    for fc in compiled:
        constraints: ConstraintsContext = fc[CONSTRAINTS_PHASE]
        storage: StorageFieldContext = fc[STORAGE_FIELD_PHASE]

        if constraints.is_identity:
            assert storage.is_identity, (
                f"{fc.name}: constraints.is_identity=True "
                f"but storage.is_identity={storage.is_identity}"
            )

        if storage.is_identity:
            assert constraints.is_identity, (
                f"{fc.name}: storage.is_identity=True "
                f"but constraints.is_identity={constraints.is_identity}"
            )


# ═══════════════════════════════════════════════════════════════════════════════
# 5. extract_all_constraints matches manual fold
# ═══════════════════════════════════════════════════════════════════════════════


@given(entity=entity_strategy)
@settings(max_examples=20)
def test_extract_all_constraints_matches_manual_fold(entity: type) -> None:
    """extract_all_constraints result equals folding each field through CONSTRAINTS_PHASE manually."""
    axes = Axes.default()

    # Method 1: extract_all_constraints (the convenience function)
    all_constraints = extract_all_constraints(entity, axes)

    # Method 2: manual fold via compile_fields with CONSTRAINTS_PHASE
    compiled = compile_fields(entity, axes, [CONSTRAINTS_PHASE])

    assert len(all_constraints) == len(compiled)

    for fc in compiled:
        assert fc.name in all_constraints
        _base_type, field_constraints = all_constraints[fc.name]
        constraints_ctx: ConstraintsContext = fc[CONSTRAINTS_PHASE]

        # Verify each constraint field matches
        assert field_constraints.min_length == constraints_ctx.min_length, (
            f"{fc.name}: min_length mismatch"
        )
        assert field_constraints.max_length == constraints_ctx.max_length, (
            f"{fc.name}: max_length mismatch"
        )
        assert field_constraints.min_value == constraints_ctx.min_value, (
            f"{fc.name}: min_value mismatch"
        )
        assert field_constraints.max_value == constraints_ctx.max_value, (
            f"{fc.name}: max_value mismatch"
        )
        assert field_constraints.pattern == constraints_ctx.pattern, (
            f"{fc.name}: pattern mismatch"
        )
        assert field_constraints.choices == constraints_ctx.choices, (
            f"{fc.name}: choices mismatch"
        )
        assert field_constraints.is_identity == constraints_ctx.is_identity, (
            f"{fc.name}: is_identity mismatch"
        )
        assert field_constraints.is_unique == constraints_ctx.is_unique, (
            f"{fc.name}: is_unique mismatch"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 6. MaxLen propagates to both constraints and openapi
# ═══════════════════════════════════════════════════════════════════════════════


@given(v=positive_int_strategy)
@settings(max_examples=50)
def test_maxlen_cross_axis(v: int) -> None:
    """MaxLen(v) appears in constraints.max_length AND openapi.schema['maxLength']."""

    @dataclass
    class E_Dynamic:
        field: Annotated[str, MaxLen(v)]

    axes = Axes.default()
    compiled = compile_fields(E_Dynamic, axes, [CONSTRAINTS_PHASE, OPENAPI_PHASE])
    assert len(compiled) == 1

    fc = compiled[0]
    constraints: ConstraintsContext = fc[CONSTRAINTS_PHASE]
    openapi: OpenAPIContext = fc[OPENAPI_PHASE]

    assert constraints.max_length == v
    assert openapi.schema["maxLength"] == v


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Min propagates to both constraints and openapi
# ═══════════════════════════════════════════════════════════════════════════════


@given(v=st.integers(min_value=-10_000, max_value=10_000))
@settings(max_examples=50)
def test_min_cross_axis(v: int) -> None:
    """Min(v) appears in constraints.min_value AND openapi.schema['minimum']."""

    @dataclass
    class E_Dynamic:
        field: Annotated[int, Min(v)]

    axes = Axes.default()
    compiled = compile_fields(E_Dynamic, axes, [CONSTRAINTS_PHASE, OPENAPI_PHASE])
    assert len(compiled) == 1

    fc = compiled[0]
    constraints: ConstraintsContext = fc[CONSTRAINTS_PHASE]
    openapi: OpenAPIContext = fc[OPENAPI_PHASE]

    assert constraints.min_value == v
    assert openapi.schema["minimum"] == v


# ═══════════════════════════════════════════════════════════════════════════════
# 8. Identity propagates to constraints and storage
# ═══════════════════════════════════════════════════════════════════════════════


def test_identity_cross_axis() -> None:
    """Identity appears in constraints.is_identity AND storage.is_identity."""

    @dataclass
    class E_Id:
        pk: Annotated[int, Identity]

    axes = Axes.default()
    compiled = compile_fields(E_Id, axes, [CONSTRAINTS_PHASE, STORAGE_FIELD_PHASE])
    assert len(compiled) == 1

    fc = compiled[0]
    constraints: ConstraintsContext = fc[CONSTRAINTS_PHASE]
    storage: StorageFieldContext = fc[STORAGE_FIELD_PHASE]

    assert constraints.is_identity is True
    assert storage.is_identity is True


# ═══════════════════════════════════════════════════════════════════════════════
# 9. Unique propagates to constraints
# ═══════════════════════════════════════════════════════════════════════════════


def test_unique_cross_axis() -> None:
    """Unique appears in constraints.is_unique."""

    @dataclass
    class E_Uniq:
        email: Annotated[str, Unique]

    axes = Axes.default()
    compiled = compile_fields(E_Uniq, axes, [CONSTRAINTS_PHASE])
    assert len(compiled) == 1

    fc = compiled[0]
    constraints: ConstraintsContext = fc[CONSTRAINTS_PHASE]

    assert constraints.is_unique is True


# ═══════════════════════════════════════════════════════════════════════════════
# Additional cross-axis consistency: Doc propagates to OpenAPI description
# ═══════════════════════════════════════════════════════════════════════════════


def test_doc_cross_axis() -> None:
    """Doc('text') appears in openapi.schema['description']."""
    axes = Axes.default()
    compiled = compile_fields(E_Doc, axes, [OPENAPI_PHASE])
    assert len(compiled) == 1

    fc = compiled[0]
    openapi: OpenAPIContext = fc[OPENAPI_PHASE]

    assert openapi.schema.get("description") == "A note field"


# ═══════════════════════════════════════════════════════════════════════════════
# Additional: Pattern propagates to constraints and openapi
# ═══════════════════════════════════════════════════════════════════════════════


def test_pattern_cross_axis() -> None:
    """Pattern regex appears in constraints.pattern AND openapi.schema['pattern']."""
    axes = Axes.default()
    compiled = compile_fields(E_Pattern, axes, [CONSTRAINTS_PHASE, OPENAPI_PHASE])
    assert len(compiled) == 1

    fc = compiled[0]
    constraints: ConstraintsContext = fc[CONSTRAINTS_PHASE]
    openapi: OpenAPIContext = fc[OPENAPI_PHASE]

    assert constraints.pattern == r"^[A-Z]{3}$"
    assert openapi.schema["pattern"] == r"^[A-Z]{3}$"


# ═══════════════════════════════════════════════════════════════════════════════
# Additional: OneOf propagates to constraints and openapi
# ═══════════════════════════════════════════════════════════════════════════════


def test_oneof_cross_axis() -> None:
    """OneOf values appear in constraints.choices AND openapi.schema['enum']."""
    axes = Axes.default()
    compiled = compile_fields(E_OneOf, axes, [CONSTRAINTS_PHASE, OPENAPI_PHASE])
    assert len(compiled) == 1

    fc = compiled[0]
    constraints: ConstraintsContext = fc[CONSTRAINTS_PHASE]
    openapi: OpenAPIContext = fc[OPENAPI_PHASE]

    assert constraints.choices == ("active", "inactive")
    assert openapi.schema["enum"] == ["active", "inactive"]


# ═══════════════════════════════════════════════════════════════════════════════
# Additional: E_Full comprehensive cross-axis check
# ═══════════════════════════════════════════════════════════════════════════════


def test_e_full_all_phases() -> None:
    """E_Full compiled through all safe phases has consistent results across axes."""
    axes = Axes.default()
    compiled = compile_fields(E_Full, axes, SAFE_PHASES)

    field_map = {fc.name: fc for fc in compiled}

    # id: Identity
    id_constraints: ConstraintsContext = field_map["id"][CONSTRAINTS_PHASE]
    id_storage: StorageFieldContext = field_map["id"][STORAGE_FIELD_PHASE]
    assert id_constraints.is_identity is True
    assert id_storage.is_identity is True

    # name: MinLen(1), MaxLen(100)
    name_constraints: ConstraintsContext = field_map["name"][CONSTRAINTS_PHASE]
    name_openapi: OpenAPIContext = field_map["name"][OPENAPI_PHASE]
    assert name_constraints.min_length == 1
    assert name_constraints.max_length == 100
    assert name_openapi.schema["minLength"] == 1
    assert name_openapi.schema["maxLength"] == 100

    # score: Min(0), Max(1000)
    score_constraints: ConstraintsContext = field_map["score"][CONSTRAINTS_PHASE]
    score_openapi: OpenAPIContext = field_map["score"][OPENAPI_PHASE]
    assert score_constraints.min_value == 0
    assert score_constraints.max_value == 1000
    assert score_openapi.schema["minimum"] == 0
    assert score_openapi.schema["maximum"] == 1000

    # email: Unique, MaxLen(255)
    email_constraints: ConstraintsContext = field_map["email"][CONSTRAINTS_PHASE]
    email_openapi: OpenAPIContext = field_map["email"][OPENAPI_PHASE]
    assert email_constraints.is_unique is True
    assert email_constraints.max_length == 255
    assert email_openapi.schema["maxLength"] == 255


# ═══════════════════════════════════════════════════════════════════════════════
# Property: MinLen + MaxLen combined cross-axis
# ═══════════════════════════════════════════════════════════════════════════════


@given(
    min_val=st.integers(min_value=0, max_value=100),
    max_val=st.integers(min_value=101, max_value=1000),
)
@settings(max_examples=50)
def test_minlen_maxlen_combined_cross_axis(min_val: int, max_val: int) -> None:
    """MinLen and MaxLen together propagate consistently to constraints and openapi."""

    @dataclass
    class E_Dynamic:
        field: Annotated[str, MinLen(min_val), MaxLen(max_val)]

    axes = Axes.default()
    compiled = compile_fields(E_Dynamic, axes, [CONSTRAINTS_PHASE, OPENAPI_PHASE])
    fc = compiled[0]

    constraints: ConstraintsContext = fc[CONSTRAINTS_PHASE]
    openapi: OpenAPIContext = fc[OPENAPI_PHASE]

    assert constraints.min_length == min_val
    assert constraints.max_length == max_val
    assert openapi.schema["minLength"] == min_val
    assert openapi.schema["maxLength"] == max_val


# ═══════════════════════════════════════════════════════════════════════════════
# Property: Min + Max combined cross-axis
# ═══════════════════════════════════════════════════════════════════════════════


@given(
    min_val=st.integers(min_value=-10_000, max_value=0),
    max_val=st.integers(min_value=1, max_value=10_000),
)
@settings(max_examples=50)
def test_min_max_combined_cross_axis(min_val: int, max_val: int) -> None:
    """Min and Max together propagate consistently to constraints and openapi."""

    @dataclass
    class E_Dynamic:
        field: Annotated[int, Min(min_val), Max(max_val)]

    axes = Axes.default()
    compiled = compile_fields(E_Dynamic, axes, [CONSTRAINTS_PHASE, OPENAPI_PHASE])
    fc = compiled[0]

    constraints: ConstraintsContext = fc[CONSTRAINTS_PHASE]
    openapi: OpenAPIContext = fc[OPENAPI_PHASE]

    assert constraints.min_value == min_val
    assert constraints.max_value == max_val
    assert openapi.schema["minimum"] == min_val
    assert openapi.schema["maximum"] == max_val

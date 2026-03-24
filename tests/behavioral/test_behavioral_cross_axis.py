"""Cross-axis behavioral tests — verify information propagates correctly ACROSS compilation axes.

Every assertion checks a VALUE or BEHAVIOR, never structure.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from emergent.wire.axis._capability import (
    ArgparseContext,
    ConstraintsContext,
    OpenAPIContext,
    StorageFieldContext,
)
from emergent.wire.axis.schema._universal import (
    Identity,
    Max,
    MaxLen,
    Min,
    MinLen,
    OneOf,
    Pattern,
    Unique,
    UniversalCapability,
)
from emergent.wire.compile._core import Axes
from emergent.wire.compile._phase import (
    ARGPARSE_PHASE,
    CONSTRAINTS_PHASE,
    OPENAPI_PHASE,
    STORAGE_FIELD_PHASE,
    CompilationPhase,
    compile_entity,
    compile_fields,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

axes = Axes.default()


# ---------------------------------------------------------------------------
# 1. MaxLen(100) on str field — Constraints + OpenAPI agree
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MaxLenEntity:
    name: Annotated[str, MaxLen(100)]


def test_maxlen_constraints_value():
    fcs = compile_fields(MaxLenEntity, axes, [CONSTRAINTS_PHASE])
    ctx = fcs[0][CONSTRAINTS_PHASE]
    assert ctx.max_length == 100


def test_maxlen_openapi_value():
    fcs = compile_fields(MaxLenEntity, axes, [OPENAPI_PHASE])
    ctx = fcs[0][OPENAPI_PHASE]
    assert ctx.schema["maxLength"] == 100


def test_maxlen_constraints_and_openapi_agree():
    fcs = compile_fields(MaxLenEntity, axes, [CONSTRAINTS_PHASE, OPENAPI_PHASE])
    fc = fcs[0]
    constraints_val = fc[CONSTRAINTS_PHASE].max_length
    openapi_val = fc[OPENAPI_PHASE].schema["maxLength"]
    assert constraints_val == openapi_val == 100


def test_maxlen_not_in_argparse_kwargs():
    """MaxLen does NOT implement compile_argparse, so argparse kwargs stay empty."""
    fcs = compile_fields(MaxLenEntity, axes, [ARGPARSE_PHASE])
    ctx = fcs[0][ARGPARSE_PHASE]
    assert "maxLength" not in ctx.kwargs
    assert "max_length" not in ctx.kwargs


# ---------------------------------------------------------------------------
# 2. Min(0) on int field — Constraints + OpenAPI agree
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MinEntity:
    count: Annotated[int, Min(0)]


def test_min_constraints_value():
    fcs = compile_fields(MinEntity, axes, [CONSTRAINTS_PHASE])
    ctx = fcs[0][CONSTRAINTS_PHASE]
    assert ctx.min_value == 0


def test_min_openapi_value():
    fcs = compile_fields(MinEntity, axes, [OPENAPI_PHASE])
    ctx = fcs[0][OPENAPI_PHASE]
    assert ctx.schema["minimum"] == 0


def test_min_openapi_no_exclusive():
    fcs = compile_fields(MinEntity, axes, [OPENAPI_PHASE])
    ctx = fcs[0][OPENAPI_PHASE]
    assert ctx.schema.get("exclusiveMinimum") is None


def test_min_constraints_and_openapi_agree():
    fcs = compile_fields(MinEntity, axes, [CONSTRAINTS_PHASE, OPENAPI_PHASE])
    fc = fcs[0]
    assert fc[CONSTRAINTS_PHASE].min_value == fc[OPENAPI_PHASE].schema["minimum"] == 0


# ---------------------------------------------------------------------------
# 3. Identity on field — Constraints + StorageField agree
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class IdentityEntity:
    id: Annotated[int, Identity]
    name: str


def test_identity_constraints():
    fcs = compile_fields(IdentityEntity, axes, [CONSTRAINTS_PHASE])
    id_ctx = fcs[0][CONSTRAINTS_PHASE]
    name_ctx = fcs[1][CONSTRAINTS_PHASE]
    assert id_ctx.is_identity is True
    assert name_ctx.is_identity is False


def test_identity_storage_field():
    fcs = compile_fields(IdentityEntity, axes, [STORAGE_FIELD_PHASE])
    id_ctx = fcs[0][STORAGE_FIELD_PHASE]
    name_ctx = fcs[1][STORAGE_FIELD_PHASE]
    assert id_ctx.is_identity is True
    assert name_ctx.is_identity is False


def test_identity_constraints_and_storage_agree():
    fcs = compile_fields(
        IdentityEntity, axes, [CONSTRAINTS_PHASE, STORAGE_FIELD_PHASE]
    )
    fc = fcs[0]
    assert fc[CONSTRAINTS_PHASE].is_identity == fc[STORAGE_FIELD_PHASE].is_identity is True


# ---------------------------------------------------------------------------
# 4. OneOf("a","b","c") on str field — Constraints + OpenAPI agree
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OneOfEntity:
    status: Annotated[str, OneOf("a", "b", "c")]


def test_oneof_constraints_choices():
    fcs = compile_fields(OneOfEntity, axes, [CONSTRAINTS_PHASE])
    ctx = fcs[0][CONSTRAINTS_PHASE]
    assert ctx.choices == ("a", "b", "c")


def test_oneof_openapi_enum():
    fcs = compile_fields(OneOfEntity, axes, [OPENAPI_PHASE])
    ctx = fcs[0][OPENAPI_PHASE]
    assert ctx.schema["enum"] == ["a", "b", "c"]


def test_oneof_constraints_and_openapi_agree():
    fcs = compile_fields(OneOfEntity, axes, [CONSTRAINTS_PHASE, OPENAPI_PHASE])
    fc = fcs[0]
    choices_from_constraints = list(fc[CONSTRAINTS_PHASE].choices)  # type: ignore[arg-type]
    choices_from_openapi = fc[OPENAPI_PHASE].schema["enum"]
    assert choices_from_constraints == choices_from_openapi


def test_oneof_argparse_choices():
    """OneOf implements compile_argparse, so choices appear in argparse kwargs."""
    fcs = compile_fields(OneOfEntity, axes, [ARGPARSE_PHASE])
    ctx = fcs[0][ARGPARSE_PHASE]
    assert list(ctx.kwargs["choices"]) == ["a", "b", "c"]


# ---------------------------------------------------------------------------
# 5. Field names match across all phases
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MultiFieldEntity:
    id: Annotated[int, Identity]
    name: Annotated[str, MaxLen(50)]
    score: Annotated[int, Min(0), Max(100)]
    status: Annotated[str, OneOf("active", "inactive")]


def test_field_names_match_across_all_phases():
    phases = [CONSTRAINTS_PHASE, OPENAPI_PHASE, ARGPARSE_PHASE, STORAGE_FIELD_PHASE]
    fcs = compile_fields(MultiFieldEntity, axes, phases)
    for fc in fcs:
        assert fc[CONSTRAINTS_PHASE].field_name == fc.name
        assert fc[OPENAPI_PHASE].field_name == fc.name
        assert fc[ARGPARSE_PHASE].field_name == fc.name
        assert fc[STORAGE_FIELD_PHASE].field_name == fc.name


def test_field_names_are_correct():
    fcs = compile_fields(MultiFieldEntity, axes, [CONSTRAINTS_PHASE])
    names = [fc.name for fc in fcs]
    assert names == ["id", "name", "score", "status"]


# ---------------------------------------------------------------------------
# 6. Adding a capability changes ALL phases
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class WithoutMax:
    score: int


@dataclass(frozen=True, slots=True)
class WithMax:
    score: Annotated[int, Max(100)]


def test_adding_max_changes_constraints():
    fcs_without = compile_fields(WithoutMax, axes, [CONSTRAINTS_PHASE])
    fcs_with = compile_fields(WithMax, axes, [CONSTRAINTS_PHASE])
    assert fcs_without[0][CONSTRAINTS_PHASE].max_value is None
    assert fcs_with[0][CONSTRAINTS_PHASE].max_value == 100


def test_adding_max_changes_openapi():
    fcs_without = compile_fields(WithoutMax, axes, [OPENAPI_PHASE])
    fcs_with = compile_fields(WithMax, axes, [OPENAPI_PHASE])
    assert "maximum" not in fcs_without[0][OPENAPI_PHASE].schema
    assert fcs_with[0][OPENAPI_PHASE].schema["maximum"] == 100


def test_adding_max_changes_both_axes_consistently():
    fcs_with = compile_fields(WithMax, axes, [CONSTRAINTS_PHASE, OPENAPI_PHASE])
    fc = fcs_with[0]
    assert fc[CONSTRAINTS_PHASE].max_value == fc[OPENAPI_PHASE].schema["maximum"] == 100


def test_adding_min_changes_both_axes():
    @dataclass(frozen=True, slots=True)
    class WithMin:
        value: Annotated[int, Min(10)]

    @dataclass(frozen=True, slots=True)
    class WithoutMin:
        value: int

    fcs_with = compile_fields(WithMin, axes, [CONSTRAINTS_PHASE, OPENAPI_PHASE])
    fcs_without = compile_fields(WithoutMin, axes, [CONSTRAINTS_PHASE, OPENAPI_PHASE])
    assert fcs_with[0][CONSTRAINTS_PHASE].min_value == 10
    assert fcs_with[0][OPENAPI_PHASE].schema["minimum"] == 10
    assert fcs_without[0][CONSTRAINTS_PHASE].min_value is None
    assert "minimum" not in fcs_without[0][OPENAPI_PHASE].schema


# ---------------------------------------------------------------------------
# 7. Multiple capabilities compound across phases
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CompoundEntity:
    name: Annotated[str, MinLen(1), MaxLen(50), Pattern(r"^[a-z]+$")]


def test_compound_constraints_all_present():
    fcs = compile_fields(CompoundEntity, axes, [CONSTRAINTS_PHASE])
    ctx = fcs[0][CONSTRAINTS_PHASE]
    assert ctx.min_length == 1
    assert ctx.max_length == 50
    assert ctx.pattern == r"^[a-z]+$"


def test_compound_openapi_all_present():
    fcs = compile_fields(CompoundEntity, axes, [OPENAPI_PHASE])
    schema = fcs[0][OPENAPI_PHASE].schema
    assert schema["minLength"] == 1
    assert schema["maxLength"] == 50
    assert schema["pattern"] == r"^[a-z]+$"


# ---------------------------------------------------------------------------
# 8. Identity + Unique distinction preserved across phases
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DistinctCaps:
    pk: Annotated[int, Identity]
    email: Annotated[str, Unique]


def test_identity_vs_unique_constraints():
    fcs = compile_fields(DistinctCaps, axes, [CONSTRAINTS_PHASE])
    pk_ctx = fcs[0][CONSTRAINTS_PHASE]
    email_ctx = fcs[1][CONSTRAINTS_PHASE]
    assert pk_ctx.is_identity is True
    assert pk_ctx.is_unique is False
    assert email_ctx.is_identity is False
    assert email_ctx.is_unique is True


def test_identity_vs_unique_storage():
    fcs = compile_fields(DistinctCaps, axes, [STORAGE_FIELD_PHASE])
    pk_ctx = fcs[0][STORAGE_FIELD_PHASE]
    email_ctx = fcs[1][STORAGE_FIELD_PHASE]
    assert pk_ctx.is_identity is True
    assert email_ctx.is_identity is False


# ---------------------------------------------------------------------------
# 9. Hypothesis: random entity → Constraints.is_identity matches StorageField.is_identity
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _IdentityEntity:
    field: Annotated[int, Identity]


@dataclass(frozen=True, slots=True)
class _PlainEntity:
    field: int


@given(use_identity=st.booleans())
@settings(max_examples=50)
def test_hypothesis_identity_cross_axis(use_identity: bool):
    entity_cls = _IdentityEntity if use_identity else _PlainEntity
    fcs = compile_fields(entity_cls, axes, [CONSTRAINTS_PHASE, STORAGE_FIELD_PHASE])
    fc = fcs[0]
    constraints_identity = fc[CONSTRAINTS_PHASE].is_identity
    storage_identity = fc[STORAGE_FIELD_PHASE].is_identity
    assert constraints_identity == storage_identity


# ---------------------------------------------------------------------------
# 10. Hypothesis: random capabilities → constraints & openapi agree on min/max
# ---------------------------------------------------------------------------


@given(
    min_val=st.one_of(st.none(), st.integers(min_value=-1000, max_value=1000)),
    max_val=st.one_of(st.none(), st.integers(min_value=-1000, max_value=1000)),
    max_len=st.one_of(st.none(), st.integers(min_value=1, max_value=500)),
)
@settings(max_examples=50)
def test_hypothesis_numeric_caps_cross_axis(
    min_val: int | None,
    max_val: int | None,
    max_len: int | None,
):
    from emergent.wire.axis.schema._inspect import FieldInfo as SchemaFieldInfo, inspect_field

    caps: list[UniversalCapability] = []
    if min_val is not None:
        caps.append(Min(min_val))
    if max_val is not None:
        caps.append(Max(max_val))
    if max_len is not None:
        caps.append(MaxLen(max_len))

    # Build FieldInfo directly instead of dynamic dataclass to avoid get_type_hints issues
    field_info = SchemaFieldInfo(
        name="value",
        base_type=str,
        is_optional=False,
        capabilities=tuple(caps),
    )

    def _schema(cls: type) -> dict[str, SchemaFieldInfo]:
        return {"value": field_info}

    local_axes = Axes(schema=_schema)

    @dataclass(frozen=True, slots=True)
    class Placeholder:
        value: str

    fcs = compile_fields(Placeholder, local_axes, [CONSTRAINTS_PHASE, OPENAPI_PHASE])
    fc = fcs[0]
    c_ctx = fc[CONSTRAINTS_PHASE]
    o_ctx = fc[OPENAPI_PHASE]

    if min_val is not None:
        assert c_ctx.min_value == min_val
        assert o_ctx.schema["minimum"] == min_val
    else:
        assert c_ctx.min_value is None
        assert "minimum" not in o_ctx.schema

    if max_val is not None:
        assert c_ctx.max_value == max_val
        assert o_ctx.schema["maximum"] == max_val
    else:
        assert c_ctx.max_value is None
        assert "maximum" not in o_ctx.schema

    if max_len is not None:
        assert c_ctx.max_length == max_len
        assert o_ctx.schema["maxLength"] == max_len
    else:
        assert c_ctx.max_length is None
        assert "maxLength" not in o_ctx.schema


# ---------------------------------------------------------------------------
# 11. Entity-level compilation preserves field values
# ---------------------------------------------------------------------------


def test_entity_compilation_preserves_field_values():
    ec = compile_entity(MultiFieldEntity, axes, [CONSTRAINTS_PHASE, OPENAPI_PHASE])
    found_id = False
    found_name = False
    for fc in ec:
        if fc.name == "id":
            assert fc[CONSTRAINTS_PHASE].is_identity is True
            found_id = True
        if fc.name == "name":
            assert fc[CONSTRAINTS_PHASE].max_length == 50
            assert fc[OPENAPI_PHASE].schema["maxLength"] == 50
            found_name = True
    assert found_id
    assert found_name


# ---------------------------------------------------------------------------
# 12. compile_fields and compile_entity produce same field values
# ---------------------------------------------------------------------------


def test_compile_entity_matches_compile_fields():
    phases = [CONSTRAINTS_PHASE, OPENAPI_PHASE, STORAGE_FIELD_PHASE]
    fcs = compile_fields(MultiFieldEntity, axes, phases)
    ec = compile_entity(MultiFieldEntity, axes, phases)
    for fc_fields, fc_entity in zip(fcs, ec):
        assert fc_fields.name == fc_entity.name
        assert fc_fields[CONSTRAINTS_PHASE].max_length == fc_entity[CONSTRAINTS_PHASE].max_length
        assert fc_fields[CONSTRAINTS_PHASE].is_identity == fc_entity[CONSTRAINTS_PHASE].is_identity
        assert fc_fields[STORAGE_FIELD_PHASE].is_identity == fc_entity[STORAGE_FIELD_PHASE].is_identity


# ---------------------------------------------------------------------------
# 13. OneOf argparse choices match constraints choices
# ---------------------------------------------------------------------------


def test_oneof_argparse_and_constraints_agree():
    fcs = compile_fields(OneOfEntity, axes, [CONSTRAINTS_PHASE, ARGPARSE_PHASE])
    fc = fcs[0]
    constraints_choices = list(fc[CONSTRAINTS_PHASE].choices)  # type: ignore[arg-type]
    argparse_choices = list(fc[ARGPARSE_PHASE].kwargs["choices"])
    assert constraints_choices == argparse_choices


# ---------------------------------------------------------------------------
# 14. No capabilities → all contexts have default values
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BareBones:
    x: int
    y: str


def test_bare_bones_defaults():
    fcs = compile_fields(BareBones, axes, [CONSTRAINTS_PHASE, OPENAPI_PHASE, STORAGE_FIELD_PHASE])
    for fc in fcs:
        c = fc[CONSTRAINTS_PHASE]
        assert c.min_value is None
        assert c.max_value is None
        assert c.max_length is None
        assert c.choices is None
        assert c.is_identity is False
        assert c.is_unique is False
        s = fc[STORAGE_FIELD_PHASE]
        assert s.is_identity is False
        assert s.to_storage is None
        assert s.from_storage is None


# ---------------------------------------------------------------------------
# 15. Numeric range propagation — Min + Max combined
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RangeEntity:
    percentage: Annotated[int, Min(0), Max(100)]


def test_range_constraints_both_bounds():
    fcs = compile_fields(RangeEntity, axes, [CONSTRAINTS_PHASE])
    ctx = fcs[0][CONSTRAINTS_PHASE]
    assert ctx.min_value == 0
    assert ctx.max_value == 100


def test_range_openapi_both_bounds():
    fcs = compile_fields(RangeEntity, axes, [OPENAPI_PHASE])
    schema = fcs[0][OPENAPI_PHASE].schema
    assert schema["minimum"] == 0
    assert schema["maximum"] == 100


def test_range_cross_axis_agreement():
    fcs = compile_fields(RangeEntity, axes, [CONSTRAINTS_PHASE, OPENAPI_PHASE])
    fc = fcs[0]
    assert fc[CONSTRAINTS_PHASE].min_value == fc[OPENAPI_PHASE].schema["minimum"]
    assert fc[CONSTRAINTS_PHASE].max_value == fc[OPENAPI_PHASE].schema["maximum"]


# ---------------------------------------------------------------------------
# 16. Compilation is deterministic
# ---------------------------------------------------------------------------


def test_compilation_deterministic():
    for _ in range(5):
        fcs = compile_fields(MultiFieldEntity, axes, [CONSTRAINTS_PHASE, OPENAPI_PHASE])
        for fc in fcs:
            if fc.name == "score":
                assert fc[CONSTRAINTS_PHASE].min_value == 0
                assert fc[CONSTRAINTS_PHASE].max_value == 100
                assert fc[OPENAPI_PHASE].schema["minimum"] == 0
                assert fc[OPENAPI_PHASE].schema["maximum"] == 100

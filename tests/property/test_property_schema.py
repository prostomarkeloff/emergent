# pyright: reportPrivateUsage=false
"""Property-based tests for schema compilation.

Uses hypothesis with fixed test entities (sampled_from) to verify
compilation determinism, phase independence, constraint extraction,
capability completeness, inspect_dataclass correctness, compile_entity
structure, SchemaCompiler.compile, and get_schema_meta.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from typing import Annotated, Any, cast

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from emergent.wire.axis.schema._inspect import (
    inspect_dataclass,
    first_match,
    dataclass_inspector,
    FieldInfo,
)
from emergent.wire.axis.schema._universal import (
    Identity,
    Unique,
    Min,
    Max,
    MinLen,
    MaxLen,
    OneOf,
    Pattern,
    Doc,
    Deprecated,
    SchemaName,
    SchemaDoc,
    Abstract,
    schema_meta,
    get_schema_meta,
    get_schema_capability,
)
from emergent.wire.compile._core import (
    Axes,
    extract_constraints,
    extract_all_constraints,
)
from emergent.wire.compile._phase import (
    CompilationPhase,
    EntityFold,
    FieldCompilation,
    EntityCompilation,
    compile_fields,
    compile_entity,
    SchemaCompiler,
    CONSTRAINTS_PHASE,
    OPENAPI_PHASE,
    ARGPARSE_PHASE,
    STORAGE_FIELD_PHASE,
    PYDANTIC_MODEL_FOLD,
    OPENAPI_SCHEMA_FOLD,
    FASTAPI_SCHEMA,
)


# ===============================================================================
# Test Entities -- fixed at module level, sampled by hypothesis
# ===============================================================================


@dataclass(frozen=True)
class E1:
    """Identity + plain field."""

    id: Annotated[int, Identity]
    name: str


@dataclass(frozen=True)
class E2:
    """Identity + length + numeric constraints."""

    id: Annotated[int, Identity]
    name: Annotated[str, MinLen(1), MaxLen(100)]
    score: Annotated[int, Min(0), Max(1000)]


@dataclass(frozen=True)
class E3:
    """OneOf enum constraint."""

    tag: Annotated[str, OneOf("a", "b", "c")]


@dataclass(frozen=True)
class E4:
    """Identity + Unique on multiple fields."""

    id: Annotated[int, Identity, Unique]
    email: Annotated[str, MaxLen(255), Unique]


@dataclass(frozen=True)
class E5:
    """Doc + Deprecated metadata."""

    note: Annotated[str, Doc("a note"), Deprecated("use memo")]


@dataclass(frozen=True)
class E6:
    """Pattern constraint."""

    slug: Annotated[str, Pattern(r"^[a-z0-9-]+$")]


@dataclass(frozen=True)
class E7:
    """No Annotated fields -- plain dataclass."""

    x: int
    y: str


@dataclass(frozen=True)
class E8:
    """Multiple constraints on one field."""

    code: Annotated[str, MinLen(2), MaxLen(10), Pattern(r"^[A-Z]+$"), Unique]


@dataclass(frozen=True)
class WithOptional:
    """Entity with optional fields."""

    x: int
    y: str | None = None


@dataclass(frozen=True)
class WithDefaults:
    """Entity with default values."""

    a: int = 0
    b: str = "default"


@dataclass(frozen=True)
class WithMixed:
    """Entity mixing identity, optional, and defaults."""

    id: Annotated[int, Identity]
    name: str
    bio: str | None = None
    score: Annotated[int, Min(0)] = 100


@schema_meta(SchemaName("custom_users"), SchemaDoc("A user entity"))
@dataclass(frozen=True)
class WithSchemaMeta:
    """Entity with schema-level metadata."""

    id: Annotated[int, Identity]
    name: str


@schema_meta(Abstract())
@dataclass(frozen=True)
class WithAbstract:
    """Abstract entity (not directly instantiated)."""

    id: Annotated[int, Identity]


@dataclass(frozen=True)
class EmptyEntity:
    """Empty entity -- no fields at all."""

    pass


ALL_ENTITIES: list[type] = [
    E1, E2, E3, E4, E5, E6, E7, E8,
    WithOptional, WithDefaults, WithMixed,
]

# Phases that don't need pydantic
SAFE_PHASES: list[CompilationPhase[Any]] = [
    CONSTRAINTS_PHASE,
    OPENAPI_PHASE,
    ARGPARSE_PHASE,
    STORAGE_FIELD_PHASE,
]

# All non-empty subsets of safe phases (for phase-combo testing)
PHASE_COMBOS: list[tuple[CompilationPhase[Any], ...]] = []
for _i in range(1, len(SAFE_PHASES) + 1):
    for _combo in combinations(SAFE_PHASES, _i):
        PHASE_COMBOS.append(_combo)


# ===============================================================================
# Strategies
# ===============================================================================

entity_st = st.sampled_from(ALL_ENTITIES)
phase_combo_st = st.sampled_from(PHASE_COMBOS)


# ===============================================================================
# Helper
# ===============================================================================


def _fields_of(cls: type) -> dict[str, FieldInfo]:
    return inspect_dataclass(cls)


# ===============================================================================
# Property 1: Compilation determinism
# ===============================================================================


@given(entity=entity_st, phases=phase_combo_st)
@settings(max_examples=200)
def test_compilation_determinism(
    entity: type,
    phases: tuple[CompilationPhase[object], ...],
) -> None:
    """Same input always produces same output."""
    axes = Axes.default()
    result_a = compile_fields(entity, axes, list(phases))
    result_b = compile_fields(entity, axes, list(phases))

    assert len(result_a) == len(result_b)
    for fc_a, fc_b in zip(result_a, result_b):
        assert fc_a.name == fc_b.name
        for phase in phases:
            ctx_a = fc_a[phase]
            ctx_b = fc_b[phase]
            assert ctx_a == ctx_b, (
                f"Non-deterministic compilation for {entity.__name__}.{fc_a.name} "
                f"in phase {phase.context_type.__name__}: {ctx_a} != {ctx_b}"
            )


# ===============================================================================
# Property 2: Phase independence
# ===============================================================================


@given(entity=entity_st, phases=phase_combo_st)
@settings(max_examples=200)
def test_phase_independence(
    entity: type,
    phases: tuple[CompilationPhase[object], ...],
) -> None:
    """Compiling with [A, B] gives same A-context as compiling with [A] alone.

    Each phase fold is independent -- co-resident phases must not interfere.
    """
    axes = Axes.default()
    combined = compile_fields(entity, axes, list(phases))

    for phase in phases:
        solo = compile_fields(entity, axes, [phase])

        assert len(combined) == len(solo)
        for fc_combined, fc_solo in zip(combined, solo):
            ctx_combined = fc_combined[phase]
            ctx_solo = fc_solo[phase]
            assert ctx_combined == ctx_solo, (
                f"Phase interference for {entity.__name__}.{fc_combined.name}: "
                f"combined {phase.context_type.__name__} = {ctx_combined} "
                f"vs solo = {ctx_solo}"
            )


# ===============================================================================
# Properties 3-7: Constraint extraction (parametrized, not hypothesis)
# ===============================================================================


class TestConstraintExtractionIdentity:
    """Property 3: Identity capability sets is_identity."""

    def test_e1_id_is_identity(self) -> None:
        constraints = extract_constraints(_fields_of(E1)["id"])
        assert constraints.is_identity is True

    def test_e2_id_is_identity(self) -> None:
        constraints = extract_constraints(_fields_of(E2)["id"])
        assert constraints.is_identity is True

    def test_e4_id_is_identity(self) -> None:
        constraints = extract_constraints(_fields_of(E4)["id"])
        assert constraints.is_identity is True

    def test_plain_field_not_identity(self) -> None:
        constraints = extract_constraints(_fields_of(E1)["name"])
        assert constraints.is_identity is False

    def test_e7_no_identity(self) -> None:
        for _name, info in _fields_of(E7).items():
            constraints = extract_constraints(info)
            assert constraints.is_identity is False

    def test_with_mixed_id_is_identity(self) -> None:
        constraints = extract_constraints(_fields_of(WithMixed)["id"])
        assert constraints.is_identity is True

    def test_with_mixed_name_not_identity(self) -> None:
        constraints = extract_constraints(_fields_of(WithMixed)["name"])
        assert constraints.is_identity is False


class TestConstraintExtractionUnique:
    """Property 4: Unique capability sets is_unique."""

    def test_e4_id_is_unique(self) -> None:
        constraints = extract_constraints(_fields_of(E4)["id"])
        assert constraints.is_unique is True

    def test_e4_email_is_unique(self) -> None:
        constraints = extract_constraints(_fields_of(E4)["email"])
        assert constraints.is_unique is True

    def test_e8_code_is_unique(self) -> None:
        constraints = extract_constraints(_fields_of(E8)["code"])
        assert constraints.is_unique is True

    def test_e1_name_not_unique(self) -> None:
        constraints = extract_constraints(_fields_of(E1)["name"])
        assert constraints.is_unique is False


class TestConstraintExtractionMinMax:
    """Property 5: Min/Max capabilities set min_value/max_value."""

    def test_e2_score_min(self) -> None:
        constraints = extract_constraints(_fields_of(E2)["score"])
        assert constraints.min_value == 0

    def test_e2_score_max(self) -> None:
        constraints = extract_constraints(_fields_of(E2)["score"])
        assert constraints.max_value == 1000

    def test_plain_field_no_minmax(self) -> None:
        constraints = extract_constraints(_fields_of(E1)["name"])
        assert constraints.min_value is None
        assert constraints.max_value is None

    def test_with_mixed_score_min(self) -> None:
        constraints = extract_constraints(_fields_of(WithMixed)["score"])
        assert constraints.min_value == 0


class TestConstraintExtractionLength:
    """Property 6: MinLen/MaxLen capabilities set min_length/max_length."""

    def test_e2_name_min_length(self) -> None:
        constraints = extract_constraints(_fields_of(E2)["name"])
        assert constraints.min_length == 1

    def test_e2_name_max_length(self) -> None:
        constraints = extract_constraints(_fields_of(E2)["name"])
        assert constraints.max_length == 100

    def test_e4_email_max_length(self) -> None:
        constraints = extract_constraints(_fields_of(E4)["email"])
        assert constraints.max_length == 255

    def test_e8_code_min_length(self) -> None:
        constraints = extract_constraints(_fields_of(E8)["code"])
        assert constraints.min_length == 2

    def test_e8_code_max_length(self) -> None:
        constraints = extract_constraints(_fields_of(E8)["code"])
        assert constraints.max_length == 10


class TestConstraintExtractionOneOf:
    """Property 7: OneOf capability sets choices."""

    def test_e3_tag_choices(self) -> None:
        constraints = extract_constraints(_fields_of(E3)["tag"])
        assert constraints.choices == ("a", "b", "c")

    def test_plain_field_no_choices(self) -> None:
        constraints = extract_constraints(_fields_of(E1)["name"])
        assert constraints.choices is None


class TestConstraintExtractionPattern:
    """Pattern capability sets pattern."""

    def test_e6_slug_pattern(self) -> None:
        constraints = extract_constraints(_fields_of(E6)["slug"])
        assert constraints.pattern == r"^[a-z0-9-]+$"

    def test_e8_code_pattern(self) -> None:
        constraints = extract_constraints(_fields_of(E8)["code"])
        assert constraints.pattern == r"^[A-Z]+$"

    def test_plain_field_no_pattern(self) -> None:
        constraints = extract_constraints(_fields_of(E7)["x"])
        assert constraints.pattern is None


# ===============================================================================
# Property 8: FieldInfo completeness -- Annotated capabilities appear in inspect
# ===============================================================================


class TestFieldInfoCompleteness:
    """All Annotated capabilities from the entity appear in FieldInfo.capabilities."""

    def test_e1_id_has_identity(self) -> None:
        info = _fields_of(E1)["id"]
        assert info.has(Identity)

    def test_e2_name_has_minlen_maxlen(self) -> None:
        info = _fields_of(E2)["name"]
        assert info.has(MinLen)
        assert info.has(MaxLen)

    def test_e2_score_has_min_max(self) -> None:
        info = _fields_of(E2)["score"]
        assert info.has(Min)
        assert info.has(Max)

    def test_e3_tag_has_oneof(self) -> None:
        info = _fields_of(E3)["tag"]
        assert info.has(OneOf)

    def test_e4_id_has_identity_and_unique(self) -> None:
        info = _fields_of(E4)["id"]
        assert info.has(Identity)
        assert info.has(Unique)

    def test_e4_email_has_maxlen_and_unique(self) -> None:
        info = _fields_of(E4)["email"]
        assert info.has(MaxLen)
        assert info.has(Unique)

    def test_e5_note_has_doc_and_deprecated(self) -> None:
        info = _fields_of(E5)["note"]
        assert info.has(Doc)
        assert info.has(Deprecated)

    def test_e6_slug_has_pattern(self) -> None:
        info = _fields_of(E6)["slug"]
        assert info.has(Pattern)

    def test_e7_plain_no_capabilities(self) -> None:
        for name, info in _fields_of(E7).items():
            assert len(info.capabilities) == 0, (
                f"E7.{name} should have no capabilities, got {info.capabilities}"
            )

    def test_e8_code_has_all_four(self) -> None:
        info = _fields_of(E8)["code"]
        assert info.has(MinLen)
        assert info.has(MaxLen)
        assert info.has(Pattern)
        assert info.has(Unique)


# ===============================================================================
# Property 9: Empty entity compiles without error, contexts are default
# ===============================================================================


class TestEmptyEntityCompilation:
    """An entity with no Annotated fields compiles cleanly."""

    @pytest.mark.parametrize("phase", SAFE_PHASES, ids=lambda p: p.context_type.__name__)
    def test_e7_compiles_without_error(
        self, phase: CompilationPhase[object]
    ) -> None:
        axes = Axes.default()
        result = compile_fields(E7, axes, [phase])
        assert len(result) == 2  # x, y

    def test_e7_constraints_are_default(self) -> None:
        axes = Axes.default()
        all_constraints = extract_all_constraints(E7, axes)
        for _name, (_base_type, constraints) in all_constraints.items():
            assert constraints.is_identity is False
            assert constraints.is_unique is False
            assert constraints.min_length is None
            assert constraints.max_length is None
            assert constraints.min_value is None
            assert constraints.max_value is None
            assert constraints.pattern is None
            assert constraints.choices is None

    def test_e7_all_phases_at_once(self) -> None:
        axes = Axes.default()
        result = compile_fields(E7, axes, list(SAFE_PHASES))
        assert len(result) == 2
        for fc in result:
            # Every phase should be accessible
            for phase in SAFE_PHASES:
                ctx = fc[phase]
                assert ctx is not None


# ===============================================================================
# NEW Property 10: inspect_dataclass returns all fields
# ===============================================================================


class TestInspectDataclassFieldCount:
    """inspect_dataclass returns correct number of fields for each entity."""

    def test_e1_field_count(self) -> None:
        assert len(inspect_dataclass(E1)) == 2

    def test_e2_field_count(self) -> None:
        assert len(inspect_dataclass(E2)) == 3

    def test_e3_field_count(self) -> None:
        assert len(inspect_dataclass(E3)) == 1

    def test_e4_field_count(self) -> None:
        assert len(inspect_dataclass(E4)) == 2

    def test_e5_field_count(self) -> None:
        assert len(inspect_dataclass(E5)) == 1

    def test_e6_field_count(self) -> None:
        assert len(inspect_dataclass(E6)) == 1

    def test_e7_field_count(self) -> None:
        assert len(inspect_dataclass(E7)) == 2

    def test_e8_field_count(self) -> None:
        assert len(inspect_dataclass(E8)) == 1

    def test_with_optional_field_count(self) -> None:
        assert len(inspect_dataclass(WithOptional)) == 2

    def test_with_defaults_field_count(self) -> None:
        assert len(inspect_dataclass(WithDefaults)) == 2

    def test_with_mixed_field_count(self) -> None:
        assert len(inspect_dataclass(WithMixed)) == 4

    def test_empty_entity_field_count(self) -> None:
        assert len(inspect_dataclass(EmptyEntity)) == 0

    @given(entity=entity_st)
    @settings(max_examples=50)
    def test_field_count_matches_dataclass_fields(self, entity: type) -> None:
        """inspect_dataclass returns same count as dataclasses.fields."""
        import dataclasses as dc

        expected = len(dc.fields(entity))
        actual = len(inspect_dataclass(entity))
        assert actual == expected, (
            f"{entity.__name__}: expected {expected} fields, got {actual}"
        )


# ===============================================================================
# NEW Property 11: FieldInfo.name matches field name
# ===============================================================================


class TestFieldInfoName:
    """Each returned FieldInfo has correct name matching its key."""

    def test_e1_field_names(self) -> None:
        fields = _fields_of(E1)
        for name, info in fields.items():
            assert info.name == name

    def test_e2_field_names(self) -> None:
        fields = _fields_of(E2)
        assert set(fields.keys()) == {"id", "name", "score"}
        for name, info in fields.items():
            assert info.name == name

    def test_with_optional_field_names(self) -> None:
        fields = _fields_of(WithOptional)
        assert set(fields.keys()) == {"x", "y"}
        for name, info in fields.items():
            assert info.name == name

    def test_with_defaults_field_names(self) -> None:
        fields = _fields_of(WithDefaults)
        assert set(fields.keys()) == {"a", "b"}
        for name, info in fields.items():
            assert info.name == name

    @given(entity=entity_st)
    @settings(max_examples=50)
    def test_all_field_names_match_keys(self, entity: type) -> None:
        """FieldInfo.name matches dict key for all entities."""
        fields = _fields_of(entity)
        for key, info in fields.items():
            assert info.name == key


# ===============================================================================
# NEW Property 12: FieldInfo.base_type correct
# ===============================================================================


class TestFieldInfoBaseType:
    """Each FieldInfo has correct base type (int, str, etc.)."""

    def test_e1_types(self) -> None:
        fields = _fields_of(E1)
        assert fields["id"].base_type is int
        assert fields["name"].base_type is str

    def test_e2_types(self) -> None:
        fields = _fields_of(E2)
        assert fields["id"].base_type is int
        assert fields["name"].base_type is str
        assert fields["score"].base_type is int

    def test_e3_tag_type(self) -> None:
        fields = _fields_of(E3)
        assert fields["tag"].base_type is str

    def test_e7_types(self) -> None:
        fields = _fields_of(E7)
        assert fields["x"].base_type is int
        assert fields["y"].base_type is str

    def test_with_optional_types(self) -> None:
        fields = _fields_of(WithOptional)
        assert fields["x"].base_type is int
        # Optional unwraps: str | None -> base_type is str
        assert fields["y"].base_type is str

    def test_with_defaults_types(self) -> None:
        fields = _fields_of(WithDefaults)
        assert fields["a"].base_type is int
        assert fields["b"].base_type is str

    def test_with_mixed_types(self) -> None:
        fields = _fields_of(WithMixed)
        assert fields["id"].base_type is int
        assert fields["name"].base_type is str
        assert fields["bio"].base_type is str
        assert fields["score"].base_type is int


# ===============================================================================
# NEW Property 13: FieldInfo.is_optional
# ===============================================================================


class TestFieldInfoIsOptional:
    """Fields with Optional[X] or X | None have is_optional=True."""

    def test_e1_no_optional_fields(self) -> None:
        fields = _fields_of(E1)
        assert fields["id"].is_optional is False
        assert fields["name"].is_optional is False

    def test_with_optional_x_not_optional(self) -> None:
        fields = _fields_of(WithOptional)
        assert fields["x"].is_optional is False

    def test_with_optional_y_is_optional(self) -> None:
        fields = _fields_of(WithOptional)
        assert fields["y"].is_optional is True

    def test_with_mixed_bio_is_optional(self) -> None:
        fields = _fields_of(WithMixed)
        assert fields["bio"].is_optional is True

    def test_with_mixed_non_optional_fields(self) -> None:
        fields = _fields_of(WithMixed)
        assert fields["id"].is_optional is False
        assert fields["name"].is_optional is False

    def test_e7_no_optional_fields(self) -> None:
        fields = _fields_of(E7)
        assert fields["x"].is_optional is False
        assert fields["y"].is_optional is False


# ===============================================================================
# NEW Property 14: FieldInfo.has_default
# ===============================================================================


class TestFieldInfoHasDefault:
    """Fields with default values have has_default=True."""

    def test_e1_no_defaults(self) -> None:
        fields = _fields_of(E1)
        assert fields["id"].has_default is False
        assert fields["name"].has_default is False

    def test_with_optional_defaults(self) -> None:
        fields = _fields_of(WithOptional)
        assert fields["x"].has_default is False
        assert fields["y"].has_default is True

    def test_with_defaults_all_have_defaults(self) -> None:
        fields = _fields_of(WithDefaults)
        assert fields["a"].has_default is True
        assert fields["b"].has_default is True

    def test_with_mixed_defaults(self) -> None:
        fields = _fields_of(WithMixed)
        assert fields["id"].has_default is False
        assert fields["name"].has_default is False
        assert fields["bio"].has_default is True
        assert fields["score"].has_default is True


# ===============================================================================
# NEW Property 15: inspect_dataclass on non-dataclass raises TypeError
# ===============================================================================


class TestInspectNonDataclass:
    """inspect_dataclass on non-dataclass raises TypeError."""

    def test_plain_class_raises(self) -> None:
        class NotADataclass:
            x: int = 0

        with pytest.raises(TypeError):
            inspect_dataclass(NotADataclass)

    def test_builtin_type_raises(self) -> None:
        with pytest.raises(TypeError):
            inspect_dataclass(int)

    def test_str_raises(self) -> None:
        with pytest.raises(TypeError):
            inspect_dataclass(str)

    def test_none_type_raises(self) -> None:
        with pytest.raises(TypeError):
            inspect_dataclass(type(None))


# ===============================================================================
# NEW Property 16: compile_entity returns EntityCompilation
# ===============================================================================


class TestCompileEntityStructure:
    """compile_entity returns EntityCompilation with correct structure."""

    def test_returns_entity_compilation(self) -> None:
        axes = Axes.default()
        ec = compile_entity(E1, axes, [OPENAPI_PHASE])
        assert isinstance(ec, EntityCompilation)

    def test_entity_compilation_has_fields(self) -> None:
        axes = Axes.default()
        ec = compile_entity(E1, axes, [OPENAPI_PHASE])
        assert len(ec.fields) == 2  # id, name

    def test_entity_compilation_field_types(self) -> None:
        axes = Axes.default()
        ec = compile_entity(E2, axes, [OPENAPI_PHASE])
        for fc in ec.fields:
            assert isinstance(fc, FieldCompilation)

    def test_entity_compilation_with_multiple_phases(self) -> None:
        axes = Axes.default()
        ec = compile_entity(E2, axes, [OPENAPI_PHASE, ARGPARSE_PHASE, STORAGE_FIELD_PHASE])
        assert len(ec.fields) == 3  # id, name, score
        for fc in ec:
            # All phases accessible
            _ = fc[OPENAPI_PHASE]
            _ = fc[ARGPARSE_PHASE]
            _ = fc[STORAGE_FIELD_PHASE]


# ===============================================================================
# NEW Property 17: EntityCompilation iteration yields FieldCompilation
# ===============================================================================


class TestEntityCompilationIteration:
    """Iterating EntityCompilation yields FieldCompilation objects."""

    def test_iteration_yields_field_compilations(self) -> None:
        axes = Axes.default()
        ec = compile_entity(E1, axes, [OPENAPI_PHASE])
        for fc in ec:
            assert isinstance(fc, FieldCompilation)

    def test_len_matches_field_count(self) -> None:
        axes = Axes.default()
        ec = compile_entity(E2, axes, [OPENAPI_PHASE])
        assert len(ec) == 3

    def test_iteration_count_matches_len(self) -> None:
        axes = Axes.default()
        ec = compile_entity(E4, axes, [OPENAPI_PHASE])
        count = sum(1 for _ in ec)
        assert count == len(ec)

    def test_empty_entity_compilation(self) -> None:
        axes = Axes.default()
        ec = compile_entity(EmptyEntity, axes, [OPENAPI_PHASE])
        assert len(ec) == 0
        assert list(ec) == []

    @given(entity=entity_st)
    @settings(max_examples=50)
    def test_len_matches_dataclass_field_count(self, entity: type) -> None:
        """EntityCompilation len matches dataclass field count."""
        import dataclasses as dc

        axes = Axes.default()
        ec = compile_entity(entity, axes, [OPENAPI_PHASE])
        assert len(ec) == len(dc.fields(entity))


# ===============================================================================
# NEW Property 18: EntityCompilation entity contexts (has_entity)
# ===============================================================================


class TestEntityCompilationEntityContexts:
    """EntityCompilation has entity-level contexts when phases have EntityFold."""

    def test_openapi_phase_has_entity_context(self) -> None:
        """OPENAPI_PHASE has OPENAPI_SCHEMA_FOLD, so ec.has_entity is True."""
        axes = Axes.default()
        ec = compile_entity(E1, axes, [OPENAPI_PHASE])
        assert ec.has_entity(cast(EntityFold[object], OPENAPI_SCHEMA_FOLD)) is True

    def test_argparse_phase_no_entity_context(self) -> None:
        """ARGPARSE_PHASE has no entity fold."""
        axes = Axes.default()
        ec = compile_entity(E1, axes, [ARGPARSE_PHASE])
        assert ec.has_entity(cast(EntityFold[object], OPENAPI_SCHEMA_FOLD)) is False
        assert ec.has_entity(cast(EntityFold[object], PYDANTIC_MODEL_FOLD)) is False

    def test_get_entity_context_returns_value(self) -> None:
        axes = Axes.default()
        ec = compile_entity(E1, axes, [OPENAPI_PHASE])
        ctx = ec[OPENAPI_SCHEMA_FOLD]
        assert ctx is not None

    def test_get_nonexistent_entity_context_raises(self) -> None:
        axes = Axes.default()
        ec = compile_entity(E1, axes, [ARGPARSE_PHASE])
        with pytest.raises(KeyError):
            _ = ec[OPENAPI_SCHEMA_FOLD]

    def test_get_optional_entity_context_none(self) -> None:
        axes = Axes.default()
        ec = compile_entity(E1, axes, [ARGPARSE_PHASE])
        assert ec.get(OPENAPI_SCHEMA_FOLD) is None

    def test_schema_meta_reflected_in_entity_context(self) -> None:
        """@schema_meta capabilities are folded into entity context."""
        axes = Axes.default()
        ec = compile_entity(WithSchemaMeta, axes, [OPENAPI_PHASE])
        ctx = ec[OPENAPI_SCHEMA_FOLD]
        # SchemaName("custom_users") should set title in OpenAPI schema context
        assert ctx.schema.get("title") == "custom_users"


# ===============================================================================
# NEW Property 19: SchemaCompiler.compile
# ===============================================================================


class TestSchemaCompilerCompile:
    """SchemaCompiler.compile returns EntityCompilation."""

    def test_fastapi_schema_compile(self) -> None:
        axes = Axes.default()
        ec = FASTAPI_SCHEMA.compile(E1, axes)
        assert isinstance(ec, EntityCompilation)
        assert len(ec) == 2

    def test_fastapi_schema_has_openapi_entity_context(self) -> None:
        axes = Axes.default()
        ec = FASTAPI_SCHEMA.compile(E1, axes)
        assert ec.has_entity(cast(EntityFold[object], OPENAPI_SCHEMA_FOLD)) is True

    def test_custom_schema_compiler(self) -> None:
        compiler = SchemaCompiler(phases=(OPENAPI_PHASE, ARGPARSE_PHASE))
        axes = Axes.default()
        ec = compiler.compile(E2, axes)
        assert len(ec) == 3
        for fc in ec:
            _ = fc[OPENAPI_PHASE]
            _ = fc[ARGPARSE_PHASE]

    def test_single_phase_compiler(self) -> None:
        compiler = SchemaCompiler(phases=(STORAGE_FIELD_PHASE,))
        axes = Axes.default()
        ec = compiler.compile(E7, axes)
        assert len(ec) == 2

    def test_schema_compiler_algebra_add(self) -> None:
        """SchemaCompiler + preserves phases (left-biased union)."""
        a = SchemaCompiler(phases=(OPENAPI_PHASE,))
        b = SchemaCompiler(phases=(ARGPARSE_PHASE,))
        combined = a + b
        assert len(combined) == 2

    def test_schema_compiler_algebra_sub(self) -> None:
        """SchemaCompiler - removes phases."""
        compiler = SchemaCompiler(phases=(OPENAPI_PHASE, ARGPARSE_PHASE))
        reduced = compiler - ARGPARSE_PHASE
        assert len(reduced) == 1

    def test_schema_compiler_contains(self) -> None:
        assert OPENAPI_PHASE in FASTAPI_SCHEMA
        assert ARGPARSE_PHASE not in FASTAPI_SCHEMA


# ===============================================================================
# NEW Property 20: Phase ordering doesn't affect results
# ===============================================================================


class TestPhaseOrdering:
    """compile_fields with [A, B] vs [B, A] gives same contexts for each phase."""

    def test_two_phase_order_invariance(self) -> None:
        axes = Axes.default()
        ab = compile_fields(E2, axes, [OPENAPI_PHASE, ARGPARSE_PHASE])
        ba = compile_fields(E2, axes, [ARGPARSE_PHASE, OPENAPI_PHASE])

        assert len(ab) == len(ba)
        for fc_ab, fc_ba in zip(ab, ba):
            assert fc_ab.name == fc_ba.name
            assert fc_ab[OPENAPI_PHASE] == fc_ba[OPENAPI_PHASE]
            assert fc_ab[ARGPARSE_PHASE] == fc_ba[ARGPARSE_PHASE]

    def test_three_phase_order_invariance(self) -> None:
        axes = Axes.default()
        phases_a: list[CompilationPhase[Any]] = [OPENAPI_PHASE, ARGPARSE_PHASE, STORAGE_FIELD_PHASE]
        phases_b: list[CompilationPhase[Any]] = [STORAGE_FIELD_PHASE, OPENAPI_PHASE, ARGPARSE_PHASE]
        phases_c: list[CompilationPhase[Any]] = [ARGPARSE_PHASE, STORAGE_FIELD_PHASE, OPENAPI_PHASE]

        result_a = compile_fields(E4, axes, phases_a)
        result_b = compile_fields(E4, axes, phases_b)
        result_c = compile_fields(E4, axes, phases_c)

        for fc_a, fc_b, fc_c in zip(result_a, result_b, result_c):
            for phase in phases_a:
                assert fc_a[phase] == fc_b[phase] == fc_c[phase], (
                    f"Order-dependent result for {fc_a.name} in {phase.context_type.__name__}"
                )

    @given(entity=entity_st)
    @settings(max_examples=50)
    def test_all_safe_phases_order_invariance(self, entity: type) -> None:
        """All safe phases produce same result regardless of order."""
        axes = Axes.default()
        forward = compile_fields(entity, axes, list(SAFE_PHASES))
        backward = compile_fields(entity, axes, list(reversed(SAFE_PHASES)))
        assert len(forward) == len(backward)
        for fc_f, fc_b in zip(forward, backward):
            assert fc_f.name == fc_b.name
            for phase in SAFE_PHASES:
                assert fc_f[phase] == fc_b[phase]


# ===============================================================================
# NEW Property 21: get_schema_meta
# ===============================================================================


class TestGetSchemaMeta:
    """get_schema_meta returns schema-level capabilities."""

    def test_no_meta_returns_empty(self) -> None:
        assert get_schema_meta(E1) == ()

    def test_with_schema_meta_returns_capabilities(self) -> None:
        meta = get_schema_meta(WithSchemaMeta)
        assert len(meta) == 2

    def test_with_schema_meta_has_schema_name(self) -> None:
        cap = get_schema_capability(WithSchemaMeta, SchemaName)
        assert cap is not None
        assert isinstance(cap, SchemaName)
        assert cap.value == "custom_users"

    def test_with_schema_meta_has_schema_doc(self) -> None:
        cap = get_schema_capability(WithSchemaMeta, SchemaDoc)
        assert cap is not None
        assert isinstance(cap, SchemaDoc)
        assert cap.description == "A user entity"

    def test_with_abstract(self) -> None:
        meta = get_schema_meta(WithAbstract)
        assert len(meta) == 1
        assert isinstance(meta[0], Abstract)

    def test_no_meta_capability_returns_none(self) -> None:
        assert get_schema_capability(E1, SchemaName) is None

    def test_e7_no_meta(self) -> None:
        assert get_schema_meta(E7) == ()


# ===============================================================================
# NEW Property 22: first_match combinator
# ===============================================================================


class TestFirstMatch:
    """first_match composes inspectors correctly."""

    def test_single_inspector(self) -> None:
        inspector = first_match(dataclass_inspector)
        fields = inspector(E1)
        assert len(fields) == 2

    def test_raises_for_non_dataclass(self) -> None:
        inspector = first_match(dataclass_inspector)
        with pytest.raises(TypeError):
            inspector(int)

    def test_priority_order(self) -> None:
        """First matching inspector wins."""
        call_log: list[str] = []

        def custom_inspector(cls: type) -> dict[str, FieldInfo] | None:
            call_log.append("custom")
            return None  # doesn't handle anything

        inspector = first_match(custom_inspector, dataclass_inspector)
        fields = inspector(E1)
        assert len(fields) == 2
        assert "custom" in call_log


# ===============================================================================
# NEW Property 23: FieldInfo.get and FieldInfo.get_all
# ===============================================================================


class TestFieldInfoGetMethods:
    """FieldInfo.get and get_all return correct capabilities."""

    def test_get_returns_first_match(self) -> None:
        info = _fields_of(E2)["name"]
        min_len = info.get(MinLen)
        assert min_len is not None
        assert isinstance(min_len, MinLen)
        assert min_len.value == 1

    def test_get_returns_none_when_absent(self) -> None:
        info = _fields_of(E7)["x"]
        assert info.get(MinLen) is None

    def test_get_all_returns_tuple(self) -> None:
        info = _fields_of(E8)["code"]
        all_caps = info.get_all(MinLen)
        assert len(all_caps) == 1
        assert all_caps[0].value == 2

    def test_get_all_empty_when_absent(self) -> None:
        info = _fields_of(E7)["x"]
        assert info.get_all(MinLen) == ()


# ===============================================================================
# NEW Property 24: WithDefaults and WithOptional compile correctly
# ===============================================================================


class TestNewEntitiesCompilation:
    """New entity types (WithOptional, WithDefaults) compile correctly."""

    def test_with_optional_compiles(self) -> None:
        axes = Axes.default()
        result = compile_fields(WithOptional, axes, list(SAFE_PHASES))
        assert len(result) == 2

    def test_with_defaults_compiles(self) -> None:
        axes = Axes.default()
        result = compile_fields(WithDefaults, axes, list(SAFE_PHASES))
        assert len(result) == 2

    def test_with_mixed_compiles(self) -> None:
        axes = Axes.default()
        result = compile_fields(WithMixed, axes, list(SAFE_PHASES))
        assert len(result) == 4

    def test_empty_entity_compiles(self) -> None:
        axes = Axes.default()
        result = compile_fields(EmptyEntity, axes, list(SAFE_PHASES))
        assert len(result) == 0

    def test_with_optional_constraints(self) -> None:
        axes = Axes.default()
        all_c = extract_all_constraints(WithOptional, axes)
        _, c_x = all_c["x"]
        assert c_x.is_optional is False
        _, c_y = all_c["y"]
        assert c_y.is_optional is True

    def test_with_defaults_constraints(self) -> None:
        axes = Axes.default()
        all_c = extract_all_constraints(WithDefaults, axes)
        for _name, (_base_type, constraints) in all_c.items():
            assert constraints.is_identity is False
            assert constraints.is_unique is False

    def test_with_mixed_identity(self) -> None:
        axes = Axes.default()
        all_c = extract_all_constraints(WithMixed, axes)
        _, c_id = all_c["id"]
        assert c_id.is_identity is True
        _, c_name = all_c["name"]
        assert c_name.is_identity is False
        _, c_score = all_c["score"]
        assert c_score.min_value == 0


# ===============================================================================
# NEW Property 25: Duplicate context_type in phases raises ValueError
# ===============================================================================


class TestDuplicatePhaseDetection:
    """compile_fields raises ValueError on duplicate context_type."""

    def test_duplicate_raises(self) -> None:
        axes = Axes.default()
        with pytest.raises(ValueError, match="Duplicate context_type"):
            compile_fields(E1, axes, [OPENAPI_PHASE, OPENAPI_PHASE])

    def test_no_duplicate_succeeds(self) -> None:
        axes = Axes.default()
        # Should not raise
        compile_fields(E1, axes, [OPENAPI_PHASE, ARGPARSE_PHASE])

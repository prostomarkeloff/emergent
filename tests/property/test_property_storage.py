# pyright: reportPrivateUsage=false
"""Property-based tests for storage roundtrip and coercion properties.

Uses hypothesis to generate random entity instances and verify that:
1. Storage roundtrip preserves entity equality (no coercion case)
2. to_storage_dict keys match compiled field names
3. to_storage_dict values match entity attributes (no coercion case)
4. Identity field detection works via Compilation
5. coerce_expr is a no-op when no coercions exist
6. coerce_expr is idempotent
7. Roundtrip with more types (bool, str, int, float)
8. Multiple entity roundtrip (3+ entities)
9. Compilation.identity_field via Compilation dataclass
10. Storage dict preserves field order
11. from_storage with lambda getter (dict-based and attribute-based)
12. Empty entity roundtrip (edge case)
13. Compilation model and entity fields store types correctly
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

import hypothesis.strategies as st
from hypothesis import given

from emergent.wire.axis.query._expr import And, Const, Eq, Field, Gt, Lt
from emergent.wire.axis.schema._universal import Identity, MaxLen, Min, Unique
from emergent.wire.compile._core import Axes
from emergent.wire.compile._phase import (
    Compilation,
    FieldCompilation,
    STORAGE_FIELD_PHASE,
    compile_fields,
    coerce_expr,
    from_storage,
    to_storage_dict,
)


# ===============================================================================
# Test entities
# ===============================================================================


@dataclass
class SimpleEntity:
    id: Annotated[int, Identity]
    name: str
    value: float
    active: bool


@dataclass
class MinimalEntity:
    x: int
    y: str


@dataclass
class BoolEntity:
    flag_a: bool
    flag_b: bool


@dataclass
class FloatEntity:
    x: float
    y: float
    z: float


@dataclass
class MixedTypesEntity:
    """Entity with all basic types: bool, str, int, float."""

    count: int
    label: str
    ratio: float
    enabled: bool


@dataclass
class WithConstraints:
    """Entity with constraints but no coercion."""

    id: Annotated[int, Identity]
    name: Annotated[str, MaxLen(100)]
    score: Annotated[int, Min(0)]


@dataclass
class MultiIdentityCandidate:
    """Entity to test that only the Identity field is detected."""

    id: Annotated[int, Identity]
    code: Annotated[str, Unique]
    value: int


@dataclass
class NoIdentity:
    """Entity without Identity field."""

    a: int
    b: str


@dataclass
class EmptyEntity:
    """Entity with no fields at all."""

    pass


@dataclass
class SingleField:
    """Entity with a single field."""

    only: int


@dataclass
class SingleIdentity:
    """Entity with a single identity field."""

    id: Annotated[int, Identity]


# ===============================================================================
# Compile fields once at module level (pure, deterministic)
# ===============================================================================

_axes = Axes.default()
_simple_fields = tuple(compile_fields(SimpleEntity, _axes, [STORAGE_FIELD_PHASE]))
_minimal_fields = tuple(compile_fields(MinimalEntity, _axes, [STORAGE_FIELD_PHASE]))
_bool_fields = tuple(compile_fields(BoolEntity, _axes, [STORAGE_FIELD_PHASE]))
_float_fields = tuple(compile_fields(FloatEntity, _axes, [STORAGE_FIELD_PHASE]))
_mixed_fields = tuple(compile_fields(MixedTypesEntity, _axes, [STORAGE_FIELD_PHASE]))
_constrained_fields = tuple(compile_fields(WithConstraints, _axes, [STORAGE_FIELD_PHASE]))
_multi_id_fields = tuple(compile_fields(MultiIdentityCandidate, _axes, [STORAGE_FIELD_PHASE]))
_no_identity_fields = tuple(compile_fields(NoIdentity, _axes, [STORAGE_FIELD_PHASE]))
_empty_fields = tuple(compile_fields(EmptyEntity, _axes, [STORAGE_FIELD_PHASE]))
_single_fields = tuple(compile_fields(SingleField, _axes, [STORAGE_FIELD_PHASE]))
_single_id_fields = tuple(compile_fields(SingleIdentity, _axes, [STORAGE_FIELD_PHASE]))


# ===============================================================================
# Hypothesis strategies
# ===============================================================================


@st.composite
def simple_entities(draw: st.DrawFn) -> SimpleEntity:
    return SimpleEntity(
        id=draw(st.integers(-1000, 1000)),
        name=draw(
            st.text(
                min_size=0,
                max_size=50,
                alphabet=st.characters(whitelist_categories=("L", "N")),
            )
        ),
        value=draw(
            st.floats(
                allow_nan=False,
                allow_infinity=False,
                min_value=-1e6,
                max_value=1e6,
            )
        ),
        active=draw(st.booleans()),
    )


@st.composite
def minimal_entities(draw: st.DrawFn) -> MinimalEntity:
    return MinimalEntity(
        x=draw(st.integers(-1000, 1000)),
        y=draw(
            st.text(
                min_size=0,
                max_size=50,
                alphabet=st.characters(whitelist_categories=("L", "N")),
            )
        ),
    )


@st.composite
def bool_entities(draw: st.DrawFn) -> BoolEntity:
    return BoolEntity(
        flag_a=draw(st.booleans()),
        flag_b=draw(st.booleans()),
    )


@st.composite
def float_entities(draw: st.DrawFn) -> FloatEntity:
    return FloatEntity(
        x=draw(st.floats(allow_nan=False, allow_infinity=False, min_value=-1e6, max_value=1e6)),
        y=draw(st.floats(allow_nan=False, allow_infinity=False, min_value=-1e6, max_value=1e6)),
        z=draw(st.floats(allow_nan=False, allow_infinity=False, min_value=-1e6, max_value=1e6)),
    )


@st.composite
def mixed_entities(draw: st.DrawFn) -> MixedTypesEntity:
    return MixedTypesEntity(
        count=draw(st.integers(-1000, 1000)),
        label=draw(
            st.text(
                min_size=0,
                max_size=50,
                alphabet=st.characters(whitelist_categories=("L", "N")),
            )
        ),
        ratio=draw(
            st.floats(
                allow_nan=False,
                allow_infinity=False,
                min_value=-1e6,
                max_value=1e6,
            )
        ),
        enabled=draw(st.booleans()),
    )


@st.composite
def constrained_entities(draw: st.DrawFn) -> WithConstraints:
    return WithConstraints(
        id=draw(st.integers(-1000, 1000)),
        name=draw(
            st.text(
                min_size=0,
                max_size=100,
                alphabet=st.characters(whitelist_categories=("L", "N")),
            )
        ),
        score=draw(st.integers(0, 10000)),
    )


@st.composite
def simple_exprs(draw: st.DrawFn) -> Eq | Gt | Lt | And:
    """Generate simple query expressions over SimpleEntity fields."""
    choice = draw(st.integers(0, 3))
    if choice == 0:
        return Eq(Field("name"), Const(draw(st.text(min_size=0, max_size=20))))
    elif choice == 1:
        return Gt(Field("value"), Const(draw(st.integers(-100, 100))))
    elif choice == 2:
        return Lt(Field("id"), Const(draw(st.integers(-100, 100))))
    else:
        left = Eq(Field("name"), Const(draw(st.text(min_size=0, max_size=10))))
        right = Gt(Field("value"), Const(draw(st.integers(-50, 50))))
        return And(left, right)


# ===============================================================================
# Property 1: Storage roundtrip (no coercion)
# ===============================================================================


@given(entity=simple_entities())
def test_storage_roundtrip_simple(entity: SimpleEntity) -> None:
    """from_storage(to_storage_dict(entity)) == entity for entities without coercion."""
    data = to_storage_dict(entity, _simple_fields)
    restored = from_storage(lambda n: data[n], SimpleEntity, _simple_fields)
    assert restored == entity


@given(entity=minimal_entities())
def test_storage_roundtrip_minimal(entity: MinimalEntity) -> None:
    """from_storage(to_storage_dict(entity)) == entity for minimal entities."""
    data = to_storage_dict(entity, _minimal_fields)
    restored = from_storage(lambda n: data[n], MinimalEntity, _minimal_fields)
    assert restored == entity


# ===============================================================================
# Property 2: to_storage_dict keys match field names
# ===============================================================================


@given(entity=simple_entities())
def test_storage_dict_keys_match_field_names(entity: SimpleEntity) -> None:
    """to_storage_dict keys are exactly the compiled field names."""
    data = to_storage_dict(entity, _simple_fields)
    expected_keys = {fc.name for fc in _simple_fields}
    assert set(data.keys()) == expected_keys


@given(entity=minimal_entities())
def test_storage_dict_keys_match_field_names_minimal(entity: MinimalEntity) -> None:
    """to_storage_dict keys are exactly the compiled field names (minimal)."""
    data = to_storage_dict(entity, _minimal_fields)
    expected_keys = {fc.name for fc in _minimal_fields}
    assert set(data.keys()) == expected_keys


# ===============================================================================
# Property 3: to_storage_dict values match attributes (no coercion)
# ===============================================================================


@given(entity=simple_entities())
def test_storage_dict_values_match_attrs(entity: SimpleEntity) -> None:
    """Without coercion, to_storage_dict values equal getattr(entity, name)."""
    data = to_storage_dict(entity, _simple_fields)
    for fc in _simple_fields:
        assert data[fc.name] == getattr(entity, fc.name)


@given(entity=minimal_entities())
def test_storage_dict_values_match_attrs_minimal(entity: MinimalEntity) -> None:
    """Without coercion, to_storage_dict values equal getattr(entity, name) (minimal)."""
    data = to_storage_dict(entity, _minimal_fields)
    for fc in _minimal_fields:
        assert data[fc.name] == getattr(entity, fc.name)


# ===============================================================================
# Property 4: Identity field detection via Compilation
# ===============================================================================


def test_identity_field_detected_simple() -> None:
    """SimpleEntity has Identity on 'id', Compilation.identity_field should find it."""

    class DummyModel:
        pass

    compilation = Compilation(
        model=DummyModel,
        entity=SimpleEntity,
        fields=_simple_fields,
    )
    assert compilation.identity_field == "id"


def test_no_identity_field_minimal() -> None:
    """MinimalEntity has no Identity, Compilation.identity_field should return None."""

    class DummyModel:
        pass

    compilation = Compilation(
        model=DummyModel,
        entity=MinimalEntity,
        fields=_minimal_fields,
    )
    assert compilation.identity_field is None


def test_identity_field_storage_context() -> None:
    """The 'id' field's StorageFieldContext has is_identity=True."""
    id_fc = next(fc for fc in _simple_fields if fc.name == "id")
    meta = id_fc[STORAGE_FIELD_PHASE]
    assert meta.is_identity is True

    # Other fields should NOT be identity
    for fc in _simple_fields:
        if fc.name != "id":
            meta = fc[STORAGE_FIELD_PHASE]
            assert meta.is_identity is False


# ===============================================================================
# Property 5: coerce_expr no-op (no coercions)
# ===============================================================================


@given(expr=simple_exprs())
def test_coerce_expr_noop_no_coercions(expr: Eq | Gt | Lt | And) -> None:
    """When no coercions exist, coerce_expr returns the expression unchanged."""
    result = coerce_expr(expr, _simple_fields)
    assert result == expr


@given(expr=simple_exprs())
def test_coerce_expr_noop_minimal(expr: Eq | Gt | Lt | And) -> None:
    """coerce_expr is a no-op for minimal fields too (no coercions)."""
    result = coerce_expr(expr, _minimal_fields)
    assert result == expr


# ===============================================================================
# Property 6: coerce_expr idempotence
# ===============================================================================


@given(expr=simple_exprs())
def test_coerce_expr_idempotent(expr: Eq | Gt | Lt | And) -> None:
    """coerce_expr(coerce_expr(expr, fields), fields) == coerce_expr(expr, fields)."""
    once = coerce_expr(expr, _simple_fields)
    twice = coerce_expr(once, _simple_fields)
    assert twice == once


# ===============================================================================
# NEW Property 7: Roundtrip with more types (bool, str, int, float)
# ===============================================================================


@given(entity=bool_entities())
def test_storage_roundtrip_bool(entity: BoolEntity) -> None:
    """Roundtrip works for entities with bool fields."""
    data = to_storage_dict(entity, _bool_fields)
    restored = from_storage(lambda n: data[n], BoolEntity, _bool_fields)
    assert restored == entity


@given(entity=float_entities())
def test_storage_roundtrip_float(entity: FloatEntity) -> None:
    """Roundtrip works for entities with multiple float fields."""
    data = to_storage_dict(entity, _float_fields)
    restored = from_storage(lambda n: data[n], FloatEntity, _float_fields)
    assert restored == entity


@given(entity=mixed_entities())
def test_storage_roundtrip_mixed_types(entity: MixedTypesEntity) -> None:
    """Roundtrip works for entities with bool, str, int, float fields."""
    data = to_storage_dict(entity, _mixed_fields)
    restored = from_storage(lambda n: data[n], MixedTypesEntity, _mixed_fields)
    assert restored == entity


@given(entity=constrained_entities())
def test_storage_roundtrip_constrained(entity: WithConstraints) -> None:
    """Roundtrip works for entities with constraints (Identity, MaxLen, Min)."""
    data = to_storage_dict(entity, _constrained_fields)
    restored = from_storage(lambda n: data[n], WithConstraints, _constrained_fields)
    assert restored == entity


@given(entity=bool_entities())
def test_storage_dict_values_match_bool(entity: BoolEntity) -> None:
    """Bool values in storage dict match entity attributes."""
    data = to_storage_dict(entity, _bool_fields)
    assert data["flag_a"] is entity.flag_a
    assert data["flag_b"] is entity.flag_b


@given(entity=float_entities())
def test_storage_dict_values_match_float(entity: FloatEntity) -> None:
    """Float values in storage dict match entity attributes."""
    data = to_storage_dict(entity, _float_fields)
    assert data["x"] == entity.x
    assert data["y"] == entity.y
    assert data["z"] == entity.z


# ===============================================================================
# NEW Property 8: Multiple entity roundtrip (3+ entity types)
# ===============================================================================


@given(
    simple=simple_entities(),
    minimal=minimal_entities(),
    mixed=mixed_entities(),
)
def test_multiple_entity_roundtrip(
    simple: SimpleEntity, minimal: MinimalEntity, mixed: MixedTypesEntity
) -> None:
    """Three different entity types all roundtrip correctly in the same test."""
    # SimpleEntity
    data_s = to_storage_dict(simple, _simple_fields)
    restored_s = from_storage(lambda n: data_s[n], SimpleEntity, _simple_fields)
    assert restored_s == simple

    # MinimalEntity
    data_m = to_storage_dict(minimal, _minimal_fields)
    restored_m = from_storage(lambda n: data_m[n], MinimalEntity, _minimal_fields)
    assert restored_m == minimal

    # MixedTypesEntity
    data_x = to_storage_dict(mixed, _mixed_fields)
    restored_x = from_storage(lambda n: data_x[n], MixedTypesEntity, _mixed_fields)
    assert restored_x == mixed


@given(
    bool_ent=bool_entities(),
    float_ent=float_entities(),
    constrained_ent=constrained_entities(),
)
def test_multiple_entity_roundtrip_varied(
    bool_ent: BoolEntity, float_ent: FloatEntity, constrained_ent: WithConstraints
) -> None:
    """Another set of three entity types roundtrip correctly."""
    data_b = to_storage_dict(bool_ent, _bool_fields)
    assert from_storage(lambda n: data_b[n], BoolEntity, _bool_fields) == bool_ent

    data_f = to_storage_dict(float_ent, _float_fields)
    assert from_storage(lambda n: data_f[n], FloatEntity, _float_fields) == float_ent

    data_c = to_storage_dict(constrained_ent, _constrained_fields)
    assert from_storage(lambda n: data_c[n], WithConstraints, _constrained_fields) == constrained_ent


# ===============================================================================
# NEW Property 9: Compilation.identity_field via Compilation dataclass
# ===============================================================================


def test_compilation_identity_field_with_constraints() -> None:
    """WithConstraints entity has Identity on 'id'."""

    class DummyModel:
        pass

    compilation = Compilation(
        model=DummyModel,
        entity=WithConstraints,
        fields=_constrained_fields,
    )
    assert compilation.identity_field == "id"


def test_compilation_identity_field_multi_id_candidate() -> None:
    """MultiIdentityCandidate has Identity on 'id', Unique on 'code' (not identity)."""

    class DummyModel:
        pass

    compilation = Compilation(
        model=DummyModel,
        entity=MultiIdentityCandidate,
        fields=_multi_id_fields,
    )
    assert compilation.identity_field == "id"


def test_compilation_no_identity_field_no_identity() -> None:
    """NoIdentity entity has no Identity field."""

    class DummyModel:
        pass

    compilation = Compilation(
        model=DummyModel,
        entity=NoIdentity,
        fields=_no_identity_fields,
    )
    assert compilation.identity_field is None


def test_compilation_identity_field_single() -> None:
    """SingleIdentity entity has exactly one Identity field."""

    class DummyModel:
        pass

    compilation = Compilation(
        model=DummyModel,
        entity=SingleIdentity,
        fields=_single_id_fields,
    )
    assert compilation.identity_field == "id"


# ===============================================================================
# NEW Property 10: Storage dict preserves field order
# ===============================================================================


@given(entity=simple_entities())
def test_storage_dict_preserves_field_order_simple(entity: SimpleEntity) -> None:
    """Keys appear in same order as dataclass fields."""
    data = to_storage_dict(entity, _simple_fields)
    field_names = [fc.name for fc in _simple_fields]
    assert list(data.keys()) == field_names


@given(entity=mixed_entities())
def test_storage_dict_preserves_field_order_mixed(entity: MixedTypesEntity) -> None:
    """Keys appear in same order as dataclass fields (mixed types)."""
    data = to_storage_dict(entity, _mixed_fields)
    field_names = [fc.name for fc in _mixed_fields]
    assert list(data.keys()) == field_names


@given(entity=constrained_entities())
def test_storage_dict_preserves_field_order_constrained(entity: WithConstraints) -> None:
    """Keys appear in same order as dataclass fields (constrained)."""
    data = to_storage_dict(entity, _constrained_fields)
    field_names = [fc.name for fc in _constrained_fields]
    assert list(data.keys()) == field_names


def test_storage_dict_order_matches_compilation_order() -> None:
    """Storage dict field order matches compile_fields output order."""
    entity = SimpleEntity(id=1, name="test", value=3.14, active=True)
    data = to_storage_dict(entity, _simple_fields)
    compiled_order = [fc.name for fc in _simple_fields]
    dict_order = list(data.keys())
    assert dict_order == compiled_order


# ===============================================================================
# NEW Property 11: from_storage with lambda getter (dict and attribute based)
# ===============================================================================


@given(entity=simple_entities())
def test_from_storage_dict_based_getter(entity: SimpleEntity) -> None:
    """from_storage with dict-based getter (lambda n: data[n])."""
    data = to_storage_dict(entity, _simple_fields)
    restored = from_storage(lambda n: data[n], SimpleEntity, _simple_fields)
    assert restored == entity


@given(entity=simple_entities())
def test_from_storage_attribute_based_getter(entity: SimpleEntity) -> None:
    """from_storage with attribute-based getter (lambda n: getattr(obj, n))."""
    # The entity itself serves as the "storage row"
    restored = from_storage(
        lambda n: getattr(entity, n), SimpleEntity, _simple_fields
    )
    assert restored == entity


@given(entity=mixed_entities())
def test_from_storage_attribute_getter_mixed(entity: MixedTypesEntity) -> None:
    """Attribute-based getter with mixed types."""
    restored = from_storage(
        lambda n: getattr(entity, n), MixedTypesEntity, _mixed_fields
    )
    assert restored == entity


@given(entity=constrained_entities())
def test_from_storage_dict_getter_constrained(entity: WithConstraints) -> None:
    """Dict-based getter with constrained entity."""
    data = to_storage_dict(entity, _constrained_fields)
    restored = from_storage(lambda n: data[n], WithConstraints, _constrained_fields)
    assert restored == entity


def test_from_storage_custom_dict_getter() -> None:
    """from_storage with a custom dict that simulates a database row."""
    row = {"x": 42, "y": "hello"}
    restored = from_storage(lambda n: row[n], MinimalEntity, _minimal_fields)
    assert restored == MinimalEntity(x=42, y="hello")


def test_from_storage_attribute_getter_named_object() -> None:
    """from_storage with attribute-based getter on a simple namespace object."""

    class Row:
        def __init__(self) -> None:
            self.x = 99
            self.y = "world"

    row = Row()
    restored = from_storage(lambda n: getattr(row, n), MinimalEntity, _minimal_fields)
    assert restored == MinimalEntity(x=99, y="world")


# ===============================================================================
# NEW Property 12: Empty entity roundtrip (edge case)
# ===============================================================================


def test_empty_entity_to_storage_dict() -> None:
    """to_storage_dict for empty entity returns empty dict."""
    entity = EmptyEntity()
    data = to_storage_dict(entity, _empty_fields)
    assert data == {}


def test_empty_entity_from_storage() -> None:
    """from_storage for empty entity creates instance with no fields."""
    restored = from_storage(lambda n: None, EmptyEntity, _empty_fields)
    assert isinstance(restored, EmptyEntity)
    assert restored == EmptyEntity()


def test_empty_entity_roundtrip() -> None:
    """Full roundtrip for empty entity."""
    entity = EmptyEntity()
    data = to_storage_dict(entity, _empty_fields)
    restored = from_storage(lambda n: data.get(n), EmptyEntity, _empty_fields)
    assert restored == entity


def test_empty_entity_keys() -> None:
    """to_storage_dict keys for empty entity is empty set."""
    data = to_storage_dict(EmptyEntity(), _empty_fields)
    assert set(data.keys()) == set()


def test_empty_entity_compilation_no_identity() -> None:
    """Empty entity has no identity field."""

    class DummyModel:
        pass

    compilation = Compilation(
        model=DummyModel,
        entity=EmptyEntity,
        fields=_empty_fields,
    )
    assert compilation.identity_field is None


# ===============================================================================
# NEW Property 13: Compilation model and entity fields store types correctly
# ===============================================================================


def test_compilation_stores_model_type() -> None:
    """Compilation.model stores the model type correctly."""

    class MyModel:
        pass

    compilation = Compilation(
        model=MyModel,
        entity=SimpleEntity,
        fields=_simple_fields,
    )
    assert compilation.model is MyModel


def test_compilation_stores_entity_type() -> None:
    """Compilation.entity stores the entity type correctly."""

    class MyModel:
        pass

    compilation = Compilation(
        model=MyModel,
        entity=SimpleEntity,
        fields=_simple_fields,
    )
    assert compilation.entity is SimpleEntity


def test_compilation_stores_different_model_types() -> None:
    """Different model types are stored correctly."""

    class SAModel:
        pass

    class MongoDoc:
        pass

    sa_comp = Compilation(
        model=SAModel,
        entity=SimpleEntity,
        fields=_simple_fields,
    )
    mongo_comp = Compilation(
        model=MongoDoc,
        entity=SimpleEntity,
        fields=_simple_fields,
    )

    assert sa_comp.model is SAModel
    assert mongo_comp.model is MongoDoc
    assert sa_comp.entity is SimpleEntity
    assert mongo_comp.entity is SimpleEntity


def test_compilation_stores_different_entity_types() -> None:
    """Different entity types are stored correctly."""

    class DummyModel:
        pass

    comp_simple = Compilation(
        model=DummyModel,
        entity=SimpleEntity,
        fields=_simple_fields,
    )
    comp_minimal = Compilation(
        model=DummyModel,
        entity=MinimalEntity,
        fields=_minimal_fields,
    )

    assert comp_simple.entity is SimpleEntity
    assert comp_minimal.entity is MinimalEntity
    assert comp_simple.model is DummyModel
    assert comp_minimal.model is DummyModel


def test_compilation_fields_stored_as_tuple() -> None:
    """Compilation.fields is a tuple of FieldCompilation."""

    class DummyModel:
        pass

    compilation = Compilation(
        model=DummyModel,
        entity=SimpleEntity,
        fields=_simple_fields,
    )
    assert isinstance(compilation.fields, tuple)
    assert len(compilation.fields) == len(_simple_fields)
    for fc in compilation.fields:
        assert isinstance(fc, FieldCompilation)


def test_compilation_fields_match_compiled_names() -> None:
    """Compilation.fields have correct names from compile_fields."""

    class DummyModel:
        pass

    compilation = Compilation(
        model=DummyModel,
        entity=SimpleEntity,
        fields=_simple_fields,
    )
    names = {fc.name for fc in compilation.fields}
    assert names == {"id", "name", "value", "active"}


# ===============================================================================
# NEW Property 14: Single-field entity roundtrip
# ===============================================================================


def test_single_field_roundtrip() -> None:
    """Roundtrip for entity with a single field."""
    entity = SingleField(only=42)
    data = to_storage_dict(entity, _single_fields)
    assert list(data.keys()) == ["only"]
    assert data["only"] == 42
    restored = from_storage(lambda n: data[n], SingleField, _single_fields)
    assert restored == entity


def test_single_field_keys() -> None:
    """Single-field entity has exactly one key."""
    data = to_storage_dict(SingleField(only=0), _single_fields)
    assert len(data) == 1
    assert "only" in data


# ===============================================================================
# NEW Property 15: coerce_expr properties for more field types
# ===============================================================================


@given(expr=simple_exprs())
def test_coerce_expr_noop_constrained(expr: Eq | Gt | Lt | And) -> None:
    """coerce_expr is a no-op for constrained fields (no coercions)."""
    result = coerce_expr(expr, _constrained_fields)
    assert result == expr


@given(expr=simple_exprs())
def test_coerce_expr_noop_mixed(expr: Eq | Gt | Lt | And) -> None:
    """coerce_expr is a no-op for mixed type fields (no coercions)."""
    result = coerce_expr(expr, _mixed_fields)
    assert result == expr


@given(expr=simple_exprs())
def test_coerce_expr_idempotent_constrained(expr: Eq | Gt | Lt | And) -> None:
    """coerce_expr idempotence for constrained fields."""
    once = coerce_expr(expr, _constrained_fields)
    twice = coerce_expr(once, _constrained_fields)
    assert twice == once


@given(expr=simple_exprs())
def test_coerce_expr_idempotent_mixed(expr: Eq | Gt | Lt | And) -> None:
    """coerce_expr idempotence for mixed type fields."""
    once = coerce_expr(expr, _mixed_fields)
    twice = coerce_expr(once, _mixed_fields)
    assert twice == once


# ===============================================================================
# NEW Property 16: Storage field context consistency
# ===============================================================================


def test_all_fields_have_storage_context() -> None:
    """Every compiled field has a STORAGE_FIELD_PHASE context."""
    for fc in _simple_fields:
        ctx = fc[STORAGE_FIELD_PHASE]
        assert ctx is not None

    for fc in _mixed_fields:
        ctx = fc[STORAGE_FIELD_PHASE]
        assert ctx is not None


def test_identity_fields_consistent_across_entities() -> None:
    """Identity field context is_identity is consistent across different entities."""
    # SimpleEntity: id is identity
    id_fc = next(fc for fc in _simple_fields if fc.name == "id")
    assert id_fc[STORAGE_FIELD_PHASE].is_identity is True

    # WithConstraints: id is identity
    id_fc2 = next(fc for fc in _constrained_fields if fc.name == "id")
    assert id_fc2[STORAGE_FIELD_PHASE].is_identity is True

    # MultiIdentityCandidate: id is identity, code is not
    id_fc3 = next(fc for fc in _multi_id_fields if fc.name == "id")
    assert id_fc3[STORAGE_FIELD_PHASE].is_identity is True
    code_fc = next(fc for fc in _multi_id_fields if fc.name == "code")
    assert code_fc[STORAGE_FIELD_PHASE].is_identity is False

    # NoIdentity: no identity fields
    for fc in _no_identity_fields:
        assert fc[STORAGE_FIELD_PHASE].is_identity is False

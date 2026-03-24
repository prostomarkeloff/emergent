"""Behavioral tests for storage roundtrip — values are preserved through serialization.

Every test verifies that entity field VALUES survive the to_storage_dict / from_storage
cycle exactly, and that compiled storage metadata reflects the correct identity field.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from hypothesis import given, settings
from hypothesis import strategies as st

from emergent.wire.axis.schema._universal import Identity, Min, Max, MinLen, MaxLen
from emergent.wire.compile._core import Axes
from emergent.wire.compile._phase import (
    Compilation,
    SchemaCompiler,
    PYDANTIC_PHASE,
    STORAGE_FIELD_PHASE,
    compile_fields,
    to_storage_dict,
    from_storage,
)


axes = Axes.default()


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _compile_storage_fields(cls: type) -> tuple:
    """Compile a class through STORAGE_FIELD_PHASE and return the fields tuple."""
    compiled = compile_fields(cls, axes, [STORAGE_FIELD_PHASE])
    return tuple(compiled)


def _roundtrip(entity: object, cls: type) -> object:
    """entity -> to_storage_dict -> from_storage -> entity_out."""
    fields = _compile_storage_fields(type(entity))
    d = to_storage_dict(entity, fields)
    return from_storage(lambda n: d[n], cls, fields)


# ═══════════════════════════════════════════════════════════════════════════════
# Basic roundtrip
# ═══════════════════════════════════════════════════════════════════════════════


def test_roundtrip_preserves_every_field_value() -> None:
    """Create entity -> to_storage_dict -> from_storage -> every field matches."""

    @dataclass
    class User:
        id: Annotated[int, Identity]
        name: str
        email: str
        age: int

    user_in = User(id=42, name="alice", email="alice@example.com", age=30)
    user_out = _roundtrip(user_in, User)

    assert user_out.id == 42
    assert user_out.name == "alice"
    assert user_out.email == "alice@example.com"
    assert user_out.age == 30


def test_roundtrip_preserves_zero_and_empty_string() -> None:
    """Edge values: 0 and '' survive roundtrip."""

    @dataclass
    class Entity:
        count: int
        label: str

    entity_in = Entity(count=0, label="")
    entity_out = _roundtrip(entity_in, Entity)

    assert entity_out.count == 0
    assert entity_out.label == ""


def test_roundtrip_preserves_negative_values() -> None:
    """Negative integers survive roundtrip."""

    @dataclass
    class Entity:
        balance: int

    entity_in = Entity(balance=-999)
    entity_out = _roundtrip(entity_in, Entity)

    assert entity_out.balance == -999


# ═══════════════════════════════════════════════════════════════════════════════
# Hypothesis roundtrip
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class HypUser:
    id: Annotated[int, Identity]
    name: str
    score: int


@given(
    uid=st.integers(min_value=0, max_value=10_000),
    name=st.text(min_size=0, max_size=50),
    score=st.integers(min_value=-1000, max_value=1000),
)
@settings(max_examples=100)
def test_hypothesis_roundtrip_preserves_values(uid: int, name: str, score: int) -> None:
    """Random entities survive storage roundtrip with all field values intact."""
    user_in = HypUser(id=uid, name=name, score=score)
    user_out = _roundtrip(user_in, HypUser)

    assert user_out.id == uid
    assert user_out.name == name
    assert user_out.score == score


# ═══════════════════════════════════════════════════════════════════════════════
# Storage dict contains correct values
# ═══════════════════════════════════════════════════════════════════════════════


def test_storage_dict_contains_correct_field_values() -> None:
    """to_storage_dict(User(id=1, name='alice'))['name'] == 'alice'."""

    @dataclass
    class User:
        id: Annotated[int, Identity]
        name: str

    user = User(id=1, name="alice")
    fields = _compile_storage_fields(User)
    d = to_storage_dict(user, fields)

    assert d["id"] == 1
    assert d["name"] == "alice"


def test_storage_dict_all_fields_present() -> None:
    """Storage dict has an entry for every field."""

    @dataclass
    class Product:
        sku: str
        price: int
        quantity: int

    product = Product(sku="ABC-123", price=999, quantity=5)
    fields = _compile_storage_fields(Product)
    d = to_storage_dict(product, fields)

    assert d["sku"] == "ABC-123"
    assert d["price"] == 999
    assert d["quantity"] == 5


# ═══════════════════════════════════════════════════════════════════════════════
# from_storage with dict getter
# ═══════════════════════════════════════════════════════════════════════════════


def test_from_storage_with_dict_getter_reconstructs_values() -> None:
    """from_storage(lambda n: d[n], cls, fields) produces entity with correct values."""

    @dataclass
    class Config:
        host: str
        port: int
        debug: bool

    raw = {"host": "localhost", "port": 8080, "debug": True}
    fields = _compile_storage_fields(Config)
    config = from_storage(lambda n: raw[n], Config, fields)

    assert config.host == "localhost"
    assert config.port == 8080
    assert config.debug is True


def test_from_storage_getter_called_per_field() -> None:
    """The getter function receives the correct field names."""

    @dataclass
    class Item:
        x: int
        y: int

    accessed_names: list[str] = []

    def tracking_getter(name: str) -> object:
        accessed_names.append(name)
        return {"x": 10, "y": 20}[name]

    fields = _compile_storage_fields(Item)
    item = from_storage(tracking_getter, Item, fields)

    assert item.x == 10
    assert item.y == 20
    assert accessed_names == ["x", "y"]


# ═══════════════════════════════════════════════════════════════════════════════
# Identity field detection
# ═══════════════════════════════════════════════════════════════════════════════


def test_identity_field_detected_in_compilation() -> None:
    """Compilation.identity_field == 'id' for entity with id: Annotated[int, Identity]."""

    @dataclass
    class User:
        id: Annotated[int, Identity]
        name: str

    compiler = SchemaCompiler(phases=(STORAGE_FIELD_PHASE,))
    ec = compiler.compile(User, axes)

    compilation: Compilation[User, dict] = Compilation(
        model=dict,
        entity=User,
        fields=ec.fields,
    )

    assert compilation.identity_field == "id"


def test_no_identity_field_returns_none() -> None:
    """Entity without Identity capability produces identity_field == None."""

    @dataclass
    class Record:
        name: str
        value: int

    compiler = SchemaCompiler(phases=(STORAGE_FIELD_PHASE,))
    ec = compiler.compile(Record, axes)

    compilation: Compilation[Record, dict] = Compilation(
        model=dict,
        entity=Record,
        fields=ec.fields,
    )

    assert compilation.identity_field is None


def test_identity_field_name_matches_annotated_field() -> None:
    """When the identity field is named 'pk', identity_field returns 'pk'."""

    @dataclass
    class Entity:
        pk: Annotated[int, Identity]
        data: str

    compiler = SchemaCompiler(phases=(STORAGE_FIELD_PHASE,))
    ec = compiler.compile(Entity, axes)

    compilation: Compilation[Entity, dict] = Compilation(
        model=dict,
        entity=Entity,
        fields=ec.fields,
    )

    assert compilation.identity_field == "pk"


# ═══════════════════════════════════════════════════════════════════════════════
# Roundtrip with capabilities preserves values
# ═══════════════════════════════════════════════════════════════════════════════


def test_roundtrip_with_constrained_fields() -> None:
    """Fields with Min/Max/MinLen/MaxLen constraints still roundtrip correctly."""

    @dataclass
    class Constrained:
        score: Annotated[int, Min(0), Max(100)]
        label: Annotated[str, MinLen(1), MaxLen(20)]

    entity_in = Constrained(score=75, label="hello")
    entity_out = _roundtrip(entity_in, Constrained)

    assert entity_out.score == 75
    assert entity_out.label == "hello"


@given(
    score=st.integers(min_value=0, max_value=100),
    label=st.text(min_size=1, max_size=20),
)
@settings(max_examples=50)
def test_hypothesis_roundtrip_constrained(score: int, label: str) -> None:
    """Hypothesis: constrained entities survive roundtrip."""

    @dataclass
    class Constrained:
        score: Annotated[int, Min(0), Max(100)]
        label: Annotated[str, MinLen(1), MaxLen(20)]

    entity_in = Constrained(score=score, label=label)
    entity_out = _roundtrip(entity_in, Constrained)

    assert entity_out.score == score
    assert entity_out.label == label

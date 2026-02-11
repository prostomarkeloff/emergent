"""Tests for emergent.wire.axis.schema._inspect — FieldInfo + inspectors."""

import dataclasses
from dataclasses import dataclass, FrozenInstanceError
from typing import Annotated, NamedTuple, TypedDict

import pytest

from emergent.wire.axis.schema._universal import (
    SchemaAxisCapability,
    UniversalCapability,
    Identity,
    Unique,
    MaxLen,
    MinLen,
    Doc,
    Min,
    Max,
    Ref,
    Nested,
)
from emergent.wire.axis.schema._inspect import (
    FieldInfo,
    Inspector,
    first_match,
    dataclass_inspector,
    pydantic_inspector,
    typeddict_inspector,
    namedtuple_inspector,
    inspect_type,
    inspect_field,
    unwrap_optional,
    unwrap_annotated,
    extract_capabilities,
    is_structured_type,
    unwrap_collection,
    get_nested_info,
    get_nested_type,
)


# ═══════════════════════════════════════════════════════════════════════════════
# FieldInfo — frozen, slotted, tuple
# ═══════════════════════════════════════════════════════════════════════════════


class TestFieldInfo:
    def test_frozen(self):
        fi = FieldInfo(name="x", base_type=str, is_optional=False, capabilities=())
        with pytest.raises((FrozenInstanceError, AttributeError)):
            fi.name = "y"  # type: ignore[misc]

    def test_slotted(self):
        fi = FieldInfo(name="x", base_type=str, is_optional=False, capabilities=())
        with pytest.raises((FrozenInstanceError, AttributeError)):
            fi.__dict__  # slots=True means no __dict__

    def test_capabilities_is_tuple(self):
        fi = FieldInfo(
            name="x", base_type=str, is_optional=False,
            capabilities=(Identity(), MaxLen(100)),
        )
        assert isinstance(fi.capabilities, tuple)

    def test_universal_returns_tuple(self):
        fi = FieldInfo(
            name="x", base_type=str, is_optional=False,
            capabilities=(Identity(), MaxLen(100)),
        )
        result = fi.universal
        assert isinstance(result, tuple)
        assert len(result) == 2  # both are UniversalCapability

    def test_dialect_returns_tuple(self):
        from emergent.wire.axis.schema.dialects.sql import SQLCapability, Index

        fi = FieldInfo(
            name="x", base_type=str, is_optional=False,
            capabilities=(Identity(), Index("idx_x")),
        )
        result = fi.dialect(SQLCapability)
        assert isinstance(result, tuple)
        assert len(result) == 1

    def test_has(self):
        fi = FieldInfo(
            name="x", base_type=int, is_optional=False,
            capabilities=(Identity(), Unique()),
        )
        assert fi.has(Identity) is True
        assert fi.has(Unique) is True
        assert fi.has(MaxLen) is False

    def test_get(self):
        fi = FieldInfo(
            name="x", base_type=str, is_optional=False,
            capabilities=(MaxLen(100), Doc("hello")),
        )
        ml = fi.get(MaxLen)
        assert ml is not None
        assert ml.value == 100

        assert fi.get(Identity) is None

    def test_get_all_returns_tuple(self):
        fi = FieldInfo(
            name="x", base_type=str, is_optional=False,
            capabilities=(Identity(), Unique()),
        )
        result = fi.get_all(UniversalCapability)
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_has_default(self):
        fi = FieldInfo(
            name="x", base_type=str, is_optional=False,
            capabilities=(), has_default=True,
        )
        assert fi.has_default is True


# ═══════════════════════════════════════════════════════════════════════════════
# Type Helpers
# ═══════════════════════════════════════════════════════════════════════════════


class TestUnwrapOptional:
    def test_plain_type(self):
        base, is_opt = unwrap_optional(str)
        assert base is str
        assert is_opt is False

    def test_optional(self):
        base, is_opt = unwrap_optional(str | None)
        assert base is str
        assert is_opt is True

    def test_union_not_optional(self):
        base, is_opt = unwrap_optional(str | int)
        assert is_opt is False


class TestUnwrapAnnotated:
    def test_plain_type(self):
        base, anns = unwrap_annotated(str)
        assert base is str
        assert anns == []

    def test_annotated(self):
        base, anns = unwrap_annotated(Annotated[str, Identity, MaxLen(100)])
        assert base is str
        assert len(anns) == 2


class TestExtractCapabilities:
    def test_instance_form(self):
        caps = extract_capabilities([MaxLen(100), Doc("hi")])
        assert isinstance(caps, tuple)
        assert len(caps) == 2

    def test_class_form(self):
        caps = extract_capabilities([Identity, Unique])
        assert isinstance(caps, tuple)
        assert len(caps) == 2
        assert isinstance(caps[0], Identity)
        assert isinstance(caps[1], Unique)

    def test_mixed_forms(self):
        caps = extract_capabilities([Identity, MaxLen(255)])
        assert len(caps) == 2

    def test_pattern_tuple(self):
        pattern = (Identity(), MaxLen(50))
        caps = extract_capabilities([pattern])
        assert len(caps) == 2

    def test_non_capability_ignored(self):
        caps = extract_capabilities(["not_a_cap", 42, Identity])
        assert len(caps) == 1

    def test_empty(self):
        caps = extract_capabilities([])
        assert caps == ()


# ═══════════════════════════════════════════════════════════════════════════════
# inspect_field
# ═══════════════════════════════════════════════════════════════════════════════


class TestInspectField:
    def test_plain_type(self):
        fi = inspect_field("name", str)
        assert fi.name == "name"
        assert fi.base_type is str
        assert fi.is_optional is False
        assert fi.capabilities == ()

    def test_annotated(self):
        fi = inspect_field("email", Annotated[str, Unique, MaxLen(255)])
        assert fi.base_type is str
        assert fi.is_optional is False
        assert len(fi.capabilities) == 2

    def test_optional(self):
        fi = inspect_field("bio", str | None)
        assert fi.base_type is str
        assert fi.is_optional is True

    def test_annotated_optional(self):
        fi = inspect_field("team_id", Annotated[int | None, Ref(target="Team")])
        assert fi.base_type is int
        assert fi.is_optional is True
        assert len(fi.capabilities) == 1

    def test_has_default(self):
        fi = inspect_field("count", int, has_default=True)
        assert fi.has_default is True


# ═══════════════════════════════════════════════════════════════════════════════
# Dataclass Inspector
# ═══════════════════════════════════════════════════════════════════════════════


class TestDataclassInspector:
    def test_basic_dataclass(self):
        @dataclass
        class User:
            id: Annotated[int, Identity]
            email: Annotated[str, Unique, MaxLen(255)]
            name: str

        result = dataclass_inspector(User)
        assert result is not None
        assert len(result) == 3
        assert result["id"].has(Identity)
        assert result["email"].has(Unique)
        assert result["name"].capabilities == ()

    def test_optional_field(self):
        @dataclass
        class User:
            bio: str | None = None

        result = dataclass_inspector(User)
        assert result is not None
        assert result["bio"].is_optional is True
        assert result["bio"].has_default is True

    def test_not_dataclass(self):
        class NotDC:
            pass

        assert dataclass_inspector(NotDC) is None

    def test_has_default_detection(self):
        @dataclass
        class Item:
            name: str
            count: int = 0

        result = dataclass_inspector(Item)
        assert result is not None
        assert result["name"].has_default is False
        assert result["count"].has_default is True


# ═══════════════════════════════════════════════════════════════════════════════
# Pydantic Inspector
# ═══════════════════════════════════════════════════════════════════════════════


class TestPydanticInspector:
    def test_pydantic_model(self):
        from pydantic import BaseModel

        class User(BaseModel):
            id: Annotated[int, Identity]
            email: str

        result = pydantic_inspector(User)
        assert result is not None
        assert len(result) == 2
        assert result["id"].has(Identity)

    def test_not_pydantic(self):
        @dataclass
        class DC:
            x: int

        assert pydantic_inspector(DC) is None


# ═══════════════════════════════════════════════════════════════════════════════
# TypedDict Inspector
# ═══════════════════════════════════════════════════════════════════════════════


class TestTypedDictInspector:
    def test_typeddict(self):
        class UserTD(TypedDict):
            id: int
            email: str

        result = typeddict_inspector(UserTD)
        assert result is not None
        assert len(result) == 2
        assert result["id"].base_type is int

    def test_typeddict_optional(self):
        class UserTD(TypedDict, total=False):
            bio: str

        result = typeddict_inspector(UserTD)
        assert result is not None
        assert result["bio"].is_optional is True

    def test_not_typeddict(self):
        @dataclass
        class DC:
            x: int

        assert typeddict_inspector(DC) is None


# ═══════════════════════════════════════════════════════════════════════════════
# NamedTuple Inspector
# ═══════════════════════════════════════════════════════════════════════════════


class TestNamedTupleInspector:
    def test_namedtuple(self):
        class Point(NamedTuple):
            x: float
            y: float

        result = namedtuple_inspector(Point)
        assert result is not None
        assert len(result) == 2
        assert result["x"].base_type is float

    def test_namedtuple_with_default(self):
        class Point(NamedTuple):
            x: float
            y: float = 0.0

        result = namedtuple_inspector(Point)
        assert result is not None
        assert result["x"].has_default is False
        assert result["y"].has_default is True

    def test_not_namedtuple(self):
        @dataclass
        class DC:
            x: int

        assert namedtuple_inspector(DC) is None


# ═══════════════════════════════════════════════════════════════════════════════
# first_match combinator
# ═══════════════════════════════════════════════════════════════════════════════


class TestFirstMatch:
    def test_dataclass_wins(self):
        @dataclass
        class User:
            id: int

        inspector = first_match(dataclass_inspector, typeddict_inspector)
        result = inspector(User)
        assert "id" in result

    def test_fallback_to_second(self):
        class UserTD(TypedDict):
            id: int

        inspector = first_match(dataclass_inspector, typeddict_inspector)
        result = inspector(UserTD)
        assert "id" in result

    def test_raises_on_no_match(self):
        class Plain:
            pass

        inspector = first_match(dataclass_inspector)
        with pytest.raises(TypeError, match="Cannot inspect"):
            inspector(Plain)


# ═══════════════════════════════════════════════════════════════════════════════
# Default inspect_type
# ═══════════════════════════════════════════════════════════════════════════════


class TestInspectType:
    def test_dataclass(self):
        @dataclass
        class User:
            id: int
            name: str

        result = inspect_type(User)
        assert len(result) == 2

    def test_pydantic(self):
        from pydantic import BaseModel

        class User(BaseModel):
            id: int

        result = inspect_type(User)
        assert "id" in result

    def test_typeddict(self):
        class UserTD(TypedDict):
            id: int

        result = inspect_type(UserTD)
        assert "id" in result

    def test_namedtuple(self):
        class Point(NamedTuple):
            x: float
            y: float

        result = inspect_type(Point)
        assert "x" in result

    def test_unsupported_raises(self):
        with pytest.raises(TypeError):
            inspect_type(str)  # type: ignore[arg-type]


# ═══════════════════════════════════════════════════════════════════════════════
# Nested Type Helpers
# ═══════════════════════════════════════════════════════════════════════════════


class TestIsStructuredType:
    def test_dataclass(self):
        @dataclass
        class DC:
            x: int

        assert is_structured_type(DC) is True

    def test_primitive(self):
        assert is_structured_type(str) is False
        assert is_structured_type(int) is False

    def test_pydantic(self):
        from pydantic import BaseModel

        class M(BaseModel):
            x: int

        assert is_structured_type(M) is True


class TestUnwrapCollection:
    def test_list(self):
        assert unwrap_collection(list[int]) is int

    def test_set(self):
        assert unwrap_collection(set[str]) is str

    def test_tuple_homogeneous(self):
        assert unwrap_collection(tuple[int, ...]) is int

    def test_not_collection(self):
        assert unwrap_collection(str) is str

    def test_plain_list(self):
        # list without type arg
        assert unwrap_collection(list) is list


class TestGetNestedInfo:
    def test_nested_dataclass(self):
        @dataclass
        class Address:
            city: str

        fi = FieldInfo(name="address", base_type=Address, is_optional=False, capabilities=())
        result = get_nested_info(fi)
        assert result is not None
        assert "city" in result

    def test_nested_collection(self):
        @dataclass
        class Item:
            name: str

        fi = FieldInfo(name="items", base_type=list[Item], is_optional=False, capabilities=())
        result = get_nested_info(fi)
        assert result is not None
        assert "name" in result

    def test_primitive_returns_none(self):
        fi = FieldInfo(name="count", base_type=int, is_optional=False, capabilities=())
        assert get_nested_info(fi) is None


class TestGetNestedType:
    def test_nested_dataclass(self):
        @dataclass
        class Address:
            city: str

        fi = FieldInfo(name="addr", base_type=Address, is_optional=False, capabilities=())
        assert get_nested_type(fi) is Address

    def test_nested_list(self):
        @dataclass
        class Item:
            name: str

        fi = FieldInfo(name="items", base_type=list[Item], is_optional=False, capabilities=())
        assert get_nested_type(fi) is Item

    def test_primitive_returns_none(self):
        fi = FieldInfo(name="x", base_type=int, is_optional=False, capabilities=())
        assert get_nested_type(fi) is None

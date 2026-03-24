"""Extended tests for emergent/wire/axis/schema/_inspect.py — coverage gaps.

Covers:
- pydantic_inspector: edge cases (annotation fallback, metadata fallback)
- namedtuple_inspector: empty fields, defaults, non-NamedTuple rejection
- typeddict_inspector: mixed required/optional keys
- unwrap_optional: multi-type union (not simple Optional)
- unwrap_annotated: non-Annotated type
- extract_capabilities: tuple pattern (tuple of capabilities in annotations)
- inspect_field: nested Annotated (Annotated inside Optional)
- first_match: no inspector matches
- _to_capability: class form, instance form, non-capability
- unwrap_collection: set, frozenset, tuple[X, ...]
- get_nested_info / get_nested_type: with collections, non-structured types
- is_structured_type for all variants
"""

from dataclasses import dataclass
from typing import Annotated, NamedTuple, Optional, TypedDict, Union

import pytest

from emergent.wire.axis.schema._inspect import (
    FieldInfo,
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
import emergent.wire.axis.schema._inspect as _inspect_mod
from emergent.wire.axis.schema._universal import (
    Identity,
    MaxLen,
    Unique,
    UniversalCapability,
    Doc,
)

# Access private function via getattr for testing internal behavior;
# pyright does not allow direct attribute access on private names from other modules.
_to_capability_fn = getattr(_inspect_mod, "_to_capability")


# ============================================================================
# Module-level types for nested tests (avoid forward reference issues)
# ============================================================================


@dataclass
class _InnerNested:
    value: int


@dataclass
class _OuterNested:
    inner: _InnerNested


@dataclass
class _ItemNested:
    name: str


@dataclass
class _ContainerNested:
    items: list[_ItemNested]


@dataclass
class _SimpleNested:
    x: int


# ============================================================================
# unwrap_optional
# ============================================================================


class TestUnwrapOptional:
    def test_simple_optional(self) -> None:
        base, is_opt = unwrap_optional(int | None)
        assert base is int
        assert is_opt is True

    def test_not_optional(self) -> None:
        base, is_opt = unwrap_optional(int)
        assert base is int
        assert is_opt is False

    def test_multi_type_union(self) -> None:
        """Union[int, str, None] is not simple Optional."""
        _base, is_opt = unwrap_optional(int | str | None)
        # Multi-type union, not simple Optional
        assert is_opt is False

    def test_union_without_none(self) -> None:
        _base, is_opt = unwrap_optional(int | str)
        assert is_opt is False


# ============================================================================
# unwrap_annotated
# ============================================================================


class TestUnwrapAnnotated:
    def test_annotated(self) -> None:
        base, anns = unwrap_annotated(Annotated[int, Identity])
        assert base is int
        assert len(anns) == 1

    def test_not_annotated(self) -> None:
        base, anns = unwrap_annotated(str)
        assert base is str
        assert anns == []


# ============================================================================
# _to_capability
# ============================================================================


class TestToCapability:
    def test_instance(self) -> None:
        cap = _to_capability_fn(MaxLen(100))
        assert cap is not None
        assert isinstance(cap, MaxLen)

    def test_class(self) -> None:
        cap = _to_capability_fn(Identity)
        assert cap is not None
        assert isinstance(cap, Identity)

    def test_non_capability(self) -> None:
        cap = _to_capability_fn("not a cap")
        assert cap is None

    def test_non_capability_type(self) -> None:
        cap = _to_capability_fn(str)
        assert cap is None


# ============================================================================
# extract_capabilities
# ============================================================================


class TestExtractCapabilities:
    def test_instance_caps(self) -> None:
        caps = extract_capabilities([MaxLen(50), Unique()])
        assert len(caps) == 2

    def test_class_caps(self) -> None:
        caps = extract_capabilities([Identity, Unique])
        assert len(caps) == 2

    def test_tuple_pattern(self) -> None:
        """Tuple of capabilities in annotations is expanded."""
        pattern = (Identity(), MaxLen(255))
        caps = extract_capabilities([pattern])
        assert len(caps) == 2

    def test_non_capabilities_ignored(self) -> None:
        caps = extract_capabilities(["hello", 42, Identity])
        assert len(caps) == 1

    def test_mixed(self) -> None:
        caps = extract_capabilities([Identity, MaxLen(50), "ignore"])
        assert len(caps) == 2


# ============================================================================
# inspect_field
# ============================================================================


class TestInspectField:
    def test_plain_type(self) -> None:
        info = inspect_field("x", int)
        assert info.name == "x"
        assert info.base_type is int
        assert info.is_optional is False
        assert info.capabilities == ()

    def test_annotated_type(self) -> None:
        info = inspect_field("email", Annotated[str, MaxLen(255)])
        assert info.base_type is str
        assert len(info.capabilities) == 1

    def test_optional_annotated(self) -> None:
        info = inspect_field("name", Optional[Annotated[str, MaxLen(50)]])
        assert info.base_type is str
        assert info.is_optional is True

    def test_has_default(self) -> None:
        info = inspect_field("active", bool, has_default=True)
        assert info.has_default is True

    def test_nested_annotated(self) -> None:
        """Annotated inside Optional with further annotations."""
        inner = Annotated[str, MaxLen(10)]
        info = inspect_field("x", Annotated[Union[inner, None], Unique])
        assert info.is_optional is True
        # Should have both MaxLen and Unique
        cap_types = {type(c).__name__ for c in info.capabilities}
        assert "MaxLen" in cap_types
        assert "Unique" in cap_types


# ============================================================================
# FieldInfo methods
# ============================================================================


class TestFieldInfoMethods:
    def _make_info(self) -> FieldInfo:
        return FieldInfo(
            name="email",
            base_type=str,
            is_optional=False,
            capabilities=(Identity(), MaxLen(255), Unique()),
        )

    def test_universal(self) -> None:
        info = self._make_info()
        universal = info.universal
        assert len(universal) == 3

    def test_dialect(self) -> None:
        info = self._make_info()
        universal = info.dialect(UniversalCapability)
        assert len(universal) == 3

    def test_has(self) -> None:
        info = self._make_info()
        assert info.has(Identity) is True
        assert info.has(Doc) is False

    def test_get(self) -> None:
        info = self._make_info()
        cap = info.get(MaxLen)
        assert cap is not None
        assert cap.value == 255

    def test_get_none(self) -> None:
        info = self._make_info()
        cap = info.get(Doc)
        assert cap is None

    def test_get_all(self) -> None:
        info = self._make_info()
        all_caps = info.get_all(UniversalCapability)
        assert len(all_caps) == 3


# ============================================================================
# first_match
# ============================================================================


class TestFirstMatch:
    def test_no_match_raises(self) -> None:
        """If no inspector handles the type, TypeError is raised."""
        inspector = first_match(dataclass_inspector)
        with pytest.raises(TypeError, match="Cannot inspect"):
            inspector(str)

    def test_first_wins(self) -> None:
        """First non-None result wins."""
        @dataclass
        class Foo:
            x: int

        inspector = first_match(dataclass_inspector, pydantic_inspector)
        result = inspector(Foo)
        assert "x" in result


# ============================================================================
# dataclass_inspector
# ============================================================================


class TestDataclassInspector:
    def test_not_dataclass(self) -> None:
        class Plain:
            x: int = 0

        result = dataclass_inspector(Plain)
        assert result is None

    def test_dataclass(self) -> None:
        @dataclass
        class Dc:
            a: int
            b: str = "hello"

        result = dataclass_inspector(Dc)
        assert result is not None
        assert "a" in result
        assert "b" in result
        assert result["b"].has_default is True


# ============================================================================
# pydantic_inspector
# ============================================================================


class TestPydanticInspector:
    def test_not_pydantic(self) -> None:
        class Plain:
            pass

        result = pydantic_inspector(Plain)
        assert result is None

    def test_pydantic_model(self) -> None:
        from pydantic import BaseModel

        class MyModel(BaseModel):
            name: str
            age: int = 25

        result = pydantic_inspector(MyModel)
        assert result is not None
        assert "name" in result
        assert "age" in result
        assert result["age"].has_default is True

    def test_pydantic_with_annotated(self) -> None:
        from pydantic import BaseModel

        class AnnotModel(BaseModel):
            email: Annotated[str, MaxLen(255)]

        result = pydantic_inspector(AnnotModel)
        assert result is not None
        info = result["email"]
        assert info.base_type is str
        caps = info.capabilities
        cap_types = [type(c).__name__ for c in caps]
        assert "MaxLen" in cap_types


# ============================================================================
# typeddict_inspector
# ============================================================================


class TestTypedDictInspector:
    def test_not_typeddict(self) -> None:
        class Plain:
            pass

        result = typeddict_inspector(Plain)
        assert result is None

    def test_typeddict(self) -> None:
        class TD(TypedDict, total=False):
            name: str
            age: int

        result = typeddict_inspector(TD)
        assert result is not None
        assert "name" in result
        assert "age" in result
        # total=False means all keys are optional
        assert result["name"].is_optional is True
        assert result["age"].is_optional is True
        assert result["age"].has_default is True

    def test_typeddict_with_annotated(self) -> None:
        class TDAnnot(TypedDict):
            email: Annotated[str, MaxLen(255)]

        result = typeddict_inspector(TDAnnot)
        assert result is not None
        info = result["email"]
        cap_types = [type(c).__name__ for c in info.capabilities]
        assert "MaxLen" in cap_types


# ============================================================================
# namedtuple_inspector
# ============================================================================


class TestNamedTupleInspector:
    def test_not_namedtuple(self) -> None:
        class Plain:
            pass

        result = namedtuple_inspector(Plain)
        assert result is None

    def test_namedtuple(self) -> None:
        class Point(NamedTuple):
            x: int
            y: int

        result = namedtuple_inspector(Point)
        assert result is not None
        assert "x" in result
        assert "y" in result
        assert result["x"].base_type is int

    def test_namedtuple_with_defaults(self) -> None:
        class Config(NamedTuple):
            host: str
            port: int = 8080

        result = namedtuple_inspector(Config)
        assert result is not None
        assert result["host"].has_default is False
        assert result["port"].has_default is True

    def test_namedtuple_not_tuple_fields(self) -> None:
        """Reject class that has _fields but not as tuple."""
        class Fake:
            _fields = "not a tuple"
            __annotations__ = {"x": int}

        result = namedtuple_inspector(Fake)
        assert result is None

    def test_namedtuple_empty_fields(self) -> None:
        """NamedTuple with empty _fields returns None."""
        class Empty:
            _fields: tuple[str, ...] = ()
            __annotations__: dict[str, type] = {}

        result = namedtuple_inspector(Empty)
        assert result is None


# ============================================================================
# is_structured_type
# ============================================================================


class TestIsStructuredType:
    def test_dataclass(self) -> None:
        @dataclass
        class Dc:
            x: int

        assert is_structured_type(Dc) is True

    def test_pydantic(self) -> None:
        from pydantic import BaseModel

        class M(BaseModel):
            x: int

        assert is_structured_type(M) is True

    def test_typeddict(self) -> None:
        class TD(TypedDict):
            x: int

        assert is_structured_type(TD) is True

    def test_namedtuple(self) -> None:
        class NT(NamedTuple):
            x: int

        assert is_structured_type(NT) is True

    def test_primitive(self) -> None:
        assert is_structured_type(str) is False
        assert is_structured_type(int) is False


# ============================================================================
# unwrap_collection
# ============================================================================


class TestUnwrapCollection:
    def test_list(self) -> None:
        @dataclass
        class Item:
            x: int

        result = unwrap_collection(list[Item])
        assert result is Item

    def test_set(self) -> None:
        result = unwrap_collection(set[int])
        assert result is int

    def test_frozenset(self) -> None:
        result = unwrap_collection(frozenset[str])
        assert result is str

    def test_homogeneous_tuple(self) -> None:
        result = unwrap_collection(tuple[int, ...])
        assert result is int

    def test_heterogeneous_tuple_no_unwrap(self) -> None:
        result = unwrap_collection(tuple[int, str])
        # Not homogeneous, returns original
        assert result == tuple[int, str]

    def test_not_collection(self) -> None:
        result = unwrap_collection(str)
        assert result is str


# ============================================================================
# get_nested_info / get_nested_type
# ============================================================================


class TestNestedHelpers:
    def test_get_nested_info_structured(self) -> None:
        fields = inspect_type(_OuterNested)
        nested = get_nested_info(fields["inner"])
        assert nested is not None
        assert "value" in nested

    def test_get_nested_info_collection(self) -> None:
        fields = inspect_type(_ContainerNested)
        nested = get_nested_info(fields["items"])
        assert nested is not None
        assert "name" in nested

    def test_get_nested_info_primitive(self) -> None:
        fields = inspect_type(_SimpleNested)
        nested = get_nested_info(fields["x"])
        assert nested is None

    def test_get_nested_type_structured(self) -> None:
        fields = inspect_type(_OuterNested)
        nested_type = get_nested_type(fields["inner"])
        assert nested_type is _InnerNested

    def test_get_nested_type_collection(self) -> None:
        fields = inspect_type(_ContainerNested)
        nested_type = get_nested_type(fields["items"])
        assert nested_type is _ItemNested

    def test_get_nested_type_primitive(self) -> None:
        fields = inspect_type(_SimpleNested)
        nested_type = get_nested_type(fields["x"])
        assert nested_type is None

"""Tests for derivelib._derive — @derive decorator and compilation pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from emergent.wire.axis.schema import Identity
from emergent.wire.axis.surface import Exposure

from derivelib._derive import (
    Pattern,
    derive,
    get_derivations,
    get_exposures,
    get_patterns,
)

from .conftest import User


class _DummyNode:
    pass


class TestDeriveDecorator:
    def test_stores_patterns(self) -> None:
        from derivelib.patterns.crud import http_crud

        pattern = http_crud("/api/users", provider_node=_DummyNode)

        @derive(pattern)
        @dataclass
        class TestEntity:
            id: Annotated[int, Identity]
            name: str

        patterns = get_patterns(TestEntity)
        assert len(patterns) == 1

    def test_returns_original_class(self) -> None:
        from derivelib.patterns.crud import http_crud

        pattern = http_crud("/api/users", provider_node=_DummyNode)

        @derive(pattern)
        @dataclass
        class TestEntity:
            id: Annotated[int, Identity]
            name: str

        instance = TestEntity(id=1, name="test")
        assert instance.name == "test"

    def test_empty_patterns(self) -> None:
        @dataclass
        class PlainEntity:
            id: int

        assert get_patterns(PlainEntity) == ()
        assert get_exposures(PlainEntity) == ()
        assert get_derivations(PlainEntity) == ()

    def test_multiple_patterns(self) -> None:
        from derivelib.patterns.crud import http_crud
        from derivelib.patterns.methods import methods

        @derive(
            http_crud("/api/items", provider_node=_DummyNode),
            methods,
        )
        @dataclass
        class MultiEntity:
            id: Annotated[int, Identity]
            name: str

        patterns = get_patterns(MultiEntity)
        assert len(patterns) == 2


class TestPatternProtocol:
    def test_isinstance_check(self) -> None:
        from derivelib.patterns.crud import http_crud

        pattern = http_crud("/api/users", provider_node=_DummyNode)
        assert isinstance(pattern, Pattern)

    def test_custom_pattern(self) -> None:
        from derivelib._derivation import Derivation
        from derivelib.axes.schema import inspect_entity

        @dataclass
        class MyPattern:
            def compile(self, entity: type) -> Derivation:
                return (inspect_entity(),)

        assert isinstance(MyPattern(), Pattern)


class TestDeriveEndpoints:
    def test_single_pattern(self) -> None:
        from derivelib._derive import derive_endpoints
        from derivelib.patterns.crud import http_crud

        @dataclass
        class Item:
            id: Annotated[int, Identity]
            name: str

        endpoints = derive_endpoints(
            Item,
            http_crud("/api/items", provider_node=_DummyNode),
        )
        assert len(endpoints) == 1
        assert len(endpoints[0].exposures) > 0

    def test_from_decorated(self) -> None:
        from derivelib._derive import derive_from_decorated
        from derivelib.patterns.crud import http_crud

        @derive(http_crud("/api/widgets", provider_node=_DummyNode))
        @dataclass
        class Widget:
            id: Annotated[int, Identity]
            name: str

        endpoints = derive_from_decorated(Widget)
        assert len(endpoints) == 1
        assert len(endpoints[0].exposures) > 0


class TestBuildApplication:
    def test_build_from_decorated(self) -> None:
        from derivelib._derive import build_application_from_decorated
        from derivelib.patterns.crud import http_crud

        @derive(http_crud("/api/things", provider_node=_DummyNode))
        @dataclass
        class Thing:
            id: Annotated[int, Identity]
            name: str

        app = build_application_from_decorated(Thing)
        assert app is not None
        assert len(app.endpoints) > 0

    def test_build_application(self) -> None:
        from derivelib._derive import build_application
        from derivelib.patterns.crud import http_crud

        @dataclass
        class Gadget:
            id: Annotated[int, Identity]
            label: str

        app = build_application(
            (Gadget, http_crud("/api/gadgets", provider_node=_DummyNode)),
        )
        assert app is not None

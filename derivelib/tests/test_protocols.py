"""Tests for derivelib._protocols — axis protocols and handler templates."""

from __future__ import annotations

from dataclasses import dataclass

from derivelib._ctx import QueryCtx, SchemaCtx, StorageCtx, SurfaceCtx
from derivelib._protocols import (
    HandlerSpec,
    QueryDerivable,
    SchemaDerivable,
    StorageDerivable,
    SurfaceDerivable,
    WrappedTemplate,
    wrap_template,
)

from .conftest import User, user_schema


class TestProtocolConformance:
    def test_schema_derivable(self) -> None:
        @dataclass
        class MyStep:
            def derive_schema(self, ctx: SchemaCtx[object]) -> SchemaCtx[object]:
                return ctx

        assert isinstance(MyStep(), SchemaDerivable)

    def test_query_derivable(self) -> None:
        @dataclass
        class MyStep:
            def derive_query(self, ctx: QueryCtx[object]) -> QueryCtx[object]:
                return ctx

        assert isinstance(MyStep(), QueryDerivable)

    def test_storage_derivable(self) -> None:
        @dataclass
        class MyStep:
            def derive_storage(self, ctx: StorageCtx[object]) -> StorageCtx[object]:
                return ctx

        assert isinstance(MyStep(), StorageDerivable)

    def test_surface_derivable(self) -> None:
        @dataclass
        class MyStep:
            def derive_surface(self, ctx: SurfaceCtx[object]) -> SurfaceCtx[object]:
                return ctx

        assert isinstance(MyStep(), SurfaceDerivable)

    def test_non_conforming(self) -> None:
        @dataclass
        class NotAStep:
            pass

        assert not isinstance(NotAStep(), SchemaDerivable)
        assert not isinstance(NotAStep(), QueryDerivable)


class TestHandlerSpec:
    def test_fields(self) -> None:
        spec = HandlerSpec(
            entity=User,
            entity_name="User",
            identity_names=("id",),
            non_identity_names=("name", "email"),
            base_query=None,
        )
        assert spec.entity is User
        assert spec.entity_name == "User"
        assert spec.identity_names == ("id",)
        assert spec.non_identity_names == ("name", "email")
        assert spec.base_query is None


class TestWrappedTemplate:
    def test_wraps_inner(self) -> None:
        from derivelib._protocols import HandlerTemplate

        @dataclass
        class MockTemplate:
            def build(self, spec: HandlerSpec[object]) -> object:
                async def handler(op: object) -> object:
                    return op
                return handler

        def wrapper(inner: object, spec: HandlerSpec[object]) -> object:
            async def wrapped_handler(op: object) -> object:
                return await inner(op)
            return wrapped_handler

        wt = WrappedTemplate(inner=MockTemplate(), wrapper=wrapper)
        spec = HandlerSpec(
            entity=User,
            entity_name="User",
            identity_names=("id",),
            non_identity_names=("name", "email"),
            base_query=None,
        )
        result = wt.build(spec)
        assert callable(result)

    def test_wrap_template_convenience(self) -> None:
        @dataclass
        class MockTemplate:
            def build(self, spec: HandlerSpec[object]) -> object:
                async def handler(op: object) -> object:
                    return op
                return handler

        def wrapper(inner: object, spec: HandlerSpec[object]) -> object:
            return inner

        wt = wrap_template(MockTemplate(), wrapper)
        assert isinstance(wt, WrappedTemplate)

"""Tests for derivelib._ctx — per-axis derivation contexts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

import pytest
from emergent.wire.axis.schema import Identity

from derivelib._ctx import (
    DerivationCtx,
    QueryCtx,
    SchemaCtx,
    StorageCtx,
    SurfaceCtx,
)

from .conftest import CompositeKey, NoIdentity, Post, User, user_schema


class TestSchemaCtxFromEntity:
    def test_detects_fields(self) -> None:
        ctx = SchemaCtx.from_entity(User)
        assert "id" in ctx.fields
        assert "name" in ctx.fields
        assert "email" in ctx.fields

    def test_detects_identity(self) -> None:
        ctx = SchemaCtx.from_entity(User)
        assert "id" in ctx.identity_fields
        assert len(ctx.identity_fields) == 1

    def test_composite_identity(self) -> None:
        ctx = SchemaCtx.from_entity(CompositeKey)
        assert "tenant_id" in ctx.identity_fields
        assert "user_id" in ctx.identity_fields
        assert len(ctx.identity_fields) == 2

    def test_no_identity(self) -> None:
        ctx = SchemaCtx.from_entity(NoIdentity)
        assert len(ctx.identity_fields) == 0

    def test_entity_type_preserved(self) -> None:
        ctx = SchemaCtx.from_entity(User)
        assert ctx.entity is User


class TestSchemaCtxHelpers:
    def test_identity_names(self) -> None:
        ctx = user_schema()
        assert ctx.identity_names() == ("id",)

    def test_identity_names_composite(self) -> None:
        ctx = SchemaCtx.from_entity(CompositeKey)
        names = ctx.identity_names()
        assert "tenant_id" in names
        assert "user_id" in names

    def test_non_identity_fields(self) -> None:
        ctx = user_schema()
        non_id = ctx.non_identity_fields()
        assert "name" in non_id
        assert "email" in non_id
        assert "id" not in non_id

    def test_field_types(self) -> None:
        ctx = user_schema()
        types = ctx.field_types()
        assert types["id"] is int
        assert types["name"] is str
        assert types["email"] is str

    def test_field_types_with_exclude(self) -> None:
        ctx = user_schema()
        types = ctx.field_types(exclude=("id",))
        assert "id" not in types
        assert "name" in types

    def test_annotated_field_types(self) -> None:
        ctx = user_schema()
        types = ctx.annotated_field_types()
        assert len(types) == 3

    def test_annotated_field_types_with_only(self) -> None:
        ctx = user_schema()
        types = ctx.annotated_field_types(only={"name", "email"})
        assert "name" in types
        assert "email" in types
        assert "id" not in types

    def test_annotated_field_types_with_exclude(self) -> None:
        ctx = user_schema()
        types = ctx.annotated_field_types(exclude=("id",))
        assert "id" not in types
        assert "name" in types


class TestSchemaCtxDefaultFields:
    def test_default_field_detected(self) -> None:
        ctx = SchemaCtx.from_entity(Post)
        assert ctx.fields["published"].has_default


class TestQueryCtx:
    def test_initial_state(self) -> None:
        schema = user_schema()
        ctx = QueryCtx(schema=schema)
        assert ctx.provider_node is None
        assert ctx.base_query is None

    def test_schema_reference(self) -> None:
        schema = user_schema()
        ctx = QueryCtx(schema=schema)
        assert ctx.schema is schema


class TestStorageCtx:
    def test_initial_state(self) -> None:
        schema = user_schema()
        ctx = StorageCtx(schema=schema)
        assert ctx.backend_node is None


class TestSurfaceCtx:
    def test_initial_state(self) -> None:
        schema = user_schema()
        ctx = SurfaceCtx(schema=schema)
        assert ctx.specs == ()
        assert ctx.operations == ()
        assert ctx.capabilities == ()

    def test_get_base_query_none(self) -> None:
        schema = user_schema()
        ctx = SurfaceCtx(schema=schema)
        assert ctx.get_base_query() is None

    def test_get_base_query_from_query_ctx(self) -> None:
        from emergent.wire.axis.query import relational

        schema = user_schema()
        q = relational(User)
        query_ctx = QueryCtx(schema=schema, base_query=q)
        ctx = SurfaceCtx(schema=schema, query=query_ctx)
        assert ctx.get_base_query() is q


class TestDerivationCtx:
    def test_bundles_all_axes(self) -> None:
        schema = user_schema()
        query = QueryCtx(schema=schema)
        storage = StorageCtx(schema=schema)
        surface = SurfaceCtx(schema=schema)
        ctx = DerivationCtx(
            schema=schema, query=query, storage=storage, surface=surface
        )
        assert ctx.schema is schema
        assert ctx.query is query
        assert ctx.storage is storage
        assert ctx.surface is surface

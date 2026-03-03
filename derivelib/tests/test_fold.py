"""Tests for derivelib._fold — fold_derive orchestration and materialize."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from emergent.wire.axis.schema import Identity

from derivelib._ctx import QueryCtx, SchemaCtx, StorageCtx, SurfaceCtx
from derivelib._fold import (
    QUERY_PHASE,
    SCHEMA_PHASE,
    STORAGE_PHASE,
    SURFACE_PHASE,
    DerivationPhase,
    fold_derive,
    materialize,
)
from derivelib._protocols import QueryDerivable, SchemaDerivable
from derivelib.axes.query import bind_provider, base_query
from derivelib.axes.schema import inspect_entity, require_identity

from .conftest import User, user_schema


class _ProviderNode:
    pass


class TestDerivationPhase:
    def test_schema_phase_method(self) -> None:
        assert SCHEMA_PHASE.method == "derive_schema"

    def test_query_phase_method(self) -> None:
        assert QUERY_PHASE.method == "derive_query"

    def test_storage_phase_method(self) -> None:
        assert STORAGE_PHASE.method == "derive_storage"

    def test_surface_phase_method(self) -> None:
        assert SURFACE_PHASE.method == "derive_surface"

    def test_invalid_protocol_raises(self) -> None:
        class BadProtocol:
            pass

        import pytest
        with pytest.raises(ValueError, match="No derive_"):
            DerivationPhase(SchemaCtx, BadProtocol)


class TestSchemaPhase:
    def test_fold_inspect(self) -> None:
        steps = (inspect_entity(),)
        result = SCHEMA_PHASE.fold(steps, SchemaCtx.from_entity(User))
        assert "id" in result.fields
        assert "name" in result.fields

    def test_fold_require_identity(self) -> None:
        steps = (inspect_entity(), require_identity())
        result = SCHEMA_PHASE.fold(steps, SchemaCtx.from_entity(User))
        assert len(result.identity_fields) == 1


class TestQueryPhase:
    def test_fold_bind_provider(self) -> None:
        steps = (bind_provider(_ProviderNode),)
        schema = user_schema()
        result = QUERY_PHASE.fold(steps, QueryCtx(schema=schema))
        assert result.provider_node is _ProviderNode

    def test_fold_base_query(self) -> None:
        steps = (base_query(),)
        schema = user_schema()
        result = QUERY_PHASE.fold(steps, QueryCtx(schema=schema))
        assert result.base_query is not None


class TestFoldDerive:
    def test_two_pass_orchestration(self) -> None:
        steps = (
            inspect_entity(),
            require_identity(),
            bind_provider(_ProviderNode),
            base_query(),
        )
        ctx = fold_derive(steps, User)
        assert ctx.schema.entity is User
        assert ctx.query.provider_node is _ProviderNode
        assert ctx.query.base_query is not None

    def test_schema_passes_to_query(self) -> None:
        steps = (inspect_entity(),)
        ctx = fold_derive(steps, User)
        assert ctx.query.schema is ctx.schema

    def test_empty_steps(self) -> None:
        ctx = fold_derive((), User)
        assert ctx.schema.entity is User
        assert ctx.surface.specs == ()


class TestMaterialize:
    def test_empty_returns_empty_endpoint(self) -> None:
        ctx = fold_derive((), User)
        endpoint = materialize(ctx)
        assert endpoint.exposures == ()

    def test_with_crud_pattern(self) -> None:
        from derivelib.patterns.crud import http_crud

        pattern = http_crud("/api/users", provider_node=_ProviderNode)
        derivation = pattern.compile(User)
        ctx = fold_derive(derivation, User)
        endpoint = materialize(ctx)
        assert len(endpoint.exposures) > 0

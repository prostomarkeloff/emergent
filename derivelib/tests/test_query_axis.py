"""Tests for derivelib.axes.query — query axis derivation steps."""

from __future__ import annotations

from derivelib._ctx import QueryCtx
from derivelib.axes.query import (
    BindProvider,
    SetBaseQuery,
    SetCustomBaseQuery,
    base_query,
    bind_provider,
    custom_base_query,
)

from .conftest import User, user_schema


class _DummyProviderNode:
    pass


class TestBindProvider:
    def test_sets_provider_node(self) -> None:
        schema = user_schema()
        ctx = QueryCtx(schema=schema)
        step = BindProvider(node_type=_DummyProviderNode)
        result = step.derive_query(ctx)
        assert result.provider_node is _DummyProviderNode

    def test_constructor(self) -> None:
        step = bind_provider(_DummyProviderNode)
        assert isinstance(step, BindProvider)
        assert step.node_type is _DummyProviderNode


class TestSetBaseQuery:
    def test_sets_base_query(self) -> None:
        schema = user_schema()
        ctx = QueryCtx(schema=schema)
        step = SetBaseQuery()
        result = step.derive_query(ctx)
        assert result.base_query is not None

    def test_constructor(self) -> None:
        step = base_query()
        assert isinstance(step, SetBaseQuery)


class TestSetCustomBaseQuery:
    def test_custom_factory(self) -> None:
        from emergent.wire.axis.query import relational

        schema = user_schema()
        ctx = QueryCtx(schema=schema)
        my_query = relational(User)

        step = SetCustomBaseQuery(query_factory=lambda entity: my_query)
        result = step.derive_query(ctx)
        assert result.base_query is my_query

    def test_constructor(self) -> None:
        from emergent.wire.axis.query import relational

        step = custom_base_query(lambda entity: relational(entity))
        assert isinstance(step, SetCustomBaseQuery)

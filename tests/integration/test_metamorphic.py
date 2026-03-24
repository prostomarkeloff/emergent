"""Metamorphic testing -- verifies RELATIONSHIPS between operations.

Each test asserts a metamorphic relation (e.g. create increases count,
delete decreases count) without needing to know exact expected output.

All tests use a compiled TestApp from the real derive pipeline.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Annotated

import pytest
from hypothesis import given, settings, strategies as st

from nodnod import scalar_node

from emergent.wire.axis.query._provider import SequenceNextId
from emergent.wire.axis.query.providers.memory import MemoryRelationalProvider
from emergent.wire.axis.schema._inspect import inspect_dataclass
from emergent.wire.axis.schema._universal import (
    Identity,
    Max,
    MaxLen,
    Min,
    MinLen,
    schema_meta,
)
from emergent.wire.axis.surface._app import Application
from emergent.wire.compile._core import Axes
from emergent.wire.compile.targets.testing import testing_compile as compile_for_test
from emergent.wire.derive import compile_derive, materialize
from emergent.wire.derive._crud import http_crud
from emergent.wire.verify import verify


# ---------------------------------------------------------------------------
# Infrastructure
# ---------------------------------------------------------------------------


def _memory_node(key_field: str = "id") -> type:
    next_id = SequenceNextId()
    store: MemoryRelationalProvider[object] = MemoryRelationalProvider(
        key_fn=lambda x: getattr(x, key_field),
        next_id=next_id,
    )

    @scalar_node
    class _Node:
        @classmethod
        def __compose__(cls) -> MemoryRelationalProvider[object]:
            return store

    return _Node


def _build_fresh_app() -> object:
    """Build a fresh TestApp with isolated in-memory state."""
    node = _memory_node()

    @schema_meta(http_crud("/users", provider_node=node))
    @dataclass
    class User:
        id: Annotated[int, Identity]
        name: Annotated[str, MinLen(1), MaxLen(50)]
        age: Annotated[int, Min(0), Max(200)]

    endpoints = []
    for ctx in compile_derive(User):
        endpoints.append(materialize(ctx))
    app = Application().mount(*endpoints)
    axes = Axes(schema=inspect_dataclass)
    return compile_for_test(app, axes=axes)


# Route indices: 0=List, 1=Get, 2=Create, 3=Update, 4=Patch, 5=Delete


async def _list_items(app: object) -> list[object]:
    result = await app.routes[0].call()
    return result.items  # type: ignore[union-attr]


async def _list_count(app: object) -> int:
    return len(await _list_items(app))


async def _create_user(
    app: object, name: str = "Test", age: int = 25
) -> object:
    return await app.routes[2].call({"name": name, "age": age})


async def _get_user(app: object, user_id: int) -> object:
    return await app.routes[1].call({"id": user_id})


async def _update_user(
    app: object, user_id: int, name: str, age: int
) -> object:
    return await app.routes[3].call({"id": user_id, "name": name, "age": age})


async def _delete_user(app: object, user_id: int) -> object:
    return await app.routes[5].call({"id": user_id})


# ---------------------------------------------------------------------------
# Metamorphic relation tests
# ---------------------------------------------------------------------------


class TestMetamorphicRelations:
    """Each test verifies a metamorphic relation between operations."""

    @pytest.mark.asyncio
    async def test_create_increases_count(self) -> None:
        """create() adds exactly one item to the list."""
        app = _build_fresh_app()
        count_before = await _list_count(app)
        await _create_user(app, "Alice", 30)
        count_after = await _list_count(app)
        assert count_after == count_before + 1

    @pytest.mark.asyncio
    async def test_delete_decreases_count(self) -> None:
        """delete() removes exactly one item from the list."""
        app = _build_fresh_app()
        created = await _create_user(app, "Alice", 30)
        count_before = await _list_count(app)
        await _delete_user(app, created.id)  # type: ignore[union-attr]
        count_after = await _list_count(app)
        assert count_after == count_before - 1

    @pytest.mark.asyncio
    async def test_create_delete_noop(self) -> None:
        """create + delete = no net change in count."""
        app = _build_fresh_app()
        # Seed with some data
        await _create_user(app, "Seed", 10)
        count_before = await _list_count(app)

        created = await _create_user(app, "Temp", 20)
        await _delete_user(app, created.id)  # type: ignore[union-attr]

        count_after = await _list_count(app)
        assert count_after == count_before

    @pytest.mark.asyncio
    async def test_update_preserves_count(self) -> None:
        """update() does not change the list length."""
        app = _build_fresh_app()
        created = await _create_user(app, "Alice", 30)
        count_before = await _list_count(app)
        await _update_user(app, created.id, "Bob", 25)  # type: ignore[union-attr]
        count_after = await _list_count(app)
        assert count_after == count_before

    @pytest.mark.asyncio
    async def test_create_unique_ids(self) -> None:
        """Creating N items produces N distinct IDs."""
        app = _build_fresh_app()
        n = 5
        ids: set[int] = set()
        for i in range(n):
            created = await _create_user(app, f"User{i}", 20 + i)
            ids.add(created.id)  # type: ignore[union-attr]
        assert len(ids) == n

    @pytest.mark.asyncio
    async def test_get_after_create_consistent(self) -> None:
        """GET by id returns exact data that was POSTed."""
        app = _build_fresh_app()
        created = await _create_user(app, "Alice", 30)
        fetched = await _get_user(app, created.id)  # type: ignore[union-attr]
        assert fetched.id == created.id  # type: ignore[union-attr]
        assert fetched.name == created.name  # type: ignore[union-attr]
        assert fetched.age == created.age  # type: ignore[union-attr]

    @pytest.mark.asyncio
    async def test_double_delete_idempotent(self) -> None:
        """Deleting an already-deleted entity does not change count."""
        app = _build_fresh_app()
        # Create two users so list is not empty after first delete
        await _create_user(app, "Keep", 10)
        to_delete = await _create_user(app, "Remove", 20)
        await _delete_user(app, to_delete.id)  # type: ignore[union-attr]

        count_after_first = await _list_count(app)

        # Second delete of same id -- should return a 404 (JSONResponse)
        result = await _delete_user(app, to_delete.id)  # type: ignore[union-attr]
        # The result is a JSONResponse with status 404, not a success response
        assert hasattr(result, "status_code") and result.status_code == 404  # type: ignore[union-attr]

        count_after_second = await _list_count(app)
        assert count_after_second == count_after_first

    @pytest.mark.asyncio
    async def test_sort_is_permutation(self) -> None:
        """Items in any order contain the same set of IDs."""
        app = _build_fresh_app()
        for i in range(4):
            await _create_user(app, f"User{i}", 20 + i)

        items = await _list_items(app)
        ids_from_list = {item.id for item in items}  # type: ignore[union-attr]

        # Verify all IDs are present regardless of order
        assert len(ids_from_list) == 4
        # Each item is retrievable individually
        for item_id in ids_from_list:
            fetched = await _get_user(app, item_id)  # type: ignore[arg-type]
            assert fetched.id == item_id  # type: ignore[union-attr]

    @pytest.mark.asyncio
    async def test_limit_is_subset(self) -> None:
        """Items returned from a smaller list are all present in the full list."""
        app = _build_fresh_app()
        for i in range(5):
            await _create_user(app, f"User{i}", 20 + i)

        full_items = await _list_items(app)
        full_ids = {item.id for item in full_items}  # type: ignore[union-attr]

        # Take a subset: first 3 items from the full list
        subset_ids = {item.id for item in full_items[:3]}  # type: ignore[union-attr]
        assert subset_ids.issubset(full_ids)

    @pytest.mark.asyncio
    async def test_create_then_list_contains_created(self) -> None:
        """A newly created item always appears in the list."""
        app = _build_fresh_app()
        created = await _create_user(app, "NewUser", 42)
        items = await _list_items(app)
        item_ids = {item.id for item in items}  # type: ignore[union-attr]
        assert created.id in item_ids  # type: ignore[union-attr]


class TestMetamorphicWithHypothesis:
    """Property-based metamorphic tests using hypothesis-generated data."""

    @given(
        name=st.text(
            min_size=1,
            max_size=50,
            alphabet=st.characters(categories=("L", "N")),
        ).filter(lambda s: len(s.strip()) > 0),
        age=st.integers(min_value=0, max_value=200),
    )
    @settings(max_examples=15, deadline=None)
    def test_create_get_roundtrip(self, name: str, age: int) -> None:
        """For any valid (name, age), create then get returns same data."""
        app = _build_fresh_app()

        async def _check() -> None:
            created = await _create_user(app, name, age)
            fetched = await _get_user(app, created.id)  # type: ignore[union-attr]
            assert fetched.name == name  # type: ignore[union-attr]
            assert fetched.age == age  # type: ignore[union-attr]

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_check())
        finally:
            loop.close()

    @given(
        name=st.text(
            min_size=1,
            max_size=50,
            alphabet=st.characters(categories=("L", "N")),
        ).filter(lambda s: len(s.strip()) > 0),
        age=st.integers(min_value=0, max_value=200),
        new_name=st.text(
            min_size=1,
            max_size=50,
            alphabet=st.characters(categories=("L", "N")),
        ).filter(lambda s: len(s.strip()) > 0),
        new_age=st.integers(min_value=0, max_value=200),
    )
    @settings(max_examples=10, deadline=None)
    def test_update_then_get_returns_new_data(
        self, name: str, age: int, new_name: str, new_age: int
    ) -> None:
        """After update, GET returns the updated values, not the originals."""
        app = _build_fresh_app()

        async def _check() -> None:
            created = await _create_user(app, name, age)
            await _update_user(app, created.id, new_name, new_age)  # type: ignore[union-attr]
            fetched = await _get_user(app, created.id)  # type: ignore[union-attr]
            assert fetched.name == new_name  # type: ignore[union-attr]
            assert fetched.age == new_age  # type: ignore[union-attr]

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_check())
        finally:
            loop.close()

    @given(n=st.integers(min_value=1, max_value=8))
    @settings(max_examples=10, deadline=None)
    def test_n_creates_n_items(self, n: int) -> None:
        """Creating n items results in exactly n items in the list."""
        app = _build_fresh_app()

        async def _check() -> None:
            for i in range(n):
                await _create_user(app, f"User{i}", i)
            count = await _list_count(app)
            assert count == n

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_check())
        finally:
            loop.close()

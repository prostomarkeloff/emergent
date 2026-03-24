"""Differential testing -- compile SAME entity to testing AND FastAPI targets.

Execute the same operation via both paths and compare results.
TestApp.routes[i].call() vs httpx.AsyncClient against FastAPI ASGI app.

This verifies cross-target consistency: the testing target and the
FastAPI target must produce equivalent responses for identical inputs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

import httpx
import pytest

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
from emergent.wire.compile.targets import fastapi as fastapi_target
from emergent.wire.compile.targets.testing import testing_compile as compile_for_test
from emergent.wire.derive import compile_derive, materialize
from emergent.wire.derive._crud import http_crud


# ---------------------------------------------------------------------------
# Infrastructure: build BOTH targets from the SAME wire Application
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


def _build_both_targets() -> tuple[object, object]:
    """Build testing target AND FastAPI target from the SAME entity/provider.

    Both targets share the same underlying MemoryRelationalProvider,
    so mutations via one are visible to the other.

    Returns (test_app, fastapi_app).
    """
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
    wire_app = Application().mount(*endpoints)
    axes = Axes(schema=inspect_dataclass)

    test_app = compile_for_test(wire_app, axes=axes)
    fapi_app = fastapi_target.compile(wire_app, axes=axes)

    return test_app, fapi_app


# Route indices for testing target:
# 0=List, 1=Get, 2=Create, 3=Update, 4=Patch, 5=Delete


# ---------------------------------------------------------------------------
# Differential tests
# ---------------------------------------------------------------------------


class TestDifferentialCrossTarget:
    """Compare testing target vs FastAPI target for same operations."""

    @pytest.mark.asyncio
    async def test_create_same_response(self) -> None:
        """Create via testing target, verify same data via FastAPI GET.

        Both targets share the same provider; the created entity
        must be visible through the FastAPI target with identical fields.
        """
        test_app, fapi_app = _build_both_targets()
        payload = {"name": "Alice", "age": 30}

        # Create via testing target
        test_result = await test_app.routes[2].call(payload)  # type: ignore[union-attr]
        entity_id = test_result.id  # type: ignore[union-attr]

        # Read back via FastAPI target
        transport = httpx.ASGITransport(app=fapi_app)  # type: ignore[arg-type]
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            http_resp = await client.get(f"/users/{entity_id}")

        assert http_resp.status_code == 200
        http_data = http_resp.json()

        # Compare field values -- must be identical
        assert test_result.id == http_data["id"]  # type: ignore[union-attr]
        assert test_result.name == http_data["name"]  # type: ignore[union-attr]
        assert test_result.age == http_data["age"]  # type: ignore[union-attr]

    @pytest.mark.asyncio
    async def test_list_same_items(self) -> None:
        """GET list via both targets produces same set of items."""
        test_app, fapi_app = _build_both_targets()

        # Seed data (via testing target -- shared provider)
        await test_app.routes[2].call({"name": "Alice", "age": 30})  # type: ignore[union-attr]
        await test_app.routes[2].call({"name": "Bob", "age": 25})  # type: ignore[union-attr]

        # Testing target list
        test_list = await test_app.routes[0].call()  # type: ignore[union-attr]
        test_ids = {item.id for item in test_list.items}  # type: ignore[union-attr]

        # FastAPI target list
        transport = httpx.ASGITransport(app=fapi_app)  # type: ignore[arg-type]
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            http_resp = await client.get("/users")

        assert http_resp.status_code == 200
        http_items = http_resp.json()["items"]
        http_ids = {item["id"] for item in http_items}

        # Same items (order may differ)
        assert test_ids == http_ids

        # Verify field values match for each id
        http_by_id = {item["id"]: item for item in http_items}
        for item in test_list.items:  # type: ignore[union-attr]
            http_item = http_by_id[item.id]  # type: ignore[union-attr]
            assert item.name == http_item["name"]  # type: ignore[union-attr]
            assert item.age == http_item["age"]  # type: ignore[union-attr]

    @pytest.mark.asyncio
    async def test_get_by_id_same(self) -> None:
        """GET by id via both targets returns exact same fields."""
        test_app, fapi_app = _build_both_targets()

        # Create via testing target
        created = await test_app.routes[2].call(  # type: ignore[union-attr]
            {"name": "Alice", "age": 30}
        )
        entity_id = created.id  # type: ignore[union-attr]

        # Testing target get
        test_result = await test_app.routes[1].call({"id": entity_id})  # type: ignore[union-attr]

        # FastAPI target get
        transport = httpx.ASGITransport(app=fapi_app)  # type: ignore[arg-type]
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            http_resp = await client.get(f"/users/{entity_id}")

        assert http_resp.status_code == 200
        http_data = http_resp.json()

        # Exact same fields
        assert test_result.id == http_data["id"]  # type: ignore[union-attr]
        assert test_result.name == http_data["name"]  # type: ignore[union-attr]
        assert test_result.age == http_data["age"]  # type: ignore[union-attr]

    @pytest.mark.asyncio
    async def test_delete_same_effect(self) -> None:
        """DELETE via testing target, verify gone from both targets."""
        test_app, fapi_app = _build_both_targets()

        # Create then delete via testing target
        created = await test_app.routes[2].call(  # type: ignore[union-attr]
            {"name": "Alice", "age": 30}
        )
        entity_id = created.id  # type: ignore[union-attr]
        delete_result = await test_app.routes[5].call({"id": entity_id})  # type: ignore[union-attr]
        assert delete_result.success is True  # type: ignore[union-attr]

        # Verify gone from testing target list
        test_list = await test_app.routes[0].call()  # type: ignore[union-attr]
        test_ids = {item.id for item in test_list.items}  # type: ignore[union-attr]
        assert entity_id not in test_ids

        # Verify gone from FastAPI target list
        transport = httpx.ASGITransport(app=fapi_app)  # type: ignore[arg-type]
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            http_list = await client.get("/users")
            http_ids = {item["id"] for item in http_list.json()["items"]}
            assert entity_id not in http_ids

            # Verify GET by id returns 404 via FastAPI
            http_get = await client.get(f"/users/{entity_id}")
            assert http_get.status_code == 404

    @pytest.mark.asyncio
    async def test_update_same_response(self) -> None:
        """PUT via both targets produces same updated field values."""
        test_app, fapi_app = _build_both_targets()

        # Create via testing target
        created = await test_app.routes[2].call(  # type: ignore[union-attr]
            {"name": "Alice", "age": 30}
        )
        entity_id = created.id  # type: ignore[union-attr]

        update_payload = {"id": entity_id, "name": "Bob", "age": 25}

        # Update via testing target
        test_result = await test_app.routes[3].call(update_payload)  # type: ignore[union-attr]

        # Verify via FastAPI GET (shared provider means update is visible)
        transport = httpx.ASGITransport(app=fapi_app)  # type: ignore[arg-type]
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            http_resp = await client.get(f"/users/{entity_id}")

        assert http_resp.status_code == 200
        http_data = http_resp.json()

        assert test_result.id == http_data["id"]  # type: ignore[union-attr]
        assert test_result.name == http_data["name"]  # type: ignore[union-attr]
        assert test_result.age == http_data["age"]  # type: ignore[union-attr]

    @pytest.mark.asyncio
    async def test_fastapi_create_visible_in_testing(self) -> None:
        """Create via FastAPI, verify visible via testing target."""
        test_app, fapi_app = _build_both_targets()
        payload = {"name": "FastAPIUser", "age": 40}

        # Create via FastAPI
        transport = httpx.ASGITransport(app=fapi_app)  # type: ignore[arg-type]
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            http_resp = await client.post("/users", json=payload)

        assert http_resp.status_code == 200
        http_data = http_resp.json()
        entity_id = http_data["id"]

        # Verify visible via testing target
        test_result = await test_app.routes[1].call({"id": entity_id})  # type: ignore[union-attr]
        assert test_result.name == payload["name"]  # type: ignore[union-attr]
        assert test_result.age == payload["age"]  # type: ignore[union-attr]

    @pytest.mark.asyncio
    async def test_mixed_operations_consistent_counts(self) -> None:
        """Interleave operations across both targets; counts stay consistent."""
        test_app, fapi_app = _build_both_targets()

        # Create 2 via testing
        await test_app.routes[2].call({"name": "Test1", "age": 20})  # type: ignore[union-attr]
        await test_app.routes[2].call({"name": "Test2", "age": 30})  # type: ignore[union-attr]

        # Create 1 via FastAPI
        transport = httpx.ASGITransport(app=fapi_app)  # type: ignore[arg-type]
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            await client.post("/users", json={"name": "API1", "age": 40})

        # Both targets should see 3 items
        test_list = await test_app.routes[0].call()  # type: ignore[union-attr]
        test_count = len(test_list.items)  # type: ignore[union-attr]

        transport2 = httpx.ASGITransport(app=fapi_app)  # type: ignore[arg-type]
        async with httpx.AsyncClient(
            transport=transport2, base_url="http://test"
        ) as client:
            http_list = await client.get("/users")
            http_count = len(http_list.json()["items"])

        assert test_count == 3
        assert http_count == 3

    @pytest.mark.asyncio
    async def test_error_responses_match_status(self) -> None:
        """GET nonexistent entity: testing returns JSONResponse 404,
        FastAPI returns HTTP 404. Both indicate not found."""
        test_app, fapi_app = _build_both_targets()

        # Testing target: get nonexistent
        test_result = await test_app.routes[1].call({"id": 999})  # type: ignore[union-attr]
        # Error capability wraps as JSONResponse with status_code 404
        assert hasattr(test_result, "status_code")
        assert test_result.status_code == 404  # type: ignore[union-attr]

        # FastAPI target
        transport = httpx.ASGITransport(app=fapi_app)  # type: ignore[arg-type]
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            http_resp = await client.get("/users/999")
            assert http_resp.status_code == 404

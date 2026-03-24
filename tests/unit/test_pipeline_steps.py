"""Tests for composable handler pipeline steps.

Tests cover:
1. Individual step behavior with mock PipelineContext
2. Pipeline compositions matching monolithic template behavior
3. Early exit (FetchOrNotFound -> Error)
4. Pipeline + WrappedTemplate coexistence
5. Explain system detecting Pipeline
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

import pytest
from kungfu import Error, Ok

from emergent.wire.axis.query import relational
from emergent.wire.axis.query.providers.memory import MemoryRelationalProvider
from emergent.wire.axis.schema._universal import Identity
from emergent.wire.derive._errors import NotFound
from emergent.wire.derive._handler import (
    FetchMany,
    FetchOneById,
    HandlerSpec,
    HandlerTemplate,
    InsertNew,
    WrappedTemplate,
)
from emergent.wire.derive._pipeline import (
    BuildEntityData,
    CopyExistingToData,
    CountTotal,
    FetchAll,
    FetchByIdentity,
    FetchOrNotFound,
    IdentityFilter,
    InMemorySort,
    MergeFields,
    Paginate,
    PatchMergeFields,
    Pipeline,
    PipelineStep,
    ProviderDelete,
    ProviderInsert,
    ProviderUpdate,
    ScopeQuery,
    SetFieldValue,
    SetTimestamp,
    WrapCount,
    WrapExists,
    WrapItems,
    WrapOk,
    WrapPaginated,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Test Entity + Provider Setup
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class Item:
    id: Annotated[int, Identity()]
    name: str
    status: str = "active"


def make_spec(
    base_query=None,
    scope_fields: tuple[str, ...] = (),
) -> HandlerSpec[Item]:
    return HandlerSpec(
        entity=Item,
        entity_name="Item",
        identity_names=("id",),
        non_identity_names=("name", "status"),
        base_query=base_query or relational(Item),
        scope_fields=scope_fields,
    )


@dataclass
class MockOp:
    """Mock op with provider + arbitrary fields."""
    provider: MemoryRelationalProvider[Item]
    id: int = 0
    name: str = ""
    status: str = "active"


# ═══════════════════════════════════════════════════════════════════════════════
# Core: Pipeline protocol compliance
# ═══════════════════════════════════════════════════════════════════════════════


class TestPipelineProtocol:
    def test_pipeline_satisfies_handler_template(self):
        p = Pipeline(ScopeQuery(), FetchAll(), WrapItems())
        assert isinstance(p, HandlerTemplate)

    def test_pipeline_is_frozen(self):
        p = Pipeline(ScopeQuery())
        with pytest.raises((AttributeError, TypeError)):
            p.steps = ()  # type: ignore[misc]

    def test_pipeline_step_protocol(self):
        assert isinstance(ScopeQuery(), PipelineStep)
        assert isinstance(FetchAll(), PipelineStep)
        assert isinstance(WrapOk(), PipelineStep)
        assert isinstance(SetTimestamp("ts"), PipelineStep)


# ═══════════════════════════════════════════════════════════════════════════════
# FetchMany equivalence
# ═══════════════════════════════════════════════════════════════════════════════


class TestFetchManyPipeline:
    @pytest.mark.asyncio
    async def test_fetch_many_empty(self):
        prov = MemoryRelationalProvider[Item]()
        spec = make_spec()
        op = MockOp(provider=prov)

        monolithic = FetchMany().build(spec)
        pipeline = Pipeline(ScopeQuery(), FetchAll(), WrapItems()).build(spec)

        mono_result = await monolithic(op)
        pipe_result = await pipeline(op)

        assert isinstance(mono_result, Ok)
        assert isinstance(pipe_result, Ok)
        assert mono_result.value == pipe_result.value == []

    @pytest.mark.asyncio
    async def test_fetch_many_with_items(self):
        prov = MemoryRelationalProvider[Item]()
        await prov.insert(Item(id=1, name="a"))
        await prov.insert(Item(id=2, name="b"))

        spec = make_spec()
        op = MockOp(provider=prov)

        monolithic = FetchMany().build(spec)
        pipeline = Pipeline(ScopeQuery(), FetchAll(), WrapItems()).build(spec)

        mono_result = await monolithic(op)
        pipe_result = await pipeline(op)

        assert isinstance(mono_result, Ok)
        assert isinstance(pipe_result, Ok)
        assert len(mono_result.value) == len(pipe_result.value) == 2


# ═══════════════════════════════════════════════════════════════════════════════
# FetchOneById equivalence
# ═══════════════════════════════════════════════════════════════════════════════


class TestFetchOneByIdPipeline:
    @pytest.mark.asyncio
    async def test_found(self):
        prov = MemoryRelationalProvider[Item]()
        await prov.insert(Item(id=1, name="test"))

        spec = make_spec()
        op = MockOp(provider=prov, id=1)

        monolithic = FetchOneById().build(spec)
        pipeline = Pipeline(
            ScopeQuery(), IdentityFilter(), FetchOrNotFound(), WrapOk()
        ).build(spec)

        mono_result = await monolithic(op)
        pipe_result = await pipeline(op)

        assert isinstance(mono_result, Ok)
        assert isinstance(pipe_result, Ok)
        assert mono_result.value.name == pipe_result.value.name == "test"

    @pytest.mark.asyncio
    async def test_not_found(self):
        prov = MemoryRelationalProvider[Item]()
        spec = make_spec()
        op = MockOp(provider=prov, id=999)

        monolithic = FetchOneById().build(spec)
        pipeline = Pipeline(
            ScopeQuery(), IdentityFilter(), FetchOrNotFound(), WrapOk()
        ).build(spec)

        mono_result = await monolithic(op)
        pipe_result = await pipeline(op)

        assert isinstance(mono_result, Error)
        assert isinstance(pipe_result, Error)
        assert isinstance(mono_result.error, NotFound)
        assert isinstance(pipe_result.error, NotFound)


# ═══════════════════════════════════════════════════════════════════════════════
# InsertNew equivalence
# ═══════════════════════════════════════════════════════════════════════════════


class TestInsertNewPipeline:
    @pytest.mark.asyncio
    async def test_insert(self):
        spec = make_spec()

        prov1 = MemoryRelationalProvider[Item]()
        op1 = MockOp(provider=prov1, id=1, name="new_item", status="active")
        monolithic = InsertNew().build(spec)
        mono_result = await monolithic(op1)

        prov2 = MemoryRelationalProvider[Item]()
        op2 = MockOp(provider=prov2, id=1, name="new_item", status="active")
        pipeline = Pipeline(BuildEntityData(), ProviderInsert(), WrapOk()).build(spec)
        pipe_result = await pipeline(op2)

        assert isinstance(mono_result, Ok)
        assert isinstance(pipe_result, Ok)
        assert mono_result.value.name == pipe_result.value.name == "new_item"


# ═══════════════════════════════════════════════════════════════════════════════
# UpdateExisting equivalence
# ═══════════════════════════════════════════════════════════════════════════════


class TestUpdateExistingPipeline:
    @pytest.mark.asyncio
    async def test_update(self):
        spec = make_spec()

        prov1 = MemoryRelationalProvider[Item](key_fn=lambda i: i.id)
        await prov1.insert(Item(id=1, name="old"))
        op1 = MockOp(provider=prov1, id=1, name="updated")

        prov2 = MemoryRelationalProvider[Item](key_fn=lambda i: i.id)
        await prov2.insert(Item(id=1, name="old"))
        op2 = MockOp(provider=prov2, id=1, name="updated")

        from emergent.wire.derive._handler import UpdateExisting

        monolithic = UpdateExisting().build(spec)
        pipeline = Pipeline(
            ScopeQuery(), IdentityFilter(), FetchOrNotFound(),
            MergeFields(), ProviderUpdate(), WrapOk(),
        ).build(spec)

        mono_result = await monolithic(op1)
        pipe_result = await pipeline(op2)

        assert isinstance(mono_result, Ok)
        assert isinstance(pipe_result, Ok)
        assert mono_result.value.name == pipe_result.value.name == "updated"

    @pytest.mark.asyncio
    async def test_update_not_found(self):
        prov = MemoryRelationalProvider[Item]()
        spec = make_spec()
        op = MockOp(provider=prov, id=999, name="x")

        pipeline = Pipeline(
            ScopeQuery(), IdentityFilter(), FetchOrNotFound(),
            MergeFields(), ProviderUpdate(), WrapOk(),
        ).build(spec)

        result = await pipeline(op)
        assert isinstance(result, Error)
        assert isinstance(result.error, NotFound)


# ═══════════════════════════════════════════════════════════════════════════════
# DeleteOne equivalence
# ═══════════════════════════════════════════════════════════════════════════════


class TestDeleteOnePipeline:
    @pytest.mark.asyncio
    async def test_delete(self):
        prov = MemoryRelationalProvider[Item](key_fn=lambda i: i.id)
        await prov.insert(Item(id=1, name="doomed"))

        spec = make_spec()
        op = MockOp(provider=prov, id=1)

        pipeline = Pipeline(
            ScopeQuery(), IdentityFilter(), FetchOrNotFound(),
            ProviderDelete(), WrapOk(),
        ).build(spec)

        result = await pipeline(op)
        assert isinstance(result, Ok)
        assert result.value.name == "doomed"

        remaining = await prov.fetch_many(relational(Item))
        assert len(remaining) == 0


# ═══════════════════════════════════════════════════════════════════════════════
# PatchExisting equivalence
# ═══════════════════════════════════════════════════════════════════════════════


class TestPatchExistingPipeline:
    @pytest.mark.asyncio
    async def test_patch_partial(self):
        prov = MemoryRelationalProvider[Item](key_fn=lambda i: i.id)
        await prov.insert(Item(id=1, name="original", status="active"))

        spec = make_spec()

        @dataclass
        class PatchOp:
            provider: MemoryRelationalProvider[Item]
            id: int = 1
            name: str = "patched"
            # status present but unchanged — PatchMerge should keep existing

        op = PatchOp(provider=prov)

        pipeline = Pipeline(
            ScopeQuery(), IdentityFilter(), FetchOrNotFound(),
            PatchMergeFields(), ProviderUpdate(), WrapOk(),
        ).build(spec)

        result = await pipeline(op)
        assert isinstance(result, Ok)
        assert result.value.name == "patched"
        assert result.value.status == "active"


# ═══════════════════════════════════════════════════════════════════════════════
# SortedFetchMany equivalence
# ═══════════════════════════════════════════════════════════════════════════════


class TestSortedFetchManyPipeline:
    @pytest.mark.asyncio
    async def test_sort_asc(self):
        prov = MemoryRelationalProvider[Item]()
        await prov.insert(Item(id=1, name="banana"))
        await prov.insert(Item(id=2, name="apple"))
        await prov.insert(Item(id=3, name="cherry"))

        spec = make_spec()

        @dataclass
        class SortOp:
            provider: MemoryRelationalProvider[Item]
            sort: str = "name"
            order: str = "asc"

        op = SortOp(provider=prov)

        pipeline = Pipeline(
            ScopeQuery(), FetchAll(),
            InMemorySort(default_sort="name"), WrapItems(),
        ).build(spec)

        result = await pipeline(op)
        assert isinstance(result, Ok)
        names = [item.name for item in result.value]
        assert names == ["apple", "banana", "cherry"]

    @pytest.mark.asyncio
    async def test_sort_desc(self):
        prov = MemoryRelationalProvider[Item]()
        await prov.insert(Item(id=1, name="a"))
        await prov.insert(Item(id=2, name="b"))

        spec = make_spec()

        @dataclass
        class SortOp:
            provider: MemoryRelationalProvider[Item]
            sort: str = "name"
            order: str = "desc"

        op = SortOp(provider=prov)

        pipeline = Pipeline(
            ScopeQuery(), FetchAll(),
            InMemorySort(), WrapItems(),
        ).build(spec)

        result = await pipeline(op)
        assert isinstance(result, Ok)
        names = [item.name for item in result.value]
        assert names == ["b", "a"]


# ═══════════════════════════════════════════════════════════════════════════════
# CountAll equivalence
# ═══════════════════════════════════════════════════════════════════════════════


class TestCountAllPipeline:
    @pytest.mark.asyncio
    async def test_count(self):
        prov = MemoryRelationalProvider[Item]()
        await prov.insert(Item(id=1, name="a"))
        await prov.insert(Item(id=2, name="b"))

        spec = make_spec()
        op = MockOp(provider=prov)

        pipeline = Pipeline(ScopeQuery(), CountTotal(), WrapCount()).build(spec)

        result = await pipeline(op)
        assert isinstance(result, Ok)
        assert result.value == 2


# ═══════════════════════════════════════════════════════════════════════════════
# ExistsById equivalence
# ═══════════════════════════════════════════════════════════════════════════════


class TestExistsByIdPipeline:
    @pytest.mark.asyncio
    async def test_exists(self):
        prov = MemoryRelationalProvider[Item]()
        await prov.insert(Item(id=1, name="a"))

        spec = make_spec()
        op = MockOp(provider=prov, id=1)

        pipeline = Pipeline(FetchByIdentity(), WrapExists()).build(spec)
        result = await pipeline(op)
        assert isinstance(result, Ok)
        assert result.value is True

    @pytest.mark.asyncio
    async def test_not_exists(self):
        prov = MemoryRelationalProvider[Item]()
        spec = make_spec()
        op = MockOp(provider=prov, id=999)

        pipeline = Pipeline(FetchByIdentity(), WrapExists()).build(spec)
        result = await pipeline(op)
        assert isinstance(result, Ok)
        assert result.value is False


# ═══════════════════════════════════════════════════════════════════════════════
# SetTimestamp
# ═══════════════════════════════════════════════════════════════════════════════


class TestSetTimestampPipeline:
    @pytest.mark.asyncio
    async def test_timestamp_insert(self):
        from datetime import datetime

        @dataclass
        class TsItem:
            id: Annotated[int, Identity()]
            name: str
            created_at: datetime | None = None
            updated_at: datetime | None = None

        ts_spec = HandlerSpec(
            entity=TsItem,
            entity_name="TsItem",
            identity_names=("id",),
            non_identity_names=("name", "created_at", "updated_at"),
            base_query=relational(TsItem),
        )

        prov = MemoryRelationalProvider[TsItem]()

        @dataclass
        class TsOp:
            provider: MemoryRelationalProvider[TsItem]
            id: int = 1
            name: str = "timestamped"

        op = TsOp(provider=prov)

        pipeline = Pipeline(
            BuildEntityData(),
            SetTimestamp("created_at"),
            SetTimestamp("updated_at"),
            ProviderInsert(),
            WrapOk(),
        ).build(ts_spec)

        result = await pipeline(op)
        assert isinstance(result, Ok)
        assert result.value.name == "timestamped"
        assert isinstance(result.value.created_at, datetime)
        assert isinstance(result.value.updated_at, datetime)


# ═══════════════════════════════════════════════════════════════════════════════
# SetFieldValue
# ═══════════════════════════════════════════════════════════════════════════════


class TestSetFieldValuePipeline:
    @pytest.mark.asyncio
    async def test_set_field(self):
        prov = MemoryRelationalProvider[Item](key_fn=lambda i: i.id)
        await prov.insert(Item(id=1, name="x", status="active"))

        spec = make_spec()
        op = MockOp(provider=prov, id=1)

        pipeline = Pipeline(
            FetchByIdentity(),
            CopyExistingToData(),
            SetFieldValue("status", lambda _op: "archived"),
            ProviderUpdate(),
            WrapOk(),
        ).build(spec)

        result = await pipeline(op)
        assert isinstance(result, Ok)
        assert result.value.status == "archived"


# ═══════════════════════════════════════════════════════════════════════════════
# PaginatedFetchMany equivalence
# ═══════════════════════════════════════════════════════════════════════════════


class TestPaginatedFetchManyPipeline:
    @pytest.mark.asyncio
    async def test_paginated(self):
        prov = MemoryRelationalProvider[Item]()
        for i in range(5):
            await prov.insert(Item(id=i + 1, name=f"item{i}"))

        spec = make_spec()

        @dataclass
        class PageOp:
            provider: MemoryRelationalProvider[Item]
            page: int = 1
            page_size: int = 2

        op = PageOp(provider=prov)

        pipeline = Pipeline(
            ScopeQuery(), CountTotal(), Paginate(default_page_size=2),
            FetchAll(), WrapPaginated(default_page_size=2),
        ).build(spec)

        result = await pipeline(op)
        assert isinstance(result, Ok)
        data = result.value
        assert data["total"] == 5
        assert data["page"] == 1
        assert data["page_size"] == 2
        assert len(data["items"]) == 2


# ═══════════════════════════════════════════════════════════════════════════════
# Pipeline + WrappedTemplate coexistence
# ═══════════════════════════════════════════════════════════════════════════════


class TestPipelineWrappedTemplate:
    @pytest.mark.asyncio
    async def test_wrap_pipeline(self):
        """Pipeline can be inner of WrappedTemplate."""
        prov = MemoryRelationalProvider[Item]()
        await prov.insert(Item(id=1, name="a"))
        await prov.insert(Item(id=2, name="b"))

        spec = make_spec()
        op = MockOp(provider=prov)

        def reverse_wrapper(inner, _spec):
            async def handler(op):
                result = await inner(op=op)
                if isinstance(result, Ok) and isinstance(result.value, list):
                    return Ok(list(reversed(result.value)))
                return result
            return handler

        wrapped = WrappedTemplate(
            inner=Pipeline(ScopeQuery(), FetchAll(), WrapItems()),
            wrapper=reverse_wrapper,
        )

        handler = wrapped.build(spec)
        result = await handler(op)
        assert isinstance(result, Ok)
        assert result.value[0].name == "b"
        assert result.value[1].name == "a"


# ═══════════════════════════════════════════════════════════════════════════════
# Explain integration
# ═══════════════════════════════════════════════════════════════════════════════


class TestPipelineExplain:
    def test_handler_info_pipeline(self):
        from emergent.wire.derive._explain import _handler_info

        p = Pipeline(ScopeQuery(), FetchAll(), WrapItems())
        info = _handler_info(p)
        assert isinstance(info, dict)
        assert info["type"] == "Pipeline"
        assert info["steps"] == ["ScopeQuery", "FetchAll", "WrapItems"]

    def test_handler_info_monolithic(self):
        from emergent.wire.derive._explain import _handler_info

        info = _handler_info(FetchMany())
        assert info == "FetchMany"

    def test_handler_info_wrapped_pipeline(self):
        from emergent.wire.derive._explain import _handler_info

        wrapped = WrappedTemplate(
            inner=Pipeline(ScopeQuery(), FetchAll(), WrapItems()),
            wrapper=lambda i, s: i,
        )
        info = _handler_info(wrapped)
        assert isinstance(info, dict)
        assert info["type"] == "WrappedTemplate"
        assert info["inner"]["type"] == "Pipeline"


# ═══════════════════════════════════════════════════════════════════════════════
# Early exit behavior
# ═══════════════════════════════════════════════════════════════════════════════


class TestEarlyExit:
    @pytest.mark.asyncio
    async def test_fetch_or_not_found_stops_pipeline(self):
        """Steps after FetchOrNotFound should NOT execute on miss."""
        prov = MemoryRelationalProvider[Item]()
        spec = make_spec()
        op = MockOp(provider=prov, id=999)

        # If MergeFields runs, it would fail (no existing). But it shouldn't run.
        pipeline = Pipeline(
            ScopeQuery(), IdentityFilter(), FetchOrNotFound(),
            MergeFields(), ProviderUpdate(), WrapOk(),
        ).build(spec)

        result = await pipeline(op)
        assert isinstance(result, Error)
        assert isinstance(result.error, NotFound)

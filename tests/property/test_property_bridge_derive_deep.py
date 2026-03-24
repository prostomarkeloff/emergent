# pyright: reportPrivateUsage=false
"""Deep coverage tests for derive handler, pipeline, methods, bridge capabilities,
FastAPI extractors, and handler introspection.

Covers:
- derive/_handler.py — handler template materialization, all CRUD + enriched templates
- derive/_pipeline.py — composable pipeline steps end-to-end
- derive/patterns/methods.py — method decorators, Methods/MethodDialect
- bridge/_capabilities.py — BridgeContext, fold_bridge, purifiers, compilable caps
- bridge/bridgers/fastapi/_capabilities.py — InferFromFastAPI, MapDepends, parse_fastapi_handler
- bridge/bridgers/fastapi/_extractors.py — HTTP/WS/Lifespan/Exception extractors
- bridge/_introspect.py — analyze_handler, unwrap, ParameterKind, InstanceInfo
"""

from __future__ import annotations

import asyncio
import functools
import inspect
from collections.abc import Sequence
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from functools import partial
from typing import Annotated, cast

import pytest
from kungfu import Error, Ok, Result

from emergent.wire.axis.query import (
    MemoryRelationalProvider,
    RelationalQuerySet,
    SequenceNextId,
    relational,
)
from emergent.wire.axis.schema._universal import Identity, schema_meta
from emergent.wire.bridge._capabilities import (
    BridgeCapability,
    BridgeContext,
    CatchErrors,
    IncludeOnlyByName,
    InjectKwarg,
    InjectKwargAsync,
    SetCodecByName,
    SetRequestTypeByName,
    SetResponseTypeByName,
    SetupTeardown,
    SkipByName,
    SkipDeprecated,
    WithContext,
    WithContextSync,
    WrapAsync,
    apply_purifiers,
    chain_purifiers,
    ensure_async,
    find_all_bridge_capabilities,
    find_bridge_capability,
    fold_bridge,
)
from emergent.wire.bridge._core import WireData
from emergent.wire.bridge._introspect import (
    ClosureFallbackUnwrap,
    DecoratorInfo,
    ParameterKind,
    ParameterShape,
    analyze_handler,
    extract_class_methods,
    get_view_class,
    no_default,
    resolve_descriptor,
    unwrap_handler,
)
from emergent.wire.bridge.bridgers.fastapi._extractors import (
    ExceptionHandlerExtractor,
    HTTPRouteExtractor,
    LifespanExtractor,
    WebSocketExtractor,
    is_fastapi_app,
)
from emergent.wire.bridge.bridgers.fastapi._capabilities import (
    InferFromFastAPI,
    MapDepends,
    parse_fastapi_handler,
    _get_fastapi_marker,
    _is_depends,
    _is_pydantic_model,
    _is_dataclass_type,
    _is_special_fastapi_type,
    _parse_handler_params,
)
from emergent.wire.bridge.bridgers.fastapi._routes import (
    HTTPRouteData,
)
from emergent.wire.derive._compile import compile_derive
from emergent.wire.derive._ctx import DeriveCtx
from emergent.wire.derive._errors import DomainError
from emergent.wire.derive._handler import (
    CachedFetchOneById,
    CountAll,
    DeleteOne,
    ExistsById,
    FetchMany,
    FetchOneById,
    HandlerSpec,
    InsertNew,
    PaginatedFetchMany,
    PatchExisting,
    SetField,
    SoftDeleteMark,
    SortedFetchMany,
    TimestampInsert,
    TimestampUpdate,
    UpdateExisting,
    UpsertExisting,
    WrappedTemplate,
    wrap_template,
)
from emergent.wire.derive._materialize import materialize
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
from emergent.wire.derive.patterns.methods import (
    Methods,
    command,
    delete,
    get,
    op,
    patch,
    post,
    put,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Test entities
# ═══════════════════════════════════════════════════════════════════════════════


class Items:
    """Provider node stub."""


@dataclass
class Item:
    id: Annotated[int, Identity()]
    name: str
    price: float


@dataclass
class TimedItem:
    id: Annotated[int, Identity()]
    name: str
    created_at: str | None = None
    updated_at: str | None = None


@dataclass
class SoftItem:
    id: Annotated[int, Identity()]
    name: str
    deleted_at: str | None = None


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _run(coro: object) -> object:
    """Run coroutine synchronously."""
    return asyncio.run(coro)  # type: ignore[arg-type]


def _make_spec(
    entity: type,
    *,
    base_query: RelationalQuerySet[object] | None = None,
    scope_fields: tuple[str, ...] = (),
) -> HandlerSpec[object]:
    """Build HandlerSpec for testing handler templates."""
    import dataclasses

    fields = dataclasses.fields(entity)
    id_names = tuple(
        f.name for f in fields
        if "Identity" in str(f.type)
    )
    non_id_names = tuple(f.name for f in fields if f.name not in id_names)
    return HandlerSpec(
        entity=entity,
        entity_name=entity.__name__,
        identity_names=id_names,
        non_identity_names=non_id_names,
        base_query=base_query if base_query is not None else relational(entity),
        scope_fields=scope_fields,
    )


def _make_provider(
    entity: type,
    initial: Sequence[object] | None = None,
    *,
    with_next_id: bool = False,
) -> MemoryRelationalProvider[object]:
    """Build a MemoryRelationalProvider with optional initial data."""
    next_id = SequenceNextId() if with_next_id else None
    return MemoryRelationalProvider(
        list(initial) if initial else [],
        key_fn=lambda e: getattr(e, "id", None),
        next_id=next_id,
    )


def _make_op(provider: MemoryRelationalProvider[object], **kwargs: object) -> object:
    """Build a simple op namespace with provider + kwargs."""
    ns = type("Op", (), {"provider": provider, **kwargs})()
    return ns


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 1: Handler Template Tests (derive/_handler.py)
# ═══════════════════════════════════════════════════════════════════════════════


class TestFetchMany:
    def test_build_returns_all_items(self) -> None:
        spec = _make_spec(Item)
        items = [Item(1, "a", 1.0), Item(2, "b", 2.0)]
        prov = _make_provider(Item, items)
        handler = FetchMany().build(spec)
        op = _make_op(prov)
        result = _run(handler(op))
        assert isinstance(result, Ok)
        assert len(cast(list[object], result.unwrap())) == 2

    def test_op_defaults(self) -> None:
        op = FetchMany().op_defaults()
        assert op.name == "List"


class TestFetchOneById:
    def test_found(self) -> None:
        spec = _make_spec(Item)
        prov = _make_provider(Item, [Item(1, "a", 1.0)])
        handler = FetchOneById().build(spec)
        op = _make_op(prov, id=1)
        result = _run(handler(op))
        assert isinstance(result, Ok)
        assert cast(Item, result.unwrap()).name == "a"

    def test_not_found(self) -> None:
        spec = _make_spec(Item)
        prov = _make_provider(Item)
        handler = FetchOneById().build(spec)
        op = _make_op(prov, id=999)
        result = _run(handler(op))
        assert isinstance(result, Error)

    def test_op_defaults(self) -> None:
        op = FetchOneById().op_defaults()
        assert op.name == "Get"


class TestInsertNew:
    def test_insert_with_provided_id(self) -> None:
        spec = _make_spec(Item)
        prov = _make_provider(Item)
        handler = InsertNew().build(spec)
        op = _make_op(prov, id=10, name="new", price=9.99)
        result = _run(handler(op))
        assert isinstance(result, Ok)
        assert cast(Item, result.unwrap()).id == 10

    def test_insert_auto_id(self) -> None:
        spec = _make_spec(Item)
        prov = _make_provider(Item, with_next_id=True)
        handler = InsertNew().build(spec)
        op = _make_op(prov, name="auto", price=1.0)
        result = _run(handler(op))
        assert isinstance(result, Ok)
        assert cast(Item, result.unwrap()).id is not None

    def test_insert_no_next_id_raises(self) -> None:
        spec = _make_spec(Item)
        prov = _make_provider(Item)
        handler = InsertNew().build(spec)
        op = _make_op(prov, name="fail", price=0.0)
        # MemoryRelationalProvider always has next_id method but raises
        # if no generator is configured
        with pytest.raises(RuntimeError, match="next_id"):
            _run(handler(op))

    def test_op_defaults(self) -> None:
        op = InsertNew().op_defaults()
        assert op.name == "Create"


class TestUpdateExisting:
    def test_update_found(self) -> None:
        spec = _make_spec(Item)
        prov = _make_provider(Item, [Item(1, "old", 1.0)])
        handler = UpdateExisting().build(spec)
        op = _make_op(prov, id=1, name="updated", price=2.0)
        result = _run(handler(op))
        assert isinstance(result, Ok)
        assert cast(Item, result.unwrap()).name == "updated"

    def test_update_not_found(self) -> None:
        spec = _make_spec(Item)
        prov = _make_provider(Item)
        handler = UpdateExisting().build(spec)
        op = _make_op(prov, id=999, name="x", price=0.0)
        result = _run(handler(op))
        assert isinstance(result, Error)

    def test_op_defaults(self) -> None:
        op = UpdateExisting().op_defaults()
        assert op.name == "Update"


class TestDeleteOne:
    def test_delete_found(self) -> None:
        spec = _make_spec(Item)
        prov = _make_provider(Item, [Item(1, "a", 1.0)])
        handler = DeleteOne().build(spec)
        op = _make_op(prov, id=1)
        result = _run(handler(op))
        assert isinstance(result, Ok)

    def test_delete_not_found(self) -> None:
        spec = _make_spec(Item)
        prov = _make_provider(Item)
        handler = DeleteOne().build(spec)
        op = _make_op(prov, id=999)
        result = _run(handler(op))
        assert isinstance(result, Error)

    def test_op_defaults(self) -> None:
        op = DeleteOne().op_defaults()
        assert op.name == "Delete"


class TestPaginatedFetchMany:
    def test_paginated_fetch(self) -> None:
        spec = _make_spec(Item)
        items = [Item(i, f"item{i}", float(i)) for i in range(50)]
        prov = _make_provider(Item, items)
        handler = PaginatedFetchMany(page_size=10).build(spec)
        op = _make_op(prov, page=2, page_size=10)
        result = _run(handler(op))
        assert isinstance(result, Ok)
        data = cast(dict[str, object], result.unwrap())
        assert data["total"] == 50
        assert data["page"] == 2
        assert data["page_size"] == 10

    def test_op_defaults(self) -> None:
        op = PaginatedFetchMany().op_defaults()
        assert op.name == "List"


class TestPatchExisting:
    def test_patch_partial_update(self) -> None:
        spec = _make_spec(Item)
        prov = _make_provider(Item, [Item(1, "old", 1.0)])
        handler = PatchExisting().build(spec)
        op = _make_op(prov, id=1, name="patched")
        result = _run(handler(op))
        assert isinstance(result, Ok)
        assert cast(Item, result.unwrap()).name == "patched"

    def test_patch_not_found(self) -> None:
        spec = _make_spec(Item)
        prov = _make_provider(Item)
        handler = PatchExisting().build(spec)
        op = _make_op(prov, id=999, name="x")
        result = _run(handler(op))
        assert isinstance(result, Error)

    def test_op_defaults(self) -> None:
        op = PatchExisting().op_defaults()
        assert op.name == "Patch"


class TestSortedFetchMany:
    def test_sorted_asc(self) -> None:
        spec = _make_spec(Item)
        items = [Item(1, "banana", 3.0), Item(2, "apple", 1.0)]
        prov = _make_provider(Item, items)
        handler = SortedFetchMany(default_sort="name").build(spec)
        op = _make_op(prov)
        result = _run(handler(op))
        assert isinstance(result, Ok)
        items_list = cast(list[Item], result.unwrap())
        names = [e.name for e in items_list]
        assert names == ["apple", "banana"]

    def test_sorted_desc(self) -> None:
        spec = _make_spec(Item)
        items = [Item(1, "a", 1.0), Item(2, "b", 2.0)]
        prov = _make_provider(Item, items)
        handler = SortedFetchMany(default_sort="name", default_order="desc").build(spec)
        op = _make_op(prov, sort="name", order="desc")
        result = _run(handler(op))
        assert isinstance(result, Ok)
        items_list = cast(list[Item], result.unwrap())
        names = [e.name for e in items_list]
        assert names == ["b", "a"]

    def test_op_defaults(self) -> None:
        op = SortedFetchMany().op_defaults()
        assert op.name == "List"


class TestUpsertExisting:
    def test_upsert_insert(self) -> None:
        spec = _make_spec(Item)
        prov = _make_provider(Item)
        handler = UpsertExisting().build(spec)
        op = _make_op(prov, id=1, name="new", price=5.0)
        result = _run(handler(op))
        assert isinstance(result, Ok)
        assert cast(Item, result.unwrap()).name == "new"

    def test_upsert_update(self) -> None:
        spec = _make_spec(Item)
        prov = _make_provider(Item, [Item(1, "old", 1.0)])
        handler = UpsertExisting().build(spec)
        op = _make_op(prov, id=1, name="updated", price=2.0)
        result = _run(handler(op))
        assert isinstance(result, Ok)
        assert cast(Item, result.unwrap()).name == "updated"

    def test_op_defaults(self) -> None:
        op = UpsertExisting().op_defaults()
        assert op.name == "Upsert"


class TestExistsById:
    def test_exists_true(self) -> None:
        spec = _make_spec(Item)
        prov = _make_provider(Item, [Item(1, "a", 1.0)])
        handler = ExistsById().build(spec)
        op = _make_op(prov, id=1)
        result = _run(handler(op))
        assert isinstance(result, Ok)
        assert result.unwrap() is True

    def test_exists_false(self) -> None:
        spec = _make_spec(Item)
        prov = _make_provider(Item)
        handler = ExistsById().build(spec)
        op = _make_op(prov, id=999)
        result = _run(handler(op))
        assert isinstance(result, Ok)
        assert result.unwrap() is False

    def test_op_defaults(self) -> None:
        op = ExistsById().op_defaults()
        assert op.name == "Exists"


class TestCountAll:
    def test_count(self) -> None:
        spec = _make_spec(Item)
        items = [Item(1, "a", 1.0), Item(2, "b", 2.0), Item(3, "c", 3.0)]
        prov = _make_provider(Item, items)
        handler = CountAll().build(spec)
        op = _make_op(prov)
        result = _run(handler(op))
        assert isinstance(result, Ok)
        assert result.unwrap() == 3

    def test_op_defaults(self) -> None:
        op = CountAll().op_defaults()
        assert op.name == "Count"


class TestSetField:
    def test_set_field_value(self) -> None:
        spec = _make_spec(Item)
        prov = _make_provider(Item, [Item(1, "old", 1.0)])
        handler = SetField(field_name="name", value_fn=lambda op: "modified").build(spec)
        op = _make_op(prov, id=1)
        result = _run(handler(op))
        assert isinstance(result, Ok)
        assert cast(Item, result.unwrap()).name == "modified"

    def test_set_field_not_found(self) -> None:
        spec = _make_spec(Item)
        prov = _make_provider(Item)
        handler = SetField(field_name="name", value_fn=lambda op: "x").build(spec)
        op = _make_op(prov, id=999)
        result = _run(handler(op))
        assert isinstance(result, Error)


class TestSoftDeleteMark:
    def test_soft_delete(self) -> None:
        spec = _make_spec(SoftItem)
        prov = _make_provider(SoftItem, [SoftItem(1, "a")])
        handler = SoftDeleteMark(deleted_field="deleted_at").build(spec)
        op = _make_op(prov, id=1)
        result = _run(handler(op))
        assert isinstance(result, Ok)
        assert cast(SoftItem, result.unwrap()).deleted_at is not None

    def test_soft_delete_not_found(self) -> None:
        spec = _make_spec(SoftItem)
        prov = _make_provider(SoftItem)
        handler = SoftDeleteMark().build(spec)
        op = _make_op(prov, id=999)
        result = _run(handler(op))
        assert isinstance(result, Error)


class TestTimestampInsert:
    def test_timestamp_insert_with_id(self) -> None:
        spec = _make_spec(TimedItem)
        prov = _make_provider(TimedItem)
        handler = TimestampInsert(created_field="created_at", updated_field="updated_at").build(spec)
        op = _make_op(prov, id=1, name="timed")
        result = _run(handler(op))
        assert isinstance(result, Ok)
        entity = cast(TimedItem, result.unwrap())
        assert entity.created_at is not None
        assert entity.updated_at is not None

    def test_timestamp_insert_auto_id(self) -> None:
        spec = _make_spec(TimedItem)
        prov = _make_provider(TimedItem, with_next_id=True)
        handler = TimestampInsert(created_field="created_at", updated_field="updated_at").build(spec)
        op = _make_op(prov, name="auto_timed")
        result = _run(handler(op))
        assert isinstance(result, Ok)

    def test_timestamp_insert_no_next_id_raises(self) -> None:
        spec = _make_spec(TimedItem)
        prov = _make_provider(TimedItem)
        handler = TimestampInsert(created_field="created_at", updated_field="updated_at").build(spec)
        op = _make_op(prov, name="fail")
        with pytest.raises(RuntimeError, match="next_id"):
            _run(handler(op))


class TestTimestampUpdate:
    def test_timestamp_update(self) -> None:
        spec = _make_spec(TimedItem)
        prov = _make_provider(TimedItem, [TimedItem(1, "old", "2020-01-01", "2020-01-01")])
        handler = TimestampUpdate(updated_field="updated_at").build(spec)
        op = _make_op(prov, id=1, name="updated_name")
        result = _run(handler(op))
        assert isinstance(result, Ok)
        assert cast(TimedItem, result.unwrap()).name == "updated_name"
        # updated_at should be changed (datetime, not the original string)
        assert cast(TimedItem, result.unwrap()).updated_at != "2020-01-01"

    def test_timestamp_update_not_found(self) -> None:
        spec = _make_spec(TimedItem)
        prov = _make_provider(TimedItem)
        handler = TimestampUpdate(updated_field="updated_at").build(spec)
        op = _make_op(prov, id=999, name="x")
        result = _run(handler(op))
        assert isinstance(result, Error)


class TestCachedFetchOneById:
    def test_cache_miss_then_hit(self) -> None:
        spec = _make_spec(Item)
        prov = _make_provider(Item, [Item(1, "a", 1.0)])

        cache_store: dict[str, object] = {}

        class SimpleCache:
            async def get(self, key: str) -> object:
                return cache_store.get(key)

            async def set(self, key: str, val: object) -> None:
                cache_store[key] = val

        handler = CachedFetchOneById().build(spec)
        op = _make_op(prov, id=1, cache=SimpleCache())
        result = _run(handler(op))
        assert isinstance(result, Ok)
        assert cast(Item, result.unwrap()).name == "a"
        # Second call should hit cache
        result2 = _run(handler(op))
        assert isinstance(result2, Ok)

    def test_cache_not_found(self) -> None:
        spec = _make_spec(Item)
        prov = _make_provider(Item)

        class SimpleCache:
            async def get(self, key: str) -> object:
                return None

            async def set(self, key: str, val: object) -> None:
                pass

        handler = CachedFetchOneById().build(spec)
        op = _make_op(prov, id=999, cache=SimpleCache())
        result = _run(handler(op))
        assert isinstance(result, Error)

    def test_no_cache_raises(self) -> None:
        spec = _make_spec(Item)
        prov = _make_provider(Item, [Item(1, "a", 1.0)])
        handler = CachedFetchOneById().build(spec)
        op = _make_op(prov, id=1)
        with pytest.raises(RuntimeError, match="cache"):
            _run(handler(op))

    def test_op_defaults(self) -> None:
        op = CachedFetchOneById().op_defaults()
        assert op.name == "Get"


class TestWrappedTemplate:
    def test_wrap_template(self) -> None:
        from emergent.wire.derive._ctx import OperationHandler

        inner = FetchMany()

        class _Wrapper:
            def __call__[EntityT](
                self,
                inner: OperationHandler[object, DomainError],
                spec: HandlerSpec[EntityT],
            ) -> OperationHandler[object, DomainError]:
                async def wrapped(op: object) -> Result[object, DomainError]:
                    result = await inner(op)
                    if isinstance(result, Ok):
                        return Ok(list(reversed(cast(list[object], result.unwrap()))))
                    return result

                return wrapped

        wrapped = wrap_template(inner, _Wrapper())
        assert isinstance(wrapped, WrappedTemplate)
        spec = _make_spec(Item)
        prov = _make_provider(Item, [Item(1, "first", 1.0), Item(2, "second", 2.0)])
        handler = wrapped.build(spec)
        op = _make_op(prov)
        result = _run(handler(op))
        assert isinstance(result, Ok)
        items = cast(list[Item], result.unwrap())
        # Items should be reversed by wrapper
        assert items[0].name == "second"


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 2: Pipeline Tests (derive/_pipeline.py)
# ═══════════════════════════════════════════════════════════════════════════════


class TestPipelineFetchAll:
    def test_scope_query_fetch_all_wrap_items(self) -> None:
        spec = _make_spec(Item)
        prov = _make_provider(Item, [Item(1, "a", 1.0), Item(2, "b", 2.0)])
        pipeline = Pipeline(ScopeQuery(), FetchAll(), WrapItems())
        handler = pipeline.build(spec)
        op = _make_op(prov)
        result = _run(handler(op))
        assert isinstance(result, Ok)
        assert len(cast(list[object], result.unwrap())) == 2


class TestPipelineIdentityFilter:
    def test_identity_filter_fetch_or_not_found(self) -> None:
        spec = _make_spec(Item)
        prov = _make_provider(Item, [Item(1, "a", 1.0)])
        pipeline = Pipeline(ScopeQuery(), IdentityFilter(), FetchOrNotFound(), WrapOk())
        handler = pipeline.build(spec)
        op = _make_op(prov, id=1)
        result = _run(handler(op))
        assert isinstance(result, Ok)
        assert cast(Item, result.unwrap()).name == "a"

    def test_identity_filter_not_found(self) -> None:
        spec = _make_spec(Item)
        prov = _make_provider(Item)
        pipeline = Pipeline(ScopeQuery(), IdentityFilter(), FetchOrNotFound(), WrapOk())
        handler = pipeline.build(spec)
        op = _make_op(prov, id=999)
        result = _run(handler(op))
        assert isinstance(result, Error)


class TestPipelinePaginate:
    def test_paginate_step(self) -> None:
        spec = _make_spec(Item)
        items = [Item(i, f"item{i}", float(i)) for i in range(30)]
        prov = _make_provider(Item, items)
        pipeline = Pipeline(ScopeQuery(), CountTotal(), Paginate(default_page_size=10), FetchAll(), WrapPaginated())
        handler = pipeline.build(spec)
        op = _make_op(prov, page=2, page_size=10)
        result = _run(handler(op))
        assert isinstance(result, Ok)
        data = cast(dict[str, object], result.unwrap())
        assert data["total"] == 30
        assert data["page"] == 2


class TestPipelineBuildEntityData:
    def test_build_entity_data_insert(self) -> None:
        spec = _make_spec(Item)
        prov = _make_provider(Item)
        pipeline = Pipeline(BuildEntityData(), ProviderInsert(), WrapOk())
        handler = pipeline.build(spec)
        op = _make_op(prov, id=1, name="built", price=5.0)
        result = _run(handler(op))
        assert isinstance(result, Ok)
        assert cast(Item, result.unwrap()).name == "built"


class TestPipelineMergeFields:
    def test_merge_fields_update(self) -> None:
        spec = _make_spec(Item)
        existing = Item(1, "old", 1.0)
        prov = _make_provider(Item, [existing])
        pipeline = Pipeline(
            ScopeQuery(), IdentityFilter(), FetchOrNotFound(),
            MergeFields(), ProviderUpdate(), WrapOk(),
        )
        handler = pipeline.build(spec)
        op = _make_op(prov, id=1, name="merged", price=2.0)
        result = _run(handler(op))
        assert isinstance(result, Ok)
        assert cast(Item, result.unwrap()).name == "merged"


class TestPipelinePatchMerge:
    def test_patch_merge_fields(self) -> None:
        spec = _make_spec(Item)
        prov = _make_provider(Item, [Item(1, "old", 1.0)])
        pipeline = Pipeline(
            ScopeQuery(), IdentityFilter(), FetchOrNotFound(),
            PatchMergeFields(), ProviderUpdate(), WrapOk(),
        )
        handler = pipeline.build(spec)
        op = _make_op(prov, id=1, name="patched")
        result = _run(handler(op))
        assert isinstance(result, Ok)
        assert cast(Item, result.unwrap()).name == "patched"


class TestPipelineCopyExistingToData:
    def test_copy_existing_to_data(self) -> None:
        spec = _make_spec(Item)
        prov = _make_provider(Item, [Item(1, "existing", 5.0)])
        pipeline = Pipeline(
            ScopeQuery(), IdentityFilter(), FetchOrNotFound(),
            CopyExistingToData(), ProviderUpdate(), WrapOk(),
        )
        handler = pipeline.build(spec)
        op = _make_op(prov, id=1)
        result = _run(handler(op))
        assert isinstance(result, Ok)
        assert cast(Item, result.unwrap()).name == "existing"


class TestPipelineSetTimestamp:
    def test_set_timestamp(self) -> None:
        spec = _make_spec(TimedItem)
        prov = _make_provider(TimedItem)
        pipeline = Pipeline(
            BuildEntityData(),
            SetTimestamp("created_at"),
            SetTimestamp("updated_at"),
            ProviderInsert(),
            WrapOk(),
        )
        handler = pipeline.build(spec)
        op = _make_op(prov, id=1, name="timed")
        result = _run(handler(op))
        assert isinstance(result, Ok)
        entity = cast(TimedItem, result.unwrap())
        assert entity.created_at is not None
        assert entity.updated_at is not None

    def test_set_timestamp_on_empty_entity_data(self) -> None:
        spec = _make_spec(TimedItem)
        prov = _make_provider(TimedItem)
        pipeline = Pipeline(SetTimestamp("created_at"), WrapOk())
        handler = pipeline.build(spec)
        op = _make_op(prov, id=1, name="x")
        result = _run(handler(op))
        assert isinstance(result, Ok)


class TestPipelineSetFieldValue:
    def test_set_field_value_step(self) -> None:
        spec = _make_spec(Item)
        prov = _make_provider(Item)
        pipeline = Pipeline(
            BuildEntityData(),
            SetFieldValue("name", lambda op: "computed"),
            ProviderInsert(),
            WrapOk(),
        )
        handler = pipeline.build(spec)
        op = _make_op(prov, id=1, name="ignored", price=1.0)
        result = _run(handler(op))
        assert isinstance(result, Ok)
        assert cast(Item, result.unwrap()).name == "computed"

    def test_set_field_value_on_empty_entity_data(self) -> None:
        spec = _make_spec(Item)
        prov = _make_provider(Item)
        pipeline = Pipeline(SetFieldValue("name", lambda op: "val"), WrapOk())
        handler = pipeline.build(spec)
        op = _make_op(prov)
        result = _run(handler(op))
        assert isinstance(result, Ok)


class TestPipelineProviderDelete:
    def test_provider_delete_step(self) -> None:
        spec = _make_spec(Item)
        prov = _make_provider(Item, [Item(1, "a", 1.0)])
        pipeline = Pipeline(
            ScopeQuery(), IdentityFilter(), FetchOrNotFound(),
            ProviderDelete(), WrapOk(),
        )
        handler = pipeline.build(spec)
        op = _make_op(prov, id=1)
        result = _run(handler(op))
        assert isinstance(result, Ok)


class TestPipelineWrapCount:
    def test_wrap_count(self) -> None:
        spec = _make_spec(Item)
        items = [Item(i, f"i{i}", float(i)) for i in range(5)]
        prov = _make_provider(Item, items)
        pipeline = Pipeline(ScopeQuery(), CountTotal(), WrapCount())
        handler = pipeline.build(spec)
        op = _make_op(prov)
        result = _run(handler(op))
        assert isinstance(result, Ok)
        assert result.unwrap() == 5


class TestPipelineWrapExists:
    def test_wrap_exists_true(self) -> None:
        spec = _make_spec(Item)
        prov = _make_provider(Item, [Item(1, "a", 1.0)])
        pipeline = Pipeline(FetchByIdentity(), WrapExists())
        handler = pipeline.build(spec)
        op = _make_op(prov, id=1)
        result = _run(handler(op))
        assert isinstance(result, Ok)
        assert result.unwrap() is True

    def test_wrap_exists_false(self) -> None:
        spec = _make_spec(Item)
        prov = _make_provider(Item)
        pipeline = Pipeline(FetchByIdentity(), WrapExists())
        handler = pipeline.build(spec)
        op = _make_op(prov, id=999)
        result = _run(handler(op))
        assert isinstance(result, Ok)
        assert result.unwrap() is False


class TestPipelineInMemorySort:
    def test_in_memory_sort(self) -> None:
        spec = _make_spec(Item)
        items = [Item(2, "b", 2.0), Item(1, "a", 1.0)]
        prov = _make_provider(Item, items)
        pipeline = Pipeline(ScopeQuery(), FetchAll(), InMemorySort(default_sort="name"), WrapItems())
        handler = pipeline.build(spec)
        op = _make_op(prov)
        result = _run(handler(op))
        assert isinstance(result, Ok)
        assert cast(list[Item], result.unwrap())[0].name == "a"


class TestPipelineWrapOkFallback:
    def test_wrap_ok_items_fallback(self) -> None:
        spec = _make_spec(Item)
        items = [Item(1, "a", 1.0)]
        prov = _make_provider(Item, items)
        pipeline = Pipeline(ScopeQuery(), FetchAll(), WrapOk())
        handler = pipeline.build(spec)
        op = _make_op(prov)
        result = _run(handler(op))
        assert isinstance(result, Ok)
        # pctx.result is None, pctx.items is set, so fallback to items
        assert len(cast(list[object], result.unwrap())) == 1

    def test_wrap_ok_existing_fallback(self) -> None:
        spec = _make_spec(Item)
        prov = _make_provider(Item, [Item(1, "a", 1.0)])
        pipeline = Pipeline(
            ScopeQuery(), IdentityFilter(), FetchOrNotFound(), WrapOk(),
        )
        handler = pipeline.build(spec)
        op = _make_op(prov, id=1)
        result = _run(handler(op))
        assert isinstance(result, Ok)
        assert cast(Item, result.unwrap()).name == "a"


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 3: Methods Pattern Tests (derive/patterns/methods.py)
# ═══════════════════════════════════════════════════════════════════════════════


class TestMethodDecorators:
    def test_post_decorator(self) -> None:
        @post("/items")
        async def create(x: int) -> Result[int, DomainError]:
            return Ok(x)

        entries = getattr(create, "__trigger_entries__", [])
        assert len(entries) == 1
        assert entries[0].trigger.method == "POST"

    def test_get_decorator(self) -> None:
        @get("/items")
        async def list_items() -> Result[list[int], DomainError]:
            return Ok([])

        entries = getattr(list_items, "__trigger_entries__", [])
        assert len(entries) == 1
        assert entries[0].trigger.method == "GET"

    def test_put_decorator(self) -> None:
        @put("/items/{id}")
        async def update(id: int) -> Result[int, DomainError]:
            return Ok(id)

        entries = getattr(update, "__trigger_entries__", [])
        assert entries[0].trigger.method == "PUT"

    def test_delete_decorator(self) -> None:
        @delete("/items/{id}")
        async def remove(id: int) -> Result[bool, DomainError]:
            return Ok(True)

        entries = getattr(remove, "__trigger_entries__", [])
        assert entries[0].trigger.method == "DELETE"

    def test_patch_decorator(self) -> None:
        @patch("/items/{id}")
        async def modify(id: int) -> Result[int, DomainError]:
            return Ok(id)

        entries = getattr(modify, "__trigger_entries__", [])
        assert entries[0].trigger.method == "PATCH"

    def test_command_decorator(self) -> None:
        @command("create-item")
        async def create_cmd(name: str) -> Result[str, DomainError]:
            return Ok(name)

        entries = getattr(create_cmd, "__trigger_entries__", [])
        assert len(entries) == 1

    def test_multi_trigger_stacking(self) -> None:
        @post("/items")
        @command("create-item")
        async def create(name: str) -> Result[str, DomainError]:
            return Ok(name)

        entries = getattr(create, "__trigger_entries__", [])
        assert len(entries) == 2

    def test_op_decorator(self) -> None:
        @op("Create")
        async def create(name: str) -> Result[str, DomainError]:
            return Ok(name)

        entry = getattr(create, "__op_entry__", None)
        assert entry is not None
        assert entry.name == "Create"

    def test_op_decorator_default_name(self) -> None:
        @op()
        async def my_action(x: int) -> Result[int, DomainError]:
            return Ok(x)

        entry = getattr(my_action, "__op_entry__", None)
        assert entry is not None
        assert entry.name == "my_action"


class TestMethodsCapability:
    def test_methods_generate_operations(self) -> None:
        @dataclass
        class TestService:
            @classmethod
            @post("/api/test")
            async def create_item(cls, name: str) -> Result[str, DomainError]:
                return Ok(name)

        cap = Methods()
        ctx = DeriveCtx.from_subject(TestService)
        ctx = cap.compile_derive_generate(ctx)
        assert len(ctx.operations) == 1

    def test_methods_static_method(self) -> None:
        @dataclass
        class TestService:
            @staticmethod
            @get("/api/health")
            async def health() -> Result[str, DomainError]:
                return Ok("ok")

        cap = Methods()
        ctx = DeriveCtx.from_subject(TestService)
        ctx = cap.compile_derive_generate(ctx)
        assert len(ctx.operations) == 1

    def test_methods_sync_method_raises(self) -> None:
        @dataclass
        class BadService:
            @classmethod
            @post("/api/bad")
            def sync_method(cls, x: int) -> Result[int, DomainError]:
                return Ok(x)

        cap = Methods()
        ctx = DeriveCtx.from_subject(BadService)
        with pytest.raises(TypeError, match="must be async"):
            cap.compile_derive_generate(ctx)


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 4: Bridge Capabilities Tests (bridge/_capabilities.py)
# ═══════════════════════════════════════════════════════════════════════════════


class TestBridgeContext:
    def test_create_context(self) -> None:
        async def handler() -> str:
            return "ok"

        ctx: BridgeContext[str, ..., str] = BridgeContext(
            trigger_data="test",
            handler=handler,
            name="test_handler",
        )
        assert ctx.name == "test_handler"
        assert ctx.skip is False
        assert ctx.deprecated is False


class TestSkipDeprecated:
    def test_skip_deprecated_handler(self) -> None:
        async def handler() -> str:
            return "ok"

        ctx = BridgeContext(trigger_data="t", handler=handler, deprecated=True)
        result = SkipDeprecated().compile_bridge(ctx)
        assert result.skip is True

    def test_keep_non_deprecated(self) -> None:
        async def handler() -> str:
            return "ok"

        ctx = BridgeContext(trigger_data="t", handler=handler, deprecated=False)
        result = SkipDeprecated().compile_bridge(ctx)
        assert result.skip is False


class TestSkipByName:
    def test_skip_by_exact_name(self) -> None:
        async def handler() -> str:
            return "ok"

        ctx = BridgeContext(trigger_data="t", handler=handler, name="internal")
        result = SkipByName(names=frozenset({"internal"})).compile_bridge(ctx)
        assert result.skip is True

    def test_skip_by_pattern(self) -> None:
        async def handler() -> str:
            return "ok"

        ctx = BridgeContext(trigger_data="t", handler=handler, name="debug_endpoint")
        result = SkipByName(pattern=r"debug_.*").compile_bridge(ctx)
        assert result.skip is True

    def test_keep_non_matching(self) -> None:
        async def handler() -> str:
            return "ok"

        ctx = BridgeContext(trigger_data="t", handler=handler, name="users")
        result = SkipByName(names=frozenset({"internal"})).compile_bridge(ctx)
        assert result.skip is False


class TestIncludeOnlyByName:
    def test_include_matching(self) -> None:
        async def handler() -> str:
            return "ok"

        ctx = BridgeContext(trigger_data="t", handler=handler, name="api_users")
        result = IncludeOnlyByName(names=frozenset({"api_users"})).compile_bridge(ctx)
        assert result.skip is False

    def test_skip_non_matching(self) -> None:
        async def handler() -> str:
            return "ok"

        ctx = BridgeContext(trigger_data="t", handler=handler, name="internal")
        result = IncludeOnlyByName(names=frozenset({"api_users"})).compile_bridge(ctx)
        assert result.skip is True

    def test_include_by_pattern(self) -> None:
        async def handler() -> str:
            return "ok"

        ctx = BridgeContext(trigger_data="t", handler=handler, name="api_orders")
        result = IncludeOnlyByName(pattern=r"api_.*").compile_bridge(ctx)
        assert result.skip is False

    def test_skip_none_name(self) -> None:
        async def handler() -> str:
            return "ok"

        ctx = BridgeContext(trigger_data="t", handler=handler, name=None)
        result = IncludeOnlyByName(names=frozenset({"test"})).compile_bridge(ctx)
        assert result.skip is True


class TestSetRequestTypeByName:
    def test_set_request_type(self) -> None:
        async def handler() -> str:
            return "ok"

        ctx = BridgeContext(trigger_data="t", handler=handler, name="create_user")
        cap = SetRequestTypeByName(type_map={"create_user": dict})
        result = cap.compile_bridge(ctx)
        assert result.request_type is dict

    def test_skip_if_already_set(self) -> None:
        async def handler() -> str:
            return "ok"

        ctx = BridgeContext(trigger_data="t", handler=handler, name="create_user", request_type=int)
        cap = SetRequestTypeByName(type_map={"create_user": dict})
        result = cap.compile_bridge(ctx)
        assert result.request_type is int

    def test_no_match(self) -> None:
        async def handler() -> str:
            return "ok"

        ctx = BridgeContext(trigger_data="t", handler=handler, name="other")
        cap = SetRequestTypeByName(type_map={"create_user": dict})
        result = cap.compile_bridge(ctx)
        assert result.request_type is None


class TestSetResponseTypeByName:
    def test_set_response_type(self) -> None:
        async def handler() -> str:
            return "ok"

        ctx = BridgeContext(trigger_data="t", handler=handler, name="get_user")
        cap = SetResponseTypeByName(type_map={"get_user": str})
        result = cap.compile_bridge(ctx)
        assert result.response_type is str


class TestSetCodecByName:
    def test_set_codec(self) -> None:
        async def handler() -> str:
            return "ok"

        sentinel_codec = object()
        ctx = BridgeContext(trigger_data="t", handler=handler, name="special")
        cap = SetCodecByName(codec_map={"special": sentinel_codec})
        result = cap.compile_bridge(ctx)
        assert result.wire.codec is sentinel_codec

    def test_skip_if_codec_set(self) -> None:
        async def handler() -> str:
            return "ok"

        existing_codec = object()
        ctx = BridgeContext(
            trigger_data="t", handler=handler, name="special",
            wire=WireData(codec=existing_codec),
        )
        cap = SetCodecByName(codec_map={"special": object()})
        result = cap.compile_bridge(ctx)
        assert result.wire.codec is existing_codec


class TestFoldBridge:
    def test_fold_bridge_chain(self) -> None:
        async def handler() -> str:
            return "ok"

        ctx = BridgeContext(trigger_data="t", handler=handler, name="test", deprecated=True)
        caps: list[BridgeCapability] = [SkipDeprecated()]
        result = fold_bridge(ctx, caps)
        assert result.skip is True

    def test_fold_bridge_stops_on_skip(self) -> None:
        async def handler() -> str:
            return "ok"

        ctx = BridgeContext(trigger_data="t", handler=handler, name="debug_x", deprecated=False)
        caps: list[BridgeCapability] = [
            SkipByName(pattern=r"debug_.*"),
            SetRequestTypeByName(type_map={"debug_x": int}),
        ]
        result = fold_bridge(ctx, caps)
        assert result.skip is True
        assert result.request_type is None


class TestFindBridgeCapability:
    def test_find_existing(self) -> None:
        caps: list[BridgeCapability] = [SkipDeprecated(), WrapAsync()]
        found = find_bridge_capability(caps, WrapAsync)
        assert found is not None

    def test_find_missing(self) -> None:
        caps: list[BridgeCapability] = [SkipDeprecated()]
        found = find_bridge_capability(caps, WrapAsync)
        assert found is None

    def test_find_all(self) -> None:
        caps: list[BridgeCapability] = [SkipDeprecated(), SkipByName(), SkipDeprecated()]
        found = find_all_bridge_capabilities(caps, SkipDeprecated)
        assert len(found) == 2


class TestPurifiers:
    def test_wrap_async_sync(self) -> None:
        def sync_handler() -> str:
            return "sync_result"

        wrapped = WrapAsync().purify(sync_handler)
        result = _run(wrapped())
        assert result == "sync_result"

    def test_wrap_async_already_async(self) -> None:
        async def async_handler() -> str:
            return "async_result"

        wrapped = WrapAsync().purify(async_handler)
        result = _run(wrapped())
        assert result == "async_result"

    def test_catch_errors(self) -> None:
        async def failing() -> str:
            raise ValueError("boom")

        wrapped = CatchErrors(on_error=lambda e: f"caught: {e}").purify(failing)
        result = _run(wrapped())
        assert result == "caught: boom"

    def test_inject_kwarg(self) -> None:
        async def handler(db: str = "default") -> str:
            return db

        wrapped = InjectKwarg(name="db", factory=lambda: "injected").purify(handler)
        result = _run(wrapped())
        assert result == "injected"

    def test_inject_kwarg_no_override(self) -> None:
        async def handler(db: str = "default") -> str:
            return db

        wrapped = InjectKwarg(name="db", factory=lambda: "injected").purify(handler)
        result = _run(wrapped(db="explicit"))
        assert result == "explicit"

    def test_inject_kwarg_async(self) -> None:
        async def handler(val: int = 0) -> int:
            return val

        async def factory() -> int:
            return 42

        wrapped = InjectKwargAsync(name="val", factory=factory).purify(handler)
        result = _run(wrapped())
        assert result == 42

    def test_chain_purifiers(self) -> None:
        def sync_fn() -> str:
            return "base"

        from emergent.wire.bridge._capabilities import Purifier
        wrapped = chain_purifiers(
            cast(list[Purifier], [WrapAsync(), CatchErrors(on_error=lambda e: "caught")]),
            sync_fn,
        )
        result = _run(wrapped())
        assert result == "base"

    def test_apply_purifiers(self) -> None:
        def sync_fn() -> str:
            return "ok"

        caps: list[BridgeCapability] = [WrapAsync()]
        wrapped = apply_purifiers(sync_fn, caps)
        result = _run(wrapped())
        assert result == "ok"

    def test_apply_purifiers_no_purifiers(self) -> None:
        async def async_fn() -> str:
            return "ok"

        caps: list[BridgeCapability] = [SkipDeprecated()]
        wrapped = apply_purifiers(async_fn, caps)
        result = _run(wrapped())
        assert result == "ok"


class TestSetupTeardown:
    def test_setup_teardown(self) -> None:
        state: list[str] = []

        async def handler() -> str:
            state.append("handler")
            return "ok"

        wrapped = SetupTeardown(
            setup=lambda: state.append("setup"),
            teardown=lambda: state.append("teardown"),
        ).purify(handler)
        _run(wrapped())
        assert state == ["setup", "handler", "teardown"]

    def test_setup_only(self) -> None:
        state: list[str] = []

        async def handler() -> str:
            return "ok"

        wrapped = SetupTeardown(
            setup=lambda: state.append("setup"),
            teardown=None,
        ).purify(handler)
        _run(wrapped())
        assert state == ["setup"]


class TestWithContext:
    def test_with_context(self) -> None:
        state: list[str] = []

        @asynccontextmanager
        async def ctx_mgr():
            state.append("enter")
            yield
            state.append("exit")

        async def handler() -> str:
            return "ok"

        wrapped = WithContext(factory=ctx_mgr).purify(handler)
        _run(wrapped())
        assert state == ["enter", "exit"]


class TestWithContextSync:
    def test_with_context_sync(self) -> None:
        state: list[str] = []

        @contextmanager
        def ctx_mgr():
            state.append("enter")
            yield
            state.append("exit")

        async def handler() -> str:
            return "ok"

        wrapped = WithContextSync(factory=ctx_mgr).purify(handler)
        _run(wrapped())
        assert state == ["enter", "exit"]


class TestEnsureAsync:
    def test_sync_to_async(self) -> None:
        def sync_fn() -> str:
            return "sync"

        async_fn = ensure_async(sync_fn)
        assert inspect.iscoroutinefunction(async_fn)
        result = _run(async_fn())
        assert result == "sync"

    def test_already_async(self) -> None:
        async def async_fn() -> str:
            return "async"

        result_fn = ensure_async(async_fn)
        assert result_fn is async_fn


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 5: FastAPI Capabilities Tests (bridge/bridgers/fastapi/_capabilities.py)
# ═══════════════════════════════════════════════════════════════════════════════


class TestFastAPITypeHelpers:
    def test_get_fastapi_marker_body(self) -> None:
        class FakeBody:
            pass

        FakeBody.__name__ = "Body"  # type: ignore[attr-defined]
        assert _get_fastapi_marker([FakeBody()]) == "Body"

    def test_get_fastapi_marker_none(self) -> None:
        assert _get_fastapi_marker([]) is None
        assert _get_fastapi_marker([42]) is None

    def test_is_depends(self) -> None:
        class Depends:
            pass

        assert _is_depends(Depends()) is True
        assert _is_depends("not_depends") is False

    def test_is_pydantic_model_false(self) -> None:
        assert _is_pydantic_model(None) is False
        assert _is_pydantic_model(int) is False
        assert _is_pydantic_model("string") is False

    def test_is_dataclass_type(self) -> None:
        assert _is_dataclass_type(Item) is True
        assert _is_dataclass_type(int) is False
        assert _is_dataclass_type(None) is False
        assert _is_dataclass_type("x") is False

    def test_is_special_fastapi_type(self) -> None:
        assert _is_special_fastapi_type(None) is False

        class Request:
            __module__ = "starlette.requests"

        assert _is_special_fastapi_type(Request) is True

        class Normal:
            __module__ = "myapp"

        assert _is_special_fastapi_type(Normal) is False

    def test_is_special_fastapi_type_module(self) -> None:
        class SomeType:
            __module__ = "fastapi.something"

        assert _is_special_fastapi_type(SomeType) is True


class TestParseHandlerParams:
    def test_parse_basic_handler(self) -> None:
        async def handler(x: int, y: str = "default") -> str:
            return f"{x}{y}"

        params = _parse_handler_params(handler)
        assert len(params) == 2
        assert params[0].name == "x"
        assert params[0].source == "unknown"
        assert params[1].name == "y"

    def test_parse_non_callable(self) -> None:
        result = _parse_handler_params("not_callable")  # type: ignore[arg-type]
        assert result == []

    def test_parse_dataclass_body(self) -> None:
        async def handler(item: Item) -> str:
            return item.name

        params = _parse_handler_params(handler)
        body_params = [p for p in params if p.source == "body"]
        assert len(body_params) == 1

    def test_parse_no_annotation(self) -> None:
        # We can't easily make a param with no annotation in Python 3.13+
        # but we test the handler with return only
        async def handler() -> str:
            return "ok"

        params = _parse_handler_params(handler)
        assert len(params) == 0


class TestParseFastAPIHandler:
    def test_group_by_source(self) -> None:
        async def handler(x: int, item: Item) -> str:
            return ""

        grouped = parse_fastapi_handler(handler)
        assert "body" in grouped
        assert "unknown" in grouped
        assert len(grouped["body"]) == 1
        assert len(grouped["unknown"]) == 1


class TestInferFromFastAPI:
    def test_infer_response_type(self) -> None:
        async def handler() -> Item:
            return Item(1, "a", 1.0)

        ctx = BridgeContext(trigger_data="t", handler=handler)
        infer = InferFromFastAPI()
        result = infer.compile_bridge(ctx)
        assert result.response_type is Item

    def test_infer_request_type_dataclass(self) -> None:
        async def handler(item: Item) -> str:
            return "ok"

        ctx = BridgeContext(trigger_data="t", handler=handler)
        infer = InferFromFastAPI(include_dataclass=True)
        result = infer.compile_bridge(ctx)
        assert result.request_type is Item

    def test_infer_no_dataclass(self) -> None:
        async def handler(item: Item) -> str:
            return "ok"

        ctx = BridgeContext(trigger_data="t", handler=handler)
        infer = InferFromFastAPI(include_dataclass=False)
        result = infer.compile_bridge(ctx)
        # Item is a dataclass but include_dataclass=False, so no inference
        assert result.request_type is None

    def test_infer_preserves_existing(self) -> None:
        async def handler() -> str:
            return "ok"

        ctx = BridgeContext(trigger_data="t", handler=handler, request_type=int, response_type=str)
        infer = InferFromFastAPI()
        result = infer.compile_bridge(ctx)
        assert result.request_type is int
        assert result.response_type is str

    def test_infer_no_return_type(self) -> None:
        async def handler():
            return "ok"

        ctx = BridgeContext(trigger_data="t", handler=handler)
        infer = InferFromFastAPI()
        result = infer.compile_bridge(ctx)
        assert result.response_type is None

    def test_get_return_type_non_callable(self) -> None:
        infer = InferFromFastAPI()
        assert infer._get_return_type("not callable") is None  # type: ignore[arg-type]


class TestMapDepends:
    def test_empty_maps_passthrough(self) -> None:
        async def handler() -> str:
            return "ok"

        cap = MapDepends()
        wrapped = cap.purify(handler)
        result = _run(wrapped())
        assert result == "ok"


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 6: FastAPI Extractors (bridge/bridgers/fastapi/_extractors.py)
# ═══════════════════════════════════════════════════════════════════════════════


class TestIsFastAPIApp:
    def test_fastapi_class_name(self) -> None:
        class FastAPI:
            pass

        assert is_fastapi_app(FastAPI()) is True

    def test_starlette_class_name(self) -> None:
        class Starlette:
            pass

        assert is_fastapi_app(Starlette()) is True

    def test_duck_typing(self) -> None:
        class DuckApp:
            routes: list[object] = []
            router: object = None

        assert is_fastapi_app(DuckApp()) is True

    def test_not_fastapi(self) -> None:
        assert is_fastapi_app("not an app") is False
        assert is_fastapi_app(42) is False


class TestHTTPRouteExtractor:
    def test_can_extract(self) -> None:
        class App:
            routes: list[object] = []

        extractor = HTTPRouteExtractor()
        assert extractor.can_extract(App()) is True
        assert extractor.can_extract("nope") is False


class TestWebSocketExtractor:
    def test_can_extract(self) -> None:
        class App:
            routes: list[object] = []

        extractor = WebSocketExtractor()
        assert extractor.can_extract(App()) is True
        assert extractor.can_extract("nope") is False


class TestLifespanExtractor:
    def test_can_extract(self) -> None:
        class Router:
            on_startup: list[object] = []
            on_shutdown: list[object] = []

        class App:
            router = Router()

        extractor = LifespanExtractor()
        assert extractor.can_extract(App()) is True
        assert extractor.can_extract("nope") is False

    def test_extract_startup_shutdown(self) -> None:
        async def startup() -> None:
            pass

        async def shutdown() -> None:
            pass

        class Router:
            on_startup = [startup]
            on_shutdown = [shutdown]

        class App:
            router = Router()

        extractor = LifespanExtractor()
        results = list(extractor.extract(App()))
        assert len(results) == 2
        startup_r = [r for r in results if getattr(r.route, "kind", None) == "startup"]
        shutdown_r = [r for r in results if getattr(r.route, "kind", None) == "shutdown"]
        assert len(startup_r) == 1
        assert len(shutdown_r) == 1

    def test_extract_no_router(self) -> None:
        extractor = LifespanExtractor()
        results = list(extractor.extract("nope"))
        assert len(results) == 0


class TestExceptionHandlerExtractor:
    def test_can_extract(self) -> None:
        class App:
            exception_handlers: dict[type, object] = {}

        extractor = ExceptionHandlerExtractor()
        assert extractor.can_extract(App()) is True
        assert extractor.can_extract("nope") is False

    def test_extract_custom_exception(self) -> None:
        class MyError(Exception):
            __module__ = "myapp"

        async def handle_error(request: object, exc: MyError) -> str:
            return "handled"

        class App:
            exception_handlers = {MyError: handle_error}

        extractor = ExceptionHandlerExtractor()
        results = list(extractor.extract(App()))
        assert len(results) == 1
        assert getattr(results[0].route, "exception_type") is MyError

    def test_skip_non_exception(self) -> None:
        class App:
            exception_handlers = {"not_a_type": lambda: None}

        extractor = ExceptionHandlerExtractor()
        results = list(extractor.extract(App()))
        assert len(results) == 0


class TestPrependPath:
    def test_prepend_path_route(self) -> None:
        from emergent.wire.bridge.bridgers.fastapi._extractors import _prepend_path

        route = HTTPRouteData(method="GET", path="/items")
        result = _prepend_path(route, "/api")
        assert isinstance(result, HTTPRouteData)
        assert result.path == "/api/items"

    def test_prepend_path_no_path_field(self) -> None:
        from emergent.wire.bridge.bridgers.fastapi._extractors import _prepend_path

        result = _prepend_path("not a dataclass", "/api")
        assert result == "not a dataclass"


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 7: Handler Introspection (bridge/_introspect.py)
# ═══════════════════════════════════════════════════════════════════════════════


class TestParameterKind:
    def test_positional_or_keyword(self) -> None:
        def fn(x: int) -> None:
            pass

        sig = inspect.signature(fn)
        kind = ParameterKind.of(list(sig.parameters.values())[0])
        assert kind == ParameterKind.POSITIONAL_OR_KEYWORD

    def test_keyword_only(self) -> None:
        def fn(*, x: int) -> None:
            pass

        sig = inspect.signature(fn)
        kind = ParameterKind.of(list(sig.parameters.values())[0])
        assert kind == ParameterKind.KEYWORD_ONLY

    def test_var_positional(self) -> None:
        def fn(*args: int) -> None:
            pass

        sig = inspect.signature(fn)
        kind = ParameterKind.of(list(sig.parameters.values())[0])
        assert kind == ParameterKind.VAR_POSITIONAL

    def test_var_keyword(self) -> None:
        def fn(**kwargs: int) -> None:
            pass

        sig = inspect.signature(fn)
        kind = ParameterKind.of(list(sig.parameters.values())[0])
        assert kind == ParameterKind.VAR_KEYWORD


class TestParameterShape:
    def test_from_parameter(self) -> None:
        def fn(x: int = 5) -> None:
            pass

        sig = inspect.signature(fn)
        param = list(sig.parameters.values())[0]
        shape = ParameterShape.from_parameter(param, int)
        assert shape.name == "x"
        assert shape.annotation is int
        assert shape.has_default is True
        assert shape.default == 5

    def test_from_parameter_no_default(self) -> None:
        def fn(x: int) -> None:
            pass

        sig = inspect.signature(fn)
        param = list(sig.parameters.values())[0]
        shape = ParameterShape.from_parameter(param)
        assert shape.has_default is False
        assert shape.default is no_default()


class TestUnwrapHandler:
    def test_unwrap_simple(self) -> None:
        def original() -> str:
            return "ok"

        handler, decorators = unwrap_handler(original)
        assert handler is original
        assert len(decorators) == 0

    def test_unwrap_wrapped(self) -> None:
        def original() -> str:
            return "ok"

        @functools.wraps(original)
        def wrapper() -> str:
            return original()

        handler, decorators = unwrap_handler(wrapper)
        assert handler is original
        assert len(decorators) == 1

    def test_unwrap_non_callable_raises(self) -> None:
        with pytest.raises(TypeError, match="Expected callable"):
            unwrap_handler("not callable")

    def test_closure_fallback(self) -> None:
        def original() -> str:
            return "ok"

        # Create a real closure that captures original
        def make_wrapper(fn: object) -> object:
            def wrapper() -> str:
                return fn()  # type: ignore[misc]

            return wrapper

        wrapper = make_wrapper(original)
        strategy = ClosureFallbackUnwrap()
        handler, _decorators = strategy.unwrap(wrapper)
        # ClosureFallbackUnwrap tries __wrapped__ first, then closure
        # Since wrapper has no __wrapped__, it falls back to closure inspection
        # and finds original in the closure
        assert handler is original


class TestAnalyzeHandler:
    def test_analyze_simple_async(self) -> None:
        async def handler(x: int) -> str:
            return str(x)

        shape = analyze_handler(handler)
        assert shape.is_async is True
        assert "x" in shape.parameters
        assert shape.return_type is str

    def test_analyze_simple_sync(self) -> None:
        def handler(x: int) -> str:
            return str(x)

        shape = analyze_handler(handler)
        assert shape.is_async is False
        assert "x" in shape.parameters

    def test_analyze_skips_self_cls(self) -> None:
        class MyClass:
            def method(self, x: int) -> str:
                return str(x)

        shape = analyze_handler(MyClass.method)
        assert "self" not in shape.parameters
        assert "x" in shape.parameters

    def test_analyze_partial(self) -> None:
        def fn(a: int, b: str) -> str:
            return f"{a}{b}"

        p = partial(fn, a=1)
        shape = analyze_handler(p)
        # 'a' should be skipped (bound in partial)
        assert "a" not in shape.parameters
        assert "b" in shape.parameters

    def test_analyze_callable_instance(self) -> None:
        class Handler:
            def __init__(self, db: str) -> None:
                self.db = db

            async def __call__(self, x: int) -> str:
                return f"{self.db}:{x}"

        h = Handler("testdb")
        shape = analyze_handler(h)
        assert shape.instance_info is not None
        assert shape.instance_info.cls is Handler
        assert "db" in shape.instance_info.init_parameters

    def test_analyze_generator(self) -> None:
        def gen() -> object:
            yield 1

        shape = analyze_handler(gen)
        assert shape.is_generator is True


class TestExtractClassMethods:
    def test_extract_existing(self) -> None:
        class MyClass:
            def foo(self) -> None:
                pass

            def bar(self) -> None:
                pass

        methods = list(extract_class_methods(MyClass, ("foo", "bar", "missing")))
        assert len(methods) == 2
        names = [n for n, _ in methods]
        assert "foo" in names
        assert "bar" in names


class TestGetViewClass:
    def test_class_input(self) -> None:
        class MyView:
            pass

        assert get_view_class(MyView) is MyView

    def test_view_class_attr(self) -> None:
        class MyView:
            pass

        class Wrapper:
            view_class = MyView

        assert get_view_class(Wrapper()) is MyView

    def test_none_for_plain(self) -> None:
        assert get_view_class("string") is None


class TestResolveDescriptor:
    def test_non_descriptor(self) -> None:
        def fn() -> str:
            return "ok"

        assert resolve_descriptor(fn) is fn

    def test_descriptor(self) -> None:
        class Desc:
            def __get__(self, obj: object, owner: type | None = None) -> str:
                return "resolved"

        result = resolve_descriptor(Desc())
        assert result == "resolved"


class TestDecoratorInfo:
    def test_create(self) -> None:
        def wrapper() -> str:
            return "ok"

        info = DecoratorInfo(
            wrapper=wrapper,
            wrapper_name="wrapper",
            wrapper_module="test",
        )
        assert info.wrapper_name == "wrapper"
        assert info.wrapper_module == "test"


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 8: Integration — compile_derive + materialize
# ═══════════════════════════════════════════════════════════════════════════════


class TestCompileDeriveIntegration:
    def test_compile_derive_basic(self) -> None:
        from emergent.wire.derive._crud import http_crud

        @schema_meta(http_crud("/items", Items))
        @dataclass
        class TestItem:
            id: Annotated[int, Identity()]
            name: str

        ctxs = compile_derive(TestItem)
        assert len(ctxs) == 1
        ctx = ctxs[0]
        assert len(ctx.specs) > 0

    def test_materialize_produces_endpoint(self) -> None:
        from emergent.wire.derive._crud import http_crud

        @schema_meta(http_crud("/products", Items))
        @dataclass
        class TestProduct:
            id: Annotated[int, Identity()]
            title: str
            price: float

        ctxs = compile_derive(TestProduct)
        endpoint = materialize(ctxs[0])
        assert endpoint is not None
        assert len(endpoint.exposures) > 0

    def test_materialize_empty_ctx(self) -> None:
        ctx: DeriveCtx[Item] = DeriveCtx.from_entity(Item)
        endpoint = materialize(ctx)
        assert len(endpoint.exposures) == 0

    def test_compile_with_paginated(self) -> None:
        from emergent.wire.derive._crud import http_crud
        from emergent.wire.derive._transforms import Paginated

        @schema_meta(http_crud("/things", Items), Paginated(25))
        @dataclass
        class TestThing:
            id: Annotated[int, Identity()]
            value: str

        ctxs = compile_derive(TestThing)
        endpoint = materialize(ctxs[0])
        assert len(endpoint.exposures) > 0

    def test_compile_with_soft_delete(self) -> None:
        from emergent.wire.derive._crud import http_crud
        from emergent.wire.derive._transforms import SoftDelete

        @schema_meta(http_crud("/soft", Items), SoftDelete())
        @dataclass
        class TestSoft:
            id: Annotated[int, Identity()]
            name: str
            deleted_at: str | None = None

        ctxs = compile_derive(TestSoft)
        endpoint = materialize(ctxs[0])
        assert len(endpoint.exposures) > 0

    def test_compile_with_timestamped(self) -> None:
        from emergent.wire.derive._crud import http_crud
        from emergent.wire.derive._transforms import Timestamped

        @schema_meta(http_crud("/timed", Items), Timestamped())
        @dataclass
        class TestTimed:
            id: Annotated[int, Identity()]
            name: str
            created_at: str | None = None
            updated_at: str | None = None

        ctxs = compile_derive(TestTimed)
        endpoint = materialize(ctxs[0])
        assert len(endpoint.exposures) > 0

    def test_compile_with_searchable(self) -> None:
        from emergent.wire.derive._crud import http_crud
        from emergent.wire.derive._transforms import Searchable

        @schema_meta(http_crud("/search", Items), Searchable(fields=("name",)))
        @dataclass
        class TestSearch:
            id: Annotated[int, Identity()]
            name: str

        ctxs = compile_derive(TestSearch)
        endpoint = materialize(ctxs[0])
        assert len(endpoint.exposures) > 0

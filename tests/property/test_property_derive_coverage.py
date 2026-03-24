# pyright: reportPrivateUsage=false
"""Property-based coverage tests for derive modules.

Targets remaining uncovered lines in:
- _handler.py (45%) — handler templates, materialization, op_defaults, WrappedTemplate
- _transforms.py (32%) — DeriveModifiable transforms (Paginated, Sorted, Readonly, etc.)
- _pipeline.py (47%) — pipeline step execution
- _project.py (73%) — field projections, response specs, converters
- patterns/methods.py (36%) — method decorators, Methods/MethodDialect capabilities
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Annotated, Any

import pytest
from kungfu import Error, Ok, Result

from emergent.wire.axis.schema._universal import Identity, schema_meta
from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger
from emergent.wire.derive._compile import compile_derive
from emergent.wire.derive._crud import (
    LIST,
    http_crud,
)
from emergent.wire.derive._ctx import DeriveCtx
from emergent.wire.derive._effects import (
    Cacheable,
    Creates,
    Deletes,
    Idempotent,
    Mutation,
    Pageable,
    Read,
    Sortable,
    Updates,
    has_effect,
)
from emergent.wire.derive._errors import DomainError, NotFound
from emergent.wire.derive._handler import (
    CachedFetchOneById,
    CountAll,
    DeleteOne,
    DescriptiveTemplate,
    ExistsById,
    FetchMany,
    FetchOneById,
    HandlerSpec,
    HandlerTemplate,
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
from emergent.wire.derive._opspec import (
    Op,
    OpSpec,
    build_from_spec,
    normalize_op,
)
from emergent.wire.derive._project import (
    AllFields,
    BoolResponse,
    ComposedResponseSpec,
    CountResponse,
    CursorPaginatedResponse,
    CustomResponse,
    EmptyResponse,
    EntityResponse,
    ExcludeFields,
    ExcludeFromProjection,
    IdOnly,
    ListResponse,
    MergeProjection,
    NoFields,
    NonId,
    OkResponse,
    OptionalNonId,
    PaginatedResponse,
    RequiredNonId,
    SelectFields,
    all_fields,
    bool_response,
    count_response,
    cursor_paginated_response,
    custom_response,
    dict_converter,
    empty_response,
    entity_response,
    exclude,
    exclude_from,
    fields,
    id_only,
    list_response,
    merge,
    no_fields,
    non_id,
    ok_response,
    optional_non_id,
    paginated_response,
    required_non_id,
    response_converter,
    response_fields,
)
from emergent.wire.derive._transforms import (
    CreateOnly,
    EffectDeprecated,
    EffectRateLimited,
    Filtered,
    MutationsOnly,
    OnlyOps,
    Paginated,
    ProjectResponse,
    Readonly,
    Searchable,
    SoftDelete,
    Sorted,
    Timestamped,
    UpdateOnly,
    WithoutCreate,
    WithoutDelete,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Test-local entity types
# ═══════════════════════════════════════════════════════════════════════════════


class ItemProvider:
    """Provider node stub."""


@dataclass
class Item:
    id: Annotated[int, Identity()]
    name: str
    value: int


@dataclass
class TimestampedItem:
    id: Annotated[int, Identity()]
    name: str
    created_at: str | None = None
    updated_at: str | None = None


@dataclass
class SoftDeletableItem:
    id: Annotated[int, Identity()]
    name: str
    deleted_at: str | None = None


@dataclass
class RichItem:
    id: Annotated[int, Identity()]
    name: str
    description: str
    status: str
    value: int


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Handler Templates — op_defaults coverage
# ═══════════════════════════════════════════════════════════════════════════════


class TestHandlerOpDefaults:
    """Cover op_defaults() for all DescriptiveTemplate implementations."""

    def test_fetch_many_op_defaults(self) -> None:
        fm = FetchMany()
        op = fm.op_defaults()
        assert op.name == "List"
        assert isinstance(op.handler_template, FetchMany)
        assert has_effect(op.effects, Read)
        assert has_effect(op.effects, Pageable)
        assert has_effect(op.effects, Sortable)

    def test_fetch_one_by_id_op_defaults(self) -> None:
        fob = FetchOneById()
        op = fob.op_defaults()
        assert op.name == "Get"
        assert isinstance(op.handler_template, FetchOneById)
        assert has_effect(op.effects, Read)
        assert has_effect(op.effects, Idempotent)
        assert has_effect(op.effects, Cacheable)

    def test_insert_new_op_defaults(self) -> None:
        ins = InsertNew()
        op = ins.op_defaults()
        assert op.name == "Create"
        assert isinstance(op.handler_template, InsertNew)
        assert has_effect(op.effects, Creates)

    def test_update_existing_op_defaults(self) -> None:
        upd = UpdateExisting()
        op = upd.op_defaults()
        assert op.name == "Update"
        assert isinstance(op.handler_template, UpdateExisting)
        assert has_effect(op.effects, Updates)
        assert has_effect(op.effects, Idempotent)

    def test_delete_one_op_defaults(self) -> None:
        d = DeleteOne()
        op = d.op_defaults()
        assert op.name == "Delete"
        assert isinstance(op.handler_template, DeleteOne)
        assert has_effect(op.effects, Deletes)
        assert has_effect(op.effects, Idempotent)

    def test_paginated_fetch_many_op_defaults(self) -> None:
        pfm = PaginatedFetchMany(page_size=30)
        op = pfm.op_defaults()
        assert op.name == "List"
        assert isinstance(op.handler_template, PaginatedFetchMany)
        assert has_effect(op.effects, Read)
        assert has_effect(op.effects, Pageable)

    def test_cached_fetch_one_op_defaults(self) -> None:
        cfob = CachedFetchOneById()
        op = cfob.op_defaults()
        assert op.name == "Get"
        assert isinstance(op.handler_template, CachedFetchOneById)
        assert has_effect(op.effects, Read)
        assert has_effect(op.effects, Cacheable)

    def test_patch_existing_op_defaults(self) -> None:
        pe = PatchExisting()
        op = pe.op_defaults()
        assert op.name == "Patch"
        assert isinstance(op.handler_template, PatchExisting)
        assert has_effect(op.effects, Updates)

    def test_sorted_fetch_many_op_defaults(self) -> None:
        sfm = SortedFetchMany(default_sort="name", default_order="desc")
        op = sfm.op_defaults()
        assert op.name == "List"
        assert isinstance(op.handler_template, SortedFetchMany)
        assert has_effect(op.effects, Read)
        assert has_effect(op.effects, Sortable)

    def test_exists_by_id_op_defaults(self) -> None:
        ebi = ExistsById()
        op = ebi.op_defaults()
        assert op.name == "Exists"
        assert isinstance(op.handler_template, ExistsById)
        assert has_effect(op.effects, Read)
        assert has_effect(op.effects, Idempotent)

    def test_count_all_op_defaults(self) -> None:
        ca = CountAll()
        op = ca.op_defaults()
        assert op.name == "Count"
        assert isinstance(op.handler_template, CountAll)
        assert has_effect(op.effects, Read)

    def test_upsert_existing_op_defaults(self) -> None:
        ue = UpsertExisting()
        op = ue.op_defaults()
        assert op.name == "Upsert"
        assert isinstance(op.handler_template, UpsertExisting)
        assert has_effect(op.effects, Creates)
        assert has_effect(op.effects, Updates)
        assert has_effect(op.effects, Idempotent)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. normalize_op — DescriptiveTemplate and Op passthrough
# ═══════════════════════════════════════════════════════════════════════════════


class TestNormalizeOp:
    """Cover normalize_op with both Op and DescriptiveTemplate."""

    def test_op_passthrough(self) -> None:
        result = normalize_op(LIST)
        assert result is LIST

    def test_descriptive_template_converts(self) -> None:
        fm = FetchMany()
        result = normalize_op(fm)
        assert isinstance(result, Op)
        assert result.name == "List"

    def test_insert_new_as_descriptive(self) -> None:
        ins = InsertNew()
        result = normalize_op(ins)
        assert result.name == "Create"

    def test_delete_one_as_descriptive(self) -> None:
        d = DeleteOne()
        result = normalize_op(d)
        assert result.name == "Delete"


# ═══════════════════════════════════════════════════════════════════════════════
# 3. WrappedTemplate and wrap_template
# ═══════════════════════════════════════════════════════════════════════════════


class TestWrappedTemplate:
    """Cover WrappedTemplate.build and wrap_template helper."""

    def test_wrap_template_creates_wrapped(self) -> None:
        inner = FetchMany()

        def wrapper(inner: Any, spec: Any) -> Any:
            return inner

        wt = wrap_template(inner, wrapper)
        assert isinstance(wt, WrappedTemplate)
        assert wt.inner is inner
        assert wt.wrapper is wrapper

    def test_wrapped_template_is_handler_template(self) -> None:
        wt = WrappedTemplate(
            inner=FetchMany(),
            wrapper=lambda inner, spec: inner,
        )
        assert isinstance(wt, HandlerTemplate)

    def test_wrapped_template_build(self) -> None:
        inner = FetchMany()
        call_log: list[str] = []

        def wrapper(inner: Any, spec: Any) -> Any:
            call_log.append("wrapped")
            return inner

        wt = WrappedTemplate(inner=inner, wrapper=wrapper)
        spec = HandlerSpec(
            entity=Item,
            entity_name="Item",
            identity_names=("id",),
            non_identity_names=("name", "value"),
            base_query=None,
        )
        handler = wt.build(spec)
        assert handler is not None
        assert "wrapped" in call_log


# ═══════════════════════════════════════════════════════════════════════════════
# 4. HandlerSpec construction
# ═══════════════════════════════════════════════════════════════════════════════


class TestHandlerSpec:
    """Cover HandlerSpec dataclass construction with various params."""

    def test_basic_construction(self) -> None:
        spec = HandlerSpec(
            entity=Item,
            entity_name="Item",
            identity_names=("id",),
            non_identity_names=("name", "value"),
            base_query=None,
        )
        assert spec.entity is Item
        assert spec.entity_name == "Item"
        assert spec.identity_names == ("id",)
        assert spec.scope_fields == ()
        assert spec.effects == ()

    def test_with_scope_fields(self) -> None:
        spec = HandlerSpec(
            entity=Item,
            entity_name="Item",
            identity_names=("id",),
            non_identity_names=("name", "value"),
            base_query=None,
            scope_fields=("user_id",),
        )
        assert spec.scope_fields == ("user_id",)

    def test_with_effects(self) -> None:
        spec = HandlerSpec(
            entity=Item,
            entity_name="Item",
            identity_names=("id",),
            non_identity_names=("name", "value"),
            base_query=None,
            effects=(Read(), Pageable()),
        )
        assert len(spec.effects) == 2


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Transforms — compile_derive integration
# ═══════════════════════════════════════════════════════════════════════════════


class TestTransformsPaginated:
    """Cover Paginated transform — replaces FetchMany with PaginatedFetchMany."""

    def test_paginated_replaces_list_handler(self) -> None:
        @schema_meta(http_crud("/items", ItemProvider), Paginated(50))
        @dataclass
        class PaginatedItem:
            id: Annotated[int, Identity()]
            name: str

        ctxs = compile_derive(PaginatedItem)
        assert len(ctxs) == 1
        ctx = ctxs[0]
        list_specs = [s for s in ctx.specs if s.name == "List"]
        assert len(list_specs) == 1
        list_spec = list_specs[0]
        assert isinstance(list_spec.handler_template, PaginatedFetchMany)
        # Check extra fields added
        extra_names = [f[0] for f in list_spec.extra_op_fields]
        assert "page" in extra_names
        assert "page_size" in extra_names

    def test_paginated_default_page_size(self) -> None:
        @schema_meta(http_crud("/items2", ItemProvider), Paginated())
        @dataclass
        class DefaultPaginatedItem:
            id: Annotated[int, Identity()]
            name: str

        ctxs = compile_derive(DefaultPaginatedItem)
        ctx = ctxs[0]
        list_specs = [s for s in ctx.specs if s.name == "List"]
        list_spec = list_specs[0]
        assert isinstance(list_spec.handler_template, PaginatedFetchMany)


class TestTransformsSorted:
    """Cover Sorted transform — replaces FetchMany with SortedFetchMany."""

    def test_sorted_replaces_list_handler(self) -> None:
        @schema_meta(http_crud("/sitems", ItemProvider), Sorted("name", "desc"))
        @dataclass
        class SortedItem:
            id: Annotated[int, Identity()]
            name: str

        ctxs = compile_derive(SortedItem)
        ctx = ctxs[0]
        list_specs = [s for s in ctx.specs if s.name == "List"]
        assert len(list_specs) == 1
        list_spec = list_specs[0]
        assert isinstance(list_spec.handler_template, SortedFetchMany)
        extra_names = [f[0] for f in list_spec.extra_op_fields]
        assert "sort" in extra_names
        assert "order" in extra_names

    def test_sorted_default_values(self) -> None:
        @schema_meta(http_crud("/sitems2", ItemProvider), Sorted())
        @dataclass
        class DefaultSortedItem:
            id: Annotated[int, Identity()]
            name: str

        ctxs = compile_derive(DefaultSortedItem)
        ctx = ctxs[0]
        list_specs = [s for s in ctx.specs if s.name == "List"]
        assert isinstance(list_specs[0].handler_template, SortedFetchMany)


class TestTransformsEffectFilters:
    """Cover Readonly, MutationsOnly, WithoutDelete, WithoutCreate, etc."""

    def test_readonly_removes_mutations(self) -> None:
        @schema_meta(http_crud("/ritems", ItemProvider), Readonly())
        @dataclass
        class ReadonlyItem:
            id: Annotated[int, Identity()]
            name: str

        ctxs = compile_derive(ReadonlyItem)
        ctx = ctxs[0]
        for s in ctx.specs:
            assert not has_effect(s.effects, Mutation)
        spec_names = {s.name for s in ctx.specs}
        assert "List" in spec_names
        assert "Get" in spec_names
        assert "Create" not in spec_names

    def test_mutations_only_removes_reads(self) -> None:
        @schema_meta(http_crud("/mitems", ItemProvider), MutationsOnly())
        @dataclass
        class MutationsItem:
            id: Annotated[int, Identity()]
            name: str

        ctxs = compile_derive(MutationsItem)
        ctx = ctxs[0]
        for s in ctx.specs:
            assert has_effect(s.effects, Mutation)
        spec_names = {s.name for s in ctx.specs}
        assert "List" not in spec_names
        assert "Get" not in spec_names

    def test_without_delete(self) -> None:
        @schema_meta(http_crud("/nditems", ItemProvider), WithoutDelete())
        @dataclass
        class NoDeleteItem:
            id: Annotated[int, Identity()]
            name: str

        ctxs = compile_derive(NoDeleteItem)
        ctx = ctxs[0]
        spec_names = {s.name for s in ctx.specs}
        assert "Delete" not in spec_names
        assert "Create" in spec_names

    def test_without_create(self) -> None:
        @schema_meta(http_crud("/ncitems", ItemProvider), WithoutCreate())
        @dataclass
        class NoCreateItem:
            id: Annotated[int, Identity()]
            name: str

        ctxs = compile_derive(NoCreateItem)
        ctx = ctxs[0]
        spec_names = {s.name for s in ctx.specs}
        assert "Create" not in spec_names
        assert "List" in spec_names

    def test_create_only(self) -> None:
        @schema_meta(http_crud("/coitems", ItemProvider), CreateOnly())
        @dataclass
        class CreateOnlyItem:
            id: Annotated[int, Identity()]
            name: str

        ctxs = compile_derive(CreateOnlyItem)
        ctx = ctxs[0]
        spec_names = {s.name for s in ctx.specs}
        assert spec_names == {"Create"}

    def test_update_only(self) -> None:
        @schema_meta(http_crud("/uoitems", ItemProvider), UpdateOnly())
        @dataclass
        class UpdateOnlyItem:
            id: Annotated[int, Identity()]
            name: str

        ctxs = compile_derive(UpdateOnlyItem)
        ctx = ctxs[0]
        spec_names = {s.name for s in ctx.specs}
        assert spec_names == {"Update", "Patch"}

    def test_only_ops(self) -> None:
        @schema_meta(http_crud("/ooitems", ItemProvider), OnlyOps(("List", "Get")))
        @dataclass
        class OnlyOpsItem:
            id: Annotated[int, Identity()]
            name: str

        ctxs = compile_derive(OnlyOpsItem)
        ctx = ctxs[0]
        spec_names = {s.name for s in ctx.specs}
        assert spec_names == {"List", "Get"}


class TestTransformsProjectResponse:
    """Cover ProjectResponse transform."""

    def test_project_response_excludes_fields(self) -> None:
        @schema_meta(http_crud("/prjitems", ItemProvider), ProjectResponse(exclude=("value",)))
        @dataclass
        class ProjectedItem:
            id: Annotated[int, Identity()]
            name: str
            value: int

        ctxs = compile_derive(ProjectedItem)
        ctx = ctxs[0]
        # Read ops should have modified response spec
        list_specs = [s for s in ctx.specs if s.name == "List"]
        assert len(list_specs) == 1
        list_spec = list_specs[0]
        assert isinstance(list_spec.response_spec, ListResponse)
        assert list_spec.response_spec.exclude == ("value",)


class TestTransformsSoftDelete:
    """Cover SoftDelete composed transform."""

    def test_soft_delete_replaces_delete_handler(self) -> None:
        @schema_meta(http_crud("/sditems", ItemProvider), SoftDelete("deleted_at"))
        @dataclass
        class SoftDeleteItem:
            id: Annotated[int, Identity()]
            name: str
            deleted_at: str | None = None

        ctxs = compile_derive(SoftDeleteItem)
        ctx = ctxs[0]
        delete_specs = [s for s in ctx.specs if s.name == "Delete"]
        assert len(delete_specs) == 1
        assert isinstance(delete_specs[0].handler_template, SoftDeleteMark)

    def test_soft_delete_excludes_field_from_create(self) -> None:
        @schema_meta(http_crud("/sditems2", ItemProvider), SoftDelete())
        @dataclass
        class SoftDelete2Item:
            id: Annotated[int, Identity()]
            name: str
            deleted_at: str | None = None

        ctxs = compile_derive(SoftDelete2Item)
        ctx = ctxs[0]
        create_specs = [s for s in ctx.specs if s.name == "Create"]
        assert len(create_specs) == 1
        assert "deleted_at" not in create_specs[0].input_fields


class TestTransformsTimestamped:
    """Cover Timestamped composed transform."""

    def test_timestamped_replaces_handlers(self) -> None:
        @schema_meta(http_crud("/tsitems", ItemProvider), Timestamped())
        @dataclass
        class TimestampEntity:
            id: Annotated[int, Identity()]
            name: str
            created_at: str | None = None
            updated_at: str | None = None

        ctxs = compile_derive(TimestampEntity)
        ctx = ctxs[0]
        create_specs = [s for s in ctx.specs if s.name == "Create"]
        assert len(create_specs) == 1
        assert isinstance(create_specs[0].handler_template, TimestampInsert)

        update_specs = [s for s in ctx.specs if s.name == "Update"]
        assert len(update_specs) == 1
        assert isinstance(update_specs[0].handler_template, TimestampUpdate)

    def test_timestamped_excludes_from_create(self) -> None:
        @schema_meta(http_crud("/tsitems2", ItemProvider), Timestamped("created_at", "updated_at"))
        @dataclass
        class TimestampEntity2:
            id: Annotated[int, Identity()]
            name: str
            created_at: str | None = None
            updated_at: str | None = None

        ctxs = compile_derive(TimestampEntity2)
        ctx = ctxs[0]
        create_specs = [s for s in ctx.specs if s.name == "Create"]
        assert "created_at" not in create_specs[0].input_fields
        assert "updated_at" not in create_specs[0].input_fields


class TestTransformsFiltered:
    """Cover Filtered transform."""

    def test_filtered_with_explicit_fields(self) -> None:
        @schema_meta(http_crud("/fitems", ItemProvider), Filtered(("name", "value")))
        @dataclass
        class FilteredItem:
            id: Annotated[int, Identity()]
            name: str
            value: int

        ctxs = compile_derive(FilteredItem)
        ctx = ctxs[0]
        list_specs = [s for s in ctx.specs if s.name == "List"]
        assert len(list_specs) == 1
        list_spec = list_specs[0]
        extra_names = [f[0] for f in list_spec.extra_op_fields]
        assert "filter_name" in extra_names
        assert "filter_value" in extra_names
        assert isinstance(list_spec.handler_template, WrappedTemplate)

    def test_filtered_no_fields_no_filterable_effect(self) -> None:
        """Filtered() with no fields and no Filterable effect should be a no-op."""
        @schema_meta(http_crud("/fitems2", ItemProvider), Filtered())
        @dataclass
        class Filtered2Item:
            id: Annotated[int, Identity()]
            name: str

        ctxs = compile_derive(Filtered2Item)
        ctx = ctxs[0]
        list_specs = [s for s in ctx.specs if s.name == "List"]
        # Handler should NOT be wrapped since no fields specified and no Filterable effect
        assert not isinstance(list_specs[0].handler_template, WrappedTemplate)


class TestTransformsSearchable:
    """Cover Searchable transform."""

    def test_searchable_with_explicit_fields(self) -> None:
        @schema_meta(http_crud("/searchitems", ItemProvider), Searchable(("name",)))
        @dataclass
        class SearchItem:
            id: Annotated[int, Identity()]
            name: str

        ctxs = compile_derive(SearchItem)
        ctx = ctxs[0]
        list_specs = [s for s in ctx.specs if s.name == "List"]
        assert len(list_specs) == 1
        extra_names = [f[0] for f in list_specs[0].extra_op_fields]
        assert "q" in extra_names
        assert isinstance(list_specs[0].handler_template, WrappedTemplate)

    def test_searchable_no_fields_no_effect(self) -> None:
        """Searchable() with no fields and no SearchableEffect should be a no-op."""
        @schema_meta(http_crud("/searchitems2", ItemProvider), Searchable())
        @dataclass
        class Search2Item:
            id: Annotated[int, Identity()]
            name: str

        ctxs = compile_derive(Search2Item)
        ctx = ctxs[0]
        list_specs = [s for s in ctx.specs if s.name == "List"]
        assert not isinstance(list_specs[0].handler_template, WrappedTemplate)


class TestTransformsEffectRateLimited:
    """Cover EffectRateLimited transform."""

    def test_effect_rate_limited_with_rate(self) -> None:
        @schema_meta(http_crud("/rlitems", ItemProvider), EffectRateLimited(rpm=120))
        @dataclass
        class RateLimitedItem:
            id: Annotated[int, Identity()]
            name: str

        ctxs = compile_derive(RateLimitedItem)
        ctx = ctxs[0]
        # No ops declare RateLimited effect by default, so no change
        for s in ctx.specs:
            # Should still compile without error
            assert s.name in {"List", "Get", "Create", "Update", "Patch", "Delete"}


class TestTransformsEffectDeprecated:
    """Cover EffectDeprecated transform."""

    def test_effect_deprecated_no_deprecated_ops(self) -> None:
        @schema_meta(http_crud("/deprititems", ItemProvider), EffectDeprecated())
        @dataclass
        class DeprecatedItem:
            id: Annotated[int, Identity()]
            name: str

        ctxs = compile_derive(DeprecatedItem)
        ctx = ctxs[0]
        # No ops declare Deprecated effect by default, so no change
        assert len(ctx.specs) == 6


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Pipeline Steps — direct execution
# ═══════════════════════════════════════════════════════════════════════════════


def _make_spec() -> HandlerSpec[Item]:
    """Helper: create a HandlerSpec for Item."""
    return HandlerSpec(
        entity=Item,
        entity_name="Item",
        identity_names=("id",),
        non_identity_names=("name", "value"),
        base_query=None,
    )


@dataclass
class FakeOp:
    """Minimal op stub for pipeline tests."""
    id: int = 1
    provider: object = None
    page: int = 1
    page_size: int = 20


def _fake_op() -> Any:
    """Create a FakeOp cast to satisfy HasProvider protocol in tests."""
    return FakeOp()


class TestPipelineSteps:
    """Cover pipeline step execution through Pipeline.build."""

    def test_pipeline_construction(self) -> None:
        from emergent.wire.derive._pipeline import (
            FetchAll,
            Pipeline,
            ScopeQuery,
            WrapItems,
        )

        p = Pipeline(ScopeQuery(), FetchAll(), WrapItems())
        assert len(p.steps) == 3

    def test_pipeline_context_creation(self) -> None:
        from emergent.wire.derive._pipeline import PipelineContext

        pctx = PipelineContext(spec=_make_spec(), op=_fake_op())
        assert pctx.query is None
        assert pctx.existing is None
        assert pctx.entity_data is None
        assert pctx.items is None
        assert pctx.result is None
        assert pctx.extras == {}

    @pytest.mark.asyncio
    async def test_set_timestamp_step(self) -> None:
        from emergent.wire.derive._pipeline import PipelineContext, SetTimestamp

        pctx = PipelineContext(spec=_make_spec(), op=_fake_op())
        step = SetTimestamp(field_name="created_at")

        result = await step.execute(pctx)
        assert result.entity_data is not None
        assert "created_at" in result.entity_data

    @pytest.mark.asyncio
    async def test_set_timestamp_step_existing_data(self) -> None:
        from emergent.wire.derive._pipeline import PipelineContext, SetTimestamp

        pctx = PipelineContext(spec=_make_spec(), op=_fake_op())
        pctx.entity_data = {"name": "test"}
        step = SetTimestamp(field_name="updated_at")

        result = await step.execute(pctx)
        assert result.entity_data is not None
        assert "updated_at" in result.entity_data
        assert result.entity_data["name"] == "test"

    @pytest.mark.asyncio
    async def test_set_field_value_step(self) -> None:
        from emergent.wire.derive._pipeline import PipelineContext, SetFieldValue

        pctx = PipelineContext(spec=_make_spec(), op=_fake_op())
        step = SetFieldValue(field_name="status", value_fn=lambda op: "active")

        result = await step.execute(pctx)
        assert result.entity_data is not None
        assert result.entity_data["status"] == "active"

    @pytest.mark.asyncio
    async def test_set_field_value_step_existing_data(self) -> None:
        from emergent.wire.derive._pipeline import PipelineContext, SetFieldValue

        pctx = PipelineContext(spec=_make_spec(), op=_fake_op())
        pctx.entity_data = {"name": "existing"}
        step = SetFieldValue(field_name="value", value_fn=lambda op: 42)

        result = await step.execute(pctx)
        assert result.entity_data is not None
        assert result.entity_data["value"] == 42
        assert result.entity_data["name"] == "existing"

    @pytest.mark.asyncio
    async def test_wrap_ok_step_with_result(self) -> None:
        from emergent.wire.derive._pipeline import PipelineContext, WrapOk

        pctx = PipelineContext(spec=_make_spec(), op=_fake_op())
        pctx.result = Item(id=1, name="test", value=10)
        step = WrapOk()

        result = await step.execute(pctx)
        assert isinstance(result, Ok)
        assert isinstance(result.value, Item)
        assert result.value.name == "test"

    @pytest.mark.asyncio
    async def test_wrap_ok_step_with_items(self) -> None:
        from emergent.wire.derive._pipeline import PipelineContext, WrapOk

        pctx = PipelineContext(spec=_make_spec(), op=_fake_op())
        pctx.items = [Item(id=1, name="a", value=1)]
        step = WrapOk()

        result = await step.execute(pctx)
        assert isinstance(result, Ok)
        assert isinstance(result.value, list)

    @pytest.mark.asyncio
    async def test_wrap_ok_step_with_existing(self) -> None:
        from emergent.wire.derive._pipeline import PipelineContext, WrapOk

        pctx = PipelineContext(spec=_make_spec(), op=_fake_op())
        pctx.existing = Item(id=1, name="ex", value=99)
        step = WrapOk()

        result = await step.execute(pctx)
        assert isinstance(result, Ok)
        assert isinstance(result.value, Item)
        assert result.value.name == "ex"

    @pytest.mark.asyncio
    async def test_wrap_exists_step_found(self) -> None:
        from emergent.wire.derive._pipeline import PipelineContext, WrapExists

        pctx = PipelineContext(spec=_make_spec(), op=_fake_op())
        pctx.existing = Item(id=1, name="a", value=1)
        step = WrapExists()

        result = await step.execute(pctx)
        assert isinstance(result, Ok)
        assert result.value is True

    @pytest.mark.asyncio
    async def test_wrap_exists_step_not_found(self) -> None:
        from emergent.wire.derive._pipeline import PipelineContext, WrapExists

        pctx = PipelineContext(spec=_make_spec(), op=_fake_op())
        step = WrapExists()

        result = await step.execute(pctx)
        assert isinstance(result, Ok)
        assert result.value is False

    @pytest.mark.asyncio
    async def test_wrap_count_step(self) -> None:
        from emergent.wire.derive._pipeline import PipelineContext, WrapCount

        pctx = PipelineContext(spec=_make_spec(), op=_fake_op())
        pctx.extras["total"] = 42
        step = WrapCount()

        result = await step.execute(pctx)
        assert isinstance(result, Ok)
        assert result.value == 42

    @pytest.mark.asyncio
    async def test_wrap_paginated_step(self) -> None:
        from emergent.wire.derive._pipeline import PipelineContext, WrapPaginated

        fake_op: Any = FakeOp(page=2, page_size=10)
        pctx = PipelineContext(spec=_make_spec(), op=fake_op)
        pctx.items = [Item(id=1, name="a", value=1)]
        pctx.extras["total"] = 100
        step = WrapPaginated(default_page_size=10)

        result = await step.execute(pctx)
        assert isinstance(result, Ok)
        val: Any = result.value
        assert val["total"] == 100
        assert val["page"] == 2
        assert val["page_size"] == 10

    @pytest.mark.asyncio
    async def test_wrap_items_step(self) -> None:
        from emergent.wire.derive._pipeline import PipelineContext, WrapItems

        pctx = PipelineContext(spec=_make_spec(), op=_fake_op())
        pctx.items = [Item(id=1, name="a", value=1), Item(id=2, name="b", value=2)]
        step = WrapItems()

        result = await step.execute(pctx)
        assert isinstance(result, Ok)
        wrapped_items: Any = result.value
        assert len(wrapped_items) == 2


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Field Projections — project method coverage
# ═══════════════════════════════════════════════════════════════════════════════


class TestFieldProjections:
    """Cover all field projection classes project() methods."""

    def _make_ctx(self) -> DeriveCtx[Item]:
        return DeriveCtx.from_entity(Item)

    def test_all_fields(self) -> None:
        ctx = self._make_ctx()
        result = AllFields().project(ctx)
        assert "id" in result
        assert "name" in result
        assert "value" in result

    def test_id_only(self) -> None:
        ctx = self._make_ctx()
        result = IdOnly().project(ctx)
        assert "id" in result
        assert "name" not in result

    def test_non_id(self) -> None:
        ctx = self._make_ctx()
        result = NonId().project(ctx)
        assert "id" not in result
        assert "name" in result
        assert "value" in result

    def test_no_fields(self) -> None:
        ctx = self._make_ctx()
        result = NoFields().project(ctx)
        assert len(result) == 0

    def test_required_non_id(self) -> None:
        ctx = self._make_ctx()
        result = RequiredNonId().project(ctx)
        # name and value are required (no default)
        assert "name" in result
        assert "value" in result
        assert "id" not in result

    def test_select_fields(self) -> None:
        ctx = self._make_ctx()
        result = SelectFields(names=("name",)).project(ctx)
        assert "name" in result
        assert "id" not in result
        assert "value" not in result

    def test_exclude_fields(self) -> None:
        ctx = self._make_ctx()
        result = ExcludeFields(names=("id",)).project(ctx)
        assert "id" not in result
        assert "name" in result

    def test_optional_non_id(self) -> None:
        ctx = self._make_ctx()
        result = OptionalNonId().project(ctx)
        assert "name" in result
        assert "id" not in result

    def test_merge_projection(self) -> None:
        ctx = self._make_ctx()
        result = MergeProjection(left=IdOnly(), right=NonId()).project(ctx)
        assert "id" in result
        assert "name" in result
        assert "value" in result

    def test_exclude_from_projection(self) -> None:
        ctx = self._make_ctx()
        result = ExcludeFromProjection(
            inner=AllFields(), names=("value",)
        ).project(ctx)
        assert "id" in result
        assert "name" in result
        assert "value" not in result


class TestConvenienceConstructors:
    """Cover convenience constructor functions."""

    def test_all_constructors_return_correct_types(self) -> None:
        assert isinstance(all_fields(), AllFields)
        assert isinstance(id_only(), IdOnly)
        assert isinstance(non_id(), NonId)
        assert isinstance(no_fields(), NoFields)
        assert isinstance(required_non_id(), RequiredNonId)
        assert isinstance(fields("a", "b"), SelectFields)
        assert isinstance(exclude("a"), ExcludeFields)
        assert isinstance(optional_non_id(), OptionalNonId)
        assert isinstance(merge(AllFields(), NonId()), MergeProjection)
        assert isinstance(exclude_from(AllFields(), "a"), ExcludeFromProjection)

    def test_response_constructors(self) -> None:
        assert isinstance(entity_response(), EntityResponse)
        assert isinstance(list_response(), ListResponse)
        assert isinstance(ok_response(), OkResponse)
        assert isinstance(paginated_response(), PaginatedResponse)
        assert isinstance(count_response(), CountResponse)
        assert isinstance(bool_response(), BoolResponse)
        assert isinstance(empty_response(), EmptyResponse)
        assert isinstance(cursor_paginated_response(), CursorPaginatedResponse)

    def test_custom_response_constructor(self) -> None:
        def conv(cls: Any, result: Any) -> Any:
            return cls()
        cr = custom_response(field_specs=(("x", int),), converter=conv)
        assert isinstance(cr, CustomResponse)


# ═══════════════════════════════════════════════════════════════════════════════
# 8. Response Specs — resolve method coverage
# ═══════════════════════════════════════════════════════════════════════════════


class TestResponseSpecs:
    """Cover ResponseSpec.resolve() for all implementations."""

    def _make_ctx(self) -> DeriveCtx[Item]:
        return DeriveCtx.from_entity(Item)

    def test_entity_response_resolve(self) -> None:
        ctx = self._make_ctx()
        fields_list, _converter = EntityResponse().resolve(ctx)
        assert len(fields_list) > 0
        field_names = [f[0] for f in fields_list]
        assert "id" in field_names
        assert "name" in field_names

    def test_entity_response_with_exclude(self) -> None:
        ctx = self._make_ctx()
        fields_list, _converter = EntityResponse(exclude=("value",)).resolve(ctx)
        field_names = [f[0] for f in fields_list]
        assert "value" not in field_names
        assert "id" in field_names

    def test_list_response_resolve(self) -> None:
        ctx = self._make_ctx()
        fields_list, _converter = ListResponse().resolve(ctx)
        assert len(fields_list) == 1
        assert fields_list[0][0] == "items"

    def test_list_response_with_exclude(self) -> None:
        ctx = self._make_ctx()
        fields_list, _converter = ListResponse(exclude=("value",)).resolve(ctx)
        assert len(fields_list) == 1
        assert fields_list[0][0] == "items"

    def test_ok_response_resolve(self) -> None:
        ctx = self._make_ctx()
        fields_list, _converter = OkResponse().resolve(ctx)
        assert len(fields_list) == 1
        assert fields_list[0][0] == "success"

    def test_paginated_response_resolve(self) -> None:
        ctx = self._make_ctx()
        fields_list, _converter = PaginatedResponse().resolve(ctx)
        field_names = [f[0] for f in fields_list]
        assert "items" in field_names
        assert "total" in field_names
        assert "page" in field_names
        assert "page_size" in field_names

    def test_count_response_resolve(self) -> None:
        ctx = self._make_ctx()
        fields_list, _converter = CountResponse().resolve(ctx)
        assert len(fields_list) == 1
        assert fields_list[0][0] == "count"

    def test_bool_response_resolve(self) -> None:
        ctx = self._make_ctx()
        fields_list, _converter = BoolResponse().resolve(ctx)
        assert len(fields_list) == 1
        assert fields_list[0][0] == "exists"

    def test_empty_response_resolve(self) -> None:
        ctx = self._make_ctx()
        fields_list, _converter = EmptyResponse().resolve(ctx)
        assert len(fields_list) == 0

    def test_cursor_paginated_response_resolve(self) -> None:
        ctx = self._make_ctx()
        fields_list, _converter = CursorPaginatedResponse().resolve(ctx)
        field_names = [f[0] for f in fields_list]
        assert "items" in field_names
        assert "next_cursor" in field_names
        assert "has_more" in field_names

    def test_custom_response_resolve(self) -> None:
        ctx = self._make_ctx()
        def conv(cls: Any, result: Any) -> Any:
            return cls()
        cr = CustomResponse(field_specs=(("x", int),), converter=conv)
        fields_list, _converter = cr.resolve(ctx)
        assert len(fields_list) == 1
        assert fields_list[0][0] == "x"


class TestResponseHelpers:
    """Cover response_fields and response_converter helpers."""

    def test_response_fields_helper(self) -> None:
        ctx = DeriveCtx.from_entity(Item)
        result = response_fields(EntityResponse(), ctx)
        assert len(result) > 0

    def test_response_converter_helper(self) -> None:
        ctx = DeriveCtx.from_entity(Item)
        conv = response_converter(EntityResponse(), ctx)
        assert callable(conv)


class TestComposedResponseSpec:
    """Cover ComposedResponseSpec."""

    def test_composed_response_spec(self) -> None:
        from emergent.wire.derive._codegen import FieldSpec
        from emergent.wire.derive._project import ResponseConverter

        @dataclass(frozen=True, slots=True)
        class FakeProjection:
            def project_response(self, ctx: DeriveCtx[Any]) -> list[FieldSpec]:
                return [("x", int)]

        @dataclass(frozen=True, slots=True)
        class FakeConverter:
            def build_converter(self, ctx: DeriveCtx[Any]) -> ResponseConverter:
                def _conv(cls: Any, result: Any) -> Any:
                    return cls()
                return _conv

        spec = ComposedResponseSpec(
            projection=FakeProjection(),
            converter=FakeConverter(),
        )
        ctx = DeriveCtx.from_entity(Item)
        fields_list, _conv = spec.resolve(ctx)
        assert len(fields_list) == 1


class TestDictConverter:
    """Cover dict_converter function."""

    def test_dict_converter_with_ok_dict(self) -> None:
        @dataclass
        class Resp:
            x: int = 0
            y: str = ""

        result = dict_converter(Resp, Ok({"x": 1, "y": "hello"}))
        assert isinstance(result, Resp)
        assert result.x == 1

    def test_dict_converter_with_ok_object(self) -> None:
        @dataclass
        class Resp:
            x: int = 0

        @dataclass
        class Source:
            x: int = 42

        result = dict_converter(Resp, Ok(Source(x=42)))
        assert isinstance(result, Resp)
        assert result.x == 42

    def test_dict_converter_with_error(self) -> None:
        @dataclass
        class Resp:
            x: int = 0

        err = NotFound(entity="test", id={"id": 1})
        result = dict_converter(Resp, Error(err))
        assert isinstance(result, NotFound)


# ═══════════════════════════════════════════════════════════════════════════════
# 9. Materialize — full round-trip through compile_derive + materialize
# ═══════════════════════════════════════════════════════════════════════════════


class TestMaterialize:
    """Cover materialize producing Endpoint from DeriveCtx."""

    def test_materialize_empty_ctx(self) -> None:
        ctx: DeriveCtx[Item] = DeriveCtx.from_entity(Item)
        endpoint = materialize(ctx)
        assert len(endpoint.exposures) == 0

    def test_materialize_full_crud(self) -> None:
        @schema_meta(http_crud("/mat_items", ItemProvider))
        @dataclass
        class MatItem:
            id: Annotated[int, Identity()]
            name: str
            value: int

        ctxs = compile_derive(MatItem)
        assert len(ctxs) == 1
        endpoint = materialize(ctxs[0])
        assert len(endpoint.exposures) == 6

    def test_materialize_with_paginated(self) -> None:
        @schema_meta(http_crud("/mat_pitems", ItemProvider), Paginated(25))
        @dataclass
        class MatPItem:
            id: Annotated[int, Identity()]
            name: str

        ctxs = compile_derive(MatPItem)
        endpoint = materialize(ctxs[0])
        assert len(endpoint.exposures) == 6

    def test_materialize_readonly(self) -> None:
        @schema_meta(http_crud("/mat_ritems", ItemProvider), Readonly())
        @dataclass
        class MatRItem:
            id: Annotated[int, Identity()]
            name: str

        ctxs = compile_derive(MatRItem)
        endpoint = materialize(ctxs[0])
        assert len(endpoint.exposures) == 2

    def test_materialize_with_transforms(self) -> None:
        @schema_meta(
            http_crud("/mat_titems", ItemProvider),
            Paginated(10),
            Sorted("name"),
        )
        @dataclass
        class MatTItem:
            id: Annotated[int, Identity()]
            name: str
            value: int

        ctxs = compile_derive(MatTItem)
        endpoint = materialize(ctxs[0])
        # All 6 CRUD ops should still be present
        assert len(endpoint.exposures) == 6


# ═══════════════════════════════════════════════════════════════════════════════
# 10. Methods Pattern — decorators and compilation
# ═══════════════════════════════════════════════════════════════════════════════


class TestMethodDecorators:
    """Cover method decorator functions: post, get, put, delete, patch, command."""

    def test_post_decorator(self) -> None:
        from emergent.wire.derive.patterns.methods import post, TRIGGER_ENTRIES_ATTR

        @post("/api/test")
        async def handler(x: int) -> Result[int, DomainError]:
            return Ok(x)

        entries = getattr(handler, TRIGGER_ENTRIES_ATTR)
        assert len(entries) == 1
        assert isinstance(entries[0].trigger, HTTPRouteTrigger)

    def test_get_decorator(self) -> None:
        from emergent.wire.derive.patterns.methods import get, TRIGGER_ENTRIES_ATTR

        @get("/api/test")
        async def handler(x: int) -> Result[int, DomainError]:
            return Ok(x)

        entries = getattr(handler, TRIGGER_ENTRIES_ATTR)
        assert entries[0].trigger.method == "GET"

    def test_put_decorator(self) -> None:
        from emergent.wire.derive.patterns.methods import put, TRIGGER_ENTRIES_ATTR

        @put("/api/test")
        async def handler(x: int) -> Result[int, DomainError]:
            return Ok(x)

        entries = getattr(handler, TRIGGER_ENTRIES_ATTR)
        assert entries[0].trigger.method == "PUT"

    def test_delete_decorator(self) -> None:
        from emergent.wire.derive.patterns.methods import delete, TRIGGER_ENTRIES_ATTR

        @delete("/api/test")
        async def handler(x: int) -> Result[int, DomainError]:
            return Ok(x)

        entries = getattr(handler, TRIGGER_ENTRIES_ATTR)
        assert entries[0].trigger.method == "DELETE"

    def test_patch_decorator(self) -> None:
        from emergent.wire.derive.patterns.methods import patch, TRIGGER_ENTRIES_ATTR

        @patch("/api/test")
        async def handler(x: int) -> Result[int, DomainError]:
            return Ok(x)

        entries = getattr(handler, TRIGGER_ENTRIES_ATTR)
        assert entries[0].trigger.method == "PATCH"

    def test_command_decorator(self) -> None:
        from emergent.wire.derive.patterns.methods import command, TRIGGER_ENTRIES_ATTR
        from emergent.wire.axis.surface.triggers.cli import CLITrigger

        @command("test-cmd", description="test command")
        async def handler(x: int) -> Result[int, DomainError]:
            return Ok(x)

        entries = getattr(handler, TRIGGER_ENTRIES_ATTR)
        assert len(entries) == 1
        assert isinstance(entries[0].trigger, CLITrigger)

    def test_method_decorator_with_capabilities(self) -> None:
        from emergent.wire.derive.patterns.methods import method, TRIGGER_ENTRIES_ATTR

        trigger = HTTPRouteTrigger("POST", "/test")

        @method(trigger, description="desc", order=50)
        async def handler(x: int) -> Result[int, DomainError]:
            return Ok(x)

        entries = getattr(handler, TRIGGER_ENTRIES_ATTR)
        assert len(entries) == 1
        assert entries[0].description == "desc"
        assert entries[0].order == 50

    def test_multi_trigger_stacking(self) -> None:
        from emergent.wire.derive.patterns.methods import (
            command,
            post,
            TRIGGER_ENTRIES_ATTR,
        )

        @post("/api/test")
        @command("test-cmd")
        async def handler(x: int) -> Result[int, DomainError]:
            return Ok(x)

        entries = getattr(handler, TRIGGER_ENTRIES_ATTR)
        assert len(entries) == 2


class TestOpDecorator:
    """Cover @op decorator."""

    def test_op_decorator_with_name(self) -> None:
        from emergent.wire.derive.patterns.methods import op, OP_ENTRIES_ATTR

        @op("Create", effects=(Creates(),))
        async def handler(x: int) -> Result[int, DomainError]:
            return Ok(x)

        entry = getattr(handler, OP_ENTRIES_ATTR)
        assert entry.name == "Create"
        assert len(entry.effects) == 1

    def test_op_decorator_default_name(self) -> None:
        from emergent.wire.derive.patterns.methods import op, OP_ENTRIES_ATTR

        @op()
        async def my_handler(x: int) -> Result[int, DomainError]:
            return Ok(x)

        entry = getattr(my_handler, OP_ENTRIES_ATTR)
        assert entry.name == "my_handler"


class TestMethodsCapability:
    """Cover Methods SchemaCapability compile_derive_generate."""

    def test_methods_classmethod(self) -> None:
        from emergent.wire.derive.patterns.methods import Methods, post

        @schema_meta(Methods())
        @dataclass
        class MyService:
            @classmethod
            @post("/api/orders")
            async def create(cls, customer: str, total: float) -> Result[int, DomainError]:
                return Ok(1)

        ctxs = compile_derive(MyService)
        assert len(ctxs) == 1
        ctx = ctxs[0]
        assert len(ctx.operations) == 1

    def test_methods_staticmethod(self) -> None:
        from emergent.wire.derive.patterns.methods import Methods, get

        @schema_meta(Methods())
        @dataclass
        class HealthService:
            @staticmethod
            @get("/api/health")
            async def health() -> Result[str, DomainError]:
                return Ok("ok")

        ctxs = compile_derive(HealthService)
        assert len(ctxs) == 1
        ctx = ctxs[0]
        assert len(ctx.operations) == 1

    def test_methods_rejects_sync(self) -> None:
        from emergent.wire.derive.patterns.methods import Methods, post

        with pytest.raises(TypeError, match="must be async"):
            @schema_meta(Methods())
            @dataclass
            class BadService:
                @classmethod
                @post("/api/sync")
                def sync_method(cls, x: int) -> Result[int, DomainError]:
                    return Ok(x)

            compile_derive(BadService)

    def test_methods_materialize(self) -> None:
        from emergent.wire.derive.patterns.methods import Methods, post

        @schema_meta(Methods())
        @dataclass
        class MatService:
            @classmethod
            @post("/api/action")
            async def do_action(cls, value: int) -> Result[int, DomainError]:
                return Ok(value * 2)

        ctxs = compile_derive(MatService)
        endpoint = materialize(ctxs[0])
        assert len(endpoint.exposures) == 1


class TestStubOp:
    """Cover _stub_op helper."""

    def test_stub_op_creates_op(self) -> None:
        from emergent.wire.derive.patterns.methods import _stub_op

        stub = _stub_op("Test", (Creates(),))
        assert stub.name == "Test"
        assert len(stub.effects) == 1


class TestResultTypeFields:
    """Cover _result_type_fields helper."""

    def test_dataclass_result_type(self) -> None:
        from emergent.wire.derive.patterns.methods import _result_type_fields

        @dataclass
        class Resp:
            x: int
            y: str

        result = _result_type_fields(Resp)
        assert "x" in result
        assert "y" in result

    def test_primitive_result_type(self) -> None:
        from emergent.wire.derive.patterns.methods import _result_type_fields

        result = _result_type_fields(int)
        assert result == {"result": int}


# ═══════════════════════════════════════════════════════════════════════════════
# 11. DeriveCtx methods — direct coverage
# ═══════════════════════════════════════════════════════════════════════════════


class TestDeriveCtxMethods:
    """Cover DeriveCtx helper methods directly."""

    def test_from_entity(self) -> None:
        ctx = DeriveCtx.from_entity(Item)
        assert ctx.entity is Item
        assert "id" in ctx.identity_fields
        assert "name" in ctx.fields

    def test_from_subject(self) -> None:
        @dataclass
        class MySubject:
            x: int = 0

        ctx = DeriveCtx.from_subject(MySubject)
        assert ctx.entity is MySubject
        assert len(ctx.fields) == 0

    def test_identity_names(self) -> None:
        ctx = DeriveCtx.from_entity(Item)
        assert ctx.identity_names() == ("id",)

    def test_non_identity_fields(self) -> None:
        ctx = DeriveCtx.from_entity(Item)
        non_id = ctx.non_identity_fields()
        assert "name" in non_id
        assert "value" in non_id
        assert "id" not in non_id

    def test_field_types(self) -> None:
        ctx = DeriveCtx.from_entity(Item)
        ft = ctx.field_types()
        assert "id" in ft
        assert "name" in ft

    def test_field_types_with_exclude(self) -> None:
        ctx = DeriveCtx.from_entity(Item)
        ft = ctx.field_types(exclude=("id",))
        assert "id" not in ft
        assert "name" in ft

    def test_annotated_field_types(self) -> None:
        ctx = DeriveCtx.from_entity(Item)
        aft = ctx.annotated_field_types()
        assert "id" in aft
        assert "name" in aft

    def test_annotated_field_types_with_only(self) -> None:
        ctx = DeriveCtx.from_entity(Item)
        aft = ctx.annotated_field_types(only={"name"})
        assert "name" in aft
        assert "id" not in aft

    def test_add_capability(self) -> None:
        from emergent.wire.derive._error_caps import ErrorTransform

        ctx = DeriveCtx.from_entity(Item)
        ctx2 = ctx.add_capability(ErrorTransform())
        assert len(ctx2.capabilities) == 1
        assert len(ctx.capabilities) == 0  # immutable


# ═══════════════════════════════════════════════════════════════════════════════
# 12. build_from_spec — direct coverage
# ═══════════════════════════════════════════════════════════════════════════════


class TestBuildFromSpec:
    """Cover build_from_spec directly."""

    def test_build_from_spec_produces_operation(self) -> None:
        ctx = DeriveCtx.from_entity(Item)
        from emergent.wire.axis.query import relational
        from emergent.wire.derive._query_strategy import RelationalStrategy

        ctx = replace(
            ctx,
            query_strategy=RelationalStrategy(
                provider_node=ItemProvider,
                base_query=relational(Item),
            ),
        )

        trigger = HTTPRouteTrigger("GET", "/test")
        spec = OpSpec(
            name="List",
            entity_name="Item",
            input_fields={},
            request_fields={},
            response_spec=ListResponse(),
            handler_template=FetchMany(),
            trigger=trigger,
            effects=(Read(),),
        )

        op_type, handler, exposure = build_from_spec(spec, ctx)
        assert op_type is not None
        assert callable(handler)
        assert exposure.trigger is trigger


# ═══════════════════════════════════════════════════════════════════════════════
# 13. Additional edge cases
# ═══════════════════════════════════════════════════════════════════════════════


class TestEdgeCases:
    """Various edge cases for uncovered paths."""

    def test_handler_template_protocol_check(self) -> None:
        """FetchMany is a HandlerTemplate."""
        assert isinstance(FetchMany(), HandlerTemplate)

    def test_descriptive_template_protocol_check(self) -> None:
        """FetchMany is a DescriptiveTemplate."""
        assert isinstance(FetchMany(), DescriptiveTemplate)

    def test_paginated_fetch_many_custom_size(self) -> None:
        pfm = PaginatedFetchMany(page_size=100)
        assert pfm.page_size == 100

    def test_sorted_fetch_many_fields(self) -> None:
        sfm = SortedFetchMany(default_sort="name", default_order="desc")
        assert sfm.default_sort == "name"
        assert sfm.default_order == "desc"

    def test_set_field_construction(self) -> None:
        sf = SetField(field_name="status", value_fn=lambda op: "active")
        assert sf.field_name == "status"

    def test_soft_delete_mark_construction(self) -> None:
        sdm = SoftDeleteMark(deleted_field="removed_at")
        assert sdm.deleted_field == "removed_at"

    def test_timestamp_insert_construction(self) -> None:
        ti = TimestampInsert(created_field="created", updated_field="updated")
        assert ti.created_field == "created"
        assert ti.updated_field == "updated"

    def test_timestamp_update_construction(self) -> None:
        tu = TimestampUpdate(updated_field="updated")
        assert tu.updated_field == "updated"

    def test_cached_fetch_one_construction(self) -> None:
        cfob = CachedFetchOneById()
        assert isinstance(cfob, HandlerTemplate)

    def test_upsert_existing_construction(self) -> None:
        ue = UpsertExisting()
        assert isinstance(ue, HandlerTemplate)

    def test_exists_by_id_construction(self) -> None:
        ebi = ExistsById()
        assert isinstance(ebi, HandlerTemplate)

    def test_count_all_construction(self) -> None:
        ca = CountAll()
        assert isinstance(ca, HandlerTemplate)

    def test_pipeline_step_protocol_check(self) -> None:
        from emergent.wire.derive._pipeline import (
            FetchAll,
            IdentityFilter,
            PipelineStep,
            ScopeQuery,
        )

        assert isinstance(ScopeQuery(), PipelineStep)
        assert isinstance(IdentityFilter(), PipelineStep)
        assert isinstance(FetchAll(), PipelineStep)

    def test_paginate_step_construction(self) -> None:
        from emergent.wire.derive._pipeline import Paginate

        p = Paginate(default_page_size=50)
        assert p.default_page_size == 50

    def test_in_memory_sort_step_construction(self) -> None:
        from emergent.wire.derive._pipeline import InMemorySort

        s = InMemorySort(default_sort="name", default_order="desc")
        assert s.default_sort == "name"
        assert s.default_order == "desc"

    @pytest.mark.asyncio
    async def test_copy_existing_to_data_step(self) -> None:
        from emergent.wire.derive._pipeline import CopyExistingToData, PipelineContext

        pctx = PipelineContext(spec=_make_spec(), op=_fake_op())
        pctx.existing = Item(id=1, name="copy_test", value=99)
        step = CopyExistingToData()

        result = await step.execute(pctx)
        assert result.entity_data is not None
        assert result.entity_data["name"] == "copy_test"
        assert result.entity_data["id"] == 1
        assert result.entity_data["value"] == 99

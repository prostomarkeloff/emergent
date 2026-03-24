# pyright: reportPrivateUsage=false
"""Deep property-based tests for the Derive axis internals.

Covers:
- _transforms.py: all DeriveModifiable transforms (frozen, construction, immutability)
- _handler.py: handler templates (frozen, construction, op_defaults, WrappedTemplate)
- _pipeline.py: pipeline steps and Pipeline (frozen, construction, PipelineContext)
- _project.py: field projections and response specs (frozen, construction, convenience fns)
- _opspec.py: OpSpec and Op (frozen, construction, defaults, normalize_op)
- _crud.py: CRUD constants and generators (op counts, effects, http_crud/cli_crud)
- _effects.py: all effect types (hierarchy, has_effect, get_effect, completeness)
"""

from __future__ import annotations

import pytest
from dataclasses import FrozenInstanceError, dataclass
from typing import Annotated

from emergent.wire.axis.schema import Identity
from emergent.wire.derive._effects import (
    Auditable,
    Bulk,
    Cacheable,
    Creates,
    Deletes,
    DerivationEffect,
    Deprecated,
    Emits,
    Filterable,
    Idempotent,
    Mutation,
    Pageable,
    Public,
    RateLimited,
    Read,
    Searchable as SearchableEffect,
    Sortable,
    Updates,
    Validated,
    Versioned,
    get_effect,
    has_effect,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Test-local entity types
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class User:
    id: Annotated[int, Identity()]
    name: str
    email: str


@dataclass
class Article:
    id: Annotated[int, Identity()]
    title: str
    body: str
    author_id: int


# ═══════════════════════════════════════════════════════════════════════════════
# 1. _effects.py — effect types, hierarchy, dispatch helpers
# ═══════════════════════════════════════════════════════════════════════════════


class TestEffectTypes:
    """All effect types exist, are frozen, and hierarchy is correct."""

    def test_read_is_derivation_effect(self) -> None:
        assert isinstance(Read(), DerivationEffect)

    def test_mutation_is_derivation_effect(self) -> None:
        assert isinstance(Mutation(), DerivationEffect)

    def test_creates_is_mutation(self) -> None:
        assert isinstance(Creates(), Mutation)

    def test_updates_is_mutation(self) -> None:
        assert isinstance(Updates(), Mutation)

    def test_deletes_is_mutation(self) -> None:
        assert isinstance(Deletes(), Mutation)

    def test_creates_is_derivation_effect(self) -> None:
        assert isinstance(Creates(), DerivationEffect)

    def test_idempotent_is_derivation_effect(self) -> None:
        assert isinstance(Idempotent(), DerivationEffect)

    def test_pageable_defaults(self) -> None:
        p = Pageable()
        assert p.default_size == 20

    def test_pageable_custom_size(self) -> None:
        p = Pageable(default_size=50)
        assert p.default_size == 50

    def test_sortable_defaults(self) -> None:
        s = Sortable()
        assert s.default_field == ""
        assert s.default_order == "asc"

    def test_cacheable_default_ttl(self) -> None:
        c = Cacheable()
        assert c.ttl == 0

    def test_cacheable_custom_ttl(self) -> None:
        c = Cacheable(ttl=300)
        assert c.ttl == 300

    def test_filterable_defaults(self) -> None:
        f = Filterable()
        assert f.fields == ()

    def test_filterable_with_fields(self) -> None:
        f = Filterable(fields=("name", "status"))
        assert f.fields == ("name", "status")

    def test_searchable_effect_defaults(self) -> None:
        s = SearchableEffect()
        assert s.fields == ()

    def test_public_is_derivation_effect(self) -> None:
        assert isinstance(Public(), DerivationEffect)

    def test_rate_limited_defaults(self) -> None:
        r = RateLimited()
        assert r.rpm == 60

    def test_rate_limited_custom(self) -> None:
        r = RateLimited(rpm=120)
        assert r.rpm == 120

    def test_validated_is_derivation_effect(self) -> None:
        assert isinstance(Validated(), DerivationEffect)

    def test_versioned_defaults(self) -> None:
        v = Versioned()
        assert v.version_field == "version"

    def test_bulk_defaults(self) -> None:
        b = Bulk()
        assert b.max_batch_size == 100

    def test_auditable_defaults(self) -> None:
        a = Auditable()
        assert a.level == "info"

    def test_emits_defaults(self) -> None:
        e = Emits()
        assert e.event == ""

    def test_emits_custom(self) -> None:
        e = Emits(event="user.created")
        assert e.event == "user.created"

    def test_deprecated_defaults(self) -> None:
        d = Deprecated()
        assert d.since == ""
        assert d.message == ""

    def test_deprecated_custom(self) -> None:
        d = Deprecated(since="v2.0", message="Use /v2/users instead")
        assert d.since == "v2.0"
        assert d.message == "Use /v2/users instead"

    def test_effect_frozen_read(self) -> None:
        r = Read()
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            r.dummy = True  # type: ignore[attr-defined]

    def test_effect_frozen_creates(self) -> None:
        c = Creates()
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            c.dummy = True  # type: ignore[attr-defined]

    def test_effect_frozen_pageable(self) -> None:
        p = Pageable()
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            p.default_size = 99  # type: ignore[misc]


class TestHasEffect:
    """has_effect dispatches via isinstance hierarchy."""

    def test_has_effect_direct_match(self) -> None:
        effects = (Read(),)
        assert has_effect(effects, Read) is True

    def test_has_effect_no_match(self) -> None:
        effects = (Read(),)
        assert has_effect(effects, Mutation) is False

    def test_has_effect_hierarchy_creates_is_mutation(self) -> None:
        effects = (Creates(),)
        assert has_effect(effects, Mutation) is True

    def test_has_effect_hierarchy_deletes_is_mutation(self) -> None:
        effects = (Deletes(),)
        assert has_effect(effects, Mutation) is True

    def test_has_effect_hierarchy_updates_is_mutation(self) -> None:
        effects = (Updates(),)
        assert has_effect(effects, Mutation) is True

    def test_has_effect_empty(self) -> None:
        assert has_effect((), Read) is False

    def test_has_effect_mixed(self) -> None:
        effects = (Read(), Creates(), Idempotent())
        assert has_effect(effects, Read) is True
        assert has_effect(effects, Creates) is True
        assert has_effect(effects, Mutation) is True
        assert has_effect(effects, Deletes) is False


class TestGetEffect:
    """get_effect returns first matching effect or None."""

    def test_get_effect_found(self) -> None:
        effects = (Read(), Pageable(default_size=50))
        result = get_effect(effects, Pageable)
        assert result is not None
        assert result.default_size == 50

    def test_get_effect_not_found(self) -> None:
        effects = (Read(),)
        assert get_effect(effects, Mutation) is None

    def test_get_effect_hierarchy(self) -> None:
        effects = (Creates(),)
        result = get_effect(effects, Mutation)
        assert isinstance(result, Creates)

    def test_get_effect_first_match(self) -> None:
        effects = (Creates(), Updates())
        result = get_effect(effects, Mutation)
        assert isinstance(result, Creates)

    def test_get_effect_empty(self) -> None:
        assert get_effect((), Read) is None


# ═══════════════════════════════════════════════════════════════════════════════
# 2. _transforms.py — frozen dataclass transforms
# ═══════════════════════════════════════════════════════════════════════════════


class TestTransformConstruction:
    """All transforms are frozen dataclasses with correct defaults."""

    def test_paginated_default(self) -> None:
        from emergent.wire.derive._transforms import Paginated

        p = Paginated()
        assert p.page_size == 20

    def test_paginated_custom(self) -> None:
        from emergent.wire.derive._transforms import Paginated

        p = Paginated(page_size=50)
        assert p.page_size == 50

    def test_paginated_frozen(self) -> None:
        from emergent.wire.derive._transforms import Paginated

        p = Paginated()
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            p.page_size = 100  # type: ignore[misc]

    def test_sorted_defaults(self) -> None:
        from emergent.wire.derive._transforms import Sorted

        s = Sorted()
        assert s.default_sort is None
        assert s.default_order == "asc"

    def test_sorted_custom(self) -> None:
        from emergent.wire.derive._transforms import Sorted

        s = Sorted(default_sort="name", default_order="desc")
        assert s.default_sort == "name"
        assert s.default_order == "desc"

    def test_sorted_frozen(self) -> None:
        from emergent.wire.derive._transforms import Sorted

        s = Sorted()
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            s.default_sort = "x"  # type: ignore[misc]

    def test_readonly_frozen(self) -> None:
        from emergent.wire.derive._transforms import Readonly

        r = Readonly()
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            r.x = 1  # type: ignore[attr-defined]

    def test_mutations_only_frozen(self) -> None:
        from emergent.wire.derive._transforms import MutationsOnly

        m = MutationsOnly()
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            m.x = 1  # type: ignore[attr-defined]

    def test_without_delete_frozen(self) -> None:
        from emergent.wire.derive._transforms import WithoutDelete

        w = WithoutDelete()
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            w.x = 1  # type: ignore[attr-defined]

    def test_without_create_frozen(self) -> None:
        from emergent.wire.derive._transforms import WithoutCreate

        w = WithoutCreate()
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            w.x = 1  # type: ignore[attr-defined]

    def test_create_only_frozen(self) -> None:
        from emergent.wire.derive._transforms import CreateOnly

        c = CreateOnly()
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            c.x = 1  # type: ignore[attr-defined]

    def test_update_only_frozen(self) -> None:
        from emergent.wire.derive._transforms import UpdateOnly

        u = UpdateOnly()
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            u.x = 1  # type: ignore[attr-defined]

    def test_only_ops_construction(self) -> None:
        from emergent.wire.derive._transforms import OnlyOps

        o = OnlyOps(ops=("List", "Get"))
        assert o.ops == ("List", "Get")

    def test_only_ops_frozen(self) -> None:
        from emergent.wire.derive._transforms import OnlyOps

        o = OnlyOps(ops=("List",))
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            o.ops = ("x",)  # type: ignore[misc]

    def test_soft_delete_defaults(self) -> None:
        from emergent.wire.derive._transforms import SoftDelete

        s = SoftDelete()
        assert s.deleted_field == "deleted_at"

    def test_soft_delete_custom(self) -> None:
        from emergent.wire.derive._transforms import SoftDelete

        s = SoftDelete(deleted_field="removed_at")
        assert s.deleted_field == "removed_at"

    def test_soft_delete_frozen(self) -> None:
        from emergent.wire.derive._transforms import SoftDelete

        s = SoftDelete()
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            s.deleted_field = "x"  # type: ignore[misc]

    def test_timestamped_defaults(self) -> None:
        from emergent.wire.derive._transforms import Timestamped

        t = Timestamped()
        assert t.created_field == "created_at"
        assert t.updated_field == "updated_at"

    def test_timestamped_custom(self) -> None:
        from emergent.wire.derive._transforms import Timestamped

        t = Timestamped(created_field="made_at", updated_field="modified_at")
        assert t.created_field == "made_at"
        assert t.updated_field == "modified_at"

    def test_timestamped_frozen(self) -> None:
        from emergent.wire.derive._transforms import Timestamped

        t = Timestamped()
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            t.created_field = "x"  # type: ignore[misc]

    def test_project_response_construction(self) -> None:
        from emergent.wire.derive._transforms import ProjectResponse

        p = ProjectResponse(exclude=("secret", "password"))
        assert p.exclude == ("secret", "password")
        assert p.effect is Read

    def test_project_response_custom_effect(self) -> None:
        from emergent.wire.derive._transforms import ProjectResponse

        p = ProjectResponse(exclude=("x",), effect=Creates)
        assert p.effect is Creates

    def test_project_response_frozen(self) -> None:
        from emergent.wire.derive._transforms import ProjectResponse

        p = ProjectResponse(exclude=("x",))
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            p.exclude = ()  # type: ignore[misc]

    def test_filtered_defaults(self) -> None:
        from emergent.wire.derive._transforms import Filtered

        f = Filtered()
        assert f.fields == ()

    def test_filtered_with_fields(self) -> None:
        from emergent.wire.derive._transforms import Filtered

        f = Filtered(fields=("name", "status"))
        assert f.fields == ("name", "status")

    def test_filtered_frozen(self) -> None:
        from emergent.wire.derive._transforms import Filtered

        f = Filtered()
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            f.fields = ("x",)  # type: ignore[misc]

    def test_searchable_defaults(self) -> None:
        from emergent.wire.derive._transforms import Searchable

        s = Searchable()
        assert s.fields == ()

    def test_searchable_with_fields(self) -> None:
        from emergent.wire.derive._transforms import Searchable

        s = Searchable(fields=("name", "bio"))
        assert s.fields == ("name", "bio")

    def test_searchable_frozen(self) -> None:
        from emergent.wire.derive._transforms import Searchable

        s = Searchable()
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            s.fields = ("x",)  # type: ignore[misc]

    def test_with_timeout_construction(self) -> None:
        from emergent.wire.derive._transforms import WithTimeout

        t = WithTimeout(seconds=30.0)
        assert t.seconds == 30.0

    def test_with_timeout_frozen(self) -> None:
        from emergent.wire.derive._transforms import WithTimeout

        t = WithTimeout(seconds=30.0)
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            t.seconds = 60.0  # type: ignore[misc]

    def test_with_retry_defaults(self) -> None:
        from emergent.wire.derive._transforms import WithRetry

        r = WithRetry()
        assert r.max_retries == 3

    def test_with_retry_custom(self) -> None:
        from emergent.wire.derive._transforms import WithRetry

        r = WithRetry(max_retries=5)
        assert r.max_retries == 5

    def test_with_retry_frozen(self) -> None:
        from emergent.wire.derive._transforms import WithRetry

        r = WithRetry()
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            r.max_retries = 10  # type: ignore[misc]

    def test_with_rate_limit_construction(self) -> None:
        from emergent.wire.derive._transforms import WithRateLimit

        rl = WithRateLimit(rpm=120)
        assert rl.rpm == 120

    def test_with_rate_limit_frozen(self) -> None:
        from emergent.wire.derive._transforms import WithRateLimit

        rl = WithRateLimit(rpm=60)
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            rl.rpm = 100  # type: ignore[misc]

    def test_effect_rate_limited_defaults(self) -> None:
        from emergent.wire.derive._transforms import EffectRateLimited

        erl = EffectRateLimited()
        assert erl.rpm is None

    def test_effect_rate_limited_custom(self) -> None:
        from emergent.wire.derive._transforms import EffectRateLimited

        erl = EffectRateLimited(rpm=30)
        assert erl.rpm == 30

    def test_effect_deprecated_frozen(self) -> None:
        from emergent.wire.derive._transforms import EffectDeprecated

        ed = EffectDeprecated()
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            ed.x = 1  # type: ignore[attr-defined]


# ═══════════════════════════════════════════════════════════════════════════════
# 3. _handler.py — handler templates
# ═══════════════════════════════════════════════════════════════════════════════


class TestHandlerTemplates:
    """Handler templates are frozen, constructible, and have op_defaults."""

    def test_fetch_many_frozen(self) -> None:
        from emergent.wire.derive._handler import FetchMany

        f = FetchMany()
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            f.x = 1  # type: ignore[attr-defined]

    def test_fetch_many_op_defaults(self) -> None:
        from emergent.wire.derive._handler import FetchMany

        op = FetchMany().op_defaults()
        assert op.name == "List"
        assert has_effect(op.effects, Read)
        assert has_effect(op.effects, Pageable)

    def test_fetch_one_by_id_op_defaults(self) -> None:
        from emergent.wire.derive._handler import FetchOneById

        op = FetchOneById().op_defaults()
        assert op.name == "Get"
        assert has_effect(op.effects, Read)
        assert has_effect(op.effects, Cacheable)

    def test_insert_new_op_defaults(self) -> None:
        from emergent.wire.derive._handler import InsertNew

        op = InsertNew().op_defaults()
        assert op.name == "Create"
        assert has_effect(op.effects, Creates)

    def test_update_existing_op_defaults(self) -> None:
        from emergent.wire.derive._handler import UpdateExisting

        op = UpdateExisting().op_defaults()
        assert op.name == "Update"
        assert has_effect(op.effects, Updates)
        assert has_effect(op.effects, Idempotent)

    def test_delete_one_op_defaults(self) -> None:
        from emergent.wire.derive._handler import DeleteOne

        op = DeleteOne().op_defaults()
        assert op.name == "Delete"
        assert has_effect(op.effects, Deletes)

    def test_paginated_fetch_many_defaults(self) -> None:
        from emergent.wire.derive._handler import PaginatedFetchMany

        p = PaginatedFetchMany()
        assert p.page_size == 20

    def test_paginated_fetch_many_custom(self) -> None:
        from emergent.wire.derive._handler import PaginatedFetchMany

        p = PaginatedFetchMany(page_size=50)
        assert p.page_size == 50

    def test_paginated_fetch_many_frozen(self) -> None:
        from emergent.wire.derive._handler import PaginatedFetchMany

        p = PaginatedFetchMany()
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            p.page_size = 100  # type: ignore[misc]

    def test_paginated_fetch_many_op_defaults(self) -> None:
        from emergent.wire.derive._handler import PaginatedFetchMany

        op = PaginatedFetchMany().op_defaults()
        assert op.name == "List"
        assert has_effect(op.effects, Read)
        assert has_effect(op.effects, Pageable)

    def test_sorted_fetch_many_defaults(self) -> None:
        from emergent.wire.derive._handler import SortedFetchMany

        s = SortedFetchMany()
        assert s.default_sort is None
        assert s.default_order == "asc"

    def test_sorted_fetch_many_custom(self) -> None:
        from emergent.wire.derive._handler import SortedFetchMany

        s = SortedFetchMany(default_sort="name", default_order="desc")
        assert s.default_sort == "name"
        assert s.default_order == "desc"

    def test_sorted_fetch_many_frozen(self) -> None:
        from emergent.wire.derive._handler import SortedFetchMany

        s = SortedFetchMany()
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            s.default_sort = "x"  # type: ignore[misc]

    def test_sorted_fetch_many_op_defaults(self) -> None:
        from emergent.wire.derive._handler import SortedFetchMany

        op = SortedFetchMany().op_defaults()
        assert op.name == "List"
        assert has_effect(op.effects, Read)
        assert has_effect(op.effects, Sortable)

    def test_soft_delete_mark_defaults(self) -> None:
        from emergent.wire.derive._handler import SoftDeleteMark

        s = SoftDeleteMark()
        assert s.deleted_field == "deleted_at"

    def test_soft_delete_mark_custom(self) -> None:
        from emergent.wire.derive._handler import SoftDeleteMark

        s = SoftDeleteMark(deleted_field="removed_at")
        assert s.deleted_field == "removed_at"

    def test_soft_delete_mark_frozen(self) -> None:
        from emergent.wire.derive._handler import SoftDeleteMark

        s = SoftDeleteMark()
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            s.deleted_field = "x"  # type: ignore[misc]

    def test_timestamp_insert_construction(self) -> None:
        from emergent.wire.derive._handler import TimestampInsert

        t = TimestampInsert(created_field="created_at", updated_field="updated_at")
        assert t.created_field == "created_at"
        assert t.updated_field == "updated_at"

    def test_timestamp_insert_frozen(self) -> None:
        from emergent.wire.derive._handler import TimestampInsert

        t = TimestampInsert(created_field="a", updated_field="b")
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            t.created_field = "x"  # type: ignore[misc]

    def test_timestamp_update_construction(self) -> None:
        from emergent.wire.derive._handler import TimestampUpdate

        t = TimestampUpdate(updated_field="updated_at")
        assert t.updated_field == "updated_at"

    def test_timestamp_update_frozen(self) -> None:
        from emergent.wire.derive._handler import TimestampUpdate

        t = TimestampUpdate(updated_field="a")
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            t.updated_field = "x"  # type: ignore[misc]

    def test_patch_existing_op_defaults(self) -> None:
        from emergent.wire.derive._handler import PatchExisting

        op = PatchExisting().op_defaults()
        assert op.name == "Patch"
        assert has_effect(op.effects, Updates)

    def test_upsert_existing_op_defaults(self) -> None:
        from emergent.wire.derive._handler import UpsertExisting

        op = UpsertExisting().op_defaults()
        assert op.name == "Upsert"
        assert has_effect(op.effects, Creates)
        assert has_effect(op.effects, Updates)

    def test_exists_by_id_op_defaults(self) -> None:
        from emergent.wire.derive._handler import ExistsById

        op = ExistsById().op_defaults()
        assert op.name == "Exists"
        assert has_effect(op.effects, Read)

    def test_count_all_op_defaults(self) -> None:
        from emergent.wire.derive._handler import CountAll

        op = CountAll().op_defaults()
        assert op.name == "Count"
        assert has_effect(op.effects, Read)

    def test_cached_fetch_one_by_id_op_defaults(self) -> None:
        from emergent.wire.derive._handler import CachedFetchOneById

        op = CachedFetchOneById().op_defaults()
        assert op.name == "Get"
        assert has_effect(op.effects, Read)
        assert has_effect(op.effects, Cacheable)

    def test_set_field_construction(self) -> None:
        from emergent.wire.derive._handler import SetField

        s = SetField(field_name="status", value_fn=lambda op: "active")
        assert s.field_name == "status"

    def test_set_field_frozen(self) -> None:
        from emergent.wire.derive._handler import SetField

        s = SetField(field_name="status", value_fn=lambda op: "active")
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            s.field_name = "x"  # type: ignore[misc]

    def test_handler_spec_construction(self) -> None:
        from emergent.wire.derive._handler import HandlerSpec

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
        assert spec.scope_fields == ()
        assert spec.effects == ()

    def test_handler_spec_frozen(self) -> None:
        from emergent.wire.derive._handler import HandlerSpec

        spec = HandlerSpec(
            entity=User, entity_name="User",
            identity_names=("id",), non_identity_names=("name",),
            base_query=None,
        )
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            spec.entity_name = "X"  # type: ignore[misc]

    def test_wrapped_template_construction(self) -> None:
        from emergent.wire.derive._handler import FetchMany, WrappedTemplate

        inner = FetchMany()

        def wrapper(inner_handler: object, spec: object) -> object:
            return inner_handler

        wt = WrappedTemplate(inner=inner, wrapper=wrapper)  # type: ignore[arg-type]
        assert wt.inner is inner

    def test_wrapped_template_frozen(self) -> None:
        from emergent.wire.derive._handler import FetchMany, WrappedTemplate

        wt = WrappedTemplate(inner=FetchMany(), wrapper=lambda i, s: i)  # type: ignore[arg-type]
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            wt.inner = FetchMany()  # type: ignore[misc]

    def test_wrap_template_helper(self) -> None:
        from emergent.wire.derive._handler import FetchMany, WrappedTemplate, wrap_template

        inner = FetchMany()

        def wrapper(i: object, s: object) -> object:
            return i

        result = wrap_template(inner, wrapper)  # type: ignore[arg-type]
        assert isinstance(result, WrappedTemplate)
        assert result.inner is inner

    def test_handler_template_is_protocol(self) -> None:
        from emergent.wire.derive._handler import FetchMany, HandlerTemplate

        assert isinstance(FetchMany(), HandlerTemplate)

    def test_descriptive_template_is_protocol(self) -> None:
        from emergent.wire.derive._handler import DescriptiveTemplate, FetchMany

        assert isinstance(FetchMany(), DescriptiveTemplate)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. _pipeline.py — pipeline steps and Pipeline construction
# ═══════════════════════════════════════════════════════════════════════════════


class TestPipelineConstruction:
    """Pipeline and pipeline steps are frozen and constructible."""

    def test_pipeline_construction(self) -> None:
        from emergent.wire.derive._pipeline import Pipeline, ScopeQuery, FetchAll, WrapItems

        p = Pipeline(ScopeQuery(), FetchAll(), WrapItems())
        assert len(p.steps) == 3

    def test_pipeline_frozen(self) -> None:
        from emergent.wire.derive._pipeline import Pipeline, ScopeQuery

        p = Pipeline(ScopeQuery())
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            p.steps = ()  # type: ignore[misc]

    def test_pipeline_empty(self) -> None:
        from emergent.wire.derive._pipeline import Pipeline

        p = Pipeline()
        assert p.steps == ()

    def test_scope_query_frozen(self) -> None:
        from emergent.wire.derive._pipeline import ScopeQuery

        s = ScopeQuery()
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            s.x = 1  # type: ignore[attr-defined]

    def test_identity_filter_frozen(self) -> None:
        from emergent.wire.derive._pipeline import IdentityFilter

        i = IdentityFilter()
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            i.x = 1  # type: ignore[attr-defined]

    def test_paginate_defaults(self) -> None:
        from emergent.wire.derive._pipeline import Paginate

        p = Paginate()
        assert p.default_page_size == 20

    def test_paginate_custom(self) -> None:
        from emergent.wire.derive._pipeline import Paginate

        p = Paginate(default_page_size=50)
        assert p.default_page_size == 50

    def test_paginate_frozen(self) -> None:
        from emergent.wire.derive._pipeline import Paginate

        p = Paginate()
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            p.default_page_size = 99  # type: ignore[misc]

    def test_fetch_all_frozen(self) -> None:
        from emergent.wire.derive._pipeline import FetchAll

        f = FetchAll()
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            f.x = 1  # type: ignore[attr-defined]

    def test_fetch_or_not_found_frozen(self) -> None:
        from emergent.wire.derive._pipeline import FetchOrNotFound

        f = FetchOrNotFound()
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            f.x = 1  # type: ignore[attr-defined]

    def test_fetch_by_identity_frozen(self) -> None:
        from emergent.wire.derive._pipeline import FetchByIdentity

        f = FetchByIdentity()
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            f.x = 1  # type: ignore[attr-defined]

    def test_count_total_frozen(self) -> None:
        from emergent.wire.derive._pipeline import CountTotal

        c = CountTotal()
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            c.x = 1  # type: ignore[attr-defined]

    def test_build_entity_data_frozen(self) -> None:
        from emergent.wire.derive._pipeline import BuildEntityData

        b = BuildEntityData()
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            b.x = 1  # type: ignore[attr-defined]

    def test_merge_fields_frozen(self) -> None:
        from emergent.wire.derive._pipeline import MergeFields

        m = MergeFields()
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            m.x = 1  # type: ignore[attr-defined]

    def test_patch_merge_fields_frozen(self) -> None:
        from emergent.wire.derive._pipeline import PatchMergeFields

        p = PatchMergeFields()
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            p.x = 1  # type: ignore[attr-defined]

    def test_copy_existing_to_data_frozen(self) -> None:
        from emergent.wire.derive._pipeline import CopyExistingToData

        c = CopyExistingToData()
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            c.x = 1  # type: ignore[attr-defined]

    def test_set_timestamp_construction(self) -> None:
        from emergent.wire.derive._pipeline import SetTimestamp

        s = SetTimestamp(field_name="created_at")
        assert s.field_name == "created_at"

    def test_set_timestamp_frozen(self) -> None:
        from emergent.wire.derive._pipeline import SetTimestamp

        s = SetTimestamp(field_name="created_at")
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            s.field_name = "x"  # type: ignore[misc]

    def test_set_field_value_construction(self) -> None:
        from emergent.wire.derive._pipeline import SetFieldValue

        s = SetFieldValue(field_name="status", value_fn=lambda op: "active")
        assert s.field_name == "status"

    def test_set_field_value_frozen(self) -> None:
        from emergent.wire.derive._pipeline import SetFieldValue

        s = SetFieldValue(field_name="status", value_fn=lambda op: "active")
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            s.field_name = "x"  # type: ignore[misc]

    def test_provider_insert_frozen(self) -> None:
        from emergent.wire.derive._pipeline import ProviderInsert

        p = ProviderInsert()
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            p.x = 1  # type: ignore[attr-defined]

    def test_provider_update_frozen(self) -> None:
        from emergent.wire.derive._pipeline import ProviderUpdate

        p = ProviderUpdate()
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            p.x = 1  # type: ignore[attr-defined]

    def test_provider_delete_frozen(self) -> None:
        from emergent.wire.derive._pipeline import ProviderDelete

        p = ProviderDelete()
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            p.x = 1  # type: ignore[attr-defined]

    def test_in_memory_sort_defaults(self) -> None:
        from emergent.wire.derive._pipeline import InMemorySort

        s = InMemorySort()
        assert s.default_sort is None
        assert s.default_order == "asc"

    def test_in_memory_sort_custom(self) -> None:
        from emergent.wire.derive._pipeline import InMemorySort

        s = InMemorySort(default_sort="name", default_order="desc")
        assert s.default_sort == "name"
        assert s.default_order == "desc"

    def test_in_memory_sort_frozen(self) -> None:
        from emergent.wire.derive._pipeline import InMemorySort

        s = InMemorySort()
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            s.default_sort = "x"  # type: ignore[misc]

    def test_wrap_ok_frozen(self) -> None:
        from emergent.wire.derive._pipeline import WrapOk

        w = WrapOk()
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            w.x = 1  # type: ignore[attr-defined]

    def test_wrap_items_frozen(self) -> None:
        from emergent.wire.derive._pipeline import WrapItems

        w = WrapItems()
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            w.x = 1  # type: ignore[attr-defined]

    def test_wrap_paginated_defaults(self) -> None:
        from emergent.wire.derive._pipeline import WrapPaginated

        w = WrapPaginated()
        assert w.default_page_size == 20

    def test_wrap_paginated_frozen(self) -> None:
        from emergent.wire.derive._pipeline import WrapPaginated

        w = WrapPaginated()
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            w.default_page_size = 99  # type: ignore[misc]

    def test_wrap_count_frozen(self) -> None:
        from emergent.wire.derive._pipeline import WrapCount

        w = WrapCount()
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            w.x = 1  # type: ignore[attr-defined]

    def test_wrap_exists_frozen(self) -> None:
        from emergent.wire.derive._pipeline import WrapExists

        w = WrapExists()
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            w.x = 1  # type: ignore[attr-defined]

    def test_check_cache_frozen(self) -> None:
        from emergent.wire.derive._pipeline import CheckCache

        c = CheckCache()
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            c.x = 1  # type: ignore[attr-defined]

    def test_populate_cache_frozen(self) -> None:
        from emergent.wire.derive._pipeline import PopulateCache

        p = PopulateCache()
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            p.x = 1  # type: ignore[attr-defined]

    def test_pipeline_step_protocol(self) -> None:
        from emergent.wire.derive._pipeline import PipelineStep, ScopeQuery

        assert isinstance(ScopeQuery(), PipelineStep)

    def test_pipeline_context_is_mutable(self) -> None:
        from emergent.wire.derive._pipeline import PipelineContext
        from emergent.wire.derive._handler import HandlerSpec

        spec = HandlerSpec(
            entity=User, entity_name="User",
            identity_names=("id",), non_identity_names=("name",),
            base_query=None,
        )

        @dataclass
        class FakeOp:
            provider: object = None

        pctx = PipelineContext(spec=spec, op=FakeOp())  # type: ignore[arg-type]
        # PipelineContext is NOT frozen -- it's mutable accumulator
        pctx.existing = None
        pctx.items = [User(id=1, name="a", email="x")]
        assert pctx.items is not None
        assert pctx.extras == {}


# ═══════════════════════════════════════════════════════════════════════════════
# 5. _project.py — field projections and response specs
# ═══════════════════════════════════════════════════════════════════════════════


class TestFieldProjections:
    """Field projection types are frozen and constructible."""

    def test_all_fields_frozen(self) -> None:
        from emergent.wire.derive._project import AllFields

        a = AllFields()
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            a.x = 1  # type: ignore[attr-defined]

    def test_id_only_frozen(self) -> None:
        from emergent.wire.derive._project import IdOnly

        i = IdOnly()
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            i.x = 1  # type: ignore[attr-defined]

    def test_non_id_frozen(self) -> None:
        from emergent.wire.derive._project import NonId

        n = NonId()
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            n.x = 1  # type: ignore[attr-defined]

    def test_no_fields_frozen(self) -> None:
        from emergent.wire.derive._project import NoFields

        n = NoFields()
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            n.x = 1  # type: ignore[attr-defined]

    def test_required_non_id_frozen(self) -> None:
        from emergent.wire.derive._project import RequiredNonId

        r = RequiredNonId()
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            r.x = 1  # type: ignore[attr-defined]

    def test_select_fields_construction(self) -> None:
        from emergent.wire.derive._project import SelectFields

        s = SelectFields(names=("name", "email"))
        assert s.names == ("name", "email")

    def test_select_fields_frozen(self) -> None:
        from emergent.wire.derive._project import SelectFields

        s = SelectFields(names=("name",))
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            s.names = ("x",)  # type: ignore[misc]

    def test_exclude_fields_construction(self) -> None:
        from emergent.wire.derive._project import ExcludeFields

        e = ExcludeFields(names=("password",))
        assert e.names == ("password",)

    def test_exclude_fields_frozen(self) -> None:
        from emergent.wire.derive._project import ExcludeFields

        e = ExcludeFields(names=("x",))
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            e.names = ("y",)  # type: ignore[misc]

    def test_exclude_from_projection_construction(self) -> None:
        from emergent.wire.derive._project import AllFields, ExcludeFromProjection

        inner = AllFields()
        e = ExcludeFromProjection(inner=inner, names=("password",))
        assert e.inner is inner
        assert e.names == ("password",)

    def test_optional_non_id_frozen(self) -> None:
        from emergent.wire.derive._project import OptionalNonId

        o = OptionalNonId()
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            o.x = 1  # type: ignore[attr-defined]

    def test_merge_projection_construction(self) -> None:
        from emergent.wire.derive._project import IdOnly, MergeProjection, OptionalNonId

        m = MergeProjection(left=IdOnly(), right=OptionalNonId())
        assert isinstance(m.left, IdOnly)
        assert isinstance(m.right, OptionalNonId)

    def test_merge_projection_frozen(self) -> None:
        from emergent.wire.derive._project import IdOnly, MergeProjection, OptionalNonId

        m = MergeProjection(left=IdOnly(), right=OptionalNonId())
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            m.left = IdOnly()  # type: ignore[misc]


class TestResponseSpecs:
    """Response spec types are frozen and constructible."""

    def test_entity_response_defaults(self) -> None:
        from emergent.wire.derive._project import EntityResponse

        e = EntityResponse()
        assert e.exclude == ()

    def test_entity_response_custom(self) -> None:
        from emergent.wire.derive._project import EntityResponse

        e = EntityResponse(exclude=("password",))
        assert e.exclude == ("password",)

    def test_entity_response_frozen(self) -> None:
        from emergent.wire.derive._project import EntityResponse

        e = EntityResponse()
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            e.exclude = ("x",)  # type: ignore[misc]

    def test_list_response_defaults(self) -> None:
        from emergent.wire.derive._project import ListResponse

        lr = ListResponse()
        assert lr.exclude == ()

    def test_list_response_custom_exclude(self) -> None:
        from emergent.wire.derive._project import ListResponse

        lr = ListResponse(exclude=("secret",))
        assert lr.exclude == ("secret",)

    def test_ok_response_frozen(self) -> None:
        from emergent.wire.derive._project import OkResponse

        o = OkResponse()
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            o.x = 1  # type: ignore[attr-defined]

    def test_paginated_response_frozen(self) -> None:
        from emergent.wire.derive._project import PaginatedResponse

        p = PaginatedResponse()
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            p.x = 1  # type: ignore[attr-defined]

    def test_count_response_frozen(self) -> None:
        from emergent.wire.derive._project import CountResponse

        c = CountResponse()
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            c.x = 1  # type: ignore[attr-defined]

    def test_bool_response_frozen(self) -> None:
        from emergent.wire.derive._project import BoolResponse

        b = BoolResponse()
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            b.x = 1  # type: ignore[attr-defined]

    def test_empty_response_frozen(self) -> None:
        from emergent.wire.derive._project import EmptyResponse

        e = EmptyResponse()
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            e.x = 1  # type: ignore[attr-defined]

    def test_cursor_paginated_response_frozen(self) -> None:
        from emergent.wire.derive._project import CursorPaginatedResponse

        c = CursorPaginatedResponse()
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            c.x = 1  # type: ignore[attr-defined]

    def test_custom_response_construction(self) -> None:
        from emergent.wire.derive._project import CustomResponse

        def _noop_converter(cls: type, r: object) -> object:
            return cls()

        cr = CustomResponse(
            field_specs=(("name", str),),
            converter=_noop_converter,
        )
        assert cr.field_specs == (("name", str),)

    def test_custom_response_frozen(self) -> None:
        from emergent.wire.derive._project import CustomResponse

        def _noop_converter(cls: type, r: object) -> object:
            return cls()

        cr = CustomResponse(field_specs=(), converter=_noop_converter)
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            cr.field_specs = ()  # type: ignore[misc]

    def test_composed_response_spec_construction(self) -> None:
        from emergent.wire.derive._project import ComposedResponseSpec

        @dataclass(frozen=True, slots=True)
        class FakeProjection:
            def project_response(self, ctx: object) -> list[object]:
                return []

        @dataclass(frozen=True, slots=True)
        class FakeConverter:
            def build_converter(self, ctx: object) -> object:
                def _conv(cls: type, r: object) -> object:
                    return cls()
                return _conv

        c = ComposedResponseSpec(projection=FakeProjection(), converter=FakeConverter())  # type: ignore[arg-type]
        assert c.projection is not None
        assert c.converter is not None


class TestConvenienceConstructors:
    """Convenience constructors return correct types."""

    def test_all_fields_fn(self) -> None:
        from emergent.wire.derive._project import AllFields, all_fields

        assert isinstance(all_fields(), AllFields)

    def test_id_only_fn(self) -> None:
        from emergent.wire.derive._project import IdOnly, id_only

        assert isinstance(id_only(), IdOnly)

    def test_non_id_fn(self) -> None:
        from emergent.wire.derive._project import NonId, non_id

        assert isinstance(non_id(), NonId)

    def test_no_fields_fn(self) -> None:
        from emergent.wire.derive._project import NoFields, no_fields

        assert isinstance(no_fields(), NoFields)

    def test_required_non_id_fn(self) -> None:
        from emergent.wire.derive._project import RequiredNonId, required_non_id

        assert isinstance(required_non_id(), RequiredNonId)

    def test_fields_fn(self) -> None:
        from emergent.wire.derive._project import SelectFields, fields

        result = fields("name", "email")
        assert isinstance(result, SelectFields)
        assert result.names == ("name", "email")

    def test_exclude_from_fn(self) -> None:
        from emergent.wire.derive._project import AllFields, ExcludeFromProjection, exclude_from

        result = exclude_from(AllFields(), "password")
        assert isinstance(result, ExcludeFromProjection)
        assert result.names == ("password",)

    def test_exclude_fn(self) -> None:
        from emergent.wire.derive._project import ExcludeFields, exclude

        result = exclude("secret", "token")
        assert isinstance(result, ExcludeFields)
        assert result.names == ("secret", "token")

    def test_optional_non_id_fn(self) -> None:
        from emergent.wire.derive._project import OptionalNonId, optional_non_id

        assert isinstance(optional_non_id(), OptionalNonId)

    def test_merge_fn(self) -> None:
        from emergent.wire.derive._project import IdOnly, MergeProjection, NonId, merge

        result = merge(IdOnly(), NonId())
        assert isinstance(result, MergeProjection)

    def test_entity_response_fn(self) -> None:
        from emergent.wire.derive._project import EntityResponse, entity_response

        assert isinstance(entity_response(), EntityResponse)

    def test_list_response_fn(self) -> None:
        from emergent.wire.derive._project import ListResponse, list_response

        assert isinstance(list_response(), ListResponse)

    def test_ok_response_fn(self) -> None:
        from emergent.wire.derive._project import OkResponse, ok_response

        assert isinstance(ok_response(), OkResponse)

    def test_paginated_response_fn(self) -> None:
        from emergent.wire.derive._project import PaginatedResponse, paginated_response

        assert isinstance(paginated_response(), PaginatedResponse)

    def test_count_response_fn(self) -> None:
        from emergent.wire.derive._project import CountResponse, count_response

        assert isinstance(count_response(), CountResponse)

    def test_bool_response_fn(self) -> None:
        from emergent.wire.derive._project import BoolResponse, bool_response

        assert isinstance(bool_response(), BoolResponse)

    def test_empty_response_fn(self) -> None:
        from emergent.wire.derive._project import EmptyResponse, empty_response

        assert isinstance(empty_response(), EmptyResponse)

    def test_cursor_paginated_response_fn(self) -> None:
        from emergent.wire.derive._project import CursorPaginatedResponse, cursor_paginated_response

        assert isinstance(cursor_paginated_response(), CursorPaginatedResponse)

    def test_custom_response_fn(self) -> None:
        from emergent.wire.derive._project import CustomResponse, custom_response

        def _noop_converter(cls: type, r: object) -> object:
            return cls()

        result = custom_response(
            field_specs=(("count", int),),
            converter=_noop_converter,
        )
        assert isinstance(result, CustomResponse)

    def test_composed_response_fn(self) -> None:
        from emergent.wire.derive._project import ComposedResponseSpec, composed_response

        @dataclass(frozen=True, slots=True)
        class FP:
            def project_response(self, ctx: object) -> list[object]:
                return []

        @dataclass(frozen=True, slots=True)
        class FC:
            def build_converter(self, ctx: object) -> object:
                def _conv(cls: type, r: object) -> object:
                    return cls()
                return _conv

        result = composed_response(FP(), FC())  # type: ignore[arg-type]
        assert isinstance(result, ComposedResponseSpec)


# ═══════════════════════════════════════════════════════════════════════════════
# 6. _opspec.py — OpSpec and Op construction
# ═══════════════════════════════════════════════════════════════════════════════


class _StubTrigger:
    pass


class _StubTemplate:
    def build(self, spec: object) -> object:
        return lambda: None


class TestOpSpec:
    """OpSpec is frozen with correct defaults."""

    def test_opspec_construction(self) -> None:
        from emergent.wire.derive._opspec import OpSpec
        from emergent.wire.derive._project import OkResponse

        spec = OpSpec(
            name="Create",
            entity_name="User",
            input_fields={"name": str},
            request_fields={"name": str},
            response_spec=OkResponse(),
            handler_template=_StubTemplate(),  # type: ignore[arg-type]
            trigger=_StubTrigger(),
        )
        assert spec.name == "Create"
        assert spec.entity_name == "User"
        assert spec.capabilities == ()
        assert spec.effects == ()
        assert spec.codec_factory is None
        assert spec.extra_op_fields == ()
        assert spec.extra_request_fields == ()
        assert spec.scope_fields == ()
        assert spec.source == ""

    def test_opspec_frozen(self) -> None:
        from emergent.wire.derive._opspec import OpSpec
        from emergent.wire.derive._project import OkResponse

        spec = OpSpec(
            name="Create", entity_name="User",
            input_fields={}, request_fields={},
            response_spec=OkResponse(),
            handler_template=_StubTemplate(),  # type: ignore[arg-type]
            trigger=_StubTrigger(),
        )
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            spec.name = "X"  # type: ignore[misc]

    def test_opspec_with_effects(self) -> None:
        from emergent.wire.derive._opspec import OpSpec
        from emergent.wire.derive._project import OkResponse

        spec = OpSpec(
            name="Create", entity_name="User",
            input_fields={}, request_fields={},
            response_spec=OkResponse(),
            handler_template=_StubTemplate(),  # type: ignore[arg-type]
            trigger=_StubTrigger(),
            effects=(Creates(), Idempotent()),
        )
        assert len(spec.effects) == 2
        assert has_effect(spec.effects, Creates)
        assert has_effect(spec.effects, Idempotent)

    def test_opspec_with_source(self) -> None:
        from emergent.wire.derive._opspec import OpSpec
        from emergent.wire.derive._project import OkResponse

        spec = OpSpec(
            name="List", entity_name="User",
            input_fields={}, request_fields={},
            response_spec=OkResponse(),
            handler_template=_StubTemplate(),  # type: ignore[arg-type]
            trigger=_StubTrigger(),
            source="CRUD",
        )
        assert spec.source == "CRUD"

    def test_opspec_with_scope_fields(self) -> None:
        from emergent.wire.derive._opspec import OpSpec
        from emergent.wire.derive._project import OkResponse

        spec = OpSpec(
            name="List", entity_name="User",
            input_fields={}, request_fields={},
            response_spec=OkResponse(),
            handler_template=_StubTemplate(),  # type: ignore[arg-type]
            trigger=_StubTrigger(),
            scope_fields=("tenant_id",),
        )
        assert spec.scope_fields == ("tenant_id",)


class TestOp:
    """Op is frozen with correct defaults."""

    def test_op_construction(self) -> None:
        from emergent.wire.derive._opspec import Op
        from emergent.wire.derive._project import NoFields, ListResponse

        op = Op(
            name="List",
            input_proj=NoFields(),
            output=ListResponse(),
            handler_template=_StubTemplate(),  # type: ignore[arg-type]
        )
        assert op.name == "List"
        assert op.capabilities == ()
        assert op.extra_op_fields == ()
        assert op.extra_request_fields == ()
        assert op.effects == ()
        assert op.codec_factory is None
        assert op.scope_fields == ()

    def test_op_frozen(self) -> None:
        from emergent.wire.derive._opspec import Op
        from emergent.wire.derive._project import NoFields, ListResponse

        op = Op(
            name="List", input_proj=NoFields(), output=ListResponse(),
            handler_template=_StubTemplate(),  # type: ignore[arg-type]
        )
        with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
            op.name = "X"  # type: ignore[misc]

    def test_op_with_effects(self) -> None:
        from emergent.wire.derive._opspec import Op
        from emergent.wire.derive._project import NoFields, ListResponse

        op = Op(
            name="List", input_proj=NoFields(), output=ListResponse(),
            handler_template=_StubTemplate(),  # type: ignore[arg-type]
            effects=(Read(), Pageable()),
        )
        assert has_effect(op.effects, Read)
        assert has_effect(op.effects, Pageable)


class TestNormalizeOp:
    """normalize_op resolves Op passthrough and DescriptiveTemplate -> Op."""

    def test_normalize_op_passthrough(self) -> None:
        from emergent.wire.derive._opspec import Op, normalize_op
        from emergent.wire.derive._project import NoFields, ListResponse

        op = Op(
            name="List", input_proj=NoFields(), output=ListResponse(),
            handler_template=_StubTemplate(),  # type: ignore[arg-type]
        )
        assert normalize_op(op) is op

    def test_normalize_op_from_descriptive_template(self) -> None:
        from emergent.wire.derive._handler import FetchMany
        from emergent.wire.derive._opspec import Op, normalize_op

        result = normalize_op(FetchMany())
        assert isinstance(result, Op)
        assert result.name == "List"

    def test_normalize_op_from_insert_new(self) -> None:
        from emergent.wire.derive._handler import InsertNew
        from emergent.wire.derive._opspec import Op, normalize_op

        result = normalize_op(InsertNew())
        assert isinstance(result, Op)
        assert result.name == "Create"

    def test_normalize_op_from_delete_one(self) -> None:
        from emergent.wire.derive._handler import DeleteOne
        from emergent.wire.derive._opspec import Op, normalize_op

        result = normalize_op(DeleteOne())
        assert isinstance(result, Op)
        assert result.name == "Delete"


# ═══════════════════════════════════════════════════════════════════════════════
# 7. _crud.py — CRUD generators and constants
# ═══════════════════════════════════════════════════════════════════════════════


class TestCRUDConstants:
    """CRUD constants have correct effects and counts."""

    def test_all_crud_ops_count(self) -> None:
        from emergent.wire.derive._crud import ALL_CRUD_OPS

        assert len(ALL_CRUD_OPS) == 6

    def test_mutation_crud_ops_count(self) -> None:
        from emergent.wire.derive._crud import MUTATION_CRUD_OPS

        assert len(MUTATION_CRUD_OPS) == 4

    def test_read_crud_ops_count(self) -> None:
        from emergent.wire.derive._crud import READ_CRUD_OPS

        assert len(READ_CRUD_OPS) == 2

    def test_list_op_has_read_effect(self) -> None:
        from emergent.wire.derive._crud import LIST

        assert has_effect(LIST.effects, Read)
        assert has_effect(LIST.effects, Pageable)
        assert has_effect(LIST.effects, Sortable)

    def test_get_op_has_read_effect(self) -> None:
        from emergent.wire.derive._crud import GET

        assert has_effect(GET.effects, Read)
        assert has_effect(GET.effects, Idempotent)
        assert has_effect(GET.effects, Cacheable)

    def test_create_op_has_creates_effect(self) -> None:
        from emergent.wire.derive._crud import CREATE

        assert has_effect(CREATE.effects, Creates)
        assert has_effect(CREATE.effects, Mutation)

    def test_update_op_has_updates_effect(self) -> None:
        from emergent.wire.derive._crud import UPDATE

        assert has_effect(UPDATE.effects, Updates)
        assert has_effect(UPDATE.effects, Mutation)
        assert has_effect(UPDATE.effects, Idempotent)

    def test_patch_op_has_updates_effect(self) -> None:
        from emergent.wire.derive._crud import PATCH

        assert has_effect(PATCH.effects, Updates)
        assert has_effect(PATCH.effects, Idempotent)

    def test_delete_op_has_deletes_effect(self) -> None:
        from emergent.wire.derive._crud import DELETE

        assert has_effect(DELETE.effects, Deletes)
        assert has_effect(DELETE.effects, Mutation)
        assert has_effect(DELETE.effects, Idempotent)

    def test_upsert_op_has_creates_and_updates(self) -> None:
        from emergent.wire.derive._crud import UPSERT

        assert has_effect(UPSERT.effects, Creates)
        assert has_effect(UPSERT.effects, Updates)
        assert has_effect(UPSERT.effects, Idempotent)

    def test_list_op_name(self) -> None:
        from emergent.wire.derive._crud import LIST

        assert LIST.name == "List"

    def test_get_op_name(self) -> None:
        from emergent.wire.derive._crud import GET

        assert GET.name == "Get"

    def test_create_op_name(self) -> None:
        from emergent.wire.derive._crud import CREATE

        assert CREATE.name == "Create"

    def test_update_op_name(self) -> None:
        from emergent.wire.derive._crud import UPDATE

        assert UPDATE.name == "Update"

    def test_patch_op_name(self) -> None:
        from emergent.wire.derive._crud import PATCH

        assert PATCH.name == "Patch"

    def test_delete_op_name(self) -> None:
        from emergent.wire.derive._crud import DELETE

        assert DELETE.name == "Delete"

    def test_upsert_op_name(self) -> None:
        from emergent.wire.derive._crud import UPSERT

        assert UPSERT.name == "Upsert"


class TestCRUDGenerators:
    """http_crud() and cli_crud() produce valid CRUD capabilities."""

    def test_http_crud_returns_crud(self) -> None:
        from emergent.wire.derive._crud import CRUD, http_crud

        result = http_crud("/api/users", object)
        assert isinstance(result, CRUD)

    def test_http_crud_has_default_ops(self) -> None:
        from emergent.wire.derive._crud import ALL_CRUD_OPS, http_crud

        result = http_crud("/api/users", object)
        assert result.ops is ALL_CRUD_OPS

    def test_http_crud_custom_ops(self) -> None:
        from emergent.wire.derive._crud import LIST, GET, http_crud

        result = http_crud("/api/users", object, ops=(LIST, GET))
        assert result.ops == (LIST, GET)

    def test_cli_crud_returns_crud(self) -> None:
        from emergent.wire.derive._crud import CRUD, cli_crud

        result = cli_crud("user", object)
        assert isinstance(result, CRUD)

    def test_cli_crud_has_default_ops(self) -> None:
        from emergent.wire.derive._crud import ALL_CRUD_OPS, cli_crud

        result = cli_crud("user", object)
        assert result.ops is ALL_CRUD_OPS

    def test_cli_crud_custom_ops(self) -> None:
        from emergent.wire.derive._crud import CREATE, DELETE, cli_crud

        result = cli_crud("user", object, ops=(CREATE, DELETE))
        assert result.ops == (CREATE, DELETE)

    def test_crud_is_schema_capability(self) -> None:
        from emergent.wire.axis.schema._universal import SchemaCapability
        from emergent.wire.derive._crud import http_crud

        result = http_crud("/api/users", object)
        assert isinstance(result, SchemaCapability)

    def test_crud_stores_provider_node(self) -> None:
        from emergent.wire.derive._crud import http_crud

        class FakeProvider:
            pass

        result = http_crud("/api/users", FakeProvider)
        assert result.provider_node is FakeProvider

    def test_crud_fn_with_capabilities(self) -> None:
        from emergent.wire.derive._crud import crud
        from emergent.wire.derive._trigger import HTTPTriggers

        @dataclass(frozen=True, slots=True)
        class FakeCap:
            pass

        result = crud(HTTPTriggers("/api/users"), object, FakeCap())  # type: ignore[arg-type]
        # Should have FakeCap + ERROR_CAPS
        assert len(result.capabilities) > 1


# ═══════════════════════════════════════════════════════════════════════════════
# 8. Cross-module: transforms are SchemaCapabilities
# ═══════════════════════════════════════════════════════════════════════════════


class TestTransformsAreCapabilities:
    """All transforms inherit from SchemaCapability."""

    def test_paginated_is_capability(self) -> None:
        from emergent.wire.axis.schema._universal import SchemaCapability
        from emergent.wire.derive._transforms import Paginated

        assert isinstance(Paginated(), SchemaCapability)

    def test_sorted_is_capability(self) -> None:
        from emergent.wire.axis.schema._universal import SchemaCapability
        from emergent.wire.derive._transforms import Sorted

        assert isinstance(Sorted(), SchemaCapability)

    def test_readonly_is_capability(self) -> None:
        from emergent.wire.axis.schema._universal import SchemaCapability
        from emergent.wire.derive._transforms import Readonly

        assert isinstance(Readonly(), SchemaCapability)

    def test_with_timeout_is_capability(self) -> None:
        from emergent.wire.axis.schema._universal import SchemaCapability
        from emergent.wire.derive._transforms import WithTimeout

        assert isinstance(WithTimeout(seconds=10), SchemaCapability)

    def test_soft_delete_is_capability(self) -> None:
        from emergent.wire.axis.schema._universal import SchemaCapability
        from emergent.wire.derive._transforms import SoftDelete

        assert isinstance(SoftDelete(), SchemaCapability)

    def test_filtered_is_capability(self) -> None:
        from emergent.wire.axis.schema._universal import SchemaCapability
        from emergent.wire.derive._transforms import Filtered

        assert isinstance(Filtered(), SchemaCapability)

    def test_searchable_is_capability(self) -> None:
        from emergent.wire.axis.schema._universal import SchemaCapability
        from emergent.wire.derive._transforms import Searchable

        assert isinstance(Searchable(), SchemaCapability)

    def test_effect_rate_limited_is_capability(self) -> None:
        from emergent.wire.axis.schema._universal import SchemaCapability
        from emergent.wire.derive._transforms import EffectRateLimited

        assert isinstance(EffectRateLimited(), SchemaCapability)

    def test_effect_deprecated_is_capability(self) -> None:
        from emergent.wire.axis.schema._universal import SchemaCapability
        from emergent.wire.derive._transforms import EffectDeprecated

        assert isinstance(EffectDeprecated(), SchemaCapability)


# ═══════════════════════════════════════════════════════════════════════════════
# 9. Field projection logic with DeriveCtx
# ═══════════════════════════════════════════════════════════════════════════════


class TestProjectionWithCtx:
    """Field projections work correctly with DeriveCtx."""

    def _make_ctx(self) -> object:
        from emergent.wire.derive._ctx import DeriveCtx
        return DeriveCtx.from_entity(User)

    def test_all_fields_projects_all(self) -> None:
        from emergent.wire.derive._project import AllFields
        ctx = self._make_ctx()
        result = AllFields().project(ctx)  # type: ignore[arg-type]
        assert set(result.keys()) == {"id", "name", "email"}

    def test_id_only_projects_identity(self) -> None:
        from emergent.wire.derive._project import IdOnly
        ctx = self._make_ctx()
        result = IdOnly().project(ctx)  # type: ignore[arg-type]
        assert set(result.keys()) == {"id"}

    def test_non_id_excludes_identity(self) -> None:
        from emergent.wire.derive._project import NonId
        ctx = self._make_ctx()
        result = NonId().project(ctx)  # type: ignore[arg-type]
        assert "id" not in result
        assert "name" in result
        assert "email" in result

    def test_no_fields_returns_empty(self) -> None:
        from emergent.wire.derive._project import NoFields
        ctx = self._make_ctx()
        result = NoFields().project(ctx)  # type: ignore[arg-type]
        assert len(result) == 0

    def test_select_fields_selects(self) -> None:
        from emergent.wire.derive._project import SelectFields
        ctx = self._make_ctx()
        result = SelectFields(names=("name",)).project(ctx)  # type: ignore[arg-type]
        assert set(result.keys()) == {"name"}

    def test_exclude_fields_excludes(self) -> None:
        from emergent.wire.derive._project import ExcludeFields
        ctx = self._make_ctx()
        result = ExcludeFields(names=("email",)).project(ctx)  # type: ignore[arg-type]
        assert "email" not in result
        assert "id" in result
        assert "name" in result

    def test_exclude_from_projection(self) -> None:
        from emergent.wire.derive._project import AllFields, ExcludeFromProjection
        ctx = self._make_ctx()
        result = ExcludeFromProjection(inner=AllFields(), names=("id",)).project(ctx)  # type: ignore[arg-type]
        assert "id" not in result
        assert "name" in result
        assert "email" in result

    def test_merge_projection_combines(self) -> None:
        from emergent.wire.derive._project import IdOnly, MergeProjection, SelectFields
        ctx = self._make_ctx()
        left = IdOnly()
        right = SelectFields(names=("email",))
        result = MergeProjection(left=left, right=right).project(ctx)  # type: ignore[arg-type]
        assert set(result.keys()) == {"id", "email"}

    def test_optional_non_id_projects(self) -> None:
        from emergent.wire.derive._project import OptionalNonId
        ctx = self._make_ctx()
        result = OptionalNonId().project(ctx)  # type: ignore[arg-type]
        assert "id" not in result
        assert "name" in result
        assert "email" in result

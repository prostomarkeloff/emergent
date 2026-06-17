"""Composable handler pipeline — step algebra for handler templates.

Pipeline implements HandlerTemplate via composable frozen dataclass steps.
Each step reads/writes a mutable PipelineContext that flows through the pipeline.
Steps can short-circuit by returning a Result (Ok or Error).

    from emergent.wire.derive._pipeline import Pipeline, ScopeQuery, FetchAll, WrapItems

    list_handler = Pipeline(ScopeQuery(), FetchAll(), WrapItems())
    # Equivalent to FetchMany().build(spec)

    update_handler = Pipeline(
        ScopeQuery(), IdentityFilter(), FetchOrNotFound(),
        MergeFields(), ProviderUpdate(), WrapOk(),
    )
    # Equivalent to UpdateExisting().build(spec)
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field as dataclass_field
from typing import Any, TYPE_CHECKING, Protocol, runtime_checkable

from kungfu import Error, Ok, Result

from emergent.wire.derive._errors import DomainError, NotFound
from emergent.wire.derive._query_helpers import (
    fetch_by_identity,
    filter_by_identity,
    identity_values,
    scoped_query,
)

if TYPE_CHECKING:
    from emergent.wire.axis.query import RelationalQuerySet
    from emergent.wire.derive._ctx import OperationHandler
    from emergent.wire.derive._handler import HandlerSpec, HasProvider


type EntityData = dict[str, object]
type EntityFieldData = dict[str, Any]


# ═══════════════════════════════════════════════════════════════════════════════
# PipelineContext — mutable runtime accumulator
# ═══════════════════════════════════════════════════════════════════════════════

# Sentinel for PATCH: distinguishes "user sent None" from "user didn't send"
_UNSET = object()


@dataclass(slots=True)
class PipelineContext[EntityT]:
    """Mutable accumulator flowing through pipeline steps.

    Short-lived (one request), never shared, never stored.
    Created fresh by Pipeline.build() for each handler invocation.
    """

    spec: HandlerSpec[EntityT]
    op: HasProvider[EntityT]

    # Accumulated state — steps read/write these
    query: RelationalQuerySet[EntityT] | None = None
    existing: EntityT | None = None
    entity_data: EntityData | None = None
    items: list[EntityT] | None = None
    result: object = None
    extras: EntityData = dataclass_field(default_factory=lambda: dict[str, object]())


# ═══════════════════════════════════════════════════════════════════════════════
# PipelineStep Protocol
# ═══════════════════════════════════════════════════════════════════════════════


@runtime_checkable
class PipelineStep(Protocol):
    """Single composable step in a handler pipeline.

    Return PipelineContext to continue to next step.
    Return Result to short-circuit the pipeline (Ok or Error).
    """

    async def execute[EntityT](
        self,
        pctx: PipelineContext[EntityT],
    ) -> PipelineContext[EntityT] | Result[Any, DomainError]: ...


# ═══════════════════════════════════════════════════════════════════════════════
# Pipeline — HandlerTemplate implementation
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Pipeline:
    """Composable handler pipeline — implements HandlerTemplate.

    Steps are frozen dataclass PipelineStep implementations.
    Pipeline itself is frozen — defunctionalized, inspectable, explainable.

        Pipeline(ScopeQuery(), FetchAll(), WrapItems())
    """

    steps: tuple[PipelineStep, ...]

    def __init__(self, *steps: PipelineStep) -> None:
        object.__setattr__(self, "steps", steps)

    def build[EntityT](
        self, spec: HandlerSpec[EntityT]
    ) -> OperationHandler[Any, DomainError]:
        """Build handler by closing over spec and steps."""
        pipeline_steps = self.steps

        async def handler(op: HasProvider[EntityT]) -> Result[Any, DomainError]:
            pctx: PipelineContext[EntityT] = PipelineContext(spec=spec, op=op)

            for step in pipeline_steps:
                step_result = await step.execute(pctx)
                if isinstance(step_result, (Ok, Error)):
                    return step_result
                pctx = step_result

            return Ok(pctx.result)

        return handler


# ═══════════════════════════════════════════════════════════════════════════════
# Query Steps
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class ScopeQuery:
    """Apply scope filters to base query. Sets pctx.query."""

    async def execute[EntityT](
        self,
        pctx: PipelineContext[EntityT],
    ) -> PipelineContext[EntityT]:
        spec = pctx.spec
        assert spec.base_query is not None
        pctx.query = scoped_query(spec.base_query, pctx.op, spec.scope_fields)
        return pctx


@dataclass(frozen=True, slots=True)
class IdentityFilter:
    """Add identity field filters to query. Requires ScopeQuery first."""

    async def execute[EntityT](
        self,
        pctx: PipelineContext[EntityT],
    ) -> PipelineContext[EntityT]:
        assert pctx.query is not None
        pctx.query = filter_by_identity(
            pctx.query, pctx.op, pctx.spec.identity_names
        )
        return pctx


@dataclass(frozen=True, slots=True)
class Paginate:
    """Apply pagination to query from op.page/op.page_size."""

    default_page_size: int = 20

    async def execute[EntityT](
        self,
        pctx: PipelineContext[EntityT],
    ) -> PipelineContext[EntityT]:
        assert pctx.query is not None
        page: int = getattr(pctx.op, "page", 1)
        page_size: int = getattr(pctx.op, "page_size", self.default_page_size)
        pctx.query = pctx.query.paginate(page, page_size)
        return pctx


# ═══════════════════════════════════════════════════════════════════════════════
# Fetch Steps
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class FetchAll:
    """Fetch all entities matching query. Sets pctx.items."""

    async def execute[EntityT](
        self,
        pctx: PipelineContext[EntityT],
    ) -> PipelineContext[EntityT]:
        assert pctx.query is not None
        pctx.items = await pctx.op.provider.fetch_many(pctx.query)
        return pctx


@dataclass(frozen=True, slots=True)
class FetchOrNotFound:
    """Fetch one entity from query, or short-circuit with NotFound.

    Sets pctx.existing on success. Returns Error(NotFound) on miss.
    """

    async def execute[EntityT](
        self,
        pctx: PipelineContext[EntityT],
    ) -> PipelineContext[EntityT] | Result[Any, DomainError]:
        assert pctx.query is not None
        result = await pctx.op.provider.fetch_one(pctx.query)
        if result is None:
            err: DomainError = NotFound(
                entity=pctx.spec.entity_name,
                id=identity_values(pctx.op, pctx.spec.identity_names),
            )
            return Error(err)
        pctx.existing = result
        return pctx


@dataclass(frozen=True, slots=True)
class FetchByIdentity:
    """Direct fetch by identity fields (builds fresh query from entity type).

    Sets pctx.existing (may be None — no error on miss).
    """

    async def execute[EntityT](
        self,
        pctx: PipelineContext[EntityT],
    ) -> PipelineContext[EntityT]:
        pctx.existing = await fetch_by_identity(
            pctx.op.provider, pctx.spec.entity, pctx.op, pctx.spec.identity_names
        )
        return pctx


@dataclass(frozen=True, slots=True)
class CountTotal:
    """Count entities matching query. Stores in pctx.extras['total']."""

    async def execute[EntityT](
        self,
        pctx: PipelineContext[EntityT],
    ) -> PipelineContext[EntityT]:
        assert pctx.query is not None
        pctx.extras["total"] = await pctx.op.provider.count(pctx.query)
        return pctx


# ═══════════════════════════════════════════════════════════════════════════════
# Data Assembly Steps
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class BuildEntityData:
    """Build entity_data from op fields for INSERT. Handles id auto-gen."""

    async def execute[EntityT](
        self,
        pctx: PipelineContext[EntityT],
    ) -> PipelineContext[EntityT]:
        spec = pctx.spec
        entity_data: EntityFieldData = {
            f: getattr(pctx.op, f)
            for f in spec.non_identity_names
            if hasattr(pctx.op, f)
        }
        for name in spec.identity_names:
            if hasattr(pctx.op, name):
                entity_data[name] = getattr(pctx.op, name)
            elif hasattr(pctx.op.provider, "next_id"):
                next_id_fn = getattr(pctx.op.provider, "next_id")
                entity_data[name] = await next_id_fn()
            else:
                raise RuntimeError(
                    f"Provider for {spec.entity.__name__} has no next_id(); "
                    f"cannot auto-assign identity field '{name}'"
                )
        pctx.entity_data = entity_data
        return pctx


@dataclass(frozen=True, slots=True)
class MergeFields:
    """Merge op fields into existing entity for UPDATE.

    All non-id fields from op, falling back to existing values.
    Requires pctx.existing to be set.
    """

    async def execute[EntityT](
        self,
        pctx: PipelineContext[EntityT],
    ) -> PipelineContext[EntityT]:
        assert pctx.existing is not None
        spec = pctx.spec
        entity_data: EntityFieldData = {
            f: getattr(pctx.op, f, getattr(pctx.existing, f))
            for f in spec.non_identity_names
        }
        for name in spec.identity_names:
            entity_data[name] = getattr(pctx.op, name)
        pctx.entity_data = entity_data
        return pctx


@dataclass(frozen=True, slots=True)
class PatchMergeFields:
    """Merge only sent fields for PATCH semantics.

    Uses _UNSET sentinel to distinguish "not sent" from "sent None".
    Requires pctx.existing to be set.
    """

    async def execute[EntityT](
        self,
        pctx: PipelineContext[EntityT],
    ) -> PipelineContext[EntityT]:
        assert pctx.existing is not None
        spec = pctx.spec
        entity_data: EntityFieldData = {
            name: getattr(pctx.existing, name)
            for name in (*spec.non_identity_names, *spec.identity_names)
        }
        for f in spec.non_identity_names:
            op_val = getattr(pctx.op, f, _UNSET)
            if op_val is not _UNSET:
                entity_data[f] = op_val
        for name in spec.identity_names:
            entity_data[name] = getattr(pctx.op, name)
        pctx.entity_data = entity_data
        return pctx


@dataclass(frozen=True, slots=True)
class CopyExistingToData:
    """Copy all fields from existing entity into entity_data."""

    async def execute[EntityT](
        self,
        pctx: PipelineContext[EntityT],
    ) -> PipelineContext[EntityT]:
        assert pctx.existing is not None
        spec = pctx.spec
        pctx.entity_data = {
            n: getattr(pctx.existing, n)
            for n in (*spec.identity_names, *spec.non_identity_names)
        }
        return pctx


@dataclass(frozen=True, slots=True)
class SetTimestamp:
    """Set a timestamp field to now(UTC) in entity_data."""

    field_name: str

    async def execute[EntityT](
        self,
        pctx: PipelineContext[EntityT],
    ) -> PipelineContext[EntityT]:
        from datetime import datetime, timezone

        if pctx.entity_data is None:
            pctx.entity_data = {}
        pctx.entity_data[self.field_name] = datetime.now(tz=timezone.utc)
        return pctx


@dataclass(frozen=True, slots=True)
class SetFieldValue:
    """Set one field to fn(op) result in entity_data."""

    field_name: str
    value_fn: Callable[[object], object]

    async def execute[EntityT](
        self,
        pctx: PipelineContext[EntityT],
    ) -> PipelineContext[EntityT]:
        if pctx.entity_data is None:
            pctx.entity_data = {}
        pctx.entity_data[self.field_name] = self.value_fn(pctx.op)
        return pctx


# ═══════════════════════════════════════════════════════════════════════════════
# Provider Mutation Steps
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class ProviderInsert:
    """Construct entity from entity_data, insert via provider."""

    async def execute[EntityT](
        self,
        pctx: PipelineContext[EntityT],
    ) -> PipelineContext[EntityT]:
        assert pctx.entity_data is not None
        entity = pctx.spec.entity(**pctx.entity_data)
        pctx.result = await pctx.op.provider.insert(entity)
        return pctx


@dataclass(frozen=True, slots=True)
class ProviderUpdate:
    """Construct entity from entity_data, update via provider."""

    async def execute[EntityT](
        self,
        pctx: PipelineContext[EntityT],
    ) -> PipelineContext[EntityT]:
        assert pctx.entity_data is not None
        entity = pctx.spec.entity(**pctx.entity_data)
        pctx.result = await pctx.op.provider.update(entity)
        return pctx


@dataclass(frozen=True, slots=True)
class ProviderDelete:
    """Delete existing entity via provider."""

    async def execute[EntityT](
        self,
        pctx: PipelineContext[EntityT],
    ) -> PipelineContext[EntityT]:
        assert pctx.existing is not None
        await pctx.op.provider.delete(pctx.existing)
        pctx.result = pctx.existing
        return pctx


# ═══════════════════════════════════════════════════════════════════════════════
# Post-Processing Steps
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class InMemorySort:
    """Sort pctx.items in-memory by op.sort/op.order fields."""

    default_sort: str | None = None
    default_order: str = "asc"

    async def execute[EntityT](
        self,
        pctx: PipelineContext[EntityT],
    ) -> PipelineContext[EntityT]:
        assert pctx.items is not None
        sort_field = getattr(pctx.op, "sort", self.default_sort) or self.default_sort
        order = getattr(pctx.op, "order", self.default_order) or self.default_order
        if sort_field:
            pctx.items = sorted(
                pctx.items,
                key=lambda x: getattr(x, sort_field, "") or "",
                reverse=(order == "desc"),
            )
        return pctx


@dataclass(frozen=True, slots=True)
class CheckCache:
    """Check cache before fetch. Short-circuits with Ok(cached) on hit."""

    async def execute[EntityT](
        self,
        pctx: PipelineContext[EntityT],
    ) -> PipelineContext[EntityT] | Result[Any, DomainError]:
        cache_key = f"{pctx.spec.entity_name}:{identity_values(pctx.op, pctx.spec.identity_names)}"
        pctx.extras["cache_key"] = cache_key
        cache = getattr(pctx.op, "cache")
        cached_val: EntityT | None = await cache.get(cache_key)
        if cached_val is not None:
            return Ok(cached_val)
        return pctx


@dataclass(frozen=True, slots=True)
class PopulateCache:
    """Write fetched entity to cache. Requires pctx.existing and extras['cache_key']."""

    async def execute[EntityT](
        self,
        pctx: PipelineContext[EntityT],
    ) -> PipelineContext[EntityT]:
        assert pctx.existing is not None
        cache_key = pctx.extras["cache_key"]
        cache = getattr(pctx.op, "cache")
        await cache.set(cache_key, pctx.existing)
        return pctx


# ═══════════════════════════════════════════════════════════════════════════════
# Result Wrapping Steps (all return Result, short-circuiting)
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class WrapOk:
    """Short-circuit with Ok(result or existing or items)."""

    async def execute[EntityT](
        self,
        pctx: PipelineContext[EntityT],
    ) -> Result[Any, DomainError]:
        value = pctx.result
        if value is None:
            value = pctx.items if pctx.items is not None else pctx.existing
        return Ok(value)


@dataclass(frozen=True, slots=True)
class WrapItems:
    """Short-circuit with Ok(items)."""

    async def execute[EntityT](
        self,
        pctx: PipelineContext[EntityT],
    ) -> Result[Any, DomainError]:
        assert pctx.items is not None
        return Ok(pctx.items)


@dataclass(frozen=True, slots=True)
class WrapPaginated:
    """Short-circuit with Ok({items, total, page, page_size})."""

    default_page_size: int = 20

    async def execute[EntityT](
        self,
        pctx: PipelineContext[EntityT],
    ) -> Result[Any, DomainError]:
        assert pctx.items is not None
        page: int = getattr(pctx.op, "page", 1)
        page_size: int = getattr(pctx.op, "page_size", self.default_page_size)
        return Ok({
            "items": pctx.items,
            "total": pctx.extras.get("total", 0),
            "page": page,
            "page_size": page_size,
        })


@dataclass(frozen=True, slots=True)
class WrapCount:
    """Short-circuit with Ok(total)."""

    async def execute[EntityT](
        self,
        pctx: PipelineContext[EntityT],
    ) -> Result[Any, DomainError]:
        return Ok(pctx.extras["total"])


@dataclass(frozen=True, slots=True)
class WrapExists:
    """Short-circuit with Ok(existing is not None)."""

    async def execute[EntityT](
        self,
        pctx: PipelineContext[EntityT],
    ) -> Result[Any, DomainError]:
        return Ok(pctx.existing is not None)


__all__ = (
    # Core
    "PipelineContext",
    "PipelineStep",
    "Pipeline",
    # Query steps
    "ScopeQuery",
    "IdentityFilter",
    "Paginate",
    # Fetch steps
    "FetchAll",
    "FetchOrNotFound",
    "FetchByIdentity",
    "CountTotal",
    # Data assembly steps
    "BuildEntityData",
    "MergeFields",
    "PatchMergeFields",
    "CopyExistingToData",
    "SetTimestamp",
    "SetFieldValue",
    # Provider mutation steps
    "ProviderInsert",
    "ProviderUpdate",
    "ProviderDelete",
    # Post-processing steps
    "InMemorySort",
    "CheckCache",
    "PopulateCache",
    # Result wrapping steps
    "WrapOk",
    "WrapItems",
    "WrapPaginated",
    "WrapCount",
    "WrapExists",
)

"""Handler infrastructure — templates, specs, protocols.

HandlerTemplate is the protocol for building handlers from context.
HandlerSpec is the precise data a template needs.
Concrete templates: FetchMany, FetchOneById, InsertNew, etc.

    from emergent.wire.derive._handler import FetchMany, HandlerSpec, HandlerTemplate
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from kungfu import Ok, Error, Result

from emergent.wire.derive._effects import DerivationEffect
from emergent.wire.derive._errors import DomainError, NotFound
from emergent.wire.derive._query_helpers import (
    fetch_by_identity,
    fetch_or_not_found,
    filter_by_identity,
    identity_query,
    identity_values,
    scoped_query,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from emergent.wire.axis.query import MutatingRelationalProvider, RelationalQuerySet
    from emergent.wire.derive._ctx import OperationHandler
    from emergent.wire.derive._opspec import Op


# ═══════════════════════════════════════════════════════════════════════════════
# HandlerSpec — precise data for handler construction
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class HandlerSpec[EntityT]:
    """Precisely what a handler template needs — not the entire context.

    Built by the materializer from DeriveCtx, passed to HandlerTemplate.build().
    """

    entity: type[EntityT]
    entity_name: str
    identity_names: tuple[str, ...]
    non_identity_names: tuple[str, ...]
    base_query: RelationalQuerySet[EntityT] | None
    scope_fields: tuple[str, ...] = ()
    effects: tuple[DerivationEffect, ...] = ()


# ═══════════════════════════════════════════════════════════════════════════════
# HasProvider Protocol
# ═══════════════════════════════════════════════════════════════════════════════


class HasProvider[E](Protocol):
    """Protocol for dynamically-generated ops with a relational provider."""

    @property
    def provider(self) -> MutatingRelationalProvider[E]: ...


# ═══════════════════════════════════════════════════════════════════════════════
# HandlerTemplate Protocol
# ═══════════════════════════════════════════════════════════════════════════════


@runtime_checkable
class HandlerTemplate(Protocol):
    """Template for building a handler from HandlerSpec.

    Result type uses Any because handler templates return varying types
    (EntityT, list[EntityT], dict[str, ...]) and kungfu's Ok[T] is invariant.
    """

    def build[EntityT](self, spec: HandlerSpec[EntityT]) -> "OperationHandler[object, DomainError]": ...


@runtime_checkable
class DescriptiveTemplate(HandlerTemplate, Protocol):
    """HandlerTemplate that self-describes its default Op contract.

    Enables passing handler instances directly as ops:

        http_crud('/users', Users, ops=(FetchMany(), InsertNew(), DeleteOne()))

    Each handler knows its default name, input projection, output spec,
    and effects — no separate Op() wrapper needed for standard cases.
    """

    def op_defaults(self) -> "Op": ...


class WrapperFn(Protocol):
    """Rank-2 wrapper function — generic over entity type."""

    def __call__[EntityT](
        self,
        inner: "OperationHandler[EntityT, DomainError]",
        spec: HandlerSpec[EntityT],
    ) -> "OperationHandler[EntityT, DomainError]": ...


@dataclass(frozen=True, slots=True)
class WrappedTemplate:
    """Compose handler templates: inner handler wrapped by an outer function."""

    inner: HandlerTemplate
    wrapper: WrapperFn

    def build[EntityT](self, spec: HandlerSpec[EntityT]) -> "OperationHandler[EntityT, DomainError]":
        handler = self.inner.build(spec)
        return self.wrapper(handler, spec)


def wrap_template(
    inner: HandlerTemplate,
    wrapper: WrapperFn,
) -> WrappedTemplate:
    """Wrap a handler template with before/after logic."""
    return WrappedTemplate(inner=inner, wrapper=wrapper)


# ═══════════════════════════════════════════════════════════════════════════════
# Core Handler Templates
# ═══════════════════════════════════════════════════════════════════════════════

# Sentinel for PATCH: distinguishes "user sent None" from "user didn't send"
_UNSET = object()


@dataclass(frozen=True, slots=True)
class FetchMany:
    """Handler: provider.fetch_many(query) -> list[entity]."""

    def build[EntityT](self, spec: HandlerSpec[EntityT]) -> "OperationHandler[list[EntityT], DomainError]":
        base = spec.base_query
        sf = spec.scope_fields

        async def handler(op: HasProvider[EntityT]) -> Result[list[EntityT], DomainError]:
            assert base is not None
            items = await op.provider.fetch_many(scoped_query(base, op, sf))
            return Ok(items)

        return handler

    def op_defaults(self) -> "Op":
        from emergent.wire.derive._effects import Pageable, Read, Sortable
        from emergent.wire.derive._opspec import Op
        from emergent.wire.derive._project import ListResponse, NoFields

        return Op("List", NoFields(), ListResponse(), self, effects=(Read(), Pageable(), Sortable()))


@dataclass(frozen=True, slots=True)
class FetchOneById:
    """Handler: provider.fetch_one(filter by identity) -> entity | NotFound."""

    def build[EntityT](self, spec: HandlerSpec[EntityT]) -> "OperationHandler[EntityT, DomainError]":
        id_names = spec.identity_names
        entity_name = spec.entity_name
        base = spec.base_query
        sf = spec.scope_fields

        async def handler(op: HasProvider[EntityT]) -> Result[EntityT, DomainError]:
            assert base is not None
            existing, err = await fetch_or_not_found(
                op.provider, identity_query(base, op, sf, id_names),
                entity_name, op, id_names,
            )
            if err is not None:
                return err
            assert existing is not None
            return Ok(existing)

        return handler

    def op_defaults(self) -> "Op":
        from emergent.wire.derive._effects import Cacheable, Idempotent, Read
        from emergent.wire.derive._opspec import Op
        from emergent.wire.derive._project import EntityResponse, IdOnly

        return Op("Get", IdOnly(), EntityResponse(), self, effects=(Read(), Idempotent(), Cacheable()))


@dataclass(frozen=True, slots=True)
class InsertNew:
    """Handler: construct entity from op fields, provider.insert -> entity."""

    def build[EntityT](self, spec: HandlerSpec[EntityT]) -> "OperationHandler[EntityT, DomainError]":
        entity = spec.entity
        id_names = spec.identity_names
        non_id_names = list(spec.non_identity_names)

        async def handler(op: HasProvider[EntityT]) -> Result[EntityT, DomainError]:
            entity_data = {f: getattr(op, f) for f in non_id_names if hasattr(op, f)}

            for name in id_names:
                if hasattr(op, name):
                    entity_data[name] = getattr(op, name)
                elif hasattr(op.provider, "next_id"):
                    next_id_fn = getattr(op.provider, "next_id")
                    entity_data[name] = await next_id_fn()
                else:
                    raise RuntimeError(
                        f"Provider for {entity.__name__} has no next_id(); "
                        f"cannot auto-assign identity field '{name}'"
                    )

            new_entity = entity(**entity_data)
            result = await op.provider.insert(new_entity)
            return Ok(result)

        return handler

    def op_defaults(self) -> "Op":
        from emergent.wire.derive._effects import Creates
        from emergent.wire.derive._opspec import Op
        from emergent.wire.derive._project import EntityResponse, NonId

        return Op("Create", NonId(), EntityResponse(), self, effects=(Creates(),))


@dataclass(frozen=True, slots=True)
class UpdateExisting:
    """Handler: find by identity, merge fields, provider.update -> entity."""

    def build[EntityT](self, spec: HandlerSpec[EntityT]) -> "OperationHandler[EntityT, DomainError]":
        entity = spec.entity
        id_names = spec.identity_names
        entity_name = spec.entity_name
        non_id_names = list(spec.non_identity_names)
        base = spec.base_query
        sf = spec.scope_fields

        async def handler(op: HasProvider[EntityT]) -> Result[EntityT, DomainError]:
            assert base is not None
            existing, err = await fetch_or_not_found(
                op.provider, identity_query(base, op, sf, id_names),
                entity_name, op, id_names,
            )
            if err is not None:
                return err
            assert existing is not None

            entity_data = {
                f: getattr(op, f, getattr(existing, f)) for f in non_id_names
            }
            for name in id_names:
                entity_data[name] = getattr(op, name)

            updated = entity(**entity_data)
            result = await op.provider.update(updated)
            return Ok(result)

        return handler

    def op_defaults(self) -> "Op":
        from emergent.wire.derive._effects import Idempotent, Updates
        from emergent.wire.derive._opspec import Op
        from emergent.wire.derive._project import AllFields, EntityResponse

        return Op("Update", AllFields(), EntityResponse(), self, effects=(Updates(), Idempotent()))


@dataclass(frozen=True, slots=True)
class DeleteOne:
    """Handler: find by identity, provider.delete -> ok."""

    def build[EntityT](self, spec: HandlerSpec[EntityT]) -> "OperationHandler[EntityT, DomainError]":
        id_names = spec.identity_names
        entity_name = spec.entity_name
        base = spec.base_query
        sf = spec.scope_fields

        async def handler(op: HasProvider[EntityT]) -> Result[EntityT, DomainError]:
            assert base is not None
            existing, err = await fetch_or_not_found(
                op.provider, identity_query(base, op, sf, id_names),
                entity_name, op, id_names,
            )
            if err is not None:
                return err
            assert existing is not None
            await op.provider.delete(existing)
            return Ok(existing)

        return handler

    def op_defaults(self) -> "Op":
        from emergent.wire.derive._effects import Deletes, Idempotent
        from emergent.wire.derive._opspec import Op
        from emergent.wire.derive._project import IdOnly, OkResponse

        return Op("Delete", IdOnly(), OkResponse(), self, effects=(Deletes(), Idempotent()))


# ═══════════════════════════════════════════════════════════════════════════════
# Enriched Handler Templates
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class PaginatedFetchMany:
    """Handler: paginated fetch with total count."""

    page_size: int = 20

    def build[EntityT](self, spec: HandlerSpec[EntityT]) -> "OperationHandler[dict[str, int | list[EntityT]], DomainError]":
        base = spec.base_query
        sf = spec.scope_fields
        default_ps = self.page_size

        async def handler(op: HasProvider[EntityT]) -> Result[dict[str, int | list[EntityT]], DomainError]:
            assert base is not None
            query = scoped_query(base, op, sf)
            total = await op.provider.count(query)
            page: int = getattr(op, "page", 1)
            page_size: int = getattr(op, "page_size", default_ps)
            paginated_query = query.paginate(page, page_size)
            items = await op.provider.fetch_many(paginated_query)
            return Ok({
                "items": items,
                "total": total,
                "page": page,
                "page_size": page_size,
            })

        return handler

    def op_defaults(self) -> "Op":
        from emergent.wire.derive._effects import Pageable, Read, Sortable
        from emergent.wire.derive._opspec import Op
        from emergent.wire.derive._project import NoFields, PaginatedResponse

        return Op("List", NoFields(), PaginatedResponse(), self, effects=(Read(), Pageable(), Sortable()))


@dataclass(frozen=True, slots=True)
class CachedFetchOneById:
    """Handler: cache-backed fetch by identity."""

    def build[EntityT](self, spec: HandlerSpec[EntityT]) -> "OperationHandler[EntityT, DomainError]":
        id_names = spec.identity_names
        entity_name = spec.entity_name
        base = spec.base_query
        sf = spec.scope_fields

        async def handler(op: HasProvider[EntityT]) -> Result[EntityT, DomainError]:
            cache_key = f"{entity_name}:{identity_values(op, id_names)}"

            cache = getattr(op, "cache", None)
            if cache is None:
                raise RuntimeError(
                    f"CachedFetchOneById requires 'cache' on the op type for {entity_name}. "
                    f"Add a cache provider node to the entity's capabilities."
                )
            cached_val: EntityT | None = await cache.get(cache_key)
            if cached_val is not None:
                return Ok(cached_val)

            assert base is not None
            existing, err = await fetch_or_not_found(
                op.provider, identity_query(base, op, sf, id_names),
                entity_name, op, id_names,
            )
            if err is not None:
                return err
            assert existing is not None

            await cache.set(cache_key, existing)
            return Ok(existing)

        return handler

    def op_defaults(self) -> "Op":
        from emergent.wire.derive._effects import Cacheable, Idempotent, Read
        from emergent.wire.derive._opspec import Op
        from emergent.wire.derive._project import EntityResponse, IdOnly

        return Op("Get", IdOnly(), EntityResponse(), self, effects=(Read(), Idempotent(), Cacheable()))


@dataclass(frozen=True, slots=True)
class PatchExisting:
    """Handler: find by identity, merge ONLY sent fields, provider.update."""

    def build[EntityT](self, spec: HandlerSpec[EntityT]) -> "OperationHandler[EntityT, DomainError]":
        entity = spec.entity
        id_names = spec.identity_names
        entity_name = spec.entity_name
        non_id_names = list(spec.non_identity_names)
        base = spec.base_query
        sf = spec.scope_fields

        async def handler(op: HasProvider[EntityT]) -> Result[EntityT, DomainError]:
            assert base is not None
            existing, err = await fetch_or_not_found(
                op.provider, identity_query(base, op, sf, id_names),
                entity_name, op, id_names,
            )
            if err is not None:
                return err
            assert existing is not None

            entity_data = {name: getattr(existing, name) for name in (*non_id_names, *id_names)}
            for f in non_id_names:
                op_val = getattr(op, f, _UNSET)
                if op_val is not _UNSET:
                    entity_data[f] = op_val
            for name in id_names:
                entity_data[name] = getattr(op, name)

            updated = entity(**entity_data)
            result = await op.provider.update(updated)
            return Ok(result)

        return handler

    def op_defaults(self) -> "Op":
        from emergent.wire.derive._effects import Idempotent, Updates
        from emergent.wire.derive._opspec import Op
        from emergent.wire.derive._project import EntityResponse, IdOnly, MergeProjection, OptionalNonId

        return Op(
            "Patch", MergeProjection(IdOnly(), OptionalNonId()), EntityResponse(), self,
            effects=(Updates(), Idempotent()),
        )


@dataclass(frozen=True, slots=True)
class SortedFetchMany:
    """Handler: fetch + in-memory sort."""

    default_sort: str | None = None
    default_order: str = "asc"

    def build[EntityT](self, spec: HandlerSpec[EntityT]) -> "OperationHandler[list[EntityT], DomainError]":
        base = spec.base_query
        sf = spec.scope_fields
        dsort = self.default_sort
        dorder = self.default_order

        async def handler(op: HasProvider[EntityT]) -> Result[list[EntityT], DomainError]:
            assert base is not None
            items = await op.provider.fetch_many(scoped_query(base, op, sf))
            sort_field = getattr(op, "sort", dsort) or dsort
            order = getattr(op, "order", dorder) or dorder
            if sort_field:
                items = sorted(
                    items,
                    key=lambda x: getattr(x, sort_field, "") or "",
                    reverse=(order == "desc"),
                )
            return Ok(items)

        return handler

    def op_defaults(self) -> "Op":
        from emergent.wire.derive._effects import Read, Sortable
        from emergent.wire.derive._opspec import Op
        from emergent.wire.derive._project import ListResponse, NoFields

        return Op("List", NoFields(), ListResponse(), self, effects=(Read(), Sortable()))


# ═══════════════════════════════════════════════════════════════════════════════
# Generic Non-CRUD Handler Templates
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class SetField:
    """Handler: fetch by identity, set one field to computed value, update."""

    field_name: str
    value_fn: "Callable[[object], object]"

    def build[EntityT](self, spec: HandlerSpec[EntityT]) -> "OperationHandler[EntityT, DomainError]":
        entity = spec.entity
        id_names = spec.identity_names
        non_id_names = spec.non_identity_names
        entity_name = spec.entity_name
        fname, vfn = self.field_name, self.value_fn

        async def handler(op: HasProvider[EntityT]) -> Result[EntityT, DomainError]:
            obj = await fetch_by_identity(op.provider, entity, op, id_names)
            if obj is None:
                return Error(NotFound(entity=entity_name, id=identity_values(op, id_names)))
            updated = entity(**{
                **{n: getattr(obj, n) for n in (*id_names, *non_id_names)},
                fname: vfn(op),
            })
            await op.provider.update(updated)
            return Ok(updated)

        return handler


@dataclass(frozen=True, slots=True)
class ExistsById:
    """Handler: check if entity exists by identity. Returns bool."""

    def build[EntityT](self, spec: HandlerSpec[EntityT]) -> "OperationHandler[bool, DomainError]":
        entity = spec.entity
        id_names = spec.identity_names

        async def handler(op: HasProvider[EntityT]) -> Result[bool, DomainError]:
            obj = await fetch_by_identity(op.provider, entity, op, id_names)
            return Ok(obj is not None)

        return handler

    def op_defaults(self) -> "Op":
        from emergent.wire.derive._effects import Idempotent, Read
        from emergent.wire.derive._opspec import Op
        from emergent.wire.derive._project import BoolResponse, IdOnly

        return Op("Exists", IdOnly(), BoolResponse(), self, effects=(Read(), Idempotent()))


@dataclass(frozen=True, slots=True)
class CountAll:
    """Handler: count entities matching base query."""

    def build[EntityT](self, spec: HandlerSpec[EntityT]) -> "OperationHandler[int, DomainError]":
        base = spec.base_query
        sf = spec.scope_fields

        async def handler(op: HasProvider[EntityT]) -> Result[int, DomainError]:
            assert base is not None
            total = await op.provider.count(scoped_query(base, op, sf))
            return Ok(total)

        return handler

    def op_defaults(self) -> "Op":
        from emergent.wire.derive._effects import Read
        from emergent.wire.derive._opspec import Op
        from emergent.wire.derive._project import CountResponse, NoFields

        return Op("Count", NoFields(), CountResponse(), self, effects=(Read(),))


# ═══════════════════════════════════════════════════════════════════════════════
# Temporal Handler Templates
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class UpsertExisting:
    """Handler: find by identity — if exists update, else insert."""

    def build[EntityT](self, spec: HandlerSpec[EntityT]) -> "OperationHandler[EntityT, DomainError]":
        entity = spec.entity
        id_names = spec.identity_names
        non_id_names = list(spec.non_identity_names)
        base = spec.base_query

        async def handler(op: HasProvider[EntityT]) -> Result[EntityT, DomainError]:
            assert base is not None
            existing = await op.provider.fetch_one(
                filter_by_identity(base, op, id_names)
            )
            entity_data = {f: getattr(op, f) for f in non_id_names if hasattr(op, f)}
            for name in id_names:
                entity_data[name] = getattr(op, name)

            new_entity = entity(**entity_data)
            if existing is not None:
                result = await op.provider.update(new_entity)
            else:
                result = await op.provider.insert(new_entity)
            return Ok(result)

        return handler

    def op_defaults(self) -> "Op":
        from emergent.wire.derive._effects import Creates, Idempotent, Updates
        from emergent.wire.derive._opspec import Op
        from emergent.wire.derive._project import AllFields, EntityResponse

        return Op("Upsert", AllFields(), EntityResponse(), self, effects=(Creates(), Updates(), Idempotent()))


@dataclass(frozen=True, slots=True)
class SoftDeleteMark:
    """Soft-delete: set deleted_at instead of hard delete.

    Replaces DeleteOne. Finds entity by identity, sets deleted_at = now(),
    provider.update(). base_query already filters out deleted records.
    """

    deleted_field: str = "deleted_at"

    def build[EntityT](
        self, spec: HandlerSpec[EntityT]
    ) -> "OperationHandler[EntityT, DomainError]":
        from datetime import datetime, timezone

        entity = spec.entity
        id_names = spec.identity_names
        non_id_names = spec.non_identity_names
        entity_name = spec.entity_name
        base = spec.base_query
        field = self.deleted_field

        async def handler(op: HasProvider[EntityT]) -> Result[EntityT, DomainError]:
            assert base is not None
            query = filter_by_identity(base, op, id_names)
            existing = await op.provider.fetch_one(query)
            if existing is None:
                result: Result[EntityT, DomainError] = Error(
                    NotFound(entity=entity_name, id=identity_values(op, id_names))
                )
                return result

            all_names = (*id_names, *non_id_names)
            data: dict[str, int | str | float | bool | datetime | None] = {
                n: getattr(existing, n) for n in all_names
            }
            data[field] = datetime.now(tz=timezone.utc)
            updated = entity(**data)
            result_entity = await op.provider.update(updated)
            return Ok(result_entity)

        return handler


@dataclass(frozen=True, slots=True)
class TimestampInsert:
    """Auto-set created_at + updated_at on insert.

    Replaces InsertNew. Overrides timestamp fields with
    datetime.now(tz=timezone.utc) before entity construction.
    """

    created_field: str
    updated_field: str

    def build[EntityT](
        self, spec: HandlerSpec[EntityT]
    ) -> "OperationHandler[EntityT, DomainError]":
        from datetime import datetime, timezone

        entity = spec.entity
        id_names = spec.identity_names
        non_id_names = list(spec.non_identity_names)
        cf, uf = self.created_field, self.updated_field

        async def handler(op: HasProvider[EntityT]) -> Result[EntityT, DomainError]:
            now = datetime.now(tz=timezone.utc)
            entity_data = {f: getattr(op, f, None) for f in non_id_names}
            entity_data[cf] = now
            entity_data[uf] = now

            for name in id_names:
                if hasattr(op, name):
                    entity_data[name] = getattr(op, name)
                elif hasattr(op.provider, "next_id"):
                    next_id_fn = getattr(op.provider, "next_id")
                    entity_data[name] = await next_id_fn()
                else:
                    raise RuntimeError(
                        f"Provider for {entity.__name__} has no next_id(); "
                        f"cannot auto-assign identity field '{name}'"
                    )

            new_entity = entity(**entity_data)
            result = await op.provider.insert(new_entity)
            return Ok(result)

        return handler


@dataclass(frozen=True, slots=True)
class TimestampUpdate:
    """Auto-set updated_at on update.

    Replaces UpdateExisting. Overrides updated_at with
    datetime.now(tz=timezone.utc) after merging fields.
    """

    updated_field: str

    def build[EntityT](
        self, spec: HandlerSpec[EntityT]
    ) -> "OperationHandler[EntityT, DomainError]":
        from datetime import datetime, timezone

        entity = spec.entity
        id_names = spec.identity_names
        entity_name = spec.entity_name
        non_id_names = list(spec.non_identity_names)
        base = spec.base_query
        uf = self.updated_field

        async def handler(op: HasProvider[EntityT]) -> Result[EntityT, DomainError]:
            assert base is not None
            existing, err = await fetch_or_not_found(
                op.provider,
                identity_query(base, op, (), id_names),
                entity_name, op, id_names,
            )
            if err is not None:
                return err
            assert existing is not None

            entity_data = {
                f: getattr(op, f, getattr(existing, f)) for f in non_id_names
            }
            for name in id_names:
                entity_data[name] = getattr(op, name)
            entity_data[uf] = datetime.now(tz=timezone.utc)

            updated = entity(**entity_data)
            update_result = await op.provider.update(updated)
            return Ok(update_result)

        return handler


__all__ = (
    "HandlerSpec",
    "HasProvider",
    "HandlerTemplate",
    "DescriptiveTemplate",
    "WrapperFn",
    "WrappedTemplate",
    "wrap_template",
    "FetchMany",
    "FetchOneById",
    "InsertNew",
    "UpdateExisting",
    "DeleteOne",
    "PaginatedFetchMany",
    "CachedFetchOneById",
    "PatchExisting",
    "SortedFetchMany",
    "UpsertExisting",
    "SetField",
    "ExistsById",
    "CountAll",
    "SoftDeleteMark",
    "TimestampInsert",
    "TimestampUpdate",
)

"""Generic handler templates — reusable across all derivation dialects.

These work for any relational entity with identity fields and a provider.
Not CRUD-specific — CRUD is just one dialect that uses them.

    from derivelib._handler_templates import FetchMany, FetchOneById, InsertNew

    LIST = Op("List", no_fields(), list_response(), FetchMany())
    GET = Op("Get", id_only(), entity_response(), FetchOneById())
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from kungfu import Ok, Result

from derivelib._ctx import OperationHandler
from derivelib._protocols import HandlerSpec, HasProvider
from derivelib._query_helpers import (
    fetch_or_not_found,
    identity_query,
    identity_values,
    scoped_query,
)

if TYPE_CHECKING:
    from derivelib._errors import DomainError

# Sentinel for PATCH: distinguishes "user sent None" from "user didn't send"
_UNSET = object()


# ═══════════════════════════════════════════════════════════════════════════════
# Core Handler Templates
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class FetchMany:
    """Handler: provider.fetch_many(query) -> list[entity].

    scope_fields: pre-filter base_query by these fields (for nested resources).
    """

    scope_fields: tuple[str, ...] = ()

    def build[EntityT](self, spec: HandlerSpec[EntityT]) -> OperationHandler[list[EntityT], DomainError]:
        base = spec.base_query
        sf = self.scope_fields

        async def handler(op: HasProvider[EntityT]) -> Result[list[EntityT], DomainError]:
            assert base is not None
            items = await op.provider.fetch_many(scoped_query(base, op, sf))
            return Ok(items)

        return handler


@dataclass(frozen=True, slots=True)
class FetchOneById:
    """Handler: provider.fetch_one(filter by identity) -> entity | NotFound.

    scope_fields: pre-filter base_query by these fields (for nested resources).
    """

    scope_fields: tuple[str, ...] = ()

    def build[EntityT](self, spec: HandlerSpec[EntityT]) -> OperationHandler[EntityT, DomainError]:
        id_names = spec.identity_names
        entity_name = spec.entity_name
        base = spec.base_query
        sf = self.scope_fields

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


@dataclass(frozen=True, slots=True)
class InsertNew:
    """Handler: construct entity from op fields, provider.insert -> entity."""

    def build[EntityT](self, spec: HandlerSpec[EntityT]) -> OperationHandler[EntityT, DomainError]:
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


@dataclass(frozen=True, slots=True)
class UpdateExisting:
    """Handler: find by identity, merge fields, provider.update -> entity.

    scope_fields: pre-filter base_query by these fields (for nested resources).
    """

    scope_fields: tuple[str, ...] = ()

    def build[EntityT](self, spec: HandlerSpec[EntityT]) -> OperationHandler[EntityT, DomainError]:
        entity = spec.entity
        id_names = spec.identity_names
        entity_name = spec.entity_name
        non_id_names = list(spec.non_identity_names)
        base = spec.base_query
        sf = self.scope_fields

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


@dataclass(frozen=True, slots=True)
class DeleteOne:
    """Handler: find by identity, provider.delete -> ok.

    scope_fields: pre-filter base_query by these fields (for nested resources).
    """

    scope_fields: tuple[str, ...] = ()

    def build[EntityT](self, spec: HandlerSpec[EntityT]) -> OperationHandler[EntityT, DomainError]:
        id_names = spec.identity_names
        entity_name = spec.entity_name
        base = spec.base_query
        sf = self.scope_fields

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


# ═══════════════════════════════════════════════════════════════════════════════
# Enriched Handler Templates
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class PaginatedFetchMany:
    """Handler: provider.fetch_many(query.paginate(op.page, op.page_size)).

    op.page and op.page_size are real typed fields on the Op type --
    added by the paginated() transform via extra_op_fields.
    """

    page_size: int = 20
    scope_fields: tuple[str, ...] = ()

    def build[EntityT](self, spec: HandlerSpec[EntityT]) -> OperationHandler[dict[str, int | list[EntityT]], DomainError]:
        base = spec.base_query
        sf = self.scope_fields
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


@dataclass(frozen=True, slots=True)
class CachedFetchOneById:
    """Handler: op.cache.get(key) -> hit? return : fetch -> cache.set -> return.

    op.cache is a real typed field on the Op type -- added by the
    cached() transform via extra_op_fields + compose.Node annotation.
    """

    scope_fields: tuple[str, ...] = ()

    def build[EntityT](self, spec: HandlerSpec[EntityT]) -> OperationHandler[EntityT, DomainError]:
        id_names = spec.identity_names
        entity_name = spec.entity_name
        base = spec.base_query
        sf = self.scope_fields

        async def handler(op: HasProvider[EntityT]) -> Result[EntityT, DomainError]:
            cache_key = f"{entity_name}:{identity_values(op, id_names)}"

            cache = getattr(op, "cache")
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


@dataclass(frozen=True, slots=True)
class PatchExisting:
    """Handler: find by identity, merge ONLY sent fields, provider.update.

    Like UpdateExisting but only changes fields the user explicitly sends.
    Uses _UNSET sentinel to distinguish "user sent None" from "not sent".
    Input projection should use OptionalNonId (all non-id fields Optional).

    scope_fields: pre-filter base_query by these fields (for nested resources).
    """

    scope_fields: tuple[str, ...] = ()

    def build[EntityT](self, spec: HandlerSpec[EntityT]) -> OperationHandler[EntityT, DomainError]:
        entity = spec.entity
        id_names = spec.identity_names
        entity_name = spec.entity_name
        non_id_names = list(spec.non_identity_names)
        base = spec.base_query
        sf = self.scope_fields

        async def handler(op: HasProvider[EntityT]) -> Result[EntityT, DomainError]:
            assert base is not None
            existing, err = await fetch_or_not_found(
                op.provider, identity_query(base, op, sf, id_names),
                entity_name, op, id_names,
            )
            if err is not None:
                return err
            assert existing is not None

            # Merge: only explicitly sent fields override existing.
            # Entity fields are dynamic — no static type for field values.
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


@dataclass(frozen=True, slots=True)
class SortedFetchMany:
    """Handler: provider.fetch_many(query) -> sorted list[entity].

    Reads op.sort and op.order fields (added by sorted_list() transform).
    Falls back to defaults if not provided. Sorts in-memory after fetch.

    scope_fields: pre-filter base_query by these fields (for nested resources).
    """

    default_sort: str | None = None
    default_order: str = "asc"
    scope_fields: tuple[str, ...] = ()

    def build[EntityT](self, spec: HandlerSpec[EntityT]) -> OperationHandler[list[EntityT], DomainError]:
        base = spec.base_query
        sf = self.scope_fields
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


__all__ = (
    "FetchMany",
    "FetchOneById",
    "InsertNew",
    "UpdateExisting",
    "DeleteOne",
    "PaginatedFetchMany",
    "CachedFetchOneById",
    "PatchExisting",
    "SortedFetchMany",
)

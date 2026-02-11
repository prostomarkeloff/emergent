"""Capability-aware adaptation — self-contained derivelib compiler.

Dogfoods wire's pattern: handler tables + fold over capabilities.
Wire is never modified. derivelib reads schema capabilities and
adapts derivation through its own handler tables.

Two adaptation passes:
  1. Ops: fold schema_meta → transform Op tuples (handler templates, projections)
  2. Query: fold schema_meta → transform base_query (filters, scopes)

    # Auto (reads @schema_meta, folds through handler tables):
    ops = adapt_ops(ALL_CRUD_OPS, User)
    step = adapt_base_query()

    # Manual (composable transforms):
    ops = with_soft_delete(ALL_CRUD_OPS, "deleted_at")
    ops = with_timestamps(ops, "created_at", "updated_at")
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from kungfu import Error, Ok, Result

if TYPE_CHECKING:
    from derivelib._ctx import OperationHandler
    from derivelib._errors import DomainError

from emergent.wire.axis.schema._universal import get_schema_meta

from emergent.wire.axis.query import RelationalQuerySet
from derivelib._ctx import QueryCtx
from derivelib._protocols import HandlerSpec
from derivelib._dialect import Op
from derivelib._effects import Creates, Deletes, Updates, has_effect
from derivelib._project import ExcludeFromProjection


# ═══════════════════════════════════════════════════════════════════════════════
# Fold — reuse wire's universal fold primitive
# ═══════════════════════════════════════════════════════════════════════════════

from emergent.wire.compile._core import fold as _wire_fold


class _NeverMatch:
    """Protocol that nothing implements — forces handlers-only dispatch in wire.fold()."""


def _fold_caps[Cap, Ctx](
    caps: tuple[Cap, ...],
    initial: Ctx,
    handlers: Mapping[type, Callable[..., Ctx]],
) -> Ctx:
    """Fold schema capabilities through handler table.

    Delegates to wire's universal fold() with handlers-only dispatch.
    Capabilities not in handlers are silently skipped (open-world).
    """
    return _wire_fold(caps, initial, _NeverMatch, "_never", handlers)


# ═══════════════════════════════════════════════════════════════════════════════
# Adaptation Contexts
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class _OpsCtx:
    """Ops adaptation context — accumulated during fold."""

    ops: tuple[Op, ...]
    created_field: str | None = None
    updated_field: str | None = None


@dataclass(frozen=True, slots=True)
class _QueryCtx[T]:
    """Query adaptation context — accumulated during fold."""

    base_query: RelationalQuerySet[T]


# ═══════════════════════════════════════════════════════════════════════════════
# Handler Templates (capability-specific replacements)
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class SoftDeleteMark:
    """Soft-delete: set deleted_at instead of hard delete.

    Replaces DeleteOne. Finds entity by identity (base_query already
    filters out deleted), sets deleted_at = now(), provider.update().
    """

    deleted_field: str = "deleted_at"

    def build[EntityT](
        self, spec: HandlerSpec[EntityT]
    ) -> OperationHandler[EntityT, DomainError]:
        from derivelib._errors import NotFound
        from derivelib._protocols import HasProvider
        from derivelib._query_helpers import filter_by_identity, identity_values

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
                result: Result[EntityT, DomainError] = Error(NotFound(entity=entity_name, id=identity_values(op, id_names)))
                return result

            # Use spec field names instead of dc_fields() to avoid DataclassInstance
            # type constraint on EntityT (which is an unconstrained TypeVar).
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

    Replaces InsertNew. Same logic but overrides timestamp fields
    with datetime.now(tz=timezone.utc) before entity construction.
    """

    created_field: str
    updated_field: str

    def build[EntityT](
        self, spec: HandlerSpec[EntityT]
    ) -> OperationHandler[EntityT, DomainError]:
        from derivelib._protocols import HasProvider

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

    Replaces UpdateExisting. Same logic but overrides updated_at
    with datetime.now(tz=timezone.utc) after merging fields.
    """

    updated_field: str

    def build[EntityT](
        self, spec: HandlerSpec[EntityT]
    ) -> OperationHandler[EntityT, DomainError]:
        from derivelib._errors import NotFound
        from derivelib._protocols import HasProvider
        from derivelib._query_helpers import filter_by_identity, identity_values

        entity = spec.entity
        id_names = spec.identity_names
        entity_name = spec.entity_name
        non_id_names = list(spec.non_identity_names)
        base = spec.base_query
        uf = self.updated_field

        async def handler(op: HasProvider[EntityT]) -> Result[EntityT, DomainError]:
            assert base is not None
            query = filter_by_identity(base, op, id_names)
            existing = await op.provider.fetch_one(query)
            if existing is None:
                result: Result[EntityT, DomainError] = Error(NotFound(entity=entity_name, id=identity_values(op, id_names)))
                return result

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


# ═══════════════════════════════════════════════════════════════════════════════
# Op Transform Functions (manual composable API)
# ═══════════════════════════════════════════════════════════════════════════════


def with_soft_delete(
    ops: tuple[Op, ...], deleted_field: str
) -> tuple[Op, ...]:
    """Replace Delete handler with soft-delete mark.

    Read ops (List, Get) are unaffected — they use base_query which
    AdaptBaseQuery already filters. Only Delete action changes.
    Dispatches on Deletes effect — any op declaring Deletes() gets replaced.
    """
    return tuple(
        replace(op, handler_template=SoftDeleteMark(deleted_field))
        if has_effect(op.effects, Deletes)
        else op
        for op in ops
    )


def with_timestamps(
    ops: tuple[Op, ...], created_field: str, updated_field: str
) -> tuple[Op, ...]:
    """Wrap Create/Update handlers with timestamp auto-set.

    Also excludes timestamp fields from input projections
    (they're auto-managed, not user-provided).
    Dispatches on Creates/Updates effects — any op declaring those gets adapted.
    """
    exclude_names = (created_field, updated_field)
    result: list[Op] = []
    for op in ops:
        if has_effect(op.effects, Creates):
            result.append(
                replace(
                    op,
                    input_proj=ExcludeFromProjection(op.input_proj, exclude_names),
                    handler_template=TimestampInsert(created_field, updated_field),
                )
            )
        elif has_effect(op.effects, Updates):
            result.append(
                replace(
                    op,
                    input_proj=ExcludeFromProjection(op.input_proj, exclude_names),
                    handler_template=TimestampUpdate(updated_field),
                )
            )
        else:
            result.append(op)
    return tuple(result)


# ═══════════════════════════════════════════════════════════════════════════════
# Handler Tables — map wire capability types → adaptation logic
# ═══════════════════════════════════════════════════════════════════════════════


def _ops_handlers() -> dict[type, Callable[..., _OpsCtx]]:
    """Ops handler table. Lazy import to avoid cycles."""
    from emergent.wire.axis.schema.dialects.temporal import (
        CreatedAt,
        SoftDelete,
        Timestamps,
        UpdatedAt,
    )

    def _soft_delete(cap: SoftDelete, ctx: _OpsCtx) -> _OpsCtx:
        return replace(ctx, ops=with_soft_delete(ctx.ops, cap.field_name))

    def _timestamps(cap: Timestamps, ctx: _OpsCtx) -> _OpsCtx:
        return replace(
            ctx,
            ops=with_timestamps(ctx.ops, cap.created_field, cap.updated_field),
        )

    def _created_at(cap: CreatedAt, ctx: _OpsCtx) -> _OpsCtx:
        created = cap.field_name
        ctx = replace(ctx, created_field=created)
        if ctx.updated_field is not None:
            return replace(
                ctx,
                ops=with_timestamps(ctx.ops, created, ctx.updated_field),
            )
        return ctx

    def _updated_at(cap: UpdatedAt, ctx: _OpsCtx) -> _OpsCtx:
        updated = cap.field_name
        ctx = replace(ctx, updated_field=updated)
        if ctx.created_field is not None:
            return replace(
                ctx,
                ops=with_timestamps(ctx.ops, ctx.created_field, updated),
            )
        return ctx

    return {
        SoftDelete: _soft_delete,
        Timestamps: _timestamps,
        CreatedAt: _created_at,
        UpdatedAt: _updated_at,
    }


def _query_handlers() -> dict[type, Callable[..., _QueryCtx[Any]]]:
    """Query handler table. Lazy import to avoid cycles.

    Any in _QueryCtx[Any]: Python cannot express rank-2 polymorphism
    ("for all T, Callable[..., _QueryCtx[T]]") in dict value types.
    Type is restored at fold boundaries in derive_query.
    """
    from emergent.wire.axis.schema.dialects.temporal import SoftDelete

    def _soft_delete(cap: SoftDelete, ctx: _QueryCtx[Any]) -> _QueryCtx[Any]:
        field = cap.field_name
        return replace(
            ctx,
            base_query=ctx.base_query.filter(
                lambda e, _f=field: getattr(e, _f).is_null()
            ),
        )

    return {
        SoftDelete: _soft_delete,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# AdaptationDialect — extensible registry for adaptation logic
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class AdaptationDialect:
    """Extensible adaptation registry — handler tables for ops + query.

    Open-world: anyone can register handlers for custom schema capabilities
    without modifying derivelib source.

        custom = DEFAULT_ADAPTATION.with_ops_handler(MyCapability, my_handler)
        Dialect(..., adaptation=custom)
    """

    ops_handlers: dict[type, Callable[..., _OpsCtx]]
    query_handlers: dict[type, Callable[..., _QueryCtx[Any]]]

    def adapt_ops(self, ops: tuple[Op, ...], entity: type) -> tuple[Op, ...]:
        """Fold schema capabilities → transform ops."""
        caps = get_schema_meta(entity)
        if not caps:
            return ops
        result = _fold_caps(caps, _OpsCtx(ops=ops), self.ops_handlers)
        return result.ops

    def adapt_base_query_step(self) -> AdaptBaseQuery:
        """Create AdaptBaseQuery derivation step using this dialect's handlers."""
        return AdaptBaseQuery(query_handlers=self.query_handlers)

    def with_ops_handler(
        self,
        cap_type: type,
        handler: Callable[..., _OpsCtx],
    ) -> AdaptationDialect:
        """Register a new ops handler for a capability type."""
        return replace(
            self, ops_handlers={**self.ops_handlers, cap_type: handler}
        )

    def with_query_handler(
        self,
        cap_type: type,
        handler: Callable[..., _QueryCtx[Any]],
    ) -> AdaptationDialect:
        """Register a new query handler for a capability type."""
        return replace(
            self, query_handlers={**self.query_handlers, cap_type: handler}
        )


def default_adaptation() -> AdaptationDialect:
    """Build default AdaptationDialect. Pure function — no global state.

    Lazy imports inside _ops_handlers/_query_handlers avoid import cycles.
    """
    return AdaptationDialect(
        ops_handlers=_ops_handlers(),
        query_handlers=_query_handlers(),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Public API (backward-compatible wrappers)
# ═══════════════════════════════════════════════════════════════════════════════


def adapt_ops(ops: tuple[Op, ...], entity: type) -> tuple[Op, ...]:
    """Fold schema capabilities → transform ops.

    Reads @schema_meta from entity, folds through handler table.
    Self-contained — wire is never modified.
    """
    return default_adaptation().adapt_ops(ops, entity)


@dataclass(frozen=True, slots=True)
class AdaptBaseQuery:
    """Query-phase derivation step: fold schema capabilities → adapt base_query.

    Reads @schema_meta from entity, folds through handler table.
    Plugs into derivelib's fold_derive as a QueryDerivable step.
    """

    query_handlers: dict[type, Callable[..., _QueryCtx[Any]]] | None = None

    def derive_query[EntityT](self, ctx: QueryCtx[EntityT]) -> QueryCtx[EntityT]:
        caps = get_schema_meta(ctx.schema.entity)
        if not caps or ctx.base_query is None:
            return ctx
        handlers = self.query_handlers if self.query_handlers is not None else _query_handlers()
        result = _fold_caps(
            caps, _QueryCtx(base_query=ctx.base_query), handlers
        )
        return replace(ctx, base_query=result.base_query)


def adapt_base_query() -> AdaptBaseQuery:
    """Create AdaptBaseQuery derivation step."""
    return AdaptBaseQuery()


# ═══════════════════════════════════════════════════════════════════════════════
# Exports
# ═══════════════════════════════════════════════════════════════════════════════

__all__ = (
    # Public API
    "adapt_ops",
    "adapt_base_query",
    "AdaptBaseQuery",
    # Extensible registry
    "AdaptationDialect",
    "default_adaptation",
    # Handler templates (reusable building blocks)
    "SoftDeleteMark",
    "TimestampInsert",
    "TimestampUpdate",
    # Manual op transforms
    "with_soft_delete",
    "with_timestamps",
)

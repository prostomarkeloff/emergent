"""Soft delete — mark as deleted instead of removing.

soft_delete() = DerivationT that:
  - Replaces Delete handler with set-deleted_at
  - Wraps List to filter out deleted entities
  - Wraps Get to reject deleted entities
  - Adds Restore op (unset deleted_at)

Entity must have a nullable deleted_at field (str | None = None).

    from examples.ultimate.soft_delete import soft_delete

    @derive(
        http_crud("/posts", provider_node=Posts)
            .chain(soft_delete())
    )
    @dataclass
    class Post:
        id: Annotated[int, Identity]
        title: str
        deleted_at: str | None = None
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, UTC
from typing import TYPE_CHECKING, Any

from kungfu import Ok, Error, Result

from derivelib import (
    Derivation, DerivationT, Step,
    Deletes, Mutation, Read, has_effect,
    NotFound, InvalidData, ExcludeFromProjection,
    HandlerSpec, WrappedTemplate,
    fetch_by_identity, not_found_error,
)
from derivelib._ctx import OperationHandler
from derivelib._protocols import HasProvider, WrapperFn

if TYPE_CHECKING:
    from derivelib._errors import DomainError


def _filter_active(items: Any, field: str) -> Any:
    """Filter out soft-deleted items.

    Any: isinstance narrows EntityT→list[Unknown]; iterate via Any to avoid
    pyright Unknown chain from generic type parameter isinstance narrowing.
    """
    return [e for e in items if getattr(e, field, None) is None]


# ═══════════════════════════════════════════════════════════════════════════════
# Handler Wrappers
# ═══════════════════════════════════════════════════════════════════════════════


def _make_soft_delete_wrapper(
    field: str,
) -> WrapperFn:
    """Replace hard delete with set-deleted_at timestamp."""

    def wrapper[EntityT](inner: OperationHandler[EntityT, DomainError], spec: HandlerSpec[EntityT]) -> OperationHandler[Any, DomainError]:
        async def handler(op: HasProvider[EntityT]) -> Result[dict[str, bool], DomainError]:
            obj = await fetch_by_identity(op.provider, spec.entity, op, spec.identity_names)
            if obj is None:
                return not_found_error(spec.entity_name, op, spec.identity_names)

            updated = spec.entity(**{
                **{name: getattr(obj, name) for name in (*spec.identity_names, *spec.non_identity_names)},
                field: datetime.now(UTC).isoformat(),
            })
            await op.provider.update(updated)
            return Ok({"success": True})

        return handler

    return wrapper


def _make_filter_deleted_wrapper(
    field: str,
) -> WrapperFn:
    """Wrap read handler: filter out soft-deleted entities."""

    def wrapper[EntityT](inner: OperationHandler[EntityT, DomainError], spec: HandlerSpec[EntityT]) -> OperationHandler[Any, DomainError]:
        async def handler(op: HasProvider[EntityT]) -> Result[EntityT | list[EntityT], DomainError]:
            result = await inner(op)
            if not isinstance(result, Ok):
                return result

            val: Any = result.value  # Any needed: isinstance(val, list) narrows to list[Unknown] for EntityT iteration

            # list: filter out deleted
            if isinstance(val, list):
                return Ok(_filter_active(val, field))

            # single entity: reject if deleted
            if hasattr(val, field) and getattr(val, field) is not None:
                return Error(NotFound(entity=spec.entity_name, id={}))

            return result

        return handler

    return wrapper


def _make_restore_wrapper(
    field: str,
) -> WrapperFn:
    """Handler for restore: unset deleted_at."""

    def wrapper[EntityT](inner: OperationHandler[EntityT, DomainError], spec: HandlerSpec[EntityT]) -> OperationHandler[Any, DomainError]:
        async def handler(op: HasProvider[EntityT]) -> Result[dict[str, bool], DomainError]:
            obj = await fetch_by_identity(op.provider, spec.entity, op, spec.identity_names)
            if obj is None:
                return not_found_error(spec.entity_name, op, spec.identity_names)
            if getattr(obj, field, None) is None:
                return Error(InvalidData(entity=spec.entity_name, reason="not deleted"))

            updated = spec.entity(**{
                **{name: getattr(obj, name) for name in (*spec.identity_names, *spec.non_identity_names)},
                field: None,
            })
            await op.provider.update(updated)
            return Ok({"success": True})

        return handler

    return wrapper


# ═══════════════════════════════════════════════════════════════════════════════
# soft_delete — DerivationT
# ═══════════════════════════════════════════════════════════════════════════════


def soft_delete(
    field: str = "deleted_at",
) -> DerivationT:
    """Replace hard delete with soft delete, filter reads, add restore.

    Entity must have: deleted_at: str | None = None

        .chain(soft_delete())
        .chain(soft_delete(field="removed_at"))
    """
    delete_wrapper = _make_soft_delete_wrapper(field)
    filter_wrapper = _make_filter_deleted_wrapper(field)
    restore_wrapper = _make_restore_wrapper(field)

    def transform(steps: Derivation) -> Derivation:
        from derivelib.axes.surface import DeriveOp
        from derivelib import FetchOneById

        result: list[Step] = []
        restore_added = False

        for s in steps:
            if not isinstance(s, DeriveOp):
                result.append(s)
                continue

            if has_effect(s.effects, Deletes):
                # Replace Delete with soft delete
                wrapped = WrappedTemplate(inner=s.handler_template, wrapper=delete_wrapper)
                result.append(replace(s, handler_template=wrapped))

                # Add Restore op (once, after Delete)
                if not restore_added:
                    from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger

                    # Build restore path from delete trigger
                    restore_path: str = getattr(s.trigger, "path").rstrip("/") + "/restore"
                    restore = replace(
                        s,
                        name="Restore",
                        handler_template=WrappedTemplate(
                            inner=FetchOneById(),
                            wrapper=restore_wrapper,
                        ),
                        trigger=HTTPRouteTrigger("POST", restore_path),
                        effects=(),
                    )
                    result.append(restore)
                    restore_added = True

            elif has_effect(s.effects, Read):
                # Wrap reads to filter out deleted
                wrapped = WrappedTemplate(inner=s.handler_template, wrapper=filter_wrapper)
                result.append(replace(s, handler_template=wrapped))

            elif has_effect(s.effects, Mutation):
                # Exclude deleted_at from create/update input — it's server-managed
                excluded = ExcludeFromProjection(s.input_proj, (field,))
                result.append(replace(s, input_proj=excluded))

            else:
                result.append(s)

        return tuple(result)

    return transform


__all__ = (
    "soft_delete",
)

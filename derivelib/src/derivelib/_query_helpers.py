"""Generic identity query helpers — shared across all derivation dialects.

These work for any relational entity with identity fields.
Not CRUD-specific.

    from derivelib._query_helpers import filter_by_identity, identity_values

    query = filter_by_identity(base_query, op, ("user_id", "product_id"))
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from kungfu import Error

from derivelib._errors import DomainError, IdentityMap, NotFound

if TYPE_CHECKING:
    from emergent.wire.axis.query import MutatingRelationalProvider, RelationalQuerySet
    from derivelib._protocols import HasProvider


def filter_by_identity[T](
    query: RelationalQuerySet[T], op: HasProvider[T], id_names: tuple[str, ...]
) -> RelationalQuerySet[T]:
    """Build chained identity filter — works for single and composite keys.

    Args:
        query: Relational query to filter
        op: Op instance with identity field values as attributes
        id_names: Identity field names to filter by
    """
    for name in id_names:
        val = getattr(op, name)
        query = query.filter(lambda e, _n=name, _v=val: getattr(e, _n) == _v)
    return query


def identity_values(op: object, id_names: tuple[str, ...]) -> IdentityMap:
    """Extract identity values as dict. Always returns dict.

    Uses getattr with runtime field names — no static type constraint
    is possible for op beyond object (getattr boundary).
    """
    return {n: getattr(op, n) for n in id_names}


def scoped_query[T](
    base: RelationalQuerySet[T], op: HasProvider[T], scope_fields: tuple[str, ...]
) -> RelationalQuerySet[T]:
    """Apply scope filters to base query. No-op if scope_fields empty."""
    return filter_by_identity(base, op, scope_fields) if scope_fields else base


def identity_query[T](
    base: RelationalQuerySet[T],
    op: HasProvider[T],
    scope_fields: tuple[str, ...],
    id_names: tuple[str, ...],
) -> RelationalQuerySet[T]:
    """Apply scope + identity filters to base query."""
    return filter_by_identity(scoped_query(base, op, scope_fields), op, id_names)


def not_found_error(
    entity_name: str, op: object, id_names: tuple[str, ...]
) -> Error[DomainError]:
    """Build Error(NotFound(...)) for missing entity.

    Uses getattr with runtime field names — no static type constraint
    is possible for op beyond object (getattr boundary).
    """
    err: DomainError = NotFound(entity=entity_name, id=identity_values(op, id_names))
    return Error(err)


async def fetch_or_not_found[T](
    provider: MutatingRelationalProvider[T],
    query: RelationalQuerySet[T],
    entity_name: str,
    op: HasProvider[T],
    id_names: tuple[str, ...],
) -> tuple[T | None, Error[DomainError] | None]:
    """Fetch one entity or return (None, not_found_error).

    Returns (entity, None) on success, (None, error) on not found.

        entity, err = await fetch_or_not_found(op.provider, q, "User", op, id_names)
        if err is not None:
            return err
    """
    result = await provider.fetch_one(query)
    if result is None:
        return None, not_found_error(entity_name, op, id_names)
    return result, None


async def fetch_by_identity[T](
    provider: MutatingRelationalProvider[T],
    entity: type[T],
    op: HasProvider[T],
    id_names: tuple[str, ...],
) -> T | None:
    """Build relational query from identity fields, fetch one entity.

    Returns entity or None. Combines relational() + filter_by_identity
    for surface steps that don't have a pre-built base_query.

        obj = await fetch_by_identity(op.provider, entity, op, id_names)
        if obj is None:
            return not_found_error(entity.__name__, op, id_names)
    """
    from emergent.wire.axis.query import relational

    q = filter_by_identity(relational(entity), op, id_names)
    return await provider.fetch_one(q)


def serialize_op_fields(op: object, field_names: tuple[str, ...] | list[str]) -> str:
    """JSON-serialize op fields for audit/event/webhook payloads.

    Skips None values. Falls back to str() for non-JSON-serializable values.
    Returns JSON string.

    Uses getattr with runtime field names — no static type constraint
    is possible for op beyond object (getattr boundary).

        payload = serialize_op_fields(op, spec.non_identity_names)
    """
    import json

    payload: dict[str, str | int | float | bool] = {}
    for name in field_names:
        val = getattr(op, name, None)
        if val is not None:
            try:
                json.dumps(val)
                payload[name] = val
            except (TypeError, ValueError):
                payload[name] = str(val)
    return json.dumps(payload)


def provider_field(node_type: type) -> type:
    """Annotated provider field for surface step request types.

    Eliminates the repeated annotation boilerplate::

        # before:
        fields["provider"] = Annotated[MutatingRelationalProvider, ComposeNode(node)]

        # after:
        fields["provider"] = provider_field(node)

    Returns Annotated[MutatingRelationalProvider[T], ComposeNode(node_type)]
    constructed dynamically — the T is resolved at runtime by compose.Node.
    """
    import typing

    from emergent.wire.axis.query import MutatingRelationalProvider  # noqa: F811
    from emergent.wire.axis.schema.dialects.compose import Node as ComposeNode

    # Build Annotated form dynamically to avoid pyright evaluating
    # the unparameterized generic (MutatingRelationalProvider requires type args).
    # At runtime, compose.Node resolves the concrete provider type.
    annotated_getitem: Callable[..., type] = getattr(typing, "Annotated").__getitem__
    return annotated_getitem((MutatingRelationalProvider, ComposeNode(node_type)))


def id_path(id_names: tuple[str, ...]) -> str:
    """Build URL path segment from identity field names.

    Returns ``"{id}"`` for single identity, ``"{a}/{b}"`` for composite.

        trigger = HTTPRouteTrigger("POST", f"{base}/{id_path(id_names)}/submit")
    """
    return "/".join(f"{{{n}}}" for n in id_names)


__all__ = (
    "filter_by_identity",
    "identity_values",
    "scoped_query",
    "identity_query",
    "not_found_error",
    "fetch_or_not_found",
    "fetch_by_identity",
    "serialize_op_fields",
    "provider_field",
    "id_path",
)

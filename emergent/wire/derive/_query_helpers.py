"""Generic identity query helpers — shared across all derivation patterns.

Work for any relational entity with identity fields and a provider.

    from emergent.wire.derive._query_helpers import filter_by_identity, identity_values
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import TYPE_CHECKING

from kungfu import Error

from emergent.wire.derive._errors import DomainError, IdentityMap, NotFound

if TYPE_CHECKING:
    from emergent.wire.axis.query import MutatingRelationalProvider, RelationalQuerySet
    from emergent.wire.derive._handler import HasProvider


def filter_by_identity[T](
    query: RelationalQuerySet[T], op: HasProvider[T], id_names: tuple[str, ...]
) -> RelationalQuerySet[T]:
    """Build chained identity filter — works for single and composite keys."""
    for name in id_names:
        val = getattr(op, name)
        query = query.filter(lambda e, _n=name, _v=val: getattr(e, _n) == _v)
    return query


def identity_values(op: object, id_names: tuple[str, ...]) -> IdentityMap:
    """Extract identity values as dict."""
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
    """Build Error(NotFound(...)) for missing entity."""
    err: DomainError = NotFound(entity=entity_name, id=identity_values(op, id_names))
    return Error(err)


async def fetch_or_not_found[T](
    provider: MutatingRelationalProvider[T],
    query: RelationalQuerySet[T],
    entity_name: str,
    op: HasProvider[T],
    id_names: tuple[str, ...],
) -> tuple[T | None, Error[DomainError] | None]:
    """Fetch one entity or return (None, not_found_error)."""
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
    """Build relational query from identity fields, fetch one entity."""
    from emergent.wire.axis.query import relational

    q = filter_by_identity(relational(entity), op, id_names)
    return await provider.fetch_one(q)


def serialize_op_fields(op: object, field_names: tuple[str, ...] | list[str]) -> str:
    """JSON-serialize op fields for audit/event/webhook payloads."""
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
    """Annotated provider field for request types with ComposeNode."""
    import typing

    from emergent.wire.axis.query import MutatingRelationalProvider  # noqa: F811
    from emergent.wire.axis.schema.dialects.compose import Node as ComposeNode

    annotated_getitem: Callable[..., type] = getattr(typing, "Annotated").__getitem__
    return annotated_getitem((MutatingRelationalProvider, ComposeNode(node_type)))


def id_path(id_names: tuple[str, ...]) -> str:
    """Build URL path segment from identity field names.

    Returns "{id}" for single identity, "{a}/{b}" for composite.
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

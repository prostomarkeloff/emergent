"""Query strategies — generic query configuration for derive.

RelationalStrategy is the default (current behavior extracted).
Custom strategies enable non-relational derivations (KV, event sourcing, etc.).

    from emergent.wire.derive._query_strategy import (
        QueryStrategy, RelationalStrategy, NoQueryStrategy, ProviderInjection,
    )
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from emergent.wire.axis.query import RelationalQuerySet


@dataclass(frozen=True, slots=True)
class QueryStrategy[EntityT]:
    """Abstract query configuration. Subclass for custom query spaces."""


@dataclass(frozen=True, slots=True)
class ProviderInjection:
    """How to inject a provider into op/request types.

    Defunctionalized — inspectable, replaceable data.
    """

    op_field: tuple[str, type]
    request_field: tuple[str, type]


@dataclass(frozen=True, slots=True)
class RelationalStrategy[EntityT](QueryStrategy[EntityT]):
    """Relational query strategy — current CRUD behavior extracted."""

    provider_node: type
    base_query: RelationalQuerySet[EntityT]
    injection: ProviderInjection | None = None


@dataclass(frozen=True, slots=True)
class NoQueryStrategy[EntityT](QueryStrategy[EntityT]):
    """No query strategy — for hand-crafted operations."""


__all__ = (
    "QueryStrategy",
    "RelationalStrategy",
    "NoQueryStrategy",
    "ProviderInjection",
)

"""Query axis steps — bind provider nodes and configure base queries.

Steps here implement QueryDerivable and run in pass 2 of fold_derive.

v4: BindProvider stores nodnod node TYPE for compose.Node resolution.
    No deps — provider resolved at runtime from scope.

    from derivelib.axes.query import bind_provider, base_query

    derivation = (
        bind_provider(UserProviderNode),  # nodnod node type
        base_query(),
    )
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace

from emergent.wire.axis.query import RelationalQuerySet, relational

from derivelib._ctx import QueryCtx


# ═══════════════════════════════════════════════════════════════════════════════
# Query Steps
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class BindProvider:
    """Step: bind provider node type for compose.Node resolution.

    Stores a nodnod node TYPE (not instance). At runtime, compose.Node
    resolves the provider from nodnod scope.
    """

    node_type: type

    def derive_query[EntityT](self, ctx: QueryCtx[EntityT]) -> QueryCtx[EntityT]:
        return replace(ctx, provider_node=self.node_type)


@dataclass(frozen=True, slots=True)
class SetBaseQuery:
    """Step: set base relational query for entity.

    Creates relational(entity) as the starting query.
    """

    def derive_query[EntityT](self, ctx: QueryCtx[EntityT]) -> QueryCtx[EntityT]:
        return replace(ctx, base_query=relational(ctx.schema.entity))


@dataclass(frozen=True, slots=True)
class SetCustomBaseQuery:
    """Step: set a custom base query."""

    query_factory: Callable[[type], RelationalQuerySet[type]]

    def derive_query[EntityT](self, ctx: QueryCtx[EntityT]) -> QueryCtx[EntityT]:
        return replace(ctx, base_query=self.query_factory(ctx.schema.entity))


# ═══════════════════════════════════════════════════════════════════════════════
# Convenience Constructors
# ═══════════════════════════════════════════════════════════════════════════════


def bind_provider(node_type: type) -> BindProvider:
    """Create BindProvider step.

    Args:
        node_type: nodnod node type that produces MutatingRelationalProvider.
    """
    return BindProvider(node_type=node_type)


def base_query() -> SetBaseQuery:
    """Create SetBaseQuery step."""
    return SetBaseQuery()


def custom_base_query(factory: Callable[[type], RelationalQuerySet[type]]) -> SetCustomBaseQuery:
    """Create SetCustomBaseQuery step."""
    return SetCustomBaseQuery(query_factory=factory)


__all__ = (
    # Steps
    "BindProvider",
    "SetBaseQuery",
    "SetCustomBaseQuery",
    # Constructors
    "bind_provider",
    "base_query",
    "custom_base_query",
)

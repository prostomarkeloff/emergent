"""Scope tiers — explicit scope hierarchy for compilation targets.

Defines tier markers (App, Request) and ScopeLayer for propagating
app-scope through Axes to execution functions.

    from emergent.wire.compile._lifetime import App, Request, ScopeLayer
    from emergent.graph import ScopeFamily

    family = (
        ScopeFamily[Tier]()
        .bind(App, DBPool, Config)
        .bind(Request, CurrentUser)
    )
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nodnod import Scope
    from emergent.graph._family import ScopeFamily


@dataclass(frozen=True, slots=True)
class Tier:
    """Scope tier marker. Hierarchy defined by parent pointer."""

    parent: Tier | None = None


App = Tier()
Request = Tier(parent=App)

type ScopeTiers = Mapping[Tier, Sequence[type]]
type TierScopes = Mapping[Tier, Scope]

_EMPTY_SCOPES: MappingProxyType[Tier, Scope] = MappingProxyType({})


@dataclass(frozen=True, slots=True)
class ScopeLayer:
    """Propagated via Axes to execution functions.

    scopes: pre-existing tier→scope mappings (e.g. {App: app_scope})
    family: ScopeFamily for generating mapped_scopes
    leaf: per-execution tier (e.g. Request) — scope created at runtime

    Derived properties:
        parent: walks leaf.parent chain → nearest scope in `scopes`
        compose: family.types_for(leaf)
    """

    scopes: TierScopes
    family: ScopeFamily[Tier]
    leaf: Tier

    @property
    def parent(self) -> Scope:
        """Walk leaf.parent chain to find nearest pre-existing scope."""
        tier = self.leaf.parent
        while tier is not None:
            if tier in self.scopes:
                return self.scopes[tier]
            tier = tier.parent
        raise LookupError(
            f"No scope found for any ancestor of leaf tier; "
            f"scopes has keys: {set(self.scopes)}"
        )

    @property
    def compose(self) -> frozenset[type]:
        """Types to compose into each leaf-tier scope."""
        return self.family.types_for(self.leaf)

    def with_scope(self, tier: Tier, scope: Scope) -> ScopeLayer:
        """Return new ScopeLayer with an additional tier→scope mapping."""
        return ScopeLayer(
            scopes=MappingProxyType({**self.scopes, tier: scope}),
            family=self.family,
            leaf=self.leaf,
        )


__all__ = (
    "Tier",
    "App",
    "Request",
    "ScopeTiers",
    "ScopeLayer",
)

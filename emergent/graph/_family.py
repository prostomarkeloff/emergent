"""ScopeFamily — free algebra for scope-to-tier mapping.

Composable type→tier bindings interpreted into nodnod mapped_scopes.

    from emergent.graph import ScopeFamily

    family = (
        ScopeFamily[Tier]()
        .bind(App, DBPool, Config)
        .bind(Request, CurrentUser)
    )

    # Compose:
    combined = family_a | family_b

    # Interpret → mapped_scopes for nodnod:
    mapped = family.materialize({App: app_scope, Request: request_scope})
    composer = Composer(scope=req_scope, agent_cls=agent, mapped_scopes=mapped)

The algebra:
    bind(key, *types) — assign types to a tier
    |                 — merge two families (right wins on conflict)
    materialize()     — interpret into dict[type, Scope] for nodnod
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from nodnod import Scope


@dataclass(frozen=True, slots=True)
class ScopeFamily[K]:
    """Free algebra: composable type→tier mapping.

    K is the tier key (Tier from _lifetime, str, enum, etc.).
    Pure data — no async, no effects, no scope creation.

    Composition via | (merge) and .bind() (extend).
    Interpretation via .materialize() → dict[type, Scope].
    """

    bindings: Mapping[type, K] = field(default_factory=lambda: MappingProxyType({}))

    def bind(self, key: K, *types: type) -> ScopeFamily[K]:
        """Bind types to a tier key.

            family.bind(App, DBPool, Config)
        """
        new = dict(self.bindings)
        for t in types:
            new[t] = key
        return ScopeFamily(MappingProxyType(new))

    def unbind(self, *types: type) -> ScopeFamily[K]:
        """Remove types from family."""
        new = {t: k for t, k in self.bindings.items() if t not in types}
        return ScopeFamily(MappingProxyType(new))

    def __or__(self, other: ScopeFamily[K]) -> ScopeFamily[K]:
        """Merge two families. Right side wins on conflict."""
        return ScopeFamily(MappingProxyType({**self.bindings, **other.bindings}))

    # --- Queries ---

    def types_for(self, key: K) -> frozenset[type]:
        """All types bound to a given tier."""
        return frozenset(t for t, k in self.bindings.items() if k is key)

    def tier_of(self, typ: type) -> K | None:
        """Which tier a type is bound to (None if unbound)."""
        return self.bindings.get(typ)

    def to_groups(self) -> Mapping[K, frozenset[type]]:
        """Invert: tier→types mapping."""
        result: dict[K, set[type]] = {}
        for typ, key in self.bindings.items():
            result.setdefault(key, set()).add(typ)
        return {k: frozenset(s) for k, s in result.items()}

    # --- Interpretation ---

    def materialize(self, scopes: Mapping[K, Scope]) -> Mapping[type, Scope]:
        """Interpret family into mapped_scopes for nodnod agent.run().

        Takes a mapping of tier keys to actual Scope objects (user-created).
        Returns dict[type, Scope] — the mapped_scopes parameter.

            mapped = family.materialize({App: app_scope, Request: req_scope})
            await agent.run(local_scope=req_scope, mapped_scopes=dict(mapped))
        """
        return MappingProxyType({
            typ: scopes[key]
            for typ, key in self.bindings.items()
            if key in scopes
        })


__all__ = ("ScopeFamily",)

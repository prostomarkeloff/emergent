"""RBAC — role-based authorization enricher + transforms.

RequireRole = ScopeEnricher that rejects if identity doesn't have required role.
require_role() = DerivationT that adds role-check enricher to ops.
authorize_ops() = DerivationT that maps per-operation role requirements.

    from derivelib.authlib.rbac import require_role, authorize_ops

    # All mutations require "editor" role:
    .chain(require_role(AuthUser, "editor", lambda u: u.roles))

    # Per-operation role gating:
    .chain(authorize_ops(AuthUser, {"Delete": "admin", "Create": "editor"}, lambda u: u.roles))
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from nodnod import Scope

from emergent.wire.axis.surface.capabilities import ScopeEnricher, EnricherNext

from derivelib._derivation import DerivationT
from derivelib._effects import DerivationEffect
from derivelib.transforms import add_capability

from .errors import AuthorizationFailed

if TYPE_CHECKING:
    from derivelib._derivation import Step


# ═══════════════════════════════════════════════════════════════════════════════
# RequireRole — enricher
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class RequireRole(ScopeEnricher):
    """Enricher: reject if identity doesn't have required role.

    Reads identity from scope via identity_type key.
    Extracts roles via role_getter(identity) -> set[str].
    Rejects if no intersection with required roles.

        RequireRole(AuthUser, frozenset({"admin"}), lambda u: u.roles)
    """

    identity_type: type
    roles: frozenset[str]
    role_getter: Callable[..., set[str]]

    async def enrich[R](self, call: EnricherNext[R], scope: Scope) -> R:
        wrapper = scope.get(self.identity_type)
        if wrapper is None:
            raise AuthorizationFailed("not authenticated")
        user_roles = self.role_getter(wrapper.value)
        if not self.roles & user_roles:
            raise AuthorizationFailed(f"requires one of: {self.roles}")
        return await call(scope)


# ═══════════════════════════════════════════════════════════════════════════════
# require_role — DerivationT
# ═══════════════════════════════════════════════════════════════════════════════


def require_role(
    identity_type: type,
    role: str,
    role_getter: Callable[..., set[str]],
    effect: type[DerivationEffect] | None = None,
) -> DerivationT:
    """Transform: add role-check enricher to ops.

    Uses add_capability — optionally filtered by effect type.

        # All ops require "admin":
        .chain(require_role(AuthUser, "admin", lambda u: u.roles))

        # Only mutations require "editor":
        .chain(require_role(AuthUser, "editor", lambda u: u.roles, effect=Mutation))
    """
    enricher = RequireRole(identity_type, frozenset({role}), role_getter)
    return add_capability(enricher, effect)


# ═══════════════════════════════════════════════════════════════════════════════
# authorize_ops — per-operation role gating
# ═══════════════════════════════════════════════════════════════════════════════


def authorize_ops(
    identity_type: type,
    role_map: dict[str, str],
    role_getter: Callable[..., set[str]],
) -> DerivationT:
    """Transform: per-operation role gating.

    Maps operation names to required roles. Only ops named in role_map
    get enrichers — others pass through unchanged.

        .chain(authorize_ops(
            AuthUser,
            {"Delete": "admin", "Create": "editor"},
            lambda u: u.roles,
        ))
    """
    from derivelib._protocols import TransformableStep, replace_caps

    def transform(steps: tuple[Step, ...]) -> tuple[Step, ...]:
        result: list[Step] = []
        for s in steps:
            if isinstance(s, TransformableStep) and s.name in role_map:
                enricher = RequireRole(
                    identity_type,
                    frozenset({role_map[s.name]}),
                    role_getter,
                )
                result.append(replace_caps(s, (*s.capabilities, enricher)))
            else:
                result.append(s)
        return tuple(result)

    return transform


__all__ = (
    "RequireRole",
    "require_role",
    "authorize_ops",
)

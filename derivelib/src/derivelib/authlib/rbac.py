"""RBAC — proxy to RoleRequired and AuthorizeOps capabilities.

DEPRECATED: Use emergent.wire.derive.auth.caps directly.
derivelib will be removed in emergent 1.0.0.
"""

from __future__ import annotations

from collections.abc import Callable

from emergent.wire.axis.schema._universal import SchemaCapability
from emergent.wire.derive._effects import DerivationEffect
from emergent.wire.derive.auth.caps import (
    AuthorizeOps,
    RequireRole,
    RoleRequired,
)


def require_role(
    identity_type: type,
    role: str,
    role_getter: Callable[..., set[str]],
    effect: type[DerivationEffect] | None = None,
) -> SchemaCapability:
    """Add role-check enricher to ops.

    Returns a RoleRequired capability (wire.derive SchemaCapability).

        .chain(require_role(AuthUser, "admin", lambda u: u.roles))
        .chain(require_role(AuthUser, "editor", lambda u: u.roles, effect=Mutation))
    """
    return RoleRequired(
        identity_type=identity_type,
        role=role,
        role_getter=role_getter,
        effect=effect,
    )


def authorize_ops(
    identity_type: type,
    role_map: dict[str, str],
    role_getter: Callable[..., set[str]],
) -> SchemaCapability:
    """Per-operation role gating.

    Returns an AuthorizeOps capability (wire.derive SchemaCapability).

        .chain(authorize_ops(
            AuthUser,
            {"Delete": "admin", "Create": "editor"},
            lambda u: u.roles,
        ))
    """
    return AuthorizeOps(
        identity_type=identity_type,
        role_map=role_map,
        role_getter=role_getter,
    )


__all__ = (
    "RequireRole",
    "require_role",
    "authorize_ops",
)

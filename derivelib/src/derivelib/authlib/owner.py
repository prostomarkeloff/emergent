"""Owner-scoped queries — proxy to OwnerScoped capability.

DEPRECATED: Use emergent.wire.derive.auth.caps.OwnerScoped directly.
derivelib will be removed in emergent 1.0.0.
"""

from __future__ import annotations

from emergent.wire.axis.schema._universal import SchemaCapability
from emergent.wire.derive.auth.caps import OwnerContext, OwnerScoped


def owner_scoped(
    identity_type: type,
    owner_field: str = "owner_id",
    identity_attr: str = "id",
) -> SchemaCapability:
    """Pre-filter all ops by owner identity.

    Returns an OwnerScoped capability (wire.derive SchemaCapability).

        .chain(owner_scoped(AuthUser, owner_field="author_id", identity_attr="name"))
    """
    return OwnerScoped(
        identity_type=identity_type,
        owner_field=owner_field,
        identity_attr=identity_attr,
    )


__all__ = (
    "OwnerContext",
    "owner_scoped",
)

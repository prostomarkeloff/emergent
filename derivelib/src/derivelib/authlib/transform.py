"""Auth transform — proxy to Authenticated capability.

DEPRECATED: Use emergent.wire.derive.auth.Authenticated directly.
derivelib will be removed in emergent 1.0.0.
"""

from __future__ import annotations

from emergent.wire.axis.schema._universal import SchemaCapability
from emergent.wire.axis.surface.capabilities import ScopeEnricher
from emergent.wire.derive._effects import DerivationEffect, Mutation
from emergent.wire.derive.auth.caps import Authenticated
from emergent.wire.derive.auth.validate import TokenValidate


def require_auth(
    validate: TokenValidate,
    *extractors: ScopeEnricher,
    effect: type[DerivationEffect] = Mutation,
) -> SchemaCapability:
    """Add auth gating to ops with given effect.

    Returns an Authenticated capability (wire.derive SchemaCapability).

        .chain(require_auth(validate, BearerExtract()))
        .chain(require_auth(validate, BearerExtract(), effect=DerivationEffect))
    """
    return Authenticated(*extractors, validate=validate, effect=effect)


__all__ = ("require_auth",)

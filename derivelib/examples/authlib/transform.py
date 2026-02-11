"""DerivationT transform — effect-driven auth gating.

require_auth = DerivationT that adds auth enricher chain to ops
matching a given effect. Uses map_by_effect — fold-based dispatch.

Enricher chain order: extractors → validate → handler.

    from authlib import require_auth, BearerExtract, TokenValidate

    auth = require_auth(
        TokenValidate(AuthUser, my_lookup),
        BearerExtract(),
        effect=Mutation,
    )

    @derive(http_crud("/posts", provider_node=Posts).chain(auth))
    @dataclass
    class Post: ...
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from emergent.wire.axis.surface.capabilities import ScopeEnricher, SurfaceCapability

from derivelib import DerivationT, DerivationEffect, Mutation, map_by_effect

from .openapi import AuthOpenAPI
from .validate import TokenValidate

if TYPE_CHECKING:
    from derivelib.axes.surface import DeriveOp as _DeriveOp


# ═══════════════════════════════════════════════════════════════════════════════
# require_auth — composable auth transform
# ═══════════════════════════════════════════════════════════════════════════════


def require_auth[V](
    validate: TokenValidate[V],
    *extractors: ScopeEnricher,
    effect: type[DerivationEffect] = Mutation,
) -> DerivationT:
    """Add auth gating to ops with given effect.

    Adds to matching ops:
      - Extractor enrichers (inject AuthToken into scope)
      - Validator enricher (check token, inject identity)
      - AuthOpenAPI capability (securitySchemes + per-route security + 401/403)

    Uses map_by_effect — only touches ops declaring the given effect.

        # Auth on mutations only (default):
        .chain(require_auth(validate, BearerExtract()))

        # Auth on ALL ops:
        .chain(require_auth(validate, BearerExtract(), effect=Read))
    """
    all_caps: tuple[SurfaceCapability, ...] = (*extractors, validate, AuthOpenAPI())

    def _add(_eff: DerivationEffect, op: _DeriveOp) -> _DeriveOp:
        return replace(op, capabilities=(*op.capabilities, *all_caps))

    return map_by_effect({effect: _add})


__all__ = (
    "require_auth",
)

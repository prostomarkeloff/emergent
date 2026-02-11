"""Credential validation — transport-agnostic identity injection.

TokenValidate = ScopeEnricher that reads AuthToken, validates via
user-provided lookup, injects user-defined identity type.

Generic over identity type — the library NEVER defines what identity
looks like. Could be str, int, AuthUser(id, role, perms), anything.
The identity type is a parameter.

    from authlib import TokenValidate, AuthToken

    validate = TokenValidate(
        identity_type=AuthUser,
        lookup=session_store.get_by_token,  # async (str) -> AuthUser | None
    )

Runtime chain: extractors inject AuthToken → validate reads it → injects identity.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from nodnod import Scope

from emergent.wire.axis.surface.capabilities import ScopeEnricher, EnricherNext

from .errors import AuthenticationRequired
from .extractors import AuthToken


# ═══════════════════════════════════════════════════════════════════════════════
# TokenValidate — generic identity injector
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class TokenValidate[V](ScopeEnricher):
    """Validate AuthToken from scope, inject user-defined identity.

    Generic over identity type V — injects under identity_type key.
    The lookup function is user-provided: async (token_str) -> V | None.

        validate = TokenValidate(
            identity_type=str,
            lookup=my_session_lookup,  # async (str) -> str | None
        )
    """

    identity_type: type[V]
    lookup: Callable[[str], Awaitable[V | None]]

    async def enrich[R](self, call: EnricherNext[R], scope: Scope) -> R:
        token_wrapper = scope.get(AuthToken)
        if token_wrapper is None:
            raise AuthenticationRequired()
        # scope.get() returns a wrapper; .value is the AuthToken dataclass
        auth_token: AuthToken = token_wrapper.value
        identity = await self.lookup(auth_token.value)
        if identity is None:
            raise AuthenticationRequired("invalid credentials")
        scope.inject(self.identity_type, identity)
        return await call(scope)


__all__ = (
    "TokenValidate",
)

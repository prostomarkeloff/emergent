"""Credential validation — transport-agnostic identity injection.

    from emergent.wire.derive.auth.validate import TokenValidate
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from nodnod import Scope

from emergent.wire.axis.surface.capabilities import EnricherNext, ScopeEnricher

from .errors import AuthenticationRequired
from .extractors import AuthToken


@dataclass(frozen=True, slots=True)
class TokenValidate(ScopeEnricher):
    """Validate AuthToken from scope, inject user-defined identity.

        validate = TokenValidate(
            identity_type=AuthUser,
            lookup=session_store.get_by_token,  # async (str) -> AuthUser | None
        )
    """

    identity_type: type
    lookup: Callable[..., Awaitable[object]]

    async def enrich[R](self, call: EnricherNext[R], scope: Scope) -> R:
        token_wrapper = scope.get(AuthToken)
        if token_wrapper is None:
            raise AuthenticationRequired()
        auth_token: AuthToken = token_wrapper.value
        identity = await self.lookup(auth_token.value)
        if identity is None:
            raise AuthenticationRequired("invalid credentials")
        scope.inject(self.identity_type, identity)
        return await call(scope)


__all__ = ("TokenValidate",)

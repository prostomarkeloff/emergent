"""Credential extractors — transport-specific AuthToken injection.

AuthToken = raw credential value (scope injection type)
Extractor = ScopeEnricher that injects AuthToken from its transport

Each extractor tries its transport, skips silently if not active.
Always calls next — never fails, never short-circuits.

    from derivelib.authlib.extractors import AuthToken, BearerExtract, CLITokenExtract

    # HTTP: Authorization: Bearer <token>
    BearerExtract()

    # CLI: --token <token> from argparse.Namespace
    CLITokenExtract()
    CLITokenExtract(attr_name="auth_token")  # custom attr

Open for extension — users write their own for other transports
(TG, WebSocket, gRPC, etc.) following the same pattern.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass

from nodnod import Scope

from emergent.wire.axis.surface.capabilities import ScopeEnricher, EnricherNext


# ═══════════════════════════════════════════════════════════════════════════════
# AuthToken — scope injection type
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class AuthToken:
    """Raw credential extracted from transport. Scope injection type."""

    value: str


# ═══════════════════════════════════════════════════════════════════════════════
# HTTP Extractor
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class BearerExtract(ScopeEnricher):
    """HTTP: extract Bearer token from Authorization header.

    Skips silently for non-HTTP scope (CLI, TG, etc.).
    Always calls next — never fails, never short-circuits.
    """

    async def enrich[R](self, call: EnricherNext[R], scope: Scope) -> R:
        try:
            import fastapi

            request = scope.get(fastapi.Request)
            if request is not None:
                auth = request.value.headers.get("authorization", "")
                if auth.startswith("Bearer "):
                    scope.inject(AuthToken, AuthToken(auth[7:]))
        except ImportError:
            pass
        return await call(scope)


# ═══════════════════════════════════════════════════════════════════════════════
# CLI Extractor
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class CLITokenExtract(ScopeEnricher):
    """CLI: extract token from argparse.Namespace attribute.

    Reads --token (or custom attr_name) from the CLI argument namespace.
    Skips silently for non-CLI scope (HTTP, TG, etc.).
    Always calls next — never fails, never short-circuits.

        # Default attr_name="token":
        #   my-app create-post --token <TOKEN> --author alice --title hi
        require_auth(validate, BearerExtract(), CLITokenExtract())

        # Custom attr_name:
        CLITokenExtract(attr_name="auth_token")
        #   my-app create-post --auth-token <TOKEN> ...
    """

    attr_name: str = "token"

    async def enrich[R](self, call: EnricherNext[R], scope: Scope) -> R:
        ns = scope.get(argparse.Namespace)
        if ns is not None:
            token_value = getattr(ns.value, self.attr_name, None)
            if isinstance(token_value, str) and token_value:
                scope.inject(AuthToken, AuthToken(token_value))
        return await call(scope)


__all__ = (
    # Scope injection type
    "AuthToken",
    # Extractors
    "BearerExtract",
    "CLITokenExtract",
)

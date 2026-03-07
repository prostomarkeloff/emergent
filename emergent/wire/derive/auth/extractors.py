"""Credential extractors — transport-specific AuthToken injection.

AuthToken = raw credential value (scope injection type)
Extractor = ScopeEnricher that injects AuthToken from its transport

Target-specific enrichers: BearerExtract uses enrich_fastapi/enrich_cli
instead of try/import conditional dispatch inside a single enrich().

    from emergent.wire.derive.auth.extractors import AuthToken, BearerExtract, CLITokenExtract
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass

from nodnod import Scope

from emergent.wire.axis.surface.capabilities import EnricherNext, ScopeEnricher


@dataclass(frozen=True, slots=True)
class AuthToken:
    """Raw credential extracted from transport. Scope injection type."""

    value: str


@dataclass(frozen=True, slots=True)
class BearerExtract(ScopeEnricher):
    """Bearer token extraction — target-specific.

    FastAPI: extracts from Authorization header.
    CLI: extracts from argparse --token flag.
    Universal fallback: no-op (passthrough).
    """

    cli_attr: str = "token"

    async def enrich_fastapi[R](self, call: EnricherNext[R], scope: Scope) -> R:
        """FastAPI: extract Bearer token from Authorization header."""
        import fastapi

        request = scope.get(fastapi.Request)
        if request is not None:
            auth = request.value.headers.get("authorization", "")
            if auth.startswith("Bearer "):
                scope.inject(AuthToken, AuthToken(auth[7:]))
        return await call(scope)

    async def enrich_cli[R](self, call: EnricherNext[R], scope: Scope) -> R:
        """CLI: extract token from argparse.Namespace attribute."""
        ns = scope.get(argparse.Namespace)
        if ns is not None:
            token_value = getattr(ns.value, self.cli_attr, None)
            if isinstance(token_value, str) and token_value:
                scope.inject(AuthToken, AuthToken(token_value))
        return await call(scope)

    async def enrich[R](self, call: EnricherNext[R], scope: Scope) -> R:
        """Universal fallback: passthrough (no extraction)."""
        return await call(scope)


@dataclass(frozen=True, slots=True)
class CLITokenExtract(ScopeEnricher):
    """CLI: extract token from argparse.Namespace attribute.

    Kept for backward compatibility. Prefer BearerExtract with cli_attr.
    """

    attr_name: str = "token"

    async def enrich_cli[R](self, call: EnricherNext[R], scope: Scope) -> R:
        ns = scope.get(argparse.Namespace)
        if ns is not None:
            token_value = getattr(ns.value, self.attr_name, None)
            if isinstance(token_value, str) and token_value:
                scope.inject(AuthToken, AuthToken(token_value))
        return await call(scope)

    async def enrich[R](self, call: EnricherNext[R], scope: Scope) -> R:
        """Universal fallback: passthrough."""
        return await call(scope)


__all__ = (
    "AuthToken",
    "BearerExtract",
    "CLITokenExtract",
)

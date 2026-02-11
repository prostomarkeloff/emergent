"""OpenAPI auth metadata — compile-time security annotations.

AuthOpenAPI = SurfaceCapability implementing both:
  - compile_fastapi: register securitySchemes on the app (once per schema gen)
  - compile_fastapi_route: add per-route security + 401/403 responses

Self-sufficient: no post-compile patching needed. The capability registers
the securityScheme on the app during compilation and adds per-route metadata
via openapi_extra.

    # Automatic — require_auth adds this capability
    require_auth(validate, BearerExtract())

    # Manual — add to any op
    add_capability(AuthOpenAPI())
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from emergent.wire.axis.surface.capabilities._base import SurfaceCapability

if TYPE_CHECKING:
    from emergent.wire.compile._capabilities import FastAPICompileContext
    from emergent.wire.axis._capability import FastAPIRouteContext


# ═══════════════════════════════════════════════════════════════════════════════
# RFC 7807 Problem Detail Schema
# ═══════════════════════════════════════════════════════════════════════════════


_PROBLEM_SCHEMA = {
    "type": "object",
    "properties": {
        "type": {"type": "string", "format": "uri"},
        "title": {"type": "string"},
        "status": {"type": "integer"},
        "detail": {"type": "string"},
        "instance": {"type": "string", "format": "uri"},
    },
    "required": ["type", "title", "status"],
}

_PROBLEM_MEDIA_TYPE = "application/problem+json"


# ═══════════════════════════════════════════════════════════════════════════════
# AuthOpenAPI — compile-time security capability
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class AuthOpenAPI(SurfaceCapability):
    """Add OpenAPI security scheme + per-route auth metadata at compile time.

    Implements both FastAPICompilable and FastAPIRouteCompilable protocols.
    The inner idempotent check (scheme_name not in schemes) makes it safe
    even if multiple routes add this capability.

        AuthOpenAPI()                      # default bearerAuth
        AuthOpenAPI(scheme_name="apiKey")  # custom scheme name
    """

    scheme_name: str = "bearerAuth"

    def compile_fastapi(self, ctx: FastAPICompileContext) -> FastAPICompileContext:
        """Register securitySchemes on the FastAPI app.

        Wraps app.openapi to inject the scheme at schema-generation time.
        """
        app = ctx.app
        scheme_name = self.scheme_name
        prev_openapi = app.openapi

        def patched_openapi():
            if app.openapi_schema:
                return app.openapi_schema
            schema = prev_openapi()
            components = schema.setdefault("components", {})
            schemes = components.setdefault("securitySchemes", {})
            if scheme_name not in schemes:
                schemes[scheme_name] = {
                    "type": "http",
                    "scheme": "bearer",
                }
            app.openapi_schema = schema
            return schema

        app.openapi = patched_openapi
        return ctx

    def compile_fastapi_route(self, ctx: FastAPIRouteContext) -> FastAPIRouteContext:
        """Add security requirement and 401/403 responses to this route."""
        auth_responses = {
            "401": {
                "description": "Authentication required",
                "content": {
                    _PROBLEM_MEDIA_TYPE: {"schema": _PROBLEM_SCHEMA},
                },
            },
            "403": {
                "description": "Insufficient permissions",
                "content": {
                    _PROBLEM_MEDIA_TYPE: {"schema": _PROBLEM_SCHEMA},
                },
            },
        }

        existing_extra = dict(ctx.openapi_extra) if ctx.openapi_extra else {}
        existing_responses = existing_extra.get("responses", {})
        scopes: list[str] = []
        security: list[dict[str, list[str]]] = [{self.scheme_name: scopes}]
        merged_extra = {
            **existing_extra,
            "security": security,
            "responses": {**existing_responses, **auth_responses},
        }
        return replace(ctx, openapi_extra=merged_extra)


__all__ = (
    "AuthOpenAPI",
)

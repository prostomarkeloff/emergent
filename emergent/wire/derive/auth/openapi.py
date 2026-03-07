"""OpenAPI auth metadata — compile-time security annotations.

    from emergent.wire.derive.auth.openapi import AuthOpenAPI
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

from emergent.wire.axis.surface.capabilities._base import SurfaceCapability
from emergent.wire.derive._errors import PROBLEM_SCHEMA as _PROBLEM_SCHEMA

if TYPE_CHECKING:
    from emergent.wire.axis._capability import FastAPIRouteContext
    from emergent.wire.compile._capabilities import FastAPICompileContext

_PROBLEM_MEDIA_TYPE = "application/problem+json"


@dataclass(frozen=True, slots=True)
class AuthOpenAPI(SurfaceCapability):
    """Add OpenAPI security scheme + per-route auth metadata at compile time.

        AuthOpenAPI()
        AuthOpenAPI(scheme_name="apiKey")
    """

    scheme_name: str = "bearerAuth"

    def compile_fastapi(self, ctx: FastAPICompileContext) -> FastAPICompileContext:
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
        # Any: openapi_extra is dict[str, Any] by definition (heterogeneous JSON).
        merged_extra: dict[str, Any] = {
            **existing_extra,
            "security": [{self.scheme_name: []}],
            "responses": {**existing_responses, **auth_responses},
        }
        return replace(ctx, openapi_extra=merged_extra)


__all__ = ("AuthOpenAPI",)

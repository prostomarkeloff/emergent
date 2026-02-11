"""HTTP/OpenAPI dialect — compile to FastAPI route configuration.

These capabilities use the compile_fastapi_route() pattern for consistency
with the schema axis capabilities.

Route-level (compile_fastapi_route):
    from emergent.wire.axis.surface.dialects import http

    endpoint(runner).expose(
        trigger, codec,
        http.Tag.of("users"),
        http.Summary.of("List all users"),
        http.BearerAuth.jwt(),
        http.ResponseStatus(201),
    )

App-level (compile_fastapi_app):
    app = Application(capabilities=(
        http.CORS(origins=("http://localhost:3000",)),
        http.GZip(minimum_size=500),
    ))
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, TYPE_CHECKING

from emergent.wire.axis._capability import (
    FastAPIAppContext,
    FastAPIRouteContext,
    fastapi_app_middleware,
    fastapi_route,
)
from emergent.wire.axis.surface.capabilities._base import SurfaceCapability

if TYPE_CHECKING:
    from fastapi.openapi.models import (
        APIKey as FAAPIKey,
        HTTPBearer as FAHTTPBearer,
        OAuth2 as FAOAuth2,
        Tag as FATag,
    )


def _get_fastapi_models() -> dict[str, type]:
    """Import FastAPI models at runtime."""
    try:
        from fastapi.openapi.models import (
            APIKey,
            HTTPBearer,
            OAuth2,
            OAuthFlowAuthorizationCode,
            OAuthFlowClientCredentials,
            OAuthFlowPassword,
            OAuthFlows,
            Tag,
        )
        return {
            "APIKey": APIKey,
            "HTTPBearer": HTTPBearer,
            "OAuth2": OAuth2,
            "OAuthFlowAuthorizationCode": OAuthFlowAuthorizationCode,
            "OAuthFlowClientCredentials": OAuthFlowClientCredentials,
            "OAuthFlowPassword": OAuthFlowPassword,
            "OAuthFlows": OAuthFlows,
            "Tag": Tag,
        }
    except ImportError as e:
        raise ImportError(
            "HTTP dialect capabilities require fastapi. "
            "Install with: pip install fastapi"
        ) from e


# ═══════════════════════════════════════════════════════════════════════════════
# Tags
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Tag(SurfaceCapability):
    """OpenAPI tag for endpoint grouping.

    Usage:
        Tag.of("auth", "Authentication endpoints")
        Tag(model)  # with pre-built FATag
    """

    model: FATag

    @classmethod
    def of(cls, name: str, description: str | None = None) -> Tag:
        """Create tag from name and optional description."""
        models = _get_fastapi_models()
        tag_cls = models["Tag"]
        return cls(tag_cls(name=name, description=description))

    def compile_fastapi_route(self, ctx: FastAPIRouteContext) -> FastAPIRouteContext:
        """Add tag to route configuration."""
        return fastapi_route(ctx, tags=(self.model.name,))


# ═══════════════════════════════════════════════════════════════════════════════
# Security Schemes
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class BearerAuth(SurfaceCapability):
    """Bearer token (JWT) security scheme.

    Usage:
        BearerAuth.jwt()
        BearerAuth.jwt("JWT token for authentication")
    """

    model: FAHTTPBearer
    scheme_name: str = "bearerAuth"

    @classmethod
    def jwt(cls, description: str | None = None) -> BearerAuth:
        """Create JWT bearer auth scheme."""
        models = _get_fastapi_models()
        bearer_cls = models["HTTPBearer"]
        return cls(
            model=bearer_cls(bearerFormat="JWT", description=description),
        )

    @classmethod
    def opaque(cls, description: str | None = None) -> BearerAuth:
        """Create opaque token bearer auth scheme."""
        models = _get_fastapi_models()
        bearer_cls = models["HTTPBearer"]
        return cls(
            model=bearer_cls(description=description),
        )

    def compile_fastapi_route(self, ctx: FastAPIRouteContext) -> FastAPIRouteContext:
        """Add bearer auth security requirement."""
        return fastapi_route(ctx, security=({self.scheme_name: []},))


@dataclass(frozen=True, slots=True)
class ApiKeyAuth(SurfaceCapability):
    """API key security scheme.

    Usage:
        ApiKeyAuth.header("X-API-Key")
        ApiKeyAuth.query("api_key")
    """

    model: FAAPIKey
    scheme_name: str = "apiKeyAuth"

    @classmethod
    def header(cls, name: str = "X-API-Key", description: str | None = None) -> ApiKeyAuth:
        """Create API key in header."""
        models = _get_fastapi_models()
        apikey_cls = models["APIKey"]
        # Use **{} to pass 'in' as keyword (reserved word in Python)
        return cls(
            model=apikey_cls(**{"in": "header", "name": name, "description": description}),
        )

    @classmethod
    def query(cls, name: str = "api_key", description: str | None = None) -> ApiKeyAuth:
        """Create API key in query parameter."""
        models = _get_fastapi_models()
        apikey_cls = models["APIKey"]
        return cls(
            model=apikey_cls(**{"in": "query", "name": name, "description": description}),
        )

    def compile_fastapi_route(self, ctx: FastAPIRouteContext) -> FastAPIRouteContext:
        """Add API key security requirement."""
        return fastapi_route(ctx, security=({self.scheme_name: []},))


@dataclass(frozen=True, slots=True)
class OAuth2Auth(SurfaceCapability):
    """OAuth2 security scheme.

    Usage:
        OAuth2Auth.authorization_code(
            authorization_url="https://example.com/oauth/authorize",
            token_url="https://example.com/oauth/token",
            scopes={"read": "Read access", "write": "Write access"},
        )
    """

    model: FAOAuth2
    scheme_name: str = "oauth2"
    required_scopes: tuple[str, ...] = ()

    @classmethod
    def authorization_code(
        cls,
        authorization_url: str,
        token_url: str,
        scopes: dict[str, str],
        refresh_url: str | None = None,
        description: str | None = None,
        required_scopes: tuple[str, ...] = (),
    ) -> OAuth2Auth:
        """Create OAuth2 authorization code flow."""
        models = _get_fastapi_models()
        flow_cls = models["OAuthFlowAuthorizationCode"]
        flows_cls = models["OAuthFlows"]
        oauth2_cls = models["OAuth2"]

        flow = flow_cls(
            authorizationUrl=authorization_url,
            tokenUrl=token_url,
            refreshUrl=refresh_url,
            scopes=scopes,
        )
        return cls(
            model=oauth2_cls(
                flows=flows_cls(authorizationCode=flow),
                description=description,
            ),
            required_scopes=required_scopes,
        )

    @classmethod
    def client_credentials(
        cls,
        token_url: str,
        scopes: dict[str, str],
        refresh_url: str | None = None,
        description: str | None = None,
        required_scopes: tuple[str, ...] = (),
    ) -> OAuth2Auth:
        """Create OAuth2 client credentials flow."""
        models = _get_fastapi_models()
        flow_cls = models["OAuthFlowClientCredentials"]
        flows_cls = models["OAuthFlows"]
        oauth2_cls = models["OAuth2"]

        flow = flow_cls(
            tokenUrl=token_url,
            refreshUrl=refresh_url,
            scopes=scopes,
        )
        return cls(
            model=oauth2_cls(
                flows=flows_cls(clientCredentials=flow),
                description=description,
            ),
            required_scopes=required_scopes,
        )

    @classmethod
    def password(
        cls,
        token_url: str,
        scopes: dict[str, str],
        refresh_url: str | None = None,
        description: str | None = None,
        required_scopes: tuple[str, ...] = (),
    ) -> OAuth2Auth:
        """Create OAuth2 password flow."""
        models = _get_fastapi_models()
        flow_cls = models["OAuthFlowPassword"]
        flows_cls = models["OAuthFlows"]
        oauth2_cls = models["OAuth2"]

        flow = flow_cls(
            tokenUrl=token_url,
            refreshUrl=refresh_url,
            scopes=scopes,
        )
        return cls(
            model=oauth2_cls(
                flows=flows_cls(password=flow),
                description=description,
            ),
            required_scopes=required_scopes,
        )

    def compile_fastapi_route(self, ctx: FastAPIRouteContext) -> FastAPIRouteContext:
        """Add OAuth2 security requirement."""
        return fastapi_route(ctx, security=({self.scheme_name: list(self.required_scopes)},))


# ═══════════════════════════════════════════════════════════════════════════════
# Operation Metadata
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Summary(SurfaceCapability):
    """OpenAPI operation summary and description.

    Usage:
        Summary.of("Login user")
        Summary.of("Login user", "Authenticates user and returns JWT token")
    """

    text: str
    description: str | None = None

    @classmethod
    def of(cls, text: str, description: str | None = None) -> Summary:
        """Create summary with optional description."""
        return cls(text=text, description=description)

    def compile_fastapi_route(self, ctx: FastAPIRouteContext) -> FastAPIRouteContext:
        """Add summary and description to route."""
        return fastapi_route(ctx, summary=self.text, description=self.description)


@dataclass(frozen=True, slots=True)
class OperationId(SurfaceCapability):
    """Explicit OpenAPI operationId.

    Usage:
        OperationId.of("loginUser")
    """

    value: str

    @classmethod
    def of(cls, value: str) -> OperationId:
        """Create operation ID."""
        return cls(value=value)

    def compile_fastapi_route(self, ctx: FastAPIRouteContext) -> FastAPIRouteContext:
        """Set operation ID."""
        return fastapi_route(ctx, operation_id=self.value)


@dataclass(frozen=True, slots=True)
class Deprecated(SurfaceCapability):
    """Mark endpoint as deprecated.

    Usage:
        Deprecated.because("Use /v2/login instead")
        Deprecated.until("2025-01-01", "Migrating to v2 API")
    """

    reason: str
    sunset_date: str | None = None  # ISO 8601 date

    @classmethod
    def because(cls, reason: str) -> Deprecated:
        """Mark as deprecated with reason."""
        return cls(reason=reason)

    @classmethod
    def until(cls, sunset_date: str, reason: str) -> Deprecated:
        """Mark as deprecated with sunset date."""
        return cls(reason=reason, sunset_date=sunset_date)

    def compile_fastapi_route(self, ctx: FastAPIRouteContext) -> FastAPIRouteContext:
        """Mark route as deprecated."""
        return fastapi_route(ctx, deprecated=True)


# ═══════════════════════════════════════════════════════════════════════════════
# Route Configuration
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class ResponseStatus(SurfaceCapability):
    """Default HTTP response status code.

    Usage:
        http.ResponseStatus(201)   # 201 Created
        http.ResponseStatus(204)   # 204 No Content
    """

    code: int

    def compile_fastapi_route(self, ctx: FastAPIRouteContext) -> FastAPIRouteContext:
        """Set response status code."""
        return fastapi_route(ctx, status_code=self.code)


@dataclass(frozen=True, slots=True)
class ResponseHeader(SurfaceCapability):
    """Document a response header in OpenAPI schema.

    Usage:
        http.ResponseHeader("X-Request-Id", "Unique request identifier")
        http.ResponseHeader("X-Rate-Limit-Remaining", "Remaining requests", schema_type="integer")
    """

    name: str
    description: str = ""
    schema_type: str = "string"

    def compile_fastapi_route(self, ctx: FastAPIRouteContext) -> FastAPIRouteContext:
        """Add response header to OpenAPI spec."""
        header_spec: dict[str, Any] = {
            "description": self.description,
            "schema": {"type": self.schema_type},
        }
        responses: dict[str, Any] = {"200": {"headers": {self.name: header_spec}}}
        return fastapi_route(ctx, openapi_extra={"responses": responses})


@dataclass(frozen=True, slots=True)
class ContentType(SurfaceCapability):
    """Response content type override.

    Usage:
        http.ContentType("text/plain")
        http.ContentType("text/csv")
    """

    media_type: str

    def compile_fastapi_route(self, ctx: FastAPIRouteContext) -> FastAPIRouteContext:
        """Set response content type in OpenAPI spec."""
        responses: dict[str, Any] = {
            "200": {"content": {self.media_type: {"schema": {"type": "string"}}}},
        }
        return fastapi_route(ctx, openapi_extra={"responses": responses})


# ═══════════════════════════════════════════════════════════════════════════════
# Application-Level Middleware
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class CORS(SurfaceCapability):
    """CORS middleware configuration.

    Usage:
        http.CORS(origins=("http://localhost:3000", "https://example.com"))
        http.CORS(origins=("*",), allow_methods=("GET", "POST"))
    """

    origins: tuple[str, ...] = ("*",)
    allow_methods: tuple[str, ...] = ("*",)
    allow_headers: tuple[str, ...] = ("*",)
    allow_credentials: bool = False
    max_age: int = 600

    def compile_fastapi_app(self, ctx: FastAPIAppContext) -> FastAPIAppContext:
        """Add CORS middleware."""
        from starlette.middleware.cors import CORSMiddleware
        return fastapi_app_middleware(
            ctx,
            CORSMiddleware,
            allow_origins=list(self.origins),
            allow_methods=list(self.allow_methods),
            allow_headers=list(self.allow_headers),
            allow_credentials=self.allow_credentials,
            max_age=self.max_age,
        )


@dataclass(frozen=True, slots=True)
class TrustedHost(SurfaceCapability):
    """Trusted host middleware — reject requests from unknown hosts.

    Usage:
        http.TrustedHost(hosts=("example.com", "*.example.com"))
    """

    hosts: tuple[str, ...]

    def compile_fastapi_app(self, ctx: FastAPIAppContext) -> FastAPIAppContext:
        """Add TrustedHost middleware."""
        from starlette.middleware.trustedhost import TrustedHostMiddleware
        return fastapi_app_middleware(
            ctx,
            TrustedHostMiddleware,
            allowed_hosts=list(self.hosts),
        )


@dataclass(frozen=True, slots=True)
class GZip(SurfaceCapability):
    """GZip compression middleware.

    Usage:
        http.GZip()              # default 500 bytes minimum
        http.GZip(minimum_size=1000)
    """

    minimum_size: int = 500

    def compile_fastapi_app(self, ctx: FastAPIAppContext) -> FastAPIAppContext:
        """Add GZip middleware."""
        from starlette.middleware.gzip import GZipMiddleware
        return fastapi_app_middleware(
            ctx,
            GZipMiddleware,
            minimum_size=self.minimum_size,
        )


__all__ = (
    # Tags
    "Tag",
    # Security
    "BearerAuth",
    "ApiKeyAuth",
    "OAuth2Auth",
    # Operation meta
    "Summary",
    "OperationId",
    "Deprecated",
    # Route configuration
    "ResponseStatus",
    "ResponseHeader",
    "ContentType",
    # Application-level middleware
    "CORS",
    "TrustedHost",
    "GZip",
)

"""OpenAPI capabilities — compile to FastAPI route configuration.

These capabilities use the compile_fastapi() pattern for consistency
with the schema axis capabilities.

    from emergent.wire.axis.surface import capabilities as C

    endpoint(runner).expose(
        trigger, codec,
        C.Tag.of("users"),
        C.Summary.of("List all users"),
        C.BearerAuth.jwt(),
    )
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from emergent.wire.axis._capability import (
    FastAPIRouteContext,
    fastapi_route,
)
from ._base import SurfaceCapability

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
            "OpenAPI capabilities require fastapi. "
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

    def compile_fastapi(self, ctx: FastAPIRouteContext) -> FastAPIRouteContext:
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

    def compile_fastapi(self, ctx: FastAPIRouteContext) -> FastAPIRouteContext:
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

    def compile_fastapi(self, ctx: FastAPIRouteContext) -> FastAPIRouteContext:
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

    def compile_fastapi(self, ctx: FastAPIRouteContext) -> FastAPIRouteContext:
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

    def compile_fastapi(self, ctx: FastAPIRouteContext) -> FastAPIRouteContext:
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

    def compile_fastapi(self, ctx: FastAPIRouteContext) -> FastAPIRouteContext:
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

    def compile_fastapi(self, ctx: FastAPIRouteContext) -> FastAPIRouteContext:
        """Mark route as deprecated."""
        return fastapi_route(ctx, deprecated=True)


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
)

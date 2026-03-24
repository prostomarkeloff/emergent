"""Tests for surface/dialects/http.py — Tag, BearerAuth, ApiKeyAuth, OAuth2Auth, Summary, etc."""

from __future__ import annotations

from emergent.wire.axis.surface.dialects.http import (
    Tag,
    BearerAuth,
    ApiKeyAuth,
    OAuth2Auth,
    Summary,
    OperationId,
    Deprecated,
    ResponseStatus,
    ResponseHeader,
    ContentType,
    CORS,
    TrustedHost,
    GZip,
)
from emergent.wire.axis._capability import (
    FastAPIRouteContext,
    FastAPIAppContext,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Tag
# ═══════════════════════════════════════════════════════════════════════════════


class TestTag:
    def test_of_creates_tag(self) -> None:
        tag = Tag.of("users")
        assert tag.model.name == "users"

    def test_of_with_description(self) -> None:
        tag = Tag.of("users", "User endpoints")
        assert tag.model.name == "users"

    def test_compile_fastapi_route(self) -> None:
        tag = Tag.of("auth")
        ctx = FastAPIRouteContext(path="/test", method="GET")
        result = tag.compile_fastapi_route(ctx)
        assert "auth" in result.tags


# ═══════════════════════════════════════════════════════════════════════════════
# BearerAuth
# ═══════════════════════════════════════════════════════════════════════════════


class TestBearerAuth:
    def test_jwt_creates_bearer(self) -> None:
        auth = BearerAuth.jwt()
        assert auth.scheme_name == "bearerAuth"

    def test_jwt_with_description(self) -> None:
        auth = BearerAuth.jwt("JWT description")
        assert auth.model is not None

    def test_opaque_creates_bearer(self) -> None:
        auth = BearerAuth.opaque()
        assert auth.scheme_name == "bearerAuth"

    def test_compile_fastapi_route(self) -> None:
        auth = BearerAuth.jwt()
        ctx = FastAPIRouteContext(path="/test", method="GET")
        result = auth.compile_fastapi_route(ctx)
        assert len(result.security) > 0
        assert "bearerAuth" in result.security[0]


# ═══════════════════════════════════════════════════════════════════════════════
# ApiKeyAuth
# ═══════════════════════════════════════════════════════════════════════════════


class TestApiKeyAuth:
    def test_header_creates_apikey(self) -> None:
        auth = ApiKeyAuth.header("X-API-Key")
        assert auth.scheme_name == "apiKeyAuth"

    def test_header_with_description(self) -> None:
        auth = ApiKeyAuth.header("X-Token", "API token header")
        assert auth.model is not None

    def test_query_creates_apikey(self) -> None:
        auth = ApiKeyAuth.query("key")
        assert auth.scheme_name == "apiKeyAuth"

    def test_compile_fastapi_route(self) -> None:
        auth = ApiKeyAuth.header()
        ctx = FastAPIRouteContext(path="/test", method="GET")
        result = auth.compile_fastapi_route(ctx)
        assert len(result.security) > 0


# ═══════════════════════════════════════════════════════════════════════════════
# OAuth2Auth
# ═══════════════════════════════════════════════════════════════════════════════


class TestOAuth2Auth:
    def test_authorization_code(self) -> None:
        auth = OAuth2Auth.authorization_code(
            authorization_url="https://example.com/auth",
            token_url="https://example.com/token",
            scopes={"read": "Read access"},
        )
        assert auth.scheme_name == "oauth2"

    def test_client_credentials(self) -> None:
        auth = OAuth2Auth.client_credentials(
            token_url="https://example.com/token",
            scopes={"admin": "Admin access"},
        )
        assert auth.scheme_name == "oauth2"

    def test_password(self) -> None:
        auth = OAuth2Auth.password(
            token_url="https://example.com/token",
            scopes={"read": "Read"},
        )
        assert auth.scheme_name == "oauth2"

    def test_with_required_scopes(self) -> None:
        auth = OAuth2Auth.authorization_code(
            authorization_url="https://example.com/auth",
            token_url="https://example.com/token",
            scopes={"read": "Read", "write": "Write"},
            required_scopes=("read", "write"),
        )
        assert auth.required_scopes == ("read", "write")

    def test_compile_fastapi_route(self) -> None:
        auth = OAuth2Auth.authorization_code(
            authorization_url="https://example.com/auth",
            token_url="https://example.com/token",
            scopes={"read": "Read"},
            required_scopes=("read",),
        )
        ctx = FastAPIRouteContext(path="/test", method="GET")
        result = auth.compile_fastapi_route(ctx)
        assert len(result.security) > 0
        assert "oauth2" in result.security[0]
        assert result.security[0]["oauth2"] == ["read"]


# ═══════════════════════════════════════════════════════════════════════════════
# Summary
# ═══════════════════════════════════════════════════════════════════════════════


class TestSummary:
    def test_of_creates_summary(self) -> None:
        s = Summary.of("Login user")
        assert s.text == "Login user"
        assert s.description is None

    def test_of_with_description(self) -> None:
        s = Summary.of("Login", "Full description")
        assert s.description == "Full description"

    def test_compile_fastapi_route(self) -> None:
        s = Summary.of("Login", "Logs in user")
        ctx = FastAPIRouteContext(path="/test", method="GET")
        result = s.compile_fastapi_route(ctx)
        assert result.summary == "Login"
        assert result.description == "Logs in user"


# ═══════════════════════════════════════════════════════════════════════════════
# OperationId
# ═══════════════════════════════════════════════════════════════════════════════


class TestOperationId:
    def test_of_creates_operation_id(self) -> None:
        op = OperationId.of("loginUser")
        assert op.value == "loginUser"

    def test_compile_fastapi_route(self) -> None:
        op = OperationId.of("loginUser")
        ctx = FastAPIRouteContext(path="/test", method="GET")
        result = op.compile_fastapi_route(ctx)
        assert result.operation_id == "loginUser"


# ═══════════════════════════════════════════════════════════════════════════════
# Deprecated
# ═══════════════════════════════════════════════════════════════════════════════


class TestDeprecated:
    def test_because(self) -> None:
        d = Deprecated.because("Use v2")
        assert d.reason == "Use v2"
        assert d.sunset_date is None

    def test_until(self) -> None:
        d = Deprecated.until("2025-12-31", "Migrating")
        assert d.reason == "Migrating"
        assert d.sunset_date == "2025-12-31"

    def test_compile_fastapi_route(self) -> None:
        d = Deprecated.because("old")
        ctx = FastAPIRouteContext(path="/test", method="GET")
        result = d.compile_fastapi_route(ctx)
        assert result.deprecated is True


# ═══════════════════════════════════════════════════════════════════════════════
# ResponseStatus
# ═══════════════════════════════════════════════════════════════════════════════


class TestResponseStatus:
    def test_compile_fastapi_route(self) -> None:
        rs = ResponseStatus(code=201)
        ctx = FastAPIRouteContext(path="/test", method="GET")
        result = rs.compile_fastapi_route(ctx)
        assert result.status_code == 201


# ═══════════════════════════════════════════════════════════════════════════════
# ResponseHeader
# ═══════════════════════════════════════════════════════════════════════════════


class TestResponseHeader:
    def test_compile_fastapi_route(self) -> None:
        rh = ResponseHeader(name="X-Request-Id", description="Unique ID")
        ctx = FastAPIRouteContext(path="/test", method="GET")
        result = rh.compile_fastapi_route(ctx)
        assert result.openapi_extra is not None
        assert "responses" in result.openapi_extra


# ═══════════════════════════════════════════════════════════════════════════════
# ContentType
# ═══════════════════════════════════════════════════════════════════════════════


class TestContentType:
    def test_compile_fastapi_route(self) -> None:
        ct = ContentType(media_type="text/csv")
        ctx = FastAPIRouteContext(path="/test", method="GET")
        result = ct.compile_fastapi_route(ctx)
        assert result.openapi_extra is not None
        assert "responses" in result.openapi_extra


# ═══════════════════════════════════════════════════════════════════════════════
# CORS / TrustedHost / GZip (app-level)
# ═══════════════════════════════════════════════════════════════════════════════


class TestCORS:
    def test_compile_fastapi_app(self) -> None:
        cors = CORS(origins=("http://localhost:3000",))
        ctx = FastAPIAppContext()
        result = cors.compile_fastapi_app(ctx)
        assert len(result.middleware) == 1


class TestTrustedHost:
    def test_compile_fastapi_app(self) -> None:
        th = TrustedHost(hosts=("example.com",))
        ctx = FastAPIAppContext()
        result = th.compile_fastapi_app(ctx)
        assert len(result.middleware) == 1


class TestGZip:
    def test_compile_fastapi_app(self) -> None:
        gz = GZip(minimum_size=1000)
        ctx = FastAPIAppContext()
        result = gz.compile_fastapi_app(ctx)
        assert len(result.middleware) == 1

"""Auth exceptions — transport-agnostic error signaling.

AuthenticationRequired = no valid credentials (401 equivalent)
AuthorizationFailed = valid identity, insufficient permissions (403 equivalent)

Plain Python exceptions, NOT fastapi.HTTPException. Each compilation
target catches them its own way. The library provides a FastAPI
exception handler registrar as convenience.

    from authlib.errors import AuthenticationRequired, AuthorizationFailed

    raise AuthenticationRequired()           # no credentials
    raise AuthorizationFailed("admin only")  # wrong permissions
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import fastapi


# ═══════════════════════════════════════════════════════════════════════════════
# Domain Exceptions
# ═══════════════════════════════════════════════════════════════════════════════


class AuthenticationRequired(Exception):
    """No valid credentials. Transport-agnostic."""

    def __init__(self, detail: str = "authentication required"):
        self.detail = detail
        super().__init__(detail)


class AuthorizationFailed(Exception):
    """Valid identity but insufficient permissions."""

    def __init__(self, detail: str = "forbidden"):
        self.detail = detail
        super().__init__(detail)


# ═══════════════════════════════════════════════════════════════════════════════
# FastAPI Exception Handler Registration
# ═══════════════════════════════════════════════════════════════════════════════


def register_auth_errors(fastapi_app: fastapi.FastAPI) -> None:
    """Register RFC 7807 exception handlers on a FastAPI app. Call once after compile.

        fastapi_app = targets.fastapi.compile(app)
        register_auth_errors(fastapi_app)
    """
    from starlette.requests import Request
    from starlette.responses import JSONResponse

    _MEDIA = "application/problem+json"

    async def _handle_401(request: Request, exc: Exception) -> JSONResponse:
        assert isinstance(exc, AuthenticationRequired)
        return JSONResponse(
            status_code=401,
            content={
                "type": "about:blank",
                "title": "Unauthorized",
                "status": 401,
                "detail": exc.detail,
            },
            media_type=_MEDIA,
        )

    async def _handle_403(request: Request, exc: Exception) -> JSONResponse:
        assert isinstance(exc, AuthorizationFailed)
        return JSONResponse(
            status_code=403,
            content={
                "type": "about:blank",
                "title": "Forbidden",
                "status": 403,
                "detail": exc.detail,
            },
            media_type=_MEDIA,
        )

    fastapi_app.add_exception_handler(AuthenticationRequired, _handle_401)
    fastapi_app.add_exception_handler(AuthorizationFailed, _handle_403)


__all__ = (
    # Domain exceptions
    "AuthenticationRequired",
    "AuthorizationFailed",
    # FastAPI helpers
    "register_auth_errors",
)

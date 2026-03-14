"""Auth exceptions — transport-agnostic error signaling.

AuthenticationRequired = no valid credentials (401 equivalent)
AuthorizationFailed = valid identity, insufficient permissions (403 equivalent)

    from emergent.wire.derive.auth.errors import AuthenticationRequired, AuthorizationFailed

    raise AuthenticationRequired()
    raise AuthorizationFailed("admin only")
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI


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


def register_auth_errors(fastapi_app: FastAPI) -> None:
    """Register RFC 7807 exception handlers on a FastAPI app."""
    from starlette.requests import Request as _Req
    from starlette.responses import JSONResponse as _JsonResp

    _MEDIA = "application/problem+json"

    async def _handle_401(request: _Req, exc: Exception) -> _JsonResp:
        if not isinstance(exc, AuthenticationRequired):
            return _JsonResp(
                status_code=500,
                content={"type": "about:blank", "title": "Internal Server Error", "status": 500},
                media_type=_MEDIA,
            )
        return _JsonResp(
            status_code=401,
            content={
                "type": "about:blank",
                "title": "Unauthorized",
                "status": 401,
                "detail": exc.detail,
            },
            media_type=_MEDIA,
            headers={"WWW-Authenticate": "Bearer"},
        )

    async def _handle_403(request: _Req, exc: Exception) -> _JsonResp:
        if not isinstance(exc, AuthorizationFailed):
            return _JsonResp(
                status_code=500,
                content={"type": "about:blank", "title": "Internal Server Error", "status": 500},
                media_type=_MEDIA,
            )
        return _JsonResp(
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
    "AuthenticationRequired",
    "AuthorizationFailed",
    "register_auth_errors",
)

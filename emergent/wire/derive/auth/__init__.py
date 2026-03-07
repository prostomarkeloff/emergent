"""Auth capabilities for wire.derive.

    from emergent.wire.derive.auth import (
        # Errors
        AuthenticationRequired, AuthorizationFailed, register_auth_errors,
        # Extractors
        AuthToken, BearerExtract, CLITokenExtract,
        # Validation
        TokenValidate,
        # OpenAPI
        AuthOpenAPI,
        # Capabilities
        Authenticated, RoleRequired, AuthorizeOps, OwnerScoped, OwnerContext,
        # Login
        LoginOp, IssueToken, token_converter,
    )
"""

from .caps import (
    Authenticated,
    AuthorizeOps,
    OwnerContext,
    OwnerScoped,
    RequireRole,
    RoleRequired,
)
from .errors import AuthenticationRequired, AuthorizationFailed, register_auth_errors
from .extractors import AuthToken, BearerExtract, CLITokenExtract
from .login import IssueToken, LoginOp, token_converter
from .openapi import AuthOpenAPI
from .validate import TokenValidate

__all__ = (
    # Errors
    "AuthenticationRequired",
    "AuthorizationFailed",
    "register_auth_errors",
    # Extractors
    "AuthToken",
    "BearerExtract",
    "CLITokenExtract",
    # Validation
    "TokenValidate",
    # OpenAPI
    "AuthOpenAPI",
    # Capabilities
    "Authenticated",
    "RequireRole",
    "RoleRequired",
    "AuthorizeOps",
    "OwnerContext",
    "OwnerScoped",
    # Login
    "LoginOp",
    "IssueToken",
    "token_converter",
)

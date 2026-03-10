"""authlib — proxy to emergent.wire.derive.auth.

DEPRECATED: Use emergent.wire.derive.auth directly.
derivelib will be removed in emergent 1.0.0.

    from emergent.wire.derive.auth import (
        Authenticated, RoleRequired, AuthorizeOps, OwnerScoped,
        AuthenticationRequired, AuthorizationFailed,
        AuthToken, BearerExtract, CLITokenExtract,
        TokenValidate, AuthOpenAPI,
        IssueToken, LoginOp, token_converter,
    )
"""

from emergent.wire.derive.auth.errors import (
    AuthenticationRequired,
    AuthorizationFailed,
    register_auth_errors,
)
from emergent.wire.derive.auth.extractors import AuthToken, BearerExtract, CLITokenExtract
from emergent.wire.derive.auth.openapi import AuthOpenAPI
from emergent.wire.derive.auth.validate import TokenValidate
from emergent.wire.derive.auth.caps import (
    Authenticated,
    AuthorizeOps,
    OwnerContext,
    OwnerScoped,
    RequireRole,
    RoleRequired,
)
from emergent.wire.derive.auth.login import IssueToken, LoginOp, token_converter

from .transform import require_auth
from .rbac import require_role, authorize_ops
from .owner import owner_scoped

# auth_login is removed — use LoginOp capability directly
_AUTH_LOGIN_MSG = (
    "derivelib.authlib.auth_login has been removed. "
    "Use emergent.wire.derive.auth.LoginOp capability directly. "
    "derivelib will be removed in emergent 1.0.0."
)


def auth_login(*args: object, **kwargs: object) -> object:
    raise ImportError(_AUTH_LOGIN_MSG)


__all__ = (
    # Errors
    "AuthenticationRequired",
    "AuthorizationFailed",
    "register_auth_errors",
    # Extractors
    "AuthToken",
    "BearerExtract",
    "CLITokenExtract",
    # OpenAPI
    "AuthOpenAPI",
    # Validation
    "TokenValidate",
    # Capabilities (new names)
    "Authenticated",
    "RequireRole",
    "RoleRequired",
    "AuthorizeOps",
    "OwnerContext",
    "OwnerScoped",
    # Login
    "IssueToken",
    "LoginOp",
    "token_converter",
    # Compat functions (return capabilities)
    "require_auth",
    "require_role",
    "authorize_ops",
    "owner_scoped",
    # Removed
    "auth_login",
)

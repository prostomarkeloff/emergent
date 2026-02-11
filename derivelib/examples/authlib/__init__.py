"""authlib — generic auth library for derivelib.

Transport-agnostic credential extraction + validation.
Generic identity type (NOT hardcoded).
Pre-built DerivationT transform + login dialect.

    from examples.authlib import (
        # Errors
        AuthenticationRequired, AuthorizationFailed, register_auth_errors,
        # Extractors
        AuthToken, BearerExtract, CLITokenExtract,
        # Validation
        TokenValidate,
        # OpenAPI
        AuthOpenAPI,
        # Transform
        require_auth,
        # Login dialect
        IssueToken, auth_login, token_converter,
    )
"""

from .errors import AuthenticationRequired, AuthorizationFailed, register_auth_errors
from .extractors import AuthToken, BearerExtract, CLITokenExtract
from .openapi import AuthOpenAPI
from .validate import TokenValidate
from .transform import require_auth
from .login import IssueToken, auth_login, token_converter

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
    # Transform
    "require_auth",
    # Login dialect
    "IssueToken",
    "auth_login",
    "token_converter",
)

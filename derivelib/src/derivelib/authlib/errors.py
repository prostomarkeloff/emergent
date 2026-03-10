"""Auth errors — re-export from emergent.wire.derive.auth.errors.

DEPRECATED: Use emergent.wire.derive.auth directly.
derivelib will be removed in emergent 1.0.0.
"""

from emergent.wire.derive.auth.errors import (
    AuthenticationRequired,
    AuthorizationFailed,
    register_auth_errors,
)

__all__ = (
    "AuthenticationRequired",
    "AuthorizationFailed",
    "register_auth_errors",
)

"""Login — re-export from emergent.wire.derive.auth.login.

DEPRECATED: Use emergent.wire.derive.auth directly.
derivelib will be removed in emergent 1.0.0.
"""

from emergent.wire.derive.auth.login import (
    IssueToken,
    LoginOp,
    token_converter,
)

__all__ = (
    "IssueToken",
    "LoginOp",
    "token_converter",
)

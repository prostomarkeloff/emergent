"""Credential extractors — re-export from emergent.wire.derive.auth.extractors.

DEPRECATED: Use emergent.wire.derive.auth directly.
derivelib will be removed in emergent 1.0.0.
"""

from emergent.wire.derive.auth.extractors import (
    AuthToken,
    BearerExtract,
    CLITokenExtract,
)

__all__ = (
    "AuthToken",
    "BearerExtract",
    "CLITokenExtract",
)

"""
Contrib — optional integrations for idempotency module.

    from emergent.idempotency.contrib import sqlalchemy

Follows the same pattern as wire.contrib — each integration is a submodule
with try/except import for optional dependencies.
"""

from . import sqlalchemy

__all__ = ("sqlalchemy",)

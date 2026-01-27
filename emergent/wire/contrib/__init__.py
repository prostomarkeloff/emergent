"""
Contrib — optional integrations. Access integrations via submodules.

    from emergent.wire.contrib import fastapi
    # app = fastapi.from_application(Application())
"""

from . import fastapi

# Expose submodules (e.g., fastapi)
__all__ = ("fastapi",)

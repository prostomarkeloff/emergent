"""
FastAPI integration for emergent.wire (optional dependency).

    from emergent.wire.contrib import fastapi
    # fapp = fastapi.from_application(app)
"""

try:
    from ._fastapi import (
        add_endpoint_to_app,
        from_application,
        compile_to_fastapi_route,
    )
except Exception:  # pragma: no cover - FastAPI not installed
    # Keep module importable even if fastapi isn't installed
    pass

__all__ = (
    "add_endpoint_to_app",
    "from_application",
    "compile_to_fastapi_route",
)

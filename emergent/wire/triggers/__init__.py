"""
Triggers — describe how endpoints are exposed (e.g., HTTP routes).

    from emergent.wire.triggers.http import HTTPRouteTrigger

    http = HTTPRouteTrigger("GET", "/users/{id}")
"""

from emergent.wire.triggers import http


__all__ = ("http",)

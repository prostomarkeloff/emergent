# pyright: reportPrivateUsage=false
"""Schemathesis fuzzing — auto-generate API requests from OpenAPI schema.

Marked @slow — skipped in light mode, runs in medium+tough.
"""

from __future__ import annotations

from typing import Any

import pytest
import schemathesis
import schemathesis.openapi
from hypothesis import settings, HealthCheck

from tests.fuzz.app import app, readonly_app, minimal_app

pytestmark = pytest.mark.slow

crud_schema = schemathesis.openapi.from_asgi("/openapi.json", app=app)


@crud_schema.parametrize()
@settings(max_examples=30, suppress_health_check=[HealthCheck.too_slow], deadline=None)
def test_crud_app_no_crash(case: Any) -> None:
    """Full CRUD app: no endpoint crashes on any valid-shaped input."""
    case.call_and_validate()


readonly_schema = schemathesis.openapi.from_asgi("/openapi.json", app=readonly_app)


@readonly_schema.parametrize()
@settings(max_examples=20, suppress_health_check=[HealthCheck.too_slow], deadline=None)
def test_readonly_app_no_crash(case: Any) -> None:
    """Readonly app: only GET endpoints, all must work."""
    case.call_and_validate()


minimal_schema = schemathesis.openapi.from_asgi("/openapi.json", app=minimal_app)


@minimal_schema.parametrize()
@settings(max_examples=30, suppress_health_check=[HealthCheck.too_slow], deadline=None)
def test_minimal_app_no_crash(case: Any) -> None:
    """Minimal entity app: simplest CRUD, must work cleanly."""
    case.call_and_validate()

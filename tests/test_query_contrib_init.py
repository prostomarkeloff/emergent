"""Tests for query contrib sqlalchemy.py and http.py re-export modules.

Covers:
- sqlalchemy.py: successful import path, __all__ contents
- http.py: successful import path, __all__ contents
"""

from __future__ import annotations

import pytest


# ─── query contrib sqlalchemy.py ─────────────────────────────────────────────


def test_query_sqlalchemy_imports_work():
    """When sqlalchemy is installed, query contrib exports work."""
    from emergent.wire.axis.query.contrib import sqlalchemy as sa_query

    assert hasattr(sa_query, "SQLAlchemyRelationalProvider")
    assert hasattr(sa_query, "SQLAlchemyRelationalStore")
    assert hasattr(sa_query, "AutoIncrementNextId")
    assert hasattr(sa_query, "SASequenceNextId")
    assert hasattr(sa_query, "provider")
    assert hasattr(sa_query, "store")


def test_query_sqlalchemy_all_contents():
    """query contrib sqlalchemy __all__ contains expected names."""
    from emergent.wire.axis.query.contrib import sqlalchemy as sa_query

    expected = (
        "SQLAlchemyRelationalProvider",
        "SQLAlchemyRelationalStore",
        "AutoIncrementNextId",
        "SASequenceNextId",
        "provider",
        "store",
    )
    for name in expected:
        assert name in sa_query.__all__, f"Missing {name} in __all__"


def test_query_sqlalchemy_provider_callable():
    """provider and store factory functions are callable."""
    from emergent.wire.axis.query.contrib import sqlalchemy as sa_query

    assert callable(sa_query.provider)
    assert callable(sa_query.store)


# ─── query contrib http.py ───────────────────────────────────────────────────


def test_query_http_imports_work():
    """When httpx is installed, query contrib http exports work."""
    try:
        from emergent.wire.axis.query.contrib import http
    except ImportError:
        pytest.skip("httpx not installed")

    assert hasattr(http, "HTTPAPIBuilder")
    assert hasattr(http, "api")
    assert hasattr(http, "page_size")
    assert hasattr(http, "offset_limit")
    assert hasattr(http, "cursor")
    assert hasattr(http, "bearer")
    assert hasattr(http, "api_key")
    assert hasattr(http, "basic")
    assert hasattr(http, "query_params")
    assert hasattr(http, "body_filters")
    assert hasattr(http, "HTTPAPIProvider")


def test_query_http_all_contents():
    """query contrib http __all__ contains expected names when httpx is available."""
    try:
        from emergent.wire.axis.query.contrib import http
    except ImportError:
        pytest.skip("httpx not installed")

    expected = (
        "HTTPAPIBuilder",
        "api",
        "PageSizePagination",
        "page_size",
        "OffsetLimitPagination",
        "offset_limit",
        "CursorPagination",
        "cursor",
        "BearerAuth",
        "bearer",
        "APIKeyAuth",
        "api_key",
        "BasicAuth",
        "basic",
        "QueryParamFilters",
        "query_params",
        "BodyFilters",
        "body_filters",
        "HTTPAPIProvider",
    )
    for name in expected:
        assert name in http.__all__, f"Missing {name} in __all__"


def test_query_http_api_callable():
    """api builder function is callable."""
    try:
        from emergent.wire.axis.query.contrib import http
    except ImportError:
        pytest.skip("httpx not installed")

    assert callable(http.api)


def test_query_http_pagination_callables():
    """Pagination factory functions are callable."""
    try:
        from emergent.wire.axis.query.contrib import http
    except ImportError:
        pytest.skip("httpx not installed")

    assert callable(http.page_size)
    assert callable(http.offset_limit)
    assert callable(http.cursor)


def test_query_http_auth_callables():
    """Auth factory functions are callable."""
    try:
        from emergent.wire.axis.query.contrib import http
    except ImportError:
        pytest.skip("httpx not installed")

    assert callable(http.bearer)
    assert callable(http.api_key)
    assert callable(http.basic)

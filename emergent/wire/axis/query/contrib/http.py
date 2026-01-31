"""HTTP API provider — REST-ish API client.

    from emergent.wire.axis.query.contrib import http

    # Build provider
    provider = (
        http.api(User, profile=InternalAPI)
        .base("https://api.example.com/users")
        .pagination(http.page_size())
        .auth(http.bearer(token))
        .build(httpx_client)
    )

    # Use
    users = api(User)
    result = await provider.fetch(users.list().filter(lambda u: u.active).page(1))

Requires: httpx
"""

try:
    from emergent.wire.axis.query.contrib._impls._http import (
        # Builder
        HTTPAPIBuilder as HTTPAPIBuilder,
        api as api,
        # Pagination strategies
        Pagination as Pagination,
        PageSizePagination as PageSizePagination,
        page_size as page_size,
        OffsetLimitPagination as OffsetLimitPagination,
        offset_limit as offset_limit,
        CursorPagination as CursorPagination,
        cursor as cursor,
        # Auth strategies
        Auth as Auth,
        BearerAuth as BearerAuth,
        bearer as bearer,
        APIKeyAuth as APIKeyAuth,
        api_key as api_key,
        BasicAuth as BasicAuth,
        basic as basic,
        # Filter encoding
        FilterEncoding as FilterEncoding,
        QueryParamFilters as QueryParamFilters,
        query_params as query_params,
        BodyFilters as BodyFilters,
        body_filters as body_filters,
        # Provider
        HTTPAPIProvider as HTTPAPIProvider,
    )

    __all__ = (
        # Builder
        "HTTPAPIBuilder",
        "api",
        # Pagination
        "Pagination",
        "PageSizePagination",
        "page_size",
        "OffsetLimitPagination",
        "offset_limit",
        "CursorPagination",
        "cursor",
        # Auth
        "Auth",
        "BearerAuth",
        "bearer",
        "APIKeyAuth",
        "api_key",
        "BasicAuth",
        "basic",
        # Filter encoding
        "FilterEncoding",
        "QueryParamFilters",
        "query_params",
        "BodyFilters",
        "body_filters",
        # Provider
        "HTTPAPIProvider",
    )

except ImportError as e:
    _msg = f"httpx is required for HTTP API provider: {e}"

    def _raise_import_error(*_args: object, **_kwargs: object) -> None:
        raise ImportError(_msg)

    # Stubs that raise on use
    api = _raise_import_error  # type: ignore[assignment]
    page_size = _raise_import_error  # type: ignore[assignment]
    offset_limit = _raise_import_error  # type: ignore[assignment]
    cursor = _raise_import_error  # type: ignore[assignment]
    bearer = _raise_import_error  # type: ignore[assignment]
    api_key = _raise_import_error  # type: ignore[assignment]
    basic = _raise_import_error  # type: ignore[assignment]
    query_params = _raise_import_error  # type: ignore[assignment]
    body_filters = _raise_import_error  # type: ignore[assignment]

    __all__ = ("api",)

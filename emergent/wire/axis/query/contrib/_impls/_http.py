"""HTTP API provider implementation.

Typed builder pattern for REST-ish API clients.
"""
# pyright: reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false
# pyright: reportUnknownMemberType=false

from __future__ import annotations

import dataclasses
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar
from urllib.parse import quote as _url_quote

import httpx

from collections.abc import Sequence as SequenceABC

from emergent.wire.axis.query._api import (
    APIQuerySet,
    ListOp,
    GetOp,
    CreateOp,
    UpdateOp,
    DeleteOp,
    PageMod,
    CursorMod,
    OffsetMod,
)
from emergent.wire.axis.query._contexts import HTTPAPIContext, HTTPAPICompilable
from emergent.wire.axis.query._proxy import OrderSpec
from emergent.wire.compile._core import fold
from emergent.wire.axis.query._expr import (
    Expr,
    Field,
    Const,
    Eq,
    Ne,
    Lt,
    Le,
    Gt,
    Ge,
    And,
    Or,
    In,
    Contains,
    StartsWith,
    EndsWith,
    IsNull,
    IsNotNull,
)


T = TypeVar("T")
K = TypeVar("K")  # Key type for APIQuerySet methods
P = TypeVar("P")  # Profile

type Params = dict[str, Any]
type Headers = dict[str, str]


# ─── Pagination Strategies ───────────────────────────────────────────────────


class Pagination(ABC):
    """Base for pagination strategies."""

    @abstractmethod
    def apply(self, params: Params, mod: PageMod | CursorMod | OffsetMod) -> None:
        """Apply pagination to request params."""
        ...


@dataclass(frozen=True, slots=True)
class PageSizePagination(Pagination):
    """Page/size pagination: ?page=1&per_page=20"""
    page_param: str = "page"
    size_param: str = "per_page"

    def apply(self, params: Params, mod: PageMod | CursorMod | OffsetMod) -> None:
        if isinstance(mod, PageMod):
            params[self.page_param] = mod.page
            params[self.size_param] = mod.per_page
        elif isinstance(mod, OffsetMod):
            # Convert offset to page
            page = (mod.offset // mod.limit) + 1
            params[self.page_param] = page
            params[self.size_param] = mod.limit


def page_size(page: str = "page", size: str = "per_page") -> PageSizePagination:
    """Page/size pagination strategy."""
    return PageSizePagination(page_param=page, size_param=size)


@dataclass(frozen=True, slots=True)
class OffsetLimitPagination(Pagination):
    """Offset/limit pagination: ?offset=0&limit=20"""
    offset_param: str = "offset"
    limit_param: str = "limit"

    def apply(self, params: Params, mod: PageMod | CursorMod | OffsetMod) -> None:
        if isinstance(mod, OffsetMod):
            params[self.offset_param] = mod.offset
            params[self.limit_param] = mod.limit
        elif isinstance(mod, PageMod):
            # Convert page to offset
            params[self.offset_param] = (mod.page - 1) * mod.per_page
            params[self.limit_param] = mod.per_page


def offset_limit(offset: str = "offset", limit: str = "limit") -> OffsetLimitPagination:
    """Offset/limit pagination strategy."""
    return OffsetLimitPagination(offset_param=offset, limit_param=limit)


@dataclass(frozen=True, slots=True)
class CursorPagination(Pagination):
    """Cursor pagination: ?cursor=abc&limit=20"""
    cursor_param: str = "cursor"
    limit_param: str = "limit"

    def apply(self, params: Params, mod: PageMod | CursorMod | OffsetMod) -> None:
        if isinstance(mod, CursorMod):
            if mod.cursor:
                params[self.cursor_param] = mod.cursor
            params[self.limit_param] = mod.limit


def cursor(cursor_param: str = "cursor", limit: str = "limit") -> CursorPagination:
    """Cursor pagination strategy."""
    return CursorPagination(cursor_param=cursor_param, limit_param=limit)


# ─── Auth Strategies ─────────────────────────────────────────────────────────


class Auth(ABC):
    """Base for auth strategies."""

    @abstractmethod
    def apply(self, headers: Headers) -> None:
        """Apply auth to request headers."""
        ...


@dataclass(frozen=True, slots=True)
class BearerAuth(Auth):
    """Bearer token auth: Authorization: Bearer <token>"""
    token: str

    def apply(self, headers: Headers) -> None:
        headers["Authorization"] = f"Bearer {self.token}"


def bearer(token: str) -> BearerAuth:
    """Bearer token auth."""
    return BearerAuth(token)


@dataclass(frozen=True, slots=True)
class APIKeyAuth(Auth):
    """API key auth: X-API-Key: <key> or ?api_key=<key>"""
    key: str
    header: str | None = "X-API-Key"
    param: str | None = None

    def apply(self, headers: Headers) -> None:
        if self.header:
            headers[self.header] = self.key


def api_key(key: str, header: str = "X-API-Key") -> APIKeyAuth:
    """API key auth via header."""
    return APIKeyAuth(key, header=header)


@dataclass(frozen=True, slots=True)
class BasicAuth(Auth):
    """Basic auth: Authorization: Basic <base64>"""
    username: str
    password: str

    def apply(self, headers: Headers) -> None:
        import base64
        credentials = base64.b64encode(f"{self.username}:{self.password}".encode()).decode()
        headers["Authorization"] = f"Basic {credentials}"


def basic(username: str, password: str) -> BasicAuth:
    """Basic auth."""
    return BasicAuth(username, password)


# ─── Filter Encoding ─────────────────────────────────────────────────────────


class FilterEncoding(ABC):
    """Base for filter encoding strategies."""

    @abstractmethod
    def encode(
        self,
        expr: Expr,
        entity: type,
        profile: type | None,
    ) -> Params:
        """Encode filter expression to request params/body."""
        ...


@dataclass(frozen=True, slots=True)
class QueryParamFilters(FilterEncoding):
    """Encode filters as query params: ?name=alice&balance__gt=100"""
    operator_sep: str = "__"  # field__op=value

    def encode(
        self,
        expr: Expr,
        entity: type,
        profile: type | None,
    ) -> Params:
        params: Params = {}
        self._encode_expr(expr, params)
        return params

    def _encode_expr(self, expr: Expr, params: Params) -> None:
        match expr:
            case Eq(Field(name), Const(value)):
                params[name] = value
            case Ne(Field(name), Const(value)):
                params[f"{name}{self.operator_sep}ne"] = value
            case Lt(Field(name), Const(value)):
                params[f"{name}{self.operator_sep}lt"] = value
            case Le(Field(name), Const(value)):
                params[f"{name}{self.operator_sep}lte"] = value
            case Gt(Field(name), Const(value)):
                params[f"{name}{self.operator_sep}gt"] = value
            case Ge(Field(name), Const(value)):
                params[f"{name}{self.operator_sep}gte"] = value
            case In(Field(name), values):
                params[f"{name}{self.operator_sep}in"] = ",".join(str(v) for v in values)
            case Contains(Field(name), substring):
                params[f"{name}{self.operator_sep}contains"] = substring
            case StartsWith(Field(name), prefix):
                params[f"{name}{self.operator_sep}startswith"] = prefix
            case EndsWith(Field(name), suffix):
                params[f"{name}{self.operator_sep}endswith"] = suffix
            case IsNull(Field(name)):
                params[f"{name}{self.operator_sep}isnull"] = "true"
            case IsNotNull(Field(name)):
                params[f"{name}{self.operator_sep}isnull"] = "false"
            case And(left, right):
                self._encode_expr(left, params)
                right_params: Params = {}
                self._encode_expr(right, right_params)
                for k, v in right_params.items():
                    if k in params:
                        raise ValueError(f"Duplicate filter key {k!r} in AND expression; query param encoding cannot represent this")
                    params[k] = v
            case Or(_, _):
                raise ValueError("OR filters not supported in query params encoding")
            case _:
                raise ValueError(f"Unsupported filter expression: {expr}")


def query_params(operator_sep: str = "__") -> QueryParamFilters:
    """Query param filter encoding: ?field__op=value"""
    return QueryParamFilters(operator_sep=operator_sep)


@dataclass(frozen=True, slots=True)
class BodyFilters(FilterEncoding):
    """Encode filters in request body (for POST search endpoints)."""

    def encode(
        self,
        expr: Expr,
        entity: type,
        profile: type | None,
    ) -> Params:
        return {"filter": self._encode_expr(expr)}

    def _encode_expr(self, expr: Expr) -> Params:
        match expr:
            case Eq(Field(name), Const(value)):
                return {name: {"eq": value}}
            case Ne(Field(name), Const(value)):
                return {name: {"ne": value}}
            case Lt(Field(name), Const(value)):
                return {name: {"lt": value}}
            case Le(Field(name), Const(value)):
                return {name: {"lte": value}}
            case Gt(Field(name), Const(value)):
                return {name: {"gt": value}}
            case Ge(Field(name), Const(value)):
                return {name: {"gte": value}}
            case In(Field(name), values):
                return {name: {"in": list(values)}}
            case And(left, right):
                return {"and": [self._encode_expr(left), self._encode_expr(right)]}
            case Or(left, right):
                return {"or": [self._encode_expr(left), self._encode_expr(right)]}
            case _:
                raise ValueError(f"Unsupported filter expression: {expr}")


def body_filters() -> BodyFilters:
    """Body filter encoding for POST search endpoints."""
    return BodyFilters()


# ─── Order Encoding ─────────────────────────────────────────────────────────


class OrderEncoding(ABC):
    """Base for order encoding strategies."""

    @abstractmethod
    def encode(self, specs: SequenceABC[OrderSpec]) -> Params:
        """Encode order specs to request params."""
        ...


@dataclass(frozen=True, slots=True)
class SortParamEncoding(OrderEncoding):
    """Encode ordering as comma-separated sort param: ?sort=-balance,name

    Configurable param name and format.
    """
    param: str = "sort"
    desc_prefix: str = "-"
    asc_prefix: str = ""
    separator: str = ","

    def encode(self, specs: SequenceABC[OrderSpec]) -> Params:
        parts: list[str] = []
        for spec in specs:
            prefix = self.asc_prefix if spec.ascending else self.desc_prefix
            parts.append(f"{prefix}{spec.field}")
        if parts:
            return {self.param: self.separator.join(parts)}
        return {}


def sort_param(
    param: str = "sort",
    desc_prefix: str = "-",
    asc_prefix: str = "",
    separator: str = ",",
) -> SortParamEncoding:
    """Sort param encoding: ?sort=-balance,name"""
    return SortParamEncoding(param=param, desc_prefix=desc_prefix, asc_prefix=asc_prefix, separator=separator)


# ─── Limit Encoding ─────────────────────────────────────────────────────────


class LimitEncoding(ABC):
    """Base for limit encoding strategies."""

    @abstractmethod
    def encode(self, count: int) -> Params:
        """Encode limit to request params."""
        ...


@dataclass(frozen=True, slots=True)
class LimitParamEncoding(LimitEncoding):
    """Encode limit as query param: ?limit=50"""
    param: str = "limit"

    def encode(self, count: int) -> Params:
        return {self.param: count}


def limit_param(param: str = "limit") -> LimitParamEncoding:
    """Limit param encoding: ?limit=50"""
    return LimitParamEncoding(param=param)


# ─── Select/Fields Encoding ─────────────────────────────────────────────────


class SelectEncoding(ABC):
    """Base for field selection encoding strategies."""

    @abstractmethod
    def encode(self, fields: SequenceABC[str]) -> Params:
        """Encode field selection to request params."""
        ...


@dataclass(frozen=True, slots=True)
class FieldsParamEncoding(SelectEncoding):
    """Encode field selection as comma-separated param: ?fields=id,name"""
    param: str = "fields"
    separator: str = ","

    def encode(self, fields: SequenceABC[str]) -> Params:
        return {self.param: self.separator.join(fields)}


def fields_param(param: str = "fields", separator: str = ",") -> FieldsParamEncoding:
    """Fields param encoding: ?fields=id,name"""
    return FieldsParamEncoding(param=param, separator=separator)


# ─── Response Parsing ────────────────────────────────────────────────────────


def _get_nested(data: Params, path: str) -> Any:
    """Get nested value by dot-separated path."""
    parts = path.split(".")
    current = data
    for part in parts:
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


# ─── HTTP API Provider ───────────────────────────────────────────────────────


@dataclass
class HTTPAPIProvider(Generic[T]):
    """HTTP API provider — executes APIQuerySet via HTTP.

    Created via http.api(Entity).base(...).build(client).
    """

    entity: type[T]
    client: httpx.AsyncClient
    base_url: str
    profile: type | None = None
    pagination: Pagination = field(default_factory=lambda: PageSizePagination())
    auth: Auth | None = None
    filter_encoding: FilterEncoding = field(default_factory=lambda: QueryParamFilters())
    order_encoding: OrderEncoding = field(default_factory=lambda: SortParamEncoding())
    limit_encoding: LimitEncoding = field(default_factory=lambda: LimitParamEncoding())
    select_encoding: SelectEncoding = field(default_factory=lambda: FieldsParamEncoding())
    data_path: str = "data"  # path to data array in response
    total_path: str | None = "total"  # path to total count
    id_field: str = "id"  # field used in URLs

    async def fetch_one(self, query: APIQuerySet[K, T]) -> T | None:
        """Execute get query, return single result."""
        if isinstance(query.op, GetOp):
            url = f"{self.base_url}/{_url_quote(str(query.op.id), safe='')}"
            try:
                response = await self._request("GET", url)
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    return None
                raise
            if response.status_code == 404:
                return None
            data = response.json()
            return self._parse_entity(data)
        elif isinstance(query.op, ListOp):
            results = await self.fetch_many(query)
            return results[0] if results else None
        raise ValueError(f"fetch_one requires Get or List op, got {type(query.op)}")

    def _build_http_context(self) -> HTTPAPIContext:
        """Build HTTP API context with closures over provider config."""
        return HTTPAPIContext(
            params={},
            body=None,
            encode_filter=lambda expr: self.filter_encoding.encode(expr, self.entity, self.profile),
            apply_pagination=lambda params, mod: self.pagination.apply(params, mod),
            is_body_filter=isinstance(self.filter_encoding, BodyFilters),
            encode_order=self.order_encoding.encode,
            encode_limit=self.limit_encoding.encode,
            encode_select=self.select_encoding.encode,
        )

    async def fetch_many(self, query: APIQuerySet[K, T]) -> list[T]:
        """Execute list query, return all results."""
        if not isinstance(query.op, ListOp):
            raise ValueError(f"fetch_many requires List op, got {type(query.op)}")

        url = self.base_url
        ctx = self._build_http_context()
        fold(query.mods, ctx, HTTPAPICompilable, "compile_http_api")

        method = "POST" if ctx.body else "GET"
        response = await self._request(method, url, params=ctx.params, json=ctx.body)
        data = response.json()

        # Extract data array
        items = _get_nested(data, self.data_path) if self.data_path else data
        if not isinstance(items, list):
            items = [items] if items else []

        return [self._parse_entity(item) for item in items]

    async def execute(self, query: APIQuerySet[K, T]) -> T:
        """Execute create/update, return result."""
        if isinstance(query.op, CreateOp):
            response = await self._request(
                "POST",
                self.base_url,
                json=self._serialize_entity(query.op.entity),
            )
            return self._parse_entity(response.json())

        elif isinstance(query.op, UpdateOp):
            url = f"{self.base_url}/{_url_quote(str(query.op.id), safe='')}"
            method = "PATCH" if query.op.partial else "PUT"
            response = await self._request(
                method,
                url,
                json=self._serialize_entity(query.op.entity),
            )
            return self._parse_entity(response.json())

        raise ValueError(f"execute requires Create or Update op, got {type(query.op)}")

    async def delete(self, query: APIQuerySet[K, T]) -> bool:
        """Execute delete, return success."""
        if not isinstance(query.op, DeleteOp):
            raise ValueError(f"delete requires Delete op, got {type(query.op)}")

        url = f"{self.base_url}/{_url_quote(str(query.op.id), safe='')}"
        response = await self._request("DELETE", url)
        return response.status_code in (200, 204)

    async def _request(
        self,
        method: str,
        url: str,
        params: Params | None = None,
        json: Params | None = None,
    ) -> httpx.Response:
        """Make HTTP request with auth."""
        headers: Headers = {}
        if self.auth:
            self.auth.apply(headers)

        response = await self.client.request(
            method,
            url,
            params=params,
            json=json,
            headers=headers,
        )
        response.raise_for_status()
        return response

    def _parse_entity(self, data: Params) -> T:
        """Parse response data into entity."""
        if not dataclasses.is_dataclass(self.entity):
            raise TypeError(
                f"{self.entity.__name__} must be a dataclass"
            )
        field_names = {f.name for f in dataclasses.fields(self.entity)}
        filtered = {k: v for k, v in data.items() if k in field_names}
        return self.entity(**filtered)

    def _serialize_entity(self, entity: T) -> Params:
        """Serialize entity to dict."""
        # asdict() needs a dataclass *instance*; is_dataclass alone also admits the
        # dataclass *type*, so exclude that to narrow entity to an instance.
        if not dataclasses.is_dataclass(entity) or isinstance(entity, type):
            raise TypeError(
                f"{type(entity).__name__} must be a dataclass instance"
            )
        return dataclasses.asdict(entity)


# ─── Builder ─────────────────────────────────────────────────────────────────


class HTTPAPIBuilder(Generic[T]):
    """Builder for HTTPAPIProvider.

    Usage:
        provider = (
            http.api(User, profile=InternalAPI)
            .base("https://api.example.com/users")
            .pagination(http.page_size())
            .auth(http.bearer(token))
            .build(client)
        )
    """

    __slots__ = (
        "_entity",
        "_profile",
        "_base_url",
        "_pagination",
        "_auth",
        "_filter_encoding",
        "_data_path",
        "_total_path",
        "_id_field",
    )

    def __init__(self, entity: type[T], profile: type | None = None) -> None:
        self._entity = entity
        self._profile = profile
        self._base_url: str | None = None
        self._pagination: Pagination = PageSizePagination()
        self._auth: Auth | None = None
        self._filter_encoding: FilterEncoding = QueryParamFilters()
        self._data_path = "data"
        self._total_path: str | None = "total"
        self._id_field = "id"

    def base(self, url: str) -> HTTPAPIBuilder[T]:
        """Set base URL."""
        self._base_url = url.rstrip("/")
        return self

    def pagination(self, strategy: Pagination) -> HTTPAPIBuilder[T]:
        """Set pagination strategy."""
        self._pagination = strategy
        return self

    def auth(self, strategy: Auth) -> HTTPAPIBuilder[T]:
        """Set auth strategy."""
        self._auth = strategy
        return self

    def filters(self, encoding: FilterEncoding) -> HTTPAPIBuilder[T]:
        """Set filter encoding strategy."""
        self._filter_encoding = encoding
        return self

    def response(
        self,
        data_path: str = "data",
        total_path: str | None = "total",
    ) -> HTTPAPIBuilder[T]:
        """Configure response parsing."""
        self._data_path = data_path
        self._total_path = total_path
        return self

    def id_field(self, field_name: str) -> HTTPAPIBuilder[T]:
        """Set ID field name for URLs."""
        self._id_field = field_name
        return self

    def build(self, client: httpx.AsyncClient) -> HTTPAPIProvider[T]:
        """Build provider with given HTTP client."""
        if not self._base_url:
            raise ValueError("base URL is required")

        return HTTPAPIProvider(
            entity=self._entity,
            client=client,
            base_url=self._base_url,
            profile=self._profile,
            pagination=self._pagination,
            auth=self._auth,
            filter_encoding=self._filter_encoding,
            data_path=self._data_path,
            total_path=self._total_path,
            id_field=self._id_field,
        )


def api(entity: type[T], profile: type | None = None) -> HTTPAPIBuilder[T]:
    """Start building HTTP API provider.

    Usage:
        provider = http.api(User).base("...").build(client)
        provider = http.api(User, profile=InternalAPI).base("...").build(client)
    """
    return HTTPAPIBuilder(entity, profile)


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

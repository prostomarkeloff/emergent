"""Tests for HTTP API query provider.

Covers pagination strategies, auth strategies, filter encoding,
the HTTPAPIBuilder, _get_nested helper, and provider entity parsing/serialization.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass

import httpx
import pytest

from emergent.wire.axis.query._api import (
    APIQuerySet,
    CreateOp,
    CursorMod,
    DeleteOp,
    FilterMod,
    GetOp,
    IncludeMod,
    ListOp,
    OffsetMod,
    OrderMod,
    PageMod,
    SearchMod,
    SelectMod,
    UpdateOp,
)
from emergent.wire.axis.query._expr import (
    And,
    Const,
    Contains,
    EndsWith,
    Eq,
    Field,
    Ge,
    Gt,
    In,
    IsNotNull,
    IsNull,
    Le,
    Lt,
    Ne,
    Or,
    StartsWith,
)
from emergent.wire.axis.query._proxy import OrderSpec
from emergent.wire.axis.query.contrib._impls._http import (
    APIKeyAuth,
    BasicAuth,
    BearerAuth,
    BodyFilters,
    CursorPagination,
    HTTPAPIBuilder,
    HTTPAPIProvider,
    OffsetLimitPagination,
    PageSizePagination,
    QueryParamFilters,
    _get_nested,  # pyright: ignore[reportPrivateUsage]  # testing private helper directly
    api_key,
    basic,
    bearer,
    body_filters,
    cursor,
    offset_limit,
    page_size,
    query_params,
)


# ─── Fixtures ────────────────────────────────────────────────────────────────


@dataclass
class User:
    id: str
    name: str
    balance: int


# ─── Pagination Tests ────────────────────────────────────────────────────────


class TestPageSizePagination:
    def test_apply_page_mod(self) -> None:
        pagination = PageSizePagination()
        params: dict[str, int | str] = {}
        pagination.apply(params, PageMod(page=3, per_page=25))
        assert params == {"page": 3, "per_page": 25}

    def test_apply_page_mod_custom_params(self) -> None:
        pagination = PageSizePagination(page_param="p", size_param="size")
        params: dict[str, int | str] = {}
        pagination.apply(params, PageMod(page=2, per_page=10))
        assert params == {"p": 2, "size": 10}

    def test_apply_offset_mod_converts_to_page(self) -> None:
        pagination = PageSizePagination()
        params: dict[str, int | str] = {}
        # offset=40, limit=20 -> page = (40 // 20) + 1 = 3
        pagination.apply(params, OffsetMod(offset=40, limit=20))
        assert params == {"page": 3, "per_page": 20}

    def test_apply_offset_mod_zero_offset(self) -> None:
        pagination = PageSizePagination()
        params: dict[str, int | str] = {}
        # offset=0, limit=10 -> page = (0 // 10) + 1 = 1
        pagination.apply(params, OffsetMod(offset=0, limit=10))
        assert params == {"page": 1, "per_page": 10}

    def test_apply_cursor_mod_does_nothing(self) -> None:
        pagination = PageSizePagination()
        params: dict[str, int | str] = {}
        pagination.apply(params, CursorMod(cursor="abc", limit=10))
        assert params == {}


class TestOffsetLimitPagination:
    def test_apply_offset_mod(self) -> None:
        pagination = OffsetLimitPagination()
        params: dict[str, int | str] = {}
        pagination.apply(params, OffsetMod(offset=100, limit=50))
        assert params == {"offset": 100, "limit": 50}

    def test_apply_offset_mod_custom_params(self) -> None:
        pagination = OffsetLimitPagination(offset_param="skip", limit_param="take")
        params: dict[str, int | str] = {}
        pagination.apply(params, OffsetMod(offset=20, limit=10))
        assert params == {"skip": 20, "take": 10}

    def test_apply_page_mod_converts_to_offset(self) -> None:
        pagination = OffsetLimitPagination()
        params: dict[str, int | str] = {}
        # page=3, per_page=20 -> offset = (3 - 1) * 20 = 40
        pagination.apply(params, PageMod(page=3, per_page=20))
        assert params == {"offset": 40, "limit": 20}

    def test_apply_page_mod_first_page(self) -> None:
        pagination = OffsetLimitPagination()
        params: dict[str, int | str] = {}
        # page=1, per_page=10 -> offset = 0
        pagination.apply(params, PageMod(page=1, per_page=10))
        assert params == {"offset": 0, "limit": 10}

    def test_apply_cursor_mod_does_nothing(self) -> None:
        pagination = OffsetLimitPagination()
        params: dict[str, int | str] = {}
        pagination.apply(params, CursorMod(cursor="abc", limit=10))
        assert params == {}


class TestCursorPagination:
    def test_apply_cursor_mod(self) -> None:
        pagination = CursorPagination()
        params: dict[str, int | str] = {}
        pagination.apply(params, CursorMod(cursor="eyJpZCI6MTIzfQ==", limit=25))
        assert params == {"cursor": "eyJpZCI6MTIzfQ==", "limit": 25}

    def test_apply_cursor_mod_without_cursor_value(self) -> None:
        pagination = CursorPagination()
        params: dict[str, int | str] = {}
        # Empty string cursor is falsy, should not be included
        pagination.apply(params, CursorMod(cursor="", limit=20))
        assert params == {"limit": 20}
        assert "cursor" not in params

    def test_apply_cursor_mod_custom_params(self) -> None:
        pagination = CursorPagination(cursor_param="after", limit_param="first")
        params: dict[str, int | str] = {}
        pagination.apply(params, CursorMod(cursor="abc123", limit=10))
        assert params == {"after": "abc123", "first": 10}

    def test_apply_page_mod_does_nothing(self) -> None:
        pagination = CursorPagination()
        params: dict[str, int | str] = {}
        pagination.apply(params, PageMod(page=1, per_page=20))
        assert params == {}


class TestPaginationFactories:
    def test_page_size_returns_correct_type(self) -> None:
        result = page_size()
        assert isinstance(result, PageSizePagination)
        assert result.page_param == "page"
        assert result.size_param == "per_page"

    def test_page_size_with_custom_params(self) -> None:
        result = page_size(page="p", size="s")
        assert result.page_param == "p"
        assert result.size_param == "s"

    def test_offset_limit_returns_correct_type(self) -> None:
        result = offset_limit()
        assert isinstance(result, OffsetLimitPagination)
        assert result.offset_param == "offset"
        assert result.limit_param == "limit"

    def test_cursor_returns_correct_type(self) -> None:
        result = cursor()
        assert isinstance(result, CursorPagination)
        assert result.cursor_param == "cursor"
        assert result.limit_param == "limit"


# ─── Auth Tests ──────────────────────────────────────────────────────────────


class TestBearerAuth:
    def test_apply_sets_authorization_header(self) -> None:
        auth = BearerAuth(token="my-secret-token")
        headers: dict[str, str] = {}
        auth.apply(headers)
        assert headers == {"Authorization": "Bearer my-secret-token"}


class TestAPIKeyAuth:
    def test_apply_sets_header(self) -> None:
        auth = APIKeyAuth(key="abc123", header="X-API-Key")
        headers: dict[str, str] = {}
        auth.apply(headers)
        assert headers == {"X-API-Key": "abc123"}

    def test_apply_custom_header_name(self) -> None:
        auth = APIKeyAuth(key="secret", header="X-Custom-Key")
        headers: dict[str, str] = {}
        auth.apply(headers)
        assert headers == {"X-Custom-Key": "secret"}

    def test_apply_no_header_does_nothing(self) -> None:
        auth = APIKeyAuth(key="abc123", header=None, param="api_key")
        headers: dict[str, str] = {}
        auth.apply(headers)
        assert headers == {}


class TestBasicAuth:
    def test_apply_sets_base64_header(self) -> None:
        auth = BasicAuth(username="alice", password="secret")
        headers: dict[str, str] = {}
        auth.apply(headers)
        expected_credentials = base64.b64encode(b"alice:secret").decode()
        assert headers == {"Authorization": f"Basic {expected_credentials}"}

    def test_apply_encodes_correctly(self) -> None:
        auth = BasicAuth(username="user", password="p@ss:word")
        headers: dict[str, str] = {}
        auth.apply(headers)
        decoded = base64.b64decode(
            headers["Authorization"].removeprefix("Basic ")
        ).decode()
        assert decoded == "user:p@ss:word"


class TestAuthFactories:
    def test_bearer_returns_correct_type(self) -> None:
        result = bearer("tok")
        assert isinstance(result, BearerAuth)
        assert result.token == "tok"

    def test_api_key_returns_correct_type(self) -> None:
        result = api_key("key123", header="X-Key")
        assert isinstance(result, APIKeyAuth)
        assert result.key == "key123"
        assert result.header == "X-Key"

    def test_basic_returns_correct_type(self) -> None:
        result = basic("user", "pass")
        assert isinstance(result, BasicAuth)
        assert result.username == "user"
        assert result.password == "pass"


# ─── Filter Encoding Tests ───────────────────────────────────────────────────


class TestQueryParamFilters:
    def _encode(
        self,
        expr: Eq | Ne | Lt | Le | Gt | Ge | In | Contains | StartsWith | EndsWith | IsNull | IsNotNull | And | Or,
        sep: str = "__",
    ) -> dict[str, str | int | bool]:
        encoding = QueryParamFilters(operator_sep=sep)
        return encoding.encode(expr, User, None)

    def test_eq(self) -> None:
        expr = Eq(Field("name"), Const("alice"))
        result = self._encode(expr)
        assert result == {"name": "alice"}

    def test_ne(self) -> None:
        expr = Ne(Field("status"), Const("banned"))
        result = self._encode(expr)
        assert result == {"status__ne": "banned"}

    def test_lt(self) -> None:
        expr = Lt(Field("balance"), Const(100))
        result = self._encode(expr)
        assert result == {"balance__lt": 100}

    def test_le(self) -> None:
        expr = Le(Field("balance"), Const(100))
        result = self._encode(expr)
        assert result == {"balance__lte": 100}

    def test_gt(self) -> None:
        expr = Gt(Field("balance"), Const(100))
        result = self._encode(expr)
        assert result == {"balance__gt": 100}

    def test_ge(self) -> None:
        expr = Ge(Field("balance"), Const(100))
        result = self._encode(expr)
        assert result == {"balance__gte": 100}

    def test_in(self) -> None:
        expr = In(Field("status"), ("active", "pending"))
        result = self._encode(expr)
        assert result == {"status__in": "active,pending"}

    def test_contains(self) -> None:
        expr = Contains(Field("name"), "ali")
        result = self._encode(expr)
        assert result == {"name__contains": "ali"}

    def test_startswith(self) -> None:
        expr = StartsWith(Field("name"), "al")
        result = self._encode(expr)
        assert result == {"name__startswith": "al"}

    def test_endswith(self) -> None:
        expr = EndsWith(Field("name"), "ice")
        result = self._encode(expr)
        assert result == {"name__endswith": "ice"}

    def test_isnull(self) -> None:
        expr = IsNull(Field("deleted_at"))
        result = self._encode(expr)
        assert result == {"deleted_at__isnull": "true"}

    def test_isnotnull(self) -> None:
        expr = IsNotNull(Field("email"))
        result = self._encode(expr)
        assert result == {"email__isnull": "false"}

    def test_and(self) -> None:
        expr = And(
            Eq(Field("active"), Const(True)),
            Gt(Field("balance"), Const(0)),
        )
        result = self._encode(expr)
        assert result == {"active": True, "balance__gt": 0}

    def test_or_raises_value_error(self) -> None:
        expr = Or(
            Eq(Field("role"), Const("admin")),
            Eq(Field("role"), Const("mod")),
        )
        with pytest.raises(ValueError, match="OR filters not supported"):
            self._encode(expr)

    def test_custom_operator_sep(self) -> None:
        expr = Gt(Field("balance"), Const(100))
        result = self._encode(expr, sep=".")
        assert result == {"balance.gt": 100}


class TestBodyFilters:
    def _encode(
        self,
        expr: Eq | Ne | Lt | Le | Gt | Ge | In | And | Or,
    ) -> dict[str, dict[str, str | int | bool | list[str]] | list[dict[str, dict[str, str | int | bool]]]]:
        encoding = BodyFilters()
        return encoding.encode(expr, User, None)

    def test_eq(self) -> None:
        expr = Eq(Field("name"), Const("alice"))
        result = self._encode(expr)
        assert result == {"filter": {"name": {"eq": "alice"}}}

    def test_ne(self) -> None:
        expr = Ne(Field("name"), Const("bob"))
        result = self._encode(expr)
        assert result == {"filter": {"name": {"ne": "bob"}}}

    def test_lt(self) -> None:
        expr = Lt(Field("balance"), Const(50))
        result = self._encode(expr)
        assert result == {"filter": {"balance": {"lt": 50}}}

    def test_and(self) -> None:
        expr = And(
            Eq(Field("active"), Const(True)),
            Gt(Field("balance"), Const(0)),
        )
        result = self._encode(expr)
        assert result == {
            "filter": {
                "and": [
                    {"active": {"eq": True}},
                    {"balance": {"gt": 0}},
                ]
            }
        }

    def test_or(self) -> None:
        expr = Or(
            Eq(Field("role"), Const("admin")),
            Eq(Field("role"), Const("mod")),
        )
        result = self._encode(expr)
        assert result == {
            "filter": {
                "or": [
                    {"role": {"eq": "admin"}},
                    {"role": {"eq": "mod"}},
                ]
            }
        }

    def test_in(self) -> None:
        expr = In(Field("status"), ("active", "pending"))
        result = self._encode(expr)
        assert result == {"filter": {"status": {"in": ["active", "pending"]}}}


class TestFilterFactories:
    def test_query_params_returns_correct_type(self) -> None:
        result = query_params()
        assert isinstance(result, QueryParamFilters)
        assert result.operator_sep == "__"

    def test_query_params_custom_sep(self) -> None:
        result = query_params(operator_sep=".")
        assert result.operator_sep == "."

    def test_body_filters_returns_correct_type(self) -> None:
        result = body_filters()
        assert isinstance(result, BodyFilters)


# ─── Helper Tests ────────────────────────────────────────────────────────────


class TestGetNested:
    def test_simple_path(self) -> None:
        data = {"name": "alice"}
        assert _get_nested(data, "name") == "alice"

    def test_nested_path(self) -> None:
        data = {"response": {"data": [1, 2, 3]}}
        assert _get_nested(data, "response.data") == [1, 2, 3]

    def test_deeply_nested(self) -> None:
        data = {"a": {"b": {"c": "deep"}}}
        assert _get_nested(data, "a.b.c") == "deep"

    def test_missing_key_returns_none(self) -> None:
        data = {"name": "alice"}
        assert _get_nested(data, "missing") is None

    def test_missing_nested_key_returns_none(self) -> None:
        data = {"a": {"b": 1}}
        assert _get_nested(data, "a.c") is None

    def test_non_dict_intermediate_returns_none(self) -> None:
        data = {"a": "not-a-dict"}
        assert _get_nested(data, "a.b") is None


# ─── Builder Tests ───────────────────────────────────────────────────────────


class TestHTTPAPIBuilder:
    def test_build_without_base_url_raises(self) -> None:
        builder = HTTPAPIBuilder(User)
        client = httpx.AsyncClient()
        with pytest.raises(ValueError, match="base URL is required"):
            builder.build(client)

    def test_build_with_base_url(self) -> None:
        client = httpx.AsyncClient()
        provider = HTTPAPIBuilder(User).base("https://api.example.com/users").build(client)
        assert provider.base_url == "https://api.example.com/users"
        assert provider.entity is User
        assert provider.client is client

    def test_base_url_strips_trailing_slash(self) -> None:
        client = httpx.AsyncClient()
        provider = HTTPAPIBuilder(User).base("https://api.example.com/users/").build(client)
        assert provider.base_url == "https://api.example.com/users"

    def test_fluent_api_chaining(self) -> None:
        client = httpx.AsyncClient()
        auth_strategy = bearer("token")
        pagination_strategy = offset_limit()
        filter_strategy = body_filters()

        provider = (
            HTTPAPIBuilder(User)
            .base("https://api.example.com/users")
            .pagination(pagination_strategy)
            .auth(auth_strategy)
            .filters(filter_strategy)
            .response(data_path="results", total_path="count")
            .id_field("user_id")
            .build(client)
        )

        assert provider.base_url == "https://api.example.com/users"
        assert isinstance(provider.pagination, OffsetLimitPagination)
        assert isinstance(provider.auth, BearerAuth)
        assert isinstance(provider.filter_encoding, BodyFilters)
        assert provider.data_path == "results"
        assert provider.total_path == "count"
        assert provider.id_field == "user_id"

    def test_build_with_profile(self) -> None:
        class InternalAPI:
            pass

        client = httpx.AsyncClient()
        provider = (
            HTTPAPIBuilder(User, profile=InternalAPI)
            .base("https://api.example.com/users")
            .build(client)
        )
        assert provider.profile is InternalAPI

    def test_build_defaults(self) -> None:
        client = httpx.AsyncClient()
        provider = HTTPAPIBuilder(User).base("https://api.example.com/users").build(client)
        assert isinstance(provider.pagination, PageSizePagination)
        assert provider.auth is None
        assert isinstance(provider.filter_encoding, QueryParamFilters)
        assert provider.data_path == "data"
        assert provider.total_path == "total"
        assert provider.id_field == "id"


# ─── Provider Parsing Tests ──────────────────────────────────────────────────


class TestProviderParseEntity:
    def _make_provider(self) -> HTTPAPIProvider[User]:
        client = httpx.AsyncClient()
        return HTTPAPIProvider(
            entity=User,
            client=client,
            base_url="https://api.example.com/users",
        )

    def test_parse_entity_with_dataclass(self) -> None:
        provider = self._make_provider()
        data = {"id": "u1", "name": "alice", "balance": 100}
        result = provider._parse_entity(data)  # pyright: ignore[reportPrivateUsage]  # testing protected method
        assert isinstance(result, User)
        assert result.id == "u1"
        assert result.name == "alice"
        assert result.balance == 100

    def test_parse_entity_filters_extra_fields(self) -> None:
        provider = self._make_provider()
        data = {"id": "u1", "name": "alice", "balance": 100, "extra": "ignored"}
        result = provider._parse_entity(data)  # pyright: ignore[reportPrivateUsage]  # testing protected method
        assert isinstance(result, User)
        assert result.id == "u1"
        assert not hasattr(result, "extra")

    def test_parse_entity_non_dataclass_raises(self) -> None:
        client = httpx.AsyncClient()
        provider = HTTPAPIProvider(
            entity=str,  # type: ignore[arg-type]
            client=client,
            base_url="https://api.example.com",
        )
        with pytest.raises(TypeError, match="must be a dataclass"):
            provider._parse_entity({"value": "test"})  # pyright: ignore[reportPrivateUsage]  # testing protected method


class TestProviderSerializeEntity:
    def _make_provider(self) -> HTTPAPIProvider[User]:
        client = httpx.AsyncClient()
        return HTTPAPIProvider(
            entity=User,
            client=client,
            base_url="https://api.example.com/users",
        )

    def test_serialize_entity_with_dataclass(self) -> None:
        provider = self._make_provider()
        user = User(id="u1", name="alice", balance=100)
        result = provider._serialize_entity(user)  # pyright: ignore[reportPrivateUsage]  # testing protected method
        assert result == {"id": "u1", "name": "alice", "balance": 100}

    def test_serialize_non_dataclass_raises(self) -> None:
        provider = self._make_provider()
        with pytest.raises(TypeError, match="must be a dataclass instance"):
            provider._serialize_entity("not a dataclass")  # type: ignore[arg-type]  # pyright: ignore[reportPrivateUsage]  # testing protected method with intentionally wrong type


# ─── Provider HTTP Integration Tests ─────────────────────────────────────────


class TestProviderFetchOne:
    @pytest.mark.asyncio
    async def test_fetch_one_get_op(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            assert str(request.url) == "https://api.example.com/users/u1"
            assert request.method == "GET"
            return httpx.Response(
                200,
                json={"id": "u1", "name": "alice", "balance": 100},
            )

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)
        provider = HTTPAPIProvider(
            entity=User,
            client=client,
            base_url="https://api.example.com/users",
        )

        query: APIQuerySet[str, User] = APIQuerySet(entity=User, op=GetOp(id="u1"))
        result = await provider.fetch_one(query)
        assert result is not None
        assert result.id == "u1"
        assert result.name == "alice"

    @pytest.mark.asyncio
    async def test_fetch_one_get_op_not_found_returns_none(self) -> None:
        """404 returns None — HTTPStatusError is caught for 404 status."""
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={})

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)
        provider = HTTPAPIProvider(
            entity=User,
            client=client,
            base_url="https://api.example.com/users",
        )

        query: APIQuerySet[str, User] = APIQuerySet(entity=User, op=GetOp(id="missing"))
        result = await provider.fetch_one(query)
        assert result is None


class TestProviderFetchMany:
    @pytest.mark.asyncio
    async def test_fetch_many_list_op(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "GET"
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"id": "u1", "name": "alice", "balance": 100},
                        {"id": "u2", "name": "bob", "balance": 200},
                    ],
                    "total": 2,
                },
            )

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)
        provider = HTTPAPIProvider(
            entity=User,
            client=client,
            base_url="https://api.example.com/users",
        )

        query: APIQuerySet[str, User] = APIQuerySet(entity=User, op=ListOp())
        result = await provider.fetch_many(query)
        assert len(result) == 2
        assert result[0].name == "alice"
        assert result[1].name == "bob"

    @pytest.mark.asyncio
    async def test_fetch_many_with_auth(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            assert request.headers["Authorization"] == "Bearer my-token"
            return httpx.Response(200, json={"data": []})

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)
        provider = HTTPAPIProvider(
            entity=User,
            client=client,
            base_url="https://api.example.com/users",
            auth=BearerAuth("my-token"),
        )

        query: APIQuerySet[str, User] = APIQuerySet(entity=User, op=ListOp())
        await provider.fetch_many(query)

    @pytest.mark.asyncio
    async def test_fetch_many_with_pagination_mod(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.params["page"] == "2"
            assert request.url.params["per_page"] == "10"
            return httpx.Response(200, json={"data": []})

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)
        provider = HTTPAPIProvider(
            entity=User,
            client=client,
            base_url="https://api.example.com/users",
        )

        query: APIQuerySet[str, User] = APIQuerySet(
            entity=User,
            op=ListOp(),
            mods=(PageMod(page=2, per_page=10),),
        )
        await provider.fetch_many(query)

    @pytest.mark.asyncio
    async def test_fetch_many_with_search_mod(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.params["q"] == "alice"
            return httpx.Response(200, json={"data": []})

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)
        provider = HTTPAPIProvider(
            entity=User,
            client=client,
            base_url="https://api.example.com/users",
        )

        query: APIQuerySet[str, User] = APIQuerySet(
            entity=User,
            op=ListOp(),
            mods=(SearchMod(query="alice"),),
        )
        await provider.fetch_many(query)

    @pytest.mark.asyncio
    async def test_fetch_many_with_select_mod(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.params["fields"] == "id,name"
            return httpx.Response(200, json={"data": []})

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)
        provider = HTTPAPIProvider(
            entity=User,
            client=client,
            base_url="https://api.example.com/users",
        )

        query: APIQuerySet[str, User] = APIQuerySet(
            entity=User,
            op=ListOp(),
            mods=(SelectMod(fields=("id", "name")),),
        )
        await provider.fetch_many(query)

    @pytest.mark.asyncio
    async def test_fetch_many_with_include_mod(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.params["include"] == "posts,comments"
            return httpx.Response(200, json={"data": []})

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)
        provider = HTTPAPIProvider(
            entity=User,
            client=client,
            base_url="https://api.example.com/users",
        )

        query: APIQuerySet[str, User] = APIQuerySet(
            entity=User,
            op=ListOp(),
            mods=(IncludeMod(relations=("posts", "comments")),),
        )
        await provider.fetch_many(query)

    @pytest.mark.asyncio
    async def test_fetch_many_with_order_mod(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.params["sort"] == "name,-balance"
            return httpx.Response(200, json={"data": []})

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)
        provider = HTTPAPIProvider(
            entity=User,
            client=client,
            base_url="https://api.example.com/users",
        )

        query: APIQuerySet[str, User] = APIQuerySet(
            entity=User,
            op=ListOp(),
            mods=(
                OrderMod(specs=(
                    OrderSpec(field="name", ascending=True),
                    OrderSpec(field="balance", ascending=False),
                )),
            ),
        )
        await provider.fetch_many(query)

    @pytest.mark.asyncio
    async def test_fetch_many_with_filter_mod_query_params(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.params["name"] == "alice"
            return httpx.Response(200, json={"data": []})

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)
        provider = HTTPAPIProvider(
            entity=User,
            client=client,
            base_url="https://api.example.com/users",
        )

        query: APIQuerySet[str, User] = APIQuerySet(
            entity=User,
            op=ListOp(),
            mods=(FilterMod(expr=Eq(Field("name"), Const("alice"))),),
        )
        await provider.fetch_many(query)

    @pytest.mark.asyncio
    async def test_fetch_many_with_body_filters_uses_post(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "POST"
            body = json.loads(request.content)
            assert body == {"filter": {"name": {"eq": "alice"}}}
            return httpx.Response(200, json={"data": []})

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)
        provider = HTTPAPIProvider(
            entity=User,
            client=client,
            base_url="https://api.example.com/users",
            filter_encoding=BodyFilters(),
        )

        query: APIQuerySet[str, User] = APIQuerySet(
            entity=User,
            op=ListOp(),
            mods=(FilterMod(expr=Eq(Field("name"), Const("alice"))),),
        )
        await provider.fetch_many(query)


class TestProviderExecute:
    @pytest.mark.asyncio
    async def test_execute_create(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "POST"
            assert str(request.url) == "https://api.example.com/users"
            body = json.loads(request.content)
            assert body == {"id": "u1", "name": "alice", "balance": 100}
            return httpx.Response(
                201,
                json={"id": "u1", "name": "alice", "balance": 100},
            )

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)
        provider = HTTPAPIProvider(
            entity=User,
            client=client,
            base_url="https://api.example.com/users",
        )

        user = User(id="u1", name="alice", balance=100)
        query: APIQuerySet[str, User] = APIQuerySet(entity=User, op=CreateOp(entity=user))
        result = await provider.execute(query)
        assert result.id == "u1"
        assert result.name == "alice"

    @pytest.mark.asyncio
    async def test_execute_update_put(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "PUT"
            assert str(request.url) == "https://api.example.com/users/u1"
            return httpx.Response(
                200,
                json={"id": "u1", "name": "alice_updated", "balance": 200},
            )

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)
        provider = HTTPAPIProvider(
            entity=User,
            client=client,
            base_url="https://api.example.com/users",
        )

        user = User(id="u1", name="alice_updated", balance=200)
        query: APIQuerySet[str, User] = APIQuerySet(entity=User, op=UpdateOp(id="u1", entity=user, partial=False))
        result = await provider.execute(query)
        assert result.name == "alice_updated"

    @pytest.mark.asyncio
    async def test_execute_update_patch(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "PATCH"
            return httpx.Response(
                200,
                json={"id": "u1", "name": "alice_patched", "balance": 150},
            )

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)
        provider = HTTPAPIProvider(
            entity=User,
            client=client,
            base_url="https://api.example.com/users",
        )

        user = User(id="u1", name="alice_patched", balance=150)
        query: APIQuerySet[str, User] = APIQuerySet(entity=User, op=UpdateOp(id="u1", entity=user, partial=True))
        result = await provider.execute(query)
        assert result.name == "alice_patched"


class TestProviderDelete:
    @pytest.mark.asyncio
    async def test_delete_success(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "DELETE"
            assert str(request.url) == "https://api.example.com/users/u1"
            return httpx.Response(204)

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)
        provider = HTTPAPIProvider(
            entity=User,
            client=client,
            base_url="https://api.example.com/users",
        )

        query: APIQuerySet[str, User] = APIQuerySet(entity=User, op=DeleteOp(id="u1"))
        result = await provider.delete(query)
        assert result is True

    @pytest.mark.asyncio
    async def test_delete_200_also_success(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200)

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)
        provider = HTTPAPIProvider(
            entity=User,
            client=client,
            base_url="https://api.example.com/users",
        )

        query: APIQuerySet[str, User] = APIQuerySet(entity=User, op=DeleteOp(id="u1"))
        result = await provider.delete(query)
        assert result is True

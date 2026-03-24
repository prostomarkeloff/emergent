# pyright: reportPrivateUsage=false
"""Tests for contrib providers, memory provider deeper coverage, and misc uncovered modules.

Covers:
- HTTP contrib: pagination, auth, filter encoding, order encoding, builder
- Memory API provider: fetch_one, fetch_many, fetch_page, execute, delete, next_id
- resolve.py: unwrap/wrap for Option, Result types; get_method_params
- surface explain: edge cases
- HTTP dialect: Tag, BearerAuth, ApiKeyAuth, OAuth2Auth, Summary, OperationId, etc.
- Telegram dialect: HelpMeta, Silent, ParseMode, etc.
- SQL queryset: window, for_update, returning, introspection, to_relational
- _generate.py: to_datanode, to_datanode_auto, ArgSpec assembly
"""

from __future__ import annotations

import base64
from dataclasses import dataclass

import pytest

from kungfu import Option, Some, Nothing, Result, Ok, Error
from emergent.wire.axis.query.providers.memory import MemoryAPIProvider

# ═══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class User:
    id: int
    name: str
    balance: float = 0.0
    active: bool = True
    department: str = "eng"
    email: str | None = None


@dataclass(frozen=True, slots=True)
class Item:
    id: int
    title: str
    price: float = 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# HTTP Contrib — Pagination strategies
# ═══════════════════════════════════════════════════════════════════════════════


class TestPageSizePagination:
    def test_page_mod_applies_page_and_size(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import PageSizePagination
        from emergent.wire.axis.query._api import PageMod

        pag = PageSizePagination()
        params: dict[str, object] = {}
        pag.apply(params, PageMod(page=2, per_page=25))
        assert params == {"page": 2, "per_page": 25}

    def test_custom_param_names(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import PageSizePagination
        from emergent.wire.axis.query._api import PageMod

        pag = PageSizePagination(page_param="p", size_param="s")
        params: dict[str, object] = {}
        pag.apply(params, PageMod(page=3, per_page=10))
        assert params == {"p": 3, "s": 10}

    def test_offset_mod_converted_to_page(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import PageSizePagination
        from emergent.wire.axis.query._api import OffsetMod

        pag = PageSizePagination()
        params: dict[str, object] = {}
        pag.apply(params, OffsetMod(offset=40, limit=20))
        # (40 // 20) + 1 = 3
        assert params["page"] == 3
        assert params["per_page"] == 20


class TestOffsetLimitPagination:
    def test_offset_mod(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import OffsetLimitPagination
        from emergent.wire.axis.query._api import OffsetMod

        pag = OffsetLimitPagination()
        params: dict[str, object] = {}
        pag.apply(params, OffsetMod(offset=10, limit=5))
        assert params == {"offset": 10, "limit": 5}

    def test_page_mod_converted_to_offset(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import OffsetLimitPagination
        from emergent.wire.axis.query._api import PageMod

        pag = OffsetLimitPagination()
        params: dict[str, object] = {}
        pag.apply(params, PageMod(page=3, per_page=10))
        # (3 - 1) * 10 = 20
        assert params["offset"] == 20
        assert params["limit"] == 10


class TestCursorPagination:
    def test_cursor_mod_with_cursor(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import CursorPagination
        from emergent.wire.axis.query._api import CursorMod

        pag = CursorPagination()
        params: dict[str, object] = {}
        pag.apply(params, CursorMod(cursor="abc123", limit=50))
        assert params == {"cursor": "abc123", "limit": 50}

    def test_cursor_mod_without_cursor(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import CursorPagination
        from emergent.wire.axis.query._api import CursorMod

        pag = CursorPagination()
        params: dict[str, object] = {}
        pag.apply(params, CursorMod(cursor="", limit=20))
        # Empty string is falsy, cursor not added
        assert "cursor" not in params
        assert params["limit"] == 20


# ═══════════════════════════════════════════════════════════════════════════════
# HTTP Contrib — Auth strategies
# ═══════════════════════════════════════════════════════════════════════════════


class TestBearerAuth:
    def test_bearer_applies_header(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import BearerAuth

        auth = BearerAuth(token="my-token-123")
        headers: dict[str, str] = {}
        auth.apply(headers)
        assert headers["Authorization"] == "Bearer my-token-123"


class TestAPIKeyAuth:
    def test_api_key_header(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import APIKeyAuth

        auth = APIKeyAuth(key="secret", header="X-API-Key")
        headers: dict[str, str] = {}
        auth.apply(headers)
        assert headers["X-API-Key"] == "secret"

    def test_api_key_custom_header(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import APIKeyAuth

        auth = APIKeyAuth(key="abc", header="X-Custom")
        headers: dict[str, str] = {}
        auth.apply(headers)
        assert headers["X-Custom"] == "abc"


class TestBasicAuth:
    def test_basic_auth_encodes_credentials(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import BasicAuth

        auth = BasicAuth(username="user", password="pass")
        headers: dict[str, str] = {}
        auth.apply(headers)
        expected = base64.b64encode(b"user:pass").decode()
        assert headers["Authorization"] == f"Basic {expected}"


# ═══════════════════════════════════════════════════════════════════════════════
# HTTP Contrib — Filter Encoding
# ═══════════════════════════════════════════════════════════════════════════════


class TestQueryParamFilters:
    def test_eq_filter(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import QueryParamFilters
        from emergent.wire.axis.query._expr import Eq, Field, Const

        enc = QueryParamFilters()
        result = enc.encode(Eq(Field("name"), Const("alice")), User, None)
        assert result == {"name": "alice"}

    def test_ne_filter(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import QueryParamFilters
        from emergent.wire.axis.query._expr import Ne, Field, Const

        enc = QueryParamFilters()
        result = enc.encode(Ne(Field("name"), Const("bob")), User, None)
        assert result == {"name__ne": "bob"}

    def test_lt_gt_le_ge_filters(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import QueryParamFilters
        from emergent.wire.axis.query._expr import Lt, Gt, Le, Ge, Field, Const

        enc = QueryParamFilters()
        assert enc.encode(Lt(Field("balance"), Const(100)), User, None) == {"balance__lt": 100}
        assert enc.encode(Gt(Field("balance"), Const(50)), User, None) == {"balance__gt": 50}
        assert enc.encode(Le(Field("balance"), Const(100)), User, None) == {"balance__lte": 100}
        assert enc.encode(Ge(Field("balance"), Const(50)), User, None) == {"balance__gte": 50}

    def test_in_filter(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import QueryParamFilters
        from emergent.wire.axis.query._expr import In, Field

        enc = QueryParamFilters()
        result = enc.encode(In(Field("id"), (1, 2, 3)), User, None)
        assert result == {"id__in": "1,2,3"}

    def test_contains_startswith_endswith(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import QueryParamFilters
        from emergent.wire.axis.query._expr import Contains, StartsWith, EndsWith, Field

        enc = QueryParamFilters()
        assert enc.encode(Contains(Field("name"), "ali"), User, None) == {"name__contains": "ali"}
        assert enc.encode(StartsWith(Field("name"), "al"), User, None) == {"name__startswith": "al"}
        assert enc.encode(EndsWith(Field("name"), "ce"), User, None) == {"name__endswith": "ce"}

    def test_isnull_isnotnull(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import QueryParamFilters
        from emergent.wire.axis.query._expr import IsNull, IsNotNull, Field

        enc = QueryParamFilters()
        assert enc.encode(IsNull(Field("email")), User, None) == {"email__isnull": "true"}
        assert enc.encode(IsNotNull(Field("email")), User, None) == {"email__isnull": "false"}

    def test_and_combines_params(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import QueryParamFilters
        from emergent.wire.axis.query._expr import And, Eq, Gt, Field, Const

        enc = QueryParamFilters()
        expr = And(Eq(Field("name"), Const("alice")), Gt(Field("balance"), Const(100)))
        result = enc.encode(expr, User, None)
        assert result == {"name": "alice", "balance__gt": 100}

    def test_and_duplicate_key_raises(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import QueryParamFilters
        from emergent.wire.axis.query._expr import And, Eq, Field, Const

        enc = QueryParamFilters()
        expr = And(Eq(Field("name"), Const("alice")), Eq(Field("name"), Const("bob")))
        with pytest.raises(ValueError, match="Duplicate filter key"):
            enc.encode(expr, User, None)

    def test_or_raises(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import QueryParamFilters
        from emergent.wire.axis.query._expr import Or, Eq, Field, Const

        enc = QueryParamFilters()
        expr = Or(Eq(Field("name"), Const("alice")), Eq(Field("name"), Const("bob")))
        with pytest.raises(ValueError, match="OR filters not supported"):
            enc.encode(expr, User, None)

    def test_custom_separator(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import QueryParamFilters
        from emergent.wire.axis.query._expr import Lt, Field, Const

        enc = QueryParamFilters(operator_sep=".")
        result = enc.encode(Lt(Field("balance"), Const(100)), User, None)
        assert result == {"balance.lt": 100}


class TestBodyFilters:
    def test_eq_filter_body(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import BodyFilters
        from emergent.wire.axis.query._expr import Eq, Field, Const

        enc = BodyFilters()
        result = enc.encode(Eq(Field("name"), Const("alice")), User, None)
        assert result == {"filter": {"name": {"eq": "alice"}}}

    def test_and_filter_body(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import BodyFilters
        from emergent.wire.axis.query._expr import And, Eq, Gt, Field, Const

        enc = BodyFilters()
        expr = And(Eq(Field("name"), Const("alice")), Gt(Field("balance"), Const(100)))
        result = enc.encode(expr, User, None)
        assert result == {
            "filter": {
                "and": [
                    {"name": {"eq": "alice"}},
                    {"balance": {"gt": 100}},
                ]
            }
        }

    def test_or_filter_body(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import BodyFilters
        from emergent.wire.axis.query._expr import Or, Eq, Field, Const

        enc = BodyFilters()
        expr = Or(Eq(Field("name"), Const("alice")), Eq(Field("name"), Const("bob")))
        result = enc.encode(expr, User, None)
        assert result == {
            "filter": {
                "or": [
                    {"name": {"eq": "alice"}},
                    {"name": {"eq": "bob"}},
                ]
            }
        }

    def test_in_filter_body(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import BodyFilters
        from emergent.wire.axis.query._expr import In, Field

        enc = BodyFilters()
        result = enc.encode(In(Field("id"), (1, 2, 3)), User, None)
        assert result == {"filter": {"id": {"in": [1, 2, 3]}}}


# ═══════════════════════════════════════════════════════════════════════════════
# HTTP Contrib — Order/Limit/Select Encoding
# ═══════════════════════════════════════════════════════════════════════════════


class TestSortParamEncoding:
    def test_ascending_and_descending(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import SortParamEncoding
        from emergent.wire.axis.query._proxy import OrderSpec

        enc = SortParamEncoding()
        result = enc.encode([
            OrderSpec("name", ascending=True),
            OrderSpec("balance", ascending=False),
        ])
        assert result == {"sort": "name,-balance"}

    def test_empty_specs(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import SortParamEncoding

        enc = SortParamEncoding()
        assert enc.encode([]) == {}

    def test_custom_param_and_prefixes(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import SortParamEncoding
        from emergent.wire.axis.query._proxy import OrderSpec

        enc = SortParamEncoding(param="order", desc_prefix="desc:", asc_prefix="asc:", separator=";")
        result = enc.encode([OrderSpec("name", ascending=True)])
        assert result == {"order": "asc:name"}


class TestLimitParamEncoding:
    def test_encode_limit(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import LimitParamEncoding

        enc = LimitParamEncoding()
        assert enc.encode(50) == {"limit": 50}


class TestFieldsParamEncoding:
    def test_encode_fields(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import FieldsParamEncoding

        enc = FieldsParamEncoding()
        assert enc.encode(["id", "name", "email"]) == {"fields": "id,name,email"}


# ═══════════════════════════════════════════════════════════════════════════════
# HTTP Contrib — Builder
# ═══════════════════════════════════════════════════════════════════════════════


class TestHTTPAPIBuilder:
    def test_builder_requires_base_url(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import HTTPAPIBuilder

        builder = HTTPAPIBuilder(User)
        with pytest.raises(ValueError, match="base URL is required"):
            builder.build(None)  # type: ignore[arg-type]

    def test_builder_strips_trailing_slash(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import HTTPAPIBuilder

        builder = HTTPAPIBuilder(User).base("https://api.example.com/users/")
        provider = builder.build(None)  # type: ignore[arg-type]
        assert provider.base_url == "https://api.example.com/users"

    def test_builder_chain(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import (
            HTTPAPIBuilder,
            BearerAuth,
            CursorPagination,
        )

        builder = (
            HTTPAPIBuilder(User)
            .base("https://api.example.com/users")
            .auth(BearerAuth("tok"))
            .pagination(CursorPagination())
            .response(data_path="results", total_path="count")
            .id_field("user_id")
        )
        provider = builder.build(None)  # type: ignore[arg-type]
        assert provider.base_url == "https://api.example.com/users"
        assert isinstance(provider.auth, BearerAuth)
        assert isinstance(provider.pagination, CursorPagination)
        assert provider.data_path == "results"
        assert provider.total_path == "count"
        assert provider.id_field == "user_id"


class TestGetNested:
    def test_simple_path(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import _get_nested

        data = {"data": [1, 2, 3]}
        assert _get_nested(data, "data") == [1, 2, 3]

    def test_nested_path(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import _get_nested

        data = {"response": {"items": [1, 2]}}
        assert _get_nested(data, "response.items") == [1, 2]

    def test_missing_path(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import _get_nested

        data = {"data": [1]}
        assert _get_nested(data, "missing.path") is None


# ═══════════════════════════════════════════════════════════════════════════════
# Memory API Provider
# ═══════════════════════════════════════════════════════════════════════════════


class TestMemoryAPIProvider:
    @pytest.fixture()
    def provider(self) -> MemoryAPIProvider[int, User]:
        from emergent.wire.axis.query.providers.memory import MemoryAPIProvider

        return MemoryAPIProvider[int, User](
            data=[
                User(id=1, name="alice", balance=100.0),
                User(id=2, name="bob", balance=200.0),
                User(id=3, name="charlie", balance=50.0),
                User(id=4, name="diana", balance=300.0, active=False),
                User(id=5, name="eve", balance=150.0),
            ],
            key_fn=lambda u: u.id,
        )

    @pytest.mark.asyncio()
    async def test_fetch_one_get_op(self, provider: MemoryAPIProvider[int, User]) -> None:
        from emergent.wire.axis.query._api import api

        users = api(User, key=lambda u: u.id)
        result = await provider.fetch_one(users.get(2))
        assert result is not None
        assert result.name == "bob"

    @pytest.mark.asyncio()
    async def test_fetch_one_get_op_not_found(self, provider: MemoryAPIProvider[int, User]) -> None:
        from emergent.wire.axis.query._api import api

        users = api(User, key=lambda u: u.id)
        result = await provider.fetch_one(users.get(999))
        assert result is None

    @pytest.mark.asyncio()
    async def test_fetch_one_list_op(self, provider: MemoryAPIProvider[int, User]) -> None:
        from emergent.wire.axis.query._api import api

        users = api(User, key=lambda u: u.id)
        result = await provider.fetch_one(users.list())
        assert result is not None
        assert result.name == "alice"

    @pytest.mark.asyncio()
    async def test_fetch_many(self, provider: MemoryAPIProvider[int, User]) -> None:
        from emergent.wire.axis.query._api import api

        users = api(User, key=lambda u: u.id)
        results = await provider.fetch_many(users.list())
        assert len(results) == 5

    @pytest.mark.asyncio()
    async def test_fetch_many_with_filter(self, provider: MemoryAPIProvider[int, User]) -> None:
        from emergent.wire.axis.query._api import api

        users = api(User, key=lambda u: u.id)
        q = users.list().filter(lambda u: u.active == True)  # noqa: E712
        results = await provider.fetch_many(q)
        assert len(results) == 4
        assert all(u.active for u in results)

    @pytest.mark.asyncio()
    async def test_fetch_page(self, provider: MemoryAPIProvider[int, User]) -> None:
        from emergent.wire.axis.query._api import api

        users = api(User, key=lambda u: u.id)
        q = users.list().page(1, per_page=2)
        result = await provider.fetch_page(q)
        assert len(result.items) == 2
        assert result.total == 5
        assert result.has_more is True

    @pytest.mark.asyncio()
    async def test_fetch_page_last(self, provider: MemoryAPIProvider[int, User]) -> None:
        from emergent.wire.axis.query._api import api

        users = api(User, key=lambda u: u.id)
        q = users.list().page(3, per_page=2)
        result = await provider.fetch_page(q)
        assert len(result.items) == 1
        assert result.has_more is False

    @pytest.mark.asyncio()
    async def test_execute_create(self, provider: MemoryAPIProvider[int, User]) -> None:
        from emergent.wire.axis.query._api import api

        users = api(User, key=lambda u: u.id)
        new_user = User(id=6, name="frank", balance=500.0)
        result = await provider.execute(users.create(new_user))
        assert result.name == "frank"
        assert len(provider.data) == 6

    @pytest.mark.asyncio()
    async def test_execute_update(self, provider: MemoryAPIProvider[int, User]) -> None:
        from emergent.wire.axis.query._api import api

        users = api(User, key=lambda u: u.id)
        updated = User(id=1, name="alice_updated", balance=999.0)
        result = await provider.execute(users.update(1, updated))
        assert result.name == "alice_updated"

    @pytest.mark.asyncio()
    async def test_execute_partial_update(self, provider: MemoryAPIProvider[int, User]) -> None:
        from emergent.wire.axis.query._api import api

        users = api(User, key=lambda u: u.id)
        partial = User(id=1, name="alice_partial", balance=0.0, active=True, department="eng")
        result = await provider.execute(users.update(1, partial, partial=True))
        # Partial update merges non-None fields
        assert result.name == "alice_partial"

    @pytest.mark.asyncio()
    async def test_delete(self, provider: MemoryAPIProvider[int, User]) -> None:
        from emergent.wire.axis.query._api import api

        users = api(User, key=lambda u: u.id)
        result = await provider.delete(users.delete(1))
        assert result is True
        assert len(provider.data) == 4

    @pytest.mark.asyncio()
    async def test_delete_nonexistent(self, provider: MemoryAPIProvider[int, User]) -> None:
        from emergent.wire.axis.query._api import api

        users = api(User, key=lambda u: u.id)
        result = await provider.delete(users.delete(999))
        assert result is False

    @pytest.mark.asyncio()
    async def test_next_id_raises_without_config(self, provider: MemoryAPIProvider[int, User]) -> None:
        with pytest.raises(RuntimeError, match="No next_id generator configured"):
            await provider.next_id()

    @pytest.mark.asyncio()
    async def test_next_id_with_sequence(self) -> None:
        from emergent.wire.axis.query.providers.memory import MemoryAPIProvider
        from emergent.wire.axis.query._provider import SequenceNextId

        provider = MemoryAPIProvider[int, User](
            key_fn=lambda u: u.id,
            next_id=SequenceNextId(),
        )
        id1 = await provider.next_id()
        id2 = await provider.next_id()
        assert id1 == 1
        assert id2 == 2

    @pytest.mark.asyncio()
    async def test_fetch_many_wrong_op_raises(self, provider: MemoryAPIProvider[int, User]) -> None:
        from emergent.wire.axis.query._api import api

        users = api(User, key=lambda u: u.id)
        with pytest.raises(TypeError, match="fetch_many.*ListOp"):
            await provider.fetch_many(users.get(1))

    @pytest.mark.asyncio()
    async def test_execute_wrong_op_raises(self, provider: MemoryAPIProvider[int, User]) -> None:
        from emergent.wire.axis.query._api import api

        users = api(User, key=lambda u: u.id)
        with pytest.raises(TypeError, match="execute.*CreateOp or UpdateOp"):
            await provider.execute(users.list())

    @pytest.mark.asyncio()
    async def test_delete_wrong_op_raises(self, provider: MemoryAPIProvider[int, User]) -> None:
        from emergent.wire.axis.query._api import api

        users = api(User, key=lambda u: u.id)
        with pytest.raises(TypeError, match="delete.*DeleteOp"):
            await provider.delete(users.list())

    @pytest.mark.asyncio()
    async def test_fetch_page_with_cursor(self, provider: MemoryAPIProvider[int, User]) -> None:
        from emergent.wire.axis.query._api import api

        users = api(User, key=lambda u: u.id)
        q = users.list().cursor("2", limit=2)
        result = await provider.fetch_page(q)
        assert len(result.items) == 2
        assert result.has_more is True

    @pytest.mark.asyncio()
    async def test_search_mod(self, provider: MemoryAPIProvider[int, User]) -> None:
        from emergent.wire.axis.query._api import api

        users = api(User, key=lambda u: u.id)
        q = users.list().search("ali")
        results = await provider.fetch_many(q)
        assert len(results) == 1
        assert results[0].name == "alice"


# ═══════════════════════════════════════════════════════════════════════════════
# resolve.py — unwrap/wrap for Option, Result types
# ═══════════════════════════════════════════════════════════════════════════════


class TestUnwrap:
    def test_unwrap_plain_type(self) -> None:
        from emergent.wire.axis.surface.codecs.resolve import unwrap

        inner, is_opt = unwrap(int)
        assert inner is int
        assert is_opt is False

    def test_unwrap_option(self) -> None:
        from emergent.wire.axis.surface.codecs.resolve import unwrap

        inner, is_opt = unwrap(Option[str])
        assert inner is str
        assert is_opt is True

    def test_unwrap_result(self) -> None:
        from emergent.wire.axis.surface.codecs.resolve import unwrap

        inner, is_opt = unwrap(Result[int, str])
        assert inner is int
        assert is_opt is True


class TestWrap:
    def test_wrap_plain_success(self) -> None:
        from emergent.wire.axis.surface.codecs.resolve import wrap

        assert wrap(int, True, 42) == 42

    def test_wrap_plain_failure_raises(self) -> None:
        from emergent.wire.axis.surface.codecs.resolve import wrap

        with pytest.raises(RuntimeError, match="Required param failed"):
            wrap(int, False, "error")

    def test_wrap_option_success(self) -> None:
        from emergent.wire.axis.surface.codecs.resolve import wrap

        result = wrap(Option[str], True, "hello")
        assert isinstance(result, Some)
        assert result.unwrap() == "hello"

    def test_wrap_option_failure(self) -> None:
        from emergent.wire.axis.surface.codecs.resolve import wrap

        result = wrap(Option[str], False, "err")
        assert isinstance(result, Nothing)

    def test_wrap_result_success(self) -> None:
        from emergent.wire.axis.surface.codecs.resolve import wrap

        result = wrap(Result[int, str], True, 42)
        assert isinstance(result, Ok)

    def test_wrap_result_failure(self) -> None:
        from emergent.wire.axis.surface.codecs.resolve import wrap

        result = wrap(Result[int, str], False, "error")
        assert isinstance(result, Error)


class TestGetMethodParams:
    def test_get_method_params_basic(self) -> None:
        from emergent.wire.axis.surface.codecs.resolve import get_method_params

        async def my_method(self: object, x: int, y: str) -> None:
            pass

        params = get_method_params(my_method)
        assert "x" in params
        assert "y" in params
        assert "self" not in params
        assert "return" not in params
        # x is plain int
        _orig_x, compose_x = params["x"]
        assert compose_x is int

    def test_get_method_params_with_option(self) -> None:
        from emergent.wire.axis.surface.codecs.resolve import get_method_params

        async def my_method(self: object, token: Option[str]) -> None:
            pass

        params = get_method_params(my_method)
        assert "token" in params
        _orig, compose = params["token"]
        assert compose is str

    def test_get_transition_params_no_transition(self) -> None:
        from emergent.wire.axis.surface.codecs.resolve import get_transition_params

        class NoTransition:
            pass

        assert get_transition_params(NoTransition) == {}


# ═══════════════════════════════════════════════════════════════════════════════
# Surface Explain — edge cases
# ═══════════════════════════════════════════════════════════════════════════════


class TestExplainEdgeCases:
    def test_unknown_trigger_fallback(self) -> None:
        from emergent.wire.axis.surface._explain import _explain_obj, SURFACE_EXPLAIN

        @dataclass(frozen=True, slots=True)
        class CustomTrigger:
            name: str

        result = _explain_obj(CustomTrigger(name="test"), SURFACE_EXPLAIN)
        assert result["type"] == "CustomTrigger"
        assert result["name"] == "test"

    def test_explain_event_trigger(self) -> None:
        from emergent.wire.axis.surface._explain import _explain_obj, SURFACE_EXPLAIN
        from emergent.wire.axis.surface.triggers.event import EventTrigger

        class MyEvent:
            pass

        result = _explain_obj(EventTrigger(MyEvent), SURFACE_EXPLAIN)
        assert result == {"type": "EventTrigger", "event_type": "MyEvent"}

    def test_explain_cli_trigger_with_description(self) -> None:
        from emergent.wire.axis.surface._explain import _explain_obj, SURFACE_EXPLAIN
        from emergent.wire.axis.surface.triggers.cli import CLITrigger

        result = _explain_obj(CLITrigger(command="scan", description="Scan path"), SURFACE_EXPLAIN)
        assert result["type"] == "CLITrigger"
        assert result["command"] == "scan"
        assert result["description"] == "Scan path"

    def test_explain_http_trigger_with_headers(self) -> None:
        from emergent.wire.axis.surface._explain import _explain_obj, SURFACE_EXPLAIN
        from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger

        trigger = HTTPRouteTrigger(method="GET", path="/users", headers=frozenset({"X-Custom"}))
        result = _explain_obj(trigger, SURFACE_EXPLAIN)
        assert result["type"] == "HTTPRouteTrigger"
        assert "X-Custom" in result["headers"]

    def test_format_trigger_short_variants(self) -> None:
        from emergent.wire.axis.surface._explain import _format_trigger_short

        assert "GET /users" == _format_trigger_short({"type": "HTTPRouteTrigger", "method": "GET", "path": "/users"})
        assert "(cli)" in _format_trigger_short({"type": "CLITrigger", "command": "scan"})
        assert "tg:" in _format_trigger_short({"type": "TelegrinderTrigger", "view": "message", "rules": ["CommandRule"]})
        assert "Event" in _format_trigger_short({"type": "EventTrigger", "event_type": "OrderCreated"})
        # Unknown trigger type
        unknown_result = _format_trigger_short({"type": "CustomTrigger", "foo": "bar"})
        assert "CustomTrigger" in unknown_result

    def test_explain_immediate_codec(self) -> None:
        from emergent.wire.axis.surface._explain import _explain_obj, SURFACE_EXPLAIN
        from emergent.wire.axis.surface.codecs.immediate import ImmediateCodec

        class MyResponse:
            @classmethod
            def produce(cls) -> "MyResponse":
                return cls()

        codec = ImmediateCodec(response=MyResponse)
        result = _explain_obj(codec, SURFACE_EXPLAIN)
        assert result["type"] == "ImmediateCodec"
        assert result["response"] == "MyResponse"

    def test_explain_delegate_codec(self) -> None:
        from emergent.wire.axis.surface._explain import _explain_obj, SURFACE_EXPLAIN
        from emergent.wire.axis.surface.codecs.delegate import DelegateCodec

        def my_handler() -> None:
            pass

        codec = DelegateCodec(handler=my_handler)
        result = _explain_obj(codec, SURFACE_EXPLAIN)
        assert result["type"] == "DelegateCodec"
        assert "my_handler" in result["handler"]

    def test_format_value_sequence(self) -> None:
        from emergent.wire.axis.surface._explain import _format_value

        assert _format_value([1, 2, 3]) == "1, 2, 3"
        assert _format_value(("a", "b")) == "a, b"

    def test_format_value_scalar(self) -> None:
        from emergent.wire.axis.surface._explain import _format_value

        assert _format_value("hello") == "'hello'"
        assert _format_value(42) == "42"


# ═══════════════════════════════════════════════════════════════════════════════
# HTTP Dialect — Capability Compilation
# ═══════════════════════════════════════════════════════════════════════════════


class TestHTTPDialectCapabilities:
    def test_summary_compile(self) -> None:
        from emergent.wire.axis.surface.dialects.http import Summary
        from emergent.wire.axis._capability import FastAPIRouteContext

        cap = Summary.of("List all users", "Returns paginated user list")
        ctx = FastAPIRouteContext(path="/users", method="GET")
        result = cap.compile_fastapi_route(ctx)
        assert result.summary == "List all users"
        assert result.description == "Returns paginated user list"

    def test_operation_id_compile(self) -> None:
        from emergent.wire.axis.surface.dialects.http import OperationId
        from emergent.wire.axis._capability import FastAPIRouteContext

        cap = OperationId.of("listUsers")
        ctx = FastAPIRouteContext(path="/users", method="GET")
        result = cap.compile_fastapi_route(ctx)
        assert result.operation_id == "listUsers"

    def test_deprecated_compile(self) -> None:
        from emergent.wire.axis.surface.dialects.http import Deprecated
        from emergent.wire.axis._capability import FastAPIRouteContext

        cap = Deprecated.because("Use /v2/users instead")
        ctx = FastAPIRouteContext(path="/users", method="GET")
        result = cap.compile_fastapi_route(ctx)
        assert result.deprecated is True
        assert cap.reason == "Use /v2/users instead"

    def test_deprecated_until(self) -> None:
        from emergent.wire.axis.surface.dialects.http import Deprecated

        cap = Deprecated.until("2025-01-01", "Migrating to v2 API")
        assert cap.sunset_date == "2025-01-01"
        assert cap.reason == "Migrating to v2 API"

    def test_response_status_compile(self) -> None:
        from emergent.wire.axis.surface.dialects.http import ResponseStatus
        from emergent.wire.axis._capability import FastAPIRouteContext

        cap = ResponseStatus(201)
        ctx = FastAPIRouteContext(path="/users", method="POST")
        result = cap.compile_fastapi_route(ctx)
        assert result.status_code == 201

    def test_response_header_compile(self) -> None:
        from emergent.wire.axis.surface.dialects.http import ResponseHeader
        from emergent.wire.axis._capability import FastAPIRouteContext

        cap = ResponseHeader("X-Request-Id", "Unique request identifier", schema_type="string")
        ctx = FastAPIRouteContext(path="/users", method="GET")
        result = cap.compile_fastapi_route(ctx)
        assert result.openapi_extra is not None
        assert "responses" in result.openapi_extra

    def test_content_type_compile(self) -> None:
        from emergent.wire.axis.surface.dialects.http import ContentType
        from emergent.wire.axis._capability import FastAPIRouteContext

        cap = ContentType("text/csv")
        ctx = FastAPIRouteContext(path="/export", method="GET")
        result = cap.compile_fastapi_route(ctx)
        assert result.openapi_extra is not None
        responses = result.openapi_extra["responses"]
        assert "text/csv" in responses["200"]["content"]


# ═══════════════════════════════════════════════════════════════════════════════
# Telegram Dialect — Capability Compilation
# ═══════════════════════════════════════════════════════════════════════════════


class TestTelegramDialectCapabilities:
    def test_help_meta_fields(self) -> None:
        from emergent.wire.axis.surface.dialects.telegram import HelpMeta

        meta = HelpMeta(description="Register new account", order=1, hidden=False)
        assert meta.description == "Register new account"
        assert meta.order == 1
        assert meta.hidden is False

    def test_help_meta_defaults(self) -> None:
        from emergent.wire.axis.surface.dialects.telegram import HelpMeta

        meta = HelpMeta(description="Help")
        assert meta.order == 100
        assert meta.hidden is False

    def test_silent_compile(self) -> None:
        from emergent.wire.axis.surface.dialects.telegram import Silent
        from emergent.wire.axis._capability import TelegrinderHandlerContext

        cap = Silent()
        ctx = TelegrinderHandlerContext()
        result = cap.compile_telegrinder(ctx)
        assert result.silent is True

    def test_parse_mode_compile(self) -> None:
        from emergent.wire.axis.surface.dialects.telegram import ParseMode
        from emergent.wire.axis._capability import TelegrinderHandlerContext

        cap = ParseMode(mode="HTML")
        ctx = TelegrinderHandlerContext()
        result = cap.compile_telegrinder(ctx)
        assert result.parse_mode == "HTML"

    def test_link_preview_compile(self) -> None:
        from emergent.wire.axis.surface.dialects.telegram import LinkPreview
        from emergent.wire.axis._capability import TelegrinderHandlerContext

        cap = LinkPreview(disabled=True)
        ctx = TelegrinderHandlerContext()
        result = cap.compile_telegrinder(ctx)
        assert result.link_preview_disabled is True

    def test_protect_content_compile(self) -> None:
        from emergent.wire.axis.surface.dialects.telegram import ProtectContent
        from emergent.wire.axis._capability import TelegrinderHandlerContext

        cap = ProtectContent()
        ctx = TelegrinderHandlerContext()
        result = cap.compile_telegrinder(ctx)
        assert result.protect_content is True

    def test_edit_message_compile(self) -> None:
        from emergent.wire.axis.surface.dialects.telegram import EditMessage
        from emergent.wire.axis._capability import TelegrinderHandlerContext

        cap = EditMessage()
        ctx = TelegrinderHandlerContext()
        result = cap.compile_telegrinder(ctx)
        assert result.edit_message is True

    def test_answer_callback_compile(self) -> None:
        from emergent.wire.axis.surface.dialects.telegram import AnswerCallback
        from emergent.wire.axis._capability import TelegrinderHandlerContext

        cap = AnswerCallback(text="Processing", show_alert=True, cache_time=10)
        ctx = TelegrinderHandlerContext()
        result = cap.compile_telegrinder(ctx)
        assert result.answer_callback is True
        assert result.answer_callback_text == "Processing"
        assert result.answer_callback_show_alert is True


# ═══════════════════════════════════════════════════════════════════════════════
# SQL QuerySet
# ═══════════════════════════════════════════════════════════════════════════════


class TestSQLRelationalQuerySet:
    def test_sql_relational_creates_empty_qs(self) -> None:
        from emergent.wire.axis.query._sql import sql_relational

        qs = sql_relational(User)
        assert qs.entity is User
        assert qs.ops == ()

    def test_for_update(self) -> None:
        from emergent.wire.axis.query._sql import sql_relational, ForUpdate

        qs = sql_relational(User).for_update(nowait=True)
        assert qs.has_for_update is True
        fu = [op for op in qs.ops if isinstance(op, ForUpdate)]
        assert len(fu) == 1
        assert fu[0].nowait is True
        assert fu[0].skip_locked is False

    def test_for_update_skip_locked(self) -> None:
        from emergent.wire.axis.query._sql import sql_relational, ForUpdate

        qs = sql_relational(User).for_update(skip_locked=True)
        fu = [op for op in qs.ops if isinstance(op, ForUpdate)][0]
        assert fu.skip_locked is True

    def test_returning(self) -> None:
        from emergent.wire.axis.query._sql import sql_relational, Returning

        qs = sql_relational(User).returning("id", "name")
        assert qs.has_returning is True
        ret = [op for op in qs.ops if isinstance(op, Returning)][0]
        assert ret.fields == ("id", "name")

    def test_returning_all(self) -> None:
        from emergent.wire.axis.query._sql import sql_relational

        qs = sql_relational(User).returning()
        assert qs.has_returning is True

    def test_to_relational_strips_sql_ops(self) -> None:
        from emergent.wire.axis.query._sql import sql_relational

        qs = (
            sql_relational(User)
            .filter(lambda u: u.active == True)  # noqa: E712
            .for_update()
            .returning("id")
        )
        rqs = qs.to_relational()
        # Should not contain ForUpdate or Returning
        from emergent.wire.axis.query._sql import ForUpdate, Returning, Window

        for op in rqs.ops:
            assert not isinstance(op, (ForUpdate, Returning, Window))
        # Should still have the filter
        assert len(rqs.ops) == 1  # just the Filter

    def test_has_windows_false_initially(self) -> None:
        from emergent.wire.axis.query._sql import sql_relational

        qs = sql_relational(User)
        assert qs.has_windows is False
        assert qs.windows == []

    def test_window_builder_over(self) -> None:
        from emergent.wire.axis.query._sql import WindowBuilder
        from emergent.wire.axis.query._aggregate import Count
        from emergent.wire.axis.query._proxy import FieldProxy, OrderSpec

        builder = WindowBuilder(func=Count(), field=None)
        spec = builder.over(
            partition_by=FieldProxy("department"),
            order_by=OrderSpec("salary", ascending=False),
        )
        assert spec.partition_by == ("department",)
        assert spec.order_by == (OrderSpec("salary", ascending=False),)

    def test_window_builder_over_tuple_partition(self) -> None:
        from emergent.wire.axis.query._sql import WindowBuilder
        from emergent.wire.axis.query._aggregate import Count
        from emergent.wire.axis.query._proxy import FieldProxy

        builder = WindowBuilder(func=Count(), field=None)
        spec = builder.over(
            partition_by=(FieldProxy("dept"), FieldProxy("team")),
        )
        assert spec.partition_by == ("dept", "team")

    def test_window_builder_over_field_proxy_order(self) -> None:
        from emergent.wire.axis.query._sql import WindowBuilder
        from emergent.wire.axis.query._aggregate import Count
        from emergent.wire.axis.query._proxy import FieldProxy, OrderSpec

        builder = WindowBuilder(func=Count(), field=None)
        spec = builder.over(order_by=FieldProxy("salary"))
        assert spec.order_by == (OrderSpec("salary", ascending=True),)

    def test_window_builder_invalid_order_type_raises(self) -> None:
        from emergent.wire.axis.query._sql import WindowBuilder
        from emergent.wire.axis.query._aggregate import Count

        builder = WindowBuilder(func=Count(), field=None)
        with pytest.raises(TypeError, match="order_by expects"):
            builder.over(order_by="invalid")  # type: ignore[arg-type]


# ═══════════════════════════════════════════════════════════════════════════════
# _generate.py — DataNode generation
# ═══════════════════════════════════════════════════════════════════════════════


class TestToDatanode:
    def test_to_datanode_creates_node_class(self) -> None:
        from emergent.wire.compile._generate import to_datanode

        @dataclass
        class SimpleRequest:
            name: str
            age: int

        # Minimal compose_from mapping
        Node = to_datanode(SimpleRequest, compose_from={})
        assert Node.__name__ == "SimpleRequestNode"

    def test_to_datanode_with_compose_from(self) -> None:
        from emergent.wire.compile._generate import to_datanode

        @dataclass
        class MsgReq:
            text: str

        class TextNode:
            pass

        Node = to_datanode(MsgReq, compose_from={"text": TextNode})
        assert Node.__name__ == "MsgReqNode"
        assert issubclass(Node, MsgReq)

    def test_to_datanode_auto(self) -> None:
        from emergent.wire.compile._generate import to_datanode_auto

        @dataclass
        class AutoReq:
            value: int

        class IntNode:
            pass

        registry = {int: IntNode}
        Node = to_datanode_auto(AutoReq, node_registry=registry)
        assert Node.__name__ == "AutoReqNode"


class TestArgSpec:
    def test_argspec_fields(self) -> None:
        from emergent.wire.compile._generate import ArgSpec

        spec = ArgSpec(name="--output", dest="output", kwargs={"help": "Output path"}, is_positional=False)
        assert spec.name == "--output"
        assert spec.dest == "output"
        assert spec.kwargs["help"] == "Output path"
        assert spec.is_positional is False

    def test_argspec_positional(self) -> None:
        from emergent.wire.compile._generate import ArgSpec

        spec = ArgSpec(name="input", dest="input", kwargs={}, is_positional=True)
        assert spec.is_positional is True


# ═══════════════════════════════════════════════════════════════════════════════
# NextId providers
# ═══════════════════════════════════════════════════════════════════════════════


class TestNextIdProviders:
    @pytest.mark.asyncio()
    async def test_sequence_next_id(self) -> None:
        from emergent.wire.axis.query._provider import SequenceNextId

        gen = SequenceNextId(start=10)
        assert await gen.next_id() == 10
        assert await gen.next_id() == 11

    @pytest.mark.asyncio()
    async def test_uuid_next_id(self) -> None:
        from emergent.wire.axis.query._provider import UuidNextId

        gen = UuidNextId()
        id1 = await gen.next_id()
        id2 = await gen.next_id()
        assert isinstance(id1, str)
        assert len(id1) == 36  # UUID format
        assert id1 != id2

    @pytest.mark.asyncio()
    async def test_prefixed_next_id(self) -> None:
        from emergent.wire.axis.query._provider import PrefixedNextId, SequenceNextId

        gen = PrefixedNextId("tx_", SequenceNextId())
        assert await gen.next_id() == "tx_1"
        assert await gen.next_id() == "tx_2"

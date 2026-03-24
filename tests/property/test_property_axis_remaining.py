# pyright: reportPrivateUsage=false
"""Remaining coverage for axis modules, derive transforms/auth, and contrib.

Covers uncovered code paths in:
  - HTTP contrib: pagination strategies, auth, filter encoding, provider methods
  - TG dialect: compile_telegrinder methods, enricher paths
  - Memory provider: partial update, cursor pagination, include mod, aggregation
  - Codec resolve: unwrap/wrap branches for Option/Result
  - Derive transforms: Paginated, Sorted, Readonly, MutationsOnly, etc.
  - Auth caps: Authenticated, RoleRequired, AuthorizeOps, OwnerScoped
  - Auth login: token_converter, IssueToken, LoginOp
  - HTTP dialect: Tag, BearerAuth, OAuth2Auth, Summary, etc.
  - Delta dialect: delta_type, apply_delta, compose_deltas, validate_delta
  - Temporal dialect: temporal filter helpers, compile methods
  - Proxy: json, regex, array ops
  - Store: RelationalStore, KVStore, APIStore methods
  - Storage explain: explain_storage, storage_dict
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Annotated, Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from emergent.wire.axis.query._store import (
    APIStore,
    BoundAPIQuerySet,
    BoundRelationalQuerySet,
    KVStore,
    RelationalStore,
)
from emergent.wire.axis.query.providers.memory import (
    MemoryAPIProvider,
    MemoryKVProvider,
    MemoryRelationalProvider,
)
from emergent.wire.axis.schema import Identity
from emergent.wire.axis.schema.dialects.delta import DeltaField


# ═══════════════════════════════════════════════════════════════════════════════
# Shared test entities
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class User:
    id: Annotated[int, Identity()]
    name: str
    email: str
    balance: int = 0
    active: bool = True
    deleted_at: str | None = None


@dataclass
class Article:
    id: Annotated[int, Identity()]
    title: str
    body: str
    author_id: int


@dataclass
class _DeltaAccount:
    id: int
    balance: Annotated[int, DeltaField("numeric")]


# ═══════════════════════════════════════════════════════════════════════════════
# 1. HTTP API contrib — pagination strategies
# ═══════════════════════════════════════════════════════════════════════════════


class TestPageSizePagination:
    def test_apply_page_mod(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import PageSizePagination
        from emergent.wire.axis.query._api import PageMod

        pag = PageSizePagination()
        params: dict[str, Any] = {}
        pag.apply(params, PageMod(page=3, per_page=25))
        assert params == {"page": 3, "per_page": 25}

    def test_apply_offset_mod_converts_to_page(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import PageSizePagination
        from emergent.wire.axis.query._api import OffsetMod

        pag = PageSizePagination()
        params: dict[str, Any] = {}
        pag.apply(params, OffsetMod(offset=40, limit=20))
        assert params == {"page": 3, "per_page": 20}

    def test_custom_param_names(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import page_size
        from emergent.wire.axis.query._api import PageMod

        pag = page_size(page="p", size="sz")
        params: dict[str, Any] = {}
        pag.apply(params, PageMod(page=2, per_page=10))
        assert params == {"p": 2, "sz": 10}


class TestOffsetLimitPagination:
    def test_apply_offset_mod(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import OffsetLimitPagination
        from emergent.wire.axis.query._api import OffsetMod

        pag = OffsetLimitPagination()
        params: dict[str, Any] = {}
        pag.apply(params, OffsetMod(offset=20, limit=10))
        assert params == {"offset": 20, "limit": 10}

    def test_apply_page_mod_converts_to_offset(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import OffsetLimitPagination
        from emergent.wire.axis.query._api import PageMod

        pag = OffsetLimitPagination()
        params: dict[str, Any] = {}
        pag.apply(params, PageMod(page=3, per_page=10))
        assert params == {"offset": 20, "limit": 10}

    def test_custom_param_names(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import offset_limit
        from emergent.wire.axis.query._api import OffsetMod

        pag = offset_limit(offset="skip", limit="take")
        params: dict[str, Any] = {}
        pag.apply(params, OffsetMod(offset=5, limit=15))
        assert params == {"skip": 5, "take": 15}


class TestCursorPagination:
    def test_apply_cursor_mod(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import CursorPagination
        from emergent.wire.axis.query._api import CursorMod

        pag = CursorPagination()
        params: dict[str, Any] = {}
        pag.apply(params, CursorMod(cursor="abc123", limit=50))
        assert params == {"cursor": "abc123", "limit": 50}

    def test_apply_cursor_mod_no_cursor(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import cursor
        from emergent.wire.axis.query._api import CursorMod

        pag = cursor()
        params: dict[str, Any] = {}
        pag.apply(params, CursorMod(cursor="", limit=10))
        assert "cursor" not in params
        assert params["limit"] == 10


# ═══════════════════════════════════════════════════════════════════════════════
# 2. HTTP API contrib — auth strategies
# ═══════════════════════════════════════════════════════════════════════════════


class TestAuthStrategies:
    def test_bearer_auth(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import bearer

        auth = bearer("my-token")
        headers: dict[str, str] = {}
        auth.apply(headers)
        assert headers["Authorization"] == "Bearer my-token"

    def test_api_key_auth(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import api_key

        auth = api_key("secret-key", header="X-Custom-Key")
        headers: dict[str, str] = {}
        auth.apply(headers)
        assert headers["X-Custom-Key"] == "secret-key"

    def test_basic_auth(self) -> None:
        import base64
        from emergent.wire.axis.query.contrib._impls._http import basic

        auth = basic("admin", "password123")
        headers: dict[str, str] = {}
        auth.apply(headers)
        expected = base64.b64encode(b"admin:password123").decode()
        assert headers["Authorization"] == f"Basic {expected}"


# ═══════════════════════════════════════════════════════════════════════════════
# 3. HTTP API contrib — filter encoding
# ═══════════════════════════════════════════════════════════════════════════════


class TestQueryParamFilters:
    def test_encode_eq(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import query_params
        from emergent.wire.axis.query._expr import Eq, Field, Const

        enc = query_params()
        result = enc.encode(Eq(Field("name"), Const("alice")), User, None)
        assert result == {"name": "alice"}

    def test_encode_ne(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import QueryParamFilters
        from emergent.wire.axis.query._expr import Ne, Field, Const

        enc = QueryParamFilters()
        result = enc.encode(Ne(Field("status"), Const("inactive")), User, None)
        assert result == {"status__ne": "inactive"}

    def test_encode_lt_le_gt_ge(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import QueryParamFilters
        from emergent.wire.axis.query._expr import Lt, Le, Gt, Ge, Field, Const

        enc = QueryParamFilters()
        assert enc.encode(Lt(Field("age"), Const(30)), User, None) == {"age__lt": 30}
        assert enc.encode(Le(Field("age"), Const(30)), User, None) == {"age__lte": 30}
        assert enc.encode(Gt(Field("age"), Const(18)), User, None) == {"age__gt": 18}
        assert enc.encode(Ge(Field("age"), Const(18)), User, None) == {"age__gte": 18}

    def test_encode_in(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import QueryParamFilters
        from emergent.wire.axis.query._expr import In, Field

        enc = QueryParamFilters()
        result = enc.encode(In(Field("status"), ("a", "b")), User, None)
        assert result == {"status__in": "a,b"}

    def test_encode_contains_startswith_endswith(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import QueryParamFilters
        from emergent.wire.axis.query._expr import Contains, StartsWith, EndsWith, Field

        enc = QueryParamFilters()
        assert enc.encode(Contains(Field("name"), "ice"), User, None) == {"name__contains": "ice"}
        assert enc.encode(StartsWith(Field("name"), "al"), User, None) == {"name__startswith": "al"}
        assert enc.encode(EndsWith(Field("name"), "ce"), User, None) == {"name__endswith": "ce"}

    def test_encode_isnull_isnotnull(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import QueryParamFilters
        from emergent.wire.axis.query._expr import IsNull, IsNotNull, Field

        enc = QueryParamFilters()
        assert enc.encode(IsNull(Field("email")), User, None) == {"email__isnull": "true"}
        assert enc.encode(IsNotNull(Field("email")), User, None) == {"email__isnull": "false"}

    def test_encode_and(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import QueryParamFilters
        from emergent.wire.axis.query._expr import And, Eq, Gt, Field, Const

        enc = QueryParamFilters()
        expr = And(Eq(Field("name"), Const("alice")), Gt(Field("age"), Const(18)))
        result = enc.encode(expr, User, None)
        assert result == {"name": "alice", "age__gt": 18}

    def test_encode_and_duplicate_raises(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import QueryParamFilters
        from emergent.wire.axis.query._expr import And, Eq, Field, Const

        enc = QueryParamFilters()
        expr = And(Eq(Field("name"), Const("a")), Eq(Field("name"), Const("b")))
        with pytest.raises(ValueError, match="Duplicate filter key"):
            enc.encode(expr, User, None)

    def test_encode_or_raises(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import QueryParamFilters
        from emergent.wire.axis.query._expr import Or, Eq, Field, Const

        enc = QueryParamFilters()
        expr = Or(Eq(Field("a"), Const(1)), Eq(Field("b"), Const(2)))
        with pytest.raises(ValueError, match="OR filters not supported"):
            enc.encode(expr, User, None)


class TestBodyFilters:
    def test_encode_eq(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import body_filters
        from emergent.wire.axis.query._expr import Eq, Field, Const

        enc = body_filters()
        result = enc.encode(Eq(Field("name"), Const("alice")), User, None)
        assert result == {"filter": {"name": {"eq": "alice"}}}

    def test_encode_ne_lt_le_gt_ge(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import BodyFilters
        from emergent.wire.axis.query._expr import Ne, Lt, Le, Gt, Ge, Field, Const

        enc = BodyFilters()
        assert enc.encode(Ne(Field("a"), Const(1)), User, None) == {"filter": {"a": {"ne": 1}}}
        assert enc.encode(Lt(Field("a"), Const(1)), User, None) == {"filter": {"a": {"lt": 1}}}
        assert enc.encode(Le(Field("a"), Const(1)), User, None) == {"filter": {"a": {"lte": 1}}}
        assert enc.encode(Gt(Field("a"), Const(1)), User, None) == {"filter": {"a": {"gt": 1}}}
        assert enc.encode(Ge(Field("a"), Const(1)), User, None) == {"filter": {"a": {"gte": 1}}}

    def test_encode_in(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import BodyFilters
        from emergent.wire.axis.query._expr import In, Field

        enc = BodyFilters()
        result = enc.encode(In(Field("status"), ("a", "b")), User, None)
        assert result == {"filter": {"status": {"in": ["a", "b"]}}}

    def test_encode_and_or(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import BodyFilters
        from emergent.wire.axis.query._expr import And, Or, Eq, Field, Const

        enc = BodyFilters()
        and_expr = And(Eq(Field("a"), Const(1)), Eq(Field("b"), Const(2)))
        or_expr = Or(Eq(Field("a"), Const(1)), Eq(Field("b"), Const(2)))
        assert enc.encode(and_expr, User, None)["filter"]["and"] is not None
        assert enc.encode(or_expr, User, None)["filter"]["or"] is not None


# ═══════════════════════════════════════════════════════════════════════════════
# 4. HTTP API contrib — sort/limit/select/response encoding
# ═══════════════════════════════════════════════════════════════════════════════


class TestSortParamEncoding:
    def test_encode_ascending(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import sort_param
        from emergent.wire.axis.query._proxy import OrderSpec

        enc = sort_param()
        result = enc.encode([OrderSpec("name", ascending=True)])
        assert result == {"sort": "name"}

    def test_encode_descending(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import SortParamEncoding
        from emergent.wire.axis.query._proxy import OrderSpec

        enc = SortParamEncoding()
        result = enc.encode([OrderSpec("balance", ascending=False)])
        assert result == {"sort": "-balance"}

    def test_encode_multiple(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import SortParamEncoding
        from emergent.wire.axis.query._proxy import OrderSpec

        enc = SortParamEncoding()
        result = enc.encode([
            OrderSpec("balance", ascending=False),
            OrderSpec("name", ascending=True),
        ])
        assert result == {"sort": "-balance,name"}

    def test_encode_empty(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import SortParamEncoding

        enc = SortParamEncoding()
        assert enc.encode([]) == {}


class TestLimitParamEncoding:
    def test_encode(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import limit_param

        enc = limit_param()
        assert enc.encode(50) == {"limit": 50}


class TestFieldsParamEncoding:
    def test_encode(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import fields_param

        enc = fields_param()
        result = enc.encode(["id", "name", "email"])
        assert result == {"fields": "id,name,email"}


class TestGetNested:
    def test_simple_path(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import _get_nested

        assert _get_nested({"data": [1, 2]}, "data") == [1, 2]

    def test_nested_path(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import _get_nested

        assert _get_nested({"response": {"items": [1]}}, "response.items") == [1]

    def test_missing_path(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import _get_nested

        assert _get_nested({"a": 1}, "b.c") is None


# ═══════════════════════════════════════════════════════════════════════════════
# 5. HTTP API contrib — builder
# ═══════════════════════════════════════════════════════════════════════════════


class TestHTTPAPIBuilder:
    def test_build_requires_base_url(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import api

        builder = api(User)
        with pytest.raises(ValueError, match="base URL is required"):
            builder.build(MagicMock())

    def test_full_builder_chain(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import (
            api, bearer, page_size, body_filters,
        )

        client = MagicMock()
        provider = (
            api(User, profile=int)
            .base("https://api.example.com/users")
            .pagination(page_size())
            .auth(bearer("tok"))
            .filters(body_filters())
            .response(data_path="results", total_path="count")
            .id_field("user_id")
            .build(client)
        )
        assert provider.base_url == "https://api.example.com/users"
        assert provider.auth is not None
        assert provider.id_field == "user_id"
        assert provider.data_path == "results"


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Telegram dialect — compile_telegrinder methods
# ═══════════════════════════════════════════════════════════════════════════════


class TestTelegramDialect:
    def test_help_meta_construction(self) -> None:
        from emergent.wire.axis.surface.dialects.telegram import HelpMeta

        h = HelpMeta("Test description", order=5)
        assert h.description == "Test description"
        assert h.order == 5
        assert not h.hidden

    def test_silent_compile_telegrinder(self) -> None:
        from emergent.wire.axis.surface.dialects.telegram import Silent
        from emergent.wire.axis._capability import TelegrinderHandlerContext

        cap = Silent()
        ctx = TelegrinderHandlerContext()
        result = cap.compile_telegrinder(ctx)
        assert result.silent is True

    def test_parse_mode_compile_telegrinder(self) -> None:
        from emergent.wire.axis.surface.dialects.telegram import ParseMode
        from emergent.wire.axis._capability import TelegrinderHandlerContext

        cap = ParseMode(mode="HTML")
        ctx = TelegrinderHandlerContext()
        result = cap.compile_telegrinder(ctx)
        assert result.parse_mode == "HTML"

    def test_link_preview_compile_telegrinder(self) -> None:
        from emergent.wire.axis.surface.dialects.telegram import LinkPreview
        from emergent.wire.axis._capability import TelegrinderHandlerContext

        cap = LinkPreview(disabled=True)
        ctx = TelegrinderHandlerContext()
        result = cap.compile_telegrinder(ctx)
        assert result.link_preview_disabled is True

    def test_protect_content_compile_telegrinder(self) -> None:
        from emergent.wire.axis.surface.dialects.telegram import ProtectContent
        from emergent.wire.axis._capability import TelegrinderHandlerContext

        cap = ProtectContent()
        ctx = TelegrinderHandlerContext()
        result = cap.compile_telegrinder(ctx)
        assert result.protect_content is True

    def test_edit_message_compile_telegrinder(self) -> None:
        from emergent.wire.axis.surface.dialects.telegram import EditMessage
        from emergent.wire.axis._capability import TelegrinderHandlerContext

        cap = EditMessage()
        ctx = TelegrinderHandlerContext()
        result = cap.compile_telegrinder(ctx)
        assert result.edit_message is True

    def test_answer_callback_compile_telegrinder(self) -> None:
        from emergent.wire.axis.surface.dialects.telegram import AnswerCallback
        from emergent.wire.axis._capability import TelegrinderHandlerContext

        cap = AnswerCallback(text="Processing", show_alert=True, cache_time=10)
        ctx = TelegrinderHandlerContext()
        result = cap.compile_telegrinder(ctx)
        assert result.answer_callback is True
        assert result.answer_callback_text == "Processing"
        assert result.answer_callback_show_alert is True


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Memory API provider — deeper testing
# ═══════════════════════════════════════════════════════════════════════════════


class TestMemoryAPIProvider:
    @pytest.fixture
    def provider(self) -> MemoryAPIProvider[int, User]:
        return MemoryAPIProvider[int, User](
            data=[
                User(id=1, name="alice", email="a@b.com", balance=100),
                User(id=2, name="bob", email="b@b.com", balance=200),
                User(id=3, name="charlie", email="c@b.com", balance=300),
            ],
            key_fn=lambda u: u.id,
        )

    @pytest.mark.asyncio
    async def test_fetch_page(self, provider: MemoryAPIProvider[int, User]) -> None:
        from emergent.wire.axis.query._api import api

        q = api(User, key=lambda u: u.id).list()
        result = await provider.fetch_page(q)
        assert result.total == 3
        assert len(result.items) == 3

    @pytest.mark.asyncio
    async def test_partial_update(self, provider: MemoryAPIProvider[int, User]) -> None:
        from emergent.wire.axis.query._api import api
        # Simulating a partial update with None fields (dynamic usage)
        partial_data: dict[str, Any] = {"id": 1, "name": "alice_updated", "email": None, "balance": None}
        partial_user: Any = User(**partial_data)
        q = api(User, key=lambda u: u.id).update(1, partial_user, partial=True)
        result = await provider.execute(q)
        assert result.name == "alice_updated"

    @pytest.mark.asyncio
    async def test_full_update(self, provider: MemoryAPIProvider[int, User]) -> None:
        from emergent.wire.axis.query._api import api

        updated = User(id=1, name="alice_v2", email="new@b.com", balance=999)
        q = api(User, key=lambda u: u.id).update(1, updated)
        result = await provider.execute(q)
        assert result.name == "alice_v2"
        assert result.balance == 999

    @pytest.mark.asyncio
    async def test_update_not_found(self, provider: MemoryAPIProvider[int, User]) -> None:
        from emergent.wire.axis.query._api import api

        q = api(User, key=lambda u: u.id).update(999, User(id=999, name="x", email="x"))
        with pytest.raises(ValueError, match="not found"):
            await provider.execute(q)

    @pytest.mark.asyncio
    async def test_delete(self, provider: MemoryAPIProvider[int, User]) -> None:
        from emergent.wire.axis.query._api import api

        q = api(User, key=lambda u: u.id).delete(1)
        result = await provider.delete(q)
        assert result is True
        assert len(provider.data) == 2

    @pytest.mark.asyncio
    async def test_delete_not_found(self, provider: MemoryAPIProvider[int, User]) -> None:
        from emergent.wire.axis.query._api import api

        q = api(User, key=lambda u: u.id).delete(999)
        result = await provider.delete(q)
        assert result is False

    @pytest.mark.asyncio
    async def test_create(self, provider: MemoryAPIProvider[int, User]) -> None:
        from emergent.wire.axis.query._api import api

        new_user = User(id=4, name="dave", email="d@b.com")
        q = api(User, key=lambda u: u.id).create(new_user)
        result = await provider.execute(q)
        assert result.name == "dave"
        assert len(provider.data) == 4

    @pytest.mark.asyncio
    async def test_fetch_one_list_op(self, provider: MemoryAPIProvider[int, User]) -> None:
        from emergent.wire.axis.query._api import api

        q = api(User, key=lambda u: u.id).list()
        result = await provider.fetch_one(q)
        assert result is not None

    @pytest.mark.asyncio
    async def test_fetch_one_get_op(self, provider: MemoryAPIProvider[int, User]) -> None:
        from emergent.wire.axis.query._api import api

        q = api(User, key=lambda u: u.id).get(2)
        result = await provider.fetch_one(q)
        assert result is not None
        assert result.name == "bob"

    @pytest.mark.asyncio
    async def test_next_id_no_generator_raises(self, provider: MemoryAPIProvider[int, User]) -> None:
        with pytest.raises(RuntimeError, match="No next_id"):
            await provider.next_id()

    @pytest.mark.asyncio
    async def test_include_mod_raises(self, provider: MemoryAPIProvider[int, User]) -> None:
        from emergent.wire.axis.query._api import api, IncludeMod

        q = api(User, key=lambda u: u.id).list()
        q = replace(q, mods=(*q.mods, IncludeMod(("relation",))))
        with pytest.raises(TypeError, match="IncludeMod"):
            await provider.fetch_many(q)


# ═══════════════════════════════════════════════════════════════════════════════
# 8. Memory Relational Provider — aggregation
# ═══════════════════════════════════════════════════════════════════════════════


class TestMemoryRelationalAggregation:
    @pytest.mark.asyncio
    async def test_basic_aggregates(self) -> None:
        from emergent.wire.axis.query.providers.memory import MemoryRelationalProvider
        from emergent.wire.axis.query import relational

        provider: MemoryRelationalProvider[User] = MemoryRelationalProvider(
            data=[
                User(id=1, name="alice", email="a@b.com", balance=100),
                User(id=2, name="bob", email="b@b.com", balance=200),
                User(id=3, name="charlie", email="c@b.com", balance=300),
            ]
        )
        q = relational(User).aggregate(
            total=lambda u: u.balance.sum(),
            avg_bal=lambda u: u.balance.avg(),
            min_bal=lambda u: u.balance.min(),
            max_bal=lambda u: u.balance.max(),
            user_count=lambda u: u.count(),
        )
        result = await provider.aggregate(q)
        assert result["total"] == 600
        assert result["avg_bal"] == 200.0
        assert result["min_bal"] == 100
        assert result["max_bal"] == 300
        assert result["user_count"] == 3

    @pytest.mark.asyncio
    async def test_string_agg(self) -> None:
        from emergent.wire.axis.query.providers.memory import MemoryRelationalProvider
        from emergent.wire.axis.query import relational

        provider: MemoryRelationalProvider[User] = MemoryRelationalProvider(
            data=[
                User(id=1, name="alice", email="a@b.com"),
                User(id=2, name="bob", email="b@b.com"),
            ]
        )
        q = relational(User).aggregate(
            names=lambda u: u.name.string_agg(", "),
        )
        result = await provider.aggregate(q)
        assert result["names"] == "alice, bob"

    @pytest.mark.asyncio
    async def test_array_agg(self) -> None:
        from emergent.wire.axis.query.providers.memory import MemoryRelationalProvider
        from emergent.wire.axis.query import relational

        provider: MemoryRelationalProvider[User] = MemoryRelationalProvider(
            data=[
                User(id=1, name="alice", email="a@b.com"),
                User(id=2, name="bob", email="b@b.com"),
            ]
        )
        q = relational(User).aggregate(
            all_names=lambda u: u.name.array_agg(),
        )
        result = await provider.aggregate(q)
        assert result["all_names"] == ["alice", "bob"]


# ═══════════════════════════════════════════════════════════════════════════════
# 9. Memory KV Provider
# ═══════════════════════════════════════════════════════════════════════════════


class TestMemoryKVProvider:
    @pytest.mark.asyncio
    async def test_scan(self) -> None:
        from kungfu import Ok
        from emergent.wire.axis.query._kv import kv

        provider = MemoryKVProvider[str, str](data={"user:1": "a", "user:2": "b", "post:1": "c"})
        qs = kv(str, key=lambda x: x)
        result = await provider.scan(qs.scan("user:*"))
        assert isinstance(result, Ok)
        assert sorted(result.value) == ["a", "b"]

    @pytest.mark.asyncio
    async def test_keys(self) -> None:
        from kungfu import Ok
        from emergent.wire.axis.query._kv import kv

        provider = MemoryKVProvider[str, str](data={"user:1": "a", "user:2": "b", "post:1": "c"})
        qs = kv(str, key=lambda x: x)
        result = await provider.keys(qs.keys("user:*"))
        assert isinstance(result, Ok)
        assert sorted(result.value) == ["user:1", "user:2"]

    @pytest.mark.asyncio
    async def test_exists(self) -> None:
        from kungfu import Ok
        from emergent.wire.axis.query._kv import kv

        provider = MemoryKVProvider[str, str](data={"k": "v"})
        qs = kv(str, key=lambda x: x)
        result = await provider.exists(qs.exists("k"))
        assert isinstance(result, Ok)
        assert result.value is True
        result2 = await provider.exists(qs.exists("missing"))
        assert isinstance(result2, Ok)
        assert result2.value is False


# ═══════════════════════════════════════════════════════════════════════════════
# 10. Codec resolve — unwrap/wrap branches
# ═══════════════════════════════════════════════════════════════════════════════


class TestCodecResolve:
    def test_unwrap_option(self) -> None:
        from kungfu import Option
        from emergent.wire.axis.surface.codecs.resolve import unwrap

        inner, is_opt = unwrap(Option[int])
        assert inner is int
        assert is_opt is True

    def test_unwrap_result(self) -> None:
        from kungfu import Result
        from emergent.wire.axis.surface.codecs.resolve import unwrap

        inner, is_opt = unwrap(Result[str, int])
        assert inner is str
        assert is_opt is True

    def test_unwrap_plain_type(self) -> None:
        from emergent.wire.axis.surface.codecs.resolve import unwrap

        inner, is_opt = unwrap(int)
        assert inner is int
        assert is_opt is False

    def test_wrap_option_success(self) -> None:
        from kungfu import Option, Some
        from emergent.wire.axis.surface.codecs.resolve import wrap

        result: Some[int] = wrap(Option[int], True, 42)
        assert isinstance(result, Some)
        assert result.value == 42

    def test_wrap_option_failure(self) -> None:
        from kungfu import Option, Nothing
        from emergent.wire.axis.surface.codecs.resolve import wrap

        result = wrap(Option[int], False, "err")
        assert isinstance(result, Nothing)

    def test_wrap_result_success(self) -> None:
        from kungfu import Result, Ok
        from emergent.wire.axis.surface.codecs.resolve import wrap

        result: Ok[str] = wrap(Result[str, int], True, "hello")
        assert isinstance(result, Ok)
        assert result.value == "hello"

    def test_wrap_result_failure(self) -> None:
        from kungfu import Result, Error
        from emergent.wire.axis.surface.codecs.resolve import wrap

        result = wrap(Result[str, int], False, 99)
        assert isinstance(result, Error)

    def test_wrap_plain_success(self) -> None:
        from emergent.wire.axis.surface.codecs.resolve import wrap

        assert wrap(int, True, 42) == 42

    def test_wrap_plain_failure_raises(self) -> None:
        from emergent.wire.axis.surface.codecs.resolve import wrap

        with pytest.raises(RuntimeError, match="Required param failed"):
            wrap(int, False, "oops")

    def test_get_transition_params_no_transition(self) -> None:
        from emergent.wire.axis.surface.codecs.resolve import get_transition_params

        class NoTransition:
            pass

        assert get_transition_params(NoTransition) == {}


# ═══════════════════════════════════════════════════════════════════════════════
# 11. Derive transforms — through compile_derive
# ═══════════════════════════════════════════════════════════════════════════════


class TestDeriveTransforms:
    def _compile(self, entity: type[Any]) -> Any:
        from emergent.wire.derive._compile import compile_derive

        ctxs: list[Any] = compile_derive(entity)
        return ctxs[0]

    def test_readonly_removes_mutations(self) -> None:
        from emergent.wire.axis.schema._universal import schema_meta
        from emergent.wire.derive._crud import http_crud
        from emergent.wire.derive._transforms import Readonly

        class DummyProvider:
            pass

        @schema_meta(http_crud("/api/users", DummyProvider), Readonly())
        @dataclass
        class ReadonlyUser:
            id: Annotated[int, Identity()]
            name: str

        ctx = self._compile(ReadonlyUser)
        for spec in ctx.specs:
            from emergent.wire.derive._effects import has_effect, Mutation
            assert not has_effect(spec.effects, Mutation)

    def test_mutations_only_keeps_mutations(self) -> None:
        from emergent.wire.axis.schema._universal import schema_meta
        from emergent.wire.derive._crud import http_crud
        from emergent.wire.derive._transforms import MutationsOnly

        class DummyProvider:
            pass

        @schema_meta(http_crud("/api/users", DummyProvider), MutationsOnly())
        @dataclass
        class MutOnlyUser:
            id: Annotated[int, Identity()]
            name: str

        ctx = self._compile(MutOnlyUser)
        from emergent.wire.derive._effects import has_effect, Mutation
        for spec in ctx.specs:
            assert has_effect(spec.effects, Mutation)

    def test_without_delete(self) -> None:
        from emergent.wire.axis.schema._universal import schema_meta
        from emergent.wire.derive._crud import http_crud
        from emergent.wire.derive._transforms import WithoutDelete

        class DummyProvider:
            pass

        @schema_meta(http_crud("/api/users", DummyProvider), WithoutDelete())
        @dataclass
        class NoDelUser:
            id: Annotated[int, Identity()]
            name: str

        ctx = self._compile(NoDelUser)
        from emergent.wire.derive._effects import has_effect, Deletes
        for spec in ctx.specs:
            assert not has_effect(spec.effects, Deletes)

    def test_paginated(self) -> None:
        from emergent.wire.axis.schema._universal import schema_meta
        from emergent.wire.derive._crud import http_crud
        from emergent.wire.derive._transforms import Paginated

        class DummyProvider:
            pass

        @schema_meta(http_crud("/api/users", DummyProvider), Paginated(50))
        @dataclass
        class PagUser:
            id: Annotated[int, Identity()]
            name: str

        ctx = self._compile(PagUser)
        list_specs = [s for s in ctx.specs if s.name == "List"]
        assert len(list_specs) == 1
        assert any(f[0] == "page" for f in list_specs[0].extra_op_fields)
        assert any(f[0] == "page_size" for f in list_specs[0].extra_op_fields)

    def test_sorted(self) -> None:
        from emergent.wire.axis.schema._universal import schema_meta
        from emergent.wire.derive._crud import http_crud
        from emergent.wire.derive._transforms import Sorted

        class DummyProvider:
            pass

        @schema_meta(http_crud("/api/users", DummyProvider), Sorted("name", "desc"))
        @dataclass
        class SortedUser:
            id: Annotated[int, Identity()]
            name: str

        ctx = self._compile(SortedUser)
        list_specs = [s for s in ctx.specs if s.name == "List"]
        assert len(list_specs) == 1
        assert any(f[0] == "sort" for f in list_specs[0].extra_op_fields)

    def test_only_ops(self) -> None:
        from emergent.wire.axis.schema._universal import schema_meta
        from emergent.wire.derive._crud import http_crud
        from emergent.wire.derive._transforms import OnlyOps

        class DummyProvider:
            pass

        @schema_meta(http_crud("/api/users", DummyProvider), OnlyOps(("List", "Get")))
        @dataclass
        class LimitedUser:
            id: Annotated[int, Identity()]
            name: str

        ctx = self._compile(LimitedUser)
        names = {s.name for s in ctx.specs}
        assert names == {"List", "Get"}

    def test_without_create(self) -> None:
        from emergent.wire.axis.schema._universal import schema_meta
        from emergent.wire.derive._crud import http_crud
        from emergent.wire.derive._transforms import WithoutCreate

        class DummyProvider:
            pass

        @schema_meta(http_crud("/api/users", DummyProvider), WithoutCreate())
        @dataclass
        class NoCreateUser:
            id: Annotated[int, Identity()]
            name: str

        ctx = self._compile(NoCreateUser)
        from emergent.wire.derive._effects import has_effect, Creates
        for spec in ctx.specs:
            assert not has_effect(spec.effects, Creates)

    def test_create_only(self) -> None:
        from emergent.wire.axis.schema._universal import schema_meta
        from emergent.wire.derive._crud import http_crud
        from emergent.wire.derive._transforms import CreateOnly

        class DummyProvider:
            pass

        @schema_meta(http_crud("/api/users", DummyProvider), CreateOnly())
        @dataclass
        class CreateOnlyUser:
            id: Annotated[int, Identity()]
            name: str

        ctx = self._compile(CreateOnlyUser)
        from emergent.wire.derive._effects import has_effect, Creates
        for spec in ctx.specs:
            assert has_effect(spec.effects, Creates)

    def test_update_only(self) -> None:
        from emergent.wire.axis.schema._universal import schema_meta
        from emergent.wire.derive._crud import http_crud
        from emergent.wire.derive._transforms import UpdateOnly

        class DummyProvider:
            pass

        @schema_meta(http_crud("/api/users", DummyProvider), UpdateOnly())
        @dataclass
        class UpdateOnlyUser:
            id: Annotated[int, Identity()]
            name: str

        ctx = self._compile(UpdateOnlyUser)
        from emergent.wire.derive._effects import has_effect, Updates
        for spec in ctx.specs:
            assert has_effect(spec.effects, Updates)


# ═══════════════════════════════════════════════════════════════════════════════
# 12. Auth capabilities
# ═══════════════════════════════════════════════════════════════════════════════


class TestAuthCaps:
    def test_authenticated_requires_validate(self) -> None:
        from emergent.wire.derive.auth.caps import Authenticated

        with pytest.raises(ValueError, match="requires a TokenValidate"):
            Authenticated()

    def test_authenticated_separates_extractors(self) -> None:
        from emergent.wire.derive.auth.caps import Authenticated
        from emergent.wire.derive.auth.validate import TokenValidate
        from emergent.wire.derive.auth.extractors import BearerExtract

        lookup = AsyncMock(return_value=None)
        auth = Authenticated(
            BearerExtract(),
            TokenValidate(identity_type=User, lookup=lookup),
        )
        assert len(auth.extractors) == 1
        assert isinstance(auth.extractors[0], BearerExtract)
        assert isinstance(auth.validate, TokenValidate)

    def test_authenticated_auto_detect_validate(self) -> None:
        from emergent.wire.derive.auth.caps import Authenticated
        from emergent.wire.derive.auth.validate import TokenValidate

        lookup = AsyncMock(return_value=None)
        auth = Authenticated(
            TokenValidate(identity_type=User, lookup=lookup),
        )
        assert len(auth.extractors) == 0
        assert isinstance(auth.validate, TokenValidate)

    def test_role_required(self) -> None:
        from emergent.wire.axis.schema._universal import schema_meta
        from emergent.wire.derive._crud import http_crud
        from emergent.wire.derive.auth.caps import RoleRequired
        from emergent.wire.derive._compile import compile_derive
        from emergent.wire.derive._effects import Mutation

        class DummyProvider:
            pass

        def _get_roles(_u: User) -> set[str]:
            return {"admin"}

        @schema_meta(
            http_crud("/api/users", DummyProvider),
            RoleRequired(User, "admin", _get_roles, effect=Mutation),
        )
        @dataclass
        class RoleUser:
            id: Annotated[int, Identity()]
            name: str

        ctx = compile_derive(RoleUser)[0]
        # Mutation specs should have the RequireRole enricher
        from emergent.wire.derive._effects import has_effect
        for spec in ctx.specs:
            if has_effect(spec.effects, Mutation):
                from emergent.wire.derive.auth.caps import RequireRole
                has_role_cap = any(isinstance(c, RequireRole) for c in spec.capabilities)
                assert has_role_cap

    def test_authorize_ops_strict_raises(self) -> None:
        from emergent.wire.derive.auth.caps import AuthorizeOps
        from emergent.wire.derive._opspec import OpSpec
        from emergent.wire.derive._handler import FetchMany
        from emergent.wire.derive._project import ListResponse
        from emergent.wire.derive._effects import Read

        spec = OpSpec(
            name="List",
            entity_name="User",
            input_fields={},
            request_fields={},
            response_spec=ListResponse(),
            handler_template=FetchMany(),
            trigger=MagicMock(),
            capabilities=(),
            effects=(Read(),),
            source="test",
        )
        from emergent.wire.derive._ctx import DeriveCtx

        ctx = DeriveCtx(entity=User, specs=(spec,))
        def _get_roles(_u: object) -> set[str]:
            return {"admin"}

        auth = AuthorizeOps(User, {"Get": "admin"}, _get_roles, strict=True)
        with pytest.raises(ValueError, match="has no role mapping"):
            auth.compile_derive_modify(ctx)

    def test_authorize_ops_non_strict(self) -> None:
        from emergent.wire.derive.auth.caps import AuthorizeOps
        from emergent.wire.derive._opspec import OpSpec
        from emergent.wire.derive._handler import FetchMany
        from emergent.wire.derive._project import ListResponse
        from emergent.wire.derive._effects import Read

        spec = OpSpec(
            name="List",
            entity_name="User",
            input_fields={},
            request_fields={},
            response_spec=ListResponse(),
            handler_template=FetchMany(),
            trigger=MagicMock(),
            capabilities=(),
            effects=(Read(),),
            source="test",
        )
        from emergent.wire.derive._ctx import DeriveCtx

        ctx = DeriveCtx(entity=User, specs=(spec,))
        def _get_roles(_u: object) -> set[str]:
            return {"admin"}

        auth = AuthorizeOps(User, {"Get": "admin"}, _get_roles, strict=False)
        result = auth.compile_derive_modify(ctx)
        assert len(result.specs) == 1


# ═══════════════════════════════════════════════════════════════════════════════
# 13. Auth login — token_converter
# ═══════════════════════════════════════════════════════════════════════════════


class TestAuthLogin:
    def test_token_converter_ok(self) -> None:
        from kungfu import Ok
        from emergent.wire.derive.auth.login import token_converter

        @dataclass
        class Resp:
            token: str | None
            error: str | None

        raw = token_converter(Resp, Ok("my-token"))
        assert isinstance(raw, Resp)
        assert raw.token == "my-token"
        assert raw.error is None

    def test_token_converter_error(self) -> None:
        from kungfu import Error
        from emergent.wire.derive.auth.login import token_converter

        @dataclass
        class Resp:
            token: str | None
            error: str | None

        raw = token_converter(Resp, Error("bad"))
        assert isinstance(raw, Resp)
        assert raw.token is None
        assert raw.error == "bad"


# ═══════════════════════════════════════════════════════════════════════════════
# 14. HTTP dialect — compile_fastapi_route / compile_fastapi_app
# ═══════════════════════════════════════════════════════════════════════════════


class TestHTTPDialect:
    def _make_route_ctx(self) -> Any:
        from emergent.wire.axis._capability import FastAPIRouteContext
        return FastAPIRouteContext(path="/test", method="GET")

    def test_tag_of(self) -> None:
        from emergent.wire.axis.surface.dialects.http import Tag

        tag = Tag.of("users", "User endpoints")
        ctx = self._make_route_ctx()
        result = tag.compile_fastapi_route(ctx)
        assert "users" in result.tags

    def test_bearer_auth_jwt(self) -> None:
        from emergent.wire.axis.surface.dialects.http import BearerAuth

        auth = BearerAuth.jwt("JWT for auth")
        ctx = self._make_route_ctx()
        result = auth.compile_fastapi_route(ctx)
        assert len(result.security) > 0

    def test_bearer_auth_opaque(self) -> None:
        from emergent.wire.axis.surface.dialects.http import BearerAuth

        auth = BearerAuth.opaque("opaque token")
        assert auth.model is not None

    def test_api_key_auth_header(self) -> None:
        from emergent.wire.axis.surface.dialects.http import ApiKeyAuth

        auth = ApiKeyAuth.header("X-API-Key")
        ctx = self._make_route_ctx()
        result = auth.compile_fastapi_route(ctx)
        assert len(result.security) > 0

    def test_api_key_auth_query(self) -> None:
        from emergent.wire.axis.surface.dialects.http import ApiKeyAuth

        auth = ApiKeyAuth.query("api_key")
        assert auth.model is not None

    def test_summary(self) -> None:
        from emergent.wire.axis.surface.dialects.http import Summary

        s = Summary.of("Login user", "Authenticates and returns JWT")
        ctx = self._make_route_ctx()
        result = s.compile_fastapi_route(ctx)
        assert result.summary == "Login user"
        assert result.description == "Authenticates and returns JWT"

    def test_operation_id(self) -> None:
        from emergent.wire.axis.surface.dialects.http import OperationId

        op = OperationId.of("loginUser")
        ctx = self._make_route_ctx()
        result = op.compile_fastapi_route(ctx)
        assert result.operation_id == "loginUser"

    def test_deprecated(self) -> None:
        from emergent.wire.axis.surface.dialects.http import Deprecated

        dep = Deprecated.because("Use v2")
        ctx = self._make_route_ctx()
        result = dep.compile_fastapi_route(ctx)
        assert result.deprecated is True

    def test_deprecated_until(self) -> None:
        from emergent.wire.axis.surface.dialects.http import Deprecated

        dep = Deprecated.until("2025-01-01", "Migrating")
        assert dep.sunset_date == "2025-01-01"

    def test_response_status(self) -> None:
        from emergent.wire.axis.surface.dialects.http import ResponseStatus

        rs = ResponseStatus(201)
        ctx = self._make_route_ctx()
        result = rs.compile_fastapi_route(ctx)
        assert result.status_code == 201

    def test_response_header(self) -> None:
        from emergent.wire.axis.surface.dialects.http import ResponseHeader

        rh = ResponseHeader("X-Request-Id", "Unique ID", schema_type="string")
        ctx = self._make_route_ctx()
        result = rh.compile_fastapi_route(ctx)
        assert result.openapi_extra is not None
        assert "responses" in result.openapi_extra

    def test_content_type(self) -> None:
        from emergent.wire.axis.surface.dialects.http import ContentType

        ct = ContentType("text/csv")
        ctx = self._make_route_ctx()
        result = ct.compile_fastapi_route(ctx)
        assert result.openapi_extra is not None

    def test_oauth2_authorization_code(self) -> None:
        from emergent.wire.axis.surface.dialects.http import OAuth2Auth

        auth = OAuth2Auth.authorization_code(
            authorization_url="https://example.com/oauth/authorize",
            token_url="https://example.com/oauth/token",
            scopes={"read": "Read access"},
            required_scopes=("read",),
        )
        ctx = self._make_route_ctx()
        result = auth.compile_fastapi_route(ctx)
        assert len(result.security) > 0

    def test_oauth2_client_credentials(self) -> None:
        from emergent.wire.axis.surface.dialects.http import OAuth2Auth

        auth = OAuth2Auth.client_credentials(
            token_url="https://example.com/token",
            scopes={"write": "Write access"},
        )
        assert auth.model is not None

    def test_oauth2_password(self) -> None:
        from emergent.wire.axis.surface.dialects.http import OAuth2Auth

        auth = OAuth2Auth.password(
            token_url="https://example.com/token",
            scopes={"admin": "Admin access"},
        )
        assert auth.model is not None


# ═══════════════════════════════════════════════════════════════════════════════
# 15. Delta dialect
# ═══════════════════════════════════════════════════════════════════════════════


class TestDeltaDialect:
    def test_numeric_delta_add(self) -> None:
        from emergent.wire.axis.schema.dialects.delta import NumericDelta

        d = NumericDelta(add=50)
        assert d.apply(100) == 150

    def test_numeric_delta_multiply(self) -> None:
        from emergent.wire.axis.schema.dialects.delta import NumericDelta

        d = NumericDelta(multiply=2.0)
        assert d.apply(100) == 200.0

    def test_numeric_delta_set_overrides(self) -> None:
        from emergent.wire.axis.schema.dialects.delta import NumericDelta

        d = NumericDelta(add=50, set=0)
        assert d.apply(100) == 0

    def test_numeric_delta_preserves_int(self) -> None:
        from emergent.wire.axis.schema.dialects.delta import NumericDelta

        d = NumericDelta(add=10)
        result = d.apply(90)
        assert isinstance(result, int)
        assert result == 100

    def test_string_delta_append(self) -> None:
        from emergent.wire.axis.schema.dialects.delta import StringDelta

        d = StringDelta(append=" world")
        assert d.apply("hello") == "hello world"

    def test_string_delta_prepend(self) -> None:
        from emergent.wire.axis.schema.dialects.delta import StringDelta

        d = StringDelta(prepend="[INFO] ")
        assert d.apply("msg") == "[INFO] msg"

    def test_string_delta_replace(self) -> None:
        from emergent.wire.axis.schema.dialects.delta import StringDelta

        d = StringDelta(replace=("old", "new"))
        assert d.apply("this is old text") == "this is new text"

    def test_string_delta_set(self) -> None:
        from emergent.wire.axis.schema.dialects.delta import StringDelta

        d = StringDelta(set="brand new")
        assert d.apply("whatever") == "brand new"

    def test_collection_delta_push(self) -> None:
        from emergent.wire.axis.schema.dialects.delta import CollectionDelta

        d: CollectionDelta[str] = CollectionDelta(push=("c", "d"))
        assert d.apply(["a", "b"]) == ["a", "b", "c", "d"]

    def test_collection_delta_pop(self) -> None:
        from emergent.wire.axis.schema.dialects.delta import CollectionDelta

        d: CollectionDelta[str] = CollectionDelta(pop=2)
        assert d.apply(["a", "b", "c", "d"]) == ["a", "b"]

    def test_collection_delta_remove(self) -> None:
        from emergent.wire.axis.schema.dialects.delta import CollectionDelta

        d: CollectionDelta[str] = CollectionDelta(remove=("b",))
        assert d.apply(["a", "b", "c"]) == ["a", "c"]

    def test_collection_delta_insert(self) -> None:
        from emergent.wire.axis.schema.dialects.delta import CollectionDelta

        d: CollectionDelta[str] = CollectionDelta(insert=(0, "first"))
        assert d.apply(["a", "b"]) == ["first", "a", "b"]

    def test_collection_delta_set(self) -> None:
        from emergent.wire.axis.schema.dialects.delta import CollectionDelta

        d: CollectionDelta[str] = CollectionDelta(set=("x", "y"))
        assert d.apply(["a", "b", "c"]) == ["x", "y"]

    def test_delta_type_generation(self) -> None:
        from emergent.wire.axis.schema.dialects.delta import delta_type, NumericDelta

        DeltaT = delta_type(_DeltaAccount)
        d = DeltaT(balance=NumericDelta(add=100))
        assert d.balance.add == 100

    def test_apply_delta(self) -> None:
        from emergent.wire.axis.schema.dialects.delta import (
            delta_type, NumericDelta, apply_delta,
        )

        DeltaT = delta_type(_DeltaAccount)
        account = _DeltaAccount(id=1, balance=100)
        d = DeltaT(balance=NumericDelta(add=50))
        new_account = apply_delta(account, d)
        assert new_account.balance == 150
        assert new_account.id == 1

    def test_compose_deltas_numeric(self) -> None:
        from emergent.wire.axis.schema.dialects.delta import (
            delta_type, NumericDelta, compose_deltas,
        )

        DeltaT = delta_type(_DeltaAccount)
        d1 = DeltaT(balance=NumericDelta(add=100))
        d2 = DeltaT(balance=NumericDelta(add=50))
        combined = compose_deltas(d1, d2)
        assert combined.balance.add == 150

    def test_compose_deltas_single(self) -> None:
        from emergent.wire.axis.schema.dialects.delta import (
            delta_type, NumericDelta, compose_deltas,
        )

        DeltaT = delta_type(_DeltaAccount)
        d1 = DeltaT(balance=NumericDelta(add=100))
        assert compose_deltas(d1) is d1

    def test_validate_delta(self) -> None:
        from emergent.wire.axis.schema.dialects.delta import (
            delta_type, NumericDelta, validate_delta,
        )

        DeltaT = delta_type(_DeltaAccount)
        d = DeltaT(balance=NumericDelta(add=50))
        errors = validate_delta(d, _DeltaAccount)
        assert errors == []

    def test_compose_string_deltas(self) -> None:
        from emergent.wire.axis.schema.dialects.delta import (
            _compose_field_deltas, StringDelta,
        )

        d1 = StringDelta(append=" world")
        d2 = StringDelta(prepend="hello ")
        result = _compose_field_deltas(d1, d2)
        assert isinstance(result, StringDelta)
        assert result.append == " world"
        assert result.prepend == "hello "

    def test_compose_collection_deltas(self) -> None:
        from emergent.wire.axis.schema.dialects.delta import (
            _compose_field_deltas, CollectionDelta,
        )

        d1: CollectionDelta[str] = CollectionDelta(push=("a",))
        d2: CollectionDelta[str] = CollectionDelta(push=("b",))
        result = _compose_field_deltas(d1, d2)
        assert isinstance(result, CollectionDelta)
        assert result.push == ("a", "b")


# ═══════════════════════════════════════════════════════════════════════════════
# 16. Temporal dialect
# ═══════════════════════════════════════════════════════════════════════════════


class TestTemporalDialect:
    def test_temporal_filter_current(self) -> None:
        from emergent.wire.axis.schema.dialects.temporal import temporal_filter_current
        from emergent.wire.axis.query._expr import IsNull

        expr = temporal_filter_current()
        assert isinstance(expr, IsNull)

    def test_temporal_filter_as_of(self) -> None:
        from datetime import datetime
        from emergent.wire.axis.schema.dialects.temporal import temporal_filter_as_of
        from emergent.wire.axis.query._expr import And

        expr = temporal_filter_as_of(datetime(2024, 1, 1))
        assert isinstance(expr, And)

    def test_temporal_filter_version(self) -> None:
        from emergent.wire.axis.schema.dialects.temporal import temporal_filter_version
        from emergent.wire.axis.query._expr import Eq

        expr = temporal_filter_version(3)
        assert isinstance(expr, Eq)

    def test_versioned_compile_pydantic_model(self) -> None:
        from emergent.wire.axis.schema.dialects.temporal import Versioned
        from emergent.wire.axis._capability import PydanticModelContext

        v = Versioned(version_field="ver", start_version=1)
        ctx = PydanticModelContext(class_name="TestModel")
        result = v.compile_pydantic_model(ctx)
        assert any(f.name == "ver" for f in result.extra_fields)


# ═══════════════════════════════════════════════════════════════════════════════
# 17. Proxy — JSON, regex, array ops
# ═══════════════════════════════════════════════════════════════════════════════


class TestProxy:
    def test_field_proxy_json(self) -> None:
        from emergent.wire.axis.query._proxy import FieldProxy
        from emergent.wire.axis.query._expr import JsonExtract

        fp = FieldProxy("metadata")
        jp = fp.json("profile.name")
        expr = jp.to_expr()
        assert isinstance(expr, JsonExtract)

    def test_json_field_proxy_eq(self) -> None:
        from emergent.wire.axis.query._proxy import FieldProxy
        from emergent.wire.axis.query._expr import Eq

        fp = FieldProxy("metadata")
        expr = fp.json("profile.name") == "alice"
        assert isinstance(expr, Eq)

    def test_field_proxy_regex(self) -> None:
        from emergent.wire.axis.query._proxy import FieldProxy
        from emergent.wire.axis.query._expr import Regex

        fp = FieldProxy("email")
        expr = fp.regex(r"^\\w+@\\w+\\.\\w+$")
        assert isinstance(expr, Regex)

    def test_field_proxy_like(self) -> None:
        from emergent.wire.axis.query._proxy import FieldProxy
        from emergent.wire.axis.query._expr import Like

        fp = FieldProxy("email")
        expr = fp.like("%@gmail.com")
        assert isinstance(expr, Like)

    def test_field_proxy_ilike(self) -> None:
        from emergent.wire.axis.query._proxy import FieldProxy
        from emergent.wire.axis.query._expr import ILike

        fp = FieldProxy("email")
        expr = fp.ilike("%@GMAIL.COM")
        assert isinstance(expr, ILike)

    def test_field_proxy_between(self) -> None:
        from emergent.wire.axis.query._proxy import FieldProxy
        from emergent.wire.axis.query._expr import Between

        fp = FieldProxy("balance")
        expr = fp.between(100, 1000)
        assert isinstance(expr, Between)

    def test_field_proxy_array_contains(self) -> None:
        from emergent.wire.axis.query._proxy import FieldProxy
        from emergent.wire.axis.query._expr import ArrayContains

        fp = FieldProxy("tags")
        expr = fp.array_contains("vip")
        assert isinstance(expr, ArrayContains)

    def test_field_proxy_array_any(self) -> None:
        from emergent.wire.axis.query._proxy import FieldProxy
        from emergent.wire.axis.query._expr import ArrayAny

        fp = FieldProxy("tags")
        expr = fp.array_any("vip", "admin")
        assert isinstance(expr, ArrayAny)

    def test_field_proxy_array_all(self) -> None:
        from emergent.wire.axis.query._proxy import FieldProxy
        from emergent.wire.axis.query._expr import ArrayAll

        fp = FieldProxy("tags")
        expr = fp.array_all("vip", "verified")
        assert isinstance(expr, ArrayAll)

    def test_field_proxy_array_overlap(self) -> None:
        from emergent.wire.axis.query._proxy import FieldProxy
        from emergent.wire.axis.query._expr import ArrayOverlap

        fp = FieldProxy("tags")
        expr = fp.array_overlap("a", "b")
        assert isinstance(expr, ArrayOverlap)

    def test_field_proxy_json_contains(self) -> None:
        from emergent.wire.axis.query._proxy import FieldProxy
        from emergent.wire.axis.query._expr import JsonContains

        fp = FieldProxy("metadata")
        expr = fp.json_contains({"role": "admin"})
        assert isinstance(expr, JsonContains)

    def test_field_proxy_json_has_key(self) -> None:
        from emergent.wire.axis.query._proxy import FieldProxy
        from emergent.wire.axis.query._expr import JsonHasKey

        fp = FieldProxy("metadata")
        expr = fp.json_has_key("profile")
        assert isinstance(expr, JsonHasKey)

    def test_field_proxy_and_or_invert(self) -> None:
        from emergent.wire.axis.query._proxy import FieldProxy
        from emergent.wire.axis.query._expr import And, Or, Not

        fp = FieldProxy("name")
        expr_and = (fp == "a") & (fp == "b")
        assert isinstance(expr_and, And)

        # Need to create from Expr objects
        expr_or = (fp == "a") | (fp == "b")
        assert isinstance(expr_or, Or)

        expr_not = ~fp
        assert isinstance(expr_not, Not)

    def test_field_proxy_is_null_is_not_null(self) -> None:
        from emergent.wire.axis.query._proxy import FieldProxy
        from emergent.wire.axis.query._expr import IsNull, IsNotNull

        fp = FieldProxy("email")
        assert isinstance(fp.is_null(), IsNull)
        assert isinstance(fp.is_not_null(), IsNotNull)

    def test_entity_proxy_field_validation(self) -> None:
        from emergent.wire.axis.query._proxy import EntityProxy

        proxy = EntityProxy(User)
        # Valid field
        _ = proxy.name
        # Invalid field
        with pytest.raises(AttributeError, match="has no field"):
            _ = proxy.nonexistent_field

    def test_build_order(self) -> None:
        from emergent.wire.axis.query._proxy import build_order

        order = build_order(User, lambda u: u.balance.desc())
        assert order.field == "balance"
        assert order.ascending is False

    def test_build_order_plain_field(self) -> None:
        from emergent.wire.axis.query._proxy import build_order

        order = build_order(User, lambda u: u.name)
        assert order.field == "name"
        assert order.ascending is True


# ═══════════════════════════════════════════════════════════════════════════════
# 18. Store — RelationalStore, KVStore, APIStore
# ═══════════════════════════════════════════════════════════════════════════════


class TestRelationalStore:
    @pytest.fixture
    def store(self) -> RelationalStore[User]:
        from emergent.wire.axis.query._store import relational_store

        provider = MemoryRelationalProvider[User](
            data=[
                User(id=1, name="alice", email="a@b.com", balance=100),
                User(id=2, name="bob", email="b@b.com", balance=200),
            ],
            key_fn=lambda u: u.id,
        )
        return relational_store(User, provider)

    @pytest.mark.asyncio
    async def test_filter(self, store: RelationalStore[User]) -> None:
        result = await store.filter(lambda u: u.name == "alice").fetch_many()
        assert len(result) == 1
        assert result[0].name == "alice"

    @pytest.mark.asyncio
    async def test_where(self, store: RelationalStore[User]) -> None:
        result = await store.where(lambda u: u.balance > 150).fetch_many()
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_order_by(self, store: RelationalStore[User]) -> None:
        result = await store.order_by(lambda u: u.balance.desc()).fetch_many()
        assert result[0].name == "bob"

    @pytest.mark.asyncio
    async def test_limit(self, store: RelationalStore[User]) -> None:
        result = await store.limit(1).fetch_many()
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_all(self, store: RelationalStore[User]) -> None:
        result = await store.all().fetch_many()
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_insert(self, store: RelationalStore[User]) -> None:
        new_user = User(id=3, name="charlie", email="c@b.com")
        result = await store.insert(new_user)
        assert result.name == "charlie"

    @pytest.mark.asyncio
    async def test_update(self, store: RelationalStore[User]) -> None:
        updated = User(id=1, name="alice_v2", email="a@b.com")
        result = await store.update(updated)
        assert result.name == "alice_v2"

    @pytest.mark.asyncio
    async def test_delete(self, store: RelationalStore[User]) -> None:
        user = User(id=1, name="alice", email="a@b.com")
        await store.delete(user)

    @pytest.mark.asyncio
    async def test_first(self, store: RelationalStore[User]) -> None:
        result = await store.query().first()
        assert result is not None

    @pytest.mark.asyncio
    async def test_count(self, store: RelationalStore[User]) -> None:
        count = await store.query().count()
        assert count == 2

    @pytest.mark.asyncio
    async def test_exists(self, store: RelationalStore[User]) -> None:
        exists = await store.filter(lambda u: u.name == "alice").exists()
        assert exists is True

    @pytest.mark.asyncio
    async def test_distinct(self, store: RelationalStore[User]) -> None:
        result = await store.distinct().fetch_many()
        assert len(result) >= 1

    @pytest.mark.asyncio
    async def test_select(self, store: RelationalStore[User]) -> None:
        result = await store.select(lambda u: u.name).fetch_many()
        assert len(result) >= 1


class TestKVStore:
    @pytest.fixture
    def kv_store(self) -> KVStore[str, str, Any]:
        from emergent.wire.axis.query._store import kv_store

        provider = MemoryKVProvider[str, str]()
        return kv_store(str, key=lambda x: x, provider=provider)

    @pytest.mark.asyncio
    async def test_set_and_get(self, kv_store: KVStore[str, str, Any]) -> None:
        from kungfu import Ok
        await kv_store.set("key1", "value1")
        result = await kv_store.get("key1")
        assert isinstance(result, Ok)
        assert result.value == "value1"

    @pytest.mark.asyncio
    async def test_delete(self, kv_store: KVStore[str, str, Any]) -> None:
        from kungfu import Ok
        await kv_store.set("key1", "value1")
        result = await kv_store.delete("key1")
        assert isinstance(result, Ok)
        assert result.value is True

    @pytest.mark.asyncio
    async def test_exists(self, kv_store: KVStore[str, str, Any]) -> None:
        from kungfu import Ok
        await kv_store.set("key1", "value1")
        result = await kv_store.exists("key1")
        assert isinstance(result, Ok)
        assert result.value is True

    @pytest.mark.asyncio
    async def test_scan(self, kv_store: KVStore[str, str, Any]) -> None:
        from kungfu import Ok
        await kv_store.set("user:1", "alice")
        await kv_store.set("user:2", "bob")
        await kv_store.set("post:1", "hello")
        result = await kv_store.scan("user:*")
        assert isinstance(result, Ok)
        assert len(result.value) == 2

    @pytest.mark.asyncio
    async def test_keys(self, kv_store: KVStore[str, str, Any]) -> None:
        from kungfu import Ok
        await kv_store.set("user:1", "alice")
        await kv_store.set("user:2", "bob")
        result = await kv_store.keys("user:*")
        assert isinstance(result, Ok)
        assert sorted(result.value) == ["user:1", "user:2"]

    @pytest.mark.asyncio
    async def test_put(self, kv_store: KVStore[str, str, Any]) -> None:
        from kungfu import Ok
        await kv_store.put("val1")
        result = await kv_store.get("val1")
        assert isinstance(result, Ok)
        assert result.value == "val1"


class TestAPIStore:
    @pytest.fixture
    def api_store(self) -> APIStore[int, User]:
        from emergent.wire.axis.query._store import api_store

        provider = MemoryAPIProvider[int, User](
            data=[User(id=1, name="alice", email="a@b.com")],
            key_fn=lambda u: u.id,
        )
        return api_store(User, provider, key=lambda u: u.id)

    @pytest.mark.asyncio
    async def test_list(self, api_store: APIStore[int, User]) -> None:
        result = await api_store.list().fetch_many()
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_get(self, api_store: APIStore[int, User]) -> None:
        result = await api_store.get(1)
        assert result is not None
        assert result.name == "alice"

    @pytest.mark.asyncio
    async def test_create(self, api_store: APIStore[int, User]) -> None:
        new_user = User(id=2, name="bob", email="b@b.com")
        result = await api_store.create(new_user)
        assert result.name == "bob"

    @pytest.mark.asyncio
    async def test_update(self, api_store: APIStore[int, User]) -> None:
        updated = User(id=1, name="alice_v2", email="a@b.com")
        result = await api_store.update(1, updated)
        assert result.name == "alice_v2"

    @pytest.mark.asyncio
    async def test_delete(self, api_store: APIStore[int, User]) -> None:
        result = await api_store.delete(1)
        assert result is True

    @pytest.mark.asyncio
    async def test_list_filter(self, api_store: APIStore[int, User]) -> None:
        result = await api_store.list().filter(lambda u: u.name == "alice").fetch_many()
        assert len(result) == 1


# ═══════════════════════════════════════════════════════════════════════════════
# 19. Storage explain
# ═══════════════════════════════════════════════════════════════════════════════


class TestStorageExplain:
    def test_unknown_type(self) -> None:
        from emergent.wire.axis.storage._explain import storage_dict

        class CustomStore:
            pass

        result = storage_dict(CustomStore())
        assert result["type"] == "CustomStore"

    def test_unknown_dataclass(self) -> None:
        from emergent.wire.axis.storage._explain import storage_dict

        @dataclass
        class CustomDC:
            value: int = 42
            name: str = "test"

        result = storage_dict(CustomDC())
        assert result["type"] == "CustomDC"
        assert result["value"] == 42
        assert result["name"] == "test"

    def test_explain_storage_formatting(self) -> None:
        from emergent.wire.axis.storage._explain import explain_storage

        @dataclass
        class MockStore:
            pass

        result = explain_storage(MockStore())
        assert "MockStore" in result

    def test_format_scalar(self) -> None:
        from emergent.wire.axis.storage._explain import _format_scalar

        assert _format_scalar(3.14) == "3.14s"
        assert _format_scalar("hello") == "'hello'"
        assert _format_scalar(42) == "42"

    def test_unknown_with_type_field(self) -> None:
        from emergent.wire.axis.storage._explain import _unknown_dict

        @dataclass
        class StoreWithType:
            backend: type[Any] = int

        result = _unknown_dict(StoreWithType())
        assert result["backend"] == "int"

    def test_unknown_with_object_field(self) -> None:
        from emergent.wire.axis.storage._explain import _unknown_dict

        @dataclass
        class StoreWithObj:
            inner: object = None

        obj = StoreWithObj(inner=[1, 2, 3])
        result = _unknown_dict(obj)
        assert result["inner"] == "list"


# ═══════════════════════════════════════════════════════════════════════════════
# 20. Auth errors — register_auth_errors
# ═══════════════════════════════════════════════════════════════════════════════


class TestAuthErrors:
    def test_authentication_required(self) -> None:
        from emergent.wire.derive.auth.errors import AuthenticationRequired

        err = AuthenticationRequired("bad token")
        assert err.detail == "bad token"

    def test_authorization_failed(self) -> None:
        from emergent.wire.derive.auth.errors import AuthorizationFailed

        err = AuthorizationFailed("admin only")
        assert err.detail == "admin only"

    def test_register_auth_errors(self) -> None:
        from fastapi import FastAPI
        from emergent.wire.derive.auth.errors import register_auth_errors

        app = FastAPI()
        register_auth_errors(app)
        # Check that exception handlers were registered
        from emergent.wire.derive.auth.errors import (
            AuthenticationRequired,
            AuthorizationFailed,
        )
        assert AuthenticationRequired in app.exception_handlers
        assert AuthorizationFailed in app.exception_handlers


# ═══════════════════════════════════════════════════════════════════════════════
# 21. Memory relational provider — mutation methods
# ═══════════════════════════════════════════════════════════════════════════════


class TestMemoryRelationalMutations:
    @pytest.mark.asyncio
    async def test_upsert_insert(self) -> None:
        from emergent.wire.axis.query.providers.memory import MemoryRelationalProvider

        provider = MemoryRelationalProvider[User](key_fn=lambda u: u.id)
        user = User(id=1, name="alice", email="a@b.com")
        result = await provider.upsert(user)
        assert result.name == "alice"
        assert len(provider.data) == 1

    @pytest.mark.asyncio
    async def test_upsert_update(self) -> None:
        from emergent.wire.axis.query.providers.memory import MemoryRelationalProvider

        provider = MemoryRelationalProvider[User](
            data=[User(id=1, name="alice", email="a@b.com")],
            key_fn=lambda u: u.id,
        )
        updated = User(id=1, name="alice_v2", email="new@b.com")
        result = await provider.upsert(updated)
        assert result.name == "alice_v2"
        assert len(provider.data) == 1

    @pytest.mark.asyncio
    async def test_delete_where(self) -> None:
        from emergent.wire.axis.query.providers.memory import MemoryRelationalProvider
        from emergent.wire.axis.query import relational

        provider = MemoryRelationalProvider[User](
            data=[
                User(id=1, name="alice", email="a@b.com"),
                User(id=2, name="bob", email="b@b.com"),
            ]
        )
        q = relational(User).filter(lambda u: u.name == "alice")
        count = await provider.delete_where(q)
        assert count == 1
        assert len(provider.data) == 1

    @pytest.mark.asyncio
    async def test_insert_many(self) -> None:
        from emergent.wire.axis.query.providers.memory import MemoryRelationalProvider

        provider = MemoryRelationalProvider[User]()
        users = [
            User(id=1, name="alice", email="a@b.com"),
            User(id=2, name="bob", email="b@b.com"),
        ]
        result = await provider.insert_many(users)
        assert len(result) == 2
        assert len(provider.data) == 2

    @pytest.mark.asyncio
    async def test_atomic_rollback(self) -> None:
        from emergent.wire.axis.query.providers.memory import MemoryRelationalProvider

        provider = MemoryRelationalProvider[User](
            data=[User(id=1, name="alice", email="a@b.com")]
        )
        with pytest.raises(ValueError):
            async with provider.atomic():
                await provider.insert(User(id=2, name="bob", email="b@b.com"))
                assert len(provider.data) == 2
                raise ValueError("rollback!")
        assert len(provider.data) == 1

    @pytest.mark.asyncio
    async def test_update_not_found_raises(self) -> None:
        from emergent.wire.axis.query.providers.memory import MemoryRelationalProvider

        provider = MemoryRelationalProvider[User](key_fn=lambda u: u.id)
        with pytest.raises(ValueError, match="not found"):
            await provider.update(User(id=999, name="ghost", email=""))

    @pytest.mark.asyncio
    async def test_upsert_no_key_fn_raises(self) -> None:
        from emergent.wire.axis.query.providers.memory import MemoryRelationalProvider

        provider = MemoryRelationalProvider[User]()
        with pytest.raises(TypeError, match="requires key_fn"):
            await provider.upsert(User(id=1, name="a", email="a"))


# ═══════════════════════════════════════════════════════════════════════════════
# 22. BoundRelationalQuerySet — chaining methods
# ═══════════════════════════════════════════════════════════════════════════════


class TestBoundRelationalQuerySet:
    @pytest.fixture
    def bound(self) -> BoundRelationalQuerySet[User]:
        from emergent.wire.axis.query import relational

        provider = MemoryRelationalProvider[User](
            data=[
                User(id=1, name="alice", email="a@b.com", balance=100),
                User(id=2, name="bob", email="b@b.com", balance=200),
                User(id=3, name="charlie", email="c@b.com", balance=300),
            ]
        )
        return BoundRelationalQuerySet(relational(User), provider)

    @pytest.mark.asyncio
    async def test_offset(self, bound: BoundRelationalQuerySet[User]) -> None:
        result = await bound.offset(1).fetch_many()
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_paginate(self, bound: BoundRelationalQuerySet[User]) -> None:
        result = await bound.paginate(1, 2).fetch_many()
        assert len(result) == 2


# ═══════════════════════════════════════════════════════════════════════════════
# 23. BoundAPIQuerySet — chaining
# ═══════════════════════════════════════════════════════════════════════════════


class TestBoundAPIQuerySet:
    @pytest.fixture
    def bound(self) -> BoundAPIQuerySet[int, User]:
        from emergent.wire.axis.query._api import api

        provider = MemoryAPIProvider[int, User](
            data=[
                User(id=1, name="alice", email="a@b.com"),
                User(id=2, name="bob", email="b@b.com"),
            ],
            key_fn=lambda u: u.id,
        )
        return BoundAPIQuerySet(api(User, key=lambda u: u.id).list(), provider)

    @pytest.mark.asyncio
    async def test_filter(self, bound: BoundAPIQuerySet[int, User]) -> None:
        result = await bound.filter(lambda u: u.name == "alice").fetch_many()
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_fetch_one(self, bound: BoundAPIQuerySet[int, User]) -> None:
        result = await bound.fetch_one()
        assert result is not None

    @pytest.mark.asyncio
    async def test_order_by(self, bound: BoundAPIQuerySet[int, User]) -> None:
        result = await bound.order_by(lambda u: u.name.desc()).fetch_many()
        assert result[0].name == "bob"


# ═══════════════════════════════════════════════════════════════════════════════
# 24. DeltaField compile methods
# ═══════════════════════════════════════════════════════════════════════════════


class TestDeltaFieldCompile:
    def test_compile_delta(self) -> None:
        from emergent.wire.axis.schema.dialects.delta import DeltaField
        from emergent.wire.axis._capability import DeltaContext

        df = DeltaField("numeric")
        ctx = DeltaContext(field_name="balance", field_type=int)
        result = df.compile_delta(ctx)
        assert result.delta_kind == "numeric"

    def test_compile_openapi(self) -> None:
        from emergent.wire.axis.schema.dialects.delta import DeltaField
        from emergent.wire.axis._capability import OpenAPIContext

        df = DeltaField("string")
        ctx = OpenAPIContext(field_name="notes", field_type=str)
        result = df.compile_openapi(ctx)
        assert result.schema.get("x-delta-type") == "string"


# ═══════════════════════════════════════════════════════════════════════════════
# 25. Numeric delta edge cases
# ═══════════════════════════════════════════════════════════════════════════════


class TestNumericDeltaEdgeCases:
    def test_multiply_with_add(self) -> None:
        from emergent.wire.axis.schema.dialects.delta import NumericDelta

        d = NumericDelta(add=10, multiply=2.0)
        # add first: 100 + 10 = 110, then multiply: 110 * 2 = 220
        result = d.apply(100)
        assert result == 220.0

    def test_compose_multiply_both(self) -> None:
        from emergent.wire.axis.schema.dialects.delta import _compose_field_deltas, NumericDelta

        d1 = NumericDelta(multiply=2.0)
        d2 = NumericDelta(multiply=3.0)
        result = _compose_field_deltas(d1, d2)
        assert isinstance(result, NumericDelta)
        assert result.multiply == 6.0

    def test_compose_multiply_only_d1(self) -> None:
        from emergent.wire.axis.schema.dialects.delta import _compose_field_deltas, NumericDelta

        d1 = NumericDelta(multiply=2.0)
        d2 = NumericDelta(add=10)
        result = _compose_field_deltas(d1, d2)
        assert isinstance(result, NumericDelta)
        assert result.multiply == 2.0

    def test_compose_set_last_wins(self) -> None:
        from emergent.wire.axis.schema.dialects.delta import _compose_field_deltas, NumericDelta

        d1 = NumericDelta(set=100)
        d2 = NumericDelta(set=200)
        result = _compose_field_deltas(d1, d2)
        assert result.set == 200

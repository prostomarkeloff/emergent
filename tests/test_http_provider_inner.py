"""Tests for HTTP API provider internals — missed lines coverage.

Covers:
- QueryParamFilters._encode_expr: Or case, unsupported expr
- BodyFilters._encode_expr: Ne, Lt, Le, Gt, Ge, In, And, Or, unsupported expr
- HTTPAPIProvider.fetch_one: ListOp branch, unsupported op ValueError
- HTTPAPIProvider.fetch_many: data is not a list (wraps in [items])
- HTTPAPIProvider.execute: UpdateOp partial=True (PATCH), unsupported op ValueError
- HTTPAPIProvider.delete: non-DeleteOp raises ValueError
- api() factory function
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx
import pytest

from emergent.wire.axis.query._api import (
    APIQuerySet,
    ListOp,
    GetOp,
    CreateOp,
    UpdateOp,
    DeleteOp,
    FilterMod,
)
from emergent.wire.axis.query._expr import (
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
    Not,
)
from emergent.wire.axis.query.contrib._impls._http import (
    QueryParamFilters,
    BodyFilters,
    HTTPAPIProvider,
    api as http_api,
    PageSizePagination,
)


# ─── Test entity ─────────────────────────────────────────────────────────────


@dataclass
class User:
    id: int
    name: str
    balance: int = 0


def _user_key(u: User) -> int:
    return u.id


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _make_provider(
    handler: httpx.MockTransport,
    data_path: str = "data",
) -> HTTPAPIProvider[User]:
    client = httpx.AsyncClient(transport=handler)
    return HTTPAPIProvider(
        entity=User,
        client=client,
        base_url="https://api.example.com/users",
        pagination=PageSizePagination(),
        filter_encoding=QueryParamFilters(),
        data_path=data_path,
    )


def _qs(
    op: ListOp | GetOp[int] | CreateOp[User] | UpdateOp[int, User] | DeleteOp[int] | None = None,
    mods: tuple[FilterMod, ...] = (),
) -> APIQuerySet[int, User]:
    return APIQuerySet(entity=User, key_fn=_user_key, op=op, mods=mods)


# ═══════════════════════════════════════════════════════════════════════════════
# QueryParamFilters._encode_expr — missed lines 255-256
# ═══════════════════════════════════════════════════════════════════════════════


class TestQueryParamFiltersOrCase:
    """Lines 253-254: Or(_, _) raises ValueError."""

    def test_or_expression_raises_value_error(self) -> None:
        enc = QueryParamFilters()
        expr = Or(Eq(Field("name"), Const("alice")), Eq(Field("name"), Const("bob")))
        with pytest.raises(ValueError, match="OR filters not supported"):
            enc.encode(expr, User, None)


class TestQueryParamFiltersUnsupported:
    """Lines 255-256: default case raises ValueError for unsupported expression."""

    def test_unsupported_expression_raises_value_error(self) -> None:
        enc = QueryParamFilters()
        # Not() is not handled by QueryParamFilters._encode_expr
        expr = Not(Eq(Field("name"), Const("alice")))
        with pytest.raises(ValueError, match="Unsupported filter expression"):
            enc.encode(expr, User, None)


# ═══════════════════════════════════════════════════════════════════════════════
# BodyFilters._encode_expr — missed lines 285, 289, 296-297
# ═══════════════════════════════════════════════════════════════════════════════


class TestBodyFiltersNe:
    """Line 281 (Ne case)."""

    def test_ne_expression(self) -> None:
        enc = BodyFilters()
        expr = Ne(Field("name"), Const("alice"))
        result = enc.encode(expr, User, None)
        assert result == {"filter": {"name": {"ne": "alice"}}}


class TestBodyFiltersLt:
    """Line 283 (Lt case)."""

    def test_lt_expression(self) -> None:
        enc = BodyFilters()
        expr = Lt(Field("balance"), Const(100))
        result = enc.encode(expr, User, None)
        assert result == {"filter": {"balance": {"lt": 100}}}


class TestBodyFiltersLe:
    """Line 285 (Le case)."""

    def test_le_expression(self) -> None:
        enc = BodyFilters()
        expr = Le(Field("balance"), Const(100))
        result = enc.encode(expr, User, None)
        assert result == {"filter": {"balance": {"lte": 100}}}


class TestBodyFiltersGt:
    """Line 287 (Gt case)."""

    def test_gt_expression(self) -> None:
        enc = BodyFilters()
        expr = Gt(Field("balance"), Const(100))
        result = enc.encode(expr, User, None)
        assert result == {"filter": {"balance": {"gt": 100}}}


class TestBodyFiltersGe:
    """Line 289 (Ge case)."""

    def test_ge_expression(self) -> None:
        enc = BodyFilters()
        expr = Ge(Field("balance"), Const(100))
        result = enc.encode(expr, User, None)
        assert result == {"filter": {"balance": {"gte": 100}}}


class TestBodyFiltersIn:
    """Line 291 (In case)."""

    def test_in_expression(self) -> None:
        enc = BodyFilters()
        expr = In(Field("name"), ("alice", "bob"))
        result = enc.encode(expr, User, None)
        assert result == {"filter": {"name": {"in": ["alice", "bob"]}}}


class TestBodyFiltersAnd:
    """Line 293 (And case)."""

    def test_and_expression(self) -> None:
        enc = BodyFilters()
        expr = And(Eq(Field("name"), Const("alice")), Gt(Field("balance"), Const(0)))
        result = enc.encode(expr, User, None)
        assert result == {
            "filter": {
                "and": [
                    {"name": {"eq": "alice"}},
                    {"balance": {"gt": 0}},
                ],
            },
        }


class TestBodyFiltersOr:
    """Line 295 (Or case)."""

    def test_or_expression(self) -> None:
        enc = BodyFilters()
        expr = Or(Eq(Field("name"), Const("alice")), Eq(Field("name"), Const("bob")))
        result = enc.encode(expr, User, None)
        assert result == {
            "filter": {
                "or": [
                    {"name": {"eq": "alice"}},
                    {"name": {"eq": "bob"}},
                ],
            },
        }


class TestBodyFiltersUnsupported:
    """Lines 296-297: default case raises ValueError for unsupported expression."""

    def test_unsupported_expression_raises_value_error(self) -> None:
        enc = BodyFilters()
        expr = Not(Eq(Field("name"), Const("alice")))
        with pytest.raises(ValueError, match="Unsupported filter expression"):
            enc.encode(expr, User, None)


# ═══════════════════════════════════════════════════════════════════════════════
# HTTPAPIProvider.fetch_one — missed lines 347, 350-353
# ═══════════════════════════════════════════════════════════════════════════════


class TestFetchOneListOp:
    """Lines 350-352: fetch_one with ListOp delegates to fetch_many, returns first."""

    @pytest.mark.anyio
    async def test_fetch_one_with_list_op_returns_first(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={"data": [{"id": 1, "name": "Alice", "balance": 100}]},
            )

        provider = _make_provider(httpx.MockTransport(handler))
        qs = _qs(op=ListOp())
        result = await provider.fetch_one(qs)
        assert result is not None
        assert result.id == 1
        assert result.name == "Alice"

    @pytest.mark.anyio
    async def test_fetch_one_with_list_op_empty_returns_none(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": []})

        provider = _make_provider(httpx.MockTransport(handler))
        qs = _qs(op=ListOp())
        result = await provider.fetch_one(qs)
        assert result is None


class _NoRaiseHTTPAPIProvider(HTTPAPIProvider[User]):
    """Subclass that does not call raise_for_status in _request.

    This allows testing the 404-check branch in fetch_one (line 347),
    which is unreachable via the default _request that always raises on 4xx.
    """

    async def _request(
        self,
        method: str,
        url: str,
        params: dict[str, str] | None = None,
        json: dict[str, str] | None = None,
    ) -> httpx.Response:
        headers: dict[str, str] = {}
        if self.auth:
            self.auth.apply(headers)
        return await self.client.request(
            method, url, params=params, json=json, headers=headers,
        )


class TestFetchOneGetOp404:
    """Line 347: fetch_one with GetOp returns None on 404.

    Note: The default _request calls raise_for_status(), so the 404 check
    in fetch_one is only reachable if _request is overridden to not raise.
    We use _NoRaiseHTTPAPIProvider to simulate that scenario.
    """

    @pytest.mark.anyio
    async def test_fetch_one_get_404_returns_none(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)
        provider = _NoRaiseHTTPAPIProvider(
            entity=User,
            client=client,
            base_url="https://api.example.com/users",
            pagination=PageSizePagination(),
            filter_encoding=QueryParamFilters(),
            data_path="data",
        )
        qs = _qs(op=GetOp(id=999))
        result = await provider.fetch_one(qs)
        assert result is None


class TestFetchOneUnsupportedOp:
    """Line 353: fetch_one with unsupported op raises ValueError."""

    @pytest.mark.anyio
    async def test_fetch_one_with_create_op_raises(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={})

        provider = _make_provider(httpx.MockTransport(handler))
        qs = _qs(op=CreateOp(entity=User(id=1, name="Alice")))
        with pytest.raises(ValueError, match="fetch_one requires Get or List op"):
            await provider.fetch_one(qs)


# ═══════════════════════════════════════════════════════════════════════════════
# HTTPAPIProvider.fetch_many — missed line 402
# ═══════════════════════════════════════════════════════════════════════════════


class TestFetchManyNonListData:
    """Line 402: when data at data_path is not a list, wraps it in [items]."""

    @pytest.mark.anyio
    async def test_fetch_many_wraps_single_item_in_list(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            # data_path points to a dict, not a list
            return httpx.Response(
                200,
                json={"data": {"id": 1, "name": "Alice", "balance": 50}},
            )

        provider = _make_provider(httpx.MockTransport(handler))
        qs = _qs(op=ListOp())
        result = await provider.fetch_many(qs)
        assert len(result) == 1
        assert result[0].id == 1
        assert result[0].name == "Alice"

    @pytest.mark.anyio
    async def test_fetch_many_none_data_returns_empty(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            # data_path "data" resolves to None (key missing)
            return httpx.Response(200, json={"items": []})

        provider = _make_provider(httpx.MockTransport(handler))
        qs = _qs(op=ListOp())
        result = await provider.fetch_many(qs)
        assert result == []


class TestFetchManyUnsupportedOp:
    """Line 358: fetch_many with non-ListOp raises ValueError."""

    @pytest.mark.anyio
    async def test_fetch_many_with_get_op_raises(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={})

        provider = _make_provider(httpx.MockTransport(handler))
        qs = _qs(op=GetOp(id=1))
        with pytest.raises(ValueError, match="fetch_many requires List op"):
            await provider.fetch_many(qs)


# ═══════════════════════════════════════════════════════════════════════════════
# HTTPAPIProvider.execute — missed lines 426, 431
# ═══════════════════════════════════════════════════════════════════════════════


class TestExecuteUpdatePartial:
    """Line 418 (partial=True): execute with UpdateOp partial=True sends PATCH."""

    @pytest.mark.anyio
    async def test_execute_update_partial_uses_patch(self) -> None:
        captured_method: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured_method.append(request.method)
            return httpx.Response(
                200,
                json={"id": 1, "name": "Updated Alice", "balance": 200},
            )

        provider = _make_provider(httpx.MockTransport(handler))
        updated_user = User(id=1, name="Updated Alice", balance=200)
        qs = _qs(op=UpdateOp(id=1, entity=updated_user, partial=True))
        result = await provider.execute(qs)
        assert captured_method[0] == "PATCH"
        assert result.name == "Updated Alice"

    @pytest.mark.anyio
    async def test_execute_update_full_uses_put(self) -> None:
        captured_method: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured_method.append(request.method)
            return httpx.Response(
                200,
                json={"id": 1, "name": "Full Update", "balance": 300},
            )

        provider = _make_provider(httpx.MockTransport(handler))
        updated_user = User(id=1, name="Full Update", balance=300)
        qs = _qs(op=UpdateOp(id=1, entity=updated_user, partial=False))
        result = await provider.execute(qs)
        assert captured_method[0] == "PUT"
        assert result.name == "Full Update"


class TestExecuteUnsupportedOp:
    """Line 426: execute with unsupported op raises ValueError."""

    @pytest.mark.anyio
    async def test_execute_with_delete_op_raises(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={})

        provider = _make_provider(httpx.MockTransport(handler))
        qs = _qs(op=DeleteOp(id=1))
        with pytest.raises(ValueError, match="execute requires Create or Update op"):
            await provider.execute(qs)

    @pytest.mark.anyio
    async def test_execute_with_list_op_raises(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={})

        provider = _make_provider(httpx.MockTransport(handler))
        qs = _qs(op=ListOp())
        with pytest.raises(ValueError, match="execute requires Create or Update op"):
            await provider.execute(qs)


# ═══════════════════════════════════════════════════════════════════════════════
# HTTPAPIProvider.delete — missed line 431
# ═══════════════════════════════════════════════════════════════════════════════


class TestDeleteUnsupportedOp:
    """Line 431: delete with non-DeleteOp raises ValueError."""

    @pytest.mark.anyio
    async def test_delete_with_list_op_raises(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={})

        provider = _make_provider(httpx.MockTransport(handler))
        qs = _qs(op=ListOp())
        with pytest.raises(ValueError, match="delete requires Delete op"):
            await provider.delete(qs)


# ═══════════════════════════════════════════════════════════════════════════════
# api() factory function — missed line 578
# ═══════════════════════════════════════════════════════════════════════════════


class TestApiFactory:
    """Line 578: api() factory returns HTTPAPIBuilder."""

    def test_api_returns_builder(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import HTTPAPIBuilder

        builder = http_api(User)
        assert isinstance(builder, HTTPAPIBuilder)

    def test_api_with_profile(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import HTTPAPIBuilder

        class InternalAPI:
            pass

        builder = http_api(User, profile=InternalAPI)
        assert isinstance(builder, HTTPAPIBuilder)

    def test_api_builder_chain_and_build(self) -> None:
        transport = httpx.MockTransport(lambda r: httpx.Response(200, json={}))
        client = httpx.AsyncClient(transport=transport)
        provider = http_api(User).base("https://api.example.com/users").build(client)
        assert isinstance(provider, HTTPAPIProvider)
        assert provider.base_url == "https://api.example.com/users"
        assert provider.entity is User

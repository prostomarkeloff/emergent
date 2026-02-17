"""Tests for APIQuerySet — building and introspection."""

from __future__ import annotations

from dataclasses import dataclass

from emergent.wire.axis.query._api import (
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
    api,
)
from emergent.wire.axis.query._proxy import OrderSpec


@dataclass
class User:
    id: str
    name: str
    active: bool = True


def _user_key(u: User) -> str:
    return u.id


# ─── Factory ─────────────────────────────────────────────────────────────────


class TestFactory:
    def test_api_creates_empty(self) -> None:
        q = api(User, key=_user_key)
        assert q.entity is User
        assert q.op is None
        assert q.mods == ()


# ─── CRUD Ops ────────────────────────────────────────────────────────────────


class TestCRUDOps:
    def test_list(self) -> None:
        q = api(User, key=_user_key).list()
        assert isinstance(q.op, ListOp)

    def test_get(self) -> None:
        q = api(User, key=_user_key).get("user-123")
        assert isinstance(q.op, GetOp)
        assert q.op.id == "user-123"

    def test_create(self) -> None:
        user = User(id="1", name="alice")
        q = api(User, key=_user_key).create(user)
        assert isinstance(q.op, CreateOp)
        assert q.op.entity is user

    def test_update(self) -> None:
        user = User(id="1", name="alice_updated")
        q = api(User, key=_user_key).update("1", user)
        assert isinstance(q.op, UpdateOp)
        assert q.op.id == "1"
        assert q.op.entity is user
        assert q.op.partial is False

    def test_update_partial(self) -> None:
        user = User(id="1", name="alice_updated")
        q = api(User, key=_user_key).update("1", user, partial=True)
        assert isinstance(q.op, UpdateOp)
        assert q.op.partial is True

    def test_delete(self) -> None:
        q = api(User, key=_user_key).delete("user-123")
        assert isinstance(q.op, DeleteOp)
        assert q.op.id == "user-123"


# ─── Modifiers ───────────────────────────────────────────────────────────────


class TestModifiers:
    def test_filter(self) -> None:
        q = api(User, key=_user_key).list().filter(lambda u: u.active == True)
        assert len(q.mods) == 1
        assert isinstance(q.mods[0], FilterMod)

    def test_order_by(self) -> None:
        q = api(User, key=_user_key).list().order_by(lambda u: u.name)
        assert isinstance(q.mods[0], OrderMod)

    def test_page(self) -> None:
        q = api(User, key=_user_key).list().page(2, per_page=50)
        mod = q.mods[0]
        assert isinstance(mod, PageMod)
        assert mod.page == 2
        assert mod.per_page == 50

    def test_cursor(self) -> None:
        q = api(User, key=_user_key).list().cursor("abc123", limit=50)
        mod = q.mods[0]
        assert isinstance(mod, CursorMod)
        assert mod.cursor == "abc123"
        assert mod.limit == 50

    def test_offset(self) -> None:
        q = api(User, key=_user_key).list().offset(100, limit=50)
        mod = q.mods[0]
        assert isinstance(mod, OffsetMod)
        assert mod.offset == 100
        assert mod.limit == 50

    def test_select(self) -> None:
        q = api(User, key=_user_key).list().select(lambda u: u.id, lambda u: u.name)
        mod = q.mods[0]
        assert isinstance(mod, SelectMod)
        assert mod.fields == ("id", "name")

    def test_search(self) -> None:
        q = api(User, key=_user_key).list().search("alice")
        mod = q.mods[0]
        assert isinstance(mod, SearchMod)
        assert mod.query == "alice"

    def test_include(self) -> None:
        q = api(User, key=_user_key).list().include("posts", "comments")
        mod = q.mods[0]
        assert isinstance(mod, IncludeMod)
        assert mod.relations == ("posts", "comments")

    def test_chaining(self) -> None:
        q = (
            api(User, key=_user_key)
            .list()
            .filter(lambda u: u.active == True)
            .order_by(lambda u: u.name)
            .page(1, per_page=20)
            .include("posts")
        )
        assert len(q.mods) == 4

    def test_immutable(self) -> None:
        q1 = api(User, key=_user_key).list()
        q2 = q1.filter(lambda u: u.active == True)
        assert len(q1.mods) == 0
        assert len(q2.mods) == 1


# ─── Introspection ───────────────────────────────────────────────────────────


class TestIntrospection:
    def test_filters(self) -> None:
        q = (
            api(User, key=_user_key)
            .list()
            .filter(lambda u: u.active == True)
            .filter(lambda u: u.name == "alice")
        )
        assert len(q.filters) == 2

    def test_ordering(self) -> None:
        q = api(User, key=_user_key).list().order_by(lambda u: u.name.desc())
        assert len(q.ordering) == 1
        assert q.ordering[0] == OrderSpec("name", ascending=False)

    def test_pagination_page(self) -> None:
        q = api(User, key=_user_key).list().page(1)
        assert isinstance(q.pagination, PageMod)

    def test_pagination_cursor(self) -> None:
        q = api(User, key=_user_key).list().cursor("abc")
        assert isinstance(q.pagination, CursorMod)

    def test_pagination_none(self) -> None:
        q = api(User, key=_user_key).list()
        assert q.pagination is None


# ─── Pagination Replacement ─────────────────────────────────────────────────


class TestPaginationReplacement:
    def test_page_then_offset_replaces(self) -> None:
        q = api(User, key=_user_key).list().page(1, per_page=20).offset(50, limit=10)
        pagination_mods = [m for m in q.mods if isinstance(m, (PageMod, CursorMod, OffsetMod))]
        assert len(pagination_mods) == 1
        assert isinstance(pagination_mods[0], OffsetMod)
        assert pagination_mods[0].offset == 50

    def test_page_then_page_replaces(self) -> None:
        q = api(User, key=_user_key).list().page(1, per_page=20).page(2, per_page=50)
        pagination_mods = [m for m in q.mods if isinstance(m, (PageMod, CursorMod, OffsetMod))]
        assert len(pagination_mods) == 1
        assert isinstance(pagination_mods[0], PageMod)
        assert pagination_mods[0].page == 2
        assert pagination_mods[0].per_page == 50

    def test_cursor_then_page_replaces(self) -> None:
        q = api(User, key=_user_key).list().cursor("abc", limit=10).page(1)
        assert isinstance(q.pagination, PageMod)

    def test_filter_and_page_coexist(self) -> None:
        q = api(User, key=_user_key).list().filter(lambda u: u.active == True).page(1)
        assert len(q.mods) == 2
        assert isinstance(q.mods[0], FilterMod)
        assert isinstance(q.mods[1], PageMod)


# ─── Integration: API Query Pipeline ────────────────────────────────────────


class TestIntegrationAPIQueryPipeline:
    def test_full_list_pipeline(self) -> None:
        q = (
            api(User, key=_user_key)
            .list()
            .filter(lambda u: u.active == True)
            .filter(lambda u: u.name != "admin")
            .order_by(lambda u: u.name)
            .page(2, per_page=25)
            .select(lambda u: u.id, lambda u: u.name)
        )
        assert isinstance(q.op, ListOp)
        assert len(q.mods) == 5
        assert isinstance(q.mods[0], FilterMod)
        assert isinstance(q.mods[1], FilterMod)
        assert isinstance(q.mods[2], OrderMod)
        assert isinstance(q.mods[3], PageMod)
        assert isinstance(q.mods[4], SelectMod)
        # Introspection
        assert len(q.filters) == 2
        assert len(q.ordering) == 1
        assert q.ordering[0] == OrderSpec("name", ascending=True)
        assert isinstance(q.pagination, PageMod)
        assert q.pagination.page == 2
        assert q.pagination.per_page == 25

    def test_update_with_filter_mods(self) -> None:
        user = User(id="1", name="alice_updated")
        q = api(User, key=_user_key).update("1", user)
        assert isinstance(q.op, UpdateOp)
        assert q.op.id == "1"
        assert q.op.entity is user
        assert q.op.partial is False
        assert q.mods == ()

    def test_crud_op_types(self) -> None:
        list_q = api(User, key=_user_key).list()
        get_q = api(User, key=_user_key).get("123")
        create_q = api(User, key=_user_key).create(User(id="1", name="alice"))
        update_q = api(User, key=_user_key).update("1", User(id="1", name="bob"))
        delete_q = api(User, key=_user_key).delete("123")

        assert isinstance(list_q.op, ListOp)
        assert isinstance(get_q.op, GetOp)
        assert isinstance(create_q.op, CreateOp)
        assert isinstance(update_q.op, UpdateOp)
        assert isinstance(delete_q.op, DeleteOp)

    def test_immutability_pipeline(self) -> None:
        q0 = api(User, key=_user_key).list()
        q1 = q0.filter(lambda u: u.active == True)
        q2 = q1.order_by(lambda u: u.name)
        q3 = q2.page(1, per_page=10)
        assert len(q0.mods) == 0
        assert len(q1.mods) == 1
        assert len(q2.mods) == 2
        assert len(q3.mods) == 3

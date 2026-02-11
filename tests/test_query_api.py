"""Tests for APIQuerySet — building and introspection."""

from __future__ import annotations

from dataclasses import dataclass

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
    api,
)
from emergent.wire.axis.query._proxy import OrderSpec


@dataclass
class User:
    id: str
    name: str
    active: bool = True


# ─── Factory ─────────────────────────────────────────────────────────────────


class TestFactory:
    def test_api_creates_empty(self):
        q = api(User)
        assert q.entity is User
        assert q.op is None
        assert q.mods == ()


# ─── CRUD Ops ────────────────────────────────────────────────────────────────


class TestCRUDOps:
    def test_list(self):
        q = api(User).list()
        assert isinstance(q.op, ListOp)

    def test_get(self):
        q = api(User).get("user-123")
        assert isinstance(q.op, GetOp)
        assert q.op.id == "user-123"

    def test_create(self):
        user = User(id="1", name="alice")
        q = api(User).create(user)
        assert isinstance(q.op, CreateOp)
        assert q.op.entity is user

    def test_update(self):
        user = User(id="1", name="alice_updated")
        q = api(User).update("1", user)
        assert isinstance(q.op, UpdateOp)
        assert q.op.id == "1"
        assert q.op.entity is user
        assert q.op.partial is False

    def test_update_partial(self):
        user = User(id="1", name="alice_updated")
        q = api(User).update("1", user, partial=True)
        assert q.op.partial is True

    def test_delete(self):
        q = api(User).delete("user-123")
        assert isinstance(q.op, DeleteOp)
        assert q.op.id == "user-123"


# ─── Modifiers ───────────────────────────────────────────────────────────────


class TestModifiers:
    def test_filter(self):
        q = api(User).list().filter(lambda u: u.active == True)
        assert len(q.mods) == 1
        assert isinstance(q.mods[0], FilterMod)

    def test_order_by(self):
        q = api(User).list().order_by(lambda u: u.name)
        assert isinstance(q.mods[0], OrderMod)

    def test_page(self):
        q = api(User).list().page(2, per_page=50)
        mod = q.mods[0]
        assert isinstance(mod, PageMod)
        assert mod.page == 2
        assert mod.per_page == 50

    def test_cursor(self):
        q = api(User).list().cursor("abc123", limit=50)
        mod = q.mods[0]
        assert isinstance(mod, CursorMod)
        assert mod.cursor == "abc123"
        assert mod.limit == 50

    def test_offset(self):
        q = api(User).list().offset(100, limit=50)
        mod = q.mods[0]
        assert isinstance(mod, OffsetMod)
        assert mod.offset == 100
        assert mod.limit == 50

    def test_select(self):
        q = api(User).list().select(lambda u: u.id, lambda u: u.name)
        mod = q.mods[0]
        assert isinstance(mod, SelectMod)
        assert mod.fields == ("id", "name")

    def test_search(self):
        q = api(User).list().search("alice")
        mod = q.mods[0]
        assert isinstance(mod, SearchMod)
        assert mod.query == "alice"

    def test_include(self):
        q = api(User).list().include("posts", "comments")
        mod = q.mods[0]
        assert isinstance(mod, IncludeMod)
        assert mod.relations == ("posts", "comments")

    def test_chaining(self):
        q = (
            api(User)
            .list()
            .filter(lambda u: u.active == True)
            .order_by(lambda u: u.name)
            .page(1, per_page=20)
            .include("posts")
        )
        assert len(q.mods) == 4

    def test_immutable(self):
        q1 = api(User).list()
        q2 = q1.filter(lambda u: u.active == True)
        assert len(q1.mods) == 0
        assert len(q2.mods) == 1


# ─── Introspection ───────────────────────────────────────────────────────────


class TestIntrospection:
    def test_filters(self):
        q = (
            api(User)
            .list()
            .filter(lambda u: u.active == True)
            .filter(lambda u: u.name == "alice")
        )
        assert len(q.filters) == 2

    def test_ordering(self):
        q = api(User).list().order_by(lambda u: u.name.desc())
        assert len(q.ordering) == 1
        assert q.ordering[0] == OrderSpec("name", ascending=False)

    def test_pagination_page(self):
        q = api(User).list().page(1)
        assert isinstance(q.pagination, PageMod)

    def test_pagination_cursor(self):
        q = api(User).list().cursor("abc")
        assert isinstance(q.pagination, CursorMod)

    def test_pagination_none(self):
        q = api(User).list()
        assert q.pagination is None


# ─── Pagination Replacement ─────────────────────────────────────────────────


class TestPaginationReplacement:
    def test_page_then_offset_replaces(self):
        q = api(User).list().page(1, per_page=20).offset(50, limit=10)
        pagination_mods = [m for m in q.mods if isinstance(m, (PageMod, CursorMod, OffsetMod))]
        assert len(pagination_mods) == 1
        assert isinstance(pagination_mods[0], OffsetMod)
        assert pagination_mods[0].offset == 50

    def test_page_then_page_replaces(self):
        q = api(User).list().page(1, per_page=20).page(2, per_page=50)
        pagination_mods = [m for m in q.mods if isinstance(m, (PageMod, CursorMod, OffsetMod))]
        assert len(pagination_mods) == 1
        assert isinstance(pagination_mods[0], PageMod)
        assert pagination_mods[0].page == 2
        assert pagination_mods[0].per_page == 50

    def test_cursor_then_page_replaces(self):
        q = api(User).list().cursor("abc", limit=10).page(1)
        assert isinstance(q.pagination, PageMod)

    def test_filter_and_page_coexist(self):
        q = api(User).list().filter(lambda u: u.active == True).page(1)
        assert len(q.mods) == 2
        assert isinstance(q.mods[0], FilterMod)
        assert isinstance(q.mods[1], PageMod)

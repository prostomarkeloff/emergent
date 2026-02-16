"""Tests for derivelib._dialect — Op, Dialect, trigger generators, op transforms."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Annotated

from emergent.wire.axis.schema import Identity
from emergent.wire.axis.surface.triggers.cli import CLITrigger
from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger

from derivelib._dialect import (
    CLITriggers,
    ChainedPattern,
    DEFAULT_REST_ROUTES,
    Dialect,
    HTTPTriggers,
    NestedHTTPTriggers,
    Op,
    by_effect,
    dialect,
    exclude_ops,
    select_ops,
    with_caps,
)
from derivelib._effects import Creates, Deletes, Mutation, Read, Updates
from derivelib._handler_templates import DeleteOne, FetchMany, FetchOneById, InsertNew
from derivelib._project import (
    entity_response,
    id_only,
    list_response,
    no_fields,
    non_id,
    ok_response,
)
from derivelib.axes.surface import DeriveOp

from .conftest import User


class _Node:
    pass


LIST = Op("List", no_fields(), list_response(), FetchMany(), effects=(Read(),))
GET = Op("Get", id_only(), entity_response(), FetchOneById(), effects=(Read(),))
CREATE = Op("Create", non_id(), entity_response(), InsertNew(), effects=(Creates(),))
DELETE = Op("Delete", id_only(), ok_response(), DeleteOne(), effects=(Deletes(),))


class TestOp:
    def test_fields(self) -> None:
        assert LIST.name == "List"
        assert LIST.capabilities == ()
        assert len(LIST.effects) == 1

    def test_frozen(self) -> None:
        import dataclasses as dc
        assert dc.is_dataclass(LIST)


class TestHTTPTriggers:
    def test_list_route(self) -> None:
        triggers = HTTPTriggers("/api/users")
        trigger = triggers(User, LIST)
        assert isinstance(trigger, HTTPRouteTrigger)
        assert trigger.method == "GET"
        assert trigger.path == "/api/users"

    def test_get_route_with_id(self) -> None:
        triggers = HTTPTriggers("/api/users")
        trigger = triggers(User, GET)
        assert isinstance(trigger, HTTPRouteTrigger)
        assert trigger.method == "GET"
        assert "{id}" in trigger.path

    def test_create_route(self) -> None:
        triggers = HTTPTriggers("/api/users")
        trigger = triggers(User, CREATE)
        assert isinstance(trigger, HTTPRouteTrigger)
        assert trigger.method == "POST"

    def test_unknown_op_gets_post(self) -> None:
        custom_op = Op("Search", no_fields(), list_response(), FetchMany())
        triggers = HTTPTriggers("/api/users")
        trigger = triggers(User, custom_op)
        assert isinstance(trigger, HTTPRouteTrigger)
        assert trigger.method == "POST"
        assert "search" in trigger.path


class TestCLITriggers:
    def test_command_name(self) -> None:
        triggers = CLITriggers("user")
        trigger = triggers(User, LIST)
        assert isinstance(trigger, CLITrigger)
        assert trigger.command == "user-list"

    def test_all_ops(self) -> None:
        triggers = CLITriggers("item")
        for op in (LIST, GET, CREATE, DELETE):
            trigger = triggers(User, op)
            assert isinstance(trigger, CLITrigger)
            assert trigger.command.startswith("item-")


class TestNestedHTTPTriggers:
    def test_nested_list(self) -> None:
        triggers = NestedHTTPTriggers("/users", ("user_id",), "posts")
        trigger = triggers(User, LIST)
        assert isinstance(trigger, HTTPRouteTrigger)
        assert trigger.method == "GET"
        assert "/users/{user_id}/posts" == trigger.path

    def test_nested_create(self) -> None:
        triggers = NestedHTTPTriggers("/users", ("user_id",), "posts")
        trigger = triggers(User, CREATE)
        assert isinstance(trigger, HTTPRouteTrigger)
        assert trigger.method == "POST"
        assert "/users/{user_id}/posts" == trigger.path


class TestDialect:
    def test_compile_produces_steps(self) -> None:
        d = dialect(
            LIST, GET,
            triggers=HTTPTriggers("/api/users"),
            provider_node=_Node,
        )
        steps = d.compile(User)
        assert len(steps) > 0

    def test_compile_has_derive_ops(self) -> None:
        d = dialect(
            LIST, GET,
            triggers=HTTPTriggers("/api/users"),
            provider_node=_Node,
        )
        steps = d.compile(User)
        derive_ops = [s for s in steps if isinstance(s, DeriveOp)]
        assert len(derive_ops) == 2

    def test_chain_returns_chained(self) -> None:
        d = dialect(
            LIST, GET,
            triggers=HTTPTriggers("/api/users"),
            provider_node=_Node,
        )
        chained = d.chain(lambda steps: steps)
        assert isinstance(chained, ChainedPattern)


class TestChainedPattern:
    def test_applies_transforms(self) -> None:
        d = dialect(
            LIST, GET, CREATE,
            triggers=HTTPTriggers("/api/users"),
            provider_node=_Node,
        )

        def remove_creates(steps: tuple) -> tuple:
            return tuple(
                s for s in steps
                if not (isinstance(s, DeriveOp) and s.name == "Create")
            )

        chained = d.chain(remove_creates)
        steps = chained.compile(User)
        derive_ops = [s for s in steps if isinstance(s, DeriveOp)]
        names = [op.name for op in derive_ops]
        assert "Create" not in names
        assert "List" in names

    def test_double_chain(self) -> None:
        d = dialect(LIST, triggers=HTTPTriggers("/api"), provider_node=_Node)
        chained = d.chain(lambda s: s).chain(lambda s: s)
        assert isinstance(chained, ChainedPattern)
        steps = chained.compile(User)
        assert len(steps) > 0


class TestOpTransforms:
    def test_select_ops(self) -> None:
        all_ops = (LIST, GET, CREATE, DELETE)
        selected = select_ops(all_ops, LIST, GET)
        assert len(selected) == 2
        assert LIST in selected
        assert GET in selected

    def test_exclude_ops(self) -> None:
        all_ops = (LIST, GET, CREATE, DELETE)
        filtered = exclude_ops(all_ops, DELETE)
        assert len(filtered) == 3
        assert DELETE not in filtered

    def test_by_effect_read(self) -> None:
        all_ops = (LIST, GET, CREATE, DELETE)
        reads = by_effect(all_ops, Read)
        assert len(reads) == 2

    def test_by_effect_mutation(self) -> None:
        all_ops = (LIST, GET, CREATE, DELETE)
        mutations = by_effect(all_ops, Mutation)
        assert len(mutations) == 2
        assert CREATE in mutations
        assert DELETE in mutations

    def test_with_caps_all(self) -> None:
        from emergent.wire.axis.surface.capabilities._base import SurfaceCapability
        from dataclasses import dataclass

        @dataclass
        class DummyCap(SurfaceCapability):
            pass

        all_ops = (LIST, GET)
        result = with_caps(all_ops, DummyCap())
        for op in result:
            assert len(op.capabilities) == 1

    def test_with_caps_filtered_by_effect(self) -> None:
        from emergent.wire.axis.surface.capabilities._base import SurfaceCapability
        from dataclasses import dataclass

        @dataclass
        class DummyCap(SurfaceCapability):
            pass

        all_ops = (LIST, GET, CREATE)
        result = with_caps(all_ops, DummyCap(), effect=Mutation)
        # Only CREATE should get the cap
        for op in result:
            if op.name == "Create":
                assert len(op.capabilities) == 1
            else:
                assert len(op.capabilities) == 0

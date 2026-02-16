"""Tests for derivelib.patterns.crud — CRUD dialect and presets."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from emergent.wire.axis.schema import Identity

from derivelib._derive import derive_endpoints, build_application
from derivelib._effects import Creates, Deletes, Mutation, Read, Updates
from derivelib.axes.surface import DeriveOp
from derivelib.patterns.crud import (
    ALL_CRUD_OPS,
    CREATE,
    DELETE,
    GET,
    LIST,
    MUTATION_CRUD_OPS,
    PATCH,
    READ_CRUD_OPS,
    UPDATE,
    cli_crud,
    crud,
    http_crud,
)

from .conftest import User


class _Node:
    pass


class TestCrudOps:
    def test_list_op(self) -> None:
        assert LIST.name == "List"

    def test_get_op(self) -> None:
        assert GET.name == "Get"

    def test_create_op(self) -> None:
        assert CREATE.name == "Create"

    def test_update_op(self) -> None:
        assert UPDATE.name == "Update"

    def test_patch_op(self) -> None:
        assert PATCH.name == "Patch"

    def test_delete_op(self) -> None:
        assert DELETE.name == "Delete"

    def test_all_crud_ops_count(self) -> None:
        assert len(ALL_CRUD_OPS) == 6

    def test_read_ops(self) -> None:
        assert LIST in READ_CRUD_OPS
        assert GET in READ_CRUD_OPS
        assert len(READ_CRUD_OPS) == 2

    def test_mutation_ops(self) -> None:
        assert CREATE in MUTATION_CRUD_OPS
        assert UPDATE in MUTATION_CRUD_OPS
        assert PATCH in MUTATION_CRUD_OPS
        assert DELETE in MUTATION_CRUD_OPS


class TestHttpCrud:
    def test_compile_produces_derive_ops(self) -> None:
        pattern = http_crud("/api/users", provider_node=_Node)
        steps = pattern.compile(User)
        derive_ops = [s for s in steps if isinstance(s, DeriveOp)]
        assert len(derive_ops) == 6

    def test_compile_with_selected_ops(self) -> None:
        pattern = http_crud("/api/users", provider_node=_Node, ops=(LIST, GET))
        steps = pattern.compile(User)
        derive_ops = [s for s in steps if isinstance(s, DeriveOp)]
        assert len(derive_ops) == 2
        names = {op.name for op in derive_ops}
        assert names == {"List", "Get"}

    def test_endpoints_generated(self) -> None:
        endpoints = derive_endpoints(
            User,
            http_crud("/api/users", provider_node=_Node),
        )
        assert len(endpoints) == 1
        assert len(endpoints[0].exposures) == 6

    def test_endpoints_with_subset(self) -> None:
        endpoints = derive_endpoints(
            User,
            http_crud("/api/users", provider_node=_Node, ops=(LIST, GET, CREATE)),
        )
        assert len(endpoints[0].exposures) == 3


class TestCliCrud:
    def test_compile_produces_derive_ops(self) -> None:
        pattern = cli_crud("user", provider_node=_Node)
        steps = pattern.compile(User)
        derive_ops = [s for s in steps if isinstance(s, DeriveOp)]
        assert len(derive_ops) == 6


class TestCrudFunction:
    def test_custom_triggers(self) -> None:
        from derivelib._dialect import HTTPTriggers

        pattern = crud(
            HTTPTriggers("/custom"),
            provider_node=_Node,
        )
        steps = pattern.compile(User)
        derive_ops = [s for s in steps if isinstance(s, DeriveOp)]
        assert len(derive_ops) == 6


class TestCrudEndToEnd:
    def test_build_application(self) -> None:
        app = build_application(
            (User, http_crud("/api/users", provider_node=_Node)),
        )
        assert app is not None
        total_exposures = sum(len(ep.exposures) for ep in app.endpoints)
        assert total_exposures == 6

"""Tests for derivelib.patterns.crud — CRUD pattern and presets."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from emergent.wire.axis.schema import Identity

from derivelib._derive import derive_endpoints, build_application
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
    http_crud,
)


class _Node:
    pass


def _make_entity(name: str = "E") -> type:
    """Fresh entity class per test to avoid capability accumulation."""
    ns: dict[str, object] = {"__annotations__": {"id": Annotated[int, Identity], "name": str}}
    cls = type(name, (), ns)
    return dataclass(cls)


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
    def test_six_endpoints(self) -> None:
        E = _make_entity("CrudAll")
        endpoints = derive_endpoints(E, http_crud("/api/e", provider_node=_Node))
        total = sum(len(ep.exposures) for ep in endpoints)
        assert total == 6

    def test_selected_ops(self) -> None:
        E = _make_entity("CrudSel")
        endpoints = derive_endpoints(E, http_crud("/api/e", provider_node=_Node, ops=(LIST, GET)))
        total = sum(len(ep.exposures) for ep in endpoints)
        assert total == 2


class TestCliCrud:
    def test_six_endpoints(self) -> None:
        E = _make_entity("CliAll")
        endpoints = derive_endpoints(E, cli_crud("e", provider_node=_Node))
        total = sum(len(ep.exposures) for ep in endpoints)
        assert total == 6


class TestCrudEndToEnd:
    def test_build_application(self) -> None:
        E = _make_entity("CrudE2E")
        app = build_application(
            (E, http_crud("/api/e", provider_node=_Node)),
        )
        assert app is not None
        total_exposures = sum(len(ep.exposures) for ep in app.endpoints)
        assert total_exposures == 6

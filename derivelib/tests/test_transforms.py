"""Tests for derivelib.transforms — fold-based derivation transforms."""

from __future__ import annotations

from dataclasses import replace
from typing import Annotated

from emergent.wire.axis.schema import Identity
from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger

from derivelib._derivation import Derivation
from derivelib._dialect import HTTPTriggers, Op
from derivelib._effects import Creates, Deletes, Mutation, Pageable, Read, Sortable, Updates
from derivelib._handler_templates import (
    DeleteOne,
    FetchMany,
    FetchOneById,
    InsertNew,
    UpdateExisting,
)
from derivelib._project import (
    entity_response,
    id_only,
    list_response,
    no_fields,
    non_id,
    ok_response,
    all_fields,
)
from derivelib.axes.schema import InspectEntity, RequireIdentity
from derivelib.axes.surface import DeriveOp
from derivelib.transforms import (
    map_all_ops,
    mutations_only,
    readonly,
    reject_by_effect,
    select_by_effect,
    without_delete,
    without_ops,
    only_ops,
)

from .conftest import User


def _trigger(method: str, path: str) -> HTTPRouteTrigger:
    return HTTPRouteTrigger(method=method, path=path)


LIST_OP = Op("List", no_fields(), list_response(), FetchMany(), effects=(Read(), Pageable(), Sortable()))
GET_OP = Op("Get", id_only(), entity_response(), FetchOneById(), effects=(Read(),))
CREATE_OP = Op("Create", non_id(), entity_response(), InsertNew(), effects=(Creates(),))
UPDATE_OP = Op("Update", all_fields(), entity_response(), UpdateExisting(), effects=(Updates(),))
DELETE_OP = Op("Delete", id_only(), ok_response(), DeleteOne(), effects=(Deletes(),))


def _make_derivation() -> Derivation:
    preamble = (InspectEntity(), RequireIdentity())
    ops = (LIST_OP, GET_OP, CREATE_OP, UPDATE_OP, DELETE_OP)
    derive_ops = tuple(
        DeriveOp(
            name=op.name,
            input_proj=op.input_proj,
            output=op.output,
            handler_template=op.handler_template,
            trigger=_trigger("GET", f"/api/{op.name.lower()}"),
            effects=op.effects,
            source=op,
        )
        for op in ops
    )
    return (*preamble, *derive_ops)


def _op_names(steps: Derivation) -> list[str]:
    return [s.name for s in steps if isinstance(s, DeriveOp)]


class TestRejectByEffect:
    def test_removes_mutations(self) -> None:
        steps = _make_derivation()
        result = reject_by_effect(Mutation)(steps)
        names = _op_names(result)
        assert "List" in names
        assert "Get" in names
        assert "Create" not in names
        assert "Update" not in names
        assert "Delete" not in names

    def test_preserves_preamble(self) -> None:
        steps = _make_derivation()
        result = reject_by_effect(Mutation)(steps)
        non_ops = [s for s in result if not isinstance(s, DeriveOp)]
        assert len(non_ops) == 2  # InspectEntity + RequireIdentity

    def test_remove_deletes(self) -> None:
        steps = _make_derivation()
        result = reject_by_effect(Deletes)(steps)
        names = _op_names(result)
        assert "Delete" not in names
        assert "Create" in names


class TestSelectByEffect:
    def test_keeps_mutations(self) -> None:
        steps = _make_derivation()
        result = select_by_effect(Mutation)(steps)
        names = _op_names(result)
        assert "Create" in names
        assert "Update" in names
        assert "Delete" in names
        assert "List" not in names
        assert "Get" not in names

    def test_keeps_preamble(self) -> None:
        steps = _make_derivation()
        result = select_by_effect(Mutation)(steps)
        non_ops = [s for s in result if not isinstance(s, DeriveOp)]
        assert len(non_ops) == 2


class TestMapAllOps:
    def test_transforms_all(self) -> None:
        steps = _make_derivation()
        result = map_all_ops(
            lambda op: replace(op, name=f"My{op.name}")
        )(steps)
        names = _op_names(result)
        assert all(n.startswith("My") for n in names)

    def test_preserves_non_ops(self) -> None:
        steps = _make_derivation()
        result = map_all_ops(lambda op: op)(steps)
        assert len(result) == len(steps)


class TestSemanticTransforms:
    def test_readonly(self) -> None:
        steps = _make_derivation()
        result = readonly()(steps)
        names = _op_names(result)
        assert set(names) == {"List", "Get"}

    def test_mutations_only(self) -> None:
        steps = _make_derivation()
        result = mutations_only()(steps)
        names = _op_names(result)
        assert set(names) == {"Create", "Update", "Delete"}

    def test_without_delete(self) -> None:
        steps = _make_derivation()
        result = without_delete()(steps)
        names = _op_names(result)
        assert "Delete" not in names
        assert len(names) == 4

    def test_without_ops(self) -> None:
        steps = _make_derivation()
        result = without_ops(DELETE_OP, CREATE_OP)(steps)
        names = _op_names(result)
        assert "Delete" not in names
        assert "Create" not in names
        assert "List" in names

    def test_only_ops(self) -> None:
        steps = _make_derivation()
        result = only_ops(LIST_OP, GET_OP)(steps)
        names = _op_names(result)
        assert set(names) == {"List", "Get"}


class TestComposition:
    def test_chain_transforms(self) -> None:
        steps = _make_derivation()
        t1 = readonly()
        t2 = map_all_ops(lambda op: replace(op, name=f"V2{op.name}"))
        result = t2(t1(steps))
        names = _op_names(result)
        assert set(names) == {"V2List", "V2Get"}

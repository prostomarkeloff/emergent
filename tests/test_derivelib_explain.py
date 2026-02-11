"""Tests for derivelib explain — dict layer, format layer, handler dispatch."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

import pytest

from emergent.wire.axis.schema import Identity
from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger
from emergent.wire.axis.surface.triggers.cli import CLITrigger

from derivelib import (
    derive,
    memory_node,
    get_patterns,
    fold_derive,
)
from derivelib._opspec import OpSpec
from derivelib._effects import Read, Creates, Updates, Deletes, Pageable, Sortable, Idempotent, Cacheable
from derivelib._project import (
    NoFields,
    IdOnly,
    NonId,
    AllFields,
    EntityResponse,
    ListResponse,
    OkResponse,
    no_fields,
    id_only,
    non_id,
    entity_response,
    list_response,
    ok_response,
)
from derivelib._handler_templates import FetchMany, FetchOneById, InsertNew, DeleteOne
from derivelib.axes.schema import InspectEntity, RequireIdentity, inspect_entity, require_identity
from derivelib.axes.query import BindProvider, SetBaseQuery, bind_provider, base_query
from derivelib.axes.surface import DeriveOp, ExposeOp, AddGlobalCap
from derivelib.adapt import AdaptBaseQuery, adapt_base_query
from derivelib._dialect import Op, Dialect, HTTPTriggers, CLITriggers as CLITriggersGen, dialect
from derivelib.patterns.crud import http_crud, LIST, GET, CREATE, DELETE, ALL_CRUD_OPS
from derivelib._explain import (
    DeriveExplainHandler,
    DERIVE_EXPLAIN,
    opspec_dict,
    step_dict,
    derivation_dict,
    entity_derivation_dict,
    dialect_dict,
    explain_opspec,
    explain_derivation,
    explain_entity,
)


# --- Fixtures ---


Users = memory_node()


@derive(http_crud("/api/users", Users))
@dataclass
class User:
    id: Annotated[int, Identity]
    name: str
    email: str


@dataclass
class SimpleEntity:
    id: Annotated[int, Identity]
    value: str


# --- OpSpec Dict ---


class TestOpSpecDict:
    def test_basic_opspec(self):
        spec = OpSpec(
            name="Get",
            entity_name="User",
            input_fields={"id": int},
            request_fields={"id": int},
            response_spec=EntityResponse(),
            handler_template=FetchOneById(),
            trigger=HTTPRouteTrigger("GET", "/api/users/{id}"),
            effects=(Read(), Idempotent(), Cacheable()),
        )
        d = opspec_dict(spec)
        assert d["name"] == "Get"
        assert d["entity_name"] == "User"
        assert d["input_fields"] == ["id"]
        assert d["response_spec"] == "EntityResponse"
        assert d["trigger"]["type"] == "HTTPRouteTrigger"
        assert d["trigger"]["method"] == "GET"
        assert d["trigger"]["path"] == "/api/users/{id}"
        assert len(d["effects"]) == 3
        effect_types = [e["type"] for e in d["effects"]]
        assert "Read" in effect_types
        assert "Cacheable" in effect_types

    def test_opspec_no_effects(self):
        spec = OpSpec(
            name="Custom",
            entity_name="User",
            input_fields={},
            request_fields={},
            response_spec=OkResponse(),
            handler_template=FetchMany(),
            trigger=HTTPRouteTrigger("POST", "/api/custom"),
        )
        d = opspec_dict(spec)
        assert "effects" not in d

    def test_opspec_cli_trigger(self):
        spec = OpSpec(
            name="List",
            entity_name="User",
            input_fields={},
            request_fields={},
            response_spec=ListResponse(),
            handler_template=FetchMany(),
            trigger=CLITrigger("list-users"),
        )
        d = opspec_dict(spec)
        assert d["trigger"]["type"] == "CLITrigger"
        assert d["trigger"]["command"] == "list-users"


# --- Step Dict ---


class TestStepDict:
    def test_inspect_entity(self):
        d = step_dict(inspect_entity())
        assert d["type"] == "InspectEntity"

    def test_require_identity(self):
        d = step_dict(require_identity())
        assert d["type"] == "RequireIdentity"

    def test_bind_provider(self):
        d = step_dict(bind_provider(Users))
        assert d["type"] == "BindProvider"
        assert "node" in d

    def test_set_base_query(self):
        d = step_dict(base_query())
        assert d["type"] == "SetBaseQuery"

    def test_adapt_base_query(self):
        d = step_dict(adapt_base_query())
        assert d["type"] == "AdaptBaseQuery"

    def test_derive_op(self):
        step = DeriveOp(
            name="List",
            input_proj=no_fields(),
            output=list_response(),
            handler_template=FetchMany(),
            trigger=HTTPRouteTrigger("GET", "/api/users"),
            effects=(Read(), Pageable()),
        )
        d = step_dict(step)
        assert d["type"] == "DeriveOp"
        assert d["name"] == "List"
        assert d["input_proj"] == "NoFields"
        assert d["output"] == "ListResponse"
        assert d["trigger"]["method"] == "GET"
        assert len(d["effects"]) == 2

    def test_derive_op_no_effects(self):
        step = DeriveOp(
            name="Custom",
            input_proj=no_fields(),
            output=ok_response(),
            handler_template=FetchMany(),
            trigger=HTTPRouteTrigger("POST", "/api/custom"),
        )
        d = step_dict(step)
        assert "effects" not in d

    def test_add_global_cap(self):
        @dataclass(frozen=True)
        class TestCap:
            level: str = "info"

        step = AddGlobalCap(cap=TestCap())
        d = step_dict(step)
        assert d["type"] == "AddGlobalCap"
        assert d["cap"]["type"] == "TestCap"


# --- Derivation Dict ---


class TestDerivationDict:
    def test_basic_derivation(self):
        steps = (inspect_entity(), require_identity())
        d = derivation_dict(steps)
        assert d["step_count"] == 2
        assert len(d["steps"]) == 2
        assert d["steps"][0]["type"] == "InspectEntity"
        assert d["steps"][1]["type"] == "RequireIdentity"

    def test_full_derivation(self):
        pattern = http_crud("/api/users", Users)
        steps = pattern.compile(User)
        d = derivation_dict(steps)
        assert d["step_count"] > 0
        step_types = [s["type"] for s in d["steps"]]
        assert "InspectEntity" in step_types
        assert "RequireIdentity" in step_types
        assert "DeriveOp" in step_types


# --- Entity Derivation Dict ---


class TestEntityDerivationDict:
    def test_decorated_entity(self):
        d = entity_derivation_dict(User)
        assert d["entity"] == "User"
        assert d["pattern_count"] == 1
        assert len(d["patterns"]) == 1

        pat = d["patterns"][0]
        assert pat["pattern_type"] == "Dialect"
        assert pat["step_count"] > 0
        assert len(pat["steps"]) > 0
        assert len(pat["specs"]) > 0

    def test_specs_have_names(self):
        d = entity_derivation_dict(User)
        specs = d["patterns"][0]["specs"]
        spec_names = [s["name"] for s in specs]
        # CRUD pattern should have these ops
        assert "List" in spec_names
        assert "Get" in spec_names
        assert "Create" in spec_names

    def test_specs_have_triggers(self):
        d = entity_derivation_dict(User)
        specs = d["patterns"][0]["specs"]
        for spec in specs:
            assert "trigger" in spec
            assert "type" in spec["trigger"]

    def test_no_patterns(self):
        d = entity_derivation_dict(SimpleEntity)
        assert d["entity"] == "SimpleEntity"
        assert d["pattern_count"] == 0
        assert d["patterns"] == []


# --- Dialect Dict ---


class TestDialectDict:
    def test_http_crud_dialect(self):
        d_obj = http_crud("/api/users", Users)
        d = dialect_dict(d_obj)
        assert d["type"] == "Dialect"
        assert d["op_count"] > 0
        assert d["triggers"] == "HTTPTriggers"
        assert d["adapt"] is True

    def test_ops_in_dialect(self):
        d_obj = http_crud("/api/users", Users)
        d = dialect_dict(d_obj)
        op_names = [op["name"] for op in d["ops"]]
        assert "List" in op_names
        assert "Get" in op_names
        assert "Create" in op_names

    def test_custom_dialect(self):
        d_obj = dialect(
            LIST, GET,
            triggers=HTTPTriggers("/api/readonly"),
            provider_node=Users,
        )
        d = dialect_dict(d_obj)
        assert d["op_count"] == 2


# --- Human-Readable: explain_opspec ---


class TestExplainOpSpec:
    def test_basic(self):
        spec = OpSpec(
            name="Get",
            entity_name="User",
            input_fields={"id": int},
            request_fields={"id": int},
            response_spec=EntityResponse(),
            handler_template=FetchOneById(),
            trigger=HTTPRouteTrigger("GET", "/api/users/{id}"),
            effects=(Read(), Idempotent()),
        )
        text = explain_opspec(spec)
        assert "Get:" in text
        assert "id" in text
        assert "EntityResponse" in text
        assert "GET /api/users/{id}" in text
        assert "Read" in text

    def test_no_input(self):
        spec = OpSpec(
            name="List",
            entity_name="User",
            input_fields={},
            request_fields={},
            response_spec=ListResponse(),
            handler_template=FetchMany(),
            trigger=HTTPRouteTrigger("GET", "/api/users"),
        )
        text = explain_opspec(spec)
        assert "(none)" in text


# --- Human-Readable: explain_derivation ---


class TestExplainDerivation:
    def test_basic(self):
        steps = (inspect_entity(), require_identity())
        text = explain_derivation(steps)
        assert "Derivation (2 steps)" in text
        assert "InspectEntity" in text
        assert "RequireIdentity" in text

    def test_with_derive_op(self):
        step = DeriveOp(
            name="List",
            input_proj=no_fields(),
            output=list_response(),
            handler_template=FetchMany(),
            trigger=HTTPRouteTrigger("GET", "/api/users"),
            effects=(Read(),),
        )
        text = explain_derivation((step,))
        assert 'DeriveOp "List"' in text
        assert "GET /api/users" in text


# --- Human-Readable: explain_entity ---


class TestExplainEntity:
    def test_header(self):
        text = explain_entity(User)
        assert "=== User Derivation ===" in text

    def test_pattern_count(self):
        text = explain_entity(User)
        assert "1 pattern" in text

    def test_steps_shown(self):
        text = explain_entity(User)
        assert "Steps" in text
        assert "InspectEntity" in text
        assert "DeriveOp" in text

    def test_opspecs_shown(self):
        text = explain_entity(User)
        assert "OpSpecs" in text
        # Should show request/response type names
        assert "UserRequest" in text
        assert "UserResponse" in text

    def test_no_patterns(self):
        text = explain_entity(SimpleEntity)
        assert "=== SimpleEntity Derivation ===" in text
        assert "0 patterns" in text

    def test_trigger_in_output(self):
        text = explain_entity(User)
        assert "/api/users" in text


# --- Open World ---


class TestOpenWorld:
    def test_unknown_step_type(self):
        @dataclass(frozen=True)
        class CustomStep:
            name: str

        d = step_dict(CustomStep("test"))
        assert d["type"] == "CustomStep"
        assert d["name"] == "test"

    def test_unknown_in_derivation(self):
        @dataclass(frozen=True)
        class CustomStep:
            name: str

        steps = (inspect_entity(), CustomStep("test"))
        d = derivation_dict(steps)
        assert d["step_count"] == 2
        assert d["steps"][1]["type"] == "CustomStep"

    def test_custom_handler(self):
        @dataclass(frozen=True)
        class CustomStep:
            url: str

        def custom_handler(step: object) -> dict:
            return {"type": "Custom", "url": getattr(step, "url", "")}

        handlers = {**_get_handlers_dict(), CustomStep: custom_handler}
        d = step_dict(CustomStep("http://example.com"), handlers=handlers)
        assert d["type"] == "Custom"
        assert d["url"] == "http://example.com"


def _get_handlers_dict() -> dict:
    """Get a plain dict copy of DERIVE_EXPLAIN for merging."""
    return dict(DERIVE_EXPLAIN.items())

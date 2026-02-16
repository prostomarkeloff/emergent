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


# =============================================================================
# Integration Tests — complex, realistic multi-feature scenarios
# =============================================================================


Products = memory_node()
Orders = memory_node()
Categories = memory_node()


@derive(http_crud("/api/products", Products))
@dataclass
class Product:
    id: Annotated[int, Identity]
    name: str
    price: float
    category: str


@derive(http_crud("/api/orders", Orders, ops=(LIST, GET, CREATE, DELETE)))
@dataclass
class Order:
    id: Annotated[int, Identity]
    customer: str
    total: float


class TestIntegrationFullEntityDict:
    """Integration tests for full_entity_dict — three-layer schema -> derivation -> surface."""

    def test_full_entity_dict_schema_layer(self):
        """Schema layer contains correct fields and identity information."""
        from derivelib._explain import full_entity_dict

        data = full_entity_dict(User)
        schema = data["schema"]
        assert isinstance(schema, dict)
        assert schema["field_count"] == 3
        assert schema["identity_count"] == 1

        fields = schema["fields"]
        assert isinstance(fields, list)
        assert len(fields) == 3

        id_field = fields[0]
        assert isinstance(id_field, dict)
        assert id_field["name"] == "id"
        assert id_field["identity"] is True

    def test_full_entity_dict_derivation_layer(self):
        """Derivation layer shows pattern and specs from fold."""
        from derivelib._explain import full_entity_dict

        data = full_entity_dict(User)
        derivation = data["derivation"]
        assert isinstance(derivation, dict)
        assert derivation["pattern_count"] == 1

        patterns = derivation["patterns"]
        assert isinstance(patterns, list)
        assert len(patterns) == 1

        pat = patterns[0]
        assert isinstance(pat, dict)
        assert pat["pattern_type"] == "Dialect"
        assert pat["step_count"] > 0

        specs = pat["specs"]
        assert isinstance(specs, list)
        spec_names = [s["name"] for s in specs if isinstance(s, dict)]
        assert "List" in spec_names
        assert "Get" in spec_names
        assert "Create" in spec_names

    def test_full_entity_dict_surface_layer(self):
        """Surface layer shows materialized endpoints with triggers and codecs."""
        from derivelib._explain import full_entity_dict

        data = full_entity_dict(User)
        surface = data["surface"]
        assert isinstance(surface, dict)
        assert surface["endpoint_count"] == 1

        endpoints = surface["endpoints"]
        assert isinstance(endpoints, list)
        assert len(endpoints) == 1

        ep = endpoints[0]
        assert isinstance(ep, dict)
        assert ep["exposure_count"] > 0

        exposures = ep["exposures"]
        assert isinstance(exposures, list)
        for exp in exposures:
            assert isinstance(exp, dict)
            assert "trigger" in exp
            assert "request" in exp
            assert "response" in exp

    def test_full_entity_dict_surface_triggers_match_specs(self):
        """Surface triggers align with derivation specs — each spec produces an exposure."""
        from derivelib._explain import full_entity_dict

        data = full_entity_dict(User)
        derivation = data["derivation"]
        surface = data["surface"]

        patterns = derivation["patterns"]
        assert isinstance(patterns, list)
        pat = patterns[0]
        assert isinstance(pat, dict)
        spec_count = len(pat["specs"]) if isinstance(pat["specs"], list) else 0

        endpoints = surface["endpoints"]
        assert isinstance(endpoints, list)
        ep = endpoints[0]
        assert isinstance(ep, dict)
        exposure_count = ep["exposure_count"]
        assert isinstance(exposure_count, int)

        assert exposure_count == spec_count

    def test_full_entity_dict_multiple_fields_entity(self):
        """Full trace works with entity having more fields."""
        from derivelib._explain import full_entity_dict

        data = full_entity_dict(Product)
        schema = data["schema"]
        assert isinstance(schema, dict)
        assert schema["field_count"] == 4
        assert schema["identity_count"] == 1


class TestIntegrationExplainFull:
    """Integration tests for explain_full — human-readable full trace."""

    def test_explain_full_contains_all_sections(self):
        """explain_full output contains schema, derivation, and surface sections."""
        from derivelib._explain import explain_full

        text = explain_full(User)
        assert "=== User (full trace) ===" in text
        assert "Schema:" in text
        assert "Derivation:" in text
        assert "Surface:" in text

    def test_explain_full_shows_fields(self):
        """explain_full output shows entity fields."""
        from derivelib._explain import explain_full

        text = explain_full(User)
        assert "id (int)" in text
        assert "name (str)" in text
        assert "email (str)" in text
        assert "Identity" in text

    def test_explain_full_shows_step_chain(self):
        """explain_full output shows derivation step chain."""
        from derivelib._explain import explain_full

        text = explain_full(User)
        # Step chain format: "steps: InspectEntity -> ..."
        assert "steps:" in text
        assert "InspectEntity" in text
        assert "RequireIdentity" in text

    def test_explain_full_shows_ops(self):
        """explain_full output shows derived ops."""
        from derivelib._explain import explain_full

        text = explain_full(User)
        assert "ops:" in text
        assert "List" in text
        assert "Get" in text
        assert "Create" in text

    def test_explain_full_shows_surface_routes(self):
        """explain_full output shows endpoint routes."""
        from derivelib._explain import explain_full

        text = explain_full(User)
        assert "/api/users" in text
        assert "GET" in text
        assert "POST" in text

    def test_explain_full_multiple_entities(self):
        """explain_full with multiple entities shows both."""
        from derivelib._explain import explain_full

        text = explain_full(User, Product)
        assert "=== User (full trace) ===" in text
        assert "=== Product (full trace) ===" in text


class TestIntegrationChainedPatternExplain:
    """Integration: explaining entities derived with chained transforms."""

    def test_readonly_chain_removes_mutations(self):
        """readonly() chain filters out mutation ops from explain output."""
        from derivelib.transforms import readonly

        ReadonlyNode = memory_node()
        pattern = http_crud("/api/readonly-items", ReadonlyNode).chain(readonly())

        @derive(pattern)
        @dataclass
        class ReadonlyItem:
            id: Annotated[int, Identity]
            value: str

        d = entity_derivation_dict(ReadonlyItem)
        pat = d["patterns"]
        assert isinstance(pat, list) and len(pat) == 1
        pat0 = pat[0]
        assert isinstance(pat0, dict)
        specs = pat0["specs"]
        assert isinstance(specs, list)
        spec_names = [s["name"] for s in specs if isinstance(s, dict)]
        # Only read ops should survive readonly()
        assert "List" in spec_names
        assert "Get" in spec_names
        assert "Create" not in spec_names
        assert "Update" not in spec_names
        assert "Delete" not in spec_names

    def test_without_delete_chain(self):
        """without_delete() chain removes Delete from explain output."""
        from derivelib.transforms import without_delete

        NoDeleteNode = memory_node()
        pattern = http_crud("/api/no-delete", NoDeleteNode).chain(without_delete())

        @derive(pattern)
        @dataclass
        class NoDeleteItem:
            id: Annotated[int, Identity]
            data: str

        d = entity_derivation_dict(NoDeleteItem)
        pat = d["patterns"]
        assert isinstance(pat, list)
        pat0 = pat[0]
        assert isinstance(pat0, dict)
        specs = pat0["specs"]
        assert isinstance(specs, list)
        spec_names = [s["name"] for s in specs if isinstance(s, dict)]
        assert "List" in spec_names
        assert "Get" in spec_names
        assert "Create" in spec_names
        assert "Delete" not in spec_names

    def test_only_ops_chain(self):
        """only_ops() chain keeps only specified ops."""
        from derivelib.transforms import only_ops

        SpecificNode = memory_node()
        pattern = http_crud("/api/specific", SpecificNode).chain(only_ops(LIST, GET))

        @derive(pattern)
        @dataclass
        class SpecificItem:
            id: Annotated[int, Identity]
            name: str

        d = entity_derivation_dict(SpecificItem)
        pat = d["patterns"]
        assert isinstance(pat, list)
        pat0 = pat[0]
        assert isinstance(pat0, dict)
        specs = pat0["specs"]
        assert isinstance(specs, list)
        spec_names = [s["name"] for s in specs if isinstance(s, dict)]
        assert spec_names == ["List", "Get"]


class TestIntegrationSubsetOpsExplain:
    """Integration: explaining entities derived with subset of CRUD ops."""

    def test_subset_ops_shows_only_selected(self):
        """http_crud with ops subset shows only those in explain."""
        d = entity_derivation_dict(Order)
        pat = d["patterns"]
        assert isinstance(pat, list) and len(pat) == 1
        pat0 = pat[0]
        assert isinstance(pat0, dict)
        specs = pat0["specs"]
        assert isinstance(specs, list)
        spec_names = [s["name"] for s in specs if isinstance(s, dict)]
        assert "List" in spec_names
        assert "Get" in spec_names
        assert "Create" in spec_names
        assert "Delete" in spec_names
        assert "Update" not in spec_names
        assert "Patch" not in spec_names

    def test_subset_ops_trigger_paths(self):
        """Trigger paths are correct for subset of ops."""
        d = entity_derivation_dict(Order)
        pat = d["patterns"]
        assert isinstance(pat, list) and len(pat) == 1
        pat0 = pat[0]
        assert isinstance(pat0, dict)
        specs = pat0["specs"]
        assert isinstance(specs, list)
        paths: list[str] = []
        for spec in specs:
            assert isinstance(spec, dict)
            trigger = spec.get("trigger")
            assert isinstance(trigger, dict)
            path = trigger.get("path", "")
            assert isinstance(path, str)
            paths.append(path)
        assert "/api/orders" in paths
        assert "/api/orders/{id}" in paths

    def test_subset_ops_effects(self):
        """Effects are preserved for subset ops in explain output."""
        d = entity_derivation_dict(Order)
        pat = d["patterns"]
        assert isinstance(pat, list)
        pat0 = pat[0]
        assert isinstance(pat0, dict)
        specs = pat0["specs"]
        assert isinstance(specs, list)

        for spec in specs:
            assert isinstance(spec, dict)
            name = spec.get("name")
            effects = spec.get("effects")
            if name == "List":
                assert isinstance(effects, list) and len(effects) > 0
                effect_types = [e["type"] for e in effects if isinstance(e, dict)]
                assert "Read" in effect_types
                assert "Pageable" in effect_types
            elif name == "Delete":
                assert isinstance(effects, list) and len(effects) > 0
                effect_types = [e["type"] for e in effects if isinstance(e, dict)]
                assert "Deletes" in effect_types


class TestIntegrationCLIDialectExplain:
    """Integration: explaining entities derived with CLI triggers."""

    def test_cli_crud_explain(self):
        """CLI CRUD dialect appears correctly in explain output."""
        from derivelib.patterns.crud import cli_crud

        CLINode = memory_node()

        @derive(cli_crud("item", CLINode))
        @dataclass
        class CLIItem:
            id: Annotated[int, Identity]
            name: str

        d = entity_derivation_dict(CLIItem)
        pat = d["patterns"]
        assert isinstance(pat, list) and len(pat) == 1
        pat0 = pat[0]
        assert isinstance(pat0, dict)
        specs = pat0["specs"]
        assert isinstance(specs, list)

        for spec in specs:
            assert isinstance(spec, dict)
            trigger = spec.get("trigger")
            assert isinstance(trigger, dict)
            assert trigger["type"] == "CLITrigger"
            command = trigger.get("command")
            assert isinstance(command, str)
            assert command.startswith("item-")

    def test_cli_crud_dialect_dict(self):
        """CLI dialect_dict shows CLI trigger type."""
        from derivelib.patterns.crud import cli_crud

        CLINode2 = memory_node()
        d_obj = cli_crud("widget", CLINode2)
        d = dialect_dict(d_obj)
        assert d["triggers"] == "CLITriggers"
        assert d["op_count"] == 6

    def test_cli_crud_human_readable(self):
        """explain_entity for CLI CRUD shows cli commands."""
        from derivelib.patterns.crud import cli_crud

        CLINode3 = memory_node()

        @derive(cli_crud("task", CLINode3))
        @dataclass
        class Task:
            id: Annotated[int, Identity]
            title: str

        text = explain_entity(Task)
        assert "task-list (cli)" in text
        assert "task-get (cli)" in text
        assert "task-create (cli)" in text


class TestIntegrationCustomDialectExplain:
    """Integration: explaining entities derived with custom dialects."""

    def test_custom_two_op_dialect(self):
        """Custom dialect with two ops shows in explain output."""
        CustomNode = memory_node()
        d_obj = dialect(
            LIST, GET,
            triggers=HTTPTriggers("/api/custom"),
            provider_node=CustomNode,
        )

        @derive(d_obj)
        @dataclass
        class CustomEntity:
            id: Annotated[int, Identity]
            value: str

        d = entity_derivation_dict(CustomEntity)
        assert d["pattern_count"] == 1

        pat = d["patterns"]
        assert isinstance(pat, list)
        pat0 = pat[0]
        assert isinstance(pat0, dict)
        specs = pat0["specs"]
        assert isinstance(specs, list)
        spec_names = [s["name"] for s in specs if isinstance(s, dict)]
        assert spec_names == ["List", "Get"]

    def test_custom_dialect_with_extra_effects(self):
        """Custom ops with extra effects show in explain output."""
        from derivelib._effects import Filterable, Searchable

        SEARCH_LIST = Op(
            "List",
            no_fields(),
            list_response(),
            FetchMany(),
            effects=(Read(), Pageable(), Sortable(), Filterable(("name",)), Searchable(("name",))),
        )

        SearchNode = memory_node()
        d_obj = dialect(
            SEARCH_LIST, GET,
            triggers=HTTPTriggers("/api/searchable"),
            provider_node=SearchNode,
        )

        @derive(d_obj)
        @dataclass
        class SearchableEntity:
            id: Annotated[int, Identity]
            name: str

        d = entity_derivation_dict(SearchableEntity)
        pat = d["patterns"]
        assert isinstance(pat, list)
        pat0 = pat[0]
        assert isinstance(pat0, dict)
        specs = pat0["specs"]
        assert isinstance(specs, list)

        list_spec = None
        for spec in specs:
            assert isinstance(spec, dict)
            if spec.get("name") == "List":
                list_spec = spec
                break
        assert list_spec is not None
        effects = list_spec.get("effects")
        assert isinstance(effects, list)
        effect_types = [e["type"] for e in effects if isinstance(e, dict)]
        assert "Read" in effect_types
        assert "Pageable" in effect_types
        assert "Filterable" in effect_types
        assert "Searchable" in effect_types


class TestIntegrationExplainRoundTrip:
    """Integration: dict layer and human-readable layer produce consistent output."""

    def test_dict_and_text_consistency(self):
        """entity_derivation_dict and explain_entity agree on structure."""
        d = entity_derivation_dict(User)
        text = explain_entity(User)

        # Pattern count
        assert d["pattern_count"] == 1
        assert "1 pattern" in text

        # Steps
        pat = d["patterns"]
        assert isinstance(pat, list)
        pat0 = pat[0]
        assert isinstance(pat0, dict)
        step_count = pat0["step_count"]
        assert isinstance(step_count, int)
        assert f"Steps ({step_count}):" in text

        # Specs
        specs = pat0["specs"]
        assert isinstance(specs, list)
        for spec in specs:
            assert isinstance(spec, dict)
            spec_name = spec["name"]
            assert isinstance(spec_name, str)
            # Each spec name appears in human-readable output
            assert spec_name in text

    def test_full_dict_and_full_text_consistency(self):
        """full_entity_dict and explain_full agree on structure."""
        from derivelib._explain import full_entity_dict, explain_full

        d = full_entity_dict(Product)
        text = explain_full(Product)

        # Entity name
        assert d["entity"] == "Product"
        assert "=== Product (full trace) ===" in text

        # Schema field count
        schema = d["schema"]
        assert isinstance(schema, dict)
        field_count = schema["field_count"]
        assert isinstance(field_count, int)
        assert f"{field_count} fields" in text

        # Derivation pattern count
        derivation = d["derivation"]
        assert isinstance(derivation, dict)
        assert f'{derivation["pattern_count"]} pattern' in text


class TestIntegrationProviderNodeTracking:
    """Integration: provider node is tracked through derivation and shown in explain."""

    def test_provider_node_in_entity_derivation_dict(self):
        """entity_derivation_dict captures provider node name."""
        d = entity_derivation_dict(User)
        pat = d["patterns"]
        assert isinstance(pat, list)
        pat0 = pat[0]
        assert isinstance(pat0, dict)
        assert "provider_node" in pat0
        # Provider node is the memory_node class
        provider = pat0["provider_node"]
        assert isinstance(provider, str)
        assert len(provider) > 0

    def test_provider_node_in_full_entity_dict(self):
        """full_entity_dict also captures provider node name."""
        from derivelib._explain import full_entity_dict

        data = full_entity_dict(Product)
        derivation = data["derivation"]
        assert isinstance(derivation, dict)
        patterns = derivation["patterns"]
        assert isinstance(patterns, list)
        pat0 = patterns[0]
        assert isinstance(pat0, dict)
        assert "provider_node" in pat0


class TestIntegrationNoPatternEntity:
    """Integration: entities with no patterns produce empty explain output."""

    def test_no_patterns_full_entity_dict(self):
        """full_entity_dict for non-derived entity shows empty layers."""
        from derivelib._explain import full_entity_dict

        data = full_entity_dict(SimpleEntity)
        assert data["entity"] == "SimpleEntity"

        schema = data["schema"]
        assert isinstance(schema, dict)
        assert schema["field_count"] == 2

        derivation = data["derivation"]
        assert isinstance(derivation, dict)
        assert derivation["pattern_count"] == 0

        surface = data["surface"]
        assert isinstance(surface, dict)
        assert surface["endpoint_count"] == 0

    def test_no_patterns_explain_full(self):
        """explain_full for non-derived entity shows all sections with zero counts."""
        from derivelib._explain import explain_full

        text = explain_full(SimpleEntity)
        assert "=== SimpleEntity (full trace) ===" in text
        assert "0 patterns" in text
        assert "0 exposures" in text


class TestIntegrationCustomHandlerDispatch:
    """Integration: custom explain handlers interact correctly with the full pipeline."""

    def test_custom_handler_in_full_derivation(self):
        """Custom step handler is used when explaining a derivation containing that step."""
        @dataclass(frozen=True)
        class AuditStep:
            level: str

        def audit_handler(step: object) -> dict[str, str | int | float | bool | None | list | dict]:
            return {"type": "AuditStep", "audit_level": getattr(step, "level", "info")}

        handlers = {**_get_handlers_dict(), AuditStep: audit_handler}

        steps = (inspect_entity(), require_identity(), AuditStep(level="debug"))
        d = derivation_dict(steps, handlers)

        assert d["step_count"] == 3
        assert isinstance(d["steps"], list)
        step_dicts = d["steps"]

        # First two steps use built-in handlers
        assert isinstance(step_dicts[0], dict)
        assert step_dicts[0]["type"] == "InspectEntity"
        assert isinstance(step_dicts[1], dict)
        assert step_dicts[1]["type"] == "RequireIdentity"

        # Third step uses custom handler
        assert isinstance(step_dicts[2], dict)
        assert step_dicts[2]["type"] == "AuditStep"
        assert step_dicts[2]["audit_level"] == "debug"

    def test_custom_handler_in_explain_derivation(self):
        """Custom handler integrates with human-readable explain_derivation."""
        @dataclass(frozen=True)
        class ValidationStep:
            strict: bool = True

        def validation_handler(step: object) -> dict[str, str | int | float | bool | None | list | dict]:
            return {"type": "ValidationStep", "strict": getattr(step, "strict", True)}

        handlers = {**_get_handlers_dict(), ValidationStep: validation_handler}
        steps = (inspect_entity(), ValidationStep(strict=True))

        text = explain_derivation(steps, handlers)
        assert "Derivation (2 steps)" in text
        assert "InspectEntity" in text
        assert "ValidationStep" in text


class TestIntegrationDialectComposition:
    """Integration: explaining composed dialect patterns (multiple dialects on one entity)."""

    def test_two_patterns_on_entity(self):
        """Entity with two patterns shows both in explain."""
        PatNode1 = memory_node()
        PatNode2 = memory_node()
        http_pattern = http_crud("/api/dual-a", PatNode1, ops=(LIST, GET))
        from derivelib.patterns.crud import cli_crud
        cli_pattern = cli_crud("dual", PatNode2, ops=(LIST, GET))

        @derive(http_pattern, cli_pattern)
        @dataclass
        class DualEntity:
            id: Annotated[int, Identity]
            name: str

        d = entity_derivation_dict(DualEntity)
        assert d["pattern_count"] == 2
        pat = d["patterns"]
        assert isinstance(pat, list)
        assert len(pat) == 2

        # First pattern: HTTP
        p0 = pat[0]
        assert isinstance(p0, dict)
        specs0 = p0["specs"]
        assert isinstance(specs0, list)
        for spec in specs0:
            assert isinstance(spec, dict)
            trigger = spec.get("trigger")
            assert isinstance(trigger, dict)
            assert trigger["type"] == "HTTPRouteTrigger"

        # Second pattern: CLI
        p1 = pat[1]
        assert isinstance(p1, dict)
        specs1 = p1["specs"]
        assert isinstance(specs1, list)
        for spec in specs1:
            assert isinstance(spec, dict)
            trigger = spec.get("trigger")
            assert isinstance(trigger, dict)
            assert trigger["type"] == "CLITrigger"

    def test_two_patterns_explain_entity(self):
        """Human-readable output shows both patterns."""
        PatNode3 = memory_node()
        PatNode4 = memory_node()

        @derive(
            http_crud("/api/both-a", PatNode3, ops=(LIST,)),
            http_crud("/api/both-b", PatNode4, ops=(GET,)),
        )
        @dataclass
        class BothEntity:
            id: Annotated[int, Identity]
            data: str

        text = explain_entity(BothEntity)
        assert "2 patterns" in text
        assert "Pattern #1" in text
        assert "Pattern #2" in text


class TestIntegrationOpSpecEffectDetails:
    """Integration: effect details (data-carrying effects) are preserved in explain."""

    def test_pageable_default_size_in_opspec_dict(self):
        """Pageable effect carries default_size through to opspec_dict."""
        spec = OpSpec(
            name="List",
            entity_name="Widget",
            input_fields={},
            request_fields={},
            response_spec=ListResponse(),
            handler_template=FetchMany(),
            trigger=HTTPRouteTrigger("GET", "/api/widgets"),
            effects=(Read(), Pageable(default_size=50)),
        )
        d = opspec_dict(spec)
        effects = d.get("effects")
        assert isinstance(effects, list)
        pageable = None
        for e in effects:
            assert isinstance(e, dict)
            if e.get("type") == "Pageable":
                pageable = e
                break
        assert pageable is not None
        assert pageable["default_size"] == 50

    def test_sortable_default_fields_in_opspec_dict(self):
        """Sortable effect carries default_field/default_order through to opspec_dict."""
        spec = OpSpec(
            name="List",
            entity_name="Widget",
            input_fields={},
            request_fields={},
            response_spec=ListResponse(),
            handler_template=FetchMany(),
            trigger=HTTPRouteTrigger("GET", "/api/widgets"),
            effects=(Read(), Sortable(default_field="name", default_order="desc")),
        )
        d = opspec_dict(spec)
        effects = d.get("effects")
        assert isinstance(effects, list)
        sortable = None
        for e in effects:
            assert isinstance(e, dict)
            if e.get("type") == "Sortable":
                sortable = e
                break
        assert sortable is not None
        assert sortable["default_field"] == "name"
        assert sortable["default_order"] == "desc"

    def test_cacheable_ttl_in_explain_opspec(self):
        """Cacheable effect with TTL shows in human-readable explain_opspec."""
        spec = OpSpec(
            name="Get",
            entity_name="Widget",
            input_fields={"id": int},
            request_fields={"id": int},
            response_spec=EntityResponse(),
            handler_template=FetchOneById(),
            trigger=HTTPRouteTrigger("GET", "/api/widgets/{id}"),
            effects=(Read(), Cacheable(ttl=300)),
        )
        text = explain_opspec(spec)
        assert "Get:" in text
        assert "Cacheable(300)" in text


class TestIntegrationCompositeIdentity:
    """Integration: entities with composite identity keys work correctly in explain."""

    def test_composite_identity_schema(self):
        """Entity with composite identity shows multiple identity fields."""
        from derivelib._explain import full_entity_dict

        CompositeNode = memory_node()

        @derive(http_crud("/api/memberships", CompositeNode))
        @dataclass
        class Membership:
            user_id: Annotated[int, Identity]
            group_id: Annotated[int, Identity]
            role: str

        data = full_entity_dict(Membership)
        schema = data["schema"]
        assert isinstance(schema, dict)
        assert schema["identity_count"] == 2
        assert schema["field_count"] == 3

        fields = schema["fields"]
        assert isinstance(fields, list)
        id_fields = [f for f in fields if isinstance(f, dict) and f.get("identity")]
        assert len(id_fields) == 2

    def test_composite_identity_trigger_paths(self):
        """Composite identity produces correct path params in triggers."""
        CompositeNode2 = memory_node()

        @derive(http_crud("/api/scores", CompositeNode2))
        @dataclass
        class Score:
            player_id: Annotated[int, Identity]
            game_id: Annotated[int, Identity]
            points: int

        d = entity_derivation_dict(Score)
        pat = d["patterns"]
        assert isinstance(pat, list)
        pat0 = pat[0]
        assert isinstance(pat0, dict)
        specs = pat0["specs"]
        assert isinstance(specs, list)

        get_spec = None
        for spec in specs:
            assert isinstance(spec, dict)
            if spec.get("name") == "Get":
                get_spec = spec
                break
        assert get_spec is not None
        trigger = get_spec["trigger"]
        assert isinstance(trigger, dict)
        path = trigger.get("path", "")
        assert isinstance(path, str)
        assert "{player_id}" in path
        assert "{game_id}" in path

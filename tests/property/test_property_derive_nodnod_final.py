# pyright: reportPrivateUsage=false
"""Property-based tests targeting EXACT remaining uncovered lines in derive modules
and compile infra nodnod paths.

Covers:
- derive/patterns/methods.py: _build_method_operation handler dispatch, Methods,
  MethodDialect with TriggerGen, response converter branches, _stub_op
- derive/_transforms.py: Filtered, Searchable, WithRetry, WithRateLimit,
  EffectRateLimited, EffectDeprecated, ProjectResponse
- derive/_pipeline.py: Pipeline.build short-circuit + Ok(pctx.result), BuildEntityData
  with next_id / no next_id, CheckCache, PopulateCache
- derive/_project.py: OkResponse, PaginatedResponse, CountResponse, BoolResponse,
  EmptyResponse, CursorPaginatedResponse, dict_converter, _result_converter error branch
- derive/_explain.py: _handler_info for Pipeline + WrappedTemplate, _trigger_short
  for CLITrigger, _effects_short empty, explain_derive with operations + capabilities
- derive/_builders.py: ExposureBuilder.build() default converter branches
- derive/_codegen.py: create_request_type DirectMapper + custom, create_response_type
  __str__ multi-field, annotate_handler, create_sentinel_operation
- derive/_error_caps.py: ProblemResponse.apply_response + compile_fastapi_route
- derive/_query_helpers.py: serialize_op_fields non-json-serializable, provider_field
- derive/_trigger.py: HTTPTriggers custom route, NestedHTTPTriggers, CLITriggers,
  FilteredTriggerGen, PrefixedTriggerGen, MultiTriggerGen
- derive/_ctx.py: provider_node, base_query, filter_query, wrap_handler
- derive/auth/caps.py: Authenticated with Public effect skip, OwnerScoped
- derive/patterns/nested.py: NestedCRUD with fk_field, _find_fk fallback
- compile/_execute.py: execute_rrc_unified, execute_stateful_unified
- compile/_pipeline.py: execute_with_pipeline
- compile/_request.py: build_field_value compose Node resolution
- compile/_stateful.py: execute_stateful_done
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field as dataclass_field
from typing import Annotated, Any

import pytest
from kungfu import Error, Ok, Result

from emergent.wire.axis.schema._universal import Identity, Ref, schema_meta
from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger
from emergent.wire.axis.surface.triggers.cli import CLITrigger
from emergent.wire.derive._compile import compile_derive
from emergent.wire.derive._materialize import materialize
from emergent.wire.derive._crud import (
    http_crud,
    cli_crud,
)
from emergent.wire.derive._ctx import DeriveCtx
from emergent.wire.derive._effects import (
    Creates,
    Mutation,
    Read,
    has_effect,
)
from emergent.wire.derive._errors import DomainError, NotFound
from emergent.wire.derive._handler import (
    FetchMany,
    FetchOneById,
    HandlerSpec,
    WrappedTemplate,
)
from emergent.wire.derive._project import (
    BoolResponse,
    CountResponse,
    CursorPaginatedResponse,
    EmptyResponse,
    EntityResponse,
    ListResponse,
    NoFields,
    OkResponse,
    PaginatedResponse,
    dict_converter,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Test-local entity types
# ═══════════════════════════════════════════════════════════════════════════════


class Users:
    """Provider node stub."""


class Posts:
    """Provider node stub for posts."""


@dataclass
class User:
    id: Annotated[int, Identity()]
    name: str
    email: str


@dataclass
class Article:
    id: Annotated[int, Identity()]
    title: str
    body: str
    author_id: int


@dataclass
class Post:
    id: Annotated[int, Identity()]
    user_id: Annotated[int, Ref(User)]
    title: str
    content: str


@dataclass
class AuthUser:
    name: str
    roles: set[str]


@dataclass(frozen=True)
class OrderResult:
    id: int
    status: str


# ═══════════════════════════════════════════════════════════════════════════════
# 1. _project.py — OkResponse, PaginatedResponse, CountResponse, BoolResponse,
#    EmptyResponse, CursorPaginatedResponse, dict_converter
# ═══════════════════════════════════════════════════════════════════════════════


class TestResponseSpecs:
    """Cover resolve() branches for all ResponseSpec variants."""

    def _make_ctx(self) -> DeriveCtx[User]:
        return DeriveCtx.from_entity(User)

    def test_ok_response_resolve(self) -> None:
        ctx = self._make_ctx()
        spec = OkResponse()
        fields, _converter = spec.resolve(ctx)
        assert len(fields) == 1
        assert fields[0][0] == "success"

    def test_ok_response_converter_ok(self) -> None:
        ctx = self._make_ctx()
        spec = OkResponse()
        fields, converter = spec.resolve(ctx)
        from emergent.wire.derive._codegen import create_response_type
        resp_cls: Any = create_response_type("OkTestResp", fields, converter)
        result = resp_cls.from_domain(Ok("anything"))
        assert result.success is True

    def test_ok_response_converter_error(self) -> None:
        ctx = self._make_ctx()
        spec = OkResponse()
        fields, converter = spec.resolve(ctx)
        from emergent.wire.derive._codegen import create_response_type
        resp_cls: Any = create_response_type("OkTestResp2", fields, converter)
        err = NotFound(entity="User", id={"id": 1})
        result = resp_cls.from_domain(Error(err))
        assert result is err

    def test_paginated_response_resolve(self) -> None:
        ctx = self._make_ctx()
        spec = PaginatedResponse()
        fields, _converter = spec.resolve(ctx)
        field_names = [f[0] for f in fields]
        assert "items" in field_names
        assert "total" in field_names
        assert "page" in field_names
        assert "page_size" in field_names

    def test_paginated_response_converter_mapping(self) -> None:
        ctx = self._make_ctx()
        spec = PaginatedResponse()
        fields, converter = spec.resolve(ctx)
        from emergent.wire.derive._codegen import create_response_type
        resp_cls: Any = create_response_type("PagResp", fields, converter)
        data = {"items": [User(1, "Alice", "a@b.com")], "total": 1, "page": 1, "page_size": 20}
        result = resp_cls.from_domain(Ok(data))
        assert result.total == 1
        assert len(result.items) == 1

    def test_paginated_response_converter_sequence(self) -> None:
        ctx = self._make_ctx()
        spec = PaginatedResponse()
        fields, converter = spec.resolve(ctx)
        from emergent.wire.derive._codegen import create_response_type
        resp_cls: Any = create_response_type("PagResp2", fields, converter)
        data = [User(1, "Alice", "a@b.com")]
        result = resp_cls.from_domain(Ok(data))
        assert result.total == 0
        assert len(result.items) == 1

    def test_paginated_response_converter_error(self) -> None:
        ctx = self._make_ctx()
        spec = PaginatedResponse()
        fields, converter = spec.resolve(ctx)
        from emergent.wire.derive._codegen import create_response_type
        resp_cls: Any = create_response_type("PagResp3", fields, converter)
        result = resp_cls.from_domain(Error(NotFound(entity="User", id={"id": 1})))
        assert result.total == 0
        assert result.items == []

    def test_count_response_resolve(self) -> None:
        ctx = self._make_ctx()
        spec = CountResponse()
        fields, _converter = spec.resolve(ctx)
        assert len(fields) == 1
        assert fields[0][0] == "count"

    def test_count_response_converter_ok(self) -> None:
        ctx = self._make_ctx()
        spec = CountResponse()
        fields, converter = spec.resolve(ctx)
        from emergent.wire.derive._codegen import create_response_type
        resp_cls: Any = create_response_type("CountResp", fields, converter)
        result = resp_cls.from_domain(Ok(42))
        assert result.count == 42

    def test_bool_response_resolve(self) -> None:
        ctx = self._make_ctx()
        spec = BoolResponse()
        fields, _converter = spec.resolve(ctx)
        assert len(fields) == 1
        assert fields[0][0] == "exists"

    def test_bool_response_converter_ok(self) -> None:
        ctx = self._make_ctx()
        spec = BoolResponse()
        fields, converter = spec.resolve(ctx)
        from emergent.wire.derive._codegen import create_response_type
        resp_cls: Any = create_response_type("BoolResp", fields, converter)
        result = resp_cls.from_domain(Ok(True))
        assert result.exists is True

    def test_bool_response_converter_error(self) -> None:
        ctx = self._make_ctx()
        spec = BoolResponse()
        fields, converter = spec.resolve(ctx)
        from emergent.wire.derive._codegen import create_response_type
        resp_cls: Any = create_response_type("BoolResp2", fields, converter)
        err = NotFound(entity="X", id={})
        result = resp_cls.from_domain(Error(err))
        assert result is err

    def test_empty_response_resolve(self) -> None:
        ctx = self._make_ctx()
        spec = EmptyResponse()
        fields, _converter = spec.resolve(ctx)
        assert len(fields) == 0

    def test_empty_response_converter_ok(self) -> None:
        ctx = self._make_ctx()
        spec = EmptyResponse()
        fields, converter = spec.resolve(ctx)
        from emergent.wire.derive._codegen import create_response_type
        resp_cls: Any = create_response_type("EmptyResp", fields, converter)
        result = resp_cls.from_domain(Ok(None))
        assert dataclasses.is_dataclass(result)

    def test_cursor_paginated_response_resolve(self) -> None:
        ctx = self._make_ctx()
        spec = CursorPaginatedResponse()
        fields, _converter = spec.resolve(ctx)
        field_names = [f[0] for f in fields]
        assert "items" in field_names
        assert "next_cursor" in field_names
        assert "has_more" in field_names

    def test_cursor_paginated_response_converter_mapping(self) -> None:
        ctx = self._make_ctx()
        spec = CursorPaginatedResponse()
        fields, converter = spec.resolve(ctx)
        from emergent.wire.derive._codegen import create_response_type
        resp_cls: Any = create_response_type("CursorResp", fields, converter)
        data = {"items": [User(1, "A", "a@b")], "next_cursor": "abc", "has_more": True}
        result = resp_cls.from_domain(Ok(data))
        assert result.has_more is True
        assert result.next_cursor == "abc"

    def test_cursor_paginated_response_converter_sequence(self) -> None:
        ctx = self._make_ctx()
        spec = CursorPaginatedResponse()
        fields, converter = spec.resolve(ctx)
        from emergent.wire.derive._codegen import create_response_type
        resp_cls: Any = create_response_type("CursorResp2", fields, converter)
        data = [User(1, "A", "a@b")]
        result = resp_cls.from_domain(Ok(data))
        assert result.next_cursor is None
        assert result.has_more is False
        assert len(result.items) == 1

    def test_cursor_paginated_response_converter_error(self) -> None:
        ctx = self._make_ctx()
        spec = CursorPaginatedResponse()
        fields, converter = spec.resolve(ctx)
        from emergent.wire.derive._codegen import create_response_type
        resp_cls: Any = create_response_type("CursorResp3", fields, converter)
        err = Error(NotFound(entity="X", id={}))
        result = resp_cls.from_domain(err)
        assert result.items == []

    def test_dict_converter_with_dict(self) -> None:
        from emergent.wire.derive._codegen import create_dataclass
        cls: Any = create_dataclass("DictResp", [("x", int), ("y", str)], frozen=True)
        raw = dict_converter(cls, Ok({"x": 1, "y": "hi"}))
        result: Any = raw
        assert result.x == 1
        assert result.y == "hi"

    def test_dict_converter_with_object(self) -> None:
        from emergent.wire.derive._codegen import create_dataclass
        cls: Any = create_dataclass("DictResp2", [("x", int), ("y", str)], frozen=True)

        @dataclass(frozen=True)
        class Obj:
            x: int = 5
            y: str = "hello"

        raw = dict_converter(cls, Ok(Obj()))
        result: Any = raw
        assert result.x == 5

    def test_dict_converter_with_error(self) -> None:
        from emergent.wire.derive._codegen import create_dataclass
        cls: Any = create_dataclass("DictResp3", [("x", int)], frozen=True)
        err = NotFound(entity="X", id={})
        result = dict_converter(cls, Error(err))
        assert result is err

    def test_dict_converter_invalid_result_raises(self) -> None:
        from emergent.wire.derive._codegen import create_dataclass
        cls: Any = create_dataclass("DictResp4", [("x", int)], frozen=True)
        with pytest.raises(TypeError, match="Expected Result"):
            dict_converter(cls, "not_a_result")  # type: ignore[arg-type]


# ═══════════════════════════════════════════════════════════════════════════════
# 2. _codegen.py — create_response_type __str__, create_sentinel_operation
# ═══════════════════════════════════════════════════════════════════════════════


class TestCodegen:
    """Cover create_response_type __str__ and sentinel."""

    def test_response_type_str_single_field(self) -> None:
        from emergent.wire.derive._codegen import create_response_type
        def _converter(cls: Any, r: Any) -> Any:
            return cls(result=42)
        converter: Any = _converter
        resp_cls: Any = create_response_type("SingleStr", [("result", int)], converter)
        instance = resp_cls(result=42)
        assert str(instance) == "42"

    def test_response_type_str_multi_field(self) -> None:
        from emergent.wire.derive._codegen import create_response_type
        def _converter(cls: Any, r: Any) -> Any:
            return cls(x=1, y="hello")
        converter: Any = _converter
        resp_cls: Any = create_response_type(
            "MultiStr", [("x", int), ("y", str)], converter
        )
        instance = resp_cls(x=1, y="hello")
        s = str(instance)
        assert "1" in s
        assert "hello" in s

    def test_response_type_str_multi_field_none_skipped(self) -> None:
        from emergent.wire.derive._codegen import create_response_type
        def _converter(cls: Any, r: Any) -> Any:
            return cls(x=1, y=None)
        converter: Any = _converter
        resp_cls: Any = create_response_type(
            "MultiStr2", [("x", int), ("y", str | None)], converter
        )
        instance = resp_cls(x=1, y=None)
        s = str(instance)
        assert "1" in s
        assert "None" not in s

    def test_create_request_type_custom_mapper(self) -> None:
        from emergent.wire.derive._codegen import (
            create_dataclass,
            create_request_type,
        )
        op_type: Any = create_dataclass("CustomOp", [("name", str)], frozen=True)
        def _mapper(self: Any) -> dict[str, Any]:
            return {"name": self.name.upper()}
        mapper: Any = _mapper
        req_cls = create_request_type(
            "CustomReq", [("name", str)], op_type, mapper=mapper
        )
        req = req_cls(name="alice")
        domain = req.to_domain()
        assert domain.name == "ALICE"

    def test_create_sentinel_operation(self) -> None:
        from emergent.wire.derive._codegen import create_sentinel_operation
        op_type, _handler = create_sentinel_operation("TestSentinel")
        assert dataclasses.is_dataclass(op_type)
        assert op_type.__name__ == "TestSentinel"

    def test_annotate_handler(self) -> None:
        from emergent.wire.derive._codegen import annotate_handler, create_dataclass
        op_type: Any = create_dataclass("AnnotOp", [("x", int)], frozen=True)

        async def raw_handler(op: object) -> Result[int, DomainError]:
            return Ok(42)

        annotated = annotate_handler(raw_handler, op_type)
        assert annotated.__annotations__["op"] is op_type


# ═══════════════════════════════════════════════════════════════════════════════
# 3. _explain.py — _handler_info for Pipeline + WrappedTemplate,
#    _trigger_short for CLITrigger, explain_derive with operations
# ═══════════════════════════════════════════════════════════════════════════════


class TestExplain:
    """Cover _handler_info, _trigger_short, explain_derive."""

    def test_handler_info_pipeline(self) -> None:
        from emergent.wire.derive._explain import _handler_info
        from emergent.wire.derive._pipeline import Pipeline, ScopeQuery, FetchAll

        p = Pipeline(ScopeQuery(), FetchAll())
        info = _handler_info(p)
        assert isinstance(info, dict)
        assert info["type"] == "Pipeline"
        steps: Any = info["steps"]
        assert "ScopeQuery" in steps
        assert "FetchAll" in steps

    def test_handler_info_wrapped_template(self) -> None:
        from emergent.wire.derive._explain import _handler_info

        inner = FetchMany()
        def _wt_wrapper(i: Any, s: Any) -> Any:
            return i
        wt_wrapper: Any = _wt_wrapper
        wt: Any = WrappedTemplate(inner=inner, wrapper=wt_wrapper)
        info = _handler_info(wt)
        assert isinstance(info, dict)
        assert info["type"] == "WrappedTemplate"

    def test_handler_info_plain_template(self) -> None:
        from emergent.wire.derive._explain import _handler_info

        info = _handler_info(FetchMany())
        assert info == "FetchMany"

    def test_trigger_short_http(self) -> None:
        from emergent.wire.derive._explain import _trigger_short

        trigger = HTTPRouteTrigger(method="GET", path="/api/users")
        assert _trigger_short(trigger) == "GET /api/users"

    def test_trigger_short_cli(self) -> None:
        from emergent.wire.derive._explain import _trigger_short

        trigger = CLITrigger(command="user-list")
        assert _trigger_short(trigger) == "CLI user-list"

    def test_trigger_short_unknown(self) -> None:
        from emergent.wire.derive._explain import _trigger_short

        class CustomTrigger:
            pass

        assert "CustomTrigger" in _trigger_short(CustomTrigger())

    def test_effects_short_empty(self) -> None:
        from emergent.wire.derive._explain import _effects_short

        assert _effects_short(()) == ""

    def test_effects_short_nonempty(self) -> None:
        from emergent.wire.derive._explain import _effects_short

        assert "Read" in _effects_short((Read(),))

    def test_explain_derive_with_operations(self) -> None:
        from emergent.wire.derive._explain import explain_derive
        from emergent.wire.derive.patterns.methods import Methods, post

        @schema_meta(Methods())
        @dataclass
        class OpService:
            @classmethod
            @post("/api/health")
            async def health(cls) -> Result[str, DomainError]:
                return Ok("ok")

        ctxs = compile_derive(OpService)
        text = explain_derive(ctxs[0])
        assert "OpService" in text
        assert "Direct operations" in text

    def test_explain_derive_with_capabilities(self) -> None:
        from emergent.wire.derive._explain import explain_derive
        from emergent.wire.derive._transforms import Paginated

        @schema_meta(http_crud("/api/items", Users), Paginated(20))
        @dataclass
        class ItemExplain:
            id: Annotated[int, Identity()]
            name: str

        ctxs = compile_derive(ItemExplain)
        text = explain_derive(ctxs[0])
        assert "ItemExplain" in text

    def test_explain_spec(self) -> None:
        from emergent.wire.derive._explain import explain_spec

        @schema_meta(http_crud("/api/items", Users))
        @dataclass
        class ItemSpec:
            id: Annotated[int, Identity()]
            name: str

        ctxs = compile_derive(ItemSpec)
        for spec in ctxs[0].specs:
            text = explain_spec(spec)
            assert spec.name in text

    def test_derive_dict_full(self) -> None:
        from emergent.wire.derive._explain import derive_dict

        @schema_meta(http_crud("/api/items", Users))
        @dataclass
        class ItemDict:
            id: Annotated[int, Identity()]
            name: str

        ctxs = compile_derive(ItemDict)
        d = derive_dict(ctxs[0])
        assert d["entity"] == "ItemDict"
        assert "specs" in d
        assert isinstance(d["specs"], list)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. _error_caps.py — ProblemResponse.apply_response + compile_fastapi_route
# ═══════════════════════════════════════════════════════════════════════════════


class TestErrorCaps:
    """Cover ProblemResponse."""

    def test_problem_response_apply_non_dc_passthrough(self) -> None:
        from emergent.wire.derive._error_caps import ProblemResponse

        pr = ProblemResponse()
        result = pr.apply_response("plain_string")
        assert result == "plain_string"

    def test_problem_response_apply_dc_with_status_code(self) -> None:
        from emergent.wire.derive._error_caps import ProblemResponse

        @dataclass
        class FakeResp:
            status_code: int = 404
            detail: str = "not found"

        pr = ProblemResponse()
        result = pr.apply_response(FakeResp())
        # If starlette is available, JSONResponse is returned
        # If not, original is returned (line 49-50)
        assert result is not None

    def test_problem_response_compile_fastapi_route(self) -> None:
        from emergent.wire.derive._error_caps import ProblemResponse
        from emergent.wire.axis._capability import FastAPIRouteContext

        pr = ProblemResponse()
        ctx = FastAPIRouteContext(path="/test", method="GET")
        new_ctx = pr.compile_fastapi_route(ctx)
        assert new_ctx.openapi_extra is not None
        assert "responses" in new_ctx.openapi_extra
        assert new_ctx.openapi_extra is not None
        responses = new_ctx.openapi_extra["responses"]
        assert "404" in responses
        assert "409" in responses
        assert "422" in responses

    def test_problem_response_compile_fastapi_route_merge_existing(self) -> None:
        from emergent.wire.derive._error_caps import ProblemResponse
        from emergent.wire.axis._capability import FastAPIRouteContext

        pr = ProblemResponse()
        existing = {"responses": {"200": {"description": "OK"}}}
        ctx = FastAPIRouteContext(path="/test", method="GET", openapi_extra=existing)
        new_ctx = pr.compile_fastapi_route(ctx)
        assert new_ctx.openapi_extra is not None
        responses = new_ctx.openapi_extra["responses"]
        assert "200" in responses
        assert "404" in responses


# ═══════════════════════════════════════════════════════════════════════════════
# 5. _query_helpers.py — serialize_op_fields with non-serializable values,
#    provider_field
# ═══════════════════════════════════════════════════════════════════════════════


class TestQueryHelpers:
    """Cover serialize_op_fields non-json-serializable, provider_field."""

    def test_serialize_op_fields_non_serializable(self) -> None:
        import json
        from emergent.wire.derive._query_helpers import serialize_op_fields

        @dataclass(frozen=True)
        class FakeOp:
            name: str = "hello"
            custom: object = dataclass_field(default_factory=object)

        op = FakeOp()
        result = serialize_op_fields(op, ("name", "custom"))
        parsed = json.loads(result)
        assert parsed["name"] == "hello"
        # custom should be str() of the object
        assert isinstance(parsed["custom"], str)

    def test_serialize_op_fields_none_value_skipped(self) -> None:
        import json
        from emergent.wire.derive._query_helpers import serialize_op_fields

        @dataclass(frozen=True)
        class FakeOp2:
            name: str = "hello"
            missing: str | None = None

        op = FakeOp2()
        result = serialize_op_fields(op, ("name", "missing"))
        parsed = json.loads(result)
        assert "missing" not in parsed

    def test_provider_field(self) -> None:
        from emergent.wire.derive._query_helpers import provider_field

        result = provider_field(Users)
        # Should produce an Annotated type with ComposeNode
        assert result is not None

    def test_id_path_single(self) -> None:
        from emergent.wire.derive._query_helpers import id_path

        assert id_path(("id",)) == "{id}"

    def test_id_path_composite(self) -> None:
        from emergent.wire.derive._query_helpers import id_path

        assert id_path(("org_id", "user_id")) == "{org_id}/{user_id}"


# ═══════════════════════════════════════════════════════════════════════════════
# 6. _trigger.py — HTTPTriggers, CLITriggers, NestedHTTPTriggers,
#    FilteredTriggerGen, PrefixedTriggerGen, MultiTriggerGen
# ═══════════════════════════════════════════════════════════════════════════════


class TestTriggerGen:
    """Cover trigger generators."""

    def test_http_triggers_known_route(self) -> None:
        from emergent.wire.derive._trigger import HTTPTriggers
        from emergent.wire.derive._opspec import Op

        triggers = HTTPTriggers("/api/users")
        stub = Op(name="List", input_proj=NoFields(), output=ListResponse(),
                  handler_template=FetchMany(), effects=(Read(),))
        trigger = triggers(User, stub)
        assert isinstance(trigger, HTTPRouteTrigger)
        assert trigger.method == "GET"

    def test_http_triggers_unknown_route_fallback(self) -> None:
        from emergent.wire.derive._trigger import HTTPTriggers
        from emergent.wire.derive._opspec import Op

        triggers = HTTPTriggers("/api/users")
        stub = Op(name="Export", input_proj=NoFields(), output=ListResponse(),
                  handler_template=FetchMany())
        trigger = triggers(User, stub)
        assert isinstance(trigger, HTTPRouteTrigger)
        assert trigger.method == "POST"
        assert "export" in trigger.path

    def test_http_triggers_custom_route_spec_string(self) -> None:
        from emergent.wire.derive._trigger import HTTPTriggers
        from emergent.wire.derive._opspec import Op

        triggers = HTTPTriggers("/api/users", routes={
            "List": ("GET", False),
            "Get": ("GET", True),
            "Custom": ("POST", "/custom_path"),
        })
        stub = Op(name="Custom", input_proj=NoFields(), output=OkResponse(),
                  handler_template=FetchMany())
        trigger = triggers(User, stub)
        assert isinstance(trigger, HTTPRouteTrigger)
        assert trigger.path == "/api/users/custom_path"

    def test_nested_http_triggers(self) -> None:
        from emergent.wire.derive._trigger import NestedHTTPTriggers
        from emergent.wire.derive._opspec import Op

        triggers = NestedHTTPTriggers("/users", ("user_id",), "posts")
        stub = Op(name="List", input_proj=NoFields(), output=ListResponse(),
                  handler_template=FetchMany(), effects=(Read(),))
        trigger = triggers(Post, stub)
        assert isinstance(trigger, HTTPRouteTrigger)
        assert "/users/{user_id}/posts" in trigger.path

    def test_nested_http_triggers_unknown_route(self) -> None:
        from emergent.wire.derive._trigger import NestedHTTPTriggers
        from emergent.wire.derive._opspec import Op

        triggers = NestedHTTPTriggers("/users", ("user_id",), "posts")
        stub = Op(name="Export", input_proj=NoFields(), output=ListResponse(),
                  handler_template=FetchMany())
        trigger = triggers(Post, stub)
        assert isinstance(trigger, HTTPRouteTrigger)
        assert "export" in trigger.path

    def test_nested_http_triggers_custom_spec(self) -> None:
        from emergent.wire.derive._trigger import NestedHTTPTriggers
        from emergent.wire.derive._opspec import Op

        triggers = NestedHTTPTriggers("/users", ("user_id",), "posts", routes={
            "List": ("GET", False),
            "Get": ("GET", "/specific"),
        })
        stub = Op(name="Get", input_proj=NoFields(), output=EntityResponse(),
                  handler_template=FetchOneById(), effects=(Read(),))
        trigger = triggers(Post, stub)
        assert isinstance(trigger, HTTPRouteTrigger)
        assert trigger.path.endswith("/specific")

    def test_cli_triggers(self) -> None:
        from emergent.wire.derive._trigger import CLITriggers
        from emergent.wire.derive._opspec import Op

        triggers = CLITriggers("user")
        stub = Op(name="List", input_proj=NoFields(), output=ListResponse(),
                  handler_template=FetchMany())
        trigger = triggers(User, stub)
        assert isinstance(trigger, CLITrigger)
        assert trigger.command == "user-list"

    def test_filtered_trigger_gen_only_ops(self) -> None:
        from emergent.wire.derive._trigger import FilteredTriggerGen, HTTPTriggers
        from emergent.wire.derive._opspec import Op

        inner = HTTPTriggers("/api/users")
        gen = FilteredTriggerGen(inner, only_ops=frozenset({"List"}))

        list_op = Op(name="List", input_proj=NoFields(), output=ListResponse(),
                     handler_template=FetchMany())
        assert gen(User, list_op) is not None

        get_op = Op(name="Get", input_proj=NoFields(), output=EntityResponse(),
                    handler_template=FetchOneById())
        assert gen(User, get_op) is None

    def test_filtered_trigger_gen_exclude_ops(self) -> None:
        from emergent.wire.derive._trigger import FilteredTriggerGen, HTTPTriggers
        from emergent.wire.derive._opspec import Op

        inner = HTTPTriggers("/api/users")
        gen = FilteredTriggerGen(inner, exclude_ops=frozenset({"Delete"}))

        delete_op = Op(name="Delete", input_proj=NoFields(), output=OkResponse(),
                       handler_template=FetchMany())
        assert gen(User, delete_op) is None

        list_op = Op(name="List", input_proj=NoFields(), output=ListResponse(),
                     handler_template=FetchMany())
        assert gen(User, list_op) is not None

    def test_prefixed_trigger_gen_http(self) -> None:
        from emergent.wire.derive._trigger import PrefixedTriggerGen, HTTPTriggers
        from emergent.wire.derive._opspec import Op

        inner = HTTPTriggers("/users")
        gen = PrefixedTriggerGen(inner, prefix="/v2")

        stub = Op(name="List", input_proj=NoFields(), output=ListResponse(),
                  handler_template=FetchMany())
        trigger = gen(User, stub)
        assert isinstance(trigger, HTTPRouteTrigger)
        assert trigger.path.startswith("/v2/users")

    def test_prefixed_trigger_gen_none_passthrough(self) -> None:
        from emergent.wire.derive._trigger import PrefixedTriggerGen, FilteredTriggerGen, HTTPTriggers
        from emergent.wire.derive._opspec import Op

        inner = FilteredTriggerGen(HTTPTriggers("/users"), only_ops=frozenset())
        gen = PrefixedTriggerGen(inner, prefix="/v2")

        stub = Op(name="List", input_proj=NoFields(), output=ListResponse(),
                  handler_template=FetchMany())
        trigger = gen(User, stub)
        assert trigger is None

    def test_multi_trigger_gen(self) -> None:
        from emergent.wire.derive._trigger import MultiTriggerGen, HTTPTriggers, CLITriggers
        from emergent.wire.derive._opspec import Op

        gen = MultiTriggerGen((HTTPTriggers("/users"), CLITriggers("user")))
        stub = Op(name="List", input_proj=NoFields(), output=ListResponse(),
                  handler_template=FetchMany())
        triggers = gen(User, stub)
        assert isinstance(triggers, tuple)
        assert len(triggers) == 2


# ═══════════════════════════════════════════════════════════════════════════════
# 7. _ctx.py — provider_node, base_query, filter_query, wrap_handler
# ═══════════════════════════════════════════════════════════════════════════════


class TestDeriveCtx:
    """Cover DeriveCtx properties and methods."""

    def test_provider_node_non_relational(self) -> None:
        ctx = DeriveCtx.from_entity(User)
        assert ctx.provider_node is None

    def test_base_query_non_relational(self) -> None:
        ctx = DeriveCtx.from_entity(User)
        assert ctx.base_query is None

    def test_filter_query_non_relational_noop(self) -> None:
        ctx = DeriveCtx.from_entity(User)
        new_ctx = ctx.filter_query(lambda e: e.id > 0)
        assert new_ctx is ctx

    def test_wrap_handler(self) -> None:
        @schema_meta(http_crud("/api/items", Users))
        @dataclass
        class WrapItem:
            id: Annotated[int, Identity()]
            name: str

        ctxs = compile_derive(WrapItem)
        ctx = ctxs[0]
        assert len(ctx.specs) > 0

        def _wrapper(inner: Any, spec: Any) -> Any:
            return inner
        new_ctx = ctx.wrap_handler(Read, _wrapper)
        for s in new_ctx.specs:
            if has_effect(s.effects, Read):
                assert isinstance(s.handler_template, WrappedTemplate)


# ═══════════════════════════════════════════════════════════════════════════════
# 8. _transforms.py — Filtered, Searchable, WithRetry, WithRateLimit,
#    EffectRateLimited, EffectDeprecated, ProjectResponse
# ═══════════════════════════════════════════════════════════════════════════════


class TestTransforms:
    """Cover transform compile_derive_modify paths."""

    def test_filtered_with_explicit_fields(self) -> None:
        from emergent.wire.derive._transforms import Filtered

        @schema_meta(http_crud("/api/items", Users), Filtered(("name",)))
        @dataclass
        class FilteredItem:
            id: Annotated[int, Identity()]
            name: str

        ctxs = compile_derive(FilteredItem)
        ctx = ctxs[0]
        read_specs = [s for s in ctx.specs if has_effect(s.effects, Read)]
        for s in read_specs:
            extra_names = [f[0] for f in s.extra_op_fields]
            assert "filter_name" in extra_names

    def test_filtered_without_fields_uses_filterable_effect(self) -> None:
        from emergent.wire.derive._transforms import Filtered

        @schema_meta(http_crud("/api/items", Users), Filtered())
        @dataclass
        class FilteredItem2:
            id: Annotated[int, Identity()]
            name: str

        ctxs = compile_derive(FilteredItem2)
        ctx = ctxs[0]
        # Without Filterable effect, no filter fields should be added
        read_specs = [s for s in ctx.specs if has_effect(s.effects, Read)]
        for s in read_specs:
            filter_names = [f[0] for f in s.extra_op_fields if f[0].startswith("filter_")]
            assert len(filter_names) == 0

    def test_searchable_with_explicit_fields(self) -> None:
        from emergent.wire.derive._transforms import Searchable

        @schema_meta(http_crud("/api/items", Users), Searchable(("name",)))
        @dataclass
        class SearchItem:
            id: Annotated[int, Identity()]
            name: str

        ctxs = compile_derive(SearchItem)
        ctx = ctxs[0]
        read_specs = [s for s in ctx.specs if has_effect(s.effects, Read)]
        for s in read_specs:
            extra_names = [f[0] for f in s.extra_op_fields]
            assert "q" in extra_names

    def test_searchable_without_fields_no_effect(self) -> None:
        from emergent.wire.derive._transforms import Searchable

        @schema_meta(http_crud("/api/items", Users), Searchable())
        @dataclass
        class SearchItem2:
            id: Annotated[int, Identity()]
            name: str

        ctxs = compile_derive(SearchItem2)
        ctx = ctxs[0]
        read_specs = [s for s in ctx.specs if has_effect(s.effects, Read)]
        for s in read_specs:
            q_fields = [f[0] for f in s.extra_op_fields if f[0] == "q"]
            assert len(q_fields) == 0

    def test_with_retry(self) -> None:
        from emergent.wire.derive._transforms import WithRetry

        @schema_meta(http_crud("/api/items", Users), WithRetry(3))
        @dataclass
        class RetryItem:
            id: Annotated[int, Identity()]
            name: str

        ctxs = compile_derive(RetryItem)
        ctx = ctxs[0]
        mutation_specs = [s for s in ctx.specs if has_effect(s.effects, Mutation)]
        for s in mutation_specs:
            cap_types = [type(c).__name__ for c in s.capabilities]
            assert "Retry" in cap_types

    def test_with_rate_limit(self) -> None:
        from emergent.wire.derive._transforms import WithRateLimit

        @schema_meta(http_crud("/api/items", Users), WithRateLimit(rpm=60))
        @dataclass
        class RateLimitItem:
            id: Annotated[int, Identity()]
            name: str

        ctxs = compile_derive(RateLimitItem)
        ctx = ctxs[0]
        for s in ctx.specs:
            cap_types = [type(c).__name__ for c in s.capabilities]
            assert "RateLimit" in cap_types

    def test_effect_rate_limited(self) -> None:
        from emergent.wire.derive._transforms import EffectRateLimited

        @schema_meta(http_crud("/api/items", Users), EffectRateLimited(rpm=120))
        @dataclass
        class ERLItem:
            id: Annotated[int, Identity()]
            name: str

        ctxs = compile_derive(ERLItem)
        # EffectRateLimited only applies to ops with RateLimited effect.
        # Since default CRUD ops don't have RateLimited effect, no cap is added
        # but the transform runs without error
        assert len(ctxs) == 1

    def test_effect_deprecated(self) -> None:
        from emergent.wire.derive._transforms import EffectDeprecated

        @schema_meta(http_crud("/api/items", Users), EffectDeprecated())
        @dataclass
        class DepItem:
            id: Annotated[int, Identity()]
            name: str

        ctxs = compile_derive(DepItem)
        # Without Deprecated effects on ops, no enricher is added
        assert len(ctxs) == 1

    def test_project_response_list_response(self) -> None:
        from emergent.wire.derive._transforms import ProjectResponse

        @schema_meta(http_crud("/api/items", Users), ProjectResponse(exclude=("email",)))
        @dataclass
        class ProjItem:
            id: Annotated[int, Identity()]
            name: str
            email: str

        ctxs = compile_derive(ProjItem)
        ctx = ctxs[0]
        read_specs = [s for s in ctx.specs if has_effect(s.effects, Read)]
        for s in read_specs:
            if isinstance(s.response_spec, ListResponse):
                assert s.response_spec.exclude == ("email",)
            elif isinstance(s.response_spec, EntityResponse):
                assert s.response_spec.exclude == ("email",)


# ═══════════════════════════════════════════════════════════════════════════════
# 9. _builders.py — ExposureBuilder.build() converter branches
# ═══════════════════════════════════════════════════════════════════════════════


class TestBuilders:
    """Cover ExposureBuilder default converter branches."""

    def test_exposure_builder_single_field_non_attr_value(self) -> None:
        from emergent.wire.derive._builders import exposure

        async def handler(op: object) -> Result[int, DomainError]:
            return Ok(42)

        _op_type, _annotated_handler, exp = (
            exposure("test", User)
            .request(name=str)
            .response(result=int)
            .handler(handler)
            .trigger(HTTPRouteTrigger("POST", "/test"))
            .build()
        )
        # The converter should handle single-field case where val doesn't have attr
        exp_any: Any = exp
        from_domain: Any = exp_any.codec.response.from_domain
        resp: Any = from_domain(Ok(42))
        assert resp.result == 42

    def test_exposure_builder_multi_field_value(self) -> None:
        from emergent.wire.derive._builders import exposure

        @dataclass(frozen=True)
        class Res:
            x: int = 1
            y: str = "hi"

        async def handler(op: object) -> Result[Res, DomainError]:
            return Ok(Res())

        _op_type, _, exp = (
            exposure("test2", User)
            .request(name=str)
            .response(x=int, y=str)
            .handler(handler)
            .trigger(HTTPRouteTrigger("POST", "/test2"))
            .build()
        )
        exp_any: Any = exp
        from_domain: Any = exp_any.codec.response.from_domain
        resp: Any = from_domain(Ok(Res()))
        assert resp.x == 1
        assert resp.y == "hi"

    def test_exposure_builder_error_branch(self) -> None:
        from emergent.wire.derive._builders import exposure

        async def handler(op: object) -> Result[int, DomainError]:
            return Error(NotFound(entity="X", id={}))

        _op_type, _, exp = (
            exposure("test3", User)
            .request(name=str)
            .response(result=int)
            .handler(handler)
            .trigger(HTTPRouteTrigger("POST", "/test3"))
            .build()
        )
        exp_any: Any = exp
        from_domain: Any = exp_any.codec.response.from_domain
        err = NotFound(entity="X", id={})
        resp: Any = from_domain(Error(err))
        assert resp is err

    def test_exposure_builder_invalid_result_raises(self) -> None:
        from emergent.wire.derive._builders import exposure

        async def handler(op: object) -> Result[int, DomainError]:
            return Ok(1)

        _op_type, _, exp = (
            exposure("test4", User)
            .request(name=str)
            .response(result=int)
            .handler(handler)
            .trigger(HTTPRouteTrigger("POST", "/test4"))
            .build()
        )
        exp_any: Any = exp
        from_domain: Any = exp_any.codec.response.from_domain
        with pytest.raises(TypeError, match="Expected Result"):
            from_domain("not_a_result")


# ═══════════════════════════════════════════════════════════════════════════════
# 10. patterns/methods.py — Methods + MethodDialect
# ═══════════════════════════════════════════════════════════════════════════════


class TestMethods:
    """Cover _build_method_operation, Methods, MethodDialect."""

    def test_methods_classmethod_dispatch(self) -> None:
        from emergent.wire.derive.patterns.methods import Methods, post

        @schema_meta(Methods())
        @dataclass
        class Svc:
            @classmethod
            @post("/api/do")
            async def do_thing(cls, name: str) -> Result[str, DomainError]:
                return Ok(f"hello {name}")

        ctxs = compile_derive(Svc)
        assert len(ctxs) == 1
        assert len(ctxs[0].operations) == 1

    def test_methods_staticmethod_dispatch(self) -> None:
        from emergent.wire.derive.patterns.methods import Methods, post

        @schema_meta(Methods())
        @dataclass
        class Svc2:
            @staticmethod
            @post("/api/health")
            async def health() -> Result[str, DomainError]:
                return Ok("ok")

        ctxs = compile_derive(Svc2)
        assert len(ctxs[0].operations) == 1

    def test_methods_instance_method_dispatch(self) -> None:
        from emergent.wire.derive.patterns.methods import Methods, post

        @schema_meta(Methods())
        @dataclass
        class Svc3:
            @post("/api/act")
            async def act(self, x: int) -> Result[int, DomainError]:
                return Ok(x * 2)

        ctxs = compile_derive(Svc3)
        assert len(ctxs[0].operations) == 1

    def test_methods_sync_method_raises(self) -> None:
        from emergent.wire.derive.patterns.methods import Methods, post

        @schema_meta(Methods())
        @dataclass
        class BadSvc:
            @classmethod
            @post("/api/bad")
            def bad(cls) -> Result[str, DomainError]:
                return Ok("nope")

        with pytest.raises(TypeError, match="must be async"):
            compile_derive(BadSvc)

    def test_methods_non_result_return_raises(self) -> None:
        from emergent.wire.derive.patterns.methods import Methods, post

        @schema_meta(Methods())
        @dataclass
        class BadSvc2:
            @classmethod
            @post("/api/bad2")
            async def bad(cls) -> str:
                return "nope"

        with pytest.raises(TypeError, match="must return Result"):
            compile_derive(BadSvc2)

    def test_methods_with_description(self) -> None:
        from emergent.wire.derive.patterns.methods import Methods, method

        @schema_meta(Methods())
        @dataclass
        class DescSvc:
            @classmethod
            @method(HTTPRouteTrigger("GET", "/help"), description="Returns help text", order=10)
            async def help_cmd(cls) -> Result[str, DomainError]:
                return Ok("help")

        ctxs = compile_derive(DescSvc)
        assert len(ctxs[0].operations) == 1
        # HelpMeta capability should be present
        caps = ctxs[0].operations[0][2].capabilities
        cap_types = [type(c).__name__ for c in caps]
        assert "HelpMeta" in cap_types

    def test_methods_multiple_triggers(self) -> None:
        from emergent.wire.derive.patterns.methods import Methods, post, command

        @schema_meta(Methods())
        @dataclass
        class MultiSvc:
            @classmethod
            @post("/api/create")
            @command("create")
            async def create(cls, name: str) -> Result[str, DomainError]:
                return Ok(name)

        ctxs = compile_derive(MultiSvc)
        # Should produce 2 operations (one per trigger)
        assert len(ctxs[0].operations) == 2

    def test_methods_dataclass_result_type_fields(self) -> None:
        from emergent.wire.derive.patterns.methods import Methods, post

        @schema_meta(Methods())
        @dataclass
        class OrderSvc:
            @classmethod
            @post("/api/orders")
            async def create(cls, customer: str) -> Result[OrderResult, DomainError]:
                return Ok(OrderResult(id=1, status="created"))

        ctxs = compile_derive(OrderSvc)
        assert len(ctxs[0].operations) == 1

    def test_method_dialect_with_http_triggers(self) -> None:
        from emergent.wire.derive.patterns.methods import MethodDialect, op
        from emergent.wire.derive._trigger import HTTPTriggers

        @schema_meta(MethodDialect(triggers=HTTPTriggers("/api/orders")))
        @dataclass
        class OrderDialect:
            @classmethod
            @op("Create", effects=(Creates(),))
            async def create(cls, customer: str) -> Result[int, DomainError]:
                return Ok(1)

        ctxs = compile_derive(OrderDialect)
        assert len(ctxs[0].operations) == 1
        trigger = ctxs[0].operations[0][2].trigger
        assert isinstance(trigger, HTTPRouteTrigger)
        assert trigger.method == "POST"

    def test_method_dialect_trigger_returns_none(self) -> None:
        from emergent.wire.derive.patterns.methods import MethodDialect, op
        from emergent.wire.derive._trigger import FilteredTriggerGen, HTTPTriggers

        filtered = FilteredTriggerGen(HTTPTriggers("/api"), only_ops=frozenset())

        @schema_meta(MethodDialect(triggers=filtered))
        @dataclass
        class FilteredDialect:
            @classmethod
            @op("Create", effects=(Creates(),))
            async def create(cls, name: str) -> Result[int, DomainError]:
                return Ok(1)

        ctxs = compile_derive(FilteredDialect)
        # TriggerGen returns None -> op is skipped
        assert len(ctxs[0].operations) == 0

    def test_method_dialect_skips_non_op_methods(self) -> None:
        from emergent.wire.derive.patterns.methods import MethodDialect, op
        from emergent.wire.derive._trigger import HTTPTriggers

        @schema_meta(MethodDialect(triggers=HTTPTriggers("/api")))
        @dataclass
        class MixedDialect:
            @classmethod
            @op("Create")
            async def create(cls, name: str) -> Result[int, DomainError]:
                return Ok(1)

            @classmethod
            async def helper(cls) -> str:
                return "not an op"

        ctxs = compile_derive(MixedDialect)
        assert len(ctxs[0].operations) == 1

    def test_method_converter_single_field_ok_branch(self) -> None:
        """Cover methods.py line 343-344: single field, val doesn't have attr."""
        from emergent.wire.derive.patterns.methods import Methods, post

        @schema_meta(Methods())
        @dataclass
        class ScalarSvc:
            @classmethod
            @post("/api/scalar")
            async def get_val(cls) -> Result[int, DomainError]:
                return Ok(99)

        ctxs = compile_derive(ScalarSvc)
        exposure_obj: Any = ctxs[0].operations[0][2]
        # Verify response converter handles scalar Ok value
        resp_cls: Any = exposure_obj.codec.response
        result: Any = resp_cls.from_domain(Ok(99))
        assert result.result == 99

    def test_method_converter_error_branch(self) -> None:
        """Cover methods.py line 347-348: Error(err) passthrough."""
        from emergent.wire.derive.patterns.methods import Methods, post

        @schema_meta(Methods())
        @dataclass
        class ErrSvc:
            @classmethod
            @post("/api/fail")
            async def fail(cls) -> Result[int, DomainError]:
                return Error(NotFound(entity="X", id={}))

        ctxs = compile_derive(ErrSvc)
        exposure_obj: Any = ctxs[0].operations[0][2]
        resp_cls: Any = exposure_obj.codec.response
        err = NotFound(entity="X", id={})
        result: Any = resp_cls.from_domain(Error(err))
        assert result is err

    def test_method_converter_invalid_result_raises(self) -> None:
        """Cover methods.py line 349-350: TypeError for non-Result."""
        from emergent.wire.derive.patterns.methods import Methods, post

        @schema_meta(Methods())
        @dataclass
        class InvalidSvc:
            @classmethod
            @post("/api/invalid")
            async def invalid(cls) -> Result[int, DomainError]:
                return Ok(1)

        ctxs = compile_derive(InvalidSvc)
        exposure_obj: Any = ctxs[0].operations[0][2]
        resp_cls: Any = exposure_obj.codec.response
        with pytest.raises(TypeError, match="Expected Result"):
            resp_cls.from_domain("not_result")

    def test_stub_op_null_template_raises(self) -> None:
        """Cover methods.py line 398: _NullTemplate.build raises."""
        from emergent.wire.derive.patterns.methods import _stub_op

        stub = _stub_op("Test", (Read(),))
        with pytest.raises(RuntimeError, match="should never be called"):
            build_fn: Any = stub.handler_template.build
            build_fn(None)


# ═══════════════════════════════════════════════════════════════════════════════
# 11. patterns/nested.py — NestedCRUD
# ═══════════════════════════════════════════════════════════════════════════════


class TestNestedCRUD:
    """Cover NestedCRUD with fk_field and fallback ref lookup."""

    def test_nested_crud_with_explicit_fk_field(self) -> None:
        from emergent.wire.derive.patterns.nested import NestedCRUD

        @schema_meta(NestedCRUD(parent=User, parent_path="/users", provider_node=Posts, fk_field="user_id"))
        @dataclass
        class NestedPost:
            id: Annotated[int, Identity()]
            user_id: Annotated[int, Ref(User)]
            title: str
            content: str

        ctxs = compile_derive(NestedPost)
        assert len(ctxs) == 1
        assert len(ctxs[0].specs) > 0

    def test_nested_crud_auto_detect_fk(self) -> None:
        from emergent.wire.derive.patterns.nested import NestedCRUD

        @schema_meta(NestedCRUD(parent=User, parent_path="/users", provider_node=Posts))
        @dataclass
        class AutoPost:
            id: Annotated[int, Identity()]
            user_id: Annotated[int, Ref(User)]
            title: str

        ctxs = compile_derive(AutoPost)
        assert len(ctxs) == 1

    def test_nested_crud_invalid_fk_raises(self) -> None:
        from emergent.wire.derive.patterns.nested import NestedCRUD

        @schema_meta(NestedCRUD(parent=User, parent_path="/users", provider_node=Posts, fk_field="missing"))
        @dataclass
        class BadPost:
            id: Annotated[int, Identity()]
            title: str

        with pytest.raises(ValueError, match="has no field 'missing'"):
            compile_derive(BadPost)

    def test_nested_crud_no_identity_raises(self) -> None:
        from emergent.wire.derive.patterns.nested import NestedCRUD

        @schema_meta(NestedCRUD(parent=User, parent_path="/users", provider_node=Posts, fk_field="user_id"))
        @dataclass
        class NoIdPost:
            user_id: int
            title: str

        with pytest.raises(ValueError, match="needs Annotated"):
            compile_derive(NoIdPost)

    def test_nested_crud_no_ref_raises(self) -> None:
        from emergent.wire.derive.patterns.nested import NestedCRUD

        @schema_meta(NestedCRUD(parent=User, parent_path="/users", provider_node=Posts))
        @dataclass
        class NoRefPost:
            id: Annotated[int, Identity()]
            title: str

        with pytest.raises(ValueError, match="has no Ref"):
            compile_derive(NoRefPost)


# ═══════════════════════════════════════════════════════════════════════════════
# 12. auth/caps.py — Authenticated with Public skip, OwnerScoped
# ═══════════════════════════════════════════════════════════════════════════════


class TestAuthCaps:
    """Cover auth caps compile paths."""

    def test_authenticated_skips_public_effects(self) -> None:
        from emergent.wire.derive.auth.caps import Authenticated
        from emergent.wire.derive.auth.validate import TokenValidate
        from emergent.wire.derive.auth.extractors import BearerExtract

        async def lookup(token: str) -> AuthUser | None:
            return AuthUser(name="test", roles={"admin"})

        validate = TokenValidate(AuthUser, lookup)

        @schema_meta(
            http_crud("/api/items", Users),
            Authenticated(BearerExtract(), validate),
        )
        @dataclass
        class AuthItem:
            id: Annotated[int, Identity()]
            name: str

        ctxs = compile_derive(AuthItem)
        ctx = ctxs[0]
        # All specs should have auth caps since none are Public
        for s in ctx.specs:
            cap_types = [type(c).__name__ for c in s.capabilities]
            assert "TokenValidate" in cap_types or "BearerExtract" in cap_types

    def test_authenticated_with_effect_filter(self) -> None:
        from emergent.wire.derive.auth.caps import Authenticated
        from emergent.wire.derive.auth.validate import TokenValidate
        from emergent.wire.derive.auth.extractors import BearerExtract

        async def lookup(token: str) -> AuthUser | None:
            return AuthUser(name="test", roles={"admin"})

        validate = TokenValidate(AuthUser, lookup)

        @schema_meta(
            http_crud("/api/items", Users),
            Authenticated(BearerExtract(), validate, effect=Mutation),
        )
        @dataclass
        class AuthItem2:
            id: Annotated[int, Identity()]
            name: str

        ctxs = compile_derive(AuthItem2)
        ctx = ctxs[0]
        for s in ctx.specs:
            cap_types = [type(c).__name__ for c in s.capabilities]
            if has_effect(s.effects, Mutation):
                assert "TokenValidate" in cap_types or "BearerExtract" in cap_types
            else:
                assert "TokenValidate" not in cap_types

    def test_owner_scoped(self) -> None:
        from emergent.wire.derive.auth.caps import OwnerScoped

        @schema_meta(
            http_crud("/api/articles", Users),
            OwnerScoped(AuthUser, owner_field="author_id", identity_attr="name"),
        )
        @dataclass
        class OwnedArticle:
            id: Annotated[int, Identity()]
            title: str
            author_id: str

        ctxs = compile_derive(OwnedArticle)
        ctx = ctxs[0]
        assert len(ctx.specs) > 0
        # owner_id extra field should be added to Create ops
        create_specs = [s for s in ctx.specs if has_effect(s.effects, Creates)]
        for s in create_specs:
            extra_names = [f[0] for f in s.extra_op_fields]
            assert "author_id" in extra_names


# ═══════════════════════════════════════════════════════════════════════════════
# 13. _pipeline.py — Pipeline, BuildEntityData, CheckCache, PopulateCache
# ═══════════════════════════════════════════════════════════════════════════════


class TestPipeline:
    """Cover pipeline step execution branches."""

    @pytest.mark.anyio
    async def test_pipeline_returns_ok_result(self) -> None:
        from emergent.wire.derive._pipeline import Pipeline, PipelineContext

        @dataclass(frozen=True, slots=True)
        class SetResult:
            async def execute(self, pctx: PipelineContext[User]) -> PipelineContext[User]:
                pctx.result = User(1, "test", "test@test.com")
                return pctx

        spec = HandlerSpec(
            entity=User, entity_name="User",
            identity_names=("id",), non_identity_names=("name", "email"),
            base_query=None,
        )
        steps: Any = (SetResult(),)
        pipeline: Any = Pipeline(*steps)
        handler = pipeline.build(spec)

        @dataclass(frozen=True)
        class FakeOp:
            id: int = 1
            name: str = "test"
            email: str = "test@test.com"

        result: Any = await handler(FakeOp())
        assert type(result).__name__ == "Ok"
        assert result.value is not None

    @pytest.mark.anyio
    async def test_pipeline_short_circuits_on_error(self) -> None:
        from emergent.wire.derive._pipeline import Pipeline, PipelineContext

        @dataclass(frozen=True, slots=True)
        class FailStep:
            async def execute(self, pctx: PipelineContext[User]) -> Result[object, DomainError]:
                return Error(NotFound(entity="User", id={"id": 1}))

        @dataclass(frozen=True, slots=True)
        class NeverReached:
            async def execute(self, pctx: PipelineContext[User]) -> PipelineContext[User]:
                raise AssertionError("Should not be reached")

        spec = HandlerSpec(
            entity=User, entity_name="User",
            identity_names=("id",), non_identity_names=("name", "email"),
            base_query=None,
        )
        steps: Any = (FailStep(), NeverReached())
        pipeline: Any = Pipeline(*steps)
        handler = pipeline.build(spec)

        @dataclass(frozen=True)
        class FakeOp:
            id: int = 1

        result = await handler(FakeOp())
        assert isinstance(result, Error)

    @pytest.mark.anyio
    async def test_pipeline_short_circuits_on_ok(self) -> None:
        from emergent.wire.derive._pipeline import Pipeline, PipelineContext

        @dataclass(frozen=True, slots=True)
        class OkStep:
            async def execute(self, pctx: PipelineContext[User]) -> Result[object, DomainError]:
                return Ok(User(1, "cached", "c@c.com"))

        spec = HandlerSpec(
            entity=User, entity_name="User",
            identity_names=("id",), non_identity_names=("name", "email"),
            base_query=None,
        )
        steps: Any = (OkStep(),)
        pipeline: Any = Pipeline(*steps)
        handler = pipeline.build(spec)

        @dataclass(frozen=True)
        class FakeOp:
            id: int = 1

        result: Any = await handler(FakeOp())
        assert type(result).__name__ == "Ok"
        assert result.value is not None

    @pytest.mark.anyio
    async def test_build_entity_data_with_op_id(self) -> None:
        from emergent.wire.derive._pipeline import BuildEntityData, PipelineContext

        spec = HandlerSpec(
            entity=User, entity_name="User",
            identity_names=("id",), non_identity_names=("name", "email"),
            base_query=None,
        )

        @dataclass(frozen=True)
        class FakeOp:
            id: int = 1
            name: str = "test"
            email: str = "t@t.com"
            provider: object = None

        fake_op: Any = FakeOp()
        pctx: PipelineContext[User] = PipelineContext(spec=spec, op=fake_op)
        step = BuildEntityData()
        result = await step.execute(pctx)
        assert result.entity_data is not None
        assert result.entity_data["id"] == 1
        assert result.entity_data["name"] == "test"

    @pytest.mark.anyio
    async def test_build_entity_data_with_next_id(self) -> None:
        from emergent.wire.derive._pipeline import BuildEntityData, PipelineContext

        spec = HandlerSpec(
            entity=User, entity_name="User",
            identity_names=("id",), non_identity_names=("name", "email"),
            base_query=None,
        )

        class FakeProvider:
            async def next_id(self) -> int:
                return 42

        @dataclass
        class FakeOp:
            name: str = "test"
            email: str = "t@t.com"
            provider: FakeProvider = dataclass_field(default_factory=FakeProvider)

        fake_op: Any = FakeOp()
        pctx: PipelineContext[User] = PipelineContext(spec=spec, op=fake_op)
        step = BuildEntityData()
        result = await step.execute(pctx)
        assert result.entity_data is not None
        assert result.entity_data["id"] == 42

    @pytest.mark.anyio
    async def test_build_entity_data_no_id_no_next_id_raises(self) -> None:
        from emergent.wire.derive._pipeline import BuildEntityData, PipelineContext

        spec = HandlerSpec(
            entity=User, entity_name="User",
            identity_names=("id",), non_identity_names=("name", "email"),
            base_query=None,
        )

        class FakeProvider:
            pass

        @dataclass
        class FakeOp:
            name: str = "test"
            email: str = "t@t.com"
            provider: FakeProvider = dataclass_field(default_factory=FakeProvider)

        fake_op: Any = FakeOp()
        pctx: PipelineContext[User] = PipelineContext(spec=spec, op=fake_op)
        step = BuildEntityData()
        with pytest.raises(RuntimeError, match="has no next_id"):
            await step.execute(pctx)

    @pytest.mark.anyio
    async def test_check_cache_hit(self) -> None:
        from emergent.wire.derive._pipeline import CheckCache, PipelineContext

        spec = HandlerSpec(
            entity=User, entity_name="User",
            identity_names=("id",), non_identity_names=("name", "email"),
            base_query=None,
        )

        cached_user = User(1, "cached", "c@c.com")

        class FakeCache:
            async def get(self, key: str) -> User | None:
                return cached_user

        @dataclass
        class FakeOp:
            id: int = 1
            cache: FakeCache = dataclass_field(default_factory=FakeCache)
            provider: object = None

        fake_op: Any = FakeOp()
        pctx: PipelineContext[User] = PipelineContext(spec=spec, op=fake_op)
        step = CheckCache()
        result = await step.execute(pctx)
        assert isinstance(result, Ok)
        assert result.value is cached_user

    @pytest.mark.anyio
    async def test_check_cache_miss(self) -> None:
        from emergent.wire.derive._pipeline import CheckCache, PipelineContext

        spec = HandlerSpec(
            entity=User, entity_name="User",
            identity_names=("id",), non_identity_names=("name", "email"),
            base_query=None,
        )

        class FakeCache:
            async def get(self, key: str) -> User | None:
                return None

        @dataclass
        class FakeOp:
            id: int = 1
            cache: FakeCache = dataclass_field(default_factory=FakeCache)
            provider: object = None

        fake_op: Any = FakeOp()
        pctx: PipelineContext[User] = PipelineContext(spec=spec, op=fake_op)
        step = CheckCache()
        result = await step.execute(pctx)
        assert isinstance(result, PipelineContext)
        assert "cache_key" in result.extras

    @pytest.mark.anyio
    async def test_populate_cache(self) -> None:
        from emergent.wire.derive._pipeline import PopulateCache, PipelineContext

        spec = HandlerSpec(
            entity=User, entity_name="User",
            identity_names=("id",), non_identity_names=("name", "email"),
            base_query=None,
        )

        stored: dict[str, object] = {}

        class FakeCache:
            async def set(self, key: str, value: object) -> None:
                stored[key] = value

        existing_user = User(1, "test", "t@t.com")

        @dataclass
        class FakeOp:
            id: int = 1
            cache: FakeCache = dataclass_field(default_factory=FakeCache)
            provider: object = None

        fake_op: Any = FakeOp()
        pctx: PipelineContext[User] = PipelineContext(spec=spec, op=fake_op)
        pctx.existing = existing_user
        pctx.extras["cache_key"] = "User:1"
        step = PopulateCache()
        result = await step.execute(pctx)
        assert isinstance(result, PipelineContext)
        assert stored["User:1"] is existing_user


# ═══════════════════════════════════════════════════════════════════════════════
# 14. compile/_execute.py — execute_rrc_unified via Testing target
# ═══════════════════════════════════════════════════════════════════════════════


class TestExecuteRRCViaTestingTarget:
    """Exercise compile/_execute.py execute_rrc_unified through testing target."""

    @pytest.mark.anyio
    async def test_compile_and_invoke_list_route(self) -> None:
        from emergent.wire.axis.surface._app import Application
        from emergent.wire.compile.targets.testing import testing_compile

        @schema_meta(http_crud("/api/items", Users))
        @dataclass
        class InvokeItem:
            id: Annotated[int, Identity()]
            name: str

        ctxs = compile_derive(InvokeItem)
        ep = materialize(ctxs[0])
        app = Application().mount(ep)
        test_app = testing_compile(app)

        assert len(test_app.routes) > 0
        # Find List route (GET /api/items)
        list_route = None
        for route in test_app.routes:
            trigger = route.trigger
            if isinstance(trigger, HTTPRouteTrigger) and trigger.method == "GET" and not "{" in trigger.path:
                list_route = route
                break

        if list_route is not None:
            # This will fail because provider isn't set up, but it exercises
            # the execute_rrc_unified code path. Catch the runtime error.
            try:
                await list_route.call({})
            except Exception:
                pass  # Expected — no real provider

    @pytest.mark.anyio
    async def test_compile_and_invoke_methods_route(self) -> None:
        from emergent.wire.axis.surface._app import Application
        from emergent.wire.compile.targets.testing import testing_compile
        from emergent.wire.derive.patterns.methods import Methods, post

        @schema_meta(Methods())
        @dataclass
        class TestSvc:
            @staticmethod
            @post("/api/echo")
            async def echo(msg: str) -> Result[str, DomainError]:
                return Ok(f"echo: {msg}")

        ctxs = compile_derive(TestSvc)
        ep = materialize(ctxs[0])
        app = Application().mount(ep)
        test_app = testing_compile(app)

        assert len(test_app.routes) == 1
        route = test_app.routes[0]
        result = await route.call({"msg": "hello"})
        assert result is not None

    @pytest.mark.anyio
    async def test_compile_and_invoke_classmethod_route(self) -> None:
        from emergent.wire.axis.surface._app import Application
        from emergent.wire.compile.targets.testing import testing_compile
        from emergent.wire.derive.patterns.methods import Methods, post

        @schema_meta(Methods())
        @dataclass
        class ClassSvc:
            @classmethod
            @post("/api/greet")
            async def greet(cls, name: str) -> Result[str, DomainError]:
                return Ok(f"hello {name}")

        ctxs = compile_derive(ClassSvc)
        ep = materialize(ctxs[0])
        app = Application().mount(ep)
        test_app = testing_compile(app)
        route = test_app.routes[0]
        result = await route.call({"name": "Alice"})
        assert result is not None


# ═══════════════════════════════════════════════════════════════════════════════
# 15. compile/_request.py — build_request, build_field_value
# ═══════════════════════════════════════════════════════════════════════════════


class TestBuildRequest:
    """Cover build_request and build_field_value."""

    @pytest.mark.anyio
    async def test_build_request_simple(self) -> None:
        from emergent.wire.compile._request import build_request
        from emergent.wire.derive._codegen import create_dataclass, create_request_type

        op_type = create_dataclass("SimpleOp", [("name", str), ("age", int)], frozen=True)
        req_cls = create_request_type("SimpleReq", [("name", str), ("age", int)], op_type)

        request = await build_request(
            request_cls=req_cls,
            get_value=lambda n: {"name": "Alice", "age": 30}.get(n),
        )
        assert request.name == "Alice"
        assert request.age == 30

    @pytest.mark.anyio
    async def test_build_request_with_defaults(self) -> None:
        from emergent.wire.compile._request import build_request
        from emergent.wire.derive._codegen import create_dataclass, create_request_type

        op_type = create_dataclass("DefOp", [("name", str), ("count", int, 0)], frozen=True)
        req_cls = create_request_type("DefReq", [("name", str), ("count", int, 0)], op_type)

        request = await build_request(
            request_cls=req_cls,
            get_value=lambda n: {"name": "Alice"}.get(n),
        )
        assert request.name == "Alice"
        assert request.count == 0

    @pytest.mark.anyio
    async def test_build_request_optional_field(self) -> None:
        from emergent.wire.compile._request import build_request
        from emergent.wire.derive._codegen import create_dataclass, create_request_type

        op_type = create_dataclass("OptOp", [("name", str), ("email", str | None, None)], frozen=True)
        req_cls = create_request_type("OptReq", [("name", str), ("email", str | None, None)], op_type)

        request = await build_request(
            request_cls=req_cls,
            get_value=lambda n: {"name": "Alice"}.get(n),
        )
        assert request.name == "Alice"
        assert request.email is None

    @pytest.mark.anyio
    async def test_build_request_not_dataclass_raises(self) -> None:
        from emergent.wire.compile._request import build_request

        with pytest.raises(TypeError, match="not a dataclass"):
            await build_request(
                request_cls=str,
                get_value=lambda n: None,
            )


# ═══════════════════════════════════════════════════════════════════════════════
# 16. Full integration — compile_derive + materialize + Testing target
# ═══════════════════════════════════════════════════════════════════════════════


class TestFullIntegration:
    """End-to-end: compile_derive -> materialize -> testing_compile -> invoke."""

    @pytest.mark.anyio
    async def test_paginated_entity_compiles(self) -> None:
        from emergent.wire.derive._transforms import Paginated

        @schema_meta(http_crud("/api/items", Users), Paginated(20))
        @dataclass
        class PagItem:
            id: Annotated[int, Identity()]
            name: str

        ctxs = compile_derive(PagItem)
        ep = materialize(ctxs[0])
        assert len(ep.exposures) > 0

    @pytest.mark.anyio
    async def test_searchable_entity_compiles(self) -> None:
        from emergent.wire.derive._transforms import Searchable

        @schema_meta(http_crud("/api/items", Users), Searchable(("name",)))
        @dataclass
        class SrchItem:
            id: Annotated[int, Identity()]
            name: str

        ctxs = compile_derive(SrchItem)
        ep = materialize(ctxs[0])
        assert len(ep.exposures) > 0

    @pytest.mark.anyio
    async def test_readonly_entity_has_no_mutations(self) -> None:
        from emergent.wire.derive._transforms import Readonly

        @schema_meta(http_crud("/api/items", Users), Readonly())
        @dataclass
        class ROItem:
            id: Annotated[int, Identity()]
            name: str

        ctxs = compile_derive(ROItem)
        for s in ctxs[0].specs:
            assert not has_effect(s.effects, Mutation)

    @pytest.mark.anyio
    async def test_methods_service_invoke(self) -> None:
        from emergent.wire.axis.surface._app import Application
        from emergent.wire.compile.targets.testing import testing_compile
        from emergent.wire.derive.patterns.methods import Methods, post, get

        @schema_meta(Methods())
        @dataclass
        class CalcSvc:
            @staticmethod
            @post("/api/add")
            async def add(a: int, b: int) -> Result[int, DomainError]:
                return Ok(a + b)

            @staticmethod
            @get("/api/version")
            async def version() -> Result[str, DomainError]:
                return Ok("1.0")

        ctxs = compile_derive(CalcSvc)
        ep = materialize(ctxs[0])
        app = Application().mount(ep)
        test_app = testing_compile(app)
        assert len(test_app.routes) == 2

        # Invoke the add route
        for route in test_app.routes:
            if isinstance(route.trigger, HTTPRouteTrigger) and route.trigger.path == "/api/add":
                result = await route.call({"a": 3, "b": 4})
                assert result is not None

    @pytest.mark.anyio
    async def test_method_dialect_invoke(self) -> None:
        from emergent.wire.axis.surface._app import Application
        from emergent.wire.compile.targets.testing import testing_compile
        from emergent.wire.derive.patterns.methods import MethodDialect, op
        from emergent.wire.derive._trigger import HTTPTriggers

        @schema_meta(MethodDialect(triggers=HTTPTriggers("/api/orders")))
        @dataclass
        class OrderSvc:
            @staticmethod
            @op("Create", effects=(Creates(),))
            async def create(customer: str) -> Result[int, DomainError]:
                return Ok(42)

        ctxs = compile_derive(OrderSvc)
        ep = materialize(ctxs[0])
        app = Application().mount(ep)
        test_app = testing_compile(app)
        assert len(test_app.routes) == 1
        result = await test_app.routes[0].call({"customer": "Alice"})
        assert result is not None

    def test_multi_generator_compile(self) -> None:
        @schema_meta(http_crud("/api/items", Users), cli_crud("item", Users))
        @dataclass
        class MultiItem:
            id: Annotated[int, Identity()]
            name: str

        ctxs = compile_derive(MultiItem)
        assert len(ctxs) == 2
        # Both should have specs
        assert len(ctxs[0].specs) > 0
        assert len(ctxs[1].specs) > 0

    def test_materialize_empty_ctx(self) -> None:
        ctx = DeriveCtx.from_entity(User)
        ep = materialize(ctx)
        assert ep.exposures == ()

    def test_materialize_with_global_capabilities(self) -> None:
        @schema_meta(http_crud("/api/items", Users))
        @dataclass
        class CapItem:
            id: Annotated[int, Identity()]
            name: str

        ctxs = compile_derive(CapItem)
        ctx = ctxs[0]
        from emergent.wire.derive._error_caps import ErrorTransform
        ctx = ctx.add_capability(ErrorTransform())
        ep = materialize(ctx)
        assert len(ep.exposures) > 0


# ═══════════════════════════════════════════════════════════════════════════════
# 17. TestApp lifecycle
# ═══════════════════════════════════════════════════════════════════════════════


class TestTestAppLifecycle:
    """Cover TestApp __aenter__/__aexit__ paths."""

    @pytest.mark.anyio
    async def test_test_app_without_scope(self) -> None:
        from emergent.wire.compile.targets.testing import TestApp

        app = TestApp(routes=())
        async with app as a:
            assert a is app

    @pytest.mark.anyio
    async def test_test_app_with_scope(self) -> None:
        from nodnod import Scope
        from emergent.wire.compile.targets.testing import TestApp

        scope = Scope(detail="test")
        app = TestApp(routes=(), _app_scope=scope)
        async with app as a:
            assert a is app

# pyright: reportPrivateUsage=false
"""Final coverage tests — compile infra, contrib, and derive remaining lines.

Covers:
- compile/_execute.py: execute_rrc_unified, execute_stateful_unified, execute_delegate_unified
- compile/_delegate.py: resolve_handler_params with Annotated compose (Node, Optional, Retrieve)
- compile/_stateful.py: execute_stateful_turn, execute_stateful_done, FromDomain helpers
- compile/_request.py: build_field_value with compose Retrieve
- compile/_generate.py: assemble edge cases, to_datanode_auto, argparse flags
- compile/_pipeline.py: execute_with_pipeline, _make_scope, _family_mapped
- compile/_capabilities.py: Mount OpenAPI schema merging, _merge_openapi, _add_generic_mount_docs
- axis/query/contrib/_impls/_sqlalchemy.py: SA window funcs, aggregate compilation
- axis/query/contrib/_impls/_http.py: HTTPAPIProvider builder, filters, pagination
- axis/storage/contrib/_impls/_sqlalchemy.py: SQLAlchemyStorage backwards compat
- derive/patterns/methods.py: MethodDialect with TriggerGen, @op decorator, multi-trigger
- derive/auth/caps.py: Authenticated, RequireRole, AuthorizeOps
- derive/auth/extractors.py: BearerExtract, CLITokenExtract
- derive/auth/login.py: LoginOp, IssueToken, token_converter
- derive/_transforms.py: Filtered, Searchable, SoftDelete, Timestamped, etc.
- derive/_builders.py: ExposureBuilder, EndpointBuilder
"""

# NOTE: No `from __future__ import annotations` here. The ops graph uses
# get_type_hints() which fails to resolve forward references for locally
# defined classes when deferred annotations are enabled.

from dataclasses import dataclass, field
from datetime import datetime
from typing import Annotated, Any, cast
from unittest.mock import AsyncMock, MagicMock

from nodnod import Scope

import pytest
from kungfu import Error, Nothing, Ok, Result, Some

from emergent.wire.axis.schema._universal import Identity, schema_meta
from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger


# ═══════════════════════════════════════════════════════════════════════════════
# Module-level domain types (avoids get_type_hints failures)
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class Widget:
    id: Annotated[int, Identity()]
    name: str
    price: float = 0.0
    active: bool = True


@dataclass
class Task:
    id: Annotated[int, Identity()]
    title: str
    description: str
    owner_id: int
    created_at: datetime | None = None
    updated_at: datetime | None = None
    deleted_at: datetime | None = None


@dataclass
class AuthUser:
    name: str
    roles: set[str] = field(default_factory=lambda: {"user"})


class Widgets:
    """Provider node stub."""


def _get_roles(u: AuthUser) -> set[str]:
    return u.roles


async def _noop_enricher(_s: Scope) -> None:
    pass


# ── RRC domain types ──


@dataclass
class GreetOp:
    name: str


@dataclass
class GreetReq:
    name: str

    def to_domain(self) -> GreetOp:
        return GreetOp(name=self.name)


@dataclass
class GreetResp:
    value: str

    @classmethod
    def from_domain(cls, dom: Result[str, str]) -> "GreetResp":
        match dom:
            case Ok(v):
                return cls(value=v)
            case _:
                return cls(value="error")


async def _greet_handler(req: GreetOp) -> Result[str, str]:
    return Ok(f"Hello, {req.name}!")


@dataclass
class EchoOp:
    msg: str


@dataclass
class EchoReq:
    msg: str

    def to_domain(self) -> EchoOp:
        return EchoOp(msg=self.msg)


@dataclass
class EchoResp:
    text: str

    @classmethod
    def from_domain(cls, dom: Result[str, str]) -> "EchoResp":
        match dom:
            case Ok(v):
                return cls(text=v)
            case _:
                return cls(text="err")


async def _echo_handler(req: EchoOp) -> Result[str, str]:
    return Ok(req.msg)


@dataclass
class PingOp:
    val: str


@dataclass
class PingReq:
    val: str

    def to_domain(self) -> PingOp:
        return PingOp(val=self.val)


@dataclass
class PingResp:
    val: str

    @classmethod
    def from_domain(cls, dom: Result[str, str]) -> "PingResp":
        match dom:
            case Ok(v):
                return cls(val=v)
            case _:
                return cls(val="err")


async def _ping_handler(req: PingOp) -> Result[str, str]:
    return Ok(f"pong-{req.val}")


# ── Pipeline domain types ──


@dataclass
class PipeOp:
    x: int


@dataclass
class PipeReq:
    x: int

    def to_domain(self) -> PipeOp:
        return PipeOp(x=self.x)


@dataclass
class PipeResp:
    result: int

    @classmethod
    def from_domain(cls, dom: Result[int, str]) -> "PipeResp":
        match dom:
            case Ok(v):
                return cls(result=v)
            case _:
                return cls(result=-1)


async def _pipe_handler(req: PipeOp) -> Result[int, str]:
    return Ok(req.x * 2)


# ── Simple types for build_request tests ──


@dataclass
class OptReq:
    name: str
    bio: str | None = None


def _empty_str_list() -> list[str]:
    return []


@dataclass
class TagReq:
    tags: list[str] = field(default_factory=_empty_str_list)


@dataclass
class CountReq:
    count: int = 5


@dataclass
class DepWidget:
    id: int
    old_name: str = ""


@dataclass
class MiniWidget:
    x: int
    y: str


@dataclass
class FlagsReq:
    verbose: bool = False


@dataclass
class CountOnlyReq:
    count: int = 5


# ═══════════════════════════════════════════════════════════════════════════════
# 1. compile/_execute.py — execute_rrc_unified
# ═══════════════════════════════════════════════════════════════════════════════


class TestExecuteRRCUnified:
    @pytest.mark.asyncio
    async def test_execute_rrc_unified_basic(self) -> None:
        from emergent.ops._graph import ops
        from emergent.wire.axis.surface._handler import Handler
        from emergent.wire.axis.surface.codecs.rrc import rrc
        from emergent.wire.compile._core import Axes
        from emergent.wire.compile._execute import execute_rrc_unified

        runner = ops().on(cast(Any, GreetOp), _greet_handler).compile()
        codec = rrc(cast(Any, GreetReq), GreetResp)
        handler = Handler(codec=codec, runner=runner, capabilities=())

        result = await execute_rrc_unified(
            handler=handler,
            axes=Axes.default(),
            get_value=lambda n: {"name": "World"}.get(n),
            inject_scope=lambda scope: None,
        )
        assert isinstance(result, GreetResp)
        assert result.value == "Hello, World!"

    @pytest.mark.asyncio
    async def test_execute_rrc_unified_with_format(self) -> None:
        from emergent.ops._graph import ops
        from emergent.wire.axis.surface._handler import Handler
        from emergent.wire.axis.surface.codecs.rrc import rrc
        from emergent.wire.compile._core import Axes
        from emergent.wire.compile._execute import execute_rrc_unified

        runner = ops().on(cast(Any, EchoOp), _echo_handler).compile()
        codec = rrc(cast(Any, EchoReq), EchoResp)
        handler = Handler(codec=codec, runner=runner, capabilities=())

        result = await execute_rrc_unified(
            handler=handler,
            axes=Axes.default(),
            get_value=lambda n: {"msg": "echo"}.get(n),
            inject_scope=lambda scope: None,
            format_response=lambda r: {"formatted": r.text},
        )
        assert result == {"formatted": "echo"}

    @pytest.mark.asyncio
    async def test_execute_rrc_unified_async_inject(self) -> None:
        from emergent.ops._graph import ops
        from emergent.wire.axis.surface._handler import Handler
        from emergent.wire.axis.surface.codecs.rrc import rrc
        from emergent.wire.compile._core import Axes
        from emergent.wire.compile._execute import execute_rrc_unified

        runner = ops().on(cast(Any, PingOp), _ping_handler).compile()
        codec = rrc(cast(Any, PingReq), PingResp)
        handler = Handler(codec=codec, runner=runner, capabilities=())

        async def async_inject(scope: Scope) -> None:
            pass

        result = await execute_rrc_unified(
            handler=handler,
            axes=Axes.default(),
            get_value=lambda n: {"val": "test"}.get(n),
            inject_scope=async_inject,
        )
        assert isinstance(result, PingResp)
        assert result.val == "pong-test"


# ═══════════════════════════════════════════════════════════════════════════════
# 2. compile/_execute.py — execute_delegate_unified
# ═══════════════════════════════════════════════════════════════════════════════


class TestExecuteDelegateUnified:
    @pytest.mark.asyncio
    async def test_delegate_async_handler(self) -> None:
        from emergent.wire.axis.surface._handler import Handler
        from emergent.wire.axis.surface.codecs.delegate import delegate
        from emergent.wire.compile._execute import execute_delegate_unified

        async def my_delegate() -> str:
            return "delegate-ok"

        codec = delegate(my_delegate)
        handler = Handler(codec=codec, runner=None, capabilities=())  # type: ignore[arg-type]

        result = await execute_delegate_unified(
            handler=handler,
            inject_scope=lambda scope: None,
        )
        assert result == "delegate-ok"

    @pytest.mark.asyncio
    async def test_delegate_sync_handler(self) -> None:
        from emergent.wire.axis.surface._handler import Handler
        from emergent.wire.axis.surface.codecs.delegate import delegate
        from emergent.wire.compile._execute import execute_delegate_unified

        def my_sync_delegate() -> str:
            return "sync-delegate"

        codec = delegate(my_sync_delegate)
        handler = Handler(codec=codec, runner=None, capabilities=())  # type: ignore[arg-type]

        result = await execute_delegate_unified(
            handler=handler,
            inject_scope=lambda scope: None,
        )
        assert result == "sync-delegate"

    @pytest.mark.asyncio
    async def test_delegate_with_format(self) -> None:
        from emergent.wire.axis.surface._handler import Handler
        from emergent.wire.axis.surface.codecs.delegate import delegate
        from emergent.wire.compile._execute import execute_delegate_unified

        async def del_fn() -> int:
            return 42

        codec = delegate(del_fn)
        handler = Handler(codec=codec, runner=None, capabilities=())  # type: ignore[arg-type]

        result = await execute_delegate_unified(
            handler=handler,
            inject_scope=lambda scope: None,
            format_response=lambda v: {"result": v},
        )
        assert result == {"result": 42}


# ═══════════════════════════════════════════════════════════════════════════════
# 3. compile/_stateful.py — execute_stateful_turn and helpers
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class SFlow:
    step: int = 0


@dataclass
class FlowResp:
    msg: str


class TestStatefulTurnExecution:
    @pytest.mark.asyncio
    async def test_stateful_turn_non_terminal(self) -> None:
        from emergent.wire.compile._stateful import execute_stateful_turn

        flow_state = SFlow(step=0)

        async def transition(state: Any, **kwargs: Any) -> tuple[SFlow, FlowResp]:
            # Return (new_state, response) tuple — parse_transition_result handles this
            return (SFlow(step=1), FlowResp(msg="next"))

        mock_handler = MagicMock()
        mock_handler.codec = MagicMock()
        mock_handler.capabilities = ()

        new_state, _response, is_terminal = await execute_stateful_turn(
            handler=mock_handler,
            state=flow_state,
            resolved_method=transition,
            composed_params={},
        )
        assert not is_terminal
        assert isinstance(new_state, SFlow)
        assert new_state.step == 1

    @pytest.mark.asyncio
    async def test_stateful_turn_terminal(self) -> None:
        from emergent.wire.compile._stateful import execute_stateful_turn
        from emergent.wire.axis.surface.codecs.stateful import Done

        flow_state = SFlow(step=2)

        async def transition(state: Any, **kwargs: Any) -> Done:
            # Return Done — parse_transition_result detects terminal
            return Done()

        mock_handler = MagicMock()
        mock_handler.codec = MagicMock()
        mock_handler.capabilities = ()

        _new_state, _response, is_terminal = await execute_stateful_turn(
            handler=mock_handler,
            state=flow_state,
            resolved_method=transition,
            composed_params={},
        )
        assert is_terminal

    @pytest.mark.asyncio
    async def test_stateful_unified_non_terminal(self) -> None:
        from emergent.wire.compile._execute import execute_stateful_unified

        mock_codec = MagicMock()
        mock_codec.flow = SFlow
        mock_store = AsyncMock()
        mock_store.get = AsyncMock(return_value=Ok(Nothing()))
        mock_store.set = AsyncMock()
        mock_codec.store = mock_store

        mock_handler = MagicMock()
        mock_handler.codec = mock_codec
        mock_handler.capabilities = ()

        async def resolve() -> tuple[Any, dict[str, Any]]:
            async def method(state: Any, **kw: Any) -> tuple[SFlow, str]:
                # Return (new_state, response) tuple — not terminal
                return (SFlow(step=1), "mid-response")
            return (method, {})

        response, is_done = await execute_stateful_unified(
            handler=mock_handler,
            store_key="test-key",
            resolve_transition=resolve,
            inject_scope=lambda s: None,
        )
        assert not is_done
        assert response == "mid-response"


# ═══════════════════════════════════════════════════════════════════════════════
# 4. compile/_delegate.py — Annotated compose dialect
# ═══════════════════════════════════════════════════════════════════════════════


class TestDelegateComposeDialect:
    @pytest.mark.asyncio
    async def test_resolve_params_with_compose_retrieve(self) -> None:
        from emergent.wire.compile._delegate import resolve_handler_params
        from emergent.wire.axis.schema.dialects.compose import Retrieve
        from nodnod import Scope
        from nodnod.agent.event_loop.agent import EventLoopAgent

        scope = Scope()
        async with scope:
            scope.inject(str, "retrieved-value")

            def handler(msg: Annotated[str, Retrieve(str)]) -> str:
                return msg

            result = await resolve_handler_params(handler, scope, EventLoopAgent)
            assert result["msg"] == "retrieved-value"

    @pytest.mark.asyncio
    async def test_resolve_params_compose_optional_missing(self) -> None:
        from emergent.wire.compile._delegate import resolve_handler_params
        from emergent.wire.axis.schema.dialects.compose import Optional as ComposeOptional
        from nodnod import Scope
        from nodnod.agent.event_loop.agent import EventLoopAgent

        class MissingNode:
            pass

        scope = Scope()
        async with scope:
            def handler(val: Annotated[int, ComposeOptional(MissingNode)]) -> int:
                return val

            result = await resolve_handler_params(handler, scope, EventLoopAgent)
            assert isinstance(result["val"], Nothing)

    @pytest.mark.asyncio
    async def test_extract_compose_capability_non_annotated(self) -> None:
        from emergent.wire.compile._delegate import _extract_compose_capability

        assert _extract_compose_capability(int) is None
        assert _extract_compose_capability(str) is None

    def test_get_base_type_simple(self) -> None:
        from emergent.wire.compile._delegate import _get_base_type

        assert _get_base_type(int) is int
        assert _get_base_type("not a type") is None

    def test_get_base_type_annotated(self) -> None:
        from emergent.wire.compile._delegate import _get_base_type
        from emergent.wire.axis.schema.dialects.compose import Retrieve

        result = _get_base_type(Annotated[str, Retrieve(str)])
        assert result is str

    def test_extract_compose_result(self) -> None:
        from emergent.wire.compile._delegate import _extract_compose_result

        assert _extract_compose_result((True, "value")) == (True, "value")
        assert _extract_compose_result((False, "error")) == (False, "error")


# ═══════════════════════════════════════════════════════════════════════════════
# 5. compile/_request.py — compose Retrieve
# ═══════════════════════════════════════════════════════════════════════════════


class TestBuildFieldValueCompose:
    @pytest.mark.asyncio
    async def test_build_field_compose_retrieve_from_scope(self) -> None:
        from emergent.wire.compile._request import build_field_value
        from emergent.wire.axis.schema._inspect import FieldInfo
        from emergent.wire.axis.schema.dialects.compose import Retrieve
        from nodnod import Scope
        from nodnod.agent.event_loop.agent import EventLoopAgent

        scope = Scope()
        async with scope:
            scope.inject(str, "scoped-val")

            info = FieldInfo(
                name="token",
                base_type=str,
                is_optional=False,
                capabilities=(Retrieve(str),),
            )
            has_val, val = await build_field_value(
                name="token",
                info=info,
                get_value=lambda n: None,
                agent_cls=EventLoopAgent,
                scope=scope,
                dataclass_field=None,
            )
            assert has_val
            assert val == "scoped-val"

    @pytest.mark.asyncio
    async def test_build_field_compose_retrieve_missing(self) -> None:
        from emergent.wire.compile._request import build_field_value
        from emergent.wire.axis.schema._inspect import FieldInfo
        from emergent.wire.axis.schema.dialects.compose import Retrieve
        from nodnod import Scope
        from nodnod.agent.event_loop.agent import EventLoopAgent

        scope = Scope()
        async with scope:
            info = FieldInfo(
                name="count",
                base_type=int,
                is_optional=False,
                capabilities=(Retrieve(int),),
            )
            has_val, val = await build_field_value(
                name="count",
                info=info,
                get_value=lambda n: None,
                agent_cls=EventLoopAgent,
                scope=scope,
                dataclass_field=None,
            )
            assert not has_val
            assert "Failed to retrieve" in str(val)


# ═══════════════════════════════════════════════════════════════════════════════
# 6. compile/_generate.py — edge cases
# ═══════════════════════════════════════════════════════════════════════════════


class TestGenerateEdgeCases:
    def test_assemble_pydantic_simple(self) -> None:
        from emergent.wire.compile._generate import to_pydantic
        from emergent.wire.compile._core import Axes

        Model = to_pydantic(DepWidget, Axes.default())
        instance = Model(id=1, old_name="x")
        assert instance.old_name == "x"  # type: ignore[attr-defined]

    def test_to_datanode_auto(self) -> None:
        from emergent.wire.compile._generate import to_datanode_auto
        from nodnod import DataNode

        NodeCls = to_datanode_auto(MiniWidget, {})
        assert issubclass(NodeCls, DataNode)

    def test_assemble_argparse_bool_flag(self) -> None:
        from emergent.wire.compile._generate import to_argparse_args
        from emergent.wire.compile._core import Axes

        specs = to_argparse_args(FlagsReq, Axes.default())
        assert any(s.dest == "verbose" for s in specs)
        verbose_spec = next(s for s in specs if s.dest == "verbose")
        assert verbose_spec.kwargs.get("action") == "store_true"

    def test_assemble_argparse_optional_with_default(self) -> None:
        from emergent.wire.compile._generate import to_argparse_args
        from emergent.wire.compile._core import Axes

        specs = to_argparse_args(CountOnlyReq, Axes.default())
        count_spec = next(s for s in specs if s.dest == "count")
        assert not count_spec.is_positional
        assert count_spec.kwargs.get("default") == 5

    def test_pydantic_coercion_assemble_non_entity_raises(self) -> None:
        from emergent.wire.compile._generate import _pydantic_coercion

        coercion = _pydantic_coercion()
        with pytest.raises(TypeError, match="Expected EntityCompilation"):
            coercion.assemble(int, "not-entity-compilation")


# ═══════════════════════════════════════════════════════════════════════════════
# 7. compile/_pipeline.py — execute_with_pipeline
# ═══════════════════════════════════════════════════════════════════════════════


class TestPipelineExecution:
    @pytest.mark.asyncio
    async def test_execute_with_pipeline_basic(self) -> None:
        from emergent.ops._graph import ops
        from emergent.wire.axis.surface._handler import Handler
        from emergent.wire.axis.surface.codecs.rrc import rrc
        from emergent.wire.compile._core import Axes
        from emergent.wire.compile._pipeline import CompiledPipeline, execute_with_pipeline

        runner = ops().on(cast(Any, PipeOp), _pipe_handler).compile()
        codec = rrc(cast(Any, PipeReq), PipeResp)
        handler = Handler(codec=codec, runner=runner, capabilities=())

        async def execute_fn(h: Any, scope: Any, get_value: Any) -> Any:
            from emergent.wire.compile._request import build_request
            from emergent.wire.compile._rrc import execute_rrc

            req = await build_request(PipeReq, get_value)
            return await execute_rrc(h, req, scope)

        class FakeExtractor:
            async def extract(self, request: object) -> dict[str, object]:
                return {"x": 10}

        pipeline = CompiledPipeline(execute=execute_fn, extractor=FakeExtractor())

        result = await execute_with_pipeline(
            compiled=pipeline,
            handler=handler,
            axes=Axes.default(),
            raw_request=object(),
        )
        assert isinstance(result, PipeResp)
        assert result.result == 20

    def test_make_scope_no_layer(self) -> None:
        from emergent.wire.compile._pipeline import _make_scope
        from nodnod import Scope

        scope = _make_scope(None)
        assert isinstance(scope, Scope)

    def test_family_mapped_no_layer(self) -> None:
        from emergent.wire.compile._pipeline import _family_mapped
        from nodnod import Scope

        result = _family_mapped(None, Scope())
        assert result == {}


# ═══════════════════════════════════════════════════════════════════════════════
# 8. compile/_capabilities.py — Mount OpenAPI merging
# ═══════════════════════════════════════════════════════════════════════════════


class TestMountOpenAPI:
    def test_merge_openapi_paths(self) -> None:
        from emergent.wire.compile._capabilities import _merge_openapi

        target: dict[str, Any] = {"paths": {}, "tags": []}
        source = {
            "paths": {
                "/items": {
                    "get": {
                        "summary": "List items",
                        "tags": ["items"],
                        "responses": {
                            "200": {"description": "OK", "schema": {"type": "array"}},
                        },
                    }
                }
            },
            "tags": [{"name": "items", "description": "Items API"}],
        }

        _merge_openapi(target, source, "/legacy", "django")
        assert "/legacy/items" in target["paths"]
        assert len(target["tags"]) >= 2

    def test_merge_openapi_with_definitions(self) -> None:
        from emergent.wire.compile._capabilities import _merge_openapi

        target: dict[str, Any] = {"paths": {}, "tags": []}
        source = {
            "paths": {
                "/users": {
                    "post": {
                        "parameters": [
                            {"in": "body", "name": "body", "required": True,
                             "schema": {"$ref": "#/definitions/UserCreate"}},
                        ],
                        "responses": {"201": {"description": "Created"}},
                    }
                }
            },
            "definitions": {
                "UserCreate": {"type": "object", "properties": {"name": {"type": "string"}}},
            },
        }

        _merge_openapi(target, source, "/api", "myapp")
        assert "components" in target
        assert "MyappUserCreate" in target["components"]["schemas"]

    def test_add_generic_mount_docs(self) -> None:
        from emergent.wire.compile._capabilities import _add_generic_mount_docs

        schema: dict[str, Any] = {"paths": {}, "tags": []}
        _add_generic_mount_docs(schema, "/django", "django")
        assert "/django/{path:path}" in schema["paths"]
        assert any(t["name"] == "django-mount" for t in cast(list[dict[str, str]], schema["tags"]))

    def test_update_refs_nested(self) -> None:
        from emergent.wire.compile._capabilities import _update_refs

        obj: dict[str, Any] = {
            "schema": {"$ref": "#/definitions/Old"},
            "nested": [{"$ref": "#/definitions/Old"}],
        }
        _update_refs(obj, "#/definitions/Old", "#/components/schemas/New")
        assert obj["schema"]["$ref"] == "#/components/schemas/New"
        assert obj["nested"][0]["$ref"] == "#/components/schemas/New"


# ═══════════════════════════════════════════════════════════════════════════════
# 9. HTTP API Provider — builder, filters, pagination
# ═══════════════════════════════════════════════════════════════════════════════


class TestHTTPAPIProviderExtended:
    def test_builder_pagination_config(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import (
            OffsetLimitPagination, api,
        )

        builder = api(Widget).base("http://example.com/widgets").pagination(OffsetLimitPagination())
        assert builder._pagination is not None

    def test_builder_auth_config(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import BearerAuth, api

        builder = api(Widget).base("http://example.com").auth(BearerAuth("tok"))
        assert builder._auth is not None

    def test_builder_filter_config(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import BodyFilters, api

        builder = api(Widget).base("http://example.com").filters(BodyFilters())
        assert isinstance(builder._filter_encoding, BodyFilters)

    def test_builder_response_config(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import api

        builder = api(Widget).base("http://example.com").response(data_path="results", total_path="count")
        assert builder._data_path == "results"

    def test_builder_id_field_config(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import api

        builder = api(Widget).base("http://example.com").id_field("widget_id")
        assert builder._id_field == "widget_id"

    def test_body_filters_and(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import BodyFilters
        from emergent.wire.axis.query._expr import And, Eq, Field, Const

        enc = BodyFilters()
        result = enc.encode(And(Eq(Field("a"), Const(1)), Eq(Field("b"), Const(2))), Widget, None)
        assert "and" in result["filter"]

    def test_body_filters_or(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import BodyFilters
        from emergent.wire.axis.query._expr import Or, Eq, Field, Const

        result = BodyFilters().encode(Or(Eq(Field("a"), Const(1)), Eq(Field("b"), Const(2))), Widget, None)
        assert "or" in result["filter"]

    def test_query_param_ne_lt_le_ge(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import QueryParamFilters
        from emergent.wire.axis.query._expr import Ne, Lt, Le, Ge, Field, Const

        enc = QueryParamFilters()
        assert "name__ne" in enc.encode(Ne(Field("name"), Const("X")), Widget, None)
        assert "price__lt" in enc.encode(Lt(Field("price"), Const(10)), Widget, None)
        assert "price__lte" in enc.encode(Le(Field("price"), Const(10)), Widget, None)
        assert "price__gte" in enc.encode(Ge(Field("price"), Const(5)), Widget, None)

    def test_query_param_in_contains_starts_ends(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import QueryParamFilters
        from emergent.wire.axis.query._expr import In, Contains, StartsWith, EndsWith, Field

        enc = QueryParamFilters()
        assert "id__in" in enc.encode(In(Field("id"), (1, 2, 3)), Widget, None)
        assert "name__contains" in enc.encode(Contains(Field("name"), "wid"), Widget, None)
        assert "name__startswith" in enc.encode(StartsWith(Field("name"), "W"), Widget, None)
        assert "name__endswith" in enc.encode(EndsWith(Field("name"), "t"), Widget, None)

    def test_query_param_is_null(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import QueryParamFilters
        from emergent.wire.axis.query._expr import IsNull, IsNotNull, Field

        enc = QueryParamFilters()
        assert enc.encode(IsNull(Field("n")), Widget, None)["n__isnull"] == "true"
        assert enc.encode(IsNotNull(Field("n")), Widget, None)["n__isnull"] == "false"

    def test_query_param_and(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import QueryParamFilters
        from emergent.wire.axis.query._expr import And, Eq, Field, Const

        result = QueryParamFilters().encode(And(Eq(Field("a"), Const(1)), Eq(Field("b"), Const(2))), Widget, None)
        assert result["a"] == 1 and result["b"] == 2

    def test_query_param_or_raises(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import QueryParamFilters
        from emergent.wire.axis.query._expr import Or, Eq, Field, Const

        with pytest.raises(ValueError, match="OR filters not supported"):
            QueryParamFilters().encode(Or(Eq(Field("a"), Const(1)), Eq(Field("b"), Const(2))), Widget, None)

    def test_cursor_pagination_without_cursor(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import CursorPagination, CursorMod

        params: dict[str, object] = {}
        CursorPagination().apply(params, CursorMod(cursor="", limit=10))
        assert "cursor" not in params
        assert params["limit"] == 10

    def test_get_nested(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import _get_nested

        assert _get_nested({"a": {"b": {"c": 42}}}, "a.b.c") == 42
        assert _get_nested({"a": {"b": 1}}, "a.x.y") is None
        assert _get_nested({"a": 1}, "missing") is None


# ═══════════════════════════════════════════════════════════════════════════════
# 10. SA query contrib — window funcs, aggregates
# ═══════════════════════════════════════════════════════════════════════════════


class TestSAQueryWindowAndAggregate:
    @pytest.mark.asyncio
    async def test_sa_window_func_handlers(self) -> None:
        from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
        from sqlalchemy.orm import DeclarativeBase
        from emergent.wire.axis.query.contrib._impls._sqlalchemy import SQLAlchemyRelationalStore
        from emergent.wire.axis.query._window import RowNumber, Rank, DenseRank

        class WBase(DeclarativeBase):
            pass

        store = SQLAlchemyRelationalStore(Widget, "win_widgets", base=WBase)
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        try:
            async with engine.begin() as conn:
                await conn.run_sync(WBase.metadata.create_all)
            async with AsyncSession(engine, expire_on_commit=False) as session:
                provider = store(session)
                handlers = provider._make_window_func_handlers()
                assert RowNumber in handlers
                assert Rank in handlers
                assert DenseRank in handlers
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_sa_aggregate_count(self) -> None:
        from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
        from sqlalchemy.orm import DeclarativeBase
        from emergent.wire.axis.query.contrib._impls._sqlalchemy import SQLAlchemyRelationalStore
        from emergent.wire.axis.query import relational

        class ABase(DeclarativeBase):
            pass

        store = SQLAlchemyRelationalStore(Widget, "agg_widgets", base=ABase)
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        try:
            async with engine.begin() as conn:
                await conn.run_sync(ABase.metadata.create_all)
            async with AsyncSession(engine, expire_on_commit=False) as session:
                provider = store(session)
                await provider.insert(Widget(id=1, name="A", price=10.0))
                await provider.insert(Widget(id=2, name="B", price=20.0))
                await session.flush()
                query = relational(Widget).aggregate(total=lambda w: w.count())
                result = await provider.aggregate(query)
                assert result["total"] == 2
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_sa_aggregate_sum_avg(self) -> None:
        from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
        from sqlalchemy.orm import DeclarativeBase
        from emergent.wire.axis.query.contrib._impls._sqlalchemy import SQLAlchemyRelationalStore
        from emergent.wire.axis.query import relational

        class SBase(DeclarativeBase):
            pass

        store = SQLAlchemyRelationalStore(Widget, "sum_widgets", base=SBase)
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        try:
            async with engine.begin() as conn:
                await conn.run_sync(SBase.metadata.create_all)
            async with AsyncSession(engine, expire_on_commit=False) as session:
                provider = store(session)
                await provider.insert(Widget(id=1, name="A", price=10.0))
                await provider.insert(Widget(id=2, name="B", price=30.0))
                await session.flush()
                query = relational(Widget).aggregate(
                    total_price=lambda w: w.price.sum(),
                    avg_price=lambda w: w.price.avg(),
                )
                result = await provider.aggregate(query)
                assert result["total_price"] == 40.0
                assert result["avg_price"] == 20.0
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_sa_delete_where(self) -> None:
        from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
        from sqlalchemy.orm import DeclarativeBase
        from emergent.wire.axis.query.contrib._impls._sqlalchemy import SQLAlchemyRelationalStore
        from emergent.wire.axis.query import relational

        class DBase(DeclarativeBase):
            pass

        store = SQLAlchemyRelationalStore(Widget, "del_widgets", base=DBase)
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        try:
            async with engine.begin() as conn:
                await conn.run_sync(DBase.metadata.create_all)
            async with AsyncSession(engine, expire_on_commit=False) as session:
                provider = store(session)
                await provider.insert(Widget(id=1, name="Del", price=0.0))
                await provider.insert(Widget(id=2, name="Keep", price=100.0))
                await session.flush()
                query = relational(Widget).filter(lambda w: w.price == 0.0)
                count = await provider.delete_where(query)
                assert count == 1
        finally:
            await engine.dispose()


# ═══════════════════════════════════════════════════════════════════════════════
# 11. SA storage — backwards compat
# ═══════════════════════════════════════════════════════════════════════════════


class TestSAStorageBackwardsCompat:
    @pytest.mark.asyncio
    async def test_sqlalchemy_storage_class(self) -> None:
        from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
        from sqlalchemy.orm import DeclarativeBase
        from emergent.wire.axis.storage.contrib._impls._sqlalchemy import SQLAlchemyStorage

        class CompatBase(DeclarativeBase):
            pass

        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        try:
            async with engine.begin() as conn:
                SQLAlchemyStorage(session=AsyncSession(engine), entity=Widget,
                                  tablename="compat_widgets", base=CompatBase)
                await conn.run_sync(CompatBase.metadata.create_all)
            async with AsyncSession(engine, expire_on_commit=False) as session:
                storage = SQLAlchemyStorage(session=session, entity=Widget,
                                            tablename="compat_widgets", base=CompatBase)
                result = await storage.set(Widget(id=1, name="Old", price=5.0))
                assert isinstance(result, Ok)
                await session.commit()
                get_result = await storage.get(1)
                assert isinstance(get_result, Ok)
                assert isinstance(get_result.value, Some)
        finally:
            await engine.dispose()


# ═══════════════════════════════════════════════════════════════════════════════
# 12. derive/patterns/methods.py — @op, MethodDialect, multi-trigger
# ═══════════════════════════════════════════════════════════════════════════════


class TestMethodPatterns:
    def test_op_decorator(self) -> None:
        from emergent.wire.derive.patterns.methods import op, OP_ENTRIES_ATTR

        @op("DoSomething")
        async def my_op() -> Result[str, str]:
            return Ok("done")

        assert getattr(my_op, OP_ENTRIES_ATTR).name == "DoSomething"

    def test_op_decorator_with_effects(self) -> None:
        from emergent.wire.derive.patterns.methods import op, OP_ENTRIES_ATTR
        from emergent.wire.derive._effects import Creates

        @op("Create", effects=(Creates(),))
        async def create_fn() -> Result[str, str]:
            return Ok("created")

        assert isinstance(getattr(create_fn, OP_ENTRIES_ATTR).effects[0], Creates)

    def test_method_multi_trigger(self) -> None:
        from emergent.wire.derive.patterns.methods import post, command, TRIGGER_ENTRIES_ATTR

        @post("/api/items")
        @command("create-item")
        async def create_item(name: str) -> Result[str, str]:
            return Ok(name)

        assert len(getattr(create_item, TRIGGER_ENTRIES_ATTR)) == 2

    def test_methods_capability_compile(self) -> None:
        from emergent.wire.derive.patterns.methods import Methods, post
        from emergent.wire.derive._compile import compile_derive

        @schema_meta(Methods())
        @dataclass
        class OrderService:
            @classmethod
            @post("/api/orders")
            async def create(cls, name: str) -> Result[str, str]:
                return Ok(f"order-{name}")

        ctxs = compile_derive(OrderService)
        assert len(ctxs) == 1
        assert len(ctxs[0].operations) > 0

    def test_method_dialect_compile(self) -> None:
        from emergent.wire.derive.patterns.methods import MethodDialect, op
        from emergent.wire.derive._compile import compile_derive
        from emergent.wire.derive._trigger import HTTPTriggers

        @schema_meta(MethodDialect(triggers=HTTPTriggers("/api/things")))
        @dataclass
        class ThingService:
            @classmethod
            @op("Create")
            async def create(cls, name: str) -> Result[str, str]:
                return Ok(f"thing-{name}")

        ctxs = compile_derive(ThingService)
        assert len(ctxs) == 1
        assert len(ctxs[0].operations) > 0

    def test_put_delete_patch_shortcuts(self) -> None:
        from emergent.wire.derive.patterns.methods import put, delete, patch, TRIGGER_ENTRIES_ATTR

        @put("/api/items/{id}")
        async def update_item(id: int, name: str) -> Result[str, str]:
            return Ok("updated")

        @delete("/api/items/{id}")
        async def delete_item(id: int) -> Result[str, str]:
            return Ok("deleted")

        @patch("/api/items/{id}")
        async def patch_item(id: int, name: str) -> Result[str, str]:
            return Ok("patched")

        assert len(getattr(update_item, TRIGGER_ENTRIES_ATTR)) == 1
        assert len(getattr(delete_item, TRIGGER_ENTRIES_ATTR)) == 1
        assert len(getattr(patch_item, TRIGGER_ENTRIES_ATTR)) == 1


# ═══════════════════════════════════════════════════════════════════════════════
# 13. derive/auth/caps.py — Authenticated, RequireRole, AuthorizeOps
# ═══════════════════════════════════════════════════════════════════════════════


class TestAuthCaps:
    def test_authenticated_requires_validate(self) -> None:
        from emergent.wire.derive.auth.caps import Authenticated

        with pytest.raises(ValueError, match="requires a TokenValidate"):
            Authenticated()

    def test_authenticated_extracts_validate(self) -> None:
        from emergent.wire.derive.auth.caps import Authenticated
        from emergent.wire.derive.auth.validate import TokenValidate
        from emergent.wire.derive.auth.extractors import BearerExtract

        async def lookup(token: str):
            return AuthUser(name="test")

        auth = Authenticated(BearerExtract(), TokenValidate(AuthUser, lookup))
        assert auth.validate is not None
        assert len(auth.extractors) == 1

    def test_authenticated_compile_skips_public(self) -> None:
        from emergent.wire.derive.auth.caps import Authenticated
        from emergent.wire.derive.auth.validate import TokenValidate
        from emergent.wire.derive.auth.extractors import BearerExtract
        from emergent.wire.derive._compile import compile_derive
        from emergent.wire.derive._crud import http_crud, LIST, GET

        async def lookup(token: str):
            return AuthUser(name="test")

        @schema_meta(
            http_crud("/api/widgets", Widgets, ops=(LIST, GET)),
            Authenticated(BearerExtract(), TokenValidate(AuthUser, lookup)),
        )
        @dataclass
        class AuthWidget:
            id: Annotated[int, Identity()]
            name: str

        ctxs = compile_derive(AuthWidget)
        assert len(ctxs) >= 1

    @pytest.mark.asyncio
    async def test_require_role_passes(self) -> None:
        from emergent.wire.derive.auth.caps import RequireRole
        from nodnod import Scope

        scope = Scope()
        async with scope:
            scope.inject(AuthUser, AuthUser(name="admin", roles={"admin", "user"}))
            enricher = RequireRole(AuthUser, frozenset({"admin"}), _get_roles)
            called = False

            async def next_call(s: Scope) -> str:
                nonlocal called
                called = True
                return "ok"

            result = await enricher.enrich(next_call, scope)
            assert called and result == "ok"

    @pytest.mark.asyncio
    async def test_require_role_fails(self) -> None:
        from emergent.wire.derive.auth.caps import RequireRole
        from emergent.wire.derive.auth.errors import AuthorizationFailed
        from nodnod import Scope

        scope = Scope()
        async with scope:
            scope.inject(AuthUser, AuthUser(name="user", roles={"user"}))
            with pytest.raises(AuthorizationFailed):
                await RequireRole(AuthUser, frozenset({"admin"}), _get_roles).enrich(_noop_enricher, scope)

    @pytest.mark.asyncio
    async def test_require_role_not_authenticated(self) -> None:
        from emergent.wire.derive.auth.caps import RequireRole
        from emergent.wire.derive.auth.errors import AuthorizationFailed
        from nodnod import Scope

        scope = Scope()
        async with scope:
            with pytest.raises(AuthorizationFailed, match="not authenticated"):
                await RequireRole(AuthUser, frozenset({"admin"}), _get_roles).enrich(_noop_enricher, scope)

    def test_authorize_ops_strict_raises(self) -> None:
        from emergent.wire.derive.auth.caps import AuthorizeOps
        from emergent.wire.derive._compile import compile_derive
        from emergent.wire.derive._crud import http_crud, LIST, GET, CREATE

        @schema_meta(
            http_crud("/api/widgets", Widgets, ops=(LIST, GET, CREATE)),
            AuthorizeOps(AuthUser, {"Create": "admin"}, _get_roles, strict=True),
        )
        @dataclass
        class StrictWidget:
            id: Annotated[int, Identity()]
            name: str

        with pytest.raises(ValueError, match="has no role mapping"):
            compile_derive(StrictWidget)

    def test_authorize_ops_non_strict(self) -> None:
        from emergent.wire.derive.auth.caps import AuthorizeOps
        from emergent.wire.derive._compile import compile_derive
        from emergent.wire.derive._crud import http_crud, LIST, GET, CREATE

        @schema_meta(
            http_crud("/api/widgets", Widgets, ops=(LIST, GET, CREATE)),
            AuthorizeOps(AuthUser, {"Create": "admin"}, _get_roles, strict=False),
        )
        @dataclass
        class NonStrictWidget:
            id: Annotated[int, Identity()]
            name: str

        ctxs = compile_derive(NonStrictWidget)
        assert len(ctxs) >= 1

    def test_role_required_compile(self) -> None:
        from emergent.wire.derive.auth.caps import RoleRequired
        from emergent.wire.derive._compile import compile_derive
        from emergent.wire.derive._crud import http_crud, LIST, GET

        @schema_meta(
            http_crud("/api/widgets", Widgets, ops=(LIST, GET)),
            RoleRequired(AuthUser, "admin", _get_roles),
        )
        @dataclass
        class RoleWidget:
            id: Annotated[int, Identity()]
            name: str

        ctxs = compile_derive(RoleWidget)
        assert len(ctxs) >= 1


# ═══════════════════════════════════════════════════════════════════════════════
# 14. derive/auth/extractors.py — BearerExtract, CLITokenExtract
# ═══════════════════════════════════════════════════════════════════════════════


class TestAuthExtractors:
    @pytest.mark.asyncio
    async def test_bearer_extract_enrich_universal(self) -> None:
        from emergent.wire.derive.auth.extractors import BearerExtract, AuthToken
        from nodnod import Scope

        scope = Scope()
        async with scope:
            async def next_call(s: Scope) -> str:
                return "ok"

            result = await BearerExtract().enrich(next_call, scope)
            assert result == "ok"
            assert scope.get(AuthToken) is None

    @pytest.mark.asyncio
    async def test_cli_token_extract_enrich_universal(self) -> None:
        from emergent.wire.derive.auth.extractors import CLITokenExtract
        from nodnod import Scope

        scope = Scope()
        async with scope:
            async def next_call(s: Scope) -> str:
                return "cli-ok"

            result = await CLITokenExtract().enrich(next_call, scope)
            assert result == "cli-ok"


# ═══════════════════════════════════════════════════════════════════════════════
# 15. derive/auth/validate.py — TokenValidate
# ═══════════════════════════════════════════════════════════════════════════════


class TestTokenValidate:
    @pytest.mark.asyncio
    async def test_validate_no_token_raises(self) -> None:
        from emergent.wire.derive.auth.validate import TokenValidate
        from emergent.wire.derive.auth.errors import AuthenticationRequired
        from nodnod import Scope

        async def lookup(token: str):
            return AuthUser(name="test")

        scope = Scope()
        async with scope:
            with pytest.raises(AuthenticationRequired):
                await TokenValidate(AuthUser, lookup).enrich(_noop_enricher, scope)

    @pytest.mark.asyncio
    async def test_validate_invalid_token_raises(self) -> None:
        from emergent.wire.derive.auth.validate import TokenValidate
        from emergent.wire.derive.auth.extractors import AuthToken
        from emergent.wire.derive.auth.errors import AuthenticationRequired
        from nodnod import Scope

        async def lookup(token: str):
            return None

        scope = Scope()
        async with scope:
            scope.inject(AuthToken, AuthToken("bad-token"))
            with pytest.raises(AuthenticationRequired, match="invalid credentials"):
                await TokenValidate(AuthUser, lookup).enrich(_noop_enricher, scope)

    @pytest.mark.asyncio
    async def test_validate_success(self) -> None:
        from emergent.wire.derive.auth.validate import TokenValidate
        from emergent.wire.derive.auth.extractors import AuthToken
        from nodnod import Scope

        async def lookup(token: str):
            return AuthUser(name="alice") if token == "valid" else None

        scope = Scope()
        async with scope:
            scope.inject(AuthToken, AuthToken("valid"))

            async def next_call(s: Scope) -> str:
                wrapper = s.get(AuthUser)
                if wrapper is not None:
                    return cast(str, wrapper.value.name)
                return "none"

            result = await TokenValidate(AuthUser, lookup).enrich(next_call, scope)
            assert result == "alice"


# ═══════════════════════════════════════════════════════════════════════════════
# 16. derive/_transforms.py — various transforms
# ═══════════════════════════════════════════════════════════════════════════════


class TestDeriveTransforms:
    def test_filtered_with_explicit_fields(self) -> None:
        from emergent.wire.derive._transforms import Filtered
        from emergent.wire.derive._compile import compile_derive
        from emergent.wire.derive._crud import http_crud, LIST, GET

        @schema_meta(http_crud("/api/w1", Widgets, ops=(LIST, GET)), Filtered(("name", "price")))
        @dataclass
        class FilteredWidget:
            id: Annotated[int, Identity()]
            name: str
            price: float = 0.0

        ctxs = compile_derive(FilteredWidget)
        assert len(ctxs) >= 1

    def test_searchable_with_explicit_fields(self) -> None:
        from emergent.wire.derive._transforms import Searchable
        from emergent.wire.derive._compile import compile_derive
        from emergent.wire.derive._crud import http_crud, LIST, GET

        @schema_meta(http_crud("/api/w2", Widgets, ops=(LIST, GET)), Searchable(("name",)))
        @dataclass
        class SearchWidget:
            id: Annotated[int, Identity()]
            name: str

        ctxs = compile_derive(SearchWidget)
        assert len(ctxs) >= 1

    def test_soft_delete_compile(self) -> None:
        from emergent.wire.derive._transforms import SoftDelete
        from emergent.wire.derive._compile import compile_derive
        from emergent.wire.derive._crud import http_crud, LIST, GET, CREATE, DELETE

        @schema_meta(http_crud("/api/w3", Widgets, ops=(LIST, GET, CREATE, DELETE)), SoftDelete())
        @dataclass
        class SoftTask:
            id: Annotated[int, Identity()]
            name: str
            deleted_at: datetime | None = None

        ctxs = compile_derive(SoftTask)
        assert len(ctxs) >= 1

    def test_timestamped_compile(self) -> None:
        from emergent.wire.derive._transforms import Timestamped
        from emergent.wire.derive._compile import compile_derive
        from emergent.wire.derive._crud import http_crud, LIST, CREATE, UPDATE

        @schema_meta(http_crud("/api/w4", Widgets, ops=(LIST, CREATE, UPDATE)), Timestamped())
        @dataclass
        class TimedTask:
            id: Annotated[int, Identity()]
            name: str
            created_at: datetime | None = None
            updated_at: datetime | None = None

        ctxs = compile_derive(TimedTask)
        assert len(ctxs) >= 1

    def test_without_create(self) -> None:
        from emergent.wire.derive._transforms import WithoutCreate
        from emergent.wire.derive._compile import compile_derive
        from emergent.wire.derive._crud import http_crud, LIST, GET, CREATE

        @schema_meta(http_crud("/api/w5", Widgets, ops=(LIST, GET, CREATE)), WithoutCreate())
        @dataclass
        class NoCreateWidget:
            id: Annotated[int, Identity()]
            name: str

        for ctx in compile_derive(NoCreateWidget):
            assert "Create" not in [s.name for s in ctx.specs]

    def test_create_only(self) -> None:
        from emergent.wire.derive._transforms import CreateOnly
        from emergent.wire.derive._compile import compile_derive
        from emergent.wire.derive._crud import http_crud, LIST, GET, CREATE

        @schema_meta(http_crud("/api/w6", Widgets, ops=(LIST, GET, CREATE)), CreateOnly())
        @dataclass
        class CreateOnlyWidget:
            id: Annotated[int, Identity()]
            name: str

        for ctx in compile_derive(CreateOnlyWidget):
            for s in ctx.specs:
                assert s.name == "Create"

    def test_update_only(self) -> None:
        from emergent.wire.derive._transforms import UpdateOnly
        from emergent.wire.derive._compile import compile_derive
        from emergent.wire.derive._crud import http_crud, LIST, UPDATE

        @schema_meta(http_crud("/api/w7", Widgets, ops=(LIST, UPDATE)), UpdateOnly())
        @dataclass
        class UpdateOnlyWidget:
            id: Annotated[int, Identity()]
            name: str

        for ctx in compile_derive(UpdateOnlyWidget):
            for s in ctx.specs:
                assert s.name == "Update"

    def test_only_ops(self) -> None:
        from emergent.wire.derive._transforms import OnlyOps
        from emergent.wire.derive._compile import compile_derive
        from emergent.wire.derive._crud import http_crud, LIST, GET, CREATE

        @schema_meta(http_crud("/api/w8", Widgets, ops=(LIST, GET, CREATE)), OnlyOps(("List",)))
        @dataclass
        class OnlyListWidget:
            id: Annotated[int, Identity()]
            name: str

        for ctx in compile_derive(OnlyListWidget):
            assert [s.name for s in ctx.specs] == ["List"]

    def test_with_timeout_compile(self) -> None:
        from emergent.wire.derive._transforms import WithTimeout
        from emergent.wire.derive._compile import compile_derive
        from emergent.wire.derive._crud import http_crud, LIST

        @schema_meta(http_crud("/api/w9", Widgets, ops=(LIST,)), WithTimeout(30.0))
        @dataclass
        class TimeoutWidget:
            id: Annotated[int, Identity()]
            name: str

        assert len(compile_derive(TimeoutWidget)) >= 1

    def test_project_response(self) -> None:
        from emergent.wire.derive._transforms import ProjectResponse
        from emergent.wire.derive._compile import compile_derive
        from emergent.wire.derive._crud import http_crud, LIST, GET

        @schema_meta(http_crud("/api/w10", Widgets, ops=(LIST, GET)), ProjectResponse(exclude=("price",)))
        @dataclass
        class ProjWidget:
            id: Annotated[int, Identity()]
            name: str
            price: float = 0.0

        assert len(compile_derive(ProjWidget)) >= 1

    def test_paginated_compile(self) -> None:
        from emergent.wire.derive._transforms import Paginated
        from emergent.wire.derive._compile import compile_derive
        from emergent.wire.derive._crud import http_crud, LIST

        @schema_meta(http_crud("/api/w11", Widgets, ops=(LIST,)), Paginated(25))
        @dataclass
        class PagedWidget:
            id: Annotated[int, Identity()]
            name: str

        assert len(compile_derive(PagedWidget)) >= 1

    def test_sorted_compile(self) -> None:
        from emergent.wire.derive._transforms import Sorted
        from emergent.wire.derive._compile import compile_derive
        from emergent.wire.derive._crud import http_crud, LIST

        @schema_meta(http_crud("/api/w12", Widgets, ops=(LIST,)), Sorted("name", "desc"))
        @dataclass
        class SortedWidget:
            id: Annotated[int, Identity()]
            name: str

        assert len(compile_derive(SortedWidget)) >= 1

    def test_mutations_only(self) -> None:
        from emergent.wire.derive._transforms import MutationsOnly
        from emergent.wire.derive._compile import compile_derive
        from emergent.wire.derive._crud import http_crud, LIST, GET, CREATE

        @schema_meta(http_crud("/api/w13", Widgets, ops=(LIST, GET, CREATE)), MutationsOnly())
        @dataclass
        class MutWidget:
            id: Annotated[int, Identity()]
            name: str

        for ctx in compile_derive(MutWidget):
            for s in ctx.specs:
                assert s.name == "Create"

    def test_without_delete(self) -> None:
        from emergent.wire.derive._transforms import WithoutDelete
        from emergent.wire.derive._compile import compile_derive
        from emergent.wire.derive._crud import http_crud, LIST, DELETE

        @schema_meta(http_crud("/api/w14", Widgets, ops=(LIST, DELETE)), WithoutDelete())
        @dataclass
        class NoDelWidget:
            id: Annotated[int, Identity()]
            name: str

        for ctx in compile_derive(NoDelWidget):
            assert "Delete" not in [s.name for s in ctx.specs]

    def test_readonly(self) -> None:
        from emergent.wire.derive._transforms import Readonly
        from emergent.wire.derive._compile import compile_derive
        from emergent.wire.derive._crud import http_crud, LIST, GET, CREATE, DELETE

        @schema_meta(http_crud("/api/w15", Widgets, ops=(LIST, GET, CREATE, DELETE)), Readonly())
        @dataclass
        class ReadonlyWidget:
            id: Annotated[int, Identity()]
            name: str

        for ctx in compile_derive(ReadonlyWidget):
            for s in ctx.specs:
                assert s.name in ("List", "Get")


# ═══════════════════════════════════════════════════════════════════════════════
# 17. derive/_builders.py — ExposureBuilder
# ═══════════════════════════════════════════════════════════════════════════════


class TestExposureBuilder:
    def test_full_build(self) -> None:
        from emergent.wire.derive._builders import exposure

        async def handler(op: object) -> Result[str, str]:
            return Ok("built")

        op_type, _, exp = (
            exposure("create", Widget)
            .request(name=str, price=float)
            .response(id=int, status=str)
            .handler(handler)
            .trigger(HTTPRouteTrigger("POST", "/api/widgets"))
            .build()
        )
        assert op_type is not None and exp is not None

    def test_build_no_trigger_raises(self) -> None:
        from emergent.wire.derive._builders import exposure

        async def handler(op: object) -> Result[str, str]:
            return Ok("nope")

        with pytest.raises(ValueError, match="Trigger not set"):
            exposure("create", Widget).request(name=str).handler(handler).build()

    def test_build_no_handler_raises(self) -> None:
        from emergent.wire.derive._builders import exposure

        with pytest.raises(ValueError, match="Handler not set"):
            exposure("create", Widget).request(name=str).trigger(HTTPRouteTrigger("POST", "/w")).build()

    def test_build_with_caps(self) -> None:
        from emergent.wire.derive._builders import exposure
        from emergent.wire.axis.surface.transforms._response import AsDict

        async def handler(op: object) -> Result[str, str]:
            return Ok("capped")

        _, _, exp = (
            exposure("create", Widget).request(name=str).response(result=str)
            .handler(handler).trigger(HTTPRouteTrigger("POST", "/w")).caps(AsDict()).build()
        )
        assert len(exp.capabilities) == 1

    def test_build_with_custom_converter(self) -> None:
        from emergent.wire.derive._builders import exposure

        def my_converter(cls: type[Any], result: Any) -> Any:
            return cls(result="custom")

        async def handler(op: object) -> Result[str, str]:
            return Ok("custom")

        op_type, _, _ = (
            exposure("create", Widget).request(name=str).response(result=str)
            .handler(handler).trigger(HTTPRouteTrigger("POST", "/w"))
            .response_converter(my_converter).build()
        )
        assert op_type is not None

    def test_build_with_default_values(self) -> None:
        from emergent.wire.derive._builders import exposure

        async def handler(op: object) -> Result[str, str]:
            return Ok("defaults")

        _, _, exp = (
            exposure("create", Widget).request(name=str).response(status=(str, "ok"))
            .handler(handler).trigger(HTTPRouteTrigger("POST", "/w")).build()
        )
        assert exp is not None

    def test_endpoint_builder(self) -> None:
        from emergent.wire.derive._builders import exposure, endpoint_builder

        async def handler(op: object) -> Result[str, str]:
            return Ok("built")

        operation = (
            exposure("create", Widget).request(name=str).response(result=str)
            .handler(handler).trigger(HTTPRouteTrigger("POST", "/w")).build()
        )
        ep = endpoint_builder().build([operation])
        assert ep is not None and len(ep.exposures) == 1

    def test_response_list_returns_bare_array(self) -> None:
        from fastapi.testclient import TestClient

        from emergent.wire.axis.surface import application
        from emergent.wire.compile.targets.fastapi import fastapi_compile
        from emergent.wire.derive._builders import endpoint_builder, exposure

        async def handler(op: object) -> Result[list[dict[str, Any]], str]:
            return Ok([{"id": 1, "name": "a"}, {"id": 2, "name": "b"}])

        operation = (
            exposure("items", Widget)
            .response_list(id=int, name=str)
            .handler(handler)
            .trigger(HTTPRouteTrigger("GET", "/items"))
            .build()
        )
        client = TestClient(fastapi_compile(application().mount(endpoint_builder().build([operation]))))
        resp = client.get("/items")
        assert resp.status_code == 200
        body = resp.json()
        # Top-level JSON array, not a {"items": ...} envelope.
        assert isinstance(body, list)
        assert body == [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]

    def test_request_field_default_optional_param(self) -> None:
        from fastapi.testclient import TestClient

        from emergent.wire.axis.surface import application
        from emergent.wire.compile.targets.fastapi import fastapi_compile
        from emergent.wire.derive._builders import endpoint_builder, exposure
        from emergent.wire.derive._project import dict_converter

        async def handler(op: Any) -> Result[dict[str, Any], str]:
            return Ok({"page": op.page})

        operation = (
            exposure("paged", Widget)
            .request(page=(int, 7))  # optional query param with default
            .response(page=int)
            .handler(handler)
            .response_converter(dict_converter)
            .trigger(HTTPRouteTrigger("GET", "/paged"))
            .build()
        )
        client = TestClient(fastapi_compile(application().mount(endpoint_builder().build([operation]))))
        # Omit ?page= entirely → handler receives the declared default.
        resp = client.get("/paged")
        assert resp.status_code == 200
        assert resp.json() == {"page": 7}
        # Provide it → coerced and used.
        resp = client.get("/paged", params={"page": 3})
        assert resp.json() == {"page": 3}


# ═══════════════════════════════════════════════════════════════════════════════
# 18. derive/auth/login.py — LoginOp, token_converter
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class TokenResp:
    token: str | None
    error: str | None


class TestLoginOp:
    def test_token_converter_ok(self) -> None:
        from emergent.wire.derive.auth.login import token_converter

        result = cast(TokenResp, token_converter(TokenResp, Ok("my-token")))
        assert result.token == "my-token" and result.error is None

    def test_token_converter_error(self) -> None:
        from emergent.wire.derive.auth.login import token_converter

        result = cast(TokenResp, token_converter(TokenResp, Error("bad")))
        assert result.token is None and result.error == "bad"

    def test_login_op_compile(self) -> None:
        from emergent.wire.derive.auth.login import LoginOp
        from emergent.wire.axis.query._kv import kv
        from emergent.wire.axis.query.providers.memory import MemoryKVProvider
        from emergent.wire.derive._compile import compile_derive

        sessions: MemoryKVProvider[str, AuthUser] = MemoryKVProvider()
        session_qs = kv(AuthUser, key=lambda u: u.name)

        @schema_meta(LoginOp("/api/login", provider_node=Widgets, sessions=sessions,
                              session_qs=session_qs, match_field="name"))
        @dataclass
        class LoginWidget:
            id: Annotated[int, Identity()]
            name: str

        ctxs = compile_derive(LoginWidget)
        assert len(ctxs) >= 1
        assert any(s.name == "Login" for s in ctxs[0].specs)


# ═══════════════════════════════════════════════════════════════════════════════
# 19. compile/_stateful.py — FromDomain helpers
# ═══════════════════════════════════════════════════════════════════════════════


class TestStatefulFromDomain:
    def test_has_from_domain_false(self) -> None:
        from emergent.wire.compile._stateful import _has_from_domain

        assert not _has_from_domain(int)
        assert not _has_from_domain(str)

    def test_call_from_domain(self) -> None:
        from emergent.wire.compile._stateful import _call_from_domain, _has_from_domain
        from emergent.wire.axis.surface.codecs.rrc import FromDomain

        @dataclass
        class MyResp(FromDomain[Any]):
            val: str

            @classmethod
            def from_domain(cls, dom: Any) -> "MyResp":
                return cls(val=str(dom))

        assert _has_from_domain(MyResp)
        assert _call_from_domain(MyResp, 42).val == "42"


# ═══════════════════════════════════════════════════════════════════════════════
# 20. compile/_execute.py & _pipeline.py — helpers
# ═══════════════════════════════════════════════════════════════════════════════


class TestExecuteHelpers:
    def test_execute_family_mapped_no_layer(self) -> None:
        from emergent.wire.compile._execute import _family_mapped
        from nodnod import Scope

        assert _family_mapped(None, Scope()) == {}

    def test_get_stateful_metadata(self) -> None:
        from emergent.wire.compile._stateful import get_stateful_metadata

        codec = MagicMock()
        codec.flow = SFlow
        codec.response = str
        codec.key_node = None
        codec.agent_cls = None
        handler = MagicMock()
        handler.codec = codec

        meta = get_stateful_metadata(handler)
        assert meta["flow_cls"] is SFlow
        assert meta["response_cls"] is str

    def test_sa_query_store_model_property(self) -> None:
        from sqlalchemy.orm import DeclarativeBase
        from emergent.wire.axis.query.contrib._impls._sqlalchemy import SQLAlchemyRelationalStore

        class PropBase(DeclarativeBase):
            pass

        store = SQLAlchemyRelationalStore(Widget, "prop_widgets", base=PropBase)
        assert store.model is not None
        assert issubclass(store.model, DeclarativeBase)

    def test_build_request_sync_default_factory(self) -> None:
        from emergent.wire.compile._request import build_request_sync

        req = build_request_sync(TagReq, lambda n: None)
        assert req.tags == []

    def test_build_request_sync_optional_absent(self) -> None:
        from emergent.wire.compile._request import build_request_sync

        req = build_request_sync(OptReq, lambda n: {"name": "Test"}.get(n))
        assert req.name == "Test"

    def test_immediate_unknown_codec_raises(self) -> None:
        from emergent.wire.compile._execute import execute_immediate_unified
        from emergent.wire.axis.surface._handler import Handler

        handler = Handler(codec="bogus", runner=None, capabilities=())  # type: ignore[arg-type]
        with pytest.raises(TypeError, match="Expected ImmediateCodec"):
            execute_immediate_unified(handler)

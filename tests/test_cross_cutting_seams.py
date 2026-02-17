"""Cross-cutting seam tests — catch silent breakages at module boundaries.

Tests critical cross-module seams where a change in one module
can silently break another: schema→compile, compiler extensibility,
app capabilities, stateful lifecycle, graph fluent, fold edge cases.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Annotated, Self

import pytest

from kungfu import Result, Ok, Error

from nodnod import Scope, Node
from nodnod.utils.create_node import create_node

from pydantic.fields import FieldInfo as PydanticFieldInfo

from emergent.ops._graph import Op, Runner, ops
from emergent.wire.axis.schema import inspect_dataclass, FieldInfo
from emergent.wire.axis.schema._universal import (
    Min, Max, MaxLen, Pattern, Doc, OneOf, Alias,
)
from emergent.wire.axis._capability import (
    PydanticCompilable, PydanticContext,
    OpenAPICompilable, OpenAPIContext,
    ArgparseCompilable, ArgparseContext,
)
from emergent.wire.compile._core import (
    Axes, fold, fold_field, extract_constraints, extract_all_constraints,
)
from emergent.wire.compile._trace import ListCollector, FoldTrace
from emergent.wire.compile._target import TargetCompiler, CodecAdapter

from emergent.wire.axis.surface import endpoint, application, empty_runner
from emergent.wire.axis.surface._handler import Handler
from emergent.wire.axis.surface.codecs.rrc import RequestResponseCodec, rrc
from emergent.wire.axis.surface.codecs.delegate import delegate
from emergent.wire.axis.surface.enrichers import Inject
from emergent.wire.axis.surface.transforms import AsDict, Transform
from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger
from emergent.wire.compile._execute import ScopeInjector
from emergent.wire.compile.targets.testing import TestRoute, testing_compile as compile_for_test

from emergent.wire.axis.surface.codecs.stateful import (
    stateful, StatefulCodec, Done,
)
from emergent.wire.compile._stateful import (
    load_state, save_state, delete_state, execute_stateful_turn,
)
from emergent.wire.axis.storage import MemoryStorage

from emergent.graph._run import TypedScope, run, compose
from emergent.graph._compiled import graph


# ═══════════════════════════════════════════════════════════════════════════════
# Module-level domain types (required for get_type_hints resolution)
# ═══════════════════════════════════════════════════════════════════════════════


# --- Schema test types ---

@dataclass(frozen=True, slots=True)
class _MinMaxEntity:
    value: Annotated[int, Min(5), Max(100)]


@dataclass(frozen=True, slots=True)
class _DocEntity:
    name: Annotated[str, Doc("help text")]


@dataclass(frozen=True, slots=True)
class _OneOfEntity:
    choice: Annotated[str, OneOf("a", "b", "c")]


@dataclass(frozen=True, slots=True)
class _AliasEntity:
    field_name: Annotated[str, Alias("other")]


@dataclass(frozen=True, slots=True)
class _ConstraintEntity:
    code: Annotated[str, Min(1), MaxLen(50), Pattern(r"\d+")]


@dataclass(frozen=True, slots=True)
class _MultiFieldEntity:
    name: Annotated[str, MaxLen(100)]
    age: Annotated[int, Min(0), Max(200)]
    email: Annotated[str, Pattern(r".+@.+")]


# --- Pipeline test types ---

@dataclass(frozen=True, slots=True)
class _SeamOp(Op[str, str]):
    name: str


async def _seam_handler(req: _SeamOp) -> Result[str, str]:
    return Ok(f"Hello, {req.name}!")


@dataclass(frozen=True, slots=True)
class _SeamReq:
    name: str

    def to_domain(self) -> _SeamOp:
        return _SeamOp(name=self.name)


@dataclass(frozen=True, slots=True)
class _SeamResp:
    message: str

    @classmethod
    def from_domain(cls, dom: Result[str, str]) -> Self:
        match dom:
            case Ok(value):
                return cls(message=value)
            case Error(err):
                return cls(message=f"ERROR: {err}")


# --- Stateful test types ---

@dataclass
class _TestFlow:
    count: int = 0

    async def __transition__(self, **kwargs: object) -> Self | Done:
        if self.count >= 2:
            return Done()
        return replace(self, count=self.count + 1)

    def to_domain(self) -> _SeamOp:
        return _SeamOp(name="done")


@dataclass
class _FlowMissingTransition:
    def to_domain(self) -> _SeamOp:
        return _SeamOp(name="nope")


@dataclass
class _FlowMissingToDomain:
    async def __transition__(self) -> Self | Done:
        return Done()


@dataclass(frozen=True, slots=True)
class _TestFlowResp:
    msg: str

    @classmethod
    def from_domain(cls, dom: Result[str, str]) -> Self:
        match dom:
            case Ok(v):
                return cls(msg=v)
            case Error(e):
                return cls(msg=str(e))


class _KeyNode:
    pass


# --- Config type for enricher tests ---

@dataclass(frozen=True, slots=True)
class _AppConfig:
    name: str = "test_app"


@dataclass(frozen=True, slots=True)
class _CfgOp(Op[str, str]):
    pass


async def _cfg_handler(req: _CfgOp, config: _AppConfig) -> Result[str, str]:
    return Ok(config.name)


@dataclass(frozen=True, slots=True)
class _CfgReq:
    def to_domain(self) -> _CfgOp:
        return _CfgOp()


@dataclass(frozen=True, slots=True)
class _CfgResp:
    out: str

    @classmethod
    def from_domain(cls, dom: Result[str, str]) -> Self:
        match dom:
            case Ok(v):
                return cls(out=v)
            case Error(e):
                return cls(out=str(e))


# --- Graph test nodes ---

class _DepA:
    value: str = "a"


class _DepB:
    value: int = 42


class _Base:
    x: int = 1


class _Impl(_Base):
    x: int = 99


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _seam_runner() -> Runner:
    return ops().on(_SeamOp, _seam_handler).compile()


def _wrap_seam_resp(r: _SeamResp) -> _SeamResp:
    return _SeamResp(message=f"wrapped:{r.message}")


# ═══════════════════════════════════════════════════════════════════════════════
# 1. TestSchemaToCompileFoldContract
# ═══════════════════════════════════════════════════════════════════════════════


class TestSchemaToCompileFoldContract:
    """Seam: schema.inspect_dataclass → FieldInfo → fold_field → contexts."""

    def test_min_max_fold_to_pydantic(self) -> None:
        fields = inspect_dataclass(_MinMaxEntity)
        field = fields["value"]
        pyd_fi = PydanticFieldInfo(annotation=int)
        ctx = fold_field(
            field,
            PydanticContext(field_name="value", field_type=int, field_info=pyd_fi),
            PydanticCompilable,
            "compile_pydantic",
        )
        # Min(5) + Max(100) should add Ge and Le metadata
        metadata_types = [type(m).__name__ for m in ctx.field_info.metadata]
        assert "Ge" in metadata_types
        assert "Le" in metadata_types

    def test_min_max_fold_to_openapi(self) -> None:
        fields = inspect_dataclass(_MinMaxEntity)
        field = fields["value"]
        ctx = fold_field(
            field,
            OpenAPIContext(field_name="value", field_type=int),
            OpenAPICompilable,
            "compile_openapi",
        )
        assert ctx.schema["minimum"] == 5
        assert ctx.schema["maximum"] == 100

    def test_doc_fold_to_all_three(self) -> None:
        fields = inspect_dataclass(_DocEntity)
        field = fields["name"]

        # Pydantic
        pyd_fi = PydanticFieldInfo(annotation=str)
        pyd_ctx = fold_field(
            field,
            PydanticContext(field_name="name", field_type=str, field_info=pyd_fi),
            PydanticCompilable,
            "compile_pydantic",
        )
        assert pyd_ctx.field_info.description == "help text"

        # OpenAPI
        oapi_ctx = fold_field(
            field,
            OpenAPIContext(field_name="name", field_type=str),
            OpenAPICompilable,
            "compile_openapi",
        )
        assert oapi_ctx.schema["description"] == "help text"

        # Argparse
        arg_ctx = fold_field(
            field,
            ArgparseContext(field_name="name", field_type=str),
            ArgparseCompilable,
            "compile_argparse",
        )
        assert arg_ctx.kwargs["help"] == "help text"

    def test_oneof_fold_to_argparse(self) -> None:
        fields = inspect_dataclass(_OneOfEntity)
        field = fields["choice"]
        ctx = fold_field(
            field,
            ArgparseContext(field_name="choice", field_type=str),
            ArgparseCompilable,
            "compile_argparse",
        )
        assert ctx.kwargs["choices"] == ["a", "b", "c"]

    def test_alias_fold_to_pydantic_and_openapi(self) -> None:
        fields = inspect_dataclass(_AliasEntity)
        field = fields["field_name"]

        # Pydantic
        pyd_fi = PydanticFieldInfo(annotation=str)
        pyd_ctx = fold_field(
            field,
            PydanticContext(field_name="field_name", field_type=str, field_info=pyd_fi),
            PydanticCompilable,
            "compile_pydantic",
        )
        assert pyd_ctx.field_info.alias == "other"

        # OpenAPI
        oapi_ctx = fold_field(
            field,
            OpenAPIContext(field_name="field_name", field_type=str),
            OpenAPICompilable,
            "compile_openapi",
        )
        assert oapi_ctx.schema["x-alias"] == "other"

    def test_extract_constraints_roundtrip(self) -> None:
        fields = inspect_dataclass(_ConstraintEntity)
        field = fields["code"]
        constraints = extract_constraints(field)
        assert constraints.min_value == 1
        assert constraints.max_length == 50
        assert constraints.pattern == r"\d+"

    def test_extract_all_constraints_multiple_fields(self) -> None:
        axes = Axes.default()
        result = extract_all_constraints(_MultiFieldEntity, axes)
        assert len(result) == 3
        assert "name" in result
        assert "age" in result
        assert "email" in result
        _, name_c = result["name"]
        assert name_c.max_length == 100
        _, age_c = result["age"]
        assert age_c.min_value == 0
        assert age_c.max_value == 200
        _, email_c = result["email"]
        assert email_c.pattern == r".+@.+"

    def test_fold_field_skips_unknown_capability(self) -> None:
        """Custom capability not implementing protocol → silently skipped."""

        @dataclass(frozen=True, slots=True)
        class _Unknown:
            pass

        # Manually build a FieldInfo with an unknown item in capabilities
        field = FieldInfo(
            name="x",
            base_type=str,
            is_optional=False,
            capabilities=(_Unknown(),),  # type: ignore[arg-type]
        )
        ctx = fold_field(
            field,
            OpenAPIContext(field_name="x", field_type=str),
            OpenAPICompilable,
            "compile_openapi",
        )
        # Should return initial context unchanged
        assert ctx.schema == {}


# ═══════════════════════════════════════════════════════════════════════════════
# 2. TestTargetCompilerExtensibilityThroughExecution
# ═══════════════════════════════════════════════════════════════════════════════


class TestTargetCompilerExtensibilityThroughExecution:
    """Seam: TargetCompiler.with_codec/replace_codec/without_codec → execution."""

    @pytest.mark.asyncio
    async def test_with_codec_custom_adapter_executes(self) -> None:
        """Add custom codec type + wrap fn → compile → route callable."""

        @dataclass(frozen=True, slots=True)
        class _CustomCodec:
            value: str

        def wrap_custom(handler: Handler[_CustomCodec], trigger: object, axes: Axes) -> TestRoute:
            async def invoke(fields: Mapping[str, object], inject: ScopeInjector | None) -> str:
                return handler.codec.value

            return TestRoute(trigger=trigger, _invoke=invoke)

        runner = _seam_runner()
        app = application().mount(
            endpoint(runner).expose(
                HTTPRouteTrigger("GET", "/custom"),
                _CustomCodec(value="custom_result"),
            )
        )
        from emergent.wire.compile.targets.testing import TESTING_COMPILER
        custom_compiler = TESTING_COMPILER.with_codec(_CustomCodec, wrap_custom)
        test = compile_for_test(app, compiler=custom_compiler)
        # Find the custom route
        custom_routes = [r for r in test.routes if isinstance(r.trigger, HTTPRouteTrigger) and r.trigger.path == "/custom"]
        assert len(custom_routes) == 1
        result = await custom_routes[0].call()
        assert result == "custom_result"

    @pytest.mark.asyncio
    async def test_replace_codec_swaps_behavior(self) -> None:
        """Replace RRC adapter with one that wraps response."""
        from emergent.wire.compile._execute import execute_rrc_unified

        def _noop_inject(scope: Scope) -> None:
            pass

        def wrap_rrc_wrapper(handler: Handler[RequestResponseCodec], trigger: object, axes: Axes) -> TestRoute:
            async def invoke(fields: Mapping[str, object], inject: ScopeInjector | None) -> object:
                result = await execute_rrc_unified(
                    handler=handler,
                    axes=axes,
                    get_value=fields.get,
                    inject_scope=_noop_inject,
                )
                return {"wrapped": True, "data": result}

            return TestRoute(trigger=trigger, _invoke=invoke)

        runner = _seam_runner()
        app = application().mount(
            endpoint(runner).expose(
                HTTPRouteTrigger("POST", "/greet"),
                rrc(_SeamReq, _SeamResp),
            )
        )
        from emergent.wire.compile.targets.testing import TESTING_COMPILER
        custom = TESTING_COMPILER.replace_codec(RequestResponseCodec, wrap_rrc_wrapper)
        test = compile_for_test(app, compiler=custom)
        result = await test.routes[0].call({"name": "Alice"})
        assert isinstance(result, dict)
        assert result["wrapped"] is True

    def test_without_codec_removes_route(self) -> None:
        """Remove RRC adapter → RRC endpoint produces no route."""
        runner = _seam_runner()
        app = application().mount(
            endpoint(runner).expose(
                HTTPRouteTrigger("POST", "/greet"),
                rrc(_SeamReq, _SeamResp),
            )
        )
        from emergent.wire.compile.targets.testing import TESTING_COMPILER
        stripped = TESTING_COMPILER.without_codec(RequestResponseCodec)
        test = compile_for_test(app, compiler=stripped)
        # No RRC routes
        rrc_routes = [r for r in test.routes if isinstance(r.trigger, HTTPRouteTrigger) and r.trigger.path == "/greet"]
        assert len(rrc_routes) == 0

    def test_without_codec_other_codecs_unaffected(self) -> None:
        """Remove RRC → delegate endpoint still compiles."""
        runner = _seam_runner()
        app = application().mount(
            endpoint(runner).expose(
                HTTPRouteTrigger("POST", "/greet"),
                rrc(_SeamReq, _SeamResp),
            ),
            endpoint(empty_runner()).expose(
                HTTPRouteTrigger("GET", "/d"),
                delegate(lambda: "ok"),
            ),
        )
        from emergent.wire.compile.targets.testing import TESTING_COMPILER
        stripped = TESTING_COMPILER.without_codec(RequestResponseCodec)
        test = compile_for_test(app, compiler=stripped)
        delegate_routes = [r for r in test.routes if isinstance(r.trigger, HTTPRouteTrigger) and r.trigger.path == "/d"]
        assert len(delegate_routes) == 1

    def test_custom_compiler_passed_to_testing_compile(self) -> None:
        """testing_compile(app, compiler=custom) uses the custom compiler."""

        @dataclass(frozen=True, slots=True)
        class _MarkerCodec:
            pass

        call_count = [0]

        def wrap_marker(handler: Handler[_MarkerCodec], trigger: object, axes: Axes) -> TestRoute:
            call_count[0] += 1

            async def invoke(fields: Mapping[str, object], inject: ScopeInjector | None) -> str:
                return "marker"

            return TestRoute(trigger=trigger, _invoke=invoke)

        compiler: TargetCompiler[object] = TargetCompiler(
            trigger_type=object,
            adapters=(CodecAdapter(_MarkerCodec, wrap_marker),),
        )
        app = application().mount(
            endpoint(empty_runner()).expose(
                HTTPRouteTrigger("GET", "/m"),
                _MarkerCodec(),
            )
        )
        test = compile_for_test(app, compiler=compiler)
        assert call_count[0] == 1
        assert len(test.routes) == 1

    def test_codec_adapter_ordering_preserved(self) -> None:
        """2 custom codecs for same trigger → both produce routes."""

        @dataclass(frozen=True, slots=True)
        class _CodecA:
            pass

        @dataclass(frozen=True, slots=True)
        class _CodecB:
            pass

        def wrap_a(handler: Handler[_CodecA], trigger: object, axes: Axes) -> TestRoute:
            async def invoke(fields: Mapping[str, object], inject: ScopeInjector | None) -> str:
                return "a"
            return TestRoute(trigger=trigger, _invoke=invoke)

        def wrap_b(handler: Handler[_CodecB], trigger: object, axes: Axes) -> TestRoute:
            async def invoke(fields: Mapping[str, object], inject: ScopeInjector | None) -> str:
                return "b"
            return TestRoute(trigger=trigger, _invoke=invoke)

        compiler: TargetCompiler[object] = TargetCompiler(
            trigger_type=object,
            adapters=(CodecAdapter(_CodecA, wrap_a), CodecAdapter(_CodecB, wrap_b)),
        )

        app = application().mount(
            endpoint(empty_runner()).expose(
                HTTPRouteTrigger("GET", "/a"),
                _CodecA(),
            ),
            endpoint(empty_runner()).expose(
                HTTPRouteTrigger("GET", "/b"),
                _CodecB(),
            ),
        )
        test = compile_for_test(app, compiler=compiler)
        assert len(test.routes) == 2


# ═══════════════════════════════════════════════════════════════════════════════
# 3. TestAppCapabilitiesThroughCompile
# ═══════════════════════════════════════════════════════════════════════════════


class TestAppCapabilitiesThroughCompile:
    """Seam: exposure capabilities → Handler.capabilities → compile pipeline.

    Tests that capabilities set on endpoint.expose() propagate through
    scan → Handler → enrichers/transforms at runtime.
    """

    @pytest.mark.asyncio
    async def test_endpoint_transform_applied(self) -> None:
        """AsDict on endpoint → response converted to dict."""
        runner = _seam_runner()
        app = application().mount(
            endpoint(runner).expose(
                HTTPRouteTrigger("POST", "/greet"),
                rrc(_SeamReq, _SeamResp),
                AsDict(),
            )
        )
        test = compile_for_test(app)
        result = await test.routes[0].call({"name": "Alice"})
        assert isinstance(result, dict)
        assert result["message"] == "Hello, Alice!"

    @pytest.mark.asyncio
    async def test_endpoint_enricher_applied(self) -> None:
        """Inject on endpoint → handler scope has the injected value."""
        runner = ops().on(_CfgOp, _cfg_handler).compile()
        cfg = _AppConfig()
        app = application().mount(
            endpoint(runner).expose(
                HTTPRouteTrigger("GET", "/cfg"),
                rrc(_CfgReq, _CfgResp),
                Inject(type=_AppConfig, value=cfg),
            )
        )
        test = compile_for_test(app)
        result = await test.routes[0].call({})
        assert isinstance(result, _CfgResp)
        assert result.out == "test_app"

    @pytest.mark.asyncio
    async def test_multiple_caps_both_apply(self) -> None:
        """Endpoint has Transform + AsDict → both applied in order."""
        runner = _seam_runner()
        app = application().mount(
            endpoint(runner).expose(
                HTTPRouteTrigger("POST", "/greet"),
                rrc(_SeamReq, _SeamResp),
                Transform[_SeamResp, _SeamResp](fn=_wrap_seam_resp),
                AsDict(),
            )
        )
        test = compile_for_test(app)
        result = await test.routes[0].call({"name": "Test"})
        assert isinstance(result, dict)
        assert result["message"] == "wrapped:Hello, Test!"

    @pytest.mark.asyncio
    async def test_same_caps_on_multiple_endpoints(self) -> None:
        """2 endpoints with same capability → both routes affected."""
        runner = _seam_runner()
        app = application().mount(
            endpoint(runner).expose(
                HTTPRouteTrigger("POST", "/a"),
                rrc(_SeamReq, _SeamResp),
                AsDict(),
            ),
            endpoint(runner).expose(
                HTTPRouteTrigger("POST", "/b"),
                rrc(_SeamReq, _SeamResp),
                AsDict(),
            ),
        )
        test = compile_for_test(app)
        r1 = await test.routes[0].call({"name": "A"})
        r2 = await test.routes[1].call({"name": "B"})
        assert isinstance(r1, dict)
        assert isinstance(r2, dict)

    @pytest.mark.asyncio
    async def test_caps_on_one_endpoint_dont_leak(self) -> None:
        """Capabilities on one endpoint don't affect another endpoint."""
        runner = _seam_runner()
        app = application().mount(
            endpoint(runner).expose(
                HTTPRouteTrigger("POST", "/with"),
                rrc(_SeamReq, _SeamResp),
                AsDict(),  # This endpoint has AsDict
            ),
            endpoint(runner).expose(
                HTTPRouteTrigger("POST", "/without"),
                rrc(_SeamReq, _SeamResp),
                # No AsDict
            ),
        )
        test = compile_for_test(app)
        r1 = await test.routes[0].call({"name": "With"})
        r2 = await test.routes[1].call({"name": "Without"})
        assert isinstance(r1, dict)  # AsDict applied
        assert isinstance(r2, _SeamResp)  # No AsDict → raw dataclass


# ═══════════════════════════════════════════════════════════════════════════════
# 4. TestStatefulCodecLifecycle
# ═══════════════════════════════════════════════════════════════════════════════


class TestStatefulCodecLifecycle:
    """Seam: StatefulCodec → load_state/save_state/delete_state → execute_stateful_turn."""

    def test_stateful_builder_validates_missing_key(self) -> None:
        with pytest.raises(ValueError, match="key_node"):
            stateful(_TestFlow, _TestFlowResp).build()

    def test_stateful_builder_validates_missing_transitions(self) -> None:
        with pytest.raises(ValueError, match="__transition__"):
            stateful(_FlowMissingTransition, _TestFlowResp).key(_KeyNode).build()

    def test_stateful_builder_validates_missing_to_domain(self) -> None:
        with pytest.raises(ValueError, match="to_domain"):
            stateful(_FlowMissingToDomain, _TestFlowResp).key(_KeyNode).build()

    def test_stateful_builder_defaults(self) -> None:
        codec = stateful(_TestFlow, _TestFlowResp).key(_KeyNode).build()
        assert isinstance(codec, StatefulCodec)
        assert isinstance(codec.store, MemoryStorage)
        assert codec.flow is _TestFlow
        assert codec.response is _TestFlowResp

    @pytest.mark.asyncio
    async def test_load_state_initial(self) -> None:
        codec = stateful(_TestFlow, _TestFlowResp).key(_KeyNode).build()
        state = await load_state(codec, "test_key")
        assert isinstance(state, _TestFlow)
        assert state.count == 0

    @pytest.mark.asyncio
    async def test_load_save_load_roundtrip(self) -> None:
        codec = stateful(_TestFlow, _TestFlowResp).key(_KeyNode).build()
        key = "roundtrip_key"

        # Save some state
        new_state = _TestFlow(count=5)
        await save_state(codec, key, _TestFlow(), new_state)

        # Load it back
        loaded = await load_state(codec, key)
        assert isinstance(loaded, _TestFlow)
        assert loaded.count == 5

    @pytest.mark.asyncio
    async def test_delete_state_clears(self) -> None:
        codec = stateful(_TestFlow, _TestFlowResp).key(_KeyNode).build()
        key = "delete_key"

        # Save state
        await save_state(codec, key, _TestFlow(), _TestFlow(count=3))

        # Delete
        await delete_state(codec, key)

        # Load returns initial
        loaded = await load_state(codec, key)
        assert loaded.count == 0

    @pytest.mark.asyncio
    async def test_execute_turn_continue(self) -> None:
        """Transition returns Self → (new_state, None, False)."""
        codec = stateful(_TestFlow, _TestFlowResp).key(_KeyNode).build()
        handler_obj = _make_stateful_handler(codec)
        state = _TestFlow(count=0)

        # The transition method is __transition__
        method = _TestFlow.__transition__

        new_state, response, is_terminal = await execute_stateful_turn(
            handler_obj, state, method, {}
        )
        assert isinstance(new_state, _TestFlow)
        assert new_state.count == 1
        assert response is None
        assert is_terminal is False

    @pytest.mark.asyncio
    async def test_execute_turn_done(self) -> None:
        """Transition returns Done() → (Done(), None, True)."""
        codec = stateful(_TestFlow, _TestFlowResp).key(_KeyNode).build()
        handler_obj = _make_stateful_handler(codec)
        state = _TestFlow(count=2)  # >= 2 triggers Done

        method = _TestFlow.__transition__

        new_state, _response, is_terminal = await execute_stateful_turn(
            handler_obj, state, method, {}
        )
        assert isinstance(new_state, Done)
        assert is_terminal is True


def _make_stateful_handler(codec: StatefulCodec) -> Handler[StatefulCodec]:
    """Create a minimal Handler[StatefulCodec] for testing."""
    return Handler(codec=codec, runner=empty_runner())


# ═══════════════════════════════════════════════════════════════════════════════
# 5. TestGraphFluent
# ═══════════════════════════════════════════════════════════════════════════════


class TestGraphFluent:
    """Seam: TypedScope / Run / Compiled / compose — fluent graph API."""

    def test_typed_scope_inject_and_get(self) -> None:
        scope = TypedScope(detail="test")
        scope.inject(_DepA, _DepA())
        result = scope.get(_DepA)
        assert isinstance(result, _DepA)
        assert result.value == "a"

    def test_typed_scope_get_missing_raises(self) -> None:
        scope = TypedScope(detail="test")
        with pytest.raises(KeyError, match="_DepA"):
            scope.get(_DepA)

    def test_typed_scope_copy_independent(self) -> None:
        original = TypedScope(detail="test")
        original.inject(_DepA, _DepA())
        copied = original.copy()
        # Inject into copy only
        copied.inject(_DepB, _DepB())

        # Original should not have _DepB
        with pytest.raises(KeyError):
            original.get(_DepB)
        # Copy should have both
        assert copied.get(_DepA).value == "a"
        assert copied.get(_DepB).value == 42

    @pytest.mark.asyncio
    async def test_run_fluent_inject(self) -> None:
        TargetNode: type[Node[str, str]] = create_node(
            name="TargetNode",
            base_node=Node,
            bases=(),
            namespace={
                "__compose__": classmethod(lambda cls: "composed"),
                "__module__": __name__,
            },
        )
        result = await run(TargetNode).inject(_DepA())
        assert isinstance(result, str)
        assert result == "composed"

    @pytest.mark.asyncio
    async def test_run_fluent_given(self) -> None:
        GivenNode: type[Node[str, str]] = create_node(
            name="GivenNode",
            base_node=Node,
            bases=(),
            namespace={
                "__compose__": classmethod(lambda cls: "given_result"),
                "__module__": __name__,
            },
        )
        result = await run(GivenNode).given(_DepA(), _DepB())
        assert result == "given_result"

    @pytest.mark.asyncio
    async def test_compose_oneshot(self) -> None:
        OneShotNode: type[Node[str, str]] = create_node(
            name="OneShotNode",
            base_node=Node,
            bases=(),
            namespace={
                "__compose__": classmethod(lambda cls: "oneshot"),
                "__module__": __name__,
            },
        )
        result = await compose(OneShotNode, _DepA())
        assert result == "oneshot"

    @pytest.mark.asyncio
    async def test_compiled_graph_reuse(self) -> None:
        ReuseNode: type[Node[int, str]] = create_node(
            name="ReuseNode",
            base_node=Node,
            bases=(),
            namespace={
                "__compose__": classmethod(lambda cls: 99),
                "__module__": __name__,
            },
        )
        g = graph(ReuseNode)
        r1 = await g(_DepA())
        r2 = await g(_DepB())
        assert r1 == 99
        assert r2 == 99

    @pytest.mark.asyncio
    async def test_compiled_run_inject_as(self) -> None:
        InjectAsNode: type[Node[str, str]] = create_node(
            name="InjectAsNode",
            base_node=Node,
            bases=(),
            namespace={
                "__compose__": classmethod(lambda cls: "inject_as_result"),
                "__module__": __name__,
            },
        )
        g = graph(InjectAsNode)
        result = await g.run().inject_as(_Base, _Impl())
        assert result == "inject_as_result"


# ═══════════════════════════════════════════════════════════════════════════════
# 6. TestFoldEdgeCases
# ═══════════════════════════════════════════════════════════════════════════════


class TestFoldEdgeCases:
    """Seam: fold() is THE universal primitive. Edge cases here affect everything."""

    def test_fold_empty_items(self) -> None:
        initial = OpenAPIContext(field_name="x", field_type=str)
        result = fold([], initial, OpenAPICompilable, "compile_openapi")
        assert result is initial

    def test_fold_protocol_dispatch(self) -> None:
        """Item implements protocol → method called."""
        ctx = fold(
            [Min(10)],
            OpenAPIContext(field_name="x", field_type=int),
            OpenAPICompilable,
            "compile_openapi",
        )
        assert ctx.schema["minimum"] == 10

    def test_fold_handler_overrides_protocol(self) -> None:
        """Item in handlers dict → handler called, not protocol method."""

        def custom_handler(item: Min, ctx: OpenAPIContext) -> OpenAPIContext:
            return replace(ctx, schema={**ctx.schema, "custom_min": item.value})

        ctx = fold(
            [Min(7)],
            OpenAPIContext(field_name="x", field_type=int),
            OpenAPICompilable,
            "compile_openapi",
            handlers={Min: custom_handler},
        )
        assert ctx.schema.get("custom_min") == 7
        # Protocol method NOT called — no "minimum" key
        assert "minimum" not in ctx.schema

    def test_fold_unknown_item_skipped(self) -> None:
        """Item not in handlers, not protocol → silently skipped."""

        class _NotACapability:
            pass

        initial = OpenAPIContext(field_name="x", field_type=str)
        result = fold(
            [_NotACapability()],
            initial,
            OpenAPICompilable,
            "compile_openapi",
        )
        assert result is initial

    def test_fold_accumulates_across_items(self) -> None:
        """3 items each modify ctx → final ctx has all 3 changes."""
        ctx = fold(
            [Min(5), Max(100), Doc("help")],
            OpenAPIContext(field_name="x", field_type=int),
            OpenAPICompilable,
            "compile_openapi",
        )
        assert ctx.schema["minimum"] == 5
        assert ctx.schema["maximum"] == 100
        assert ctx.schema["description"] == "help"

    def test_traced_fold_records_steps(self) -> None:
        """traced_fold with ListCollector → FoldStep per item + FoldTrace."""
        from emergent.wire.compile._core import traced_fold

        collector = ListCollector()
        _ctx, trace = traced_fold(
            [Min(5), Max(100)],
            OpenAPIContext(field_name="x", field_type=int),
            OpenAPICompilable,
            "compile_openapi",
            None,
            collector,
        )
        assert isinstance(trace, FoldTrace)
        assert len(trace.steps) == 2
        assert trace.items_applied == 2
        assert trace.steps[0].item_type == "Min"
        assert trace.steps[1].item_type == "Max"
        assert trace.steps[0].dispatch == "protocol"
        # Collector also received events
        assert len(collector.fold_steps) == 2
        assert len(collector.fold_traces) == 1

    def test_fold_field_delegates_to_fold(self) -> None:
        """fold_field(FieldInfo) → same result as fold(field.capabilities, ...)."""
        fields = inspect_dataclass(_MinMaxEntity)
        field = fields["value"]

        initial = OpenAPIContext(field_name="value", field_type=int)

        via_fold_field = fold_field(
            field, initial, OpenAPICompilable, "compile_openapi"
        )
        via_fold = fold(
            field.capabilities, initial, OpenAPICompilable, "compile_openapi"
        )
        assert via_fold_field == via_fold

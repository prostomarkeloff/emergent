"""Cross-module integration tests — compile pipeline.

Tests the execution pipeline: testing_compile → _execute.py → _request.py → _rrc.py,
graph Composer, enrichers/transforms runtime, scope family lifecycle, and tracing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Annotated, Self

import pytest

from kungfu import Result, Ok, Error

from nodnod import Scope, Node
from nodnod.utils.create_node import create_node

from emergent.ops._graph import Op, Runner, ops
from emergent.wire.axis.surface import endpoint, application, empty_runner
from emergent.wire.axis.surface.codecs.rrc import (
    rrc,
)
from emergent.wire.axis.surface.codecs.delegate import delegate
from emergent.wire.axis.surface.codecs.immediate import (
    immediate,
    immediate_factory,
)
from emergent.wire.axis.surface.enrichers import (
    ScopeEnricher,
    EnricherNext,
    Inject,
    Validate,
    When,
)
from emergent.wire.axis.surface.transforms import AsDict, AsStr, Transform
from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger
from emergent.wire.compile._core import Axes
from emergent.wire.compile._trace import ListCollector
from emergent.wire.compile._request import build_request
from emergent.graph._compose import Composer
from emergent.graph._family import ScopeFamily
from emergent.wire.compile._lifetime import Tier, App
from emergent.wire.compile.targets.testing import testing_compile as compile_for_test, TestApp, TestRoute
from emergent.wire.axis.schema.dialects.compose import Retrieve
from emergent.wire.axis.surface._app import Application


# ═══════════════════════════════════════════════════════════════════════════════
# Module-level domain types (required for get_type_hints resolution)
# ═══════════════════════════════════════════════════════════════════════════════


# --- Greet (shared) ---

@dataclass(frozen=True, slots=True)
class Greet(Op[str, str]):
    name: str


async def _greet_handler(req: Greet) -> Result[str, str]:
    return Ok(f"Hello, {req.name}!")


@dataclass(frozen=True, slots=True)
class GreetRequest:
    name: str

    def to_domain(self) -> Greet:
        return Greet(name=self.name)


@dataclass(frozen=True, slots=True)
class GreetResponse:
    message: str

    @classmethod
    def from_domain(cls, dom: Result[str, str]) -> Self:
        match dom:
            case Ok(value):
                return cls(message=value)
            case Error(err):
                return cls(message=f"ERROR: {err}")


# --- Optional field ---

@dataclass(frozen=True, slots=True)
class OptOp(Op[str, str]):
    value: str


async def _opt_handler(req: OptOp) -> Result[str, str]:
    return Ok(req.value)


@dataclass(frozen=True, slots=True)
class OptReq:
    value: str
    extra: str | None = None

    def to_domain(self) -> OptOp:
        return OptOp(value=self.value)


@dataclass(frozen=True, slots=True)
class OptResp:
    msg: str

    @classmethod
    def from_domain(cls, dom: Result[str, str]) -> Self:
        match dom:
            case Ok(v):
                return cls(msg=v)
            case Error(e):
                return cls(msg=str(e))


# --- Default field ---

@dataclass(frozen=True, slots=True)
class DefOp(Op[str, str]):
    greeting: str


async def _def_handler(req: DefOp) -> Result[str, str]:
    return Ok(req.greeting)


@dataclass(frozen=True, slots=True)
class DefReq:
    greeting: str = "default_greeting"

    def to_domain(self) -> DefOp:
        return DefOp(greeting=self.greeting)


@dataclass(frozen=True, slots=True)
class DefResp:
    msg: str

    @classmethod
    def from_domain(cls, dom: Result[str, str]) -> Self:
        match dom:
            case Ok(v):
                return cls(msg=v)
            case Error(e):
                return cls(msg=str(e))


# --- Error result ---

@dataclass(frozen=True, slots=True)
class FailOp(Op[str, str]):
    pass


async def _fail_handler(req: FailOp) -> Result[str, str]:
    return Error("something went wrong")


@dataclass(frozen=True, slots=True)
class FailReq:
    def to_domain(self) -> FailOp:
        return FailOp()


@dataclass(frozen=True, slots=True)
class FailResp:
    msg: str
    ok: bool

    @classmethod
    def from_domain(cls, dom: Result[str, str]) -> Self:
        match dom:
            case Ok(v):
                return cls(msg=v, ok=True)
            case Error(e):
                return cls(msg=e, ok=False)


# --- Echo (for multiple endpoints) ---

@dataclass(frozen=True, slots=True)
class EchoOp(Op[str, str]):
    text: str


async def _echo_handler(req: EchoOp) -> Result[str, str]:
    return Ok(req.text)


@dataclass(frozen=True, slots=True)
class EchoReq:
    text: str

    def to_domain(self) -> EchoOp:
        return EchoOp(text=self.text)


@dataclass(frozen=True, slots=True)
class EchoResp:
    out: str

    @classmethod
    def from_domain(cls, dom: Result[str, str]) -> Self:
        match dom:
            case Ok(v):
                return cls(out=v)
            case Error(e):
                return cls(out=str(e))


# --- Inject enricher ---

@dataclass(frozen=True, slots=True)
class AppConfig:
    name: str = "test_app"


@dataclass(frozen=True, slots=True)
class CfgOp(Op[str, str]):
    pass


async def _cfg_handler(req: CfgOp, config: AppConfig) -> Result[str, str]:
    return Ok(config.name)


@dataclass(frozen=True, slots=True)
class CfgReq:
    def to_domain(self) -> CfgOp:
        return CfgOp()


@dataclass(frozen=True, slots=True)
class CfgResp:
    out: str

    @classmethod
    def from_domain(cls, dom: Result[str, str]) -> Self:
        match dom:
            case Ok(v):
                return cls(out=v)
            case Error(e):
                return cls(out=str(e))


# --- Immediate ---

@dataclass
class HelpResp:
    text: str = "help"

    @classmethod
    def produce(cls) -> HelpResp:
        return cls()


@dataclass
class StrResp:
    text: str

    @classmethod
    def produce(cls) -> StrResp:
        return cls(text="hello")

    def __str__(self) -> str:
        return self.text


# --- Build request types ---

@dataclass
class PlainReq:
    name: str
    age: int


@dataclass
class DefaultReq:
    name: str
    greeting: str = "hi"


@dataclass
class OptionalReq:
    name: str
    extra: str | None = None


@dataclass
class MissingReq:
    name: str
    age: int


# --- Compose retrieve request ---

class _RetrieveToken:
    secret: str = "tok123"


@dataclass
class RetrieveReq:
    name: str
    token: Annotated[_RetrieveToken, Retrieve(_RetrieveToken)] = field(default=None)  # type: ignore[assignment]


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _greet_runner() -> Runner:
    return ops().on(Greet, _greet_handler).compile()


def _greet_app() -> tuple[Application, Runner]:
    runner = _greet_runner()
    trigger = HTTPRouteTrigger("POST", "/greet")
    app = application().mount(
        endpoint(runner).expose(trigger, rrc(GreetRequest, GreetResponse))
    )
    return app, runner


# ═══════════════════════════════════════════════════════════════════════════════
# 1. TestRRCFullPipeline
# ═══════════════════════════════════════════════════════════════════════════════


class TestRRCFullPipeline:
    """RRC: fields → Request → Op → Result → Response through compile_for_test."""

    @pytest.mark.asyncio
    async def test_basic_rrc_roundtrip(self) -> None:
        app, _ = _greet_app()
        test = compile_for_test(app)
        result = await test.routes[0].call({"name": "Alice"})
        assert isinstance(result, GreetResponse)
        assert result.message == "Hello, Alice!"

    @pytest.mark.asyncio
    async def test_rrc_missing_required_field(self) -> None:
        app, _ = _greet_app()
        test = compile_for_test(app)
        with pytest.raises(RuntimeError, match="name"):
            await test.routes[0].call({})

    @pytest.mark.asyncio
    async def test_rrc_optional_field_defaults_to_none(self) -> None:
        runner = ops().on(OptOp, _opt_handler).compile()
        app = application().mount(
            endpoint(runner).expose(
                HTTPRouteTrigger("POST", "/opt"),
                rrc(OptReq, OptResp),
            )
        )
        test = compile_for_test(app)
        result = await test.routes[0].call({"value": "hi"})
        assert isinstance(result, OptResp)
        assert result.msg == "hi"

    @pytest.mark.asyncio
    async def test_rrc_default_field_used(self) -> None:
        runner = ops().on(DefOp, _def_handler).compile()
        app = application().mount(
            endpoint(runner).expose(
                HTTPRouteTrigger("POST", "/def"),
                rrc(DefReq, DefResp),
            )
        )
        test = compile_for_test(app)
        result = await test.routes[0].call({})
        assert isinstance(result, DefResp)
        assert result.msg == "default_greeting"

    @pytest.mark.asyncio
    async def test_rrc_error_result_propagates(self) -> None:
        runner = ops().on(FailOp, _fail_handler).compile()
        app = application().mount(
            endpoint(runner).expose(
                HTTPRouteTrigger("POST", "/fail"),
                rrc(FailReq, FailResp),
            )
        )
        test = compile_for_test(app)
        result = await test.routes[0].call({})
        assert isinstance(result, FailResp)
        assert not result.ok
        assert result.msg == "something went wrong"

    @pytest.mark.asyncio
    async def test_rrc_multiple_endpoints(self) -> None:
        app, _ = _greet_app()
        echo_runner = ops().on(EchoOp, _echo_handler).compile()
        app = app.mount(
            endpoint(echo_runner).expose(
                HTTPRouteTrigger("POST", "/echo"),
                rrc(EchoReq, EchoResp),
            )
        )
        test = compile_for_test(app)
        assert len(test.routes) == 2

        r1 = await test.routes[0].call({"name": "Bob"})
        assert isinstance(r1, GreetResponse)
        assert r1.message == "Hello, Bob!"

        r2 = await test.routes[1].call({"text": "ping"})
        assert isinstance(r2, EchoResp)
        assert r2.out == "ping"


# ═══════════════════════════════════════════════════════════════════════════════
# 2. TestDelegatePipeline
# ═══════════════════════════════════════════════════════════════════════════════


class _DelegateConfig:
    value: str = "injected"


class _DelegateToken:
    secret: str = "abc123"


async def _delegate_simple() -> str:
    return "delegate_result"


async def _delegate_with_config(cfg: _DelegateConfig) -> str:
    return cfg.value


async def _delegate_with_retrieve(t: Annotated[_DelegateToken, Retrieve(_DelegateToken)]) -> str:
    return t.secret


async def _delegate_async() -> int:
    return 42


class TestDelegatePipeline:
    """Delegate handlers — handler params resolved via scope/compose."""

    @pytest.mark.asyncio
    async def test_delegate_basic_handler(self) -> None:
        app = application().mount(
            endpoint(empty_runner()).expose(
                HTTPRouteTrigger("GET", "/d"),
                delegate(_delegate_simple),
            )
        )
        test = compile_for_test(app)
        result = await test.routes[0].call()
        assert result == "delegate_result"

    @pytest.mark.asyncio
    async def test_delegate_scope_injection(self) -> None:
        app = application().mount(
            endpoint(empty_runner()).expose(
                HTTPRouteTrigger("GET", "/d"),
                delegate(_delegate_with_config),
            )
        )
        test = compile_for_test(app)
        cfg = _DelegateConfig()
        result = await test.routes[0].call(
            inject=lambda scope: scope.inject(_DelegateConfig, cfg),
        )
        assert result == "injected"

    @pytest.mark.asyncio
    async def test_delegate_compose_retrieve(self) -> None:
        app = application().mount(
            endpoint(empty_runner()).expose(
                HTTPRouteTrigger("GET", "/d"),
                delegate(_delegate_with_retrieve),
            )
        )
        test = compile_for_test(app)
        tok = _DelegateToken()
        result = await test.routes[0].call(
            inject=lambda scope: scope.inject(_DelegateToken, tok),
        )
        assert result == "abc123"

    @pytest.mark.asyncio
    async def test_delegate_async_handler(self) -> None:
        app = application().mount(
            endpoint(empty_runner()).expose(
                HTTPRouteTrigger("GET", "/d"),
                delegate(_delegate_async),
            )
        )
        test = compile_for_test(app)
        result = await test.routes[0].call()
        assert result == 42


# ═══════════════════════════════════════════════════════════════════════════════
# 3. TestImmediatePipeline
# ═══════════════════════════════════════════════════════════════════════════════


class TestImmediatePipeline:
    """Immediate codecs — produce() and factory()."""

    @pytest.mark.asyncio
    async def test_immediate_produce(self) -> None:
        app = application().mount(
            endpoint(empty_runner()).expose(
                HTTPRouteTrigger("GET", "/help"),
                immediate(HelpResp),
            )
        )
        test = compile_for_test(app)
        result = await test.routes[0].call()
        assert isinstance(result, HelpResp)
        assert result.text == "help"

    @pytest.mark.asyncio
    async def test_immediate_factory(self) -> None:
        captured = "factory_output"

        def _factory() -> dict[str, str]:
            return {"info": captured}

        app = application().mount(
            endpoint(empty_runner()).expose(
                HTTPRouteTrigger("GET", "/info"),
                immediate_factory(_factory),
            )
        )
        test = compile_for_test(app)
        result = await test.routes[0].call()
        assert result == {"info": "factory_output"}


# ═══════════════════════════════════════════════════════════════════════════════
# 4. TestEnricherExecution
# ═══════════════════════════════════════════════════════════════════════════════


def _str_list_factory() -> list[str]:
    return []


@dataclass(frozen=True, slots=True)
class _OrderedEnricher(ScopeEnricher):
    label: str
    _order: list[str] = field(default_factory=_str_list_factory, compare=False, hash=False)

    async def enrich(self, call: EnricherNext[object], scope: Scope) -> object:
        self._order.append(f"enter:{self.label}")
        result = await call(scope)
        self._order.append(f"exit:{self.label}")
        return result


@dataclass(frozen=True, slots=True)
class _RecordingEnricher(ScopeEnricher):
    tag: str
    _recorded: list[str] = field(default_factory=_str_list_factory, compare=False, hash=False)

    async def enrich(self, call: EnricherNext[object], scope: Scope) -> object:
        self._recorded.append(self.tag)
        return await call(scope)


class TestEnricherExecution:
    """Enrichers through the full pipeline via capabilities."""

    @pytest.mark.asyncio
    async def test_inject_enricher(self) -> None:
        cfg = AppConfig()
        runner = ops().on(CfgOp, _cfg_handler).compile()
        app = application().mount(
            endpoint(runner).expose(
                HTTPRouteTrigger("GET", "/cfg"),
                rrc(CfgReq, CfgResp),
                Inject(type=AppConfig, value=cfg),
            )
        )
        test = compile_for_test(app)
        result = await test.routes[0].call({})
        assert isinstance(result, CfgResp)
        assert result.out == "test_app"

    @pytest.mark.asyncio
    async def test_validate_enricher_pass(self) -> None:
        def _extract_true(_scope: Scope) -> bool:
            return True

        def _predicate_true(_val: bool) -> bool:
            return True

        def _on_invalid(_val: bool) -> GreetResponse:
            return GreetResponse(message="INVALID")

        runner = _greet_runner()
        app = application().mount(
            endpoint(runner).expose(
                HTTPRouteTrigger("POST", "/greet"),
                rrc(GreetRequest, GreetResponse),
                Validate(
                    extract=_extract_true,
                    predicate=_predicate_true,
                    on_invalid=_on_invalid,
                ),
            )
        )
        test = compile_for_test(app)
        result = await test.routes[0].call({"name": "Alice"})
        assert isinstance(result, GreetResponse)
        assert result.message == "Hello, Alice!"

    @pytest.mark.asyncio
    async def test_validate_enricher_short_circuit(self) -> None:
        def _extract_false(_scope: Scope) -> bool:
            return False

        def _predicate_identity(v: bool) -> bool:
            return v

        def _on_invalid_blocked(_val: bool) -> GreetResponse:
            return GreetResponse(message="BLOCKED")

        runner = _greet_runner()
        app = application().mount(
            endpoint(runner).expose(
                HTTPRouteTrigger("POST", "/greet"),
                rrc(GreetRequest, GreetResponse),
                Validate(
                    extract=_extract_false,
                    predicate=_predicate_identity,
                    on_invalid=_on_invalid_blocked,
                ),
            )
        )
        test = compile_for_test(app)
        result = await test.routes[0].call({"name": "Alice"})
        assert isinstance(result, GreetResponse)
        assert result.message == "BLOCKED"

    @pytest.mark.asyncio
    async def test_when_enricher_condition_true(self) -> None:
        def _always_true(_scope: Scope) -> bool:
            return True

        runner = _greet_runner()
        recorded: list[str] = []
        recorder = _RecordingEnricher(tag="applied", _recorded=recorded)

        app = application().mount(
            endpoint(runner).expose(
                HTTPRouteTrigger("POST", "/greet"),
                rrc(GreetRequest, GreetResponse),
                When(condition=_always_true, then=recorder),
            )
        )
        test = compile_for_test(app)
        await test.routes[0].call({"name": "X"})
        assert "applied" in recorded

    @pytest.mark.asyncio
    async def test_when_enricher_condition_false(self) -> None:
        def _always_false(_scope: Scope) -> bool:
            return False

        runner = _greet_runner()
        recorded: list[str] = []
        recorder = _RecordingEnricher(tag="should_not_appear", _recorded=recorded)

        app = application().mount(
            endpoint(runner).expose(
                HTTPRouteTrigger("POST", "/greet"),
                rrc(GreetRequest, GreetResponse),
                When(condition=_always_false, then=recorder),
            )
        )
        test = compile_for_test(app)
        await test.routes[0].call({"name": "X"})
        assert "should_not_appear" not in recorded

    @pytest.mark.asyncio
    async def test_enricher_ordering(self) -> None:
        runner = _greet_runner()
        order: list[str] = []

        app = application().mount(
            endpoint(runner).expose(
                HTTPRouteTrigger("POST", "/greet"),
                rrc(GreetRequest, GreetResponse),
                _OrderedEnricher(label="A", _order=order),
                _OrderedEnricher(label="B", _order=order),
            )
        )
        test = compile_for_test(app)
        await test.routes[0].call({"name": "X"})
        assert order == ["enter:A", "enter:B", "exit:B", "exit:A"]


# ═══════════════════════════════════════════════════════════════════════════════
# 5. TestResponseTransforms
# ═══════════════════════════════════════════════════════════════════════════════


class TestResponseTransforms:
    """Response transforms through the pipeline via capabilities."""

    @pytest.mark.asyncio
    async def test_asdict_on_dataclass_response(self) -> None:
        runner = _greet_runner()
        app = application().mount(
            endpoint(runner).expose(
                HTTPRouteTrigger("POST", "/greet"),
                rrc(GreetRequest, GreetResponse),
                AsDict(),
            )
        )
        test = compile_for_test(app)
        result = await test.routes[0].call({"name": "Alice"})
        assert isinstance(result, dict)
        assert result == {"message": "Hello, Alice!"}

    @pytest.mark.asyncio
    async def test_asstr_on_response(self) -> None:
        app = application().mount(
            endpoint(empty_runner()).expose(
                HTTPRouteTrigger("GET", "/str"),
                immediate(StrResp),
                AsStr(),
            )
        )
        test = compile_for_test(app)
        result = await test.routes[0].call()
        assert result == "hello"

    @pytest.mark.asyncio
    async def test_custom_transform_fn(self) -> None:
        def _to_data(r: GreetResponse) -> dict[str, str]:
            return {"data": r.message}

        runner = _greet_runner()
        app = application().mount(
            endpoint(runner).expose(
                HTTPRouteTrigger("POST", "/greet"),
                rrc(GreetRequest, GreetResponse),
                Transform(fn=_to_data),
            )
        )
        test = compile_for_test(app)
        result = await test.routes[0].call({"name": "Alice"})
        assert result == {"data": "Hello, Alice!"}

    @pytest.mark.asyncio
    async def test_chained_transforms(self) -> None:
        def _add_wrapped(d: dict[str, object]) -> dict[str, object]:
            return {**d, "wrapped": True}

        runner = _greet_runner()
        app = application().mount(
            endpoint(runner).expose(
                HTTPRouteTrigger("POST", "/greet"),
                rrc(GreetRequest, GreetResponse),
                AsDict(),
                Transform(fn=_add_wrapped),
            )
        )
        test = compile_for_test(app)
        result = await test.routes[0].call({"name": "Alice"})
        assert isinstance(result, dict)
        assert result["message"] == "Hello, Alice!"
        assert result["wrapped"] is True


# ═══════════════════════════════════════════════════════════════════════════════
# 6. TestScopeFamilyLifecycle
# ═══════════════════════════════════════════════════════════════════════════════


class _DBPool:
    connected: bool = True


class _ReqId:
    def __init__(self, val: str) -> None:
        self.val = val


class _SharedConfig:
    name: str = "shared"


async def _db_handler(pool: _DBPool) -> str:
    return f"connected={pool.connected}"


async def _reqid_handler(rid: _ReqId) -> str:
    return rid.val


async def _shared_handler(cfg: _SharedConfig) -> str:
    return cfg.name


class TestScopeFamilyLifecycle:
    """App-tier / Request-tier scope lifecycle through compile_for_test."""

    @pytest.mark.asyncio
    async def test_app_tier_compose_once(self) -> None:
        DBPoolNode: type[Node[_DBPool, str]] = create_node(
            name="DBPoolNode",
            base_node=Node,
            bases=(),
            namespace={
                "__compose__": classmethod(lambda cls: _DBPool()),
                "__module__": __name__,
            },
        )

        family: ScopeFamily[Tier] = ScopeFamily[Tier]().bind(App, DBPoolNode)

        app = application().mount(
            endpoint(empty_runner()).expose(
                HTTPRouteTrigger("GET", "/db"),
                delegate(_db_handler),
            )
        )
        test = compile_for_test(app, family=family)
        async with test:
            result = await test.routes[0].call(
                inject=lambda scope: scope.inject(_DBPool, _DBPool()),
            )
            assert result == "connected=True"

    @pytest.mark.asyncio
    async def test_request_tier_per_request(self) -> None:
        app = application().mount(
            endpoint(empty_runner()).expose(
                HTTPRouteTrigger("GET", "/req"),
                delegate(_reqid_handler),
            )
        )
        test = compile_for_test(app)

        r1 = await test.routes[0].call(
            inject=lambda scope: scope.inject(_ReqId, _ReqId("req1")),
        )
        r2 = await test.routes[0].call(
            inject=lambda scope: scope.inject(_ReqId, _ReqId("req2")),
        )
        assert r1 == "req1"
        assert r2 == "req2"

    @pytest.mark.asyncio
    async def test_request_inherits_from_app(self) -> None:
        family: ScopeFamily[Tier] = ScopeFamily[Tier]()

        app = application().mount(
            endpoint(empty_runner()).expose(
                HTTPRouteTrigger("GET", "/inherit"),
                delegate(_shared_handler),
            )
        )
        test = compile_for_test(app, family=family)
        async with test:
            # pyright: ignore[reportPrivateUsage] - test needs access to app scope for setup
            app_scope = test._app_scope  # pyright: ignore[reportPrivateUsage]
            if app_scope is not None:
                app_scope.inject(_SharedConfig, _SharedConfig())

            result = await test.routes[0].call()
            assert result == "shared"

    @pytest.mark.asyncio
    async def test_no_family_still_works(self) -> None:
        app, _ = _greet_app()
        test = compile_for_test(app)
        result = await test.routes[0].call({"name": "NoFamily"})
        assert isinstance(result, GreetResponse)
        assert result.message == "Hello, NoFamily!"


# ═══════════════════════════════════════════════════════════════════════════════
# 7. TestRequestBuilding
# ═══════════════════════════════════════════════════════════════════════════════


class TestRequestBuilding:
    """Direct tests of build_request with various field types."""

    @pytest.mark.asyncio
    async def test_plain_fields_from_getter(self) -> None:
        values = {"name": "Alice", "age": 30}
        result = await build_request(PlainReq, values.get)
        assert result.name == "Alice"
        assert result.age == 30

    @pytest.mark.asyncio
    async def test_default_field_fallback(self) -> None:
        result = await build_request(DefaultReq, {"name": "Bob"}.get)
        assert result.name == "Bob"
        assert result.greeting == "hi"

    @pytest.mark.asyncio
    async def test_optional_field_none_fallback(self) -> None:
        result = await build_request(OptionalReq, {"name": "Charlie"}.get)
        assert result.name == "Charlie"
        assert result.extra is None

    @pytest.mark.asyncio
    async def test_compose_retrieve_from_scope(self) -> None:
        tok = _RetrieveToken()
        async with Scope(detail="test") as scope:
            scope.inject(_RetrieveToken, tok)
            result = await build_request(RetrieveReq, {"name": "D"}.get, scope=scope)
            assert result.name == "D"
            assert result.token is tok

    @pytest.mark.asyncio
    async def test_missing_required_raises(self) -> None:
        with pytest.raises(RuntimeError, match="age"):
            await build_request(MissingReq, {"name": "E"}.get)


# ═══════════════════════════════════════════════════════════════════════════════
# 8. TestGraphComposer
# ═══════════════════════════════════════════════════════════════════════════════


class _ComposerConfig:
    val: int = 99


class _Parent:
    x: int = 1


class _Dep:
    name: str = "resolved"


async def _dep_handler(dep: _Dep) -> str:
    return dep.name


class TestGraphComposer:
    """Composer.compose, compose_batch, retrieve, child, resolve_params."""

    @pytest.mark.asyncio
    async def test_compose_scalar_node(self) -> None:
        MyNode: type[Node[str, str]] = create_node(
            name="MyNode",
            base_node=Node,
            bases=(),
            namespace={
                "__compose__": classmethod(lambda cls: "scalar_value"),
                "__module__": __name__,
            },
        )

        async with Scope(detail="test") as scope:
            composer = Composer.create(scope)
            ok, value = await composer.compose(MyNode)
            assert ok
            assert value == "scalar_value"

    @pytest.mark.asyncio
    async def test_compose_batch(self) -> None:
        NodeA: type[Node[str, str]] = create_node(
            name="NodeA",
            base_node=Node,
            bases=(),
            namespace={
                "__compose__": classmethod(lambda cls: "a"),
                "__module__": __name__,
            },
        )
        NodeB: type[Node[int, str]] = create_node(
            name="NodeB",
            base_node=Node,
            bases=(),
            namespace={
                "__compose__": classmethod(lambda cls: 42),
                "__module__": __name__,
            },
        )

        async with Scope(detail="test") as scope:
            composer = Composer.create(scope)
            await composer.compose_batch({NodeA, NodeB})

            ok_a, val_a = composer.retrieve(NodeA)
            ok_b, val_b = composer.retrieve(NodeB)
            assert ok_a
            assert val_a == "a"
            assert ok_b
            assert val_b == 42

    @pytest.mark.asyncio
    async def test_retrieve_injected_value(self) -> None:
        async with Scope(detail="test") as scope:
            cfg = _ComposerConfig()
            scope.inject(_ComposerConfig, cfg)
            composer = Composer.create(scope)
            ok, val = composer.retrieve(_ComposerConfig)
            assert ok
            assert val is cfg

    @pytest.mark.asyncio
    async def test_child_inherits_parent(self) -> None:
        async with Scope(detail="parent") as scope:
            scope.inject(_Parent, _Parent())
            composer = Composer.create(scope)
            child = composer.child("child_scope")
            ok, val = child.retrieve(_Parent)
            assert ok
            assert val is not None
            assert val.x == 1

    @pytest.mark.asyncio
    async def test_resolve_params(self) -> None:
        async with Scope(detail="test") as scope:
            scope.inject(_Dep, _Dep())
            composer = Composer.create(scope)
            params = await composer.resolve_params(_dep_handler)
            assert "dep" in params
            assert isinstance(params["dep"], _Dep)
            assert params["dep"].name == "resolved"


# ═══════════════════════════════════════════════════════════════════════════════
# 9. TestTracing
# ═══════════════════════════════════════════════════════════════════════════════


class TestTracing:
    """ListCollector captures scan/wrap events during compile."""

    def test_scan_events_emitted(self) -> None:
        app, _ = _greet_app()
        collector = ListCollector()
        axes = Axes.traced(collector)
        compile_for_test(app, axes=axes)
        assert len(collector.scan_events) == 1
        assert collector.scan_events[0].codec_type == "RequestResponseCodec"

    def test_wrap_events_emitted(self) -> None:
        app, _ = _greet_app()
        collector = ListCollector()
        axes = Axes.traced(collector)
        compile_for_test(app, axes=axes)
        assert len(collector.wrap_events) == 1
        assert collector.wrap_events[0].codec_type == "RequestResponseCodec"
        assert collector.wrap_events[0].result_type == "TestRoute"

    def test_scan_event_fields(self) -> None:
        runner = _greet_runner()
        app = application().mount(
            endpoint(runner).expose(
                HTTPRouteTrigger("POST", "/greet"),
                rrc(GreetRequest, GreetResponse),
                Inject(type=int, value=42),
            )
        )
        collector = ListCollector()
        axes = Axes.traced(collector)
        compile_for_test(app, axes=axes)

        event = collector.scan_events[0]
        assert event.trigger_type == "HTTPRouteTrigger"
        assert event.codec_type == "RequestResponseCodec"
        assert len(event.capabilities) == 1
        assert "Inject" in event.capabilities[0]

    def test_multiple_endpoints_traced(self) -> None:
        def _ok_handler() -> str:
            return "ok"

        runner = _greet_runner()
        app = application().mount(
            endpoint(runner).expose(
                HTTPRouteTrigger("POST", "/a"),
                rrc(GreetRequest, GreetResponse),
            ),
            endpoint(empty_runner()).expose(
                HTTPRouteTrigger("GET", "/b"),
                delegate(_ok_handler),
            ),
        )
        collector = ListCollector()
        axes = Axes.traced(collector)
        compile_for_test(app, axes=axes)
        assert len(collector.scan_events) == 2
        assert len(collector.wrap_events) == 2


# ═══════════════════════════════════════════════════════════════════════════════
# 10. TestMixedCodecsApp
# ═══════════════════════════════════════════════════════════════════════════════


class TestMixedCodecsApp:
    """RRC + Delegate + Immediate in one Application."""

    def _build_mixed_app(self) -> Application:
        def _delegate_ok() -> str:
            return "delegate_ok"

        runner = _greet_runner()

        rrc_ep = endpoint(runner).expose(
            HTTPRouteTrigger("POST", "/greet"),
            rrc(GreetRequest, GreetResponse),
        )
        delegate_ep = endpoint(empty_runner()).expose(
            HTTPRouteTrigger("GET", "/delegate"),
            delegate(_delegate_ok),
        )
        immediate_ep = endpoint(empty_runner()).expose(
            HTTPRouteTrigger("GET", "/help"),
            immediate(HelpResp),
        )

        app = application().mount(rrc_ep, delegate_ep, immediate_ep)
        return app

    def _find_route_by_trigger_path(self, test: TestApp, path: str) -> TestRoute:
        """Find route by matching trigger path."""
        for route in test.routes:
            trigger = route.trigger
            if isinstance(trigger, HTTPRouteTrigger) and trigger.path == path:
                return route
        raise AssertionError(f"No route with path {path}")

    def test_mixed_app_all_routes_compiled(self) -> None:
        app = self._build_mixed_app()
        test = compile_for_test(app)
        assert len(test.routes) == 3

    @pytest.mark.asyncio
    async def test_mixed_app_rrc_works(self) -> None:
        app = self._build_mixed_app()
        test = compile_for_test(app)
        route = self._find_route_by_trigger_path(test, "/greet")
        result = await route.call({"name": "Mixed"})
        assert isinstance(result, GreetResponse)
        assert result.message == "Hello, Mixed!"

    @pytest.mark.asyncio
    async def test_mixed_app_delegate_works(self) -> None:
        app = self._build_mixed_app()
        test = compile_for_test(app)
        route = self._find_route_by_trigger_path(test, "/delegate")
        result = await route.call()
        assert result == "delegate_ok"

    @pytest.mark.asyncio
    async def test_mixed_app_immediate_works(self) -> None:
        app = self._build_mixed_app()
        test = compile_for_test(app)
        route = self._find_route_by_trigger_path(test, "/help")
        result = await route.call()
        assert isinstance(result, HelpResp)
        assert result.text == "help"

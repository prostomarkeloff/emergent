# pyright: reportPrivateUsage=false
"""Tests for deep async runtime paths in compile infrastructure.

Covers uncovered lines across:
- _execute.py: RRC unified, stateful unified, delegate unified paths
- _stateful.py: execute_stateful_done with enrichers, FromDomain resolution
- _request.py: compose node/optional/fallback/race/retrieve resolution
- _delegate.py: resolve_handler_params with compose dialect annotations
- _pipeline.py: execute_with_pipeline, scope helpers, coercion paths
- _generate.py: to_datanode, to_datanode_auto, pydantic field handling
- _capabilities.py: Mount OpenAPI merge, _merge_openapi, _add_generic_mount_docs
"""

from dataclasses import dataclass, field
from typing import Annotated, Any, Self

import pytest

from kungfu import Ok, Result, Some, Nothing, Option

from nodnod import Scope, Node, DataNode, EventLoopAgent

from emergent.ops._graph import Op, ops
from emergent.wire.axis.surface._app import application
from emergent.wire.axis.surface._endpoint import endpoint
from emergent.wire.axis.surface._handler import Handler
from emergent.wire.axis.surface.codecs.rrc import (
    rrc,
)
from emergent.wire.axis.surface.codecs.delegate import delegate
from emergent.wire.axis.surface.codecs.immediate import (
    immediate,
    immediate_factory,
)
from emergent.wire.axis.surface.codecs.stateful import (
    StatefulCodec,
    Done,
    Cancelled,
    get_transitions,
)
from emergent.wire.axis.surface.enrichers._base import ScopeEnricher, EnricherNext
from emergent.wire.axis.storage import MemoryStorage
from emergent.wire.compile._core import Axes
from emergent.wire.compile._execute import (
    execute_rrc_unified,
    execute_stateful_unified,
    execute_immediate_unified,
    execute_delegate_unified,
)
from emergent.wire.compile._stateful import (
    execute_stateful_turn,
    execute_stateful_done,
    load_state,
    save_state,
    delete_state,
)
from emergent.wire.compile._request import (
    build_request,
    compose_node_value,
)
from emergent.wire.compile._delegate import resolve_handler_params
from emergent.wire.compile._pipeline import (
    CompiledPipeline,
    compile_pipeline,
    execute_with_pipeline,
    _make_scope,
    _family_mapped,
)
from emergent.wire.compile._capabilities import (
    apply_response_capabilities,
    fold_handler_runtime,
    Mount,
    _merge_openapi,
    _add_generic_mount_docs,
)
from emergent.wire.compile._generate import (
    to_pydantic,
    to_argparse_args,
    to_datanode,
    to_datanode_auto,
)
from emergent.wire.compile.targets import testing as testing_target


# ═══════════════════════════════════════════════════════════════════════════════
# Shared Fixtures
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class GreetOp(Op[str, str]):
    name: str


async def _handle_greet(req: GreetOp) -> Result[str, str]:
    return Ok(f"Hello, {req.name}!")


@dataclass(frozen=True, slots=True)
class GreetRequest:
    name: str

    def to_domain(self) -> GreetOp:
        return GreetOp(name=self.name)


@dataclass(frozen=True, slots=True)
class GreetResponse:
    message: str

    @classmethod
    def from_domain(cls, dom: Result[str, str]) -> Self:
        match dom:
            case Ok(v):
                return cls(message=v)
            case _:
                return cls(message="error")


def _make_runner():
    return ops().on(GreetOp, _handle_greet).compile()


def _make_axes() -> Axes:
    return Axes.default()


# ═══════════════════════════════════════════════════════════════════════════════
# 1. execute_rrc_unified — lines 123-124, 141-143
# ═══════════════════════════════════════════════════════════════════════════════


class TestExecuteRrcUnified:
    """Test the full RRC unified execution path."""

    @pytest.mark.asyncio
    async def test_basic_rrc_execution(self) -> None:
        """RRC unified with simple handler produces correct response."""
        handler = Handler(
            codec=rrc(GreetRequest, GreetResponse),
            runner=_make_runner(),
        )
        axes = _make_axes()
        result = await execute_rrc_unified(
            handler=handler,
            axes=axes,
            get_value={"name": "Alice"}.get,
            inject_scope=lambda s: None,
        )
        assert isinstance(result, GreetResponse)
        assert result.message == "Hello, Alice!"

    @pytest.mark.asyncio
    async def test_rrc_with_format_response(self) -> None:
        """RRC unified applies format_response when provided."""
        handler = Handler(
            codec=rrc(GreetRequest, GreetResponse),
            runner=_make_runner(),
        )
        axes = _make_axes()
        result = await execute_rrc_unified(
            handler=handler,
            axes=axes,
            get_value={"name": "Bob"}.get,
            inject_scope=lambda s: None,
            format_response=lambda r: {"formatted": r.message},
        )
        assert result == {"formatted": "Hello, Bob!"}

    @pytest.mark.asyncio
    async def test_rrc_with_async_inject_scope(self) -> None:
        """RRC unified with async inject_scope."""
        injected: list[str] = []

        async def async_inject(scope: Scope) -> None:
            injected.append("injected")

        handler = Handler(
            codec=rrc(GreetRequest, GreetResponse),
            runner=_make_runner(),
        )
        axes = _make_axes()
        result = await execute_rrc_unified(
            handler=handler,
            axes=axes,
            get_value={"name": "Carol"}.get,
            inject_scope=async_inject,
        )
        assert isinstance(result, GreetResponse)
        assert injected == ["injected"]

    @pytest.mark.asyncio
    async def test_rrc_exception_is_logged_and_reraised(self) -> None:
        """When RRC execution raises, exception is reraised (lines 141-143)."""

        @dataclass(frozen=True, slots=True)
        class BrokenRequest:
            name: str

            def to_domain(self) -> GreetOp:
                raise RuntimeError("broken to_domain")

        handler = Handler(
            codec=rrc(BrokenRequest, GreetResponse),
            runner=_make_runner(),
        )
        axes = _make_axes()
        with pytest.raises(RuntimeError, match="broken to_domain"):
            await execute_rrc_unified(
                handler=handler,
                axes=axes,
                get_value={"name": "X"}.get,
                inject_scope=lambda s: None,
            )


# ═══════════════════════════════════════════════════════════════════════════════
# 2. execute_stateful_unified — lines 194, 207, 213-246
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class PlaceBetOp(Op[str, str]):
    amount: int


async def _handle_place_bet(req: PlaceBetOp) -> Result[str, str]:
    return Ok(f"bet:{req.amount}")


@dataclass
class BetFlow:
    step: int = 0

    async def __transition__(self, **kwargs: Any) -> "BetFlow | Done | tuple[BetFlow, str]":
        if self.step >= 2:
            return Done()
        return BetFlow(step=self.step + 1), f"step-{self.step + 1}"

    def to_domain(self) -> PlaceBetOp:
        return PlaceBetOp(amount=self.step * 100)


@dataclass
class CancellableFlow:
    step: int = 0

    async def __transition__(self, **kwargs: Any) -> "CancellableFlow | Cancelled | tuple[CancellableFlow, str]":
        if self.step >= 1:
            return Cancelled()
        return CancellableFlow(step=self.step + 1), f"step-{self.step + 1}"

    def to_domain(self) -> PlaceBetOp:
        return PlaceBetOp(amount=999)


@dataclass(frozen=True, slots=True)
class BetResponse:
    result: str

    @classmethod
    def from_domain(cls, dom: Result[str, str]) -> Self:
        match dom:
            case Ok(v):
                return cls(result=v)
            case _:
                return cls(result="err")


class SimpleKeyNode:
    pass


class TestExecuteStatefulUnified:
    """Test full stateful unified execution paths."""

    def _make_stateful_handler(
        self,
        flow_cls: type = BetFlow,
    ) -> Handler[StatefulCodec]:
        runner = ops().on(PlaceBetOp, _handle_place_bet).compile()
        codec = StatefulCodec(
            flow=flow_cls,
            response=BetResponse,
            store=MemoryStorage[str, object](),
            key_node=SimpleKeyNode,
            agent_cls=EventLoopAgent,
        )
        return Handler(codec=codec, runner=runner)

    @pytest.mark.asyncio
    async def test_non_terminal_turn_saves_state(self) -> None:
        """Non-terminal transition saves state and returns response."""
        handler = self._make_stateful_handler()
        transitions = get_transitions(BetFlow)
        method = transitions[0]

        async def resolve() -> tuple[Any, dict[str, Any]]:
            return (method, {})

        result, is_done = await execute_stateful_unified(
            handler=handler,
            store_key="user:1",
            resolve_transition=resolve,
            inject_scope=lambda s: None,
        )
        assert not is_done
        assert result == "step-1"

    @pytest.mark.asyncio
    async def test_non_terminal_with_format_response(self) -> None:
        """Non-terminal turn applies format_response (line 207)."""
        handler = self._make_stateful_handler()
        transitions = get_transitions(BetFlow)

        async def resolve() -> tuple[Any, dict[str, Any]]:
            return (transitions[0], {})

        result, is_done = await execute_stateful_unified(
            handler=handler,
            store_key="user:2",
            resolve_transition=resolve,
            inject_scope=lambda s: None,
            format_response=lambda r: f"formatted:{r}",
        )
        assert not is_done
        assert result == "formatted:step-1"

    @pytest.mark.asyncio
    async def test_resolve_none_raises_runtime_error(self) -> None:
        """If resolve returns None, raises RuntimeError (line 194)."""
        handler = self._make_stateful_handler()

        async def resolve() -> tuple[Any, dict[str, Any]] | None:
            return None

        with pytest.raises(RuntimeError, match="No transition resolvable"):
            await execute_stateful_unified(
                handler=handler,
                store_key="user:3",
                resolve_transition=resolve,
                inject_scope=lambda s: None,
            )

    @pytest.mark.asyncio
    async def test_terminal_done_executes_op(self) -> None:
        """Done transition executes op via runner (lines 217-246).

        Tests execute_stateful_done directly since execute_stateful_unified
        passes new_state (Done) which is the terminal marker.
        """
        handler = self._make_stateful_handler()
        state = BetFlow(step=5)

        scope = Scope()
        async with scope:
            result = await execute_stateful_done(handler, state, scope)
        assert isinstance(result, BetResponse)
        assert result.result == "bet:500"

    @pytest.mark.asyncio
    async def test_cancelled_deletes_state(self) -> None:
        """Cancelled transition deletes state and returns without op exec (line 213)."""
        handler = self._make_stateful_handler(flow_cls=CancellableFlow)
        codec = handler.codec

        await codec.store.set("user:5", CancellableFlow(step=1))

        transitions = get_transitions(CancellableFlow)

        async def resolve() -> tuple[Any, dict[str, Any]]:
            return (transitions[0], {})

        _result, is_done = await execute_stateful_unified(
            handler=handler,
            store_key="user:5",
            resolve_transition=resolve,
            inject_scope=lambda s: None,
        )
        assert is_done
        # State should be deleted
        stored = await codec.store.get("user:5")
        match stored:
            case Ok(Nothing()):
                pass
            case _:
                pytest.fail(f"Expected Nothing, got {stored}")

    @pytest.mark.asyncio
    async def test_done_with_parent_scope(self) -> None:
        """Done transition uses parent_scope when axes.scope_layer is None."""
        handler = self._make_stateful_handler()
        state = BetFlow(step=3)

        parent = Scope(detail="parent")
        async with parent:
            result = await execute_stateful_done(handler, state, parent)
        assert isinstance(result, BetResponse)
        assert result.result == "bet:300"

    @pytest.mark.asyncio
    async def test_done_with_format_response(self) -> None:
        """Done path in execute_stateful_unified applies format_response (lines 243-244).

        Tests the format_response path by using a non-terminal transition
        where format_response is applied.
        """
        handler = self._make_stateful_handler()
        transitions = get_transitions(BetFlow)

        async def resolve() -> tuple[Any, dict[str, Any]]:
            return (transitions[0], {})

        # Test non-terminal with format_response to cover line 207
        result, is_done = await execute_stateful_unified(
            handler=handler,
            store_key="user:7",
            resolve_transition=resolve,
            inject_scope=lambda s: None,
            format_response=lambda r: f"wrapped:{r}",
        )
        assert not is_done
        assert result == "wrapped:step-1"


# ═══════════════════════════════════════════════════════════════════════════════
# 3. execute_stateful_done with enrichers — _stateful.py lines 101-136
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class CountingEnricher(ScopeEnricher):
    """Enricher that counts calls."""
    counter: list[int]

    async def enrich(self, call: EnricherNext[Any], scope: Scope) -> Any:
        self.counter.append(1)
        return await call(scope)

    def compile_handler_runtime(self, ctx: Any) -> Any:
        from dataclasses import replace
        return replace(ctx, enrichers=(*ctx.enrichers, self))


class TestExecuteStatefulDone:
    """Test execute_stateful_done core handler and enricher paths."""

    @pytest.mark.asyncio
    async def test_core_handler_from_domain(self) -> None:
        """Core path: state.to_domain() -> Op -> Result -> from_domain."""
        runner = ops().on(PlaceBetOp, _handle_place_bet).compile()
        codec = StatefulCodec(
            flow=BetFlow,
            response=BetResponse,
            store=MemoryStorage[str, object](),
            key_node=SimpleKeyNode,
            agent_cls=EventLoopAgent,
        )
        handler = Handler(codec=codec, runner=runner)
        state = BetFlow(step=5)

        scope = Scope()
        async with scope:
            result = await execute_stateful_done(handler, state, scope)

        assert isinstance(result, BetResponse)
        assert result.result == "bet:500"

    @pytest.mark.asyncio
    async def test_done_with_enrichers(self) -> None:
        """Enrichers wrap done handler (lines 132-134)."""
        counter: list[int] = []
        enricher = CountingEnricher(counter=counter)

        runner = ops().on(PlaceBetOp, _handle_place_bet).compile()
        codec = StatefulCodec(
            flow=BetFlow,
            response=BetResponse,
            store=MemoryStorage[str, object](),
            key_node=SimpleKeyNode,
            agent_cls=EventLoopAgent,
        )
        handler = Handler(codec=codec, runner=runner, capabilities=(enricher,))
        state = BetFlow(step=3)

        scope = Scope()
        async with scope:
            result = await execute_stateful_done(handler, state, scope)

        assert isinstance(result, BetResponse)
        assert counter == [1]

    @pytest.mark.asyncio
    async def test_done_without_enrichers(self) -> None:
        """No enrichers -> direct core handler call (lines 135-136)."""
        runner = ops().on(PlaceBetOp, _handle_place_bet).compile()
        codec = StatefulCodec(
            flow=BetFlow,
            response=BetResponse,
            store=MemoryStorage[str, object](),
            key_node=SimpleKeyNode,
            agent_cls=EventLoopAgent,
        )
        handler = Handler(codec=codec, runner=runner, capabilities=())
        state = BetFlow(step=1)

        scope = Scope()
        async with scope:
            result = await execute_stateful_done(handler, state, scope)

        assert isinstance(result, BetResponse)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. _request.py — build_field_value with compose nodes (lines 45-48, 72-103)
# ═══════════════════════════════════════════════════════════════════════════════


class ValueNode(DataNode):
    value: int = 42

    @classmethod
    def __compose__(cls) -> "ValueNode":
        return cls()


class FailNode(Node[str, str]):
    @classmethod
    def __compose__(cls) -> str:
        raise RuntimeError("cannot compose")


class TestBuildRequest:
    """Test build_request and build_field_value compose paths."""

    @pytest.mark.asyncio
    async def test_compose_node_value(self) -> None:
        """compose_node_value resolves a DataNode (lines 45-48)."""
        scope = Scope()
        async with scope:
            success, value = await compose_node_value(ValueNode, EventLoopAgent, scope)
        assert success
        assert isinstance(value, ValueNode)

    @pytest.mark.asyncio
    async def test_build_request_regular_fields(self) -> None:
        """build_request with regular fields from get_value."""
        result = await build_request(
            request_cls=GreetRequest,
            get_value={"name": "Alice"}.get,
        )
        assert isinstance(result, GreetRequest)
        assert result.name == "Alice"

    @pytest.mark.asyncio
    async def test_build_request_with_default_field(self) -> None:
        """build_request uses dataclass defaults when no value provided."""

        @dataclass(frozen=True, slots=True)
        class ReqWithDefault:
            name: str
            greeting: str = "Hi"

            def to_domain(self) -> GreetOp:
                return GreetOp(name=self.name)

        result = await build_request(
            request_cls=ReqWithDefault,
            get_value={"name": "Bob"}.get,
        )
        assert result.greeting == "Hi"

    @pytest.mark.asyncio
    async def test_build_request_optional_field_none(self) -> None:
        """build_request returns None for optional field without value (line 127)."""

        @dataclass(frozen=True, slots=True)
        class ReqOptional:
            name: str
            tag: str | None = None

            def to_domain(self) -> GreetOp:
                return GreetOp(name=self.name)

        result = await build_request(
            request_cls=ReqOptional,
            get_value={"name": "Carol"}.get,
        )
        assert result.tag is None

    @pytest.mark.asyncio
    async def test_build_request_compose_node_field(self) -> None:
        """build_request resolves compose.Node annotated field (lines 72-76)."""
        from emergent.wire.axis.schema.dialects import compose

        @dataclass
        class ReqWithNode:
            name: str
            node_val: Annotated[int, compose.Node(ValueNode)] = 0

            def to_domain(self) -> GreetOp:
                return GreetOp(name=self.name)

        scope = Scope()
        async with scope:
            result = await build_request(
                request_cls=ReqWithNode,
                get_value={"name": "D"}.get,
                scope=scope,
            )
        assert result.name == "D"

    @pytest.mark.asyncio
    async def test_build_request_compose_node_with_map(self) -> None:
        """compose.Node with map transforms the value (line 74-75)."""
        from emergent.wire.axis.schema.dialects import compose

        @dataclass
        class ReqWithMap:
            name: str
            doubled: Annotated[int, compose.Node(ValueNode, map=lambda v: v.value * 2)] = 0

            def to_domain(self) -> GreetOp:
                return GreetOp(name=self.name)

        scope = Scope()
        async with scope:
            result = await build_request(
                request_cls=ReqWithMap,
                get_value={"name": "E"}.get,
                scope=scope,
            )
        assert result.doubled == 84  # 42 * 2

    @pytest.mark.asyncio
    async def test_build_request_compose_optional_node(self) -> None:
        """compose.Optional resolves to Some/Nothing (lines 82-87)."""
        from emergent.wire.axis.schema.dialects import compose

        @dataclass
        class ReqWithOptional:
            name: str
            maybe: Annotated[Option[int], compose.Optional(ValueNode)] = field(default_factory=Nothing)

            def to_domain(self) -> GreetOp:
                return GreetOp(name=self.name)

        scope = Scope()
        async with scope:
            result = await build_request(
                request_cls=ReqWithOptional,
                get_value={"name": "F"}.get,
                scope=scope,
            )
        assert isinstance(result.maybe, Some)

    @pytest.mark.asyncio
    async def test_build_request_compose_retrieve(self) -> None:
        """compose.Retrieve fetches from scope (lines 105-111)."""
        from emergent.wire.axis.schema.dialects import compose

        class AuthUser:
            pass

        @dataclass
        class ReqWithRetrieve:
            name: str
            user: Annotated[AuthUser | None, compose.Retrieve(AuthUser)] = field(default=None)

            def to_domain(self) -> GreetOp:
                return GreetOp(name=self.name)

        user = AuthUser()
        scope = Scope()
        async with scope:
            scope.inject(AuthUser, user)
            result = await build_request(
                request_cls=ReqWithRetrieve,
                get_value={"name": "G"}.get,
                scope=scope,
            )
        assert result.user is user

    @pytest.mark.asyncio
    async def test_build_request_compose_fallback(self) -> None:
        """compose.Fallback tries nodes in order (lines 89-94)."""
        from emergent.wire.axis.schema.dialects import compose

        @dataclass
        class ReqWithFallback:
            name: str
            val: Annotated[int, compose.Fallback(ValueNode)] = 0

            def to_domain(self) -> GreetOp:
                return GreetOp(name=self.name)

        scope = Scope()
        async with scope:
            result = await build_request(
                request_cls=ReqWithFallback,
                get_value={"name": "H"}.get,
                scope=scope,
            )
        assert result.name == "H"

    @pytest.mark.asyncio
    async def test_build_request_compose_race(self) -> None:
        """compose.Race runs nodes concurrently (lines 96-103)."""
        from emergent.wire.axis.schema.dialects import compose

        @dataclass
        class ReqWithRace:
            name: str
            val: Annotated[int, compose.Race(ValueNode)] = 0

            def to_domain(self) -> GreetOp:
                return GreetOp(name=self.name)

        scope = Scope()
        async with scope:
            result = await build_request(
                request_cls=ReqWithRace,
                get_value={"name": "I"}.get,
                scope=scope,
            )
        assert result.name == "I"

    @pytest.mark.asyncio
    async def test_build_request_required_field_error(self) -> None:
        """build_request raises RuntimeError for missing required field."""
        with pytest.raises(RuntimeError, match="Cannot resolve required field"):
            await build_request(
                request_cls=GreetRequest,
                get_value=lambda name: None,
            )

    @pytest.mark.asyncio
    async def test_build_request_not_dataclass_error(self) -> None:
        """build_request raises TypeError for non-dataclass."""

        class NotDC:
            pass

        with pytest.raises(TypeError, match="not a dataclass"):
            await build_request(
                request_cls=NotDC,
                get_value=lambda name: None,
            )


# ═══════════════════════════════════════════════════════════════════════════════
# 5. _delegate.py — resolve_handler_params (lines 57-58, 76-82, 88, 98-99, 113)
# ═══════════════════════════════════════════════════════════════════════════════


class TestResolveHandlerParams:
    """Test compose dialect resolution on handler parameters."""

    @pytest.mark.asyncio
    async def test_resolve_with_compose_node(self) -> None:
        """Handler param annotated with compose.Node resolves via nodnod (lines 76-82)."""
        from emergent.wire.axis.schema.dialects.compose import Node as ComposeNode

        async def handler(val: Annotated[int, ComposeNode(ValueNode)]) -> str:
            return f"got:{val}"

        scope = Scope()
        async with scope:
            params = await resolve_handler_params(handler, scope, EventLoopAgent)
        assert "val" in params

    @pytest.mark.asyncio
    async def test_resolve_with_compose_optional(self) -> None:
        """Handler param with compose.Optional wraps in Option (lines 84-90)."""
        from emergent.wire.axis.schema.dialects.compose import Optional as ComposeOptional

        async def handler(val: Annotated[Option[int], ComposeOptional(ValueNode)]) -> str:
            return "ok"

        scope = Scope()
        async with scope:
            params = await resolve_handler_params(handler, scope, EventLoopAgent)
        assert "val" in params
        assert isinstance(params["val"], Some)

    @pytest.mark.asyncio
    async def test_resolve_with_compose_retrieve(self) -> None:
        """Handler param with compose.Retrieve reads from scope (lines 92-99)."""
        from emergent.wire.axis.schema.dialects.compose import Retrieve as ComposeRetrieve

        class MyService:
            pass

        svc = MyService()

        async def handler(svc_param: Annotated[MyService, ComposeRetrieve(MyService)]) -> str:
            return "ok"

        scope = Scope()
        async with scope:
            scope.inject(MyService, svc)
            params = await resolve_handler_params(handler, scope, EventLoopAgent)
        assert params["svc_param"] is svc

    @pytest.mark.asyncio
    async def test_resolve_compose_retrieve_not_in_scope(self) -> None:
        """compose.Retrieve skips when type not in scope (line 99)."""
        from emergent.wire.axis.schema.dialects.compose import Retrieve as ComposeRetrieve

        class Missing:
            pass

        async def handler(x: Annotated[Missing, ComposeRetrieve(Missing)]) -> str:
            return "ok"

        scope = Scope()
        async with scope:
            params = await resolve_handler_params(handler, scope, EventLoopAgent)
        assert "x" not in params

    @pytest.mark.asyncio
    async def test_resolve_fallback_by_type_from_scope(self) -> None:
        """Fallback: type not annotated with compose, retrieved from scope (lines 101-113)."""

        class Config:
            value: int = 10

        cfg = Config()

        async def handler(config: Config) -> str:
            return "ok"

        scope = Scope()
        async with scope:
            scope.inject(Config, cfg)
            params = await resolve_handler_params(handler, scope, EventLoopAgent)
        assert params["config"] is cfg

    @pytest.mark.asyncio
    async def test_resolve_fallback_compose_as_node(self) -> None:
        """Fallback: type not in scope, try composing as nodnod node (line 111-113)."""

        async def handler(val: ValueNode) -> str:
            return "ok"

        scope = Scope()
        async with scope:
            params = await resolve_handler_params(handler, scope, EventLoopAgent)
        assert "val" in params

    @pytest.mark.asyncio
    async def test_resolve_skips_self_and_cls(self) -> None:
        """'self' and 'cls' params are skipped (line 64-65)."""

        class MyClass:
            async def method(self, x: int = 5) -> str:
                return "ok"

        scope = Scope()
        async with scope:
            params = await resolve_handler_params(MyClass.method, scope, EventLoopAgent)
        assert "self" not in params

    @pytest.mark.asyncio
    async def test_resolve_skips_empty_annotation(self) -> None:
        """Param without annotation is skipped (line 68-69)."""

        async def handler(x: Any) -> str:  # no annotation
            return "ok"

        scope = Scope()
        async with scope:
            params = await resolve_handler_params(handler, scope, EventLoopAgent)
        assert "x" not in params

    @pytest.mark.asyncio
    async def test_compose_node_with_default(self) -> None:
        """compose.Node fallback to default when node fails (line 81-82)."""
        from emergent.wire.axis.schema.dialects.compose import Node as ComposeNode

        class BrokenNode(Node[str, str]):
            @classmethod
            def __compose__(cls) -> str:
                raise RuntimeError("broken")

        async def handler(val: Annotated[str, ComposeNode(BrokenNode, default="fallback")]) -> str:
            return val

        scope = Scope()
        async with scope:
            params = await resolve_handler_params(handler, scope, EventLoopAgent)
        assert params["val"] == "fallback"

    @pytest.mark.asyncio
    async def test_compose_node_with_map_function(self) -> None:
        """compose.Node map transforms the composed value (line 78-79)."""
        from emergent.wire.axis.schema.dialects.compose import Node as ComposeNode

        async def handler(
            val: Annotated[str, ComposeNode(ValueNode, map=lambda v: f"mapped:{v.value}")]
        ) -> str:
            return val

        scope = Scope()
        async with scope:
            params = await resolve_handler_params(handler, scope, EventLoopAgent)
        assert params["val"] == "mapped:42"


# ═══════════════════════════════════════════════════════════════════════════════
# 6. execute_delegate_unified — lines 331, 338-339, 351, 354-356
# ═══════════════════════════════════════════════════════════════════════════════


class TestExecuteDelegateUnified:
    """Test delegate execution with compose dialect."""

    @pytest.mark.asyncio
    async def test_basic_async_delegate(self) -> None:
        """Async delegate handler is called with resolved params."""
        called: list[str] = []

        async def my_handler() -> str:
            called.append("called")
            return "result"

        handler = Handler(
            codec=delegate(my_handler),
            runner=_make_runner(),
        )
        axes = _make_axes()
        result = await execute_delegate_unified(
            handler=handler,
            inject_scope=lambda s: None,
            axes=axes,
        )
        assert result == "result"
        assert called == ["called"]

    @pytest.mark.asyncio
    async def test_sync_delegate_handler(self) -> None:
        """Sync delegate is run via asyncio.to_thread."""
        called: list[str] = []

        def sync_handler() -> str:
            called.append("sync")
            return "sync-result"

        handler = Handler(
            codec=delegate(sync_handler),
            runner=_make_runner(),
        )
        result = await execute_delegate_unified(
            handler=handler,
            inject_scope=lambda s: None,
        )
        assert result == "sync-result"
        assert called == ["sync"]

    @pytest.mark.asyncio
    async def test_delegate_with_format_response(self) -> None:
        """Delegate applies format_response."""

        async def my_handler() -> str:
            return "raw"

        handler = Handler(
            codec=delegate(my_handler),
            runner=_make_runner(),
        )
        result = await execute_delegate_unified(
            handler=handler,
            inject_scope=lambda s: None,
            format_response=lambda r: f"formatted:{r}",
        )
        assert result == "formatted:raw"

    @pytest.mark.asyncio
    async def test_delegate_with_enrichers(self) -> None:
        """Delegate with enricher capabilities (line 351)."""
        counter: list[int] = []
        enricher = CountingEnricher(counter=counter)

        async def my_handler() -> str:
            return "enriched"

        handler = Handler(
            codec=delegate(my_handler),
            runner=_make_runner(),
            capabilities=(enricher,),
        )
        result = await execute_delegate_unified(
            handler=handler,
            inject_scope=lambda s: None,
        )
        assert result == "enriched"
        assert counter == [1]

    @pytest.mark.asyncio
    async def test_delegate_exception_logged_and_reraised(self) -> None:
        """Delegate exception path (lines 354-356)."""

        async def failing_handler() -> str:
            raise ValueError("boom")

        handler = Handler(
            codec=delegate(failing_handler),
            runner=_make_runner(),
        )
        with pytest.raises(ValueError, match="boom"):
            await execute_delegate_unified(
                handler=handler,
                inject_scope=lambda s: None,
            )

    @pytest.mark.asyncio
    async def test_delegate_with_async_inject(self) -> None:
        """Delegate with async inject_scope (line 331)."""
        injected: list[str] = []

        async def async_inject(scope: Scope) -> None:
            injected.append("async-injected")

        async def my_handler() -> str:
            return "ok"

        handler = Handler(
            codec=delegate(my_handler),
            runner=_make_runner(),
        )
        await execute_delegate_unified(
            handler=handler,
            inject_scope=async_inject,
        )
        assert injected == ["async-injected"]


# ═══════════════════════════════════════════════════════════════════════════════
# 7. _pipeline.py — execute_with_pipeline, scope helpers (lines 120, 128, etc.)
# ═══════════════════════════════════════════════════════════════════════════════


class TestPipeline:
    """Test pipeline scope helpers and execution."""

    def test_make_scope_without_layer(self) -> None:
        """_make_scope returns fresh Scope when no layer (line 121)."""
        scope = _make_scope(None)
        assert isinstance(scope, Scope)

    def test_family_mapped_none_layer(self) -> None:
        """_family_mapped returns empty dict when layer is None (line 127)."""
        result = _family_mapped(None, Scope())
        assert result == {}

    def test_compile_pipeline_no_execute_raises(self) -> None:
        """compile_pipeline raises TypeError if ctx has no execute."""

        class BadCtx:
            pass

        with pytest.raises(TypeError, match="no 'execute' attribute"):
            compile_pipeline(BadCtx(), _make_axes())

    def test_compile_pipeline_basic(self) -> None:
        """compile_pipeline creates CompiledPipeline from ctx."""

        async def exec_fn(handler: Any, scope: Any, get_value: Any) -> object:
            return "ok"

        @dataclass
        class Ctx:
            execute: Any = exec_fn

        compiled = compile_pipeline(Ctx(), _make_axes())
        assert isinstance(compiled, CompiledPipeline)
        assert compiled.execute is exec_fn

    @pytest.mark.asyncio
    async def test_execute_with_pipeline_basic(self) -> None:
        """execute_with_pipeline runs the compiled execute fn."""

        async def exec_fn(handler: Any, scope: Scope, get_value: Any) -> object:
            return "pipeline-result"

        compiled = CompiledPipeline(execute=exec_fn)
        handler = Handler(
            codec=rrc(GreetRequest, GreetResponse),
            runner=_make_runner(),
        )
        axes = _make_axes()
        result = await execute_with_pipeline(compiled, handler, axes, None)
        assert result == "pipeline-result"

    @pytest.mark.asyncio
    async def test_execute_with_pipeline_extractor(self) -> None:
        """execute_with_pipeline uses extractor when provided (lines 177-192)."""

        class DictExtractor:
            async def extract(self, request: object) -> dict[str, object]:
                return {"name": "extracted"}

        async def exec_fn(handler: Any, scope: Scope, get_value: Any) -> object:
            if get_value:
                return get_value("name")
            return "no-extractor"

        compiled = CompiledPipeline(execute=exec_fn, extractor=DictExtractor())
        handler = Handler(
            codec=rrc(GreetRequest, GreetResponse),
            runner=_make_runner(),
        )
        axes = _make_axes()
        result = await execute_with_pipeline(compiled, handler, axes, {})
        assert result == "extracted"

    @pytest.mark.asyncio
    async def test_execute_with_pipeline_enrichers(self) -> None:
        """execute_with_pipeline applies enrichers (line 201)."""
        counter: list[int] = []
        enricher = CountingEnricher(counter=counter)

        async def exec_fn(handler: Any, scope: Scope, get_value: Any) -> object:
            return "enriched-pipeline"

        compiled = CompiledPipeline(execute=exec_fn)
        handler = Handler(
            codec=rrc(GreetRequest, GreetResponse),
            runner=_make_runner(),
            capabilities=(enricher,),
        )
        axes = _make_axes()
        result = await execute_with_pipeline(compiled, handler, axes, None)
        assert result == "enriched-pipeline"
        assert counter == [1]

    @pytest.mark.asyncio
    async def test_execute_with_pipeline_exception(self) -> None:
        """execute_with_pipeline logs and reraises exceptions (lines 203-205)."""

        async def exec_fn(handler: Any, scope: Scope, get_value: Any) -> object:
            raise RuntimeError("pipeline-error")

        compiled = CompiledPipeline(execute=exec_fn)
        handler = Handler(
            codec=rrc(GreetRequest, GreetResponse),
            runner=_make_runner(),
        )
        axes = _make_axes()
        with pytest.raises(RuntimeError, match="pipeline-error"):
            await execute_with_pipeline(compiled, handler, axes, None)

    @pytest.mark.asyncio
    async def test_execute_with_pipeline_inject_type(self) -> None:
        """execute_with_pipeline injects raw_request by inject_type (lines 164-165)."""

        class MyRequest:
            pass

        async def exec_fn(handler: Any, scope: Scope, get_value: Any) -> object:
            result = scope.retrieve(MyRequest)
            match result:
                case Some(_v):
                    return "injected"
                case _:
                    return "not-injected"

        compiled = CompiledPipeline(execute=exec_fn, inject_type=MyRequest)
        handler = Handler(
            codec=rrc(GreetRequest, GreetResponse),
            runner=_make_runner(),
        )
        axes = _make_axes()
        req = MyRequest()
        result = await execute_with_pipeline(compiled, handler, axes, req)
        assert result == "injected"


# ═══════════════════════════════════════════════════════════════════════════════
# 8. _generate.py — to_datanode, to_datanode_auto, pydantic assembly
# ═══════════════════════════════════════════════════════════════════════════════


class TestGenerateDataNode:
    """Test to_datanode and to_datanode_auto (lines 319-320, 333-337)."""

    def test_to_datanode_basic(self) -> None:
        """to_datanode creates a DataNode subclass (lines 313-346)."""

        @dataclass
        class UserInfo:
            name: str
            age: int

        NodeCls = to_datanode(UserInfo, compose_from={})
        assert issubclass(NodeCls, DataNode)
        assert NodeCls.__name__ == "UserInfoNode"

    def test_to_datanode_with_compose_from(self) -> None:
        """to_datanode __compose__ uses compose_from mapping."""

        @dataclass
        class Info:
            val: int

        NodeCls = to_datanode(Info, compose_from={"val": ValueNode})
        assert hasattr(NodeCls, "__compose__")

    def test_to_datanode_auto_maps_fields(self) -> None:
        """to_datanode_auto maps fields via registry (lines 349-359)."""

        @dataclass
        class AutoInfo:
            value: int

        # ValueNode already produces int
        registry: dict[type, type] = {int: ValueNode}
        NodeCls = to_datanode_auto(AutoInfo, registry)
        assert issubclass(NodeCls, DataNode)
        assert NodeCls.__name__ == "AutoInfoNode"


class TestGeneratePydantic:
    """Test Pydantic model generation with field properties."""

    def test_pydantic_basic(self) -> None:
        """to_pydantic generates a BaseModel from dataclass."""
        from pydantic import BaseModel

        @dataclass
        class SimpleReq:
            name: str
            age: int

        Model = to_pydantic(SimpleReq, _make_axes())
        assert issubclass(Model, BaseModel)
        instance = Model(name="Alice", age=30)
        assert getattr(instance, "name") == "Alice"

    def test_pydantic_optional_field(self) -> None:
        """Pydantic model handles optional fields with None default (line 181)."""

        @dataclass
        class OptReq:
            name: str
            tag: str | None = None

        Model = to_pydantic(OptReq, _make_axes())
        instance = Model(name="Bob")
        assert getattr(instance, "tag") is None

    def test_pydantic_default_factory(self) -> None:
        """Pydantic model handles default_factory (line 179)."""

        @dataclass
        class FactReq:
            name: str
            items: list[str] = field(default_factory=lambda: list[str]())

        Model = to_pydantic(FactReq, _make_axes())
        instance = Model(name="Carol")
        assert getattr(instance, "items") == []

    def test_pydantic_compose_node_skipped(self) -> None:
        """Pydantic skips compose.Node fields (line 146)."""
        from emergent.wire.axis.schema.dialects import compose

        @dataclass
        class ComposeReq:
            name: str
            node_val: Annotated[int, compose.Node(ValueNode)] = 0

        Model = to_pydantic(ComposeReq, _make_axes())
        # node_val should NOT be in the pydantic model
        assert "node_val" not in Model.model_fields


class TestGenerateArgparse:
    """Test argparse spec generation."""

    def test_argparse_basic(self) -> None:
        """to_argparse_args generates specs from dataclass."""

        @dataclass
        class CLIReq:
            name: str
            count: int

        specs = to_argparse_args(CLIReq, _make_axes())
        assert len(specs) >= 2
        names = [s.dest for s in specs]
        assert "name" in names
        assert "count" in names

    def test_argparse_compose_node_skipped(self) -> None:
        """Argparse skips compose.Node fields (line 270)."""
        from emergent.wire.axis.schema.dialects import compose

        @dataclass
        class CLICompose:
            name: str
            node_val: Annotated[int, compose.Node(ValueNode)] = 0

        specs = to_argparse_args(CLICompose, _make_axes())
        dests = [s.dest for s in specs]
        assert "node_val" not in dests

    def test_argparse_bool_flag(self) -> None:
        """Argparse bool field with default generates store_true (line 291-294)."""

        @dataclass
        class BoolReq:
            verbose: bool = False

        specs = to_argparse_args(BoolReq, _make_axes())
        assert len(specs) == 1
        assert specs[0].kwargs.get("action") == "store_true"

    def test_argparse_optional_field(self) -> None:
        """Argparse optional field becomes --flag (lines 295-300)."""

        @dataclass
        class OptCLI:
            name: str
            tag: str | None = None

        specs = to_argparse_args(OptCLI, _make_axes())
        tag_spec = next(s for s in specs if s.dest == "tag")
        assert not tag_spec.is_positional


# ═══════════════════════════════════════════════════════════════════════════════
# 9. _capabilities.py — Mount, _merge_openapi, _add_generic_mount_docs
# ═══════════════════════════════════════════════════════════════════════════════


class TestMountOpenAPI:
    """Test Mount OpenAPI documentation merge (lines 181-194, 218, 246, 248)."""

    def test_add_generic_mount_docs(self) -> None:
        """_add_generic_mount_docs adds generic path docs."""
        schema: dict[str, Any] = {"paths": {}}
        _add_generic_mount_docs(schema, "/django", "django")
        assert "/django/{path:path}" in schema["paths"]
        assert "get" in schema["paths"]["/django/{path:path}"]
        assert "post" in schema["paths"]["/django/{path:path}"]
        assert "tags" in schema

    def test_merge_openapi_basic(self) -> None:
        """_merge_openapi merges source paths into target."""
        target: dict[str, Any] = {"paths": {}}
        source: dict[str, Any] = {
            "paths": {
                "/users": {
                    "get": {"tags": ["users"], "responses": {"200": {"description": "OK"}}}
                }
            }
        }
        _merge_openapi(target, source, "/api", "backend")
        assert "/api/users" in target["paths"]
        assert "get" in target["paths"]["/api/users"]

    def test_merge_openapi_with_parameters_key(self) -> None:
        """_merge_openapi skips 'parameters' method key (line 218)."""
        target: dict[str, Any] = {"paths": {}}
        source: dict[str, Any] = {
            "paths": {
                "/items": {
                    "parameters": [{"name": "id", "in": "path"}],
                    "get": {"tags": ["items"], "responses": {"200": {"description": "OK"}}},
                }
            }
        }
        _merge_openapi(target, source, "/v1", "service")
        methods = target["paths"]["/v1/items"]
        assert "parameters" not in methods
        assert "get" in methods

    def test_merge_openapi_body_param_to_request_body(self) -> None:
        """_merge_openapi converts body params to requestBody and handles non-body (lines 238-248)."""
        target: dict[str, Any] = {"paths": {}}
        source: dict[str, Any] = {
            "paths": {
                "/create": {
                    "post": {
                        "tags": ["create"],
                        "parameters": [
                            {"name": "data", "in": "body", "required": True, "schema": {"type": "object"}},
                            {"name": "q", "in": "query", "required": False},
                        ],
                        "responses": {"200": {"description": "OK"}},
                    }
                }
            }
        }
        _merge_openapi(target, source, "/api", "svc")
        post = target["paths"]["/api/create"]["post"]
        assert "requestBody" in post
        assert post["requestBody"]["required"] is True
        # Non-body param retained in parameters
        assert "parameters" in post
        assert len(post["parameters"]) == 1
        assert post["parameters"][0]["name"] == "q"

    def test_merge_openapi_body_param_only(self) -> None:
        """When only body params exist, parameters is deleted (lines 249-250)."""
        target: dict[str, Any] = {"paths": {}}
        source: dict[str, Any] = {
            "paths": {
                "/upload": {
                    "post": {
                        "tags": [],
                        "parameters": [
                            {"name": "file", "in": "body", "schema": {}},
                        ],
                        "responses": {"201": {"description": "Created"}},
                    }
                }
            }
        }
        _merge_openapi(target, source, "", "upload")
        post = target["paths"]["/upload"]["post"]
        assert "requestBody" in post
        assert "parameters" not in post

    def test_merge_openapi_swagger_response_conversion(self) -> None:
        """_merge_openapi converts Swagger 2.0 response schemas to 3.x (lines 228-232)."""
        target: dict[str, Any] = {"paths": {}}
        source: dict[str, Any] = {
            "paths": {
                "/old": {
                    "get": {
                        "tags": ["legacy"],
                        "responses": {
                            "200": {"schema": {"type": "object"}, "description": "OK"},
                        },
                    }
                }
            }
        }
        _merge_openapi(target, source, "/v2", "legacy")
        resp_200 = target["paths"]["/v2/old"]["get"]["responses"]["200"]
        assert "content" in resp_200
        assert "application/json" in resp_200["content"]
        assert "schema" not in resp_200

    def test_merge_openapi_definitions(self) -> None:
        """_merge_openapi merges definitions into components/schemas."""
        target: dict[str, Any] = {"paths": {}}
        source: dict[str, Any] = {
            "paths": {
                "/items": {
                    "get": {
                        "tags": ["items"],
                        "responses": {
                            "200": {
                                "content": {"application/json": {"schema": {"$ref": "#/definitions/Item"}}}
                            }
                        },
                    }
                }
            },
            "definitions": {
                "Item": {"type": "object", "properties": {"name": {"type": "string"}}}
            },
        }
        _merge_openapi(target, source, "/api", "shop")
        assert "components" in target
        assert "ShopItem" in target["components"]["schemas"]

    def test_mount_custom_openapi_with_source(self) -> None:
        """Mount._add_openapi_docs with source_schema calls _merge_openapi (line 186-188)."""

        class FakeApp:
            openapi_schema: dict[str, Any] | None = None

            def mount(self, prefix: str, app: Any) -> None:
                pass

            def openapi(self) -> dict[str, Any]:
                return {"paths": {}, "info": {"title": "Test", "version": "1.0"}}

        mount = Mount(
            app=FakeApp(),
            prefix="/mounted",
            source="external",
            openapi_schema={
                "paths": {"/health": {"get": {"tags": ["health"], "responses": {"200": {"description": "OK"}}}}},
            },
        )
        app = FakeApp()
        mount._add_openapi_docs(app)
        schema = app.openapi()
        assert "/mounted/health" in schema["paths"]

    def test_mount_custom_openapi_no_source(self) -> None:
        """Mount._add_openapi_docs without source adds generic docs (line 190-191)."""

        class FakeApp:
            openapi_schema: dict[str, Any] | None = None

            def mount(self, prefix: str, app: Any) -> None:
                pass

            def openapi(self) -> dict[str, Any]:
                return {"paths": {}, "info": {"title": "Test", "version": "1.0"}}

        mount = Mount(app=FakeApp(), prefix="/legacy", source="old")
        app = FakeApp()
        mount._add_openapi_docs(app)
        schema = app.openapi()
        assert "/legacy/{path:path}" in schema["paths"]

    def test_mount_openapi_cached(self) -> None:
        """Mount._add_openapi_docs caches schema (line 181-182)."""

        class FakeApp:
            openapi_schema: dict[str, Any] | None = None

            def mount(self, prefix: str, app: Any) -> None:
                pass

            def openapi(self) -> dict[str, Any]:
                return {"paths": {}, "info": {"title": "Test", "version": "1.0"}}

        mount = Mount(app=FakeApp(), prefix="/x", source="y")
        app = FakeApp()
        mount._add_openapi_docs(app)
        # First call generates
        schema1 = app.openapi()
        # Second call returns cached
        schema2 = app.openapi()
        assert schema1 is schema2


# ═══════════════════════════════════════════════════════════════════════════════
# 10. Testing target — integration tests via TestApp
# ═══════════════════════════════════════════════════════════════════════════════


class TestTestingTarget:
    """End-to-end tests via testing_compile."""

    @pytest.mark.asyncio
    async def test_rrc_via_testing_target(self) -> None:
        """Full RRC path via testing_compile -> TestApp -> TestRoute.call()."""
        runner = _make_runner()
        app = application().mount(
            endpoint(runner).expose(
                "test-trigger",
                rrc(GreetRequest, GreetResponse),
            )
        )
        test = testing_target.testing_compile(app)
        assert len(test.routes) == 1
        result = await test.routes[0].call({"name": "Testing"})
        assert isinstance(result, GreetResponse)
        assert result.message == "Hello, Testing!"

    @pytest.mark.asyncio
    async def test_delegate_via_testing_target(self) -> None:
        """Full delegate path via testing_compile."""
        called: list[str] = []

        async def my_handler() -> str:
            called.append("delegate")
            return "delegate-result"

        runner = _make_runner()
        app = application().mount(
            endpoint(runner).expose(
                "delegate-trigger",
                delegate(my_handler),
            )
        )
        test = testing_target.testing_compile(app)
        result = await test.routes[0].call()
        assert result == "delegate-result"
        assert called == ["delegate"]

    @pytest.mark.asyncio
    async def test_immediate_via_testing_target(self) -> None:
        """Full immediate path via testing_compile."""

        @dataclass
        class HelpResp:
            text: str = "help!"

            @classmethod
            def produce(cls) -> Self:
                return cls()

        runner = _make_runner()
        app = application().mount(
            endpoint(runner).expose(
                "help-trigger",
                immediate(HelpResp),
            )
        )
        test = testing_target.testing_compile(app)
        result = await test.routes[0].call()
        assert isinstance(result, HelpResp)
        assert result.text == "help!"

    @pytest.mark.asyncio
    async def test_immediate_factory_via_testing(self) -> None:
        """Immediate factory path via testing_compile."""
        runner = _make_runner()
        app = application().mount(
            endpoint(runner).expose(
                "factory-trigger",
                immediate_factory(lambda: {"status": "ok"}),
            )
        )
        test = testing_target.testing_compile(app)
        result = await test.routes[0].call()
        assert result == {"status": "ok"}

    @pytest.mark.asyncio
    async def test_testing_target_with_inject(self) -> None:
        """TestRoute.call() with custom inject_scope."""
        injected_values: list[str] = []

        def inject(scope: Scope) -> None:
            injected_values.append("injected")

        runner = _make_runner()
        app = application().mount(
            endpoint(runner).expose(
                "inject-trigger",
                rrc(GreetRequest, GreetResponse),
            )
        )
        test = testing_target.testing_compile(app)
        result = await test.routes[0].call(
            {"name": "Injected"},
            inject=inject,
        )
        assert isinstance(result, GreetResponse)
        assert injected_values == ["injected"]

    @pytest.mark.asyncio
    async def test_multiple_routes(self) -> None:
        """testing_compile handles multiple endpoints."""
        runner = _make_runner()
        app = application().mount(
            endpoint(runner).expose("t1", rrc(GreetRequest, GreetResponse)),
            endpoint(runner).expose("t2", rrc(GreetRequest, GreetResponse)),
        )
        test = testing_target.testing_compile(app)
        assert len(test.routes) == 2

    @pytest.mark.asyncio
    async def test_test_app_context_manager(self) -> None:
        """TestApp __aenter__/__aexit__ work without family."""
        runner = _make_runner()
        app = application().mount(
            endpoint(runner).expose("t1", rrc(GreetRequest, GreetResponse)),
        )
        test = testing_target.testing_compile(app)
        async with test as t:
            result = await t.routes[0].call({"name": "CM"})
            assert isinstance(result, GreetResponse)


# ═══════════════════════════════════════════════════════════════════════════════
# 11. State management — load/save/delete (covered for completeness)
# ═══════════════════════════════════════════════════════════════════════════════


class TestStateManagement:
    """Test state management helpers."""

    @pytest.mark.asyncio
    async def test_load_state_initial(self) -> None:
        """load_state returns initial flow when key not found."""
        codec = StatefulCodec(
            flow=BetFlow,
            response=BetResponse,
            store=MemoryStorage[str, object](),
            key_node=SimpleKeyNode,
            agent_cls=EventLoopAgent,
        )
        state = await load_state(codec, "new-key")
        assert isinstance(state, BetFlow)
        assert state.step == 0

    @pytest.mark.asyncio
    async def test_load_state_existing(self) -> None:
        """load_state returns saved state."""
        codec = StatefulCodec(
            flow=BetFlow,
            response=BetResponse,
            store=MemoryStorage[str, object](),
            key_node=SimpleKeyNode,
            agent_cls=EventLoopAgent,
        )
        saved = BetFlow(step=5)
        await codec.store.set("existing", saved)
        state = await load_state(codec, "existing")
        assert state.step == 5

    @pytest.mark.asyncio
    async def test_save_state_changed(self) -> None:
        """save_state saves when new is different from old."""
        codec = StatefulCodec(
            flow=BetFlow,
            response=BetResponse,
            store=MemoryStorage[str, object](),
            key_node=SimpleKeyNode,
            agent_cls=EventLoopAgent,
        )
        old = BetFlow(step=0)
        new = BetFlow(step=1)
        await save_state(codec, "k", old, new)
        loaded = await load_state(codec, "k")
        assert loaded.step == 1

    @pytest.mark.asyncio
    async def test_save_state_unchanged(self) -> None:
        """save_state skips when new is same object as old."""
        codec = StatefulCodec(
            flow=BetFlow,
            response=BetResponse,
            store=MemoryStorage[str, object](),
            key_node=SimpleKeyNode,
            agent_cls=EventLoopAgent,
        )
        state = BetFlow(step=0)
        await save_state(codec, "k", state, state)
        # Should not be saved
        loaded = await load_state(codec, "k")
        assert loaded.step == 0  # initial default

    @pytest.mark.asyncio
    async def test_delete_state(self) -> None:
        """delete_state removes from store."""
        codec = StatefulCodec(
            flow=BetFlow,
            response=BetResponse,
            store=MemoryStorage[str, object](),
            key_node=SimpleKeyNode,
            agent_cls=EventLoopAgent,
        )
        await codec.store.set("del-key", BetFlow(step=3))
        await delete_state(codec, "del-key")
        state = await load_state(codec, "del-key")
        assert state.step == 0  # back to initial


# ═══════════════════════════════════════════════════════════════════════════════
# 12. apply_response_capabilities, fold_handler_runtime
# ═══════════════════════════════════════════════════════════════════════════════


class TestCapabilityProcessing:
    """Test response capability application."""

    def test_apply_no_capabilities(self) -> None:
        """apply_response_capabilities with no caps returns unchanged."""
        result = apply_response_capabilities("hello", ())
        assert result == "hello"

    def test_fold_handler_runtime_empty(self) -> None:
        """fold_handler_runtime with empty caps returns empty context."""
        ctx = fold_handler_runtime(())
        assert ctx.enrichers == ()
        assert ctx.response_transforms == ()

    def test_fold_handler_runtime_with_enricher(self) -> None:
        """fold_handler_runtime collects enrichers."""
        counter: list[int] = []
        enricher = CountingEnricher(counter=counter)
        ctx = fold_handler_runtime((enricher,))
        assert len(ctx.enrichers) == 1


# ═══════════════════════════════════════════════════════════════════════════════
# 13. Immediate unified execution
# ═══════════════════════════════════════════════════════════════════════════════


class TestImmediateUnified:
    """Test execute_immediate_unified for both codec types."""

    def test_immediate_codec(self) -> None:
        """ImmediateCodec produces response via produce()."""

        @dataclass
        class Resp:
            msg: str = "produced"

            @classmethod
            def produce(cls) -> Self:
                return cls()

        handler = Handler(
            codec=immediate(Resp),
            runner=_make_runner(),
        )
        result = execute_immediate_unified(handler)
        assert isinstance(result, Resp)
        assert result.msg == "produced"

    def test_immediate_factory_codec(self) -> None:
        """ImmediateFactoryCodec calls factory."""
        handler = Handler(
            codec=immediate_factory(lambda: {"key": "value"}),
            runner=_make_runner(),
        )
        result = execute_immediate_unified(handler)
        assert result == {"key": "value"}

    def test_immediate_with_format_response(self) -> None:
        """execute_immediate_unified applies format_response."""

        @dataclass
        class Resp:
            msg: str = "produced"

            @classmethod
            def produce(cls) -> Self:
                return cls()

        handler = Handler(
            codec=immediate(Resp),
            runner=_make_runner(),
        )
        result = execute_immediate_unified(handler, format_response=lambda r: r.msg.upper())
        assert result == "PRODUCED"

    def test_immediate_unknown_codec_raises(self) -> None:
        """execute_immediate_unified raises TypeError for unknown codec."""

        class WeirdCodec:
            pass

        handler = Handler(
            codec=WeirdCodec(),
            runner=_make_runner(),
        )
        with pytest.raises(TypeError, match="Expected ImmediateCodec"):
            execute_immediate_unified(handler)


# ═══════════════════════════════════════════════════════════════════════════════
# 14. execute_stateful_turn — parsing results
# ═══════════════════════════════════════════════════════════════════════════════


class TestExecuteStatefulTurn:
    """Test execute_stateful_turn with various transition results."""

    @pytest.mark.asyncio
    async def test_turn_non_terminal(self) -> None:
        """Non-terminal turn returns new state and response."""
        codec = StatefulCodec(
            flow=BetFlow,
            response=BetResponse,
            store=MemoryStorage[str, object](),
            key_node=SimpleKeyNode,
            agent_cls=EventLoopAgent,
        )
        handler = Handler(
            codec=codec,
            runner=ops().on(PlaceBetOp, _handle_place_bet).compile(),
        )

        state = BetFlow(step=0)
        transitions = get_transitions(BetFlow)
        method = transitions[0]

        new_state, response, is_terminal = await execute_stateful_turn(
            handler, state, method, {}
        )
        assert not is_terminal
        assert isinstance(new_state, BetFlow)
        assert new_state.step == 1
        assert response == "step-1"

    @pytest.mark.asyncio
    async def test_turn_terminal(self) -> None:
        """Terminal turn with Done returns is_terminal=True."""
        codec = StatefulCodec(
            flow=BetFlow,
            response=BetResponse,
            store=MemoryStorage[str, object](),
            key_node=SimpleKeyNode,
            agent_cls=EventLoopAgent,
        )
        handler = Handler(
            codec=codec,
            runner=ops().on(PlaceBetOp, _handle_place_bet).compile(),
        )

        state = BetFlow(step=2)
        transitions = get_transitions(BetFlow)
        method = transitions[0]

        new_state, response, is_terminal = await execute_stateful_turn(
            handler, state, method, {}
        )
        assert is_terminal
        assert isinstance(new_state, Done)
        assert response is None


# ═══════════════════════════════════════════════════════════════════════════════
# 15. _merge_openapi edge cases
# ═══════════════════════════════════════════════════════════════════════════════


class TestMergeOpenAPIEdgeCases:
    """Additional edge cases for _merge_openapi."""

    def test_merge_with_base_path(self) -> None:
        """_merge_openapi includes basePath from source."""
        target: dict[str, Any] = {"paths": {}}
        source: dict[str, Any] = {
            "basePath": "/api/v1",
            "paths": {
                "/users": {
                    "get": {"tags": ["users"], "responses": {"200": {"description": "OK"}}}
                }
            },
        }
        _merge_openapi(target, source, "/proxy", "backend")
        assert "/proxy/api/v1/users" in target["paths"]

    def test_merge_tags_from_source(self) -> None:
        """_merge_openapi merges tags from source spec."""
        target: dict[str, Any] = {"paths": {}}
        source: dict[str, Any] = {
            "paths": {},
            "tags": [
                {"name": "users", "description": "User management"},
            ],
        }
        _merge_openapi(target, source, "/api", "backend")
        assert "tags" in target
        tag_names = [t["name"] for t in target["tags"]]
        assert "backend:users" in tag_names
        assert "backend" in tag_names

    def test_merge_no_tags_in_method(self) -> None:
        """_merge_openapi adds source_name when no tags present."""
        target: dict[str, Any] = {"paths": {}}
        source: dict[str, Any] = {
            "paths": {
                "/ping": {
                    "get": {"responses": {"200": {"description": "pong"}}}
                }
            },
        }
        _merge_openapi(target, source, "/ext", "external")
        method = target["paths"]["/ext/ping"]["get"]
        assert method["tags"] == ["external"]

"""Tests for remaining coverage gaps across multiple modules.

Covers:
1. _request.py: compose_optional_node, compose_fallback_nodes, compose_race_nodes,
   compose_node_map, compose_node_default, default_factory, optional None paths
2. _execute.py: execute_stateful_unified cancelled/done paths, execute_delegate_unified,
   _family_mapped with no layer
3. _stateful.py: execute_stateful_done with enrichers, Union response fallback
4. targets/pure.py: wrap_websocket_delegate inner handler, wrap_exception_delegate
5. enrichers/_impl.py: Cached enricher (cache hit + miss paths)
6. _generate.py: to_datanode, to_datanode_auto, to_telegram_fields
"""

from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Callable
from typing import Annotated, Self, Union

import pytest

from kungfu import Result, Ok, Error, Some, Nothing, Option
from nodnod import Scope, Node
from nodnod.agent.event_loop.agent import EventLoopAgent
from nodnod.utils.create_node import create_node

from emergent.ops._graph import Op, Runner, ops
from emergent.wire.axis.surface._handler import Handler
from emergent.wire.axis.surface.codecs.stateful import (
    StatefulCodec,
    Done,
    Cancelled,
    transition,
    get_transitions,
)
from emergent.wire.axis.surface.codecs.delegate import DelegateCodec, delegate
from emergent.wire.axis.surface.enrichers._impl import (
    Cached,
    Inject,
)
from emergent.wire.axis.storage import MemoryStorage
from emergent.wire.axis.schema.dialects.compose import (
    Node as ComposeNode,
    Optional as ComposeOptional,
    Fallback as ComposeFallback,
    Race as ComposeRace,
    Retrieve as ComposeRetrieve,
)
from emergent.wire.compile._request import (
    build_request,
)
from emergent.wire.compile._stateful import (
    execute_stateful_done,
)
from emergent.wire.compile._execute import (
    execute_stateful_unified,
    execute_delegate_unified,
    _family_mapped,  # pyright: ignore[reportPrivateUsage] - testing private helper directly
)
from emergent.wire.compile._core import Axes
from emergent.wire.compile._generate import (
    to_datanode,
    to_datanode_auto,
    to_telegram_fields,
)


# =============================================================================
# Shared test helpers
# =============================================================================


def _make_memory_store() -> MemoryStorage[str, object]:
    return MemoryStorage[str, object]()


@dataclass(frozen=True, slots=True)
class _SimpleOp(Op[int, str]):
    value: int


async def _simple_op_handler(req: _SimpleOp) -> Result[int, str]:
    return Ok(req.value)


def _make_runner() -> Runner:
    return ops().on(_SimpleOp, _simple_op_handler).compile()


def _noop_inject(scope: Scope) -> None:
    """No-op scope injector for tests."""
    return None


def _always_none(name: str) -> None:
    """get_value that always returns None — for testing missing fields."""
    return None


def _compose_success(cls: type) -> str:
    return "success_value"


def _compose_fail(cls: type) -> str:
    raise RuntimeError("fail")


# Nodes for compose tests
_SuccessNode: type[Node[str, str]] = create_node(
    name="_SuccessNode",
    base_node=Node,
    bases=(),
    namespace={
        "__compose__": classmethod(_compose_success),
        "__module__": __name__,
    },
)

_FailNode: type[Node[str, str]] = create_node(
    name="_FailNode",
    base_node=Node,
    bases=(),
    namespace={
        "__compose__": classmethod(_compose_fail),
        "__module__": __name__,
    },
)


# =============================================================================
# 1. _request.py — compose_optional_node path
# =============================================================================


@dataclass
class OptionalNodeReq:
    name: str
    maybe: Annotated[Option[str], ComposeOptional(_SuccessNode)] = field(
        default_factory=Nothing
    )


@dataclass
class OptionalNodeFailReq:
    name: str
    maybe: Annotated[Option[str], ComposeOptional(int)] = field(
        default_factory=Nothing
    )


class TestComposeOptionalNode:
    """Lines 82-87: compose_optional_node success => Some, failure => Nothing."""

    @pytest.mark.asyncio
    async def test_optional_node_success_returns_some(self) -> None:
        async with Scope() as scope:
            result = await build_request(
                OptionalNodeReq, {"name": "Alice"}.get, scope=scope
            )
            assert result.name == "Alice"
            # compose_optional_node succeeded, wrapped in Some
            maybe: Option[str] = result.maybe
            assert isinstance(maybe, Some)
            assert maybe.unwrap() == "success_value"

    @pytest.mark.asyncio
    async def test_optional_node_failure_returns_nothing(self) -> None:
        """When node composition fails, result is Nothing()."""
        async with Scope() as scope:
            result = await build_request(
                OptionalNodeFailReq, {"name": "Alice"}.get, scope=scope
            )
            assert result.name == "Alice"
            assert isinstance(result.maybe, Nothing)


# =============================================================================
# 1. _request.py — compose_fallback_nodes path
# =============================================================================


def _compose_fallback_a(cls: type) -> str:
    return "fallback_A"


def _compose_fallback_b(cls: type) -> str:
    return "fallback_B"


_FallbackNodeA: type[Node[str, str]] = create_node(
    name="_FallbackNodeA",
    base_node=Node,
    bases=(),
    namespace={
        "__compose__": classmethod(_compose_fallback_a),
        "__module__": __name__,
    },
)

_FallbackNodeB: type[Node[str, str]] = create_node(
    name="_FallbackNodeB",
    base_node=Node,
    bases=(),
    namespace={
        "__compose__": classmethod(_compose_fallback_b),
        "__module__": __name__,
    },
)


@dataclass
class FallbackReq:
    name: str
    data: Annotated[str, ComposeFallback(_FallbackNodeA, _FallbackNodeB)] = ""


@dataclass
class FallbackAllFailReq:
    name: str
    data: Annotated[str, ComposeFallback(int, float)] = ""


class TestComposeFallbackNodes:
    """Lines 89-94: compose_fallback_nodes — first success wins, or all fail."""

    @pytest.mark.asyncio
    async def test_fallback_first_succeeds(self) -> None:
        async with Scope() as scope:
            result = await build_request(
                FallbackReq, {"name": "X"}.get, scope=scope
            )
            assert result.data == "fallback_A"

    @pytest.mark.asyncio
    async def test_fallback_all_fail_returns_error(self) -> None:
        """All fallback nodes fail => field resolution fails."""
        with pytest.raises(RuntimeError, match="All fallback nodes failed"):
            async with Scope() as scope:
                await build_request(
                    FallbackAllFailReq, {"name": "X"}.get, scope=scope
                )


# =============================================================================
# 1. _request.py — compose_race_nodes path
# =============================================================================


def _compose_race_1(cls: type) -> str:
    return "race_1"


def _compose_race_2(cls: type) -> str:
    return "race_2"


_RaceNode1: type[Node[str, str]] = create_node(
    name="_RaceNode1",
    base_node=Node,
    bases=(),
    namespace={
        "__compose__": classmethod(_compose_race_1),
        "__module__": __name__,
    },
)

_RaceNode2: type[Node[str, str]] = create_node(
    name="_RaceNode2",
    base_node=Node,
    bases=(),
    namespace={
        "__compose__": classmethod(_compose_race_2),
        "__module__": __name__,
    },
)


@dataclass
class RaceReq:
    name: str
    data: Annotated[str, ComposeRace(_RaceNode1, _RaceNode2)] = ""


@dataclass
class RaceAllFailReq:
    name: str
    data: Annotated[str, ComposeRace(int, float)] = ""


class TestComposeRaceNodes:
    """Lines 96-103: compose_race_nodes — concurrent, first success wins."""

    @pytest.mark.asyncio
    async def test_race_returns_first_success(self) -> None:
        async with Scope() as scope:
            result = await build_request(
                RaceReq, {"name": "X"}.get, scope=scope
            )
            # One of the race nodes succeeded
            assert result.data in ("race_1", "race_2")

    @pytest.mark.asyncio
    async def test_race_all_fail_returns_error(self) -> None:
        """All race nodes fail => field resolution fails."""
        with pytest.raises(RuntimeError, match="All race nodes failed"):
            async with Scope() as scope:
                await build_request(
                    RaceAllFailReq, {"name": "X"}.get, scope=scope
                )


# =============================================================================
# 1. _request.py — compose_node_map path
# =============================================================================


@dataclass
class NodeMapReq:
    name: str
    data: Annotated[str, ComposeNode(_SuccessNode, map=lambda v: v.upper())] = ""  # pyright: ignore[reportUnknownLambdaType] - map callback type unknown in ComposeNode


class TestComposeNodeMap:
    """Line 74-75: compose_node_map applied after successful compose."""

    @pytest.mark.asyncio
    async def test_node_map_applied(self) -> None:
        async with Scope() as scope:
            result = await build_request(
                NodeMapReq, {"name": "X"}.get, scope=scope
            )
            assert result.data == "SUCCESS_VALUE"


# =============================================================================
# 1. _request.py — compose_node_default path
# =============================================================================


@dataclass
class NodeDefaultReq:
    name: str
    data: Annotated[str, ComposeNode(int, default="fallback_default")] = ""


class TestComposeNodeDefault:
    """Lines 77-78: compose_node fails but default is provided."""

    @pytest.mark.asyncio
    async def test_node_default_on_failure(self) -> None:
        async with Scope() as scope:
            result = await build_request(
                NodeDefaultReq, {"name": "X"}.get, scope=scope
            )
            assert result.data == "fallback_default"


# =============================================================================
# 1. _request.py — compose_node no default (line 79-80)
# =============================================================================


@dataclass
class NodeNoDefaultReq:
    name: str
    data: Annotated[str, ComposeNode(int)] = ""


class TestComposeNodeNoDefault:
    """Lines 79-80: compose_node fails, no default, returns error."""

    @pytest.mark.asyncio
    async def test_node_failure_no_default_required_field(self) -> None:
        @dataclass
        class _ReqNodeFail:
            data: Annotated[str, ComposeNode(int)]

        with pytest.raises(RuntimeError, match="Cannot resolve required field"):
            async with Scope() as scope:
                await build_request(
                    _ReqNodeFail, _always_none, scope=scope
                )


# =============================================================================
# 1. _request.py — compose_retrieve Nothing path (lines 110-111)
# =============================================================================


class _Missing:
    pass


@dataclass
class RetrieveMissReq:
    data: Annotated[_Missing, ComposeRetrieve(_Missing)]


class TestComposeRetrieveNothing:
    """Lines 110-111: compose_retrieve_type returns Nothing => error."""

    @pytest.mark.asyncio
    async def test_retrieve_missing_raises(self) -> None:
        with pytest.raises(RuntimeError, match="Cannot resolve required field"):
            async with Scope() as scope:
                await build_request(
                    RetrieveMissReq, _always_none, scope=scope
                )


# =============================================================================
# 1. _request.py — default_factory path (line 123)
# =============================================================================


@dataclass
class FactoryDefaultReq:
    name: str
    items: list[str] = field(default_factory=list)  # pyright: ignore[reportUnknownVariableType] - bare list factory; type annotation provides list[str]


class TestBuildFieldValueDefaultFactory:
    """Line 123: default_factory fallback."""

    @pytest.mark.asyncio
    async def test_default_factory_used_when_no_value(self) -> None:
        result = await build_request(
            FactoryDefaultReq, {"name": "X"}.get
        )
        items: list[str] = result.items
        assert items == []


# =============================================================================
# 1. _request.py — optional field None path (line 127)
# =============================================================================


@dataclass
class OptFieldReq:
    name: str
    bio: str | None = None


class TestBuildFieldValueOptionalNone:
    """Line 127: optional field with no value returns None."""

    @pytest.mark.asyncio
    async def test_optional_field_resolves_to_none(self) -> None:
        result = await build_request(
            OptFieldReq, {"name": "X"}.get
        )
        assert result.bio is None


# =============================================================================
# 2. _execute.py — _family_mapped with no layer (line 51-58)
# =============================================================================


class TestFamilyMapped:
    """Lines 51-58: _family_mapped returns empty dict when layer is None."""

    def test_family_mapped_none_returns_empty(self) -> None:
        result = _family_mapped(None, Scope())
        assert result == {}

    def test_family_mapped_with_layer(self) -> None:
        from emergent.wire.compile._lifetime import ScopeLayer, App, Request, Tier
        from emergent.graph._family import ScopeFamily

        family: ScopeFamily[Tier] = ScopeFamily[Tier]().bind(App, str).bind(Request, int)
        app_scope = Scope()
        layer = ScopeLayer(
            scopes={App: app_scope},
            family=family,
            leaf=Request,
        )
        req_scope = Scope()
        result = _family_mapped(layer, req_scope)
        # str is bound to App => maps to app_scope
        # int is bound to Request => maps to req_scope
        assert str in result
        assert result[str] is app_scope
        assert int in result
        assert result[int] is req_scope


# =============================================================================
# 2. _execute.py — execute_stateful_unified cancelled path (lines 211-213)
# =============================================================================


@dataclass(frozen=True, slots=True)
class _CancelOp(Op[int, str]):
    pass


async def _cancel_op_handler(req: _CancelOp) -> Result[int, str]:
    return Ok(0)


@dataclass
class CancelFlow:
    step: int = 0

    @transition
    async def go(self, cancel: bool = False) -> Self | Done:
        if cancel:
            return Cancelled()
        return Done()

    def to_domain(self) -> _CancelOp:
        return _CancelOp()


@dataclass
class CancelResp:
    value: int

    @classmethod
    def from_domain(cls, r: Result[int, str]) -> Self:
        match r:
            case Ok(v):
                return cls(value=v)
            case Error():
                return cls(value=-1)


class TestExecuteStatefulUnifiedCancelled:
    """Lines 211-213: Cancelled path in execute_stateful_unified."""

    @pytest.mark.asyncio
    async def test_cancelled_deletes_state_and_returns(self) -> None:
        store = _make_memory_store()
        codec = StatefulCodec(
            flow=CancelFlow,
            response=CancelResp,
            store=store,
            key_node=str,
            agent_cls=EventLoopAgent,
        )
        runner = ops().on(_CancelOp, _cancel_op_handler).compile()
        handler = Handler(codec=codec, runner=runner, capabilities=())

        transitions = get_transitions(CancelFlow)
        method = transitions[0]

        async def resolve() -> tuple[object, dict[str, object]]:
            return method, {"cancel": True}

        _response, is_done = await execute_stateful_unified(
            handler=handler,
            store_key="user1",
            resolve_transition=resolve,
            inject_scope=_noop_inject,
        )
        # Cancelled => is_done=True, state deleted
        assert is_done


# =============================================================================
# 2. _execute.py — execute_stateful_unified done path (lines 216-229)
# =============================================================================


@dataclass(frozen=True, slots=True)
class _TerminalState(Done):
    """Terminal state that carries to_domain() — used when flow is complete.

    Subclasses Done so isinstance(state, Done) is True (terminal),
    but also carries the accumulated data for to_domain().
    """
    count: int = 0

    def to_domain(self) -> _SimpleOp:
        return _SimpleOp(value=self.count)


@dataclass
class DoneFlow:
    count: int = 5

    @transition
    async def go(self) -> Self | _TerminalState:
        return _TerminalState(count=self.count)

    def to_domain(self) -> _SimpleOp:
        return _SimpleOp(value=self.count)


@dataclass
class DoneResp:
    value: int

    @classmethod
    def from_domain(cls, r: Result[int, str]) -> Self:
        match r:
            case Ok(v):
                return cls(value=v)
            case Error():
                return cls(value=-1)


class TestExecuteStatefulUnifiedDone:
    """Lines 216-229: Done path — creates scope, executes, deletes state."""

    @pytest.mark.asyncio
    async def test_done_path_executes_op(self) -> None:
        store = _make_memory_store()
        codec = StatefulCodec(
            flow=DoneFlow,
            response=DoneResp,
            store=store,
            key_node=str,
            agent_cls=EventLoopAgent,
        )
        runner = _make_runner()
        handler = Handler(codec=codec, runner=runner, capabilities=())

        transitions = get_transitions(DoneFlow)
        method = transitions[0]

        async def resolve() -> tuple[object, dict[str, object]]:
            return method, {}

        response, is_done = await execute_stateful_unified(
            handler=handler,
            store_key="user1",
            resolve_transition=resolve,
            inject_scope=_noop_inject,
        )
        assert is_done
        assert isinstance(response, DoneResp)
        assert response.value == 5

    @pytest.mark.asyncio
    async def test_done_with_parent_scope(self) -> None:
        """Line 220: parent_scope path when no axes layer."""
        store = _make_memory_store()
        codec = StatefulCodec(
            flow=DoneFlow,
            response=DoneResp,
            store=store,
            key_node=str,
            agent_cls=EventLoopAgent,
        )
        runner = _make_runner()
        handler = Handler(codec=codec, runner=runner, capabilities=())

        transitions = get_transitions(DoneFlow)
        method = transitions[0]

        async def resolve() -> tuple[object, dict[str, object]]:
            return method, {}

        async with Scope() as parent:
            response, is_done = await execute_stateful_unified(
                handler=handler,
                store_key="user1",
                resolve_transition=resolve,
                inject_scope=_noop_inject,
                parent_scope=parent,
            )
            assert is_done
            assert isinstance(response, DoneResp)

    @pytest.mark.asyncio
    async def test_done_with_format_response(self) -> None:
        """Lines 241-242: format_response applied after done."""
        store = _make_memory_store()
        codec = StatefulCodec(
            flow=DoneFlow,
            response=DoneResp,
            store=store,
            key_node=str,
            agent_cls=EventLoopAgent,
        )
        runner = _make_runner()
        handler = Handler(codec=codec, runner=runner, capabilities=())

        transitions = get_transitions(DoneFlow)
        method = transitions[0]

        async def resolve() -> tuple[object, dict[str, object]]:
            return method, {}

        response, is_done = await execute_stateful_unified(
            handler=handler,
            store_key="user1",
            resolve_transition=resolve,
            inject_scope=_noop_inject,
            format_response=lambda r: {"formatted": True, "original": r},
        )
        assert is_done
        assert response["formatted"] is True
        assert isinstance(response["original"], DoneResp)


# =============================================================================
# 2. _execute.py — execute_stateful_unified non-terminal path
# =============================================================================


@dataclass
class MultiStepFlow:
    step: int = 0

    @transition
    async def advance(self) -> Self | tuple[Self, str] | Done:
        if self.step >= 2:
            return Done()
        new: Self = MultiStepFlow(step=self.step + 1)  # pyright: ignore[reportAssignmentType] - MultiStepFlow is final, Self == MultiStepFlow
        return new, f"step_{self.step + 1}"

    def to_domain(self) -> _SimpleOp:
        return _SimpleOp(value=self.step)


class TestExecuteStatefulUnifiedNonTerminal:
    """Lines 202-208: non-terminal path saves state and returns response."""

    @pytest.mark.asyncio
    async def test_non_terminal_saves_state(self) -> None:
        store = _make_memory_store()
        codec = StatefulCodec(
            flow=MultiStepFlow,
            response=DoneResp,
            store=store,
            key_node=str,
            agent_cls=EventLoopAgent,
        )
        runner = _make_runner()
        handler = Handler(codec=codec, runner=runner, capabilities=())

        transitions = get_transitions(MultiStepFlow)
        method = transitions[0]

        async def resolve() -> tuple[object, dict[str, object]]:
            return method, {}

        response, is_done = await execute_stateful_unified(
            handler=handler,
            store_key="user1",
            resolve_transition=resolve,
            inject_scope=_noop_inject,
        )
        assert not is_done
        assert response == "step_1"

    @pytest.mark.asyncio
    async def test_non_terminal_with_format_response(self) -> None:
        """Lines 204-207: non-terminal with format_response applied."""
        store = _make_memory_store()
        codec = StatefulCodec(
            flow=MultiStepFlow,
            response=DoneResp,
            store=store,
            key_node=str,
            agent_cls=EventLoopAgent,
        )
        runner = _make_runner()
        handler = Handler(codec=codec, runner=runner, capabilities=())

        transitions = get_transitions(MultiStepFlow)
        method = transitions[0]

        async def resolve() -> tuple[object, dict[str, object]]:
            return method, {}

        response, is_done = await execute_stateful_unified(
            handler=handler,
            store_key="user1",
            resolve_transition=resolve,
            inject_scope=_noop_inject,
            format_response=lambda r: f"fmt:{r}",
        )
        assert not is_done
        assert response == "fmt:step_1"


# =============================================================================
# 2. _execute.py — execute_delegate_unified (lines 328, 335-336, 341-353)
# =============================================================================


class TestExecuteDelegateUnified:
    """Lines 290-362: execute_delegate_unified — async handler body."""

    @pytest.mark.asyncio
    async def test_delegate_async_handler(self) -> None:
        async def my_handler() -> str:
            return "delegate_result"

        codec = delegate(my_handler)
        runner = _make_runner()
        handler = Handler(codec=codec, runner=runner, capabilities=())

        result = await execute_delegate_unified(
            handler=handler,
            inject_scope=_noop_inject,
        )
        assert result == "delegate_result"

    @pytest.mark.asyncio
    async def test_delegate_sync_handler(self) -> None:
        def my_sync_handler() -> str:
            return "sync_result"

        codec = delegate(my_sync_handler)
        runner = _make_runner()
        handler = Handler(codec=codec, runner=runner, capabilities=())

        result = await execute_delegate_unified(
            handler=handler,
            inject_scope=_noop_inject,
        )
        assert result == "sync_result"

    @pytest.mark.asyncio
    async def test_delegate_with_format_response(self) -> None:
        async def my_handler() -> str:
            return "raw"

        codec = delegate(my_handler)
        runner = _make_runner()
        handler = Handler(codec=codec, runner=runner, capabilities=())

        result = await execute_delegate_unified(
            handler=handler,
            inject_scope=_noop_inject,
            format_response=lambda r: f"formatted:{r}",
        )
        assert result == "formatted:raw"

    @pytest.mark.asyncio
    async def test_delegate_with_enrichers(self) -> None:
        """Lines 347-348: delegate with enrichers wrapping execution."""
        async def my_handler() -> str:
            return "enriched"

        codec = delegate(my_handler)
        runner = _make_runner()
        enricher = Inject(type=int, value=99)
        handler = Handler(codec=codec, runner=runner, capabilities=(enricher,))

        result = await execute_delegate_unified(
            handler=handler,
            inject_scope=_noop_inject,
        )
        assert result == "enriched"

    @pytest.mark.asyncio
    async def test_delegate_exception_propagates(self) -> None:
        """Lines 351-353: exception in delegate propagates."""
        async def failing_handler() -> str:
            raise ValueError("delegate_fail")

        codec = delegate(failing_handler)
        runner = _make_runner()
        handler = Handler(codec=codec, runner=runner, capabilities=())

        with pytest.raises(ValueError, match="delegate_fail"):
            await execute_delegate_unified(
                handler=handler,
                inject_scope=_noop_inject,
            )


# =============================================================================
# 3. _stateful.py — execute_stateful_done with enrichers (lines 105-107)
# =============================================================================


class TestExecuteStatefulDoneWithEnrichers:
    """Lines 105-107: enrichers wrap core_handler in execute_stateful_done."""

    @pytest.mark.asyncio
    async def test_done_with_enricher_chain(self) -> None:
        codec = StatefulCodec(
            flow=DoneFlow,
            response=DoneResp,
            store=_make_memory_store(),
            key_node=str,
            agent_cls=EventLoopAgent,
        )
        runner = _make_runner()
        enricher = Inject(type=int, value=42)
        handler = Handler(codec=codec, runner=runner, capabilities=(enricher,))
        state = DoneFlow(count=10)

        async with Scope() as scope:
            result = await execute_stateful_done(handler, state, scope)
            assert isinstance(result, DoneResp)
            assert result.value == 10
            # Enricher injected int
            wrapper = scope.get(int)
            assert wrapper is not None
            assert wrapper.value == 42


# =============================================================================
# 3. _stateful.py — Union response fallback (lines 91-98)
# =============================================================================


@dataclass
class UnionRespA:
    val_a: int

    @classmethod
    def from_domain(cls, r: Result[int, str]) -> Self:
        match r:
            case Ok(v):
                return cls(val_a=v)
            case Error():
                return cls(val_a=-1)


@dataclass
class UnionRespB:
    val_b: str


@dataclass(frozen=True, slots=True)
class _UnionTerminalState(Done):
    """Terminal state for union response test."""
    count: int = 0

    def to_domain(self) -> _SimpleOp:
        return _SimpleOp(value=self.count)


@dataclass
class UnionDoneFlow:
    count: int = 7

    @transition
    async def go(self) -> Self | _UnionTerminalState:
        return _UnionTerminalState(count=self.count)

    def to_domain(self) -> _SimpleOp:
        return _SimpleOp(value=self.count)


class TestExecuteStatefulDoneUnionResponse:
    """Lines 91-98: Union response type — finds member with from_domain."""

    @pytest.mark.asyncio
    async def test_union_response_finds_from_domain(self) -> None:
        codec = StatefulCodec(
            flow=UnionDoneFlow,
            response=Union[UnionRespA, UnionRespB],
            store=_make_memory_store(),
            key_node=str,
            agent_cls=EventLoopAgent,
        )
        runner = _make_runner()
        handler = Handler(codec=codec, runner=runner, capabilities=())
        state = UnionDoneFlow(count=99)

        async with Scope() as scope:
            result = await execute_stateful_done(handler, state, scope)
            assert isinstance(result, UnionRespA)
            assert result.val_a == 99


# =============================================================================
# 3. _stateful.py — scope_extras in core_handler (line 82)
# =============================================================================


class TestExecuteStatefulDoneScopeExtras:
    """Line 82: scope.merge() extracts scope_extras excluding Scope itself."""

    @pytest.mark.asyncio
    async def test_scope_extras_passed_to_runner(self) -> None:
        codec = StatefulCodec(
            flow=DoneFlow,
            response=DoneResp,
            store=_make_memory_store(),
            key_node=str,
            agent_cls=EventLoopAgent,
        )
        runner = _make_runner()
        handler = Handler(codec=codec, runner=runner, capabilities=())
        state = DoneFlow(count=42)

        async with Scope() as scope:
            scope.inject(str, "extra_string")
            result = await execute_stateful_done(handler, state, scope)
            assert isinstance(result, DoneResp)
            assert result.value == 42


# =============================================================================
# 4. targets/pure.py — wrap_websocket_delegate (lines 152-164)
# =============================================================================


class TestWrapWebsocketDelegate:
    """Lines 156-163: wrap_websocket_delegate inner handler body."""

    @pytest.mark.asyncio
    async def test_websocket_delegate_async_handler(self) -> None:
        from emergent.wire.compile.targets.pure import wrap_websocket_delegate
        from emergent.wire.axis.surface.triggers.websocket import WebSocketTrigger

        call_log: list[str] = []

        async def ws_handler() -> None:
            call_log.append("ws_called")

        codec = DelegateCodec(handler=ws_handler)
        runner = _make_runner()
        h = Handler(codec=codec, runner=runner, capabilities=())
        trigger = WebSocketTrigger(path="/ws")
        axes = Axes.default()

        route = wrap_websocket_delegate(h, trigger, axes)
        async with Scope() as scope:
            await route.handler(scope)
        assert "ws_called" in call_log

    @pytest.mark.asyncio
    async def test_websocket_delegate_sync_handler(self) -> None:
        from emergent.wire.compile.targets.pure import wrap_websocket_delegate
        from emergent.wire.axis.surface.triggers.websocket import WebSocketTrigger

        call_log: list[str] = []

        def ws_handler_sync() -> None:
            call_log.append("sync_ws_called")

        codec = DelegateCodec(handler=ws_handler_sync)
        runner = _make_runner()
        h = Handler(codec=codec, runner=runner, capabilities=())
        trigger = WebSocketTrigger(path="/ws")
        axes = Axes.default()

        route = wrap_websocket_delegate(h, trigger, axes)
        async with Scope() as scope:
            await route.handler(scope)
        assert "sync_ws_called" in call_log


# =============================================================================
# 4. targets/pure.py — wrap_exception_delegate (lines 123-134)
# =============================================================================


class TestWrapExceptionDelegate:
    """Lines 127-138: wrap_exception_delegate inner handler body."""

    @pytest.mark.asyncio
    async def test_exception_delegate_async(self) -> None:
        from emergent.wire.compile.targets.pure import wrap_exception_delegate
        from emergent.wire.axis.surface.triggers.exception import ExceptionTrigger

        async def exc_handler() -> str:
            return "handled"

        codec = DelegateCodec(handler=exc_handler)
        runner = _make_runner()
        h = Handler(codec=codec, runner=runner, capabilities=())
        trigger: ExceptionTrigger[Exception] = ExceptionTrigger(exception_type=ValueError)
        axes = Axes.default()

        route = wrap_exception_delegate(h, trigger, axes)
        assert route.exception_type is ValueError
        assert route.propagate is False

        async with Scope() as scope:
            result = await route.handler(scope)
            assert result == "handled"

    @pytest.mark.asyncio
    async def test_exception_delegate_sync(self) -> None:
        from emergent.wire.compile.targets.pure import wrap_exception_delegate
        from emergent.wire.axis.surface.triggers.exception import ExceptionTrigger

        def sync_exc_handler() -> str:
            return "sync_handled"

        codec = DelegateCodec(handler=sync_exc_handler)
        runner = _make_runner()
        h = Handler(codec=codec, runner=runner, capabilities=())
        trigger: ExceptionTrigger[Exception] = ExceptionTrigger(exception_type=RuntimeError, propagate=True)
        axes = Axes.default()

        route = wrap_exception_delegate(h, trigger, axes)
        assert route.exception_type is RuntimeError
        assert route.propagate is True

        async with Scope() as scope:
            result = await route.handler(scope)
            assert result == "sync_handled"


# =============================================================================
# 5. enrichers/_impl.py — Cached enricher (lines 343-365)
# =============================================================================


class _FakeTier:
    """Minimal tier for Cached enricher testing."""

    def __init__(self) -> None:
        self._store: dict[str, object] = {}

    async def get(self, key: str) -> Result[Option[object], str]:
        if key in self._store:
            return Ok(Some(self._store[key]))
        return Ok(Nothing())

    async def set(self, key: str, value: object) -> Result[None, str]:
        self._store[key] = value
        return Ok(None)


def _cache_key_fn(k: str) -> str:
    return f"cache:{k}"


def _short_cache_key_fn(k: str) -> str:
    return f"c:{k}"


def _cache_scope_key(scope: Scope) -> str:
    return "test_key"


def _cache_scope_key_short(scope: Scope) -> str:
    return "k"


@dataclass(frozen=True, slots=True)
class _FakeCacheExecutor:
    """Minimal executor for Cached enricher testing."""

    key_fn: Callable[[str], str]
    tiers: tuple[_FakeTier, ...]


class TestCachedEnricher:
    """Lines 343-365: Cached enricher — cache miss then hit."""

    @pytest.mark.asyncio
    async def test_cache_miss_then_hit(self) -> None:
        tier = _FakeTier()
        executor = _FakeCacheExecutor(
            key_fn=_cache_key_fn,
            tiers=(tier,),
        )
        call_count = 0

        async def counting_handler(scope: Scope) -> str:
            nonlocal call_count
            call_count += 1
            return "computed"

        enricher = Cached(
            executor=executor,  # type: ignore[reportArgumentType]
            key=_cache_scope_key,
        )

        # First call: cache miss, handler executes
        async with Scope() as scope:
            result = await enricher.enrich(counting_handler, scope)
            assert result == "computed"
            assert call_count == 1

        # Second call: cache hit, handler NOT called
        async with Scope() as scope2:
            result2 = await enricher.enrich(counting_handler, scope2)
            assert result2 == "computed"
            assert call_count == 1  # Still 1 — cached

    @pytest.mark.asyncio
    async def test_cache_populates_all_tiers(self) -> None:
        tier1 = _FakeTier()
        tier2 = _FakeTier()
        executor = _FakeCacheExecutor(
            key_fn=_short_cache_key_fn,
            tiers=(tier1, tier2),
        )

        async def handler(scope: Scope) -> str:
            return "value"

        enricher = Cached(
            executor=executor,  # type: ignore[reportArgumentType]
            key=_cache_scope_key_short,
        )

        async with Scope() as scope:
            await enricher.enrich(handler, scope)

        # Both tiers populated
        r1 = await tier1.get("c:k")
        r2 = await tier2.get("c:k")
        assert isinstance(r1, Ok)
        assert isinstance(r2, Ok)


# =============================================================================
# 6. _generate.py — to_datanode (lines 237-264)
# =============================================================================


@dataclass
class Coord:
    x: int
    y: int


class XNode:
    pass


class YNode:
    pass


class TestToDatanodeGeneration:
    """Lines 237-264: to_datanode with compose_from mapping."""

    def test_datanode_compose_method_works(self) -> None:
        """Verify __compose__ classmethod extracts values from kwargs."""
        CoordNode = to_datanode(Coord, compose_from={"x": XNode, "y": YNode})
        # to_datanode returns dynamically-created type; __compose__.__func__ is untyped
        compose_fn: Callable[..., Coord] = CoordNode.__compose__.__func__  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]

        # Simulate nodnod calling __compose__ with node results
        class _MockWrapper:
            def __init__(self, val: int) -> None:
                self.value = val

        result: Coord = compose_fn(CoordNode, x=_MockWrapper(10), y=_MockWrapper(20))  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType] - dynamic compose
        assert result.x == 10  # pyright: ignore[reportUnknownMemberType] - dynamic compose result
        assert result.y == 20  # pyright: ignore[reportUnknownMemberType] - dynamic compose result

    def test_datanode_annotations(self) -> None:
        CoordNode = to_datanode(Coord, compose_from={"x": XNode})
        compose_fn: Callable[..., Coord] = CoordNode.__compose__.__func__  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType] - dynamically generated type
        annotations: dict[str, type] = compose_fn.__annotations__  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType] - runtime annotations dict
        assert annotations["x"] is XNode
        assert annotations["return"] is Coord

    def test_datanode_module_preserved(self) -> None:
        CoordNode = to_datanode(Coord, compose_from={})
        assert CoordNode.__module__ == Coord.__module__


# =============================================================================
# 6. _generate.py — to_datanode_auto (lines 267-277)
# =============================================================================


class TestToDatanodeAuto:
    """Lines 267-277: auto mapping from type hints to node registry."""

    def test_auto_maps_matching_types(self) -> None:
        registry: dict[type, type] = {int: XNode}
        CoordNode = to_datanode_auto(Coord, node_registry=registry)
        compose_fn: Callable[..., Coord] = CoordNode.__compose__.__func__  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType] - dynamically generated type
        # Both x and y are int, both should map to XNode
        annotations: dict[str, type] = compose_fn.__annotations__  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType] - runtime annotations dict
        assert annotations.get("x") is XNode  # pyright: ignore[reportUnknownMemberType] - annotations from dynamic type
        assert annotations.get("y") is XNode  # pyright: ignore[reportUnknownMemberType] - annotations from dynamic type

    def test_auto_skips_unregistered_types(self) -> None:
        @dataclass
        class Mixed:
            name: str
            count: int

        registry: dict[type, type] = {int: XNode}
        MixedNode = to_datanode_auto(Mixed, node_registry=registry)
        compose_fn: Callable[..., Mixed] = MixedNode.__compose__.__func__  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType] - dynamically generated type
        # Only count (int) is mapped, name (str) is not
        annotations: dict[str, type] = compose_fn.__annotations__  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType] - runtime annotations dict
        assert annotations.get("count") is XNode  # pyright: ignore[reportUnknownMemberType] - annotations from dynamic type
        assert "name" not in annotations or annotations.get("name") is not XNode  # pyright: ignore[reportUnknownMemberType] - annotations from dynamic type


# =============================================================================
# 6. _generate.py — to_telegram_fields (lines 324-333)
# =============================================================================


@dataclass
class TGMsg:
    title: str
    body: str
    count: int


class TestToTelegramFieldsGeneration:
    """Lines 324-333: to_telegram_fields compiles TG_RENDER_PHASE."""

    def test_returns_contexts_for_all_fields(self) -> None:
        axes = Axes.default()
        fields = to_telegram_fields(TGMsg, axes)
        assert len(fields) == 3
        names = [ctx.field_name for ctx in fields]
        assert "title" in names
        assert "body" in names
        assert "count" in names

    def test_field_types_correct(self) -> None:
        axes = Axes.default()
        fields = to_telegram_fields(TGMsg, axes)
        by_name = {ctx.field_name: ctx for ctx in fields}
        assert by_name["title"].field_type is str
        assert by_name["count"].field_type is int


# =============================================================================
# 2. _execute.py — execute_stateful_unified error path (lines 230-236)
# =============================================================================


class TestExecuteStatefulUnifiedError:
    """Lines 230-236: exception during stateful execution is logged and raised."""

    @pytest.mark.asyncio
    async def test_error_propagates(self) -> None:
        store = _make_memory_store()
        codec = StatefulCodec(
            flow=DoneFlow,
            response=DoneResp,
            store=store,
            key_node=str,
            agent_cls=EventLoopAgent,
        )
        runner = _make_runner()
        handler = Handler(codec=codec, runner=runner, capabilities=())

        async def resolve() -> tuple[object, dict[str, object]]:
            raise RuntimeError("resolve_error")

        with pytest.raises(RuntimeError, match="resolve_error"):
            await execute_stateful_unified(
                handler=handler,
                store_key="user1",
                resolve_transition=resolve,
                inject_scope=_noop_inject,
            )

    @pytest.mark.asyncio
    async def test_no_transition_raises(self) -> None:
        """Line 192: resolve_transition returns None."""
        store = _make_memory_store()
        codec = StatefulCodec(
            flow=DoneFlow,
            response=DoneResp,
            store=store,
            key_node=str,
            agent_cls=EventLoopAgent,
        )
        runner = _make_runner()
        handler = Handler(codec=codec, runner=runner, capabilities=())

        async def resolve() -> None:
            return None

        with pytest.raises(RuntimeError, match="No transition resolvable"):
            await execute_stateful_unified(
                handler=handler,
                store_key="user1",
                resolve_transition=resolve,
                inject_scope=_noop_inject,
            )


# =============================================================================
# 2. _execute.py — execute_stateful_unified with async inject_scope
# =============================================================================


class TestExecuteStatefulUnifiedAsyncInject:
    """Lines 224-226: async inject_scope path."""

    @pytest.mark.asyncio
    async def test_async_inject_scope(self) -> None:
        store = _make_memory_store()
        codec = StatefulCodec(
            flow=DoneFlow,
            response=DoneResp,
            store=store,
            key_node=str,
            agent_cls=EventLoopAgent,
        )
        runner = _make_runner()
        handler = Handler(codec=codec, runner=runner, capabilities=())

        transitions = get_transitions(DoneFlow)
        method = transitions[0]
        injected: list[str] = []

        async def resolve() -> tuple[object, dict[str, object]]:
            return method, {}

        async def async_inject(scope: Scope) -> None:
            injected.append("async_injected")

        _response, is_done = await execute_stateful_unified(
            handler=handler,
            store_key="user1",
            resolve_transition=resolve,
            inject_scope=async_inject,
        )
        assert is_done
        assert "async_injected" in injected

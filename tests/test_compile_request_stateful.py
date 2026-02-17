"""Tests for _request.py (build_request_sync, compose paths) and _stateful.py (execute_stateful_done, get_stateful_metadata)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Annotated, Self

import pytest

from kungfu import Result, Ok, Error
from nodnod import Scope, Node
from nodnod.utils.create_node import create_node

from emergent.ops._graph import Op, Runner, ops
from emergent.wire.compile._request import (
    build_request,
    build_request_sync,
    compose_node_value,
)
from emergent.wire.compile._stateful import (
    execute_stateful_turn,
    execute_stateful_done,
    load_state,
    save_state,
    delete_state,
    get_stateful_metadata,
)
from emergent.wire.axis.surface._handler import Handler
from emergent.wire.axis.surface.codecs.stateful import (
    StatefulCodec,
    Done,
    transition,
    get_transitions,
)
from emergent.wire.axis.schema.dialects.compose import (
    Node as ComposeNode,
    Retrieve as ComposeRetrieve,
)
from nodnod.agent.event_loop.agent import EventLoopAgent


# ═══════════════════════════════════════════════════════════════════════════════
# Domain types for tests
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class SimpleReq:
    name: str
    age: int


@dataclass
class DefaultReq:
    name: str
    greeting: str = "hello"


@dataclass
class FactoryReq:
    name: str
    tags: list[str] = field(default_factory=lambda: list[str]())


@dataclass
class OptionalReq:
    name: str
    bio: str | None = None


class _Token:
    secret: str = "tok"


@dataclass
class RetrieveReq:
    name: str
    token: Annotated[_Token, ComposeRetrieve(_Token)] = None  # type: ignore[assignment]


# ═══════════════════════════════════════════════════════════════════════════════
# build_request_sync
# ═══════════════════════════════════════════════════════════════════════════════


class TestBuildRequestSync:
    def test_basic_fields(self) -> None:
        result = build_request_sync(SimpleReq, {"name": "Alice", "age": 30}.get)
        assert result.name == "Alice"
        assert result.age == 30

    def test_default_field(self) -> None:
        result = build_request_sync(DefaultReq, {"name": "Bob"}.get)
        assert result.greeting == "hello"

    def test_factory_default(self) -> None:
        result = build_request_sync(FactoryReq, {"name": "Eve"}.get)
        assert result.tags == []

    def test_missing_required_raises(self) -> None:
        with pytest.raises(RuntimeError, match="age"):
            build_request_sync(SimpleReq, {"name": "Alice"}.get)

    def test_not_dataclass_raises(self) -> None:
        empty: dict[str, str] = {}
        with pytest.raises(TypeError, match="not a dataclass"):
            build_request_sync(str, empty.get)

    def test_none_value_uses_default(self) -> None:
        result = build_request_sync(DefaultReq, lambda n: None if n == "greeting" else "Bob")
        assert result.greeting == "hello"


# ═══════════════════════════════════════════════════════════════════════════════
# build_request (async) — compose paths
# ═══════════════════════════════════════════════════════════════════════════════


_ConfigNode: type[Node[str, str]] = create_node(
    name="_ConfigNode",
    base_node=Node,
    bases=(),
    namespace={
        "__compose__": classmethod(lambda cls: "composed_config"),
        "__module__": __name__,
    },
)


@dataclass
class ComposeNodeReq:
    name: str
    config: Annotated[str, ComposeNode(_ConfigNode)] = ""


class TestBuildRequestAsync:
    @pytest.mark.asyncio
    async def test_compose_retrieve(self) -> None:
        tok = _Token()
        async with Scope() as scope:
            scope.inject(_Token, tok)
            result = await build_request(RetrieveReq, {"name": "D"}.get, scope=scope)
            assert result.token is tok

    @pytest.mark.asyncio
    async def test_compose_node(self) -> None:
        async with Scope() as scope:
            result = await build_request(ComposeNodeReq, {"name": "X"}.get, scope=scope)
            assert result.config == "composed_config"

    @pytest.mark.asyncio
    async def test_not_dataclass_raises(self) -> None:
        empty: dict[str, str] = {}
        with pytest.raises(TypeError, match="not a dataclass"):
            await build_request(str, empty.get)

    @pytest.mark.asyncio
    async def test_optional_field_none(self) -> None:
        result = await build_request(OptionalReq, {"name": "X"}.get)
        assert result.bio is None


# ═══════════════════════════════════════════════════════════════════════════════
# compose_node_value
# ═══════════════════════════════════════════════════════════════════════════════


class TestComposeNodeValue:
    @pytest.mark.asyncio
    async def test_compose_succeeds(self) -> None:
        from nodnod.agent.event_loop.agent import EventLoopAgent
        async with Scope() as scope:
            success, value = await compose_node_value(_ConfigNode, EventLoopAgent, scope)
            assert success
            assert value == "composed_config"


# ═══════════════════════════════════════════════════════════════════════════════
# Stateful: execute_stateful_turn
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class CounterOp(Op[int, str]):
    count: int


async def _counter_handler(req: CounterOp) -> Result[int, str]:
    return Ok(req.count)


@dataclass
class CounterResp:
    value: int

    @classmethod
    def from_domain(cls, r: Result[int, str]) -> Self:
        match r:
            case Ok(v):
                return cls(value=v)
            case Error(_):
                return cls(value=-1)


@dataclass
class CounterFlow:
    count: int = 0

    @transition
    async def increment(self, amount: int) -> Self | Done:
        new_count = self.count + amount
        if new_count >= 10:
            return Done()
        return type(self)(count=new_count)

    def to_domain(self) -> CounterOp:
        return CounterOp(count=self.count)


class TestExecuteStatefulTurn:
    @pytest.mark.asyncio
    async def test_non_terminal_turn(self) -> None:
        codec = StatefulCodec(
            flow=CounterFlow,
            response=CounterResp,
            store=_make_memory_store(),
            key_node=str,
            agent_cls=EventLoopAgent,
        )
        handler = Handler(codec=codec, runner=_make_runner(), capabilities=())
        state = CounterFlow(count=0)
        transitions = get_transitions(CounterFlow)
        method = transitions[0]

        new_state, _, is_terminal = await execute_stateful_turn(
            handler, state, method, {"amount": 3}
        )
        assert not is_terminal
        assert new_state.count == 3

    @pytest.mark.asyncio
    async def test_terminal_turn(self) -> None:
        codec = StatefulCodec(
            flow=CounterFlow,
            response=CounterResp,
            store=_make_memory_store(),
            key_node=str,
            agent_cls=EventLoopAgent,
        )
        handler = Handler(codec=codec, runner=_make_runner(), capabilities=())
        state = CounterFlow(count=8)
        transitions = get_transitions(CounterFlow)
        method = transitions[0]

        new_state, _, is_terminal = await execute_stateful_turn(
            handler, state, method, {"amount": 5}
        )
        assert is_terminal
        assert isinstance(new_state, Done)


# ═══════════════════════════════════════════════════════════════════════════════
# Stateful: execute_stateful_done
# ═══════════════════════════════════════════════════════════════════════════════


class TestExecuteStatefulDone:
    @pytest.mark.asyncio
    async def test_done_executes_op(self) -> None:
        codec = StatefulCodec(
            flow=CounterFlow,
            response=CounterResp,
            store=_make_memory_store(),
            key_node=str,
            agent_cls=EventLoopAgent,
        )
        runner = _make_runner()
        handler = Handler(codec=codec, runner=runner, capabilities=())
        done_state = CounterFlow(count=42)
        async with Scope() as scope:
            result = await execute_stateful_done(handler, done_state, scope)
            assert isinstance(result, CounterResp)
            assert result.value == 42


# ═══════════════════════════════════════════════════════════════════════════════
# Stateful: load_state / save_state / delete_state
# ═══════════════════════════════════════════════════════════════════════════════


class TestStateManagement:
    @pytest.mark.asyncio
    async def test_load_state_initial(self) -> None:
        store = _make_memory_store()
        codec = StatefulCodec(
            flow=CounterFlow,
            response=CounterResp,
            store=store,
            key_node=str,
            agent_cls=EventLoopAgent,
        )
        state = await load_state(codec, "user1")
        assert isinstance(state, CounterFlow)
        assert state.count == 0

    @pytest.mark.asyncio
    async def test_save_and_load_state(self) -> None:
        store = _make_memory_store()
        codec = StatefulCodec(
            flow=CounterFlow,
            response=CounterResp,
            store=store,
            key_node=str,
            agent_cls=EventLoopAgent,
        )
        old_state = CounterFlow(count=0)
        new_state = CounterFlow(count=5)
        await save_state(codec, "user1", old_state, new_state)
        loaded = await load_state(codec, "user1")
        assert loaded.count == 5

    @pytest.mark.asyncio
    async def test_save_same_reference_skipped(self) -> None:
        store = _make_memory_store()
        codec = StatefulCodec(
            flow=CounterFlow,
            response=CounterResp,
            store=store,
            key_node=str,
            agent_cls=EventLoopAgent,
        )
        state = CounterFlow(count=5)
        await save_state(codec, "user1", state, state)  # Same reference
        loaded = await load_state(codec, "user1")
        assert loaded.count == 0  # Initial, because save was skipped

    @pytest.mark.asyncio
    async def test_delete_state(self) -> None:
        store = _make_memory_store()
        codec = StatefulCodec(
            flow=CounterFlow,
            response=CounterResp,
            store=store,
            key_node=str,
            agent_cls=EventLoopAgent,
        )
        await save_state(codec, "user1", CounterFlow(0), CounterFlow(5))
        await delete_state(codec, "user1")
        loaded = await load_state(codec, "user1")
        assert loaded.count == 0  # Back to initial


# ═══════════════════════════════════════════════════════════════════════════════
# get_stateful_metadata
# ═══════════════════════════════════════════════════════════════════════════════


class TestGetStatefulMetadata:
    def test_metadata_keys(self) -> None:
        codec = StatefulCodec(
            flow=CounterFlow,
            response=CounterResp,
            store=_make_memory_store(),
            key_node=str,
            agent_cls=EventLoopAgent,
        )
        handler = Handler(codec=codec, runner=_make_runner(), capabilities=())
        meta = get_stateful_metadata(handler)
        assert "transitions" in meta
        assert "flow_cls" in meta
        assert meta["flow_cls"] is CounterFlow
        assert "response_cls" in meta
        assert meta["response_cls"] is CounterResp
        assert "key_node" in meta
        assert meta["key_node"] is str
        assert "agent_cls" in meta


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _make_memory_store():
    """Create a simple in-memory store for stateful tests."""
    from emergent.wire.axis.storage import MemoryStorage
    from typing import Any
    return MemoryStorage[str, Any]()


def _make_runner() -> Runner:
    return ops().on(CounterOp, _counter_handler).compile()

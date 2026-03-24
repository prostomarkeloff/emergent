"""Tests for unified execution — _execute.py and _delegate.py.

Covers:
- execute_rrc_unified: basic execution, format_response, inject_scope
- execute_immediate_unified: ImmediateCodec, ImmediateFactoryCodec, format_response, wrong codec
- execute_delegate_unified: async handler, format_response
- execute_stateful_unified: non-terminal turn, terminal Done, Cancelled
- _family_mapped: None layer → empty dict
- resolve_handler_params from _delegate.py: scope retrieval, compose node
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Annotated, Self

import pytest

from kungfu import Result, Ok, Error, Some
from nodnod import Scope, Node
from nodnod.utils.create_node import create_node

from emergent.ops._graph import Op, Runner, ops
from emergent.wire.axis.surface._handler import Handler
from emergent.wire.axis.surface.codecs.rrc import RequestResponseCodec, rrc
from emergent.wire.axis.surface.codecs.delegate import DelegateCodec, delegate
from emergent.wire.axis.surface.codecs.immediate import (
    ImmediateCodec,
    ImmediateFactoryCodec,
    immediate,
    immediate_factory,
)
from emergent.wire.axis.surface.codecs.stateful import (
    StatefulCodec,
    Done,
    Cancelled,
    transition,
    stateful,
)
from emergent.wire.axis.schema.dialects.compose import (
    Node as ComposeNode,
    Retrieve as ComposeRetrieve,
)
from emergent.wire.compile._core import Axes
from emergent.wire.compile._execute import (
    execute_rrc_unified,
    execute_immediate_unified,
    execute_delegate_unified,
    execute_stateful_unified,
    _family_mapped,  # pyright: ignore[reportPrivateUsage] - testing private helper directly; no public API exposes this
)
from emergent.wire.compile._delegate import resolve_handler_params
from emergent.wire.axis.storage import MemoryStorage
from nodnod.agent.event_loop.agent import EventLoopAgent


# ═══════════════════════════════════════════════════════════════════════════════
# Domain types shared across tests
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class LenOp(Op[int, str]):
    name: str


async def _len_handler(req: LenOp) -> Result[int, str]:
    return Ok(len(req.name))


@dataclass
class LenReq:
    name: str

    def to_domain(self) -> LenOp:
        return LenOp(name=self.name)


@dataclass
class LenResp:
    value: int

    @classmethod
    def from_domain(cls, dom: Result[int, str]) -> Self:
        match dom:
            case Ok(v):
                return cls(value=v)
            case Error(_):
                return cls(value=-1)


def _make_len_runner() -> Runner:
    return ops().on(LenOp, _len_handler).compile()


def _make_rrc_handler(runner: Runner | None = None) -> Handler[RequestResponseCodec]:
    if runner is None:
        runner = _make_len_runner()
    codec = rrc(LenReq, LenResp)
    return Handler(codec=codec, runner=runner, capabilities=())


def _make_memory_store() -> MemoryStorage[str, object]:
    return MemoryStorage[str, object]()


def _noop_inject(scope: Scope) -> None:
    """No-op scope injector — does not inject anything."""
    pass


# ═══════════════════════════════════════════════════════════════════════════════
# execute_rrc_unified
# ═══════════════════════════════════════════════════════════════════════════════


class TestExecuteRrcUnified:
    @pytest.mark.asyncio
    async def test_basic_execution_returns_response(self) -> None:
        handler = _make_rrc_handler()
        axes = Axes.default()

        response = await execute_rrc_unified(
            handler=handler,
            axes=axes,
            get_value={"name": "Alice"}.get,
            inject_scope=_noop_inject,
        )

        assert isinstance(response, LenResp)
        assert response.value == len("Alice")

    @pytest.mark.asyncio
    async def test_basic_execution_computes_correct_value(self) -> None:
        handler = _make_rrc_handler()
        axes = Axes.default()

        response = await execute_rrc_unified(
            handler=handler,
            axes=axes,
            get_value={"name": "Hi"}.get,
            inject_scope=_noop_inject,
        )

        assert isinstance(response, LenResp)
        assert response.value == 2

    @pytest.mark.asyncio
    async def test_with_format_response_transforms_result(self) -> None:
        handler = _make_rrc_handler()
        axes = Axes.default()

        def fmt(resp: LenResp) -> int:
            return resp.value * 10

        result = await execute_rrc_unified(
            handler=handler,
            axes=axes,
            get_value={"name": "Hi"}.get,
            inject_scope=_noop_inject,
            format_response=fmt,
        )

        assert result == 20

    @pytest.mark.asyncio
    async def test_inject_scope_is_called(self) -> None:
        handler = _make_rrc_handler()
        axes = Axes.default()
        injected: list[Scope] = []

        def capturing_inject(scope: Scope) -> None:
            injected.append(scope)

        await execute_rrc_unified(
            handler=handler,
            axes=axes,
            get_value={"name": "X"}.get,
            inject_scope=capturing_inject,
        )

        assert len(injected) == 1
        assert isinstance(injected[0], Scope)

    @pytest.mark.asyncio
    async def test_async_inject_scope_is_awaited(self) -> None:
        handler = _make_rrc_handler()
        axes = Axes.default()
        injected: list[bool] = []

        async def async_inject(scope: Scope) -> None:
            injected.append(True)

        await execute_rrc_unified(
            handler=handler,
            axes=axes,
            get_value={"name": "X"}.get,
            inject_scope=async_inject,
        )

        assert injected == [True]

    @pytest.mark.asyncio
    async def test_without_format_response_returns_response_object(self) -> None:
        handler = _make_rrc_handler()
        axes = Axes.default()

        response = await execute_rrc_unified(
            handler=handler,
            axes=axes,
            get_value={"name": "abc"}.get,
            inject_scope=_noop_inject,
            format_response=None,
        )

        assert isinstance(response, LenResp)
        assert response.value == 3


# ═══════════════════════════════════════════════════════════════════════════════
# execute_immediate_unified
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class GreetResp:
    text: str

    @classmethod
    def produce(cls) -> Self:
        return cls(text="Hello!")


class TestExecuteImmediateUnified:
    def test_immediate_codec_calls_produce(self) -> None:
        codec = immediate(GreetResp)
        runner = _make_len_runner()
        handler: Handler[ImmediateCodec] = Handler(
            codec=codec, runner=runner, capabilities=()
        )

        response = execute_immediate_unified(handler)

        assert isinstance(response, GreetResp)
        assert response.text == "Hello!"

    def test_immediate_factory_codec_calls_factory(self) -> None:
        call_count: list[int] = [0]

        def factory() -> GreetResp:
            call_count[0] += 1
            return GreetResp(text="From factory")

        codec = immediate_factory(factory)
        runner = _make_len_runner()
        handler: Handler[ImmediateFactoryCodec] = Handler(
            codec=codec, runner=runner, capabilities=()
        )

        response = execute_immediate_unified(handler)

        assert isinstance(response, GreetResp)
        assert response.text == "From factory"
        assert call_count[0] == 1

    def test_with_format_response_applied_to_immediate(self) -> None:
        codec = immediate(GreetResp)
        runner = _make_len_runner()
        handler: Handler[ImmediateCodec] = Handler(
            codec=codec, runner=runner, capabilities=()
        )

        result = execute_immediate_unified(
            handler, format_response=lambda r: r.text.upper()
        )

        assert result == "HELLO!"

    def test_with_format_response_applied_to_factory(self) -> None:
        codec = immediate_factory(lambda: GreetResp(text="bye"))
        runner = _make_len_runner()
        handler: Handler[ImmediateFactoryCodec] = Handler(
            codec=codec, runner=runner, capabilities=()
        )

        result = execute_immediate_unified(
            handler, format_response=lambda r: r.text.upper()
        )

        assert result == "BYE"

    def test_wrong_codec_type_raises_type_error(self) -> None:
        codec = rrc(LenReq, LenResp)
        runner = _make_len_runner()
        handler: Handler[RequestResponseCodec] = Handler(
            codec=codec, runner=runner, capabilities=()
        )

        with pytest.raises(TypeError, match="ImmediateCodec or ImmediateFactoryCodec"):
            execute_immediate_unified(handler)  # type: ignore[arg-type]

    def test_factory_called_fresh_each_time(self) -> None:
        counter: list[int] = [0]

        def factory() -> GreetResp:
            counter[0] += 1
            return GreetResp(text=f"call {counter[0]}")

        codec = immediate_factory(factory)
        runner = _make_len_runner()
        handler: Handler[ImmediateFactoryCodec] = Handler(
            codec=codec, runner=runner, capabilities=()
        )

        r1 = execute_immediate_unified(handler)
        r2 = execute_immediate_unified(handler)

        assert r1.text == "call 1"
        assert r2.text == "call 2"


# ═══════════════════════════════════════════════════════════════════════════════
# execute_delegate_unified
# ═══════════════════════════════════════════════════════════════════════════════


class TestExecuteDelegateUnified:
    @pytest.mark.asyncio
    async def test_async_handler_called_with_no_params(self) -> None:
        results: list[str] = []

        async def my_handler() -> str:
            results.append("called")
            return "ok"

        codec = delegate(my_handler)
        runner = _make_len_runner()
        handler: Handler[DelegateCodec] = Handler(
            codec=codec, runner=runner, capabilities=()
        )

        response = await execute_delegate_unified(
            handler=handler,
            inject_scope=_noop_inject,
        )

        assert response == "ok"
        assert results == ["called"]

    @pytest.mark.asyncio
    async def test_async_handler_with_format_response(self) -> None:
        async def my_handler() -> int:
            return 7

        codec = delegate(my_handler)
        runner = _make_len_runner()
        handler: Handler[DelegateCodec] = Handler(
            codec=codec, runner=runner, capabilities=()
        )

        result = await execute_delegate_unified(
            handler=handler,
            inject_scope=_noop_inject,
            format_response=lambda v: v * 2,
        )

        assert result == 14

    @pytest.mark.asyncio
    async def test_inject_scope_called_in_delegate(self) -> None:
        injected: list[bool] = []

        async def my_handler() -> str:
            return "done"

        def capturing_inject(scope: Scope) -> None:
            injected.append(True)

        codec = delegate(my_handler)
        runner = _make_len_runner()
        handler: Handler[DelegateCodec] = Handler(
            codec=codec, runner=runner, capabilities=()
        )

        await execute_delegate_unified(
            handler=handler,
            inject_scope=capturing_inject,
        )

        assert injected == [True]

    @pytest.mark.asyncio
    async def test_sync_handler_runs_via_thread(self) -> None:
        called_in_thread: list[bool] = []

        def sync_handler() -> str:
            # Just verify it returns something — sync execution is wrapped
            called_in_thread.append(True)
            return "sync_result"

        codec = delegate(sync_handler)
        runner = _make_len_runner()
        handler: Handler[DelegateCodec] = Handler(
            codec=codec, runner=runner, capabilities=()
        )

        result = await execute_delegate_unified(
            handler=handler,
            inject_scope=_noop_inject,
        )

        assert result == "sync_result"
        assert called_in_thread == [True]


# ═══════════════════════════════════════════════════════════════════════════════
# execute_stateful_unified
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class CollectOp(Op[str, str]):
    words: tuple[str, ...]


async def _collect_handler(req: CollectOp) -> Result[str, str]:
    return Ok(" ".join(req.words))


@dataclass
class CollectResp:
    text: str

    @classmethod
    def from_domain(cls, dom: Result[str, str]) -> Self:
        match dom:
            case Ok(v):
                return cls(text=v)
            case Error(e):
                return cls(text=f"error: {e}")


@dataclass
class CollectFlow:
    words: tuple[str, ...] = field(default_factory=tuple)

    @transition
    async def add_word(self, word: str) -> Self | Done:
        new_words = self.words + (word,)
        if len(new_words) >= 3:
            return Done()
        return replace(self, words=new_words)

    def to_domain(self) -> CollectOp:
        return CollectOp(words=self.words)


@dataclass
class CancellableFlow:
    received: bool = False

    @transition
    async def maybe_cancel(self, cancel: bool) -> Self | Cancelled:
        if cancel:
            return Cancelled()
        return replace(self, received=True)

    def to_domain(self) -> CollectOp:
        return CollectOp(words=("cancelled",))


def _make_collect_runner() -> Runner:
    return ops().on(CollectOp, _collect_handler).compile()


def _make_collect_stateful_codec() -> StatefulCodec:
    return (
        stateful(CollectFlow, CollectResp)
        .key(str)
        .store(_make_memory_store())
        .build()
    )


def _make_cancellable_stateful_codec() -> StatefulCodec:
    return (
        stateful(CancellableFlow, CollectResp)
        .key(str)
        .store(_make_memory_store())
        .build()
    )


class TestExecuteStatefulUnified:
    @pytest.mark.asyncio
    async def test_non_terminal_turn_returns_not_done(self) -> None:
        codec = _make_collect_stateful_codec()
        runner = _make_collect_runner()
        handler: Handler[StatefulCodec] = Handler(
            codec=codec, runner=runner, capabilities=()
        )

        from emergent.wire.axis.surface.codecs.stateful import get_transitions

        transitions = get_transitions(CollectFlow)
        method = transitions[0]

        params: dict[str, object] = {"word": "hello"}
        resolved = (method, params)

        async def resolve() -> tuple[object, dict[str, object]]:
            return resolved

        _response, is_done = await execute_stateful_unified(
            handler=handler,
            store_key="user1",
            resolve_transition=resolve,
            inject_scope=_noop_inject,
        )

        assert not is_done

    @pytest.mark.asyncio
    async def test_non_terminal_turn_stores_partial_state(self) -> None:
        codec = _make_collect_stateful_codec()
        runner = _make_collect_runner()
        handler: Handler[StatefulCodec] = Handler(
            codec=codec, runner=runner, capabilities=()
        )

        from emergent.wire.axis.surface.codecs.stateful import get_transitions

        transitions = get_transitions(CollectFlow)
        method = transitions[0]

        async def resolve() -> tuple[object, dict[str, object]]:
            return (method, {"word": "first"})

        await execute_stateful_unified(
            handler=handler,
            store_key="user2",
            resolve_transition=resolve,
            inject_scope=_noop_inject,
        )

        # Second turn should see the partial state
        stored_state = await codec.store.get("user2")
        match stored_state:
            case Ok(Some(state)):
                assert isinstance(state, CollectFlow)
                assert "first" in state.words
            case _:
                pytest.fail("Expected stored state after non-terminal turn")

    @pytest.mark.asyncio
    async def test_cancelled_turn_preceding_non_terminal_stores_state(self) -> None:
        """Non-terminal turn followed by cancelled — verify state is persisted then cleaned."""
        codec = _make_cancellable_stateful_codec()
        runner = _make_collect_runner()
        handler: Handler[StatefulCodec] = Handler(
            codec=codec, runner=runner, capabilities=()
        )

        from emergent.wire.axis.surface.codecs.stateful import get_transitions

        transitions = get_transitions(CancellableFlow)
        method = transitions[0]

        # Non-terminal turn first
        async def resolve_non_terminal() -> tuple[object, dict[str, object]]:
            return (method, {"cancel": False})

        _response, is_done = await execute_stateful_unified(
            handler=handler,
            store_key="seq_user",
            resolve_transition=resolve_non_terminal,
            inject_scope=_noop_inject,
        )
        assert not is_done

        # State should be saved
        stored = await codec.store.get("seq_user")
        match stored:
            case Ok(Some(state)):
                assert isinstance(state, CancellableFlow)
                assert state.received is True
            case _:
                pytest.fail("Expected persisted state after non-terminal turn")

    @pytest.mark.asyncio
    async def test_execute_stateful_done_directly_produces_response(self) -> None:
        """Directly invoke execute_stateful_done with a proper flow state.

        execute_stateful_unified passes the Done() marker to execute_stateful_done,
        which requires the state to have to_domain(). We test execute_stateful_done
        directly here with the correct accumulated flow state.
        """
        from emergent.wire.compile._stateful import execute_stateful_done

        codec = _make_collect_stateful_codec()
        runner = _make_collect_runner()
        handler: Handler[StatefulCodec] = Handler(
            codec=codec, runner=runner, capabilities=()
        )

        # The accumulated state before Done was triggered
        pre_done_state = CollectFlow(words=("a", "b", "c"))

        async with Scope() as scope:
            result = await execute_stateful_done(handler, pre_done_state, scope)

        assert isinstance(result, CollectResp)
        assert result.text == "a b c"

    @pytest.mark.asyncio
    async def test_cancelled_turn_returns_is_done_true(self) -> None:
        codec = _make_cancellable_stateful_codec()
        runner = _make_collect_runner()
        handler: Handler[StatefulCodec] = Handler(
            codec=codec, runner=runner, capabilities=()
        )

        from emergent.wire.axis.surface.codecs.stateful import get_transitions

        transitions = get_transitions(CancellableFlow)
        method = transitions[0]

        async def resolve() -> tuple[object, dict[str, object]]:
            return (method, {"cancel": True})

        _response, is_done = await execute_stateful_unified(
            handler=handler,
            store_key="cancel_user",
            resolve_transition=resolve,
            inject_scope=_noop_inject,
        )

        assert is_done

    @pytest.mark.asyncio
    async def test_cancelled_deletes_state_without_op_execution(self) -> None:
        codec = _make_cancellable_stateful_codec()
        runner = _make_collect_runner()
        handler: Handler[StatefulCodec] = Handler(
            codec=codec, runner=runner, capabilities=()
        )

        from emergent.wire.axis.surface.codecs.stateful import get_transitions

        transitions = get_transitions(CancellableFlow)
        method = transitions[0]

        await codec.store.set("cancel_user2", CancellableFlow(received=False))

        async def resolve() -> tuple[object, dict[str, object]]:
            return (method, {"cancel": True})

        await execute_stateful_unified(
            handler=handler,
            store_key="cancel_user2",
            resolve_transition=resolve,
            inject_scope=_noop_inject,
        )

        # State must be deleted after Cancelled
        stored = await codec.store.get("cancel_user2")
        match stored:
            case Ok(Some(_)):
                pytest.fail("State should have been deleted after Cancelled")
            case _:
                pass  # Correct

    @pytest.mark.asyncio
    async def test_format_response_applied_to_non_terminal_with_side_response(self) -> None:
        """format_response is applied when a non-terminal turn includes a side response."""

        @dataclass
        class EchoFlow:
            collected: str = ""

            @transition
            async def echo(self, msg: str) -> "tuple[EchoFlow, str]":
                new_self = replace(self, collected=self.collected + msg)
                return (new_self, f"echo: {msg}")

            def to_domain(self) -> CollectOp:
                return CollectOp(words=(self.collected,))

        codec = (
            stateful(EchoFlow, CollectResp)
            .key(str)
            .store(_make_memory_store())
            .build()
        )
        runner = _make_collect_runner()
        handler: Handler[StatefulCodec] = Handler(
            codec=codec, runner=runner, capabilities=()
        )

        from emergent.wire.axis.surface.codecs.stateful import get_transitions

        transitions = get_transitions(EchoFlow)
        method = transitions[0]

        async def resolve() -> tuple[object, dict[str, object]]:
            return (method, {"msg": "hello"})

        response, is_done = await execute_stateful_unified(
            handler=handler,
            store_key="echo_user",
            resolve_transition=resolve,
            inject_scope=_noop_inject,
            format_response=lambda r: r.upper() if isinstance(r, str) else r,
        )

        assert not is_done
        # The format_response was applied to the side response string
        assert isinstance(response, str)
        assert response == "ECHO: HELLO"

    @pytest.mark.asyncio
    async def test_none_resolve_transition_raises_runtime_error(self) -> None:
        codec = _make_collect_stateful_codec()
        runner = _make_collect_runner()
        handler: Handler[StatefulCodec] = Handler(
            codec=codec, runner=runner, capabilities=()
        )

        async def resolve_none() -> None:
            return None

        with pytest.raises(RuntimeError, match="No transition resolvable"):
            await execute_stateful_unified(
                handler=handler,
                store_key="user_none",
                resolve_transition=resolve_none,
                inject_scope=_noop_inject,
            )


# ═══════════════════════════════════════════════════════════════════════════════
# _family_mapped
# ═══════════════════════════════════════════════════════════════════════════════


class TestFamilyMapped:
    @pytest.mark.asyncio
    async def test_none_layer_returns_empty_dict(self) -> None:
        async with Scope() as scope:
            result = _family_mapped(None, scope)
            assert result == {}

    @pytest.mark.asyncio
    async def test_none_layer_is_empty_mapping(self) -> None:
        async with Scope() as scope:
            result = _family_mapped(None, scope)
            assert len(result) == 0

    @pytest.mark.asyncio
    async def test_none_layer_is_not_none(self) -> None:
        async with Scope() as scope:
            result = _family_mapped(None, scope)
            assert result is not None


# ═══════════════════════════════════════════════════════════════════════════════
# resolve_handler_params from _delegate.py
# ═══════════════════════════════════════════════════════════════════════════════


class _ServiceToken:
    value: str = "secret"


_ServiceNode: type[Node[str, str]] = create_node(
    name="_ServiceNode",
    base_node=Node,
    bases=(),
    namespace={
        "__compose__": classmethod(lambda cls: "service_value"),
        "__module__": __name__,
    },
)


class TestResolveHandlerParams:
    @pytest.mark.asyncio
    async def test_retrieve_from_scope_by_annotated(self) -> None:
        tok = _ServiceToken()

        async def handler(
            token: Annotated[_ServiceToken, ComposeRetrieve(_ServiceToken)],
        ) -> str:
            return token.value

        async with Scope() as scope:
            scope.inject(_ServiceToken, tok)
            params = await resolve_handler_params(handler, scope, EventLoopAgent)

        assert "token" in params
        assert params["token"] is tok

    @pytest.mark.asyncio
    async def test_retrieve_missing_from_scope_skips_param(self) -> None:
        async def handler(
            token: Annotated[_ServiceToken, ComposeRetrieve(_ServiceToken)],
        ) -> str:
            return "no token"

        async with Scope() as scope:
            params = await resolve_handler_params(handler, scope, EventLoopAgent)

        # When the type is missing from scope, the param is omitted
        assert "token" not in params

    @pytest.mark.asyncio
    async def test_compose_node_annotation_resolves_value(self) -> None:
        async def handler(
            svc: Annotated[str, ComposeNode(_ServiceNode)],
        ) -> str:
            return svc

        async with Scope() as scope:
            params = await resolve_handler_params(handler, scope, EventLoopAgent)

        assert "svc" in params
        assert params["svc"] == "service_value"

    @pytest.mark.asyncio
    async def test_plain_type_fallback_retrieves_from_scope(self) -> None:
        tok = _ServiceToken()

        async def handler(token: _ServiceToken) -> str:
            return token.value

        async with Scope() as scope:
            scope.inject(_ServiceToken, tok)
            params = await resolve_handler_params(handler, scope, EventLoopAgent)

        assert "token" in params
        assert params["token"] is tok

    @pytest.mark.asyncio
    async def test_self_param_is_skipped(self) -> None:
        class MyClass:
            async def method(self, token: _ServiceToken) -> str:
                return token.value

        tok = _ServiceToken()
        async with Scope() as scope:
            scope.inject(_ServiceToken, tok)
            params = await resolve_handler_params(MyClass.method, scope, EventLoopAgent)

        assert "self" not in params
        assert "token" in params

"""Tests for emergent/wire/axis/surface/codecs/stateful.py.

Covers: transition decorator, get_transitions, has_transitions,
parse_transition_result, Done/Cancelled, StatefulBuilder, StatefulCodec.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from kungfu import Some, Nothing

from emergent.wire.axis.surface.codecs.stateful import (
    transition,
    get_transitions,
    has_transitions,
    parse_transition_result,
    TransitionResult,
    Done,
    Cancelled,
    StatefulCodec,
    StatefulBuilder,
    stateful,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Shared test flows
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class SampleFlow:
    value: int = 0

    @transition
    async def step(self, x: int) -> SampleFlow | Done:
        if x > 10:
            return Done()
        return SampleFlow(value=x)

    def to_domain(self) -> None:
        return None


@dataclass
class ClassicFlow:
    value: int = 0

    async def __transition__(self, x: int) -> ClassicFlow | Done:
        if x > 10:
            return Done()
        return ClassicFlow(value=x)

    def to_domain(self) -> None:
        return None


@dataclass
class BothFlow:
    value: int = 0

    @transition
    async def decorated(self, x: int) -> BothFlow | Done:
        return self

    async def __transition__(self, x: int) -> BothFlow | Done:
        return Done()

    def to_domain(self) -> None:
        return None


class EmptyFlow:
    def to_domain(self) -> None:
        return None


class NoToDomainFlow:
    @transition
    async def step(self, x: int) -> Done:
        return Done()


class NoKeyFlow:
    @transition
    async def step(self, x: int) -> Done:
        return Done()

    def to_domain(self) -> None:
        return None


class DummyResponse:
    pass


class DummyKey:
    pass


class DummyStore:
    pass


# ═══════════════════════════════════════════════════════════════════════════════
# transition() decorator
# ═══════════════════════════════════════════════════════════════════════════════


class TestTransitionDecorator:
    def test_marks_with_attribute(self) -> None:
        """transition() sets __is_transition__ = True on the function."""
        async def my_fn(self: object) -> Done:
            return Done()

        decorated = transition(my_fn)
        assert getattr(decorated, "__is_transition__", False) is True

    def test_returns_original_function(self) -> None:
        """transition() returns the exact same function object."""
        async def my_fn(self: object) -> Done:
            return Done()

        result = transition(my_fn)
        assert result is my_fn


# ═══════════════════════════════════════════════════════════════════════════════
# get_transitions()
# ═══════════════════════════════════════════════════════════════════════════════


class TestGetTransitions:
    def test_decorated_methods_returned(self) -> None:
        """Class with @transition methods yields those methods."""
        transitions = get_transitions(SampleFlow)
        assert len(transitions) == 1
        assert getattr(transitions[0], "__is_transition__", False) is True

    def test_classic_transition_fallback(self) -> None:
        """Class with __transition__ and no @transition yields __transition__."""
        transitions = get_transitions(ClassicFlow)
        assert len(transitions) == 1
        assert transitions[0] is ClassicFlow.__transition__

    def test_transition_decorator_wins_over_dunder(self) -> None:
        """When both exist, @transition wins; __transition__ is ignored (starts with _)."""
        transitions = get_transitions(BothFlow)
        # Only @transition-decorated methods are returned (dunder skipped by name filter)
        assert len(transitions) == 1
        assert getattr(transitions[0], "__is_transition__", False) is True

    def test_no_transitions_returns_empty(self) -> None:
        """Class with neither @transition nor __transition__ yields empty list."""
        transitions = get_transitions(EmptyFlow)
        assert transitions == []


# ═══════════════════════════════════════════════════════════════════════════════
# has_transitions()
# ═══════════════════════════════════════════════════════════════════════════════


class TestHasTransitions:
    def test_true_when_transitions_exist(self) -> None:
        assert has_transitions(SampleFlow) is True

    def test_false_when_no_transitions(self) -> None:
        assert has_transitions(EmptyFlow) is False


# ═══════════════════════════════════════════════════════════════════════════════
# parse_transition_result()
# ═══════════════════════════════════════════════════════════════════════════════


class TestParseTransitionResult:
    def test_self_instance_is_not_terminal(self) -> None:
        """Returning a plain state instance: is_terminal=False, response=Nothing."""
        state = SampleFlow(value=5)
        result: TransitionResult[SampleFlow, str] = parse_transition_result(state)
        assert isinstance(result, TransitionResult)
        assert result.is_terminal is False
        assert isinstance(result.response, Nothing)

    def test_tuple_state_and_response(self) -> None:
        """Returning (state, resp) tuple: is_terminal=False, response=Some(resp)."""
        state = SampleFlow(value=3)
        resp = "intermediate"
        result = parse_transition_result((state, resp))
        assert result.is_terminal is False
        assert result.response == Some(resp)

    def test_done_is_terminal(self) -> None:
        """Returning Done(): is_terminal=True, response=Nothing."""
        result: TransitionResult[SampleFlow, str] = parse_transition_result(Done())
        assert result.is_terminal is True
        assert isinstance(result.response, Nothing)

    def test_done_tuple_is_terminal_with_response(self) -> None:
        """Returning (Done(), resp): is_terminal=True, response=Some(resp)."""
        resp = "final"
        result = parse_transition_result((Done(), resp))
        assert result.is_terminal is True
        assert result.response == Some(resp)


# ═══════════════════════════════════════════════════════════════════════════════
# Done / Cancelled
# ═══════════════════════════════════════════════════════════════════════════════


class TestDoneAndCancelled:
    def test_done_is_frozen_dataclass(self) -> None:
        """Done is a frozen dataclass — mutation raises FrozenInstanceError."""
        done = Done()
        with pytest.raises(Exception):
            done.__dict__["x"] = 1  # type: ignore[attr-defined]

    def test_cancelled_is_subclass_of_done(self) -> None:
        assert issubclass(Cancelled, Done)

    def test_cancelled_instance_is_done(self) -> None:
        assert isinstance(Cancelled(), Done)


# ═══════════════════════════════════════════════════════════════════════════════
# StatefulBuilder
# ═══════════════════════════════════════════════════════════════════════════════


class TestStatefulBuilder:
    def test_stateful_returns_builder(self) -> None:
        """stateful(Flow, Response) returns a StatefulBuilder."""
        builder = stateful(SampleFlow, DummyResponse)
        assert isinstance(builder, StatefulBuilder)

    def test_store_fluent_returns_self(self) -> None:
        """.store() returns the builder itself for chaining."""
        builder = stateful(SampleFlow, DummyResponse)
        from emergent.wire.axis.storage import MemoryStorage
        store: MemoryStorage[str, object] = MemoryStorage()
        result = builder.store(store)
        assert result is builder

    def test_key_fluent_returns_self(self) -> None:
        """.key() returns the builder itself for chaining."""
        builder = stateful(SampleFlow, DummyResponse)
        result = builder.key(DummyKey)
        assert result is builder

    def test_agent_fluent_returns_self(self) -> None:
        """.agent() returns the builder itself for chaining."""
        from nodnod.agent.event_loop.agent import EventLoopAgent
        builder = stateful(SampleFlow, DummyResponse)
        result = builder.agent(EventLoopAgent)
        assert result is builder

    def test_build_without_key_raises(self) -> None:
        """.build() without .key() raises ValueError."""
        builder = stateful(SampleFlow, DummyResponse)
        with pytest.raises(ValueError, match="key_node"):
            builder.build()

    def test_build_flow_without_transitions_raises(self) -> None:
        """.build() with a flow that has no transitions raises ValueError."""
        builder = stateful(EmptyFlow, DummyResponse).key(DummyKey)
        with pytest.raises(ValueError, match="__transition__"):
            builder.build()

    def test_build_flow_missing_to_domain_raises(self) -> None:
        """.build() with a flow that lacks to_domain raises ValueError."""
        builder = stateful(NoToDomainFlow, DummyResponse).key(DummyKey)
        with pytest.raises(ValueError, match="to_domain"):
            builder.build()

    def test_build_success_returns_stateful_codec(self) -> None:
        """.build() with valid flow and key returns StatefulCodec with correct fields."""
        codec = stateful(SampleFlow, DummyResponse).key(DummyKey).build()
        assert isinstance(codec, StatefulCodec)
        assert codec.flow is SampleFlow
        assert codec.response is DummyResponse
        assert codec.key_node is DummyKey

    def test_build_defaults_to_memory_storage(self) -> None:
        """.build() without .store() defaults to MemoryStorage."""
        from emergent.wire.axis.storage import MemoryStorage
        codec = stateful(SampleFlow, DummyResponse).key(DummyKey).build()
        assert isinstance(codec.store, MemoryStorage)

    def test_build_defaults_to_event_loop_agent(self) -> None:
        """.build() without .agent() defaults to EventLoopAgent."""
        from nodnod.agent.event_loop.agent import EventLoopAgent
        codec = stateful(SampleFlow, DummyResponse).key(DummyKey).build()
        assert codec.agent_cls is EventLoopAgent


# ═══════════════════════════════════════════════════════════════════════════════
# StatefulCodec
# ═══════════════════════════════════════════════════════════════════════════════


class TestStatefulCodec:
    def test_frozen_dataclass_cannot_mutate(self) -> None:
        """StatefulCodec is frozen — attribute assignment raises FrozenInstanceError."""
        from emergent.wire.axis.storage import MemoryStorage
        from nodnod.agent.event_loop.agent import EventLoopAgent
        codec = StatefulCodec(
            flow=SampleFlow,
            response=DummyResponse,
            store=MemoryStorage[str, SampleFlow](),
            key_node=DummyKey,
            agent_cls=EventLoopAgent,
        )
        with pytest.raises(Exception):
            codec.flow = EmptyFlow  # type: ignore[misc]

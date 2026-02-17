"""Tests for codecs/resolve.py — unwrap, wrap, compose_params, try_compose_params, resolve_transition."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from kungfu import Option, Some, Nothing, Result, Ok, Error
from nodnod import Scope, Node
from nodnod.utils.create_node import create_node

from emergent.wire.axis.surface.codecs.resolve import (
    unwrap,
    wrap,
    get_method_params,
    get_transition_params,
    compose_params,
    try_compose_params,
    resolve_transition,
)

# Access private helper for testing via module attribute
import emergent.wire.axis.surface.codecs.resolve as _resolve_mod

_is_nodnod_node = _resolve_mod._is_nodnod_node  # pyright: ignore[reportPrivateUsage] — testing private helper intentionally


# Module-level types for type hint resolution (needed with `from __future__ import annotations`)
class _Unresolvable:
    """Type that is not a nodnod node and won't be injected — always fails composition."""
    pass


class _TransitionSelf:
    """Dummy self type for standalone transition-like functions in tests."""
    pass


async def _bad_transition(self: _TransitionSelf, thing: _Unresolvable) -> str:
    return ""


async def _good_transition(self: _TransitionSelf, token: str) -> str:
    return ""


# ═══════════════════════════════════════════════════════════════════════════════
# unwrap
# ═══════════════════════════════════════════════════════════════════════════════


class TestUnwrap:
    def test_plain_type(self) -> None:
        inner, is_optional = unwrap(str)
        assert inner is str
        assert not is_optional

    def test_option_type(self) -> None:
        inner, is_optional = unwrap(Option[int])
        assert inner is int
        assert is_optional

    def test_result_type(self) -> None:
        inner, is_optional = unwrap(Result[str, int])
        assert inner is str
        assert is_optional


# ═══════════════════════════════════════════════════════════════════════════════
# wrap
# ═══════════════════════════════════════════════════════════════════════════════


class TestWrap:
    def test_plain_success(self) -> None:
        result = wrap(str, True, "hello")
        assert result == "hello"

    def test_plain_failure_raises(self) -> None:
        with pytest.raises(RuntimeError, match="Required param failed"):
            wrap(str, False, "error msg")

    def test_option_success(self) -> None:
        result = wrap(Option[int], True, 42)
        assert isinstance(result, Some)
        assert result.unwrap() == 42

    def test_option_failure(self) -> None:
        result = wrap(Option[int], False, "error")
        assert isinstance(result, Nothing)

    def test_result_success(self) -> None:
        result = wrap(Result[str, int], True, "ok")
        assert isinstance(result, Ok)
        assert result.unwrap() == "ok"

    def test_result_failure(self) -> None:
        result = wrap(Result[str, int], False, 42)
        assert isinstance(result, Error)


# ═══════════════════════════════════════════════════════════════════════════════
# get_method_params / get_transition_params
# ═══════════════════════════════════════════════════════════════════════════════


class TestGetMethodParams:
    def test_simple_method(self) -> None:
        async def handler(self: _TransitionSelf, name: str, age: int) -> str:
            return ""

        params = get_method_params(handler)
        assert "name" in params
        assert "age" in params
        # self and return excluded
        assert "self" not in params
        assert "return" not in params

    def test_option_param(self) -> None:
        async def handler(self: _TransitionSelf, token: Option[str]) -> str:
            return ""

        params = get_method_params(handler)
        assert params["token"][1] is str  # compose_type

    def test_result_param(self) -> None:
        async def handler(self: _TransitionSelf, data: Result[int, str]) -> str:
            return ""

        params = get_method_params(handler)
        assert params["data"][1] is int  # compose_type


class TestGetTransitionParams:
    def test_with_transition(self) -> None:
        @dataclass
        class Flow:
            async def __transition__(self, value: str) -> None:
                pass

        params = get_transition_params(Flow)
        assert "value" in params

    def test_without_transition(self) -> None:
        @dataclass
        class NoTransition:
            pass

        params = get_transition_params(NoTransition)
        assert params == {}


# ═══════════════════════════════════════════════════════════════════════════════
# compose_params
# ═══════════════════════════════════════════════════════════════════════════════


# Create a simple nodnod node for testing
_TokenNode: type[Node[str, str]] = create_node(
    name="_TokenNode",
    base_node=Node,
    bases=(),
    namespace={
        "__compose__": classmethod(lambda cls: "test_token"),
        "__module__": __name__,
    },
)


class TestComposeParams:
    @pytest.mark.asyncio
    async def test_compose_injected_value(self) -> None:
        from nodnod.agent.event_loop.agent import EventLoopAgent

        params = {"name": (str, str)}
        async with Scope() as scope:
            scope.inject(str, "injected")
            composed = await compose_params(params, scope, EventLoopAgent)
            assert composed["name"] == "injected"

    @pytest.mark.asyncio
    async def test_compose_nodnod_node(self) -> None:
        from nodnod.agent.event_loop.agent import EventLoopAgent

        params = {"token": (_TokenNode, _TokenNode)}
        async with Scope() as scope:
            composed = await compose_params(params, scope, EventLoopAgent)
            assert composed["token"] == "test_token"

    @pytest.mark.asyncio
    async def test_compose_non_node_non_injected(self) -> None:
        from nodnod.agent.event_loop.agent import EventLoopAgent

        params = {"thing": (_Unresolvable, _Unresolvable)}
        async with Scope() as scope:
            with pytest.raises(RuntimeError, match="Required param failed"):
                await compose_params(params, scope, EventLoopAgent)

    @pytest.mark.asyncio
    async def test_compose_optional_non_node(self) -> None:
        from nodnod.agent.event_loop.agent import EventLoopAgent

        params = {"thing": (Option[_Unresolvable], _Unresolvable)}
        async with Scope() as scope:
            composed = await compose_params(params, scope, EventLoopAgent)
            assert isinstance(composed["thing"], Nothing)


# ═══════════════════════════════════════════════════════════════════════════════
# try_compose_params
# ═══════════════════════════════════════════════════════════════════════════════


class TestTryComposeParams:
    @pytest.mark.asyncio
    async def test_all_required_succeed(self) -> None:
        from nodnod.agent.event_loop.agent import EventLoopAgent

        params = {"token": (_TokenNode, _TokenNode)}
        async with Scope() as scope:
            result = await try_compose_params(params, scope, EventLoopAgent)
            assert isinstance(result, Some)

    @pytest.mark.asyncio
    async def test_required_fails_returns_nothing(self) -> None:
        from nodnod.agent.event_loop.agent import EventLoopAgent

        params = {"thing": (_Unresolvable, _Unresolvable)}
        async with Scope() as scope:
            result = await try_compose_params(params, scope, EventLoopAgent)
            assert isinstance(result, Nothing)

    @pytest.mark.asyncio
    async def test_optional_failure_still_succeeds(self) -> None:
        from nodnod.agent.event_loop.agent import EventLoopAgent

        params = {
            "token": (_TokenNode, _TokenNode),
            "opt": (Option[_Unresolvable], _Unresolvable),
        }
        async with Scope() as scope:
            result = await try_compose_params(params, scope, EventLoopAgent)
            assert isinstance(result, Some)


# ═══════════════════════════════════════════════════════════════════════════════
# resolve_transition
# ═══════════════════════════════════════════════════════════════════════════════


class TestResolveTransition:
    @pytest.mark.asyncio
    async def test_first_resolvable_chosen(self) -> None:
        from nodnod.agent.event_loop.agent import EventLoopAgent

        async def good_transition(self: _TransitionSelf, token: str) -> str:
            return ""

        async with Scope() as scope:
            scope.inject(str, "injected_token")
            result = await resolve_transition([good_transition], scope, EventLoopAgent)
            assert isinstance(result, Some)
            method, _composed = result.unwrap()
            assert method is good_transition

    @pytest.mark.asyncio
    async def test_no_resolvable_returns_nothing(self) -> None:
        from nodnod.agent.event_loop.agent import EventLoopAgent

        async with Scope() as scope:
            result = await resolve_transition([_bad_transition], scope, EventLoopAgent)
            assert isinstance(result, Nothing)

    @pytest.mark.asyncio
    async def test_skips_unresolvable_finds_resolvable(self) -> None:
        from nodnod.agent.event_loop.agent import EventLoopAgent

        async with Scope() as scope:
            scope.inject(str, "tok")
            result = await resolve_transition([_bad_transition, _good_transition], scope, EventLoopAgent)
            assert isinstance(result, Some)
            method, _ = result.unwrap()
            assert method is _good_transition


# ═══════════════════════════════════════════════════════════════════════════════
# _is_nodnod_node
# ═══════════════════════════════════════════════════════════════════════════════


class TestIsNodnodNode:
    def test_node_type_detected(self) -> None:
        assert _is_nodnod_node(_TokenNode) is True

    def test_plain_type_not_node(self) -> None:
        assert _is_nodnod_node(str) is False

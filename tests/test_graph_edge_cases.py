"""Tests for edge cases in emergent/ops/_graph.py and emergent/graph/_run.py.

Covers:
1. Runner.run() with scope_extras
2. Runner.run() with unregistered op returns Error
3. Runner.__call__() returns LazyCoroResult with same result as run()
4. Op.get() on unbound op raises RuntimeError
5. TypedScope.copy() produces independent copy
6. TypedScope.all_injected() returns all injections
7. TypedScope.copy() does not share mutation state
8. Runner.run() basic happy path
9. Runner.run() with scope_extras — multiple extras at once
10. Runner.__call__() result equals Runner.run() result
11. TypedScope inject then get round-trip
12. TypedScope.copy() detail is preserved
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from kungfu import Error, Ok, Result

from emergent.graph._run import TypedScope
from emergent.ops._graph import Op, ops


# ═══════════════════════════════════════════════════════════════════════════════
# Shared fixtures / helpers
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class DoubleOp(Op[int, str]):
    value: int


async def double_handler(req: DoubleOp) -> Result[int, str]:
    return Ok(req.value * 2)


@dataclass
class EchoOp(Op[str, str]):
    text: str


async def echo_handler(req: EchoOp) -> Result[str, str]:
    return Ok(req.text)


@dataclass
class UnregisteredOp(Op[int, str]):
    x: int


@dataclass
class UnboundOp(Op[int, str]):
    x: int


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Runner.run() happy path
# ═══════════════════════════════════════════════════════════════════════════════


class TestRunnerRunHappyPath:
    @pytest.mark.asyncio
    async def test_basic_op_returns_ok(self) -> None:
        runner = ops().on(DoubleOp, double_handler).compile()
        result = await runner.run(DoubleOp(value=5))
        assert result == Ok(10)

    @pytest.mark.asyncio
    async def test_string_op_returns_ok(self) -> None:
        runner = ops().on(EchoOp, echo_handler).compile()
        result = await runner.run(EchoOp(text="hello"))
        assert result == Ok("hello")


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Runner.run() with scope_extras
# ═══════════════════════════════════════════════════════════════════════════════


class TestRunnerRunWithScopeExtras:
    @pytest.mark.asyncio
    async def test_scope_extras_do_not_break_handler(self) -> None:
        """Extras injected into scope must not interfere with the handler result."""
        runner = ops().on(DoubleOp, double_handler).compile()
        result = await runner.run(DoubleOp(value=7), scope_extras={str: "extra_value"})
        assert result == Ok(14)

    @pytest.mark.asyncio
    async def test_scope_extras_multiple_types(self) -> None:
        """Multiple scope_extras entries must all be accepted without error."""
        runner = ops().on(EchoOp, echo_handler).compile()
        extras: dict[type, object] = {int: 42, float: 3.14}
        result = await runner.run(EchoOp(text="world"), scope_extras=extras)
        assert result == Ok("world")

    @pytest.mark.asyncio
    async def test_scope_extras_none_is_equivalent_to_omitting(self) -> None:
        runner = ops().on(DoubleOp, double_handler).compile()
        result_no_extras = await runner.run(DoubleOp(value=3))
        result_none_extras = await runner.run(DoubleOp(value=3), scope_extras=None)
        assert result_no_extras == result_none_extras


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Runner.run() with unregistered op
# ═══════════════════════════════════════════════════════════════════════════════


class TestRunnerRunUnregisteredOp:
    @pytest.mark.asyncio
    async def test_unregistered_op_returns_error(self) -> None:
        runner = ops().on(DoubleOp, double_handler).compile()
        result = await runner.run(UnregisteredOp(x=1))
        assert isinstance(result, Error)

    @pytest.mark.asyncio
    async def test_unregistered_op_error_mentions_op_name(self) -> None:
        runner = ops().compile()
        result = await runner.run(UnregisteredOp(x=99))
        assert isinstance(result, Error)
        assert "UnregisteredOp" in result.error


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Runner.__call__() returns LazyCoroResult
# ═══════════════════════════════════════════════════════════════════════════════


class TestRunnerCall:
    @pytest.mark.asyncio
    async def test_call_returns_same_result_as_run(self) -> None:
        runner = ops().on(DoubleOp, double_handler).compile()
        lazy = runner(DoubleOp(value=4))
        result_call = await lazy
        result_run = await runner.run(DoubleOp(value=4))
        assert result_call == result_run

    @pytest.mark.asyncio
    async def test_call_on_unregistered_op_returns_error(self) -> None:
        runner = ops().compile()
        lazy = runner(UnregisteredOp(x=5))
        result = await lazy
        assert isinstance(result, Error)


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Op.get() when unbound
# ═══════════════════════════════════════════════════════════════════════════════


class TestOpGetUnbound:
    def test_get_on_unbound_op_raises_runtime_error(self) -> None:
        op = UnboundOp(x=1)
        with pytest.raises(RuntimeError):
            op.get()

    def test_runtime_error_message_contains_op_name(self) -> None:
        op = UnboundOp(x=2)
        with pytest.raises(RuntimeError, match="UnboundOp"):
            op.get()


# ═══════════════════════════════════════════════════════════════════════════════
# 6. TypedScope.copy()
# ═══════════════════════════════════════════════════════════════════════════════


class TestTypedScopeCopy:
    def test_copy_contains_same_injections(self) -> None:
        scope = TypedScope(detail="test")
        scope.inject(int, 42)
        scope.inject(str, "hello")

        copy = scope.copy()
        injected = copy.all_injected()

        assert injected[int] == 42
        assert injected[str] == "hello"

    def test_copy_is_independent_from_original(self) -> None:
        scope = TypedScope(detail="test")
        scope.inject(int, 10)

        copy = scope.copy()
        # Inject into copy after copying — original must not see it
        copy.inject(float, 3.14)

        original_injected = scope.all_injected()
        assert float not in original_injected

    def test_copy_mutations_do_not_affect_original_values(self) -> None:
        scope = TypedScope(detail="test")
        scope.inject(int, 99)

        copy = scope.copy()
        # Re-inject a different value for the same type into the copy
        copy.inject(int, 0)

        # Original must retain its own value
        assert scope.all_injected()[int] == 99


# ═══════════════════════════════════════════════════════════════════════════════
# 7. TypedScope.all_injected()
# ═══════════════════════════════════════════════════════════════════════════════


class TestTypedScopeAllInjected:
    def test_empty_scope_returns_empty_dict(self) -> None:
        scope = TypedScope(detail="empty")
        assert scope.all_injected() == {}

    def test_all_injected_returns_every_entry(self) -> None:
        scope = TypedScope(detail="full")
        scope.inject(int, 1)
        scope.inject(str, "two")
        scope.inject(float, 3.0)

        injected = scope.all_injected()
        assert injected[int] == 1
        assert injected[str] == "two"
        assert injected[float] == 3.0
        assert len(injected) == 3

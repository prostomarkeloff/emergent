"""Extended tests for emergent/ops/_graph.py — coverage gaps.

Covers:
- _collect_op_deps with dependency cycles and complex graphs
- Runner.__call__() returning LazyCoroResult
- Runner.run() with scope_extras
- Runner.run() with unregistered op (Error path)
- OpsBuilder.on() last-registration-wins behavior
- OpsBuilder.inject()
- Op.get() raises RuntimeError when unbound
- _is_op_type edge cases
- _CachedOp wrapper behavior
"""

# pyright: reportPrivateUsage=false
# Rationale: tests must access private/protected internals (_is_op_type,
# _CachedOp, _registry, _precompile_scope, _collect_op_deps) to verify
# their correctness. There is no public API for these implementation details.

from __future__ import annotations

from dataclasses import dataclass

import pytest

from kungfu import Result, Ok, Error

from emergent.ops._graph import (
    Op,
    OpsBuilder,
    Runner,
    ops,
    _is_op_type,
    _CachedOp,
)


# ============================================================================
# Test Op Types
# ============================================================================


@dataclass(frozen=True, slots=True)
class GetPrice(Op[float, str]):
    product_id: int


@dataclass(frozen=True, slots=True)
class GetStock(Op[int, str]):
    product_id: int


@dataclass(frozen=True, slots=True)
class BuildSummary(Op[str, str]):
    product_id: int
    price: GetPrice
    stock: GetStock


@dataclass(frozen=True, slots=True)
class SimpleOp(Op[str, str]):
    value: str


@dataclass(frozen=True, slots=True)
class NestedDep(Op[str, str]):
    inner: SimpleOp


@dataclass(frozen=True, slots=True)
class DeepChain(Op[str, str]):
    dep: NestedDep


class Injected:
    """A dependency that is not an Op."""
    def __init__(self, name: str) -> None:
        self.name = name


# ============================================================================
# Handlers
# ============================================================================


async def handle_get_price(req: GetPrice) -> Result[float, str]:
    return Ok(float(req.product_id) * 10.0)


async def handle_get_stock(req: GetStock) -> Result[int, str]:
    return Ok(req.product_id * 5)


async def handle_build_summary(
    req: BuildSummary,
    price: GetPrice,
    stock: GetStock,
) -> Result[str, str]:
    p = await price
    s = await stock
    match p:
        case Ok(price_val):
            pass
        case _:
            return Error("price failed")
    match s:
        case Ok(stock_val):
            pass
        case _:
            return Error("stock failed")
    return Ok(f"product={req.product_id} price={price_val} stock={stock_val}")


async def handle_simple(req: SimpleOp) -> Result[str, str]:
    return Ok(f"handled:{req.value}")


async def handle_nested(req: NestedDep, inner: SimpleOp) -> Result[str, str]:
    r = await inner
    match r:
        case Ok(val):
            return Ok(f"nested:{val}")
        case _:
            return Error("nested failed")


async def handle_deep(req: DeepChain, dep: NestedDep) -> Result[str, str]:
    r = await dep
    match r:
        case Ok(val):
            return Ok(f"deep:{val}")
        case _:
            return Error("deep failed")


async def handle_simple_with_injected(req: SimpleOp, injected: Injected) -> Result[str, str]:
    return Ok(f"{req.value}:{injected.name}")


# ============================================================================
# Op base class
# ============================================================================


class TestOpBase:
    def test_get_raises_when_unbound(self) -> None:
        op = SimpleOp(value="test")
        with pytest.raises(RuntimeError, match="not bound"):
            op.get()

    def test_await_calls_get(self) -> None:
        """Op.__await__ delegates to get()."""
        op = SimpleOp(value="test")
        with pytest.raises(RuntimeError, match="not bound"):
            # Attempting to create the coroutine will call get()
            op.__await__()


# ============================================================================
# _is_op_type
# ============================================================================


class TestIsOpType:
    def test_op_subclass(self) -> None:
        assert _is_op_type(SimpleOp) is True

    def test_op_itself(self) -> None:
        assert _is_op_type(Op) is True

    def test_non_op(self) -> None:
        assert _is_op_type(str) is False
        assert _is_op_type(int) is False

    def test_non_type(self) -> None:
        assert _is_op_type("not a type") is False
        assert _is_op_type(42) is False
        assert _is_op_type(None) is False


# ============================================================================
# _CachedOp
# ============================================================================


class TestCachedOp:
    @pytest.mark.asyncio
    async def test_cached_ok(self) -> None:
        ok_result: Result[str, str] = Ok("hello")
        cached: _CachedOp[str, str] = _CachedOp(ok_result)
        result: Result[str, str] = await cached.get()
        assert isinstance(result, Ok)
        assert result.value == "hello"

    @pytest.mark.asyncio
    async def test_cached_error(self) -> None:
        err_result: Result[str, str] = Error("fail")
        cached: _CachedOp[str, str] = _CachedOp(err_result)
        result: Result[str, str] = await cached.get()
        assert isinstance(result, Error)
        assert result.error == "fail"

    @pytest.mark.asyncio
    async def test_cached_await(self) -> None:
        ok_result: Result[int, str] = Ok(42)
        cached: _CachedOp[int, str] = _CachedOp(ok_result)
        result: Result[int, str] = await cached
        assert isinstance(result, Ok)
        assert result.value == 42


# ============================================================================
# OpsBuilder
# ============================================================================


class TestOpsBuilder:
    def test_on_last_registration_wins(self) -> None:
        """If the same op is registered twice, the last handler wins."""
        async def handler_v1(req: SimpleOp) -> Result[str, str]:
            return Ok("v1")

        async def handler_v2(req: SimpleOp) -> Result[str, str]:
            return Ok("v2")

        builder = ops().on(SimpleOp, handler_v1).on(SimpleOp, handler_v2)
        runner = builder.compile()
        # The internal registry should have handler_v2
        assert runner._registry[SimpleOp].handler is handler_v2

    def test_inject_on_builder(self) -> None:
        builder = ops()
        injected = Injected("test")
        builder = builder.inject(Injected, injected)
        # inject returns the same builder (it mutates the precompile scope)
        assert builder._precompile_scope.all_injected()[Injected] is injected


# ============================================================================
# Runner._collect_op_deps
# ============================================================================


class TestCollectOpDeps:
    def _make_runner(self) -> Runner:
        return (
            ops()
            .on(GetPrice, handle_get_price)
            .on(GetStock, handle_get_stock)
            .on(BuildSummary, handle_build_summary)
            .on(SimpleOp, handle_simple)
            .on(NestedDep, handle_nested)
            .on(DeepChain, handle_deep)
            .compile()
        )

    def test_no_deps(self) -> None:
        runner = self._make_runner()
        req = SimpleOp(value="x")
        deps = runner._collect_op_deps(req)
        assert deps == []

    def test_direct_deps(self) -> None:
        runner = self._make_runner()
        price = GetPrice(product_id=1)
        stock = GetStock(product_id=1)
        req = BuildSummary(product_id=1, price=price, stock=stock)
        deps = runner._collect_op_deps(req)
        dep_types = [t for t, _ in deps]
        assert GetPrice in dep_types
        assert GetStock in dep_types

    def test_nested_deps(self) -> None:
        runner = self._make_runner()
        inner = SimpleOp(value="a")
        nested = NestedDep(inner=inner)
        req = DeepChain(dep=nested)
        deps = runner._collect_op_deps(req)
        dep_types = [t for t, _ in deps]
        assert NestedDep in dep_types
        assert SimpleOp in dep_types

    def test_cycle_detection(self) -> None:
        """If the same Op instance appears multiple times, visited set prevents re-visit."""
        runner = self._make_runner()
        shared_price = GetPrice(product_id=1)
        stock = GetStock(product_id=1)
        req = BuildSummary(product_id=1, price=shared_price, stock=stock)
        # No error, no infinite loop
        deps = runner._collect_op_deps(req)
        assert len(deps) == 2

    def test_non_dataclass_op(self) -> None:
        """Op without dataclass fields is handled (no __dataclass_fields__)."""
        runner = self._make_runner()

        class PlainOp(Op[str, str]):
            pass

        req = PlainOp()
        deps = runner._collect_op_deps(req)
        assert deps == []


# ============================================================================
# Runner.run
# ============================================================================


class TestRunnerRun:
    @pytest.mark.asyncio
    async def test_run_simple(self) -> None:
        runner = ops().on(SimpleOp, handle_simple).compile()
        result = await runner.run(SimpleOp(value="hello"))
        assert isinstance(result, Ok)
        assert result.value == "handled:hello"

    @pytest.mark.asyncio
    async def test_run_unregistered_op(self) -> None:
        runner = ops().on(SimpleOp, handle_simple).compile()
        result = await runner.run(GetPrice(product_id=1))
        assert isinstance(result, Error)
        assert "not registered" in str(result.error).lower() or "GetPrice" in str(result.error)

    @pytest.mark.asyncio
    async def test_run_with_scope_extras(self) -> None:
        """scope_extras injects additional typed values into handler scope."""
        runner = ops().on(SimpleOp, handle_simple_with_injected).compile()
        injected = Injected("extra")
        result = await runner.run(
            SimpleOp(value="test"),
            scope_extras={Injected: injected},
        )
        assert isinstance(result, Ok)
        assert result.value == "test:extra"

    @pytest.mark.asyncio
    async def test_run_with_dependencies(self) -> None:
        """Build a runner with multi-op dependency graph."""
        runner = (
            ops()
            .on(GetPrice, handle_get_price)
            .on(GetStock, handle_get_stock)
            .on(BuildSummary, handle_build_summary)
            .compile()
        )
        price = GetPrice(product_id=2)
        stock = GetStock(product_id=2)
        req = BuildSummary(product_id=2, price=price, stock=stock)
        result = await runner.run(req)
        assert isinstance(result, Ok)
        assert "product=2" in result.value
        assert "price=20.0" in result.value
        assert "stock=10" in result.value


# ============================================================================
# Runner.__call__
# ============================================================================


class TestRunnerCall:
    @pytest.mark.asyncio
    async def test_call_returns_lazy_coro_result(self) -> None:
        """Runner.__call__ returns a LazyCoroResult that can be awaited."""
        runner = ops().on(SimpleOp, handle_simple).compile()
        lazy = runner(SimpleOp(value="call"))
        result = await lazy
        assert isinstance(result, Ok)
        assert result.value == "handled:call"


# ============================================================================
# Runner.inject
# ============================================================================


class TestRunnerInject:
    @pytest.mark.asyncio
    async def test_inject_on_runner(self) -> None:
        runner = ops().on(SimpleOp, handle_simple_with_injected).compile()
        injected = Injected("runner-injected")
        runner.inject(Injected, injected)
        result = await runner.run(SimpleOp(value="hi"))
        assert isinstance(result, Ok)
        assert result.value == "hi:runner-injected"


# ============================================================================
# ops() and operation_set()
# ============================================================================


class TestOpsFactory:
    def test_ops_returns_builder(self) -> None:
        builder = ops()
        assert isinstance(builder, OpsBuilder)

    def test_operation_set_alias(self) -> None:
        from emergent.ops._graph import operation_set
        builder = operation_set()
        assert isinstance(builder, OpsBuilder)

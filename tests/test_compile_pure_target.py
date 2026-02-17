"""Tests for pure target compilation — lifecycle, exception, and compiler instances.

Covers:
- wrap_lifecycle_delegate: sync and async handlers
- wrap_lifecycle_factory: sync and async factories
- LifecycleRoute.order propagation
- app_scope_lifespan: context manager enter/yield/exit
- STARTUP_COMPILER, SHUTDOWN_COMPILER, EXCEPTION_COMPILER, WEBSOCKET_COMPILER
  are TargetCompiler instances with correct trigger_type
"""

from __future__ import annotations

import pytest

from nodnod import Scope

from emergent.ops._graph import ops
from emergent.wire.axis.surface._handler import Handler
from emergent.wire.axis.surface.codecs.delegate import DelegateCodec
from emergent.wire.axis.surface.codecs.immediate import ImmediateFactoryCodec
from emergent.wire.axis.surface.triggers.lifecycle import StartupTrigger, ShutdownTrigger
from emergent.wire.axis.surface.triggers.exception import ExceptionTrigger
from emergent.wire.axis.surface.triggers.websocket import WebSocketTrigger
from emergent.wire.compile._core import Axes
from emergent.wire.compile._target import TargetCompiler
from emergent.wire.compile.targets.pure import (
    LifecycleRoute,
    STARTUP_COMPILER,
    SHUTDOWN_COMPILER,
    EXCEPTION_COMPILER,
    WEBSOCKET_COMPILER,
    wrap_lifecycle_delegate,
    wrap_lifecycle_factory,
    app_scope_lifespan,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════════


def _make_runner():
    return ops().compile()


def _make_axes() -> Axes:
    return Axes.default()


# ═══════════════════════════════════════════════════════════════════════════════
# 1. wrap_lifecycle_delegate — sync handler
# ═══════════════════════════════════════════════════════════════════════════════


class TestWrapLifecycleDelegateSyncHandler:
    """wrap_lifecycle_delegate with a synchronous handler function calls the fn."""

    @pytest.mark.asyncio
    async def test_sync_handler_is_called(self) -> None:
        called: list[str] = []

        def sync_fn() -> None:
            called.append("sync_called")

        codec = DelegateCodec(handler=sync_fn)
        handler: Handler[DelegateCodec] = Handler(codec=codec, runner=_make_runner())
        trigger = StartupTrigger(order=0)
        axes = _make_axes()

        route = wrap_lifecycle_delegate(handler, trigger, axes)

        assert isinstance(route, LifecycleRoute)
        await route.handler()
        assert called == ["sync_called"]

    @pytest.mark.asyncio
    async def test_sync_handler_called_exactly_once(self) -> None:
        call_count: list[int] = [0]

        def sync_fn() -> None:
            call_count[0] += 1

        codec = DelegateCodec(handler=sync_fn)
        handler: Handler[DelegateCodec] = Handler(codec=codec, runner=_make_runner())
        route = wrap_lifecycle_delegate(handler, StartupTrigger(), _make_axes())

        await route.handler()
        await route.handler()
        assert call_count[0] == 2


# ═══════════════════════════════════════════════════════════════════════════════
# 2. wrap_lifecycle_delegate — async handler
# ═══════════════════════════════════════════════════════════════════════════════


class TestWrapLifecycleDelegateAsyncHandler:
    """wrap_lifecycle_delegate with an async handler awaits the coroutine."""

    @pytest.mark.asyncio
    async def test_async_handler_is_awaited(self) -> None:
        awaited: list[str] = []

        async def async_fn() -> None:
            awaited.append("async_awaited")

        codec = DelegateCodec(handler=async_fn)
        handler: Handler[DelegateCodec] = Handler(codec=codec, runner=_make_runner())
        trigger = StartupTrigger(order=0)

        route = wrap_lifecycle_delegate(handler, trigger, _make_axes())

        assert isinstance(route, LifecycleRoute)
        await route.handler()
        assert awaited == ["async_awaited"]

    @pytest.mark.asyncio
    async def test_async_handler_with_shutdown_trigger(self) -> None:
        log: list[str] = []

        async def async_shutdown() -> None:
            log.append("shutdown")

        codec = DelegateCodec(handler=async_shutdown)
        handler: Handler[DelegateCodec] = Handler(codec=codec, runner=_make_runner())
        route = wrap_lifecycle_delegate(handler, ShutdownTrigger(order=5), _make_axes())

        await route.handler()
        assert log == ["shutdown"]


# ═══════════════════════════════════════════════════════════════════════════════
# 3. wrap_lifecycle_factory — sync factory
# ═══════════════════════════════════════════════════════════════════════════════


class TestWrapLifecycleFactorySyncFactory:
    """wrap_lifecycle_factory with a sync factory (returns non-awaitable) calls the factory."""

    @pytest.mark.asyncio
    async def test_sync_factory_is_called(self) -> None:
        invoked: list[str] = []

        def sync_factory() -> str:
            invoked.append("factory_called")
            return "result"

        codec = ImmediateFactoryCodec(factory=sync_factory)
        handler: Handler[ImmediateFactoryCodec] = Handler(
            codec=codec, runner=_make_runner()
        )
        trigger = StartupTrigger(order=0)

        route = wrap_lifecycle_factory(handler, trigger, _make_axes())

        assert isinstance(route, LifecycleRoute)
        await route.handler()
        assert invoked == ["factory_called"]

    @pytest.mark.asyncio
    async def test_sync_factory_called_on_shutdown(self) -> None:
        log: list[str] = []

        def sync_factory() -> None:
            log.append("shutdown_factory")

        codec = ImmediateFactoryCodec(factory=sync_factory)
        handler: Handler[ImmediateFactoryCodec] = Handler(
            codec=codec, runner=_make_runner()
        )
        route = wrap_lifecycle_factory(handler, ShutdownTrigger(order=1), _make_axes())
        await route.handler()
        assert log == ["shutdown_factory"]


# ═══════════════════════════════════════════════════════════════════════════════
# 4. wrap_lifecycle_factory — async factory (returns awaitable)
# ═══════════════════════════════════════════════════════════════════════════════


class TestWrapLifecycleFactoryAsyncFactory:
    """wrap_lifecycle_factory with an async factory awaits the returned coroutine."""

    @pytest.mark.asyncio
    async def test_async_factory_result_is_awaited(self) -> None:
        awaited: list[str] = []

        async def async_factory() -> str:
            awaited.append("async_factory_awaited")
            return "done"

        codec = ImmediateFactoryCodec(factory=async_factory)
        handler: Handler[ImmediateFactoryCodec] = Handler(
            codec=codec, runner=_make_runner()
        )
        trigger = StartupTrigger(order=0)

        route = wrap_lifecycle_factory(handler, trigger, _make_axes())

        assert isinstance(route, LifecycleRoute)
        await route.handler()
        assert awaited == ["async_factory_awaited"]


# ═══════════════════════════════════════════════════════════════════════════════
# 5. LifecycleRoute.order matches trigger order
# ═══════════════════════════════════════════════════════════════════════════════


class TestLifecycleRouteOrder:
    """LifecycleRoute.order is taken from the trigger's order field."""

    def test_delegate_order_from_startup_trigger(self) -> None:
        def fn() -> None:
            pass

        codec = DelegateCodec(handler=fn)
        handler: Handler[DelegateCodec] = Handler(codec=codec, runner=_make_runner())

        route = wrap_lifecycle_delegate(handler, StartupTrigger(order=7), _make_axes())
        assert route.order == 7

    def test_delegate_order_from_shutdown_trigger(self) -> None:
        def fn() -> None:
            pass

        codec = DelegateCodec(handler=fn)
        handler: Handler[DelegateCodec] = Handler(codec=codec, runner=_make_runner())

        route = wrap_lifecycle_delegate(handler, ShutdownTrigger(order=42), _make_axes())
        assert route.order == 42

    def test_factory_order_propagated(self) -> None:
        def factory() -> None:
            pass

        codec = ImmediateFactoryCodec(factory=factory)
        handler: Handler[ImmediateFactoryCodec] = Handler(
            codec=codec, runner=_make_runner()
        )

        route = wrap_lifecycle_factory(handler, StartupTrigger(order=3), _make_axes())
        assert route.order == 3

    def test_default_order_is_zero(self) -> None:
        def fn() -> None:
            pass

        codec = DelegateCodec(handler=fn)
        handler: Handler[DelegateCodec] = Handler(codec=codec, runner=_make_runner())

        route = wrap_lifecycle_delegate(handler, StartupTrigger(), _make_axes())
        assert route.order == 0


# ═══════════════════════════════════════════════════════════════════════════════
# 6. app_scope_lifespan — enter and yield scope (no compose)
# ═══════════════════════════════════════════════════════════════════════════════


class TestAppScopeLifespan:
    """app_scope_lifespan enters the scope, yields it, and exits cleanly."""

    @pytest.mark.asyncio
    async def test_yields_scope_without_compose(self) -> None:
        scope = Scope(detail="test:app_scope_lifespan")
        yielded: list[Scope] = []

        async with app_scope_lifespan(scope) as s:
            yielded.append(s)

        assert len(yielded) == 1
        assert yielded[0] is scope

    @pytest.mark.asyncio
    async def test_scope_is_entered_on_entry(self) -> None:
        scope = Scope(detail="test:app_scope_entered")

        async with app_scope_lifespan(scope) as s:
            # Scope is active — we can inject into it
            s.inject(str, "hello")
            retrieved = s.retrieve(str)
            # retrieve returns an Option; Some means found
            from kungfu import Some
            assert isinstance(retrieved, Some)


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Compiler instances — trigger_type and type correctness
# ═══════════════════════════════════════════════════════════════════════════════


class TestCompilerInstances:
    """STARTUP_COMPILER, SHUTDOWN_COMPILER, EXCEPTION_COMPILER, WEBSOCKET_COMPILER
    are TargetCompiler instances with the correct trigger_type."""

    def test_startup_compiler_is_target_compiler(self) -> None:
        assert isinstance(STARTUP_COMPILER, TargetCompiler)

    def test_startup_compiler_trigger_type(self) -> None:
        assert STARTUP_COMPILER.trigger_type is StartupTrigger

    def test_shutdown_compiler_is_target_compiler(self) -> None:
        assert isinstance(SHUTDOWN_COMPILER, TargetCompiler)

    def test_shutdown_compiler_trigger_type(self) -> None:
        assert SHUTDOWN_COMPILER.trigger_type is ShutdownTrigger

    def test_exception_compiler_is_target_compiler(self) -> None:
        assert isinstance(EXCEPTION_COMPILER, TargetCompiler)

    def test_exception_compiler_trigger_type(self) -> None:
        assert EXCEPTION_COMPILER.trigger_type is ExceptionTrigger

    def test_websocket_compiler_is_target_compiler(self) -> None:
        assert isinstance(WEBSOCKET_COMPILER, TargetCompiler)

    def test_websocket_compiler_trigger_type(self) -> None:
        assert WEBSOCKET_COMPILER.trigger_type is WebSocketTrigger

    def test_startup_compiler_has_adapters(self) -> None:
        assert len(STARTUP_COMPILER.adapters) > 0

    def test_shutdown_compiler_has_adapters(self) -> None:
        assert len(SHUTDOWN_COMPILER.adapters) > 0

    def test_exception_compiler_has_adapters(self) -> None:
        assert len(EXCEPTION_COMPILER.adapters) > 0

    def test_websocket_compiler_has_adapters(self) -> None:
        assert len(WEBSOCKET_COMPILER.adapters) > 0

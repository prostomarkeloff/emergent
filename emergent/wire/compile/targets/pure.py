"""Pure target — framework-agnostic compilation for non-transport triggers.

Lifecycle, exception, and websocket triggers share a pattern: they don't need
HTTP/CLI/Telegram-specific wrapping. The pure target compiles them to structured
route objects that any framework adapter can consume.

Pattern: framework adapter creates Scope, injects its context, calls route.handler.

    from emergent.wire.compile.targets.pure import STARTUP_COMPILER, EXCEPTION_COMPILER

    for trigger, handler, route in EXCEPTION_COMPILER.scan_and_wrap(app, axes):
        async def _exc(request, exc, _route=route):
            async with Scope() as scope:
                scope.inject(type(request), request)
                scope.inject(type(exc), exc)
                return await _route.handler(scope)
        framework.add_exception_handler(route.exception_type, _exc)
"""

from __future__ import annotations

import inspect
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Protocol

from nodnod import Scope

from emergent.wire.axis.surface._handler import Handler
from emergent.wire.axis.surface.codecs.delegate import DelegateCodec
from emergent.wire.axis.surface.codecs.immediate import ImmediateFactoryCodec
from emergent.wire.axis.surface.triggers.lifecycle import StartupTrigger, ShutdownTrigger
from emergent.wire.axis.surface.triggers.exception import ExceptionTrigger
from emergent.wire.axis.surface.triggers.websocket import WebSocketTrigger
from emergent.wire.compile._core import Axes
from emergent.wire.compile._target import CodecBinding, TargetCompiler


# ═══════════════════════════════════════════════════════════════════════════════
# Route types — structured wrap results
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class LifecycleRoute:
    """Compiled lifecycle handler — ready to call, no context needed."""

    handler: Callable[[], Awaitable[None]]
    order: int


@dataclass(frozen=True, slots=True)
class ExceptionRoute:
    """Compiled exception handler — takes Scope with injected exception + context."""

    handler: Callable[[Scope], Awaitable[Any]]
    exception_type: type[Exception]
    propagate: bool


@dataclass(frozen=True, slots=True)
class WebSocketRoute:
    """Compiled websocket handler — takes Scope with injected websocket."""

    handler: Callable[[Scope], Awaitable[None]]


# ═══════════════════════════════════════════════════════════════════════════════
# WrapContexts for pure targets
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class LifecycleWrapContext:
    """Wrap context for lifecycle triggers."""
    execute: Callable[..., Any] | None = None
    order: int = 0


@dataclass(frozen=True, slots=True)
class ExceptionWrapContext:
    """Wrap context for exception triggers."""
    execute: Callable[..., Any] | None = None
    exception_type: type[Exception] = Exception
    propagate: bool = False


@dataclass(frozen=True, slots=True)
class WebSocketWrapContext:
    """Wrap context for websocket triggers."""
    execute: Callable[..., Any] | None = None


from typing import runtime_checkable


@runtime_checkable
class PurePipelineCompilable(Protocol):
    """No-op pipeline protocol for pure targets."""

    def compile_pure_pipeline(self, ctx: object) -> object: ...


# ═══════════════════════════════════════════════════════════════════════════════
# Lifecycle from_codec + assemble
# ═══════════════════════════════════════════════════════════════════════════════


def _lifecycle_delegate_from_codec(
    codec: DelegateCodec,
    trigger: StartupTrigger | ShutdownTrigger,
) -> LifecycleWrapContext:
    """Seed LifecycleWrapContext from DelegateCodec."""
    fn = codec.handler

    async def _execute(handler: Handler[DelegateCodec], **_: Any) -> None:
        if inspect.iscoroutinefunction(fn):
            await fn()
        else:
            fn()

    return LifecycleWrapContext(execute=_execute, order=trigger.order)


def _lifecycle_factory_from_codec(
    codec: ImmediateFactoryCodec,
    trigger: StartupTrigger | ShutdownTrigger,
) -> LifecycleWrapContext:
    """Seed LifecycleWrapContext from ImmediateFactoryCodec."""
    fn = codec.factory

    async def _execute(handler: Handler[ImmediateFactoryCodec], **_: Any) -> None:
        result = fn()
        if inspect.isawaitable(result):
            await result

    return LifecycleWrapContext(execute=_execute, order=trigger.order)


def _assemble_lifecycle(
    ctx: LifecycleWrapContext,
    handler: Handler[Any],
    axes: Axes,
) -> LifecycleRoute:
    """Assemble LifecycleRoute from WrapContext."""
    execute_fn = ctx.execute
    if execute_fn is None:
        raise ValueError("LifecycleWrapContext has no execute function")

    async def _handler() -> None:
        await execute_fn(handler)

    return LifecycleRoute(handler=_handler, order=ctx.order)


# ═══════════════════════════════════════════════════════════════════════════════
# Exception from_codec + assemble
# ═══════════════════════════════════════════════════════════════════════════════


def _exception_delegate_from_codec(
    codec: DelegateCodec,
    trigger: ExceptionTrigger[Exception],
) -> ExceptionWrapContext:
    """Seed ExceptionWrapContext from DelegateCodec."""
    from emergent.graph._compose import Composer

    fn = codec.handler

    async def _execute(handler: Handler[DelegateCodec], scope: Scope) -> Any:
        composer = Composer.create(scope)
        kwargs = await composer.resolve_params(fn)
        if inspect.iscoroutinefunction(fn):
            return await fn(**kwargs)
        return fn(**kwargs)

    return ExceptionWrapContext(
        execute=_execute,
        exception_type=trigger.exception_type,
        propagate=trigger.propagate,
    )


def _assemble_exception(
    ctx: ExceptionWrapContext,
    handler: Handler[Any],
    axes: Axes,
) -> ExceptionRoute:
    """Assemble ExceptionRoute from WrapContext."""
    execute_fn = ctx.execute
    if execute_fn is None:
        raise ValueError("ExceptionWrapContext has no execute function")

    async def _handler(scope: Scope) -> Any:
        return await execute_fn(handler, scope)

    return ExceptionRoute(
        handler=_handler,
        exception_type=ctx.exception_type,
        propagate=ctx.propagate,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# WebSocket from_codec + assemble
# ═══════════════════════════════════════════════════════════════════════════════


def _websocket_delegate_from_codec(
    codec: DelegateCodec,
    trigger: WebSocketTrigger,
) -> WebSocketWrapContext:
    """Seed WebSocketWrapContext from DelegateCodec."""
    from emergent.graph._compose import Composer

    fn = codec.handler

    async def _execute(handler: Handler[DelegateCodec], scope: Scope) -> None:
        composer = Composer.create(scope)
        kwargs = await composer.resolve_params(fn)
        if inspect.iscoroutinefunction(fn):
            await fn(**kwargs)
        else:
            fn(**kwargs)

    return WebSocketWrapContext(execute=_execute)


def _assemble_websocket(
    ctx: WebSocketWrapContext,
    handler: Handler[Any],
    axes: Axes,
) -> WebSocketRoute:
    """Assemble WebSocketRoute from WrapContext."""
    execute_fn = ctx.execute
    if execute_fn is None:
        raise ValueError("WebSocketWrapContext has no execute function")

    async def _handler(scope: Scope) -> None:
        await execute_fn(handler, scope)

    return WebSocketRoute(handler=_handler)


# ═══════════════════════════════════════════════════════════════════════════════
# App Scope Lifecycle
# ═══════════════════════════════════════════════════════════════════════════════


@asynccontextmanager
async def app_scope_lifespan(
    app_scope: Scope,
    compose: Sequence[type] = (),
) -> AsyncIterator[Scope]:
    """Enter app scope, compose App-tier nodes, yield, cleanup."""
    from emergent.graph._compose import Composer

    async with app_scope:
        if compose:
            composer = Composer.create(app_scope)
            await composer.compose_batch(set(compose))
        yield app_scope


# ═══════════════════════════════════════════════════════════════════════════════
# Compilers
# ═══════════════════════════════════════════════════════════════════════════════


STARTUP_COMPILER = TargetCompiler(
    trigger_type=StartupTrigger,
    adapters=(
        CodecBinding(DelegateCodec, _lifecycle_delegate_from_codec),
        CodecBinding(ImmediateFactoryCodec, _lifecycle_factory_from_codec),
    ),
    pipeline_protocol=PurePipelineCompilable,
    pipeline_method="compile_pure_pipeline",
    assemble=_assemble_lifecycle,
)

SHUTDOWN_COMPILER = TargetCompiler(
    trigger_type=ShutdownTrigger,
    adapters=(
        CodecBinding(DelegateCodec, _lifecycle_delegate_from_codec),
        CodecBinding(ImmediateFactoryCodec, _lifecycle_factory_from_codec),
    ),
    pipeline_protocol=PurePipelineCompilable,
    pipeline_method="compile_pure_pipeline",
    assemble=_assemble_lifecycle,
)

EXCEPTION_COMPILER = TargetCompiler(
    trigger_type=ExceptionTrigger,
    adapters=(
        CodecBinding(DelegateCodec, _exception_delegate_from_codec),
    ),
    pipeline_protocol=PurePipelineCompilable,
    pipeline_method="compile_pure_pipeline",
    assemble=_assemble_exception,
)

WEBSOCKET_COMPILER = TargetCompiler(
    trigger_type=WebSocketTrigger,
    adapters=(
        CodecBinding(DelegateCodec, _websocket_delegate_from_codec),
    ),
    pipeline_protocol=PurePipelineCompilable,
    pipeline_method="compile_pure_pipeline",
    assemble=_assemble_websocket,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Backward-compat wrappers
# ═══════════════════════════════════════════════════════════════════════════════


def wrap_lifecycle_delegate(
    handler: Handler[DelegateCodec],
    trigger: StartupTrigger | ShutdownTrigger,
    axes: Axes,
) -> LifecycleRoute:
    ctx = _lifecycle_delegate_from_codec(handler.codec, trigger)
    return _assemble_lifecycle(ctx, handler, axes)


def wrap_lifecycle_factory(
    handler: Handler[ImmediateFactoryCodec],
    trigger: StartupTrigger | ShutdownTrigger,
    axes: Axes,
) -> LifecycleRoute:
    ctx = _lifecycle_factory_from_codec(handler.codec, trigger)
    return _assemble_lifecycle(ctx, handler, axes)


def wrap_exception_delegate(
    handler: Handler[DelegateCodec],
    trigger: ExceptionTrigger[Exception],
    axes: Axes,
) -> ExceptionRoute:
    ctx = _exception_delegate_from_codec(handler.codec, trigger)
    return _assemble_exception(ctx, handler, axes)


def wrap_websocket_delegate(
    handler: Handler[DelegateCodec],
    trigger: WebSocketTrigger,
    axes: Axes,
) -> WebSocketRoute:
    ctx = _websocket_delegate_from_codec(handler.codec, trigger)
    return _assemble_websocket(ctx, handler, axes)


__all__ = (
    "LifecycleRoute",
    "ExceptionRoute",
    "WebSocketRoute",
    "app_scope_lifespan",
    "wrap_lifecycle_delegate",
    "wrap_lifecycle_factory",
    "wrap_exception_delegate",
    "wrap_websocket_delegate",
    "STARTUP_COMPILER",
    "SHUTDOWN_COMPILER",
    "EXCEPTION_COMPILER",
    "WEBSOCKET_COMPILER",
)

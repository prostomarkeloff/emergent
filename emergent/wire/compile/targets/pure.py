"""Pure target — framework-agnostic compilation for non-transport triggers.

Lifecycle, exception, and websocket triggers share a pattern: they don't need
HTTP/CLI/Telegram-specific wrapping. The pure target compiles them to structured
route objects that any framework adapter can consume.

Pattern: framework adapter creates Scope, injects its context, calls route.handler.

    from emergent.wire.compile.targets.pure import STARTUP_COMPILER, EXCEPTION_COMPILER

    # FastAPI adapter
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
from typing import Any

from nodnod import Scope

from emergent.wire.axis.surface._handler import Handler
from emergent.wire.axis.surface.codecs.delegate import DelegateCodec
from emergent.wire.axis.surface.codecs.immediate import ImmediateFactoryCodec
from emergent.wire.axis.surface.triggers.lifecycle import StartupTrigger, ShutdownTrigger
from emergent.wire.axis.surface.triggers.exception import ExceptionTrigger
from emergent.wire.axis.surface.triggers.websocket import WebSocketTrigger
from emergent.wire.compile._core import Axes
from emergent.wire.compile._target import CodecAdapter, TargetCompiler


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
    """Compiled exception handler — takes Scope with injected exception + context.

    handler return type is Any because the response type is framework-specific
    and user-defined (dict, Response, Pydantic model, etc.).
    """

    handler: Callable[[Scope], Awaitable[Any]]
    exception_type: type[Exception]
    propagate: bool


@dataclass(frozen=True, slots=True)
class WebSocketRoute:
    """Compiled websocket handler — takes Scope with injected websocket."""

    handler: Callable[[Scope], Awaitable[None]]


# ═══════════════════════════════════════════════════════════════════════════════
# Lifecycle wrap functions
# ═══════════════════════════════════════════════════════════════════════════════


def wrap_lifecycle_delegate(
    handler: Handler[DelegateCodec],
    trigger: StartupTrigger | ShutdownTrigger,
    axes: Axes,
) -> LifecycleRoute:
    """Wrap DelegateCodec for lifecycle — call handler directly."""
    fn = handler.codec.handler

    async def _handler() -> None:
        if inspect.iscoroutinefunction(fn):
            await fn()
        else:
            fn()

    return LifecycleRoute(handler=_handler, order=trigger.order)


def wrap_lifecycle_factory(
    handler: Handler[ImmediateFactoryCodec],
    trigger: StartupTrigger | ShutdownTrigger,
    axes: Axes,
) -> LifecycleRoute:
    """Wrap ImmediateFactoryCodec for lifecycle — call factory."""
    fn = handler.codec.factory

    async def _handler() -> None:
        result = fn()
        if inspect.isawaitable(result):
            await result

    return LifecycleRoute(handler=_handler, order=trigger.order)


# ═══════════════════════════════════════════════════════════════════════════════
# Exception wrap function
# ═══════════════════════════════════════════════════════════════════════════════


def wrap_exception_delegate(
    handler: Handler[DelegateCodec],
    trigger: ExceptionTrigger[Exception],
    axes: Axes,
) -> ExceptionRoute:
    """Wrap DelegateCodec for exception handling — compose dialect resolves params."""
    from emergent.graph._compose import Composer

    fn = handler.codec.handler

    async def _handler(scope: Scope) -> Any:
        composer = Composer.create(scope)
        kwargs = await composer.resolve_params(fn)
        if inspect.iscoroutinefunction(fn):
            return await fn(**kwargs)
        return fn(**kwargs)

    return ExceptionRoute(
        handler=_handler,
        exception_type=trigger.exception_type,
        propagate=trigger.propagate,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# WebSocket wrap function
# ═══════════════════════════════════════════════════════════════════════════════


def wrap_websocket_delegate(
    handler: Handler[DelegateCodec],
    trigger: WebSocketTrigger,
    axes: Axes,
) -> WebSocketRoute:
    """Wrap DelegateCodec for websocket — compose dialect resolves params."""
    from emergent.graph._compose import Composer

    fn = handler.codec.handler

    async def _handler(scope: Scope) -> None:
        composer = Composer.create(scope)
        kwargs = await composer.resolve_params(fn)
        if inspect.iscoroutinefunction(fn):
            await fn(**kwargs)
        else:
            fn(**kwargs)

    return WebSocketRoute(handler=_handler)


# ═══════════════════════════════════════════════════════════════════════════════
# App Scope Lifecycle
# ═══════════════════════════════════════════════════════════════════════════════


@asynccontextmanager
async def app_scope_lifespan(
    app_scope: Scope,
    compose: Sequence[type] = (),
) -> AsyncIterator[Scope]:
    """Enter app scope, compose App-tier nodes, yield, cleanup.

    Any target compiler uses this for app scope lifecycle:
        async with app_scope_lifespan(scope, [DBPool, Config]):
            # startup handlers, serve requests, etc.
    """
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
        CodecAdapter(DelegateCodec, wrap_lifecycle_delegate),
        CodecAdapter(ImmediateFactoryCodec, wrap_lifecycle_factory),
    ),
)

SHUTDOWN_COMPILER = TargetCompiler(
    trigger_type=ShutdownTrigger,
    adapters=(
        CodecAdapter(DelegateCodec, wrap_lifecycle_delegate),
        CodecAdapter(ImmediateFactoryCodec, wrap_lifecycle_factory),
    ),
)

EXCEPTION_COMPILER = TargetCompiler(
    trigger_type=ExceptionTrigger,
    adapters=(
        CodecAdapter(DelegateCodec, wrap_exception_delegate),
    ),
)

WEBSOCKET_COMPILER = TargetCompiler(
    trigger_type=WebSocketTrigger,
    adapters=(
        CodecAdapter(DelegateCodec, wrap_websocket_delegate),
    ),
)


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

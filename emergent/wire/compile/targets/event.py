"""Event target — compile Application to EventDispatcher.

Target compilation via WrapPhase — same pattern as schema compilation.

    from emergent.wire.compile.targets.event import event_compile

    dispatcher = event_compile(app)
    async with dispatcher:
        results = await dispatcher.dispatch(OrderCreated(order_id=1, total=99.99))
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from nodnod import Scope

from emergent.wire.axis.surface._app import Application
from emergent.wire.axis.surface._handler import Handler
from emergent.wire.axis.surface.codecs.rrc import RequestResponseCodec
from emergent.wire.axis.surface.codecs.delegate import DelegateCodec
from emergent.wire.axis.surface.triggers.event import EventTrigger
from emergent.wire.compile._core import Axes, fold
from emergent.wire.compile._execute import (
    ScopeInjector,
    execute_rrc_unified,
    execute_delegate_unified,
)
from emergent.wire.compile._target import CodecBinding, TargetCompiler
from emergent.wire.compile._lifetime import ScopeLayer, Tier, App, Request
from emergent.wire.compile.targets.pure import app_scope_lifespan

from emergent.graph._family import ScopeFamily


# ═══════════════════════════════════════════════════════════════════════════════
# EventWrapContext — seeded by from_codec, refined by capabilities
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class EventWrapContext:
    """Wrap context for Event target."""

    event_type: type | None = None
    execute: Callable[..., Any] | None = None
    trigger: EventTrigger[object] | None = None


from typing import runtime_checkable


@runtime_checkable
class EventPipelineCompilable(Protocol):
    """Capability that configures Event pipeline."""

    def compile_event_pipeline(
        self, ctx: EventWrapContext,
    ) -> EventWrapContext: ...


# ═══════════════════════════════════════════════════════════════════════════════
# Helper
# ═══════════════════════════════════════════════════════════════════════════════


def _chain_injectors(
    event_inject: Callable[[Scope], None],
    user_inject: ScopeInjector | None,
) -> Callable[[Scope], None]:
    """Chain event injector with optional user injector."""
    if user_inject is None:
        return event_inject

    def combined(scope: Scope) -> None:
        event_inject(scope)
        user_inject(scope)

    return combined


# ═══════════════════════════════════════════════════════════════════════════════
# EventRoute — structured wrap result
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class EventRoute:
    """Compiled event handler — ready to call with event + optional scope injector."""

    event_type: type
    trigger: EventTrigger[object]
    _invoke: Callable[[object, ScopeInjector | None], Awaitable[object]]

    async def call(
        self,
        event: Any,
        inject: ScopeInjector | None = None,
    ) -> Any:
        return await self._invoke(event, inject)


# ═══════════════════════════════════════════════════════════════════════════════
# from_codec functions
# ═══════════════════════════════════════════════════════════════════════════════


def rrc_from_codec_event(
    codec: RequestResponseCodec,
    trigger: EventTrigger[Any],
) -> EventWrapContext:
    """Seed EventWrapContext from RRC codec."""
    return EventWrapContext(
        event_type=trigger.event_type,
        execute=_rrc_execute_event,
        trigger=trigger,
    )


def delegate_from_codec_event(
    codec: DelegateCodec,
    trigger: EventTrigger[Any],
) -> EventWrapContext:
    """Seed EventWrapContext from DelegateCodec."""
    return EventWrapContext(
        event_type=trigger.event_type,
        execute=_delegate_execute_event,
        trigger=trigger,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Execute functions — codec-specific
# ═══════════════════════════════════════════════════════════════════════════════


async def _rrc_execute_event(
    handler: Handler[RequestResponseCodec],
    event: Any,
    inject: ScopeInjector | None,
    axes: Axes,
) -> Any:
    """RRC execution for events."""
    def event_inject(scope: Scope) -> None:
        scope.inject(type(event), event)

    return await execute_rrc_unified(
        handler=handler,
        axes=axes,
        get_value=lambda name: getattr(event, name, None),
        inject_scope=_chain_injectors(event_inject, inject),
    )


async def _delegate_execute_event(
    handler: Handler[DelegateCodec],
    event: Any,
    inject: ScopeInjector | None,
    axes: Axes,
) -> Any:
    """Delegate execution for events."""
    def event_inject(scope: Scope) -> None:
        scope.inject(type(event), event)

    return await execute_delegate_unified(
        handler=handler,
        axes=axes,
        inject_scope=_chain_injectors(event_inject, inject),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Assembler
# ═══════════════════════════════════════════════════════════════════════════════


def assemble_event_route(
    ctx: EventWrapContext,
    handler: Handler[Any],
    axes: Axes,
) -> EventRoute:
    """Assemble EventRoute from compiled WrapContext."""
    execute_fn = ctx.execute
    if execute_fn is None:
        raise ValueError("EventWrapContext.execute must be set before assembly")
    if ctx.event_type is None:
        raise ValueError("EventWrapContext.event_type must be set before assembly")
    if ctx.trigger is None:
        raise ValueError("EventWrapContext.trigger must be set before assembly")

    async def invoke(event: Any, inject: ScopeInjector | None) -> Any:
        return await execute_fn(handler, event, inject, axes)

    return EventRoute(
        event_type=ctx.event_type,
        trigger=ctx.trigger,
        _invoke=invoke,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# EVENT_COMPILER
# ═══════════════════════════════════════════════════════════════════════════════


EVENT_COMPILER: TargetCompiler[EventTrigger[object]] = TargetCompiler(
    trigger_type=EventTrigger,
    adapters=(
        CodecBinding(RequestResponseCodec, rrc_from_codec_event),
        CodecBinding(DelegateCodec, delegate_from_codec_event),
    ),
    pipeline_protocol=EventPipelineCompilable,
    pipeline_method="compile_event_pipeline",
    assemble=assemble_event_route,
)


# ═══════════════════════════════════════════════════════════════════════════════
# EventDispatcher
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class EventDispatcher:
    """Compiled event dispatcher — routes events to handlers by type."""

    routes: Mapping[type, tuple[EventRoute, ...]]
    _app_scope: Scope | None = field(default=None, repr=False)
    _app_compose: frozenset[type] = field(default_factory=lambda: frozenset[type](), repr=False)

    async def dispatch(
        self,
        event: Any,
        inject: ScopeInjector | None = None,
    ) -> tuple[Any, ...]:
        """Dispatch event to all matching handlers."""
        handlers = self.routes.get(type(event), ())
        return tuple([await r.call(event, inject) for r in handlers])

    async def __aenter__(self) -> EventDispatcher:
        if self._app_scope is not None:
            self._lifespan_cm = app_scope_lifespan(
                self._app_scope, list(self._app_compose),
            )
            await self._lifespan_cm.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        cm = getattr(self, "_lifespan_cm", None)
        if cm is not None:
            await cm.__aexit__(exc_type, exc_val, exc_tb)


# ═══════════════════════════════════════════════════════════════════════════════
# event_compile
# ═══════════════════════════════════════════════════════════════════════════════


def event_compile(
    app: Application,
    axes: Axes | None = None,
    compiler: TargetCompiler[EventTrigger[Any]] | None = None,
    family: ScopeFamily[Tier] | None = None,
) -> EventDispatcher:
    """Compile wire Application to EventDispatcher."""
    base_axes = axes or Axes.default()
    _compiler = compiler or EVENT_COMPILER

    app_scope: Scope | None = None
    request_axes = base_axes

    if family is not None:
        from types import MappingProxyType

        app_scope = Scope(detail="event-app")
        layer = ScopeLayer(
            scopes=MappingProxyType({App: app_scope}),
            family=family,
            leaf=Request,
        )
        request_axes = base_axes.with_scope_layer(layer)

    grouped: dict[type, list[EventRoute]] = {}
    for _trigger, _handler, route in _compiler.scan_and_wrap(app, request_axes):
        grouped.setdefault(route.event_type, []).append(route)

    routes: Mapping[type, tuple[EventRoute, ...]] = {
        ev_type: tuple(route_list) for ev_type, route_list in grouped.items()
    }

    app_compose: frozenset[type] = frozenset(family.types_for(App)) if family else frozenset[type]()

    return EventDispatcher(
        routes=routes,
        _app_scope=app_scope,
        _app_compose=app_compose,
    )


__all__ = (
    "EventRoute",
    "EventWrapContext",
    "EventPipelineCompilable",
    "EventDispatcher",
    "EVENT_COMPILER",
    "event_compile",
    "rrc_from_codec_event",
    "delegate_from_codec_event",
    "assemble_event_route",
)

# ═══════════════════════════════════════════════════════════════════════════════
# Backward-compat wrappers
# ═══════════════════════════════════════════════════════════════════════════════


def wrap_rrc_event(
    handler: Handler[RequestResponseCodec],
    trigger: EventTrigger[Any],
    axes: Axes,
) -> EventRoute:
    ctx = rrc_from_codec_event(handler.codec, trigger)
    ctx = fold(handler.capabilities, ctx, EventPipelineCompilable, "compile_event_pipeline", trace=axes.trace)
    return assemble_event_route(ctx, handler, axes)


def wrap_delegate_event(
    handler: Handler[DelegateCodec],
    trigger: EventTrigger[Any],
    axes: Axes,
) -> EventRoute:
    ctx = delegate_from_codec_event(handler.codec, trigger)
    ctx = fold(handler.capabilities, ctx, EventPipelineCompilable, "compile_event_pipeline", trace=axes.trace)
    return assemble_event_route(ctx, handler, axes)


# Alias for cleaner API
compile = event_compile

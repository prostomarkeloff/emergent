"""Event target — compile Application to EventDispatcher.

    from emergent.wire.compile.targets.event import event_compile

    dispatcher = event_compile(app)
    async with dispatcher:
        results = await dispatcher.dispatch(OrderCreated(order_id=1, total=99.99))
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Generic, TypeVar

from nodnod import Scope

from emergent.wire.axis.surface._app import Application
from emergent.wire.axis.surface._handler import Handler
from emergent.wire.axis.surface.codecs.rrc import RequestResponseCodec
from emergent.wire.axis.surface.codecs.delegate import DelegateCodec
from emergent.wire.axis.surface.triggers.event import EventTrigger
from emergent.wire.compile._core import Axes
from emergent.wire.compile._execute import (
    ScopeInjector,
    execute_rrc_unified,
    execute_delegate_unified,
)
from emergent.wire.compile._target import CodecAdapter, TargetCompiler
from emergent.wire.compile._lifetime import ScopeLayer, Tier, App, Request
from emergent.wire.compile.targets.pure import app_scope_lifespan

from emergent.graph._family import ScopeFamily


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
        user_inject(scope)  # type: ignore[arg-type]

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
        event: object,
        inject: ScopeInjector | None = None,
    ) -> object:
        return await self._invoke(event, inject)


# ═══════════════════════════════════════════════════════════════════════════════
# RRC Wrapper
# ═══════════════════════════════════════════════════════════════════════════════


def wrap_rrc_event(
    handler: Handler[RequestResponseCodec],
    trigger: EventTrigger[object],
    axes: Axes,
) -> EventRoute:
    """Wrap RRC handler for event dispatch — event fields become request values."""

    async def invoke(event: object, inject: ScopeInjector | None) -> object:
        def event_inject(scope: Scope) -> None:
            scope.inject(type(event), event)

        return await execute_rrc_unified(
            handler=handler,
            axes=axes,
            get_value=lambda name: getattr(event, name, None),
            inject_scope=_chain_injectors(event_inject, inject),
        )

    return EventRoute(
        event_type=trigger.event_type,
        trigger=trigger,
        _invoke=invoke,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Delegate Wrapper
# ═══════════════════════════════════════════════════════════════════════════════


def wrap_delegate_event(
    handler: Handler[DelegateCodec],
    trigger: EventTrigger[object],
    axes: Axes,
) -> EventRoute:
    """Wrap DelegateCodec for event dispatch — event injected into scope."""

    async def invoke(event: object, inject: ScopeInjector | None) -> object:
        def event_inject(scope: Scope) -> None:
            scope.inject(type(event), event)

        return await execute_delegate_unified(
            handler=handler,
            axes=axes,
            inject_scope=_chain_injectors(event_inject, inject),
        )

    return EventRoute(
        event_type=trigger.event_type,
        trigger=trigger,
        _invoke=invoke,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# EVENT_COMPILER
# ═══════════════════════════════════════════════════════════════════════════════


EVENT_COMPILER: TargetCompiler[EventTrigger[object]] = TargetCompiler(
    trigger_type=EventTrigger,
    adapters=(
        CodecAdapter(RequestResponseCodec, wrap_rrc_event),
        CodecAdapter(DelegateCodec, wrap_delegate_event),
    ),
)


# ═══════════════════════════════════════════════════════════════════════════════
# EventDispatcher
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class EventDispatcher:
    """Compiled event dispatcher — routes events to handlers by type.

    Usage::

        dispatcher = event_compile(app)
        async with dispatcher:
            results = await dispatcher.dispatch(OrderCreated(order_id=1, total=99.99))
    """

    routes: Mapping[type, tuple[EventRoute, ...]]
    _app_scope: Scope | None = field(default=None, repr=False)
    _app_compose: frozenset[type] = field(default_factory=frozenset, repr=False)

    async def dispatch(
        self,
        event: object,
        inject: ScopeInjector | None = None,
    ) -> tuple[object, ...]:
        """Dispatch event to all matching handlers.

        Returns tuple of results from each handler.
        """
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
    compiler: TargetCompiler[EventTrigger[object]] | None = None,
    family: ScopeFamily[Tier] | None = None,
) -> EventDispatcher:
    """Compile wire Application to EventDispatcher.

    Args:
        app: Wire application
        axes: Axes context (default: Axes.default())
        compiler: TargetCompiler (default: EVENT_COMPILER). Pass custom
                  compiler to add/swap/remove codec adapters.
        family: Optional ScopeFamily for tiered scope management.

    Returns:
        EventDispatcher ready for dispatch (use as async context manager
        when family is provided).
    """
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

    # Scan and wrap all event handlers
    grouped: dict[type, list[EventRoute]] = {}
    for trigger, handler, route in _compiler.scan_and_wrap(app, request_axes):
        grouped.setdefault(route.event_type, []).append(route)

    routes: Mapping[type, tuple[EventRoute, ...]] = {
        ev_type: tuple(route_list) for ev_type, route_list in grouped.items()
    }

    app_compose = frozenset(family.types_for(App)) if family else frozenset()

    return EventDispatcher(
        routes=routes,
        _app_scope=app_scope,
        _app_compose=app_compose,
    )


__all__ = (
    "EventRoute",
    "EventDispatcher",
    "EVENT_COMPILER",
    "event_compile",
    "wrap_rrc_event",
    "wrap_delegate_event",
)

# Alias for cleaner API
compile = event_compile

"""SSE execution — mirrors wire's _rrc.py + _execute.py layering.

Layer 1 (core): execute_sse(handler, request, scope)
  - enrichers → to_domain → runner.run → raw Result
  - Like execute_rrc but no from_domain (streaming has no single response)

Layer 2 (unified): execute_sse_unified(handler, axes, get_value, inject_scope)
  - Scope setup, request building, enrichers — same for all frameworks
  - Adapters just provide get_value + inject_scope

    from derivelib.examples.exotic_codec.execute import execute_sse_unified

    # FastAPI adapter becomes trivial:
    async def route(request: Request) -> StreamingResponse:
        result = await execute_sse_unified(
            handler=handler,
            axes=axes,
            get_value=lambda name: body.get(name),
            inject_scope=lambda scope: scope.inject(Request, request),
        )
        return StreamingResponse(format_sse(result), ...)
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from nodnod import Scope
from nodnod.agent.event_loop.agent import EventLoopAgent

from emergent.wire.axis.surface._handler import Handler
from emergent.wire.axis.surface.enrichers import ScopeEnricher, chain_enrichers
from emergent.wire.compile._core import Axes
from emergent.wire.compile._request import build_request

from kungfu import Result

from .codec import ServerSentEventsCodec

if TYPE_CHECKING:
    from nodnod.agent.base import Agent
    from emergent.wire.axis.surface.codecs.rrc import ToDomain
    from emergent.ops._graph import Op


# ═══════════════════════════════════════════════════════════════════════════════
# Layer 1: Core execution (mirrors _rrc.py → execute_rrc)
# ═══════════════════════════════════════════════════════════════════════════════


async def execute_sse[EventT](
    handler: Handler[ServerSentEventsCodec[EventT]],
    request: ToDomain[Op[object, object]],
    scope: Scope,
) -> Result[object, object]:
    """Core SSE execution pipeline.

    Pure async function:
    1. Extract ScopeEnricher capabilities
    2. Chain enrichers around core handler
    3. Execute: enrichers → request.to_domain() → Op → runner.run()

    Like execute_rrc but returns raw Result (no from_domain).
    The raw Result is what gets streamed by the adapter.
    """
    async def core_handler(scope: Scope) -> Result[object, object]:
        op: Op[object, object] = request.to_domain()
        scope_extras: dict[type, object] = {}
        for key, value in scope.items():
            if key is not Scope:
                scope_extras[key] = value.value
        return await handler.runner.run(op, scope_extras=scope_extras)

    enrichers = tuple(
        cap for cap in handler.capabilities
        if isinstance(cap, ScopeEnricher)
    )

    if enrichers:
        return await chain_enrichers(enrichers, core_handler)(scope)
    else:
        return await core_handler(scope)


# ═══════════════════════════════════════════════════════════════════════════════
# Layer 2: Unified execution (mirrors _execute.py → execute_rrc_unified)
# ═══════════════════════════════════════════════════════════════════════════════


# Same type aliases as wire's _execute.py
ValueGetter = Callable[[str], str | int | float | bool | None]
ScopeInjector = Callable[[Scope], None] | Callable[[Scope], Awaitable[None]]


async def execute_sse_unified[EventT](
    handler: Handler[ServerSentEventsCodec[EventT]],
    axes: Axes,
    get_value: ValueGetter,
    inject_scope: ScopeInjector,
    agent_cls: type[Agent] | None = None,
) -> Result[object, object]:
    """Unified SSE execution — same for all frameworks.

    This is THE handler logic. Adapters just provide the pieces.
    Returns raw domain Result for the adapter to stream.

    Args:
        handler: SSE handler with codec and capabilities
        axes: Compilation axes
        get_value: Extract field value by name from framework context
        inject_scope: Inject framework types into scope
        agent_cls: nodnod Agent class (default: EventLoopAgent)

    Returns:
        Raw domain Result (Ok(list[entity]) or Error)
    """
    req_cls: type[ToDomain[Op[object, object]]] = handler.codec.request
    _agent_cls: type[Agent] = agent_cls or EventLoopAgent

    async with Scope() as scope:
        # 1. Inject framework context
        result = inject_scope(scope)
        if result is not None and hasattr(result, "__await__"):
            await result

        # 2. Build request using unified function
        request: ToDomain[Op[object, object]] = await build_request(
            request_cls=req_cls,
            get_value=get_value,
            agent_cls=_agent_cls,
            scope=scope,
        )

        # 3. Inject request for enrichers
        scope.inject(req_cls, request)

        # 4. Execute with enrichers
        return await execute_sse(handler, request, scope)


__all__ = (
    "execute_sse",
    "execute_sse_unified",
    "ValueGetter",
    "ScopeInjector",
)

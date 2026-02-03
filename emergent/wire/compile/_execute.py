"""Unified execution — makes target-specific compilers trivial.

All behavior is unified here. Adapters just provide:
- ScopeSetup: inject framework context into scope
- ValueGetter: extract field values from context
- ResponseFormatter: format response for framework

    from emergent.wire.compile._execute import compile_rrc_handler

    # FastAPI adapter becomes trivial:
    async def route(request: Request) -> Any:
        body = await request.json()
        return await compile_rrc_handler(
            handler=handler,
            axes=axes,
            get_value=lambda name: body.get(name),
            inject_scope=lambda scope: scope.inject(Request, request),
        )
"""

from __future__ import annotations

from typing import Any, Callable, Awaitable, TYPE_CHECKING

from nodnod import Scope
from nodnod.agent.event_loop.agent import EventLoopAgent

from emergent.wire.axis.surface._handler import Handler
from emergent.wire.axis.surface.codecs.rrc import RequestResponseCodec
from emergent.wire.axis.surface.codecs.stateful import StatefulCodec
from emergent.wire.compile._core import Axes
from emergent.wire.compile._rrc import execute_rrc
from emergent.wire.compile._request import build_request
from emergent.wire.compile._capabilities import apply_response_capabilities
from emergent.wire.compile._stateful import (
    execute_stateful_turn,
    execute_stateful_done,
    load_state,
    save_state,
    delete_state,
)

if TYPE_CHECKING:
    from nodnod.agent.base import Agent


# ═══════════════════════════════════════════════════════════════════════════════
# Type Aliases
# ═══════════════════════════════════════════════════════════════════════════════


# Function to get field value by name from framework context
ValueGetter = Callable[[str], Any]

# Function to inject framework context into scope
ScopeInjector = Callable[[Scope], None] | Callable[[Scope], Awaitable[None]]

# Function to format response for framework
ResponseFormatter = Callable[[Any], Any]


# ═══════════════════════════════════════════════════════════════════════════════
# RRC Execution
# ═══════════════════════════════════════════════════════════════════════════════


async def execute_rrc_unified(
    handler: Handler[RequestResponseCodec],
    axes: Axes,
    get_value: ValueGetter,
    inject_scope: ScopeInjector,
    agent_cls: type[Agent] | None = None,
    format_response: ResponseFormatter | None = None,
) -> Any:
    """Unified RRC execution — same for all frameworks.

    This is THE handler logic. Adapters just provide the pieces.

    Args:
        handler: RRC handler with codec and capabilities
        axes: Compilation axes
        get_value: Extract field value by name from framework context
        inject_scope: Inject framework types into scope
        agent_cls: nodnod Agent class (default: EventLoopAgent)
        format_response: Optional response formatter

    Returns:
        Formatted response
    """
    req_cls = handler.codec.request
    _agent_cls = agent_cls or EventLoopAgent

    async with Scope() as scope:
        # 1. Inject framework context
        result = inject_scope(scope)
        if result is not None and hasattr(result, "__await__"):
            await result

        # 2. Build request using unified function
        request = await build_request(
            request_cls=req_cls,
            get_value=get_value,
            agent_cls=_agent_cls,
            scope=scope,
        )

        # 3. Inject request for enrichers
        scope.inject(req_cls, request)

        # 4. Execute with enrichers
        response = await execute_rrc(handler, request, scope)

    # 5. Apply response capabilities
    response = apply_response_capabilities(response, handler.capabilities)

    # 6. Format response
    if format_response is not None:
        response = format_response(response)

    return response


# ═══════════════════════════════════════════════════════════════════════════════
# Stateful Execution
# ═══════════════════════════════════════════════════════════════════════════════


async def execute_stateful_unified(
    handler: Handler[StatefulCodec],
    store_key: str,
    resolve_transition: Callable[..., Awaitable[tuple[Any, dict[str, Any]] | None]],
    inject_scope: ScopeInjector,
    format_response: ResponseFormatter | None = None,
) -> tuple[Any, bool]:
    """Unified stateful turn execution.

    Args:
        handler: Stateful handler
        store_key: Key for state store
        resolve_transition: Async function returning (method, composed_params) or None
        inject_scope: Inject framework types into scope
        format_response: Optional response formatter

    Returns:
        (response, is_done)
    """
    codec = handler.codec

    # 1. Load state
    state = await load_state(codec, store_key)

    # 2. Resolve transition
    resolved = await resolve_transition()
    if resolved is None:
        raise RuntimeError("No transition resolvable")

    method, composed = resolved

    # 3. Execute transition
    new_state, response, is_terminal = await execute_stateful_turn(
        handler, state, method, composed
    )

    # 4. Continue or Done
    if not is_terminal:
        await save_state(codec, store_key, state, new_state)
        if response is not None and format_response is not None:
            response = format_response(
                apply_response_capabilities(response, handler.capabilities)
            )
        return response, False

    # 5. Done — execute with enrichers
    async with Scope() as done_scope:
        result = inject_scope(done_scope)
        if result is not None and hasattr(result, "__await__"):
            await result
        final = await execute_stateful_done(handler, new_state, done_scope)

    await delete_state(codec, store_key)

    # 6. Apply response capabilities
    final = apply_response_capabilities(final, handler.capabilities)

    if format_response is not None:
        final = format_response(final)

    return final, True


# ═══════════════════════════════════════════════════════════════════════════════
# Immediate Execution
# ═══════════════════════════════════════════════════════════════════════════════


def execute_immediate_unified(
    handler: Handler[Any],
    format_response: ResponseFormatter | None = None,
) -> Any:
    """Unified immediate execution — produces response directly.

    Args:
        handler: Handler with ImmediateCodec or ImmediateFactoryCodec
        format_response: Optional response formatter

    Returns:
        Formatted response
    """
    from emergent.wire.axis.surface.codecs.immediate import ImmediateCodec, ImmediateFactoryCodec

    codec = handler.codec

    if isinstance(codec, ImmediateCodec):
        response = codec.response.produce()
    elif isinstance(codec, ImmediateFactoryCodec):
        response = codec.factory()
    else:
        raise TypeError(f"Expected ImmediateCodec or ImmediateFactoryCodec, got {type(codec)}")

    # Apply response capabilities
    response = apply_response_capabilities(response, handler.capabilities)

    if format_response is not None:
        response = format_response(response)

    return response


# ═══════════════════════════════════════════════════════════════════════════════
# Delegate Execution
# ═══════════════════════════════════════════════════════════════════════════════


async def execute_delegate_unified(
    handler: Handler[Any],
    inject_scope: ScopeInjector,
    agent_cls: type[Agent] | None = None,
    format_response: ResponseFormatter | None = None,
) -> Any:
    """Unified delegate execution — compose dialect works by default.

    Compose dialect (compose.Node, compose.Retrieve, compose.Optional) is
    resolved automatically on handler params. No capability needed.

    Args:
        handler: DelegateCodec handler
        inject_scope: Inject framework types into scope
        agent_cls: nodnod Agent class (default: EventLoopAgent)
        format_response: Optional response formatter

    Returns:
        Formatted response
    """
    from emergent.wire.axis.surface.capabilities._base import ScopeEnricher
    from emergent.wire.axis.surface.capabilities._delegate import resolve_handler_params
    from emergent.wire.compile._rrc import chain_enrichers

    _agent_cls = agent_cls or EventLoopAgent
    original = handler.codec.handler

    # Collect enrichers
    enrichers = tuple(
        cap for cap in handler.capabilities if isinstance(cap, ScopeEnricher)
    )

    async with Scope() as scope:
        # 1. Inject framework context
        result = inject_scope(scope)
        if result is not None and hasattr(result, "__await__"):
            await result

        # 2. Core execution — resolve params via compose dialect
        async def core(s: Scope) -> Any:
            kwargs = await resolve_handler_params(original, s, _agent_cls)
            return await _call_delegate(original, **kwargs)

        # 3. Execute with enrichers
        if enrichers:
            response = await chain_enrichers(enrichers, core)(scope)
        else:
            response = await core(scope)

    # 4. Apply response capabilities
    response = apply_response_capabilities(response, handler.capabilities)

    # 5. Format response
    if format_response is not None:
        response = format_response(response)

    return response


async def _call_delegate(handler: Callable[..., Any], **kwargs: Any) -> Any:
    """Call delegate handler (sync or async)."""
    import asyncio
    import inspect

    if inspect.iscoroutinefunction(handler):
        return await handler(**kwargs)
    else:
        return await asyncio.to_thread(handler, **kwargs)


__all__ = (
    "ValueGetter",
    "ScopeInjector",
    "ResponseFormatter",
    "execute_rrc_unified",
    "execute_stateful_unified",
    "execute_immediate_unified",
    "execute_delegate_unified",
)

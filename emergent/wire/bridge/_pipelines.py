"""Extraction pipelines — unified extraction for each trigger type.

Like compile/_execute.py provides unified execution for each codec type,
this module provides unified extraction for each trigger type.

    from emergent.wire.bridge._pipelines import extract_http_unified

    extracted = extract_http_unified(route_data, handler, axes, capabilities)
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from emergent.wire.bridge._core import BridgeAxes, ExtractedHandler
from emergent.wire.bridge._analyze import HandlerAnalysis, analyze_handler
from emergent.wire.bridge._capabilities import (
    BridgeCapability,
    BridgeContext,
    apply_bridge_capabilities,
    apply_purifiers,
)
from emergent.wire.bridge._source import LifecycleData, ExceptionData, WebSocketData


# ═══════════════════════════════════════════════════════════════════════════════
# HTTP Extraction Pipeline
# ═══════════════════════════════════════════════════════════════════════════════


def extract_http_unified[T, **P, R](
    route_data: T,
    handler: Callable[P, R],
    axes: BridgeAxes,
    capabilities: Sequence[BridgeCapability] = (),
) -> tuple[ExtractedHandler[T, P, R] | None, HandlerAnalysis]:
    """Unified HTTP route extraction pipeline.

    Steps:
    1. Analyze handler (discover parameters, depends, types)
    2. Build context with analysis
    3. Apply BridgeCompilable capabilities
    4. Apply Purifiers to handler
    5. Return ExtractedHandler

    Args:
        route_data: Source-specific trigger data
        handler: Handler callable
        axes: Bridge axes with inspector
        capabilities: Bridge capabilities to apply

    Returns:
        Tuple of (ExtractedHandler or None if skipped, HandlerAnalysis)
    """
    # 1. Analyze handler
    analysis = analyze_handler(handler)

    # 2. Inspect types via axes inspector
    request_type = axes.inspector.request_type(handler)
    response_type = axes.inspector.response_type(handler)

    # 3. Build initial context
    ctx: BridgeContext[T, P, R] = BridgeContext(
        trigger_data=route_data,
        handler=handler,
        request_type=request_type,
        response_type=response_type,
        name=analysis.name,
        description=analysis.docstring,
    )

    # 4. Apply BridgeCompilable capabilities
    ctx = apply_bridge_capabilities(ctx, capabilities)
    if ctx.skip:
        return None, analysis

    # 5. Apply Purifiers to handler
    wrapped_handler = apply_purifiers(ctx.handler, capabilities)

    # 6. Build and return ExtractedHandler
    extracted = ExtractedHandler(
        trigger_data=ctx.trigger_data,
        handler=wrapped_handler,
        name=ctx.name,
        description=ctx.description,
        deprecated=ctx.deprecated,
        wire=ctx.wire,
    )

    return extracted, analysis


# ═══════════════════════════════════════════════════════════════════════════════
# Lifecycle Extraction Pipeline
# ═══════════════════════════════════════════════════════════════════════════════


def extract_lifecycle_unified[**P, R](
    lifecycle_data: LifecycleData,
    handler: Callable[P, R],
    axes: BridgeAxes,
    capabilities: Sequence[BridgeCapability] = (),
) -> tuple[ExtractedHandler[LifecycleData, P, R] | None, HandlerAnalysis]:
    """Unified lifecycle extraction pipeline.

    Args:
        lifecycle_data: Lifecycle trigger data (startup/shutdown)
        handler: Lifecycle handler
        axes: Bridge axes
        capabilities: Bridge capabilities

    Returns:
        Tuple of (ExtractedHandler or None, HandlerAnalysis)
    """
    # 1. Analyze handler
    analysis = analyze_handler(handler)

    # 2. Build context (lifecycle handlers typically have no request/response types)
    ctx: BridgeContext[LifecycleData, P, R] = BridgeContext(
        trigger_data=lifecycle_data,
        handler=handler,
        request_type=None,
        response_type=None,
        name=analysis.name,
        description=analysis.docstring,
    )

    # 3. Apply capabilities
    ctx = apply_bridge_capabilities(ctx, capabilities)
    if ctx.skip:
        return None, analysis

    # 4. Apply Purifiers
    wrapped_handler = apply_purifiers(ctx.handler, capabilities)

    # 5. Return ExtractedHandler
    extracted = ExtractedHandler(
        trigger_data=ctx.trigger_data,
        handler=wrapped_handler,
        name=ctx.name,
        description=ctx.description,
        deprecated=ctx.deprecated,
        wire=ctx.wire,
    )

    return extracted, analysis


# ═══════════════════════════════════════════════════════════════════════════════
# WebSocket Extraction Pipeline
# ═══════════════════════════════════════════════════════════════════════════════


def extract_websocket_unified[**P, R](
    ws_data: WebSocketData,
    handler: Callable[P, R],
    axes: BridgeAxes,
    capabilities: Sequence[BridgeCapability] = (),
) -> tuple[ExtractedHandler[WebSocketData, P, R] | None, HandlerAnalysis]:
    """Unified websocket extraction pipeline.

    Args:
        ws_data: WebSocket trigger data
        handler: WebSocket handler
        axes: Bridge axes
        capabilities: Bridge capabilities

    Returns:
        Tuple of (ExtractedHandler or None, HandlerAnalysis)
    """
    # 1. Analyze handler
    analysis = analyze_handler(handler)

    # 2. Inspect types
    request_type = axes.inspector.request_type(handler)
    response_type = axes.inspector.response_type(handler)

    # 3. Build context
    ctx: BridgeContext[WebSocketData, P, R] = BridgeContext(
        trigger_data=ws_data,
        handler=handler,
        request_type=request_type,
        response_type=response_type,
        name=analysis.name,
        description=analysis.docstring,
    )

    # 4. Apply capabilities
    ctx = apply_bridge_capabilities(ctx, capabilities)
    if ctx.skip:
        return None, analysis

    # 5. Apply Purifiers
    wrapped_handler = apply_purifiers(ctx.handler, capabilities)

    # 6. Return ExtractedHandler
    extracted = ExtractedHandler(
        trigger_data=ctx.trigger_data,
        handler=wrapped_handler,
        name=ctx.name,
        description=ctx.description,
        deprecated=ctx.deprecated,
        wire=ctx.wire,
    )

    return extracted, analysis


# ═══════════════════════════════════════════════════════════════════════════════
# Exception Handler Extraction Pipeline
# ═══════════════════════════════════════════════════════════════════════════════


def extract_exception_unified[**P, R](
    exc_data: ExceptionData,
    handler: Callable[P, R],
    axes: BridgeAxes,
    capabilities: Sequence[BridgeCapability] = (),
) -> tuple[ExtractedHandler[ExceptionData, P, R] | None, HandlerAnalysis]:
    """Unified exception handler extraction pipeline.

    Args:
        exc_data: Exception trigger data
        handler: Exception handler
        axes: Bridge axes
        capabilities: Bridge capabilities

    Returns:
        Tuple of (ExtractedHandler or None, HandlerAnalysis)
    """
    # 1. Analyze handler
    analysis = analyze_handler(handler)

    # 2. Inspect types
    response_type = axes.inspector.response_type(handler)

    # 3. Build context (request is the exception)
    ctx: BridgeContext[ExceptionData, P, R] = BridgeContext(
        trigger_data=exc_data,
        handler=handler,
        request_type=exc_data.exception_type,
        response_type=response_type,
        name=analysis.name,
        description=analysis.docstring,
    )

    # 4. Apply capabilities
    ctx = apply_bridge_capabilities(ctx, capabilities)
    if ctx.skip:
        return None, analysis

    # 5. Apply Purifiers
    wrapped_handler = apply_purifiers(ctx.handler, capabilities)

    # 6. Return ExtractedHandler
    extracted = ExtractedHandler(
        trigger_data=ctx.trigger_data,
        handler=wrapped_handler,
        name=ctx.name,
        description=ctx.description,
        deprecated=ctx.deprecated,
        wire=ctx.wire,
    )

    return extracted, analysis


# ═══════════════════════════════════════════════════════════════════════════════
# Generic Extraction Pipeline
# ═══════════════════════════════════════════════════════════════════════════════


def extract_generic_unified[T, **P, R](
    trigger_data: T,
    handler: Callable[P, R],
    axes: BridgeAxes,
    capabilities: Sequence[BridgeCapability] = (),
) -> tuple[ExtractedHandler[T, P, R] | None, HandlerAnalysis]:
    """Generic extraction pipeline for any trigger type.

    Use specific pipelines (extract_http_unified, etc.) when possible
    for better type inference.

    Args:
        trigger_data: Any trigger data
        handler: Handler callable
        axes: Bridge axes
        capabilities: Bridge capabilities

    Returns:
        Tuple of (ExtractedHandler or None, HandlerAnalysis)
    """
    # 1. Analyze handler
    analysis = analyze_handler(handler)

    # 2. Inspect types
    request_type = axes.inspector.request_type(handler)
    response_type = axes.inspector.response_type(handler)

    # 3. Build context
    ctx: BridgeContext[T, P, R] = BridgeContext(
        trigger_data=trigger_data,
        handler=handler,
        request_type=request_type,
        response_type=response_type,
        name=analysis.name,
        description=analysis.docstring,
    )

    # 4. Apply capabilities
    ctx = apply_bridge_capabilities(ctx, capabilities)
    if ctx.skip:
        return None, analysis

    # 5. Apply Purifiers
    wrapped_handler = apply_purifiers(ctx.handler, capabilities)

    # 6. Return ExtractedHandler
    extracted = ExtractedHandler(
        trigger_data=ctx.trigger_data,
        handler=wrapped_handler,
        name=ctx.name,
        description=ctx.description,
        deprecated=ctx.deprecated,
        wire=ctx.wire,
    )

    return extracted, analysis


__all__ = (
    "extract_http_unified",
    "extract_lifecycle_unified",
    "extract_websocket_unified",
    "extract_exception_unified",
    "extract_generic_unified",
)

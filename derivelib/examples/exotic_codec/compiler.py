"""FastAPI compiler extension for ServerSentEventsCodec.

Thin adapter — mirrors wire's targets/fastapi.py pattern:
  - wrap_rrc_fastapi parses HTTP → calls execute_rrc_unified
  - wrap_sse_fastapi parses HTTP → calls execute_sse_unified → formats SSE

Serialization (dataclass → JSON) is compiler-level concern.
Execution pipeline lives in execute.py.

    from derivelib.examples.exotic_codec.compiler import SSE_COMPILER

    fastapi_app = fastapi.compile(app, compiler=SSE_COMPILER)
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import AsyncIterator
from typing import Any as _AnyCompiler
from kungfu import Result

import fastapi
from kungfu import Ok, Error
from starlette.responses import StreamingResponse

from emergent.wire.axis.surface._handler import Handler
from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger
from emergent.wire.compile._core import Axes
from emergent.wire.compile._target import TargetCompiler
from emergent.wire.compile.targets.fastapi import FASTAPI_COMPILER, FastAPIRoute

from .codec import ServerSentEventsCodec
from .execute import execute_sse_unified


# ═══════════════════════════════════════════════════════════════════════════════
# Serialization — compiler's concern
# ═══════════════════════════════════════════════════════════════════════════════


def serialize_entity(entity: object) -> str:
    """Serialize entity to JSON string for SSE data field.

    Uses ``object`` because this accepts dataclasses, dicts, or any JSON-serializable
    value — no single Protocol captures this; runtime isinstance dispatch decides.
    """
    if dataclasses.is_dataclass(entity) and not isinstance(entity, type):
        return json.dumps(dataclasses.asdict(entity))
    if isinstance(entity, dict):
        return json.dumps(entity)
    return json.dumps({"value": entity})


def format_sse_stream(domain_result: Result[_AnyCompiler, _AnyCompiler]) -> AsyncIterator[str]:
    """Format domain Result as SSE event stream.

    SSE format per event:
        id: <sequence>
        event: entity
        data: <json>

    Terminal:
        event: done
        data: {"total": N}

    Error:
        event: error
        data: {"error": "..."}

    Uses Any for Result type parameters because:
    - Handler returns Result[object, object] from runner.run()
    - pyright can't track object through isinstance checks for list elements
    - Actual runtime types are determined by the handler template (FetchMany, etc.)
    - serialize_entity accepts object parameter, so this is safe
    - No alternative without cast() or type: ignore (both forbidden)
    """
    async def _stream() -> AsyncIterator[str]:
        match domain_result:
            case Ok(items):
                # items has type Any - can be single entity or list of entities
                # Avoid isinstance because pyright creates Unknown element types
                #
                # Convert to iterable using try/except instead of isinstance
                # This avoids type narrowing issues
                try:
                    # Try to iterate - works for lists. iter() accepts Any.
                    items_iter: _AnyCompiler = iter(items)
                    count: int = 0
                    for item_obj in items_iter:
                        item_typed: _AnyCompiler = item_obj
                        data = serialize_entity(item_typed)
                        yield f"id: {count}\nevent: entity\ndata: {data}\n\n"
                        count += 1
                    yield f"event: done\ndata: {json.dumps({'total': count})}\n\n"
                except TypeError:
                    # Not iterable, single item
                    data = serialize_entity(items)
                    yield f"id: 0\nevent: entity\ndata: {data}\n\n"
                    yield f"event: done\ndata: {json.dumps({'total': 1})}\n\n"
            case Error(err):
                yield f"event: error\ndata: {json.dumps({'error': str(err)})}\n\n"

    return _stream()


# ═══════════════════════════════════════════════════════════════════════════════
# Thin FastAPI adapter (mirrors wrap_rrc_fastapi)
# ═══════════════════════════════════════════════════════════════════════════════


def wrap_sse_fastapi[EventT](
    handler: Handler[ServerSentEventsCodec[EventT]],
    trigger: HTTPRouteTrigger,
    axes: Axes,
) -> FastAPIRoute:
    """Wrap SSE codec for FastAPI — thin adapter.

    1. Parse HTTP request → coerce via Pydantic
    2. Call execute_sse_unified (all logic lives there)
    3. Format as StreamingResponse
    """
    from emergent.wire.compile._generate import to_pydantic
    from emergent.wire.axis.surface.codecs.rrc import ToDomain
    from emergent.ops._graph import Op

    req_cls: type[ToDomain[Op[object, object]]] = handler.codec.request
    RequestModel = to_pydantic(req_cls, axes)

    async def _route(request: fastapi.Request) -> StreamingResponse:
        # 1. Parse + coerce request (identical to wrap_rrc_fastapi)
        if trigger.method in ("POST", "PUT", "PATCH"):
            try:
                body: dict[str, object] = await request.json()
            except Exception:
                body = {}
        else:
            body = dict(request.query_params)

        all_values: dict[str, object] = {**body, **dict(request.path_params)}
        pydantic_instance = RequestModel(**all_values)
        coerced: dict[str, object] = pydantic_instance.model_dump()

        # 2. Unified execution — all logic lives in execute.py
        def get_value_typed(name: str) -> str | int | float | bool | None:
            val = coerced.get(name)
            if isinstance(val, (str, int, float, bool)) or val is None:
                return val
            return str(val)

        domain_result = await execute_sse_unified(
            handler=handler,
            axes=axes,
            get_value=get_value_typed,
            inject_scope=lambda scope: scope.inject(fastapi.Request, request),
        )

        # 3. Format as SSE stream
        return StreamingResponse(
            format_sse_stream(domain_result),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
        )

    _route.__annotations__ = {
        "request": fastapi.Request,
        "return": StreamingResponse,
    }
    return FastAPIRoute(endpoint=_route)


# ═══════════════════════════════════════════════════════════════════════════════
# Extended Compiler — one line, open-world
# ═══════════════════════════════════════════════════════════════════════════════


SSE_COMPILER: TargetCompiler[HTTPRouteTrigger] = FASTAPI_COMPILER.with_codec(
    ServerSentEventsCodec, wrap_sse_fastapi
)


__all__ = ("wrap_sse_fastapi", "serialize_entity", "format_sse_stream", "SSE_COMPILER")

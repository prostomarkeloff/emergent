"""RRC compilation — universal request-response handler.

Single implementation, parameterized by wrapper.

    from emergent.wire.compiler import compile_rrc

    # FastAPI
    route = compile_rrc(handler, axes, fastapi_wrapper)

    # CLI
    cmd = compile_rrc(handler, axes, cli_wrapper)
"""

from __future__ import annotations

from typing import Any, Callable, TypeVar

from kungfu import Ok, Error

from emergent.wire._handler import Handler
from emergent.wire.axis.surface.codecs.rrc import RequestResponseCodec


T = TypeVar("T")


async def execute_rrc(
    handler: Handler[RequestResponseCodec],
    request: Any,
) -> Any:
    """Universal RRC execution pipeline.

    Pure async function:
    1. Run middlewares → build scope_extras
    2. request.to_domain() → Op
    3. runner.run(op, scope_extras) → Result
    4. response.from_domain(result) → response

    Same logic for all frameworks.
    """
    codec = handler.codec
    scope_extras: dict[type, object] = {}

    # Middlewares
    for mw in codec.middlewares:
        mw_op = mw.build(request)
        mw_result = await mw.runner.run(mw_op)
        match mw_result:
            case Ok(value):
                scope_extras[mw.inject_as] = value
            case Error():
                return mw.reject(mw_result)

    # Main pipeline
    op = request.to_domain()
    result = await handler.runner.run(op, scope_extras=scope_extras)
    return codec.response.from_domain(result)


def compile_rrc(
    handler: Handler[RequestResponseCodec],
    wrap: Callable[[Callable[..., Any]], T],
) -> T:
    """Compile RRC handler with framework-specific wrapper.

    Args:
        handler: RRC handler bundle
        wrap: Framework wrapper (adds annotations, routing, etc.)

    Returns:
        Framework-specific handler artifact

    Example:
        # FastAPI wrapper adds type annotations for OpenAPI
        def fastapi_wrap(fn):
            fn.__annotations__ = {"req": RequestType, "return": ResponseType}
            return fn

        route = compile_rrc(handler, fastapi_wrap)
    """
    async def _handler(request: Any) -> Any:
        return await execute_rrc(handler, request)

    return wrap(_handler)


__all__ = (
    "execute_rrc",
    "compile_rrc",
)

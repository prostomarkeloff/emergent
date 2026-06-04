"""RRC compilation — universal request-response handler.

Single implementation, parameterized by wrapper.

    from emergent.wire.compile import compile_rrc

    # FastAPI
    route = compile_rrc(handler, axes, fastapi_wrapper)

    # CLI
    cmd = compile_rrc(handler, axes, cli_wrapper)
"""

from __future__ import annotations

from typing import Any

from nodnod import Scope

from emergent.wire.axis.surface._handler import Handler
from emergent.wire.axis.surface.codecs.rrc import RequestResponseCodec
from emergent.wire.axis.surface.enrichers import chain_enrichers
from emergent.wire.compile._capabilities import fold_handler_runtime

type ScopeExtras = dict[type, Any]


async def execute_rrc(
    handler: Handler[RequestResponseCodec],
    request: Any,
    scope: Scope,
    target: str | None = None,
) -> Any:
    """Universal RRC execution pipeline.

    Pure async function:
    1. Extract ScopeEnricher capabilities
    2. Chain enrichers around core handler
    3. Execute: enrichers → request.to_domain() → Op → Result → response

    Same logic for all frameworks.
    """
    codec = handler.codec

    # Core handler: request → op → result → response
    async def core_handler(scope: Scope) -> Any:
        op = request.to_domain()
        # Extract scope values to pass to ops runner
        scope_extras: ScopeExtras = {}
        for key, value in scope.items():
            if key is not Scope:  # Skip Scope itself
                scope_extras[key] = value.value
        result = await handler.runner.run(op, scope_extras=scope_extras)
        return codec.response.from_domain(result)

    # Extract enrichers via fold
    rt_ctx = fold_handler_runtime(handler.capabilities)
    enrichers = rt_ctx.enrichers

    # Chain and execute
    if enrichers:
        wrapped = chain_enrichers(enrichers, core_handler, target=target)
        return await wrapped(scope)
    else:
        return await core_handler(scope)


__all__ = (
    "execute_rrc",
)

"""FastAPI adapter — functional compiler for FastAPI.

    from emergent.wire.compiler import Axes, fastapi_compile

    axes = Axes.default()
    app = fastapi_compile(wire_app, axes)
"""

from __future__ import annotations

from typing import Annotated, Any, Callable, cast

import fastapi
from kungfu import Some, Nothing
from nodnod import Scope
from nodnod.agent.base import Agent

from emergent.wire._handler import Handler
from emergent.wire._scan import scan, scan_stack, StackView
from emergent.wire.axis.surface._app import Application
from emergent.wire.axis.surface._stack import AppStack
from emergent.wire.axis.surface.codecs.rrc import RequestResponseCodec
from emergent.wire.axis.surface.codecs.stateful import StatefulCodec, get_transitions
from emergent.wire.axis.surface.codecs.resolve import get_method_params, resolve_transition
from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger

from emergent.wire.compiler._core import Axes
from emergent.wire.compiler._rrc import execute_rrc
from emergent.wire.compiler._stateful import (
    execute_stateful_turn,
    execute_stateful_done,
    load_state,
    save_state,
    delete_state,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Pydantic Detection
# ═══════════════════════════════════════════════════════════════════════════════


def _is_pydantic_model(typ: Any) -> bool:
    """Check if type is Pydantic BaseModel."""
    try:
        from pydantic import BaseModel
        return isinstance(typ, type) and issubclass(typ, BaseModel)
    except ImportError:
        return False


def _get_pydantic_types_from_transitions(transitions: list[Callable[..., Any]]) -> set[type]:
    """Find Pydantic models across all transitions."""
    result: set[type] = set()
    for method in transitions:
        params = get_method_params(method)
        for _, (_, compose_type) in params.items():
            if _is_pydantic_model(compose_type):
                result.add(compose_type)
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# Scope Setup
# ═══════════════════════════════════════════════════════════════════════════════


async def setup_fastapi_scope(
    scope: Scope,
    request: fastapi.Request,
    pydantic_types: set[type],
) -> None:
    """Configure scope for FastAPI context."""
    scope.inject(fastapi.Request, request)

    if pydantic_types:
        try:
            body = await request.json()
        except Exception:
            body = {}

        for pydantic_type in pydantic_types:
            try:
                instance = pydantic_type(**body)
                scope.inject(pydantic_type, instance)
            except Exception:
                pass


# ═══════════════════════════════════════════════════════════════════════════════
# RRC Wrapper
# ═══════════════════════════════════════════════════════════════════════════════


def wrap_rrc_fastapi(
    handler: Handler[RequestResponseCodec],
    trigger: HTTPRouteTrigger,
    axes: Axes,
) -> Any:
    """Wrap RRC handler for FastAPI."""
    req_cls = handler.codec.request
    resp_cls = handler.codec.response

    async def _route(req: Any) -> Any:
        return await execute_rrc(handler, req)

    # FastAPI GET needs Depends
    if trigger.method == "GET":
        _route.__annotations__ = {
            "req": Annotated[req_cls, fastapi.Depends()],
            "return": resp_cls,
        }
    else:
        _route.__annotations__ = {
            "req": req_cls,
            "return": resp_cls,
        }

    return _route


# ═══════════════════════════════════════════════════════════════════════════════
# Stateful Wrapper
# ═══════════════════════════════════════════════════════════════════════════════


def wrap_stateful_fastapi(
    handler: Handler[StatefulCodec],
    trigger: HTTPRouteTrigger,
    axes: Axes,
) -> Any:
    """Wrap StatefulCodec handler for FastAPI."""
    codec = handler.codec
    agent_cls = cast(type[Agent], codec.agent_cls)
    transitions = get_transitions(codec.flow)
    pydantic_types = _get_pydantic_types_from_transitions(transitions)

    async def _route(request: fastapi.Request) -> Any:
        # 1. Compose key_node → store key
        async with Scope() as scope:
            scope.inject(fastapi.Request, request)
            agent = agent_cls.build({codec.key_node})
            await agent.run(local_scope=scope, mapped_scopes={})

            key_result = scope.retrieve(codec.key_node)
            match key_result:
                case Some(value):
                    store_key = str(value.value)
                case Nothing():
                    return fastapi.Response(
                        content="Session key resolution failed", status_code=400
                    )

        # 2. Load state
        state = await load_state(codec, store_key)

        # 3. Setup scope, resolve transition
        async with Scope() as scope:
            await setup_fastapi_scope(scope, request, pydantic_types)
            resolved = await resolve_transition(transitions, scope, agent_cls)

        # 4. Execute transition
        match resolved:
            case Some((method, composed)):
                new_state, response, is_terminal = await execute_stateful_turn(
                    handler, state, method, composed
                )
            case Nothing():
                return fastapi.Response(content="No transition resolvable", status_code=400)

        # 5. Continue or Done
        if not is_terminal:
            await save_state(codec, store_key, state, new_state)
            if response is not None:
                return _serialize(response)
            return fastapi.Response(status_code=200)

        # 6. Done
        _, rejection, final = await execute_stateful_done(handler, new_state)

        await delete_state(codec, store_key)

        if rejection is not None:
            return _serialize(rejection)

        return _serialize(final)

    _route.__annotations__ = {
        "request": fastapi.Request,
        "return": codec.response,
    }

    return _route


def _serialize(resp: Any) -> Any:
    """Serialize response for FastAPI."""
    if isinstance(resp, fastapi.Response):
        return resp
    if _is_pydantic_model(type(resp)):
        return resp
    return resp


# ═══════════════════════════════════════════════════════════════════════════════
# Registration
# ═══════════════════════════════════════════════════════════════════════════════


def register_handler(
    app: fastapi.FastAPI | fastapi.APIRouter,
    trigger: HTTPRouteTrigger,
    handler: Handler[Any],
    axes: Axes,
) -> None:
    """Register handler on FastAPI app/router."""
    method_fn = getattr(app, trigger.method.lower(), None)
    if method_fn is None:
        raise ValueError(f"Unsupported HTTP method: {trigger.method}")

    if isinstance(handler.codec, RequestResponseCodec):
        route = wrap_rrc_fastapi(handler, trigger, axes)
    elif isinstance(handler.codec, StatefulCodec):
        route = wrap_stateful_fastapi(handler, trigger, axes)
    else:
        raise ValueError(f"Unknown codec type: {type(handler.codec)}")

    method_fn(trigger.path)(route)


# ═══════════════════════════════════════════════════════════════════════════════
# Compilation Functions
# ═══════════════════════════════════════════════════════════════════════════════


def fastapi_compile(app: Application, axes: Axes | None = None) -> fastapi.FastAPI:
    """Compile wire Application to FastAPI app.

    Args:
        app: Wire application
        axes: Axes context (default: Axes.default())

    Returns:
        FastAPI application
    """
    axes = axes or Axes.default()
    fapi = fastapi.FastAPI()

    for trigger, handler in scan(app, HTTPRouteTrigger, RequestResponseCodec):
        register_handler(fapi, trigger, handler, axes)

    for trigger, handler in scan(app, HTTPRouteTrigger, StatefulCodec):
        register_handler(fapi, trigger, handler, axes)

    return fapi


def fastapi_compile_stack(stack: AppStack, axes: Axes | None = None) -> fastapi.FastAPI:
    """Compile AppStack to FastAPI app with nested routers."""
    axes = axes or Axes.default()
    fapi = fastapi.FastAPI()
    view = scan_stack(stack, HTTPRouteTrigger)

    def build_router(v: StackView[HTTPRouteTrigger]) -> fastapi.APIRouter:
        router = fastapi.APIRouter()
        for trigger, handler in v.root:
            register_handler(router, trigger, handler, axes)

        for prefix, child in v.mounts.items():
            if isinstance(child, StackView):
                nested = build_router(child)
            else:
                nested = fastapi.APIRouter()
                for trigger, handler in child:
                    register_handler(nested, trigger, handler, axes)
            router.include_router(nested, prefix=f"/{prefix}")

        return router

    # Root handlers
    for trigger, handler in view.root:
        register_handler(fapi, trigger, handler, axes)

    # Mounts
    for prefix, child in view.mounts.items():
        if isinstance(child, StackView):
            router = build_router(child)
        else:
            router = fastapi.APIRouter()
            for trigger, handler in child:
                register_handler(router, trigger, handler, axes)
        fapi.include_router(router, prefix=f"/{prefix}")

    return fapi


__all__ = (
    "fastapi_compile",
    "fastapi_compile_stack",
    "wrap_rrc_fastapi",
    "wrap_stateful_fastapi",
    "register_handler",
    "setup_fastapi_scope",
)

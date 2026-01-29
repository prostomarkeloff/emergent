"""FastAPI compiler — compile wire Application to FastAPI app.

    from emergent.wire.contrib import fastapi as wire_fastapi

    app = wire_fastapi.from_application(wire_app)

Supports two codec types:

1. RequestResponseCodec:
   Request types are dataclasses/Pydantic models parsed from request.
   Response types implement from_domain() for Result conversion.

2. StatefulCodec:
   Single-class FSM with __transition__ method.
   State is persisted via StateStore, keyed by key_node's composed value.

   Compiler introspects __transition__ signature to find node-like deps.
   Node-likes include:
   - nodnod nodes (composed via Scope)
   - Pydantic BaseModel (parsed from request.json())
   - fastapi.Request (injected directly)
"""

from typing import Annotated, Any, cast, get_origin, get_args, Union

import fastapi
from kungfu import Some, Nothing
from nodnod import Scope
from nodnod.agent.base import Agent

from emergent.wire._app import Application
from emergent.wire._endpoint import Endpoint
from emergent.wire._handler import Handler
from emergent.wire._scan import scan, scan_endpoint
from emergent.wire.codecs.rrc import RequestResponseCodec, execute as rrc_execute
from emergent.wire.codecs.resolve import get_transition_params, compose_params
from emergent.wire.codecs.stateful import (
    StatefulCodec,
    parse_transition_result,
    run_middlewares,
)
from emergent.wire.triggers.http import HTTPRouteTrigger, Path


# ─── Node-like Detection ────────────────────────────────────────────────────


def _is_pydantic_model(typ: Any) -> bool:
    """Check if type is a Pydantic BaseModel subclass."""
    try:
        from pydantic import BaseModel

        return isinstance(typ, type) and issubclass(typ, BaseModel)
    except ImportError:
        return False


def _call_from_domain(response_type: type, result: Any) -> Any:
    """Call from_domain on response type, handling Union types.

    For Union[A, B, C], finds member with from_domain and calls it.
    """
    # Direct type with from_domain
    if hasattr(response_type, "from_domain"):
        return response_type.from_domain(result)

    # Union type — find member with from_domain
    origin = get_origin(response_type)
    if origin is Union:
        for member in get_args(response_type):
            if hasattr(member, "from_domain"):
                return member.from_domain(result)

    raise TypeError(f"Response type {response_type} has no from_domain method")


def _get_pydantic_types(params: dict[str, tuple[type, type]]) -> set[type]:
    """Find Pydantic models in transition params (for pre-injection)."""
    return {
        compose_type
        for _, compose_type in params.values()
        if _is_pydantic_model(compose_type)
    }


def _wrap_handler(
    trigger: HTTPRouteTrigger, handler: Handler[RequestResponseCodec]
) -> Any:
    """Wrap Handler in FastAPI-compatible route function."""
    req_cls: Any = handler.codec.request
    resp_cls = handler.codec.response

    async def _route_handler(req: Any) -> Any:
        return await rrc_execute(handler, req)

    # FastAPI GET routes need Depends to inject model from query params
    # POST/PUT/etc use body deserialization directly
    if trigger.method == "GET":
        _route_handler.__annotations__ = {
            "req": Annotated[req_cls, fastapi.Depends()],
            "return": resp_cls,
        }
    else:
        _route_handler.__annotations__ = {
            "req": req_cls,
            "return": resp_cls,
        }

    return _route_handler


# ─── StatefulCodec Handler ──────────────────────────────────────────────────


async def _setup_scope_fastapi(
    scope: Scope,
    request: fastapi.Request,
    pydantic_types: set[type],
) -> None:
    """Configure scope for FastAPI context.

    Injects:
    - fastapi.Request
    - Pydantic models parsed from request.json() (compiler magic)
    """
    scope.inject(fastapi.Request, request)

    # Pydantic magic: parse from body and pre-inject
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
                pass  # Will fail in compose_params → wrap as Nothing/Error


def _serialize_response(resp: Any) -> Any:
    """Serialize response for FastAPI.

    - Pydantic model → model itself (FastAPI handles serialization + OpenAPI)
    - fastapi.Response → as-is
    - Other → as-is (FastAPI will try to serialize)
    """
    # fastapi.Response subclasses returned directly
    if isinstance(resp, fastapi.Response):
        return resp

    # Pydantic models returned directly (FastAPI handles them)
    if _is_pydantic_model(type(resp)):
        return resp

    # Fallback
    return resp


def _wrap_stateful_handler(handler: Handler[StatefulCodec]) -> Any:
    """Wrap StatefulCodec Handler in FastAPI-compatible route function.

    Execution flow:
    1. Compose key_node to get store key (e.g., SessionId from cookie)
    2. Load state from store (or create initial)
    3. Setup scope, compose __transition__ params
    4. Call state.__transition__(**params)
    5. If continue: save state, return intermediate response
    6. If Done:
       a. Run middlewares → scope_extras
       b. state.to_domain() → Op
       c. runner.run(op, scope_extras) → Result
       d. response.from_domain(result) → final response
    7. Delete state, return final response
    """
    codec = handler.codec
    agent_cls = cast(type[Agent], codec.agent_cls)
    params = get_transition_params(codec.flow)
    pydantic_types = _get_pydantic_types(params)

    async def _route_handler(request: fastapi.Request) -> Any:
        # 1. Compose key_node to get store key
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

        # 2. Load state from store (or create initial)
        state = await codec.store.get(store_key)
        if state is None:
            state = codec.flow()

        # 3. Setup scope, compose __transition__ params
        async with Scope() as scope:
            await _setup_scope_fastapi(scope, request, pydantic_types)
            composed = await compose_params(params, scope, agent_cls)

        # 4. Call __transition__ and parse result
        raw_result = await state.__transition__(**composed)
        result = parse_transition_result(raw_result)

        # 5. If continue: save state only if it changed, return intermediate response
        if not result.is_terminal:
            new_state = result.state_or_done
            if new_state is not state:  # Prevent ghost states
                await codec.store.set(store_key, new_state)
            match result.response:
                case Some(resp):
                    return _serialize_response(resp)
                case Nothing():
                    return fastapi.Response(status_code=200)

        # 6. Done — run middlewares, execute Op, format response
        scope_extras, rejection = await run_middlewares(codec.middlewares, state)
        match rejection:
            case Some(resp):
                await codec.store.delete(store_key)
                return _serialize_response(resp)
            case Nothing():
                pass

        # 6b-c. to_domain() → Op → runner.run()
        op = state.to_domain()
        op_result = await handler.runner.run(op, scope_extras=scope_extras)

        # 6d. response.from_domain(result) — handles Union types
        final_response = _call_from_domain(codec.response, op_result)

        # 7. Delete state, return final response
        await codec.store.delete(store_key)
        return _serialize_response(final_response)

    # OpenAPI: use codec.response as return type
    _route_handler.__annotations__ = {
        "request": fastapi.Request,
        "return": codec.response,
    }
    return _route_handler


def compile_to_fastapi_route(
    endp: Endpoint,
) -> list[tuple[str, Path, Any]]:
    """Compile endpoint exposures into (method, path, handler) tuples."""
    return [
        (trigger.method.upper(), trigger.path, _wrap_handler(trigger, handler))
        for trigger, handler in scan_endpoint(
            endp, HTTPRouteTrigger, RequestResponseCodec
        )
    ]


def _register_handler(
    app: fastapi.FastAPI,
    trigger: HTTPRouteTrigger,
    handler: Handler[Any],
) -> None:
    """Register a single trigger-handler pair on FastAPI app."""
    route_method = getattr(app, trigger.method.lower(), None)
    if route_method is None:
        raise ValueError(f"Unsupported HTTP method: {trigger.method}")

    if isinstance(handler.codec, RequestResponseCodec):
        route_method(trigger.path)(_wrap_handler(trigger, handler))
    elif isinstance(handler.codec, StatefulCodec):
        route_method(trigger.path)(_wrap_stateful_handler(handler))


def add_endpoint_to_app(
    app: fastapi.FastAPI,
    endp: Endpoint,
) -> None:
    """Register endpoint's HTTP exposures as FastAPI routes."""
    # RRC handlers
    for trigger, handler in scan_endpoint(endp, HTTPRouteTrigger, RequestResponseCodec):
        _register_handler(app, trigger, handler)

    # StatefulCodec handlers
    for trigger, handler in scan_endpoint(endp, HTTPRouteTrigger, StatefulCodec):
        _register_handler(app, trigger, handler)


def from_application(app: Application) -> fastapi.FastAPI:
    """Compile wire Application to FastAPI app."""
    f_app = fastapi.FastAPI()

    # RRC handlers
    for trigger, handler in scan(app, HTTPRouteTrigger, RequestResponseCodec):
        _register_handler(f_app, trigger, handler)

    # StatefulCodec handlers
    for trigger, handler in scan(app, HTTPRouteTrigger, StatefulCodec):
        _register_handler(f_app, trigger, handler)

    return f_app

"""FastAPI adapter — functional compiler for FastAPI.

from emergent.wire.compile import Axes, fastapi_compile

axes = Axes.default()
app = fastapi_compile(wire_app, axes)
"""

from __future__ import annotations

from typing import Any, Callable, cast

import fastapi
from kungfu import Some, Nothing
from nodnod import Scope
from nodnod.agent.base import Agent

from emergent.wire.axis.surface._handler import Handler
from emergent.wire.axis.surface._scan import scan_endpoint, scan_stack, StackView
from emergent.wire.axis.surface._app import Application
from emergent.wire.axis.surface._endpoint import Endpoint
from emergent.wire.axis.surface._stack import AppStack
from emergent.wire.axis.surface.codecs.rrc import RequestResponseCodec
from emergent.wire.axis.surface.codecs.stateful import StatefulCodec, get_transitions
from emergent.wire.axis.surface.codecs.immediate import (
    ImmediateCodec,
    ImmediateFactoryCodec,
)
from emergent.wire.axis.surface.codecs.delegate import DelegateCodec
from emergent.wire.axis.surface.codecs.resolve import (
    get_method_params,
    resolve_transition,
)
from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger

from emergent.wire.compile._core import Axes, scan_all_codecs
from emergent.wire.compile._capabilities import (
    apply_response_capabilities,
    apply_fastapi_capabilities,
    apply_fastapi_route_capabilities,
    FastAPICompileContext,
    FastAPIRouteContext,
)
from emergent.wire.compile._execute import (
    execute_rrc_unified,
    execute_immediate_unified,
)
from emergent.wire.compile._stateful import (
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


def _get_pydantic_types_from_transitions(
    transitions: list[Callable[..., Any]],
) -> set[type]:
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
    """Wrap RRC handler for FastAPI — trivial with unified execution."""
    resp_cls = handler.codec.response

    async def _route(request: fastapi.Request) -> Any:
        # Parse request data based on method
        if trigger.method in ("POST", "PUT", "PATCH"):
            try:
                body = await request.json()
            except Exception:
                body = {}
        else:
            body = dict(request.query_params)

        # Merge path params + body/query (path params take precedence)
        all_values = {**body, **dict(request.path_params)}

        # Unified execution — just provide the pieces
        return await execute_rrc_unified(
            handler=handler,
            axes=axes,
            get_value=lambda name: all_values.get(name),
            inject_scope=lambda scope: scope.inject(fastapi.Request, request),
        )

    _route.__annotations__ = {
        "request": fastapi.Request,
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
                return fastapi.Response(
                    content="No transition resolvable", status_code=400
                )

        # 5. Continue or Done
        if not is_terminal:
            await save_state(codec, store_key, state, new_state)
            if response is not None:
                # Apply response capabilities
                response = apply_response_capabilities(response, handler.capabilities)
                return _serialize(response)
            return fastapi.Response(status_code=200)

        # 6. Done — execute with enrichers
        async with Scope() as done_scope:
            await setup_fastapi_scope(done_scope, request, pydantic_types)
            final = await execute_stateful_done(handler, new_state, done_scope)

        await delete_state(codec, store_key)

        # Apply response capabilities
        final = apply_response_capabilities(final, handler.capabilities)
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
# Immediate Handlers
# ═══════════════════════════════════════════════════════════════════════════════


def wrap_immediate_fastapi(
    handler: Handler[Any],
    trigger: HTTPRouteTrigger,
    axes: Axes,
) -> Any:
    """Wrap Immediate codecs for FastAPI — trivial with unified execution."""

    async def _route() -> Any:
        return execute_immediate_unified(handler)

    return _route


# Alias for backwards compatibility
wrap_immediate_factory_fastapi = wrap_immediate_fastapi


# ═══════════════════════════════════════════════════════════════════════════════
# Delegate Wrapper — compose dialect works by default
# ═══════════════════════════════════════════════════════════════════════════════


def wrap_delegate_fastapi(
    handler: Handler[DelegateCodec],
    trigger: HTTPRouteTrigger,
    axes: Axes,
    agent_cls: type[Agent] | None = None,
) -> Any:
    """Wrap DelegateCodec handler for FastAPI — trivial with unified execution.

    Compose dialect works by default on handler params.
    """
    from emergent.wire.compile._execute import execute_delegate_unified

    # Build route using unified execution
    async def _route(request: fastapi.Request) -> Any:
        def inject_scope(scope: Scope) -> None:
            scope.inject(fastapi.Request, request)
            # Inject path params into scope
            for _, value in request.path_params.items():
                scope.inject(type(value), value)

        return await execute_delegate_unified(
            handler=handler,
            inject_scope=inject_scope,
            agent_cls=agent_cls,
        )

    return _route


# ═══════════════════════════════════════════════════════════════════════════════
# Registration
# ═══════════════════════════════════════════════════════════════════════════════


def register_handler(
    app: fastapi.FastAPI | fastapi.APIRouter,
    trigger: HTTPRouteTrigger,
    handler: Handler[Any],
    axes: Axes,
    mounted: set[tuple[int, str]] | None = None,
) -> None:
    """Register handler on FastAPI app/router."""
    # 1. Build compile context
    ctx = FastAPICompileContext(
        app=app,
        trigger=trigger,
        handler=handler,
        mounted=mounted if mounted is not None else set(),
    )

    # 2. Apply compile-time capabilities (e.g., Mount)
    ctx = apply_fastapi_capabilities(ctx, handler.capabilities)

    # If capability handled registration (e.g., mounted ASGI), we're done
    if ctx.skip_route:
        return

    # 3. Build route context for route-level capabilities (Tag, Summary, etc.)
    route_ctx = FastAPIRouteContext(
        path=trigger.path,
        method=trigger.method,
    )
    route_ctx = apply_fastapi_route_capabilities(route_ctx, handler.capabilities)

    # 4. Wrap handler based on codec
    if isinstance(handler.codec, RequestResponseCodec):
        route = wrap_rrc_fastapi(handler, trigger, axes)
    elif isinstance(handler.codec, StatefulCodec):
        route = wrap_stateful_fastapi(handler, trigger, axes)
    elif isinstance(handler.codec, ImmediateCodec):
        route = wrap_immediate_fastapi(handler, trigger, axes)
    elif isinstance(handler.codec, ImmediateFactoryCodec):
        route = wrap_immediate_factory_fastapi(handler, trigger, axes)
    elif isinstance(handler.codec, DelegateCodec):
        route = wrap_delegate_fastapi(handler, trigger, axes)
    else:
        raise ValueError(f"Unknown codec type: {type(handler.codec)}")

    # 5. Register route with capabilities from route context
    method_fn = getattr(app, trigger.method.lower(), None)
    if method_fn is None:
        raise ValueError(f"Unsupported HTTP method: {trigger.method}")

    # Apply route context to FastAPI decorator
    method_fn(
        trigger.path,
        tags=list(route_ctx.tags) if route_ctx.tags else None,
        summary=route_ctx.summary,
        description=route_ctx.description,
        deprecated=route_ctx.deprecated or None,
        operation_id=route_ctx.operation_id,
    )(route)


# ═══════════════════════════════════════════════════════════════════════════════
# Compilation Functions
# ═══════════════════════════════════════════════════════════════════════════════


def fastapi_compile_endpoint(
    endp: Endpoint,
    axes: Axes | None = None,
) -> list[fastapi.routing.APIRoute]:
    """Compile single Endpoint to list of FastAPI APIRoute objects.

    Args:
        endp: Wire endpoint
        axes: Axes context (default: Axes.default())

    Returns:
        List of APIRoute objects for all HTTP exposures

    Example:
        from emergent.wire import endpoint
        from emergent.wire.compile import fastapi_compile_endpoint

        routes = fastapi_compile_endpoint(
            endpoint(my_runner)
                .expose(HTTPRouteTrigger("POST", "/users"), rrc(CreateUser, UserResponse))
                .expose(HTTPRouteTrigger("GET", "/users/{id}"), rrc(GetUser, UserResponse))
        )

        app = FastAPI()
        for route in routes:
            app.routes.append(route)
        # or
        router = APIRouter(routes=routes)
    """
    axes = axes or Axes.default()
    routes: list[fastapi.routing.APIRoute] = []

    for trigger, handler in scan_endpoint(endp, HTTPRouteTrigger, RequestResponseCodec):
        route_fn = wrap_rrc_fastapi(handler, trigger, axes)
        routes.append(
            fastapi.routing.APIRoute(
                path=trigger.path,
                endpoint=route_fn,
                methods=[trigger.method.upper()],
                response_model=handler.codec.response,
            )
        )

    for trigger, handler in scan_endpoint(endp, HTTPRouteTrigger, StatefulCodec):
        route_fn = wrap_stateful_fastapi(handler, trigger, axes)
        routes.append(
            fastapi.routing.APIRoute(
                path=trigger.path,
                endpoint=route_fn,
                methods=[trigger.method.upper()],
                response_model=handler.codec.response,
            )
        )

    return routes


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

    # Shared state for compile-time capabilities
    mounted: set[tuple[int, str]] = set()

    # Unified compile loop
    scan_all_codecs(
        app,
        HTTPRouteTrigger,
        lambda trigger, handler: register_handler(
            fapi, trigger, handler, axes, mounted
        ),
    )

    return fapi


def fastapi_compile_stack(stack: AppStack, axes: Axes | None = None) -> fastapi.FastAPI:
    """Compile AppStack to FastAPI app with nested routers."""
    axes = axes or Axes.default()
    fapi = fastapi.FastAPI()
    view = scan_stack(stack, HTTPRouteTrigger)

    # Shared state for compile-time capabilities
    mounted: set[tuple[int, str]] = set()

    def build_router(v: StackView[HTTPRouteTrigger]) -> fastapi.APIRouter:
        router = fastapi.APIRouter()
        for trigger, handler in v.root:
            register_handler(router, trigger, handler, axes, mounted)

        for prefix, child in v.mounts.items():
            if isinstance(child, StackView):
                nested = build_router(child)
            else:
                nested = fastapi.APIRouter()
                for trigger, handler in child:
                    register_handler(nested, trigger, handler, axes, mounted)
            router.include_router(nested, prefix=f"/{prefix}")

        return router

    # Root handlers
    for trigger, handler in view.root:
        register_handler(fapi, trigger, handler, axes, mounted)

    # Mounts
    for prefix, child in view.mounts.items():
        if isinstance(child, StackView):
            router = build_router(child)
        else:
            router = fastapi.APIRouter()
            for trigger, handler in child:
                register_handler(router, trigger, handler, axes, mounted)
        fapi.include_router(router, prefix=f"/{prefix}")

    return fapi


__all__ = (
    "fastapi_compile",
    "fastapi_compile_endpoint",
    "fastapi_compile_stack",
    "wrap_rrc_fastapi",
    "wrap_stateful_fastapi",
    "wrap_immediate_fastapi",
    "wrap_immediate_factory_fastapi",
    "register_handler",
    "setup_fastapi_scope",
)


# Alias for cleaner API
compile = fastapi_compile
compile_stack = fastapi_compile_stack
compile_endpoint = fastapi_compile_endpoint

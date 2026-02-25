"""FastAPI adapter — functional compiler for FastAPI.

from emergent.wire.compile import Axes, fastapi_compile

axes = Axes.default()
app = fastapi_compile(wire_app, axes)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import fastapi
from kungfu import Some, Nothing
from nodnod import Scope
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

from emergent.wire.compile._core import Axes, fold
from emergent.wire.compile._target import CodecAdapter, TargetCompiler
from emergent.wire.compile._capabilities import (
    apply_response_capabilities,
    FastAPICompileContext,
    FastAPICompilable,
    FastAPIRouteCompilable,
)
from emergent.wire.axis._capability import FastAPIRouteContext
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
from emergent.wire.compile._lifetime import ScopeLayer, Tier, App, Request

from emergent.graph._family import ScopeFamily
from emergent.wire.compile.targets.pure import (
    STARTUP_COMPILER,
    SHUTDOWN_COMPILER,
    EXCEPTION_COMPILER,
    WEBSOCKET_COMPILER,
    ExceptionRoute,
    WebSocketRoute,
    app_scope_lifespan,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Pydantic Detection
# ═══════════════════════════════════════════════════════════════════════════════


def is_pydantic_model(typ: Any) -> bool:
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
            if is_pydantic_model(compose_type):
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
# FastAPIRoute — structured wrap result (NO heuristics in registration)
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class FastAPIRoute:
    """Structured result of wrapping a handler for FastAPI.

    The wrap function knows its codec and fills ALL metadata.
    register_handler reads ONLY from this — zero hasattr/getattr on codec.
    """

    endpoint: Any
    response_model: type | None = None
    openapi_extra: dict[str, Any] | None = None


# ═══════════════════════════════════════════════════════════════════════════════
# RRC Wrapper
# ═══════════════════════════════════════════════════════════════════════════════


def wrap_rrc_fastapi(
    handler: Handler[RequestResponseCodec],
    trigger: HTTPRouteTrigger,
    axes: Axes,
) -> FastAPIRoute:
    """Wrap RRC handler for FastAPI — uses Pydantic for type coercion."""
    from emergent.wire.compile._generate import to_pydantic

    req_cls = handler.codec.request
    resp_cls = handler.codec.response

    # Compile request to Pydantic for type coercion
    RequestModel = to_pydantic(req_cls, axes)

    async def _route(request: fastapi.Request) -> Any:
        from fastapi.exceptions import RequestValidationError
        from pydantic import ValidationError

        # Parse request data based on method
        if trigger.method in ("POST", "PUT", "PATCH"):
            content_type = request.headers.get("content-type", "")
            if "application/x-www-form-urlencoded" in content_type or "multipart/form-data" in content_type:
                body = dict(await request.form())
            else:
                try:
                    body = await request.json()
                except Exception:
                    body = {}
        else:
            body = dict(request.query_params)

        # Merge path params + body/query (path params take precedence)
        all_values = {**body, **dict(request.path_params)}

        # Coerce types via Pydantic
        try:
            pydantic_instance = RequestModel(**all_values)
        except ValidationError as e:
            raise RequestValidationError(e.errors()) from e
        coerced = pydantic_instance.model_dump()

        # Unified execution — just provide the pieces
        return await execute_rrc_unified(
            handler=handler,
            axes=axes,
            get_value=lambda name: coerced.get(name),
            inject_scope=lambda scope: scope.inject(fastapi.Request, request),
        )

    _route.__annotations__ = {
        "request": fastapi.Request,
        "return": resp_cls,
    }

    return FastAPIRoute(
        endpoint=_route,
        response_model=resp_cls,
        openapi_extra=build_rrc_openapi_extra(handler.codec, trigger, axes),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Stateful Wrapper
# ═══════════════════════════════════════════════════════════════════════════════


def wrap_stateful_fastapi(
    handler: Handler[StatefulCodec],
    trigger: HTTPRouteTrigger,
    axes: Axes,
) -> FastAPIRoute:
    """Wrap StatefulCodec handler for FastAPI."""
    from emergent.graph._compose import Composer

    codec = handler.codec
    transitions = get_transitions(codec.flow)
    pydantic_types = _get_pydantic_types_from_transitions(transitions)

    async def _route(request: fastapi.Request) -> Any:
        layer = axes.scope_layer

        # 1. Compose key_node → store key
        key_scope = layer.parent.create_child("stateful-key") if layer else Scope()
        async with key_scope:
            key_scope.inject(fastapi.Request, request)
            composer = Composer.create(key_scope, codec.agent_cls)

            success, key_value = await composer.compose(codec.key_node)
            if not success:
                raise RuntimeError(f"Session key resolution failed: {key_value}")
            store_key = str(key_value)

        # 2. Load state
        state = await load_state(codec, store_key)

        # 3. Setup scope, resolve transition
        transition_scope = layer.parent.create_child("stateful-transition") if layer else Scope()
        async with transition_scope:
            await setup_fastapi_scope(transition_scope, request, pydantic_types)
            resolved = await resolve_transition(transitions, transition_scope, codec.agent_cls)

        # 4. Execute transition
        match resolved:
            case Some((method, composed)):
                new_state, response, is_terminal = await execute_stateful_turn(
                    handler, state, method, composed
                )
            case Nothing():
                raise RuntimeError("No transition resolvable")

        # 5. Continue or Done
        if not is_terminal:
            await save_state(codec, store_key, state, new_state)
            if response is not None:
                return apply_response_capabilities(response, handler.capabilities)
            return None

        # 6. Done — execute with enrichers
        done_scope = layer.parent.create_child("stateful-done") if layer else Scope()
        async with done_scope:
            await setup_fastapi_scope(done_scope, request, pydantic_types)
            final = await execute_stateful_done(handler, new_state, done_scope)

        await delete_state(codec, store_key)

        final = apply_response_capabilities(final, handler.capabilities)
        return final

    _route.__annotations__ = {
        "request": fastapi.Request,
        "return": codec.response,
    }

    return FastAPIRoute(
        endpoint=_route,
        response_model=codec.response,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Immediate Handlers
# ═══════════════════════════════════════════════════════════════════════════════


def wrap_immediate_fastapi(
    handler: Handler[Any],
    trigger: HTTPRouteTrigger,
    axes: Axes,
) -> FastAPIRoute:
    """Wrap Immediate codecs for FastAPI — trivial with unified execution."""

    async def _route() -> Any:
        return execute_immediate_unified(handler)

    return FastAPIRoute(endpoint=_route)


# Alias for backwards compatibility
wrap_immediate_factory_fastapi = wrap_immediate_fastapi


# ═══════════════════════════════════════════════════════════════════════════════
# Delegate Wrapper — compose dialect works by default
# ═══════════════════════════════════════════════════════════════════════════════


def wrap_delegate_fastapi(
    handler: Handler[DelegateCodec],
    trigger: HTTPRouteTrigger,
    axes: Axes,
) -> FastAPIRoute:
    """Wrap DelegateCodec handler for FastAPI — trivial with unified execution.

    Compose dialect works by default on handler params.
    """
    from emergent.wire.compile._execute import execute_delegate_unified

    async def _route(request: fastapi.Request) -> Any:
        def inject_scope(scope: Scope) -> None:
            scope.inject(fastapi.Request, request)
            for _, value in request.path_params.items():
                scope.inject(type(value), value)

        return await execute_delegate_unified(
            handler=handler,
            inject_scope=inject_scope,
            axes=axes,
        )

    return FastAPIRoute(endpoint=_route)


# ═══════════════════════════════════════════════════════════════════════════════
# OpenAPI Schema Generation — uses schema axis
# ═══════════════════════════════════════════════════════════════════════════════


def build_rrc_openapi_extra(
    codec: RequestResponseCodec,
    trigger: HTTPRouteTrigger,
    axes: Axes,
) -> dict[str, Any] | None:
    """Build openapi_extra for RRC codec using schema axis.

    Uses to_openapi_schema() to generate proper request schema.
    FastAPI will merge this into the route's OpenAPI specification.
    """
    import re
    from emergent.wire.compile._schema import to_openapi_schema

    req_cls = codec.request

    # Generate request schema using schema axis
    request_schema = to_openapi_schema(req_cls, axes)

    # Extract path params from trigger
    path_param_names = set(re.findall(r"\{(\w+)\}", trigger.path))

    # Build path parameters list
    path_parameters: list[dict[str, Any]] = []
    if path_param_names and "properties" in request_schema:
        for name in path_param_names:
            if name in request_schema["properties"]:
                prop = request_schema["properties"][name]
                path_parameters.append({
                    "name": name,
                    "in": "path",
                    "required": True,
                    "schema": prop,
                })

    result: dict[str, Any] = {}

    # Add path parameters
    if path_parameters:
        result["parameters"] = path_parameters

    # Add request body for POST/PUT/PATCH
    if trigger.method in ("POST", "PUT", "PATCH"):
        # Remove path params from body schema
        body_schema = dict(request_schema)
        if "properties" in body_schema and path_param_names:
            body_schema = dict(body_schema)
            body_schema["properties"] = {
                k: v for k, v in body_schema["properties"].items()
                if k not in path_param_names
            }
            if "required" in body_schema:
                body_schema["required"] = [
                    r for r in body_schema["required"]
                    if r not in path_param_names
                ]

        # Only add requestBody if there are body properties
        if body_schema.get("properties"):
            result["requestBody"] = {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": body_schema,
                    }
                },
            }
    else:
        # GET/DELETE — add query parameters
        query_parameters: list[dict[str, Any]] = []
        if "properties" in request_schema:
            required_fields = set(request_schema.get("required", []))
            for name, prop in request_schema["properties"].items():
                if name not in path_param_names:
                    query_parameters.append({
                        "name": name,
                        "in": "query",
                        "required": name in required_fields,
                        "schema": prop,
                    })

        if query_parameters:
            if "parameters" in result:
                result["parameters"].extend(query_parameters)
            else:
                result["parameters"] = query_parameters

    return result if result else None


# ═══════════════════════════════════════════════════════════════════════════════
# Registration
# ═══════════════════════════════════════════════════════════════════════════════


def register_handler(
    app: fastapi.FastAPI | fastapi.APIRouter,
    trigger: HTTPRouteTrigger,
    handler: Handler[Any],
    route: FastAPIRoute,
    axes: Axes,
    mounted: set[tuple[int, str]] | None = None,
) -> None:
    """Register pre-wrapped handler on FastAPI app/router.

    Reads ALL metadata from FastAPIRoute — zero codec sniffing.
    Capabilities applied from handler.capabilities (axis data).
    """
    # 1. Apply compile-time capabilities (e.g., Mount) — fold() with tracing
    ctx = FastAPICompileContext(
        app=app,
        trigger=trigger,
        handler=handler,
        mounted=mounted if mounted is not None else set(),
    )
    ctx = fold(
        handler.capabilities, ctx,
        FastAPICompilable, "compile_fastapi",
        trace=axes.trace,
    )

    if ctx.skip_route:
        return

    # 2. Route-level capabilities (Tag, Summary, etc.) — fold() with tracing
    route_ctx = FastAPIRouteContext(
        path=trigger.path,
        method=trigger.method,
    )
    route_ctx = fold(
        handler.capabilities, route_ctx,
        FastAPIRouteCompilable, "compile_fastapi_route",
        trace=axes.trace,
    )

    # 3. Register — all metadata from FastAPIRoute + route_ctx
    method_fn = getattr(app, trigger.method.lower(), None)
    if method_fn is None:
        raise ValueError(f"Unsupported HTTP method: {trigger.method}")

    # Merge openapi_extra: route comes from wrap, capabilities come from route_ctx
    openapi_extra = route.openapi_extra
    if route_ctx.openapi_extra:
        if openapi_extra is None:
            openapi_extra = dict(route_ctx.openapi_extra)
        else:
            openapi_extra = dict(openapi_extra)
            for key, value in route_ctx.openapi_extra.items():
                if key == "responses" and "responses" in openapi_extra:
                    openapi_extra["responses"] = {
                        **openapi_extra["responses"],
                        **value,
                    }
                else:
                    openapi_extra[key] = value

    kwargs: dict[str, Any] = {
        "tags": list(route_ctx.tags) if route_ctx.tags else None,
        "summary": route_ctx.summary,
        "description": route_ctx.description,
        "deprecated": route_ctx.deprecated or None,
        "operation_id": route_ctx.operation_id,
        "response_model": route.response_model,
        "openapi_extra": openapi_extra,
    }
    if route_ctx.status_code is not None:
        kwargs["status_code"] = route_ctx.status_code

    method_fn(trigger.path, **kwargs)(route.endpoint)


# ═══════════════════════════════════════════════════════════════════════════════
# FASTAPI_COMPILER — open-world codec adapter set
# ═══════════════════════════════════════════════════════════════════════════════


FASTAPI_COMPILER: TargetCompiler[HTTPRouteTrigger] = TargetCompiler(
    trigger_type=HTTPRouteTrigger,
    adapters=(
        CodecAdapter(RequestResponseCodec, wrap_rrc_fastapi),
        CodecAdapter(StatefulCodec, wrap_stateful_fastapi),
        CodecAdapter(ImmediateCodec, wrap_immediate_fastapi),
        CodecAdapter(ImmediateFactoryCodec, wrap_immediate_factory_fastapi),
        CodecAdapter(DelegateCodec, wrap_delegate_fastapi),
    ),
)


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
        fapi_route = wrap_rrc_fastapi(handler, trigger, axes)
        routes.append(
            fastapi.routing.APIRoute(
                path=trigger.path,
                endpoint=fapi_route.endpoint,
                methods=[trigger.method.upper()],
                response_model=fapi_route.response_model,
            )
        )

    for trigger, handler in scan_endpoint(endp, HTTPRouteTrigger, StatefulCodec):
        fapi_route = wrap_stateful_fastapi(handler, trigger, axes)
        routes.append(
            fastapi.routing.APIRoute(
                path=trigger.path,
                endpoint=fapi_route.endpoint,
                methods=[trigger.method.upper()],
                response_model=fapi_route.response_model,
            )
        )

    return routes


def fastapi_compile(
    app: Application,
    axes: Axes | None = None,
    compiler: TargetCompiler[HTTPRouteTrigger] | None = None,
    family: ScopeFamily[Tier] | None = None,
) -> fastapi.FastAPI:
    """Compile wire Application to FastAPI app.

    Handles:
    - HTTP routes (HTTPRouteTrigger) via TargetCompiler
    - Lifecycle (StartupTrigger, ShutdownTrigger) via lifespan
    - Exception handlers (ExceptionTrigger)
    - WebSockets (WebSocketTrigger)
    - Global capabilities (Application.capabilities)

    Args:
        app: Wire application
        axes: Axes context (default: Axes.default())
        compiler: TargetCompiler (default: FASTAPI_COMPILER). Pass custom
                  compiler to add/swap/remove codec adapters.
        family: Optional ScopeFamily for tiered scope management. When provided,
                an App scope is composed once at startup and Request scopes
                inherit from it. mapped_scopes routes node results to tiers.

    Returns:
        FastAPI application
    """
    from contextlib import asynccontextmanager
    from collections.abc import AsyncIterator

    from emergent.wire.axis._capability import (
        FastAPIAppContext,
        FastAPIAppCompilable,
    )

    base_axes = axes or Axes.default()
    _compiler = compiler or FASTAPI_COMPILER

    # Build scope hierarchy from family
    app_scope: Scope | None = None
    request_axes = base_axes

    if family is not None:
        from types import MappingProxyType

        app_scope = Scope(detail="app")
        layer = ScopeLayer(
            scopes=MappingProxyType({App: app_scope}),
            family=family,
            leaf=Request,
        )
        request_axes = base_axes.with_scope_layer(layer)

    # 1. Collect lifecycle handlers sorted by order — via pure compilers
    startup_with_order = sorted(
        [(route.order, route.handler) for _, _, route in STARTUP_COMPILER.scan_and_wrap(app, base_axes)],
        key=lambda x: x[0],
    )
    shutdown_with_order = sorted(
        [(route.order, route.handler) for _, _, route in SHUTDOWN_COMPILER.scan_and_wrap(app, base_axes)],
        key=lambda x: x[0],
    )

    @asynccontextmanager
    async def lifespan(fastapi_app: fastapi.FastAPI) -> AsyncIterator[None]:
        del fastapi_app  # unused but required by FastAPI
        app_types = list(family.types_for(App)) if family else []
        if app_scope is not None:
            async with app_scope_lifespan(app_scope, app_types):
                for _order, handler_fn in startup_with_order:
                    await handler_fn()
                yield
                for _order, handler_fn in shutdown_with_order:
                    await handler_fn()
        else:
            for _order, handler_fn in startup_with_order:
                await handler_fn()
            yield
            for _order, handler_fn in shutdown_with_order:
                await handler_fn()

    fapi = fastapi.FastAPI(lifespan=lifespan)

    # 2. Process application-level capabilities → middleware (fold with tracing)
    app_ctx = fold(
        app.capabilities, FastAPIAppContext(),
        FastAPIAppCompilable, "compile_fastapi_app",
        trace=base_axes.trace,
    )

    for middleware_cls, kwargs in app_ctx.middleware:
        fapi.add_middleware(middleware_cls, **kwargs)

    for router in app_ctx.routers:
        fapi.include_router(router)

    # 3. Exception handlers — via pure compiler + FastAPI scope injection
    for exc_trigger, _, exc_route in EXCEPTION_COMPILER.scan_and_wrap(app, base_axes):
        async def _exc_handler(
            request: fastapi.Request,
            exc: Exception,
            _route: ExceptionRoute = exc_route,
            _app_scope: Scope | None = app_scope,
        ) -> Any:
            exc_scope = _app_scope.create_child("exception") if _app_scope else Scope()
            async with exc_scope:
                exc_scope.inject(fastapi.Request, request)
                exc_scope.inject(type(exc), exc)
                return await _route.handler(exc_scope)
        fapi.add_exception_handler(exc_route.exception_type, _exc_handler)

    # 4. WebSocket routes — via pure compiler + FastAPI scope injection
    for ws_trigger, _, ws_route in WEBSOCKET_COMPILER.scan_and_wrap(app, base_axes):
        async def _ws_handler(
            websocket: fastapi.WebSocket,
            _route: WebSocketRoute = ws_route,
            _app_scope: Scope | None = app_scope,
        ) -> None:
            ws_scope = _app_scope.create_child("websocket") if _app_scope else Scope()
            async with ws_scope:
                ws_scope.inject(fastapi.WebSocket, websocket)
                await _route.handler(ws_scope)
        fapi.add_api_websocket_route(ws_trigger.path, _ws_handler, name=ws_trigger.name)

    # 5. HTTP routes — via TargetCompiler, no isinstance chains
    mounted: set[tuple[int, str]] = set()
    for trigger, handler, route in _compiler.scan_and_wrap(app, request_axes):
        register_handler(fapi, trigger, handler, route, request_axes, mounted)

    return fapi


def _wrap_for_stack(
    handler: Handler[Any],
    trigger: HTTPRouteTrigger,
    axes: Axes,
    compiler: TargetCompiler[HTTPRouteTrigger],
) -> FastAPIRoute:
    """Find the right adapter and wrap handler for stack compilation."""
    for adapter in compiler.adapters:
        if isinstance(handler.codec, adapter.codec_type):
            return adapter.wrap(handler, trigger, axes)
    raise ValueError(f"No adapter for codec type: {type(handler.codec)}")


def fastapi_compile_stack(
    stack: AppStack,
    axes: Axes | None = None,
    compiler: TargetCompiler[HTTPRouteTrigger] | None = None,
) -> fastapi.FastAPI:
    """Compile AppStack to FastAPI app with nested routers."""
    axes = axes or Axes.default()
    _compiler = compiler or FASTAPI_COMPILER
    fapi = fastapi.FastAPI()
    view = scan_stack(stack, HTTPRouteTrigger)

    mounted: set[tuple[int, str]] = set()

    def _register(
        target: fastapi.FastAPI | fastapi.APIRouter,
        trigger: HTTPRouteTrigger,
        handler: Handler[Any],
    ) -> None:
        route = _wrap_for_stack(handler, trigger, axes, _compiler)
        register_handler(target, trigger, handler, route, axes, mounted)

    def build_router(v: StackView[HTTPRouteTrigger]) -> fastapi.APIRouter:
        router = fastapi.APIRouter()
        for trigger, handler in v.root:
            _register(router, trigger, handler)

        for prefix, child in v.mounts.items():
            if isinstance(child, StackView):
                nested = build_router(child)
            else:
                nested = fastapi.APIRouter()
                for trigger, handler in child:
                    _register(nested, trigger, handler)
            router.include_router(nested, prefix=f"/{prefix}")

        return router

    for trigger, handler in view.root:
        _register(fapi, trigger, handler)

    for prefix, child in view.mounts.items():
        if isinstance(child, StackView):
            router = build_router(child)
        else:
            router = fastapi.APIRouter()
            for trigger, handler in child:
                _register(router, trigger, handler)
        fapi.include_router(router, prefix=f"/{prefix}")

    return fapi


__all__ = (
    "fastapi_compile",
    "fastapi_compile_endpoint",
    "fastapi_compile_stack",
    "FastAPIRoute",
    "wrap_rrc_fastapi",
    "wrap_stateful_fastapi",
    "wrap_immediate_fastapi",
    "wrap_immediate_factory_fastapi",
    "register_handler",
    "setup_fastapi_scope",
    "is_pydantic_model",
    "build_rrc_openapi_extra",
    "FASTAPI_COMPILER",
)


# Alias for cleaner API
compile = fastapi_compile
compile_stack = fastapi_compile_stack
compile_endpoint = fastapi_compile_endpoint

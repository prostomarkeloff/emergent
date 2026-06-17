"""FastAPI adapter — functional compiler for FastAPI.

Target compilation via WrapPhase — same pattern as schema compilation:
    from_codec(codec, trigger) → WrapCtx → fold(capabilities) → WrapCtx → assemble → Route

    from emergent.wire.compile import Axes
    from emergent.wire.compile.targets.fastapi import fastapi_compile

    axes = Axes.default()
    app = fastapi_compile(wire_app, axes)
"""

from __future__ import annotations

import types
from dataclasses import dataclass
from typing import Any, Callable, Protocol, cast

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
from emergent.wire.compile._target import (
    CodecBinding,
    TargetCompiler,
    wrap_for_stack as _wrap_for_stack,
)
from emergent.wire.compile._pipeline import (
    compile_pipeline,
    execute_with_pipeline,
)
from emergent.wire.compile._capabilities import (
    apply_response_capabilities,
    FastAPICompileContext,
    FastAPICompilable,
    FastAPIRouteCompilable,
)
from emergent.wire.axis._capability import FastAPIRouteContext, CoercionSpec
from emergent.wire.compile._execute import (
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


type JsonDict = dict[str, Any]
type JsonDictList = list[JsonDict]


# ═══════════════════════════════════════════════════════════════════════════════
# FastAPI Extractors
# ═══════════════════════════════════════════════════════════════════════════════


class FastAPIExtractor(Protocol):
    """Extract raw dict from FastAPI request."""

    async def extract(self, request: fastapi.Request) -> JsonDict: ...


@dataclass(frozen=True, slots=True)
class FastAPIJsonExtractor:
    """Extract from JSON body + path params."""

    include_path_params: bool = True

    async def extract(self, request: fastapi.Request) -> JsonDict:
        content_type = request.headers.get("content-type", "")
        if (
            "application/x-www-form-urlencoded" in content_type
            or "multipart/form-data" in content_type
        ):
            body: JsonDict = dict(await request.form())
        else:
            try:
                raw_json: Any = await request.json()
            except ValueError:
                raw_json = {}
            # request.json() returns Any; isinstance narrows to dict[Unknown, Unknown]
            body: JsonDict = cast(JsonDict, raw_json) if isinstance(raw_json, dict) else {}
        if self.include_path_params:
            return {**body, **dict(request.path_params)}
        return body


@dataclass(frozen=True, slots=True)
class FastAPIQueryExtractor:
    """Extract from query params + path params."""

    async def extract(self, request: fastapi.Request) -> JsonDict:
        return {**dict(request.query_params), **dict(request.path_params)}


@dataclass(frozen=True, slots=True)
class FastAPIFormExtractor:
    """Extract from form data + path params."""

    async def extract(self, request: fastapi.Request) -> JsonDict:
        return {**dict(await request.form()), **dict(request.path_params)}


# Pre-built extraction constants — initialized lazily to avoid circular imports.
# Use init_fastapi_extraction_constants() to lazily populate these.
_extract_form: object | None = None
_extract_json: object | None = None
_extract_query: object | None = None


def init_fastapi_extraction_constants() -> None:
    """Initialize extraction constants (for use in capabilities)."""
    global _extract_form, _extract_json, _extract_query
    from emergent.wire.axis.surface.capabilities._pipeline import Extraction

    _extract_form = Extraction(fastapi=FastAPIFormExtractor())
    _extract_json = Extraction(fastapi=FastAPIJsonExtractor())
    _extract_query = Extraction(fastapi=FastAPIQueryExtractor())


def __getattr__(name: str) -> object:
    """Lazy access to extraction constants (initialized on first use)."""
    _aliases = {"EXTRACT_FORM": "_extract_form", "EXTRACT_JSON": "_extract_json", "EXTRACT_QUERY": "_extract_query"}
    if name in _aliases:
        init_fastapi_extraction_constants()
        return globals()[_aliases[name]]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# ═══════════════════════════════════════════════════════════════════════════════
# FastAPIWrapContext — seeded by from_codec, refined by capabilities
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class FastAPIWrapContext:
    """Wrap context for FastAPI — seeded by from_codec, refined by capabilities.

    Same pattern as schema compilation contexts (PydanticContext, etc.):
    - from_codec reads codec data into initial context
    - fold(capabilities) customizes via compile_fastapi_pipeline
    - assembler reads final context to build route

    Fields populated by from_codec:
        request_type, response_type — from codec
        execute — codec-specific execution function
        trigger — original HTTP trigger (for OpenAPI, path params, etc.)
        extractor — framework extraction strategy (GET→query, POST→body)
        coercion — validation spec (Pydantic, msgspec, etc.)
        error_type — exception type for validation errors
        inject_type — type to inject raw_request as into scope
    """

    # From codec (via from_codec):
    request_type: type | None = None
    # GenericAlias covers ``list[item]`` for collection (bare-array) responses.
    response_type: type | types.UnionType | types.GenericAlias | None = None
    execute: Callable[..., Any] | None = None

    # From trigger/framework defaults (via from_codec):
    trigger: HTTPRouteTrigger | None = None
    extractor: FastAPIExtractor | None = None
    coercion: CoercionSpec | None = None
    error_type: type | None = None
    inject_type: type = fastapi.Request


from typing import runtime_checkable


@runtime_checkable
class FastAPIPipelineCompilable(Protocol):
    """Capability that configures FastAPI request pipeline."""

    def compile_fastapi_pipeline(
        self, ctx: FastAPIWrapContext,
    ) -> FastAPIWrapContext: ...


# ═══════════════════════════════════════════════════════════════════════════════
# Pydantic Detection (for stateful)
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
# Scope Setup (for stateful)
# ═══════════════════════════════════════════════════════════════════════════════


async def setup_fastapi_scope(
    scope: Scope,
    request: fastapi.Request,
    pydantic_types: set[type],
) -> None:
    """Configure scope for FastAPI context."""
    scope.inject(fastapi.Request, request)

    if pydantic_types:
        from pydantic import ValidationError

        try:
            body = await request.json()
        except ValueError:
            body = {}

        for pydantic_type in pydantic_types:
            try:
                instance = pydantic_type(**body)
                scope.inject(pydantic_type, instance)
            except (ValidationError, TypeError):
                pass


# ═══════════════════════════════════════════════════════════════════════════════
# FastAPIRoute — structured wrap result (NO heuristics in registration)
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class FastAPIRoute:
    """Structured result of wrapping a handler for FastAPI.

    The assembler fills ALL metadata.
    register_handler reads ONLY from this — zero hasattr/getattr on codec.
    """

    endpoint: Any
    # Mirrors FastAPIWrapContext.response_type: a collection response is `list[item]`
    # (a GenericAlias), so this must admit GenericAlias alongside plain types/unions.
    response_model: type | types.UnionType | types.GenericAlias | None = None
    openapi_extra: JsonDict | None = None


# ═══════════════════════════════════════════════════════════════════════════════
# Execute functions — codec-specific (called by execute_with_pipeline)
# ═══════════════════════════════════════════════════════════════════════════════


async def _rrc_execute(
    handler: Handler[RequestResponseCodec],
    scope: Scope,
    get_value: Callable[[str], Any] | None,
) -> Any:
    """RRC execution: build request → run op → map response."""
    from emergent.graph._compose import Composer
    from emergent.wire.compile._rrc import execute_rrc
    from emergent.wire.compile._request import build_request

    req_cls = handler.codec.request
    composer = Composer.create(scope)
    request = await build_request(
        request_cls=req_cls,
        get_value=get_value or (lambda _name: None),
        agent_cls=composer.agent_cls,
        scope=scope,
    )
    scope.inject(req_cls, request)
    response = await execute_rrc(handler, request, scope)
    response = apply_response_capabilities(response, handler.capabilities)
    return response


async def _stateful_execute(
    handler: Handler[StatefulCodec],
    scope: Scope,
    get_value: Callable[[str], Any] | None,
) -> Any:
    """Stateful execution: compose key → load state → transition → done."""
    from emergent.graph._compose import Composer

    codec = handler.codec
    transitions = get_transitions(codec.flow)
    pydantic_types = _get_pydantic_types_from_transitions(transitions)

    # Get the raw request from scope
    req_wrapper = scope.get(fastapi.Request)
    if req_wrapper is None:
        raise RuntimeError("fastapi.Request not found in scope")
    request = req_wrapper.value

    # 1. Compose key_node → store key
    key_scope = scope.create_child("stateful-key")
    async with key_scope:
        key_scope.inject(fastapi.Request, request)
        composer = Composer.create(key_scope, codec.agent_cls)
        # codec.key_node is a bare `type` (no type parameter), so compose()'s generic
        # T resolves to Unknown; pinning the concrete tuple shape (Any payload) stops
        # the Unknown leaking. We only need str conversion of the result.
        compose_result: tuple[bool, Any] = await composer.compose(
            codec.key_node,
        )
        success = compose_result[0]
        key_result = compose_result[1]
        if not success:
            raise RuntimeError(f"Session key resolution failed: {key_result}")
        store_key = str(key_result)

    # 2. Load state
    state = await load_state(codec, store_key)

    # 3. Setup scope, resolve transition
    transition_scope = scope.create_child("stateful-transition")
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
    done_scope = scope.create_child("stateful-done")
    async with done_scope:
        await setup_fastapi_scope(done_scope, request, pydantic_types)
        final = await execute_stateful_done(handler, new_state, done_scope)

    await delete_state(codec, store_key)
    final = apply_response_capabilities(final, handler.capabilities)
    return final


async def _immediate_execute(
    handler: Handler[Any],
    scope: Scope,
    get_value: Callable[[str], Any] | None,
) -> Any:
    """Immediate execution: produce response directly."""
    return execute_immediate_unified(handler)


async def _delegate_execute(
    handler: Handler[DelegateCodec],
    scope: Scope,
    get_value: Callable[[str], Any] | None,
) -> Any:
    """Delegate execution: compose params → call handler."""
    from emergent.wire.compile._execute import execute_delegate_unified

    # Get the raw request from scope
    req_wrapper = scope.get(fastapi.Request)
    request = req_wrapper.value if req_wrapper is not None else None

    def inject_scope(s: Scope) -> None:
        if request is not None:
            s.inject(fastapi.Request, request)
            for _, value in request.path_params.items():
                s.inject(type(value), value)

    return await execute_delegate_unified(
        handler=handler,
        inject_scope=inject_scope,
        target="fastapi",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# from_codec functions — read codec data into context
# ═══════════════════════════════════════════════════════════════════════════════


def _default_extractor(trigger: HTTPRouteTrigger) -> FastAPIExtractor:
    """Default extractor based on HTTP method."""
    if trigger.method in ("POST", "PUT", "PATCH"):
        return FastAPIJsonExtractor()
    return FastAPIQueryExtractor()


def _default_coercion() -> CoercionSpec:
    """Default Pydantic coercion — inline construction to avoid private import."""
    from emergent.wire.compile._phase import SchemaCompiler, PYDANTIC_PHASE, EntityCompilation
    from emergent.wire.compile._generate import assemble_pydantic

    def _pydantic_validate(model: type, raw: JsonDict) -> JsonDict:
        instance = model(**raw)
        return instance.model_dump()

    def _assemble(cls: type, ec: Any) -> type:
        assert isinstance(ec, EntityCompilation)
        return assemble_pydantic(cls, ec)

    return CoercionSpec(
        compiler=SchemaCompiler(phases=(PYDANTIC_PHASE,)),
        assemble=_assemble,
        validate=_pydantic_validate,
    )


def _validation_error_type() -> type:
    """FastAPI's RequestValidationError."""
    from fastapi.exceptions import RequestValidationError
    return RequestValidationError


def _response_model(
    codec_response: type | None,
) -> type | types.UnionType | types.GenericAlias | None:
    """Response model for the route.

    A collection response (top-level JSON array) maps to ``list[item]`` so the
    body is a bare array; any other response is its own type.
    """
    from emergent.wire.derive._codegen import CollectionResponseMarker

    # Hold the unnarrowed value: returning the `issubclass`-narrowed `codec_response`
    # on the fall-through would leave a `type[Unknown]` residual in the inferred
    # return (a TypeGuard-narrowing artifact); the plain copy keeps it `type | None`.
    plain: type | None = codec_response
    if (
        isinstance(codec_response, type)
        and issubclass(codec_response, CollectionResponseMarker)
    ):
        return list[codec_response.collection_item()]
    return plain


def rrc_from_codec(
    codec: RequestResponseCodec,
    trigger: HTTPRouteTrigger,
) -> FastAPIWrapContext:
    """Seed WrapContext from RRC codec — request/response types + extraction."""
    return FastAPIWrapContext(
        request_type=codec.request,
        response_type=_response_model(codec.response),
        execute=_rrc_execute,
        trigger=trigger,
        extractor=_default_extractor(trigger),
        coercion=_default_coercion(),
        error_type=_validation_error_type(),
    )


def stateful_from_codec(
    codec: StatefulCodec,
    trigger: HTTPRouteTrigger,
) -> FastAPIWrapContext:
    """Seed WrapContext from StatefulCodec — no extraction/coercion needed."""
    return FastAPIWrapContext(
        response_type=codec.response,
        execute=_stateful_execute,
        trigger=trigger,
    )


def immediate_from_codec(
    codec: ImmediateCodec | ImmediateFactoryCodec,
    trigger: HTTPRouteTrigger,
) -> FastAPIWrapContext:
    """Seed WrapContext from ImmediateCodec — trivial, no extraction."""
    return FastAPIWrapContext(
        execute=_immediate_execute,
        trigger=trigger,
        inject_type=type(None),
    )


def delegate_from_codec(
    codec: DelegateCodec,
    trigger: HTTPRouteTrigger,
) -> FastAPIWrapContext:
    """Seed WrapContext from DelegateCodec — compose resolves params."""
    return FastAPIWrapContext(
        execute=_delegate_execute,
        trigger=trigger,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Assembler — truly DUMB (reads context, builds route)
# ═══════════════════════════════════════════════════════════════════════════════


def assemble_fastapi_route(
    ctx: FastAPIWrapContext,
    handler: Handler[Any],
    axes: Axes,
) -> FastAPIRoute:
    """Assemble FastAPIRoute from compiled WrapContext.

    All intelligence is in execute_with_pipeline.
    This just wraps it in a FastAPI route closure + generates OpenAPI.
    """
    compiled = compile_pipeline(ctx, axes)

    # Codecs that need request (RRC, Stateful, Delegate) get a route with request arg.
    # Codecs that don't (Immediate) get a simple no-arg route.
    if ctx.extractor is not None or ctx.inject_type is not type(None):
        async def _route(request: fastapi.Request) -> Any:
            return await execute_with_pipeline(compiled, handler, axes, request, target="fastapi")

        _route.__annotations__ = {
            "request": fastapi.Request,
            "return": ctx.response_type or Any,
        }
        endpoint = _route
    else:
        async def _simple_route() -> Any:
            return await execute_with_pipeline(compiled, handler, axes, None, target="fastapi")

        endpoint = _simple_route

    # OpenAPI extra for RRC
    openapi_extra: JsonDict | None = None
    if ctx.request_type is not None and ctx.trigger is not None:
        openapi_extra = build_rrc_openapi_extra(handler.codec, ctx.trigger, axes)

    return FastAPIRoute(
        endpoint=endpoint,
        response_model=ctx.response_type,
        openapi_extra=openapi_extra,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# OpenAPI Schema Generation — uses schema axis
# ═══════════════════════════════════════════════════════════════════════════════


def build_rrc_openapi_extra(
    codec: RequestResponseCodec,
    trigger: HTTPRouteTrigger,
    axes: Axes,
) -> JsonDict | None:
    """Build openapi_extra for RRC codec using schema axis."""
    import re
    from emergent.wire.compile._schema import to_openapi_schema

    req_cls = codec.request
    request_schema = to_openapi_schema(req_cls, axes)
    path_param_names = set(re.findall(r"\{(\w+)\}", trigger.path))

    path_parameters: JsonDictList = []
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

    result: JsonDict = {}

    if path_parameters:
        result["parameters"] = path_parameters

    if trigger.method in ("POST", "PUT", "PATCH"):
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
        query_parameters: JsonDictList = []
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

    kwargs: JsonDict = {
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
# FASTAPI_COMPILER — open-world codec binding set
# ═══════════════════════════════════════════════════════════════════════════════


FASTAPI_COMPILER: TargetCompiler[HTTPRouteTrigger] = TargetCompiler(
    trigger_type=HTTPRouteTrigger,
    adapters=(
        CodecBinding(RequestResponseCodec, rrc_from_codec),
        CodecBinding(StatefulCodec, stateful_from_codec),
        CodecBinding(ImmediateCodec, immediate_from_codec),
        CodecBinding(ImmediateFactoryCodec, immediate_from_codec),
        CodecBinding(DelegateCodec, delegate_from_codec),
    ),
    pipeline_protocol=FastAPIPipelineCompilable,
    pipeline_method="compile_fastapi_pipeline",
    assemble=assemble_fastapi_route,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Compilation Functions
# ═══════════════════════════════════════════════════════════════════════════════


def fastapi_compile_endpoint(
    endp: Endpoint,
    axes: Axes | None = None,
) -> list[fastapi.routing.APIRoute]:
    """Compile single Endpoint to list of FastAPI APIRoute objects."""
    axes = axes or Axes.default()
    routes: list[fastapi.routing.APIRoute] = []

    for trigger, handler in scan_endpoint(endp, HTTPRouteTrigger, RequestResponseCodec):
        ctx = rrc_from_codec(handler.codec, trigger)
        ctx = fold(
            handler.capabilities, ctx,
            FastAPIPipelineCompilable, "compile_fastapi_pipeline",
            trace=axes.trace,
        )
        fapi_route = assemble_fastapi_route(ctx, handler, axes)
        routes.append(
            fastapi.routing.APIRoute(
                path=trigger.path,
                endpoint=fapi_route.endpoint,
                methods=[trigger.method.upper()],
                response_model=fapi_route.response_model,
            )
        )

    for trigger, handler in scan_endpoint(endp, HTTPRouteTrigger, StatefulCodec):
        ctx = stateful_from_codec(handler.codec, trigger)
        ctx = fold(
            handler.capabilities, ctx,
            FastAPIPipelineCompilable, "compile_fastapi_pipeline",
            trace=axes.trace,
        )
        fapi_route = assemble_fastapi_route(ctx, handler, axes)
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
    """Compile wire Application to FastAPI app."""
    from contextlib import asynccontextmanager
    from collections.abc import AsyncIterator

    from emergent.wire.axis._capability import (
        FastAPIAppContext,
        FastAPIAppCompilable,
    )

    base_axes = axes or Axes.default()
    _compiler = compiler or FASTAPI_COMPILER

    app_scope: Scope | None = None
    _family: ScopeFamily[Tier] | None = family
    request_axes = base_axes

    if _family is not None:
        from types import MappingProxyType

        app_scope = Scope(detail="app")
        layer = ScopeLayer(
            scopes=MappingProxyType({App: app_scope}),
            family=_family,
            leaf=Request,
        )
        request_axes = base_axes.with_scope_layer(layer)
    elif base_axes.scope_layer is not None:
        # axes already has a scope_layer (e.g. from build_axes) — use it
        layer = base_axes.scope_layer
        _family = layer.family
        app_scope = layer.scopes.get(App)
        request_axes = base_axes

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
    async def lifespan(_fastapi_app: fastapi.FastAPI) -> AsyncIterator[None]:
        app_types = list(_family.types_for(App)) if _family else []
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

    # 2. Process application-level capabilities → middleware
    app_ctx = fold(
        app.capabilities, FastAPIAppContext(),
        FastAPIAppCompilable, "compile_fastapi_app",
        trace=base_axes.trace,
    )

    for middleware_cls, kwargs in app_ctx.middleware:
        fapi.add_middleware(middleware_cls, **kwargs)

    for router in app_ctx.routers:
        # routers stored as object in FastAPIAppContext to avoid fastapi import in axis layer
        assert isinstance(router, fastapi.routing.APIRouter)
        fapi.include_router(router)

    # 3. Exception handlers
    for _exc_trigger, _, exc_route in EXCEPTION_COMPILER.scan_and_wrap(app, base_axes):
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

    # 4. WebSocket routes
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

    # 5. HTTP routes — via TargetCompiler
    mounted: set[tuple[int, str]] = set()
    for trigger, handler, route in _compiler.scan_and_wrap(app, request_axes):
        register_handler(fapi, trigger, handler, route, request_axes, mounted)

    return fapi


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
    "FastAPIWrapContext",
    "FastAPIPipelineCompilable",
    "rrc_from_codec",
    "stateful_from_codec",
    "immediate_from_codec",
    "delegate_from_codec",
    "assemble_fastapi_route",
    "register_handler",
    "setup_fastapi_scope",
    "is_pydantic_model",
    "build_rrc_openapi_extra",
    "FASTAPI_COMPILER",
    "init_fastapi_extraction_constants",
)


# ═══════════════════════════════════════════════════════════════════════════════
# Backward-compat wrappers — compose from_codec → fold → assemble into one call
# ═══════════════════════════════════════════════════════════════════════════════


def wrap_rrc_fastapi(
    handler: Handler[RequestResponseCodec],
    trigger: HTTPRouteTrigger,
    axes: Axes,
) -> FastAPIRoute:
    ctx = rrc_from_codec(handler.codec, trigger)
    ctx = fold(handler.capabilities, ctx, FastAPIPipelineCompilable, "compile_fastapi_pipeline", trace=axes.trace)
    return assemble_fastapi_route(ctx, handler, axes)


def wrap_stateful_fastapi(
    handler: Handler[StatefulCodec],
    trigger: HTTPRouteTrigger,
    axes: Axes,
) -> FastAPIRoute:
    ctx = stateful_from_codec(handler.codec, trigger)
    ctx = fold(handler.capabilities, ctx, FastAPIPipelineCompilable, "compile_fastapi_pipeline", trace=axes.trace)
    return assemble_fastapi_route(ctx, handler, axes)


def wrap_immediate_fastapi(
    handler: Handler[Any],
    trigger: HTTPRouteTrigger,
    axes: Axes,
) -> FastAPIRoute:
    ctx = immediate_from_codec(handler.codec, trigger)
    ctx = fold(handler.capabilities, ctx, FastAPIPipelineCompilable, "compile_fastapi_pipeline", trace=axes.trace)
    return assemble_fastapi_route(ctx, handler, axes)


wrap_immediate_factory_fastapi = wrap_immediate_fastapi


def wrap_delegate_fastapi(
    handler: Handler[DelegateCodec],
    trigger: HTTPRouteTrigger,
    axes: Axes,
) -> FastAPIRoute:
    ctx = delegate_from_codec(handler.codec, trigger)
    ctx = fold(handler.capabilities, ctx, FastAPIPipelineCompilable, "compile_fastapi_pipeline", trace=axes.trace)
    return assemble_fastapi_route(ctx, handler, axes)


# Old context name alias
FastAPIPipelineContext = FastAPIWrapContext


# ═══════════════════════════════════════════════════════════════════════════════
# RFC 7807 validation error handler — opt-in helper
# ═══════════════════════════════════════════════════════════════════════════════


def install_rfc7807_validation_handler(app: fastapi.FastAPI) -> None:
    """Register exception handler that converts FastAPI's 422 to RFC 7807 format.

    By default FastAPI returns ``{"detail": [...]}``. This replaces it with
    RFC 7807 Problem Detail (``{"type", "title", "status", "detail"}``),
    matching the OpenAPI schema declared by ``ProblemResponse``.

    Call AFTER ``fastapi_compile``::

        fapi = fastapi_compile(wire_app, axes)
        install_rfc7807_validation_handler(fapi)
    """
    from fastapi.exceptions import RequestValidationError
    from starlette.responses import JSONResponse

    async def _handler(
        request: fastapi.Request,
        exc: Exception,
    ) -> JSONResponse:
        # Starlette's ExceptionHandler protocol types `exc` as the base Exception;
        # FastAPI only dispatches RequestValidationError to this registration, so the
        # narrowing always holds at runtime.
        assert isinstance(exc, RequestValidationError)
        errors = exc.errors()
        fields = [
            f"{'.'.join(str(loc) for loc in e.get('loc', ()))}: {e.get('msg', '')}"
            for e in errors
        ]
        return JSONResponse(
            status_code=422,
            content={
                "type": "urn:emergent:error:validation",
                "title": "Validation Error",
                "status": 422,
                "detail": "; ".join(fields),
                "instance": str(request.url.path),
            },
            media_type="application/problem+json",
        )

    app.add_exception_handler(RequestValidationError, _handler)


# Alias for cleaner API
compile = fastapi_compile
compile_stack = fastapi_compile_stack
compile_endpoint = fastapi_compile_endpoint

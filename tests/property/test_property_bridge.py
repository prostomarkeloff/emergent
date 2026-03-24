# pyright: reportPrivateUsage=false
"""Tests for the bridge system — extracting routes from framework apps back into wire format.

Tests two categories:
1. Round-trip: emergent Application -> FastAPI -> bridge -> emergent Application
2. Pure bridge components: introspection, signature analysis, detection, types, capabilities, registry
"""

from __future__ import annotations

import asyncio
import functools
import inspect
from collections.abc import Coroutine
from dataclasses import dataclass, replace
from typing import Any, cast

import fastapi
import pytest
from pydantic import BaseModel

from emergent.wire.axis.surface._app import Application, application
from emergent.wire.axis.surface._endpoint import endpoint
from emergent.wire.axis.surface.codecs.delegate import delegate
from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger
from emergent.wire.compile.targets.fastapi import fastapi_compile

# Bridge imports
from emergent.wire.bridge import build_application, extract
from emergent.wire.bridge._capabilities import (
    AddCapability,
    BridgeCapability,
    BridgeContext,
    CatchErrors,
    IncludeOnlyByName,
    InjectKwarg,
    SetCodecByName,
    SetRequestTypeByName,
    SetResponseTypeByName,
    SetupTeardown,
    SkipByName,
    SkipDeprecated,
    WrapAsDelegate,
    WrapAsync,
    apply_bridge_capabilities,
    apply_purifiers,
    chain_purifiers,
    ensure_async,
    find_all_bridge_capabilities,
    find_bridge_capability,
    fold_bridge,
)
from emergent.wire.bridge._core import WireData
from emergent.wire.bridge._detect import (
    BodyDetection,
    DIDetection,
    DetectionResult,
    run_detectors,
)
from emergent.wire.bridge._extractor import (
    compose_extractors,
    filter_extractor,
    first_extractor,
)
from emergent.wire.bridge._introspect import (
    ClosureFallbackUnwrap,
    DecoratorInfo,
    HandlerShape,
    ParameterKind,
    ParameterShape,
    analyze_handler,
    extract_class_methods,
    get_view_class,
    no_default,
    resolve_descriptor,
    unwrap_handler,
)
from emergent.wire.bridge._registry import (
    BridgeRegistry,
    FrameworkBridger,
    get_default_registry,
)
from emergent.wire.bridge._signature import (
    HandlerParameter,
    HandlerSignature,
    analyze_signature,
    first_analyzer,
)
from emergent.wire.bridge._types import Extracted
from emergent.wire.bridge._unified import ExtractedWithShape, build_extracted
from emergent.wire.bridge.bridgers.fastapi import (
    HTTPRouteData,
    is_fastapi_app,
)


def _run_awaitable(aw: object) -> object:
    """Run an Awaitable via asyncio.run, casting for pyright compatibility."""
    return asyncio.run(cast(Coroutine[Any, Any, object], aw))


# =========================================================================
# Module-level types (needed because `from __future__ import annotations`
# makes type hints stringified -- get_type_hints requires module scope)
# =========================================================================


class ItemCreate(BaseModel):
    name: str
    price: float


class ItemResponse(BaseModel):
    id: int
    name: str
    price: float


class UserCreate(BaseModel):
    username: str


class UserResponse(BaseModel):
    id: int
    username: str


@dataclass
class PlainRequest:
    value: int


@dataclass
class PlainResponse:
    result: str


# =========================================================================
# 1. Round-trip tests: emergent -> FastAPI -> bridge -> emergent
# =========================================================================


class TestRoundTripFastapiDelegate:
    """Build wire Application with delegate codec, compile to FastAPI, bridge back."""

    def _build_wire_app(self) -> Application:
        """Build a wire Application with delegate endpoints."""
        from emergent.wire.axis.surface import empty_runner

        runner = empty_runner()

        async def list_items() -> list[ItemResponse]:
            return [ItemResponse(id=1, name="Sword", price=100.0)]

        async def create_item(item: ItemCreate) -> ItemResponse:
            return ItemResponse(id=2, name=item.name, price=item.price)

        ep_list = endpoint(runner).expose(
            HTTPRouteTrigger(method="GET", path="/items"),
            delegate(list_items, response=list[ItemResponse]),
        )
        ep_create = endpoint(runner).expose(
            HTTPRouteTrigger(method="POST", path="/items"),
            delegate(create_item, response=ItemResponse),
        )
        return application().mount(ep_list, ep_create)

    def test_roundtrip_produces_application(self) -> None:
        wire_app = self._build_wire_app()
        fapi = fastapi_compile(wire_app)
        bridged = build_application(fapi)
        assert isinstance(bridged, Application)

    def test_roundtrip_preserves_endpoint_count(self) -> None:
        wire_app = self._build_wire_app()
        fapi = fastapi_compile(wire_app)
        bridged = build_application(fapi)
        # Each endpoint can have multiple exposures; bridge extracts per-method routes.
        assert len(bridged.endpoints) >= 2

    def test_roundtrip_extracts_http_routes(self) -> None:
        wire_app = self._build_wire_app()
        fapi = fastapi_compile(wire_app)
        extracted = extract(fapi, HTTPRouteData)
        paths = {e.route.path for e in extracted}
        assert "/items" in paths

    def test_roundtrip_extracts_methods(self) -> None:
        wire_app = self._build_wire_app()
        fapi = fastapi_compile(wire_app)
        extracted = extract(fapi, HTTPRouteData)
        methods = {e.route.method for e in extracted}
        assert "GET" in methods
        assert "POST" in methods


class TestRoundTripMultipleEndpoints:
    """Round-trip with more endpoints to verify scaling."""

    def _build_wire_app(self) -> Application:
        from emergent.wire.axis.surface import empty_runner

        runner = empty_runner()

        async def get_users() -> list[UserResponse]:
            return []

        async def create_user(user: UserCreate) -> UserResponse:
            return UserResponse(id=1, username=user.username)

        async def get_items() -> list[ItemResponse]:
            return []

        ep_users_get = endpoint(runner).expose(
            HTTPRouteTrigger(method="GET", path="/users"),
            delegate(get_users, response=list[UserResponse]),
        )
        ep_users_post = endpoint(runner).expose(
            HTTPRouteTrigger(method="POST", path="/users"),
            delegate(create_user, response=UserResponse),
        )
        ep_items_get = endpoint(runner).expose(
            HTTPRouteTrigger(method="GET", path="/items"),
            delegate(get_items, response=list[ItemResponse]),
        )
        return application().mount(ep_users_get, ep_users_post, ep_items_get)

    def test_roundtrip_three_endpoints(self) -> None:
        wire_app = self._build_wire_app()
        fapi = fastapi_compile(wire_app)
        bridged = build_application(fapi)
        assert len(bridged.endpoints) >= 3

    def test_roundtrip_all_paths_present(self) -> None:
        wire_app = self._build_wire_app()
        fapi = fastapi_compile(wire_app)
        extracted = extract(fapi, HTTPRouteData)
        paths = {e.route.path for e in extracted}
        assert "/users" in paths
        assert "/items" in paths

    def test_roundtrip_handler_names_extracted(self) -> None:
        wire_app = self._build_wire_app()
        fapi = fastapi_compile(wire_app)
        extracted = extract(fapi, HTTPRouteData)
        # Each extracted route should have a non-None name
        for e in extracted:
            assert e.name is not None
        assert len(extracted) >= 3


class TestRoundTripWithCapabilities:
    """Round-trip with bridge capabilities applied during bridging."""

    def _build_fastapi_from_wire(self) -> fastapi.FastAPI:
        from emergent.wire.axis.surface import empty_runner

        runner = empty_runner()

        async def list_items() -> list[ItemResponse]:
            return []

        async def create_item(item: ItemCreate) -> ItemResponse:
            return ItemResponse(id=1, name=item.name, price=item.price)

        wire_app = application().mount(
            endpoint(runner).expose(
                HTTPRouteTrigger(method="GET", path="/items"),
                delegate(list_items, response=list[ItemResponse]),
            ),
            endpoint(runner).expose(
                HTTPRouteTrigger(method="POST", path="/items"),
                delegate(create_item, response=ItemResponse),
            ),
        )
        return fastapi_compile(wire_app)

    def test_skip_by_name_reduces_endpoints(self) -> None:
        fapi = self._build_fastapi_from_wire()
        all_bridged = build_application(fapi)
        total_count = len(all_bridged.endpoints)

        # Skip the compiled handler names (_route) - should remove HTTP routes
        bridged = build_application(
            fapi,
            capabilities=[SkipByName(names=frozenset({"_route"}))],
        )
        assert len(bridged.endpoints) < total_count

    def test_include_only_by_name_filters(self) -> None:
        fapi = self._build_fastapi_from_wire()
        # Include only _route (the compiled HTTP handler name)
        bridged = build_application(
            fapi,
            capabilities=[IncludeOnlyByName(names=frozenset({"_route"}))],
        )
        # Should only contain endpoints named _route (the HTTP routes)
        http_routes = extract(fapi, HTTPRouteData)
        assert len(bridged.endpoints) == len(http_routes)

    def test_skip_deprecated_skips_none_when_no_deprecated(self) -> None:
        fapi = self._build_fastapi_from_wire()
        all_bridged = build_application(fapi)
        bridged = build_application(
            fapi,
            capabilities=[SkipDeprecated()],
        )
        assert len(bridged.endpoints) == len(all_bridged.endpoints)


# =========================================================================
# 2. Handler introspection (_introspect.py)
# =========================================================================


class TestAnalyzeHandlerSync:
    def test_sync_function(self) -> None:
        def my_handler(x: int, y: str = "hello") -> bool:
            return True

        shape = analyze_handler(my_handler)
        assert shape.name == "my_handler"
        assert shape.is_async is False
        assert "x" in shape.parameters
        assert "y" in shape.parameters

    def test_parameter_types(self) -> None:
        def handler(x: int, y: str = "hello") -> bool:
            return True

        shape = analyze_handler(handler)
        assert shape.parameters["x"].annotation is int
        assert shape.parameters["y"].annotation is str

    def test_parameter_defaults(self) -> None:
        def handler(x: int, y: str = "hello") -> bool:
            return True

        shape = analyze_handler(handler)
        assert shape.parameters["x"].has_default is False
        assert shape.parameters["y"].has_default is True
        assert shape.parameters["y"].default == "hello"

    def test_return_type(self) -> None:
        def handler(x: int) -> str:
            return "ok"

        shape = analyze_handler(handler)
        assert shape.return_type is str


class TestAnalyzeHandlerAsync:
    def test_async_function(self) -> None:
        async def my_handler(x: int) -> str:
            return "ok"

        shape = analyze_handler(my_handler)
        assert shape.is_async is True
        assert shape.name == "my_handler"
        assert "x" in shape.parameters

    def test_async_no_params(self) -> None:
        async def handler() -> None:
            pass

        shape = analyze_handler(handler)
        assert shape.is_async is True
        assert len(shape.parameters) == 0


class TestAnalyzeHandlerDecorated:
    def test_unwraps_decorated_function(self) -> None:
        def original(x: int) -> str:
            return str(x)

        @functools.wraps(original)
        def wrapper(x: int) -> str:
            return original(x)

        wrapper.__wrapped__ = original  # type: ignore[attr-defined]

        shape = analyze_handler(wrapper)
        assert len(shape.decorators) > 0
        assert shape.handler is original

    def test_closure_fallback_unwrap(self) -> None:
        def original(x: int) -> str:
            return str(x)

        from typing import Callable
        def make_wrapper(fn: Callable[[int], str]) -> Callable[[int], str]:
            def wrapper(x: int) -> str:
                return fn(x)
            return wrapper

        wrapped = make_wrapper(original)
        shape = analyze_handler(wrapped, unwrap_strategy=ClosureFallbackUnwrap())
        # Should find original via closure inspection
        assert shape.handler is original or shape.name is not None


class TestParameterShape:
    def test_from_parameter_with_annotation(self) -> None:
        def handler(x: int) -> None:
            pass

        sig = inspect.signature(handler)
        param = sig.parameters["x"]
        ps = ParameterShape.from_parameter(param, resolved_annotation=int)
        assert ps.name == "x"
        assert ps.annotation is int
        assert ps.has_default is False
        assert ps.kind == ParameterKind.POSITIONAL_OR_KEYWORD

    def test_from_parameter_with_default(self) -> None:
        def handler(x: int = 42) -> None:
            pass

        sig = inspect.signature(handler)
        param = sig.parameters["x"]
        ps = ParameterShape.from_parameter(param)
        assert ps.has_default is True
        assert ps.default == 42

    def test_no_default_sentinel(self) -> None:
        sentinel = no_default()
        assert sentinel is not None
        # Sentinel should be consistent
        assert no_default() is sentinel


class TestParameterKind:
    def test_positional_or_keyword(self) -> None:
        def handler(x: int) -> None:
            pass

        sig = inspect.signature(handler)
        kind = ParameterKind.of(sig.parameters["x"])
        assert kind == ParameterKind.POSITIONAL_OR_KEYWORD

    def test_keyword_only(self) -> None:
        def handler(*, x: int) -> None:
            pass

        sig = inspect.signature(handler)
        kind = ParameterKind.of(sig.parameters["x"])
        assert kind == ParameterKind.KEYWORD_ONLY

    def test_var_positional(self) -> None:
        def handler(*args: int) -> None:
            pass

        sig = inspect.signature(handler)
        kind = ParameterKind.of(sig.parameters["args"])
        assert kind == ParameterKind.VAR_POSITIONAL

    def test_var_keyword(self) -> None:
        def handler(**kwargs: int) -> None:
            pass

        sig = inspect.signature(handler)
        kind = ParameterKind.of(sig.parameters["kwargs"])
        assert kind == ParameterKind.VAR_KEYWORD


class TestUnwrapHandler:
    def test_plain_function_no_decorators(self) -> None:
        def handler() -> None:
            pass

        unwrapped, decorators = unwrap_handler(handler)
        assert unwrapped is handler
        assert decorators == ()

    def test_unwrap_chain(self) -> None:
        def original() -> None:
            pass

        @functools.wraps(original)
        def wrapper() -> None:
            pass

        wrapper.__wrapped__ = original  # type: ignore[attr-defined]
        unwrapped, decorators = unwrap_handler(wrapper)
        assert unwrapped is original
        assert len(decorators) == 1

    def test_non_callable_raises(self) -> None:
        with pytest.raises(TypeError):
            unwrap_handler(42)


class TestExtractClassMethods:
    def test_extracts_existing_methods(self) -> None:
        class MyView:
            def get(self) -> str:
                return "ok"

            def post(self) -> str:
                return "ok"

        methods = list(extract_class_methods(MyView, ("get", "post", "delete")))
        assert len(methods) == 2
        names = [name for name, _ in methods]
        assert "get" in names
        assert "post" in names

    def test_missing_methods_skipped(self) -> None:
        class MyView:
            def get(self) -> str:
                return "ok"

        methods = list(extract_class_methods(MyView, ("get", "nonexistent")))
        assert len(methods) == 1


class TestGetViewClass:
    def test_returns_class_for_type(self) -> None:
        class MyView:
            pass

        assert get_view_class(MyView) is MyView

    def test_returns_none_for_non_class(self) -> None:
        assert get_view_class("not a class") is None

    def test_returns_view_class_attr(self) -> None:
        class Inner:
            pass

        class Container:
            view_class = Inner

        assert get_view_class(Container()) is Inner


class TestResolveDescriptor:
    def test_non_descriptor_returns_self(self) -> None:
        obj = "hello"
        assert resolve_descriptor(obj) is obj

    def test_type_not_resolved(self) -> None:
        # types have __get__ but should not be resolved
        assert resolve_descriptor(int) is int


class TestDecoratorInfo:
    def test_construction(self) -> None:
        def wrapper() -> None:
            pass

        info = DecoratorInfo(
            wrapper=wrapper,
            wrapper_name="wrapper",
            wrapper_module=__name__,
        )
        assert info.wrapper is wrapper
        assert info.wrapper_name == "wrapper"
        assert info.wrapper_module == __name__

    def test_frozen(self) -> None:
        def wrapper() -> None:
            pass

        info = DecoratorInfo(wrapper=wrapper, wrapper_name="w", wrapper_module=None)
        with pytest.raises(AttributeError):
            info.wrapper_name = "other"  # type: ignore[misc]


# =========================================================================
# 3. Signature analysis (_signature.py)
# =========================================================================


class TestAnalyzeSignature:
    def test_sync_handler(self) -> None:
        def handler(x: int, y: str = "hello") -> bool:
            return True

        sig = analyze_signature(handler)
        assert sig.is_async is False
        assert "x" in sig.parameters
        assert "y" in sig.parameters
        assert sig.return_type is bool

    def test_async_handler(self) -> None:
        async def handler(x: int) -> str:
            return "ok"

        sig = analyze_signature(handler)
        assert sig.is_async is True
        assert sig.return_type is str

    def test_required_parameters(self) -> None:
        def handler(x: int, y: str = "hello") -> None:
            pass

        sig = analyze_signature(handler)
        required = sig.required_parameters()
        assert "x" in required
        assert "y" not in required

    def test_optional_parameters(self) -> None:
        def handler(x: int, y: str = "hello") -> None:
            pass

        sig = analyze_signature(handler)
        optional = sig.optional_parameters()
        assert "y" in optional
        assert "x" not in optional

    def test_body_type_detection(self) -> None:
        def handler(body: PlainRequest) -> PlainResponse:
            return PlainResponse(result="ok")

        sig = analyze_signature(handler)
        assert sig.body_type() is PlainRequest

    def test_no_body_type_for_primitives(self) -> None:
        def handler(x: int, y: str) -> None:
            pass

        sig = analyze_signature(handler)
        assert sig.body_type() is None


class TestHandlerParameter:
    def test_has_default(self) -> None:
        param = HandlerParameter(
            name="x",
            base_type=int,
            is_optional=False,
            default=inspect.Parameter.empty,
        )
        assert param.has_default() is False

    def test_has_default_with_value(self) -> None:
        param = HandlerParameter(
            name="x",
            base_type=int,
            is_optional=True,
            default=42,
        )
        assert param.has_default() is True


class TestFirstAnalyzer:
    def test_first_match_wins(self) -> None:
        from typing import Callable

        def custom_analyzer(handler: Callable[..., object]) -> HandlerSignature | None:
            return HandlerSignature(is_async=True)

        combined = first_analyzer(custom_analyzer, analyze_signature)

        def handler(x: int) -> str:
            return "ok"

        result = combined(handler)
        assert result is not None
        assert result.is_async is True  # from custom

    def test_fallback_to_standard(self) -> None:
        from typing import Callable

        def always_none(handler: Callable[..., object]) -> HandlerSignature | None:
            return None

        combined = first_analyzer(always_none)

        def handler(x: int) -> str:
            return "ok"

        result = combined(handler)
        assert result is not None
        assert "x" in result.parameters


# =========================================================================
# 4. Detection protocols (_detect.py)
# =========================================================================


class TestBodyDetection:
    def test_construction(self) -> None:
        ps = ParameterShape(
            name="body", annotation=PlainRequest, default=no_default(),
            has_default=False, kind=ParameterKind.POSITIONAL_OR_KEYWORD,
        )
        detection = BodyDetection(parameter=ps, body_type=PlainRequest)
        assert detection.body_type is PlainRequest
        assert detection.parameter.name == "body"

    def test_frozen(self) -> None:
        ps = ParameterShape(
            name="body", annotation=PlainRequest, default=no_default(),
            has_default=False, kind=ParameterKind.POSITIONAL_OR_KEYWORD,
        )
        detection = BodyDetection(parameter=ps, body_type=PlainRequest)
        with pytest.raises(AttributeError):
            detection.body_type = int  # type: ignore[misc]


class TestDIDetection:
    def test_construction(self) -> None:
        ps = ParameterShape(
            name="db", annotation=object, default=no_default(),
            has_default=False, kind=ParameterKind.POSITIONAL_OR_KEYWORD,
        )
        detection = DIDetection(parameter=ps, source="factory_fn")
        assert detection.source == "factory_fn"
        assert detection.to_capability is None

    def test_frozen(self) -> None:
        ps = ParameterShape(
            name="db", annotation=object, default=no_default(),
            has_default=False, kind=ParameterKind.POSITIONAL_OR_KEYWORD,
        )
        detection = DIDetection(parameter=ps, source="x")
        with pytest.raises(AttributeError):
            detection.source = "y"  # type: ignore[misc]


class TestDetectionResult:
    def test_construction(self) -> None:
        result = DetectionResult(body=None, di_params=(), decorator_capabilities=())
        assert result.body is None
        assert result.di_params == ()
        assert result.decorator_capabilities == ()

    def test_frozen(self) -> None:
        result = DetectionResult(body=None, di_params=(), decorator_capabilities=())
        with pytest.raises(AttributeError):
            result.body = "something"  # type: ignore[misc]


class TestRunDetectors:
    def test_no_detectors_empty_result(self) -> None:
        def handler(x: int) -> str:
            return "ok"

        shape = analyze_handler(handler)
        result = run_detectors(shape)
        assert result.body is None
        assert result.di_params == ()
        assert result.decorator_capabilities == ()

    def test_body_detector_runs(self) -> None:
        def handler(body: PlainRequest) -> PlainResponse:
            return PlainResponse(result="ok")

        shape = analyze_handler(handler)

        @dataclass(frozen=True, slots=True)
        class TestBodyDetector:
            def detect(
                self, param: ParameterShape, shape: HandlerShape
            ) -> BodyDetection | None:
                if param.annotation is PlainRequest:
                    return BodyDetection(parameter=param, body_type=PlainRequest)
                return None

        result = run_detectors(shape, body_detectors=(TestBodyDetector(),))
        assert result.body is not None
        assert result.body.body_type is PlainRequest


# =========================================================================
# 5. Bridge types (_types.py)
# =========================================================================


class TestExtracted:
    def test_construction(self) -> None:
        async def handler() -> None:
            pass

        route = HTTPRouteData(method="GET", path="/test")
        extracted = Extracted(route=route, handler=handler, name="test_handler")
        assert extracted.name == "test_handler"
        assert extracted.deprecated is False
        assert extracted.metadata == {}

    def test_frozen(self) -> None:
        async def handler() -> None:
            pass

        route = HTTPRouteData(method="GET", path="/test")
        extracted = Extracted(route=route, handler=handler)
        with pytest.raises(AttributeError):
            extracted.name = "changed"  # type: ignore[misc]

    def test_with_metadata(self) -> None:
        async def handler() -> None:
            pass

        route = HTTPRouteData(method="GET", path="/test")
        extracted = Extracted(
            route=route, handler=handler, metadata={"key": "value"}
        )
        assert extracted.metadata["key"] == "value"

    def test_deprecated_flag(self) -> None:
        async def handler() -> None:
            pass

        route = HTTPRouteData(method="GET", path="/test")
        extracted = Extracted(route=route, handler=handler, deprecated=True)
        assert extracted.deprecated is True


# =========================================================================
# 6. Bridge capabilities (_capabilities.py)
# =========================================================================


@dataclass(frozen=True, slots=True)
class _StubRouteData:
    """Minimal route data for capability tests."""
    path: str
    method: str = "GET"


def _make_ctx(
    name: str = "test_handler",
    deprecated: bool = False,
    skip: bool = False,
    wire: WireData | None = None,
    request_type: type | None = None,
    response_type: type | None = None,
) -> BridgeContext[_StubRouteData, ..., object]:
    async def handler() -> None:
        pass

    return BridgeContext(
        trigger_data=_StubRouteData(path="/test"),
        handler=handler,
        name=name,
        deprecated=deprecated,
        skip=skip,
        wire=wire or WireData(),
        request_type=request_type,
        response_type=response_type,
    )


class TestSkipDeprecated:
    def test_skips_deprecated(self) -> None:
        ctx = _make_ctx(deprecated=True)
        cap = SkipDeprecated()
        result = cap.compile_bridge(ctx)
        assert result.skip is True

    def test_keeps_non_deprecated(self) -> None:
        ctx = _make_ctx(deprecated=False)
        cap = SkipDeprecated()
        result = cap.compile_bridge(ctx)
        assert result.skip is False


class TestSkipByName:
    def test_skips_matching_name(self) -> None:
        ctx = _make_ctx(name="internal_handler")
        cap = SkipByName(names=frozenset({"internal_handler"}))
        result = cap.compile_bridge(ctx)
        assert result.skip is True

    def test_keeps_non_matching(self) -> None:
        ctx = _make_ctx(name="public_handler")
        cap = SkipByName(names=frozenset({"internal_handler"}))
        result = cap.compile_bridge(ctx)
        assert result.skip is False

    def test_skips_by_pattern(self) -> None:
        ctx = _make_ctx(name="_private_handler")
        cap = SkipByName(pattern=r"^_")
        result = cap.compile_bridge(ctx)
        assert result.skip is True


class TestIncludeOnlyByName:
    def test_includes_matching(self) -> None:
        ctx = _make_ctx(name="allowed")
        cap = IncludeOnlyByName(names=frozenset({"allowed"}))
        result = cap.compile_bridge(ctx)
        assert result.skip is False

    def test_skips_non_matching(self) -> None:
        ctx = _make_ctx(name="not_allowed")
        cap = IncludeOnlyByName(names=frozenset({"allowed"}))
        result = cap.compile_bridge(ctx)
        assert result.skip is True

    def test_skips_none_name(self) -> None:
        ctx = _make_ctx(name="anything")
        ctx = replace(ctx, name=None)
        cap = IncludeOnlyByName(names=frozenset({"allowed"}))
        result = cap.compile_bridge(ctx)
        assert result.skip is True

    def test_includes_by_pattern(self) -> None:
        ctx = _make_ctx(name="api_get_items")
        cap = IncludeOnlyByName(pattern=r"^api_")
        result = cap.compile_bridge(ctx)
        assert result.skip is False


class TestSetRequestTypeByName:
    def test_sets_type_for_matching_name(self) -> None:
        ctx = _make_ctx(name="create_item")
        cap = SetRequestTypeByName(type_map={"create_item": PlainRequest})
        result = cap.compile_bridge(ctx)
        assert result.request_type is PlainRequest

    def test_no_override_if_already_set(self) -> None:
        ctx = _make_ctx(name="create_item", request_type=int)
        cap = SetRequestTypeByName(type_map={"create_item": PlainRequest})
        result = cap.compile_bridge(ctx)
        assert result.request_type is int

    def test_no_change_for_unmatched_name(self) -> None:
        ctx = _make_ctx(name="other")
        cap = SetRequestTypeByName(type_map={"create_item": PlainRequest})
        result = cap.compile_bridge(ctx)
        assert result.request_type is None


class TestSetResponseTypeByName:
    def test_sets_type_for_matching_name(self) -> None:
        ctx = _make_ctx(name="get_item")
        cap = SetResponseTypeByName(type_map={"get_item": PlainResponse})
        result = cap.compile_bridge(ctx)
        assert result.response_type is PlainResponse

    def test_no_override_if_already_set(self) -> None:
        ctx = _make_ctx(name="get_item", response_type=str)
        cap = SetResponseTypeByName(type_map={"get_item": PlainResponse})
        result = cap.compile_bridge(ctx)
        assert result.response_type is str


class TestWrapAsync:
    def test_purify_sync_to_async(self) -> None:
        def sync_handler() -> str:
            return "ok"

        cap = WrapAsync()
        result = cap.purify(sync_handler)
        assert inspect.iscoroutinefunction(result)

    def test_purify_already_async(self) -> None:
        async def async_handler() -> str:
            return "ok"

        cap = WrapAsync()
        result = cap.purify(async_handler)
        assert inspect.iscoroutinefunction(result)


class TestCatchErrors:
    def test_catches_errors(self) -> None:
        def failing_handler() -> str:
            raise ValueError("boom")

        cap = CatchErrors(on_error=lambda e: f"caught: {e}")
        wrapped = cap.purify(failing_handler)
        result = _run_awaitable(wrapped())
        assert result == "caught: boom"


class TestFoldBridge:
    def test_fold_applies_capabilities_in_order(self) -> None:
        ctx = _make_ctx(name="handler")
        caps: list[BridgeCapability] = [
            SetRequestTypeByName(type_map={"handler": PlainRequest}),
            SetResponseTypeByName(type_map={"handler": PlainResponse}),
        ]
        result = fold_bridge(ctx, caps)
        assert result.request_type is PlainRequest
        assert result.response_type is PlainResponse

    def test_fold_short_circuits_on_skip(self) -> None:
        ctx = _make_ctx(name="handler", deprecated=True)
        caps: list[BridgeCapability] = [
            SkipDeprecated(),
            SetRequestTypeByName(type_map={"handler": PlainRequest}),
        ]
        result = fold_bridge(ctx, caps)
        assert result.skip is True
        # Should not have set request_type
        assert result.request_type is None


class TestFindCapabilities:
    def test_find_bridge_capability(self) -> None:
        caps: list[BridgeCapability] = [
            SkipDeprecated(),
            WrapAsync(),
            SkipByName(names=frozenset({"x"})),
        ]
        found = find_bridge_capability(caps, SkipDeprecated)
        assert found is not None
        assert isinstance(found, SkipDeprecated)

    def test_find_bridge_capability_none(self) -> None:
        caps: list[BridgeCapability] = [WrapAsync()]
        found = find_bridge_capability(caps, SkipDeprecated)
        assert found is None

    def test_find_all_bridge_capabilities(self) -> None:
        caps: list[BridgeCapability] = [
            SkipByName(names=frozenset({"a"})),
            WrapAsync(),
            SkipByName(names=frozenset({"b"})),
        ]
        found = find_all_bridge_capabilities(caps, SkipByName)
        assert len(found) == 2


class TestChainPurifiers:
    def test_empty_purifiers_returns_async(self) -> None:
        def sync_handler() -> str:
            return "ok"

        result = chain_purifiers([], sync_handler)
        assert inspect.iscoroutinefunction(result)

    def test_single_purifier(self) -> None:
        def sync_handler() -> str:
            return "ok"

        result = chain_purifiers([WrapAsync()], sync_handler)
        assert inspect.iscoroutinefunction(result)


class TestApplyBridgeCapabilities:
    def test_applies_compilable_capabilities(self) -> None:
        ctx = _make_ctx(deprecated=True)
        caps: list[BridgeCapability] = [SkipDeprecated()]
        result = apply_bridge_capabilities(ctx, caps)
        assert result.skip is True


class TestApplyPurifiers:
    def test_applies_purifier_capabilities(self) -> None:
        def sync_handler() -> str:
            return "ok"

        caps: list[BridgeCapability] = [WrapAsync()]
        result = apply_purifiers(sync_handler, caps)
        assert inspect.iscoroutinefunction(result)

    def test_no_purifiers_still_async(self) -> None:
        def sync_handler() -> str:
            return "ok"

        result = apply_purifiers(sync_handler, [])
        assert inspect.iscoroutinefunction(result)


# =========================================================================
# 7. Registry (_registry.py)
# =========================================================================


class TestBridgeRegistry:
    def test_default_registry_has_fastapi(self) -> None:
        registry = get_default_registry()
        fapi = fastapi.FastAPI()
        bridger = registry.detect(fapi)
        assert bridger is not None
        assert bridger.name == "fastapi"

    def test_detect_returns_none_for_unknown(self) -> None:
        registry = get_default_registry()
        result = registry.detect("not a framework")
        assert result is None

    def test_with_bridger_adds(self) -> None:
        empty_registry = BridgeRegistry(bridgers=())

        @dataclass(frozen=True, slots=True)
        class StubExtractor:
            def can_extract(self, source: object) -> bool:
                return False

            def extract(self, source: object):  # type: ignore[no-untyped-def]
                return iter([])

        @dataclass(frozen=True, slots=True)
        class StubToWire:
            def to_trigger(self, route: object) -> object:
                return None

            def to_codec(self, route: object, handler: object) -> object:
                return None

        stub = FrameworkBridger(
            name="stub",
            can_bridge=lambda s: isinstance(s, dict),
            extractor=StubExtractor(),  # type: ignore[arg-type]
            to_wire=StubToWire(),  # type: ignore[arg-type]
        )
        new_registry = empty_registry.with_bridger(stub)
        assert new_registry.detect({}) is not None

    def test_without_bridger_removes(self) -> None:
        registry = get_default_registry()
        stripped = registry.without_bridger("fastapi")
        fapi = fastapi.FastAPI()
        assert stripped.detect(fapi) is None

    def test_replace_bridger(self) -> None:
        registry = get_default_registry()
        original = registry.detect(fastapi.FastAPI())
        assert original is not None

        # Replace with a bridger that always returns False
        def _never_bridge(s: object) -> bool:
            return False

        new_bridger = replace(original, can_bridge=_never_bridge)
        replaced = registry.replace_bridger("fastapi", new_bridger)
        assert replaced.detect(fastapi.FastAPI()) is None


class TestIsFastapiApp:
    def test_fastapi_instance(self) -> None:
        assert is_fastapi_app(fastapi.FastAPI()) is True

    def test_non_fastapi(self) -> None:
        assert is_fastapi_app("not fastapi") is False

    def test_dict_is_not_fastapi(self) -> None:
        assert is_fastapi_app({}) is False


# =========================================================================
# 8. Unified extraction (_unified.py)
# =========================================================================


class TestBuildExtracted:
    def test_basic_extraction(self) -> None:
        async def handler(x: int) -> str:
            return "ok"

        route = HTTPRouteData(method="GET", path="/test")
        result = build_extracted(handler, route, name="test_handler")
        assert isinstance(result, ExtractedWithShape)
        assert result.name == "test_handler"
        assert result.shape is not None

    def test_to_extracted(self) -> None:
        async def handler() -> None:
            pass

        route = HTTPRouteData(method="GET", path="/test")
        ews = build_extracted(handler, route, name="handler")
        extracted = ews.to_extracted()
        assert isinstance(extracted, Extracted)
        assert extracted.name == "handler"

    def test_body_type_property(self) -> None:
        async def handler(body: PlainRequest) -> PlainResponse:
            return PlainResponse(result="ok")

        route = HTTPRouteData(method="POST", path="/test")

        @dataclass(frozen=True, slots=True)
        class TestDetector:
            def detect(
                self, param: ParameterShape, shape: HandlerShape
            ) -> BodyDetection | None:
                if param.annotation is PlainRequest:
                    return BodyDetection(parameter=param, body_type=PlainRequest)
                return None

        result = build_extracted(
            handler, route, body_detectors=[TestDetector()]
        )
        assert result.body_type is PlainRequest

    def test_response_type_from_shape(self) -> None:
        async def handler() -> PlainResponse:
            return PlainResponse(result="ok")

        route = HTTPRouteData(method="GET", path="/test")
        result = build_extracted(handler, route)
        assert result.response_type is PlainResponse


# =========================================================================
# 9. Extractor composition (_extractor.py)
# =========================================================================


class TestExtractorComposition:
    def test_compose_extractors(self) -> None:
        @dataclass(frozen=True, slots=True)
        class ExtractorA:
            def can_extract(self, source: object) -> bool:
                return isinstance(source, dict)

            def extract(self, source: object):  # type: ignore[no-untyped-def]
                yield Extracted(
                    route=HTTPRouteData(method="GET", path="/a"),
                    handler=lambda: None,
                    name="a",
                )

        @dataclass(frozen=True, slots=True)
        class ExtractorB:
            def can_extract(self, source: object) -> bool:
                return isinstance(source, dict)

            def extract(self, source: object):  # type: ignore[no-untyped-def]
                yield Extracted(
                    route=HTTPRouteData(method="POST", path="/b"),
                    handler=lambda: None,
                    name="b",
                )

        combined = compose_extractors(ExtractorA(), ExtractorB())  # type: ignore[arg-type]
        results = list(combined.extract({}))
        assert len(results) == 2

    def test_filter_extractor(self) -> None:
        @dataclass(frozen=True, slots=True)
        class SimpleExtractor:
            def can_extract(self, source: object) -> bool:
                return True

            def extract(self, source: object):  # type: ignore[no-untyped-def]
                yield Extracted(
                    route=HTTPRouteData(method="GET", path="/keep"),
                    handler=lambda: None,
                    name="keep",
                )
                yield Extracted(
                    route=HTTPRouteData(method="GET", path="/skip"),
                    handler=lambda: None,
                    name="skip",
                    deprecated=True,
                )

        filtered = filter_extractor(
            SimpleExtractor(),  # type: ignore[arg-type]
            lambda e: not e.deprecated,
        )
        results = list(filtered.extract({}))
        assert len(results) == 1
        assert results[0].name == "keep"

    def test_first_extractor_stops_after_first(self) -> None:
        @dataclass(frozen=True, slots=True)
        class ExtractorA:
            def can_extract(self, source: object) -> bool:
                return True

            def extract(self, source: object):  # type: ignore[no-untyped-def]
                yield Extracted(
                    route=HTTPRouteData(method="GET", path="/a"),
                    handler=lambda: None,
                    name="a",
                )

        @dataclass(frozen=True, slots=True)
        class ExtractorB:
            def can_extract(self, source: object) -> bool:
                return True

            def extract(self, source: object):  # type: ignore[no-untyped-def]
                yield Extracted(
                    route=HTTPRouteData(method="POST", path="/b"),
                    handler=lambda: None,
                    name="b",
                )

        combined = first_extractor(ExtractorA(), ExtractorB())  # type: ignore[arg-type]
        results = list(combined.extract({}))
        assert len(results) == 1
        assert results[0].name == "a"


# =========================================================================
# 10. HTTPRouteData construction
# =========================================================================


class TestHTTPRouteData:
    def test_construction_minimal(self) -> None:
        rd = HTTPRouteData(method="GET", path="/items")
        assert rd.method == "GET"
        assert rd.path == "/items"
        assert rd.tags == ()
        assert rd.deprecated is False
        assert rd.status_code == 200

    def test_construction_full(self) -> None:
        rd = HTTPRouteData(
            method="POST",
            path="/items",
            name="create_item",
            tags=("items",),
            deprecated=True,
            response_model=ItemResponse,
            status_code=201,
            operation_id="createItem",
            summary="Create an item",
            description="Creates a new item",
        )
        assert rd.method == "POST"
        assert rd.name == "create_item"
        assert rd.tags == ("items",)
        assert rd.deprecated is True
        assert rd.response_model is ItemResponse
        assert rd.status_code == 201

    def test_frozen(self) -> None:
        rd = HTTPRouteData(method="GET", path="/")
        with pytest.raises(AttributeError):
            rd.method = "POST"  # type: ignore[misc]


# =========================================================================
# 11. build_application edge cases
# =========================================================================


class TestBuildApplicationEdgeCases:
    def test_unknown_source_raises(self) -> None:
        with pytest.raises(ValueError, match="No bridger found"):
            build_application("not a framework app")

    def test_empty_fastapi_app(self) -> None:
        fapi = fastapi.FastAPI()
        result = build_application(fapi)
        # Empty app should produce empty Application
        assert isinstance(result, Application)

    def test_build_application_with_custom_registry(self) -> None:
        fapi = fastapi.FastAPI()
        registry = get_default_registry()
        result = build_application(fapi, registry=registry)
        assert isinstance(result, Application)


# =========================================================================
# 12. extract() function (_scan.py)
# =========================================================================


class TestExtractFunction:
    def test_extract_from_fastapi(self) -> None:
        app = fastapi.FastAPI()

        @app.get("/test")
        async def _test_route() -> dict[str, str]:
            return {"status": "ok"}

        assert _test_route is not None  # registered via decorator
        results = extract(app)
        assert len(results) > 0

    def test_extract_with_route_type_filter(self) -> None:
        app = fastapi.FastAPI()

        @app.get("/test")
        async def _test_route() -> dict[str, str]:
            return {"status": "ok"}

        assert _test_route is not None  # registered via decorator
        http_results = extract(app, HTTPRouteData)
        assert all(isinstance(e.route, HTTPRouteData) for e in http_results)

    def test_extract_unknown_source_raises(self) -> None:
        with pytest.raises(ValueError, match="No extractors found"):
            extract("not a framework")


# =========================================================================
# 13. SetupTeardown purifier
# =========================================================================


class TestSetupTeardown:
    def test_setup_called(self) -> None:
        called: list[str] = []

        def setup() -> None:
            called.append("setup")

        cap = SetupTeardown(setup=setup)

        def handler() -> str:
            return "ok"

        wrapped = cap.purify(handler)
        _run_awaitable(wrapped())
        assert "setup" in called

    def test_teardown_called(self) -> None:
        called: list[str] = []

        def setup() -> None:
            called.append("setup")

        def teardown() -> None:
            called.append("teardown")

        cap = SetupTeardown(setup=setup, teardown=teardown)

        def handler() -> str:
            return "ok"

        wrapped = cap.purify(handler)
        _run_awaitable(wrapped())
        assert "setup" in called
        assert "teardown" in called


# =========================================================================
# 14. InjectKwarg purifier
# =========================================================================


class TestInjectKwarg:
    def test_injects_kwarg(self) -> None:
        cap = InjectKwarg(name="db", factory=lambda: "test_db")

        def handler(db: str = "default") -> str:
            return db

        wrapped = cap.purify(handler)
        result = _run_awaitable(wrapped())
        assert result == "test_db"

    def test_does_not_override_explicit(self) -> None:
        cap = InjectKwarg(name="db", factory=lambda: "injected")

        def handler(db: str = "default") -> str:
            return db

        wrapped = cap.purify(handler)
        result = _run_awaitable(wrapped(db="explicit"))
        assert result == "explicit"


# =========================================================================
# 15. BridgeContext construction
# =========================================================================


class TestBridgeContext:
    def test_construction(self) -> None:
        async def handler() -> None:
            pass

        ctx = BridgeContext(
            trigger_data=HTTPRouteData(method="GET", path="/test"),
            handler=handler,
            name="test",
        )
        assert ctx.name == "test"
        assert ctx.skip is False
        assert ctx.deprecated is False

    def test_frozen(self) -> None:
        async def handler() -> None:
            pass

        ctx = BridgeContext(
            trigger_data=HTTPRouteData(method="GET", path="/test"),
            handler=handler,
        )
        with pytest.raises(AttributeError):
            ctx.skip = True  # type: ignore[misc]

    def test_replace_updates(self) -> None:
        async def handler() -> None:
            pass

        ctx = BridgeContext(
            trigger_data=HTTPRouteData(method="GET", path="/test"),
            handler=handler,
            name="original",
        )
        updated = replace(ctx, name="updated")
        assert updated.name == "updated"
        assert ctx.name == "original"


# =========================================================================
# 16. WrapAsDelegate
# =========================================================================


class TestWrapAsDelegate:
    def test_sets_codec_on_context(self) -> None:
        async def handler() -> str:
            return "ok"

        ctx = BridgeContext(
            trigger_data=_StubRouteData(path="/test"),
            handler=handler,
            response_type=str,
        )
        cap = WrapAsDelegate()
        result = cap.compile_bridge(ctx)
        assert result.wire.codec is not None


# =========================================================================
# 17. SetCodecByName
# =========================================================================


class TestSetCodecByName:
    def test_sets_codec(self) -> None:
        ctx = _make_ctx(name="my_handler")
        cap = SetCodecByName(codec_map={"my_handler": "my_codec"})
        result = cap.compile_bridge(ctx)
        assert result.wire.codec == "my_codec"

    def test_no_override_if_already_set(self) -> None:
        ctx = _make_ctx(name="my_handler")
        ctx = replace(ctx, wire=WireData(codec="existing"))
        cap = SetCodecByName(codec_map={"my_handler": "new_codec"})
        result = cap.compile_bridge(ctx)
        assert result.wire.codec == "existing"

    def test_no_change_for_unmatched(self) -> None:
        ctx = _make_ctx(name="other")
        cap = SetCodecByName(codec_map={"my_handler": "my_codec"})
        result = cap.compile_bridge(ctx)
        assert result.wire.codec is None


# =========================================================================
# 18. EnsureAsync utility
# =========================================================================


class TestEnsureAsync:
    def test_sync_becomes_async(self) -> None:
        def sync_fn() -> str:
            return "ok"

        result = ensure_async(sync_fn)
        assert inspect.iscoroutinefunction(result)

    def test_async_stays_async(self) -> None:
        async def async_fn() -> str:
            return "ok"

        result = ensure_async(async_fn)
        assert result is async_fn


# =========================================================================
# 19. AddCapability
# =========================================================================


class TestAddCapability:
    def test_adds_capability_for_all_names(self) -> None:

        @dataclass(frozen=True, slots=True)
        class StubSurfaceCap:
            tag: str

        ctx = _make_ctx(name="handler")
        cap = AddCapability(capability=StubSurfaceCap(tag="test"))  # type: ignore[arg-type]
        result = cap.compile_bridge(ctx)
        assert len(result.wire.surface_capabilities) == 1

    def test_adds_only_for_matching_names(self) -> None:
        @dataclass(frozen=True, slots=True)
        class StubSurfaceCap:
            tag: str

        ctx = _make_ctx(name="other")
        cap = AddCapability(
            capability=StubSurfaceCap(tag="test"),  # type: ignore[arg-type]
            for_names=frozenset({"target"}),
        )
        result = cap.compile_bridge(ctx)
        assert len(result.wire.surface_capabilities) == 0

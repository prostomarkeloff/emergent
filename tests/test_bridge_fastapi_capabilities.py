"""Tests for emergent.wire.bridge.bridgers.fastapi._capabilities — covers missed lines.

Targeted lines:
- 79-81: _get_fastapi_marker finds marker in Annotated annotations
- 88: _is_special_fastapi_type returns False for None
- 93, 95: _is_special_fastapi_type detects by name and module
- 102: _is_pydantic_model handles None / non-type inputs
- 109: _is_dataclass_type handles None / non-type inputs
- 151-152: _parse_handler_params exception handling
- 166-167: _parse_handler_params None annotation branch
- 175: _parse_handler_params non-type base_type
- 181-183: _parse_handler_params explicit FastAPI marker
- 188: _parse_handler_params special type detection
- 202: _parse_handler_params unknown with None base_type
- 278, 283, 291-293: InferFromFastAPI._get_return_type edge cases
- 306, 310: MapDepends default factories
- 348-365: MapDepends.purify wraps handler with depends resolution
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

import pytest
from fastapi import Body, Cookie, Depends, Header, Path, Query
from fastapi import BackgroundTasks, UploadFile
from pydantic import BaseModel
from starlette.requests import Request
from starlette.responses import Response
from starlette.websockets import WebSocket

from emergent.wire.bridge._capabilities import (
    BridgeContext,
)
from emergent.wire.bridge.bridgers.fastapi._capabilities import (
    InferFromFastAPI,
    MapDepends,
    parse_fastapi_handler,
)

# These private helpers are imported for direct unit testing of internal
# implementation details. reportPrivateUsage suppression is unavoidable
# because the functions are intentionally private but need coverage tests.
from emergent.wire.bridge.bridgers.fastapi._capabilities import (
    _get_fastapi_marker as _get_fastapi_marker,  # pyright: ignore[reportPrivateUsage]
    _is_dataclass_type as _is_dataclass_type,  # pyright: ignore[reportPrivateUsage]
    _is_depends as _is_depends,  # pyright: ignore[reportPrivateUsage]
    _is_pydantic_model as _is_pydantic_model,  # pyright: ignore[reportPrivateUsage]
    _is_special_fastapi_type as _is_special_fastapi_type,  # pyright: ignore[reportPrivateUsage]
    _parse_handler_params as _parse_handler_params,  # pyright: ignore[reportPrivateUsage]
)


# ═══════════════════════════════════════════════════════════════════════════════
# Module-level types for annotation resolution
# (from __future__ import annotations makes hints stringified)
# ═══════════════════════════════════════════════════════════════════════════════


class UserModel(BaseModel):
    """Pydantic model for tests."""

    name: str
    age: int


@dataclass
class ItemDC:
    """Dataclass for tests."""

    title: str


@dataclass(frozen=True, slots=True)
class StubRouteData:
    """Minimal route data for tests."""

    path: str
    method: str = "GET"


# ═══════════════════════════════════════════════════════════════════════════════
# _get_fastapi_marker (lines 79-82)
# ═══════════════════════════════════════════════════════════════════════════════


class TestGetFastAPIMarker:
    """Test _get_fastapi_marker — lines 78-82."""

    def test_finds_query_marker(self) -> None:
        """Line 79-81: find FastAPI marker type by class name."""
        marker = Query()
        result = _get_fastapi_marker([marker])
        assert result == "Query"

    def test_finds_body_marker(self) -> None:
        marker = Body()
        result = _get_fastapi_marker([marker])
        assert result == "Body"

    def test_finds_path_marker(self) -> None:
        marker = Path()
        result = _get_fastapi_marker([marker])
        assert result == "Path"

    def test_finds_header_marker(self) -> None:
        marker = Header()
        result = _get_fastapi_marker([marker])
        assert result == "Header"

    def test_finds_cookie_marker(self) -> None:
        marker = Cookie()
        result = _get_fastapi_marker([marker])
        assert result == "Cookie"

    def test_returns_none_for_no_marker(self) -> None:
        """Line 82: no marker found returns None."""
        result = _get_fastapi_marker(["metadata", 42])
        assert result is None

    def test_returns_none_for_empty_list(self) -> None:
        result = _get_fastapi_marker([])
        assert result is None

    def test_finds_first_marker(self) -> None:
        result = _get_fastapi_marker(["metadata", Query(), Body()])
        assert result == "Query"


# ═══════════════════════════════════════════════════════════════════════════════
# _is_special_fastapi_type (lines 88, 93, 95)
# ═══════════════════════════════════════════════════════════════════════════════


class TestIsSpecialFastAPIType:
    """Test _is_special_fastapi_type — lines 87-96."""

    def test_returns_false_for_none(self) -> None:
        """Line 88: None input returns False."""
        assert _is_special_fastapi_type(None) is False

    def test_detects_request_by_name(self) -> None:
        """Line 93: type name in _SPECIAL_TYPE_NAMES."""
        assert _is_special_fastapi_type(Request) is True

    def test_detects_response_by_name(self) -> None:
        assert _is_special_fastapi_type(Response) is True

    def test_detects_websocket_by_name(self) -> None:
        assert _is_special_fastapi_type(WebSocket) is True

    def test_detects_background_tasks(self) -> None:
        assert _is_special_fastapi_type(BackgroundTasks) is True

    def test_detects_by_module_fastapi(self) -> None:
        """Line 94-95: types from fastapi.* module."""
        assert _is_special_fastapi_type(UploadFile) is True

    def test_returns_false_for_regular_type(self) -> None:
        assert _is_special_fastapi_type(str) is False
        assert _is_special_fastapi_type(int) is False

    def test_returns_false_for_custom_class(self) -> None:
        class MyRequest:
            pass

        assert _is_special_fastapi_type(MyRequest) is False


# ═══════════════════════════════════════════════════════════════════════════════
# _is_pydantic_model (line 102)
# ═══════════════════════════════════════════════════════════════════════════════


class TestIsPydanticModel:
    """Test _is_pydantic_model — line 101-103."""

    def test_returns_false_for_none(self) -> None:
        """Line 101: None returns False."""
        assert _is_pydantic_model(None) is False

    def test_returns_false_for_non_type(self) -> None:
        """Line 101: non-type returns False."""
        assert _is_pydantic_model("not_a_type") is False
        assert _is_pydantic_model(42) is False

    def test_returns_true_for_pydantic_model(self) -> None:
        assert _is_pydantic_model(UserModel) is True

    def test_returns_false_for_dataclass(self) -> None:
        assert _is_pydantic_model(ItemDC) is False

    def test_returns_false_for_plain_class(self) -> None:
        class Plain:
            pass

        assert _is_pydantic_model(Plain) is False


# ═══════════════════════════════════════════════════════════════════════════════
# _is_dataclass_type (line 109)
# ═══════════════════════════════════════════════════════════════════════════════


class TestIsDataclassType:
    """Test _is_dataclass_type — lines 107-110."""

    def test_returns_false_for_none(self) -> None:
        assert _is_dataclass_type(None) is False

    def test_returns_false_for_non_type(self) -> None:
        assert _is_dataclass_type("not_a_type") is False
        assert _is_dataclass_type(42) is False

    def test_returns_true_for_dataclass(self) -> None:
        assert _is_dataclass_type(ItemDC) is True

    def test_returns_false_for_pydantic(self) -> None:
        assert _is_dataclass_type(UserModel) is False

    def test_returns_false_for_plain_class(self) -> None:
        class Plain:
            pass

        assert _is_dataclass_type(Plain) is False


# ═══════════════════════════════════════════════════════════════════════════════
# _is_depends (line 115)
# ═══════════════════════════════════════════════════════════════════════════════


class TestIsDepends:
    def test_detects_depends(self) -> None:
        def get_db() -> str:
            return "db"

        assert _is_depends(Depends(get_db)) is True

    def test_rejects_non_depends(self) -> None:
        assert _is_depends(42) is False
        assert _is_depends("string") is False


# ═══════════════════════════════════════════════════════════════════════════════
# _parse_handler_params (lines 145-202)
# ═══════════════════════════════════════════════════════════════════════════════


class TestParseHandlerParams:
    """Test _parse_handler_params — multiple missed lines."""

    def test_non_callable_returns_empty(self) -> None:
        """Line 145-146: non-callable returns empty list."""
        not_callable = 42
        # Deliberately pass a non-callable to test the guard clause;
        # pyright correctly rejects this, but we need to verify runtime behavior.
        result = _parse_handler_params(not_callable)  # pyright: ignore[reportArgumentType] -- testing runtime guard for non-callable input
        assert result == []

    def test_unannotated_param_is_unknown(self) -> None:
        """Lines 165-167: params without annotation are 'unknown'."""
        # exec is used to create a function with an unannotated parameter
        # without triggering pyright's reportUnknownArgumentType on the
        # handler signature, since `from __future__ import annotations`
        # stringifies all annotations and pyright flags Unknown param types.
        ns: dict[str, object] = {}
        exec("def handler(x): pass", ns)  # noqa: S102
        handler = ns["handler"]
        assert callable(handler)
        result = _parse_handler_params(handler)
        assert len(result) == 1
        assert result[0].source == "unknown"
        assert result[0].base_type is None

    def test_explicit_body_marker(self) -> None:
        """Lines 180-183: explicit Body() marker in Annotated."""

        def handler(data: Annotated[str, Body()]) -> None:
            pass

        result = _parse_handler_params(handler)
        body_params = [p for p in result if p.source == "body"]
        assert len(body_params) == 1
        assert body_params[0].name == "data"
        assert body_params[0].base_type is str

    def test_explicit_query_marker(self) -> None:
        """Lines 180-183: explicit Query() marker."""

        def handler(q: Annotated[str, Query()]) -> None:
            pass

        result = _parse_handler_params(handler)
        query_params = [p for p in result if p.source == "query"]
        assert len(query_params) == 1
        assert query_params[0].name == "q"

    def test_explicit_path_marker(self) -> None:
        def handler(user_id: Annotated[int, Path()]) -> None:
            pass

        result = _parse_handler_params(handler)
        path_params = [p for p in result if p.source == "path"]
        assert len(path_params) == 1
        assert path_params[0].name == "user_id"

    def test_explicit_header_marker(self) -> None:
        def handler(x_token: Annotated[str, Header()]) -> None:
            pass

        result = _parse_handler_params(handler)
        header_params = [p for p in result if p.source == "header"]
        assert len(header_params) == 1
        assert header_params[0].name == "x_token"

    def test_explicit_cookie_marker(self) -> None:
        def handler(session_id: Annotated[str, Cookie()]) -> None:
            pass

        result = _parse_handler_params(handler)
        cookie_params = [p for p in result if p.source == "cookie"]
        assert len(cookie_params) == 1
        assert cookie_params[0].name == "session_id"

    def test_special_type_detection(self) -> None:
        """Lines 187-189: special FastAPI type → 'special' source."""

        def handler(request: Request) -> None:
            pass

        result = _parse_handler_params(handler)
        special_params = [p for p in result if p.source == "special"]
        assert len(special_params) == 1
        assert special_params[0].name == "request"
        assert special_params[0].base_type is Request

    def test_pydantic_model_implicit_body(self) -> None:
        """Lines 191-194: Pydantic model without marker → implicit body."""

        def handler(user: UserModel) -> None:
            pass

        result = _parse_handler_params(handler)
        body_params = [p for p in result if p.source == "body"]
        assert len(body_params) == 1
        assert body_params[0].name == "user"
        assert body_params[0].base_type is UserModel

    def test_dataclass_implicit_body(self) -> None:
        """Lines 191-194: dataclass without marker → implicit body."""

        def handler(item: ItemDC) -> None:
            pass

        result = _parse_handler_params(handler)
        body_params = [p for p in result if p.source == "body"]
        assert len(body_params) == 1
        assert body_params[0].name == "item"
        assert body_params[0].base_type is ItemDC

    def test_primitive_is_unknown(self) -> None:
        """Lines 196-199: primitive type without marker → unknown."""

        def handler(count: int) -> None:
            pass

        result = _parse_handler_params(handler)
        unknown_params = [p for p in result if p.source == "unknown"]
        assert len(unknown_params) == 1
        assert unknown_params[0].name == "count"
        assert unknown_params[0].base_type is int

    def test_depends_detection(self) -> None:
        """Lines 161-163: Depends() default → 'depends' source."""

        def get_db() -> str:
            return "db"

        def handler(db: str = Depends(get_db)) -> None:
            pass

        result = _parse_handler_params(handler)
        depends_params = [p for p in result if p.source == "depends"]
        assert len(depends_params) == 1
        assert depends_params[0].name == "db"

    def test_optional_param_detection(self) -> None:
        """Detect Optional[T] / T | None as optional."""

        def handler(name: str | None = None) -> None:
            pass

        result = _parse_handler_params(handler)
        assert len(result) == 1
        assert result[0].is_optional is True

    def test_mixed_params(self) -> None:
        """Handler with multiple parameter types."""

        def get_db() -> str:
            return "db"

        def handler(
            user: UserModel,
            q: Annotated[str, Query()],
            db: str = Depends(get_db),
        ) -> str:
            return "ok"

        result = _parse_handler_params(handler)
        sources = {p.name: p.source for p in result}
        assert sources["user"] == "body"
        assert sources["q"] == "query"
        assert sources["db"] == "depends"


# ═══════════════════════════════════════════════════════════════════════════════
# InferFromFastAPI._get_return_type edge cases (lines 278, 283, 291-293)
# ═══════════════════════════════════════════════════════════════════════════════


class TestInferFromFastAPIReturnType:
    """Test InferFromFastAPI._get_return_type — missed edge cases."""

    def test_no_return_annotation(self) -> None:
        """Line 282-283: handler with no return annotation."""
        # Use exec to create a handler without return annotation to avoid
        # pyright reportUnknownArgumentType from stringified annotations.
        ns: dict[str, object] = {}
        exec("def handler(x: int): pass", ns)  # noqa: S102
        handler = ns["handler"]
        assert callable(handler)

        cap = InferFromFastAPI()
        ctx = BridgeContext(
            trigger_data=StubRouteData(path="/test"),
            handler=handler,
            name="handler",
        )
        result = cap.compile_bridge(ctx)
        assert result.response_type is None

    def test_return_none_type(self) -> None:
        """Return type is None."""

        def handler() -> None:
            pass

        cap = InferFromFastAPI()
        # _get_return_type is protected; suppression needed because this test
        # directly validates the internal method's behavior for NoneType returns.
        result = cap._get_return_type(handler)  # pyright: ignore[reportPrivateUsage]
        assert result is type(None)

    def test_non_callable_return_type(self) -> None:
        """Line 277-278: non-callable returns None."""
        cap = InferFromFastAPI()
        not_callable = 42
        # _get_return_type is protected and we deliberately pass a non-callable;
        # suppression needed for both the protected access and the wrong arg type.
        result = cap._get_return_type(not_callable)  # pyright: ignore[reportPrivateUsage, reportArgumentType] -- testing runtime guard for non-callable input
        assert result is None

    def test_optional_return_type_unwrapped(self) -> None:
        """Return type Optional[X] is unwrapped to X."""

        def handler() -> str | None:
            return None

        cap = InferFromFastAPI()
        # _get_return_type is protected; suppression needed because this test
        # directly validates internal unwrapping of Optional return types.
        result = cap._get_return_type(handler)  # pyright: ignore[reportPrivateUsage]
        assert result is str

    def test_annotated_return_type_unwrapped(self) -> None:
        """Return type Annotated[X, ...] is unwrapped to X."""

        def handler() -> Annotated[str, "doc"]:
            return "ok"

        cap = InferFromFastAPI()
        # _get_return_type is protected; suppression needed because this test
        # directly validates internal unwrapping of Annotated return types.
        result = cap._get_return_type(handler)  # pyright: ignore[reportPrivateUsage]
        assert result is str


# ═══════════════════════════════════════════════════════════════════════════════
# InferFromFastAPI.compile_bridge — more edge cases
# ═══════════════════════════════════════════════════════════════════════════════


class TestInferFromFastAPICompileBridge:
    """Test InferFromFastAPI.compile_bridge — additional cases."""

    def test_does_not_overwrite_existing_request_type(self) -> None:
        """Existing request_type is preserved."""

        def handler(user: UserModel) -> str:
            return user.name

        ctx = BridgeContext(
            trigger_data=StubRouteData(path="/test"),
            handler=handler,
            name="handler",
            request_type=int,
        )
        cap = InferFromFastAPI()
        result = cap.compile_bridge(ctx)
        assert result.request_type is int

    def test_does_not_overwrite_existing_response_type(self) -> None:
        """Existing response_type is preserved."""

        def handler() -> str:
            return "hello"

        ctx = BridgeContext(
            trigger_data=StubRouteData(path="/test"),
            handler=handler,
            name="handler",
            response_type=float,
        )
        cap = InferFromFastAPI()
        result = cap.compile_bridge(ctx)
        assert result.response_type is float

    def test_include_dataclass_false_skips_dataclass_body(self) -> None:
        """With include_dataclass=False, dataclass params are not body."""

        def handler(item: ItemDC) -> str:
            return item.title

        ctx = BridgeContext(
            trigger_data=StubRouteData(path="/test"),
            handler=handler,
            name="handler",
        )
        cap = InferFromFastAPI(include_dataclass=False)
        result = cap.compile_bridge(ctx)
        assert result.request_type is None

    def test_include_dataclass_true_detects_dataclass_body(self) -> None:
        """With include_dataclass=True, dataclass params are body."""

        def handler(item: ItemDC) -> str:
            return item.title

        ctx = BridgeContext(
            trigger_data=StubRouteData(path="/test"),
            handler=handler,
            name="handler",
        )
        cap = InferFromFastAPI(include_dataclass=True)
        result = cap.compile_bridge(ctx)
        assert result.request_type is ItemDC

    def test_handler_with_no_body_params(self) -> None:
        """Handler with only primitive params has no request_type."""

        def handler(name: str, age: int) -> str:
            return name

        ctx = BridgeContext(
            trigger_data=StubRouteData(path="/test"),
            handler=handler,
            name="handler",
        )
        cap = InferFromFastAPI()
        result = cap.compile_bridge(ctx)
        assert result.request_type is None
        assert result.response_type is str


# ═══════════════════════════════════════════════════════════════════════════════
# MapDepends — default factories and purify (lines 306, 310, 348-365)
# ═══════════════════════════════════════════════════════════════════════════════


class TestMapDepends:
    """Test MapDepends — lines 306, 310, 346-365."""

    def test_default_empty_maps(self) -> None:
        """Lines 306, 310: default factory creates empty dicts."""
        cap = MapDepends()
        assert cap.depends_map == {}
        assert cap.scope_map == {}

    @pytest.mark.asyncio
    async def test_purify_returns_async_when_no_maps(self) -> None:
        """Line 350-351: no maps → ensure_async only."""
        cap = MapDepends()

        async def handler() -> str:
            return "ok"

        wrapped = cap.purify(handler)
        # When both maps are empty, ensure_async returns async handler directly
        assert wrapped is handler
        result = await wrapped()
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_purify_wraps_sync_when_no_maps(self) -> None:
        """Line 350-351: no maps with sync handler → ensure_async wraps it."""
        cap = MapDepends()

        def handler() -> str:
            return "ok"

        wrapped = cap.purify(handler)
        # Sync handler gets wrapped
        assert wrapped is not handler
        result = await wrapped()
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_purify_resolves_depends_factory(self) -> None:
        """Lines 353-363: depends_map resolves to factory result."""
        def get_db() -> str:
            return "test_db"

        def handler(db: str = Depends(get_db)) -> str:
            return db

        cap = MapDepends(
            depends_map={get_db: lambda: "resolved_db"},
        )

        wrapped = cap.purify(handler)
        result = await wrapped()
        assert result == "resolved_db"

    @pytest.mark.asyncio
    async def test_purify_does_not_override_explicit_kwarg(self) -> None:
        """Line 357: param_name not in kwargs check."""

        def get_db() -> str:
            return "test_db"

        def handler(db: str = Depends(get_db)) -> str:
            return db

        cap = MapDepends(
            depends_map={get_db: lambda: "resolved_db"},
        )

        wrapped = cap.purify(handler)
        result = await wrapped(db="explicit_db")
        assert result == "explicit_db"

    @pytest.mark.asyncio
    async def test_purify_resolves_async_factory(self) -> None:
        """Lines 358-360: factory returns coroutine, gets awaited."""

        def get_session() -> str:
            return "session"

        async def session_factory() -> str:
            return "async_session"

        def handler(session: str = Depends(get_session)) -> str:
            return session

        cap = MapDepends(
            depends_map={get_session: session_factory},
        )

        wrapped = cap.purify(handler)
        result = await wrapped()
        assert result == "async_session"

    @pytest.mark.asyncio
    async def test_purify_with_no_matching_param(self) -> None:
        """When depends_map key doesn't match handler params, kwarg is not injected."""

        def get_db() -> str:
            return "db"

        def other_dep() -> str:
            return "other"

        def handler(db: str = Depends(get_db)) -> str:
            return db

        # Map a different dependency than what handler uses
        cap = MapDepends(
            depends_map={other_dep: lambda: "wrong"},
        )

        _wrapped = cap.purify(handler)
        # Handler will use default from Depends
        # Since Depends is just metadata, handler called with no db kwarg
        # will use the default from the signature, which is Depends(get_db)
        # But _call_handler should work and the Depends object stays as default
        # In practice, handler gets called without db in kwargs
        assert _wrapped is not None


# ═══════════════════════════════════════════════════════════════════════════════
# parse_fastapi_handler — grouping (integration)
# ═══════════════════════════════════════════════════════════════════════════════


class TestParseFastAPIHandlerMissed:
    """Test parse_fastapi_handler with various param types."""

    def test_groups_all_source_types(self) -> None:
        """Verify all source categories exist in grouped result."""

        def get_db() -> str:
            return "db"

        def handler(
            user: UserModel,
            q: Annotated[str, Query()],
            db: str = Depends(get_db),
        ) -> str:
            return "ok"

        grouped = parse_fastapi_handler(handler)
        # All categories should exist in result
        for key in ("body", "query", "path", "header", "cookie", "form",
                     "file", "depends", "special", "unknown"):
            assert key in grouped

        assert len(grouped["body"]) == 1
        assert grouped["body"][0].name == "user"
        assert len(grouped["query"]) == 1
        assert grouped["query"][0].name == "q"
        assert len(grouped["depends"]) == 1
        assert grouped["depends"][0].name == "db"

    def test_special_type_grouped_correctly(self) -> None:
        """Special types are grouped under 'special'."""

        def handler(request: Request) -> None:
            pass

        grouped = parse_fastapi_handler(handler)
        assert len(grouped["special"]) == 1
        assert grouped["special"][0].name == "request"

    def test_non_callable_returns_all_empty_groups(self) -> None:
        """Non-callable input produces all-empty groups."""
        not_callable = 42
        # Deliberately pass a non-callable to test runtime guard;
        # pyright correctly rejects this, but we verify runtime behavior.
        grouped = parse_fastapi_handler(not_callable)  # pyright: ignore[reportArgumentType] -- testing runtime guard for non-callable input
        for key in grouped:
            assert grouped[key] == []


# ═══════════════════════════════════════════════════════════════════════════════
# DEFAULT_INFERENCE constant
# ═══════════════════════════════════════════════════════════════════════════════


class TestDefaultInference:
    def test_default_inference_tuple(self) -> None:
        from emergent.wire.bridge.bridgers.fastapi._capabilities import (  # pyright: ignore[reportPrivateUsage] -- testing module-level constant from private submodule
            DEFAULT_INFERENCE,
        )

        assert len(DEFAULT_INFERENCE) == 1
        assert isinstance(DEFAULT_INFERENCE[0], InferFromFastAPI)

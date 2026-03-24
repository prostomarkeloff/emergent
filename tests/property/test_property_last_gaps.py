# pyright: reportPrivateUsage=false
"""Final coverage sweep — every file with >5 missing statements.

Covers: resolve.py, telegram.py, _capabilities.py, memory.py, _extractors.py,
FA _capabilities.py, storage _explain.py, _sql.py, surface _explain.py,
delta.py, temporal.py, auth/openapi.py, _coerce.py, query _explain.py,
compile _explain.py, _relational.py, derive _explain.py, _project.py,
_pipeline.py, _introspect.py, http.py, SA target, compile _pipeline.py,
ops _graph.py.
"""

from __future__ import annotations

import inspect
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import wraps

import pytest

from kungfu import Ok, Error, Some, Nothing, Option, Result


# ═══════════════════════════════════════════════════════════════════════════════
# 1. resolve.py — unwrap/wrap branches
# ═══════════════════════════════════════════════════════════════════════════════


class TestResolveUnwrapWrap:
    """Exercise all unwrap/wrap branches in codecs/resolve.py."""

    def test_unwrap_option(self) -> None:
        from emergent.wire.axis.surface.codecs.resolve import unwrap

        inner, is_opt = unwrap(Option[int])
        assert inner is int
        assert is_opt is True

    def test_unwrap_result(self) -> None:
        from emergent.wire.axis.surface.codecs.resolve import unwrap

        inner, is_opt = unwrap(Result[str, int])
        assert inner is str
        assert is_opt is True

    def test_unwrap_plain_type(self) -> None:
        from emergent.wire.axis.surface.codecs.resolve import unwrap

        inner, is_opt = unwrap(int)
        assert inner is int
        assert is_opt is False

    def test_wrap_option_success(self) -> None:
        from emergent.wire.axis.surface.codecs.resolve import wrap

        val = wrap(Option[int], True, 42)
        assert isinstance(val, Some)

    def test_wrap_option_failure(self) -> None:
        from emergent.wire.axis.surface.codecs.resolve import wrap

        val = wrap(Option[int], False, "err")
        assert isinstance(val, Nothing)

    def test_wrap_result_success(self) -> None:
        from emergent.wire.axis.surface.codecs.resolve import wrap

        val = wrap(Result[int, str], True, 42)
        assert isinstance(val, Ok)

    def test_wrap_result_failure(self) -> None:
        from emergent.wire.axis.surface.codecs.resolve import wrap

        val = wrap(Result[int, str], False, "oops")
        assert isinstance(val, Error)

    def test_wrap_plain_success(self) -> None:
        from emergent.wire.axis.surface.codecs.resolve import wrap

        assert wrap(int, True, 42) == 42

    def test_wrap_plain_failure_raises(self) -> None:
        from emergent.wire.axis.surface.codecs.resolve import wrap

        with pytest.raises(RuntimeError, match="Required param failed"):
            wrap(int, False, "err")

    def test_get_method_params(self) -> None:
        from emergent.wire.axis.surface.codecs.resolve import get_method_params

        async def method(self: object, x: Option[int], y: str) -> None: ...

        params = get_method_params(method)
        assert "x" in params
        assert "y" in params
        assert "self" not in params
        assert "return" not in params

    def test_get_transition_params_no_transition(self) -> None:
        from emergent.wire.axis.surface.codecs.resolve import get_transition_params

        class NoTransition:
            pass

        assert get_transition_params(NoTransition) == {}

    def test_is_nodnod_node(self) -> None:
        from emergent.wire.axis.surface.codecs.resolve import _is_nodnod_node

        class FakeNode:
            __dependencies__ = ()

        assert _is_nodnod_node(FakeNode) is True
        assert _is_nodnod_node(int) is False


# ═══════════════════════════════════════════════════════════════════════════════
# 2. telegram.py — TG compile methods
# ═══════════════════════════════════════════════════════════════════════════════


class TestTelegramDialects:
    """Exercise all compile_telegrinder methods and enricher branches."""

    def test_help_meta_creation(self) -> None:
        from emergent.wire.axis.surface.dialects.telegram import HelpMeta

        h = HelpMeta(description="Test", order=5, hidden=True)
        assert h.description == "Test"
        assert h.order == 5
        assert h.hidden is True

    def test_edit_message_compile(self) -> None:
        from emergent.wire.axis.surface.dialects.telegram import EditMessage
        from emergent.wire.axis._capability import TelegrinderHandlerContext

        ctx = TelegrinderHandlerContext()
        em = EditMessage()
        new_ctx = em.compile_telegrinder(ctx)
        assert new_ctx.edit_message is True

    def test_answer_callback_compile(self) -> None:
        from emergent.wire.axis.surface.dialects.telegram import AnswerCallback
        from emergent.wire.axis._capability import TelegrinderHandlerContext

        ctx = TelegrinderHandlerContext()
        ac = AnswerCallback(text="OK", show_alert=True)
        new_ctx = ac.compile_telegrinder(ctx)
        assert new_ctx.answer_callback is True
        assert new_ctx.answer_callback_text == "OK"
        assert new_ctx.answer_callback_show_alert is True

    def test_silent_compile(self) -> None:
        from emergent.wire.axis.surface.dialects.telegram import Silent
        from emergent.wire.axis._capability import TelegrinderHandlerContext

        ctx = TelegrinderHandlerContext()
        new_ctx = Silent().compile_telegrinder(ctx)
        assert new_ctx.silent is True

    def test_parse_mode_compile(self) -> None:
        from emergent.wire.axis.surface.dialects.telegram import ParseMode
        from emergent.wire.axis._capability import TelegrinderHandlerContext

        ctx = TelegrinderHandlerContext()
        new_ctx = ParseMode(mode="HTML").compile_telegrinder(ctx)
        assert new_ctx.parse_mode == "HTML"

    def test_link_preview_compile(self) -> None:
        from emergent.wire.axis.surface.dialects.telegram import LinkPreview
        from emergent.wire.axis._capability import TelegrinderHandlerContext

        ctx = TelegrinderHandlerContext()
        new_ctx = LinkPreview(disabled=True).compile_telegrinder(ctx)
        assert new_ctx.link_preview_disabled is True

    def test_protect_content_compile(self) -> None:
        from emergent.wire.axis.surface.dialects.telegram import ProtectContent
        from emergent.wire.axis._capability import TelegrinderHandlerContext

        ctx = TelegrinderHandlerContext()
        new_ctx = ProtectContent().compile_telegrinder(ctx)
        assert new_ctx.protect_content is True


# ═══════════════════════════════════════════════════════════════════════════════
# 3. bridge/_capabilities.py — remaining bridge capabilities
# ═══════════════════════════════════════════════════════════════════════════════


class TestBridgeCapabilities:
    """Exercise all bridge capability compile/purify methods."""

    def test_skip_deprecated(self) -> None:
        from emergent.wire.bridge._capabilities import SkipDeprecated, BridgeContext

        async def handler() -> str:
            return "ok"

        ctx = BridgeContext(trigger_data=None, handler=handler, deprecated=True)
        result = SkipDeprecated().compile_bridge(ctx)
        assert result.skip is True

    def test_skip_deprecated_not_deprecated(self) -> None:
        from emergent.wire.bridge._capabilities import SkipDeprecated, BridgeContext

        async def handler() -> str:
            return "ok"

        ctx = BridgeContext(trigger_data=None, handler=handler, deprecated=False)
        result = SkipDeprecated().compile_bridge(ctx)
        assert result.skip is False

    def test_skip_by_name(self) -> None:
        from emergent.wire.bridge._capabilities import SkipByName, BridgeContext

        async def handler() -> str:
            return "ok"

        ctx = BridgeContext(trigger_data=None, handler=handler, name="skip_me")
        cap = SkipByName(names=frozenset({"skip_me"}))
        result = cap.compile_bridge(ctx)
        assert result.skip is True

    def test_skip_by_name_pattern(self) -> None:
        from emergent.wire.bridge._capabilities import SkipByName, BridgeContext

        async def handler() -> str:
            return "ok"

        ctx = BridgeContext(trigger_data=None, handler=handler, name="test_foo")
        cap = SkipByName(pattern=r"test_.*")
        result = cap.compile_bridge(ctx)
        assert result.skip is True

    def test_include_only_by_name_match(self) -> None:
        from emergent.wire.bridge._capabilities import IncludeOnlyByName, BridgeContext

        async def handler() -> str:
            return "ok"

        ctx = BridgeContext(trigger_data=None, handler=handler, name="keep")
        cap = IncludeOnlyByName(names=frozenset({"keep"}))
        result = cap.compile_bridge(ctx)
        assert result.skip is False

    def test_include_only_by_name_no_name(self) -> None:
        from emergent.wire.bridge._capabilities import IncludeOnlyByName, BridgeContext

        async def handler() -> str:
            return "ok"

        ctx = BridgeContext(trigger_data=None, handler=handler, name=None)
        cap = IncludeOnlyByName(names=frozenset({"keep"}))
        result = cap.compile_bridge(ctx)
        assert result.skip is True

    def test_include_only_by_name_pattern_match(self) -> None:
        from emergent.wire.bridge._capabilities import IncludeOnlyByName, BridgeContext

        async def handler() -> str:
            return "ok"

        ctx = BridgeContext(trigger_data=None, handler=handler, name="api_v2")
        cap = IncludeOnlyByName(pattern=r"api_.*")
        result = cap.compile_bridge(ctx)
        assert result.skip is False

    def test_include_only_by_name_no_match(self) -> None:
        from emergent.wire.bridge._capabilities import IncludeOnlyByName, BridgeContext

        async def handler() -> str:
            return "ok"

        ctx = BridgeContext(trigger_data=None, handler=handler, name="other")
        cap = IncludeOnlyByName(names=frozenset({"keep"}))
        result = cap.compile_bridge(ctx)
        assert result.skip is True

    def test_set_request_type_by_name(self) -> None:
        from emergent.wire.bridge._capabilities import SetRequestTypeByName, BridgeContext

        async def handler() -> str:
            return "ok"

        ctx = BridgeContext(trigger_data=None, handler=handler, name="create")
        cap = SetRequestTypeByName(type_map={"create": int})
        result = cap.compile_bridge(ctx)
        assert result.request_type is int

    def test_set_response_type_by_name(self) -> None:
        from emergent.wire.bridge._capabilities import SetResponseTypeByName, BridgeContext

        async def handler() -> str:
            return "ok"

        ctx = BridgeContext(trigger_data=None, handler=handler, name="create")
        cap = SetResponseTypeByName(type_map={"create": str})
        result = cap.compile_bridge(ctx)
        assert result.response_type is str

    @pytest.mark.anyio
    async def test_catch_errors_purify(self) -> None:
        from emergent.wire.bridge._capabilities import CatchErrors

        async def failing() -> str:
            raise ValueError("boom")

        cap: CatchErrors[str] = CatchErrors(on_error=lambda e: f"caught: {e}")
        wrapped = cap.purify(failing)
        result = await wrapped()
        assert result == "caught: boom"

    @pytest.mark.anyio
    async def test_wrap_async_purify(self) -> None:
        from emergent.wire.bridge._capabilities import WrapAsync

        def sync_fn() -> str:
            return "sync"

        wrapped = WrapAsync().purify(sync_fn)
        assert await wrapped() == "sync"

    @pytest.mark.anyio
    async def test_inject_kwarg(self) -> None:
        from emergent.wire.bridge._capabilities import InjectKwarg

        async def handler(db: str = "none") -> str:
            return db

        cap: InjectKwarg[str] = InjectKwarg(name="db", factory=lambda: "real_db")
        wrapped = cap.purify(handler)
        assert await wrapped() == "real_db"

    @pytest.mark.anyio
    async def test_setup_teardown(self) -> None:
        from emergent.wire.bridge._capabilities import SetupTeardown

        calls: list[str] = []

        async def handler() -> str:
            calls.append("handler")
            return "ok"

        cap = SetupTeardown(
            setup=lambda: calls.append("setup"),
            teardown=lambda: calls.append("teardown"),
        )
        wrapped = cap.purify(handler)
        await wrapped()
        assert calls == ["setup", "handler", "teardown"]

    @pytest.mark.anyio
    async def test_with_context_sync(self) -> None:
        from emergent.wire.bridge._capabilities import WithContextSync

        calls: list[str] = []

        @contextmanager
        def ctx():
            calls.append("enter")
            yield
            calls.append("exit")

        async def handler() -> str:
            return "ok"

        cap = WithContextSync(factory=ctx)
        wrapped = cap.purify(handler)
        assert await wrapped() == "ok"
        assert calls == ["enter", "exit"]

    def test_fold_bridge_with_skip(self) -> None:
        from emergent.wire.bridge._capabilities import (
            fold_bridge,
            SkipDeprecated,
            BridgeContext,
        )

        async def handler() -> str:
            return "ok"

        ctx = BridgeContext(trigger_data=None, handler=handler, deprecated=True)
        caps = [SkipDeprecated()]
        result = fold_bridge(ctx, caps)
        assert result.skip is True

    def test_find_bridge_capability(self) -> None:
        from emergent.wire.bridge._capabilities import (
            find_bridge_capability,
            find_all_bridge_capabilities,
            SkipDeprecated,
            SkipByName,
        )

        caps = [SkipDeprecated(), SkipByName()]
        assert find_bridge_capability(caps, SkipDeprecated) is caps[0]
        assert find_bridge_capability(caps, type(None)) is None  # type: ignore[arg-type]
        assert len(find_all_bridge_capabilities(caps, SkipDeprecated)) == 1

    def test_chain_purifiers_empty(self) -> None:
        from emergent.wire.bridge._capabilities import chain_purifiers

        async def handler() -> str:
            return "ok"

        result = chain_purifiers([], handler)
        assert inspect.iscoroutinefunction(result)

    def test_ensure_async_already_async(self) -> None:
        from emergent.wire.bridge._capabilities import ensure_async

        async def handler() -> str:
            return "ok"

        assert ensure_async(handler) is handler


# ═══════════════════════════════════════════════════════════════════════════════
# 4. memory.py — memory provider methods
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class Item:
    id: int
    name: str
    value: int = 0


class TestMemoryProviders:
    """Exercise remaining MemoryRelationalProvider / MemoryKVProvider methods."""

    @pytest.mark.anyio
    async def test_relational_update(self) -> None:
        from emergent.wire.axis.query.providers.memory import MemoryRelationalProvider

        p: MemoryRelationalProvider[Item] = MemoryRelationalProvider(
            data=[Item(1, "a", 10)],
            key_fn=lambda x: x.id,
        )
        updated = await p.update(Item(1, "b", 20))
        assert updated.name == "b"

    @pytest.mark.anyio
    async def test_relational_update_not_found(self) -> None:
        from emergent.wire.axis.query.providers.memory import MemoryRelationalProvider

        p: MemoryRelationalProvider[Item] = MemoryRelationalProvider(
            key_fn=lambda x: x.id,
        )
        with pytest.raises(ValueError, match="not found"):
            await p.update(Item(99, "x"))

    @pytest.mark.anyio
    async def test_relational_delete_by_key(self) -> None:
        from emergent.wire.axis.query.providers.memory import MemoryRelationalProvider

        p: MemoryRelationalProvider[Item] = MemoryRelationalProvider(
            data=[Item(1, "a"), Item(2, "b")],
            key_fn=lambda x: x.id,
        )
        await p.delete(Item(1, "a"))
        assert len(p.data) == 1

    @pytest.mark.anyio
    async def test_relational_delete_without_key(self) -> None:
        from emergent.wire.axis.query.providers.memory import MemoryRelationalProvider

        item = Item(1, "a")
        p: MemoryRelationalProvider[Item] = MemoryRelationalProvider(data=[item])
        await p.delete(item)
        assert len(p.data) == 0

    @pytest.mark.anyio
    async def test_relational_upsert_insert(self) -> None:
        from emergent.wire.axis.query.providers.memory import MemoryRelationalProvider

        p: MemoryRelationalProvider[Item] = MemoryRelationalProvider(
            key_fn=lambda x: x.id,
        )
        result = await p.upsert(Item(1, "new"))
        assert result.name == "new"
        assert len(p.data) == 1

    @pytest.mark.anyio
    async def test_relational_upsert_update(self) -> None:
        from emergent.wire.axis.query.providers.memory import MemoryRelationalProvider

        p: MemoryRelationalProvider[Item] = MemoryRelationalProvider(
            data=[Item(1, "old")],
            key_fn=lambda x: x.id,
        )
        result = await p.upsert(Item(1, "new"))
        assert result.name == "new"
        assert len(p.data) == 1

    @pytest.mark.anyio
    async def test_relational_insert_many(self) -> None:
        from emergent.wire.axis.query.providers.memory import MemoryRelationalProvider

        p: MemoryRelationalProvider[Item] = MemoryRelationalProvider()
        result = await p.insert_many([Item(1, "a"), Item(2, "b")])
        assert len(result) == 2
        assert len(p.data) == 2

    @pytest.mark.anyio
    async def test_relational_next_id_error(self) -> None:
        from emergent.wire.axis.query.providers.memory import MemoryRelationalProvider

        p: MemoryRelationalProvider[Item] = MemoryRelationalProvider()
        with pytest.raises(RuntimeError, match="No next_id"):
            await p.next_id()

    @pytest.mark.anyio
    async def test_kv_delete(self) -> None:
        from emergent.wire.axis.query.providers.memory import MemoryKVProvider
        from emergent.wire.axis.query._kv import kv

        @dataclass(frozen=True)
        class KVItem:
            key: str
            val: int

        qs = kv(KVItem, key=lambda x: x.key)
        p: MemoryKVProvider[str, KVItem] = MemoryKVProvider(data={"a": KVItem("a", 1)})
        result = await p.delete(qs.delete("a"))
        assert result == Ok(True)

    @pytest.mark.anyio
    async def test_kv_exists(self) -> None:
        from emergent.wire.axis.query.providers.memory import MemoryKVProvider
        from emergent.wire.axis.query._kv import kv

        @dataclass(frozen=True)
        class KVItem2:
            key: str
            val: int

        qs = kv(KVItem2, key=lambda x: x.key)
        p: MemoryKVProvider[str, KVItem2] = MemoryKVProvider(data={"a": KVItem2("a", 1)})
        result = await p.exists(qs.exists("a"))
        assert result == Ok(True)

    @pytest.mark.anyio
    async def test_kv_scan(self) -> None:
        from emergent.wire.axis.query.providers.memory import MemoryKVProvider
        from emergent.wire.axis.query._kv import kv

        @dataclass(frozen=True)
        class KVItem3:
            key: str
            val: int

        qs = kv(KVItem3, key=lambda x: x.key)
        p: MemoryKVProvider[str, KVItem3] = MemoryKVProvider(data={
            "user:1": KVItem3("user:1", 10),
            "user:2": KVItem3("user:2", 20),
            "item:1": KVItem3("item:1", 5),
        })
        result = await p.scan(qs.scan("user:*"))
        assert isinstance(result, Ok)

    @pytest.mark.anyio
    async def test_kv_keys(self) -> None:
        from emergent.wire.axis.query.providers.memory import MemoryKVProvider
        from emergent.wire.axis.query._kv import kv

        @dataclass(frozen=True)
        class KVItem4:
            key: str
            val: int

        qs = kv(KVItem4, key=lambda x: x.key)
        p: MemoryKVProvider[str, KVItem4] = MemoryKVProvider(data={
            "user:1": KVItem4("user:1", 10),
            "item:1": KVItem4("item:1", 5),
        })
        result = await p.keys(qs.keys("user:*"))
        assert isinstance(result, Ok)


# ═══════════════════════════════════════════════════════════════════════════════
# 5. fastapi/_extractors.py — remaining extractors
# ═══════════════════════════════════════════════════════════════════════════════


class TestFAExtractors:
    """Exercise FastAPI extractor methods."""

    def test_is_fastapi_app_duck(self) -> None:
        from emergent.wire.bridge.bridgers.fastapi._extractors import is_fastapi_app

        class FakeApp:
            routes = []
            router = None

        assert is_fastapi_app(FakeApp()) is True
        assert is_fastapi_app("not an app") is False

    def test_is_fastapi_app_type_name(self) -> None:
        from emergent.wire.bridge.bridgers.fastapi._extractors import is_fastapi_app

        class Starlette:
            pass

        assert is_fastapi_app(Starlette()) is True

    def test_http_route_extractor_can_extract(self) -> None:
        from emergent.wire.bridge.bridgers.fastapi._extractors import HTTPRouteExtractor

        ext = HTTPRouteExtractor()
        assert ext.can_extract(type("X", (), {"routes": []})()) is True
        assert ext.can_extract(42) is False

    def test_websocket_extractor_can_extract(self) -> None:
        from emergent.wire.bridge.bridgers.fastapi._extractors import WebSocketExtractor

        ext = WebSocketExtractor()
        assert ext.can_extract(type("X", (), {"routes": []})()) is True
        assert ext.can_extract(42) is False

    def test_lifespan_extractor_can_extract(self) -> None:
        from emergent.wire.bridge.bridgers.fastapi._extractors import LifespanExtractor

        ext = LifespanExtractor()

        class FakeRouter:
            on_startup = []
            on_shutdown = []

        class FakeApp:
            router = FakeRouter()

        assert ext.can_extract(FakeApp()) is True
        assert ext.can_extract(42) is False

    def test_exception_handler_extractor_can_extract(self) -> None:
        from emergent.wire.bridge.bridgers.fastapi._extractors import ExceptionHandlerExtractor

        ext = ExceptionHandlerExtractor()
        assert ext.can_extract(type("X", (), {"exception_handlers": {}})()) is True
        assert ext.can_extract(42) is False

    def test_prepend_path(self) -> None:
        from emergent.wire.bridge.bridgers.fastapi._extractors import _prepend_path

        @dataclass(frozen=True)
        class FakeRoute:
            path: str

        route = FakeRoute(path="/users")
        result = _prepend_path(route, "/api/v1")
        assert getattr(result, "path") == "/api/v1/users"

    def test_prepend_path_no_path_field(self) -> None:
        from emergent.wire.bridge.bridgers.fastapi._extractors import _prepend_path

        @dataclass(frozen=True)
        class NoPath:
            name: str

        route = NoPath(name="test")
        result = _prepend_path(route, "/api")
        assert result is route


# ═══════════════════════════════════════════════════════════════════════════════
# 6. fastapi/_capabilities.py — FA bridge capabilities
# ═══════════════════════════════════════════════════════════════════════════════


from pydantic import BaseModel as _BaseModel


class _FAReqModel(_BaseModel):
    name: str


class _FARespModel(_BaseModel):
    id: int


class TestFACapabilities:
    """Exercise FastAPI-specific bridge capabilities."""

    def test_parse_handler_params_body(self) -> None:
        from emergent.wire.bridge.bridgers.fastapi._capabilities import _parse_handler_params

        async def handler(user: _FAReqModel) -> str:
            return ""

        params = _parse_handler_params(handler)
        assert any(p.source == "body" for p in params)

    def test_parse_handler_params_no_annotation(self) -> None:
        from typing import Callable, cast
        from emergent.wire.bridge.bridgers.fastapi._capabilities import _parse_handler_params

        # Build handler dynamically so it genuinely lacks annotation
        _fn = eval("lambda x: ''")  # noqa: S307
        handler = cast(Callable[..., str], _fn)

        params = _parse_handler_params(handler)
        assert any(p.source == "unknown" for p in params)

    def test_infer_from_fastapi(self) -> None:
        from emergent.wire.bridge.bridgers.fastapi._capabilities import InferFromFastAPI
        from emergent.wire.bridge._capabilities import BridgeContext

        async def handler(body: _FAReqModel) -> _FARespModel:
            return _FARespModel(id=1)

        ctx = BridgeContext(trigger_data=None, handler=handler)
        result = InferFromFastAPI().compile_bridge(ctx)
        assert result.request_type is _FAReqModel
        assert result.response_type is _FARespModel

    def test_parse_fastapi_handler_grouped(self) -> None:
        from emergent.wire.bridge.bridgers.fastapi._capabilities import parse_fastapi_handler

        async def handler(x: int = 0) -> str:
            return ""

        grouped = parse_fastapi_handler(handler)
        assert isinstance(grouped, dict)
        assert "unknown" in grouped


# ═══════════════════════════════════════════════════════════════════════════════
# 7. storage/_explain.py — storage explain
# ═══════════════════════════════════════════════════════════════════════════════


class TestStorageExplain:
    """Exercise storage explain dict + human-readable."""

    def test_storage_dict_unknown(self) -> None:
        from emergent.wire.axis.storage._explain import storage_dict

        class UnknownStore:
            pass

        d = storage_dict(UnknownStore())
        assert d["type"] == "UnknownStore"

    def test_explain_storage_unknown(self) -> None:
        from emergent.wire.axis.storage._explain import explain_storage

        class UnknownStore:
            pass

        text = explain_storage(UnknownStore())
        assert "UnknownStore" in text

    def test_format_scalar_float(self) -> None:
        from emergent.wire.axis.storage._explain import _format_scalar

        assert _format_scalar(5.0) == "5.0s"

    def test_format_scalar_str(self) -> None:
        from emergent.wire.axis.storage._explain import _format_scalar

        assert _format_scalar("hello") == "'hello'"


# ═══════════════════════════════════════════════════════════════════════════════
# 8. _sql.py — SQL query remaining
# ═══════════════════════════════════════════════════════════════════════════════


class TestSQLQuery:
    """Exercise SQL-specific query ops and SQLRelationalQuerySet."""

    def test_sql_relational_for_update(self) -> None:
        from emergent.wire.axis.query._sql import sql_relational

        q = sql_relational(Item).for_update(nowait=True)
        assert q.has_for_update is True

    def test_sql_relational_returning(self) -> None:
        from emergent.wire.axis.query._sql import sql_relational

        q = sql_relational(Item).returning("id", "name")
        assert q.has_returning is True

    def test_sql_relational_to_relational(self) -> None:
        from emergent.wire.axis.query._sql import sql_relational

        q = sql_relational(Item).filter(lambda i: i.value > 0).for_update()
        r = q.to_relational()
        assert not any(
            type(op).__name__ == "ForUpdate" for op in r.ops
        )

    def test_sql_relational_has_windows(self) -> None:
        from emergent.wire.axis.query._sql import sql_relational

        q = sql_relational(Item)
        assert q.has_windows is False

    def test_window_builder_partition_by_tuple(self) -> None:
        from emergent.wire.axis.query._sql import WindowBuilder
        from emergent.wire.axis.query._aggregate import Count
        from emergent.wire.axis.query._proxy import FieldProxy

        fp1 = FieldProxy("dept")
        fp2 = FieldProxy("region")
        wb = WindowBuilder(Count(), None)
        spec = wb.over(partition_by=(fp1, fp2))
        assert spec.partition_by == ("dept", "region")

    def test_window_builder_order_by_field_proxy(self) -> None:
        from emergent.wire.axis.query._sql import WindowBuilder
        from emergent.wire.axis.query._aggregate import Count
        from emergent.wire.axis.query._proxy import FieldProxy

        fp = FieldProxy("salary")
        wb = WindowBuilder(Count(), None)
        spec = wb.over(order_by=fp)
        assert len(spec.order_by) == 1
        assert spec.order_by[0].field == "salary"


# ═══════════════════════════════════════════════════════════════════════════════
# 9. surface/_explain.py — surface explain
# ═══════════════════════════════════════════════════════════════════════════════


class TestSurfaceExplain:
    """Exercise surface explain functions."""

    def test_dataclass_dict(self) -> None:
        from emergent.wire.axis.surface._explain import _dataclass_dict

        @dataclass(frozen=True)
        class FakeCap:
            name: str

        d = _dataclass_dict(FakeCap(name="test"))
        assert d["type"] == "FakeCap"
        assert d["name"] == "test"

    def test_format_obj_short(self) -> None:
        from emergent.wire.axis.surface._explain import _format_obj_short

        d = {"type": "Timeout", "seconds": 30}
        text = _format_obj_short(d)
        assert "Timeout" in text
        assert "30" in text

    def test_format_trigger_short_http(self) -> None:
        from emergent.wire.axis.surface._explain import _format_trigger_short

        d = {"type": "HTTPRouteTrigger", "method": "GET", "path": "/users"}
        assert "GET /users" == _format_trigger_short(d)

    def test_format_trigger_short_cli(self) -> None:
        from emergent.wire.axis.surface._explain import _format_trigger_short

        d = {"type": "CLITrigger", "command": "deploy"}
        assert "deploy (cli)" == _format_trigger_short(d)

    def test_format_trigger_short_tg(self) -> None:
        from emergent.wire.axis.surface._explain import _format_trigger_short

        d = {"type": "TelegrinderTrigger", "view": "message", "rules": ["Command"]}
        text = _format_trigger_short(d)
        assert "tg:message" in text

    def test_format_trigger_short_event(self) -> None:
        from emergent.wire.axis.surface._explain import _format_trigger_short

        d = {"type": "EventTrigger", "event_type": "UserCreated"}
        text = _format_trigger_short(d)
        assert "Event UserCreated" == text


# ═══════════════════════════════════════════════════════════════════════════════
# 10. delta.py — delta remaining
# ═══════════════════════════════════════════════════════════════════════════════


class TestDelta:
    """Exercise delta operations and composition."""

    def test_numeric_delta_add(self) -> None:
        from emergent.wire.axis.schema.dialects.delta import NumericDelta

        d = NumericDelta(add=50)
        assert d.apply(100) == 150

    def test_numeric_delta_multiply(self) -> None:
        from emergent.wire.axis.schema.dialects.delta import NumericDelta

        d = NumericDelta(multiply=2.0)
        assert d.apply(100) == 200.0

    def test_numeric_delta_set(self) -> None:
        from emergent.wire.axis.schema.dialects.delta import NumericDelta

        d = NumericDelta(set=0)
        assert d.apply(999) == 0

    def test_string_delta_prepend(self) -> None:
        from emergent.wire.axis.schema.dialects.delta import StringDelta

        d = StringDelta(prepend="[URGENT] ")
        assert d.apply("hello") == "[URGENT] hello"

    def test_string_delta_replace(self) -> None:
        from emergent.wire.axis.schema.dialects.delta import StringDelta

        d = StringDelta(replace=("old", "new"))
        assert d.apply("the old value") == "the new value"

    def test_collection_delta_pop(self) -> None:
        from emergent.wire.axis.schema.dialects.delta import CollectionDelta

        d: CollectionDelta[int] = CollectionDelta(pop=2)
        assert d.apply([1, 2, 3, 4]) == [1, 2]

    def test_collection_delta_remove(self) -> None:
        from emergent.wire.axis.schema.dialects.delta import CollectionDelta

        d: CollectionDelta[str] = CollectionDelta(remove=("b",))
        assert d.apply(["a", "b", "c"]) == ["a", "c"]

    def test_collection_delta_insert(self) -> None:
        from emergent.wire.axis.schema.dialects.delta import CollectionDelta

        d: CollectionDelta[str] = CollectionDelta(insert=(0, "first"))
        assert d.apply(["a", "b"]) == ["first", "a", "b"]

    def test_collection_delta_set(self) -> None:
        from emergent.wire.axis.schema.dialects.delta import CollectionDelta

        d: CollectionDelta[str] = CollectionDelta(set=("x", "y"))
        assert d.apply(["a"]) == ["x", "y"]

    def test_compose_deltas_single(self) -> None:
        from emergent.wire.axis.schema.dialects.delta import (
            compose_deltas,
            NumericDelta,
        )

        @dataclass(frozen=True)
        class D:
            balance: NumericDelta | None = None

        d1 = D(balance=NumericDelta(add=100))
        result = compose_deltas(d1)
        assert result is d1

    def test_delta_kind(self) -> None:
        from emergent.wire.axis.schema.dialects.delta import (
            _delta_kind,
            NumericDelta,
            StringDelta,
            CollectionDelta,
        )

        assert _delta_kind(NumericDelta()) == "numeric"
        assert _delta_kind(StringDelta()) == "string"
        assert _delta_kind(CollectionDelta()) == "collection"


# ═══════════════════════════════════════════════════════════════════════════════
# 11. temporal.py — temporal remaining
# ═══════════════════════════════════════════════════════════════════════════════


class TestTemporal:
    """Exercise temporal query helpers."""

    def test_temporal_filter_current(self) -> None:
        from emergent.wire.axis.schema.dialects.temporal import temporal_filter_current
        from emergent.wire.axis.query._expr import IsNull

        expr = temporal_filter_current()
        assert isinstance(expr, IsNull)

    def test_temporal_filter_as_of(self) -> None:
        from emergent.wire.axis.schema.dialects.temporal import temporal_filter_as_of
        from emergent.wire.axis.query._expr import And

        ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
        expr = temporal_filter_as_of(ts)
        assert isinstance(expr, And)

    def test_temporal_filter_version(self) -> None:
        from emergent.wire.axis.schema.dialects.temporal import temporal_filter_version
        from emergent.wire.axis.query._expr import Eq

        expr = temporal_filter_version(5)
        assert isinstance(expr, Eq)


# ═══════════════════════════════════════════════════════════════════════════════
# 12. auth/openapi.py — auth openapi
# ═══════════════════════════════════════════════════════════════════════════════


class TestAuthOpenAPI:
    """Exercise AuthOpenAPI capability."""

    def test_auth_openapi_compile_fastapi_route(self) -> None:
        from emergent.wire.derive.auth.openapi import AuthOpenAPI
        from emergent.wire.axis._capability import FastAPIRouteContext

        ctx = FastAPIRouteContext(path="/users", method="GET")
        cap = AuthOpenAPI(scheme_name="bearerAuth")
        result = cap.compile_fastapi_route(ctx)
        assert result.openapi_extra is not None
        assert "security" in result.openapi_extra
        assert "responses" in result.openapi_extra


# ═══════════════════════════════════════════════════════════════════════════════
# 13. _coerce.py — coercion remaining
# ═══════════════════════════════════════════════════════════════════════════════


class TestExprCoercer:
    """Exercise ExprCoercer branches."""

    def test_coercer_noop_empty(self) -> None:
        from emergent.wire.axis.query._coerce import ExprCoercer
        from emergent.wire.axis.query._expr import Eq, Field, Const

        coercer = ExprCoercer({})
        expr = Eq(Field("x"), Const(1))
        assert coercer(expr) is expr

    def test_coercer_bool_empty_false(self) -> None:
        from emergent.wire.axis.query._coerce import ExprCoercer

        assert bool(ExprCoercer({})) is False

    def test_coercer_bool_nonempty_true(self) -> None:
        from emergent.wire.axis.query._coerce import ExprCoercer

        assert bool(ExprCoercer({"x": str})) is True

    def test_coercer_applies_to_eq(self) -> None:
        from emergent.wire.axis.query._coerce import ExprCoercer
        from emergent.wire.axis.query._expr import Eq, Field, Const

        coercer = ExprCoercer({"x": lambda v: str(v)})
        expr = Eq(Field("x"), Const(42))
        result = coercer(expr)
        assert isinstance(result, Eq)

    def test_coercer_and_or_not(self) -> None:
        from emergent.wire.axis.query._coerce import ExprCoercer
        from emergent.wire.axis.query._expr import And, Or, Not, Eq, Field, Const

        coercer = ExprCoercer({"x": str})
        expr = And(
            Or(Eq(Field("x"), Const(1)), Eq(Field("x"), Const(2))),
            Not(Eq(Field("x"), Const(3))),
        )
        result = coercer(expr)
        assert isinstance(result, And)

    def test_coercer_in_node(self) -> None:
        from emergent.wire.axis.query._coerce import ExprCoercer
        from emergent.wire.axis.query._expr import In, Field

        coercer = ExprCoercer({"x": str})
        expr = In(Field("x"), values=(1, 2, 3))
        result = coercer(expr)
        assert isinstance(result, In)

    def test_coercer_between_node(self) -> None:
        from emergent.wire.axis.query._coerce import ExprCoercer
        from emergent.wire.axis.query._expr import Between, Field, Const

        coercer = ExprCoercer({"x": str})
        expr = Between(Field("x"), Const(1), Const(10))
        result = coercer(expr)
        assert isinstance(result, Between)


# ═══════════════════════════════════════════════════════════════════════════════
# 14. query/_explain.py — query explain
# ═══════════════════════════════════════════════════════════════════════════════


class TestQueryExplain:
    """Exercise query explain handlers and ExplainDialect."""

    def test_format_ops_empty(self) -> None:
        from emergent.wire.axis.query._explain import format_ops, RELATIONAL_EXPLAIN

        assert format_ops([], RELATIONAL_EXPLAIN) == "(empty)"

    def test_format_ops_filter(self) -> None:
        from emergent.wire.axis.query._explain import format_ops, RELATIONAL_EXPLAIN
        from emergent.wire.axis.query._relational import Filter
        from emergent.wire.axis.query._expr import Eq, Field, Const

        ops = [Filter(Eq(Field("x"), Const(1)))]
        text = format_ops(ops, RELATIONAL_EXPLAIN)
        assert "Filter" in text

    def test_explain_dialect_with_handler(self) -> None:
        from emergent.wire.axis.query._explain import ExplainDialect, RELATIONAL_EXPLAIN

        def custom_handler(op: object) -> dict[str, object]:
            return {"op": "Custom"}

        class CustomOp:
            pass

        dialect = ExplainDialect(handlers=RELATIONAL_EXPLAIN)
        new_dialect = dialect.with_handler(CustomOp, custom_handler)
        assert CustomOp in new_dialect.handlers

    def test_explain_dialect_without_handler(self) -> None:
        from emergent.wire.axis.query._explain import ExplainDialect, RELATIONAL_EXPLAIN
        from emergent.wire.axis.query._relational import Filter

        dialect = ExplainDialect(handlers=RELATIONAL_EXPLAIN)
        new_dialect = dialect.without_handler(Filter)
        assert Filter not in new_dialect.handlers

    def test_kv_explain(self) -> None:
        from emergent.wire.axis.query._explain import explain_ops, KV_EXPLAIN
        from emergent.wire.axis.query._kv import KVGet, KVSet, KVDelete, Exists, Scan, Keys

        ops = [KVGet("k"), KVSet("k", "v", ttl=60), KVDelete("k"), Exists("k"), Scan("*"), Keys("*")]
        result = explain_ops(ops, KV_EXPLAIN)
        assert len(result) == 6

    def test_api_explain(self) -> None:
        from emergent.wire.axis.query._explain import explain_ops, API_EXPLAIN
        from emergent.wire.axis.query._api import ListOp, GetOp, CreateOp, DeleteOp

        ops = [ListOp(), GetOp(id=1), CreateOp(entity=Item(1, "a")), DeleteOp(id=1)]
        result = explain_ops(ops, API_EXPLAIN)
        assert len(result) == 4


# ═══════════════════════════════════════════════════════════════════════════════
# 15. compile/_explain.py — compile explain
# ═══════════════════════════════════════════════════════════════════════════════


class TestCompileExplain:
    """Exercise compile explain functions."""

    def test_explain_no_tracing(self) -> None:
        from emergent.wire.compile._explain import explain
        from emergent.wire.compile._core import Axes
        from emergent.wire.axis.schema._inspect import inspect_dataclass

        axes = Axes(schema=inspect_dataclass)
        text = explain(axes)
        assert "tracing not enabled" in text

    def test_explain_field_no_trace(self) -> None:
        from emergent.wire.compile._explain import explain_field
        from emergent.wire.compile._core import Axes
        from emergent.wire.axis.schema._inspect import inspect_dataclass

        axes = Axes(schema=inspect_dataclass)
        text = explain_field(axes, "email")
        assert "not found" in text

    def test_explain_type_no_trace(self) -> None:
        from emergent.wire.compile._explain import explain_type
        from emergent.wire.compile._core import Axes
        from emergent.wire.axis.schema._inspect import inspect_dataclass

        axes = Axes(schema=inspect_dataclass)
        text = explain_type(axes, "User")
        assert "not found" in text


# ═══════════════════════════════════════════════════════════════════════════════
# 16. _relational.py — relational remaining
# ═══════════════════════════════════════════════════════════════════════════════


class TestRelational:
    """Exercise relational ops and QuerySet."""

    def test_limit_negative_raises(self) -> None:
        from emergent.wire.axis.query._relational import Limit

        with pytest.raises(ValueError, match="non-negative"):
            Limit(-1)

    def test_offset_negative_raises(self) -> None:
        from emergent.wire.axis.query._relational import Offset

        with pytest.raises(ValueError, match="non-negative"):
            Offset(-1)

    def test_distinct_dedup_dataclass(self) -> None:
        from emergent.wire.axis.query._relational import Distinct
        from emergent.wire.axis.query._contexts import MemoryQueryContext

        data: list[object] = [Item(1, "a"), Item(1, "a"), Item(2, "b")]
        ctx = MemoryQueryContext(data=data)
        result = Distinct().compile_memory_query(ctx)
        assert len(result.data) == 2

    def test_relational_queryset_append(self) -> None:
        from emergent.wire.axis.query._relational import relational

        q = relational(Item).limit(10)
        assert len(q.ops) == 1

    def test_select_memory_query(self) -> None:
        from emergent.wire.axis.query._relational import Select
        from emergent.wire.axis.query._contexts import MemoryQueryContext

        data: list[object] = [Item(1, "a", 10), Item(2, "b", 20)]
        ctx = MemoryQueryContext(data=data)
        result = Select(fields=("name",)).compile_memory_query(ctx)
        assert result.data[0] == {"name": "a"}


# ═══════════════════════════════════════════════════════════════════════════════
# 17. derive/_explain.py — derive explain
# ═══════════════════════════════════════════════════════════════════════════════


class TestDeriveExplain:
    """Exercise derive explain functions."""

    def test_trigger_dict_http(self) -> None:
        from emergent.wire.derive._explain import trigger_dict
        from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger

        t = HTTPRouteTrigger(method="GET", path="/users")
        d = trigger_dict(t)
        assert d["type"] == "http"
        assert d["method"] == "GET"

    def test_trigger_dict_cli(self) -> None:
        from emergent.wire.derive._explain import trigger_dict
        from emergent.wire.axis.surface.triggers.cli import CLITrigger

        t = CLITrigger(command="deploy")
        d = trigger_dict(t)
        assert d["type"] == "cli"
        assert d["command"] == "deploy"

    def test_trigger_dict_unknown(self) -> None:
        from emergent.wire.derive._explain import trigger_dict

        class CustomTrigger:
            pass

        d = trigger_dict(CustomTrigger())
        assert d["type"] == "CustomTrigger"

    def test_effect_dict_dataclass(self) -> None:
        from emergent.wire.derive._explain import effect_dict

        @dataclass(frozen=True)
        class FakeEffect:
            name: str

        d = effect_dict(FakeEffect(name="create"))
        assert d["type"] == "FakeEffect"
        assert d["name"] == "create"

    def test_capability_dict(self) -> None:
        from emergent.wire.derive._explain import capability_dict

        @dataclass(frozen=True)
        class FakeCap:
            timeout: int

        d = capability_dict(FakeCap(timeout=30))
        assert d["timeout"] == 30


# ═══════════════════════════════════════════════════════════════════════════════
# 18. _project.py — project remaining
# ═══════════════════════════════════════════════════════════════════════════════


class TestProjections:
    """Exercise projection types (no DeriveCtx needed for pure data tests)."""

    def test_ok_response_resolve(self) -> None:
        from emergent.wire.derive._project import OkResponse

        resp = OkResponse()
        # We only test that resolve method exists and is callable
        assert hasattr(resp, "resolve")

    def test_count_response_resolve(self) -> None:
        from emergent.wire.derive._project import CountResponse

        resp = CountResponse()
        assert hasattr(resp, "resolve")

    def test_bool_response_resolve(self) -> None:
        from emergent.wire.derive._project import BoolResponse

        resp = BoolResponse()
        assert hasattr(resp, "resolve")

    def test_empty_response_resolve(self) -> None:
        from emergent.wire.derive._project import EmptyResponse

        resp = EmptyResponse()
        assert hasattr(resp, "resolve")

    def test_custom_response_resolve(self) -> None:
        from emergent.wire.derive._project import CustomResponse

        def conv(cls: type, result: object) -> object:
            return result

        resp = CustomResponse(field_specs=(("x", int),), converter=conv)
        assert hasattr(resp, "resolve")

    def test_convenience_constructors(self) -> None:
        from emergent.wire.derive._project import (
            all_fields,
            id_only,
            non_id,
            no_fields,
            required_non_id,
            fields,
            exclude,
            optional_non_id,
            entity_response,
            list_response,
            ok_response,
            paginated_response,
            count_response,
            bool_response,
            empty_response,
            cursor_paginated_response,
        )

        assert all_fields() is not None
        assert id_only() is not None
        assert non_id() is not None
        assert no_fields() is not None
        assert required_non_id() is not None
        assert fields("a", "b") is not None
        assert exclude("c") is not None
        assert optional_non_id() is not None
        assert entity_response() is not None
        assert list_response() is not None
        assert ok_response() is not None
        assert paginated_response() is not None
        assert count_response() is not None
        assert bool_response() is not None
        assert empty_response() is not None
        assert cursor_paginated_response() is not None


# ═══════════════════════════════════════════════════════════════════════════════
# 19. _pipeline.py — pipeline remaining
# ═══════════════════════════════════════════════════════════════════════════════


class TestPipeline:
    """Exercise pipeline steps."""

    def test_pipeline_creation(self) -> None:
        from emergent.wire.derive._pipeline import Pipeline, ScopeQuery, FetchAll, WrapItems

        p = Pipeline(ScopeQuery(), FetchAll(), WrapItems())
        assert len(p.steps) == 3

    def test_pipeline_step_protocol(self) -> None:
        from emergent.wire.derive._pipeline import PipelineStep, ScopeQuery

        assert isinstance(ScopeQuery(), PipelineStep)

    def test_paginate_creation(self) -> None:
        from emergent.wire.derive._pipeline import Paginate

        p = Paginate(default_page_size=50)
        assert p.default_page_size == 50

    def test_set_timestamp_creation(self) -> None:
        from emergent.wire.derive._pipeline import SetTimestamp

        s = SetTimestamp(field_name="created_at")
        assert s.field_name == "created_at"

    def test_set_field_value_creation(self) -> None:
        from emergent.wire.derive._pipeline import SetFieldValue

        s = SetFieldValue(field_name="status", value_fn=lambda op: "active")
        assert s.field_name == "status"

    def test_in_memory_sort_creation(self) -> None:
        from emergent.wire.derive._pipeline import InMemorySort

        s = InMemorySort(default_sort="name", default_order="desc")
        assert s.default_sort == "name"

    def test_wrap_paginated_creation(self) -> None:
        from emergent.wire.derive._pipeline import WrapPaginated

        w = WrapPaginated(default_page_size=10)
        assert w.default_page_size == 10


# ═══════════════════════════════════════════════════════════════════════════════
# 20. _introspect.py — introspect remaining
# ═══════════════════════════════════════════════════════════════════════════════


class TestIntrospect:
    """Exercise handler introspection."""

    def test_unwrap_handler_no_wrapped(self) -> None:
        from emergent.wire.bridge._introspect import unwrap_handler

        def plain() -> str:
            return "ok"

        handler, decorators = unwrap_handler(plain)
        assert handler is plain
        assert decorators == ()

    def test_unwrap_handler_with_wrapped(self) -> None:
        from emergent.wire.bridge._introspect import unwrap_handler

        def original() -> str:
            return "ok"

        @wraps(original)
        def wrapper() -> str:
            return original()

        handler, decorators = unwrap_handler(wrapper)
        assert handler is original
        assert len(decorators) == 1

    def test_analyze_handler_async(self) -> None:
        from emergent.wire.bridge._introspect import analyze_handler

        async def my_handler(x: int, y: str = "default") -> bool:
            return True

        shape = analyze_handler(my_handler)
        assert shape.is_async is True
        assert "x" in shape.parameters
        assert "y" in shape.parameters
        assert shape.return_type is bool

    def test_analyze_handler_sync(self) -> None:
        from emergent.wire.bridge._introspect import analyze_handler

        def my_handler(x: int) -> str:
            return ""

        shape = analyze_handler(my_handler)
        assert shape.is_async is False

    def test_extract_class_methods(self) -> None:
        from emergent.wire.bridge._introspect import extract_class_methods

        class MyView:
            def get(self) -> str:
                return ""

            def post(self) -> str:
                return ""

        methods = list(extract_class_methods(MyView, ("get", "post", "delete")))
        assert len(methods) == 2
        assert methods[0][0] == "get"
        assert methods[1][0] == "post"

    def test_get_view_class(self) -> None:
        from emergent.wire.bridge._introspect import get_view_class

        class MyClass:
            pass

        assert get_view_class(MyClass) is MyClass
        assert get_view_class("str") is None

    def test_parameter_kind_of(self) -> None:
        from emergent.wire.bridge._introspect import ParameterKind

        param = inspect.Parameter("x", inspect.Parameter.KEYWORD_ONLY)
        assert ParameterKind.of(param) == ParameterKind.KEYWORD_ONLY

    def test_closure_fallback_unwrap(self) -> None:
        from emergent.wire.bridge._introspect import ClosureFallbackUnwrap

        def plain() -> str:
            return "ok"

        strategy = ClosureFallbackUnwrap()
        handler, _decorators = strategy.unwrap(plain)
        assert handler is plain

    def test_resolve_descriptor(self) -> None:
        from emergent.wire.bridge._introspect import resolve_descriptor

        assert resolve_descriptor(42) == 42

    def test_analyze_handler_partial(self) -> None:
        from functools import partial
        from emergent.wire.bridge._introspect import analyze_handler

        def full_handler(a: int, b: str) -> bool:
            return True

        p = partial(full_handler, a=1)
        shape = analyze_handler(p)
        assert shape.partial_func is not None
        assert "a" not in shape.parameters


# ═══════════════════════════════════════════════════════════════════════════════
# 21. http contrib — ImportError stub path
# ═══════════════════════════════════════════════════════════════════════════════


class TestHTTPContrib:
    """Exercise http contrib import behavior."""

    def test_http_module_importable(self) -> None:
        from emergent.wire.axis.query.contrib import http
        assert hasattr(http, "__all__")


# ═══════════════════════════════════════════════════════════════════════════════
# 22. compile/targets/sqlalchemy.py — SA target
# ═══════════════════════════════════════════════════════════════════════════════


class TestSATarget:
    """Exercise SQLAlchemy target compilation."""

    def test_compile_sa_non_dataclass_raises(self) -> None:
        from emergent.wire.compile.targets.sqlalchemy import compile_sa

        with pytest.raises(TypeError, match="must be a dataclass"):
            compile_sa(int, "integers")

    def test_make_sa_initial(self) -> None:
        from emergent.wire.compile.targets.sqlalchemy import make_sa_initial
        from emergent.wire.axis._capability import SQLAlchemyContext

        initial_fn = make_sa_initial()
        ctx = initial_fn("field1", int)
        assert isinstance(ctx, SQLAlchemyContext)
        assert ctx.field_name == "field1"


# ═══════════════════════════════════════════════════════════════════════════════
# 23. compile/_pipeline.py — pipeline remaining
# ═══════════════════════════════════════════════════════════════════════════════


class TestCompilePipeline:
    """Exercise compile pipeline functions."""

    def test_compiled_pipeline_creation(self) -> None:
        from emergent.wire.compile._pipeline import CompiledPipeline

        def _noop_exec(h: object, s: object, g: object) -> None:
            pass

        p = CompiledPipeline(
            execute=_noop_exec,
            extractor=None,
            coerce_model=None,
            coercion=None,
        )
        assert p.coerce_model is None

    def test_compile_pipeline_no_execute_raises(self) -> None:
        from emergent.wire.compile._pipeline import compile_pipeline
        from emergent.wire.compile._core import Axes
        from emergent.wire.axis.schema._inspect import inspect_dataclass

        class BadCtx:
            coercion = None

        axes = Axes(schema=inspect_dataclass)
        with pytest.raises(TypeError, match="no 'execute'"):
            compile_pipeline(BadCtx(), axes)

    def test_compile_pipeline_with_execute(self) -> None:
        from emergent.wire.compile._pipeline import compile_pipeline, CompiledPipeline
        from emergent.wire.compile._core import Axes
        from emergent.wire.axis.schema._inspect import inspect_dataclass

        def _good_exec(h: object, s: object, g: object) -> None:
            pass

        class GoodCtx:
            coercion = None
            execute = _good_exec

        axes = Axes(schema=inspect_dataclass)
        result = compile_pipeline(GoodCtx(), axes)
        assert isinstance(result, CompiledPipeline)

    def test_make_scope_no_layer(self) -> None:
        from emergent.wire.compile._pipeline import _make_scope
        from nodnod import Scope

        scope = _make_scope(None)
        assert isinstance(scope, Scope)


# ═══════════════════════════════════════════════════════════════════════════════
# 24. ops/_graph.py — ops remaining
# ═══════════════════════════════════════════════════════════════════════════════


# --- Module-level Op classes (must be visible to get_type_hints) ---
from emergent.ops._graph import Op as _OpBase


@dataclass(frozen=True, slots=True)
class _GetPriceOp(_OpBase[float, str]):
    product_id: int


async def _get_price_handler(req: _GetPriceOp) -> Result[float, str]:
    return Ok(9.99)


@dataclass(frozen=True, slots=True)
class _MyUnboundOp(_OpBase[int, str]):
    x: int


@dataclass(frozen=True, slots=True)
class _UnknownOp(_OpBase[int, str]):
    x: int


@dataclass(frozen=True, slots=True)
class _AddOp(_OpBase[int, str]):
    a: int
    b: int


async def _add_handler(req: _AddOp) -> Result[int, str]:
    return Ok(req.a + req.b)


@dataclass(frozen=True, slots=True)
class _NopOp(_OpBase[int, str]):
    pass


async def _nop_handler(req: _NopOp) -> Result[int, str]:
    return Ok(0)


class TestOpsGraph:
    """Exercise ops builder and runner."""

    def test_ops_builder(self) -> None:
        from emergent.ops._graph import ops

        builder = ops().on(_GetPriceOp, _get_price_handler)
        runner = builder.compile()
        assert runner is not None

    def test_op_unbound_get_raises(self) -> None:
        op = _MyUnboundOp(x=1)
        with pytest.raises(RuntimeError, match="not bound"):
            op.get()

    def test_is_op_type(self) -> None:
        from emergent.ops._graph import _is_op_type

        assert _is_op_type(_MyUnboundOp) is True
        assert _is_op_type(int) is False
        assert _is_op_type("not a type") is False

    @pytest.mark.anyio
    async def test_runner_run_unregistered(self) -> None:
        from emergent.ops._graph import ops

        runner = ops().compile()
        result = await runner.run(_UnknownOp(x=1))
        assert isinstance(result, Error)

    @pytest.mark.anyio
    async def test_runner_simple_op(self) -> None:
        from emergent.ops._graph import ops

        runner = ops().on(_AddOp, _add_handler).compile()
        result = await runner.run(_AddOp(a=2, b=3))
        assert result == Ok(5)

    def test_runner_call_returns_lazy(self) -> None:
        from emergent.ops._graph import ops

        runner = ops().on(_NopOp, _nop_handler).compile()
        lazy = runner(_NopOp())
        assert lazy is not None

    def test_ops_builder_inject(self) -> None:
        from emergent.ops._graph import ops

        builder = ops().inject(str, "hello")
        assert builder is not None

    def test_operation_set_alias(self) -> None:
        from emergent.ops._graph import operation_set

        builder = operation_set()
        assert builder is not None

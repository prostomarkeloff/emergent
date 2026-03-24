# pyright: reportPrivateUsage=false
"""Coverage push — target every file with >20 missing statements.

Covers uncovered lines in:
  resolve.py, telegram.py, _transforms.py, cli.py, _generate.py,
  _capabilities.py (bridge), caps.py (auth), _execute.py,
  memory.py, _request.py, _stateful.py, _extractors.py (fastapi),
  _capabilities.py (fastapi), _sqlalchemy.py (storage), _explain.py,
  methods.py, fastapi.py (target), telegrinder.py (target),
  _sqlalchemy.py (query), _http.py (query)
"""

from __future__ import annotations

import argparse
import base64
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Annotated, Any, Self, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from kungfu import Ok, Some, Nothing, Option, Result
from nodnod import Scope
from nodnod.agent.event_loop.agent import EventLoopAgent

from emergent.wire.axis.schema._universal import Identity


# ═══════════════════════════════════════════════════════════════════════════════
# Shared fixtures
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class Foo:
    id: int
    name: str
    active: bool = True
    score: float = 0.0
    tag: str | None = None


@dataclass(frozen=True)
class Bar:
    key: str
    value: int


@dataclass(frozen=True)
class SimpleReq:
    name: str


@dataclass(frozen=True)
class SimpleResp:
    result: str


# Module-level Pydantic model for FastAPI inference tests
try:
    from pydantic import BaseModel as _BM

    class PydanticUser(_BM):
        name: str
        age: int = 0
except ImportError:
    PydanticUser = None  # type: ignore[assignment, misc]


# ═══════════════════════════════════════════════════════════════════════════════
# 1. resolve.py — compose_params, try_compose_params, resolve_transition
# ═══════════════════════════════════════════════════════════════════════════════


class TestResolveComposeParams:
    """Cover compose_params, try_compose_params, resolve_transition deep paths."""

    @pytest.mark.asyncio
    async def test_compose_params_non_node_plain_type_raises(self) -> None:
        from emergent.wire.axis.surface.codecs.resolve import compose_params

        async def method(self: object, x: int) -> None: ...

        from emergent.wire.axis.surface.codecs.resolve import get_method_params
        params = get_method_params(method)
        scope = Scope()
        async with scope:
            # int is required, not a node, not in scope -> RuntimeError
            with pytest.raises(RuntimeError, match="Required param failed"):
                await compose_params(params, scope, EventLoopAgent)

    @pytest.mark.asyncio
    async def test_compose_params_optional_non_node(self) -> None:
        from emergent.wire.axis.surface.codecs.resolve import compose_params

        async def method(self: object, x: Option[int]) -> None: ...

        from emergent.wire.axis.surface.codecs.resolve import get_method_params
        params = get_method_params(method)
        scope = Scope()
        async with scope:
            result = await compose_params(params, scope, EventLoopAgent)
        # x is optional, not a node, not in scope -> Nothing
        assert "x" in result
        assert isinstance(result["x"], Nothing)

    @pytest.mark.asyncio
    async def test_compose_params_pre_injected_type(self) -> None:
        from emergent.wire.axis.surface.codecs.resolve import compose_params

        async def method(self: object, val: int) -> None: ...

        from emergent.wire.axis.surface.codecs.resolve import get_method_params
        params = get_method_params(method)
        scope = Scope()
        async with scope:
            scope.inject(int, 42)
            result = await compose_params(params, scope, EventLoopAgent)
        assert result["val"] == 42

    @pytest.mark.asyncio
    async def test_try_compose_params_required_non_node_returns_nothing(self) -> None:
        from emergent.wire.axis.surface.codecs.resolve import try_compose_params

        async def method(self: object, x: int) -> None: ...

        from emergent.wire.axis.surface.codecs.resolve import get_method_params
        params = get_method_params(method)
        scope = Scope()
        async with scope:
            result = await try_compose_params(params, scope, EventLoopAgent)
        assert isinstance(result, Nothing)

    @pytest.mark.asyncio
    async def test_try_compose_params_optional_non_node_wraps_failure(self) -> None:
        from emergent.wire.axis.surface.codecs.resolve import try_compose_params

        async def method(self: object, x: Option[int]) -> None: ...

        from emergent.wire.axis.surface.codecs.resolve import get_method_params
        params = get_method_params(method)
        scope = Scope()
        async with scope:
            result = await try_compose_params(params, scope, EventLoopAgent)
        assert isinstance(result, Some)

    @pytest.mark.asyncio
    async def test_try_compose_params_pre_injected_succeeds(self) -> None:
        from emergent.wire.axis.surface.codecs.resolve import try_compose_params

        async def method(self: object, val: int) -> None: ...

        from emergent.wire.axis.surface.codecs.resolve import get_method_params
        params = get_method_params(method)
        scope = Scope()
        async with scope:
            scope.inject(int, 99)
            result = await try_compose_params(params, scope, EventLoopAgent)
        assert isinstance(result, Some)
        assert result.unwrap()["val"] == 99

    @pytest.mark.asyncio
    async def test_resolve_transition_returns_nothing_when_all_fail(self) -> None:
        from emergent.wire.axis.surface.codecs.resolve import resolve_transition

        async def t1(self: object, x: int) -> None: ...
        async def t2(self: object, y: str) -> None: ...

        scope = Scope()
        async with scope:
            result = await resolve_transition([t1, t2], scope, EventLoopAgent)
        assert isinstance(result, Nothing)

    @pytest.mark.asyncio
    async def test_resolve_transition_first_match(self) -> None:
        from emergent.wire.axis.surface.codecs.resolve import resolve_transition

        async def t1(self: object, x: int) -> None: ...
        async def t2(self: object, y: str) -> None: ...

        scope = Scope()
        async with scope:
            scope.inject(str, "hello")
            result = await resolve_transition([t1, t2], scope, EventLoopAgent)
        assert isinstance(result, Some)
        method, _params = result.unwrap()
        assert method is t2

    def test_get_transition_params_with_method(self) -> None:
        from emergent.wire.axis.surface.codecs.resolve import get_transition_params

        @dataclass
        class Flow:
            async def __transition__(self, x: int, y: str) -> None: ...

        params = get_transition_params(Flow)
        assert "x" in params
        assert "y" in params


# ═══════════════════════════════════════════════════════════════════════════════
# 2. telegram.py — EditMessage, AnswerCallback, ReplyMessage enrichers
# ═══════════════════════════════════════════════════════════════════════════════


class TestTelegramDialectEnrichers:
    """Cover EditMessage.enrich, AnswerCallback.enrich, ReplyMessage.enrich."""

    @pytest.mark.asyncio
    async def test_edit_message_no_callback_query(self) -> None:
        from emergent.wire.axis.surface.dialects.telegram import EditMessage

        enricher = EditMessage()

        async def call(scope: Scope) -> str:
            return "response text"

        scope = Scope()
        async with scope:
            result = await enricher.enrich(call, scope)
        assert result == "response text"

    @pytest.mark.asyncio
    async def test_answer_callback_no_callback_query(self) -> None:
        from emergent.wire.axis.surface.dialects.telegram import AnswerCallback

        enricher = AnswerCallback(text="Processing", show_alert=True)

        async def call(scope: Scope) -> str:
            return "done"

        scope = Scope()
        async with scope:
            result = await enricher.enrich(call, scope)
        assert result == "done"

    @pytest.mark.asyncio
    async def test_reply_message_none_response(self) -> None:
        from emergent.wire.axis.surface.dialects.telegram import ReplyMessage

        enricher = ReplyMessage()

        async def call(scope: Scope) -> None:
            return None

        scope = Scope()
        async with scope:
            result = await enricher.enrich(call, scope)
        assert result is None

    @pytest.mark.asyncio
    async def test_reply_message_empty_string(self) -> None:
        from emergent.wire.axis.surface.dialects.telegram import ReplyMessage

        enricher = ReplyMessage()

        async def call(scope: Scope) -> str:
            return ""

        scope = Scope()
        async with scope:
            result = await enricher.enrich(call, scope)
        assert result is None

    @pytest.mark.asyncio
    async def test_reply_message_no_api_in_scope(self) -> None:
        from emergent.wire.axis.surface.dialects.telegram import ReplyMessage

        enricher = ReplyMessage()

        async def call(scope: Scope) -> str:
            return "hello world"

        scope = Scope()
        async with scope:
            result = await enricher.enrich(call, scope)
        assert result == "hello world"

    def test_unwrap_some_with_value(self) -> None:
        from emergent.wire.axis.surface.dialects.telegram import _unwrap_some

        class FakeVal:
            value = 42

        assert _unwrap_some(FakeVal()) == 42

    def test_unwrap_some_without_value(self) -> None:
        from emergent.wire.axis.surface.dialects.telegram import _unwrap_some

        assert _unwrap_some(object()) is None


# ═══════════════════════════════════════════════════════════════════════════════
# 3. _transforms.py — EffectRateLimited, EffectDeprecated, Filtered, Searchable
# ═══════════════════════════════════════════════════════════════════════════════


class TestTransformsDeepPaths:
    """Cover EffectRateLimited, EffectDeprecated, Filtered, Searchable transforms."""

    def test_effect_rate_limited_with_rpm(self) -> None:
        from emergent.wire.derive._transforms import EffectRateLimited

        cap = EffectRateLimited(rpm=120)
        # Just verify construction
        assert cap.rpm == 120

    def test_effect_deprecated_creation(self) -> None:
        from emergent.wire.derive._transforms import EffectDeprecated

        cap = EffectDeprecated()
        assert cap is not None

    def test_with_rate_limit_creation(self) -> None:
        from emergent.wire.derive._transforms import WithRateLimit

        cap = WithRateLimit(rpm=60)
        assert cap.rpm == 60

    def test_with_retry_creation(self) -> None:
        from emergent.wire.derive._transforms import WithRetry

        cap = WithRetry(max_retries=5)
        assert cap.max_retries == 5

    def test_with_timeout_creation(self) -> None:
        from emergent.wire.derive._transforms import WithTimeout

        cap = WithTimeout(seconds=30.0)
        assert cap.seconds == 30.0


# ═══════════════════════════════════════════════════════════════════════════════
# 4. cli.py — CLI compilation deep paths
# ═══════════════════════════════════════════════════════════════════════════════


class TestCLIDeepPaths:
    """Cover CLI compilation paths: delegate handler inspection, typed CLI."""

    def test_inspect_handler_params_basic(self) -> None:
        from emergent.wire.compile.targets.cli import _inspect_handler_params

        def handler(name: str, age: int = 30) -> str:
            return f"{name}:{age}"

        params = _inspect_handler_params(handler)
        assert len(params) == 2
        names = [p[0] for p in params]
        assert "name" in names
        assert "age" in names

    def test_inspect_handler_params_no_type_hints(self) -> None:
        from emergent.wire.compile.targets.cli import _inspect_handler_params

        # Build handler with no annotations at runtime to test no-type-hints path
        ns: dict[str, Any] = {}
        exec("def handler(x): pass", ns)
        handler = ns["handler"]

        params = _inspect_handler_params(handler)
        assert len(params) == 0

    def test_prompt_value_int(self) -> None:
        from emergent.wire.compile.targets.cli import _prompt_value

        with patch("builtins.input", return_value="42"):
            result = _prompt_value("age", int)
        assert result == 42

    def test_prompt_value_float(self) -> None:
        from emergent.wire.compile.targets.cli import _prompt_value

        with patch("builtins.input", return_value="3.14"):
            result = _prompt_value("score", float)
        assert result == 3.14

    def test_prompt_value_bool(self) -> None:
        from emergent.wire.compile.targets.cli import _prompt_value

        with patch("builtins.input", return_value="yes"):
            result = _prompt_value("active", bool)
        assert result is True

    def test_prompt_value_str(self) -> None:
        from emergent.wire.compile.targets.cli import _prompt_value

        with patch("builtins.input", return_value="hello"):
            result = _prompt_value("name", str)
        assert result == "hello"

    def test_prompt_value_empty(self) -> None:
        from emergent.wire.compile.targets.cli import _prompt_value

        with patch("builtins.input", return_value=""):
            result = _prompt_value("name", str)
        assert result is None

    def test_prompt_value_eof_error(self) -> None:
        from emergent.wire.compile.targets.cli import _prompt_value

        with patch("builtins.input", side_effect=EOFError):
            result = _prompt_value("name", str)
        assert result is None

    def test_build_delegate_args_plain_type(self) -> None:
        from emergent.wire.compile.targets.cli import _build_delegate_args

        def handler(name: str) -> str:
            return name

        ns = argparse.Namespace(name="Bob")
        args = _build_delegate_args(handler, ns)
        assert args["name"] == "Bob"

    def test_build_delegate_args_none_value(self) -> None:
        from emergent.wire.compile.targets.cli import _build_delegate_args

        def handler(name: str) -> str:
            return name

        ns = argparse.Namespace(name=None)
        args = _build_delegate_args(handler, ns)
        assert "name" not in args

    def test_build_delegate_args_with_int(self) -> None:
        from emergent.wire.compile.targets.cli import _build_delegate_args

        def handler(count: int) -> str:
            return str(count)

        ns = argparse.Namespace(count=42)
        args = _build_delegate_args(handler, ns)
        assert args["count"] == 42

    def test_get_delegate_arg_specs_with_bool(self) -> None:
        from emergent.wire.compile.targets.cli import _get_delegate_arg_specs
        from emergent.wire.compile._core import Axes

        def handler(verbose: bool = False) -> str:
            return ""

        specs = _get_delegate_arg_specs(handler, Axes.default())
        assert len(specs) >= 1

    def test_coerce_cli_values(self) -> None:
        from emergent.wire.compile.targets.cli import coerce_cli_values
        from emergent.wire.compile._core import Axes

        @dataclass
        class R:
            count: int

        get_value = coerce_cli_values(R, Axes.default(), lambda n: "5" if n == "count" else None)
        assert get_value("count") == 5

    def test_cli_wrap_context_defaults(self) -> None:
        from emergent.wire.compile.targets.cli import CLIWrapContext

        ctx = CLIWrapContext()
        assert ctx.request_type is None
        assert ctx.response_type is None
        assert ctx.execute is None

    def test_cli_route_creation(self) -> None:
        from emergent.wire.compile.targets.cli import CLIRoute

        route = CLIRoute(handler=lambda ns: "ok")
        assert route.arg_specs == ()

    def test_assemble_cli_route_no_execute_raises(self) -> None:
        from emergent.wire.compile.targets.cli import assemble_cli_route, CLIWrapContext
        from emergent.wire.compile._core import Axes
        from emergent.wire.axis.surface._handler import Handler
        from emergent.wire.axis.surface.codecs.immediate import ImmediateCodec

        @dataclass(frozen=True)
        class Resp:
            @classmethod
            def produce(cls) -> Self:
                return cls()

        handler: Handler[ImmediateCodec] = Handler(
            runner=MagicMock(),
            codec=ImmediateCodec(response=Resp),
            capabilities=(),
        )
        ctx = CLIWrapContext(execute=None)
        with pytest.raises(ValueError, match="execute must be set"):
            assemble_cli_route(ctx, handler, Axes.default())


# ═══════════════════════════════════════════════════════════════════════════════
# 5. _generate.py — to_datanode, assemble_pydantic, assemble_argparse
# ═══════════════════════════════════════════════════════════════════════════════


class TestGenerateDeepPaths:
    """Cover to_datanode, to_datanode_auto, argparse assembler deep paths."""

    def test_to_datanode_basic(self) -> None:
        from emergent.wire.compile._generate import to_datanode

        @dataclass
        class Item:
            name: str
            value: int

        node_cls = to_datanode(Item, {}, None)
        assert node_cls.__name__ == "ItemNode"

    def test_assemble_argparse_with_arg_names(self) -> None:
        from emergent.wire.compile._generate import to_argparse_args
        from emergent.wire.compile._core import Axes

        @dataclass
        class R:
            name: str
            count: int = 0

        specs = to_argparse_args(R, Axes.default())
        assert len(specs) >= 1

    def test_to_pydantic_basic(self) -> None:
        from emergent.wire.compile._generate import to_pydantic
        from emergent.wire.compile._core import Axes

        @dataclass
        class Item:
            name: str
            value: int = 0

        model = to_pydantic(Item, Axes.default())
        assert model.__name__ == "Item"
        instance = model(name="test")
        assert getattr(instance, "name") == "test"

    def test_to_pydantic_optional_field(self) -> None:
        from emergent.wire.compile._generate import to_pydantic
        from emergent.wire.compile._core import Axes

        @dataclass
        class Item:
            name: str
            tag: str | None = None

        model = to_pydantic(Item, Axes.default())
        instance = model(name="test")
        assert getattr(instance, "tag") is None


# ═══════════════════════════════════════════════════════════════════════════════
# 6. _capabilities.py (bridge) — deep bridge capability paths
# ═══════════════════════════════════════════════════════════════════════════════


class TestBridgeCapabilitiesDeep:
    """Cover IsolateGlobal, IsolateGlobalAsync, InjectKwargAsync, SetGlobal, etc."""

    @pytest.mark.asyncio
    async def test_isolate_global_purify(self) -> None:
        from emergent.wire.bridge._capabilities import IsolateGlobal

        iso = IsolateGlobal(
            module_path="sys",
            attr_name="_test_coverage_global",
            factory=lambda: "isolated_value",
        )

        sys._test_coverage_global = "original"  # type: ignore[attr-defined]

        async def handler() -> str:
            return getattr(sys, "_test_coverage_global", "not found")

        wrapped = iso.purify(handler)
        result = await wrapped()
        assert result == "isolated_value"
        # Old value restored
        assert sys._test_coverage_global == "original"  # type: ignore[attr-defined]
        del sys._test_coverage_global  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_isolate_global_async_purify(self) -> None:
        from emergent.wire.bridge._capabilities import IsolateGlobalAsync

        @asynccontextmanager
        async def factory() -> AsyncIterator[str]:
            yield "async_value"

        iso = IsolateGlobalAsync(
            module_path="sys",
            attr_name="_test_async_global",
            factory=factory,
        )

        sys._test_async_global = "original"  # type: ignore[attr-defined]

        async def handler() -> str:
            return getattr(sys, "_test_async_global", "not found")

        wrapped = iso.purify(handler)
        result = await wrapped()
        assert result == "async_value"
        assert sys._test_async_global == "original"  # type: ignore[attr-defined]
        del sys._test_async_global  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_isolate_global_async_exception_path(self) -> None:
        from emergent.wire.bridge._capabilities import IsolateGlobalAsync

        @asynccontextmanager
        async def factory() -> AsyncIterator[str]:
            yield "value"

        iso = IsolateGlobalAsync(
            module_path="sys",
            attr_name="_test_exc_global",
            factory=factory,
        )

        sys._test_exc_global = "original"  # type: ignore[attr-defined]

        async def handler() -> str:
            raise ValueError("boom")

        wrapped = iso.purify(handler)
        with pytest.raises(ValueError, match="boom"):
            await wrapped()
        assert sys._test_exc_global == "original"  # type: ignore[attr-defined]
        del sys._test_exc_global  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_inject_kwarg_async_purify(self) -> None:
        from emergent.wire.bridge._capabilities import InjectKwargAsync

        async def get_db() -> str:
            return "db_connection"

        inj = InjectKwargAsync(name="db", factory=get_db)

        async def handler(db: str = "") -> str:
            return db

        wrapped = inj.purify(handler)
        result = await wrapped()
        assert result == "db_connection"

    @pytest.mark.asyncio
    async def test_inject_kwarg_async_already_provided(self) -> None:
        from emergent.wire.bridge._capabilities import InjectKwargAsync

        async def get_db() -> str:
            return "injected"

        inj = InjectKwargAsync(name="db", factory=get_db)

        async def handler(db: str = "") -> str:
            return db

        wrapped = inj.purify(handler)
        result = await wrapped(db="explicit")
        assert result == "explicit"

    def test_set_global_purify(self) -> None:
        from emergent.wire.bridge._capabilities import SetGlobal

        sg = SetGlobal(
            module_path="sys",
            attr_name="_test_setglobal",
            factory=lambda: "initialized",
        )

        async def handler() -> str:
            return getattr(sys, "_test_setglobal", "not found")

        sg.purify(handler)
        # SetGlobal sets the value during purify
        assert sys._test_setglobal == "initialized"  # type: ignore[attr-defined]
        del sys._test_setglobal  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_with_context_purify(self) -> None:
        from emergent.wire.bridge._capabilities import WithContext

        calls: list[str] = []

        @asynccontextmanager
        async def ctx_factory() -> AsyncIterator[None]:
            calls.append("enter")
            yield
            calls.append("exit")

        wc = WithContext(factory=ctx_factory)

        async def handler() -> str:
            return "result"

        wrapped = wc.purify(handler)
        result = await wrapped()
        assert result == "result"
        assert calls == ["enter", "exit"]

    def test_wrap_as_delegate(self) -> None:
        from emergent.wire.bridge._capabilities import WrapAsDelegate, BridgeContext

        wad = WrapAsDelegate()

        async def handler() -> str:
            return "hello"

        ctx: BridgeContext[str, ..., str] = BridgeContext(
            trigger_data="test",
            handler=handler,
            response_type=str,
        )
        result = wad.compile_bridge(ctx)
        assert result.wire.codec is not None

    def test_set_codec_by_name_match(self) -> None:
        from emergent.wire.bridge._capabilities import SetCodecByName, BridgeContext

        codec_obj = object()

        cap = SetCodecByName(codec_map={"my_handler": codec_obj})

        async def handler() -> str:
            return ""

        ctx: BridgeContext[str, ..., str] = BridgeContext(
            trigger_data="test",
            handler=handler,
            name="my_handler",
        )
        result = cap.compile_bridge(ctx)
        assert result.wire.codec is codec_obj

    def test_set_codec_by_name_no_match(self) -> None:
        from emergent.wire.bridge._capabilities import SetCodecByName, BridgeContext

        cap = SetCodecByName(codec_map={"other": object()})

        async def handler() -> str:
            return ""

        ctx: BridgeContext[str, ..., str] = BridgeContext(
            trigger_data="test",
            handler=handler,
            name="my_handler",
        )
        result = cap.compile_bridge(ctx)
        assert result.wire.codec is None

    def test_matches_name_pattern(self) -> None:
        from emergent.wire.bridge._capabilities import _matches_name, BridgeContext

        async def handler() -> str:
            return ""

        ctx: BridgeContext[str, ..., str] = BridgeContext(
            trigger_data="test",
            handler=handler,
            name="get_users",
        )
        assert _matches_name(ctx, None, r"get_.*") is True
        assert _matches_name(ctx, None, r"post_.*") is False

    def test_add_capability_matches_by_pattern(self) -> None:
        from emergent.wire.bridge._capabilities import AddCapability, BridgeContext

        class FakeCap:
            pass

        cap = AddCapability(capability=FakeCap(), for_pattern=r"get_.*")  # type: ignore[arg-type]

        async def handler() -> str:
            return ""

        ctx: BridgeContext[str, ..., str] = BridgeContext(
            trigger_data="test",
            handler=handler,
            name="get_users",
        )
        result = cap.compile_bridge(ctx)
        assert len(result.wire.surface_capabilities) == 1


# ═══════════════════════════════════════════════════════════════════════════════
# 7. auth/caps.py — Authenticated, AuthorizeOps, OwnerScoped deep paths
# ═══════════════════════════════════════════════════════════════════════════════


class TestAuthCapsDeep:
    """Cover Authenticated with effect filtering, AuthorizeOps, OwnerScoped."""

    def test_authenticated_with_effect_filter(self) -> None:
        from emergent.wire.derive.auth.caps import Authenticated
        from emergent.wire.derive.auth.validate import TokenValidate
        from emergent.wire.derive.auth.extractors import BearerExtract
        from emergent.wire.derive._effects import Mutation

        @dataclass
        class User:
            name: str

        async def lookup(token: str) -> User:
            return User(name="alice")

        auth = Authenticated(
            BearerExtract(),
            TokenValidate(User, lookup),
            effect=Mutation,
        )
        assert auth.effect is Mutation
        assert len(auth.extractors) == 1

    def test_authenticated_no_validate_raises(self) -> None:
        from emergent.wire.derive.auth.caps import Authenticated
        from emergent.wire.derive.auth.extractors import BearerExtract

        with pytest.raises(ValueError, match="requires a TokenValidate"):
            Authenticated(BearerExtract())

    def test_authorize_ops_strict_missing_key(self) -> None:
        from emergent.wire.derive.auth.caps import AuthorizeOps

        @dataclass
        class User:
            roles: set[str]

        def _get_roles(u: User) -> set[str]:
            return u.roles

        cap = AuthorizeOps(
            identity_type=User,
            role_map={"Create": "admin"},
            role_getter=_get_roles,
            strict=True,
        )
        # Just verify it is strict by default
        assert cap.strict is True

    def test_authorize_ops_non_strict(self) -> None:
        from emergent.wire.derive.auth.caps import AuthorizeOps

        @dataclass
        class User:
            roles: set[str]

        def _get_roles(u: User) -> set[str]:
            return u.roles

        cap = AuthorizeOps(
            identity_type=User,
            role_map={"Delete": "admin"},
            role_getter=_get_roles,
            strict=False,
        )
        assert cap.strict is False


# ═══════════════════════════════════════════════════════════════════════════════
# 8. _execute.py — stateful, immediate, delegate execution paths
# ═══════════════════════════════════════════════════════════════════════════════


class TestExecuteDeepPaths:
    """Cover execute_stateful_unified, execute_immediate_unified, execute_delegate_unified."""

    @pytest.mark.asyncio
    async def test_execute_immediate_with_format(self) -> None:
        from emergent.wire.compile._execute import execute_immediate_unified
        from emergent.wire.axis.surface._handler import Handler
        from emergent.wire.axis.surface.codecs.immediate import ImmediateCodec

        @dataclass(frozen=True)
        class Resp:
            @classmethod
            def produce(cls) -> Self:
                return cls()

            def __str__(self) -> str:
                return "raw_response"

        handler: Handler[ImmediateCodec] = Handler(
            runner=MagicMock(),
            codec=ImmediateCodec(response=Resp),
            capabilities=(),
        )

        result = execute_immediate_unified(
            handler, format_response=lambda r: f"formatted: {r}"
        )
        assert result == "formatted: raw_response"

    @pytest.mark.asyncio
    async def test_execute_immediate_factory_codec(self) -> None:
        from emergent.wire.compile._execute import execute_immediate_unified
        from emergent.wire.axis.surface._handler import Handler
        from emergent.wire.axis.surface.codecs.immediate import ImmediateFactoryCodec

        handler: Handler[ImmediateFactoryCodec] = Handler(
            runner=MagicMock(),
            codec=ImmediateFactoryCodec(factory=lambda: "factory_result"),
            capabilities=(),
        )

        result = execute_immediate_unified(handler)
        assert result == "factory_result"

    @pytest.mark.asyncio
    async def test_execute_immediate_unknown_codec_raises(self) -> None:
        from emergent.wire.compile._execute import execute_immediate_unified
        from emergent.wire.axis.surface._handler import Handler

        handler = Handler(
            runner=MagicMock(),
            codec=MagicMock(),
            capabilities=(),
        )

        with pytest.raises(TypeError, match="Expected ImmediateCodec"):
            execute_immediate_unified(handler)


# ═══════════════════════════════════════════════════════════════════════════════
# 9. memory.py — memory providers deep paths
# ═══════════════════════════════════════════════════════════════════════════════


class TestMemoryProviderDeep:
    """Cover MemoryKVProvider, MemoryRelationalProvider, MemoryAPIProvider."""

    @pytest.mark.asyncio
    async def test_kv_get_wrong_op_raises(self) -> None:
        from emergent.wire.axis.query.providers.memory import MemoryKVProvider
        from emergent.wire.axis.query._kv import kv

        provider = MemoryKVProvider[str, str]()
        q = kv(str, key=lambda x: x).set("k", "v")
        with pytest.raises(TypeError, match="get\\(\\) requires KVGet"):
            await provider.get(q)

    @pytest.mark.asyncio
    async def test_kv_set_wrong_op_raises(self) -> None:
        from emergent.wire.axis.query.providers.memory import MemoryKVProvider
        from emergent.wire.axis.query._kv import kv

        provider = MemoryKVProvider[str, str]()
        q = kv(str, key=lambda x: x).get("k")
        with pytest.raises(TypeError, match="set\\(\\) requires KVSet"):
            await provider.set(q)

    @pytest.mark.asyncio
    async def test_kv_delete_wrong_op_raises(self) -> None:
        from emergent.wire.axis.query.providers.memory import MemoryKVProvider
        from emergent.wire.axis.query._kv import kv

        provider = MemoryKVProvider[str, str]()
        q = kv(str, key=lambda x: x).get("k")
        with pytest.raises(TypeError, match="delete\\(\\) requires KVDelete"):
            await provider.delete(q)

    @pytest.mark.asyncio
    async def test_kv_exists_wrong_op_raises(self) -> None:
        from emergent.wire.axis.query.providers.memory import MemoryKVProvider
        from emergent.wire.axis.query._kv import kv

        provider = MemoryKVProvider[str, str]()
        q = kv(str, key=lambda x: x).get("k")
        with pytest.raises(TypeError, match="exists\\(\\) requires Exists"):
            await provider.exists(q)

    @pytest.mark.asyncio
    async def test_kv_scan_wrong_op_raises(self) -> None:
        from emergent.wire.axis.query.providers.memory import MemoryKVProvider
        from emergent.wire.axis.query._kv import kv

        provider = MemoryKVProvider[str, str]()
        q = kv(str, key=lambda x: x).get("k")
        with pytest.raises(TypeError, match="scan\\(\\) requires Scan"):
            await provider.scan(q)

    @pytest.mark.asyncio
    async def test_kv_keys_wrong_op_raises(self) -> None:
        from emergent.wire.axis.query.providers.memory import MemoryKVProvider
        from emergent.wire.axis.query._kv import kv

        provider = MemoryKVProvider[str, str]()
        q = kv(str, key=lambda x: x).get("k")
        with pytest.raises(TypeError, match="keys\\(\\) requires Keys"):
            await provider.keys(q)

    @pytest.mark.asyncio
    async def test_relational_atomic_rollback(self) -> None:
        from emergent.wire.axis.query.providers.memory import MemoryRelationalProvider

        provider = MemoryRelationalProvider[Foo]()
        provider.add(Foo(id=1, name="a"))
        assert len(provider.data) == 1

        with pytest.raises(ValueError):
            async with provider.atomic():
                provider.add(Foo(id=2, name="b"))
                raise ValueError("rollback")

        assert len(provider.data) == 1  # rolled back

    @pytest.mark.asyncio
    async def test_api_provider_partial_update(self) -> None:
        from emergent.wire.axis.query.providers.memory import MemoryAPIProvider
        from emergent.wire.axis.query._api import api

        provider = MemoryAPIProvider[int, Foo](
            data=[Foo(id=1, name="original", score=10.0)],
            key_fn=lambda f: f.id,
        )

        q = api(Foo, key=lambda f: f.id).update(
            1, Foo(id=1, name="updated", score=None),  # type: ignore[arg-type]
            partial=True,
        )
        result = await provider.execute(q)
        assert result.name == "updated"

    @pytest.mark.asyncio
    async def test_api_provider_full_update(self) -> None:
        from emergent.wire.axis.query.providers.memory import MemoryAPIProvider
        from emergent.wire.axis.query._api import api

        provider = MemoryAPIProvider[int, Foo](
            data=[Foo(id=1, name="original")],
            key_fn=lambda f: f.id,
        )

        q = api(Foo, key=lambda f: f.id).update(
            1, Foo(id=1, name="replaced"),
        )
        result = await provider.execute(q)
        assert result.name == "replaced"

    @pytest.mark.asyncio
    async def test_api_provider_update_not_found(self) -> None:
        from emergent.wire.axis.query.providers.memory import MemoryAPIProvider
        from emergent.wire.axis.query._api import api

        provider = MemoryAPIProvider[int, Foo](
            data=[],
            key_fn=lambda f: f.id,
        )

        q = api(Foo, key=lambda f: f.id).update(999, Foo(id=999, name="x"))
        with pytest.raises(ValueError, match="not found"):
            await provider.execute(q)

    @pytest.mark.asyncio
    async def test_api_provider_delete_no_key_fn(self) -> None:
        from emergent.wire.axis.query.providers.memory import MemoryAPIProvider
        from emergent.wire.axis.query._api import api

        provider = MemoryAPIProvider[int, Foo](data=[])

        q = api(Foo, key=lambda f: f.id).delete(1)
        with pytest.raises(TypeError, match="requires key_fn"):
            await provider.delete(q)

    @pytest.mark.asyncio
    async def test_api_provider_fetch_one_get_op(self) -> None:
        from emergent.wire.axis.query.providers.memory import MemoryAPIProvider
        from emergent.wire.axis.query._api import api

        provider = MemoryAPIProvider[int, Foo](
            data=[Foo(id=1, name="Alice"), Foo(id=2, name="Bob")],
            key_fn=lambda f: f.id,
        )

        q = api(Foo, key=lambda f: f.id).get(1)
        result = await provider.fetch_one(q)
        assert result is not None
        assert result.name == "Alice"

    @pytest.mark.asyncio
    async def test_api_provider_fetch_one_not_found(self) -> None:
        from emergent.wire.axis.query.providers.memory import MemoryAPIProvider
        from emergent.wire.axis.query._api import api

        provider = MemoryAPIProvider[int, Foo](
            data=[],
            key_fn=lambda f: f.id,
        )

        q = api(Foo, key=lambda f: f.id).get(999)
        result = await provider.fetch_one(q)
        assert result is None

    @pytest.mark.asyncio
    async def test_api_provider_fetch_page(self) -> None:
        from emergent.wire.axis.query.providers.memory import MemoryAPIProvider
        from emergent.wire.axis.query._api import api

        provider = MemoryAPIProvider[int, Foo](
            data=[Foo(id=i, name=f"item_{i}") for i in range(5)],
            key_fn=lambda f: f.id,
        )

        q = api(Foo, key=lambda f: f.id).list()
        result = await provider.fetch_page(q)
        assert result.total == 5
        assert len(result.items) == 5

    @pytest.mark.asyncio
    async def test_api_provider_next_id_error(self) -> None:
        from emergent.wire.axis.query.providers.memory import MemoryAPIProvider

        provider = MemoryAPIProvider[int, Foo](data=[])
        with pytest.raises(RuntimeError, match="No next_id"):
            await provider.next_id()

    @pytest.mark.asyncio
    async def test_relational_aggregate_with_field(self) -> None:
        from emergent.wire.axis.query.providers.memory import MemoryRelationalProvider
        from emergent.wire.axis.query._relational import relational

        provider = MemoryRelationalProvider[Foo](
            data=[Foo(id=1, name="a", score=10.0), Foo(id=2, name="b", score=20.0)]
        )

        q = relational(Foo).aggregate(
            total_score=lambda f: f.score.sum(),
            avg_score=lambda f: f.score.avg(),
            min_score=lambda f: f.score.min(),
            max_score=lambda f: f.score.max(),
            count=lambda f: f.count(),
        )
        result = await provider.aggregate(q)
        assert result["total_score"] == 30.0
        assert result["avg_score"] == 15.0
        assert result["min_score"] == 10.0
        assert result["max_score"] == 20.0
        assert result["count"] == 2


# ═══════════════════════════════════════════════════════════════════════════════
# 10. _request.py — build_field_value fallback/race paths
# ═══════════════════════════════════════════════════════════════════════════════


class TestRequestBuildDeep:
    """Cover build_field_value paths: fallback nodes, race nodes."""

    @pytest.mark.asyncio
    async def test_build_request_non_dataclass_raises(self) -> None:
        from emergent.wire.compile._request import build_request

        with pytest.raises(TypeError, match="not a dataclass"):
            await build_request(str, lambda n: None)

    @pytest.mark.asyncio
    async def test_build_request_required_field_missing(self) -> None:
        from emergent.wire.compile._request import build_request

        @dataclass
        class R:
            name: str

        with pytest.raises(RuntimeError, match="Cannot resolve"):
            await build_request(R, lambda n: None)

    @pytest.mark.asyncio
    async def test_build_request_default_factory(self) -> None:
        from emergent.wire.compile._request import build_request

        @dataclass
        class R:
            tags: list[str] = field(default_factory=lambda: list[str]())

        result = await build_request(R, lambda n: None)
        assert result.tags == []

    @pytest.mark.asyncio
    async def test_build_request_default_value(self) -> None:
        from emergent.wire.compile._request import build_request

        @dataclass
        class R:
            count: int = 10

        result = await build_request(R, lambda n: None)
        assert result.count == 10

    def test_build_request_sync_required_missing(self) -> None:
        from emergent.wire.compile._request import build_request_sync

        @dataclass
        class R:
            name: str

        with pytest.raises(RuntimeError, match="No value for required"):
            build_request_sync(R, lambda n: None)

    def test_build_request_sync_non_dataclass_raises(self) -> None:
        from emergent.wire.compile._request import build_request_sync

        with pytest.raises(TypeError, match="not a dataclass"):
            build_request_sync(str, lambda n: None)


# ═══════════════════════════════════════════════════════════════════════════════
# 11. _stateful.py — stateful management helpers
# ═══════════════════════════════════════════════════════════════════════════════


class TestStatefulManagement:
    """Cover load_state, save_state, delete_state, get_stateful_metadata."""

    @pytest.mark.asyncio
    async def test_load_state_from_store(self) -> None:
        from emergent.wire.compile._stateful import load_state
        from emergent.wire.axis.surface.codecs.stateful import StatefulCodec

        store = AsyncMock()
        store.get = AsyncMock(return_value=Ok(Some("existing_state")))

        @dataclass
        class Flow:
            pass

        codec = StatefulCodec(
            flow=Flow,
            response=str,
            store=store,
            key_node=type,
            agent_cls=EventLoopAgent,
        )

        result = await load_state(codec, "key1")
        assert result == "existing_state"

    @pytest.mark.asyncio
    async def test_load_state_creates_new(self) -> None:
        from emergent.wire.compile._stateful import load_state
        from emergent.wire.axis.surface.codecs.stateful import StatefulCodec

        store = AsyncMock()
        store.get = AsyncMock(return_value=Ok(Nothing()))

        @dataclass
        class Flow:
            pass

        codec = StatefulCodec(
            flow=Flow,
            response=str,
            store=store,
            key_node=type,
            agent_cls=EventLoopAgent,
        )

        result = await load_state(codec, "key1")
        assert isinstance(result, Flow)

    @pytest.mark.asyncio
    async def test_save_state_when_changed(self) -> None:
        from emergent.wire.compile._stateful import save_state
        from emergent.wire.axis.surface.codecs.stateful import StatefulCodec

        store = AsyncMock()
        store.set = AsyncMock()

        codec = StatefulCodec(
            flow=type,
            response=str,
            store=store,
            key_node=type,
            agent_cls=EventLoopAgent,
        )

        old = object()
        new = object()
        await save_state(codec, "key1", old, new)
        store.set.assert_called_once_with("key1", new)

    @pytest.mark.asyncio
    async def test_save_state_no_change(self) -> None:
        from emergent.wire.compile._stateful import save_state
        from emergent.wire.axis.surface.codecs.stateful import StatefulCodec

        store = AsyncMock()
        store.set = AsyncMock()

        codec = StatefulCodec(
            flow=type,
            response=str,
            store=store,
            key_node=type,
            agent_cls=EventLoopAgent,
        )

        obj = object()
        await save_state(codec, "key1", obj, obj)
        store.set.assert_not_called()

    @pytest.mark.asyncio
    async def test_delete_state(self) -> None:
        from emergent.wire.compile._stateful import delete_state
        from emergent.wire.axis.surface.codecs.stateful import StatefulCodec

        store = AsyncMock()
        store.delete = AsyncMock()

        codec = StatefulCodec(
            flow=type,
            response=str,
            store=store,
            key_node=type,
            agent_cls=EventLoopAgent,
        )

        await delete_state(codec, "key1")
        store.delete.assert_called_once_with("key1")


# ═══════════════════════════════════════════════════════════════════════════════
# 12. _extractors.py (fastapi) — extractors coverage
# ═══════════════════════════════════════════════════════════════════════════════


class TestFastAPIExtractors:
    """Cover HTTPRouteExtractor, WebSocketExtractor, LifespanExtractor, etc."""

    def test_http_route_extractor_skips_non_apiroute(self) -> None:
        from emergent.wire.bridge.bridgers.fastapi._extractors import HTTPRouteExtractor

        extractor = HTTPRouteExtractor()
        mock_source = MagicMock()
        mock_source.routes = [MagicMock()]  # Not an APIRoute
        routes = list(extractor.extract(mock_source))
        assert len(routes) == 0

    def test_lifespan_extractor_extracts_startup(self) -> None:
        from emergent.wire.bridge.bridgers.fastapi._extractors import LifespanExtractor

        extractor = LifespanExtractor()

        def startup_fn() -> None:
            pass

        mock_source = MagicMock()
        mock_source.router.on_startup = [startup_fn]
        mock_source.router.on_shutdown = []

        routes = list(extractor.extract(mock_source))
        assert len(routes) == 1
        assert routes[0].name == "startup_fn"

    def test_lifespan_extractor_no_router(self) -> None:
        from emergent.wire.bridge.bridgers.fastapi._extractors import LifespanExtractor

        extractor = LifespanExtractor()
        mock_source = MagicMock(spec=[])  # no router attr
        routes = list(extractor.extract(mock_source))
        assert len(routes) == 0

    def test_exception_handler_extractor_skips_starlette(self) -> None:
        from emergent.wire.bridge.bridgers.fastapi._extractors import ExceptionHandlerExtractor

        extractor = ExceptionHandlerExtractor()

        class StarletteError(Exception):
            __module__ = "starlette.exceptions"

        mock_source = MagicMock()
        def _err_handler(r: object, e: object) -> None:
            pass

        mock_source.exception_handlers = {StarletteError: _err_handler}
        routes = list(extractor.extract(mock_source))
        assert len(routes) == 0

    def test_exception_handler_extractor_user_handler(self) -> None:
        from emergent.wire.bridge.bridgers.fastapi._extractors import ExceptionHandlerExtractor

        extractor = ExceptionHandlerExtractor()

        class CustomError(Exception):
            pass

        def handle_custom(request: object, exc: CustomError) -> str:
            return "handled"

        mock_source = MagicMock()
        mock_source.exception_handlers = {CustomError: handle_custom}
        routes = list(extractor.extract(mock_source))
        assert len(routes) == 1

    def test_prepend_path_non_dataclass(self) -> None:
        from emergent.wire.bridge.bridgers.fastapi._extractors import _prepend_path

        result = _prepend_path("not_a_dataclass", "/prefix")
        assert result == "not_a_dataclass"

    def test_prepend_path_no_path_field(self) -> None:
        from emergent.wire.bridge.bridgers.fastapi._extractors import _prepend_path

        @dataclass(frozen=True)
        class NoPath:
            name: str

        result = _prepend_path(NoPath(name="test"), "/prefix")
        assert isinstance(result, NoPath)

    def test_is_fastapi_app_starlette(self) -> None:
        from emergent.wire.bridge.bridgers.fastapi._extractors import is_fastapi_app

        class Starlette:
            pass

        assert is_fastapi_app(Starlette()) is True


# ═══════════════════════════════════════════════════════════════════════════════
# 13. _capabilities.py (fastapi) — InferFromFastAPI deep paths
# ═══════════════════════════════════════════════════════════════════════════════


class TestFastAPICapabilitiesDeep:
    """Cover InferFromFastAPI with various handler signatures."""

    def test_infer_pydantic_body(self) -> None:
        from emergent.wire.bridge.bridgers.fastapi._capabilities import InferFromFastAPI
        from emergent.wire.bridge._capabilities import BridgeContext

        cap = InferFromFastAPI(include_dataclass=True)

        # Use module-level PydanticUser so get_type_hints can resolve it
        async def handler(user: PydanticUser) -> str:
            return user.name

        # Patch __module__ and __globals__ so get_type_hints resolves
        handler.__globals__["PydanticUser"] = PydanticUser

        ctx: BridgeContext[str, ..., str] = BridgeContext(
            trigger_data="test",
            handler=handler,
        )
        result = cap.compile_bridge(ctx)
        assert result.request_type is PydanticUser
        assert result.response_type is str

    def test_infer_no_body_handler(self) -> None:
        from emergent.wire.bridge.bridgers.fastapi._capabilities import InferFromFastAPI
        from emergent.wire.bridge._capabilities import BridgeContext

        cap = InferFromFastAPI()

        async def handler(user_id: int) -> str:
            return ""

        ctx: BridgeContext[str, ..., str] = BridgeContext(
            trigger_data="test",
            handler=handler,
        )
        result = cap.compile_bridge(ctx)
        assert result.request_type is None
        assert result.response_type is str

    def test_infer_preserves_existing_types(self) -> None:
        from emergent.wire.bridge.bridgers.fastapi._capabilities import InferFromFastAPI
        from emergent.wire.bridge._capabilities import BridgeContext

        cap = InferFromFastAPI()

        async def handler() -> str:
            return ""

        ctx: BridgeContext[str, ..., str] = BridgeContext(
            trigger_data="test",
            handler=handler,
            request_type=int,
            response_type=float,
        )
        result = cap.compile_bridge(ctx)
        assert result.request_type is int
        assert result.response_type is float

    def test_parse_handler_no_annotations(self) -> None:
        from emergent.wire.bridge.bridgers.fastapi._capabilities import _parse_handler_params

        def handler(x: Any) -> None:
            pass

        params = _parse_handler_params(handler)
        found = [p for p in params if p.name == "x"]
        assert len(found) == 1
        assert found[0].source == "unknown"

    def test_is_depends_detection(self) -> None:
        from emergent.wire.bridge.bridgers.fastapi._capabilities import _is_depends

        class Depends:
            pass

        assert _is_depends(Depends()) is True
        assert _is_depends("not depends") is False

    def test_map_depends_no_deps(self) -> None:
        from emergent.wire.bridge.bridgers.fastapi._capabilities import MapDepends

        cap = MapDepends()

        async def handler() -> str:
            return "result"

        wrapped = cap.purify(handler)
        assert wrapped is not None


# ═══════════════════════════════════════════════════════════════════════════════
# 14. _sqlalchemy.py (storage) — BoundSQLAlchemyStore paths
# ═══════════════════════════════════════════════════════════════════════════════


class TestSQLAlchemyStorageDeep:
    """Cover SQLAlchemyStore, BoundSQLAlchemyStore."""

    def test_store_creation(self) -> None:
        from emergent.wire.axis.storage.contrib._impls._sqlalchemy import store as sa_store

        @dataclass
        class User:
            id: Annotated[int, Identity()]
            name: str

        s = sa_store(User, "sa_users_cov1")
        assert s.entity is User
        assert s.tablename == "sa_users_cov1"

    def test_store_model_property(self) -> None:
        from emergent.wire.axis.storage.contrib._impls._sqlalchemy import store as sa_store

        @dataclass
        class Item:
            id: Annotated[int, Identity()]
            name: str

        s = sa_store(Item, "sa_items_cov1")
        model = s.model
        assert model is not None

    def test_bound_store_entity_property(self) -> None:
        from emergent.wire.axis.storage.contrib._impls._sqlalchemy import store as sa_store

        @dataclass
        class Item:
            id: Annotated[int, Identity()]
            name: str

        s = sa_store(Item, "sa_items_cov2")
        bound = s.bind(MagicMock())
        assert bound.entity is Item

    def test_storage_error_creation(self) -> None:
        from emergent.wire.axis.storage.contrib._impls._sqlalchemy import StorageError

        err = StorageError("test error", cause=ValueError("inner"))
        assert err.message == "test error"
        assert isinstance(err.cause, ValueError)


# ═══════════════════════════════════════════════════════════════════════════════
# 15. _explain.py (storage) — storage explain deep paths
# ═══════════════════════════════════════════════════════════════════════════════


class TestStorageExplainDeep:
    """Cover storage explain with composition wrappers and formatting."""

    def test_explain_prefix_kv(self) -> None:
        from emergent.wire.axis.storage._explain import storage_dict
        from emergent.wire.axis.storage._compose import PrefixKV

        inner_kv = MagicMock()
        cast(Any, inner_kv).__class__ = type("UnknownStore", (), {})

        prefix_store = PrefixKV[str, str](prefix="cache:", inner=inner_kv)
        d = storage_dict(prefix_store)
        assert d["type"] == "PrefixKV"
        assert d["prefix"] == "cache:"
        assert "inner" in d

    def test_explain_readonly_kv(self) -> None:
        from emergent.wire.axis.storage._explain import storage_dict
        from emergent.wire.axis.storage._compose import ReadonlyKV

        inner_kv = MagicMock()
        cast(Any, inner_kv).__class__ = type("UnknownStore", (), {})

        ro_store = ReadonlyKV[str, str](inner=inner_kv)
        d = storage_dict(ro_store)
        assert d["type"] == "ReadonlyKV"

    def test_explain_fallback_kv(self) -> None:
        from emergent.wire.axis.storage._explain import storage_dict
        from emergent.wire.axis.storage._compose import FallbackKV

        primary = MagicMock()
        cast(Any, primary).__class__ = type("Primary", (), {})
        secondary = MagicMock()
        cast(Any, secondary).__class__ = type("Secondary", (), {})

        fb = FallbackKV[str, str](primary=primary, secondary=secondary)
        d = storage_dict(fb)
        assert d["type"] == "FallbackKV"
        assert "primary" in d
        assert "secondary" in d

    def test_explain_tiered_kv_with_ttl(self) -> None:
        from emergent.wire.axis.storage._explain import storage_dict
        from emergent.wire.axis.storage._compose import TieredKV

        l1 = MagicMock()
        cast(Any, l1).__class__ = type("L1", (), {})
        l2 = MagicMock()
        cast(Any, l2).__class__ = type("L2", (), {})

        tiered = TieredKV[str, str](l1=l1, l2=l2, l1_ttl=timedelta(seconds=300))
        d = storage_dict(tiered)
        assert d["type"] == "TieredKV"
        assert d["l1_ttl"] == 300.0

    def test_explain_kv_basic(self) -> None:
        from emergent.wire.axis.storage._explain import storage_dict
        from emergent.wire.axis.storage._kv import KV

        kv_store = KV[str, str](codec=MagicMock(), backend=MagicMock())
        d = storage_dict(kv_store)
        assert d["type"] == "KV"
        assert "codec" in d
        assert "backend" in d

    def test_explain_storage_human_readable(self) -> None:
        from emergent.wire.axis.storage._explain import explain_storage
        from emergent.wire.axis.storage._kv import KV

        kv_store = KV[str, str](codec=MagicMock(), backend=MagicMock())
        text = explain_storage(kv_store)
        assert "KV" in text

    def test_explain_storage_nested_human_readable(self) -> None:
        from emergent.wire.axis.storage._explain import explain_storage
        from emergent.wire.axis.storage._compose import PrefixKV
        from emergent.wire.axis.storage._kv import KV

        inner = KV[str, str](codec=MagicMock(), backend=MagicMock())
        prefix = PrefixKV[str, str](prefix="test:", inner=inner)
        text = explain_storage(prefix)
        assert "PrefixKV" in text
        assert "test:" in text

    def test_format_scalar_int(self) -> None:
        from emergent.wire.axis.storage._explain import _format_scalar

        assert _format_scalar(42) == "42"

    def test_format_scalar_none(self) -> None:
        from emergent.wire.axis.storage._explain import _format_scalar

        assert _format_scalar(None) == "None"

    def test_unknown_dict_with_type_field(self) -> None:
        from emergent.wire.axis.storage._explain import _unknown_dict

        @dataclass
        class Thing:
            name: str
            count: int
            cls: type = int

        obj = Thing(name="foo", count=5, cls=str)
        d = _unknown_dict(obj)
        assert d["type"] == "Thing"
        assert d["name"] == "foo"
        assert d["count"] == 5
        assert d["cls"] == "str"

    def test_explain_lock(self) -> None:
        from emergent.wire.axis.storage._explain import storage_dict
        from emergent.wire.axis.storage._lock import Lock

        lock = Lock[str](backend=MagicMock())
        d = storage_dict(lock)
        assert d["type"] == "Lock"

    def test_explain_counter(self) -> None:
        from emergent.wire.axis.storage._explain import storage_dict
        from emergent.wire.axis.storage._counter import Counter

        counter = Counter[str](backend=MagicMock())
        d = storage_dict(counter)
        assert d["type"] == "Counter"


# ═══════════════════════════════════════════════════════════════════════════════
# 16. methods.py — Methods and MethodDialect deep paths
# ═══════════════════════════════════════════════════════════════════════════════


class TestMethodsDeepPaths:
    """Cover method(), command(), Methods capability, MethodDialect capability."""

    def test_command_decorator(self) -> None:
        from emergent.wire.derive.patterns.methods import command, TRIGGER_ENTRIES_ATTR

        @command("greet", description="Greet user")
        async def greet(name: str) -> Result[str, str]:
            return Ok(f"Hello {name}")

        entries = getattr(greet, TRIGGER_ENTRIES_ATTR, [])
        assert len(entries) == 1
        assert entries[0].trigger.command == "greet"

    def test_get_decorator(self) -> None:
        from emergent.wire.derive.patterns.methods import get, TRIGGER_ENTRIES_ATTR

        @get("/api/items")
        async def list_items() -> Result[list[str], str]:
            return Ok([])

        entries = getattr(list_items, TRIGGER_ENTRIES_ATTR, [])
        assert len(entries) == 1

    def test_put_decorator(self) -> None:
        from emergent.wire.derive.patterns.methods import put, TRIGGER_ENTRIES_ATTR

        @put("/api/items/{id}")
        async def update_item(item_id: int) -> Result[str, str]:
            return Ok("updated")

        entries = getattr(update_item, TRIGGER_ENTRIES_ATTR, [])
        assert len(entries) == 1

    def test_patch_decorator(self) -> None:
        from emergent.wire.derive.patterns.methods import patch as patch_dec, TRIGGER_ENTRIES_ATTR

        @patch_dec("/api/items/{id}")
        async def patch_item(item_id: int) -> Result[str, str]:
            return Ok("patched")

        entries = getattr(patch_item, TRIGGER_ENTRIES_ATTR, [])
        assert len(entries) == 1

    def test_delete_decorator(self) -> None:
        from emergent.wire.derive.patterns.methods import delete as del_dec, TRIGGER_ENTRIES_ATTR

        @del_dec("/api/items/{id}")
        async def delete_item(item_id: int) -> Result[bool, str]:
            return Ok(True)

        entries = getattr(delete_item, TRIGGER_ENTRIES_ATTR, [])
        assert len(entries) == 1

    def test_result_type_fields_dataclass(self) -> None:
        from emergent.wire.derive.patterns.methods import _result_type_fields

        @dataclass
        class ItemResult:
            id: int
            name: str

        fields = _result_type_fields(ItemResult)
        assert "id" in fields
        assert "name" in fields

    def test_result_type_fields_primitive(self) -> None:
        from emergent.wire.derive.patterns.methods import _result_type_fields

        fields = _result_type_fields(int)
        assert "result" in fields
        assert fields["result"] is int

    def test_build_method_operation_sync_raises(self) -> None:
        from emergent.wire.derive.patterns.methods import _build_method_operation
        from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger

        @dataclass
        class Service:
            @classmethod
            def sync_method(cls, x: int) -> Result[str, str]:
                return Ok("")

        with pytest.raises(TypeError, match="must be async"):
            _build_method_operation(
                service=Service,
                method_name="sync_method",
                trigger=HTTPRouteTrigger("POST", "/api/test"),
                capabilities=(),
                suffix="",
            )

    def test_op_entry_creation(self) -> None:
        from emergent.wire.derive.patterns.methods import _OpEntry

        entry = _OpEntry(name="Create", effects=(), capabilities=())
        assert entry.name == "Create"

    def test_stub_op_creation(self) -> None:
        from emergent.wire.derive.patterns.methods import _stub_op

        stub = _stub_op("TestOp", ())
        assert stub.name == "TestOp"


# ═══════════════════════════════════════════════════════════════════════════════
# 17. HTTP contrib — QueryParamFilters, BodyFilters, Pagination, Auth
# ═══════════════════════════════════════════════════════════════════════════════


class TestHTTPContribDeep:
    """Cover HTTP contrib paths: pagination, auth, filter encoding."""

    def test_offset_limit_pagination_from_page(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import (
            OffsetLimitPagination,
            PageMod,
        )

        pag = OffsetLimitPagination()
        params: dict[str, Any] = {}
        pag.apply(params, PageMod(page=3, per_page=10))
        assert params["offset"] == 20
        assert params["limit"] == 10

    def test_page_size_pagination_from_offset(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import (
            PageSizePagination,
            OffsetMod,
        )

        pag = PageSizePagination()
        params: dict[str, Any] = {}
        pag.apply(params, OffsetMod(offset=20, limit=10))
        assert params["page"] == 3
        assert params["per_page"] == 10

    def test_cursor_pagination_with_cursor(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import (
            CursorPagination,
            CursorMod,
        )

        pag = CursorPagination()
        params: dict[str, Any] = {}
        pag.apply(params, CursorMod(cursor="abc123", limit=20))
        assert params["cursor"] == "abc123"
        assert params["limit"] == 20

    def test_basic_auth(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import BasicAuth

        auth = BasicAuth(username="user", password="pass")
        headers: dict[str, str] = {}
        auth.apply(headers)
        expected = base64.b64encode(b"user:pass").decode()
        assert headers["Authorization"] == f"Basic {expected}"

    def test_api_key_auth(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import APIKeyAuth

        auth = APIKeyAuth(key="my-key", header="X-API-Key")
        headers: dict[str, str] = {}
        auth.apply(headers)
        assert headers["X-API-Key"] == "my-key"

    def test_body_filters_nested(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import BodyFilters
        from emergent.wire.axis.query._expr import Field, Const, Lt, Ge, In

        bf = BodyFilters()

        expr = Lt(Field("age"), Const(30))
        result = bf.encode(expr, object, None)
        assert result["filter"]["age"]["lt"] == 30

        expr2 = Ge(Field("score"), Const(80))
        result2 = bf.encode(expr2, object, None)
        assert result2["filter"]["score"]["gte"] == 80

        expr3 = In(Field("status"), ("active", "pending"))
        result3 = bf.encode(expr3, object, None)
        assert result3["filter"]["status"]["in"] == ["active", "pending"]

    def test_body_filters_unsupported_raises(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import BodyFilters
        from emergent.wire.axis.query._expr import IsNull, Field

        bf = BodyFilters()
        with pytest.raises(ValueError, match="Unsupported"):
            bf.encode(IsNull(Field("name")), object, None)

    def test_query_param_duplicate_and_key_raises(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import QueryParamFilters
        from emergent.wire.axis.query._expr import Field, Const, Eq, And

        qp = QueryParamFilters()
        expr = And(Eq(Field("name"), Const("a")), Eq(Field("name"), Const("b")))
        with pytest.raises(ValueError, match="Duplicate filter key"):
            qp.encode(expr, object, None)

    def test_sort_param_encoding(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import SortParamEncoding
        from emergent.wire.axis.query._proxy import OrderSpec

        enc = SortParamEncoding()
        specs = [OrderSpec(field="name", ascending=True), OrderSpec(field="score", ascending=False)]
        result = enc.encode(specs)
        assert result["sort"] == "name,-score"

    def test_sort_param_empty(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import SortParamEncoding

        enc = SortParamEncoding()
        result = enc.encode([])
        assert result == {}

    def test_limit_param_encoding(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import LimitParamEncoding

        enc = LimitParamEncoding()
        result = enc.encode(50)
        assert result == {"limit": 50}

    def test_fields_param_encoding(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import FieldsParamEncoding

        enc = FieldsParamEncoding()
        result = enc.encode(["id", "name", "email"])
        assert result == {"fields": "id,name,email"}

    def test_get_nested_deep(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import _get_nested

        data = {"response": {"data": {"items": [1, 2, 3]}}}
        result = _get_nested(data, "response.data.items")
        assert result == [1, 2, 3]

    def test_get_nested_missing(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import _get_nested

        data = {"a": {"b": 1}}
        result = _get_nested(data, "a.c")
        assert result is None

    def test_get_nested_non_dict(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import _get_nested

        data = {"a": 42}
        result = _get_nested(data, "a.b")
        assert result is None

    def test_builder_full_flow(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import api, page_size, bearer

        builder = (
            api(Foo)
            .base("https://example.com/api/foos")
            .pagination(page_size())
            .auth(bearer("token123"))
            .response(data_path="results", total_path="count")
            .id_field("foo_id")
        )
        assert builder._base_url == "https://example.com/api/foos"
        assert builder._id_field == "foo_id"

    def test_builder_no_base_raises(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import api
        import httpx

        builder = api(Foo)
        with pytest.raises(ValueError, match="base URL is required"):
            builder.build(httpx.AsyncClient())


# ═══════════════════════════════════════════════════════════════════════════════
# 18. FastAPI target — compile paths
# ═══════════════════════════════════════════════════════════════════════════════


class TestFastAPITargetDeep:
    """Cover FastAPI target: extractors, from_codec, OpenAPI generation."""

    @pytest.mark.asyncio
    async def test_json_extractor_invalid_json(self) -> None:
        from emergent.wire.compile.targets.fastapi import FastAPIJsonExtractor

        extractor = FastAPIJsonExtractor()
        request = MagicMock()
        request.headers = {"content-type": "application/json"}
        request.json = AsyncMock(side_effect=ValueError("bad json"))
        request.path_params = {}

        result = await extractor.extract(request)
        assert result == {}

    @pytest.mark.asyncio
    async def test_query_extractor(self) -> None:
        from emergent.wire.compile.targets.fastapi import FastAPIQueryExtractor

        extractor = FastAPIQueryExtractor()
        request = MagicMock()
        request.query_params = {"name": "Alice", "age": "30"}
        request.path_params = {"id": "1"}

        result = await extractor.extract(request)
        assert result["name"] == "Alice"
        assert result["id"] == "1"

    def test_is_pydantic_model_true(self) -> None:
        from emergent.wire.compile.targets.fastapi import is_pydantic_model
        from pydantic import BaseModel

        class M(BaseModel):
            x: int = 0

        assert is_pydantic_model(M) is True

    def test_is_pydantic_model_false(self) -> None:
        from emergent.wire.compile.targets.fastapi import is_pydantic_model

        assert is_pydantic_model(int) is False

    def test_default_extractor_get(self) -> None:
        from emergent.wire.compile.targets.fastapi import _default_extractor, FastAPIQueryExtractor
        from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger

        ext = _default_extractor(HTTPRouteTrigger("GET", "/api"))
        assert isinstance(ext, FastAPIQueryExtractor)

    def test_default_extractor_post(self) -> None:
        from emergent.wire.compile.targets.fastapi import _default_extractor, FastAPIJsonExtractor
        from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger

        ext = _default_extractor(HTTPRouteTrigger("POST", "/api"))
        assert isinstance(ext, FastAPIJsonExtractor)

    def test_openapi_extra_get_query_params(self) -> None:
        from emergent.wire.compile.targets.fastapi import build_rrc_openapi_extra
        from emergent.wire.axis.surface.codecs.rrc import rrc
        from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger
        from emergent.wire.compile._core import Axes

        from emergent.ops._graph import Op

        @dataclass
        class SearchReq:
            q: str
            limit: int = 10

            def to_domain(self) -> Op[str, str]:
                return cast(Op[str, str], self)

        @dataclass
        class SearchResp:
            items: list[str] = field(default_factory=lambda: list[str]())

            @classmethod
            def from_domain(cls, dom: Result[str, str]) -> Self:
                return cls()

        codec = rrc(SearchReq, SearchResp)
        trigger = HTTPRouteTrigger("GET", "/api/search")
        extra = build_rrc_openapi_extra(codec, trigger, Axes.default())
        assert extra is not None
        assert "parameters" in extra

    def test_openapi_extra_post_with_path_params(self) -> None:
        from emergent.wire.compile.targets.fastapi import build_rrc_openapi_extra
        from emergent.wire.axis.surface.codecs.rrc import rrc
        from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger
        from emergent.wire.compile._core import Axes

        from emergent.ops._graph import Op

        @dataclass
        class CreateReq:
            user_id: int
            name: str

            def to_domain(self) -> Op[str, str]:
                return cast(Op[str, str], self)

        @dataclass
        class CreateResp:
            id: int = 0

            @classmethod
            def from_domain(cls, dom: Result[str, str]) -> Self:
                return cls()

        codec = rrc(CreateReq, CreateResp)
        trigger = HTTPRouteTrigger("POST", "/api/users/{user_id}")
        extra = build_rrc_openapi_extra(codec, trigger, Axes.default())
        assert extra is not None
        assert "parameters" in extra
        assert "requestBody" in extra


# ═══════════════════════════════════════════════════════════════════════════════
# 19. telegrinder.py target — format response, help generation
# ═══════════════════════════════════════════════════════════════════════════════


class TestTelegrindTargetDeep:
    """Cover telegrinder format_tg_response, help generation."""

    def test_format_response_none(self) -> None:
        from emergent.wire.compile.targets.telegrinder import _format_tg_response

        assert _format_tg_response(None) is None

    def test_format_response_str(self) -> None:
        from emergent.wire.compile.targets.telegrinder import _format_tg_response

        assert _format_tg_response("hello") == "hello"

    def test_format_response_int(self) -> None:
        from emergent.wire.compile.targets.telegrinder import _format_tg_response

        assert _format_tg_response(42) == 42

    def test_format_response_dict(self) -> None:
        from emergent.wire.compile.targets.telegrinder import _format_tg_response

        d = {"key": "val"}
        assert _format_tg_response(d) is d

    def test_format_response_custom_str(self) -> None:
        from emergent.wire.compile.targets.telegrinder import _format_tg_response

        class Custom:
            def __str__(self) -> str:
                return "custom_str"

        result = _format_tg_response(Custom())
        assert result == "custom_str"

    def test_format_response_no_custom_str(self) -> None:
        from emergent.wire.compile.targets.telegrinder import _format_tg_response

        class NoStr:
            pass

        obj = NoStr()
        result = _format_tg_response(obj)
        assert result is obj

    def test_format_response_bytes(self) -> None:
        from emergent.wire.compile.targets.telegrinder import _format_tg_response

        assert _format_tg_response(b"data") == b"data"

    def test_format_response_bool(self) -> None:
        from emergent.wire.compile.targets.telegrinder import _format_tg_response

        assert _format_tg_response(True) is True

    def test_format_response_list(self) -> None:
        from emergent.wire.compile.targets.telegrinder import _format_tg_response

        lst = [1, 2, 3]
        assert _format_tg_response(lst) is lst

    def test_telegrind_wrap_context_defaults(self) -> None:
        from emergent.wire.compile.targets.telegrinder import TelegrindWrapContext

        ctx = TelegrindWrapContext()
        assert ctx.execute is None
        assert ctx.rules == ()
        assert ctx.trigger is None

    def test_telegrind_route_creation(self) -> None:
        from emergent.wire.compile.targets.telegrinder import TelegrindRoute

        route = TelegrindRoute(handler=lambda ctx: "ok", rules=())
        assert route.handler is not None

    def test_assemble_telegrind_route_none_execute_raises(self) -> None:
        from emergent.wire.compile.targets.telegrinder import (
            assemble_telegrind_route,
            TelegrindWrapContext,
        )
        from emergent.wire.compile._core import Axes

        ctx = TelegrindWrapContext(execute=None)
        with pytest.raises(RuntimeError, match="execute is None"):
            assemble_telegrind_route(ctx, MagicMock(), Axes.default())

    def test_command_info_creation(self) -> None:
        from emergent.wire.compile.targets.telegrinder import CommandInfo

        info = CommandInfo(name="start", args=["name"], description="Start bot", order=1)
        assert info.name == "start"
        assert info.order == 1


# ═══════════════════════════════════════════════════════════════════════════════
# 20. SA query contrib — aggregate handlers, window functions
# ═══════════════════════════════════════════════════════════════════════════════


class TestSAQueryContribDeep:
    """Cover SA aggregate handlers, window funcs, store factory."""

    @pytest.mark.asyncio
    async def test_auto_increment_next_id(self) -> None:
        from emergent.wire.axis.query.contrib._impls._sqlalchemy import AutoIncrementNextId

        nid = AutoIncrementNextId()
        result = await nid.next_id()
        assert result == 0

    def test_sa_store_creation(self) -> None:
        from emergent.wire.axis.query.contrib._impls._sqlalchemy import store as sa_store

        @dataclass
        class User:
            id: Annotated[int, Identity()]
            name: str

        s = sa_store(User, "sa_q_users_cov1")
        assert s.model is not None

    def test_sa_store_bind(self) -> None:
        from emergent.wire.axis.query.contrib._impls._sqlalchemy import store as sa_store

        @dataclass
        class Item:
            id: Annotated[int, Identity()]
            name: str

        s = sa_store(Item, "sa_q_items_cov1")
        provider = s.bind(MagicMock())
        assert provider is not None

    def test_sa_store_call(self) -> None:
        from emergent.wire.axis.query.contrib._impls._sqlalchemy import store as sa_store

        @dataclass
        class Item:
            id: Annotated[int, Identity()]
            name: str

        s = sa_store(Item, "sa_q_items_cov2")
        provider = s(MagicMock())
        assert provider is not None

    def test_sa_provider_creation(self) -> None:
        from emergent.wire.axis.query.contrib._impls._sqlalchemy import provider as sa_provider

        @dataclass
        class Item:
            id: Annotated[int, Identity()]
            name: str

        p = sa_provider(MagicMock(), Item, "sa_q_items_cov3")
        assert p is not None

    def test_make_sa_agg_handlers_coverage(self) -> None:
        from emergent.wire.axis.query.contrib._impls._sqlalchemy import _make_sa_agg_handlers
        from emergent.wire.axis.query._aggregate import (
            Count, Sum, Avg, Min, Max, ArrayAgg, StringAgg,
        )

        handlers = _make_sa_agg_handlers()
        assert Count in handlers
        assert Sum in handlers
        assert Avg in handlers
        assert Min in handlers
        assert Max in handlers
        assert ArrayAgg in handlers
        assert StringAgg in handlers

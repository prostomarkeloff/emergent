# pyright: reportPrivateUsage=false
"""Property tests for:
1. emergent/wire/compile/targets/telegrinder.py — compilation, codecs, capabilities, help
2. emergent/wire/axis/query/contrib/_impls/_sqlalchemy.py — SA relational provider
3. emergent/wire/axis/storage/contrib/_impls/_sqlalchemy.py — SA storage backend

All deps are installed: telegrinder, sqlalchemy 2.0.46, aiosqlite.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Annotated, Self
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from kungfu import Ok, Error, Result, Nothing, Some

from emergent.wire.axis.schema._universal import Identity, MaxLen, Unique


# ═══════════════════════════════════════════════════════════════════════════════
# Domain types — shared across all test sections
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class User:
    id: Annotated[int, Identity]
    name: str
    email: Annotated[str, Unique, MaxLen(255)]
    score: int = 0
    active: bool = True


@dataclass
class Item:
    id: Annotated[int, Identity]
    label: str
    price: int = 0


# ═══════════════════════════════════════════════════════════════════════════════
# Declarative bases (separate per section to avoid table name collisions)
# ═══════════════════════════════════════════════════════════════════════════════


class QueryTestBase(DeclarativeBase):
    pass


class StorageTestBase(DeclarativeBase):
    pass


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 1: Telegrinder target
# ═══════════════════════════════════════════════════════════════════════════════


pytest.importorskip("telegrinder")

from emergent.ops._graph import Op, ops
from emergent.wire.axis.surface._app import application
from emergent.wire.axis.surface._endpoint import endpoint
from emergent.wire.axis.surface._handler import Handler
from emergent.wire.axis.surface.codecs.rrc import RequestResponseCodec, rrc
from emergent.wire.axis.surface.codecs.immediate import (
    ImmediateCodec,
    ImmediateFactoryCodec,
    immediate,
    immediate_factory,
)
from emergent.wire.axis.surface.codecs.delegate import DelegateCodec, delegate
from emergent.wire.axis.surface.triggers.telegrinder import TelegrindTrigger
from emergent.wire.axis.surface.dialects.telegram import (
    HelpMeta,
    Silent,
    ParseMode,
    LinkPreview,
    ProtectContent,
)
from emergent.wire.compile._core import Axes
from emergent.wire.compile.targets.telegrinder import (
    TelegrindRoute,
    TelegrindWrapContext,
    TELEGRINDER_COMPILER,
    telegrinder_compile,
    wrap_rrc_telegrinder,
    wrap_delegate_telegrinder,
    wrap_immediate_telegrinder,
    enhance_command_with_args,
    register_handler,
    extract_command_info,
    generate_help_from_command_rules,
    fold_tg_handler_ctx,
    rrc_from_codec_tg,
    immediate_from_codec_tg,
    delegate_from_codec_tg,
    assemble_telegrind_route,
    _format_tg_response as _format_tg_response,  # pyright: ignore[reportPrivateUsage]
)

from telegrinder.bot.rules.command import Command
from telegrinder.bot.rules.abc import ABCRule
from telegrinder.bot.dispatch import Dispatch


# ─── Telegrinder domain fixtures ─────────────────────────────────────────────


@dataclass
class EchoOp(Op[str, str]):
    text: str


async def _echo_handler(req: EchoOp) -> Result[str, str]:
    return Ok(f"Echo: {req.text}")


@dataclass
class EchoReq:
    name: str

    def to_domain(self) -> EchoOp:
        return EchoOp(text=self.name)


@dataclass
class EchoResp:
    text: str

    @classmethod
    def from_domain(cls, dom: Result[str, str]) -> Self:
        match dom:
            case Ok(v):
                return cls(text=v)
            case Error(e):
                return cls(text=str(e))

    def __str__(self) -> str:
        return self.text


@dataclass
class ImmResp:
    text: str = "help"

    @classmethod
    def produce(cls) -> Self:
        return cls(text="help-text")

    def __str__(self) -> str:
        return self.text


_runner = ops().on(EchoOp, _echo_handler).compile()
_mock_runner = MagicMock()
_axes = Axes.default()


def _make_trigger(*rules: ABCRule, view: str = "message") -> TelegrindTrigger:
    return TelegrindTrigger(*rules, view=view)


def _make_rrc_handler(
    caps: tuple[object, ...] = (),
) -> Handler[RequestResponseCodec]:
    return Handler(
        codec=RequestResponseCodec(request=EchoReq, response=EchoResp),
        runner=_mock_runner,
        capabilities=caps,  # type: ignore[arg-type]
    )


# ─── Tests: Compilation produces correct Dispatch ────────────────────────────


class TestTelegrindCompileBasic:
    """telegrinder_compile returns Dispatch with handlers registered."""

    def test_compile_returns_dispatch(self) -> None:
        app = application().mount(
            endpoint(_runner).expose(
                TelegrindTrigger(Command("start")),
                rrc(EchoReq, EchoResp),
            ),
        )
        dp = telegrinder_compile(app)
        assert isinstance(dp, Dispatch)

    def test_compile_with_explicit_axes(self) -> None:
        app = application().mount(
            endpoint(_runner).expose(
                TelegrindTrigger(Command("ping")),
                rrc(EchoReq, EchoResp),
            ),
        )
        dp = telegrinder_compile(app, axes=Axes.default())
        assert isinstance(dp, Dispatch)

    def test_compile_empty_app(self) -> None:
        app = application()
        dp = telegrinder_compile(app)
        assert isinstance(dp, Dispatch)


# ─── Tests: Rules correctly attached ─────────────────────────────────────────


class TestRulesAttached:
    """Rules from trigger are attached to the TelegrindRoute."""

    def test_rrc_route_has_rules(self) -> None:
        trigger = _make_trigger(Command("start"))
        handler = _make_rrc_handler()
        route = wrap_rrc_telegrinder(handler, trigger, _axes)
        assert isinstance(route, TelegrindRoute)
        assert len(route.rules) >= 1

    def test_trigger_view_respected(self) -> None:
        trigger = _make_trigger(Command("start"), view="callback_query")
        assert trigger.view == "callback_query"

    def test_multiple_rules(self) -> None:
        rule1 = Command("start")
        rule2 = Command("begin")
        trigger = _make_trigger(rule1, rule2)
        assert len(trigger.rules) == 2


# ─── Tests: Command triggers produce command handlers ────────────────────────


class TestCommandTriggers:
    """Command triggers produce correct handlers."""

    def test_command_trigger_compiles(self) -> None:
        app = application().mount(
            endpoint(_runner).expose(
                TelegrindTrigger(Command("hello")),
                rrc(EchoReq, EchoResp),
            ),
        )
        dp = telegrinder_compile(app)
        assert isinstance(dp, Dispatch)

    def test_enhance_command_no_args(self) -> None:
        """enhance_command_with_args returns same trigger when no CommandArg fields."""
        trigger = _make_trigger(Command("test"))
        result = enhance_command_with_args(trigger, EchoReq)
        assert len(result.rules) == len(trigger.rules)


# ─── Tests: All codec types compile ──────────────────────────────────────────


class TestCodecCompilation:
    """RRC, Delegate, Immediate, ImmediateFactory all compile."""

    def test_rrc_compiles(self) -> None:
        trigger = _make_trigger(Command("rrc"))
        handler = _make_rrc_handler()
        route = wrap_rrc_telegrinder(handler, trigger, _axes)
        assert isinstance(route, TelegrindRoute)
        assert route.handler is not None
        assert len(route.rules) > 0

    def test_delegate_compiles(self) -> None:
        async def _delegate_fn() -> str:
            return "delegated"

        trigger = _make_trigger(Command("del"))
        handler = Handler(
            codec=delegate(_delegate_fn),
            runner=_mock_runner,
            capabilities=(),
        )
        route = wrap_delegate_telegrinder(handler, trigger, _axes)
        assert isinstance(route, TelegrindRoute)

    def test_immediate_compiles(self) -> None:
        trigger = _make_trigger(Command("imm"))
        handler = Handler(
            codec=immediate(ImmResp),
            runner=_mock_runner,
            capabilities=(),
        )
        route = wrap_immediate_telegrinder(handler, trigger, _axes)
        assert isinstance(route, TelegrindRoute)

    def test_immediate_factory_compiles(self) -> None:
        trigger = _make_trigger(Command("immf"))
        handler = Handler(
            codec=immediate_factory(lambda: ImmResp(text="factory")),
            runner=_mock_runner,
            capabilities=(),
        )
        route = wrap_immediate_telegrinder(handler, trigger, _axes)
        assert isinstance(route, TelegrindRoute)


# ─── Tests: Capabilities applied ─────────────────────────────────────────────


class TestCapabilities:
    """Telegram capabilities (Silent, ParseMode, etc.) are applied."""

    def test_silent_folds(self) -> None:
        ctx = fold_tg_handler_ctx((Silent(),))
        assert ctx.silent is True

    def test_parse_mode_folds(self) -> None:
        ctx = fold_tg_handler_ctx((ParseMode("HTML"),))
        assert ctx.parse_mode == "HTML"

    def test_link_preview_folds(self) -> None:
        ctx = fold_tg_handler_ctx((LinkPreview(disabled=True),))
        assert ctx.link_preview_disabled is True

    def test_protect_content_folds(self) -> None:
        ctx = fold_tg_handler_ctx((ProtectContent(),))
        assert ctx.protect_content is True

    def test_multiple_capabilities_fold(self) -> None:
        ctx = fold_tg_handler_ctx((Silent(), ParseMode("MarkdownV2")))
        assert ctx.silent is True
        assert ctx.parse_mode == "MarkdownV2"

    def test_empty_capabilities_returns_defaults(self) -> None:
        ctx = fold_tg_handler_ctx(())
        assert ctx.silent is False
        assert ctx.parse_mode is None
        assert ctx.edit_message is False


# ─── Tests: Multiple endpoints combine ───────────────────────────────────────


class TestMultipleEndpoints:
    """Multiple endpoints combine correctly in one Dispatch."""

    def test_two_rrc_endpoints(self) -> None:
        app = application().mount(
            endpoint(_runner).expose(
                TelegrindTrigger(Command("a")),
                rrc(EchoReq, EchoResp),
            ),
            endpoint(_runner).expose(
                TelegrindTrigger(Command("b")),
                rrc(EchoReq, EchoResp),
            ),
        )
        dp = telegrinder_compile(app)
        assert isinstance(dp, Dispatch)

    def test_mixed_codecs(self) -> None:
        async def _fn() -> str:
            return "ok"

        app = application().mount(
            endpoint(_runner).expose(
                TelegrindTrigger(Command("rrc")),
                rrc(EchoReq, EchoResp),
            ),
            endpoint(_runner).expose(
                TelegrindTrigger(Command("imm")),
                immediate(ImmResp),
            ),
            endpoint(_runner).expose(
                TelegrindTrigger(Command("del")),
                delegate(_fn),
            ),
        )
        dp = telegrinder_compile(app)
        assert isinstance(dp, Dispatch)

    def test_application_merge_compiles(self) -> None:
        app1 = application().mount(
            endpoint(_runner).expose(
                TelegrindTrigger(Command("x")),
                rrc(EchoReq, EchoResp),
            ),
        )
        app2 = application().mount(
            endpoint(_runner).expose(
                TelegrindTrigger(Command("y")),
                rrc(EchoReq, EchoResp),
            ),
        )
        merged = app1 + app2
        dp = telegrinder_compile(merged)
        assert isinstance(dp, Dispatch)


# ─── Tests: Traced compilation ───────────────────────────────────────────────


class TestTracedCompilation:
    """Traced compilation emits events."""

    def test_traced_compile(self) -> None:
        from emergent.wire.compile._trace import ListCollector

        trace = ListCollector()
        axes = Axes(schema=Axes.default().schema, trace=trace)
        app = application().mount(
            endpoint(_runner).expose(
                TelegrindTrigger(Command("traced")),
                rrc(EchoReq, EchoResp),
            ),
        )
        dp = telegrinder_compile(app, axes=axes)
        assert isinstance(dp, Dispatch)
        assert len(trace.scan_events) >= 1
        assert len(trace.wrap_events) >= 1


# ─── Tests: from_codec functions ─────────────────────────────────────────────


class TestFromCodecFunctions:
    """from_codec functions seed TelegrindWrapContext correctly."""

    def test_rrc_from_codec(self) -> None:
        codec = RequestResponseCodec(request=EchoReq, response=EchoResp)
        trigger = _make_trigger(Command("test"))
        ctx = rrc_from_codec_tg(codec, trigger)
        assert isinstance(ctx, TelegrindWrapContext)
        assert ctx.execute is not None
        assert ctx.trigger is trigger
        assert len(ctx.rules) >= 1

    def test_immediate_from_codec(self) -> None:
        codec = immediate(ImmResp)
        trigger = _make_trigger(Command("test"))
        ctx = immediate_from_codec_tg(codec, trigger)
        assert isinstance(ctx, TelegrindWrapContext)
        assert ctx.execute is not None

    def test_delegate_from_codec(self) -> None:
        codec = delegate(lambda: "ok")
        trigger = _make_trigger(Command("test"))
        ctx = delegate_from_codec_tg(codec, trigger)
        assert isinstance(ctx, TelegrindWrapContext)
        assert ctx.execute is not None


# ─── Tests: assemble + register_handler ──────────────────────────────────────


class TestAssembleAndRegister:
    """assemble_telegrind_route and register_handler work correctly."""

    def test_assemble_raises_on_none_execute(self) -> None:
        ctx = TelegrindWrapContext(execute=None, rules=())
        handler = _make_rrc_handler()
        with pytest.raises(RuntimeError, match="execute is None"):
            assemble_telegrind_route(ctx, handler, _axes)

    def test_register_handler_on_dispatch(self) -> None:
        dp = Dispatch()
        trigger = _make_trigger(Command("reg"))
        handler = _make_rrc_handler()
        route = wrap_rrc_telegrinder(handler, trigger, _axes)
        register_handler(dp, trigger, handler, route)
        # No exception means success


# ─── Tests: _format_tg_response ──────────────────────────────────────────────


class TestFormatTgResponse:
    """Response formatting for telegrinder."""

    def test_str_passthrough(self) -> None:
        assert _format_tg_response("hello") == "hello"

    def test_int_passthrough(self) -> None:
        assert _format_tg_response(42) == 42

    def test_none_passthrough(self) -> None:
        assert _format_tg_response(None) is None

    def test_dict_passthrough(self) -> None:
        d = {"key": "value"}
        assert _format_tg_response(d) is d

    def test_custom_str_converts(self) -> None:
        resp = EchoResp(text="converted")
        result = _format_tg_response(resp)
        assert result == "converted"

    def test_no_custom_str_passthrough(self) -> None:
        class NoStr:
            pass

        obj = NoStr()
        assert _format_tg_response(obj) is obj


# ─── Tests: Help generation ──────────────────────────────────────────────────


class TestHelpGeneration:
    """Help generation from command rules."""

    def test_extract_command_info_with_help_meta(self) -> None:
        trigger = _make_trigger(Command("start"))
        handler = Handler(
            codec=rrc(EchoReq, EchoResp),
            runner=_mock_runner,
            capabilities=(HelpMeta("Start the bot", order=1),),
        )
        info = extract_command_info(trigger, handler)
        assert info is not None
        assert info.name == "start"
        assert info.description == "Start the bot"
        assert info.order == 1

    def test_extract_command_info_no_help_meta(self) -> None:
        trigger = _make_trigger(Command("silent"))
        handler = _make_rrc_handler()
        info = extract_command_info(trigger, handler)
        assert info is None

    def test_extract_command_info_hidden(self) -> None:
        trigger = _make_trigger(Command("secret"))
        handler = Handler(
            codec=rrc(EchoReq, EchoResp),
            runner=_mock_runner,
            capabilities=(HelpMeta("Hidden", hidden=True),),
        )
        info = extract_command_info(trigger, handler)
        assert info is None

    def test_generate_help_text(self) -> None:
        app = application().mount(
            endpoint(_runner).expose(
                TelegrindTrigger(Command("start")),
                rrc(EchoReq, EchoResp),
                HelpMeta("Start the bot", order=1),
            ),
            endpoint(_runner).expose(
                TelegrindTrigger(Command("help")),
                immediate(ImmResp),
                HelpMeta("Show help", order=2),
            ),
        )
        help_text = generate_help_from_command_rules(app)
        assert "/start" in help_text
        assert "/help" in help_text

    def test_generate_help_with_header_footer(self) -> None:
        app = application().mount(
            endpoint(_runner).expose(
                TelegrindTrigger(Command("test")),
                rrc(EchoReq, EchoResp),
                HelpMeta("Test"),
            ),
        )
        help_text = generate_help_from_command_rules(
            app, header="=== Help ===", footer="=== End ==="
        )
        assert help_text.startswith("=== Help ===")
        assert help_text.endswith("=== End ===")

    def test_generate_help_empty_app(self) -> None:
        app = application()
        help_text = generate_help_from_command_rules(app)
        assert help_text == ""


# ─── Tests: TELEGRINDER_COMPILER structure ────────────────────────────────────


class TestCompilerStructure:
    """TELEGRINDER_COMPILER has correct adapters."""

    def test_has_rrc(self) -> None:
        assert RequestResponseCodec in TELEGRINDER_COMPILER

    def test_has_immediate(self) -> None:
        assert ImmediateCodec in TELEGRINDER_COMPILER

    def test_has_immediate_factory(self) -> None:
        assert ImmediateFactoryCodec in TELEGRINDER_COMPILER

    def test_has_delegate(self) -> None:
        assert DelegateCodec in TELEGRINDER_COMPILER

    def test_trigger_type(self) -> None:
        assert TELEGRINDER_COMPILER.trigger_type is TelegrindTrigger


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 2: SA query contrib
# ═══════════════════════════════════════════════════════════════════════════════


from emergent.wire.axis.query._relational import relational
from emergent.wire.axis.query.contrib._impls._sqlalchemy import (
    SQLAlchemyRelationalProvider,
    provider as sa_query_provider,
    store as sa_query_store,
    AutoIncrementNextId,
)
from emergent.wire.compile.targets.sqlalchemy import compile_sa, compile_expr


# ─── Query fixtures ──────────────────────────────────────────────────────────


UserQueryStore = sa_query_store(User, "q_test_users", base=QueryTestBase)
ItemQueryStore = sa_query_store(Item, "q_test_items", base=QueryTestBase)


@pytest_asyncio.fixture
async def q_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(QueryTestBase.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def q_session(q_engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSession(q_engine, expire_on_commit=False) as sess:
        yield sess


@pytest_asyncio.fixture
async def q_provider(q_session: AsyncSession) -> SQLAlchemyRelationalProvider[User]:
    return UserQueryStore(q_session)


@pytest_asyncio.fixture
async def q_provider_items(q_session: AsyncSession) -> SQLAlchemyRelationalProvider[Item]:
    return ItemQueryStore(q_session)


async def _seed_users(provider: SQLAlchemyRelationalProvider[User], session: AsyncSession) -> list[User]:
    users = [
        User(id=1, name="Alice", email="alice@example.com", score=100, active=True),
        User(id=2, name="Bob", email="bob@example.com", score=200, active=True),
        User(id=3, name="Charlie", email="charlie@example.com", score=50, active=False),
        User(id=4, name="Diana", email="diana@example.com", score=300, active=True),
        User(id=5, name="Eve", email="eve@example.com", score=150, active=False),
    ]
    for u in users:
        await provider.insert(u)
    await session.commit()
    return users


async def seed_items(
    provider: SQLAlchemyRelationalProvider[Item], session: AsyncSession,
) -> list[Item]:
    """Seed items into the provider (kept for future test use)."""
    items = [
        Item(id=1, label="apple", price=10),
        Item(id=2, label="banana", price=20),
        Item(id=3, label="cherry", price=15),
    ]
    for item in items:
        await provider.insert(item)
    await session.commit()
    return items


# ─── Tests: compile_expr for expression types ────────────────────────────────


class TestCompileExpr:
    """compile_expr for various Expr types via SA."""

    def test_compile_eq(self) -> None:
        from emergent.wire.axis.query._expr import Eq, Field, Const
        compiled = compile_sa(User, "expr_eq_users", base=QueryTestBase)
        expr = Eq(Field("name"), Const("Alice"))
        result = compile_expr(expr, compiled)
        assert result is not None

    def test_compile_ne(self) -> None:
        from emergent.wire.axis.query._expr import Ne, Field, Const
        compiled = compile_sa(User, "expr_ne_users", base=QueryTestBase)
        expr = Ne(Field("name"), Const("Alice"))
        result = compile_expr(expr, compiled)
        assert result is not None

    def test_compile_lt(self) -> None:
        from emergent.wire.axis.query._expr import Lt, Field, Const
        compiled = compile_sa(User, "expr_lt_users", base=QueryTestBase)
        expr = Lt(Field("score"), Const(100))
        result = compile_expr(expr, compiled)
        assert result is not None

    def test_compile_le(self) -> None:
        from emergent.wire.axis.query._expr import Le, Field, Const
        compiled = compile_sa(User, "expr_le_users", base=QueryTestBase)
        expr = Le(Field("score"), Const(100))
        result = compile_expr(expr, compiled)
        assert result is not None

    def test_compile_gt(self) -> None:
        from emergent.wire.axis.query._expr import Gt, Field, Const
        compiled = compile_sa(User, "expr_gt_users", base=QueryTestBase)
        expr = Gt(Field("score"), Const(100))
        result = compile_expr(expr, compiled)
        assert result is not None

    def test_compile_ge(self) -> None:
        from emergent.wire.axis.query._expr import Ge, Field, Const
        compiled = compile_sa(User, "expr_ge_users", base=QueryTestBase)
        expr = Ge(Field("score"), Const(100))
        result = compile_expr(expr, compiled)
        assert result is not None

    def test_compile_and(self) -> None:
        from emergent.wire.axis.query._expr import And, Eq, Field, Const
        compiled = compile_sa(User, "expr_and_users", base=QueryTestBase)
        expr = And(Eq(Field("name"), Const("Alice")), Eq(Field("active"), Const(True)))
        result = compile_expr(expr, compiled)
        assert result is not None

    def test_compile_or(self) -> None:
        from emergent.wire.axis.query._expr import Or, Eq, Field, Const
        compiled = compile_sa(User, "expr_or_users", base=QueryTestBase)
        expr = Or(Eq(Field("name"), Const("Alice")), Eq(Field("name"), Const("Bob")))
        result = compile_expr(expr, compiled)
        assert result is not None

    def test_compile_not(self) -> None:
        from emergent.wire.axis.query._expr import Not, Eq, Field, Const
        compiled = compile_sa(User, "expr_not_users", base=QueryTestBase)
        expr = Not(Eq(Field("active"), Const(False)))
        result = compile_expr(expr, compiled)
        assert result is not None

    def test_compile_in(self) -> None:
        from emergent.wire.axis.query._expr import In, Field
        compiled = compile_sa(User, "expr_in_users", base=QueryTestBase)
        expr = In(Field("name"), ("Alice", "Bob"))
        result = compile_expr(expr, compiled)
        assert result is not None

    def test_compile_between(self) -> None:
        from emergent.wire.axis.query._expr import Between, Field, Const
        compiled = compile_sa(User, "expr_between_users", base=QueryTestBase)
        expr = Between(Field("score"), Const(50), Const(200))
        result = compile_expr(expr, compiled)
        assert result is not None

    def test_compile_like(self) -> None:
        from emergent.wire.axis.query._expr import Like, Field
        compiled = compile_sa(User, "expr_like_users", base=QueryTestBase)
        expr = Like(Field("email"), "%@example.com")
        result = compile_expr(expr, compiled)
        assert result is not None

    def test_compile_is_null(self) -> None:
        from emergent.wire.axis.query._expr import IsNull, Field
        compiled = compile_sa(User, "expr_isnull_users", base=QueryTestBase)
        expr = IsNull(Field("email"))
        result = compile_expr(expr, compiled)
        assert result is not None

    def test_compile_is_not_null(self) -> None:
        from emergent.wire.axis.query._expr import IsNotNull, Field
        compiled = compile_sa(User, "expr_isnotnull_users", base=QueryTestBase)
        expr = IsNotNull(Field("email"))
        result = compile_expr(expr, compiled)
        assert result is not None

    def test_compile_contains(self) -> None:
        from emergent.wire.axis.query._expr import Contains, Field
        compiled = compile_sa(User, "expr_contains_users", base=QueryTestBase)
        expr = Contains(Field("name"), "li")
        result = compile_expr(expr, compiled)
        assert result is not None

    def test_compile_startswith(self) -> None:
        from emergent.wire.axis.query._expr import StartsWith, Field
        compiled = compile_sa(User, "expr_sw_users", base=QueryTestBase)
        expr = StartsWith(Field("name"), "Al")
        result = compile_expr(expr, compiled)
        assert result is not None

    def test_compile_endswith(self) -> None:
        from emergent.wire.axis.query._expr import EndsWith, Field
        compiled = compile_sa(User, "expr_ew_users", base=QueryTestBase)
        expr = EndsWith(Field("name"), "ice")
        result = compile_expr(expr, compiled)
        assert result is not None


# ─── Tests: fetch_one, fetch_many, count, exists ─────────────────────────────


class TestQueryFetchOperations:
    """Test fetch_one, fetch_many, count, exists with real SA + SQLite."""

    @pytest.mark.asyncio
    async def test_fetch_many_all(
        self, q_provider: SQLAlchemyRelationalProvider[User], q_session: AsyncSession,
    ) -> None:
        await _seed_users(q_provider, q_session)
        q = relational(User)
        result = await q_provider.fetch_many(q)
        assert len(result) == 5

    @pytest.mark.asyncio
    async def test_fetch_one_found(
        self, q_provider: SQLAlchemyRelationalProvider[User], q_session: AsyncSession,
    ) -> None:
        await _seed_users(q_provider, q_session)
        q = relational(User).filter(lambda u: u.name == "Alice")
        result = await q_provider.fetch_one(q)
        assert result is not None
        assert result.name == "Alice"

    @pytest.mark.asyncio
    async def test_fetch_one_not_found(
        self, q_provider: SQLAlchemyRelationalProvider[User], q_session: AsyncSession,
    ) -> None:
        await _seed_users(q_provider, q_session)
        q = relational(User).filter(lambda u: u.name == "Nobody")
        result = await q_provider.fetch_one(q)
        assert result is None

    @pytest.mark.asyncio
    async def test_count(
        self, q_provider: SQLAlchemyRelationalProvider[User], q_session: AsyncSession,
    ) -> None:
        await _seed_users(q_provider, q_session)
        q = relational(User)
        count = await q_provider.count(q)
        assert count == 5

    @pytest.mark.asyncio
    async def test_count_with_filter(
        self, q_provider: SQLAlchemyRelationalProvider[User], q_session: AsyncSession,
    ) -> None:
        await _seed_users(q_provider, q_session)
        q = relational(User).filter(lambda u: u.active == True)  # noqa: E712
        count = await q_provider.count(q)
        assert count == 3

    @pytest.mark.asyncio
    async def test_exists_true(
        self, q_provider: SQLAlchemyRelationalProvider[User], q_session: AsyncSession,
    ) -> None:
        await _seed_users(q_provider, q_session)
        q = relational(User).filter(lambda u: u.name == "Alice")
        assert await q_provider.exists(q) is True

    @pytest.mark.asyncio
    async def test_exists_false(
        self, q_provider: SQLAlchemyRelationalProvider[User], q_session: AsyncSession,
    ) -> None:
        await _seed_users(q_provider, q_session)
        q = relational(User).filter(lambda u: u.name == "Nobody")
        assert await q_provider.exists(q) is False


# ─── Tests: Filter + OrderBy + Limit + Offset ────────────────────────────────


class TestQueryComposition:
    """Filter, OrderBy, Limit, Offset compose correctly."""

    @pytest.mark.asyncio
    async def test_filter_by_active(
        self, q_provider: SQLAlchemyRelationalProvider[User], q_session: AsyncSession,
    ) -> None:
        await _seed_users(q_provider, q_session)
        q = relational(User).filter(lambda u: u.active == True)  # noqa: E712
        result = await q_provider.fetch_many(q)
        assert len(result) == 3
        assert all(u.active for u in result)

    @pytest.mark.asyncio
    async def test_order_by_score_asc(
        self, q_provider: SQLAlchemyRelationalProvider[User], q_session: AsyncSession,
    ) -> None:
        await _seed_users(q_provider, q_session)
        q = relational(User).order_by(lambda u: u.score)
        result = await q_provider.fetch_many(q)
        scores = [u.score for u in result]
        assert scores == sorted(scores)

    @pytest.mark.asyncio
    async def test_order_by_score_desc(
        self, q_provider: SQLAlchemyRelationalProvider[User], q_session: AsyncSession,
    ) -> None:
        await _seed_users(q_provider, q_session)
        q = relational(User).order_by(lambda u: u.score.desc())
        result = await q_provider.fetch_many(q)
        scores = [u.score for u in result]
        assert scores == sorted(scores, reverse=True)

    @pytest.mark.asyncio
    async def test_limit(
        self, q_provider: SQLAlchemyRelationalProvider[User], q_session: AsyncSession,
    ) -> None:
        await _seed_users(q_provider, q_session)
        q = relational(User).limit(2)
        result = await q_provider.fetch_many(q)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_offset(
        self, q_provider: SQLAlchemyRelationalProvider[User], q_session: AsyncSession,
    ) -> None:
        await _seed_users(q_provider, q_session)
        q = relational(User).order_by(lambda u: u.id).offset(3)
        result = await q_provider.fetch_many(q)
        assert len(result) == 2
        assert result[0].id == 4

    @pytest.mark.asyncio
    async def test_filter_order_limit_offset(
        self, q_provider: SQLAlchemyRelationalProvider[User], q_session: AsyncSession,
    ) -> None:
        await _seed_users(q_provider, q_session)
        q = (
            relational(User)
            .filter(lambda u: u.active == True)  # noqa: E712
            .order_by(lambda u: u.score.desc())
            .limit(2)
            .offset(1)
        )
        result = await q_provider.fetch_many(q)
        assert len(result) == 2
        # Active users sorted by score desc: Diana(300), Bob(200), Alice(100)
        # Offset 1 + Limit 2 = Bob(200), Alice(100)
        assert result[0].name == "Bob"
        assert result[1].name == "Alice"

    @pytest.mark.asyncio
    async def test_multiple_filters(
        self, q_provider: SQLAlchemyRelationalProvider[User], q_session: AsyncSession,
    ) -> None:
        await _seed_users(q_provider, q_session)
        q = (
            relational(User)
            .filter(lambda u: u.active == True)  # noqa: E712
            .filter(lambda u: u.score > 100)
        )
        result = await q_provider.fetch_many(q)
        assert len(result) == 2
        names = {u.name for u in result}
        assert names == {"Bob", "Diana"}


# ─── Tests: Aggregate queries ────────────────────────────────────────────────


class TestAggregateQueries:
    """Aggregate queries (Count, Sum, Avg, Min, Max)."""

    @pytest.mark.asyncio
    async def test_count_aggregate(
        self, q_provider: SQLAlchemyRelationalProvider[User], q_session: AsyncSession,
    ) -> None:
        await _seed_users(q_provider, q_session)
        q = relational(User).aggregate(total=lambda u: u.count())
        result = await q_provider.aggregate(q)
        assert result["total"] == 5

    @pytest.mark.asyncio
    async def test_sum_aggregate(
        self, q_provider: SQLAlchemyRelationalProvider[User], q_session: AsyncSession,
    ) -> None:
        await _seed_users(q_provider, q_session)
        q = relational(User).aggregate(total_score=lambda u: u.score.sum())
        result = await q_provider.aggregate(q)
        assert result["total_score"] == 100 + 200 + 50 + 300 + 150

    @pytest.mark.asyncio
    async def test_avg_aggregate(
        self, q_provider: SQLAlchemyRelationalProvider[User], q_session: AsyncSession,
    ) -> None:
        await _seed_users(q_provider, q_session)
        q = relational(User).aggregate(avg_score=lambda u: u.score.avg())
        result = await q_provider.aggregate(q)
        assert result["avg_score"] == (100 + 200 + 50 + 300 + 150) / 5

    @pytest.mark.asyncio
    async def test_min_aggregate(
        self, q_provider: SQLAlchemyRelationalProvider[User], q_session: AsyncSession,
    ) -> None:
        await _seed_users(q_provider, q_session)
        q = relational(User).aggregate(min_score=lambda u: u.score.min())
        result = await q_provider.aggregate(q)
        assert result["min_score"] == 50

    @pytest.mark.asyncio
    async def test_max_aggregate(
        self, q_provider: SQLAlchemyRelationalProvider[User], q_session: AsyncSession,
    ) -> None:
        await _seed_users(q_provider, q_session)
        q = relational(User).aggregate(max_score=lambda u: u.score.max())
        result = await q_provider.aggregate(q)
        assert result["max_score"] == 300

    @pytest.mark.asyncio
    async def test_multiple_aggregates(
        self, q_provider: SQLAlchemyRelationalProvider[User], q_session: AsyncSession,
    ) -> None:
        await _seed_users(q_provider, q_session)
        q = relational(User).aggregate(
            total=lambda u: u.count(),
            total_score=lambda u: u.score.sum(),
            min_score=lambda u: u.score.min(),
            max_score=lambda u: u.score.max(),
        )
        result = await q_provider.aggregate(q)
        assert result["total"] == 5
        assert result["total_score"] == 800
        assert result["min_score"] == 50
        assert result["max_score"] == 300

    @pytest.mark.asyncio
    async def test_aggregate_with_filter(
        self, q_provider: SQLAlchemyRelationalProvider[User], q_session: AsyncSession,
    ) -> None:
        await _seed_users(q_provider, q_session)
        q = (
            relational(User)
            .filter(lambda u: u.active == True)  # noqa: E712
            .aggregate(active_total=lambda u: u.count())
        )
        result = await q_provider.aggregate(q)
        assert result["active_total"] == 3

    @pytest.mark.asyncio
    async def test_aggregate_empty_specs(
        self, q_provider: SQLAlchemyRelationalProvider[User], q_session: AsyncSession,
    ) -> None:
        await _seed_users(q_provider, q_session)
        q = relational(User)
        result = await q_provider.aggregate(q)
        assert result == {}


# ─── Tests: Write operations ─────────────────────────────────────────────────


class TestQueryWriteOperations:
    """insert, update, delete, delete_where via provider."""

    @pytest.mark.asyncio
    async def test_insert(
        self, q_provider: SQLAlchemyRelationalProvider[User], q_session: AsyncSession,
    ) -> None:
        user = User(id=0, name="New", email="new@test.com", score=10, active=True)
        result = await q_provider.insert(user)
        await q_session.commit()
        assert result.name == "New"
        assert result.email == "new@test.com"

    @pytest.mark.asyncio
    async def test_update(
        self, q_provider: SQLAlchemyRelationalProvider[User], q_session: AsyncSession,
    ) -> None:
        await _seed_users(q_provider, q_session)
        updated = User(id=1, name="Alice Updated", email="alice@example.com", score=999, active=True)
        result = await q_provider.update(updated)
        await q_session.commit()
        assert result.name == "Alice Updated"
        assert result.score == 999

    @pytest.mark.asyncio
    async def test_delete(
        self, q_provider: SQLAlchemyRelationalProvider[User], q_session: AsyncSession,
    ) -> None:
        await _seed_users(q_provider, q_session)
        user = User(id=1, name="Alice", email="alice@example.com", score=100, active=True)
        await q_provider.delete(user)
        await q_session.commit()
        q = relational(User).filter(lambda u: u.name == "Alice")
        assert await q_provider.fetch_one(q) is None

    @pytest.mark.asyncio
    async def test_delete_where(
        self, q_provider: SQLAlchemyRelationalProvider[User], q_session: AsyncSession,
    ) -> None:
        await _seed_users(q_provider, q_session)
        q = relational(User).filter(lambda u: u.active == False)  # noqa: E712
        count = await q_provider.delete_where(q)
        await q_session.commit()
        assert count == 2
        remaining = await q_provider.fetch_many(relational(User))
        assert len(remaining) == 3

    @pytest.mark.asyncio
    async def test_insert_raises_for_non_dataclass(
        self, q_provider: SQLAlchemyRelationalProvider[User],
    ) -> None:
        with pytest.raises(TypeError, match="dataclass"):
            await q_provider.insert("not a dataclass")  # type: ignore[arg-type]


# ─── Tests: Store factory ────────────────────────────────────────────────────


class TestQueryStoreFactory:
    """SQLAlchemyRelationalStore bind/call."""

    @pytest.mark.asyncio
    async def test_store_bind(self, q_session: AsyncSession) -> None:
        prov = UserQueryStore.bind(q_session)
        assert isinstance(prov, SQLAlchemyRelationalProvider)

    @pytest.mark.asyncio
    async def test_store_call(self, q_session: AsyncSession) -> None:
        prov = UserQueryStore(q_session)
        assert isinstance(prov, SQLAlchemyRelationalProvider)

    def test_store_model(self) -> None:
        assert UserQueryStore.model is not None

    @pytest.mark.asyncio
    async def test_next_id_default(
        self, q_provider: SQLAlchemyRelationalProvider[User],
    ) -> None:
        next_id = await q_provider.next_id()
        assert next_id == 0  # AutoIncrement


class TestAutoIncrementNextId:
    """AutoIncrementNextId always returns 0."""

    @pytest.mark.asyncio
    async def test_returns_zero(self) -> None:
        nid = AutoIncrementNextId()
        assert await nid.next_id() == 0


# ─── Tests: inline provider factory ──────────────────────────────────────────


class TestInlineProvider:
    """sa_query.provider() creates inline provider."""

    @pytest.mark.asyncio
    async def test_inline_provider(self, q_session: AsyncSession) -> None:
        prov = sa_query_provider(q_session, User, "q_test_users", base=QueryTestBase)
        assert isinstance(prov, SQLAlchemyRelationalProvider)


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 3: SA storage contrib
# ═══════════════════════════════════════════════════════════════════════════════


from emergent.wire.axis.storage.contrib._impls._sqlalchemy import (
    BoundSQLAlchemyStore,
    SQLAlchemyStorage,
    StorageError,
    store as sa_storage_store,
    sqlalchemy as sa_storage_inline,
)


# ─── Storage fixtures ────────────────────────────────────────────────────────


UserStore = sa_storage_store(User, "s_test_users", base=StorageTestBase)
ItemStore = sa_storage_store(Item, "s_test_items", base=StorageTestBase)


@pytest_asyncio.fixture
async def s_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(StorageTestBase.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def s_session(s_engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSession(s_engine, expire_on_commit=False) as sess:
        yield sess


@pytest_asyncio.fixture
async def bound_store(s_session: AsyncSession) -> BoundSQLAlchemyStore[User]:
    return UserStore.bind(s_session)


@pytest_asyncio.fixture
async def legacy_store(s_session: AsyncSession) -> SQLAlchemyStorage[User]:
    return SQLAlchemyStorage(
        session=s_session,
        entity=User,
        tablename="s_test_users",
        base=StorageTestBase,
    )


# ─── Tests: KV operations ────────────────────────────────────────────────────


class TestStorageKV:
    """KV operations: get, set, delete, exists."""

    @pytest.mark.asyncio
    async def test_set_and_get(
        self, bound_store: BoundSQLAlchemyStore[User], s_session: AsyncSession,
    ) -> None:
        user = User(id=1, name="Alice", email="alice@test.com", score=100, active=True)
        result = await bound_store.set(user)
        await s_session.commit()
        assert isinstance(result, Ok)

        get_result = await bound_store.get(1)
        assert isinstance(get_result, Ok)
        match get_result.unwrap():
            case Some(u):
                assert u.name == "Alice"
            case _:
                pytest.fail("Expected Some")

    @pytest.mark.asyncio
    async def test_get_missing(
        self, bound_store: BoundSQLAlchemyStore[User],
    ) -> None:
        result = await bound_store.get(999)
        assert isinstance(result, Ok)
        assert isinstance(result.unwrap(), Nothing)

    @pytest.mark.asyncio
    async def test_set_upsert(
        self, bound_store: BoundSQLAlchemyStore[User], s_session: AsyncSession,
    ) -> None:
        user = User(id=1, name="Alice", email="alice@test.com", score=100, active=True)
        await bound_store.set(user)
        await s_session.commit()

        updated = User(id=1, name="Alice Updated", email="alice@test.com", score=200, active=True)
        await bound_store.set(updated)
        await s_session.commit()

        get_result = await bound_store.get(1)
        assert isinstance(get_result, Ok)
        match get_result.unwrap():
            case Some(u):
                assert u.name == "Alice Updated"
                assert u.score == 200
            case _:
                pytest.fail("Expected Some")

    @pytest.mark.asyncio
    async def test_delete_existing(
        self, bound_store: BoundSQLAlchemyStore[User], s_session: AsyncSession,
    ) -> None:
        user = User(id=1, name="Alice", email="alice@test.com", score=100, active=True)
        await bound_store.set(user)
        await s_session.commit()

        del_result = await bound_store.delete(1)
        await s_session.commit()
        assert isinstance(del_result, Ok)
        assert del_result.unwrap() is True

    @pytest.mark.asyncio
    async def test_delete_missing(
        self, bound_store: BoundSQLAlchemyStore[User],
    ) -> None:
        del_result = await bound_store.delete(999)
        assert isinstance(del_result, Ok)
        assert del_result.unwrap() is False

    @pytest.mark.asyncio
    async def test_exists_true(
        self, bound_store: BoundSQLAlchemyStore[User], s_session: AsyncSession,
    ) -> None:
        user = User(id=1, name="Alice", email="alice@test.com", score=100, active=True)
        await bound_store.set(user)
        await s_session.commit()

        result = await bound_store.exists(1)
        assert isinstance(result, Ok)
        assert result.unwrap() is True

    @pytest.mark.asyncio
    async def test_exists_false(
        self, bound_store: BoundSQLAlchemyStore[User],
    ) -> None:
        result = await bound_store.exists(999)
        assert isinstance(result, Ok)
        assert result.unwrap() is False


# ─── Tests: find / find_one / count / delete_where ────────────────────────────


class TestStorageRelational:
    """Relational operations on storage."""

    @pytest.mark.asyncio
    async def test_find(
        self, bound_store: BoundSQLAlchemyStore[User], s_session: AsyncSession,
    ) -> None:
        for i, name in enumerate(["Alice", "Bob", "Charlie"], 1):
            await bound_store.set(
                User(id=i, name=name, email=f"{name.lower()}@test.com", score=i * 100, active=i < 3)
            )
        await s_session.commit()

        result = await bound_store.find(lambda u: u.active == True)  # noqa: E712
        assert isinstance(result, Ok)
        users = result.unwrap()
        assert len(users) == 2

    @pytest.mark.asyncio
    async def test_find_one_found(
        self, bound_store: BoundSQLAlchemyStore[User], s_session: AsyncSession,
    ) -> None:
        await bound_store.set(User(id=1, name="Alice", email="alice@test.com", score=100, active=True))
        await s_session.commit()

        result = await bound_store.find_one(lambda u: u.name == "Alice")
        assert isinstance(result, Ok)
        match result.unwrap():
            case Some(u):
                assert u.name == "Alice"
            case _:
                pytest.fail("Expected Some")

    @pytest.mark.asyncio
    async def test_find_one_not_found(
        self, bound_store: BoundSQLAlchemyStore[User], s_session: AsyncSession,
    ) -> None:
        result = await bound_store.find_one(lambda u: u.name == "Nobody")
        assert isinstance(result, Ok)
        assert isinstance(result.unwrap(), Nothing)

    @pytest.mark.asyncio
    async def test_count_all(
        self, bound_store: BoundSQLAlchemyStore[User], s_session: AsyncSession,
    ) -> None:
        for i in range(1, 4):
            await bound_store.set(
                User(id=i, name=f"User{i}", email=f"user{i}@test.com", score=i * 10, active=True)
            )
        await s_session.commit()

        result = await bound_store.count()
        assert isinstance(result, Ok)
        assert result.unwrap() == 3

    @pytest.mark.asyncio
    async def test_count_with_predicate(
        self, bound_store: BoundSQLAlchemyStore[User], s_session: AsyncSession,
    ) -> None:
        for i in range(1, 6):
            await bound_store.set(
                User(id=i, name=f"User{i}", email=f"user{i}@test.com", score=i * 10, active=i <= 3)
            )
        await s_session.commit()

        result = await bound_store.count(lambda u: u.active == True)  # noqa: E712
        assert isinstance(result, Ok)
        assert result.unwrap() == 3

    @pytest.mark.asyncio
    async def test_delete_where(
        self, bound_store: BoundSQLAlchemyStore[User], s_session: AsyncSession,
    ) -> None:
        for i in range(1, 4):
            await bound_store.set(
                User(id=i, name=f"User{i}", email=f"user{i}@test.com", score=i * 10, active=i == 1)
            )
        await s_session.commit()

        result = await bound_store.delete_where(lambda u: u.active == False)  # noqa: E712
        assert isinstance(result, Ok)
        assert result.unwrap() == 2

        count_result = await bound_store.count()
        assert isinstance(count_result, Ok)
        assert count_result.unwrap() == 1


# ─── Tests: Bulk operations ──────────────────────────────────────────────────


class TestStorageBulk:
    """Bulk operations: set_many, all."""

    @pytest.mark.asyncio
    async def test_set_many(
        self, bound_store: BoundSQLAlchemyStore[User], s_session: AsyncSession,
    ) -> None:
        users = [
            User(id=i, name=f"User{i}", email=f"user{i}@test.com", score=i * 10, active=True)
            for i in range(1, 4)
        ]
        result = await bound_store.set_many(users)
        await s_session.commit()
        assert isinstance(result, Ok)
        assert len(result.unwrap()) == 3

    @pytest.mark.asyncio
    async def test_all(
        self, bound_store: BoundSQLAlchemyStore[User], s_session: AsyncSession,
    ) -> None:
        users = [
            User(id=i, name=f"User{i}", email=f"user{i}@test.com", score=i * 10, active=True)
            for i in range(1, 4)
        ]
        await bound_store.set_many(users)
        await s_session.commit()

        result = await bound_store.all()
        assert isinstance(result, Ok)
        assert len(result.unwrap()) == 3


# ─── Tests: Store factory / legacy ───────────────────────────────────────────


class TestStorageStoreFactory:
    """SQLAlchemyStore factory and legacy SQLAlchemyStorage."""

    def test_store_entity(self) -> None:
        assert UserStore.entity is User

    def test_store_model(self) -> None:
        assert UserStore.model is not None

    def test_store_tablename(self) -> None:
        assert UserStore.tablename == "s_test_users"

    @pytest.mark.asyncio
    async def test_store_call(self, s_session: AsyncSession) -> None:
        bound = UserStore(s_session)
        assert isinstance(bound, BoundSQLAlchemyStore)

    @pytest.mark.asyncio
    async def test_legacy_storage_works(
        self, legacy_store: SQLAlchemyStorage[User], s_session: AsyncSession,
    ) -> None:
        user = User(id=1, name="Legacy", email="legacy@test.com", score=0, active=True)
        result = await legacy_store.set(user)
        await s_session.commit()
        assert isinstance(result, Ok)

    @pytest.mark.asyncio
    async def test_inline_storage_factory(self, s_session: AsyncSession) -> None:
        storage = sa_storage_inline(s_session, User, "s_test_users", base=StorageTestBase)
        assert isinstance(storage, SQLAlchemyStorage)


# ─── Tests: BoundSQLAlchemyStore properties ──────────────────────────────────


class TestBoundStoreProperties:
    """BoundSQLAlchemyStore exposes entity and model."""

    @pytest.mark.asyncio
    async def test_entity(self, bound_store: BoundSQLAlchemyStore[User]) -> None:
        assert bound_store.entity is User

    @pytest.mark.asyncio
    async def test_model(self, bound_store: BoundSQLAlchemyStore[User]) -> None:
        assert bound_store.model is not None


# ─── Tests: Error handling ───────────────────────────────────────────────────


class TestStorageErrorType:
    """StorageError dataclass."""

    def test_storage_error_message(self) -> None:
        err = StorageError(message="test error")
        assert err.message == "test error"
        assert err.cause is None

    def test_storage_error_with_cause(self) -> None:
        cause = ValueError("root")
        err = StorageError(message="test error", cause=cause)
        assert err.cause is cause

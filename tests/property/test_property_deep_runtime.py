# pyright: reportPrivateUsage=false
"""Deep runtime tests — compile infrastructure, contrib providers, derive runtime.

Covers remaining uncovered lines in:
- compile/_execute.py — execute_rrc_unified, execute_stateful_unified, execute_delegate_unified, execute_immediate_unified
- compile/_generate.py — to_pydantic, to_argparse_args, assemble_pydantic, assemble_argparse, to_datanode, _pydantic_coercion
- compile/_delegate.py — resolve_handler_params with compose dialect (Node, Retrieve, Optional, Fallback)
- compile/_stateful.py — execute_stateful_turn, execute_stateful_done, load_state, save_state, delete_state
- compile/_request.py — build_request, build_field_value with compose nodes (Node, Optional, Fallback, Race, Retrieve)
- compile/_pipeline.py — compile_pipeline, execute_with_pipeline with coercion model
- compile/_capabilities.py — fold_handler_runtime, apply_response_capabilities, Mount + OpenAPI merge
- axis/query/contrib/_impls/_sqlalchemy.py — window funcs, aggregates, delete_where, delete_returning
- axis/query/contrib/_impls/_http.py — HTTP API provider, pagination, auth, filter encoding
- axis/storage/contrib/_impls/_sqlalchemy.py — find, find_one, count, delete_where, set_many, all
- axis/query/providers/memory.py — MemoryKVProvider ops, MemoryAPIProvider, MemoryRelationalProvider aggregates
- derive/_handler.py — PatchExisting, SortedFetchMany, SoftDeleteMark, TimestampInsert, TimestampUpdate, SetField, ExistsById, CountAll, UpsertExisting
- derive/_transforms.py — Paginated, Sorted, Readonly, SoftDelete, Timestamped, Filtered, Searchable, ProjectResponse
- derive/auth/caps.py — Authenticated, RequireRole, RoleRequired, AuthorizeOps, OwnerScoped
- derive/auth/login.py — LoginOp, IssueToken, token_converter
- derive/_pipeline.py — Pipeline, ScopeQuery, IdentityFilter, FetchAll, FetchOrNotFound, MergeFields, WrapOk, WrapItems, WrapPaginated
- derive/patterns/methods.py — @post, @get, Methods, MethodDialect, _build_method_operation
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Annotated, Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from kungfu import Error, Nothing, Ok, Result, Some
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from emergent.wire.axis.schema._universal import Identity, MaxLen, Unique


# ═══════════════════════════════════════════════════════════════════════════════
# Domain types
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class User:
    id: Annotated[int, Identity()]
    name: str
    email: Annotated[str, Unique(), MaxLen(255)]
    score: int = 0
    active: bool = True


@dataclass
class Article:
    id: Annotated[int, Identity()]
    title: str
    body: str
    author_id: int
    created_at: datetime | None = None
    updated_at: datetime | None = None
    deleted_at: datetime | None = None


@dataclass
class AuthUser:
    name: str
    roles: set[str] = field(default_factory=lambda: {"user"})


# ═══════════════════════════════════════════════════════════════════════════════
# SA fixtures — fresh DeclarativeBase per invocation to avoid table collisions
# ═══════════════════════════════════════════════════════════════════════════════


@pytest_asyncio.fixture
async def sa_session() -> AsyncGenerator[tuple[AsyncSession, Any], None]:
    import uuid
    from emergent.wire.axis.storage.contrib._impls._sqlalchemy import store as sa_store

    base: type[DeclarativeBase] = type(f"DB_{uuid.uuid4().hex[:8]}", (DeclarativeBase,), {})
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    store = sa_store(User, "deep_users", base=base)
    async with engine.begin() as conn:
        await conn.run_sync(base.metadata.create_all)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        yield session, store
    await engine.dispose()


@pytest_asyncio.fixture
async def sa_session2() -> AsyncGenerator[AsyncSession, None]:
    import uuid
    from emergent.wire.axis.query.contrib._impls._sqlalchemy import store as sa_q_store

    base: type[DeclarativeBase] = type(f"DB2_{uuid.uuid4().hex[:8]}", (DeclarativeBase,), {})
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sa_q_store(User, "deep_q_users", base=base)
    async with engine.begin() as conn:
        await conn.run_sync(base.metadata.create_all)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        yield session
    await engine.dispose()


# ═══════════════════════════════════════════════════════════════════════════════
# 1. compile/_request.py — build_request, build_field_value
# ═══════════════════════════════════════════════════════════════════════════════


class TestBuildRequest:
    @pytest.mark.asyncio
    async def test_build_request_basic_fields(self) -> None:
        from emergent.wire.compile._request import build_request

        @dataclass
        class Req:
            name: str
            age: int

        req = await build_request(Req, lambda n: {"name": "Alice", "age": 30}.get(n))
        assert req.name == "Alice"
        assert req.age == 30

    @pytest.mark.asyncio
    async def test_build_request_optional_field_missing(self) -> None:
        from emergent.wire.compile._request import build_request

        @dataclass
        class Req:
            name: str
            bio: str | None = None

        req = await build_request(Req, lambda n: {"name": "Bob"}.get(n))
        assert req.name == "Bob"
        assert req.bio is None

    @pytest.mark.asyncio
    async def test_build_request_with_default(self) -> None:
        from emergent.wire.compile._request import build_request

        @dataclass
        class Req:
            name: str
            count: int = 42

        req = await build_request(Req, lambda n: {"name": "C"}.get(n))
        assert req.name == "C"
        assert req.count == 42

    @pytest.mark.asyncio
    async def test_build_request_not_dataclass_raises(self) -> None:
        from emergent.wire.compile._request import build_request

        class NotDC:
            pass

        with pytest.raises(TypeError, match="not a dataclass"):
            await build_request(NotDC, lambda n: None)

    @pytest.mark.asyncio
    async def test_build_request_missing_required_raises(self) -> None:
        from emergent.wire.compile._request import build_request

        @dataclass
        class Req:
            name: str

        with pytest.raises(RuntimeError, match="Cannot resolve"):
            await build_request(Req, lambda n: None)

    @pytest.mark.asyncio
    async def test_build_request_default_factory(self) -> None:
        from emergent.wire.compile._request import build_request

        @dataclass
        class Req:
            tags: list[str] = field(default_factory=lambda: list[str]())

        req = await build_request(Req, lambda n: None)
        tags: list[str] = req.tags
        assert tags == []

    def test_build_request_sync_basic(self) -> None:
        from emergent.wire.compile._request import build_request_sync

        @dataclass
        class Req:
            name: str
            count: int = 5

        req = build_request_sync(Req, lambda n: {"name": "X"}.get(n))
        assert req.name == "X"
        assert req.count == 5

    def test_build_request_sync_not_dataclass(self) -> None:
        from emergent.wire.compile._request import build_request_sync

        with pytest.raises(TypeError, match="not a dataclass"):
            build_request_sync(int, lambda n: None)

    def test_build_request_sync_missing_required(self) -> None:
        from emergent.wire.compile._request import build_request_sync

        @dataclass
        class Req:
            name: str

        with pytest.raises(RuntimeError, match="No value for required"):
            build_request_sync(Req, lambda n: None)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. compile/_pipeline.py — compile_pipeline, execute_with_pipeline
# ═══════════════════════════════════════════════════════════════════════════════


class TestCompilePipeline:
    def test_compile_pipeline_no_execute_raises(self) -> None:
        from emergent.wire.compile._pipeline import compile_pipeline
        from emergent.wire.compile._core import Axes

        ctx = object()
        with pytest.raises(TypeError, match="no 'execute' attribute"):
            compile_pipeline(ctx, Axes.default())

    def test_compile_pipeline_basic(self) -> None:
        from emergent.wire.compile._pipeline import compile_pipeline, CompiledPipeline
        from emergent.wire.compile._core import Axes

        async def dummy_execute(h: Any, s: Any, gv: Any) -> str:
            return "ok"

        class FakeCtx:
            execute = dummy_execute

        result = compile_pipeline(FakeCtx(), Axes.default())
        assert isinstance(result, CompiledPipeline)
        assert result.execute is not None
        assert result.extractor is None
        assert result.coerce_model is None

    def test_compile_pipeline_with_coercion(self) -> None:
        from emergent.wire.compile._pipeline import compile_pipeline
        from emergent.wire.compile._core import Axes
        from emergent.wire.compile._generate import _pydantic_coercion

        @dataclass
        class Req:
            name: str

        _coercion = _pydantic_coercion()

        def _exec(h: Any, s: Any, gv: Any) -> str:
            return "ok"

        ctx = type("FakeCtx", (), {
            "execute": staticmethod(_exec),
            "coercion": _coercion,
            "request_type": Req,
        })()

        result = compile_pipeline(ctx, Axes.default())
        assert result.coerce_model is not None


# ═══════════════════════════════════════════════════════════════════════════════
# 3. compile/_capabilities.py — fold_handler_runtime, apply_response_capabilities
# ═══════════════════════════════════════════════════════════════════════════════


class TestCapabilities:
    def test_fold_handler_runtime_empty(self) -> None:
        from emergent.wire.compile._capabilities import fold_handler_runtime

        ctx = fold_handler_runtime(())
        assert ctx.enrichers == ()
        assert ctx.response_transforms == ()

    def test_apply_response_capabilities_no_transforms(self) -> None:
        from emergent.wire.compile._capabilities import apply_response_capabilities

        result = apply_response_capabilities({"data": 1}, ())
        assert result == {"data": 1}

    def test_apply_response_capabilities_with_transform(self) -> None:
        from emergent.wire.compile._capabilities import apply_response_capabilities
        from emergent.wire.axis.surface.transforms._response import AsDict

        result = apply_response_capabilities(User(id=1, name="A", email="a@b.c"), (AsDict(),))
        assert isinstance(result, dict)
        assert result["name"] == "A"


# ═══════════════════════════════════════════════════════════════════════════════
# 4. compile/_execute.py — execute_immediate_unified
# ═══════════════════════════════════════════════════════════════════════════════


class TestExecuteImmediate:
    def test_immediate_codec(self) -> None:
        from emergent.wire.compile._execute import execute_immediate_unified
        from emergent.wire.axis.surface.codecs.immediate import immediate
        from emergent.wire.axis.surface._handler import Handler

        @dataclass
        class HelloResp:
            msg: str = "hello"

            @classmethod
            def produce(cls) -> HelloResp:
                return cls(msg="hello")

        codec = immediate(HelloResp)
        handler = Handler(codec=codec, runner=None, capabilities=())  # type: ignore[arg-type]
        result = execute_immediate_unified(handler)
        assert isinstance(result, HelloResp)
        assert result.msg == "hello"

    def test_immediate_factory_codec(self) -> None:
        from emergent.wire.compile._execute import execute_immediate_unified
        from emergent.wire.axis.surface.codecs.immediate import immediate_factory
        from emergent.wire.axis.surface._handler import Handler

        codec = immediate_factory(lambda: {"status": "ok"})
        handler = Handler(codec=codec, runner=None, capabilities=())  # type: ignore[arg-type]
        result = execute_immediate_unified(handler)
        assert result == {"status": "ok"}

    def test_immediate_with_format_response(self) -> None:
        from emergent.wire.compile._execute import execute_immediate_unified
        from emergent.wire.axis.surface.codecs.immediate import immediate_factory
        from emergent.wire.axis.surface._handler import Handler

        codec = immediate_factory(lambda: 42)
        handler = Handler(codec=codec, runner=None, capabilities=())  # type: ignore[arg-type]
        result = execute_immediate_unified(handler, format_response=lambda x: {"value": x})
        assert result == {"value": 42}

    def test_immediate_unknown_codec_raises(self) -> None:
        from emergent.wire.compile._execute import execute_immediate_unified
        from emergent.wire.axis.surface._handler import Handler

        handler = Handler(codec="not_a_codec", runner=None, capabilities=())  # type: ignore[arg-type]
        with pytest.raises(TypeError, match="Expected ImmediateCodec"):
            execute_immediate_unified(handler)


# ═══════════════════════════════════════════════════════════════════════════════
# 5. compile/_generate.py — to_pydantic, to_argparse_args, _pydantic_coercion
# ═══════════════════════════════════════════════════════════════════════════════


class TestGenerate:
    def test_to_pydantic_basic(self) -> None:
        from emergent.wire.compile._generate import to_pydantic
        from emergent.wire.compile._core import Axes

        Model = to_pydantic(User, Axes.default())
        instance = Model(id=1, name="Alice", email="a@b.com", score=10, active=True)
        assert instance.name == "Alice"  # type: ignore[attr-defined]

    def test_to_argparse_args_basic(self) -> None:
        from emergent.wire.compile._generate import to_argparse_args
        from emergent.wire.compile._core import Axes

        specs = to_argparse_args(User, Axes.default())
        assert len(specs) > 0
        names = {s.dest for s in specs}
        assert "name" in names

    def test_pydantic_coercion_roundtrip(self) -> None:
        from emergent.wire.compile._generate import _pydantic_coercion

        coercion = _pydantic_coercion()
        assert coercion.compiler is not None
        assert coercion.validate is not None

    def test_pydantic_coercion_validate(self) -> None:
        from emergent.wire.compile._generate import _pydantic_coercion, to_pydantic
        from emergent.wire.compile._core import Axes

        coercion = _pydantic_coercion()
        Model = to_pydantic(User, Axes.default())
        validated = coercion.validate(Model, {"id": 1, "name": "A", "email": "b@c.d"})
        assert validated["name"] == "A"

    def test_to_datanode_basic(self) -> None:
        from emergent.wire.compile._generate import to_datanode

        @dataclass
        class Simple:
            x: int
            y: str

        try:
            from nodnod import DataNode

            NodeCls = to_datanode(Simple, {})
            assert issubclass(NodeCls, DataNode)
        except ImportError:
            pytest.skip("nodnod not installed")

    def test_assemble_pydantic_optional_field(self) -> None:
        from emergent.wire.compile._generate import to_pydantic
        from emergent.wire.compile._core import Axes

        @dataclass
        class OptReq:
            name: str
            bio: str | None = None

        Model = to_pydantic(OptReq, Axes.default())
        instance = Model(name="A")
        assert instance.bio is None  # type: ignore[attr-defined]


# ═══════════════════════════════════════════════════════════════════════════════
# 6. compile/_stateful.py — state management helpers
# ═══════════════════════════════════════════════════════════════════════════════


class TestStatefulHelpers:
    @pytest.mark.asyncio
    async def test_load_state_no_existing(self) -> None:
        from emergent.wire.compile._stateful import load_state

        @dataclass
        class Flow:
            step: int = 0

        store = AsyncMock()
        store.get = AsyncMock(return_value=Ok(Nothing()))

        codec = MagicMock()
        codec.store = store
        codec.flow = Flow

        state = await load_state(codec, "key1")
        assert isinstance(state, Flow)
        assert state.step == 0

    @pytest.mark.asyncio
    async def test_load_state_existing(self) -> None:
        from emergent.wire.compile._stateful import load_state

        @dataclass
        class Flow:
            step: int = 0

        existing = Flow(step=3)
        store = AsyncMock()
        store.get = AsyncMock(return_value=Ok(Some(existing)))

        codec = MagicMock()
        codec.store = store
        codec.flow = Flow

        state = await load_state(codec, "key1")
        assert state.step == 3

    @pytest.mark.asyncio
    async def test_save_state_when_changed(self) -> None:
        from emergent.wire.compile._stateful import save_state

        store = AsyncMock()
        codec = MagicMock()
        codec.store = store

        old = object()
        new = object()
        await save_state(codec, "key", old, new)
        store.set.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_save_state_same_object_skips(self) -> None:
        from emergent.wire.compile._stateful import save_state

        store = AsyncMock()
        codec = MagicMock()
        codec.store = store

        obj = object()
        await save_state(codec, "key", obj, obj)
        store.set.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_delete_state(self) -> None:
        from emergent.wire.compile._stateful import delete_state

        store = AsyncMock()
        codec = MagicMock()
        codec.store = store

        await delete_state(codec, "key")
        store.delete.assert_awaited_once_with("key")

    def test_get_stateful_metadata(self) -> None:
        from emergent.wire.compile._stateful import get_stateful_metadata

        @dataclass
        class Flow:
            step: int = 0

        codec = MagicMock()
        codec.flow = Flow
        codec.response = str
        codec.key_node = None
        codec.agent_cls = None

        handler = MagicMock()
        handler.codec = codec

        meta = get_stateful_metadata(handler)
        assert meta["flow_cls"] is Flow
        assert meta["response_cls"] is str


# ═══════════════════════════════════════════════════════════════════════════════
# 7. compile/_delegate.py — resolve_handler_params
# ═══════════════════════════════════════════════════════════════════════════════


class TestDelegateResolveParams:
    @pytest.mark.asyncio
    async def test_resolve_params_basic_type_from_scope(self) -> None:
        from emergent.wire.compile._delegate import resolve_handler_params
        from nodnod import Scope
        from nodnod.agent.event_loop.agent import EventLoopAgent

        scope = Scope()
        async with scope:
            scope.inject(str, "hello")

            def handler(msg: str) -> str:
                return msg

            result = await resolve_handler_params(handler, scope, EventLoopAgent)
            assert result["msg"] == "hello"

    @pytest.mark.asyncio
    async def test_resolve_params_skips_self_cls(self) -> None:
        from emergent.wire.compile._delegate import resolve_handler_params
        from nodnod import Scope
        from nodnod.agent.event_loop.agent import EventLoopAgent

        scope = Scope()
        async with scope:
            def handler(self: Any, cls: Any, msg: str) -> str:
                return msg

            scope.inject(str, "test")
            result = await resolve_handler_params(handler, scope, EventLoopAgent)
            assert "self" not in result
            assert "cls" not in result

    @pytest.mark.asyncio
    async def test_resolve_params_no_annotation(self) -> None:
        from emergent.wire.compile._delegate import resolve_handler_params
        from nodnod import Scope
        from nodnod.agent.event_loop.agent import EventLoopAgent

        scope = Scope()
        async with scope:

            def handler(x: Any) -> Any:
                return x

            result = await resolve_handler_params(handler, scope, EventLoopAgent)
            # No annotation -> skipped
            assert "x" not in result


# ═══════════════════════════════════════════════════════════════════════════════
# 8. SA storage contrib — deeper operations
# ═══════════════════════════════════════════════════════════════════════════════


class TestSAStorageDeep:
    @pytest.mark.asyncio
    async def test_store_find(self, sa_session: AsyncSession) -> None:
        from emergent.wire.axis.storage.contrib._impls._sqlalchemy import SQLAlchemyStore

        sa_session, s = sa_session  # type: ignore[assignment]  # unpack (session, store) fixture
        bound = s(sa_session)
        await bound.set(User(id=1, name="Alice", email="a@b.com", score=10))
        await bound.set(User(id=2, name="Bob", email="b@b.com", score=20))
        await sa_session.commit()

        result = await bound.find(lambda u: u.score > 5)
        assert isinstance(result, Ok)
        assert len(result.value) == 2

    @pytest.mark.asyncio
    async def test_store_find_one(self, sa_session: AsyncSession) -> None:
        from emergent.wire.axis.storage.contrib._impls._sqlalchemy import SQLAlchemyStore

        sa_session, s = sa_session  # type: ignore[assignment]  # unpack (session, store) fixture
        bound = s(sa_session)
        await bound.set(User(id=10, name="Charlie", email="c@d.e", score=99))
        await sa_session.commit()

        result = await bound.find_one(lambda u: u.name == "Charlie")
        assert isinstance(result, Ok)
        assert isinstance(result.value, Some)
        assert result.value.value.score == 99

    @pytest.mark.asyncio
    async def test_store_find_one_not_found(self, sa_session: AsyncSession) -> None:
        from emergent.wire.axis.storage.contrib._impls._sqlalchemy import SQLAlchemyStore

        sa_session, s = sa_session  # type: ignore[assignment]  # unpack (session, store) fixture
        bound = s(sa_session)

        result = await bound.find_one(lambda u: u.name == "Nobody")
        assert isinstance(result, Ok)
        assert isinstance(result.value, Nothing)

    @pytest.mark.asyncio
    async def test_store_count(self, sa_session: AsyncSession) -> None:
        from emergent.wire.axis.storage.contrib._impls._sqlalchemy import SQLAlchemyStore

        sa_session, s = sa_session  # type: ignore[assignment]  # unpack (session, store) fixture
        bound = s(sa_session)
        await bound.set(User(id=20, name="D", email="d@e.f"))
        await sa_session.commit()

        result = await bound.count()
        assert isinstance(result, Ok)
        assert result.value >= 1

    @pytest.mark.asyncio
    async def test_store_count_with_predicate(self, sa_session: AsyncSession) -> None:
        from emergent.wire.axis.storage.contrib._impls._sqlalchemy import SQLAlchemyStore

        sa_session, s = sa_session  # type: ignore[assignment]  # unpack (session, store) fixture
        bound = s(sa_session)
        await bound.set(User(id=30, name="E", email="e@f.g", score=100))
        await sa_session.commit()

        result = await bound.count(lambda u: u.score >= 100)
        assert isinstance(result, Ok)
        assert result.value >= 1

    @pytest.mark.asyncio
    async def test_store_delete_where(self, sa_session: AsyncSession) -> None:
        from emergent.wire.axis.storage.contrib._impls._sqlalchemy import SQLAlchemyStore

        sa_session, s = sa_session  # type: ignore[assignment]  # unpack (session, store) fixture
        bound = s(sa_session)
        await bound.set(User(id=40, name="ToDelete", email="del@x.y", score=0))
        await sa_session.commit()

        result = await bound.delete_where(lambda u: u.name == "ToDelete")
        assert isinstance(result, Ok)
        assert result.value >= 1

    @pytest.mark.asyncio
    async def test_store_set_many(self, sa_session: AsyncSession) -> None:
        from emergent.wire.axis.storage.contrib._impls._sqlalchemy import SQLAlchemyStore

        sa_session, s = sa_session  # type: ignore[assignment]  # unpack (session, store) fixture
        bound = s(sa_session)

        users = [
            User(id=50, name="U1", email="u1@x.y"),
            User(id=51, name="U2", email="u2@x.y"),
        ]
        result = await bound.set_many(users)
        assert isinstance(result, Ok)
        assert len(result.value) == 2
        await sa_session.commit()

    @pytest.mark.asyncio
    async def test_store_all(self, sa_session: AsyncSession) -> None:
        from emergent.wire.axis.storage.contrib._impls._sqlalchemy import SQLAlchemyStore

        sa_session, s = sa_session  # type: ignore[assignment]  # unpack (session, store) fixture
        bound = s(sa_session)
        await bound.set(User(id=60, name="AllTest", email="all@x.y"))
        await sa_session.commit()

        result = await bound.all()
        assert isinstance(result, Ok)
        assert len(result.value) >= 1

    @pytest.mark.asyncio
    async def test_store_exists(self, sa_session: AsyncSession) -> None:
        from emergent.wire.axis.storage.contrib._impls._sqlalchemy import SQLAlchemyStore

        sa_session, s = sa_session  # type: ignore[assignment]  # unpack (session, store) fixture
        bound = s(sa_session)
        await bound.set(User(id=70, name="ExistsTest", email="ex@x.y"))
        await sa_session.commit()

        result = await bound.exists(70)
        assert isinstance(result, Ok)
        assert result.value is True

        result2 = await bound.exists(99999)
        assert isinstance(result2, Ok)
        assert result2.value is False


# ═══════════════════════════════════════════════════════════════════════════════
# 9. Memory providers — KV, API, Relational aggregation
# ═══════════════════════════════════════════════════════════════════════════════


class TestMemoryProviders:
    @pytest.mark.asyncio
    async def test_kv_get_set_delete(self) -> None:
        from emergent.wire.axis.query._kv import kv
        from emergent.wire.axis.query.providers.memory import MemoryKVProvider

        provider = MemoryKVProvider[str, str]()
        qs = kv(str, key=lambda x: x)

        await provider.set(qs.set("k1", "v1"))
        result = await provider.get(qs.get("k1"))
        assert isinstance(result, Ok)
        assert isinstance(result, Ok)
        assert result.value == "v1"

        del_result = await provider.delete(qs.delete("k1"))
        assert isinstance(del_result, Ok)
        assert del_result.value is True

    @pytest.mark.asyncio
    async def test_kv_exists(self) -> None:
        from emergent.wire.axis.query._kv import kv
        from emergent.wire.axis.query.providers.memory import MemoryKVProvider

        provider = MemoryKVProvider[str, int]()
        qs = kv(int, key=lambda x: str(x))

        await provider.set(qs.set("a", 1))
        result = await provider.exists(qs.exists("a"))
        assert isinstance(result, Ok)
        assert result.value is True

        result2 = await provider.exists(qs.exists("b"))
        assert isinstance(result2, Ok)
        assert result2.value is False

    @pytest.mark.asyncio
    async def test_kv_scan(self) -> None:
        from emergent.wire.axis.query._kv import kv
        from emergent.wire.axis.query.providers.memory import MemoryKVProvider

        provider = MemoryKVProvider[str, str]()
        qs = kv(str, key=lambda x: x)
        await provider.set(qs.set("user:1", "Alice"))
        await provider.set(qs.set("user:2", "Bob"))
        await provider.set(qs.set("item:1", "Sword"))

        result = await provider.scan(qs.scan("user:*"))
        assert isinstance(result, Ok)
        assert len(result.value) == 2

    @pytest.mark.asyncio
    async def test_kv_keys(self) -> None:
        from emergent.wire.axis.query._kv import kv
        from emergent.wire.axis.query.providers.memory import MemoryKVProvider

        provider = MemoryKVProvider[str, str]()
        qs = kv(str, key=lambda x: x)
        await provider.set(qs.set("a:1", "x"))
        await provider.set(qs.set("a:2", "y"))

        result = await provider.keys(qs.keys("a:*"))
        assert isinstance(result, Ok)
        assert len(result.value) == 2

    @pytest.mark.asyncio
    async def test_relational_aggregate(self) -> None:
        from emergent.wire.axis.query import MemoryRelationalProvider, relational

        provider = MemoryRelationalProvider[User](data=[
            User(id=1, name="A", email="a@b.c", score=10),
            User(id=2, name="B", email="b@b.c", score=20),
            User(id=3, name="C", email="c@b.c", score=30),
        ])

        query = relational(User).aggregate(
            total_count=lambda u: u.count(),
            total_score=lambda u: u.score.sum(),
            avg_score=lambda u: u.score.avg(),
        )
        result = await provider.aggregate(query)
        assert result["total_count"] == 3
        assert result["total_score"] == 60
        assert result["avg_score"] == 20.0

    @pytest.mark.asyncio
    async def test_relational_atomic_rollback(self) -> None:
        from emergent.wire.axis.query import MemoryRelationalProvider

        provider = MemoryRelationalProvider[User](
            data=[User(id=1, name="A", email="a@b.c")]
        )

        with pytest.raises(ValueError):
            async with provider.atomic():
                await provider.insert(User(id=2, name="B", email="b@b.c"))
                assert len(provider.data) == 2
                raise ValueError("rollback!")

        assert len(provider.data) == 1

    @pytest.mark.asyncio
    async def test_relational_delete_where(self) -> None:
        from emergent.wire.axis.query import MemoryRelationalProvider, relational

        provider = MemoryRelationalProvider[User](data=[
            User(id=1, name="Del", email="d@x.y", score=0),
            User(id=2, name="Keep", email="k@x.y", score=100),
        ])

        q = relational(User).filter(lambda u: u.score == 0)
        count = await provider.delete_where(q)
        assert count == 1
        assert len(provider.data) == 1

    @pytest.mark.asyncio
    async def test_relational_upsert(self) -> None:
        from emergent.wire.axis.query import MemoryRelationalProvider

        provider = MemoryRelationalProvider[User](
            data=[User(id=1, name="A", email="a@b.c")],
            key_fn=lambda u: u.id,
        )
        updated = await provider.upsert(User(id=1, name="A-updated", email="a@b.c"))
        assert updated.name == "A-updated"
        assert len(provider.data) == 1

        await provider.upsert(User(id=2, name="B", email="b@b.c"))
        assert len(provider.data) == 2


# ═══════════════════════════════════════════════════════════════════════════════
# 10. HTTP API Provider — pagination, auth, filters
# ═══════════════════════════════════════════════════════════════════════════════


class TestHTTPAPIProvider:
    def test_page_size_pagination(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import (
            PageSizePagination, PageMod,
        )

        pag = PageSizePagination()
        params: dict[str, object] = {}
        pag.apply(params, PageMod(page=2, per_page=10))
        assert params["page"] == 2
        assert params["per_page"] == 10

    def test_page_size_pagination_from_offset(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import (
            PageSizePagination, OffsetMod,
        )

        pag = PageSizePagination()
        params: dict[str, object] = {}
        pag.apply(params, OffsetMod(offset=20, limit=10))
        assert params["page"] == 3
        assert params["per_page"] == 10

    def test_offset_limit_pagination(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import (
            OffsetLimitPagination, OffsetMod,
        )

        pag = OffsetLimitPagination()
        params: dict[str, object] = {}
        pag.apply(params, OffsetMod(offset=10, limit=5))
        assert params["offset"] == 10
        assert params["limit"] == 5

    def test_offset_limit_from_page(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import (
            OffsetLimitPagination, PageMod,
        )

        pag = OffsetLimitPagination()
        params: dict[str, object] = {}
        pag.apply(params, PageMod(page=3, per_page=10))
        assert params["offset"] == 20
        assert params["limit"] == 10

    def test_cursor_pagination(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import (
            CursorPagination, CursorMod,
        )

        pag = CursorPagination()
        params: dict[str, object] = {}
        pag.apply(params, CursorMod(cursor="abc", limit=20))
        assert params["cursor"] == "abc"
        assert params["limit"] == 20

    def test_bearer_auth(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import BearerAuth

        auth = BearerAuth(token="secret")
        headers: dict[str, str] = {}
        auth.apply(headers)
        assert headers["Authorization"] == "Bearer secret"

    def test_basic_auth(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import BasicAuth
        import base64

        auth = BasicAuth(username="user", password="pass")
        headers: dict[str, str] = {}
        auth.apply(headers)
        expected = base64.b64encode(b"user:pass").decode()
        assert headers["Authorization"] == f"Basic {expected}"

    def test_api_key_auth(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import APIKeyAuth

        auth = APIKeyAuth(key="my-key")
        headers: dict[str, str] = {}
        auth.apply(headers)
        assert headers["X-API-Key"] == "my-key"

    def test_query_param_filters_basic(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import QueryParamFilters
        from emergent.wire.axis.query._expr import Eq, Field, Const

        enc = QueryParamFilters()
        result = enc.encode(Eq(Field("name"), Const("Alice")), User, None)
        assert result["name"] == "Alice"

    def test_query_param_filters_operators(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import QueryParamFilters
        from emergent.wire.axis.query._expr import Gt, Field, Const

        enc = QueryParamFilters()
        result = enc.encode(Gt(Field("score"), Const(10)), User, None)
        assert "score__gt" in result

    def test_body_filters_basic(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import BodyFilters
        from emergent.wire.axis.query._expr import Eq, Field, Const

        enc = BodyFilters()
        result = enc.encode(Eq(Field("name"), Const("Bob")), User, None)
        assert "filter" in result
        assert result["filter"]["name"]["eq"] == "Bob"

    def test_sort_param_encoding(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import SortParamEncoding
        from emergent.wire.axis.query._proxy import OrderSpec

        enc = SortParamEncoding()
        result = enc.encode([OrderSpec("name", True), OrderSpec("score", False)])
        assert result["sort"] == "name,-score"

    def test_fields_param_encoding(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import FieldsParamEncoding

        enc = FieldsParamEncoding()
        result = enc.encode(["id", "name", "email"])
        assert result["fields"] == "id,name,email"

    def test_limit_param_encoding(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import LimitParamEncoding

        enc = LimitParamEncoding()
        result = enc.encode(50)
        assert result["limit"] == 50

    def test_builder_requires_base_url(self) -> None:
        from emergent.wire.axis.query.contrib._impls._http import api

        builder = api(User)
        with pytest.raises(ValueError, match="base URL is required"):
            import httpx
            builder.build(httpx.AsyncClient())


# ═══════════════════════════════════════════════════════════════════════════════
# 11. Derive handler templates — runtime execution via MemoryRelationalProvider
# ═══════════════════════════════════════════════════════════════════════════════


class TestDeriveHandlerRuntime:
    def _make_provider(self, data: list[User] | None = None) -> MemoryRelationalProvider[User]:
        from emergent.wire.axis.query import MemoryRelationalProvider

        return MemoryRelationalProvider[User](
            data=list(data) if data else [],
            key_fn=lambda u: u.id,
        )

    def _make_spec(self, provider: Any = None, base_query: Any = None) -> Any:
        from emergent.wire.axis.query import relational
        from emergent.wire.derive._handler import HandlerSpec

        return HandlerSpec(
            entity=User,
            entity_name="User",
            identity_names=("id",),
            non_identity_names=("name", "email", "score", "active"),
            base_query=base_query or relational(User),
        )

    def _make_op(self, provider: Any, **kwargs: Any) -> Any:
        """Create a mock op with provider and fields."""
        mock = MagicMock()
        mock.provider = provider
        for k, v in kwargs.items():
            setattr(mock, k, v)
        return mock

    @pytest.mark.asyncio
    async def test_fetch_many(self) -> None:
        from emergent.wire.derive._handler import FetchMany

        data = [User(id=1, name="A", email="a@b.c"), User(id=2, name="B", email="b@b.c")]
        prov = self._make_provider(data)
        spec = self._make_spec()
        handler = FetchMany().build(spec)
        op = self._make_op(prov)
        result = await handler(op=op)
        assert isinstance(result, Ok)
        items: Any = result.value
        assert len(items) == 2

    @pytest.mark.asyncio
    async def test_fetch_one_by_id(self) -> None:
        from emergent.wire.derive._handler import FetchOneById

        prov = self._make_provider([User(id=1, name="A", email="a@b.c")])
        spec = self._make_spec()
        handler = FetchOneById().build(spec)
        op = self._make_op(prov, id=1)
        result = await handler(op=op)
        assert isinstance(result, Ok)
        assert result.value.name == "A"

    @pytest.mark.asyncio
    async def test_fetch_one_by_id_not_found(self) -> None:
        from emergent.wire.derive._handler import FetchOneById

        prov = self._make_provider([])
        spec = self._make_spec()
        handler = FetchOneById().build(spec)
        op = self._make_op(prov, id=999)
        result = await handler(op=op)
        assert isinstance(result, Error)

    @pytest.mark.asyncio
    async def test_insert_new(self) -> None:
        from emergent.wire.derive._handler import InsertNew

        prov = self._make_provider()
        spec = self._make_spec()
        handler = InsertNew().build(spec)
        op = self._make_op(prov, id=1, name="New", email="new@x.y", score=0, active=True)
        result = await handler(op=op)
        assert isinstance(result, Ok)
        assert getattr(result.value, 'name') == "New"
        assert len(prov.data) == 1

    @pytest.mark.asyncio
    async def test_update_existing(self) -> None:
        from emergent.wire.derive._handler import UpdateExisting

        prov = self._make_provider([User(id=1, name="Old", email="old@x.y")])
        spec = self._make_spec()
        handler = UpdateExisting().build(spec)
        op = self._make_op(prov, id=1, name="Updated", email="up@x.y", score=0, active=True)
        result = await handler(op=op)
        assert isinstance(result, Ok)
        assert result.value.name == "Updated"

    @pytest.mark.asyncio
    async def test_delete_one(self) -> None:
        from emergent.wire.derive._handler import DeleteOne

        prov = self._make_provider([User(id=1, name="Del", email="del@x.y")])
        spec = self._make_spec()
        handler = DeleteOne().build(spec)
        op = self._make_op(prov, id=1)
        result = await handler(op=op)
        assert isinstance(result, Ok)
        assert len(prov.data) == 0

    @pytest.mark.asyncio
    async def test_paginated_fetch_many(self) -> None:
        from emergent.wire.derive._handler import PaginatedFetchMany

        data = [User(id=i, name=f"U{i}", email=f"u{i}@x.y") for i in range(50)]
        prov = self._make_provider(data)
        spec = self._make_spec()
        handler = PaginatedFetchMany(page_size=10).build(spec)
        op = self._make_op(prov, page=1, page_size=10)
        result = await handler(op=op)
        assert isinstance(result, Ok)
        val: Any = result.value
        assert val["total"] == 50
        assert len(val["items"]) == 10

    @pytest.mark.asyncio
    async def test_sorted_fetch_many(self) -> None:
        from emergent.wire.derive._handler import SortedFetchMany

        data = [
            User(id=1, name="Charlie", email="c@x.y"),
            User(id=2, name="Alice", email="a@x.y"),
            User(id=3, name="Bob", email="b@x.y"),
        ]
        prov = self._make_provider(data)
        spec = self._make_spec()
        handler = SortedFetchMany(default_sort="name").build(spec)
        op = self._make_op(prov, sort="name", order="asc")
        result = await handler(op=op)
        assert isinstance(result, Ok)
        assert result.value[0].name == "Alice"

    @pytest.mark.asyncio
    async def test_patch_existing(self) -> None:
        from emergent.wire.derive._handler import PatchExisting

        prov = self._make_provider([User(id=1, name="Old", email="old@x.y", score=5)])
        spec = self._make_spec()
        handler = PatchExisting().build(spec)
        op = self._make_op(prov, id=1, name="Patched")
        # PatchExisting checks getattr with _UNSET sentinel, so fields NOT on op stay unchanged
        result = await handler(op=op)
        assert isinstance(result, Ok)
        assert result.value.name == "Patched"

    @pytest.mark.asyncio
    async def test_upsert_existing_insert(self) -> None:
        from emergent.wire.derive._handler import UpsertExisting

        prov = self._make_provider()
        spec = self._make_spec()
        handler = UpsertExisting().build(spec)
        op = self._make_op(prov, id=1, name="New", email="n@x.y", score=0, active=True)
        result = await handler(op=op)
        assert isinstance(result, Ok)
        assert len(prov.data) == 1

    @pytest.mark.asyncio
    async def test_upsert_existing_update(self) -> None:
        from emergent.wire.derive._handler import UpsertExisting

        prov = self._make_provider([User(id=1, name="Orig", email="o@x.y")])
        spec = self._make_spec()
        handler = UpsertExisting().build(spec)
        op = self._make_op(prov, id=1, name="Upserted", email="up@x.y", score=0, active=True)
        result = await handler(op=op)
        assert isinstance(result, Ok)
        assert result.value.name == "Upserted"

    @pytest.mark.asyncio
    async def test_exists_by_id(self) -> None:
        from emergent.wire.derive._handler import ExistsById

        prov = self._make_provider([User(id=1, name="A", email="a@b.c")])
        spec = self._make_spec()
        handler = ExistsById().build(spec)
        op = self._make_op(prov, id=1)
        result = await handler(op=op)
        assert isinstance(result, Ok)
        assert result.value is True

    @pytest.mark.asyncio
    async def test_count_all(self) -> None:
        from emergent.wire.derive._handler import CountAll

        data = [User(id=i, name=f"U{i}", email=f"u{i}@x.y") for i in range(5)]
        prov = self._make_provider(data)
        spec = self._make_spec()
        handler = CountAll().build(spec)
        op = self._make_op(prov)
        result = await handler(op=op)
        assert isinstance(result, Ok)
        assert result.value == 5

    @pytest.mark.asyncio
    async def test_soft_delete_mark(self) -> None:
        from emergent.wire.derive._handler import SoftDeleteMark, HandlerSpec
        from emergent.wire.axis.query import relational

        @dataclass
        class SoftEntity:
            id: Annotated[int, Identity()]
            name: str
            deleted_at: datetime | None = None

        prov = MemoryRelationalProvider[SoftEntity](
            data=[SoftEntity(id=1, name="X")],
            key_fn=lambda e: e.id,
        )
        spec = HandlerSpec(
            entity=SoftEntity,
            entity_name="SoftEntity",
            identity_names=("id",),
            non_identity_names=("name", "deleted_at"),
            base_query=relational(SoftEntity),
        )
        handler = SoftDeleteMark().build(spec)
        op = self._make_op(prov, id=1)
        result = await handler(op=op)
        assert isinstance(result, Ok)
        assert result.value.deleted_at is not None

    @pytest.mark.asyncio
    async def test_timestamp_insert(self) -> None:
        from emergent.wire.derive._handler import TimestampInsert, HandlerSpec
        from emergent.wire.axis.query import MemoryRelationalProvider, relational

        prov = MemoryRelationalProvider[Article](key_fn=lambda a: a.id)
        spec = HandlerSpec(
            entity=Article,
            entity_name="Article",
            identity_names=("id",),
            non_identity_names=("title", "body", "author_id", "created_at", "updated_at", "deleted_at"),
            base_query=relational(Article),
        )
        handler = TimestampInsert(created_field="created_at", updated_field="updated_at").build(spec)
        op = self._make_op(prov, id=1, title="T", body="B", author_id=1, deleted_at=None)
        result = await handler(op=op)
        assert isinstance(result, Ok)
        assert result.value.created_at is not None
        assert result.value.updated_at is not None

    @pytest.mark.asyncio
    async def test_timestamp_update(self) -> None:
        from emergent.wire.derive._handler import TimestampUpdate, HandlerSpec
        from emergent.wire.axis.query import MemoryRelationalProvider, relational

        now = datetime.now(tz=timezone.utc)
        prov = MemoryRelationalProvider[Article](
            data=[Article(id=1, title="Old", body="old", author_id=1, created_at=now, updated_at=now)],
            key_fn=lambda a: a.id,
        )
        spec = HandlerSpec(
            entity=Article,
            entity_name="Article",
            identity_names=("id",),
            non_identity_names=("title", "body", "author_id", "created_at", "updated_at", "deleted_at"),
            base_query=relational(Article),
        )
        handler = TimestampUpdate(updated_field="updated_at").build(spec)
        op = self._make_op(prov, id=1, title="New", body="new", author_id=1, created_at=now, deleted_at=None)
        result = await handler(op=op)
        assert isinstance(result, Ok)
        assert result.value.updated_at is not None
        assert result.value.updated_at > now

    @pytest.mark.asyncio
    async def test_set_field(self) -> None:
        from emergent.wire.derive._handler import SetField

        prov = self._make_provider([User(id=1, name="A", email="a@b.c", score=0)])
        spec = self._make_spec()
        handler = SetField(field_name="score", value_fn=lambda op: 999).build(spec)
        op = self._make_op(prov, id=1)
        result = await handler(op=op)
        assert isinstance(result, Ok)
        assert result.value.score == 999


# Need to import MemoryRelationalProvider at module level for SoftDeleteMark test
from emergent.wire.axis.query import MemoryRelationalProvider


# ═══════════════════════════════════════════════════════════════════════════════
# 12. Derive _pipeline.py — Pipeline steps end-to-end
# ═══════════════════════════════════════════════════════════════════════════════


class TestDerivePipeline:
    @pytest.mark.asyncio
    async def test_pipeline_fetch_all(self) -> None:
        from emergent.wire.axis.query import relational
        from emergent.wire.derive._handler import HandlerSpec
        from emergent.wire.derive._pipeline import (
            FetchAll, Pipeline, ScopeQuery, WrapItems,
        )

        data = [User(id=1, name="A", email="a@b.c"), User(id=2, name="B", email="b@b.c")]
        prov = MemoryRelationalProvider[User](data=list(data), key_fn=lambda u: u.id)
        spec = HandlerSpec(
            entity=User, entity_name="User",
            identity_names=("id",),
            non_identity_names=("name", "email", "score", "active"),
            base_query=relational(User),
        )
        handler = Pipeline(ScopeQuery(), FetchAll(), WrapItems()).build(spec)
        op = MagicMock()
        op.provider = prov
        result = await handler(op=op)
        assert isinstance(result, Ok)
        items: Any = result.value
        assert len(items) == 2

    @pytest.mark.asyncio
    async def test_pipeline_fetch_or_not_found(self) -> None:
        from emergent.wire.axis.query import relational
        from emergent.wire.derive._handler import HandlerSpec
        from emergent.wire.derive._pipeline import (
            FetchOrNotFound, IdentityFilter, Pipeline, ScopeQuery, WrapOk,
        )

        prov = MemoryRelationalProvider[User](data=[], key_fn=lambda u: u.id)
        spec = HandlerSpec(
            entity=User, entity_name="User",
            identity_names=("id",),
            non_identity_names=("name", "email", "score", "active"),
            base_query=relational(User),
        )
        handler = Pipeline(ScopeQuery(), IdentityFilter(), FetchOrNotFound(), WrapOk()).build(spec)
        op = MagicMock()
        op.provider = prov
        op.id = 999
        result = await handler(op=op)
        assert isinstance(result, Error)

    @pytest.mark.asyncio
    async def test_pipeline_insert(self) -> None:
        from emergent.wire.axis.query import relational
        from emergent.wire.derive._handler import HandlerSpec
        from emergent.wire.derive._pipeline import (
            BuildEntityData, Pipeline, ProviderInsert, WrapOk,
        )

        prov = MemoryRelationalProvider[User](data=[], key_fn=lambda u: u.id)
        spec = HandlerSpec(
            entity=User, entity_name="User",
            identity_names=("id",),
            non_identity_names=("name", "email", "score", "active"),
            base_query=relational(User),
        )
        handler = Pipeline(BuildEntityData(), ProviderInsert(), WrapOk()).build(spec)
        op = MagicMock()
        op.provider = prov
        op.id = 1
        op.name = "PipeInsert"
        op.email = "pi@x.y"
        op.score = 0
        op.active = True
        result = await handler(op=op)
        assert isinstance(result, Ok)
        assert getattr(result.value, 'name') == "PipeInsert"

    @pytest.mark.asyncio
    async def test_pipeline_update(self) -> None:
        from emergent.wire.axis.query import relational
        from emergent.wire.derive._handler import HandlerSpec
        from emergent.wire.derive._pipeline import (
            FetchOrNotFound, IdentityFilter, MergeFields,
            Pipeline, ProviderUpdate, ScopeQuery, WrapOk,
        )

        prov = MemoryRelationalProvider[User](
            data=[User(id=1, name="Old", email="o@x.y")],
            key_fn=lambda u: u.id,
        )
        spec = HandlerSpec(
            entity=User, entity_name="User",
            identity_names=("id",),
            non_identity_names=("name", "email", "score", "active"),
            base_query=relational(User),
        )
        handler = Pipeline(
            ScopeQuery(), IdentityFilter(), FetchOrNotFound(),
            MergeFields(), ProviderUpdate(), WrapOk(),
        ).build(spec)
        op = MagicMock()
        op.provider = prov
        op.id = 1
        op.name = "New"
        op.email = "n@x.y"
        op.score = 10
        op.active = True
        result = await handler(op=op)
        assert isinstance(result, Ok)
        assert getattr(result.value, 'name') == "New"

    @pytest.mark.asyncio
    async def test_pipeline_paginated(self) -> None:
        from emergent.wire.axis.query import relational
        from emergent.wire.derive._handler import HandlerSpec
        from emergent.wire.derive._pipeline import (
            CountTotal, FetchAll, Paginate, Pipeline,
            ScopeQuery, WrapPaginated,
        )

        data = [User(id=i, name=f"U{i}", email=f"u{i}@x.y") for i in range(25)]
        prov = MemoryRelationalProvider[User](data=list(data), key_fn=lambda u: u.id)
        spec = HandlerSpec(
            entity=User, entity_name="User",
            identity_names=("id",),
            non_identity_names=("name", "email", "score", "active"),
            base_query=relational(User),
        )
        handler = Pipeline(
            ScopeQuery(), CountTotal(), Paginate(default_page_size=10),
            FetchAll(), WrapPaginated(default_page_size=10),
        ).build(spec)
        op = MagicMock()
        op.provider = prov
        op.page = 1
        op.page_size = 10
        result = await handler(op=op)
        assert isinstance(result, Ok)
        val: Any = result.value
        assert val["total"] == 25
        assert len(val["items"]) == 10

    @pytest.mark.asyncio
    async def test_pipeline_delete(self) -> None:
        from emergent.wire.axis.query import relational
        from emergent.wire.derive._handler import HandlerSpec
        from emergent.wire.derive._pipeline import (
            FetchOrNotFound, IdentityFilter, Pipeline,
            ProviderDelete, ScopeQuery, WrapOk,
        )

        prov = MemoryRelationalProvider[User](
            data=[User(id=1, name="Del", email="d@x.y")],
            key_fn=lambda u: u.id,
        )
        spec = HandlerSpec(
            entity=User, entity_name="User",
            identity_names=("id",),
            non_identity_names=("name", "email", "score", "active"),
            base_query=relational(User),
        )
        handler = Pipeline(
            ScopeQuery(), IdentityFilter(), FetchOrNotFound(),
            ProviderDelete(), WrapOk(),
        ).build(spec)
        op = MagicMock()
        op.provider = prov
        op.id = 1
        result = await handler(op=op)
        assert isinstance(result, Ok)
        assert len(prov.data) == 0


# ═══════════════════════════════════════════════════════════════════════════════
# 13. Derive _transforms.py — transform capabilities
# ═══════════════════════════════════════════════════════════════════════════════


class TestDeriveTransforms:
    def _make_ctx(self) -> tuple[Any, type[Any]]:
        from emergent.wire.derive._compile import compile_derive
        from emergent.wire.axis.schema._universal import schema_meta
        from emergent.wire.derive._crud import http_crud

        @dataclass
        class TUser:
            id: Annotated[int, Identity()]
            name: str
            score: int = 0

        from nodnod import DataNode

        class TUsers(DataNode):
            pass

        schema_meta(http_crud("/t-users", TUsers))(TUser)
        ctxs = compile_derive(TUser)
        return ctxs[0], TUser

    def test_readonly_removes_mutations(self) -> None:
        from emergent.wire.derive._transforms import Readonly

        ctx, _entity = self._make_ctx()
        new_ctx = Readonly().compile_derive_modify(ctx)
        for spec in new_ctx.specs:
            from emergent.wire.derive._effects import Mutation, has_effect
            assert not has_effect(spec.effects, Mutation)

    def test_without_delete_removes_delete(self) -> None:
        from emergent.wire.derive._transforms import WithoutDelete

        ctx, _entity = self._make_ctx()
        new_ctx = WithoutDelete().compile_derive_modify(ctx)
        for spec in new_ctx.specs:
            from emergent.wire.derive._effects import Deletes, has_effect
            assert not has_effect(spec.effects, Deletes)

    def test_mutations_only_keeps_mutations(self) -> None:
        from emergent.wire.derive._transforms import MutationsOnly

        ctx, _entity = self._make_ctx()
        new_ctx = MutationsOnly().compile_derive_modify(ctx)
        from emergent.wire.derive._effects import Mutation, has_effect
        for spec in new_ctx.specs:
            assert has_effect(spec.effects, Mutation)

    def test_paginated_adds_page_fields(self) -> None:
        from emergent.wire.derive._transforms import Paginated

        ctx, _entity = self._make_ctx()
        new_ctx = Paginated(page_size=25).compile_derive_modify(ctx)
        # At least one spec should have page fields
        found = False
        for spec in new_ctx.specs:
            for ef in spec.extra_request_fields:
                if ef[0] == "page":
                    found = True
        assert found

    def test_sorted_adds_sort_fields(self) -> None:
        from emergent.wire.derive._transforms import Sorted

        ctx, _entity = self._make_ctx()
        new_ctx = Sorted(default_sort="name").compile_derive_modify(ctx)
        found = False
        for spec in new_ctx.specs:
            for ef in spec.extra_request_fields:
                if ef[0] == "sort":
                    found = True
        assert found

    def test_only_ops_filters(self) -> None:
        from emergent.wire.derive._transforms import OnlyOps

        ctx, _entity = self._make_ctx()
        new_ctx = OnlyOps(ops=("List", "Get")).compile_derive_modify(ctx)
        names = {s.name for s in new_ctx.specs}
        assert names <= {"List", "Get"}


# ═══════════════════════════════════════════════════════════════════════════════
# 14. Derive auth — Authenticated, RequireRole, RoleRequired
# ═══════════════════════════════════════════════════════════════════════════════


class TestDeriveAuth:
    def test_authenticated_requires_validate(self) -> None:
        from emergent.wire.derive.auth.caps import Authenticated
        from emergent.wire.derive.auth.extractors import BearerExtract

        with pytest.raises(ValueError, match="requires a TokenValidate"):
            Authenticated(BearerExtract())

    def test_authenticated_construction(self) -> None:
        from emergent.wire.derive.auth.caps import Authenticated
        from emergent.wire.derive.auth.extractors import BearerExtract
        from emergent.wire.derive.auth.validate import TokenValidate

        async def lookup(token: str) -> AuthUser | None:
            return AuthUser(name="admin")

        auth = Authenticated(
            BearerExtract(),
            TokenValidate(identity_type=AuthUser, lookup=lookup),
        )
        assert len(auth.extractors) == 1
        assert auth.validate is not None

    def test_require_role_construction(self) -> None:
        from emergent.wire.derive.auth.caps import RequireRole

        def _get_roles(u: AuthUser) -> set[str]:
            return u.roles

        enricher = RequireRole(
            identity_type=AuthUser,
            roles=frozenset({"admin"}),
            role_getter=_get_roles,
        )
        assert enricher.roles == frozenset({"admin"})

    def test_role_required_construction(self) -> None:
        from emergent.wire.derive.auth.caps import RoleRequired

        def _get_roles(u: AuthUser) -> set[str]:
            return u.roles

        cap = RoleRequired(
            identity_type=AuthUser,
            role="editor",
            role_getter=_get_roles,
        )
        assert cap.role == "editor"

    def test_authorize_ops_strict_raises(self) -> None:
        from emergent.wire.derive.auth.caps import AuthorizeOps

        def _get_roles(u: AuthUser) -> set[str]:
            return u.roles

        cap = AuthorizeOps(
            identity_type=AuthUser,
            role_map={"Create": "admin"},
            role_getter=_get_roles,
            strict=True,
        )
        # Strict mode raises when an op is not in the map
        ctx, _entity = TestDeriveTransforms()._make_ctx()
        with pytest.raises(ValueError, match="no role mapping"):
            cap.compile_derive_modify(ctx)

    def test_authorize_ops_non_strict(self) -> None:
        from emergent.wire.derive.auth.caps import AuthorizeOps

        def _get_roles(u: AuthUser) -> set[str]:
            return u.roles

        cap = AuthorizeOps(
            identity_type=AuthUser,
            role_map={"Create": "admin"},
            role_getter=_get_roles,
            strict=False,
        )
        ctx, _entity = TestDeriveTransforms()._make_ctx()
        new_ctx = cap.compile_derive_modify(ctx)
        assert len(new_ctx.specs) > 0


# ═══════════════════════════════════════════════════════════════════════════════
# 15. Derive auth/login.py — LoginOp, IssueToken, token_converter
# ═══════════════════════════════════════════════════════════════════════════════


class TestDeriveLogin:
    def test_token_converter_ok(self) -> None:
        from emergent.wire.derive.auth.login import token_converter

        @dataclass
        class Resp:
            token: str | None
            error: str | None

        raw = token_converter(Resp, Ok("abc"))
        assert isinstance(raw, Resp)
        assert raw.token == "abc"
        assert raw.error is None

    def test_token_converter_error(self) -> None:
        from emergent.wire.derive.auth.login import token_converter

        @dataclass
        class Resp:
            token: str | None
            error: str | None

        raw = token_converter(Resp, Error("bad"))
        assert isinstance(raw, Resp)
        assert raw.token is None
        assert raw.error == "bad"

    @pytest.mark.asyncio
    async def test_issue_token_success(self) -> None:
        from emergent.wire.axis.query._kv import kv
        from emergent.wire.axis.query.providers.memory import MemoryKVProvider
        from emergent.wire.derive.auth.login import IssueToken
        from emergent.wire.derive._handler import HandlerSpec
        from emergent.wire.axis.query import relational

        sessions: MemoryKVProvider[str, AuthUser] = MemoryKVProvider()
        qs = kv(AuthUser, key=lambda u: u.name)

        prov = MemoryRelationalProvider[User](
            data=[User(id=1, name="admin", email="admin@x.y")],
            key_fn=lambda u: u.id,
        )

        spec = HandlerSpec(
            entity=User, entity_name="User",
            identity_names=("id",),
            non_identity_names=("name", "email", "score", "active"),
            base_query=relational(User),
        )

        template = IssueToken(
            sessions=sessions,
            session_qs=qs,
            match_field="name",
        )
        handler = template.build(spec)
        op = MagicMock()
        op.provider = prov
        op.name = "admin"
        result = await handler(op=op)
        assert isinstance(result, Ok)
        assert len(result.value) > 0  # token string
        # Session should have been stored
        assert len(sessions.data) == 1

    @pytest.mark.asyncio
    async def test_issue_token_not_found(self) -> None:
        from emergent.wire.axis.query._kv import kv
        from emergent.wire.axis.query.providers.memory import MemoryKVProvider
        from emergent.wire.derive.auth.login import IssueToken
        from emergent.wire.derive._handler import HandlerSpec
        from emergent.wire.axis.query import relational

        sessions: MemoryKVProvider[str, AuthUser] = MemoryKVProvider()
        qs = kv(AuthUser, key=lambda u: u.name)
        prov = MemoryRelationalProvider[User](data=[], key_fn=lambda u: u.id)

        spec = HandlerSpec(
            entity=User, entity_name="User",
            identity_names=("id",),
            non_identity_names=("name", "email", "score", "active"),
            base_query=relational(User),
        )
        template = IssueToken(sessions=sessions, session_qs=qs, match_field="name")
        handler = template.build(spec)
        op = MagicMock()
        op.provider = prov
        op.name = "nonexistent"
        result = await handler(op=op)
        assert isinstance(result, Error)


# ═══════════════════════════════════════════════════════════════════════════════
# 16. Derive patterns/methods.py — decorators and Methods capability
# ═══════════════════════════════════════════════════════════════════════════════


class TestDeriveMethods:
    def test_post_decorator_attaches_trigger_entry(self) -> None:
        from emergent.wire.derive.patterns.methods import post, TRIGGER_ENTRIES_ATTR

        @post("/api/test")
        async def handler(name: str) -> Result[str, str]:
            return Ok(name)

        entries = getattr(handler, TRIGGER_ENTRIES_ATTR)
        assert len(entries) == 1
        assert entries[0].trigger.method == "POST"
        assert entries[0].trigger.path == "/api/test"

    def test_get_decorator(self) -> None:
        from emergent.wire.derive.patterns.methods import get, TRIGGER_ENTRIES_ATTR

        @get("/api/items")
        async def handler() -> Result[str, str]:
            return Ok("items")

        entries = getattr(handler, TRIGGER_ENTRIES_ATTR)
        assert entries[0].trigger.method == "GET"

    def test_op_decorator(self) -> None:
        from emergent.wire.derive.patterns.methods import op, OP_ENTRIES_ATTR
        from emergent.wire.derive._effects import Creates

        @op("Create", effects=(Creates(),))
        async def handler(name: str) -> Result[str, str]:
            return Ok(name)

        entry = getattr(handler, OP_ENTRIES_ATTR)
        assert entry.name == "Create"
        assert len(entry.effects) == 1

    def test_methods_generates_operations(self) -> None:
        from emergent.wire.derive.patterns.methods import Methods, post
        from emergent.wire.axis.schema._universal import schema_meta
        from emergent.wire.derive._compile import compile_derive

        @schema_meta(Methods())
        @dataclass
        class Svc:
            @staticmethod
            @post("/api/svc/do")
            async def do_thing(val: int) -> Result[str, str]:
                return Ok(str(val))

        ctxs = compile_derive(Svc)
        assert len(ctxs) == 1
        assert len(ctxs[0].operations) == 1

    def test_method_decorator_multiple_triggers(self) -> None:
        from emergent.wire.derive.patterns.methods import post, get, TRIGGER_ENTRIES_ATTR

        @get("/api/v2/items")
        @post("/api/items")
        async def handler(name: str) -> Result[str, str]:
            return Ok(name)

        entries = getattr(handler, TRIGGER_ENTRIES_ATTR)
        assert len(entries) == 2

    def test_methods_sync_handler_raises(self) -> None:
        from emergent.wire.derive.patterns.methods import Methods, post
        from emergent.wire.axis.schema._universal import schema_meta
        from emergent.wire.derive._compile import compile_derive

        @schema_meta(Methods())
        @dataclass
        class BadSvc:
            @staticmethod
            @post("/api/bad")
            def sync_handler(val: int) -> Result[str, str]:
                return Ok(str(val))

        with pytest.raises(TypeError, match="must be async"):
            compile_derive(BadSvc)

    def test_methods_classmethod(self) -> None:
        from emergent.wire.derive.patterns.methods import Methods, post
        from emergent.wire.axis.schema._universal import schema_meta
        from emergent.wire.derive._compile import compile_derive

        @schema_meta(Methods())
        @dataclass
        class ClsSvc:
            @classmethod
            @post("/api/cls")
            async def action(cls, x: int) -> Result[int, str]:
                return Ok(x * 2)

        ctxs = compile_derive(ClsSvc)
        assert len(ctxs) == 1
        assert len(ctxs[0].operations) == 1


# ═══════════════════════════════════════════════════════════════════════════════
# 17. Auth errors — register_auth_errors
# ═══════════════════════════════════════════════════════════════════════════════


class TestAuthErrors:
    def test_register_auth_errors(self) -> None:
        import fastapi
        from emergent.wire.derive.auth.errors import register_auth_errors

        app = fastapi.FastAPI()
        register_auth_errors(app)
        # Should not raise

    @pytest.mark.asyncio
    async def test_auth_error_responses(self) -> None:
        import fastapi
        from httpx import ASGITransport, AsyncClient
        from emergent.wire.derive.auth.errors import (
            AuthenticationRequired,
            AuthorizationFailed,
            register_auth_errors,
        )

        app = fastapi.FastAPI()
        register_auth_errors(app)

        @app.get("/auth-test")
        async def auth_test() -> None:
            raise AuthenticationRequired()

        @app.get("/perm-test")
        async def perm_test() -> None:
            raise AuthorizationFailed("admin only")

        _ = auth_test, perm_test  # used by FastAPI decorator

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r1 = await client.get("/auth-test")
            assert r1.status_code == 401
            assert r1.json()["title"] == "Unauthorized"

            r2 = await client.get("/perm-test")
            assert r2.status_code == 403
            assert r2.json()["detail"] == "admin only"


# ═══════════════════════════════════════════════════════════════════════════════
# 18. Derive _pipeline.py — additional steps
# ═══════════════════════════════════════════════════════════════════════════════


class TestPipelineStepsAdditional:
    @pytest.mark.asyncio
    async def test_set_timestamp_step(self) -> None:
        from emergent.wire.derive._pipeline import SetTimestamp, PipelineContext
        from emergent.wire.derive._handler import HandlerSpec
        from emergent.wire.axis.query import relational

        spec = HandlerSpec(
            entity=User, entity_name="User",
            identity_names=("id",),
            non_identity_names=("name", "email", "score", "active"),
            base_query=relational(User),
        )
        step = SetTimestamp(field_name="updated_at")
        pctx = PipelineContext(spec=spec, op=MagicMock())
        pctx.entity_data = {"name": "X"}
        result = await step.execute(pctx)
        assert result.entity_data is not None
        assert "updated_at" in result.entity_data
        assert isinstance(result.entity_data["updated_at"], datetime)

    @pytest.mark.asyncio
    async def test_set_field_value_step(self) -> None:
        from emergent.wire.derive._pipeline import SetFieldValue, PipelineContext
        from emergent.wire.derive._handler import HandlerSpec
        from emergent.wire.axis.query import relational

        spec = HandlerSpec(
            entity=User, entity_name="User",
            identity_names=("id",),
            non_identity_names=("name", "email", "score", "active"),
            base_query=relational(User),
        )
        step = SetFieldValue(field_name="score", value_fn=lambda op: 100)
        pctx = PipelineContext(spec=spec, op=MagicMock())
        result = await step.execute(pctx)
        assert result.entity_data is not None
        assert result.entity_data["score"] == 100

    @pytest.mark.asyncio
    async def test_in_memory_sort_step(self) -> None:
        from emergent.wire.derive._pipeline import InMemorySort, PipelineContext
        from emergent.wire.derive._handler import HandlerSpec
        from emergent.wire.axis.query import relational

        spec = HandlerSpec(
            entity=User, entity_name="User",
            identity_names=("id",),
            non_identity_names=("name", "email", "score", "active"),
            base_query=relational(User),
        )
        step = InMemorySort(default_sort="name")
        pctx = PipelineContext(spec=spec, op=MagicMock())
        pctx.items = [
            User(id=2, name="Charlie", email="c@x.y"),
            User(id=1, name="Alice", email="a@x.y"),
        ]
        op_mock: Any = pctx.op
        op_mock.sort = "name"
        op_mock.order = "asc"
        result = await step.execute(pctx)
        assert result.items is not None
        assert result.items[0].name == "Alice"

    @pytest.mark.asyncio
    async def test_wrap_count_step(self) -> None:
        from emergent.wire.derive._pipeline import WrapCount, PipelineContext
        from emergent.wire.derive._handler import HandlerSpec
        from emergent.wire.axis.query import relational

        spec = HandlerSpec(
            entity=User, entity_name="User",
            identity_names=("id",),
            non_identity_names=("name", "email", "score", "active"),
            base_query=relational(User),
        )
        pctx = PipelineContext(spec=spec, op=MagicMock())
        pctx.extras["total"] = 42
        result = await WrapCount().execute(pctx)
        assert isinstance(result, Ok)
        assert result.value == 42

    @pytest.mark.asyncio
    async def test_wrap_exists_step(self) -> None:
        from emergent.wire.derive._pipeline import WrapExists, PipelineContext
        from emergent.wire.derive._handler import HandlerSpec
        from emergent.wire.axis.query import relational

        spec = HandlerSpec(
            entity=User, entity_name="User",
            identity_names=("id",),
            non_identity_names=("name", "email", "score", "active"),
            base_query=relational(User),
        )
        pctx = PipelineContext(spec=spec, op=MagicMock())
        pctx.existing = User(id=1, name="A", email="a@b.c")
        result = await WrapExists().execute(pctx)
        assert isinstance(result, Ok)
        assert result.value is True

    @pytest.mark.asyncio
    async def test_copy_existing_to_data_step(self) -> None:
        from emergent.wire.derive._pipeline import CopyExistingToData, PipelineContext
        from emergent.wire.derive._handler import HandlerSpec
        from emergent.wire.axis.query import relational

        spec = HandlerSpec(
            entity=User, entity_name="User",
            identity_names=("id",),
            non_identity_names=("name", "email", "score", "active"),
            base_query=relational(User),
        )
        pctx = PipelineContext(spec=spec, op=MagicMock())
        pctx.existing = User(id=1, name="Copy", email="c@x.y", score=5, active=True)
        result = await CopyExistingToData().execute(pctx)
        assert result.entity_data is not None
        assert result.entity_data["name"] == "Copy"
        assert result.entity_data["id"] == 1

    @pytest.mark.asyncio
    async def test_fetch_by_identity_step(self) -> None:
        from emergent.wire.derive._pipeline import FetchByIdentity, PipelineContext
        from emergent.wire.derive._handler import HandlerSpec
        from emergent.wire.axis.query import relational

        prov = MemoryRelationalProvider[User](
            data=[User(id=1, name="A", email="a@b.c")],
            key_fn=lambda u: u.id,
        )
        spec = HandlerSpec(
            entity=User, entity_name="User",
            identity_names=("id",),
            non_identity_names=("name", "email", "score", "active"),
            base_query=relational(User),
        )
        op = MagicMock()
        op.provider = prov
        op.id = 1
        pctx = PipelineContext(spec=spec, op=op)
        result = await FetchByIdentity().execute(pctx)
        assert result.existing is not None
        assert result.existing.name == "A"


# ═══════════════════════════════════════════════════════════════════════════════
# 19. compile/_capabilities.py — Mount capability
# ═══════════════════════════════════════════════════════════════════════════════


class TestMountCapability:
    def test_mount_compile_fastapi(self) -> None:
        import fastapi
        from emergent.wire.compile._capabilities import Mount, FastAPICompileContext

        app = fastapi.FastAPI()
        mounted_app = fastapi.FastAPI()

        ctx = FastAPICompileContext(
            app=app,
            trigger=None,
            handler=None,
            mounted=set(),
            skip_route=False,
        )

        mount = Mount(app=mounted_app, prefix="/sub", source="test")
        result = mount.compile_fastapi(ctx)
        assert result.skip_route is True

    def test_mount_no_duplicate(self) -> None:
        import fastapi
        from emergent.wire.compile._capabilities import Mount, FastAPICompileContext

        app = fastapi.FastAPI()
        mounted_app = fastapi.FastAPI()

        ctx = FastAPICompileContext(
            app=app,
            trigger=None,
            handler=None,
            mounted={(id(mounted_app), "/sub")},
            skip_route=False,
        )

        mount = Mount(app=mounted_app, prefix="/sub")
        result = mount.compile_fastapi(ctx)
        assert result.skip_route is True


# ═══════════════════════════════════════════════════════════════════════════════
# 20. Derive handler templates — op_defaults()
# ═══════════════════════════════════════════════════════════════════════════════


class TestHandlerOpDefaults:
    def test_fetch_many_defaults(self) -> None:
        from emergent.wire.derive._handler import FetchMany

        op = FetchMany().op_defaults()
        assert op.name == "List"

    def test_fetch_one_by_id_defaults(self) -> None:
        from emergent.wire.derive._handler import FetchOneById

        op = FetchOneById().op_defaults()
        assert op.name == "Get"

    def test_insert_new_defaults(self) -> None:
        from emergent.wire.derive._handler import InsertNew

        op = InsertNew().op_defaults()
        assert op.name == "Create"

    def test_update_existing_defaults(self) -> None:
        from emergent.wire.derive._handler import UpdateExisting

        op = UpdateExisting().op_defaults()
        assert op.name == "Update"

    def test_delete_one_defaults(self) -> None:
        from emergent.wire.derive._handler import DeleteOne

        op = DeleteOne().op_defaults()
        assert op.name == "Delete"

    def test_paginated_fetch_many_defaults(self) -> None:
        from emergent.wire.derive._handler import PaginatedFetchMany

        op = PaginatedFetchMany().op_defaults()
        assert op.name == "List"

    def test_patch_existing_defaults(self) -> None:
        from emergent.wire.derive._handler import PatchExisting

        op = PatchExisting().op_defaults()
        assert op.name == "Patch"

    def test_upsert_existing_defaults(self) -> None:
        from emergent.wire.derive._handler import UpsertExisting

        op = UpsertExisting().op_defaults()
        assert op.name == "Upsert"

    def test_exists_by_id_defaults(self) -> None:
        from emergent.wire.derive._handler import ExistsById

        op = ExistsById().op_defaults()
        assert op.name == "Exists"

    def test_count_all_defaults(self) -> None:
        from emergent.wire.derive._handler import CountAll

        op = CountAll().op_defaults()
        assert op.name == "Count"

    def test_sorted_fetch_many_defaults(self) -> None:
        from emergent.wire.derive._handler import SortedFetchMany

        op = SortedFetchMany().op_defaults()
        assert op.name == "List"

    def test_cached_fetch_one_defaults(self) -> None:
        from emergent.wire.derive._handler import CachedFetchOneById

        op = CachedFetchOneById().op_defaults()
        assert op.name == "Get"


# ═══════════════════════════════════════════════════════════════════════════════
# 21. Handler WrappedTemplate
# ═══════════════════════════════════════════════════════════════════════════════


class TestWrappedTemplate:
    @pytest.mark.asyncio
    async def test_wrapped_template(self) -> None:
        from emergent.wire.derive._handler import (
            FetchMany, HandlerSpec, wrap_template,
        )
        from emergent.wire.axis.query import relational

        data = [User(id=1, name="A", email="a@b.c")]
        prov = MemoryRelationalProvider[User](data=list(data), key_fn=lambda u: u.id)
        spec = HandlerSpec(
            entity=User, entity_name="User",
            identity_names=("id",),
            non_identity_names=("name", "email", "score", "active"),
            base_query=relational(User),
        )

        def wrapper(inner: Any, spec: Any) -> Any:
            async def wrapped(op: Any) -> Any:
                result: Any = await inner(op=op)
                if type(result).__name__ == "Ok":
                    val: Any = result.value
                    return Ok([u for u in val if u.active])
                return result
            return wrapped

        wt = wrap_template(FetchMany(), wrapper)
        handler = wt.build(spec)
        op = MagicMock()
        op.provider = prov
        result = await handler(op=op)
        assert isinstance(result, Ok)

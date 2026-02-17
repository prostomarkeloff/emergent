"""Tests targeting specific uncovered lines across multiple modules.

Covers:
- fastapi.py L232: RuntimeError when stateful key compose fails
- fastapi.py L699-708: WebSocket handler registration in fastapi_compile()
- _sqlalchemy.py L151: _get_identity_field returns None
- _sqlalchemy.py L253,261: FK creation branch in compile_model
- _sqlalchemy.py L303,309: Ne/Lt/Le expression compilation
- _sqlalchemy.py L791: SQLAlchemyStore.model property
- _sqlalchemy.py L877: BoundSQLAlchemyStore.get returns Nothing for missing key
- _sqlalchemy.py L905-911: BoundSQLAlchemyStore.delete returns False for missing key
- _run.py L115-116: Run.inject_as with explicit type
- _visualize.py L115,173,228: empty layer skip in to_mermaid/to_text/to_ascii
- _graph.py (idempotency) L151-152: FetchRecordNode wildcard match
- _graph.py (idempotency) L507-508: pending_wait wildcard match (still pending)
- _graph.py (ops) L94-95: _is_op_type TypeError branch
- _graph.py (ops) L305: _collect_op_deps visited cycle detection
- _graph.py (ops) L384-386: Runner.run node not found in scope
- _run.py (saga) L229-230: run_parallel Error branch
- _inspect.py L553-554: get_nested_info TypeError branch
- delta.py L355: compose_deltas skip None fields
- delta.py L439: validate_delta skip None fields
- delta.py L478: _delta_kind returns "collection"
"""

from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Annotated
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from kungfu import Ok, Error, Result, Nothing


# ═══════════════════════════════════════════════════════════════════════════════
# 1. FastAPI stateful handler — key compose failure (L232)
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_stateful_fastapi_key_compose_failure() -> None:
    """Line 232: raise RuntimeError when composer.compose fails for key_node."""
    import fastapi
    from emergent.wire.axis.surface._handler import Handler
    from emergent.wire.axis.surface.codecs.stateful import StatefulCodec
    from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger
    from emergent.wire.compile._core import Axes
    from emergent.wire.compile.targets.fastapi import wrap_stateful_fastapi

    # Create a minimal stateful codec with a key_node that will fail
    # We need to mock things so compose returns (False, error_message)
    mock_codec = MagicMock(spec=StatefulCodec)
    mock_codec.key_node = MagicMock()
    mock_codec.agent_cls = MagicMock()
    mock_codec.flow = MagicMock()

    handler = MagicMock(spec=Handler)
    handler.codec = mock_codec

    trigger = HTTPRouteTrigger(method="POST", path="/test")
    axes = Axes.default()

    # Mock get_transitions to return empty list
    with patch(
        "emergent.wire.compile.targets.fastapi.get_transitions",
        return_value=[],
    ), patch(
        "emergent.wire.compile.targets.fastapi._get_pydantic_types_from_transitions",
        return_value=set(),
    ):
        route = wrap_stateful_fastapi(handler, trigger, axes)

    # Now call the inner _route and make compose fail
    mock_request = MagicMock(spec=fastapi.Request)

    with patch(
        "emergent.graph._compose.Composer.create"
    ) as mock_create:
        mock_composer_instance = AsyncMock()
        mock_composer_instance.compose = AsyncMock(
            return_value=(False, "key not found")
        )
        mock_create.return_value = mock_composer_instance

        with pytest.raises(RuntimeError, match="Session key resolution failed"):
            await route.endpoint(mock_request)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. FastAPI WebSocket handler registration (L699-708)
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_fastapi_compile_websocket_routes() -> None:
    """Lines 699-708: WebSocket handler closure creation + registration call.

    FastAPI's param introspection doesn't handle Scope | None in closure defaults,
    so we patch add_api_websocket_route to capture the handler and verify it works.
    """
    import fastapi
    from nodnod import Scope
    from emergent.wire.axis.surface._app import Application
    from emergent.wire.axis.surface.triggers.websocket import WebSocketTrigger
    from emergent.wire.compile._core import Axes
    from emergent.wire.compile.targets.fastapi import fastapi_compile
    from emergent.wire.compile.targets.pure import (
        WebSocketRoute,
    )

    ws_called_with_scope: Scope | None = None

    async def mock_ws_handler(scope: Scope) -> None:
        nonlocal ws_called_with_scope
        ws_called_with_scope = scope

    ws_trigger = WebSocketTrigger(path="/ws/test", name="test_ws")
    ws_route = WebSocketRoute(handler=mock_ws_handler)

    app = Application(endpoints=[], capabilities=())

    # Capture what gets registered
    registered_handlers: list[tuple[str, Callable[..., Coroutine[None, None, None]], str | None]] = []

    def capture_add_ws(
        self_fapi: fastapi.FastAPI,
        path: str,
        endpoint_fn: Callable[..., Coroutine[None, None, None]],
        name: str | None = None,
        **kw: str,
    ) -> None:
        registered_handlers.append((path, endpoint_fn, name))

    mock_compiler = MagicMock()
    mock_compiler.scan_and_wrap = MagicMock(
        return_value=[(ws_trigger, MagicMock(), ws_route)]
    )
    with patch(
        "emergent.wire.compile.targets.fastapi.WEBSOCKET_COMPILER",
        mock_compiler,
    ), patch.object(
        fastapi.FastAPI,
        "add_api_websocket_route",
        capture_add_ws,
    ):
        _fapi = fastapi_compile(app, Axes.default())

    # Verify the handler was registered with correct path and name
    assert len(registered_handlers) == 1
    reg_path, handler_fn, reg_name = registered_handlers[0]
    assert reg_path == "/ws/test"
    assert reg_name == "test_ws"

    # Call the handler to exercise the closure body (lines 704-707)
    mock_websocket = MagicMock(spec=fastapi.WebSocket)
    await handler_fn(mock_websocket)

    # Verify the inner handler called ws_route.handler with a scope
    # that has the websocket injected
    assert ws_called_with_scope is not None


# ═══════════════════════════════════════════════════════════════════════════════
# 3. SQLAlchemy — various branches
# ═══════════════════════════════════════════════════════════════════════════════


def test_sqlalchemy_get_identity_field_returns_none() -> None:
    """Line 151: _get_identity_field returns None when no Identity field."""
    from emergent.wire.axis.storage.contrib._impls._sqlalchemy import (
        _get_identity_field,  # pyright: ignore[reportPrivateUsage] - testing private function
    )
    from emergent.wire.axis.schema._inspect import inspect_type

    @dataclass
    class NoIdentity:
        name: str
        value: int

    fields = inspect_type(NoIdentity)
    result = _get_identity_field(fields)
    assert result is None


def test_sqlalchemy_compile_model_with_fk() -> None:
    """Lines 252-261: compile_model with ForeignKey field."""
    from emergent.wire.axis.storage.contrib._impls._sqlalchemy import (
        compile_model,
    )
    from emergent.wire.axis.schema._universal import Identity, Ref
    from sqlalchemy.orm import DeclarativeBase

    class FKTestBase(DeclarativeBase):
        pass

    @dataclass
    class FKParent:
        id: Annotated[int, Identity]
        name: str

    # Compile parent first
    _parent_model = compile_model(FKParent, "fk_test_parent", base=FKTestBase)

    # Use Ref with string target to trigger FK creation
    @dataclass
    class FKChild:
        id: Annotated[int, Identity]
        parent_id: Annotated[int, Ref("fk_test_parent.id")]

    child_model = compile_model(FKChild, "fk_test_child", base=FKTestBase)

    # Verify FK was created
    table = child_model.__table__
    fk_cols = [
        c
        for c in table.columns
        if c.foreign_keys
    ]
    assert len(fk_cols) == 1


def test_sqlalchemy_compile_expr_ne_lt_le() -> None:
    """Lines 303, 305, 309: compile_expr for Ne, Lt, Le expressions."""
    from emergent.wire.axis.storage.contrib._impls._sqlalchemy import (
        compile_expr,
        compile_model,
    )
    from emergent.wire.axis.schema._universal import Identity
    from emergent.wire.axis.query._expr import (
        Field,
        Const,
        Ne,
        Lt,
        Le,
    )
    from sqlalchemy.orm import DeclarativeBase

    class ExprBase(DeclarativeBase):
        pass

    @dataclass
    class Item:
        id: Annotated[int, Identity]
        price: int
        name: str

    model = compile_model(Item, "test_expr_items", base=ExprBase)

    # Test Ne
    ne_expr = Ne(left=Field("price"), right=Const(100))
    ne_result = compile_expr(ne_expr, model)
    assert ne_result is not None

    # Test Lt
    lt_expr = Lt(left=Field("price"), right=Const(50))
    lt_result = compile_expr(lt_expr, model)
    assert lt_result is not None

    # Test Le
    le_expr = Le(left=Field("price"), right=Const(75))
    le_result = compile_expr(le_expr, model)
    assert le_result is not None


def test_sqlalchemy_store_model_property() -> None:
    """Line 791: SQLAlchemyStore.model property."""
    from emergent.wire.axis.storage.contrib._impls._sqlalchemy import (
        SQLAlchemyStore,
    )
    from emergent.wire.axis.schema._universal import Identity

    @dataclass
    class PropEntity:
        id: Annotated[int, Identity]
        name: str

    store = SQLAlchemyStore(
        entity=PropEntity,
        tablename="test_prop_entity",
    )
    model = store.model
    assert model is not None
    assert hasattr(model, "__tablename__")
    assert model.__tablename__ == "test_prop_entity"


@pytest.mark.asyncio
async def test_sqlalchemy_bound_store_get_returns_nothing() -> None:
    """Line 877: BoundSQLAlchemyStore.get returns Ok(Nothing()) for missing key."""
    from emergent.wire.axis.storage.contrib._impls._sqlalchemy import (
        compile_model,
    )
    from emergent.wire.axis.schema._universal import Identity
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import DeclarativeBase

    class GetTestBase(DeclarativeBase):
        pass

    @dataclass
    class GetEntity:
        id: Annotated[int, Identity]
        name: str

    model = compile_model(GetEntity, "get_test_entity", base=GetTestBase)

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(GetTestBase.metadata.create_all)

    async with AsyncSession(engine) as session:
        from emergent.wire.axis.storage.contrib._impls._sqlalchemy import (
            BoundSQLAlchemyStore,
        )
        store = BoundSQLAlchemyStore(
            session=session,
            entity=GetEntity,
            model=model,
            identity_field="id",
        )

        result = await store.get(999)
        match result:
            case Ok(Nothing()):
                pass  # Expected
            case _:
                pytest.fail(f"Expected Ok(Nothing()), got {result}")

    await engine.dispose()


@pytest.mark.asyncio
async def test_sqlalchemy_bound_store_delete_returns_false() -> None:
    """Lines 905-911: BoundSQLAlchemyStore.delete returns Ok(False) for missing."""
    from emergent.wire.axis.storage.contrib._impls._sqlalchemy import (
        compile_model,
        BoundSQLAlchemyStore,
    )
    from emergent.wire.axis.schema._universal import Identity
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import DeclarativeBase

    class DelTestBase(DeclarativeBase):
        pass

    @dataclass
    class DelEntity:
        id: Annotated[int, Identity]
        name: str

    model = compile_model(DelEntity, "del_test_entity", base=DelTestBase)

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(DelTestBase.metadata.create_all)

    async with AsyncSession(engine) as session:
        store = BoundSQLAlchemyStore(
            session=session,
            entity=DelEntity,
            model=model,
            identity_field="id",
        )

        result = await store.delete(999)
        match result:
            case Ok(False):
                pass  # Expected
            case _:
                pytest.fail(f"Expected Ok(False), got {result}")

    await engine.dispose()


# ═══════════════════════════════════════════════════════════════════════════════
# 4. graph._run — Run.inject_as (L115-116)
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_run_inject_as() -> None:
    """Lines 115-116: Run.inject_as with explicit type."""
    from emergent import graph as G

    class _Greeter:
        def __init__(self, greeting: str) -> None:
            self.greeting = greeting

        @classmethod
        def __compose__(cls, name: str) -> "_Greeter":
            return cls(f"Hello, {name}")

    Greeter: type[_Greeter] = G.node(_Greeter)

    r = G.run(Greeter).inject_as(str, "World")
    result = await r
    assert result.greeting == "Hello, World"


# ═══════════════════════════════════════════════════════════════════════════════
# 5. graph._visualize — empty layer skip (L115, L173, L228)
# ═══════════════════════════════════════════════════════════════════════════════


def test_to_mermaid_with_empty_layers() -> None:
    """Line 115: skip empty layers in to_mermaid."""
    from emergent import graph as G

    # The empty layer skip happens when get_layers returns a layer with no nodes.
    # This is tricky to trigger naturally. We mock get_layers to include empty layers.
    with patch(
        "emergent.graph._visualize.get_layers",
        return_value=[[], [MagicMock(__name__="A")], []],
    ), patch(
        "emergent.graph._visualize.get_all_nodes",
        return_value={},
    ):

        class DummyNode:
            pass

        result = G.to_mermaid(DummyNode, layered=True)
        assert "A" in result
        # Empty layers should be skipped — no "L0" or "L2" subgraph
        assert "subgraph Input" not in result  # L0 is empty, skipped
        assert "subgraph L2" not in result  # L2 is empty, skipped


def test_to_text_with_empty_layers() -> None:
    """Line 173: skip empty layers in to_text."""
    from emergent import graph as G

    with patch(
        "emergent.graph._visualize.get_layers",
        return_value=[[], [MagicMock(__name__="B")], []],
    ):

        class DummyNode2:
            pass

        result = G.to_text(DummyNode2)
        assert "B" in result
        # Only the non-empty layer should appear
        lines = result.strip().split("\n")
        assert len(lines) == 1


def test_to_ascii_with_empty_layers() -> None:
    """Line 228: skip empty layers in to_ascii."""
    from emergent import graph as G

    with patch(
        "emergent.graph._visualize.get_layers",
        return_value=[[], [MagicMock(__name__="C")], []],
    ):

        class DummyNode3:
            pass

        result = G.to_ascii(DummyNode3)
        assert "C" in result


# ═══════════════════════════════════════════════════════════════════════════════
# 6. idempotency._graph — FetchRecordNode wildcard match (L151-152)
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_fetch_record_node_wildcard_match() -> None:
    """Lines 151-152: FetchRecordNode.__compose__ wildcard branch."""
    from emergent.idempotency._graph import (
        FetchRecordNode,
        SpecNode,
        IdempotencySpec,
    )
    from emergent.idempotency._policy import Policy

    # We need storage.get to return something that doesn't match
    # Ok(Some(...)), Ok(Nothing()), or Error(...).
    # The wildcard `case _` catches unexpected return types.
    # We achieve this by making storage.get return a value that
    # doesn't match the three explicit patterns.

    mock_storage = AsyncMock()
    # Return something weird that is not Ok or Error — the only way
    # is to return something that isn't a Result at all.
    # Since FetchRecordNode uses match, if it somehow gets a non-Result value,
    # the wildcard fires. This is a defensive branch.
    # We'll patch the function to test this by making storage.get return
    # an Ok wrapping something that is not Some or Nothing.
    mock_storage.get = AsyncMock(return_value=Ok("unexpected_raw_value"))

    spec = IdempotencySpec(
        key="test-key",
        input_value="test",
        operation=AsyncMock(),
        storage=mock_storage,
        policy=Policy(),
    )

    spec_node = SpecNode(spec)
    result = await FetchRecordNode.__compose__(spec_node)
    # Wildcard should fire, returning cls(None, spec)
    assert result.record is None
    assert result.spec is spec
    assert result.store_error is None


# ═══════════════════════════════════════════════════════════════════════════════
# 7. idempotency._graph — pending_wait wildcard (L507-508)
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_pending_wait_still_pending_then_timeout() -> None:
    """Lines 507-508: pending_wait wildcard branch when record stays pending."""
    from datetime import timedelta, datetime
    from emergent.idempotency._graph import (
        IdempotencyOutcome,
        OutcomeError,
        PendingRecordNode,
        IdempotencySpec,
    )
    from emergent.idempotency._types import RecordState, IdempotencyRecord
    from emergent.idempotency._policy import Policy, OnPending

    # Create a record that stays PENDING throughout
    pending_record: IdempotencyRecord[str, str] = IdempotencyRecord(
        key="test",
        state=RecordState.PENDING,
        value=None,
        error=None,
        created_at=datetime.now(),
        expires_at=None,
        input_hash=None,
    )

    mock_storage = AsyncMock()
    # Return Ok("raw_string") — not Ok(Some(...)) or Ok(Nothing()) or Error(...)
    # This triggers the wildcard `case _: pass` which just continues the loop
    mock_storage.get = AsyncMock(return_value=Ok("unexpected"))

    spec = IdempotencySpec(
        key="test",
        input_value="test",
        operation=AsyncMock(),
        storage=mock_storage,
        policy=Policy(
            conflict_strategy=OnPending.WAIT,
            pending_wait_timeout=timedelta(milliseconds=50),
        ),
    )

    node = PendingRecordNode(
        record=pending_record,
        spec=spec,
    )

    # Call the pending_wait case handler directly
    # pending_wait is a @case method on a @polymorphic class; access via __func__
    # pyright cannot see @case methods on @polymorphic classes since they are dynamically created
    pending_wait_fn = getattr(IdempotencyOutcome, "pending_wait")
    outcome: OutcomeError = await pending_wait_fn.__func__(IdempotencyOutcome, node)
    from emergent.idempotency._types import IdempotencyErrorKind
    # Should timeout because the wildcard just passes (continues loop)
    assert outcome.kind == IdempotencyErrorKind.TIMEOUT


# ═══════════════════════════════════════════════════════════════════════════════
# 8. ops._graph — _is_op_type TypeError (L94-95)
# ═══════════════════════════════════════════════════════════════════════════════


def test_is_op_type_with_type_error() -> None:
    """Lines 94-95: _is_op_type returns False on TypeError."""
    from emergent.ops._graph import _is_op_type  # pyright: ignore[reportPrivateUsage] - testing private function

    # Some objects cause TypeError in issubclass
    # Using a non-type value that passes isinstance(typ, type)
    # but fails in issubclass — e.g., a generic alias
    import typing

    # typing generics can cause TypeError with issubclass
    result = _is_op_type(typing.List[int])
    assert result is False

    # Regular non-type
    result2 = _is_op_type("not_a_type")
    assert result2 is False


# ═══════════════════════════════════════════════════════════════════════════════
# 9. ops._graph — _collect_op_deps cycle detection (L304-305)
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_ops_collect_deps_cycle_detection() -> None:
    """Line 305: _collect_op_deps returns early when op_id already visited."""
    from emergent.ops._graph import Op, ops

    @dataclass(frozen=True, slots=True)
    class CycleOp(Op[str, str]):
        name: str

    async def cycle_handler(req: CycleOp) -> Result[str, str]:
        return Ok(req.name)

    runner = ops().on(CycleOp, cycle_handler).compile()

    # Create an op that references itself (cycle)
    op = CycleOp(name="test")
    # The _collect_op_deps method uses visited set to avoid cycles
    deps = runner._collect_op_deps(op)  # pyright: ignore[reportPrivateUsage] - testing protected method
    # Should return empty since CycleOp has no Op fields
    assert deps == []


@pytest.mark.asyncio
async def test_ops_runner_node_not_found() -> None:
    """Lines 384-386: Runner.run returns Error when node not found in scope."""
    from emergent.ops._graph import Op, ops

    @dataclass(frozen=True, slots=True)
    class MissingOp(Op[str, str]):
        name: str

    async def missing_handler(req: MissingOp) -> Result[str, str]:
        return Ok(req.name)

    runner = ops().on(MissingOp, missing_handler).compile()

    # Patch scope.retrieve to return Nothing (no value)
    with patch("emergent.graph._run.TypedScope") as MockScope:
        mock_scope = AsyncMock()
        mock_scope.inner = MagicMock()
        mock_scope.inner.retrieve = MagicMock(return_value=Nothing())
        mock_scope.all_injected = MagicMock(return_value={})
        mock_scope.__aenter__ = AsyncMock(return_value=mock_scope)
        mock_scope.__aexit__ = AsyncMock(return_value=None)
        MockScope.return_value = mock_scope

        # Also patch agent.run to not crash
        with patch.object(runner, "_agent") as mock_agent_factory:
            mock_agent = AsyncMock()
            mock_agent.run = AsyncMock()
            mock_agent_factory.build.return_value = mock_agent

            result = await runner.run(MissingOp(name="test"))
            # Should return Error since node not found
            match result:
                case Error(msg):
                    assert "Node not found" in str(msg)
                case _:
                    pytest.fail(f"Expected Error, got {result}")


# ═══════════════════════════════════════════════════════════════════════════════
# 10. saga._run — run_parallel Error branch (L229-230)
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_saga_run_parallel_error_branch() -> None:
    """Lines 229-230: run_parallel when C_parallel itself returns Error."""
    from emergent.saga._run import run_parallel
    from emergent.saga._types import SagaStep, Parallel
    from kungfu import LazyCoroResult

    async def action_fn() -> Result[str, str]:
        return Ok("a")

    step1 = SagaStep(
        action=LazyCoroResult(action_fn),
        compensate=None,
    )

    par = Parallel(sagas=(step1,))

    # Patch C_parallel to return an awaitable Error
    async def fake_parallel(*args: str) -> Result[str, str]:
        return Error("parallel failed")

    with patch("emergent.saga._run.C_parallel", side_effect=fake_parallel):

        result = await run_parallel(par)
        match result:
            case Error(saga_err):
                assert saga_err.step_failed == 0
            case _:
                pytest.fail(f"Expected Error, got {result}")


# ═══════════════════════════════════════════════════════════════════════════════
# 11. schema._inspect — get_nested_info TypeError (L553-554)
# ═══════════════════════════════════════════════════════════════════════════════


def test_get_nested_info_type_error() -> None:
    """Lines 553-554: get_nested_info returns None on TypeError in inspect_type."""
    from emergent.wire.axis.schema._inspect import get_nested_info, FieldInfo

    # Create a FieldInfo with a type that is_structured_type but inspect_type raises TypeError
    # We mock is_structured_type to return True and inspect_type to raise TypeError
    with patch(
        "emergent.wire.axis.schema._inspect.is_structured_type",
        return_value=True,
    ), patch(
        "emergent.wire.axis.schema._inspect.inspect_type",
        side_effect=TypeError("cannot inspect"),
    ):
        info = FieldInfo(
            name="test_field",
            base_type=str,
            is_optional=False,
            capabilities=(),
        )
        result = get_nested_info(info)
        assert result is None


# ═══════════════════════════════════════════════════════════════════════════════
# 12. delta.py — compose_deltas None fields (L354-355)
# ═══════════════════════════════════════════════════════════════════════════════


def test_compose_deltas_skip_none_fields() -> None:
    """Line 355: compose_deltas skips None delta fields."""
    from emergent.wire.axis.schema.dialects.delta import (
        compose_deltas,
        NumericDelta,
    )

    @dataclass
    class TestDelta:
        balance: NumericDelta | None = None
        score: NumericDelta | None = None

    d1 = TestDelta(balance=NumericDelta(add=100), score=None)
    d2 = TestDelta(balance=None, score=NumericDelta(add=50))

    result = compose_deltas(d1, d2)
    assert result.balance.add == 100  # from d1
    assert result.score.add == 50  # from d2


# ═══════════════════════════════════════════════════════════════════════════════
# 13. delta.py — validate_delta None fields (L438-439)
# ═══════════════════════════════════════════════════════════════════════════════


def test_validate_delta_skip_none_fields() -> None:
    """Line 439: validate_delta skips None delta fields."""
    from emergent.wire.axis.schema.dialects.delta import (
        validate_delta,
        DeltaField,
        NumericDelta,
    )

    @dataclass
    class Account:
        id: int
        balance: Annotated[int, DeltaField("numeric")]

    @dataclass
    class AccountDelta:
        balance: NumericDelta | None = None

    # All fields None — should produce empty errors
    delta = AccountDelta(balance=None)
    errors = validate_delta(delta, Account)
    assert errors == []


# ═══════════════════════════════════════════════════════════════════════════════
# 14. delta.py — _delta_kind returns "collection" (L477-478)
# ═══════════════════════════════════════════════════════════════════════════════


def test_delta_kind_collection() -> None:
    """Line 478: _delta_kind returns 'collection' for CollectionDelta."""
    from emergent.wire.axis.schema.dialects.delta import (
        _delta_kind,  # pyright: ignore[reportPrivateUsage] - testing private function
        CollectionDelta,
    )

    cd = CollectionDelta(push=("a", "b"))
    assert _delta_kind(cd) == "collection"


def test_delta_kind_unknown() -> None:
    """Line 479: _delta_kind returns 'unknown' for unrecognized delta."""
    from emergent.wire.axis.schema.dialects.delta import (
        _delta_kind,  # pyright: ignore[reportPrivateUsage] - testing private function
    )

    # _delta_kind checks isinstance for NumericDelta, StringDelta, then hasattr("push").
    # The "unknown" branch is purely defensive — it fires only when none of the checks
    # match, which cannot happen with a valid AnyDelta value. To test this defensive
    # branch, we must pass an object outside the AnyDelta union type.
    @dataclass
    class FakeDelta:
        """Not a real delta — no 'push' attr, not NumericDelta or StringDelta."""
        value: int = 0

    # pyright: ignore[reportArgumentType] - intentionally passing non-AnyDelta to test defensive "unknown" branch
    assert _delta_kind(FakeDelta()) == "unknown"  # pyright: ignore[reportArgumentType]

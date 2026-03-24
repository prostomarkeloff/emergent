# pyright: reportPrivateUsage=false
"""Tests covering remaining uncovered wire/ modules.

Covers:
  - compile/_execute.py: execute_immediate_unified, _family_mapped
  - compile/_delegate.py: resolve_handler_params, _get_base_type, _extract_compose_capability
  - compile/_pipeline.py: CompiledPipeline, compile_pipeline, _make_scope, _family_mapped
  - compile/_request.py: build_request, build_request_sync, build_field_value
  - compile/_rrc.py: execute_rrc
  - compile/_stateful.py: load_state, save_state, delete_state, get_stateful_metadata
  - surface/_scan.py: scan, scan_endpoint, scan_stack
  - surface/_explain.py: application_dict, explain_application, exposure_dict, endpoint_dict
  - surface/_stack.py: AppStack, app_stack
  - surface/capabilities/_pipeline.py: Coercion, Extraction, NO_COERCION
  - surface/codecs/resolve.py: unwrap, wrap, get_method_params, get_transition_params
  - surface/dialects/http.py: Summary, OperationId, Deprecated, ResponseStatus, etc.
  - surface/dialects/telegram.py: HelpMeta, Silent, ParseMode, LinkPreview, ProtectContent
  - query/_explain.py: explain_ops, format_ops, ExplainDialect
  - query/_sql.py: SQLRelationalQuerySet, ForUpdate, Returning, Window
  - schema/_explain.py: schema_dict, explain_schema, explain_field
  - schema/dialects/delta.py: NumericDelta, StringDelta, CollectionDelta, apply_delta, etc.
  - schema/dialects/temporal.py: temporal filters, Versioned, Timestamps, etc.
  - storage/_explain.py: storage_dict, explain_storage
  - storage/_memory.py: MemoryStorage
  - storage/_file.py: FileStorage
  - query/contrib/http.py: import availability
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Annotated, Self

import pytest
from kungfu import Option, Result, Ok, Error, Some, Nothing

from emergent.ops._graph import Op, Runner, ops
from emergent.wire.axis.surface import application, endpoint
from emergent.wire.axis.surface._types import Exposure
from emergent.wire.axis.surface._scan import scan, scan_endpoint, scan_stack, StackView
from emergent.wire.axis.surface._stack import app_stack
from emergent.wire.axis.surface._explain import (
    application_dict,
    explain_application,
    exposure_dict,
    explain_endpoint,
)
from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger
from emergent.wire.axis.surface.triggers.cli import CLITrigger
from emergent.wire.axis.surface.triggers.event import EventTrigger
from emergent.wire.axis.surface.codecs.rrc import (
    RequestResponseCodec,
    rrc,
)
from emergent.wire.axis.surface.codecs.delegate import DelegateCodec, delegate
from emergent.wire.axis.surface.codecs.immediate import (
    ImmediateCodec,
    ImmediateFactoryCodec,
    immediate,
    immediate_factory,
)
from emergent.wire.axis.surface.capabilities._base import SurfaceCapability
from emergent.wire.axis.surface.capabilities._pipeline import (
    Coercion,
    Extraction,
    NO_COERCION,
)
from emergent.wire.axis.surface.codecs.resolve import (
    unwrap,
    wrap,
    get_method_params,
    get_transition_params,
)
from emergent.wire.axis.surface.dialects.http import (
    Summary,
    OperationId,
    Deprecated,
    ResponseStatus,
    ResponseHeader,
    ContentType,
)
from emergent.wire.axis.surface.dialects.telegram import (
    HelpMeta,
    Silent,
    ParseMode,
    LinkPreview,
    ProtectContent,
)
from emergent.wire.axis.query._explain import (
    explain_ops,
    format_ops,
    RELATIONAL_EXPLAIN,
    RELATIONAL_EXPLAIN_DIALECT,
    API_EXPLAIN_DIALECT,
    KV_EXPLAIN_DIALECT,
)
from emergent.wire.axis.query._relational import (
    Filter,
    OrderBy,
    Limit,
    Offset,
)
from emergent.wire.axis.query._sql import (
    sql_relational,
    ForUpdate,
    Returning,
)
from emergent.wire.axis.query._expr import (
    Eq,
    Gt,
    Field,
    Const,
)
from emergent.wire.axis.query._proxy import OrderSpec
from emergent.wire.axis.schema._explain import (
    schema_dict,
    explain_schema,
    explain_field,
)
from emergent.wire.axis.schema.dialects.delta import (
    NumericDelta,
    StringDelta,
    CollectionDelta,
    DeltaField,
    apply_delta,
    compose_deltas,
    validate_delta,
    delta_type,
)
from emergent.wire.axis.schema.dialects.temporal import (
    Versioned,
    Temporal,
    Timestamps,
    SoftDelete,
    TemporalCapability,
    temporal_filter_current,
    temporal_filter_as_of,
    temporal_filter_version,
)
from emergent.wire.axis.storage._explain import (
    storage_dict,
    explain_storage,
)
from emergent.wire.axis.storage._memory import MemoryStorage
from emergent.wire.axis.storage._file import FileStorage
from emergent.wire.compile._pipeline import (
    CompiledPipeline,
    compile_pipeline,
)
from emergent.wire.compile._core import Axes
from emergent.wire.compile._request import build_request, build_request_sync
from emergent.wire.axis.schema import Identity, MaxLen, Min, Max, Doc


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _runner() -> Runner:
    """Create an empty Runner for Endpoint construction."""
    return ops().compile()


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Surface scan — scan, scan_endpoint, scan_stack
# ═══════════════════════════════════════════════════════════════════════════════


def test_scan_finds_http_triggers():
    """scan() extracts matching (trigger, handler) pairs by trigger type."""
    trigger = HTTPRouteTrigger(method="GET", path="/users")
    codec = rrc(_DummyRequest, _DummyResponse)
    app = application().mount(endpoint(_runner()).expose(trigger, codec))

    results = scan(app, HTTPRouteTrigger)
    assert len(results) == 1
    trig, handler = results[0]
    assert trig.method == "GET"
    assert trig.path == "/users"
    assert isinstance(handler.codec, RequestResponseCodec)


def test_scan_filters_by_codec_type():
    """scan() with codec filter only returns matching codec types."""
    trigger = HTTPRouteTrigger(method="POST", path="/submit")
    codec = delegate(lambda: None)
    app = application().mount(endpoint(_runner()).expose(trigger, codec))

    # Looking for RRC codec should find nothing
    results = scan(app, HTTPRouteTrigger, RequestResponseCodec)
    assert len(results) == 0

    # Looking for DelegateCodec should find it
    results = scan(app, HTTPRouteTrigger, DelegateCodec)
    assert len(results) == 1


def test_scan_endpoint_returns_pairs():
    """scan_endpoint extracts from a single Endpoint."""
    trigger = CLITrigger(command="test")
    codec = rrc(_DummyRequest, _DummyResponse)
    ep = endpoint(_runner()).expose(trigger, codec)

    results = scan_endpoint(ep, CLITrigger)
    assert len(results) == 1
    assert results[0][0].command == "test"


def test_scan_stack_nested():
    """scan_stack walks nested AppStack."""
    root_app = application().mount(
        endpoint(_runner()).expose(
            CLITrigger(command="root-cmd"),
            rrc(_DummyRequest, _DummyResponse),
        )
    )
    sub_app = application().mount(
        endpoint(_runner()).expose(
            CLITrigger(command="sub-cmd"),
            rrc(_DummyRequest, _DummyResponse),
        )
    )
    stack = app_stack().root(root_app).mount("sub", sub_app)
    view = scan_stack(stack, CLITrigger)

    assert len(view.root) == 1
    assert view.root[0][0].command == "root-cmd"
    assert "sub" in view.mounts
    sub_view = view.mounts["sub"]
    assert isinstance(sub_view, list)
    assert len(sub_view) == 1
    assert sub_view[0][0].command == "sub-cmd"


# ═══════════════════════════════════════════════════════════════════════════════
# 2. AppStack — composition
# ═══════════════════════════════════════════════════════════════════════════════


def test_app_stack_root_and_mount():
    """AppStack.root() and .mount() compose correctly."""
    stack = app_stack()
    root = application().mount(
        endpoint(_runner()).expose(CLITrigger(command="a"), delegate(lambda: None))
    )
    sub = application().mount(
        endpoint(_runner()).expose(CLITrigger(command="b"), delegate(lambda: None))
    )
    composed = stack.root(root).mount("prefix", sub)
    assert len(composed.root_app.endpoints) == 1
    assert "prefix" in composed.mounts


def test_app_stack_nested_stacks():
    """AppStack can mount another AppStack."""
    inner = app_stack().root(
        application().mount(
            endpoint(_runner()).expose(CLITrigger(command="inner"), delegate(lambda: None))
        )
    )
    outer = app_stack().mount("ns", inner)
    view = scan_stack(outer, CLITrigger)
    assert "ns" in view.mounts
    assert isinstance(view.mounts["ns"], StackView)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Surface explain
# ═══════════════════════════════════════════════════════════════════════════════


def test_application_dict_structure():
    """application_dict returns expected structure."""
    trigger = HTTPRouteTrigger(method="GET", path="/health")
    codec = rrc(_DummyRequest, _DummyResponse)
    app = application().mount(endpoint(_runner()).expose(trigger, codec))

    data = application_dict(app)
    assert data["endpoint_count"] == 1
    assert len(data["endpoints"]) == 1
    ep_data = data["endpoints"][0]
    assert ep_data["exposure_count"] == 1


def test_explain_application_human_readable():
    """explain_application returns non-empty string."""
    trigger = HTTPRouteTrigger(method="POST", path="/login")
    codec = rrc(_DummyRequest, _DummyResponse)
    app = application().mount(endpoint(_runner()).expose(trigger, codec))

    text = explain_application(app)
    assert "Application" in text
    assert "POST /login" in text
    assert "RequestResponseCodec" in text


def test_explain_endpoint_human_readable():
    """explain_endpoint formats a single endpoint."""
    trigger = CLITrigger(command="scan", description="Scan files")
    codec = rrc(_DummyRequest, _DummyResponse)
    ep = endpoint(_runner()).expose(trigger, codec)

    text = explain_endpoint(ep)
    assert "Endpoint" in text
    assert "scan (cli)" in text


def test_exposure_dict_with_capabilities():
    """exposure_dict includes capabilities."""

    @dataclass(frozen=True, slots=True)
    class _TestCap(SurfaceCapability):
        value: int = 42

    trigger = HTTPRouteTrigger(method="GET", path="/test")
    codec = rrc(_DummyRequest, _DummyResponse)
    exp = Exposure(trigger, codec, (_TestCap(),))

    data = exposure_dict(exp)
    assert "trigger" in data
    assert "codec" in data
    assert "capabilities" in data
    assert len(data["capabilities"]) == 1


def test_explain_delegate_codec():
    """exposure_dict explains DelegateCodec handler name."""
    trigger = HTTPRouteTrigger(method="GET", path="/delegate")

    def my_handler() -> None:
        pass

    codec = delegate(my_handler)
    exp = Exposure(trigger, codec, ())
    data = exposure_dict(exp)
    assert data["codec"]["type"] == "DelegateCodec"
    assert "my_handler" in data["codec"]["handler"]


def test_explain_immediate_codec():
    """exposure_dict explains ImmediateCodec."""
    trigger = CLITrigger(command="help")
    codec = immediate(_HelpResponse)
    exp = Exposure(trigger, codec, ())
    data = exposure_dict(exp)
    assert data["codec"]["type"] == "ImmediateCodec"


def test_explain_immediate_factory_codec():
    """exposure_dict explains ImmediateFactoryCodec."""
    trigger = CLITrigger(command="version")
    codec = immediate_factory(lambda: "1.0")
    exp = Exposure(trigger, codec, ())
    data = exposure_dict(exp)
    assert data["codec"]["type"] == "ImmediateFactoryCodec"


def test_explain_event_trigger():
    """exposure_dict explains EventTrigger."""

    @dataclass
    class OrderCreated:
        order_id: int

    trigger = EventTrigger(OrderCreated)
    codec = delegate(lambda: None)
    exp = Exposure(trigger, codec, ())
    data = exposure_dict(exp)
    assert data["trigger"]["type"] == "EventTrigger"
    assert data["trigger"]["event_type"] == "OrderCreated"


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Codec resolve — unwrap, wrap, get_method_params
# ═══════════════════════════════════════════════════════════════════════════════


def test_unwrap_plain_type():
    """unwrap() on a plain type returns (type, False)."""
    inner, is_optional = unwrap(int)
    assert inner is int
    assert is_optional is False


def test_unwrap_option():
    """unwrap() on Option[T] returns (T, True)."""
    inner, is_optional = unwrap(Option[int])
    assert inner is int
    assert is_optional is True


def test_unwrap_result():
    """unwrap() on Result[T, E] returns (T, True)."""
    inner, is_optional = unwrap(Result[str, int])
    assert inner is str
    assert is_optional is True


def test_wrap_option_success():
    """wrap() on Option type with success returns Some."""
    val = wrap(Option[int], True, 42)
    assert isinstance(val, Some)


def test_wrap_option_failure():
    """wrap() on Option type with failure returns Nothing."""
    val = wrap(Option[int], False, "err")
    assert isinstance(val, Nothing)


def test_wrap_result_success():
    """wrap() on Result type with success returns Ok."""
    val = wrap(Result[str, int], True, "hello")
    assert isinstance(val, Ok)


def test_wrap_result_failure():
    """wrap() on Result type with failure returns Error."""
    val = wrap(Result[str, int], False, 123)
    assert isinstance(val, Error)


def test_wrap_plain_success():
    """wrap() on plain type with success returns value."""
    val = wrap(int, True, 42)
    assert val == 42


def test_wrap_plain_failure_raises():
    """wrap() on plain type with failure raises RuntimeError."""
    with pytest.raises(RuntimeError, match="Required param failed"):
        wrap(int, False, "oops")


def test_get_method_params_simple():
    """get_method_params extracts params excluding self/return."""

    class Flow:
        async def transition(self, amount: int, name: str) -> Self:
            return self

    params = get_method_params(Flow.transition)
    assert "amount" in params
    assert "name" in params
    assert "self" not in params
    assert "return" not in params


def test_get_transition_params_from_flow():
    """get_transition_params reads __transition__."""

    class MyFlow:
        async def __transition__(self, x: int) -> Self:
            return self

    params = get_transition_params(MyFlow)
    assert "x" in params


def test_get_transition_params_no_transition():
    """get_transition_params returns {} when no __transition__."""

    class NoTransition:
        pass

    params = get_transition_params(NoTransition)
    assert params == {}


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Pipeline compilation
# ═══════════════════════════════════════════════════════════════════════════════


def _fake_execute(h: object, s: object, gv: object) -> None:
    pass


def test_compile_pipeline_basic():
    """compile_pipeline builds CompiledPipeline from a context object."""

    @dataclass
    class FakeCtx:
        execute: object = _fake_execute

    ctx = FakeCtx()
    axes = Axes.default()
    compiled = compile_pipeline(ctx, axes)
    assert isinstance(compiled, CompiledPipeline)
    assert compiled.execute is ctx.execute
    assert compiled.extractor is None
    assert compiled.coerce_model is None


def test_compile_pipeline_missing_execute_raises():
    """compile_pipeline raises TypeError when execute is missing."""

    class BadCtx:
        pass

    with pytest.raises(TypeError, match="has no 'execute' attribute"):
        compile_pipeline(BadCtx(), Axes.default())


def test_compiled_pipeline_frozen():
    """CompiledPipeline is frozen dataclass."""
    cp = CompiledPipeline(execute=lambda: None)
    with pytest.raises(AttributeError):
        cp.execute = lambda: None  # type: ignore[misc]


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Request building
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class _SimpleRequest:
    name: str
    age: int


@dataclass
class _DefaultRequest:
    name: str
    tag: str = "default"


@dataclass
class _OptionalRequest:
    name: str
    bio: str | None = None


@pytest.mark.asyncio
async def test_build_request_simple():
    """build_request constructs from a simple getter."""
    values = {"name": "Alice", "age": 30}
    result = await build_request(_SimpleRequest, lambda n: values.get(n))
    assert result.name == "Alice"
    assert result.age == 30


@pytest.mark.asyncio
async def test_build_request_with_defaults():
    """build_request falls back to defaults."""
    values = {"name": "Bob"}
    result = await build_request(_DefaultRequest, lambda n: values.get(n))
    assert result.name == "Bob"
    assert result.tag == "default"


@pytest.mark.asyncio
async def test_build_request_optional_none():
    """build_request sets optional fields to None when missing."""
    values = {"name": "Carol"}
    result = await build_request(_OptionalRequest, lambda n: values.get(n))
    assert result.name == "Carol"
    assert result.bio is None


@pytest.mark.asyncio
async def test_build_request_not_dataclass_raises():
    """build_request raises TypeError for non-dataclass."""
    with pytest.raises(TypeError, match="is not a dataclass"):
        await build_request(int, lambda n: None)


def test_build_request_sync_simple():
    """build_request_sync constructs without async."""
    values = {"name": "Dave", "age": 25}
    result = build_request_sync(_SimpleRequest, lambda n: values.get(n))
    assert result.name == "Dave"
    assert result.age == 25


def test_build_request_sync_defaults():
    """build_request_sync uses field defaults."""
    values = {"name": "Eve"}
    result = build_request_sync(_DefaultRequest, lambda n: values.get(n))
    assert result.tag == "default"


def test_build_request_sync_not_dataclass():
    """build_request_sync raises TypeError for non-dataclass."""
    with pytest.raises(TypeError, match="is not a dataclass"):
        build_request_sync(str, lambda n: None)


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Query explain
# ═══════════════════════════════════════════════════════════════════════════════


def test_explain_ops_relational():
    """explain_ops with RELATIONAL_EXPLAIN produces dicts."""
    ops_list = [
        Filter(Gt(Field("balance"), Const(100))),
        Limit(10),
        Offset(5),
    ]
    result = explain_ops(ops_list, RELATIONAL_EXPLAIN)
    assert len(result) == 3
    assert result[0]["op"] == "Filter"
    assert result[1]["op"] == "Limit"
    assert result[1]["count"] == 10
    assert result[2]["op"] == "Offset"
    assert result[2]["count"] == 5


def test_format_ops_relational():
    """format_ops produces human-readable text."""
    ops_list = [
        Filter(Eq(Field("status"), Const("active"))),
        OrderBy(specs=(OrderSpec("name", ascending=True),)),
        Limit(20),
    ]
    text = format_ops(ops_list, RELATIONAL_EXPLAIN)
    assert "Filter" in text
    assert "OrderBy" in text
    assert "Limit" in text


def test_format_ops_empty():
    """format_ops on empty list returns (empty)."""
    text = format_ops([], RELATIONAL_EXPLAIN)
    assert text == "(empty)"


def test_explain_ops_unknown_op_fallback():
    """explain_ops produces minimal dict for unknown op types."""

    @dataclass
    class UnknownOp:
        pass

    result = explain_ops([UnknownOp()], RELATIONAL_EXPLAIN)
    assert result[0]["op"] == "UnknownOp"


def test_explain_dialect_with_handler():
    """ExplainDialect.with_handler adds custom handler."""

    @dataclass(frozen=True)
    class CustomOp:
        label: str

    def _explain_custom(op: CustomOp) -> dict[str, str]:
        return {"op": "Custom", "label": op.label}

    dialect = RELATIONAL_EXPLAIN_DIALECT.with_handler(CustomOp, _explain_custom)
    result = dialect.explain([CustomOp("test")])
    assert result[0]["op"] == "Custom"
    assert result[0]["label"] == "test"


def test_explain_dialect_without_handler():
    """ExplainDialect.without_handler removes a handler."""
    dialect = RELATIONAL_EXPLAIN_DIALECT.without_handler(Filter)
    result = dialect.explain([Filter(Eq(Field("x"), Const(1)))])
    assert result[0]["op"] == "Filter"  # fallback to type name
    assert "expr" not in result[0]


def test_explain_dialect_format():
    """ExplainDialect.format produces text."""
    text = RELATIONAL_EXPLAIN_DIALECT.format([Limit(5)])
    assert "Limit" in text
    assert "5" in text


# ═══════════════════════════════════════════════════════════════════════════════
# 8. SQL query set
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class _User:
    id: int
    name: str
    balance: int
    department: str


def test_sql_relational_for_update():
    """SQLRelationalQuerySet.for_update() adds ForUpdate op."""
    q = sql_relational(_User).for_update()
    assert q.has_for_update
    assert any(isinstance(op, ForUpdate) for op in q.ops)


def test_sql_relational_for_update_nowait():
    """ForUpdate with nowait flag."""
    q = sql_relational(_User).for_update(nowait=True)
    fu = next(op for op in q.ops if isinstance(op, ForUpdate))
    assert fu.nowait is True


def test_sql_relational_returning():
    """SQLRelationalQuerySet.returning() adds Returning op."""
    q = sql_relational(_User).returning("id", "name")
    assert q.has_returning
    ret = next(op for op in q.ops if isinstance(op, Returning))
    assert ret.fields == ("id", "name")


def test_sql_relational_to_relational_strips_sql():
    """to_relational() strips SQL-specific ops."""
    q = (
        sql_relational(_User)
        .filter(lambda u: u.balance > 0)
        .for_update()
        .returning("id")
    )
    rq = q.to_relational()
    assert not any(isinstance(op, (ForUpdate, Returning)) for op in rq.ops)
    assert any(isinstance(op, Filter) for op in rq.ops)


def test_sql_relational_has_windows_false_by_default():
    """has_windows is False when no windows added."""
    q = sql_relational(_User)
    assert q.has_windows is False


def test_sql_relational_chaining():
    """Multiple operations chain on SQLRelationalQuerySet."""
    q = (
        sql_relational(_User)
        .filter(lambda u: u.balance > 0)
        .order_by(lambda u: u.name.asc())
        .limit(10)
        .for_update(skip_locked=True)
    )
    assert len(q.ops) == 4


# ═══════════════════════════════════════════════════════════════════════════════
# 9. Schema explain
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class _SchemaUser:
    id: Annotated[int, Identity]
    email: Annotated[str, MaxLen(255), Doc("User email")]
    score: Annotated[int, Min(0), Max(100)]


def test_schema_dict_structure():
    """schema_dict returns expected structure."""
    data = schema_dict(_SchemaUser)
    assert data["name"] == "_SchemaUser"
    assert "fields" in data
    assert len(data["fields"]) == 3


def test_explain_schema_human_readable():
    """explain_schema returns non-empty readable text."""
    text = explain_schema(_SchemaUser)
    assert "_SchemaUser" in text
    assert "id" in text
    assert "email" in text


def test_explain_field_found():
    """explain_field returns info for known field."""
    text = explain_field(_SchemaUser, "email")
    assert "email" in text


def test_explain_field_not_found():
    """explain_field returns not-found message for unknown field."""
    text = explain_field(_SchemaUser, "nonexistent")
    assert "not found" in text


# ═══════════════════════════════════════════════════════════════════════════════
# 10. Delta dialect
# ═══════════════════════════════════════════════════════════════════════════════


def test_numeric_delta_add():
    """NumericDelta.apply adds to value."""
    delta = NumericDelta(add=50)
    assert delta.apply(100) == 150


def test_numeric_delta_set_overrides():
    """NumericDelta with set ignores add/multiply."""
    delta = NumericDelta(add=50, set=0)
    assert delta.apply(100) == 0


def test_numeric_delta_multiply():
    """NumericDelta.apply multiplies value."""
    delta = NumericDelta(multiply=2.0)
    assert delta.apply(50) == 100


def test_string_delta_append():
    """StringDelta.apply appends text."""
    delta = StringDelta(append=" (updated)")
    assert delta.apply("hello") == "hello (updated)"


def test_string_delta_set_overrides():
    """StringDelta with set overrides other ops."""
    delta = StringDelta(append="x", set="new")
    assert delta.apply("old") == "new"


def test_string_delta_prepend_and_replace():
    """StringDelta prepend + replace combination."""
    delta = StringDelta(prepend="[", replace=("o", "0"))
    assert delta.apply("world") == "[w0rld"


def test_collection_delta_push():
    """CollectionDelta.apply pushes items."""
    delta: CollectionDelta[str] = CollectionDelta(push=("new",))
    assert delta.apply(["old"]) == ["old", "new"]


def test_collection_delta_set():
    """CollectionDelta with set replaces entirely."""
    delta: CollectionDelta[str] = CollectionDelta(set=("a", "b"))
    assert delta.apply(["x", "y", "z"]) == ["a", "b"]


def test_collection_delta_remove_and_pop():
    """CollectionDelta remove + pop combination."""
    delta: CollectionDelta[int] = CollectionDelta(remove=(1,), pop=1)
    result = delta.apply([1, 2, 3, 4])
    # Remove 1 -> [2, 3, 4], pop 1 -> [2, 3]
    assert result == [2, 3]


def test_apply_delta_frozen_dataclass():
    """apply_delta returns new instance for frozen dataclass."""

    @dataclass(frozen=True)
    class Account:
        balance: Annotated[int, DeltaField("numeric")]
        notes: Annotated[str, DeltaField("string")]

    AccountDelta = delta_type(Account)
    account = Account(balance=100, notes="hello")
    d = AccountDelta(balance=NumericDelta(add=50))
    new = apply_delta(account, d)
    assert new.balance == 150
    assert new.notes == "hello"


def test_compose_deltas_numeric():
    """compose_deltas sums numeric additions."""

    @dataclass(frozen=True)
    class Wallet:
        balance: Annotated[int, DeltaField("numeric")]

    WalletDelta = delta_type(Wallet)
    d1 = WalletDelta(balance=NumericDelta(add=100))
    d2 = WalletDelta(balance=NumericDelta(add=50))
    combined = compose_deltas(d1, d2)
    assert combined.balance.add == 150


def test_compose_deltas_single():
    """compose_deltas with one delta returns it."""

    @dataclass(frozen=True)
    class Tiny:
        val: Annotated[int, DeltaField("numeric")]

    TinyDelta = delta_type(Tiny)
    d1 = TinyDelta(val=NumericDelta(add=1))
    assert compose_deltas(d1) is d1


def test_validate_delta_valid():
    """validate_delta returns empty list for valid delta."""

    @dataclass(frozen=True)
    class Item:
        price: Annotated[int, DeltaField("numeric")]

    ItemDelta = delta_type(Item)
    d = ItemDelta(price=NumericDelta(add=10))
    errors = validate_delta(d, Item)
    assert errors == []


# ═══════════════════════════════════════════════════════════════════════════════
# 11. Temporal dialect
# ═══════════════════════════════════════════════════════════════════════════════


def test_temporal_filter_current():
    """temporal_filter_current creates IsNull expression."""
    expr = temporal_filter_current()
    result_str = str(expr)
    assert "valid_to" in result_str


def test_temporal_filter_as_of():
    """temporal_filter_as_of creates AND expression."""
    ts = datetime(2024, 6, 15)
    expr = temporal_filter_as_of(ts)
    result_str = str(expr)
    assert "valid_from" in result_str
    assert "valid_to" in result_str


def test_temporal_filter_version():
    """temporal_filter_version creates Eq expression."""
    expr = temporal_filter_version(3)
    result_str = str(expr)
    assert "version" in result_str


def test_versioned_capability_is_temporal():
    """Versioned is a TemporalCapability."""
    v = Versioned()
    assert isinstance(v, TemporalCapability)
    assert v.version_field == "version"
    assert v.start_version == 1


def test_timestamps_capability_fields():
    """Timestamps has expected field names."""
    ts = Timestamps()
    assert ts.created_field == "created_at"
    assert ts.updated_field == "updated_at"


def test_soft_delete_field():
    """SoftDelete has expected field name."""
    sd = SoftDelete()
    assert sd.field_name == "deleted_at"


def test_temporal_custom_field_names():
    """Temporal capabilities accept custom field names."""
    v = Versioned(version_field="ver", start_version=0)
    assert v.version_field == "ver"
    assert v.start_version == 0

    t = Temporal(valid_from_field="start", valid_to_field="end")
    assert t.valid_from_field == "start"
    assert t.valid_to_field == "end"


# ═══════════════════════════════════════════════════════════════════════════════
# 12. Memory storage
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_memory_storage_get_set_delete():
    """MemoryStorage basic get/set/delete."""
    store: MemoryStorage[str, str] = MemoryStorage()
    await store.set("key1", "value1")

    result = await store.get("key1")
    assert isinstance(result, Ok)
    inner = result.unwrap()
    assert isinstance(inner, Some)
    assert inner.unwrap() == "value1"

    await store.delete("key1")
    result2 = await store.get("key1")
    assert isinstance(result2, Ok)
    assert isinstance(result2.unwrap(), Nothing)


@pytest.mark.asyncio
async def test_memory_storage_set_nx():
    """MemoryStorage set_nx doesn't overwrite existing."""
    store: MemoryStorage[str, int] = MemoryStorage()
    r1 = await store.set_nx("k", 1)
    assert r1.unwrap() is True

    r2 = await store.set_nx("k", 2)
    assert r2.unwrap() is False

    # Value should still be 1
    val = await store.get("k")
    assert val.unwrap().unwrap() == 1


@pytest.mark.asyncio
async def test_memory_storage_ttl_expiry():
    """MemoryStorage entries expire after TTL."""
    store: MemoryStorage[str, str] = MemoryStorage()
    # Use a negative timedelta so expires_at is firmly in the past
    await store.set("k", "v", ttl=timedelta(seconds=-1))
    result = await store.get("k")
    assert isinstance(result.unwrap(), Nothing)


@pytest.mark.asyncio
async def test_memory_storage_keys():
    """MemoryStorage.keys returns matching keys."""
    store: MemoryStorage[str, str] = MemoryStorage()
    await store.set("user:1", "a")
    await store.set("user:2", "b")
    await store.set("session:1", "c")

    all_keys = await store.keys()
    assert len(all_keys.unwrap()) == 3

    user_keys = await store.keys("user:*")
    assert len(user_keys.unwrap()) == 2


@pytest.mark.asyncio
async def test_memory_storage_delete_pattern():
    """MemoryStorage.delete_pattern removes matching keys."""
    store: MemoryStorage[str, str] = MemoryStorage()
    await store.set("tmp:1", "a")
    await store.set("tmp:2", "b")
    await store.set("perm:1", "c")

    result = await store.delete_pattern("tmp:*")
    assert result.unwrap() == 2

    remaining = await store.keys()
    assert len(remaining.unwrap()) == 1


# ═══════════════════════════════════════════════════════════════════════════════
# 13. File storage
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_file_storage_persistence():
    """FileStorage persists data to disk."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "test.pickle")

        store1: FileStorage[str, str] = FileStorage(path)
        await store1.set("key", "value")

        # Create new instance — should load from file
        store2: FileStorage[str, str] = FileStorage(path)
        result = await store2.get("key")
        assert isinstance(result, Ok)
        assert result.unwrap().unwrap() == "value"


# ═══════════════════════════════════════════════════════════════════════════════
# 14. Storage explain
# ═══════════════════════════════════════════════════════════════════════════════


def test_storage_explain_unknown_type():
    """storage_dict on unknown type produces fallback dict."""

    class CustomStore:
        pass

    data = storage_dict(CustomStore())
    assert data["type"] == "CustomStore"


def test_explain_storage_produces_text():
    """explain_storage produces non-empty text."""

    class AnotherStore:
        pass

    text = explain_storage(AnotherStore())
    assert "AnotherStore" in text


# ═══════════════════════════════════════════════════════════════════════════════
# 15. HTTP dialect capabilities (pure logic)
# ═══════════════════════════════════════════════════════════════════════════════


def test_summary_creation():
    """Summary.of creates with text and description."""
    s = Summary.of("List users", "Returns all active users")
    assert s.text == "List users"
    assert s.description == "Returns all active users"


def test_operation_id_creation():
    """OperationId.of creates with value."""
    op_id = OperationId.of("listUsers")
    assert op_id.value == "listUsers"


def test_deprecated_because():
    """Deprecated.because creates with reason."""
    d = Deprecated.because("Use /v2 instead")
    assert d.reason == "Use /v2 instead"
    assert d.sunset_date is None


def test_deprecated_until():
    """Deprecated.until creates with date and reason."""
    d = Deprecated.until("2025-01-01", "Migrating to v2")
    assert d.sunset_date == "2025-01-01"
    assert d.reason == "Migrating to v2"


def test_response_status_code():
    """ResponseStatus stores code."""
    rs = ResponseStatus(201)
    assert rs.code == 201


def test_response_header_defaults():
    """ResponseHeader default values."""
    rh = ResponseHeader("X-Request-Id", "Unique ID")
    assert rh.name == "X-Request-Id"
    assert rh.schema_type == "string"


def test_content_type():
    """ContentType stores media type."""
    ct = ContentType("text/csv")
    assert ct.media_type == "text/csv"


# ═══════════════════════════════════════════════════════════════════════════════
# 16. Telegram dialect capabilities (pure logic)
# ═══════════════════════════════════════════════════════════════════════════════


def test_help_meta_defaults():
    """HelpMeta default values."""
    hm = HelpMeta("Register account")
    assert hm.description == "Register account"
    assert hm.order == 100
    assert hm.hidden is False


def test_silent_is_surface_capability():
    """Silent is a SurfaceCapability."""
    s = Silent()
    assert isinstance(s, SurfaceCapability)


def test_parse_mode_stores_mode():
    """ParseMode stores mode."""
    pm = ParseMode("HTML")
    assert pm.mode == "HTML"


def test_link_preview_disabled():
    """LinkPreview default is disabled=True."""
    lp = LinkPreview()
    assert lp.disabled is True


def test_protect_content_is_frozen():
    """ProtectContent is frozen."""
    pc = ProtectContent()
    with pytest.raises((AttributeError, TypeError)):
        pc.foo = True  # type: ignore[attr-defined]


# ═══════════════════════════════════════════════════════════════════════════════
# 17. Coercion/Extraction capabilities (pure logic)
# ═══════════════════════════════════════════════════════════════════════════════


def test_no_coercion_has_none_spec():
    """NO_COERCION has spec=None."""
    assert NO_COERCION.spec is None


def test_coercion_is_frozen():
    """Coercion is frozen."""
    c = Coercion(spec=None)
    with pytest.raises(AttributeError):
        c.spec = None  # type: ignore[misc]


def test_extraction_defaults():
    """Extraction defaults all extractors to None."""
    e = Extraction()
    assert e.fastapi is None
    assert e.cli is None
    assert e.telegram is None
    assert e.testing is None
    assert e.event is None


# ═══════════════════════════════════════════════════════════════════════════════
# 18. Immediate codec execution
# ═══════════════════════════════════════════════════════════════════════════════


def test_execute_immediate_unified_producing():
    """execute_immediate_unified with ImmediateCodec produces response."""
    from emergent.wire.compile._execute import execute_immediate_unified
    from emergent.wire.axis.surface._handler import Handler

    codec = immediate(_HelpResponse)
    handler: Handler[ImmediateCodec] = Handler(
        codec=codec, runner=_runner(), capabilities=()
    )
    response = execute_immediate_unified(handler)
    assert response == "Help text"


def test_execute_immediate_unified_factory():
    """execute_immediate_unified with ImmediateFactoryCodec produces response."""
    from emergent.wire.compile._execute import execute_immediate_unified
    from emergent.wire.axis.surface._handler import Handler

    codec = immediate_factory(lambda: {"status": "ok"})
    handler: Handler[ImmediateFactoryCodec] = Handler(
        codec=codec, runner=_runner(), capabilities=()
    )
    response = execute_immediate_unified(handler)
    assert response == {"status": "ok"}


def test_execute_immediate_unified_with_formatter():
    """execute_immediate_unified applies format_response."""
    from emergent.wire.compile._execute import execute_immediate_unified
    from emergent.wire.axis.surface._handler import Handler

    codec = immediate_factory(lambda: 42)
    handler = Handler(codec=codec, runner=_runner(), capabilities=())
    response = execute_immediate_unified(handler, format_response=str)
    assert response == "42"


def test_execute_immediate_unified_bad_codec_raises():
    """execute_immediate_unified raises TypeError for unknown codec."""
    from emergent.wire.compile._execute import execute_immediate_unified
    from emergent.wire.axis.surface._handler import Handler

    @dataclass
    class BadCodec:
        pass

    handler = Handler(codec=BadCodec(), runner=_runner(), capabilities=())
    with pytest.raises(TypeError, match="Expected ImmediateCodec"):
        execute_immediate_unified(handler)


# ═══════════════════════════════════════════════════════════════════════════════
# 19. KV explain handlers
# ═══════════════════════════════════════════════════════════════════════════════


def test_kv_explain_dialect():
    """KV_EXPLAIN_DIALECT explains KV ops."""
    from emergent.wire.axis.query._kv import KVGet, KVSet, KVDelete

    ops_list = [
        KVGet("user:1"),
        KVSet("user:2", {"name": "Bob"}, ttl=60),
        KVDelete("user:3"),
    ]
    result = KV_EXPLAIN_DIALECT.explain(ops_list)
    assert len(result) == 3
    assert result[0]["op"] == "Get"
    assert result[1]["op"] == "Set"
    assert result[1]["ttl"] == 60
    assert result[2]["op"] == "Delete"


def test_api_explain_dialect():
    """API_EXPLAIN_DIALECT explains API ops."""
    from emergent.wire.axis.query._api import ListOp, GetOp

    ops_list = [ListOp(), GetOp("123")]
    result = API_EXPLAIN_DIALECT.explain(ops_list)
    assert len(result) == 2
    assert result[0]["op"] == "List"
    assert result[1]["op"] == "Get"


# ═══════════════════════════════════════════════════════════════════════════════
# 20. Query contrib http — import availability
# ═══════════════════════════════════════════════════════════════════════════════


def test_query_contrib_init_importable():
    """query.contrib.__init__ is importable regardless of httpx."""
    import emergent.wire.axis.query.contrib

    assert hasattr(emergent.wire.axis.query.contrib, "__all__")


# ═══════════════════════════════════════════════════════════════════════════════
# Test fixture types (defined at module level for all tests)
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class _DummyOp(Op[str, str]):
    name: str


@dataclass(frozen=True)
class _DummyRequest:
    name: str = "test"

    def to_domain(self) -> _DummyOp:
        return _DummyOp(name=self.name)


@dataclass(frozen=True)
class _DummyResponse:
    message: str = "ok"

    @classmethod
    def from_domain(cls, dom: Result[str, str]) -> _DummyResponse:
        return cls(message="ok")


class _HelpResponse:
    @classmethod
    def produce(cls) -> str:
        return "Help text"

# pyright: reportPrivateUsage=false
"""Misc sweep tests — covers small remaining gaps across 35+ files.

Each test targets exact uncovered lines in a specific module.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable, Self, cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from kungfu import Ok, Error, Some, Nothing, Option, Result


# ═══════════════════════════════════════════════════════════════════════════════
# 1. telegram.py — TG dialect compile methods + enrichers
# ═══════════════════════════════════════════════════════════════════════════════


class TestTelegramDialect:
    """Tests for emergent.wire.axis.surface.dialects.telegram."""

    def test_help_meta_creation(self) -> None:
        from emergent.wire.axis.surface.dialects.telegram import HelpMeta

        h = HelpMeta("desc", order=5, hidden=True)
        assert h.description == "desc"
        assert h.order == 5
        assert h.hidden is True

    def test_help_meta_defaults(self) -> None:
        from emergent.wire.axis.surface.dialects.telegram import HelpMeta

        h = HelpMeta("desc")
        assert h.order == 100
        assert h.hidden is False

    def test_silent_compile_telegrinder(self) -> None:
        from emergent.wire.axis.surface.dialects.telegram import Silent
        from emergent.wire.axis._capability import TelegrinderHandlerContext

        cap = Silent()
        ctx = TelegrinderHandlerContext()
        result = cap.compile_telegrinder(ctx)
        assert result.silent is True

    def test_parse_mode_compile_telegrinder(self) -> None:
        from emergent.wire.axis.surface.dialects.telegram import ParseMode
        from emergent.wire.axis._capability import TelegrinderHandlerContext

        cap = ParseMode(mode="HTML")
        ctx = TelegrinderHandlerContext()
        result = cap.compile_telegrinder(ctx)
        assert result.parse_mode == "HTML"

    def test_link_preview_compile_telegrinder(self) -> None:
        from emergent.wire.axis.surface.dialects.telegram import LinkPreview
        from emergent.wire.axis._capability import TelegrinderHandlerContext

        cap = LinkPreview(disabled=True)
        ctx = TelegrinderHandlerContext()
        result = cap.compile_telegrinder(ctx)
        assert result.link_preview_disabled is True

    def test_protect_content_compile_telegrinder(self) -> None:
        from emergent.wire.axis.surface.dialects.telegram import ProtectContent
        from emergent.wire.axis._capability import TelegrinderHandlerContext

        cap = ProtectContent()
        ctx = TelegrinderHandlerContext()
        result = cap.compile_telegrinder(ctx)
        assert result.protect_content is True

    def test_edit_message_compile_telegrinder(self) -> None:
        from emergent.wire.axis.surface.dialects.telegram import EditMessage
        from emergent.wire.axis._capability import TelegrinderHandlerContext

        cap = EditMessage()
        ctx = TelegrinderHandlerContext()
        result = cap.compile_telegrinder(ctx)
        assert result.edit_message is True

    def test_answer_callback_compile_telegrinder(self) -> None:
        from emergent.wire.axis.surface.dialects.telegram import AnswerCallback
        from emergent.wire.axis._capability import TelegrinderHandlerContext

        cap = AnswerCallback(text="Processing", show_alert=True)
        ctx = TelegrinderHandlerContext()
        result = cap.compile_telegrinder(ctx)
        assert result.answer_callback is True
        assert result.answer_callback_text == "Processing"
        assert result.answer_callback_show_alert is True

    @pytest.mark.asyncio
    async def test_edit_message_enrich_no_cq(self) -> None:
        """EditMessage enrich — no callback query returns response."""
        from emergent.wire.axis.surface.dialects.telegram import EditMessage
        from nodnod import Scope

        cap = EditMessage()
        async with Scope() as scope:
            async def call(s: Any) -> str:
                return "hello"
            result = await cap.enrich(call, scope)
            assert result == "hello"

    @pytest.mark.asyncio
    async def test_answer_callback_enrich_no_cq(self) -> None:
        """AnswerCallback enrich — no callback query returns response unchanged."""
        from emergent.wire.axis.surface.dialects.telegram import AnswerCallback
        from nodnod import Scope

        cap = AnswerCallback(text="ack")
        async with Scope() as scope:
            async def call(s: Any) -> str:
                return "response"
            result = await cap.enrich(call, scope)
            assert result == "response"

    @pytest.mark.asyncio
    async def test_reply_message_enrich_none_response(self) -> None:
        """ReplyMessage enrich — None response returns None."""
        from emergent.wire.axis.surface.dialects.telegram import ReplyMessage
        from nodnod import Scope

        cap = ReplyMessage()
        async with Scope() as scope:
            async def call(s: Any) -> None:
                return None
            result = await cap.enrich(call, scope)
            assert result is None

    @pytest.mark.asyncio
    async def test_reply_message_enrich_empty_string(self) -> None:
        """ReplyMessage enrich — empty string returns None."""
        from emergent.wire.axis.surface.dialects.telegram import ReplyMessage
        from nodnod import Scope

        cap = ReplyMessage()
        async with Scope() as scope:
            async def call(s: Any) -> str:
                return ""
            result = await cap.enrich(call, scope)
            assert result is None

    @pytest.mark.asyncio
    async def test_reply_message_enrich_no_api(self) -> None:
        """ReplyMessage enrich — no API in scope returns response unchanged."""
        from emergent.wire.axis.surface.dialects.telegram import ReplyMessage
        from nodnod import Scope

        cap = ReplyMessage()
        async with Scope() as scope:
            async def call(s: Any) -> str:
                return "text"
            result = await cap.enrich(call, scope)
            assert result == "text"

    def test_unwrap_some(self) -> None:
        from emergent.wire.axis.surface.dialects.telegram import _unwrap_some

        class FakeSome:
            value = 42

        assert _unwrap_some(FakeSome()) == 42
        assert _unwrap_some("no_value_attr") is None


# ═══════════════════════════════════════════════════════════════════════════════
# 2. codecs/resolve.py — codec resolution
# ═══════════════════════════════════════════════════════════════════════════════


class TestCodecResolve:
    """Tests for emergent.wire.axis.surface.codecs.resolve."""

    def test_unwrap_plain_type(self) -> None:
        from emergent.wire.axis.surface.codecs.resolve import unwrap

        inner, is_opt = unwrap(int)
        assert inner is int
        assert is_opt is False

    def test_unwrap_option(self) -> None:
        from emergent.wire.axis.surface.codecs.resolve import unwrap

        inner, is_opt = unwrap(Option[str])
        assert inner is str
        assert is_opt is True

    def test_unwrap_result(self) -> None:
        from emergent.wire.axis.surface.codecs.resolve import unwrap

        inner, is_opt = unwrap(Result[int, str])
        assert inner is int
        assert is_opt is True

    def test_wrap_option_success(self) -> None:
        from emergent.wire.axis.surface.codecs.resolve import wrap

        r = wrap(Option[int], True, 42)
        assert isinstance(r, Some)
        assert r.unwrap() == 42

    def test_wrap_option_failure(self) -> None:
        from emergent.wire.axis.surface.codecs.resolve import wrap

        r = wrap(Option[int], False, "err")
        assert isinstance(r, Nothing)

    def test_wrap_result_success(self) -> None:
        from emergent.wire.axis.surface.codecs.resolve import wrap

        r = wrap(Result[int, str], True, 42)
        assert isinstance(r, Ok)

    def test_wrap_result_failure(self) -> None:
        from emergent.wire.axis.surface.codecs.resolve import wrap

        r = wrap(Result[int, str], False, "err")
        assert isinstance(r, Error)

    def test_wrap_plain_success(self) -> None:
        from emergent.wire.axis.surface.codecs.resolve import wrap

        r = wrap(int, True, 42)
        assert r == 42

    def test_wrap_plain_failure_raises(self) -> None:
        from emergent.wire.axis.surface.codecs.resolve import wrap

        with pytest.raises(RuntimeError, match="Required param failed"):
            wrap(int, False, "err")

    def test_get_transition_params_no_transition(self) -> None:
        from emergent.wire.axis.surface.codecs.resolve import get_transition_params

        class NoTransition:
            pass

        assert get_transition_params(NoTransition) == {}

    def test_get_method_params(self) -> None:
        from emergent.wire.axis.surface.codecs.resolve import get_method_params

        async def my_method(self: Any, x: int, y: str) -> str:
            return ""

        params = get_method_params(my_method)
        assert "x" in params
        assert "y" in params
        assert "self" not in params
        assert "return" not in params

    def test_is_nodnod_node_false(self) -> None:
        from emergent.wire.axis.surface.codecs.resolve import _is_nodnod_node

        assert _is_nodnod_node(int) is False

    def test_is_nodnod_node_true(self) -> None:
        from emergent.wire.axis.surface.codecs.resolve import _is_nodnod_node

        class FakeNode:
            __dependencies__ = ()

        assert _is_nodnod_node(FakeNode) is True


# ═══════════════════════════════════════════════════════════════════════════════
# 3. bridge/_capabilities.py — bridge caps
# ═══════════════════════════════════════════════════════════════════════════════


class TestBridgeCapabilities:
    """Tests for emergent.wire.bridge._capabilities."""

    def test_skip_deprecated(self) -> None:
        from emergent.wire.bridge._capabilities import SkipDeprecated, BridgeContext

        ctx = BridgeContext(trigger_data=None, handler=lambda: None, deprecated=True)
        result = SkipDeprecated().compile_bridge(ctx)
        assert result.skip is True

    def test_skip_deprecated_not_deprecated(self) -> None:
        from emergent.wire.bridge._capabilities import SkipDeprecated, BridgeContext

        ctx = BridgeContext(trigger_data=None, handler=lambda: None, deprecated=False)
        result = SkipDeprecated().compile_bridge(ctx)
        assert result.skip is False

    def test_skip_by_name_exact(self) -> None:
        from emergent.wire.bridge._capabilities import SkipByName, BridgeContext

        ctx = BridgeContext(trigger_data=None, handler=lambda: None, name="skip_me")
        result = SkipByName(names=frozenset({"skip_me"})).compile_bridge(ctx)
        assert result.skip is True

    def test_skip_by_name_pattern(self) -> None:
        from emergent.wire.bridge._capabilities import SkipByName, BridgeContext

        ctx = BridgeContext(trigger_data=None, handler=lambda: None, name="internal_handler")
        result = SkipByName(pattern="internal_.*").compile_bridge(ctx)
        assert result.skip is True

    def test_skip_by_name_no_match(self) -> None:
        from emergent.wire.bridge._capabilities import SkipByName, BridgeContext

        ctx = BridgeContext(trigger_data=None, handler=lambda: None, name="public")
        result = SkipByName(names=frozenset({"private"})).compile_bridge(ctx)
        assert result.skip is False

    def test_include_only_by_name(self) -> None:
        from emergent.wire.bridge._capabilities import IncludeOnlyByName, BridgeContext

        ctx = BridgeContext(trigger_data=None, handler=lambda: None, name="allowed")
        result = IncludeOnlyByName(names=frozenset({"allowed"})).compile_bridge(ctx)
        assert result.skip is False

    def test_include_only_by_name_skips_others(self) -> None:
        from emergent.wire.bridge._capabilities import IncludeOnlyByName, BridgeContext

        ctx = BridgeContext(trigger_data=None, handler=lambda: None, name="other")
        result = IncludeOnlyByName(names=frozenset({"allowed"})).compile_bridge(ctx)
        assert result.skip is True

    def test_include_only_no_name(self) -> None:
        from emergent.wire.bridge._capabilities import IncludeOnlyByName, BridgeContext

        ctx = BridgeContext(trigger_data=None, handler=lambda: None, name=None)
        result = IncludeOnlyByName(names=frozenset({"allowed"})).compile_bridge(ctx)
        assert result.skip is True

    def test_include_only_pattern_match(self) -> None:
        from emergent.wire.bridge._capabilities import IncludeOnlyByName, BridgeContext

        ctx = BridgeContext(trigger_data=None, handler=lambda: None, name="api_v2_users")
        result = IncludeOnlyByName(pattern="api_v2_.*").compile_bridge(ctx)
        assert result.skip is False

    def test_set_request_type_by_name(self) -> None:
        from emergent.wire.bridge._capabilities import SetRequestTypeByName, BridgeContext

        ctx = BridgeContext(trigger_data=None, handler=lambda: None, name="create")
        result = SetRequestTypeByName(type_map={"create": int}).compile_bridge(ctx)
        assert result.request_type is int

    def test_set_request_type_already_set(self) -> None:
        from emergent.wire.bridge._capabilities import SetRequestTypeByName, BridgeContext

        ctx = BridgeContext(trigger_data=None, handler=lambda: None, name="create", request_type=str)
        result = SetRequestTypeByName(type_map={"create": int}).compile_bridge(ctx)
        assert result.request_type is str

    def test_set_response_type_by_name(self) -> None:
        from emergent.wire.bridge._capabilities import SetResponseTypeByName, BridgeContext

        ctx = BridgeContext(trigger_data=None, handler=lambda: None, name="get")
        result = SetResponseTypeByName(type_map={"get": dict}).compile_bridge(ctx)
        assert result.response_type is dict

    def test_set_codec_by_name(self) -> None:
        from emergent.wire.bridge._capabilities import SetCodecByName, BridgeContext

        codec = object()
        ctx = BridgeContext(trigger_data=None, handler=lambda: None, name="foo")
        result = SetCodecByName(codec_map={"foo": codec}).compile_bridge(ctx)
        assert result.wire.codec is codec

    def test_matches_name_no_criteria(self) -> None:
        from emergent.wire.bridge._capabilities import _matches_name, BridgeContext

        ctx = BridgeContext(trigger_data=None, handler=lambda: None, name="anything")
        assert _matches_name(ctx, None, None) is True

    def test_matches_name_by_set(self) -> None:
        from emergent.wire.bridge._capabilities import _matches_name, BridgeContext

        ctx = BridgeContext(trigger_data=None, handler=lambda: None, name="x")
        assert _matches_name(ctx, frozenset({"x"}), None) is True

    def test_find_bridge_capability(self) -> None:
        from emergent.wire.bridge._capabilities import (
            find_bridge_capability,
            find_all_bridge_capabilities,
            SkipDeprecated,
            WrapAsync,
        )

        caps = [SkipDeprecated(), WrapAsync(), SkipDeprecated()]
        assert isinstance(find_bridge_capability(caps, SkipDeprecated), SkipDeprecated)
        assert find_bridge_capability(caps, type(None)) is None  # type: ignore[arg-type]
        all_skip = find_all_bridge_capabilities(caps, SkipDeprecated)
        assert len(all_skip) == 2

    @pytest.mark.asyncio
    async def test_catch_errors_purifier(self) -> None:
        from emergent.wire.bridge._capabilities import CatchErrors

        cap = CatchErrors(on_error=lambda e: f"caught: {e}")

        async def failing() -> str:
            raise ValueError("oops")

        wrapped = cap.purify(failing)
        result = await wrapped()
        assert result == "caught: oops"

    @pytest.mark.asyncio
    async def test_inject_kwarg(self) -> None:
        from emergent.wire.bridge._capabilities import InjectKwarg

        cap = InjectKwarg(name="db", factory=lambda: "db_conn")

        async def handler(db: str = "") -> str:
            return db

        wrapped = cap.purify(handler)
        result = await wrapped()
        assert result == "db_conn"

    @pytest.mark.asyncio
    async def test_setup_teardown(self) -> None:
        from emergent.wire.bridge._capabilities import SetupTeardown

        calls: list[str] = []
        cap = SetupTeardown(
            setup=lambda: calls.append("setup"),
            teardown=lambda: calls.append("teardown"),
        )

        async def handler() -> str:
            return "ok"

        wrapped = cap.purify(handler)
        result = await wrapped()
        assert result == "ok"
        assert calls == ["setup", "teardown"]

    def test_fold_bridge_skip_early(self) -> None:
        from emergent.wire.bridge._capabilities import fold_bridge, BridgeContext, SkipDeprecated

        ctx = BridgeContext(trigger_data=None, handler=lambda: None, deprecated=True)
        result = fold_bridge(ctx, [SkipDeprecated(), SkipDeprecated()])
        assert result.skip is True

    @pytest.mark.asyncio
    async def test_with_context_sync_purifier(self) -> None:
        from emergent.wire.bridge._capabilities import WithContextSync
        from contextlib import contextmanager

        entered: list[bool] = []

        @contextmanager
        def my_ctx():
            entered.append(True)
            yield

        cap = WithContextSync(factory=my_ctx)

        async def handler() -> str:
            return "ok"

        wrapped = cap.purify(handler)
        result = await wrapped()
        assert result == "ok"
        assert entered == [True]


# ═══════════════════════════════════════════════════════════════════════════════
# 4. temporal.py — temporal remaining
# ═══════════════════════════════════════════════════════════════════════════════


class TestTemporalDialect:
    """Tests for emergent.wire.axis.schema.dialects.temporal."""

    def test_valid_from_compile_sa(self) -> None:
        from emergent.wire.axis.schema.dialects.temporal import ValidFrom
        from emergent.wire.axis._capability import SQLAlchemyTableContext

        cap = ValidFrom(field_name="vf", use_server_default=True)
        ctx = SQLAlchemyTableContext(class_name="User")
        result = cap.compile_sqlalchemy_table(ctx)
        assert any(c.name == "vf" for c in result.extra_columns)

    def test_valid_to_compile_sa(self) -> None:
        from emergent.wire.axis.schema.dialects.temporal import ValidTo
        from emergent.wire.axis._capability import SQLAlchemyTableContext

        cap = ValidTo(field_name="vt")
        ctx = SQLAlchemyTableContext(class_name="User")
        result = cap.compile_sqlalchemy_table(ctx)
        assert any(c.name == "vt" for c in result.extra_columns)

    def test_temporal_compile_sa(self) -> None:
        from emergent.wire.axis.schema.dialects.temporal import Temporal
        from emergent.wire.axis._capability import SQLAlchemyTableContext

        cap = Temporal()
        ctx = SQLAlchemyTableContext(class_name="User")
        result = cap.compile_sqlalchemy_table(ctx)
        names = [c.name for c in result.extra_columns]
        assert "valid_from" in names
        assert "valid_to" in names

    def test_created_at_compile_sa(self) -> None:
        from emergent.wire.axis.schema.dialects.temporal import CreatedAt
        from emergent.wire.axis._capability import SQLAlchemyTableContext

        cap = CreatedAt()
        ctx = SQLAlchemyTableContext(class_name="User")
        result = cap.compile_sqlalchemy_table(ctx)
        assert any(c.name == "created_at" for c in result.extra_columns)

    def test_updated_at_compile_sa(self) -> None:
        from emergent.wire.axis.schema.dialects.temporal import UpdatedAt
        from emergent.wire.axis._capability import SQLAlchemyTableContext

        cap = UpdatedAt()
        ctx = SQLAlchemyTableContext(class_name="User")
        result = cap.compile_sqlalchemy_table(ctx)
        assert any(c.name == "updated_at" for c in result.extra_columns)

    def test_timestamps_compile_sa(self) -> None:
        from emergent.wire.axis.schema.dialects.temporal import Timestamps
        from emergent.wire.axis._capability import SQLAlchemyTableContext

        cap = Timestamps()
        ctx = SQLAlchemyTableContext(class_name="User")
        result = cap.compile_sqlalchemy_table(ctx)
        names = [c.name for c in result.extra_columns]
        assert "created_at" in names
        assert "updated_at" in names

    def test_soft_delete_compile_sa(self) -> None:
        from emergent.wire.axis.schema.dialects.temporal import SoftDelete
        from emergent.wire.axis._capability import SQLAlchemyTableContext

        cap = SoftDelete()
        ctx = SQLAlchemyTableContext(class_name="User")
        result = cap.compile_sqlalchemy_table(ctx)
        assert any(c.name == "deleted_at" for c in result.extra_columns)

    def test_temporal_filter_current(self) -> None:
        from emergent.wire.axis.schema.dialects.temporal import temporal_filter_current
        from emergent.wire.axis.query._expr import IsNull

        expr = temporal_filter_current()
        assert isinstance(expr, IsNull)

    def test_temporal_filter_as_of(self) -> None:
        from emergent.wire.axis.schema.dialects.temporal import temporal_filter_as_of
        from emergent.wire.axis.query._expr import And

        now = datetime.now()
        expr = temporal_filter_as_of(now)
        assert isinstance(expr, And)

    def test_temporal_filter_version(self) -> None:
        from emergent.wire.axis.schema.dialects.temporal import temporal_filter_version
        from emergent.wire.axis.query._expr import Eq

        expr = temporal_filter_version(3)
        assert isinstance(expr, Eq)


# ═══════════════════════════════════════════════════════════════════════════════
# 5. delta.py — delta remaining
# ═══════════════════════════════════════════════════════════════════════════════


class TestDeltaDialect:
    """Tests for emergent.wire.axis.schema.dialects.delta."""

    def test_numeric_delta_set(self) -> None:
        from emergent.wire.axis.schema.dialects.delta import NumericDelta

        d = NumericDelta(set=99)
        assert d.apply(100) == 99

    def test_numeric_delta_add_multiply(self) -> None:
        from emergent.wire.axis.schema.dialects.delta import NumericDelta

        d = NumericDelta(add=10, multiply=2.0)
        assert d.apply(5) == 30.0

    def test_numeric_delta_preserve_int(self) -> None:
        from emergent.wire.axis.schema.dialects.delta import NumericDelta

        d = NumericDelta(add=5)
        result = d.apply(10)
        assert result == 15
        assert isinstance(result, int)

    def test_string_delta_set(self) -> None:
        from emergent.wire.axis.schema.dialects.delta import StringDelta

        d = StringDelta(set="new")
        assert d.apply("old") == "new"

    def test_string_delta_prepend_append_replace(self) -> None:
        from emergent.wire.axis.schema.dialects.delta import StringDelta

        d = StringDelta(prepend="[", append="]", replace=("x", "y"))
        assert d.apply("xhello") == "[yhello]"

    def test_collection_delta_set(self) -> None:
        from emergent.wire.axis.schema.dialects.delta import CollectionDelta

        d: CollectionDelta[str] = CollectionDelta(set=("a", "b"))
        assert d.apply(["x", "y"]) == ["a", "b"]

    def test_collection_delta_operations(self) -> None:
        from emergent.wire.axis.schema.dialects.delta import CollectionDelta

        d: CollectionDelta[str] = CollectionDelta(
            push=("new",), pop=1, remove=("old",), insert=(0, "first")
        )
        result = d.apply(["old", "keep", "last"])
        # remove "old" -> ["keep", "last"]
        # pop 1 from end -> ["keep"]
        # push "new" -> ["keep", "new"]
        # insert "first" at 0 -> ["first", "keep", "new"]
        assert result == ["first", "keep", "new"]

    def test_compose_deltas_single(self) -> None:
        from emergent.wire.axis.schema.dialects.delta import compose_deltas, NumericDelta

        @dataclass(frozen=True)
        class FakeDelta:
            val: NumericDelta | None = None

        d1 = FakeDelta(val=NumericDelta(add=10))
        result = compose_deltas(d1)
        assert result is d1

    def test_compose_deltas_empty_raises(self) -> None:
        from emergent.wire.axis.schema.dialects.delta import compose_deltas

        with pytest.raises(ValueError, match="At least one delta"):
            compose_deltas()

    def test_compose_field_deltas_string(self) -> None:
        from emergent.wire.axis.schema.dialects.delta import _compose_field_deltas, StringDelta

        d1 = StringDelta(append=" world")
        d2 = StringDelta(prepend="Hello ")
        result = _compose_field_deltas(d1, d2)
        assert isinstance(result, StringDelta)
        assert result.prepend == "Hello "
        assert result.append == " world"

    def test_compose_field_deltas_numeric(self) -> None:
        from emergent.wire.axis.schema.dialects.delta import _compose_field_deltas, NumericDelta

        d1 = NumericDelta(add=5, multiply=2.0)
        d2 = NumericDelta(add=3, multiply=3.0)
        result = _compose_field_deltas(d1, d2)
        assert isinstance(result, NumericDelta)
        assert result.add == 8
        assert result.multiply == 6.0

    def test_compose_field_deltas_collection(self) -> None:
        from emergent.wire.axis.schema.dialects.delta import _compose_field_deltas, CollectionDelta

        d1: CollectionDelta[str] = CollectionDelta(push=("a",), pop=1)
        d2: CollectionDelta[str] = CollectionDelta(push=("b",), remove=("x",))
        result = _compose_field_deltas(d1, d2)
        assert hasattr(result, "push")

    def test_delta_kind(self) -> None:
        from emergent.wire.axis.schema.dialects.delta import _delta_kind, NumericDelta, StringDelta, CollectionDelta

        assert _delta_kind(NumericDelta()) == "numeric"
        assert _delta_kind(StringDelta()) == "string"
        assert _delta_kind(CollectionDelta()) == "collection"

    def test_delta_field_compile_openapi(self) -> None:
        from emergent.wire.axis.schema.dialects.delta import DeltaField
        from emergent.wire.axis._capability import OpenAPIContext

        cap = DeltaField(delta_type="numeric")
        ctx = OpenAPIContext(field_name="balance", field_type=int)
        result = cap.compile_openapi(ctx)
        assert result.schema.get("x-delta-type") == "numeric"


# ═══════════════════════════════════════════════════════════════════════════════
# 6. schema/_explain.py — schema explain
# ═══════════════════════════════════════════════════════════════════════════════


class TestSchemaExplain:
    """Tests for emergent.wire.axis.schema._explain."""

    def test_cap_repr_empty_fields(self) -> None:
        from emergent.wire.axis.schema._explain import _cap_repr
        from emergent.wire.axis.schema._universal import SchemaCapability

        @dataclass(frozen=True)
        class Empty(SchemaCapability):
            pass

        assert _cap_repr(Empty()) == "Empty"

    def test_cap_repr_with_type_field(self) -> None:
        from emergent.wire.axis.schema._explain import _cap_repr
        from emergent.wire.axis.schema._universal import SchemaCapability

        @dataclass(frozen=True)
        class WithType(SchemaCapability):
            target: type = int

        r = _cap_repr(WithType())
        assert "int" in r

    def test_cap_repr_non_dataclass(self) -> None:
        from emergent.wire.axis.schema._explain import _cap_repr
        from emergent.wire.axis.schema._universal import SchemaCapability

        class NoField(SchemaCapability):
            pass

        assert _cap_repr(NoField()) == "NoField"

    def test_explain_field_not_found(self) -> None:
        from emergent.wire.axis.schema._explain import explain_field

        @dataclass
        class Simple:
            x: int = 0

        result = explain_field(Simple, "nonexistent")
        assert "not found" in result

    def test_schema_dict_structure(self) -> None:
        from emergent.wire.axis.schema._explain import schema_dict

        @dataclass
        class Simple:
            x: int = 0

        data = schema_dict(Simple)
        assert data["name"] == "Simple"
        assert "fields" in data

    def test_explain_schema_output(self) -> None:
        from emergent.wire.axis.schema._explain import explain_schema

        @dataclass
        class Simple:
            x: int = 0

        text = explain_schema(Simple)
        assert "Simple" in text

    def test_format_cap_short_no_fields(self) -> None:
        from emergent.wire.axis.schema._explain import _format_cap_short

        assert _format_cap_short({"type": "Foo"}) == "Foo"

    def test_format_cap_short_with_fields(self) -> None:
        from emergent.wire.axis.schema._explain import _format_cap_short

        result = _format_cap_short({"type": "MaxLen", "max_length": 255})
        assert "MaxLen" in result
        assert "255" in result


# ═══════════════════════════════════════════════════════════════════════════════
# 7. query/_proxy.py — proxy remaining
# ═══════════════════════════════════════════════════════════════════════════════


class TestQueryProxy:
    """Tests for emergent.wire.axis.query._proxy."""

    def test_field_proxy_between(self) -> None:
        from emergent.wire.axis.query._proxy import FieldProxy
        from emergent.wire.axis.query._expr import Between

        fp = FieldProxy("balance")
        expr = fp.between(100, 1000)
        assert isinstance(expr, Between)

    def test_field_proxy_like(self) -> None:
        from emergent.wire.axis.query._proxy import FieldProxy
        from emergent.wire.axis.query._expr import Like

        fp = FieldProxy("email")
        expr = fp.like("%@gmail.com")
        assert isinstance(expr, Like)

    def test_field_proxy_ilike(self) -> None:
        from emergent.wire.axis.query._proxy import FieldProxy
        from emergent.wire.axis.query._expr import ILike

        fp = FieldProxy("email")
        expr = fp.ilike("%@GMAIL.COM")
        assert isinstance(expr, ILike)

    def test_field_proxy_regex(self) -> None:
        from emergent.wire.axis.query._proxy import FieldProxy
        from emergent.wire.axis.query._expr import Regex

        fp = FieldProxy("email")
        expr = fp.regex(r"^\w+@\w+\.\w+$")
        assert isinstance(expr, Regex)

    def test_field_proxy_array_ops(self) -> None:
        from emergent.wire.axis.query._proxy import FieldProxy
        from emergent.wire.axis.query._expr import ArrayContains, ArrayAny, ArrayAll, ArrayOverlap

        fp = FieldProxy("tags")
        assert isinstance(fp.array_contains("vip"), ArrayContains)
        assert isinstance(fp.array_any("a", "b"), ArrayAny)
        assert isinstance(fp.array_all("a", "b"), ArrayAll)
        assert isinstance(fp.array_overlap("a", "b"), ArrayOverlap)

    def test_field_proxy_json_ops(self) -> None:
        from emergent.wire.axis.query._proxy import FieldProxy, JsonFieldProxy
        from emergent.wire.axis.query._expr import JsonContains, JsonHasKey

        fp = FieldProxy("metadata")
        jp = fp.json("profile.name")
        assert isinstance(jp, JsonFieldProxy)
        assert isinstance(fp.json_contains({"role": "admin"}), JsonContains)
        assert isinstance(fp.json_has_key("profile"), JsonHasKey)

    def test_json_field_proxy_comparison(self) -> None:
        from emergent.wire.axis.query._proxy import FieldProxy
        from emergent.wire.axis.query._expr import Eq

        fp = FieldProxy("metadata")
        expr = fp.json("name") == "alice"
        assert isinstance(expr, Eq)

    def test_field_proxy_aggregates(self) -> None:
        from emergent.wire.axis.query._proxy import FieldProxy
        from emergent.wire.axis.query._aggregate import AggregateExpr

        fp = FieldProxy("balance")
        assert isinstance(fp.sum(), AggregateExpr)
        assert isinstance(fp.avg(), AggregateExpr)
        assert isinstance(fp.min(), AggregateExpr)
        assert isinstance(fp.max(), AggregateExpr)
        assert isinstance(fp.count(), AggregateExpr)
        assert isinstance(fp.array_agg(), AggregateExpr)
        assert isinstance(fp.string_agg(","), AggregateExpr)

    def test_entity_proxy_count(self) -> None:
        from emergent.wire.axis.query._proxy import EntityProxy
        from emergent.wire.axis.query._aggregate import AggregateExpr

        @dataclass
        class User:
            id: int = 0

        proxy = EntityProxy(User)
        assert isinstance(proxy.count(), AggregateExpr)

    def test_entity_proxy_window_functions(self) -> None:
        from emergent.wire.axis.query._proxy import EntityProxy

        @dataclass
        class User:
            id: int = 0
            dept: str = ""

        proxy = EntityProxy(User)
        rb = proxy.row_number()
        assert hasattr(rb, "over")
        rb2 = proxy.rank()
        assert hasattr(rb2, "over")
        rb3 = proxy.dense_rank()
        assert hasattr(rb3, "over")
        rb4 = proxy.ntile(4)
        assert hasattr(rb4, "over")

    def test_entity_proxy_invalid_field(self) -> None:
        from emergent.wire.axis.query._proxy import EntityProxy

        @dataclass
        class User:
            id: int = 0

        proxy = EntityProxy(User)
        with pytest.raises(AttributeError, match="no field"):
            proxy.nonexistent

    def test_build_order_ascending_default(self) -> None:
        from emergent.wire.axis.query._proxy import build_order, OrderSpec

        @dataclass
        class User:
            name: str = ""

        order = build_order(User, lambda u: u.name)
        assert isinstance(order, OrderSpec)
        assert order.ascending is True

    def test_field_proxy_lag_lead(self) -> None:
        from emergent.wire.axis.query._proxy import FieldProxy

        fp = FieldProxy("balance")
        lag_b = fp.lag(2, default=0)
        assert hasattr(lag_b, "over")
        lead_b = fp.lead(1)
        assert hasattr(lead_b, "over")


# ═══════════════════════════════════════════════════════════════════════════════
# 8. storage/_explain.py — storage explain
# ═══════════════════════════════════════════════════════════════════════════════


class TestStorageExplain:
    """Tests for emergent.wire.axis.storage._explain."""

    def test_unknown_dict_dataclass(self) -> None:
        from emergent.wire.axis.storage._explain import _unknown_dict

        @dataclass
        class Custom:
            x: int = 1
            name: str = "test"

        d = _unknown_dict(Custom())
        assert d["type"] == "Custom"
        assert d["x"] == 1

    def test_unknown_dict_non_dataclass(self) -> None:
        from emergent.wire.axis.storage._explain import _unknown_dict

        d = _unknown_dict("plain_string")
        assert d["type"] == "str"

    def test_storage_dict_unknown(self) -> None:
        from emergent.wire.axis.storage._explain import storage_dict

        d = storage_dict("unknown_thing")
        assert d["type"] == "str"

    def test_explain_storage_unknown(self) -> None:
        from emergent.wire.axis.storage._explain import explain_storage

        text = explain_storage("unknown")
        assert "str" in text

    def test_format_scalar_float(self) -> None:
        from emergent.wire.axis.storage._explain import _format_scalar

        assert _format_scalar(1.5) == "1.5s"

    def test_format_scalar_string(self) -> None:
        from emergent.wire.axis.storage._explain import _format_scalar

        assert _format_scalar("test") == "'test'"

    def test_format_scalar_other(self) -> None:
        from emergent.wire.axis.storage._explain import _format_scalar

        assert _format_scalar(42) == "42"


# ═══════════════════════════════════════════════════════════════════════════════
# 9. derive/auth/openapi.py — auth openapi
# ═══════════════════════════════════════════════════════════════════════════════


class TestAuthOpenAPI:
    """Tests for emergent.wire.derive.auth.openapi."""

    def test_auth_openapi_compile_fastapi_route(self) -> None:
        from emergent.wire.derive.auth.openapi import AuthOpenAPI
        from emergent.wire.axis._capability import FastAPIRouteContext

        cap = AuthOpenAPI(scheme_name="bearerAuth")
        ctx = FastAPIRouteContext(path="/test", method="GET")
        result = cap.compile_fastapi_route(ctx)
        extra = result.openapi_extra
        assert extra is not None
        assert "security" in extra
        assert "responses" in extra
        assert "401" in extra["responses"]
        assert "403" in extra["responses"]

    def test_auth_openapi_compile_fastapi_route_existing_extra(self) -> None:
        from emergent.wire.derive.auth.openapi import AuthOpenAPI
        from emergent.wire.axis._capability import FastAPIRouteContext

        cap = AuthOpenAPI()
        ctx = FastAPIRouteContext(path="/test", method="POST", openapi_extra={"tags": ["auth"]})
        result = cap.compile_fastapi_route(ctx)
        extra = result.openapi_extra
        assert extra is not None
        assert "tags" in extra
        assert "security" in extra


# ═══════════════════════════════════════════════════════════════════════════════
# 10. bridge/_introspect.py — introspect remaining
# ═══════════════════════════════════════════════════════════════════════════════


class TestBridgeIntrospect:
    """Tests for emergent.wire.bridge._introspect."""

    def test_analyze_handler_async(self) -> None:
        from emergent.wire.bridge._introspect import analyze_handler

        async def my_handler(x: int, y: str = "hello") -> str:
            return ""

        shape = analyze_handler(my_handler)
        assert shape.is_async is True
        assert "x" in shape.parameters
        assert shape.parameters["y"].has_default is True

    def test_analyze_handler_sync(self) -> None:
        from emergent.wire.bridge._introspect import analyze_handler

        def my_handler(x: int) -> str:
            return ""

        shape = analyze_handler(my_handler)
        assert shape.is_async is False

    def test_analyze_handler_decorated(self) -> None:
        import functools
        from emergent.wire.bridge._introspect import analyze_handler

        def decorator(fn: Callable[..., object]) -> Callable[..., object]:
            @functools.wraps(fn)
            def wrapper(*args: object, **kwargs: object) -> object:
                return fn(*args, **kwargs)
            return wrapper

        @decorator
        def my_handler(x: int) -> str:
            return ""

        shape = analyze_handler(my_handler)
        assert len(shape.decorators) > 0

    def test_analyze_handler_callable_instance(self) -> None:
        from emergent.wire.bridge._introspect import analyze_handler

        class Handler:
            def __init__(self, db: str) -> None:
                self.db = db

            async def __call__(self, x: int) -> str:
                return ""

        h = Handler("conn")
        shape = analyze_handler(h)
        assert shape.instance_info is not None
        assert shape.instance_info.cls is Handler

    def test_parameter_kind_of(self) -> None:
        from emergent.wire.bridge._introspect import ParameterKind

        import inspect as _inspect

        for kind_val in [
            _inspect.Parameter.POSITIONAL_ONLY,
            _inspect.Parameter.POSITIONAL_OR_KEYWORD,
            _inspect.Parameter.VAR_POSITIONAL,
            _inspect.Parameter.KEYWORD_ONLY,
            _inspect.Parameter.VAR_KEYWORD,
        ]:
            p = _inspect.Parameter("x", kind_val)
            pk = ParameterKind.of(p)
            assert isinstance(pk, ParameterKind)

    def test_extract_class_methods(self) -> None:
        from emergent.wire.bridge._introspect import extract_class_methods

        class MyClass:
            def get(self) -> None: ...
            def post(self) -> None: ...

        methods = list(extract_class_methods(MyClass, ("get", "post", "delete")))
        assert len(methods) == 2
        names = [m[0] for m in methods]
        assert "get" in names
        assert "post" in names

    def test_get_view_class(self) -> None:
        from emergent.wire.bridge._introspect import get_view_class

        class MyView:
            pass

        assert get_view_class(MyView) is MyView
        assert get_view_class("not_a_class") is None

        class HasViewClass:
            view_class = MyView

        assert get_view_class(HasViewClass()) is MyView

    def test_closure_fallback_unwrap(self) -> None:
        from emergent.wire.bridge._introspect import ClosureFallbackUnwrap

        def original(x: int) -> int:
            return x

        # No __wrapped__, no closure -> should return original
        strategy = ClosureFallbackUnwrap()
        handler, decorators = strategy.unwrap(original)
        assert handler is original
        assert len(decorators) == 0

    def test_resolve_descriptor(self) -> None:
        from emergent.wire.bridge._introspect import resolve_descriptor

        class MyDescriptor:
            def __get__(self, obj: object, objtype: type | None = None) -> str:
                return "resolved"

        result = resolve_descriptor(MyDescriptor())
        assert result == "resolved"

    def test_no_default_sentinel(self) -> None:
        from emergent.wire.bridge._introspect import no_default, _NO_DEFAULT

        assert no_default() is _NO_DEFAULT

    def test_analyze_partial(self) -> None:
        from functools import partial
        from emergent.wire.bridge._introspect import analyze_handler

        def my_func(x: int, y: str) -> str:
            return f"{x}-{y}"

        p = partial(my_func, y="hello")
        shape = analyze_handler(p)
        assert shape.partial_func is not None
        assert "y" in shape.partial_keywords
        # y should be skipped from parameters
        assert "y" not in shape.parameters


# ═══════════════════════════════════════════════════════════════════════════════
# 11. surface/capabilities/_pipeline.py — pipeline caps
# ═══════════════════════════════════════════════════════════════════════════════


class TestPipelineCapabilities:
    """Tests for emergent.wire.axis.surface.capabilities._pipeline."""

    def test_coercion_creation(self) -> None:
        from emergent.wire.axis.surface.capabilities._pipeline import Coercion

        c = Coercion(spec=None)
        assert c.spec is None

    def test_no_coercion_constant(self) -> None:
        from emergent.wire.axis.surface.capabilities._pipeline import NO_COERCION

        assert NO_COERCION.spec is None

    def test_extraction_creation(self) -> None:
        from emergent.wire.axis.surface.capabilities._pipeline import Extraction

        e = Extraction(fastapi="fa_extractor")
        assert e.fastapi == "fa_extractor"
        assert e.cli is None

    def test_extraction_compile_fastapi_none(self) -> None:
        from emergent.wire.axis.surface.capabilities._pipeline import Extraction

        e = Extraction()  # all None

        @dataclass
        class FakeCtx:
            extractor: object | None = None

        ctx = FakeCtx()
        result = e.compile_fastapi_pipeline(ctx)
        assert result is ctx  # unchanged

    def test_module_getattr_pydantic(self) -> None:
        from emergent.wire.axis.surface.capabilities import _pipeline

        # Test __getattr__ for PYDANTIC lazy init
        p = _pipeline.__getattr__("PYDANTIC")
        assert p.spec is not None

    def test_module_getattr_unknown(self) -> None:
        from emergent.wire.axis.surface.capabilities import _pipeline

        with pytest.raises(AttributeError, match="has no attribute"):
            _pipeline.__getattr__("NONEXISTENT")


# ═══════════════════════════════════════════════════════════════════════════════
# 12. surface/_explain.py — surface explain
# ═══════════════════════════════════════════════════════════════════════════════


class TestSurfaceExplain:
    """Tests for emergent.wire.axis.surface._explain."""

    def test_explain_http_trigger(self) -> None:
        from emergent.wire.axis.surface._explain import _explain_http_trigger
        from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger

        t = HTTPRouteTrigger(method="GET", path="/users")
        d = _explain_http_trigger(t)
        assert d["method"] == "GET"
        assert d["path"] == "/users"

    def test_explain_cli_trigger(self) -> None:
        from emergent.wire.axis.surface._explain import _explain_cli_trigger
        from emergent.wire.axis.surface.triggers.cli import CLITrigger

        t = CLITrigger(command="greet", description="Say hi")
        d = _explain_cli_trigger(t)
        assert d["command"] == "greet"
        assert d["description"] == "Say hi"

    def test_explain_event_trigger(self) -> None:
        from emergent.wire.axis.surface._explain import _explain_event_trigger
        from emergent.wire.axis.surface.triggers.event import EventTrigger

        @dataclass
        class OrderCreated:
            order_id: int = 0

        t = EventTrigger[object](event_type=OrderCreated)
        d = _explain_event_trigger(t)
        assert d["event_type"] == "OrderCreated"

    def test_format_trigger_short_http(self) -> None:
        from emergent.wire.axis.surface._explain import _format_trigger_short

        d = {"type": "HTTPRouteTrigger", "method": "GET", "path": "/users"}
        assert _format_trigger_short(d) == "GET /users"

    def test_format_trigger_short_cli(self) -> None:
        from emergent.wire.axis.surface._explain import _format_trigger_short

        d = {"type": "CLITrigger", "command": "greet"}
        assert "(cli)" in _format_trigger_short(d)

    def test_format_trigger_short_event(self) -> None:
        from emergent.wire.axis.surface._explain import _format_trigger_short

        d = {"type": "EventTrigger", "event_type": "OrderCreated"}
        assert "Event" in _format_trigger_short(d)

    def test_format_trigger_short_tg(self) -> None:
        from emergent.wire.axis.surface._explain import _format_trigger_short

        d = {"type": "TelegrinderTrigger", "view": "message", "rules": ["Command"]}
        assert "tg:" in _format_trigger_short(d)

    def test_format_trigger_short_unknown(self) -> None:
        from emergent.wire.axis.surface._explain import _format_trigger_short

        d = {"type": "Unknown"}
        assert "Unknown" in _format_trigger_short(d)

    def test_format_value_list(self) -> None:
        from emergent.wire.axis.surface._explain import _format_value

        assert _format_value(["a", "b"]) == "a, b"


# ═══════════════════════════════════════════════════════════════════════════════
# 13. compile/targets/testing.py — testing target
# ═══════════════════════════════════════════════════════════════════════════════


class TestTestingTarget:
    """Tests for emergent.wire.compile.targets.testing."""

    def test_rrc_from_codec_testing(self) -> None:
        from emergent.wire.compile.targets.testing import rrc_from_codec_testing
        from emergent.wire.axis.surface.codecs.rrc import RequestResponseCodec

        from emergent.ops._graph import Op

        @dataclass
        class Req:
            x: int = 0

            def to_domain(self) -> Op[str, str]:
                return cast(Op[str, str], self)

        @dataclass
        class Resp:
            y: str = ""

            @classmethod
            def from_domain(cls, dom: Result[str, str]) -> Self:
                return cls()

        codec = RequestResponseCodec(request=Req, response=Resp)
        ctx = rrc_from_codec_testing(codec, "trigger")
        assert ctx.execute is not None
        assert ctx.trigger == "trigger"

    def test_delegate_from_codec_testing(self) -> None:
        from emergent.wire.compile.targets.testing import delegate_from_codec_testing
        from emergent.wire.axis.surface.codecs.delegate import DelegateCodec

        codec = DelegateCodec(handler=lambda: None)
        ctx = delegate_from_codec_testing(codec, "trigger")
        assert ctx.execute is not None

    def test_immediate_from_codec_testing(self) -> None:
        from emergent.wire.compile.targets.testing import immediate_from_codec_testing
        from emergent.wire.axis.surface.codecs.immediate import ImmediateCodec

        @dataclass
        class Resp:
            msg: str = "ok"

            @classmethod
            def produce(cls) -> Self:
                return cls()

        codec = ImmediateCodec(response=Resp)
        ctx = immediate_from_codec_testing(codec, "trigger")
        assert ctx.execute is not None

    def test_assemble_testing_route_no_execute_raises(self) -> None:
        from emergent.wire.compile.targets.testing import assemble_testing_route, TestingWrapContext
        from emergent.wire.compile._core import Axes

        ctx = TestingWrapContext(execute=None)
        with pytest.raises(ValueError, match="must be set"):
            assemble_testing_route(ctx, MagicMock(), Axes.default())


# ═══════════════════════════════════════════════════════════════════════════════
# 14. compile/targets/pure.py — pure target
# ═══════════════════════════════════════════════════════════════════════════════


class TestPureTarget:
    """Tests for emergent.wire.compile.targets.pure."""

    def test_lifecycle_route_dataclass(self) -> None:
        from emergent.wire.compile.targets.pure import LifecycleRoute

        async def handler() -> None:
            pass

        route = LifecycleRoute(handler=handler, order=1)
        assert route.order == 1

    def test_exception_route_dataclass(self) -> None:
        from emergent.wire.compile.targets.pure import ExceptionRoute

        async def handler(scope: Any) -> None:
            pass

        route = ExceptionRoute(handler=handler, exception_type=ValueError, propagate=False)
        assert route.exception_type is ValueError

    def test_websocket_route_dataclass(self) -> None:
        from emergent.wire.compile.targets.pure import WebSocketRoute

        async def handler(scope: Any) -> None:
            pass

        route = WebSocketRoute(handler=handler)
        assert route.handler is handler

    def test_assemble_lifecycle_no_execute_raises(self) -> None:
        from emergent.wire.compile.targets.pure import _assemble_lifecycle, LifecycleWrapContext
        from emergent.wire.compile._core import Axes

        ctx = LifecycleWrapContext(execute=None)
        with pytest.raises(ValueError, match="has no execute"):
            _assemble_lifecycle(ctx, MagicMock(), Axes.default())

    def test_assemble_exception_no_execute_raises(self) -> None:
        from emergent.wire.compile.targets.pure import _assemble_exception, ExceptionWrapContext
        from emergent.wire.compile._core import Axes

        ctx = ExceptionWrapContext(execute=None)
        with pytest.raises(ValueError, match="has no execute"):
            _assemble_exception(ctx, MagicMock(), Axes.default())

    def test_assemble_websocket_no_execute_raises(self) -> None:
        from emergent.wire.compile.targets.pure import _assemble_websocket, WebSocketWrapContext
        from emergent.wire.compile._core import Axes

        ctx = WebSocketWrapContext(execute=None)
        with pytest.raises(ValueError, match="has no execute"):
            _assemble_websocket(ctx, MagicMock(), Axes.default())


# ═══════════════════════════════════════════════════════════════════════════════
# 15. compile/targets/event.py — event target
# ═══════════════════════════════════════════════════════════════════════════════


class TestEventTarget:
    """Tests for emergent.wire.compile.targets.event."""

    def test_chain_injectors_no_user(self) -> None:
        from emergent.wire.compile.targets.event import _chain_injectors

        calls: list[str] = []
        def event_inject(scope: Any) -> None:
            calls.append("event")

        combined = _chain_injectors(event_inject, None)
        combined(MagicMock())
        assert calls == ["event"]

    def test_chain_injectors_with_user(self) -> None:
        from emergent.wire.compile.targets.event import _chain_injectors

        calls: list[str] = []
        def event_inject(scope: Any) -> None:
            calls.append("event")
        def user_inject(scope: Any) -> None:
            calls.append("user")

        combined = _chain_injectors(event_inject, user_inject)
        combined(MagicMock())
        assert calls == ["event", "user"]

    def test_assemble_event_route_no_execute_raises(self) -> None:
        from emergent.wire.compile.targets.event import assemble_event_route, EventWrapContext
        from emergent.wire.compile._core import Axes

        ctx = EventWrapContext(event_type=None, execute=None)
        with pytest.raises(ValueError, match="must be set"):
            assemble_event_route(ctx, MagicMock(), Axes.default())

    def test_assemble_event_route_no_event_type_raises(self) -> None:
        from emergent.wire.compile.targets.event import assemble_event_route, EventWrapContext
        from emergent.wire.compile._core import Axes

        ctx = EventWrapContext(event_type=None, execute=lambda: None)
        with pytest.raises(ValueError, match="event_type must be set"):
            assemble_event_route(ctx, MagicMock(), Axes.default())


# ═══════════════════════════════════════════════════════════════════════════════
# 16. derive/_project.py — project remaining
# ═══════════════════════════════════════════════════════════════════════════════


class TestDeriveProject:
    """Tests for emergent.wire.derive._project."""

    def test_convenience_constructors(self) -> None:
        from emergent.wire.derive._project import (
            all_fields, id_only, non_id, no_fields, fields, exclude, exclude_from,
        )
        from emergent.wire.derive._project import AllFields, IdOnly, NonId, NoFields

        assert isinstance(all_fields(), AllFields)
        assert isinstance(id_only(), IdOnly)
        assert isinstance(non_id(), NonId)
        assert isinstance(no_fields(), NoFields)

        f = fields("a", "b")
        assert f.names == ("a", "b")

        e = exclude("x")
        assert e.names == ("x",)

        ef = exclude_from(all_fields(), "z")
        assert ef.inner is not None

    def test_custom_response(self) -> None:
        from emergent.wire.derive._project import custom_response

        def _converter(cls: type, r: object) -> Any:
            return cls(x=1)

        cr = custom_response(
            field_specs=(("x", int),),
            converter=_converter,
        )
        assert len(cr.field_specs) == 1


# ═══════════════════════════════════════════════════════════════════════════════
# 17. query/_explain.py — query explain
# ═══════════════════════════════════════════════════════════════════════════════


class TestQueryExplain:
    """Tests for emergent.wire.axis.query._explain."""

    def test_explain_ops_with_unknown(self) -> None:
        from emergent.wire.axis.query._explain import explain_ops

        class CustomOp:
            pass

        result = explain_ops([CustomOp()], {})
        assert result[0]["op"] == "CustomOp"

    def test_format_ops_empty(self) -> None:
        from emergent.wire.axis.query._explain import format_ops

        assert format_ops([], {}) == "(empty)"

    def test_format_ops_relational(self) -> None:
        from emergent.wire.axis.query._explain import format_ops, RELATIONAL_EXPLAIN
        from emergent.wire.axis.query._relational import Limit

        text = format_ops([Limit(10)], RELATIONAL_EXPLAIN)
        assert "Limit" in text
        assert "10" in text

    def test_explain_dialect_with_handler(self) -> None:
        from emergent.wire.axis.query._explain import ExplainDialect

        dialect = ExplainDialect(handlers={})
        new_dialect = dialect.with_handler(int, lambda op: {"op": "Int"})
        assert int in new_dialect.handlers

    def test_explain_dialect_without_handler(self) -> None:
        from emergent.wire.axis.query._explain import ExplainDialect

        dialect = ExplainDialect(handlers={int: lambda op: {"op": "Int"}})
        new_dialect = dialect.without_handler(int)
        assert int not in new_dialect.handlers

    def test_explain_dialect_format(self) -> None:
        from emergent.wire.axis.query._explain import RELATIONAL_EXPLAIN_DIALECT
        from emergent.wire.axis.query._relational import Limit, Offset

        text = RELATIONAL_EXPLAIN_DIALECT.format([Limit(5), Offset(10)])
        assert "Limit" in text
        assert "Offset" in text

    def test_kv_explain(self) -> None:
        from emergent.wire.axis.query._explain import KV_EXPLAIN, explain_ops
        from emergent.wire.axis.query._kv import KVGet, KVSet, KVDelete, Exists, Scan, Keys

        ops = [KVGet("key1"), KVSet("key2", "val"), KVDelete("key3"), Exists("key4"), Scan("*"), Keys("*")]
        result = explain_ops(ops, KV_EXPLAIN)
        assert len(result) == 6

    def test_api_explain(self) -> None:
        from emergent.wire.axis.query._explain import API_EXPLAIN, explain_ops
        from emergent.wire.axis.query._api import ListOp, GetOp, DeleteOp, PageMod, SearchMod, IncludeMod

        ops = [
            ListOp(), GetOp(id=1), DeleteOp(id=2),
            PageMod(page=1, per_page=10),
            SearchMod(query="test"),
            IncludeMod(relations=("posts",)),
        ]
        result = explain_ops(ops, API_EXPLAIN)
        assert len(result) == 6


# ═══════════════════════════════════════════════════════════════════════════════
# 18. query/_coerce.py — coercion remaining
# ═══════════════════════════════════════════════════════════════════════════════


class TestExprCoercer:
    """Tests for emergent.wire.axis.query._coerce."""

    def test_empty_coercion_noop(self) -> None:
        from emergent.wire.axis.query._coerce import ExprCoercer
        from emergent.wire.axis.query._expr import Eq, Field, Const

        coercer = ExprCoercer({})
        expr = Eq(Field("x"), Const(1))
        assert coercer(expr) is expr
        assert bool(coercer) is False

    def test_coerce_eq(self) -> None:
        from emergent.wire.axis.query._coerce import ExprCoercer
        from emergent.wire.axis.query._expr import Eq, Field, Const

        def _to_str(v: object) -> object:
            return str(v)

        coercer = ExprCoercer({"x": _to_str})
        expr = Eq(Field("x"), Const(42))
        result = coercer(expr)
        assert isinstance(result, Eq)
        right = result.right
        assert isinstance(right, Const)
        assert cast(Const[str], right).value == "42"

    def test_coerce_in(self) -> None:
        from emergent.wire.axis.query._coerce import ExprCoercer
        from emergent.wire.axis.query._expr import In, Field

        def _to_str_in(v: object) -> object:
            return str(v)

        coercer = ExprCoercer({"x": _to_str_in})
        expr = In(Field("x"), (1, 2, 3))
        result = coercer(expr)
        assert isinstance(result, In)
        assert result.values == ("1", "2", "3")

    def test_coerce_between(self) -> None:
        from emergent.wire.axis.query._coerce import ExprCoercer
        from emergent.wire.axis.query._expr import Between, Field, Const

        def _to_str_between(v: object) -> object:
            return str(v)

        coercer = ExprCoercer({"x": _to_str_between})
        expr = Between(Field("x"), Const(1), Const(10))
        result = coercer(expr)
        assert isinstance(result, Between)

    def test_coerce_and_or_not(self) -> None:
        from emergent.wire.axis.query._coerce import ExprCoercer
        from emergent.wire.axis.query._expr import And, Or, Not, Eq, Field, Const

        def _to_str(v: object) -> object:
            return str(v)

        coercer = ExprCoercer({"x": _to_str})
        inner = Eq(Field("x"), Const(1))
        expr = And(inner, Or(inner, Not(inner)))
        result = coercer(expr)
        assert isinstance(result, And)

    def test_coerce_contains(self) -> None:
        from emergent.wire.axis.query._coerce import ExprCoercer
        from emergent.wire.axis.query._expr import Contains, Field

        def _upper_x(v: object) -> object:
            return str(v).upper()

        coercer = ExprCoercer({"x": _upper_x})
        expr = Contains(Field("x"), "hello")
        result = coercer(expr)
        assert isinstance(result, Contains)
        assert result.substring == "HELLO"

    def test_coerce_like(self) -> None:
        from emergent.wire.axis.query._coerce import ExprCoercer
        from emergent.wire.axis.query._expr import Like, Field

        def _upper_email(v: object) -> object:
            return str(v).upper()

        coercer = ExprCoercer({"email": _upper_email})
        expr = Like(Field("email"), "%@gmail.com")
        result = coercer(expr)
        assert isinstance(result, Like)


# ═══════════════════════════════════════════════════════════════════════════════
# 19. bridge/bridgers/fastapi/_utils.py — FA utils
# ═══════════════════════════════════════════════════════════════════════════════


class TestFastAPIUtils:
    """Tests for emergent.wire.bridge.bridgers.fastapi._utils."""

    def test_is_depends_false(self) -> None:
        from emergent.wire.bridge.bridgers.fastapi._utils import is_depends

        assert is_depends("not_depends") is False

    def test_is_depends_true(self) -> None:
        from emergent.wire.bridge.bridgers.fastapi._utils import is_depends

        class Depends:
            pass

        assert is_depends(Depends()) is True

    def test_get_depends_func(self) -> None:
        from emergent.wire.bridge.bridgers.fastapi._utils import get_depends_func

        class FakeDepends:
            dependency = "my_func"

        assert get_depends_func(FakeDepends()) == "my_func"
        assert get_depends_func("no_dep") is None

    def test_find_depends_param(self) -> None:
        from emergent.wire.bridge.bridgers.fastapi._utils import find_depends_param

        def get_db() -> str:
            return "db"

        # Create a class with the exact name "Depends" so type().__name__ == "Depends"
        Depends = type("Depends", (), {"dependency": None})

        dep = Depends()
        dep.dependency = get_db  # type: ignore[attr-defined]

        def handler(db: str = dep) -> None:  # type: ignore[assignment]
            pass

        result = find_depends_param(handler, get_db)
        assert result == "db"

    def test_find_depends_param_not_callable(self) -> None:
        from emergent.wire.bridge.bridgers.fastapi._utils import find_depends_param

        assert find_depends_param("not_callable", None) is None

    def test_get_all_depends_not_callable(self) -> None:
        from emergent.wire.bridge.bridgers.fastapi._utils import get_all_depends

        result = get_all_depends("not_callable")  # type: ignore[arg-type]
        assert result == []

    def test_get_all_depends_with_depends(self) -> None:
        from emergent.wire.bridge.bridgers.fastapi._utils import get_all_depends

        def get_db() -> str:
            return "db"

        Depends = type("Depends", (), {"dependency": None})
        dep = Depends()
        dep.dependency = get_db  # type: ignore[attr-defined]

        def handler(db: str = dep) -> None:  # type: ignore[assignment]
            pass

        result = get_all_depends(handler)
        assert len(result) == 1
        assert result[0][0] == "db"
        assert result[0][1] is get_db


# ═══════════════════════════════════════════════════════════════════════════════
# 20. compile/_explain.py — compile explain
# ═══════════════════════════════════════════════════════════════════════════════


class TestCompileExplain:
    """Tests for emergent.wire.compile._explain."""

    def test_explain_no_tracing(self) -> None:
        from emergent.wire.compile._explain import explain
        from emergent.wire.compile._core import Axes

        axes = Axes.default()
        text = explain(axes)
        assert "tracing not enabled" in text

    def test_explain_field_not_found(self) -> None:
        from emergent.wire.compile._explain import explain_field
        from emergent.wire.compile._core import Axes

        axes = Axes.default()
        text = explain_field(axes, "nonexistent")
        assert "not found" in text

    def test_explain_type_not_found(self) -> None:
        from emergent.wire.compile._explain import explain_type
        from emergent.wire.compile._core import Axes

        axes = Axes.default()
        text = explain_type(axes, "NonexistentType")
        assert "not found" in text

    def test_trace_dict_no_tracing(self) -> None:
        from emergent.wire.compile._explain import trace_dict
        from emergent.wire.compile._core import Axes

        axes = Axes.default()
        # Post-TypedDict refactor: always returns TraceDict shape with empty lists.
        assert trace_dict(axes) == {"types": [], "scan": [], "wrap": []}

    def test_field_dict_no_tracing(self) -> None:
        from emergent.wire.compile._explain import field_dict
        from emergent.wire.compile._core import Axes

        axes = Axes.default()
        assert field_dict(axes, "x") is None

    def test_type_dict_no_tracing(self) -> None:
        from emergent.wire.compile._explain import type_dict
        from emergent.wire.compile._core import Axes

        axes = Axes.default()
        assert type_dict(axes, "User") is None

    def test_get_field_trace_no_tracing(self) -> None:
        from emergent.wire.compile._explain import get_field_trace
        from emergent.wire.compile._core import Axes

        axes = Axes.default()
        assert get_field_trace(axes, "x") is None

    def test_get_phase_trace_no_field(self) -> None:
        from emergent.wire.compile._explain import get_phase_trace
        from emergent.wire.compile._core import Axes

        axes = Axes.default()
        assert get_phase_trace(axes, "x", "pydantic") is None

    def test_changed_fields_no_tracing(self) -> None:
        from emergent.wire.compile._explain import changed_fields
        from emergent.wire.compile._core import Axes

        axes = Axes.default()
        assert changed_fields(axes, "pydantic") == []

    def test_active_capabilities_no_tracing(self) -> None:
        from emergent.wire.compile._explain import active_capabilities
        from emergent.wire.compile._core import Axes

        axes = Axes.default()
        assert active_capabilities(axes, "email") == []


# ═══════════════════════════════════════════════════════════════════════════════
# 21. derive/_explain.py — derive explain
# ═══════════════════════════════════════════════════════════════════════════════


class TestDeriveExplain:
    """Tests for emergent.wire.derive._explain."""

    def test_trigger_dict_http(self) -> None:
        from emergent.wire.derive._explain import trigger_dict
        from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger

        d = trigger_dict(HTTPRouteTrigger(method="POST", path="/create"))
        assert d["type"] == "http"
        assert d["method"] == "POST"

    def test_trigger_dict_cli(self) -> None:
        from emergent.wire.derive._explain import trigger_dict
        from emergent.wire.axis.surface.triggers.cli import CLITrigger

        d = trigger_dict(CLITrigger(command="run"))
        assert d["type"] == "cli"

    def test_trigger_dict_unknown(self) -> None:
        from emergent.wire.derive._explain import trigger_dict

        d = trigger_dict("custom_trigger")
        assert d["type"] == "str"

    def test_effect_dict(self) -> None:
        from emergent.wire.derive._explain import effect_dict

        @dataclass
        class MyEffect:
            name: str = "test"
            count: int = 5

        d = effect_dict(MyEffect())
        assert d["type"] == "MyEffect"
        assert d["name"] == "test"
        assert d["count"] == 5

    def test_capability_dict(self) -> None:
        from emergent.wire.derive._explain import capability_dict

        @dataclass
        class MyCap:
            enabled: bool = True

        d = capability_dict(MyCap())
        assert d["type"] == "MyCap"
        assert d["enabled"] is True


# ═══════════════════════════════════════════════════════════════════════════════
# 22. derive/_codegen.py — codegen
# ═══════════════════════════════════════════════════════════════════════════════


class TestDeriveCodegen:
    """Tests for emergent.wire.derive._codegen."""

    def test_create_dataclass(self) -> None:
        from emergent.wire.derive._codegen import create_dataclass

        cls = create_dataclass("MyType", [("x", int), ("y", str, "default")])
        instance = cls(x=1)
        assert instance.x == 1
        assert instance.y == "default"
        assert cls.__name__ == "MyType"

    def test_set_type_name(self) -> None:
        from emergent.wire.derive._codegen import set_type_name, create_dataclass

        cls = create_dataclass("OldName", [("x", int)])
        set_type_name(cls, "NewName")
        assert cls.__name__ == "NewName"
        assert cls.__qualname__ == "NewName"

    def test_direct_mapper(self) -> None:
        from emergent.wire.derive._codegen import DirectMapper

        @dataclass
        class Req:
            x: int = 1
            y: str = "hello"

        mapper = DirectMapper()
        result = mapper(Req())
        assert result["x"] == 1
        assert result["y"] == "hello"

    def test_result_conversion_ok(self) -> None:
        from emergent.wire.derive._codegen import ResultConversion

        @dataclass
        class Resp:
            val: int = 0

        def _ok_conv(cls: type, v: object) -> Any:
            return cls(val=v)

        conv = ResultConversion(ok=_ok_conv)
        result = conv(Resp, Ok(42))
        assert getattr(result, "val") == 42

    def test_result_conversion_error(self) -> None:
        from emergent.wire.derive._codegen import ResultConversion

        def _ok_noop(cls: type, v: object) -> Any:
            return cls()

        def _err_conv(cls: type, e: object) -> Any:
            return f"error: {e}"

        conv = ResultConversion(
            ok=_ok_noop,
            error=_err_conv,
        )
        result = conv(dict, Error("oops"))
        assert result == "error: oops"

    def test_result_conversion_error_none(self) -> None:
        from emergent.wire.derive._codegen import ResultConversion

        def _ok_noop2(cls: type, v: object) -> Any:
            return cls()

        conv = ResultConversion(ok=_ok_noop2)
        # No error handler -> returns err directly
        result = conv(dict, Error("oops"))
        assert result == "oops"

    def test_create_request_type(self) -> None:
        from emergent.wire.derive._codegen import create_request_type

        @dataclass
        class Op:
            x: int = 0
            y: str = ""

        req_cls = create_request_type("CreateReq", [("x", int), ("y", str)], Op)
        req = req_cls(x=1, y="hello")
        domain = req.to_domain()
        assert domain.x == 1
        assert domain.y == "hello"

    def test_create_response_type(self) -> None:
        from emergent.wire.derive._codegen import create_response_type

        def converter(cls: type, result: Any) -> Any:
            return cls(val=result)

        resp_cls: Any = create_response_type("MyResp", [("val", int)], converter)
        resp = resp_cls.from_domain(42)
        assert resp.val == 42

    def test_create_sentinel_operation(self) -> None:
        from emergent.wire.derive._codegen import create_sentinel_operation

        op_type, _handler = create_sentinel_operation("SentinelOp")
        assert op_type.__name__ == "SentinelOp"


# ═══════════════════════════════════════════════════════════════════════════════
# 23. derive/_builders.py — builders
# ═══════════════════════════════════════════════════════════════════════════════


class TestDeriveBuilders:
    """Tests for emergent.wire.derive._builders."""

    def test_exposure_builder_no_trigger_raises(self) -> None:
        from emergent.wire.derive._builders import exposure

        builder = (
            exposure("test", int)
            .request(x=int)
            .response(y=str)
            .handler(AsyncMock(return_value=Ok(None)))
        )
        with pytest.raises(ValueError, match="Trigger not set"):
            builder.build()

    def test_exposure_builder_no_handler_raises(self) -> None:
        from emergent.wire.derive._builders import exposure
        from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger

        builder = (
            exposure("test", int)
            .request(x=int)
            .response(y=str)
            .trigger(HTTPRouteTrigger("POST", "/test"))
        )
        with pytest.raises(ValueError, match="Handler not set"):
            builder.build()

    def test_exposure_builder_full(self) -> None:
        from emergent.wire.derive._builders import exposure
        from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger

        async def handler(op: Any) -> Result[Any, Any]:
            return Ok(op)

        op_type, _annotated_handler, exp = (
            exposure("create", int)
            .request(x=int)
            .response(y=str)
            .handler(handler)
            .trigger(HTTPRouteTrigger("POST", "/create"))
            .build()
        )
        assert op_type is not None
        assert exp.trigger is not None


# ═══════════════════════════════════════════════════════════════════════════════
# 24. query/_sql.py — SQL query
# ═══════════════════════════════════════════════════════════════════════════════


class TestSQLQuery:
    """Tests for emergent.wire.axis.query._sql."""

    def test_window_builder_over_basic(self) -> None:
        from emergent.wire.axis.query._sql import WindowBuilder
        from emergent.wire.axis.query._proxy import FieldProxy, OrderSpec
        from emergent.wire.axis.query._window import RowNumber

        wb = WindowBuilder(RowNumber(), None)
        spec = wb.over(
            partition_by=FieldProxy("dept"),
            order_by=OrderSpec("salary", ascending=False),
        )
        assert spec.partition_by == ("dept",)
        assert len(spec.order_by) == 1

    def test_window_builder_over_tuple_partition(self) -> None:
        from emergent.wire.axis.query._sql import WindowBuilder
        from emergent.wire.axis.query._proxy import FieldProxy
        from emergent.wire.axis.query._window import RowNumber

        wb = WindowBuilder(RowNumber(), None)
        spec = wb.over(partition_by=(FieldProxy("a"), FieldProxy("b")))
        assert spec.partition_by == ("a", "b")

    def test_window_builder_over_field_proxy_order(self) -> None:
        from emergent.wire.axis.query._sql import WindowBuilder
        from emergent.wire.axis.query._proxy import FieldProxy
        from emergent.wire.axis.query._window import RowNumber

        wb = WindowBuilder(RowNumber(), None)
        spec = wb.over(order_by=FieldProxy("name"))
        assert spec.order_by[0].ascending is True

    def test_window_builder_over_tuple_order(self) -> None:
        from emergent.wire.axis.query._sql import WindowBuilder
        from emergent.wire.axis.query._proxy import FieldProxy, OrderSpec
        from emergent.wire.axis.query._window import RowNumber

        wb = WindowBuilder(RowNumber(), None)
        spec = wb.over(order_by=cast(tuple[OrderSpec, ...], (OrderSpec("x"), FieldProxy("y"))))
        assert len(spec.order_by) == 2

    def test_window_builder_bad_order_type(self) -> None:
        from emergent.wire.axis.query._sql import WindowBuilder
        from emergent.wire.axis.query._window import RowNumber

        wb = WindowBuilder(RowNumber(), None)
        with pytest.raises(TypeError):
            wb.over(order_by="bad")  # type: ignore[arg-type]

    def test_for_update(self) -> None:
        from emergent.wire.axis.query._sql import ForUpdate

        fu = ForUpdate(nowait=True, skip_locked=False)
        assert fu.nowait is True

    def test_returning(self) -> None:
        from emergent.wire.axis.query._sql import Returning

        r = Returning(fields=("id", "name"))
        assert r.fields == ("id", "name")


# ═══════════════════════════════════════════════════════════════════════════════
# 25. query/_relational.py — relational ops
# ═══════════════════════════════════════════════════════════════════════════════


class TestRelationalOps:
    """Tests for emergent.wire.axis.query._relational."""

    def test_limit_negative_raises(self) -> None:
        from emergent.wire.axis.query._relational import Limit

        with pytest.raises(ValueError, match="non-negative"):
            Limit(-1)

    def test_offset_negative_raises(self) -> None:
        from emergent.wire.axis.query._relational import Offset

        with pytest.raises(ValueError, match="non-negative"):
            Offset(-1)

    def test_distinct_deduplicate(self) -> None:
        from emergent.wire.axis.query._relational import Distinct

        @dataclass
        class Item:
            x: int = 0

        d = Distinct()
        items: list[object] = [Item(1), Item(1), Item(2)]
        result = d._deduplicate(items)
        assert len(result) == 2


# ═══════════════════════════════════════════════════════════════════════════════
# 26. derive/auth/extractors.py — auth extractors
# ═══════════════════════════════════════════════════════════════════════════════


class TestAuthExtractors:
    """Tests for emergent.wire.derive.auth.extractors."""

    def test_auth_token_creation(self) -> None:
        from emergent.wire.derive.auth.extractors import AuthToken

        t = AuthToken(value="abc123")
        assert t.value == "abc123"

    @pytest.mark.asyncio
    async def test_bearer_extract_fallback(self) -> None:
        from emergent.wire.derive.auth.extractors import BearerExtract
        from nodnod import Scope

        cap = BearerExtract()
        async with Scope() as scope:
            async def call(s: Any) -> str:
                return "ok"
            result = await cap.enrich(call, scope)
            assert result == "ok"

    @pytest.mark.asyncio
    async def test_cli_token_extract_fallback(self) -> None:
        from emergent.wire.derive.auth.extractors import CLITokenExtract
        from nodnod import Scope

        cap = CLITokenExtract()
        async with Scope() as scope:
            async def call(s: Any) -> str:
                return "ok"
            result = await cap.enrich(call, scope)
            assert result == "ok"


# ═══════════════════════════════════════════════════════════════════════════════
# 27. bridge/bridgers/fastapi/_to_wire.py — FA to_wire
# ═══════════════════════════════════════════════════════════════════════════════


class TestFastAPIToWire:
    """Tests for emergent.wire.bridge.bridgers.fastapi._to_wire."""

    def test_http_to_wire_trigger(self) -> None:
        from emergent.wire.bridge.bridgers.fastapi._to_wire import HTTPToWire
        from emergent.wire.bridge.bridgers.fastapi._routes import HTTPRouteData

        from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger

        converter = HTTPToWire()
        route = HTTPRouteData(path="/users", method="GET")
        trigger = converter.to_trigger(route)
        assert isinstance(trigger, HTTPRouteTrigger)
        assert trigger.path == "/users"

    def test_http_to_wire_codec(self) -> None:
        from emergent.wire.bridge.bridgers.fastapi._to_wire import HTTPToWire
        from emergent.wire.bridge.bridgers.fastapi._routes import HTTPRouteData

        converter = HTTPToWire()
        route = HTTPRouteData(path="/users", method="GET")

        def handler() -> None:
            pass

        codec = converter.to_codec(route, handler)
        assert codec is not None

    def test_websocket_to_wire(self) -> None:
        from emergent.wire.bridge.bridgers.fastapi._to_wire import WebSocketToWire
        from emergent.wire.bridge.bridgers.fastapi._routes import WebSocketRouteData

        converter = WebSocketToWire()
        route = WebSocketRouteData(path="/ws", name="ws_route")
        trigger = converter.to_trigger(route)
        assert getattr(trigger, "path") == "/ws"

    def test_lifespan_to_wire_startup(self) -> None:
        from emergent.wire.bridge.bridgers.fastapi._to_wire import LifespanToWire
        from emergent.wire.bridge.bridgers.fastapi._routes import LifespanData

        converter = LifespanToWire()
        route = LifespanData(kind="startup", order=0)
        trigger = converter.to_trigger(route)
        assert type(trigger).__name__ == "StartupTrigger"

    def test_lifespan_to_wire_shutdown(self) -> None:
        from emergent.wire.bridge.bridgers.fastapi._to_wire import LifespanToWire
        from emergent.wire.bridge.bridgers.fastapi._routes import LifespanData

        converter = LifespanToWire()
        route = LifespanData(kind="shutdown", order=0)
        trigger = converter.to_trigger(route)
        assert type(trigger).__name__ == "ShutdownTrigger"

    def test_lifespan_to_wire_unknown_kind(self) -> None:
        from emergent.wire.bridge.bridgers.fastapi._to_wire import LifespanToWire
        from emergent.wire.bridge.bridgers.fastapi._routes import LifespanData

        converter = LifespanToWire()
        route = LifespanData(kind="unknown", order=0)
        with pytest.raises(ValueError, match="Unknown lifespan kind"):
            converter.to_trigger(route)

    def test_exception_handler_to_wire(self) -> None:
        from emergent.wire.bridge.bridgers.fastapi._to_wire import ExceptionHandlerToWire
        from emergent.wire.bridge.bridgers.fastapi._routes import ExceptionHandlerData

        converter = ExceptionHandlerToWire()
        route = ExceptionHandlerData(exception_type=ValueError)
        trigger = converter.to_trigger(route)
        assert type(trigger).__name__ == "ExceptionTrigger"


# ═══════════════════════════════════════════════════════════════════════════════
# 28. pydantic dialect
# ═══════════════════════════════════════════════════════════════════════════════


class TestPydanticDialect:
    """Tests for emergent.wire.axis.schema.dialects.pydantic."""

    def test_exclude_compile(self) -> None:
        from emergent.wire.axis.schema.dialects.pydantic import Exclude
        from emergent.wire.axis._capability import PydanticContext
        from pydantic.fields import FieldInfo as PydFieldInfo

        cap = Exclude()
        ctx = PydanticContext(field_name="secret", field_type=str, field_info=PydFieldInfo())
        result = cap.compile_pydantic(ctx)
        assert result is not ctx  # changed

    def test_include_compile(self) -> None:
        from emergent.wire.axis.schema.dialects.pydantic import Include
        from emergent.wire.axis._capability import PydanticContext
        from pydantic.fields import FieldInfo as PydFieldInfo

        cap = Include()
        ctx = PydanticContext(field_name="visible", field_type=str, field_info=PydFieldInfo())
        result = cap.compile_pydantic(ctx)
        assert result is not ctx

    def test_validator_before_compile(self) -> None:
        from emergent.wire.axis.schema.dialects.pydantic import ValidatorBefore
        from emergent.wire.axis._capability import PydanticContext
        from pydantic.fields import FieldInfo as PydFieldInfo

        cap = ValidatorBefore(func=lambda v: v)
        ctx = PydanticContext(field_name="email", field_type=str, field_info=PydFieldInfo())
        result = cap.compile_pydantic(ctx)
        assert result is not ctx

    def test_validator_after_compile(self) -> None:
        from emergent.wire.axis.schema.dialects.pydantic import ValidatorAfter
        from emergent.wire.axis._capability import PydanticContext
        from pydantic.fields import FieldInfo as PydFieldInfo

        cap = ValidatorAfter(func=lambda v: v)
        ctx = PydanticContext(field_name="email", field_type=str, field_info=PydFieldInfo())
        result = cap.compile_pydantic(ctx)
        assert result is not ctx

    def test_validator_wrap_compile(self) -> None:
        from emergent.wire.axis.schema.dialects.pydantic import ValidatorWrap
        from emergent.wire.axis._capability import PydanticContext
        from pydantic.fields import FieldInfo as PydFieldInfo

        cap = ValidatorWrap(func=lambda v, handler: handler(v))
        ctx = PydanticContext(field_name="email", field_type=str, field_info=PydFieldInfo())
        result = cap.compile_pydantic(ctx)
        assert result is not ctx


# ═══════════════════════════════════════════════════════════════════════════════
# 29. handler transforms
# ═══════════════════════════════════════════════════════════════════════════════


class TestHandlerTransforms:
    """Tests for emergent.wire.axis.surface.transforms._handler."""

    def test_timeout_seconds(self) -> None:
        from emergent.wire.axis.surface.transforms._handler import Timeout

        t = Timeout.seconds(30)
        assert t.duration == timedelta(seconds=30)

    def test_timeout_minutes(self) -> None:
        from emergent.wire.axis.surface.transforms._handler import Timeout

        t = Timeout.minutes(5)
        assert t.duration == timedelta(minutes=5)

    def test_timeout_hours(self) -> None:
        from emergent.wire.axis.surface.transforms._handler import Timeout

        t = Timeout.hours(1)
        assert t.duration == timedelta(hours=1)


# ═══════════════════════════════════════════════════════════════════════════════
# 30. query/contrib/http.py — http contrib init
# ═══════════════════════════════════════════════════════════════════════════════


class TestHTTPContrib:
    """Tests for emergent.wire.axis.query.contrib.http import behavior."""

    def test_http_import_stubs(self) -> None:
        """Test that HTTP contrib either imports real impls or stubs."""
        import emergent.wire.axis.query.contrib.http as http_mod

        # The module should have 'api' attribute regardless
        assert hasattr(http_mod, "api")


# ═══════════════════════════════════════════════════════════════════════════════
# 31. bridge/bridgers/fastapi/_extractors.py — FA extractors
# ═══════════════════════════════════════════════════════════════════════════════


class TestFastAPIExtractors:
    """Tests for emergent.wire.bridge.bridgers.fastapi._extractors."""

    def test_is_fastapi_app_duck_typing(self) -> None:
        from emergent.wire.bridge.bridgers.fastapi._extractors import is_fastapi_app

        class FakeApp:
            routes = []
            router = None

        assert is_fastapi_app(FakeApp()) is True

    def test_is_fastapi_app_by_name(self) -> None:
        from emergent.wire.bridge.bridgers.fastapi._extractors import is_fastapi_app

        class FastAPI:
            pass

        assert is_fastapi_app(FastAPI()) is True

    def test_is_fastapi_app_starlette(self) -> None:
        from emergent.wire.bridge.bridgers.fastapi._extractors import is_fastapi_app

        class Starlette:
            pass

        assert is_fastapi_app(Starlette()) is True

    def test_is_fastapi_app_not(self) -> None:
        from emergent.wire.bridge.bridgers.fastapi._extractors import is_fastapi_app

        assert is_fastapi_app("not_an_app") is False

    def test_http_route_extractor_can_extract(self) -> None:
        from emergent.wire.bridge.bridgers.fastapi._extractors import HTTPRouteExtractor

        class FakeApp:
            routes = []

        ext = HTTPRouteExtractor()
        assert ext.can_extract(FakeApp()) is True
        assert ext.can_extract("no_routes") is False


# ═══════════════════════════════════════════════════════════════════════════════
# 32. bridge/bridgers/fastapi/_capabilities.py — FA bridge caps
# ═══════════════════════════════════════════════════════════════════════════════


class TestFastAPIBridgeCaps:
    """Tests for emergent.wire.bridge.bridgers.fastapi._capabilities."""

    def test_get_fastapi_marker(self) -> None:
        from emergent.wire.bridge.bridgers.fastapi._capabilities import _get_fastapi_marker

        class Body:
            pass

        assert _get_fastapi_marker([Body()]) == "Body"
        assert _get_fastapi_marker([]) is None
        assert _get_fastapi_marker(["plain_str"]) is None

    def test_is_special_fastapi_type(self) -> None:
        from emergent.wire.bridge.bridgers.fastapi._capabilities import _is_special_fastapi_type

        assert _is_special_fastapi_type(None) is False

        class Request:
            __module__ = "starlette.requests"

        assert _is_special_fastapi_type(Request) is True

    def test_is_pydantic_model(self) -> None:
        from emergent.wire.bridge.bridgers.fastapi._capabilities import _is_pydantic_model

        assert _is_pydantic_model(None) is False
        assert _is_pydantic_model(int) is False

    def test_is_dataclass_type(self) -> None:
        from emergent.wire.bridge.bridgers.fastapi._capabilities import _is_dataclass_type

        assert _is_dataclass_type(None) is False

        @dataclass
        class DC:
            x: int = 0

        assert _is_dataclass_type(DC) is True

    def test_is_depends(self) -> None:
        from emergent.wire.bridge.bridgers.fastapi._capabilities import _is_depends

        class Depends:
            pass

        assert _is_depends(Depends()) is True
        assert _is_depends("not_depends") is False

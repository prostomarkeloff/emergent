"""Tests for query explain — dict layer, format layer, dialects."""

from __future__ import annotations

from typing import Any
from dataclasses import dataclass

from emergent.wire.axis.query._explain import (
    API_EXPLAIN,
    API_EXPLAIN_DIALECT,
    KV_EXPLAIN,
    KV_EXPLAIN_DIALECT,
    RELATIONAL_EXPLAIN,
    RELATIONAL_EXPLAIN_DIALECT,
    explain_ops,
    format_ops,
)
from emergent.wire.axis.query._expr import (
    And,
    Const,
    Eq,
    Field,
    Gt,
)
from emergent.wire.axis.query._relational import (
    Aggregate,
    AggregateSpec,
    Distinct,
    Filter,
    GroupBy,
    Having,
    Join,
    Limit,
    Offset,
    OrderBy,
    Select,
)
from emergent.wire.axis.query._proxy import OrderSpec
from emergent.wire.axis.query._aggregate import Count, Sum
from emergent.wire.axis.query._kv import (
    Exists,
    Keys,
    KVDelete,
    KVGet,
    KVSet,
    Scan,
)
from emergent.wire.axis.query._api import (
    CreateOp,
    CursorMod,
    DeleteOp,
    FilterMod,
    GetOp,
    IncludeMod,
    ListOp,
    OffsetMod,
    OrderMod,
    PageMod,
    SearchMod,
    SelectMod,
    UpdateOp,
)


@dataclass
class User:
    id: str
    name: str
    active: bool = True


# ─── Relational ──────────────────────────────────────────────────────────────


class TestRelationalExplain:
    def test_filter(self):
        ops = [Filter(Gt(Field("balance"), Const(100)))]
        result = explain_ops(ops, RELATIONAL_EXPLAIN)
        assert len(result) == 1
        assert result[0]["op"] == "Filter"
        assert result[0]["expr"] == "balance > 100"
        assert result[0]["fields"] == ["balance"]

    def test_order_by(self):
        ops = [OrderBy((OrderSpec("name", ascending=True), OrderSpec("id", ascending=False)))]
        result = explain_ops(ops, RELATIONAL_EXPLAIN)
        assert result[0]["op"] == "OrderBy"
        assert result[0]["specs"] == ["name ASC", "id DESC"]

    def test_limit(self):
        result = explain_ops([Limit(10)], RELATIONAL_EXPLAIN)
        assert result[0] == {"op": "Limit", "count": 10}

    def test_offset(self):
        result = explain_ops([Offset(20)], RELATIONAL_EXPLAIN)
        assert result[0] == {"op": "Offset", "count": 20}

    def test_select(self):
        result = explain_ops([Select(("id", "name"))], RELATIONAL_EXPLAIN)
        assert result[0] == {"op": "Select", "fields": ["id", "name"]}

    def test_join(self):
        result = explain_ops(
            [Join(target=User, on=Eq(Field("user_id"), Field("id")), kind="left")],
            RELATIONAL_EXPLAIN,
        )
        assert result[0]["op"] == "Join"
        assert result[0]["target"] == "User"
        assert result[0]["kind"] == "left"

    def test_group_by(self):
        result = explain_ops([GroupBy(("status",))], RELATIONAL_EXPLAIN)
        assert result[0] == {"op": "GroupBy", "fields": ["status"]}

    def test_having(self):
        result = explain_ops([Having(Gt(Field("count"), Const(5)))], RELATIONAL_EXPLAIN)
        assert result[0]["op"] == "Having"
        assert result[0]["expr"] == "count > 5"

    def test_distinct(self):
        result = explain_ops([Distinct()], RELATIONAL_EXPLAIN)
        assert result[0] == {"op": "Distinct"}

    def test_aggregate(self):
        specs = (
            AggregateSpec(func=Count(), field=None, alias="total"),
            AggregateSpec(func=Sum(), field="balance", alias="sum_balance"),
        )
        result = explain_ops([Aggregate(specs)], RELATIONAL_EXPLAIN)
        assert result[0]["op"] == "Aggregate"
        assert result[0]["specs"] == ["total=Count(*)", "sum_balance=Sum(balance)"]

    def test_complex_pipeline(self):
        ops = [
            Filter(And(Eq(Field("active"), Const(True)), Gt(Field("balance"), Const(0)))),
            OrderBy((OrderSpec("balance", ascending=False),)),
            Offset(10),
            Limit(50),
            Select(("id", "name", "balance")),
        ]
        result = explain_ops(ops, RELATIONAL_EXPLAIN)
        assert len(result) == 5
        assert [r["op"] for r in result] == ["Filter", "OrderBy", "Offset", "Limit", "Select"]


# ─── KV ──────────────────────────────────────────────────────────────────────


class TestKVExplain:
    def test_get(self):
        result = explain_ops([KVGet("alice")], KV_EXPLAIN)
        assert result[0] == {"op": "Get", "key": "'alice'"}

    def test_set_no_ttl(self):
        result = explain_ops([KVSet("alice", User("1", "alice"))], KV_EXPLAIN)
        assert result[0]["op"] == "Set"
        assert "ttl" not in result[0]

    def test_set_with_ttl(self):
        result = explain_ops([KVSet("alice", User("1", "alice"), ttl=3600)], KV_EXPLAIN)
        assert result[0]["ttl"] == 3600

    def test_delete(self):
        result = explain_ops([KVDelete("alice")], KV_EXPLAIN)
        assert result[0] == {"op": "Delete", "key": "'alice'"}

    def test_exists(self):
        result = explain_ops([Exists("alice")], KV_EXPLAIN)
        assert result[0] == {"op": "Exists", "key": "'alice'"}

    def test_scan(self):
        result = explain_ops([Scan("user:*")], KV_EXPLAIN)
        assert result[0] == {"op": "Scan", "pattern": "user:*"}

    def test_keys(self):
        result = explain_ops([Keys("*")], KV_EXPLAIN)
        assert result[0] == {"op": "Keys", "pattern": "*"}


# ─── API ─────────────────────────────────────────────────────────────────────


class TestAPIExplain:
    def test_list(self):
        result = explain_ops([ListOp()], API_EXPLAIN)
        assert result[0] == {"op": "List"}

    def test_get(self):
        result = explain_ops([GetOp("user-123")], API_EXPLAIN)
        assert result[0] == {"op": "Get", "id": "'user-123'"}

    def test_create(self):
        result = explain_ops([CreateOp(User("1", "alice"))], API_EXPLAIN)
        assert result[0] == {"op": "Create", "entity_type": "User"}

    def test_update(self):
        result = explain_ops([UpdateOp("1", User("1", "alice"))], API_EXPLAIN)
        assert result[0]["op"] == "Update"

    def test_patch(self):
        result = explain_ops([UpdateOp("1", User("1", "alice"), partial=True)], API_EXPLAIN)
        assert result[0]["op"] == "Patch"

    def test_delete(self):
        result = explain_ops([DeleteOp("user-123")], API_EXPLAIN)
        assert result[0] == {"op": "Delete", "id": "'user-123'"}

    def test_filter_mod(self):
        result = explain_ops([FilterMod(Eq(Field("active"), Const(True)))], API_EXPLAIN)
        assert result[0]["op"] == "Filter"
        assert result[0]["fields"] == ["active"]

    def test_order_mod(self):
        result = explain_ops(
            [OrderMod((OrderSpec("name", ascending=True),))], API_EXPLAIN
        )
        assert result[0]["specs"] == ["name ASC"]

    def test_page_mod(self):
        result = explain_ops([PageMod(2, 50)], API_EXPLAIN)
        assert result[0] == {"op": "Page", "page": 2, "per_page": 50}

    def test_cursor_mod(self):
        result = explain_ops([CursorMod("abc", 20)], API_EXPLAIN)
        assert result[0] == {"op": "Cursor", "cursor": "abc", "limit": 20}

    def test_offset_mod(self):
        result = explain_ops([OffsetMod(100, 50)], API_EXPLAIN)
        assert result[0] == {"op": "Offset", "offset": 100, "limit": 50}

    def test_select_mod(self):
        result = explain_ops([SelectMod(("id", "name"))], API_EXPLAIN)
        assert result[0] == {"op": "Select", "fields": ["id", "name"]}

    def test_search_mod(self):
        result = explain_ops([SearchMod("alice")], API_EXPLAIN)
        assert result[0] == {"op": "Search", "query": "alice"}

    def test_include_mod(self):
        result = explain_ops([IncludeMod(("posts", "comments"))], API_EXPLAIN)
        assert result[0] == {"op": "Include", "relations": ["posts", "comments"]}

    def test_full_api_pipeline(self):
        ops = [
            ListOp(),
            FilterMod(Eq(Field("active"), Const(True))),
            OrderMod((OrderSpec("name", ascending=True),)),
            PageMod(1, 20),
            IncludeMod(("posts",)),
        ]
        result = explain_ops(ops, API_EXPLAIN)
        assert len(result) == 5
        assert [r["op"] for r in result] == ["List", "Filter", "OrderBy", "Page", "Include"]


# ─── Open World ──────────────────────────────────────────────────────────────


class TestOpenWorld:
    def test_unknown_op_produces_type_name(self):
        @dataclass(frozen=True)
        class MyCustomOp:
            value: int

        result = explain_ops([MyCustomOp(42)], RELATIONAL_EXPLAIN)
        assert result[0] == {"op": "MyCustomOp"}

    def test_mixed_known_and_unknown(self):
        @dataclass(frozen=True)
        class CustomOp:
            pass

        ops = [Filter(Eq(Field("x"), Const(1))), CustomOp(), Limit(10)]
        result = explain_ops(ops, RELATIONAL_EXPLAIN)
        assert len(result) == 3
        assert result[0]["op"] == "Filter"
        assert result[1] == {"op": "CustomOp"}
        assert result[2]["op"] == "Limit"

    def test_empty_ops(self):
        result = explain_ops([], RELATIONAL_EXPLAIN)
        assert result == []


# ─── Format Layer ────────────────────────────────────────────────────────────


class TestFormatOps:
    def test_empty(self):
        assert format_ops([], RELATIONAL_EXPLAIN) == "(empty)"

    def test_simple(self):
        text = format_ops([Limit(10)], RELATIONAL_EXPLAIN)
        assert "Limit" in text
        assert "10" in text

    def test_multi_line(self):
        ops = [
            Filter(Gt(Field("balance"), Const(100))),
            Limit(10),
        ]
        text = format_ops(ops, RELATIONAL_EXPLAIN)
        lines = text.strip().split("\n")
        assert len(lines) == 2
        assert "1." in lines[0]
        assert "2." in lines[1]

    def test_unknown_op_formatted(self):
        @dataclass(frozen=True)
        class Foo:
            pass

        text = format_ops([Foo()], RELATIONAL_EXPLAIN)
        assert "Foo" in text

    def test_no_extra_keys_for_simple_ops(self):
        text = format_ops([Distinct()], RELATIONAL_EXPLAIN)
        # Distinct has no extra keys — should just show "Distinct"
        assert "Distinct" in text
        assert "=" not in text


# ─── ExplainDialect ──────────────────────────────────────────────────────────


class TestExplainDialect:
    def test_explain_via_dialect(self):
        result = RELATIONAL_EXPLAIN_DIALECT.explain([Limit(10)])
        assert result[0] == {"op": "Limit", "count": 10}

    def test_format_via_dialect(self):
        text = RELATIONAL_EXPLAIN_DIALECT.format([Limit(10)])
        assert "Limit" in text

    def test_with_handler(self):
        @dataclass(frozen=True)
        class CustomOp:
            n: int

        # ExplainHandler = Callable[[Any], dict[str, Any]], so handler must return dict[str, Any]
        def handle_custom(op: CustomOp) -> dict[str, Any]:
            return {"op": "Custom", "n": op.n}

        extended = RELATIONAL_EXPLAIN_DIALECT.with_handler(CustomOp, handle_custom)
        result = extended.explain([CustomOp(42)])
        assert result[0] == {"op": "Custom", "n": 42}

    def test_with_handler_immutable(self):
        @dataclass(frozen=True)
        class CustomOp:
            pass

        original = RELATIONAL_EXPLAIN_DIALECT
        extended = original.with_handler(CustomOp, lambda op: {"op": "X"})
        # Original unchanged
        assert CustomOp not in original.handlers
        assert CustomOp in extended.handlers

    def test_without_handler(self):
        trimmed = RELATIONAL_EXPLAIN_DIALECT.without_handler(Limit)
        # Limit now falls back to open-world
        result = trimmed.explain([Limit(10)])
        assert result[0] == {"op": "Limit"}  # no count — generic fallback

    def test_api_dialect(self):
        result = API_EXPLAIN_DIALECT.explain([ListOp(), PageMod(1, 20)])
        assert len(result) == 2

    def test_kv_dialect(self):
        result = KV_EXPLAIN_DIALECT.explain([KVGet("key")])
        assert result[0]["op"] == "Get"


# ─── Integration: Explain Complex Pipeline ──────────────────────────────────


class TestIntegrationExplainComplexPipeline:
    def test_relational_pipeline_explain_dict(self):
        ops = [
            Filter(And(Eq(Field("active"), Const(True)), Gt(Field("balance"), Const(0)))),
            OrderBy((OrderSpec("balance", ascending=False), OrderSpec("name", ascending=True))),
            Offset(20),
            Limit(10),
            Select(("id", "name", "balance")),
            Distinct(),
        ]
        result = explain_ops(ops, RELATIONAL_EXPLAIN)
        assert len(result) == 6
        assert result[0]["op"] == "Filter"
        assert "active" in result[0]["fields"]
        assert "balance" in result[0]["fields"]
        assert result[1]["op"] == "OrderBy"
        assert result[1]["specs"] == ["balance DESC", "name ASC"]
        assert result[2] == {"op": "Offset", "count": 20}
        assert result[3] == {"op": "Limit", "count": 10}
        assert result[4] == {"op": "Select", "fields": ["id", "name", "balance"]}
        assert result[5] == {"op": "Distinct"}

    def test_relational_pipeline_format_text(self):
        ops = [
            Filter(Gt(Field("balance"), Const(100))),
            OrderBy((OrderSpec("name", ascending=True),)),
            Limit(50),
            Offset(10),
            Select(("id", "name")),
        ]
        text = format_ops(ops, RELATIONAL_EXPLAIN)
        lines = text.strip().split("\n")
        assert len(lines) == 5
        assert "Filter" in lines[0]
        assert "OrderBy" in lines[1]
        assert "Limit" in lines[2]
        assert "Offset" in lines[3]
        assert "Select" in lines[4]

    def test_api_pipeline_explain(self):
        ops = [
            ListOp(),
            FilterMod(Eq(Field("active"), Const(True))),
            FilterMod(Gt(Field("balance"), Const(100))),
            OrderMod((OrderSpec("name", ascending=True),)),
            PageMod(2, 25),
            SearchMod("test"),
            SelectMod(("id", "name")),
            IncludeMod(("posts",)),
        ]
        result = explain_ops(ops, API_EXPLAIN)
        assert len(result) == 8
        assert result[0]["op"] == "List"
        assert result[1]["op"] == "Filter"
        assert result[2]["op"] == "Filter"
        assert result[3]["op"] == "OrderBy"
        assert result[4] == {"op": "Page", "page": 2, "per_page": 25}
        assert result[5] == {"op": "Search", "query": "test"}
        assert result[6] == {"op": "Select", "fields": ["id", "name"]}
        assert result[7] == {"op": "Include", "relations": ["posts"]}

    def test_api_crud_explain(self):
        user = User(id="1", name="alice")
        ops_create = [CreateOp(user)]
        ops_update = [UpdateOp("1", user)]
        ops_patch = [UpdateOp("1", user, partial=True)]
        ops_delete = [DeleteOp("1")]

        assert explain_ops(ops_create, API_EXPLAIN)[0]["op"] == "Create"
        assert explain_ops(ops_update, API_EXPLAIN)[0]["op"] == "Update"
        assert explain_ops(ops_patch, API_EXPLAIN)[0]["op"] == "Patch"
        assert explain_ops(ops_delete, API_EXPLAIN)[0]["op"] == "Delete"

    def test_explain_via_dialect_object(self):
        ops = [
            Filter(Gt(Field("balance"), Const(100))),
            Limit(10),
        ]
        dict_result = RELATIONAL_EXPLAIN_DIALECT.explain(ops)
        text_result = RELATIONAL_EXPLAIN_DIALECT.format(ops)
        assert len(dict_result) == 2
        assert "Filter" in text_result
        assert "Limit" in text_result

# pyright: reportPrivateUsage=false
"""Property-based & unit tests for verify/, storage axis, and ops/_graph.py gaps.

Covers:
  VERIFY (emergent/wire/verify/):
    - _issue.py: Issue, Severity, VerificationError frozen dataclasses
    - _length.py: LengthVerifyCtx.check() — MinLen > MaxLen, MaxLen == 0
    - _numeric.py: NumericVerifyCtx.check() — all four contradiction patterns
    - _semantics.py: SemanticsVerifyCtx.check() — 5 semantic contradiction/warning cases
    - _verify.py: verify() and verify_raising() end-to-end

  STORAGE (emergent/wire/axis/storage/):
    - _codec.py: PickleCodec, JsonCodec, IdentityCodec encode/decode roundtrip
    - _memory.py: MemoryStorage get/set/delete/set_nx/delete_pattern/keys + TTL
    - _result.py: map_option and map_result combinators
    - _kv.py: KV typed wrapper over MemoryStorage
    - _queue.py: Queue/QueueFull push/pop/peek/length
    - _counter.py: Counter/CounterFull incr/decr/incr_by/decr_by
    - _lock.py: Lock acquire/release/hold context manager
    - _compose.py: PrefixKV, ReadonlyKV, FallbackKV, TieredKV wrappers
    - _file.py: FileStorage persistence
    - _explain.py: storage_dict / explain_storage

  OPS (emergent/ops/_graph.py):
    - _create_node_for_handler: node creation with Op deps
    - Runner.run() with global inject
    - Runner.__call__ returning LazyCoroResult
    - Deep dependency chains
"""

# pyright: reportPrivateUsage=false

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from datetime import timedelta
from typing import Never

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from kungfu import Result, Ok, Error, Option, Some, Nothing

# ═══════════════════════════════════════════════════════════════════════════════
# Verify imports
# ═══════════════════════════════════════════════════════════════════════════════

from emergent.wire.verify._issue import Issue, Severity, VerificationError
from emergent.wire.verify._length import LengthVerifyCtx
from emergent.wire.verify._numeric import NumericVerifyCtx
from emergent.wire.verify._semantics import SemanticsVerifyCtx

# ═══════════════════════════════════════════════════════════════════════════════
# Storage imports
# ═══════════════════════════════════════════════════════════════════════════════

from emergent.wire.axis.storage._codec import PickleCodec, JsonCodec, IdentityCodec
from emergent.wire.axis.storage._memory import MemoryStorage
from emergent.wire.axis.storage._result import map_option, map_result
from emergent.wire.axis.storage._kv import kv
from emergent.wire.axis.storage._queue import queue, queue_full
from emergent.wire.axis.storage._counter import counter, counter_full
from emergent.wire.axis.storage._lock import lock, lock_extend
from emergent.wire.axis.storage._compose import (
    prefix_kv,
    readonly_kv,
    fallback_kv,
    tiered_kv,
)
from emergent.wire.axis.storage._file import FileStorage
from emergent.wire.axis.storage._explain import storage_dict, explain_storage

# ═══════════════════════════════════════════════════════════════════════════════
# Ops imports
# ═══════════════════════════════════════════════════════════════════════════════

from emergent.ops._graph import (
    Op,
    ops,
    _create_node_for_handler,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Part 1: VERIFY
# ═══════════════════════════════════════════════════════════════════════════════


class TestIssueTypes:
    """Issue, Severity, VerificationError are frozen dataclasses/enums."""

    def test_issue_frozen(self) -> None:
        issue = Issue(field="name", severity=Severity.ERROR, message="bad")
        with pytest.raises(AttributeError):
            issue.field = "other"  # type: ignore[misc]

    def test_severity_values(self) -> None:
        assert Severity.ERROR.value == "error"
        assert Severity.WARNING.value == "warning"

    def test_verification_error_carries_issues(self) -> None:
        issues = (
            Issue("a", Severity.ERROR, "err1"),
            Issue("b", Severity.ERROR, "err2"),
        )
        exc = VerificationError("test", issues)
        assert exc.issues == issues
        assert "test" in str(exc)

    def test_issue_eq(self) -> None:
        a = Issue("x", Severity.ERROR, "msg")
        b = Issue("x", Severity.ERROR, "msg")
        assert a == b

    def test_issue_ne(self) -> None:
        a = Issue("x", Severity.ERROR, "msg")
        b = Issue("y", Severity.ERROR, "msg")
        assert a != b


class TestLengthVerifyCtx:
    """LengthVerifyCtx.check() — length constraint validation."""

    def test_no_constraints_no_issues(self) -> None:
        ctx = LengthVerifyCtx(field_name="name", field_type=str)
        assert ctx.check() == ()

    def test_valid_range(self) -> None:
        ctx = LengthVerifyCtx(field_name="name", field_type=str, min_length=1, max_length=10)
        assert ctx.check() == ()

    def test_min_gt_max_is_error(self) -> None:
        ctx = LengthVerifyCtx(field_name="name", field_type=str, min_length=10, max_length=5)
        issues = ctx.check()
        assert len(issues) == 1
        assert issues[0].severity is Severity.ERROR
        assert "MinLen(10) > MaxLen(5)" in issues[0].message

    def test_max_zero_is_warning(self) -> None:
        ctx = LengthVerifyCtx(field_name="code", field_type=str, max_length=0)
        issues = ctx.check()
        assert len(issues) == 1
        assert issues[0].severity is Severity.WARNING
        assert "MaxLen(0)" in issues[0].message

    def test_min_gt_max_and_max_zero(self) -> None:
        ctx = LengthVerifyCtx(field_name="x", field_type=str, min_length=1, max_length=0)
        issues = ctx.check()
        assert len(issues) == 2
        severities = {i.severity for i in issues}
        assert Severity.ERROR in severities
        assert Severity.WARNING in severities

    @given(
        mn=st.integers(min_value=0, max_value=1000),
        mx=st.integers(min_value=0, max_value=1000),
    )
    @settings(max_examples=50)
    def test_property_min_le_max_no_error(self, mn: int, mx: int) -> None:
        assume(mn <= mx and mx > 0)
        ctx = LengthVerifyCtx(field_name="f", field_type=str, min_length=mn, max_length=mx)
        issues = ctx.check()
        errors = [i for i in issues if i.severity is Severity.ERROR]
        assert len(errors) == 0

    @given(
        mn=st.integers(min_value=1, max_value=1000),
        mx=st.integers(min_value=0, max_value=999),
    )
    @settings(max_examples=50)
    def test_property_min_gt_max_always_error(self, mn: int, mx: int) -> None:
        assume(mn > mx)
        ctx = LengthVerifyCtx(field_name="f", field_type=str, min_length=mn, max_length=mx)
        issues = ctx.check()
        errors = [i for i in issues if i.severity is Severity.ERROR]
        assert len(errors) >= 1

    def test_frozen(self) -> None:
        ctx = LengthVerifyCtx(field_name="x", field_type=str)
        with pytest.raises(AttributeError):
            ctx.min_length = 5  # type: ignore[misc]


class TestNumericVerifyCtx:
    """NumericVerifyCtx.check() — numeric constraint validation."""

    def test_no_constraints_no_issues(self) -> None:
        ctx = NumericVerifyCtx(field_name="age", field_type=int)
        assert ctx.check() == ()

    def test_valid_inclusive_range(self) -> None:
        ctx = NumericVerifyCtx(field_name="age", field_type=int, lower_bound=0, upper_bound=100)
        assert ctx.check() == ()

    def test_min_gt_max_error(self) -> None:
        ctx = NumericVerifyCtx(field_name="x", field_type=float, lower_bound=10.0, upper_bound=5.0)
        issues = ctx.check()
        assert len(issues) == 1
        assert issues[0].severity is Severity.ERROR
        assert "Min(10.0) > Max(5.0)" in issues[0].message

    def test_exclusive_min_ge_exclusive_max_error(self) -> None:
        ctx = NumericVerifyCtx(
            field_name="x", field_type=float,
            exclusive_lower=5.0, exclusive_upper=5.0,
        )
        issues = ctx.check()
        assert len(issues) == 1
        assert issues[0].severity is Severity.ERROR
        assert "ExclusiveMin(5.0) >= ExclusiveMax(5.0)" in issues[0].message

    def test_exclusive_min_gt_exclusive_max_error(self) -> None:
        ctx = NumericVerifyCtx(
            field_name="x", field_type=float,
            exclusive_lower=10.0, exclusive_upper=5.0,
        )
        issues = ctx.check()
        assert len(issues) == 1
        assert "ExclusiveMin(10.0) >= ExclusiveMax(5.0)" in issues[0].message

    def test_min_ge_exclusive_max_empty_range(self) -> None:
        ctx = NumericVerifyCtx(
            field_name="x", field_type=float,
            lower_bound=5.0, exclusive_upper=5.0,
        )
        issues = ctx.check()
        assert len(issues) == 1
        assert "empty range" in issues[0].message

    def test_exclusive_min_ge_max_empty_range(self) -> None:
        ctx = NumericVerifyCtx(
            field_name="x", field_type=float,
            exclusive_lower=5.0, upper_bound=5.0,
        )
        issues = ctx.check()
        assert len(issues) == 1
        assert "empty range" in issues[0].message

    def test_multiple_violations(self) -> None:
        """All four conditions fire simultaneously."""
        ctx = NumericVerifyCtx(
            field_name="x",
            field_type=float,
            lower_bound=10.0,
            upper_bound=5.0,
            exclusive_lower=10.0,
            exclusive_upper=5.0,
        )
        issues = ctx.check()
        assert len(issues) == 4
        assert all(i.severity is Severity.ERROR for i in issues)

    @given(
        lo=st.floats(min_value=-1000, max_value=1000, allow_nan=False, allow_infinity=False),
        hi=st.floats(min_value=-1000, max_value=1000, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=50)
    def test_property_valid_range_no_error(self, lo: float, hi: float) -> None:
        assume(lo < hi)
        ctx = NumericVerifyCtx(field_name="f", field_type=float, lower_bound=lo, upper_bound=hi)
        issues = ctx.check()
        assert len(issues) == 0

    def test_frozen(self) -> None:
        ctx = NumericVerifyCtx(field_name="x", field_type=int)
        with pytest.raises(AttributeError):
            ctx.lower_bound = 5.0  # type: ignore[misc]


class TestSemanticsVerifyCtx:
    """SemanticsVerifyCtx.check() — semantic contradiction detection."""

    def test_no_flags_no_issues(self) -> None:
        ctx = SemanticsVerifyCtx(field_name="name", field_type=str)
        assert ctx.check() == ()

    def test_readonly_writeonly_error(self) -> None:
        ctx = SemanticsVerifyCtx(field_name="x", field_type=str, is_read_only=True, is_write_only=True)
        issues = ctx.check()
        errors = [i for i in issues if i.severity is Severity.ERROR]
        assert len(errors) == 1
        assert "inaccessible" in errors[0].message

    def test_computed_writeonly_error(self) -> None:
        ctx = SemanticsVerifyCtx(field_name="x", field_type=str, is_computed=True, is_write_only=True)
        issues = ctx.check()
        errors = [i for i in issues if i.severity is Severity.ERROR]
        assert len(errors) == 1
        assert "Computed + WriteOnly" in errors[0].message

    def test_identity_nullable_warning(self) -> None:
        ctx = SemanticsVerifyCtx(field_name="id", field_type=int, is_identity=True, is_nullable=True)
        issues = ctx.check()
        warnings = [i for i in issues if i.severity is Severity.WARNING]
        assert len(warnings) >= 1
        assert any("Identity + Nullable" in w.message for w in warnings)

    def test_unique_nullable_warning(self) -> None:
        ctx = SemanticsVerifyCtx(field_name="email", field_type=str, is_unique=True, is_nullable=True)
        issues = ctx.check()
        warnings = [i for i in issues if i.severity is Severity.WARNING]
        assert len(warnings) == 1
        assert "Unique + Nullable" in warnings[0].message

    def test_identity_computed_warning(self) -> None:
        ctx = SemanticsVerifyCtx(field_name="id", field_type=int, is_identity=True, is_computed=True)
        issues = ctx.check()
        warnings = [i for i in issues if i.severity is Severity.WARNING]
        assert len(warnings) == 1
        assert "Identity + Computed" in warnings[0].message

    def test_all_contradictions_fire(self) -> None:
        """Trigger all 5 checks at once."""
        ctx = SemanticsVerifyCtx(
            field_name="x",
            field_type=str,
            is_read_only=True,
            is_write_only=True,
            is_computed=True,
            is_identity=True,
            is_unique=True,
            is_nullable=True,
        )
        issues = ctx.check()
        # 2 errors: readonly+writeonly, computed+writeonly
        # 3 warnings: identity+nullable, unique+nullable, identity+computed
        assert len(issues) == 5

    def test_frozen(self) -> None:
        ctx = SemanticsVerifyCtx(field_name="x", field_type=str)
        with pytest.raises(AttributeError):
            ctx.is_read_only = True  # type: ignore[misc]


# ═══════════════════════════════════════════════════════════════════════════════
# Part 2: STORAGE
# ═══════════════════════════════════════════════════════════════════════════════


# ─── Codecs ──────────────────────────────────────────────────────────────────


class TestPickleCodec:
    @given(st.text())
    @settings(max_examples=30)
    def test_roundtrip_strings(self, s: str) -> None:
        codec: PickleCodec[str] = PickleCodec()
        assert codec.decode(codec.encode(s)) == s

    @given(st.integers())
    @settings(max_examples=30)
    def test_roundtrip_ints(self, n: int) -> None:
        codec: PickleCodec[int] = PickleCodec()
        assert codec.decode(codec.encode(n)) == n

    def test_roundtrip_dict(self) -> None:
        codec: PickleCodec[dict[str, int]] = PickleCodec()
        d = {"a": 1, "b": 2}
        assert codec.decode(codec.encode(d)) == d

    def test_roundtrip_list(self) -> None:
        codec: PickleCodec[list[int]] = PickleCodec()
        lst = [1, 2, 3]
        assert codec.decode(codec.encode(lst)) == lst

    def test_encode_returns_bytes(self) -> None:
        codec: PickleCodec[str] = PickleCodec()
        assert isinstance(codec.encode("hello"), bytes)


class TestJsonCodec:
    @given(st.text())
    @settings(max_examples=30)
    def test_roundtrip_strings(self, s: str) -> None:
        codec: JsonCodec[str] = JsonCodec()
        assert codec.decode(codec.encode(s)) == s

    def test_roundtrip_dict(self) -> None:
        codec: JsonCodec[dict[str, int]] = JsonCodec()
        d = {"key": 42}
        assert codec.decode(codec.encode(d)) == d

    def test_encode_is_utf8(self) -> None:
        codec: JsonCodec[str] = JsonCodec()
        encoded = codec.encode("hello")
        assert isinstance(encoded, bytes)
        assert encoded.decode("utf-8") == '"hello"'


class TestIdentityCodec:
    def test_encode_passthrough(self) -> None:
        codec = IdentityCodec()
        data = b"raw bytes"
        assert codec.encode(data) is data

    def test_decode_passthrough(self) -> None:
        codec = IdentityCodec()
        data = b"raw bytes"
        assert codec.decode(data) is data

    @given(st.binary())
    @settings(max_examples=30)
    def test_roundtrip(self, data: bytes) -> None:
        codec = IdentityCodec()
        assert codec.decode(codec.encode(data)) == data


# ─── Result combinators ─────────────────────────────────────────────────────


def _double(x: int) -> int:
    return x * 2


def _add5(x: int) -> int:
    return x + 5


class TestMapOption:
    def test_ok_some_maps(self) -> None:
        result: Result[Option[int], str] = Ok(Some(10))
        mapped: Result[Option[int], str] = map_option(result, _double)
        assert mapped == Ok(Some(20))

    def test_ok_nothing_stays(self) -> None:
        result: Result[Option[int], str] = Ok(Nothing())
        mapped: Result[Option[int], str] = map_option(result, _double)
        assert mapped == Ok(Nothing())

    def test_error_stays(self) -> None:
        result: Result[Option[int], str] = Error("fail")
        mapped: Result[Option[int], str] = map_option(result, _double)
        assert isinstance(mapped, Error)
        assert mapped.error == "fail"


class TestMapResult:
    def test_ok_maps(self) -> None:
        result: Result[int, str] = Ok(10)
        mapped: Result[int, str] = map_result(result, _add5)
        assert mapped == Ok(15)

    def test_error_stays(self) -> None:
        result: Result[int, str] = Error("oops")
        mapped: Result[int, str] = map_result(result, _add5)
        assert isinstance(mapped, Error)


# ─── MemoryStorage ──────────────────────────────────────────────────────────


class TestMemoryStorage:
    @pytest.mark.asyncio
    async def test_get_missing_returns_nothing(self) -> None:
        store: MemoryStorage[str, str] = MemoryStorage()
        result = await store.get("missing")
        assert result == Ok(Nothing())

    @pytest.mark.asyncio
    async def test_set_and_get(self) -> None:
        store: MemoryStorage[str, str] = MemoryStorage()
        await store.set("key", "value")
        result = await store.get("key")
        assert result == Ok(Some("value"))

    @pytest.mark.asyncio
    async def test_delete_existing(self) -> None:
        store: MemoryStorage[str, str] = MemoryStorage()
        await store.set("key", "value")
        await store.delete("key")
        assert await store.get("key") == Ok(Nothing())

    @pytest.mark.asyncio
    async def test_delete_missing_is_ok(self) -> None:
        store: MemoryStorage[str, str] = MemoryStorage()
        result = await store.delete("nonexistent")
        assert result == Ok(None)

    @pytest.mark.asyncio
    async def test_set_with_ttl_expires(self) -> None:
        store: MemoryStorage[str, str] = MemoryStorage()
        # TTL of zero seconds — expires immediately
        await store.set("key", "value", ttl=timedelta(seconds=-1))
        result = await store.get("key")
        assert result == Ok(Nothing())

    @pytest.mark.asyncio
    async def test_set_nx_new_key_returns_true(self) -> None:
        store: MemoryStorage[str, str] = MemoryStorage()
        result = await store.set_nx("key", "value")
        assert result == Ok(True)
        assert await store.get("key") == Ok(Some("value"))

    @pytest.mark.asyncio
    async def test_set_nx_existing_key_returns_false(self) -> None:
        store: MemoryStorage[str, str] = MemoryStorage()
        await store.set("key", "first")
        result = await store.set_nx("key", "second")
        assert result == Ok(False)
        assert await store.get("key") == Ok(Some("first"))

    @pytest.mark.asyncio
    async def test_set_nx_expired_key_allows_overwrite(self) -> None:
        store: MemoryStorage[str, str] = MemoryStorage()
        await store.set("key", "old", ttl=timedelta(seconds=-1))
        result = await store.set_nx("key", "new")
        assert result == Ok(True)
        assert await store.get("key") == Ok(Some("new"))

    @pytest.mark.asyncio
    async def test_delete_pattern(self) -> None:
        store: MemoryStorage[str, str] = MemoryStorage()
        await store.set("user:1", "alice")
        await store.set("user:2", "bob")
        await store.set("session:1", "data")
        result = await store.delete_pattern("user:*")
        assert result == Ok(2)
        assert await store.get("session:1") == Ok(Some("data"))

    @pytest.mark.asyncio
    async def test_delete_pattern_no_match(self) -> None:
        store: MemoryStorage[str, str] = MemoryStorage()
        await store.set("key", "value")
        result = await store.delete_pattern("other:*")
        assert result == Ok(0)

    @pytest.mark.asyncio
    async def test_keys_all(self) -> None:
        store: MemoryStorage[str, str] = MemoryStorage()
        await store.set("a", "1")
        await store.set("b", "2")
        result = await store.keys()
        assert isinstance(result, Ok)
        assert set(result.value) == {"a", "b"}

    @pytest.mark.asyncio
    async def test_keys_with_pattern(self) -> None:
        store: MemoryStorage[str, str] = MemoryStorage()
        await store.set("user:1", "alice")
        await store.set("user:2", "bob")
        await store.set("session:1", "data")
        result = await store.keys("user:*")
        assert isinstance(result, Ok)
        assert set(result.value) == {"user:1", "user:2"}


# ─── KV typed wrapper ───────────────────────────────────────────────────────


class TestKV:
    @pytest.mark.asyncio
    async def test_kv_set_get_roundtrip(self) -> None:
        backend: MemoryStorage[str, bytes] = MemoryStorage()
        store = kv(backend, PickleCodec[dict[str, int]]())
        data = {"count": 42}
        await store.set("key1", data)
        result = await store.get("key1")
        assert result == Ok(Some(data))

    @pytest.mark.asyncio
    async def test_kv_get_missing(self) -> None:
        backend: MemoryStorage[str, bytes] = MemoryStorage()
        store = kv(backend, JsonCodec[str]())
        result = await store.get("missing")
        assert result == Ok(Nothing())

    @pytest.mark.asyncio
    async def test_kv_delete(self) -> None:
        backend: MemoryStorage[str, bytes] = MemoryStorage()
        store = kv(backend, PickleCodec[str]())
        await store.set("key", "value")
        await store.delete("key")
        result = await store.get("key")
        assert result == Ok(Nothing())

    @pytest.mark.asyncio
    async def test_kv_frozen(self) -> None:
        backend: MemoryStorage[str, bytes] = MemoryStorage()
        store = kv(backend, PickleCodec[str]())
        with pytest.raises(AttributeError):
            store.backend = backend  # type: ignore[misc]


# ─── Queue ───────────────────────────────────────────────────────────────────


class _InMemoryQueueBackend:
    """Minimal queue backend for testing."""

    def __init__(self) -> None:
        self._items: list[bytes] = []

    async def push(self, value: bytes) -> Result[None, Never]:
        self._items.append(value)
        return Ok(None)

    async def pop(self) -> Result[Option[bytes], Never]:
        if not self._items:
            return Ok(Nothing())
        return Ok(Some(self._items.pop(0)))

    async def peek(self) -> Result[Option[bytes], Never]:
        if not self._items:
            return Ok(Nothing())
        return Ok(Some(self._items[0]))

    async def length(self) -> Result[int, Never]:
        return Ok(len(self._items))


class TestQueue:
    @pytest.mark.asyncio
    async def test_push_and_pop(self) -> None:
        backend = _InMemoryQueueBackend()
        q = queue(backend, PickleCodec[str]())
        await q.push("hello")
        await q.push("world")
        r1 = await q.pop()
        r2 = await q.pop()
        assert r1 == Ok(Some("hello"))
        assert r2 == Ok(Some("world"))

    @pytest.mark.asyncio
    async def test_pop_empty(self) -> None:
        backend = _InMemoryQueueBackend()
        q = queue(backend, PickleCodec[str]())
        result = await q.pop()
        assert result == Ok(Nothing())


class TestQueueFull:
    @pytest.mark.asyncio
    async def test_peek_without_remove(self) -> None:
        backend = _InMemoryQueueBackend()
        q = queue_full(backend, PickleCodec[int]())
        await q.push(42)
        peek_result = await q.peek()
        assert peek_result == Ok(Some(42))
        # Still there
        pop_result = await q.pop()
        assert pop_result == Ok(Some(42))

    @pytest.mark.asyncio
    async def test_length(self) -> None:
        backend = _InMemoryQueueBackend()
        q = queue_full(backend, JsonCodec[str]())
        assert await q.length() == Ok(0)
        await q.push("a")
        await q.push("b")
        assert await q.length() == Ok(2)


# ─── Counter ─────────────────────────────────────────────────────────────────


class _InMemoryCounterBackend:
    """Minimal counter backend for testing."""

    def __init__(self) -> None:
        self._counters: dict[str, int] = {}

    async def incr(self, key: str) -> Result[int, Never]:
        self._counters[key] = self._counters.get(key, 0) + 1
        return Ok(self._counters[key])

    async def decr(self, key: str) -> Result[int, Never]:
        self._counters[key] = self._counters.get(key, 0) - 1
        return Ok(self._counters[key])

    async def incr_by(self, key: str, amount: int) -> Result[int, Never]:
        self._counters[key] = self._counters.get(key, 0) + amount
        return Ok(self._counters[key])


class TestCounter:
    @pytest.mark.asyncio
    async def test_incr(self) -> None:
        backend = _InMemoryCounterBackend()
        c = counter(backend)
        assert await c.incr("x") == Ok(1)
        assert await c.incr("x") == Ok(2)

    @pytest.mark.asyncio
    async def test_decr(self) -> None:
        backend = _InMemoryCounterBackend()
        c = counter(backend)
        assert await c.decr("x") == Ok(-1)
        assert await c.decr("x") == Ok(-2)


class TestCounterFull:
    @pytest.mark.asyncio
    async def test_incr_by(self) -> None:
        backend = _InMemoryCounterBackend()
        c = counter_full(backend)
        assert await c.incr_by("x", 10) == Ok(10)
        assert await c.incr_by("x", 5) == Ok(15)

    @pytest.mark.asyncio
    async def test_decr_by(self) -> None:
        backend = _InMemoryCounterBackend()
        c = counter_full(backend)
        await c.incr_by("x", 100)
        assert await c.decr_by("x", 30) == Ok(70)

    @pytest.mark.asyncio
    async def test_incr_decr_combo(self) -> None:
        backend = _InMemoryCounterBackend()
        c = counter_full(backend)
        await c.incr("x")
        await c.incr("x")
        await c.decr("x")
        assert await c.incr_by("x", 10) == Ok(11)


# ─── Lock ────────────────────────────────────────────────────────────────────


class _InMemoryLockBackend:
    """Minimal lock backend for testing."""

    def __init__(self) -> None:
        self._locks: set[str] = set()

    async def acquire(self, key: str, ttl: timedelta) -> Result[bool, Never]:
        if key in self._locks:
            return Ok(False)
        self._locks.add(key)
        return Ok(True)

    async def release(self, key: str) -> Result[None, Never]:
        self._locks.discard(key)
        return Ok(None)

    async def extend(self, key: str, ttl: timedelta) -> Result[bool, Never]:
        if key in self._locks:
            return Ok(True)
        return Ok(False)


class TestLock:
    @pytest.mark.asyncio
    async def test_acquire_and_release(self) -> None:
        backend = _InMemoryLockBackend()
        l = lock(backend)
        result = await l.acquire("res:1", timedelta(seconds=30))
        assert result == Ok(True)
        # Cannot acquire again
        result2 = await l.acquire("res:1", timedelta(seconds=30))
        assert result2 == Ok(False)
        # Release
        await l.release("res:1")
        # Can acquire again
        result3 = await l.acquire("res:1", timedelta(seconds=30))
        assert result3 == Ok(True)

    @pytest.mark.asyncio
    async def test_hold_context_manager(self) -> None:
        backend = _InMemoryLockBackend()
        l = lock(backend)
        async with l.hold("res:1", timedelta(seconds=30)) as acquired:
            assert acquired is True
            # Lock is held
            r = await l.acquire("res:1", timedelta(seconds=30))
            assert r == Ok(False)
        # Lock released after context
        r2 = await l.acquire("res:1", timedelta(seconds=30))
        assert r2 == Ok(True)

    @pytest.mark.asyncio
    async def test_hold_not_acquired(self) -> None:
        backend = _InMemoryLockBackend()
        l = lock(backend)
        # Pre-acquire so the hold fails
        await l.acquire("res:1", timedelta(seconds=30))
        async with l.hold("res:1", timedelta(seconds=30)) as acquired:
            assert acquired is False


class TestLockExtend:
    @pytest.mark.asyncio
    async def test_extend(self) -> None:
        backend = _InMemoryLockBackend()
        le = lock_extend(backend)
        await le.acquire("r", timedelta(seconds=30))
        result = await le.extend("r", timedelta(seconds=60))
        assert result == Ok(True)

    @pytest.mark.asyncio
    async def test_extend_not_held(self) -> None:
        backend = _InMemoryLockBackend()
        le = lock_extend(backend)
        result = await le.extend("r", timedelta(seconds=60))
        assert result == Ok(False)

    @pytest.mark.asyncio
    async def test_hold_context_manager(self) -> None:
        backend = _InMemoryLockBackend()
        le = lock_extend(backend)
        async with le.hold("r", timedelta(seconds=30)) as acquired:
            assert acquired is True
        # Released after exit
        r = await le.acquire("r", timedelta(seconds=30))
        assert r == Ok(True)


# ─── Compose (PrefixKV, ReadonlyKV, FallbackKV, TieredKV) ───────────────────


class TestPrefixKV:
    @pytest.mark.asyncio
    async def test_prefix_prepended(self) -> None:
        backend: MemoryStorage[str, bytes] = MemoryStorage()
        inner = kv(backend, PickleCodec[str]())
        p = prefix_kv(inner, "ns:")
        await p.set("key", "value")
        # Check it was stored with prefix in backend
        raw = await backend.get("ns:key")
        assert isinstance(raw, Ok)
        assert isinstance(raw.value, Some)
        # Read through prefix
        result = await p.get("key")
        assert result == Ok(Some("value"))

    @pytest.mark.asyncio
    async def test_prefix_delete(self) -> None:
        backend: MemoryStorage[str, bytes] = MemoryStorage()
        inner = kv(backend, PickleCodec[str]())
        p = prefix_kv(inner, "ns:")
        await p.set("key", "value")
        await p.delete("key")
        assert await p.get("key") == Ok(Nothing())


class TestReadonlyKV:
    @pytest.mark.asyncio
    async def test_get_works(self) -> None:
        backend: MemoryStorage[str, bytes] = MemoryStorage()
        inner = kv(backend, PickleCodec[str]())
        await inner.set("key", "value")
        ro = readonly_kv(inner)
        result = await ro.get("key")
        assert result == Ok(Some("value"))

    @pytest.mark.asyncio
    async def test_set_is_noop(self) -> None:
        backend: MemoryStorage[str, bytes] = MemoryStorage()
        inner = kv(backend, PickleCodec[str]())
        ro = readonly_kv(inner)
        result = await ro.set("key", "value")
        assert result == Ok(Nothing())
        # Nothing was actually stored
        assert await inner.get("key") == Ok(Nothing())

    @pytest.mark.asyncio
    async def test_delete_is_noop(self) -> None:
        backend: MemoryStorage[str, bytes] = MemoryStorage()
        inner = kv(backend, PickleCodec[str]())
        await inner.set("key", "value")
        ro = readonly_kv(inner)
        await ro.delete("key")
        # Key still exists in inner
        assert await inner.get("key") == Ok(Some("value"))


class TestFallbackKV:
    @pytest.mark.asyncio
    async def test_primary_ok(self) -> None:
        b1: MemoryStorage[str, bytes] = MemoryStorage()
        b2: MemoryStorage[str, bytes] = MemoryStorage()
        primary = kv(b1, PickleCodec[str]())
        secondary = kv(b2, PickleCodec[str]())
        fb = fallback_kv(primary, secondary)
        await fb.set("key", "value")
        result = await fb.get("key")
        assert result == Ok(Some("value"))

    @pytest.mark.asyncio
    async def test_delete_primary_ok(self) -> None:
        b1: MemoryStorage[str, bytes] = MemoryStorage()
        b2: MemoryStorage[str, bytes] = MemoryStorage()
        primary = kv(b1, PickleCodec[str]())
        secondary = kv(b2, PickleCodec[str]())
        fb = fallback_kv(primary, secondary)
        await fb.set("key", "value")
        result = await fb.delete("key")
        assert result == Ok(None)


class TestTieredKV:
    @pytest.mark.asyncio
    async def test_l1_hit(self) -> None:
        b1: MemoryStorage[str, bytes] = MemoryStorage()
        b2: MemoryStorage[str, bytes] = MemoryStorage()
        l1 = kv(b1, PickleCodec[str]())
        l2 = kv(b2, PickleCodec[str]())
        tiered = tiered_kv(l1, l2)
        # Put in L1 directly
        await l1.set("key", "fast")
        result = await tiered.get("key")
        assert result == Ok(Some("fast"))

    @pytest.mark.asyncio
    async def test_l2_hit_populates_l1(self) -> None:
        b1: MemoryStorage[str, bytes] = MemoryStorage()
        b2: MemoryStorage[str, bytes] = MemoryStorage()
        l1 = kv(b1, PickleCodec[str]())
        l2 = kv(b2, PickleCodec[str]())
        tiered = tiered_kv(l1, l2)
        # Put in L2 only
        await l2.set("key", "slow")
        result = await tiered.get("key")
        assert result == Ok(Some("slow"))
        # Now L1 should have it too
        assert await l1.get("key") == Ok(Some("slow"))

    @pytest.mark.asyncio
    async def test_set_writes_both(self) -> None:
        b1: MemoryStorage[str, bytes] = MemoryStorage()
        b2: MemoryStorage[str, bytes] = MemoryStorage()
        l1 = kv(b1, PickleCodec[str]())
        l2 = kv(b2, PickleCodec[str]())
        tiered = tiered_kv(l1, l2)
        await tiered.set("key", "both")
        assert await l1.get("key") == Ok(Some("both"))
        assert await l2.get("key") == Ok(Some("both"))

    @pytest.mark.asyncio
    async def test_delete_removes_both(self) -> None:
        b1: MemoryStorage[str, bytes] = MemoryStorage()
        b2: MemoryStorage[str, bytes] = MemoryStorage()
        l1 = kv(b1, PickleCodec[str]())
        l2 = kv(b2, PickleCodec[str]())
        tiered = tiered_kv(l1, l2)
        await tiered.set("key", "value")
        await tiered.delete("key")
        assert await l1.get("key") == Ok(Nothing())
        assert await l2.get("key") == Ok(Nothing())

    @pytest.mark.asyncio
    async def test_miss_both_returns_nothing(self) -> None:
        b1: MemoryStorage[str, bytes] = MemoryStorage()
        b2: MemoryStorage[str, bytes] = MemoryStorage()
        l1 = kv(b1, PickleCodec[str]())
        l2 = kv(b2, PickleCodec[str]())
        tiered = tiered_kv(l1, l2)
        result = await tiered.get("missing")
        assert result == Ok(Nothing())


# ─── FileStorage ─────────────────────────────────────────────────────────────


class TestFileStorage:
    @pytest.mark.asyncio
    async def test_persist_and_reload(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "store.pickle")
            store: FileStorage[str, str] = FileStorage(path)
            await store.set("key", "value")
            # Create new instance that loads from file
            store2: FileStorage[str, str] = FileStorage(path)
            result = await store2.get("key")
            assert result == Ok(Some("value"))

    @pytest.mark.asyncio
    async def test_persist_creates_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "subdir", "store.pickle")
            store: FileStorage[str, str] = FileStorage(path)
            await store.set("key", "value")
            assert os.path.exists(path)

    @pytest.mark.asyncio
    async def test_load_nonexistent_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "missing.pickle")
            store: FileStorage[str, str] = FileStorage(path)
            result = await store.get("key")
            assert result == Ok(Nothing())


# ─── Explain ─────────────────────────────────────────────────────────────────


class TestStorageExplain:
    def test_storage_dict_kv(self) -> None:
        backend: MemoryStorage[str, bytes] = MemoryStorage()
        store = kv(backend, PickleCodec[str]())
        d = storage_dict(store)
        assert d["type"] == "KV"
        assert d["codec"] == "PickleCodec"
        assert d["backend"] == "MemoryStorage"

    def test_storage_dict_prefix_kv(self) -> None:
        backend: MemoryStorage[str, bytes] = MemoryStorage()
        inner = kv(backend, JsonCodec[str]())
        p = prefix_kv(inner, "ns:")
        d = storage_dict(p)
        assert d["type"] == "PrefixKV"
        assert d["prefix"] == "ns:"
        assert d["inner"]["type"] == "KV"

    def test_explain_storage_string(self) -> None:
        backend: MemoryStorage[str, bytes] = MemoryStorage()
        store = kv(backend, PickleCodec[str]())
        text = explain_storage(store)
        assert "KV" in text
        assert "PickleCodec" in text

    def test_storage_dict_unknown_type(self) -> None:
        class CustomThing:
            pass
        d = storage_dict(CustomThing())
        assert d["type"] == "CustomThing"


# ═══════════════════════════════════════════════════════════════════════════════
# Part 3: OPS/_GRAPH.PY
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class FetchData(Op[str, str]):
    url: str


@dataclass(frozen=True, slots=True)
class Transform(Op[int, str]):
    raw: FetchData


@dataclass(frozen=True, slots=True)
class Aggregate(Op[str, str]):
    transform: Transform


async def handle_fetch(req: FetchData) -> Result[str, str]:
    return Ok(f"data-from-{req.url}")


async def handle_transform(req: Transform, raw: FetchData) -> Result[int, str]:
    r = await raw
    match r:
        case Ok(val):
            return Ok(len(val))
        case Error(e):
            return Error(e)


async def handle_aggregate(req: Aggregate, transform: Transform) -> Result[str, str]:
    r = await transform
    match r:
        case Ok(val):
            return Ok(f"aggregated:{val}")
        case Error(e):
            return Error(e)


class _InjectedConfig:
    def __init__(self, base: str) -> None:
        self.base = base


async def _handle_with_config(req: FetchData, config: _InjectedConfig) -> Result[str, str]:
    return Ok(f"{config.base}/{req.url}")


class TestOpsCreateNode:
    def test_create_node_simple(self) -> None:
        """_create_node_for_handler creates a node class for a simple handler."""
        registry: dict[type[Op[object, object]], type] = {}
        op_params: dict[type[Op[object, object]], set[str]] = {}
        node_cls = _create_node_for_handler(FetchData, handle_fetch, registry, op_params)
        assert node_cls is not None
        assert "Node:FetchData" in node_cls.__name__

    def test_create_node_with_dep(self) -> None:
        """_create_node_for_handler wires Op dependencies as node deps."""
        registry: dict[type[Op[object, object]], type] = {}
        op_params: dict[type[Op[object, object]], set[str]] = {}
        # First register FetchData's node
        fetch_node = _create_node_for_handler(FetchData, handle_fetch, registry, op_params)
        registry[FetchData] = fetch_node
        # Now create Transform's node with dependency on FetchData
        transform_node = _create_node_for_handler(Transform, handle_transform, registry, op_params)
        assert transform_node is not None
        assert "raw" in op_params[Transform]


class TestRunnerDeepChain:
    @pytest.mark.asyncio
    async def test_three_level_chain(self) -> None:
        """Three-level deep dependency chain resolves correctly."""
        runner = (
            ops()
            .on(FetchData, handle_fetch)
            .on(Transform, handle_transform)
            .on(Aggregate, handle_aggregate)
            .compile()
        )
        fetch = FetchData(url="example.com")
        transform = Transform(raw=fetch)
        req = Aggregate(transform=transform)
        result = await runner.run(req)
        assert isinstance(result, Ok)
        assert "aggregated:" in result.value

    @pytest.mark.asyncio
    async def test_runner_global_inject(self) -> None:
        """Runner.inject() makes dependencies available to all handlers."""
        runner = ops().on(FetchData, _handle_with_config).compile()
        runner.inject(_InjectedConfig, _InjectedConfig("https://api"))
        result = await runner.run(FetchData(url="data"))
        assert isinstance(result, Ok)
        assert result.value == "https://api/data"

    @pytest.mark.asyncio
    async def test_runner_call_returns_lazy(self) -> None:
        """Runner.__call__ wraps run in LazyCoroResult."""
        runner = ops().on(FetchData, handle_fetch).compile()
        lazy = runner(FetchData(url="lazy"))
        result = await lazy
        assert isinstance(result, Ok)
        assert "data-from-lazy" in result.value

    @pytest.mark.asyncio
    async def test_collect_deps_deep(self) -> None:
        """_collect_op_deps recursively collects 3-level dependencies."""
        runner = (
            ops()
            .on(FetchData, handle_fetch)
            .on(Transform, handle_transform)
            .on(Aggregate, handle_aggregate)
            .compile()
        )
        fetch = FetchData(url="x")
        transform = Transform(raw=fetch)
        req = Aggregate(transform=transform)
        deps = runner._collect_op_deps(req)
        dep_types = [t for t, _ in deps]
        assert Transform in dep_types
        assert FetchData in dep_types
        assert len(deps) == 2

    @pytest.mark.asyncio
    async def test_unregistered_op_returns_error(self) -> None:
        """Running an unregistered op returns Error."""
        runner = ops().on(FetchData, handle_fetch).compile()
        result = await runner.run(Transform(raw=FetchData(url="x")))
        assert isinstance(result, Error)

    def test_builder_returns_new_instance(self) -> None:
        """OpsBuilder.on() returns a new builder (immutable)."""
        b1 = ops()
        b2 = b1.on(FetchData, handle_fetch)
        assert b1 is not b2
        assert len(b1._items) == 0
        assert len(b2._items) == 1

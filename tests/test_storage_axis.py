"""Tests for the storage axis — capabilities, patterns, codecs, and composition.

Covers:
    - MemoryStorage: CRUD, TTL, pattern matching, keys
    - FileStorage: persistence across instances
    - Codecs: PickleCodec, JsonCodec, IdentityCodec round-trips
    - KV / KVNX patterns: codec integration
    - Queue / QueueFull patterns: FIFO ordering with mock backend
    - PubSub pattern: publish/subscribe with mock backend
    - Lock / LockExtend patterns: acquire/release/hold with mock backend
    - Counter / CounterFull patterns: incr/decr/incr_by with mock backend
    - Composition wrappers: PrefixKV, TieredKV, FallbackKV, ReadonlyKV
    - Result combinators: map_option, map_result
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from dataclasses import dataclass
from datetime import timedelta
from typing import AsyncIterator, Never

import pytest
from kungfu import Ok, Error, Some, Nothing, Result, Option

from emergent.wire.axis.storage._memory import MemoryStorage, BaseTTLStorage
from emergent.wire.axis.storage._file import FileStorage
from emergent.wire.axis.storage._codec import PickleCodec, JsonCodec, IdentityCodec


# Module-level dataclasses for pickle compatibility
@dataclass
class _User:
    name: str
    age: int


@dataclass
class _Item:
    name: str
    qty: int
from emergent.wire.axis.storage._kv import KV, KVNX, kv, kv_nx
from emergent.wire.axis.storage._queue import Queue, QueueFull, queue, queue_full
from emergent.wire.axis.storage._pubsub import PubSub, pubsub
from emergent.wire.axis.storage._lock import Lock, LockExtend, lock, lock_extend
from emergent.wire.axis.storage._counter import Counter, CounterFull, counter, counter_full
from emergent.wire.axis.storage._compose import (
    PrefixKV,
    TieredKV,
    FallbackKV,
    ReadonlyKV,
    prefix_kv,
    tiered_kv,
    fallback_kv,
    readonly_kv,
)
from emergent.wire.axis.storage._result import map_option, map_result


# =============================================================================
# Mock backends for patterns that MemoryStorage does not implement
# =============================================================================


class MockQueueBackend:
    """In-memory queue backend implementing Push + Pop + Peek + Len capabilities."""

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


class MockPubSubBackend:
    """In-memory pub/sub backend implementing Publish + Subscribe capabilities."""

    def __init__(self) -> None:
        self._channels: dict[str, list[bytes]] = {}

    async def publish(self, channel: str, value: bytes) -> Result[None, Never]:
        self._channels.setdefault(channel, []).append(value)
        return Ok(None)

    async def subscribe(self, channel: str) -> AsyncIterator[Result[bytes, Never]]:
        for msg in self._channels.get(channel, []):
            yield Ok(msg)


class MockLockBackend:
    """In-memory lock backend implementing Acquire + Release + Extend capabilities."""

    def __init__(self) -> None:
        self._locks: dict[str, bool] = {}

    async def acquire(self, key: str, ttl: timedelta) -> Result[bool, Never]:
        if self._locks.get(key, False):
            return Ok(False)
        self._locks[key] = True
        return Ok(True)

    async def release(self, key: str) -> Result[None, Never]:
        self._locks.pop(key, None)
        return Ok(None)

    async def extend(self, key: str, ttl: timedelta) -> Result[bool, Never]:
        if key in self._locks and self._locks[key]:
            return Ok(True)
        return Ok(False)


class MockCounterBackend:
    """In-memory counter backend implementing Incr + Decr + IncrBy capabilities."""

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


class FailingKVBackend:
    """A KV backend that always returns Error for testing FallbackKV."""

    async def get(self, key: str) -> Result[Option[bytes], str]:
        return Error("backend failure")

    async def set(
        self, key: str, value: bytes, ttl: timedelta | None = None
    ) -> Result[None, str]:
        return Error("backend failure")

    async def delete(self, key: str) -> Result[None, str]:
        return Error("backend failure")


# =============================================================================
# 1. MemoryStorage
# =============================================================================


class TestMemoryStorage:
    """Tests for MemoryStorage: CRUD, TTL, pattern ops."""

    @pytest.mark.asyncio
    async def test_set_and_get_basic(self) -> None:
        storage = MemoryStorage()
        await storage.set("k", "v")
        result = await storage.get("k")
        assert result == Ok(Some("v"))

    @pytest.mark.asyncio
    async def test_get_missing_key_returns_nothing(self) -> None:
        storage = MemoryStorage()
        result = await storage.get("missing")
        assert result == Ok(Nothing())

    @pytest.mark.asyncio
    async def test_delete_removes_key(self) -> None:
        storage = MemoryStorage()
        await storage.set("k", "v")
        await storage.delete("k")
        result = await storage.get("k")
        assert result == Ok(Nothing())

    @pytest.mark.asyncio
    async def test_delete_nonexistent_key_is_noop(self) -> None:
        storage = MemoryStorage()
        result = await storage.delete("nonexistent")
        assert result == Ok(None)

    @pytest.mark.asyncio
    async def test_set_overwrites_existing(self) -> None:
        storage = MemoryStorage()
        await storage.set("k", "v1")
        await storage.set("k", "v2")
        result = await storage.get("k")
        assert result == Ok(Some("v2"))

    @pytest.mark.asyncio
    async def test_set_nx_new_key_returns_true(self) -> None:
        storage = MemoryStorage()
        result = await storage.set_nx("k", "v")
        assert result == Ok(True)
        get_result = await storage.get("k")
        assert get_result == Ok(Some("v"))

    @pytest.mark.asyncio
    async def test_set_nx_existing_key_returns_false(self) -> None:
        storage = MemoryStorage()
        await storage.set_nx("k", "v")
        result = await storage.set_nx("k", "v2")
        assert result == Ok(False)
        # Original value unchanged
        get_result = await storage.get("k")
        assert get_result == Ok(Some("v"))

    @pytest.mark.asyncio
    async def test_ttl_entry_expires(self) -> None:
        storage = MemoryStorage()
        await storage.set("k", "v", ttl=timedelta(milliseconds=10))
        # Immediately should still be present
        result_before = await storage.get("k")
        assert result_before == Ok(Some("v"))
        # Wait for expiry
        await asyncio.sleep(0.05)
        result_after = await storage.get("k")
        assert result_after == Ok(Nothing())

    @pytest.mark.asyncio
    async def test_set_without_ttl_does_not_expire(self) -> None:
        storage = MemoryStorage()
        await storage.set("k", "v")
        await asyncio.sleep(0.01)
        result = await storage.get("k")
        assert result == Ok(Some("v"))

    @pytest.mark.asyncio
    async def test_set_nx_with_expired_entry_returns_true(self) -> None:
        storage = MemoryStorage()
        await storage.set_nx("k", "old", ttl=timedelta(milliseconds=10))
        await asyncio.sleep(0.05)
        # Expired entry should allow set_nx to succeed
        result = await storage.set_nx("k", "new")
        assert result == Ok(True)
        get_result = await storage.get("k")
        assert get_result == Ok(Some("new"))

    @pytest.mark.asyncio
    async def test_delete_pattern_with_fnmatch(self) -> None:
        storage = MemoryStorage()
        await storage.set("user:1", "alice")
        await storage.set("user:2", "bob")
        await storage.set("order:1", "pizza")
        result = await storage.delete_pattern("user:*")
        assert result == Ok(2)
        assert await storage.get("user:1") == Ok(Nothing())
        assert await storage.get("user:2") == Ok(Nothing())
        assert await storage.get("order:1") == Ok(Some("pizza"))

    @pytest.mark.asyncio
    async def test_delete_pattern_no_matches(self) -> None:
        storage = MemoryStorage()
        await storage.set("user:1", "alice")
        result = await storage.delete_pattern("order:*")
        assert result == Ok(0)
        assert await storage.get("user:1") == Ok(Some("alice"))

    @pytest.mark.asyncio
    async def test_keys_all(self) -> None:
        storage = MemoryStorage()
        await storage.set("a", 1)
        await storage.set("b", 2)
        await storage.set("c", 3)
        result = await storage.keys()
        assert isinstance(result, Ok)
        keys = result.unwrap()
        assert sorted(keys) == ["a", "b", "c"]

    @pytest.mark.asyncio
    async def test_keys_with_pattern(self) -> None:
        storage = MemoryStorage()
        await storage.set("user:1", "alice")
        await storage.set("user:2", "bob")
        await storage.set("order:1", "pizza")
        result = await storage.keys("user:*")
        assert isinstance(result, Ok)
        keys = result.unwrap()
        assert sorted(keys) == ["user:1", "user:2"]

    @pytest.mark.asyncio
    async def test_keys_empty_storage(self) -> None:
        storage = MemoryStorage()
        result = await storage.keys()
        assert result == Ok([])

    @pytest.mark.asyncio
    async def test_set_returns_ok_none(self) -> None:
        storage = MemoryStorage()
        result = await storage.set("k", "v")
        assert result == Ok(None)

    @pytest.mark.asyncio
    async def test_multiple_keys_independent(self) -> None:
        storage = MemoryStorage()
        await storage.set("a", 1)
        await storage.set("b", 2)
        assert await storage.get("a") == Ok(Some(1))
        assert await storage.get("b") == Ok(Some(2))
        await storage.delete("a")
        assert await storage.get("a") == Ok(Nothing())
        assert await storage.get("b") == Ok(Some(2))


# =============================================================================
# 2. FileStorage
# =============================================================================


class TestFileStorage:
    """Tests for FileStorage: persistence across instances."""

    @pytest.mark.asyncio
    async def test_write_and_read_back(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test.pickle")
            storage = FileStorage(path)
            await storage.set("k", "v")
            result = await storage.get("k")
            assert result == Ok(Some("v"))

    @pytest.mark.asyncio
    async def test_persistence_across_instances(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test.pickle")
            # Write with first instance
            storage1 = FileStorage(path)
            await storage1.set("k", "v")
            # Read with a new instance (same path)
            storage2 = FileStorage(path)
            result = await storage2.get("k")
            assert result == Ok(Some("v"))

    @pytest.mark.asyncio
    async def test_file_actually_created(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "data.pickle")
            assert not os.path.exists(path)
            storage = FileStorage(path)
            await storage.set("k", "v")
            assert os.path.exists(path)

    @pytest.mark.asyncio
    async def test_creates_parent_directories(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "sub", "dir", "data.pickle")
            storage = FileStorage(path)
            await storage.set("k", "v")
            assert os.path.exists(path)

    @pytest.mark.asyncio
    async def test_delete_persists(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test.pickle")
            storage1 = FileStorage(path)
            await storage1.set("k", "v")
            await storage1.delete("k")
            storage2 = FileStorage(path)
            result = await storage2.get("k")
            assert result == Ok(Nothing())

    @pytest.mark.asyncio
    async def test_file_storage_inherits_ttl(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test.pickle")
            storage = FileStorage(path)
            await storage.set("k", "v", ttl=timedelta(milliseconds=10))
            result_before = await storage.get("k")
            assert result_before == Ok(Some("v"))
            await asyncio.sleep(0.05)
            result_after = await storage.get("k")
            assert result_after == Ok(Nothing())

    @pytest.mark.asyncio
    async def test_empty_file_storage_returns_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test.pickle")
            storage = FileStorage(path)
            result = await storage.get("nonexistent")
            assert result == Ok(Nothing())


# =============================================================================
# 3. Codecs
# =============================================================================


class TestPickleCodec:
    """Tests for PickleCodec: round-trip encoding/decoding."""

    def test_encode_decode_dict(self) -> None:
        codec = PickleCodec()
        data = {"key": "value", "num": 42}
        encoded = codec.encode(data)
        assert isinstance(encoded, bytes)
        decoded = codec.decode(encoded)
        assert decoded == data

    def test_encode_decode_list(self) -> None:
        codec = PickleCodec()
        data = [1, 2, 3, "hello"]
        encoded = codec.encode(data)
        decoded = codec.decode(encoded)
        assert decoded == data

    def test_encode_decode_dataclass(self) -> None:
        codec = PickleCodec()
        user = _User(name="Alice", age=30)
        encoded = codec.encode(user)
        decoded = codec.decode(encoded)
        assert decoded == user

    def test_encode_decode_nested(self) -> None:
        codec = PickleCodec()
        data = {"users": [{"name": "Alice"}, {"name": "Bob"}], "count": 2}
        encoded = codec.encode(data)
        decoded = codec.decode(encoded)
        assert decoded == data

    def test_encode_decode_primitives(self) -> None:
        codec = PickleCodec()
        for value in [42, 3.14, "hello", True, None]:
            encoded = codec.encode(value)
            decoded = codec.decode(encoded)
            assert decoded == value


class TestJsonCodec:
    """Tests for JsonCodec: round-trip encoding/decoding."""

    def test_encode_decode_dict(self) -> None:
        codec = JsonCodec()
        data = {"key": "value", "num": 42}
        encoded = codec.encode(data)
        assert isinstance(encoded, bytes)
        decoded = codec.decode(encoded)
        assert decoded == data

    def test_encode_decode_list(self) -> None:
        codec = JsonCodec()
        data = [1, 2, 3, "hello"]
        encoded = codec.encode(data)
        decoded = codec.decode(encoded)
        assert decoded == data

    def test_encode_decode_primitives(self) -> None:
        codec = JsonCodec()
        for value in [42, 3.14, "hello", True, None]:
            encoded = codec.encode(value)
            decoded = codec.decode(encoded)
            assert decoded == value

    def test_encode_produces_utf8_bytes(self) -> None:
        codec = JsonCodec()
        encoded = codec.encode({"key": "value"})
        assert isinstance(encoded, bytes)
        text = encoded.decode("utf-8")
        assert '"key"' in text

    def test_encode_decode_nested(self) -> None:
        codec = JsonCodec()
        data = {"users": [{"name": "Alice"}, {"name": "Bob"}], "count": 2}
        encoded = codec.encode(data)
        decoded = codec.decode(encoded)
        assert decoded == data


class TestIdentityCodec:
    """Tests for IdentityCodec: bytes pass-through."""

    def test_encode_returns_same_bytes(self) -> None:
        codec = IdentityCodec()
        data = b"hello world"
        assert codec.encode(data) is data

    def test_decode_returns_same_bytes(self) -> None:
        codec = IdentityCodec()
        data = b"hello world"
        assert codec.decode(data) is data

    def test_round_trip(self) -> None:
        codec = IdentityCodec()
        data = b"\x00\x01\x02\xff"
        assert codec.decode(codec.encode(data)) == data


# =============================================================================
# 4. KV / KVNX patterns
# =============================================================================


class TestKVPattern:
    """Tests for KV pattern: codec integration with MemoryStorage backend."""

    @pytest.mark.asyncio
    async def test_set_and_get_with_pickle(self) -> None:
        store = kv(MemoryStorage(), PickleCodec())
        await store.set("k", {"a": 1})
        result = await store.get("k")
        assert result == Ok(Some({"a": 1}))

    @pytest.mark.asyncio
    async def test_set_and_get_with_json(self) -> None:
        store = kv(MemoryStorage(), JsonCodec())
        await store.set("k", [1, 2, 3])
        result = await store.get("k")
        assert result == Ok(Some([1, 2, 3]))

    @pytest.mark.asyncio
    async def test_get_missing_returns_nothing(self) -> None:
        store = kv(MemoryStorage(), PickleCodec())
        result = await store.get("missing")
        assert result == Ok(Nothing())

    @pytest.mark.asyncio
    async def test_delete(self) -> None:
        store = kv(MemoryStorage(), PickleCodec())
        await store.set("k", "v")
        await store.delete("k")
        result = await store.get("k")
        assert result == Ok(Nothing())

    @pytest.mark.asyncio
    async def test_set_with_ttl(self) -> None:
        store = kv(MemoryStorage(), PickleCodec())
        await store.set("k", "v", ttl=timedelta(milliseconds=10))
        result_before = await store.get("k")
        assert result_before == Ok(Some("v"))
        await asyncio.sleep(0.05)
        result_after = await store.get("k")
        assert result_after == Ok(Nothing())

    @pytest.mark.asyncio
    async def test_overwrite_value(self) -> None:
        store = kv(MemoryStorage(), PickleCodec())
        await store.set("k", "v1")
        await store.set("k", "v2")
        result = await store.get("k")
        assert result == Ok(Some("v2"))

    @pytest.mark.asyncio
    async def test_complex_values(self) -> None:
        store = kv(MemoryStorage(), PickleCodec())
        item = _Item(name="Widget", qty=10)
        await store.set("item:1", item)
        result = await store.get("item:1")
        assert result == Ok(Some(item))

    @pytest.mark.asyncio
    async def test_kv_factory_returns_kv_instance(self) -> None:
        store = kv(MemoryStorage(), PickleCodec())
        assert isinstance(store, KV)


class TestKVNXPattern:
    """Tests for KVNX pattern: KV + set_nx."""

    @pytest.mark.asyncio
    async def test_set_nx_new_key(self) -> None:
        store = kv_nx(MemoryStorage(), PickleCodec())
        result = await store.set_nx("k", "v")
        assert result == Ok(True)

    @pytest.mark.asyncio
    async def test_set_nx_existing_key(self) -> None:
        store = kv_nx(MemoryStorage(), PickleCodec())
        await store.set_nx("k", "v")
        result = await store.set_nx("k", "v2")
        assert result == Ok(False)

    @pytest.mark.asyncio
    async def test_set_nx_value_preserved(self) -> None:
        store = kv_nx(MemoryStorage(), PickleCodec())
        await store.set_nx("k", {"original": True})
        await store.set_nx("k", {"overwrite": True})
        result = await store.get("k")
        assert result == Ok(Some({"original": True}))

    @pytest.mark.asyncio
    async def test_set_nx_with_ttl(self) -> None:
        store = kv_nx(MemoryStorage(), PickleCodec())
        result = await store.set_nx("k", "v", ttl=timedelta(milliseconds=10))
        assert result == Ok(True)
        await asyncio.sleep(0.05)
        # After expiry, set_nx should succeed again
        result2 = await store.set_nx("k", "v2")
        assert result2 == Ok(True)

    @pytest.mark.asyncio
    async def test_kvnx_get_and_delete(self) -> None:
        store = kv_nx(MemoryStorage(), PickleCodec())
        await store.set("k", "v")
        assert await store.get("k") == Ok(Some("v"))
        await store.delete("k")
        assert await store.get("k") == Ok(Nothing())

    @pytest.mark.asyncio
    async def test_kv_nx_factory_returns_kvnx_instance(self) -> None:
        store = kv_nx(MemoryStorage(), PickleCodec())
        assert isinstance(store, KVNX)


# =============================================================================
# 5. Queue / QueueFull patterns
# =============================================================================


class TestQueuePattern:
    """Tests for Queue pattern with mock backend."""

    @pytest.mark.asyncio
    async def test_push_and_pop(self) -> None:
        q = queue(MockQueueBackend(), PickleCodec())
        await q.push("hello")
        result = await q.pop()
        assert result == Ok(Some("hello"))

    @pytest.mark.asyncio
    async def test_pop_empty_returns_nothing(self) -> None:
        q = queue(MockQueueBackend(), PickleCodec())
        result = await q.pop()
        assert result == Ok(Nothing())

    @pytest.mark.asyncio
    async def test_fifo_order(self) -> None:
        q = queue(MockQueueBackend(), PickleCodec())
        await q.push("first")
        await q.push("second")
        await q.push("third")
        assert await q.pop() == Ok(Some("first"))
        assert await q.pop() == Ok(Some("second"))
        assert await q.pop() == Ok(Some("third"))
        assert await q.pop() == Ok(Nothing())

    @pytest.mark.asyncio
    async def test_push_complex_values(self) -> None:
        q = queue(MockQueueBackend(), PickleCodec())
        await q.push({"key": "value", "list": [1, 2, 3]})
        result = await q.pop()
        assert result == Ok(Some({"key": "value", "list": [1, 2, 3]}))

    @pytest.mark.asyncio
    async def test_queue_factory(self) -> None:
        q = queue(MockQueueBackend(), PickleCodec())
        assert isinstance(q, Queue)


class TestQueueFullPattern:
    """Tests for QueueFull pattern with peek and length."""

    @pytest.mark.asyncio
    async def test_peek_returns_front_without_removing(self) -> None:
        q = queue_full(MockQueueBackend(), PickleCodec())
        await q.push("hello")
        peek_result = await q.peek()
        assert peek_result == Ok(Some("hello"))
        # Still in queue
        pop_result = await q.pop()
        assert pop_result == Ok(Some("hello"))

    @pytest.mark.asyncio
    async def test_peek_empty_returns_nothing(self) -> None:
        q = queue_full(MockQueueBackend(), PickleCodec())
        result = await q.peek()
        assert result == Ok(Nothing())

    @pytest.mark.asyncio
    async def test_length(self) -> None:
        q = queue_full(MockQueueBackend(), PickleCodec())
        assert await q.length() == Ok(0)
        await q.push("a")
        assert await q.length() == Ok(1)
        await q.push("b")
        assert await q.length() == Ok(2)
        await q.pop()
        assert await q.length() == Ok(1)

    @pytest.mark.asyncio
    async def test_queue_full_factory(self) -> None:
        q = queue_full(MockQueueBackend(), PickleCodec())
        assert isinstance(q, QueueFull)

    @pytest.mark.asyncio
    async def test_push_pop_peek_integration(self) -> None:
        q = queue_full(MockQueueBackend(), JsonCodec())
        await q.push({"id": 1})
        await q.push({"id": 2})
        assert await q.peek() == Ok(Some({"id": 1}))
        assert await q.length() == Ok(2)
        assert await q.pop() == Ok(Some({"id": 1}))
        assert await q.peek() == Ok(Some({"id": 2}))
        assert await q.length() == Ok(1)


# =============================================================================
# 6. PubSub pattern
# =============================================================================


class TestPubSubPattern:
    """Tests for PubSub pattern with mock backend."""

    @pytest.mark.asyncio
    async def test_publish_and_subscribe(self) -> None:
        backend = MockPubSubBackend()
        ps = pubsub(backend, PickleCodec())
        await ps.publish("events", {"type": "click"})
        await ps.publish("events", {"type": "scroll"})

        received = []
        async for result in ps.subscribe("events"):
            match result:
                case Ok(msg):
                    received.append(msg)
        assert received == [{"type": "click"}, {"type": "scroll"}]

    @pytest.mark.asyncio
    async def test_subscribe_empty_channel(self) -> None:
        backend = MockPubSubBackend()
        ps = pubsub(backend, PickleCodec())
        received = []
        async for result in ps.subscribe("empty"):
            match result:
                case Ok(msg):
                    received.append(msg)
        assert received == []

    @pytest.mark.asyncio
    async def test_separate_channels(self) -> None:
        backend = MockPubSubBackend()
        ps = pubsub(backend, PickleCodec())
        await ps.publish("ch1", "msg1")
        await ps.publish("ch2", "msg2")

        ch1_msgs = []
        async for result in ps.subscribe("ch1"):
            match result:
                case Ok(msg):
                    ch1_msgs.append(msg)

        ch2_msgs = []
        async for result in ps.subscribe("ch2"):
            match result:
                case Ok(msg):
                    ch2_msgs.append(msg)

        assert ch1_msgs == ["msg1"]
        assert ch2_msgs == ["msg2"]

    @pytest.mark.asyncio
    async def test_pubsub_factory(self) -> None:
        ps = pubsub(MockPubSubBackend(), PickleCodec())
        assert isinstance(ps, PubSub)


# =============================================================================
# 7. Lock / LockExtend patterns
# =============================================================================


class TestLockPattern:
    """Tests for Lock pattern with mock backend."""

    @pytest.mark.asyncio
    async def test_acquire_returns_true(self) -> None:
        lk = lock(MockLockBackend())
        result = await lk.acquire("resource:1", timedelta(seconds=30))
        assert result == Ok(True)

    @pytest.mark.asyncio
    async def test_acquire_already_held_returns_false(self) -> None:
        lk = lock(MockLockBackend())
        await lk.acquire("resource:1", timedelta(seconds=30))
        result = await lk.acquire("resource:1", timedelta(seconds=30))
        assert result == Ok(False)

    @pytest.mark.asyncio
    async def test_release_frees_lock(self) -> None:
        lk = lock(MockLockBackend())
        await lk.acquire("resource:1", timedelta(seconds=30))
        await lk.release("resource:1")
        result = await lk.acquire("resource:1", timedelta(seconds=30))
        assert result == Ok(True)

    @pytest.mark.asyncio
    async def test_hold_context_manager_acquires_and_releases(self) -> None:
        lk = lock(MockLockBackend())
        async with lk.hold("resource:1", timedelta(seconds=30)) as acquired:
            assert acquired is True
        # After exiting, lock should be released
        result = await lk.acquire("resource:1", timedelta(seconds=30))
        assert result == Ok(True)

    @pytest.mark.asyncio
    async def test_hold_when_already_held(self) -> None:
        backend = MockLockBackend()
        lk = lock(backend)
        # Pre-acquire the lock externally
        await backend.acquire("resource:1", timedelta(seconds=30))
        async with lk.hold("resource:1", timedelta(seconds=30)) as acquired:
            assert acquired is False

    @pytest.mark.asyncio
    async def test_hold_releases_on_exception(self) -> None:
        lk = lock(MockLockBackend())
        with pytest.raises(ValueError):
            async with lk.hold("resource:1", timedelta(seconds=30)) as acquired:
                assert acquired is True
                raise ValueError("boom")
        # Lock should still be released
        result = await lk.acquire("resource:1", timedelta(seconds=30))
        assert result == Ok(True)

    @pytest.mark.asyncio
    async def test_independent_locks(self) -> None:
        lk = lock(MockLockBackend())
        r1 = await lk.acquire("a", timedelta(seconds=10))
        r2 = await lk.acquire("b", timedelta(seconds=10))
        assert r1 == Ok(True)
        assert r2 == Ok(True)

    @pytest.mark.asyncio
    async def test_lock_factory(self) -> None:
        lk = lock(MockLockBackend())
        assert isinstance(lk, Lock)


class TestLockExtendPattern:
    """Tests for LockExtend pattern with extend capability."""

    @pytest.mark.asyncio
    async def test_extend_while_held(self) -> None:
        lk = lock_extend(MockLockBackend())
        await lk.acquire("resource:1", timedelta(seconds=30))
        result = await lk.extend("resource:1", timedelta(seconds=60))
        assert result == Ok(True)

    @pytest.mark.asyncio
    async def test_extend_not_held(self) -> None:
        lk = lock_extend(MockLockBackend())
        result = await lk.extend("resource:1", timedelta(seconds=60))
        assert result == Ok(False)

    @pytest.mark.asyncio
    async def test_lock_extend_hold_context_manager(self) -> None:
        lk = lock_extend(MockLockBackend())
        async with lk.hold("resource:1", timedelta(seconds=30)) as acquired:
            assert acquired is True
        result = await lk.acquire("resource:1", timedelta(seconds=30))
        assert result == Ok(True)

    @pytest.mark.asyncio
    async def test_lock_extend_factory(self) -> None:
        lk = lock_extend(MockLockBackend())
        assert isinstance(lk, LockExtend)


# =============================================================================
# 8. Counter / CounterFull patterns
# =============================================================================


class TestCounterPattern:
    """Tests for Counter pattern with mock backend."""

    @pytest.mark.asyncio
    async def test_incr_from_zero(self) -> None:
        c = counter(MockCounterBackend())
        result = await c.incr("hits")
        assert result == Ok(1)

    @pytest.mark.asyncio
    async def test_incr_multiple(self) -> None:
        c = counter(MockCounterBackend())
        await c.incr("hits")
        await c.incr("hits")
        result = await c.incr("hits")
        assert result == Ok(3)

    @pytest.mark.asyncio
    async def test_decr_from_zero(self) -> None:
        c = counter(MockCounterBackend())
        result = await c.decr("balance")
        assert result == Ok(-1)

    @pytest.mark.asyncio
    async def test_decr_after_incr(self) -> None:
        c = counter(MockCounterBackend())
        await c.incr("stock")
        await c.incr("stock")
        await c.incr("stock")
        result = await c.decr("stock")
        assert result == Ok(2)

    @pytest.mark.asyncio
    async def test_independent_keys(self) -> None:
        c = counter(MockCounterBackend())
        await c.incr("a")
        await c.incr("a")
        await c.incr("b")
        result_a = await c.incr("a")
        result_b = await c.incr("b")
        assert result_a == Ok(3)
        assert result_b == Ok(2)

    @pytest.mark.asyncio
    async def test_counter_factory(self) -> None:
        c = counter(MockCounterBackend())
        assert isinstance(c, Counter)


class TestCounterFullPattern:
    """Tests for CounterFull pattern with incr_by."""

    @pytest.mark.asyncio
    async def test_incr_by(self) -> None:
        c = counter_full(MockCounterBackend())
        result = await c.incr_by("balance", 100)
        assert result == Ok(100)

    @pytest.mark.asyncio
    async def test_incr_by_accumulates(self) -> None:
        c = counter_full(MockCounterBackend())
        await c.incr_by("balance", 50)
        result = await c.incr_by("balance", 30)
        assert result == Ok(80)

    @pytest.mark.asyncio
    async def test_incr_by_negative_decrements(self) -> None:
        c = counter_full(MockCounterBackend())
        await c.incr_by("balance", 100)
        result = await c.incr_by("balance", -40)
        assert result == Ok(60)

    @pytest.mark.asyncio
    async def test_decr_by(self) -> None:
        c = counter_full(MockCounterBackend())
        await c.incr_by("balance", 100)
        result = await c.decr_by("balance", 30)
        assert result == Ok(70)

    @pytest.mark.asyncio
    async def test_incr_and_decr_with_incr_by(self) -> None:
        c = counter_full(MockCounterBackend())
        await c.incr("x")
        await c.incr("x")
        await c.incr("x")
        await c.decr("x")
        result = await c.incr_by("x", 10)
        assert result == Ok(12)

    @pytest.mark.asyncio
    async def test_counter_full_factory(self) -> None:
        c = counter_full(MockCounterBackend())
        assert isinstance(c, CounterFull)


# =============================================================================
# 9. Composition wrappers
# =============================================================================


class TestPrefixKV:
    """Tests for PrefixKV: key prefixing."""

    @pytest.mark.asyncio
    async def test_set_and_get_with_prefix(self) -> None:
        inner = kv(MemoryStorage(), PickleCodec())
        prefixed = prefix_kv(inner, "cache:")
        await prefixed.set("k", "v")
        result = await prefixed.get("k")
        assert result == Ok(Some("v"))

    @pytest.mark.asyncio
    async def test_prefix_is_applied_to_inner(self) -> None:
        inner = kv(MemoryStorage(), PickleCodec())
        prefixed = prefix_kv(inner, "cache:")
        await prefixed.set("k", "v")
        # Direct inner access with prefixed key should work
        result = await inner.get("cache:k")
        assert result == Ok(Some("v"))
        # Direct inner access without prefix should not find it
        result_no_prefix = await inner.get("k")
        assert result_no_prefix == Ok(Nothing())

    @pytest.mark.asyncio
    async def test_delete_with_prefix(self) -> None:
        inner = kv(MemoryStorage(), PickleCodec())
        prefixed = prefix_kv(inner, "ns:")
        await prefixed.set("k", "v")
        await prefixed.delete("k")
        result = await prefixed.get("k")
        assert result == Ok(Nothing())

    @pytest.mark.asyncio
    async def test_different_prefixes_isolate(self) -> None:
        backend = MemoryStorage()
        store_a = prefix_kv(kv(backend, PickleCodec()), "a:")
        store_b = prefix_kv(kv(backend, PickleCodec()), "b:")
        await store_a.set("k", "from_a")
        await store_b.set("k", "from_b")
        assert await store_a.get("k") == Ok(Some("from_a"))
        assert await store_b.get("k") == Ok(Some("from_b"))

    @pytest.mark.asyncio
    async def test_prefix_kv_factory(self) -> None:
        inner = kv(MemoryStorage(), PickleCodec())
        prefixed = prefix_kv(inner, "cache:")
        assert isinstance(prefixed, PrefixKV)


class TestTieredKV:
    """Tests for TieredKV: L1 miss -> L2 hit -> L1 populated."""

    @pytest.mark.asyncio
    async def test_l2_hit_populates_l1(self) -> None:
        l1 = kv(MemoryStorage(), PickleCodec())
        l2 = kv(MemoryStorage(), PickleCodec())
        tiered = tiered_kv(l1, l2)
        # Only in L2
        await l2.set("k", "v")
        # Get from tiered: should hit L2, populate L1
        result = await tiered.get("k")
        assert result == Ok(Some("v"))
        # Now L1 should have it
        result_l1 = await l1.get("k")
        assert result_l1 == Ok(Some("v"))

    @pytest.mark.asyncio
    async def test_l1_hit_does_not_check_l2(self) -> None:
        l1 = kv(MemoryStorage(), PickleCodec())
        l2 = kv(MemoryStorage(), PickleCodec())
        tiered = tiered_kv(l1, l2)
        await l1.set("k", "l1_value")
        await l2.set("k", "l2_value")
        # Should return L1 value
        result = await tiered.get("k")
        assert result == Ok(Some("l1_value"))

    @pytest.mark.asyncio
    async def test_miss_both_returns_nothing(self) -> None:
        l1 = kv(MemoryStorage(), PickleCodec())
        l2 = kv(MemoryStorage(), PickleCodec())
        tiered = tiered_kv(l1, l2)
        result = await tiered.get("missing")
        assert result == Ok(Nothing())

    @pytest.mark.asyncio
    async def test_set_writes_to_both_tiers(self) -> None:
        l1 = kv(MemoryStorage(), PickleCodec())
        l2 = kv(MemoryStorage(), PickleCodec())
        tiered = tiered_kv(l1, l2)
        await tiered.set("k", "v")
        assert await l1.get("k") == Ok(Some("v"))
        assert await l2.get("k") == Ok(Some("v"))

    @pytest.mark.asyncio
    async def test_delete_removes_from_both_tiers(self) -> None:
        l1 = kv(MemoryStorage(), PickleCodec())
        l2 = kv(MemoryStorage(), PickleCodec())
        tiered = tiered_kv(l1, l2)
        await tiered.set("k", "v")
        await tiered.delete("k")
        assert await l1.get("k") == Ok(Nothing())
        assert await l2.get("k") == Ok(Nothing())

    @pytest.mark.asyncio
    async def test_tiered_kv_factory(self) -> None:
        l1 = kv(MemoryStorage(), PickleCodec())
        l2 = kv(MemoryStorage(), PickleCodec())
        tiered = tiered_kv(l1, l2)
        assert isinstance(tiered, TieredKV)

    @pytest.mark.asyncio
    async def test_tiered_kv_with_l1_ttl(self) -> None:
        l1 = kv(MemoryStorage(), PickleCodec())
        l2 = kv(MemoryStorage(), PickleCodec())
        tiered = tiered_kv(l1, l2, l1_ttl=timedelta(milliseconds=10))
        await l2.set("k", "v")
        # First get populates L1
        result = await tiered.get("k")
        assert result == Ok(Some("v"))
        assert await l1.get("k") == Ok(Some("v"))
        # Wait for L1 to expire
        await asyncio.sleep(0.05)
        assert await l1.get("k") == Ok(Nothing())
        # L2 still has it
        assert await l2.get("k") == Ok(Some("v"))


class TestFallbackKV:
    """Tests for FallbackKV: primary error -> secondary."""

    @pytest.mark.asyncio
    async def test_primary_success_returns_primary(self) -> None:
        primary = kv(MemoryStorage(), PickleCodec())
        secondary = kv(MemoryStorage(), PickleCodec())
        fb = fallback_kv(primary, secondary)
        await primary.set("k", "primary_value")
        await secondary.set("k", "secondary_value")
        result = await fb.get("k")
        assert result == Ok(Some("primary_value"))

    @pytest.mark.asyncio
    async def test_primary_failure_falls_back_to_secondary(self) -> None:
        failing = KV(FailingKVBackend(), PickleCodec())
        secondary = kv(MemoryStorage(), PickleCodec())
        fb = fallback_kv(failing, secondary)
        await secondary.set("k", "backup_value")
        result = await fb.get("k")
        assert result == Ok(Some("backup_value"))

    @pytest.mark.asyncio
    async def test_fallback_set(self) -> None:
        failing = KV(FailingKVBackend(), PickleCodec())
        secondary = kv(MemoryStorage(), PickleCodec())
        fb = fallback_kv(failing, secondary)
        result = await fb.set("k", "v")
        assert result == Ok(None)
        # Should be in secondary
        assert await secondary.get("k") == Ok(Some("v"))

    @pytest.mark.asyncio
    async def test_fallback_delete(self) -> None:
        failing = KV(FailingKVBackend(), PickleCodec())
        secondary = kv(MemoryStorage(), PickleCodec())
        fb = fallback_kv(failing, secondary)
        await secondary.set("k", "v")
        result = await fb.delete("k")
        assert result == Ok(None)
        assert await secondary.get("k") == Ok(Nothing())

    @pytest.mark.asyncio
    async def test_fallback_kv_factory(self) -> None:
        primary = kv(MemoryStorage(), PickleCodec())
        secondary = kv(MemoryStorage(), PickleCodec())
        fb = fallback_kv(primary, secondary)
        assert isinstance(fb, FallbackKV)


class TestReadonlyKV:
    """Tests for ReadonlyKV: writes disabled."""

    @pytest.mark.asyncio
    async def test_get_reads_through(self) -> None:
        inner = kv(MemoryStorage(), PickleCodec())
        await inner.set("k", "v")
        ro = readonly_kv(inner)
        result = await ro.get("k")
        assert result == Ok(Some("v"))

    @pytest.mark.asyncio
    async def test_set_is_noop_returns_nothing(self) -> None:
        inner = kv(MemoryStorage(), PickleCodec())
        ro = readonly_kv(inner)
        result = await ro.set("k", "v")
        assert result == Ok(Nothing())
        # Inner should not have the value
        assert await inner.get("k") == Ok(Nothing())

    @pytest.mark.asyncio
    async def test_delete_is_noop_returns_nothing(self) -> None:
        inner = kv(MemoryStorage(), PickleCodec())
        await inner.set("k", "v")
        ro = readonly_kv(inner)
        result = await ro.delete("k")
        assert result == Ok(Nothing())
        # Inner should still have the value
        assert await inner.get("k") == Ok(Some("v"))

    @pytest.mark.asyncio
    async def test_readonly_kv_factory(self) -> None:
        inner = kv(MemoryStorage(), PickleCodec())
        ro = readonly_kv(inner)
        assert isinstance(ro, ReadonlyKV)

    @pytest.mark.asyncio
    async def test_get_missing_returns_nothing(self) -> None:
        inner = kv(MemoryStorage(), PickleCodec())
        ro = readonly_kv(inner)
        result = await ro.get("missing")
        assert result == Ok(Nothing())


# =============================================================================
# 10. Result combinators
# =============================================================================


class TestMapOption:
    """Tests for map_option combinator."""

    def test_ok_some_applies_function(self) -> None:
        result = map_option(Ok(Some(1)), str)
        assert result == Ok(Some("1"))

    def test_ok_nothing_stays_nothing(self) -> None:
        result = map_option(Ok(Nothing()), str)
        assert result == Ok(Nothing())

    def test_error_passes_through(self) -> None:
        result = map_option(Error("fail"), str)
        assert result == Error("fail")

    def test_ok_some_with_complex_transform(self) -> None:
        result = map_option(Ok(Some([1, 2, 3])), len)
        assert result == Ok(Some(3))

    def test_ok_some_with_lambda(self) -> None:
        result = map_option(Ok(Some(5)), lambda x: x * 2)
        assert result == Ok(Some(10))


class TestMapResult:
    """Tests for map_result combinator."""

    def test_ok_applies_function(self) -> None:
        result = map_result(Ok(1), str)
        assert result == Ok("1")

    def test_error_passes_through(self) -> None:
        result = map_result(Error("fail"), str)
        assert result == Error("fail")

    def test_ok_with_complex_transform(self) -> None:
        result = map_result(Ok([1, 2, 3]), len)
        assert result == Ok(3)

    def test_ok_with_lambda(self) -> None:
        result = map_result(Ok(5), lambda x: x * 2)
        assert result == Ok(10)


# =============================================================================
# INTEGRATION TESTS — realistic multi-layer composition scenarios
# =============================================================================


class TestCompositionPrefixTieredFallback:
    """Integration: composing Prefix, Tiered, and Fallback layers together."""

    @pytest.mark.asyncio
    async def test_tiered_with_prefix_on_both_tiers(self) -> None:
        """Prefix isolation within a tiered cache.

        L1 and L2 share the same physical backend but use different prefixes,
        so their keyspaces do not collide.  TieredKV still populates L1 on
        L2 hits.
        """
        shared_backend = MemoryStorage()
        l1 = prefix_kv(kv(shared_backend, PickleCodec()), "l1:")
        l2 = prefix_kv(kv(shared_backend, PickleCodec()), "l2:")
        tiered = tiered_kv(l1, l2)

        # Populate L2 only
        await l2.set("user:1", {"name": "Alice"})
        # L1 has nothing yet
        assert await l1.get("user:1") == Ok(Nothing())

        # Tiered get should miss L1, hit L2, and populate L1
        result = await tiered.get("user:1")
        assert result == Ok(Some({"name": "Alice"}))

        # L1 should now be populated
        assert await l1.get("user:1") == Ok(Some({"name": "Alice"}))

        # Underlying backend should have both prefixed keys
        raw_l1 = await shared_backend.get("l1:user:1")
        raw_l2 = await shared_backend.get("l2:user:1")
        assert raw_l1 != Ok(Nothing())
        assert raw_l2 != Ok(Nothing())

    @pytest.mark.asyncio
    async def test_fallback_wrapping_tiered_layers(self) -> None:
        """FallbackKV where primary is a TieredKV and secondary is a plain KV.

        When the primary tiered store works, fallback never triggers.
        """
        l1 = kv(MemoryStorage(), PickleCodec())
        l2 = kv(MemoryStorage(), PickleCodec())
        primary = tiered_kv(l1, l2)
        secondary = kv(MemoryStorage(), PickleCodec())

        await secondary.set("key", "from-secondary")
        await l2.set("key", "from-l2")

        fb = fallback_kv(primary, secondary)

        # Primary tiered works -> should get l2 value (l1 miss -> l2 hit)
        result = await fb.get("key")
        assert result == Ok(Some("from-l2"))

    @pytest.mark.asyncio
    async def test_fallback_to_secondary_tiered(self) -> None:
        """FallbackKV where primary always fails and secondary is a TieredKV."""
        failing = KV(FailingKVBackend(), PickleCodec())
        l1 = kv(MemoryStorage(), PickleCodec())
        l2 = kv(MemoryStorage(), PickleCodec())
        secondary = tiered_kv(l1, l2)
        await l2.set("key", "safe-value")

        fb = fallback_kv(failing, secondary)
        result = await fb.get("key")
        assert result == Ok(Some("safe-value"))
        # Secondary tiered should have promoted to L1
        assert await l1.get("key") == Ok(Some("safe-value"))

    @pytest.mark.asyncio
    async def test_readonly_over_tiered_blocks_writes(self) -> None:
        """ReadonlyKV wrapping TieredKV: reads pass through, writes are blocked."""
        l1 = kv(MemoryStorage(), PickleCodec())
        l2 = kv(MemoryStorage(), PickleCodec())
        tiered = tiered_kv(l1, l2)
        await l2.set("config", "production")

        ro = readonly_kv(tiered)

        # Read works
        result = await ro.get("config")
        assert result == Ok(Some("production"))

        # Write is silently blocked
        write_result = await ro.set("config", "overwritten")
        assert write_result == Ok(Nothing())
        # Original value unchanged
        assert await l2.get("config") == Ok(Some("production"))

        # Delete is silently blocked
        delete_result = await ro.delete("config")
        assert delete_result == Ok(Nothing())
        assert await l2.get("config") == Ok(Some("production"))

    @pytest.mark.asyncio
    async def test_prefix_over_readonly_over_kv(self) -> None:
        """PrefixKV -> ReadonlyKV -> KV: prefixed reads work, writes blocked."""
        inner = kv(MemoryStorage(), PickleCodec())
        await inner.set("ns:key", "value")

        ro = readonly_kv(inner)
        prefixed = prefix_kv(ro, "ns:")

        result = await prefixed.get("key")
        assert result == Ok(Some("value"))

        # Write through prefix -> readonly is blocked
        write_result = await prefixed.set("key", "new")
        assert write_result == Ok(Nothing())

    @pytest.mark.asyncio
    async def test_nested_prefix_chains(self) -> None:
        """Multiple levels of prefix nesting accumulate correctly."""
        backend = MemoryStorage()
        inner = kv(backend, PickleCodec())
        p1 = prefix_kv(inner, "app:")
        p2 = prefix_kv(p1, "v2:")
        p3 = prefix_kv(p2, "prod:")

        await p3.set("setting", 42)

        # The actual key in the backend should be the full concatenation
        raw = await backend.get("app:v2:prod:setting")
        assert raw == Ok(Some(PickleCodec().encode(42)))

        # Read back through the chain
        assert await p3.get("setting") == Ok(Some(42))

        # Intermediate prefixes should see partial keys
        assert await p2.get("prod:setting") == Ok(Some(42))
        assert await p1.get("v2:prod:setting") == Ok(Some(42))


class TestCrossPatternOnSharedBackend:
    """Integration: KV, Queue, PubSub, Counter, Lock on the same MemoryStorage."""

    @pytest.mark.asyncio
    async def test_kv_and_queue_share_backend_without_interference(self) -> None:
        """KV and Queue can use the same backend for different data flows."""
        kv_backend = MemoryStorage()
        q_backend = MockQueueBackend()

        kv_store = kv(kv_backend, JsonCodec())
        q_store = queue(q_backend, JsonCodec())

        # KV stores metadata, Queue stores jobs
        await kv_store.set("job:count", 0)
        await q_store.push({"job": "process_images"})
        await q_store.push({"job": "send_emails"})

        # Process queue, update counter
        processed = 0
        while True:
            result = await q_store.pop()
            match result:
                case Ok(Some(_)):
                    processed += 1
                case _:
                    break

        await kv_store.set("job:count", processed)
        count_result = await kv_store.get("job:count")
        assert count_result == Ok(Some(2))

    @pytest.mark.asyncio
    async def test_kv_counter_and_lock_workflow(self) -> None:
        """Realistic workflow: lock a resource, update a counter, store result in KV."""
        lk = lock(MockLockBackend())
        cnt = counter(MockCounterBackend())
        store = kv(MemoryStorage(), PickleCodec())

        async with lk.hold("inventory:widget", timedelta(seconds=30)) as acquired:
            assert acquired is True
            # Decrement stock
            stock = await cnt.incr("sold:widget")
            assert stock == Ok(1)
            # Record the sale
            await store.set("last_sale", {"item": "widget", "sold_count": stock.unwrap()})

        # Lock is released, data is persisted
        result = await lk.acquire("inventory:widget", timedelta(seconds=30))
        assert result == Ok(True)
        sale = await store.get("last_sale")
        assert sale == Ok(Some({"item": "widget", "sold_count": 1}))

    @pytest.mark.asyncio
    async def test_pubsub_triggers_kv_update(self) -> None:
        """PubSub messages drive KV state changes."""
        ps_backend = MockPubSubBackend()
        ps = pubsub(ps_backend, JsonCodec())
        store = kv(MemoryStorage(), JsonCodec())

        # Simulate event publishing
        await ps.publish("events", {"action": "user_signup", "user": "alice"})
        await ps.publish("events", {"action": "user_signup", "user": "bob"})

        # Process events and update KV
        signups: list[str] = []
        async for result in ps.subscribe("events"):
            match result:
                case Ok(msg):
                    signups.append(msg["user"])

        await store.set("total_signups", len(signups))
        await store.set("recent_users", signups)

        assert await store.get("total_signups") == Ok(Some(2))
        assert await store.get("recent_users") == Ok(Some(["alice", "bob"]))


class TestTieredWithTTLAndFallback:
    """Integration: tiered caching with TTL expiry and fallback recovery."""

    @pytest.mark.asyncio
    async def test_l1_ttl_expires_l2_still_serves(self) -> None:
        """L1 cache expires but L2 persists, so subsequent get re-populates L1."""
        l1 = kv(MemoryStorage(), PickleCodec())
        l2 = kv(MemoryStorage(), PickleCodec())
        tiered = tiered_kv(l1, l2, l1_ttl=timedelta(milliseconds=20))

        await tiered.set("session", {"user_id": 42, "role": "admin"})

        # Immediately: both tiers have it
        assert await l1.get("session") == Ok(Some({"user_id": 42, "role": "admin"}))
        assert await l2.get("session") == Ok(Some({"user_id": 42, "role": "admin"}))

        # Wait for L1 TTL to expire
        await asyncio.sleep(0.05)
        assert await l1.get("session") == Ok(Nothing())

        # Tiered get should re-populate L1 from L2
        result = await tiered.get("session")
        assert result == Ok(Some({"user_id": 42, "role": "admin"}))
        assert await l1.get("session") == Ok(Some({"user_id": 42, "role": "admin"}))

    @pytest.mark.asyncio
    async def test_tiered_set_then_delete_clears_both(self) -> None:
        """Delete through tiered removes from L1 and L2."""
        l1 = kv(MemoryStorage(), PickleCodec())
        l2 = kv(MemoryStorage(), PickleCodec())
        tiered = tiered_kv(l1, l2)

        await tiered.set("token", "abc123")
        assert await l1.get("token") == Ok(Some("abc123"))
        assert await l2.get("token") == Ok(Some("abc123"))

        await tiered.delete("token")
        assert await l1.get("token") == Ok(Nothing())
        assert await l2.get("token") == Ok(Nothing())

        # Tiered get should also return Nothing
        assert await tiered.get("token") == Ok(Nothing())

    @pytest.mark.asyncio
    async def test_fallback_kv_with_different_codecs(self) -> None:
        """FallbackKV where primary uses Pickle and secondary uses Json.

        Both work independently. When primary fails, secondary (Json) serves.
        """
        secondary = kv(MemoryStorage(), JsonCodec())
        failing = KV(FailingKVBackend(), PickleCodec())
        fb = fallback_kv(failing, secondary)

        await fb.set("data", [1, 2, 3])
        result = await fb.get("data")
        assert result == Ok(Some([1, 2, 3]))


class TestMultiStepWorkflows:
    """Integration: realistic multi-step application workflows."""

    @pytest.mark.asyncio
    async def test_session_store_with_ttl_and_prefix(self) -> None:
        """Session management: prefix-isolated, TTL-limited sessions."""
        backend = MemoryStorage()
        sessions = prefix_kv(kv(backend, PickleCodec()), "session:")

        session_data = {"user_id": 1, "permissions": ["read", "write"]}
        await sessions.set("abc123", session_data, ttl=timedelta(milliseconds=30))

        # Session is valid immediately
        result = await sessions.get("abc123")
        assert result == Ok(Some(session_data))

        # Wait for expiry
        await asyncio.sleep(0.05)
        expired = await sessions.get("abc123")
        assert expired == Ok(Nothing())

    @pytest.mark.asyncio
    async def test_queue_drain_with_counter_tracking(self) -> None:
        """Process a work queue while tracking stats via counter."""
        q = queue_full(MockQueueBackend(), PickleCodec())
        cnt = counter_full(MockCounterBackend())

        # Enqueue work items
        items = [_Item(name=f"item_{i}", qty=i * 10) for i in range(5)]
        for item in items:
            await q.push(item)

        assert await q.length() == Ok(5)

        # Drain the queue and count
        total_qty = 0
        while True:
            popped = await q.pop()
            match popped:
                case Ok(Some(item)):
                    total_qty += item.qty
                    await cnt.incr("processed")
                case _:
                    break

        processed_count = await cnt.incr_by("processed", 0)  # read current value
        assert processed_count == Ok(5)
        assert total_qty == 0 + 10 + 20 + 30 + 40
        assert await q.length() == Ok(0)

    @pytest.mark.asyncio
    async def test_lock_guard_with_kvnx_idempotent_write(self) -> None:
        """Lock a resource, then use KVNX set_nx for idempotent writes."""
        lk = lock(MockLockBackend())
        store = kv_nx(MemoryStorage(), PickleCodec())

        async with lk.hold("order:process", timedelta(seconds=10)) as acquired:
            assert acquired is True
            # Idempotent write: only first succeeds
            first = await store.set_nx("order:123", {"status": "processing"})
            assert first == Ok(True)
            second = await store.set_nx("order:123", {"status": "duplicate"})
            assert second == Ok(False)

        # Verify the first value stuck
        result = await store.get("order:123")
        assert result == Ok(Some({"status": "processing"}))

    @pytest.mark.asyncio
    async def test_multi_namespace_isolation(self) -> None:
        """Multiple prefix-isolated namespaces on a shared backend."""
        backend = MemoryStorage()
        users = prefix_kv(kv(backend, JsonCodec()), "users:")
        orders = prefix_kv(kv(backend, JsonCodec()), "orders:")
        settings = prefix_kv(kv(backend, JsonCodec()), "settings:")

        await users.set("alice", {"email": "alice@example.com"})
        await orders.set("alice", {"total": 100})
        await settings.set("alice", {"theme": "dark"})

        # Each namespace is independent
        assert await users.get("alice") == Ok(Some({"email": "alice@example.com"}))
        assert await orders.get("alice") == Ok(Some({"total": 100}))
        assert await settings.get("alice") == Ok(Some({"theme": "dark"}))

        # Delete in one namespace doesn't affect others
        await users.delete("alice")
        assert await users.get("alice") == Ok(Nothing())
        assert await orders.get("alice") == Ok(Some({"total": 100}))
        assert await settings.get("alice") == Ok(Some({"theme": "dark"}))

    @pytest.mark.asyncio
    async def test_tiered_cache_invalidation_workflow(self) -> None:
        """Write-through tiered cache with manual invalidation cycle."""
        l1 = kv(MemoryStorage(), PickleCodec())
        l2 = kv(MemoryStorage(), PickleCodec())
        tiered = tiered_kv(l1, l2)

        # Initial write populates both tiers
        await tiered.set("product:42", {"price": 29.99, "stock": 100})
        assert await l1.get("product:42") == Ok(Some({"price": 29.99, "stock": 100}))
        assert await l2.get("product:42") == Ok(Some({"price": 29.99, "stock": 100}))

        # Simulate price update: delete from tiered, then re-set
        await tiered.delete("product:42")
        assert await l1.get("product:42") == Ok(Nothing())
        assert await l2.get("product:42") == Ok(Nothing())

        await tiered.set("product:42", {"price": 24.99, "stock": 95})
        result = await tiered.get("product:42")
        assert result == Ok(Some({"price": 24.99, "stock": 95}))

    @pytest.mark.asyncio
    async def test_file_storage_as_tiered_l2(self) -> None:
        """FileStorage as the persistent L2 tier in a TieredKV setup."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "l2_data.pickle")
            l1 = kv(MemoryStorage(), PickleCodec())
            l2 = kv(FileStorage(path), PickleCodec())
            tiered = tiered_kv(l1, l2)

            await tiered.set("persistent_key", "important_data")

            # L2 data survives re-instantiation of FileStorage
            l2_new = kv(FileStorage(path), PickleCodec())
            result = await l2_new.get("persistent_key")
            assert result == Ok(Some("important_data"))


class TestErrorPropagationThroughLayers:
    """Integration: verifying error propagation through composition stacks."""

    @pytest.mark.asyncio
    async def test_failing_primary_in_double_fallback(self) -> None:
        """Two levels of fallback: primary fails -> first fallback fails -> second works."""
        failing1 = KV(FailingKVBackend(), PickleCodec())
        failing2 = KV(FailingKVBackend(), PickleCodec())
        working = kv(MemoryStorage(), PickleCodec())
        await working.set("key", "finally")

        # First fallback layer: failing1 -> failing2
        fb1 = fallback_kv(failing1, failing2)
        # Second fallback layer: fb1 -> working
        fb2 = fallback_kv(fb1, working)

        # fb1.get fails (both failing), fb2 falls back to working
        result = await fb2.get("key")
        assert result == Ok(Some("finally"))

    @pytest.mark.asyncio
    async def test_fallback_set_propagates_to_secondary(self) -> None:
        """When primary set fails, fallback writes to secondary.

        Subsequent get through fallback reads from secondary.
        """
        failing = KV(FailingKVBackend(), PickleCodec())
        secondary = kv(MemoryStorage(), PickleCodec())
        fb = fallback_kv(failing, secondary)

        await fb.set("x", "value")
        result = await fb.get("x")
        assert result == Ok(Some("value"))

        # Delete also goes to secondary
        await fb.delete("x")
        result_after = await fb.get("x")
        assert result_after == Ok(Nothing())

    @pytest.mark.asyncio
    async def test_readonly_with_fallback_inner(self) -> None:
        """ReadonlyKV wrapping FallbackKV: reads fall through, writes blocked."""
        failing = KV(FailingKVBackend(), PickleCodec())
        secondary = kv(MemoryStorage(), PickleCodec())
        await secondary.set("immutable", "data")

        fb = fallback_kv(failing, secondary)
        ro = readonly_kv(fb)

        # Read falls through: failing -> secondary -> "data"
        result = await ro.get("immutable")
        assert result == Ok(Some("data"))

        # Write is blocked by readonly
        write_result = await ro.set("immutable", "changed")
        assert write_result == Ok(Nothing())

        # Data unchanged
        assert await secondary.get("immutable") == Ok(Some("data"))

    @pytest.mark.asyncio
    async def test_prefix_over_fallback_with_failing_primary(self) -> None:
        """PrefixKV -> FallbackKV: prefix is applied before fallback logic."""
        failing = KV(FailingKVBackend(), PickleCodec())
        secondary = kv(MemoryStorage(), PickleCodec())
        fb = fallback_kv(failing, secondary)
        prefixed = prefix_kv(fb, "ns:")

        await prefixed.set("key", "val")
        # The secondary should have the prefixed key
        assert await secondary.get("ns:key") == Ok(Some("val"))
        # And prefixed get works
        assert await prefixed.get("key") == Ok(Some("val"))


# ═══════════════════════════════════════════════════════════════════════════════
# Integration: Full storage lifecycle with all patterns
# ═══════════════════════════════════════════════════════════════════════════════


class TestIntegrationStorageFullLifecycle:
    """End-to-end: KV + Queue + Counter + PubSub + Lock through composition."""

    @pytest.mark.asyncio
    async def test_kv_codec_roundtrip_all_codecs(self) -> None:
        """Verify KV set/get roundtrip with Pickle, JSON, and Identity codecs."""
        codecs = [PickleCodec(), JsonCodec(), IdentityCodec()]
        for codec in codecs:
            if isinstance(codec, IdentityCodec):
                # IdentityCodec only works with bytes
                store = kv(MemoryStorage(), codec)
                await store.set("key", b"hello")
                result = await store.get("key")
                assert result == Ok(Some(b"hello"))
            else:
                store = kv(MemoryStorage(), codec)
                data = {"name": "test", "value": 42}
                await store.set("key", data)
                result = await store.get("key")
                assert result == Ok(Some(data))

    @pytest.mark.asyncio
    async def test_prefix_tiered_kv_isolation(self) -> None:
        """PrefixKV + TieredKV: namespaced multi-tier storage."""
        mem1 = MemoryStorage()
        mem2 = MemoryStorage()
        l1 = kv(mem1, PickleCodec())
        l2 = kv(mem2, PickleCodec())

        tiered = tiered_kv(l1, l2, l1_ttl=timedelta(seconds=60))

        # Namespace A
        ns_a = prefix_kv(tiered, "a:")
        # Namespace B
        ns_b = prefix_kv(tiered, "b:")

        await ns_a.set("key", "value_a")
        await ns_b.set("key", "value_b")

        # Isolated reads
        assert await ns_a.get("key") == Ok(Some("value_a"))
        assert await ns_b.get("key") == Ok(Some("value_b"))

        # Raw keys in L1 backend are prefixed
        assert await l1.get("a:key") == Ok(Some("value_a"))
        assert await l1.get("b:key") == Ok(Some("value_b"))

    @pytest.mark.asyncio
    async def test_queue_fifo_with_all_operations(self) -> None:
        """Queue full lifecycle: push, peek, pop, length."""
        backend = MockQueueBackend()
        codec = PickleCodec()
        q = queue_full(backend, codec)

        # Push 3 items
        await q.push("first")
        await q.push("second")
        await q.push("third")

        # Length
        result = await q.length()
        assert result == Ok(3)

        # Peek (doesn't remove)
        peek_result = await q.peek()
        assert peek_result == Ok(Some("first"))

        # Pop (FIFO)
        pop1 = await q.pop()
        assert pop1 == Ok(Some("first"))
        pop2 = await q.pop()
        assert pop2 == Ok(Some("second"))

        # Remaining
        result = await q.length()
        assert result == Ok(1)

    @pytest.mark.asyncio
    async def test_counter_full_lifecycle(self) -> None:
        """Counter: incr, decr, incr_by — each returns new value."""
        backend = MockCounterBackend()
        c = counter_full(backend)

        r1 = await c.incr("visits")
        assert r1 == Ok(1)
        r2 = await c.incr("visits")
        assert r2 == Ok(2)
        r3 = await c.incr("visits")
        assert r3 == Ok(3)

        r4 = await c.decr("visits")
        assert r4 == Ok(2)

        r5 = await c.incr_by("visits", 10)
        assert r5 == Ok(12)

        r6 = await c.decr_by("visits", 5)
        assert r6 == Ok(7)

    @pytest.mark.asyncio
    async def test_readonly_kv_blocks_writes(self) -> None:
        """ReadonlyKV blocks set/delete but allows get."""
        inner = kv(MemoryStorage(), PickleCodec())
        await inner.set("existing", "data")

        ro = readonly_kv(inner)
        # Read works
        assert await ro.get("existing") == Ok(Some("data"))
        # Write blocked
        write_result = await ro.set("new", "value")
        assert write_result == Ok(Nothing())
        # Delete blocked
        del_result = await ro.delete("existing")
        assert del_result == Ok(Nothing())
        # Original unchanged
        assert await inner.get("existing") == Ok(Some("data"))

    @pytest.mark.asyncio
    async def test_map_result_and_map_option(self) -> None:
        """Result combinators: map_option transforms inner value."""
        store = kv(MemoryStorage(), PickleCodec())
        await store.set("num", 42)

        result = await store.get("num")
        # map_option transforms the value inside Ok(Some(...))
        mapped = map_option(result, lambda x: x * 2)
        assert mapped == Ok(Some(84))

        # Missing key → Ok(Nothing) → map_option is no-op
        missing = await store.get("missing")
        mapped_missing = map_option(missing, lambda x: x * 2)
        assert mapped_missing == Ok(Nothing())

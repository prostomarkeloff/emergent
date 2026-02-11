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

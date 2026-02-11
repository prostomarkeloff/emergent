"""Tests for storage explain — dict layer, format layer, recursive composition."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

import pytest

from emergent.wire.axis.storage._kv import KV, KVNX
from emergent.wire.axis.storage._queue import Queue, QueueFull
from emergent.wire.axis.storage._pubsub import PubSub
from emergent.wire.axis.storage._lock import Lock, LockExtend
from emergent.wire.axis.storage._counter import Counter, CounterFull
from emergent.wire.axis.storage._compose import PrefixKV, TieredKV, FallbackKV, ReadonlyKV
from emergent.wire.axis.storage._codec import PickleCodec, JsonCodec, IdentityCodec
from emergent.wire.axis.storage._memory import MemoryStorage
from emergent.wire.axis.storage._explain import (
    storage_dict,
    explain_storage,
    STORAGE_EXPLAIN,
    StorageExplainHandler,
)


# ─── Helpers ────────────────────────────────────────────────────────────────


def _mem():
    return MemoryStorage()


def _kv():
    return KV(backend=_mem(), codec=PickleCodec())


def _kv_json():
    return KV(backend=_mem(), codec=JsonCodec())


# ─── Basic Patterns ─────────────────────────────────────────────────────────


class TestKVDict:
    def test_basic_kv(self):
        store = _kv()
        d = storage_dict(store)
        assert d["type"] == "KV"
        assert d["codec"] == "PickleCodec"
        assert d["backend"] == "MemoryStorage"

    def test_kv_json(self):
        store = _kv_json()
        d = storage_dict(store)
        assert d["codec"] == "JsonCodec"

    def test_kvnx(self):
        store = KVNX(backend=_mem(), codec=PickleCodec())
        d = storage_dict(store)
        assert d["type"] == "KVNX"


class TestQueueDict:
    def test_queue(self):
        store = Queue(backend=_mem(), codec=JsonCodec())
        d = storage_dict(store)
        assert d["type"] == "Queue"
        assert d["codec"] == "JsonCodec"

    def test_queue_full(self):
        store = QueueFull(backend=_mem(), codec=PickleCodec())
        d = storage_dict(store)
        assert d["type"] == "QueueFull"


class TestPubSubDict:
    def test_pubsub(self):
        store = PubSub(backend=_mem(), codec=JsonCodec())
        d = storage_dict(store)
        assert d["type"] == "PubSub"


class TestLockDict:
    def test_lock(self):
        store = Lock(backend=_mem())
        d = storage_dict(store)
        assert d["type"] == "Lock"
        assert d["backend"] == "MemoryStorage"

    def test_lock_extend(self):
        store = LockExtend(backend=_mem())
        d = storage_dict(store)
        assert d["type"] == "LockExtend"


class TestCounterDict:
    def test_counter(self):
        store = Counter(backend=_mem())
        d = storage_dict(store)
        assert d["type"] == "Counter"

    def test_counter_full(self):
        store = CounterFull(backend=_mem())
        d = storage_dict(store)
        assert d["type"] == "CounterFull"


# ─── Composition Wrappers ───────────────────────────────────────────────────


class TestPrefixKV:
    def test_prefix_dict(self):
        store = PrefixKV(inner=_kv(), prefix="cache:")
        d = storage_dict(store)
        assert d["type"] == "PrefixKV"
        assert d["prefix"] == "cache:"
        assert d["inner"]["type"] == "KV"

    def test_nested_prefix(self):
        inner = PrefixKV(inner=_kv(), prefix="v1:")
        outer = PrefixKV(inner=inner, prefix="ns:")
        d = storage_dict(outer)
        assert d["type"] == "PrefixKV"
        assert d["inner"]["type"] == "PrefixKV"
        assert d["inner"]["inner"]["type"] == "KV"


class TestTieredKV:
    def test_tiered_dict(self):
        store = TieredKV(l1=_kv(), l2=_kv_json())
        d = storage_dict(store)
        assert d["type"] == "TieredKV"
        assert d["l1"]["type"] == "KV"
        assert d["l1"]["codec"] == "PickleCodec"
        assert d["l2"]["type"] == "KV"
        assert d["l2"]["codec"] == "JsonCodec"

    def test_tiered_with_ttl(self):
        store = TieredKV(l1=_kv(), l2=_kv_json(), l1_ttl=timedelta(seconds=300))
        d = storage_dict(store)
        assert d["l1_ttl"] == 300.0

    def test_tiered_no_ttl_key(self):
        store = TieredKV(l1=_kv(), l2=_kv())
        d = storage_dict(store)
        assert "l1_ttl" not in d


class TestFallbackKV:
    def test_fallback_dict(self):
        store = FallbackKV(primary=_kv(), secondary=_kv_json())
        d = storage_dict(store)
        assert d["type"] == "FallbackKV"
        assert d["primary"]["type"] == "KV"
        assert d["secondary"]["type"] == "KV"


class TestReadonlyKV:
    def test_readonly_dict(self):
        store = ReadonlyKV(inner=_kv())
        d = storage_dict(store)
        assert d["type"] == "ReadonlyKV"
        assert d["inner"]["type"] == "KV"


class TestDeepComposition:
    def test_tiered_with_prefix(self):
        l1 = PrefixKV(inner=_kv(), prefix="cache:")
        l2 = _kv_json()
        store = TieredKV(l1=l1, l2=l2, l1_ttl=timedelta(seconds=300))
        d = storage_dict(store)
        assert d["type"] == "TieredKV"
        assert d["l1"]["type"] == "PrefixKV"
        assert d["l1"]["prefix"] == "cache:"
        assert d["l1"]["inner"]["type"] == "KV"
        assert d["l2"]["type"] == "KV"
        assert d["l1_ttl"] == 300.0

    def test_readonly_fallback(self):
        store = ReadonlyKV(inner=FallbackKV(primary=_kv(), secondary=_kv_json()))
        d = storage_dict(store)
        assert d["type"] == "ReadonlyKV"
        assert d["inner"]["type"] == "FallbackKV"
        assert d["inner"]["primary"]["type"] == "KV"


# ─── Human-Readable Layer ───────────────────────────────────────────────────


class TestExplainStorage:
    def test_simple_kv(self):
        text = explain_storage(_kv())
        assert "KV" in text
        assert "PickleCodec" in text
        assert "MemoryStorage" in text

    def test_prefix(self):
        store = PrefixKV(inner=_kv(), prefix="cache:")
        text = explain_storage(store)
        assert "PrefixKV" in text
        assert "'cache:'" in text
        assert "inner:" in text

    def test_tiered(self):
        store = TieredKV(l1=_kv(), l2=_kv_json(), l1_ttl=timedelta(seconds=300))
        text = explain_storage(store)
        assert "TieredKV" in text
        assert "l1:" in text
        assert "l2:" in text
        assert "300.0s" in text

    def test_deep_composition(self):
        l1 = PrefixKV(inner=_kv(), prefix="cache:")
        store = TieredKV(l1=l1, l2=_kv_json())
        text = explain_storage(store)
        assert "TieredKV" in text
        assert "PrefixKV" in text


# ─── Open World ─────────────────────────────────────────────────────────────


class TestOpenWorld:
    def test_unknown_type(self):
        @dataclass(frozen=True)
        class CustomStore:
            name: str

        d = storage_dict(CustomStore("redis"))
        assert d["type"] == "CustomStore"
        assert d["name"] == "redis"

    def test_custom_handler(self):
        @dataclass(frozen=True)
        class CustomStore:
            url: str

        def custom_handler(store, ctx):
            return {"type": "Custom", "url": store.url}

        handlers = {**STORAGE_EXPLAIN, CustomStore: custom_handler}
        d = storage_dict(CustomStore("redis://localhost"), handlers=handlers)
        assert d["type"] == "Custom"
        assert d["url"] == "redis://localhost"

    def test_unknown_in_format(self):
        @dataclass(frozen=True)
        class CustomStore:
            name: str

        text = explain_storage(CustomStore("redis"))
        assert "CustomStore" in text
        assert "redis" in text

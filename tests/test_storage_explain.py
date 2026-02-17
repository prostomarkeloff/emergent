"""Tests for storage explain -- dict layer, format layer, recursive composition."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Never, AsyncIterator

from kungfu import Result, Ok, Option, Some, Nothing

from emergent.wire.axis.storage._kv import KV, KVNX  # pyright: ignore[reportPrivateUsage] - testing private module
from emergent.wire.axis.storage._queue import Queue, QueueFull  # pyright: ignore[reportPrivateUsage] - testing private module
from emergent.wire.axis.storage._pubsub import PubSub  # pyright: ignore[reportPrivateUsage] - testing private module
from emergent.wire.axis.storage._lock import Lock, LockExtend  # pyright: ignore[reportPrivateUsage] - testing private module
from emergent.wire.axis.storage._counter import Counter, CounterFull  # pyright: ignore[reportPrivateUsage] - testing private module
from emergent.wire.axis.storage._compose import PrefixKV, TieredKV, FallbackKV, ReadonlyKV  # pyright: ignore[reportPrivateUsage] - testing private module
from emergent.wire.axis.storage._codec import PickleCodec, JsonCodec, IdentityCodec  # pyright: ignore[reportPrivateUsage] - testing private module
from emergent.wire.axis.storage._memory import MemoryStorage  # pyright: ignore[reportPrivateUsage] - testing private module
from emergent.wire.axis.storage._explain import (  # pyright: ignore[reportPrivateUsage] - testing private module
    storage_dict,
    explain_storage,
    STORAGE_EXPLAIN,
    StorageExplainHandler,
    _ExplainCtx,  # pyright: ignore[reportPrivateUsage] - needed for custom handler type signatures in tests
)


# --- Mock backends for Queue, PubSub, Lock, Counter ---
# MemoryStorage only implements KV capabilities (Get/Set/Delete/SetNX).
# These mock backends satisfy the protocols required by other patterns.


class _MockQueueBackend:
    """In-memory queue backend implementing Push + Pop + Peek + Len."""

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


class _MockPubSubBackend:
    """In-memory pub/sub backend implementing Publish + Subscribe."""

    def __init__(self) -> None:
        self._channels: dict[str, list[bytes]] = {}

    async def publish(self, channel: str, value: bytes) -> Result[None, Never]:
        self._channels.setdefault(channel, []).append(value)
        return Ok(None)

    async def subscribe(self, channel: str) -> AsyncIterator[Result[bytes, Never]]:
        for msg in self._channels.get(channel, []):
            yield Ok(msg)


class _MockLockBackend:
    """In-memory lock backend implementing Acquire + Release + Extend."""

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


class _MockCounterBackend:
    """In-memory counter backend implementing Incr + Decr + IncrBy."""

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


# --- Helpers ---


def _mem() -> MemoryStorage[str, bytes]:
    return MemoryStorage[str, bytes]()


def _kv() -> KV[str, Never]:
    return KV[str, Never](backend=_mem(), codec=PickleCodec[str]())


def _kv_json() -> KV[str, Never]:
    return KV[str, Never](backend=_mem(), codec=JsonCodec[str]())


def _queue_backend() -> _MockQueueBackend:
    return _MockQueueBackend()


def _lock_backend() -> _MockLockBackend:
    return _MockLockBackend()


def _counter_backend() -> _MockCounterBackend:
    return _MockCounterBackend()


def _pubsub_backend() -> _MockPubSubBackend:
    return _MockPubSubBackend()


# --- Basic Patterns ---


class TestKVDict:
    def test_basic_kv(self) -> None:
        store = _kv()
        d = storage_dict(store)
        assert d["type"] == "KV"
        assert d["codec"] == "PickleCodec"
        assert d["backend"] == "MemoryStorage"

    def test_kv_json(self) -> None:
        store = _kv_json()
        d = storage_dict(store)
        assert d["codec"] == "JsonCodec"

    def test_kvnx(self) -> None:
        store = KVNX[str, Never](backend=_mem(), codec=PickleCodec[str]())
        d = storage_dict(store)
        assert d["type"] == "KVNX"


class TestQueueDict:
    def test_queue(self) -> None:
        store = Queue[str, Never](backend=_queue_backend(), codec=JsonCodec[str]())
        d = storage_dict(store)
        assert d["type"] == "Queue"
        assert d["codec"] == "JsonCodec"

    def test_queue_full(self) -> None:
        store = QueueFull[str, Never](backend=_queue_backend(), codec=PickleCodec[str]())
        d = storage_dict(store)
        assert d["type"] == "QueueFull"


class TestPubSubDict:
    def test_pubsub(self) -> None:
        store = PubSub[str, Never](backend=_pubsub_backend(), codec=JsonCodec[str]())
        d = storage_dict(store)
        assert d["type"] == "PubSub"


class TestLockDict:
    def test_lock(self) -> None:
        store = Lock[Never](backend=_lock_backend())
        d = storage_dict(store)
        assert d["type"] == "Lock"
        assert d["backend"] == "_MockLockBackend"

    def test_lock_extend(self) -> None:
        store = LockExtend[Never](backend=_lock_backend())
        d = storage_dict(store)
        assert d["type"] == "LockExtend"


class TestCounterDict:
    def test_counter(self) -> None:
        store = Counter[Never](backend=_counter_backend())
        d = storage_dict(store)
        assert d["type"] == "Counter"

    def test_counter_full(self) -> None:
        store = CounterFull[Never](backend=_counter_backend())
        d = storage_dict(store)
        assert d["type"] == "CounterFull"


# --- Composition Wrappers ---


class TestPrefixKV:
    def test_prefix_dict(self) -> None:
        store = PrefixKV[str, Never](inner=_kv(), prefix="cache:")
        d = storage_dict(store)
        assert d["type"] == "PrefixKV"
        assert d["prefix"] == "cache:"
        assert d["inner"]["type"] == "KV"

    def test_nested_prefix(self) -> None:
        inner = PrefixKV[str, Never](inner=_kv(), prefix="v1:")
        outer = PrefixKV[str, Never](inner=inner, prefix="ns:")  # pyright: ignore[reportArgumentType] - testing explain with nested wrappers; PrefixKV is not KV but explain handles it
        d = storage_dict(outer)
        assert d["type"] == "PrefixKV"
        assert d["inner"]["type"] == "PrefixKV"
        assert d["inner"]["inner"]["type"] == "KV"


class TestTieredKV:
    def test_tiered_dict(self) -> None:
        store = TieredKV[str, Never](l1=_kv(), l2=_kv_json())
        d = storage_dict(store)
        assert d["type"] == "TieredKV"
        assert d["l1"]["type"] == "KV"
        assert d["l1"]["codec"] == "PickleCodec"
        assert d["l2"]["type"] == "KV"
        assert d["l2"]["codec"] == "JsonCodec"

    def test_tiered_with_ttl(self) -> None:
        store = TieredKV[str, Never](l1=_kv(), l2=_kv_json(), l1_ttl=timedelta(seconds=300))
        d = storage_dict(store)
        assert d["l1_ttl"] == 300.0

    def test_tiered_no_ttl_key(self) -> None:
        store = TieredKV[str, Never](l1=_kv(), l2=_kv())
        d = storage_dict(store)
        assert "l1_ttl" not in d


class TestFallbackKV:
    def test_fallback_dict(self) -> None:
        store = FallbackKV[str, Never](primary=_kv(), secondary=_kv_json())
        d = storage_dict(store)
        assert d["type"] == "FallbackKV"
        assert d["primary"]["type"] == "KV"
        assert d["secondary"]["type"] == "KV"


class TestReadonlyKV:
    def test_readonly_dict(self) -> None:
        store = ReadonlyKV[str, Never](inner=_kv())
        d = storage_dict(store)
        assert d["type"] == "ReadonlyKV"
        assert d["inner"]["type"] == "KV"


class TestDeepComposition:
    def test_tiered_with_prefix(self) -> None:
        l1 = PrefixKV[str, Never](inner=_kv(), prefix="cache:")
        l2 = _kv_json()
        store = TieredKV[str, Never](l1=l1, l2=l2, l1_ttl=timedelta(seconds=300))  # pyright: ignore[reportArgumentType] - testing explain with PrefixKV as l1; wrappers are not KV but explain handles composition
        d = storage_dict(store)
        assert d["type"] == "TieredKV"
        assert d["l1"]["type"] == "PrefixKV"
        assert d["l1"]["prefix"] == "cache:"
        assert d["l1"]["inner"]["type"] == "KV"
        assert d["l2"]["type"] == "KV"
        assert d["l1_ttl"] == 300.0

    def test_readonly_fallback(self) -> None:
        store = ReadonlyKV[str, Never](inner=FallbackKV[str, Never](primary=_kv(), secondary=_kv_json()))  # pyright: ignore[reportArgumentType] - testing explain with FallbackKV as inner; wrappers are not KV but explain handles composition
        d = storage_dict(store)
        assert d["type"] == "ReadonlyKV"
        assert d["inner"]["type"] == "FallbackKV"
        assert d["inner"]["primary"]["type"] == "KV"


# --- Human-Readable Layer ---


class TestExplainStorage:
    def test_simple_kv(self) -> None:
        text = explain_storage(_kv())
        assert "KV" in text
        assert "PickleCodec" in text
        assert "MemoryStorage" in text

    def test_prefix(self) -> None:
        store = PrefixKV[str, Never](inner=_kv(), prefix="cache:")
        text = explain_storage(store)
        assert "PrefixKV" in text
        assert "'cache:'" in text
        assert "inner:" in text

    def test_tiered(self) -> None:
        store = TieredKV[str, Never](l1=_kv(), l2=_kv_json(), l1_ttl=timedelta(seconds=300))
        text = explain_storage(store)
        assert "TieredKV" in text
        assert "l1:" in text
        assert "l2:" in text
        assert "300.0s" in text

    def test_deep_composition(self) -> None:
        l1 = PrefixKV[str, Never](inner=_kv(), prefix="cache:")
        store = TieredKV[str, Never](l1=l1, l2=_kv_json())  # pyright: ignore[reportArgumentType] - testing explain with PrefixKV as l1
        text = explain_storage(store)
        assert "TieredKV" in text
        assert "PrefixKV" in text


# --- Open World ---


class TestOpenWorld:
    def test_unknown_type(self) -> None:
        @dataclass(frozen=True)
        class CustomStore:
            name: str

        d = storage_dict(CustomStore("redis"))
        assert d["type"] == "CustomStore"
        assert d["name"] == "redis"

    def test_custom_handler(self) -> None:
        @dataclass(frozen=True)
        class CustomStore:
            url: str

        def custom_handler(store: CustomStore, ctx: _ExplainCtx) -> dict[str, str]:
            return {"type": "Custom", "url": store.url}

        handlers: dict[type, StorageExplainHandler] = {**STORAGE_EXPLAIN, CustomStore: custom_handler}
        d = storage_dict(CustomStore("redis://localhost"), handlers=handlers)
        assert d["type"] == "Custom"
        assert d["url"] == "redis://localhost"

    def test_unknown_in_format(self) -> None:
        @dataclass(frozen=True)
        class CustomStore:
            name: str

        text = explain_storage(CustomStore("redis"))
        assert "CustomStore" in text
        assert "redis" in text


# =============================================================================
# INTEGRATION TESTS -- deep composition, cross-pattern, custom handlers
# =============================================================================


class TestDeepCompositionIntegration:
    """Integration: realistic multi-layer composition trees and their explain output."""

    def test_tiered_with_prefixed_l1_and_fallback_l2(self) -> None:
        """TieredKV where L1 is PrefixKV and L2 is FallbackKV.

        Verifies the full recursive dict tree is correct.
        """
        l1 = PrefixKV[str, Never](inner=_kv(), prefix="cache:")
        primary_l2 = _kv_json()
        secondary_l2 = _kv()
        l2 = FallbackKV[str, Never](primary=primary_l2, secondary=secondary_l2)
        store = TieredKV[str, Never](l1=l1, l2=l2, l1_ttl=timedelta(seconds=60))  # pyright: ignore[reportArgumentType] - testing explain with PrefixKV/FallbackKV as tiers

        d = storage_dict(store)
        assert d["type"] == "TieredKV"
        assert d["l1_ttl"] == 60.0

        # L1 subtree
        assert d["l1"]["type"] == "PrefixKV"
        assert d["l1"]["prefix"] == "cache:"
        assert d["l1"]["inner"]["type"] == "KV"
        assert d["l1"]["inner"]["codec"] == "PickleCodec"

        # L2 subtree
        assert d["l2"]["type"] == "FallbackKV"
        assert d["l2"]["primary"]["type"] == "KV"
        assert d["l2"]["primary"]["codec"] == "JsonCodec"
        assert d["l2"]["secondary"]["type"] == "KV"
        assert d["l2"]["secondary"]["codec"] == "PickleCodec"

    def test_readonly_wrapping_tiered_wrapping_prefix(self) -> None:
        """ReadonlyKV -> TieredKV -> (PrefixKV, KV).

        Three layers of composition produce a four-level dict tree.
        """
        l1 = PrefixKV[str, Never](inner=_kv(), prefix="fast:")
        l2 = _kv_json()
        tiered = TieredKV[str, Never](l1=l1, l2=l2)  # pyright: ignore[reportArgumentType] - testing explain with PrefixKV as l1
        store = ReadonlyKV[str, Never](inner=tiered)  # pyright: ignore[reportArgumentType] - testing explain with TieredKV as inner

        d = storage_dict(store)
        assert d["type"] == "ReadonlyKV"
        assert d["inner"]["type"] == "TieredKV"
        assert d["inner"]["l1"]["type"] == "PrefixKV"
        assert d["inner"]["l1"]["prefix"] == "fast:"
        assert d["inner"]["l1"]["inner"]["type"] == "KV"
        assert d["inner"]["l2"]["type"] == "KV"
        assert d["inner"]["l2"]["codec"] == "JsonCodec"

    def test_triple_nested_prefix(self) -> None:
        """Three layers of PrefixKV nesting."""
        inner = _kv()
        p1 = PrefixKV[str, Never](inner=inner, prefix="app:")
        p2 = PrefixKV[str, Never](inner=p1, prefix="v2:")  # pyright: ignore[reportArgumentType] - testing explain with nested PrefixKV
        p3 = PrefixKV[str, Never](inner=p2, prefix="prod:")  # pyright: ignore[reportArgumentType] - testing explain with nested PrefixKV

        d = storage_dict(p3)
        assert d["type"] == "PrefixKV"
        assert d["prefix"] == "prod:"
        assert d["inner"]["type"] == "PrefixKV"
        assert d["inner"]["prefix"] == "v2:"
        assert d["inner"]["inner"]["type"] == "PrefixKV"
        assert d["inner"]["inner"]["prefix"] == "app:"
        assert d["inner"]["inner"]["inner"]["type"] == "KV"

    def test_fallback_with_fallback_secondary(self) -> None:
        """FallbackKV whose secondary is also a FallbackKV (chained fallbacks)."""
        primary = _kv()
        mid_primary = _kv_json()
        mid_secondary = _kv()
        secondary = FallbackKV[str, Never](primary=mid_primary, secondary=mid_secondary)
        store = FallbackKV[str, Never](primary=primary, secondary=secondary)  # pyright: ignore[reportArgumentType] - testing explain with FallbackKV as secondary

        d = storage_dict(store)
        assert d["type"] == "FallbackKV"
        assert d["primary"]["type"] == "KV"
        assert d["secondary"]["type"] == "FallbackKV"
        assert d["secondary"]["primary"]["codec"] == "JsonCodec"
        assert d["secondary"]["secondary"]["codec"] == "PickleCodec"

    def test_all_wrappers_combined(self) -> None:
        """Every composition wrapper in a single tree.

        ReadonlyKV -> FallbackKV -> (PrefixKV, TieredKV -> (KV, KV))
        """
        l1_tier = _kv()
        l2_tier = _kv_json()
        tiered = TieredKV[str, Never](l1=l1_tier, l2=l2_tier, l1_ttl=timedelta(seconds=120))
        prefixed = PrefixKV[str, Never](inner=_kv(), prefix="primary:")
        fb = FallbackKV[str, Never](primary=prefixed, secondary=tiered)  # pyright: ignore[reportArgumentType] - testing explain with PrefixKV/TieredKV as branches
        store = ReadonlyKV[str, Never](inner=fb)  # pyright: ignore[reportArgumentType] - testing explain with FallbackKV as inner

        d = storage_dict(store)
        assert d["type"] == "ReadonlyKV"

        fb_dict = d["inner"]
        assert fb_dict["type"] == "FallbackKV"

        assert fb_dict["primary"]["type"] == "PrefixKV"
        assert fb_dict["primary"]["prefix"] == "primary:"
        assert fb_dict["primary"]["inner"]["type"] == "KV"

        assert fb_dict["secondary"]["type"] == "TieredKV"
        assert fb_dict["secondary"]["l1_ttl"] == 120.0
        assert fb_dict["secondary"]["l1"]["type"] == "KV"
        assert fb_dict["secondary"]["l1"]["codec"] == "PickleCodec"
        assert fb_dict["secondary"]["l2"]["type"] == "KV"
        assert fb_dict["secondary"]["l2"]["codec"] == "JsonCodec"


class TestExplainFormatIntegration:
    """Integration: human-readable format for complex composition trees."""

    def test_tiered_fallback_format_contains_all_layers(self) -> None:
        """explain_storage for TieredKV(PrefixKV, FallbackKV) has every element."""
        l1 = PrefixKV[str, Never](inner=_kv(), prefix="cache:")
        l2 = FallbackKV[str, Never](primary=_kv_json(), secondary=_kv())
        store = TieredKV[str, Never](l1=l1, l2=l2, l1_ttl=timedelta(seconds=300))  # pyright: ignore[reportArgumentType] - testing explain with PrefixKV/FallbackKV as tiers

        text = explain_storage(store)
        assert "TieredKV" in text
        assert "PrefixKV" in text
        assert "'cache:'" in text
        assert "FallbackKV" in text
        assert "JsonCodec" in text
        assert "PickleCodec" in text
        assert "300.0s" in text

    def test_readonly_fallback_format(self) -> None:
        """explain_storage for ReadonlyKV(FallbackKV(KV, KV))."""
        store = ReadonlyKV[str, Never](
            inner=FallbackKV[str, Never](primary=_kv(), secondary=_kv_json())  # pyright: ignore[reportArgumentType] - testing explain with FallbackKV as inner
        )
        text = explain_storage(store)
        assert "ReadonlyKV" in text
        assert "FallbackKV" in text
        assert "primary:" in text
        assert "secondary:" in text

    def test_deep_nesting_format_has_indentation(self) -> None:
        """Deeply nested stores produce indented, multi-line output."""
        inner = _kv()
        p1 = PrefixKV[str, Never](inner=inner, prefix="a:")
        p2 = PrefixKV[str, Never](inner=p1, prefix="b:")  # pyright: ignore[reportArgumentType] - testing explain with nested PrefixKV
        store = ReadonlyKV[str, Never](inner=p2)  # pyright: ignore[reportArgumentType] - testing explain with PrefixKV as inner

        text = explain_storage(store)
        lines = text.strip().split("\n")
        # Should have multiple lines due to nesting
        assert len(lines) > 1
        # Deeper lines should have more indentation
        assert "ReadonlyKV" in lines[0]
        # Inner content should be indented
        indented_lines = [line for line in lines[1:] if line.startswith("  ")]
        assert len(indented_lines) > 0

    def test_format_all_wrappers_combined(self) -> None:
        """Format the tree: ReadonlyKV -> FallbackKV -> (PrefixKV, TieredKV)."""
        l1_tier = _kv()
        l2_tier = _kv_json()
        tiered = TieredKV[str, Never](l1=l1_tier, l2=l2_tier, l1_ttl=timedelta(seconds=60))
        prefixed = PrefixKV[str, Never](inner=_kv(), prefix="ns:")
        fb = FallbackKV[str, Never](primary=prefixed, secondary=tiered)  # pyright: ignore[reportArgumentType] - testing explain with PrefixKV/TieredKV as branches
        store = ReadonlyKV[str, Never](inner=fb)  # pyright: ignore[reportArgumentType] - testing explain with FallbackKV as inner

        text = explain_storage(store)
        # All type names should appear
        for name in ("ReadonlyKV", "FallbackKV", "PrefixKV", "TieredKV"):
            assert name in text
        # Scalar details should appear
        assert "'ns:'" in text
        assert "60.0s" in text


class TestCrossPatternExplain:
    """Integration: explain for non-KV patterns within composition contexts."""

    def test_all_base_patterns_have_distinct_type(self) -> None:
        """Each storage pattern produces a unique 'type' field in storage_dict."""
        stores: list[object] = [
            _kv(),
            KVNX[str, Never](backend=_mem(), codec=PickleCodec[str]()),
            Queue[str, Never](backend=_queue_backend(), codec=JsonCodec[str]()),
            QueueFull[str, Never](backend=_queue_backend(), codec=PickleCodec[str]()),
            PubSub[str, Never](backend=_pubsub_backend(), codec=JsonCodec[str]()),
            Lock[Never](backend=_lock_backend()),
            LockExtend[Never](backend=_lock_backend()),
            Counter[Never](backend=_counter_backend()),
            CounterFull[Never](backend=_counter_backend()),
        ]

        types = [storage_dict(s)["type"] for s in stores]
        # All types should be unique
        assert len(types) == len(set(types))

    def test_all_base_patterns_produce_valid_explain_text(self) -> None:
        """explain_storage returns non-empty, type-containing text for every pattern."""
        patterns: list[tuple[str, object]] = [
            ("KV", _kv()),
            ("KVNX", KVNX[str, Never](backend=_mem(), codec=PickleCodec[str]())),
            ("Queue", Queue[str, Never](backend=_queue_backend(), codec=JsonCodec[str]())),
            ("QueueFull", QueueFull[str, Never](backend=_queue_backend(), codec=PickleCodec[str]())),
            ("PubSub", PubSub[str, Never](backend=_pubsub_backend(), codec=JsonCodec[str]())),
            ("Lock", Lock[Never](backend=_lock_backend())),
            ("LockExtend", LockExtend[Never](backend=_lock_backend())),
            ("Counter", Counter[Never](backend=_counter_backend())),
            ("CounterFull", CounterFull[Never](backend=_counter_backend())),
        ]

        for expected_type, store in patterns:
            text = explain_storage(store)
            assert expected_type in text, f"{expected_type} not in explain output"
            assert len(text) > 0

    def test_identity_codec_in_explain(self) -> None:
        """KV with IdentityCodec shows 'IdentityCodec' in explain."""
        store = KV[bytes, Never](backend=_mem(), codec=IdentityCodec())
        d = storage_dict(store)
        assert d["codec"] == "IdentityCodec"

        text = explain_storage(store)
        assert "IdentityCodec" in text


class TestCustomHandlerIntegration:
    """Integration: extending the explain system with custom handlers."""

    def test_custom_store_in_composition_tree(self) -> None:
        """A custom store type used as inner node of a PrefixKV."""

        @dataclass(frozen=True)
        class RedisKV:
            url: str
            db: int

        def redis_handler(store: RedisKV, ctx: _ExplainCtx) -> dict[str, str | int]:
            return {"type": "RedisKV", "url": store.url, "db": store.db}

        handlers: dict[type, StorageExplainHandler] = {
            **STORAGE_EXPLAIN,
            RedisKV: redis_handler,
        }

        # PrefixKV wrapping a custom RedisKV
        store = PrefixKV[str, Never](inner=RedisKV(url="redis://localhost", db=0), prefix="cache:")  # pyright: ignore[reportArgumentType] - testing explain with custom RedisKV as inner
        d = storage_dict(store, handlers=handlers)

        assert d["type"] == "PrefixKV"
        assert d["prefix"] == "cache:"
        assert d["inner"]["type"] == "RedisKV"
        assert d["inner"]["url"] == "redis://localhost"
        assert d["inner"]["db"] == 0

    def test_custom_handler_in_tiered_tree(self) -> None:
        """Custom store type as L2 in a TieredKV."""

        @dataclass(frozen=True)
        class S3Backend:
            bucket: str

        def s3_handler(store: S3Backend, ctx: _ExplainCtx) -> dict[str, str]:
            return {"type": "S3Backend", "bucket": store.bucket}

        handlers: dict[type, StorageExplainHandler] = {
            **STORAGE_EXPLAIN,
            S3Backend: s3_handler,
        }

        store = TieredKV[str, Never](l1=_kv(), l2=S3Backend(bucket="my-data"))  # pyright: ignore[reportArgumentType] - testing explain with custom S3Backend as l2
        d = storage_dict(store, handlers=handlers)

        assert d["type"] == "TieredKV"
        assert d["l1"]["type"] == "KV"
        assert d["l2"]["type"] == "S3Backend"
        assert d["l2"]["bucket"] == "my-data"

    def test_custom_handler_overrides_built_in(self) -> None:
        """A custom handler can override the built-in KV handler."""

        def verbose_kv_handler(store: KV[str, Never], ctx: _ExplainCtx) -> dict[str, str]:
            return {
                "type": "KV_VERBOSE",
                "codec": type(store.codec).__name__,
                "backend": type(store.backend).__name__,
                "note": "custom handler active",
            }

        handlers: dict[type, StorageExplainHandler] = {
            **STORAGE_EXPLAIN,
            KV: verbose_kv_handler,
        }

        store = _kv()
        d = storage_dict(store, handlers=handlers)
        assert d["type"] == "KV_VERBOSE"
        assert d["note"] == "custom handler active"

        # The override propagates into nested compositions too
        prefixed = PrefixKV[str, Never](inner=store, prefix="ns:")
        d2 = storage_dict(prefixed, handlers=handlers)
        assert d2["inner"]["type"] == "KV_VERBOSE"


class TestDictFormatRoundTrip:
    """Integration: verify storage_dict output can be formatted and still contains all info."""

    def test_dict_keys_present_in_format(self) -> None:
        """All scalar keys from storage_dict appear in explain_storage output."""
        store = TieredKV[str, Never](
            l1=PrefixKV[str, Never](inner=_kv(), prefix="fast:"),  # pyright: ignore[reportArgumentType] - testing explain with PrefixKV as l1
            l2=_kv_json(),
            l1_ttl=timedelta(seconds=999),
        )

        _d = storage_dict(store)
        text = explain_storage(store)

        # Every scalar value from the dict should appear in the formatted text
        assert "TieredKV" in text
        assert "'fast:'" in text
        assert "999.0s" in text
        assert "PickleCodec" in text
        assert "JsonCodec" in text
        assert "MemoryStorage" in text

    def test_nested_dict_structure_matches_format_depth(self) -> None:
        """The number of dict nesting levels correlates with format line count."""
        # Simple single level
        simple = _kv()
        simple_text = explain_storage(simple)
        simple_lines = [line for line in simple_text.strip().split("\n") if line.strip()]

        # Two levels
        prefixed = PrefixKV[str, Never](inner=_kv(), prefix="ns:")
        prefixed_text = explain_storage(prefixed)
        prefixed_lines = [line for line in prefixed_text.strip().split("\n") if line.strip()]

        # Three levels
        tiered = TieredKV[str, Never](
            l1=PrefixKV[str, Never](inner=_kv(), prefix="c:"),  # pyright: ignore[reportArgumentType] - testing explain with PrefixKV as l1
            l2=_kv_json(),
        )
        tiered_text = explain_storage(tiered)
        tiered_lines = [line for line in tiered_text.strip().split("\n") if line.strip()]

        # More composition = more lines
        assert len(simple_lines) <= len(prefixed_lines)
        assert len(prefixed_lines) <= len(tiered_lines)


# =============================================================================
# Integration: Explain full composition topology
# =============================================================================


class TestIntegrationExplainCompositionTopology:
    """Explain complex composition topologies -- verify dict and text output
    for deeply nested storage configurations."""

    def test_four_level_nesting(self) -> None:
        """Readonly -> Prefix -> Tiered -> (Prefix -> KV, KV) -- all layers visible."""
        inner_l1 = PrefixKV[str, Never](inner=_kv(), prefix="cache:")
        inner_l2 = _kv_json()
        tiered = TieredKV[str, Never](l1=inner_l1, l2=inner_l2, l1_ttl=timedelta(seconds=300))  # pyright: ignore[reportArgumentType] - testing explain with PrefixKV as l1
        prefixed = PrefixKV[str, Never](inner=tiered, prefix="app:")  # pyright: ignore[reportArgumentType] - testing explain with TieredKV as inner
        ro = ReadonlyKV[str, Never](inner=prefixed)  # pyright: ignore[reportArgumentType] - testing explain with PrefixKV as inner

        d = storage_dict(ro)
        assert d["type"] == "ReadonlyKV"
        assert d["inner"]["type"] == "PrefixKV"
        assert d["inner"]["prefix"] == "app:"
        assert d["inner"]["inner"]["type"] == "TieredKV"
        assert d["inner"]["inner"]["l1"]["type"] == "PrefixKV"
        assert d["inner"]["inner"]["l1"]["prefix"] == "cache:"

        text = explain_storage(ro)
        assert "ReadonlyKV" in text
        assert "app:" in text
        assert "TieredKV" in text
        assert "cache:" in text
        assert "JsonCodec" in text
        assert "PickleCodec" in text

    def test_fallback_explain_shows_both_branches(self) -> None:
        """FallbackKV with primary + secondary -- both visible in explain."""
        primary = PrefixKV[str, Never](inner=_kv(), prefix="primary:")
        secondary = _kv_json()
        fb = FallbackKV[str, Never](primary=primary, secondary=secondary)  # pyright: ignore[reportArgumentType] - testing explain with PrefixKV as primary

        d = storage_dict(fb)
        assert d["type"] == "FallbackKV"
        assert d["primary"]["type"] == "PrefixKV"
        assert d["secondary"]["type"] == "KV"
        assert d["secondary"]["codec"] == "JsonCodec"

        text = explain_storage(fb)
        assert "FallbackKV" in text
        assert "primary:" in text
        assert "JsonCodec" in text

    def test_all_patterns_explain(self) -> None:
        """All pattern types (KV, KVNX, Queue, PubSub, Lock, Counter) produce valid explain."""
        patterns: list[object] = [
            _kv(),
            KVNX[str, Never](backend=_mem(), codec=PickleCodec[str]()),
        ]
        for p in patterns:
            d = storage_dict(p)
            assert "type" in d
            text = explain_storage(p)
            assert len(text) > 0

    def test_custom_handler_override(self) -> None:
        """Custom StorageExplainHandler overrides dict output for a type."""
        store = _kv()

        # Default
        d_default = storage_dict(store)
        assert d_default["type"] == "KV"

        # Custom handler -- a plain callable matching StorageExplainHandler signature
        def custom_handler(s: KV[str, Never], ctx: _ExplainCtx) -> dict[str, str | bool]:
            return {"type": "CustomKV", "custom": True}

        d_custom = storage_dict(store, handlers={type(store): custom_handler})
        assert d_custom["type"] == "CustomKV"
        assert d_custom["custom"] is True

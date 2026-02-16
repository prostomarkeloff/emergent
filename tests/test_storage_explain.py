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


# =============================================================================
# INTEGRATION TESTS — deep composition, cross-pattern, custom handlers
# =============================================================================


class TestDeepCompositionIntegration:
    """Integration: realistic multi-layer composition trees and their explain output."""

    def test_tiered_with_prefixed_l1_and_fallback_l2(self) -> None:
        """TieredKV where L1 is PrefixKV and L2 is FallbackKV.

        Verifies the full recursive dict tree is correct.
        """
        l1 = PrefixKV(inner=_kv(), prefix="cache:")
        primary_l2 = _kv_json()
        secondary_l2 = _kv()
        l2 = FallbackKV(primary=primary_l2, secondary=secondary_l2)
        store = TieredKV(l1=l1, l2=l2, l1_ttl=timedelta(seconds=60))

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
        l1 = PrefixKV(inner=_kv(), prefix="fast:")
        l2 = _kv_json()
        tiered = TieredKV(l1=l1, l2=l2)
        store = ReadonlyKV(inner=tiered)

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
        p1 = PrefixKV(inner=inner, prefix="app:")
        p2 = PrefixKV(inner=p1, prefix="v2:")
        p3 = PrefixKV(inner=p2, prefix="prod:")

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
        secondary = FallbackKV(primary=mid_primary, secondary=mid_secondary)
        store = FallbackKV(primary=primary, secondary=secondary)

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
        tiered = TieredKV(l1=l1_tier, l2=l2_tier, l1_ttl=timedelta(seconds=120))
        prefixed = PrefixKV(inner=_kv(), prefix="primary:")
        fb = FallbackKV(primary=prefixed, secondary=tiered)
        store = ReadonlyKV(inner=fb)

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
        l1 = PrefixKV(inner=_kv(), prefix="cache:")
        l2 = FallbackKV(primary=_kv_json(), secondary=_kv())
        store = TieredKV(l1=l1, l2=l2, l1_ttl=timedelta(seconds=300))

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
        store = ReadonlyKV(
            inner=FallbackKV(primary=_kv(), secondary=_kv_json())
        )
        text = explain_storage(store)
        assert "ReadonlyKV" in text
        assert "FallbackKV" in text
        assert "primary:" in text
        assert "secondary:" in text

    def test_deep_nesting_format_has_indentation(self) -> None:
        """Deeply nested stores produce indented, multi-line output."""
        inner = _kv()
        p1 = PrefixKV(inner=inner, prefix="a:")
        p2 = PrefixKV(inner=p1, prefix="b:")
        store = ReadonlyKV(inner=p2)

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
        tiered = TieredKV(l1=l1_tier, l2=l2_tier, l1_ttl=timedelta(seconds=60))
        prefixed = PrefixKV(inner=_kv(), prefix="ns:")
        fb = FallbackKV(primary=prefixed, secondary=tiered)
        store = ReadonlyKV(inner=fb)

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
        stores = [
            _kv(),
            KVNX(backend=_mem(), codec=PickleCodec()),
            Queue(backend=_mem(), codec=JsonCodec()),
            QueueFull(backend=_mem(), codec=PickleCodec()),
            PubSub(backend=_mem(), codec=JsonCodec()),
            Lock(backend=_mem()),
            LockExtend(backend=_mem()),
            Counter(backend=_mem()),
            CounterFull(backend=_mem()),
        ]

        types = [storage_dict(s)["type"] for s in stores]
        # All types should be unique
        assert len(types) == len(set(types))

    def test_all_base_patterns_produce_valid_explain_text(self) -> None:
        """explain_storage returns non-empty, type-containing text for every pattern."""
        patterns: list[tuple[str, object]] = [
            ("KV", _kv()),
            ("KVNX", KVNX(backend=_mem(), codec=PickleCodec())),
            ("Queue", Queue(backend=_mem(), codec=JsonCodec())),
            ("QueueFull", QueueFull(backend=_mem(), codec=PickleCodec())),
            ("PubSub", PubSub(backend=_mem(), codec=JsonCodec())),
            ("Lock", Lock(backend=_mem())),
            ("LockExtend", LockExtend(backend=_mem())),
            ("Counter", Counter(backend=_mem())),
            ("CounterFull", CounterFull(backend=_mem())),
        ]

        for expected_type, store in patterns:
            text = explain_storage(store)
            assert expected_type in text, f"{expected_type} not in explain output"
            assert len(text) > 0

    def test_identity_codec_in_explain(self) -> None:
        """KV with IdentityCodec shows 'IdentityCodec' in explain."""
        store = KV(backend=_mem(), codec=IdentityCodec())
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

        # We need the _ExplainCtx import for the handler signature
        handlers: dict[type, StorageExplainHandler] = {
            **STORAGE_EXPLAIN,
            RedisKV: redis_handler,
        }

        # PrefixKV wrapping a custom RedisKV
        store = PrefixKV(inner=RedisKV(url="redis://localhost", db=0), prefix="cache:")
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

        store = TieredKV(l1=_kv(), l2=S3Backend(bucket="my-data"))
        d = storage_dict(store, handlers=handlers)

        assert d["type"] == "TieredKV"
        assert d["l1"]["type"] == "KV"
        assert d["l2"]["type"] == "S3Backend"
        assert d["l2"]["bucket"] == "my-data"

    def test_custom_handler_overrides_built_in(self) -> None:
        """A custom handler can override the built-in KV handler."""

        def verbose_kv_handler(store: KV, ctx: _ExplainCtx) -> dict[str, str]:
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
        prefixed = PrefixKV(inner=store, prefix="ns:")
        d2 = storage_dict(prefixed, handlers=handlers)
        assert d2["inner"]["type"] == "KV_VERBOSE"


class TestDictFormatRoundTrip:
    """Integration: verify storage_dict output can be formatted and still contains all info."""

    def test_dict_keys_present_in_format(self) -> None:
        """All scalar keys from storage_dict appear in explain_storage output."""
        store = TieredKV(
            l1=PrefixKV(inner=_kv(), prefix="fast:"),
            l2=_kv_json(),
            l1_ttl=timedelta(seconds=999),
        )

        d = storage_dict(store)
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
        simple_lines = [l for l in simple_text.strip().split("\n") if l.strip()]

        # Two levels
        prefixed = PrefixKV(inner=_kv(), prefix="ns:")
        prefixed_text = explain_storage(prefixed)
        prefixed_lines = [l for l in prefixed_text.strip().split("\n") if l.strip()]

        # Three levels
        tiered = TieredKV(
            l1=PrefixKV(inner=_kv(), prefix="c:"),
            l2=_kv_json(),
        )
        tiered_text = explain_storage(tiered)
        tiered_lines = [l for l in tiered_text.strip().split("\n") if l.strip()]

        # More composition = more lines
        assert len(simple_lines) <= len(prefixed_lines)
        assert len(prefixed_lines) <= len(tiered_lines)


# ═══════════════════════════════════════════════════════════════════════════════
# Integration: Explain full composition topology
# ═══════════════════════════════════════════════════════════════════════════════


class TestIntegrationExplainCompositionTopology:
    """Explain complex composition topologies — verify dict and text output
    for deeply nested storage configurations."""

    def test_four_level_nesting(self) -> None:
        """Readonly → Prefix → Tiered → (Prefix → KV, KV) — all layers visible."""
        inner_l1 = PrefixKV(inner=_kv(), prefix="cache:")
        inner_l2 = _kv_json()
        tiered = TieredKV(l1=inner_l1, l2=inner_l2, l1_ttl=timedelta(seconds=300))
        prefixed = PrefixKV(inner=tiered, prefix="app:")
        ro = ReadonlyKV(inner=prefixed)

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
        """FallbackKV with primary + secondary — both visible in explain."""
        primary = PrefixKV(inner=_kv(), prefix="primary:")
        secondary = _kv_json()
        fb = FallbackKV(primary=primary, secondary=secondary)

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
        patterns = [
            _kv(),
            KVNX(backend=_mem(), codec=PickleCodec()),
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

        # Custom handler — a plain callable matching StorageExplainHandler signature
        def custom_handler(s: object, ctx: object) -> dict[str, object]:
            return {"type": "CustomKV", "custom": True}

        d_custom = storage_dict(store, handlers={type(store): custom_handler})
        assert d_custom["type"] == "CustomKV"
        assert d_custom["custom"] is True

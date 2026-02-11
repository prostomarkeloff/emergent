"""Storage axis — data persistence via capabilities grammar.

Capabilities are atomic operations. Patterns compose capabilities with codecs.

    from emergent.wire.axis import storage

    # Capabilities (what backends implement)
    storage.Get, storage.Set, storage.Delete      # KV
    storage.Push, storage.Pop, storage.Peek       # Queue
    storage.Publish, storage.Subscribe            # PubSub
    storage.Acquire, storage.Release              # Lock
    storage.Incr, storage.Decr                    # Counter

    # Patterns (what users use)
    users = storage.kv(backend, storage.PickleCodec[User]())
    orders = storage.queue(backend, storage.JsonCodec[Order]())
    events = storage.pubsub(backend, storage.JsonCodec[Event]())

Backend implements capabilities. Pattern composes backend + codec.
Capabilities are the grammar. Patterns are sentences.
"""

# Capabilities — the grammar
from emergent.wire.axis.storage._capabilities import (
    # KV
    Get,
    Set,
    Delete,
    SetWithTTL,
    SetNX,
    # Queue
    Push,
    Pop,
    Peek,
    Len,
    # PubSub
    Publish,
    Subscribe,
    # Lock
    Acquire,
    Release,
    Extend,
    # Counter
    Incr,
    Decr,
    IncrBy,
    # Batch
    BatchGet,
    BatchSet,
    BatchDelete,
    # Pattern
    DeletePattern,
)

# Memory implementation
from emergent.wire.axis.storage._memory import BaseTTLStorage, MemoryStorage

# File implementation (persistent)
from emergent.wire.axis.storage._file import FileStorage

# Codecs — serialization
from emergent.wire.axis.storage._codec import (
    Codec,
    PickleCodec,
    JsonCodec,
    IdentityCodec,
)

# Patterns — compositions
from emergent.wire.axis.storage._kv import (
    KVBackend,
    KVBackendNX,
    KV,
    KVNX,
    kv,
    kv_nx,
)
from emergent.wire.axis.storage._queue import (
    QueueBackend,
    QueueBackendFull,
    Queue,
    QueueFull,
    queue,
    queue_full,
)
from emergent.wire.axis.storage._pubsub import (
    PubSubBackend,
    PubSub,
    pubsub,
)

# Lock Pattern
from emergent.wire.axis.storage._lock import (
    LockBackend,
    LockBackendExtend,
    Lock,
    LockExtend,
    lock,
    lock_extend,
)

# Counter Pattern
from emergent.wire.axis.storage._counter import (
    CounterBackend,
    CounterBackendFull,
    Counter,
    CounterFull,
    counter,
    counter_full,
)

# Result combinators
from emergent.wire.axis.storage._result import (
    map_option,
    map_result,
)

# KV Composition Helpers
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

# Explain
from emergent.wire.axis.storage._explain import (
    StorageExplainHandler,
    storage_dict,
    explain_storage,
    STORAGE_EXPLAIN,
)

# Contrib backends
from emergent.wire.axis.storage import contrib

__all__ = (
    # Capabilities
    "Get",
    "Set",
    "Delete",
    "SetWithTTL",
    "SetNX",
    "Push",
    "Pop",
    "Peek",
    "Len",
    "Publish",
    "Subscribe",
    "Acquire",
    "Release",
    "Extend",
    "Incr",
    "Decr",
    "IncrBy",
    "BatchGet",
    "BatchSet",
    "BatchDelete",
    "DeletePattern",
    # Memory
    "BaseTTLStorage",
    "MemoryStorage",
    # File (persistent)
    "FileStorage",
    # Codecs
    "Codec",
    "PickleCodec",
    "JsonCodec",
    "IdentityCodec",
    # KV Pattern
    "KVBackend",
    "KVBackendNX",
    "KV",
    "KVNX",
    "kv",
    "kv_nx",
    # Queue Pattern
    "QueueBackend",
    "QueueBackendFull",
    "Queue",
    "QueueFull",
    "queue",
    "queue_full",
    # PubSub Pattern
    "PubSubBackend",
    "PubSub",
    "pubsub",
    # Lock Pattern
    "LockBackend",
    "LockBackendExtend",
    "Lock",
    "LockExtend",
    "lock",
    "lock_extend",
    # Counter Pattern
    "CounterBackend",
    "CounterBackendFull",
    "Counter",
    "CounterFull",
    "counter",
    "counter_full",
    # KV Composition
    "PrefixKV",
    "TieredKV",
    "FallbackKV",
    "ReadonlyKV",
    "prefix_kv",
    "tiered_kv",
    "fallback_kv",
    "readonly_kv",
    # Result combinators
    "map_option",
    "map_result",
    # Explain
    "StorageExplainHandler",
    "storage_dict",
    "explain_storage",
    "STORAGE_EXPLAIN",
    # Contrib
    "contrib",
)

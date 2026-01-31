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
from emergent.wire.axis.storage._memory import MemoryStorage

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
    "MemoryStorage",
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
    # Contrib
    "contrib",
)

# Beyond the Database

You've been querying relational data with the query axis. Rows and columns, filters and joins. But now you need a cache. A task queue. A distributed lock so two workers don't process the same job. A counter that won't lose increments under concurrent load. A pub/sub channel for real-time events.

None of that is relational. The query axis handles tables. The storage axis handles everything else.

---

## The grammar

Storage capabilities are atomic operations, each a Protocol class:

```python
from emergent.wire.axis import storage

# KV:      Get, Set, Delete, SetWithTTL, SetNX
# Queue:   Push, Pop, Peek, Len
# PubSub:  Publish, Subscribe
# Lock:    Acquire, Release, Extend
# Counter: Incr, Decr, IncrBy
# Batch:   BatchGet, BatchSet, BatchDelete
```

These are the alphabet. A backend implements whichever letters it knows. Nobody forces a queue backend to support key-value operations. Nobody forces a KV store to do pub/sub. Structural typing -- if your class has `async def get(self, key: K) -> Result[Option[V], E]`, it satisfies `Get[K, V, E]`. No registration, no base class inheritance.

## Patterns: the sentences

Raw capabilities are too low-level for daily use. Patterns compose them with codecs into typed interfaces:

```python
from emergent.wire.axis import storage

backend = storage.MemoryStorage[str, bytes]()

# KV: Get + Set + Delete + Codec
users = storage.kv(backend, storage.PickleCodec[User]())
await users.set("user:1", user)
match await users.get("user:1"):
    case Ok(Some(user)): print(f"Found {user.name}")
    case Ok(Nothing()):  print("Not found")

# Queue: Push + Pop + Codec
tasks = storage.queue(queue_backend, storage.JsonCodec[Task]())
await tasks.push(task)
match await tasks.pop():
    case Ok(Some(task)): process(task)
    case Ok(Nothing()):  print("Queue empty")

# PubSub: Publish + Subscribe + Codec
events = storage.pubsub(pubsub_backend, storage.JsonCodec[Event]())
await events.publish("orders", order_event)
async for result in events.subscribe("orders"):
    match result:
        case Ok(event): handle(event)
        case Error(e):  log(e)

# Lock: Acquire + Release (no codec needed)
from datetime import timedelta
lock_store = storage.lock(lock_backend)
async with lock_store.hold("job:processing", timedelta(seconds=30)) as acquired:
    if acquired:
        await do_exclusive_work()

# Counter: Incr + Decr (no codec needed)
hits = storage.counter(counter_backend)
new_count = await hits.incr("page:home")
```

Every return value is a `Result`. No exceptions flying around. You pattern-match on success or failure, always.

## Codecs

The serialization layer sits between your types and the raw bytes the backend stores:

- **`PickleCodec[T]()`** -- fast, Python-only. Good for caches where you control both sides.
- **`JsonCodec[T]()`** -- portable, human-readable. Good for anything that might cross language boundaries.
- **`IdentityCodec()`** -- no transformation. Pass bytes straight through.

The codec is a parameter, not a decision baked into the backend. Same Redis backend, different codecs for different use cases:

```python
sessions = storage.kv(redis, storage.PickleCodec[Session]())
settings = storage.kv(redis, storage.JsonCodec[dict]())
blobs    = storage.kv(redis, storage.IdentityCodec())
```

## Backends

Two ship out of the box:

```python
# In-memory -- for tests and single-instance apps
mem = storage.MemoryStorage[str, bytes]()

# File-backed -- pickle persistence, survives restarts
disk = storage.FileStorage[str, bytes](".data/cache.pickle")
```

`MemoryStorage` implements Get, Set, SetWithTTL, Delete, SetNX, and DeletePattern. All operations return `Result[..., Never]` -- they literally cannot fail. `FileStorage` extends `MemoryStorage` with disk persistence: every write pickles the entire dict to a file. Crude, effective, zero dependencies.

For production, bring your own backend. Implement the capability protocols your patterns need and you're done. A Redis adapter that satisfies `Get + Set + Delete` is a KV backend by structural typing, not by inheriting from a framework base class.

## Composition

This is where it gets interesting. KV stores compose:

```python
from emergent.wire.axis.storage import prefix_kv, tiered_kv, fallback_kv, readonly_kv
from datetime import timedelta

# Namespace isolation: all keys get a prefix
tenant_users = prefix_kv(base_kv, "tenant:acme:")
await tenant_users.set("alice", user)  # Actually stores "tenant:acme:alice"

# Two-tier cache: memory (fast) -> disk (durable)
cached = tiered_kv(memory_kv, disk_kv, l1_ttl=timedelta(minutes=5))
# Read: check memory -> miss -> check disk -> populate memory
# Write: write to disk first, then memory

# Failover: try primary, fall back to secondary on error
resilient = fallback_kv(primary_redis, backup_redis)

# Safety: reads work, writes silently no-op
safe = readonly_kv(production_kv)
```

`PrefixKV` wraps a KV and prepends a string to every key. `TieredKV` implements cache-aside: check L1, miss, check L2, populate L1. `FallbackKV` tries the primary and switches to the secondary on any error. `ReadonlyKV` allows gets but swallows sets and deletes.

These are pure wrappers. No new backend needed. They compose existing KV stores into new ones. Stack them:

```python
# Namespaced, cached, resilient KV
users = prefix_kv(
    tiered_kv(
        fallback_kv(memory_primary, memory_backup),
        disk_kv,
        l1_ttl=timedelta(minutes=5),
    ),
    "users:",
)
```

Each layer is a frozen dataclass. Each layer is transparent to the explain system.

## The insight

The grammar is the type system. `KVBackend[E]` guarantees Get + Set + Delete. `QueueBackend[E]` guarantees Push + Pop. `LockBackend[E]` guarantees Acquire + Release. These aren't string labels -- they're structural constraints enforced by the type checker.

Add a new capability like `Extend` to your lock backend, and existing `Lock` patterns that only need `Acquire + Release` still work. The new `LockExtend` pattern requires the additional capability. Old code doesn't break. New code opts in. Open-world by construction.

This is the same principle that runs through every axis. Schema capabilities, query expressions, surface enrichers, storage operations -- all grammars. All structurally typed. All composable without coordination.

---

**Next:** [The Universal Fold ->](21-compilation.md)

"""KV QuerySet — Key-Value operations.

For Redis, in-memory KV stores, simple caches.

    users = kv(User, key=lambda u: u.id)

    # Single key ops
    await provider.get(users.get("alice"))
    await provider.set(users.set("alice", user))
    await provider.delete(users.delete("alice"))

    # Scan
    await provider.scan(users.scan("user:*"))
"""

from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatch
from typing import TYPE_CHECKING, Any, Callable, Generic, TypeVar

if TYPE_CHECKING:
    from emergent.wire.axis.query._contexts import MemoryKVContext, HTTPKVContext

from emergent.wire.axis._explain import ExplainContext, ExplainNode


K = TypeVar("K")
T = TypeVar("T")


# ─── Operations ───────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class KVGet(Generic[K]):
    """Get by key."""
    key: K

    def compile_memory_kv(self, ctx: MemoryKVContext) -> MemoryKVContext:
        ctx.result = ctx.store.get(self.key)
        return ctx

    def compile_http_kv(self, ctx: HTTPKVContext) -> HTTPKVContext:
        ctx.method = "GET"
        ctx.path = ctx.encode_key(self.key)
        return ctx

    def compile_explain(self, ctx: ExplainContext) -> ExplainContext:
        return ctx.add(ExplainNode(kind="Get", fields=(("key", repr(self.key)),)))


@dataclass(frozen=True, slots=True)
class KVSet(Generic[K, T]):
    """Set key-value."""
    key: K
    value: T
    ttl: int | None = None  # seconds

    def compile_memory_kv(self, ctx: MemoryKVContext) -> MemoryKVContext:
        ctx.store[self.key] = self.value
        return ctx

    def compile_http_kv(self, ctx: HTTPKVContext) -> HTTPKVContext:
        ctx.method = "PUT"
        ctx.path = ctx.encode_key(self.key)
        ctx.body = ctx.encode_value(self.value, self.ttl)
        return ctx

    def compile_explain(self, ctx: ExplainContext) -> ExplainContext:
        from emergent.wire.axis._explain import ExplainValue
        fields: list[tuple[str, ExplainValue]] = [("key", repr(self.key))]
        if self.ttl is not None:
            fields.append(("ttl", self.ttl))
        return ctx.add(ExplainNode(kind="Set", fields=tuple(fields)))


@dataclass(frozen=True, slots=True)
class KVDelete(Generic[K]):
    """Delete by key."""
    key: K

    def compile_memory_kv(self, ctx: MemoryKVContext) -> MemoryKVContext:
        ctx.result = self.key in ctx.store
        ctx.store.pop(self.key, None)
        return ctx

    def compile_http_kv(self, ctx: HTTPKVContext) -> HTTPKVContext:
        ctx.method = "DELETE"
        ctx.path = ctx.encode_key(self.key)
        return ctx

    def compile_explain(self, ctx: ExplainContext) -> ExplainContext:
        return ctx.add(ExplainNode(kind="Delete", fields=(("key", repr(self.key)),)))


@dataclass(frozen=True, slots=True)
class Exists(Generic[K]):
    """Check key exists."""
    key: K

    def compile_memory_kv(self, ctx: MemoryKVContext) -> MemoryKVContext:
        ctx.result = self.key in ctx.store
        return ctx

    def compile_http_kv(self, ctx: HTTPKVContext) -> HTTPKVContext:
        ctx.method = "HEAD"
        ctx.path = ctx.encode_key(self.key)
        return ctx

    def compile_explain(self, ctx: ExplainContext) -> ExplainContext:
        return ctx.add(ExplainNode(kind="Exists", fields=(("key", repr(self.key)),)))


@dataclass(frozen=True, slots=True)
class Scan:
    """Scan by pattern."""
    pattern: str

    def compile_memory_kv(self, ctx: MemoryKVContext) -> MemoryKVContext:
        ctx.result = [v for k, v in ctx.store.items() if fnmatch(str(k), self.pattern)]
        return ctx

    def compile_http_kv(self, ctx: HTTPKVContext) -> HTTPKVContext:
        ctx.method = "GET"
        ctx.params = ctx.encode_pattern(self.pattern)
        return ctx

    def compile_explain(self, ctx: ExplainContext) -> ExplainContext:
        return ctx.add(ExplainNode(kind="Scan", fields=(("pattern", self.pattern),)))


@dataclass(frozen=True, slots=True)
class Keys:
    """Get all keys matching pattern."""
    pattern: str

    def compile_memory_kv(self, ctx: MemoryKVContext) -> MemoryKVContext:
        ctx.result = [k for k in ctx.store if fnmatch(str(k), self.pattern)]
        return ctx

    def compile_http_kv(self, ctx: HTTPKVContext) -> HTTPKVContext:
        ctx.method = "GET"
        ctx.params = ctx.encode_pattern(self.pattern)
        return ctx

    def compile_explain(self, ctx: ExplainContext) -> ExplainContext:
        return ctx.add(ExplainNode(kind="Keys", fields=(("pattern", self.pattern),)))


# Union type
KVOp = KVGet[Any] | KVSet[Any, Any] | KVDelete[Any] | Exists[Any] | Scan | Keys

# Backward compatibility aliases
Get = KVGet
Delete = KVDelete


# ─── QuerySet ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class KVQuerySet(Generic[K, T]):
    """KV query — key-value operations.

    Generic over K (key type) and T (value type).
    Immutable. Each method returns new query op.
    """

    entity: type[T]
    key_fn: Callable[[T], K]
    op: KVOp | None = None

    def get(self, key: K) -> KVQuerySet[K, T]:
        """Get by key.

        Usage:
            users.get("alice")
            users.get(123)
        """
        return KVQuerySet(entity=self.entity, key_fn=self.key_fn, op=KVGet(key))

    def set(self, key: K, value: T, ttl: int | None = None) -> KVQuerySet[K, T]:
        """Set key-value with optional TTL.

        Usage:
            users.set("alice", user)
            users.set("alice", user, ttl=3600)  # expires in 1 hour
        """
        return KVQuerySet(entity=self.entity, key_fn=self.key_fn, op=KVSet(key, value, ttl))

    def delete(self, key: K) -> KVQuerySet[K, T]:
        """Delete by key.

        Usage:
            users.delete("alice")
        """
        return KVQuerySet(entity=self.entity, key_fn=self.key_fn, op=KVDelete(key))

    def exists(self, key: K) -> KVQuerySet[K, T]:
        """Check if key exists.

        Usage:
            users.exists("alice")
        """
        return KVQuerySet(entity=self.entity, key_fn=self.key_fn, op=Exists(key))

    def scan(self, pattern: str) -> KVQuerySet[K, T]:
        """Scan keys by pattern.

        Usage:
            users.scan("user:*")
            users.scan("session:abc:*")
        """
        return KVQuerySet(entity=self.entity, key_fn=self.key_fn, op=Scan(pattern))

    def keys(self, pattern: str = "*") -> KVQuerySet[K, T]:
        """Get keys matching pattern.

        Usage:
            users.keys()  # all keys
            users.keys("user:*")
        """
        return KVQuerySet(entity=self.entity, key_fn=self.key_fn, op=Keys(pattern))

    # ─── Introspection ─────────────────────────────────────────────────────

    @property
    def ops(self) -> tuple[KVOp, ...]:
        """Pipeline ops for fold compilation. Uniform access with RelationalQuerySet/APIQuerySet."""
        return (self.op,) if self.op is not None else ()

    # ─── Convenience ──────────────────────────────────────────────────────

    def put(self, entity: T, ttl: int | None = None) -> KVQuerySet[K, T]:
        """Set using entity's key.

        Usage:
            users.put(user)  # key extracted from user
        """
        key = self.key_fn(entity)
        return self.set(key, entity, ttl)


def kv(entity: type[T], key: Callable[[T], K]) -> KVQuerySet[K, T]:
    """Create KV QuerySet for entity.

    Args:
        entity: Entity type
        key: Function to extract key from entity

    Usage:
        users = kv(User, key=lambda u: u.id)
        q = users.get("alice")
    """
    return KVQuerySet(entity=entity, key_fn=key)


__all__ = (
    # Operations (new names)
    "KVGet",
    "KVSet",
    "KVDelete",
    "Exists",
    "Scan",
    "Keys",
    "KVOp",
    # Backward compat aliases
    "Get",
    "Delete",
    # QuerySet
    "KVQuerySet",
    "kv",
)

"""KV QuerySet — Key-Value operations.

For Redis, in-memory KV stores, simple caches.

    users = kv(User, key=lambda u: u.id)

    # Single key ops
    await provider.get(users.get("alice"))
    await provider.set(users.set("alice", user))
    await provider.delete(users.delete("alice"))

    # Scan
    await provider.fetch_many(users.scan("user:*"))
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Generic, TypeVar


T = TypeVar("T")


# ─── Operations ───────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Get:
    """Get by key."""
    key: Any


@dataclass(frozen=True, slots=True)
class Set:
    """Set key-value."""
    key: Any
    value: Any
    ttl: int | None = None  # seconds


@dataclass(frozen=True, slots=True)
class Delete:
    """Delete by key."""
    key: Any


@dataclass(frozen=True, slots=True)
class Exists:
    """Check key exists."""
    key: Any


@dataclass(frozen=True, slots=True)
class Scan:
    """Scan by pattern."""
    pattern: str


@dataclass(frozen=True, slots=True)
class Keys:
    """Get all keys matching pattern."""
    pattern: str


# Union type
KVOp = Get | Set | Delete | Exists | Scan | Keys


# ─── QuerySet ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class KVQuerySet(Generic[T]):
    """KV query — key-value operations.

    Immutable. Each method returns new query op.
    """

    entity: type[T]
    key_fn: Callable[[T], Any]
    op: KVOp | None = None

    def get(self, key: Any) -> KVQuerySet[T]:
        """Get by key.

        Usage:
            users.get("alice")
            users.get(123)
        """
        return KVQuerySet(entity=self.entity, key_fn=self.key_fn, op=Get(key))

    def set(self, key: Any, value: T, ttl: int | None = None) -> KVQuerySet[T]:
        """Set key-value with optional TTL.

        Usage:
            users.set("alice", user)
            users.set("alice", user, ttl=3600)  # expires in 1 hour
        """
        return KVQuerySet(entity=self.entity, key_fn=self.key_fn, op=Set(key, value, ttl))

    def delete(self, key: Any) -> KVQuerySet[T]:
        """Delete by key.

        Usage:
            users.delete("alice")
        """
        return KVQuerySet(entity=self.entity, key_fn=self.key_fn, op=Delete(key))

    def exists(self, key: Any) -> KVQuerySet[T]:
        """Check if key exists.

        Usage:
            users.exists("alice")
        """
        return KVQuerySet(entity=self.entity, key_fn=self.key_fn, op=Exists(key))

    def scan(self, pattern: str) -> KVQuerySet[T]:
        """Scan keys by pattern.

        Usage:
            users.scan("user:*")
            users.scan("session:abc:*")
        """
        return KVQuerySet(entity=self.entity, key_fn=self.key_fn, op=Scan(pattern))

    def keys(self, pattern: str = "*") -> KVQuerySet[T]:
        """Get keys matching pattern.

        Usage:
            users.keys()  # all keys
            users.keys("user:*")
        """
        return KVQuerySet(entity=self.entity, key_fn=self.key_fn, op=Keys(pattern))

    # ─── Convenience ──────────────────────────────────────────────────────

    def put(self, entity: T, ttl: int | None = None) -> KVQuerySet[T]:
        """Set using entity's key.

        Usage:
            users.put(user)  # key extracted from user
        """
        key = self.key_fn(entity)
        return self.set(key, entity, ttl)


def kv(entity: type[T], key: Callable[[T], Any]) -> KVQuerySet[T]:
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
    # Operations
    "Get",
    "Set",
    "Delete",
    "Exists",
    "Scan",
    "Keys",
    "KVOp",
    # QuerySet
    "KVQuerySet",
    "kv",
)

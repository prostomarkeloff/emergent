"""Storage capabilities — atomic operations that compose into patterns.

Capabilities are the grammar. Patterns are sentences.

    # Atomic capabilities
    Get[K, V, E]      — read by key
    Set[K, V, E]      — write by key
    Delete[K, E]      — remove by key
    SetWithTTL[K, V, E] — write with expiration
    SetNX[K, V, E]    — write if not exists

    Push[V, E]        — append to queue
    Pop[V, E]         — remove from queue
    Peek[V, E]        — read without remove
    Len[E]            — queue length

    Publish[C, V, E]  — broadcast to channel
    Subscribe[C, V, E] — listen to channel

    Acquire[K, E]     — distributed lock
    Release[K, E]     — release lock

    Incr[K, E]        — atomic increment
    Decr[K, E]        — atomic decrement

Backends implement capabilities. Patterns require capabilities.
"""

from datetime import timedelta
from typing import Protocol, AsyncIterator

from kungfu import Result, Option


type KVMap[K, V] = dict[K, V]


# ═══════════════════════════════════════════════════════════════════════════════
# KV Capabilities
# ═══════════════════════════════════════════════════════════════════════════════


class Get[K, V, E](Protocol):
    """Read by key."""
    async def get(self, key: K) -> Result[Option[V], E]: ...


class Set[K, V, E](Protocol):
    """Write by key."""
    async def set(self, key: K, value: V) -> Result[None, E]: ...


class Delete[K, E](Protocol):
    """Remove by key."""
    async def delete(self, key: K) -> Result[None, E]: ...


class SetWithTTL[K, V, E](Protocol):
    """Write with expiration."""
    async def set(self, key: K, value: V, ttl: timedelta | None = None) -> Result[None, E]: ...


class SetNX[K, V, E](Protocol):
    """Write if not exists. Returns True if set, False if exists."""
    async def set_nx(self, key: K, value: V, ttl: timedelta | None = None) -> Result[bool, E]: ...


# ═══════════════════════════════════════════════════════════════════════════════
# Queue Capabilities
# ═══════════════════════════════════════════════════════════════════════════════


class Push[V, E](Protocol):
    """Append to queue."""
    async def push(self, value: V) -> Result[None, E]: ...


class Pop[V, E](Protocol):
    """Remove from front of queue."""
    async def pop(self) -> Result[Option[V], E]: ...


class Peek[V, E](Protocol):
    """Read front without removing."""
    async def peek(self) -> Result[Option[V], E]: ...


class Len[E](Protocol):
    """Get length."""
    async def length(self) -> Result[int, E]: ...


# ═══════════════════════════════════════════════════════════════════════════════
# PubSub Capabilities
# ═══════════════════════════════════════════════════════════════════════════════


class Publish[C, V, E](Protocol):
    """Broadcast to channel."""
    async def publish(self, channel: C, value: V) -> Result[None, E]: ...


class Subscribe[C, V, E](Protocol):
    """Listen to channel."""
    def subscribe(self, channel: C) -> AsyncIterator[Result[V, E]]: ...


# ═══════════════════════════════════════════════════════════════════════════════
# Lock Capabilities
# ═══════════════════════════════════════════════════════════════════════════════


class Acquire[K, E](Protocol):
    """Acquire distributed lock. Returns True if acquired."""
    async def acquire(self, key: K, ttl: timedelta) -> Result[bool, E]: ...


class Release[K, E](Protocol):
    """Release distributed lock."""
    async def release(self, key: K) -> Result[None, E]: ...


class Extend[K, E](Protocol):
    """Extend lock TTL. Returns True if extended."""
    async def extend(self, key: K, ttl: timedelta) -> Result[bool, E]: ...


# ═══════════════════════════════════════════════════════════════════════════════
# Counter Capabilities
# ═══════════════════════════════════════════════════════════════════════════════


class Incr[K, E](Protocol):
    """Atomic increment. Returns new value."""
    async def incr(self, key: K) -> Result[int, E]: ...


class Decr[K, E](Protocol):
    """Atomic decrement. Returns new value."""
    async def decr(self, key: K) -> Result[int, E]: ...


class IncrBy[K, E](Protocol):
    """Atomic increment by amount. Returns new value."""
    async def incr_by(self, key: K, amount: int) -> Result[int, E]: ...


# ═══════════════════════════════════════════════════════════════════════════════
# Batch Capabilities
# ═══════════════════════════════════════════════════════════════════════════════


class BatchGet[K, V, E](Protocol):
    """Read multiple keys."""
    async def get_many(self, keys: list[K]) -> Result[KVMap[K, V], E]: ...


class BatchSet[K, V, E](Protocol):
    """Write multiple keys."""
    async def set_many(self, items: KVMap[K, V]) -> Result[None, E]: ...


class BatchDelete[K, E](Protocol):
    """Delete multiple keys."""
    async def delete_many(self, keys: list[K]) -> Result[None, E]: ...


# ═══════════════════════════════════════════════════════════════════════════════
# Pattern Capabilities
# ═══════════════════════════════════════════════════════════════════════════════


class DeletePattern[E](Protocol):
    """Delete by pattern (e.g., 'user:*')."""
    async def delete_pattern(self, pattern: str) -> Result[int, E]: ...


__all__ = (
    # KV
    "Get",
    "Set",
    "Delete",
    "SetWithTTL",
    "SetNX",
    # Queue
    "Push",
    "Pop",
    "Peek",
    "Len",
    # PubSub
    "Publish",
    "Subscribe",
    # Lock
    "Acquire",
    "Release",
    "Extend",
    # Counter
    "Incr",
    "Decr",
    "IncrBy",
    # Batch
    "BatchGet",
    "BatchSet",
    "BatchDelete",
    # Pattern
    "DeletePattern",
)

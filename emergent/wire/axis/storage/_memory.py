"""In-memory storage implementation.

MemoryStorage implements all capabilities for testing and single-instance use.

    from emergent.wire.axis.storage import MemoryStorage

    storage = MemoryStorage[str, User]()
    await storage.set("user:1", user)
    match await storage.get("user:1"):
        case Ok(Some(user)): ...
"""

import fnmatch
from datetime import datetime, timedelta
from typing import Generic, TypeVar, Never

from kungfu import Result, Ok, Option, Some, Nothing


K = TypeVar("K")
V = TypeVar("V")


class BaseTTLStorage(Generic[K, V]):
    """Base storage with TTL support and (value, expires_at) tuples.

    Subclasses override `_persist()` to add durability.
    """

    _data: dict[K, tuple[V, datetime | None]]

    def _is_expired(self, expires_at: datetime | None) -> bool:
        """Check if entry is expired."""
        return expires_at is not None and datetime.now() > expires_at

    def _persist(self) -> None:
        """Called after every write. Override for durability."""

    # Get
    async def get(self, key: K) -> Result[Option[V], Never]:
        entry = self._data.get(key)
        if entry is None:
            return Ok(Nothing())
        value, expires_at = entry
        if self._is_expired(expires_at):
            del self._data[key]
            self._persist()
            return Ok(Nothing())
        return Ok(Some(value))

    # Set with TTL
    async def set(self, key: K, value: V, ttl: timedelta | None = None) -> Result[None, Never]:
        expires_at = datetime.now() + ttl if ttl else None
        self._data[key] = (value, expires_at)
        self._persist()
        return Ok(None)

    # Delete
    async def delete(self, key: K) -> Result[None, Never]:
        self._data.pop(key, None)
        self._persist()
        return Ok(None)

    # SetNX
    async def set_nx(self, key: K, value: V, ttl: timedelta | None = None) -> Result[bool, Never]:
        """Set if not exists. Returns True if set."""
        entry = self._data.get(key)
        if entry is not None:
            _, expires_at = entry
            if not self._is_expired(expires_at):
                return Ok(False)
            del self._data[key]

        expires_at = datetime.now() + ttl if ttl else None
        self._data[key] = (value, expires_at)
        self._persist()
        return Ok(True)

    # DeletePattern (string keys only)
    async def delete_pattern(self, pattern: str) -> Result[int, Never]:
        """Delete keys matching pattern."""
        keys_to_delete = [
            k for k in self._data.keys()
            if isinstance(k, str) and fnmatch.fnmatch(k, pattern)
        ]
        for key in keys_to_delete:
            del self._data[key]
        if keys_to_delete:
            self._persist()
        return Ok(len(keys_to_delete))

    # Keys
    async def keys(self, pattern: str = "*") -> Result[list[K], Never]:
        """Get keys matching pattern."""
        if pattern == "*":
            return Ok(list(self._data.keys()))
        matching = [
            k for k in self._data.keys()
            if isinstance(k, str) and fnmatch.fnmatch(k, pattern)
        ]
        return Ok(matching)


class MemoryStorage(BaseTTLStorage[K, V]):
    """In-memory storage with all capabilities.

    Implements: Get, Set, SetWithTTL, Delete, SetNX, DeletePattern

    For testing and single-instance use only.
    """

    def __init__(self) -> None:
        self._data: dict[K, tuple[V, datetime | None]] = {}


__all__ = ("BaseTTLStorage", "MemoryStorage")

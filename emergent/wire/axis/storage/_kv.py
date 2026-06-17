"""KV pattern — key-value storage with typed codec.

KV = Get + Set + Delete capabilities composed with Codec.

    users = kv(redis, PickleCodec[User]())
    await users.set("user:1", user)
    user = await users.get("user:1")
"""

from dataclasses import dataclass
from datetime import timedelta
from typing import Protocol

from kungfu import Result, Option

from emergent.wire.axis._explain import ExplainContext, ExplainNode
from emergent.wire.axis.storage._codec import Codec
from emergent.wire.axis.storage._result import map_option
from emergent.wire.axis.storage._capabilities import (
    Get as GetCap,
    SetWithTTL as SetCap,
    Delete as DeleteCap,
    SetNX as SetNXCap,
)


# ═══════════════════════════════════════════════════════════════════════════════
# KV Backend — composition of capabilities
# ═══════════════════════════════════════════════════════════════════════════════


class KVBackend[E](
    GetCap[str, bytes, E],
    SetCap[str, bytes, E],
    DeleteCap[str, E],
    Protocol,
):
    """Backend with KV capabilities. Get + Set + Delete."""
    ...


class KVBackendNX[E](
    GetCap[str, bytes, E],
    SetCap[str, bytes, E],
    DeleteCap[str, E],
    SetNXCap[str, bytes, E],
    Protocol,
):
    """Backend with KV + SetNX capabilities."""
    ...


# ═══════════════════════════════════════════════════════════════════════════════
# KV Store — typed wrapper
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class KV[T, E]:
    """Typed key-value store.

    Combines backend (capabilities) with codec (serialization).

    Example:
        users = KV(redis, PickleCodec[User]())

        await users.set("user:1", user)
        match await users.get("user:1"):
            case Ok(Some(user)): ...
            case Ok(Nothing()): ...
            case Error(e): ...
    """

    backend: KVBackend[E]
    codec: Codec[T]

    def compile_explain(self, ctx: ExplainContext) -> ExplainContext:
        return ctx.add(
            ExplainNode(
                "KV",
                (
                    ("codec", type(self.codec).__name__),
                    ("backend", type(self.backend).__name__),
                ),
            )
        )

    async def get(self, key: str) -> Result[Option[T], E]:
        """Get typed value by key."""
        return map_option(await self.backend.get(key), self.codec.decode)

    async def set(self, key: str, value: T, ttl: timedelta | None = None) -> Result[None, E]:
        """Set typed value."""
        return await self.backend.set(key, self.codec.encode(value), ttl)

    async def delete(self, key: str) -> Result[None, E]:
        """Delete key."""
        return await self.backend.delete(key)


@dataclass(frozen=True, slots=True)
class KVNX[T, E]:
    """Typed key-value store with SetNX.

    Like KV but also supports set_nx (set if not exists).
    """

    backend: KVBackendNX[E]
    codec: Codec[T]

    def compile_explain(self, ctx: ExplainContext) -> ExplainContext:
        return ctx.add(
            ExplainNode(
                "KVNX",
                (
                    ("codec", type(self.codec).__name__),
                    ("backend", type(self.backend).__name__),
                ),
            )
        )

    async def get(self, key: str) -> Result[Option[T], E]:
        """Get typed value by key."""
        return map_option(await self.backend.get(key), self.codec.decode)

    async def set(self, key: str, value: T, ttl: timedelta | None = None) -> Result[None, E]:
        """Set typed value."""
        return await self.backend.set(key, self.codec.encode(value), ttl)

    async def set_nx(self, key: str, value: T, ttl: timedelta | None = None) -> Result[bool, E]:
        """Set if not exists. Returns True if set."""
        return await self.backend.set_nx(key, self.codec.encode(value), ttl)

    async def delete(self, key: str) -> Result[None, E]:
        """Delete key."""
        return await self.backend.delete(key)


def kv[T, E](backend: KVBackend[E], codec: Codec[T]) -> KV[T, E]:
    """Create typed KV store."""
    return KV(backend, codec)


def kv_nx[T, E](backend: KVBackendNX[E], codec: Codec[T]) -> KVNX[T, E]:
    """Create typed KV store with SetNX."""
    return KVNX(backend, codec)


__all__ = ("KVBackend", "KVBackendNX", "KV", "KVNX", "kv", "kv_nx")

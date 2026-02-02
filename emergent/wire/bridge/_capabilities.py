"""Bridge capabilities — transform during extraction.

Like compile/_capabilities.py + surface/capabilities/_enricher.py combined.

Two orthogonal protocols:
- BridgeCompilable: transforms BridgeContext (compile-time metadata)
- Purifier: wraps handler (symmetric to ScopeEnricher)

A capability can implement both, one, or neither.

    from emergent.wire.bridge import capabilities as BC

    result = sources.fastapi(
        app,
        capabilities=(
            BC.SkipDeprecated(),
            BC.AddCapability(C.Timeout(seconds=30), for_names=frozenset({"slow"})),
            BC.IsolateGlobal(...),
        ),
    )
"""

from __future__ import annotations

import asyncio
import functools
import inspect
import re
from collections.abc import Awaitable, Callable, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Protocol, TypeGuard, runtime_checkable

from kungfu import Result

from emergent.wire.axis._capability import Capability
from emergent.wire.bridge._core import (
    AnyHandler,
    AsyncHandler,
    SyncHandler,
)

if TYPE_CHECKING:
    from emergent.wire.axis.surface.capabilities._base import SurfaceCapability


# Context manager type alias
type AsyncContextManagerFactory[V] = Callable[[], AbstractAsyncContextManager[V]]


# ═══════════════════════════════════════════════════════════════════════════════
# Bridge Context — extraction metadata
# ═══════════════════════════════════════════════════════════════════════════════


def _empty_surface_caps() -> tuple[SurfaceCapability, ...]:
    return ()


@dataclass(frozen=True, slots=True)
class BridgeContext[T, **P, R]:
    """Extraction context — capabilities transform this.

    T — source-specific trigger data type.
    P — handler parameter spec.
    R — handler return type.

    Capabilities set codec/op_type/op_handler for endpoint creation.
    """

    trigger_data: T
    handler: AnyHandler[P, R]
    # Detected types (from inspector)
    request_type: type | None = None
    response_type: type | None = None
    # Metadata
    name: str | None = None
    description: str | None = None
    deprecated: bool = False
    surface_capabilities: tuple[SurfaceCapability, ...] = field(
        default_factory=_empty_surface_caps
    )
    skip: bool = False
    # Codec + runner setup — set by capabilities (self-contained!)
    codec: object | None = None
    op_type: type | None = None
    op_handler: Callable[..., Awaitable[Result[object, object]]] | None = None


# ═══════════════════════════════════════════════════════════════════════════════
# Protocols
# ═══════════════════════════════════════════════════════════════════════════════


@runtime_checkable
class BridgeCompilable(Protocol):
    """Protocol for context transformation at extraction-time."""

    def compile_bridge[T, **P, R](
        self, ctx: BridgeContext[T, P, R]
    ) -> BridgeContext[T, P, R]:
        """Transform bridge context."""
        ...


@runtime_checkable
class Purifier(Protocol):
    """Protocol for handler wrapping at extraction-time.

    Symmetric to ScopeEnricher but for bridge direction.
    Always returns async handler, preserving parameter spec and return type.
    """

    def purify[**P, R](self, handler: AnyHandler[P, R]) -> AsyncHandler[P, R]:
        """Wrap handler with purification logic."""
        ...


# ═══════════════════════════════════════════════════════════════════════════════
# Base Class
# ═══════════════════════════════════════════════════════════════════════════════


class BridgeCapability(Capability):
    """Base class for bridge extraction capabilities."""

    pass


# ═══════════════════════════════════════════════════════════════════════════════
# Type Guards
# ═══════════════════════════════════════════════════════════════════════════════


def _is_async_handler[**P, R](
    handler: AnyHandler[P, R],
) -> TypeGuard[AsyncHandler[P, R]]:
    """Check if handler is async coroutine function."""
    return inspect.iscoroutinefunction(handler)


def _is_sync_handler[**P, R](
    handler: AnyHandler[P, R],
) -> TypeGuard[SyncHandler[P, R]]:
    """Check if handler is sync (not async) function."""
    return not inspect.iscoroutinefunction(handler)


# ═══════════════════════════════════════════════════════════════════════════════
# Execution Helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _ensure_async[**P, R](handler: AnyHandler[P, R]) -> AsyncHandler[P, R]:
    """Ensure handler is async.

    If handler is already async, returns it unchanged.
    If handler is sync, wraps it to run in thread pool.
    """
    if _is_async_handler(handler):
        return handler

    if _is_sync_handler(handler):
        sync_fn = handler

        @functools.wraps(sync_fn)
        async def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
            return await asyncio.to_thread(sync_fn, *args, **kwargs)

        return wrapped

    raise TypeError("Handler must be sync or async")


async def _call_handler[**P, R](
    handler: AnyHandler[P, R],
    *args: P.args,
    **kwargs: P.kwargs,
) -> R:
    """Call handler (sync or async) and return result."""
    if _is_async_handler(handler):
        return await handler(*args, **kwargs)

    if _is_sync_handler(handler):
        return await asyncio.to_thread(handler, *args, **kwargs)

    raise TypeError("Handler must be sync or async")


def chain_purifiers[**P, R](
    purifiers: Sequence[Purifier],
    handler: AnyHandler[P, R],
) -> AsyncHandler[P, R]:
    """Chain purifiers around handler."""
    if not purifiers:
        return _ensure_async(handler)

    result: AsyncHandler[P, R] = purifiers[-1].purify(handler)
    for purifier in reversed(purifiers[:-1]):
        result = purifier.purify(result)
    return result


def apply_bridge_capabilities[T, **P, R](
    ctx: BridgeContext[T, P, R],
    capabilities: Sequence[BridgeCapability],
) -> BridgeContext[T, P, R]:
    """Apply BridgeCompilable capabilities to context."""
    current = ctx
    for cap in capabilities:
        if isinstance(cap, BridgeCompilable):
            current = cap.compile_bridge(current)
            if current.skip:
                return current
    return current


def apply_purifiers[**P, R](
    handler: AnyHandler[P, R],
    capabilities: Sequence[BridgeCapability],
) -> AsyncHandler[P, R]:
    """Apply Purifier capabilities to handler."""
    purifiers = [cap for cap in capabilities if isinstance(cap, Purifier)]
    if not purifiers:
        return _ensure_async(handler)
    return chain_purifiers(purifiers, handler)


# ═══════════════════════════════════════════════════════════════════════════════
# Capability Lookup Helpers
# ═══════════════════════════════════════════════════════════════════════════════


def find_bridge_capability[C: BridgeCapability](
    capabilities: Sequence[BridgeCapability],
    cap_type: type[C],
) -> C | None:
    """Find first capability of given type."""
    for cap in capabilities:
        if isinstance(cap, cap_type):
            return cap
    return None


def find_all_bridge_capabilities[C: BridgeCapability](
    capabilities: Sequence[BridgeCapability],
    cap_type: type[C],
) -> list[C]:
    """Find all capabilities of given type."""
    return [cap for cap in capabilities if isinstance(cap, cap_type)]


# ═══════════════════════════════════════════════════════════════════════════════
# Matching Helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _matches_name[T, **P, R](
    ctx: BridgeContext[T, P, R],
    names: frozenset[str] | None,
    pattern: str | None,
) -> bool:
    """Check if context matches name criteria."""
    if names is not None and ctx.name is not None:
        if ctx.name in names:
            return True
    if pattern is not None and ctx.name is not None:
        if re.match(pattern, ctx.name):
            return True
    return names is None and pattern is None


# ═══════════════════════════════════════════════════════════════════════════════
# Standard BridgeCompilable Capabilities
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class SkipDeprecated(BridgeCapability):
    """Skip deprecated handlers."""

    def compile_bridge[T, **P, R](
        self, ctx: BridgeContext[T, P, R]
    ) -> BridgeContext[T, P, R]:
        if ctx.deprecated:
            return replace(ctx, skip=True)
        return ctx


@dataclass(frozen=True, slots=True)
class SkipByName(BridgeCapability):
    """Skip handlers by exact name or pattern."""

    names: frozenset[str] = frozenset()
    pattern: str | None = None

    def compile_bridge[T, **P, R](
        self, ctx: BridgeContext[T, P, R]
    ) -> BridgeContext[T, P, R]:
        if ctx.name is not None:
            if ctx.name in self.names:
                return replace(ctx, skip=True)
            if self.pattern is not None and re.match(self.pattern, ctx.name):
                return replace(ctx, skip=True)
        return ctx


@dataclass(frozen=True, slots=True)
class AddCapability(BridgeCapability):
    """Add surface capability to handlers."""

    capability: SurfaceCapability
    for_names: frozenset[str] | None = None
    for_pattern: str | None = None

    def compile_bridge[T, **P, R](
        self, ctx: BridgeContext[T, P, R]
    ) -> BridgeContext[T, P, R]:
        if not _matches_name(ctx, self.for_names, self.for_pattern):
            return ctx
        return replace(
            ctx,
            surface_capabilities=(*ctx.surface_capabilities, self.capability),
        )


@dataclass(frozen=True, slots=True)
class SetRequestTypeByName(BridgeCapability):
    """Set request type by handler name."""

    type_map: dict[str, type]

    def compile_bridge[T, **P, R](
        self, ctx: BridgeContext[T, P, R]
    ) -> BridgeContext[T, P, R]:
        if ctx.request_type is not None:
            return ctx
        if ctx.name is not None and ctx.name in self.type_map:
            return replace(ctx, request_type=self.type_map[ctx.name])
        return ctx


@dataclass(frozen=True, slots=True)
class SetResponseTypeByName(BridgeCapability):
    """Set response type by handler name."""

    type_map: dict[str, type]

    def compile_bridge[T, **P, R](
        self, ctx: BridgeContext[T, P, R]
    ) -> BridgeContext[T, P, R]:
        if ctx.response_type is not None:
            return ctx
        if ctx.name is not None and ctx.name in self.type_map:
            return replace(ctx, response_type=self.type_map[ctx.name])
        return ctx


# ═══════════════════════════════════════════════════════════════════════════════
# Standard Purifier Capabilities
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class WrapAsync(BridgeCapability):
    """Wrap sync handler in async via thread pool."""

    def purify[**P, R](self, handler: AnyHandler[P, R]) -> AsyncHandler[P, R]:
        return _ensure_async(handler)


@dataclass(frozen=True, slots=True)
class CatchErrors[E](BridgeCapability):
    """Add error boundary around handler."""

    on_error: Callable[[Exception], E]

    def purify[**P, R](self, handler: AnyHandler[P, R]) -> AsyncHandler[P, R | E]:
        fallback = self.on_error

        @functools.wraps(handler)
        async def wrapped(*args: P.args, **kwargs: P.kwargs) -> R | E:
            try:
                return await _call_handler(handler, *args, **kwargs)
            except Exception as e:
                return fallback(e)

        return wrapped


@dataclass(frozen=True, slots=True)
class IsolateGlobal[V](BridgeCapability):
    """Isolate global module attribute with lock."""

    module_path: str
    attr_name: str
    factory: Callable[[], V]
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def purify[**P, R](self, handler: AnyHandler[P, R]) -> AsyncHandler[P, R]:
        import importlib

        module = importlib.import_module(self.module_path)
        attr = self.attr_name
        factory = self.factory
        lock = self._lock

        @functools.wraps(handler)
        async def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
            async with lock:
                old = getattr(module, attr)
                setattr(module, attr, factory())
                try:
                    return await _call_handler(handler, *args, **kwargs)
                finally:
                    setattr(module, attr, old)

        return wrapped


@dataclass(frozen=True, slots=True)
class IsolateGlobalAsync[V](BridgeCapability):
    """Isolate global with async context manager factory."""

    module_path: str
    attr_name: str
    factory: AsyncContextManagerFactory[V]
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def purify[**P, R](self, handler: AnyHandler[P, R]) -> AsyncHandler[P, R]:
        import importlib

        module = importlib.import_module(self.module_path)
        attr = self.attr_name
        factory = self.factory
        lock = self._lock

        @functools.wraps(handler)
        async def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
            async with lock:
                old = getattr(module, attr)
                cm = factory()
                new_value = await cm.__aenter__()
                setattr(module, attr, new_value)
                try:
                    return await _call_handler(handler, *args, **kwargs)
                finally:
                    await cm.__aexit__(None, None, None)
                    setattr(module, attr, old)

        return wrapped


@dataclass(frozen=True, slots=True)
class InjectKwarg[V](BridgeCapability):
    """Inject keyword argument into handler."""

    name: str
    factory: Callable[[], V]

    def purify[**P, R](self, handler: AnyHandler[P, R]) -> AsyncHandler[P, R]:
        kwarg_name = self.name
        get_value = self.factory

        @functools.wraps(handler)
        async def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
            if kwarg_name not in kwargs:
                kwargs[kwarg_name] = get_value()
            return await _call_handler(handler, *args, **kwargs)

        return wrapped


@dataclass(frozen=True, slots=True)
class InjectKwargAsync[V](BridgeCapability):
    """Inject keyword argument with async factory."""

    name: str
    factory: Callable[[], Awaitable[V]]

    def purify[**P, R](self, handler: AnyHandler[P, R]) -> AsyncHandler[P, R]:
        kwarg_name = self.name
        get_value = self.factory

        @functools.wraps(handler)
        async def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
            if kwarg_name not in kwargs:
                kwargs[kwarg_name] = await get_value()
            return await _call_handler(handler, *args, **kwargs)

        return wrapped


# ═══════════════════════════════════════════════════════════════════════════════
# MountASGI — mount ASGI app via compiler capability
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class MountASGI(BridgeCapability):
    """Mount ASGI app instead of calling individual handlers.

    Adds the Mount compiler capability to extracted handlers.
    The compiler will mount the ASGI app ONCE at the specified prefix.
    Individual route registrations are skipped — ASGI app handles all routes.

    Example::

        from django.core.asgi import get_asgi_application

        django_asgi = get_asgi_application()

        result = sources.django(
            urlpatterns,
            capabilities=(
                BC.MountASGI(django_asgi, prefix="/django", source="django"),
                BC.WrapAsDelegate(),
            ),
        )

    Attributes:
        app: ASGI application to mount.
        prefix: Path prefix to mount at.
        source: Source framework name (for documentation).
    """

    app: object  # ASGI app
    prefix: str = "/"
    source: str = ""
    _mount_cap: object | None = field(default=None, compare=False, hash=False)

    def compile_bridge[T, **P, R](
        self, ctx: BridgeContext[T, P, R]
    ) -> BridgeContext[T, P, R]:
        """Add Mount compiler capability to surface capabilities."""
        from emergent.wire.compile._capabilities import Mount

        # Reuse same Mount instance so it mounts only once
        if self._mount_cap is None:
            object.__setattr__(self, "_mount_cap", Mount(self.app, self.prefix, self.source))

        return replace(
            ctx,
            surface_capabilities=(*ctx.surface_capabilities, self._mount_cap),
        )


# ═══════════════════════════════════════════════════════════════════════════════
# WrapAsDelegate — THIN, preserves handler signature
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class WrapAsDelegate(BridgeCapability):
    """Wrap handler as DelegateCodec — THIN, framework handles params.

    SIMPLE capability that:
    1. Wraps handler in DelegateCodec (preserves signature)
    2. Optionally extracts response type from return annotation
    3. That's it! Framework (FastAPI) handles all param resolution.

    This is the THIN approach — don't reinvent type resolution.
    """

    def compile_bridge[T, **P, R](
        self, ctx: BridgeContext[T, P, R]
    ) -> BridgeContext[T, P, R]:
        """Create delegate codec — just wrap the handler."""
        from typing import get_type_hints

        from emergent.wire.axis.surface.codecs.delegate import delegate

        # Extract response type from return annotation
        response_type: type | None = None
        if callable(ctx.handler):
            try:
                hints = get_type_hints(ctx.handler)
                ret = hints.get("return")
                if isinstance(ret, type):
                    response_type = ret
            except Exception:
                pass

        # Create codec — just wraps the handler
        codec = delegate(ctx.handler, response=response_type)

        return replace(ctx, codec=codec)


__all__ = (
    # Types
    "SyncHandler",
    "AsyncHandler",
    "AnyHandler",
    # Context
    "BridgeContext",
    # Protocols
    "BridgeCompilable",
    "Purifier",
    # Base
    "BridgeCapability",
    # Execution helpers
    "chain_purifiers",
    "apply_bridge_capabilities",
    "apply_purifiers",
    # Lookup helpers
    "find_bridge_capability",
    "find_all_bridge_capabilities",
    # BridgeCompilable capabilities
    "SkipDeprecated",
    "SkipByName",
    "AddCapability",
    "SetRequestTypeByName",
    "SetResponseTypeByName",
    # Purifier capabilities
    "WrapAsync",
    "CatchErrors",
    "IsolateGlobal",
    "IsolateGlobalAsync",
    "InjectKwarg",
    "InjectKwargAsync",
    # ASGI mounting
    "MountASGI",
    # Delegate wrapping (THIN — framework handles params)
    "WrapAsDelegate",
)

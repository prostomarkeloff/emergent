"""Bridge capabilities — GENERIC transformation during extraction.

CORE MODULE — framework-agnostic. Framework-specific capabilities
live in bridgers/ (e.g., bridgers/fastapi/_capabilities.py).

Two orthogonal protocols:
- BridgeCompilable: transforms BridgeContext (extraction-time metadata)
- Purifier: wraps handler (static transformation)

A capability can implement both, one, or neither.

    from emergent.wire.bridge import capabilities as BC
    from emergent.wire.bridge.bridgers import fastapi

    wire_app = fastapi.extract(
        app,
        capabilities=(
            BC.SkipDeprecated(),
            BC.AddCapability(C.Timeout(seconds=30), for_names=frozenset({"slow"})),
            BC.IsolateGlobal(...),
            # Framework-specific:
            fastapi.capabilities.MapDepends({...}),
        ),
    )
"""

from __future__ import annotations

import asyncio
import functools
import inspect
import re
import sys
from collections.abc import Awaitable, Callable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager, AbstractContextManager
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Protocol, TypeGuard, runtime_checkable


from emergent.wire.axis._capability import Capability
from emergent.wire.bridge._core import (
    AnyHandler,
    AsyncHandler,
    SyncHandler,
    WireData,
)

if TYPE_CHECKING:
    from emergent.wire.axis.surface.capabilities._base import SurfaceCapability


# Context manager type alias
type AsyncContextManagerFactory[V] = Callable[[], AbstractAsyncContextManager[V]]


# ═══════════════════════════════════════════════════════════════════════════════
# Bridge Context — extraction metadata
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class BridgeContext[T, **P, R]:
    """Extraction context — capabilities transform this.

    T — source-specific trigger data type.
    P — handler parameter spec.
    R — handler return type.

    Wire-specific data (codec, surface_capabilities) stored in `wire` field.
    Use replace() to update.
    """

    trigger_data: T
    handler: AnyHandler[P, R]
    # Detected types (from inspector)
    request_type: type | None = None
    response_type: type | None = None
    # Basic metadata
    name: str | None = None
    description: str | None = None
    deprecated: bool = False
    skip: bool = False
    # Wire-specific data — typed container
    wire: WireData = field(default_factory=WireData)


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
    """Protocol for STATIC handler wrapping at extraction-time.

    NOT symmetric to ScopeEnricher — this runs ONCE at extraction, not per-request.
    Use for: sync→async conversion, error boundaries, global isolation.

    For RUNTIME behavior (auth, timeout, retry, caching), use AddCapability
    with enrichers instead::

        # WRONG — Purifier can't access request/scope
        class AuthPurifier:
            def purify(self, handler): ...  # No scope access!

        # RIGHT — AddCapability with enricher runs at runtime
        AddCapability(enricher.Provide(type=User, ...))
        AddCapability(enricher.Timeout(seconds=30))
        AddCapability(enricher.Retry(policy=...))

    Always returns async handler, preserving parameter spec and return type.
    """

    def purify[**P, R](self, handler: AnyHandler[P, R]) -> AsyncHandler[P, R]:
        """Wrap handler with static transformation logic."""
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


# Public aliases for use by bridgers
ensure_async = _ensure_async
call_handler = _call_handler


def chain_purifiers[**P, R](
    purifiers: Sequence[Purifier],
    handler: AnyHandler[P, R],
) -> AsyncHandler[P, R]:
    """Chain purifiers around handler.

    Purifiers are applied in order: first purifier is outermost wrapper.
    For [A, B, C]: A wraps B wraps C wraps handler.
    Execution order: A.before → B.before → C.before → handler → C.after → B.after → A.after
    """
    if not purifiers:
        return _ensure_async(handler)

    # Apply in reverse so first purifier is outermost
    result: AsyncHandler[P, R] = _ensure_async(handler)
    for purifier in reversed(purifiers):
        result = purifier.purify(result)
    return result


type BridgeCapabilityHandler = Callable[
    [BridgeCapability, BridgeContext[object, ..., object]],
    BridgeContext[object, ..., object],
]

type BridgeCapabilityHandlers = Mapping[type[BridgeCapability], BridgeCapabilityHandler]

type NameTypeMap = dict[str, type]
type NameCodecMap = dict[str, object]


def fold_bridge[T, **P, R](
    ctx: BridgeContext[T, P, R],
    capabilities: Sequence[BridgeCapability],
    handlers: BridgeCapabilityHandlers | None = None,
) -> BridgeContext[T, P, R]:
    """Universal bridge-level capability fold — THE bridge primitive.

    Two-level dispatch mirroring compile.fold_field:
    1. Custom handlers override (keyed by capability type)
    2. BridgeCompilable protocol dispatch (fallback)

    Args:
        ctx: Starting BridgeContext
        capabilities: Capabilities to apply
        handlers: Optional custom handlers keyed by capability type

    Returns:
        Final accumulated context after all capabilities applied
    """
    current: BridgeContext[T, P, R] = ctx
    for cap in capabilities:
        cap_type = type(cap)
        if handlers and cap_type in handlers:
            # BridgeCapabilityHandler is type-erased to BridgeContext[object, ..., object]
            # because heterogeneous handler mappings can't preserve per-key generics.
            # The handler contract guarantees it returns the same BridgeContext shape.
            current = handlers[cap_type](cap, current)
        elif isinstance(cap, BridgeCompilable):
            current = cap.compile_bridge(current)
        if current.skip:
            return current
    return current


def apply_bridge_capabilities[T, **P, R](
    ctx: BridgeContext[T, P, R],
    capabilities: Sequence[BridgeCapability],
    handlers: BridgeCapabilityHandlers | None = None,
) -> BridgeContext[T, P, R]:
    """Apply BridgeCompilable capabilities to context.

    Thin wrapper around fold_bridge. The handlers parameter enables
    custom per-type overrides without modifying capabilities.
    """
    return fold_bridge(ctx, capabilities, handlers)


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
class IncludeOnlyByName(BridgeCapability):
    """Include only handlers matching name or pattern. Skip all others."""

    names: frozenset[str] = frozenset()
    pattern: str | None = None

    def compile_bridge[T, **P, R](
        self, ctx: BridgeContext[T, P, R]
    ) -> BridgeContext[T, P, R]:
        if ctx.name is None:
            return replace(ctx, skip=True)
        if ctx.name in self.names:
            return ctx
        if self.pattern is not None and re.match(self.pattern, ctx.name):
            return ctx
        return replace(ctx, skip=True)


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
        new_wire = replace(
            ctx.wire,
            surface_capabilities=(*ctx.wire.surface_capabilities, self.capability),
        )
        return replace(ctx, wire=new_wire)


@dataclass(frozen=True, slots=True)
class SetRequestTypeByName(BridgeCapability):
    """Set request type by handler name."""

    type_map: NameTypeMap

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

    type_map: NameTypeMap

    def compile_bridge[T, **P, R](
        self, ctx: BridgeContext[T, P, R]
    ) -> BridgeContext[T, P, R]:
        if ctx.response_type is not None:
            return ctx
        if ctx.name is not None and ctx.name in self.type_map:
            return replace(ctx, response_type=self.type_map[ctx.name])
        return ctx


@dataclass(frozen=True, slots=True)
class SetCodecByName(BridgeCapability):
    """Set codec explicitly by handler name.

    Use when you need full control over codec creation.

    Example::

        SetCodecByName(codec_map={
            "get_users": rrc(GetUsersRequest, UsersResponse),
            "create_user": rrc(CreateUserRequest, UserResponse),
        })
    """

    codec_map: NameCodecMap

    def compile_bridge[T, **P, R](
        self, ctx: BridgeContext[T, P, R]
    ) -> BridgeContext[T, P, R]:
        if ctx.wire.codec is not None:
            return ctx
        if ctx.name is not None and ctx.name in self.codec_map:
            new_wire = replace(ctx.wire, codec=self.codec_map[ctx.name])
            return replace(ctx, wire=new_wire)
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
    """Isolate global module attribute with per-handler lock.

    Each wrapped handler gets its OWN lock, so different handlers
    don't block each other. Only concurrent calls to the SAME handler serialize.
    """

    module_path: str
    attr_name: str
    factory: Callable[[], V]

    def purify[**P, R](self, handler: AnyHandler[P, R]) -> AsyncHandler[P, R]:
        import importlib

        module = importlib.import_module(self.module_path)
        attr = self.attr_name
        factory = self.factory
        # Per-handler lock — created once per purify() call
        lock = asyncio.Lock()

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
    """Isolate global with async context manager factory.

    Each wrapped handler gets its OWN lock, so different handlers
    don't block each other. Only concurrent calls to the SAME handler serialize.
    """

    module_path: str
    attr_name: str
    factory: AsyncContextManagerFactory[V]

    def purify[**P, R](self, handler: AnyHandler[P, R]) -> AsyncHandler[P, R]:
        import importlib

        module = importlib.import_module(self.module_path)
        attr = self.attr_name
        factory = self.factory
        # Per-handler lock — created once per purify() call
        lock = asyncio.Lock()

        @functools.wraps(handler)
        async def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
            async with lock:
                old = getattr(module, attr)
                cm = factory()
                new_value = await cm.__aenter__()
                setattr(module, attr, new_value)
                try:
                    result = await _call_handler(handler, *args, **kwargs)
                except BaseException:
                    await cm.__aexit__(*sys.exc_info())
                    setattr(module, attr, old)
                    raise
                await cm.__aexit__(None, None, None)
                setattr(module, attr, old)
                return result

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
# Context Manager Purifiers — THE MISSING PRIMITIVE
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class WithContext(BridgeCapability):
    """Run handler inside sync context manager.

    THE universal primitive for legacy code that uses globals/thread-locals.

    Handler signature is preserved — context manager sets up environment,
    handler uses globals/thread-locals as usual.

    Examples::

        # Flask: request context
        WithContext(lambda: app.request_context(environ))

        # Thread-local stack
        WithContext(lambda: local_stack.push(current_value))

        # Class initialization
        @contextmanager
        def ensure_init(cls, db):
            if cls._db is None:
                cls.init(db)
            yield

        WithContext(lambda: ensure_init(UserService, real_db))

        # Set global (no restore)
        @contextmanager
        def set_db(db):
            import myapp
            myapp.db = db
            yield  # No cleanup — permanent for handler

        WithContext(lambda: set_db(real_db))
    """

    factory: Callable[[], AbstractAsyncContextManager[object]]

    def purify[**P, R](self, handler: AnyHandler[P, R]) -> AsyncHandler[P, R]:
        make_ctx = self.factory

        @functools.wraps(handler)
        async def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
            async with make_ctx():
                return await _call_handler(handler, *args, **kwargs)

        return wrapped


@dataclass(frozen=True, slots=True)
class WithContextSync(BridgeCapability):
    """Run handler inside SYNC context manager (converted to async).

    For legacy context managers that aren't async.

    Example::

        from contextlib import contextmanager

        @contextmanager
        def flask_context(app, environ):
            with app.request_context(environ):
                yield

        WithContextSync(lambda: flask_context(app, environ))
    """

    factory: Callable[[], AbstractContextManager[object]]

    def purify[**P, R](self, handler: AnyHandler[P, R]) -> AsyncHandler[P, R]:
        make_ctx = self.factory

        @functools.wraps(handler)
        async def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
            with make_ctx():
                return await _call_handler(handler, *args, **kwargs)

        return wrapped


@dataclass(frozen=True, slots=True)
class SetupTeardown(BridgeCapability):
    """Call setup before handler, teardown after.

    Simpler than context manager when you don't need the protocol.

    Example::

        SetupTeardown(
            setup=lambda: MyClass.init(db),
            teardown=lambda: MyClass.cleanup(),  # Optional
        )
    """

    setup: Callable[[], object]
    teardown: Callable[[], object] | None = None

    def purify[**P, R](self, handler: AnyHandler[P, R]) -> AsyncHandler[P, R]:
        do_setup = self.setup
        do_teardown = self.teardown

        @functools.wraps(handler)
        async def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
            do_setup()
            try:
                return await _call_handler(handler, *args, **kwargs)
            finally:
                if do_teardown is not None:
                    do_teardown()

        return wrapped


@dataclass(frozen=True, slots=True)
class SetGlobal(BridgeCapability):
    """Set module global before handler (no restore).

    For late-bound globals that need initialization.
    Simpler than IsolateGlobal when you don't need isolation.

    Example::

        # db.py has: db = None
        SetGlobal("myapp.db", "db", factory=lambda: Database(url))
    """

    module_path: str
    attr_name: str
    factory: Callable[[], object]

    def purify[**P, R](self, handler: AnyHandler[P, R]) -> AsyncHandler[P, R]:
        import importlib

        module = importlib.import_module(self.module_path)
        setattr(module, self.attr_name, self.factory())

        @functools.wraps(handler)
        async def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
            return await _call_handler(handler, *args, **kwargs)

        return wrapped


# ═══════════════════════════════════════════════════════════════════════════════
# WrapAsDelegate — THIN, preserves handler signature
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class WrapAsDelegate(BridgeCapability):
    """Wrap handler as DelegateCodec — THIN, framework handles params.

    SIMPLE capability that:
    1. Wraps handler in DelegateCodec (preserves signature)
    2. Uses response_type from context (already extracted by inspector)
    3. That's it! Target framework handles all param resolution.

    This is the THIN approach — don't reinvent type resolution.
    """

    def compile_bridge[T, **P, R](
        self, ctx: BridgeContext[T, P, R]
    ) -> BridgeContext[T, P, R]:
        """Create delegate codec — just wrap the handler."""
        from emergent.wire.axis.surface.codecs.delegate import delegate

        # Use response_type from context (already extracted by inspector)
        codec = delegate(ctx.handler, response=ctx.response_type)
        new_wire = replace(ctx.wire, codec=codec)

        return replace(ctx, wire=new_wire)


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
    # Fold primitive
    "BridgeCapabilityHandler",
    "fold_bridge",
    # Execution helpers
    "ensure_async",
    "call_handler",
    "chain_purifiers",
    "apply_bridge_capabilities",
    "apply_purifiers",
    # Lookup helpers
    "find_bridge_capability",
    "find_all_bridge_capabilities",
    # BridgeCompilable capabilities
    "SkipDeprecated",
    "SkipByName",
    "IncludeOnlyByName",
    "AddCapability",
    "SetRequestTypeByName",
    "SetResponseTypeByName",
    "SetCodecByName",
    # Purifier capabilities — Handler wrapping
    "WrapAsync",
    "CatchErrors",
    # Purifier capabilities — Global/Module state
    "IsolateGlobal",
    "IsolateGlobalAsync",
    "SetGlobal",
    # Purifier capabilities — Dependency injection
    "InjectKwarg",
    "InjectKwargAsync",
    # Purifier capabilities — Context management (THE KEY PRIMITIVE)
    "WithContext",
    "WithContextSync",
    "SetupTeardown",
    # Delegate wrapping (THIN — framework handles params)
    "WrapAsDelegate",
)

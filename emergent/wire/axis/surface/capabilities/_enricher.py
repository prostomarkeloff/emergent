"""Scope enricher capabilities — runtime middleware for surface axis.

Uses combinators.py for all operations (timeout, retry, rate_limit).
Uses emergent.cache for caching.

    from emergent.wire.axis.surface import capabilities as C

    endpoint(runner).expose(
        trigger,
        rrc(Request, Response),
        C.enricher.Timeout(seconds=5.0),
        C.enricher.Retry(policy=RetryPolicy.exponential(times=3)),
        Auth(BalanceRequest),
    )
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Awaitable, Callable, Generic, TypeVar, TYPE_CHECKING

from kungfu import Result, Ok, Error
from combinators import lift as L
from combinators import timeout as comb_timeout, delay as comb_delay
from combinators import retry as comb_retry, rate_limit as comb_rate_limit
from combinators.control import RetryPolicy
from combinators.concurrency import RateLimitPolicy

from ._base import SurfaceCapability, ScopeEnricher, EnricherNext

if TYPE_CHECKING:
    from nodnod import Scope
    from emergent.ops._graph import Runner, Op
    from emergent.cache import CacheExecutor


T = TypeVar("T")
E = TypeVar("E")
R = TypeVar("R")
K = TypeVar("K")
V = TypeVar("V")


# ═══════════════════════════════════════════════════════════════════════════════
# Execution Helpers
# ═══════════════════════════════════════════════════════════════════════════════


def chain_enrichers[R](
    enrichers: tuple[ScopeEnricher, ...],
    handler: EnricherNext[R],
) -> EnricherNext[R]:
    """Chain enrichers around handler.

    Builds middleware stack: e1(e2(e3(handler)))
    First enricher in tuple is outermost (runs first).
    """
    result: EnricherNext[R] = handler
    for enricher in reversed(enrichers):
        result = _make_enricher_wrapper(enricher, result)
    return result


def _make_enricher_wrapper[R](
    enricher: ScopeEnricher,
    next_handler: EnricherNext[R],
) -> EnricherNext[R]:
    """Create wrapper closure for enricher."""
    async def wrapper(scope: Scope) -> R:
        return await enricher.enrich(next_handler, scope)
    return wrapper


async def execute_with_enrichers[R](
    enrichers: tuple[ScopeEnricher, ...],
    handler: EnricherNext[R],
    scope: Scope,
) -> R:
    """Execute handler with enrichers."""
    wrapped = chain_enrichers(enrichers, handler)
    return await wrapped(scope)


# ═══════════════════════════════════════════════════════════════════════════════
# Time Enrichers (via combinators.py)
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Timeout(SurfaceCapability):
    """Timeout enricher — uses combinators.py timeout.

    Example::

        Timeout(seconds=5.0)
    """

    seconds: float

    async def enrich[R](self, call: EnricherNext[R], scope: Scope) -> R:
        async def handler() -> Result[R, Exception]:
            try:
                return Ok(await call(scope))
            except Exception as e:
                return Error(e)

        interp = comb_timeout(L.wrap_async(handler), seconds=self.seconds)
        result = await L.down.to_result(interp)

        match result:
            case Ok(value):
                return value
            case Error(e):
                raise e


@dataclass(frozen=True, slots=True)
class Delay(SurfaceCapability):
    """Delay enricher — uses combinators.py delay.

    Example::

        Delay(seconds=1.0)
    """

    seconds: float

    async def enrich[R](self, call: EnricherNext[R], scope: Scope) -> R:
        async def handler() -> Result[R, Exception]:
            try:
                return Ok(await call(scope))
            except Exception as e:
                return Error(e)

        interp = comb_delay(L.wrap_async(handler), seconds=self.seconds)
        result = await L.down.to_result(interp)

        match result:
            case Ok(value):
                return value
            case Error(e):
                raise e


# ═══════════════════════════════════════════════════════════════════════════════
# Resilience Enrichers (via combinators.py)
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Retry(SurfaceCapability):
    """Retry enricher — uses combinators.py RetryPolicy.

    Example::

        from combinators.control import RetryPolicy

        Retry(policy=RetryPolicy.exponential(times=3, initial=0.1))
        Retry(policy=RetryPolicy.fixed(times=3, delay_seconds=0.5))
    """

    policy: RetryPolicy[Exception]

    async def enrich[R](self, call: EnricherNext[R], scope: Scope) -> R:
        async def handler() -> Result[R, Exception]:
            try:
                return Ok(await call(scope))
            except Exception as e:
                return Error(e)

        interp = comb_retry(L.wrap_async(handler), policy=self.policy)
        result = await L.down.to_result(interp)

        match result:
            case Ok(value):
                return value
            case Error(e):
                raise e


@dataclass(frozen=True, slots=True)
class RateLimit(SurfaceCapability):
    """Rate limit enricher — uses combinators.py RateLimitPolicy.

    Example::

        from combinators.concurrency import RateLimitPolicy

        RateLimit(policy=RateLimitPolicy(max_per_second=10.0, burst=5))
    """

    policy: RateLimitPolicy

    async def enrich[R](self, call: EnricherNext[R], scope: Scope) -> R:
        async def handler() -> Result[R, Exception]:
            try:
                return Ok(await call(scope))
            except Exception as e:
                return Error(e)

        interp = comb_rate_limit(L.wrap_async(handler), policy=self.policy)
        result = await L.down.to_result(interp)

        match result:
            case Ok(value):
                return value
            case Error(e):
                raise e


# ═══════════════════════════════════════════════════════════════════════════════
# Provide / Injection Enrichers
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Provide(SurfaceCapability, Generic[T, E]):
    """Provide enricher — run op, inject result into scope.

    Universal pattern for scope enrichment:
    1. Build op from scope
    2. Run op via runner
    3. On Ok: inject result, continue
    4. On Error: short-circuit with error response

    Example::

        Provide(
            type=AuthUser,
            runner=auth_runner,
            op=lambda s: s.get(Request).value.to_auth(),
            on_error=lambda r: ErrorResponse("Unauthorized"),
        )
    """

    type: type[T]
    runner: Runner
    op: Callable[[Scope], Op[T, E]]
    on_error: Callable[[Result[T, E]], object]

    async def enrich[R](self, call: EnricherNext[R], scope: Scope) -> R | object:
        built_op = self.op(scope)
        result: Result[T, E] = await self.runner.run(built_op)

        match result:
            case Ok(value):
                scope.inject(self.type, value)
                return await call(scope)
            case Error():
                return self.on_error(result)


@dataclass(frozen=True, slots=True)
class Inject(SurfaceCapability, Generic[T]):
    """Inject enricher — inject a value into scope before handler.

    Example::

        # Static value
        Inject(type=Config, value=my_config)

        # Computed from scope
        Inject(type=Logger, factory=lambda s: Logger(s.get(Request).id))
    """

    type: type[T]
    value: T | None = None
    factory: Callable[[Scope], T] | None = None

    async def enrich[R](self, call: EnricherNext[R], scope: Scope) -> R:
        if self.factory is not None:
            scope.inject(self.type, self.factory(scope))
        elif self.value is not None:
            scope.inject(self.type, self.value)
        return await call(scope)


# ═══════════════════════════════════════════════════════════════════════════════
# Transform Enrichers
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Transform(SurfaceCapability, Generic[T, R]):
    """Transform enricher — transform response after handler.

    Example::

        Transform(response=lambda r: r.model_dump())
        Transform(response=lambda r: {"data": r, "status": "ok"})
    """

    response: Callable[[T], R]

    async def enrich[S](self, call: EnricherNext[T], scope: Scope) -> R:
        result = await call(scope)
        return self.response(result)


@dataclass(frozen=True, slots=True)
class TransformAsync(SurfaceCapability, Generic[T, R]):
    """Async transform enricher.

    Example::

        TransformAsync(response=async_serialize)
    """

    response: Callable[[T], Awaitable[R]]

    async def enrich[S](self, call: EnricherNext[T], scope: Scope) -> R:
        result = await call(scope)
        return await self.response(result)


# ═══════════════════════════════════════════════════════════════════════════════
# Validation Enrichers
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Validate(SurfaceCapability, Generic[T]):
    """Validate enricher — validate something from scope before handler.

    Example::

        Validate(
            extract=lambda scope: scope.get(Request),
            predicate=lambda req: req.amount > 0,
            on_invalid=lambda req: ErrorResponse("Amount must be positive"),
        )
    """

    extract: Callable[[Scope], T]
    predicate: Callable[[T], bool]
    on_invalid: Callable[[T], object]

    async def enrich[R](self, call: EnricherNext[R], scope: Scope) -> R | object:
        value = self.extract(scope)
        if not self.predicate(value):
            return self.on_invalid(value)
        return await call(scope)


# ═══════════════════════════════════════════════════════════════════════════════
# Cache Enricher (via emergent.cache)
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Cached(SurfaceCapability, Generic[K, V]):
    """Cache enricher — uses emergent.cache.CacheExecutor.

    Wraps handler with cache lookup. On hit, returns cached value.
    On miss, executes handler and caches result.

    Example::

        from emergent import cache as C

        response_cache = (
            C.cache(
                key=lambda req: f"response:{req.user_id}",
                fetch=lambda req: L.up.fail(C.CacheError(...)),
            )
            .tier(C.LocalTier(max_size=1000))
            .build()
        )

        Cached(
            executor=response_cache,
            key=lambda scope: scope.get(Request),
        )
    """

    executor: CacheExecutor[K, V, object]
    key: Callable[[Scope], K]

    async def enrich[R](self, call: EnricherNext[V], scope: Scope) -> V:
        from kungfu import Some

        k = self.key(scope)
        cache_key = self.executor.key_fn(k)

        # Try cache first
        for tier in self.executor.tiers:
            match await tier.get(cache_key):
                case Ok(Some(value)):
                    return value
                case _:
                    continue

        # Cache miss — execute handler
        result = await call(scope)

        # Populate all tiers
        for tier in self.executor.tiers:
            await tier.set(cache_key, result)

        return result


# ═══════════════════════════════════════════════════════════════════════════════
# Control Flow Enrichers
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Passthrough(SurfaceCapability):
    """Passthrough enricher — does nothing, just calls next.

    Useful as placeholder or for conditional chains.
    """

    async def enrich[R](self, call: EnricherNext[R], scope: Scope) -> R:
        return await call(scope)


@dataclass(frozen=True, slots=True)
class When(SurfaceCapability):
    """Conditional enricher — apply inner enricher only when condition is true.

    Example::

        When(
            condition=lambda scope: scope.get(Request).needs_auth,
            then=Auth(...),
        )
    """

    condition: Callable[[Scope], bool]
    then: ScopeEnricher
    otherwise: ScopeEnricher = field(default_factory=Passthrough)

    async def enrich[R](self, call: EnricherNext[R], scope: Scope) -> R:
        if self.condition(scope):
            return await self.then.enrich(call, scope)
        return await self.otherwise.enrich(call, scope)


__all__ = (
    # Execution
    "chain_enrichers",
    "execute_with_enrichers",
    # Time
    "Timeout",
    "Delay",
    # Resilience
    "Retry",
    "RateLimit",
    # Provide / Injection
    "Provide",
    "Inject",
    # Transform
    "Transform",
    "TransformAsync",
    # Validation
    "Validate",
    # Cache
    "Cached",
    # Control flow
    "Passthrough",
    "When",
)

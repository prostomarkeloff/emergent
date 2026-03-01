# Wrapping the Handler

Your payment endpoint is timing out. Not every endpoint -- just the one that talks to the slow third-party billing API. You could slap a global timeout middleware on the whole application, but then your health check gets the same 30-second timeout as your billing call, and your file upload gets the same retry policy as your login endpoint. That's a sledgehammer. You need a scalpel.

One endpoint gets a 5-second timeout. Another gets retry with exponential backoff. A third gets both plus rate limiting. Each one declared right where the endpoint is defined, not in some middleware registry three files away.

---

## The protocol

Enrichers are the scalpel. Here's the entire contract:

```python
from emergent.wire.axis.surface.enrichers._base import ScopeEnricher, EnricherNext

# EnricherNext[R] = Callable[[Scope], Awaitable[R]]

@runtime_checkable
class ScopeEnricher(SurfaceCapability, Protocol):
    async def enrich[R](self, call: EnricherNext[R], scope: Scope) -> R: ...
```

You receive the next handler as `call`. You decide: call it, skip it, wrap it, retry it, time it, cache it. The scope carries the request context. The return type `R` is generic -- enrichers don't care what the handler returns.

This is the classic middleware pattern, but as a frozen dataclass capability instead of a function decorator. That distinction matters. Enrichers are data. They serialize. They explain. They compose.

## Built-in enrichers

The framework ships a toolkit:

```python
from emergent.wire.axis.surface import enrichers
from combinators.control import RetryPolicy
from combinators.concurrency import RateLimitPolicy

# Time control
enrichers.Timeout(seconds=5.0)          # Kill after 5 seconds
enrichers.Delay(seconds=1.0)            # Wait 1 second before executing

# Resilience
enrichers.Retry(policy=RetryPolicy.exponential(times=3, initial=0.1))
enrichers.RateLimit(policy=RateLimitPolicy(max_per_second=10.0, burst=5))

# Injection
enrichers.Inject(type=Config, value=my_config)           # Static value into scope
enrichers.Provide(type=AuthUser, runner=r, op=..., on_error=...)  # Run op, inject result

# Validation
enrichers.Validate(extract=lambda s: s.get(Request), predicate=lambda r: r.amount > 0,
                   on_invalid=lambda r: ErrorResponse("Amount must be positive"))

# Control flow
enrichers.When(condition=lambda s: s.get(Request).needs_auth, then=Auth(...))
enrichers.Passthrough()  # No-op, useful as a default branch
```

Each one is a frozen dataclass. No mutable state. No hidden registration. Just data that knows how to wrap a handler.

## Using them on endpoints

Enrichers are capabilities -- they go in the same `.expose()` call as triggers and codecs:

```python
from emergent.wire.axis.surface import endpoint, enrichers
from emergent.wire.axis.surface.codecs import rrc
from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger
from combinators.control import RetryPolicy

endpoint(runner).expose(
    HTTPRouteTrigger("POST", "/billing/charge"),
    rrc(ChargeRequest, ChargeResponse),
    enrichers.Timeout(seconds=5.0),
    enrichers.Retry(policy=RetryPolicy.exponential(times=3, initial=0.1)),
)
```

That endpoint gets a 5-second timeout and 3 retries with exponential backoff. The health check endpoint next to it gets nothing. The file upload gets only a rate limiter. Each endpoint declares exactly what it needs.

## The chain

When multiple enrichers stack, order matters. `chain_enrichers` builds the middleware onion:

```python
from emergent.wire.axis.surface.enrichers import chain_enrichers

wrapped = chain_enrichers(
    (Auth(...), RateLimit(...), Timeout(5.0)),
    core_handler,
)
# Execution: Auth -> RateLimit -> Timeout -> core_handler
```

First in the tuple is outermost, runs first. Auth checks the token before the rate limiter counts the request. The rate limiter gates before the timeout starts ticking. The timeout wraps only the actual handler execution, not the auth check.

This is the one place in emergent where sequence matters. Capabilities on the schema axis are commutative -- `Annotated[str, MaxLen(50), Unique]` means the same thing regardless of order. But enrichers form a function composition chain: `f(g(h(x)))` is not `h(g(f(x)))`. Auth before RateLimit before Timeout is a different program than Timeout before Auth before RateLimit.

## Writing your own

A logging enricher in six lines:

```python
from dataclasses import dataclass
from emergent.wire.axis.surface.enrichers import ScopeEnricher, EnricherNext

@dataclass(frozen=True, slots=True)
class LogRequest(ScopeEnricher):
    async def enrich[R](self, call: EnricherNext[R], scope: Scope) -> R:
        print(f"Request started")
        result = await call(scope)
        print(f"Request completed")
        return result
```

A circuit breaker that short-circuits without calling the handler:

```python
@dataclass(frozen=True, slots=True)
class CircuitBreaker(ScopeEnricher):
    failure_threshold: int
    _failures: dict[str, int]  # shared mutable state (careful)

    async def enrich[R](self, call: EnricherNext[R], scope: Scope) -> R:
        key = str(type(scope))
        if self._failures.get(key, 0) >= self.failure_threshold:
            raise CircuitOpenError("Circuit is open")
        try:
            result = await call(scope)
            self._failures[key] = 0
            return result
        except Exception:
            self._failures[key] = self._failures.get(key, 0) + 1
            raise
```

The pattern is always the same: receive `call` and `scope`, decide what to do with them.

## Conditional enrichment

The `When` enricher lets you apply middleware conditionally without branching in your handler:

```python
enrichers.When(
    condition=lambda scope: scope.get(Request).value.is_premium,
    then=enrichers.RateLimit(policy=RateLimitPolicy(max_per_second=100.0, burst=50)),
    otherwise=enrichers.RateLimit(policy=RateLimitPolicy(max_per_second=10.0, burst=5)),
)
```

Premium users get 100 requests per second. Everyone else gets 10. The handler doesn't know or care -- the enricher resolves it before the handler ever runs.

---

Enrichers are runtime middleware, but they're still capabilities -- frozen data that the compiler can inspect and the explain system can describe. They're the composable scalpel for per-endpoint behavior that global middleware can never provide.

**Next:** [Beyond the Database ->](20-storage.md)

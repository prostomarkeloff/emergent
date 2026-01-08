# Reference

API reference for code generation.

---

## The Stack

```
emergent.graph  → @G.node, __compose__, topology
emergent.saga   → S.step().then(), auto-rollback
emergent.cache  → C.cache().tier().build()
nodnod          → dependency graphs
combinators     → flow().retry().timeout().compile()
kungfu          → Result[T, E], Ok, Error
```

---

## Imports

```python
from emergent import saga as S
from emergent import cache as C
from emergent import graph as G
from combinators import flow, lift as L
from kungfu import Result, Ok, Error
```

---

## graph

The core paradigm. Programs as dependency graphs.

### API

```python
@G.node                              # Mark class as graph node
class MyNode:
    @classmethod
    async def __compose__(           # Signature = dependencies
        cls,
        dep1: OtherNode,             # Framework resolves this first
        dep2: AnotherNode,           # And this (parallel if independent)
    ) -> MyNode:                     # Returns instance with computed data
        return cls(...)

G.compose(Node, *inputs) -> Node     # Build graph, resolve, return node
G.run(Node) -> RunBuilder            # Fluent API for injection
    .inject(instance)                # Inject concrete node
    .inject_as(Type, instance)       # Inject as Protocol implementation
```

### Pattern: Define Node

```python
@G.node
class FetchUser:
    def __init__(self, data: User) -> None:
        self.data = data

    @classmethod
    async def __compose__(cls, cart: CartNode) -> FetchUser:
        user = await repo.get_user(cart.data.user_id)
        return cls(user)
```

### Pattern: Parallel Execution

```python
@G.node
class CheckoutNode:
    @classmethod
    async def __compose__(
        cls,
        profile: ProfileNode,   # ┐
        loyalty: LoyaltyNode,   # ├─ All depend on CartNode, not each other
        items: ItemsNode,       # ┘ → Run in parallel automatically
    ) -> CheckoutNode:
        return cls(...)
```

### Pattern: DI with Protocol

```python
class PaymentGateway(Protocol):
    async def charge(self, amount: int) -> str: ...

@G.node
class PaymentNode:
    @classmethod
    async def __compose__(cls, gateway: PaymentGateway) -> PaymentNode:
        return cls(await gateway.charge(1000))

# Bind at runtime
await G.run(PaymentNode).inject_as(PaymentGateway, StripePayment())
```

### Pattern: Type-safe Entry Point

```python
@G.node
class ProcessOrder:
    @classmethod
    async def __compose__(cls, user: UserNode, saga: SagaNode) -> ProcessOrder:
        return cls(Order(...))

    @classmethod
    async def execute(cls, cart: Cart, gateway: PaymentGateway) -> Order:
        """Type-safe method that encapsulates all dependencies."""
        node = await (
            G.run(cls)
            .inject(CartNode(cart))
            .inject_as(PaymentGateway, gateway)
        )
        return node.data
```

---

## saga

Distributed transactions with auto-rollback.

### API

```python
S.step(
    action: LazyCoroResult[T, E],
    compensate: Callable[[T], Awaitable[None]] | None = None,
) -> SagaStep[T, E]

step.then(f: Callable[[T], SagaStep[U, E2]]) -> Then[T, U, E | E2]

await S.run(step: SagaStep[T, E]) -> Result[SagaResult[T], SagaError[E]]
await S.run_chain(chain: Then[..., T, E]) -> Result[SagaResult[T], SagaError[E]]

# Also available:
S.from_async(action, on_error, compensate) -> SagaStep[T, E]
```

### Pattern

```python
saga = (
    S.step(
        action=L.catching_async(
            lambda: reserve(items),
            on_error=lambda e: ReserveError(str(e)),
        ),
        compensate=lambda res: release(res.id),
    )
    .then(lambda _: S.step(
        action=L.catching_async(
            lambda: charge(amount),
            on_error=lambda e: PaymentError(str(e)),
        ),
        compensate=lambda pay: refund(pay.id),
    ))
)

result = await S.run_chain(saga)
match result:
    case Ok(r): return r.value
    case Error(e): log(f"Failed: {e.error}, rolled back: {e.rollback_complete}")
```

---

## cache

Multi-tier caching.

**Key concepts:**
- `Tier` = storage backend (global, inject via DI)
- `Cache` = declarative builder (per-use-case, type-safe)

### API

```python
# Tier — storage backend
C.LocalTier(max_size: int = 1000) -> Tier[T]

# Cache — declarative builder
C.cache(
    key: Callable[[K], str],
    fetch: Callable[[K], LazyCoroResult[T, E]],
) -> Cache[K, T, E]

cache.tier(t: Tier[T]) -> Cache[K, T, E]
cache.build() -> CacheExecutor[K, T, E]

executor.get(key: K) -> LazyCoroResult[CacheResult[T], CacheError | E]
await executor.invalidate(key: K) -> Result[bool, CacheError]
```

### Tier Stacking (L1/L2 Cache Pattern)

```
.tier(local).tier(redis)

READ:       local → miss → redis → miss → fetch()
WRITE:      fetch() → store in local AND redis  
INVALIDATE: remove from local AND redis
```

```python
# Tiers are global backends
local = C.LocalTier(max_size=10000)  # L1: per-instance, in-memory
redis = RedisTier(client, ttl=300)   # L2: shared (your impl)

# Cache stacks tiers
user_cache = (
    C.cache(key=lambda uid: f"user:{uid.value}", fetch=fetch_user)
    .tier(local)   # check first
    .tier(redis)   # check second
    .build()
)

result = await user_cache.get(uid)
# result.tier = "local" | "redis" | None (miss)
```

### Pattern: Tier via DI (Real App)

```python
@G.node
class L1Cache[T]:
    """In-memory, per-instance."""
    def __init__(self, tier: C.Tier[T]) -> None:
        self.tier = tier
    
    @classmethod
    def __compose__(cls) -> L1Cache[Profile]:
        return cls(C.LocalTier(max_size=10000))

@G.node
class L2Cache[T]:
    """Redis, shared across instances."""
    def __init__(self, tier: C.Tier[T]) -> None:
        self.tier = tier
    
    @classmethod
    def __compose__(cls, redis: RedisPool) -> L2Cache[Profile]:
        return cls(RedisTier(redis.client, ttl=300))

@G.node
class ProfileNode:
    def __init__(self, profile: Profile) -> None:
        self.data = profile
    
    @classmethod
    async def __compose__(
        cls, cart: CartInput, l1: L1Cache, l2: L2Cache
    ) -> ProfileNode:
        cache = (
            C.cache(key=lambda uid: f"profile:{uid}", fetch=fetch_profile)
            .tier(l1.tier)
            .tier(l2.tier)
            .build()
        )
        result = await cache.get(cart.user_id)
        return cls(result.unwrap().value)
```

---

## combinators.py

### Lift

```python
L.call(func, *args)                    # Lift sync/async call
L.call_catching(func, on_error, *args) # Lift with error mapping
L.up.pure(value)                       # Lift value
L.up.fail(error)                       # Lift error
```

### Flow

```python
pipeline = (
    flow(L.call_catching(api.get, on_error=map_error, key=key))
    .retry(times=3)
    .timeout(seconds=2.0)
    .compile()
)

result = await pipeline  # Result[T, E | TimeoutError]
```

### Combinators

```python
from combinators import fallback_chain, race_ok, parallel, traverse_par

result = await fallback_chain(primary, secondary, L.up.pure(DEFAULT))
result = await race_ok(provider_a, provider_b)
results = await parallel(op1, op2, op3)
results = await traverse_par(items, process, concurrency=10)
```

---

## kungfu

### Result

```python
async def get_user(uid: int) -> Result[User, NotFoundError]:
    user = await db.get(uid)
    return Ok(user) if user else Error(NotFoundError(uid))

match await get_user(42):
    case Ok(user): return user
    case Error(e): handle(e)
```

### Methods

```python
result.map(f)        # Transform Ok value
result.map_err(f)    # Transform Error value
result.unwrap()      # Get value or raise
result.unwrap_or(d)  # Get value or default
result.is_ok()       # Check success
result.is_err()      # Check failure
```

---

## Common Patterns

### Cache Inside Node

```python
@G.node
class ProfileNode:
    @classmethod
    async def __compose__(cls, cart: CartNode) -> ProfileNode:
        result = await profile_cache.get(cart.data.user_id)
        return cls(result.unwrap().value)
```

### Saga Inside Node

```python
@G.node
class PaymentSagaNode:
    @classmethod
    async def __compose__(cls, totals: TotalsNode) -> PaymentSagaNode:
        saga = (
            S.step(
                action=L.catching_async(
                    lambda: reserve(totals.items),
                    on_error=lambda e: Err(str(e)),
                ),
                compensate=lambda res: release(res.id),
            )
            .then(lambda _: S.step(
                action=L.catching_async(
                    lambda: charge(totals.amount),
                    on_error=lambda e: Err(str(e)),
                ),
                compensate=lambda pay: refund(pay.id),
            ))
        )
        result = await S.run_chain(saga)
        return cls(result.unwrap().value)
```

### Resilient Fetch

```python
fetch = (
    flow(L.call_catching(api.get, on_error=map_error, key=key))
    .retry(times=3)
    .timeout(seconds=2.0)
    .compile()
)

result = await fallback_chain(fetch, cache, L.up.pure(DEFAULT))
```

### Parallel Items

```python
@G.node
class ItemsNode:
    @classmethod
    async def __compose__(cls, cart: CartNode) -> ItemsNode:
        items = await traverse_par(cart.data.items, catalog.get, concurrency=10)
        return cls(items.unwrap())
```

---

## Golden Rules

1. **Types as specs** — `Result[T, E]` documents all failure modes
2. **Errors as values** — no exceptions for business logic
3. **Topology over instructions** — `__compose__` signature = dependency graph
4. **Parallel by default** — independent nodes run concurrently
5. **Protocol for DI** — swap implementations at runtime
6. **Saga for rollback** — compensation is explicit
7. **Cache for latency** — tier-based, declarative

# Guide

Building a checkout system with the full stack.

---

## The Stack

```
YOUR CODE       ─── business logic, invariants (Level 6)
emergent.graph  ─── topology, parallelization (Level 5)
emergent.saga   ─── distributed transactions (Level 5)
emergent.cache  ─── multi-tier caching (Level 5)
nodnod          ─── dependency graphs (Level 4)
combinators.py  ─── retry, timeout, fallback (Level 3)
kungfu          ─── Result[T, E], explicit errors (Level 2)
```

You write Level 6. The stack handles everything below.

---

## Step 1: Explicit Errors (kungfu)

Start with honest types:

```python
from kungfu import Result, Ok, Error

@dataclass(frozen=True)
class NotFoundError(Exception):
    entity: str
    id: int

async def get_user(uid: int) -> Result[User, NotFoundError]:
    user = await db.get(uid)
    return Ok(user) if user else Error(NotFoundError("User", uid))
```

Now the signature says exactly what can fail.

---

## Step 2: Resilience (combinators.py)

Add retry, timeout, fallback:

```python
from combinators import flow, lift as L

fetch_user = (
    flow(L.call_catching(api.get_user, on_error=map_error, uid=uid))
    .retry(times=3)
    .timeout(seconds=2.0)
    .compile()
)

result = await fetch_user
```

Resilience is composition, not configuration.

---

## Step 3: Caching (emergent.cache)

**Key concepts:**
- `Tier` = storage backend (global, inject via DI)
- `Cache` = declarative builder (per-use-case, type-safe)
- Tiers **stack**: `.tier(L1).tier(L2)` = L1/L2 cache pattern

```python
from emergent import cache as C
from combinators import lift as L

# Tiers are global backends
local = C.LocalTier(max_size=10000)  # L1: per-instance, fast
redis = RedisTier(client, ttl=300)   # L2: shared (your impl)

# Fetch function
def fetch_user(uid: UserId) -> LazyCoroResult[User, NotFoundError]:
    return L.catching_async(
        lambda: repo.get_user(uid.value),
        on_error=lambda e: NotFoundError("User", uid.value),
    )

# Cache builder — stacks tiers
user_cache = (
    C.cache(key=lambda uid: f"user:{uid.value}", fetch=fetch_user)
    .tier(local)   # check first
    .tier(redis)   # check second
    .build()
)

result = await user_cache.get(user_id)
# READ:  local → miss → redis → miss → fetch()
# WRITE: fetch() → store in local AND redis
```

**Real app pattern (tiers via DI nodes):**

```python
@G.node
class L1Cache[T]:
    """In-memory per instance — fast, no network."""
    def __init__(self, tier: C.Tier[T]) -> None:
        self.tier = tier
    
    @classmethod
    def __compose__(cls) -> L1Cache[Profile]:
        return cls(C.LocalTier(max_size=10000))

@G.node
class L2Cache[T]:
    """Redis shared across instances."""
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
            .tier(l1.tier)  # L1
            .tier(l2.tier)  # L2
            .build()
        )
        result = await cache.get(cart.user_id)
        return cls(result.unwrap().value)
```

---

## Step 4: Saga (emergent.saga)

Distributed transactions with rollback:

```python
from emergent import saga as S
from combinators import lift as L

checkout = (
    S.step(
        action=L.catching_async(lambda: inventory.reserve(order_id), on_error=ReserveError),
        compensate=lambda res: inventory.release(res.reservation_id),
    )
    .then(lambda res: S.step(
        action=L.catching_async(lambda: payment.authorize(res.amount), on_error=PaymentError),
        compensate=lambda auth: payment.void(auth.id),
    ))
)

result = await S.run_chain(checkout)
# If payment fails → inventory.release runs automatically
```

---

## Step 5: Graph (emergent.graph)

This is the paradigm shift. Programs become **topologies**:

```python
from emergent import graph as G

@G.node
class CartNode:
    def __init__(self, data: Cart) -> None:
        self.data = data

@G.node
class ProfileNode:
    def __init__(self, data: UserProfile) -> None:
        self.data = data

    @classmethod
    async def __compose__(cls, cart: CartNode) -> ProfileNode:
        # Signature declares: ProfileNode depends on CartNode
        result = await user_cache.get(cart.data.user_id)
        return cls(result.unwrap().value)

@G.node
class LoyaltyNode:
    def __init__(self, data: LoyaltyInfo) -> None:
        self.data = data

    @classmethod
    async def __compose__(cls, cart: CartNode) -> LoyaltyNode:
        # Also depends on CartNode, but NOT on ProfileNode
        return cls(await repo.get_loyalty(cart.data.user_id))

@G.node
class CheckoutNode:
    @classmethod
    async def __compose__(
        cls,
        profile: ProfileNode,   # ┐
        loyalty: LoyaltyNode,   # ┘ Framework sees: both depend on CartNode
    ) -> CheckoutNode:          #   Runs them in PARALLEL automatically
        return cls(...)
```

**What happens:**
1. Framework builds graph from type signatures
2. Analyzes dependencies
3. Runs independent nodes in parallel
4. Caches results for reuse

You declare **topology**. Framework handles **execution**.

---

## Step 6: DI with Protocol

Swap implementations at runtime:

```python
from typing import Protocol

class PaymentGateway(Protocol):
    async def authorize(self, amount: int) -> str: ...

class StripePayment:
    async def authorize(self, amount: int) -> str:
        return await stripe.charge(amount)

class MockPayment:
    async def authorize(self, amount: int) -> str:
        return f"mock_{amount}"

@G.node
class PaymentNode:
    @classmethod
    async def __compose__(cls, gateway: PaymentGateway) -> PaymentNode:
        # Depends on abstract PaymentGateway
        return cls(await gateway.authorize(1000))

# Production
await G.run(PaymentNode).inject_as(PaymentGateway, StripePayment())

# Tests
await G.run(PaymentNode).inject_as(PaymentGateway, MockPayment())
```

Same graph. Different bindings. Full type safety.

---

## Step 7: Full Composition

Everything together:

```python
@G.node
class CheckoutNode:
    @classmethod
    async def __compose__(
        cls,
        profile: ProfileNode,      # Cached (uses emergent.cache inside)
        loyalty: LoyaltyNode,      # Parallel with profile
        items: ItemsNode,          # Parallel with both
        tax: TaxNode,              # Depends on items + profile
        saga: CheckoutSagaNode,    # Uses emergent.saga inside
    ) -> CheckoutNode:
        return cls(Order(
            user=profile.data,
            items=items.data,
            total=tax.total,
            auth_code=saga.auth_code,
        ))

    @classmethod
    async def execute(cls, cart: Cart, payment: PaymentGateway) -> Order:
        """Type-safe entry point."""
        node = await (
            G.run(cls)
            .inject(CartNode(cart))
            .inject_as(PaymentGateway, payment)
        )
        return node.data
```

---

## What We Built

| Layer | Library | Pattern |
|-------|---------|---------|
| Errors | kungfu | `Result[T, E]` |
| Resilience | combinators | `flow().retry().timeout()` |
| Caching | emergent.cache | `C.cache().tier().build()` |
| Transactions | emergent.saga | `S.step().then()` |
| Topology | emergent.graph | `@G.node` + `__compose__` |
| DI | Protocol | `inject_as()` |

---

## The Key Insight

Traditional code: **instructions** (do this, then that, then this)

```python
profile = await get_profile(user_id)  # Step 1
loyalty = await get_loyalty(user_id)  # Step 2 (waits for step 1)
items = await get_items(cart)         # Step 3 (waits for step 2)
```

emergent code: **topology** (this depends on that)

```python
@G.node
class ProfileNode:
    @classmethod
    async def __compose__(cls, cart: CartNode) -> ProfileNode: ...

@G.node
class LoyaltyNode:
    @classmethod
    async def __compose__(cls, cart: CartNode) -> LoyaltyNode: ...

@G.node
class ItemsNode:
    @classmethod
    async def __compose__(cls, cart: CartNode) -> ItemsNode: ...
```

Framework sees: all three depend only on `CartNode`. Runs all three in parallel.

---

## The Key Insight (Reprise)

**Level 6 is YOUR business DSL:**

```python
# This IS your domain language
@G.node
class CheckoutNode:
    @classmethod
    async def __compose__(
        cls,
        profile: ProfileNode,   # Cached by Level 5
        loyalty: LoyaltyNode,   # Parallelized by Level 4
        items: ItemsNode,       # Retried by Level 3
        saga: SagaNode,         # Compensated by Level 5
    ) -> CheckoutNode:
        # YOUR BUSINESS RULES HERE
        if loyalty.data.tier == "banned":
            raise FraudError("Banned user")
        if sum(i.amount for i in items.data) > 10000:
            raise LimitError("Order too large")
        return cls(Order(...))
```

You define invariants. You compose services. You don't write retry loops. You don't manage compensators. You don't think about parallelization.

**The paradox**: Declarative APIs look scary at first. Then they're liberating. Because everything is local. Because types are documentation. Because the framework handles everything else.

Juniors write Level 6 on day 2. LLMs generate it reliably. Seniors build Levels 1-5 once.

---

## Next

- See `examples/full_stack/` for working code
- Read `docs/reference.md` for API details
- Read `docs/philosophy.md` for principles

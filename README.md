<div align="center">

# emergent

**Type-safe, composable DSLs for common patterns**

[![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Types: pyright strict](https://img.shields.io/badge/types-pyright%20strict-blue)](https://github.com/microsoft/pyright)

</div>

---

Backend code gets messy fast. Retries here, caching there, rollback logic somewhere in a `finally` block. `emergent` turns these patterns into composable building blocks.

---

## Before & After

**❌ Standard Python: 45 lines of scattered logic**

```python
async def checkout(user_id: int, cart: Cart) -> Order:
    # Fetch user (no caching, sequential)
    profile = await get_profile(user_id)
    loyalty = await get_loyalty(user_id)  # waits for profile
    items = []
    for item in cart.items:
        items.append(await get_item(item.id))  # sequential loop
    
    # Calculate totals
    subtotal = sum(i.price * i.qty for i in items)
    discount = loyalty.discount_percent
    tax = await tax_service.calculate(subtotal, profile.address)
    
    # Reserve inventory (manual rollback)
    reservation = await inventory.reserve(cart.items)
    
    # Charge payment (hope reserve worked)
    try:
        payment = await payment_service.charge(subtotal + tax - discount)
    except PaymentError:
        await inventory.release(reservation)  # manual cleanup
        raise
    
    # Create order (hope charge worked)
    try:
        order = await create_order(profile, items, payment)
    except Exception:
        await payment_service.refund(payment)  # more manual cleanup
        await inventory.release(reservation)
        raise
    
    return order
```

**✅ Emergent: declare topology, not instructions**

```python
from emergent import graph as G, saga as S, cache as C
from combinators import lift as L

@G.node
class ProfileNode:
    @classmethod
    async def __compose__(cls, cart: CartInput) -> ProfileNode:
        result = await profile_cache.get(cart.user_id)
        return cls(result.unwrap().value)

@G.node
class LoyaltyNode:
    @classmethod
    async def __compose__(cls, cart: CartInput) -> LoyaltyNode:
        return cls(await repo.get_loyalty(cart.user_id))

@G.node  
class CheckoutNode:
    @classmethod
    async def __compose__(
        cls,
        profile: ProfileNode,   # ┐
        loyalty: LoyaltyNode,   # ├─ parallel (auto)
        items: ItemsNode,       # ┘
        saga: PaymentSagaNode,  # rollback (auto)
    ) -> CheckoutNode:
        return cls(Order(...))

result = await G.compose(CheckoutNode, cart)
```

**The difference?** One is instructions. The other is a dependency graph the framework optimizes.

---

## What's Inside

| Module | Pattern | One-liner |
|--------|---------|-----------|
| `saga` | Distributed transactions | Steps + compensators. Failure = auto-rollback. |
| `cache` | Multi-tier caching | key → tiers → fetch. Miss = fetch + store. |
| `graph` | Computation graphs | Nodes + deps = parallelization + DI. |

---

## saga

Chain operations with compensation on failure:

```python
from emergent import saga as S
from combinators import lift as L

checkout = (
    S.step(
        action=L.catching_async(
            lambda: inventory.reserve(cart.items),
            on_error=lambda e: InventoryError(str(e)),
        ),
        compensate=lambda res: inventory.release(res.reservation_id),
    )
    .then(lambda res: S.step(
        action=L.catching_async(
            lambda: payment.charge(cart.total),
            on_error=lambda e: PaymentError(str(e)),
        ),
        compensate=lambda pay: payment.refund(pay.transaction_id),
    ))
)

result = await S.run_chain(checkout)
# payment fails → inventory.release(res) runs automatically
```

---

## cache

**Tier** = storage backend (global, inject via DI)  
**Cache** = declarative builder (per-use-case, type-safe)

```python
from emergent import cache as C

# Tiers are global storage backends
local = C.LocalTier(max_size=10000)
redis = RedisTier(client, ttl=300)  # your impl

# Cache builder — per use-case, stacks tiers
user_cache = (
    C.cache(key=lambda uid: f"user:{uid.value}", fetch=fetch_user)
    .tier(local)   # L1: in-memory (fast)
    .tier(redis)   # L2: redis (shared)
    .build()
)

result = await user_cache.get(user_id)
# Lookup: local → redis → fetch
# On miss: fetch → store in ALL tiers
# result.tier = "local" | "redis" | None
```

**Tier stacking = L1/L2 cache pattern:**

```
┌─────────────────────────────────────────────────┐
│ .tier(local).tier(redis)                        │
├─────────────────────────────────────────────────┤
│ READ:  local → miss → redis → miss → fetch()   │
│ WRITE: fetch() → store in local AND redis      │
│ INVALIDATE: remove from local AND redis        │
└─────────────────────────────────────────────────┘
```

**Real app pattern (DI via nodes):**

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
            .tier(l1.tier)  # L1: fast local
            .tier(l2.tier)  # L2: shared redis
            .build()
        )
        result = await cache.get(cart.user_id)
        return cls(result.unwrap().value)
```

---

## graph

Declare dependencies. Framework handles parallelization:

```python
from emergent import graph as G

@G.node
class FetchUser:
    def __init__(self, user: User) -> None:
        self.data = user
    
    @classmethod
    async def __compose__(cls, order: OrderInput) -> FetchUser:
        return cls(await repo.get_user(order.user_id))

@G.node
class FetchItems:
    def __init__(self, items: list[Item]) -> None:
        self.data = items
    
    @classmethod
    async def __compose__(cls, order: OrderInput) -> FetchItems:
        return cls(await repo.get_items(order.item_ids))

@G.node
class ProcessOrder:
    def __init__(self, order: Order) -> None:
        self.data = order
    
    @classmethod
    async def __compose__(
        cls,
        user: FetchUser,   # ┐ no dependency between them
        items: FetchItems, # ┘ → run in parallel
    ) -> ProcessOrder:
        return cls(Order(user.data, items.data))

result = await G.compose(ProcessOrder, order)
```

**DI with Protocol:**

```python
class PaymentGateway(Protocol):
    async def charge(self, amount: int) -> str: ...

@G.node
class Payment:
    def __init__(self, tx_id: str) -> None:
        self.tx_id = tx_id
    
    @classmethod
    async def __compose__(cls, gateway: PaymentGateway) -> Payment:
        return cls(await gateway.charge(1000))

# Production
result = await G.run(Payment).inject_as(PaymentGateway, StripePayment())

# Tests
result = await G.run(Payment).inject_as(PaymentGateway, MockPayment())
```

---

## The Stack

```
┌──────────────────────────────────────────────────────────────┐
│ Level 6: YOUR CODE      — business logic, invariants        │
├──────────────────────────────────────────────────────────────┤
│ Level 5: emergent       — saga, cache, graph                 │
├──────────────────────────────────────────────────────────────┤
│ Level 4: nodnod         — dependency graphs                  │
├──────────────────────────────────────────────────────────────┤
│ Level 3: combinators.py — retry, timeout, fallback           │
├──────────────────────────────────────────────────────────────┤
│ Level 2: kungfu         — Result[T, E]                       │
├──────────────────────────────────────────────────────────────┤
│ Level 1: Python 3.13    — type unions, Protocol              │
└──────────────────────────────────────────────────────────────┘
```

Each level does one thing. Use what you need.

---

## Why It Works for Juniors and LLMs

Declarative APIs look scary at first. Then they're liberating.

**Why juniors succeed:**
- No hidden state to understand
- Dependencies are in the signature
- Pyright catches mistakes before runtime
- Same patterns everywhere

**Why LLMs succeed:**
- Constrained grammar → fewer ways to be wrong
- Type signatures are specifications
- Add a feature = add a node + an edge

```python
# Junior writes this on day 2:
@G.node
class MyFeature:
    @classmethod
    async def __compose__(cls, user: UserNode, config: ConfigNode) -> MyFeature:
        return cls(...)  # framework handles the rest
```

---

## Installation

```bash
uv add git+https://github.com/prostomarkeloff/emergent.git
```

---

## Documentation

| Document | Purpose |
|----------|---------|
| [Philosophy](docs/philosophy.md) | Core principles |
| [Guide](docs/guide.md) | Build a checkout system step by step |
| [Reference](docs/reference.md) | API reference |

---

## Dependencies

| Library | Purpose |
|---------|---------|
| [kungfu](https://github.com/timoniq/kungfu) | `Result`, `Option`, `LazyCoroResult` |
| [combinators.py](https://github.com/prostomarkeloff/combinators.py) | `retry`, `timeout`, `fallback` |
| [nodnod](https://github.com/timoniq/nodnod) | Dependency graphs |

---

## Try It

```bash
cd emergent && uv run python -m examples.full_stack.main
```

```
> checkout 1 CABLE:2
  [Cache] profile HIT
  [Saga] reserve → charge
  ✓ Order ORD-0001
```

---

<div align="center">

**Declare topology. Let the framework optimize.**

</div>

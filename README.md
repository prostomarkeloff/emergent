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
| `idempotency` | Exactly-once execution | Deduplicate concurrent calls. TTL + stores. |

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

## idempotency

Make side‑effectful operations run exactly once per key — even with retries, timeouts, or concurrent requests.

```python
from emergent import idempotency as I
from combinators import lift as L
from kungfu import Ok, Error

def charge(order_id: str):
    async def impl() -> str:  # tx id from provider
        return "tx_123"
    return L.catching_async(impl, on_error=str)

executor = (
    I.idempotent(charge)
    .key(lambda oid: f"payment:{oid}")
    .policy(I.Policy().with_ttl(hours=1))
    .build()
)

match await executor.run("order-123"):
    case Ok(r):
        print(r.value, r.from_cache)  # True on retries
    case Error(e):
        print(e.kind.name, e.message)
```

What it guarantees
- One key → one result until TTL expires.
- Concurrency policy: WAIT (default), FAIL, or FORCE.
- Failures: store for a TTL or drop to allow retries.
- Optional input fingerprint (via graph API) to detect key collisions.

SQLAlchemy in 60 seconds

```python
from dataclasses import dataclass
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
from emergent.idempotency import IdempotencyMixin, SQLAlchemyStore, IdempotencyStatus

# 1) Model with IdempotencyMixin
class OrderTable(Base, IdempotencyMixin):
    __tablename__ = "orders"
    id: Mapped[str] = mapped_column(primary_key=True)
    # ... your fields ...

# 2) Pending payload for creation
@dataclass(frozen=True)
class OrderPending:
    order_id: str
    customer_id: str
    amount_cents: int

# 3) Store factory
store = SQLAlchemyStore[OrderTable, OrderPending](
    session_factory=my_session_factory,
    model=OrderTable,
    to_pending=lambda key, p: OrderTable(
        id=p.order_id,
        idempotency_key=key,
        idempotency_status=IdempotencyStatus.PROCESSING,
        customer_id=p.customer_id,
        amount_cents=p.amount_cents,
        created_at=datetime.now(),
    ),
    to_insert=lambda m: sqlite_insert(OrderTable)
        .values(...)
        .on_conflict_do_nothing(index_elements=["idempotency_key"]),
)

# 4) Execute idempotently
pending = OrderPending(order_id="ord_1", customer_id="c_1", amount_cents=9999)
executor = (
    I.idempotent(process_payment)
    .key(lambda req: req.idempotency_key)
    .store(store.with_pending(pending))
    .build()
)
```

Notes:
- Key collisions: advanced mode supports input fingerprinting via graph API (`IdempotencySpec.input_hash`).
- Stores: use `MemoryStore` for tests; use `SQLAlchemyStore` (or implement `Store[T]`) in production.
- Errors: `IdempotencyError.kind` helps distinguish CONFLICT, TIMEOUT, STORE_ERROR, etc.

Domain‑driven (nodes + DI)
Treat DB idempotency as part of your domain. Build a store node once, derive pending data from the request, and assemble an executor in a use‑case node.

```python
from dataclasses import dataclass
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from emergent import graph as G
from emergent import idempotency as I
from kungfu import Ok, Error
from combinators import lift as L

# Domain I/O
@dataclass(frozen=True)
class CreateOrderRequest:
    idempotency_key: str
    customer_id: str
    amount_cents: int

@dataclass(frozen=True)
class OrderPending:
    order_id: str
    customer_id: str
    amount_cents: int

# 1) Domain store node (SQLAlchemy-backed)
@G.node
class OrderStore:
    def __init__(self, store: I.SQLAlchemyStore):
        self.value = store

    @classmethod
    def __compose__(cls, sessions: async_sessionmaker[AsyncSession]) -> "OrderStore":
        store = I.SQLAlchemyStore(
            session_factory=sessions,
            model=OrderTable,  # your model with IdempotencyMixin
            to_pending=lambda key, p: OrderTable(
                id=p.order_id,
                idempotency_key=key,
                idempotency_status=I.IdempotencyStatus.PROCESSING,
                customer_id=p.customer_id,
                amount_cents=p.amount_cents,
                created_at=datetime.now(),
            ),
            to_insert=lambda m: sqlite_insert(OrderTable)
                .values(
                    id=m.id,
                    idempotency_key=m.idempotency_key,
                    idempotency_status=m.idempotency_status,
                    customer_id=m.customer_id,
                    amount_cents=m.amount_cents,
                    created_at=m.created_at,
                )
                .on_conflict_do_nothing(index_elements=["idempotency_key"]),
        )
        return cls(store)

# 2) Centralized policy node
@G.node
class PaymentPolicy:
    def __init__(self, value: I.Policy):
        self.value = value

    @classmethod
    def __compose__(cls) -> "PaymentPolicy":
        return cls(I.Policy().with_ttl(hours=1).with_on_pending(I.WAIT))

# 3) Pending builder from request
@G.node
class BuildPending:
    def __init__(self, value: OrderPending):
        self.value = value

    @classmethod
    def __compose__(cls, req: CreateOrderRequest) -> "BuildPending":
        return cls(OrderPending(
            order_id=f"ord_{req.idempotency_key}",
            customer_id=req.customer_id,
            amount_cents=req.amount_cents,
        ))

# 4) Operation wrapped as LazyCoroResult
def charge(req: CreateOrderRequest):
    async def impl() -> str:
        return "tx_123"
    return L.catching_async(impl, on_error=str)

# 5) Use-case node assembles the executor and runs it
@G.node
class CreateOrderUseCase:
    def __init__(self, key: str, ok: I.IdempotencyResult[str] | None, err: I.IdempotencyError[str] | None):
        self.key, self.ok, self.err = key, ok, err

    @classmethod
    async def __compose__(
        cls,
        req: CreateOrderRequest,
        store: OrderStore,
        pending: BuildPending,
        policy: PaymentPolicy,
    ) -> "CreateOrderUseCase":
        executor = (
            I.idempotent(charge)
            .key(lambda r: f"payment:{r.idempotency_key}")
            .store(store.value.with_pending(pending.value))
            .policy(policy.value)
            .build()
        )
        r = await executor.run(req)
        match r:
            case Ok(ok):
                return cls(ok.key, ok, None)
            case Error(err):
                return cls(req.idempotency_key, None, err)

# Bootstrap: pre-compile graph and inject infra once per process
pipeline = G.graph(CreateOrderUseCase)
runner = pipeline.run().inject(my_async_session_factory)  # reuse this

# Per request: provide request input (runner keeps the infra injection)
out = await runner.given(CreateOrderRequest("k1", "c1", 9999))
out2 = await runner.given(CreateOrderRequest("k2", "c2", 1999))
```

Runner patterns:
- Reuse runner (above) when you handle many requests in the same process.
- Or inject the same session factory per request — it’s cheap and still uses the pooled engine:

```python
out = await pipeline.run() \
    .inject(my_async_session_factory) \
    .given(CreateOrderRequest("k3", "c3", 4999))
```

Infra notes:
- Engine: create once per process (`create_async_engine(...)`).
- Session factory: safe to reuse or inject per request — it’s a light handle over the same engine.
- Sessions: open/close per request inside the store/service.
- MemoryStore: use a shared singleton; Redis/clients: share the client, build Store wrappers freely.

Why this design:
- DB idempotency lives in the domain: the store node owns mapping and conflict rules.
- Executors don’t touch DB details; they only receive `store.with_pending(...)` and policy.
- Swap store implementations per bounded context without changing call sites.

Infra stores (Memory/Redis)
- Keep a single MemoryStore per process, or share a Redis client.
- Build small Store wrappers; inject them via nodes/DI instead of recreating clients.

---

## The Stack

```
┌──────────────────────────────────────────────────────────────┐
│ Level 6: YOUR CODE      — business logic, invariants         │
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

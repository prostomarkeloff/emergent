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
# Assume domain types/services already exist:
# Cart, Order, get_profile, get_loyalty, get_item, tax_service,
# inventory, payment_service, create_order, PaymentError

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
from dataclasses import dataclass
from emergent import ops as O, saga as S
from kungfu import Result, Ok, Error

# Ops
@dataclass(frozen=True, slots=True)
class GetProfile(O.Returning[Profile, str]):
    user_id: int

@dataclass(frozen=True, slots=True)
class GetItems(O.Returning[list[Item], str]):
    cart: Cart

@dataclass(frozen=True, slots=True)
class PaymentFlow(O.Returning[str, str]):  # returns tx id
    items: GetItems  # Op dependency → runs first, then awaited as cached

@dataclass(frozen=True, slots=True)
class BuildCheckout(O.Returning[Order, str]):
    cart: Cart
    profile: GetProfile
    items: GetItems
    payment: PaymentFlow

# Handlers
async def get_profile_op(req: GetProfile, repo: Repo) -> Result[Profile, str]:
    p = await repo.get_profile(req.user_id)
    return Ok(p) if p else Error("profile not found")

async def get_items_op(req: GetItems, repo: Repo) -> Result[list[Item], str]:
    items = await repo.get_items(req.cart)
    return Ok(items) if items else Error("no items")

async def payment_flow_op(
    req: PaymentFlow,
    items: GetItems,               # awaited → cached Result
    inventory: Inventory,
    gateway: PaymentGateway,
) -> Result[str, str]:
    match await items:
        case Ok(item_list):
            subtotal = sum(i.price * i.qty for i in item_list)
            flow = S.from_async(
                lambda: inventory.reserve(item_list),
                on_error=lambda e: f"reserve: {e}",
                compensate=lambda r: inventory.release(r),
            ).then(lambda r: S.from_async(
                lambda: gateway.charge(subtotal),
                on_error=lambda e: f"charge: {e}",
                compensate=lambda tx: gateway.refund(tx),
            ))
            match await S.run_chain(flow):
                case Ok(ok): return Ok(ok.value)   # tx id
                case Error(_): return Error("payment failed")
        case Error(e):
            return Error(e)

async def build_checkout_op(
    req: BuildCheckout,
    profile: GetProfile,
    items: GetItems,
    payment: PaymentFlow,
) -> Result[Order, str]:
    p, i, tx = await profile, await items, await payment
    match (p, i, tx):
        case (Ok(profile), Ok(items), Ok(tx_id)):
            return Ok(Order(profile, items, tx_id))
        case _:
            return Error("checkout failed")

# Wire and run — the framework analyzes dependencies and parallelizes
runner = (
    O.ops()
    .on(GetProfile, get_profile_op)
    .on(GetItems, get_items_op)
    .on(PaymentFlow, payment_flow_op)
    .on(BuildCheckout, build_checkout_op)
).compile() \
 .inject(Repo, repo) \
 .inject(Inventory, inventory) \
 .inject(PaymentGateway, gateway)

result = await runner.run(
    BuildCheckout(
        cart,
        GetProfile(cart.user_id),     # runs in parallel with GetItems
        GetItems(cart),               # cached Result passed to PaymentFlow
        PaymentFlow(GetItems(cart)),  # depends on Items; compensates on failure
    )
)
```

**The difference?** One is instructions. The other is a dependency graph the framework optimizes.

---

## What's Inside

| Module | Pattern | One-liner |
|--------|---------|-----------|
| `ops` | Data-driven dispatch | Replaces match/case. Auto DI + parallelization. |
| `saga` | Distributed transactions | Steps + compensators. Failure = auto-rollback. |
| `cache` | Multi-tier caching | key → tiers → fetch. Miss = fetch + store. |
| `graph` | Computation graphs | Nodes + deps = parallelization + DI. |
| `idempotency` | Exactly-once execution | Deduplicate concurrent calls. TTL + stores. |
| `wire` | Transport-agnostic endpoints | Expose ops via triggers + codecs. |

---

## ops

Data-driven dispatch — replaces `match/case` with declarative registration:

```python
from emergent import ops as O
from kungfu import Result, Ok, Error

@dataclass(frozen=True, slots=True)
class GetUser(O.Returning[User, NotFound]):
    user_id: int

async def get_user(req: GetUser, db: Database) -> Result[User, NotFound]:
    return await db.get(req.user_id)

runner = O.ops().on(GetUser, get_user).compile().inject(Database, db)
result = await runner.run(GetUser(42))
```

**Composition** — operations depending on other operations (auto parallelization):

```python
@dataclass(frozen=True, slots=True)
class BuildSummary(O.Returning[str, str]):
    product_id: int
    price: GetPrice    # dependency
    stock: GetStock    # dependency

async def build_summary(
    req: BuildSummary,
    price: GetPrice,    # has .get() → cached Result
    stock: GetStock,    # has .get() → cached Result
) -> Result[str, str]:
    p = await price  # instant (already computed in parallel)
    s = await stock
    match (p, s):
        case (Ok(pv), Ok(sv)): return Ok(f"${pv}, {sv} units")
        case _: return Error("failed")
```

**Policies** (retry, timeout, idempotency) are achieved via composition with `combinators.py` and other emergent modules: `saga`, `cache`, `idempotency`.

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
from emergent.idempotency.contrib.sqlalchemy import IdempotencyMixin, SQLAlchemyStore, IdempotencyStatus

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

## wire

**Product of Spaces = Leverage.**

Every axis splits into **Semantic × Physical**. The Cartesian product gives you combinatorial power:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Product of Spaces                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   Surface:   Codec × Trigger    →  1 codec, 3 triggers = 3 endpoints        │
│   Storage:   Pattern × Backend  →  1 pattern, 3 backends = 3 storages       │
│   Schema:    Dialect × Compiler →  1 schema, 3 compilers = 3 outputs        │
│   Query:     Expr × Provider    →  1 query, 3 providers = 3 executions      │
│                                                                              │
│   You write the LEFT side. Framework multiplies by the RIGHT.               │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Why this matters:**
- Write 1 `rrc(Request, Response)` codec → expose via HTTP, CLI, Telegram
- Write 1 `@dataclass User` with annotations → generate SQLAlchemy, OpenAPI, Pydantic
- Write 1 `lambda u: u.balance > 0` query → run on SQL, Memory, HTTP API

You don't write N implementations. You write 1 semantic thing, and the product with N physical targets gives you N concrete artifacts.

---

### Wire Axes Architecture

```
wire/axis/
├── surface/     # Codec × Trigger = Endpoint
├── storage/     # Pattern × Backend = Storage
├── schema/      # Dialect × Compiler = Model
└── query/       # Expr × Provider = Execution
```

| Axis | Semantic (what you write) | Physical (framework multiplies) | Product |
|------|---------------------------|--------------------------------|---------|
| **Surface** | Codec (rrc, stateful) | Trigger (http, cli, tg) | endpoint |
| **Storage** | Pattern (KV, Queue) | Backend (memory, redis, sql) | storage |
| **Schema** | Dialect (annotations) | Compiler (sqlalchemy, openapi) | model |
| **Query** | Expression AST | Provider (sql, memory, http) | execution |

**The math:** If you have 2 codecs, 3 triggers, 2 patterns, 3 backends — you get 2×3 + 2×3 = 12 concrete artifacts from 4 semantic definitions.

---

### Schema Axis — Multi-Dialect Annotations

**1 dataclass × N compilers = N outputs.**

Each compiler reads its dialect, ignores others:

```python
from dataclasses import dataclass
from typing import Annotated
from emergent.wire.axis.schema.dialects import cli, openapi

@dataclass
class RegisterRequest:
    """Register new user."""
    login: Annotated[str,
        cli.Help("Username"),           # CLI: argparse help text
        cli.Positional(),               # CLI: positional arg (not --flag)
        openapi.Description("Username for registration"),  # OpenAPI: schema description
    ]
    password: Annotated[str,
        cli.Help("Password"),
        cli.Positional(),
        openapi.Description("Account password"),
    ]

    def to_domain(self) -> Register:
        return Register(login=self.login, password=self.password)
```

**Compiler behavior:**
- FastAPI compiler → reads `openapi.*`, generates OpenAPI schema
- CLI compiler → reads `cli.*`, generates argparse args
- Each ignores unknown dialects (no errors)

**Available dialects:**

| Dialect | Capabilities |
|---------|--------------|
| `cli` | `Help`, `Positional`, `Flag`, `Choices`, `Nargs`, `Env` |
| `openapi` | `Format`, `Description`, `Examples`, `Deprecated`, `ReadOnly` |
| `sql` | `Index`, `Type`, `ServerDefault`, `ForeignKey`, `PrimaryKey` |

---

### Storage Axis — SQLAlchemy Backend

**1 dataclass × SQLAlchemy compiler = complete storage.**

Same dataclass with schema annotations → generates SQLAlchemy model, KV operations, relational queries. Backend does NOT own transactions — caller commits.

```python
from dataclasses import dataclass
from typing import Annotated
from emergent.wire.axis.schema import Identity, Unique, MaxLen
from emergent.wire.axis.storage.contrib import sqlalchemy

@dataclass
class User:
    id: Annotated[int, Identity]
    email: Annotated[str, Unique, MaxLen(255)]
    balance: int

# Store pattern — configure once, use with any session
UserStore = sqlalchemy.store(User, "users")

async with session_factory() as session:
    users = UserStore(session)  # bind to session

    # KV operations
    await users.set(User(id=1, email="alice@example.com", balance=100))
    user = await users.get(1)

    # Relational queries with lambda → AST
    active = await users.find(lambda u: u.balance > 0)
    alice = await users.find_one(lambda u: u.email == "alice@example.com")

    await session.commit()  # Caller commits!
```

**What it generates:**
- SQLAlchemy model class from dataclass + schema annotations
- `Identity` → `primary_key=True`
- `Unique` → `unique=True`
- `MaxLen(n)` → `String(n)`
- `Ref(Target)` → `ForeignKey`

**Inline usage (no pre-configuration):**

```python
async with session_factory() as session:
    users = sqlalchemy.sqlalchemy(session, User, "users")
    await users.set(user)
    await session.commit()
```

---

### The Leverage: eDSL Inside eDSL

Look at `StatefulCodec`. The `__transition__` method signature **IS a DSL**:

```python
async def __transition__(
    self,
    token: Option[HttpToken],      # "try to get token, Nothing if can't"
    bet_input: Option[BetInput],   # "try to get bet, Nothing if can't"
    request: fastapi.Request,      # "I require the raw request"
) -> Self | tuple[Self, Response] | Done:
```

You **declare what you want** in types. The framework **introspects and delivers**:
- `Option[X]` → compose X, wrap failure in `Nothing`
- `Result[X, E]` → compose X, wrap failure in `Error`
- Plain `X` → compose X, fail if can't
- Return type → what can happen next

This is **eDSL layering**:
- Level 1: `application().mount(endpoint().expose())` — structure
- Level 2: `stateful().key().use().build()` — codec config
- Level 3: `__transition__` signature — behavior via types

Each level hides complexity. Each level provides leverage.

**The pattern generalizes.** Codecs can define their own "signature-as-DSL" patterns:

**JobCodec** — async operations that take time:

```python
@dataclass(frozen=True, slots=True)
class JobCodec:
    """Async job pattern: start → poll → result."""
    start: type      # start.to_domain() → Op that returns job_id
    progress: type   # progress type (optional)
    result: type     # final result type
    ttl: timedelta   # how long to keep completed jobs

# User writes ONE declaration. Compiler creates THREE endpoints:
# POST /jobs      → start job, return job_id
# GET /jobs/{id}  → get status + progress
# GET /jobs/{id}/result → get final result (when done)

# The "DSL" is the type declarations + how they compose:
@dataclass
class ImageResizeJob:
    image_url: str
    width: int
    height: int

    def to_domain(self) -> StartResize:
        return StartResize(self.image_url, self.width, self.height)

@dataclass
class ResizeProgress:
    percent: int
    stage: str

@dataclass
class ResizeResult:
    url: str

    @classmethod
    def from_domain(cls, dom: Result[str, str]) -> Self: ...
```

**SubscriptionCodec** — server-push patterns:

```python
@dataclass(frozen=True, slots=True)
class SubscriptionCodec:
    """Subscribe once, receive events until disconnect."""
    subscribe: type   # subscribe.to_domain() → Op that validates subscription
    event: type       # event type pushed to client
    filter: type | None  # optional per-subscriber filter

# The "DSL" is in the subscribe type's __compose__:
@dataclass
class OrderUpdates(DataNode):
    user_id: int
    order_ids: list[str]

    @classmethod
    def __compose__(cls, auth: AuthUser, req: SubscribeRequest) -> Self:
        # Auth user can only subscribe to their own orders
        return cls(user_id=auth.id, order_ids=req.order_ids)

    def to_domain(self) -> ValidateSubscription:
        return ValidateSubscription(self.user_id, self.order_ids)

# Compiler creates SSE/WebSocket endpoint that:
# 1. Composes subscribe type (validates via nodnod)
# 2. Holds connection
# 3. Pushes events matching filter
```

**WizardCodec** — ordered multi-step flows:

```python
@dataclass(frozen=True, slots=True)
class WizardCodec:
    """Ordered steps with validation, back/forward navigation."""
    steps: tuple[type[WizardStep], ...]  # step order
    response: type
    allow_back: bool = True

class WizardStep(Protocol):
    """Each step declares its inputs via __compose__ signature."""
    @classmethod
    def __compose__(cls, ...) -> Self: ...
    def validate(self) -> Result[Self, ValidationError]: ...

# The "DSL" is the step sequence + each step's __compose__:
@dataclass
class ShippingStep(DataNode):
    address: str
    city: str

    @classmethod
    def __compose__(cls, form: ShippingForm) -> Self:
        return cls(address=form.address, city=form.city)

    def validate(self) -> Result[Self, ValidationError]:
        if not self.address:
            return Error(ValidationError("address required"))
        return Ok(self)

@dataclass
class PaymentStep(DataNode):
    card_token: str
    shipping: ShippingStep  # depends on previous step!

    @classmethod
    def __compose__(cls, form: PaymentForm, shipping: ShippingStep) -> Self:
        return cls(card_token=form.token, shipping=shipping)
```

**The insight:** Codecs define **what the user declares** and **what the framework does with it**. The more you can express in type signatures and protocols, the more the framework can introspect and automate.

**What you DON'T write:**
- Polling endpoint boilerplate (JobCodec)
- SSE connection management (SubscriptionCodec)
- Step navigation logic (WizardCodec)
- Progress tracking infrastructure
- Retry/timeout/fallback wiring

**What you DO write:**
- Type declarations with protocols
- `__compose__` signatures that declare dependencies
- Domain ops (pure, tested once)

The framework reads your declarations, compilers produce framework-native implementations. That's the leverage.

---

### Separation of Concerns

Wire separates **three orthogonal axes**:

```
Trigger  = WHERE to listen    (HTTP route, CLI subcommand, bot command)
Codec    = HOW to execute     (request-response, stateful FSM, streaming)
Compiler = WHAT to produce    (FastAPI app, argparse parser, Dispatch)
```

**Endpoint** bundles a runner with exposures. Each exposure is a point in Trigger × Codec space:

```python
endpoint(game_runner).expose(
    HTTPRouteTrigger("POST", "/bet"),
    rrc(BetRequest, BetResponse).use(auth_mw).build(),  # middleware is part of codec
)
```

**Codec owns execution semantics** — including middleware. When you call `.use(auth_mw)`, the middleware becomes part of the codec. The codec's `execute()` function runs everything: middlewares → `to_domain()` → `runner.run()` → `from_domain()`.

**Compiler claims a region** of Trigger × Codec space and produces a framework artifact:

```python
app = application().mount(endpoint1, endpoint2, endpoint3)

# Each compiler scans for its trigger type
fastapi_app = fastapi.from_application(app)   # claims HTTPRouteTrigger
cli_parser = cli.from_application(app)        # claims CLITrigger
tg_dispatch = telegrinder.from_application(app)  # claims TelegrindTrigger
```

---

### Request Types: Transport-Idiomatic

Request types are **different per transport** — each has its idiom, wire lets you use it:

**HTTP — Pydantic models** (body/query parsing, OpenAPI schema):

```python
class BetRequest(BaseModel):
    token: str
    bet: str
    amount: int

    def to_domain(self) -> PlaceBet:
        return PlaceBet(bet=self.bet, amount=self.amount)

    def to_auth(self) -> Authenticate:  # middleware protocol
        return Authenticate(token=self.token)
```

**CLI — dataclass + cli_field** (argparse) **+ DataNode** (DI via compose):

```python
@dataclass
class BetRequest(DataNode):
    login: str  # composed from CLILogin node, not CLI arg
    bet: str = cli_field(help="Bet type: red, black, or number")
    amount: int = cli_field(help="Bet amount")

    @classmethod
    def __compose__(cls, cli_login: CLILogin, ns: argparse.Namespace) -> BetRequest:
        return cls(login=cli_login, bet=ns.bet, amount=ns.amount)

    def to_domain(self) -> PlaceBet:
        return PlaceBet(bet=self.bet, amount=self.amount)
```

**Telegram — DataNode** (compose from telegrinder nodes):

```python
@dataclass
class RegisterRequest(DataNode):
    login: str
    password: str

    @classmethod
    def __compose__(cls, text: Text) -> RegisterRequest:
        parts = str(text).split()
        return cls(login=parts[1], password=parts[2])

    def to_domain(self) -> Register:
        return Register(login=self.login, password=self.password)
```

**The contract:** `to_domain() → Op`. How you parse input is transport-specific. What you produce is universal.

---

### Response Types: Often Shared

Response types implement `from_domain(Result) → Self` — they're often **shared across transports**:

```python
from kungfu import Result, Ok, Error

@dataclass
class BetResponse:
    won: bool | None = None
    number: int | None = None
    payout: int | None = None
    new_balance: int | None = None
    error: str | None = None

    @classmethod
    def from_domain(cls, dom: Result[BetResult, str]) -> BetResponse:
        match dom:
            case Ok(r):
                return cls(won=r.won, number=r.number, payout=r.payout, new_balance=r.new_balance)
            case Error(e):
                return cls(error=e)

    def __str__(self) -> str:  # CLI/Telegram use this
        if self.error:
            return f"Error: {self.error}"
        won = "Won" if self.won else "Lost"
        return f"{won}! Number: {self.number}, Payout: {self.payout}, Balance: {self.new_balance}"
```

**Middleware rejection response:**

```python
@dataclass
class AuthErrorResponse:
    error: str

    @classmethod
    def from_domain(cls, dom: Result[AuthUser, str]) -> AuthErrorResponse:
        match dom:
            case Error(e): return cls(error=e)
            case Ok(_): return cls(error="auth failed")
```

---

### Program Composition — Product in Action

The roulette example (`examples/roulette/`) shows the product:

- **1 runner** × 2 triggers = 2 entry points
- **1 request type** with 2 dialects = works in HTTP + CLI
- **1 response type** = shared across all transports

```python
from emergent.wire import endpoint, Application, inject
from emergent.wire.axis.surface.codecs.rrc import rrc
from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger
from emergent.wire.axis.surface.triggers.cli import CLITrigger
from emergent.wire.compiler import fastapi_compile, cli_compile

# Domain runners (pure, tested once, reused everywhere)
auth_runner = O.ops().on(Register, register_op).on(Login, login_op).compile()
game_runner = O.ops().on(PlaceBet, place_bet_op).compile()

# Middleware — inject AuthUser from request token
http_auth = (
    inject(AuthUser)
        .using(auth_runner)
        .from_request(HasAuth, lambda req: req.to_auth())
        .on_reject(AuthErrorResponse.from_domain)
        .build()
)

# ONE Application — multiple triggers per endpoint
app = Application().mount(
    # Register — public, both HTTP and CLI
    endpoint(auth_runner)
        .expose(HTTPRouteTrigger("POST", "/register"), rrc(RegisterRequest, TokenResponse).build())
        .expose(CLITrigger("register", "Register new user"), rrc(RegisterRequest, TokenResponse).build()),

    # Login — public
    endpoint(auth_runner)
        .expose(HTTPRouteTrigger("POST", "/login"), rrc(LoginRequest, TokenResponse).build())
        .expose(CLITrigger("login", "Login to account"), rrc(LoginRequest, TokenResponse).build()),

    # Bet — requires auth for HTTP
    endpoint(game_runner)
        .expose(HTTPRouteTrigger("POST", "/bet"), rrc(BetRequest, BetResponse).use(http_auth).build())
        .expose(CLITrigger("bet", "Place a bet"), rrc(BetRequest, BetResponse).build()),
)

# Compile to framework-native artifacts
fastapi_app = fastapi_compile(app)         # OpenAPI, async routes
cli_parser = cli_compile(app, prog="roulette")  # argparse, --help
```

**What compilers give you:**
- FastAPI: automatic OpenAPI schema, proper HTTP methods, body/query parsing
- CLI: `argparse` with `--help`, positional args from `cli.Positional()`, exit codes
- Telegrinder: handlers on `Dispatch` views, keyboard flows

**What you don't write:**
- Route registration boilerplate
- Argument parsing setup
- Framework-specific handler wrappers

---

### Clean Code Through Separation

The architecture enforces clean boundaries:

```
┌──────────────────────────────────────────────────────────────────────────┐
│  PURE ZONE (your domain)                                                  │
│  ────────────────────────                                                 │
│  Ops, handlers, runners — no framework imports, no transport knowledge    │
│  Example: PlaceBet op, place_bet_op handler, game_runner                  │
└──────────────────────────────────────────────────────────────────────────┘
                                    ↓
┌──────────────────────────────────────────────────────────────────────────┐
│  WIRE ZONE (your contracts)                                               │
│  ──────────────────────────                                               │
│  Request/Response types with protocols — to_domain(), from_domain()       │
│  Transport-specific parsing, framework-agnostic execution                 │
│  Example: BetRequest(BaseModel), BetRequest(DataNode)                     │
└──────────────────────────────────────────────────────────────────────────┘
                                    ↓
┌──────────────────────────────────────────────────────────────────────────┐
│  COMPILER ZONE (contrib)                                                  │
│  ───────────────────────                                                  │
│  Framework bridges — translate contracts to native constructs             │
│  You don't write this, you use it                                         │
│  Example: fastapi.from_application(), cli.from_application()              │
└──────────────────────────────────────────────────────────────────────────┘
```

Your domain stays pure. Your wiring declares contracts. Compilers handle the framework chaos.

---

### Custom Codecs

Codec = execution semantics. Look at `stateful.py` — it's transport-agnostic. The codec defines **what protocols types must satisfy** and **what the execution lifecycle looks like**. Compilers just configure the scope.

**The pattern:**
1. Define protocols for user's types (what methods they must have)
2. Codec dataclass stores types + config (frozen, slots)
3. Builder validates and constructs
4. Co-located `execute()` defines the lifecycle

**BatchCodec** — process multiple items with parallel/sequential control:

```python
# ─── Protocols ────────────────────────────────────────────────────────────────

Item = TypeVar("Item")
T = TypeVar("T")
E = TypeVar("E")

class BatchItem(Protocol[T, E]):
    """Each item in a batch must produce an Op."""
    def to_domain(self) -> Op[T, E]: ...

class BatchResponse(Protocol[T, E]):
    """Response built from collected results."""
    @classmethod
    def from_batch(cls, results: list[Result[T, E]]) -> Self: ...

# ─── Codec ────────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class BatchCodec(Generic[Item, T, E]):
    """Process multiple items as a batch."""
    item: type[BatchItem[T, E]]      # item.to_domain() → Op
    response: type[BatchResponse[T, E]]  # response.from_batch(results)
    parallel: bool = True

# ─── Execute ──────────────────────────────────────────────────────────────────

async def execute(
    handler: Handler[BatchCodec[Item, T, E]],
    items: list[BatchItem[T, E]],
) -> BatchResponse[T, E]:
    """Batch execution: run all ops, collect results."""
    ops = [item.to_domain() for item in items]

    if handler.codec.parallel:
        results = await asyncio.gather(*[handler.runner.run(op) for op in ops])
    else:
        results = [await handler.runner.run(op) for op in ops]

    return handler.codec.response.from_batch(results)

# ─── Builder ──────────────────────────────────────────────────────────────────

class BatchBuilder(Generic[Item, T, E]):
    def __init__(self, item: type[BatchItem[T, E]], response: type[BatchResponse[T, E]]):
        self._item, self._response, self._parallel = item, response, True

    def sequential(self) -> BatchBuilder[Item, T, E]:
        self._parallel = False
        return self

    def build(self) -> BatchCodec[Item, T, E]:
        return BatchCodec(self._item, self._response, self._parallel)

def batch(item, response) -> BatchBuilder:
    return BatchBuilder(item, response)

# Usage: batch(OrderItem, BatchOrderResponse).sequential().build()
```

**QueueCodec** — message processing with acknowledgment semantics:

```python
# ─── Protocols ────────────────────────────────────────────────────────────────

class QueueMessage(Protocol[T, E]):
    """Message from queue — parse from bytes, produce Op."""
    @classmethod
    def from_bytes(cls, payload: bytes) -> Self: ...
    def to_domain(self) -> Op[T, E]: ...

class AckPolicy(Enum):
    BEFORE = "before"          # Ack before processing (at-most-once)
    AFTER_SUCCESS = "after"    # Ack only on success (at-least-once)
    MANUAL = "manual"          # Handler controls ack via result

# ─── Codec ────────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class QueueCodec(Generic[T, E]):
    """Message queue processing — no response, ack/nack is the result."""
    message: type[QueueMessage[T, E]]
    ack_policy: AckPolicy = AckPolicy.AFTER_SUCCESS
    max_retries: int = 3

# ─── Execute ──────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class QueueResult:
    """What the compiler should do after processing."""
    ack: bool
    requeue: bool = False

async def execute(
    handler: Handler[QueueCodec[T, E]],
    payload: bytes,
) -> QueueResult:
    """Queue execution: process message, return ack decision."""
    msg = handler.codec.message.from_bytes(payload)

    if handler.codec.ack_policy == AckPolicy.BEFORE:
        # At-most-once: ack immediately, then process
        result = await handler.runner.run(msg.to_domain())
        return QueueResult(ack=True)

    result = await handler.runner.run(msg.to_domain())

    match result:
        case Ok(_):
            return QueueResult(ack=True)
        case Error(_):
            return QueueResult(ack=False, requeue=True)

# Compiler bridges this to RabbitMQ/SQS/Kafka acknowledgment APIs
```

**ConnectionCodec** — persistent connection with lifecycle hooks:

```python
# ─── Protocols ────────────────────────────────────────────────────────────────

Ctx = TypeVar("Ctx")  # Connection context (managed by codec)

class OnConnect(Protocol[Ctx, T, E]):
    """Called when connection opens. Can reject via Error."""
    def to_domain(self) -> Op[T, E]: ...

class OnMessage(Protocol[Ctx, T, E]):
    """Called for each message. Ctx available via __compose__."""
    def to_domain(self) -> Op[T, E]: ...

class OnDisconnect(Protocol[Ctx]):
    """Called when connection closes. Cleanup opportunity."""
    def to_domain(self) -> Op[None, None]: ...

# ─── Codec ────────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class ConnectionCodec(Generic[Ctx, T, E]):
    """Connection lifecycle with bidirectional messaging."""
    context: type[Ctx]                      # Connection state type
    on_connect: type[OnConnect[Ctx, T, E]] | None
    on_message: type[OnMessage[Ctx, T, E]]
    on_disconnect: type[OnDisconnect[Ctx]] | None
    push_response: type | None = None       # Server → client message type

# Compiler implements the lifecycle:
# 1. Connection opens → on_connect.to_domain() → Ok = accept, Error = reject
# 2. Message arrives → on_message.to_domain() → result may contain pushes
# 3. Connection closes → on_disconnect.to_domain() → cleanup
#
# Context is injected into scope, so on_message can compose from it:
#
#     @dataclass
#     class ChatMessage(DataNode):
#         text: str
#         @classmethod
#         def __compose__(cls, ctx: ChatContext, raw: RawMessage) -> Self:
#             return cls(text=raw.text)
```

The codec is **transport-agnostic**. A WebSocket compiler and an SSE compiler can both use `ConnectionCodec` — they just configure the scope differently and bridge to their framework's connection API.

---

### Custom Compilers

A compiler scans for its trigger type and bridges to a target framework:

```python
from emergent.wire._scan import scan
from emergent.wire.codecs.rrc import RequestResponseCodec, execute as rrc_execute

def from_application(app: Application) -> DjangoUrlConf:
    """Compile wire Application to Django URL configuration."""
    urls = []

    for trigger, handler in scan(app, DjangoRouteTrigger, RequestResponseCodec):
        async def view(request, trigger=trigger, handler=handler):
            # Bridge Django request → wire request
            wire_request = handler.codec.request(**parse_django_request(request))
            # Execute the full pipeline (middlewares, to_domain, run, from_domain)
            response = await rrc_execute(handler, wire_request)
            # Bridge wire response → Django response
            return JsonResponse(dataclasses.asdict(response))

        urls.append(path(trigger.route, view))

    return urls
```

**The pattern:**
1. `scan(app, YourTrigger, CodecType)` → list of `(trigger, handler)` pairs
2. For each pair, build a framework-native handler that:
   - Parses framework input → wire request type
   - Calls `codec.execute(handler, request)` — this runs the full pipeline
   - Converts wire response → framework output
3. Register on the framework artifact

**What you can build:**
- Django compiler (URL conf from triggers)
- gRPC compiler (service definitions from triggers)
- Cron compiler (scheduled jobs from time-based triggers)
- OpenAPI generator (introspect codecs, produce spec without runtime)
- Test harness (direct handler invocation, no network)
- GraphQL compiler (resolvers from triggers)

The codec's `execute()` IS the business logic pipeline. Your compiler just bridges I/O.

---

### AppStack: Hierarchical Composition

For nested command structures (like `git remote add`):

```python
main_app = application().mount(...)   # top-level commands
new_app = application().mount(...)    # subcommands under "new"

stack = app_stack().root(main_app).mount("new", new_app)

# CLI compiler produces:
#   cli scan    (from main_app)
#   cli new op  (from new_app under "new" prefix)
```

Compilers that support `AppStack` use `scan_stack()` which returns a tree structure.

---

### Quick Example

```python
from dataclasses import dataclass
from typing import Annotated
from emergent import ops as O
from emergent.wire import endpoint, Application
from emergent.wire.axis.surface.codecs.rrc import rrc
from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger
from emergent.wire.axis.schema.dialects import openapi
from emergent.wire.compiler import fastapi_compile

# Domain (pure)
runner = O.ops().on(GetUser, get_user_handler).compile()

# Request with multi-dialect annotations
@dataclass
class GetUserRequest:
    user_id: Annotated[int, openapi.Description("User ID to fetch")]

    def to_domain(self) -> GetUser:
        return GetUser(user_id=self.user_id)

# Application
app = Application().mount(
    endpoint(runner).expose(
        HTTPRouteTrigger("GET", "/users/{user_id}"),
        rrc(GetUserRequest, UserResponse).build(),
    )
)

# Compile
fastapi_app = fastapi_compile(app)
```

Run with `uvicorn module:fastapi_app --reload` — you get OpenAPI at `/docs` for free.

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

**Roulette example — unified multi-transport app:**

```bash
# FastAPI (OpenAPI at /docs)
uvicorn examples.roulette.wiring:fastapi_app --reload

# CLI commands
python -m examples.roulette register alice secret
python -m examples.roulette login alice secret
python -m examples.roulette bet red 100
```

**Full stack example:**

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

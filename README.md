<div align="center">

# emergent

**Type-safe, composable DSLs for common patterns**

[![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Types: pyright strict](https://img.shields.io/badge/types-pyright%20strict-blue)](https://github.com/microsoft/pyright)

</div>

---

## The Insight

**Semantic × Physical = Pipeline.**

Every system has two orthogonal dimensions:
- **Semantic** — WHAT you express (the grammar)
- **Physical** — WHERE it materializes (the target)

You write the semantic side. The framework multiplies by physical targets:

```
1 codec   × 3 triggers  = 3 endpoints
1 pattern × 3 backends  = 3 storages
1 schema  × 3 compilers = 3 outputs
1 query   × 3 providers = 3 executions
```

---

## The Four Axes

| Axis | Semantic | Physical | Product |
|------|----------|----------|---------|
| **Surface** | Codec (execution shape) | Trigger (entry point) | endpoint |
| **Storage** | Pattern (KV, Queue) | Backend (memory, redis) | storage |
| **Schema** | Dialect (annotations) | Compiler (sql, openapi) | model |
| **Query** | Space (operations) | Provider (sql, memory) | store |

```python
# Same Codec, different Triggers → 3 endpoints
rrc(Request, Response) × HTTP     → HTTP endpoint
rrc(Request, Response) × CLI      → CLI command
rrc(Request, Response) × Telegram → Bot handler

# Same Space, different Providers → 2 stores
relational(User) × SQLProvider    → SQL repository
relational(User) × MemoryProvider → In-memory (tests)
```

---

## What's Inside

| Module | Pattern | One-liner |
|--------|---------|-----------|
| `ops` | Data-driven dispatch | Op dataclass → handler → runner.run(op) |
| `saga` | Distributed transactions | Steps + compensators. Failure = auto-rollback. |
| `cache` | Multi-tier caching | key → tiers → fetch. Miss = fetch + store. |
| `graph` | Computation graphs | Nodes + deps = parallelization + DI. |
| `idempotency` | Exactly-once execution | Deduplicate concurrent calls. TTL + stores. |
| `wire` | Transport-agnostic endpoints | 4 axes compose into production stacks. |

---

## ops

Data-driven dispatch — declare ops, register handlers, run:

```python
from emergent import ops as O
from kungfu import Result, Ok

@dataclass(frozen=True, slots=True)
class GetUser(O.Returning[User, NotFound]):
    user_id: int

async def get_user(req: GetUser, db: Database) -> Result[User, NotFound]:
    return await db.get(req.user_id)

runner = O.ops().on(GetUser, get_user).compile().inject(Database, db)
result = await runner.run(GetUser(42))
```

**Composition** — op fields typed as other ops become dependencies (auto-parallelized):

```python
@dataclass(frozen=True, slots=True)
class BuildSummary(O.Returning[str, str]):
    product_id: int
    price: GetPrice    # runs in parallel
    stock: GetStock    # runs in parallel

async def build_summary(req: BuildSummary, price: GetPrice, stock: GetStock) -> Result[str, str]:
    p, s = await price, await stock  # instant — already computed
    return Ok(f"${p.unwrap()}, {s.unwrap()} units")
```

---

## saga

Chain operations with compensation on failure:

```python
from emergent import saga as S

checkout = (
    S.step(
        action=lambda: inventory.reserve(items),
        compensate=lambda res: inventory.release(res),
    )
    .then(lambda res: S.step(
        action=lambda: payment.charge(total),
        compensate=lambda pay: payment.refund(pay),
    ))
)

result = await S.run_chain(checkout)
# payment fails → inventory.release() runs automatically
```

---

## cache

Multi-tier caching with automatic population:

```python
from emergent import cache as C

local = C.LocalTier(max_size=10000)
redis = RedisTier(client, ttl=300)

user_cache = (
    C.cache(key=lambda uid: f"user:{uid}", fetch=fetch_user)
    .tier(local)   # L1: in-memory
    .tier(redis)   # L2: shared
    .build()
)

result = await user_cache.get(user_id)
# Lookup: local → redis → fetch
# Miss: fetch → store in ALL tiers
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
    @classmethod
    async def __compose__(
        cls,
        user: FetchUser,   # ┐ no dependency between them
        items: FetchItems, # ┘ → run in parallel
    ) -> ProcessOrder:
        return cls(Order(user.data, items.data))

result = await G.compose(ProcessOrder, order)
```

---

## idempotency

Make side-effectful operations run exactly once per key:

```python
from emergent import idempotency as I

executor = (
    I.idempotent(charge)
    .key(lambda req: f"payment:{req.order_id}")
    .policy(I.Policy().with_ttl(hours=1))
    .build()
)

match await executor.run(request):
    case Ok(r): print(r.value, r.from_cache)  # True on retries
    case Error(e): print(e.kind.name, e.message)
```

---

## wire

The binding layer. Four axes compose into production stacks.

### Surface Axis: Codec × Trigger = Endpoint

**Codecs** define execution shapes:
- `rrc` — request → response (classic REST)
- `stateful` — multi-turn FSM (accumulate → Done → execute)

**Triggers** define entry points:
- `HTTPRouteTrigger("POST", "/bet")` — REST endpoint
- `CLITrigger("bet", "Place a bet")` — CLI command

```python
from emergent.wire import endpoint, Application
from emergent.wire.axis.surface.codecs.rrc import rrc
from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger
from emergent.wire.axis.surface.triggers.cli import CLITrigger
from emergent.wire.contrib import fastapi, cli

# Request with to_domain()
@dataclass
class BetRequest:
    bet: str
    amount: int

    def to_domain(self) -> PlaceBet:
        return PlaceBet(bet=self.bet, amount=self.amount)

# Response with from_domain()
@dataclass
class BetResponse:
    won: bool | None = None
    error: str | None = None

    @classmethod
    def from_domain(cls, dom: Result[BetResult, str]) -> BetResponse:
        match dom:
            case Ok(r): return cls(won=r.won)
            case Error(e): return cls(error=e)

# ONE runner × multiple triggers
app = Application().mount(
    endpoint(game_runner)
        .expose(HTTPRouteTrigger("POST", "/bet"), rrc(BetRequest, BetResponse).build())
        .expose(CLITrigger("bet", "Place a bet"), rrc(BetRequest, BetResponse).build()),
)

# Compile to production stacks
fastapi_app = fastapi.from_application(app)  # OpenAPI at /docs
cli_parser = cli.from_application(app, prog="game")  # argparse with --help
```

### Query Axis: Space × Provider = Store

Spaces have their own query languages. Providers execute them:

```python
from emergent.wire.axis.query import relational, relational_store, MemoryRelationalProvider

# Low-level: QuerySet + Provider separate
users = relational(User)
q = users.filter(lambda u: u.balance > 100).order_by(lambda u: u.balance.desc())
result = await provider.fetch_many(q)

# High-level: Store bundles them
users = relational_store(User, MemoryRelationalProvider())
result = await users.filter(lambda u: u.active).fetch_many()
```

Lambda expressions build typed AST:
```python
.filter(lambda u: u.balance > 100)
# → Filter(Gt(Field("balance"), Const(100)))
# → SQL: WHERE balance > 100
# → Memory: [u for u in users if u.balance > 100]
```

### Storage Axis: Pattern × Backend = Storage

Capabilities are grammar. Patterns are sentences:

```python
from emergent.wire.axis.storage import kv, MemoryStorage, JsonCodec

# KV pattern = Get + Set + Delete + Codec
cache = kv(MemoryStorage(), JsonCodec())

await cache.set("user:42", user)
user = await cache.get("user:42")
```

### Schema Axis: Dialect × Compiler = Model

One dataclass, multiple outputs via Annotated:

```python
from emergent.wire.axis.schema.dialects import cli, openapi

@dataclass
class RegisterRequest:
    login: Annotated[str,
        cli.Help("Username"),
        cli.Positional(),
        openapi.Description("Username for registration"),
    ]
    password: Annotated[str,
        cli.Help("Password"),
        openapi.Description("Account password"),
    ]
```

Each compiler reads its dialect, ignores others:
- FastAPI compiler → reads `openapi.*`, generates OpenAPI schema
- CLI compiler → reads `cli.*`, generates argparse args

---

## The Stack

```
┌──────────────────────────────────────────────────────────┐
│ Level 5: YOUR CODE      — business logic, invariants     │
├──────────────────────────────────────────────────────────┤
│ Level 4: emergent       — saga, cache, graph, wire       │
├──────────────────────────────────────────────────────────┤
│ Level 3: nodnod         — dependency graphs              │
├──────────────────────────────────────────────────────────┤
│ Level 2: combinators.py — retry, timeout, fallback       │
├──────────────────────────────────────────────────────────┤
│ Level 1: kungfu         — Result[T, E]                   │
├──────────────────────────────────────────────────────────┤
│ Level 0: Python 3.13    — type unions, Protocol          │
└──────────────────────────────────────────────────────────┘
```

Each level does one thing. Use what you need.

---

## Installation

```bash
uv add git+https://github.com/prostomarkeloff/emergent.git
```

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
uv run python -m examples.full_stack.main
```

---

<div align="center">

**Declare topology. Let the framework optimize.**

</div>

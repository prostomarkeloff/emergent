<div align="center">

# emergent

**Type-safe DSLs for common patterns**

[![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Types: pyright strict](https://img.shields.io/badge/types-pyright%20strict-blue)](https://github.com/microsoft/pyright)

</div>

---

# Quickstart

```bash
uv add git+https://github.com/prostomarkeloff/emergent.git
```

Create `app.py` — 3 dataclasses, 15 endpoints, zero controllers:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from emergent.wire.axis.schema import Identity, Unique
from emergent.wire.compile import targets

from derivelib import derive, build_application_from_decorated, memory_node
from derivelib.patterns.crud import http_crud

Users = memory_node()
Posts = memory_node()
Comments = memory_node()


@derive(http_crud("/users", provider_node=Users))
@dataclass
class User:
    id: Annotated[int, Identity]
    name: str
    email: Annotated[str, Unique]


@derive(http_crud("/posts", provider_node=Posts))
@dataclass
class Post:
    id: Annotated[int, Identity]
    title: str
    body: str
    author_id: int


@derive(http_crud("/comments", provider_node=Comments))
@dataclass
class Comment:
    id: Annotated[int, Identity]
    post_id: int
    text: str


app = build_application_from_decorated(User, Post, Comment)
fastapi_app = targets.fastapi.compile(app)
```

15 REST endpoints. Full CRUD. Pydantic validation. OpenAPI schema. RFC 7807 errors.

```bash
uvicorn app:fastapi_app --reload
# Open http://localhost:8000/docs

curl http://localhost:8000/users
curl -X POST http://localhost:8000/users -H 'Content-Type: application/json' \
     -d '{"name": "Alice", "email": "alice@example.com"}'
curl http://localhost:8000/users/1
```

> Full runnable example: `derivelib/examples/crud.py`

---

# Part 1: Build

Four levels of wiring — from fully derived to fully manual. Choose the level that fits.

---

## Level 1: Pure Algebra — one dataclass, one decorator

From `derivelib/examples/multi_target.py` — one entity, HTTP + CLI:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from emergent.wire.axis.schema import Identity

from derivelib import derive, build_application_from_decorated, memory_node
from derivelib.patterns.crud import http_crud, cli_crud

Store = memory_node()

@derive(
    http_crud("/products", provider_node=Store),
    cli_crud("product", provider_node=Store),
)
@dataclass
class Product:
    id: Annotated[int, Identity]
    name: str
    price: float
    in_stock: bool = True

app = build_application_from_decorated(Product)
```

```bash
# HTTP
uv run python -m derivelib.examples.multi_target http
curl http://localhost:8000/products

# CLI
uv run python -m derivelib.examples.multi_target cli product-create laptop 999.99
uv run python -m derivelib.examples.multi_target cli product-list
```

Transforms compose via `.chain()` — from `derivelib/examples/query_transforms.py`:

```python
from derivelib import paginated, sorted_list, filtered, searchable

@derive(
    http_crud("/books", provider_node=Books)
        .chain(paginated())
        .chain(sorted_list())
        .chain(filtered("genre", "author"))
        .chain(searchable("title", "author"))
)
@dataclass
class Book:
    id: Annotated[int, Identity]
    title: str
    author: str
    genre: str
    year: int
```

```bash
uv run python -m derivelib.examples.query_transforms

curl 'http://localhost:8000/books?page=1&page_size=5'
curl 'http://localhost:8000/books?sort=title&order=desc'
curl 'http://localhost:8000/books?filter_genre=fiction'
curl 'http://localhost:8000/books?q=python'
```

**You write:** entity fields + pattern choice.
**Derived:** request/response types, handlers, routes, OpenAPI, CLI, error handling.

---

## Level 2: Algebra + Methods — derive the boring, write the interesting

From `derivelib/examples/bounties.py` — 3 derived + 2 hand-written endpoints:

```python
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Annotated

from kungfu import Error, Ok, Result

from emergent.wire.axis.query import MutatingRelationalProvider, relational
from emergent.wire.axis.schema import Identity
from emergent.wire.axis.schema.dialects import compose

from derivelib import build_application_from_decorated, derive, fields, memory_node
from derivelib._errors import DomainError, InvalidData
from derivelib.patterns.crud import CREATE, GET, LIST, http_crud
from derivelib.patterns.methods import methods, post

BountyBoard = memory_node()

# CREATE normally takes ALL non-id fields. Narrow it: only title + reward.
BOUNTY_CREATE = replace(CREATE, input_proj=fields("title", "reward"))

@derive(
    http_crud("/bounties", provider_node=BountyBoard, ops=(LIST, GET, BOUNTY_CREATE)),
    methods,
)
@dataclass
class Bounty:
    id: Annotated[int, Identity]
    title: str
    reward: int
    status: str = "open"
    hunter: str | None = None

    @post("/bounties/{bounty_id}/claim")
    async def claim(
        self,
        db: Annotated[MutatingRelationalProvider[Bounty], compose.Node(BountyBoard)],
        bounty_id: int,
        hunter: str,
    ) -> Result[Bounty, DomainError]:
        bounty = await db.fetch_one(
            relational(Bounty).filter(lambda b: b.id == bounty_id)
        )
        if bounty is None:
            return Error(InvalidData(entity="Bounty", reason=f"bounty {bounty_id} not found"))
        if bounty.status != "open":
            return Error(InvalidData(entity="Bounty", reason=f"already {bounty.status}"))
        updated = replace(bounty, status="claimed", hunter=hunter)
        await db.update(updated)
        return Ok(updated)

    @post("/bounties/{bounty_id}/complete")
    async def complete(
        self,
        db: Annotated[MutatingRelationalProvider[Bounty], compose.Node(BountyBoard)],
        bounty_id: int,
    ) -> Result[Bounty, DomainError]:
        bounty = await db.fetch_one(
            relational(Bounty).filter(lambda b: b.id == bounty_id)
        )
        if bounty is None:
            return Error(InvalidData(entity="Bounty", reason=f"bounty {bounty_id} not found"))
        if bounty.status != "claimed":
            return Error(
                InvalidData(entity="Bounty", reason=f"not claimed yet, status is {bounty.status}")
            )
        updated = replace(bounty, status="completed")
        await db.update(updated)
        return Ok(updated)

app = build_application_from_decorated(Bounty)
```

```bash
uv run python -m derivelib.examples.bounties

curl -X POST http://localhost:8000/bounties -H 'Content-Type: application/json' \
     -d '{"title":"Debug the cursed regex","reward":200}'
curl http://localhost:8000/bounties
curl -X POST http://localhost:8000/bounties/1/claim -H 'Content-Type: application/json' \
     -d '{"bounty_id":1,"hunter":"Geralt"}'
curl -X POST http://localhost:8000/bounties/1/complete -H 'Content-Type: application/json' \
     -d '{"bounty_id":1}'
```

5 endpoints: 3 derived (List, Get, Create) + 2 hand-written (claim, complete). Shared provider, shared error handling.

---

## Level 3: Pure Methods — every endpoint explicit

From `derivelib/examples/service.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from kungfu import Error, Ok, Result

from emergent.wire.axis.query import MutatingRelationalProvider, relational
from emergent.wire.axis.query.providers.memory import MemoryRelationalProvider
from emergent.wire.axis.schema import Identity
from emergent.wire.axis.schema.dialects import compose

from derivelib import build_application_from_decorated, derive, memory_node
from derivelib._errors import DomainError, InvalidData
from derivelib.patterns.methods import get, methods, post


@dataclass
class Order:
    id: Annotated[int, Identity]
    customer: str
    total: float
    status: str


OrderStore = memory_node()


@derive(methods)
@dataclass
class OrderService:
    @post("/api/orders")
    async def create(
        self,
        db: Annotated[MemoryRelationalProvider[Order], compose.Node(OrderStore)],
        customer: str,
        total: float,
    ) -> Result[int, DomainError]:
        nid: int = await db.next_id()
        await db.insert(
            Order(id=nid, customer=customer, total=total, status="pending")
        )
        return Ok(nid)

    @get("/api/orders")
    async def list_all(
        self,
        db: Annotated[MemoryRelationalProvider[Order], compose.Node(OrderStore)],
    ) -> Result[list[Order], DomainError]:
        orders = await db.fetch_many(relational(Order))
        return Ok(orders)

    @get("/api/orders/{order_id}")
    async def find(
        self,
        db: Annotated[MutatingRelationalProvider[Order], compose.Node(OrderStore)],
        order_id: int,
    ) -> Result[Order | None, DomainError]:
        order = await db.fetch_one(
            relational(Order).filter(lambda o: o.id == order_id)
        )
        return Ok(order)

    @post("/api/orders/cancel")
    async def cancel(
        self,
        db: Annotated[MutatingRelationalProvider[Order], compose.Node(OrderStore)],
        order_id: int,
    ) -> Result[bool, DomainError]:
        order = await db.fetch_one(
            relational(Order).filter(lambda o: o.id == order_id)
        )
        if order is None:
            return Error(InvalidData(entity="Order", reason=f"order {order_id} not found"))
        await db.update(
            Order(id=order.id, customer=order.customer, total=order.total, status="cancelled")
        )
        return Ok(True)

app = build_application_from_decorated(OrderService)
```

```bash
uv run python -m derivelib.examples.service

curl -X POST http://localhost:8000/api/orders \
     -H 'Content-Type: application/json' \
     -d '{"customer": "Charlie", "total": 199.99}'
curl http://localhost:8000/api/orders
curl http://localhost:8000/api/orders/1
curl -X POST http://localhost:8000/api/orders/cancel \
     -H 'Content-Type: application/json' \
     -d '{"order_id": 1}'
```

**You write:** every method, every trigger, every parameter.
**Derived:** request/response types, route registration, error handling, DI wiring.

---

## Level 4: Pure Wire — full manual control

From `examples/roulette/` — multi-target app (HTTP + CLI + Telegram).

### requests — boundary in, multi-dialect annotations

```python
# examples/roulette/requests.py

from emergent.wire.axis.schema import Doc
from emergent.wire.axis.schema.dialects import cli, tg, compose

@dataclass
class RegisterRequest:
    login: Annotated[str,
        cli.Help("Username"), cli.Positional(),
        Doc("Username for registration"),
        tg.CommandArg(),
    ]
    password: Annotated[str,
        cli.Help("Password"), cli.Positional(),
        Doc("Account password"),
        tg.CommandArg(),
    ]

    def to_domain(self) -> Register:
        return Register(login=self.login, password=self.password)


@dataclass
class BetRequest:
    token: Annotated[str, Doc("Auth token from login")]
    bet: Annotated[str,
        cli.Help("Bet type: red, black, or 0-36"), cli.Positional(),
        Doc("Bet type: 'red', 'black', or number 0-36"),
        tg.CommandArg(),
    ]
    amount: Annotated[int,
        cli.Help("Bet amount"), cli.Positional(),
        Doc("Amount to bet"),
        tg.CommandArg(),
    ]

    def to_domain(self) -> PlaceBet:
        return PlaceBet(bet=self.bet, amount=self.amount)

    def to_auth(self) -> Authenticate:
        return Authenticate(token=self.token)


@dataclass
class TelegramBalanceRequest:
    chat_id: Annotated[int, compose.Node(ChatId)]

    def to_domain(self) -> GetBalance:
        return GetBalance()

    def to_auth(self) -> TelegramIdentity:
        return TelegramIdentity(chat_id=self.chat_id)
```

ONE type, THREE projections. `to_domain()` converts boundary → op.

### responses — boundary out, UI annotations

```python
# examples/roulette/responses.py

from emergent.wire.axis.schema.dialects import tg

@dataclass
class BetResponse:
    result: Annotated[str | None, tg.Bold()] = None
    number: Annotated[int | None, tg.Code()] = None
    payout: Annotated[int | None, tg.Bold()] = None
    new_balance: Annotated[int | None, tg.Bold()] = None
    error: str | None = None

    @classmethod
    def from_domain(cls, dom: Result[BetResult, str]) -> BetResponse:
        match dom:
            case Ok(r):
                result = "Won!" if r.won else "Lost"
                return cls(result=result, number=r.number,
                           payout=r.payout, new_balance=r.new_balance)
            case Error(e):
                return cls(error=e)
```

### wiring — expose everywhere

```python
# examples/roulette/wiring.py

from emergent.wire.axis.surface import endpoint, Application
from emergent.wire.axis.surface.codecs.rrc import rrc
from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger
from emergent.wire.axis.surface.triggers.cli import CLITrigger
from emergent.wire.axis.surface.triggers.telegrinder import TelegrindTrigger
from emergent.wire.axis.surface.capabilities import SurfaceCapability, ScopeEnricher, EnricherNext
from emergent.wire.compile.targets import fastapi, cli

from telegrinder.bot.rules import Command


# Custom auth enricher
@dataclass(frozen=True, slots=True)
class Auth(SurfaceCapability, ScopeEnricher):
    request_cls: type[HasAuth]

    async def enrich[R](self, call: EnricherNext[R], scope: Scope) -> R | AuthErrorResponse:
        req_value = scope.get(self.request_cls)
        if req_value is None:
            return AuthErrorResponse(error="request not in scope")
        req: HasAuth = req_value.value
        result = await auth_runner.run(req.to_auth())
        match result:
            case Ok(user):
                scope.inject(AuthUser, user)
                return await call(scope)
            case Error(e):
                return AuthErrorResponse(error=e)


app = Application().mount(
    # Register — public, HTTP + CLI + Telegram
    endpoint(auth_runner)
        .expose(HTTPRouteTrigger("POST", "/register"), rrc(RegisterRequest, TokenResponse))
        .expose(CLITrigger("register", "Register new user"), rrc(RegisterRequest, TokenResponse)),

    # Login — public, HTTP + CLI
    endpoint(auth_runner)
        .expose(HTTPRouteTrigger("POST", "/login"), rrc(LoginRequest, TokenResponse))
        .expose(CLITrigger("login", "Login to account"), rrc(LoginRequest, TokenResponse)),

    # Balance — requires auth
    endpoint(game_runner)
        .expose(HTTPRouteTrigger("GET", "/balance"), rrc(BalanceRequest, BalanceResponse),
                Auth(BalanceRequest)),

    # Bet — requires auth, HTTP + CLI
    endpoint(game_runner)
        .expose(HTTPRouteTrigger("POST", "/bet"), rrc(BetRequest, BetResponse),
                Auth(BetRequest))
        .expose(CLITrigger("bet", "Place a bet"), rrc(BetRequest, BetResponse)),

    # Telegram endpoints
    endpoint(auth_runner)
        .expose(TelegrindTrigger(Command("register")), rrc(RegisterRequest, TokenResponse)),
    endpoint(game_runner)
        .expose(TelegrindTrigger(Command("balance")), rrc(TelegramBalanceRequest, BalanceResponse),
                Auth(TelegramBalanceRequest)),
    endpoint(game_runner)
        .expose(TelegrindTrigger(Command("bet")), rrc(TelegramBetRequest, BetResponse),
                Auth(TelegramBetRequest)),
)

fastapi_app = fastapi.compile(app)
cli_parser = cli.compile(app, prog="roulette")
```

```bash
# HTTP
uvicorn examples.roulette.wiring:fastapi_app --reload

# CLI
uv run python -m examples.roulette register alice secret
uv run python -m examples.roulette login alice secret
```

> Full runnable example: `examples/roulette/`

### Choosing the right level

| Level | Boilerplate | Control | Schema-driven |
|---|---|---|---|
| 1. Pure Algebra | Minimal | Pattern-level | Yes |
| 2. Algebra + Methods | Low | Per-method for domain ops | Hybrid |
| 3. Pure Methods | Medium | Per-method for all ops | No |
| 4. Pure Wire | Maximum | Total | No |

Levels compose: a single `@derive(...)` can stack CRUD + methods patterns. Each level uses the same compilation pipeline and target compilers.

---

# Part 2: Understand

---

## The four axes

| Action | Axis | You write | Swappable target |
|--------|------|-----------|------------------|
| **Describe** | schema | `Annotated[str, cli.Help(...)]` | compiler (CLI, OpenAPI, SQL) |
| **Access** | query | `store.filter(...).fetch_many()` | provider (Memory, SQL, HTTP) |
| **Persist** | storage | `kv(backend, codec)` | backend (Memory, Redis) |
| **Expose** | surface | `endpoint().expose(trigger, codec)` | trigger (HTTP, CLI, Telegram) |

Each axis = **Language x Target**. Swap target, keep code.

---

## Wire architecture

```
emergent/wire/
├── axis/                          # FOUR AXES
│   ├── _capability.py             # ROOT Capability + compilation contexts
│   ├── surface/                   # WHERE + HOW to execute (API surface)
│   │   ├── codecs/                # rrc, stateful, immediate
│   │   ├── triggers/              # http, cli, telegrinder
│   │   ├── dialects/              # openapi, telegram, cli capabilities
│   │   ├── enrichers/             # runtime middleware
│   │   └── transforms/            # compile-time transforms
│   ├── storage/                   # HOW to persist (KV, Queue, PubSub)
│   ├── schema/                    # WHAT shape data takes (annotations)
│   │   └── dialects/              # cli, openapi, sql, pydantic, tg, compose
│   └── query/                     # HOW to access data (QuerySets)
│       └── providers/             # memory, sql
├── compile/                       # Application → Framework artifacts
│   └── targets/                   # fastapi, cli, telegrinder
└── bridge/                        # Framework → Application (reverse)
    └── bridgers/                  # fastapi extractors
```

---

## Capability system — self-contained compiler plugins

**Capabilities are self-contained.** Compiler calls `compile_*()` methods and collects results.

```python
from dataclasses import dataclass, replace
from emergent.wire.axis._capability import (
    Capability,
    OpenAPIContext, ArgparseContext, SQLAlchemyContext,
    openapi_schema, argparse_arg, sqlalchemy_column,
)

@dataclass(frozen=True, slots=True)
class MaxLen(Capability):
    value: int

    def compile_openapi(self, ctx: OpenAPIContext) -> OpenAPIContext:
        return openapi_schema(ctx, maxLength=self.value)

    def compile_sqlalchemy(self, ctx: SQLAlchemyContext) -> SQLAlchemyContext:
        return sqlalchemy_column(ctx, length=self.value)

    # No compile_argparse — DON'T implement no-op methods
```

### Compilation contexts per axis

**Schema axis** (field-level):
- `PydanticContext` — holds `FieldInfo` directly
- `OpenAPIContext` — holds JSON Schema dict
- `ArgparseContext` — holds `add_argument` kwargs
- `SQLAlchemyContext` — holds Column config

**Schema axis** (class-level):
- `PydanticModelContext` — model title, description
- `OpenAPISchemaContext` — schema-level JSON Schema
- `SQLAlchemyTableContext` — table name, constraints, indexes

**Surface axis** (route-level):
- `FastAPIRouteContext` — path, method, tags, security
- `TelegrinderHandlerContext` — edit_message, answer_callback
- `CLICommandContext` — name, help, description

### Compilable protocols

```python
# Field-level
class PydanticCompilable(Protocol):
    def compile_pydantic(self, ctx: PydanticContext) -> PydanticContext: ...

class OpenAPICompilable(Protocol):
    def compile_openapi(self, ctx: OpenAPIContext) -> OpenAPIContext: ...

class ArgparseCompilable(Protocol):
    def compile_argparse(self, ctx: ArgparseContext) -> ArgparseContext: ...

class SQLAlchemyCompilable(Protocol):
    def compile_sqlalchemy(self, ctx: SQLAlchemyContext) -> SQLAlchemyContext: ...

# Surface-level
class FastAPICompilable(Protocol):
    def compile_fastapi(self, ctx: FastAPIRouteContext) -> FastAPIRouteContext: ...

class TelegrinderCompilable(Protocol):
    def compile_telegrinder(self, ctx: TelegrinderHandlerContext) -> TelegrinderHandlerContext: ...
```

---

## schema

Annotated fields. Each compiler reads its dialect.

```python
from emergent.wire.axis.schema import Identity, Unique, MaxLen
from emergent.wire.axis.schema.dialects import sql, openapi, cli, tg

@dataclass
class User:
    id: Annotated[int, Identity]
    email: Annotated[str,
        Unique, MaxLen(255),           # universal — all compilers
        sql.Index("idx_email"),        # SQL only
        openapi.Format("email"),       # OpenAPI only
        cli.Help("User email"),        # CLI only
    ]
```

### Pre-built patterns

```python
from emergent.wire.axis.schema import Id, Email, Slug, Username, Short, NonNegative

@dataclass
class User:
    id: Annotated[int, *Id]              # Identity
    email: Annotated[str, *Email]        # Unique + MaxLen(255)
    name: Annotated[str, *Short]         # MaxLen(100)
    balance: Annotated[int, *NonNegative] # Min(0)
```

### compose dialect — nodnod node composition

From `examples/roulette/requests.py`:

```python
from emergent.wire.axis.schema.dialects import compose
from telegrinder.node import ChatId

@dataclass
class TelegramBalanceRequest:
    chat_id: Annotated[int, compose.Node(ChatId)]  # Compose from nodnod node

    def to_domain(self) -> GetBalance:
        return GetBalance()

    def to_auth(self) -> TelegramIdentity:
        return TelegramIdentity(chat_id=self.chat_id)
```

---

## query

QuerySet builds AST. Provider executes.

```python
from emergent.wire.axis.query import relational_store, MemoryRelationalProvider

users = relational_store(User, MemoryRelationalProvider[User]())

active = await users.filter(lambda u: u.active).fetch_many()
rich = await users.filter(lambda u: u.balance > 100).limit(10).fetch_many()
```

Swap `MemoryRelationalProvider` → `SQLProvider`. Same code.

---

## storage

Pattern = capabilities + codec. Backend = implementation.

```python
from emergent.wire.axis.storage import kv, queue, MemoryStorage, JsonCodec

# KV = Get + Set + Delete
users = kv(MemoryStorage(), JsonCodec[User]())

# Queue = Push + Pop + Peek
tasks = queue(backend, JsonCodec[Task]())
```

---

## surface

Codec = execution shape. Trigger = where.

**Codecs:**
- `rrc` — request → response
- `stateful` — state → ... → Done → execute
- `immediate` — return value directly

**Triggers:**
- `HTTPRouteTrigger` — REST endpoint
- `CLITrigger` — CLI subcommand
- `TelegrindTrigger` — Telegram bot

**Capabilities (enrichers):**
```python
from emergent.wire.axis.surface import capabilities as C

endpoint(runner).expose(
    trigger,
    rrc(Request, Response),
    C.enricher.Provide(type=AuthUser, ...),    # Auth via Provide
    C.enricher.Timeout(seconds=5.0),           # Timeout
    C.enricher.Retry(policy=RetryPolicy(...)), # Retry
)
```

---

## derivelib — algebraic derivation system

Not a CRUD generator. CRUD is one dialect. The machinery is a generic algebraic derivation system over wire's 4-axis IR.

### The algebra

```
Step       = any object implementing derive_schema / derive_query / derive_storage / derive_surface
Derivation = tuple[Step, ...]
DerivationT = Derivation → Derivation
```

### The pipeline

```
entity + @derive(pattern)
    ↓
pattern.compile(entity) → Derivation (tuple of steps)
    ↓
fold_derive(steps, entity) → DerivationCtx
    ↓
materialize(ctx) → Endpoint
    ↓
build_application_from_decorated → Application
    ↓
targets.fastapi.compile(app)  /  targets.cli.compile(app)
```

### Two-pass fold

```
Pass 1:  Schema    — inspect entity fields, validate constraints
Pass 2:  Query → Storage → Surface  (sequential, each sees prior results)
```

Each step only runs in passes where it implements the matching protocol. Steps not matching a phase are silently skipped.

### CRUD Ops

```python
from derivelib.patterns import LIST, GET, CREATE, UPDATE, PATCH, DELETE

LIST   = Op("List",   no_fields(),  list_response(),   FetchMany())
GET    = Op("Get",    id_only(),    entity_response(),  FetchOneById())
CREATE = Op("Create", non_id(),     entity_response(),  InsertNew())
UPDATE = Op("Update", all_fields(), entity_response(),  UpdateExisting())
PATCH  = Op("Patch",  merge(id_only(), optional_non_id()), entity_response(), PatchExisting())
DELETE = Op("Delete", id_only(),    ok_response(),      DeleteOne())
```

### Transforms (DerivationT)

```python
from derivelib.transforms import (
    readonly, mutations_only, without_delete,
    without_ops, only_ops,
    add_capability, paginated, sorted_list,
    project_response, swap_handler, rename_ops,
    map_by_effect, wrap_by_effect,
    with_timeout, with_retry, with_rate_limit,
    map_methods, add_method_capability,
)

# Compose via .chain()
http_crud("/users", Users).chain(
    readonly(),
    paginated(50),
    add_capability(CORSCap()),
    project_response(exclude=("secret",)),
)
```

### Effects

```python
from derivelib import Read, Mutation, Creates, Updates, Deletes, Pageable, Sortable, Cacheable

# Creates/Updates/Deletes extend Mutation
# So has_effect(effects, Mutation) matches them automatically
add_capability(AuthCap(), Mutation)  # auth only for mutations
```

### Adaptation (auto-adapt from schema_meta)

```python
from emergent.wire.axis.schema._universal import schema_meta
from emergent.wire.axis.schema.dialects.temporal import SoftDelete, Timestamps

@schema_meta(SoftDelete("deleted_at"), Timestamps("created_at", "updated_at"))
@derive(http_crud("/api/users", Users))
@dataclass
class User:
    id: Annotated[int, Identity]
    name: str
    deleted_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
```

Delete → SoftDeleteMark, Create → auto-set timestamps, base query filters `deleted_at IS NULL`.

### Nested CRUD

From `derivelib/examples/nested.py`:

```python
from emergent.wire.axis.schema._universal import Ref

from derivelib import derive, build_application_from_decorated, memory_node
from derivelib.patterns.crud import http_crud
from derivelib.patterns.nested import nested_http_crud

Users = memory_node()
Posts = memory_node()

@derive(http_crud("/users", provider_node=Users))
@dataclass
class User:
    id: Annotated[int, Identity]
    name: str
    email: str


@derive(nested_http_crud("/users", parent=User, provider_node=Posts))
@dataclass
class Post:
    id: Annotated[int, Identity]
    user_id: Annotated[int, Ref(User)]
    title: str
    body: str
```

```bash
uv run python -m derivelib.examples.nested

curl -X POST http://localhost:8000/users -H 'Content-Type: application/json' \
     -d '{"name": "Alice", "email": "alice@example.com"}'
curl -X POST http://localhost:8000/users/1/posts -H 'Content-Type: application/json' \
     -d '{"title": "Hello World", "body": "First post"}'
curl http://localhost:8000/users/1/posts
```

### Self-description

```python
from derivelib import explain_entity

print(explain_entity(User))
```

```
=== User Derivation ===
  1 pattern

  Pattern #1: Dialect, provider=Users
    Steps (11):
      1. InspectEntity
      2. RequireIdentity
      3. BindProvider(node=Users)
      4. SetBaseQuery
      5. AdaptBaseQuery
      6. DeriveOp "List" -> GET /api/users
         effects: Read, Pageable, Sortable
      7. DeriveOp "Get" -> GET /api/users/{id}
         effects: Read, Idempotent, Cacheable
      ...
```

---

## ops

Fields typed as ops = parallel dependencies.

```python
@dataclass(frozen=True, slots=True)
class GetProfile(O.Returning[Profile, str]):
    user_id: int
    user: GetUser      # ↘ parallel
    posts: GetPosts    # ↗ no dep between them
```

Framework runs `GetUser` and `GetPosts` in parallel, injects results.

---

## Tools

```python
from emergent import saga as S, cache as C, graph as G, idempotency as I

# saga — rollback on failure
checkout = S.step(reserve, release).then(lambda _: S.step(charge, refund))

# cache — tiered
cache = C.cache(key, fetch).tier(l1).tier(l2).build()

# graph — parallel nodes
@G.node
class Profile:
    @classmethod
    async def __compose__(cls, user: FetchUser, posts: FetchPosts) -> Profile: ...

# idempotency — exactly once
executor = I.idempotent(charge).key(lambda r: f"pay:{r.id}").build()
```

---

# Part 3: Extend

---

## Custom capability

```python
@dataclass(frozen=True, slots=True)
class GrpcFieldNumber(Capability):
    number: int

    def compile_protobuf(self, ctx: ProtobufContext) -> ProtobufContext:
        return replace(ctx, field_number=self.number)

@dataclass
class User:
    id: Annotated[int, Identity, GrpcFieldNumber(1)]
```

---

## Custom enricher

From `examples/roulette/wiring.py`:

```python
@dataclass(frozen=True, slots=True)
class Auth(SurfaceCapability, ScopeEnricher):
    request_cls: type[HasAuth]

    async def enrich[R](self, call: EnricherNext[R], scope: Scope) -> R | AuthErrorResponse:
        req_value = scope.get(self.request_cls)
        if req_value is None:
            return AuthErrorResponse(error="request not in scope")
        req: HasAuth = req_value.value
        result = await auth_runner.run(req.to_auth())
        match result:
            case Ok(user):
                scope.inject(AuthUser, user)
                return await call(scope)
            case Error(e):
                return AuthErrorResponse(error=e)
```

---

## Custom provider

```python
class SQLProvider(RelationalProvider[T]):
    async def fetch_many(self, q: RelationalQuerySet[T]) -> list[T]:
        stmt = select(self.model)
        for op in q.ops:
            match op:
                case Filter(expr): stmt = stmt.where(compile_expr(expr))
        return await self.session.scalars(stmt)
```

---

## Custom backend

```python
class RedisBackend:
    async def get(self, key: str) -> bytes | None:
        return await self.client.get(key)
    async def set(self, key: str, value: bytes) -> None:
        await self.client.set(key, value)
```

---

## Custom dialect

From `derivelib/examples/task_queue.py` — build your own dialect in 30 lines:

```python
from derivelib import (
    Op, derive, build_application_from_decorated, dialect,
    HTTPTriggers, CLITriggers,
    required_non_id, entity_response, id_only, list_response, no_fields,
    Read, Creates, Idempotent,
    FetchMany, FetchOneById,
)


def http_task_queue(path, provider_node, processor):
    return dialect(
        Op("Create", required_non_id(), entity_response(),
           SubmitAndProcess(processor), effects=(Creates(),)),
        Op("Get", id_only(), entity_response(),
           FetchOneById(), effects=(Read(), Idempotent())),
        Op("List", no_fields(), list_response(),
           FetchMany(), effects=(Read(),)),
        triggers=HTTPTriggers(path),
        provider_node=provider_node,
    )


@derive(
    http_task_queue("/tasks", provider_node=Tasks, processor=resize_image),
    cli_task_queue("task", provider_node=Tasks, processor=resize_image),
)
@dataclass
class ImageResize:
    id: Annotated[int, Identity]
    url: str
    width: int
    height: int
    status: str = "pending"
    result: str = ""
    error: str = ""
```

```bash
uv run python -m derivelib.examples.task_queue http
# POST /tasks -> submit, GET /tasks/{id} -> status, GET /tasks -> list

uv run python -m derivelib.examples.task_queue cli task-create https://example.com/img.png 800 600
uv run python -m derivelib.examples.task_queue cli task-list
```

---

## Custom pattern

From `derivelib/examples/workflow.py` — state machine from transition map:

```python
from derivelib import (
    derive, build_application_from_decorated, memory_node,
    exposure, SurfaceCtx, Derivation,
    fetch_by_identity, id_path, provider_field,
    NotFound, InvalidData,
)
from derivelib.axes.schema import inspect_entity, require_identity


@dataclass(frozen=True, slots=True)
class Transition:
    name: str
    from_states: tuple[str, ...]
    to_state: str


@dataclass(frozen=True, slots=True)
class WorkflowPattern:
    base_path: str
    provider_node: type
    state_field: str
    transitions: tuple[Transition, ...]

    def compile(self, entity: type) -> Derivation:
        init = self.transitions[0].from_states[0] if self.transitions else "draft"
        return (
            inspect_entity(), require_identity(),
            WorkflowCreateStep(self.base_path, self.state_field, init, self.provider_node),
            *(TransitionStep(self.base_path, tr, self.state_field, self.provider_node)
              for tr in self.transitions),
        )


Orders = memory_node()

@derive(WorkflowPattern(
    "/orders", provider_node=Orders, state_field="status",
    transitions=(
        Transition("submit",  ("draft",), "pending"),
        Transition("approve", ("pending",), "approved"),
        Transition("reject",  ("pending",), "rejected"),
        Transition("ship",    ("approved",), "shipped"),
        Transition("cancel",  ("draft", "pending"), "cancelled"),
    ),
))
@dataclass
class Order:
    id: Annotated[int, Identity]
    customer: str
    amount: float
    status: str = "draft"
```

```bash
uv run python -m derivelib.examples.workflow

curl -X POST http://localhost:8000/orders/create -H 'Content-Type: application/json' \
     -d '{"customer": "Alice", "amount": 99.99}'
curl -X POST http://localhost:8000/orders/1/submit
curl -X POST http://localhost:8000/orders/1/approve
curl -X POST http://localhost:8000/orders/1/ship
```

5 transitions, 6 endpoints. Invalid transitions return errors automatically.

---

## Custom compiler target

```python
from emergent.wire.compile import execute_rrc_unified

def grpc_compile(app: Application) -> GrpcServer:
    pairs = scan(app, GrpcTrigger)
    for trigger, handler in pairs:
        async def route(request):
            return await execute_rrc_unified(
                handler=handler,
                get_value=lambda name: getattr(request, name),
                inject_scope=lambda scope: scope.inject(GrpcRequest, request),
            )
        server.add_method(trigger.service, trigger.method, route)
    return server
```

---

## Bridge — legacy framework → wire

Symmetric to compile. Extract handlers from existing frameworks into wire Application.

```
compile: Application → Framework (OUT)
bridge:  Framework → Application (IN)
```

```python
from emergent.wire.bridge import WrapAsDelegate, IsolateGlobal, AddTrigger
from emergent.wire.bridge.bridgers import fastapi
from emergent.wire.axis.surface.triggers.cli import CLITrigger
from emergent.wire.compile.targets import cli

from my_legacy_app import fastapi_app

# Extract FastAPI → wire Application
wire_app = fastapi.extract(
    fastapi_app,
    capabilities=(
        WrapAsDelegate(),
        IsolateGlobal(
            module_path="my_legacy_app.routes",
            attr_name="_cache",
            factory=lambda: create_storage(),
        ),
        AddTrigger(
            trigger_type=CLITrigger,
            builder=lambda h: CLITrigger(h.name or "cmd", h.description),
        ),
    ),
)

# Compile to CLI
cli_parser = cli.compile(wire_app, prog="my-tool")
```

| Capability | Purpose |
|------------|---------|
| `WrapAsDelegate()` | Preserve handler signature as DelegateCodec |
| `IsolateGlobal(module, attr, factory)` | Replace module global with fresh instance per call |
| `AddTrigger(type, builder)` | Add trigger for cross-compilation |
| `MapDepends(depends_map)` | Resolve FastAPI `Depends()` parameters |
| `SkipByName(names)` | Skip handlers by name |
| `CatchErrors(on_error)` | Wrap handler with error boundary |

---

## Stack

| Layer | What |
|-------|------|
| emergent | ops, wire, saga, cache, graph, idempotency |
| derivelib | algebraic derivation over wire's 4-axis IR |
| [nodnod](https://github.com/timoniq/nodnod) | dependency graphs |
| [combinators.py](https://github.com/prostomarkeloff/combinators.py) | retry, timeout, fallback |
| [kungfu](https://github.com/timoniq/kungfu) | Result, Option |

---

<div align="center">

**Describe. Access. Persist. Execute. Expose.**

**Plain Python. Portable programs.**

</div>

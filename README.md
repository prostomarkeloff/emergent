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

```python
from dataclasses import dataclass
from typing import Annotated

from emergent.wire.axis.schema import Identity
from emergent.wire.compile.targets import fastapi

from derivelib import derive, build_application_from_decorated
from derivelib.patterns import http_crud

@derive(http_crud("/api/users", provider_node=Users))
@dataclass
class User:
    id: Annotated[int, Identity]
    name: str
    email: str

app = build_application_from_decorated(User)
fastapi_app = fastapi.compile(app)
```

5 endpoints (List, Get, Create, Update, Delete), request/response types with Pydantic validation, OpenAPI schema, error handling — all from the shape of `User`.

```bash
uvicorn app:fastapi_app --reload
# Open http://localhost:8000/docs
```

---

# Part 1: Build

Four levels of wiring — from fully derived to fully manual. Choose the level that fits.

---

## Level 1: Pure Algebra — one dataclass, one decorator

```python
from derivelib import derive, build_application_from_decorated
from derivelib.patterns import http_crud, cli_crud
from derivelib.transforms import readonly, paginated, add_capability

@derive(
    http_crud("/api/users", provider_node=Users).chain(
        paginated(50),
        add_capability(BearerAuth.jwt(), Mutation),
    ),
    cli_crud("user", provider_node=Users).chain(readonly()),
)
@dataclass
class User:
    id: Annotated[int, Identity]
    name: Annotated[str, MinLen(1), MaxLen(100)]
    email: Annotated[str, Unique, MaxLen(255)]
```

**You write:** entity fields + pattern choice.
**Derived:** request/response types, handlers, routes, OpenAPI, CLI, error handling.

---

## Level 2: Algebra + Methods — derive the boring, write the interesting

```python
from derivelib import derive, build_application_from_decorated
from derivelib.patterns.crud import http_crud, LIST, GET, CREATE
from derivelib.patterns.methods import methods, post

@derive(
    http_crud("/bounties", provider_node=BountyBoard, ops=(LIST, GET, CREATE)),
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
        bounty = await db.fetch_one(relational(Bounty).filter(lambda b: b.id == bounty_id))
        if bounty is None:
            return Error(InvalidData(entity="Bounty", reason="not found"))
        updated = replace(bounty, status="claimed", hunter=hunter)
        await db.update(updated)
        return Ok(updated)
```

5 endpoints: 3 derived (List, Get, Create) + 2 hand-written (claim, complete). Shared provider, shared error handling.

---

## Level 3: Pure Methods — every endpoint explicit

```python
from derivelib import derive, build_application_from_decorated
from derivelib.patterns.methods import methods, post, get

@derive(methods)
@dataclass
class OrderService:
    @post("/api/orders")
    async def create(self, customer: str, total: float) -> Result[int, DomainError]:
        return Ok(new_id)

    @get("/api/orders")
    async def list_all(self) -> Result[list[Order], DomainError]:
        ...

app = build_application_from_decorated(OrderService)
```

**You write:** every method, every trigger, every parameter.
**Derived:** request/response types, route registration, error handling, DI wiring.

---

## Level 4: Pure Wire — full manual control

Real examples from `examples/roulette/`.

### ops — what your program does

```python
from dataclasses import dataclass
from emergent import ops as O

@dataclass(frozen=True, slots=True)
class PlaceBet(O.Returning[BetResult, str]):
    bet: str
    amount: int

@dataclass(frozen=True, slots=True)
class GetBalance(O.Returning[int, str]):
    pass
```

`O.Returning[SuccessType, ErrorType]` — declares what the op returns.

### handlers — how it works

```python
from kungfu import Result, Ok, Error

async def handle_place_bet(op: PlaceBet, game_store: GameStore) -> Result[BetResult, str]:
    if op.amount <= 0:
        return Error("amount must be positive")
    return await game_store.place_bet(op.bet, op.amount)

async def handle_get_balance(_op: GetBalance, auth_user: AuthUser, game_store: GameStore) -> Result[int, str]:
    balance = await game_store.get_balance(auth_user)
    return Ok(balance)
```

Handler signature declares dependencies. Framework injects them.

### runner — wire together

```python
from emergent import ops as O

game_runner = (
    O.ops()
    .on(PlaceBet, handle_place_bet)
    .on(GetBalance, handle_get_balance)
    .compile()
    .inject(GameStore, game_store)
)
```

### requests — boundary in

```python
from emergent.wire.axis.schema.dialects import cli, openapi, tg

@dataclass
class BetRequest:
    token: Annotated[str, openapi.Description("Auth token")]
    bet: Annotated[str, cli.Help("red, black, or 0-36"), cli.Positional(), tg.CommandArg()]
    amount: Annotated[int, cli.Help("Bet amount"), cli.Positional(), tg.CommandArg()]

    def to_domain(self) -> PlaceBet:
        return PlaceBet(bet=self.bet, amount=self.amount)

    def to_auth(self) -> Authenticate:
        return Authenticate(token=self.token)
```

ONE type, THREE projections. `to_domain()` converts boundary → op.

### responses — boundary out

```python
from kungfu import Result, Ok, Error
from emergent.wire.axis.schema.dialects import tg

@dataclass
class BetResponse:
    result: Annotated[str | None, tg.Bold()] = None
    payout: Annotated[int | None, tg.Bold()] = None
    error: str | None = None

    @classmethod
    def from_domain(cls, dom: Result[BetResult, str]) -> "BetResponse":
        match dom:
            case Ok(r):
                return cls(result="Won!" if r.won else "Lost", payout=r.payout)
            case Error(e):
                return cls(error=e)
```

`from_domain()` converts op result → boundary.

### wiring — expose everywhere

```python
from nodnod import Scope

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
        req: HasAuth = scope.get(self.request_cls).value
        result = await auth_runner.run(req.to_auth())
        match result:
            case Ok(user):
                scope.inject(AuthUser, user)
                return await call(scope)
            case Error(e):
                return AuthErrorResponse(error=e)


app = Application().mount(
    # Public
    endpoint(auth_runner)
        .expose(HTTPRouteTrigger("POST", "/register"), rrc(RegisterRequest, TokenResponse))
        .expose(CLITrigger("register", "Register user"), rrc(RegisterRequest, TokenResponse)),

    # Protected
    endpoint(game_runner)
        .expose(HTTPRouteTrigger("POST", "/bet"), rrc(BetRequest, BetResponse), Auth(BetRequest))
        .expose(CLITrigger("bet", "Place bet"), rrc(BetRequest, BetResponse)),

    # Telegram
    endpoint(game_runner)
        .expose(TelegrindTrigger(Command("bet")), rrc(TelegramBetRequest, BetResponse), Auth(TelegramBetRequest)),
)

fastapi_app = fastapi.compile(app)
cli_parser = cli.compile(app, prog="roulette")
```

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

Each axis = **Language × Target**. Swap target, keep code.

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

```python
from emergent.wire.axis.schema.dialects import compose
from telegrinder.node import ChatId

@dataclass
class TelegramRequest:
    chat_id: Annotated[int, compose.Node(ChatId)]  # Compose from nodnod node

    def to_domain(self) -> GetBalance:
        return GetBalance()
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

```python
from derivelib.patterns import nested_http_crud

@derive(nested_http_crud("/users", parent=User, provider_node=Posts))
@dataclass
class Post:
    id: Annotated[int, Identity]
    user_id: Annotated[int, Ref(User)]
    title: str
    body: str
# → GET/POST /users/{user_id}/posts, GET/PUT/DELETE /users/{user_id}/posts/{id}
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

```python
@dataclass(frozen=True, slots=True)
class RateLimit(SurfaceCapability, ScopeEnricher):
    requests_per_minute: int

    async def enrich[R](self, call: EnricherNext[R], scope: Scope) -> R:
        # Check rate limit...
        return await call(scope)
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

Build your own derivation dialect from generic primitives:

```python
from derivelib import dialect, Op, fields, entity_response, list_response
from derivelib import FetchMany, FetchOneById, Read, Mutation, Creates, Idempotent
from derivelib import HTTPTriggers

SUBMIT = Op("Create", required_non_id(), entity_response(),
    SubmitAndProcess(processor), effects=(Mutation(), Creates()))
GET    = Op("Get", id_only(), entity_response(),
    FetchOneById(), effects=(Read(), Idempotent()))
LIST   = Op("List", no_fields(), list_response(),
    FetchMany(), effects=(Read(),))

def http_task_queue(path, provider_node, processor):
    return dialect(SUBMIT, GET, LIST,
        triggers=HTTPTriggers(path),
        provider_node=provider_node,
    )

@derive(http_task_queue("/tasks", Tasks, processor=resize_image))
@dataclass
class ImageResize:
    id: Annotated[int, Identity]
    url: str
    width: int
    height: int
    status: str = "pending"
```

---

## Custom pattern

```python
@dataclass(frozen=True, slots=True)
class WorkflowPattern:
    base_path: str
    provider_node: type
    state_field: str
    transitions: tuple[Transition, ...]

    def compile(self, entity: type) -> Derivation:
        return (
            inspect_entity(), require_identity(),
            WorkflowCreateStep(self.base_path, self.state_field, "draft", self.provider_node),
            *(TransitionStep(self.base_path, tr, self.state_field, self.provider_node)
              for tr in self.transitions),
        )

@derive(WorkflowPattern(
    "/orders", provider_node=Orders, state_field="status",
    transitions=(
        Transition("submit",  ("draft",), "pending"),
        Transition("approve", ("pending",), "approved"),
        Transition("ship",    ("approved",), "shipped"),
    ),
))
@dataclass
class Order:
    id: Annotated[int, Identity]
    customer: str
    amount: float
    status: str = "draft"
```

---

## Custom effect end-to-end

```python
# 1. Define effect
@dataclass(frozen=True, slots=True)
class MindBorn(DerivationEffect):
    """A new mind emerges after this operation."""

# 2. Put on an op
CREATE_MIND = Op("Create", required_non_id(), entity_response(),
    InsertNew(), effects=(Mutation(), Creates(), MindBorn()))

# 3. Build transform
def on_mind_born(callback) -> DerivationT:
    return map_by_effect({
        MindBorn: lambda _eff, op: replace(op, handler_template=wrap_template(
            op.handler_template, lambda inner, spec: _after(inner, callback),
        ))
    })

# 4. Use
@derive(
    dialect(CREATE_MIND, GET, LIST,
        triggers=HTTPTriggers("/api/minds"),
        provider_node=Minds,
    ).chain(on_mind_born(celebrate))
)
@dataclass
class Mind:
    id: Annotated[int, Identity]
    name: str
```

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

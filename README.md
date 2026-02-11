<div align="center">

# emergent

**Write once, compile anywhere.**

[![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Types: pyright strict](https://img.shields.io/badge/types-pyright%20strict-blue)](https://github.com/microsoft/pyright)

</div>

One dataclass. One decorator. Full application — HTTP, CLI, Telegram, OpenAPI, Pydantic validation, RFC 7807 errors. All from the shape of your types.

```python
@derive(http_crud("/users", provider_node=Users))
@dataclass
class User:
    id: Annotated[int, Identity]
    name: str
    email: Annotated[str, Unique]
```

That's 5 REST endpoints. Add another entity — that's 10. Three entities — 15. You write fields, emergent writes everything else.

```bash
uv add git+https://github.com/prostomarkeloff/emergent.git
```

> Full runnable example: [`derivelib/examples/crud.py`](derivelib/examples/crud.py)

---

# The spectrum

Four levels of control. Pick what fits. Mix them in one app.

## Level 1: Pure Algebra

One dataclass, one decorator. Schema drives everything.

```python
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
```

Same entity, two targets. HTTP _and_ CLI from one definition.

Transforms compose via `.chain()`:

```python
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
curl 'http://localhost:8000/books?page=1&page_size=5'
curl 'http://localhost:8000/books?sort=title&order=desc'
curl 'http://localhost:8000/books?filter_genre=fiction&q=python'
```

> Runnable: [`derivelib/examples/multi_target.py`](derivelib/examples/multi_target.py), [`derivelib/examples/query_transforms.py`](derivelib/examples/query_transforms.py)

---

## Level 2: Algebra + Methods

Derive the boring parts. Write the interesting ones.

```python
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

    @classmethod
    @post("/bounties/{bounty_id}/claim")
    async def claim(
        cls,
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
```

5 endpoints: 3 derived (List, Get, Create) + 2 hand-written (claim, complete). One provider, shared error handling, zero glue.

```bash
curl -X POST http://localhost:8000/bounties -H 'Content-Type: application/json' \
     -d '{"title":"Debug the cursed regex","reward":200}'
curl -X POST http://localhost:8000/bounties/1/claim -H 'Content-Type: application/json' \
     -d '{"bounty_id":1,"hunter":"Geralt"}'
```

> Runnable: [`derivelib/examples/bounties.py`](derivelib/examples/bounties.py)

---

## Level 3: Pure Methods

You write every endpoint. derivelib still handles request/response types, routing, error handling, and DI.

```python
@derive(methods)
@dataclass
class OrderService:
    @classmethod
    @post("/api/orders")
    async def create(
        cls,
        db: Annotated[MemoryRelationalProvider[Order], compose.Node(OrderStore)],
        customer: str,
        total: float,
    ) -> Result[int, DomainError]:
        nid = await db.next_id()
        await db.insert(Order(id=nid, customer=customer, total=total, status="pending"))
        return Ok(nid)

    @classmethod
    @get("/api/orders")
    async def list_all(cls, db: ...) -> Result[list[Order], DomainError]:
        return Ok(await db.fetch_many(relational(Order)))

    @classmethod
    @get("/api/orders/{order_id}")
    async def find(cls, db: ..., order_id: int) -> Result[Order | None, DomainError]:
        return Ok(await db.fetch_one(relational(Order).filter(lambda o: o.id == order_id)))

    @classmethod
    @post("/api/orders/cancel")
    async def cancel(cls, db: ..., order_id: int) -> Result[bool, DomainError]:
        order = await db.fetch_one(relational(Order).filter(lambda o: o.id == order_id))
        if order is None:
            return Error(InvalidData(entity="Order", reason=f"order {order_id} not found"))
        await db.update(replace(order, status="cancelled"))
        return Ok(True)
```

> Runnable: [`derivelib/examples/service.py`](derivelib/examples/service.py)

---

## Level 4: Pure Wire

No derivelib. Write wire IR directly — endpoints, codecs, triggers. Maximum control, every target.

```python
app = Application().mount(
    # One endpoint, three targets
    endpoint(auth_runner)
        .expose(HTTPRouteTrigger("POST", "/register"), rrc(RegisterRequest, TokenResponse))
        .expose(CLITrigger("register", "Register"), rrc(RegisterRequest, TokenResponse))
        .expose(TelegrindTrigger(Command("register")), rrc(RegisterRequest, TokenResponse)),

    # Auth-protected endpoint
    endpoint(game_runner)
        .expose(HTTPRouteTrigger("POST", "/bet"), rrc(BetRequest, BetResponse), Auth(BetRequest))
        .expose(CLITrigger("bet", "Place a bet"), rrc(BetRequest, BetResponse)),
)

fastapi_app = fastapi.compile(app)
cli_parser = cli.compile(app, prog="roulette")
```

One type, three projections. One endpoint, three exposures.

```python
@dataclass
class RegisterRequest:
    login: Annotated[str, Doc("Login"), cli.Help("Username"), cli.Positional(), tg.CommandArg()]
    password: Annotated[str, Doc("Password"), cli.Help("Password"), cli.Positional(), tg.CommandArg()]

    def to_domain(self) -> Register:
        return Register(login=self.login, password=self.password)
```

> Full multi-file example: [`examples/roulette/`](examples/roulette/)

### Choosing the right level

| Level | You write | You get for free |
|---|---|---|
| **1. Pure Algebra** | Fields + pattern | Everything |
| **2. Algebra + Methods** | Fields + domain methods | CRUD + wiring |
| **3. Pure Methods** | Every method | Types, routing, errors, DI |
| **4. Pure Wire** | Everything | Multi-target compilation |

Levels compose: a single `@derive(...)` can stack CRUD + methods on the same entity.

---

# How it works

## Four axes

Every program touches four concerns. emergent makes each one swappable:

| | You write | Swap target, keep code |
|---|---|---|
| **schema** | `Annotated[str, cli.Help(...)]` | CLI, OpenAPI, SQL, Pydantic |
| **query** | `store.filter(...).fetch_many()` | Memory, SQL, HTTP |
| **storage** | `kv(backend, codec)` | Memory, Redis, File |
| **surface** | `endpoint().expose(trigger, codec)` | HTTP, CLI, Telegram |

```python
# One field, annotations for every target
email: Annotated[str,
    Unique, MaxLen(255),           # universal
    sql.Index("idx_email"),        # SQL compiler reads this
    openapi.Format("email"),       # OpenAPI compiler reads this
    cli.Help("User email"),        # CLI compiler reads this
]
```

Each compiler reads only the dialect it understands. Add a target = add a compiler.

## The derivation pipeline

```
@derive(pattern)  on  @dataclass
    |
pattern.compile(entity) --> tuple of Steps
    |
fold_derive(steps) --> two-pass fold over 4 axes
    |              Pass 1: Schema (inspect fields)
    |              Pass 2: Query -> Storage -> Surface
materialize() --> wire Endpoint
    |
targets.fastapi.compile()  /  targets.cli.compile()
```

Steps only run in passes where they implement the matching protocol. Unknown phases are silently skipped. This is how CRUD steps and methods steps coexist in one derivation.

## Transforms

```python
http_crud("/users", Users).chain(
    readonly(),                          # drop mutations
    paginated(50),                       # add page/page_size params
    add_capability(BearerAuth(), Mutation), # auth only for writes
    project_response(exclude=("secret",)), # hide fields
)
```

Transforms are `Derivation -> Derivation`. They compose left-to-right via `.chain()`. Effects (`Read`, `Mutation`, `Creates`, `Deletes`, ...) let you target specific ops without naming them.

> Full reference: [`docs/derivelib.md`](docs/derivelib.md)

---

# Extend

Everything is open-world. No source modification needed.

## Custom capability

A self-contained compiler plugin:

```python
@dataclass(frozen=True, slots=True)
class GrpcFieldNumber(Capability):
    number: int

    def compile_protobuf(self, ctx: ProtobufContext) -> ProtobufContext:
        return replace(ctx, field_number=self.number)
```

## Custom dialect

Build your own derivation pattern in ~20 lines:

```python
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
```

> Runnable: [`derivelib/examples/task_queue.py`](derivelib/examples/task_queue.py)

## Custom pattern

State machine from a transition map:

```python
@derive(WorkflowPattern(
    "/orders", provider_node=Orders, state_field="status",
    transitions=(
        Transition("submit",  ("draft",), "pending"),
        Transition("approve", ("pending",), "approved"),
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

5 transitions, 6 endpoints. Invalid transitions return errors automatically.

> Runnable: [`derivelib/examples/workflow.py`](derivelib/examples/workflow.py)

## Bridge — existing framework to wire

The reverse of compilation. Extract a FastAPI app into wire, re-compile to CLI:

```
compile: Application --> Framework (OUT)
bridge:  Framework --> Application (IN)
```

```python
wire_app = fastapi.extract(legacy_app, capabilities=(
    WrapAsDelegate(),
    AddTrigger(trigger_type=CLITrigger, builder=build_cli_trigger),
))
cli_parser = cli.compile(wire_app, prog="my-tool")
```

---

# Examples

### derivelib

| Example | What it shows |
|---|---|
| [`crud.py`](derivelib/examples/crud.py) | 3 entities, 15 endpoints, zero controllers |
| [`bounties.py`](derivelib/examples/bounties.py) | CRUD + hand-written domain methods on one entity |
| [`service.py`](derivelib/examples/service.py) | Pure methods — every endpoint explicit |
| [`multi_target.py`](derivelib/examples/multi_target.py) | Same entity compiled to HTTP and CLI |
| [`nested.py`](derivelib/examples/nested.py) | `/users/{user_id}/posts` — nested resources |
| [`query_transforms.py`](derivelib/examples/query_transforms.py) | Pagination, sorting, filtering, search |
| [`projection.py`](derivelib/examples/projection.py) | Field-level response projection + auth |
| [`task_queue.py`](derivelib/examples/task_queue.py) | Custom dialect in 30 lines |
| [`workflow.py`](derivelib/examples/workflow.py) | State machine from transition map |
| [`authlib/`](derivelib/examples/authlib/) | Transport-agnostic auth library |
| [`chat/`](derivelib/examples/chat/) | AI chat with custom dialect |
| [`exotic_codec/`](derivelib/examples/exotic_codec/) | SSE + RRC + Immediate codecs in one app |
| [`ultimate/`](derivelib/examples/ultimate/) | 1 dataclass, 14 endpoints, 7 orthogonal concerns |

### wire / emergent

| Example | What it shows |
|---|---|
| [`roulette/`](examples/roulette/) | HTTP + CLI + Telegram from one codebase |
| [`wiring.py`](examples/wiring.py) | Raw wire: endpoint + trigger + codec |
| [`saga_example.py`](examples/saga_example.py) | Distributed transactions with auto-rollback |
| [`cache_example.py`](examples/cache_example.py) | Multi-tier caching |
| [`graph_example.py`](examples/graph_example.py) | Programs as dependency graphs |

---

# Docs

| Document | What's in it |
|---|---|
| [`docs/derivelib.md`](docs/derivelib.md) | Full derivelib reference — contexts, protocols, fold, ops, transforms, cookbook |
| [`docs/cheatsheet.md`](docs/cheatsheet.md) | Complete cheatsheet — all four axes, every import, every pattern |
| [`docs/introduction/`](docs/introduction/) | The six axes model and why emergent exists |

---

# Self-description

Every derivation can explain itself:

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

# Stack

| Layer | What |
|-------|------|
| emergent | ops, wire, saga, cache, graph, idempotency |
| derivelib | algebraic derivation over wire's 4-axis IR |
| [nodnod](https://github.com/timoniq/nodnod) | dependency graphs |
| [combinators.py](https://github.com/prostomarkeloff/combinators.py) | retry, timeout, fallback |
| [kungfu](https://github.com/timoniq/kungfu) | Result, Option |

---

<div align="center">

**Describe. Access. Persist. Expose.**

**Plain Python. Write once, compile anywhere.**

</div>

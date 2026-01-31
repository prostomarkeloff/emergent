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

Create `app.py`:

```python
from dataclasses import dataclass
from typing import Annotated

from kungfu import Result, Ok, Error

from emergent import ops as O
from emergent.wire import endpoint, Application
from emergent.wire.axis.surface.codecs.rrc import rrc
from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger
from emergent.wire.axis.surface.triggers.cli import CLITrigger
from emergent.wire.axis.schema.dialects import cli
from emergent.wire.compiler import fastapi_compile, cli_compile


# ─── Domain ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class GreetResult:
    message: str


# ─── Op ──────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Greet(O.Returning[GreetResult, str]):
    name: str


# ─── Handler ─────────────────────────────────────────────────────────────────


async def handle_greet(op: Greet) -> Result[GreetResult, str]:
    if not op.name:
        return Error("name is required")
    return Ok(GreetResult(message=f"Hello, {op.name}!"))


# ─── Runner ──────────────────────────────────────────────────────────────────


runner = O.ops().on(Greet, handle_greet).compile()


# ─── Request / Response ──────────────────────────────────────────────────────


@dataclass
class GreetRequest:
    name: Annotated[str, cli.Help("Name to greet"), cli.Positional()]

    def to_domain(self) -> Greet:
        return Greet(name=self.name)


@dataclass
class GreetResponse:
    message: str | None = None
    error: str | None = None

    @classmethod
    def from_domain(cls, dom: Result[GreetResult, str]) -> "GreetResponse":
        match dom:
            case Ok(r):
                return cls(message=r.message)
            case Error(e):
                return cls(error=e)


# ─── Wiring ──────────────────────────────────────────────────────────────────


app = Application().mount(
    endpoint(runner)
        .expose(HTTPRouteTrigger("POST", "/greet"), rrc(GreetRequest, GreetResponse).build())
        .expose(CLITrigger("greet", "Greet someone"), rrc(GreetRequest, GreetResponse).build())
)

fastapi_app = fastapi_compile(app)
cli_parser = cli_compile(app, prog="app")


if __name__ == "__main__":
    from emergent.wire.compiler import cli_run
    cli_run(cli_parser)
```

Run:

```bash
# HTTP
uvicorn app:fastapi_app --reload
# Open http://localhost:8000/docs

# CLI
python app.py greet Alice
# → {"message": "Hello, Alice!"}
```

---

# Part 1: Build

Real examples from `examples/roulette/`.

---

## ops — what your program does

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

---

## handlers — how it works

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

---

## runner — wire together

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

---

## requests — boundary in

```python
from dataclasses import dataclass
from typing import Annotated
from emergent.wire.axis.schema.dialects import cli, openapi

@dataclass
class BetRequest:
    token: Annotated[str, openapi.Description("Auth token")]
    bet: Annotated[str, cli.Help("red, black, or 0-36"), cli.Positional()]
    amount: Annotated[int, cli.Help("Bet amount"), cli.Positional()]

    def to_domain(self) -> PlaceBet:
        return PlaceBet(bet=self.bet, amount=self.amount)

    def to_auth(self) -> Authenticate:
        return Authenticate(token=self.token)
```

`to_domain()` converts boundary → op. `to_auth()` extracts auth data.

---

## responses — boundary out

```python
from dataclasses import dataclass
from kungfu import Result, Ok, Error

@dataclass
class BetResponse:
    won: bool | None = None
    payout: int | None = None
    error: str | None = None

    @classmethod
    def from_domain(cls, dom: Result[BetResult, str]) -> "BetResponse":
        match dom:
            case Ok(r):
                return cls(won=r.won, payout=r.payout)
            case Error(e):
                return cls(error=e)
```

`from_domain()` converts op result → boundary.

---

## wiring — expose everywhere

```python
from emergent.wire import endpoint, Application, inject
from emergent.wire.axis.surface.codecs.rrc import rrc
from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger
from emergent.wire.axis.surface.triggers.cli import CLITrigger
from emergent.wire.compiler import fastapi_compile, cli_compile

# Auth middleware
http_auth = (
    inject(AuthUser)
        .using(auth_runner)
        .from_request(HasAuth, lambda req: req.to_auth())
        .on_reject(AuthErrorResponse.from_domain)
        .build()
)

app = Application().mount(
    # Public
    endpoint(auth_runner)
        .expose(HTTPRouteTrigger("POST", "/register"), rrc(RegisterRequest, TokenResponse).build())
        .expose(CLITrigger("register", "Register user"), rrc(RegisterRequest, TokenResponse).build()),

    # Protected
    endpoint(game_runner)
        .expose(HTTPRouteTrigger("POST", "/bet"), rrc(BetRequest, BetResponse).use(http_auth).build())
        .expose(CLITrigger("bet", "Place bet"), rrc(BetRequest, BetResponse).build()),
)

fastapi_app = fastapi_compile(app)
cli_parser = cli_compile(app, prog="roulette")
```

---

## store — data access

```python
from dataclasses import dataclass
from typing import Annotated
from emergent.wire.axis.schema import Identity
from emergent.wire.axis.query import relational_store, MemoryRelationalProvider

@dataclass
class Transaction:
    id: Annotated[str, Identity]
    login: str
    amount: int

class GameStore:
    def __init__(self) -> None:
        self._provider = MemoryRelationalProvider[Transaction]()
        self._transactions = relational_store(Transaction, self._provider)

    async def get_history(self, login: str) -> list[Transaction]:
        return await (
            self._transactions
            .filter(lambda t: t.login == login)
            .order_by(lambda t: t.created_at.desc())
            .limit(10)
            .fetch_many()
        )

    async def insert(self, tx: Transaction) -> None:
        await self._transactions.insert(tx)
```

---

## storage — cache/kv

```python
from emergent.wire.axis.storage import kv, MemoryStorage, JsonCodec

cache = kv(MemoryStorage(), JsonCodec[User]())

await cache.set("alice", user)
user = await cache.get("alice")
```

---

# Part 2: Understand

---

## The five axes

| Action | Axis | You write | Swappable target |
|--------|------|-----------|------------------|
| **Describe** | schema | `Annotated[str, cli.Help(...)]` | compiler (CLI, OpenAPI, SQL) |
| **Access** | query | `store.filter(...).fetch_many()` | provider (Memory, SQL, HTTP) |
| **Persist** | storage | `kv(backend, codec)` | backend (Memory, Redis) |
| **Execute** | ops | `O.Returning[T, E]` + handler | runner |
| **Expose** | surface | `endpoint().expose(trigger, codec)` | trigger (HTTP, CLI, Telegram) |

Each axis = **Language × Target**. Swap target, keep code.

---

## schema

Annotated fields. Each compiler reads its dialect.

```python
from emergent.wire.axis.schema import Identity, Unique, MaxLen
from emergent.wire.axis.schema.dialects import sql, openapi, cli

@dataclass
class User:
    id: Annotated[int, Identity]
    email: Annotated[str,
        Unique, MaxLen(255),        # universal
        sql.Index("idx_email"),     # SQL only
        openapi.Format("email"),    # OpenAPI only
        cli.Help("User email"),     # CLI only
    ]
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

## surface

Codec = execution shape. Trigger = where.

- `rrc` — request → response
- `stateful` — state → ... → Done → execute
- `HTTPRouteTrigger` — REST endpoint
- `CLITrigger` — CLI subcommand
- `TelegrindTrigger` — Telegram bot

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

## Custom dialect

```python
@dataclass(frozen=True, slots=True)
class GrpcFieldNumber(Capability):
    number: int

@dataclass
class User:
    id: Annotated[int, Identity, GrpcFieldNumber(1)]
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

## Custom compiler

```python
def grpc_compile(app: Application) -> GrpcServer:
    pairs = scan(app, GrpcTrigger, RequestResponseCodec)
    for trigger, handler in pairs:
        server.add_method(trigger.service, trigger.method, make_handler(handler))
    return server
```

---

## Stack

| Layer | What |
|-------|------|
| emergent | ops, wire, saga, cache, graph, idempotency |
| [nodnod](https://github.com/timoniq/nodnod) | dependency graphs |
| [combinators.py](https://github.com/prostomarkeloff/combinators.py) | retry, timeout, fallback |
| [kungfu](https://github.com/timoniq/kungfu) | Result, Option |

---

<div align="center">

**Describe. Access. Persist. Execute. Expose.**

**Plain Python. Portable programs.**

</div>

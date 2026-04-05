<div align="center">

# emergent

**Write meaning, not code.**

[![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Types: pyright strict](https://img.shields.io/badge/types-pyright%20strict-blue)](https://github.com/microsoft/pyright)

</div>

A compilation platform where frozen data compiles itself through `fold`. You build compilation languages — not applications. HTTP, CLI, Telegram, OpenAPI, Pydantic, SQL are libraries on the platform. Your custom compilers sit next to them.

```python
@schema_meta(http_crud("/users", Users))
@dataclass
class User:
    id: Annotated[int, Identity]
    name: str
    email: Annotated[str, Unique, MaxLen(255)]
```

5 REST endpoints. Pydantic models. OpenAPI spec. You write fields, `fold` writes everything else.

```bash
uv add git+https://github.com/prostomarkeloff/emergent.git
```

---

## The idea

Frameworks today scatter meaning across files. A `User` lives in a model, a serializer, a view, a URL config, a migration, a test fixture — and none of those files know about each other. An LLM (or a human) has to hold the whole graph in their head to make a correct change.

emergent inverts this. **Everything about a thing is on the thing:**

```python
@schema_meta(
    http_crud("/bounties", Board, ops=(LIST, GET, CREATE)),
    Methods(),
)
@dataclass
class Bounty:
    id: Annotated[int, Identity]
    title: str
    reward: Annotated[int, Min(0)]
    status: Annotated[str, MaxLen(20), Doc("Bounty status"),
                       cli.Help("Current status"), openapi.Description("Status field"),
                       sql.Index("idx_status")]

    @classmethod
    @post("/bounties/{bounty_id}/claim")
    async def claim(cls, db: ..., bounty_id: int, hunter: str) -> Result[Bounty, DomainError]: ...
```

One place. Every concern — validation, CLI help text, OpenAPI description, SQL index, HTTP routes — lives as an annotation on the field it belongs to. The `fold` compiler reads these annotations and produces correct output for each target. No sync bugs. No scattered state. No framework magic to reverse-engineer.

This is **locality by construction**, and it's what makes emergent work for humans and machines alike.

> **[The entire platform is one function.](docs/essence.md)** Compilation, verification, explanation, query execution, derivation — all are `fold` applied to different data. Everything else is consequences.

---

## Platform, not framework

Frameworks prescribe structure. Rails prescribes MVC. Django prescribes models-views-templates. You write code *inside* the framework.

emergent provides primitives. You build *on* the platform:

| Primitive | What it does |
|-----------|-------------|
| `fold(items, ctx, protocol, method)` | Iterate capabilities, dispatch by protocol, accumulate context. 8 lines. |
| `CompilationPhase(ctx_type, protocol, initial)` | Reified fold configuration. One phase = one compilation language. |
| `SchemaCompiler(phases)` | Composable set of phases. Algebra: `+`, `\|`, `-`, `&`. |
| `TargetCompiler(trigger, codecs, pipeline, assemble)` | Surface-level compilation: Application → framework artifact. |

The 4 axes (Schema, Surface, Storage, Query) are **libraries** built on these primitives. `wire.derive` is a library. Your custom compilers sit next to them — not inside a framework, but on the same platform.

### Create your own compiler

A `CompilationPhase` is a language definition. Context = value domain. Protocol = well-formed programs. `fold` = evaluator. Define all three in ~15 lines:

```python
@dataclass(frozen=True, slots=True)
class RankCtx:
    score: float = 1.0
    skip: bool = False

@runtime_checkable
class RankCompilable(Protocol):
    def compile_rank(self, ctx: RankCtx) -> RankCtx: ...

RANK_PHASE = CompilationPhase(RankCtx, RankCompilable, lambda n, t: RankCtx())
```

Now any frozen dataclass with `compile_rank` participates:

```python
@dataclass(frozen=True, slots=True)
class RecencyBoost:
    weight: float = 0.3
    def compile_rank(self, ctx: RankCtx) -> RankCtx:
        return replace(ctx, score=ctx.score * (1 + self.weight))

@dataclass(frozen=True, slots=True)
class AccessControl:
    allowed: bool = True
    def compile_rank(self, ctx: RankCtx) -> RankCtx:
        if not self.allowed:
            return replace(ctx, skip=True)
        return ctx

# Your compiler runs:
ctx = fold((RecencyBoost(), AccessControl()), RankCtx(score=0.9), RankCompilable, "compile_rank")
# → RankCtx(score=1.17, skip=False)
```

You just defined a search ranking language. Zero changes to emergent. The same `fold` that compiles Pydantic models compiles your ranking. The same `SchemaCompiler` algebra composes your phase with any other: `FASTAPI_SCHEMA + RANK_PHASE`.

### Execution: nodnod

emergent has two co-equal primitives. `fold` compiles descriptions. [nodnod](https://github.com/timoniq/nodnod) executes dependency graphs:

```python
@G.node
class FetchPrice:
    @classmethod
    async def __compose__(cls, product: Product, db: Database) -> float:
        return await db.get_price(product.id)

@G.node
class FetchStock:
    @classmethod
    async def __compose__(cls, product: Product, db: Database) -> int:
        return await db.get_stock(product.id)

# FetchPrice and FetchStock have no dependency on each other → run in parallel.
# No asyncio.gather. No concurrency code. The type signatures ARE the graph.
result = await G.compose(BuildReport, product, db)
```

Types are the specification. `fold` reads capabilities from `Annotated`. nodnod reads dependencies from `__compose__` signatures. Both: the structure IS the program.

---

## Why this matters

A `User` in Django lives in a model, a serializer, a view, a URL config, a migration. Five files that must agree. When you change one, you grep for the others and hope. When a new developer joins, they trace the chain by hand. When a coding agent tries to add a field, it hallucinates a signal that doesn't exist because the pattern *looked right* from the three files it saw.

This is the scattered meaning problem. It is not a tooling problem — it is a language problem. The absence of a primitive that lets you state a fact once and have every consumer derive what it needs.

emergent is that primitive. Four properties make it work:

| Property | What it means |
|---|---|
| **Locality** | All concerns for a field live on the field. `Annotated[str, MaxLen(255), Unique, sql.Index()]` — validation, schema, DDL in one place. |
| **Defunctionalization** | Behavior is data. `MaxLen(255)` is a frozen dataclass you can print, compare, serialize. Not a closure. Not a decorator. Data. |
| **Open-world dispatch** | New capabilities participate via `isinstance`. No registration. No plugin system. Implement the protocol → fold picks you up. |
| **Algebraic composition** | Compilers compose: `FASTAPI_SCHEMA + YOUR_PHASE`. Capabilities compose: `(MaxLen(255), Unique)`. No interference between independent concerns. |

The result: any observer — human, LLM, or your future self at 3 AM — reads one declaration and knows everything. One change propagates to all targets. Not by convention. By construction.

---

## Self-describing

emergent's IR reads itself. Every axis has an `explain` system — structured dicts for tools, human-readable text for you:

```python
explain_schema(User)
# === User ===
#   [SchemaName('users')]
#
#   id (int):
#     [Identity]
#
#   email (str):
#     [Unique, MaxLen(255)]
#     cli: Help('Email address')
#     openapi: Description('User email'), Format('email')
#     sql: Index('idx_email')

explain_application(app)
# === Application (3 endpoints) ===
#
#   Endpoint #1 (2 exposures):
#     [POST /api/v1/players] RequestResponseCodec
#       request: RegisterRequest, response: RegisterResponse
#     [register (cli)] RequestResponseCodec
#       request: RegisterRequest, response: RegisterResponse

explain_full(User)  # 3-layer trace
# === User (full trace) ===
#
#   Schema: 3 fields (1 identity)
#     id (int) [Identity]
#     name (str)
#     email (str) [Unique]
#
#   Derivation: 1 pattern
#     Pattern #1: Dialect (11 steps), provider=Users
#       steps: InspectEntity → RequireIdentity → BindProvider → ...
#       ops: List, Get, Create, Update, Patch, Delete
#
#   Surface: 6 exposures across 1 endpoint
#     GET /api/users [ListUserRequest → ListUserResponse]
#     GET /api/users/{id} [GetUserRequest → GetUserResponse]
#     ...
```

Schema, query, storage, surface, compilation trace, derivation pipeline — all explainable. No execution, no side effects. The program describes itself from its own IR.

---

## Verified at import time

`verify` catches semantic contradictions before your code runs:

```python
from emergent.wire.verify import verify_raising

@dataclass
class Sensor:
    id: Annotated[int, Identity]
    name: Annotated[str, MinLen(50), MaxLen(10)]       # ERROR: MinLen > MaxLen
    temp: Annotated[float, Min(200), Max(125)]          # ERROR: Min > Max
    secret: Annotated[str, ReadOnly(), WriteOnly()]      # ERROR: inaccessible field

verify_raising(Sensor)  # VerificationError with all issues
```

Three built-in phases — numeric constraints, length constraints, semantic flags — each running as a standard compilation phase. Open-world: add your own verification phases without modifying emergent.

---

## Four levels of control

```python
# Level 1 — auto CRUD: one decorator, full API
@schema_meta(http_crud("/products", Store))
@dataclass
class Product:
    id: Annotated[int, Identity]
    name: str
    price: float

# Level 2 — CRUD + methods: derive CRUD, hand-write domain logic
@schema_meta(http_crud("/bounties", Board, ops=(LIST, GET, CREATE)), Methods())
@dataclass
class Bounty:
    id: Annotated[int, Identity]
    title: str
    reward: int

    @classmethod
    @post("/bounties/{bounty_id}/claim")
    async def claim(cls, db: ..., bounty_id: int, hunter: str) -> Result[Bounty, DomainError]: ...

# Level 3 — hand-written methods: every endpoint explicit, full control
@schema_meta(Methods())
@dataclass
class Auth:
    @classmethod
    @post("/login")
    async def login(cls, creds: Credentials) -> Result[Token, AuthError]: ...

# Level 4 — raw wire: one endpoint, three targets
endpoint(runner)
    .expose(HTTPRouteTrigger("POST", "/register"), rrc(Req, Resp))
    .expose(CLITrigger("register"), rrc(Req, Resp))
    .expose(TelegrindTrigger(Command("register")), rrc(Req, Resp))
```

Pick what fits. Mix in one app. Drop down a level when you need control, stay high when you don't.

---

## Semantic transforms

Transforms in emergent dispatch on domain *meaning*, not syntax. This is a novel mechanism — no existing macro system combines domain-semantic awareness with compositional algebra:

```python
@schema_meta(
    http_crud("/posts", Posts),
    WithoutDelete(),    # ← removes DELETE op across all targets
    Paginated(20),      # ← adds pagination to ops with Pageable effect
    Sorted(),           # ← adds sorting to LIST
    Filtered("author"), # ← adds exact-match filter
)
@dataclass
class Post:
    id: Annotated[int, Identity]
    title: str
    body: str
    author: str
```

Capabilities stack as arguments in `@schema_meta()` — frozen data in, frozen data out. They compose because they operate on algebraic structure, not string templates or AST nodes.

---

## Examples

| Example | What it shows |
|---|---|
| [`roulette/`](examples/roulette/) | HTTP + CLI + Telegram from one codebase |
| [`cross_compile/`](examples/cross_compile/) | Bridge legacy FastAPI → CLI |
| [`full_stack/`](examples/full_stack/) | Full-stack example |
| [`wiring.py`](examples/wiring.py) | Raw wire: endpoint + trigger + codec |

---

## Tutorial

A story-driven, 27-chapter walkthrough — from first API to handing your codebase to a coding agent.

**[Start here → `docs/tutorial/00-intro.md`](docs/tutorial/00-intro.md)**

| Part | Chapters | What you'll build |
|---|---|---|
| I–IV | [01](docs/tutorial/01-first-api.md)–[14](docs/tutorial/14-whats-next.md) | CRUD, methods, transforms, auth, nested resources, multi-target, custom dialects, raw wire, bridge |
| V–VI | [15](docs/tutorial/15-queries.md)–[18](docs/tutorial/18-scope-and-di.md) | Query axis, providers, ops & runners, scope & DI |
| VII–VIII | [19](docs/tutorial/19-enrichers.md)–[24](docs/tutorial/24-design.md) | Enrichers, storage, compilation internals, stateful codecs, roulette walkthrough, design philosophy |
| IX | [25](docs/tutorial/25-verify-and-explain.md)–[27](docs/tutorial/27-handing-it-to-the-machine.md) | Verify & explain, why emergent is LLM-native, agent workflows |

---

## Docs

| | |
|---|---|
| [`docs/intro.md`](docs/intro.md) | Introduction (EN) |
| [`docs/intro_ru.md`](docs/intro_ru.md) | Введение (RU) |
| [`docs/essence.md`](docs/essence.md) | The essence — one function, one operator |
| [`docs/philosophy.md`](docs/philosophy.md) | Design philosophy |
| [`docs/theory/architecture.md`](docs/theory/architecture.md) | Architecture — theory, invariants, algebraic properties |
| [`docs/internal/wire-reference.md`](docs/internal/wire-reference.md) | Wire reference — axes, capabilities, compile, bridge |
| [`docs/internal/cheatsheet.md`](docs/internal/cheatsheet.md) | Cheatsheet — all axes, every import, every pattern |
| [`docs/theory/universal-derivation.md`](docs/theory/universal-derivation.md) | Derivation — entity → endpoints via fold |
| [`docs/theory/compiler-deep-dive.md`](docs/theory/compiler-deep-dive.md) | Compiler deep-dive — developing custom compilers |
| [`docs/emergent-and-ai.md`](docs/emergent-and-ai.md) | emergent + AI agents |
| [`docs/book/`](docs/book/) | Book — 5-chapter SICP-style deep dive into compilation thinking |

---

## Where we are

emergent is young — started January 2026. Already runs in production. The core architecture (fold, CompilationPhase, SchemaCompiler, TargetCompiler, verify, explain, derive) is stable. What's still growing: the ecosystem, the stdlib, the number of built-in targets and dialects. Breaking changes happen, but we keep them well-motivated.

---

## Stack

| Layer | What |
|---|---|
| [deployme.py](https://github.com/prostomarkeloff/deployme.py) | Application → infrastructure (compose, k8s) |
| **emergent** | **platform**: fold, CompilationPhase, SchemaCompiler, TargetCompiler |
| emergent.wire | **libraries**: axes (schema, surface, storage, query), derive, bridge, verify |
| emergent.graph | **runtime**: Composer, ScopeFamily, RuntimePolicy (Cooperative / WorkStealing) |
| emergent.ops/saga/cache | **patterns**: data-driven dispatch, compensation chains, tiered caching |
| [nodnod](https://github.com/timoniq/nodnod) | typed dependency graphs, auto-parallelization, Either, Scope |
| [combinators.py](https://github.com/prostomarkeloff/combinators.py) | retry, timeout, fallback, race |
| [kungfu](https://github.com/timoniq/kungfu) | Result, Option, LazyCoroResult |

---

<div align="center">

**Define a context. Define a protocol. Call fold.**

**You just created a compilation language.**

</div>

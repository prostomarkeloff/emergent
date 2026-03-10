<div align="center">

# emergent

**Write meaning, not code.**

[![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Types: pyright strict](https://img.shields.io/badge/types-pyright%20strict-blue)](https://github.com/microsoft/pyright)

</div>

A type-algebraic framework where your code is pure domain meaning and compilation produces the rest — HTTP, CLI, Telegram, OpenAPI, Pydantic validation, SQL, RFC 7807 errors. All from the shape of your types.

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

> **[The entire framework is one function.](docs/essence.md)** Compilation, verification, explanation, LLM verification, query execution, derivation, semantic macros — all are the same `fold` applied to different data. Everything else is consequences.

---

## Why this matters now

Coding agents are becoming primary authors of production code. But implicit architectures break them — AI-assisted development is often slower on real repos, developers ship AI code they don't fully understand, and refactoring drops dramatically.

The problem isn't the models. It's the code they're asked to work with. Non-local dependencies, implicit global state, and framework magic require understanding the whole program to change one part. LLMs fail at this — compositional reasoning across scattered files degrades fast.

emergent is designed from the ground up so that **an agent never needs to understand the whole program**. Four structural properties make this work:

| Property | What it means |
|---|---|
| **Locality** | All concerns for a field/entity live on it. O(1) navigation, zero cross-file dependencies. |
| **Defunctionalization** | Behavior is frozen data (dataclasses), not functions. Every capability is inspectable, hashable, serializable. |
| **Semantic dispatch** | Transforms operate on domain *meaning* (effects), not syntax. A `SoftDelete()` transform knows what "delete" means across all targets. |
| **Composition algebra** | Capabilities compose via tuple concatenation (free monoid). All combinations are valid by construction. |

The result: a derivation is ~50 tokens of pure meaning. An LLM doesn't generate boilerplate — it generates *intent*, and `fold` compiles intent into code.

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
| [`docs/architecture.md`](docs/architecture.md) | Architecture — theory, invariants, algebraic properties |
| [`docs/wire-reference.md`](docs/wire-reference.md) | Wire reference — axes, capabilities, compile, bridge |
| [`docs/cheatsheet.md`](docs/cheatsheet.md) | Cheatsheet — all axes, every import, every pattern |
| [`docs/derivelib.md`](docs/derivelib.md) | derivelib reference (deprecated) |
| [`docs/universal-derivation.md`](docs/universal-derivation.md) | Universal derivation — fold_schema, three-phase compilation |
| [`docs/compiler-deep-dive.md`](docs/compiler-deep-dive.md) | Compiler deep-dive — developing & tuning custom compilers |
| [`docs/multi_runtime.md`](docs/multi_runtime.md) | Multi-runtime — open-world graph execution |
| [`docs/property-based.md`](docs/property-based.md) | Property-based testing from entity schemas |
| [`docs/tg-patterns.md`](docs/tg-patterns.md) | Telegram patterns — TGApp, inline, callbacks |
| [`docs/emergent-and-ai.md`](docs/emergent-and-ai.md) | emergent + AI agents |

---

## Where we are

emergent is young — started January 2026, three months in. Already runs in production. The core architecture (IR model, compilers, capabilities, verify, explain, derive) is stable. What's still growing: the ecosystem, the stdlib, the number of built-in targets and dialects. Breaking changes happen, but we keep them well-motivated.

---

## Stack

| Layer | What |
|---|---|
| [deployme.py](https://github.com/prostomarkeloff/deployme.py) | Application → infrastructure (compose, k8s) |
| emergent | ops, wire, derive, saga, cache, graph, idempotency, verify |
| [nodnod](https://github.com/timoniq/nodnod) | dependency graphs |
| [combinators.py](https://github.com/prostomarkeloff/combinators.py) | retry, timeout, fallback |
| [kungfu](https://github.com/timoniq/kungfu) | Result, Option |

---

<div align="center">

**Describe. Access. Persist. Expose.**

**Plain Python. Write meaning, compile anywhere.**

</div>

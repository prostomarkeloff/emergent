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

5 REST endpoints. You write fields, emergent writes everything else.

```bash
uv add git+https://github.com/prostomarkeloff/emergent.git
```

---

## Where we are

emergent is young — started January 2026, on end of Februrary — two months in. emergent + derivelib already run in production. The core architecture (IR model, compilers, capabilities) is stable and expressive enough to describe anything you'd want to build. What's still growing: the ecosystem, the stdlib, the number of built-in targets and dialects. Breaking changes happen, but we try to keep them well-motivated.

This is an **LLM-native framework**. emergent is built with AI agents, and it's designed to be worked on by them. The three-part architecture — typed IR model, fold-based compilers, self-contained capabilities — means an LLM never needs to understand the whole program. It reads the local annotations, understands the local types, and produces correct results. No spooky action at a distance, no implicit global state, no framework magic to reverse-engineer. That's not a side effect of the design — it's a core goal.

---

## Quick taste

```python
# Level 1 — one decorator, full API
@derive(http_crud("/products", provider_node=Store))
@dataclass
class Product:
    id: Annotated[int, Identity]
    name: str
    price: float

# Level 2 — derive CRUD, hand-write domain logic
@derive(
    http_crud("/bounties", provider_node=Board, ops=(LIST, GET, CREATE)),
    methods,
)
@dataclass
class Bounty:
    id: Annotated[int, Identity]
    title: str
    reward: int

    @classmethod
    @post("/bounties/{bounty_id}/claim")
    async def claim(cls, db: ..., bounty_id: int, hunter: str) -> Result[Bounty, DomainError]: ...

# Level 4 — raw wire, one endpoint → three targets
endpoint(runner)
    .expose(HTTPRouteTrigger("POST", "/register"), rrc(Req, Resp))
    .expose(CLITrigger("register"), rrc(Req, Resp))
    .expose(TelegrindTrigger(Command("register")), rrc(Req, Resp))
```

Four levels of control — pure algebra, algebra + methods, pure methods, pure wire. Pick what fits, mix in one app.

---

## Examples

### derivelib

| Example | What it shows |
|---|---|
| [`crud.py`](derivelib/examples/crud.py) | 3 entities, 15 endpoints, zero controllers |
| [`bounties.py`](derivelib/examples/bounties.py) | CRUD + hand-written domain methods |
| [`service.py`](derivelib/examples/service.py) | Pure methods — every endpoint explicit |
| [`multi_target.py`](derivelib/examples/multi_target.py) | Same entity → HTTP and CLI |
| [`nested.py`](derivelib/examples/nested.py) | Nested resources |
| [`query_transforms.py`](derivelib/examples/query_transforms.py) | Pagination, sorting, filtering, search |
| [`task_queue.py`](derivelib/examples/task_queue.py) | Custom dialect in 30 lines |
| [`workflow.py`](derivelib/examples/workflow.py) | State machine from transition map |
| [`ultimate/`](derivelib/examples/ultimate/) | 1 dataclass, 14 endpoints, 7 concerns |

### wire

| Example | What it shows |
|---|---|
| [`roulette/`](examples/roulette/) | HTTP + CLI + Telegram from one codebase |
| [`cross_compile/`](examples/cross_compile/) | Bridge legacy FastAPI → CLI |
| [`wiring.py`](examples/wiring.py) | Raw wire: endpoint + trigger + codec |

---

## Docs

| | |
|---|---|
| [`docs/intro.md`](docs/intro.md) | Introduction (EN) |
| [`docs/intro_ru.md`](docs/intro_ru.md) | Введение (RU) |
| [`docs/wire-reference.md`](docs/wire-reference.md) | Wire reference — axes, capabilities, compile, bridge |
| [`docs/cheatsheet.md`](docs/cheatsheet.md) | Cheatsheet — all axes, every import, every pattern |
| [`docs/derivelib.md`](docs/derivelib.md) | derivelib reference — algebra, fold, ops, transforms |
| [`docs/tg-patterns.md`](docs/tg-patterns.md) | Telegram patterns — TGApp, inline, callbacks |

---

## Stack

| Layer | What |
|---|---|
| [deployme.py](https://github.com/prostomarkeloff/deployme.py) | Application → infrastructure (compose, k8s) |
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

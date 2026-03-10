# Handing It to the Machine

You open Claude Code. You type: "add pagination and auth to the users API." You go make coffee. When you come back, it's done. One capability added to `@schema_meta`. Tests pass. No hallucinated middleware. No phantom signal handlers. No changes to files the agent shouldn't have touched.

This isn't hypothetical. It's what actually happens when a coding agent meets an emergent codebase. This chapter is about why — and how to make it work even better.

---

## What the agent sees

When a coding agent opens your emergent project, it reads one entity and knows everything:

```python
@schema_meta(
    http_crud("/users", Users),
    Paginated(50),
    Sorted(),
)
@dataclass
class User:
    id: Annotated[int, Identity]
    name: Annotated[str, MaxLen(100)]
    email: Annotated[str, Unique]
```

CRUD at `/users`. Paginated. Sorted. Provider is `Users`. Identity field is `id`. Name is max 100 chars. Email is unique. That's everything. No routing file to check. No serializer to find. No middleware to trace. No mixin to unravel. One decorator. One dataclass. Complete picture.

The agent doesn't need to build a mental model of your architecture. The architecture is *right there*, in the syntax. The `@schema_meta` decorator isn't hiding behavior — it's declaring it. The `Annotated` types aren't metadata hints — they're the actual compilation inputs. What you see is what the compiler sees.

## The verify-before-run loop

Here's emergent's secret weapon for agent workflows: everything is inspectable and verifiable before it executes.

The pipeline has natural checkpoints:

1. **Assemble** — build frozen dataclasses (pure data, no side effects)
2. **Verify** — `verify_raising(*entities)` catches contradictions immediately
3. **Inspect** — call `explain_entity(User)` to see the derivation steps, triggers, field specs
4. **Compile** — `compile_derive(User)` + `materialize(ctx)` + `targets.fastapi.compile(app)` is pure and traceable
5. **Inspect again** — `explain(axes)` after `Axes.traced()` shows every fold step
6. **Run** — only now do side effects happen

The agent must adopt `verify` into its workflow. After every change, verify. This isn't optional — it's the agent's primary safety net. Your custom verification phases (see [Chapter 25](25-verify-and-explain.md)) catch domain-specific mistakes that no generic linter ever could.

```python
from emergent.wire.verify import verify_raising
verify_raising(User, Product, Order)  # fails fast on contradictions
```

```python
from emergent.wire.derive import explain_entity
print(explain_entity(User))
# Shows: schema fields, derivation steps, generated endpoints, triggers
```

```python
from emergent.wire.compile import Axes
from emergent.wire.compile._explain import explain

axes = Axes.traced()
fastapi_app = fastapi.compile(app, axes)
print(explain(axes))
# Shows: every capability, every fold step, every context change
```

No "write 200 lines and pray." Write, verify, inspect, compile, inspect, run.

## Tasks that just work

These prompts produce correct results on first try, consistently:

**"Add soft delete to Users."** The agent adds `SoftDelete(field="deleted_at")` to `@schema_meta` and adds `deleted_at: datetime | None = None` to the dataclass. One file. Two lines.

**"Make the API read-only."** Add `Readonly()` to `@schema_meta`. Done.

**"Add rate limiting to mutations only."** Add `EffectRateLimited(policy=...)` to `@schema_meta`. The transform targets only mutation effects. Read endpoints are untouched.

**"Create a CLI version of this API."** The agent adds `cli_crud("user", Users)` to `@schema_meta` and calls `cli.compile(app)`. Same entity, new target. No adapter code.

**"Add a new entity Product with standard CRUD."** The agent copies the User pattern, changes the fields. No routing to configure, no serializer to write, no viewset to register. The pattern is the configuration.

Why do these work? Each task is a **single local change**. The agent reads one file, modifies one decorator or adds one line, and the framework handles the rest. No cross-file coordination. No implicit state to discover. No "also remember to update the URL config."

## Tasks that need guidance

Not everything is one-shot. Be honest about when to help:

**Custom handler templates.** Building a new `SubmitAndProcess` or `SoftDeleteMark` template requires understanding the `HandlerSpec` protocol. Tell the agent: "look at examples for a custom handler template."

**New compilation targets.** Writing a GraphQL compiler or a gRPC target means understanding fold and phases. Point the agent at the compilation docs.

**Complex stateful codecs.** Multi-turn Telegram flows with branching state are genuinely hard. The agent will write a `__transition__` method, but review the state transition logic — that's domain logic, not framework plumbing.

**Cross-entity concerns.** When a transform needs data from two different providers, the agent may need a hint about nodnod scope and how to inject dependencies.

The pattern: when the task is *compose existing pieces*, the agent nails it first try. When the task is *build new primitives from scratch*, give it a pointer to an example.

## Setting up your project

Practical tips for maximum agent effectiveness:

**Keep entities self-contained.** One file per entity or logical group. The agent reads one file, understands one entity, modifies one entity. If your User, Product, and Order are in separate files, the agent never needs to hold all three in context.

**Use `explain()` in tests.** The agent can verify its own work:

```python
def test_user_has_pagination():
    info = explain_entity(User)
    assert "paginated" in info

def test_app_has_expected_endpoints():
    data = application_dict(app)
    paths = [
        exp["trigger"]["path"]
        for ep in data["endpoints"]
        for exp in ep["exposures"]
        if exp["trigger"].get("type") == "HTTPRouteTrigger"
    ]
    assert "/users" in paths
```

**Run tests after every change.** `uv run python -m pytest tests/ -x -q`. The agent should do this automatically. Fast tests + local changes = tight feedback loop.

**Use the levels.** If the agent is struggling with a Level 3 task (custom dialect), check if Level 2 (CRUD + methods) does what you need. Simpler tasks have simpler prompts.

---

## Copy & go

Enough theory. Here's a `CLAUDE.md` you can drop into any emergent project root right now. Copy it, paste it, and your coding agent is set up.

````markdown
# CLAUDE.md — emergent project

## What This Is

emergent is a **programming environment** where code = inspectable data. You assemble frozen dataclasses, fold/compile them into target artifacts (FastAPI, CLI, Telegram). Everything is transparent and verifiable at every step.

## Build & Test

```bash
uv run python -m pytest tests/ -x -q   # Run all tests
uv run python -m pytest tests/test_X.py # Single file
```

## The Universal Pattern

```
frozen dataclasses (ops / capabilities / steps)
    -> fold (isinstance-based protocol dispatch)
    -> context accumulation
    -> compile to target artifact
```

Same pattern at every layer. derive: Entity -> DeriveCtx -> Endpoint. wire: Application -> FastAPI/CLI/TG. Always frozen data in, compiled artifact out.

## How To Add a CRUD Entity

```python
from dataclasses import dataclass
from typing import Annotated
from nodnod import scalar_node
from emergent.wire.axis.schema import Identity, MaxLen, Unique
from emergent.wire.axis.query.providers.memory import MemoryRelationalProvider
from emergent.wire.axis.query import SequenceNextId, MutatingRelationalProvider
from emergent.wire.axis.schema._universal import schema_meta
from emergent.wire.axis.surface import application
from emergent.wire.derive import compile_derive, materialize, http_crud

@scalar_node
class Users:
    @classmethod
    def __compose__(cls) -> MutatingRelationalProvider:
        return MemoryRelationalProvider(key_fn=lambda x: x.id, next_id=SequenceNextId())

@schema_meta(http_crud("/users", Users))
@dataclass
class User:
    id: Annotated[int, Identity]
    name: Annotated[str, MaxLen(100)]
    email: Annotated[str, Unique]

app = application().mount(*[materialize(ctx) for ctx in compile_derive(User)])

from emergent.wire.compile.targets import fastapi
fastapi_app = fastapi.compile(app)
```

## How To Add Features to an Existing Entity

All via capabilities in `@schema_meta(...)` — one line each:

```python
from emergent.wire.derive import (
    Paginated, Sorted, Readonly, ProjectResponse,
    SoftDelete, Timestamped, WithoutDelete,
)

# Paginate:        @schema_meta(http_crud(..., Users), Paginated(50))
# Sort:            @schema_meta(http_crud(..., Users), Sorted())
# Read-only:       @schema_meta(http_crud(..., Users), Readonly())
# Hide fields:     @schema_meta(http_crud(..., Users), ProjectResponse(exclude=("secret",)))
# Stack them:      @schema_meta(http_crud(..., Users), Paginated(50), Sorted(), Readonly())

# Soft delete + timestamps:
@schema_meta(
    http_crud("/users", Users),
    SoftDelete(field="deleted_at"),
    Timestamped(created="created_at", updated="updated_at"),
)
@dataclass
class User:
    id: Annotated[int, Identity]
    name: str
    deleted_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
```

## How To Add a CLI Target

```python
from emergent.wire.derive import cli_crud

@schema_meta(
    http_crud("/users", Users),
    cli_crud("user", Users),
)
@dataclass
class User: ...

from emergent.wire.compile.targets import cli as cli_target
cli_parser = cli_target.compile(app, prog="myapp")
```

## How To Add Hand-Written Methods

```python
from emergent.wire.derive.patterns.methods import Methods, post, get, command
from kungfu import Result, Ok, Error

@schema_meta(http_crud("/bounties", Board), Methods())
@dataclass
class Bounty:
    id: Annotated[int, Identity]
    title: str
    status: str = "open"

    @classmethod
    @post("/bounties/{bounty_id}/claim")
    async def claim(cls, db: Annotated[MutatingRelationalProvider, compose.Node(Board)],
                    bounty_id: int) -> Result[Bounty, DomainError]:
        # domain logic
        return Ok(updated)
```

## How To Write a Raw Wire Endpoint

```python
from emergent.wire.axis.surface import endpoint, application
from emergent.wire.axis.surface.codecs.rrc import rrc
from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger

ep = endpoint(runner).expose(
    HTTPRouteTrigger("GET", "/health"),
    rrc(HealthRequest, HealthResponse),
)
app = application().mount(ep)
```

## Verification Workflow

Always follow this loop — verify and inspect before you run:

1. Assemble frozen dataclasses (no side effects)
2. `verify_raising(*entities)` — catch contradictions at compile time
3. `explain_entity(User)` — inspect derivation steps
4. `compile_derive(User)` + `materialize(ctx)` — pure, no side effects
5. `explain(axes)` after `Axes.traced()` — inspect compilation
6. Run tests / start server

```python
from emergent.wire.verify import verify_raising
verify_raising(User, Product, Order)  # MUST run after every change

from emergent.wire.derive import explain_entity
print(explain_entity(User))

from emergent.wire.compile import Axes
from emergent.wire.compile._explain import explain
axes = Axes.traced()
fastapi_app = fastapi.compile(app, axes)
print(explain(axes))
```

## Critical Rules

1. **Frozen dataclasses everywhere.** All ops, capabilities, steps, effects: `@dataclass(frozen=True, slots=True)`. Use `dataclasses.replace()` to modify. Never mutate.

2. **Result, not exceptions.** `from kungfu import Result, Ok, Error`. Handlers return `Result[T, E]`. Pattern match with `case Ok(v)` / `case Error(e)`.

3. **Effects over names.** Dispatch on effects, not op names:
   ```python
   # WRONG: if op.name == "Create"
   # RIGHT: if has_effect(op.effects, Mutation)
   ```

4. **scope.get() returns a wrapper.**
   ```python
   scope.get(AuthToken)              # wrapper (or None)
   scope.get(AuthToken).value        # the AuthToken instance
   scope.get(AuthToken).value.value  # the token string
   ```

5. **Never hardcode behavior.** All behavior flows through capabilities, codecs, fold. If you need a custom response, make it a capability — not an if-statement in the compiler.

6. **No `Any`, `cast`, `type: ignore`.** Use generics, Protocol, TypeVar with bounds.

7. **Open-world extension.** New capability = frozen dataclass + `compile_*()` methods. Old compilers silently skip unknown capabilities.

## Key Imports

```python
# Core derive
from emergent.wire.axis.schema._universal import schema_meta
from emergent.wire.derive import compile_derive, materialize
from emergent.wire.derive import http_crud, cli_crud
from emergent.wire.derive._crud import LIST, GET, CREATE, UPDATE, PATCH, DELETE
from emergent.wire.derive.patterns.methods import Methods, post, get, put, delete, command
from emergent.wire.derive.patterns.nested import nested_http_crud
from emergent.wire.derive import (
    Paginated, Sorted, Readonly, ProjectResponse,
    SoftDelete, Timestamped, WithoutDelete, Filtered, Searchable,
)
from emergent.wire.derive import explain_entity

# Schema
from emergent.wire.axis.schema import Identity, Unique, Nullable, ReadOnly, Sensitive
from emergent.wire.axis.schema import Min, Max, MinLen, MaxLen, Pattern, OneOf, Doc, Ref
from emergent.wire.axis.schema.dialects import cli, openapi, sql, tg, compose

# Query + providers
from emergent.wire.axis.query import relational, MutatingRelationalProvider, SequenceNextId
from emergent.wire.axis.query.providers.memory import MemoryRelationalProvider

# Wire surface
from emergent.wire.axis.surface import endpoint, application
from emergent.wire.axis.surface.codecs.rrc import rrc
from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger
from emergent.wire.axis.surface.triggers.cli import CLITrigger

# Compile
from emergent.wire.compile import Axes
from emergent.wire.compile.targets import fastapi, cli as cli_target

# Results
from kungfu import Result, Ok, Error

# Effects
from emergent.wire.derive._effects import Read, Mutation, Creates, Updates, Deletes

# Provider node
from nodnod import scalar_node
```

## Choosing the Right Level

| Task | Level | Pattern |
|------|-------|---------|
| Standard CRUD | 1 | `@schema_meta(http_crud(...))` |
| CRUD + domain methods | 2 | `@schema_meta(http_crud(...), Methods())` |
| All hand-written endpoints | 3 | `@schema_meta(Methods())` |
| Multi-target, custom wiring | 4 | `endpoint().expose()` |
| Custom business pattern | any | Custom `DeriveGeneratable` |
````

---

*The framework is the projection. Your domain is the source. And the observer — human or machine — sees exactly what it needs. Nothing hidden. Nothing scattered. Write the shape. Derive the rest.*

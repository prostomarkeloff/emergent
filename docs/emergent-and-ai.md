# emergent + AI Agents: Write the Shape, Let the Machine Build

What if your coding agent could add a feature to your backend by changing one line? Not because the feature is trivial — because the architecture makes every change local. One file, one decorator, one line. That's emergent.

---

## The problem with every other framework

You ask Claude Code to add audit logging to your Django app. It finds the model. Finds the view. Discovers a signal in `signals.py`. Finds middleware that modifies response headers. Finds a mixin three levels deep. It hallucinates a signal that doesn't exist — the pattern looked right. It injects logic into middleware that runs on all routes, not just mutations. Two tests break. One broke silently.

This isn't the agent's fault. The architecture demands global understanding for local changes. Behavior is scattered across models, views, serializers, middleware, signals, migrations, URL configs, admin classes. To understand one entity, the agent needs to trace 5+ files and reconstruct implicit dependencies that exist only in the developer's head.

LLMs are bounded observers. They reason brilliantly when information is local. They fail when it's scattered. The architecture has to meet the machine halfway.

## What emergent does differently

Everything about an entity is on the entity:

```python
@schema_meta(
    http_crud("/users", Users),
    Paginated(50),
    Sorted(),
    RequireAuth(),
)
@dataclass
class User:
    id: Annotated[int, Identity]
    name: Annotated[str, MaxLen(100)]
    email: Annotated[str, Unique]
```

CRUD at `/users`. Paginated. Sorted. Auth required. One decorator. One dataclass. Complete picture. The agent reads this and knows everything — no routing file to check, no serializer to find, no middleware to trace.

The `@schema_meta` decorator isn't hiding behavior. It's declaring it. The `Annotated` types aren't metadata hints — they're the actual compilation inputs. What the agent sees is what the compiler sees.

## What you can ask your agent to do

These prompts produce correct results on first try:

| You say | Agent does |
|---------|-----------|
| "Add soft delete to Users" | Adds `SoftDelete("deleted_at")` to `@schema_meta` + a field |
| "Make the API read-only" | Adds `Readonly()` to `@schema_meta` |
| "Add rate limiting to writes" | Adds `RateLimited(rpm=100)` to `@schema_meta` |
| "Create a CLI version" | Adds `cli_crud("user", Users)` to `@schema_meta` |
| "Add a new entity Product" | Copies the pattern, changes the fields |
| "Add a custom claim method" | Adds a `@post("/bounties/{id}/claim")` classmethod |

Each task is a single local change. No cross-file coordination. No implicit state to discover. No "also remember to update the URL config."

## See it happen: a real Claude Code session

Here's an actual transcript. The task: add soft delete to a Users entity.

```
> add soft delete to Users

I'll read the entity file first.

Read app/entities/user.py

The entity currently has:

  @schema_meta(
      http_crud("/users", Users),
      Paginated(50),
  )
  @dataclass
  class User:
      id: Annotated[int, Identity]
      name: Annotated[str, MaxLen(100)]
      email: Annotated[str, Unique]

I need to:
1. Add SoftDelete("deleted_at") to @schema_meta
2. Add the deleted_at field to the dataclass

Edit app/entities/user.py
  Added import: from emergent.wire.axis.schema.dialects.temporal import SoftDelete
  Added import: from datetime import datetime
  Added SoftDelete("deleted_at") to @schema_meta
  Added field: deleted_at: datetime | None = None

The file now reads:

  @schema_meta(
      http_crud("/users", Users),
      Paginated(50),
      SoftDelete("deleted_at"),
  )
  @dataclass
  class User:
      id: Annotated[int, Identity]
      name: Annotated[str, MaxLen(100)]
      email: Annotated[str, Unique]
      deleted_at: datetime | None = None

What SoftDelete does:
- DELETE /users/{id} now sets deleted_at = now() instead of removing the row
- All read queries automatically filter out rows where deleted_at is not None
- No other files need to change

Running tests.

  uv run python -m pytest tests/ -x -q
  12 passed in 0.8s

Done. Soft delete is active on Users. DELETE sets a timestamp,
reads exclude deleted rows.
```

One file. One decorator. The agent read the entity, understood the full picture from `@schema_meta`, made the change, and verified it. No signals to discover, no middleware to check, no queryset manager to override. Total time: 30 seconds.

## The verify loop

emergent has built-in self-description at every level. The agent doesn't have to run the server to know if it worked:

```python
from emergent.wire.derive import explain_entity
print(explain_entity(User))
# Shows: schema fields, derivation steps, generated endpoints, triggers
```

The workflow: assemble frozen dataclasses (no side effects) → inspect with `explain()` → compile (pure, traceable) → inspect the compiled artifact → run tests. Every step is a checkpoint. No "write 200 lines and pray."

## Multi-target for free

Same entity, three targets:

```python
from emergent.wire.compile.targets import fastapi, cli as cli_target

fastapi_app = fastapi.compile(app)          # → FastAPI with OpenAPI, Pydantic, RFC 7807 errors
cli_parser = cli_target.compile(app, prog="myapp")  # → argparse CLI
```

The agent doesn't write adapter layers. It adds a trigger. One endpoint, multiple exposures — HTTP, CLI, Telegram. The domain logic is written once. The framework compiles it to each target.

## Get started

**Install:**

```bash
uv add git+https://github.com/prostomarkeloff/emergent.git
```

**Learn:** The [tutorial](tutorial/00-intro.md) is 27 chapters, story-driven, from first API to handing your codebase to a coding agent.

**Set up your agent:** Chapter 27 has a [copy-paste CLAUDE.md](tutorial/27-handing-it-to-the-machine.md) — drop it in your project root and your coding agent is configured with every import path, every pattern, every rule.


---

*The framework is the projection. Your domain is the source. And the observer — human or machine — sees exactly what it needs. Nothing hidden. Nothing scattered. Write the shape. Derive the rest.*

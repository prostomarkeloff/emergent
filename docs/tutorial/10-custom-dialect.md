# Custom Dialects

Here's the secret that took me a while to see: **CRUD is not special.**

`http_crud` is 6 `Op` descriptors with handler templates, bundled with HTTP triggers. That's it. It's one dialect built from generic primitives. You can build your own dialect for anything — a task queue, an event pipeline, a game server, a monitoring dashboard. The primitives are the same.

Let's build a task queue to prove it.

---

## The task queue dialect

Tasks are submitted, processed in the background, and their status can be polled. Three operations:
- **Create** — submit a task, start processing
- **Get** — poll status by ID
- **List** — see all tasks

We need a custom handler template for Create (because it needs to kick off background processing), but Get and List are just `FetchOneById` and `FetchMany` — same as CRUD.

```python
# task_queue.py
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated

from kungfu import Ok, Result
from nodnod import scalar_node

from emergent.wire.axis.query import MutatingRelationalProvider, SequenceNextId
from emergent.wire.axis.query.providers.memory import MemoryRelationalProvider
from emergent.wire.axis.schema import Identity

from derivelib import (
    Op, derive, build_application_from_decorated, dialect,
    HTTPTriggers, CLITriggers, HandlerSpec,
    required_non_id, entity_response, id_only, list_response, no_fields,
    Read, Creates, Idempotent,
    FetchMany, FetchOneById,
)
from derivelib._ctx import OperationHandler
from derivelib._errors import DomainError
from derivelib._protocols import HasProvider


# ── The custom handler template ──────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class SubmitAndProcess[R]:
    """Insert entity, fire background processor."""

    processor: Callable[..., Awaitable[R]]
    background: bool = True

    def build[E](self, spec: HandlerSpec[E]) -> OperationHandler[E, DomainError]:
        import dataclasses as _dc

        entity_type = spec.entity
        id_names = spec.identity_names
        id_set = set(id_names)
        proc, bg = self.processor, self.background

        # Structural discovery: required non-identity fields = user input
        inputs = [
            f.name for f in _dc.fields(entity_type)
            if f.name not in id_set
            and f.default is _dc.MISSING
            and f.default_factory is _dc.MISSING
        ]
        all_names = [f.name for f in _dc.fields(entity_type)]

        def _rebuild(obj: E, **kw: str | int) -> E:
            data = {n: getattr(obj, n) for n in all_names}
            data.update(kw)
            return entity_type(**data)

        async def handler(op: HasProvider[E]) -> Result[E, DomainError]:
            # Build entity from request fields
            data = {f: getattr(op, f) for f in inputs}
            for name in id_names:
                data[name] = 0
            task = entity_type(**data)

            # Assign ID and insert
            provider = op.provider
            if isinstance(provider, MemoryRelationalProvider):
                task = _rebuild(task, **{id_names[0]: await provider.next_id()})
            inserted = await provider.insert(task)

            # Process
            async def run() -> None:
                running = _rebuild(inserted, status="running")
                await provider.update(running)
                try:
                    result = await proc(inserted)
                    await provider.update(
                        _rebuild(running, status="done", result=str(result))
                    )
                except Exception as e:
                    await provider.update(
                        _rebuild(running, status="failed", error=str(e))
                    )

            if bg:
                asyncio.create_task(run())
            else:
                await run()

            return Ok(inserted)

        return handler


# ── The dialect: 3 ops ───────────────────────────────────────────────────────

def _task_ops[R](
    processor: Callable[..., Awaitable[R]], background: bool = True,
) -> tuple[Op, ...]:
    return (
        Op("Create", required_non_id(), entity_response(),
           SubmitAndProcess(processor, background=background),
           effects=(Creates(),)),
        Op("Get", id_only(), entity_response(),
           FetchOneById(), effects=(Read(), Idempotent())),
        Op("List", no_fields(), list_response(),
           FetchMany(), effects=(Read(),)),
    )


def http_task_queue[R](
    path: str, provider_node: type, processor: Callable[..., Awaitable[R]],
) -> ...:
    return dialect(
        *_task_ops(processor),
        triggers=HTTPTriggers(path),
        provider_node=provider_node,
    )


def cli_task_queue[R](
    prefix: str, provider_node: type, processor: Callable[..., Awaitable[R]],
) -> ...:
    return dialect(
        *_task_ops(processor, background=False),
        triggers=CLITriggers(prefix),
        provider_node=provider_node,
    )
```

That's the dialect. ~80 lines. Most of it is the `SubmitAndProcess` template. The dialect itself is just `_task_ops` (3 `Op` descriptors) plus `dialect()` (the smart constructor that adds schema inspection and provider binding).

## Using it

```python
_store: MemoryRelationalProvider[ImageResize] = MemoryRelationalProvider(
    key_fn=lambda x: x.id, next_id=SequenceNextId(),
)

@scalar_node
class Tasks:
    @classmethod
    def __compose__(cls) -> MutatingRelationalProvider[ImageResize]:
        return _store


async def resize_image(task: ImageResize) -> str:
    await asyncio.sleep(2)
    return f"resized {task.url} to {task.width}x{task.height}"


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
# Submit a task
curl -X POST http://localhost:8000/tasks \
     -H 'Content-Type: application/json' \
     -d '{"url": "https://example.com/img.png", "width": 800, "height": 600}'
# {"id": 1, "url": "...", "status": "pending", ...}

# Poll (after 2 seconds)
curl http://localhost:8000/tasks/1
# {"id": 1, ..., "status": "done", "result": "resized ... to 800x600"}

# List all
curl http://localhost:8000/tasks
```

Same `@derive`. Same `build_application_from_decorated`. Same `targets.fastapi.compile`. Different dialect. Different behavior. Same algebra.

## The `dialect()` smart constructor

When you call `dialect(*ops, triggers=..., provider_node=...)`, it:

1. Prepends schema preamble: `inspect_entity()`, `require_identity()`
2. Prepends query setup: `bind_provider(node)`, `base_query()`
3. Adds `provider` field to all ops (so handlers can access the database)
4. Pairs each `Op` with a trigger from the trigger generator
5. Returns a `Dialect` — which is a `Pattern`, meaning it has `.compile(entity)` and `.chain(transform)`

You get all the framework machinery for free: schema inspection, provider binding, identity validation, transforms. Your custom dialect only needs to define what's *unique* — the ops and their handler templates.

---

**Next:** [State Machines →](11-state-machines.md)

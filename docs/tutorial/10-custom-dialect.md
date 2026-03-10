# Custom Dialects

Here's the secret that took me a while to see: **CRUD is not special.**

`http_crud` is a `SchemaCapability` implementing `DeriveGeneratable`. It bundles 6 `Op` descriptors with handler templates and HTTP triggers. That's it. It's one dialect built from generic primitives. You can build your own dialect for anything — a task queue, an event pipeline, a game server, a monitoring dashboard. The primitives are the same.

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
from emergent.wire.axis.schema._universal import SchemaCapability, schema_meta
from emergent.wire.axis.surface import application
from emergent.wire.derive import compile_derive, materialize
from emergent.wire.derive._ctx import DeriveCtx, OperationHandler
from emergent.wire.derive._crud import _provider_fields
from emergent.wire.derive._effects import Creates, DomainError, Idempotent, Read
from emergent.wire.derive._handler import FetchMany, FetchOneById, HandlerSpec
from emergent.wire.derive._opspec import Op, generate_specs
from emergent.wire.derive._project import entity_response, id_only, list_response, non_id
from emergent.wire.derive._query_strategy import ProviderInjection, RelationalStrategy
from emergent.wire.derive._trigger import CLITriggers, HTTPTriggers, TriggerGen
from emergent.wire.axis.query import relational


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

        async def handler(op: object) -> Result[E, DomainError]:
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


# ── The dialect: a DeriveGeneratable SchemaCapability ────────────────────────

@dataclass(frozen=True, slots=True)
class TaskQueue(SchemaCapability):
    """Task queue dialect — submit, poll, list."""

    triggers: TriggerGen
    provider_node: type
    processor: Callable[..., Awaitable[object]]
    background: bool = True

    def compile_derive_generate(self, ctx: DeriveCtx) -> DeriveCtx:
        if not ctx.identity_fields:
            raise ValueError(f"{ctx.entity.__name__} needs Identity field for TaskQueue")

        prov_op_field, prov_req_field = _provider_fields(self.provider_node)
        from dataclasses import replace
        ctx = replace(
            ctx,
            query_strategy=RelationalStrategy(
                provider_node=self.provider_node,
                base_query=relational(ctx.entity),
                injection=ProviderInjection(
                    op_field=prov_op_field,
                    request_field=prov_req_field,
                ),
            ),
        )

        from emergent.wire.derive._project import no_fields

        ops = (
            Op("Create", non_id(), entity_response(),
               SubmitAndProcess(self.processor, background=self.background),
               effects=(Creates(),)),
            Op("Get", id_only(), entity_response(),
               FetchOneById(), effects=(Read(), Idempotent())),
            Op("List", no_fields(), list_response(),
               FetchMany(), effects=(Read(),)),
        )

        return generate_specs(
            ctx,
            ops=ops,
            triggers=self.triggers,
            capabilities=(),
            source="TaskQueue",
            extra_op_fields=(prov_op_field,),
            extra_request_fields=(prov_req_field,),
        )


def http_task_queue[R](
    path: str, provider_node: type, processor: Callable[..., Awaitable[R]],
) -> TaskQueue:
    return TaskQueue(
        triggers=HTTPTriggers(path),
        provider_node=provider_node,
        processor=processor,
    )


def cli_task_queue[R](
    prefix: str, provider_node: type, processor: Callable[..., Awaitable[R]],
) -> TaskQueue:
    return TaskQueue(
        triggers=CLITriggers(prefix),
        provider_node=provider_node,
        processor=processor,
        background=False,
    )
```

That's the dialect. The `TaskQueue` is a `SchemaCapability` implementing `DeriveGeneratable`. It creates a `DeriveCtx`, sets up the query strategy, defines 3 ops, and calls `generate_specs()` — the same function `CRUD` uses internally.

## Using it

```python
@scalar_node
class Tasks:
    @classmethod
    def __compose__(cls) -> MutatingRelationalProvider[ImageResize]:
        return MemoryRelationalProvider(key_fn=lambda x: x.id, next_id=SequenceNextId())


async def resize_image(task: ImageResize) -> str:
    await asyncio.sleep(2)
    return f"resized {task.url} to {task.width}x{task.height}"


@schema_meta(
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

Same `@schema_meta`. Same `compile_derive` + `materialize`. Same `targets.fastapi.compile`. Different dialect. Different behavior. Same algebra.

## Building a custom DeriveGeneratable

When you build a custom `SchemaCapability` implementing `compile_derive_generate`, you:

1. Set up the query strategy (provider node, base query)
2. Define your ops — each with a name, input projection, response spec, handler template, and effects
3. Call `generate_specs()` — the shared loop that pairs ops with triggers and appends `OpSpec`s to the context

You get all the framework machinery for free: schema inspection (fields are already on `DeriveCtx`), provider binding, identity validation, transforms. Your custom dialect only needs to define what's *unique* — the ops and their handler templates.

---

**Next:** [State Machines →](11-state-machines.md)

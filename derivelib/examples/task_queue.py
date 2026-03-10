"""Build your own dialect in 30 lines.

CRUD is not special. It's 5 Ops with handler templates.
This task queue is 3 Ops with a custom SubmitAndProcess handler.
Same algebra, different dialect.

    uv run python -m derivelib.examples.task_queue http
    uv run python -m derivelib.examples.task_queue cli task-create https://example.com/img.png 800 600
    uv run python -m derivelib.examples.task_queue cli task-list
"""

from __future__ import annotations

import asyncio
import os
import pickle
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace as dc_replace
from typing import Annotated, TYPE_CHECKING

from kungfu import Ok, Result
from nodnod import scalar_node

from emergent.wire.axis.query import MutatingRelationalProvider, RelationalQuerySet, SequenceNextId, relational
from emergent.wire.axis.query.providers.memory import MemoryRelationalProvider
from emergent.wire.axis.schema import Identity
from emergent.wire.axis.schema._universal import SchemaCapability

from emergent.wire.derive._ctx import DeriveCtx
from emergent.wire.derive._crud import _provider_fields
from emergent.wire.derive._effects import Creates, Idempotent, Read
from emergent.wire.derive._handler import FetchMany, FetchOneById, HandlerSpec, HasProvider
from emergent.wire.derive._opspec import Op, OpSpec
from emergent.wire.derive._project import entity_response, id_only, list_response, no_fields, required_non_id
from emergent.wire.derive._query_strategy import ProviderInjection, RelationalStrategy
from emergent.wire.derive._trigger import CLITriggers, HTTPTriggers, TriggerGen

from derivelib import derive, build_application_from_decorated

if TYPE_CHECKING:
    from emergent.wire.derive._errors import DomainError


# --- handler template: insert + process (background or foreground) ---

@dataclass(frozen=True, slots=True)
class SubmitAndProcess[R]:
    """Insert entity, run processor. Schema introspection finds input fields."""

    processor: Callable[..., Awaitable[R]]
    background: bool = True
    status_field: str = "status"
    result_field: str = "result"
    error_field: str = "error"

    def build[EntityT](self, spec: HandlerSpec[EntityT]) -> Callable[..., Awaitable[Result[EntityT, DomainError]]]:
        import dataclasses as _dc
        entity_type = spec.entity
        id_names = spec.identity_names
        id_set = set(id_names)
        proc, bg = self.processor, self.background
        sf, rf, ef = self.status_field, self.result_field, self.error_field
        # structural discovery: required non-identity fields = user input
        inputs = [f.name for f in _dc.fields(entity_type) if f.name not in id_set and f.default is _dc.MISSING and f.default_factory is _dc.MISSING]
        all_field_names = [f.name for f in _dc.fields(entity_type)]

        def _rebuild(obj: EntityT, **overrides: str | int) -> EntityT:
            """Reconstruct entity with overrides (avoids dc_replace on TypeVar)."""
            data = {name: getattr(obj, name) for name in all_field_names}
            data.update(overrides)
            return entity_type(**data)

        async def handler(op: HasProvider[EntityT]) -> Result[EntityT, DomainError]:
            data: dict[str, str | int] = {f: getattr(op, f) for f in inputs}
            for name in id_names:
                data[name] = 0
            task: EntityT = entity_type(**data)
            provider = op.provider
            if isinstance(provider, MemoryRelationalProvider):
                task = _rebuild(task, **{id_names[0]: await provider.next_id()})
            inserted = await provider.insert(task)

            async def run() -> None:
                running = _rebuild(inserted, **{sf: "running"})
                await provider.update(running)
                try:
                    result = await proc(inserted)
                    await provider.update(_rebuild(running, **{sf: "done", rf: str(result)}))
                except Exception as e:
                    await provider.update(_rebuild(running, **{sf: "failed", ef: str(e)}))

            if bg:
                asyncio.create_task(run())
            else:
                await run()
            return Ok(inserted)

        return handler


# --- the ops: 3 operations, transport-agnostic ---

def _task_ops[R](processor: Callable[..., Awaitable[R]], background: bool = True) -> tuple[Op, ...]:
    return (
        Op("Create", required_non_id(), entity_response(),
           SubmitAndProcess(processor, background=background), effects=(Creates(),)),
        Op("Get", id_only(), entity_response(), FetchOneById(), effects=(Read(), Idempotent())),
        Op("List", no_fields(), list_response(), FetchMany(), effects=(Read(),)),
    )


# --- TaskQueue as SchemaCapability (DeriveGeneratable) ---

@dataclass(frozen=True, slots=True)
class TaskQueueCapability[R](SchemaCapability):
    """Task queue dialect — 3 ops (Create/Get/List) with custom submit-and-process handler."""

    triggers: TriggerGen
    provider_node: type
    processor: Callable[..., Awaitable[R]]
    background: bool = True

    def compile_derive_generate(self, ctx: DeriveCtx) -> DeriveCtx:  # type: ignore[type-arg]
        prov_op_field, prov_req_field = _provider_fields(self.provider_node)
        ctx = dc_replace(
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

        for op in _task_ops(self.processor, background=self.background):
            trigger_result = self.triggers(ctx.entity, op)
            if trigger_result is None:
                continue
            triggers = (trigger_result,) if not isinstance(trigger_result, tuple) else trigger_result

            in_fields = op.input_proj.project(ctx)
            annotated_fields = ctx.annotated_field_types(only=set(in_fields.keys()))

            for t in triggers:
                spec = OpSpec(
                    name=op.name,
                    entity_name=ctx.entity.__name__,
                    input_fields=in_fields,
                    request_fields=dict(annotated_fields),
                    response_spec=op.output,
                    handler_template=op.handler_template,
                    trigger=t,
                    capabilities=op.capabilities,
                    effects=op.effects,
                    codec_factory=op.codec_factory,
                    extra_op_fields=(prov_op_field, *op.extra_op_fields),
                    extra_request_fields=(prov_req_field, *op.extra_request_fields),
                    scope_fields=op.scope_fields,
                    source="TaskQueue",
                )
                ctx = ctx.add_spec(spec)

        return ctx


def http_task_queue[R](path: str, provider_node: type, processor: Callable[..., Awaitable[R]]) -> TaskQueueCapability[R]:
    return TaskQueueCapability(HTTPTriggers(path), provider_node, processor)


def cli_task_queue[R](prefix: str, provider_node: type, processor: Callable[..., Awaitable[R]]) -> TaskQueueCapability[R]:
    return TaskQueueCapability(CLITriggers(prefix), provider_node, processor, background=False)


# --- persistent provider (pickle) ---

class PickleProvider[T](MemoryRelationalProvider[T]):
    def __init__(
        self,
        path: str,
        *,
        key_fn: Callable[[T], int] | None = None,
        next_id: SequenceNextId | None = None,
    ) -> None:
        super().__init__(key_fn=key_fn, next_id=next_id)
        self._path, self._loaded = path, False

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if os.path.exists(self._path):
            with open(self._path, "rb") as f:
                s = pickle.load(f)
            self._data = s.get("data", [])
            if isinstance(self._next_id, SequenceNextId) and "counter" in s:
                setattr(self._next_id, "_counter", s["counter"])

    def _save(self) -> None:
        d: dict[str, list[T] | int] = {"data": self._data}
        if isinstance(self._next_id, SequenceNextId):
            d["counter"] = getattr(self._next_id, "_counter")
        with open(self._path, "wb") as f:
            pickle.dump(d, f)

    async def fetch_one(self, query: RelationalQuerySet[T]) -> T | None:
        self._load(); return await super().fetch_one(query)

    async def fetch_many(self, query: RelationalQuerySet[T]) -> list[T]:
        self._load(); return await super().fetch_many(query)

    async def insert(self, entity: T) -> T:
        self._load(); r = await super().insert(entity); self._save(); return r

    async def update(self, entity: T) -> T:
        self._load(); r = await super().update(entity); self._save(); return r

    async def delete(self, entity: T) -> None:
        self._load(); await super().delete(entity); self._save()

    async def next_id(self) -> int:
        self._load(); return await super().next_id()


# --- usage ---

_store: PickleProvider[ImageResize] = PickleProvider(
    ".task_queue.pickle", key_fn=lambda x: x.id, next_id=SequenceNextId(),
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


app = build_application_from_decorated(ImageResize)

from emergent.wire.compile import targets  # noqa: E402

fastapi_app = targets.fastapi.compile(app)


from emergent.wire.compile.targets.cli import TYPED_CLI  # noqa: E402


if __name__ == "__main__":
    import sys

    mode = sys.argv[1] if len(sys.argv) > 1 else "http"

    if mode == "http":
        print("\n  POST /tasks -> submit, GET /tasks/{id} -> status, GET /tasks -> list\n")
        import uvicorn
        uvicorn.run(fastapi_app, host="0.0.0.0", port=8000)

    elif mode == "cli":
        parser = targets.cli.cli_compile(app, prog="taskq", compiler=TYPED_CLI)
        sys.exit(targets.cli.cli_run(parser, sys.argv[2:]))

    else:
        print("Usage: python -m derivelib.examples.task_queue {http|cli} [args]")

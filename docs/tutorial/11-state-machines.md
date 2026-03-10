# State Machines

Another custom dialect. This time we're not deriving CRUD or task processing — we're deriving *validated state transitions*.

An order goes from draft to pending to approved to shipped. Or it gets rejected. Or cancelled. The transitions have rules: you can't ship a draft, you can't approve something that's already shipped. Normally you'd write validation logic in every handler. With a custom `DeriveGeneratable`, you declare the rules and the handlers generate themselves.

---

## The workflow dialect

The idea: define transitions as data, generate one endpoint per transition with automatic validation.

```python
# workflow.py
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Annotated

from kungfu import Ok, Error, Result
from nodnod import scalar_node

from emergent.wire.axis.query import MutatingRelationalProvider, SequenceNextId
from emergent.wire.axis.query.providers.memory import MemoryRelationalProvider
from emergent.wire.axis.schema import Identity
from emergent.wire.axis.schema._universal import SchemaCapability, schema_meta
from emergent.wire.axis.surface import application
from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger
from emergent.wire.derive import compile_derive, materialize, ExposureBuilder, exposure
from emergent.wire.derive._ctx import DeriveCtx
from emergent.wire.derive._effects import Creates, Mutation, DomainError, InvalidData, NotFound
from emergent.wire.derive._query_helpers import fetch_by_identity, provider_field


# ── Transition DSL ───────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class Transition:
    name: str
    from_states: tuple[str, ...]
    to_state: str
```

Five transitions. A name, where it can start from, where it goes.

```python
# ── The DeriveGeneratable capability ─────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class WorkflowPattern(SchemaCapability):
    base_path: str
    provider_node: type
    state_field: str
    transitions: tuple[Transition, ...]

    def compile_derive_generate(self, ctx: DeriveCtx) -> DeriveCtx:
        entity = ctx.entity
        id_names = tuple(ctx.identity_fields.keys())
        non_id_names = tuple(
            n for n in ctx.fields if n not in ctx.identity_fields
        )

        # Create endpoint
        init_state = self.transitions[0].from_states[0] if self.transitions else "draft"
        ctx = self._add_create(ctx, entity, id_names, non_id_names, init_state)

        # One transition endpoint per declared transition
        for tr in self.transitions:
            ctx = self._add_transition(ctx, entity, id_names, non_id_names, tr)

        return ctx

    def _add_create(self, ctx, entity, id_names, non_id_names, init_state):
        path = f"{self.base_path}/create"
        # ... builds a create endpoint with initial state
        # (see examples for full implementation)
        return ctx

    def _add_transition(self, ctx, entity, id_names, non_id_names, tr):
        sf = self.state_field

        async def handler(op: object) -> Result[object, DomainError]:
            obj = await fetch_by_identity(op.provider, entity, op, id_names)
            if obj is None:
                return Error(NotFound(
                    entity=entity.__name__,
                    id={n: getattr(op, n) for n in id_names},
                ))
            cur = getattr(obj, sf)
            if cur not in tr.from_states:
                return Error(InvalidData(
                    entity=entity.__name__,
                    reason=f"cannot '{tr.name}': state is '{cur}', "
                           f"expected one of {tr.from_states}",
                ))
            updated = entity(**{
                **{n: getattr(obj, n) for n in (*id_names, *non_id_names)},
                sf: tr.to_state,
            })
            await op.provider.update(updated)
            return Ok(updated)

        # Build the operation and exposure, add to ctx
        # ... (using ctx.add_operation or generate_specs)
        return ctx
```

Each transition produces one endpoint. The handler: fetch the entity, check current state against allowed `from_states`, update to `to_state`, save. The `WorkflowPattern` implements `DeriveGeneratable` — it contributes endpoints to the derive context during Phase 1.

## Using it

```python
@scalar_node
class Orders:
    @classmethod
    def __compose__(cls) -> MutatingRelationalProvider:
        return MemoryRelationalProvider(key_fn=lambda x: x.id, next_id=SequenceNextId())


@schema_meta(WorkflowPattern(
    "/orders", provider_node=Orders, state_field="status",
    transitions=(
        Transition("submit",  ("draft",),    "pending"),
        Transition("approve", ("pending",),  "approved"),
        Transition("reject",  ("pending",),  "rejected"),
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


app = application().mount(*[materialize(ctx) for ctx in compile_derive(Order)])
from emergent.wire.compile import targets
fastapi_app = targets.fastapi.compile(app)
```

```bash
curl -X POST http://localhost:8000/orders/create \
     -H 'Content-Type: application/json' \
     -d '{"customer": "Alice", "amount": 99.99}'
# {"id": 1, "state": "draft"}

curl -X POST http://localhost:8000/orders/1/submit
# {"state": "pending"}

curl -X POST http://localhost:8000/orders/1/ship
# {"type": "about:blank", "title": "Invalid Data", "status": 422,
#  "detail": "cannot 'ship': state is 'pending', expected one of ('approved',)"}

curl -X POST http://localhost:8000/orders/1/approve
# {"state": "approved"}

curl -X POST http://localhost:8000/orders/1/ship
# {"state": "shipped"}
```

Five transitions, six endpoints, validated. emergent doesn't know about state machines. The `WorkflowPattern` does. And it's built from the same pieces as CRUD — schema inspection via `DeriveCtx`, surface contributions via `add_operation`, handler functions, trigger generation.

That's the thesis: the primitives are general enough to express any derivation pattern. CRUD, task queues, state machines, event sourcing — they're all just different `DeriveGeneratable` capabilities of the same algebra.

---

**Next:** [Raw Wire →](12-raw-wire.md)

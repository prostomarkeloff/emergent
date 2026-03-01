# State Machines

Another custom dialect. This time we're not deriving CRUD or task processing — we're deriving *validated state transitions*.

An order goes from draft to pending to approved to shipped. Or it gets rejected. Or cancelled. The transitions have rules: you can't ship a draft, you can't approve something that's already shipped. Normally you'd write validation logic in every handler. With a custom dialect, you declare the rules and the handlers generate themselves.

---

## The workflow dialect

The idea: define transitions as data, generate one endpoint per transition with automatic validation.

```python
# workflow.py (full implementation in derivelib/examples/workflow.py)
from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from kungfu import Ok, Error, Result

from emergent.wire.axis.schema import Identity
from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger

from derivelib import (
    derive, build_application_from_decorated, memory_node,
    exposure, SurfaceCtx, Derivation,
    fetch_by_identity, id_path, provider_field,
    NotFound, InvalidData, DomainError,
)
from derivelib._effects import Creates, Mutation
from derivelib.axes.schema import inspect_entity, require_identity
from derivelib._protocols import HasProvider


# ── Transition DSL ───────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class Transition:
    name: str
    from_states: tuple[str, ...]
    to_state: str
```

Five transitions. A name, where it can start from, where it goes.

```python
# ── Surface step: one endpoint per transition ────────────────────────────────

@dataclass(frozen=True, slots=True)
class TransitionStep:
    base_path: str
    transition: Transition
    state_field: str
    provider_node: type

    @property
    def name(self) -> str:
        return self.transition.name

    def derive_surface[E](self, ctx: SurfaceCtx[E]) -> SurfaceCtx[E]:
        schema = ctx.schema
        entity = schema.entity
        id_names = schema.identity_names()
        non_id_names = tuple(schema.non_identity_fields().keys())
        tr, sf = self.transition, self.state_field

        async def handler(op: HasProvider[E]) -> Result[E, DomainError]:
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

        req_fields = {n: info.base_type for n, info in schema.identity_fields.items()}
        req_fields["provider"] = provider_field(self.provider_node)
        path = f"{self.base_path}/{id_path(id_names)}/{tr.name}"
        return ctx.add_exposure(
            exposure(tr.name, entity)
            .request(**req_fields)
            .response(state=str)
            .handler(handler)
            .trigger(HTTPRouteTrigger("POST", path))
        )
```

Each `TransitionStep` implements `SurfaceDerivable` — it contributes one endpoint to the surface axis. The handler: fetch the entity, check current state against allowed `from_states`, update to `to_state`, save.

```python
# ── The pattern ──────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class WorkflowPattern:
    base_path: str
    provider_node: type
    state_field: str
    transitions: tuple[Transition, ...]

    def compile(self, entity: type) -> Derivation:
        init = self.transitions[0].from_states[0] if self.transitions else "draft"
        return (
            inspect_entity(), require_identity(),
            WorkflowCreateStep(self.base_path, self.state_field, init, self.provider_node),
            *(TransitionStep(self.base_path, tr, self.state_field, self.provider_node)
              for tr in self.transitions),
        )
```

`WorkflowPattern` is a `Pattern` — it has `compile(entity) -> Derivation`. The derivation is: schema inspection + a create step + one transition step per declared transition.

## Using it

```python
Orders = memory_node()


@derive(WorkflowPattern(
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


app = build_application_from_decorated(Order)
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

Five transitions, six endpoints, validated. emergent doesn't know about state machines. The `WorkflowPattern` does. And it's built from the same pieces as CRUD — schema inspection, surface steps, handler functions, trigger generation.

That's the thesis: the primitives are general enough to express any derivation pattern. CRUD, task queues, state machines, event sourcing — they're all just different dialects of the same algebra.

---

**Next:** [Raw Wire →](12-raw-wire.md)

"""5 transitions. 6 endpoints. Validated.

Declare state machine rules. Get validated API endpoints.
Invalid transitions return errors. No manual validation code.

    uv run python -m derivelib.examples.workflow

    curl -X POST http://localhost:8000/orders/create -H 'Content-Type: application/json' \
         -d '{"customer": "Alice", "amount": 99.99}'
    curl -X POST http://localhost:8000/orders/1/submit
    curl -X POST http://localhost:8000/orders/1/approve
    curl -X POST http://localhost:8000/orders/1/ship
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated

from kungfu import Ok, Error, Result

from emergent.wire.axis.schema import Identity
from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger

from derivelib import (
    derive, build_application_from_decorated, memory_node,
    exposure, SurfaceCtx, Derivation,
    fetch_by_identity, id_path, provider_field,
    NotFound, InvalidData, DomainError,
)
from derivelib.axes.schema import inspect_entity, require_identity
from derivelib._protocols import HasProvider

if TYPE_CHECKING:
    from collections.abc import Mapping


# --- transition DSL ---

@dataclass(frozen=True, slots=True)
class Transition:
    name: str
    from_states: tuple[str, ...]
    to_state: str


# --- surface steps: create + transition ---

@dataclass(frozen=True, slots=True)
class WorkflowCreateStep:
    base_path: str
    state_field: str
    initial_state: str
    provider_node: type

    def derive_surface[EntityT](self, ctx: SurfaceCtx[EntityT]) -> SurfaceCtx[EntityT]:
        schema = ctx.schema
        entity = schema.entity
        id_names = schema.identity_names()
        non_id = schema.non_identity_fields()
        sf, init = self.state_field, self.initial_state

        fields = {f.name: f.base_type for f in non_id.values()}
        fields["provider"] = provider_field(self.provider_node)
        names = list(non_id.keys())

        async def handler(op: HasProvider[EntityT]) -> Result[EntityT, DomainError]:
            d = {n: getattr(op, n) for n in names}
            for name in id_names:
                d[name] = 0
            d[sf] = init
            return Ok(await op.provider.insert(entity(**d)))

        resp_fields: dict[str, type] = {n: info.base_type for n, info in schema.identity_fields.items()}
        resp_fields["state"] = str
        return ctx.add_exposure(
            exposure("create", entity)
            .request(**fields).response(**resp_fields)
            .handler(handler).trigger(HTTPRouteTrigger("POST", f"{self.base_path}/create"))
        )


@dataclass(frozen=True, slots=True)
class TransitionStep:
    base_path: str
    transition: Transition
    state_field: str
    provider_node: type

    def derive_surface[EntityT](self, ctx: SurfaceCtx[EntityT]) -> SurfaceCtx[EntityT]:
        schema = ctx.schema
        entity = schema.entity
        id_names = schema.identity_names()
        non_id_names = tuple(schema.non_identity_fields().keys())
        tr, sf = self.transition, self.state_field

        async def handler(op: HasProvider[EntityT]) -> Result[EntityT, DomainError]:
            obj = await fetch_by_identity(op.provider, entity, op, id_names)
            if obj is None:
                id_map: Mapping[str, int | str] = {name: getattr(op, name) for name in id_names}
                return Error(NotFound(entity=entity.__name__, id=id_map))
            cur = getattr(obj, sf)
            if cur not in tr.from_states:
                return Error(InvalidData(
                    entity=entity.__name__,
                    reason=f"cannot '{tr.name}': state is '{cur}', expected one of {tr.from_states}"
                ))
            updated = entity(**{
                **{name: getattr(obj, name) for name in (*id_names, *non_id_names)},
                sf: tr.to_state,
            })
            await op.provider.update(updated)
            return Ok(updated)

        req_fields = {n: info.base_type for n, info in schema.identity_fields.items()}
        req_fields["provider"] = provider_field(self.provider_node)
        return ctx.add_exposure(
            exposure(tr.name, entity)
            .request(**req_fields)
            .response(state=str)
            .handler(handler).trigger(HTTPRouteTrigger("POST", f"{self.base_path}/{id_path(id_names)}/{tr.name}"))
        )


# --- the pattern: transitions tuple -> endpoints ---

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
            *(TransitionStep(self.base_path, tr, self.state_field, self.provider_node) for tr in self.transitions),
        )


# --- usage ---

Orders = memory_node()


@derive(WorkflowPattern(
    "/orders", provider_node=Orders, state_field="status",
    transitions=(
        Transition("submit",  ("draft",), "pending"),
        Transition("approve", ("pending",), "approved"),
        Transition("reject",  ("pending",), "rejected"),
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

from emergent.wire.compile import targets  # noqa: E402

fastapi_app = targets.fastapi.compile(app)

if __name__ == "__main__":
    import uvicorn

    from derivelib import endpoint_count
    n = endpoint_count(app)
    print(f"\n  5 transitions -> {n} endpoints. validated.")
    print("  draft -> pending -> approved -> shipped")
    print("  cancel from: draft, pending | reject from: pending\n")
    uvicorn.run(fastapi_app, host="0.0.0.0", port=8000)

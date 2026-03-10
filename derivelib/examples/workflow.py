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

from collections.abc import Mapping
from dataclasses import dataclass, replace as dc_replace
from typing import Annotated

from kungfu import Ok, Error, Result

from emergent.wire.axis.query import relational
from emergent.wire.axis.schema import Identity
from emergent.wire.axis.schema._universal import SchemaCapability
from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger

from emergent.wire.derive._ctx import DeriveCtx
from emergent.wire.derive._crud import _provider_fields
from emergent.wire.derive._effects import Creates, Mutation
from emergent.wire.derive._handler import HandlerSpec, HasProvider
from emergent.wire.derive._opspec import Op, OpSpec
from emergent.wire.derive._project import (
    CustomResponse,
    dict_converter,
    entity_response,
    non_id,
    id_only,
)
from emergent.wire.derive._query_helpers import fetch_by_identity, id_path
from emergent.wire.derive._query_strategy import ProviderInjection, RelationalStrategy
from emergent.wire.derive._trigger import TriggerGen
from emergent.wire.derive._errors import InvalidData, NotFound, DomainError

from derivelib import derive, build_application_from_decorated, memory_node


# --- transition DSL ---

@dataclass(frozen=True, slots=True)
class Transition:
    name: str
    from_states: tuple[str, ...]
    to_state: str


# --- handler templates ---

@dataclass(frozen=True, slots=True)
class WorkflowInsert:
    """Handler: insert entity with forced initial state."""

    state_field: str
    initial_state: str

    def build[EntityT](self, spec: HandlerSpec[EntityT]) -> ...:
        entity = spec.entity
        id_names = spec.identity_names
        non_id_names = list(spec.non_identity_names)
        sf, init = self.state_field, self.initial_state

        async def handler(op: HasProvider[EntityT]) -> Result[EntityT, DomainError]:
            d = {n: getattr(op, n) for n in non_id_names if hasattr(op, n)}
            for name in id_names:
                if hasattr(op, name):
                    d[name] = getattr(op, name)
                elif hasattr(op.provider, "next_id"):
                    d[name] = await op.provider.next_id()
                else:
                    raise RuntimeError(f"Cannot auto-assign identity field '{name}'")
            d[sf] = init
            return Ok(await op.provider.insert(entity(**d)))

        return handler


@dataclass(frozen=True, slots=True)
class WorkflowTransition:
    """Handler: validate current state, transition to new state."""

    transition: Transition
    state_field: str

    def build[EntityT](self, spec: HandlerSpec[EntityT]) -> ...:
        entity = spec.entity
        id_names = spec.identity_names
        non_id_names = list(spec.non_identity_names)
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

        return handler


# --- WorkflowCapability: DeriveGeneratable ---

@dataclass(frozen=True, slots=True)
class WorkflowCapability(SchemaCapability):
    """State machine pattern — 1 create + N transition ops."""

    base_path: str
    provider_node: type
    state_field: str
    transitions: tuple[Transition, ...]

    def compile_derive_generate(self, ctx: DeriveCtx) -> DeriveCtx:  # type: ignore[type-arg]
        if not ctx.identity_fields:
            raise ValueError(
                f"{ctx.entity.__name__} needs Annotated[T, Identity] field for Workflow"
            )

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

        initial_state = self.transitions[0].from_states[0] if self.transitions else "draft"
        entity_name = ctx.entity.__name__

        # Create op
        create_op = Op(
            "Create",
            non_id(),
            entity_response(),
            WorkflowInsert(self.state_field, initial_state),
            effects=(Creates(),),
        )
        create_trigger = HTTPRouteTrigger("POST", f"{self.base_path}/create")
        in_fields = create_op.input_proj.project(ctx)
        annotated_fields = ctx.annotated_field_types(only=set(in_fields.keys()))

        ctx = ctx.add_spec(OpSpec(
            name=create_op.name,
            entity_name=entity_name,
            input_fields=in_fields,
            request_fields=dict(annotated_fields),
            response_spec=create_op.output,
            handler_template=create_op.handler_template,
            trigger=create_trigger,
            capabilities=create_op.capabilities,
            effects=create_op.effects,
            codec_factory=create_op.codec_factory,
            extra_op_fields=(prov_op_field, *create_op.extra_op_fields),
            extra_request_fields=(prov_req_field, *create_op.extra_request_fields),
            scope_fields=create_op.scope_fields,
            source="Workflow",
        ))

        # Transition ops
        id_names = ctx.identity_names()
        path_segment = id_path(id_names)

        for tr in self.transitions:
            tr_op = Op(
                tr.name.capitalize(),
                id_only(),
                CustomResponse(
                    field_specs=(("state", str),),
                    converter=dict_converter,
                ),
                WorkflowTransition(tr, self.state_field),
                effects=(Mutation(),),
            )
            tr_trigger = HTTPRouteTrigger("POST", f"{self.base_path}/{path_segment}/{tr.name}")
            tr_in_fields = tr_op.input_proj.project(ctx)
            tr_annotated = ctx.annotated_field_types(only=set(tr_in_fields.keys()))

            ctx = ctx.add_spec(OpSpec(
                name=tr_op.name,
                entity_name=entity_name,
                input_fields=tr_in_fields,
                request_fields=dict(tr_annotated),
                response_spec=tr_op.output,
                handler_template=tr_op.handler_template,
                trigger=tr_trigger,
                capabilities=tr_op.capabilities,
                effects=tr_op.effects,
                codec_factory=tr_op.codec_factory,
                extra_op_fields=(prov_op_field, *tr_op.extra_op_fields),
                extra_request_fields=(prov_req_field, *tr_op.extra_request_fields),
                scope_fields=tr_op.scope_fields,
                source="Workflow",
            ))

        return ctx


# --- usage ---

Orders = memory_node()


@derive(WorkflowCapability(
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

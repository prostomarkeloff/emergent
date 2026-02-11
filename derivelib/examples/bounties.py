"""Bounty board: derive the CRUD, write the domain logic.

http_crud gives list / get / create for free.
@post methods add claim and complete — the interesting part.

One entity, two patterns, five endpoints.

    uv run python -m derivelib.examples.bounties

    # post some bounties
    curl -X POST http://localhost:8000/bounties -H 'Content-Type: application/json' \
         -d '{"title":"Debug the cursed regex","reward":200}'
    curl -X POST http://localhost:8000/bounties -H 'Content-Type: application/json' \
         -d '{"title":"Slay the mass producer of microservices","reward":750}'

    # list them
    curl http://localhost:8000/bounties

    # claim one
    curl -X POST http://localhost:8000/bounties/1/claim -H 'Content-Type: application/json' \
         -d '{"bounty_id":1,"hunter":"Geralt"}'

    # complete it
    curl -X POST http://localhost:8000/bounties/1/complete -H 'Content-Type: application/json' \
         -d '{"bounty_id":1}'
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Annotated

from kungfu import Error, Ok, Result

from emergent.wire.axis.query import MutatingRelationalProvider, relational
from emergent.wire.axis.schema import Identity
from emergent.wire.axis.schema.dialects import compose

from derivelib import build_application_from_decorated, derive, fields, memory_node
from derivelib._errors import DomainError, InvalidData
from derivelib.patterns.crud import CREATE, GET, LIST, http_crud
from derivelib.patterns.methods import methods, post


# --- one node, shared by CRUD and methods ---

BountyBoard = memory_node()

# CREATE normally takes ALL non-id fields. Narrow it: only title + reward.
# status and hunter are managed by domain logic (claim/complete).
BOUNTY_CREATE = replace(CREATE, input_proj=fields("title", "reward"))


# --- one entity, two patterns ---


@derive(
    http_crud("/bounties", provider_node=BountyBoard, ops=(LIST, GET, BOUNTY_CREATE)),
    methods,
)
@dataclass
class Bounty:
    id: Annotated[int, Identity]
    title: str
    reward: int
    status: str = "open"
    hunter: str | None = None

    @post("/bounties/{bounty_id}/claim")
    async def claim(
        self,
        db: Annotated[MutatingRelationalProvider[Bounty], compose.Node(BountyBoard)],
        bounty_id: int,
        hunter: str,
    ) -> Result[Bounty, DomainError]:
        bounty = await db.fetch_one(
            relational(Bounty).filter(lambda b: b.id == bounty_id)
        )
        if bounty is None:
            return Error(InvalidData(entity="Bounty", reason=f"bounty {bounty_id} not found"))
        if bounty.status != "open":
            return Error(InvalidData(entity="Bounty", reason=f"already {bounty.status}"))
        updated = replace(bounty, status="claimed", hunter=hunter)
        await db.update(updated)
        return Ok(updated)

    @post("/bounties/{bounty_id}/complete")
    async def complete(
        self,
        db: Annotated[MutatingRelationalProvider[Bounty], compose.Node(BountyBoard)],
        bounty_id: int,
    ) -> Result[Bounty, DomainError]:
        bounty = await db.fetch_one(
            relational(Bounty).filter(lambda b: b.id == bounty_id)
        )
        if bounty is None:
            return Error(InvalidData(entity="Bounty", reason=f"bounty {bounty_id} not found"))
        if bounty.status != "claimed":
            return Error(
                InvalidData(entity="Bounty", reason=f"not claimed yet, status is {bounty.status}")
            )
        updated = replace(bounty, status="completed")
        await db.update(updated)
        return Ok(updated)


# --- build & compile ---

app = build_application_from_decorated(Bounty)

from emergent.wire.compile import targets  # noqa: E402

fastapi_app = targets.fastapi.compile(app)

if __name__ == "__main__":
    import uvicorn

    from derivelib import endpoint_count

    n = endpoint_count(app)
    print(f"\n  1 dataclass -> {n} endpoints: 3 derived + 2 hand-written.\n")
    print("  Derived:      GET /bounties, GET /bounties/{id}, POST /bounties")
    print("  Hand-written: POST /bounties/{id}/claim, POST /bounties/{id}/complete\n")
    uvicorn.run(fastapi_app, host="0.0.0.0", port=8000)

"""Explicit triggers on methods — the ``methods`` pattern.

Each method declares its own trigger via ``@post``, ``@get``, ``@command``, etc.
Capabilities (tags, auth, OpenAPI metadata) attach per-method too.

    uv run python -m derivelib.examples.service

    curl -X POST http://localhost:8000/api/orders \
         -H 'Content-Type: application/json' \
         -d '{"customer": "Charlie", "total": 199.99}'

    curl http://localhost:8000/api/orders

    curl http://localhost:8000/api/orders/1

    curl -X POST http://localhost:8000/api/orders/cancel \
         -H 'Content-Type: application/json' \
         -d '{"order_id": 1}'
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from kungfu import Error, Ok, Result

from emergent.wire.axis.query import MutatingRelationalProvider, relational
from emergent.wire.axis.query.providers.memory import MemoryRelationalProvider
from emergent.wire.axis.schema import Identity
from emergent.wire.axis.schema.dialects import compose

from derivelib import build_application_from_decorated, derive, memory_node
from derivelib import DomainError, InvalidData
from derivelib.patterns.methods import get, methods, post


# --- domain model ---


@dataclass
class Order:
    id: Annotated[int, Identity]
    customer: str
    total: float
    status: str


# --- provider node (in-memory) ---

OrderStore = memory_node()


# --- service ---


@derive(methods)
@dataclass
class OrderService:
    """Order management with explicit HTTP triggers per method."""

    @classmethod
    @post("/api/orders")
    async def create(
        cls,
        db: Annotated[MemoryRelationalProvider[Order], compose.Node(OrderStore)],
        customer: str,
        total: float,
    ) -> Result[int, DomainError]:
        nid: int = await db.next_id()
        await db.insert(
            Order(id=nid, customer=customer, total=total, status="pending")
        )
        return Ok(nid)

    @classmethod
    @get("/api/orders")
    async def list_all(
        cls,
        db: Annotated[MemoryRelationalProvider[Order], compose.Node(OrderStore)],
    ) -> Result[list[Order], DomainError]:
        orders = await db.fetch_many(relational(Order))
        return Ok(orders)

    @classmethod
    @get("/api/orders/{order_id}")
    async def find(
        cls,
        db: Annotated[MutatingRelationalProvider[Order], compose.Node(OrderStore)],
        order_id: int,
    ) -> Result[Order | None, DomainError]:
        order = await db.fetch_one(
            relational(Order).filter(lambda o: o.id == order_id)
        )
        return Ok(order)

    @classmethod
    @post("/api/orders/cancel")
    async def cancel(
        cls,
        db: Annotated[MutatingRelationalProvider[Order], compose.Node(OrderStore)],
        order_id: int,
    ) -> Result[bool, DomainError]:
        order = await db.fetch_one(
            relational(Order).filter(lambda o: o.id == order_id)
        )
        if order is None:
            return Error(InvalidData(entity="Order", reason=f"order {order_id} not found"))
        await db.update(
            Order(
                id=order.id,
                customer=order.customer,
                total=order.total,
                status="cancelled",
            )
        )
        return Ok(True)


# --- build & compile ---

app = build_application_from_decorated(OrderService)

from emergent.wire.compile import targets  # noqa: E402

fastapi_app = targets.fastapi.compile(app)

if __name__ == "__main__":
    import uvicorn

    from derivelib import endpoint_count

    n = endpoint_count(app)
    print(f"\n  4 methods -> {n} endpoints. explicit triggers.")
    print("  POST /api/orders          (create)")
    print("  GET  /api/orders          (list_all)")
    print("  GET  /api/orders/{{order_id}} (find)")
    print("  POST /api/orders/cancel   (cancel)\n")
    uvicorn.run(fastapi_app, host="0.0.0.0", port=8000)

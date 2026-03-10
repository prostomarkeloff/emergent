# Pure Methods

Not everything is an entity with a database behind it. Sometimes you just need endpoints. A service. A calculator. A webhook handler. Something where CRUD makes no sense and you want full control over every route.

The `Methods` capability works alone — no `http_crud`, no identity field, no provider (unless you need one). You write the methods, you decorate them, the derive system wires them.

---

## The order service

```python
# orders.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from kungfu import Error, Ok, Result
from nodnod import scalar_node

from emergent.wire.axis.query import MutatingRelationalProvider, SequenceNextId, relational
from emergent.wire.axis.query.providers.memory import MemoryRelationalProvider
from emergent.wire.axis.schema import Identity
from emergent.wire.axis.schema._universal import schema_meta
from emergent.wire.axis.schema.dialects import compose
from emergent.wire.axis.surface import application
from emergent.wire.derive import compile_derive, materialize
from emergent.wire.derive._effects import DomainError, InvalidData
from emergent.wire.derive.patterns.methods import Methods, get, post


@dataclass
class Order:
    id: Annotated[int, Identity]
    customer: str
    total: float
    status: str


@scalar_node
class OrderStore:
    @classmethod
    def __compose__(cls) -> MutatingRelationalProvider[Order]:
        return MemoryRelationalProvider(key_fn=lambda x: x.id, next_id=SequenceNextId())


@schema_meta(Methods())
@dataclass
class OrderService:
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
        return Ok(await db.fetch_many(relational(Order)))

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
            Order(id=order.id, customer=order.customer, total=order.total, status="cancelled")
        )
        return Ok(True)


app = application().mount(*[materialize(ctx) for ctx in compile_derive(OrderService)])

from emergent.wire.compile import targets
fastapi_app = targets.fastapi.compile(app)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(fastapi_app, host="0.0.0.0", port=8000)
```

```bash
curl -X POST http://localhost:8000/api/orders \
     -H 'Content-Type: application/json' \
     -d '{"customer": "Charlie", "total": 199.99}'
# 1

curl http://localhost:8000/api/orders
# [{"id": 1, "customer": "Charlie", "total": 199.99, "status": "pending"}]

curl -X POST http://localhost:8000/api/orders/cancel \
     -H 'Content-Type: application/json' \
     -d '{"order_id": 1}'
# true
```

Four methods. Four endpoints. Every trigger explicit. Every handler yours.

---

## What `Methods` does

When `compile_derive` sees `Methods()` in the schema metadata, it runs `compile_derive_generate`. This scans `OrderService` for classmethods decorated with `@post`, `@get`, `@command`, etc. For each one:

1. The decorator (`@post("/api/orders")`) becomes the HTTP trigger
2. The method signature becomes the request type — `customer: str, total: float` are the request fields (minus `cls` and injected dependencies like `db`)
3. The return type `Result[int, DomainError]` determines the response shape
4. The method body is the handler

That's it. No schema introspection, no automatic operations. `Methods` is just a scanner that turns decorated methods into wire exposures. It's the thinnest layer above raw wire.

## When to use what

After three chapters, you've seen three levels:

| Level | Pattern | You write | Framework writes |
|-------|---------|-----------|-----------------|
| 1 | `http_crud` only | Fields | Everything |
| 2 | `http_crud` + `Methods` | Fields + domain methods | CRUD + wiring |
| 2 | `Methods` only | All methods | Wiring only |

There's no "best" level. A `User` entity might be pure Level 1. A `Payment` service might be pure `Methods`. A `Bounty` might mix both. Use whatever fits. They compose in the same application.

---

So far, we've been deriving endpoints from entity shapes or explicit methods. But there's a whole dimension we haven't touched: what if you want to *modify* what gets derived, without writing it by hand?

**Next:** [Transforms →](04-transforms.md)

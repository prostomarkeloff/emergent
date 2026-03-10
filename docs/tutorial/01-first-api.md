# Your First API

We're building a product catalog. The whole thing. It will take about 25 lines.

```python
# catalog.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from nodnod import scalar_node

from emergent.wire.axis.query import MutatingRelationalProvider, SequenceNextId
from emergent.wire.axis.query.providers.memory import MemoryRelationalProvider
from emergent.wire.axis.schema import Identity
from emergent.wire.axis.schema._universal import schema_meta
from emergent.wire.axis.surface import application
from emergent.wire.derive import compile_derive, materialize, http_crud


@scalar_node
class Products:
    @classmethod
    def __compose__(cls) -> MutatingRelationalProvider:
        return MemoryRelationalProvider(key_fn=lambda x: x.id, next_id=SequenceNextId())


@schema_meta(http_crud("/products", Products))
@dataclass
class Product:
    id: Annotated[int, Identity]
    name: str
    price: float


app = application().mount(*[materialize(ctx) for ctx in compile_derive(Product)])

from emergent.wire.compile import targets
fastapi_app = targets.fastapi.compile(app)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(fastapi_app, host="0.0.0.0", port=8000)
```

Run it:

```bash
uv run python catalog.py
```

Now hit it:

```bash
# Create
curl -X POST http://localhost:8000/products \
     -H 'Content-Type: application/json' \
     -d '{"name": "Keyboard", "price": 79.99}'
# {"id": 1, "name": "Keyboard", "price": 79.99}

# List
curl http://localhost:8000/products
# {"items": [{"id": 1, "name": "Keyboard", "price": 79.99}]}

# Get
curl http://localhost:8000/products/1
# {"id": 1, "name": "Keyboard", "price": 79.99}

# Update
curl -X PUT http://localhost:8000/products/1 \
     -H 'Content-Type: application/json' \
     -d '{"id": 1, "name": "Mechanical Keyboard", "price": 129.99}'
# {"id": 1, "name": "Mechanical Keyboard", "price": 129.99}

# Delete
curl -X DELETE http://localhost:8000/products/1
# {"success": true}

# Not found
curl http://localhost:8000/products/999
# {"type": "about:blank", "title": "Not Found", "status": 404,
#  "detail": "Product with id 999 not found"}
```

Six endpoints. Validation. RFC 7807 errors. OpenAPI at `/docs`. Let's understand what just happened.

---

## Pulling apart the magic

**`Annotated[int, Identity]`** — this marker says "this field is the primary key." It's how the derivation knows which fields go into a GET request (identity only), which into a CREATE request (everything *except* identity), and how to look up entities. If you forget it, you get a clear error at derivation time, not a mystery at runtime.

**`@scalar_node` + `MemoryRelationalProvider`** — a nodnod node wrapping an in-memory relational provider. Think of it as a list pretending to be a database. For prototyping it's instant; in production you'd swap in SQLAlchemy.

**`http_crud("/products", Products)`** — a *capability*. It's a `SchemaCapability` implementing `DeriveGeneratable`. It bundles 6 operation descriptors (List, Get, Create, Update, Patch, Delete) with HTTP triggers (`GET /products`, `POST /products`, etc.). It knows nothing about your specific entity yet — it's a recipe, not a meal.

**`@schema_meta(...)`** — attaches the capability to your class as schema metadata. Nothing generates yet. It's stored, waiting.

**`compile_derive(Product)`** — *now* it runs. Three-phase compilation:

1. **Phase 1 (Generate):** CRUD reads the entity schema — discovers `id`, `name`, `price`, finds the identity field (`id`), binds the provider, generates one `OpSpec` per CRUD operation
2. **Phase 2 (Modify):** any `DeriveModifiable` capabilities transform the specs (none here)
3. **Phase 3 (Augment):** any `DeriveAugmentable` capabilities run post-modification (none here)

Returns `list[DeriveCtx]` — one context per generator group.

**`materialize(ctx)`** — converts `DeriveCtx` into a wire `Endpoint` with concrete request types, response types, handlers, and exposures.

**`application().mount(...)` + `targets.fastapi.compile(app)`** — the Application is target-independent. FastAPI is one projection. CLI is another. Telegram is another.

That last point matters. The Application isn't a FastAPI app. It's an intermediate representation. FastAPI is one projection. CLI is another. Telegram is another. But we'll get to that.

---

For now, stare at those 25 lines. Think about how many lines the FastAPI equivalent would be. Think about how many of those lines were *plumbing*. We just deleted all of them.

**Next:** [Domain Logic →](02-domain-logic.md)

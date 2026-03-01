# Your First API

We're building a product catalog. The whole thing. It will take about 20 lines.

```python
# catalog.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from emergent.wire.axis.schema import Identity
from derivelib import derive, build_application_from_decorated, memory_node
from derivelib.patterns.crud import http_crud

Products = memory_node()

@derive(http_crud("/products", provider_node=Products))
@dataclass
class Product:
    id: Annotated[int, Identity]
    name: str
    price: float

app = build_application_from_decorated(Product)

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

**`Annotated[int, Identity]`** — this marker says "this field is the primary key." It's how derivelib knows which fields go into a GET request (identity only), which into a CREATE request (everything *except* identity), and how to look up entities. If you forget it, you get a clear error at derivation time, not a mystery at runtime.

**`memory_node()`** — a nodnod node wrapping an in-memory relational provider. Think of it as a list pretending to be a database. For prototyping it's instant; in production you'd swap in SQLAlchemy.

**`http_crud("/products", provider_node=Products)`** — a *pattern*. It bundles 6 operation descriptors (List, Get, Create, Update, Patch, Delete) with HTTP triggers (`GET /products`, `POST /products`, etc.). It knows nothing about your specific entity yet — it's a recipe, not a meal.

**`@derive(...)`** — attaches the pattern to your class. Nothing generates yet. It's stored, waiting.

**`build_application_from_decorated(Product)`** — *now* it runs. For each decorated class:

1. Inspect fields (schema axis) — discover `id`, `name`, `price`
2. Find the identity field — `id`
3. Bind the provider (query axis) — `Products`
4. Generate one spec per CRUD operation (surface axis)
5. Materialize concrete request types, response types, handlers
6. Assemble into a wire `Application`

**`targets.fastapi.compile(app)`** — the Application is target-independent. This projects it to FastAPI: route functions, Pydantic models, framework registration.

That last point matters. The Application isn't a FastAPI app. It's an intermediate representation. FastAPI is one projection. CLI is another. Telegram is another. But we'll get to that.

---

For now, stare at those 20 lines. Think about how many lines the FastAPI equivalent would be. Think about how many of those lines were *plumbing*. We just deleted all of them.

**Next:** [Domain Logic →](02-domain-logic.md)

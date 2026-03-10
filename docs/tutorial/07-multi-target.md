# One Codebase, Three Targets

This is the chapter where emergent stops looking like "a nicer way to write FastAPI" and starts looking like something fundamentally different.

Everything so far compiled to HTTP. But the wire `Application` — the thing `compile_derive` + `materialize` produces — isn't an HTTP app. It's an intermediate representation. HTTP is one projection. CLI is another. Telegram is another.

Watch.

---

## The shop

```python
# shop.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from nodnod import scalar_node

from emergent.wire.axis.query import MutatingRelationalProvider, SequenceNextId
from emergent.wire.axis.query.providers.memory import MemoryRelationalProvider
from emergent.wire.axis.schema import Identity
from emergent.wire.axis.schema._universal import schema_meta
from emergent.wire.axis.surface import application
from emergent.wire.derive import compile_derive, materialize, http_crud, cli_crud


@scalar_node
class Store:
    @classmethod
    def __compose__(cls) -> MutatingRelationalProvider:
        return MemoryRelationalProvider(key_fn=lambda x: x.id, next_id=SequenceNextId())


@schema_meta(
    http_crud("/products", Store),
    cli_crud("product", Store),
)
@dataclass
class Product:
    id: Annotated[int, Identity]
    name: str
    price: float
    in_stock: bool = True


app = application().mount(*[materialize(ctx) for ctx in compile_derive(Product)])

from emergent.wire.compile import targets
from emergent.wire.compile.targets.cli import TYPED_CLI

if __name__ == "__main__":
    import sys

    mode = sys.argv[1] if len(sys.argv) > 1 else "http"

    if mode == "http":
        fastapi_app = targets.fastapi.compile(app)
        import uvicorn
        uvicorn.run(fastapi_app, host="0.0.0.0", port=8000)

    elif mode == "cli":
        parser = targets.cli.cli_compile(app, prog="shop", compiler=TYPED_CLI)
        sys.exit(targets.cli.cli_run(parser, sys.argv[2:]))
```

```bash
# HTTP mode
uv run python shop.py http
curl -X POST http://localhost:8000/products \
     -H 'Content-Type: application/json' \
     -d '{"name": "Laptop", "price": 999.99}'
# {"id": 1, "name": "Laptop", "price": 999.99, "in_stock": true}

# CLI mode
uv run python shop.py cli product-create Laptop 999.99
# Product(id=1, name='Laptop', price=999.99, in_stock=True)

uv run python shop.py cli product-list
# [Product(id=1, name='Laptop', price=999.99, in_stock=True)]
```

Same entity. Same provider. Same data. Two completely different interfaces. One `@schema_meta`, two capabilities.

---

## What happened

```python
@schema_meta(
    http_crud("/products", Store),   # HTTP triggers
    cli_crud("product", Store),      # CLI triggers
)
```

Two `DeriveGeneratable` capabilities stacked. Each produces operation descriptors with *different trigger generators*:
- `http_crud` uses `HTTPTriggers("/products")` — maps ops to HTTP routes
- `cli_crud` uses `CLITriggers("product")` — maps ops to CLI commands (`product-create`, `product-list`, `product-get`, ...)

Since there are multiple generators, `compile_derive` creates separate `DeriveCtx` for each — one with HTTP endpoints, one with CLI endpoints. `materialize` converts each into a wire `Endpoint`. The application ends up with endpoints that have different trigger types.

When you call `targets.fastapi.compile(app)`, the FastAPI compiler scans for `HTTPRouteTrigger` exposures and ignores everything else. When you call `targets.cli.cli_compile(app)`, the CLI compiler scans for `CLITrigger` exposures and ignores everything else.

Neither compiler knows the other exists. They each project the same IR into their own world.

## The sheaf

This is what the architecture docs call "the sheaf." Your application is a global section — a single coherent description. Each compilation target is a fiber — a projection that extracts the view it understands. HTTP sees HTTP triggers. CLI sees CLI triggers. Telegram sees Telegram triggers.

```
     Application (global section)
           │
    ┌──────┼──────┐
    ▼      ▼      ▼
   HTTP   CLI    TG     ← fibers
```

You don't write adapters. You don't maintain three codebases. You write one description with multiple capabilities, and each compiler reads its own. The sync between targets is guaranteed by construction — they derive from the same fields, the same types, the same domain.

Want to add Telegram? Stack a third capability. The dataclass doesn't change. The domain logic doesn't change. You just add another projection.

---

**Next:** [How It Works →](08-how-it-works.md)

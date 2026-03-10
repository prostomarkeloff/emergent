# Custom Handler Templates

You know how `FetchMany` handles List, `InsertNew` handles Create, `DeleteOne` handles Delete? Those are *handler templates* — frozen dataclasses that implement a `build(spec) -> handler` protocol. The derivation calls `build()` at materialization time, passing structural information about the entity, and gets back an async handler function.

You can write your own.

---

## The problem

You have an inventory system. Products have a `stock` field. You want a "restock" endpoint that *increments* stock by a given quantity — not replaces it, not sets it. The built-in `UpdateExisting` template overwrites the entire entity. You need something different.

## The template

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from kungfu import Error, Ok, Result

from emergent.wire.axis.schema import Identity
from emergent.wire.axis.schema._universal import schema_meta
from emergent.wire.axis.surface import application
from emergent.wire.derive import compile_derive, materialize, http_crud
from emergent.wire.derive._handler import HandlerSpec
from emergent.wire.derive._ctx import OperationHandler
from emergent.wire.derive._effects import DomainError, Mutation
from emergent.wire.derive._opspec import Op
from emergent.wire.derive._project import id_only, entity_response
from emergent.wire.derive._query_helpers import fetch_by_identity, NotFound


@dataclass(frozen=True, slots=True)
class IncrementField:
    """Handler template: fetch entity by ID, increment a field, save."""

    field: str
    increment_param: str = "quantity"

    def build[E](self, spec: HandlerSpec[E]) -> OperationHandler[E, DomainError]:
        entity_cls = spec.entity
        id_names = spec.identity_names
        field, param = self.field, self.increment_param

        async def handler(op: object) -> Result[E, DomainError]:
            # Fetch
            obj = await fetch_by_identity(op.provider, entity_cls, op, id_names)
            if obj is None:
                id_map = {n: getattr(op, n) for n in id_names}
                return Error(NotFound(entity=entity_cls.__name__, id=id_map))

            # Increment
            current = getattr(obj, field)
            delta = getattr(op, param)

            # Rebuild (generic — works for any entity)
            import dataclasses as _dc
            data = {f.name: getattr(obj, f.name) for f in _dc.fields(entity_cls)}
            data[field] = current + delta
            updated = entity_cls(**data)

            # Save
            await op.provider.update(updated)
            return Ok(updated)

        return handler
```

That's it. `IncrementField` is a frozen dataclass (defunctionalized — it's data, not a function). Its `build` method receives a `HandlerSpec` with the entity type, identity field names, and base query. It returns an async handler.

## Using it

Two ways to use a custom template:

**Option A — define a new Op and include it in CRUD:**

```python
from dataclasses import replace
from emergent.wire.derive._crud import UPDATE

RESTOCK = Op(
    "Restock",
    id_only(),
    entity_response(),
    IncrementField(field="stock"),
    extra_request_fields=(("quantity", int),),
    effects=(Mutation(),),
)

@schema_meta(http_crud("/items", Items, ops=(*ALL_CRUD_OPS, RESTOCK)))
@dataclass
class Item:
    id: Annotated[int, Identity]
    name: str
    stock: int = 0
```

Then the CRUD endpoints plus your custom Restock endpoint are all generated together.

## The HandlerSpec

Your template's `build` method receives a `HandlerSpec[E]` with:

| Field | Type | What it gives you |
|-------|------|-------------------|
| `entity` | `type[E]` | The entity class itself |
| `entity_name` | `str` | `"Item"` |
| `identity_names` | `tuple[str, ...]` | `("id",)` |
| `non_identity_names` | `tuple[str, ...]` | `("name", "stock")` |
| `base_query` | `RelationalQuerySet[E] \| None` | Pre-configured query for this entity |

And the handler itself receives an `op` — the request object. It always has a `.provider` field (the database access) plus whatever fields the input projection and extra fields specify.

The pattern: fetch -> validate -> transform -> save -> return. The template abstracts the *shape* of the operation; the entity-specific details (which field to increment, by how much) are parameters on the frozen dataclass.

---

**Next:** [Custom Dialects →](10-custom-dialect.md)

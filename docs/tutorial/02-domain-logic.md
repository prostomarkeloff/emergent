# Domain Logic

CRUD is nice. But you don't build products — you build *systems*. Systems have rules. A bug can be assigned. A bug can be closed. A closed bug can't be assigned again. CRUD doesn't know about any of that.

So here's the question: can we keep the free CRUD for the boring parts and write only the interesting logic by hand?

Yes. That's what Level 2 looks like.

---

## The bug tracker

```python
# bugs.py
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Annotated

from kungfu import Error, Ok, Result
from nodnod import scalar_node

from emergent.wire.axis.query import MutatingRelationalProvider, SequenceNextId, relational
from emergent.wire.axis.query.providers.memory import MemoryRelationalProvider
from emergent.wire.axis.schema import Identity
from emergent.wire.axis.schema._universal import schema_meta
from emergent.wire.axis.schema.dialects import compose
from emergent.wire.axis.surface import application
from emergent.wire.derive import compile_derive, materialize, http_crud
from emergent.wire.derive._crud import CREATE, GET, LIST
from emergent.wire.derive._effects import DomainError, InvalidData
from emergent.wire.derive._project import SelectFields
from emergent.wire.derive.patterns.methods import Methods, post


@scalar_node
class Bugs:
    @classmethod
    def __compose__(cls) -> MutatingRelationalProvider:
        return MemoryRelationalProvider(key_fn=lambda x: x.id, next_id=SequenceNextId())


# CREATE normally takes ALL non-id fields. We narrow it:
# only title + severity. status and assignee are domain-managed.
BUG_CREATE = replace(CREATE, input_proj=SelectFields("title", "severity"))


@schema_meta(
    http_crud("/bugs", Bugs, ops=(LIST, GET, BUG_CREATE)),
    Methods(),
)
@dataclass
class Bug:
    id: Annotated[int, Identity]
    title: str
    severity: str
    status: str = "open"
    assignee: str | None = None

    @classmethod
    @post("/bugs/{bug_id}/assign")
    async def assign(
        cls,
        db: Annotated[MutatingRelationalProvider[Bug], compose.Node(Bugs)],
        bug_id: int,
        assignee: str,
    ) -> Result[Bug, DomainError]:
        bug = await db.fetch_one(
            relational(Bug).filter(lambda b: b.id == bug_id)
        )
        if bug is None:
            return Error(InvalidData(entity="Bug", reason=f"bug {bug_id} not found"))
        if bug.status == "closed":
            return Error(InvalidData(entity="Bug", reason="can't assign a closed bug"))
        updated = replace(bug, assignee=assignee, status="assigned")
        await db.update(updated)
        return Ok(updated)

    @classmethod
    @post("/bugs/{bug_id}/close")
    async def close(
        cls,
        db: Annotated[MutatingRelationalProvider[Bug], compose.Node(Bugs)],
        bug_id: int,
    ) -> Result[Bug, DomainError]:
        bug = await db.fetch_one(
            relational(Bug).filter(lambda b: b.id == bug_id)
        )
        if bug is None:
            return Error(InvalidData(entity="Bug", reason=f"bug {bug_id} not found"))
        if bug.status == "closed":
            return Error(InvalidData(entity="Bug", reason="already closed"))
        updated = replace(bug, status="closed")
        await db.update(updated)
        return Ok(updated)


app = application().mount(*[materialize(ctx) for ctx in compile_derive(Bug)])

from emergent.wire.compile import targets
fastapi_app = targets.fastapi.compile(app)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(fastapi_app, host="0.0.0.0", port=8000)
```

Five endpoints. Three derived (list, get, create), two hand-written (assign, close).

```bash
# Create a bug (only title + severity)
curl -X POST http://localhost:8000/bugs \
     -H 'Content-Type: application/json' \
     -d '{"title": "Login broken on Safari", "severity": "high"}'
# {"id": 1, "title": "Login broken on Safari", "severity": "high",
#  "status": "open", "assignee": null}

# Assign it
curl -X POST http://localhost:8000/bugs/1/assign \
     -H 'Content-Type: application/json' \
     -d '{"bug_id": 1, "assignee": "Alice"}'
# {"id": 1, ..., "status": "assigned", "assignee": "Alice"}

# Try to assign a closed bug
curl -X POST http://localhost:8000/bugs/1/close \
     -H 'Content-Type: application/json' -d '{"bug_id": 1}'
curl -X POST http://localhost:8000/bugs/1/assign \
     -H 'Content-Type: application/json' \
     -d '{"bug_id": 1, "assignee": "Bob"}'
# {"type": "about:blank", "title": "Invalid Data", "status": 422,
#  "detail": "can't assign a closed bug"}
```

The domain rules work. Let's unpack the new concepts.

---

## Two capabilities, one entity

```python
@schema_meta(
    http_crud("/bugs", Bugs, ops=(LIST, GET, BUG_CREATE)),
    Methods(),
)
```

Two capabilities stacked in `@schema_meta`. `http_crud` is a `DeriveGeneratable` that derives the mechanical CRUD endpoints. `Methods()` is another `DeriveGeneratable` that scans the class for `@post` / `@get` decorated methods and wires each one as an endpoint. They don't interfere — they each generate into separate contexts when there are multiple generators, producing independent endpoints.

## Narrowing CREATE

```python
BUG_CREATE = replace(CREATE, input_proj=SelectFields("title", "severity"))
```

`CREATE` normally accepts all non-identity fields. But `status` and `assignee` are domain-managed — users shouldn't set them directly. `replace()` (from dataclasses) swaps the input projection. The derived CREATE endpoint now only accepts `title` and `severity`. `status` defaults to `"open"`, `assignee` to `None`.

## Result, not exceptions

```python
async def assign(...) -> Result[Bug, DomainError]:
    ...
    return Ok(updated)   # success
    return Error(InvalidData(...))  # failure
```

emergent uses `kungfu`'s `Result[T, E]`. No exceptions for domain logic. `Ok(value)` on success, `Error(reason)` on failure. The framework converts these: `Ok` becomes a 200 response with the entity, `Error(InvalidData(...))` becomes a 422 with an RFC 7807 body.

This isn't a style choice — it's a design constraint. When errors are values in the type signature, the type checker catches missing error handling at compile time. You can't forget to handle a failure mode because pyright won't let you.

## The database

```python
db: Annotated[MutatingRelationalProvider[Bug], compose.Node(Bugs)]
```

`MutatingRelationalProvider[Bug]` is the typed interface to the data store. `compose.Node(Bugs)` tells nodnod's dependency injection to resolve it from the `Bugs` node. Inside the method: `db.fetch_one(query)`, `db.update(entity)`, `db.insert(entity)`.

```python
relational(Bug).filter(lambda b: b.id == bug_id)
```

The query axis. `relational(Bug)` starts a typed query. `.filter()` adds a predicate. The query is a data structure — it doesn't execute until the provider runs it.

---

This is the pattern for most production APIs. Derive the boring parts, write the interesting parts. The framework handles list/get/create; you handle assign/close/transfer/approve — the stuff that makes your domain *yours*.

**Next:** [Pure Methods →](03-pure-methods.md)

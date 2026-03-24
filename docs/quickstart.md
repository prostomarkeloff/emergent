# Quickstart

3 dataclasses → 18 REST endpoints. 5 minutes.

## Install

```bash
pip install emergent[fastapi]
# or
uv add emergent[fastapi]
```

## Define entities

```python
# app.py
from dataclasses import dataclass
from typing import Annotated

from emergent.wire.axis.schema import Identity, Unique, MaxLen, Min, Max
from emergent.wire.derive import derive, memory_node, build_application_from_decorated, http_crud
from emergent.wire.compile import targets

# In-memory providers (one line each)
Users = memory_node()
Posts = memory_node()
Comments = memory_node()


@derive(http_crud("/users", provider_node=Users))
@dataclass
class User:
    id: Annotated[int, Identity]
    name: str
    email: Annotated[str, Unique]


@derive(http_crud("/posts", provider_node=Posts))
@dataclass
class Post:
    id: Annotated[int, Identity]
    title: Annotated[str, MaxLen(200)]
    body: str
    author_id: int


@derive(http_crud("/comments", provider_node=Comments))
@dataclass
class Comment:
    id: Annotated[int, Identity]
    post_id: int
    text: str


# Compile
app = build_application_from_decorated(User, Post, Comment)
fastapi_app = targets.fastapi.compile(app)
```

## Run

```bash
uvicorn app:fastapi_app --reload
```

## Use

```bash
# Create a user
curl -X POST http://localhost:8000/users \
  -H 'Content-Type: application/json' \
  -d '{"name": "Alice", "email": "alice@example.com"}'

# List users
curl http://localhost:8000/users

# Get by id
curl http://localhost:8000/users/1

# Update
curl -X PUT http://localhost:8000/users/1 \
  -H 'Content-Type: application/json' \
  -d '{"name": "Alicia", "email": "alice@example.com"}'

# Delete
curl -X DELETE http://localhost:8000/users/1
```

Each entity gets 6 endpoints: list, get, create, update, patch, delete. 3 entities × 6 = 18 endpoints. Pydantic validation, OpenAPI spec, RFC 9457 error responses — all generated from the dataclass definition.

## What just happened

```
@dataclass         →  entity definition
Annotated[..., X]  →  capabilities (Identity, Unique, MaxLen)
@derive(http_crud) →  attach CRUD pattern
memory_node()      →  in-memory storage
build_application  →  wire Application (target-agnostic)
targets.fastapi    →  compile to FastAPI
```

The `fold` compiler read every `Annotated` capability and produced Pydantic models, OpenAPI schema, and FastAPI routes. You wrote fields. emergent wrote everything else.

## Next

- Add constraints: `Min(0)`, `Max(200)`, `OneOf("admin", "user")` — validation across all targets
- Add transforms: `Paginated(20)`, `Readonly()`, `SoftDelete()` — modify generated endpoints
- Add auth: `Authenticated()`, `RequireRole("admin")` — per-endpoint authorization
- Add targets: `targets.cli.compile(app)` — same entities, CLI interface
- [Full tutorial →](tutorial/00-intro.md)

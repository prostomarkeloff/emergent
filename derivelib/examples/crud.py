"""3 dataclasses. 15 endpoints. Zero controllers.

    uv run python -m derivelib.examples.crud

    curl http://localhost:8000/users
    curl -X POST http://localhost:8000/users -H 'Content-Type: application/json' \
         -d '{"name": "Alice", "email": "alice@example.com"}'
    curl http://localhost:8000/users/1
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from emergent.wire.axis.schema import Identity, Unique

from derivelib import derive, build_application_from_decorated, memory_node
from derivelib.patterns.crud import http_crud


# --- providers (one line each) ---

Users = memory_node()
Posts = memory_node()
Comments = memory_node()


# --- the entire API definition ---


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
    title: str
    body: str
    author_id: int


@derive(http_crud("/comments", provider_node=Comments))
@dataclass
class Comment:
    id: Annotated[int, Identity]
    post_id: int
    text: str


# --- that's it. 15 REST endpoints. full CRUD. RFC 7807 errors. ---

app = build_application_from_decorated(User, Post, Comment)

from emergent.wire.compile import targets

fastapi_app = targets.fastapi.compile(app)

if __name__ == "__main__":
    import uvicorn

    from derivelib import endpoint_count
    n = endpoint_count(app)
    print(f"\n  3 dataclasses -> {n} endpoints. zero controllers.\n")
    print("  curl http://localhost:8000/users")
    print('  curl -X POST http://localhost:8000/users -H "Content-Type: application/json" \\')
    print('       -d \'{"name": "Alice", "email": "alice@example.com"}\'\n')
    uvicorn.run(fastapi_app, host="0.0.0.0", port=8000)

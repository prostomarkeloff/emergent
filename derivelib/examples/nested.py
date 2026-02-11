"""Nested resources: /users/{user_id}/posts.

Parent CRUD + child CRUD scoped by parent FK.
FK auto-discovered from Ref(User) on Post.user_id.

    uv run python -m derivelib.examples.nested

    # Create user
    curl -X POST http://localhost:8000/users -H 'Content-Type: application/json' \
         -d '{"name": "Alice", "email": "alice@example.com"}'

    # Create post under user
    curl -X POST http://localhost:8000/users/1/posts -H 'Content-Type: application/json' \
         -d '{"title": "Hello World", "body": "First post"}'

    # List posts for user
    curl http://localhost:8000/users/1/posts

    # Get specific post
    curl http://localhost:8000/users/1/posts/1
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from emergent.wire.axis.schema import Identity
from emergent.wire.axis.schema._universal import Ref

from derivelib import derive, build_application_from_decorated, memory_node
from derivelib.patterns.crud import http_crud
from derivelib.patterns.nested import nested_http_crud


# --- providers ---

Users = memory_node()
Posts = memory_node()


# --- entities ---

@derive(http_crud("/users", provider_node=Users))
@dataclass
class User:
    id: Annotated[int, Identity]
    name: str
    email: str


@derive(nested_http_crud("/users", parent=User, provider_node=Posts))
@dataclass
class Post:
    id: Annotated[int, Identity]
    user_id: Annotated[int, Ref(User)]
    title: str
    body: str


# --- application ---

app = build_application_from_decorated(User, Post)

from emergent.wire.compile import targets  # noqa: E402

fastapi_app = targets.fastapi.compile(app)

if __name__ == "__main__":
    import uvicorn

    from derivelib import endpoint_count
    n = endpoint_count(app)
    print(f"\n  {n} endpoints: users CRUD + nested posts CRUD")
    print("  POST /users → create user")
    print("  POST /users/{{user_id}}/posts → create post")
    print("  GET  /users/{{user_id}}/posts → list user's posts")
    print("  GET  /users/{{user_id}}/posts/{{id}} → get post\n")
    uvicorn.run(fastapi_app, host="0.0.0.0", port=8000)

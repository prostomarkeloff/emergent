# Nested Resources

An author has posts. Posts live under `/authors/{author_id}/posts`. When you list posts for author 1, you only see author 1's posts. When you create a post, the `author_id` comes from the URL.

This is a parent-child relationship. Doing it by hand means manually scoping every query, manually extracting path params, manually validating that the parent exists. Doing it with derivelib means one annotation.

---

## The blog

```python
# blog.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from emergent.wire.axis.schema import Identity
from emergent.wire.axis.schema._universal import Ref

from derivelib import derive, build_application_from_decorated, memory_node
from derivelib.patterns.crud import http_crud
from derivelib.patterns.nested import nested_http_crud

Authors = memory_node()
Posts = memory_node()


@derive(http_crud("/authors", provider_node=Authors))
@dataclass
class Author:
    id: Annotated[int, Identity]
    name: str
    bio: str


@derive(nested_http_crud("/authors", parent=Author, provider_node=Posts))
@dataclass
class Post:
    id: Annotated[int, Identity]
    author_id: Annotated[int, Ref(Author)]
    title: str
    body: str


app = build_application_from_decorated(Author, Post)

from emergent.wire.compile import targets
fastapi_app = targets.fastapi.compile(app)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(fastapi_app, host="0.0.0.0", port=8000)
```

```bash
# Create an author
curl -X POST http://localhost:8000/authors \
     -H 'Content-Type: application/json' \
     -d '{"name": "Alice", "bio": "Writes about Python"}'

# Create a post under that author
curl -X POST http://localhost:8000/authors/1/posts \
     -H 'Content-Type: application/json' \
     -d '{"title": "Hello World", "body": "First post"}'

# List posts for author 1 only
curl http://localhost:8000/authors/1/posts
# {"items": [{"id": 1, "author_id": 1, "title": "Hello World", ...}]}

# Get specific post
curl http://localhost:8000/authors/1/posts/1
```

---

## How it works

**`Ref(Author)`** on `author_id` — marks this field as a foreign key to `Author`. This is a schema-axis capability. It tells derivelib: "this field references a parent entity."

**`nested_http_crud("/authors", parent=Author, provider_node=Posts)`** — generates CRUD endpoints nested under the parent path. Routes become `/authors/{author_id}/posts`, `/authors/{author_id}/posts/{id}`, etc. Queries are auto-scoped: listing posts for author 1 filters by `author_id == 1`. Creating a post under author 1 auto-fills `author_id = 1` from the URL.

The parent entity (`Author`) gets its own flat CRUD. The child entity (`Post`) gets nested CRUD scoped by the parent FK. You can combine this with transforms — `nested_http_crud(...).chain(paginated(10))` gives you paginated nested lists.

Short chapter. The point isn't complexity — it's that relationships that usually require careful manual scoping are handled by one annotation and one pattern.

---

**Next:** [One Codebase, Three Targets →](07-multi-target.md)

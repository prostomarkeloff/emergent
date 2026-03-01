# Transforms

You've built a CRUD API. It works. Then someone asks: "Can I paginate the list?" And: "Can I sort it?" And: "Can I filter by author?" And: "Can I search?"

You could write all of that by hand. Or you could tell the derivation to *reshape itself*.

---

## The article API

```python
# articles.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from emergent.wire.axis.schema import Identity

from derivelib import (
    derive, build_application_from_decorated, memory_node,
    paginated, sorted_list, filtered, searchable,
)
from derivelib.patterns.crud import http_crud

Articles = memory_node()

@derive(
    http_crud("/articles", provider_node=Articles)
        .chain(paginated(20))
        .chain(sorted_list())
        .chain(filtered("author", "published"))
        .chain(searchable("title", "body"))
)
@dataclass
class Article:
    id: Annotated[int, Identity]
    title: str
    body: str
    author: str
    published: bool = False

app = build_application_from_decorated(Article)

from emergent.wire.compile import targets
fastapi_app = targets.fastapi.compile(app)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(fastapi_app, host="0.0.0.0", port=8000)
```

Same `http_crud`. Same 6 endpoints. But now the List endpoint speaks a different language:

```bash
# Paginated
curl 'http://localhost:8000/articles?page=1&page_size=5'
# {"items": [...], "total": 12, "page": 1, "page_size": 5}

# Sorted
curl 'http://localhost:8000/articles?page=1&page_size=5&sort=title&order=desc'

# Filtered by author
curl 'http://localhost:8000/articles?filter_author=alice'

# Full-text search
curl 'http://localhost:8000/articles?q=python'
```

Four transforms. Four new capabilities. Zero new handlers written.

---

## How `.chain()` works

`.chain(transform)` takes a `DerivationT` — a function that rewrites the derivation tuple — and applies it *after* the pattern compiles but *before* anything materializes into code.

Think of it like this: `http_crud` produces a description of 6 operations. Each transform reads that description, finds operations it cares about, and modifies them. The modified description then gets compiled into actual endpoints.

**`paginated(20)`** — finds the List operation (it has the `Pageable` effect). Replaces its handler template with `PaginatedFetchMany(page_size=20)`. Adds `page` and `page_size` to the request. Changes the response shape from `{"items": [...]}` to `{"items": [...], "total": N, "page": M, "page_size": K}`.

**`sorted_list()`** — finds operations with the `Sortable` effect. Adds `sort` and `order` query parameters.

**`filtered("author", "published")`** — adds `filter_author` and `filter_published` query parameters. Exact match.

**`searchable("title", "body")`** — adds a `q` parameter. Case-insensitive substring search across the named fields.

Each transform targets operations by their *effects* — semantic tags that describe what an operation does. `LIST` has `Pageable` and `Sortable` effects by default. Transforms match on those effects and leave everything else alone. This is why `paginated()` modifies List but not Get or Create — they don't have the `Pageable` effect.

## Stacking and composing

Transforms chain. Each one sees the result of the previous:

```python
http_crud("/articles", provider_node=Articles)
    .chain(paginated(20))        # modify List handler
    .chain(sorted_list())        # add sort params to (already-paginated) List
    .chain(readonly())           # remove Create, Update, Patch, Delete entirely
    .chain(without_delete())     # or just remove Delete
```

Some useful ones at a glance:

| Transform | What it does |
|-----------|-------------|
| `readonly()` | Drop all mutation endpoints |
| `without_delete()` | Drop DELETE only |
| `without_ops(PATCH, UPDATE)` | Drop specific ops |
| `only_ops(LIST, GET)` | Keep only these |
| `add_capability(cap, Mutation)` | Attach a capability to mutations |
| `swap_handler("List", MyHandler())` | Replace a handler template |
| `project_response(exclude=("secret",))` | Strip fields from responses |

The key insight: transforms operate on *descriptions*, not code. They rewrite the derivation data before materialization. That's why they're powerful — you're not monkey-patching handlers, you're reshaping what gets generated in the first place.

---

**Next:** [Authentication →](05-auth.md)

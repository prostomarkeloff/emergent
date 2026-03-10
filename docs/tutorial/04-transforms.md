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

from nodnod import scalar_node

from emergent.wire.axis.query import MutatingRelationalProvider, SequenceNextId
from emergent.wire.axis.query.providers.memory import MemoryRelationalProvider
from emergent.wire.axis.schema import Identity
from emergent.wire.axis.schema._universal import schema_meta
from emergent.wire.axis.surface import application
from emergent.wire.derive import (
    compile_derive, materialize, http_crud,
    Paginated, Sorted, Filtered, Searchable,
)


@scalar_node
class Articles:
    @classmethod
    def __compose__(cls) -> MutatingRelationalProvider:
        return MemoryRelationalProvider(key_fn=lambda x: x.id, next_id=SequenceNextId())


@schema_meta(
    http_crud("/articles", Articles),
    Paginated(20),
    Sorted(),
    Filtered("author", "published"),
    Searchable("title", "body"),
)
@dataclass
class Article:
    id: Annotated[int, Identity]
    title: str
    body: str
    author: str
    published: bool = False


app = application().mount(*[materialize(ctx) for ctx in compile_derive(Article)])

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

## How transforms work

Transforms are `DeriveModifiable` capabilities — they run in Phase 2 of the three-phase compilation, after generators (Phase 1) have produced OpSpecs but before anything materializes into code.

Think of it like this: `http_crud` produces a description of 6 operations. Each transform reads that description, finds operations it cares about, and modifies them. The modified description then gets compiled into actual endpoints.

**`Paginated(20)`** — finds the List operation (it has the `Pageable` effect). Replaces its handler template with `PaginatedFetchMany(page_size=20)`. Adds `page` and `page_size` to the request. Changes the response shape from `{"items": [...]}` to `{"items": [...], "total": N, "page": M, "page_size": K}`.

**`Sorted()`** — finds operations with the `Sortable` effect. Adds `sort` and `order` query parameters.

**`Filtered("author", "published")`** — adds `filter_author` and `filter_published` query parameters. Exact match.

**`Searchable("title", "body")`** — adds a `q` parameter. Case-insensitive substring search across the named fields.

Each transform targets operations by their *effects* — semantic tags that describe what an operation does. `LIST` has `Pageable` and `Sortable` effects by default. Transforms match on those effects and leave everything else alone. This is why `Paginated()` modifies List but not Get or Create — they don't have the `Pageable` effect.

## Stacking and composing

Transforms stack in `@schema_meta`. Each one sees the result of the previous:

```python
@schema_meta(
    http_crud("/articles", Articles),
    Paginated(20),       # modify List handler
    Sorted(),            # add sort params to (already-paginated) List
    Readonly(),          # remove Create, Update, Patch, Delete entirely
    WithoutDelete(),     # or just remove Delete
)
```

Some useful ones at a glance:

| Transform | What it does |
|-----------|-------------|
| `Readonly()` | Drop all mutation endpoints |
| `WithoutDelete()` | Drop DELETE only |
| `OnlyOps("List", "Get")` | Keep only these |
| `ProjectResponse(exclude=("secret",))` | Strip fields from responses |
| `SoftDelete(field="deleted_at")` | Mark as deleted instead of deleting |
| `Timestamped(created="created_at", updated="updated_at")` | Auto-set timestamps |

The key insight: transforms operate on *descriptions*, not code. They rewrite the derivation data before materialization. That's why they're powerful — you're not monkey-patching handlers, you're reshaping what gets generated in the first place.

---

**Next:** [Authentication →](05-auth.md)

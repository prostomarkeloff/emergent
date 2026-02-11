"""Pagination, sorting, filtering, search — all via .chain() transforms.

    uv run python -m derivelib.examples.query_transforms

    # paginated list
    curl 'http://localhost:8000/books?page=1&page_size=5'

    # sorted
    curl 'http://localhost:8000/books?page=1&page_size=5&sort=title&order=asc'

    # filtered by genre
    curl 'http://localhost:8000/books?filter_genre=fiction'

    # full-text search
    curl 'http://localhost:8000/books?q=python'

LIST op already declares Pageable + Sortable effects (see patterns/crud.py).
Transforms read config from effects automatically.
filtered() and searchable() add params + in-memory post-filter.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from emergent.wire.axis.schema import Identity

from derivelib import (
    derive, build_application_from_decorated, endpoint_count, memory_node,
    paginated, sorted_list, filtered, searchable,
)
from derivelib.patterns.crud import http_crud


Books = memory_node()


@derive(
    http_crud("/books", provider_node=Books)
        .chain(paginated())
        .chain(sorted_list())
        .chain(filtered("genre", "author"))
        .chain(searchable("title", "author"))
)
@dataclass
class Book:
    id: Annotated[int, Identity]
    title: str
    author: str
    genre: str
    year: int


app = build_application_from_decorated(Book)

from emergent.wire.compile import targets  # noqa: E402

fastapi_app = targets.fastapi.compile(app)

if __name__ == "__main__":
    import uvicorn

    n = endpoint_count(app)
    print(f"\n  1 entity -> {n} endpoints. paginated + sorted + filtered + searchable.\n")
    print("  curl 'http://localhost:8000/books?page=1&page_size=5'")
    print("  curl 'http://localhost:8000/books?sort=title&order=desc'")
    print("  curl 'http://localhost:8000/books?filter_genre=fiction'")
    print("  curl 'http://localhost:8000/books?q=python'\n")
    uvicorn.run(fastapi_app, host="0.0.0.0", port=8000)

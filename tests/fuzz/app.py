# pyright: reportPrivateUsage=false
"""Emergent test apps compiled from dataclasses — used by schemathesis fuzzing.

Uses emergent.wire.derive directly:
  memory_node() + @derive(http_crud(...)) + build_application_from_decorated + fastapi.compile

Multiple apps with different entity/capability combos to fuzz different code paths.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any

from emergent.wire.derive import derive, build_application_from_decorated, memory_node, http_crud, Paginated, Readonly

from emergent.wire.axis.schema._universal import (
    Identity,
    Min,
    Max,
    MinLen,
    MaxLen,
    OneOf,
    Unique,
    Doc,
    schema_meta,
)
from emergent.wire.compile import targets
from emergent.wire.compile.targets.fastapi import install_rfc7807_validation_handler


def _compile_with_rfc7807(wire_app: Any) -> Any:
    """Compile to FastAPI and install RFC 7807 validation error handler."""
    fa = targets.fastapi.compile(wire_app)
    install_rfc7807_validation_handler(fa)
    return fa


# ═══════════════════════════════════════════════════════════════════════════════
# App 1: Full CRUD (same as derivelib/examples/crud.py)
# ═══════════════════════════════════════════════════════════════════════════════

Users = memory_node()
Posts = memory_node()


@derive(http_crud("/users", provider_node=Users))
@dataclass
class User:
    id: Annotated[int, Identity]
    name: Annotated[str, MinLen(1), MaxLen(100)]
    email: Annotated[str, Unique, MaxLen(255)]
    age: Annotated[int, Min(0), Max(200)]
    role: Annotated[str, OneOf("admin", "user", "mod")]


@derive(http_crud("/posts", provider_node=Posts))
@dataclass
class Post:
    id: Annotated[int, Identity]
    title: Annotated[str, MinLen(1), MaxLen(200)]
    body: str
    author_id: int


crud_app = build_application_from_decorated(User, Post)
app = _compile_with_rfc7807(crud_app)


# ═══════════════════════════════════════════════════════════════════════════════
# App 2: Readonly (no mutations — only GET endpoints)
# ═══════════════════════════════════════════════════════════════════════════════

ReadonlyItems = memory_node()


@derive(http_crud("/items", provider_node=ReadonlyItems), Readonly())
@dataclass
class Item:
    id: Annotated[int, Identity]
    title: Annotated[str, MinLen(1), MaxLen(200)]
    price: Annotated[float, Min(0.0), Max(1_000_000.0)]


readonly_app_wire = build_application_from_decorated(Item)
readonly_app = _compile_with_rfc7807(readonly_app_wire)


# ═══════════════════════════════════════════════════════════════════════════════
# App 3: Minimal entity (fewest fields, least constraints)
# ═══════════════════════════════════════════════════════════════════════════════

Things = memory_node()


@derive(http_crud("/things", provider_node=Things))
@dataclass
class Thing:
    id: Annotated[int, Identity]
    label: str


minimal_app_wire = build_application_from_decorated(Thing)
minimal_app = _compile_with_rfc7807(minimal_app_wire)

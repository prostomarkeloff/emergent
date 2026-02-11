"""authlib demo — User + Post with orthogonal auth.

Identity = str (login name) — simplest possible.
Demonstrates:
  - auth_login on User (public)
  - require_auth on Post (mutations only)
  - BearerExtract for HTTP
  - Custom identity type = str (no hardcoded AuthUser)

    cd derivelib && PYTHONPATH=src:.. uv run python -m examples.authlib

    # 1. create user (public)
    curl -X POST http://localhost:8000/users -H 'Content-Type: application/json' \
         -d '{"name": "alice"}'

    # 2. login (public, returns token)
    curl -X POST http://localhost:8000/login -H 'Content-Type: application/json' \
         -d '{"name": "alice"}'

    # 3. create post without auth -> 401
    curl -X POST http://localhost:8000/posts -H 'Content-Type: application/json' \
         -d '{"author": "alice", "title": "hi"}'

    # 4. create post with auth -> 200 (use token from step 2)
    curl -X POST http://localhost:8000/posts -H 'Content-Type: application/json' \
         -H 'Authorization: Bearer <token-from-login>' \
         -d '{"author": "alice", "title": "hi"}'

    # 5. list posts (public) -> 200
    curl http://localhost:8000/posts

    # 6. login unknown user -> {"token": null, "error": "not found"}
    curl -X POST http://localhost:8000/login -H 'Content-Type: application/json' \
         -d '{"name": "nobody"}'
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from nodnod import scalar_node

from emergent.wire.axis.query import MutatingRelationalProvider, SequenceNextId, kv
from emergent.wire.axis.query.providers.memory import MemoryRelationalProvider, MemoryKVProvider
from emergent.wire.axis.schema import Identity

from derivelib import derive, build_application_from_decorated
from derivelib.patterns.crud import http_crud, LIST, GET, CREATE

from . import (
    BearerExtract,
    TokenValidate,
    require_auth,
    auth_login,
    register_auth_errors,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Providers
# ═══════════════════════════════════════════════════════════════════════════════


_users: MemoryRelationalProvider[User] = MemoryRelationalProvider(
    key_fn=lambda x: x.id, next_id=SequenceNextId(),
)
_posts: MemoryRelationalProvider[Post] = MemoryRelationalProvider(
    key_fn=lambda x: x.id, next_id=SequenceNextId(),
)


@scalar_node
class UserStore:
    @classmethod
    def __compose__(cls) -> MutatingRelationalProvider[User]:
        return _users


@scalar_node
class PostStore:
    @classmethod
    def __compose__(cls) -> MutatingRelationalProvider[Post]:
        return _posts


# ═══════════════════════════════════════════════════════════════════════════════
# Session Storage — identity = str (login name). NOT hardcoded AuthUser.
# ═══════════════════════════════════════════════════════════════════════════════


IdentityType = str

_sessions: MemoryKVProvider[str, IdentityType] = MemoryKVProvider()
_session_qs = kv(IdentityType, key=lambda name: name)


async def _lookup_token(token_value: str) -> IdentityType | None:
    """Look up identity by token. Returns None if invalid."""
    return await _sessions.get(_session_qs.get(token_value))


# ═══════════════════════════════════════════════════════════════════════════════
# Auth Transform — composable, effect-driven
# ═══════════════════════════════════════════════════════════════════════════════


auth = require_auth(
    TokenValidate(identity_type=IdentityType, lookup=_lookup_token),
    BearerExtract(),
)


# ═══════════════════════════════════════════════════════════════════════════════
# Entities
# ═══════════════════════════════════════════════════════════════════════════════


def _identity_fn(u: User) -> str:
    return u.name


@derive(
    http_crud("/users", provider_node=UserStore, ops=(LIST, GET, CREATE)),
    auth_login(
        "/login",
        provider_node=UserStore,
        sessions=_sessions,
        session_qs=_session_qs,
        match_field="name",
        identity_fn=_identity_fn,
    ),
)
@dataclass
class User:
    id: Annotated[int, Identity]
    name: str


@derive(http_crud("/posts", provider_node=PostStore, ops=(LIST, GET, CREATE)).chain(auth))
@dataclass
class Post:
    id: Annotated[int, Identity]
    author: str
    title: str


# ═══════════════════════════════════════════════════════════════════════════════
# Build
# ═══════════════════════════════════════════════════════════════════════════════


app = build_application_from_decorated(User, Post)

from emergent.wire.compile import targets  # noqa: E402

fastapi_app = targets.fastapi.compile(app)
register_auth_errors(fastapi_app)

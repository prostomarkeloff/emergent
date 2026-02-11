"""User projection: authorized sees active_at, public does not.

One @dataclass, three endpoint groups, field-level response projection + auth.

    cd derivelib && PYTHONPATH=src:.. uv run python -m examples.projection


Endpoint map
────────────

    METHOD  PATH              AUTH     RESPONSE FIELDS
    GET     /users            -        {items: [{id, name, email}]}
    GET     /users/{id}       -        {id, name, email}
    POST    /users            -        {id, name, email, active_at}
    GET     /users/me/{id}    Bearer   {id, name, email, active_at}
    POST    /login            -        {token, error}

Public Read ops have active_at stripped via project_response().
Authorized Read ops return full entity. Mutations always return full entity.


OpenAPI response schemas
────────────────────────

    ListUserResponse:    ['items']           items = list[UserView]
    UserView:            ['id', 'name', 'email']
    GetUserResponse (1): ['id', 'name', 'email']          <- public
    GetUserResponse (2): ['id', 'name', 'email', 'active_at']  <- authorized
    CreateUserResponse:  ['id', 'name', 'email', 'active_at']
    LoginUserResponse:   ['token', 'error']

    securitySchemes:
      bearerAuth: {type: http, scheme: bearer}

    GET    /users/me/{id}  has security=[{bearerAuth: []}]


Compilation trace (Axes.traced() -> explain())
──────────────────────────────────────────────

    === ListUserRequest ===
      provider (MutatingRelationalProvider):
        [Node]
        PydanticContext: Node (skipped)
    === GetUserRequest ===
      id (int):
        [Identity]
        PydanticContext: Identity (skipped)
      provider (MutatingRelationalProvider):
        [Node]
        PydanticContext: Node (skipped)
    === CreateUserRequest ===
      name (str):
      email (str):
        [Unique]
        PydanticContext: Unique (skipped)
      active_at (str):
      provider (MutatingRelationalProvider):
        [Node]
        PydanticContext: Node (skipped)
    === LoginUserRequest ===
      name (str):
      provider (MutatingRelationalProvider):
        [Node]
        PydanticContext: Node (skipped)

    === Scan ===
      GET  /users          -> RRC  [2 caps]
      GET  /users/{id}     -> RRC  [2 caps]
      POST /users          -> RRC  [2 caps]
      GET  /users/me/{id}  -> RRC  [5 caps: BearerExtract, TokenValidate, AuthOpenAPI, ...]
      POST /login          -> RRC

    === Wrap ===
      RRC -> FastAPIRoute  (GET  /users)
      RRC -> FastAPIRoute  (GET  /users/{id})
      RRC -> FastAPIRoute  (POST /users)
      RRC -> FastAPIRoute  (GET  /users/me/{id})
      RRC -> FastAPIRoute  (POST /login)


curl test results
─────────────────

    # 1. create user (public)
    $ curl -s -X POST http://localhost:8000/users -H 'Content-Type: application/json' \\
           -d '{"name":"alice","email":"alice@example.com","active_at":"2024-01-01"}'
    {"id":1,"name":"alice","email":"alice@example.com","active_at":"2024-01-01"}

    # 2. login -> get token
    $ curl -s -X POST http://localhost:8000/login -H 'Content-Type: application/json' \\
           -d '{"name":"alice"}'
    {"token":"8zliN-MtGz71sck8fcpg1Q05xzucN8KvzoPKk28t-mc","error":null}

    # 3. public list — no active_at in items
    $ curl -s http://localhost:8000/users
    {"items":[{"id":1,"name":"alice","email":"alice@example.com"}]}

    # 4. public get — no active_at
    $ curl -s http://localhost:8000/users/1
    {"id":1,"name":"alice","email":"alice@example.com"}

    # 5. authorized get — WITH active_at
    $ curl -s http://localhost:8000/users/me/1 -H 'Authorization: Bearer <TOKEN>'
    {"id":1,"name":"alice","email":"alice@example.com","active_at":"2024-01-01"}

    # 6. no token — 401
    $ curl -s http://localhost:8000/users/me/1
    {"type":"about:blank","title":"Unauthorized","status":401,"detail":"authentication required"}

    # 7. invalid token — 401
    $ curl -s http://localhost:8000/users/me/1 -H 'Authorization: Bearer garbage'
    {"type":"about:blank","title":"Unauthorized","status":401,"detail":"invalid credentials"}

    # 8. not found — 404
    $ curl -s http://localhost:8000/users/999
    {"type":"about:blank","title":"Not Found","status":404,"detail":"User with id 999 not found","instance":""}

    # 9. login unknown user
    $ curl -s -X POST http://localhost:8000/login -H 'Content-Type: application/json' \\
           -d '{"name":"nobody"}'
    {"token":null,"error":"not found"}
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from nodnod import scalar_node

from emergent.wire.axis.query import MutatingRelationalProvider, SequenceNextId, kv
from emergent.wire.axis.query.providers.memory import MemoryRelationalProvider, MemoryKVProvider
from emergent.wire.axis.schema import Identity, Unique

from derivelib import Read, derive, build_application_from_decorated
from derivelib.patterns.crud import http_crud, GET, LIST, CREATE
from derivelib.transforms import project_response

from derivelib.authlib import (
    BearerExtract,
    TokenValidate,
    require_auth,
    auth_login,
    register_auth_errors,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Providers + session storage
# ═══════════════════════════════════════════════════════════════════════════════


_users: MemoryRelationalProvider[User] = MemoryRelationalProvider(
    key_fn=lambda x: x.id, next_id=SequenceNextId(),
)

IdentityType = str
_sessions: MemoryKVProvider[str, IdentityType] = MemoryKVProvider()
_session_qs = kv(IdentityType, key=lambda name: name)


async def _lookup_token(token_value: str) -> IdentityType | None:
    return await _sessions.get(_session_qs.get(token_value))


@scalar_node
class UserStore:
    @classmethod
    def __compose__(cls) -> MutatingRelationalProvider[User]:
        return _users


# ═══════════════════════════════════════════════════════════════════════════════
# Auth transform — gates Read ops with Bearer token
# ═══════════════════════════════════════════════════════════════════════════════

auth = require_auth(
    TokenValidate(identity_type=IdentityType, lookup=_lookup_token),
    BearerExtract(),
    effect=Read,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Entity — one User, three endpoint groups
# ═══════════════════════════════════════════════════════════════════════════════


def _identity_fn(u: User) -> str:
    return u.name


@derive(
    # Public: LIST + GET + CREATE, response without active_at
    http_crud("/users", provider_node=UserStore, ops=(LIST, GET, CREATE)).chain(
        project_response(exclude=("active_at",))
    ),
    # Authorized: GET with all fields (requires Bearer token)
    http_crud("/users/me", provider_node=UserStore, ops=(GET,)).chain(auth),
    # Login: public, issues token
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
    email: Annotated[str, Unique]
    active_at: str | None = None


# ═══════════════════════════════════════════════════════════════════════════════
# Compile
# ═══════════════════════════════════════════════════════════════════════════════

app = build_application_from_decorated(User)

from emergent.wire.compile import Axes, explain, targets  # noqa: E402

axes = Axes.traced()
fastapi_app = targets.fastapi.compile(app, axes=axes)
register_auth_errors(fastapi_app)

if __name__ == "__main__":
    import uvicorn

    print(explain(axes))
    uvicorn.run(fastapi_app, host="0.0.0.0", port=8000)

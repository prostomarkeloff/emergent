# Authentication

Your API is open. Anyone can read, write, delete. That was fine for prototyping. It's not fine for production.

Let's lock the door. Not by hand-writing middleware — by composing auth as a capability on the derivation.

---

## The notes API

We want three endpoint groups on one entity:
- **Public**: list + get + create, but with `active_at` hidden from responses
- **Authorized**: get with full fields, requires a Bearer token
- **Login**: issues tokens

```python
# notes.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from nodnod import scalar_node

from emergent.wire.axis.query import MutatingRelationalProvider, SequenceNextId, kv
from emergent.wire.axis.query.providers.memory import MemoryRelationalProvider, MemoryKVProvider
from emergent.wire.axis.schema import Identity, Unique
from emergent.wire.axis.schema._universal import schema_meta
from emergent.wire.axis.surface import application
from emergent.wire.derive import compile_derive, materialize, http_crud, ProjectResponse
from emergent.wire.derive._crud import GET, LIST, CREATE
from emergent.wire.derive._effects import Read
from emergent.wire.derive.auth import (
    Authenticated,
    BearerExtract,
    LoginOp,
    TokenValidate,
    register_auth_errors,
)


# --- storage ---

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


# --- entity: three endpoint groups from one class ---

def _identity_fn(u: User) -> str:
    return u.name


@schema_meta(
    # Public: list + get + create, hide active_at
    http_crud("/users", UserStore, ops=(LIST, GET, CREATE)),
    ProjectResponse(exclude=("active_at",)),
    # Authorized: get with all fields, requires Bearer token
    http_crud("/users/me", UserStore, ops=(GET,)),
    Authenticated(
        BearerExtract(),
        TokenValidate(identity_type=IdentityType, lookup=_lookup_token),
        effect=Read,
    ),
    # Login
    LoginOp(
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


app = application().mount(*[materialize(ctx) for ctx in compile_derive(User)])

from emergent.wire.compile import Axes, targets
fastapi_app = targets.fastapi.compile(app)
register_auth_errors(fastapi_app)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(fastapi_app, host="0.0.0.0", port=8000)
```

```bash
# 1. Create a user
curl -s -X POST http://localhost:8000/users \
     -H 'Content-Type: application/json' \
     -d '{"name":"alice","email":"alice@example.com","active_at":"2024-01-01"}'
# {"id":1,"name":"alice","email":"alice@example.com"}

# 2. Login
curl -s -X POST http://localhost:8000/login \
     -H 'Content-Type: application/json' \
     -d '{"name":"alice"}'
# {"token":"8zliN-MtGz...","error":null}

# 3. Public list — active_at stripped
curl -s http://localhost:8000/users
# {"items":[{"id":1,"name":"alice","email":"alice@example.com"}]}

# 4. Authorized get — full entity
curl -s http://localhost:8000/users/me/1 \
     -H 'Authorization: Bearer 8zliN-MtGz...'
# {"id":1,"name":"alice","email":"alice@example.com","active_at":"2024-01-01"}

# 5. No token — 401
curl -s http://localhost:8000/users/me/1
# {"type":"about:blank","title":"Unauthorized","status":401,
#  "detail":"authentication required"}
```

---

## How auth flows

Three pieces snap together:

**`LoginOp("/login", ...)`** — a `DeriveGeneratable` capability that creates a POST endpoint. It finds the user by `match_field`, generates a random token, stores it in the session KV provider, returns it. It's a derivation capability just like `http_crud` — it produces a wire endpoint from a description.

**`Authenticated(BearerExtract(), TokenValidate(...), effect=Read)`** — a `DeriveModifiable` that wraps endpoints matching the `Read` effect with two *enrichers*:

1. **`BearerExtract()`** — reads `Authorization: Bearer <token>` from the request header, injects the raw token into the scope
2. **`TokenValidate(lookup=...)`** — calls your lookup function, validates the token, injects the user identity into the scope

Enrichers are runtime middleware. They execute *before* your handler. If the token is missing or invalid, the enricher short-circuits with a 401 — the handler never runs.

**`ProjectResponse(exclude=("active_at",))`** — strips `active_at` from response types on Read operations. Public users see `{id, name, email}`. Authorized users see everything.

## Positional capabilities

Notice the ordering in `@schema_meta(...)`. This matters.

Capabilities in `schema_meta` are **positional** — a modifier binds to the generator **immediately before it**. Capabilities before the first generator are global (apply to all).

```python
@schema_meta(
    http_crud("/users", ...),                  # generator 0
    ProjectResponse(exclude=("active_at",)),   # local to generator 0
    http_crud("/users/me", ..., ops=(GET,)),   # generator 1
    Authenticated(...),                        # local to generator 1
    LoginOp("/login", ...),                    # generator 2
)
```

`ProjectResponse` only strips `active_at` from `/users` endpoints. `/users/me` keeps all fields. `Authenticated` only gates `/users/me`. The public `/users` endpoints stay open. No special filtering parameter needed — just position.

This works for any derivation, not just HTTP. CLI, task queues, custom algebras — same rule.

The beautiful part: these are all just capabilities. `Authenticated` is a `DeriveModifiable`. `LoginOp` is a `DeriveGeneratable`. `ProjectResponse` is a `DeriveModifiable`. They compose in `@schema_meta(...)` like any other capability. Auth isn't a special subsystem bolted onto the framework — it's built from the same algebra as pagination and CRUD.

---

**Next:** [Nested Resources →](06-nested.md)

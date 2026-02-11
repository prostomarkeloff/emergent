"""Login dialect — generic token issuance.

IssueToken = handler template for login operations
auth_login() = dialect builder (1 op, issues token, public)

Parametric on: match field, token factory, identity factory.
The library never assumes what identity looks like.

    from derivelib.authlib.login import auth_login

    @derive(
        http_crud("/users", provider_node=UserStore, ops=(LIST, GET, CREATE)),
        auth_login("/login", provider_node=UserStore, sessions=sessions, session_qs=qs),
    )
    @dataclass
    class User: ...
"""

from __future__ import annotations

import secrets
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from kungfu import Error, Ok, Result

from emergent.wire.axis.query._kv import KVQuerySet
from emergent.wire.axis.query.providers.memory import MemoryKVProvider

from derivelib._dialect import Dialect, Op, HTTPTriggers, dialect
from derivelib._effects import Creates
from derivelib._project import fields, custom_response
from derivelib._protocols import HandlerSpec, HasProvider

if TYPE_CHECKING:
    from derivelib._ctx import OperationHandler
    from derivelib._errors import DomainError


# ═══════════════════════════════════════════════════════════════════════════════
# Response Converter
# ═══════════════════════════════════════════════════════════════════════════════


def token_converter[T, E](cls: type, result: Result[T, E]) -> Result[T, E]:
    """Standard converter for login response: {token, error}.

    Wraps both success and error in the response type — transport-agnostic.
    WHY Callable[..., Result]: response classes are generated at derive time via
    make_dataclass; the concrete type is not expressible statically.
    """
    match result:
        case Ok(val):
            return cls(token=val, error=None)
        case Error(err):
            return cls(token=None, error=str(err))
        case _:
            raise TypeError(f"Expected Result, got {type(result)}")


# ═══════════════════════════════════════════════════════════════════════════════
# IssueToken — handler template
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class IssueToken[V]:
    """Generic login handler template.

    Generic over V (identity value type stored in sessions).

    1. Fetch all entities from provider
    2. Find one matching match_field
    3. Create token via token_fn(entity)
    4. Create identity via identity_fn(entity)
    5. Store token -> identity in session KV
    6. Return Ok(token) or Error("not found")

    User controls: what field to match on, how to create tokens,
    what identity to store. The library doesn't assume.
    """

    sessions: MemoryKVProvider[str, V]
    session_qs: KVQuerySet[str, V]
    match_field: str = "name"
    token_fn: Callable[..., str] | None = None
    identity_fn: Callable[..., V] | None = None

    def build[EntityT](self, spec: HandlerSpec[EntityT]) -> OperationHandler[Any, DomainError]:
        from derivelib._errors import NotFound

        sessions = self.sessions
        qs = self.session_qs
        base_query = spec.base_query
        match_field = self.match_field
        entity_name = spec.entity_name

        def _default_token(e: EntityT) -> str:
            _ = e
            return secrets.token_urlsafe(32)

        token_fn: Callable[..., str] = self.token_fn if self.token_fn is not None else _default_token
        identity_fn = self.identity_fn

        async def handler(op: HasProvider[EntityT]) -> Result[str, DomainError]:
            match_value = getattr(op, match_field)
            assert base_query is not None
            query = base_query.filter(
                lambda e, _f=match_field, _v=match_value: getattr(e, _f) == _v
            )
            entity = await op.provider.fetch_one(query)
            if entity is None:
                return Error(NotFound(entity=entity_name, id={match_field: match_value}))
            token: str = token_fn(entity)
            if identity_fn is not None:
                await sessions.set(qs.set(token, identity_fn(entity)))
            else:
                # V = EntityT when identity_fn omitted (caller invariant).
                # Any: V and EntityT are independent type params — not expressible.
                identity_val: Any = entity
                await sessions.set(qs.set(token, identity_val))
            return Ok(token)

        return handler


# ═══════════════════════════════════════════════════════════════════════════════
# auth_login — dialect builder
# ═══════════════════════════════════════════════════════════════════════════════


from emergent.wire.axis.surface.triggers.http import Method

LOGIN_ROUTES: dict[str, tuple[Method, bool]] = {"Login": ("POST", False)}


def auth_login[V](
    path: str,
    provider_node: type,
    *,
    sessions: MemoryKVProvider[str, V],
    session_qs: KVQuerySet[str, V],
    match_field: str = "name",
    token_fn: Callable[..., str] | None = None,
    identity_fn: Callable[..., V] | None = None,
) -> Dialect:
    """Login dialect - 1 op, issues token. No auth required (public).

        auth_login(
            "/login",
            provider_node=UserStore,
            sessions=sessions,
            session_qs=qs,
            match_field="name",
            identity_fn=lambda u: u.name,  # identity = str
        )
    """
    return dialect(
        Op(
            "Login",
            fields(match_field),
            custom_response(
                (("token", str | None), ("error", str | None)),
                token_converter,
            ),
            IssueToken(sessions, session_qs, match_field, token_fn, identity_fn),
            effects=(Creates(),),
        ),
        triggers=HTTPTriggers(path, routes=LOGIN_ROUTES),
        provider_node=provider_node,
    )


__all__ = (
    # Response converter
    "token_converter",
    # Handler template
    "IssueToken",
    # Dialect builder
    "auth_login",
    # Route config
    "LOGIN_ROUTES",
)

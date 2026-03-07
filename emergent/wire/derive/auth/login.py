"""Login capability — generic token issuance as SchemaCapability.

    @schema_meta(
        http_crud("/users", Users, ops=(LIST, GET, CREATE)),
        LoginOp("/login", provider_node=Users, sessions=sessions, session_qs=qs),
    )
    @dataclass
    class User: ...
"""

from __future__ import annotations

import secrets
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from kungfu import Error, Ok, Result

from emergent.wire.axis.query._kv import KVQuerySet
from emergent.wire.axis.query.providers.memory import MemoryKVProvider
from emergent.wire.axis.schema._universal import SchemaCapability

from emergent.wire.derive._effects import Creates
from emergent.wire.derive._handler import HandlerSpec, HasProvider
from emergent.wire.derive._opspec import Op
from emergent.wire.derive._project import CustomResponse, SelectFields
from emergent.wire.derive._trigger import HTTPTriggers

if TYPE_CHECKING:
    from emergent.wire.axis.query import RelationalQuerySet
    from emergent.wire.derive._ctx import DeriveCtx, OperationHandler
    from emergent.wire.derive._errors import DomainError


# ═══════════════════════════════════════════════════════════════════════════════
# Response Converter
# ═══════════════════════════════════════════════════════════════════════════════


def token_converter[T, E](cls: type, result: Result[T, E]) -> object:
    """Standard converter for login response: {token, error}."""
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

    1. Fetch all entities from provider
    2. Find one matching match_field
    3. Create token via token_fn(entity)
    4. Create identity via identity_fn(entity)
    5. Store token -> identity in session KV
    6. Return Ok(token) or Error("not found")
    """

    sessions: MemoryKVProvider[str, V]
    session_qs: KVQuerySet[str, V]
    match_field: str = "name"
    token_fn: Callable[..., str] | None = None
    identity_fn: Callable[..., V] | None = None

    def build[EntityT](self, spec: HandlerSpec[EntityT]) -> OperationHandler[str, DomainError]:
        from emergent.wire.derive._errors import NotFound

        sessions = self.sessions
        qs = self.session_qs
        base_query = spec.base_query
        match_field = self.match_field
        entity_name = spec.entity_name

        def _default_token(e: EntityT) -> str:
            _ = e
            return secrets.token_urlsafe(32)

        token_fn: Callable[..., str] = (
            self.token_fn if self.token_fn is not None else _default_token
        )
        identity_fn = self.identity_fn

        async def handler(op: HasProvider[EntityT]) -> Result[str, DomainError]:
            match_value = getattr(op, match_field)
            assert base_query is not None
            query = base_query.filter(
                lambda e, _f=match_field, _v=match_value: getattr(e, _f) == _v
            )
            entity = await op.provider.fetch_one(query)
            if entity is None:
                return Error(
                    NotFound(entity=entity_name, id={match_field: match_value})
                )
            token: str = token_fn(entity)
            if identity_fn is not None:
                await sessions.set(qs.set(token, identity_fn(entity)))
            else:
                await sessions.set(qs.set(token, entity))  # type: ignore[arg-type]
            return Ok(token)

        return handler


# ═══════════════════════════════════════════════════════════════════════════════
# LoginOp — SchemaCapability (DeriveGeneratable)
# ═══════════════════════════════════════════════════════════════════════════════


from emergent.wire.axis.surface.triggers.http import Method

LOGIN_ROUTES: dict[str, tuple[Method, bool]] = {"Login": ("POST", False)}


@dataclass(frozen=True, slots=True)
class LoginOp[V](SchemaCapability):
    """Login dialect — 1 op, issues token.

        LoginOp("/login", provider_node=Users, sessions=sessions, session_qs=qs)
    """

    path: str
    provider_node: type
    sessions: MemoryKVProvider[str, V]
    session_qs: KVQuerySet[str, V]
    match_field: str = "name"
    token_fn: Callable[..., str] | None = None
    identity_fn: Callable[..., V] | None = None

    def compile_derive_generate(self, ctx: DeriveCtx) -> DeriveCtx:
        from emergent.wire.axis.query import relational
        from emergent.wire.derive._crud import _provider_fields

        login_op = Op(
            "Login",
            SelectFields(names=(self.match_field,)),
            CustomResponse(
                fields=(("token", str | None), ("error", str | None)),
                converter=token_converter,
            ),
            IssueToken(
                self.sessions,
                self.session_qs,
                self.match_field,
                self.token_fn,
                self.identity_fn,
            ),
            effects=(Creates(),),
        )

        from dataclasses import replace as dc_replace

        from emergent.wire.derive._query_strategy import ProviderInjection, RelationalStrategy

        prov_op_field, prov_req_field = _provider_fields(self.provider_node)
        ctx = dc_replace(
            ctx,
            query_strategy=RelationalStrategy(
                provider_node=self.provider_node,
                base_query=relational(ctx.entity),
                injection=ProviderInjection(
                    op_field=prov_op_field,
                    request_field=prov_req_field,
                ),
            ),
        )

        triggers = HTTPTriggers(self.path, routes=LOGIN_ROUTES)

        from emergent.wire.derive._opspec import OpSpec

        trigger = triggers(ctx.entity, login_op)
        in_fields = login_op.input_proj.project(ctx)
        annotated_fields = ctx.annotated_field_types(only=set(in_fields.keys()))

        spec = OpSpec(
            name=login_op.name,
            entity_name=ctx.entity.__name__,
            input_fields=in_fields,
            request_fields=dict(annotated_fields),
            response_spec=login_op.output,
            handler_template=login_op.handler_template,
            trigger=trigger,
            capabilities=login_op.capabilities,
            effects=login_op.effects,
            codec_factory=login_op.codec_factory,
            extra_op_fields=(prov_op_field, *login_op.extra_op_fields),
            extra_request_fields=(prov_req_field, *login_op.extra_request_fields),
            scope_fields=login_op.scope_fields,
            source="LoginOp",
        )
        return ctx.add_spec(spec)


__all__ = (
    "token_converter",
    "IssueToken",
    "LoginOp",
    "LOGIN_ROUTES",
)

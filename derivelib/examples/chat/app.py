"""AI chat — 3 entities, auth, custom dialects.

User creates chats, sends messages. The AI replies automatically.
Demonstrates: custom dialects, handler templates, orthogonal auth, suggestions.

    uv run python -m derivelib.examples.chat

    # create user (public — no auth)
    curl -X POST http://localhost:8000/users -H 'Content-Type: application/json' \
         -d '{"name": "Alice"}'

    # login (public — returns token)
    curl -X POST http://localhost:8000/login -H 'Content-Type: application/json' \
         -d '{"name": "Alice"}'

    # create chat (auth required)
    curl -X POST http://localhost:8000/chats \
         -H 'Content-Type: application/json' \
         -H 'Authorization: Bearer tok_1' \
         -d '{"user_id": 1, "title": "My first chat"}'

    # send message (auth required, AI replies with suggestions)
    curl -X POST http://localhost:8000/messages \
         -H 'Content-Type: application/json' \
         -H 'Authorization: Bearer tok_1' \
         -d '{"chat_id": 1, "text": "Hello!"}'

    # list messages (public — reads don't need auth)
    curl 'http://localhost:8000/messages?chat_id=1'
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Annotated, Any, TYPE_CHECKING

from kungfu import Ok, Error, Result
from nodnod import Scope, scalar_node

from emergent.wire.axis.query import MutatingRelationalProvider, SequenceNextId, kv
from emergent.wire.axis.query._kv import KVQuerySet
from emergent.wire.axis.query.providers.memory import MemoryRelationalProvider, MemoryKVProvider
from emergent.wire.axis.schema import Identity
from emergent.wire.axis.surface.capabilities import ScopeEnricher, EnricherNext
from emergent.wire.axis.surface.triggers.http import Method

from derivelib import (
    Op, Dialect, derive, build_application_from_decorated, dialect,
    HTTPTriggers, HandlerSpec,
    fields, id_only, entity_response, list_response, custom_response,
    Read, Mutation, Creates, Idempotent,
    add_capability, FetchMany, FetchOneById,
)
from derivelib._ctx import OperationHandler
from derivelib._protocols import HasProvider
from derivelib.patterns.crud import http_crud, LIST, GET, CREATE

if TYPE_CHECKING:
    from derivelib._errors import DomainError, NotFound


# ═══════════════════════════════════════════════════════════════════════════════
# Providers (module-level instances — persist across requests)
# ═══════════════════════════════════════════════════════════════════════════════


_users: MemoryRelationalProvider[User] = MemoryRelationalProvider(
    key_fn=lambda x: x.id, next_id=SequenceNextId(),
)
_chats: MemoryRelationalProvider[Chat] = MemoryRelationalProvider(
    key_fn=lambda x: x.id, next_id=SequenceNextId(),
)
_messages: MemoryRelationalProvider[Message] = MemoryRelationalProvider(
    key_fn=lambda x: x.id, next_id=SequenceNextId(),
)


@scalar_node
class UserStore:
    @classmethod
    def __compose__(cls) -> MutatingRelationalProvider[User]:
        return _users


@scalar_node
class ChatStore:
    @classmethod
    def __compose__(cls) -> MutatingRelationalProvider[Chat]:
        return _chats


@scalar_node
class MessageStore:
    @classmethod
    def __compose__(cls) -> MutatingRelationalProvider[Message]:
        return _messages


# ═══════════════════════════════════════════════════════════════════════════════
# Auth — orthogonal token-based auth via ScopeEnricher
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class AuthUser:
    """Authenticated user — injected into scope by TokenAuth."""
    user_id: int
    name: str


_sessions: MemoryKVProvider[str, AuthUser] = MemoryKVProvider()
_session_qs: KVQuerySet[str, AuthUser] = kv(AuthUser, key=lambda u: str(u.user_id))


@dataclass(frozen=True, slots=True)
class TokenAuth(ScopeEnricher):
    """Token auth — reads Authorization header, injects AuthUser into scope.

    Pure gating: no response modification.
    Orthogonal: apply to any dialect via add_capability(TokenAuth(), Mutation).
    """

    async def enrich[R](self, call: EnricherNext[R], scope: Scope) -> R:
        import fastapi

        request = scope.get(fastapi.Request)
        if request is None:
            raise fastapi.HTTPException(401, "no request context")

        auth_header = request.value.headers.get("authorization", "")
        if not auth_header.startswith("Bearer "):
            raise fastapi.HTTPException(401, "missing Authorization: Bearer <token>")

        token = auth_header.removeprefix("Bearer ")
        user = await _sessions.get(_session_qs.get(token))
        if user is None:
            raise fastapi.HTTPException(401, "invalid token")

        scope.inject(AuthUser, user)
        return await call(scope)


# Single transform — apply to any entity's dialect
auth = add_capability(TokenAuth(), Mutation)


# ═══════════════════════════════════════════════════════════════════════════════
# Login dialect — proper derivelib Op (compiles to any target)
# ═══════════════════════════════════════════════════════════════════════════════


def _token_converter[T, E](cls: type, result: Result[T, E]) -> Result[T, E]:
    match result:
        case Ok(token):
            return cls(token=token, error=None)
        case Error(err):
            return cls(token=None, error=str(err))
        case _:
            raise TypeError(f"Expected Result, got {type(result)}")


@dataclass(frozen=True, slots=True)
class IssueToken:
    """Look up entity by name, create session token. Return token."""

    sessions: MemoryKVProvider[str, AuthUser]
    session_qs: KVQuerySet[str, AuthUser]

    def build[EntityT](self, spec: HandlerSpec[EntityT]) -> OperationHandler[Any, DomainError]:
        sessions = self.sessions
        qs = self.session_qs
        base_query = spec.base_query

        async def handler(op: HasProvider[EntityT]) -> Result[str, DomainError]:
            assert base_query is not None
            all_entities = await op.provider.fetch_many(base_query)
            matched = next(
                (e for e in all_entities if getattr(e, "name", None) == getattr(op, "name", None)),
                None,
            )
            if matched is None:
                return Error(NotFound(entity=spec.entity_name, id={"name": getattr(op, "name", "")}))

            token = f"tok_{getattr(matched, 'id', 0)}"
            await sessions.set(qs.set(token, AuthUser(getattr(matched, "id", 0), getattr(matched, "name", ""))))
            return Ok(token)

        return handler


LOGIN_ROUTES: dict[str, tuple[Method, bool]] = {"Login": ("POST", False)}


def auth_login(
    path: str,
    provider_node: type,
    sessions: MemoryKVProvider[str, AuthUser],
    session_qs: KVQuerySet[str, AuthUser],
) -> Dialect:
    """Login dialect — 1 op, issues token. No auth required (public)."""
    return dialect(
        Op("Login", fields("name"), custom_response((("token", str | None), ("error", str | None)), _token_converter),
           IssueToken(sessions, session_qs), effects=(Creates(),)),
        triggers=HTTPTriggers(path, routes=LOGIN_ROUTES),
        provider_node=provider_node,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# AI reply function (replace with OpenAI / Anthropic / local model)
# ═══════════════════════════════════════════════════════════════════════════════


async def ai_reply(text: str, history: list[Message]) -> str:
    """Stub AI — swap for real LLM call.

    Receives user text + full chat history for context.
    """
    n = sum(1 for m in history if m.role == "user")
    if n <= 1:
        return f'Hello! You said: "{text}". How can I help you?'
    return f'Interesting — "{text}". That\'s message #{n} in our conversation.'


# ═══════════════════════════════════════════════════════════════════════════════
# Suggestions — async function (swap for real API call)
# ═══════════════════════════════════════════════════════════════════════════════


async def suggest(reply_text: str) -> list[str]:
    """Generate follow-up suggestions from AI reply.

    Stub — swap for real API call (OpenAI, search, etc).
    """
    if "help" in reply_text.lower():
        return ["Tell me about yourself", "What can you do?", "Surprise me"]
    return ["Tell me more", "Why?", "Change topic"]


# ═══════════════════════════════════════════════════════════════════════════════
# Custom handler: send message + AI auto-reply + suggestions
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class SendAndReply:
    """Insert user message, generate AI reply, insert reply. Return reply.

    Same pattern as InsertNew but with async AI generation + optional suggestions.
    suggest_fn is async — can call external APIs (OpenAI, search, etc).
    """

    reply_fn: Callable[[str, list[Message]], Awaitable[str]]
    suggest_fn: Callable[[str], Awaitable[list[str]]] | None = None

    def build[EntityT](self, spec: HandlerSpec[EntityT]) -> OperationHandler[Any, DomainError]:
        # Any: EntityT is Message at runtime; the handler constructs entities
        # via dynamic attribute access (generic type has no known constructor).
        entity: Any = spec.entity
        base_query = spec.base_query
        suggest = self.suggest_fn

        async def handler(op: HasProvider[EntityT]) -> Result[EntityT, DomainError]:
            provider = op.provider
            chat_id: int = getattr(op, "chat_id")
            text: str = getattr(op, "text")

            # 1. insert user message
            next_id_val: int = await provider.next_id() if isinstance(provider, MemoryRelationalProvider) else 0
            user_msg: EntityT = entity(
                id=next_id_val, chat_id=chat_id, text=text, role="user",
            )
            await provider.insert(user_msg)

            # 2. fetch chat history for AI context
            assert base_query is not None
            all_msgs = await provider.fetch_many(base_query)
            # Any: list[EntityT] can't assign to list[Message] (invariant);
            # reply_fn takes list[Message] but EntityT is Message at runtime.
            history: Any = [m for m in all_msgs if getattr(m, "chat_id", None) == chat_id]

            # 3. generate AI reply
            reply_text = await self.reply_fn(text, history)

            # 4. generate suggestions (async — can hit external APIs)
            suggest_result: list[str] = await suggest(reply_text) if suggest else []

            # 5. insert AI reply
            reply_id: int = await provider.next_id() if isinstance(provider, MemoryRelationalProvider) else 0
            reply_msg: EntityT = entity(
                id=reply_id, chat_id=chat_id, text=reply_text,
                role="assistant", suggestions=suggest_result,
            )
            await provider.insert(reply_msg)

            return Ok(reply_msg)

        return handler


# ═══════════════════════════════════════════════════════════════════════════════
# Message dialect — Send + History + Get
# ═══════════════════════════════════════════════════════════════════════════════


MESSAGE_ROUTES: dict[str, tuple[Method, bool]] = {
    "Send": ("POST", False),      # POST /messages
    "History": ("GET", False),     # GET  /messages?chat_id=...
    "Get": ("GET", True),          # GET  /messages/{id}
}


def http_chat(
    path: str,
    provider_node: type,
    reply_fn: Callable[[str, list[Message]], Awaitable[str]],
    suggest_fn: Callable[[str], Awaitable[list[str]]] | None = None,
) -> Dialect:
    """Chat message dialect — 3 ops, AI auto-reply on send.

    Custom dialect = 3 Ops + custom handler template + custom routes.
    Same algebra as CRUD, different semantics.
    """
    return dialect(
        Op("Send", fields("chat_id", "text"), entity_response(),
           SendAndReply(reply_fn, suggest_fn), effects=(Creates(),)),
        Op("History", fields("chat_id"), list_response(),
           FetchMany(scope_fields=("chat_id",)), effects=(Read(),)),
        Op("Get", id_only(), entity_response(),
           FetchOneById(), effects=(Read(), Idempotent())),
        triggers=HTTPTriggers(path, routes=MESSAGE_ROUTES),
        provider_node=provider_node,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Entities
# ═══════════════════════════════════════════════════════════════════════════════


@derive(
    http_crud("/users", provider_node=UserStore, ops=(LIST, GET, CREATE)),
    auth_login("/login", provider_node=UserStore, sessions=_sessions, session_qs=_session_qs),
)
@dataclass
class User:
    id: Annotated[int, Identity]
    name: str


@derive(http_crud("/chats", provider_node=ChatStore, ops=(LIST, GET, CREATE)).chain(auth))
@dataclass
class Chat:
    id: Annotated[int, Identity]
    user_id: int
    title: str


@derive(http_chat("/messages", provider_node=MessageStore, reply_fn=ai_reply, suggest_fn=suggest).chain(auth))
@dataclass
class Message:
    id: Annotated[int, Identity]
    chat_id: int
    text: str
    role: str = "user"
    suggestions: list[str] = field(default_factory=lambda: [])


# ═══════════════════════════════════════════════════════════════════════════════
# Build
# ═══════════════════════════════════════════════════════════════════════════════


app = build_application_from_decorated(User, Chat, Message)

from emergent.wire.compile import targets  # noqa: E402

fastapi_app = targets.fastapi.compile(app)

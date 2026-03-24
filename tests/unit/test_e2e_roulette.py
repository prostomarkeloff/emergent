"""End-to-end tests modelled on the roulette example.

Exercises the full emergent stack: ops, schema, query, surface, compile.
Every feature the roulette example uses is covered so nothing breaks silently.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Annotated, Protocol, Self

import pytest
from kungfu import Result, Ok, Error

from nodnod import Scope

from emergent.ops._graph import Op, Runner, ops
from emergent.wire.axis.schema import Identity
from emergent.wire.axis.schema._inspect import inspect_dataclass
from emergent.wire.axis.schema._universal import Doc, MaxLen, MinLen, Unique
from emergent.wire.axis.schema.dialects import cli as cli_dialect
from emergent.wire.axis.surface import endpoint, application, empty_runner
from emergent.wire.axis.surface.enrichers import ScopeEnricher, EnricherNext
from emergent.wire.axis.surface.codecs.rrc import rrc
from emergent.wire.axis.surface.codecs.delegate import delegate
from emergent.wire.axis.surface.codecs import immediate_factory
from emergent.wire.axis.surface.enrichers import Inject, Validate, chain_enrichers
from emergent.wire.axis.surface.transforms import AsDict
from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger
from emergent.wire.axis.surface.triggers.cli import CLITrigger
from emergent.wire.axis.query import (
    relational_store,
    MemoryRelationalProvider,
    PrefixedNextId,
    SequenceNextId,
)
from emergent.wire.compile._core import Axes, extract_constraints
from emergent.wire.compile._trace import ListCollector
from emergent.wire.compile.targets.testing import testing_compile as compile_for_test


# ═══════════════════════════════════════════════════════════════════════════════
# Domain types — module level for get_type_hints resolution
# ═══════════════════════════════════════════════════════════════════════════════


class AuthUser(str):
    """Authenticated user identity."""


@dataclass(frozen=True, slots=True)
class Register(Op[str, str]):
    login: str
    password: str


@dataclass(frozen=True, slots=True)
class Login(Op[str, str]):
    login: str
    password: str


@dataclass(frozen=True, slots=True)
class Authenticate(Op[AuthUser, str]):
    token: str


@dataclass(frozen=True, slots=True)
class GetBalance(Op[int, str]):
    pass


@dataclass(frozen=True, slots=True)
class PlaceBet(Op[int, str]):
    bet: str
    amount: int


@dataclass(frozen=True, slots=True)
class RegisterRequest:
    login: Annotated[str, cli_dialect.Help("Username"), Doc("Username")]
    password: Annotated[str, cli_dialect.Help("Password"), Doc("Password")]

    def to_domain(self) -> Register:
        return Register(login=self.login, password=self.password)


@dataclass(frozen=True, slots=True)
class LoginRequest:
    login: str
    password: str

    def to_domain(self) -> Login:
        return Login(login=self.login, password=self.password)


@dataclass(frozen=True, slots=True)
class BalanceRequest:
    token: str

    def to_domain(self) -> GetBalance:
        return GetBalance()

    def to_auth(self) -> Authenticate:
        return Authenticate(token=self.token)


@dataclass(frozen=True, slots=True)
class BetRequest:
    token: str
    bet: str
    amount: int

    def to_domain(self) -> PlaceBet:
        return PlaceBet(bet=self.bet, amount=self.amount)

    def to_auth(self) -> Authenticate:
        return Authenticate(token=self.token)


@dataclass(frozen=True, slots=True)
class TokenResponse:
    token: str | None = None
    error: str | None = None

    @classmethod
    def from_domain(cls, dom: Result[str, str]) -> Self:
        match dom:
            case Ok(token):
                return cls(token=token)
            case Error(err):
                return cls(error=err)


@dataclass(frozen=True, slots=True)
class BalanceResponse:
    balance: int | None = None
    error: str | None = None

    @classmethod
    def from_domain(cls, dom: Result[int, str]) -> Self:
        match dom:
            case Ok(bal):
                return cls(balance=bal)
            case Error(err):
                return cls(error=err)


@dataclass(frozen=True, slots=True)
class BetResponse:
    won: bool | None = None
    payout: int | None = None
    error: str | None = None

    @classmethod
    def from_domain(cls, dom: Result[int, str]) -> Self:
        match dom:
            case Ok(payout):
                return cls(won=payout > 0, payout=payout)
            case Error(err):
                return cls(error=err)


@dataclass(frozen=True, slots=True)
class AuthErrorResponse:
    error: str


@dataclass(frozen=True, slots=True)
class HelpResponse:
    text: str


class HasAuth(Protocol):
    def to_auth(self) -> Authenticate: ...


# --- Schema entity for constraint tests ---

@dataclass(frozen=True, slots=True)
class AnnotatedEntity:
    id: Annotated[int, Identity]
    name: Annotated[str, MinLen(2), MaxLen(50), Doc("User name")]
    email: Annotated[str, Unique, MaxLen(255)]


# ═══════════════════════════════════════════════════════════════════════════════
# Stores — each test gets a fresh instance via fixtures
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class User:
    login: Annotated[str, Identity]
    password_hash: str
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class Session:
    token: Annotated[str, Identity]
    login: str
    created_at: datetime = field(default_factory=datetime.now)


class TxType(Enum):
    CREDIT = "credit"
    DEBIT = "debit"


@dataclass
class Transaction:
    id: Annotated[str, Identity]
    login: str
    tx_type: TxType
    amount: int
    reason: str
    created_at: datetime = field(default_factory=datetime.now)


class TokenStore:
    """In-memory token→login mapping. Replaces global dict."""

    def __init__(self) -> None:
        self._tokens: dict[str, str] = {}

    def put(self, token: str, login: str) -> None:
        self._tokens[token] = login

    def get(self, token: str) -> str | None:
        return self._tokens.get(token)


class AuthStore:
    def __init__(self) -> None:
        self._provider: MemoryRelationalProvider[User] = MemoryRelationalProvider()
        self._users = relational_store(User, self._provider)
        self._session_provider: MemoryRelationalProvider[Session] = MemoryRelationalProvider()
        self._sessions = relational_store(Session, self._session_provider)

    async def user_exists(self, login: str) -> bool:
        return await self._users.filter(lambda u: u.login == login).exists()

    async def get_user(self, login: str) -> User | None:
        return await self._users.filter(lambda u: u.login == login).first()

    async def create_user(self, login: str, password_hash: str) -> None:
        await self._users.insert(User(login=login, password_hash=password_hash))

    async def create_session(self, token: str, login: str) -> None:
        await self._sessions.insert(Session(token=token, login=login))

    async def get_session(self, token: str) -> Session | None:
        return await self._sessions.filter(lambda s: s.token == token).first()


class GameStore:
    INITIAL_BALANCE = 1000

    def __init__(self) -> None:
        self._provider = MemoryRelationalProvider[Transaction](
            next_id=PrefixedNextId("tx_", SequenceNextId()),
        )
        self._transactions = relational_store(Transaction, self._provider)

    async def ensure_balance(self, login: str) -> None:
        async with self._provider.atomic():
            exists = await self._transactions.filter(
                lambda t: t.login == login,
            ).exists()
            if not exists:
                await self._transactions.insert(
                    Transaction(
                        id=await self._provider.next_id(),
                        login=login, tx_type=TxType.CREDIT,
                        amount=self.INITIAL_BALANCE, reason="initial",
                    )
                )

    async def get_balance(self, login: str) -> int:
        txs = await self._transactions.filter(
            lambda t: t.login == login,
        ).fetch_many()
        total = 0
        for tx in txs:
            if tx.tx_type == TxType.CREDIT:
                total += tx.amount
            else:
                total -= tx.amount
        return total


# ═══════════════════════════════════════════════════════════════════════════════
# Handlers — all state flows through injected stores, zero globals
# ═══════════════════════════════════════════════════════════════════════════════


async def handle_register(
    op: Register, auth_store: AuthStore, game_store: GameStore, token_store: TokenStore,
) -> Result[str, str]:
    if await auth_store.user_exists(op.login):
        return Error("user already exists")
    await auth_store.create_user(op.login, op.password)
    token = f"tok_{op.login}"
    await auth_store.create_session(token, op.login)
    token_store.put(token, op.login)
    await game_store.ensure_balance(op.login)
    return Ok(token)


async def handle_login(
    op: Login, auth_store: AuthStore, token_store: TokenStore,
) -> Result[str, str]:
    user = await auth_store.get_user(op.login)
    if user is None or user.password_hash != op.password:
        return Error("invalid credentials")
    token = f"tok_{op.login}"
    token_store.put(token, op.login)
    return Ok(token)


async def handle_authenticate(
    op: Authenticate, token_store: TokenStore,
) -> Result[AuthUser, str]:
    login = token_store.get(op.token)
    if login is None:
        return Error("invalid token")
    return Ok(AuthUser(login))


async def handle_get_balance(
    _op: GetBalance, auth_user: AuthUser, game_store: GameStore,
) -> Result[int, str]:
    return Ok(await game_store.get_balance(auth_user))


async def handle_place_bet(
    op: PlaceBet, auth_user: AuthUser, game_store: GameStore,
) -> Result[int, str]:
    balance = await game_store.get_balance(auth_user)
    if op.amount <= 0:
        return Error("amount must be positive")
    if op.amount > balance:
        return Error("insufficient balance")
    return Ok(op.amount * 2)


# ═══════════════════════════════════════════════════════════════════════════════
# Auth Enricher — references auth_runner via field, no globals
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class Auth(ScopeEnricher):
    request_cls: type[HasAuth]
    auth_runner: Runner

    async def enrich[R](self, call: EnricherNext[R], scope: Scope) -> R | AuthErrorResponse:
        req_value = scope.get(self.request_cls)
        if req_value is None:
            return AuthErrorResponse(error="request not in scope")
        req: HasAuth = req_value.value
        result: Result[AuthUser, str] = await self.auth_runner.run(req.to_auth())
        match result:
            case Ok(user):
                scope.inject(AuthUser, user)
                return await call(scope)
            case Error(e):
                return AuthErrorResponse(error=e)


# ═══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class Env:
    """All per-test state bundled together."""

    auth_store: AuthStore
    game_store: GameStore
    token_store: TokenStore
    auth_runner: Runner
    game_runner: Runner


@pytest.fixture()
def env() -> Env:
    auth_s = AuthStore()
    game_s = GameStore()
    tok_s = TokenStore()

    auth_r = (
        ops()
        .on(Register, handle_register)
        .on(Login, handle_login)
        .on(Authenticate, handle_authenticate)
        .compile()
        .inject(AuthStore, auth_s)
        .inject(GameStore, game_s)
        .inject(TokenStore, tok_s)
    )
    game_r = (
        ops()
        .on(GetBalance, handle_get_balance)
        .on(PlaceBet, handle_place_bet)
        .compile()
        .inject(GameStore, game_s)
    )
    return Env(
        auth_store=auth_s,
        game_store=game_s,
        token_store=tok_s,
        auth_runner=auth_r,
        game_runner=game_r,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Ops Pipeline — runner dispatch, DI injection, scope_extras
# ═══════════════════════════════════════════════════════════════════════════════


class TestOpsPipeline:

    @pytest.mark.asyncio
    async def test_register_returns_token(self, env: Env) -> None:
        result = await env.auth_runner.run(Register(login="alice", password="secret"))
        assert isinstance(result, Ok)
        assert result.unwrap() == "tok_alice"

    @pytest.mark.asyncio
    async def test_register_duplicate(self, env: Env) -> None:
        await env.auth_runner.run(Register(login="alice", password="s"))
        result = await env.auth_runner.run(Register(login="alice", password="s"))
        assert isinstance(result, Error)
        assert "already exists" in result.unwrap_err()

    @pytest.mark.asyncio
    async def test_login_success(self, env: Env) -> None:
        await env.auth_runner.run(Register(login="alice", password="secret"))
        result = await env.auth_runner.run(Login(login="alice", password="secret"))
        assert isinstance(result, Ok)

    @pytest.mark.asyncio
    async def test_login_wrong_password(self, env: Env) -> None:
        await env.auth_runner.run(Register(login="alice", password="secret"))
        result = await env.auth_runner.run(Login(login="alice", password="wrong"))
        assert isinstance(result, Error)
        assert "invalid" in result.unwrap_err()

    @pytest.mark.asyncio
    async def test_authenticate_valid(self, env: Env) -> None:
        await env.auth_runner.run(Register(login="alice", password="s"))
        result = await env.auth_runner.run(Authenticate(token="tok_alice"))
        assert isinstance(result, Ok)
        assert result.unwrap() == AuthUser("alice")

    @pytest.mark.asyncio
    async def test_authenticate_invalid(self, env: Env) -> None:
        result = await env.auth_runner.run(Authenticate(token="bogus"))
        assert isinstance(result, Error)

    @pytest.mark.asyncio
    async def test_balance_via_scope_extras(self, env: Env) -> None:
        result = await env.game_runner.run(
            GetBalance(),
            scope_extras={AuthUser: AuthUser("ghost")},
        )
        assert isinstance(result, Ok)
        assert result.unwrap() == 0

    @pytest.mark.asyncio
    async def test_register_creates_initial_balance(self, env: Env) -> None:
        await env.auth_runner.run(Register(login="bob", password="p"))
        result = await env.game_runner.run(
            GetBalance(),
            scope_extras={AuthUser: AuthUser("bob")},
        )
        assert isinstance(result, Ok)
        assert result.unwrap() == 1000

    @pytest.mark.asyncio
    async def test_bet_insufficient_balance(self, env: Env) -> None:
        result = await env.game_runner.run(
            PlaceBet(bet="red", amount=100),
            scope_extras={AuthUser: AuthUser("nobody")},
        )
        assert isinstance(result, Error)
        assert "insufficient" in result.unwrap_err()

    @pytest.mark.asyncio
    async def test_bet_negative_amount(self, env: Env) -> None:
        await env.auth_runner.run(Register(login="alice", password="p"))
        result = await env.game_runner.run(
            PlaceBet(bet="red", amount=-5),
            scope_extras={AuthUser: AuthUser("alice")},
        )
        assert isinstance(result, Error)
        assert "positive" in result.unwrap_err()

    @pytest.mark.asyncio
    async def test_bet_success(self, env: Env) -> None:
        await env.auth_runner.run(Register(login="alice", password="p"))
        result = await env.game_runner.run(
            PlaceBet(bet="red", amount=50),
            scope_extras={AuthUser: AuthUser("alice")},
        )
        assert isinstance(result, Ok)
        assert result.unwrap() == 100


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Query Axis — relational store CRUD, filtering, ID generation
# ═══════════════════════════════════════════════════════════════════════════════


class TestQueryAxis:

    @pytest.mark.asyncio
    async def test_insert_and_exists(self) -> None:
        provider: MemoryRelationalProvider[User] = MemoryRelationalProvider()
        store = relational_store(User, provider)
        assert not await store.filter(lambda u: u.login == "alice").exists()
        await store.insert(User(login="alice", password_hash="h"))
        assert await store.filter(lambda u: u.login == "alice").exists()

    @pytest.mark.asyncio
    async def test_filter_first(self) -> None:
        provider: MemoryRelationalProvider[User] = MemoryRelationalProvider()
        store = relational_store(User, provider)
        await store.insert(User(login="alice", password_hash="h1"))
        await store.insert(User(login="bob", password_hash="h2"))
        user = await store.filter(lambda u: u.login == "bob").first()
        assert user is not None
        assert user.login == "bob"
        assert user.password_hash == "h2"

    @pytest.mark.asyncio
    async def test_first_not_found(self) -> None:
        provider: MemoryRelationalProvider[User] = MemoryRelationalProvider()
        store = relational_store(User, provider)
        assert await store.filter(lambda u: u.login == "ghost").first() is None

    @pytest.mark.asyncio
    async def test_fetch_many(self) -> None:
        provider: MemoryRelationalProvider[User] = MemoryRelationalProvider()
        store = relational_store(User, provider)
        for name in ("a", "b", "c"):
            await store.insert(User(login=name, password_hash="h"))
        all_users = await store.filter(lambda u: u.login != "").fetch_many()
        assert len(all_users) == 3

    @pytest.mark.asyncio
    async def test_filter_fetch_many(self) -> None:
        provider: MemoryRelationalProvider[User] = MemoryRelationalProvider()
        store = relational_store(User, provider)
        await store.insert(User(login="a", password_hash="x"))
        await store.insert(User(login="b", password_hash="y"))
        await store.insert(User(login="c", password_hash="x"))
        result = await store.filter(lambda u: u.password_hash == "x").fetch_many()
        assert {u.login for u in result} == {"a", "c"}

    @pytest.mark.asyncio
    async def test_delete(self) -> None:
        provider: MemoryRelationalProvider[User] = MemoryRelationalProvider()
        store = relational_store(User, provider)
        user = User(login="alice", password_hash="h")
        await store.insert(user)
        await store.delete(user)
        assert not await store.filter(lambda u: u.login == "alice").exists()

    @pytest.mark.asyncio
    async def test_prefixed_next_id(self) -> None:
        provider = MemoryRelationalProvider[Transaction](
            next_id=PrefixedNextId("tx_", SequenceNextId()),
        )
        id1 = await provider.next_id()
        id2 = await provider.next_id()
        assert id1.startswith("tx_")
        assert id2.startswith("tx_")
        assert id1 != id2

    @pytest.mark.asyncio
    async def test_ledger_balance(self) -> None:
        game = GameStore()
        await game.ensure_balance("alice")
        assert await game.get_balance("alice") == GameStore.INITIAL_BALANCE

    @pytest.mark.asyncio
    async def test_ledger_idempotent(self) -> None:
        game = GameStore()
        await game.ensure_balance("alice")
        await game.ensure_balance("alice")
        assert await game.get_balance("alice") == GameStore.INITIAL_BALANCE

    @pytest.mark.asyncio
    async def test_ledger_unknown_user_zero(self) -> None:
        assert await GameStore().get_balance("unknown") == 0


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Schema Axis — inspect, Identity, Doc, MinLen, MaxLen, Unique, multi-dialect
# ═══════════════════════════════════════════════════════════════════════════════


class TestSchemaAxis:

    def test_identity(self) -> None:
        fields = inspect_dataclass(AnnotatedEntity)
        assert fields["id"].has(Identity)

    def test_doc(self) -> None:
        fields = inspect_dataclass(AnnotatedEntity)
        doc = fields["name"].get(Doc)
        assert doc is not None
        assert doc.text == "User name"

    def test_minlen_maxlen(self) -> None:
        fields = inspect_dataclass(AnnotatedEntity)
        min_len = fields["name"].get(MinLen)
        max_len = fields["name"].get(MaxLen)
        assert min_len is not None
        assert max_len is not None
        assert min_len.value == 2
        assert max_len.value == 50

    def test_unique(self) -> None:
        assert inspect_dataclass(AnnotatedEntity)["email"].has(Unique)

    def test_extract_constraints(self) -> None:
        c = extract_constraints(inspect_dataclass(AnnotatedEntity)["name"])
        assert c.min_length == 2
        assert c.max_length == 50

    def test_identity_constraint(self) -> None:
        assert extract_constraints(inspect_dataclass(AnnotatedEntity)["id"]).is_identity

    def test_unique_constraint(self) -> None:
        assert extract_constraints(inspect_dataclass(AnnotatedEntity)["email"]).is_unique

    def test_multi_dialect_annotations(self) -> None:
        fields = inspect_dataclass(RegisterRequest)
        assert fields["login"].has(Doc)
        assert fields["login"].has(cli_dialect.Help)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Surface Axis — endpoint, expose, application, multi-trigger, capabilities
# ═══════════════════════════════════════════════════════════════════════════════


class TestSurfaceAxis:

    def test_single_expose(self, env: Env) -> None:
        ep = endpoint(env.auth_runner).expose(
            HTTPRouteTrigger("POST", "/register"),
            rrc(RegisterRequest, TokenResponse),
        )
        assert len(ep.exposures) == 1

    def test_multi_expose(self, env: Env) -> None:
        ep = (
            endpoint(env.auth_runner)
            .expose(HTTPRouteTrigger("POST", "/r"), rrc(RegisterRequest, TokenResponse))
            .expose(CLITrigger("register", "Register"), rrc(RegisterRequest, TokenResponse))
        )
        assert len(ep.exposures) == 2
        trigger_types = {type(e.trigger) for e in ep.exposures}
        assert trigger_types == {HTTPRouteTrigger, CLITrigger}

    def test_application_mount(self, env: Env) -> None:
        ep1 = endpoint(env.auth_runner).expose(
            HTTPRouteTrigger("POST", "/a"), rrc(RegisterRequest, TokenResponse),
        )
        ep2 = endpoint(env.auth_runner).expose(
            HTTPRouteTrigger("POST", "/b"), rrc(LoginRequest, TokenResponse),
        )
        app = application().mount(ep1, ep2)
        assert len(app.endpoints) == 2

    def test_application_merge(self, env: Env) -> None:
        a1 = application().mount(
            endpoint(env.auth_runner).expose(
                HTTPRouteTrigger("POST", "/a"), rrc(RegisterRequest, TokenResponse),
            )
        )
        a2 = application().mount(
            endpoint(env.auth_runner).expose(
                HTTPRouteTrigger("POST", "/b"), rrc(LoginRequest, TokenResponse),
            )
        )
        assert len((a1 + a2).endpoints) == 2

    def test_capabilities_on_exposure(self, env: Env) -> None:
        auth_cap = Auth(BalanceRequest, env.auth_runner)
        ep = endpoint(env.game_runner).expose(
            HTTPRouteTrigger("GET", "/balance"),
            rrc(BalanceRequest, BalanceResponse),
            auth_cap,
        )
        assert ep.exposures[0].capabilities == (auth_cap,)

    def test_immediate_factory_codec(self) -> None:
        ep = endpoint(empty_runner()).expose(
            CLITrigger("help", "Help"),
            immediate_factory(lambda: HelpResponse(text="hi")),
        )
        assert len(ep.exposures) == 1

    def test_mount_returns_new_app(self, env: Env) -> None:
        ep = endpoint(env.auth_runner).expose(
            HTTPRouteTrigger("POST", "/r"), rrc(RegisterRequest, TokenResponse),
        )
        app1 = application()
        app2 = app1.mount(ep)
        assert len(app1.endpoints) == 0
        assert len(app2.endpoints) == 1

    def test_with_capabilities(self) -> None:
        app = application().with_capabilities(Inject(type=int, value=42))
        assert len(app.capabilities) == 1


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Compile Pipeline — full end-to-end via compile_for_test
# ═══════════════════════════════════════════════════════════════════════════════


class TestCompilePipeline:

    @pytest.mark.asyncio
    async def test_rrc_roundtrip(self, env: Env) -> None:
        app = application().mount(
            endpoint(env.auth_runner).expose(
                HTTPRouteTrigger("POST", "/register"),
                rrc(RegisterRequest, TokenResponse),
            )
        )
        test = compile_for_test(app)
        result = await test.routes[0].call({"login": "alice", "password": "s"})
        assert isinstance(result, TokenResponse)
        assert result.token == "tok_alice"
        assert result.error is None

    @pytest.mark.asyncio
    async def test_rrc_error_propagates(self, env: Env) -> None:
        app = application().mount(
            endpoint(env.auth_runner).expose(
                HTTPRouteTrigger("POST", "/register"),
                rrc(RegisterRequest, TokenResponse),
            )
        )
        test = compile_for_test(app)
        await test.routes[0].call({"login": "alice", "password": "s"})
        result = await test.routes[0].call({"login": "alice", "password": "s"})
        assert isinstance(result, TokenResponse)
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_two_routes_register_then_login(self, env: Env) -> None:
        app = application().mount(
            endpoint(env.auth_runner).expose(
                HTTPRouteTrigger("POST", "/register"),
                rrc(RegisterRequest, TokenResponse),
            ),
            endpoint(env.auth_runner).expose(
                HTTPRouteTrigger("POST", "/login"),
                rrc(LoginRequest, TokenResponse),
            ),
        )
        test = compile_for_test(app)
        await test.routes[0].call({"login": "alice", "password": "secret"})
        result = await test.routes[1].call({"login": "alice", "password": "secret"})
        assert isinstance(result, TokenResponse)
        assert result.token is not None

    @pytest.mark.asyncio
    async def test_immediate_factory(self) -> None:
        app = application().mount(
            endpoint(empty_runner()).expose(
                CLITrigger("help", "Help"),
                immediate_factory(lambda: HelpResponse(text="hello")),
            )
        )
        result = await compile_for_test(app).routes[0].call()
        assert isinstance(result, HelpResponse)
        assert result.text == "hello"

    @pytest.mark.asyncio
    async def test_multi_route_count(self, env: Env) -> None:
        app = application().mount(
            endpoint(env.auth_runner).expose(
                HTTPRouteTrigger("POST", "/register"),
                rrc(RegisterRequest, TokenResponse),
            ),
            endpoint(env.auth_runner).expose(
                HTTPRouteTrigger("POST", "/login"),
                rrc(LoginRequest, TokenResponse),
            ),
            endpoint(empty_runner()).expose(
                CLITrigger("help", "Help"),
                immediate_factory(lambda: HelpResponse(text="h")),
            ),
        )
        assert len(compile_for_test(app).routes) == 3

    @pytest.mark.asyncio
    async def test_as_dict_transform(self, env: Env) -> None:
        app = application().mount(
            endpoint(env.auth_runner).expose(
                HTTPRouteTrigger("POST", "/register"),
                rrc(RegisterRequest, TokenResponse),
                AsDict(),
            )
        )
        result = await compile_for_test(app).routes[0].call(
            {"login": "alice", "password": "s"},
        )
        assert isinstance(result, dict)
        assert "token" in result


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Enricher Chain — inject, validate, short-circuit, ordering
# ═══════════════════════════════════════════════════════════════════════════════


class TestEnricherChain:

    @pytest.mark.asyncio
    async def test_inject(self) -> None:
        enricher = Inject(type=AuthUser, value=AuthUser("alice"))

        async def handler(s: Scope) -> str:
            wrapper = s.get(AuthUser)
            assert wrapper is not None
            assert wrapper.value == AuthUser("alice")
            return "ok"

        assert await chain_enrichers((enricher,), handler)(Scope()) == "ok"

    @pytest.mark.asyncio
    async def test_validate_pass(self) -> None:
        scope = Scope()
        scope.inject(int, 42)

        def extract_int(s: Scope) -> int:
            wrapper = s.get(int)
            assert wrapper is not None
            return wrapper.value

        enricher = Validate(
            extract=extract_int,
            predicate=lambda v: v > 0,
            on_invalid=lambda v: f"bad: {v}",
        )

        async def handler(s: Scope) -> str:
            return "passed"

        assert await chain_enrichers((enricher,), handler)(scope) == "passed"

    @pytest.mark.asyncio
    async def test_validate_reject(self) -> None:
        scope = Scope()
        scope.inject(int, -1)

        def extract_int(s: Scope) -> int:
            wrapper = s.get(int)
            assert wrapper is not None
            return wrapper.value

        enricher = Validate(
            extract=extract_int,
            predicate=lambda v: v > 0,
            on_invalid=lambda v: f"bad: {v}",
        )

        async def handler(s: Scope) -> str:
            pytest.fail("should not be called")
            return ""

        assert await chain_enrichers((enricher,), handler)(scope) == "bad: -1"

    @pytest.mark.asyncio
    async def test_ordering(self) -> None:
        order: list[str] = []

        @dataclass(frozen=True, slots=True)
        class Rec(ScopeEnricher):
            name: str

            async def enrich[R](self, call: EnricherNext[R], scope: Scope) -> R:
                order.append(f">{self.name}")
                result = await call(scope)
                order.append(f"<{self.name}")
                return result

        async def handler(s: Scope) -> str:
            order.append("handler")
            return "ok"

        await chain_enrichers((Rec("a"), Rec("b")), handler)(Scope())
        assert order == [">a", ">b", "handler", "<b", "<a"]

    @pytest.mark.asyncio
    async def test_auth_enricher_success(self, env: Env) -> None:
        await env.auth_runner.run(Register(login="alice", password="s"))
        scope = Scope()
        scope.inject(BalanceRequest, BalanceRequest(token="tok_alice"))

        async def handler(s: Scope) -> str:
            wrapper = s.get(AuthUser)
            assert wrapper is not None
            assert wrapper.value == AuthUser("alice")
            return "authorized"

        result = await chain_enrichers(
            (Auth(BalanceRequest, env.auth_runner),), handler,
        )(scope)
        assert result == "authorized"

    @pytest.mark.asyncio
    async def test_auth_enricher_reject(self, env: Env) -> None:
        scope = Scope()
        scope.inject(BalanceRequest, BalanceRequest(token="bad"))

        async def handler(s: Scope) -> str:
            pytest.fail("should not be called")
            return ""

        result = await chain_enrichers(
            (Auth(BalanceRequest, env.auth_runner),), handler,
        )(scope)
        assert isinstance(result, AuthErrorResponse)
        assert "invalid" in result.error


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Multi-Exposure — same endpoint, multiple triggers
# ═══════════════════════════════════════════════════════════════════════════════


class TestMultiExposure:

    @pytest.mark.asyncio
    async def test_dual_trigger_two_routes(self, env: Env) -> None:
        app = application().mount(
            endpoint(env.auth_runner)
            .expose(HTTPRouteTrigger("POST", "/register"), rrc(RegisterRequest, TokenResponse))
            .expose(CLITrigger("register", "Register"), rrc(RegisterRequest, TokenResponse))
        )
        assert len(compile_for_test(app).routes) == 2

    @pytest.mark.asyncio
    async def test_dual_trigger_both_work(self, env: Env) -> None:
        app = application().mount(
            endpoint(env.auth_runner)
            .expose(HTTPRouteTrigger("POST", "/register"), rrc(RegisterRequest, TokenResponse))
            .expose(CLITrigger("register", "Register"), rrc(RegisterRequest, TokenResponse))
        )
        test = compile_for_test(app)
        r0 = await test.routes[0].call({"login": "alice", "password": "p"})
        r1 = await test.routes[1].call({"login": "bob", "password": "p"})
        assert isinstance(r0, TokenResponse) and r0.token is not None
        assert isinstance(r1, TokenResponse) and r1.token is not None


# ═══════════════════════════════════════════════════════════════════════════════
# 8. Delegate Codec
# ═══════════════════════════════════════════════════════════════════════════════


class TestDelegateCodec:

    @pytest.mark.asyncio
    async def test_basic(self) -> None:
        async def handler(scope: Scope) -> str:
            return "delegate_ok"

        app = application().mount(
            endpoint(empty_runner()).expose(
                HTTPRouteTrigger("GET", "/status"),
                delegate(handler, response=str),
            )
        )
        assert await compile_for_test(app).routes[0].call() == "delegate_ok"

    @pytest.mark.asyncio
    async def test_with_scope_inject(self) -> None:
        async def handler(scope: Scope) -> str:
            w = scope.get(AuthUser)
            return f"user:{w.value}" if w else "anon"

        app = application().mount(
            endpoint(empty_runner()).expose(
                HTTPRouteTrigger("GET", "/me"),
                delegate(handler, response=str),
            )
        )
        result = await compile_for_test(app).routes[0].call(
            inject=lambda scope: scope.inject(AuthUser, AuthUser("bob")),
        )
        assert result == "user:bob"


# ═══════════════════════════════════════════════════════════════════════════════
# 9. Protocol Contracts — to_domain, from_domain, to_auth
# ═══════════════════════════════════════════════════════════════════════════════


class TestProtocolContracts:

    def test_register_request_to_domain(self) -> None:
        op = RegisterRequest(login="a", password="b").to_domain()
        assert isinstance(op, Register)
        assert op.login == "a"

    def test_balance_request_to_auth(self) -> None:
        auth_op = BalanceRequest(token="tok").to_auth()
        assert isinstance(auth_op, Authenticate)
        assert auth_op.token == "tok"

    def test_bet_request_to_domain(self) -> None:
        op = BetRequest(token="t", bet="red", amount=50).to_domain()
        assert isinstance(op, PlaceBet)
        assert op.bet == "red" and op.amount == 50

    def test_token_response_ok(self) -> None:
        r = TokenResponse.from_domain(Ok("tok"))
        assert r.token == "tok" and r.error is None

    def test_token_response_error(self) -> None:
        r = TokenResponse.from_domain(Error("bad"))
        assert r.token is None and r.error == "bad"

    def test_balance_response_ok(self) -> None:
        assert BalanceResponse.from_domain(Ok(42)).balance == 42

    def test_bet_response_ok(self) -> None:
        r = BetResponse.from_domain(Ok(100))
        assert r.won is True and r.payout == 100

    def test_bet_response_zero_payout(self) -> None:
        r = BetResponse.from_domain(Ok(0))
        assert r.won is False

    def test_bet_response_error(self) -> None:
        assert BetResponse.from_domain(Error("nope")).error == "nope"


# ═══════════════════════════════════════════════════════════════════════════════
# 10. Tracing — Axes.traced, compile with tracing
# ═══════════════════════════════════════════════════════════════════════════════


class TestTracing:

    @pytest.mark.asyncio
    async def test_events_collected(self, env: Env) -> None:
        collector = ListCollector()
        app = application().mount(
            endpoint(env.auth_runner).expose(
                HTTPRouteTrigger("POST", "/register"),
                rrc(RegisterRequest, TokenResponse),
            )
        )
        compile_for_test(app, axes=Axes.traced(collector))
        assert len(collector.scan_events) > 0
        assert len(collector.wrap_events) > 0

    @pytest.mark.asyncio
    async def test_traced_call_still_works(self, env: Env) -> None:
        collector = ListCollector()
        app = application().mount(
            endpoint(env.auth_runner).expose(
                HTTPRouteTrigger("POST", "/register"),
                rrc(RegisterRequest, TokenResponse),
            )
        )
        test = compile_for_test(app, axes=Axes.traced(collector))
        result = await test.routes[0].call({"login": "alice", "password": "s"})
        assert isinstance(result, TokenResponse)
        assert result.token is not None


# ═══════════════════════════════════════════════════════════════════════════════
# 11. Full Roulette Smoke — mini-app exercising everything together
# ═══════════════════════════════════════════════════════════════════════════════


class TestFullRouletteSmoke:

    @pytest.mark.asyncio
    async def test_full_app_lifecycle(self, env: Env) -> None:
        """Build mini-roulette, compile, exercise register→login→balance→bet."""
        app = application().mount(
            endpoint(env.auth_runner).expose(
                HTTPRouteTrigger("POST", "/register"),
                rrc(RegisterRequest, TokenResponse),
            ),
            endpoint(env.auth_runner).expose(
                HTTPRouteTrigger("POST", "/login"),
                rrc(LoginRequest, TokenResponse),
            ),
            endpoint(empty_runner()).expose(
                CLITrigger("help", "Help"),
                immediate_factory(lambda: HelpResponse(text="Roulette Bot")),
            ),
        )
        test = compile_for_test(app)
        assert len(test.routes) == 3

        # Register
        r = await test.routes[0].call({"login": "alice", "password": "secret"})
        assert isinstance(r, TokenResponse) and r.token is not None

        # Login
        r = await test.routes[1].call({"login": "alice", "password": "secret"})
        assert isinstance(r, TokenResponse) and r.token is not None

        # Help
        r = await test.routes[2].call()
        assert isinstance(r, HelpResponse) and "Roulette" in r.text

    @pytest.mark.asyncio
    async def test_ops_full_journey(self, env: Env) -> None:
        """Ops-level: register → authenticate → balance → bet."""
        # Register
        reg = await env.auth_runner.run(Register(login="alice", password="s"))
        assert isinstance(reg, Ok)

        # Authenticate
        auth = await env.auth_runner.run(Authenticate(token="tok_alice"))
        assert isinstance(auth, Ok)
        user = auth.unwrap()

        # Balance (1000 initial)
        bal = await env.game_runner.run(GetBalance(), scope_extras={AuthUser: user})
        assert isinstance(bal, Ok)
        assert bal.unwrap() == 1000

        # Bet
        bet = await env.game_runner.run(
            PlaceBet(bet="red", amount=50), scope_extras={AuthUser: user},
        )
        assert isinstance(bet, Ok)
        assert bet.unwrap() == 100

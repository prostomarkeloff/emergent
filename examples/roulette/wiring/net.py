"""FastAPI wiring — HTTP endpoints for roulette.

Run with: uvicorn roulette.wiring.fastapi:app --reload
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Self

import fastapi
from kungfu import Option, Some, Nothing, Result, Ok, Error
from nodnod import NodeError
from nodnod.interface.scalar import scalar_node
from pydantic import BaseModel

from emergent.wire import endpoint, application
from emergent.wire.codecs.rrc import RequestResponseCodec, rrc
from emergent.wire.codecs.stateful import stateful, Done
from emergent.wire.triggers.http import HTTPRouteTrigger
from emergent.wire.contrib import fastapi as wire_fastapi

from roulette.auth.ops import Register, Login, Authenticate
from roulette.game.ops import GetBalance, PlaceBet
from roulette.game.domain import BetResult
from roulette.wiring import (
    auth_runner,
    game_runner,
    auth_mw,
    stateful_auth_mw,
    RegisterResponse,
    LoginResponse,
    BalanceResponse,
    BetResponse,
)


# ═══════════════════════════════════════════════════════════════════════════
# HTTP Request Types
# ═══════════════════════════════════════════════════════════════════════════


class RegisterRequest(BaseModel):
    """POST request — Pydantic for body parsing."""

    login: str
    password: str

    def to_domain(self) -> Register:
        return Register(login=self.login, password=self.password)


class LoginRequest(BaseModel):
    """POST request — Pydantic for body parsing."""

    login: str
    password: str

    def to_domain(self) -> Login:
        return Login(login=self.login, password=self.password)


class BalanceRequest(BaseModel):
    """GET request — Pydantic for query params."""

    token: str

    def to_domain(self) -> GetBalance:
        return GetBalance()

    def to_auth(self) -> Authenticate:
        return Authenticate(token=self.token)


class BetRequest(BaseModel):
    """POST request — Pydantic for body parsing."""

    token: str
    bet: str
    amount: int

    def to_domain(self) -> PlaceBet:
        return PlaceBet(bet=self.bet, amount=self.amount)

    def to_auth(self) -> Authenticate:
        return Authenticate(token=self.token)


# ═══════════════════════════════════════════════════════════════════════════
# Betting Flow — Single-class FSM with __transition__ + to_domain
# ═══════════════════════════════════════════════════════════════════════════


@scalar_node
class SessionId:
    """Extract session key from cookie — node-like."""

    @classmethod
    def __compose__(cls, request: fastapi.Request) -> str:
        session = request.cookies.get("session_id")
        if not session:
            raise NodeError("No session cookie")
        return session


@scalar_node
class HttpToken:
    """Extract auth token from header — node-like."""

    @classmethod
    def __compose__(cls, request: fastapi.Request) -> str:
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            raise NodeError("Missing Bearer token")
        return auth[7:]


class BetInput(BaseModel):
    """Pydantic model for bet input — node-like."""

    bet_type: str
    amount: int


# ─── Response Models (Pydantic → OpenAPI schema) ─────────────────────────────


class TokenAcceptedResponse(BaseModel):
    """Intermediate response after token accepted."""

    status: str = "token_accepted"
    next_step: str = "send bet_input"


class FlowBetResponse(BaseModel):
    """Final response from stateful bet flow."""

    won: bool | None = None
    number: int | None = None
    new_balance: int | None = None
    error: str | None = None

    @classmethod
    def from_domain(cls, dom: Result[BetResult, str]) -> FlowBetResponse:
        match dom:
            case Ok(r):
                return cls(won=r.won, number=r.number, new_balance=r.new_balance)
            case Error(e):
                return cls(error=str(e))
            case _:
                return cls(error="Unknown error")


# Union for OpenAPI — intermediate OR final response
BetFlowResponse = TokenAcceptedResponse | FlowBetResponse


# ─── Flow ────────────────────────────────────────────────────────────────────


@dataclass
class HttpBetFlow:
    """HTTP stateful bet flow — collects token, then bet input.

    __transition__: state changes + intermediate responses
    to_domain(): called when Done — constructs PlaceBet Op

    The flow is PURE — no runners called directly.
    Auth middleware handles authentication when Done.
    """

    token: Option[str] = field(default_factory=Nothing)
    bet_type: Option[str] = field(default_factory=Nothing)
    amount: Option[int] = field(default_factory=Nothing)

    async def __transition__(
        self,
        token: Option[HttpToken],
        bet_input: Option[BetInput],
        request: fastapi.Request,
    ) -> Self | tuple[Self, TokenAcceptedResponse] | Done:
        """State transitions. Returns intermediate response for HTTP."""

        # Step 1: Collect token from header
        match (self.token, token):
            case (Nothing(), Some(t)):
                return (replace(self, token=Some(t)), TokenAcceptedResponse())
            case _:
                pass

        # Step 2: Have token, collect bet input → store and Done
        match (self.token, bet_input):
            case (Some(_), Some(bet)):
                # Must store bet data before Done - to_domain() needs it
                self.bet_type = Some(bet.bet_type)
                self.amount = Some(bet.amount)
                return Done()  # Triggers middleware + to_domain() + runner
            case _:
                pass

        return self

    def to_domain(self) -> PlaceBet:
        """Called when Done — constructs Op from accumulated state."""
        return PlaceBet(
            bet=self.bet_type.unwrap(),
            amount=self.amount.unwrap(),
        )


# ═══════════════════════════════════════════════════════════════════════════
# Wire & Compile
# ═══════════════════════════════════════════════════════════════════════════


wire_app = application().mount(
    # Auth — public
    endpoint(auth_runner).expose(
        HTTPRouteTrigger("POST", "/register"),
        RequestResponseCodec(RegisterRequest, RegisterResponse),
    ),
    endpoint(auth_runner).expose(
        HTTPRouteTrigger("POST", "/login"),
        RequestResponseCodec(LoginRequest, LoginResponse),
    ),
    # Game — with auth middleware (RRC)
    endpoint(game_runner).expose(
        HTTPRouteTrigger("GET", "/balance"),
        rrc(BalanceRequest, BalanceResponse).use(auth_mw).build(),
    ),
    endpoint(game_runner).expose(
        HTTPRouteTrigger("POST", "/bet"),
        rrc(BetRequest, BetResponse).use(auth_mw).build(),
    ),
    # Stateful flow — with auth middleware (StatefulCodec)
    endpoint(game_runner).expose(
        HTTPRouteTrigger("POST", "/bet/flow"),
        stateful(HttpBetFlow, BetFlowResponse).key(SessionId).use(stateful_auth_mw).build(),
    ),
)

app = wire_fastapi.from_application(wire_app)

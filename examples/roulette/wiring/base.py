"""Shared wiring components — middleware, response types, runners.

Transport-specific wiring modules import from here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from kungfu import Result, Ok, Error, Option, Some

from emergent.wire import middleware
from emergent.wire.codecs.stateful import stateful_middleware

from roulette.auth.ops import Authenticate, AuthUser, TelegramIdentity, TrustedIdentity
from roulette.auth.runner import auth_runner
from roulette.game.domain import BetResult
from roulette.game.runner import game_runner


# ── Re-exports ────────────────────────────────────────────────────────────

__all__ = [
    "auth_runner",
    "game_runner",
    # HTTP middleware (token-based)
    "auth_mw",
    "stateful_auth_mw",
    # Telegram middleware (chat_id-based)
    "tg_auth_mw",
    "stateful_tg_auth_mw",
    # CLI middleware (trusted session)
    "cli_auth_mw",
    # Protocols
    "HasAuth",
    "HasToken",
    # Responses
    "AuthErrorResponse",
    "RegisterResponse",
    "LoginResponse",
    "LinkResponse",
    "BalanceResponse",
    "BetResponse",
]


# ── Middleware axis (RRC) ─────────────────────────────────────────────────


class HasAuth(Protocol):
    """Request protocol for the auth middleware axis."""

    def to_auth(self) -> Authenticate: ...


@dataclass
class AuthErrorResponse:
    """Middleware rejection response — axes don't mix."""

    error: str

    @classmethod
    def from_domain(cls, dom: Result[AuthUser, str]) -> AuthErrorResponse:
        match dom:
            case Error(e):
                return cls(error=e)
            case _:
                return cls(error="auth failed")

    def __str__(self) -> str:
        return f"Auth error: {self.error}"


def _build_auth_from_request(req: HasAuth) -> Authenticate:
    return req.to_auth()


auth_mw = middleware(
    auth_runner,
    AuthUser,
    _build_auth_from_request,
    AuthErrorResponse.from_domain,
)


# ── Stateful Middleware ───────────────────────────────────────────────────


class HasToken(Protocol):
    """State protocol for stateful auth middleware."""

    token: Option[str]


def _build_auth_op(state: HasToken) -> Authenticate | None:
    """Build auth op from state. None if no token yet."""
    match state.token:
        case Some(tok):
            return Authenticate(token=tok)
        case _:
            return None


stateful_auth_mw = stateful_middleware(
    auth_runner,
    AuthUser,
    _build_auth_op,
    AuthErrorResponse.from_domain,
)


# ── Telegram Middleware (trusted transport) ──────────────────────────────


class HasChatId(Protocol):
    """Protocol for extracting chat_id from request/state."""

    chat_id: int


def _tg_auth_op(req: HasChatId) -> TelegramIdentity:
    return TelegramIdentity(chat_id=req.chat_id)


tg_auth_mw = middleware(
    auth_runner,
    AuthUser,
    _tg_auth_op,
    AuthErrorResponse.from_domain,
)


def _stateful_tg_auth_op(state: HasChatId) -> TelegramIdentity:
    return TelegramIdentity(chat_id=state.chat_id)


stateful_tg_auth_mw = stateful_middleware(
    auth_runner,
    AuthUser,
    _stateful_tg_auth_op,
    AuthErrorResponse.from_domain,
)


# ── CLI Middleware (trusted transport) ───────────────────────────────────


class HasLogin(Protocol):
    """Protocol for extracting login from CLI session."""

    login: str


def _cli_auth_op(req: HasLogin) -> TrustedIdentity:
    return TrustedIdentity(login=req.login)


cli_auth_mw = middleware(
    auth_runner,
    AuthUser,
    _cli_auth_op,
    AuthErrorResponse.from_domain,
)


# ── Response types (shared across transports) ─────────────────────────────


@dataclass
class RegisterResponse:
    token: str | None = None
    error: str | None = None

    @classmethod
    def from_domain(cls, dom: Result[str, str]) -> RegisterResponse:
        match dom:
            case Ok(token):
                return cls(token=token)
            case Error(e):
                return cls(error=e)

    def __str__(self) -> str:
        if self.error:
            return f"Registration failed: {self.error}"
        return f"Registered! Token: {self.token}"


@dataclass
class LoginResponse:
    token: str | None = None
    error: str | None = None

    @classmethod
    def from_domain(cls, dom: Result[str, str]) -> LoginResponse:
        match dom:
            case Ok(token):
                return cls(token=token)
            case Error(e):
                return cls(error=e)

    def __str__(self) -> str:
        if self.error:
            return f"Login failed: {self.error}"
        return f"Logged in! Token: {self.token}"


@dataclass
class LinkResponse:
    success: bool = False
    error: str | None = None

    @classmethod
    def from_domain(cls, dom: Result[str, str]) -> LinkResponse:
        match dom:
            case Ok(_):
                return cls(success=True)
            case Error(e):
                return cls(error=e)

    def __str__(self) -> str:
        if self.error:
            return f"Link failed: {self.error}"
        return "Linked!"


@dataclass
class BalanceResponse:
    balance: int | None = None
    error: str | None = None

    @classmethod
    def from_domain(cls, dom: Result[int, str]) -> BalanceResponse:
        match dom:
            case Ok(balance):
                return cls(balance=balance)
            case Error(e):
                return cls(error=e)

    def __str__(self) -> str:
        if self.error:
            return f"Error: {self.error}"
        return f"Balance: {self.balance}"


@dataclass
class BetResponse:
    won: bool | None = None
    number: int | None = None
    payout: int | None = None
    new_balance: int | None = None
    error: str | None = None

    @classmethod
    def from_domain(cls, dom: Result[BetResult, str]) -> BetResponse:
        match dom:
            case Ok(bet_result):
                return cls(
                    won=bet_result.won,
                    number=bet_result.number,
                    payout=bet_result.payout,
                    new_balance=bet_result.new_balance,
                )
            case Error(e):
                return cls(error=e)

    def __str__(self) -> str:
        if self.error:
            return f"Error: {self.error}"
        won = "Won" if self.won else "Lost"
        return f"{won}! Number: {self.number}, Payout: {self.payout}, Balance: {self.new_balance}"

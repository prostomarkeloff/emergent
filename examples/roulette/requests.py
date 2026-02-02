"""Request types — multi-dialect annotations for all compilers.

Each request type has:
- cli.* annotations for argparse
- openapi.* annotations for FastAPI/OpenAPI

Universal annotations (MinLen, etc.) work everywhere.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from emergent.wire.axis.schema.dialects import cli, openapi, tg, compose
from telegrinder.node import ChatId

from roulette.auth.ops import Register, Login, Authenticate, TelegramIdentity, LinkTelegram
from roulette.game.ops import GetBalance, PlaceBet


# ─── Auth Requests ────────────────────────────────────────────────────────────


@dataclass
class RegisterRequest:
    """Register new user."""
    login: Annotated[str,
        cli.Help("Username"),
        cli.Positional(),
        openapi.Description("Username for registration"),
        tg.CommandArg(),
    ]
    password: Annotated[str,
        cli.Help("Password"),
        cli.Positional(),
        openapi.Description("Account password"),
        tg.CommandArg(),
    ]

    def to_domain(self) -> Register:
        return Register(login=self.login, password=self.password)


@dataclass
class LoginRequest:
    """Login to existing account."""
    login: Annotated[str, cli.Help("Username"), cli.Positional(), tg.CommandArg()]
    password: Annotated[str, cli.Help("Password"), cli.Positional(), tg.CommandArg()]

    def to_domain(self) -> Login:
        return Login(login=self.login, password=self.password)


@dataclass
class AuthenticatedRequest:
    """Request with token auth header."""
    token: Annotated[str, openapi.Description("Auth token from login")]

    def to_auth(self) -> Authenticate:
        return Authenticate(token=self.token)


@dataclass
class LinkTelegramRequest:
    """Link Telegram chat to account."""
    chat_id: int
    login: Annotated[str, cli.Help("Username"), cli.Positional()]
    password: Annotated[str, cli.Help("Password"), cli.Positional()]

    def to_domain(self) -> LinkTelegram:
        return LinkTelegram(
            chat_id=self.chat_id,
            login=self.login,
            password=self.password,
        )


# ─── Game Requests ────────────────────────────────────────────────────────────


@dataclass
class BalanceRequest:
    """Get current balance (with auth token)."""
    token: Annotated[str, openapi.Description("Auth token from login")]

    def to_domain(self) -> GetBalance:
        return GetBalance()

    def to_auth(self) -> Authenticate:
        return Authenticate(token=self.token)


@dataclass
class TelegramBalanceRequest:
    """Get balance via Telegram (auth via chat_id binding)."""
    chat_id: Annotated[int, compose.Node(ChatId)]

    def to_domain(self) -> GetBalance:
        return GetBalance()

    def to_auth(self) -> TelegramIdentity:
        return TelegramIdentity(chat_id=self.chat_id)


@dataclass
class BetRequest:
    """Place a bet (with auth token)."""
    token: Annotated[str, openapi.Description("Auth token from login")]
    bet: Annotated[str,
        cli.Help("Bet type: red, black, or 0-36"),
        cli.Positional(),
        openapi.Description("Bet type: 'red', 'black', or number 0-36"),
        tg.CommandArg(),
    ]
    amount: Annotated[int,
        cli.Help("Bet amount"),
        cli.Positional(),
        openapi.Description("Amount to bet"),
        tg.CommandArg(),
    ]

    def to_domain(self) -> PlaceBet:
        return PlaceBet(bet=self.bet, amount=self.amount)

    def to_auth(self) -> Authenticate:
        return Authenticate(token=self.token)


@dataclass
class TelegramBetRequest:
    """Place bet via Telegram (auth via chat_id binding)."""
    chat_id: Annotated[int, compose.Node(ChatId)]
    bet: Annotated[str, tg.CommandArg()]
    amount: Annotated[int, tg.CommandArg()]

    def to_domain(self) -> PlaceBet:
        return PlaceBet(bet=self.bet, amount=self.amount)

    def to_auth(self) -> TelegramIdentity:
        return TelegramIdentity(chat_id=self.chat_id)


__all__ = (
    "RegisterRequest",
    "LoginRequest",
    "AuthenticatedRequest",
    "LinkTelegramRequest",
    "BalanceRequest",
    "TelegramBalanceRequest",
    "BetRequest",
    "TelegramBetRequest",
)

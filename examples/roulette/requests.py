"""Request types — multi-dialect annotations for all compilers.

Each request type has:
- cli.* annotations for argparse
- openapi.* annotations for FastAPI/OpenAPI

Universal annotations (MinLen, etc.) work everywhere.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from emergent.wire.axis.schema.dialects import cli, openapi

from roulette.auth.ops import Register, Login, Authenticate, LinkTelegram
from roulette.game.ops import GetBalance, PlaceBet


# ─── Auth Requests ────────────────────────────────────────────────────────────


@dataclass
class RegisterRequest:
    """Register new user."""
    login: Annotated[str,
        cli.Help("Username"),
        cli.Positional(),
        openapi.Description("Username for registration"),
    ]
    password: Annotated[str,
        cli.Help("Password"),
        cli.Positional(),
        openapi.Description("Account password"),
    ]

    def to_domain(self) -> Register:
        return Register(login=self.login, password=self.password)


@dataclass
class LoginRequest:
    """Login to existing account."""
    login: Annotated[str, cli.Help("Username"), cli.Positional()]
    password: Annotated[str, cli.Help("Password"), cli.Positional()]

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
class BetRequest:
    """Place a bet (with auth token)."""
    token: Annotated[str, openapi.Description("Auth token from login")]
    bet: Annotated[str,
        cli.Help("Bet type: red, black, or 0-36"),
        cli.Positional(),
        openapi.Description("Bet type: 'red', 'black', or number 0-36"),
    ]
    amount: Annotated[int,
        cli.Help("Bet amount"),
        cli.Positional(),
        openapi.Description("Amount to bet"),
    ]

    def to_domain(self) -> PlaceBet:
        return PlaceBet(bet=self.bet, amount=self.amount)

    def to_auth(self) -> Authenticate:
        return Authenticate(token=self.token)


__all__ = (
    "RegisterRequest",
    "LoginRequest",
    "AuthenticatedRequest",
    "LinkTelegramRequest",
    "BalanceRequest",
    "BetRequest",
)

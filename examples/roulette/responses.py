"""Response types — generic helpers to reduce boilerplate.

Instead of writing separate RegisterResponse, LoginResponse, etc.
with the same Ok→data, Error→error pattern, use generic helpers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar, TYPE_CHECKING

from kungfu import Result, Ok, Error

if TYPE_CHECKING:
    from roulette.game.domain import BetResult
    from roulette.auth.ops import AuthUser

T = TypeVar("T")


@dataclass
class SuccessResponse(Generic[T]):
    """Generic success response."""
    data: T | None = None
    error: str | None = None

    @classmethod
    def from_result(cls, result: Result[T, str]) -> SuccessResponse[T]:
        match result:
            case Ok(data):
                return cls(data=data)
            case Error(e):
                return cls(error=e)


@dataclass
class TokenResponse:
    """Token response for auth operations."""
    token: str | None = None
    error: str | None = None

    @classmethod
    def from_domain(cls, dom: Result[str, str]) -> TokenResponse:
        match dom:
            case Ok(token):
                return cls(token=token)
            case Error(e):
                return cls(error=e)

    def __str__(self) -> str:
        if self.error:
            return f"Error: {self.error}"
        return f"Token: {self.token}"


@dataclass
class BalanceResponse:
    """Balance response."""
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
    """Bet result response."""
    won: bool | None = None
    number: int | None = None
    payout: int | None = None
    new_balance: int | None = None
    error: str | None = None

    @classmethod
    def from_domain(cls, dom: Result[BetResult, str]) -> BetResponse:
        match dom:
            case Ok(r):
                return cls(
                    won=r.won,
                    number=r.number,
                    payout=r.payout,
                    new_balance=r.new_balance,
                )
            case Error(e):
                return cls(error=e)

    def __str__(self) -> str:
        if self.error:
            return f"Error: {self.error}"
        won = "Won" if self.won else "Lost"
        return f"{won}! Number: {self.number}, Payout: {self.payout}, Balance: {self.new_balance}"


@dataclass
class AuthErrorResponse:
    """Auth error for middleware rejections."""
    error: str

    @classmethod
    def from_domain(cls, dom: Result[AuthUser, str]) -> AuthErrorResponse:
        match dom:
            case Error(e):
                return cls(error=e)
            case Ok(_):
                return cls(error="auth failed")

    def __str__(self) -> str:
        return f"Auth error: {self.error}"


__all__ = (
    "SuccessResponse",
    "TokenResponse",
    "BalanceResponse",
    "BetResponse",
    "AuthErrorResponse",
)

"""Response types — multi-target UI annotations.

UI annotations per target:
- tg.* — Telegram formatting

Text/i18n is in the data, not annotations.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar, TYPE_CHECKING, Annotated

from kungfu import Result, Ok, Error
from emergent.wire.axis.schema.dialects import tg

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
    token: Annotated[str | None, tg.Code()] = None
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
    """Balance response with UI annotations."""
    balance: Annotated[int | None, tg.Bold()] = None
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
    """Bet result response — text in data, formatting in annotations."""
    # Text already includes emoji/i18n — done in from_domain
    result: Annotated[str | None, tg.Bold()] = None
    number: Annotated[int | None, tg.Code()] = None
    payout: Annotated[int | None, tg.Bold()] = None
    new_balance: Annotated[int | None, tg.Bold()] = None
    error: str | None = None

    @classmethod
    def from_domain(cls, dom: Result[BetResult, str]) -> BetResponse:
        match dom:
            case Ok(r):
                # i18n/text done HERE, not in annotations
                result = "✅ Won!" if r.won else "❌ Lost"
                return cls(
                    result=result,
                    number=r.number,
                    payout=r.payout,
                    new_balance=r.new_balance,
                )
            case Error(e):
                return cls(error=e)

    def __str__(self) -> str:
        if self.error:
            return f"Error: {self.error}"
        return f"{self.result} Number: {self.number}, Payout: {self.payout}, Balance: {self.new_balance}"


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

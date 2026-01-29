"""Auth ops — generated via: emergent-meta new op."""

from dataclasses import dataclass

from emergent import ops as O


class AuthUser(str):
    """Authenticated user identity (login string)."""


@dataclass(frozen=True, slots=True)
class Register(O.Returning[str, str]):
    login: str
    password: str


@dataclass(frozen=True, slots=True)
class Login(O.Returning[str, str]):
    login: str
    password: str


@dataclass(frozen=True, slots=True)
class Authenticate(O.Returning[AuthUser, str]):
    """HTTP token-based auth."""
    token: str


@dataclass(frozen=True, slots=True)
class TelegramIdentity(O.Returning[AuthUser, str]):
    """Telegram chat_id → AuthUser via binding store."""
    chat_id: int


@dataclass(frozen=True, slots=True)
class TrustedIdentity(O.Returning[AuthUser, str]):
    """CLI trusted session — login from local file."""
    login: str


@dataclass(frozen=True, slots=True)
class LinkTelegram(O.Returning[str, str]):
    """Bind telegram chat_id to login (after credential check)."""
    chat_id: int
    login: str
    password: str

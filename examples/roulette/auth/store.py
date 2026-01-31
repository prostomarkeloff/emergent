"""Auth store — user/session storage via relational query axis."""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass, field
from datetime import datetime
from typing import Annotated

from emergent.wire.axis.query import relational_store, MemoryRelationalProvider
from emergent.wire.axis.schema import Identity


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


@dataclass
class TelegramBinding:
    chat_id: Annotated[int, Identity]
    login: str
    created_at: datetime = field(default_factory=datetime.now)


class AuthStore:
    """Auth storage using relational query axis."""

    def __init__(self) -> None:
        self._users = relational_store(User, MemoryRelationalProvider[User]())
        self._sessions = relational_store(Session, MemoryRelationalProvider[Session]())
        self._telegram = relational_store(TelegramBinding, MemoryRelationalProvider[TelegramBinding]())

    # ─── Users ───────────────────────────────────────────────────────────

    async def user_exists(self, login: str) -> bool:
        return await self._users.filter(lambda u: u.login == login).exists()

    async def create_user(self, login: str, password: str) -> User:
        user = User(login=login, password_hash=self._hash(password))
        return await self._users.insert(user)

    async def check_password(self, login: str, password: str) -> bool:
        user = await self._users.filter(lambda u: u.login == login).first()
        if user is None:
            return False
        return user.password_hash == self._hash(password)

    # ─── Sessions ────────────────────────────────────────────────────────

    async def create_session(self, login: str) -> str:
        token = secrets.token_hex(16)
        await self._sessions.insert(Session(token=token, login=login))
        return token

    async def get_user_by_token(self, token: str) -> str | None:
        session = await self._sessions.filter(lambda s: s.token == token).first()
        return session.login if session else None

    # ─── Telegram ────────────────────────────────────────────────────────

    async def bind_telegram(self, chat_id: int, login: str) -> None:
        old = await self._telegram.filter(lambda t: t.chat_id == chat_id).first()
        if old:
            await self._telegram.delete(old)
        await self._telegram.insert(TelegramBinding(chat_id=chat_id, login=login))

    async def get_login_by_chat_id(self, chat_id: int) -> str | None:
        binding = await self._telegram.filter(lambda t: t.chat_id == chat_id).first()
        return binding.login if binding else None

    @staticmethod
    def _hash(password: str) -> str:
        return hashlib.sha256(password.encode()).hexdigest()

"""Auth store — in-memory user/session storage."""

import hashlib
import secrets


class AuthStore:
    """In-memory auth storage: users and sessions."""

    def __init__(self) -> None:
        self._users: dict[str, str] = {}  # login → hashed password
        self._sessions: dict[str, str] = {}  # token → login
        self._telegram_bindings: dict[int, str] = {}  # chat_id → login

    def user_exists(self, login: str) -> bool:
        return login in self._users

    def create_user(self, login: str, password: str) -> None:
        self._users[login] = self._hash(password)

    def check_password(self, login: str, password: str) -> bool:
        stored = self._users.get(login)
        if stored is None:
            return False
        return stored == self._hash(password)

    def create_session(self, login: str) -> str:
        token = secrets.token_hex(16)
        self._sessions[token] = login
        return token

    def get_user_by_token(self, token: str) -> str | None:
        return self._sessions.get(token)

    def bind_telegram(self, chat_id: int, login: str) -> None:
        self._telegram_bindings[chat_id] = login

    def get_login_by_chat_id(self, chat_id: int) -> str | None:
        return self._telegram_bindings.get(chat_id)

    @staticmethod
    def _hash(password: str) -> str:
        return hashlib.sha256(password.encode()).hexdigest()

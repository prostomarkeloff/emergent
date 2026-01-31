"""Auth handlers."""

from kungfu import Result, Ok, Error

from roulette.auth.ops import (
    Register,
    Login,
    Authenticate,
    AuthUser,
    TelegramIdentity,
    TrustedIdentity,
    LinkTelegram,
)
from roulette.auth.store import AuthStore
from roulette.game.store import GameStore


async def handle_register(
    op: Register, auth_store: AuthStore, game_store: GameStore
) -> Result[str, str]:
    """Register → create user, init balance, return token."""
    if await auth_store.user_exists(op.login):
        return Error(f"user {op.login!r} already exists")

    await auth_store.create_user(op.login, op.password)
    await game_store.ensure_balance(op.login)
    token = await auth_store.create_session(op.login)
    return Ok(token)


async def handle_login(op: Login, auth_store: AuthStore) -> Result[str, str]:
    """Login → verify credentials, return token."""
    if not await auth_store.check_password(op.login, op.password):
        return Error("invalid credentials")

    token = await auth_store.create_session(op.login)
    return Ok(token)


async def handle_authenticate(
    op: Authenticate, auth_store: AuthStore
) -> Result[AuthUser, str]:
    """Authenticate → resolve token to AuthUser."""
    login = await auth_store.get_user_by_token(op.token)
    if login is None:
        return Error("invalid token")
    return Ok(AuthUser(login))


async def handle_telegram_identity(
    op: TelegramIdentity, auth_store: AuthStore
) -> Result[AuthUser, str]:
    """TelegramIdentity → resolve chat_id to AuthUser."""
    login = await auth_store.get_login_by_chat_id(op.chat_id)
    if login is None:
        return Error("not linked — use /link first")
    return Ok(AuthUser(login))


async def handle_trusted_identity(
    op: TrustedIdentity, auth_store: AuthStore
) -> Result[AuthUser, str]:
    """TrustedIdentity → trust login from CLI session."""
    if not op.login:
        return Error("not logged in — use 'login' command first")
    if not await auth_store.user_exists(op.login):
        return Error("user not found")
    return Ok(AuthUser(op.login))


async def handle_link_telegram(
    op: LinkTelegram, auth_store: AuthStore
) -> Result[str, str]:
    """LinkTelegram → bind chat_id after credential check."""
    if not await auth_store.check_password(op.login, op.password):
        return Error("invalid credentials")
    await auth_store.bind_telegram(op.chat_id, op.login)
    return Ok("linked")

"""Auth runner — generated via: emergent-meta new runner."""

from emergent import ops as O

from roulette.auth.ops import (
    Register,
    Login,
    Authenticate,
    TelegramIdentity,
    TrustedIdentity,
    LinkTelegram,
)
from roulette.auth.handlers import (
    handle_register,
    handle_login,
    handle_authenticate,
    handle_telegram_identity,
    handle_trusted_identity,
    handle_link_telegram,
)
from roulette.auth.store import AuthStore
from roulette.game.store import GameStore
from roulette.stores import auth_store, game_store

auth_runner = (
    O.ops()
    .on(Register, handle_register)
    .on(Login, handle_login)
    .on(Authenticate, handle_authenticate)
    .on(TelegramIdentity, handle_telegram_identity)
    .on(TrustedIdentity, handle_trusted_identity)
    .on(LinkTelegram, handle_link_telegram)
    .compile()
    .inject(AuthStore, auth_store)
    .inject(GameStore, game_store)
)

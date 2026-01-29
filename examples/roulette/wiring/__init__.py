"""Roulette wiring — transport-specific endpoint configurations.

# Telegrinder bot
from roulette.wiring.telegrinder import dispatch
bot = Telegrinder(api, dispatch=dispatch)

# FastAPI
from roulette.wiring.fastapi import app
uvicorn.run(app)
"""

from roulette.wiring.base import (
    auth_runner,
    game_runner,
    # HTTP middleware (token-based)
    auth_mw,
    stateful_auth_mw,
    # Telegram middleware (chat_id-based)
    tg_auth_mw,
    stateful_tg_auth_mw,
    # CLI middleware (trusted session)
    cli_auth_mw,
    # Responses
    RegisterResponse,
    LoginResponse,
    LinkResponse,
    BalanceResponse,
    BetResponse,
)

__all__ = [
    "auth_runner",
    "game_runner",
    "auth_mw",
    "stateful_auth_mw",
    "tg_auth_mw",
    "stateful_tg_auth_mw",
    "cli_auth_mw",
    "RegisterResponse",
    "LoginResponse",
    "LinkResponse",
    "BalanceResponse",
    "BetResponse",
]

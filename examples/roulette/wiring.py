"""Unified wiring — one Application, multiple compilers.

Run:
    # FastAPI
    uvicorn roulette.wiring:fastapi_app --reload

    # CLI
    python -m roulette register alice secret
    python -m roulette login alice secret

    # Telegram (set BOT_TOKEN env var)
    python -m roulette --bot
"""

from __future__ import annotations

from emergent.wire import endpoint, Application, inject
from emergent.wire.axis.surface.codecs.rrc import rrc
from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger
from emergent.wire.axis.surface.triggers.cli import CLITrigger
from emergent.wire.compiler import fastapi_compile, cli_compile, cli_run

from roulette.auth.ops import Authenticate, AuthUser
from roulette.auth.runner import auth_runner
from roulette.game.runner import game_runner

from roulette.requests import (
    RegisterRequest,
    LoginRequest,
    BetRequest,
    BalanceRequest,
)
from roulette.responses import (
    TokenResponse,
    BalanceResponse,
    BetResponse,
    AuthErrorResponse,
)


# ─── Middleware ───────────────────────────────────────────────────────────────


from typing import Protocol


class HasAuth(Protocol):
    """Request that can provide auth token."""
    def to_auth(self) -> Authenticate: ...


# HTTP auth middleware: inject AuthUser from request's token
http_auth = (
    inject(AuthUser)
        .using(auth_runner)
        .from_request(HasAuth, lambda req: req.to_auth())
        .on_reject(AuthErrorResponse.from_domain)
        .build()
)


# ─── Application ──────────────────────────────────────────────────────────────


app = Application().mount(
    # Register — public
    endpoint(auth_runner)
        .expose(
            HTTPRouteTrigger("POST", "/register"),
            rrc(RegisterRequest, TokenResponse).build(),
        )
        .expose(
            CLITrigger("register", "Register new user"),
            rrc(RegisterRequest, TokenResponse).build(),
        ),

    # Login — public
    endpoint(auth_runner)
        .expose(
            HTTPRouteTrigger("POST", "/login"),
            rrc(LoginRequest, TokenResponse).build(),
        )
        .expose(
            CLITrigger("login", "Login to account"),
            rrc(LoginRequest, TokenResponse).build(),
        ),

    # Balance — requires auth
    endpoint(game_runner)
        .expose(
            HTTPRouteTrigger("GET", "/balance"),
            rrc(BalanceRequest, BalanceResponse).use(http_auth).build(),
        ),

    # Bet — requires auth
    endpoint(game_runner)
        .expose(
            HTTPRouteTrigger("POST", "/bet"),
            rrc(BetRequest, BetResponse).use(http_auth).build(),
        )
        .expose(
            CLITrigger("bet", "Place a bet"),
            rrc(BetRequest, BetResponse).build(),  # CLI uses local session
        ),
)


# ─── Compilers ────────────────────────────────────────────────────────────────


fastapi_app = fastapi_compile(app)
cli_parser = cli_compile(app, prog="roulette")


# ─── Entry Point ──────────────────────────────────────────────────────────────


if __name__ == "__main__":
    cli_run(cli_parser)

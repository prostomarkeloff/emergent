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

from dataclasses import dataclass
from typing import Protocol

from nodnod import Scope

from emergent.wire.axis.surface import endpoint, Application, empty_runner
from emergent.wire.axis.surface.capabilities._base import ScopeEnricher
from emergent.wire.axis.surface.codecs.rrc import rrc
from emergent.wire.axis.surface.codecs import immediate_factory
from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger
from emergent.wire.axis.surface.triggers.cli import CLITrigger
from emergent.wire.axis.surface.triggers.telegrinder import TelegrindTrigger
from emergent.wire.axis.surface.capabilities import SurfaceCapability, EnricherNext
from emergent.wire.compile.targets import fastapi, cli
from emergent.wire.compile.targets.cli import cli_run

from kungfu import Result, Ok, Error

from telegrinder.bot.rules import Command

from roulette.auth.ops import Authenticate, TelegramIdentity, AuthUser
from roulette.auth.runner import auth_runner
from roulette.game.runner import game_runner
from roulette.bot.runner import bot_runner, StartBot, BotStarted
from roulette.help import HelpResponse

from roulette.requests import (
    RegisterRequest,
    LoginRequest,
    BetRequest,
    BalanceRequest,
    TelegramBalanceRequest,
    TelegramBetRequest,
)
from roulette.responses import (
    TokenResponse,
    BalanceResponse,
    BetResponse,
    AuthErrorResponse,
)


# ─── Auth Protocol ───────────────────────────────────────────────────────────


class HasAuth(Protocol):
    """Request that can provide auth op."""
    def to_auth(self) -> Authenticate | TelegramIdentity: ...


# ─── Auth Enricher ───────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Auth(SurfaceCapability, ScopeEnricher):
    """Auth enricher — extracts auth op from request via HasAuth protocol.

    Usage:
        endpoint(runner).expose(
            trigger,
            rrc(BalanceRequest, BalanceResponse),
            Auth(BalanceRequest),
        )
    """
    request_cls: type[HasAuth]

    async def enrich[R](self, call: EnricherNext[R], scope: Scope) -> R | AuthErrorResponse:
        # Get request from scope
        req_value = scope.get(self.request_cls)
        if req_value is None:
            return AuthErrorResponse(error="request not in scope")

        # Extract auth op via protocol
        req: HasAuth = req_value.value
        auth_op: Authenticate | TelegramIdentity = req.to_auth()

        # Run auth
        result: Result[AuthUser, str] = await auth_runner.run(auth_op)

        match result:
            case Ok(user):
                scope.inject(AuthUser, user)
                return await call(scope)
            case Error(e):
                return AuthErrorResponse(error=e)


# ─── Application ─────────────────────────────────────────────────────────────


def _build_endpoints():
    """Build endpoints list."""
    endpoints = [
        # Register — public
        endpoint(auth_runner)
            .expose(
                HTTPRouteTrigger("POST", "/register"),
                rrc(RegisterRequest, TokenResponse),
            )
            .expose(
                CLITrigger("register", "Register new user"),
                rrc(RegisterRequest, TokenResponse),
            ),

        # Login — public
        endpoint(auth_runner)
            .expose(
                HTTPRouteTrigger("POST", "/login"),
                rrc(LoginRequest, TokenResponse),
            )
            .expose(
                CLITrigger("login", "Login to account"),
                rrc(LoginRequest, TokenResponse),
            ),

        # Balance — requires auth
        endpoint(game_runner)
            .expose(
                HTTPRouteTrigger("GET", "/balance"),
                rrc(BalanceRequest, BalanceResponse),
                Auth(BalanceRequest),
            ),

        # Bet — requires auth
        endpoint(game_runner)
            .expose(
                HTTPRouteTrigger("POST", "/bet"),
                rrc(BetRequest, BetResponse),
                Auth(BetRequest),
            )
            .expose(
                CLITrigger("bet", "Place a bet"),
                rrc(BetRequest, BetResponse),
            ),
    ]

    # Telegram endpoints
    endpoints.extend([
        endpoint(auth_runner)
            .expose(
                TelegrindTrigger(Command("register")),
                rrc(RegisterRequest, TokenResponse),
            ),
        endpoint(auth_runner)
            .expose(
                TelegrindTrigger(Command("login")),
                rrc(LoginRequest, TokenResponse),
            ),
        endpoint(game_runner)
            .expose(
                TelegrindTrigger(Command("balance")),
                rrc(TelegramBalanceRequest, BalanceResponse),
                Auth(TelegramBalanceRequest),
            ),
        endpoint(game_runner)
            .expose(
                TelegrindTrigger(Command("bet")),
                rrc(TelegramBetRequest, BetResponse),
                Auth(TelegramBetRequest),
            ),
    ])

    # Bot CLI command
    endpoints.append(
        endpoint(bot_runner)
            .expose(
                CLITrigger("bot", "Start Telegram bot"),
                rrc(StartBot, BotStarted),
            )
    )

    return endpoints


# Build app without help first
_base_app = Application().mount(*_build_endpoints())


# ─── Help Generation ─────────────────────────────────────────────────────────


from emergent.wire.compile.targets.telegrinder import generate_help_from_command_rules

# Descriptions — callable for i18n support
_descriptions: dict[type, str] = {
    RegisterRequest: "Register new account",
    LoginRequest: "Login to your account",
    TelegramBalanceRequest: "Check your balance",
    TelegramBetRequest: "Place a bet",
}

_help_text = generate_help_from_command_rules(
    _base_app,
    get_description=lambda cls: _descriptions.get(cls, ""),
    order=[RegisterRequest, LoginRequest, TelegramBalanceRequest, TelegramBetRequest],
    template="/{name} {args} — {description}",
    header="Roulette Bot\n\nCommands:",
    footer="\nGood luck!",
)

# Add help endpoint with generated text
app = _base_app.mount(
    endpoint(empty_runner())
        .expose(
            TelegrindTrigger(Command("help")),
            immediate_factory(lambda: HelpResponse(text=_help_text)),
        )
)


# ─── Compilers ───────────────────────────────────────────────────────────────


fastapi_app = fastapi.compile(app)
cli_parser = cli.compile(app, prog="roulette")

from emergent.wire.compile.targets import telegrinder as tg_compile

telegram_dp = tg_compile.compile(app)


# ─── Entry Point ─────────────────────────────────────────────────────────────


if __name__ == "__main__":
    cli_run(cli_parser)

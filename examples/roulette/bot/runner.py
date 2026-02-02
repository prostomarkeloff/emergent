"""Bot runner — starts Telegram bot."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Annotated

from kungfu import Result, Ok, Error
from telegrinder import API, Telegrinder, Token

from emergent import ops as O
from emergent.wire.axis.schema.dialects import cli


# ─── Domain ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class StartBotOp(O.Returning[str, str]):
    """Domain operation: start bot."""
    token: str


# ─── Request/Response ────────────────────────────────────────────────────────


@dataclass
class StartBot:
    """Start bot CLI request."""
    token: Annotated[str | None, cli.Help("Bot token (uses BOT_TOKEN env if not set)")] = None

    def to_domain(self) -> StartBotOp:
        token = self.token or os.environ.get("BOT_TOKEN")
        if not token:
            raise ValueError("BOT_TOKEN environment variable not set")
        return StartBotOp(token=token)


@dataclass
class BotStarted:
    """Bot started response."""
    message: str | None = None
    error: str | None = None

    @classmethod
    def from_domain(cls, dom: Result[str, str]) -> BotStarted:
        match dom:
            case Ok(msg):
                return cls(message=msg)
            case Error(e):
                return cls(error=e)

    def __str__(self) -> str:
        if self.error:
            return f"Error: {self.error}"
        return self.message or "Bot stopped"


# ─── Handler ─────────────────────────────────────────────────────────────────


async def handle_start_bot(op: StartBotOp) -> Result[str, str]:
    """Start the Telegram bot."""
    from roulette.wiring import telegram_dp

    api = API(Token(op.token))
    bot = Telegrinder(api, dispatch=telegram_dp)

    print("Starting bot...")
    async for updates in bot.polling.listen():
        for update in updates:
            if update.message:
                msg = update.message.unwrap()
                text = msg.text.unwrap() if msg.text else "<no text>"
                user = msg.from_.unwrap().first_name if msg.from_ else "unknown"
                print(f"[{user}] {text}")
            await bot.dispatch.feed(api, update)

    return Ok("Bot stopped")


# ─── Runner ──────────────────────────────────────────────────────────────────


bot_runner = (
    O.ops()
    .on(StartBotOp, handle_start_bot)
    .compile()
)

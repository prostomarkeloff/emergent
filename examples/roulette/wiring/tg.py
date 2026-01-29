"""Telegrinder wiring — Telegram bot for roulette.

Run with:
    export BOT_TOKEN=your_token
    python -m roulette.wiring.tg
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Self

from kungfu import Option, Some, Nothing
from nodnod import DataNode, NodeError
from nodnod.interface.scalar import scalar_node
from telegrinder.bot.rules import Command
from telegrinder.node import Text, ChatId
from telegrinder.bot.cute_types import MessageCute
from telegrinder.types.objects import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
)

from emergent.wire import endpoint, application
from emergent.wire.codecs.rrc import RequestResponseCodec
from emergent.wire.codecs.stateful import stateful, Done
from emergent.wire.triggers.telegrinder import TelegrindTrigger
from emergent.wire.contrib import telegrinder as wire_tg

from roulette.auth.ops import Register, Login, LinkTelegram
from roulette.game.ops import PlaceBet
from roulette.wiring import (
    auth_runner,
    game_runner,
    stateful_tg_auth_mw,
    RegisterResponse,
    LoginResponse,
    LinkResponse,
    BetResponse,
)


# ═══════════════════════════════════════════════════════════════════════════
# Request DataNodes — parse from Telegram context
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class RegisterRequest(DataNode):
    login: str
    password: str

    @classmethod
    def __compose__(cls, text: Text) -> RegisterRequest:
        parts = str(text).split()
        if len(parts) < 3:
            raise NodeError("Usage: /register <login> <password>")
        return cls(login=parts[1], password=parts[2])

    def to_domain(self) -> Register:
        return Register(login=self.login, password=self.password)


@dataclass
class LoginRequest(DataNode):
    login: str
    password: str

    @classmethod
    def __compose__(cls, text: Text) -> LoginRequest:
        parts = str(text).split()
        if len(parts) < 3:
            raise NodeError("Usage: /login <login> <password>")
        return cls(login=parts[1], password=parts[2])

    def to_domain(self) -> Login:
        return Login(login=self.login, password=self.password)


@dataclass
class LinkRequest(DataNode):
    """Link telegram chat_id to existing account."""

    chat_id: int
    login: str
    password: str

    @classmethod
    def __compose__(cls, text: Text, chat_id: ChatId) -> LinkRequest:
        parts = str(text).split()
        if len(parts) < 3:
            raise NodeError("Usage: /link <login> <password>")
        return cls(chat_id=int(chat_id), login=parts[1], password=parts[2])

    def to_domain(self) -> LinkTelegram:
        return LinkTelegram(
            chat_id=self.chat_id, login=self.login, password=self.password
        )


# ═══════════════════════════════════════════════════════════════════════════
# Betting Flow — Single-class FSM with __transition__ + to_domain
# ═══════════════════════════════════════════════════════════════════════════


@scalar_node
class BetType:
    """Parse bet type from text — node-like."""

    @classmethod
    def __compose__(cls, text: Text) -> str:
        t = str(text).lower()
        if "red" in t:
            return "red"
        if "black" in t:
            return "black"
        raise NodeError("Pick red or black")


@scalar_node
class BetAmount:
    """Parse positive integer amount — node-like."""

    @classmethod
    def __compose__(cls, text: Text) -> int:
        try:
            amount = int(str(text))
            if amount <= 0:
                raise ValueError()
            return amount
        except ValueError:
            raise NodeError("Enter a positive number")


@dataclass
class BetFlow:
    """Single-class FSM — collects bet type and amount.

    Auth is handled by tg_auth_mw via chat_id binding (no token needed).
    User must /link first to bind their telegram to an account.
    """

    chat_id: int = 0  # Set from ChatId node on first transition
    bet_type: Option[str] = field(default_factory=Nothing)
    amount: Option[int] = field(default_factory=Nothing)
    started: bool = False

    async def __transition__(
        self,
        chat_id: ChatId,
        bet_type: Option[BetType],
        amount: Option[BetAmount],
        msg: MessageCute,
    ) -> Self | Done:
        """State transitions + UI side effects. No business logic here."""

        # Step 1: Start flow — show color picker
        if not self.started:
            await msg.answer(
                "🎰 Choose color:",
                reply_markup=ReplyKeyboardMarkup(
                    keyboard=[
                        [
                            KeyboardButton(text="🔴 Red"),
                            KeyboardButton(text="⚫ Black"),
                        ]
                    ],
                    resize_keyboard=True,
                    one_time_keyboard=True,
                ),
            )
            return replace(self, chat_id=int(chat_id), started=True)

        # Step 2: Collect bet type
        match (self.bet_type, bet_type):
            case (Nothing(), Some(bt)):
                await msg.answer(
                    f"Color: {bt}\nEnter amount:",
                    reply_markup=ReplyKeyboardRemove(remove_keyboard=True),
                )
                return replace(self, bet_type=Some(bt))
            case _:
                pass

        # Step 3: Collect amount → Done
        match (self.bet_type, amount):
            case (Some(_), Some(amt)):
                self.amount = Some(amt)
                return Done()  # Triggers middleware + to_domain() + runner
            case _:
                pass

        return self

    def to_domain(self) -> PlaceBet:
        """Called when Done — constructs Op from accumulated state."""
        return PlaceBet(
            bet=self.bet_type.unwrap(),
            amount=self.amount.unwrap(),
        )


# ═══════════════════════════════════════════════════════════════════════════
# Wire & Compile
# ═══════════════════════════════════════════════════════════════════════════


wire_app = application().mount(
    endpoint(auth_runner).expose(
        TelegrindTrigger(Command("register"), view="message"),
        RequestResponseCodec(RegisterRequest, RegisterResponse),
    ),
    endpoint(auth_runner).expose(
        TelegrindTrigger(Command("login"), view="message"),
        RequestResponseCodec(LoginRequest, LoginResponse),
    ),
    endpoint(auth_runner).expose(
        TelegrindTrigger(Command("link"), view="message"),
        RequestResponseCodec(LinkRequest, LinkResponse),
    ),
    endpoint(game_runner).expose(
        TelegrindTrigger(Command("bet"), view="message"),
        stateful(BetFlow, BetResponse).key(ChatId).use(stateful_tg_auth_mw).build(),
    ),
)

dispatch = wire_tg.from_application(wire_app)


if __name__ == "__main__":
    import os
    from logging import basicConfig

    basicConfig(level="DEBUG")

    from telegrinder import API, Telegrinder, Token

    bot_token = os.environ.get("BOT_TOKEN")
    if not bot_token:
        print("Set BOT_TOKEN environment variable")
        raise SystemExit(1)

    api = API(token=Token(bot_token))
    bot = Telegrinder(api, dispatch=dispatch)

    print("Roulette Bot (Trusted Transport)")
    print("  /register <login> <password>  — create account")
    print("  /link <login> <password>      — link telegram to account")
    print("  /bet                          — place bet (after /link)")
    bot.run_forever()

"""casino_bot — Casino Royale: games, spies, and noir flirting.

Full showcase of derivelib tg/ patterns with swappable intelligence.

    /start      — welcome & main menu              (methods + tg_command)
    /wallet     — check chips balance               (methods + tg_command)
    /roulette   — spin the wheel                   (tg_dashboard: bet tabs + color actions)
    /coinflip   — heads or tails                   (tg_dashboard: bet tabs + side actions)
    /slots      — pull the lever                   (methods, instant)
    /missions   — spy mission board                (tg_browse: query + action + tabs)
    /cipher     — crack the code                   (tg_flow: TextInput → result)
    /lounge     — noir conversation                (tg_flow: Inline(@options) → FlowWidget)
    /settings   — player settings                   (tg_settings: field editing)
    /help       — command reference                (methods + tg_command)

Architecture: Intelligence protocol — swappable brain.
    All state lives in Casino dataclass, injected via nodnod.
    No globals. Intelligence is a field on Casino.

    # Default (deterministic)
    casino = Casino()

    # With LLM
    casino = Casino(intel=LLMIntelligence(my_openai_call))

    BOT_TOKEN=123:ABC uv run python derivelib/examples/casino_bot.py
"""

from __future__ import annotations

import hashlib
import random
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Annotated, ClassVar, Protocol, runtime_checkable

from kungfu import Ok, Result, Some
from nodnod import scalar_node  # type: ignore[import-untyped]
from telegrinder.bot.cute_types.message import MessageCute
from telegrinder.bot.rules.command import Command
from telegrinder.node import UserId
from telegrinder.tools.keyboard import InlineKeyboard

from emergent.wire.axis.schema import Identity
from emergent.wire.axis.schema.dialects import compose, tg

from derivelib import build_application_from_decorated, derive, endpoint_count
from derivelib._errors import DomainError
from derivelib.patterns import (
    methods,
    tg_command,
    tg_delegate,
    tg_flow,
    Inline,
    ShowMode,
    with_cancel,
    with_back,
    with_show_mode,
    FinishResult,
    tg_browse,
    tg_dashboard,
    tg_settings,
    on_save,
    format_settings,
    TextInput,
    Confirm,
    Counter,
    BrowseSource,
    ListBrowseSource,
    ActionResult,
    query,
    action,
    format_card,
    view_filter,
    WidgetContext,
    Stay,
    Advance,
    Reject,
    NoOp,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Domain Types
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class GameOutcome:
    won: bool
    payout: int
    narrative: str


@dataclass(frozen=True, slots=True)
class MissionOutcome:
    success: bool
    reward: int
    narrative: str


@dataclass(frozen=True, slots=True)
class CipherOutcome:
    solved: bool
    hint: str
    reward: int


@dataclass
class PlayerData:
    chips: int = 1000
    total_won: int = 0
    total_lost: int = 0
    games_played: int = 0
    codename: str = "Rookie"
    missions_done: int = 0
    reputation: int = 0
    flirt_history: list[str] = field(default_factory=lambda: list[str]())


@dataclass(frozen=True, slots=True)
class Mission:
    id: Annotated[int, Identity]
    name: Annotated[str, tg.Bold()]
    difficulty: str
    reward_range: str
    description: str


class Difficulty(Enum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


ROULETTE_REDS = frozenset({1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36})

MISSIONS: tuple[Mission, ...] = (
    Mission(1, "Dead Drop Pickup", "easy", "50 chips", "Retrieve a package from the old café."),
    Mission(2, "Embassy Tail", "easy", "50 chips", "Follow the attaché. Don't be seen."),
    Mission(3, "Safe Cracker", "medium", "200 chips", "Open the vault in the east wing."),
    Mission(4, "Double Cross", "medium", "200 chips", "Turn the informant. Make it convincing."),
    Mission(5, "Train Intercept", "hard", "700 chips", "Board the Orient Express. Find the briefcase."),
    Mission(6, "Rooftop Extraction", "hard", "700 chips", "Helicopter at midnight. Don't miss it."),
    Mission(7, "The Mole", "hard", "700 chips", "Someone in the agency is compromised. Find them."),
    Mission(8, "Market Sweep", "easy", "50 chips", "Sweep the bazaar for listening devices."),
    Mission(9, "Cipher Relay", "medium", "200 chips", "Decode and retransmit within the window."),
)

LOUNGE_CHARACTERS: dict[str, str] = {
    "Vivienne": "A singer with a past. Red dress, cigarette holder, knows everyone's secrets.",
    "Marcel": "The bartender. Impeccable suit, French accent, and a memory like a vault.",
    "Anya": "Eastern European. Claims to be a journalist. Nobody believes her.",
    "Jack": "Ex-detective. Drinks bourbon. Hasn't smiled since '42.",
}

CIPHER_WORDS = ("NIGHTFALL", "SCARLET", "VENOM", "SHADOW", "MERCURY", "PHANTOM", "COBRA", "ECLIPSE")


# ═══════════════════════════════════════════════════════════════════════════════
# Intelligence Protocol — the swappable brain
# ═══════════════════════════════════════════════════════════════════════════════


@runtime_checkable
class Intelligence(Protocol):
    """Swappable brain for all bot decisions.

    Game outcomes use random for fairness. Intelligence controls NARRATIVE only.
    """

    async def roulette_result(self, bet: int, choice: str, winning: int) -> GameOutcome: ...
    async def coinflip_result(self, bet: int, call: str, landed: str) -> GameOutcome: ...
    async def slots_result(self, bet: int) -> tuple[str, str, str, GameOutcome]: ...
    async def spy_mission(self, difficulty: str, codename: str) -> MissionOutcome: ...
    async def cipher_check(self, answer: str, secret: str) -> CipherOutcome: ...
    async def flirt(self, character: str, message: str, history: Sequence[str]) -> str: ...


class HouseIntelligence:
    """Deterministic house logic. Fair odds, canned noir text."""

    _FLIRT: ClassVar[tuple[str, ...]] = (
        "She traced the rim of her glass. 'You remind me of someone I used to trust.'",
        "'Dangerous words for a place like this,' she murmured, smoke curling upward.",
        "He leaned closer. 'In this city, everyone has a price. What's yours?'",
        "'You play a dangerous game,' she said, but her eyes said she liked it.",
        "The piano played something melancholy. 'Buy me a drink and I'll tell you a secret.'",
        "'I've seen men like you come and go. Mostly go.' A half-smile. 'Stay a while.'",
        "He adjusted his cufflinks. 'Trust is a currency I can't afford to spend.'",
        "'The last person who looked at me like that ended up in the harbour.' She winked.",
        "'You've got nerve, walking in here.' She didn't look away. 'I respect nerve.'",
        "'Everyone in this room is lying about something.' She sipped. 'Even me.'",
    )

    _SPY: ClassVar[dict[str, tuple[str, ...]]] = {
        "easy": (
            "Dead drop at the café. Envelope retrieved. Clean exit through the kitchen.",
            "Tailed the courier through the market. Package secured behind the fish stall.",
            "The informant left the microfilm in a newspaper. Routine pickup.",
        ),
        "medium": (
            "Guards changed shift late. Slipped through the east wing. Documents photographed.",
            "The informant was nervous. Extraction took 40 minutes. Intel is gold.",
            "Had to dodge embassy security. Close call at checkpoint 3. Mission complete.",
        ),
        "hard": (
            "Laser grid. Pressure plates. Three locks. But the microfilm is ours.",
            "Double agent situation. Had to improvise. Cover intact. Barely.",
            "Intercepted the transmission from a moving train. Codebreakers will love this.",
        ),
    }

    async def roulette_result(self, bet: int, choice: str, winning: int) -> GameOutcome:
        won, payout = False, 0
        if choice == "green":
            won = winning == 0
            payout = bet * 35 if won else 0
        elif choice == "red":
            won = winning in ROULETTE_REDS
            payout = bet * 2 if won else 0
        elif choice == "black":
            won = winning != 0 and winning not in ROULETTE_REDS
            payout = bet * 2 if won else 0
        elif choice.isdigit():
            won = int(choice) == winning
            payout = bet * 35 if won else 0

        if won:
            narrative = f"The ball lands on {winning}. The table erupts. +{payout} chips."
        else:
            narrative = f"The ball lands on {winning}. The croupier rakes your chips. Silence."
        return GameOutcome(won=won, payout=payout, narrative=narrative)

    async def coinflip_result(self, bet: int, call: str, landed: str) -> GameOutcome:
        won = call == landed
        payout = bet * 2 if won else 0
        if won:
            narrative = f"The coin catches the light — {landed}. You called it. +{payout} chips."
        else:
            narrative = f"The coin spins… {landed}. Not your call. The house collects."
        return GameOutcome(won=won, payout=payout, narrative=narrative)

    async def slots_result(self, bet: int) -> tuple[str, str, str, GameOutcome]:
        symbols = ("🍒", "🍋", "🔔", "💎", "7️⃣", "🃏")
        r1, r2, r3 = random.choice(symbols), random.choice(symbols), random.choice(symbols)
        if r1 == r2 == r3:
            mult = 50 if r1 == "7️⃣" else 20 if r1 == "💎" else 10
            payout = bet * mult
            narrative = {50: "JACKPOT! Triple sevens!", 20: "Triple diamonds!", 10: f"Triple {r1}!"}[mult]
            return r1, r2, r3, GameOutcome(won=True, payout=payout, narrative=narrative)
        if r1 == r2 or r2 == r3:
            return r1, r2, r3, GameOutcome(won=True, payout=bet * 2, narrative="Two of a kind. Small win.")
        return r1, r2, r3, GameOutcome(won=False, payout=0, narrative="No match. The reels shrug.")

    async def spy_mission(self, difficulty: str, codename: str) -> MissionOutcome:
        odds = {"easy": 0.8, "medium": 0.55, "hard": 0.3}
        rewards = {"easy": 50, "medium": 200, "hard": 700}
        success = random.random() < odds.get(difficulty, 0.5)
        reward = rewards.get(difficulty, 50) if success else 0
        narratives = self._SPY.get(difficulty, self._SPY["easy"])
        return MissionOutcome(success=success, reward=reward,
                              narrative=f"Agent {codename}: {random.choice(narratives)}")

    async def cipher_check(self, answer: str, secret: str) -> CipherOutcome:
        if answer.lower().strip() == secret.lower().strip():
            return CipherOutcome(solved=True, hint="", reward=200)
        n = min(len(answer) // 2 + 1, len(secret) - 1)
        hint = secret[:n] + "·" * (len(secret) - n)
        return CipherOutcome(solved=False, hint=f"Close… pattern: {hint}", reward=0)

    async def flirt(self, character: str, message: str, history: Sequence[str]) -> str:
        return random.choice(self._FLIRT)


class LLMIntelligence:
    """Plug any LLM: async (str) -> str.

        casino = Casino(intel=LLMIntelligence(my_openai_call))
    """

    def __init__(self, call: Callable[[str], Awaitable[str]]) -> None:
        self._call = call

    async def roulette_result(self, bet: int, choice: str, winning: int) -> GameOutcome:
        won, payout = False, 0
        if choice == "green":
            won = winning == 0; payout = bet * 35 if won else 0
        elif choice == "red":
            won = winning in ROULETTE_REDS; payout = bet * 2 if won else 0
        elif choice == "black":
            won = winning != 0 and winning not in ROULETTE_REDS; payout = bet * 2 if won else 0
        narrative = await self._call(
            f"Roulette. Bet {bet} on {choice}, landed {winning}. {'Won' if won else 'Lost'}. One noir sentence.")
        return GameOutcome(won=won, payout=payout, narrative=narrative)

    async def coinflip_result(self, bet: int, call: str, landed: str) -> GameOutcome:
        won = call == landed
        payout = bet * 2 if won else 0
        narrative = await self._call(
            f"Coin flip. Called {call}, landed {landed}. {'Won' if won else 'Lost'}. One noir sentence.")
        return GameOutcome(won=won, payout=payout, narrative=narrative)

    async def slots_result(self, bet: int) -> tuple[str, str, str, GameOutcome]:
        house = HouseIntelligence()
        r1, r2, r3, outcome = await house.slots_result(bet)
        narrative = await self._call(
            f"Slots: {r1}{r2}{r3}. {'Won '+str(outcome.payout) if outcome.won else 'Lost'}. One noir sentence.")
        return r1, r2, r3, GameOutcome(won=outcome.won, payout=outcome.payout, narrative=narrative)

    async def spy_mission(self, difficulty: str, codename: str) -> MissionOutcome:
        odds = {"easy": 0.8, "medium": 0.55, "hard": 0.3}
        rewards = {"easy": 50, "medium": 200, "hard": 700}
        success = random.random() < odds.get(difficulty, 0.5)
        reward = rewards.get(difficulty, 50) if success else 0
        narrative = await self._call(
            f"Spy mission. Agent {codename}. {difficulty}. {'Success' if success else 'Failure'}. Two sentences.")
        return MissionOutcome(success=success, reward=reward, narrative=narrative)

    async def cipher_check(self, answer: str, secret: str) -> CipherOutcome:
        if answer.lower().strip() == secret.lower().strip():
            return CipherOutcome(solved=True, hint="", reward=200)
        hint = await self._call(f"Code word is '{secret}'. Guess was '{answer}'. Cryptic one-line hint.")
        return CipherOutcome(solved=False, hint=hint, reward=0)

    async def flirt(self, character: str, message: str, history: Sequence[str]) -> str:
        ctx = "\n".join(history[-6:]) if history else "(first meeting)"
        return await self._call(
            f"You are {character} in a 1940s noir casino.\n{ctx}\n\nPlayer: \"{message}\"\n\n"
            "Reply in character. Flirty, classy, detective-novel. One paragraph.")


# ═══════════════════════════════════════════════════════════════════════════════
# Casino — all mutable state in one place, injected via nodnod
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class Casino:
    """All state lives here. Injected via compose.Node(CasinoNode)."""

    intel: Intelligence = field(default_factory=HouseIntelligence)
    players: dict[int, PlayerData] = field(default_factory=lambda: dict[int, PlayerData]())

    def player(self, uid: int) -> PlayerData:
        if uid not in self.players:
            self.players[uid] = PlayerData()
        return self.players[uid]

    def pay(self, uid: int, amount: int) -> bool:
        p = self.player(uid)
        if p.chips < amount:
            return False
        p.chips -= amount
        return True

    def win(self, uid: int, payout: int) -> None:
        p = self.player(uid)
        p.chips += payout
        p.total_won += payout
        p.games_played += 1

    def lose(self, uid: int, bet: int) -> None:
        p = self.player(uid)
        p.total_lost += bet
        p.games_played += 1

    def win_rate(self, uid: int) -> str:
        p = self.player(uid)
        total = p.total_won + p.total_lost
        if total == 0:
            return "—"
        return f"{p.total_won * 100 // total}%"

    def rank(self, uid: int) -> str:
        rep = self.player(uid).reputation
        if rep >= 1000:
            return "Director"
        if rep >= 600:
            return "Station Chief"
        if rep >= 300:
            return "Senior Operative"
        if rep >= 100:
            return "Field Agent"
        return "Rookie"

    def leaderboard(self, top: int = 10) -> list[tuple[int, PlayerData]]:
        return sorted(self.players.items(), key=lambda kv: kv[1].chips, reverse=True)[:top]


# Instance created here, passed to nodnod. Replace .intel for LLM.
casino = Casino()


@scalar_node
class CasinoNode:
    @classmethod
    def __compose__(cls) -> Casino:
        return casino


@scalar_node
class MissionCatalogNode:
    @classmethod
    def __compose__(cls) -> Sequence[Mission]:
        return MISSIONS


@dataclass
class BetStore:
    """Per-user bet amounts for browse-based games (tab presets + counter)."""

    amounts: dict[tuple[str, int], int] = field(default_factory=lambda: dict[tuple[str, int], int]())
    last_filter: dict[tuple[str, int], str] = field(default_factory=lambda: dict[tuple[str, int], str]())

    def resolve(self, game: str, uid: int, filter_key: str, default: int = 50) -> int:
        """Resolve current bet: tab preset wins on change, otherwise stored amount."""
        key = (game, uid)
        if filter_key and filter_key != self.last_filter.get(key, ""):
            self.amounts[key] = int(filter_key)
        self.last_filter[key] = filter_key
        return self.amounts.get(key, default)

    def adjust(
        self, game: str, uid: int, delta: int, *, min_bet: int = 10, max_bet: int = 1000,
    ) -> int:
        """Adjust stored bet by delta, clamped to [min_bet, max_bet]."""
        key = (game, uid)
        current = self.amounts.get(key, 50)
        new_bet = max(min_bet, min(max_bet, current + delta))
        self.amounts[key] = new_bet
        return new_bet


bet_store = BetStore()


@scalar_node
class BetStoreNode:
    @classmethod
    def __compose__(cls) -> BetStore:
        return bet_store


# ═══════════════════════════════════════════════════════════════════════════════
# Cipher helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _current_cipher() -> str:
    idx = int(time.time() // 600) % len(CIPHER_WORDS)
    return CIPHER_WORDS[idx]


def _cipher_puzzle() -> str:
    word = _current_cipher()
    h = hashlib.md5(word.encode()).hexdigest()[:6]  # noqa: S324
    return f"Intercept #{h.upper()} — {len(word)} letters, starts with '{word[0]}'"


# ═══════════════════════════════════════════════════════════════════════════════
# /roulette — spin the wheel (tg_dashboard)
#
# Showcases: tg_dashboard, view_filter tabs (bet presets), counter (+/−), actions
# ═══════════════════════════════════════════════════════════════════════════════


async def _play_roulette(
    t: RouletteTable,
    choice: str,
    uid: int,
    c: Casino,
) -> ActionResult:
    if not c.pay(uid, t.bet):
        return ActionResult.stay(f"Not enough chips! Balance: {c.player(uid).chips}")

    winning = random.randint(0, 36)
    outcome = await c.intel.roulette_result(t.bet, choice, winning)

    if outcome.won:
        c.win(uid, outcome.payout)
    else:
        c.lose(uid, t.bet)

    return ActionResult.refresh(f"🎰 {outcome.narrative}")


@derive(tg_dashboard(
    command="roulette",
    key_node=UserId,
    description="Spin the wheel",
    order=2,
))
@dataclass
class RouletteTable:
    id: Annotated[int, Identity] = 0
    bet: int = 50
    balance: int = 1000

    @classmethod
    @view_filter("250", key="250")
    @view_filter("100", key="100")
    @view_filter("50", key="50")
    @query
    async def table(
        cls,
        uid: Annotated[int, compose.Node(UserId)],
        c: Annotated[Casino, compose.Node(CasinoNode)],
        bets: Annotated[BetStore, compose.Node(BetStoreNode)],
        filter_key: str = "",
    ) -> RouletteTable:
        bet = bets.resolve("roulette", uid, filter_key)
        balance = c.player(uid).chips
        return RouletteTable(id=1, bet=bet, balance=balance)

    @classmethod
    @format_card
    def render_table(cls, t: RouletteTable) -> str:
        return (
            f"🎰 Roulette\n"
            f"💰 Bet: {t.bet} chips\n"
            f"💵 Balance: {t.balance} chips"
        )

    @classmethod
    @action("➖", row=0)
    async def bet_down(
        cls,
        t: RouletteTable,
        uid: Annotated[int, compose.Node(UserId)],
        bets: Annotated[BetStore, compose.Node(BetStoreNode)],
    ) -> ActionResult:
        if t.bet <= 10:
            return ActionResult.stay("Min bet is 10")
        bets.adjust("roulette", uid, -10)
        return ActionResult.refresh()

    @classmethod
    @action("➕", row=0)
    async def bet_up(
        cls,
        t: RouletteTable,
        uid: Annotated[int, compose.Node(UserId)],
        bets: Annotated[BetStore, compose.Node(BetStoreNode)],
    ) -> ActionResult:
        if t.bet >= 1000:
            return ActionResult.stay("Max bet is 1000")
        bets.adjust("roulette", uid, 10)
        return ActionResult.refresh()

    @classmethod
    @action("🔴 Red", row=1)
    async def color_a(
        cls,
        t: RouletteTable,
        uid: Annotated[int, compose.Node(UserId)],
        c: Annotated[Casino, compose.Node(CasinoNode)],
    ) -> ActionResult:
        return await _play_roulette(t, "red", uid, c)

    @classmethod
    @action("⚫ Black", row=1)
    async def color_b(
        cls,
        t: RouletteTable,
        uid: Annotated[int, compose.Node(UserId)],
        c: Annotated[Casino, compose.Node(CasinoNode)],
    ) -> ActionResult:
        return await _play_roulette(t, "black", uid, c)

    @classmethod
    @action("🟢 Green", row=1)
    async def color_c(
        cls,
        t: RouletteTable,
        uid: Annotated[int, compose.Node(UserId)],
        c: Annotated[Casino, compose.Node(CasinoNode)],
    ) -> ActionResult:
        return await _play_roulette(t, "green", uid, c)


# ═══════════════════════════════════════════════════════════════════════════════
# /coinflip — heads or tails (tg_dashboard)
#
# Showcases: tg_dashboard, view_filter tabs (bet presets), counter (+/−), actions
# ═══════════════════════════════════════════════════════════════════════════════


async def _play_coinflip(
    t: CoinFlipTable,
    call: str,
    uid: int,
    c: Casino,
) -> ActionResult:
    if not c.pay(uid, t.bet):
        return ActionResult.stay(f"Not enough chips! Balance: {c.player(uid).chips}")

    landed = "heads" if random.random() < 0.5 else "tails"
    outcome = await c.intel.coinflip_result(t.bet, call, landed)

    if outcome.won:
        c.win(uid, outcome.payout)
    else:
        c.lose(uid, t.bet)

    return ActionResult.refresh(f"🪙 {outcome.narrative}")


@derive(tg_dashboard(
    command="coinflip",
    key_node=UserId,
    description="Heads or tails",
    order=3,
))
@dataclass
class CoinFlipTable:
    id: Annotated[int, Identity] = 0
    bet: int = 50
    balance: int = 1000

    @classmethod
    @view_filter("250", key="250")
    @view_filter("100", key="100")
    @view_filter("50", key="50")
    @query
    async def table(
        cls,
        uid: Annotated[int, compose.Node(UserId)],
        c: Annotated[Casino, compose.Node(CasinoNode)],
        bets: Annotated[BetStore, compose.Node(BetStoreNode)],
        filter_key: str = "",
    ) -> CoinFlipTable:
        bet = bets.resolve("coinflip", uid, filter_key)
        balance = c.player(uid).chips
        return CoinFlipTable(id=1, bet=bet, balance=balance)

    @classmethod
    @format_card
    def render_table(cls, t: CoinFlipTable) -> str:
        return (
            f"🪙 Coin Flip\n"
            f"💰 Bet: {t.bet} chips\n"
            f"💵 Balance: {t.balance} chips"
        )

    @classmethod
    @action("➖", row=0)
    async def bet_down(
        cls,
        t: CoinFlipTable,
        uid: Annotated[int, compose.Node(UserId)],
        bets: Annotated[BetStore, compose.Node(BetStoreNode)],
    ) -> ActionResult:
        if t.bet <= 10:
            return ActionResult.stay("Min bet is 10")
        bets.adjust("coinflip", uid, -10)
        return ActionResult.refresh()

    @classmethod
    @action("➕", row=0)
    async def bet_up(
        cls,
        t: CoinFlipTable,
        uid: Annotated[int, compose.Node(UserId)],
        bets: Annotated[BetStore, compose.Node(BetStoreNode)],
    ) -> ActionResult:
        if t.bet >= 1000:
            return ActionResult.stay("Max bet is 1000")
        bets.adjust("coinflip", uid, 10)
        return ActionResult.refresh()

    @classmethod
    @action("🪙 Heads", row=1)
    async def heads(
        cls,
        t: CoinFlipTable,
        uid: Annotated[int, compose.Node(UserId)],
        c: Annotated[Casino, compose.Node(CasinoNode)],
    ) -> ActionResult:
        return await _play_coinflip(t, "heads", uid, c)

    @classmethod
    @action("🪙 Tails", row=1)
    async def tails(
        cls,
        t: CoinFlipTable,
        uid: Annotated[int, compose.Node(UserId)],
        c: Annotated[Casino, compose.Node(CasinoNode)],
    ) -> ActionResult:
        return await _play_coinflip(t, "tails", uid, c)


# ═══════════════════════════════════════════════════════════════════════════════
# /cipher — crack the code (tg_flow)
#
# Showcases: TextInput with dynamic label, with_cancel
# ═══════════════════════════════════════════════════════════════════════════════


class CipherInput:
    """Dynamic-prompt text input that regenerates the cipher puzzle each render."""

    @property
    def prompt(self) -> str:
        return f"🔐 {_cipher_puzzle()}\n\nEnter the code word:"

    @property
    def needs_callback(self) -> bool:
        return False

    async def render(self, ctx: WidgetContext) -> tuple[str, InlineKeyboard | None]:
        return self.prompt, None

    async def handle_message(self, message: MessageCute, ctx: WidgetContext) -> Advance | Reject:
        match message.text:
            case Some(text):
                return Advance(value=text.strip(), summary=text.strip()[:30])
            case _:
                return Reject(message="Please send a text message.")

    async def handle_callback(self, value: str, ctx: WidgetContext) -> NoOp:
        return NoOp()


@derive(tg_flow(command="cipher", key_node=UserId, description="Crack the code", order=7).chain(
    with_cancel(), with_show_mode(ShowMode.EDIT),
))
@dataclass
class CipherChallenge:
    id: Annotated[int, Identity] = 0
    answer: Annotated[str, CipherInput()] = ""

    async def finish(
        self,
        uid: Annotated[int, compose.Node(UserId)],
        c: Annotated[Casino, compose.Node(CasinoNode)],
    ) -> Result[FinishResult, DomainError]:
        secret = _current_cipher()
        result = await c.intel.cipher_check(self.answer, secret)
        p = c.player(uid)

        if result.solved:
            c.win(uid, result.reward)
            p.reputation += 10
            return Ok(FinishResult.message(
                f"🔓 DECRYPTED\n\nCode word: {secret}\n"
                f"+{result.reward} chips, +10 rep\n\n"
                f"Balance: {p.chips} | Rep: {p.reputation}\n\n"
                "Try /cipher again!"))

        return Ok(FinishResult.message(
            f"❌ Wrong.\n\n{result.hint}\n\nTry /cipher again!"))


# ═══════════════════════════════════════════════════════════════════════════════
# /lounge — noir conversation (tg_flow + FlowWidget)
#
# Showcases: Inline with @options, custom FlowWidget, with_cancel, with_back
# ═══════════════════════════════════════════════════════════════════════════════


_HISTORY_SEP = "|||"


def _parse_conversation(ctx: WidgetContext) -> list[str]:
    """Extract conversation history from flow current_value (stored as delimited string)."""
    if isinstance(ctx.current_value, Some) and isinstance(ctx.current_value.value, str):
        raw = ctx.current_value.value
        if raw:
            return raw.split(_HISTORY_SEP)
    return list[str]()


class ConversationWidget:
    """Multi-turn noir conversation. Stay = keep talking, Advance = leave.

    Conversation history is stored as JSON in the flow field's current_value.
    Character name comes from flow_state (the 'character' field of the entity).
    """

    @property
    def prompt(self) -> str:
        return "🍸 The Lounge — say something or leave."

    @property
    def needs_callback(self) -> bool:
        return True

    async def render(self, ctx: WidgetContext) -> tuple[str, InlineKeyboard | None]:
        from telegrinder.tools.keyboard import InlineButton, InlineKeyboard

        kb = InlineKeyboard()
        kb.add(InlineButton(text="Leave the lounge", callback_data=ctx.callback_data("_leave")))
        kb.row()

        char = str(ctx.flow_state.get("character", "Someone"))
        desc = LOUNGE_CHARACTERS.get(char, "A mysterious stranger.")

        history = _parse_conversation(ctx)
        last_reply = history[-1] if history else desc

        return (
            f"🍸 The Lounge — {char}\n_{desc}_\n\n{last_reply}\n\nType a message or leave.",
            kb,
        )

    async def handle_message(self, message: MessageCute, ctx: WidgetContext) -> Stay | Reject:
        match message.text:
            case Some(text):
                pass
            case _:
                return Reject(message="Please send a text message.")

        char = str(ctx.flow_state.get("character", "Someone"))
        history = _parse_conversation(ctx)

        history.append(f"You: {text}")
        reply = await casino.intel.flirt(char, text, history)
        history.append(f"{char}: {reply}")

        return Stay(new_value=_HISTORY_SEP.join(history))

    async def handle_callback(self, value: str, ctx: WidgetContext) -> Stay | Advance:
        if value == "_leave":
            return Advance(value="done", summary="Left the lounge")
        history = _parse_conversation(ctx)
        return Stay(new_value=_HISTORY_SEP.join(history))


_conversation_widget = ConversationWidget()


@derive(tg_flow(command="lounge", key_node=UserId, description="Noir lounge", order=8).chain(
    with_cancel(), with_back(), with_show_mode(ShowMode.EDIT),
))
@dataclass
class NoirLounge:
    id: Annotated[int, Identity] = 0
    character: Annotated[str, Inline("🍸 Who catches your eye?", Vivienne="Vivienne", Marcel="Marcel", Anya="Anya", Jack="Jack")] = ""
    conversation: Annotated[str, _conversation_widget] = ""

    async def finish(self) -> Result[FinishResult, DomainError]:
        lines = len(self.conversation.split(_HISTORY_SEP)) if self.conversation else 0
        return Ok(FinishResult.message(
            f"You leave the lounge.\n\n"
            f"{lines} lines exchanged with {self.character}.\n"
            "The piano keeps playing. It always does."))


# ═══════════════════════════════════════════════════════════════════════════════
# /missions — spy mission board (tg_browse)
#
# Showcases: tg_browse, query, action, format_card, view_filter, tabs
# ═══════════════════════════════════════════════════════════════════════════════


@derive(tg_browse(
    command="missions",
    provider_node=MissionCatalogNode,
    key_node=UserId,
    page_size=3,
    description="Spy mission board",
    order=6,
))
@dataclass
class MissionBoard:
    id: Annotated[int, Identity] = 0

    @classmethod
    @view_filter("Hard", key="hard")
    @view_filter("Medium", key="medium")
    @view_filter("Easy", key="easy")
    @query
    async def missions(cls, filter_key: str = "") -> BrowseSource[Mission]:
        if filter_key:
            return ListBrowseSource([m for m in MISSIONS if m.difficulty == filter_key])
        return ListBrowseSource(list(MISSIONS))

    @classmethod
    @format_card
    def render_mission(cls, m: Mission) -> str:
        icon = {"easy": "🟢", "medium": "🟡", "hard": "🔴"}.get(m.difficulty, "⚪")
        return f"{icon} <b>{m.name}</b>\n{m.description}\nReward: {m.reward_range}"

    @classmethod
    @action("🕵️ Accept")
    async def accept(
        cls,
        mission: Mission,
        uid: Annotated[int, compose.Node(UserId)],
        c: Annotated[Casino, compose.Node(CasinoNode)],
    ) -> ActionResult:
        p = c.player(uid)
        outcome = await c.intel.spy_mission(mission.difficulty, p.codename)

        if outcome.success:
            p.chips += outcome.reward
            p.total_won += outcome.reward
            p.missions_done += 1
            p.reputation += {"easy": 5, "medium": 15, "hard": 40}.get(mission.difficulty, 5)
            return ActionResult.stay(
                f"✅ {outcome.narrative}\n+{outcome.reward} chips | Rep: {p.reputation}")

        return ActionResult.stay(f"❌ {outcome.narrative}\nMission failed. No reward.")


# ═══════════════════════════════════════════════════════════════════════════════
# CasinoMenu — main commands (methods)
#
# Showcases: tg_command, tg_delegate, methods pattern, compose.Node DI
# ═══════════════════════════════════════════════════════════════════════════════


@derive(methods)
@dataclass
class CasinoMenu:
    id: Annotated[int, Identity] = 0

    @classmethod
    @tg_command("start", description="Welcome to Casino Royale", order=1)
    async def start(cls, uid: Annotated[int, compose.Node(UserId)]) -> Result[str, DomainError]:
        return Ok(
            "🎰 <b>Casino Royale</b>\n\n"
            "Welcome, agent. Your cover: high-roller.\n\n"
            "/roulette — spin the wheel\n"
            "/coinflip — heads or tails\n"
            "/slots — pull the lever\n"
            "/missions — spy work\n"
            "/cipher — crack codes\n"
            "/lounge — a drink and conversation\n"
            "/wallet — your chips\n"
            "/profile — agent dossier\n"
            "/settings — player settings")

    @classmethod
    @tg_command("wallet", description="Check your chips", order=4)
    async def wallet(
        cls,
        uid: Annotated[int, compose.Node(UserId)],
        c: Annotated[Casino, compose.Node(CasinoNode)],
    ) -> Result[str, DomainError]:
        p = c.player(uid)
        return Ok(
            f"💰 <b>Wallet</b>\n\n"
            f"Chips:      {p.chips}\n"
            f"Total won:  {p.total_won}\n"
            f"Total lost: {p.total_lost}\n"
            f"Games:      {p.games_played}")

    @classmethod
    @tg_command("profile", description="Agent dossier", order=5)
    async def profile(
        cls,
        uid: Annotated[int, compose.Node(UserId)],
        c: Annotated[Casino, compose.Node(CasinoNode)],
    ) -> Result[str, DomainError]:
        p = c.player(uid)
        return Ok(
            f"🕵️ <b>Agent Dossier</b>\n\n"
            f"Codename:   {p.codename}\n"
            f"Rank:       {c.rank(uid)}\n"
            f"Reputation: {p.reputation}\n"
            f"Missions:   {p.missions_done}\n"
            f"Chips:      {p.chips}\n"
            f"Win rate:   {c.win_rate(uid)}")

    @classmethod
    @tg_command("slots", description="Pull the lever", order=3)
    async def slots(
        cls,
        uid: Annotated[int, compose.Node(UserId)],
        c: Annotated[Casino, compose.Node(CasinoNode)],
    ) -> Result[str, DomainError]:
        bet = 25
        if not c.pay(uid, bet):
            return Ok(f"Not enough chips. Balance: {c.player(uid).chips}")

        r1, r2, r3, outcome = await c.intel.slots_result(bet)
        if outcome.won:
            c.win(uid, outcome.payout)
        else:
            c.lose(uid, bet)

        return Ok(
            f"🎰 <b>Slots</b> ({bet} chips)\n\n"
            f"  [ {r1} | {r2} | {r3} ]\n\n"
            f"{outcome.narrative}\n\n"
            f"Balance: {c.player(uid).chips} chips")

    @classmethod
    @tg_command("codename", description="Set spy codename", order=9)
    async def set_codename(
        cls,
        uid: Annotated[int, compose.Node(UserId)],
        c: Annotated[Casino, compose.Node(CasinoNode)],
        name: Annotated[str, tg.CommandArg()],
    ) -> Result[str, DomainError]:
        p = c.player(uid)
        old = p.codename
        p.codename = name
        return Ok(f"Codename changed: {old} → {name}")

    @classmethod
    @tg_command("help", description="All commands", order=10)
    async def help_cmd(cls) -> Result[str, DomainError]:
        from emergent.wire.compile.targets.telegrinder import generate_help_from_command_rules
        return Ok(generate_help_from_command_rules(
            app, template="/{name} — {description}", header="🎰 <b>Casino Royale</b>\n\n"))

    @classmethod
    @tg_delegate(Command("leaderboard"), description="Top agents", order=11)
    async def leaderboard(
        cls,
        message: MessageCute,
        c: Annotated[Casino, compose.Node(CasinoNode)],
    ) -> None:
        top = c.leaderboard()
        if not top:
            await message.answer("No players yet. /start to join.")
            return

        lines = ["🏆 <b>Leaderboard</b>\n"]
        for i, (_, p) in enumerate(top, 1):
            medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(i, f"{i}.")
            lines.append(f"{medal} {p.codename} — {p.chips} chips (rep {p.reputation})")

        await message.answer("\n".join(lines))


# ═══════════════════════════════════════════════════════════════════════════════
# /settings — player settings (tg_settings)
#
# Showcases: tg_settings, on_save, format_settings, TextInput, Confirm, Counter
# ═══════════════════════════════════════════════════════════════════════════════


@derive(tg_settings(command="settings", key_node=UserId, description="Player settings", order=9))
@dataclass
class PlayerSettings:
    codename: Annotated[str, TextInput("Enter your codename:")]
    notifications: Annotated[bool, Confirm("Enable game notifications?")]
    preferred_bet: Annotated[int, Counter("Default bet:", min=10, max=1000, step=10, default=50)]

    @classmethod
    @query
    async def load(
        cls,
        uid: Annotated[int, compose.Node(UserId)],
        c: Annotated[Casino, compose.Node(CasinoNode)],
    ) -> PlayerSettings:
        p = c.player(uid)
        return PlayerSettings(
            codename=p.codename,
            notifications=True,
            preferred_bet=50,
        )

    @classmethod
    @on_save
    async def save(
        cls,
        settings: PlayerSettings,
        uid: Annotated[int, compose.Node(UserId)],
        c: Annotated[Casino, compose.Node(CasinoNode)],
    ) -> None:
        p = c.player(uid)
        p.codename = settings.codename

    @classmethod
    @format_settings
    def render(cls, s: PlayerSettings) -> str:
        notif = "On" if s.notifications else "Off"
        return (
            f"Settings\n\n"
            f"Codename: {s.codename}\n"
            f"Notifications: {notif}\n"
            f"Default bet: {s.preferred_bet} chips"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Build & run
# ═══════════════════════════════════════════════════════════════════════════════

app = build_application_from_decorated(
    CasinoMenu, RouletteTable, CoinFlipTable,
    CipherChallenge, NoirLounge, MissionBoard,
    PlayerSettings,
)

from emergent.wire.compile.targets import telegrinder as tg_compile  # noqa: E402

dispatch = tg_compile.compile(app)

if __name__ == "__main__":
    from telegrinder import API, Telegrinder, Token

    n = endpoint_count(app)
    print(f"\n  🎰 Casino Royale Bot")
    print(f"  {n} endpoints derived from 7 entities\n")
    print("  /start      — welcome")
    print("  /roulette   — spin the wheel")
    print("  /coinflip   — heads or tails")
    print("  /slots      — pull the lever")
    print("  /missions   — spy mission board")
    print("  /cipher     — crack the code")
    print("  /lounge     — noir conversation")
    print("  /wallet     — check chips")
    print("  /profile    — agent dossier")
    print("  /codename   — set spy name")
    print("  /settings   — player settings")
    print("  /leaderboard — top agents")
    print("  /help       — all commands\n")

    import os

    token = os.environ.get("BOT_TOKEN", "")
    if not token:
        print("  Set BOT_TOKEN=... to run\n")
    else:
        bot = Telegrinder(API(Token(token)), dispatch=dispatch)
        bot.run_forever()

"""Game handlers — generated via: emergent-meta new handler."""

import random

from kungfu import Result, Ok, Error

from roulette.auth.ops import AuthUser
from roulette.game.ops import GetBalance, PlaceBet
from roulette.game.domain import BetResult, parse_bet, REDS, BLACKS
from roulette.game.store import GameStore


async def handle_get_balance(
    _op: GetBalance, auth_user: AuthUser, game_store: GameStore
) -> Result[int, str]:
    """Handle GetBalance — return current balance for authenticated user."""
    return Ok(game_store.get_balance(auth_user))


async def handle_place_bet(
    op: PlaceBet, auth_user: AuthUser, game_store: GameStore
) -> Result[BetResult, str]:
    """Handle PlaceBet — validate, spin, compute payout."""
    try:
        bet = parse_bet(op.bet)
    except ValueError as exc:
        return Error(str(exc))

    balance = game_store.get_balance(auth_user)
    if op.amount <= 0:
        return Error("amount must be positive")
    if op.amount > balance:
        return Error(f"insufficient balance: have {balance}, need {op.amount}")

    number = random.randint(0, 36)  # noqa: S311

    payout = 0
    if isinstance(bet, str):
        # color bet
        if bet == "red" and number in REDS:
            payout = op.amount * 2
        elif bet == "black" and number in BLACKS:
            payout = op.amount * 2
    elif bet == number:
        # exact number bet
        payout = op.amount * 36

    new_balance = balance - op.amount + payout
    game_store.update_balance(auth_user, new_balance)

    return Ok(
        BetResult(
            won=payout > 0,
            number=number,
            payout=payout,
            new_balance=new_balance,
        )
    )

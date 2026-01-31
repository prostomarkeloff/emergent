"""Game handlers."""

import random

from kungfu import Result, Ok, Error

from roulette.auth.ops import AuthUser
from roulette.game.ops import GetBalance, PlaceBet
from roulette.game.domain import BetResult, parse_bet, REDS, BLACKS
from roulette.game.store import GameStore


async def handle_get_balance(
    _op: GetBalance, auth_user: AuthUser, game_store: GameStore
) -> Result[int, str]:
    """GetBalance → return current balance."""
    balance = await game_store.get_balance(auth_user)
    return Ok(balance)


async def handle_place_bet(
    op: PlaceBet, auth_user: AuthUser, game_store: GameStore
) -> Result[BetResult, str]:
    """PlaceBet → validate, debit, spin, credit if won."""
    # Parse bet
    try:
        bet = parse_bet(op.bet)
    except ValueError as exc:
        return Error(str(exc))

    if op.amount <= 0:
        return Error("amount must be positive")

    # Atomic debit (checks balance inside transaction)
    bet_result = await game_store.place_bet(auth_user, op.amount, op.bet)
    match bet_result:
        case Error(e):
            return Error(e)
        case Ok(balance_after_bet):
            pass

    # Spin
    number = random.randint(0, 36)  # noqa: S311

    # Calculate payout
    payout = 0
    if isinstance(bet, str):
        if bet == "red" and number in REDS:
            payout = op.amount * 2
        elif bet == "black" and number in BLACKS:
            payout = op.amount * 2
    elif bet == number:
        payout = op.amount * 36

    # Credit winnings
    if payout > 0:
        new_balance = await game_store.record_win(auth_user, payout, op.bet)
    else:
        new_balance = balance_after_bet

    return Ok(BetResult(
        won=payout > 0,
        number=number,
        payout=payout,
        new_balance=new_balance,
    ))

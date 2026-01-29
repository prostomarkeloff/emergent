"""Entry point for roulette — smoke test via runner."""

import asyncio

from kungfu import Ok, Error

from roulette.auth.ops import Register, Login, Authenticate
from roulette.auth.runner import auth_runner
from roulette.game.ops import GetBalance, PlaceBet
from roulette.game.runner import game_runner
from roulette.auth.ops import AuthUser


async def main() -> None:
    # Register
    result = await auth_runner.run(Register(login="alice", password="secret"))
    match result:
        case Ok(token):
            print(f"Registered, token: {token[:8]}...")
        case Error(err):
            print(f"Register error: {err}")
            return

    # Login
    result = await auth_runner.run(Login(login="alice", password="secret"))
    match result:
        case Ok(token):
            print(f"Logged in, token: {token[:8]}...")
        case Error(err):
            print(f"Login error: {err}")
            return

    # Authenticate
    auth_result = await auth_runner.run(Authenticate(token=token))
    match auth_result:
        case Ok(user):
            print(f"Authenticated as: {user}")
        case Error(err):
            print(f"Auth error: {err}")
            return

    # Get balance (inject AuthUser into scope)
    balance_result = await game_runner.run(GetBalance(), scope_extras={AuthUser: user})
    match balance_result:
        case Ok(balance):
            print(f"Balance: {balance}")
        case Error(err):
            print(f"Balance error: {err}")

    # Place bet
    bet_result = await game_runner.run(
        PlaceBet(bet="red", amount=10),
        scope_extras={AuthUser: user},
    )
    match bet_result:
        case Ok(br):
            won = "Won" if br.won else "Lost"
            print(
                f"{won}! Number: {br.number}, Payout: {br.payout}, Balance: {br.new_balance}"
            )
        case Error(err):
            print(f"Bet error: {err}")


if __name__ == "__main__":
    asyncio.run(main())

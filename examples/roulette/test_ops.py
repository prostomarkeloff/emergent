"""Tests for roulette — layered auth + game runners."""

import pytest
from emergent import ops as O
from kungfu import Ok, Error

from roulette.auth.ops import Register, Login, Authenticate, AuthUser
from roulette.auth.handlers import handle_register, handle_login, handle_authenticate
from roulette.auth.store import AuthStore
from roulette.game.ops import GetBalance, PlaceBet
from roulette.game.handlers import handle_get_balance, handle_place_bet
from roulette.game.store import GameStore


@pytest.fixture
def auth_store() -> AuthStore:
    return AuthStore()


@pytest.fixture
def game_store() -> GameStore:
    return GameStore()


@pytest.fixture
def auth_runner(auth_store: AuthStore, game_store: GameStore):
    return (
        O.ops()
        .on(Register, handle_register)
        .on(Login, handle_login)
        .on(Authenticate, handle_authenticate)
        .compile()
        .inject(AuthStore, auth_store)
        .inject(GameStore, game_store)
    )


@pytest.fixture
def game_runner(game_store: GameStore):
    return (
        O.ops()
        .on(GetBalance, handle_get_balance)
        .on(PlaceBet, handle_place_bet)
        .compile()
        .inject(GameStore, game_store)
    )


# ── Auth tests ───────────────────────────────────────────────────────────


def test_register_op_creation():
    op = Register(login="alice", password="secret")
    assert op.login == "alice"


@pytest.mark.asyncio
async def test_register(auth_runner):
    result = await auth_runner.run(Register(login="alice", password="secret"))
    assert isinstance(result, Ok)


@pytest.mark.asyncio
async def test_register_duplicate(auth_runner):
    await auth_runner.run(Register(login="alice", password="secret"))
    result = await auth_runner.run(Register(login="alice", password="other"))
    assert isinstance(result, Error)


@pytest.mark.asyncio
async def test_login(auth_runner):
    await auth_runner.run(Register(login="alice", password="secret"))
    result = await auth_runner.run(Login(login="alice", password="secret"))
    assert isinstance(result, Ok)


@pytest.mark.asyncio
async def test_login_bad_password(auth_runner):
    await auth_runner.run(Register(login="alice", password="secret"))
    result = await auth_runner.run(Login(login="alice", password="wrong"))
    assert isinstance(result, Error)


@pytest.mark.asyncio
async def test_authenticate(auth_runner):
    reg_result = await auth_runner.run(Register(login="alice", password="secret"))
    match reg_result:
        case Ok(token):
            auth_result = await auth_runner.run(Authenticate(token=token))
            match auth_result:
                case Ok(user):
                    assert user == "alice"
                case _:
                    pytest.fail(f"Expected Ok, got {auth_result}")
        case _:
            pytest.fail(f"Expected Ok, got {reg_result}")


# ── Game tests ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_balance(game_runner, game_store: GameStore):
    game_store.ensure_balance("alice")
    result = await game_runner.run(
        GetBalance(), scope_extras={AuthUser: AuthUser("alice")}
    )
    match result:
        case Ok(balance):
            assert balance == 100
        case _:
            pytest.fail(f"Expected Ok, got {result}")


@pytest.mark.asyncio
async def test_place_bet(game_runner, game_store: GameStore):
    game_store.ensure_balance("alice")
    result = await game_runner.run(
        PlaceBet(bet="red", amount=10),
        scope_extras={AuthUser: AuthUser("alice")},
    )
    match result:
        case Ok(bet_result):
            assert bet_result.new_balance >= 0
        case Error(e):
            pytest.fail(f"Expected Ok, got Error: {e}")


@pytest.mark.asyncio
async def test_place_bet_insufficient(game_runner, game_store: GameStore):
    game_store.ensure_balance("alice")
    result = await game_runner.run(
        PlaceBet(bet="red", amount=999),
        scope_extras={AuthUser: AuthUser("alice")},
    )
    assert isinstance(result, Error)
